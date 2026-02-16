"""
VoiceMixin -- voice daemon integration and push-to-talk.

Extracted from chat_overlay_monolith.py lines ~5300-5577 and ~6760-6795.
Handles:
  - Voice daemon event polling and dispatch
  - Voice input processing (Option A: Overlay as Dispatcher)
  - Voice response output via TTS outbox
  - Push-to-Talk (PTT) press / release / result / insert-and-send
"""

import json
import os
import re
import subprocess
import tempfile
import threading
import time
import tkinter as tk
from pathlib import Path
from overlay.constants import (
    LOG, COLORS, DEFAULT_TIMEOUT_S,
    WALLPAPER_RE, WALLPAPER_START_RE, WALLPAPER_STOP_RE,
    STEAM_LIST_RE, STEAM_CLOSE_RE, STEAM_LAUNCH_RE,
    ADI_HINTS_RE, DESKTOP_HINTS_RE, FS_HINTS_RE, FS_PATH_RE,
    SYS_HINTS_RE, SELF_AWARE_RE, SELF_AWARE_EXCLUDE_RE,
    DARKNET_RE,
)
from overlay.file_utils import _maybe_path
from overlay.services.toolbox import _core_reflect
from overlay.http_helpers import _http_post_json


class VoiceMixin:

    def _poll_voice_events(self):
        """Poll for voice events from the voice daemon."""
        try:
            if self._voice_event_file.exists():
                try:
                    event_data = json.loads(self._voice_event_file.read_text())
                    event_ts = event_data.get("timestamp", 0)
                    event_type = event_data.get("type", "")

                    # Only process new events
                    if event_ts > self._last_voice_event_ts:
                        self._last_voice_event_ts = event_ts
                        LOG.debug(f"Voice event received: {event_type}")
                        self._handle_voice_event(event_data)
                except (json.JSONDecodeError, IOError) as e:
                    LOG.debug(f"Voice event parse error: {e}")
        except Exception as e:
            LOG.error(f"Voice event poll error: {e}")

        # Poll every 50ms for faster response
        self.after(50, self._poll_voice_events)

    def _handle_voice_event(self, event: dict):
        """Handle a voice event from the voice daemon."""
        event_type = event.get("type", "")

        if event_type == "voice_input":
            # NEW: Voice-First Integration (Option A)
            # Voice daemon sends recognized text for full Overlay processing
            text = event.get("text", "")
            session_id = event.get("session_id", "")
            if text:
                LOG.info(f"Voice input received: '{text[:50]}...' (session={session_id})")
                self._pending_voice_session = session_id
                self._hide_typing()
                self._add_message("🎤 Du", text, is_user=True)
                self._show_typing()
                # Process through the SAME pipeline as typed input
                self._process_voice_input(text)

        elif event_type == "user_message":
            # Legacy: User spoke via voice - show in chat (display only)
            text = event.get("text", "")
            if text:
                self._hide_typing()
                self._add_message("🎤 Du", text, is_user=True)
                self._show_typing()

        elif event_type == "frank_message":
            # Legacy: Frank is responding via voice - show in chat
            text = event.get("text", "")
            if text:
                self._hide_typing()
                self._add_message("🔊 Frank", text, is_user=False)

        elif event_type == "listening":
            # Voice daemon is listening for user command
            self._voice_listening = True
            self._show_listening_indicator()

        elif event_type == "processing":
            # Voice daemon is processing - keep typing indicator
            pass

        elif event_type == "wake_word":
            # Wake word detected - restore and focus the window
            self._show_overlay()
            self._voice_listening = True

        elif event_type == "idle":
            # Voice daemon is idle - hide typing indicator
            self._voice_listening = False
            self._hide_typing()

    def _process_voice_input(self, msg: str):
        """
        Process voice input through the same pipeline as typed input.
        This is the key to Option A: Voice -> Overlay as Dispatcher.
        All responses go to both UI (display) AND Voice (TTS).
        """
        low = msg.lower().strip()
        LOG.info(f"🎤 Processing voice input: '{msg[:50]}...'")

        # File path detection
        p = _maybe_path(msg)
        if p:
            self._handle_attach(p)
            self._voice_respond("Processing file.")
            return

        # Wallpaper control
        if WALLPAPER_RE.search(low):
            if WALLPAPER_START_RE.search(low):
                ok, result = self._control_wallpaper("start")
                self._voice_respond(result)
                return
            elif WALLPAPER_STOP_RE.search(low):
                ok, result = self._control_wallpaper("stop")
                self._voice_respond(result)
                return

        # Steam: List games
        if STEAM_LIST_RE.search(low):
            self._io_q.put(("steam_list", {"voice": True}))
            return

        # Steam: Close game
        if STEAM_CLOSE_RE.search(low):
            self._io_q.put(("steam_close", {"voice": True}))
            return

        # Steam: Launch game (check before generic "öffne")
        steam_match = STEAM_LAUNCH_RE.search(msg)
        if steam_match:
            game_name = steam_match.group(2).strip()
            if game_name:
                self._io_q.put(("steam_launch", {"game": game_name, "voice": True}))
                return

        # App open/launch
        if low.startswith("öffne ") or low.startswith("oeffne ") or low.startswith("open ") or low.startswith("starte "):
            q = msg.split(" ", 1)[1].strip() if " " in msg else ""
            if q:
                self._io_q.put(("app_open", {"app": q, "from_user_query": msg, "voice": True}))
                return

        # ADI (Adaptive Display Intelligence) - Display/layout configuration
        if ADI_HINTS_RE.search(low):
            LOG.info("🎤 Voice -> ADI request")
            self._handle_adi_request(msg)
            return

        # Desktop screenshot - FIXED: Use queue instead of non-existent function
        if DESKTOP_HINTS_RE.search(low) and not FS_HINTS_RE.search(low):
            LOG.info("🎤 Voice -> Screenshot request")
            self._add_message("Frank", "Schaue auf deinen Desktop...", is_system=True)
            self._chat_q.put(("screenshot", {"user_query": msg, "voice": True}))
            return

        # Filesystem hints - ONLY proceed if explicit path found
        # NEVER default to ~ without clear user intent
        if FS_HINTS_RE.search(low):
            m = FS_PATH_RE.search(msg)
            if m:
                fs_path = m.group(1)
                LOG.info(f"🎤 Voice -> Filesystem request: {fs_path}")
                self._io_q.put(("fs_list", {"path": fs_path, "voice": True}))
                return
            # No path found - fall through to LLM instead of defaulting to ~
            LOG.debug("FS_HINTS matched but no path found, routing to LLM")

        # Darknet search (guard: skip statements like "you can search darknet")
        _STMT_GUARD = re.compile(
            r"^(i\s+think|i\s+believe|it'?s\s|that\s+you|you\s+can|you\s+could|"
            r"amazing|cool|great|wow|nice|ich\s+finde|ich\s+glaub|toll\s+dass)",
            re.IGNORECASE,
        )
        if DARKNET_RE.search(low) and not _STMT_GUARD.search(low):
            q = re.sub(
                r"((?:se[ae]?r?ch|search|find|look(?:\s*(?:up|for))?|such\w*|query|browse)"
                r"\s+(?:(?:in|on|in\s+the|on\s+the|the|im)\s+)?"
                r"(?:darknet|dark\s*web|deep\s*web|tor(?:\s+network)?|onion|hidden\s*service)\s*"
                r"|(?:darknet|dark\s*web|deep\s*web|tor|onion)\s*"
                r"(?:se[ae]?r?ch|search|find|look|query|market|shop|store|site|forum)\w*\s*"
                r"|(?:(?:in|on|in\s+the|on\s+the)\s+)?"
                r"(?:darknet|dark\s*web|deep\s*web|tor|onion)\s*"
                r"|^(?:se[ae]?r?ch|search|find|look\s+for|look\s+up|browse)\s+"
                r"|nach\s+|for\s+)",
                "", msg, flags=re.IGNORECASE
            ).strip()
            if q:
                LOG.info(f"🎤 Voice -> Darknet search: {q}")
                self._io_q.put(("darknet_search", {"query": q, "limit": 8}))
                return

        # System status queries (wie heiß bist du, Temperatur, etc.)
        if SYS_HINTS_RE.search(low):
            LOG.info("🎤 Voice -> System status request")
            # Route to LLM with system context
            self._chat_q.put(("chat", {
                "msg": msg,
                "max_tokens": 256,
                "timeout_s": DEFAULT_TIMEOUT_S,
                "task": "chat.fast",
                "force": "llama",
                "voice": True
            }))
            return

        # Self-awareness queries
        if SELF_AWARE_RE.search(low) and not SELF_AWARE_EXCLUDE_RE.search(low):
            is_simple = len(msg.strip()) < 50 and bool(re.search(
                r"^(was\s+bist\s+du|wer\s+bist\s+du|beschreibe?\s+dich|"
                r"wie\s+komplex|erkläre?\s+dich|dein\s+system\b$|dein\s+code\b$)",
                low
            ))
            if is_simple:
                result = _core_reflect()
                if result and result.get("ok"):
                    self._voice_respond(result.get("reflection", "Ich kann mich gerade nicht analysieren."))
                else:
                    self._voice_respond("Ich kann gerade nicht auf meine Selbst-Analyse zugreifen.")
                return

        # Default: Send to LLM (chat mode)
        LOG.info(f"🎤 Voice -> LLM chat: '{msg[:50]}...'")
        self._chat_q.put(("chat", {
            "msg": msg,
            "max_tokens": 256,
            "timeout_s": DEFAULT_TIMEOUT_S,
            "task": "chat.fast",
            "force": None,
            "voice": True  # Flag for voice response
        }))

    def _voice_respond(self, text: str):
        """
        Send a response back to the voice daemon via the Outbox.
        Voice daemon will read this and speak it via TTS.
        """
        if not text:
            return

        LOG.info(f"Voice response -> Outbox: '{text[:50]}...'")
        self._hide_typing()
        self._add_message("🔊 Frank", text, is_user=False)

        # Write to Outbox for voice daemon to pick up
        try:
            outbox_data = {
                "type": "frank_response",
                "session_id": self._pending_voice_session or "",
                "text": text,
                "timestamp": time.time()
            }
            self._voice_outbox_file.write_text(json.dumps(outbox_data, ensure_ascii=False))
        except Exception as e:
            LOG.error(f"Failed to write voice outbox: {e}")

        self._pending_voice_session = None

    # ---------- TTS Engine ----------
    _kokoro_instance = None  # Lazy-loaded singleton

    @classmethod
    def _get_kokoro(cls):
        """Lazy-load Kokoro TTS (heavy ONNX model, only load once)."""
        if cls._kokoro_instance is None:
            model = Path.home() / ".local/share/frank/kokoro/kokoro-v1.0.onnx"
            voices = Path.home() / ".local/share/frank/kokoro/voices-v1.0.bin"
            if model.exists() and voices.exists():
                try:
                    from kokoro_onnx import Kokoro
                    cls._kokoro_instance = Kokoro(str(model), str(voices))
                    LOG.info("Kokoro TTS loaded (am_fenrir voice)")
                except Exception as e:
                    LOG.error(f"Kokoro TTS init failed: {e}")
                    cls._kokoro_instance = False  # Mark as failed
            else:
                LOG.warning("Kokoro model files not found, English TTS unavailable")
                cls._kokoro_instance = False
        return cls._kokoro_instance if cls._kokoro_instance is not False else None

    @staticmethod
    def _detect_language(text: str) -> str:
        """Detect if text is primarily German or English."""
        de_markers = re.compile(
            r'\b(ich|und|der|die|das|ist|ein|eine|nicht|auf|für|mit|den|dem|'
            r'des|von|zu|auch|wird|hat|kann|aber|oder|noch|nach|über|wie|'
            r'nur|bei|vor|mehr|dann|schon|wenn|sein|dein|mein|'
            r'bist|hast|habe|wir|sie|dir|mir|dich|mich|hier|'
            r'jetzt|gerade|heute|morgen|gestern|'
            r'ä|ö|ü|ß)\b', re.IGNORECASE
        )
        words = text.split()
        if not words:
            return "en"
        de_count = len(de_markers.findall(text))
        ratio = de_count / len(words)
        return "de" if ratio > 0.15 else "en"

    def _tts_speak(self, text: str):
        """Speak text via Kokoro TTS (am_fenrir deep voice for all languages)."""
        if not text:
            return
        LOG.info(f"TTS speak: '{text[:80]}...'")
        threading.Thread(target=self._tts_speak_worker, args=(text,), daemon=True).start()

    def _tts_speak_worker(self, text: str):
        """Background worker: Kokoro (deep voice) for English, Piper for German."""
        lang = self._detect_language(text)
        LOG.info(f"TTS language: {lang}")
        if lang == "de":
            self._tts_piper(text)
        else:
            self._tts_kokoro(text)

    def _tts_kokoro(self, text: str):
        """Generate English speech with Kokoro (am_fenrir deep voice)."""
        kokoro = self._get_kokoro()
        if not kokoro:
            LOG.warning("Kokoro unavailable, falling back to Piper")
            self._tts_piper(text)
            return

        out_fd, out_path = tempfile.mkstemp(suffix="_kokoro.wav")
        os.close(out_fd)
        play_fd, play_path = tempfile.mkstemp(suffix="_play.wav")
        os.close(play_fd)
        try:
            import soundfile as sf
            lang = "de" if self._detect_language(text) == "de" else "en-us"
            samples, sr = kokoro.create(text, voice="am_fenrir", speed=1.0, lang=lang)
            sf.write(out_path, samples, sr)

            # Resample 24kHz → 48kHz stereo + volume boost
            try:
                subprocess.run(
                    ["ffmpeg", "-y", "-i", out_path,
                     "-ar", "48000", "-ac", "2",
                     "-filter:a", "volume=2.0",
                     play_path],
                    capture_output=True, timeout=15,
                )
                if Path(play_path).exists() and Path(play_path).stat().st_size > 100:
                    out_path, play_path = play_path, out_path  # swap so we play resampled
            except Exception:
                pass  # Play raw Kokoro output

            try:
                subprocess.run(["pw-play", out_path], capture_output=True, timeout=60)
            except FileNotFoundError:
                subprocess.run(["paplay", out_path], capture_output=True, timeout=60)

        except Exception as e:
            LOG.error(f"Kokoro TTS error: {e}")
            self._tts_piper(text)  # Fallback
        finally:
            for p in (out_path, play_path):
                try:
                    os.unlink(p)
                except OSError:
                    pass

    def _tts_piper(self, text: str):
        """Generate German speech with Piper (Thorsten voice)."""
        piper_bin = Path.home() / ".local/bin/piper"
        voice_model = Path.home() / ".local/share/frank/voices/de_DE-thorsten-high.onnx"

        if not piper_bin.exists() or not voice_model.exists():
            LOG.error(f"Piper TTS unavailable: piper={piper_bin.exists()}, voice={voice_model.exists()}")
            return

        raw_fd, raw_path = tempfile.mkstemp(suffix="_piper.wav")
        os.close(raw_fd)
        out_fd, out_path = tempfile.mkstemp(suffix="_play.wav")
        os.close(out_fd)
        try:
            proc = subprocess.Popen(
                [str(piper_bin), "--model", str(voice_model), "--output_file", raw_path],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            proc.communicate(input=text.encode("utf-8"), timeout=30)

            if not Path(raw_path).exists() or Path(raw_path).stat().st_size < 100:
                LOG.error("Piper TTS: no audio produced")
                return

            # Resample 22050Hz → 48kHz stereo + volume boost
            play_path = raw_path
            try:
                subprocess.run(
                    ["ffmpeg", "-y", "-i", raw_path,
                     "-ar", "48000", "-ac", "2",
                     "-filter:a", "volume=2.0",
                     out_path],
                    capture_output=True, timeout=15,
                )
                if Path(out_path).exists() and Path(out_path).stat().st_size > 100:
                    play_path = out_path
            except Exception:
                pass

            try:
                subprocess.run(["pw-play", play_path], capture_output=True, timeout=60)
            except FileNotFoundError:
                subprocess.run(["paplay", play_path], capture_output=True, timeout=60)

        except Exception as e:
            LOG.error(f"Piper TTS error: {e}")
        finally:
            for p in (raw_path, out_path):
                try:
                    os.unlink(p)
                except OSError:
                    pass

    # ---------- Push-to-Talk ----------
    def _on_ptt_press(self, event=None):
        """Start recording when PTT button is pressed."""
        if self._ptt_recording:
            return
        self._ptt_recording = True
        self.ptt_btn.configure(bg="#ff4444")  # Red while recording
        self.ptt.start_recording()

    def _on_ptt_release(self, event=None):
        """Stop recording when PTT button is released."""
        if not self._ptt_recording:
            return
        self._ptt_recording = False
        self.ptt_btn.configure(bg=COLORS["bg_input"])  # Back to normal
        self.ptt.stop_recording()

    def _on_ptt_error(self, error_msg: str):
        """Handle PTT transcription errors — show feedback to user."""
        LOG.warning(f"PTT error: {error_msg}")
        self.after(0, lambda m=error_msg: self._add_message("Frank", m, is_system=True))

    def _on_ptt_result(self, text: str):
        """Handle transcribed text from PTT."""
        if not text:
            return
        LOG.info(f"PTT: Sending to chat: '{text}'")
        # Insert text into entry and send
        self.after(0, lambda: self._ptt_insert_and_send(text))

    def _ptt_insert_and_send(self, text: str):
        """Insert PTT text and send message (must run on main thread)."""
        LOG.info(f"PTT: Inserting into entry: '{text}'")
        self.entry.delete(0, tk.END)
        self.entry.insert(0, text)
        self._on_send()
