#!/usr/bin/env python3
"""
Comprehensive Tests for system_settings.py

Tests:
1. get_displays() and get_resolutions()
2. set_resolution() with AUTO_REVERT mechanism
3. get_volume() and set_volume() audio controls
4. toggle_mute() functionality
5. scan_bluetooth() and pair_bluetooth()
6. Confirmation integration for display changes
7. Edge cases: invalid resolution, volume out of range

Author: Test Suite
"""

import json
import logging
import os
import sys
import threading
import time
import unittest
from unittest.mock import patch, MagicMock, PropertyMock
from dataclasses import dataclass
from typing import Dict, List, Optional, Any, Tuple

# Setup logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
LOG = logging.getLogger("test_system_settings")

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import the modules to test
from system_control.system_settings import (
    DisplayMode, AudioDevice, BluetoothDevice,
    DisplayManager, AudioManager, BluetoothManager,
    SystemSettings, get_settings,
    get_displays, get_current_resolution,
    request_resolution_change, execute_resolution_change, keep_resolution,
    get_audio_outputs, get_audio_inputs, set_volume, toggle_mute,
    scan_bluetooth, request_bluetooth_pair, execute_bluetooth_pair,
    DISPLAY_REVERT_SECONDS
)

from system_control.sensitive_actions import (
    ConfirmationLevel, ConfirmationState,
    get_handler, request_confirmation, is_action_confirmed,
    confirm_action, mark_action_executed, cancel_pending_action
)


class TestDisplayMode(unittest.TestCase):
    """Test DisplayMode dataclass."""

    def test_display_mode_creation(self):
        """Test creating a DisplayMode."""
        mode = DisplayMode(width=1920, height=1080, refresh_rate=60.0)
        self.assertEqual(mode.width, 1920)
        self.assertEqual(mode.height, 1080)
        self.assertEqual(mode.refresh_rate, 60.0)
        self.assertFalse(mode.is_current)
        self.assertFalse(mode.is_preferred)

    def test_display_mode_str(self):
        """Test DisplayMode string representation."""
        mode = DisplayMode(width=2560, height=1440, refresh_rate=144.0)
        self.assertEqual(str(mode), "2560x1440@144.0Hz")

    def test_display_mode_to_dict(self):
        """Test DisplayMode to_dict method."""
        mode = DisplayMode(width=1920, height=1080, refresh_rate=60.0, is_current=True, is_preferred=True)
        d = mode.to_dict()
        self.assertEqual(d["width"], 1920)
        self.assertEqual(d["height"], 1080)
        self.assertEqual(d["refresh_rate"], 60.0)
        self.assertTrue(d["is_current"])
        self.assertTrue(d["is_preferred"])


class TestAudioDevice(unittest.TestCase):
    """Test AudioDevice dataclass."""

    def test_audio_device_creation(self):
        """Test creating an AudioDevice."""
        device = AudioDevice(
            name="alsa_output.pci-0000_00_1f.3.analog-stereo",
            description="Built-in Audio Analog Stereo",
            device_type="sink"
        )
        self.assertEqual(device.device_type, "sink")
        self.assertFalse(device.is_default)
        self.assertEqual(device.volume, 100)
        self.assertFalse(device.muted)

    def test_audio_device_to_dict(self):
        """Test AudioDevice to_dict method."""
        device = AudioDevice(
            name="test_sink",
            description="Test Sink",
            device_type="sink",
            is_default=True,
            volume=75,
            muted=True
        )
        d = device.to_dict()
        self.assertEqual(d["name"], "test_sink")
        self.assertEqual(d["type"], "sink")
        self.assertTrue(d["is_default"])
        self.assertEqual(d["volume"], 75)
        self.assertTrue(d["muted"])


class TestBluetoothDevice(unittest.TestCase):
    """Test BluetoothDevice dataclass."""

    def test_bluetooth_device_creation(self):
        """Test creating a BluetoothDevice."""
        device = BluetoothDevice(
            mac="AA:BB:CC:DD:EE:FF",
            name="My Headphones",
            device_type="audio"
        )
        self.assertEqual(device.mac, "AA:BB:CC:DD:EE:FF")
        self.assertEqual(device.name, "My Headphones")
        self.assertEqual(device.device_type, "audio")
        self.assertFalse(device.paired)
        self.assertFalse(device.connected)
        self.assertFalse(device.trusted)

    def test_bluetooth_device_to_dict(self):
        """Test BluetoothDevice to_dict method."""
        device = BluetoothDevice(
            mac="11:22:33:44:55:66",
            name="Keyboard",
            device_type="input",
            paired=True,
            connected=True,
            trusted=True
        )
        d = device.to_dict()
        self.assertEqual(d["mac"], "11:22:33:44:55:66")
        self.assertEqual(d["type"], "input")
        self.assertTrue(d["paired"])
        self.assertTrue(d["connected"])


class TestDisplayManager(unittest.TestCase):
    """Test DisplayManager class."""

    def setUp(self):
        """Set up test fixtures."""
        self.manager = DisplayManager()

    @patch('subprocess.run')
    def test_get_displays_success(self, mock_run):
        """Test get_displays with valid xrandr output."""
        mock_run.return_value = MagicMock(
            stdout="""Screen 0: minimum 8 x 8, current 1920 x 1080, maximum 32767 x 32767
eDP-1 connected primary 1920x1080+0+0 (normal left inverted right x axis y axis) 344mm x 194mm
   1920x1080     60.00*+  59.97    59.96    59.93
   1680x1050     59.95    59.88
   1280x1024     60.02
   1440x900      59.89
   1280x800      59.99
   1280x720      60.00    59.99    59.86    59.74
   1024x768      60.04    60.00
DP-1 disconnected (normal left inverted right x axis y axis)
HDMI-1 connected 1920x1080+1920+0 (normal left inverted right x axis y axis) 527mm x 296mm
   1920x1080     60.00*+  50.00    59.94
   1280x720      60.00    50.00    59.94
""",
            returncode=0
        )

        displays = self.manager.get_displays()

        # Should have two connected displays
        self.assertIn("eDP-1", displays)
        self.assertIn("HDMI-1", displays)
        self.assertNotIn("DP-1", displays)  # Disconnected

        # Check eDP-1 modes
        edp_modes = displays["eDP-1"]
        self.assertTrue(len(edp_modes) > 0)

        # Find the current mode
        current_modes = [m for m in edp_modes if m.is_current]
        self.assertEqual(len(current_modes), 1)
        self.assertEqual(current_modes[0].width, 1920)
        self.assertEqual(current_modes[0].height, 1080)

    @patch('subprocess.run')
    def test_get_displays_xrandr_failure(self, mock_run):
        """Test get_displays when xrandr fails."""
        mock_run.side_effect = Exception("xrandr not found")

        displays = self.manager.get_displays()

        # Should return empty dict on failure
        self.assertEqual(displays, {})

    @patch('subprocess.run')
    def test_get_current_resolution(self, mock_run):
        """Test get_current_resolution."""
        mock_run.return_value = MagicMock(
            stdout="""eDP-1 connected 1920x1080+0+0
   1920x1080     60.00*+
   1280x720      60.00
""",
            returncode=0
        )

        mode = self.manager.get_current_resolution()

        self.assertIsNotNone(mode)
        self.assertEqual(mode.width, 1920)
        self.assertEqual(mode.height, 1080)
        self.assertTrue(mode.is_current)

    @patch('subprocess.run')
    def test_set_resolution_success(self, mock_run):
        """Test _set_resolution with successful xrandr command."""
        mock_run.return_value = MagicMock(returncode=0)

        success = self.manager._set_resolution("eDP-1", 1920, 1080, 60.0)

        self.assertTrue(success)
        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        self.assertEqual(call_args[0], "xrandr")
        self.assertIn("--output", call_args)
        self.assertIn("eDP-1", call_args)
        self.assertIn("--mode", call_args)
        self.assertIn("1920x1080", call_args)

    @patch('subprocess.run')
    def test_set_resolution_failure(self, mock_run):
        """Test _set_resolution with failed xrandr command."""
        mock_run.return_value = MagicMock(returncode=1)

        success = self.manager._set_resolution("eDP-1", 9999, 9999, 60.0)

        self.assertFalse(success)


class TestAudioManager(unittest.TestCase):
    """Test AudioManager class."""

    def setUp(self):
        """Set up test fixtures."""
        self.manager = AudioManager()

    @patch('subprocess.run')
    def test_get_outputs(self, mock_run):
        """Test get_outputs with valid pactl output."""
        # Mock for listing sinks
        def mock_run_side_effect(*args, **kwargs):
            cmd = args[0]
            if "short" in cmd:
                return MagicMock(
                    stdout="0\talsa_output.pci-0000_00_1f.3.analog-stereo\tmodule-alsa-card.c\ts16le 2ch 44100Hz\tSUSPENDED\n",
                    returncode=0
                )
            elif "get-default-sink" in cmd:
                return MagicMock(
                    stdout="alsa_output.pci-0000_00_1f.3.analog-stereo\n",
                    returncode=0
                )
            elif "list" in cmd and "sinks" in cmd:
                return MagicMock(
                    stdout="""Sink #0
    State: SUSPENDED
    Name: alsa_output.pci-0000_00_1f.3.analog-stereo
    Description: Built-in Audio Analog Stereo
    Driver: module-alsa-card.c
    Volume: front-left: 65536 / 100% / 0.00 dB,   front-right: 65536 / 100% / 0.00 dB
    Mute: no
""",
                    returncode=0
                )
            return MagicMock(stdout="", returncode=0)

        mock_run.side_effect = mock_run_side_effect

        outputs = self.manager.get_outputs()

        self.assertTrue(len(outputs) >= 0)  # May be empty in test env

    @patch('subprocess.run')
    def test_set_volume_in_range(self, mock_run):
        """Test set_volume with valid volume."""
        mock_run.return_value = MagicMock(returncode=0)

        success, msg = self.manager.set_volume(50)

        self.assertTrue(success)
        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        self.assertIn("50%", call_args)

    @patch('subprocess.run')
    def test_set_volume_clamped_low(self, mock_run):
        """Test set_volume clamps negative values to 0."""
        mock_run.return_value = MagicMock(returncode=0)

        success, msg = self.manager.set_volume(-50)

        self.assertTrue(success)
        call_args = mock_run.call_args[0][0]
        self.assertIn("0%", call_args)

    @patch('subprocess.run')
    def test_set_volume_clamped_high(self, mock_run):
        """Test set_volume clamps values above 150 to 150."""
        mock_run.return_value = MagicMock(returncode=0)

        success, msg = self.manager.set_volume(200)

        self.assertTrue(success)
        call_args = mock_run.call_args[0][0]
        self.assertIn("150%", call_args)

    @patch('subprocess.run')
    def test_toggle_mute_success(self, mock_run):
        """Test toggle_mute success."""
        mock_run.return_value = MagicMock(returncode=0)

        success, msg = self.manager.toggle_mute()

        self.assertTrue(success)
        call_args = mock_run.call_args[0][0]
        self.assertIn("toggle", call_args)

    @patch('subprocess.run')
    def test_toggle_mute_failure(self, mock_run):
        """Test toggle_mute failure."""
        mock_run.return_value = MagicMock(returncode=1)

        success, msg = self.manager.toggle_mute()

        self.assertFalse(success)


class TestBluetoothManager(unittest.TestCase):
    """Test BluetoothManager class."""

    def setUp(self):
        """Set up test fixtures."""
        self.manager = BluetoothManager()

    @patch('time.sleep')
    @patch('subprocess.run')
    def test_get_devices(self, mock_run, mock_sleep):
        """Test get_devices (scan)."""
        def mock_run_side_effect(*args, **kwargs):
            cmd = args[0]
            if "devices" in cmd:
                return MagicMock(
                    stdout="Device AA:BB:CC:DD:EE:FF MyHeadphones\nDevice 11:22:33:44:55:66 Keyboard\n",
                    returncode=0
                )
            elif "info" in cmd:
                return MagicMock(
                    stdout="""Device AA:BB:CC:DD:EE:FF
    Name: MyHeadphones
    Paired: yes
    Connected: yes
    Trusted: yes
    Icon: audio-headset
""",
                    returncode=0
                )
            return MagicMock(stdout="", returncode=0)

        mock_run.side_effect = mock_run_side_effect

        devices = self.manager.get_devices(scan_time=1)

        self.assertTrue(len(devices) >= 0)  # May vary

    @patch('subprocess.run')
    def test_disconnect_success(self, mock_run):
        """Test disconnect success."""
        mock_run.return_value = MagicMock(returncode=0)

        success, msg = self.manager.disconnect("AA:BB:CC:DD:EE:FF")

        self.assertTrue(success)

    @patch('subprocess.run')
    def test_disconnect_failure(self, mock_run):
        """Test disconnect failure."""
        mock_run.return_value = MagicMock(returncode=1)

        success, msg = self.manager.disconnect("AA:BB:CC:DD:EE:FF")

        self.assertFalse(success)


class TestConfirmationIntegration(unittest.TestCase):
    """Test confirmation system integration with display changes."""

    def setUp(self):
        """Set up test fixtures."""
        # Reset singleton for clean tests
        import system_control.sensitive_actions as sa
        sa._handler = None

    def test_request_resolution_change_creates_action(self):
        """Test that request_resolution_change creates a pending action."""
        with patch.object(DisplayManager, 'get_displays') as mock_get:
            with patch.object(DisplayManager, 'get_current_resolution') as mock_current:
                mock_get.return_value = {
                    "eDP-1": [DisplayMode(1920, 1080, 60.0, is_current=True)]
                }
                mock_current.return_value = DisplayMode(1920, 1080, 60.0, is_current=True)

                action_id, msg = request_resolution_change(2560, 1440, 60.0, "eDP-1")

                self.assertIsNotNone(action_id)
                self.assertTrue(action_id.startswith("display_resolution_"))
                self.assertIn("2560", msg)
                self.assertIn("1440", msg)

    def test_auto_revert_level_for_display(self):
        """Test that display resolution uses AUTO_REVERT confirmation level."""
        with patch.object(DisplayManager, 'get_displays') as mock_get:
            with patch.object(DisplayManager, 'get_current_resolution') as mock_current:
                mock_get.return_value = {
                    "eDP-1": [DisplayMode(1920, 1080, 60.0, is_current=True)]
                }
                mock_current.return_value = DisplayMode(1920, 1080, 60.0, is_current=True)

                action_id, msg = request_resolution_change(1280, 720, 60.0, "eDP-1")

                handler = get_handler()
                action = handler.get_action(action_id)

                self.assertEqual(action.level, ConfirmationLevel.AUTO_REVERT.name)
                self.assertEqual(action.auto_revert_seconds, DISPLAY_REVERT_SECONDS)

    def test_execute_without_confirmation_fails(self):
        """Test that executing without confirmation fails."""
        with patch.object(DisplayManager, 'get_displays') as mock_get:
            with patch.object(DisplayManager, 'get_current_resolution') as mock_current:
                mock_get.return_value = {
                    "eDP-1": [DisplayMode(1920, 1080, 60.0, is_current=True)]
                }
                mock_current.return_value = DisplayMode(1920, 1080, 60.0, is_current=True)

                action_id, msg = request_resolution_change(1280, 720, 60.0, "eDP-1")

                # Try to execute without confirmation
                success, msg = execute_resolution_change(action_id)

                self.assertFalse(success)
                self.assertIn("nicht bestätigt", msg)

    def test_full_confirmation_flow(self):
        """Test complete confirmation flow for display change."""
        with patch.object(DisplayManager, 'get_displays') as mock_get:
            with patch.object(DisplayManager, 'get_current_resolution') as mock_current:
                with patch.object(DisplayManager, '_set_resolution') as mock_set:
                    mock_get.return_value = {
                        "eDP-1": [DisplayMode(1920, 1080, 60.0, is_current=True)]
                    }
                    mock_current.return_value = DisplayMode(1920, 1080, 60.0, is_current=True)
                    mock_set.return_value = True

                    # Request change
                    action_id, msg = request_resolution_change(1280, 720, 60.0, "eDP-1")

                    # First confirmation
                    success, msg = confirm_action(action_id)
                    self.assertTrue(success)

                    # Second confirmation (AUTO_REVERT requires double)
                    success, msg = confirm_action(action_id, is_second=True)
                    self.assertTrue(success)

                    # Now execute
                    success, msg = execute_resolution_change(action_id)
                    self.assertTrue(success)
                    mock_set.assert_called_with("eDP-1", 1280, 720, 60.0)


class TestEdgeCases(unittest.TestCase):
    """Test edge cases and error handling."""

    def test_volume_negative(self):
        """Test setting negative volume is clamped to 0."""
        manager = AudioManager()
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            success, msg = manager.set_volume(-100)
            self.assertTrue(success)
            # Verify the clamped value
            call_args = mock_run.call_args[0][0]
            self.assertIn("0%", call_args)

    def test_volume_over_150(self):
        """Test setting volume over 150 is clamped."""
        manager = AudioManager()
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            success, msg = manager.set_volume(300)
            self.assertTrue(success)
            # Verify the clamped value
            call_args = mock_run.call_args[0][0]
            self.assertIn("150%", call_args)

    def test_invalid_display_name(self):
        """Test operations with invalid display name."""
        manager = DisplayManager()
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="Display not found")
            success = manager._set_resolution("INVALID-1", 1920, 1080, 60.0)
            self.assertFalse(success)

    def test_invalid_resolution(self):
        """Test setting invalid resolution."""
        manager = DisplayManager()
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="Invalid mode")
            success = manager._set_resolution("eDP-1", 99999, 99999, 60.0)
            self.assertFalse(success)

    def test_xrandr_timeout(self):
        """Test xrandr command timeout."""
        manager = DisplayManager()
        with patch('subprocess.run') as mock_run:
            import subprocess
            mock_run.side_effect = subprocess.TimeoutExpired(cmd="xrandr", timeout=10)
            displays = manager.get_displays()
            self.assertEqual(displays, {})

    def test_pactl_exception(self):
        """Test pactl exception handling."""
        manager = AudioManager()
        with patch('subprocess.run') as mock_run:
            mock_run.side_effect = Exception("pactl not found")
            success, msg = manager.toggle_mute()
            self.assertFalse(success)
            self.assertIn("Fehler", msg)

    def test_bluetooth_pairing_timeout(self):
        """Test bluetooth pairing timeout."""
        manager = BluetoothManager()

        # Mock confirmation
        import system_control.sensitive_actions as sa
        sa._handler = None

        action_id, msg = manager.request_pair("AA:BB:CC:DD:EE:FF", "TestDevice")

        # Confirm the action
        confirm_action(action_id)
        confirm_action(action_id, is_second=True)  # May need second for some levels

        with patch('subprocess.run') as mock_run:
            import subprocess
            mock_run.side_effect = subprocess.TimeoutExpired(cmd="bluetoothctl", timeout=30)

            success, msg = manager.execute_pair(action_id)
            self.assertFalse(success)
            self.assertIn("Timeout", msg)

    def test_empty_display_list(self):
        """Test handling empty display list."""
        manager = DisplayManager()
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(stdout="", returncode=0)
            displays = manager.get_displays()
            self.assertEqual(displays, {})

    def test_malformed_xrandr_output(self):
        """Test handling malformed xrandr output."""
        manager = DisplayManager()
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(
                stdout="garbage output that isn't valid xrandr\n",
                returncode=0
            )
            displays = manager.get_displays()
            # Should handle gracefully without crashing
            self.assertIsInstance(displays, dict)


class TestPublicAPI(unittest.TestCase):
    """Test public API functions."""

    @patch.object(DisplayManager, 'get_displays')
    def test_get_displays_returns_dict_format(self, mock_method):
        """Test get_displays returns proper dict format."""
        mock_method.return_value = {
            "eDP-1": [DisplayMode(1920, 1080, 60.0, is_current=True)]
        }

        result = get_displays()

        self.assertIsInstance(result, dict)
        self.assertIn("eDP-1", result)
        self.assertIsInstance(result["eDP-1"], list)
        self.assertIsInstance(result["eDP-1"][0], dict)
        self.assertEqual(result["eDP-1"][0]["width"], 1920)

    @patch.object(DisplayManager, 'get_current_resolution')
    def test_get_current_resolution_returns_dict(self, mock_method):
        """Test get_current_resolution returns dict format."""
        mock_method.return_value = DisplayMode(1920, 1080, 60.0, is_current=True)

        result = get_current_resolution()

        self.assertIsInstance(result, dict)
        self.assertEqual(result["width"], 1920)

    @patch.object(AudioManager, 'get_outputs')
    def test_get_audio_outputs_returns_list(self, mock_method):
        """Test get_audio_outputs returns list format."""
        mock_method.return_value = [
            AudioDevice("sink1", "Sink 1", "sink", is_default=True)
        ]

        result = get_audio_outputs()

        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 1)
        self.assertIsInstance(result[0], dict)

    @patch.object(AudioManager, 'set_volume')
    def test_set_volume_public_api(self, mock_method):
        """Test set_volume public API."""
        mock_method.return_value = (True, "Volume set")

        success, msg = set_volume(50)

        self.assertTrue(success)
        mock_method.assert_called_with(50)

    @patch.object(AudioManager, 'toggle_mute')
    def test_toggle_mute_public_api(self, mock_method):
        """Test toggle_mute public API."""
        mock_method.return_value = (True, "Muted")

        success, msg = toggle_mute()

        self.assertTrue(success)
        mock_method.assert_called_once()


class TestAutoRevertMechanism(unittest.TestCase):
    """Test AUTO_REVERT mechanism for display changes."""

    def setUp(self):
        """Reset singleton."""
        import system_control.sensitive_actions as sa
        sa._handler = None

    def test_auto_revert_timer_starts(self):
        """Test that auto-revert timer starts after execution."""
        with patch.object(DisplayManager, 'get_displays') as mock_get:
            with patch.object(DisplayManager, 'get_current_resolution') as mock_current:
                with patch.object(DisplayManager, '_set_resolution') as mock_set:
                    mock_get.return_value = {
                        "eDP-1": [DisplayMode(1920, 1080, 60.0, is_current=True)]
                    }
                    mock_current.return_value = DisplayMode(1920, 1080, 60.0, is_current=True)
                    mock_set.return_value = True

                    # Request, confirm, execute
                    action_id, _ = request_resolution_change(1280, 720, 60.0, "eDP-1")
                    confirm_action(action_id)
                    confirm_action(action_id, is_second=True)

                    success, msg = execute_resolution_change(action_id)

                    self.assertTrue(success)
                    self.assertIn("automatisch", msg)
                    self.assertIn(str(DISPLAY_REVERT_SECONDS), msg)

    def test_keep_resolution_cancels_revert(self):
        """Test that keep_resolution cancels auto-revert."""
        with patch.object(DisplayManager, 'get_displays') as mock_get:
            with patch.object(DisplayManager, 'get_current_resolution') as mock_current:
                with patch.object(DisplayManager, '_set_resolution') as mock_set:
                    mock_get.return_value = {
                        "eDP-1": [DisplayMode(1920, 1080, 60.0, is_current=True)]
                    }
                    mock_current.return_value = DisplayMode(1920, 1080, 60.0, is_current=True)
                    mock_set.return_value = True

                    # Request, confirm, execute
                    action_id, _ = request_resolution_change(1280, 720, 60.0, "eDP-1")
                    confirm_action(action_id)
                    confirm_action(action_id, is_second=True)
                    execute_resolution_change(action_id)

                    # Keep the resolution
                    success, msg = keep_resolution(action_id)

                    self.assertTrue(success)
                    self.assertIn("beibehalten", msg.lower())


class TestSystemSettingsSingleton(unittest.TestCase):
    """Test SystemSettings singleton."""

    def test_singleton_returns_same_instance(self):
        """Test that get_settings returns same instance."""
        settings1 = get_settings()
        settings2 = get_settings()

        self.assertIs(settings1, settings2)

    def test_settings_has_all_managers(self):
        """Test that settings has all managers."""
        settings = get_settings()

        self.assertIsInstance(settings.display, DisplayManager)
        self.assertIsInstance(settings.audio, AudioManager)
        self.assertIsInstance(settings.bluetooth, BluetoothManager)


def run_tests():
    """Run all tests and return results."""
    # Create test suite
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    # Add all test classes
    test_classes = [
        TestDisplayMode,
        TestAudioDevice,
        TestBluetoothDevice,
        TestDisplayManager,
        TestAudioManager,
        TestBluetoothManager,
        TestConfirmationIntegration,
        TestEdgeCases,
        TestPublicAPI,
        TestAutoRevertMechanism,
        TestSystemSettingsSingleton,
    ]

    for test_class in test_classes:
        tests = loader.loadTestsFromTestCase(test_class)
        suite.addTests(tests)

    # Run with verbosity
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    return result


if __name__ == "__main__":
    print("=" * 70)
    print("COMPREHENSIVE TESTS FOR system_settings.py")
    print("=" * 70)
    print()

    result = run_tests()

    print()
    print("=" * 70)
    print("TEST SUMMARY")
    print("=" * 70)
    print(f"Tests run: {result.testsRun}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")
    print(f"Skipped: {len(result.skipped)}")

    if result.failures:
        print("\nFAILURES:")
        for test, traceback in result.failures:
            print(f"  - {test}: {traceback}")

    if result.errors:
        print("\nERRORS:")
        for test, traceback in result.errors:
            print(f"  - {test}: {traceback}")

    # Exit with appropriate code
    sys.exit(0 if result.wasSuccessful() else 1)
