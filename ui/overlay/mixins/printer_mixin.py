"""Printer mixin -- print files, check printer status, list print jobs.

Extends the existing printer detection/setup in system_control with
actual printing (lp/lpr) and status queries (lpstat).
Workers run on IO thread.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

from overlay.constants import LOG


class PrinterMixin:
    """Printer: status, print files, job queue."""

    # ── Printer status ────────────────────────────────────────────

    def _do_printer_status_worker(self, **_kw):
        """Show printer status and print queue."""
        try:
            # Get configured printers
            result = subprocess.run(
                ["lpstat", "-p", "-d"],
                capture_output=True, text=True, timeout=5,
            )
            printer_info = result.stdout.strip() if result.returncode == 0 else ""

            # Get print queue
            queue_result = subprocess.run(
                ["lpstat", "-o"],
                capture_output=True, text=True, timeout=5,
            )
            queue_info = queue_result.stdout.strip() if queue_result.returncode == 0 else ""

        except FileNotFoundError:
            self._ui_call(lambda: self._add_message(
                "Frank",
                "CUPS is not installed. Printer management not available.\n"
                "Say 'install cups' to set up.",
                is_system=True,
            ))
            return
        except Exception as e:
            LOG.error(f"Printer status error: {e}")
            self._ui_call(lambda: self._add_message(
                "Frank", f"Could not query printer status: {e}", is_system=True,
            ))
            return

        # Parse and format output
        lines = ["PRINTER STATUS:", "=" * 40, ""]

        if not printer_info:
            lines.append("No printers configured.")
            lines.append("")
            lines.append("Say 'set up printer' to search and configure.")
        else:
            # Parse printer lines
            for line in printer_info.split("\n"):
                line = line.strip()
                if not line:
                    continue
                if line.startswith("printer"):
                    # e.g. "printer HP_DeskJet is idle."
                    name_match = re.match(r"printer\s+(\S+)\s+(.+)", line)
                    if name_match:
                        name = name_match.group(1).replace("_", " ")
                        status = name_match.group(2).rstrip(".")
                        # Translate common statuses
                        status_de = status
                        if "idle" in status.lower():
                            status_de = "Ready"
                        elif "printing" in status.lower():
                            status_de = "Printing"
                        elif "disabled" in status.lower():
                            status_de = "Disabled"
                        lines.append(f"  {name}: {status_de}")
                elif line.startswith("system default"):
                    default_match = re.match(r"system default destination:\s*(\S+)", line)
                    if default_match:
                        lines.append(f"\n  Default printer: {default_match.group(1).replace('_', ' ')}")

        if queue_info:
            lines.append("")
            lines.append("PRINT JOBS:")
            lines.append("-" * 40)
            job_count = 0
            for line in queue_info.split("\n"):
                line = line.strip()
                if line:
                    lines.append(f"  {line}")
                    job_count += 1
            if job_count == 0:
                lines.append("  No jobs in the queue.")
        else:
            if printer_info:
                lines.append("")
                lines.append("No print jobs in the queue.")

        msg = "\n".join(lines)
        self._ui_call(lambda m=msg: self._add_message("Frank", m))

    # ── Print file ────────────────────────────────────────────────

    def _do_print_file_worker(self, path: str = "", user_msg: str = "", **_kw):
        """Print a file using lp command."""
        # If no path given, check for last attached file
        if not path and hasattr(self, '_last_file') and self._last_file:
            path = str(self._last_file)

        if not path:
            self._ui_call(lambda: self._add_message(
                "Frank",
                "Which file should I print? Provide the path, e.g.:\n"
                "'print ~/Documents/letter.pdf'",
                is_system=True,
            ))
            return

        # Expand ~ and resolve path
        file_path = Path(path).expanduser().resolve()

        if not file_path.exists():
            self._ui_call(lambda p=str(file_path): self._add_message(
                "Frank", f"File not found: {p}", is_system=True,
            ))
            return

        # Check if it's a printable file type
        printable = {".pdf", ".txt", ".ps", ".png", ".jpg", ".jpeg", ".gif",
                     ".bmp", ".tiff", ".doc", ".docx", ".odt", ".html"}
        suffix = file_path.suffix.lower()
        if suffix not in printable:
            self._ui_call(lambda s=suffix: self._add_message(
                "Frank",
                f"File type '{s}' may not be supported.\n"
                f"Supported formats: PDF, TXT, images, Office documents.",
                is_system=True,
            ))
            return

        # Check for default printer
        try:
            result = subprocess.run(
                ["lpstat", "-d"],
                capture_output=True, text=True, timeout=3,
            )
            if "no system default" in result.stdout.lower() or result.returncode != 0:
                self._ui_call(lambda: self._add_message(
                    "Frank",
                    "No default printer configured.\n"
                    "Say 'set up printer' to configure.",
                    is_system=True,
                ))
                return
        except FileNotFoundError:
            self._ui_call(lambda: self._add_message(
                "Frank", "CUPS is not installed.", is_system=True,
            ))
            return

        # Print!
        self._ui_call(lambda p=file_path.name: self._add_message(
            "Frank", f"Printing '{p}'...", is_system=True,
        ))

        try:
            result = subprocess.run(
                ["lp", str(file_path)],
                capture_output=True, text=True, timeout=10,
            )

            if result.returncode == 0:
                # Extract job ID from output like "request id is HP_DeskJet-123 (1 file(s))"
                job_match = re.search(r"request id is (\S+)", result.stdout)
                job_id = job_match.group(1) if job_match else "unknown"

                self._ui_call(lambda f=file_path.name, j=job_id: self._add_message(
                    "Frank",
                    f"Print job sent!\n"
                    f"  File: {f}\n"
                    f"  Job ID: {j}\n\n"
                    f"Say 'printer status' for progress.",
                ))
            else:
                err = result.stderr.strip() or result.stdout.strip() or "Unknown error"
                self._ui_call(lambda e=err: self._add_message(
                    "Frank", f"Print failed: {e}", is_system=True,
                ))

        except subprocess.TimeoutExpired:
            self._ui_call(lambda: self._add_message(
                "Frank", "Print job: timeout exceeded.", is_system=True,
            ))
        except Exception as e:
            LOG.error(f"Print file error: {e}")
            self._ui_call(lambda err=str(e): self._add_message(
                "Frank", f"Print error: {err}", is_system=True,
            ))
