"""File utility functions extracted from the monolith overlay."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from overlay.constants import (
    LOG,
    PATH_LIKE_RE,
    EXT_LANG,
    SESSION_ID,
    INGEST_BASE_ENV,
    INGEST_PORT_CANDIDATES,
    INGEST_HEALTH_PATHS,
    INGEST_UPLOAD_PATHS,
)
from overlay.http_helpers import _http_get_json, _http_post_multipart
from overlay.services.core_api import _core_chat


def _debug_log(msg: str):
    """Write debug message to file."""
    try:
        try:
            from config.paths import get_temp as _get_temp_fu
            _vision_log = str(_get_temp_fu("vision_debug.log"))
        except ImportError:
            _vision_log = "/tmp/frank/vision_debug.log"
        with open(_vision_log, "a") as f:
            import time
            f.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")
            f.flush()
    except Exception:
        pass


def _suggest_features_for_content(content: str, file_type: str) -> List[str]:
    """Suggest relevant features based on file content and type."""
    suggestions = []
    content_lower = content.lower()

    # Content-based feature suggestions
    if any(w in content_lower for w in ["wallpaper", "hintergrund", "desktop", "animation"]):
        suggestions.append("My **Live Wallpaper** could be extended with these concepts")
    if any(w in content_lower for w in ["app", "programm", "software", "anwendung", "launcher"]):
        suggestions.append("My **App Launcher** could integrate these apps")
    if any(w in content_lower for w in ["smart", "home", "licht", "lampe", "steckdose", "sensor"]):
        suggestions.append("My **Smart Home** integration could help here")
    if any(w in content_lower for w in ["screenshot", "bild", "image", "foto", "vision"]):
        suggestions.append("My **Screenshot Analysis** could visualize this")
    if any(w in content_lower for w in ["code", "python", "script", "function", "class", "def "]):
        suggestions.append("I could **analyze this code** and explain it")
    if any(w in content_lower for w in ["todo", "aufgabe", "task", "liste", "plan"]):
        suggestions.append("I could help **organize** these tasks")
    if any(w in content_lower for w in ["api", "endpoint", "server", "http", "request"]):
        suggestions.append("My **system knowledge** could help with API integration")

    # File type based suggestions
    if file_type.lower() in ["pdf-dokument", "pdf"]:
        suggestions.append("I can **read the content aloud** or summarize it")
    if file_type.lower() in ["python", "code", ".py"]:
        suggestions.append("I can **explain the code** and suggest improvements")

    return suggestions[:3]  # Max 3 suggestions


def _generate_file_abstract(file_path: Path, content: str, file_type: str) -> str:
    """Generate a detailed abstract for any file using LLM, with feature-based suggestions."""
    size = file_path.stat().st_size if file_path.exists() else 0
    size_str = _fmt_bytes(size)

    # LLM has 4096 token context now
    # ~1.3 chars per token for German, need room for prompt (~300 tokens) and response (~500 tokens)
    # Safe content: (4096 - 800) * 1.3 = ~4300 chars
    max_content = 4000  # Generous limit with 4096 context
    content_preview = content[:max_content]
    if len(content) > max_content:
        content_preview += "..."

    prompt = f"""File: {file_path.name} ({file_type}, {size_str})

Content:
{content_preview}

Give a clear analysis (3-4 sentences): What is this? What does it contain? What is it for?"""

    abstract_text = ""
    try:
        res = _core_chat(prompt, max_tokens=250, timeout_s=60, task="chat.fast", force="llama")
        if res.get("ok"):
            abstract_text = res.get("text", "").strip()
        _debug_log(f"Abstract LLM response: ok={res.get('ok')}")
    except Exception as e:
        _debug_log(f"Abstract generation error: {e}")

    if not abstract_text:
        # Fallback: return basic info with first part of content
        preview = content[:300].replace('\n', ' ').strip()
        abstract_text = f"Content: {preview}..."

    # Build response with analysis
    response = f"**{file_path.name}** ({size_str})\n\n{abstract_text}"

    # Add feature-based suggestions (self-reflection on what Frank could do)
    suggestions = _suggest_features_for_content(content, file_type)
    if suggestions:
        response += "\n\n**What I could do with this:**\n"
        for s in suggestions:
            response += f"• {s}\n"

    return response


def _format_file_list(result: Dict[str, Any], path: str) -> str:
    """Format file list result for display."""
    if not result or not result.get("ok"):
        error = result.get("error", "unknown") if result else "timeout"
        return f"Error listing {path}: {error}"

    entries = result.get("items") or result.get("entries", [])
    if not entries:
        return f"The folder {path} is empty."

    dirs = [e for e in entries if e.get("is_dir")]
    files = [e for e in entries if not e.get("is_dir")]

    lines = [f"Contents of {path} ({len(entries)} entries):"]
    lines.append("")

    if dirs:
        lines.append(f"Folders ({len(dirs)}):")
        for d in sorted(dirs, key=lambda x: x.get("name", ""))[:20]:
            lines.append(f"  [DIR] {d.get('name', '?')}")
        if len(dirs) > 20:
            lines.append(f"  ... and {len(dirs) - 20} more folders")

    if files:
        lines.append(f"\nFiles ({len(files)}):")
        for f in sorted(files, key=lambda x: x.get("name", ""))[:30]:
            size = f.get("size", 0)
            size_str = _fmt_bytes(size) if size else "?"
            lines.append(f"  {f.get('name', '?')} ({size_str})")
        if len(files) > 30:
            lines.append(f"  ... and {len(files) - 30} more files")

    return "\n".join(lines)


def _is_ok_health(j: Optional[Dict[str, Any]]) -> bool:
    return isinstance(j, dict) and (j.get("ok") is True or j.get("status") == "ok")


def _detect_ingest_base() -> Optional[str]:
    if INGEST_BASE_ENV:
        return INGEST_BASE_ENV
    for port in INGEST_PORT_CANDIDATES:
        base = f"http://127.0.0.1:{port}"
        for hp in INGEST_HEALTH_PATHS:
            j = _http_get_json(base + hp, timeout_s=0.8)
            if _is_ok_health(j):
                return base
    return None


def _try_ingest_upload(file_path: Path) -> Tuple[bool, str]:
    base = _detect_ingest_base()
    if not base:
        return False, "ingest base not found"
    last_err = ""
    for up in INGEST_UPLOAD_PATHS:
        url = base + up
        try:
            _http_post_multipart(url, file_path, timeout_s=60.0)
            return True, f"{url}"
        except Exception as e:
            last_err = str(e)
    return False, f"upload failed ({base}): {last_err}"


def _maybe_path(s: str) -> Optional[Path]:
    """Check if string looks like a valid file path. Returns Path if file exists, else None."""
    s = (s or "").strip()
    if not s:
        return None
    # CRITICAL: Reject strings too long to be valid paths (Linux PATH_MAX = 4096)
    # This prevents OSError: [Errno 36] File name too long when calling exists()
    if len(s) > 4096:
        return None
    if not PATH_LIKE_RE.search(s):
        return None
    s = s.strip('"').strip("'").replace("\\ ", " ")
    # Also reject if any path component exceeds NAME_MAX (255)
    if any(len(part) > 255 for part in s.split("/")):
        return None
    p = Path(s).expanduser()
    try:
        if p.exists() and p.is_file():
            return p
    except OSError:
        # Catch any remaining OS errors (permission, invalid chars, etc.)
        return None
    return None


def _read_file_preview(p: Path, max_chars: int = 110_000) -> Tuple[str, str]:
    ext = p.suffix.lower()
    lang = EXT_LANG.get(ext, "text")
    try:
        txt = p.read_text(encoding="utf-8", errors="replace")
    except Exception:
        b = p.read_bytes()
        txt = f"[binary file; first 4096 bytes hex]\n{b[:4096].hex()}"
        lang = "text"
    if len(txt) > max_chars:
        txt = txt[:max_chars] + "\n\n[...truncated...]"
    return lang, txt


def _fmt_bytes(n: Optional[int]) -> str:
    if n is None:
        return "?"
    try:
        n = int(n)
    except Exception:
        return "?"
    units = ["B", "KB", "MB", "GB", "TB"]
    f = float(n)
    u = 0
    while f >= 1024.0 and u < len(units) - 1:
        f /= 1024.0
        u += 1
    if u == 0:
        return f"{int(f)}{units[u]}"
    return f"{f:.1f}{units[u]}"


def _extract_context_line(j: Dict[str, Any]) -> str:
    cpu_model = cores = mhz = None
    try:
        cpu = j.get("cpu") or {}
        cpu_model = cpu.get("model")
        cores = cpu.get("cores")
        mhz = cpu.get("mhz_avg")
    except Exception:
        pass

    mem_used = mem_total = None
    try:
        mem = j.get("mem") or {}
        mkb = mem.get("mem_kb") or {}
        mem_total = int(mkb.get("total", 0)) * 1024
        mem_used = int(mkb.get("used", 0)) * 1024
    except Exception:
        pass

    disk_used = disk_total = None
    try:
        disk = j.get("disk") or {}
        root = (disk.get("paths") or {}).get("/") or disk.get("root") or {}
        disk_total = root.get("total_bytes") or root.get("total")
        disk_used = root.get("used_bytes") or root.get("used")
        if disk_total is not None:
            disk_total = int(disk_total)
        if disk_used is not None:
            disk_used = int(disk_used)
    except Exception:
        pass

    temp_c = None
    try:
        temps = j.get("temps") or {}
        if "max_c" in temps:
            temp_c = float(temps["max_c"])
        elif "cpu_max_c" in temps:
            temp_c = float(temps["cpu_max_c"])
    except Exception:
        pass

    parts: List[str] = []
    if cpu_model:
        parts.append(str(cpu_model))
    if cores:
        parts.append(f"{cores}c")
    if mhz:
        try:
            parts.append(f"{float(mhz):.0f}MHz")
        except Exception:
            pass

    mem_part = ""
    if mem_used is not None and mem_total is not None and mem_total > 0:
        mem_part = f"RAM {_fmt_bytes(mem_used)}/{_fmt_bytes(mem_total)}"

    disk_part = ""
    if disk_used is not None and disk_total is not None and disk_total > 0:
        disk_part = f"Disk {_fmt_bytes(disk_used)}/{_fmt_bytes(disk_total)}"

    temp_part = ""
    if temp_c is not None:
        temp_part = f"Temp {temp_c:.0f}C"

    tail = " | ".join([p for p in [mem_part, disk_part, temp_part] if p])
    head = " ".join(parts).strip()
    if head and tail:
        return f"{head} | {tail}"
    return head or tail or ""


def _build_file_prompt(action: str, p: Path, lang: str, content: str, ctx: str) -> str:
    size = p.stat().st_size
    # Truncate content to fit in LLM context (4096 tokens)
    max_content = 4500
    truncated = content[:max_content]
    if len(content) > max_content:
        truncated += "\n[...truncated...]"

    return (
        f"File: {p.name} ({_fmt_bytes(size)})\n"
        f"Task: {action}\n\n"
        f"Content:\n```{lang}\n{truncated}\n```"
    )
