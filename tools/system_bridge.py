#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
System Bridge - Driver Awareness for Frank

A translator module that acts as a bridge between Frank and system drivers.
Enables Frank to understand undocumented kernel modules and safely access them.

Categories:
  - lib*:    Libraries (libX11, libXau, etc.)
  - drm*:    Graphics drivers (drm_kms_helper, amdgpu, etc.)
  - snd*:    Audio drivers (snd_hda_codec, snd_usb_audio, etc.)
  - i2c*:    I2C interfaces (i2c_dev, i2c_piix4, etc.)
  - rfkill*: Radio control (rfkill, rfkill_default)
  - usb*:    USB drivers (usbhid, usb_storage, etc.)
  - net*:    Network drivers (r8169, iwlwifi, etc.)

Database: /home/ai-core-node/aicore/database/system_bridge.db
"""

import json
import logging
import os
import re
import sqlite3
import subprocess
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

LOG = logging.getLogger("system_bridge")

# Database path (ALWAYS use this directory!)
try:
    from config.paths import DB_DIR, get_db
    BRIDGE_DB = get_db("system_bridge")
except ImportError:
    DB_DIR = Path.home() / ".local" / "share" / "frank" / "db"
    DB_DIR.mkdir(parents=True, exist_ok=True)
    BRIDGE_DB = DB_DIR / "system_bridge.db"


# =============================================================================
# Predefined Driver Descriptions (Base Knowledge)
# =============================================================================

DRIVER_KNOWLEDGE_BASE = {
    # Graphics (DRM)
    "amdgpu": {
        "category": "graphics",
        "description": "AMD GPU kernel driver for Radeon graphics cards",
        "description_de": "AMD GPU kernel driver for Radeon graphics cards (RX 5000/6000/7000 series)",
        "capabilities": ["3D acceleration", "Video decoding", "Display output", "Vulkan", "OpenGL"],
        "config_paths": ["/sys/class/drm/card0", "/sys/kernel/debug/dri/0"],
        "safe_to_query": True,
    },
    "drm": {
        "category": "graphics",
        "description": "Direct Rendering Manager - base framework for GPU drivers",
        "description_de": "Direct Rendering Manager - base for all GPU drivers on Linux",
        "capabilities": ["Display management", "Framebuffer", "Mode setting"],
        "safe_to_query": True,
    },
    "drm_kms_helper": {
        "category": "graphics",
        "description": "Kernel Mode Setting Helper for DRM",
        "description_de": "Helper module for kernel mode setting (resolution, refresh rate)",
        "capabilities": ["Mode setting", "Hotplug detection"],
        "safe_to_query": True,
    },
    "drm_display_helper": {
        "category": "graphics",
        "description": "Display helper for DRM subsystem",
        "description_de": "Helper module for display management and EDID parsing",
        "safe_to_query": True,
    },
    "drm_buddy": {
        "category": "graphics",
        "description": "Buddy allocator for DRM memory management",
        "description_de": "Memory allocator for GPU VRAM management",
        "safe_to_query": True,
    },
    "drm_ttm_helper": {
        "category": "graphics",
        "description": "Translation Table Maps Helper for GPU memory",
        "description_de": "TTM helper module for GPU memory management",
        "safe_to_query": True,
    },
    "i915": {
        "category": "graphics",
        "description": "Intel Integrated Graphics driver",
        "description_de": "Intel iGPU driver (HD Graphics, Iris, UHD)",
        "capabilities": ["3D acceleration", "Video decoding", "Display"],
        "safe_to_query": True,
    },
    "nvidia": {
        "category": "graphics",
        "description": "NVIDIA proprietary GPU driver",
        "description_de": "NVIDIA GPU driver (GeForce, RTX series)",
        "capabilities": ["CUDA", "3D acceleration", "NVENC"],
        "safe_to_query": True,
    },
    "nouveau": {
        "category": "graphics",
        "description": "Open-source NVIDIA driver",
        "description_de": "Free NVIDIA driver (limited performance)",
        "safe_to_query": True,
    },

    # Audio (SND)
    "snd": {
        "category": "audio",
        "description": "ALSA Sound Core",
        "description_de": "Advanced Linux Sound Architecture - base audio module",
        "capabilities": ["PCM playback", "Mixer control", "MIDI"],
        "safe_to_query": True,
    },
    "snd_hda_intel": {
        "category": "audio",
        "description": "Intel HD Audio Controller driver",
        "description_de": "Driver for Intel High Definition Audio (HDA) chips",
        "config_paths": ["/proc/asound"],
        "safe_to_query": True,
    },
    "snd_hda_codec": {
        "category": "audio",
        "description": "HD Audio Codec driver",
        "description_de": "Generic HDA codec driver",
        "safe_to_query": True,
    },
    "snd_hda_codec_realtek": {
        "category": "audio",
        "description": "Realtek HD Audio Codec",
        "description_de": "Realtek audio codec driver (ALC series)",
        "safe_to_query": True,
    },
    "snd_hda_codec_hdmi": {
        "category": "audio",
        "description": "HDMI Audio Codec",
        "description_de": "Audio output via HDMI/DisplayPort",
        "safe_to_query": True,
    },
    "snd_usb_audio": {
        "category": "audio",
        "description": "USB Audio driver",
        "description_de": "Driver for USB audio devices (DACs, headsets, microphones)",
        "safe_to_query": True,
    },
    "snd_sof": {
        "category": "audio",
        "description": "Sound Open Firmware",
        "description_de": "Intel SOF Audio DSP Framework",
        "safe_to_query": True,
    },
    "snd_sof_amd_acp": {
        "category": "audio",
        "description": "AMD Audio Co-Processor SOF driver",
        "description_de": "AMD audio processor with Sound Open Firmware",
        "safe_to_query": True,
    },
    "snd_pcm": {
        "category": "audio",
        "description": "ALSA PCM Subsystem",
        "description_de": "Pulse Code Modulation - digital audio streams",
        "safe_to_query": True,
    },

    # I2C
    "i2c_core": {
        "category": "i2c",
        "description": "I2C Bus Core",
        "description_de": "Inter-Integrated Circuit Bus - communication with sensors/chips",
        "capabilities": ["Sensor communication", "EEPROM access", "Hardware monitoring"],
        "safe_to_query": True,
    },
    "i2c_piix4": {
        "category": "i2c",
        "description": "AMD/Intel PIIX4 SMBus driver",
        "description_de": "SMBus controller for AMD/Intel chipsets",
        "safe_to_query": True,
    },
    "i2c_dev": {
        "category": "i2c",
        "description": "I2C Userspace Device Interface",
        "description_de": "Allows userspace access to I2C bus (/dev/i2c-*)",
        "config_paths": ["/dev/i2c-0", "/dev/i2c-1"],
        "safe_to_query": True,
    },
    "i2c_hid": {
        "category": "i2c",
        "description": "I2C HID Transport Layer",
        "description_de": "Human Interface Devices over I2C (touchpads, touchscreens)",
        "safe_to_query": True,
    },
    "i2c_algo_bit": {
        "category": "i2c",
        "description": "I2C Bit-Banging Algorithm",
        "description_de": "Software I2C implementation",
        "safe_to_query": True,
    },

    # USB
    "usbcore": {
        "category": "usb",
        "description": "USB Core Subsystem",
        "description_de": "Universal Serial Bus - base for all USB devices",
        "capabilities": ["USB 1.1", "USB 2.0", "USB 3.x", "Hotplug"],
        "safe_to_query": True,
    },
    "usbhid": {
        "category": "usb",
        "description": "USB Human Interface Device driver",
        "description_de": "Driver for USB keyboards, mice, gamepads",
        "safe_to_query": True,
    },
    "usb_storage": {
        "category": "usb",
        "description": "USB Mass Storage driver",
        "description_de": "Driver for USB sticks and external hard drives",
        "safe_to_query": True,
    },
    "xhci_hcd": {
        "category": "usb",
        "description": "USB 3.0 xHCI Host Controller",
        "description_de": "USB 3.0/3.1/3.2 controller driver",
        "safe_to_query": True,
    },
    "ehci_hcd": {
        "category": "usb",
        "description": "USB 2.0 EHCI Host Controller",
        "description_de": "USB 2.0 controller driver",
        "safe_to_query": True,
    },

    # Radio/Wireless
    "rfkill": {
        "category": "wireless",
        "description": "RF Kill Switch Subsystem",
        "description_de": "Control of radio networks (WLAN, Bluetooth on/off)",
        "capabilities": ["WLAN control", "Bluetooth control", "Hardware kill switch"],
        "config_paths": ["/sys/class/rfkill"],
        "safe_to_query": True,
    },
    "cfg80211": {
        "category": "wireless",
        "description": "Linux Wireless Configuration API",
        "description_de": "Configuration framework for WLAN drivers",
        "safe_to_query": True,
    },
    "mac80211": {
        "category": "wireless",
        "description": "IEEE 802.11 Wireless Stack",
        "description_de": "Software MAC layer for WLAN",
        "safe_to_query": True,
    },
    "iwlwifi": {
        "category": "wireless",
        "description": "Intel Wireless WiFi driver",
        "description_de": "Intel WLAN adapter (AX200, AX210, etc.)",
        "safe_to_query": True,
    },
    "bluetooth": {
        "category": "wireless",
        "description": "Bluetooth Core",
        "description_de": "Bluetooth protocol stack",
        "capabilities": ["Bluetooth LE", "Audio profiles", "HID profiles"],
        "safe_to_query": True,
    },
    "btusb": {
        "category": "wireless",
        "description": "Bluetooth USB driver",
        "description_de": "USB Bluetooth adapter driver",
        "safe_to_query": True,
    },

    # Network
    "r8169": {
        "category": "network",
        "description": "Realtek RTL8169 Ethernet driver",
        "description_de": "Realtek Gigabit Ethernet (RTL8111/8168/8169)",
        "safe_to_query": True,
    },
    "e1000e": {
        "category": "network",
        "description": "Intel Gigabit Ethernet driver",
        "description_de": "Intel PRO/1000 network cards",
        "safe_to_query": True,
    },
    "igb": {
        "category": "network",
        "description": "Intel Gigabit Ethernet (igb)",
        "description_de": "Intel server network cards (I210, I350)",
        "safe_to_query": True,
    },

    # Libraries
    "libcrc32c": {
        "category": "library",
        "description": "CRC32c Library",
        "description_de": "Fast CRC32c checksum calculation",
        "safe_to_query": True,
    },
    "libarc4": {
        "category": "library",
        "description": "ARC4 Cipher Library",
        "description_de": "ARC4 stream cipher (for legacy protocols)",
        "safe_to_query": True,
    },

    # Virtualization
    "kvm": {
        "category": "virtualization",
        "description": "Kernel Virtual Machine",
        "description_de": "Hardware virtualization for VMs (QEMU/libvirt)",
        "capabilities": ["VM execution", "Hardware passthrough"],
        "safe_to_query": True,
    },
    "kvm_amd": {
        "category": "virtualization",
        "description": "KVM AMD-V Support",
        "description_de": "AMD virtualization extensions (SVM)",
        "safe_to_query": True,
    },
    "kvm_intel": {
        "category": "virtualization",
        "description": "KVM Intel VT-x Support",
        "description_de": "Intel virtualization extensions (VMX)",
        "safe_to_query": True,
    },

    # Storage/Filesystem
    "ext4": {
        "category": "filesystem",
        "description": "EXT4 Filesystem",
        "description_de": "Standard Linux filesystem",
        "safe_to_query": True,
    },
    "btrfs": {
        "category": "filesystem",
        "description": "BTRFS Filesystem",
        "description_de": "Copy-on-write filesystem with snapshots",
        "safe_to_query": True,
    },
    "nvme": {
        "category": "storage",
        "description": "NVMe Controller driver",
        "description_de": "Driver for NVMe SSDs",
        "safe_to_query": True,
    },
    "ahci": {
        "category": "storage",
        "description": "AHCI SATA Controller",
        "description_de": "SATA controller for hard drives/SSDs",
        "safe_to_query": True,
    },

    # Input Devices
    "hid": {
        "category": "input",
        "description": "Human Interface Device Core",
        "description_de": "Base for input devices (keyboard, mouse, gamepad)",
        "safe_to_query": True,
    },
    "hid_generic": {
        "category": "input",
        "description": "Generic HID driver",
        "description_de": "Generic driver for HID-compliant devices",
        "safe_to_query": True,
    },
    "evdev": {
        "category": "input",
        "description": "Event Device Interface",
        "description_de": "Linux input event interface (/dev/input/event*)",
        "safe_to_query": True,
    },
}

# Category Descriptions
CATEGORY_DESCRIPTIONS = {
    "graphics": "Graphics cards and display drivers",
    "audio": "Audio drivers and sound subsystem",
    "i2c": "I2C/SMBus hardware communication",
    "usb": "USB controllers and device drivers",
    "wireless": "WLAN, Bluetooth and radio control",
    "network": "Network adapters and Ethernet",
    "library": "Kernel libraries and helper functions",
    "virtualization": "Virtualization (KVM, containers)",
    "filesystem": "Filesystems",
    "storage": "Storage controllers (NVMe, SATA)",
    "input": "Input devices (keyboard, mouse)",
    "unknown": "Unknown/undocumented modules",
}


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class DriverInfo:
    """Information about a kernel driver."""
    name: str
    category: str = "unknown"
    description: str = ""
    description_de: str = ""
    capabilities: List[str] = field(default_factory=list)
    config_paths: List[str] = field(default_factory=list)
    is_loaded: bool = False
    size_kb: int = 0
    used_by: List[str] = field(default_factory=list)
    safe_to_query: bool = True
    custom_notes: str = ""
    last_seen: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "category": self.category,
            "description": self.description,
            "description_de": self.description_de,
            "capabilities": self.capabilities,
            "config_paths": self.config_paths,
            "is_loaded": self.is_loaded,
            "size_kb": self.size_kb,
            "used_by": self.used_by,
            "safe_to_query": self.safe_to_query,
            "custom_notes": self.custom_notes,
        }


# =============================================================================
# Database Layer
# =============================================================================

class BridgeDB:
    """SQLite database for System Bridge."""

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS drivers (
        name TEXT PRIMARY KEY,
        category TEXT NOT NULL DEFAULT 'unknown',
        description TEXT DEFAULT '',
        description_de TEXT DEFAULT '',
        capabilities TEXT DEFAULT '[]',
        config_paths TEXT DEFAULT '[]',
        safe_to_query INTEGER DEFAULT 1,
        custom_notes TEXT DEFAULT '',
        first_seen TEXT NOT NULL,
        last_seen TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_drivers_category ON drivers(category);

    CREATE TABLE IF NOT EXISTS driver_observations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        driver_name TEXT NOT NULL,
        timestamp TEXT NOT NULL,
        is_loaded INTEGER NOT NULL,
        size_kb INTEGER DEFAULT 0,
        used_by TEXT DEFAULT '[]',
        FOREIGN KEY (driver_name) REFERENCES drivers(name)
    );
    CREATE INDEX IF NOT EXISTS idx_obs_driver ON driver_observations(driver_name);
    CREATE INDEX IF NOT EXISTS idx_obs_ts ON driver_observations(timestamp);

    CREATE TABLE IF NOT EXISTS bridge_meta (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL,
        updated TEXT NOT NULL
    );
    """

    def __init__(self, db_path: Path = BRIDGE_DB):
        self._db_path = db_path
        self._local = threading.local()
        DB_DIR.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _get_conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = sqlite3.connect(
                str(self._db_path),
                timeout=30.0,
                check_same_thread=False,
            )
            self._local.conn.row_factory = sqlite3.Row
            self._local.conn.execute("PRAGMA journal_mode=WAL")
            self._local.conn.execute("PRAGMA synchronous=NORMAL")
        return self._local.conn

    def _init_schema(self):
        conn = self._get_conn()
        conn.executescript(self.SCHEMA)
        conn.commit()

    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        return self._get_conn().execute(sql, params)

    def commit(self):
        self._get_conn().commit()

    def fetchone(self, sql: str, params: tuple = ()) -> Optional[sqlite3.Row]:
        return self.execute(sql, params).fetchone()

    def fetchall(self, sql: str, params: tuple = ()) -> List[sqlite3.Row]:
        return self.execute(sql, params).fetchall()


# =============================================================================
# System Bridge Core
# =============================================================================

class SystemBridge:
    """
    System Bridge - Translator between Frank and kernel drivers.

    Enables:
    - Detection of loaded modules
    - Lookup of driver descriptions
    - Adding custom descriptions
    - Safe querying of driver information
    """

    def __init__(self):
        self.db = BridgeDB()
        self._lock = threading.Lock()
        self._populate_base_knowledge()
        LOG.info("System Bridge initialized (DB: %s)", BRIDGE_DB)

    def _populate_base_knowledge(self):
        """Populate DB with base knowledge from DRIVER_KNOWLEDGE_BASE."""
        now = datetime.now().isoformat()
        for name, info in DRIVER_KNOWLEDGE_BASE.items():
            existing = self.db.fetchone("SELECT name FROM drivers WHERE name = ?", (name,))
            if not existing:
                self.db.execute("""
                    INSERT INTO drivers
                    (name, category, description, description_de, capabilities, config_paths,
                     safe_to_query, first_seen, last_seen)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    name,
                    info.get("category", "unknown"),
                    info.get("description", ""),
                    info.get("description_de", ""),
                    json.dumps(info.get("capabilities", [])),
                    json.dumps(info.get("config_paths", [])),
                    1 if info.get("safe_to_query", True) else 0,
                    now, now
                ))
        self.db.commit()

    def scan_loaded_modules(self) -> List[DriverInfo]:
        """
        Scan currently loaded kernel modules.
        Returns list of DriverInfo objects.
        """
        modules = []
        now = datetime.now().isoformat()

        try:
            result = subprocess.run(
                ["lsmod"],
                capture_output=True, text=True, timeout=10
            )
            lines = result.stdout.strip().split("\n")[1:]  # Skip header

            for line in lines:
                parts = line.split()
                if len(parts) >= 2:
                    name = parts[0]
                    size_kb = int(parts[1]) // 1024 if parts[1].isdigit() else 0
                    used_by = parts[3].split(",") if len(parts) >= 4 and parts[3] != "-" else []

                    # Lookup in DB or Knowledge Base
                    info = self.get_driver_info(name)
                    info.is_loaded = True
                    info.size_kb = size_kb
                    info.used_by = used_by
                    info.last_seen = now

                    modules.append(info)

                    # Update observation in DB
                    self.db.execute("""
                        INSERT INTO driver_observations
                        (driver_name, timestamp, is_loaded, size_kb, used_by)
                        VALUES (?, ?, 1, ?, ?)
                    """, (name, now, size_kb, json.dumps(used_by)))

            self.db.commit()

        except Exception as e:
            LOG.error("Error scanning modules: %s", e)

        return modules

    def get_driver_info(self, name: str) -> DriverInfo:
        """
        Get information about a driver.
        Combines DB knowledge with Knowledge Base.
        """
        # Check DB first
        row = self.db.fetchone("SELECT * FROM drivers WHERE name = ?", (name,))

        if row:
            return DriverInfo(
                name=row["name"],
                category=row["category"],
                description=row["description"],
                description_de=row["description_de"],
                capabilities=json.loads(row["capabilities"] or "[]"),
                config_paths=json.loads(row["config_paths"] or "[]"),
                safe_to_query=bool(row["safe_to_query"]),
                custom_notes=row["custom_notes"] or "",
                last_seen=row["last_seen"],
            )

        # Then check Knowledge Base
        if name in DRIVER_KNOWLEDGE_BASE:
            kb = DRIVER_KNOWLEDGE_BASE[name]
            return DriverInfo(
                name=name,
                category=kb.get("category", "unknown"),
                description=kb.get("description", ""),
                description_de=kb.get("description_de", ""),
                capabilities=kb.get("capabilities", []),
                config_paths=kb.get("config_paths", []),
                safe_to_query=kb.get("safe_to_query", True),
            )

        # Try to infer category from name
        category = self._infer_category(name)

        # New unknown driver - save to DB
        now = datetime.now().isoformat()
        self.db.execute("""
            INSERT OR IGNORE INTO drivers
            (name, category, description, description_de, first_seen, last_seen)
            VALUES (?, ?, '', '', ?, ?)
        """, (name, category, now, now))
        self.db.commit()

        return DriverInfo(
            name=name,
            category=category,
            description=f"Kernel module '{name}' (no description available)",
            description_de=f"Kernel module '{name}' (no description available)",
            last_seen=now,
        )

    def _infer_category(self, name: str) -> str:
        """Infer category from module name."""
        name_lower = name.lower()

        if name_lower.startswith("snd") or "audio" in name_lower or "sound" in name_lower:
            return "audio"
        if name_lower.startswith("drm") or "gpu" in name_lower:
            return "graphics"
        if name_lower.startswith("i2c"):
            return "i2c"
        if name_lower.startswith("usb") or "hid" in name_lower:
            return "usb"
        if "rfkill" in name_lower or "wifi" in name_lower or "wlan" in name_lower:
            return "wireless"
        if "bluetooth" in name_lower or name_lower.startswith("bt"):
            return "wireless"
        if name_lower.startswith("lib"):
            return "library"
        if "net" in name_lower or "eth" in name_lower:
            return "network"
        if "kvm" in name_lower or "virt" in name_lower:
            return "virtualization"
        if "nvme" in name_lower or "ahci" in name_lower or "sata" in name_lower:
            return "storage"

        return "unknown"

    def add_description(self, name: str, description: str,
                        description_de: str = None,
                        category: str = None,
                        capabilities: List[str] = None,
                        custom_notes: str = None) -> bool:
        """
        Add or update a driver description.

        Args:
            name: Module name
            description: English description
            description_de: German description (optional)
            category: Category (optional)
            capabilities: List of capabilities (optional)
            custom_notes: Custom notes (optional)

        Returns:
            True on success
        """
        now = datetime.now().isoformat()

        existing = self.db.fetchone("SELECT * FROM drivers WHERE name = ?", (name,))

        if existing:
            # Update
            updates = []
            params = []

            if description:
                updates.append("description = ?")
                params.append(description)
            if description_de:
                updates.append("description_de = ?")
                params.append(description_de)
            if category:
                updates.append("category = ?")
                params.append(category)
            if capabilities is not None:
                updates.append("capabilities = ?")
                params.append(json.dumps(capabilities))
            if custom_notes is not None:
                updates.append("custom_notes = ?")
                params.append(custom_notes)

            updates.append("last_seen = ?")
            params.append(now)
            params.append(name)

            self.db.execute(
                f"UPDATE drivers SET {', '.join(updates)} WHERE name = ?",
                tuple(params)
            )
        else:
            # Insert
            cat = category or self._infer_category(name)
            self.db.execute("""
                INSERT INTO drivers
                (name, category, description, description_de, capabilities, custom_notes,
                 first_seen, last_seen)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                name, cat, description or "", description_de or "",
                json.dumps(capabilities or []), custom_notes or "",
                now, now
            ))

        self.db.commit()
        LOG.info("Driver description updated: %s", name)
        return True

    def get_modules_by_category(self, category: str) -> List[DriverInfo]:
        """Get all modules of a category."""
        rows = self.db.fetchall(
            "SELECT * FROM drivers WHERE category = ?", (category,)
        )
        return [
            DriverInfo(
                name=r["name"],
                category=r["category"],
                description=r["description"],
                description_de=r["description_de"],
                capabilities=json.loads(r["capabilities"] or "[]"),
                safe_to_query=bool(r["safe_to_query"]),
                custom_notes=r["custom_notes"] or "",
            )
            for r in rows
        ]

    def get_undocumented_modules(self) -> List[DriverInfo]:
        """Find modules without description."""
        modules = self.scan_loaded_modules()
        return [m for m in modules if not m.description or m.category == "unknown"]

    def query_module_details(self, name: str) -> Dict:
        """
        Safe query of module details from /sys and modinfo.

        Returns dict with extended information.
        """
        info = self.get_driver_info(name)
        result = info.to_dict()

        if not info.safe_to_query:
            result["warning"] = "Module marked as unsafe for queries"
            return result

        # Query modinfo
        try:
            modinfo = subprocess.run(
                ["modinfo", name],
                capture_output=True, text=True, timeout=5
            )
            if modinfo.returncode == 0:
                result["modinfo"] = {}
                for line in modinfo.stdout.strip().split("\n"):
                    if ":" in line:
                        key, val = line.split(":", 1)
                        key = key.strip().lower().replace(" ", "_")
                        result["modinfo"][key] = val.strip()
        except Exception as e:
            LOG.debug("modinfo failed for %s: %s", name, e)

        # Parameters from /sys/module/
        sys_path = Path(f"/sys/module/{name}/parameters")
        if sys_path.exists():
            result["parameters"] = {}
            try:
                for param in sys_path.iterdir():
                    try:
                        result["parameters"][param.name] = param.read_text().strip()
                    except:
                        result["parameters"][param.name] = "(not readable)"
            except:
                pass

        return result

    def get_summary(self) -> Dict:
        """Summary of the system state."""
        modules = self.scan_loaded_modules()

        by_category = {}
        for m in modules:
            if m.category not in by_category:
                by_category[m.category] = []
            by_category[m.category].append(m.name)

        total_kb = sum(m.size_kb for m in modules)
        undocumented = len([m for m in modules if not m.description])

        return {
            "total_modules": len(modules),
            "total_size_kb": total_kb,
            "total_size_mb": round(total_kb / 1024, 1),
            "undocumented": undocumented,
            "by_category": {k: len(v) for k, v in by_category.items()},
            "categories": list(by_category.keys()),
            "category_descriptions": CATEGORY_DESCRIPTIONS,
        }

    def context_for_frank(self, query: str = None) -> str:
        """
        Generate context string for Frank's prompt injection.

        Args:
            query: Optional search query to filter relevant modules

        Returns:
            Formatted context string
        """
        lines = ["[System Bridge - Driver Knowledge:"]

        if query:
            # Search for relevant modules
            query_lower = query.lower()
            relevant = []

            rows = self.db.fetchall("SELECT * FROM drivers")
            for row in rows:
                if (query_lower in row["name"].lower() or
                    query_lower in (row["description"] or "").lower() or
                    query_lower in (row["description_de"] or "").lower() or
                    query_lower in row["category"]):
                    relevant.append(row)

            if relevant:
                for r in relevant[:5]:
                    desc = r["description_de"] or r["description"] or "No description"
                    lines.append(f"  - {r['name']} ({r['category']}): {desc}")
            else:
                lines.append(f"  No modules found for: {query}")
        else:
            # General summary
            summary = self.get_summary()
            lines.append(f"  {summary['total_modules']} modules loaded ({summary['total_size_mb']} MB)")
            for cat, count in summary["by_category"].items():
                cat_desc = CATEGORY_DESCRIPTIONS.get(cat, cat)
                lines.append(f"  - {cat}: {count} modules ({cat_desc})")

        lines.append("]")
        return "\n".join(lines)


# =============================================================================
# Singleton & Convenience
# =============================================================================

_bridge: Optional[SystemBridge] = None


def get_bridge() -> SystemBridge:
    """Get or create System Bridge instance."""
    global _bridge
    if _bridge is None:
        _bridge = SystemBridge()
    return _bridge


def scan() -> List[Dict]:
    """Scan loaded modules."""
    return [m.to_dict() for m in get_bridge().scan_loaded_modules()]


def lookup(name: str) -> Dict:
    """Lookup a driver."""
    return get_bridge().get_driver_info(name).to_dict()


def describe(name: str, description: str, **kwargs) -> bool:
    """Add description."""
    return get_bridge().add_description(name, description, **kwargs)


def summary() -> Dict:
    """System summary."""
    return get_bridge().get_summary()


def context(query: str = None) -> str:
    """Context for Frank."""
    return get_bridge().context_for_frank(query)


# =============================================================================
# CLI
# =============================================================================

def _cli_main():
    import argparse

    parser = argparse.ArgumentParser(
        description="System Bridge - Driver Awareness for Frank",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Commands:
  scan            Scan loaded kernel modules
  lookup NAME     Show info about a module
  describe NAME   Add description
  category CAT    Show modules of a category
  undocumented    Show modules without description
  summary         System summary
  context [QUERY] Generate context for Frank
        """
    )
    parser.add_argument("command", nargs="?", default="summary")
    parser.add_argument("arg", nargs="?", help="Argument for command")
    parser.add_argument("--desc", help="Description (for describe)")
    parser.add_argument("--desc-de", help="German description")
    parser.add_argument("--category", help="Category")
    parser.add_argument("--json", action="store_true", help="JSON output")

    args = parser.parse_args()
    bridge = get_bridge()

    def _out(data):
        if args.json:
            print(json.dumps(data, indent=2, ensure_ascii=False, default=str))
        elif isinstance(data, dict):
            for k, v in data.items():
                if isinstance(v, dict):
                    print(f"{k}:")
                    for k2, v2 in v.items():
                        print(f"  {k2}: {v2}")
                elif isinstance(v, list):
                    print(f"{k}: {', '.join(str(x) for x in v[:10])}")
                else:
                    print(f"{k}: {v}")
        elif isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    print(f"  - {item.get('name', item)}")
                else:
                    print(f"  - {item}")
        else:
            print(data)

    cmd = args.command.lower()

    if cmd == "scan":
        print("=== Loaded Kernel Modules ===")
        modules = bridge.scan_loaded_modules()
        for m in sorted(modules, key=lambda x: x.category):
            desc = m.description_de or m.description or "(no description)"
            print(f"[{m.category:12}] {m.name:30} {m.size_kb:6} KB  {desc[:50]}")
        print(f"\nTotal: {len(modules)} modules")

    elif cmd == "lookup":
        if not args.arg:
            print("Error: module name required")
            return
        info = bridge.query_module_details(args.arg)
        print(f"=== {args.arg} ===")
        _out(info)

    elif cmd == "describe":
        if not args.arg:
            print("Error: module name required")
            return
        if not args.desc:
            print("Error: --desc required")
            return
        bridge.add_description(
            args.arg,
            args.desc,
            description_de=args.desc_de,
            category=args.category
        )
        print(f"Description for '{args.arg}' updated")

    elif cmd == "category":
        if not args.arg:
            print("Available categories:")
            for cat, desc in CATEGORY_DESCRIPTIONS.items():
                print(f"  {cat:15} - {desc}")
            return
        modules = bridge.get_modules_by_category(args.arg)
        print(f"=== Category: {args.arg} ===")
        for m in modules:
            print(f"  {m.name}: {m.description_de or m.description or '(no description)'}")

    elif cmd == "undocumented":
        print("=== Modules Without Description ===")
        modules = bridge.get_undocumented_modules()
        for m in modules:
            print(f"  [{m.category}] {m.name}")
        print(f"\n{len(modules)} undocumented modules")

    elif cmd == "summary":
        print("=== System Bridge Summary ===")
        _out(bridge.get_summary())

    elif cmd == "context":
        print(bridge.context_for_frank(args.arg))

    else:
        parser.print_help()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    _cli_main()
