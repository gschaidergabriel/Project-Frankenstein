"""Persistence mixin -- save / load chat history (SQLite primary, JSON fallback).

Methods rely on self.* attributes provided by the assembled ChatOverlay
at runtime via MRO.
"""

import json
from pathlib import Path

from overlay.constants import LOG
from overlay.widgets.message_bubble import MessageBubble


class PersistenceMixin:

    def _build_bubble_callbacks(self, text: str, is_user: bool):
        """Build on_retry / on_speak callbacks for a history bubble."""
        on_retry = None
        on_speak = None
        if not is_user:
            # Find last user message in history for retry
            for h in reversed(self._chat_history):
                if h.get("role") == "user":
                    _m = h.get("text", "")
                    on_retry = lambda m=_m: self._retry_last_message(m)
                    break
            # TTS callback (no message duplication)
            if hasattr(self, '_tts_speak'):
                on_speak = lambda m=text: self._tts_speak(m)
        return on_retry, on_speak

    def _save_chat_history(self):
        """Save chat history to JSON (backward compat -- SQLite is primary now)."""
        try:
            self._chat_history_file.parent.mkdir(parents=True, exist_ok=True)
            self._chat_history_file.write_text(
                json.dumps(self._chat_history, ensure_ascii=False, indent=2)
            )
        except Exception as e:
            LOG.error(f"Failed to save chat history: {e}")

    def _load_chat_history(self) -> bool:
        """Load chat history for UI display.

        Primary: SQLite (last 50 messages).
        Fallback: JSON file.
        """
        # Try SQLite first
        if hasattr(self, '_chat_memory_db'):
            try:
                messages = self._chat_memory_db.get_recent_messages(limit=10)
                if messages:
                    # Populate in-memory ring buffer for LLM context fallback
                    self._chat_history = [
                        {"role": m["role"], "sender": m["sender"],
                         "text": m["text"][:500] if len(m["text"]) > 500 else m["text"],
                         "is_user": bool(m["is_user"]),
                         "ts": m["timestamp"]}
                        for m in messages[-self._chat_history_max:]
                    ]
                    # Render all messages in UI
                    for msg in messages:
                        sender = msg.get("sender", "Frank")
                        text = msg.get("text", "")
                        is_user = bool(msg.get("is_user", False))
                        is_system = msg.get("role") == "system"
                        if text:
                            on_retry = None
                            on_speak = None
                            if not is_system:
                                on_retry, on_speak = self._build_bubble_callbacks(text, is_user)
                            bubble = MessageBubble(
                                self.messages_frame,
                                sender=sender,
                                message=text,
                                is_user=is_user,
                                is_system=is_system,
                                on_link_click=lambda url: self._io_q.put(("open", url)),
                                on_retry=on_retry,
                                on_speak=on_speak,
                            )
                            bubble.pack(fill="x", anchor="w" if not is_user else "e")
                    # Force full layout: update_idletasks + update ensures all
                    # Configure events are processed and widgets get real dimensions
                    self.messages_frame.update_idletasks()
                    self.update()
                    self.chat_canvas.configure(scrollregion=self.chat_canvas.bbox("all"))
                    self.chat_canvas.yview_moveto(1.0)
                    LOG.info(f"Loaded {len(messages)} messages from SQLite memory")
                    return True
            except Exception as e:
                LOG.warning(f"SQLite history load failed, falling back to JSON: {e}")

        # Fallback to original JSON loading
        try:
            if not self._chat_history_file.exists():
                return False

            data = json.loads(self._chat_history_file.read_text())
            if not data or not isinstance(data, list):
                return False

            self._chat_history = data[-self._chat_history_max:]

            for msg in self._chat_history:
                sender = msg.get("sender", "Frank" if msg.get("role") == "frank" else "Du")
                text = msg.get("text", "")
                is_user = msg.get("is_user", msg.get("role") == "user")
                if text:
                    on_retry, on_speak = self._build_bubble_callbacks(text, is_user)
                    bubble = MessageBubble(
                        self.messages_frame,
                        sender=sender,
                        message=text,
                        is_user=is_user,
                        is_system=False,
                        on_link_click=lambda url: self._io_q.put(("open", url)),
                        on_retry=on_retry,
                        on_speak=on_speak,
                    )
                    bubble.pack(fill="x", anchor="w" if not is_user else "e")

            self.messages_frame.update_idletasks()
            self.update()
            self.chat_canvas.configure(scrollregion=self.chat_canvas.bbox("all"))
            self.chat_canvas.yview_moveto(1.0)

            LOG.info(f"Loaded {len(self._chat_history)} messages from JSON history")
            return True

        except Exception as e:
            LOG.error(f"Failed to load chat history: {e}")
            return False

    def _trigger_session_summary(self):
        """Generate session summary via LLM after session ends."""
        if not hasattr(self, '_chat_memory_db'):
            return
        try:
            session = self._chat_memory_db.get_session_for_summarization()
            if not session:
                return

            messages = self._chat_memory_db.get_session_messages(
                session["session_id"], limit=30,
            )
            if len(messages) < 3:
                return

            conv_text = "\n".join(
                f"{'User' if m['is_user'] else 'Frank'}: {m['text'][:200]}"
                for m in messages[:20]
            )

            prompt = (
                f"Fasse das folgende Gespraech in 2-3 Saetzen zusammen. "
                f"Nenne die Hauptthemen und wichtige Fakten.\n\n"
                f"{conv_text}\n\n"
                f"Zusammenfassung (2-3 Saetze, Deutsch):"
            )

            from overlay.services.core_api import _core_chat
            res = _core_chat(prompt, max_tokens=200, timeout_s=30,
                             task="chat.fast", force="llama")
            if res.get("ok") and res.get("text"):
                summary = res["text"].strip()[:500]
                self._chat_memory_db.store_session_summary(
                    session["session_id"], summary,
                )
                LOG.info(f"Session summary generated: {summary[:80]}...")
        except Exception as e:
            LOG.warning(f"Session summary generation failed: {e}")

    def _memory_maintenance_timer(self):
        """Periodic memory maintenance: cleanup old messages, generate summaries."""
        try:
            if hasattr(self, '_chat_memory_db'):
                archived = self._chat_memory_db.cleanup_old_messages(retention_days=30)
                if archived > 0:
                    LOG.info(f"Memory maintenance: archived {archived} old messages")
                self._trigger_session_summary()
        except Exception as e:
            LOG.warning(f"Memory maintenance error: {e}")
        self.after(3600_000, self._memory_maintenance_timer)
