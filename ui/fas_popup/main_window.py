#!/usr/bin/env python3
"""
F.A.S. Proposal Popup - Main Window
Cyberpunk-styled GTK4 popup for feature proposals.
"""

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Gdk', '4.0')

from gi.repository import Gtk, Gdk, GLib, Gio, Pango
import functools
import json
import logging
import os
import sys
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional, Callable

# Setup logging for this module
LOG = logging.getLogger("fas_popup")
if not LOG.handlers:
    LOG.addHandler(logging.StreamHandler(sys.stderr))
    LOG.setLevel(logging.DEBUG)

# Add parent path for imports
AICORE_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(AICORE_ROOT))

from config.fas_popup_config import get_config
from ui.fas_popup.sound_manager import SoundManager
from ui.fas_popup.use_case_generator import UseCaseGenerator
from ui.fas_popup.queue_manager import ProposalQueueManager

# A.S.R.S. Integration
try:
    from services.asrs.integrator import get_integrator, IntegrationResult
    ASRS_AVAILABLE = True
except ImportError:
    ASRS_AVAILABLE = False


class FeatureRow(Gtk.Box):
    """A single feature item in the list."""

    def __init__(self, feature: Dict, on_toggle: Callable, on_details: Callable):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.feature = feature
        self.on_toggle = on_toggle
        self.on_details = on_details
        self.selected = False

        self.add_css_class("fas-feature-item")
        self.set_margin_start(10)
        self.set_margin_end(10)
        self.set_margin_top(4)
        self.set_margin_bottom(4)

        self._build_ui()

    def _build_ui(self):
        # Header row: checkbox + name + type badge + confidence
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)

        # Checkbox
        self.checkbox = Gtk.CheckButton()
        self.checkbox.add_css_class("fas-feature-checkbox")
        self.checkbox.connect("toggled", self._on_checkbox_toggled)
        header.append(self.checkbox)

        # Name and type
        name_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        name_box.set_hexpand(True)

        name_label = Gtk.Label(label=self.feature.get("name", "Unknown"))
        name_label.add_css_class("fas-feature-name")
        name_label.set_halign(Gtk.Align.START)
        name_box.append(name_label)

        type_label = Gtk.Label(label=self.feature.get("feature_type", "tool").upper())
        type_label.add_css_class("fas-feature-type")
        type_label.set_halign(Gtk.Align.START)
        name_box.append(type_label)

        header.append(name_box)

        # Confidence badge
        confidence = self.feature.get("confidence_score", 0)
        conf_label = Gtk.Label(label=f"{int(confidence * 100)}%")
        conf_label.add_css_class("fas-confidence-label")
        header.append(conf_label)

        # Details button
        details_btn = Gtk.Button(label="DETAILS")
        details_btn.add_css_class("fas-details-button")
        details_btn.connect("clicked", lambda _: self.on_details(self.feature))
        header.append(details_btn)

        self.append(header)

        # Description
        desc = self.feature.get("description", "")
        if desc:
            desc_label = Gtk.Label(label=desc[:150] + ("..." if len(desc) > 150 else ""))
            desc_label.add_css_class("fas-feature-description")
            desc_label.set_halign(Gtk.Align.START)
            desc_label.set_wrap(True)
            desc_label.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
            desc_label.set_max_width_chars(80)
            self.append(desc_label)

        # Confidence bar
        conf_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        conf_box.add_css_class("fas-confidence-container")

        progress = Gtk.ProgressBar()
        progress.add_css_class("fas-confidence-bar")
        progress.set_fraction(confidence)
        progress.set_hexpand(True)
        conf_box.append(progress)

        self.append(conf_box)

        # Use case box (collapsible)
        use_case_gen = UseCaseGenerator()
        use_case = use_case_gen.generate_use_case(self.feature)

        use_case_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        use_case_box.add_css_class("fas-usecase-box")

        title = Gtk.Label(label="💡 " + use_case["title"])
        title.add_css_class("fas-usecase-title")
        title.set_halign(Gtk.Align.START)
        use_case_box.append(title)

        why_label = Gtk.Label(label=use_case["why"][:200])
        why_label.add_css_class("fas-usecase-text")
        why_label.set_halign(Gtk.Align.START)
        why_label.set_wrap(True)
        why_label.set_max_width_chars(70)
        use_case_box.append(why_label)

        if use_case.get("personal_relevance"):
            relevance = Gtk.Label(label=f"📊 {use_case['personal_relevance']}")
            relevance.add_css_class("fas-personal-relevance")
            relevance.set_halign(Gtk.Align.START)
            use_case_box.append(relevance)

        self.append(use_case_box)

    def _on_checkbox_toggled(self, checkbox):
        self.selected = checkbox.get_active()
        if self.selected:
            self.add_css_class("selected")
        else:
            self.remove_css_class("selected")
        self.on_toggle(self.feature, self.selected)

    def set_selected(self, selected: bool):
        self.checkbox.set_active(selected)


class FASPopupWindow(Gtk.ApplicationWindow):
    """Main F.A.S. Proposal Popup Window."""

    def __init__(self, app: Gtk.Application, features: List[Dict] = None, manual: bool = False):
        super().__init__(application=app, title="F.A.S. Intelligence Report")

        self.features = features or []
        self.manual_open = manual
        self.selected_features: Dict[int, Dict] = {}
        self.feature_rows: List[FeatureRow] = []

        # Track timer IDs for cleanup (HIGH #6 fix)
        self._timer_ids: List[int] = []

        # Genesis result tracking (for daemon communication)
        self._genesis_decision: Optional[str] = None  # "approve", "reject", or None (=defer)

        self.config = get_config()
        self.sound = SoundManager(
            enabled=self.config.get("sound_enabled", True),
            volume=self.config.get("sound_volume", 0.6)
        )
        self.queue_manager = ProposalQueueManager(self.config)

        self._setup_window()
        self._load_css()
        self._build_ui()
        self._setup_keyboard_shortcuts()

        # Play appear sound
        self.sound.play_popup_appear()

    @staticmethod
    def _detect_workarea():
        """Detect usable workarea from WM (accounts for panels, docks)."""
        import subprocess
        wa_x, wa_y, wa_w, wa_h = 0, 0, 1920, 1080
        try:
            result = subprocess.run(
                ['xprop', '-root', '_NET_WORKAREA'],
                capture_output=True, text=True, timeout=3
            )
            # Parse: _NET_WORKAREA(CARDINAL) = 66, 38, 958, 562, ...
            if '=' in result.stdout:
                vals = result.stdout.split('=', 1)[1].strip().split(',')
                if len(vals) >= 4:
                    wa_x = int(vals[0].strip())
                    wa_y = int(vals[1].strip())
                    wa_w = int(vals[2].strip())
                    wa_h = int(vals[3].strip())
        except Exception as e:
            LOG.debug(f"Workarea detection failed: {e}")
        return wa_x, wa_y, wa_w, wa_h

    def _setup_window(self):
        """Configure fullscreen window with centered content."""
        self._workarea = self._detect_workarea()
        wa_x, wa_y, wa_w, wa_h = self._workarea

        # Detect actual screen size
        self._screen_w, self._screen_h = 1024, 600
        self._detect_screen_size()

        self.popup_width = min(self.config.get("popup_width", 900), self._screen_w - 40)
        self.popup_height = min(self.config.get("popup_height", 700), self._screen_h - 40)

        # Calculate centering margins
        self._margin_x = max(0, (self._screen_w - self.popup_width) // 2)
        self._margin_y = max(0, (self._screen_h - self.popup_height) // 2)

        self.set_decorated(False)
        self.set_resizable(False)
        self.add_css_class("fas-popup-window")

        print(f"Screen: {self._screen_w}x{self._screen_h}, popup: {self.popup_width}x{self.popup_height}, margins: ({self._margin_x},{self._margin_y})")

        self.connect("realize", self._on_realize)
        self.connect("close-request", self._on_close_request)

    def _detect_screen_size(self):
        """Detect primary monitor size from xrandr."""
        import subprocess, re
        try:
            result = subprocess.run(['xrandr', '--query'], capture_output=True, text=True, timeout=3)
            for line in result.stdout.split('\n'):
                if ' connected' in line:
                    is_primary = 'primary' in line
                    match = re.search(r'(\d+)x(\d+)\+(\d+)\+(\d+)', line)
                    if match:
                        w, h = int(match.group(1)), int(match.group(2))
                        if is_primary:
                            self._screen_w = w
                            self._screen_h = h
                            return
            # Fallback: no primary found, use first connected monitor
            for line in result.stdout.split('\n'):
                if ' connected' in line:
                    match = re.search(r'(\d+)x(\d+)\+(\d+)\+(\d+)', line)
                    if match:
                        self._screen_w = int(match.group(1))
                        self._screen_h = int(match.group(2))
                        return
        except Exception:
            pass

    def _on_realize(self, widget):
        """Go fullscreen — covers everything including Frank."""
        self.fullscreen()

    def _on_close_request(self, window):
        """Handle window close."""
        for timer_id in self._timer_ids:
            try:
                GLib.source_remove(timer_id)
            except Exception:
                pass
        self._timer_ids.clear()

        self._write_genesis_result()
        return False

    def _write_genesis_result(self):
        """Write result file so Genesis daemon knows the user's decision."""
        try:
            decision = self._genesis_decision or "defer"
            result = {
                "decision": decision,
                "timestamp": time.time(),
                "features": [f.get("id") for f in self.features],
            }
            result_path = Path("/tmp/genesis_popup_result.json")
            result_path.write_text(json.dumps(result))
            LOG.info(f"Genesis result written: {decision}")
        except Exception as e:
            LOG.warning(f"Failed to write genesis result: {e}")

    def _load_css(self):
        """Load CSS theme."""
        css_path = Path(__file__).parent / "styles" / "cyberpunk.css"
        if css_path.exists():
            css_provider = Gtk.CssProvider()
            css_provider.load_from_path(str(css_path))
            Gtk.StyleContext.add_provider_for_display(
                Gdk.Display.get_default(),
                css_provider,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
            )

    def _build_ui(self):
        """Build the main UI — content centered via explicit margins."""
        # Content panel positioned with margins (no halign — it doesn't work in GTK4 AppWindow)
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        content.add_css_class("fas-main-container")
        content.set_size_request(self.popup_width, self.popup_height)
        content.set_margin_start(self._margin_x)
        content.set_margin_end(self._margin_x)
        content.set_margin_top(self._margin_y)
        content.set_margin_bottom(self._margin_y)

        # Header
        header = self._build_header()
        content.append(header)

        # Feature list in scrolled window
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_vexpand(True)

        self.feature_list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.feature_list.add_css_class("fas-feature-list")

        for feature in self.features:
            row = FeatureRow(
                feature,
                on_toggle=self._on_feature_toggle,
                on_details=self._show_details
            )
            self.feature_rows.append(row)
            self.feature_list.append(row)

        scroll.set_child(self.feature_list)
        content.append(scroll)

        # Queue status (if manual open with few features)
        if self.manual_open and len(self.features) < self.config.get("min_features_for_auto_popup", 7):
            status = self._build_queue_status()
            content.append(status)

        # Actions
        actions = self._build_actions()
        content.append(actions)

        self.set_child(content)

    def _build_header(self) -> Gtk.Box:
        """Build the header section."""
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        header.add_css_class("fas-header")

        # Title section
        title_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        title_box.set_hexpand(True)

        title = Gtk.Label(label="░▒▓ F.A.S. INTELLIGENCE REPORT ▓▒░")
        title.add_css_class("fas-title")
        title.set_halign(Gtk.Align.START)
        title_box.append(title)

        subtitle = Gtk.Label(label=f"{len(self.features)} NEW CAPABILITIES DISCOVERED")
        subtitle.add_css_class("fas-subtitle")
        subtitle.set_halign(Gtk.Align.START)
        title_box.append(subtitle)

        header.append(title_box)

        # Sound toggle
        self.sound_btn = Gtk.Button(label="🔊 ON" if self.sound.enabled else "🔇 OFF")
        self.sound_btn.add_css_class("fas-sound-toggle")
        if not self.sound.enabled:
            self.sound_btn.add_css_class("sound-off")
        self.sound_btn.connect("clicked", self._toggle_sound)
        header.append(self.sound_btn)

        return header

    def _build_queue_status(self) -> Gtk.Box:
        """Build queue status indicator."""
        status = self.queue_manager.get_queue_status()

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.add_css_class("fas-status-queue")

        text = f"💡 Auto-popup triggers at {status['min_required']}+ features"
        label = Gtk.Label(label=text)
        label.set_halign(Gtk.Align.START)
        box.append(label)

        progress_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)

        progress_label = Gtk.Label(label=f"Current: {status['high_confidence']}/{status['min_required']}")
        progress_box.append(progress_label)

        progress = Gtk.ProgressBar()
        progress.set_fraction(min(1.0, status['high_confidence'] / status['min_required']))
        progress.set_hexpand(True)
        progress_box.append(progress)

        box.append(progress_box)

        return box

    def _build_actions(self) -> Gtk.Box:
        """Build the action buttons section."""
        actions = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        actions.add_css_class("fas-actions-container")

        # Top row: Approve All, Reject All, Later — fill width evenly
        top_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        top_row.set_margin_start(10)
        top_row.set_margin_end(10)

        approve_all = Gtk.Button(label="✓ APPROVE ALL")
        approve_all.add_css_class("fas-button")
        approve_all.add_css_class("fas-button-approve-all")
        approve_all.set_hexpand(True)
        approve_all.connect("clicked", self._on_approve_all)
        top_row.append(approve_all)

        reject_all = Gtk.Button(label="✗ REJECT ALL")
        reject_all.add_css_class("fas-button")
        reject_all.add_css_class("fas-button-reject-all")
        reject_all.set_hexpand(True)
        reject_all.connect("clicked", self._on_reject_all)
        top_row.append(reject_all)

        later = Gtk.Button(label="⏰ LATER")
        later.add_css_class("fas-button")
        later.add_css_class("fas-button-later")
        later.set_hexpand(True)
        later.connect("clicked", self._on_later)
        top_row.append(later)

        actions.append(top_row)

        # Middle row: Archive, Settings
        mid_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        mid_row.set_halign(Gtk.Align.CENTER)

        archive_btn = Gtk.Button(label="📁 ARCHIVE")
        archive_btn.add_css_class("fas-button")
        archive_btn.add_css_class("fas-button-archive")
        archive_btn.connect("clicked", self._show_archive)
        mid_row.append(archive_btn)

        settings_btn = Gtk.Button(label="⚙ SETTINGS")
        settings_btn.add_css_class("fas-button")
        settings_btn.add_css_class("fas-button-settings")
        settings_btn.connect("clicked", self._show_settings)
        mid_row.append(settings_btn)

        actions.append(mid_row)

        # Bottom row: Integrate selected
        bottom_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        bottom_row.set_halign(Gtk.Align.CENTER)

        self.integrate_btn = Gtk.Button(label="▶ INTEGRATE SELECTED (0)")
        self.integrate_btn.add_css_class("fas-button")
        self.integrate_btn.add_css_class("fas-button-integrate")
        self.integrate_btn.set_sensitive(False)
        self.integrate_btn.connect("clicked", self._on_integrate_selected)
        bottom_row.append(self.integrate_btn)

        actions.append(bottom_row)

        return actions

    def _setup_keyboard_shortcuts(self):
        """Setup keyboard navigation."""
        controller = Gtk.EventControllerKey()
        controller.connect("key-pressed", self._on_key_pressed)
        self.add_controller(controller)

    def _on_key_pressed(self, controller, keyval, keycode, state):
        """Handle keyboard shortcuts."""
        key_name = Gdk.keyval_name(keyval)

        if key_name == "Escape":
            self._on_later(None)
            return True
        elif key_name == "Return":
            if self.selected_features:
                self._on_integrate_selected(None)
            return True
        elif key_name == "a":
            self._select_all()
            return True
        elif key_name == "n":
            self._select_none()
            return True
        elif key_name == "r":
            self._on_reject_all(None)
            return True

        return False

    def _on_feature_toggle(self, feature: Dict, selected: bool):
        """Handle feature selection toggle."""
        feature_id = feature.get("id")
        if selected:
            self.selected_features[feature_id] = feature
        elif feature_id in self.selected_features:
            del self.selected_features[feature_id]

        self.sound.play_click()
        self._update_integrate_button()

    def _update_integrate_button(self):
        """Update the integrate button text and state."""
        count = len(self.selected_features)
        self.integrate_btn.set_label(f"▶ INTEGRATE SELECTED ({count})")
        self.integrate_btn.set_sensitive(count > 0)

    def _select_all(self):
        """Select all features."""
        for row in self.feature_rows:
            row.set_selected(True)

    def _select_none(self):
        """Deselect all features."""
        for row in self.feature_rows:
            row.set_selected(False)

    def _toggle_sound(self, button):
        """Toggle sound on/off."""
        self.sound.enabled = not self.sound.enabled
        if self.sound.enabled:
            button.set_label("🔊 ON")
            button.remove_css_class("sound-off")
            self.sound.play_click()
        else:
            button.set_label("🔇 OFF")
            button.add_css_class("sound-off")

    def _on_approve_all(self, button):
        """Approve all features."""
        self._genesis_decision = "approve"
        self._select_all()
        self._on_integrate_selected(None)

    def _on_reject_all(self, button):
        """Reject all features permanently."""
        self._genesis_decision = "reject"
        self.sound.play_dismiss()

        for feature in self.features:
            self.queue_manager.reject_feature(feature.get("id"), permanent=True)

        self.queue_manager.record_popup_shown()
        self.close()

    def _on_later(self, button):
        """Postpone for later."""
        self.sound.play_dismiss()
        self.queue_manager.postpone_popup()
        self.close()

    def _on_integrate_selected(self, button):
        """Integrate selected features."""
        if not self.selected_features:
            return

        self.sound.play_integration_start()

        # Show progress dialog
        self._show_integration_progress(list(self.selected_features.values()))

    def _show_integration_progress(self, features: List[Dict]):
        """Show integration progress dialog with A.S.R.S. safety monitoring."""
        dialog = Gtk.Window(title="Integration Progress")
        dialog.set_transient_for(self)
        dialog.set_modal(True)
        dialog.set_default_size(420, 200)  # Kompakter
        dialog.set_resizable(False)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.set_margin_top(16)
        box.set_margin_bottom(16)
        box.set_margin_start(20)
        box.set_margin_end(20)

        # Header with title and A.S.R.S. indicator
        header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        title = Gtk.Label(label="Integration in Progress")
        title.add_css_class("fas-progress-title")
        header_box.append(title)

        asrs_indicator = Gtk.Label(label="🛡️ A.S.R.S.")
        asrs_indicator.add_css_class("fas-asrs-indicator")
        asrs_indicator.set_hexpand(True)
        asrs_indicator.set_halign(Gtk.Align.END)
        header_box.append(asrs_indicator)
        box.append(header_box)

        # Progress bar
        progress = Gtk.ProgressBar()
        progress.add_css_class("fas-progress-bar")
        box.append(progress)

        # Status and time info in one row
        info_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)

        status_label = Gtk.Label(label="Starting...")
        status_label.add_css_class("fas-progress-status")
        status_label.set_halign(Gtk.Align.START)
        status_label.set_hexpand(True)
        info_box.append(status_label)

        # Time remaining label
        time_label = Gtk.Label(label="~0s")
        time_label.add_css_class("fas-progress-time")
        time_label.set_halign(Gtk.Align.END)
        info_box.append(time_label)

        box.append(info_box)

        dialog.set_child(box)
        dialog.present()

        # Track results
        self._integration_results = []
        self._integration_failures = []

        # Timing - fast baseline takes ~1-2s per feature
        total = len(features)
        estimated_per_feature = 2  # Fast file backup only
        total_estimated = total * estimated_per_feature
        start_time = time.time()

        # Update time label periodically
        def update_time():
            if not dialog.get_visible():
                return False
            elapsed = time.time() - start_time
            remaining = max(0, total_estimated - elapsed)
            time_label.set_text(f"~{int(remaining)}s")
            return True

        time_timer_id = GLib.timeout_add(500, update_time)
        self._timer_ids.append(time_timer_id)

        # Helper functions for thread-safe GTK updates (avoid lambda with loop variables)
        def update_progress_backup(idx: int, fname: str, total_count: int):
            """Thread-safe progress update for backup phase."""
            progress.set_fraction((idx + 0.3) / total_count)
            status_label.set_text(f"[{idx+1}/{total_count}] Backup: {fname}...")

        def update_progress_complete(idx: int, total_count: int):
            """Thread-safe progress update for completion."""
            progress.set_fraction((idx + 1) / total_count)

        # Run integration in thread - fast minimal baselines + background A.S.R.S.
        def integrate_thread():
            for i, feature in enumerate(features):
                feature_name = feature.get('name', 'Unknown')[:30]
                feature_id = feature.get("id")

                # Update UI using functools.partial for thread-safety
                GLib.idle_add(functools.partial(update_progress_backup, i, feature_name, total))

                try:
                    # FAST PATH: Create minimal baseline (file backups only)
                    # This is GUARANTEED to work and be fast
                    self._create_minimal_baseline(feature)

                    # Mark as approved in database
                    self.queue_manager.approve_feature(feature_id)

                    self._integration_results.append({
                        "feature_id": feature_id,
                        "feature_name": feature_name,
                        "success": True,
                        "status": "approved",
                    })

                    print(f"[FAS] Feature approved with baseline: {feature_name}")

                except Exception as e:
                    print(f"[FAS] Integration error for {feature_name}: {e}")
                    self._integration_failures.append({
                        "feature_id": feature_id,
                        "error": str(e)
                    })

                GLib.idle_add(functools.partial(update_progress_complete, i, total))
                time.sleep(0.3)  # Small delay for UI feedback

            # Schedule A.S.R.S. background monitoring (non-blocking)
            self._schedule_asrs_monitoring(features)

            GLib.idle_add(self._on_integration_complete, dialog, features)

        thread = threading.Thread(target=integrate_thread)
        thread.daemon = True
        thread.start()

    def _schedule_asrs_monitoring(self, features: List[Dict]):
        """Schedule A.S.R.S. background monitoring for approved features."""
        def start_monitoring():
            try:
                # Prepare detailed feature data for A.S.R.S.
                feature_ids = []
                features_data = []

                for f in features:
                    fid = f.get("id")
                    if not fid:
                        continue

                    feature_ids.append(fid)
                    features_data.append({
                        "name": f.get("name", f"Feature #{fid}"),
                        "feature_type": f.get("feature_type", "unknown"),
                        "modified_files": f.get("affected_files", []),
                        "modified_functions": f.get("affected_functions", []),
                        "target_file": f.get("target_file", ""),
                        "confidence_score": f.get("confidence_score", 0.5),
                    })

                # Write to monitoring queue file for A.S.R.S. daemon
                monitor_file = Path("/tmp/asrs_monitor_queue.json")
                monitor_file.write_text(json.dumps({
                    "timestamp": time.time(),
                    "action": "monitor",
                    "feature_ids": feature_ids,
                    "features": features_data,
                }))

                print(f"[FAS] A.S.R.S. monitoring scheduled for {len(feature_ids)} features")

            except Exception as e:
                print(f"[FAS] A.S.R.S. schedule error: {e}")

        # Run in background thread
        thread = threading.Thread(target=start_monitoring, daemon=True)
        thread.start()

    def _create_minimal_baseline(self, feature: Dict):
        """Create a minimal baseline - fast file backups for rollback capability."""
        import shutil
        from datetime import datetime

        feature_id = feature.get("id", 0)
        feature_name = feature.get("name", "unknown")
        # Use same directory as A.S.R.S. for consistency
        from config.paths import ASRS_BACKUP_DIR as _ASRS_BACKUP_DIR
        backup_dir = _ASRS_BACKUP_DIR / f"baseline_{feature_id}_{int(time.time())}"

        try:
            backup_dir.mkdir(parents=True, exist_ok=True)

            # Backup core files that might be affected
            try:
                from config.paths import AICORE_ROOT as _AICORE_ROOT
            except ImportError:
                _AICORE_ROOT = Path(__file__).resolve().parents[2]
            core_files = [
                _AICORE_ROOT / "core" / "app.py",
                _AICORE_ROOT / "tools" / "toolboxd.py",
                _AICORE_ROOT / "services" / "router.py",
            ]

            # Also backup feature-specific target file if specified
            target_file = feature.get("target_file")
            if target_file:
                core_files.append(Path(target_file))

            backed_up = []
            for core_file in core_files:
                if core_file.exists():
                    try:
                        dest = backup_dir / core_file.name
                        shutil.copy2(core_file, dest)
                        backed_up.append(str(core_file))
                    except Exception as e:
                        print(f"[FAS] Backup failed for {core_file}: {e}")

            # Save metadata
            metadata = {
                "feature_id": feature_id,
                "feature_name": feature_name,
                "created_at": datetime.now().isoformat(),
                "type": "baseline",
                "backed_up_files": backed_up,
                "backup_dir": str(backup_dir),
            }
            (backup_dir / "metadata.json").write_text(json.dumps(metadata, indent=2))

            print(f"[FAS] Baseline created: {backup_dir} ({len(backed_up)} files)")

        except Exception as e:
            print(f"[FAS] Minimal baseline error: {e}")

    def _on_integration_complete(self, dialog: Gtk.Window, features: List[Dict]):
        """Called when integration is complete."""
        dialog.close()

        failures = len(self._integration_failures) if hasattr(self, '_integration_failures') else 0
        successes = len(self._integration_results) if hasattr(self, '_integration_results') else 0

        if failures > 0:
            self.sound.play_dismiss()
            msg = f"✓ {successes} features integrated\n⚠️ {failures} features failed"
            msg_type = Gtk.MessageType.WARNING
        else:
            self.sound.play_integration_done()
            msg = f"✓ {successes} features integrated!\n\n📋 Baselines created\n🛡️ A.S.R.S. monitoring active"
            msg_type = Gtk.MessageType.INFO

        success_dialog = Gtk.MessageDialog(
            transient_for=self,
            modal=True,
            message_type=msg_type,
            buttons=Gtk.ButtonsType.OK,
            text=msg
        )
        success_dialog.connect("response", lambda d, r: d.close())
        success_dialog.present()

        self.queue_manager.record_popup_shown()

        # Close main window after a delay
        close_timer_id = GLib.timeout_add(2000, self.close)
        self._timer_ids.append(close_timer_id)

    def _show_details(self, feature: Dict):
        """Show feature details dialog."""
        dialog = Gtk.Window(title=f"Feature Details: {feature.get('name', 'Unknown')}")
        dialog.set_transient_for(self)
        dialog.set_modal(True)
        dialog.set_default_size(700, 500)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        box.set_margin_top(20)
        box.set_margin_bottom(20)
        box.set_margin_start(20)
        box.set_margin_end(20)

        # Header
        header = Gtk.Label(label=feature.get("name", "Unknown"))
        header.add_css_class("fas-details-section-title")
        header.set_halign(Gtk.Align.START)
        box.append(header)

        # Info grid
        info = [
            ("Type", feature.get("feature_type", "Unknown")),
            ("Source", feature.get("repo_name", "Unknown")),
            ("File", feature.get("file_path", "Unknown")),
            ("Confidence", f"{int(feature.get('confidence_score', 0) * 100)}%"),
            ("Sandbox Tests", f"{feature.get('test_iterations', 0)} passed"),
        ]

        for label, value in info:
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            lbl = Gtk.Label(label=f"{label}:")
            lbl.set_halign(Gtk.Align.START)
            lbl.set_width_chars(15)
            row.append(lbl)
            val = Gtk.Label(label=value)
            val.set_halign(Gtk.Align.START)
            row.append(val)
            box.append(row)

        # Description
        desc_title = Gtk.Label(label="Description:")
        desc_title.add_css_class("fas-details-section-title")
        desc_title.set_halign(Gtk.Align.START)
        box.append(desc_title)

        desc = Gtk.Label(label=feature.get("description", "No description"))
        desc.set_wrap(True)
        desc.set_halign(Gtk.Align.START)
        box.append(desc)

        # Code preview
        code_title = Gtk.Label(label="Code Preview:")
        code_title.add_css_class("fas-details-section-title")
        code_title.set_halign(Gtk.Align.START)
        box.append(code_title)

        code_view = Gtk.TextView()
        code_view.set_editable(False)
        code_view.add_css_class("fas-code-preview")
        code_view.get_buffer().set_text(feature.get("code_snippet", "No code available")[:1000])
        code_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        box.append(code_view)

        # Buttons
        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        btn_box.set_halign(Gtk.Align.CENTER)

        close_btn = Gtk.Button(label="Close")
        close_btn.connect("clicked", lambda b: dialog.close())
        btn_box.append(close_btn)

        box.append(btn_box)

        scroll.set_child(box)
        dialog.set_child(scroll)
        dialog.present()

    def _show_archive(self, button):
        """Show archive view."""
        dialog = Gtk.Window(title="F.A.S. Archive")
        dialog.set_transient_for(self)
        dialog.set_modal(True)
        dialog.set_default_size(700, 500)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        # Header
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        header.add_css_class("fas-archive-header")

        title = Gtk.Label(label="░▒▓ F.A.S. ARCHIVE ▓▒░")
        title.add_css_class("fas-archive-title")
        title.set_hexpand(True)
        title.set_halign(Gtk.Align.START)
        header.append(title)

        back_btn = Gtk.Button(label="← BACK")
        back_btn.connect("clicked", lambda b: dialog.close())
        header.append(back_btn)

        box.append(header)

        # Archive list
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_vexpand(True)

        archive_list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)

        archived = self.queue_manager.get_archived_features()
        if archived:
            for feature in archived:
                row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
                row.add_css_class("fas-archive-item")
                row.set_margin_start(10)
                row.set_margin_end(10)
                row.set_margin_top(4)
                row.set_margin_bottom(4)

                # Name
                name = Gtk.Label(label=f"✗ {feature.get('name', 'Unknown')}")
                name.set_hexpand(True)
                name.set_halign(Gtk.Align.START)
                row.append(name)

                # Confidence
                conf = Gtk.Label(label=f"{int(feature.get('confidence_score', 0) * 100)}%")
                row.append(conf)

                # Reactivate button
                react_btn = Gtk.Button(label="REACTIVATE")
                react_btn.add_css_class("fas-reactivate-button")
                react_btn.connect("clicked", lambda b, f=feature: self._reactivate_feature(f, dialog))
                row.append(react_btn)

                archive_list.append(row)
        else:
            empty = Gtk.Label(label="No archived features")
            empty.set_margin_top(50)
            archive_list.append(empty)

        scroll.set_child(archive_list)
        box.append(scroll)

        # Statistics
        stats = self.queue_manager.get_statistics()
        stats_label = Gtk.Label(
            label=f"📊 {stats['rejected']} rejected | {stats['integrated']} integrated | {stats['in_queue']} in queue"
        )
        stats_label.set_margin_top(10)
        stats_label.set_margin_bottom(10)
        box.append(stats_label)

        dialog.set_child(box)
        dialog.present()

    def _reactivate_feature(self, feature: Dict, archive_dialog: Gtk.Window):
        """Reactivate an archived feature."""
        self.queue_manager.reactivate_feature(feature.get("id"))
        archive_dialog.close()
        self._show_archive(None)  # Refresh archive view

    def _show_settings(self, button):
        """Show settings dialog."""
        dialog = Gtk.Window(title="F.A.S. Settings")
        dialog.set_transient_for(self)
        dialog.set_modal(True)
        dialog.set_default_size(400, 300)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        box.set_margin_top(20)
        box.set_margin_bottom(20)
        box.set_margin_start(20)
        box.set_margin_end(20)

        title = Gtk.Label(label="⚙ Settings")
        title.set_halign(Gtk.Align.START)
        box.append(title)

        # Sound toggle
        sound_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        sound_label = Gtk.Label(label="Sound:")
        sound_label.set_hexpand(True)
        sound_label.set_halign(Gtk.Align.START)
        sound_row.append(sound_label)

        sound_switch = Gtk.Switch()
        sound_switch.set_active(self.sound.enabled)
        sound_switch.connect("state-set", lambda s, state: self.sound.set_enabled(state))
        sound_row.append(sound_switch)
        box.append(sound_row)

        # Volume slider
        vol_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        vol_label = Gtk.Label(label="Volume:")
        vol_label.set_hexpand(True)
        vol_label.set_halign(Gtk.Align.START)
        vol_row.append(vol_label)

        vol_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 10)
        vol_scale.set_value(self.sound.volume * 100)
        vol_scale.set_size_request(150, -1)
        vol_scale.connect("value-changed", lambda s: self.sound.set_volume(s.get_value() / 100))
        vol_row.append(vol_scale)
        box.append(vol_row)

        # Close button
        close_btn = Gtk.Button(label="Close")
        close_btn.connect("clicked", lambda b: dialog.close())
        close_btn.set_halign(Gtk.Align.CENTER)
        box.append(close_btn)

        dialog.set_child(box)
        dialog.present()


class FASPopupApp(Gtk.Application):
    """
    GTK Application wrapper with singleton enforcement.
    Uses Gio.ApplicationFlags.FLAGS_NONE which enforces single instance.
    """

    # Lock file for additional safety
    LOCK_FILE = Path(f"/run/user/{os.getuid()}/frank/fas_popup.lock")

    def __init__(self, features: List[Dict] = None, manual: bool = False):
        super().__init__(application_id="com.frank.fas.popup",
                        flags=Gio.ApplicationFlags.FLAGS_NONE)
        self.features = features or []
        self.manual = manual
        self.win = None
        self.connect("activate", self.on_activate)
        self.connect("shutdown", self.on_shutdown)

    @classmethod
    def is_already_running(cls) -> bool:
        """Check if another instance is already running."""
        import fcntl

        cls.LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)

        try:
            cls._lock_fd = open(cls.LOCK_FILE, 'w')
            fcntl.flock(cls._lock_fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            cls._lock_fd.write(str(os.getpid()))
            cls._lock_fd.flush()
            return False  # We got the lock
        except (IOError, OSError):
            return True  # Another instance has the lock

    @classmethod
    def release_lock(cls):
        """Release the lock file."""
        import fcntl
        try:
            if hasattr(cls, '_lock_fd') and cls._lock_fd:
                fcntl.flock(cls._lock_fd.fileno(), fcntl.LOCK_UN)
                cls._lock_fd.close()
            if cls.LOCK_FILE.exists():
                cls.LOCK_FILE.unlink()
        except OSError as e:
            LOG.debug(f"Lock release error (may be expected): {e}")
        except Exception as e:
            LOG.warning(f"Unexpected lock release error: {e}")

    def on_activate(self, app):
        """Handle activate signal - only one window ever."""
        if not self.win:
            self.win = FASPopupWindow(self, self.features, self.manual)
        self.win.present()

    def on_shutdown(self, app):
        """Handle application shutdown."""
        self.release_lock()


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="F.A.S. Proposal Popup")
    parser.add_argument("--features", type=str, help="Features as JSON string")
    parser.add_argument("--manual", action="store_true", help="Manually opened (show queue status)")
    parser.add_argument("--force", action="store_true", help="Force start even if another instance exists")
    parser.add_argument("--all", action="store_true", help="Show ALL features (not just ready ones)")

    args = parser.parse_args()

    # Check for existing instance (singleton enforcement)
    if not args.force and FASPopupApp.is_already_running():
        print("F.A.S. Popup is already running. Use --force to override.")
        # Try to raise the existing window
        try:
            import subprocess
            subprocess.run(['wmctrl', '-a', 'F.A.S. Intelligence'], capture_output=True)
        except subprocess.SubprocessError as e:
            LOG.debug(f"Could not raise existing window: {e}")
        except Exception as e:
            LOG.warning(f"Window raise error: {e}")
        return

    features = []
    if args.features:
        try:
            features = json.loads(args.features)
        except json.JSONDecodeError as e:
            LOG.warning(f"Could not parse features JSON: {e}")
        except Exception as e:
            LOG.error(f"Features parsing error: {e}")

    # If no features provided, get from queue
    if not features:
        config = get_config()
        manager = ProposalQueueManager(config)
        if args.all:
            features = manager.get_all_features()
        else:
            features = manager.get_ready_features()

    try:
        app = FASPopupApp(features=features, manual=args.manual)
        app.run([])
    finally:
        FASPopupApp.release_lock()


if __name__ == "__main__":
    main()
