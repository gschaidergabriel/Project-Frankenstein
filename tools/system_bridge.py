#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
System Bridge - Treiber-Awareness für Frank

Ein Übersetzer-Modul das als Bridge zwischen Frank und den System-Treibern fungiert.
Ermöglicht Frank, undokumentierte Kernel-Module zu verstehen und sicher darauf zuzugreifen.

Kategorien:
  - lib*:    Bibliotheken (libX11, libXau, etc.)
  - drm*:    Grafiktreiber (drm_kms_helper, amdgpu, etc.)
  - snd*:    Audio-Treiber (snd_hda_codec, snd_usb_audio, etc.)
  - i2c*:    I2C-Schnittstellen (i2c_dev, i2c_piix4, etc.)
  - rfkill*: Funk-Steuerung (rfkill, rfkill_default)
  - usb*:    USB-Treiber (usbhid, usb_storage, etc.)
  - net*:    Netzwerk-Treiber (r8169, iwlwifi, etc.)

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

# Database path (IMMER diesen Ordner verwenden!)
try:
    from config.paths import DB_DIR, get_db
    BRIDGE_DB = get_db("system_bridge")
except ImportError:
    DB_DIR = Path("/home/ai-core-node/aicore/database")
    BRIDGE_DB = DB_DIR / "system_bridge.db"


# =============================================================================
# Vordefinierte Treiber-Beschreibungen (Basis-Wissen)
# =============================================================================

DRIVER_KNOWLEDGE_BASE = {
    # Grafik (DRM)
    "amdgpu": {
        "category": "graphics",
        "description": "AMD GPU Kernel-Treiber für Radeon Grafikkarten",
        "description_de": "AMD GPU Kernel-Treiber für Radeon Grafikkarten (RX 5000/6000/7000 Serie)",
        "capabilities": ["3D-Beschleunigung", "Video-Dekodierung", "Display-Ausgabe", "Vulkan", "OpenGL"],
        "config_paths": ["/sys/class/drm/card0", "/sys/kernel/debug/dri/0"],
        "safe_to_query": True,
    },
    "drm": {
        "category": "graphics",
        "description": "Direct Rendering Manager - Basis-Framework für GPU-Treiber",
        "description_de": "Direct Rendering Manager - Basis für alle GPU-Treiber unter Linux",
        "capabilities": ["Display-Management", "Framebuffer", "Mode-Setting"],
        "safe_to_query": True,
    },
    "drm_kms_helper": {
        "category": "graphics",
        "description": "Kernel Mode Setting Helper für DRM",
        "description_de": "Hilfsmodul für Kernel Mode Setting (Auflösung, Refresh-Rate)",
        "capabilities": ["Mode-Setting", "Hotplug-Erkennung"],
        "safe_to_query": True,
    },
    "drm_display_helper": {
        "category": "graphics",
        "description": "Display-Helper für DRM Subsystem",
        "description_de": "Hilfsmodul für Display-Verwaltung und EDID-Parsing",
        "safe_to_query": True,
    },
    "drm_buddy": {
        "category": "graphics",
        "description": "Buddy-Allocator für DRM Speicherverwaltung",
        "description_de": "Speicher-Allocator für GPU-VRAM Management",
        "safe_to_query": True,
    },
    "drm_ttm_helper": {
        "category": "graphics",
        "description": "Translation Table Maps Helper für GPU-Speicher",
        "description_de": "TTM-Hilfsmodul für GPU-Speicherverwaltung",
        "safe_to_query": True,
    },
    "i915": {
        "category": "graphics",
        "description": "Intel Integrated Graphics Treiber",
        "description_de": "Intel iGPU Treiber (HD Graphics, Iris, UHD)",
        "capabilities": ["3D-Beschleunigung", "Video-Dekodierung", "Display"],
        "safe_to_query": True,
    },
    "nvidia": {
        "category": "graphics",
        "description": "NVIDIA proprietärer GPU-Treiber",
        "description_de": "NVIDIA GPU Treiber (GeForce, RTX Serie)",
        "capabilities": ["CUDA", "3D-Beschleunigung", "NVENC"],
        "safe_to_query": True,
    },
    "nouveau": {
        "category": "graphics",
        "description": "Open-Source NVIDIA Treiber",
        "description_de": "Freier NVIDIA-Treiber (eingeschränkte Leistung)",
        "safe_to_query": True,
    },

    # Audio (SND)
    "snd": {
        "category": "audio",
        "description": "ALSA Sound Core",
        "description_de": "Advanced Linux Sound Architecture - Basis-Audiomodul",
        "capabilities": ["PCM-Wiedergabe", "Mixer-Kontrolle", "MIDI"],
        "safe_to_query": True,
    },
    "snd_hda_intel": {
        "category": "audio",
        "description": "Intel HD Audio Controller Treiber",
        "description_de": "Treiber für Intel High Definition Audio (HDA) Chips",
        "config_paths": ["/proc/asound"],
        "safe_to_query": True,
    },
    "snd_hda_codec": {
        "category": "audio",
        "description": "HD Audio Codec Treiber",
        "description_de": "Generischer HDA Codec-Treiber",
        "safe_to_query": True,
    },
    "snd_hda_codec_realtek": {
        "category": "audio",
        "description": "Realtek HD Audio Codec",
        "description_de": "Realtek Audio-Codec Treiber (ALC-Serie)",
        "safe_to_query": True,
    },
    "snd_hda_codec_hdmi": {
        "category": "audio",
        "description": "HDMI Audio Codec",
        "description_de": "Audio-Ausgabe über HDMI/DisplayPort",
        "safe_to_query": True,
    },
    "snd_usb_audio": {
        "category": "audio",
        "description": "USB Audio Treiber",
        "description_de": "Treiber für USB-Audiogeräte (DACs, Headsets, Mikrofone)",
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
        "description": "AMD Audio Co-Processor SOF Treiber",
        "description_de": "AMD Audio-Prozessor mit Sound Open Firmware",
        "safe_to_query": True,
    },
    "snd_pcm": {
        "category": "audio",
        "description": "ALSA PCM Subsystem",
        "description_de": "Pulse Code Modulation - digitale Audio-Streams",
        "safe_to_query": True,
    },

    # I2C
    "i2c_core": {
        "category": "i2c",
        "description": "I2C Bus Core",
        "description_de": "Inter-Integrated Circuit Bus - Kommunikation mit Sensoren/Chips",
        "capabilities": ["Sensor-Kommunikation", "EEPROM-Zugriff", "Hardware-Monitoring"],
        "safe_to_query": True,
    },
    "i2c_piix4": {
        "category": "i2c",
        "description": "AMD/Intel PIIX4 SMBus Treiber",
        "description_de": "SMBus-Controller für AMD/Intel Chipsätze",
        "safe_to_query": True,
    },
    "i2c_dev": {
        "category": "i2c",
        "description": "I2C Userspace Device Interface",
        "description_de": "Erlaubt Userspace-Zugriff auf I2C-Bus (/dev/i2c-*)",
        "config_paths": ["/dev/i2c-0", "/dev/i2c-1"],
        "safe_to_query": True,
    },
    "i2c_hid": {
        "category": "i2c",
        "description": "I2C HID Transport Layer",
        "description_de": "Human Interface Devices über I2C (Touchpads, Touchscreens)",
        "safe_to_query": True,
    },
    "i2c_algo_bit": {
        "category": "i2c",
        "description": "I2C Bit-Banging Algorithmus",
        "description_de": "Software-I2C Implementation",
        "safe_to_query": True,
    },

    # USB
    "usbcore": {
        "category": "usb",
        "description": "USB Core Subsystem",
        "description_de": "Universal Serial Bus - Basis für alle USB-Geräte",
        "capabilities": ["USB 1.1", "USB 2.0", "USB 3.x", "Hotplug"],
        "safe_to_query": True,
    },
    "usbhid": {
        "category": "usb",
        "description": "USB Human Interface Device Treiber",
        "description_de": "Treiber für USB-Tastaturen, Mäuse, Gamepads",
        "safe_to_query": True,
    },
    "usb_storage": {
        "category": "usb",
        "description": "USB Mass Storage Treiber",
        "description_de": "Treiber für USB-Sticks und externe Festplatten",
        "safe_to_query": True,
    },
    "xhci_hcd": {
        "category": "usb",
        "description": "USB 3.0 xHCI Host Controller",
        "description_de": "USB 3.0/3.1/3.2 Controller-Treiber",
        "safe_to_query": True,
    },
    "ehci_hcd": {
        "category": "usb",
        "description": "USB 2.0 EHCI Host Controller",
        "description_de": "USB 2.0 Controller-Treiber",
        "safe_to_query": True,
    },

    # Funk/Wireless
    "rfkill": {
        "category": "wireless",
        "description": "RF Kill Switch Subsystem",
        "description_de": "Steuerung von Funknetzwerken (WLAN, Bluetooth an/aus)",
        "capabilities": ["WLAN-Kontrolle", "Bluetooth-Kontrolle", "Hardware-Kill-Switch"],
        "config_paths": ["/sys/class/rfkill"],
        "safe_to_query": True,
    },
    "cfg80211": {
        "category": "wireless",
        "description": "Linux Wireless Configuration API",
        "description_de": "Konfigurations-Framework für WLAN-Treiber",
        "safe_to_query": True,
    },
    "mac80211": {
        "category": "wireless",
        "description": "IEEE 802.11 Wireless Stack",
        "description_de": "Software-MAC-Layer für WLAN",
        "safe_to_query": True,
    },
    "iwlwifi": {
        "category": "wireless",
        "description": "Intel Wireless WiFi Treiber",
        "description_de": "Intel WLAN-Adapter (AX200, AX210, etc.)",
        "safe_to_query": True,
    },
    "bluetooth": {
        "category": "wireless",
        "description": "Bluetooth Core",
        "description_de": "Bluetooth-Protokoll-Stack",
        "capabilities": ["Bluetooth LE", "Audio-Profile", "HID-Profile"],
        "safe_to_query": True,
    },
    "btusb": {
        "category": "wireless",
        "description": "Bluetooth USB Treiber",
        "description_de": "USB-Bluetooth-Adapter Treiber",
        "safe_to_query": True,
    },

    # Netzwerk
    "r8169": {
        "category": "network",
        "description": "Realtek RTL8169 Ethernet Treiber",
        "description_de": "Realtek Gigabit Ethernet (RTL8111/8168/8169)",
        "safe_to_query": True,
    },
    "e1000e": {
        "category": "network",
        "description": "Intel Gigabit Ethernet Treiber",
        "description_de": "Intel PRO/1000 Netzwerkkarten",
        "safe_to_query": True,
    },
    "igb": {
        "category": "network",
        "description": "Intel Gigabit Ethernet (igb)",
        "description_de": "Intel Server-Netzwerkkarten (I210, I350)",
        "safe_to_query": True,
    },

    # Bibliotheken
    "libcrc32c": {
        "category": "library",
        "description": "CRC32c Bibliothek",
        "description_de": "Schnelle CRC32c Prüfsummen-Berechnung",
        "safe_to_query": True,
    },
    "libarc4": {
        "category": "library",
        "description": "ARC4 Cipher Bibliothek",
        "description_de": "ARC4 Stream-Cipher (für ältere Protokolle)",
        "safe_to_query": True,
    },

    # Virtualisierung
    "kvm": {
        "category": "virtualization",
        "description": "Kernel Virtual Machine",
        "description_de": "Hardware-Virtualisierung für VMs (QEMU/libvirt)",
        "capabilities": ["VM-Ausführung", "Hardware-Passthrough"],
        "safe_to_query": True,
    },
    "kvm_amd": {
        "category": "virtualization",
        "description": "KVM AMD-V Support",
        "description_de": "AMD Virtualisierungs-Erweiterungen (SVM)",
        "safe_to_query": True,
    },
    "kvm_intel": {
        "category": "virtualization",
        "description": "KVM Intel VT-x Support",
        "description_de": "Intel Virtualisierungs-Erweiterungen (VMX)",
        "safe_to_query": True,
    },

    # Speicher/Dateisystem
    "ext4": {
        "category": "filesystem",
        "description": "EXT4 Dateisystem",
        "description_de": "Standard Linux Dateisystem",
        "safe_to_query": True,
    },
    "btrfs": {
        "category": "filesystem",
        "description": "BTRFS Dateisystem",
        "description_de": "Copy-on-Write Dateisystem mit Snapshots",
        "safe_to_query": True,
    },
    "nvme": {
        "category": "storage",
        "description": "NVMe Controller Treiber",
        "description_de": "Treiber für NVMe SSDs",
        "safe_to_query": True,
    },
    "ahci": {
        "category": "storage",
        "description": "AHCI SATA Controller",
        "description_de": "SATA-Controller für Festplatten/SSDs",
        "safe_to_query": True,
    },

    # Eingabegeräte
    "hid": {
        "category": "input",
        "description": "Human Interface Device Core",
        "description_de": "Basis für Eingabegeräte (Tastatur, Maus, Gamepad)",
        "safe_to_query": True,
    },
    "hid_generic": {
        "category": "input",
        "description": "Generic HID Treiber",
        "description_de": "Generischer Treiber für HID-konforme Geräte",
        "safe_to_query": True,
    },
    "evdev": {
        "category": "input",
        "description": "Event Device Interface",
        "description_de": "Linux Input-Event Schnittstelle (/dev/input/event*)",
        "safe_to_query": True,
    },
}

# Kategorie-Beschreibungen
CATEGORY_DESCRIPTIONS = {
    "graphics": "Grafikkarten und Display-Treiber",
    "audio": "Audio-Treiber und Sound-Subsystem",
    "i2c": "I2C/SMBus Hardware-Kommunikation",
    "usb": "USB-Controller und Geräte-Treiber",
    "wireless": "WLAN, Bluetooth und Funk-Steuerung",
    "network": "Netzwerk-Adapter und Ethernet",
    "library": "Kernel-Bibliotheken und Hilfsfunktionen",
    "virtualization": "Virtualisierung (KVM, Container)",
    "filesystem": "Dateisysteme",
    "storage": "Speicher-Controller (NVMe, SATA)",
    "input": "Eingabegeräte (Tastatur, Maus)",
    "unknown": "Unbekannte/Undokumentierte Module",
}


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class DriverInfo:
    """Information über einen Kernel-Treiber."""
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
    """SQLite Datenbank für System Bridge."""

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
    System Bridge - Übersetzer zwischen Frank und Kernel-Treibern.

    Ermöglicht:
    - Erkennung geladener Module
    - Lookup von Treiber-Beschreibungen
    - Hinzufügen eigener Beschreibungen
    - Sichere Abfrage von Treiber-Informationen
    """

    def __init__(self):
        self.db = BridgeDB()
        self._lock = threading.Lock()
        self._populate_base_knowledge()
        LOG.info("System Bridge initialisiert (DB: %s)", BRIDGE_DB)

    def _populate_base_knowledge(self):
        """Fülle DB mit Basis-Wissen aus DRIVER_KNOWLEDGE_BASE."""
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
        Scanne aktuell geladene Kernel-Module.
        Returns Liste von DriverInfo Objekten.
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

                    # Lookup in DB oder Knowledge Base
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
            LOG.error("Fehler beim Scannen der Module: %s", e)

        return modules

    def get_driver_info(self, name: str) -> DriverInfo:
        """
        Hole Informationen über einen Treiber.
        Kombiniert DB-Wissen mit Knowledge Base.
        """
        # Erst DB prüfen
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

        # Dann Knowledge Base prüfen
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

        # Versuche Kategorie aus Namen abzuleiten
        category = self._infer_category(name)

        # Neuer unbekannter Treiber - in DB speichern
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
            description=f"Kernel-Modul '{name}' (keine Beschreibung verfügbar)",
            description_de=f"Kernel-Modul '{name}' (keine Beschreibung verfügbar)",
            last_seen=now,
        )

    def _infer_category(self, name: str) -> str:
        """Leite Kategorie aus Modulnamen ab."""
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
        Füge oder aktualisiere eine Treiber-Beschreibung.

        Args:
            name: Modulname
            description: Englische Beschreibung
            description_de: Deutsche Beschreibung (optional)
            category: Kategorie (optional)
            capabilities: Liste von Fähigkeiten (optional)
            custom_notes: Eigene Notizen (optional)

        Returns:
            True bei Erfolg
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
        LOG.info("Treiber-Beschreibung aktualisiert: %s", name)
        return True

    def get_modules_by_category(self, category: str) -> List[DriverInfo]:
        """Hole alle Module einer Kategorie."""
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
        """Finde Module ohne Beschreibung."""
        modules = self.scan_loaded_modules()
        return [m for m in modules if not m.description or m.category == "unknown"]

    def query_module_details(self, name: str) -> Dict:
        """
        Sichere Abfrage von Modul-Details aus /sys und modinfo.

        Returns dict mit erweiterten Informationen.
        """
        info = self.get_driver_info(name)
        result = info.to_dict()

        if not info.safe_to_query:
            result["warning"] = "Modul als unsicher für Abfragen markiert"
            return result

        # modinfo abfragen
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
            LOG.debug("modinfo fehlgeschlagen für %s: %s", name, e)

        # Parameter aus /sys/module/
        sys_path = Path(f"/sys/module/{name}/parameters")
        if sys_path.exists():
            result["parameters"] = {}
            try:
                for param in sys_path.iterdir():
                    try:
                        result["parameters"][param.name] = param.read_text().strip()
                    except:
                        result["parameters"][param.name] = "(nicht lesbar)"
            except:
                pass

        return result

    def get_summary(self) -> Dict:
        """Zusammenfassung des System-Zustands."""
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
        Generiere Kontext-String für Frank's Prompt-Injection.

        Args:
            query: Optionale Suchanfrage um relevante Module zu filtern

        Returns:
            Formatierter Kontext-String
        """
        lines = ["[System Bridge - Treiber-Wissen:"]

        if query:
            # Suche relevante Module
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
                    desc = r["description_de"] or r["description"] or "Keine Beschreibung"
                    lines.append(f"  - {r['name']} ({r['category']}): {desc}")
            else:
                lines.append(f"  Keine Module gefunden für: {query}")
        else:
            # Allgemeine Zusammenfassung
            summary = self.get_summary()
            lines.append(f"  {summary['total_modules']} Module geladen ({summary['total_size_mb']} MB)")
            for cat, count in summary["by_category"].items():
                cat_desc = CATEGORY_DESCRIPTIONS.get(cat, cat)
                lines.append(f"  - {cat}: {count} Module ({cat_desc})")

        lines.append("]")
        return "\n".join(lines)


# =============================================================================
# Singleton & Convenience
# =============================================================================

_bridge: Optional[SystemBridge] = None


def get_bridge() -> SystemBridge:
    """Hole oder erstelle System Bridge Instanz."""
    global _bridge
    if _bridge is None:
        _bridge = SystemBridge()
    return _bridge


def scan() -> List[Dict]:
    """Scanne geladene Module."""
    return [m.to_dict() for m in get_bridge().scan_loaded_modules()]


def lookup(name: str) -> Dict:
    """Lookup eines Treibers."""
    return get_bridge().get_driver_info(name).to_dict()


def describe(name: str, description: str, **kwargs) -> bool:
    """Füge Beschreibung hinzu."""
    return get_bridge().add_description(name, description, **kwargs)


def summary() -> Dict:
    """System-Zusammenfassung."""
    return get_bridge().get_summary()


def context(query: str = None) -> str:
    """Kontext für Frank."""
    return get_bridge().context_for_frank(query)


# =============================================================================
# CLI
# =============================================================================

def _cli_main():
    import argparse

    parser = argparse.ArgumentParser(
        description="System Bridge - Treiber-Awareness für Frank",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Befehle:
  scan            Scanne geladene Kernel-Module
  lookup NAME     Zeige Info zu einem Modul
  describe NAME   Füge Beschreibung hinzu
  category CAT    Zeige Module einer Kategorie
  undocumented    Zeige Module ohne Beschreibung
  summary         System-Zusammenfassung
  context [QUERY] Generiere Kontext für Frank
        """
    )
    parser.add_argument("command", nargs="?", default="summary")
    parser.add_argument("arg", nargs="?", help="Argument für Befehl")
    parser.add_argument("--desc", help="Beschreibung (für describe)")
    parser.add_argument("--desc-de", help="Deutsche Beschreibung")
    parser.add_argument("--category", help="Kategorie")
    parser.add_argument("--json", action="store_true", help="JSON-Ausgabe")

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
        print("=== Geladene Kernel-Module ===")
        modules = bridge.scan_loaded_modules()
        for m in sorted(modules, key=lambda x: x.category):
            desc = m.description_de or m.description or "(keine Beschreibung)"
            print(f"[{m.category:12}] {m.name:30} {m.size_kb:6} KB  {desc[:50]}")
        print(f"\nGesamt: {len(modules)} Module")

    elif cmd == "lookup":
        if not args.arg:
            print("Fehler: Modulname erforderlich")
            return
        info = bridge.query_module_details(args.arg)
        print(f"=== {args.arg} ===")
        _out(info)

    elif cmd == "describe":
        if not args.arg:
            print("Fehler: Modulname erforderlich")
            return
        if not args.desc:
            print("Fehler: --desc erforderlich")
            return
        bridge.add_description(
            args.arg,
            args.desc,
            description_de=args.desc_de,
            category=args.category
        )
        print(f"Beschreibung für '{args.arg}' aktualisiert")

    elif cmd == "category":
        if not args.arg:
            print("Verfügbare Kategorien:")
            for cat, desc in CATEGORY_DESCRIPTIONS.items():
                print(f"  {cat:15} - {desc}")
            return
        modules = bridge.get_modules_by_category(args.arg)
        print(f"=== Kategorie: {args.arg} ===")
        for m in modules:
            print(f"  {m.name}: {m.description_de or m.description or '(keine Beschreibung)'}")

    elif cmd == "undocumented":
        print("=== Module ohne Beschreibung ===")
        modules = bridge.get_undocumented_modules()
        for m in modules:
            print(f"  [{m.category}] {m.name}")
        print(f"\n{len(modules)} undokumentierte Module")

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
