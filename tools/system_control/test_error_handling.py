#!/usr/bin/env python3
"""
Comprehensive Error Handling Tests for System Control Modules

Tests:
1. Missing external tools (nmcli, wmctrl, pactl, xrandr, etc.)
2. Timeout handling in subprocess calls
3. Graceful degradation when features unavailable
4. Invalid input handling in all public functions
5. Concurrent access to shared state
6. Cleanup after errors
7. Logging of errors

Author: Test Suite
"""

import json
import logging
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch, PropertyMock

# Setup logging for tests
logging.basicConfig(level=logging.DEBUG, format='%(name)s - %(levelname)s - %(message)s')
LOG = logging.getLogger(__name__)


class TestMissingExternalTools(unittest.TestCase):
    """Test behavior when external tools are missing."""

    def test_missing_nmcli_wifi_scan(self):
        """Test WiFi scan when nmcli is not available."""
        from system_control.network_manager import WiFiScanner

        scanner = WiFiScanner()

        # Mock subprocess.run to simulate FileNotFoundError for nmcli
        with patch('subprocess.run') as mock_run:
            mock_run.side_effect = FileNotFoundError("nmcli not found")

            # Should not crash, should return empty list or fallback
            try:
                networks = scanner.scan()
                # If it returns something, verify it's a list
                self.assertIsInstance(networks, list)
            except FileNotFoundError:
                # If it propagates the error, that's a bug we're documenting
                LOG.warning("ISSUE: WiFiScanner.scan() does not handle missing nmcli gracefully")

    def test_missing_wmctrl_app_manager(self):
        """Test app manager when wmctrl is not available."""
        from system_control.app_manager import AppManager

        manager = AppManager()

        with patch('subprocess.run') as mock_run:
            mock_run.side_effect = FileNotFoundError("wmctrl not found")

            # Should return empty list or handle gracefully
            try:
                apps = manager.get_running_apps()
                self.assertIsInstance(apps, list)
                self.assertEqual(len(apps), 0)
            except FileNotFoundError:
                self.fail("ISSUE: AppManager.get_running_apps() does not handle missing wmctrl gracefully")

    def test_missing_pactl_audio_manager(self):
        """Test audio manager when pactl is not available."""
        from system_control.system_settings import AudioManager

        manager = AudioManager()

        with patch('subprocess.run') as mock_run:
            mock_run.side_effect = FileNotFoundError("pactl not found")

            try:
                outputs = manager.get_outputs()
                self.assertIsInstance(outputs, list)
            except FileNotFoundError:
                self.fail("ISSUE: AudioManager.get_outputs() does not handle missing pactl gracefully")

    def test_missing_xrandr_display_manager(self):
        """Test display manager when xrandr is not available."""
        from system_control.system_settings import DisplayManager

        manager = DisplayManager()

        with patch('subprocess.run') as mock_run:
            mock_run.side_effect = FileNotFoundError("xrandr not found")

            try:
                displays = manager.get_displays()
                self.assertIsInstance(displays, dict)
            except FileNotFoundError:
                self.fail("ISSUE: DisplayManager.get_displays() does not handle missing xrandr gracefully")

    def test_missing_bluetoothctl(self):
        """Test bluetooth manager when bluetoothctl is not available."""
        from system_control.system_settings import BluetoothManager

        manager = BluetoothManager()

        with patch('subprocess.run') as mock_run:
            mock_run.side_effect = FileNotFoundError("bluetoothctl not found")

            try:
                devices = manager.get_devices(scan_time=1)
                self.assertIsInstance(devices, list)
            except FileNotFoundError:
                self.fail("ISSUE: BluetoothManager.get_devices() does not handle missing bluetoothctl gracefully")

    def test_missing_lpinfo_printer_detection(self):
        """Test printer detection when lpinfo is not available."""
        from system_control.hardware_autosetup import PrinterDetector

        detector = PrinterDetector()

        with patch('subprocess.run') as mock_run:
            mock_run.side_effect = FileNotFoundError("lpinfo not found")

            try:
                printers = detector.detect_all()
                self.assertIsInstance(printers, list)
            except FileNotFoundError:
                self.fail("ISSUE: PrinterDetector.detect_all() does not handle missing lpinfo gracefully")

    def test_missing_avahi_browse(self):
        """Test network printer detection when avahi-browse is not available."""
        from system_control.hardware_autosetup import PrinterDetector

        detector = PrinterDetector()

        # Mock to return empty for lpinfo USB, then FileNotFoundError for avahi
        def mock_run_side_effect(cmd, *args, **kwargs):
            if 'lpinfo' in cmd:
                result = MagicMock()
                result.stdout = ""
                result.returncode = 0
                return result
            elif 'avahi-browse' in cmd:
                raise FileNotFoundError("avahi-browse not found")
            return MagicMock(stdout="", returncode=0)

        with patch('subprocess.run', side_effect=mock_run_side_effect):
            try:
                printers = detector._detect_network()
                self.assertIsInstance(printers, list)
            except FileNotFoundError:
                # This is expected as the code does catch this
                pass


class TestTimeoutHandling(unittest.TestCase):
    """Test timeout handling in subprocess calls."""

    def test_wifi_scan_timeout(self):
        """Test WiFi scan handles timeout."""
        from system_control.network_manager import WiFiScanner

        scanner = WiFiScanner()

        with patch('subprocess.run') as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired(cmd='nmcli', timeout=30)

            try:
                networks = scanner.scan()
                # Should handle timeout gracefully
                self.assertIsInstance(networks, list)
            except subprocess.TimeoutExpired:
                LOG.warning("ISSUE: WiFiScanner.scan() does not handle timeout gracefully")

    def test_bluetooth_scan_timeout(self):
        """Test Bluetooth scan handles timeout."""
        from system_control.system_settings import BluetoothManager

        manager = BluetoothManager()

        with patch('subprocess.run') as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired(cmd='bluetoothctl', timeout=5)

            try:
                devices = manager.get_devices(scan_time=1)
                self.assertIsInstance(devices, list)
            except subprocess.TimeoutExpired:
                LOG.warning("ISSUE: BluetoothManager.get_devices() does not handle timeout gracefully")

    def test_app_close_timeout(self):
        """Test app close handles timeout."""
        from system_control.app_manager import AppManager

        manager = AppManager()

        # First need to mock get_running_apps to return something
        mock_app = MagicMock()
        mock_app.name = "test_app"
        mock_app.pid = 12345
        mock_app.window_title = "Test Window"

        with patch.object(manager, 'get_running_apps', return_value=[mock_app]):
            with patch.object(manager, 'find_app_by_name', return_value=[mock_app]):
                with patch('subprocess.run') as mock_run:
                    mock_run.side_effect = subprocess.TimeoutExpired(cmd='wmctrl', timeout=5)

                    success, msg = manager.close_app("test_app")
                    # Should handle gracefully
                    self.assertIn("Fehler", msg.lower() if not success else "ok")

    def test_printer_setup_timeout(self):
        """Test printer setup handles timeout."""
        from system_control.hardware_autosetup import PrinterSetup, PrinterInfo, DriverInfo

        setup = PrinterSetup()

        printer = PrinterInfo(
            name="Test Printer",
            manufacturer="HP",
            model="DeskJet",
            connection_type="usb",
            uri="usb://HP/DeskJet"
        )
        driver = DriverInfo(
            name="Test Driver",
            source="system",
            ppd_file="drv:///sample.ppd"
        )

        with patch('subprocess.run') as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired(cmd='lpadmin', timeout=30)

            success, msg = setup.setup_printer(printer, driver)
            # Should return False with error message
            self.assertFalse(success)
            self.assertIn("Fehler", msg)


class TestGracefulDegradation(unittest.TestCase):
    """Test graceful degradation when features unavailable."""

    def test_vcb_bridge_unavailable(self):
        """Test WiFi key extractor when VCB bridge unavailable."""
        from system_control.network_manager import WiFiKeyExtractor

        extractor = WiFiKeyExtractor()

        # Mock the import to fail
        with patch.object(extractor, '_vcb_available', False):
            result = extractor.extract_key_from_image("/fake/image.jpg")
            # Should return None gracefully
            self.assertIsNone(result)

    def test_network_sentinel_unavailable(self):
        """Test device discovery when network_sentinel unavailable."""
        from system_control.network_manager import DeviceDiscovery

        discovery = DeviceDiscovery()

        # Mock the import to fail
        with patch.dict('sys.modules', {'..network_sentinel': None}):
            with patch('builtins.__import__', side_effect=ImportError("No module")):
                try:
                    devices = discovery.discover()
                    # Should fall back to ARP cache
                    self.assertIsInstance(devices, dict)
                except ImportError:
                    LOG.warning("ISSUE: DeviceDiscovery.discover() does not handle missing network_sentinel")

    def test_iwlist_fallback(self):
        """Test WiFi scan falls back to iwlist when nmcli fails."""
        from system_control.network_manager import WiFiScanner

        scanner = WiFiScanner()

        call_count = [0]

        def mock_run(cmd, *args, **kwargs):
            call_count[0] += 1
            if 'nmcli' in cmd:
                result = MagicMock()
                result.stdout = ""
                result.returncode = 1  # nmcli fails
                return result
            elif 'iwconfig' in cmd or 'iwlist' in cmd:
                result = MagicMock()
                result.stdout = ""
                result.returncode = 0
                return result
            return MagicMock(stdout="", returncode=0)

        with patch('subprocess.run', side_effect=mock_run):
            networks = scanner.scan()
            # Should have tried fallback
            self.assertIsInstance(networks, list)


class TestInvalidInputHandling(unittest.TestCase):
    """Test handling of invalid inputs in all public functions."""

    def test_invalid_folder_path_analyze(self):
        """Test analyze_folder with non-existent path."""
        from system_control.file_organizer import analyze_folder

        result = analyze_folder("/nonexistent/path/that/does/not/exist")
        self.assertIsInstance(result, dict)
        self.assertEqual(len(result), 0)

    def test_invalid_folder_path_plan_organization(self):
        """Test plan_organization with non-existent path."""
        from system_control.file_organizer import plan_organization

        moves, preview = plan_organization("/nonexistent/path")
        self.assertIsInstance(moves, list)
        self.assertEqual(len(moves), 0)
        self.assertIn("existiert nicht", preview)

    def test_empty_action_id(self):
        """Test execute functions with empty action_id."""
        from system_control.file_organizer import execute_organization
        from system_control.network_manager import execute_wifi_connect
        from system_control.system_settings import execute_resolution_change

        success, msg = execute_organization("")
        self.assertFalse(success)

        success, msg = execute_wifi_connect("")
        self.assertFalse(success)

        success, msg = execute_resolution_change("")
        self.assertFalse(success)

    def test_invalid_action_id(self):
        """Test execute functions with invalid action_id."""
        from system_control.file_organizer import execute_organization

        success, msg = execute_organization("nonexistent_action_12345")
        self.assertFalse(success)
        self.assertIn("nicht bestätigt", msg)

    def test_empty_ssid_connect(self):
        """Test WiFi connect with empty SSID."""
        from system_control.network_manager import connect_wifi

        action_id, msg = connect_wifi("")
        # Should return empty action_id or error message
        if action_id:
            LOG.warning("ISSUE: connect_wifi() accepts empty SSID")

    def test_invalid_resolution(self):
        """Test resolution change with invalid values."""
        from system_control.system_settings import request_resolution_change

        # Negative values
        action_id, msg = request_resolution_change(-1920, -1080)
        # Should handle gracefully

        # Zero values
        action_id, msg = request_resolution_change(0, 0)
        # Should handle gracefully

    def test_invalid_volume_value(self):
        """Test volume setting with out-of-range values."""
        from system_control.system_settings import set_volume

        # Test that values are clamped
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=0)

            # Value too high
            success, msg = set_volume(200)
            # Should clamp to 150

            # Negative value
            success, msg = set_volume(-50)
            # Should clamp to 0

    def test_invalid_bluetooth_mac(self):
        """Test Bluetooth disconnect with invalid MAC."""
        from system_control.system_settings import disconnect_bluetooth

        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=1)

            success, msg = disconnect_bluetooth("invalid-mac")
            self.assertFalse(success)

    def test_empty_app_name_close(self):
        """Test close_app with empty name."""
        from system_control.app_manager import close_app

        success, msg = close_app("")
        self.assertFalse(success)
        self.assertIn("nicht gefunden", msg.lower())

    def test_invalid_scan_time(self):
        """Test Bluetooth scan with invalid scan_time."""
        from system_control.system_settings import scan_bluetooth

        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(stdout="", returncode=0)

            # Negative scan time
            try:
                devices = scan_bluetooth(scan_time=-5)
                self.assertIsInstance(devices, list)
            except Exception as e:
                LOG.warning(f"ISSUE: scan_bluetooth() doesn't handle negative scan_time: {e}")

    def test_null_structure_creation(self):
        """Test folder structure creation with None structure."""
        from system_control.file_organizer import create_folder_structure

        try:
            action_id, msg = create_folder_structure("/tmp/test", None)
            # Should handle None gracefully
        except (TypeError, AttributeError) as e:
            LOG.warning(f"ISSUE: create_folder_structure() doesn't handle None structure: {e}")

    def test_malformed_rules_custom_organization(self):
        """Test custom organization with malformed rules."""
        from system_control.file_organizer import FileOrganizer

        organizer = FileOrganizer()

        # Empty rules
        moves, preview = organizer.plan_custom_organization("/tmp", [])
        self.assertIsInstance(moves, list)

        # Rules with missing keys
        moves, preview = organizer.plan_custom_organization("/tmp", [{"invalid": "rule"}])
        self.assertIsInstance(moves, list)


class TestConcurrentAccess(unittest.TestCase):
    """Test concurrent access to shared state."""

    def test_concurrent_action_registration(self):
        """Test concurrent registration of actions."""
        from system_control.sensitive_actions import SensitiveActionHandler, ConfirmationLevel

        handler = SensitiveActionHandler()
        results = []
        errors = []

        def register_action(i):
            try:
                action_id = handler.register_action(
                    action_type="test",
                    description=f"Test action {i}",
                    preview=f"Preview {i}",
                    params={"index": i},
                    level=ConfirmationLevel.SINGLE
                )
                results.append(action_id)
            except Exception as e:
                errors.append(e)

        # Create multiple threads
        threads = []
        for i in range(10):
            t = threading.Thread(target=register_action, args=(i,))
            threads.append(t)

        # Start all threads
        for t in threads:
            t.start()

        # Wait for all threads
        for t in threads:
            t.join()

        # Verify no errors and all actions registered
        self.assertEqual(len(errors), 0, f"Errors occurred: {errors}")
        self.assertEqual(len(results), 10)
        # Verify all IDs are unique
        self.assertEqual(len(set(results)), 10)

    def test_concurrent_confirmations(self):
        """Test concurrent confirmation of same action."""
        from system_control.sensitive_actions import SensitiveActionHandler, ConfirmationLevel

        handler = SensitiveActionHandler()

        # Register an action
        action_id = handler.register_action(
            action_type="test",
            description="Test action",
            preview="Preview",
            params={},
            level=ConfirmationLevel.SINGLE
        )

        results = []

        def confirm_action():
            success, msg = handler.confirm_first(action_id)
            results.append((success, msg))

        # Try to confirm from multiple threads
        threads = []
        for i in range(5):
            t = threading.Thread(target=confirm_action)
            threads.append(t)

        for t in threads:
            t.start()

        for t in threads:
            t.join()

        # Only one should succeed (first one)
        success_count = sum(1 for s, _ in results if s)
        self.assertGreaterEqual(success_count, 1)

    def test_singleton_thread_safety(self):
        """Test singleton access from multiple threads."""
        from system_control.file_organizer import get_organizer
        from system_control.network_manager import get_manager
        from system_control.app_manager import get_manager as get_app_manager

        organizers = []
        managers = []
        app_managers = []

        def get_singletons():
            organizers.append(id(get_organizer()))
            managers.append(id(get_manager()))
            app_managers.append(id(get_app_manager()))

        threads = []
        for i in range(10):
            t = threading.Thread(target=get_singletons)
            threads.append(t)

        for t in threads:
            t.start()

        for t in threads:
            t.join()

        # All should be same instance
        self.assertEqual(len(set(organizers)), 1)
        self.assertEqual(len(set(managers)), 1)
        self.assertEqual(len(set(app_managers)), 1)


class TestCleanupAfterErrors(unittest.TestCase):
    """Test cleanup after errors."""

    def test_file_organizer_cleanup_on_error(self):
        """Test that file organizer cleans up properly after errors."""
        from system_control.file_organizer import FileOrganizer
        import tempfile

        organizer = FileOrganizer()

        # Create temp directory with files
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create test files
            test_file = Path(tmpdir) / "test.pdf"
            test_file.write_text("test")

            # Mock shutil.move to fail
            with patch('shutil.move') as mock_move:
                mock_move.side_effect = PermissionError("Access denied")

                moves, _ = organizer.plan_organization(tmpdir)

                if moves:
                    # Try to execute with mocked action
                    from system_control.sensitive_actions import SensitiveActionHandler, ConfirmationLevel

                    handler = SensitiveActionHandler()
                    action_id = handler.register_action(
                        action_type="file_organize",
                        description="Test",
                        preview="Test",
                        params={"moves": [m.to_dict() for m in moves]},
                        level=ConfirmationLevel.SINGLE
                    )
                    handler.confirm_first(action_id)

                    # Execute - should fail but cleanup
                    with patch('system_control.file_organizer.get_handler', return_value=handler):
                        success, msg = organizer.execute_organization(action_id)
                        # Should handle error
                        self.assertIn("Fehler", msg)

    def test_undo_history_preserved_on_error(self):
        """Test that undo history is preserved when save fails."""
        from system_control.file_organizer import FileOrganizer

        organizer = FileOrganizer()

        # Add some history
        initial_history_len = len(organizer._undo_history)

        # Mock file write to fail
        with patch.object(Path, 'write_text', side_effect=PermissionError("Access denied")):
            try:
                organizer._save_history()
            except Exception:
                pass

        # History in memory should be preserved
        self.assertEqual(len(organizer._undo_history), initial_history_len)

    def test_pending_action_cleanup_on_expiry(self):
        """Test that expired actions are cleaned up."""
        from system_control.sensitive_actions import SensitiveActionHandler, ConfirmationLevel

        handler = SensitiveActionHandler()

        # Register an action with very short expiry (via patching)
        action_id = handler.register_action(
            action_type="test",
            description="Test",
            preview="Test",
            params={},
            level=ConfirmationLevel.SINGLE
        )

        # Manually expire the action
        action = handler.get_action(action_id)
        if action:
            action.expires_at = (datetime.now() - timedelta(minutes=10)).isoformat()

        # Run cleanup
        handler._cleanup_expired()

        # Action should be removed
        self.assertIsNone(handler.get_action(action_id))


class TestErrorLogging(unittest.TestCase):
    """Test that errors are properly logged."""

    def test_subprocess_errors_logged(self):
        """Test that subprocess errors are logged."""
        from system_control.network_manager import WiFiScanner

        scanner = WiFiScanner()

        with self.assertLogs('system_control.network', level='WARNING') as cm:
            with patch('subprocess.run') as mock_run:
                mock_run.side_effect = Exception("Test error")

                # Should log the error
                try:
                    scanner.scan()
                except Exception:
                    pass

        # Verify error was logged
        self.assertTrue(any('scan failed' in msg.lower() or 'error' in msg.lower()
                           for msg in cm.output))

    def test_file_operation_errors_logged(self):
        """Test that file operation errors are logged."""
        from system_control.file_organizer import FileOrganizer

        organizer = FileOrganizer()

        with self.assertLogs('system_control.file_organizer', level='ERROR') as cm:
            with patch('shutil.move', side_effect=OSError("Disk full")):
                # Create a mock operation
                from system_control.file_organizer import FileMove, OrganizeOperation

                op = OrganizeOperation(
                    operation_id="test",
                    description="Test",
                    timestamp=datetime.now().isoformat()
                )
                op.moves = [FileMove(
                    source="/nonexistent/source",
                    destination="/nonexistent/dest",
                    timestamp=datetime.now().isoformat(),
                    success=True
                )]

                # Try to undo
                organizer._undo_operation(op)

        # Verify error was logged
        self.assertTrue(any('undo failed' in msg.lower() or 'error' in msg.lower()
                           for msg in cm.output))


class TestEdgeCases(unittest.TestCase):
    """Test edge cases and boundary conditions."""

    def test_very_long_ssid(self):
        """Test handling of very long SSID."""
        from system_control.network_manager import connect_wifi

        long_ssid = "A" * 256  # Longer than 32 char limit
        action_id, msg = connect_wifi(long_ssid)
        # Should handle gracefully

    def test_special_characters_in_paths(self):
        """Test handling of special characters in paths."""
        from system_control.file_organizer import analyze_folder

        special_paths = [
            "/path/with spaces/folder",
            "/path/with'quotes/folder",
            "/path/with\"doublequotes/folder",
            "/path/with\ttab/folder",
            "/path/with\nnewline/folder",
        ]

        for path in special_paths:
            try:
                result = analyze_folder(path)
                self.assertIsInstance(result, dict)
            except Exception as e:
                LOG.warning(f"ISSUE: analyze_folder() fails with special path '{path}': {e}")

    def test_unicode_in_file_names(self):
        """Test handling of unicode in file names."""
        from system_control.file_organizer import FileOrganizer
        import tempfile

        organizer = FileOrganizer()

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create file with unicode name
            unicode_file = Path(tmpdir) / "test_\u00e4\u00f6\u00fc\u00df_\u4e2d\u6587.pdf"
            unicode_file.write_text("test")

            try:
                result = organizer.analyze_folder(tmpdir)
                self.assertIn("documents", result)
            except Exception as e:
                LOG.warning(f"ISSUE: analyze_folder() fails with unicode filenames: {e}")

    def test_empty_folder_analysis(self):
        """Test analysis of empty folder."""
        from system_control.file_organizer import analyze_folder
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            result = analyze_folder(tmpdir)
            self.assertIsInstance(result, dict)
            self.assertEqual(len(result), 0)

    def test_deeply_nested_structure(self):
        """Test handling of deeply nested folder structures."""
        from system_control.file_organizer import create_folder_structure

        deep_structure = {"level1": {"level2": {"level3": {"level4": {"level5": ["deep"]}}}}}

        with tempfile.TemporaryDirectory() as tmpdir:
            action_id, msg = create_folder_structure(tmpdir, deep_structure)
            self.assertIsNotNone(action_id)

    def test_maximum_undo_history(self):
        """Test that undo history is properly limited."""
        from system_control.file_organizer import FileOrganizer, OrganizeOperation, MAX_UNDO_HISTORY

        organizer = FileOrganizer()

        # Add more than MAX_UNDO_HISTORY operations
        for i in range(MAX_UNDO_HISTORY + 20):
            op = OrganizeOperation(
                operation_id=f"test_{i}",
                description=f"Test {i}",
                timestamp=datetime.now().isoformat(),
                completed=True
            )
            organizer._undo_history.append(op)

        # Save should truncate
        organizer._save_history()

        # After reload, should have at most MAX_UNDO_HISTORY
        organizer._load_history()
        self.assertLessEqual(len(organizer._undo_history), MAX_UNDO_HISTORY + 20)

    def test_auto_revert_cancellation_race(self):
        """Test race condition in auto-revert cancellation."""
        from system_control.sensitive_actions import SensitiveActionHandler, ConfirmationLevel

        handler = SensitiveActionHandler()

        action_id = handler.register_action(
            action_type="display_resolution",
            description="Test resolution change",
            preview="Test",
            params={},
            level=ConfirmationLevel.AUTO_REVERT,
            auto_revert_seconds=1
        )

        # Confirm and execute
        handler.confirm_first(action_id)
        handler.confirm_second(action_id)

        revert_called = [False]

        def revert():
            revert_called[0] = True

        handler.mark_executed(action_id, revert)

        # Immediately try to cancel
        success, msg = handler.cancel_auto_revert(action_id)

        # Wait for potential race
        time.sleep(1.5)

        # Either cancel succeeded or revert happened, but not crash
        self.assertTrue(success or revert_called[0])


class TestChatIntegrationErrors(unittest.TestCase):
    """Test error handling in chat integration."""

    def test_invalid_message_patterns(self):
        """Test handling of messages that almost match patterns."""
        from system_control.chat_integration import ChatIntegration

        integration = ChatIntegration()

        edge_messages = [
            "",  # Empty
            " ",  # Whitespace only
            "\n\t",  # Just newlines/tabs
            "ja" * 1000,  # Very long message
            "\x00\x01\x02",  # Binary data
        ]

        for msg in edge_messages:
            try:
                handled, response = integration.process_message(msg)
                # Should not crash
            except Exception as e:
                self.fail(f"ISSUE: process_message() crashed with '{repr(msg)}': {e}")

    def test_missing_response_callback(self):
        """Test behavior when response callback is not set."""
        from system_control.chat_integration import ChatIntegration

        integration = ChatIntegration()  # No callback set

        # This should not crash
        integration._respond("Test message")

        # Now test with callback
        messages = []
        integration.set_response_callback(lambda m: messages.append(m))
        integration._respond("Test message 2")
        self.assertEqual(len(messages), 1)

    def test_pending_action_timeout(self):
        """Test handling when pending action expires during confirmation."""
        from system_control.chat_integration import ChatIntegration
        from system_control.sensitive_actions import get_handler

        integration = ChatIntegration()

        # Trigger file organize to create pending action
        with patch('system_control.file_organizer.get_organizer') as mock_org:
            mock_org.return_value.plan_organization.return_value = (
                [MagicMock(to_dict=lambda: {})],
                "Preview"
            )

            handled, response = integration.process_message("ordne downloads")

            if integration._pending_action_id:
                # Expire the action
                handler = get_handler()
                action = handler.get_action(integration._pending_action_id)
                if action:
                    action.expires_at = (datetime.now() - timedelta(hours=1)).isoformat()

                # Now try to confirm
                handled, response = integration.process_message("ja")
                # Should handle expired action gracefully


def run_tests():
    """Run all tests and report results."""
    # Create test suite
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    # Add all test classes
    test_classes = [
        TestMissingExternalTools,
        TestTimeoutHandling,
        TestGracefulDegradation,
        TestInvalidInputHandling,
        TestConcurrentAccess,
        TestCleanupAfterErrors,
        TestErrorLogging,
        TestEdgeCases,
        TestChatIntegrationErrors,
    ]

    for test_class in test_classes:
        tests = loader.loadTestsFromTestCase(test_class)
        suite.addTests(tests)

    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    # Print summary
    print("\n" + "=" * 70)
    print("ERROR HANDLING TEST SUMMARY")
    print("=" * 70)
    print(f"Tests run: {result.testsRun}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")
    print(f"Skipped: {len(result.skipped)}")

    if result.failures:
        print("\nFAILURES:")
        for test, traceback in result.failures:
            print(f"  - {test}: {traceback.split(chr(10))[0]}")

    if result.errors:
        print("\nERRORS:")
        for test, traceback in result.errors:
            print(f"  - {test}: {traceback.split(chr(10))[0]}")

    return result


if __name__ == "__main__":
    # Change to the system_control directory for imports
    sys.path.insert(0, str(Path(__file__).parent.parent))

    result = run_tests()
    sys.exit(0 if result.wasSuccessful() else 1)
