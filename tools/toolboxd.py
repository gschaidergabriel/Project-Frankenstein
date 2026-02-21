#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
toolboxd: Local Tools API (stdlib only)

Provides:
- /health
- /fs/list, /fs/read, /fs/move, /fs/copy, /fs/delete, /fs/backup
- /desktop/open_url (proxy to desktopd), /desktop/screenshot (png b64)
- /sys/summary, /sys/mem, /sys/disk, /sys/temps, /sys/cpu, /sys/os, /sys/services_user
- /sys/drivers - kernel module versions and loaded drivers
- /sys/usb - USB device enumeration with details
- /sys/network - network interfaces with IP, MAC, throughput
- /sys/hardware_deep - BIOS, CPU cache, GPU features, PCI devices
- /app/search, /app/list, /app/open, /app/close, /app/allow, /app/capabilities
- /steam/list, /steam/search, /steam/launch, /steam/close
- /email/unread, /email/list, /email/read, /email/check_new, /email/delete, /email/spam
- /calendar/today, /calendar/week, /calendar/events, /calendar/event, /calendar/create, /calendar/delete
- /contacts/list, /contacts/search, /contacts/get, /contacts/create, /contacts/delete
- /notes/create, /notes/list, /notes/search, /notes/get, /notes/update, /notes/delete
- /todo/create, /todo/list, /todo/search, /todo/complete, /todo/delete, /todo/due

Security model:
- READ endpoints allowed inside MUTABLE_ROOTS or RO_ROOTS
- MUTATING endpoints allowed ONLY inside MUTABLE_ROOTS
"""

from __future__ import annotations

import base64
import json
import os
import platform
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ---------------- config ----------------

try:
    from config.paths import AICORE_ROOT as _TOOLBOX_SRC_ROOT, DB_DIR, TOOLS_DIR as _TOOLBOX_TOOLS_DIR
    _TOOLBOX_PROJECT_ROOT = str(_TOOLBOX_SRC_ROOT.parent.parent)
except ImportError:
    _TOOLBOX_SRC_ROOT = Path(__file__).resolve().parents[1]  # tools/ -> opt/aicore
    _TOOLBOX_PROJECT_ROOT = str(_TOOLBOX_SRC_ROOT.parent.parent)  # opt/aicore -> opt -> aicore
    DB_DIR = Path.home() / ".local" / "share" / "frank" / "db"
    DB_DIR.mkdir(parents=True, exist_ok=True)
    _TOOLBOX_TOOLS_DIR = _TOOLBOX_SRC_ROOT / "tools"

HOST = os.environ.get("AICORE_TOOLBOX_HOST", "127.0.0.1")
PORT = int(os.environ.get("AICORE_TOOLBOX_PORT", "8096"))

# Allow mutation only inside these roots
# Default: home + aicore tree
MUTABLE_ROOTS = [
    p.strip() for p in os.environ.get(
        "AICORE_TOOLBOX_ROOTS",
        f"{Path.home()}:{_TOOLBOX_PROJECT_ROOT}:/tmp",
    ).split(":")
    if p.strip()
]

# Allow read-only access also inside these roots (system introspection)
RO_ROOTS = [
    p.strip() for p in os.environ.get(
        "AICORE_TOOLBOX_RO_ROOTS",
        "/proc:/sys:/etc:/var/log",
    ).split(":")
    if p.strip()
]

BACKUP_ROOT = Path(os.environ.get("AICORE_TOOLBOX_BACKUP_ROOT", str(Path.home() / "aicore_backups")))

# Database directory for persistent storage — set above via config.paths or fallback

# Ensure critical directories exist at import time
def _ensure_directories():
    """Ensure critical directories exist, creating them if necessary."""
    for dir_path in [DB_DIR, BACKUP_ROOT]:
        try:
            dir_path.mkdir(parents=True, exist_ok=True)
        except PermissionError:
            # Log but don't fail - directory might be created later
            pass
        except Exception:
            pass

_ensure_directories()

DESKTOP_ACTION_URL = os.environ.get("AICORE_DESKTOP_ACTION_URL", "http://127.0.0.1:8092/desktop/action").rstrip("/")
DEFAULT_BROWSER_OPEN_TIMEOUT = float(os.environ.get("AICORE_BROWSER_OPEN_TIMEOUT", "4.0"))

# Cache (system stats) to reduce load
_CACHE: Dict[str, Tuple[float, Any]] = {}
CACHE_TTL_SUMMARY = float(os.environ.get("AICORE_TOOLBOX_SYS_TTL", "1.0"))

# ---------------- helpers ----------------

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def _json_dumps(obj: Any) -> bytes:
    return json.dumps(obj, ensure_ascii=False).encode("utf-8")

def _which(cmd: str) -> Optional[str]:
    return shutil.which(cmd)

def _run(cmd: List[str], timeout: float = 5.0) -> Tuple[int, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        out = (p.stdout or "") + (p.stderr or "")
        return p.returncode, out.strip()
    except Exception as e:
        return 1, repr(e)

def _resolve(p: str) -> Path:
    return Path(p).expanduser().resolve()

def _within(path: Path, roots: List[str]) -> bool:
    for r in roots:
        try:
            rr = Path(r).expanduser().resolve()
        except Exception:
            continue
        if rr == path or rr in path.parents:
            return True
    return False

def _allow_read(path: Path) -> bool:
    return _within(path, MUTABLE_ROOTS) or _within(path, RO_ROOTS)

def _allow_write(path: Path) -> bool:
    if not _within(path, MUTABLE_ROOTS):
        return False
    # Protect critical paths from deletion/overwrite even inside MUTABLE_ROOTS
    if _is_protected(path):
        return False
    return True

# Paths that must never be deleted or overwritten via the API.
# Sub-paths within these ARE writable (e.g. ~/.config/frank/new_file is fine)
# but the root path itself and direct children of critical dirs are protected.
_PROTECTED_PATHS = None  # lazily built

def _get_protected_paths():
    global _PROTECTED_PATHS
    if _PROTECTED_PATHS is None:
        _home = Path.home().resolve()
        _PROTECTED_PATHS = {
            _home,                          # entire home dir
            _home / ".ssh",
            _home / ".gnupg",
            _home / ".config",
            _home / ".local",
            _home / ".bashrc",
            _home / ".profile",
            _home / ".bash_profile",
            _home / ".mozilla",
            _home / ".thunderbird",
            _home / ".pki",
            _home / "aicore",               # aicore installation root
            _home / "aicore" / "opt",
            _home / "aicore" / "opt" / "aicore",
            Path("/"),
            Path("/home"),
            Path("/etc"),
            Path("/usr"),
            Path("/var"),
            Path("/boot"),
            Path("/bin"),
            Path("/sbin"),
            Path("/lib"),
        }
    return _PROTECTED_PATHS

def _is_protected(path: Path) -> bool:
    """Return True if path is a protected location that must not be deleted."""
    resolved = path.resolve()
    return resolved in _get_protected_paths()

def _cache_get(key: str, ttl: float) -> Optional[Any]:
    v = _CACHE.get(key)
    if not v:
        return None
    ts, val = v
    if (time.time() - ts) <= ttl:
        return val
    return None

def _cache_set(key: str, val: Any) -> None:
    _CACHE[key] = (time.time(), val)

# ---------------- entity session logs ----------------

_ENTITY_LOG_DIR = Path.home() / ".local" / "share" / "frank" / "logs"
_ENTITY_PREFIX_MAP = {
    "kairos": "mirror_kairos",
    "hibbert": "therapist_hibbert",
    "raven": "companion_raven",
    "atlas": "atlas_atlas",
    "echo": "muse_echo",
}
# Reverse map: prefix -> display name
_ENTITY_NAMES = {v: k for k, v in _ENTITY_PREFIX_MAP.items()}


def _entity_log_files(entity: str = "all") -> List[Path]:
    """Return sorted (newest-first) entity log JSON files."""
    log_dir = _ENTITY_LOG_DIR
    if not log_dir.is_dir():
        return []
    if entity and entity != "all" and entity in _ENTITY_PREFIX_MAP:
        prefix = _ENTITY_PREFIX_MAP[entity]
        files = sorted(log_dir.glob(f"{prefix}_*.json"), reverse=True)
    else:
        # All entities
        files = []
        for prefix in _ENTITY_PREFIX_MAP.values():
            files.extend(log_dir.glob(f"{prefix}_*.json"))
        files.sort(key=lambda f: f.stat().st_mtime, reverse=True)
    return files


def entity_sessions_list(entity: str = "all", limit: int = 10) -> Dict[str, Any]:
    """List entity sessions with summary previews."""
    files = _entity_log_files(entity)[:limit]
    sessions = []
    for f in files:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            summary = data.get("summary", "")
            sessions.append({
                "session_id": data.get("session_id", f.stem),
                "agent": data.get("agent", ""),
                "timestamp": data.get("timestamp", ""),
                "turns": data.get("turns", 0),
                "exit_reason": data.get("exit_reason", ""),
                "initial_mood": data.get("initial_mood"),
                "final_mood": data.get("final_mood"),
                "mood_delta": data.get("mood_delta"),
                "summary_preview": summary[:200] + ("..." if len(summary) > 200 else ""),
                "topics": data.get("topics", []),
            })
        except Exception:
            continue
    return {"ok": True, "sessions": sessions, "count": len(sessions)}


def entity_session_read(session_id: str, include_history: bool = True) -> Dict[str, Any]:
    """Read a specific entity session by session_id."""
    log_dir = _ENTITY_LOG_DIR
    if not log_dir.is_dir():
        return {"ok": False, "error": "log_directory_not_found"}
    # Find the file matching this session_id
    for f in log_dir.iterdir():
        if not f.name.endswith(".json"):
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            if data.get("session_id") == session_id:
                result = {
                    "ok": True,
                    "session_id": data.get("session_id"),
                    "agent": data.get("agent"),
                    "timestamp": data.get("timestamp"),
                    "turns": data.get("turns"),
                    "exit_reason": data.get("exit_reason"),
                    "initial_mood": data.get("initial_mood"),
                    "final_mood": data.get("final_mood"),
                    "mood_delta": data.get("mood_delta"),
                    "summary": data.get("summary"),
                    "topics": data.get("topics", []),
                    "observations": data.get("observations", []),
                }
                if include_history:
                    result["history"] = data.get("history", [])
                return result
        except Exception:
            continue
    return {"ok": False, "error": f"session_not_found: {session_id}"}


def entity_sessions_search(query: str, entity: str = "all", limit: int = 5) -> Dict[str, Any]:
    """Search across entity session logs for a keyword."""
    query_lower = query.lower()
    files = _entity_log_files(entity)
    matches = []
    for f in files:
        if len(matches) >= limit:
            break
        try:
            raw = f.read_text(encoding="utf-8")
            data = json.loads(raw)
            # Search in summary and history text
            found_in = []
            summary = data.get("summary", "")
            if query_lower in summary.lower():
                found_in.append("summary")
            history = data.get("history", [])
            matching_turns = []
            for turn in history:
                text = turn.get("text", "")
                if query_lower in text.lower():
                    found_in.append(f"{turn.get('speaker', '?')}")
                    # Extract context snippet around match
                    idx = text.lower().index(query_lower)
                    start = max(0, idx - 80)
                    end = min(len(text), idx + len(query) + 80)
                    snippet = ("..." if start > 0 else "") + text[start:end] + ("..." if end < len(text) else "")
                    matching_turns.append({"speaker": turn.get("speaker"), "snippet": snippet})
            if found_in:
                matches.append({
                    "session_id": data.get("session_id", f.stem),
                    "agent": data.get("agent", ""),
                    "timestamp": data.get("timestamp", ""),
                    "topics": data.get("topics", []),
                    "found_in": list(set(found_in)),
                    "matching_turns": matching_turns[:3],
                    "summary_preview": summary[:200] + ("..." if len(summary) > 200 else ""),
                })
        except Exception:
            continue
    return {"ok": True, "results": matches, "count": len(matches), "query": query}


# ---------------- fs ops ----------------

def fs_list(path: str, recursive: bool = False, max_entries: int = 2000, include_hidden: bool = False) -> Dict[str, Any]:
    p = _resolve(path)
    if not p.exists():
        return {"ok": False, "error": "not_found", "path": str(p)}
    if not _allow_read(p):
        return {"ok": False, "error": "forbidden", "path": str(p)}

    out: List[Dict[str, Any]] = []
    n = 0

    def add_item(pp: Path) -> None:
        nonlocal n
        if n >= max_entries:
            return
        name = pp.name
        if not include_hidden and name.startswith("."):
            return
        try:
            st = pp.stat()
            out.append({
                "path": str(pp),
                "name": name,
                "is_dir": pp.is_dir(),
                "size": st.st_size,
                "mtime": st.st_mtime,
            })
            n += 1
        except Exception:
            return

    if p.is_file():
        add_item(p)
        return {"ok": True, "base": str(p), "items": out, "truncated": False}

    if not recursive:
        for child in sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
            add_item(child)
            if n >= max_entries:
                break
        return {"ok": True, "base": str(p), "items": out, "truncated": n >= max_entries}

    # recursive walk
    for root, dirs, files in os.walk(str(p)):
        rootp = Path(root)
        # filter hidden dirs if needed
        if not include_hidden:
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            files = [f for f in files if not f.startswith(".")]
        for d in sorted(dirs):
            add_item(rootp / d)
            if n >= max_entries:
                return {"ok": True, "base": str(p), "items": out, "truncated": True}
        for f in sorted(files):
            add_item(rootp / f)
            if n >= max_entries:
                return {"ok": True, "base": str(p), "items": out, "truncated": True}

    return {"ok": True, "base": str(p), "items": out, "truncated": False}

def fs_read(path: str, max_bytes: int = 256_000) -> Dict[str, Any]:
    p = _resolve(path)
    if not p.exists() or not p.is_file():
        return {"ok": False, "error": "not_found", "path": str(p)}
    if not _allow_read(p):
        return {"ok": False, "error": "forbidden", "path": str(p)}
    try:
        data = p.read_bytes()
        truncated = False
        if len(data) > max_bytes:
            data = data[:max_bytes]
            truncated = True
        # best effort text
        try:
            text = data.decode("utf-8")
            kind = "text"
            b64 = None
        except Exception:
            kind = "binary"
            text = None
            b64 = base64.b64encode(data).decode("ascii")
        return {
            "ok": True,
            "path": str(p),
            "kind": kind,
            "truncated": truncated,
            "text": text,
            "b64": b64,
            "bytes": len(data),
        }
    except Exception as e:
        return {"ok": False, "error": "read_failed", "detail": str(e), "path": str(p)}

def fs_write(path: str, content: str, overwrite: bool = False) -> Dict[str, Any]:
    p = _resolve(path)
    if not _allow_write(p):
        return {"ok": False, "error": "forbidden", "path": str(p)}
    if p.exists() and not overwrite:
        return {"ok": False, "error": "exists", "path": str(p)}
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return {"ok": True, "path": str(p), "bytes": len(content.encode("utf-8"))}
    except Exception as e:
        return {"ok": False, "error": "write_failed", "detail": str(e), "path": str(p)}

def _ensure_parent(dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)

def fs_move(src: str, dst: str, overwrite: bool = False) -> Dict[str, Any]:
    sp = _resolve(src)
    dp = _resolve(dst)
    if not sp.exists():
        return {"ok": False, "error": "src_not_found", "src": str(sp)}
    if not _allow_write(sp) or not _allow_write(dp):
        return {"ok": False, "error": "forbidden", "src": str(sp), "dst": str(dp)}
    if dp.exists() and not overwrite:
        return {"ok": False, "error": "dst_exists", "dst": str(dp)}
    try:
        _ensure_parent(dp)
        if dp.exists() and overwrite:
            if dp.is_dir():
                shutil.rmtree(dp)
            else:
                dp.unlink()
        shutil.move(str(sp), str(dp))
        return {"ok": True, "src": str(sp), "dst": str(dp)}
    except Exception as e:
        return {"ok": False, "error": "move_failed", "detail": str(e), "src": str(sp), "dst": str(dp)}

def fs_copy(src: str, dst: str, overwrite: bool = False) -> Dict[str, Any]:
    sp = _resolve(src)
    dp = _resolve(dst)
    if not sp.exists():
        return {"ok": False, "error": "src_not_found", "src": str(sp)}
    if not _allow_read(sp) or not _allow_write(dp):
        return {"ok": False, "error": "forbidden", "src": str(sp), "dst": str(dp)}
    if dp.exists() and not overwrite:
        return {"ok": False, "error": "dst_exists", "dst": str(dp)}
    try:
        _ensure_parent(dp)
        if dp.exists() and overwrite:
            if dp.is_dir():
                shutil.rmtree(dp)
            else:
                dp.unlink()
        if sp.is_dir():
            shutil.copytree(str(sp), str(dp))
        else:
            shutil.copy2(str(sp), str(dp))
        return {"ok": True, "src": str(sp), "dst": str(dp)}
    except Exception as e:
        return {"ok": False, "error": "copy_failed", "detail": str(e), "src": str(sp), "dst": str(dp)}

def fs_delete(path: str) -> Dict[str, Any]:
    p = _resolve(path)
    if not p.exists():
        return {"ok": False, "error": "not_found", "path": str(p)}
    if _is_protected(p):
        return {"ok": False, "error": "protected_path",
                "detail": f"Cannot delete protected path: {p}", "path": str(p)}
    if not _allow_write(p):
        return {"ok": False, "error": "forbidden", "path": str(p)}
    try:
        if p.is_dir():
            shutil.rmtree(p)
        else:
            p.unlink()
        return {"ok": True, "path": str(p)}
    except Exception as e:
        return {"ok": False, "error": "delete_failed", "detail": str(e), "path": str(p)}

def fs_backup(
    src_paths: List[str],
    backup_dir: Optional[str] = None,
    mode: str = "copy",  # copy|move
    keep_structure: bool = True,
) -> Dict[str, Any]:
    if mode not in ("copy", "move"):
        return {"ok": False, "error": "bad_mode", "mode": mode}

    bdir = _resolve(backup_dir) if backup_dir else BACKUP_ROOT.resolve()
    if not _allow_write(bdir):
        # backup dir must be writable root; allow inside MUTABLE_ROOTS by default
        # if user wants elsewhere, add to AICORE_TOOLBOX_ROOTS
        return {"ok": False, "error": "backup_dir_forbidden", "backup_dir": str(bdir)}

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    target_root = bdir / ts
    target_root.mkdir(parents=True, exist_ok=True)

    results: List[Dict[str, Any]] = []
    for sp_s in src_paths:
        sp = _resolve(sp_s)
        if not sp.exists():
            results.append({"ok": False, "error": "src_not_found", "src": str(sp)})
            continue
        # backups are a mutation only if mode=move; copy is read->write
        if mode == "move":
            if not _allow_write(sp):
                results.append({"ok": False, "error": "forbidden_move_src", "src": str(sp)})
                continue
        else:
            if not _allow_read(sp):
                results.append({"ok": False, "error": "forbidden_read_src", "src": str(sp)})
                continue

        try:
            if keep_structure:
                # preserve absolute-ish structure under target_root
                rel = str(sp).lstrip(os.sep).replace(":", "_")
                dp = target_root / rel
            else:
                dp = target_root / sp.name

            _ensure_parent(dp)

            if mode == "copy":
                if sp.is_dir():
                    shutil.copytree(str(sp), str(dp))
                else:
                    shutil.copy2(str(sp), str(dp))
            else:
                shutil.move(str(sp), str(dp))

            results.append({"ok": True, "src": str(sp), "dst": str(dp), "mode": mode})
        except Exception as e:
            results.append({"ok": False, "error": "backup_failed", "detail": str(e), "src": str(sp)})

    return {"ok": True, "backup_root": str(target_root), "results": results}
# ---------------- desktop ops ----------------

def _http_post_json(url: str, payload: Dict[str, Any], timeout_s: float = 5.0) -> Dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
        return json.loads(raw) if raw else {}

def desktop_open_url(url: str) -> Dict[str, Any]:
    # proxy to desktopd (existing component)
    try:
        res = _http_post_json(DESKTOP_ACTION_URL, {"type": "open_url", "url": url}, timeout_s=DEFAULT_BROWSER_OPEN_TIMEOUT)
        return {"ok": bool(res.get("ok", True)), "upstream": res}
    except Exception as e:
        return {"ok": False, "error": "open_url_failed", "detail": str(e)}

def _capture_png_bytes() -> Tuple[bool, str, Optional[bytes]]:
    """
    Try multiple screenshot backends.
    Returns (ok, backend, png_bytes).
    """
    tmp = Path("/tmp") / f"aicore_screen_{int(time.time()*1000)}.png"

    # 1) ImageMagick import -> stdout
    if _which("import"):
        try:
            p = subprocess.run(["import", "-window", "root", "png:-"], capture_output=True, timeout=3.0)
            if p.returncode == 0 and p.stdout:
                return True, "import", p.stdout
        except Exception:
            pass

    # 2) grim (wayland)
    if _which("grim"):
        try:
            rc, out = _run(["grim", str(tmp)], timeout=3.0)
            if rc == 0 and tmp.exists():
                data = tmp.read_bytes()
                tmp.unlink(missing_ok=True)
                return True, "grim", data
        except Exception:
            pass

    # 3) gnome-screenshot
    if _which("gnome-screenshot"):
        try:
            rc, out = _run(["gnome-screenshot", "-f", str(tmp)], timeout=4.0)
            if rc == 0 and tmp.exists():
                data = tmp.read_bytes()
                tmp.unlink(missing_ok=True)
                return True, "gnome-screenshot", data
        except Exception:
            pass

    # 4) scrot
    if _which("scrot"):
        try:
            rc, out = _run(["scrot", str(tmp)], timeout=4.0)
            if rc == 0 and tmp.exists():
                data = tmp.read_bytes()
                tmp.unlink(missing_ok=True)
                return True, "scrot", data
        except Exception:
            pass

    return False, "none", None

def desktop_screenshot() -> Dict[str, Any]:
    ok, backend, data = _capture_png_bytes()
    if not ok or not data:
        return {
            "ok": False,
            "error": "screenshot_unavailable",
            "detail": "No screenshot backend found (need: import/grim/gnome-screenshot/scrot).",
        }
    b64 = base64.b64encode(data).decode("ascii")
    return {"ok": True, "backend": backend, "png_b64": b64, "bytes": len(data), "ts": now_iso()}

# ---------------- system ops ----------------

def _read_text(path: str) -> str:
    return Path(path).read_text(encoding="utf-8", errors="replace")

def sys_os() -> Dict[str, Any]:
    info: Dict[str, Any] = {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "uname": " ".join(platform.uname()),
    }
    p = Path("/etc/os-release")
    if p.exists():
        d: Dict[str, str] = {}
        for line in _read_text(str(p)).splitlines():
            line = line.strip()
            if not line or "=" not in line:
                continue
            k, v = line.split("=", 1)
            d[k] = v.strip().strip('"')
        info["os_release"] = d
    return {"ok": True, "ts": now_iso(), "os": info}

def sys_cpu() -> Dict[str, Any]:
    model = ""
    mhz_vals: List[float] = []
    cores = 0
    try:
        txt = _read_text("/proc/cpuinfo")
        for line in txt.splitlines():
            if line.startswith("model name"):
                if not model:
                    model = line.split(":", 1)[1].strip()
            if line.startswith("cpu MHz"):
                try:
                    mhz_vals.append(float(line.split(":", 1)[1].strip()))
                except Exception:
                    pass
            if line.startswith("processor"):
                cores += 1
    except Exception:
        pass
    mhz = round(sum(mhz_vals) / len(mhz_vals), 1) if mhz_vals else None
    return {"ok": True, "ts": now_iso(), "cpu": {"model": model or None, "cores": cores or None, "mhz_avg": mhz}}

def sys_mem() -> Dict[str, Any]:
    mi: Dict[str, int] = {}
    try:
        for line in _read_text("/proc/meminfo").splitlines():
            m = re.match(r"^(\w+):\s+(\d+)\s+kB", line)
            if m:
                mi[m.group(1)] = int(m.group(2))
    except Exception:
        return {"ok": False, "error": "meminfo_unavailable"}

    total = mi.get("MemTotal", 0)
    avail = mi.get("MemAvailable", 0)
    used = max(0, total - avail)
    swap_total = mi.get("SwapTotal", 0)
    swap_free = mi.get("SwapFree", 0)
    swap_used = max(0, swap_total - swap_free)
    swap_percent = round((swap_used / swap_total) * 100, 1) if swap_total > 0 else 0.0
    return {
        "ok": True,
        "ts": now_iso(),
        "mem_kb": {"total": total, "used": used, "available": avail},
        "swap_kb": {"total": swap_total, "used": swap_used, "free": swap_free},
        "swap_percent": swap_percent,
    }

def sys_uptime_load() -> Dict[str, Any]:
    up_s = None
    la = None
    try:
        up_s = float(_read_text("/proc/uptime").split()[0])
    except Exception:
        pass
    try:
        parts = _read_text("/proc/loadavg").split()
        la = {"1": float(parts[0]), "5": float(parts[1]), "15": float(parts[2])}
    except Exception:
        pass
    return {"ok": True, "ts": now_iso(), "uptime_s": up_s, "loadavg": la}

def sys_disk(paths: Optional[List[str]] = None) -> Dict[str, Any]:
    if not paths:
        # keep it practical: home + aicore + /
        paths = [str(Path.home()), _TOOLBOX_PROJECT_ROOT, "/"]
    items: List[Dict[str, Any]] = []
    for p in paths:
        try:
            rp = _resolve(p)
            if not _allow_read(rp):
                items.append({"path": str(rp), "ok": False, "error": "forbidden"})
                continue
            du = shutil.disk_usage(str(rp))
            percent_used = round((du.used / du.total) * 100, 1) if du.total > 0 else 0.0
            items.append({
                "path": str(rp),
                "ok": True,
                "total": du.total,
                "used": du.used,
                "free": du.free,
                "percent_used": percent_used,
            })
        except Exception as e:
            items.append({"path": p, "ok": False, "error": str(e)})
    return {"ok": True, "ts": now_iso(), "disks": items}

def sys_temps() -> Dict[str, Any]:
    sensors: List[Dict[str, Any]] = []

    # thermal zones
    tz = Path("/sys/class/thermal")
    if tz.exists():
        for z in sorted(tz.glob("thermal_zone*")):
            try:
                tfile = z / "temp"
                if not tfile.exists():
                    continue
                temp_m = int(tfile.read_text().strip())
                t_c = temp_m / 1000.0
                ttype = None
                tf = z / "type"
                if tf.exists():
                    ttype = tf.read_text(encoding="utf-8", errors="replace").strip()
                sensors.append({"source": "thermal_zone", "name": z.name, "type": ttype, "temp_c": t_c})
            except Exception:
                continue

    # hwmon temps
    hw = Path("/sys/class/hwmon")
    if hw.exists():
        for h in sorted(hw.glob("hwmon*")):
            name = None
            try:
                nf = h / "name"
                if nf.exists():
                    name = nf.read_text(encoding="utf-8", errors="replace").strip()
            except Exception:
                name = None
            for inp in sorted(h.glob("temp*_input")):
                try:
                    temp_m = int(inp.read_text().strip())
                    t_c = temp_m / 1000.0
                    label = None
                    lf = inp.with_name(inp.name.replace("_input", "_label"))
                    if lf.exists():
                        label = lf.read_text(encoding="utf-8", errors="replace").strip()
                    sensors.append({
                        "source": "hwmon",
                        "hwmon": h.name,
                        "chip": name,
                        "sensor": inp.name,
                        "label": label,
                        "temp_c": t_c,
                    })
                except Exception:
                    continue

    max_temp = None
    if sensors:
        try:
            max_temp = max(s.get("temp_c") for s in sensors if isinstance(s.get("temp_c"), (int, float)))
        except Exception:
            max_temp = None

    return {"ok": True, "ts": now_iso(), "max_temp_c": max_temp, "sensors": sensors}

def sys_pressure() -> Dict[str, Any]:
    """Read PSI (Pressure Stall Information) from /proc/pressure/{cpu,memory,io}."""
    pressure: Dict[str, Any] = {}
    for resource in ("cpu", "memory", "io"):
        p = Path(f"/proc/pressure/{resource}")
        if not p.exists():
            continue
        try:
            txt = p.read_text(encoding="utf-8", errors="replace").strip()
            entry: Dict[str, Any] = {"raw": txt}
            for line in txt.splitlines():
                # Lines like: some avg10=0.00 avg60=0.00 avg300=0.00 total=0
                parts = line.split()
                if not parts:
                    continue
                kind = parts[0]  # "some" or "full"
                vals: Dict[str, Any] = {}
                for kv in parts[1:]:
                    if "=" in kv:
                        k, v = kv.split("=", 1)
                        try:
                            vals[k] = float(v)
                        except ValueError:
                            vals[k] = v
                entry[kind] = vals
            pressure[resource] = entry
        except Exception:
            continue

    return {"ok": True, "ts": now_iso(), "pressure": pressure}

def sys_disk_health() -> Dict[str, Any]:
    """Read NVMe/SMART disk health data via smartctl if available."""
    smartctl_bin = _which("smartctl")
    if not smartctl_bin:
        return {"ok": False, "error": "smartctl_not_available", "detail": "Install smartmontools for disk health data"}

    devices: List[Dict[str, Any]] = []

    # Discover devices via smartctl --scan -j
    rc, out = _run([smartctl_bin, "--scan", "-j"], timeout=10.0)
    if rc != 0 and not out.strip():
        return {"ok": False, "error": "smartctl_scan_failed", "detail": out}

    device_list: List[str] = []
    try:
        scan_data = json.loads(out)
        for dev in scan_data.get("devices", []):
            name = dev.get("name")
            if name:
                device_list.append(name)
    except Exception:
        # Fallback: try common device paths
        for candidate in ["/dev/sda", "/dev/nvme0", "/dev/nvme0n1"]:
            if Path(candidate).exists():
                device_list.append(candidate)

    for dev_path in device_list:
        rc, out = _run([smartctl_bin, "-j", "-a", dev_path], timeout=15.0)
        if not out.strip():
            devices.append({"device": dev_path, "ok": False, "error": "no_output"})
            continue
        try:
            data = json.loads(out)
            entry: Dict[str, Any] = {
                "device": dev_path,
                "ok": True,
                "model_name": data.get("model_name"),
                "serial_number": data.get("serial_number"),
                "firmware_version": data.get("firmware_version"),
                "smart_status": data.get("smart_status", {}).get("passed"),
                "temperature": data.get("temperature", {}).get("current"),
                "power_on_hours": data.get("power_on_time", {}).get("hours"),
            }
            # NVMe-specific fields
            nvme_health = data.get("nvme_smart_health_information_log", {})
            if nvme_health:
                entry["nvme_health"] = {
                    "percentage_used": nvme_health.get("percentage_used"),
                    "available_spare": nvme_health.get("available_spare"),
                    "media_errors": nvme_health.get("media_errors"),
                    "power_cycles": nvme_health.get("power_cycles"),
                    "unsafe_shutdowns": nvme_health.get("unsafe_shutdowns"),
                }
            devices.append(entry)
        except Exception as e:
            devices.append({"device": dev_path, "ok": False, "error": str(e)})

    return {"ok": True, "ts": now_iso(), "devices": devices}

def sys_services_user(pattern: str = "aicore-*") -> Dict[str, Any]:
    # systemd user services (read-only)
    rc, out = _run(["systemctl", "--user", "list-units", "--type=service", "--all", pattern, "--no-legend", "--no-pager"], timeout=3.0)
    items: List[Dict[str, Any]] = []
    if rc != 0:
        return {"ok": False, "error": "systemctl_failed", "detail": out}
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        # UNIT LOAD ACTIVE SUB DESCRIPTION...
        parts = line.split(None, 4)
        if len(parts) < 4:
            continue
        unit, load, active, sub = parts[:4]
        desc = parts[4] if len(parts) >= 5 else ""
        items.append({"unit": unit, "load": load, "active": active, "sub": sub, "desc": desc})
    return {"ok": True, "ts": now_iso(), "services": items}

def sys_summary() -> Dict[str, Any]:
    cached = _cache_get("sys_summary", CACHE_TTL_SUMMARY)
    if cached is not None:
        return cached

    d: Dict[str, Any] = {"ok": True, "ts": now_iso()}
    d["os"] = sys_os().get("os")
    d["cpu"] = sys_cpu().get("cpu")
    d["mem"] = sys_mem()
    d["uptime_load"] = sys_uptime_load()
    d["disk"] = sys_disk().get("disks")
    d["temps"] = sys_temps()
    d["services_user"] = sys_services_user().get("services")

    _cache_set("sys_summary", d)
    return d


# ---------------- deep system ops ----------------

def sys_drivers() -> Dict[str, Any]:
    """
    Get loaded kernel modules with versions from /proc/modules and modinfo.
    Returns real driver data, not guesses.
    """
    modules: List[Dict[str, Any]] = []

    try:
        # Read loaded modules from /proc/modules
        modules_txt = _read_text("/proc/modules")
        for line in modules_txt.splitlines():
            parts = line.split()
            if len(parts) < 6:
                continue
            name = parts[0]
            size = int(parts[1]) if parts[1].isdigit() else 0
            used_by = parts[3].strip("-").split(",") if parts[3] != "-" else []
            state = parts[4]  # Live, Loading, Unloading

            mod_info: Dict[str, Any] = {
                "name": name,
                "size_bytes": size,
                "state": state,
                "used_by": [u for u in used_by if u],
            }

            # Get detailed info via modinfo
            rc, out = _run(["modinfo", "-F", "version", name], timeout=2.0)
            if rc == 0 and out.strip():
                mod_info["version"] = out.strip()

            rc, out = _run(["modinfo", "-F", "description", name], timeout=2.0)
            if rc == 0 and out.strip():
                mod_info["description"] = out.strip()

            rc, out = _run(["modinfo", "-F", "author", name], timeout=2.0)
            if rc == 0 and out.strip():
                mod_info["author"] = out.strip()

            rc, out = _run(["modinfo", "-F", "license", name], timeout=2.0)
            if rc == 0 and out.strip():
                mod_info["license"] = out.strip()

            modules.append(mod_info)
    except Exception as e:
        return {"ok": False, "error": "modules_read_failed", "detail": str(e)}

    # Also get kernel version
    kernel_ver = None
    try:
        kernel_ver = _read_text("/proc/version").strip()
    except Exception:
        pass

    return {
        "ok": True,
        "ts": now_iso(),
        "kernel": kernel_ver,
        "module_count": len(modules),
        "modules": modules,
    }


def sys_usb() -> Dict[str, Any]:
    """
    Enumerate USB devices with details from /sys/bus/usb/devices and lsusb.
    """
    devices: List[Dict[str, Any]] = []

    # Method 1: Parse /sys/bus/usb/devices
    usb_path = Path("/sys/bus/usb/devices")
    if usb_path.exists():
        for dev_dir in sorted(usb_path.iterdir()):
            if not dev_dir.is_dir():
                continue
            # Skip interface entries (contain ":")
            if ":" in dev_dir.name:
                continue

            dev_info: Dict[str, Any] = {"bus_id": dev_dir.name}

            def read_attr(name: str) -> Optional[str]:
                f = dev_dir / name
                if f.exists():
                    try:
                        return f.read_text(encoding="utf-8", errors="replace").strip()
                    except Exception:
                        pass
                return None

            # Read device attributes
            vid = read_attr("idVendor")
            pid = read_attr("idProduct")
            if vid and pid:
                dev_info["vendor_id"] = vid
                dev_info["product_id"] = pid

            manufacturer = read_attr("manufacturer")
            product = read_attr("product")
            serial = read_attr("serial")

            if manufacturer:
                dev_info["manufacturer"] = manufacturer
            if product:
                dev_info["product"] = product
            if serial:
                dev_info["serial"] = serial

            # Speed and class
            speed = read_attr("speed")
            if speed:
                dev_info["speed_mbps"] = speed

            dev_class = read_attr("bDeviceClass")
            if dev_class:
                dev_info["device_class"] = dev_class

            # Power state
            power_state = read_attr("power/runtime_status")
            if power_state:
                dev_info["power_state"] = power_state

            # Only add if it has meaningful info
            if vid or product or manufacturer:
                devices.append(dev_info)

    # Method 2: Also try lsusb for additional info
    lsusb_devices: List[Dict[str, str]] = []
    if _which("lsusb"):
        rc, out = _run(["lsusb"], timeout=3.0)
        if rc == 0:
            for line in out.splitlines():
                # Bus 001 Device 002: ID 1d6b:0003 Linux Foundation 3.0 root hub
                m = re.match(r"Bus (\d+) Device (\d+): ID ([0-9a-f]{4}):([0-9a-f]{4})\s*(.*)", line, re.I)
                if m:
                    lsusb_devices.append({
                        "bus": m.group(1),
                        "device": m.group(2),
                        "vendor_id": m.group(3),
                        "product_id": m.group(4),
                        "description": m.group(5).strip(),
                    })

    return {
        "ok": True,
        "ts": now_iso(),
        "device_count": len(devices),
        "devices": devices,
        "lsusb": lsusb_devices,
    }


def sys_usb_storage() -> Dict[str, Any]:
    """List USB storage devices with mount status via lsblk."""
    devices: List[Dict[str, Any]] = []
    if _which("lsblk"):
        rc, out = _run(
            ["lsblk", "-Jpo", "NAME,SIZE,FSTYPE,LABEL,MOUNTPOINT,TRAN,VENDOR,MODEL,TYPE"],
            timeout=5.0,
        )
        if rc == 0:
            import json as _json
            try:
                data = _json.loads(out)
                for dev in data.get("blockdevices", []):
                    if dev.get("tran") != "usb":
                        continue
                    # Top-level disk
                    disk_info = {
                        "device": dev.get("name", ""),
                        "size": dev.get("size", ""),
                        "vendor": (dev.get("vendor") or "").strip(),
                        "model": (dev.get("model") or "").strip(),
                        "partitions": [],
                    }
                    children = dev.get("children", [])
                    if children:
                        for part in children:
                            disk_info["partitions"].append({
                                "device": part.get("name", ""),
                                "size": part.get("size", ""),
                                "fstype": part.get("fstype") or "",
                                "label": part.get("label") or "",
                                "mountpoint": part.get("mountpoint") or "",
                            })
                    else:
                        # Disk without partition table (formatted directly)
                        disk_info["partitions"].append({
                            "device": dev.get("name", ""),
                            "size": dev.get("size", ""),
                            "fstype": dev.get("fstype") or "",
                            "label": dev.get("label") or "",
                            "mountpoint": dev.get("mountpoint") or "",
                        })
                    devices.append(disk_info)
            except Exception as e:
                return {"ok": False, "error": f"lsblk parse: {e}"}
    return {"ok": True, "ts": now_iso(), "devices": devices, "count": len(devices)}


def _resolve_usb_device(identifier: str) -> Optional[str]:
    """Resolve a label, mountpoint, or device path to a block device path."""
    if identifier.startswith("/dev/"):
        return identifier
    # Try to find by label or mountpoint via lsblk
    if _which("lsblk"):
        rc, out = _run(
            ["lsblk", "-Jpo", "NAME,LABEL,MOUNTPOINT,TRAN,TYPE"],
            timeout=5.0,
        )
        if rc == 0:
            import json as _json
            try:
                data = _json.loads(out)
                ident_lower = identifier.lower()
                for dev in data.get("blockdevices", []):
                    for part in dev.get("children", [dev]):
                        label = (part.get("label") or "").lower()
                        mp = (part.get("mountpoint") or "").lower()
                        name = part.get("name", "")
                        if label and ident_lower in label:
                            return name
                        if mp and ident_lower in mp:
                            return name
            except Exception:
                pass
    return None


def sys_usb_mount(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Mount a USB storage device via udisksctl (no root needed)."""
    device = str(payload.get("device", payload.get("label", ""))).strip()
    if not device:
        return {"ok": False, "error": "missing_device", "msg": "No device specified."}

    resolved = _resolve_usb_device(device)
    if not resolved:
        return {"ok": False, "error": "not_found", "msg": f"Device '{device}' not found."}

    if _which("udisksctl"):
        rc, out = _run(["udisksctl", "mount", "-b", resolved, "--no-user-interaction"], timeout=15.0)
        if rc == 0:
            # Extract mountpoint from output: "Mounted /dev/sdb1 at /media/user/label"
            mp = ""
            m = re.search(r"at\s+(/\S+)", out)
            if m:
                mp = m.group(1)
            return {"ok": True, "device": resolved, "mountpoint": mp, "msg": f"Mounted: {resolved} → {mp}"}
        return {"ok": False, "error": "mount_failed", "msg": out.strip()}

    if _which("gio"):
        rc, out = _run(["gio", "mount", "-d", resolved], timeout=15.0)
        if rc == 0:
            return {"ok": True, "device": resolved, "mountpoint": "", "msg": f"Mounted via gio: {resolved}"}
        return {"ok": False, "error": "mount_failed", "msg": out.strip()}

    return {"ok": False, "error": "no_tool", "msg": "Neither udisksctl nor gio available."}


def sys_usb_unmount(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Unmount a USB storage device via udisksctl."""
    device = str(payload.get("device", payload.get("mountpoint", payload.get("label", "")))).strip()
    if not device:
        return {"ok": False, "error": "missing_device", "msg": "No device specified."}

    resolved = _resolve_usb_device(device)
    if not resolved:
        return {"ok": False, "error": "not_found", "msg": f"Device '{device}' not found."}

    if _which("udisksctl"):
        rc, out = _run(["udisksctl", "unmount", "-b", resolved, "--no-user-interaction"], timeout=15.0)
        if rc == 0:
            return {"ok": True, "device": resolved, "msg": f"Unmounted: {resolved}"}
        return {"ok": False, "error": "unmount_failed", "msg": out.strip()}

    return {"ok": False, "error": "no_tool", "msg": "udisksctl not available."}


def sys_usb_eject(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Safely eject a USB device: unmount all partitions, then power-off."""
    device = str(payload.get("device", payload.get("label", ""))).strip()
    if not device:
        return {"ok": False, "error": "missing_device", "msg": "No device specified."}

    resolved = _resolve_usb_device(device)
    if not resolved:
        return {"ok": False, "error": "not_found", "msg": f"Device '{device}' not found."}

    # Find parent disk (e.g. /dev/sdb from /dev/sdb1)
    disk = re.sub(r"\d+$", "", resolved)

    if not _which("udisksctl"):
        return {"ok": False, "error": "no_tool", "msg": "udisksctl not available."}

    # Unmount all partitions of this disk
    if _which("lsblk"):
        rc, out = _run(["lsblk", "-Jpo", "NAME,MOUNTPOINT,TYPE"], timeout=5.0)
        if rc == 0:
            import json as _json
            try:
                data = _json.loads(out)
                for dev in data.get("blockdevices", []):
                    if dev.get("name", "") == disk:
                        for part in dev.get("children", []):
                            if part.get("mountpoint"):
                                _run(["udisksctl", "unmount", "-b", part["name"], "--no-user-interaction"], timeout=10.0)
            except Exception:
                pass

    # Power off the disk
    rc, out = _run(["udisksctl", "power-off", "-b", disk, "--no-user-interaction"], timeout=15.0)
    if rc == 0:
        return {"ok": True, "device": disk, "msg": f"Safely ejected: {disk}"}
    return {"ok": False, "error": "eject_failed", "msg": out.strip()}


def sys_network() -> Dict[str, Any]:
    """
    Get network interfaces with IP addresses, MAC, state, and throughput stats.
    """
    interfaces: List[Dict[str, Any]] = []

    net_path = Path("/sys/class/net")
    if not net_path.exists():
        return {"ok": False, "error": "sysfs_net_unavailable"}

    for iface_dir in sorted(net_path.iterdir()):
        if not iface_dir.is_symlink() and not iface_dir.is_dir():
            continue

        iface_name = iface_dir.name
        iface_info: Dict[str, Any] = {"name": iface_name}

        def read_attr(path: str) -> Optional[str]:
            try:
                return Path(path).read_text(encoding="utf-8", errors="replace").strip()
            except Exception:
                return None

        # MAC address
        mac = read_attr(str(iface_dir / "address"))
        if mac and mac != "00:00:00:00:00:00":
            iface_info["mac"] = mac

        # Operstate (up/down)
        operstate = read_attr(str(iface_dir / "operstate"))
        if operstate:
            iface_info["state"] = operstate

        # Speed (for ethernet)
        speed = read_attr(str(iface_dir / "speed"))
        if speed and speed != "-1":
            try:
                iface_info["speed_mbps"] = int(speed)
            except Exception:
                pass

        # MTU
        mtu = read_attr(str(iface_dir / "mtu"))
        if mtu:
            try:
                iface_info["mtu"] = int(mtu)
            except Exception:
                pass

        # Driver info
        driver_link = iface_dir / "device" / "driver"
        if driver_link.exists():
            try:
                driver_path = driver_link.resolve()
                iface_info["driver"] = driver_path.name
            except Exception:
                pass

        # TX/RX statistics for throughput
        stats_dir = iface_dir / "statistics"
        if stats_dir.exists():
            tx_bytes = read_attr(str(stats_dir / "tx_bytes"))
            rx_bytes = read_attr(str(stats_dir / "rx_bytes"))
            tx_packets = read_attr(str(stats_dir / "tx_packets"))
            rx_packets = read_attr(str(stats_dir / "rx_packets"))
            tx_errors = read_attr(str(stats_dir / "tx_errors"))
            rx_errors = read_attr(str(stats_dir / "rx_errors"))

            stats: Dict[str, int] = {}
            for name, val in [("tx_bytes", tx_bytes), ("rx_bytes", rx_bytes),
                              ("tx_packets", tx_packets), ("rx_packets", rx_packets),
                              ("tx_errors", tx_errors), ("rx_errors", rx_errors)]:
                if val:
                    try:
                        stats[name] = int(val)
                    except Exception:
                        pass
            if stats:
                iface_info["statistics"] = stats

        # Get IP addresses via ip command
        if _which("ip"):
            rc, out = _run(["ip", "-j", "addr", "show", iface_name], timeout=2.0)
            if rc == 0 and out.strip():
                try:
                    ip_data = json.loads(out)
                    if ip_data and isinstance(ip_data, list) and len(ip_data) > 0:
                        addr_info = ip_data[0].get("addr_info", [])
                        addresses: List[Dict[str, Any]] = []
                        for ai in addr_info:
                            addresses.append({
                                "family": ai.get("family"),
                                "address": ai.get("local"),
                                "prefixlen": ai.get("prefixlen"),
                                "scope": ai.get("scope"),
                            })
                        if addresses:
                            iface_info["addresses"] = addresses
                except Exception:
                    pass

        # Wireless info if applicable
        wireless_dir = iface_dir / "wireless"
        if wireless_dir.exists():
            iface_info["type"] = "wireless"
            # Try to get SSID via iwgetid
            if _which("iwgetid"):
                rc, out = _run(["iwgetid", iface_name, "-r"], timeout=2.0)
                if rc == 0 and out.strip():
                    iface_info["ssid"] = out.strip()
        elif iface_name.startswith("lo"):
            iface_info["type"] = "loopback"
        elif iface_name.startswith("docker") or iface_name.startswith("br-"):
            iface_info["type"] = "bridge"
        elif iface_name.startswith("veth"):
            iface_info["type"] = "veth"
        else:
            iface_info["type"] = "ethernet"

        interfaces.append(iface_info)

    # Get default gateway
    default_gateway = None
    if _which("ip"):
        rc, out = _run(["ip", "route", "show", "default"], timeout=2.0)
        if rc == 0:
            m = re.search(r"via\s+(\S+)", out)
            if m:
                default_gateway = m.group(1)

    return {
        "ok": True,
        "ts": now_iso(),
        "default_gateway": default_gateway,
        "interface_count": len(interfaces),
        "interfaces": interfaces,
    }


def sys_hardware_deep() -> Dict[str, Any]:
    """
    Get deep hardware info: BIOS, CPU cache, GPU features, PCI devices.
    """
    result: Dict[str, Any] = {"ok": True, "ts": now_iso()}

    # BIOS / DMI info
    dmi_info: Dict[str, Any] = {}
    dmi_path = Path("/sys/class/dmi/id")
    if dmi_path.exists():
        for attr in ["bios_vendor", "bios_version", "bios_date", "bios_release",
                     "board_vendor", "board_name", "board_version",
                     "product_name", "product_version", "sys_vendor"]:
            f = dmi_path / attr
            if f.exists():
                try:
                    val = f.read_text(encoding="utf-8", errors="replace").strip()
                    if val:
                        dmi_info[attr] = val
                except PermissionError:
                    pass
                except Exception:
                    pass
    result["dmi"] = dmi_info

    # CPU detailed info including cache
    cpu_info: Dict[str, Any] = {}
    try:
        cpuinfo = _read_text("/proc/cpuinfo")
        flags = ""
        cache_size = ""
        cpu_family = ""
        model = ""
        stepping = ""
        microcode = ""

        for line in cpuinfo.splitlines():
            if line.startswith("flags"):
                flags = line.split(":", 1)[1].strip()
            elif line.startswith("cache size"):
                cache_size = line.split(":", 1)[1].strip()
            elif line.startswith("cpu family"):
                cpu_family = line.split(":", 1)[1].strip()
            elif line.startswith("model") and not line.startswith("model name"):
                model = line.split(":", 1)[1].strip()
            elif line.startswith("stepping"):
                stepping = line.split(":", 1)[1].strip()
            elif line.startswith("microcode"):
                microcode = line.split(":", 1)[1].strip()

        if flags:
            cpu_info["flags"] = flags.split()[:50]  # Limit to first 50 flags
            cpu_info["flag_count"] = len(flags.split())
        if cache_size:
            cpu_info["cache_size"] = cache_size
        if cpu_family:
            cpu_info["family"] = cpu_family
        if model:
            cpu_info["model"] = model
        if stepping:
            cpu_info["stepping"] = stepping
        if microcode:
            cpu_info["microcode"] = microcode
    except Exception:
        pass

    # CPU cache topology from /sys
    cache_info: List[Dict[str, Any]] = []
    cpu0_cache = Path("/sys/devices/system/cpu/cpu0/cache")
    if cpu0_cache.exists():
        for idx_dir in sorted(cpu0_cache.glob("index*")):
            cache_entry: Dict[str, Any] = {"index": idx_dir.name}
            for attr in ["level", "type", "size", "coherency_line_size",
                         "ways_of_associativity", "number_of_sets"]:
                f = idx_dir / attr
                if f.exists():
                    try:
                        cache_entry[attr] = f.read_text().strip()
                    except Exception:
                        pass
            cache_info.append(cache_entry)
    cpu_info["cache_topology"] = cache_info
    result["cpu_deep"] = cpu_info

    # GPU info from /sys/class/drm and lspci
    gpu_info: List[Dict[str, Any]] = []

    # From sysfs drm
    drm_path = Path("/sys/class/drm")
    if drm_path.exists():
        for card_dir in sorted(drm_path.glob("card[0-9]*")):
            if not card_dir.is_dir():
                continue
            if "-" in card_dir.name:  # Skip connector entries like card0-HDMI
                continue

            gpu_entry: Dict[str, Any] = {"device": card_dir.name}

            # Device info
            device_link = card_dir / "device"
            if device_link.exists():
                # Vendor/device IDs
                for attr in ["vendor", "device", "subsystem_vendor", "subsystem_device"]:
                    f = device_link / attr
                    if f.exists():
                        try:
                            gpu_entry[attr] = f.read_text().strip()
                        except Exception:
                            pass

                # Driver
                driver_link = device_link / "driver"
                if driver_link.exists():
                    try:
                        gpu_entry["driver"] = driver_link.resolve().name
                    except Exception:
                        pass

                # GPU-specific attributes
                for attr in ["gpu_busy_percent", "mem_info_vram_total",
                             "mem_info_vram_used", "power_dpm_state"]:
                    f = device_link / attr
                    if f.exists():
                        try:
                            gpu_entry[attr] = f.read_text().strip()
                        except Exception:
                            pass

            gpu_info.append(gpu_entry)

    # Supplement with lspci for GPU details
    if _which("lspci"):
        rc, out = _run(["lspci", "-nn", "-d", "::0300"], timeout=3.0)  # VGA controllers
        if rc == 0 and out.strip():
            for line in out.splitlines():
                for gpu in gpu_info:
                    # Try to match by description
                    if gpu.get("vendor") and gpu["vendor"].replace("0x", "") in line.lower():
                        gpu["lspci_desc"] = line.strip()
                        break
                else:
                    # If no match, add as separate entry
                    gpu_info.append({"lspci_desc": line.strip()})

    result["gpu"] = gpu_info

    # PCI devices summary (categorized)
    pci_summary: Dict[str, int] = {}
    if _which("lspci"):
        rc, out = _run(["lspci"], timeout=3.0)
        if rc == 0:
            for line in out.splitlines():
                # Extract device class (first part after bus ID)
                parts = line.split(":", 1)
                if len(parts) >= 2:
                    class_name = parts[1].strip().split(":")[0].strip()
                    pci_summary[class_name] = pci_summary.get(class_name, 0) + 1
    result["pci_device_classes"] = pci_summary

    # Memory modules from dmidecode (if available and has perms)
    mem_modules: List[Dict[str, str]] = []
    if _which("dmidecode"):
        rc, out = _run(["dmidecode", "-t", "memory"], timeout=5.0)
        if rc == 0:
            current_module: Dict[str, str] = {}
            for line in out.splitlines():
                line = line.strip()
                if line.startswith("Memory Device"):
                    if current_module and current_module.get("Size", "").strip() not in ["", "No Module Installed"]:
                        mem_modules.append(current_module)
                    current_module = {}
                elif ":" in line:
                    key, val = line.split(":", 1)
                    key = key.strip()
                    val = val.strip()
                    if key in ["Size", "Type", "Speed", "Manufacturer", "Part Number", "Locator"]:
                        current_module[key] = val
            if current_module and current_module.get("Size", "").strip() not in ["", "No Module Installed"]:
                mem_modules.append(current_module)
    result["memory_modules"] = mem_modules

    return result


def sys_extended_summary() -> Dict[str, Any]:
    """
    Extended system summary including deep hardware info.
    """
    cached = _cache_get("sys_extended", CACHE_TTL_SUMMARY * 5)  # Cache 5x longer
    if cached is not None:
        return cached

    d: Dict[str, Any] = {"ok": True, "ts": now_iso()}
    d["basic"] = sys_summary()
    d["drivers"] = sys_drivers()
    d["usb"] = sys_usb()
    d["network"] = sys_network()
    d["hardware_deep"] = sys_hardware_deep()

    _cache_set("sys_extended", d)
    return d


# ---------------- HTTP server ----------------

import urllib.request  # placed here to keep parts cleaner


@dataclass
class RequestCtx:
    path: str
    payload: Dict[str, Any]


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, obj: Any) -> None:
        data = _json_dumps(obj)
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        try:
            self.wfile.write(data)
        except BrokenPipeError:
            return

    def _read_json(self) -> Dict[str, Any]:
        try:
            ln = int(self.headers.get("Content-Length", "0"))
        except Exception:
            ln = 0
        raw = self.rfile.read(ln) if ln > 0 else b"{}"
        try:
            obj = json.loads(raw.decode("utf-8", errors="replace"))
            return obj if isinstance(obj, dict) else {}
        except Exception:
            return {}

    def log_message(self, fmt: str, *args: Any) -> None:
        # keep quiet
        return

    def do_GET(self) -> None:
        if self.path == "/health":
            self._send(200, {"ok": True, "ts": now_iso()})
            return
        self._send(404, {"ok": False, "error": "not_found", "path": self.path})

    def do_POST(self) -> None:
        payload = self._read_json()
        p = self.path

        # FS
        if p == "/fs/list":
            res = fs_list(
                path=str(payload.get("path", ".")),
                recursive=bool(payload.get("recursive", False)),
                max_entries=int(payload.get("max_entries", 2000)),
                include_hidden=bool(payload.get("include_hidden", False)),
            )
            self._send(200, res)
            return

        if p == "/fs/read":
            res = fs_read(
                path=str(payload.get("path", "")),
                max_bytes=int(payload.get("max_bytes", 256_000)),
            )
            self._send(200, res)
            return

        if p == "/fs/write":
            res = fs_write(
                path=str(payload.get("path", "")),
                content=str(payload.get("content", "")),
                overwrite=bool(payload.get("overwrite", False)),
            )
            self._send(200, res)
            return

        if p == "/fs/move":
            res = fs_move(
                src=str(payload.get("src", "")),
                dst=str(payload.get("dst", "")),
                overwrite=bool(payload.get("overwrite", False)),
            )
            self._send(200, res)
            return

        if p == "/fs/copy":
            res = fs_copy(
                src=str(payload.get("src", "")),
                dst=str(payload.get("dst", "")),
                overwrite=bool(payload.get("overwrite", False)),
            )
            self._send(200, res)
            return

        if p == "/fs/delete":
            res = fs_delete(path=str(payload.get("path", "")))
            self._send(200, res)
            return

        if p == "/fs/backup":
            src_paths = payload.get("src_paths", [])
            if not isinstance(src_paths, list):
                src_paths = []
            res = fs_backup(
                src_paths=[str(x) for x in src_paths],
                backup_dir=str(payload.get("backup_dir")) if payload.get("backup_dir") else None,
                mode=str(payload.get("mode", "copy")),
                keep_structure=bool(payload.get("keep_structure", True)),
            )
            self._send(200, res)
            return

        # Desktop / browser
        if p == "/desktop/open_url":
            url = str(payload.get("url", "")).strip()
            if not url:
                self._send(400, {"ok": False, "error": "missing_url"})
                return
            self._send(200, desktop_open_url(url))
            return

        if p == "/desktop/screenshot":
            self._send(200, desktop_screenshot())
            return

        # System
        if p == "/sys/os":
            self._send(200, sys_os())
            return
        if p == "/sys/cpu":
            self._send(200, sys_cpu())
            return
        if p == "/sys/mem":
            self._send(200, sys_mem())
            return
        if p == "/sys/disk":
            paths = payload.get("paths")
            if isinstance(paths, list):
                paths = [str(x) for x in paths]
            else:
                paths = None
            self._send(200, sys_disk(paths=paths))
            return
        if p == "/sys/temps":
            self._send(200, sys_temps())
            return
        if p == "/sys/pressure":
            self._send(200, sys_pressure())
            return
        if p == "/sys/disk_health":
            self._send(200, sys_disk_health())
            return
        if p == "/sys/services_user":
            pat = str(payload.get("pattern", "aicore-*"))
            self._send(200, sys_services_user(pattern=pat))
            return
        if p == "/sys/summary":
            self._send(200, sys_summary())
            return

        # Deep system info endpoints
        if p == "/sys/drivers":
            self._send(200, sys_drivers())
            return
        if p == "/sys/usb":
            self._send(200, sys_usb())
            return
        if p == "/sys/usb/storage":
            self._send(200, sys_usb_storage())
            return
        if p == "/sys/usb/mount":
            self._send(200, sys_usb_mount(payload))
            return
        if p == "/sys/usb/unmount":
            self._send(200, sys_usb_unmount(payload))
            return
        if p == "/sys/usb/eject":
            self._send(200, sys_usb_eject(payload))
            return
        if p == "/sys/network":
            self._send(200, sys_network())
            return
        if p == "/sys/hardware_deep":
            self._send(200, sys_hardware_deep())
            return
        if p == "/sys/extended":
            self._send(200, sys_extended_summary())
            return

        # App Registry endpoints
        if p == "/app/search":
            from app_registry import app_search
            query = str(payload.get("query", ""))
            limit = int(payload.get("limit", 10))
            self._send(200, app_search(query, limit))
            return

        if p == "/app/list":
            from app_registry import app_list
            limit = int(payload.get("limit", 50))
            effective_only = bool(payload.get("effective_only", False))
            self._send(200, app_list(limit, effective_only))
            return

        if p == "/app/open":
            from app_registry import app_open
            app_id = str(payload.get("app", payload.get("app_id", "")))
            if not app_id:
                self._send(400, {"ok": False, "error": "missing_app", "message": "Parameter 'app' is missing"})
                return
            self._send(200, app_open(app_id))
            return

        if p == "/app/close":
            from app_registry import app_close
            app_id = str(payload.get("app", payload.get("app_id", "")))
            if not app_id:
                self._send(400, {"ok": False, "error": "missing_app", "message": "Parameter 'app' is missing"})
                return
            self._send(200, app_close(app_id))
            return

        if p == "/app/allow":
            from app_registry import app_allow
            app_id = str(payload.get("app", payload.get("app_id", "")))
            permanent = bool(payload.get("permanent", False))
            if not app_id:
                self._send(400, {"ok": False, "error": "missing_app", "message": "Parameter 'app' is missing"})
                return
            self._send(200, app_allow(app_id, permanent))
            return

        if p == "/app/capabilities":
            from app_registry import app_capabilities
            self._send(200, app_capabilities())
            return

        # Steam endpoints
        if p == "/steam/list":
            from steam_integration import get_installed_games
            games = get_installed_games()
            self._send(200, {
                "ok": True,
                "count": len(games),
                "games": [{"appid": g.appid, "name": g.name, "size": g.size_on_disk} for g in games]
            })
            return

        if p == "/steam/search":
            from steam_integration import get_installed_games, find_game_by_name
            query = str(payload.get("query", ""))
            if not query:
                self._send(400, {"ok": False, "error": "missing_query"})
                return
            games = get_installed_games()
            game = find_game_by_name(query, games)
            if game:
                self._send(200, {"ok": True, "found": True, "game": {"appid": game.appid, "name": game.name}})
            else:
                # Return suggestions
                suggestions = [g.name for g in games[:5]]
                self._send(200, {"ok": True, "found": False, "suggestions": suggestions})
            return

        if p == "/steam/launch":
            from steam_integration import launch_game_by_name
            game_name = str(payload.get("game", payload.get("name", "")))
            if not game_name:
                self._send(400, {"ok": False, "error": "missing_game", "message": "Parameter 'game' is missing"})
                return
            success, msg = launch_game_by_name(game_name)
            self._send(200, {"ok": success, "message": msg})
            return

        if p == "/steam/close":
            from steam_integration import close_game
            game_name = payload.get("game", payload.get("name"))
            if not game_name:
                self._send(400, {"ok": False, "error": "missing 'game' or 'name' parameter"})
                return
            success, msg = close_game(game_name)
            self._send(200, {"ok": success, "message": msg})
            return

        # Core-Awareness endpoints
        if p == "/core/summary":
            import sys
            sys.path.insert(0, str(_TOOLBOX_TOOLS_DIR))
            from core_awareness import get_summary
            self._send(200, get_summary())
            return

        if p == "/core/describe":
            import sys
            sys.path.insert(0, str(_TOOLBOX_TOOLS_DIR))
            from core_awareness import describe_self
            self._send(200, {"ok": True, "description": describe_self()})
            return

        if p == "/core/module":
            import sys
            sys.path.insert(0, str(_TOOLBOX_TOOLS_DIR))
            from core_awareness import get_module
            name = str(payload.get("name", payload.get("module", "")))
            if not name:
                self._send(400, {"ok": False, "error": "missing_name"})
                return
            self._send(200, get_module(name))
            return

        if p == "/core/scan":
            import sys
            sys.path.insert(0, str(_TOOLBOX_TOOLS_DIR))
            from core_awareness import full_scan
            self._send(200, full_scan())
            return

        if p == "/core/pause":
            import sys
            sys.path.insert(0, str(_TOOLBOX_TOOLS_DIR))
            from core_awareness import pause_watch
            pause_watch()
            self._send(200, {"ok": True, "message": "Watcher paused"})
            return

        if p == "/core/resume":
            import sys
            sys.path.insert(0, str(_TOOLBOX_TOOLS_DIR))
            from core_awareness import resume_watch
            resume_watch()
            self._send(200, {"ok": True, "message": "Watcher resumed"})
            return

        if p == "/core/reflect":
            import sys
            sys.path.insert(0, str(_TOOLBOX_TOOLS_DIR))
            from core_awareness import get_awareness
            name = str(payload.get("name", payload.get("module", "")))
            awareness = get_awareness()
            if name:
                reflection = awareness.reflect_on_module(name)
            else:
                reflection = awareness.describe_self()
            self._send(200, {"ok": True, "reflection": reflection})
            return

        if p == "/core/features":
            import sys
            sys.path.insert(0, str(_TOOLBOX_TOOLS_DIR))
            from core_awareness import get_features
            self._send(200, get_features())
            return

        # ---------- Skill System Endpoints ----------

        if p == "/skill/list":
            import sys
            sys.path.insert(0, str(_TOOLBOX_SRC_ROOT))
            from skills import get_skill_registry
            registry = get_skill_registry()
            skills = []
            for s in registry.list_all():
                skills.append({
                    "name": s.name,
                    "description": s.meta.get("description", ""),
                    "type": s.skill_type,
                    "keywords": s.meta.get("keywords", []),
                    "parameters": s.meta.get("parameters", []),
                    "category": s.meta.get("category", ""),
                    "version": s.meta.get("version", ""),
                })
            self._send(200, {"ok": True, "skills": skills, "count": len(skills)})
            return

        if p == "/skill/run":
            import sys
            sys.path.insert(0, str(_TOOLBOX_SRC_ROOT))
            from skills import get_skill_registry
            skill_name = str(payload.get("skill", ""))
            params = payload.get("params", {})
            if not skill_name:
                self._send(400, {"ok": False, "error": "missing 'skill' parameter"})
                return
            result = get_skill_registry().execute(skill_name, params)
            status = 200 if result.get("ok") else 500
            self._send(status, result)
            return

        if p == "/skill/reload":
            import sys
            sys.path.insert(0, str(_TOOLBOX_SRC_ROOT))
            from skills import get_skill_registry
            name = str(payload.get("name", "")) or None
            count = get_skill_registry().reload(name)
            self._send(200, {"ok": True, "reloaded": count})
            return

        if p == "/skill/browse":
            import sys
            sys.path.insert(0, str(_TOOLBOX_SRC_ROOT))
            from skills import get_skill_registry
            query = str(payload.get("query", ""))
            limit = int(payload.get("limit", 20))
            result = get_skill_registry().browse_marketplace(query, limit)
            self._send(200, result)
            return

        if p == "/skill/install":
            import sys
            sys.path.insert(0, str(_TOOLBOX_SRC_ROOT))
            from skills import get_skill_registry
            slug = str(payload.get("slug", ""))
            if not slug:
                self._send(400, {"ok": False, "error": "missing 'slug' parameter"})
                return
            result = get_skill_registry().install_from_marketplace(slug)
            status = 200 if result.get("ok") else 400
            self._send(status, result)
            return

        if p == "/skill/summary":
            import sys
            sys.path.insert(0, str(_TOOLBOX_SRC_ROOT))
            from skills import get_skill_registry
            summary = get_skill_registry().get_skills_summary()
            self._send(200, {"ok": True, "summary": summary})
            return

        # User profile endpoints
        if p == "/user/name":
            from user_profile import get_user_name, set_user_name
            if payload.get("name"):
                set_user_name(str(payload["name"]))
                self._send(200, {"ok": True, "name": payload["name"]})
            else:
                name = get_user_name()
                self._send(200, {"ok": True, "name": name})
            return

        # Email endpoints (read-only)
        if p == "/email/unread":
            from email_reader import get_unread_count
            counts = get_unread_count()
            if "error" in counts:
                self._send(500, {"ok": False, "error": counts["error"]})
            else:
                self._send(200, {"ok": True, "unread": counts})
            return

        if p == "/email/list":
            from email_reader import list_emails
            folder = str(payload.get("folder", "INBOX"))
            limit = int(payload.get("limit", 20))
            emails = list_emails(folder=folder, limit=limit)
            if emails and "error" in emails[0]:
                self._send(500, {"ok": False, "error": emails[0]["error"]})
            else:
                self._send(200, {"ok": True, "count": len(emails), "emails": emails})
            return

        if p == "/email/read":
            from email_reader import read_email
            folder = str(payload.get("folder", "INBOX"))
            msg_id = payload.get("id")
            idx = payload.get("idx")
            query = payload.get("query")
            if idx is not None:
                idx = int(idx)
            result = read_email(folder=folder, msg_id=msg_id, idx=idx, query=query)
            if "error" in result:
                self._send(404, {"ok": False, "error": result["error"]})
            else:
                self._send(200, {"ok": True, "email": result})
            return

        if p == "/email/check_new":
            from email_reader import check_new_emails
            result = check_new_emails()
            if "error" in result:
                self._send(500, {"ok": False, "error": result["error"]})
            else:
                self._send(200, {"ok": True, **result})
            return

        if p == "/email/delete":
            from email_reader import delete_emails
            folder = str(payload.get("folder", "[Gmail]/Spam"))
            query = payload.get("query")
            msg_id = payload.get("id")
            delete_all = bool(payload.get("delete_all", False))
            result = delete_emails(folder=folder, query=query, delete_all=delete_all, msg_id=msg_id)
            if "error" in result:
                self._send(500, {"ok": False, "error": result["error"]})
            else:
                self._send(200, {"ok": True, **result})
            return

        if p == "/email/spam":
            from email_reader import move_to_spam
            folder = str(payload.get("folder", "INBOX"))
            msg_id = payload.get("id")
            query = payload.get("query")
            result = move_to_spam(folder=folder, msg_id=msg_id, query=query)
            if "error" in result:
                self._send(500, {"ok": False, "error": result["error"]})
            else:
                self._send(200, {"ok": True, **result})
            return

        if p == "/email/send":
            from email_reader import send_email
            to = str(payload.get("to", ""))
            subject = str(payload.get("subject", ""))
            body = str(payload.get("body", ""))
            cc = payload.get("cc") or None
            bcc = payload.get("bcc") or None
            attachments = payload.get("attachments")  # list of file paths or None
            in_reply_to = payload.get("in_reply_to")
            references = payload.get("references")
            result = send_email(to=to, subject=subject, body=body,
                                cc=cc, bcc=bcc,
                                attachments=attachments, in_reply_to=in_reply_to,
                                references=references)
            if "error" in result:
                self._send(500, {"ok": False, "error": result["error"]})
            else:
                self._send(200, {"ok": True, **result})
            return

        if p == "/email/draft":
            from email_reader import save_draft
            to = str(payload.get("to", ""))
            subject = str(payload.get("subject", ""))
            body = str(payload.get("body", ""))
            result = save_draft(to=to, subject=subject, body=body)
            if "error" in result:
                self._send(500, {"ok": False, "error": result["error"]})
            else:
                self._send(200, {"ok": True, **result})
            return

        if p == "/email/toggle_read":
            from email_reader import toggle_read_status
            folder = str(payload.get("folder", "INBOX"))
            msg_id = payload.get("id") or payload.get("msg_id")
            mark_read = bool(payload.get("mark_read", True))
            result = toggle_read_status(folder=folder, msg_id=msg_id, mark_read=mark_read)
            if "error" in result:
                self._send(500, {"ok": False, "error": result["error"]})
            else:
                self._send(200, {"ok": True, **result})
            return

        # ── Calendar endpoints ────────────────────────────────────

        if p == "/calendar/today":
            from calendar_reader import get_today_events
            result = get_today_events()
            if "error" in result:
                self._send(500, {"ok": False, "error": result["error"]})
            else:
                self._send(200, result)
            return

        if p == "/calendar/week":
            from calendar_reader import get_week_events
            result = get_week_events()
            if "error" in result:
                self._send(500, {"ok": False, "error": result["error"]})
            else:
                self._send(200, result)
            return

        if p == "/calendar/events":
            from calendar_reader import list_events
            start = payload.get("start")
            end = payload.get("end")
            limit = int(payload.get("limit", 20))
            result = list_events(start=start, end=end, limit=limit)
            if "error" in result:
                self._send(500, {"ok": False, "error": result["error"]})
            else:
                self._send(200, result)
            return

        if p == "/calendar/event":
            from calendar_reader import get_event
            uid = str(payload.get("uid", ""))
            result = get_event(uid)
            if "error" in result:
                self._send(500, {"ok": False, "error": result["error"]})
            else:
                self._send(200, result)
            return

        if p == "/calendar/create":
            from calendar_reader import create_event
            title = str(payload.get("title", ""))
            start = str(payload.get("start", ""))
            end = payload.get("end")
            description = str(payload.get("description", ""))
            location = str(payload.get("location", ""))
            result = create_event(title=title, start=start, end=end, description=description, location=location)
            if "error" in result:
                self._send(500, {"ok": False, "error": result["error"]})
            else:
                self._send(200, result)
            return

        if p == "/calendar/delete":
            from calendar_reader import delete_event
            uid = str(payload.get("uid", ""))
            result = delete_event(uid)
            if "error" in result:
                self._send(500, {"ok": False, "error": result["error"]})
            else:
                self._send(200, result)
            return

        # ── Contacts endpoints ────────────────────────────────────

        if p == "/contacts/list":
            from contact_reader import list_contacts
            result = list_contacts()
            if "error" in result:
                self._send(500, {"ok": False, "error": result["error"]})
            else:
                self._send(200, result)
            return

        if p == "/contacts/search":
            from contact_reader import search_contacts
            query = str(payload.get("query", ""))
            result = search_contacts(query)
            if "error" in result:
                self._send(500, {"ok": False, "error": result["error"]})
            else:
                self._send(200, result)
            return

        if p == "/contacts/get":
            from contact_reader import get_contact
            uid = str(payload.get("uid", ""))
            result = get_contact(uid)
            if "error" in result:
                self._send(500, {"ok": False, "error": result["error"]})
            else:
                self._send(200, result)
            return

        if p == "/contacts/create":
            from contact_reader import create_contact
            name = str(payload.get("name", ""))
            phone = str(payload.get("phone", ""))
            email = str(payload.get("email", ""))
            org = str(payload.get("org", ""))
            result = create_contact(name=name, phone=phone, email=email, org=org)
            if "error" in result:
                self._send(500, {"ok": False, "error": result["error"]})
            else:
                self._send(200, result)
            return

        if p == "/contacts/delete":
            from contact_reader import delete_contact
            uid = str(payload.get("uid", ""))
            result = delete_contact(uid)
            if "error" in result:
                self._send(500, {"ok": False, "error": result["error"]})
            else:
                self._send(200, result)
            return

        # ── Notes endpoints ───────────────────────────────────────

        if p == "/notes/create":
            from notes_store import create_note
            content = str(payload.get("content", ""))
            tags = str(payload.get("tags", ""))
            result = create_note(content=content, tags=tags)
            if "error" in result:
                self._send(500, {"ok": False, "error": result["error"]})
            else:
                self._send(200, result)
            return

        if p == "/notes/list":
            from notes_store import list_notes
            limit = int(payload.get("limit", 20))
            result = list_notes(limit=limit)
            if "error" in result:
                self._send(500, {"ok": False, "error": result["error"]})
            else:
                self._send(200, result)
            return

        if p == "/notes/search":
            from notes_store import search_notes
            query = str(payload.get("query", ""))
            result = search_notes(query)
            if "error" in result:
                self._send(500, {"ok": False, "error": result["error"]})
            else:
                self._send(200, result)
            return

        if p == "/notes/get":
            from notes_store import get_note
            note_id = int(payload.get("id", 0))
            result = get_note(note_id)
            if "error" in result:
                self._send(500, {"ok": False, "error": result["error"]})
            else:
                self._send(200, result)
            return

        if p == "/notes/update":
            from notes_store import update_note
            note_id = int(payload.get("id", 0))
            content = payload.get("content")
            tags = payload.get("tags")
            result = update_note(note_id, content=content, tags=tags)
            if "error" in result:
                self._send(500, {"ok": False, "error": result["error"]})
            else:
                self._send(200, result)
            return

        if p == "/notes/delete":
            from notes_store import delete_note
            note_id = int(payload.get("id", 0))
            result = delete_note(note_id)
            if "error" in result:
                self._send(500, {"ok": False, "error": result["error"]})
            else:
                self._send(200, result)
            return

        # ── Todo endpoints ────────────────────────────────────────

        if p == "/todo/create":
            from todo_store import create_todo
            content = str(payload.get("content", ""))
            due_date = payload.get("due_date")
            result = create_todo(content, due_date=due_date)
            if "error" in result:
                self._send(500, {"ok": False, "error": result["error"]})
            else:
                self._send(200, result)
            return

        if p == "/todo/list":
            from todo_store import list_todos
            status = str(payload.get("status", "pending"))
            limit = int(payload.get("limit", 20))
            result = list_todos(status=status, limit=limit)
            if "error" in result:
                self._send(500, {"ok": False, "error": result["error"]})
            else:
                self._send(200, result)
            return

        if p == "/todo/search":
            from todo_store import search_todos
            query = str(payload.get("query", ""))
            result = search_todos(query)
            if "error" in result:
                self._send(500, {"ok": False, "error": result["error"]})
            else:
                self._send(200, result)
            return

        if p == "/todo/complete":
            from todo_store import complete_todo
            todo_id = int(payload.get("id", 0))
            result = complete_todo(todo_id)
            if "error" in result:
                self._send(500, {"ok": False, "error": result["error"]})
            else:
                self._send(200, result)
            return

        if p == "/todo/delete":
            from todo_store import delete_todo
            todo_id = int(payload.get("id", 0))
            result = delete_todo(todo_id)
            if "error" in result:
                self._send(500, {"ok": False, "error": result["error"]})
            else:
                self._send(200, result)
            return

        if p == "/todo/due":
            from todo_store import get_due_todos
            within = int(payload.get("within_minutes", 15))
            result = get_due_todos(within_minutes=within)
            if "error" in result:
                self._send(500, {"ok": False, "error": result["error"]})
            else:
                self._send(200, result)
            return

        # ---------- Entity Session Log Endpoints ----------

        if p == "/entity/sessions":
            entity = str(payload.get("entity", "all")).lower()
            limit = int(payload.get("limit", 10))
            self._send(200, entity_sessions_list(entity=entity, limit=limit))
            return

        if p == "/entity/session":
            session_id = str(payload.get("session_id", ""))
            if not session_id:
                self._send(400, {"ok": False, "error": "missing 'session_id' parameter"})
                return
            include_history = payload.get("include_history", True)
            if isinstance(include_history, str):
                include_history = include_history.lower() not in ("false", "0", "no")
            self._send(200, entity_session_read(session_id=session_id, include_history=bool(include_history)))
            return

        if p == "/entity/search":
            query = str(payload.get("query", ""))
            if not query:
                self._send(400, {"ok": False, "error": "missing 'query' parameter"})
                return
            entity = str(payload.get("entity", "all")).lower()
            limit = int(payload.get("limit", 5))
            self._send(200, entity_sessions_search(query=query, entity=entity, limit=limit))
            return

        self._send(404, {"ok": False, "error": "not_found", "path": p})


def main() -> None:
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"toolboxd listening on http://{HOST}:{PORT}")
    httpd.serve_forever()


if __name__ == "__main__":
    main()

