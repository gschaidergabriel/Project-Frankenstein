#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Frank Voice Daemon

Provides voice interaction with Frank:
- Wake word detection ("Hey Frank")
- Speech-to-Text with whisper.cpp (GPU via Vulkan)
- Text-to-Speech with Piper (German male voice - Thorsten)
- Auto-detection of audio devices (PipeWire/PulseAudio)
- Integration with Frank chat overlay

Usage:
    python voice_daemon.py [--daemon]
"""

import os
import sys
import time
import json
import wave
import struct
import logging
import tempfile
import threading
import subprocess
import urllib.request
import urllib.error
from pathlib import Path
from typing import Optional, Tuple, List, Dict
from dataclasses import dataclass

import numpy as np

# Logging
LOG_FILE = Path('/tmp/frank_voice.log')
logging.basicConfig(
    level=logging.DEBUG,
    format='[%(asctime)s] %(levelname)s: %(message)s',
    handlers=[
        logging.StreamHandler(sys.stderr),
        logging.FileHandler(LOG_FILE)
    ]
)
LOG = logging.getLogger("frank_voice")
# Reduce noise from other loggers
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)

# Configuration
CONFIG = {
    # Wake word settings - multiple variations Whisper might output
    "wake_words": [
        "hallo frank", "hallo, frank", "hallo fränk", "hallo frank,",
        "hi frank", "hi, frank", "hi frank,",
        "hello frank", "hello, frank",
        "hey frank", "hey, frank",
        "halo frank", "hallo fronk", "hi fronk",
        "na frank", "ja frank", "ey frank",
        "hallo, fran", "hallo fran", "hi fran",
    ],

    # Audio settings
    "sample_rate": 16000,
    "channels": 1,
    "silence_threshold": 0.02,  # RMS threshold for silence (normalized)
    "silence_duration": 1.5,  # seconds of silence to stop recording
    "max_recording_duration": 30,  # max seconds to record
    "min_recording_duration": 0.5,  # min seconds for valid recording

    # Voice Activity Detection (VAD)
    "vad_energy_threshold": 0.03,  # Minimum RMS energy to consider as speech
    "vad_min_speech_frames": 2,  # Minimum frames with speech to trigger transcription

    # Hallucination filter - only clear Whisper artifacts
    "hallucination_patterns": [
        "[musik]", "(musik)", "[applaus]", "(applaus)",
        "[gelächter]", "(gelächter)", "[stille]", "(stille)",
        "[klopfen]", "(klopfen)", "[gespräch]", "(gespräch)",
        "* musik *", "*musik*", "* klopfen *", "*klopfen*",
        "danke fürs zuschauen", "thanks for watching",
        "untertitel von", "subtitles by", "copyright",
    ],

    # Whisper settings (GPU server)
    "whisper_server_url": "http://127.0.0.1:8103/inference",
    "whisper_language": "de",

    # Piper TTS settings
    "piper_path": str(Path.home() / ".local/bin/piper"),
    "piper_voice": str(Path.home() / ".local/share/frank/voices/de_DE-thorsten-high.onnx"),

    # Frank API
    "frank_api_url": "http://127.0.0.1:8088/chat",

    # IPC with chat overlay
    "voice_event_file": "/tmp/frank_voice_event.json",

    # Device preferences (keywords to look for)
    "preferred_mic_keywords": ["rode", "nt-usb", "usb"],
    "preferred_speaker_keywords": ["bluez", "bluetooth"],
}


@dataclass
class AudioDevice:
    """Represents a PulseAudio/PipeWire device."""
    id: str
    name: str
    driver: str
    sample_spec: str
    state: str
    is_bluetooth: bool = False


class PulseAudioManager:
    """Manages audio devices via PulseAudio/PipeWire."""

    def __init__(self):
        self.input_device: Optional[str] = None
        self.output_device: Optional[str] = None
        self._detect_devices()

    def _run_pactl(self, *args) -> str:
        """Run pactl command and return output."""
        try:
            result = subprocess.run(
                ["pactl"] + list(args),
                capture_output=True, text=True, timeout=5
            )
            return result.stdout
        except Exception as e:
            LOG.error(f"pactl error: {e}")
            return ""

    def _detect_devices(self):
        """Auto-detect best audio devices."""
        LOG.info("Detecting audio devices...")

        # Get sinks (output devices)
        sinks_output = self._run_pactl("list", "sinks", "short")
        best_output = None

        for line in sinks_output.strip().split('\n'):
            if not line:
                continue
            parts = line.split('\t')
            if len(parts) >= 2:
                sink_id, sink_name = parts[0], parts[1]
                name_lower = sink_name.lower()

                # Prefer Bluetooth
                for keyword in CONFIG["preferred_speaker_keywords"]:
                    if keyword in name_lower:
                        best_output = sink_name
                        LOG.info(f"Found preferred speaker: {sink_name}")
                        break

                if best_output:
                    break
                elif best_output is None and "monitor" not in name_lower:
                    best_output = sink_name

        # Get sources (input devices)
        sources_output = self._run_pactl("list", "sources", "short")
        best_input = None

        for line in sources_output.strip().split('\n'):
            if not line:
                continue
            parts = line.split('\t')
            if len(parts) >= 2:
                source_id, source_name = parts[0], parts[1]
                name_lower = source_name.lower()

                # Skip monitor sources
                if "monitor" in name_lower:
                    continue

                # Prefer USB mics (especially RODE)
                for keyword in CONFIG["preferred_mic_keywords"]:
                    if keyword in name_lower:
                        best_input = source_name
                        LOG.info(f"Found preferred mic: {source_name}")
                        break

                if best_input:
                    break
                elif best_input is None:
                    best_input = source_name

        self.input_device = best_input
        self.output_device = best_output

        LOG.info(f"Selected input: {self.input_device}")
        LOG.info(f"Selected output: {self.output_device}")

    def refresh_devices(self):
        """Refresh device detection (call when devices change)."""
        self._detect_devices()

    def record_audio(self, duration: float, output_file: str) -> bool:
        """Record audio using parecord and convert to WAV."""
        try:
            # Refresh devices in case they changed
            if not self.input_device:
                self._detect_devices()

            # Record raw PCM first (more reliable)
            raw_file = output_file + ".raw"

            cmd = [
                "parecord",
                "--raw",
                f"--rate={CONFIG['sample_rate']}",
                f"--channels={CONFIG['channels']}",
                "--format=s16le",
            ]

            if self.input_device:
                cmd.append(f"--device={self.input_device}")

            cmd.append(raw_file)

            LOG.debug(f"Recording command: {' '.join(cmd)}")

            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            time.sleep(duration + 0.3)
            proc.terminate()

            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()

            # Check raw file and convert to WAV
            if Path(raw_file).exists():
                raw_size = Path(raw_file).stat().st_size
                LOG.debug(f"Raw file size: {raw_size} bytes")

                if raw_size > 1000:
                    # Convert raw PCM to WAV
                    self._raw_to_wav(raw_file, output_file)
                    Path(raw_file).unlink()

                    if Path(output_file).exists():
                        wav_size = Path(output_file).stat().st_size
                        LOG.debug(f"WAV file size: {wav_size} bytes")
                        return wav_size > 100

                # Clean up raw file if conversion failed
                try:
                    Path(raw_file).unlink()
                except:
                    pass

            return False

        except Exception as e:
            LOG.error(f"Recording error: {e}")
            return False

    def _raw_to_wav(self, raw_file: str, wav_file: str):
        """Convert raw PCM to WAV format."""
        import wave

        with open(raw_file, 'rb') as rf:
            raw_data = rf.read()

        with wave.open(wav_file, 'wb') as wf:
            wf.setnchannels(CONFIG['channels'])
            wf.setsampwidth(2)  # 16-bit = 2 bytes
            wf.setframerate(CONFIG['sample_rate'])
            wf.writeframes(raw_data)

    def play_audio(self, wav_file: str) -> bool:
        """Play audio using paplay."""
        try:
            cmd = ["paplay"]

            if self.output_device:
                cmd.append(f"--device={self.output_device}")

            cmd.append(wav_file)

            result = subprocess.run(cmd, capture_output=True, timeout=60)
            return result.returncode == 0

        except Exception as e:
            LOG.error(f"Playback error: {e}")
            return False


def fuzzy_wake_word_match(text: str, wake_words: list) -> Tuple[bool, str, str]:
    """
    Fuzzy match for wake words - handles Whisper transcription variations.
    Returns (matched, matched_word, remaining_text).
    """
    text_lower = text.lower().strip()
    text_clean = text_lower.lstrip(".,!?-–„\"' ")

    # Direct prefix match first
    for wake_word in wake_words:
        if text_clean.startswith(wake_word):
            remaining = text_clean[len(wake_word):].strip(" .,!?-–")
            return True, wake_word, remaining

    # Check for frank/franklin within first 3 words with greeting-like prefix
    words = text_clean.replace(",", " ").replace(".", " ").split()
    if len(words) >= 2:
        # Greetings that could precede "Frank"
        greetings = ["hallo", "hello", "hi", "hey", "halo", "allo", "na", "ja", "ey", "eh"]
        # Names that Whisper might output instead of "Frank"
        frank_variants = ["frank", "fran", "franklin", "fronk", "fränk", "franc"]

        # Check first word is greeting
        first_word = words[0].strip(".,!?")
        if first_word in greetings:
            # Check if frank variant appears in words 1-3
            for i in range(1, min(4, len(words))):
                word = words[i].strip(".,!?").lower()
                for variant in frank_variants:
                    if variant in word:
                        remaining = " ".join(words[i+1:]).strip()
                        matched = f"{first_word} {words[i]}"
                        return True, matched, remaining

    return False, "", ""


def check_audio_energy(wav_file: str) -> Tuple[bool, float]:
    """
    Check if audio file has sufficient energy to be speech.
    Returns (has_speech, energy_level).
    """
    try:
        with wave.open(wav_file, 'rb') as wf:
            frames = wf.readframes(wf.getnframes())
            audio = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0

        # Calculate RMS energy
        rms = np.sqrt(np.mean(audio ** 2))

        # Count frames above threshold
        frame_size = CONFIG["sample_rate"] // 10  # 100ms frames
        speech_frames = 0
        for i in range(0, len(audio) - frame_size, frame_size):
            frame = audio[i:i + frame_size]
            frame_rms = np.sqrt(np.mean(frame ** 2))
            if frame_rms > CONFIG["vad_energy_threshold"]:
                speech_frames += 1

        has_speech = speech_frames >= CONFIG["vad_min_speech_frames"]
        LOG.debug(f"Audio energy: RMS={rms:.4f}, speech_frames={speech_frames}, has_speech={has_speech}")
        return has_speech, rms

    except Exception as e:
        LOG.error(f"Audio energy check error: {e}")
        return True, 0.0  # Default to True on error


def is_hallucination(text: str) -> bool:
    """Check if transcription is likely a Whisper hallucination."""
    if not text:
        return True

    text_lower = text.lower().strip()

    # Check against known hallucination patterns
    for pattern in CONFIG["hallucination_patterns"]:
        if pattern in text_lower:
            LOG.debug(f"Filtered hallucination: '{text}' (matched: {pattern})")
            return True

    # Too short (single character or just punctuation)
    clean_text = ''.join(c for c in text if c.isalnum() or c.isspace())
    if len(clean_text.strip()) < 3:
        LOG.debug(f"Filtered too short: '{text}'")
        return True

    # Only non-speech markers like [...]
    if text.startswith('[') and text.endswith(']'):
        LOG.debug(f"Filtered marker: '{text}'")
        return True
    if text.startswith('(') and text.endswith(')'):
        LOG.debug(f"Filtered marker: '{text}'")
        return True

    return False


class SpeechToText:
    """Handles speech-to-text with whisper.cpp server (GPU via Vulkan)."""

    def __init__(self):
        self.server_url = CONFIG["whisper_server_url"]
        LOG.info(f"Using whisper.cpp GPU server at {self.server_url}")

        # Check if server is available
        try:
            req = urllib.request.Request(
                "http://127.0.0.1:8103/",
                method="GET"
            )
            with urllib.request.urlopen(req, timeout=2) as resp:
                LOG.info("Whisper GPU server is ready")
        except Exception as e:
            LOG.warning(f"Whisper GPU server not responding: {e}")

    def transcribe_file(self, wav_file: str) -> str:
        """Transcribe a WAV file to text using whisper.cpp server."""
        try:
            import mimetypes

            # Read the WAV file
            with open(wav_file, 'rb') as f:
                wav_data = f.read()

            # Create multipart form data
            boundary = '----WebKitFormBoundary7MA4YWxkTrZu0gW'

            body = []
            # Add file field
            body.append(f'--{boundary}'.encode())
            body.append(f'Content-Disposition: form-data; name="file"; filename="{Path(wav_file).name}"'.encode())
            body.append(b'Content-Type: audio/wav')
            body.append(b'')
            body.append(wav_data)

            # Add language field
            body.append(f'--{boundary}'.encode())
            body.append(f'Content-Disposition: form-data; name="language"'.encode())
            body.append(b'')
            body.append(CONFIG["whisper_language"].encode())

            # Add temperature field (for better accuracy)
            body.append(f'--{boundary}'.encode())
            body.append(f'Content-Disposition: form-data; name="temperature"'.encode())
            body.append(b'')
            body.append(b'0.0')

            # Close boundary
            body.append(f'--{boundary}--'.encode())
            body.append(b'')

            body_bytes = b'\r\n'.join(body)

            # Make request
            req = urllib.request.Request(
                self.server_url,
                data=body_bytes,
                headers={
                    'Content-Type': f'multipart/form-data; boundary={boundary}',
                }
            )

            with urllib.request.urlopen(req, timeout=30) as resp:
                result = json.loads(resp.read().decode('utf-8'))

            text = result.get("text", "").strip()
            LOG.debug(f"Whisper GPU transcribed: '{text}'")
            return text

        except urllib.error.URLError as e:
            LOG.error(f"Whisper server connection error: {e}")
            return ""
        except Exception as e:
            LOG.error(f"Transcription error: {e}")
            return ""

    def transcribe_array(self, audio_data: np.ndarray) -> str:
        """Transcribe a numpy array to text by saving to temp file."""
        try:
            # Save array to temp WAV file
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                temp_path = f.name

            # Write WAV file
            with wave.open(temp_path, 'wb') as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(CONFIG['sample_rate'])
                # Convert float32 to int16 if needed
                if audio_data.dtype == np.float32:
                    audio_data = (audio_data * 32767).astype(np.int16)
                wf.writeframes(audio_data.tobytes())

            # Transcribe via server
            text = self.transcribe_file(temp_path)

            # Cleanup
            try:
                os.unlink(temp_path)
            except:
                pass

            return text

        except Exception as e:
            LOG.error(f"Transcription error: {e}")
            return ""


class TextToSpeech:
    """Handles text-to-speech with Piper."""

    def __init__(self, audio_manager: PulseAudioManager):
        self.audio_manager = audio_manager
        self.piper_path = CONFIG["piper_path"]
        self.voice_model = CONFIG["piper_voice"]

        # Check if piper and voice exist
        if not Path(self.piper_path).exists():
            raise FileNotFoundError(f"Piper not found: {self.piper_path}")
        if not Path(self.voice_model).exists():
            raise FileNotFoundError(f"Voice model not found: {self.voice_model}")

        LOG.info(f"TTS ready with voice: {Path(self.voice_model).name}")

    def speak(self, text: str) -> bool:
        """Convert text to speech and play it."""
        if not text.strip():
            return False

        LOG.info(f"Speaking: {text[:50]}...")

        try:
            # Generate speech with Piper
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                wav_path = f.name

            # Run piper
            cmd = [
                self.piper_path,
                "--model", self.voice_model,
                "--output_file", wav_path
            ]

            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            proc.communicate(input=text.encode('utf-8'), timeout=30)

            # Play the audio
            if Path(wav_path).exists() and Path(wav_path).stat().st_size > 100:
                success = self.audio_manager.play_audio(wav_path)
                os.unlink(wav_path)
                return success

            return False

        except Exception as e:
            LOG.error(f"TTS error: {e}")
            # Fallback to espeak
            try:
                subprocess.run(
                    ["espeak", "-v", "de", text],
                    capture_output=True,
                    timeout=30
                )
                return True
            except:
                return False


class FrankAPI:
    """Interface to Frank's chat API."""

    # Frank's capabilities context
    CAPABILITIES = """You are Frank, a helpful local AI assistant with voice control.
You can do the following:
- Launch Steam games: e.g. "Start Dota 2" or "Open Counter-Strike"
- List Steam games: "What games do I have?"
- Close games: "Close the game"
- Take screenshots and describe the desktop
- Show files and folders
- Answer general questions

Answer briefly and naturally. You are speaking to the user via voice."""

    def __init__(self):
        self.api_url = CONFIG["frank_api_url"]

    def chat(self, message: str) -> str:
        """Send message to Frank and get response."""
        try:
            # Add capabilities context for voice interactions
            full_message = f"[System: {self.CAPABILITIES}]\n\nUser says: {message}"

            data = json.dumps({
                "text": full_message,
                "max_tokens": 300,
                "task": "chat.fast",
                "force": "llama"
            }).encode('utf-8')

            req = urllib.request.Request(
                self.api_url,
                data=data,
                headers={"Content-Type": "application/json"}
            )

            with urllib.request.urlopen(req, timeout=60) as resp:
                result = json.loads(resp.read().decode('utf-8'))

            if result.get("ok"):
                return result.get("text", "").strip()
            else:
                return "Entschuldigung, ich konnte das nicht verarbeiten."

        except Exception as e:
            LOG.error(f"Frank API error: {e}")
            return "Entschuldigung, ich bin gerade nicht erreichbar."


class VoiceEventBroadcaster:
    """Broadcasts voice events to the chat overlay."""

    def __init__(self):
        self.event_file = Path(CONFIG["voice_event_file"])
        self.outbox_file = Path("/tmp/frank_voice_outbox.json")
        self._session_counter = 0

    def broadcast(self, event_type: str, data: dict):
        """Broadcast an event to the chat overlay."""
        event = {
            "type": event_type,
            "timestamp": time.time(),
            **data
        }
        try:
            self.event_file.write_text(json.dumps(event))
            LOG.info(f"📡 Event broadcast: {event_type} - {data.get('text', '')[:30] if data.get('text') else ''}")
        except Exception as e:
            LOG.error(f"Broadcast error: {e}")

    def voice_input(self, text: str) -> str:
        """
        Send voice input to Overlay for processing (Option A).
        Returns a unique session ID for tracking the response.
        """
        self._session_counter += 1
        session_id = f"voice_{int(time.time())}_{self._session_counter}"
        self.broadcast("voice_input", {
            "text": text,
            "session_id": session_id,
            "source": "voice"
        })
        return session_id

    def wait_for_response(self, session_id: str, timeout: float = 60.0) -> Optional[str]:
        """
        Wait for Overlay response in Outbox (Option A).
        Returns the response text or None on timeout.
        """
        start_time = time.time()
        last_ts = 0.0

        while (time.time() - start_time) < timeout:
            try:
                if self.outbox_file.exists():
                    data = json.loads(self.outbox_file.read_text())
                    ts = data.get("timestamp", 0)

                    # Check if this is a new response for our session
                    if ts > last_ts:
                        last_ts = ts
                        resp_session = data.get("session_id", "")
                        if resp_session == session_id or not resp_session:
                            text = data.get("text", "")
                            if text:
                                LOG.info(f"📥 Outbox response: '{text[:50]}...'")
                                return text
            except (json.JSONDecodeError, IOError) as e:
                LOG.debug(f"Outbox read error: {e}")

            time.sleep(0.1)

        LOG.warning(f"Timeout waiting for response (session={session_id})")
        return None

    def user_speaking(self, text: str):
        self.broadcast("user_message", {"text": text, "source": "voice"})

    def frank_speaking(self, text: str):
        self.broadcast("frank_message", {"text": text, "source": "voice"})

    def listening(self):
        self.broadcast("listening", {})

    def processing(self):
        self.broadcast("processing", {})

    def wake_word_detected(self):
        self.broadcast("wake_word", {})


class VoiceDaemon:
    """Main voice daemon that coordinates everything."""

    def __init__(self):
        LOG.info("=" * 50)
        LOG.info("Initializing Frank Voice Daemon...")

        # Components
        self.audio_manager = PulseAudioManager()
        self.stt = SpeechToText()
        self.tts = TextToSpeech(self.audio_manager)
        self.frank_api = FrankAPI()
        self.broadcaster = VoiceEventBroadcaster()

        # State
        self.running = False
        self.is_speaking = False

        LOG.info("Voice Daemon initialized successfully")
        LOG.info("=" * 50)

    def _check_for_wake_word(self, text: str) -> Tuple[bool, str]:
        """Check if text STARTS with wake word and return remaining text."""
        if not text:
            return False, ""

        # Use fuzzy matching
        matched, wake_word, remaining = fuzzy_wake_word_match(text, CONFIG["wake_words"])

        if matched:
            LOG.info(f"Wake word '{wake_word}' detected in: '{text}'")
            return True, remaining

        return False, ""

    def _record_command(self) -> Optional[str]:
        """Record audio until silence and return transcribed text."""
        LOG.info("Recording command...")
        self.broadcaster.listening()

        try:
            # Record in shorter chunks for better responsiveness
            all_text = ""
            silence_count = 0
            max_silence = 2  # Stop after 2 silent chunks (more responsive)
            speech_started = False

            for i in range(10):  # Max 10 chunks of 3 seconds = 30 seconds
                chunk_file = f"/tmp/frank_chunk_{i}.wav"

                if self.audio_manager.record_audio(3.0, chunk_file):
                    chunk_text = self.stt.transcribe_file(chunk_file)

                    if chunk_text and chunk_text.strip():
                        all_text += " " + chunk_text
                        silence_count = 0
                        speech_started = True
                        LOG.info(f"Chunk {i}: '{chunk_text}'")
                    else:
                        silence_count += 1
                        LOG.info(f"Chunk {i}: silence ({silence_count}/{max_silence})")

                    # Clean up chunk file
                    try:
                        os.unlink(chunk_file)
                    except:
                        pass

                    # If we got speech and then silence, user is done
                    if speech_started and silence_count >= 1:
                        LOG.info("User finished speaking")
                        break

                    # If no speech at all after several chunks, give up
                    if not speech_started and silence_count >= max_silence:
                        LOG.info("No speech detected after multiple chunks")
                        break

            return all_text.strip() if all_text else None

        except Exception as e:
            LOG.error(f"Recording error: {e}")
            return None

    def _listen_for_wake_word(self) -> Tuple[bool, str]:
        """Listen for wake word. Returns (detected, extra_text)."""
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            wav_path = f.name

        try:
            # Record chunk for wake word detection
            if self.audio_manager.record_audio(2.0, wav_path):
                # OPTIMIZATION 1: Check audio energy before expensive transcription
                has_speech, energy = check_audio_energy(wav_path)

                if not has_speech:
                    # No significant audio - skip transcription entirely
                    LOG.debug(f"Silence detected (energy={energy:.4f}), skipping transcription")
                    return False, ""

                # Transcribe only if there's actual audio
                LOG.debug(f"Speech detected (energy={energy:.4f}), transcribing...")
                text = self.stt.transcribe_file(wav_path)

                if text:
                    # OPTIMIZATION 2: Filter hallucinations
                    if is_hallucination(text):
                        LOG.debug(f"Hallucination filtered: '{text}'")
                        return False, ""

                    LOG.info(f"Heard: '{text}'")
                    detected, remaining = self._check_for_wake_word(text)
                    return detected, remaining
                else:
                    LOG.debug("Whisper returned empty")
            else:
                LOG.warning("Recording failed")

            return False, ""

        except Exception as e:
            LOG.error(f"Wake word detection error: {e}")
            return False, ""
        finally:
            try:
                os.unlink(wav_path)
            except:
                pass

    def _process_command(self, initial_text: str = ""):
        """Process a voice command after wake word detection."""
        self.broadcaster.wake_word_detected()
        LOG.info(f"Processing command. Initial text: '{initial_text}'")

        try:
            # If we already have text with the wake word, use it
            if initial_text and len(initial_text) > 3:
                user_text = initial_text
            else:
                # Acknowledge and record more
                self.is_speaking = True
                self.tts.speak("Ja?")
                self.is_speaking = False

                # Small delay to avoid picking up own TTS
                time.sleep(0.3)

                # Record the full command
                user_text = self._record_command()

            if not user_text or len(user_text.strip()) < 2:
                LOG.info("No command detected")
                self.broadcaster.broadcast("idle", {})  # Clear typing indicator
                self.is_speaking = True
                self.tts.speak("Ich habe dich nicht verstanden.")
                self.is_speaking = False
                return

            LOG.info(f"User command: '{user_text}'")
            self.broadcaster.processing()

            # Option A: Send to Overlay for full pipeline processing
            # This enables all tool integrations (Steam, Screenshot, FS, etc.)
            LOG.info("🎤 Voice -> Overlay (Option A)")
            session_id = self.broadcaster.voice_input(user_text)

            # Wait for Overlay response
            response = self.broadcaster.wait_for_response(session_id, timeout=60.0)

            if not response:
                # Fallback to direct Core API if Overlay doesn't respond
                LOG.warning("Overlay timeout, falling back to direct Core API")
                response = self.frank_api.chat(user_text)

            LOG.info(f"Frank response: '{response[:100]}...'")

            # Speak the response
            self.is_speaking = True
            self.tts.speak(response)
            self.is_speaking = False

        finally:
            # Always clear the typing indicator
            self.broadcaster.broadcast("idle", {})

    def run(self):
        """Main daemon loop."""
        LOG.info("=" * 50)
        LOG.info("Frank Voice Daemon starting main loop...")
        LOG.info("Say 'Hallo Frank' or 'Hi Frank' to start a conversation")
        LOG.info("=" * 50)

        self.running = True

        # Initial greeting
        self.tts.speak("Hallo! Ich bin Frank. Sag Hallo Frank oder Hi Frank, um mit mir zu sprechen.")

        while self.running:
            try:
                # Skip if we're currently speaking
                if self.is_speaking:
                    time.sleep(0.1)
                    continue

                # Listen for wake word
                detected, extra_text = self._listen_for_wake_word()

                if detected:
                    LOG.info(f"Wake word detected! Extra text: '{extra_text}'")
                    self._process_command(extra_text)
                    LOG.info("Listening for wake word again...")

            except KeyboardInterrupt:
                LOG.info("Interrupted by user")
                break
            except Exception as e:
                LOG.error(f"Error in main loop: {e}")
                time.sleep(1)

        LOG.info("Voice Daemon stopped")

    def stop(self):
        """Stop the daemon."""
        self.running = False


def test_tts(text: str):
    """Test TTS functionality."""
    print(f"Testing TTS with: '{text}'")
    audio_mgr = PulseAudioManager()
    tts = TextToSpeech(audio_mgr)
    success = tts.speak(text)
    print(f"TTS {'succeeded' if success else 'failed'}")


def test_stt():
    """Test STT functionality."""
    print("Testing STT - Recording for 5 seconds...")
    audio_mgr = PulseAudioManager()
    stt = SpeechToText()

    wav_file = "/tmp/frank_stt_test.wav"
    if audio_mgr.record_audio(5.0, wav_file):
        text = stt.transcribe_file(wav_file)
        print(f"Transcribed: '{text}'")
        os.unlink(wav_file)
    else:
        print("Recording failed")


def test_full():
    """Test full voice pipeline."""
    print("Testing full voice pipeline...")
    print("Say something after the beep...")

    audio_mgr = PulseAudioManager()
    stt = SpeechToText()
    tts = TextToSpeech(audio_mgr)
    frank = FrankAPI()

    # Record
    tts.speak("Ich höre.")

    wav_file = "/tmp/frank_full_test.wav"
    if audio_mgr.record_audio(5.0, wav_file):
        # Transcribe
        text = stt.transcribe_file(wav_file)
        print(f"You said: '{text}'")
        os.unlink(wav_file)

        if text:
            # Get response
            response = frank.chat(text)
            print(f"Frank: '{response}'")

            # Speak
            tts.speak(response)
    else:
        print("Recording failed")


def list_devices():
    """List audio devices."""
    print("Audio Devices:")
    print("\nSinks (Output):")
    result = subprocess.run(["pactl", "list", "sinks", "short"], capture_output=True, text=True)
    for line in result.stdout.strip().split('\n'):
        if line:
            print(f"  {line}")

    print("\nSources (Input):")
    result = subprocess.run(["pactl", "list", "sources", "short"], capture_output=True, text=True)
    for line in result.stdout.strip().split('\n'):
        if line and "monitor" not in line.lower():
            print(f"  {line}")


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Frank Voice Daemon")
    parser.add_argument("--test-tts", metavar="TEXT", help="Test TTS with given text")
    parser.add_argument("--test-stt", action="store_true", help="Test STT (record 5 seconds)")
    parser.add_argument("--test-full", action="store_true", help="Test full pipeline")
    parser.add_argument("--list-devices", action="store_true", help="List audio devices")
    parser.add_argument("--daemon", action="store_true", help="Run as daemon")
    args = parser.parse_args()

    if args.list_devices:
        list_devices()
        return

    if args.test_tts:
        test_tts(args.test_tts)
        return

    if args.test_stt:
        test_stt()
        return

    if args.test_full:
        test_full()
        return

    # Run daemon
    daemon = VoiceDaemon()
    daemon.run()


if __name__ == "__main__":
    main()
