"""MessageMixin -- message display, images, typing/listening indicators, search results, file actions.

Extracted from chat_overlay_monolith.py lines ~4880-5241.
Plain mixin class; all `self.*` references resolve at runtime via MRO.
"""

import time
import tkinter as tk
from pathlib import Path
from typing import List
from overlay.constants import COLORS, LOG, SearchResult
from overlay.widgets.message_bubble import MessageBubble
from overlay.widgets.image_bubble import ImageBubble
from overlay.widgets.image_viewer import ImageViewer
from overlay.widgets.search_result_card import SearchResultCard
from overlay.widgets.file_action_bar import FileActionBar
from overlay.services.search import _open_url
from overlay.helpers.context_suggestions import get_context_suggestions


class MessageMixin:

    # ---------- Messages ----------

    def _add_message(self, sender: str, message: str, is_user: bool = False, is_system: bool = False, persist: bool = True):
        LOG.debug(f"Adding message: {sender}: {message[:50]}...")

        # Add to LLM context ring buffer (skip system messages — they're not conversation)
        if not is_system and message.strip():
            role = "user" if is_user else "frank"
            hist_msg = message[:500] + "..." if len(message) > 500 else message
            self._chat_history.append({
                "role": role,
                "sender": sender,
                "text": hist_msg,
                "is_user": is_user,
                "ts": time.time(),
            })
            if len(self._chat_history) > self._chat_history_max:
                self._chat_history = self._chat_history[-self._chat_history_max:]
            if persist:
                self._save_chat_history()

        # Store ALL messages (including system) in SQLite for UI persistence
        if persist and message.strip() and hasattr(self, '_chat_memory_db'):
            try:
                role = "user" if is_user else ("system" if is_system else "frank")
                self._chat_memory_db.store_message(
                    session_id=self._memory_session_id,
                    role=role, sender=sender,
                    text=message,
                    is_user=is_user, is_system=is_system,
                )
            except Exception as e:
                LOG.warning(f"Chat memory store error: {e}")

        # Build retry/speak callbacks for Frank messages
        _on_retry = None
        _on_speak = None
        _on_do_this = None
        if not is_user and not is_system:
            # Retry: re-send the last user message
            _last_user = None
            for h in reversed(self._chat_history):
                if h.get("role") == "user":
                    _last_user = h.get("text", "")
                    break
            if _last_user:
                _retry_msg = _last_user
                _on_retry = lambda m=_retry_msg: self._retry_last_message(m)
            # Speak: TTS the message (no chat duplication)
            if hasattr(self, '_tts_speak'):
                _speak_msg = message
                _on_speak = lambda m=_speak_msg: self._tts_speak(m)
            # Do This: detect agentic action proposal in parenthetical
            try:
                from services.action_intent_detector import detect_parenthetical_action
                _intent = detect_parenthetical_action(message)
                if _intent and hasattr(self, '_start_agentic_execution'):
                    _goal = _intent["goal"]
                    _on_do_this = lambda g=_goal: self._start_agentic_execution(g)
                    LOG.debug(f"Action intent detected: {_goal[:80]}")
            except Exception:
                pass
        bubble = MessageBubble(
            self.messages_frame,
            sender=sender,
            message=message,
            is_user=is_user,
            is_system=is_system,
            on_link_click=lambda url: self._io_q.put(("open", url)),
            on_retry=_on_retry,
            on_speak=_on_speak,
            on_do_this=_on_do_this,
        )
        bubble.pack(fill="x", anchor="w" if not is_user else "e")

        # Force UI refresh and scroll to bottom (only if user is near bottom)
        self.messages_frame.update_idletasks()
        self.chat_canvas.configure(scrollregion=self.chat_canvas.bbox("all"))
        self._smart_scroll()
        # Force window to process pending events
        self.update_idletasks()
        self.update()

    def _add_image(self, image_source, caption: str = "", is_user: bool = False):
        """Add an image bubble to the chat.

        Args:
            image_source: Path string or PIL Image object
            caption: Optional caption text below the image
            is_user: True if this is a user-sent image (right-aligned)

        The image is displayed as a thumbnail (max 200px wide initially).
        Clicking opens a fullscreen viewer next to the overlay.
        """
        LOG.debug(f"Adding image: {image_source} (caption: {caption[:30] if caption else 'none'}...)")

        def open_viewer(image_path: str):
            """Open image viewer popup."""
            try:
                # Get current overlay geometry for positioning
                overlay_geo = self.geometry()
                ImageViewer(self, image_path, overlay_geometry=overlay_geo)
            except Exception as e:
                LOG.error(f"Failed to open image viewer: {e}")
                self._add_message("Frank", f"Could not open image: {e}", is_system=True)

        try:
            bubble = ImageBubble(
                self.messages_frame,
                image_source=image_source,
                caption=caption,
                on_click=open_viewer,
                is_user=is_user
            )
            bubble.pack(fill="x", anchor="w" if not is_user else "e")

            # Force UI refresh and scroll to bottom (only if user is near bottom)
            self.messages_frame.update_idletasks()
            self.chat_canvas.configure(scrollregion=self.chat_canvas.bbox("all"))
            self._smart_scroll()
            self.update_idletasks()
            self.update()

        except Exception as e:
            LOG.error(f"Failed to add image bubble: {e}")
            # Fallback to text message
            path_str = str(image_source) if isinstance(image_source, str) else "[PIL Image]"
            self._add_message("Frank", f"[Image: {path_str}]", is_system=True)

    def _retry_last_message(self, msg: str):
        """Re-send a user message through the chat pipeline."""
        try:
            from overlay.constants import DEFAULT_MAX_TOKENS, DEFAULT_TIMEOUT_S
            self._add_message("Du", msg, is_user=True)
            self._chat_q.put(("chat", {
                "msg": msg, "max_tokens": DEFAULT_MAX_TOKENS,
                "timeout_s": DEFAULT_TIMEOUT_S, "task": "chat.fast", "force": None
            }))
        except Exception as e:
            LOG.error(f"Retry failed: {e}")

    # ---------- Context Suggestions ----------

    def _show_context_suggestions(self, frank_response: str):
        """Show context-aware suggestion chips after Frank responds."""
        try:
            # Get last user message for context
            user_query = ""
            for h in reversed(self._chat_history):
                if h.get("role") == "user":
                    user_query = h.get("text", "")
                    break

            combined = f"{user_query} {frank_response}"
            suggestions = get_context_suggestions(combined)
            if not suggestions:
                return

            # Remove old suggestion chips
            self._dismiss_suggestions()

            # Create chip frame
            self._suggestion_frame = tk.Frame(self.messages_frame, bg=COLORS["bg_chat"])
            self._suggestion_frame.pack(fill="x", padx=20, pady=(0, 4))

            hint = tk.Label(
                self._suggestion_frame, text="Quick:",
                bg=COLORS["bg_chat"], fg=COLORS["text_muted"],
                font=("Consolas", 8)
            )
            hint.pack(side="left", padx=(0, 4))

            for label, cmd in suggestions:
                chip = tk.Label(
                    self._suggestion_frame,
                    text=f" {label} ",
                    bg=COLORS["bg_elevated"],
                    fg=COLORS["accent_secondary"],
                    font=("Consolas", 9),
                    cursor="hand2",
                    padx=8, pady=2,
                )
                chip.pack(side="left", padx=(0, 6))
                chip.bind("<Button-1>", lambda e, c=cmd: self._execute_suggestion(c))
                chip.bind("<Enter>", lambda e, w=chip: w.configure(
                    bg=COLORS["bg_highlight"], fg=COLORS["neon_cyan"]))
                chip.bind("<Leave>", lambda e, w=chip: w.configure(
                    bg=COLORS["bg_elevated"], fg=COLORS["accent_secondary"]))

            # Auto-dismiss after 15 seconds
            self.after(15000, self._dismiss_suggestions)

            # Scroll to show chips
            self.messages_frame.update_idletasks()
            self.chat_canvas.configure(scrollregion=self.chat_canvas.bbox("all"))
            self._smart_scroll()

        except Exception as e:
            LOG.debug(f"Context suggestions error: {e}")

    def _execute_suggestion(self, command: str):
        """Execute a suggestion chip command."""
        self._dismiss_suggestions()
        if command == "/file":
            if hasattr(self, '_on_attach'):
                self._on_attach()
        else:
            self._route_message(command)

    def _dismiss_suggestions(self):
        """Remove suggestion chips."""
        if hasattr(self, '_suggestion_frame') and self._suggestion_frame:
            try:
                self._suggestion_frame.destroy()
            except Exception:
                pass
            self._suggestion_frame = None

    # ---------- Typing Indicator ----------

    def _show_typing(self):
        """Show animated typing indicator with elapsed time."""
        if self._is_typing:
            return
        self._is_typing = True
        self._typing_dots = 0
        self._typing_start_time = time.time()

        # Create typing bubble
        self._typing_bubble = tk.Frame(self.messages_frame, bg=COLORS["bg_chat"])
        self._typing_bubble.pack(fill="x", padx=10, pady=6)

        container = tk.Frame(self._typing_bubble, bg=COLORS["bg_chat"])
        container.pack(anchor="w")

        # Shadow + bubble (same style as Frank messages)
        shadow = tk.Frame(container, bg=COLORS["shadow"])
        shadow.pack(padx=(2, 0), pady=(2, 0))

        bubble_outer = tk.Frame(shadow, bg=COLORS["border_light"], padx=1, pady=1)
        bubble_outer.pack(padx=(0, 2), pady=(0, 2))

        bubble = tk.Frame(bubble_outer, bg=COLORS["bg_ai_msg"], padx=14, pady=10)
        bubble.pack()

        # Top row: sender + cancel button
        top_row = tk.Frame(bubble, bg=COLORS["bg_ai_msg"])
        top_row.pack(fill="x", pady=(0, 6))

        tk.Label(
            top_row, text="\u25cf Frank", bg=COLORS["bg_ai_msg"],
            fg=COLORS["accent"], font=("Segoe UI", 9, "bold")
        ).pack(side="left")

        # Cancel (X) button — top right
        cancel_btn = tk.Label(
            top_row, text="\u2715", bg=COLORS["bg_ai_msg"],
            fg=COLORS["text_muted"], font=("Segoe UI", 10), cursor="hand2",
        )
        cancel_btn.pack(side="right", padx=(8, 0))
        cancel_btn.bind("<Button-1>", lambda e: self._cancel_thinking())

        # Animated dots container
        self._dots_frame = tk.Frame(bubble, bg=COLORS["bg_ai_msg"])
        self._dots_frame.pack(anchor="w")

        self._dot_labels = []
        for i in range(3):
            dot = tk.Label(
                self._dots_frame, text="\u25cf", bg=COLORS["bg_ai_msg"],
                fg=COLORS["text_muted"], font=("Segoe UI", 12)
            )
            dot.pack(side="left", padx=2)
            self._dot_labels.append(dot)

        # Elapsed time label (initially hidden, shown after 5s)
        self._typing_elapsed_label = tk.Label(
            bubble, text="", bg=COLORS["bg_ai_msg"],
            fg=COLORS["text_muted"], font=("Consolas", 8)
        )
        self._typing_elapsed_label.pack(anchor="w", pady=(4, 0))

        # Start animation
        self._animate_typing_dots()

        # Scroll to show typing indicator
        self.messages_frame.update_idletasks()
        self.chat_canvas.configure(scrollregion=self.chat_canvas.bbox("all"))
        self._smart_scroll()

    def _animate_typing_dots(self):
        """Animate the typing indicator dots with elapsed time feedback."""
        if not self._is_typing or not hasattr(self, '_dot_labels'):
            return

        # Cycle through dots
        for i, dot in enumerate(self._dot_labels):
            if i == self._typing_dots % 3:
                dot.configure(fg=COLORS["accent"])
            else:
                dot.configure(fg=COLORS["text_muted"])

        self._typing_dots += 1

        # Update elapsed time label
        if hasattr(self, '_typing_elapsed_label') and hasattr(self, '_typing_start_time'):
            elapsed = int(time.time() - self._typing_start_time)
            if elapsed >= 60:
                mins = elapsed // 60
                secs = elapsed % 60
                self._typing_elapsed_label.configure(
                    text=f"Still active... {mins}m {secs:02d}s",
                    fg=COLORS.get("warning", "#FFD700"))
            elif elapsed >= 15:
                self._typing_elapsed_label.configure(
                    text=f"Thinking... {elapsed}s",
                    fg=COLORS["text_muted"])
            elif elapsed >= 5:
                self._typing_elapsed_label.configure(text=f"{elapsed}s")

        self.after(300, self._animate_typing_dots)

    def _cancel_thinking(self):
        """Cancel current thinking/processing — interrupt Frank."""
        LOG.info("User cancelled thinking")
        self._hide_typing()
        # Set cancel flag so workers can check
        self._thinking_cancelled = True
        self._add_message("Frank", "Cancelled.", is_system=True)

    def _hide_typing(self):
        """Hide typing indicator."""
        self._is_typing = False
        if hasattr(self, '_typing_bubble') and self._typing_bubble:
            try:
                self._typing_bubble.destroy()
            except tk.TclError:
                pass  # Widget already destroyed
            self._typing_bubble = None
        self._dot_labels = []
        # Also hide listening indicator
        if hasattr(self, '_listening_bubble') and self._listening_bubble:
            try:
                self._listening_bubble.destroy()
            except tk.TclError:
                pass  # Widget already destroyed
            self._listening_bubble = None

    # ---------- Listening Indicator ----------

    def _show_listening_indicator(self):
        """Show listening indicator (microphone icon)."""
        # Hide any existing indicators first
        self._hide_typing()

        # Create listening bubble
        self._listening_bubble = tk.Frame(self.messages_frame, bg=COLORS["bg_chat"])
        self._listening_bubble.pack(fill="x", padx=10, pady=6)

        container = tk.Frame(self._listening_bubble, bg=COLORS["bg_chat"])
        container.pack(anchor="w")

        # Shadow + bubble
        shadow = tk.Frame(container, bg=COLORS["shadow"])
        shadow.pack(padx=(2, 0), pady=(2, 0))

        bubble_outer = tk.Frame(shadow, bg=COLORS["accent"], padx=1, pady=1)
        bubble_outer.pack(padx=(0, 2), pady=(0, 2))

        bubble = tk.Frame(bubble_outer, bg=COLORS["bg_ai_msg"], padx=14, pady=10)
        bubble.pack()

        # Microphone icon + "Listening..."
        tk.Label(
            bubble, text="\U0001f3a4 Listening...", bg=COLORS["bg_ai_msg"],
            fg=COLORS["accent"], font=("Segoe UI", 10, "bold")
        ).pack(anchor="w")

        # Scroll to show indicator
        self.messages_frame.update_idletasks()
        self.chat_canvas.configure(scrollregion=self.chat_canvas.bbox("all"))
        self._smart_scroll()

    # ---------- Smart Scroll ----------

    def _smart_scroll(self):
        """Scroll to bottom ONLY if user is already near the bottom (threshold 0.95).
        Prevents stealing scroll position when user is reading history."""
        try:
            yview = self.chat_canvas.yview()
            if yview[1] >= 0.95:
                self.chat_canvas.yview_moveto(1.0)
        except Exception:
            # Fallback: always scroll on error
            self.chat_canvas.yview_moveto(1.0)

    # ---------- Streaming Message ----------

    def _start_streaming_message(self):
        """Create a live-updating message bubble for streaming LLM responses."""
        self._stream_user_scrolled = False  # Track if user manually scrolled
        # Container frame (same layout as MessageBubble)
        self._stream_frame = tk.Frame(self.messages_frame, bg=COLORS["bg_chat"])
        self._stream_frame.pack(fill="x", padx=8, pady=4)

        container = tk.Frame(self._stream_frame, bg=COLORS["bg_chat"])
        container.pack(fill="x")

        bubble = tk.Frame(container, bg=COLORS["bg_ai_msg"], padx=0, pady=0)
        bubble.pack(anchor="w", side="left", fill="x", expand=True)

        # Left border stripe (cyan for Frank)
        border_stripe = tk.Frame(bubble, bg=COLORS["neon_cyan"], width=3)
        border_stripe.pack(side="left", fill="y")

        content = tk.Frame(bubble, bg=COLORS["bg_ai_msg"], padx=12, pady=8)
        content.pack(side="left", fill="both", expand=True)

        # Sender label
        tk.Label(
            content, text="\u25c0 FRANK", bg=COLORS["bg_ai_msg"],
            fg=COLORS["neon_cyan"], font=("Consolas", 9, "bold"), anchor="w"
        ).pack(anchor="w", pady=(0, 4))

        # Live text widget (normal state so we can insert tokens)
        self._stream_text = tk.Text(
            content, bg=COLORS["bg_ai_msg"], fg=COLORS["text_ai"],
            font=("Consolas", 10), wrap="word", relief="flat",
            padx=0, pady=0, height=1, borderwidth=0, highlightthickness=0,
            selectbackground=COLORS.get("neon_cyan", "#00FFFF"),
            selectforeground=COLORS["bg_main"],
        )
        self._stream_text.pack(anchor="w", fill="both", expand=True)
        self._stream_text.tag_configure("normal", foreground=COLORS["text_ai"])
        self._stream_accumulated = ""

        # Scroll to show streaming bubble
        self.messages_frame.update_idletasks()
        self.chat_canvas.configure(scrollregion=self.chat_canvas.bbox("all"))
        self.chat_canvas.yview_moveto(1.0)

    def _append_streaming_token(self, token: str):
        """Append a token to the streaming bubble. Must be called on main thread."""
        if not hasattr(self, '_stream_text') or self._stream_text is None:
            return
        try:
            self._stream_text.insert("end", token, "normal")
            self._stream_accumulated += token
            # Recalculate height periodically (every ~20 chars to avoid flicker)
            if len(self._stream_accumulated) % 20 < len(token):
                try:
                    dl = self._stream_text.count("1.0", "end", "displaylines")
                    if dl:
                        h = dl[0] if isinstance(dl, tuple) else dl
                        self._stream_text.configure(height=max(1, h))
                except (tk.TclError, Exception):
                    pass
                # Update scroll region
                self.messages_frame.update_idletasks()
                self.chat_canvas.configure(scrollregion=self.chat_canvas.bbox("all"))
                # Only auto-scroll if user hasn't manually scrolled away
                if not getattr(self, '_stream_user_scrolled', False):
                    self.chat_canvas.yview_moveto(1.0)
        except tk.TclError:
            pass  # Widget destroyed

    def _finalize_streaming_message(self, full_text: str):
        """Finalize streaming: destroy live bubble, create proper MessageBubble."""
        # Capture scroll intent before destroying stream frame
        _was_user_scrolled = getattr(self, '_stream_user_scrolled', False)

        # Remove the streaming frame
        if hasattr(self, '_stream_frame') and self._stream_frame:
            try:
                self._stream_frame.destroy()
            except tk.TclError:
                pass
            self._stream_frame = None
            self._stream_text = None
            self._stream_accumulated = ""

        # Reset stream scroll flag
        self._stream_user_scrolled = False

        # Create a proper MessageBubble with the full text (supports selection, links, etc.)
        if full_text.strip():
            # Build retry/speak/do-this callbacks
            _on_retry = None
            _on_speak = None
            _on_do_this = None
            _last_user = None
            for h in reversed(self._chat_history):
                if h.get("role") == "user":
                    _last_user = h.get("text", "")
                    break
            if _last_user:
                _retry_msg = _last_user
                _on_retry = lambda m=_retry_msg: self._retry_last_message(m)
            if hasattr(self, '_tts_speak'):
                _speak_text = full_text
                _on_speak = lambda m=_speak_text: self._tts_speak(m)
            # Detect agentic action proposal in parenthetical
            try:
                from services.action_intent_detector import detect_parenthetical_action
                _intent = detect_parenthetical_action(full_text)
                if _intent and hasattr(self, '_start_agentic_execution'):
                    _goal = _intent["goal"]
                    _on_do_this = lambda g=_goal: self._start_agentic_execution(g)
            except Exception:
                pass

            bubble = MessageBubble(
                self.messages_frame, sender="Frank", message=full_text,
                is_user=False, is_system=False,
                on_link_click=lambda url: self._io_q.put(("open", url)),
                on_retry=_on_retry,
                on_speak=_on_speak,
                on_do_this=_on_do_this,
            )
            bubble.pack(fill="x", anchor="w")

            # Show context-aware suggestion chips
            self._show_context_suggestions(full_text)

            self.messages_frame.update_idletasks()
            self.chat_canvas.configure(scrollregion=self.chat_canvas.bbox("all"))
            # Only scroll to bottom if user didn't manually scroll away
            if not _was_user_scrolled:
                self.chat_canvas.yview_moveto(1.0)
            self.update_idletasks()

    # ---------- Search Results ----------

    def _render_results(self, results: List[SearchResult]):
        self._clear_results()
        if not results:
            return

        self.results_container.pack(fill="x", padx=15, pady=(0, 5))

        # Header with close button
        header_frame = tk.Frame(self.results_container, bg=COLORS["bg_main"])
        header_frame.pack(fill="x", pady=(0, 5))

        header = tk.Label(
            header_frame,
            text=f"Search results ({len(results)}):",
            bg=COLORS["bg_main"],
            fg=COLORS["text_secondary"],
            font=("Segoe UI", 9)
        )
        header.pack(side="left")

        close_btn = tk.Label(
            header_frame,
            text="\u2715 Close",
            bg=COLORS["bg_main"],
            fg=COLORS["accent"],
            font=("Segoe UI", 9),
            cursor="hand2"
        )
        close_btn.pack(side="right")
        close_btn.bind("<Button-1>", lambda e: self._clear_results())

        # Scrollable frame for results
        canvas = tk.Canvas(self.results_container, bg=COLORS["bg_main"], highlightthickness=0, height=220)
        scrollbar = tk.Scrollbar(self.results_container, orient="vertical", command=canvas.yview)
        scrollable_frame = tk.Frame(canvas, bg=COLORS["bg_main"])

        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw", width=390)
        canvas.configure(yscrollcommand=scrollbar.set)

        # Mouse wheel scrolling — bind to canvas AND all children recursively.
        # "break" stops event propagation so the main chat canvas does NOT scroll.
        def _scroll_up(e):
            canvas.yview_scroll(-1, "units")
            return "break"

        def _scroll_down(e):
            canvas.yview_scroll(1, "units")
            return "break"

        def _on_mousewheel(event):
            try:
                canvas.yview_scroll(int(-1*(event.delta/120)), "units")
            except Exception:
                pass
            return "break"

        def _bind_scroll_recursive(widget):
            widget.bind("<MouseWheel>", _on_mousewheel)
            widget.bind("<Button-4>", _scroll_up)
            widget.bind("<Button-5>", _scroll_down)
            for child in widget.winfo_children():
                _bind_scroll_recursive(child)

        canvas.bind("<MouseWheel>", _on_mousewheel)
        canvas.bind("<Button-4>", _scroll_up)
        canvas.bind("<Button-5>", _scroll_down)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        for idx, result in enumerate(results, start=1):
            card = SearchResultCard(
                scrollable_frame,
                index=idx,
                result=result,
                on_click=lambda url: self._io_q.put(("open", url))
            )
            card.pack(fill="x", pady=2)

        # Bind scroll to all child widgets AFTER cards are created
        _bind_scroll_recursive(scrollable_frame)

        hint = tk.Label(
            self.results_container,
            text="Scroll for more | Click to open | 'open 1' | 'dismiss'",
            bg=COLORS["bg_main"],
            fg=COLORS["text_system"],
            font=("Segoe UI", 8)
        )
        hint.pack(anchor="w", pady=(5, 0))

    def _render_darknet_results(self, results: List[SearchResult]):
        """Render darknet search results with Matrix-style green-on-black theme."""
        from overlay.widgets.search_result_card import SearchResultCard
        self._clear_results()
        if not results:
            return

        self.results_container.pack(fill="x", padx=15, pady=(0, 5))

        # Header with Matrix-green styling
        header_frame = tk.Frame(self.results_container, bg=COLORS["darknet_bg"])
        header_frame.pack(fill="x", pady=(0, 5))

        header = tk.Label(
            header_frame,
            text=f"\u26a0 Darknet ({len(results)} results):",
            bg=COLORS["darknet_bg"],
            fg=COLORS["darknet_header"],
            font=("Consolas", 9, "bold")
        )
        header.pack(side="left")

        close_btn = tk.Label(
            header_frame,
            text="\u2715 Close",
            bg=COLORS["darknet_bg"],
            fg=COLORS["darknet_title"],
            font=("Consolas", 9),
            cursor="hand2"
        )
        close_btn.pack(side="right")
        close_btn.bind("<Button-1>", lambda e: self._clear_results())

        # Scrollable result list
        canvas = tk.Canvas(self.results_container, bg=COLORS["darknet_bg"], highlightthickness=0, height=220)
        scrollbar = tk.Scrollbar(self.results_container, orient="vertical", command=canvas.yview)
        scrollable_frame = tk.Frame(canvas, bg=COLORS["darknet_bg"])

        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw", width=390)
        canvas.configure(yscrollcommand=scrollbar.set)

        # Mouse wheel scrolling — bind to canvas AND all children recursively.
        # "break" stops event propagation so the main chat canvas does NOT scroll.
        def _scroll_up_dn(e):
            canvas.yview_scroll(-1, "units")
            return "break"

        def _scroll_down_dn(e):
            canvas.yview_scroll(1, "units")
            return "break"

        def _on_mousewheel_dn(event):
            try:
                canvas.yview_scroll(int(-1*(event.delta/120)), "units")
            except Exception:
                pass
            return "break"

        def _bind_scroll_recursive_dn(widget):
            widget.bind("<MouseWheel>", _on_mousewheel_dn)
            widget.bind("<Button-4>", _scroll_up_dn)
            widget.bind("<Button-5>", _scroll_down_dn)
            for child in widget.winfo_children():
                _bind_scroll_recursive_dn(child)

        canvas.bind("<MouseWheel>", _on_mousewheel_dn)
        canvas.bind("<Button-4>", _scroll_up_dn)
        canvas.bind("<Button-5>", _scroll_down_dn)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        for idx, result in enumerate(results, start=1):
            card = SearchResultCard(
                scrollable_frame,
                index=idx,
                result=result,
                on_click=lambda url: self._io_q.put(("darknet_open", url)),
                darknet=True,
            )
            card.pack(fill="x", pady=2)

        # Bind scroll to all child widgets AFTER cards are created
        _bind_scroll_recursive_dn(scrollable_frame)

        hint = tk.Label(
            self.results_container,
            text="\u26a0 .onion links | Opens in Tor Browser | 'open 1' | 'dismiss'",
            bg=COLORS["darknet_bg"],
            fg=COLORS["darknet_snippet"],
            font=("Consolas", 8)
        )
        hint.pack(anchor="w", pady=(5, 0))

    # ---------- Email Cards ----------

    def _remove_email_from_list(self, msg_id: str = None, idx: int = None):
        """Remove a single email from the currently displayed list and re-render."""
        if not hasattr(self, "_current_email_list") or not self._current_email_list:
            return
        before = len(self._current_email_list)
        if msg_id:
            self._current_email_list = [
                e for e in self._current_email_list
                if e.get("id") != msg_id and e.get("id", "").strip("<>") != msg_id.strip("<>")
            ]
        if idx is not None:
            self._current_email_list = [
                e for e in self._current_email_list if e.get("idx") != idx
            ]
        if len(self._current_email_list) < before:
            folder = getattr(self, "_current_email_folder", "INBOX")
            self._render_email_list(self._current_email_list, folder)

    def _render_email_list(self, emails: list, folder: str = "INBOX"):
        """Render clickable email cards with REAL metadata (no LLM)."""
        from overlay.widgets.email_card import EmailCard, EmailData

        # Store for instant removal on delete/spam + "diese mails" context
        self._current_email_list = list(emails)
        self._current_email_folder = folder
        self._last_email_notification_folder = folder

        self._clear_results()
        if not emails:
            return

        self.results_container.pack(fill="x", padx=15, pady=(0, 5))

        # Header with count and close button
        header_frame = tk.Frame(self.results_container, bg=COLORS["bg_main"])
        header_frame.pack(fill="x", pady=(0, 5))

        unread_count = sum(1 for e in emails if not e.get("read", True))
        total = len(emails)
        _FOLDER_DISPLAY = {
            "INBOX": "Inbox", "[Gmail]/Spam": "Spam",
            "[Gmail]/Papierkorb": "Trash", "[Gmail]/Gesendet": "Sent",
            "[Gmail]/Entw&APw-rfe": "Drafts", "[Gmail]/Wichtig": "Important",
            "[Gmail]/Alle Nachrichten": "All Mail",
        }
        folder_name = _FOLDER_DISPLAY.get(folder, folder)
        if unread_count > 0:
            header_text = f"{folder_name} - {unread_count} unread ({total} total):"
        else:
            header_text = f"{folder_name} ({total}):"

        header = tk.Label(
            header_frame, text=header_text,
            bg=COLORS["bg_main"], fg=COLORS["text_secondary"],
            font=("Segoe UI", 9)
        )
        header.pack(side="left")

        close_btn = tk.Label(
            header_frame, text="\u2715 Close",
            bg=COLORS["bg_main"], fg=COLORS["accent"],
            font=("Segoe UI", 9), cursor="hand2"
        )
        close_btn.pack(side="right")
        close_btn.bind("<Button-1>", lambda e: self._clear_results())

        # Search bar
        search_frame = tk.Frame(self.results_container, bg=COLORS["bg_main"])
        search_frame.pack(fill="x", pady=(0, 4))

        search_entry = tk.Entry(
            search_frame, bg=COLORS["bg_elevated"], fg=COLORS["text_primary"],
            insertbackground=COLORS["neon_cyan"], font=("Consolas", 9),
            relief="flat", highlightbackground=COLORS["text_muted"],
            highlightcolor=COLORS["neon_cyan"], highlightthickness=1,
        )
        search_entry.pack(side="left", fill="x", expand=True, padx=(0, 4))
        search_entry.bind("<Return>", lambda e, f=folder: self._io_q.put(
            ("email_search", {"query": search_entry.get().strip(), "folder": f})
        ) if search_entry.get().strip() else None)

        tk.Label(
            search_frame, text="from: subject: date:",
            bg=COLORS["bg_main"], fg=COLORS["text_muted"],
            font=("Consolas", 7)
        ).pack(side="right")

        # Scrollable frame for email cards
        canvas = tk.Canvas(self.results_container, bg=COLORS["bg_main"], highlightthickness=0, height=280)
        scrollbar = tk.Scrollbar(self.results_container, orient="vertical", command=canvas.yview)
        scrollable_frame = tk.Frame(canvas, bg=COLORS["bg_main"])

        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw", width=390)
        canvas.configure(yscrollcommand=scrollbar.set)

        # Mouse wheel scrolling — bind to canvas and surrounding widgets
        def _email_scroll(event):
            canvas.yview_scroll(-1 if event.num == 4 else 1, "units")
            return "break"

        for _sw in (canvas, scrollbar, header_frame, header, close_btn,
                    self.results_container, search_frame, search_entry):
            _sw.bind("<Button-4>", _email_scroll)
            _sw.bind("<Button-5>", _email_scroll)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # Create EmailCard for each email
        for em in emails:
            email_data = EmailData(
                idx=em.get("idx", 0),
                msg_id=em.get("id", ""),
                sender=em.get("from", "?"),
                subject=em.get("subject", "(no subject)"),
                date=em.get("date", ""),
                timestamp=em.get("timestamp", 0),
                snippet=em.get("snippet", ""),
                read=em.get("read", True),
                starred=em.get("starred", False),
                folder=folder,
                to=em.get("to", ""),
                cc=em.get("cc", ""),
            )
            card = EmailCard(
                scrollable_frame,
                email_data=email_data,
                on_click=lambda ed=email_data: self._io_q.put(("email_popup", {"email_data": ed})),
            )
            card.pack(fill="x", pady=1)

        # Bind scroll to ALL child widgets recursively (gaps, inner frames, labels)
        def _bind_scroll_recursive(widget):
            widget.bind("<Button-4>", _email_scroll)
            widget.bind("<Button-5>", _email_scroll)
            for child in widget.winfo_children():
                _bind_scroll_recursive(child)
        _bind_scroll_recursive(scrollable_frame)

    def _show_email_in_chat(self, email_data):
        """Instant email detail: show metadata in chat + action bar below. No LLM, 0ms."""
        from overlay.widgets.email_card import format_sender, format_date_short

        import re

        sender = format_sender(email_data.sender)
        date = format_date_short(email_data.date)
        subject = email_data.subject or "(no subject)"
        snippet = email_data.snippet or ""

        # Clean snippet: strip ALL HTML entities, tags, and junk
        snippet = re.sub(r'&[a-zA-Z]+;', ' ', snippet)   # &nbsp; &zwnj; etc.
        snippet = re.sub(r'&#?\w+;', ' ', snippet)        # &#160; etc.
        snippet = re.sub(r'&\w*$', '', snippet)            # trailing truncated &zw
        snippet = re.sub(r'<[^>]+>', '', snippet)          # <tags>
        snippet = re.sub(r'^\d{1,3}\s+', '', snippet.strip())  # leading "96 " junk
        snippet = " ".join(snippet.split())                # collapse whitespace
        if len(snippet) > 200:
            snippet = snippet[:200] + "..."

        # Build chat message with real metadata
        lines = [
            f"From: {sender}",
            f"Subject: {subject}",
            f"Date: {date}",
        ]
        if snippet:
            lines.append(f"---\n{snippet}")

        msg = "\n".join(lines)
        self._add_message("Frank", msg)

        # Show compact action bar in results_container
        self._clear_results()
        self.results_container.pack(fill="x", padx=15, pady=(0, 3))

        actions_frame = tk.Frame(self.results_container, bg=COLORS["bg_main"])
        actions_frame.pack(fill="x")

        msg_id = email_data.msg_id
        query = email_data.sender or email_data.subject
        folder = email_data.folder

        # READ button (green) - fetch full email body via LLM summary
        read_btn = tk.Label(
            actions_frame, text=" READ ",
            bg="#006400", fg="#FFFFFF",
            font=("Consolas", 9, "bold"), cursor="hand2", padx=6, pady=3
        )
        read_btn.pack(side="left", padx=(0, 6))
        read_btn.bind("<Button-1>", lambda e, f=folder, m=msg_id, q=query, idx=email_data.idx:
                      self._io_q.put(("email_detail", {"folder": f, "msg_id": m, "idx": idx})))

        # THUNDERBIRD button (blue) - open Thunderbird email client
        tb_btn = tk.Label(
            actions_frame, text=" THUNDERBIRD ",
            bg="#1E90FF", fg="#FFFFFF",
            font=("Consolas", 9, "bold"), cursor="hand2", padx=6, pady=3
        )
        tb_btn.pack(side="left", padx=(0, 6))
        tb_btn.bind("<Button-1>", lambda e: self._open_thunderbird())

        # SPAM button (yellow)
        spam_btn = tk.Label(
            actions_frame, text=" SPAM ",
            bg="#8B8000", fg="#FFFFFF",
            font=("Consolas", 9, "bold"), cursor="hand2", padx=6, pady=3
        )
        spam_btn.pack(side="left", padx=(0, 6))
        spam_btn.bind("<Button-1>", lambda e, f=folder, m=msg_id, q=query:
                      self._io_q.put(("email_spam", {"folder": f, "msg_id": m, "query": q})))

        # DELETE button (red)
        del_btn = tk.Label(
            actions_frame, text=" DELETE ",
            bg="#8B0000", fg="#FFFFFF",
            font=("Consolas", 9, "bold"), cursor="hand2", padx=6, pady=3
        )
        del_btn.pack(side="left", padx=(0, 6))
        del_btn.bind("<Button-1>", lambda e, f=folder, m=msg_id, q=query:
                     self._io_q.put(("email_delete_single", {"folder": f, "msg_id": m, "query": q})))

        # BACK button (cyan) - back to email list
        back_btn = tk.Label(
            actions_frame, text=" BACK ",
            bg=COLORS.get("neon_cyan", "#00FFFF"), fg=COLORS["bg_main"],
            font=("Consolas", 9, "bold"), cursor="hand2", padx=6, pady=3
        )
        back_btn.pack(side="left")
        back_btn.bind("<Button-1>", lambda e, f=folder:
                      self._io_q.put(("email_list_cards", {"folder": f})))

    def _open_thunderbird(self):
        """Open Thunderbird email client."""
        import subprocess
        try:
            subprocess.Popen(["thunderbird"], start_new_session=True,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except FileNotFoundError:
            try:
                subprocess.Popen(["snap", "run", "thunderbird"], start_new_session=True,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception:
                self._add_message("Frank", "Could not start Thunderbird.", is_system=True)

    # ---------- File Actions ----------

    def _show_file_actions(self):
        self._hide_file_actions()
        if not self._last_file:
            return

        self.file_actions_container.pack(fill="x", padx=15, pady=(0, 5))

        action_bar = FileActionBar(
            self.file_actions_container,
            filename=self._last_file.name,
            on_action=self._run_file_action,
            on_cancel=self._clear_file
        )
        action_bar.pack(fill="x")

    def _clear_file(self):
        self._last_file = None
        self._last_file_lang = "text"
        self._last_file_content = ""
        self._hide_file_actions()
        self._add_message("Frank", "Ok, cancelled.", is_system=True)
