"""
Live Preview Popup Window
Shows code execution output with Frank chat sidebar
"""

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, GLib, Gdk, GdkPixbuf, Pango

import asyncio
import threading
import weakref
from typing import Optional
from pathlib import Path

from writer.editor.document import Document
from writer.sandbox.executor import SandboxExecutor
from writer.autofix.engine import AutoFixEngine, AutoFixResult
from writer.ai.bridge import FrankBridge

# Constants for configuration
MAX_CHAT_CONTENT_LENGTH = 10000
MAX_CODE_BLOCK_LENGTH = 50000
DEFAULT_PANED_POSITION = 600
SETTINGS_KEY_PANED_POSITION = "preview-paned-position"


class LivePreviewPopup(Adw.Window):
    """Live preview window for code execution"""

    # Class-level registry for popup instances (weak references)
    _instances = weakref.WeakValueDictionary()
    _instance_counter = 0

    def __init__(
        self,
        parent,
        document: Document,
        config,
        frank_bridge: FrankBridge
    ):
        super().__init__()
        self.parent_window = parent
        self.document = document
        self.config = config
        self.frank_bridge = frank_bridge

        # Register this instance with weak reference
        LivePreviewPopup._instance_counter += 1
        self._instance_id = LivePreviewPopup._instance_counter
        LivePreviewPopup._instances[self._instance_id] = self

        # Track window validity
        self._is_destroyed = False

        # Components
        self.sandbox = SandboxExecutor(config.sandbox)
        self.autofix = AutoFixEngine(
            sandbox=self.sandbox,
            frank_bridge=frank_bridge,
            max_attempts=config.sandbox.max_fix_attempts,
            on_progress=self._on_autofix_progress
        )

        # State
        self.is_running = False
        self.current_result = None
        self._cancel_requested = False
        self._current_process = None  # Track running process for cancellation

        # Thread synchronization
        self._run_lock = threading.Lock()

        self._setup_window()
        self._build_ui()

    def _setup_window(self):
        """Setup window properties"""
        self.set_title("Live Preview")
        self.set_default_size(900, 700)
        self.set_transient_for(self.parent_window)
        self.set_modal(False)

        # Handle close and destroy
        self.connect('close-request', self._on_close_request)
        self.connect('destroy', self._on_destroy)

    def _on_destroy(self, widget):
        """Handle window destruction"""
        self._is_destroyed = True
        # Remove from instances registry
        if self._instance_id in LivePreviewPopup._instances:
            del LivePreviewPopup._instances[self._instance_id]

    def _is_valid(self) -> bool:
        """Check if popup is still valid for operations"""
        return not self._is_destroyed and self.get_realized()

    def _build_ui(self):
        """Build the UI"""
        # Main container
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_content(main_box)

        # Header bar
        header = Adw.HeaderBar()
        header.set_title_widget(Adw.WindowTitle(
            title="Live Preview",
            subtitle=self.document.title
        ))

        # Run button
        self.run_btn = Gtk.Button()
        run_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        self.run_icon = Gtk.Image.new_from_icon_name("media-playback-start-symbolic")
        run_box.append(self.run_icon)
        self.run_label = Gtk.Label(label="Run")
        run_box.append(self.run_label)
        self.run_btn.set_child(run_box)
        self.run_btn.add_css_class("suggested-action")
        self.run_btn.connect('clicked', lambda b: self.run_code())
        header.pack_start(self.run_btn)

        # Stop button
        self.stop_btn = Gtk.Button(icon_name="media-playback-stop-symbolic")
        self.stop_btn.set_tooltip_text("Stop")
        self.stop_btn.set_sensitive(False)
        self.stop_btn.connect('clicked', lambda b: self.stop_code())
        header.pack_start(self.stop_btn)

        # Auto-fix toggle
        self.autofix_toggle = Gtk.ToggleButton(label="Auto-Fix")
        self.autofix_toggle.set_active(self.config.sandbox.auto_fix_enabled)
        header.pack_end(self.autofix_toggle)

        main_box.append(header)

        # Content paned
        self.paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        # Load saved position or use default
        saved_position = getattr(self.config, 'get', lambda k, d: d)(
            SETTINGS_KEY_PANED_POSITION, DEFAULT_PANED_POSITION
        )
        self.paned.set_position(saved_position)
        self.paned.set_shrink_start_child(False)
        self.paned.set_shrink_end_child(False)
        # Save position on change
        self.paned.connect('notify::position', self._on_paned_position_changed)
        main_box.append(self.paned)

        # Left side - Output
        output_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.paned.set_start_child(output_box)

        # Output stack (for different output types)
        self.output_stack = Gtk.Stack()
        self.output_stack.set_vexpand(True)
        output_box.append(self.output_stack)

        # Visual output (images/plots)
        visual_scroll = Gtk.ScrolledWindow()
        self.visual_output = Gtk.Picture()
        self.visual_output.set_can_shrink(True)
        visual_scroll.set_child(self.visual_output)
        self.output_stack.add_titled(visual_scroll, "visual", "Visual")

        # Console output
        console_scroll = Gtk.ScrolledWindow()
        self.console_output = Gtk.TextView()
        self.console_output.set_editable(False)
        self.console_output.set_monospace(True)
        self.console_output.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.console_output.set_left_margin(8)
        self.console_output.set_right_margin(8)
        self.console_output.set_top_margin(8)
        console_scroll.set_child(self.console_output)
        self.output_stack.add_titled(console_scroll, "console", "Console")

        # HTML output (WebKitGTK would go here, using placeholder)
        html_scroll = Gtk.ScrolledWindow()
        self.html_label = Gtk.Label(label="HTML Preview")
        html_scroll.set_child(self.html_label)
        self.output_stack.add_titled(html_scroll, "html", "HTML")

        # Output type switcher
        output_switcher = Gtk.StackSwitcher()
        output_switcher.set_stack(self.output_stack)
        output_switcher.set_halign(Gtk.Align.CENTER)
        output_switcher.set_margin_top(6)
        output_switcher.set_margin_bottom(6)
        output_box.append(output_switcher)

        # Status bar
        self.status_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.status_box.set_margin_start(8)
        self.status_box.set_margin_end(8)
        self.status_box.set_margin_bottom(8)

        self.status_icon = Gtk.Image.new_from_icon_name("emblem-ok-symbolic")
        self.status_box.append(self.status_icon)

        self.status_label = Gtk.Label(label="Bereit")
        self.status_label.set_halign(Gtk.Align.START)
        self.status_label.set_hexpand(True)
        self.status_box.append(self.status_label)

        self.time_label = Gtk.Label(label="")
        self.time_label.add_css_class("dim-label")
        self.status_box.append(self.time_label)

        output_box.append(self.status_box)

        # Right side - Chat
        chat_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        chat_box.set_size_request(280, -1)
        self.paned.set_end_child(chat_box)

        # Chat header
        chat_header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        chat_header.set_margin_start(8)
        chat_header.set_margin_end(8)
        chat_header.set_margin_top(8)

        chat_icon = Gtk.Image.new_from_icon_name("user-available-symbolic")
        chat_header.append(chat_icon)

        chat_title = Gtk.Label(label="Frank")
        chat_title.add_css_class("heading")
        chat_header.append(chat_title)

        chat_box.append(chat_header)

        # Chat messages
        self.chat_scroll = Gtk.ScrolledWindow()
        self.chat_scroll.set_vexpand(True)
        self.chat_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        self.chat_messages = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.chat_messages.set_margin_start(8)
        self.chat_messages.set_margin_end(8)
        self.chat_messages.set_margin_top(8)
        self.chat_messages.set_margin_bottom(8)
        self.chat_scroll.set_child(self.chat_messages)
        chat_box.append(self.chat_scroll)

        # Chat input
        input_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        input_box.set_margin_start(8)
        input_box.set_margin_end(8)
        input_box.set_margin_bottom(8)

        self.chat_entry = Gtk.Entry()
        self.chat_entry.set_placeholder_text("Änderung beschreiben...")
        self.chat_entry.set_hexpand(True)
        self.chat_entry.connect('activate', self._on_chat_send)
        input_box.append(self.chat_entry)

        send_btn = Gtk.Button(icon_name="go-next-symbolic")
        send_btn.add_css_class("suggested-action")
        send_btn.connect('clicked', self._on_chat_send)
        input_box.append(send_btn)

        chat_box.append(input_box)

        # Initial chat message
        self._add_chat_message(
            "frank",
            "Ich beobachte den Code. Sag mir, was ich ändern soll, und ich setze es direkt um."
        )

    def run_code(self):
        """Run code in sandbox"""
        if self.is_running:
            return

        # Check window validity
        if not self._is_valid():
            return

        with self._run_lock:
            self.is_running = True
            self._cancel_requested = False

        self._update_running_state(True)

        # Clear previous output
        self._clear_output()

        # Get current code with document lock if available
        code = self._get_document_content_safe()
        language = self.document.language or 'python'

        # Read GTK widget state on main thread BEFORE spawning worker
        autofix_active = self.autofix_toggle.get_active()

        # Run in background thread to avoid blocking GTK main loop
        thread = threading.Thread(
            target=self._run_in_background,
            args=(code, language, autofix_active),
            daemon=True
        )
        thread.start()

    def _get_document_content_safe(self) -> str:
        """Get document content with proper synchronization"""
        # Use document lock if available
        if hasattr(self.document, 'lock'):
            with self.document.lock:
                return self.document.content
        elif hasattr(self.document, 'get_content'):
            return self.document.get_content()
        else:
            return self.document.content

    def _set_document_content_safe(self, content: str):
        """Set document content with proper synchronization - must be called from main thread"""
        def do_set():
            if not self._is_valid():
                return False
            # Use document lock if available
            if hasattr(self.document, 'lock'):
                with self.document.lock:
                    self.document.set_content(content)
            elif hasattr(self.document, 'set_content'):
                self.document.set_content(content)
            else:
                self.document.content = content
            return False
        GLib.idle_add(do_set)

    def _run_in_background(self, code: str, language: str, autofix_active: bool = False):
        """Run code in background thread - does NOT block GTK main loop.

        ``autofix_active`` is read from the GTK toggle on the main thread
        and passed here to avoid accessing GTK widgets from a worker thread.
        """
        try:
            # Create event loop for this thread
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            try:
                if self._cancel_requested:
                    GLib.idle_add(self._on_run_cancelled)
                    return

                if autofix_active:
                    result = loop.run_until_complete(
                        self.autofix.execute_with_autofix(code, language)
                    )

                    if self._cancel_requested:
                        GLib.idle_add(self._on_run_cancelled)
                        return

                    self.current_result = result

                    # Schedule UI updates on main thread
                    if result.success:
                        GLib.idle_add(self._show_result, result)
                    else:
                        GLib.idle_add(self._show_error, result)

                    # Update document if code was fixed
                    if result.final_code != code:
                        self._set_document_content_safe(result.final_code)
                        fix_summary = self.autofix.get_fix_summary(result)
                        GLib.idle_add(
                            self._add_chat_message,
                            "frank",
                            f"Code wurde automatisch korrigiert. {fix_summary}"
                        )
                else:
                    result = loop.run_until_complete(
                        self.sandbox.execute(code, language)
                    )

                    if self._cancel_requested:
                        GLib.idle_add(self._on_run_cancelled)
                        return

                    # Schedule UI updates on main thread
                    if result.success:
                        GLib.idle_add(self._show_execution_result, result)
                    else:
                        GLib.idle_add(self._show_execution_error, result)

            finally:
                loop.close()

        except Exception as e:
            GLib.idle_add(self._on_run_error, str(e))
        finally:
            GLib.idle_add(self._on_run_complete)

    def _on_run_error(self, error_msg: str):
        """Handle run error - called on main thread"""
        if not self._is_valid():
            return False
        self._append_console(f"Execution error: {error_msg}")
        self._set_status("Error", "dialog-error-symbolic")
        return False

    def _on_run_cancelled(self):
        """Handle run cancellation - called on main thread"""
        if not self._is_valid():
            return False
        self._set_status("Cancelled", "process-stop-symbolic")
        self._on_run_complete()
        return False

    def _on_run_complete(self):
        """Called when run completes - must be called on main thread"""
        if not self._is_valid():
            return False
        with self._run_lock:
            self.is_running = False
            self._cancel_requested = False
            self._current_process = None
        self._update_running_state(False)
        return False

    def stop_code(self):
        """Stop code execution with proper process cancellation"""
        with self._run_lock:
            self._cancel_requested = True

            # Cancel sandbox process if running
            if self._current_process is not None:
                try:
                    self._current_process.terminate()
                except Exception:
                    pass  # Process may already be dead

            # Also tell sandbox to cancel
            if hasattr(self.sandbox, 'cancel'):
                try:
                    self.sandbox.cancel()
                except Exception:
                    pass

        self._update_running_state(False)
        self._set_status("Stopped", "process-stop-symbolic")

    def _update_running_state(self, running: bool):
        """Update UI for running state"""
        if not self._is_valid():
            return

        self.run_btn.set_sensitive(not running)
        self.stop_btn.set_sensitive(running)

        if running:
            self.run_icon.set_from_icon_name("process-working-symbolic")
            self.run_label.set_label("Running...")
            self._set_status("Executing code...", "process-working-symbolic")
        else:
            self.run_icon.set_from_icon_name("media-playback-start-symbolic")
            self.run_label.set_label("Run")

    def _clear_output(self):
        """Clear all output"""
        if not self._is_valid():
            return
        self.visual_output.set_paintable(None)
        self.console_output.get_buffer().set_text("")

    def _show_result(self, result: AutoFixResult):
        """Show auto-fix result"""
        if not self._is_valid():
            return False

        if result.visual_output:
            self._show_visual(result.visual_output)
            self.output_stack.set_visible_child_name("visual")
        else:
            self.output_stack.set_visible_child_name("console")

        num_fixes = len(result.attempts) if result.attempts else 0
        self._set_status(
            f"Success ({num_fixes} fix{'es' if num_fixes != 1 else ''})",
            "emblem-ok-symbolic"
        )
        return False

    def _show_error(self, result: AutoFixResult):
        """Show auto-fix error"""
        if not self._is_valid():
            return False

        num_attempts = len(result.attempts) if result.attempts else 0
        error_text = str(result.error)[:500] if result.error else "Unknown error"
        self._append_console(f"Error after {num_attempts} attempts:\n{error_text}")
        self.output_stack.set_visible_child_name("console")
        self._set_status("Failed", "dialog-error-symbolic")
        return False

    def _show_execution_result(self, result):
        """Show direct execution result"""
        if not self._is_valid():
            return False

        if result.visual_output:
            self._show_visual(result.visual_output)
            self.output_stack.set_visible_child_name("visual")
        elif result.stdout:
            self._append_console(result.stdout)
            self.output_stack.set_visible_child_name("console")

        exec_time = getattr(result, 'execution_time_ms', 0) or 0
        self._set_status(f"Done ({exec_time:.0f}ms)", "emblem-ok-symbolic")
        self.time_label.set_label(f"{exec_time:.0f}ms")
        return False

    def _show_execution_error(self, result):
        """Show direct execution error"""
        if not self._is_valid():
            return False

        error_text = str(result.stderr)[:1000] if result.stderr else "Unknown error"
        self._append_console(f"Error:\n{error_text}")
        self.output_stack.set_visible_child_name("console")
        self._set_status("Error", "dialog-error-symbolic")
        return False

    def _show_visual(self, image_data: bytes):
        """Show visual output with proper resource cleanup"""
        if not self._is_valid():
            return False

        loader = None
        try:
            loader = GdkPixbuf.PixbufLoader()
            loader.write(image_data)
            loader.close()
            loader_closed = True
            pixbuf = loader.get_pixbuf()

            if pixbuf:
                # Scale image if too large to prevent memory issues
                max_dimension = 2048
                width = pixbuf.get_width()
                height = pixbuf.get_height()

                if width > max_dimension or height > max_dimension:
                    scale = min(max_dimension / width, max_dimension / height)
                    new_width = int(width * scale)
                    new_height = int(height * scale)
                    pixbuf = pixbuf.scale_simple(
                        new_width, new_height,
                        GdkPixbuf.InterpType.BILINEAR
                    )

                texture = Gdk.Texture.new_for_pixbuf(pixbuf)
                self.visual_output.set_paintable(texture)
        except Exception as e:
            self._append_console(f"Error loading image: {e}")
        finally:
            # Ensure loader is always closed to prevent memory leak
            if loader is not None:
                try:
                    loader.close()
                except Exception:
                    pass  # May already be closed or in error state
        return False

    def _append_console(self, text: str):
        """Append text to console with auto-scroll"""
        if not self._is_valid():
            return

        buffer = self.console_output.get_buffer()
        end_iter = buffer.get_end_iter()
        buffer.insert(end_iter, text + "\n")

        # Auto-scroll to end
        end_iter = buffer.get_end_iter()
        self.console_output.scroll_to_iter(end_iter, 0.0, False, 0.0, 1.0)

    def _set_status(self, text: str, icon: str):
        """Set status bar"""
        if not self._is_valid():
            return
        self.status_label.set_label(text)
        self.status_icon.set_from_icon_name(icon)

    def _on_autofix_progress(self, event: str, data: dict):
        """Handle auto-fix progress"""
        GLib.idle_add(self._update_autofix_status, event, data)

    def _update_autofix_status(self, event: str, data: dict):
        """Update status for auto-fix"""
        if not self._is_valid():
            return False

        try:
            if event == 'attempt_start':
                attempt = data.get('attempt', '?')
                max_attempts = data.get('max_attempts', '?')
                self._set_status(
                    f"Attempt {attempt}/{max_attempts}...",
                    "process-working-symbolic"
                )
            elif event == 'fix_applied':
                attempt = data.get('attempt', '?')
                fix_desc = str(data.get('fix', ''))[:200]
                self._append_console(f"Fix #{attempt}: {fix_desc}")
                self._add_chat_message("frank", f"Fix applied: {fix_desc}")
            elif event == 'success':
                self._set_status("Success", "emblem-ok-symbolic")
            elif event == 'cannot_fix':
                error_text = str(data.get('error', 'Unknown error'))[:200]
                self._add_chat_message(
                    "frank",
                    f"Cannot automatically fix this error:\n{error_text}"
                )
        except Exception:
            pass  # Don't crash on status update errors

        return False

    def _add_chat_message(self, role: str, content: str):
        """Add message to chat with error handling and content truncation"""
        if not self._is_valid():
            return False

        try:
            # Validate and truncate content if needed
            if content is None:
                content = ""
            content = str(content)

            if len(content) > MAX_CHAT_CONTENT_LENGTH:
                content = content[:MAX_CHAT_CONTENT_LENGTH] + "... (truncated)"

            msg_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)

            role_label = Gtk.Label(label="You:" if role == 'user' else "Frank:")
            role_label.add_css_class("dim-label")
            role_label.set_halign(Gtk.Align.START)
            msg_box.append(role_label)

            content_label = Gtk.Label(label=content)
            content_label.set_wrap(True)
            content_label.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
            content_label.set_halign(Gtk.Align.START)
            content_label.set_selectable(True)
            content_label.set_max_width_chars(30)
            msg_box.append(content_label)

            self.chat_messages.append(msg_box)

            # Auto-scroll chat to bottom
            def scroll_to_bottom():
                if not self._is_valid():
                    return False
                adj = self.chat_scroll.get_vadjustment()
                adj.set_value(adj.get_upper())
                return False
            GLib.idle_add(scroll_to_bottom)

        except Exception as e:
            # Log error but don't crash
            print(f"Error adding chat message: {e}")

        return False

    def _on_chat_send(self, widget):
        """Handle chat send"""
        text = self.chat_entry.get_text().strip()
        if not text:
            return

        self.chat_entry.set_text("")
        self._add_chat_message("user", text)

        # Process command
        GLib.idle_add(self._process_chat_command, text)

    def _process_chat_command(self, text: str):
        """Process chat command - runs FrankBridge in background thread"""
        if not self._is_valid():
            return False

        # Get current code safely
        code = self._get_document_content_safe()
        language = self.document.language or 'python'

        # Run FrankBridge call in background thread to avoid blocking GTK
        def do_frank_call():
            try:
                # Truncate code if too long
                truncated_code = code
                if len(code) > MAX_CODE_BLOCK_LENGTH:
                    truncated_code = code[:MAX_CODE_BLOCK_LENGTH] + "\n# ... (truncated)"

                response = self.frank_bridge.chat(
                    f"Modify the following {language} code based on this instruction: '{text}'\n\n"
                    f"Current code:\n```{language}\n{truncated_code}\n```\n\n"
                    f"Return only the modified code, no explanation:",
                    context={'mode': 'code_modification'}
                )

                # Schedule UI update on main thread
                GLib.idle_add(self._handle_frank_response, code, response, language)

            except Exception as e:
                GLib.idle_add(
                    self._add_chat_message,
                    "frank",
                    f"Error processing request: {str(e)[:200]}"
                )

        thread = threading.Thread(target=do_frank_call, daemon=True)
        thread.start()

        return False

    def _handle_frank_response(self, original_code: str, response, language: str):
        """Handle Frank's response on main thread"""
        if not self._is_valid():
            return False

        # Extract text content from AIResponse object or plain string
        from writer.ai.bridge import AIResponse
        if isinstance(response, AIResponse):
            if not response.success:
                self._add_chat_message("frank", response.error or "Fehler bei der Verarbeitung.")
                return False
            response_text = response.content
        else:
            response_text = str(response) if response else ""

        # Extract code from response
        new_code = self._extract_code(response_text, language)

        if new_code and new_code != original_code:
            # Update document safely
            self._set_document_content_safe(new_code)

            self._add_chat_message("frank", "Code updated. Re-running...")

            # Re-run
            self.run_code()
        else:
            self._add_chat_message("frank", response_text)

        return False

    def _extract_code(self, response: str, language: str) -> Optional[str]:
        """Extract code from AI response with improved reliability"""
        if not response or not isinstance(response, str):
            return None

        # Check for code block markers
        if "```" not in response:
            return None

        try:
            parts = response.split("```")

            # Need at least opening and closing markers (3 parts minimum)
            if len(parts) < 2:
                return None

            code_part = parts[1]

            # Bounds check - ensure we have content
            if not code_part or len(code_part.strip()) == 0:
                return None

            # Remove language identifier from first line
            lines = code_part.split('\n')
            if len(lines) > 0:
                first_line = lines[0].strip().lower()
                # Extended list of language identifiers
                known_languages = [
                    language.lower(), 'python', 'python3', 'py',
                    'javascript', 'js', 'typescript', 'ts',
                    'bash', 'sh', 'shell', 'zsh',
                    'html', 'css', 'json', 'xml', 'yaml', 'yml',
                    'c', 'cpp', 'c++', 'java', 'go', 'rust', 'ruby', 'rb',
                    'sql', 'r', 'php', 'swift', 'kotlin', 'scala'
                ]
                if first_line in known_languages:
                    code_part = '\n'.join(lines[1:])

            extracted = code_part.strip()

            # Validate extracted text is not empty
            if not extracted:
                return None

            # Sanity check - extracted code shouldn't be too short
            # (likely extraction error) or contain only whitespace
            if len(extracted) < 3:
                return None

            return extracted

        except Exception:
            # Any parsing error - return None
            return None

    def _on_close_request(self, window):
        """Handle close request with proper cleanup"""
        # Mark as destroyed to prevent further operations
        self._is_destroyed = True

        # Stop any running code
        if self.is_running:
            self.stop_code()

        # Cleanup sandbox
        try:
            self.sandbox.cleanup()
        except Exception:
            pass  # Don't fail on cleanup errors

        # Save paned position for next time
        if hasattr(self.config, 'set'):
            try:
                self.config.set(SETTINGS_KEY_PANED_POSITION, self.paned.get_position())
            except Exception:
                pass

        return False

    def _on_paned_position_changed(self, paned, param):
        """Handle paned position change - save for persistence"""
        # Defer saving to avoid excessive writes during resize
        pass  # Position saved on close
