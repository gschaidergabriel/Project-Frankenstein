#!/usr/bin/env python3
"""
Chat Integration - Connects System Control to Chat Overlay

Provides context-aware detection and handling of system control requests
from natural language chat input.

Author: Frank AI System
"""

import logging
import re
from typing import Any, Callable, Dict, List, Optional, Tuple

from .sensitive_actions import (
    get_handler,
    confirm_action,
    get_pending_actions,
    ConfirmationState,
)

try:
    from tools.approval_queue import submit_request, check_response, ApprovalUrgency
except ImportError:
    submit_request = None  # Not available in standalone testing

# Import package management regex from constants (overlay)
try:
    from overlay.constants import PACKAGE_INSTALL_RE, PACKAGE_REMOVE_RE
except ImportError:
    # Fallback: define locally if constants not on import path
    PACKAGE_INSTALL_RE = re.compile(
        r"(installier|install|einricht|setup|hinzufüg|add\s|hol\s|"
        r"paket.{0,5}install|programm.{0,5}install|"
        r"apt.{0,5}install|pip.{0,5}install|snap.{0,5}install|flatpak.{0,5}install|"
        r"aktualisier|update|upgrade|system.{0,5}aktualisier|system.{0,5}update)",
        re.IGNORECASE,
    )
    PACKAGE_REMOVE_RE = re.compile(
        r"(deinstallier|uninstall|entfern.{0,5}paket|remove.{0,5}package|"
        r"apt.{0,5}remove|pip.{0,5}uninstall|snap.{0,5}remove|flatpak.{0,5}uninstall)",
        re.IGNORECASE,
    )

LOG = logging.getLogger("system_control.chat")


# =============================================================================
# Intent Detection Patterns (German + English)
# =============================================================================

# File organization patterns
FILE_ORGANIZE_RE = re.compile(
    r"(ordne|sortiere|aufräumen|räum.*auf|organisiere|organize|sort|clean.?up|"
    r"dateien.*ordnen|ordner.*aufräumen|downloads.*sortieren|"
    r"verschieb.*nach|move.*to|strukturiere)",
    re.IGNORECASE
)

# Undo patterns
UNDO_RE = re.compile(
    r"(rückgängig|undo|zurück|revert|wiederherstellen|"
    r"mach.*rückgängig|nimm.*zurück|das war falsch)",
    re.IGNORECASE
)

# Confirmation patterns
CONFIRM_YES_RE = re.compile(
    r"^(ja|yes|ok|okay|jep|jup|yep|yup|jo|sure|klar|mach|"
    r"ja.*mach|mach.*das|do it|go ahead|bestätige|confirm|"
    r"passt|genau|richtig|stimmt|ja bitte|ja gerne|"
    r"einverstanden|agreed|proceed)$",
    re.IGNORECASE
)

CONFIRM_NO_RE = re.compile(
    r"^(nein|no|nope|stop|halt|abbrechen|cancel|"
    r"nicht|lieber nicht|doch nicht|vergiss|forget|"
    r"lass|warte|stopp)$",
    re.IGNORECASE
)

# Keep resolution patterns (for auto-revert)
KEEP_RESOLUTION_RE = re.compile(
    r"(behalten|keep|passt.*so|ist gut|gefällt|looks good|"
    r"so lassen|bleibt so|nicht zurück|don't revert)",
    re.IGNORECASE
)

# WiFi/Network patterns
WIFI_RE = re.compile(
    r"(wlan|wifi|w-lan|netzwerk.*verbind|connect.*network|"
    r"wlan.*zeig|wifi.*scan|netzwerke|available.*networks|"
    r"internet.*verbind|verbind.*wlan)",
    re.IGNORECASE
)

DEVICE_DISCOVERY_RE = re.compile(
    r"(geräte.*netzwerk|devices.*network|was.*verbunden|"
    r"wer.*netzwerk|scan.*network|netzwerk.*scan|"
    r"zeig.*geräte|show.*devices|was ist im netzwerk)",
    re.IGNORECASE
)

# Bluetooth patterns
BLUETOOTH_RE = re.compile(
    r"(bluetooth|kopfhörer.*verbind|headphones.*connect|"
    r"koppeln|pairing|bt.*verbind|bluetooth.*scan|"
    r"kopplungsmodus|airpods|buds)",
    re.IGNORECASE
)

# Display/Resolution patterns
DISPLAY_RE = re.compile(
    r"(auflösung|resolution|bildschirm.*einstell|display.*settings|"
    r"monitor.*ändern|änder.*auflösung|change.*resolution|"
    r"\d+x\d+|fullhd|4k|1080p|1440p|2160p)",
    re.IGNORECASE
)

# Audio patterns
AUDIO_RE = re.compile(
    r"(lautstärke|volume|ton|sound|audio|mute|stumm|"
    r"lauter|leiser|louder|quieter|speaker|lautsprecher|"
    r"kopfhörer.*ausgabe|output.*device|audio.*gerät)",
    re.IGNORECASE
)

# Printer patterns
PRINTER_RE = re.compile(
    r"(drucker|printer|drucken|print|cups|"
    r"drucker.*einricht|setup.*printer|install.*printer|"
    r"drucker.*hinzufügen|add.*printer|neuer drucker)",
    re.IGNORECASE
)

# WiFi key from photo
WIFI_KEY_PHOTO_RE = re.compile(
    r"(wlan.*foto|wifi.*photo|passwort.*bild|password.*image|"
    r"router.*aufkleber|router.*sticker|scan.*qr|"
    r"foto.*passwort|schlüssel.*bild|key.*photo)",
    re.IGNORECASE
)

# WiFi on/off patterns
WIFI_TOGGLE_RE = re.compile(
    r"(wifi|wlan|w-lan).{0,10}(aus|ein|off|on|deaktiv|aktiv|abschalt|anschalt|"
    r"ausschalten|einschalten|disable|enable)|"
    r"(schalte?|mach).{0,10}(wifi|wlan).{0,10}(aus|ein|off|on)|"
    r"(internet|netz).{0,10}(aus|abschalt)",
    re.IGNORECASE
)

# App close patterns - NO confirmation needed
APP_CLOSE_RE = re.compile(
    r"(schließ|beende|kill|close|quit|exit|stopp|beenden|schliessen).{0,15}"
    r"(discord|blender|firefox|chrome|spotify|vscode|steam|gimp|inkscape|"
    r"vlc|obs|slack|telegram|signal|thunderbird|libreoffice|nautilus|"
    r"terminal|editor|app|programm|anwendung|fenster)|"
    r"(discord|blender|firefox|chrome|spotify|vscode|steam|gimp|inkscape|"
    r"vlc|obs|slack|telegram|signal|thunderbird|libreoffice).{0,10}"
    r"(schließen|beenden|zu|aus)",
    re.IGNORECASE
)

# List running apps
APP_LIST_RE = re.compile(
    r"(welche|was|zeig|list).{0,15}(apps?|programme?|anwendungen?|fenster).{0,10}"
    r"(laufen|offen|geöffnet|aktiv|running|open)|"
    r"(laufende?|offene?|aktive?).{0,10}(apps?|programme?|anwendungen?)",
    re.IGNORECASE
)

# Package search patterns (no install/remove, just searching)
PACKAGE_SEARCH_RE = re.compile(
    r"(such.{0,5}paket|search.{0,5}package|paket.{0,5}such|"
    r"gibt.{0,5}es.{0,10}paket|find.{0,5}package|"
    r"welche.{0,5}paket|available.{0,5}package)",
    re.IGNORECASE
)


class ChatIntegration:
    """
    Handles system control requests from chat input.

    Detects intent, manages confirmation state, and executes actions.
    """

    def __init__(self, response_callback: Optional[Callable[[str], None]] = None):
        """
        Args:
            response_callback: Function to send responses back to chat
        """
        self.response_callback = response_callback
        self._pending_action_id: Optional[str] = None
        self._pending_action_type: Optional[str] = None

    def set_response_callback(self, callback: Callable[[str], None]):
        """Set the callback for sending responses."""
        self.response_callback = callback

    def _respond(self, message: str):
        """Send response to chat."""
        if self.response_callback:
            self.response_callback(message)
        else:
            LOG.warning(f"No response callback set. Message: {message}")

    def process_message(self, message: str) -> Tuple[bool, Optional[str]]:
        """
        Process a chat message for system control intents.

        Args:
            message: User's chat message

        Returns:
            (handled, response) - True if handled, with optional response message
        """
        message = message.strip()

        # Check for pending confirmation first
        if self._pending_action_id:
            return self._handle_pending_confirmation(message)

        # Check for undo request
        if UNDO_RE.search(message):
            return self._handle_undo_request()

        # Check for file organization
        if FILE_ORGANIZE_RE.search(message):
            return self._handle_file_organize(message)

        # Check for app close - NO confirmation
        if APP_CLOSE_RE.search(message):
            return self._handle_app_close(message)

        # Check for list running apps
        if APP_LIST_RE.search(message):
            return self._handle_list_apps()

        # Check for WiFi on/off - needs confirmation
        if WIFI_TOGGLE_RE.search(message):
            return self._handle_wifi_toggle(message)

        # Check for WiFi/network scan - no confirmation
        if WIFI_RE.search(message):
            return self._handle_wifi_request(message)

        if DEVICE_DISCOVERY_RE.search(message):
            return self._handle_device_discovery()

        # Check for Bluetooth
        if BLUETOOTH_RE.search(message):
            return self._handle_bluetooth_request(message)

        # Check for display settings
        if DISPLAY_RE.search(message):
            return self._handle_display_request(message)

        # Check for audio
        if AUDIO_RE.search(message):
            return self._handle_audio_request(message)

        # Check for printer
        if PRINTER_RE.search(message):
            return self._handle_printer_request(message)

        # Check for package removal (before install, to avoid false match on "deinstallier")
        if PACKAGE_REMOVE_RE.search(message):
            return self._handle_package_remove(message)

        # Check for package install / update
        if PACKAGE_INSTALL_RE.search(message):
            return self._handle_package_install(message)

        # Check for package search
        if PACKAGE_SEARCH_RE.search(message):
            return self._handle_package_search(message)

        return False, None

    def _handle_pending_confirmation(self, message: str) -> Tuple[bool, Optional[str]]:
        """Handle confirmation for pending action."""
        action = get_handler().get_action(self._pending_action_id)

        if not action:
            self._pending_action_id = None
            self._pending_action_type = None
            return False, None

        # Check for resolution keep request
        if self._pending_action_type == "display_resolution" and KEEP_RESOLUTION_RE.search(message):
            from .system_settings import keep_resolution
            success, msg = keep_resolution(self._pending_action_id)
            self._pending_action_id = None
            self._pending_action_type = None
            return True, msg

        # Check for yes/confirm - SINGLE confirmation, then execute
        if CONFIRM_YES_RE.match(message):
            # Confirm the action
            success, msg = confirm_action(self._pending_action_id, is_second=False)

            if success:
                # Action confirmed, execute it immediately
                exec_success, exec_msg = self._execute_confirmed_action()
                self._pending_action_id = None
                self._pending_action_type = None
                return True, exec_msg

            self._pending_action_id = None
            self._pending_action_type = None
            return True, msg

        # Check for no/cancel
        if CONFIRM_NO_RE.match(message):
            from .sensitive_actions import cancel_pending_action
            cancel_pending_action(self._pending_action_id)
            self._pending_action_id = None
            self._pending_action_type = None
            return True, "Aktion abgebrochen."

        # Not a confirmation - might be a new request
        return False, None

    def _execute_confirmed_action(self) -> Tuple[bool, str]:
        """Execute the confirmed action based on type."""
        if not self._pending_action_id or not self._pending_action_type:
            return False, "Keine bestätigte Aktion vorhanden"

        action_type = self._pending_action_type

        if action_type == "file_organize":
            from .file_organizer import execute_organization
            return execute_organization(self._pending_action_id)

        elif action_type == "file_structure":
            from .file_organizer import execute_structure_creation
            return execute_structure_creation(self._pending_action_id)

        elif action_type == "wifi_connect":
            from .network_manager import execute_wifi_connect
            return execute_wifi_connect(self._pending_action_id)

        elif action_type == "wifi_toggle":
            from .network_manager import get_manager
            return get_manager().execute_wifi_toggle(self._pending_action_id)

        elif action_type == "display_resolution":
            from .system_settings import execute_resolution_change
            return execute_resolution_change(self._pending_action_id)

        elif action_type == "bluetooth_pair":
            from .system_settings import execute_bluetooth_pair
            return execute_bluetooth_pair(self._pending_action_id)

        elif action_type == "printer_setup":
            from .hardware_autosetup import execute_printer_setup
            return execute_printer_setup(self._pending_action_id)

        elif action_type == "package_install":
            from .package_manager import get_manager as get_pkg_manager, PackageBackend
            action = get_handler().get_action(self._pending_action_id)
            if action and action.params:
                mgr = get_pkg_manager()
                packages = action.params.get("packages", [])
                backend = PackageBackend(action.params.get("backend", "apt"))
                return mgr.install(packages, backend)
            return False, "Installationsdetails nicht gefunden."

        elif action_type == "package_remove":
            from .package_manager import get_manager as get_pkg_manager, PackageBackend
            action = get_handler().get_action(self._pending_action_id)
            if action and action.params:
                mgr = get_pkg_manager()
                packages = action.params.get("packages", [])
                backend = PackageBackend(action.params.get("backend", "apt"))
                return mgr.remove(packages, backend)
            return False, "Entfernungsdetails nicht gefunden."

        elif action_type == "system_update":
            from .package_manager import get_manager as get_pkg_manager
            return get_pkg_manager().execute_update()

        return False, f"Unbekannter Aktionstyp: {action_type}"

    def _handle_undo_request(self) -> Tuple[bool, Optional[str]]:
        """Handle undo request."""
        from .file_organizer import undo_last_organization, get_undo_preview

        preview = get_undo_preview()
        if not preview:
            return True, "Keine rückgängig machbare Aktion gefunden."

        success, msg = undo_last_organization()
        return True, msg

    def _handle_file_organize(self, message: str) -> Tuple[bool, Optional[str]]:
        """Handle file organization request."""
        from .file_organizer import request_organization

        # Extract folder from message
        folder = self._extract_folder_path(message)
        if not folder:
            folder = "~/Downloads"  # Default

        action_id, msg = request_organization(
            source_folder=folder,
            strategy="by_type",
            description=f"Dateien in {folder} nach Typ sortieren"
        )

        if action_id:
            self._pending_action_id = action_id
            self._pending_action_type = "file_organize"

        return True, msg

    def _handle_wifi_request(self, message: str) -> Tuple[bool, Optional[str]]:
        """Handle WiFi request."""
        from .network_manager import format_wifi_list, connect_wifi

        # Check if connecting to specific network (needs confirmation)
        ssid_match = re.search(r'verbind.*["\']([^"\']+)["\']|connect.*["\']([^"\']+)["\']', message)
        if ssid_match:
            ssid = ssid_match.group(1) or ssid_match.group(2)
            # Check for password
            pw_match = re.search(r'passwort[:\s]+["\']?([^\s"\']+)["\']?|password[:\s]+["\']?([^\s"\']+)["\']?', message, re.IGNORECASE)
            password = None
            if pw_match:
                password = pw_match.group(1) or pw_match.group(2)

            # Check for key from photo
            if WIFI_KEY_PHOTO_RE.search(message):
                # Extract image path
                img_match = re.search(r'["\']?(/[^\s"\']+\.(jpg|jpeg|png|gif))["\']?', message, re.IGNORECASE)
                if img_match:
                    action_id, msg = connect_wifi(ssid, key_image_path=img_match.group(1))
                    if action_id:
                        self._pending_action_id = action_id
                        self._pending_action_type = "wifi_connect"
                    return True, msg

            action_id, msg = connect_wifi(ssid, password)
            if action_id:
                self._pending_action_id = action_id
                self._pending_action_type = "wifi_connect"
            return True, msg

        # Just scan and show networks - NO confirmation needed
        return True, format_wifi_list()

    def _handle_device_discovery(self) -> Tuple[bool, Optional[str]]:
        """Handle device discovery request - NO confirmation needed."""
        from .network_manager import format_device_list
        return True, format_device_list()

    def _handle_wifi_toggle(self, message: str) -> Tuple[bool, Optional[str]]:
        """Handle WiFi on/off request - needs ONE confirmation."""
        from .network_manager import get_manager

        # Determine if turning on or off
        msg_lower = message.lower()
        turn_off = any(x in msg_lower for x in ["aus", "off", "deaktiv", "abschalt", "ausschalten", "disable"])
        turn_on = any(x in msg_lower for x in ["ein", "on", "aktiv", "anschalt", "einschalten", "enable"])

        if turn_off:
            action_id, msg = get_manager().set_wifi_enabled(False)
            if action_id:
                self._pending_action_id = action_id
                self._pending_action_type = "wifi_toggle"
            return True, msg

        elif turn_on:
            action_id, msg = get_manager().set_wifi_enabled(True)
            if action_id:
                self._pending_action_id = action_id
                self._pending_action_type = "wifi_toggle"
            return True, msg

        # Not clear what to do - show status
        enabled, status = get_manager().get_wifi_status()
        return True, f"{status}\n\nSage 'WiFi aus' oder 'WiFi ein' zum Umschalten."

    def _handle_app_close(self, message: str) -> Tuple[bool, Optional[str]]:
        """Handle app close request - NO confirmation needed."""
        from .app_manager import close_app

        # Extract app name from message
        app_name = self._extract_app_name(message)

        if not app_name:
            return True, "Welche App soll ich schließen? Sage z.B. 'Schließ Discord' oder 'Beende Firefox'."

        success, msg = close_app(app_name)
        return True, msg

    def _handle_list_apps(self) -> Tuple[bool, Optional[str]]:
        """Handle list running apps request - NO confirmation needed."""
        from .app_manager import list_running_apps
        return True, list_running_apps()

    def _extract_app_name(self, message: str) -> Optional[str]:
        """Extract app name from close command."""
        # Common apps
        apps = [
            "discord", "blender", "firefox", "chrome", "spotify", "vscode",
            "steam", "gimp", "inkscape", "vlc", "obs", "slack", "telegram",
            "signal", "thunderbird", "libreoffice", "nautilus", "terminal",
            "editor", "vs code", "visual studio"
        ]

        msg_lower = message.lower()

        for app in apps:
            if app in msg_lower:
                return app

        # Try to extract app name after close keywords
        match = re.search(
            r'(?:schließ|beende|close|quit|exit|stopp)\s+(?:die\s+|das\s+|den\s+)?(\w+)',
            msg_lower
        )
        if match:
            return match.group(1)

        return None

    def _handle_bluetooth_request(self, message: str) -> Tuple[bool, Optional[str]]:
        """Handle Bluetooth request."""
        from .system_settings import scan_bluetooth, request_bluetooth_pair

        # Check if pairing specific device
        device_match = re.search(r'koppel.*["\']([^"\']+)["\']|pair.*["\']([^"\']+)["\']', message)
        if device_match:
            device_name = device_match.group(1) or device_match.group(2)
            # Would need to find MAC from name - for now just scan
            pass

        # Scan and show devices
        devices = scan_bluetooth(scan_time=5)

        if not devices:
            return True, "Keine Bluetooth-Geräte gefunden. Stelle sicher, dass die Geräte im Pairing-Modus sind."

        lines = ["BLUETOOTH-GERÄTE:", "=" * 40, ""]
        for d in devices:
            status = []
            if d["connected"]:
                status.append("Verbunden")
            if d["paired"]:
                status.append("Gekoppelt")

            status_str = f" ({', '.join(status)})" if status else ""
            lines.append(f"  {d['name']}{status_str}")
            lines.append(f"    MAC: {d['mac']}")
            lines.append("")

        lines.append("Sage z.B. 'Koppel mit <Gerätename>' zum Verbinden.")

        return True, "\n".join(lines)

    def _handle_display_request(self, message: str) -> Tuple[bool, Optional[str]]:
        """Handle display settings request."""
        from .system_settings import get_displays, get_current_resolution, request_resolution_change

        # Check for specific resolution
        res_match = re.search(r'(\d{3,4})\s*x\s*(\d{3,4})', message)
        rate_match = re.search(r'@?\s*(\d+)\s*hz', message, re.IGNORECASE)

        if res_match:
            width = int(res_match.group(1))
            height = int(res_match.group(2))
            rate = float(rate_match.group(1)) if rate_match else 60.0

            action_id, msg = request_resolution_change(width, height, rate)
            if action_id:
                self._pending_action_id = action_id
                self._pending_action_type = "display_resolution"
            return True, msg

        # Show current displays
        displays = get_displays()
        current = get_current_resolution()

        lines = ["DISPLAY-EINSTELLUNGEN:", "=" * 40, ""]

        if current:
            lines.append(f"Aktuelle Auflösung: {current['width']}x{current['height']}@{current['refresh_rate']}Hz")
            lines.append("")

        lines.append("Verfügbare Modi:")
        for name, modes in displays.items():
            lines.append(f"\n{name}:")
            for mode in modes[:8]:
                marker = " *" if mode['is_current'] else ""
                pref = " (empfohlen)" if mode['is_preferred'] else ""
                lines.append(f"  {mode['width']}x{mode['height']}@{mode['refresh_rate']}Hz{marker}{pref}")

        lines.append("")
        lines.append("Sage z.B. 'Auflösung 1920x1080@60Hz' zum Ändern.")

        return True, "\n".join(lines)

    def _handle_audio_request(self, message: str) -> Tuple[bool, Optional[str]]:
        """Handle audio settings request - NO confirmation needed for volume/mute."""
        from .system_settings import get_audio_outputs, set_volume, toggle_mute

        # Volume change - direct execution, no confirmation
        vol_match = re.search(r'lautstärke\s*(\d+)|volume\s*(\d+)|(\d+)\s*%', message, re.IGNORECASE)
        if vol_match:
            vol = int(vol_match.group(1) or vol_match.group(2) or vol_match.group(3))
            success, msg = set_volume(vol)
            return True, msg

        # Mute toggle - direct execution, no confirmation
        if re.search(r'mute|stumm', message, re.IGNORECASE):
            success, msg = toggle_mute()
            return True, msg

        # Show audio devices - no confirmation needed
        outputs = get_audio_outputs()

        lines = ["AUDIO-AUSGABEN:", "=" * 40, ""]

        for out in outputs:
            default = " (STANDARD)" if out['is_default'] else ""
            vol = f" [{out['volume']}%]" if out['volume'] else ""
            muted = " [STUMM]" if out['muted'] else ""
            lines.append(f"  {out['description']}{default}{vol}{muted}")

        lines.append("")
        lines.append("Sage z.B. 'Lautstärke 50' oder 'Mute' zum Ändern.")

        return True, "\n".join(lines)

    def _handle_printer_request(self, message: str) -> Tuple[bool, Optional[str]]:
        """Handle printer request."""
        from .hardware_autosetup import detect_printers, format_printer_list, request_printer_setup

        printers = detect_printers()

        if not printers:
            return True, "Keine Drucker gefunden. Stelle sicher, dass der Drucker angeschlossen und eingeschaltet ist."

        # Check if setting up specific printer
        if re.search(r'einricht|setup|install|hinzufügen|add', message, re.IGNORECASE):
            if len(printers) == 1:
                # Set up the only printer
                action_id, msg = request_printer_setup(printers[0])
                if action_id:
                    self._pending_action_id = action_id
                    self._pending_action_type = "printer_setup"
                return True, msg
            else:
                # Multiple printers - show list
                return True, format_printer_list(printers) + "\n\nSage welchen Drucker ich einrichten soll."

        return True, format_printer_list(printers)

    # =========================================================================
    # Package Management Handlers
    # =========================================================================

    def _handle_package_install(self, message: str) -> Tuple[bool, Optional[str]]:
        """Handle package install or system update request."""
        from .package_manager import get_manager as get_pkg_manager, PackageBackend

        mgr = get_pkg_manager()
        msg_lower = message.lower()

        # Check for system update / upgrade request
        if re.search(r'(system.{0,5}(aktualisier|update|upgrade)|aktualisier.{0,5}system|'
                      r'update.{0,5}system|upgrade.{0,5}system|alle.{0,5}paket.{0,5}aktualisier)',
                      msg_lower):
            count, summary = mgr.check_updates()
            if count == 0:
                return True, summary

            # Register as pending action requiring confirmation
            from .sensitive_actions import get_handler as get_sa_handler, ConfirmationLevel
            action_id = get_sa_handler().register_action(
                action_type="system_update",
                description=f"System-Update: {count} Pakete aktualisieren",
                preview=summary,
                params={"count": count},
                level=ConfirmationLevel.SINGLE,
            )
            self._pending_action_id = action_id
            self._pending_action_type = "system_update"

            lines = [
                "SYSTEM-UPDATE:",
                "=" * 40,
                "",
                summary,
                "",
                "Sag 'ja' zum Bestaetigen oder 'nein' zum Abbrechen.",
            ]
            return True, "\n".join(lines)

        # Regular package install
        backend = mgr.detect_backend(message)
        packages = mgr.extract_packages(message)

        if not packages:
            return True, "Welche Pakete soll ich installieren? Sage z.B. 'Installiere htop' oder 'pip install requests'."

        # Validate first
        ok, err = mgr.validate(packages, backend)
        if not ok:
            return True, f"Kann nicht installieren: {err}"

        # Gather info for preview
        info_lines = ["PAKET-INSTALLATION:", "=" * 40, ""]
        info_lines.append(f"Backend: {backend.value}")
        info_lines.append(f"Pakete:  {', '.join(packages)}")
        info_lines.append("")

        for pkg in packages:
            info = mgr.get_info(pkg, backend)
            if info:
                info_lines.append(f"  {info.name}")
                if info.version:
                    info_lines.append(f"    Version: {info.version}")
                if info.description:
                    info_lines.append(f"    Beschreibung: {info.description}")
                if info.size_human:
                    info_lines.append(f"    Groesse: {info.size_human}")
                info_lines.append("")
            else:
                info_lines.append(f"  {pkg} (keine Details verfuegbar)")
                info_lines.append("")

        # Register as pending action
        from .sensitive_actions import get_handler as get_sa_handler, ConfirmationLevel
        action_id = get_sa_handler().register_action(
            action_type="package_install",
            description=f"Pakete installieren: {', '.join(packages)} ({backend.value})",
            preview="\n".join(info_lines),
            params={"packages": packages, "backend": backend.value},
            level=ConfirmationLevel.SINGLE,
        )
        self._pending_action_id = action_id
        self._pending_action_type = "package_install"

        info_lines.append("Sag 'ja' zum Bestaetigen oder 'nein' zum Abbrechen.")
        return True, "\n".join(info_lines)

    def _handle_package_search(self, message: str) -> Tuple[bool, Optional[str]]:
        """Handle package search request."""
        from .package_manager import get_manager as get_pkg_manager

        mgr = get_pkg_manager()
        backend = mgr.detect_backend(message)

        # Extract search term (remove search keywords)
        cleaned = re.sub(
            r'(such[e]?|search|find|paket[e]?|package[s]?|gibt es|welche|available|bitte|mal|mir)',
            '', message, flags=re.IGNORECASE
        ).strip()
        term = cleaned.split()[0] if cleaned.split() else ""

        if not term or len(term) < 2:
            return True, "Was soll ich suchen? Sage z.B. 'Suche Paket htop' oder 'Suche pip requests'."

        results = mgr.search(term, backend if backend != mgr.detect_backend("") else None)

        if not results:
            return True, f"Keine Pakete gefunden fuer '{term}'."

        lines = [f"PAKET-SUCHE: '{term}'", "=" * 40, ""]
        for r in results:
            lines.append(f"  [{r.backend.value}] {r.name}")
            if r.description:
                lines.append(f"    {r.description}")
            lines.append("")

        lines.append("Sage z.B. 'Installiere <paketname>' zum Installieren.")
        return True, "\n".join(lines)

    def _handle_package_remove(self, message: str) -> Tuple[bool, Optional[str]]:
        """Handle package removal request."""
        from .package_manager import get_manager as get_pkg_manager

        mgr = get_pkg_manager()
        backend = mgr.detect_backend(message)
        packages = mgr.extract_packages(message)

        if not packages:
            return True, "Welche Pakete soll ich entfernen? Sage z.B. 'Deinstalliere htop'."

        # Validate
        ok, err = mgr.validate(packages, backend)
        if not ok:
            return True, f"Kann nicht entfernen: {err}"

        # Check reverse dependencies for apt packages
        info_lines = ["PAKET-ENTFERNUNG:", "=" * 40, ""]
        info_lines.append(f"Backend: {backend.value}")
        info_lines.append(f"Pakete:  {', '.join(packages)}")
        info_lines.append("")

        from .package_manager import PackageBackend as PB
        if backend == PB.APT:
            for pkg in packages:
                rdeps = mgr._check_rdeps(pkg)
                if rdeps:
                    info_lines.append(f"  WARNUNG: '{pkg}' wird von {len(rdeps)} Paketen benoetigt:")
                    for dep in rdeps[:5]:
                        info_lines.append(f"    - {dep}")
                    if len(rdeps) > 5:
                        info_lines.append(f"    ... und {len(rdeps) - 5} weitere")
                    info_lines.append("")
                    info_lines.append("Entfernung koennte andere Programme beeintraechtigen!")
                    info_lines.append("")

        # Register as pending action
        from .sensitive_actions import get_handler as get_sa_handler, ConfirmationLevel
        action_id = get_sa_handler().register_action(
            action_type="package_remove",
            description=f"Pakete entfernen: {', '.join(packages)} ({backend.value})",
            preview="\n".join(info_lines),
            params={"packages": packages, "backend": backend.value},
            level=ConfirmationLevel.SINGLE,
        )
        self._pending_action_id = action_id
        self._pending_action_type = "package_remove"

        info_lines.append("Sag 'ja' zum Bestaetigen oder 'nein' zum Abbrechen.")
        return True, "\n".join(info_lines)

    def _extract_folder_path(self, message: str) -> Optional[str]:
        """Extract folder path from message."""
        # Common folder patterns
        patterns = [
            r'in\s+["\']?([~/][^\s"\']+)["\']?',
            r'folder\s+["\']?([~/][^\s"\']+)["\']?',
            r'ordner\s+["\']?([~/][^\s"\']+)["\']?',
            r'downloads',
            r'dokumente|documents',
            r'desktop',
        ]

        message_lower = message.lower()

        for pattern in patterns:
            match = re.search(pattern, message_lower)
            if match:
                # Check if we captured a path in group 1
                if match.lastindex and match.lastindex >= 1:
                    captured = match.group(1)
                    if captured and captured.startswith(("~", "/")):
                        return captured
                # Handle keyword matches
                matched_text = match.group(0)
                if "downloads" in matched_text:
                    return "~/Downloads"
                elif "dokument" in matched_text or "document" in matched_text:
                    return "~/Dokumente"
                elif "desktop" in matched_text:
                    return "~/Desktop"

        return None

    def has_pending_action(self) -> bool:
        """Check if there's a pending action awaiting confirmation."""
        return self._pending_action_id is not None

    def get_pending_action_type(self) -> Optional[str]:
        """Get the type of pending action."""
        return self._pending_action_type

    def cancel_pending(self):
        """Cancel any pending action."""
        if self._pending_action_id:
            from .sensitive_actions import cancel_pending_action
            cancel_pending_action(self._pending_action_id)
        self._pending_action_id = None
        self._pending_action_type = None


# Singleton
_integration: Optional[ChatIntegration] = None


def get_integration() -> ChatIntegration:
    """Get singleton integration."""
    global _integration
    if _integration is None:
        _integration = ChatIntegration()
    return _integration


# Public API

def process_system_control(message: str) -> Tuple[bool, Optional[str]]:
    """
    Process a message for system control intents.

    Returns:
        (handled, response) - True if handled with response message
    """
    return get_integration().process_message(message)


def set_response_callback(callback: Callable[[str], None]):
    """Set the response callback."""
    get_integration().set_response_callback(callback)


def has_pending_action() -> bool:
    """Check for pending action."""
    return get_integration().has_pending_action()


def get_pending_action_type() -> Optional[str]:
    """Get pending action type."""
    return get_integration().get_pending_action_type()


# Quick test
if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)

    print("=== Chat Integration Test ===")

    integration = get_integration()

    # Test messages
    test_messages = [
        "Kannst du bitte meine Downloads aufräumen?",
        "Zeig mir die verfügbaren WLAN-Netzwerke",
        "Welche Geräte sind im Netzwerk?",
        "Ändere die Auflösung auf 1920x1080",
        "Wie laut ist die Musik?",
        "Gibt es einen Drucker?",
    ]

    for msg in test_messages:
        print(f"\nUser: {msg}")
        handled, response = integration.process_message(msg)
        if handled:
            print(f"Frank: {response}")
        else:
            print("(Not a system control request)")
