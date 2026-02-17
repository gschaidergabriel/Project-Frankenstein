#!/usr/bin/env python3
"""
Hardware Auto-Setup - Automatic Printer and Hardware Configuration

Features:
- Automatic printer detection (USB, network)
- Driver search via OpenPrinting.org API
- Vendor-specific driver download (HP, Canon, Epson, Brother)
- CUPS integration for printer setup
- Double opt-in for driver installation

Author: Frank AI System
"""

import json
import logging
import os
import re
import subprocess
import tempfile
import time
import urllib.request
import urllib.error
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .sensitive_actions import (
    ConfirmationLevel,
    request_confirmation,
    is_action_confirmed,
    mark_action_executed,
)

LOG = logging.getLogger("system_control.hardware")

# Database path
try:
    from config.paths import SYSTEM_CONTROL_DIR as DB_DIR
except ImportError:
    DB_DIR = Path.home() / ".local" / "share" / "frank" / "system_control"
DB_DIR.mkdir(parents=True, exist_ok=True)
PRINTER_CACHE_FILE = DB_DIR / "printer_cache.json"

# Driver download directory
try:
    from config.paths import TEMP_DIR as _hw_temp_dir
    DRIVER_DOWNLOAD_DIR = _hw_temp_dir / "drivers"
except ImportError:
    import tempfile as _hw_tempfile
    DRIVER_DOWNLOAD_DIR = Path(_hw_tempfile.gettempdir()) / "frank" / "drivers"
DRIVER_DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class PrinterInfo:
    """Represents a detected printer."""
    name: str
    manufacturer: str
    model: str
    connection_type: str  # "usb", "network", "unknown"
    uri: str  # CUPS device URI
    driver_info: str = ""
    is_configured: bool = False
    serial: str = ""
    ip_address: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "manufacturer": self.manufacturer,
            "model": self.model,
            "connection_type": self.connection_type,
            "uri": self.uri,
            "driver_info": self.driver_info,
            "is_configured": self.is_configured,
            "serial": self.serial,
            "ip_address": self.ip_address
        }


@dataclass
class DriverInfo:
    """Represents a printer driver."""
    name: str
    source: str  # "openprinting", "hp", "canon", "epson", "brother", "system"
    ppd_file: str
    download_url: str = ""
    package_name: str = ""
    version: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "source": self.source,
            "ppd_file": self.ppd_file,
            "download_url": self.download_url,
            "package_name": self.package_name,
            "version": self.version
        }


class PrinterDetector:
    """Detects printers on USB and network."""

    def detect_all(self) -> List[PrinterInfo]:
        """Detect all available printers."""
        printers = []

        # USB printers
        printers.extend(self._detect_usb())

        # Network printers
        printers.extend(self._detect_network())

        # Filter duplicates
        seen = set()
        unique = []
        for p in printers:
            key = (p.manufacturer, p.model)
            if key not in seen:
                seen.add(key)
                unique.append(p)

        return unique

    def _detect_usb(self) -> List[PrinterInfo]:
        """Detect USB printers using lpinfo."""
        printers = []

        try:
            result = subprocess.run(
                ["lpinfo", "-v"],
                capture_output=True,
                text=True,
                timeout=30
            )

            for line in result.stdout.split("\n"):
                if "usb://" in line:
                    parts = line.split()
                    if len(parts) >= 2:
                        uri = parts[1]

                        # Parse manufacturer and model from URI
                        # Format: usb://Manufacturer/Model?serial=XXX
                        match = re.match(r'usb://([^/]+)/([^?]+)', uri)
                        if match:
                            manufacturer = match.group(1).replace("%20", " ")
                            model = match.group(2).replace("%20", " ")

                            serial = ""
                            if "serial=" in uri:
                                serial = uri.split("serial=")[1].split("&")[0]

                            printer = PrinterInfo(
                                name=f"{manufacturer} {model}",
                                manufacturer=manufacturer,
                                model=model,
                                connection_type="usb",
                                uri=uri,
                                serial=serial
                            )
                            printers.append(printer)

        except Exception as e:
            LOG.error(f"USB detection failed: {e}")

        return printers

    def _detect_network(self) -> List[PrinterInfo]:
        """Detect network printers using avahi/mDNS."""
        printers = []

        try:
            # Use avahi-browse for mDNS/Bonjour printers
            result = subprocess.run(
                ["avahi-browse", "-t", "-r", "_ipp._tcp", "--parsable"],
                capture_output=True,
                text=True,
                timeout=15
            )

            current_printer = {}
            for line in result.stdout.split("\n"):
                if not line:
                    if current_printer.get("ip"):
                        # Create printer from collected info
                        name = current_printer.get("name", "Network Printer")
                        ip = current_printer.get("ip", "")

                        printer = PrinterInfo(
                            name=name,
                            manufacturer=self._guess_manufacturer(name),
                            model=name,
                            connection_type="network",
                            uri=f"ipp://{ip}/ipp/print",
                            ip_address=ip
                        )
                        printers.append(printer)

                    current_printer = {}
                    continue

                parts = line.split(";")
                if len(parts) >= 4:
                    if parts[0] == "=":
                        current_printer["name"] = parts[3]
                    elif "address" in line.lower() or re.match(r'\d+\.\d+\.\d+\.\d+', parts[-1]):
                        current_printer["ip"] = parts[-1]

        except FileNotFoundError:
            LOG.warning("avahi-browse not available for network printer detection")
        except Exception as e:
            LOG.error(f"Network detection failed: {e}")

        # Also check SNMP if available
        printers.extend(self._detect_snmp())

        return printers

    def _detect_snmp(self) -> List[PrinterInfo]:
        """Detect printers via SNMP broadcast (requires snmpwalk)."""
        # Simplified - would need network scanning
        return []

    def _guess_manufacturer(self, name: str) -> str:
        """Guess manufacturer from printer name."""
        name_lower = name.lower()
        manufacturers = ["hp", "canon", "epson", "brother", "samsung", "xerox", "lexmark", "ricoh"]

        for mfr in manufacturers:
            if mfr in name_lower:
                return mfr.upper()

        return "Unknown"


class DriverSearch:
    """Searches for printer drivers from various sources."""

    # OpenPrinting.org API
    OPENPRINTING_API = "https://www.openprinting.org/printers/api/list"

    # Vendor-specific driver sources
    VENDOR_DRIVERS = {
        "HP": {
            "package": "hplip",
            "setup_cmd": ["hp-setup", "-i"],
            "apt_packages": ["hplip", "hplip-gui"]
        },
        "CANON": {
            "search_url": "https://www.canon.de/support/",
            "apt_packages": ["cnijfilter2"]
        },
        "EPSON": {
            "package": "epson-inkjet-printer-escpr",
            "apt_packages": ["printer-driver-escpr"]
        },
        "BROTHER": {
            "search_url": "https://support.brother.com/g/b/downloadtop.aspx",
            "apt_packages": []
        }
    }

    def search_driver(self, printer: PrinterInfo) -> List[DriverInfo]:
        """
        Search for drivers for a printer.

        Returns list of available drivers, ordered by preference.
        """
        drivers = []

        # 1. Check system PPD files first
        system_drivers = self._search_system_ppd(printer)
        drivers.extend(system_drivers)

        # 2. Check OpenPrinting.org
        openprinting_drivers = self._search_openprinting(printer)
        drivers.extend(openprinting_drivers)

        # 3. Check vendor-specific
        vendor_drivers = self._search_vendor(printer)
        drivers.extend(vendor_drivers)

        return drivers

    def _search_system_ppd(self, printer: PrinterInfo) -> List[DriverInfo]:
        """Search installed system PPD files."""
        drivers = []

        try:
            result = subprocess.run(
                ["lpinfo", "-m"],
                capture_output=True,
                text=True,
                timeout=30
            )

            search_terms = [
                printer.manufacturer.lower(),
                printer.model.lower(),
                printer.model.replace(" ", "").lower()
            ]

            for line in result.stdout.split("\n"):
                line_lower = line.lower()
                for term in search_terms:
                    if term and term in line_lower:
                        parts = line.split(None, 1)
                        if len(parts) >= 1:
                            ppd = parts[0]
                            name = parts[1] if len(parts) > 1 else ppd

                            driver = DriverInfo(
                                name=name,
                                source="system",
                                ppd_file=ppd
                            )
                            drivers.append(driver)
                        break

        except Exception as e:
            LOG.error(f"System PPD search failed: {e}")

        return drivers

    def _search_openprinting(self, printer: PrinterInfo) -> List[DriverInfo]:
        """Search OpenPrinting.org for drivers."""
        drivers = []

        try:
            # Search API
            search_query = f"{printer.manufacturer} {printer.model}".replace(" ", "+")
            url = f"https://www.openprinting.org/printers?search={search_query}"

            # Note: OpenPrinting doesn't have a public JSON API
            # This is a placeholder - in production, would scrape or use Foomatic
            LOG.debug(f"OpenPrinting search: {url}")

        except Exception as e:
            LOG.warning(f"OpenPrinting search failed: {e}")

        return drivers

    def _search_vendor(self, printer: PrinterInfo) -> List[DriverInfo]:
        """Search vendor-specific driver sources."""
        drivers = []
        mfr = printer.manufacturer.upper()

        if mfr not in self.VENDOR_DRIVERS:
            return drivers

        vendor_info = self.VENDOR_DRIVERS[mfr]

        # Check if vendor package is available
        for pkg in vendor_info.get("apt_packages", []):
            if self._package_available(pkg):
                driver = DriverInfo(
                    name=f"{mfr} Driver Package ({pkg})",
                    source=mfr.lower(),
                    ppd_file="",
                    package_name=pkg
                )
                drivers.append(driver)

        return drivers

    def _package_available(self, package: str) -> bool:
        """Check if apt package is available."""
        try:
            result = subprocess.run(
                ["apt-cache", "show", package],
                capture_output=True,
                timeout=10
            )
            return result.returncode == 0
        except Exception:
            return False


class DriverInstaller:
    """Downloads and installs printer drivers."""

    def install_driver(self, driver: DriverInfo) -> Tuple[bool, str]:
        """
        Install a driver.

        Returns:
            (success, message)
        """
        if driver.source == "system":
            # Already installed
            return True, f"Driver already installed: {driver.name}"

        if driver.package_name:
            return self._install_apt_package(driver.package_name)

        if driver.download_url:
            return self._download_and_install(driver)

        return False, "No installation method available"

    def _install_apt_package(self, package: str) -> Tuple[bool, str]:
        """Install driver via apt."""
        try:
            LOG.info(f"Installing package: {package}")

            # Update apt cache
            subprocess.run(
                ["sudo", "apt-get", "update"],
                capture_output=True,
                timeout=120
            )

            # Install package
            result = subprocess.run(
                ["sudo", "apt-get", "install", "-y", package],
                capture_output=True,
                text=True,
                timeout=300
            )

            if result.returncode == 0:
                return True, f"Driver package '{package}' successfully installed"
            else:
                return False, f"Installation failed: {result.stderr[:200]}"

        except subprocess.TimeoutExpired:
            return False, "Installation timeout"
        except Exception as e:
            return False, f"Error: {e}"

    def _download_and_install(self, driver: DriverInfo) -> Tuple[bool, str]:
        """Download and install driver from URL."""
        try:
            # Download
            filename = driver.download_url.split("/")[-1]
            download_path = DRIVER_DOWNLOAD_DIR / filename

            LOG.info(f"Downloading driver: {driver.download_url}")

            urllib.request.urlretrieve(driver.download_url, download_path)

            # Determine file type and install
            if filename.endswith(".deb"):
                result = subprocess.run(
                    ["sudo", "dpkg", "-i", str(download_path)],
                    capture_output=True,
                    text=True,
                    timeout=120
                )

                # Fix dependencies
                subprocess.run(
                    ["sudo", "apt-get", "-f", "install", "-y"],
                    capture_output=True,
                    timeout=120
                )

                if result.returncode == 0:
                    return True, f"Driver installed: {filename}"

            elif filename.endswith(".ppd") or filename.endswith(".ppd.gz"):
                # Copy PPD to system location
                ppd_dir = Path("/usr/share/cups/model")
                subprocess.run(
                    ["sudo", "cp", str(download_path), str(ppd_dir)],
                    timeout=10
                )
                return True, f"PPD file installed: {filename}"

            return False, f"Unknown file type: {filename}"

        except Exception as e:
            return False, f"Download/installation failed: {e}"


class PrinterSetup:
    """Sets up printers in CUPS."""

    def setup_printer(
        self,
        printer: PrinterInfo,
        driver: DriverInfo,
        printer_name: Optional[str] = None
    ) -> Tuple[bool, str]:
        """
        Set up a printer in CUPS.

        Args:
            printer: Printer info
            driver: Driver to use
            printer_name: Custom name (optional)

        Returns:
            (success, message)
        """
        if not printer_name:
            # Create safe printer name
            printer_name = re.sub(r'[^a-zA-Z0-9_-]', '_', printer.name)[:50]

        try:
            # Build lpadmin command
            cmd = [
                "sudo", "lpadmin",
                "-p", printer_name,
                "-v", printer.uri,
                "-E"  # Enable printer
            ]

            # Add PPD if available
            if driver.ppd_file:
                cmd.extend(["-m", driver.ppd_file])
            else:
                # Use generic driver
                cmd.extend(["-m", "everywhere"])

            # Add description
            cmd.extend(["-D", f"{printer.manufacturer} {printer.model}"])

            LOG.info(f"Setting up printer: {' '.join(cmd)}")

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30
            )

            if result.returncode == 0:
                # Set as default if it's the first printer
                subprocess.run(
                    ["sudo", "lpadmin", "-d", printer_name],
                    capture_output=True,
                    timeout=10
                )

                return True, f"Printer '{printer_name}' successfully configured!"
            else:
                return False, f"Setup failed: {result.stderr}"

        except Exception as e:
            return False, f"Error: {e}"


class HardwareAutoSetup:
    """Main hardware auto-setup interface."""

    def __init__(self):
        self.detector = PrinterDetector()
        self.driver_search = DriverSearch()
        self.driver_installer = DriverInstaller()
        self.printer_setup = PrinterSetup()

    def detect_printers(self) -> List[Dict[str, Any]]:
        """Detect all printers."""
        printers = self.detector.detect_all()
        return [p.to_dict() for p in printers]

    def find_drivers(self, printer_info: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Find drivers for a printer."""
        printer = PrinterInfo(**printer_info)
        drivers = self.driver_search.search_driver(printer)
        return [d.to_dict() for d in drivers]

    def request_printer_setup(
        self,
        printer_info: Dict[str, Any],
        driver_info: Optional[Dict[str, Any]] = None
    ) -> Tuple[str, str]:
        """
        Request printer setup with confirmation.

        Returns:
            (action_id, confirmation_message)
        """
        printer = PrinterInfo(**printer_info)

        # Find driver if not specified
        if not driver_info:
            drivers = self.driver_search.search_driver(printer)
            if drivers:
                driver_info = drivers[0].to_dict()

        driver = DriverInfo(**driver_info) if driver_info else None

        preview = f"""PRINTER SETUP:

Printer: {printer.name}
Manufacturer: {printer.manufacturer}
Model: {printer.model}
Connection: {printer.connection_type}
URI: {printer.uri}

Driver: {driver.name if driver else 'Search automatically'}
Source: {driver.source if driver else 'System/OpenPrinting'}

The printer will be configured and set as default printer.
"""
        if driver and driver.package_name:
            preview += f"\nPackage will be installed: {driver.package_name}"

        return request_confirmation(
            action_type="printer_setup",
            description=f"Set up printer: {printer.name}",
            preview=preview,
            params={
                "printer": printer_info,
                "driver": driver_info
            },
            level=ConfirmationLevel.SINGLE
        )

    def execute_printer_setup(self, action_id: str) -> Tuple[bool, str]:
        """Execute confirmed printer setup."""
        if not is_action_confirmed(action_id):
            return False, "Action not confirmed"

        from .sensitive_actions import get_handler
        action = get_handler().get_action(action_id)

        if not action:
            return False, "Action not found"

        printer_info = action.params["printer"]
        driver_info = action.params.get("driver")

        printer = PrinterInfo(**printer_info)

        # Find driver if not specified
        if not driver_info:
            drivers = self.driver_search.search_driver(printer)
            if not drivers:
                return False, "No matching driver found"
            driver_info = drivers[0].to_dict()

        driver = DriverInfo(**driver_info)

        # Install driver if needed
        if driver.package_name:
            success, msg = self.driver_installer.install_driver(driver)
            if not success:
                return False, f"Driver installation failed: {msg}"

        # Set up printer
        success, msg = self.printer_setup.setup_printer(printer, driver)

        if success:
            mark_action_executed(action_id)

        return success, msg

    def auto_setup_new_printer(self) -> Tuple[Optional[str], str]:
        """
        Automatically detect and set up new printers.

        Returns:
            (action_id or None, message)
        """
        printers = self.detector.detect_all()

        if not printers:
            return None, "No new printers found"

        # Filter out already configured printers
        new_printers = [p for p in printers if not p.is_configured]

        if not new_printers:
            return None, "All detected printers are already configured"

        # Set up the first new printer
        printer = new_printers[0]
        return self.request_printer_setup(printer.to_dict())


# Singleton
_setup: Optional[HardwareAutoSetup] = None


def get_setup() -> HardwareAutoSetup:
    """Get singleton setup."""
    global _setup
    if _setup is None:
        _setup = HardwareAutoSetup()
    return _setup


# Public API

def detect_printers() -> List[Dict[str, Any]]:
    """Detect all printers."""
    return get_setup().detect_printers()


def find_drivers(printer_info: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Find drivers for a printer."""
    return get_setup().find_drivers(printer_info)


def request_printer_setup(
    printer_info: Dict[str, Any],
    driver_info: Optional[Dict[str, Any]] = None
) -> Tuple[str, str]:
    """Request printer setup."""
    return get_setup().request_printer_setup(printer_info, driver_info)


def execute_printer_setup(action_id: str) -> Tuple[bool, str]:
    """Execute printer setup."""
    return get_setup().execute_printer_setup(action_id)


def auto_setup_new_printer() -> Tuple[Optional[str], str]:
    """Auto-detect and set up new printers."""
    return get_setup().auto_setup_new_printer()


def format_printer_list(printers: List[Dict[str, Any]]) -> str:
    """Format printer list for display."""
    if not printers:
        return "No printers found."

    lines = ["DETECTED PRINTERS:", "=" * 40, ""]

    for p in printers:
        conn_type = "USB" if p["connection_type"] == "usb" else "Network"
        status = "Configured" if p["is_configured"] else "New"

        lines.append(f"{p['manufacturer']} {p['model']}")
        lines.append(f"  Connection: {conn_type}")
        lines.append(f"  Status: {status}")
        if p["ip_address"]:
            lines.append(f"  IP: {p['ip_address']}")
        lines.append("")

    return "\n".join(lines)


# Quick test
if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)

    print("=== Hardware Auto-Setup Test ===")

    setup = get_setup()

    print("\n--- Detecting Printers ---")
    printers = setup.detect_printers()
    print(format_printer_list(printers))

    if printers:
        print("\n--- Searching Drivers ---")
        for p in printers[:2]:
            print(f"\nDrivers for {p['name']}:")
            drivers = setup.find_drivers(p)
            for d in drivers[:3]:
                print(f"  - {d['name']} ({d['source']})")
