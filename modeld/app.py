#!/usr/bin/env python3
import json
import time
import threading
import urllib.request
import urllib.error
import socket
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from datetime import datetime, timezone

HOST = "127.0.0.1"
PORT = 8090

# Backends: llama-server instances (already running)
BACKENDS = {
    "deepseek_r1_8b_q6k": "http://127.0.0.1:8101",
}

# Limit in-flight requests per backend to avoid overload / connection churn
MAX_INFLIGHT_PER_BACKEND = 4
_backend_sema = {k: threading.Semaphore(MAX_INFLIGHT_PER_BACKEND) for k in BACKENDS.keys()}

_last_active_model_lock = threading.Lock()
_last_active_model = None

def now() -> str:
    return datetime.now(timezone.utc).isoformat()

def http_get_json(url: str, timeout_s: int = 2) -> dict:
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", errors="replace")
        except Exception:
            body = "<failed to read body>"
        raise RuntimeError(f"HTTPError {e.code} {e.reason} body={body[:500]}") from None
    except socket.timeout:
        raise RuntimeError(f"GET timeout after {timeout_s}s") from None
    except ConnectionError as e:
        raise RuntimeError(f"GET connection error: {e}") from None
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Invalid JSON response: {e}") from None

def http_post_json(url: str, payload: dict, timeout_s: int) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", errors="replace")
        except Exception:
            body = "<failed to read body>"
        raise RuntimeError(f"HTTPError {e.code} {e.reason} body={body[:500]}") from None
    except socket.timeout:
        raise RuntimeError(f"POST timeout after {timeout_s}s") from None
    except ConnectionError as e:
        raise RuntimeError(f"POST connection error: {e}") from None
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Invalid JSON response: {e}") from None

def backend_health() -> dict:
    out = {}
    for mid, base in BACKENDS.items():
        try:
            body = http_get_json(f"{base}/health", timeout_s=2)
            out[mid] = {"ok": True, "status": 200, "body": body}
        except Exception as e:
            out[mid] = {"ok": False, "error": str(e)}
    return out

def _set_active(model_id: str):
    global _last_active_model
    with _last_active_model_lock:
        _last_active_model = model_id

def _get_active():
    with _last_active_model_lock:
        return _last_active_model

def infer_via_backend(model_id: str, prompt: str, temperature: float, max_tokens: int, timeout_s: int) -> dict:
    if model_id not in BACKENDS:
        raise RuntimeError(f"unknown model_id: {model_id}")

    base = BACKENDS[model_id]
    sem = _backend_sema[model_id]

    acquired = sem.acquire(timeout=max(1, min(10, int(timeout_s))))
    if not acquired:
        raise TimeoutError(f"backend busy: {model_id}")

    try:
        # OpenAI-compatible llama-server endpoint
        payload = {
            "model": model_id,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": float(temperature),
            "max_tokens": int(max_tokens),
        }

        # Small retry loop for transient "connection refused" (service restart)
        last_err = None
        for attempt in range(6):
            try:
                resp = http_post_json(
                    f"{base}/v1/chat/completions",
                    payload,
                    timeout_s=max(5, int(timeout_s)),
                )
                _set_active(model_id)
                try:
                    text = resp["choices"][0]["message"]["content"]
                except Exception:
                    text = json.dumps(resp, ensure_ascii=False)
                return {"ok": True, "model_id": model_id, "text": text}
            except urllib.error.URLError as e:
                last_err = e
                msg = str(e)
                # retry only on "refused"
                if "Connection refused" in msg or getattr(e, "reason", None) == ConnectionRefusedError:
                    time.sleep(0.2 * (attempt + 1))
                    continue
                raise
            except Exception as e:
                last_err = e
                raise
        raise RuntimeError(f"backend connect failed after retries: {last_err}")
    finally:
        sem.release()

class Handler(BaseHTTPRequestHandler):
    def _json(self, code: int, obj: dict):
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        try:
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            return

    def do_GET(self):
        if self.path == "/health":
            self._json(200, {
                "ok": True,
                "ts": now(),
                "active_model": _get_active(),
                "backends": BACKENDS,
                "backend_health": backend_health(),
            })
            return
        if self.path == "/models":
            self._json(200, {"models": list(BACKENDS.keys()), "active_model": _get_active()})
            return
        self._json(404, {"error": "not_found"})

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw.decode("utf-8"))
        except Exception:
            self._json(400, {"error": "invalid_json"})
            return

        try:
            if self.path == "/infer":
                model_id = payload.get("model_id", "")
                prompt = payload.get("prompt", "")
                temperature = float(payload.get("temperature", 0.2))
                max_tokens = int(payload.get("max_tokens", 256))
                timeout_s = int(payload.get("timeout_s", 300))
                self._json(200, infer_via_backend(model_id, prompt, temperature, max_tokens, timeout_s))
                return

            self._json(404, {"error": "not_found"})
        except (socket.timeout, TimeoutError) as e:
            self._json(504, {"ok": False, "error": "timeout", "detail": str(e)})
        except Exception as e:
            self._json(500, {"ok": False, "error": "infer_failed", "detail": str(e)})

def main():
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    httpd.daemon_threads = True
    print(f"modeld listening on http://{HOST}:{PORT}")
    httpd.serve_forever()

if __name__ == "__main__":
    main()

