"""
VoiceMixin -- push-to-talk and TTS.

Handles:
  - Voice input processing via push-to-talk
  - Voice response output via TTS (Kokoro EN / Piper DE)
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
    STEAM_LIST_RE, STEAM_CLOSE_RE, STEAM_LAUNCH_RE,
    ADI_HINTS_RE, DESKTOP_HINTS_RE, FS_HINTS_RE, FS_PATH_RE,
    SYS_HINTS_RE, SELF_AWARE_RE, SELF_AWARE_EXCLUDE_RE,
    DARKNET_RE,
)
from overlay.file_utils import _maybe_path
from overlay.services.toolbox import _core_reflect
from overlay.http_helpers import _http_post_json


class VoiceMixin:

    def _process_voice_input(self, msg: str):
        """
        Process voice input through the same pipeline as typed input.
        This is the key to Option A: Voice -> Overlay as Dispatcher.
        All responses go to both UI (display) AND Voice (TTS).
        """
        low = msg.lower().strip()
        LOG.info(f"🎤 Processing voice input: '{msg[:50]}...'")

        # Block input while agentic mode is active (prevent parallel LLM responses)
        if hasattr(self, '_agentic_active') and self._agentic_active:
            # Allow cancel/stop commands through
            if low in ("abbrechen", "stop", "cancel", "stopp"):
                if hasattr(self, '_cancel_agentic_execution'):
                    self._cancel_agentic_execution()
                return
            # Block everything else — agent is working
            LOG.info(f"🎤 Voice input blocked (agentic active): '{msg[:50]}...'")
            self._hide_typing()
            self._add_message("Frank", "I'm still working on the previous task. Say 'cancel' to stop it.", is_system=True)
            return

        # File path detection
        p = _maybe_path(msg)
        if p:
            self._handle_attach(p)
            self._voice_respond("Processing file.")
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
                "max_tokens": 150,
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

        # Agentic execution detection — complex tasks that need real tools
        if hasattr(self, '_is_agentic_query') and self._is_agentic_query(msg):
            LOG.info(f"🎤 Voice -> Agentic execution: '{msg[:50]}...'")
            self._start_agentic_execution(msg)
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
        """Show response in chat AND speak it via TTS."""
        if not text:
            return

        # Check if user cancelled while we were processing
        if getattr(self, '_thinking_cancelled', False):
            LOG.info(f"Voice response suppressed (cancelled): '{text[:50]}...'")
            return

        LOG.info(f"Voice response: '{text[:50]}...'")
        self._hide_typing()
        self._add_message("Frank", text, is_user=False)

        # Speak the response via TTS
        self._tts_speak(text)

    # ---------- TTS Engine ----------
    _kokoro_instance = None  # Lazy-loaded singleton
    _audio_sink = None  # Detected output device
    _tts_play_proc = None  # Current pw-play process (for cancellation)

    @classmethod
    def _get_audio_sink(cls) -> str:
        """Use the system default audio output sink."""
        if cls._audio_sink is not None:
            return cls._audio_sink
        try:
            result = subprocess.run(
                ["pactl", "get-default-sink"],
                capture_output=True, text=True, timeout=5,
            )
            default = result.stdout.strip()
            if default:
                cls._audio_sink = default
                LOG.info(f"TTS audio sink (system default): {cls._audio_sink}")
                return cls._audio_sink
        except Exception as e:
            LOG.warning(f"Audio sink detection failed: {e}")
        cls._audio_sink = ""  # Empty = use pw-play default
        return cls._audio_sink

    @classmethod
    def _stop_tts_playback(cls):
        """Stop any currently playing TTS audio."""
        if cls._tts_play_proc and cls._tts_play_proc.poll() is None:
            try:
                cls._tts_play_proc.terminate()
                cls._tts_play_proc.wait(timeout=2)
                LOG.info("TTS: stopped previous playback")
            except Exception:
                try:
                    cls._tts_play_proc.kill()
                except Exception:
                    pass
            cls._tts_play_proc = None

    @classmethod
    def _play_audio(cls, wav_path: str):
        """Play audio file on the correct output device (stops previous playback)."""
        cls._stop_tts_playback()
        sink = cls._get_audio_sink()
        try:
            cmd = ["pw-play"]
            if sink:
                cmd.extend(["--target", sink])
            cmd.append(wav_path)
            cls._tts_play_proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            cls._tts_play_proc.wait(timeout=120)
            LOG.info(f"TTS play: exit={cls._tts_play_proc.returncode}, sink={sink or 'default'}")
        except subprocess.TimeoutExpired:
            LOG.warning("TTS play timed out")
            cls._stop_tts_playback()
        except FileNotFoundError:
            cmd = ["paplay"]
            if sink:
                cmd.extend(["--device", sink])
            cmd.append(wav_path)
            cls._tts_play_proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            cls._tts_play_proc.wait(timeout=120)
            LOG.info(f"TTS paplay: exit={cls._tts_play_proc.returncode}")

    @classmethod
    def _get_kokoro(cls):
        """Lazy-load Kokoro TTS (heavy ONNX model, only load once)."""
        if cls._kokoro_instance is None:
            model = Path.home() / ".local/share/frank/kokoro/kokoro-v1.0.onnx"
            voices = Path.home() / ".local/share/frank/kokoro/voices-v1.0.bin"
            if model.exists() and voices.exists():
                try:
                    # Use all CPU cores for ONNX inference
                    os.environ.setdefault("OMP_NUM_THREADS", str(os.cpu_count() or 8))
                    from kokoro_onnx import Kokoro
                    cls._kokoro_instance = Kokoro(str(model), str(voices))
                    LOG.info("Kokoro TTS loaded (am_fenrir voice, %d threads)", os.cpu_count() or 8)
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

    @staticmethod
    def _split_tts_text(text: str, max_len: int = 400) -> list:
        """Split text into chunks safe for Kokoro (avoids index-out-of-bounds on long text)."""
        if len(text) <= max_len:
            return [text]
        chunks = []
        # Split on sentence boundaries first
        import re as _re
        sentences = _re.split(r'(?<=[.!?])\s+', text)
        current = ""
        for sent in sentences:
            if len(current) + len(sent) + 1 <= max_len:
                current = (current + " " + sent).strip() if current else sent
            else:
                if current:
                    chunks.append(current)
                # If single sentence is too long, split on commas/spaces
                if len(sent) > max_len:
                    words = sent.split()
                    current = ""
                    for w in words:
                        if len(current) + len(w) + 1 <= max_len:
                            current = (current + " " + w).strip() if current else w
                        else:
                            if current:
                                chunks.append(current)
                            current = w
                else:
                    current = sent
        if current:
            chunks.append(current)
        return chunks if chunks else [text[:max_len]]

    def _tts_kokoro(self, text: str):
        """Generate English speech with Kokoro (am_fenrir deep voice)."""
        kokoro = self._get_kokoro()
        if not kokoro:
            LOG.warning("Kokoro unavailable, no English TTS possible")
            return

        out_fd, out_path = tempfile.mkstemp(suffix="_kokoro.wav")
        os.close(out_fd)
        play_fd, play_path = tempfile.mkstemp(suffix="_play.wav")
        os.close(play_fd)
        try:
            import numpy as np
            import soundfile as sf
            lang = "de" if self._detect_language(text) == "de" else "en-us"

            # Split long text into chunks to avoid Kokoro index errors
            chunks = self._split_tts_text(text)
            all_samples = []
            sr = 24000
            for chunk in chunks:
                try:
                    samples, sr = kokoro.create(chunk, voice="am_fenrir", speed=1.0, lang=lang)
                    all_samples.append(samples)
                except Exception as chunk_err:
                    LOG.warning(f"Kokoro chunk failed ({len(chunk)} chars): {chunk_err}")

            if not all_samples:
                LOG.error("Kokoro: all chunks failed")
                return

            combined = np.concatenate(all_samples)
            sf.write(out_path, combined, sr)

            # Resample 24kHz → 48kHz stereo + volume boost
            try:
                subprocess.run(
                    ["ffmpeg", "-y", "-i", out_path,
                     "-ar", "48000", "-ac", "2",
                     "-filter:a", "volume=2.0",
                     play_path],
                    capture_output=True, timeout=30,
                )
                if Path(play_path).exists() and Path(play_path).stat().st_size > 100:
                    out_path, play_path = play_path, out_path  # swap so we play resampled
            except Exception:
                pass  # Play raw Kokoro output

            self._play_audio(out_path)

        except Exception as e:
            LOG.error(f"Kokoro TTS error: {e}")
            # Do NOT fall back to Piper for English — Thorsten can't speak English
        finally:
            for p in (out_path, play_path):
                try:
                    os.unlink(p)
                except OSError:
                    pass

    def _tts_piper(self, text: str):
        """Generate German speech with Piper (Thorsten voice)."""
        LOG.info("TTS Piper: starting synthesis...")
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
            stdout, stderr = proc.communicate(input=text.encode("utf-8"), timeout=30)
            LOG.info(f"TTS Piper: synthesis done, exit={proc.returncode}, raw_size={Path(raw_path).stat().st_size if Path(raw_path).exists() else 0}")

            if not Path(raw_path).exists() or Path(raw_path).stat().st_size < 100:
                LOG.error("Piper TTS: no audio produced")
                if stderr:
                    LOG.error(f"Piper stderr: {stderr.decode('utf-8', errors='replace')[:200]}")
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

            LOG.info(f"TTS Piper: playing {play_path}...")
            self._play_audio(play_path)

        except Exception as e:
            LOG.error(f"Piper TTS error: {e}", exc_info=True)
        finally:
            for p in (raw_path, out_path):
                try:
                    os.unlink(p)
                except OSError:
                    pass

    # ---------- Push-to-Talk ----------
    _ptt_indicator_bubble = None

    def _on_ptt_press(self, event=None):
        """Start recording when PTT button is pressed."""
        if self._ptt_recording:
            return
        self._ptt_recording = True
        self.ptt_btn.configure(bg="#ff4444")  # Red while recording
        # Show recording indicator in chat
        self._show_ptt_indicator()
        self.ptt.start_recording()

    def _on_ptt_release(self, event=None):
        """Stop recording when PTT button is released."""
        if not self._ptt_recording:
            return
        self._ptt_recording = False
        self.ptt_btn.configure(bg=COLORS["bg_input"])  # Back to normal
        # Remove recording indicator
        self._hide_ptt_indicator()
        self.ptt.stop_recording()

    def _show_ptt_indicator(self):
        """Show a 'Recording...' indicator in the chat area."""
        try:
            self._hide_ptt_indicator()  # Remove any existing
            self._ptt_indicator_bubble = tk.Frame(self.messages_frame, bg="#ff4444", padx=12, pady=6)
            lbl = tk.Label(
                self._ptt_indicator_bubble,
                text="\u23fa Recording...",
                bg="#ff4444", fg="white",
                font=("Ubuntu", 10, "bold"),
            )
            lbl.pack()
            self._ptt_indicator_bubble.pack(fill="x", pady=(4, 4))
            self.messages_frame.update_idletasks()
            self.chat_canvas.configure(scrollregion=self.chat_canvas.bbox("all"))
            self.chat_canvas.yview_moveto(1.0)
        except Exception as e:
            LOG.debug(f"PTT indicator show error: {e}")

    def _hide_ptt_indicator(self):
        """Remove the recording indicator."""
        try:
            if self._ptt_indicator_bubble:
                self._ptt_indicator_bubble.destroy()
                self._ptt_indicator_bubble = None
        except Exception:
            self._ptt_indicator_bubble = None

    def _on_ptt_error(self, error_msg: str):
        """Handle PTT transcription errors — show feedback to user."""
        LOG.warning(f"PTT error: {error_msg}")
        self.after(0, lambda m=error_msg: self._add_message("Frank", m, is_system=True))

    def _on_ptt_result(self, text: str):
        """Handle transcribed text from PTT — show in chat and process with voice response."""
        if not text:
            return
        LOG.info(f"PTT: Transcribed speech: '{text}'")
        # Run on main thread: show user message + process as voice input
        self.after(0, lambda t=text: self._ptt_process(t))

    def _ptt_process(self, text: str):
        """Route transcribed voice text through the full command router.

        This ensures ALL features (file search, web search, emails, calendar,
        todos, notes, system control, etc.) work identically via PTT as they
        do when typed. The command router handles display and dispatch.
        """
        LOG.info(f"PTT: Processing voice input: '{text}'")
        self._thinking_cancelled = False  # Reset cancel flag for new request
        # Route through the full command dispatcher — same as typed input
        self._route_message(text)
