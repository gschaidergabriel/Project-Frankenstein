#!/usr/bin/env python3
"""
ADI Sound Manager - Audio feedback for the ADI popup.

Provides cyberpunk-styled sound effects for user interactions.
Based on the FAS popup sound manager pattern.
"""

import logging
import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Optional

LOG = logging.getLogger("adi.sound")

# Sound file directory
SOUNDS_DIR = Path(__file__).parent / "sounds"

# Global sound manager instance
_sound_manager: Optional['SoundManager'] = None


class SoundManager:
    """Manages sound playback for ADI popup."""

    def __init__(self, enabled: bool = True, volume: float = 0.6):
        self.enabled = enabled
        self.volume = max(0.0, min(1.0, volume))
        self._last_played: dict = {}
        self._cooldown = 0.15  # Minimum seconds between same sound
        self._sounds_generated = False

        # Generate sounds on first use
        self._ensure_sounds()

    def _ensure_sounds(self):
        """Ensure sound files exist, generate if needed."""
        if self._sounds_generated:
            return

        SOUNDS_DIR.mkdir(parents=True, exist_ok=True)

        # Check if sox is available
        try:
            subprocess.run(['sox', '--version'], capture_output=True, timeout=5)
            has_sox = True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            has_sox = False
            LOG.warning("sox not found, sounds will be disabled")
            self.enabled = False  # Disable sounds entirely when sox is missing

        if not has_sox:
            return

        # Generate sounds if they don't exist
        sounds = {
            "popup_appear": self._gen_popup_appear,
            "popup_dismiss": self._gen_popup_dismiss,
            "message_send": self._gen_message_send,
            "message_receive": self._gen_message_receive,
            "apply": self._gen_apply,
            "click": self._gen_click,
        }

        for name, generator in sounds.items():
            sound_path = SOUNDS_DIR / f"{name}.ogg"
            if not sound_path.exists():
                try:
                    generator(sound_path)
                    LOG.debug(f"Generated sound: {name}")
                except Exception as e:
                    LOG.warning(f"Failed to generate {name}: {e}")

        self._sounds_generated = True

    def _gen_popup_appear(self, path: Path):
        """Generate popup appear sound - warm ascending tone."""
        subprocess.run([
            'sox', '-n', str(path),
            'synth', '0.08', 'sine', '400',
            'synth', '0.08', 'sine', '500', 'gain', '-3',
            'synth', '0.15', 'sine', '600', 'gain', '-6',
            'fade', 'q', '0.01', '0.3', '0.1',
            'reverb', '20',
        ], capture_output=True, timeout=10)

    def _gen_popup_dismiss(self, path: Path):
        """Generate popup dismiss sound - soft descending whoosh."""
        subprocess.run([
            'sox', '-n', str(path),
            'synth', '0.2', 'sine', '500:200',
            'fade', 'q', '0.01', '0.2', '0.15',
            'gain', '-6',
        ], capture_output=True, timeout=10)

    def _gen_message_send(self, path: Path):
        """Generate message send sound - quick blip."""
        subprocess.run([
            'sox', '-n', str(path),
            'synth', '0.05', 'sine', '800',
            'fade', 'q', '0.005', '0.05', '0.02',
            'gain', '-8',
        ], capture_output=True, timeout=10)

    def _gen_message_receive(self, path: Path):
        """Generate message receive sound - soft chime."""
        subprocess.run([
            'sox', '-n', str(path),
            'synth', '0.1', 'sine', '600',
            'synth', '0.1', 'sine', '750', 'gain', '-3',
            'fade', 'q', '0.01', '0.2', '0.1',
            'gain', '-6',
            'reverb', '15',
        ], capture_output=True, timeout=10)

    def _gen_apply(self, path: Path):
        """Generate apply/confirm sound - success chord."""
        subprocess.run([
            'sox', '-n', str(path),
            'synth', '0.15', 'sine', '523',  # C5
            'synth', '0.15', 'sine', '659', 'gain', '-3',  # E5
            'synth', '0.2', 'sine', '784', 'gain', '-6',  # G5
            'fade', 'q', '0.01', '0.4', '0.2',
            'reverb', '25',
        ], capture_output=True, timeout=10)

    def _gen_click(self, path: Path):
        """Generate click sound - subtle tick."""
        subprocess.run([
            'sox', '-n', str(path),
            'synth', '0.02', 'sine', '1000',
            'fade', 'q', '0.002', '0.02', '0.01',
            'gain', '-12',
        ], capture_output=True, timeout=10)

    def _play(self, sound_name: str, async_play: bool = True):
        """Play a sound file."""
        if not self.enabled:
            return

        # Check cooldown
        now = time.time()
        last = self._last_played.get(sound_name, 0)
        if now - last < self._cooldown:
            return
        self._last_played[sound_name] = now

        sound_path = SOUNDS_DIR / f"{sound_name}.ogg"
        if not sound_path.exists():
            return

        def do_play():
            try:
                # Calculate volume (paplay uses 0-65536)
                vol = int(self.volume * 65536)

                # Try paplay first (PulseAudio)
                result = subprocess.run(
                    ['paplay', '--volume', str(vol), str(sound_path)],
                    capture_output=True,
                    timeout=5
                )

                if result.returncode != 0:
                    # Fallback to aplay
                    subprocess.run(
                        ['aplay', '-q', str(sound_path)],
                        capture_output=True,
                        timeout=5
                    )
            except Exception as e:
                LOG.debug(f"Sound playback failed: {e}")

        if async_play:
            thread = threading.Thread(target=do_play, daemon=True)
            thread.start()
        else:
            do_play()

    def set_enabled(self, enabled: bool):
        """Enable or disable sounds."""
        self.enabled = enabled

    def set_volume(self, volume: float):
        """Set volume (0.0 to 1.0)."""
        self.volume = max(0.0, min(1.0, volume))

    # Convenience methods
    def play_popup_appear(self):
        self._play("popup_appear")

    def play_popup_dismiss(self):
        self._play("popup_dismiss")

    def play_message_send(self):
        self._play("message_send")

    def play_message_receive(self):
        self._play("message_receive")

    def play_apply(self):
        self._play("apply")

    def play_click(self):
        self._play("click")


def get_sound_manager(enabled: bool = True, volume: float = 0.6) -> SoundManager:
    """Get or create the global sound manager instance."""
    global _sound_manager
    if _sound_manager is None:
        _sound_manager = SoundManager(enabled, volume)
    return _sound_manager


# Quick test
if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)

    print("=== ADI Sound Manager Test ===")
    sm = get_sound_manager()

    print("Playing popup appear...")
    sm.play_popup_appear()
    time.sleep(0.5)

    print("Playing message send...")
    sm.play_message_send()
    time.sleep(0.3)

    print("Playing message receive...")
    sm.play_message_receive()
    time.sleep(0.3)

    print("Playing apply...")
    sm.play_apply()
    time.sleep(0.5)

    print("Playing dismiss...")
    sm.play_popup_dismiss()
    time.sleep(0.3)

    print("Done!")
