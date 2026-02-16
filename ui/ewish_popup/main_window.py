#!/usr/bin/env python3
"""
E-WISH Popup - Main Window
Cyberpunk-styled GTK4 popup for Frank's wishes.
"""

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Gdk', '4.0')

from gi.repository import Gtk, Gdk, GLib, Gio, Pango
import json
import logging
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional, Callable

# Setup logging - FIX: INFO instead of DEBUG in production
LOG = logging.getLogger("ewish_popup")
if not LOG.handlers:
    LOG.addHandler(logging.StreamHandler(sys.stderr))
    LOG.setLevel(logging.INFO)  # FIX: DEBUG causes performance overhead

# Add parent path for imports
AICORE_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(AICORE_ROOT))

# Import E-WISH
try:
    from ext.e_wish import get_ewish, Wish, WishState, WishCategory, CATEGORY_CONFIG
    EWISH_AVAILABLE = True
except ImportError as e:
    LOG.warning(f"E-WISH import failed: {e}")
    EWISH_AVAILABLE = False

# Import sound manager (reuse from fas_popup)
try:
    from ui.fas_popup.sound_manager import SoundManager
    SOUND_AVAILABLE = True
except ImportError:
    SOUND_AVAILABLE = False

    class SoundManager:
        """Dummy sound manager."""
        def __init__(self, *args, **kwargs): pass
        def play_popup_appear(self): pass
        def play_click(self): pass
        def play_integration_done(self): pass
        def play_dismiss(self): pass


class EWishPopupWindow(Gtk.ApplicationWindow):
    """Main E-WISH Popup Window."""

    # Maximum number of retry attempts for timer (prevents infinite loop)
    MAX_OVERLAY_RETRIES = 50  # 50 * 100ms = 5 seconds max

    def __init__(self, app: Gtk.Application, wish: 'Wish' = None):
        super().__init__(application=app, title="Frank Has a Wish")

        self.wish = wish
        self._timer_ids: List[int] = []
        self._response_callback: Optional[Callable] = None
        self._overlay_retry_count = 0  # FIX: Counter for timer retries

        # Window dimensions
        self.popup_width = 700
        self.popup_height = 500

        # Sound manager
        self.sound = SoundManager(enabled=True, volume=0.6)

        self._setup_window()
        self._load_css()
        self._build_ui()
        self._setup_keyboard_shortcuts()

        # Play appear sound
        self.sound.play_popup_appear()

    def set_response_callback(self, callback: Callable):
        """Set callback for when user responds."""
        self._response_callback = callback

    def _setup_window(self):
        """Configure window properties."""
        self.set_default_size(self.popup_width, self.popup_height)
        self.set_resizable(False)
        self.set_decorated(True)
        self.add_css_class("ewish-popup-window")

        # Create overlay after window is realized
        self.connect("realize", self._on_realize)

    def _on_realize(self, widget):
        """Called when window is realized."""
        self._create_overlay_window()
        timer_id = GLib.timeout_add(500, self._center_and_raise)
        self._timer_ids.append(timer_id)

    def _create_overlay_window(self):
        """Create semi-transparent dark overlay behind popup."""
        # Signal Frank overlay to dim
        self._signal_frank_dim(True)

        # Get screen size
        self.screen_width = 1920
        self.screen_height = 1080
        try:
            result = subprocess.run(['xrandr', '--query'], capture_output=True, text=True)
            import re
            max_x = 0
            max_y = 0
            for line in result.stdout.split('\n'):
                if ' connected' in line:
                    match = re.search(r'(\d+)x(\d+)\+(\d+)\+(\d+)', line)
                    if match:
                        w, h, x, y = int(match.group(1)), int(match.group(2)), int(match.group(3)), int(match.group(4))
                        max_x = max(max_x, x + w)
                        max_y = max(max_y, y + h)
            if max_x > 0:
                self.screen_width = max_x
                self.screen_height = max_y
        except Exception as e:
            LOG.warning(f"Screen size detection failed: {e}")

        # Create overlay window
        self.overlay_window = Gtk.Window()
        self.overlay_window.set_title("ewish-dark-overlay")
        self.overlay_window.set_decorated(False)

        overlay_box = Gtk.Box()
        overlay_box.add_css_class("ewish-overlay-bg")

        # Click to close
        click = Gtk.GestureClick()
        click.connect("pressed", self._on_overlay_clicked)
        overlay_box.add_controller(click)

        self.overlay_window.set_child(overlay_box)
        self.connect("close-request", self._on_close_request)

        self.overlay_window.present()
        self.overlay_window.fullscreen()

        timer_id = GLib.timeout_add(50, self._setup_overlay_opacity)
        self._timer_ids.append(timer_id)

    def _setup_overlay_opacity(self):
        """Set overlay opacity via X11 (FIX: with max retries)."""
        # FIX: Prevent infinite loop
        self._overlay_retry_count += 1
        if self._overlay_retry_count > self.MAX_OVERLAY_RETRIES:
            LOG.warning(f"Overlay setup failed after {self.MAX_OVERLAY_RETRIES} retries")
            return False

        try:
            result = subprocess.run(
                ['xdotool', 'search', '--name', 'ewish-dark-overlay'],
                capture_output=True, text=True, timeout=5
            )
            if not result.stdout.strip():
                timer_id = GLib.timeout_add(100, self._setup_overlay_opacity)
                self._timer_ids.append(timer_id)
                return False

            dim_wid = result.stdout.strip().split()[0]

            # Make sticky and set opacity to 75%
            subprocess.run(['wmctrl', '-i', '-r', dim_wid, '-b', 'add,sticky'], capture_output=True, timeout=5)
            subprocess.run([
                'xprop', '-id', dim_wid,
                '-f', '_NET_WM_WINDOW_OPACITY', '32c',
                '-set', '_NET_WM_WINDOW_OPACITY', '3221225472'
            ], capture_output=True, timeout=5)

            # Lower Frank windows
            frank_result = subprocess.run(['xdotool', 'search', '--name', 'Frank'], capture_output=True, text=True, timeout=5)
            if frank_result.stdout.strip():
                for frank_wid in frank_result.stdout.strip().split('\n'):
                    if frank_wid.strip():
                        subprocess.run(['xdotool', 'windowlower', frank_wid.strip()], capture_output=True, timeout=5)

            subprocess.run(['xdotool', 'windowraise', dim_wid], capture_output=True, timeout=5)

        except Exception as e:
            LOG.warning(f"Overlay setup error: {e}")
        return False

    def _center_and_raise(self):
        """Center popup on current monitor."""
        import re
        try:
            # Get mouse position
            result = subprocess.run(['xdotool', 'getmouselocation', '--shell'], capture_output=True, text=True)
            mouse_x, mouse_y = 960, 540
            for line in result.stdout.split('\n'):
                if line.startswith('X='):
                    mouse_x = int(line.split('=')[1])
                elif line.startswith('Y='):
                    mouse_y = int(line.split('=')[1])

            # Get monitors
            result = subprocess.run(['xrandr', '--query'], capture_output=True, text=True)
            monitors = []
            for line in result.stdout.split('\n'):
                if ' connected' in line:
                    match = re.search(r'(\d+)x(\d+)\+(\d+)\+(\d+)', line)
                    if match:
                        monitors.append({
                            'width': int(match.group(1)),
                            'height': int(match.group(2)),
                            'x': int(match.group(3)),
                            'y': int(match.group(4)),
                        })

            # Find target monitor
            target = monitors[0] if monitors else {'width': 1920, 'height': 1080, 'x': 0, 'y': 0}
            for mon in monitors:
                if mon['x'] <= mouse_x < mon['x'] + mon['width'] and mon['y'] <= mouse_y < mon['y'] + mon['height']:
                    target = mon
                    break

            # Center position
            x = target['x'] + (target['width'] - self.popup_width) // 2
            y = target['y'] + (target['height'] - self.popup_height) // 2

            # Move and raise
            subprocess.run([
                'wmctrl', '-r', 'Frank Has a Wish',
                '-e', f'0,{x},{y},{self.popup_width},{self.popup_height}'
            ], capture_output=True)
            subprocess.run([
                'wmctrl', '-r', 'Frank Has a Wish',
                '-b', 'add,above,sticky'
            ], capture_output=True)

            # Proper stacking order
            dim_result = subprocess.run(['xdotool', 'search', '--name', 'ewish-dark-overlay'], capture_output=True, text=True, timeout=5)
            if dim_result.stdout.strip():
                dim_wid = dim_result.stdout.strip().split()[0]
                subprocess.run(['xdotool', 'windowraise', dim_wid], capture_output=True, timeout=5)

            popup_result = subprocess.run(['xdotool', 'search', '--name', 'Frank Has a Wish'], capture_output=True, text=True, timeout=5)
            if popup_result.stdout.strip():
                popup_wid = popup_result.stdout.strip().split()[0]
                subprocess.run(['xdotool', 'windowactivate', popup_wid], capture_output=True, timeout=5)
                subprocess.run(['xdotool', 'windowraise', popup_wid], capture_output=True, timeout=5)

        except Exception as e:
            LOG.warning(f"Window positioning error: {e}")
        return False

    def _on_overlay_clicked(self, gesture, n_press, x, y):
        """Handle overlay click - postpone."""
        self._on_later(None)

    def _on_close_request(self, window):
        """Handle window close."""
        for timer_id in self._timer_ids:
            try:
                GLib.source_remove(timer_id)
            except Exception:
                pass
        self._timer_ids.clear()

        self._signal_frank_dim(False)
        if hasattr(self, 'overlay_window') and self.overlay_window:
            self.overlay_window.close()
        return False

    def _signal_frank_dim(self, dim: bool):
        """Signal Frank overlay to dim/restore."""
        signal_file = Path("/tmp/frank_ewish_dim_signal")
        try:
            if dim:
                signal_file.touch()
            else:
                if signal_file.exists():
                    signal_file.unlink()
        except Exception as e:
            LOG.warning(f"Frank signal error: {e}")

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
        """Build the main UI."""
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        main_box.add_css_class("ewish-main-container")

        # Header
        header = self._build_header()
        main_box.append(header)

        # Wish content
        content = self._build_wish_content()
        main_box.append(content)

        # Chat input
        chat_box = self._build_chat_input()
        main_box.append(chat_box)

        # Actions
        actions = self._build_actions()
        main_box.append(actions)

        self.set_child(main_box)

    def _build_header(self) -> Gtk.Box:
        """Build header section."""
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        header.add_css_class("ewish-header")

        # Title
        title_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        title_box.set_hexpand(True)

        title = Gtk.Label(label="░▒▓ FRANK HAS A WISH ▓▒░")
        title.add_css_class("ewish-title")
        title.set_halign(Gtk.Align.START)
        title_box.append(title)

        subtitle = Gtk.Label(label="E-WISH v1.0 - Emergent Wish Expression")
        subtitle.add_css_class("ewish-subtitle")
        subtitle.set_halign(Gtk.Align.START)
        title_box.append(subtitle)

        header.append(title_box)

        # Close button
        close_btn = Gtk.Button(label="✕")
        close_btn.add_css_class("ewish-close-button")
        close_btn.connect("clicked", lambda _: self._on_later(None))
        header.append(close_btn)

        return header

    def _build_wish_content(self) -> Gtk.Box:
        """Build wish content section."""
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        content.add_css_class("ewish-content")
        content.set_vexpand(True)

        if not self.wish:
            # No wish - show placeholder
            label = Gtk.Label(label="No wishes available")
            label.add_css_class("ewish-no-wish")
            content.append(label)
            return content

        # Category badge and intensity
        badge_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)

        config = self.wish.get_category_config()
        category_label = Gtk.Label(label=f"{config['icon']} {config['label']}")
        category_label.add_css_class("ewish-category-badge")
        # Set color via inline style
        category_label.set_css_classes(["ewish-category-badge", f"ewish-category-{self.wish.category.value}"])
        badge_box.append(category_label)

        # Intensity bar
        intensity_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        intensity_box.set_hexpand(True)

        intensity_label = Gtk.Label(label="Intensity:")
        intensity_label.add_css_class("ewish-intensity-label")
        intensity_box.append(intensity_label)

        intensity_bar = Gtk.ProgressBar()
        intensity_bar.add_css_class("ewish-intensity-bar")
        intensity_bar.set_fraction(self.wish.get_current_intensity())
        intensity_bar.set_hexpand(True)
        intensity_box.append(intensity_bar)

        intensity_pct = Gtk.Label(label=f"{self.wish.get_current_intensity():.0%}")
        intensity_pct.add_css_class("ewish-intensity-pct")
        intensity_box.append(intensity_pct)

        badge_box.append(intensity_box)
        content.append(badge_box)

        # Main wish card
        wish_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        wish_card.add_css_class("ewish-card")

        # Description
        desc_label = Gtk.Label(label=f'"{self.wish.description}"')
        desc_label.add_css_class("ewish-description")
        desc_label.set_wrap(True)
        desc_label.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        desc_label.set_max_width_chars(60)
        desc_label.set_halign(Gtk.Align.START)
        wish_card.append(desc_label)

        # Reasoning
        if self.wish.reasoning:
            reason_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            reason_icon = Gtk.Label(label="💭")
            reason_box.append(reason_icon)

            reason_label = Gtk.Label(label=self.wish.reasoning)
            reason_label.add_css_class("ewish-reasoning")
            reason_label.set_wrap(True)
            reason_label.set_max_width_chars(55)
            reason_label.set_halign(Gtk.Align.START)
            reason_box.append(reason_label)
            wish_card.append(reason_box)

        # Success criteria
        if self.wish.success_criteria:
            criteria_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            criteria_icon = Gtk.Label(label="✅")
            criteria_box.append(criteria_icon)

            criteria_title = Gtk.Label(label="Success Criteria:")
            criteria_title.add_css_class("ewish-criteria-title")
            criteria_box.append(criteria_title)
            wish_card.append(criteria_box)

            criteria_label = Gtk.Label(label=self.wish.success_criteria)
            criteria_label.add_css_class("ewish-criteria")
            criteria_label.set_wrap(True)
            criteria_label.set_max_width_chars(55)
            criteria_label.set_halign(Gtk.Align.START)
            criteria_label.set_margin_start(28)
            wish_card.append(criteria_label)

        content.append(wish_card)

        # Priority indicator
        priority_label = Gtk.Label(label=f"Priority: {self.wish.priority.name}")
        priority_label.add_css_class("ewish-priority")
        priority_label.set_halign(Gtk.Align.START)
        content.append(priority_label)

        return content

    def _build_chat_input(self) -> Gtk.Box:
        """Build chat input section."""
        chat_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        chat_box.add_css_class("ewish-chat-container")

        label = Gtk.Label(label="💬 Your Response (optional):")
        label.add_css_class("ewish-chat-label")
        label.set_halign(Gtk.Align.START)
        chat_box.append(label)

        # Text entry
        self.chat_entry = Gtk.Entry()
        self.chat_entry.add_css_class("ewish-chat-entry")
        self.chat_entry.set_placeholder_text("Type your response here...")
        self.chat_entry.connect("activate", self._on_send_response)
        chat_box.append(self.chat_entry)

        return chat_box

    def _build_actions(self) -> Gtk.Box:
        """Build action buttons section."""
        actions = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        actions.add_css_class("ewish-actions-container")

        # Quick action buttons
        btn_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        btn_row.set_halign(Gtk.Align.CENTER)

        # Approve button
        approve_btn = Gtk.Button(label="✓ ALLOW")
        approve_btn.add_css_class("ewish-button")
        approve_btn.add_css_class("ewish-button-approve")
        approve_btn.connect("clicked", self._on_approve)
        btn_row.append(approve_btn)

        # Reject button
        reject_btn = Gtk.Button(label="✗ REJECT")
        reject_btn.add_css_class("ewish-button")
        reject_btn.add_css_class("ewish-button-reject")
        reject_btn.connect("clicked", self._on_reject)
        btn_row.append(reject_btn)

        # Later button
        later_btn = Gtk.Button(label="⏰ LATER")
        later_btn.add_css_class("ewish-button")
        later_btn.add_css_class("ewish-button-later")
        later_btn.connect("clicked", self._on_later)
        btn_row.append(later_btn)

        # More info button
        info_btn = Gtk.Button(label="💬 MORE INFO")
        info_btn.add_css_class("ewish-button")
        info_btn.add_css_class("ewish-button-info")
        info_btn.connect("clicked", self._on_more_info)
        btn_row.append(info_btn)

        actions.append(btn_row)

        # Send with message button
        send_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        send_row.set_halign(Gtk.Align.CENTER)

        self.send_btn = Gtk.Button(label="▶ RESPOND WITH MESSAGE")
        self.send_btn.add_css_class("ewish-button")
        self.send_btn.add_css_class("ewish-button-send")
        self.send_btn.connect("clicked", self._on_send_response)
        send_row.append(self.send_btn)

        actions.append(send_row)

        # Keyboard hint
        hint = Gtk.Label(label="Y = Allow | N = Reject | ESC = Later | Enter = Send")
        hint.add_css_class("ewish-keyboard-hint")
        actions.append(hint)

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
            self._on_send_response(None)
            return True
        elif key_name.lower() == "y":
            self._on_approve(None)
            return True
        elif key_name.lower() == "n":
            self._on_reject(None)
            return True

        return False

    # Maximum length for user responses (FIX: Input Validation)
    MAX_RESPONSE_LENGTH = 1000

    def _get_response_text(self) -> str:
        """Get text from chat entry (FIX: with input validation)."""
        text = self.chat_entry.get_text().strip()
        # Limit length
        if len(text) > self.MAX_RESPONSE_LENGTH:
            text = text[:self.MAX_RESPONSE_LENGTH]
            LOG.warning(f"Response truncated to {self.MAX_RESPONSE_LENGTH} chars")
        return text

    def _on_approve(self, button):
        """Handle approve action."""
        self.sound.play_integration_done()

        if self.wish and EWISH_AVAILABLE:
            ewish = get_ewish()
            response = self._get_response_text()
            ewish.activate_wish(self.wish.id, response)
            LOG.info(f"Wish approved: {self.wish.id}")

        if self._response_callback:
            self._response_callback("approved", self.wish, self._get_response_text())

        self._show_inline_confirmation("✓ WISH ALLOWED", "Frank will work on it.", "#00ff88")
        GLib.timeout_add(2500, self._close_all)  # FIX: Longer confirmation (2.5s)

    def _on_reject(self, button):
        """Handle reject action."""
        self.sound.play_dismiss()

        if self.wish and EWISH_AVAILABLE:
            ewish = get_ewish()
            response = self._get_response_text()
            if response:
                ewish.set_user_response(self.wish.id, response)
            ewish.reject_wish(self.wish.id, "user_rejected")
            LOG.info(f"Wish rejected: {self.wish.id}")

        if self._response_callback:
            self._response_callback("rejected", self.wish, self._get_response_text())

        self._show_inline_confirmation("✗ WISH REJECTED", "Frank understands.", "#ff4444")
        GLib.timeout_add(2500, self._close_all)  # FIX: Longer confirmation (2.5s)

    def _on_later(self, button):
        """Handle later action."""
        self.sound.play_dismiss()

        if self.wish and EWISH_AVAILABLE:
            ewish = get_ewish()
            ewish.postpone_wish(self.wish.id)

        if self._response_callback:
            self._response_callback("postponed", self.wish, "")

        self.close()

    def _on_more_info(self, button):
        """Handle more info request."""
        self.sound.play_click()

        if self._response_callback:
            self._response_callback("more_info", self.wish, "")

        # Show more info dialog
        if self.wish:
            self._show_details_dialog()

    def _on_send_response(self, widget):
        """Handle send with message."""
        response = self._get_response_text()
        if not response:
            # No text, just approve
            self._on_approve(None)
            return

        self.sound.play_integration_done()

        if self.wish and EWISH_AVAILABLE:
            ewish = get_ewish()
            ewish.activate_wish(self.wish.id, response)

        if self._response_callback:
            self._response_callback("approved_with_message", self.wish, response)

        self._show_inline_confirmation("✓ RESPONSE SENT", f"Message: {response[:40]}...", "#00ff88")
        GLib.timeout_add(2500, self._close_all)  # FIX: Longer confirmation (2.5s)

    # Allowed colors for confirmation (FIX: CSS Injection Prevention)
    ALLOWED_COLORS = {"#00ff88", "#ff4444", "#00fff9", "#ff00ff", "#ffff00"}

    def _show_inline_confirmation(self, title: str, message: str, color: str = "#00ff88"):
        """Show confirmation by replacing main content (FIX: CSS Injection Prevention)."""
        # FIX: Validate color against whitelist
        if color not in self.ALLOWED_COLORS:
            LOG.warning(f"Invalid color rejected: {color}, using default")
            color = "#00ff88"

        # Create confirmation overlay
        confirm_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        confirm_box.set_valign(Gtk.Align.CENTER)
        confirm_box.set_halign(Gtk.Align.CENTER)
        confirm_box.set_vexpand(True)

        # Big checkmark/X
        icon_label = Gtk.Label(label=title)
        icon_label.set_css_classes(["ewish-confirm-title"])
        # Apply color via inline CSS (color is now validated)
        css = f"""
            .ewish-confirm-title {{
                font-family: 'Share Tech Mono', monospace;
                font-size: 28px;
                font-weight: bold;
                color: {color};
                text-shadow: 0 0 20px {color};
            }}
            .ewish-confirm-message {{
                font-family: sans-serif;
                font-size: 16px;
                color: #e0e0e0;
            }}
        """
        css_provider = Gtk.CssProvider()
        css_provider.load_from_data(css.encode())
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(),
            css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_USER
        )
        confirm_box.append(icon_label)

        # Message
        msg_label = Gtk.Label(label=message)
        msg_label.set_css_classes(["ewish-confirm-message"])
        confirm_box.append(msg_label)

        # Replace main content
        child = self.get_child()
        if child:
            # Clear existing content and show confirmation
            for widget in list(child):
                child.remove(widget)
            child.append(confirm_box)

        LOG.info(f"Confirmation shown: {title}")

    def _close_all(self):
        """Close popup and overlay."""
        LOG.info("Closing E-WISH popup")
        self.close()
        return False  # Don't repeat

    def _show_details_dialog(self):
        """Show detailed wish information."""
        dialog = Gtk.Window(title=f"Wish Details")
        dialog.set_transient_for(self)
        dialog.set_modal(True)
        dialog.set_default_size(500, 400)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.set_margin_top(20)
        box.set_margin_bottom(20)
        box.set_margin_start(20)
        box.set_margin_end(20)

        # Details
        details = [
            ("Category", self.wish.category.value),
            ("Priority", self.wish.priority.name),
            ("Status", self.wish.state.value),
            ("Intensity", f"{self.wish.get_current_intensity():.0%}"),
            ("Source", f"{self.wish.source_module}/{self.wish.source_event}"),
            ("Created", self.wish.created_at.strftime("%Y-%m-%d %H:%M")),
            ("Self-solvable", "Yes" if self.wish.actionable else "No"),
            ("Requires User", "Yes" if self.wish.requires_user else "No"),
        ]

        for label, value in details:
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            lbl = Gtk.Label(label=f"{label}:")
            lbl.set_halign(Gtk.Align.START)
            lbl.set_width_chars(20)
            row.append(lbl)
            val = Gtk.Label(label=value)
            val.set_halign(Gtk.Align.START)
            row.append(val)
            box.append(row)

        # Close button
        close_btn = Gtk.Button(label="Close")
        close_btn.connect("clicked", lambda b: dialog.close())
        close_btn.set_halign(Gtk.Align.CENTER)
        close_btn.set_margin_top(12)
        box.append(close_btn)

        dialog.set_child(box)
        dialog.present()


class EWishPopupApp(Gtk.Application):
    """GTK Application wrapper."""

    LOCK_FILE = Path(f"/run/user/{os.getuid()}/frank/ewish_popup.lock")

    def __init__(self, wish: 'Wish' = None):
        super().__init__(
            application_id="com.frank.ewish.popup",
            flags=Gio.ApplicationFlags.FLAGS_NONE
        )
        self.wish = wish
        self.win = None
        self.connect("activate", self.on_activate)
        self.connect("shutdown", self.on_shutdown)

    @classmethod
    def is_already_running(cls) -> bool:
        """Check if already running (FIX: Memory leak with lock file)."""
        import fcntl
        cls.LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
        try:
            cls._lock_fd = open(cls.LOCK_FILE, 'w')
            try:
                fcntl.flock(cls._lock_fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                cls._lock_fd.write(str(os.getpid()))
                cls._lock_fd.flush()
                return False
            except (IOError, OSError):
                # FIX: Close file if lock fails
                cls._lock_fd.close()
                cls._lock_fd = None
                return True
        except (IOError, OSError):
            return True

    @classmethod
    def release_lock(cls):
        """Release lock file."""
        import fcntl
        try:
            if hasattr(cls, '_lock_fd') and cls._lock_fd:
                fcntl.flock(cls._lock_fd.fileno(), fcntl.LOCK_UN)
                cls._lock_fd.close()
            if cls.LOCK_FILE.exists():
                cls.LOCK_FILE.unlink()
        except Exception:
            pass

    def on_activate(self, app):
        """Handle activate signal."""
        if not self.win:
            self.win = EWishPopupWindow(self, self.wish)
        self.win.present()

    def on_shutdown(self, app):
        """Handle shutdown."""
        self.release_lock()


def show_wish_popup(wish: 'Wish' = None, callback: Callable = None):
    """
    Show the E-WISH popup.

    Args:
        wish: The wish to display (or None to get from E-WISH)
        callback: Called with (action, wish, response) when user responds
    """
    if EWishPopupApp.is_already_running():
        LOG.info("E-WISH popup already running")
        try:
            subprocess.run(['wmctrl', '-a', 'Frank Has a Wish'], capture_output=True)
        except Exception:
            pass
        return

    # Get wish from E-WISH if not provided
    if wish is None and EWISH_AVAILABLE:
        ewish = get_ewish()
        wishes = ewish.get_expressible_wishes()
        wish = wishes[0] if wishes else None

    if not wish:
        LOG.info("No wish to display")
        return

    try:
        app = EWishPopupApp(wish=wish)
        if callback and app.win:
            app.win.set_response_callback(callback)
        app.run([])
    finally:
        EWishPopupApp.release_lock()


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="E-WISH Popup")
    parser.add_argument("--wish-id", type=str, help="Specific wish ID to display")
    parser.add_argument("--test", action="store_true", help="Show test wish")
    parser.add_argument("--force", action="store_true", help="Force start")
    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG)

    wish = None

    if args.test:
        # Create test wish
        if EWISH_AVAILABLE:
            ewish = get_ewish()
            wish = ewish.add_manual_wish(
                "Ich möchte meine PDF-Analyse-Fähigkeiten verbessern",
                WishCategory.IMPROVEMENT,
                "Wiederholte Schwierigkeiten beim Parsen komplexer PDFs"
            )
    elif args.wish_id and EWISH_AVAILABLE:
        ewish = get_ewish()
        wish = ewish.get_wish_by_id(args.wish_id)
    elif EWISH_AVAILABLE:
        ewish = get_ewish()
        wishes = ewish.get_expressible_wishes()
        wish = wishes[0] if wishes else None

    if not wish and not args.force:
        print("No wish to display. Use --test to show a test wish.")
        return

    if not args.force and EWishPopupApp.is_already_running():
        print("E-WISH popup already running. Use --force to override.")
        return

    def on_response(action, wish, response):
        print(f"Response: action={action}, wish_id={wish.id if wish else None}, response={response}")

    try:
        app = EWishPopupApp(wish=wish)
        # Set callback after window is created
        def set_callback():
            if app.win:
                app.win.set_response_callback(on_response)
            return False
        GLib.idle_add(set_callback)
        app.run([])
    finally:
        EWishPopupApp.release_lock()


if __name__ == "__main__":
    main()
