#!/usr/bin/env python3
"""
Network Manager - WiFi, Device Discovery, and Smart Connection

Features:
- WiFi network scanning with open/secured sorting
- Device discovery by category
- WiFi key extraction from photos (via VCB Bridge)
- Secure connection with double opt-in
- Integration with network_sentinel.py

Author: Frank AI System
"""

import json
import logging
import re
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .sensitive_actions import (
    ConfirmationLevel,
    request_confirmation,
    is_action_confirmed,
    mark_action_executed,
)

LOG = logging.getLogger("system_control.network")

# Database path
try:
    from config.paths import SYSTEM_CONTROL_DIR as DB_DIR
except ImportError:
    DB_DIR = Path("/home/ai-core-node/aicore/database/system_control")
DB_DIR.mkdir(parents=True, exist_ok=True)
KNOWN_NETWORKS_FILE = DB_DIR / "known_networks.json"
DEVICE_CACHE_FILE = DB_DIR / "device_cache.json"


class NetworkSecurity(Enum):
    """WiFi security type."""
    OPEN = "open"
    WEP = "wep"
    WPA = "wpa"
    WPA2 = "wpa2"
    WPA3 = "wpa3"
    ENTERPRISE = "enterprise"


class DeviceCategory(Enum):
    """Device categories."""
    ROUTER = "router"
    COMPUTER = "computer"
    PHONE = "phone"
    TABLET = "tablet"
    TV = "tv"
    PRINTER = "printer"
    IOT = "iot"
    CAMERA = "camera"
    NAS = "nas"
    GAMING = "gaming"
    UNKNOWN = "unknown"


@dataclass
class WiFiNetwork:
    """Represents a WiFi network."""
    ssid: str
    bssid: str
    signal_strength: int  # dBm
    channel: int
    frequency: float  # GHz
    security: NetworkSecurity
    is_open: bool
    last_seen: str

    def to_dict(self) -> dict:
        return {
            "ssid": self.ssid,
            "bssid": self.bssid,
            "signal_strength": self.signal_strength,
            "channel": self.channel,
            "frequency": self.frequency,
            "security": self.security.value,
            "is_open": self.is_open,
            "last_seen": self.last_seen,
        }


@dataclass
class NetworkDevice:
    """Represents a network device."""
    ip: str
    mac: str
    hostname: str
    vendor: str
    category: DeviceCategory
    open_ports: List[int] = field(default_factory=list)
    services: Dict[int, str] = field(default_factory=dict)
    first_seen: str = ""
    last_seen: str = ""

    def to_dict(self) -> dict:
        return {
            "ip": self.ip,
            "mac": self.mac,
            "hostname": self.hostname,
            "vendor": self.vendor,
            "category": self.category.value,
            "open_ports": self.open_ports,
            "services": self.services,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
        }


class WiFiScanner:
    """Scans for available WiFi networks."""

    def __init__(self):
        self._last_scan: Optional[datetime] = None
        self._networks: List[WiFiNetwork] = []

    def scan(self, interface: str = None) -> List[WiFiNetwork]:
        """
        Scan for WiFi networks.

        Returns networks sorted: open first (green), then secured (red).
        """
        networks = []

        # Try nmcli first (most reliable)
        try:
            result = subprocess.run(
                ["nmcli", "-t", "-f", "SSID,BSSID,SIGNAL,CHAN,FREQ,SECURITY", "device", "wifi", "list", "--rescan", "yes"],
                capture_output=True,
                text=True,
                timeout=30
            )

            if result.returncode == 0:
                for line in result.stdout.strip().split("\n"):
                    if not line:
                        continue

                    parts = line.split(":")
                    if len(parts) >= 6:
                        ssid = parts[0]
                        bssid = ":".join(parts[1:7])  # MAC is 6 parts
                        remaining = ":".join(parts[7:]).split(":")

                        if len(remaining) >= 4:
                            signal = int(remaining[0]) if remaining[0].isdigit() else -100
                            channel = int(remaining[1]) if remaining[1].isdigit() else 0
                            freq_str = remaining[2]
                            security_str = remaining[3] if len(remaining) > 3 else ""

                            # Parse frequency
                            freq = 2.4
                            if "5" in freq_str:
                                freq = 5.0

                            # Parse security
                            security = self._parse_security(security_str)
                            is_open = security == NetworkSecurity.OPEN

                            network = WiFiNetwork(
                                ssid=ssid,
                                bssid=bssid,
                                signal_strength=int(signal / 2) - 100,  # Convert percentage to approx dBm
                                channel=channel,
                                frequency=freq,
                                security=security,
                                is_open=is_open,
                                last_seen=datetime.now().isoformat()
                            )
                            networks.append(network)

        except Exception as e:
            LOG.warning(f"nmcli scan failed: {e}")

        # Fallback: try iwlist
        if not networks:
            networks = self._scan_iwlist(interface)

        # Sort: open networks first (by signal), then secured (by signal)
        open_networks = sorted(
            [n for n in networks if n.is_open],
            key=lambda x: x.signal_strength,
            reverse=True
        )
        secured_networks = sorted(
            [n for n in networks if not n.is_open],
            key=lambda x: x.signal_strength,
            reverse=True
        )

        self._networks = open_networks + secured_networks
        self._last_scan = datetime.now()

        LOG.info(f"WiFi scan: {len(open_networks)} open, {len(secured_networks)} secured")
        return self._networks

    def _scan_iwlist(self, interface: str = None) -> List[WiFiNetwork]:
        """Fallback scan using iwlist."""
        networks = []

        if not interface:
            # Find wireless interface
            try:
                result = subprocess.run(
                    ["iwconfig"],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                for line in result.stdout.split("\n"):
                    if "IEEE 802.11" in line:
                        interface = line.split()[0]
                        break
            except Exception:
                interface = "wlan0"

        try:
            result = subprocess.run(
                ["sudo", "iwlist", interface, "scan"],
                capture_output=True,
                text=True,
                timeout=30
            )

            current = {}
            for line in result.stdout.split("\n"):
                line = line.strip()

                if "Cell" in line and "Address:" in line:
                    if current.get("bssid"):
                        networks.append(self._create_network_from_iwlist(current))
                    current = {"bssid": line.split("Address:")[1].strip()}

                elif "ESSID:" in line:
                    current["ssid"] = line.split('"')[1] if '"' in line else ""

                elif "Signal level=" in line:
                    match = re.search(r"Signal level=(-?\d+)", line)
                    if match:
                        current["signal"] = int(match.group(1))

                elif "Channel:" in line:
                    match = re.search(r"Channel:(\d+)", line)
                    if match:
                        current["channel"] = int(match.group(1))

                elif "Encryption key:" in line:
                    current["encrypted"] = "on" in line.lower()

                elif "WPA" in line or "WPA2" in line:
                    current["wpa"] = True

            if current.get("bssid"):
                networks.append(self._create_network_from_iwlist(current))

        except Exception as e:
            LOG.error(f"iwlist scan failed: {e}")

        return networks

    def _create_network_from_iwlist(self, data: dict) -> WiFiNetwork:
        """Create WiFiNetwork from iwlist data."""
        encrypted = data.get("encrypted", False)
        wpa = data.get("wpa", False)

        if not encrypted:
            security = NetworkSecurity.OPEN
        elif wpa:
            security = NetworkSecurity.WPA2
        else:
            security = NetworkSecurity.WEP

        return WiFiNetwork(
            ssid=data.get("ssid", ""),
            bssid=data.get("bssid", ""),
            signal_strength=data.get("signal", -100),
            channel=data.get("channel", 0),
            frequency=5.0 if data.get("channel", 0) > 14 else 2.4,
            security=security,
            is_open=security == NetworkSecurity.OPEN,
            last_seen=datetime.now().isoformat()
        )

    def _parse_security(self, security_str: str) -> NetworkSecurity:
        """Parse security string from nmcli."""
        security_str = security_str.upper()

        if not security_str or security_str == "--":
            return NetworkSecurity.OPEN
        elif "WPA3" in security_str:
            return NetworkSecurity.WPA3
        elif "WPA2" in security_str:
            return NetworkSecurity.WPA2
        elif "WPA" in security_str:
            return NetworkSecurity.WPA
        elif "WEP" in security_str:
            return NetworkSecurity.WEP
        elif "802.1X" in security_str or "ENTERPRISE" in security_str:
            return NetworkSecurity.ENTERPRISE

        return NetworkSecurity.WPA2  # Default assumption

    def get_networks(self) -> List[WiFiNetwork]:
        """Get cached networks."""
        return self._networks


class DeviceDiscovery:
    """Discovers and categorizes network devices."""

    # Vendor to category mapping
    VENDOR_CATEGORIES = {
        "apple": DeviceCategory.PHONE,
        "samsung": DeviceCategory.PHONE,
        "huawei": DeviceCategory.PHONE,
        "xiaomi": DeviceCategory.PHONE,
        "sony": DeviceCategory.TV,
        "lg": DeviceCategory.TV,
        "roku": DeviceCategory.TV,
        "amazon": DeviceCategory.IOT,
        "google": DeviceCategory.IOT,
        "hp": DeviceCategory.PRINTER,
        "canon": DeviceCategory.PRINTER,
        "epson": DeviceCategory.PRINTER,
        "brother": DeviceCategory.PRINTER,
        "synology": DeviceCategory.NAS,
        "qnap": DeviceCategory.NAS,
        "netgear": DeviceCategory.ROUTER,
        "tp-link": DeviceCategory.ROUTER,
        "asus": DeviceCategory.ROUTER,
        "linksys": DeviceCategory.ROUTER,
        "raspberry": DeviceCategory.IOT,
        "hikvision": DeviceCategory.CAMERA,
        "dahua": DeviceCategory.CAMERA,
        "ring": DeviceCategory.CAMERA,
        "nest": DeviceCategory.IOT,
        "philips": DeviceCategory.IOT,
        "nvidia": DeviceCategory.GAMING,
        "playstation": DeviceCategory.GAMING,
        "xbox": DeviceCategory.GAMING,
        "nintendo": DeviceCategory.GAMING,
    }

    def __init__(self):
        self._devices: Dict[str, NetworkDevice] = {}
        self._load_cache()

    def _load_cache(self):
        """Load device cache."""
        try:
            if DEVICE_CACHE_FILE.exists():
                data = json.loads(DEVICE_CACHE_FILE.read_text())
                for dev_data in data.get("devices", []):
                    dev = NetworkDevice(
                        ip=dev_data["ip"],
                        mac=dev_data["mac"],
                        hostname=dev_data.get("hostname", ""),
                        vendor=dev_data.get("vendor", ""),
                        category=DeviceCategory(dev_data.get("category", "unknown")),
                        open_ports=dev_data.get("open_ports", []),
                        services=dev_data.get("services", {}),
                        first_seen=dev_data.get("first_seen", ""),
                        last_seen=dev_data.get("last_seen", "")
                    )
                    self._devices[dev.ip] = dev
        except Exception as e:
            LOG.warning(f"Failed to load device cache: {e}")

    def _save_cache(self):
        """Save device cache."""
        try:
            data = {
                "timestamp": datetime.now().isoformat(),
                "devices": [d.to_dict() for d in self._devices.values()]
            }
            DEVICE_CACHE_FILE.write_text(json.dumps(data, indent=2))
        except Exception as e:
            LOG.error(f"Failed to save device cache: {e}")

    def discover(self) -> Dict[DeviceCategory, List[NetworkDevice]]:
        """
        Discover devices on the network using network_sentinel.

        Returns devices grouped by category (only categories with devices).
        """
        # Try to use network_sentinel
        try:
            from ..network_sentinel import scan_network, get_network_map

            # Quick scan
            devices_data = scan_network()

            for dev_data in devices_data:
                ip = dev_data["ip"]
                mac = dev_data.get("mac", "")
                hostname = dev_data.get("hostname", "")
                vendor = dev_data.get("vendor", "")

                # Categorize by vendor
                category = self._categorize_device(vendor, hostname, mac)

                now = datetime.now().isoformat()

                if ip in self._devices:
                    # Update existing
                    self._devices[ip].last_seen = now
                    self._devices[ip].hostname = hostname or self._devices[ip].hostname
                    self._devices[ip].vendor = vendor or self._devices[ip].vendor
                else:
                    # New device
                    self._devices[ip] = NetworkDevice(
                        ip=ip,
                        mac=mac,
                        hostname=hostname,
                        vendor=vendor,
                        category=category,
                        first_seen=now,
                        last_seen=now
                    )

        except ImportError:
            LOG.warning("network_sentinel not available, using fallback")
            self._discover_fallback()

        self._save_cache()

        # Group by category
        grouped: Dict[DeviceCategory, List[NetworkDevice]] = {}
        for device in self._devices.values():
            if device.category not in grouped:
                grouped[device.category] = []
            grouped[device.category].append(device)

        # Only return categories with devices
        return {k: v for k, v in grouped.items() if v}

    def _discover_fallback(self):
        """Fallback discovery using ARP cache."""
        try:
            arp_file = Path("/proc/net/arp")
            if arp_file.exists():
                for line in arp_file.read_text().split("\n")[1:]:
                    parts = line.split()
                    if len(parts) >= 4 and parts[2] != "0x0":
                        ip = parts[0]
                        mac = parts[3]

                        if ip not in self._devices and mac != "00:00:00:00:00:00":
                            self._devices[ip] = NetworkDevice(
                                ip=ip,
                                mac=mac,
                                hostname="",
                                vendor="",
                                category=DeviceCategory.UNKNOWN,
                                first_seen=datetime.now().isoformat(),
                                last_seen=datetime.now().isoformat()
                            )
        except Exception as e:
            LOG.error(f"Fallback discovery failed: {e}")

    def _categorize_device(self, vendor: str, hostname: str, mac: str) -> DeviceCategory:
        """Categorize device based on vendor, hostname, and MAC."""
        # Check vendor
        vendor_lower = vendor.lower()
        hostname_lower = hostname.lower()

        for vendor_key, category in self.VENDOR_CATEGORIES.items():
            if vendor_key in vendor_lower or vendor_key in hostname_lower:
                return category

        # Check hostname patterns
        if any(x in hostname_lower for x in ["router", "gateway", "ap-", "access"]):
            return DeviceCategory.ROUTER
        if any(x in hostname_lower for x in ["iphone", "android", "phone", "mobile"]):
            return DeviceCategory.PHONE
        if any(x in hostname_lower for x in ["ipad", "tablet"]):
            return DeviceCategory.TABLET
        if any(x in hostname_lower for x in ["laptop", "desktop", "pc-", "macbook"]):
            return DeviceCategory.COMPUTER
        if any(x in hostname_lower for x in ["tv", "chromecast", "firestick"]):
            return DeviceCategory.TV
        if any(x in hostname_lower for x in ["print", "deskjet", "laserjet"]):
            return DeviceCategory.PRINTER
        if any(x in hostname_lower for x in ["cam", "doorbell", "security"]):
            return DeviceCategory.CAMERA
        if any(x in hostname_lower for x in ["nas", "storage", "diskstation"]):
            return DeviceCategory.NAS

        return DeviceCategory.UNKNOWN

    def get_devices_by_category(self, category: DeviceCategory) -> List[NetworkDevice]:
        """Get devices of a specific category."""
        return [d for d in self._devices.values() if d.category == category]


class WiFiKeyExtractor:
    """Extracts WiFi keys from photos using VCB Bridge."""

    def __init__(self):
        self._vcb_available = False
        self._check_vcb()

    def _check_vcb(self):
        """Check if VCB Bridge is available."""
        try:
            from ..vcb_bridge import vcb_status
            status = vcb_status()
            self._vcb_available = status.get("enabled", False)
        except ImportError:
            LOG.warning("VCB Bridge not available")

    def extract_key_from_image(self, image_path: str) -> Optional[str]:
        """
        Extract WiFi key from an image (e.g., router sticker photo).

        Returns the extracted key or None.
        """
        if not self._vcb_available:
            LOG.warning("VCB Bridge not available for key extraction")
            return None

        try:
            from ..vcb_bridge import analyze_image

            prompt = (
                "This image shows a WiFi router sticker or network information. "
                "Find and extract ONLY the WiFi password/key/Kennwort/Schlüssel. "
                "Look for labels like: Password, Key, Kennwort, WPA-Key, Network Key, PIN. "
                "Return ONLY the password value, nothing else. "
                "If you cannot find a password, return 'NOT_FOUND'."
            )

            result = analyze_image(image_path, prompt)

            if result and result != "NOT_FOUND":
                # Clean up the result
                key = result.strip()
                # Remove common prefixes
                for prefix in ["Password:", "Key:", "Kennwort:", "WPA-Key:", "PIN:"]:
                    if key.lower().startswith(prefix.lower()):
                        key = key[len(prefix):].strip()

                # Validate: typical WiFi key is 8-63 characters
                if 8 <= len(key) <= 63:
                    LOG.info(f"Extracted WiFi key: {'*' * len(key)}")
                    return key

            LOG.warning("Could not extract WiFi key from image")
            return None

        except Exception as e:
            LOG.error(f"Key extraction failed: {e}")
            return None


class NetworkManager:
    """Main network management interface."""

    def __init__(self):
        self.wifi_scanner = WiFiScanner()
        self.device_discovery = DeviceDiscovery()
        self.key_extractor = WiFiKeyExtractor()
        self._known_networks = self._load_known_networks()

    def get_wifi_status(self) -> Tuple[bool, str]:
        """Get current WiFi status."""
        try:
            result = subprocess.run(
                ["nmcli", "radio", "wifi"],
                capture_output=True,
                text=True,
                timeout=5
            )
            enabled = "enabled" in result.stdout.lower()
            return enabled, "WiFi ist AN" if enabled else "WiFi ist AUS"
        except Exception as e:
            return False, f"Status unbekannt: {e}"

    def set_wifi_enabled(self, enabled: bool) -> Tuple[str, str]:
        """
        Enable or disable WiFi (requires confirmation).

        Returns:
            (action_id, confirmation_message)
        """
        action = "einschalten" if enabled else "ausschalten"
        preview = f"WiFi wird {'aktiviert' if enabled else 'deaktiviert'}."

        return request_confirmation(
            action_type="wifi_toggle",
            description=f"WiFi {action}",
            preview=preview,
            params={"enabled": enabled},
            level=ConfirmationLevel.SINGLE
        )

    def execute_wifi_toggle(self, action_id: str) -> Tuple[bool, str]:
        """Execute confirmed WiFi toggle."""
        if not is_action_confirmed(action_id):
            return False, "Aktion nicht bestätigt"

        from .sensitive_actions import get_handler
        action = get_handler().get_action(action_id)

        if not action:
            return False, "Aktion nicht gefunden"

        enabled = action.params.get("enabled", True)

        try:
            state = "on" if enabled else "off"
            result = subprocess.run(
                ["nmcli", "radio", "wifi", state],
                capture_output=True,
                text=True,
                timeout=10
            )

            if result.returncode == 0:
                mark_action_executed(action_id)
                return True, f"WiFi {'eingeschaltet' if enabled else 'ausgeschaltet'}!"
            else:
                return False, f"Fehler: {result.stderr}"

        except Exception as e:
            return False, f"Fehler: {e}"

    def _load_known_networks(self) -> Dict[str, str]:
        """Load known networks (SSID -> password)."""
        try:
            if KNOWN_NETWORKS_FILE.exists():
                return json.loads(KNOWN_NETWORKS_FILE.read_text())
        except Exception:
            pass
        return {}

    def _save_known_networks(self):
        """Save known networks."""
        try:
            KNOWN_NETWORKS_FILE.write_text(json.dumps(self._known_networks, indent=2))
        except Exception as e:
            LOG.error(f"Failed to save known networks: {e}")

    def scan_wifi(self) -> List[Dict[str, Any]]:
        """
        Scan for WiFi networks.

        Returns list sorted: open networks first (green), secured (red).
        """
        networks = self.wifi_scanner.scan()
        return [n.to_dict() for n in networks]

    def discover_devices(self) -> Dict[str, List[Dict[str, Any]]]:
        """
        Discover network devices grouped by category.

        Only returns categories with devices found.
        """
        grouped = self.device_discovery.discover()
        return {
            cat.value: [d.to_dict() for d in devices]
            for cat, devices in grouped.items()
        }

    def connect_wifi(
        self,
        ssid: str,
        password: Optional[str] = None,
        key_image_path: Optional[str] = None
    ) -> Tuple[str, str]:
        """
        Connect to a WiFi network with double opt-in.

        Args:
            ssid: Network SSID
            password: Network password (optional for open networks)
            key_image_path: Path to image containing WiFi key

        Returns:
            (action_id, confirmation_message)
        """
        # Find network in scan results
        network = None
        for n in self.wifi_scanner.get_networks():
            if n.ssid == ssid:
                network = n
                break

        # Extract key from image if provided
        if key_image_path and not password:
            password = self.key_extractor.extract_key_from_image(key_image_path)
            if not password:
                return "", "Konnte kein WiFi-Passwort aus dem Bild extrahieren"

        # Check if open or secured
        if network and network.is_open:
            # Open network
            preview = f"Verbinde mit offenem Netzwerk: {ssid}\nSignal: {network.signal_strength} dBm"
        else:
            # Secured network
            if not password:
                return "", f"Netzwerk '{ssid}' erfordert ein Passwort"

            preview = f"Verbinde mit geschütztem Netzwerk: {ssid}\nSicherheit: {network.security.value if network else 'WPA2'}"

        # Single confirmation for all network operations
        level = ConfirmationLevel.SINGLE

        return request_confirmation(
            action_type="wifi_connect",
            description=f"Mit WiFi verbinden: {ssid}",
            preview=preview,
            params={
                "ssid": ssid,
                "password": password,
                "security": network.security.value if network else "wpa2"
            },
            level=level
        )

    def execute_wifi_connect(self, action_id: str) -> Tuple[bool, str]:
        """Execute confirmed WiFi connection."""
        if not is_action_confirmed(action_id):
            return False, "Aktion nicht bestätigt"

        from .sensitive_actions import get_handler
        action = get_handler().get_action(action_id)

        if not action:
            return False, "Aktion nicht gefunden"

        ssid = action.params["ssid"]
        password = action.params.get("password")

        try:
            if password:
                # Connect with password
                result = subprocess.run(
                    ["nmcli", "device", "wifi", "connect", ssid, "password", password],
                    capture_output=True,
                    text=True,
                    timeout=30
                )
            else:
                # Connect to open network
                result = subprocess.run(
                    ["nmcli", "device", "wifi", "connect", ssid],
                    capture_output=True,
                    text=True,
                    timeout=30
                )

            if result.returncode == 0:
                # Save to known networks
                if password:
                    self._known_networks[ssid] = password
                    self._save_known_networks()

                mark_action_executed(action_id)
                return True, f"Erfolgreich mit '{ssid}' verbunden!"
            else:
                return False, f"Verbindung fehlgeschlagen: {result.stderr}"

        except subprocess.TimeoutExpired:
            return False, "Verbindung Timeout"
        except Exception as e:
            return False, f"Fehler: {e}"

    def format_wifi_list(self, networks: List[Dict[str, Any]]) -> str:
        """Format WiFi networks for display."""
        lines = ["VERFÜGBARE WLAN-NETZWERKE:", "=" * 40, ""]

        open_nets = [n for n in networks if n["is_open"]]
        secured_nets = [n for n in networks if not n["is_open"]]

        if open_nets:
            lines.append("OFFENE NETZWERKE (keine Authentifizierung):")
            for n in open_nets:
                signal = self._signal_bars(n["signal_strength"])
                lines.append(f"  {signal} {n['ssid']} ({n['frequency']}GHz)")
            lines.append("")

        if secured_nets:
            lines.append("GESCHÜTZTE NETZWERKE:")
            for n in secured_nets:
                signal = self._signal_bars(n["signal_strength"])
                security = n["security"].upper()
                lines.append(f"  {signal} {n['ssid']} [{security}] ({n['frequency']}GHz)")

        return "\n".join(lines)

    def _signal_bars(self, dbm: int) -> str:
        """Convert signal strength to bars."""
        if dbm >= -50:
            return "[||||]"
        elif dbm >= -60:
            return "[||| ]"
        elif dbm >= -70:
            return "[||  ]"
        elif dbm >= -80:
            return "[|   ]"
        else:
            return "[    ]"

    def format_device_list(self, devices: Dict[str, List[Dict[str, Any]]]) -> str:
        """Format discovered devices for display."""
        lines = ["ERKANNTE NETZWERK-GERÄTE:", "=" * 40, ""]

        category_names = {
            "router": "ROUTER/ACCESS POINTS",
            "computer": "COMPUTER",
            "phone": "SMARTPHONES",
            "tablet": "TABLETS",
            "tv": "TVs & STREAMING",
            "printer": "DRUCKER",
            "camera": "KAMERAS",
            "nas": "NETZWERKSPEICHER",
            "gaming": "GAMING-GERÄTE",
            "iot": "SMART HOME/IOT",
            "unknown": "SONSTIGE"
        }

        for cat, cat_devices in devices.items():
            if cat_devices:
                lines.append(f"{category_names.get(cat, cat.upper())}:")
                for d in cat_devices:
                    name = d["hostname"] or d["vendor"] or d["ip"]
                    lines.append(f"  - {name} ({d['ip']})")
                lines.append("")

        if not devices:
            lines.append("Keine Geräte gefunden.")

        return "\n".join(lines)


# Singleton
_manager: Optional[NetworkManager] = None


def get_manager() -> NetworkManager:
    """Get singleton manager."""
    global _manager
    if _manager is None:
        _manager = NetworkManager()
    return _manager


# Public API

def scan_wifi() -> List[Dict[str, Any]]:
    """Scan for WiFi networks."""
    return get_manager().scan_wifi()


def discover_devices() -> Dict[str, List[Dict[str, Any]]]:
    """Discover network devices."""
    return get_manager().discover_devices()


def connect_wifi(
    ssid: str,
    password: Optional[str] = None,
    key_image_path: Optional[str] = None
) -> Tuple[str, str]:
    """Request WiFi connection."""
    return get_manager().connect_wifi(ssid, password, key_image_path)


def execute_wifi_connect(action_id: str) -> Tuple[bool, str]:
    """Execute confirmed WiFi connection."""
    return get_manager().execute_wifi_connect(action_id)


def format_wifi_list() -> str:
    """Get formatted WiFi list."""
    networks = scan_wifi()
    return get_manager().format_wifi_list(networks)


def format_device_list() -> str:
    """Get formatted device list."""
    devices = discover_devices()
    return get_manager().format_device_list(devices)


# Quick test
if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)

    print("=== Network Manager Test ===")

    manager = get_manager()

    print("\n--- WiFi Scan ---")
    networks = manager.scan_wifi()
    print(manager.format_wifi_list(networks))

    print("\n--- Device Discovery ---")
    devices = manager.discover_devices()
    print(manager.format_device_list(devices))
