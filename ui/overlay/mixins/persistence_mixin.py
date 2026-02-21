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
                messages = self._chat_memory_db.get_recent_messages(limit=30)
                if messages:
                    # Populate in-memory ring buffer for LLM context (skip system msgs)
                    self._chat_history = [
                        {"role": m["role"], "sender": m["sender"],
                         "text": m["text"][:500] if len(m["text"]) > 500 else m["text"],
                         "is_user": bool(m["is_user"]),
                         "ts": m["timestamp"]}
                        for m in messages[-self._chat_history_max:]
                        if m.get("role") != "system"
                    ]
                    # Render all messages in UI
                    for msg in messages:
                        sender = msg.get("sender", "Frank")
                        text = msg.get("text", "")
                        is_user = bool(msg.get("is_user", False))
                        is_system = msg.get("role") == "system"
                        # Truncate system messages (entity session summaries etc.)
                        # to max 15 words for clean chat display
                        if is_system and text:
                            words = text.split()
                            if len(words) > 15:
                                text = " ".join(words[:15]) + " …"
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
        """Generate session summary (delegates to batch method)."""
        self._batch_session_summaries(max_sessions=1)

    def _memory_maintenance_timer(self):
        """Periodic memory maintenance: close idle sessions, generate summaries, cleanup."""
        try:
            if hasattr(self, '_chat_memory_db'):
                # 1. Close idle sessions (>30 min without activity)
                try:
                    closed = self._chat_memory_db.close_idle_sessions(idle_minutes=30)
                    if closed > 0:
                        LOG.info(f"Memory maintenance: closed {closed} idle sessions")
                except Exception as e:
                    LOG.debug(f"Idle session close failed: {e}")

                # 2. Batch summarize up to 3 sessions per cycle
                self._batch_session_summaries(max_sessions=3)

                # 3. Archive old messages
                archived = self._chat_memory_db.cleanup_old_messages(retention_days=30)
                if archived > 0:
                    LOG.info(f"Memory maintenance: archived {archived} old messages")

                # 4. Memory consistency check (runs max 1x/day)
                try:
                    from services.memory_consistency import get_consistency_daemon
                    cd = get_consistency_daemon()
                    if cd.should_run():
                        report = cd.run_nightly()
                        LOG.info(f"Consistency check: {report.get('duration_ms', 0)}ms")
                except Exception as e:
                    LOG.debug(f"Consistency check skipped: {e}")
        except Exception as e:
            LOG.warning(f"Memory maintenance error: {e}")
        self.after(3600_000, self._memory_maintenance_timer)

    def _batch_session_summaries(self, max_sessions: int = 3):
        """Generate summaries for up to N sessions. Falls back to keyword extraction."""
        if not hasattr(self, '_chat_memory_db'):
            return

        try:
            sessions = self._chat_memory_db.get_sessions_for_summarization(limit=max_sessions)
        except Exception:
            sessions = []
            session = self._chat_memory_db.get_session_for_summarization()
            if session:
                sessions = [session]

        for session in sessions:
            try:
                messages = self._chat_memory_db.get_session_messages(
                    session["session_id"], limit=30,
                )
                if len(messages) < 3:
                    continue

                conv_text = "\n".join(
                    f"{'User' if m['is_user'] else 'Frank'}: {m['text'][:200]}"
                    for m in messages[:20]
                )

                # Try LLM summarization
                summary = None
                try:
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
                except Exception as e:
                    LOG.debug(f"LLM summary failed, trying keyword fallback: {e}")

                # Fallback: keyword-based summary
                if not summary:
                    summary = self._keyword_summary(messages)

                if summary:
                    self._chat_memory_db.store_session_summary(
                        session["session_id"], summary,
                    )
                    LOG.info(f"Session {session['session_id']} summarized: {summary[:80]}...")

            except Exception as e:
                LOG.warning(f"Session summary failed for {session.get('session_id')}: {e}")

    @staticmethod
    def _keyword_summary(messages: list) -> str:
        """Fallback: extract key topics from messages when LLM unavailable."""
        import re
        from collections import Counter

        # Collect words from user messages (most indicative of topics)
        words = []
        for m in messages:
            if m.get("is_user"):
                text = m.get("text", "").lower()
                # Remove short/common words
                tokens = re.findall(r'\b[a-zäöüß]{4,}\b', text)
                words.extend(tokens)

        if not words:
            return ""

        # Filter stopwords
        stopwords = {"dass", "wird", "habe", "haben", "eine", "einen", "einem", "einer",
                     "nicht", "auch", "noch", "schon", "aber", "oder", "wenn", "dann",
                     "this", "that", "with", "from", "they", "have", "been", "were",
                     "what", "about", "your", "will", "would", "could", "should",
                     "frank", "bitte", "danke", "kannst", "machen", "gerade"}
        filtered = [w for w in words if w not in stopwords]

        top = Counter(filtered).most_common(5)
        if not top:
            return ""

        topics = ", ".join(w for w, _ in top)
        return f"Themen: {topics} ({len(messages)} Nachrichten)"
