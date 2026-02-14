#!/usr/bin/env python3
"""
F.A.S. Sound Manager
Handles all audio feedback for the popup system.
"""

import subprocess
import time
from pathlib import Path
from typing import Dict, Optional
import threading

# Try to import for generating sounds
try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False


class SoundManager:
    """
    Manages UI sounds with volume control and cooldown.
    """

    try:
        from config.paths import SOUNDS_DIR as _SOUNDS_DIR
    except ImportError:
        _SOUNDS_DIR = Path("/home/ai-core-node/aicore/opt/aicore/ui/sounds")
    SOUNDS_DIR = _SOUNDS_DIR

    # Sound definitions
    SOUNDS = {
        "popup_appear": "popup_appear.ogg",
        "checkbox_click": "checkbox_click.ogg",
        "integration_start": "integration_start.ogg",
        "integration_done": "integration_done.ogg",
        "popup_dismiss": "popup_dismiss.ogg",
    }

    def __init__(self, enabled: bool = True, volume: float = 0.6):
        self.enabled = enabled
        self.volume = max(0.0, min(1.0, volume))
        self.last_played: Dict[str, float] = {}
        self.min_interval = 0.15  # Minimum seconds between same sound
        self._ensure_sounds_exist()

    def _ensure_sounds_exist(self):
        """Create sound files if they don't exist."""
        self.SOUNDS_DIR.mkdir(parents=True, exist_ok=True)

        for sound_name, filename in self.SOUNDS.items():
            sound_path = self.SOUNDS_DIR / filename
            if not sound_path.exists():
                self._generate_sound(sound_name, sound_path)

    def _generate_sound(self, sound_name: str, path: Path):
        """Generate a simple sound file using sox or ffmpeg."""
        # Check if sox is available
        sox_available = self._check_command("sox")
        ffmpeg_available = self._check_command("ffmpeg")

        if not sox_available and not ffmpeg_available:
            print(f"Neither sox nor ffmpeg available, skipping sound generation")
            return

        # Sound parameters for each type
        sound_params = {
            "popup_appear": self._gen_popup_appear,
            "checkbox_click": self._gen_click,
            "integration_start": self._gen_power_up,
            "integration_done": self._gen_success,
            "popup_dismiss": self._gen_whoosh,
        }

        generator = sound_params.get(sound_name, self._gen_click)
        try:
            if sox_available:
                generator(path)
            elif ffmpeg_available:
                self._gen_sound_ffmpeg(sound_name, path)
        except Exception as e:
            print(f"Could not generate sound {sound_name}: {e}")

    def _check_command(self, cmd: str) -> bool:
        """Check if a command is available."""
        try:
            result = subprocess.run(['which', cmd], capture_output=True)
            return result.returncode == 0
        except (subprocess.SubprocessError, OSError):
            return False

    def _gen_sound_ffmpeg(self, sound_name: str, path: Path):
        """Generate sound using ffmpeg as fallback."""
        # Different frequencies for different sounds
        params = {
            "popup_appear": ("sine", 880, 0.5),
            "checkbox_click": ("sine", 1000, 0.05),
            "integration_start": ("sine", 440, 0.3),
            "integration_done": ("sine", 660, 0.5),
            "popup_dismiss": ("sine", 300, 0.2),
        }
        wave, freq, duration = params.get(sound_name, ("sine", 440, 0.2))

        subprocess.run([
            'ffmpeg', '-y', '-f', 'lavfi',
            '-i', f'sine=frequency={freq}:duration={duration}',
            '-af', 'volume=0.3',
            str(path)
        ], capture_output=True, check=False)

    def _gen_popup_appear(self, path: Path):
        """Cyberpunk chime - ascending synth."""
        # Using sox to generate a synth sound
        subprocess.run([
            'sox', '-n', str(path),
            'synth', '0.1', 'sine', '440',
            'synth', '0.1', 'sine', '660', 'gain', '-3',
            'synth', '0.3', 'sine', '880', 'gain', '-6',
            'fade', 'q', '0.01', '0.5', '0.2',
            'reverb', '30',
        ], capture_output=True, check=False)

    def _gen_click(self, path: Path):
        """Short click sound."""
        subprocess.run([
            'sox', '-n', str(path),
            'synth', '0.05', 'sine', '1000',
            'fade', 'q', '0.005', '0.05', '0.02',
            'gain', '-10',
        ], capture_output=True, check=False)

    def _gen_power_up(self, path: Path):
        """Ascending power-up sound."""
        subprocess.run([
            'sox', '-n', str(path),
            'synth', '0.5', 'sine', '200:800',
            'fade', 'q', '0.01', '0.5', '0.1',
            'gain', '-6',
        ], capture_output=True, check=False)

    def _gen_success(self, path: Path):
        """Success chime - harmonic."""
        subprocess.run([
            'sox', '-n', str(path),
            'synth', '0.2', 'sine', '523',  # C5
            'synth', '0.2', 'sine', '659',  # E5
            'synth', '0.4', 'sine', '784',  # G5
            'fade', 'q', '0.01', '0.8', '0.3',
            'reverb', '40',
            'gain', '-6',
        ], capture_output=True, check=False)

    def _gen_whoosh(self, path: Path):
        """Dismissal whoosh sound."""
        subprocess.run([
            'sox', '-n', str(path),
            'synth', '0.3', 'noise', 'band', '500', '200',
            'fade', 'q', '0.01', '0.3', '0.2',
            'gain', '-15',
        ], capture_output=True, check=False)

    def _gen_silence(self, path: Path):
        """Generate a silent file as placeholder."""
        subprocess.run([
            'sox', '-n', str(path),
            'trim', '0', '0.1',
        ], capture_output=True, check=False)

    def play(self, sound_name: str, async_play: bool = True):
        """
        Play a sound if enabled and cooldown allows.

        Args:
            sound_name: Name of the sound to play
            async_play: If True, play in background thread
        """
        if not self.enabled:
            return

        # Check cooldown
        now = time.time()
        if sound_name in self.last_played:
            if now - self.last_played[sound_name] < self.min_interval:
                return

        self.last_played[sound_name] = now

        # Get sound file
        filename = self.SOUNDS.get(sound_name)
        if not filename:
            return

        sound_path = self.SOUNDS_DIR / filename
        if not sound_path.exists():
            return

        if async_play:
            thread = threading.Thread(target=self._play_sound, args=(sound_path,))
            thread.daemon = True
            thread.start()
        else:
            self._play_sound(sound_path)

    def _play_sound(self, sound_path: Path):
        """Play sound file using paplay."""
        try:
            # Calculate PulseAudio volume (0-65536)
            pa_volume = int(65536 * self.volume)

            subprocess.run(
                ['paplay', '--volume', str(pa_volume), str(sound_path)],
                capture_output=True,
                timeout=5,
            )
        except subprocess.TimeoutExpired:
            pass
        except FileNotFoundError:
            # paplay not available, try aplay
            try:
                subprocess.run(
                    ['aplay', '-q', str(sound_path)],
                    capture_output=True,
                    timeout=5,
                )
            except (subprocess.SubprocessError, FileNotFoundError, OSError):
                pass  # Audio playback not available
        except (subprocess.SubprocessError, OSError):
            pass  # Subprocess error, ignore silently

    def set_enabled(self, enabled: bool):
        """Enable or disable sounds."""
        self.enabled = enabled

    def set_volume(self, volume: float):
        """Set volume (0.0 - 1.0)."""
        self.volume = max(0.0, min(1.0, volume))

    def play_popup_appear(self):
        """Play popup appear sound."""
        self.play("popup_appear")

    def play_click(self):
        """Play checkbox click sound."""
        self.play("checkbox_click")

    def play_integration_start(self):
        """Play integration start sound."""
        self.play("integration_start")

    def play_integration_done(self):
        """Play integration complete sound."""
        self.play("integration_done")

    def play_dismiss(self):
        """Play popup dismiss sound."""
        self.play("popup_dismiss")


# Singleton instance
_sound_manager: Optional[SoundManager] = None


def get_sound_manager() -> SoundManager:
    """Get or create sound manager singleton."""
    global _sound_manager
    if _sound_manager is None:
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).parent.parent.parent))
        from config.fas_popup_config import get_config
        config = get_config()
        _sound_manager = SoundManager(
            enabled=config.get("sound_enabled", True),
            volume=config.get("sound_volume", 0.6),
        )
    return _sound_manager
