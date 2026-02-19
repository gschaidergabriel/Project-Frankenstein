"""Lifecycle mixin -- destroy, FAS polling, restore signal, ADI, and BSN layout controller.

Methods rely on self.* attributes provided by the assembled ChatOverlay
at runtime via MRO.
"""

import json
import os
import signal
import time
from pathlib import Path

from overlay.constants import LOG
from overlay.bsn.constants import (
    get_workarea_y, get_workarea_x, get_workarea,
    BSNConstants, get_primary_monitor,
)
from overlay.bsn.controller import LayoutController

try:
    from config.paths import get_state
    _LAST_MONITOR_FILE = get_state("last_monitor")  # creates parent if needed
    _SESSION_FILE = get_state("frank_session")
except ImportError:
    _LAST_MONITOR_FILE = Path.home() / ".local" / "share" / "frank" / "state" / "last_monitor.json"
    _SESSION_FILE = Path.home() / ".local" / "share" / "frank" / "state" / "frank_session.json"
try:
    from config.paths import TEMP_FILES as _LM_TF
    USER_CLOSED_SIGNAL = _LM_TF["user_closed"]
    GAMING_LOCK = _LM_TF["gaming_lock"]
except ImportError:
    USER_CLOSED_SIGNAL = Path("/tmp/frank/user_closed")
    GAMING_LOCK = Path("/tmp/frank/gaming_lock")

# Shutdown reasons — only USER_INITIATED writes the user_closed signal
SHUTDOWN_USER = "user_closed"        # User clicked X or tray quit
SHUTDOWN_SIGNAL = "signal"           # SIGTERM from systemd/gaming mode
SHUTDOWN_WRITER = "writer"           # Writer mode taking over
SHUTDOWN_GAMING = "gaming"           # Gaming mode stopping overlay
SHUTDOWN_CRASH = "crash"             # Unhandled exception


class LifecycleMixin:

    # Set by external code before destroy() to control behavior
    _shutdown_reason: str = SHUTDOWN_USER  # default: assume user-initiated

    def register_signal_handlers(self):
        """Register SIGTERM/SIGINT handlers for graceful shutdown.

        Call this from ChatOverlay.__init__() AFTER mainloop is set up.
        SIGTERM from systemd/gaming mode should NOT write user_closed signal,
        so the watchdog will auto-restart the overlay.
        """
        def _on_sigterm(signum, frame):
            sig_name = "SIGTERM" if signum == signal.SIGTERM else "SIGINT"
            LOG.info(f"Received {sig_name} — graceful shutdown (no user_closed signal)")
            self._shutdown_reason = SHUTDOWN_SIGNAL
            # Schedule destroy on the Tk main thread (signal handlers run on main thread)
            try:
                self.after(0, self.destroy)
            except Exception:
                # If Tk is already dead, just exit
                self._cleanup_without_tk()
                os._exit(0)

        signal.signal(signal.SIGTERM, _on_sigterm)
        # Keep SIGINT for Ctrl+C during development
        signal.signal(signal.SIGINT, _on_sigterm)

    def _cleanup_without_tk(self):
        """Minimal cleanup when Tk is unavailable (crash/signal during shutdown)."""
        try:
            if hasattr(self, '_chat_memory_db'):
                self._chat_memory_db.end_session(getattr(self, '_memory_session_id', ''))
                self._chat_memory_db.close()
        except Exception:
            pass
        # Remove singleton lock
        try:
            from overlay.constants import LOCK_FILE
            LOCK_FILE.unlink(missing_ok=True)
        except Exception:
            pass

    def destroy(self):
        """Override destroy to cleanup BSN LayoutController, Genesis Watcher, and tray icon.

        Only writes the user_closed signal if shutdown was USER-initiated.
        Signal-based shutdowns (SIGTERM from systemd/gaming) do NOT write it,
        allowing the watchdog to auto-restart.
        """
        reason = getattr(self, '_shutdown_reason', SHUTDOWN_USER)

        if reason == SHUTDOWN_USER:
            # User explicitly closed — tell watchdog NOT to auto-restart
            try:
                USER_CLOSED_SIGNAL.write_text(json.dumps({
                    "timestamp": time.time(),
                    "reason": reason,
                }))
                LOG.info(f"User close signal written (reason={reason}) — watchdog will not auto-restart")
            except Exception as e:
                LOG.debug(f"Failed to write user-close signal: {e}")
        else:
            LOG.info(f"Shutdown reason={reason} — NOT writing user_closed signal (watchdog may restart)")

        # End chat memory session and trigger summary generation
        if hasattr(self, '_chat_memory_db'):
            try:
                self._chat_memory_db.end_session(self._memory_session_id)
                self._trigger_session_summary()
                self._chat_memory_db.close()
            except Exception as e:
                LOG.debug(f"Chat memory shutdown: {e}")

        # Clear DOCK strut before destroying window
        try:
            from overlay.dock_hints import clear_strut
            xid = getattr(self, '_dock_xid', self.winfo_id())
            clear_strut(xid)
        except Exception:
            pass

        self._stop_layout_controller()
        if hasattr(self, '_genesis_watcher'):
            self._genesis_watcher.stop()
        try:
            from overlay.tray_icon import stop_tray_icon
            stop_tray_icon()
        except Exception:
            pass
        super().destroy()

    # ---------- FAS dimming ----------

    def _poll_fas_dim_signal(self):
        """Check for FAS popup dim signal and respond."""
        try:
            if self._fas_dim_signal_file.exists():
                if not self._fas_dimmed:
                    print("[FAS-DIM] Signal detected, dimming overlay...")
                    self._dim_for_fas()
            else:
                if self._fas_dimmed:
                    print("[FAS-DIM] Signal removed, restoring overlay...")
                    self._restore_from_fas()
        except Exception as e:
            print(f"[FAS-DIM] Error: {e}")
        self.after(200, self._poll_fas_dim_signal)

    def _restore_from_fas(self):
        """Restore this overlay after F.A.S. popup closes."""
        try:
            self._fas_dimmed = False
            self.attributes("-alpha", self._fas_original_alpha)
        except Exception as e:
            print(f"Frank restore error: {e}")

    def _dim_for_fas(self):
        """Dim this overlay for F.A.S. popup focus."""
        try:
            self._fas_dimmed = True
            self.attributes("-alpha", 0.3)
        except Exception as e:
            print(f"Frank dim error: {e}")

    # ---------- Restore signal ----------

    def _poll_restore_signal(self):
        """Check for restore signal and show the overlay window."""
        try:
            if self._restore_signal_file.exists():
                LOG.info("Restore signal detected, showing overlay...")
                self._restore_signal_file.unlink()
                self._restore_window()
        except Exception as e:
            LOG.debug(f"Restore signal poll error: {e}")
        self.after(500, self._poll_restore_signal)

    def _restore_window(self):
        """Restore the window to visible state WITHOUT stealing focus."""
        try:
            self._show_overlay()
            LOG.info("Overlay window restored (no focus steal)")
        except Exception as e:
            LOG.error(f"Window restore error: {e}")

    # ---------- Tray quit signal ----------

    def _poll_tray_quit_signal(self):
        """Poll for tray quit signal and destroy overlay if found."""
        try:
            try:
                from config.paths import get_temp as _get_temp_tq
                quit_signal = _get_temp_tq("tray_quit")
            except ImportError:
                quit_signal = Path("/tmp/frank/tray_quit")
            if quit_signal.exists():
                quit_signal.unlink(missing_ok=True)
                LOG.info("Tray quit signal received — destroying overlay")
                self.destroy()
                return  # Don't reschedule after destroy
        except Exception as e:
            LOG.debug(f"Tray quit poll error: {e}")
        self.after(500, self._poll_tray_quit_signal)

    # ---------- Tray signal polling ----------

    def _poll_tray_signals(self):
        """Poll for tray icon toggle signal file with cooldown protection."""
        try:
            from overlay.tray_icon import TRAY_TOGGLE_SIGNAL
            if TRAY_TOGGLE_SIGNAL.exists():
                TRAY_TOGGLE_SIGNAL.unlink(missing_ok=True)
                # Cooldown: ignore signals within 1.5s of last action
                now = time.time()
                last = getattr(self, '_last_tray_action_ts', 0.0)
                if now - last < 1.5:
                    LOG.debug("Tray signal ignored (cooldown)")
                else:
                    self._last_tray_action_ts = now
                    hidden = getattr(self, '_overlay_hidden', False)
                    minimized = getattr(self, '_overlay_minimized', False)
                    state = self.state() if self.winfo_exists() else "dead"
                    LOG.info("Tray toggle signal received (hidden=%s, minimized=%s, state=%s)",
                             hidden, minimized, state)
                    if hidden or minimized or state != "normal":
                        self._show_overlay()
                    else:
                        self._minimize_overlay()
        except Exception as e:
            LOG.warning(f"Tray signal poll error: {e}")
        finally:
            self.after(300, self._poll_tray_signals)

    # ---------- BSN Layout Controller ----------

    def _start_layout_controller(self):
        """Start BSN LayoutController after window is ready."""
        try:
            self._layout_controller.start()
            LOG.info("BSN: LayoutController started successfully")
        except Exception as e:
            LOG.error(f"BSN: Failed to start LayoutController: {e}")

    def _stop_layout_controller(self):
        """Stop BSN LayoutController."""
        try:
            if hasattr(self, '_layout_controller'):
                self._layout_controller.stop()
        except Exception as e:
            LOG.error(f"BSN: Failed to stop LayoutController: {e}")

    # ---------- ADI (Adaptive Display Intelligence) ----------

    def _check_monitor_on_startup(self):
        """Check if current monitor changed. Only show message on genuine change."""
        try:
            from ui.adi_popup.monitor_detector import get_primary_monitor, is_monitor_known

            monitor = get_primary_monitor()
            if not monitor:
                return

            current_edid = monitor.edid_hash
            last_edid = self._read_last_monitor_edid()
            is_same_monitor = (last_edid == current_edid)
            is_restart = self._is_overlay_restart()

            # Always persist current EDID
            self._write_last_monitor_edid(current_edid, monitor.get_display_name())

            if is_monitor_known(current_edid):
                # Profile exists -- silently apply it
                LOG.info(f"Known monitor detected: {monitor.get_display_name()}")
                self._apply_display_profile(current_edid)
            elif is_same_monitor or is_restart:
                # Same monitor or just an overlay restart -- don't bother user
                LOG.info(f"Monitor unchanged ({monitor.get_display_name()}), skipping prompt")
            else:
                # Genuinely new monitor -- inform the user
                LOG.info(f"New monitor detected: {monitor.get_display_name()}")
                self._add_message(
                    "Frank",
                    f"New monitor detected: **{monitor.get_display_name()}** ({monitor.width}x{monitor.height}). "
                    f"Let me know if you'd like to adjust the layout.",
                    is_system=True
                )
        except ImportError as e:
            LOG.debug(f"ADI module not available: {e}")
        except Exception as e:
            LOG.warning(f"Monitor check failed: {e}")

    def _read_last_monitor_edid(self) -> str:
        """Read the last known monitor EDID hash from persistent storage."""
        try:
            if _LAST_MONITOR_FILE.exists():
                data = json.loads(_LAST_MONITOR_FILE.read_text())
                return data.get("edid_hash", "")
        except Exception:
            pass
        return ""

    def _write_last_monitor_edid(self, edid_hash: str, display_name: str):
        """Persist the current monitor EDID hash."""
        try:
            _LAST_MONITOR_FILE.parent.mkdir(parents=True, exist_ok=True)
            _LAST_MONITOR_FILE.write_text(json.dumps({
                "edid_hash": edid_hash,
                "display_name": display_name,
                "timestamp": time.time(),
            }))
        except Exception as e:
            LOG.debug(f"Failed to write last monitor file: {e}")

    def _is_overlay_restart(self) -> bool:
        """Detect if this is an overlay restart within the same boot session."""
        try:
            if _SESSION_FILE.exists():
                data = json.loads(_SESSION_FILE.read_text())
                stored_boot_id = data.get("boot_id", "")
                current_boot_id = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
                return stored_boot_id == current_boot_id
        except Exception:
            pass
        return False

    def _apply_display_profile(self, edid_hash: str):
        """Apply saved display profile to Frank window (DOCK mode: width + opacity only)."""
        try:
            from ui.adi_popup.profile_manager import load_profile

            profile = load_profile(edid_hash)
            if not profile:
                return

            frank = profile.get("frank_layout", {})
            if not frank:
                return

            # DOCK mode: position and height are fixed, only width is configurable
            width = frank.get("width", BSNConstants.FRANK_DEFAULT_WIDTH)
            width = max(BSNConstants.FRANK_MIN_WIDTH, width)
            cur_h = self.winfo_height()
            dock_x = getattr(self, '_dock_x', get_workarea_x())
            dock_y = getattr(self, '_workarea_y', get_workarea_y())

            self.geometry(f"{width}x{cur_h}+{dock_x}+{dock_y}")
            self._adi_profile_applied = True
            LOG.info(f"Applied display profile (DOCK): width={width}")

            # Update strut for new width
            if hasattr(self, '_update_strut'):
                self.update_idletasks()
                self._update_strut()

            opacity = frank.get("opacity", 0.95)
            try:
                self.attributes("-alpha", opacity)
            except Exception:
                pass

        except Exception as e:
            LOG.warning(f"Failed to apply display profile: {e}")

    def _poll_adi_apply_signal(self):
        """Poll for ADI apply signal file and apply profile if found."""
        try:
            from config.paths import get_temp as _get_temp_adi
            signal_file = _get_temp_adi("adi_apply_signal")
        except ImportError:
            signal_file = Path("/tmp/frank/adi_apply_signal")
        try:
            if signal_file.exists():
                edid_hash = signal_file.read_text().strip()
                signal_file.unlink()
                if edid_hash:
                    LOG.info(f"ADI apply signal received for: {edid_hash}")
                    self._apply_display_profile(edid_hash)
        except Exception as e:
            LOG.debug(f"ADI signal poll error: {e}")
        self.after(2000, self._poll_adi_apply_signal)

