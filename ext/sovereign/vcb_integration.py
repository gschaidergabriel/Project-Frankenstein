#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
E-SMC/V Visual-Causal-Bridge (VCB) Integration
==============================================

Epistemische Brücke zwischen System-Logs und tatsächlicher User-Experience.
Frank kann "sehen" was auf dem Desktop passiert und dies mit Logs korrelieren.

Der Synergie-Prozess:
1. Beobachtung: Frank bemerkt Anomalie in Logs oder erhält vage User-Anfrage
2. Visual Audit: take_screenshot() um visuellen Status zu synchronisieren
3. Kausale Analyse: Korrelation (Log: hohe Last + Screenshot: hängendes Fenster)
4. Sovereign Action: Installation/Konfiguration zur Behebung

Datenschutz:
- Screenshots werden im RAM verarbeitet
- Nach VLM-Inference sofort verworfen
- Nur Text-Beschreibung wird in world_experience.db gespeichert

Rate-Limiter: Max 100 Bilder/Tag

Usage:
    from ext.sovereign.vcb_integration import get_vcb_bridge

    vcb = get_vcb_bridge()

    # Visual Audit durchführen
    description = vcb.visual_audit("Hohe CPU-Last erkannt")

    # Log-Visual Korrelation
    result = vcb.correlate_log_visual(
        "ERROR: Xorg consuming 100% CPU",
        description
    )
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import subprocess
import threading
from dataclasses import dataclass
from datetime import datetime, date
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# =============================================================================
# CONFIGURATION
# =============================================================================

# Rate Limits
MAX_DAILY_SCREENSHOTS = 100
MAX_SCREENSHOTS_PER_HOUR = 20

# Paths
try:
    from config.paths import get_db, DB_DIR as _DB_DIR
except ImportError:
    _DB_DIR = Path("/home/ai-core-node/.local/share/frank/db")
    def get_db(name):
        return _DB_DIR / f"{name}.db"

AICORE_DB = _DB_DIR
WORLD_EXP_DB = get_db("world_experience")
SOVEREIGN_DB = get_db("sovereign")

# VLM Configuration (für lokale Qwen-VL oder HuggingFace API)
VLM_LOCAL_ENDPOINT = "http://127.0.0.1:11434/api/generate"  # Ollama
VLM_MODEL = "llava"  # oder "qwen-vl" wenn verfügbar

# Gaming-Mode Lock File
GAMING_LOCK_FILE = Path("/tmp/frank_gaming_mode.lock")


# =============================================================================
# DATA STRUCTURES
# =============================================================================

@dataclass
class VisualAuditResult:
    """Ergebnis eines Visual Audits."""
    timestamp: str
    reason: str
    description: str
    confidence: float
    anomalies_detected: List[str]
    suggested_actions: List[str]
    audit_id: str


@dataclass
class CorrelationResult:
    """Ergebnis einer Log-Visual Korrelation."""
    correlation_found: bool
    confidence: float
    log_summary: str
    visual_summary: str
    suggested_action: str
    sources: List[str]
    legitimacy_score: float


# =============================================================================
# VCB BRIDGE
# =============================================================================

class VCBBridge:
    """
    👁️ Visual-Causal-Bridge: Epistemische Brücke zwischen Logs und Desktop.

    Ermöglicht Frank zu "sehen" was auf dem Bildschirm passiert und
    dies mit System-Logs zu korrelieren.
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

        self._daily_count = 0
        self._hourly_count = 0
        self._last_reset_date = date.today()
        self._last_hourly_reset = datetime.now().hour

        self._initialized = True

    def _check_rate_limit(self) -> Tuple[bool, str]:
        """Prüft Rate-Limits."""
        now = datetime.now()
        today = date.today()

        # Daily reset
        if today != self._last_reset_date:
            self._daily_count = 0
            self._last_reset_date = today

        # Hourly reset
        if now.hour != self._last_hourly_reset:
            self._hourly_count = 0
            self._last_hourly_reset = now.hour

        if self._daily_count >= MAX_DAILY_SCREENSHOTS:
            return False, f"Daily limit reached ({MAX_DAILY_SCREENSHOTS}/day)"

        if self._hourly_count >= MAX_SCREENSHOTS_PER_HOUR:
            return False, f"Hourly limit reached ({MAX_SCREENSHOTS_PER_HOUR}/hour)"

        return True, "OK"

    def _increment_counters(self) -> None:
        """Erhöht Rate-Limit Zähler."""
        self._daily_count += 1
        self._hourly_count += 1

    def is_gaming_active(self) -> bool:
        """
        Prüft ob Gaming-Mode aktiv ist.
        VCB ist während Gaming DEAKTIVIERT (Anti-Cheat Schutz).
        """
        if GAMING_LOCK_FILE.exists():
            return True

        # Check for running games
        try:
            result = subprocess.run(
                ["pgrep", "-f", "steam.*app"],
                capture_output=True, timeout=2
            )
            return result.returncode == 0
        except Exception:
            pass

        return False

    def _take_screenshot_raw(self) -> Optional[bytes]:
        """
        Erstellt Screenshot im RAM (nicht auf Disk).
        Returns PNG bytes oder None bei Fehler.
        """
        try:
            # Verwende gnome-screenshot oder scrot
            # Output direkt nach stdout um Disk zu vermeiden
            result = subprocess.run(
                ["gnome-screenshot", "-f", "/dev/stdout"],
                capture_output=True, timeout=5
            )

            if result.returncode == 0 and result.stdout:
                return result.stdout

            # Fallback: scrot
            result = subprocess.run(
                ["scrot", "-o", "-"],
                capture_output=True, timeout=5
            )

            if result.returncode == 0 and result.stdout:
                return result.stdout

            # Fallback 2: import (ImageMagick)
            result = subprocess.run(
                ["import", "-window", "root", "png:-"],
                capture_output=True, timeout=5
            )

            if result.returncode == 0 and result.stdout:
                return result.stdout

        except Exception:
            pass

        return None

    def _analyze_screenshot_vlm(self, image_bytes: bytes, context: str) -> str:
        """
        Analysiert Screenshot mit VLM (Vision Language Model).
        Gibt Text-Beschreibung zurück.
        """
        try:
            import urllib.request

            # Encode image as base64
            image_b64 = base64.b64encode(image_bytes).decode('utf-8')

            # Try local Ollama first
            payload = {
                "model": VLM_MODEL,
                "prompt": f"""Analysiere diesen Desktop-Screenshot.
Kontext: {context}

Describe briefly and precisely:
1. What is visible on the screen?
2. Are there visible problems (error dialogs, hanging windows, high load indicators)?
3. Which applications are active?

Answer in 2-3 sentences.""",
                "images": [image_b64],
                "stream": False
            }

            req = urllib.request.Request(
                VLM_LOCAL_ENDPOINT,
                data=json.dumps(payload).encode('utf-8'),
                headers={"Content-Type": "application/json"},
                method="POST"
            )

            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                return data.get("response", "Keine Beschreibung verfügbar")

        except Exception as e:
            return f"VLM-Analyse nicht verfügbar: {str(e)}"

    def _store_in_world_experience(
        self,
        audit_id: str,
        description: str,
        context: str
    ) -> None:
        """
        Speichert Visual-Beschreibung in world_experience.db.
        NUR Text wird gespeichert, keine Bilder!
        """
        try:
            import sqlite3

            with sqlite3.connect(WORLD_EXP_DB) as conn:
                # Prüfe ob Tabelle existiert
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS vcb_observations (
                        id TEXT PRIMARY KEY,
                        timestamp TEXT NOT NULL,
                        context TEXT,
                        visual_description TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    )
                """)

                conn.execute("""
                    INSERT INTO vcb_observations (id, timestamp, context, visual_description, created_at)
                    VALUES (?, ?, ?, ?, ?)
                """, (
                    audit_id,
                    datetime.now().isoformat(),
                    context,
                    description,
                    datetime.now().isoformat()
                ))
        except Exception:
            pass

    def visual_audit(
        self,
        reason: str,
        store_result: bool = True
    ) -> Optional[VisualAuditResult]:
        """
        Führt einen Visual Audit durch.

        1. Screenshot im RAM
        2. VLM-Inference
        3. Screenshot verwerfen (nur Text behalten)
        4. Optional: Text in world_experience.db speichern

        Args:
            reason: Warum wird der Audit durchgeführt
            store_result: Ob Ergebnis in DB gespeichert werden soll

        Returns:
            VisualAuditResult oder None bei Fehler/Block
        """
        # Gaming-Mode Check
        if self.is_gaming_active():
            return None

        # Rate-Limit Check
        allowed, msg = self._check_rate_limit()
        if not allowed:
            return None

        # Take screenshot (in RAM)
        image_bytes = self._take_screenshot_raw()
        if not image_bytes:
            return None

        # Increment counter
        self._increment_counters()

        # Generate audit ID
        audit_id = f"vcb_{datetime.now().strftime('%Y%m%d%H%M%S')}_{hashlib.sha256(os.urandom(8)).hexdigest()[:8]}"

        # Analyze with VLM
        description = self._analyze_screenshot_vlm(image_bytes, reason)

        # WICHTIG: Screenshot-Bytes werden hier verworfen (out of scope)
        # Nur die Text-Beschreibung bleibt

        # Parse anomalies from description
        anomalies = []
        anomaly_keywords = ["fehler", "error", "hängt", "freeze", "nicht reagiert", "hohe last", "100%"]
        desc_lower = description.lower()
        for kw in anomaly_keywords:
            if kw in desc_lower:
                anomalies.append(kw)

        # Suggested actions based on anomalies
        suggested = []
        if "hängt" in desc_lower or "freeze" in desc_lower:
            suggested.append("Prozess neu starten")
        if "hohe last" in desc_lower or "100%" in desc_lower:
            suggested.append("Ressourcen-Monitor installieren (htop)")
        if "fehler" in desc_lower or "error" in desc_lower:
            suggested.append("Log-Analyse durchführen")

        result = VisualAuditResult(
            timestamp=datetime.now().isoformat(),
            reason=reason,
            description=description,
            confidence=0.7 if anomalies else 0.5,
            anomalies_detected=anomalies,
            suggested_actions=suggested,
            audit_id=audit_id
        )

        # Store in world_experience.db
        if store_result:
            self._store_in_world_experience(audit_id, description, reason)

        return result

    def correlate_log_visual(
        self,
        log_entry: str,
        visual_description: str
    ) -> CorrelationResult:
        """
        Korreliert Log-Eintrag mit visueller Beobachtung.

        Args:
            log_entry: Der Log-Eintrag (z.B. "ERROR: High CPU usage")
            visual_description: Die VLM-Beschreibung des Screenshots

        Returns:
            CorrelationResult mit Confidence und suggested_action
        """
        # Simple keyword-based correlation
        log_lower = log_entry.lower()
        visual_lower = visual_description.lower()

        correlation_found = False
        confidence = 0.0
        suggested_action = ""

        # CPU-Korrelation
        if any(k in log_lower for k in ["cpu", "last", "load"]):
            if any(k in visual_lower for k in ["last", "100%", "hängt", "langsam"]):
                correlation_found = True
                confidence = 0.85
                suggested_action = "CPU-intensive Prozesse identifizieren und optimieren"

        # Memory-Korrelation
        if any(k in log_lower for k in ["memory", "ram", "oom", "speicher"]):
            if any(k in visual_lower for k in ["speicher", "memory", "swap"]):
                correlation_found = True
                confidence = 0.8
                suggested_action = "Memory-Leak untersuchen, ggf. Prozess neu starten"

        # UI-Freeze-Korrelation
        if any(k in log_lower for k in ["xorg", "compositor", "display"]):
            if any(k in visual_lower for k in ["hängt", "freeze", "reagiert nicht"]):
                correlation_found = True
                confidence = 0.9
                suggested_action = "Compositor oder Display-Server neu starten"

        # Fallback
        if not correlation_found:
            # Check for any overlap
            log_words = set(log_lower.split())
            visual_words = set(visual_lower.split())
            overlap = log_words & visual_words
            if len(overlap) > 2:
                correlation_found = True
                confidence = 0.5
                suggested_action = "Weitere Analyse erforderlich"

        sources = ["log_error"]
        if visual_description and "VLM-Analyse nicht verfügbar" not in visual_description:
            sources.append("visual_vcb")

        # Calculate legitimacy score
        from .e_smc import CausalValidator
        legitimacy = CausalValidator.get_legitimacy_score(sources)

        return CorrelationResult(
            correlation_found=correlation_found,
            confidence=confidence,
            log_summary=log_entry[:200],
            visual_summary=visual_description[:200],
            suggested_action=suggested_action,
            sources=sources,
            legitimacy_score=legitimacy
        )

    def get_stats(self) -> Dict[str, Any]:
        """Gibt aktuelle Statistiken zurück."""
        return {
            "daily_count": self._daily_count,
            "hourly_count": self._hourly_count,
            "daily_limit": MAX_DAILY_SCREENSHOTS,
            "hourly_limit": MAX_SCREENSHOTS_PER_HOUR,
            "remaining_daily": MAX_DAILY_SCREENSHOTS - self._daily_count,
            "remaining_hourly": MAX_SCREENSHOTS_PER_HOUR - self._hourly_count,
            "gaming_active": self.is_gaming_active(),
        }


# =============================================================================
# SINGLETON ACCESS
# =============================================================================

_vcb_bridge: Optional[VCBBridge] = None


def get_vcb_bridge() -> VCBBridge:
    """Singleton-Zugriff auf VCB Bridge."""
    global _vcb_bridge
    if _vcb_bridge is None:
        _vcb_bridge = VCBBridge()
    return _vcb_bridge


# =============================================================================
# CLI
# =============================================================================

if __name__ == "__main__":
    import sys

    vcb = get_vcb_bridge()

    if len(sys.argv) > 1:
        cmd = sys.argv[1]

        if cmd == "status":
            stats = vcb.get_stats()
            print("VCB Bridge Status:")
            print(f"  Daily: {stats['daily_count']}/{stats['daily_limit']}")
            print(f"  Hourly: {stats['hourly_count']}/{stats['hourly_limit']}")
            print(f"  Gaming Active: {stats['gaming_active']}")

        elif cmd == "audit":
            reason = " ".join(sys.argv[2:]) if len(sys.argv) > 2 else "Manual audit"
            print(f"Running visual audit: {reason}")
            result = vcb.visual_audit(reason)
            if result:
                print(f"Audit ID: {result.audit_id}")
                print(f"Description: {result.description}")
                print(f"Anomalies: {result.anomalies_detected}")
                print(f"Suggested: {result.suggested_actions}")
            else:
                print("Audit blocked (Gaming mode or rate limit)")

        elif cmd == "correlate":
            log_entry = sys.argv[2] if len(sys.argv) > 2 else "ERROR: High CPU"
            visual_desc = sys.argv[3] if len(sys.argv) > 3 else "Desktop zeigt hohe CPU-Last"
            result = vcb.correlate_log_visual(log_entry, visual_desc)
            print(f"Correlation found: {result.correlation_found}")
            print(f"Confidence: {result.confidence}")
            print(f"Sources: {result.sources}")
            print(f"Legitimacy: {result.legitimacy_score}")
            print(f"Suggested: {result.suggested_action}")

        else:
            print(f"Unknown command: {cmd}")
            print("Usage: vcb_integration.py [status|audit [reason]|correlate [log] [visual]]")

    else:
        print("E-SMC/V Visual-Causal-Bridge")
        print()
        stats = vcb.get_stats()
        print(f"Screenshots today: {stats['daily_count']}/{stats['daily_limit']}")
        print(f"Gaming mode: {'ACTIVE (VCB disabled)' if stats['gaming_active'] else 'inactive'}")
