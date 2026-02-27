"""
Frank Chat Panel for Sidebar
Natural language command interface
"""

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, GLib, Pango

from typing import Callable, Optional, List
import re
import json
import threading
from pathlib import Path
from dataclasses import dataclass, asdict

from writer.sidebar.intent_parser import IntentParser, Intent

# Persistent chat history file
try:
    from config.paths import AICORE_CONFIG
    CHAT_HISTORY_PATH = AICORE_CONFIG / "writer" / "chat_history.json"
except ImportError:
    CHAT_HISTORY_PATH = Path.home() / ".config" / "frank" / "writer" / "chat_history.json"
MAX_HISTORY_MESSAGES = 100


@dataclass
class ChatMessage:
    """A chat message"""
    role: str  # 'user' or 'frank'
    content: str
    is_action: bool = False
    action_type: str = None


class ChatPanel(Gtk.Box):
    """Chat panel for Frank interaction"""

    def __init__(self, frank_bridge, on_action: Callable):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.frank_bridge = frank_bridge
        self.on_action = on_action
        self.intent_parser = IntentParser()
        self.messages: List[ChatMessage] = []
        self.pending_confirmation = None

        self.set_margin_start(6)
        self.set_margin_end(6)
        self.set_margin_top(6)
        self.set_margin_bottom(6)
        self.set_spacing(6)

        self._build_ui()
        self._load_history()

    def _build_ui(self):
        """Build chat panel UI"""
        # Header
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        header.set_spacing(6)

        icon = Gtk.Image.new_from_icon_name("user-available-symbolic")
        header.append(icon)

        title = Gtk.Label(label="Frank")
        title.add_css_class("heading")
        header.append(title)

        self.append(header)

        # Chat history
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        self.chat_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.chat_box.set_margin_top(6)
        self.chat_box.set_margin_bottom(6)
        scrolled.set_child(self.chat_box)
        self.append(scrolled)

        # Input area
        input_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)

        self.entry = Gtk.Entry()
        self.entry.set_placeholder_text("Message to Frank...")
        self.entry.set_hexpand(True)
        self.entry.connect('activate', self._on_send)
        input_box.append(self.entry)

        send_btn = Gtk.Button(icon_name="go-next-symbolic")
        send_btn.add_css_class("suggested-action")
        send_btn.connect('clicked', self._on_send)
        input_box.append(send_btn)

        self.append(input_box)

        # Add welcome message
        self._add_message(ChatMessage(
            role='frank',
            content="Hello! How can I help? You can ask me to save, export, run code, or edit text."
        ))

    def _add_message(self, message: ChatMessage, show_actions: bool = False):
        """Add message to chat"""
        self.messages.append(message)

        # Create message widget
        msg_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)

        # Role label
        role_label = Gtk.Label(
            label="You:" if message.role == 'user' else "Frank:"
        )
        role_label.add_css_class("dim-label")
        role_label.set_halign(Gtk.Align.START)
        msg_box.append(role_label)

        # Content
        content_label = Gtk.Label(label=message.content)
        content_label.set_wrap(True)
        content_label.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        content_label.set_halign(Gtk.Align.START)
        content_label.set_hexpand(True)
        content_label.set_selectable(True)
        content_label.set_xalign(0)

        if message.role == 'frank':
            content_label.add_css_class("accent")

        msg_box.append(content_label)

        # Action buttons for Frank responses (Copy / Insert into text)
        if show_actions and message.role == 'frank' and message.content.strip():
            btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
            btn_box.set_margin_top(2)

            copy_btn = Gtk.Button(label="Copy")
            copy_btn.add_css_class("flat")
            copy_btn.add_css_class("small")
            copy_btn.set_tooltip_text("Copy to clipboard")
            response_text = message.content
            copy_btn.connect('clicked', lambda b, t=response_text: self._copy_to_clipboard(t))
            btn_box.append(copy_btn)

            insert_btn = Gtk.Button(label="Insert")
            insert_btn.add_css_class("flat")
            insert_btn.add_css_class("small")
            insert_btn.set_tooltip_text("Insert into document")
            insert_btn.connect('clicked', lambda b, t=response_text: self._insert_into_document(t))
            btn_box.append(insert_btn)

            msg_box.append(btn_box)

        self.chat_box.append(msg_box)

        # Scroll to bottom and persist
        GLib.idle_add(self._scroll_to_bottom)
        self._save_history()

    def _scroll_to_bottom(self):
        """Scroll chat to bottom"""
        adj = self.chat_box.get_parent().get_vadjustment()
        adj.set_value(adj.get_upper())
        return False

    def _on_send(self, widget):
        """Handle send button/enter"""
        text = self.entry.get_text().strip()
        if not text:
            return

        self.entry.set_text("")

        # Add user message
        self._add_message(ChatMessage(role='user', content=text))

        # Handle pending confirmation
        if self.pending_confirmation:
            self._handle_confirmation_response(text)
            return

        # Parse intent
        intent = self.intent_parser.parse(text)

        if intent:
            self._handle_intent(intent)
        else:
            # Send to Frank for general chat
            self._send_to_frank(text)

    def _handle_intent(self, intent: Intent):
        """Handle parsed intent"""
        if intent.critical:
            # Ask for confirmation
            self.pending_confirmation = intent
            self._show_confirmation(intent)
        else:
            # Execute directly
            self._execute_intent(intent)

    def _show_confirmation(self, intent: Intent):
        """Show confirmation for critical action"""
        confirmation_text = intent.confirmation_message

        # Create confirmation widget
        confirm_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)

        msg_label = Gtk.Label(label=confirmation_text)
        msg_label.set_wrap(True)
        msg_label.set_halign(Gtk.Align.START)
        confirm_box.append(msg_label)

        # Buttons
        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)

        yes_btn = Gtk.Button(label="Yes")
        yes_btn.add_css_class("suggested-action")
        yes_btn.connect('clicked', lambda b: self._confirm_action(True))
        btn_box.append(yes_btn)

        no_btn = Gtk.Button(label="No")
        no_btn.connect('clicked', lambda b: self._confirm_action(False))
        btn_box.append(no_btn)

        confirm_box.append(btn_box)

        # Add confirm_box to chat_box UI
        self.chat_box.append(confirm_box)

        # Add to chat
        self._add_message(ChatMessage(
            role='frank',
            content=confirmation_text,
            is_action=True,
            action_type='confirmation'
        ))

    def _confirm_action(self, confirmed: bool):
        """Handle confirmation response"""
        intent = self.pending_confirmation
        self.pending_confirmation = None

        if confirmed:
            self._add_message(ChatMessage(role='user', content="Yes"))
            self._execute_intent(intent)
        else:
            self._add_message(ChatMessage(role='user', content="No"))
            self._add_message(ChatMessage(
                role='frank',
                content="Okay, cancelled."
            ))

    def _handle_confirmation_response(self, text: str):
        """Handle text response to confirmation"""
        text_lower = text.lower()
        if text_lower in ['yes', 'ja', 'ok', 'okay', 'do it', 'sure', 'please']:
            self._confirm_action(True)
        elif text_lower in ['no', 'nein', 'cancel', 'stop', 'abort']:
            self._confirm_action(False)
        else:
            self._add_message(ChatMessage(
                role='frank',
                content="Please answer with 'Yes' or 'No'."
            ))

    def _execute_intent(self, intent: Intent):
        """Execute an intent"""
        # Notify action handler
        self.on_action(intent.action, intent.data)

        # Add confirmation message
        self._add_message(ChatMessage(
            role='frank',
            content=f"✓ {intent.success_message}"
        ))

    def _send_to_frank(self, text: str):
        """Send message to Frank AI with streaming support."""
        # Create streaming response label
        self._streaming_msg_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        role_label = Gtk.Label(label="Frank:")
        role_label.add_css_class("dim-label")
        role_label.set_halign(Gtk.Align.START)
        self._streaming_msg_box.append(role_label)

        self._streaming_label = Gtk.Label(label="...")
        self._streaming_label.set_wrap(True)
        self._streaming_label.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        self._streaming_label.set_halign(Gtk.Align.START)
        self._streaming_label.set_hexpand(True)
        self._streaming_label.set_selectable(True)
        self._streaming_label.set_xalign(0)
        self._streaming_label.add_css_class("accent")
        self._streaming_msg_box.append(self._streaming_label)
        self.chat_box.append(self._streaming_msg_box)

        self._streaming_chunks = []

        def on_token(chunk):
            """Called from background thread for each token."""
            GLib.idle_add(self._append_stream_token, chunk)

        def background_task():
            try:
                response = self.frank_bridge.chat_stream(text, on_token=on_token)
                GLib.idle_add(self._finalize_stream, response)
            except Exception as e:
                # Fallback to non-streaming
                try:
                    response = self.frank_bridge.chat(text)
                    GLib.idle_add(self._finalize_stream, response)
                except Exception as e2:
                    from writer.ai.bridge import AIResponse
                    GLib.idle_add(
                        self._finalize_stream,
                        AIResponse(content="", success=False, error=str(e2))
                    )

        thread = threading.Thread(target=background_task, daemon=True)
        thread.start()

    def _append_stream_token(self, chunk):
        """Append a streaming token to the response label."""
        self._streaming_chunks.append(chunk)
        self._streaming_label.set_label("".join(self._streaming_chunks))
        GLib.idle_add(self._scroll_to_bottom)
        return False

    def _finalize_stream(self, response):
        """Finalize streaming response."""
        from writer.ai.bridge import AIResponse

        # Remove the streaming box (will be replaced by normal message)
        if self._streaming_msg_box and self._streaming_msg_box.get_parent():
            self.chat_box.remove(self._streaming_msg_box)

        if isinstance(response, AIResponse):
            if response.success and response.content:
                self._add_message(ChatMessage(role='frank', content=response.content), show_actions=True)
            else:
                self._add_message(ChatMessage(
                    role='frank',
                    content=f"Error: {response.error or 'No response'}"
                ))
        else:
            self._add_message(ChatMessage(
                role='frank',
                content="Sorry, I could not generate a response."
            ))
        return False

    def _copy_to_clipboard(self, text: str):
        """Copy text to clipboard."""
        display = self.get_display()
        clipboard = display.get_clipboard()
        clipboard.set(text)

    def _insert_into_document(self, text: str):
        """Insert text into the current document at cursor."""
        self.on_action('insert_text', {'text': text})

    def add_system_message(self, content: str):
        """Add a system message to chat"""
        self._add_message(ChatMessage(
            role='frank',
            content=content
        ))

    # ── Chat History Persistence ─────────────────────────

    def _load_history(self):
        """Load chat history from disk."""
        try:
            if CHAT_HISTORY_PATH.exists():
                data = json.loads(CHAT_HISTORY_PATH.read_text(encoding='utf-8'))
                for item in data[-20:]:  # Load last 20 messages
                    msg = ChatMessage(
                        role=item.get('role', 'frank'),
                        content=item.get('content', ''),
                    )
                    self._add_message(msg)
        except Exception:
            pass

    def _save_history(self):
        """Save chat history to disk."""
        try:
            CHAT_HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
            data = [
                {'role': m.role, 'content': m.content}
                for m in self.messages[-MAX_HISTORY_MESSAGES:]
            ]
            CHAT_HISTORY_PATH.write_text(
                json.dumps(data, ensure_ascii=False, indent=1),
                encoding='utf-8'
            )
        except Exception:
            pass
