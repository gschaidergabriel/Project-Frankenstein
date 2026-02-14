"""Vision / image analysis / PDF text extraction helpers."""

from __future__ import annotations

from pathlib import Path
from typing import List

from overlay.constants import LOG, AICORE_ROOT


def _debug_log(msg: str):
    """Write debug message to file."""
    try:
        with open("/tmp/frank_vision_debug.log", "a") as f:
            import time
            f.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")
            f.flush()
    except Exception:
        pass


def _analyze_with_vcb(screenshot_path: Path, user_query: str) -> str:
    """Analyze screenshot using VCB (Hybrid OCR + Local Vision - no external APIs).

    Uses OCR for accurate text extraction and vision model for layout understanding.
    OCR grounding significantly reduces hallucination from local vision models.
    Self-awareness context is injected for desktop screenshots.
    """
    try:
        _debug_log(f"VCB: Analyzing {screenshot_path} with hybrid OCR+Vision (self-aware)")

        # Import VCB module
        try:
            from tools.vcb_bridge import analyze_image
        except ImportError:
            # Try absolute import
            import sys
            try:
                from config.paths import AICORE_ROOT as _AICORE_ROOT
            except ImportError:
                from pathlib import Path as _P
                _AICORE_ROOT = _P(__file__).resolve().parents[3]  # ui/overlay/services/ -> opt/aicore
            sys.path.insert(0, str(_AICORE_ROOT))
            from tools.vcb_bridge import analyze_image

        # Pass is_screenshot=True to enable self-awareness context
        result = analyze_image(
            str(screenshot_path),
            user_query if user_query else None,
            is_screenshot=True
        )

        if result:
            _debug_log(f"VCB: Got {len(result)} chars: {result[:100]}...")
            return result
        else:
            _debug_log("VCB: No result (rate limit or error)")
    except Exception as e:
        _debug_log(f"VCB ERROR: {e}")
    return ""


# Compatibility alias for existing code
_analyze_with_moondream = _analyze_with_vcb


def _analyze_image_with_vcb(image_path: Path, context: str = "") -> str:
    """Analyze any image file using VCB (Hybrid OCR + Local Vision - no external APIs).

    Uses OCR for text extraction and vision model for layout/content understanding.
    """
    try:
        _debug_log(f"VCB Image: Analyzing {image_path} with hybrid OCR+Vision")

        # Import VCB module
        try:
            from tools.vcb_bridge import analyze_image
        except ImportError:
            # Try absolute import
            import sys
            try:
                from config.paths import AICORE_ROOT as _AICORE_ROOT
            except ImportError:
                from pathlib import Path as _P
                _AICORE_ROOT = _P(__file__).resolve().parents[3]  # ui/overlay/services/ -> opt/aicore
            sys.path.insert(0, str(_AICORE_ROOT))
            from tools.vcb_bridge import analyze_image

        # Build question for VCB - OCR grounding is handled internally
        question = context if context else None

        result = analyze_image(str(image_path), question)

        if result:
            _debug_log(f"VCB Image: Got {len(result)} chars")
            return result
        else:
            _debug_log("VCB Image: No result (rate limit or error)")
    except Exception as e:
        _debug_log(f"VCB Image ERROR: {e}")
    return ""


# Compatibility alias for existing code
_analyze_image_with_moondream = _analyze_image_with_vcb


def _capture_error_screenshot(error_context: str = "") -> dict:
    """
    Capture screenshot for error debugging.

    Uses VCB with spam protection to prevent negative loops.
    """
    try:
        from tools.vcb_bridge import capture_error_screenshot
        return capture_error_screenshot(error_context)
    except ImportError:
        import sys
        try:
            from config.paths import AICORE_ROOT as _AICORE_ROOT
        except ImportError:
            from pathlib import Path as _P
            _AICORE_ROOT = _P(__file__).resolve().parents[3]  # ui/overlay/services/ -> opt/aicore
        sys.path.insert(0, str(_AICORE_ROOT))
        from tools.vcb_bridge import capture_error_screenshot
        return capture_error_screenshot(error_context)
    except Exception as e:
        _debug_log(f"Error screenshot failed: {e}")
        return None


def _extract_pdf_text(pdf_path: Path, max_pages: int = 10) -> str:
    """Extract text from PDF using pdftotext or PyPDF2."""
    text = ""

    # Try pdftotext first (faster, better quality)
    try:
        import subprocess
        result = subprocess.run(
            ["pdftotext", "-layout", "-l", str(max_pages), str(pdf_path), "-"],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0 and result.stdout.strip():
            text = result.stdout.strip()
            _debug_log(f"PDF extracted via pdftotext: {len(text)} chars")
            return text[:50000]  # Limit size
    except Exception as e:
        _debug_log(f"pdftotext failed: {e}")

    # Fallback to PyPDF2
    try:
        from PyPDF2 import PdfReader
        reader = PdfReader(str(pdf_path))
        pages = []
        for i, page in enumerate(reader.pages[:max_pages]):
            pages.append(page.extract_text() or "")
        text = "\n\n".join(pages)
        _debug_log(f"PDF extracted via PyPDF2: {len(text)} chars")
        return text[:50000]
    except Exception as e:
        _debug_log(f"PyPDF2 failed: {e}")

    return ""
