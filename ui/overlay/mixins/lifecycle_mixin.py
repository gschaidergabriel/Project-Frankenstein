"""Lifecycle mixin -- destroy, FAS polling, restore signal, ADI, and BSN layout controller.

Methods rely on self.* attributes provided by the assembled ChatOverlay
at runtime via MRO.
"""

import json
import os
import subprocess
import time
from pathlib import Path

from overlay.constants import LOG
from overlay.bsn.constants import get_workarea_y, get_workarea_x
from overlay.bsn.controller import LayoutController

try:
    from config.paths import get_state
    _LAST_MONITOR_FILE = get_state("last_monitor")  # creates parent if needed
    _SESSION_FILE = get_state("frank_session")
except ImportError:
    _LAST_MONITOR_FILE = Path("/home/ai-core-node/.local/share/frank/state/last_monitor.json")
    _SESSION_FILE = Path("/home/ai-core-node/.local/share/frank/state/frank_session.json")
USER_CLOSED_SIGNAL = Path("/tmp/frank_user_closed")


class LifecycleMixin:

    def destroy(self):
        """Override destroy to cleanup BSN LayoutController, Genesis Watcher, and tray icon."""
        # Signal that the USER closed the overlay (not a crash).
        # The watchdog reads this and will NOT auto-restart frank-overlay.
        try:
            USER_CLOSED_SIGNAL.write_text(json.dumps({
                "timestamp": time.time(),
                "reason": "user_closed",
            }))
            LOG.info("User close signal written — watchdog will not auto-restart")
        except Exception as e:
            LOG.debug(f"Failed to write user-close signal: {e}")

        # End chat memory session and trigger summary generation
        if hasattr(self, '_chat_memory_db'):
            try:
                self._chat_memory_db.end_session(self._memory_session_id)
                self._trigger_session_summary()
                self._chat_memory_db.close()
            except Exception as e:
                LOG.debug(f"Chat memory shutdown: {e}")

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
            if not getattr(self, '_fullscreen_yielded', False):
                self.attributes("-topmost", True)
            self.attributes("-alpha", self._fas_original_alpha)
            self.lift()
        except Exception as e:
            print(f"Frank restore error: {e}")

    def _dim_for_fas(self):
        """Dim this overlay for F.A.S. popup focus."""
        try:
            self._fas_dimmed = True
            self.attributes("-topmost", False)
            self.attributes("-alpha", 0.3)
            self.lower()
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
            quit_signal = Path("/tmp/frank_tray_quit")
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

    # ---------- Fullscreen detection ----------

    def _poll_fullscreen(self):
        """Detect if another window is fullscreen and yield topmost."""
        try:
            result = subprocess.run(
                ['xdotool', 'getactivewindow'],
                capture_output=True, text=True, timeout=2,
                env={**os.environ, 'DISPLAY': ':0'}
            )
            active_wid = result.stdout.strip()
            if active_wid:
                prop = subprocess.run(
                    ['xprop', '-id', active_wid, '_NET_WM_STATE'],
                    capture_output=True, text=True, timeout=2,
                    env={**os.environ, 'DISPLAY': ':0'}
                )
                is_fullscreen = '_NET_WM_STATE_FULLSCREEN' in prop.stdout

                if is_fullscreen and not self._fullscreen_yielded:
                    self._fullscreen_yielded = True
                    self.attributes("-topmost", False)
                    self.lower()
                    LOG.info("Fullscreen detected — overlay yielded topmost")
                elif not is_fullscreen and self._fullscreen_yielded:
                    self._fullscreen_yielded = False
                    if not self._fas_dimmed:
                        self.attributes("-topmost", True)
                        LOG.info("Fullscreen exited — overlay topmost restored")
        except Exception as e:
            LOG.debug(f"Fullscreen poll error: {e}")
        self.after(500, self._poll_fullscreen)

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
        """Apply saved display profile to Frank window."""
        try:
            from ui.adi_popup.profile_manager import load_profile

            profile = load_profile(edid_hash)
            if not profile:
                return

            frank = profile.get("frank_layout", {})
            if not frank:
                return

            width = frank.get("width", 420)
            height = frank.get("height", 720)
            x = frank.get("x", get_workarea_x() + 1)
            y = frank.get("y", get_workarea_y())

            # Enforce: NEVER above GNOME panel
            min_y = get_workarea_y()
            if y < min_y:
                LOG.warning(f"ADI profile y={y} below panel height {min_y}, clamping")
                y = min_y

            self.geometry(f"{width}x{height}+{x}+{y}")
            self._adi_profile_applied = True  # Flag for BSN: don't reposition
            LOG.info(f"Applied display profile: {width}x{height}+{x}+{y}")

            opacity = frank.get("opacity", 0.95)
            try:
                self.attributes("-alpha", opacity)
            except Exception:
                pass

        except Exception as e:
            LOG.warning(f"Failed to apply display profile: {e}")

    def _poll_adi_apply_signal(self):
        """Poll for ADI apply signal file and apply profile if found."""
        signal_file = Path("/tmp/frank_adi_apply_signal")
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

    # ---------- Panel Boundary Enforcement ----------

    def _enforce_panel_boundary(self):
        """
        Ensure the overlay is NEVER above the GNOME panel or left of the dock.

        This is the single authoritative method that enforces correct positioning.
        Called at startup (multiple times), after focus hacks, after ADI profiles,
        after restore, and periodically.
        """
        try:
            if not self.winfo_exists():
                return

            y = self.winfo_y()
            x = self.winfo_x()
            min_y = get_workarea_y()
            min_x = 0  # Allow at screen edge, but not negative

            needs_fix = False
            new_y = y
            new_x = x

            if y < min_y:
                new_y = min_y
                needs_fix = True
            if x < min_x:
                new_x = min_x
                needs_fix = True

            if needs_fix:
                if getattr(self, '_dragging', False):
                    return  # Never interfere with user drag
                LOG.warning(
                    f"Panel boundary violated: was ({x},{y}), "
                    f"correcting to ({new_x},{new_y}) [min_y={min_y}]"
                )
                self.geometry(f"+{new_x}+{new_y}")
                self.update_idletasks()
        except Exception as e:
            LOG.debug(f"Panel enforcement error: {e}")

    def _periodic_panel_enforcement(self):
        """Periodic check that runs every 10 seconds to catch any position drift."""
        try:
            self._enforce_panel_boundary()
        except Exception:
            pass
        self.after(10000, self._periodic_panel_enforcement)
