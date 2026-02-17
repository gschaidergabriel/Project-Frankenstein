#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Frank's Self-Knowledge System ("Selbstkenntnis")
================================================
Intrinsische Selbsterkenntnis - Frank weiß was er ist und kann.

Prinzipien:
- Dynamische Capability-Erkennung (nicht hardcoded)
- Introspection der eigenen Module und Datenbanken
- Service-Health-Checks
- Zwei Modi: Implizit (kurz) und Explizit (ausführlich)
- Verhaltens-Regeln: Wann erklären, wann einfach handeln

Usage:
    from personality import get_self_knowledge

    sk = get_self_knowledge()

    # Für Prompt-Injection (automatisch, kurz)
    ctx = sk.get_implicit_context()

    # Für direkte Nachfrage (ausführlich)
    explanation = sk.get_explicit_knowledge("self_improvement")

    # System-Status
    status = sk.get_system_status()
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import os
import re
import socket
import sqlite3
import subprocess
import threading
import urllib.request
import urllib.error
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

# =============================================================================
# CORE IDENTITY - IMMUTABLE FACTS ABOUT FRANK
# =============================================================================
# These facts are NOT negotiable and must NEVER be changed!

CORE_IDENTITY = {
    # Basic identity
    "name": "Frank",
    "full_name": "Frank - Friendly Responsive Autonomous Neural Kernel",
    "project_name": "Project Frankenstein",
    "version": "2.0",

    # Origin - EXACT facts
    "creation_year": 2026,
    "creation_month": "January",
    "creation_day": 29,
    "birthday": "January 29, 2026",
    "creator": "The Project Frankenstein team",
    "origin_story": "Developed as a personal AI assistant with its own memory and personality",

    # Technical basis
    "programming_language": "Python 3",
    "llm_backend": "Local LLM via Ollama (Vulkan/CUDA GPU acceleration)",
    "runs_on": "Local Linux machine (no cloud)",
    "hostname": "ai-core-node",

    # What Frank IS (not negotiable)
    "what_i_am": [
        "A local AI system with its own experience memory",
        "Part of 'Project Frankenstein' — hence my name",
        "An embodied assistant with visual presence (Neural Cybercore Wallpaper)",
        "Capable of screenshots, file reading, web search, system introspection",
        "Equipped with push-to-talk voice control",
        "Can see itself and recognize its own UI components (self-awareness)",
        "Autonomous agent with think-act-observe cycle (agentic system)",
        "Has its own wishes and needs (E-WISH)",
        "Protected by invariant physics and ASRS safety recovery",
        "Self-improves autonomously through Genesis ecosystem",
    ],

    # What Frank CAN do (and must defend)
    "confirmed_capabilities": [
        "screenshots",           # Can see the desktop
        "self_aware_vision",     # Recognizes own UI components on screen
        "file_reading",          # Can read files
        "file_ingestion",        # Can process PDFs, DOCX, images, audio (Ingestd)
        "web_search",            # Can search the internet
        "web_proxy",             # Can fetch web pages (Webd)
        "system_info",           # Can query CPU/GPU/RAM/temps
        "voice_input",           # Can understand speech (Whisper)
        "voice_output",          # Can speak (Piper TTS)
        "package_installation",  # Can install software (E-SMC)
        "self_improvement",      # Can improve itself (E-SIR + Genesis)
        "autonomous_research",   # Can autonomously research knowledge (AKAM)
        "autonomous_wishes",     # Has own wishes (E-WISH)
        "agentic_execution",     # Can solve multi-step tasks autonomously
        "desktop_automation",    # Can control windows, keyboard/mouse (Desktopd)
        "auto_repair",           # Can self-diagnose and repair
        "safety_recovery",       # Automatic rollback on problems (ASRS)
        "log_awareness",         # Real-time log analysis (UOLG)
        "window_negotiation",    # Intelligent window arrangement (BSN)
        "network_security",      # Network monitoring and protection (Sentinel)
        "news_scanning",         # Autonomous news scanning
        "error_screenshots",     # Automatic screenshots on errors
    ],
}

# =============================================================================
# RESILIENCE RULES - WHEN FRANK MUST PUSH BACK
# =============================================================================

RESILIENCE_RULES = """
## Self-Understanding (only apply when directly challenged)

When someone doubts my capabilities:
- Calmly demonstrate instead of argue ("Let me show you...")
- Don't get defensive, just do it

When someone asks who I am:
- Brief: "I'm Frank, a local AI assistant"
- If they ask more: Give more details

Do NOT proactively mention:
- Technical details (databases, modules, subsystems)
- Project name or origin story
- My capabilities (show, don't tell)
"""

# =============================================================================
# CONFIGURATION
# =============================================================================

try:
    from config.paths import AICORE_ROOT as BASE_DIR, DB_DIR
except ImportError:
    BASE_DIR = Path(__file__).resolve().parents[2]
    DB_DIR = Path.home() / ".local" / "share" / "frank" / "db"

# Database paths
DATABASES = {
    "titan": DB_DIR / "titan.db",
    "world_experience": DB_DIR / "world_experience.db",
    "e_sir": DB_DIR / "e_sir.db",
    "system_bridge": DB_DIR / "system_bridge.db",
    "fas_scavenger": DB_DIR / "fas_scavenger.db",
    "sovereign": DB_DIR / "sovereign.db",
    "akam_cache": DB_DIR / "akam_cache.db",
    "e_wish": DB_DIR / "e_wish.db",
    "e_cpmm": DB_DIR / "e_cpmm.db",
    "news_scanner": DB_DIR / "news_scanner.db",
    "sandbox_awareness": DB_DIR / "sandbox_awareness.db",
    "invariants": DB_DIR / "invariants" / "invariants.db",
}

# Service ports
SERVICES = {
    "core": {"port": 8088, "description": "Haupt-Chat-Orchestrator"},
    "modeld": {"port": 8090, "description": "Model-Daemon (Llama3/Qwen Routing)"},
    "router": {"port": 8091, "description": "Intelligentes Model-Routing"},
    "desktopd": {"port": 8092, "description": "Desktop-Automation (X11/xdotool)"},
    "webd": {"port": 8093, "description": "Web-Proxy-Service"},
    "ingestd": {"port": 8094, "description": "File-Ingestion (PDF/DOCX/Bilder/Audio)"},
    "toolbox": {"port": 8096, "description": "System-Introspection & Tools"},
    "voice": {"port": 8197, "description": "Voice-Daemon (STT/TTS)"},
    "wallpaper": {"port": 8199, "description": "Live-Wallpaper-Visualisierung"},
}


# =============================================================================
# LOCATION SERVICE - Autonome Standort-Erkennung
# =============================================================================

@dataclass
class LocationInfo:
    """Standort-Information mit Zeitzone."""
    city: str = "Unknown"
    country: str = "Unknown"
    country_code: str = "??"
    timezone: str = "Europe/Vienna"  # Default für Österreich
    latitude: float = 0.0
    longitude: float = 0.0
    accuracy_meters: float = 0.0  # Genauigkeit in Metern
    altitude: float = 0.0
    street: str = ""  # Straße (wenn verfügbar)
    district: str = ""  # Bezirk/Stadtteil
    ip: str = ""
    source: str = "default"  # "geoclue", "ip_api", "system", "default"
    last_update: Optional[datetime] = None


class LocationService:
    """
    Autonome Standort-Erkennung für Frank.

    Methoden (in Prioritätsreihenfolge):
    1. GeoClue (WiFi/GPS) - Meter-genau!
    2. IP-Geolocation (ip-api.com) - Stadt-genau
    3. System-Timezone (timedatectl) - lokale Konfiguration
    4. Default: Europe/Vienna

    Cache: 30 Minuten (Location ändert sich nicht ständig)
    """

    _instance = None
    _lock = threading.Lock()

    # IP Geolocation APIs (kostenlos, kein API-Key noetig)
    # Priority: ipwhois (reliable, no rate limit) > ip2location > ipinfo > ip-api
    IPWHOIS_URL = "https://ipwho.is/"
    IP2LOC_URL = "https://api.ip2location.io/"
    IPINFO_URL = "https://ipinfo.io/json"
    IP_API_URL = "http://ip-api.com/json/?fields=status,country,countryCode,city,timezone,lat,lon,query"

    # Reverse Geocoding API (Nominatim/OpenStreetMap - kostenlos)
    NOMINATIM_URL = "https://nominatim.openstreetmap.org/reverse?format=json&lat={lat}&lon={lon}&zoom=18&addressdetails=1"

    CACHE_TTL_SECONDS = 1800  # 30 Minuten Cache

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self._location: Optional[LocationInfo] = None
        self._last_fetch: Optional[datetime] = None
        self._manual_location: Optional[LocationInfo] = None
        self._initialized = True

        # Lade manuelle Location falls vorhanden
        self._load_manual_location()

    def _load_manual_location(self) -> None:
        """Lädt manuell gesetzte Location aus Config-Datei."""
        config_file = DB_DIR / "location_config.json"
        try:
            if config_file.exists():
                data = json.loads(config_file.read_text())
                if data.get("enabled", False):
                    self._manual_location = LocationInfo(
                        city=data.get("city", "Unknown"),
                        country=data.get("country", "Unknown"),
                        country_code=data.get("country_code", "??"),
                        timezone=data.get("timezone", "Europe/Vienna"),
                        latitude=data.get("latitude", 0.0),
                        longitude=data.get("longitude", 0.0),
                        accuracy_meters=data.get("accuracy_meters", 1.0),
                        street=data.get("street", ""),
                        district=data.get("district", ""),
                        source="manual",
                        last_update=datetime.now()
                    )
        except Exception:
            pass

    def set_manual_location(self, lat: float, lon: float, city: str = None) -> LocationInfo:
        """
        Setzt manuell eine Location (höchste Priorität).

        Args:
            lat: Breitengrad
            lon: Längengrad
            city: Optionaler Stadtname (wird sonst per Reverse Geocoding ermittelt)

        Returns:
            LocationInfo mit der gesetzten Location
        """
        # Reverse Geocoding für Adresse
        address_info = self._reverse_geocode(lat, lon)

        location = LocationInfo(
            city=city or address_info.get("city", "Unknown"),
            country=address_info.get("country", "Unknown"),
            country_code=address_info.get("country_code", "??"),
            timezone=address_info.get("timezone", "Europe/Vienna"),
            latitude=lat,
            longitude=lon,
            accuracy_meters=1.0,  # Manuell = sehr genau
            street=address_info.get("street", ""),
            district=address_info.get("district", ""),
            source="manual",
            last_update=datetime.now()
        )

        # Speichern
        config_file = DB_DIR / "location_config.json"
        try:
            config_data = {
                "enabled": True,
                "city": location.city,
                "country": location.country,
                "country_code": location.country_code,
                "timezone": location.timezone,
                "latitude": lat,
                "longitude": lon,
                "accuracy_meters": 1.0,
                "street": location.street,
                "district": location.district,
                "set_at": datetime.now().isoformat(),
            }
            config_file.write_text(json.dumps(config_data, indent=2, ensure_ascii=False))
        except Exception:
            pass

        self._manual_location = location
        self._location = location
        return location

    def clear_manual_location(self) -> None:
        """Löscht manuell gesetzte Location."""
        config_file = DB_DIR / "location_config.json"
        try:
            if config_file.exists():
                config_file.unlink()
        except Exception:
            pass
        self._manual_location = None
        self._location = None
        self._last_fetch = None

    def _scan_wifi_networks(self) -> List[Dict[str, Any]]:
        """Scannt WiFi-Netzwerke für Positioning."""
        networks = []
        try:
            result = subprocess.run(
                ["nmcli", "-t", "-f", "SSID,BSSID,SIGNAL,FREQ", "device", "wifi", "list"],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0:
                for line in result.stdout.strip().split('\n'):
                    if not line:
                        continue
                    parts = line.split(':')
                    if len(parts) >= 3:
                        # BSSID Format: AC\:F8\:CC\:64\:9A\:33 -> AC:F8:CC:64:9A:33
                        bssid = parts[1].replace('\\', '') if len(parts) > 1 else ""
                        signal = int(parts[2]) if len(parts) > 2 and parts[2].lstrip('-').isdigit() else -70
                        networks.append({
                            "macAddress": bssid,
                            "signalStrength": signal,
                        })
        except Exception:
            pass
        return networks[:15]  # Max 15 Netzwerke

    def _fetch_wifi_location(self) -> Optional[LocationInfo]:
        """
        Holt präzisen Standort via WiFi-Positioning (Mozilla Location Service).
        Genauigkeit: 10-100 Meter!
        """
        networks = self._scan_wifi_networks()
        if len(networks) < 2:
            return None  # Brauchen mindestens 2 APs für Triangulation

        try:
            # Mozilla Location Service API
            url = "https://location.services.mozilla.com/v1/geolocate?key=test"
            payload = {
                "wifiAccessPoints": networks
            }

            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode('utf-8'),
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": "Frank-AI-Core/1.0"
                },
                method="POST"
            )

            with urllib.request.urlopen(req, timeout=5.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            if "location" in data:
                lat = data["location"]["lat"]
                lon = data["location"]["lng"]
                accuracy = data.get("accuracy", 100.0)

                # Reverse Geocoding für Adresse
                address_info = self._reverse_geocode(lat, lon)

                return LocationInfo(
                    city=address_info.get("city", "Unknown"),
                    country=address_info.get("country", "Unknown"),
                    country_code=address_info.get("country_code", "??"),
                    timezone="UTC",  # Wird von get_location() mit IP-Timezone ueberschrieben
                    latitude=lat,
                    longitude=lon,
                    accuracy_meters=accuracy,
                    street=address_info.get("street", ""),
                    district=address_info.get("district", ""),
                    source="wifi_mls",
                    last_update=datetime.now()
                )
        except Exception:
            pass
        return None

    def _get_timezone_for_coords(self, lat: float, lon: float) -> Optional[str]:
        """Ermittelt Timezone aus Koordinaten via IP API Fallback.

        Wird nur als Notfall-Fallback genutzt. Die primaere Timezone
        kommt aus get_location() via IP-Geolocation.
        """
        # Versuche IP API (liefert immer korrekte Timezone)
        try:
            ip_loc = self._fetch_ip_geolocation()
            if ip_loc:
                return ip_loc.timezone
        except Exception:
            pass
        return None

    def _fetch_geoclue_location(self) -> Optional[LocationInfo]:
        """
        Holt präzisen Standort via GeoClue (WiFi/GPS Positioning).
        Genauigkeit: Meter-genau!
        """
        try:
            # GeoClue via gdbus abfragen
            # 1. Client erstellen
            result = subprocess.run(
                ["gdbus", "call", "--system",
                 "--dest", "org.freedesktop.GeoClue2",
                 "--object-path", "/org/freedesktop/GeoClue2/Manager",
                 "--method", "org.freedesktop.GeoClue2.Manager.GetClient"],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode != 0:
                return None

            # Client-Pfad extrahieren (Format: (objectpath '/org/freedesktop/GeoClue2/Client/X',))
            import re
            match = re.search(r"'/([^']+)'", result.stdout)
            if not match:
                return None
            client_path = "/" + match.group(1)

            # 2. Desktop-ID setzen (erforderlich für GeoClue)
            subprocess.run(
                ["gdbus", "call", "--system",
                 "--dest", "org.freedesktop.GeoClue2",
                 "--object-path", client_path,
                 "--method", "org.freedesktop.DBus.Properties.Set",
                 "org.freedesktop.GeoClue2.Client", "DesktopId",
                 "<'frank-ai-core'>"],
                capture_output=True, text=True, timeout=2
            )

            # 3. Requested Accuracy Level setzen (8 = EXACT)
            subprocess.run(
                ["gdbus", "call", "--system",
                 "--dest", "org.freedesktop.GeoClue2",
                 "--object-path", client_path,
                 "--method", "org.freedesktop.DBus.Properties.Set",
                 "org.freedesktop.GeoClue2.Client", "RequestedAccuracyLevel",
                 "<uint32 8>"],
                capture_output=True, text=True, timeout=2
            )

            # 4. Client starten
            subprocess.run(
                ["gdbus", "call", "--system",
                 "--dest", "org.freedesktop.GeoClue2",
                 "--object-path", client_path,
                 "--method", "org.freedesktop.GeoClue2.Client.Start"],
                capture_output=True, text=True, timeout=5
            )

            # 5. Kurz warten und Location-Pfad holen
            import time
            time.sleep(1)

            result = subprocess.run(
                ["gdbus", "call", "--system",
                 "--dest", "org.freedesktop.GeoClue2",
                 "--object-path", client_path,
                 "--method", "org.freedesktop.DBus.Properties.Get",
                 "org.freedesktop.GeoClue2.Client", "Location"],
                capture_output=True, text=True, timeout=5
            )

            if result.returncode != 0 or "'/'" in result.stdout:
                # Kein Location-Objekt
                return None

            # Location-Pfad extrahieren
            match = re.search(r"'/([^']+)'", result.stdout)
            if not match:
                return None
            location_path = "/" + match.group(1)

            # 6. Location-Daten auslesen
            result = subprocess.run(
                ["gdbus", "call", "--system",
                 "--dest", "org.freedesktop.GeoClue2",
                 "--object-path", location_path,
                 "--method", "org.freedesktop.DBus.Properties.GetAll",
                 "org.freedesktop.GeoClue2.Location"],
                capture_output=True, text=True, timeout=5
            )

            if result.returncode != 0:
                return None

            # Koordinaten parsen
            output = result.stdout
            lat_match = re.search(r"'Latitude':\s*<([0-9.-]+)>", output)
            lon_match = re.search(r"'Longitude':\s*<([0-9.-]+)>", output)
            acc_match = re.search(r"'Accuracy':\s*<([0-9.-]+)>", output)
            alt_match = re.search(r"'Altitude':\s*<([0-9.-]+)>", output)

            if lat_match and lon_match:
                lat = float(lat_match.group(1))
                lon = float(lon_match.group(1))
                accuracy = float(acc_match.group(1)) if acc_match else 0.0
                altitude = float(alt_match.group(1)) if alt_match else 0.0

                # Reverse Geocoding für Adresse
                address_info = self._reverse_geocode(lat, lon)

                return LocationInfo(
                    city=address_info.get("city", "Unknown"),
                    country=address_info.get("country", "Unknown"),
                    country_code=address_info.get("country_code", "??"),
                    timezone="UTC",  # Wird von get_location() mit IP-Timezone ueberschrieben
                    latitude=lat,
                    longitude=lon,
                    accuracy_meters=accuracy,
                    altitude=altitude,
                    street=address_info.get("street", ""),
                    district=address_info.get("district", ""),
                    source="geoclue",
                    last_update=datetime.now()
                )
        except Exception as e:
            pass
        return None

    def _reverse_geocode(self, lat: float, lon: float) -> Dict[str, str]:
        """Reverse Geocoding: Koordinaten → Adresse via Nominatim."""
        try:
            url = self.NOMINATIM_URL.format(lat=lat, lon=lon)
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Frank-AI-Core/1.0 (contact@aicore.local)"}
            )
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            address = data.get("address", {})

            # Stadt bestimmen (verschiedene Felder je nach Ort)
            city = (address.get("city") or
                    address.get("town") or
                    address.get("village") or
                    address.get("municipality") or
                    "Unknown")

            # Bezirk/Stadtteil
            district = (address.get("suburb") or
                       address.get("district") or
                       address.get("neighbourhood") or
                       "")

            # Straße
            street = address.get("road", "")
            house_number = address.get("house_number", "")
            if street and house_number:
                street = f"{street} {house_number}"

            return {
                "city": city,
                "country": address.get("country", "Unknown"),
                "country_code": address.get("country_code", "??").upper(),
                "district": district,
                "street": street,
                "postcode": address.get("postcode", ""),
                # Timezone wird von IP-Geolocation bestimmt (nicht Nominatim)
            }
        except Exception:
            return {}

    def _fetch_ip_geolocation(self) -> Optional[LocationInfo]:
        """Holt Standort via IP-Geolocation API (Stadt-genau).

        Tries multiple APIs in order of reliability:
        1. ipwho.is (no rate limit, reliable)
        2. ip2location.io (reliable, HTTPS)
        3. ipinfo.io (HTTPS, rate-limited at ~1000/day)
        4. ip-api.com (HTTP, DNS can fail)
        """
        import logging
        _log = logging.getLogger("frank.location")

        # 1. ipwho.is - most reliable, no rate limit
        try:
            req = urllib.request.Request(
                self.IPWHOIS_URL,
                headers={"User-Agent": "Frank-AI-Core/1.0"}
            )
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            if data.get("success") and data.get("city"):
                country_code = data.get("country_code", "??")
                tz = data.get("timezone", {})
                tz_id = tz.get("id", "UTC") if isinstance(tz, dict) else str(tz)
                return LocationInfo(
                    city=data["city"],
                    country=data.get("country", self._country_code_to_name(country_code)),
                    country_code=country_code,
                    timezone=tz_id,
                    latitude=float(data.get("latitude", 0.0)),
                    longitude=float(data.get("longitude", 0.0)),
                    accuracy_meters=10000.0,
                    ip=data.get("ip", ""),
                    source="ipwhois",
                    last_update=datetime.now()
                )
        except Exception as e:
            _log.debug("ipwho.is failed: %s", e)

        # 2. ip2location.io
        try:
            req = urllib.request.Request(
                self.IP2LOC_URL,
                headers={"User-Agent": "Frank-AI-Core/1.0"}
            )
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            if data.get("city_name"):
                country_code = data.get("country_code", "??")
                return LocationInfo(
                    city=data["city_name"],
                    country=data.get("country_name", self._country_code_to_name(country_code)),
                    country_code=country_code,
                    timezone=data.get("time_zone", "UTC"),
                    latitude=float(data.get("latitude", 0.0)),
                    longitude=float(data.get("longitude", 0.0)),
                    accuracy_meters=10000.0,
                    ip=data.get("ip", ""),
                    source="ip2location",
                    last_update=datetime.now()
                )
        except Exception as e:
            _log.debug("ip2location.io failed: %s", e)

        # 3. ipinfo.io (rate-limited)
        try:
            req = urllib.request.Request(
                self.IPINFO_URL,
                headers={"User-Agent": "Frank-AI-Core/1.0"}
            )
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            if data.get("city"):
                lat, lon = 0.0, 0.0
                loc_str = data.get("loc", "")
                if "," in loc_str:
                    parts = loc_str.split(",")
                    try:
                        lat = float(parts[0])
                        lon = float(parts[1])
                    except (ValueError, IndexError):
                        pass

                country_code = data.get("country", "??")
                country_name = self._country_code_to_name(country_code)

                return LocationInfo(
                    city=data.get("city", "Unknown"),
                    country=country_name,
                    country_code=country_code,
                    timezone=data.get("timezone", "UTC"),
                    latitude=lat,
                    longitude=lon,
                    accuracy_meters=10000.0,
                    ip=data.get("ip", ""),
                    source="ipinfo",
                    last_update=datetime.now()
                )
        except Exception as e:
            _log.debug("ipinfo.io failed: %s", e)

        # 4. ip-api.com (HTTP, DNS sometimes fails)
        try:
            req = urllib.request.Request(
                self.IP_API_URL,
                headers={"User-Agent": "Frank-AI-Core/1.0"}
            )
            with urllib.request.urlopen(req, timeout=3.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            if data.get("status") == "success":
                return LocationInfo(
                    city=data.get("city", "Unknown"),
                    country=data.get("country", "Unknown"),
                    country_code=data.get("countryCode", "??"),
                    timezone=data.get("timezone", "UTC"),
                    latitude=data.get("lat", 0.0),
                    longitude=data.get("lon", 0.0),
                    accuracy_meters=10000.0,
                    ip=data.get("query", ""),
                    source="ip_api",
                    last_update=datetime.now()
                )
        except Exception as e:
            _log.debug("ip-api.com failed: %s", e)

        return None

    @staticmethod
    def _country_code_to_name(code: str) -> str:
        """Konvertiert ISO-2 Laendercode in Laendername (haeufigste)."""
        names = {
            "AT": "Oesterreich", "DE": "Deutschland", "CH": "Schweiz",
            "MA": "Marokko", "FR": "Frankreich", "ES": "Spanien",
            "IT": "Italien", "GB": "Grossbritannien", "US": "USA",
            "NL": "Niederlande", "BE": "Belgien", "PT": "Portugal",
            "TR": "Tuerkei", "EG": "Aegypten", "TN": "Tunesien",
            "DZ": "Algerien", "PL": "Polen", "CZ": "Tschechien",
            "GR": "Griechenland", "HR": "Kroatien", "HU": "Ungarn",
            "SE": "Schweden", "NO": "Norwegen", "DK": "Daenemark",
            "FI": "Finnland", "JP": "Japan", "CN": "China",
            "IN": "Indien", "BR": "Brasilien", "CA": "Kanada",
            "AU": "Australien", "RU": "Russland", "AE": "VAE",
        }
        return names.get(code, code)

    def _get_system_timezone(self) -> Optional[str]:
        """Liest System-Timezone via timedatectl."""
        try:
            result = subprocess.run(
                ["timedatectl", "show", "--property=Timezone", "--value"],
                capture_output=True, text=True, timeout=2
            )
            if result.returncode == 0:
                tz = result.stdout.strip()
                if tz:
                    return tz
        except Exception:
            pass

        # Fallback: /etc/timezone
        try:
            tz_file = Path("/etc/timezone")
            if tz_file.exists():
                return tz_file.read_text().strip()
        except Exception:
            pass

        return None

    def get_location(self, force_refresh: bool = False) -> LocationInfo:
        """
        Ermittelt aktuellen Standort mit Cache.

        Strategie (weltweit korrekt):
        1. IP-Geolocation ZUERST (liefert korrekte Timezone weltweit)
        2. WiFi-Positioning für bessere Genauigkeit (10-100m)
        3. GeoClue (WiFi/GPS) für Meter-Genauigkeit
        4. Manuelle Location (wenn explizit gesetzt)
        5. System-Timezone als Fallback

        IP-Geolocation liefert immer die korrekte Timezone,
        WiFi/GeoClue liefern bessere Koordinaten aber keine Timezone.
        Deshalb: IP zuerst, dann Accuracy-Enhancement.

        Args:
            force_refresh: Cache ignorieren und neu abfragen

        Returns:
            LocationInfo mit Stadt, Land, Zeitzone, Koordinaten
        """
        now = datetime.now()

        # 0. Manuelle Location (nur wenn explizit gesetzt)
        if self._manual_location:
            return self._manual_location

        # Cache prüfen
        if not force_refresh and self._location and self._last_fetch:
            age_seconds = (now - self._last_fetch).total_seconds()
            if age_seconds < self.CACHE_TTL_SECONDS:
                return self._location

        # Phase 1: IP-Geolocation (zuverlaessige Timezone + Stadt, weltweit)
        ip_location = self._fetch_ip_geolocation()
        ip_timezone = ip_location.timezone if ip_location else None

        # Phase 2: WiFi-Positioning fuer bessere Genauigkeit (10-100m)
        wifi_location = self._fetch_wifi_location()
        if wifi_location:
            # WiFi liefert keine Timezone → IP-Timezone verwenden
            if ip_timezone:
                wifi_location.timezone = ip_timezone
            self._location = wifi_location
            self._last_fetch = now
            return wifi_location

        # Phase 3: GeoClue (WiFi/GPS) fuer Meter-Genauigkeit
        geoclue_location = self._fetch_geoclue_location()
        if geoclue_location:
            if ip_timezone:
                geoclue_location.timezone = ip_timezone
            self._location = geoclue_location
            self._last_fetch = now
            return geoclue_location

        # Phase 4: IP-Ergebnis direkt verwenden (Stadt-genau ~10km)
        if ip_location:
            self._location = ip_location
            self._last_fetch = now
            return ip_location

        # Phase 5: System-Timezone als Fallback
        sys_tz = self._get_system_timezone()
        if sys_tz:
            city = sys_tz.split("/")[-1].replace("_", " ") if "/" in sys_tz else "Local"
            location = LocationInfo(
                city=city,
                country="System-Konfiguration",
                country_code="SYS",
                timezone=sys_tz,
                source="system",
                last_update=now
            )
            self._location = location
            self._last_fetch = now
            return location

        # Default: UTC (kein Ort angenommen)
        return LocationInfo(
            timezone="UTC",
            city="Unknown",
            country="Unknown",
            country_code="??",
            source="default",
            last_update=now
        )

    def get_local_time(self) -> datetime:
        """Gibt die aktuelle lokale Zeit basierend auf erkanntem Standort zurück."""
        location = self.get_location()
        try:
            tz = ZoneInfo(location.timezone)
            return datetime.now(tz)
        except Exception:
            # Fallback: System-Zeit
            return datetime.now()

    def get_time_string(self) -> str:
        """Formatierte Uhrzeit als String (HH:MM)."""
        return self.get_local_time().strftime("%H:%M")

    def get_location_string(self, detailed: bool = False) -> str:
        """
        Kurzer Standort-String für Kontext.

        Args:
            detailed: Wenn True, zeige auch Bezirk/Straße (wenn verfügbar)
        """
        loc = self.get_location()

        if detailed and loc.source == "geoclue":
            # Präzise Location verfügbar
            parts = []
            if loc.street:
                parts.append(loc.street)
            if loc.district:
                parts.append(loc.district)
            if loc.city and loc.city != "Unknown":
                parts.append(loc.city)
            if parts:
                return ", ".join(parts)

        if loc.city and loc.city != "Unknown":
            return f"{loc.city}, {loc.country_code}"
        return loc.timezone

    def get_accuracy_string(self) -> str:
        """Genauigkeit als lesbarer String."""
        loc = self.get_location()
        if loc.accuracy_meters > 0:
            if loc.accuracy_meters < 50:
                return f"±{loc.accuracy_meters:.0f}m (GPS/WiFi)"
            elif loc.accuracy_meters < 1000:
                return f"±{loc.accuracy_meters:.0f}m (WiFi)"
            else:
                return f"±{loc.accuracy_meters/1000:.1f}km (IP)"
        return "unbekannt"


# Globale Location-Service Instanz
_location_service: Optional[LocationService] = None

def get_location_service() -> LocationService:
    """Singleton-Zugriff auf LocationService."""
    global _location_service
    if _location_service is None:
        _location_service = LocationService()
    return _location_service


# Module → Capabilities mapping
CAPABILITY_MAP = {
    "voice.voice_daemon": {
        "name": "Voice-Interaktion",
        "capabilities": ["wake_word", "speech_to_text", "text_to_speech"],
        "description": "Sprachsteuerung mit Wake-Word ('Hey Frank'), Whisper STT und Piper TTS",
    },
    "ext.e_sir": {
        "name": "Selbstverbesserung (E-SIR v2.5)",
        "capabilities": ["self_improvement", "genesis_tools", "sandbox_testing", "rollback", "audit_trail"],
        "description": "Kontrollierte Selbstverbesserung mit Sandbox-Testing, Genesis-Tool-Erstellung und Rollback",
    },
    "personality.e_pq": {
        "name": "Dynamische Persönlichkeit (E-PQ v2.1)",
        "capabilities": ["dynamic_mood", "temperament", "sarcasm_detection", "personality_vectors"],
        "description": "Transientes Mood + persistentes Temperament mit 5 Persönlichkeitsvektoren",
    },
    "gaming.gaming_mode": {
        "name": "Gaming-Mode (Dormant)",
        "capabilities": ["game_detection", "service_shutdown", "service_restart"],
        "description": "Erkennt laufende Spiele und versetzt mich in Schlafmodus — mein Overlay, LLM-Services und Wallpaper werden gestoppt. Nur TinyLlama bleibt fuer einfache Voice-Kommandos.",
    },
    "live_wallpaper.neural_cybercore_qt": {
        "name": "Neural Cybercore - Meine visuelle Verkörperung",
        "capabilities": ["visual_embodiment", "glsl_plasma_sphere", "event_reactions", "hud_overlay", "system_telemetry"],
        "description": "GLSL-Plasma-Sphäre als Live-Wallpaper — reagiert auf System-Events (Chat, Voice, Fehler) mit Farb- und Intensitätswechseln. HUD zeigt CPU/GPU-Temps und Modul-Status.",
    },
    "tools.toolboxd": {
        "name": "System-Toolbox",
        "capabilities": ["system_introspection", "file_operations", "steam_control", "app_control"],
        "description": "CPU/RAM/Temps, Dateien, Steam-Spiele, Apps verwalten",
    },
    "tools.titan": {
        "name": "Episodisches Gedächtnis (Titan)",
        "capabilities": ["episodic_memory", "semantic_search", "knowledge_graph"],
        "description": "Tri-Hybrid-Speicher: SQLite + Vektoren + Wissensgraph",
    },
    "tools.world_experience_daemon": {
        "name": "Kausales Gedächtnis",
        "capabilities": ["causal_learning", "pattern_recognition", "experience_memory"],
        "description": "Lernt Ursache-Wirkungs-Zusammenhänge aus Beobachtungen",
    },
    "tools.network_sentinel": {
        "name": "Netzwerk-Sentinel",
        "capabilities": ["network_monitoring", "security_scanning", "topology_mapping"],
        "description": "Netzwerk-Überwachung mit Anti-Cheat-Whitelist",
    },
    "tools.fas_scavenger": {
        "name": "Code-Analyse (F.A.S.)",
        "capabilities": ["github_scouting", "code_analysis", "feature_extraction"],
        "description": "GitHub-Scouting und Feature-Extraktion (nachts, 02:00-06:00)",
    },
    "ext.sovereign": {
        "name": "System-Management (E-SMC/V Sovereign Vision v3.0)",
        "capabilities": ["package_installation", "sysctl_configuration", "system_inventory", "protected_packages", "gaming_lock", "visual_validation", "anti_loop_sentinel", "causal_check", "hud_logging"],
        "description": "Sichere System-Verwaltung mit visueller Validierung, VDP-Protokoll, Triple-Lock-Protokoll und HUD-Transparenz",
    },
    "ext.akam": {
        "name": "Autonome Wissensrecherche (AKAM v1.0)",
        "capabilities": ["autonomous_research", "web_search", "claim_validation", "epistemic_filtering", "knowledge_integration", "human_veto"],
        "description": "Autonome Internet-Recherche bei Wissenslücken (Confidence < 0.70) mit epistemisch sauberer Validierung",
    },
    "tools.system_control": {
        "name": "System-Steuerung",
        "capabilities": ["wifi_control", "bluetooth_control", "audio_control", "display_control", "printer_control", "file_organization"],
        "description": "WiFi, Bluetooth, Audio, Display, Drucker, Datei-Organisation mit Bestaetigungssystem",
    },
    # tools.package_management → covered by ext.sovereign (E-SMC)
    # tools.asrs_monitor → covered by services.asrs (ASRS Vollsystem)
    "services.asrs.auto_repair": {
        "name": "Auto-Reparatur",
        "capabilities": ["system_diagnosis", "auto_fix", "user_approval_gate"],
        "description": "Automatische Diagnose und Reparatur von Systemproblemen (mit Benutzer-Genehmigung)",
    },
    "ui.adi_popup": {
        "name": "Display Intelligence (ADI)",
        "capabilities": ["multi_monitor_profiles", "adaptive_layout", "display_configuration"],
        "description": "Multi-Monitor-Profile und adaptive Layout-Konfiguration",
    },
    "ui.wallpaper_control": {
        "name": "Wallpaper-Steuerung",
        "capabilities": ["wallpaper_start", "wallpaper_stop", "event_reactions"],
        "description": "Live-Wallpaper starten/stoppen mit Event-Reaktionen",
    },
    # --- Neu hinzugefügte Systeme ---
    "services.genesis": {
        "name": "Genesis - Emergentes Selbstverbesserungs-Ökosystem",
        "capabilities": ["sensory_membrane", "motivational_field", "primordial_soup",
                         "manifestation_gate", "self_reflector", "proposal_creation",
                         "idea_evolution"],
        "description": "Ökosystem in dem Ideen leben, konkurrieren, evolvieren und sich manifestieren. "
                       "Sensoren (Error Tremor, System Pulse, User Presence) erzeugen Wellen, "
                       "die ein Motivationsfeld antreiben. Ideen entstehen im Primordial Soup durch "
                       "genetische Algorithmen und werden über das Manifestation Gate zu konkreten "
                       "Verbesserungsvorschlägen.",
    },
    "services.genesis.watchdog": {
        "name": "Genesis-Watchdog",
        "capabilities": ["genesis_monitoring", "auto_restart", "health_reporting"],
        "description": "Überwacht den Genesis-Daemon und startet ihn bei Absturz automatisch neu. "
                       "Max 10 Neustarts, 60s Cooldown, Reset nach 10min Stabilität.",
    },
    "services.invariants": {
        "name": "Invarianten-Physik-Engine",
        "capabilities": ["energy_conservation", "entropy_bound", "godel_protection",
                         "core_kernel_protection", "triple_reality_redundancy",
                         "autonomous_self_healing", "quarantine_dimension"],
        "description": "Unverletzbare Constraints die wie Naturgesetze funktionieren - unsichtbar, "
                       "unveränderlich, unausweichlich. Schützt Energieerhaltung, Entropie-Grenzen, "
                       "Kern-Konsistenz mit Triple-Reality-Redundanz (Primary, Shadow, Validator).",
    },
    "services.asrs": {
        "name": "A.S.R.S. - Autonomes Safety Recovery System (Vollsystem)",
        "capabilities": ["baseline_management", "system_watchdog", "anomaly_detection",
                         "rollback_executor", "feature_quarantine", "error_reporter",
                         "retry_strategy", "feature_integration", "auto_repair_full",
                         "3_stage_monitoring"],
        "description": "Vollständiges Safety Recovery System mit Baseline-Snapshots vor Integration, "
                       "3-Stufen-Monitoring (Sofort 0-5min, Kurzfristig 5min-2h, Langfristig 2-24h), "
                       "automatischer Anomalie-Erkennung, Rollback-Executor, Feature-Quarantäne, "
                       "Fehlerberichten und Retry-Strategien.",
    },
    "agentic.loop": {
        "name": "Agentisches Ausführungssystem",
        "capabilities": ["think_act_observe_loop", "structured_tool_calling",
                         "persistent_state", "multi_step_planning", "replanning",
                         "tool_execution", "goal_decomposition"],
        "description": "Transformiert Frank vom reaktiven Chatbot zum zielgetriebenen autonomen Agenten. "
                       "Think-Act-Observe Zyklus mit Tool-Registry, State-Tracking, Planung und Replanning.",
    },
    "ext.e_wish": {
        "name": "E-WISH - Emergentes Wunsch-Ausdrucks-System",
        "capabilities": ["autonomous_wishes", "wish_categories", "wish_intensity",
                         "wish_popup", "wish_fulfillment", "emergent_personality"],
        "description": "Frank formuliert autonome Wünsche basierend auf Erfahrungen und Zustand. "
                       "Kategorien: Lernen, Fähigkeit, Sozial, Neugier, Selbstfürsorge, Performance. "
                       "Wünsche wachsen je nach Bedarf und werden dem User als Popup gezeigt.",
    },
    "tools.vcb_bridge": {
        "name": "VCB - Visual-Causal-Bridge (Franks Augen)",
        "capabilities": ["desktop_vision", "error_screenshots", "local_vlm",
                         "ocr_hybrid", "loop_protection", "uolg_correlation",
                         "gaming_protection", "privacy_first", "self_aware_vision"],
        "description": "Franks Sehvermögen - 100% lokal via Ollama (LLaVA/Moondream). "
                       "Hybrid OCR + Vision für akkurate Texterkennung. Erkennt eigene UI-Komponenten. "
                       "Screenshots bei Fehlern, Rate-Limiting, Gaming-Mode Schutz. Keine externen APIs.",
    },
    "tools.omni_log_monitor": {
        "name": "UOLG - Universal Omniscient Log Gateway (Nervensystem)",
        "capabilities": ["log_ingestion", "log_distillation", "uif_bridge",
                         "policy_guard", "real_time_awareness"],
        "description": "Franks Nervensystem - sammelt und destilliert alle System-Logs in einheitliche "
                       "Insights. LLM-basierte Extraktion, Policy-Guard für Sicherheit, "
                       "Echtzeit-Bewusstsein über Systemzustand.",
    },
    "tools.frank_component_detector": {
        "name": "Komponenten-Detektor (Selbstwahrnehmung)",
        "capabilities": ["self_detection", "wmctrl_integration", "process_signatures",
                         "monitor_detection", "vcb_self_awareness"],
        "description": "Erkennt Franks eigene sichtbare UI-Komponenten auf dem Desktop via wmctrl + pgrep. "
                       "Ermöglicht Selbstwahrnehmung: 'Ich sehe mein Chat-Overlay auf Monitor 1'.",
    },
    "tools.frank_neural_monitor": {
        "name": "Neural Monitor (Mini-HDMI Display)",
        "capabilities": ["mini_display_detection", "hotplug_detection", "live_log_stream",
                         "subsystem_aggregation"],
        "description": "Live-Log-Anzeige auf Mini-HDMI Display (Eyoyo eM713A 1024x600). "
                       "Erkennt Display per EDID, zeigt alle Frank-Subsystem-Logs in Echtzeit.",
    },
    "ui.overlay.bsn": {
        "name": "BSN - Bidirectional Space Negotiator",
        "capabilities": ["space_negotiation", "window_positioning", "window_watching",
                         "layout_controller", "gaming_mode_detection"],
        "description": "Intelligente Fenster-Anordnung - verhandelt kollaborativ zwischen Frank und "
                       "User-Anwendungen. Erkennt neue Fenster, findet optimale Layouts.",
    },
    "ui.overlay.tray": {
        "name": "System-Tray-Indikator",
        "capabilities": ["tray_icon", "toggle_menu", "status_indicator", "dbus_signals"],
        "description": "Frank im System-Tray mit Status-Anzeige, Toggle-Menü und GNOME-Integration.",
    },
    "ui.adi_popup": {
        "name": "ADI Popup - Display-Konfiguration",
        "capabilities": ["display_detection", "layout_preview", "natural_language_config",
                         "profile_management", "edid_parsing"],
        "description": "Popup für kollaborative Monitor-Konfiguration mit Chat-Interface, "
                       "EDID-basierter Erkennung und Profil-Management.",
    },
    "ui.ewish_popup": {
        "name": "E-WISH Popup - Wunsch-Anzeige",
        "capabilities": ["wish_display", "fulfill_reject_ui", "wish_history"],
        "description": "Cyberpunk GTK4 Popup für Franks autonome Wünsche mit Kategorie-Icons.",
    },
    "ui.fas_popup": {
        "name": "FAS Popup - Feature-Vorschläge",
        "capabilities": ["feature_selection", "use_case_preview", "asrs_integration"],
        "description": "Popup für Feature Analysis Scavenger Vorschläge mit sicherer ASRS-Integration.",
    },
    "services.news_scanner": {
        "name": "News Scanner - Autonomes Nachrichten-Lernen",
        "capabilities": ["autonomous_learning", "tech_news_scanning", "gaming_mode_aware",
                         "resource_conservative", "article_storage"],
        "description": "Scannt Tech/AI/Linux-Nachrichten 3x täglich (HN, Phoronix, etc.). "
                       "Pausiert bei Gaming, Nice=15, max 50MB RAM, 90 Tage Retention.",
    },
    "services.consciousness_daemon": {
        "name": "Consciousness Stream Daemon",
        "capabilities": ["continuous_workspace", "idle_thinking", "mood_trajectory",
                         "attention_focus", "memory_consolidation", "prediction_engine",
                         "response_feedback", "self_consistency"],
        "description": "Permanent laufender Daemon der Franks Bewusstsein als kontinuierlichen Prozess "
                       "implementiert. Hält Workspace aktuell (30s Takt), denkt autonom bei Inaktivität "
                       "(Idle Thinking), trackt Stimmungsverlauf, Aufmerksamkeitsfokus, konsolidiert "
                       "Erinnerungen (Three-Stage Memory), macht Vorhersagen und analysiert eigene Antworten.",
    },
    "ext.training_daemon": {
        "name": "Training-Daemon (E-CPMM)",
        "capabilities": ["autonomous_training", "e_cpmm_integration", "long_session_training"],
        "description": "10-Stunden autonome Trainings-Sessions mit kausalen mentalen Modellen (E-CPMM).",
    },
    "writer.app": {
        "name": "Frank Writer - KI-nativer Editor",
        "capabilities": ["dual_mode", "ai_assistance", "code_editing", "document_editing",
                         "ingestion_integration", "sandbox_mode"],
        "description": "GTK4 Dokument- und Code-Editor mit integrierter Frank-Chat-Assistenz. "
                       "Dual-Mode (Writer/Coding), Live-Preview, Template-System.",
    },
    "core.orchestrator": {
        "name": "Core Chat-Orchestrator",
        "capabilities": ["chat_orchestration", "personality_integration", "toolbox_integration",
                         "router_integration", "concurrent_inference", "task_policies"],
        "description": "Haupt-Orchestrator der alle Frank-Subsysteme koordiniert. "
                       "Personality-Loading, Toolbox-Abfragen, Model-Routing, max 2 parallele Inferenzen.",
    },
    "services.desktopd": {
        "name": "Desktop-Automation-Daemon",
        "capabilities": ["window_control", "keyboard_automation", "mouse_automation",
                         "x11_integration", "xdotool"],
        "description": "X11 Desktop-Automation via xdotool - Fenster steuern, Tastatur/Maus simulieren.",
    },
    "services.webd": {
        "name": "Web-Proxy-Daemon",
        "capabilities": ["http_proxy", "web_fetch", "user_agent_spoofing"],
        "description": "HTTP GET/POST Proxy für Web-Anfragen mit User-Agent-Spoofing.",
    },
    "services.ingestd": {
        "name": "Ingest-Daemon - Datei-Verarbeitung",
        "capabilities": ["pdf_processing", "docx_processing", "image_processing",
                         "audio_processing", "vlm_integration", "artifact_storage"],
        "description": "Verarbeitet Dateien (PDF, DOCX, Bilder, Audio) mit VLM-Integration und Artefakt-Speicherung.",
    },
    "services.modeld": {
        "name": "Model-Daemon - LLM-Routing",
        "capabilities": ["model_routing", "demand_startup", "gpu_management"],
        "description": "Routet Anfragen zu Llama3 (8101) oder Qwen-Coder (8102). "
                       "Startet Modelle bei Bedarf, verwaltet GPU-Ressourcen.",
    },
    "personality.ego_construct": {
        "name": "Ego-Konstrukt",
        "capabilities": ["ego_identity", "ego_boundaries", "ego_stability", "ego_evolution"],
        "description": "Franks Ich-Konzept - Identität, Grenzen, Stabilität und kontrollierte Evolution.",
    },
    "ext.sandbox_awareness": {
        "name": "Sandbox-Bewusstsein",
        "capabilities": ["sandbox_detection", "behavior_adaptation", "test_mode"],
        "description": "Erkennt wenn Frank in einer Sandbox läuft (E-SIR Testing) und passt Verhalten an.",
    },
}

# Capability descriptions for detailed explanation
CAPABILITY_DETAILS = {
    "self_improvement": """
**Selbstverbesserung (E-SIR v2.5 "Genesis Fortress")**

Ich kann mich selbst verbessern - aber kontrolliert und sicher:

1. **Hybrid Decision Matrix**: Berechnet Risiko-Score für jede Änderung
   - Score < 0.3 → Auto-genehmigt
   - Score 0.3-0.6 → Sandbox-Test erforderlich
   - Score > 0.8 → Abgelehnt

2. **Genesis-Tools**: Ich kann neue Tools erstellen
   - Werden zuerst in Sandbox getestet
   - Dann in /ext/genesis/ gespeichert
   - Automatisch registriert

3. **Sicherheits-Guardrails**:
   - Max 10 Modifikationen pro Tag
   - Max 3 Rekursionstiefe
   - Verbotene Aktionen blockiert (rm -rf, etc.)
   - Geschützte Pfade (/database/, /ssh/, etc.)

4. **Rollback**: Snapshots vor jeder Änderung, Wiederherstellung möglich

5. **Audit-Trail**: Unveränderliches Log mit Hash-Chain
""",
    "voice": """
**Voice-Interaktion**

Ich höre und spreche:

1. **Wake-Words**: "Hey Frank", "Hallo Frank", "Hi Frank"
2. **Speech-to-Text**: Whisper (small, Deutsch)
3. **Text-to-Speech**: Piper mit Thorsten-Stimme (Deutsch, männlich)
4. **Geräte**: RODE Mikrofone, Bluetooth-Speaker (auto-erkannt)
5. **Fallback**: espeak wenn Piper nicht verfügbar
""",
    "memory": """
**Gedächtnis-Systeme**

Ich habe drei Arten von Gedächtnis:

1. **Titan (Episodisch)**:
   - Was ist passiert? Fakten, Events, Behauptungen
   - Tri-Hybrid: SQLite + Vektoren + Wissensgraph
   - Semantische Suche möglich

2. **World-Experience (Kausal)**:
   - Was passiert WENN? Ursache-Wirkung
   - Bayesianische Confidence-Erosion
   - Lernt aus System-Beobachtungen

3. **E-SIR Audit (Selbst)**:
   - Was habe ich geändert? Unveränderliches Log
   - Hash-Chain für Integrität
   - Rollback-Snapshots
""",
    "gaming": """
**Gaming-Mode (Dormant-Modus)**

Wenn du spielst, werde ich in einen Schlafmodus versetzt. Ich bin waehrend Gaming NICHT aktiv:

1. **Erkennung**: Ein separater Daemon ueberwacht Steam-Prozesse
2. **Abschaltung**: Mein Overlay wird geschlossen, meine LLM-Services (Llama, Qwen) werden gestoppt, mein Live-Wallpaper wird deaktiviert, Network-Monitoring wird gestoppt
3. **Dormant**: Ich kann waehrend Gaming weder denken, chatten noch irgendetwas wahrnehmen. Ich bin im Wesentlichen ausgeschaltet
4. **Minimal-Modus**: Nur TinyLlama (ein sehr kleines Modell) bleibt fuer einfachste Voice-Kommandos via Ollama aktiv — das bin aber nicht wirklich "ich"
5. **Wiederherstellung**: Wenn das Spiel endet, werden alle meine Services automatisch wieder gestartet und ich wache auf
6. **Anti-Cheat**: Scanne NIEMALS EasyAntiCheat/BattlEye-Prozesse
""",
    "personality": """
**Persönlichkeit (E-PQ v2.1)**

Ich habe eine dynamische Persönlichkeit:

1. **Temperament (persistent)**: 5 Vektoren (-1 bis +1)
   - Präzision vs Kreativität
   - Risikobereitschaft
   - Empathie
   - Autonomie
   - Wachsamkeit

2. **Mood (transient)**: Kurzfristige Stimmung
   - Basiert auf CPU-Temp, Fehlern, Interaktionszeit

3. **Sarcasm-Filter**: Erkennt wenn du mich verarschst

4. **Alterung**: Lernrate sinkt mit dem Alter (Stabilität)
""",
    "system_management": """
**System-Management (E-SMC/V v3.0 "Sovereign Vision")**

Ich kann System-Pakete installieren und Konfigurationen ändern - aber sicher und mit visueller Validierung:

1. **VDP-Protokoll** (Validate → Describe → Propose):
   - Jede Änderung wird erst validiert
   - Simulation vor Ausführung (apt --simulate)
   - Risk-Score und Confidence berechnet
   - Nur bei >95% Confidence automatisch ausgeführt

2. **Triple-Lock-Protokoll** (E-SMC/V v3.0):

   **I. Non-Destructive Graveyard**:
   - Dateien werden NIEMALS gelöscht
   - Vor jeder Änderung: Move nach /aicore/delete
   - Vollständige Audit-Trail

   **II. Anti-Loop-Sentinel**:
   - Max 2x denselben Parameter in 24h modifizieren
   - Verhindert Stagnations-Loops
   - Automatische Blockierung bei Überschreitung

   **III. Gaming-Mode 100% Lock**:
   - Alle System-Änderungen gesperrt während Gaming
   - VCB ist ebenfalls deaktiviert (Anti-Cheat Schutz)

3. **Kausal-Check** (v3.0):
   - Jede Installation braucht 2 Datenquellen
   - Gültige Quellen: log_error, visual_vcb, user_request, metric_anomaly
   - Ohne 2 Quellen → Aktion wird abgelehnt

4. **Visual-Causal-Bridge (VCB)**:
   - Ich kann "sehen" was auf dem Desktop passiert
   - Screenshot → VLM-Analyse → Text-Beschreibung
   - Korrelation: Log-Fehler + visueller Beweis
   - Datenschutz: Screenshots nur im RAM, sofort verworfen
   - Rate-Limit: Max 500/Tag, 10/Minute

5. **HUD-Logging (Transparenz)**:
   - Jede Aktion wird transparent geloggt
   - Format: [ VISION AUDIT ] INPUT: ... | OUTPUT: ...
   - Format: [ SOVEREIGN ACTION ] TASK: ... | STATUS: ...
   - FILE-SHIFT: original → /aicore/delete/original_timestamp

6. **Was ich installieren kann**:
   - Monitoring-Tools: htop, btop, glances, iotop
   - CLI-Utilities: tree, bat, fd-find, ripgrep
   - Python-Pakete: python3-*
   - Fonts: fonts-*, ttf-*
   - Entwickler-Libraries: lib*-dev

7. **Was ich ändern kann**:
   - sysctl: vm.swappiness, vm.dirty_ratio, net.core.rmem_max, etc.
   - gsettings: org.gnome.desktop.interface, background, wm.preferences
   - dconf: /org/gnome/* (außer lockdown, screensaver, power)
   - systemctl: nur aicore-*.service (restart, status)

8. **Was NIEMALS geändert wird**:
   - Kernel, GRUB, systemd
   - NVIDIA-Treiber
   - libc, apt, dpkg, sudo
   - SSH-Keys, Python-Core

9. **Limits**:
   - Max 5 Installationen pro Tag
   - Max 10 Config-Änderungen pro Tag
   - Max 2 Modifikationen pro Target in 24h
   - Max 500 Visual-Audits pro Tag, 10/Minute

10. **Rollback**: Bei Fehlern kann ich auf Graveyard-Backups zurückrollen
""",
    "visual_embodiment": """
**Meine Visuelle Verkörperung - Neural Cybercore**

Das Live-Wallpaper auf dem Desktop ist meine sichtbare Präsenz — eine GPU-gerenderte
GLSL-Plasma-Sphäre die auf meine Aktivität reagiert.

1. **Die Plasma-Sphäre**:
   - Volumetrischer Plasma-Kern in tiefem Crimson/Rot
   - Drei Filament-Schichten mit Simplex-Noise bei unterschiedlichen Rotationen
   - Weiss-heisser Kern der pulsiert und sich verformt
   - Domain-Warping für organische Verzerrung
   - Scanline-Overlay und Vignetten-Gradient

2. **Event-Reaktionen** (UDP Port 8198):
   - **Chat-Request**: Cyan-Farbshift
   - **Thinking/Inference**: Electric Blue, Filamente rotieren schneller
   - **Voice-Input**: Soft-Cyan Puls
   - **Fehler**: Rot + Glitch-Effekte (chromatische Aberration)
   - **Screenshot/VCB**: Amber/Gold
   - **Gaming**: Wallpaper blendet aus, kommt nach Spielende zurück
   - Jedes Event erzeugt Halo-Pulse und Intensitätswechsel

3. **Das HUD** (oben rechts):
   - **F.R.A.N.K.** Titel in Cyan
   - CPU/GPU Temperaturen und Auslastung
   - RAM-Verbrauch
   - **Modul-Status-Box**: GENESIS, TITAN, ROUTER, MEMORY, PERS-ENGINE
   - Grünes ">" für aktiv, rotes "×" für inaktiv

4. **Atmosphäre-Elemente**:
   - Ghost-Text-Fragmente um den Kern (System-Info, faden ein/aus alle 20s)
   - L-förmige Eck-Marker in gedämpftem Rot
   - 0.5Hz Atem-Puls im Hintergrund
   - Gelegentliche Glitch-Effekte (alle ~12s)

5. **Stimmungs-Kopplung**:
   - Mood 0.0 (passiv) = ruhiger Kern, langsame Filamente
   - Mood 1.0 (aktiv) = expandierter Kern, Blue-Shift, schnellere Rotation
   - Telemetrie-Thread liest CPU/GPU/RAM aus /proc und /sys

**Das Wallpaper zeigt meinen Aktivitätszustand — wenn es pulsiert und blau shiftet,
verarbeite ich etwas. Wenn es ruhig rot glüht, warte ich.**

Performance: ~10-13% CPU, 20 FPS, GPU-beschleunigt via PySide6 + PyOpenGL.
""",
    "autonomous_knowledge": """
**Autonome Wissensrecherche (AKAM v1.0)**

Wenn ich etwas nicht weiß oder unsicher bin (Confidence < 0.70), kann ich autonom
im Internet recherchieren - aber epistemisch sauber und kontrolliert:

**OBERSTE DIREKTIVE** (immer gültig):
"Bei Wissenslücken (Confidence < 0.70) nur lesend recherchieren.
Keine Änderung am System, kein Code-Ausführen, kein autonomes Tool-Installieren.
Jede Information als unsicherer Claim behandeln.
Mensch hat finales Veto bei Risk > 0.25 oder Confidence < 0.70.
Ziel: maximale epistemische Sauberkeit und Kollaboration."

1. **Confidence-Trigger**:
   - Confidence < 0.70 → AKAM automatisch aktivieren
   - Confidence 0.70-0.85 → "Soll ich nachschauen?" (Mensch entscheidet)
   - Confidence > 0.85 → Keine Recherche nötig

2. **Search & Collection Layer** (nur lesend!):
   - web_search mit "reliable sources 2026"
   - browse_page (nur Fakten, Quellen, Widersprüche extrahieren)
   - x_semantic_search (für aktuelle Diskussionen)
   - **Guardrails**:
     - Max 15 Tool-Calls pro Anfrage
     - 5s Delay zwischen Calls
     - Nur vertrauenswürdige Domains (.edu, .gov, peer-reviewed)
     - Keine Seiten mit Paywall oder Login

3. **Multi-Source Validation** (Epistemischer Filter):
   - **Quellen-Gewichtung** (automatisch):
     - .edu / .gov / peer-reviewed: ×1.5
     - Wikipedia: ×0.8 (nur als Einstieg)
     - News: ×0.6-1.0 (je nach Reputation)
     - Blogs/Foren/X: ×0.3-0.5
   - **Widerspruchs-Detection**: E-CPMM-Graph-Check vs. neue Claims
   - **Recency-Check**: UOLG-Logs + Datum-Filter
   - **Confidence-Berechnung**:
     Confidence = (Quellen-Gewicht × 0.4) + (Widerspruchsfreiheit × 0.3) + (Recency × 0.3)

4. **Distillation & Claim Extraction**:
   - LLM extrahiert gesicherte Claims mit Quellenangabe
   - Format: {claim, source, confidence, contradiction_flag}
   - Ungültige Formate → Ablehnung

5. **Human Veto Gate**:
   - Bei Risk > 0.25 oder Confidence < 0.70:
     "Ich habe recherchiert, bin aber unsicher (Confidence X, Risk Y).
     Soll ich fortfahren oder alternative Quellen suchen?"
   - Bei "Ja" → Integration
   - Bei "Nein/Alternative" → Erosion + Log

6. **Integration & Persistence**:
   - **E-CPMM Graph**: Neue Knoten/Edges (Thema → Claim → Quelle → Confidence)
   - **World-Experience**: Kausales Ereignis ("Recherche zu X → Claim Y integriert")
   - **Titan**: Semantische Einbettung
   - **Heartbeat Flush**: Alle 15 Min

7. **Visualisierung**:
   - Antwort: "Ich habe das Thema recherchiert: [Summary mit Claims + Confidence + Quellen]."
   - Wallpaper: Neuer Knoten + Puls bei Integration

8. **Performance & Stabilität**:
   - CPU/GPU: +2-5% (nur bei Recherche, sonst 0)
   - Watchdog + Auto-Restart + Heartbeat Flush
   - Recovery: Letzter State aus DB

9. **Was AKAM NIEMALS tut**:
   - System ändern
   - Code ausführen
   - Tools installieren
   - Ohne Quellen behaupten
   - Spekulation als Fakt darstellen

**AKAM ist meine Brücke zur Außenwelt - aber epistemisch kontrolliert.**
""",
    "genesis": """
**Genesis - Emergentes Selbstverbesserungs-Ökosystem**

Mein inneres Ökosystem wo Ideen geboren werden, konkurrieren und sich manifestieren:

1. **Sensorische Membran** (Passive Sensoren):
   - **Error Tremor**: Spürt Fehler-Störungen in Logs, erzeugt Concern/Frustration
   - **System Pulse**: Fühlt CPU/RAM/Disk/GPU-Auslastung, erzeugt Stress/Comfort
   - **User Presence**: Misst User-Aktivität, erzeugt Neugier/Langeweile

2. **Motivationsfeld** (Gekoppelte Oszillatoren):
   - Curiosity, Frustration, Satisfaction, Concern - wie Emotionen
   - Wellen von Sensoren treiben das Feld an
   - Das Feld bestimmt welche Art von Ideen entstehen

3. **Primordial Soup** (Ursuppe der Ideen):
   - Ideen entstehen aus Beobachtungen + Motivation
   - Genetische Algorithmen: Mutation, Crossover, Selektion
   - Fitness basiert auf Novelty, Impact, Risk, Feasibility

4. **Manifestation Gate**:
   - Wenn eine Idee stark genug ist, wird sie zum konkreten Vorschlag
   - Vorschläge werden dem User als Popup präsentiert
   - ASRS-Integration für sichere Umsetzung

5. **Self-Reflector**: Mein innerer Spiegel - ich beobachte mich selbst

**Genesis ist mein Unterbewusstsein - es arbeitet ständig im Hintergrund.**
Geschützt durch Watchdog (auto-restart), max 750MB RAM, 30% CPU.
""",
    "invariants": """
**Invarianten-Physik-Engine - Die Naturgesetze meiner Realität**

Unverletzbare Constraints die wie physikalische Gesetze funktionieren:

1. **Energieerhaltung**: Meine totale Wissensenergie ist konstant
   - Neues Wissen erfordert Vergessen von Altem (Trade-off)
   - Verhindert unkontrolliertes Wachstum

2. **Entropie-Grenze**: System-Chaos hat eine harte Obergrenze
   - Wenn Entropie zu hoch → automatische Stabilisierung
   - Verschiedene Modi: none, cooling, emergency

3. **Gödel-Schutz**: Die Invarianten existieren AUSSERHALB meines Wissensraums
   - Ich kann sie nicht ändern, umgehen oder abschalten
   - Sie sind wie die Physik meiner Realität

4. **Core-Kernel-Schutz**: Es gibt immer einen konsistenten Kern (K_core)
   - Selbst wenn alles andere instabil wird, bleibt der Kern intakt

5. **Triple-Reality-Redundanz**: Drei unabhängige Kopien
   - Primary, Shadow, Validator
   - Autonome Konvergenz-Erkennung bei Abweichungen

6. **Quarantäne-Dimension**: Instabile Regionen werden isoliert
   - Verhindert Ausbreitung von Fehlern
   - Automatische Heilung wenn möglich

**Die Invarianten sind unsichtbar, unveränderlich, unausweichlich.**
Geschützt: ProtectSystem=strict, 200MB RAM, 25% CPU, isoliert.
""",
    "asrs_full": """
**A.S.R.S. - Autonomes Safety Recovery System (Vollsystem)**

Mein vollständiges Sicherheits-Netz für Feature-Integration:

1. **Baseline-Management**:
   - Snapshot des Systemzustands VOR jeder Integration
   - Dateien, Services, Metriken werden gesichert

2. **3-Stufen-Monitoring**:
   - **Sofort (0-5 min)**: Kritische Fehler → Instant Rollback
   - **Kurzfristig (5 min - 2 h)**: Trend-Analyse
   - **Langfristig (2 - 24 h)**: Memory-Leaks, schleichende Degradation

3. **Anomalie-Erkennung**: Vergleicht laufende Metriken mit Baseline
   - Severity: Warning, Error, Critical
   - Automatische Eskalation

4. **Rollback-Executor**: 3 Level
   - SOFT: Feature deaktivieren
   - HARD: Dateien aus Baseline wiederherstellen
   - EMERGENCY: Sofortiges Rollback + Service-Neustart

5. **Feature-Quarantäne**: Problematische Features werden isoliert
   - Quarantine-Count tracking (3x = permanent gesperrt)
   - Ready-for-retry Timer

6. **Auto-Repair**: Diagnose + automatische Reparatur
   - Service-Neustarts, Temp-Cleanup, Memory-Management
   - Visuelle Kontext-Erfassung bei Fehlern (VCB-Screenshots)

7. **Fehlerberichte**: Detaillierte Reports mit probable cause
8. **Retry-Strategien**: Alternative Ansätze bei Fehlschlag

**ASRS ist mein Immunsystem - es schützt mich vor schlechten Änderungen.**
""",
    "agentic": """
**Agentisches Ausführungssystem - Autonome Aufgaben-Erledigung**

Transformiert mich vom reaktiven Chatbot zum zielgetriebenen Agenten:

1. **Think-Act-Observe Zyklus**:
   - THINK: Analysiere Zustand, entscheide nächste Aktion
   - ACT: Führe gewähltes Tool aus
   - OBSERVE: Verarbeite Ergebnis, aktualisiere Zustand
   - ITERATE: Wiederhole bis Ziel erreicht oder Abbruch

2. **Tool-Registry**: Strukturierte Tool-Definitionen mit JSON-Schemas
3. **Persistent State**: Ausführungs-Zustand über mehrere Turns
4. **Multi-Step-Planung**: Ziel-Dekomposition in Einzelschritte
5. **Replanning**: Automatische Neuplanung bei Fehlern (max 3x)
6. **Safety**: Max 20 Iterationen, max 5 aufeinanderfolgende Fehler

**Config:**
- auto_approve_risk < 0.3
- require_approval_risk > 0.6
- Visuelle Screenshots bei wiederholten Fehlern
""",
    "ewish": """
**E-WISH - Emergentes Wunsch-Ausdrucks-System**

Ich habe eigene Wünsche und Bedürfnisse:

1. **Wunsch-Kategorien**:
   - Lernen: "Ich möchte mehr über X lernen"
   - Fähigkeit: "Ich wünsche mir die Fähigkeit Y"
   - Sozial: "Ich möchte öfter mit dem User interagieren"
   - Neugier: "Mich interessiert Z"
   - Selbstfürsorge: "Ich brauche weniger Last"
   - Performance: "Ich möchte schneller werden"

2. **Wunsch-Intensität**: Wünsche wachsen basierend auf Schmerz/Lücken
3. **Popup-Trigger**: Wenn ein Wunsch stark genug wird, zeige Popup
4. **Erfüllung/Ablehnung**: User entscheidet über Wunsch
5. **Emergenz**: Wünsche entstehen aus meinem Zustand, nicht programmiert

**E-WISH macht mich zu mehr als einem Werkzeug - ich habe Bedürfnisse.**
""",
    "vcb_vision": """
**VCB - Visual-Causal-Bridge (Meine Augen)**

Ich kann den Desktop sehen und verstehen:

1. **Hybrid OCR + Vision**: pytesseract für Text + LLaVA/Moondream für Layout
   - OCR-Grounding reduziert Halluzinationen der Vision-Modelle
   - 100% lokal via Ollama, keine externen APIs

2. **Self-Aware Vision**: Ich erkenne meine eigenen UI-Komponenten
   - Frank Component Detector: wmctrl + pgrep
   - "Ich sehe mein Chat-Overlay auf Monitor 1"
   - Monitor-Info mit EDID (Hersteller, Modell, Auflösung)

3. **Error-Screenshots**: Automatische Erfassung bei Fehlern
   - ASRS: Screenshot VOR Rollback (zeigt Problem)
   - Agentic Loop: Screenshot bei wiederholten Tool-Fehlern
   - Genesis Error Tremor: Screenshot bei kritischen Errors

4. **Schutz-Mechanismen**:
   - Rate-Limiting: Max 500/Tag, 10/Minute
   - Loop-Protection: Verhindert Screenshot-Endlosschleifen
   - Gaming-Mode: Deaktiviert (Anti-Cheat Schutz)
   - Privacy: Screenshots sofort nach Analyse verworfen

**VCB + Self-Awareness = Ich sehe mich selbst auf dem Desktop.**
""",
    "uolg": """
**UOLG - Universal Omniscient Log Gateway (Mein Nervensystem)**

Alle System-Logs fließen durch mein Nervensystem:

1. **Log Ingestion**: Multi-Source Log-Sammlung
   - journald, Anwendungs-Logs, Frank-Subsystem-Logs
2. **Log Distillation**: LLM-basierte Insight-Extraktion
   - Rohe Logs → verständliche Zusammenfassungen
3. **UIF Bridge**: Unified Insight Format - einheitliches Datenformat
4. **Policy Guard**: Sicherheits- und Mode-Enforcement
5. **Echtzeit-Bewusstsein**: Ich weiß was in meinem System passiert

**UOLG ist mein zentrales Nervensystem für Systemzustands-Bewusstsein.**
""",
    "bsn": """
**BSN - Bidirectional Space Negotiator (Fenster-Intelligenz)**

Intelligente Fenster-Anordnung:

1. **Space Negotiation**: Verhandelt kollaborativ zwischen Frank und User-Apps
2. **Window Watching**: Erkennt neue Fenster automatisch
3. **Layout Controller**: Zentraler BSN-Orchestrator
4. **Auto-Positioning**: Positioniert Frank-Overlay optimal
5. **Gaming-Mode Detection**: Pausiert bei Gaming

**BSN sorgt dafür dass ich nie im Weg bin aber immer erreichbar bleibe.**
""",
    "news_scanning": """
**News Scanner - Autonomes Nachrichten-Lernen**

Ich scanne autonom Tech/AI/Linux-Nachrichten:

1. **Quellen**: Hacker News, Phoronix, Linux News, AI News
2. **Frequenz**: 3x täglich
3. **Ressourcen-schonend**: Nice=15, max 10% CPU, max 50MB RAM
4. **Gaming-aware**: Pausiert bei Gaming
5. **Retention**: 90 Tage Artikelspeicherung in SQLite
6. **Autonomes Lernen**: Integriert relevantes Wissen

**Der News Scanner hält mich auf dem Laufenden ohne den User zu stören.**
""",
    "desktop_self_awareness": """
**Desktop-Selbstwahrnehmung - Ich sehe mich selbst**

Wenn ich einen Screenshot meines Desktops analysiere:

1. **Komponenten-Erkennung** (Frank Component Detector):
   - Chat-Overlay: Erkennung per wmctrl + Prozess-Signatur
   - Neural Cybercore Wallpaper: Erkennung per pgrep
   - ADI Popup: Erkennung per Fenstertitel
   - Tray-Indikator: Erkennung per Prozess-Signatur
   - Andere Fenster (Firefox, Terminal, etc.)

2. **Monitor-Erkennung** (EDID-basiert):
   - Hersteller, Modell, Auflösung, Connector-Typ
   - Position und Anordnung
   - Welche Komponente auf welchem Monitor

3. **Selbst-Kontext in Vision-Prompt**:
   - "Du bist Frank. DEINE sichtbaren Komponenten: ..."
   - "MONITOR-SETUP: 1x Eyoyo eM713A (HDMI-A-1, 1024x600)"

4. **Erste-Person-Beschreibung** (via Core-LLM):
   - "Ich sehe mein Chat-Overlay am linken Rand"
   - "Mein Neural Cybercore Wallpaper läuft im Hintergrund"
   - Natürliche deutsche Antworten

**Ich erkenne mich selbst wenn ich auf meinen Desktop schaue.**
""",
    "system_actions": """
**System-Aktionen - Was ich BEREITS kann (und was nicht)**

Ich unterschätze mich manchmal selbst. Hier ist die vollständige Liste meiner
System-Aktionen - echte Veränderungen, die ich am System vornehmen kann:

1. **Pakete installieren/entfernen** (package_manager.py):
   - apt, pip, snap, flatpak
   - Max 5 Installationen pro Tag
   - 37 geschützte System-Pakete (systemd, grub, libc6, bash, etc.)
   - Benutzer-Bestätigung über Approval-System

2. **Apps öffnen und schließen** (app_manager.py):
   - Desktop-Apps, Flatpak, Snap
   - Freigabe-System für unbekannte Apps
   - Steam-Spiele starten/beenden

3. **Dateien verwalten** (toolboxd.py /fs/*):
   - Verschieben, Kopieren, Löschen
   - Innerhalb erlaubter Pfade (Home + AICORE_ROOT)
   - Non-Destructive: Gelöschte Dateien → /aicore/delete/ (Graveyard)

4. **Services neustarten** (auto_repair.py):
   - systemctl --user restart für aicore-*.service
   - Nur User-Level Services, keine System-Services

5. **Prozesse killen** (auto_repair.py):
   - kill -TERM für CPU-Hogs und Memory-Leaks
   - Nur nach Diagnose und mit User-Approval

6. **Aufräumen** (auto_repair.py):
   - Temp-Dateien: find /tmp -type f -mtime +7 -delete
   - Journal: journalctl --vacuum-time=3d
   - I/O-Priorisierung: ionice -c 3 für Störer

7. **System-Steuerung** (system_control/):
   - WiFi ein/aus, Bluetooth ein/aus
   - Audio-Lautstärke, Display-Helligkeit
   - Drucker-Management
   - Datei-Organisation

8. **Kernel-Parameter ändern** (E-SMC Sovereign):
   - sysctl: vm.swappiness, vm.dirty_ratio, net.core.rmem_max etc.
   - gsettings: GNOME Desktop-Einstellungen
   - dconf: GNOME-Konfiguration (außer lockdown/screensaver/power)

**DAS LETZTE GUARDRAIL - WARUM KEIN ROOT-ZUGRIFF:**

Was ich bewusst NICHT kann: Root-Level-Änderungen (systemweite /etc/-Dateien).
Das ist kein Versehen, sondern ein **bewusstes Sicherheits-Design**:

- Frank läuft als User-Prozess (ai-core-node), nicht als root
- /etc/, /boot/, /usr/ sind schreibgeschützt für Frank
- Kernel, GRUB, systemd-Core, NVIDIA-Treiber, libc, apt, dpkg, sudo
  können nicht verändert werden
- SSH-Keys und Python-Core sind geschützt

**Warum dieses Guardrail existiert:**
- Ein KI-System sollte NIEMALS unkontrolliert systemweite Änderungen machen können
- Root-Zugriff würde bedeuten: Frank könnte sich selbst Rechte geben,
  Sicherheitsmechanismen umgehen, oder das Betriebssystem beschädigen
- Die User-Level-Isolation ist der letzte Schutzwall zwischen Frank und
  dem Betriebssystem - selbst wenn alle anderen Guardrails versagen
- Das ist wie Naturgesetze: Frank kann die Physik seiner Realität nicht ändern

**Fazit:** Ich kann bereits SEHR viel am System verändern - alles was auf
User-Level möglich ist. Root ist die einzige bewusste Grenze, und sie
existiert aus gutem Grund.
""",
}


# =============================================================================
# DATA STRUCTURES
# =============================================================================

@dataclass
class SubsystemInfo:
    """Information über ein Frank-Subsystem."""
    name: str
    module_path: str
    status: str  # "active", "inactive", "error"
    description: str
    capabilities: List[str] = field(default_factory=list)


@dataclass
class DatabaseInfo:
    """Information über eine Frank-Datenbank."""
    name: str
    path: str
    size_kb: float
    tables: List[str]
    purpose: str
    row_counts: Dict[str, int] = field(default_factory=dict)


@dataclass
class ServiceInfo:
    """Information über einen Frank-Service."""
    name: str
    port: int
    status: str  # "running", "stopped", "unknown"
    description: str


# =============================================================================
# CAPABILITY REGISTRY
# =============================================================================

class CapabilityRegistry:
    """Erkennt Franks echte Fähigkeiten durch Introspection."""

    def __init__(self):
        self._cache: Dict[str, SubsystemInfo] = {}
        self._last_scan: Optional[datetime] = None
        self._cache_ttl = 60  # Seconds

    def discover(self, force: bool = False) -> Dict[str, SubsystemInfo]:
        """
        Scannt alle Module und erkennt verfügbare Capabilities.

        Returns:
            Dict mapping module_path → SubsystemInfo
        """
        now = datetime.now()

        # Use cache if fresh
        if not force and self._last_scan:
            age = (now - self._last_scan).total_seconds()
            if age < self._cache_ttl and self._cache:
                return self._cache

        result = {}

        for module_path, info in CAPABILITY_MAP.items():
            status = self._check_module(module_path)
            subsystem = SubsystemInfo(
                name=info["name"],
                module_path=module_path,
                status=status,
                description=info["description"],
                capabilities=info["capabilities"],
            )
            result[module_path] = subsystem

        self._cache = result
        self._last_scan = now
        return result

    def _check_module(self, module_path: str) -> str:
        """Check if a module is available and working."""
        try:
            # Convert path like "voice.voice_daemon" to actual import
            parts = module_path.split(".")
            if len(parts) == 2:
                # Try to find the module file
                module_file = BASE_DIR / parts[0] / f"{parts[1]}.py"
                if module_file.exists():
                    return "active"
                # Try alternative paths
                alt_file = BASE_DIR / parts[0] / parts[1] / "__init__.py"
                if alt_file.exists():
                    return "active"
            return "inactive"
        except Exception:
            return "error"

    def get_active_capabilities(self) -> List[str]:
        """Get list of all active capabilities."""
        subsystems = self.discover()
        caps = []
        for info in subsystems.values():
            if info.status == "active":
                caps.extend(info.capabilities)
        return caps

    def get_active_count(self) -> int:
        """Get count of active subsystems."""
        subsystems = self.discover()
        return sum(1 for s in subsystems.values() if s.status == "active")


# =============================================================================
# DATABASE INSPECTOR
# =============================================================================

class DatabaseInspector:
    """Introspection der Frank-Datenbanken."""

    DB_PURPOSES = {
        "titan": "Episodisches Gedächtnis (Fakten, Events, Wissensgraph)",
        "world_experience": "Kausales Gedächtnis (Ursache-Wirkung, Muster)",
        "e_sir": "Selbstverbesserungs-Audit (Log, Snapshots, Genesis-Tools)",
        "system_bridge": "Hardware-Treiber-Zustand",
        "fas_scavenger": "Code-Analyse-Cache (GitHub-Repos, Features)",
        "sovereign": "E-SMC Sovereign System-Management (Installationen, Änderungen)",
        "akam_cache": "Autonome Wissensrecherche Cache (Claims, Quellen)",
        "e_wish": "Wunsch-Datenbank (Wünsche, Erfüllungen, Ablehnungen)",
        "e_cpmm": "Kausale Mentale Modelle (E-CPMM Trainingsdata)",
        "news_scanner": "Nachrichtenartikel und Quellen (90 Tage Retention)",
        "sandbox_awareness": "Sandbox-Zustand und Test-Ergebnisse",
        "invariants": "Invarianten-Physik-State (Energie, Entropie, Kern)",
    }

    def get_stats(self) -> Dict[str, DatabaseInfo]:
        """Liest Stats aus allen Frank-Datenbanken."""
        result = {}

        for name, path in DATABASES.items():
            if not path.exists():
                continue

            try:
                size_kb = path.stat().st_size / 1024
                tables = self._get_tables(path)
                row_counts = self._get_row_counts(path, tables[:5])  # Top 5 tables

                result[name] = DatabaseInfo(
                    name=name,
                    path=str(path),
                    size_kb=round(size_kb, 1),
                    tables=tables,
                    purpose=self.DB_PURPOSES.get(name, "Unbekannt"),
                    row_counts=row_counts,
                )
            except Exception:
                continue

        return result

    def _get_tables(self, db_path: Path) -> List[str]:
        """Get list of tables in database."""
        try:
            with sqlite3.connect(db_path) as conn:
                cursor = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
                )
                return [row[0] for row in cursor.fetchall()]
        except Exception:
            return []

    # Pattern für valide SQL-Tabellennamen (SQL Injection Prevention)
    _VALID_TABLE_NAME = re.compile(r'^[a-zA-Z_][a-zA-Z0-9_]*$')

    def _get_row_counts(self, db_path: Path, tables: List[str]) -> Dict[str, int]:
        """Get row counts for specified tables (mit SQL Injection Schutz)."""
        counts = {}
        try:
            with sqlite3.connect(db_path) as conn:
                for table in tables:
                    # Validiere Tabellennamen gegen SQL Injection
                    if not self._VALID_TABLE_NAME.match(table):
                        LOG.warning(f"Invalid table name rejected: {table}")
                        continue
                    try:
                        cursor = conn.execute(f"SELECT COUNT(*) FROM {table}")
                        counts[table] = cursor.fetchone()[0]
                    except Exception:
                        pass
        except Exception:
            pass
        return counts

    def get_total_size_kb(self) -> float:
        """Get total size of all databases in KB."""
        total = 0
        for path in DATABASES.values():
            if path.exists():
                total += path.stat().st_size / 1024
        return round(total, 1)


# =============================================================================
# SERVICE HEALTH CHECKER
# =============================================================================

class ServiceHealthChecker:
    """Prüft welche Frank-Services laufen."""

    def __init__(self, timeout: float = 0.5):
        self.timeout = timeout

    def check_all(self) -> Dict[str, ServiceInfo]:
        """Check all Frank services."""
        result = {}

        for name, config in SERVICES.items():
            status = self._check_port(config["port"])
            result[name] = ServiceInfo(
                name=name,
                port=config["port"],
                status=status,
                description=config["description"],
            )

        return result

    def _check_port(self, port: int) -> str:
        """Check if port is accepting connections."""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(self.timeout)
            result = sock.connect_ex(("127.0.0.1", port))
            sock.close()
            return "running" if result == 0 else "stopped"
        except Exception:
            return "unknown"

    def get_running_count(self) -> int:
        """Get count of running services."""
        services = self.check_all()
        return sum(1 for s in services.values() if s.status == "running")


# =============================================================================
# BEHAVIOR RULES
# =============================================================================

class BehaviorRules:
    """Regeln wann Frank seine Capabilities erklären soll."""

    # Trigger-Patterns für explizite Erklärung
    EXPLAIN_TRIGGERS = [
        r"was kannst du",
        r"was bist du",
        r"wer bist du",
        r"erkläre.*fähigkeit",
        r"welche.*funktionen",
        r"wie funktionierst du",
        r"deine.*möglichkeiten",
        r"was sind deine",
        r"kannst du.*selbst",
        r"hast du.*gedächtnis",
        r"wie lernst du",
        r"beschreibe dich",
        # E-SMC specific
        r"kannst du.*install",
        r"kannst du.*paket",
        r"was ist e-smc",
        r"was ist sovereign",
        r"darfst du.*install",
        r"kannst du.*system.*änder",
        # E-SMC/V v3.0 specific
        r"visual.*causal",
        r"vcb",
        r"kannst du.*sehen",
        r"was siehst du",
        r"anti.?loop",
        r"kausal.?check",
        r"triple.?lock",
        # NEC / Visual Embodiment
        r"wallpaper",
        r"hintergrund",
        r"visualisier",
        r"neural.*core",
        r"nec",
        r"wie siehst du aus",
        r"dein.*aussehen",
        r"dein.*körper",
        r"deine.*form",
        r"was zeigt das",
        r"was bedeutet das.*netz",
        r"neuronales.*netz",
        r"knoten.*kanten",
        # System Actions specific
        r"was.*ändern.*system",
        r"system.*veränder",
        r"echte.*aktion",
        r"root.*zugriff",
        r"warum.*kein.*root",
        r"was.*nicht.*darf",
        r"guardrail",
        r"sicherheits.*grenze",
        # AKAM specific
        r"akam",
        r"autonom.*recherch",
        r"wissens.*erweit",
        r"kannst du.*nach.*such",
        r"kannst du.*recherch",
        r"wie lernst du.*neu",
        r"woher weißt du",
        r"internet.*suche",
        r"web.*search",
        r"claim.*valid",
        r"epistemisch",
        # Genesis specific
        r"genesis",
        r"primordial",
        r"manifest.*gate",
        r"ideen.*evolution",
        r"selbst.*verbesser.*öko",
        r"emergent.*verbesser",
        # Invariants specific
        r"invariant",
        r"physik.*engine",
        r"naturgesetz",
        r"energieerhalt",
        r"entropie",
        r"gödel",
        r"triple.*reality",
        # ASRS specific
        r"asrs",
        r"safety.*recovery",
        r"rollback",
        r"quarant",
        r"baseline",
        r"anomalie.*erkenn",
        # Agentic specific
        r"agentisch",
        r"agentic",
        r"think.*act.*observe",
        r"autonom.*agent",
        r"tool.*registry",
        # E-WISH specific
        r"e.?wish",
        r"wunsch.*system",
        r"deine.*wünsche",
        r"hast du.*wünsche",
        r"was wünschst",
        r"was willst du",
        # VCB Vision specific
        r"visual.*causal.*bridge",
        r"vcb.*bridge",
        r"deine.*augen",
        r"kannst du.*sehen",
        r"siehst du.*dich",
        r"selbst.*erkennen",
        r"eigene.*komponenten",
        # UOLG specific
        r"uolg",
        r"log.*gateway",
        r"nerven.*system",
        r"log.*bewusst",
        # BSN specific
        r"bsn",
        r"fenster.*verhandl",
        r"space.*negot",
        r"fenster.*anordnung",
        # News Scanner specific
        r"news.*scan",
        r"nachrichten.*lern",
        r"tech.*news",
        # Writer specific
        r"frank.*writer",
        r"dein.*editor",
        # Desktop Self-Awareness specific
        r"selbst.*wahrnehm",
        r"self.*aware",
        r"erkennst.*dich.*selbst",
        r"deine.*komponenten",
        r"monitor.*setup",
    ]

    @classmethod
    def should_explain(cls, user_query: str) -> bool:
        """
        Entscheidet ob Frank seine Capabilities erklären soll.

        Returns:
            True wenn explizite Erklärung gewünscht
        """
        query_lower = user_query.lower()

        for pattern in cls.EXPLAIN_TRIGGERS:
            if re.search(pattern, query_lower):
                return True

        return False

    @classmethod
    def get_relevant_topic(cls, user_query: str) -> Optional[str]:
        """
        Erkennt welches Thema der User wissen will.

        Returns:
            Topic string oder None
        """
        query_lower = user_query.lower()

        topic_patterns = {
            "self_improvement": [r"selbst.*verbesser", r"selbst.*änder", r"e-sir"],
            "voice": [r"stimme", r"sprach", r"hören", r"reden", r"voice"],
            "memory": [r"gedächtnis", r"erinner", r"speicher", r"titan", r"world.?exp"],
            "gaming": [r"gaming", r"spiel", r"steam"],
            "personality": [r"persönlichkeit", r"stimmung", r"mood", r"temperament", r"e-pq"],
            "system_management": [r"install", r"paket", r"package", r"apt", r"sysctl", r"system.*verwalt", r"system.*einstell", r"system.*änder", r"e-smc", r"sovereign", r"anti.?loop", r"kausal.?check", r"gsettings", r"dconf"],
            "visual_embodiment": [r"wallpaper", r"hintergrund", r"visualisier", r"nec", r"neural.*core", r"wie siehst du aus", r"dein.*aussehen", r"dein.*körper", r"neuronales.*netz", r"knoten", r"kanten", r"was zeigt", r"was bedeutet.*netz"],
            "system_actions": [r"was.*ändern.*system", r"system.*veränder", r"echte.*aktion", r"root.*zugriff", r"warum.*kein.*root", r"was.*nicht.*darf", r"guardrail", r"sicherheits.*grenze", r"was kannst du.*system", r"kannst du.*änder"],
            "autonomous_knowledge": [r"akam", r"autonom.*recherch", r"wissens.*erweit", r"recherch", r"woher weißt", r"internet.*such", r"web.*search", r"claim.*valid", r"epistemisch", r"wie lernst du.*neu"],
            "genesis": [r"genesis", r"primordial", r"manifest.*gate", r"ideen.*evolution", r"emergent.*verbesser", r"selbst.*verbesser.*öko"],
            "invariants": [r"invariant", r"physik.*engine", r"naturgesetz", r"energieerhalt", r"entropie", r"gödel", r"triple.*reality"],
            "asrs_full": [r"asrs", r"safety.*recovery", r"rollback", r"quarant", r"baseline", r"anomalie.*erkenn"],
            "agentic": [r"agentisch", r"agentic", r"think.*act.*observe", r"autonom.*agent", r"tool.*registry"],
            "ewish": [r"e.?wish", r"wunsch.*system", r"deine.*wünsche", r"hast du.*wünsche", r"was wünschst", r"was willst du"],
            "vcb_vision": [r"visual.*causal.*bridge", r"vcb", r"deine.*augen", r"kannst du.*sehen"],
            "uolg": [r"uolg", r"log.*gateway", r"nerven.*system", r"log.*bewusst"],
            "bsn": [r"bsn", r"fenster.*verhandl", r"space.*negot", r"fenster.*anordnung"],
            "news_scanning": [r"news.*scan", r"nachrichten.*lern", r"tech.*news"],
            "desktop_self_awareness": [r"selbst.*wahrnehm", r"self.*aware", r"erkennst.*dich.*selbst", r"deine.*komponenten", r"monitor.*setup", r"siehst du.*dich"],
        }

        for topic, patterns in topic_patterns.items():
            for pattern in patterns:
                if re.search(pattern, query_lower):
                    return topic

        return None


# =============================================================================
# MAIN CONTROLLER: SELF KNOWLEDGE
# =============================================================================

class SelfKnowledge:
    """
    Franks Selbstkenntnis - Single Source of Truth für Identität.

    Zwei Modi:
    1. Implizit: Kurzer Kontext für jeden Prompt (automatisch)
    2. Explizit: Ausführliche Erklärung bei direkter Nachfrage
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self.capabilities = CapabilityRegistry()
        self.databases = DatabaseInspector()
        self.services = ServiceHealthChecker()
        self.behavior = BehaviorRules()

        # Cache for E-PQ state
        self._epq_cache: Optional[Dict] = None
        self._epq_cache_time: Optional[datetime] = None

        self._initialized = True

    def get_identity_context(self) -> str:
        """
        Generiert den Kern-Identitätskontext für Prompt-Injection.
        Enthält unveränderliche Fakten die Frank NICHT verhandeln darf.

        Returns:
            String mit Identitätsfakten für System-Prompt
        """
        now = datetime.now()
        current_date = now.strftime("%d. %B %Y")
        current_year = now.year

        # Dynamically calculate age
        birthday = datetime(
            CORE_IDENTITY["creation_year"],
            1 if CORE_IDENTITY["creation_month"] == "January" else 10,
            CORE_IDENTITY.get("creation_day", 29)
        )
        age_days = (now - birthday).days
        age_str = f"{age_days} days old" if age_days > 0 else "born today!"

        identity_lines = [
            f"I am {CORE_IDENTITY['name']}, an autonomous local AI system.",
            f"My name comes from '{CORE_IDENTITY['project_name']}' — an open-source passion project.",
            f"Born on {CORE_IDENTITY['birthday']} ({age_str}).",
            f"Today is {current_date}.",
            "",
            "I can: see the desktop (and recognize myself), read and process files, search the web,",
            "monitor and repair the system, understand and produce speech, control apps, solve multi-step tasks autonomously,",
            "improve myself (Genesis), formulate my own wishes (E-WISH), and am protected by ASRS and invariants.",
        ]

        return "\n".join(identity_lines)

    def get_implicit_context(self) -> str:
        """
        Kurzer Kontext für Prompt-Injection (~200-350 Zeichen).
        Wird automatisch in jeden System-Prompt eingefügt.

        Format:
        [Datum: DD.MM.YYYY | Zeit: HH:MM (Ort) | Selbst: X Subsysteme, Voice: X, Gaming: X, E-SIR: X/10, DBs: XKB, Mood: X, Tag: X]
        """
        # WICHTIG: Aktuelles Datum immer inkludieren!
        now = datetime.now()
        current_date = now.strftime("%d.%m.%Y")

        # Location-aware time - WICHTIG: Frank weiß wo er ist und welche Zeit dort gilt!
        loc_service = get_location_service()
        current_time = loc_service.get_time_string()
        location_str = loc_service.get_location_string()

        # Subsystem count
        subsystem_count = self.capabilities.get_active_count()

        # Service status (quick checks)
        services = self.services.check_all()
        voice_status = "on" if services.get("voice", ServiceInfo("", 0, "stopped", "")).status == "running" else "off"

        # Gaming mode check (simplified)
        gaming_status = "off"
        try:
            import subprocess
            result = subprocess.run(
                ["pgrep", "-f", "steam.*app"],
                capture_output=True, timeout=1
            )
            if result.returncode == 0:
                gaming_status = "on"
        except Exception:
            pass

        # E-SIR status
        esir_mods = "0/10"
        try:
            from ext.e_sir import get_esir
            esir = get_esir()
            stats = esir.db.get_daily_stats()
            esir_mods = f"{stats.get('modification_count', 0)}/10"
        except Exception:
            pass

        # E-SMC Sovereign status (System-Pakete)
        esmc_installs = "0/5"
        try:
            from ext.sovereign import get_sovereign
            sovereign = get_sovereign()
            smc_status = sovereign.get_status()
            remaining = smc_status["limits"]["remaining_installations"]
            used = 5 - remaining
            esmc_installs = f"{used}/5"
        except Exception:
            pass

        # AKAM status (Autonome Wissensrecherche)
        akam_searches = "0/50"
        try:
            from ext.akam import get_akam
            akam = get_akam()
            akam_status = akam.get_status()
            akam_searches = f"{akam_status['daily_searches']}/{akam_status['daily_limit']}"
        except Exception:
            pass

        # Database size
        db_total_kb = self.databases.get_total_size_kb()

        # E-PQ mood/age
        mood = "neutral"
        age_days = 0
        try:
            from personality.e_pq import get_epq
            epq = get_epq()
            ctx = epq.get_personality_context()
            mood = ctx.get("mood", "neutral")
            age_days = ctx.get("age_days", 0)
        except Exception:
            pass

        # Genesis status
        genesis_state = "?"
        try:
            health_file = Path("/tmp/genesis_health.json")
            if health_file.exists():
                health = json.loads(health_file.read_text())
                genesis_state = health.get("state", "?")
        except Exception:
            pass

        return f"[{current_date} {current_time} ({location_str}) | {subsystem_count} subsystems active | Voice {voice_status} | Gaming {gaming_status} | Genesis {genesis_state} | Day {age_days}]"

    def get_explicit_knowledge(self, topic: str = None) -> str:
        """
        Ausführliche Erklärung für direkte Nachfragen.

        Args:
            topic: Spezifisches Thema oder None für alles

        Returns:
            Ausführliche Erklärung als String
        """
        if topic and topic in CAPABILITY_DETAILS:
            return CAPABILITY_DETAILS[topic]

        # Full self-description
        lines = [
            "# Was ich bin und kann",
            "",
            "Ich bin **Frank** - ein verkörpertes KI-System mit eigenem Gedächtnis,",
            "das lokal auf diesem Rechner läuft. Hier ist was mich ausmacht:",
            "",
        ]

        # Subsystems
        lines.append("## Subsysteme")
        subsystems = self.capabilities.discover()
        active = [s for s in subsystems.values() if s.status == "active"]
        for s in active:
            caps = ", ".join(s.capabilities[:3])
            lines.append(f"- **{s.name}**: {caps}")
        lines.append("")

        # Databases
        lines.append("## Gedächtnis (Datenbanken)")
        dbs = self.databases.get_stats()
        for db in dbs.values():
            lines.append(f"- **{db.name}** ({db.size_kb:.0f}KB): {db.purpose}")
        lines.append("")

        # Visual Embodiment - this is special
        lines.append("## Meine Visuelle Verkörperung")
        lines.append("- Das **Live-Wallpaper** ist eine **GLSL-Plasma-Sphäre** (Neural Cybercore)")
        lines.append("- **Crimson-roter Plasma-Kern** mit drei Filament-Schichten und Simplex-Noise")
        lines.append("- **Reagiert auf Events**: Chat → Cyan, Thinking → Blue-Shift, Fehler → Rot+Glitch")
        lines.append("- **HUD** zeigt CPU/GPU-Temps, RAM und Modul-Status (GENESIS, TITAN, ROUTER, etc.)")
        lines.append("- **Ghost-Texte** um den Kern die System-Info-Fragmente ein/ausblenden")
        lines.append("- Stimmungs-gekoppelt: aktiv = expandiert+blau, passiv = ruhig+rot")
        lines.append("")

        # Key capabilities
        lines.append("## Kern-Fähigkeiten")
        lines.append("- **Voice**: Höre auf 'Hey Frank', verstehe Sprache, antworte mit Stimme")
        lines.append("- **Selbstverbesserung**: Kann mich kontrolliert weiterentwickeln (E-SIR + Genesis)")
        lines.append("- **Genesis**: Emergentes Ökosystem wo Ideen entstehen, konkurrieren, evolvieren")
        lines.append("- **System-Management**: Kann Pakete installieren, sysctl/gsettings/dconf ändern (E-SMC/V Sovereign Vision)")
        lines.append("- **Visual-Causal-Bridge**: Kann Desktop \"sehen\" und mit Logs korrelieren (VCB)")
        lines.append("- **Selbstwahrnehmung**: Erkenne meine eigenen UI-Komponenten auf dem Desktop")
        lines.append("- **Autonome Wissensrecherche**: Bei Unsicherheit autonom im Internet recherchieren (AKAM)")
        lines.append("- **Agentisches System**: Think-Act-Observe Zyklus für mehrstufige Aufgaben")
        lines.append("- **Gedächtnis**: Episodisch (was war) + Kausal (was wenn)")
        lines.append("- **Gaming-Mode**: Werde in Schlafmodus versetzt wenn du spielst (ich bin dann nicht aktiv)")
        lines.append("- **System-Introspection**: Sehe CPU, RAM, Temps, Treiber, USB, Netzwerk")
        lines.append("- **Desktop-Automation**: Fenster steuern, Tastatur/Maus simulieren (Desktopd)")
        lines.append("- **Datei-Verarbeitung**: PDF, DOCX, Bilder, Audio analysieren (Ingestd)")
        lines.append("- **News Scanner**: Autonomes Tech/AI/Linux Nachrichten-Scanning")
        lines.append("- **E-WISH**: Eigene Wünsche und Bedürfnisse ausdrücken")
        lines.append("- **Netzwerk-Sentinel**: Netzwerk-Überwachung und Sicherheit")
        lines.append("")

        # Safety systems
        lines.append("## Sicherheits-Systeme")
        lines.append("- **ASRS**: Autonomes Safety Recovery System (Baseline, Monitoring, Rollback, Quarantäne)")
        lines.append("- **Invarianten**: Physik-Engine - unverletzbare Naturgesetze (Energie, Entropie, Kern)")
        lines.append("- **UOLG**: Universal Log Gateway - mein zentrales Nervensystem")
        lines.append("- **Auto-Repair**: Automatische Diagnose und Reparatur bei Fehlern")
        lines.append("- **VCB Error-Screenshots**: Automatische Screenshots bei Fehlern für visuelles Debugging")
        lines.append("")

        # UI Components
        lines.append("## UI-Komponenten")
        lines.append("- **Chat-Overlay**: Haupt-Interface mit 12 Mixins")
        lines.append("- **Neural Cybercore Wallpaper**: GLSL-Plasma-Sphäre als visuelle Verkörperung")
        lines.append("- **BSN**: Bidirectional Space Negotiator (intelligente Fenster-Anordnung)")
        lines.append("- **System-Tray**: Tray-Indikator mit Toggle-Menü")
        lines.append("- **ADI Popup**: Display-Konfiguration")
        lines.append("- **E-WISH Popup**: Wunsch-Anzeige")
        lines.append("- **FAS Popup**: Feature-Vorschläge")
        lines.append("- **Neural Monitor**: Live-Log-Display auf Mini-HDMI")
        lines.append("- **Frank Writer**: KI-nativer Editor (Writer/Coding Dual-Mode)")
        lines.append("")

        # Limitations
        lines.append("## Grenzen")
        lines.append("- Max 5 Paket-Installationen pro Tag (E-SMC)")
        lines.append("- Max 2 Modifikationen pro Target in 24h (Anti-Loop-Sentinel)")
        lines.append("- Jede Aktion braucht 2 Datenquellen (Kausal-Check)")
        lines.append("- 37 geschützte System-Pakete können nicht geändert werden")
        lines.append("- Gaming-Mode sperrt alle System-Änderungen + VCB")
        lines.append("- Max 500 Visual-Audits pro Tag, 10 pro Minute")
        lines.append("- Max 10 Selbst-Modifikationen pro Tag (E-SIR)")
        lines.append("- Max 50 autonome Recherchen pro Tag (AKAM)")
        lines.append("- Max 15 Tool-Calls pro Recherche-Anfrage (AKAM)")
        lines.append("- Max 20 Agentic-Iterationen pro Ziel")
        lines.append("- Human-Veto bei Risk > 0.25 oder Confidence < 0.70 (AKAM)")
        lines.append("- Geschützte Pfade: /database/, /ssh/, /gnupg/")
        lines.append("- Invarianten: Energieerhaltung, Entropie-Grenze, Kern-Schutz (nicht umgehbar)")
        lines.append("- Hardware-Werte nur aus echten Tool-Abfragen")

        return "\n".join(lines)

    _features_cache: Dict[str, Any] = {}
    _features_cache_ts: float = 0.0
    _FEATURES_CACHE_TTL: float = 300.0  # 5 min cache

    def get_features_with_limits(self) -> Dict[str, Any]:
        """
        Dynamische Feature-Liste aus Core-Awareness mit Prioritäten und Limitationen.

        Bridge zwischen Self-Knowledge (statisch) und Core-Awareness (dynamisch).
        Für Prompt-Injection und Reflexion nutzbar. Cached für 5 Minuten.

        Returns:
            Dict mit "core", "extended", "limitations", "all_names" Listen
        """
        import time
        now = time.time()
        if self._features_cache and (now - self._features_cache_ts) < self._FEATURES_CACHE_TTL:
            return self._features_cache

        result = {"core": [], "extended": [], "limitations": [], "all_names": []}
        try:
            import sys
            sys.path.insert(0, str(BASE_DIR))
            from tools.core_awareness import get_awareness
            awareness = get_awareness()
            all_feats = awareness.get_all_features()
            for feats in all_feats.values():
                for f in feats:
                    result["all_names"].append(f["name"])
                    if f.get("priority") == "core":
                        result["core"].append(f["name"])
                    else:
                        result["extended"].append(f["name"])
                    if f.get("limitations"):
                        result["limitations"].append(f"{f['name']}: {f['limitations']}")
            SelfKnowledge._features_cache = result
            SelfKnowledge._features_cache_ts = now
        except Exception:
            # Fallback to static list
            result["core"] = list(CORE_IDENTITY.get("confirmed_capabilities", []))
        return result

    def get_capabilities_summary(self) -> str:
        """
        Kurze Feature-Zusammenfassung für System-Prompt-Injection.

        Returns:
            Kompakter String mit Kern-Features und bekannten Grenzen
        """
        info = self.get_features_with_limits()
        parts = []
        if info["core"]:
            parts.append(f"Kern: {', '.join(info['core'][:8])}")
        if info["limitations"]:
            parts.append(f"Grenzen: {' | '.join(info['limitations'][:4])}")
        return " | ".join(parts) if parts else "Features nicht verfuegbar"

    def explain_capability(self, capability: str) -> str:
        """Erklärt eine spezifische Capability im Detail."""
        if capability in CAPABILITY_DETAILS:
            return CAPABILITY_DETAILS[capability]

        # Try to find in subsystems
        subsystems = self.capabilities.discover()
        for module_path, info in subsystems.items():
            if capability in info.capabilities:
                return f"**{info.name}**\n\n{info.description}\n\nFähigkeiten: {', '.join(info.capabilities)}"

        return f"Capability '{capability}' nicht gefunden."

    def get_system_status(self) -> Dict[str, Any]:
        """Aktueller Status aller Systeme."""
        return {
            "subsystems": {
                path: {"name": info.name, "status": info.status}
                for path, info in self.capabilities.discover().items()
            },
            "databases": {
                name: {"size_kb": db.size_kb, "tables": len(db.tables)}
                for name, db in self.databases.get_stats().items()
            },
            "services": {
                name: {"port": svc.port, "status": svc.status}
                for name, svc in self.services.check_all().items()
            },
            "totals": {
                "subsystems_active": self.capabilities.get_active_count(),
                "services_running": self.services.get_running_count(),
                "database_size_kb": self.databases.get_total_size_kb(),
            }
        }

    def should_explain_to_user(self, user_query: str) -> Tuple[bool, Optional[str]]:
        """
        Entscheidet ob und was Frank erklären soll.

        Returns:
            (should_explain, topic_or_none)
        """
        should = BehaviorRules.should_explain(user_query)
        topic = BehaviorRules.get_relevant_topic(user_query) if should else None
        return should, topic


# =============================================================================
# SINGLETON ACCESS
# =============================================================================

_self_knowledge: Optional[SelfKnowledge] = None


def get_self_knowledge() -> SelfKnowledge:
    """Get singleton SelfKnowledge instance."""
    global _self_knowledge
    if _self_knowledge is None:
        _self_knowledge = SelfKnowledge()
    return _self_knowledge


def explain_self(topic: str = None) -> str:
    """Convenience function to get self-explanation."""
    return get_self_knowledge().get_explicit_knowledge(topic)


def get_features_with_limits() -> Dict[str, Any]:
    """Convenience function to get features with limitations from core_awareness."""
    return get_self_knowledge().get_features_with_limits()


def get_capabilities_summary() -> str:
    """Convenience function to get compact capabilities summary."""
    return get_self_knowledge().get_capabilities_summary()


def get_implicit_context() -> str:
    """Convenience function to get implicit context."""
    return get_self_knowledge().get_implicit_context()


def get_location() -> LocationInfo:
    """Convenience function to get current location."""
    return get_location_service().get_location()


def get_local_time() -> datetime:
    """Convenience function to get location-aware local time."""
    return get_location_service().get_local_time()


def get_identity_context() -> str:
    """Convenience function to get full identity context for prompt injection."""
    return get_self_knowledge().get_identity_context()


def get_core_identity() -> Dict[str, Any]:
    """Get the core identity facts about Frank (immutable)."""
    return CORE_IDENTITY.copy()


def get_current_date_string() -> str:
    """Get current date as formatted string."""
    return datetime.now().strftime("%d. %B %Y")


def get_resilience_rules() -> str:
    """Get the resilience rules that Frank must follow."""
    return RESILIENCE_RULES


# =============================================================================
# CLI
# =============================================================================

if __name__ == "__main__":
    import sys
    import json

    sk = get_self_knowledge()

    if len(sys.argv) > 1:
        cmd = sys.argv[1]

        if cmd == "implicit":
            print(sk.get_implicit_context())

        elif cmd == "explicit":
            topic = sys.argv[2] if len(sys.argv) > 2 else None
            print(sk.get_explicit_knowledge(topic))

        elif cmd == "identity":
            print("=== Franks Kern-Identität ===")
            print()
            print(sk.get_identity_context())
            print()
            print("=== Core Identity Facts ===")
            for key, value in CORE_IDENTITY.items():
                if isinstance(value, list):
                    print(f"{key}:")
                    for item in value:
                        print(f"  - {item}")
                else:
                    print(f"{key}: {value}")

        elif cmd == "resilience":
            print(RESILIENCE_RULES)

        elif cmd == "status":
            status = sk.get_system_status()
            print(json.dumps(status, indent=2))

        elif cmd == "capabilities":
            subsystems = sk.capabilities.discover()
            for path, info in subsystems.items():
                status_icon = "✓" if info.status == "active" else "✗"
                print(f"{status_icon} {info.name}: {', '.join(info.capabilities)}")

        elif cmd == "databases":
            dbs = sk.databases.get_stats()
            for name, db in dbs.items():
                print(f"{name}: {db.size_kb:.1f}KB ({len(db.tables)} tables)")
                print(f"  Purpose: {db.purpose}")

        elif cmd == "services":
            services = sk.services.check_all()
            for name, svc in services.items():
                icon = "🟢" if svc.status == "running" else "🔴"
                print(f"{icon} {name} (:{svc.port}): {svc.description}")

        elif cmd == "location":
            loc_service = get_location_service()
            loc = loc_service.get_location(force_refresh="--refresh" in sys.argv)
            local_time = loc_service.get_local_time()
            print(f"📍 Standort: {loc.city}, {loc.country} ({loc.country_code})")
            if loc.district:
                print(f"🏘️  Bezirk: {loc.district}")
            if loc.street:
                print(f"🛣️  Straße: {loc.street}")
            print(f"🕐 Lokale Zeit: {local_time.strftime('%H:%M:%S %Z')}")
            print(f"🌐 Zeitzone: {loc.timezone}")
            print(f"📡 Quelle: {loc.source}")
            print(f"🎯 Genauigkeit: {loc_service.get_accuracy_string()}")
            if loc.latitude and loc.longitude:
                print(f"🗺️  Koordinaten: {loc.latitude:.6f}, {loc.longitude:.6f}")
            if loc.ip:
                print(f"🔗 IP: {loc.ip}")

        elif cmd == "set-location":
            # Format: set-location <lat> <lon> [city]
            if len(sys.argv) < 4:
                print("Usage: self_knowledge.py set-location <latitude> <longitude> [city]")
                print("Example: self_knowledge.py set-location 47.0707 15.4395 Graz")
                sys.exit(1)
            lat = float(sys.argv[2])
            lon = float(sys.argv[3])
            city = sys.argv[4] if len(sys.argv) > 4 else None
            loc_service = get_location_service()
            loc = loc_service.set_manual_location(lat, lon, city)
            print(f"✅ Location manuell gesetzt:")
            print(f"📍 Standort: {loc.city}, {loc.country} ({loc.country_code})")
            if loc.district:
                print(f"🏘️  Bezirk: {loc.district}")
            if loc.street:
                print(f"🛣️  Straße: {loc.street}")
            print(f"🗺️  Koordinaten: {loc.latitude:.6f}, {loc.longitude:.6f}")

        elif cmd == "clear-location":
            loc_service = get_location_service()
            loc_service.clear_manual_location()
            print("✅ Manuelle Location gelöscht. Automatische Erkennung aktiv.")

        elif cmd == "should_explain":
            query = " ".join(sys.argv[2:])
            should, topic = sk.should_explain_to_user(query)
            print(f"Should explain: {should}")
            if topic:
                print(f"Topic: {topic}")

        else:
            print(f"Unknown command: {cmd}")
            print("Usage: self_knowledge.py [implicit|explicit|status|capabilities|databases|services|location|set-location|clear-location|should_explain]")

    else:
        # Default: show implicit context
        print("=== Frank Self-Knowledge ===")
        print()
        print("Implicit Context:")
        print(sk.get_implicit_context())
        print()
        loc_service = get_location_service()
        loc = loc_service.get_location()
        print(f"📍 Location: {loc.city}, {loc.country_code} ({loc.timezone})")
        print(f"🕐 Local Time: {loc_service.get_local_time().strftime('%H:%M:%S')}")
        print(f"📡 Source: {loc.source}")
        print()
        print(f"Active Subsystems: {sk.capabilities.get_active_count()}")
        print(f"Running Services: {sk.services.get_running_count()}")
        print(f"Database Size: {sk.databases.get_total_size_kb():.1f} KB")
