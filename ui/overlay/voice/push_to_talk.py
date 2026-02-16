"""PushToTalk class extracted from the monolith overlay."""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import threading
import urllib.error
import urllib.request
import wave
from typing import Callable

from overlay.constants import LOG

# Whisper hallucination patterns — these are artifacts, not real speech
_HALLUCINATION_RE = re.compile(
    r"^\s*[\[\(]?\s*("
    r"musik|music|applaus|applause|gelächter|laughter|stille|silence|"
    r"klopfen|knocking|gespräch|rauschen|noise|wind|husten|cough|"
    r"lacht|laughs|seufzt|sighs|weint|cries|singt|sings|pfeift|whistles"
    r")\s*[\]\)]?\s*$",
    re.IGNORECASE,
)
_FILLER_RE = re.compile(
    r"^\s*(\.+|,+|!+|\?+|-+|–+|\.{2,}|…+)\s*$"
)


class PushToTalk:
    """Push-to-talk voice input using whisper.cpp GPU server."""

    WHISPER_URL = "http://127.0.0.1:8103/inference"
    SAMPLE_RATE = 16000

    def __init__(self, callback: Callable[[str], None], error_callback: Callable[[str], None] = None):
        """
        Initialize PTT.
        callback: Function to call with transcribed text.
        error_callback: Function to call with error message on failure.
        """
        self.callback = callback
        self.error_callback = error_callback
        self.recording = False
        self.record_process = None
        self.temp_file = None
        self._detect_mic()

    def _detect_mic(self):
        """Use the system default microphone (pactl get-default-source)."""
        self.mic_device = None
        try:
            result = subprocess.run(
                ["pactl", "get-default-source"],
                capture_output=True, text=True, timeout=5
            )
            default = result.stdout.strip()
            if default and "monitor" not in default.lower():
                self.mic_device = default
                LOG.info(f"PTT: Using system default mic: {self.mic_device}")
            else:
                LOG.warning(f"PTT: Default source is a monitor ({default}), using no --device flag")
        except Exception as e:
            LOG.error(f"PTT: Mic detection failed: {e}")

    def start_recording(self):
        """Start recording audio."""
        if self.recording:
            return

        self.recording = True
        self.temp_file = tempfile.NamedTemporaryFile(suffix=".raw", delete=False)
        self.temp_file.close()

        cmd = [
            "parecord", "--raw",
            f"--rate={self.SAMPLE_RATE}",
            "--channels=1",
            "--format=s16le",
        ]
        if self.mic_device:
            cmd.append(f"--device={self.mic_device}")
        cmd.append(self.temp_file.name)

        LOG.info("PTT: Recording started")
        self.record_process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def stop_recording(self):
        """Stop recording and transcribe."""
        if not self.recording:
            return

        self.recording = False

        if self.record_process:
            self.record_process.terminate()
            try:
                self.record_process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.record_process.kill()
            self.record_process = None

        LOG.info("PTT: Recording stopped, transcribing...")

        # Convert raw to WAV and transcribe in background
        threading.Thread(target=self._transcribe, daemon=True).start()

    def _transcribe(self):
        """Convert raw audio to WAV and send to Whisper server.
        Uses try/finally to ensure temp file cleanup (HIGH #7 fix).
        """
        raw_path = None
        wav_path = None
        try:
            raw_path = self.temp_file.name
            wav_path = raw_path.replace(".raw", ".wav")

            # Check if we have audio data
            raw_size = os.path.getsize(raw_path)
            if raw_size < 1000:
                LOG.warning("PTT: Recording too short")
                return

            # Convert raw to WAV with audio preprocessing
            with open(raw_path, 'rb') as rf:
                raw_data = rf.read()

            # Preprocess: normalize + noise gate for cleaner Whisper input
            try:
                import struct
                samples = list(struct.unpack(f'{len(raw_data)//2}h', raw_data))
                peak = max(abs(s) for s in samples) if samples else 0

                # Noise gate: silence samples below threshold (kills background hum)
                noise_floor = 300
                samples = [s if abs(s) > noise_floor else 0 for s in samples]

                # Normalize to ~80% of max range for consistent Whisper input levels
                if peak > 0:
                    target = int(32767 * 0.8)
                    factor = target / peak
                    if factor > 1.05:  # Only boost, don't reduce loud audio
                        samples = [max(-32767, min(32767, int(s * factor))) for s in samples]

                raw_data = struct.pack(f'{len(samples)}h', *samples)
                LOG.debug(f"PTT: Audio preprocessed: peak={peak}, noise_floor={noise_floor}")
            except Exception as pp_err:
                LOG.debug(f"PTT: Audio preprocessing skipped: {pp_err}")

            with wave.open(wav_path, 'wb') as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(self.SAMPLE_RATE)
                wf.writeframes(raw_data)

            # Send to Whisper server
            with open(wav_path, 'rb') as f:
                wav_data = f.read()

            boundary = '----PTTBoundary'
            body = []
            body.append(f'--{boundary}'.encode())
            body.append(b'Content-Disposition: form-data; name="file"; filename="audio.wav"')
            body.append(b'Content-Type: audio/wav')
            body.append(b'')
            body.append(wav_data)
            body.append(f'--{boundary}'.encode())
            body.append(b'Content-Disposition: form-data; name="language"')
            body.append(b'')
            body.append(b'auto')
            body.append(f'--{boundary}'.encode())
            body.append(b'Content-Disposition: form-data; name="temperature"')
            body.append(b'')
            body.append(b'0.0')
            body.append(f'--{boundary}--'.encode())
            body.append(b'')

            body_bytes = b'\r\n'.join(body)

            req = urllib.request.Request(
                self.WHISPER_URL,
                data=body_bytes,
                headers={'Content-Type': f'multipart/form-data; boundary={boundary}'}
            )

            with urllib.request.urlopen(req, timeout=30) as resp:
                result = json.loads(resp.read().decode('utf-8'))

            text = result.get("text", "").strip()

            if not text:
                LOG.warning("PTT: No speech detected")
                return

            # Filter Whisper hallucinations
            if _HALLUCINATION_RE.match(text) or _FILLER_RE.match(text):
                LOG.info(f"PTT: Filtered hallucination: '{text}'")
                return

            # Filter too-short or punctuation-only
            clean = re.sub(r"[^\w\s]", "", text).strip()
            if len(clean) < 2:
                LOG.info(f"PTT: Filtered too short: '{text}'")
                return

            LOG.info(f"PTT: Transcribed: '{text}'")
            self.callback(text)

        except urllib.error.URLError as e:
            LOG.error(f"PTT: Whisper server connection error: {e}")
            if self.error_callback:
                self.error_callback("Speech recognition unreachable. Whisper server is not running.")
        except json.JSONDecodeError as e:
            LOG.error(f"PTT: Invalid response from Whisper server: {e}")
            if self.error_callback:
                self.error_callback("Speech recognition: Invalid response from server.")
        except OSError as e:
            LOG.error(f"PTT: File operation error: {e}")
            if self.error_callback:
                self.error_callback("Speech recognition: File error.")
        except Exception as e:
            LOG.error(f"PTT: Transcription error: {e}")
            if self.error_callback:
                self.error_callback(f"Speech recognition failed: {e}")
        finally:
            # Cleanup temp files (HIGH #7 fix - prevent file handle leaks)
            if raw_path and os.path.exists(raw_path):
                try:
                    os.unlink(raw_path)
                except OSError as e:
                    LOG.debug(f"PTT: Could not remove raw file: {e}")
            if wav_path and os.path.exists(wav_path):
                try:
                    os.unlink(wav_path)
                except OSError as e:
                    LOG.debug(f"PTT: Could not remove wav file: {e}")
