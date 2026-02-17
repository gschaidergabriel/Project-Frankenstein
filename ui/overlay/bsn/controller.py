import json
import os
import subprocess
import threading
import time
from pathlib import Path
from overlay.constants import LOG
from overlay.bsn.constants import BSNConstants, get_workarea_y, get_workarea_x, get_workarea, get_primary_monitor
from overlay.bsn.negotiator import SpaceNegotiator
from overlay.bsn.positioner import WindowPositioner
from overlay.bsn.watcher import WindowWatcher


class LayoutController:
    """Central control of the BSN system."""

    def __init__(self, overlay):
        self.overlay = overlay
        self.negotiator = SpaceNegotiator(overlay)
        self.positioner = WindowPositioner(overlay)
        self.watcher = WindowWatcher(self)
        self._started = False

    def start(self):
        """Starts the layout system."""
        if self._started:
            return
        self._started = True
        self.watcher.start()
        # Check existing windows and adjust Frank if needed.
        # Delay 3s to run AFTER ADI profile restoration (which runs at t=3000ms from app start).
        # ADI applies saved profiles at t=3s, so we must check overlaps AFTER that.
        threading.Thread(target=self._startup_avoid_overlap, daemon=True).start()
        LOG.info("BSN: LayoutController started")

    def stop(self):
        """Stops the layout system."""
        self.watcher.stop()
        self._started = False

    def is_gaming_mode(self) -> bool:
        """Checks if gaming mode is active."""
        try:
            state_file = Path("/tmp/gaming_mode_state.json")
            if state_file.exists():
                data = json.loads(state_file.read_text())
                return data.get("active", False)
        except Exception:
            pass
        return False

    def _apply_geometry(self, geo_str: str):
        """Apply geometry on main thread (tkinter thread-safety)."""
        if getattr(self.overlay, '_dragging', False):
            LOG.info(f"BSN: Skipping geometry — user is dragging")
            return
        try:
            self.overlay.geometry(geo_str)
            self.overlay.update_idletasks()
            LOG.info(f"BSN: Geometry applied on main thread: {geo_str}")
            # After resize, scroll chat to bottom (bubble heights may need recalc)
            if hasattr(self.overlay, 'chat_canvas'):
                self.overlay.after(100, lambda: (
                    self.overlay.chat_canvas.configure(
                        scrollregion=self.overlay.chat_canvas.bbox("all")),
                    self.overlay.chat_canvas.yview_moveto(1.0),
                ))
        except Exception as e:
            LOG.error(f"BSN: Failed to apply geometry: {e}")

    def handle_new_window(self, win_id: str):
        """Called when a new window is detected."""
        try:
            # Signal fullscreen poller to ignore maximized states during positioning
            # (BSN is intentionally un-maximizing and repositioning this window)
            self.overlay._bsn_positioning_until = time.time() + 2.5

            layout = self.negotiator.negotiate()

            if layout["success"]:
                LOG.info(f"BSN: Layout negotiated - frank_action={layout['frank_action']}")
                self.positioner.apply_layout(layout, win_id)
            else:
                LOG.error("BSN: Layout negotiation failed!")
        except Exception as e:
            LOG.error(f"BSN: Error handling new window: {e}")

    def restore_frank(self):
        """Restore Frank after all fullscreen apps have closed."""
        def _restore():
            try:
                if not getattr(self.overlay, '_fullscreen_yielded', False):
                    self.overlay.attributes("-topmost", True)
                    self.overlay.lift()
                    LOG.info("BSN: Frank restored (fullscreen app closed)")
            except Exception as e:
                LOG.debug(f"BSN: Frank restore error: {e}")
        try:
            self.overlay.after(0, _restore)
        except Exception:
            pass

    def handle_fullscreen_app(self, win_id: str):
        """Handle apps that need the full primary monitor (Steam, etc.).

        Maximizes the app on the primary monitor and yields Frank to background.
        """
        try:
            self.positioner.maximize_on_primary(win_id)
            # Yield Frank: lower and remove topmost
            def _yield_frank():
                try:
                    self.overlay.attributes("-topmost", False)
                    self.overlay.lower()
                    LOG.info("BSN: Frank yielded for fullscreen app")
                except Exception as e:
                    LOG.debug(f"BSN: Frank yield error: {e}")
            self.overlay.after(0, _yield_frank)
        except Exception as e:
            LOG.error(f"BSN: Error handling fullscreen app: {e}")

    # ---------- Startup overlap avoidance ----------

    def _startup_avoid_overlap(self):
        """
        At startup, check existing windows and reposition/resize Frank
        to avoid overlapping them. Only adjusts if possible.
        """
        import time
        # Wait for ADI profile restoration (t=3s from app start) to complete
        # before checking overlaps. ADI applies saved profiles which can override
        # our positioning, so we must run AFTER ADI.
        time.sleep(3.5)

        # Respect ADI profile — if user has a saved display profile, don't override it
        if getattr(self.overlay, '_adi_profile_applied', False):
            LOG.info("BSN: ADI profile was applied — skipping startup repositioning")
            return

        try:
            env = {**os.environ, "DISPLAY": os.environ.get("DISPLAY", ":0")}
            existing = self._get_existing_window_rects(env)

            if not existing:
                LOG.info("BSN: No existing windows to avoid at startup")
                return

            LOG.info(f"BSN: Startup check - {len(existing)} existing window(s) found")

            # Filter: only consider windows on the primary monitor
            mon = get_primary_monitor()
            mon_right = mon["x"] + mon["width"]
            existing = [w for w in existing if w["x"] < mon_right]

            if not existing:
                LOG.info("BSN: No existing windows on primary monitor to avoid")
                return

            frank = {
                "x": self.overlay.winfo_x(),
                "y": self.overlay.winfo_y(),
                "width": self.overlay.winfo_width(),
                "height": self.overlay.winfo_height(),
            }

            # Check if Frank overlaps any existing window
            overlapping = self._find_overlaps(frank, existing)
            if not overlapping:
                LOG.info("BSN: Frank doesn't overlap any existing windows")
                return

            overlap_names = [w.get("title", "?")[:40] for w in overlapping]
            LOG.info(
                f"BSN: Frank overlaps {len(overlapping)} window(s): {overlap_names}, "
                f"trying to find better position"
            )

            wa = get_workarea()
            current_area = self._overlap_area(frank, existing)
            best = self._find_best_frank_position(frank, existing, wa)

            if best:
                fewer_overlaps = best["score"] < len(overlapping)
                less_area = best.get("overlap_area", current_area) < current_area * 0.7
                if fewer_overlaps or less_area:
                    geo_str = f"{best['width']}x{best['height']}+{best['x']}+{best['y']}"
                    LOG.info(
                        f"BSN: Repositioning Frank: {geo_str} "
                        f"(overlaps: {len(overlapping)}->{best['score']}, "
                        f"area: {current_area}->{best.get('overlap_area', '?')})"
                    )
                    # CRITICAL: tkinter is NOT thread-safe!
                    # Must schedule geometry change on the main thread via after()
                    self.overlay.after(0, lambda g=geo_str: self._apply_geometry(g))
                else:
                    LOG.info(
                        f"BSN: No significant improvement found "
                        f"(best: {best['score']} overlaps, area={best.get('overlap_area', '?')} "
                        f"vs current: {len(overlapping)} overlaps, area={current_area})"
                    )
            else:
                LOG.info("BSN: No candidate positions generated")

        except Exception as e:
            LOG.warning(f"BSN: Startup overlap avoidance error: {e}")

    def _get_existing_window_rects(self, env: dict) -> list:
        """Get rectangles of all real user windows (excluding Frank, wallpaper, dialogs).

        Uses wmctrl for window listing but xdotool for ACTUAL geometry,
        because wmctrl can report wrong coordinates on scaled displays.
        """
        windows = []
        try:
            # Get window list from wmctrl
            result = subprocess.run(
                ["wmctrl", "-l"],
                capture_output=True, text=True, timeout=3, env=env,
            )
            for line in result.stdout.strip().split("\n"):
                if not line:
                    continue
                parts = line.split(None, 4)
                if len(parts) < 5:
                    continue

                win_id = parts[0]
                desktop = parts[1]
                title = parts[4] if len(parts) > 4 else ""
                title_lower = title.lower()

                # Skip special windows
                if desktop == "-1":
                    continue
                if "f.r.a.n.k" in title_lower:
                    continue
                if "frank neural core" in title_lower or "cybercore" in title_lower:
                    continue

                # Get ACTUAL geometry via xdotool (wmctrl can be 2x wrong on scaled displays)
                geo = self._xdotool_geometry(win_id, env)
                if not geo:
                    continue

                x, y, w, h = geo["x"], geo["y"], geo["width"], geo["height"]

                # Skip tiny windows (dialogs, popups)
                if w < 200 or h < 150:
                    continue

                windows.append({"x": x, "y": y, "width": w, "height": h, "title": title})
        except Exception as e:
            LOG.debug(f"BSN: Error getting window rects: {e}")

        return windows

    def _xdotool_geometry(self, win_id: str, env: dict) -> dict:
        """Get actual window geometry via xdotool (pixel-accurate)."""
        try:
            result = subprocess.run(
                ["xdotool", "getwindowgeometry", "--shell", win_id],
                capture_output=True, text=True, timeout=2, env=env,
            )
            geo = {}
            for line in result.stdout.strip().split("\n"):
                if "=" in line:
                    k, v = line.split("=", 1)
                    geo[k] = int(v)
            if "X" in geo and "Y" in geo and "WIDTH" in geo and "HEIGHT" in geo:
                return {"x": geo["X"], "y": geo["Y"], "width": geo["WIDTH"], "height": geo["HEIGHT"]}
        except Exception:
            pass
        return None

    def _find_overlaps(self, frank: dict, windows: list) -> list:
        """Find which windows Frank overlaps with."""
        overlapping = []
        fx1, fy1 = frank["x"], frank["y"]
        fx2, fy2 = fx1 + frank["width"], fy1 + frank["height"]

        for win in windows:
            wx1, wy1 = win["x"], win["y"]
            wx2, wy2 = wx1 + win["width"], wy1 + win["height"]

            # Check rectangle overlap
            if fx1 < wx2 and fx2 > wx1 and fy1 < wy2 and fy2 > wy1:
                overlapping.append(win)

        return overlapping

    def _overlap_area(self, frank: dict, windows: list) -> int:
        """Calculate total overlap area in pixels between Frank and all windows."""
        total = 0
        fx1, fy1 = frank["x"], frank["y"]
        fx2, fy2 = fx1 + frank["width"], fy1 + frank["height"]

        for win in windows:
            wx1, wy1 = win["x"], win["y"]
            wx2, wy2 = wx1 + win["width"], wy1 + win["height"]

            # Intersection rectangle
            ix1 = max(fx1, wx1)
            iy1 = max(fy1, wy1)
            ix2 = min(fx2, wx2)
            iy2 = min(fy2, wy2)

            if ix1 < ix2 and iy1 < iy2:
                total += (ix2 - ix1) * (iy2 - iy1)

        return total

    def _find_best_frank_position(self, frank: dict, windows: list, wa: dict) -> dict:
        """
        Find the best position for Frank that minimizes window overlaps.
        All positions are constrained to the PRIMARY monitor.

        Strategy:
        1. Generate candidates from gaps between windows
        2. Try fitting Frank just LEFT of each window's left edge
        3. Try fitting Frank just RIGHT of each window's right edge
        4. Also try fixed positions (left/right of workarea)
        5. For each position, try multiple widths (current, shrunk, minimum)
        6. Score each candidate by overlap count, prefer fewer overlaps + wider Frank

        Returns best candidate dict with 'score' field, or None.
        """
        min_y = wa["y"]
        # Use PRIMARY monitor right edge, NOT total workarea (which spans all monitors)
        mon = get_primary_monitor()
        screen_right = mon["x"] + mon["width"]
        frank_h = frank["height"]
        gap = BSNConstants.GAP

        # Collect all candidate X positions to try
        x_candidates = set()

        # Fixed positions
        x_candidates.add(wa["x"] + 1)     # Left of workarea (right of dock)
        x_candidates.add(wa["x"])          # Exactly at dock edge

        # Just left of each window (Frank ends before window starts)
        for win in windows:
            x_candidates.add(wa["x"] + 1)  # Leftmost possible
            # Right of each window
            win_right = win["x"] + win["width"]
            if win_right < screen_right:
                x_candidates.add(win_right + gap)

        # Widths to try (prefer wider)
        widths = sorted(set([
            frank["width"],
            BSNConstants.FRANK_DEFAULT_WIDTH,
            BSNConstants.FRANK_MIN_WIDTH,
            # Also try widths that fit exactly in gaps
        ]), reverse=True)

        # For each window, calculate width that fits just before it
        for win in windows:
            fit_width = win["x"] - wa["x"] - gap - 1
            if BSNConstants.FRANK_MIN_WIDTH <= fit_width <= frank["width"]:
                widths.append(fit_width)
        # Also try from right side
        for win in windows:
            win_right = win["x"] + win["width"]
            fit_width = screen_right - win_right - gap
            if BSNConstants.FRANK_MIN_WIDTH <= fit_width <= frank["width"]:
                widths.append(fit_width)

        widths = sorted(set(widths), reverse=True)  # Prefer wider

        best = None
        best_overlap_count = float("inf")
        best_overlap_area = float("inf")
        best_width = 0

        for width in widths:
            for x in x_candidates:
                # Also try right-aligned for this width
                for try_x in [x, screen_right - width]:
                    # Bounds check
                    if try_x < 0 or try_x + width > screen_right:
                        continue

                    candidate = {
                        "x": try_x,
                        "y": min_y,
                        "width": width,
                        "height": frank_h,
                    }

                    overlap_count = len(self._find_overlaps(candidate, windows))
                    overlap_area = self._overlap_area(candidate, windows)

                    # Score: primary = overlap count, secondary = overlap area,
                    # tertiary = prefer wider Frank (negative width)
                    is_better = False
                    if overlap_count < best_overlap_count:
                        is_better = True
                    elif overlap_count == best_overlap_count:
                        if overlap_area < best_overlap_area:
                            is_better = True
                        elif overlap_area == best_overlap_area and width > best_width:
                            is_better = True

                    if is_better:
                        best = candidate
                        best_overlap_count = overlap_count
                        best_overlap_area = overlap_area
                        best_width = width

                    # Perfect position found
                    if overlap_count == 0:
                        best["score"] = 0
                        best["overlap_area"] = 0
                        return best

        if best:
            best["score"] = best_overlap_count
            best["overlap_area"] = best_overlap_area
        return best
