#!/usr/bin/env python3
"""
ADI Popup Main Window - Adaptive Display Intelligence.

GTK4-based popup for collaborative display configuration.
Features:
- Dark fullscreen overlay
- Live ASCII layout preview
- Integrated chat for natural language configuration
- Apply/Later action buttons
"""

import argparse
import fcntl
import logging
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Optional

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Gdk', '4.0')
from gi.repository import Gtk, Gdk, GLib, Pango

# Setup logging
LOG = logging.getLogger("adi.popup")
if not LOG.handlers:
    LOG.addHandler(logging.StreamHandler(sys.stderr))
    LOG.setLevel(logging.DEBUG)

# Add parent paths for imports
AICORE_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(AICORE_ROOT))

from ui.adi_popup.monitor_detector import get_primary_monitor, MonitorInfo
from ui.adi_popup.profile_manager import (
    load_profile, save_profile, create_default_profile, add_proposal_to_history
)
from ui.adi_popup.layout_preview import generate_preview
from ui.adi_popup.chat_handler import ADIChatHandler
from ui.adi_popup.sound_manager import get_sound_manager
from config.adi_config import get_config


class ADIPopupWindow(Gtk.ApplicationWindow):
    """Main ADI configuration popup window."""

    def __init__(self, app: Gtk.Application, reopen: bool = False):
        super().__init__(application=app)

        self.config = get_config()
        self.reopen = reopen  # True if editing existing profile
        self.sound = get_sound_manager(
            enabled=self.config.get("sound_enabled", True),
            volume=self.config.get("sound_volume", 0.6)
        )

        # Timer IDs for cleanup
        self._timer_ids = []

        # Get monitor info
        self.monitor = get_primary_monitor()
        LOG.info(f"Monitor: {self.monitor.get_display_name()} ({self.monitor.width}x{self.monitor.height})")

        # Load or create profile
        existing_profile = load_profile(self.monitor.edid_hash)
        if existing_profile:
            self.profile = existing_profile
            self.is_new_monitor = False
        else:
            self.profile = create_default_profile(self.monitor)
            self.is_new_monitor = True

        # Initialize chat handler
        self.chat_handler = ADIChatHandler(
            monitor_info=self.profile.get("monitor", {}),
            current_layout=self.profile.get("frank_layout", {}),
            llm_url=self.config.get("llm_url", "http://127.0.0.1:8101/v1/chat/completions"),
            timeout=self.config.get("llm_timeout", 30),
        )

        # Setup window
        self.set_title("A.D.I.")
        self.set_default_size(
            self.config.get("popup_width", 800),
            self.config.get("popup_height", 700)
        )
        self.set_resizable(False)
        self.add_css_class("adi-popup-window")

        # Get screen dimensions for overlay
        self._get_screen_dimensions()

        # Build UI
        self._build_ui()

        # Load CSS
        self._load_css()

        # Connect signals
        self.connect("realize", self._on_realize)
        self.connect("close-request", self._on_close_request)

    def _get_screen_dimensions(self):
        """Get screen dimensions using xrandr."""
        try:
            result = subprocess.run(
                ['xrandr', '--current'],
                capture_output=True, text=True, timeout=5
            )
            # Find primary or first connected monitor
            for line in result.stdout.split('\n'):
                if ' connected' in line:
                    match = __import__('re').search(r'(\d+)x(\d+)\+(\d+)\+(\d+)', line)
                    if match:
                        self.screen_width = int(match.group(1))
                        self.screen_height = int(match.group(2))
                        return
        except Exception as e:
            LOG.warning(f"Failed to get screen dimensions: {e}")

        # Fallback
        self.screen_width = 1920
        self.screen_height = 1080

    def _build_ui(self):
        """Build the popup UI."""
        # Main container
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.set_child(main_box)

        # Header
        self._build_header(main_box)

        # Content area (scrollable)
        content_scroll = Gtk.ScrolledWindow()
        content_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        content_scroll.set_vexpand(True)
        main_box.append(content_scroll)

        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        content_box.set_margin_start(16)
        content_box.set_margin_end(16)
        content_box.set_margin_top(12)
        content_box.set_margin_bottom(12)
        content_scroll.set_child(content_box)

        # Preview area
        self._build_preview(content_box)

        # Chat area
        self._build_chat(content_box)

        # Action buttons
        self._build_actions(main_box)

    def _build_header(self, parent: Gtk.Box):
        """Build the header section."""
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        header.add_css_class("adi-header")
        parent.append(header)

        # Status dot
        status_dot = Gtk.DrawingArea()
        status_dot.set_size_request(10, 10)
        status_dot.add_css_class("adi-status-dot")
        if self.is_new_monitor:
            status_dot.add_css_class("adi-status-new")
        else:
            status_dot.add_css_class("adi-status-edit")
        header.append(status_dot)

        # Title
        title_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        title_box.set_hexpand(True)

        title = Gtk.Label(label="A.D.I. // ADAPTIVE DISPLAY INTELLIGENCE")
        title.add_css_class("adi-title")
        title.set_halign(Gtk.Align.START)
        title_box.append(title)

        status_text = "NEW MONITOR DETECTED" if self.is_new_monitor else "EDIT CONFIGURATION"
        subtitle = Gtk.Label(label=status_text)
        subtitle.add_css_class("adi-subtitle")
        subtitle.set_halign(Gtk.Align.START)
        title_box.append(subtitle)

        header.append(title_box)

        # Sound toggle
        self.sound_btn = Gtk.ToggleButton()
        self.sound_btn.set_icon_name("audio-volume-high-symbolic")
        self.sound_btn.add_css_class("adi-sound-toggle")
        self.sound_btn.set_active(self.sound.enabled)
        self.sound_btn.connect("toggled", self._on_sound_toggle)
        header.append(self.sound_btn)

        # Close button
        close_btn = Gtk.Button()
        close_btn.set_icon_name("window-close-symbolic")
        close_btn.add_css_class("adi-close-button")
        close_btn.connect("clicked", lambda _: self.close())
        header.append(close_btn)

    def _build_preview(self, parent: Gtk.Box):
        """Build the preview section."""
        preview_container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        preview_container.add_css_class("adi-preview-container")
        parent.append(preview_container)

        # Label
        label = Gtk.Label(label="LIVE PREVIEW")
        label.add_css_class("adi-preview-label")
        label.set_halign(Gtk.Align.START)
        preview_container.append(label)

        # Preview text
        self.preview_text = Gtk.Label()
        self.preview_text.add_css_class("adi-preview-text")
        self.preview_text.set_halign(Gtk.Align.CENTER)
        self.preview_text.set_selectable(False)
        # Use monospace font
        self.preview_text.set_use_markup(True)
        preview_container.append(self.preview_text)

        # Monitor info
        info_text = f"<b>{self.monitor.get_display_name()}</b> | {self.monitor.width}x{self.monitor.height} @ {self.monitor.refresh}Hz"
        if self.is_new_monitor:
            info_text += " | <span color='#00ff88'>NEWLY DETECTED</span>"

        monitor_info = Gtk.Label()
        monitor_info.add_css_class("adi-monitor-info")
        monitor_info.set_markup(info_text)
        monitor_info.set_halign(Gtk.Align.START)
        preview_container.append(monitor_info)

        # Initial preview
        self._update_preview()

    def _build_chat(self, parent: Gtk.Box):
        """Build the chat section."""
        chat_container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        chat_container.add_css_class("adi-chat-container")
        chat_container.set_vexpand(True)
        parent.append(chat_container)

        # Label
        label = Gtk.Label(label="CHAT WITH FRANK")
        label.add_css_class("adi-chat-label")
        label.set_halign(Gtk.Align.START)
        chat_container.append(label)

        # Chat scroll area
        chat_scroll = Gtk.ScrolledWindow()
        chat_scroll.add_css_class("adi-chat-scroll")
        chat_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        chat_scroll.set_vexpand(True)
        chat_scroll.set_min_content_height(200)
        chat_container.append(chat_scroll)

        # Messages container
        self.messages_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.messages_box.add_css_class("adi-chat-messages")
        self.messages_box.set_margin_start(8)
        self.messages_box.set_margin_end(8)
        self.messages_box.set_margin_top(8)
        self.messages_box.set_margin_bottom(8)
        chat_scroll.set_child(self.messages_box)

        self.chat_scroll = chat_scroll

        # Input area
        input_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        input_box.add_css_class("adi-chat-input-container")
        chat_container.append(input_box)

        self.chat_input = Gtk.Entry()
        self.chat_input.add_css_class("adi-chat-input")
        self.chat_input.set_placeholder_text("Type here...")
        self.chat_input.set_hexpand(True)
        self.chat_input.connect("activate", self._on_send_message)
        input_box.append(self.chat_input)

        send_btn = Gtk.Button(label="SEND")
        send_btn.add_css_class("adi-send-button")
        send_btn.connect("clicked", self._on_send_message)
        input_box.append(send_btn)

        # Add initial message
        initial_msg = self.chat_handler.get_initial_message(self.is_new_monitor)
        self._add_message("frank", initial_msg)

    def _build_actions(self, parent: Gtk.Box):
        """Build the action buttons section."""
        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        actions.add_css_class("adi-actions")
        actions.set_halign(Gtk.Align.CENTER)
        parent.append(actions)

        # Apply button
        apply_btn = Gtk.Button(label="APPLY")
        apply_btn.add_css_class("adi-button-primary")
        apply_btn.connect("clicked", self._on_apply)
        actions.append(apply_btn)

        # Later button
        later_btn = Gtk.Button(label="LATER")
        later_btn.add_css_class("adi-button-secondary")
        later_btn.connect("clicked", self._on_later)
        actions.append(later_btn)

    def _load_css(self):
        """Load the CSS theme."""
        css_path = Path(__file__).parent / "styles" / "adi_cyberpunk.css"

        if css_path.exists():
            css_provider = Gtk.CssProvider()
            css_provider.load_from_path(str(css_path))

            Gtk.StyleContext.add_provider_for_display(
                Gdk.Display.get_default(),
                css_provider,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
            )
            LOG.debug(f"Loaded CSS from {css_path}")
        else:
            LOG.warning(f"CSS file not found: {css_path}")

    def _on_realize(self, widget):
        """Called when window is realized."""
        self.sound.play_popup_appear()

        # Create overlay and center popup
        timer_id = GLib.timeout_add(100, self._create_overlay_window)
        self._timer_ids.append(timer_id)

    def _create_overlay_window(self):
        """Create the dark overlay window."""
        LOG.debug("Creating overlay window")

        # Signal Frank to dim
        self._signal_frank_dim(True)

        # Create overlay window
        self.overlay_window = Gtk.Window()
        self.overlay_window.set_title("adi-dark-overlay")
        self.overlay_window.set_decorated(False)

        # Black background
        overlay_box = Gtk.Box()
        overlay_box.add_css_class("adi-overlay-bg")

        # Click to close
        click = Gtk.GestureClick.new()
        click.connect("pressed", self._on_overlay_clicked)
        overlay_box.add_controller(click)

        self.overlay_window.set_child(overlay_box)

        # Show and fullscreen
        self.overlay_window.present()
        self.overlay_window.fullscreen()

        # Setup overlay position/opacity
        timer_id = GLib.timeout_add(100, self._setup_overlay)
        self._timer_ids.append(timer_id)

        return False  # Don't repeat

    def _setup_overlay(self):
        """Set up overlay opacity and stacking."""
        try:
            # Find overlay window
            result = subprocess.run(
                ['xdotool', 'search', '--name', 'adi-dark-overlay'],
                capture_output=True, text=True, timeout=5
            )

            if not result.stdout.strip():
                timer_id = GLib.timeout_add(100, self._setup_overlay)
                self._timer_ids.append(timer_id)
                return False

            overlay_wid = result.stdout.strip().split()[0]

            # Set opacity (75%)
            subprocess.run([
                'xprop', '-id', overlay_wid,
                '-f', '_NET_WM_WINDOW_OPACITY', '32c',
                '-set', '_NET_WM_WINDOW_OPACITY', '3221225472'  # 0.75 * 0xFFFFFFFF
            ], capture_output=True, timeout=5)

            # Make sticky
            subprocess.run([
                'wmctrl', '-i', '-r', overlay_wid, '-b', 'add,sticky'
            ], capture_output=True, timeout=5)

            # Lower Frank windows
            frank_result = subprocess.run(
                ['xdotool', 'search', '--name', 'F.R.A.N.K.'],
                capture_output=True, text=True, timeout=5
            )
            for wid in frank_result.stdout.strip().split():
                if wid:
                    subprocess.run(['xdotool', 'windowlower', wid], capture_output=True, timeout=5)

            # Raise overlay
            subprocess.run(['xdotool', 'windowraise', overlay_wid], capture_output=True, timeout=5)

            # Raise and center main popup
            timer_id = GLib.timeout_add(100, self._center_and_raise_popup)
            self._timer_ids.append(timer_id)

        except Exception as e:
            LOG.error(f"Failed to setup overlay: {e}")

        return False

    def _center_and_raise_popup(self):
        """Center the popup and raise it above overlay."""
        try:
            # Find our popup window
            result = subprocess.run(
                ['xdotool', 'search', '--name', 'A.D.I.'],
                capture_output=True, text=True, timeout=5
            )

            if result.stdout.strip():
                popup_wid = result.stdout.strip().split()[0]

                # Center on screen
                win_w = self.config.get("popup_width", 800)
                win_h = self.config.get("popup_height", 700)
                x = (self.screen_width - win_w) // 2
                y = (self.screen_height - win_h) // 2

                subprocess.run([
                    'xdotool', 'windowmove', popup_wid, str(x), str(y)
                ], capture_output=True, timeout=5)

                # CRITICAL: Ensure proper stacking order
                # 1. First lower Frank windows
                frank_result = subprocess.run(
                    ['xdotool', 'search', '--name', 'F.R.A.N.K.'],
                    capture_output=True, text=True, timeout=5
                )
                for wid in frank_result.stdout.strip().split():
                    if wid:
                        subprocess.run(['xdotool', 'windowlower', wid], capture_output=True, timeout=5)

                # 2. Then raise overlay (with opacity)
                overlay_result = subprocess.run(
                    ['xdotool', 'search', '--name', 'adi-dark-overlay'],
                    capture_output=True, text=True, timeout=5
                )
                if overlay_result.stdout.strip():
                    overlay_wid = overlay_result.stdout.strip().split()[0]
                    subprocess.run(['xdotool', 'windowraise', overlay_wid], capture_output=True, timeout=5)

                # 3. Finally raise popup ABOVE everything (including overlay)
                subprocess.run(['xdotool', 'windowraise', popup_wid], capture_output=True, timeout=5)
                subprocess.run(['xdotool', 'windowactivate', popup_wid], capture_output=True, timeout=5)

                # Make popup stay on top
                subprocess.run([
                    'wmctrl', '-i', '-r', popup_wid, '-b', 'add,above'
                ], capture_output=True, timeout=5)

                LOG.debug(f"Stacking order set: Frank < Overlay < Popup ({popup_wid})")

                # Re-enforce stacking after 200ms (window managers sometimes reorder)
                timer_id = GLib.timeout_add(200, self._enforce_stacking)
                self._timer_ids.append(timer_id)

        except Exception as e:
            LOG.error(f"Failed to center popup: {e}")

        return False

    def _enforce_stacking(self):
        """Re-enforce stacking order to keep popup on top."""
        try:
            # Find and raise popup above overlay
            popup_result = subprocess.run(
                ['xdotool', 'search', '--name', 'A.D.I.'],
                capture_output=True, text=True, timeout=5
            )
            if popup_result.stdout.strip():
                popup_wid = popup_result.stdout.strip().split()[0]
                subprocess.run(['xdotool', 'windowraise', popup_wid], capture_output=True, timeout=5)
        except Exception as e:
            LOG.debug(f"Stacking enforcement error: {e}")
        return False  # Don't repeat

    def _signal_frank_dim(self, dim: bool):
        """Signal Frank to dim or restore."""
        try:
            from config.paths import get_temp as _get_temp_adim
            signal_file = _get_temp_adim("adi_dim_signal")
        except ImportError:
            signal_file = Path("/tmp/frank/adi_dim_signal")
        try:
            if dim:
                signal_file.touch()
            else:
                signal_file.unlink(missing_ok=True)
        except Exception as e:
            LOG.warning(f"Failed to signal Frank: {e}")

    def _on_overlay_clicked(self, gesture, n_press, x, y):
        """Handle click on overlay."""
        self.sound.play_popup_dismiss()
        self.close()

    def _on_close_request(self, widget):
        """Handle window close."""
        self._signal_frank_dim(False)

        if hasattr(self, 'overlay_window') and self.overlay_window:
            self.overlay_window.close()

        # Cancel all timers
        for timer_id in self._timer_ids:
            try:
                GLib.source_remove(timer_id)
            except Exception:
                pass
        self._timer_ids.clear()

        # Restore Frank overlay visibility
        self._restore_frank_overlay()

        return False

    def _restore_frank_overlay(self):
        """Restore Frank overlay to visible state after popup closes."""
        try:
            # Touch the restore signal file so Frank shows itself
            try:
                from config.paths import TEMP_FILES as _TF_adi
                restore_signal = _TF_adi["overlay_show"]
            except ImportError:
                restore_signal = Path("/tmp/frank/overlay_show")
            restore_signal.touch()
            LOG.debug("Signaled Frank overlay to restore")

            # Also try to show/raise Frank window directly
            result = subprocess.run(
                ['xdotool', 'search', '--name', 'F.R.A.N.K.'],
                capture_output=True, text=True, timeout=5
            )
            for wid in result.stdout.strip().split():
                if wid:
                    subprocess.run(['xdotool', 'windowmap', wid], capture_output=True, timeout=5)
                    subprocess.run(['xdotool', 'windowraise', wid], capture_output=True, timeout=5)
                    LOG.debug(f"Raised Frank window: {wid}")
        except Exception as e:
            LOG.warning(f"Failed to restore Frank overlay: {e}")

    def _on_sound_toggle(self, button):
        """Toggle sound on/off."""
        self.sound.set_enabled(button.get_active())
        self.sound.play_click()

    def _update_preview(self):
        """Update the layout preview."""
        layout = self.profile.get("frank_layout", {})
        app_zone = self.profile.get("app_zone", {})

        preview = generate_preview(
            self.monitor.width,
            self.monitor.height,
            layout,
            app_zone
        )

        # Use monospace markup
        self.preview_text.set_markup(f"<tt>{GLib.markup_escape_text(preview)}</tt>")

    def _add_message(self, sender: str, text: str):
        """Add a message to the chat."""
        msg_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        msg_box.add_css_class("adi-message")
        msg_box.add_css_class(f"adi-message-{sender}")

        # Sender label
        sender_label = Gtk.Label(label="FRANK" if sender == "frank" else "YOU")
        sender_label.add_css_class("adi-message-sender")
        sender_label.add_css_class(f"adi-message-sender-{sender}")
        sender_label.set_halign(Gtk.Align.START)
        msg_box.append(sender_label)

        # Message text
        text_label = Gtk.Label(label=text)
        text_label.add_css_class("adi-message-text")
        text_label.set_halign(Gtk.Align.START)
        text_label.set_wrap(True)
        text_label.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        text_label.set_max_width_chars(60)
        text_label.set_selectable(True)
        msg_box.append(text_label)

        self.messages_box.append(msg_box)

        # Scroll to bottom
        GLib.idle_add(self._scroll_to_bottom)

    def _scroll_to_bottom(self):
        """Scroll chat to bottom."""
        adj = self.chat_scroll.get_vadjustment()
        adj.set_value(adj.get_upper() - adj.get_page_size())
        return False

    def _on_send_message(self, widget):
        """Handle send message."""
        text = self.chat_input.get_text().strip()
        if not text:
            return

        self.chat_input.set_text("")
        self.sound.play_message_send()

        # Add user message
        self._add_message("user", text)

        # Process in thread to avoid UI freeze
        thread = threading.Thread(target=self._process_chat, args=(text,), daemon=True)
        thread.start()

    def _process_chat(self, user_text: str):
        """Process chat message in background thread."""
        try:
            response, new_layout = self.chat_handler.process_user_message(user_text)

            # Update UI on main thread
            GLib.idle_add(self._on_chat_response, response, new_layout)

        except Exception as e:
            LOG.error(f"Chat processing error: {e}")
            GLib.idle_add(
                self._add_message,
                "frank",
                "Sorry, something went wrong. Please try again."
            )

    def _on_chat_response(self, response: str, new_layout: Optional[dict]):
        """Handle chat response on main thread."""
        self.sound.play_message_receive()
        self._add_message("frank", response)

        if new_layout:
            # Update profile
            self.profile["frank_layout"] = new_layout

            # Recalculate app zone
            frank = new_layout
            margin = 10
            if frank.get("position", "left") == "left":
                app_x = frank.get("x", 10) + frank.get("width", 420) + margin
            else:
                app_x = margin

            self.profile["app_zone"] = {
                "x": app_x,
                "y": 0,
                "width": self.monitor.width - app_x - margin,
                "height": self.monitor.height - 48 - margin,
            }

            # Add to history
            add_proposal_to_history(
                self.profile,
                "frank",
                new_layout,
                response[:100]
            )

            # Update preview
            self._update_preview()

        return False

    def _on_apply(self, button):
        """Apply the configuration."""
        self.sound.play_apply()

        # Mark as approved
        self.profile.setdefault("meta", {})["user_approved"] = True

        # Save profile
        save_profile(self.profile)
        LOG.info(f"Saved profile for {self.monitor.edid_hash}")

        # Signal Frank to apply settings
        self._write_apply_signal()

        # Add confirmation message
        self._add_message("frank", "Configuration saved! Settings will be applied.")

        # Close after short delay
        timer_id = GLib.timeout_add(1500, self.close)
        self._timer_ids.append(timer_id)

    def _write_apply_signal(self):
        """Write signal file for Frank to apply settings."""
        try:
            from config.paths import get_temp as _get_temp_adia
            signal_file = _get_temp_adia("adi_apply_signal")
        except ImportError:
            signal_file = Path("/tmp/frank/adi_apply_signal")
        try:
            with open(signal_file, 'w') as f:
                f.write(self.monitor.edid_hash)
        except Exception as e:
            LOG.warning(f"Failed to write apply signal: {e}")

    def _on_later(self, button):
        """Close without applying."""
        self.sound.play_popup_dismiss()
        self.close()


class ADIPopupApp(Gtk.Application):
    """GTK Application for ADI popup."""

    def __init__(self, reopen: bool = False):
        super().__init__(application_id="com.frank.adi.popup")
        self.reopen = reopen
        self.window = None

    def do_activate(self):
        """Activate the application."""
        if not self.window:
            self.window = ADIPopupWindow(self, reopen=self.reopen)
        self.window.present()


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="ADI - Adaptive Display Intelligence")
    parser.add_argument("--reopen", action="store_true", help="Reopen existing profile")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    if args.debug:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)

    # Check singleton
    lock_file = Path(f"/run/user/{os.getuid()}/frank/adi_popup.lock")
    lock_file.parent.mkdir(parents=True, exist_ok=True)

    try:
        lock_fd = open(lock_file, 'w')
        fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (IOError, OSError):
        LOG.warning("ADI popup already running")
        sys.exit(1)

    app = ADIPopupApp(reopen=args.reopen)
    app.run()


if __name__ == "__main__":
    main()
