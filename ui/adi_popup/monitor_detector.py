#!/usr/bin/env python3
"""
ADI Monitor Detector - EDID-based hardware identification.

Detects connected monitors and extracts unique identifiers
from EDID data to enable per-device profile storage.
"""

import hashlib
import logging
import re
import struct
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

LOG = logging.getLogger("adi.monitor_detector")

# EDID manufacturer codes (3-letter PnP IDs)
# Common manufacturers - extend as needed
MANUFACTURER_NAMES = {
    "ACR": "Acer",
    "ACI": "Asus",
    "AOC": "AOC",
    "AUS": "Asus",
    "BNQ": "BenQ",
    "DEL": "Dell",
    "ENC": "Eizo",
    "EYA": "Eyoyo",
    "GSM": "LG",
    "HPN": "HP",
    "HWP": "HP",
    "IVM": "Iiyama",
    "LEN": "Lenovo",
    "LGD": "LG Display",
    "MEI": "Panasonic",
    "NEC": "NEC",
    "PHL": "Philips",
    "SAM": "Samsung",
    "SDC": "Samsung",
    "SNY": "Sony",
    "VSC": "ViewSonic",
}

# Profile storage location
try:
    from config.paths import ADI_PROFILES_DIR
    PROFILES_DIR = ADI_PROFILES_DIR
except ImportError:
    PROFILES_DIR = Path("/home/ai-core-node/.local/share/frank/adi_profiles")


@dataclass
class MonitorInfo:
    """Information about a connected monitor."""

    name: str                    # Connector name: "HDMI-A-1", "DP-1", etc.
    manufacturer: str = ""       # Human-readable: "Samsung", "Dell", etc.
    manufacturer_code: str = ""  # PnP ID: "SAM", "DEL", etc.
    model: str = ""              # Model name from EDID
    serial: str = ""             # Serial number (if available)
    product_code: int = 0        # Product code from EDID
    edid_hash: str = ""          # Unique hash for profile matching
    width: int = 1920            # Current resolution width
    height: int = 1080           # Current resolution height
    x: int = 0                   # Position in virtual desktop
    y: int = 0                   # Position in virtual desktop
    refresh: int = 60            # Refresh rate in Hz
    physical_width_mm: int = 0   # Physical width in mm
    physical_height_mm: int = 0  # Physical height in mm
    dpi: int = 96                # Estimated DPI
    is_primary: bool = False     # Is this the primary monitor?
    raw_edid: bytes = field(default_factory=bytes, repr=False)

    def get_display_name(self) -> str:
        """Get a human-readable display name."""
        if self.model:
            if self.manufacturer:
                return f"{self.manufacturer} {self.model}"
            return self.model
        if self.manufacturer:
            return f"{self.manufacturer} ({self.name})"
        return self.name

    def get_unique_id(self) -> str:
        """Get unique identifier string."""
        return f"{self.manufacturer_code}_{self.product_code:04x}_{self.serial or 'unknown'}"


def _parse_edid_manufacturer(edid: bytes) -> str:
    """Extract manufacturer code from EDID bytes 8-9."""
    if len(edid) < 10:
        return "UNK"

    # Manufacturer ID is encoded in bytes 8-9 as compressed ASCII
    # Each letter is 5 bits: (byte - 'A' + 1)
    mfg_bytes = (edid[8] << 8) | edid[9]

    letter1 = ((mfg_bytes >> 10) & 0x1F) + ord('A') - 1
    letter2 = ((mfg_bytes >> 5) & 0x1F) + ord('A') - 1
    letter3 = (mfg_bytes & 0x1F) + ord('A') - 1

    try:
        return chr(letter1) + chr(letter2) + chr(letter3)
    except ValueError:
        return "UNK"


def _parse_edid_product_code(edid: bytes) -> int:
    """Extract product code from EDID bytes 10-11."""
    if len(edid) < 12:
        return 0
    return edid[10] | (edid[11] << 8)


def _parse_edid_serial(edid: bytes) -> str:
    """Extract serial number from EDID bytes 12-15."""
    if len(edid) < 16:
        return ""
    serial_num = struct.unpack('<I', edid[12:16])[0]
    if serial_num == 0 or serial_num == 0x01010101:
        return ""
    return f"{serial_num:08x}"


def _parse_edid_descriptors(edid: bytes) -> Dict[str, str]:
    """Parse EDID descriptor blocks for model name and serial string."""
    result = {"model": "", "serial_string": ""}

    if len(edid) < 128:
        return result

    # Descriptors are at bytes 54-125 (4 x 18-byte blocks)
    for i in range(4):
        offset = 54 + (i * 18)
        desc = edid[offset:offset + 18]

        if len(desc) < 18:
            continue

        # Check descriptor type (bytes 0-3 should be 0x00 for text descriptors)
        if desc[0] == 0 and desc[1] == 0 and desc[2] == 0:
            desc_type = desc[3]
            # 0xFC = Monitor name, 0xFF = Serial string
            text_data = desc[5:18]

            # Extract text (terminated by 0x0A or padded with 0x20)
            text = ""
            for byte in text_data:
                if byte == 0x0A or byte == 0x00:
                    break
                text += chr(byte)
            text = text.strip()

            if desc_type == 0xFC:  # Monitor name
                result["model"] = text
            elif desc_type == 0xFF:  # Serial string
                result["serial_string"] = text

    return result


def _parse_edid_physical_size(edid: bytes) -> tuple:
    """Extract physical size in mm from EDID."""
    if len(edid) < 22:
        return (0, 0)

    # Bytes 21-22 contain width and height in cm
    width_cm = edid[21]
    height_cm = edid[22]

    return (width_cm * 10, height_cm * 10)


def _calculate_dpi(width_px: int, height_px: int, width_mm: int, height_mm: int) -> int:
    """Calculate DPI from resolution and physical size."""
    if width_mm <= 0 or height_mm <= 0:
        return 96  # Default DPI

    # Calculate diagonal in inches
    width_in = width_mm / 25.4
    height_in = height_mm / 25.4

    # Use horizontal DPI (usually more accurate)
    dpi = int(width_px / width_in)

    # Sanity check
    if dpi < 50 or dpi > 600:
        return 96

    return dpi


def _compute_edid_hash(edid: bytes, name: str) -> str:
    """Compute a unique hash for the monitor."""
    if edid:
        # Use first 128 bytes of EDID (the base block)
        data = edid[:128] if len(edid) >= 128 else edid
        return hashlib.sha256(data).hexdigest()[:16]
    else:
        # Fallback: hash the connector name
        return hashlib.sha256(name.encode()).hexdigest()[:16]


def _parse_xrandr_verbose() -> Dict[str, MonitorInfo]:
    """Parse xrandr --verbose output to get monitor info with EDID."""
    monitors = {}

    try:
        result = subprocess.run(
            ["xrandr", "--verbose"],
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode != 0:
            LOG.warning(f"xrandr failed: {result.stderr}")
            return monitors

        output = result.stdout
    except subprocess.TimeoutExpired:
        LOG.error("xrandr timed out")
        return monitors
    except FileNotFoundError:
        LOG.error("xrandr not found")
        return monitors

    # Parse connected monitors
    # Pattern: "HDMI-A-1 connected primary 1920x1080+0+0 ..."
    monitor_pattern = re.compile(
        r'^(\S+)\s+connected\s*(primary)?\s*'
        r'(?:(\d+)x(\d+)\+(\d+)\+(\d+))?',
        re.MULTILINE
    )

    # Find EDID blocks
    edid_pattern = re.compile(
        r'EDID:\s*\n((?:\s+[0-9a-f]+\n)+)',
        re.IGNORECASE
    )

    # Split by monitor sections
    sections = re.split(r'^(\S+)\s+(?:connected|disconnected)', output, flags=re.MULTILINE)

    current_monitor = None

    for match in monitor_pattern.finditer(output):
        name = match.group(1)
        is_primary = match.group(2) == "primary"
        width = int(match.group(3)) if match.group(3) else 0
        height = int(match.group(4)) if match.group(4) else 0
        x = int(match.group(5)) if match.group(5) else 0
        y = int(match.group(6)) if match.group(6) else 0

        # Find the section for this monitor to extract EDID
        section_start = match.start()
        # Find the next monitor or end
        next_match = monitor_pattern.search(output, match.end())
        section_end = next_match.start() if next_match else len(output)
        section = output[section_start:section_end]

        # Extract EDID from section
        edid_bytes = b""
        edid_match = edid_pattern.search(section)
        if edid_match:
            hex_lines = edid_match.group(1)
            hex_str = re.sub(r'\s+', '', hex_lines)
            try:
                edid_bytes = bytes.fromhex(hex_str)
            except ValueError:
                LOG.warning(f"Failed to parse EDID hex for {name}")

        # Parse EDID data
        mfg_code = _parse_edid_manufacturer(edid_bytes) if edid_bytes else "UNK"
        mfg_name = MANUFACTURER_NAMES.get(mfg_code, mfg_code)
        product_code = _parse_edid_product_code(edid_bytes) if edid_bytes else 0
        serial = _parse_edid_serial(edid_bytes) if edid_bytes else ""
        descriptors = _parse_edid_descriptors(edid_bytes) if edid_bytes else {}
        phys_w, phys_h = _parse_edid_physical_size(edid_bytes) if edid_bytes else (0, 0)

        # Use serial string from descriptor if available
        if descriptors.get("serial_string") and not serial:
            serial = descriptors["serial_string"]

        # Calculate DPI
        dpi = _calculate_dpi(width, height, phys_w, phys_h)

        # Compute unique hash
        edid_hash = _compute_edid_hash(edid_bytes, name)

        # Extract refresh rate from mode line
        # xrandr format: "1024x600      60.00*+" (asterisk after number)
        refresh = 60
        refresh_match = re.search(rf'{width}x{height}\s+(\d+\.\d+)\*', section)
        if refresh_match:
            refresh = int(float(refresh_match.group(1)))
        else:
            # Alternative format: look for any active mode with asterisk
            alt_match = re.search(r'(\d+\.\d+)\*', section)
            if alt_match:
                refresh = int(float(alt_match.group(1)))

        monitors[name] = MonitorInfo(
            name=name,
            manufacturer=mfg_name,
            manufacturer_code=mfg_code,
            model=descriptors.get("model", ""),
            serial=serial,
            product_code=product_code,
            edid_hash=edid_hash,
            width=width,
            height=height,
            x=x,
            y=y,
            refresh=refresh,
            physical_width_mm=phys_w,
            physical_height_mm=phys_h,
            dpi=dpi,
            is_primary=is_primary,
            raw_edid=edid_bytes,
        )

    return monitors


def get_connected_monitors() -> List[MonitorInfo]:
    """Get list of all connected monitors."""
    monitors = _parse_xrandr_verbose()
    return list(monitors.values())


def get_primary_monitor() -> Optional[MonitorInfo]:
    """Get the primary monitor."""
    monitors = _parse_xrandr_verbose()

    # First try to find explicitly primary monitor
    for monitor in monitors.values():
        if monitor.is_primary:
            return monitor

    # Fallback to first connected monitor
    if monitors:
        return next(iter(monitors.values()))

    # Ultimate fallback
    LOG.warning("No monitors detected, returning fallback")
    return MonitorInfo(
        name="FALLBACK",
        width=1920,
        height=1080,
        edid_hash="fallback_monitor",
    )


def get_monitor_by_name(name: str) -> Optional[MonitorInfo]:
    """Get a specific monitor by connector name."""
    monitors = _parse_xrandr_verbose()
    return monitors.get(name)


def is_monitor_known(edid_hash: str) -> bool:
    """Check if we have a saved profile for this monitor."""
    profile_path = PROFILES_DIR / f"{edid_hash}.json"
    return profile_path.exists()


def get_all_known_profiles() -> List[str]:
    """Get list of all known monitor EDID hashes."""
    if not PROFILES_DIR.exists():
        return []
    return [p.stem for p in PROFILES_DIR.glob("*.json")]


# Quick test
if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)

    print("=== Connected Monitors ===")
    for monitor in get_connected_monitors():
        print(f"\n{monitor.name}:")
        print(f"  Display: {monitor.get_display_name()}")
        print(f"  Resolution: {monitor.width}x{monitor.height} @ {monitor.refresh}Hz")
        print(f"  Position: {monitor.x},{monitor.y}")
        print(f"  Physical: {monitor.physical_width_mm}x{monitor.physical_height_mm}mm")
        print(f"  DPI: {monitor.dpi}")
        print(f"  Manufacturer: {monitor.manufacturer} ({monitor.manufacturer_code})")
        print(f"  Model: {monitor.model}")
        print(f"  Serial: {monitor.serial}")
        print(f"  EDID Hash: {monitor.edid_hash}")
        print(f"  Unique ID: {monitor.get_unique_id()}")
        print(f"  Primary: {monitor.is_primary}")
        print(f"  Known: {is_monitor_known(monitor.edid_hash)}")
