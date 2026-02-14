"""Password Manager mixin -- popup, chat commands, auto-type.

Workers run on IO thread, popup created via _ui_call() on main thread.
"""
from __future__ import annotations

import subprocess
import sys
import threading
import time

from overlay.constants import LOG

try:
    from config.paths import TOOLS_DIR as _TOOLS_DIR
except ImportError:
    from pathlib import Path as _Path
    _TOOLS_DIR = _Path("/home/ai-core-node/aicore/opt/aicore/tools")
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))


class PasswordMixin:
    """Password Manager: popup, list, search, auto-type, copy."""

    # ── Popup management ──────────────────────────────────────────────

    def _open_password_popup(self):
        """Open the password popup (must run on main thread)."""
        if self._password_popup is not None:
            try:
                self._password_popup.lift()
                return
            except Exception:
                self._password_popup = None

        from overlay.widgets.password_popup import PasswordPopup
        self._password_popup = PasswordPopup(
            self,
            on_destroy=self._on_password_popup_destroyed,
            on_autotype=self._do_autotype_credentials,
        )

    def _on_password_popup_destroyed(self):
        self._password_popup = None

    # ── Auto-type (runs in background thread) ─────────────────────────

    def _do_autotype_credentials(self, username: str, password: str):
        """Type username + Tab + password into focused window (xdotool)."""
        def _type():
            self._ui_call(lambda: self._add_message(
                "Frank",
                "Auto-login: Focus the login window! Input in 3 seconds...",
                is_system=True
            ))
            time.sleep(3)
            try:
                subprocess.run(
                    ["xdotool", "type", "--clearmodifiers", "--delay", "20", username],
                    timeout=5, check=False,
                )
                time.sleep(0.1)
                subprocess.run(
                    ["xdotool", "key", "Tab"],
                    timeout=2, check=False,
                )
                time.sleep(0.1)
                subprocess.run(
                    ["xdotool", "type", "--clearmodifiers", "--delay", "20", password],
                    timeout=5, check=False,
                )
                self._ui_call(lambda: self._add_message(
                    "Frank", "Login typed!", is_system=True
                ))
            except FileNotFoundError:
                self._ui_call(lambda: self._add_message(
                    "Frank", "xdotool not installed! (sudo apt install xdotool)",
                    is_system=True
                ))
            except Exception as e:
                self._ui_call(lambda err=e: self._add_message(
                    "Frank", f"Auto-type error: {err}", is_system=True
                ))

        threading.Thread(target=_type, daemon=True).start()

    # ── Workers (IO thread, dispatched by worker_mixin) ───────────────

    def _do_password_popup_worker(self, **kwargs):
        """Open the password manager popup."""
        self._ui_call(self._open_password_popup)

    def _do_password_list_worker(self, voice: bool = False, **kwargs):
        """List password names in chat (NO credentials)."""
        self._ui_call(self._show_typing)
        try:
            import password_store

            if not password_store.is_initialized():
                reply = "No password store found. Say 'password manager' to create one."
                self._ui_call(self._hide_typing)
                self._ui_call(lambda r=reply: self._add_message("Frank", r))
                return

            if not password_store.is_unlocked():
                self._ui_call(self._hide_typing)
                self._ui_call(lambda: self._add_message(
                    "Frank", "Password store is locked. Open the password manager to unlock."
                ))
                self._ui_call(self._open_password_popup)
                return

            result = password_store.list_passwords()
            if not result.get("ok"):
                self._ui_call(self._hide_typing)
                self._ui_call(lambda: self._add_message("Frank", "Error loading.", is_system=True))
                return

            entries = result.get("entries", [])
            if not entries:
                reply = "No passwords saved. Open the password manager to add some."
            else:
                lines = [f"Saved passwords ({len(entries)}):"]
                for e in entries:
                    url_hint = f" ({e['url']})" if e.get("url") else ""
                    lines.append(f"  • {e['name']}{url_hint}")
                reply = "\n".join(lines)

            self._ui_call(self._hide_typing)
            if voice and hasattr(self, '_voice_respond'):
                self._ui_call(lambda r=reply: self._voice_respond(r))
            else:
                self._ui_call(lambda r=reply: self._add_message("Frank", r))

        except Exception as e:
            self._ui_call(self._hide_typing)
            self._ui_call(lambda err=e: self._add_message("Frank", f"Error: {err}", is_system=True))

    def _do_password_search_worker(self, query: str = "", voice: bool = False, **kwargs):
        """Search and show password in chat (auto-hide after 30s)."""
        self._ui_call(self._show_typing)
        try:
            import password_store

            if not password_store.is_unlocked():
                self._ui_call(self._hide_typing)
                self._ui_call(lambda: self._add_message(
                    "Frank", "Password store is locked. Open the password manager."
                ))
                self._ui_call(self._open_password_popup)
                return

            result = password_store.search_passwords(query)
            if not result.get("ok") or not result.get("entries"):
                self._ui_call(self._hide_typing)
                self._ui_call(lambda q=query: self._add_message(
                    "Frank", f"No password found for '{q}'."
                ))
                return

            # Get full entry for first match
            entry = result["entries"][0]
            full = password_store.get_password(entry["id"])
            if not full.get("ok"):
                self._ui_call(self._hide_typing)
                self._ui_call(lambda: self._add_message("Frank", "Decryption failed.", is_system=True))
                return

            e = full["entry"]
            reply = (
                f"🔑 {e['name']}:\n"
                f"  User: {e['username']}\n"
                f"  Pass: {e['password']}"
            )
            if e.get("url"):
                reply += f"\n  URL:  {e['url']}"

            self._ui_call(self._hide_typing)

            # Show password, then auto-hide after 30s
            msg_ref = [None]

            def _show():
                self._add_message("Frank", reply)
                # Schedule auto-hide
                self.after(30000, lambda: self._auto_hide_password(reply))

            if voice and hasattr(self, '_voice_respond'):
                self._ui_call(lambda r=reply: self._voice_respond(
                    f"Password for {e['name']}: Username {e['username']}"
                ))
            else:
                self._ui_call(_show)

        except Exception as e:
            self._ui_call(self._hide_typing)
            self._ui_call(lambda err=e: self._add_message("Frank", f"Error: {err}", is_system=True))

    def _auto_hide_password(self, original_text: str):
        """Replace password message with hidden placeholder after timeout."""
        try:
            if not hasattr(self, '_chat_canvas') or not hasattr(self, '_msg_widgets'):
                return
            # Find and replace the message content
            for widget_id, widget_data in list(getattr(self, '_msg_widgets', {}).items()):
                if hasattr(widget_data, 'get') and widget_data.get('text') == original_text:
                    # Try to update the message text
                    if 'label' in widget_data:
                        widget_data['label'].configure(text="[Password hidden after 30s]")
                    break
        except Exception:
            pass  # Best-effort auto-hide

    def _do_password_autotype_worker(self, query: str = "", **kwargs):
        """Auto-type login credentials via xdotool."""
        self._ui_call(self._show_typing)
        try:
            import password_store

            if not password_store.is_unlocked():
                self._ui_call(self._hide_typing)
                self._ui_call(lambda: self._add_message(
                    "Frank", "Password store is locked."
                ))
                self._ui_call(self._open_password_popup)
                return

            result = password_store.search_passwords(query)
            if not result.get("ok") or not result.get("entries"):
                self._ui_call(self._hide_typing)
                self._ui_call(lambda q=query: self._add_message(
                    "Frank", f"No password found for '{q}'."
                ))
                return

            entry = result["entries"][0]
            full = password_store.get_password(entry["id"])
            if not full.get("ok"):
                self._ui_call(self._hide_typing)
                return

            e = full["entry"]
            self._ui_call(self._hide_typing)
            self._do_autotype_credentials(e["username"], e["password"])

        except Exception as e:
            self._ui_call(self._hide_typing)
            self._ui_call(lambda err=e: self._add_message("Frank", f"Error: {err}", is_system=True))

    def _do_password_copy_worker(self, query: str = "", voice: bool = False, **kwargs):
        """Copy password to clipboard (auto-clear after 30s)."""
        self._ui_call(self._show_typing)
        try:
            import password_store

            if not password_store.is_unlocked():
                self._ui_call(self._hide_typing)
                self._ui_call(lambda: self._add_message(
                    "Frank", "Password store is locked."
                ))
                self._ui_call(self._open_password_popup)
                return

            result = password_store.search_passwords(query)
            if not result.get("ok") or not result.get("entries"):
                self._ui_call(self._hide_typing)
                self._ui_call(lambda q=query: self._add_message(
                    "Frank", f"No password found for '{q}'."
                ))
                return

            entry = result["entries"][0]
            full = password_store.get_password(entry["id"])
            if not full.get("ok"):
                self._ui_call(self._hide_typing)
                return

            pw = full["entry"]["password"]
            name = full["entry"]["name"]

            def _copy():
                self.clipboard_clear()
                self.clipboard_append(pw)

            self._ui_call(_copy)

            # Update clipboard hash to prevent capture by clipboard history
            import hashlib
            self._last_clipboard_hash = hashlib.sha256(
                pw.encode("utf-8", errors="replace")
            ).hexdigest()

            # Auto-clear clipboard after 30s
            self._ui_call(lambda: self.after(30000, self._clear_clipboard_after_copy))

            reply = f"Password for '{name}' copied! (will be cleared in 30s)"
            self._ui_call(self._hide_typing)
            if voice and hasattr(self, '_voice_respond'):
                self._ui_call(lambda r=reply: self._voice_respond(r))
            else:
                self._ui_call(lambda r=reply: self._add_message("Frank", r))

        except Exception as e:
            self._ui_call(self._hide_typing)
            self._ui_call(lambda err=e: self._add_message("Frank", f"Error: {err}", is_system=True))

    def _clear_clipboard_after_copy(self):
        """Clear clipboard after password was copied."""
        try:
            self.clipboard_clear()
            self.clipboard_append("")
        except Exception:
            pass
