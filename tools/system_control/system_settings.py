#!/usr/bin/env python3
"""
System Settings - Display, Audio, and Bluetooth Control

Features:
- Display resolution with auto-revert (15 second timeout)
- Audio output/input selection
- Bluetooth pairing and management
- Double opt-in for system changes

Author: Frank AI System
"""

import json
import logging
import re
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .sensitive_actions import (
    ConfirmationLevel,
    request_confirmation,
    is_action_confirmed,
    mark_action_executed,
    get_handler,
)

LOG = logging.getLogger("system_control.settings")

# Auto-revert timeout for display changes
DISPLAY_REVERT_SECONDS = 15


@dataclass
class DisplayMode:
    """Represents a display resolution mode."""
    width: int
    height: int
    refresh_rate: float
    is_current: bool = False
    is_preferred: bool = False

    def __str__(self) -> str:
        return f"{self.width}x{self.height}@{self.refresh_rate}Hz"

    def to_dict(self) -> dict:
        return {
            "width": self.width,
            "height": self.height,
            "refresh_rate": self.refresh_rate,
            "is_current": self.is_current,
            "is_preferred": self.is_preferred
        }


@dataclass
class AudioDevice:
    """Represents an audio device."""
    name: str
    description: str
    device_type: str  # "sink" (output) or "source" (input)
    is_default: bool = False
    volume: int = 100
    muted: bool = False

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "type": self.device_type,
            "is_default": self.is_default,
            "volume": self.volume,
            "muted": self.muted
        }


@dataclass
class BluetoothDevice:
    """Represents a bluetooth device."""
    mac: str
    name: str
    device_type: str  # "audio", "input", "unknown"
    paired: bool = False
    connected: bool = False
    trusted: bool = False

    def to_dict(self) -> dict:
        return {
            "mac": self.mac,
            "name": self.name,
            "type": self.device_type,
            "paired": self.paired,
            "connected": self.connected,
            "trusted": self.trusted
        }


class DisplayManager:
    """Manages display settings."""

    def __init__(self):
        self._current_mode: Optional[DisplayMode] = None
        self._previous_mode: Optional[DisplayMode] = None

    def get_displays(self) -> Dict[str, List[DisplayMode]]:
        """
        Get available displays and their modes.

        Returns:
            Dict mapping display name to list of available modes
        """
        displays: Dict[str, List[DisplayMode]] = {}

        try:
            result = subprocess.run(
                ["xrandr", "--query"],
                capture_output=True,
                text=True,
                timeout=10
            )

            current_display = None

            for line in result.stdout.split("\n"):
                # Display line
                if " connected" in line:
                    parts = line.split()
                    current_display = parts[0]
                    displays[current_display] = []

                # Resolution line
                elif current_display and line.strip() and "x" in line:
                    line = line.strip()
                    parts = line.split()

                    if parts:
                        resolution = parts[0]
                        match = re.match(r"(\d+)x(\d+)", resolution)
                        if match:
                            width = int(match.group(1))
                            height = int(match.group(2))

                            # Parse refresh rates
                            for part in parts[1:]:
                                # Remove markers
                                rate_str = part.replace("*", "").replace("+", "").strip()
                                try:
                                    rate = float(rate_str)
                                    is_current = "*" in part
                                    is_preferred = "+" in part

                                    mode = DisplayMode(
                                        width=width,
                                        height=height,
                                        refresh_rate=rate,
                                        is_current=is_current,
                                        is_preferred=is_preferred
                                    )
                                    displays[current_display].append(mode)

                                    if is_current:
                                        self._current_mode = mode
                                except ValueError:
                                    pass

        except Exception as e:
            LOG.error(f"Failed to get displays: {e}")

        return displays

    def get_current_resolution(self, display: str = None) -> Optional[DisplayMode]:
        """Get current resolution for a display."""
        displays = self.get_displays()

        if display and display in displays:
            for mode in displays[display]:
                if mode.is_current:
                    return mode
        elif displays:
            # Return first display's current mode
            for modes in displays.values():
                for mode in modes:
                    if mode.is_current:
                        return mode

        return self._current_mode

    def request_resolution_change(
        self,
        width: int,
        height: int,
        refresh_rate: float = 60.0,
        display: str = None
    ) -> Tuple[str, str]:
        """
        Request display resolution change with auto-revert.

        Returns:
            (action_id, confirmation_message)
        """
        current = self.get_current_resolution(display)

        # Get display name
        displays = self.get_displays()
        if not display and displays:
            display = list(displays.keys())[0]

        preview = f"""CHANGE RESOLUTION:

Display: {display}
Current resolution: {current.width}x{current.height}@{current.refresh_rate}Hz
New resolution: {width}x{height}@{refresh_rate}Hz

WARNING: The change will be automatically reverted after {DISPLAY_REVERT_SECONDS} seconds
if you do not confirm!
"""

        return request_confirmation(
            action_type="display_resolution",
            description=f"Change resolution to {width}x{height}",
            preview=preview,
            params={
                "display": display,
                "width": width,
                "height": height,
                "refresh_rate": refresh_rate,
                "previous_width": current.width if current else 1920,
                "previous_height": current.height if current else 1080,
                "previous_rate": current.refresh_rate if current else 60.0
            },
            level=ConfirmationLevel.AUTO_REVERT,
            auto_revert_seconds=DISPLAY_REVERT_SECONDS,
            undo_info={
                "operation_type": "display_resolution",
                "can_undo": True
            }
        )

    def execute_resolution_change(self, action_id: str) -> Tuple[bool, str]:
        """Execute confirmed resolution change."""
        if not is_action_confirmed(action_id):
            return False, "Action not confirmed"

        action = get_handler().get_action(action_id)
        if not action:
            return False, "Action not found"

        display = action.params["display"]
        width = action.params["width"]
        height = action.params["height"]
        rate = action.params["refresh_rate"]

        # Store previous mode for revert
        prev_width = action.params["previous_width"]
        prev_height = action.params["previous_height"]
        prev_rate = action.params["previous_rate"]

        def revert_callback():
            """Revert to previous resolution."""
            LOG.info("Auto-reverting display resolution...")
            self._set_resolution(display, prev_width, prev_height, prev_rate)

        try:
            success = self._set_resolution(display, width, height, rate)

            if success:
                mark_action_executed(action_id, revert_callback)
                return True, f"""Resolution changed to {width}x{height}@{rate}Hz

The change will be automatically reverted in {DISPLAY_REVERT_SECONDS} seconds.
Say 'keep' or 'looks good' to keep the change."""
            else:
                return False, "Resolution change failed"

        except Exception as e:
            return False, f"Error: {e}"

    def _set_resolution(self, display: str, width: int, height: int, rate: float) -> bool:
        """Set display resolution using xrandr."""
        try:
            mode = f"{width}x{height}"
            result = subprocess.run(
                ["xrandr", "--output", display, "--mode", mode, "--rate", str(rate)],
                capture_output=True,
                text=True,
                timeout=10
            )
            return result.returncode == 0
        except Exception as e:
            LOG.error(f"xrandr failed: {e}")
            return False

    def keep_resolution(self, action_id: str) -> Tuple[bool, str]:
        """Keep the current resolution (cancel auto-revert)."""
        from .sensitive_actions import get_handler
        handler = get_handler()
        return handler.cancel_auto_revert(action_id)


class AudioManager:
    """Manages audio settings using PulseAudio/PipeWire."""

    def get_outputs(self) -> List[AudioDevice]:
        """Get available audio outputs (sinks)."""
        return self._get_devices("sink")

    def get_inputs(self) -> List[AudioDevice]:
        """Get available audio inputs (sources)."""
        return self._get_devices("source")

    def _get_devices(self, device_type: str) -> List[AudioDevice]:
        """Get audio devices of a specific type."""
        devices = []

        try:
            # Use pactl to list devices
            result = subprocess.run(
                ["pactl", "list", f"{device_type}s", "short"],
                capture_output=True,
                text=True,
                timeout=10
            )

            # Get default device
            default_result = subprocess.run(
                ["pactl", "get-default-sink" if device_type == "sink" else "get-default-source"],
                capture_output=True,
                text=True,
                timeout=5
            )
            default_name = default_result.stdout.strip()

            for line in result.stdout.strip().split("\n"):
                if not line:
                    continue

                parts = line.split("\t")
                if len(parts) >= 2:
                    name = parts[1]

                    # Get device info
                    info = self._get_device_info(device_type, name)

                    device = AudioDevice(
                        name=name,
                        description=info.get("description", name),
                        device_type=device_type,
                        is_default=(name == default_name),
                        volume=info.get("volume", 100),
                        muted=info.get("muted", False)
                    )
                    devices.append(device)

        except Exception as e:
            LOG.error(f"Failed to get audio devices: {e}")

        return devices

    def _get_device_info(self, device_type: str, name: str) -> Dict[str, Any]:
        """Get detailed device info."""
        info = {"description": name, "volume": 100, "muted": False}

        try:
            result = subprocess.run(
                ["pactl", "list", f"{device_type}s"],
                capture_output=True,
                text=True,
                timeout=10
            )

            in_device = False
            for line in result.stdout.split("\n"):
                if f"Name: {name}" in line:
                    in_device = True
                elif in_device and line.startswith("Name:"):
                    break
                elif in_device:
                    if "Description:" in line:
                        info["description"] = line.split("Description:")[1].strip()
                    elif "Volume:" in line:
                        match = re.search(r"(\d+)%", line)
                        if match:
                            info["volume"] = int(match.group(1))
                    elif "Mute:" in line:
                        info["muted"] = "yes" in line.lower()

        except Exception:
            pass

        return info

    def set_default_output(self, device_name: str) -> Tuple[bool, str]:
        """Set default audio output."""
        try:
            result = subprocess.run(
                ["pactl", "set-default-sink", device_name],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                return True, f"Audio output set to '{device_name}'"
            return False, f"Could not set audio output: {result.stderr}"
        except Exception as e:
            return False, f"Error: {e}"

    def set_default_input(self, device_name: str) -> Tuple[bool, str]:
        """Set default audio input."""
        try:
            result = subprocess.run(
                ["pactl", "set-default-source", device_name],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                return True, f"Audio input set to '{device_name}'"
            return False, f"Could not set audio input: {result.stderr}"
        except Exception as e:
            return False, f"Error: {e}"

    def set_volume(self, volume: int, device_type: str = "sink") -> Tuple[bool, str]:
        """Set volume for default device."""
        try:
            volume = max(0, min(150, volume))
            target = "@DEFAULT_SINK@" if device_type == "sink" else "@DEFAULT_SOURCE@"
            result = subprocess.run(
                ["pactl", f"set-{device_type}-volume", target, f"{volume}%"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                return True, f"Volume set to {volume}%"
            return False, f"Could not set volume: {result.stderr}"
        except Exception as e:
            return False, f"Error: {e}"

    def toggle_mute(self, device_type: str = "sink") -> Tuple[bool, str]:
        """Toggle mute for default device."""
        try:
            target = "@DEFAULT_SINK@" if device_type == "sink" else "@DEFAULT_SOURCE@"
            result = subprocess.run(
                ["pactl", f"set-{device_type}-mute", target, "toggle"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                return True, "Mute toggled"
            return False, f"Could not toggle mute: {result.stderr}"
        except Exception as e:
            return False, f"Error: {e}"


class BluetoothManager:
    """Manages Bluetooth devices using bluetoothctl."""

    def get_devices(self, scan_time: int = 5) -> List[BluetoothDevice]:
        """
        Get available Bluetooth devices.

        Args:
            scan_time: Seconds to scan for devices
        """
        devices = []

        try:
            # Start scan
            subprocess.run(
                ["bluetoothctl", "scan", "on"],
                capture_output=True,
                timeout=2
            )

            time.sleep(scan_time)

            # Stop scan
            subprocess.run(
                ["bluetoothctl", "scan", "off"],
                capture_output=True,
                timeout=2
            )

            # List devices
            result = subprocess.run(
                ["bluetoothctl", "devices"],
                capture_output=True,
                text=True,
                timeout=5
            )

            for line in result.stdout.strip().split("\n"):
                if "Device" in line:
                    parts = line.split()
                    if len(parts) >= 3:
                        mac = parts[1]
                        name = " ".join(parts[2:])

                        # Get device info
                        info = self._get_device_info(mac)

                        device = BluetoothDevice(
                            mac=mac,
                            name=name,
                            device_type=info.get("type", "unknown"),
                            paired=info.get("paired", False),
                            connected=info.get("connected", False),
                            trusted=info.get("trusted", False)
                        )
                        devices.append(device)

        except Exception as e:
            LOG.error(f"Bluetooth scan failed: {e}")

        return devices

    def _get_device_info(self, mac: str) -> Dict[str, Any]:
        """Get Bluetooth device info."""
        info = {"type": "unknown", "paired": False, "connected": False, "trusted": False}

        try:
            result = subprocess.run(
                ["bluetoothctl", "info", mac],
                capture_output=True,
                text=True,
                timeout=5
            )

            for line in result.stdout.split("\n"):
                line = line.strip()
                if "Paired: yes" in line:
                    info["paired"] = True
                elif "Connected: yes" in line:
                    info["connected"] = True
                elif "Trusted: yes" in line:
                    info["trusted"] = True
                elif "Icon: audio" in line:
                    info["type"] = "audio"
                elif "Icon: input" in line:
                    info["type"] = "input"

        except Exception:
            pass

        return info

    def request_pair(self, mac: str, name: str) -> Tuple[str, str]:
        """Request Bluetooth pairing with confirmation."""
        preview = f"""BLUETOOTH PAIRING:

Device: {name}
MAC: {mac}

The device will be paired and marked as trusted.
"""
        return request_confirmation(
            action_type="bluetooth_pair",
            description=f"Pair Bluetooth device: {name}",
            preview=preview,
            params={"mac": mac, "name": name},
            level=ConfirmationLevel.SINGLE
        )

    def execute_pair(self, action_id: str) -> Tuple[bool, str]:
        """Execute Bluetooth pairing."""
        if not is_action_confirmed(action_id):
            return False, "Action not confirmed"

        action = get_handler().get_action(action_id)
        if not action:
            return False, "Action not found"

        mac = action.params["mac"]
        name = action.params["name"]

        try:
            # Pair
            result = subprocess.run(
                ["bluetoothctl", "pair", mac],
                capture_output=True,
                text=True,
                timeout=30
            )

            if "Failed" in result.stdout or result.returncode != 0:
                return False, f"Pairing failed: {result.stdout}"

            # Trust
            subprocess.run(["bluetoothctl", "trust", mac], timeout=5)

            # Connect
            subprocess.run(["bluetoothctl", "connect", mac], timeout=10)

            mark_action_executed(action_id)
            return True, f"Bluetooth device '{name}' successfully paired!"

        except subprocess.TimeoutExpired:
            return False, "Pairing timeout - make sure the device is in pairing mode"
        except Exception as e:
            return False, f"Error: {e}"

    def disconnect(self, mac: str) -> Tuple[bool, str]:
        """Disconnect a Bluetooth device."""
        try:
            result = subprocess.run(
                ["bluetoothctl", "disconnect", mac],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                return True, "Bluetooth device disconnected"
            return False, f"Disconnection failed: {result.stderr}"
        except Exception as e:
            return False, f"Error: {e}"


class SystemSettings:
    """Unified system settings interface."""

    def __init__(self):
        self.display = DisplayManager()
        self.audio = AudioManager()
        self.bluetooth = BluetoothManager()


# Singleton
_settings: Optional[SystemSettings] = None


def get_settings() -> SystemSettings:
    """Get singleton settings."""
    global _settings
    if _settings is None:
        _settings = SystemSettings()
    return _settings


# Public API - Display

def get_displays() -> Dict[str, List[Dict]]:
    """Get available displays and modes."""
    displays = get_settings().display.get_displays()
    return {
        name: [mode.to_dict() for mode in modes]
        for name, modes in displays.items()
    }


def get_current_resolution() -> Optional[Dict]:
    """Get current display resolution."""
    mode = get_settings().display.get_current_resolution()
    return mode.to_dict() if mode else None


def request_resolution_change(
    width: int,
    height: int,
    refresh_rate: float = 60.0,
    display: str = None
) -> Tuple[str, str]:
    """Request resolution change."""
    return get_settings().display.request_resolution_change(width, height, refresh_rate, display)


def execute_resolution_change(action_id: str) -> Tuple[bool, str]:
    """Execute resolution change."""
    return get_settings().display.execute_resolution_change(action_id)


def keep_resolution(action_id: str) -> Tuple[bool, str]:
    """Keep current resolution (cancel auto-revert)."""
    return get_settings().display.keep_resolution(action_id)


# Public API - Audio

def get_audio_outputs() -> List[Dict]:
    """Get available audio outputs."""
    return [d.to_dict() for d in get_settings().audio.get_outputs()]


def get_audio_inputs() -> List[Dict]:
    """Get available audio inputs."""
    return [d.to_dict() for d in get_settings().audio.get_inputs()]


def set_audio_output(device_name: str) -> Tuple[bool, str]:
    """Set default audio output."""
    return get_settings().audio.set_default_output(device_name)


def set_audio_input(device_name: str) -> Tuple[bool, str]:
    """Set default audio input."""
    return get_settings().audio.set_default_input(device_name)


def set_volume(volume: int) -> Tuple[bool, str]:
    """Set audio volume."""
    return get_settings().audio.set_volume(volume)


def toggle_mute() -> Tuple[bool, str]:
    """Toggle audio mute."""
    return get_settings().audio.toggle_mute()


# Public API - Bluetooth

def scan_bluetooth(scan_time: int = 5) -> List[Dict]:
    """Scan for Bluetooth devices."""
    return [d.to_dict() for d in get_settings().bluetooth.get_devices(scan_time)]


def request_bluetooth_pair(mac: str, name: str) -> Tuple[str, str]:
    """Request Bluetooth pairing."""
    return get_settings().bluetooth.request_pair(mac, name)


def execute_bluetooth_pair(action_id: str) -> Tuple[bool, str]:
    """Execute Bluetooth pairing."""
    return get_settings().bluetooth.execute_pair(action_id)


def disconnect_bluetooth(mac: str) -> Tuple[bool, str]:
    """Disconnect Bluetooth device."""
    return get_settings().bluetooth.disconnect(mac)


# Quick test
if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)

    print("=== System Settings Test ===")

    settings = get_settings()

    print("\n--- Displays ---")
    displays = settings.display.get_displays()
    for name, modes in displays.items():
        print(f"\n{name}:")
        for mode in modes[:5]:
            marker = " *" if mode.is_current else ""
            print(f"  {mode}{marker}")

    print("\n--- Audio Outputs ---")
    outputs = settings.audio.get_outputs()
    for out in outputs:
        default = " (DEFAULT)" if out.is_default else ""
        print(f"  {out.description}{default}")

    print("\n--- Audio Inputs ---")
    inputs = settings.audio.get_inputs()
    for inp in inputs:
        default = " (DEFAULT)" if inp.is_default else ""
        print(f"  {inp.description}{default}")
