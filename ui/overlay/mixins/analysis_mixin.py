"""Analysis workers – screenshot, image, PDF, file read, and ADI display intelligence."""
from __future__ import annotations

import base64
import os
import subprocess
import sys
import time
import shutil
from pathlib import Path
from typing import Dict

from overlay.constants import LOG, FRANK_IDENTITY, IMAGE_EXTENSIONS, EXT_LANG, AICORE_ROOT
from overlay.services.core_api import _core_chat
from overlay.services.vision import _analyze_with_vcb, _analyze_image_with_vcb, _extract_pdf_text, _debug_log
from overlay.services.toolbox import _take_screenshot, _read_file_via_toolbox, _is_path_forbidden
from overlay.file_utils import _fmt_bytes, _generate_file_abstract, _read_file_preview


class AnalysisMixin:
    """Screenshot capture, image/PDF analysis, file reading, and ADI display intelligence."""

    # ========== ADI (Adaptive Display Intelligence) Methods ==========

    def _handle_adi_request(self, user_message: str):
        """
        User asked about display/layout configuration.
        Opens the ADI popup for collaborative configuration.
        """
        LOG.info(f"ADI request triggered: {user_message[:50]}...")
        self._add_message("Frank", "Opening the display setup. We can adjust the settings together there.", is_system=True)

        # Open ADI popup in background
        try:
            adi_script = AICORE_ROOT / "ui" / "adi_popup" / "main_window.py"
            subprocess.Popen(
                [sys.executable, str(adi_script), "--reopen"],
                env={**os.environ, "DISPLAY": os.environ.get("DISPLAY", ":0")},
                start_new_session=True,
            )
        except Exception as e:
            LOG.error(f"Failed to open ADI popup: {e}")
            self._add_message("Frank", "Could not open the display setup.", is_system=True)

    def _do_screenshot_worker(self, user_query: str, voice: bool = False):
        """Take screenshot, analyze with VCB vision API, respond naturally."""
        _debug_log(f"Screenshot worker started for: {user_query} (voice={voice})")
        self._ui_call(self._show_typing)

        # Take screenshot
        result = _take_screenshot()
        screenshot_ok = result and result.get("ok")
        screenshot_path = None
        _debug_log(f"Screenshot result ok: {screenshot_ok}")

        if screenshot_ok:
            try:
                png_b64 = result.get("png_b64", "")
                if png_b64:
                    screenshot_path = Path("/tmp") / f"frank_screenshot_{int(time.time())}.png"
                    screenshot_path.write_bytes(base64.b64decode(png_b64))
                    _debug_log(f"Screenshot saved to: {screenshot_path}")
            except Exception as e:
                _debug_log(f"Screenshot save error: {e}")

        # Try QR scan on screenshot FIRST
        qr_results = []
        if screenshot_path and screenshot_path.exists():
            try:
                sys.path.insert(0, str(AICORE_ROOT / "tools"))
                from qr_tool import scan_from_file
                qr_results = scan_from_file(str(screenshot_path))
                if qr_results:
                    _debug_log(f"QR codes found on screen: {qr_results}")
            except Exception as e:
                _debug_log(f"QR scan on screenshot skipped: {e}")

        # If QR found, show results and skip vision analysis
        if qr_results:
            self._ui_call(self._hide_typing)
            def _show_qr_screen(results=qr_results):
                if len(results) == 1:
                    self._add_message("Frank", results[0])
                else:
                    lines = [f"{len(results)} QR codes found:"]
                    for r in results:
                        lines.append(r)
                    self._add_message("Frank", "\n".join(lines))
            self._ui_call(_show_qr_screen)
            try:
                screenshot_path.unlink()
            except Exception:
                pass
            return

        # PRIMARY: Analyze with VCB (Hugging Face Vision API)
        vision_description = ""
        if screenshot_path and screenshot_path.exists():
            _debug_log("Calling VCB...")
            vision_description = _analyze_with_vcb(screenshot_path, user_query)
            _debug_log(f"VCB returned {len(vision_description)} chars")

        # FALLBACK: Gather metadata if vision fails
        desktop_info = []
        if not vision_description:
            # Get active window
            try:
                active_result = subprocess.run(
                    ["xdotool", "getactivewindow", "getwindowname"],
                    capture_output=True, text=True, timeout=2.0
                )
                if active_result.returncode == 0 and active_result.stdout:
                    desktop_info.append(f"Active window: {active_result.stdout.strip()}")
            except Exception:
                pass

            # OCR as last resort
            if screenshot_path and screenshot_path.exists():
                try:
                    import pytesseract
                    from PIL import Image
                    img = Image.open(screenshot_path)
                    ocr_text = pytesseract.image_to_string(img, lang='deu+eng')
                    if ocr_text and len(ocr_text.strip()) > 20:
                        lines = [l.strip() for l in ocr_text.split('\n') if len(l.strip()) > 5][:5]
                        if lines:
                            desktop_info.append(f"Visible text: {' | '.join(lines)}")
                except Exception:
                    pass

        # Build self-aware response via LLM (like _do_analyze_image_worker)
        _debug_log(f"Vision description: {(vision_description or 'none')[:200]}...")

        # Gather self-awareness context for the LLM prompt
        component_summary = ""
        monitor_summary = ""
        try:
            from tools.frank_component_detector import detect_frank_components
            comp_data = detect_frank_components()
            if comp_data["frank_components"]:
                parts = [c["name"] for c in comp_data["frank_components"]]
                component_summary = ", ".join(parts)
            if comp_data["monitors"]:
                mon_parts = [f"{m['name']} ({m['resolution']})" for m in comp_data["monitors"]]
                monitor_summary = f"{len(comp_data['monitors'])} Monitor(e): {', '.join(mon_parts)}"
            if comp_data["other_windows"]:
                other = [w["title"][:40] for w in comp_data["other_windows"][:4]]
                component_summary += f". Other windows: {', '.join(other)}"
        except Exception as e:
            _debug_log(f"Component detection failed: {e}")

        if vision_description or desktop_info:
            raw_description = vision_description if vision_description else " ".join(desktop_info)

            # Replace trigger words BEFORE sending to core API
            safe_desc = raw_description.replace("desktop", "computer").replace("Desktop", "Computer")
            safe_desc = safe_desc.replace("screen", "display").replace("Screen", "Display")

            # Route through LLM for natural self-aware first-person response
            prompt = (
                f"You are Frank. You just looked at your monitor.\n\n"
                f"Image analysis result:\n{safe_desc}\n\n"
            )
            if component_summary:
                prompt += f"Your own components: {component_summary}\n"
            if monitor_summary:
                prompt += f"Monitor setup: {monitor_summary}\n"
            prompt += (
                "\nDescribe in 3-5 sentences what you see. "
                "Recognize your own parts (e.g. 'my chat overlay', 'my wallpaper'). "
                "Speak in first person. Be natural and specific. "
                "Avoid the words: desktop, screen, do you see, what do you see."
            )

            try:
                _debug_log("Routing screenshot through LLM for self-aware response...")
                res = _core_chat(prompt, max_tokens=400, timeout_s=60, task="chat.fast", force="llama")
                reply = (res.get("text") or "").strip() if res.get("ok") else ""
                if not reply:
                    # Fallback to raw vision output
                    reply = f"I see: {safe_desc[:500]}"
                _debug_log(f"LLM reply: {reply[:150]}...")
            except Exception as e:
                _debug_log(f"LLM routing failed: {e}")
                reply = f"Ich sehe: {safe_desc[:500]}"
        else:
            reply = "Could not analyze the monitor."

        _debug_log(f"Final reply: {reply[:150]}...")

        self._ui_call(self._hide_typing)

        # Show screenshot thumbnail in chat (if available)
        if screenshot_path and screenshot_path.exists():
            # Copy to persistent location for viewer access
            try:
                persistent_path = Path("/tmp") / f"frank_screenshot_view_{int(time.time())}.png"
                shutil.copy2(screenshot_path, persistent_path)
                self._ui_call(lambda p=str(persistent_path): self._add_image(p, caption="Desktop Screenshot", is_user=False))
                # Clean up original
                screenshot_path.unlink()
            except Exception as e:
                _debug_log(f"Screenshot display error: {e}")
                # Fallback: just delete the original
                try:
                    screenshot_path.unlink()
                except Exception:
                    pass

        # Route response: Voice -> Outbox + UI, Normal -> UI only
        if voice:
            self._ui_call(lambda r=reply: self._voice_respond(r))
        else:
            self._ui_call(lambda r=reply: self._add_message("Frank", r))

    def _do_analyze_image_worker(self, path: Path):
        """Analyze an image file using VCB vision model + QR scan."""
        _debug_log(f"Image analysis worker started for: {path}")
        self._ui_call(self._show_typing)

        size = path.stat().st_size if path.exists() else 0
        size_str = _fmt_bytes(size)

        # Try QR scan FIRST — if image contains QR codes, decode them
        qr_results = []
        try:
            sys.path.insert(0, str(AICORE_ROOT / "tools"))
            from qr_tool import scan_from_file
            qr_results = scan_from_file(str(path))
            if qr_results:
                _debug_log(f"QR codes found in image: {qr_results}")
        except Exception as e:
            _debug_log(f"QR scan skipped: {e}")

        # If QR codes found, show decoded content directly
        if qr_results:
            self._ui_call(self._hide_typing)
            def _show_qr(results=qr_results):
                if len(results) == 1:
                    self._add_message("Frank", results[0])
                else:
                    lines = [f"{len(results)} QR codes found:"]
                    for r in results:
                        lines.append(r)
                    self._add_message("Frank", "\n".join(lines))
            self._ui_call(_show_qr)
            return

        # Use VCB to analyze the image
        vision_description = _analyze_image_with_vcb(path, context=f"Filename: {path.name}")

        if not vision_description:
            self._ui_call(self._hide_typing)
            self._ui_call(lambda p=path, s=size_str: self._add_message(
                "Frank",
                f"Image received: {p.name} ({s}). Could not analyze the image - Vision API not available.",
                is_system=True
            ))
            return

        # Generate natural response via LLM
        prompt = f"""You are Frank. The user sent you an image: {path.name} ({size_str})

The image analysis returned:
{vision_description}

Create a short, informative abstract:
1. What does the image show?
2. Important details
3. Quality/special features

Maximum 4-5 sentences, naturally phrased."""

        try:
            res = _core_chat(prompt, max_tokens=400, timeout_s=60, task="chat.fast", force="llama")
            reply = (res.get("text") or "").strip() if res.get("ok") else vision_description
        except Exception as e:
            _debug_log(f"Image LLM error: {e}")
            reply = f"Image analysis: {vision_description}"

        self._ui_call(self._hide_typing)
        self._ui_call(lambda r=reply: self._add_message("Frank", r))

    def _do_analyze_pdf_worker(self, path: Path):
        """Analyze a PDF file - extract text and generate abstract."""
        _debug_log(f"PDF analysis worker started for: {path}")
        self._ui_call(self._show_typing)

        size = path.stat().st_size if path.exists() else 0
        size_str = _fmt_bytes(size)

        # Extract text from PDF
        pdf_text = _extract_pdf_text(path)

        if not pdf_text:
            self._ui_call(self._hide_typing)
            self._ui_call(lambda p=path, s=size_str: self._add_message(
                "Frank",
                f"PDF received: {p.name} ({s}). Could not extract text - PDF may be scanned or protected.",
                is_system=True
            ))
            return

        # Generate abstract via LLM
        abstract = _generate_file_abstract(path, pdf_text, "PDF-Dokument")

        self._ui_call(self._hide_typing)
        self._ui_call(lambda r=abstract: self._add_message("Frank", r))

    def _do_read_file_worker(self, path: str, user_query: str):
        """Read a file from the filesystem and provide analysis."""
        _debug_log(f"Read file worker started for: {path}")
        self._ui_call(self._show_typing)

        # Resolve and check path
        try:
            p = Path(path).expanduser().resolve()
        except Exception as e:
            self._ui_call(self._hide_typing)
            self._ui_call(lambda e=e: self._add_message("Frank", f"Invalid path: {e}", is_system=True))
            return

        if not p.exists():
            self._ui_call(self._hide_typing)
            self._ui_call(lambda pp=p: self._add_message("Frank", f"File not found: {pp}", is_system=True))
            return

        if p.is_dir():
            # It's a directory - list contents instead
            self._ui_call(self._hide_typing)
            self._io_q.put(("fs_list", {"path": str(p), "user_query": user_query}))
            return

        # Check if forbidden
        if _is_path_forbidden(str(p)):
            self._ui_call(self._hide_typing)
            self._ui_call(lambda: self._add_message("Frank", "Access to this file is not allowed.", is_system=True))
            return

        size = p.stat().st_size
        size_str = _fmt_bytes(size)
        ext = p.suffix.lower()

        # Handle different file types
        if ext in IMAGE_EXTENSIONS:
            self._ui_call(self._hide_typing)
            self._ui_call(lambda pp=p: self._add_message("Frank", f"Loading image: {pp.name}...", is_system=True))
            self._chat_q.put(("analyze_image", {"path": p}))
            return

        if ext == ".pdf":
            self._ui_call(self._hide_typing)
            self._ui_call(lambda pp=p: self._add_message("Frank", f"Loading PDF: {pp.name}...", is_system=True))
            self._chat_q.put(("analyze_pdf", {"path": p}))
            return

        # Read text file via toolbox
        result = _read_file_via_toolbox(str(p), max_bytes=100000)

        if not result or not result.get("ok"):
            error = result.get("error", "Unknown error") if result else "No response"
            self._ui_call(self._hide_typing)
            self._ui_call(lambda e=error: self._add_message("Frank", f"Error reading: {e}", is_system=True))
            return

        content = result.get("text", "")
        if not content and result.get("b64"):
            # Binary file
            self._ui_call(self._hide_typing)
            self._ui_call(lambda pp=p, s=size_str: self._add_message(
                "Frank",
                f"File {pp.name} ({s}) is a binary file and cannot be displayed as text.",
                is_system=True
            ))
            return

        # Generate abstract for the file
        lang = EXT_LANG.get(ext, "text")
        file_type = f"{lang.title()} file" if lang != "text" else "Text file"

        # Store for potential follow-up questions
        self._last_file = p
        self._last_file_lang = lang
        self._last_file_content = content

        # Generate and show abstract
        abstract = _generate_file_abstract(p, content, file_type)

        self._ui_call(self._hide_typing)
        self._ui_call(lambda r=abstract: self._add_message("Frank", r))
