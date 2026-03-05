#!/usr/bin/env python3
import base64
import io
import re
import json, os, shlex, shutil, signal, subprocess, sys, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

# FIX: Input Validation Patterns (Command Injection Prevention)
# Erlaubte Key-Kombinationen für xdotool
ALLOWED_KEY_PATTERNS = re.compile(r'^[a-zA-Z0-9+_\-]+$')
# Maximale Text-Länge für type_text
MAX_TYPE_TEXT_LENGTH = 5000
# Gefährliche Zeichen für Shell-Injection
DANGEROUS_CHARS = re.compile(r'[;&|`$(){}]')

HOST = "127.0.0.1"
PORT = 8092

# --- helpers ---------------------------------------------------------------

def run(cmd, timeout=10, check=True):
    """
    run shell command (list or string). returns (rc, out, err)
    """
    if isinstance(cmd, str):
        cmd = shlex.split(cmd)
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout, text=True)
    if check and p.returncode != 0:
        raise RuntimeError(f"cmd failed rc={p.returncode} cmd={cmd} err={p.stderr.strip()}")
    return p.returncode, p.stdout, p.stderr

def json_read(handler):
    n = int(handler.headers.get("Content-Length", "0"))
    raw = handler.rfile.read(n) if n else b"{}"
    try:
        return json.loads(raw.decode("utf-8"))
    except Exception:
        return None

def json_write(handler, code, obj):
    data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    handler.send_response(code)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    try:
        handler.wfile.write(data)
    except (BrokenPipeError, ConnectionResetError):
        pass

def bin_write(handler, code, content_type, blob: bytes):
    handler.send_response(code)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(len(blob)))
    handler.end_headers()
    try:
        handler.wfile.write(blob)
    except (BrokenPipeError, ConnectionResetError):
        pass

def ensure_x11():
    disp = os.environ.get("DISPLAY", "")
    if not disp:
        raise RuntimeError("DISPLAY is not set. Start this daemon in the same user X11 session.")
    return disp

def _wid_dec_to_hex(wid_dec_str: str) -> str:
    wid_dec_str = (wid_dec_str or "").strip()
    if not wid_dec_str:
        return ""
    try:
        return hex(int(wid_dec_str))
    except Exception:
        return wid_dec_str

# --- desktop state ---------------------------------------------------------

def list_windows():
    """
    returns list of windows with id, desktop, pid, x,y,w,h, host, title
    """
    ensure_x11()
    if not shutil.which("wmctrl"):
        raise RuntimeError("wmctrl not found in PATH. Install with: sudo apt install wmctrl")
    rc, out, _ = run(["wmctrl", "-lpG"], timeout=5, check=False)
    wins = []
    for line in out.splitlines():
        parts = line.split(None, 8)
        if len(parts) < 9:
            continue
        wid_hex, desk, pid, x, y, w, h, host, title = parts
        wins.append({
            "wid": wid_hex,
            "desktop": int(desk),
            "pid": int(pid),
            "x": int(x), "y": int(y), "w": int(w), "h": int(h),
            "host": host,
            "title": title,
        })
    return wins

def active_window():
    ensure_x11()
    if not shutil.which("xdotool"):
        raise RuntimeError("xdotool not found in PATH. Install with: sudo apt install xdotool")
    rc, wid_dec, _ = run(["xdotool", "getactivewindow"], timeout=2, check=False)
    wid_dec = (wid_dec or "").strip()
    wid_hex = _wid_dec_to_hex(wid_dec)
    name = ""
    if wid_dec:
        rc, name, _ = run(["xdotool", "getwindowname", wid_dec], timeout=2, check=False)
        name = (name or "").strip()
    return {"wid": wid_hex, "wid_dec": wid_dec, "title": name}

# --- screenshots -----------------------------------------------------------

def screenshot_png(monitor=1):
    """
    monitor: 1 = primary monitor in most setups. 0 would be "all" in mss.
    returns PNG bytes
    """
    ensure_x11()
    try:
        import mss
        from PIL import Image
    except Exception as e:
        raise RuntimeError("missing deps for screenshots. Install: python3 -m pip install --user mss pillow") from e

    with mss.mss() as sct:
        # mss monitors: 0=all, 1=first, 2=second...
        mon_idx = int(monitor)
        if mon_idx < 0 or mon_idx >= len(sct.monitors):
            mon_idx = 1 if len(sct.monitors) > 1 else 0
        mon = sct.monitors[mon_idx]
        shot = sct.grab(mon)
        img = Image.frombytes("RGB", shot.size, shot.rgb)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

def screenshot_b64(monitor=1):
    png = screenshot_png(monitor=monitor)
    return base64.b64encode(png).decode("ascii")

# --- actions ---------------------------------------------------------------

def open_url(url):
    """Open URL (FIX: mit Command Injection Prevention)."""
    u = urlparse(url)
    if u.scheme not in ("http", "https"):
        raise RuntimeError("only http/https allowed")
    # FIX: Prüfe auf gefährliche Zeichen in URL
    if DANGEROUS_CHARS.search(url):
        raise RuntimeError("URL contains dangerous characters")
    # FIX: Maximale URL-Länge
    if len(url) > 2048:
        raise RuntimeError("URL too long")
    if not shutil.which("xdg-open"):
        raise RuntimeError("xdg-open not found in PATH")
    run(["xdg-open", url], timeout=3, check=False)
    return {"opened": True, "url": url}

def focus_window(title_contains=None, wid=None):
    ensure_x11()
    if not shutil.which("wmctrl"):
        raise RuntimeError("wmctrl not found in PATH. Install with: sudo apt install wmctrl")
    if wid:
        run(["wmctrl", "-ia", wid], timeout=3, check=False)
        return {"focused": True, "wid": wid}
    if title_contains:
        for w in list_windows():
            if title_contains.lower() in (w.get("title","").lower()):
                run(["wmctrl", "-ia", w["wid"]], timeout=3, check=False)
                return {"focused": True, "wid": w["wid"], "title": w["title"]}
        return {"focused": False, "reason": "no_match"}
    raise RuntimeError("need wid or title_contains")

def type_text(text, delay_ms=8):
    """Type text via xdotool (FIX: mit Input Validation)."""
    ensure_x11()
    # FIX: Längen-Limit
    if len(text) > MAX_TYPE_TEXT_LENGTH:
        raise RuntimeError(f"Text too long (max {MAX_TYPE_TEXT_LENGTH} chars)")
    if not shutil.which("xdotool"):
        raise RuntimeError("xdotool not found in PATH. Install with: sudo apt install xdotool")
    # delay_ms muss Integer sein
    delay_ms = max(1, min(100, int(delay_ms)))
    run(["xdotool", "type", "--delay", str(delay_ms), text], timeout=10, check=False)
    return {"typed": True, "len": len(text)}

def key_combo(combo):
    """Press key combo via xdotool (FIX: mit Whitelist Validation)."""
    ensure_x11()
    # FIX: Nur erlaubte Key-Kombinationen
    if not ALLOWED_KEY_PATTERNS.match(combo):
        raise RuntimeError(f"Invalid key combo: {combo}")
    # FIX: Maximale Länge
    if len(combo) > 50:
        raise RuntimeError("Key combo too long")
    if not shutil.which("xdotool"):
        raise RuntimeError("xdotool not found in PATH. Install with: sudo apt install xdotool")
    run(["xdotool", "key", combo], timeout=3, check=False)
    return {"key": combo, "ok": True}

def click(button=1):
    ensure_x11()
    if not shutil.which("xdotool"):
        raise RuntimeError("xdotool not found in PATH. Install with: sudo apt install xdotool")
    run(["xdotool", "click", str(int(button))], timeout=3, check=False)
    return {"clicked": True, "button": int(button)}

# --- http server -----------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        return

    def do_GET(self):
        # allow query params
        path, _, qs = self.path.partition("?")
        q = parse_qs(qs)

        if path == "/health":
            json_write(self, 200, {"ok": True})
            return

        if path == "/desktop/state":
            try:
                st = {
                    "ok": True,
                    "active": active_window(),
                    "windows": list_windows(),
                }
                json_write(self, 200, st)
            except Exception as e:
                json_write(self, 500, {"ok": False, "error": "state_failed", "detail": str(e)})
            return

        # raw png
        if path == "/desktop/screenshot.png":
            try:
                monitor = int(q.get("monitor", ["1"])[0])
                png = screenshot_png(monitor=monitor)
                bin_write(self, 200, "image/png", png)
            except Exception as e:
                json_write(self, 500, {"ok": False, "error": "screenshot_failed", "detail": str(e)})
            return

        # base64 json (handy for text-only pipelines)
        if path == "/desktop/screenshot":
            try:
                monitor = int(q.get("monitor", ["1"])[0])
                b64 = screenshot_b64(monitor=monitor)
                json_write(self, 200, {"ok": True, "monitor": monitor, "png_b64": b64})
            except Exception as e:
                json_write(self, 500, {"ok": False, "error": "screenshot_failed", "detail": str(e)})
            return

        json_write(self, 404, {"ok": False, "error": "not_found"})

    def do_POST(self):
        payload = json_read(self)
        if payload is None:
            json_write(self, 400, {"ok": False, "error": "invalid_json"})
            return

        if self.path != "/desktop/action":
            json_write(self, 404, {"ok": False, "error": "not_found"})
            return

        try:
            act = payload.get("type", "")
            if act == "open_url":
                res = open_url(payload["url"])
            elif act == "focus_window":
                res = focus_window(payload.get("title_contains"), payload.get("wid"))
            elif act == "type":
                res = type_text(payload.get("text",""), payload.get("delay_ms", 8))
            elif act == "key":
                res = key_combo(payload["combo"])
            elif act == "click":
                res = click(payload.get("button", 1))
            else:
                json_write(self, 400, {"ok": False, "error": "unknown_action", "detail": act})
                return

            json_write(self, 200, {"ok": True, "result": res})
        except KeyError as e:
            json_write(self, 400, {"ok": False, "error": "missing_field", "detail": str(e)})
        except Exception as e:
            json_write(self, 500, {"ok": False, "error": "action_failed", "detail": str(e)})

_httpd = None

def _shutdown_handler(signum, frame):
    """Handle SIGTERM/SIGINT for graceful shutdown."""
    print(f"desktopd received signal {signum}, shutting down...")
    if _httpd:
        _httpd.shutdown()
    sys.exit(0)

def main():
    global _httpd

    # Register signal handlers for graceful shutdown
    signal.signal(signal.SIGTERM, _shutdown_handler)
    signal.signal(signal.SIGINT, _shutdown_handler)

    print(f"desktopd listening on http://{HOST}:{PORT}")
    _httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    _httpd.daemon_threads = True
    _httpd.serve_forever()

if __name__ == "__main__":
    from config.logging_config import setup_file_logging
    setup_file_logging("desktopd")
    main()

