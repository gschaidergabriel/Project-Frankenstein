#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Visual-Causal-Bridge (VCB) v3.0 - Frank's Eyes (Local Only)

100% lokale Bildanalyse mit Moondream 2 via Ollama.
Keine externen API-Abhängigkeiten mehr.

Features:
- Moondream 2 als einziger Vision-Backend (via Ollama)
- Error-Screenshot für automatische Fehleranalyse
- Loop-Protection gegen System-Blockierung
- UOLG Integration für Log-Korrelation
- Gaming Mode Protection
- Privacy: Screenshots nach Analyse gelöscht

Usage:
    from tools.vcb_bridge import take_screenshot, analyze_screen, analyze_image

    # Screenshot analysis
    result = take_screenshot("Was siehst du auf dem Bildschirm?")

    # Image file analysis
    description = analyze_image("/path/to/image.png", "What is shown?")

    # Error screenshot (for debugging)
    error_context = capture_error_screenshot("Service crashed")
"""

import base64
import io
import json
import logging
import subprocess
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import urllib.request
import urllib.error

# Logging
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s [VCB]: %(message)s',
)
LOG = logging.getLogger("vcb")

# =============================================================================
# CONFIGURATION
# =============================================================================

# Paths
try:
    from config.paths import STATE_DIR as DB_DIR, get_state, ERROR_SCREENSHOTS_DIR as ERROR_SCREENSHOT_DIR
    VCB_STATE_FILE = get_state("vcb_state")
except ImportError:
    DB_DIR = Path("/home/ai-core-node/aicore/database")
    VCB_STATE_FILE = DB_DIR / "vcb_state.json"
    ERROR_SCREENSHOT_DIR = Path("/home/ai-core-node/aicore/database/error_screenshots")
GAMING_STATE_FILE = Path("/tmp/gaming_mode_state.json")
TEMP_SCREENSHOT = Path("/tmp/vcb_screenshot.png")

# Local Vision Model via Ollama (ONLY BACKEND)
# LLaVA 7B is more reliable than Moondream for detailed analysis
OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODELS = ["llava:latest", "moondream:latest"]  # Fallback order

# Configuration
CONFIG = {
    # Rate Limiting
    "daily_limit": 500,                     # Higher limit for local (no API costs)
    "rate_limit_per_minute": 10,            # Max per minute
    "cooldown_on_error_sec": 10,            # Short cooldown for local errors

    # Timeouts
    "ollama_timeout_seconds": 120,          # Timeout for Moondream inference
    "ollama_health_timeout": 3,             # Quick health check

    # Image Processing
    "max_image_size_kb": 1024,              # Larger for local (no upload limits)
    "jpeg_quality": 85,                     # Higher quality for local

    # Loop Protection
    "max_consecutive_failures": 3,          # Max failures before pause
    "failure_backoff_seconds": 60,          # Backoff after max failures
    "error_screenshot_cooldown_sec": 30,    # Min time between error screenshots

    # Error Screenshot
    "max_error_screenshots_per_hour": 10,   # Prevent screenshot spam
    "error_screenshot_retention_hours": 24, # Auto-delete after 24h

    # Misc
    "default_confidence": 0.8,              # Higher confidence for local
}

# UOLG Integration
UOLG_API_URL = "http://localhost:8197"


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class VCBState:
    """Tracks VCB usage and loop protection."""
    daily_count: int = 0
    last_reset_date: str = ""
    minute_timestamps: List[float] = None
    last_error_time: float = 0
    total_analyses: int = 0
    consecutive_failures: int = 0
    last_failure_time: float = 0
    error_screenshots_this_hour: int = 0
    last_error_screenshot_time: float = 0
    last_error_screenshot_hour: int = -1

    def __post_init__(self):
        if self.minute_timestamps is None:
            self.minute_timestamps = []


@dataclass
class VisualEvidence:
    """Result of visual analysis."""
    timestamp: datetime
    description: str
    confidence: float
    correlated_logs: List[dict]
    model_used: str
    backend: str = "moondream_local"
    processing_time_sec: float = 0.0

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp.isoformat(),
            "description": self.description,
            "confidence": self.confidence,
            "correlated_logs": self.correlated_logs,
            "model_used": self.model_used,
            "backend": self.backend,
            "processing_time_sec": round(self.processing_time_sec, 2),
        }


# =============================================================================
# RATE LIMITER WITH LOOP PROTECTION
# =============================================================================

class RateLimiter:
    """Rate limiter with loop protection to prevent system blocking."""

    def __init__(self):
        self.state = VCBState()
        self._lock = threading.Lock()
        self._load_state()

    def _load_state(self):
        """Load state from disk."""
        try:
            if VCB_STATE_FILE.exists():
                data = json.loads(VCB_STATE_FILE.read_text())
                self.state.daily_count = data.get("daily_count", 0)
                self.state.last_reset_date = data.get("last_reset_date", "")
                self.state.total_analyses = data.get("total_analyses", 0)
                self.state.last_error_time = data.get("last_error_time", 0)
                self.state.consecutive_failures = data.get("consecutive_failures", 0)
                self.state.last_failure_time = data.get("last_failure_time", 0)
                self.state.error_screenshots_this_hour = data.get("error_screenshots_this_hour", 0)
                self.state.last_error_screenshot_hour = data.get("last_error_screenshot_hour", -1)
        except Exception:
            pass

    def _save_state(self):
        """Save state to disk."""
        try:
            DB_DIR.mkdir(parents=True, exist_ok=True)
            data = {
                "daily_count": self.state.daily_count,
                "last_reset_date": self.state.last_reset_date,
                "total_analyses": self.state.total_analyses,
                "last_error_time": self.state.last_error_time,
                "consecutive_failures": self.state.consecutive_failures,
                "last_failure_time": self.state.last_failure_time,
                "error_screenshots_this_hour": self.state.error_screenshots_this_hour,
                "last_error_screenshot_hour": self.state.last_error_screenshot_hour,
            }
            VCB_STATE_FILE.write_text(json.dumps(data, indent=2))
        except Exception as e:
            LOG.error(f"Failed to save VCB state: {e}")

    def can_proceed(self) -> Tuple[bool, str]:
        """Check if we can make a request (with loop protection)."""
        with self._lock:
            now = time.time()
            today = datetime.now().strftime("%Y-%m-%d")
            current_hour = datetime.now().hour

            # Reset daily counter at midnight
            if self.state.last_reset_date != today:
                self.state.daily_count = 0
                self.state.last_reset_date = today
                self.state.minute_timestamps = []
                self.state.consecutive_failures = 0
                self._save_state()

            # Reset hourly error screenshot counter
            if self.state.last_error_screenshot_hour != current_hour:
                self.state.error_screenshots_this_hour = 0
                self.state.last_error_screenshot_hour = current_hour

            # LOOP PROTECTION: Check for too many consecutive failures
            if self.state.consecutive_failures >= CONFIG["max_consecutive_failures"]:
                elapsed = now - self.state.last_failure_time
                if elapsed < CONFIG["failure_backoff_seconds"]:
                    remaining = int(CONFIG["failure_backoff_seconds"] - elapsed)
                    return False, f"Loop protection: {remaining}s backoff after {self.state.consecutive_failures} failures"
                else:
                    # Reset after backoff period
                    self.state.consecutive_failures = 0

            # Check daily limit
            if self.state.daily_count >= CONFIG["daily_limit"]:
                return False, f"Daily limit reached ({CONFIG['daily_limit']} images)"

            # Check cooldown after error
            if self.state.last_error_time > 0:
                elapsed = now - self.state.last_error_time
                if elapsed < CONFIG["cooldown_on_error_sec"]:
                    remaining = int(CONFIG["cooldown_on_error_sec"] - elapsed)
                    return False, f"Cooldown after error ({remaining}s remaining)"

            # Check per-minute rate
            minute_ago = now - 60
            self.state.minute_timestamps = [
                t for t in self.state.minute_timestamps if t > minute_ago
            ]
            if len(self.state.minute_timestamps) >= CONFIG["rate_limit_per_minute"]:
                return False, "Rate limit: too many requests per minute"

            return True, "OK"

    def can_error_screenshot(self) -> Tuple[bool, str]:
        """Check if we can take an error screenshot (prevent spam)."""
        with self._lock:
            now = time.time()
            current_hour = datetime.now().hour

            # Reset hourly counter
            if self.state.last_error_screenshot_hour != current_hour:
                self.state.error_screenshots_this_hour = 0
                self.state.last_error_screenshot_hour = current_hour

            # Check cooldown
            elapsed = now - self.state.last_error_screenshot_time
            if elapsed < CONFIG["error_screenshot_cooldown_sec"]:
                remaining = int(CONFIG["error_screenshot_cooldown_sec"] - elapsed)
                return False, f"Error screenshot cooldown ({remaining}s)"

            # Check hourly limit
            if self.state.error_screenshots_this_hour >= CONFIG["max_error_screenshots_per_hour"]:
                return False, f"Max error screenshots this hour ({CONFIG['max_error_screenshots_per_hour']})"

            return True, "OK"

    def record_error_screenshot(self):
        """Record an error screenshot was taken."""
        with self._lock:
            self.state.error_screenshots_this_hour += 1
            self.state.last_error_screenshot_time = time.time()
            self._save_state()

    def record_request(self):
        """Record a successful request."""
        with self._lock:
            now = time.time()
            self.state.daily_count += 1
            self.state.total_analyses += 1
            self.state.minute_timestamps.append(now)
            self.state.last_error_time = 0
            self.state.consecutive_failures = 0  # Reset on success
            self._save_state()

    def record_failure(self):
        """Record a failure (for loop protection)."""
        with self._lock:
            self.state.consecutive_failures += 1
            self.state.last_failure_time = time.time()
            self.state.last_error_time = time.time()
            LOG.warning(f"VCB failure recorded ({self.state.consecutive_failures}/{CONFIG['max_consecutive_failures']})")
            self._save_state()

    def get_stats(self) -> dict:
        """Get rate limiter statistics."""
        with self._lock:
            return {
                "daily_count": self.state.daily_count,
                "daily_limit": CONFIG["daily_limit"],
                "remaining_today": CONFIG["daily_limit"] - self.state.daily_count,
                "total_analyses": self.state.total_analyses,
                "consecutive_failures": self.state.consecutive_failures,
                "error_screenshots_this_hour": self.state.error_screenshots_this_hour,
            }


# =============================================================================
# GAMING MODE GUARD
# =============================================================================

class GamingModeGuard:
    """Checks if gaming mode is active."""

    def __init__(self):
        self._cache = False
        self._last_check = 0

    def is_gaming(self) -> bool:
        """Check if gaming mode is active."""
        now = time.time()
        if now - self._last_check < 5:
            return self._cache

        self._last_check = now
        try:
            if GAMING_STATE_FILE.exists():
                data = json.loads(GAMING_STATE_FILE.read_text())
                self._cache = data.get("active", False)
        except Exception:
            pass
        return self._cache


# =============================================================================
# SCREEN CAPTURE
# =============================================================================

class ScreenCapture:
    """Handles screenshot capture and compression."""

    @staticmethod
    def capture(output_path: Path = TEMP_SCREENSHOT) -> Optional[Path]:
        """Capture screenshot using available tools."""
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Try multiple screenshot tools
        for cmd in [
            ["maim", "-u", str(output_path)],
            ["scrot", str(output_path)],
            ["grim", str(output_path)],  # Wayland support
            ["import", "-window", "root", str(output_path)],
        ]:
            try:
                result = subprocess.run(cmd, capture_output=True, timeout=10)
                if result.returncode == 0 and output_path.exists():
                    LOG.debug(f"Screenshot captured with {cmd[0]}")
                    return output_path
            except FileNotFoundError:
                continue
            except Exception as e:
                LOG.warning(f"{cmd[0]} failed: {e}")

        LOG.error("All screenshot methods failed")
        return None

    @staticmethod
    def compress_if_needed(image_path: Path) -> bytes:
        """Compress image for inference."""
        try:
            from PIL import Image

            img = Image.open(image_path)

            # Convert to RGB
            if img.mode in ('RGBA', 'P', 'LA'):
                bg = Image.new('RGB', img.size, (0, 0, 0))
                if img.mode == 'P':
                    img = img.convert('RGBA')
                if img.mode in ('RGBA', 'LA'):
                    bg.paste(img, mask=img.split()[-1])
                    img = bg
                else:
                    img = img.convert('RGB')
            elif img.mode != 'RGB':
                img = img.convert('RGB')

            # Compress
            buf = io.BytesIO()
            img.save(buf, format='JPEG', quality=CONFIG["jpeg_quality"])
            size_kb = len(buf.getvalue()) / 1024

            if size_kb > CONFIG["max_image_size_kb"]:
                scale = (CONFIG["max_image_size_kb"] / size_kb) ** 0.5
                new_size = (int(img.width * scale), int(img.height * scale))
                img = img.resize(new_size, Image.Resampling.LANCZOS)
                buf = io.BytesIO()
                img.save(buf, format='JPEG', quality=CONFIG["jpeg_quality"])

            LOG.debug(f"Image: {len(buf.getvalue()) / 1024:.1f}KB")
            return buf.getvalue()

        except ImportError:
            with open(image_path, 'rb') as f:
                return f.read()

    @staticmethod
    def cleanup(image_path: Path):
        """Delete screenshot after analysis."""
        try:
            if image_path and image_path.exists():
                image_path.unlink()
        except Exception:
            pass


# =============================================================================
# SYSTEM INFO (Hardware Grounding)
# =============================================================================

class SystemInfo:
    """Get actual system information for grounding vision model."""

    _monitor_cache: Optional[List[dict]] = None
    _cache_time: float = 0

    @classmethod
    def get_monitors(cls) -> List[dict]:
        """Get connected monitors with rich EDID data (cached for 60s)."""
        now = time.time()
        if cls._monitor_cache is not None and (now - cls._cache_time) < 60:
            return cls._monitor_cache

        monitors = []

        # Try rich EDID detection first
        try:
            import sys
            try:
                from config.paths import AICORE_ROOT as _vcb_root
                sys.path.insert(0, str(_vcb_root))
            except ImportError:
                sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # tools/ -> opt/aicore
            from ui.adi_popup.monitor_detector import get_connected_monitors
            for m in get_connected_monitors():
                monitors.append({
                    "name": m.name,
                    "primary": m.is_primary,
                    "resolution": f"{m.width}x{m.height}",
                    "manufacturer": m.manufacturer,
                    "model": m.model,
                    "display_name": m.get_display_name(),
                    "refresh": m.refresh,
                    "physical_mm": f"{m.physical_width_mm}x{m.physical_height_mm}",
                    "x": m.x,
                    "y": m.y,
                })
        except Exception as e:
            LOG.debug(f"EDID monitor detection failed, falling back to xrandr: {e}")

        # Fallback to basic xrandr
        if not monitors:
            try:
                result = subprocess.run(
                    ["xrandr", "--query"],
                    capture_output=True, text=True, timeout=5
                )
                if result.returncode == 0:
                    import re
                    for line in result.stdout.split('\n'):
                        match = re.match(r'^(\S+)\s+connected\s*(primary)?\s*(\d+x\d+)?', line)
                        if match:
                            monitors.append({
                                "name": match.group(1),
                                "primary": match.group(2) == "primary",
                                "resolution": match.group(3) or "unknown",
                                "manufacturer": "",
                                "model": "",
                                "display_name": match.group(1),
                                "refresh": 60,
                                "physical_mm": "",
                                "x": 0,
                                "y": 0,
                            })
            except Exception as e:
                LOG.debug(f"xrandr failed: {e}")

        cls._monitor_cache = monitors
        cls._cache_time = now
        return monitors

    @classmethod
    def get_monitor_count(cls) -> int:
        """Get number of connected monitors."""
        return len(cls.get_monitors())

    @classmethod
    def get_monitor_info_text(cls) -> str:
        """Get human-readable monitor info for prompts."""
        monitors = cls.get_monitors()
        if not monitors:
            return ""

        if len(monitors) == 1:
            m = monitors[0]
            display = m.get("display_name", m["name"])
            return (
                f"WICHTIG - HARDWARE-FAKT: Es ist nur EIN EINZIGER Monitor angeschlossen "
                f"({display}, {m['name']}, {m['resolution']}). "
                f"Was du als 'mehrere Monitore' interpretierst, sind FENSTER auf EINEM Bildschirm. "
                f"Sage NIEMALS 'mehrere Monitore' oder 'multiple monitors'."
            )
        else:
            details = []
            for i, m in enumerate(monitors):
                display = m.get("display_name", m["name"])
                primary = " [PRIMARY]" if m.get("primary") else ""
                details.append(f"Monitor {i+1}: {display} ({m['name']}, {m['resolution']}{primary})")
            return f"HARDWARE-FAKT: Es sind {len(monitors)} Monitore angeschlossen:\n" + "\n".join(details)


# =============================================================================
# OCR ENGINE (Text Grounding)
# =============================================================================

class OCREngine:
    """OCR engine using tesseract for accurate text extraction.

    Used to ground vision model outputs and reduce hallucination.
    """

    @staticmethod
    def extract_text(image_path: Path) -> str:
        """Extract text from image using tesseract OCR."""
        try:
            import pytesseract
            from PIL import Image

            img = Image.open(image_path)
            # Use German + English for best results
            text = pytesseract.image_to_string(img, lang='deu+eng', config='--psm 3')
            text = text.strip()

            if text:
                LOG.debug(f"OCR extracted {len(text)} chars")
            return text

        except ImportError:
            LOG.warning("pytesseract not available for OCR")
            return ""
        except Exception as e:
            LOG.warning(f"OCR failed: {e}")
            return ""

    @staticmethod
    def extract_text_from_bytes(image_bytes: bytes) -> str:
        """Extract text from image bytes."""
        try:
            import pytesseract
            from PIL import Image
            import io

            img = Image.open(io.BytesIO(image_bytes))
            text = pytesseract.image_to_string(img, lang='deu+eng', config='--psm 3')
            return text.strip()

        except Exception as e:
            LOG.warning(f"OCR from bytes failed: {e}")
            return ""

    @staticmethod
    def get_window_titles(image_path: Path) -> List[str]:
        """Try to extract window titles from screenshot using targeted OCR."""
        try:
            import pytesseract
            from PIL import Image

            img = Image.open(image_path)
            width, height = img.size

            # Focus on top region where window titles usually are
            top_region = img.crop((0, 0, width, min(100, height // 5)))

            text = pytesseract.image_to_string(top_region, lang='deu+eng', config='--psm 6')

            # Extract likely window titles (lines with content)
            titles = [line.strip() for line in text.split('\n') if line.strip() and len(line.strip()) > 3]
            return titles[:5]  # Max 5 titles

        except Exception:
            return []


# =============================================================================
# LOCAL MOONDREAM VLM (ONLY BACKEND)
# =============================================================================

class LocalVisionVLM:
    """Local Vision VLM via Ollama - Frank's only vision backend.

    Uses LLaVA as primary (more reliable) with Moondream as fallback.
    """

    # Known hallucination patterns to correct (applied post-processing)
    HALLUCINATION_FIXES = [
        # LLaVA often mistakes multiple windows for multiple monitors
        (r"mehrere\s+(Monitore|Bildschirme|Displays)", "mehrere Fenster"),
        (r"multiple\s+(monitors|screens|displays)", "multiple windows"),
        (r"zwei\s+(Monitore|Bildschirme)", "zwei Fenster"),
        (r"three\s+(monitors|screens)", "multiple windows"),
        (r"dual[\s-]?monitor", "split-screen layout"),
        (r"multi[\s-]?monitor", "multi-window"),
        # German variations
        (r"verschiedenen\s+Monitoren", "verschiedenen Fenstern"),
        (r"auf\s+verschiedenen\s+Bildschirmen", "in verschiedenen Fenstern"),
        (r"Anzahl\s+der\s+Monitore", "Anzahl der Fenster"),
    ]

    def __init__(self):
        self.url = OLLAMA_URL
        self.models = OLLAMA_MODELS
        self.timeout = CONFIG["ollama_timeout_seconds"]
        self._available_models = None
        self._last_health_check = 0

    def _fix_known_hallucinations(self, text: str) -> str:
        """Fix known hallucination patterns in vision model output."""
        import re
        fixed = text
        for pattern, replacement in self.HALLUCINATION_FIXES:
            fixed = re.sub(pattern, replacement, fixed, flags=re.IGNORECASE)
        return fixed

    def caption_image(self, image_bytes: bytes, question: Optional[str] = None,
                      include_self_awareness: bool = False) -> Tuple[Optional[str], str]:
        """
        Get image caption using local vision model.

        Tries LLaVA first (more reliable), falls back to Moondream.

        Args:
            image_bytes: JPEG image bytes
            question: Optional question about the image
            include_self_awareness: If True, inject Frank's self-awareness context

        Returns:
            Tuple of (description, model_used) or (None, "") on failure
        """
        image_b64 = base64.b64encode(image_bytes).decode('utf-8')

        # Get actual monitor configuration for grounding
        monitor_info = SystemInfo.get_monitor_info_text()

        # Self-awareness context for desktop screenshots
        self_awareness = ""
        if include_self_awareness:
            try:
                from tools.frank_component_detector import get_self_awareness_context
                self_awareness = get_self_awareness_context()
            except Exception as e:
                LOG.debug(f"Self-awareness context failed: {e}")

        base_prompt = (
            "Beschreibe NUR was du tatsächlich siehst. Keine Vermutungen oder Erfindungen. "
            "Welche Fenster sind offen? Welcher Text ist lesbar? "
            "Sei kurz und faktisch. Antworte auf Deutsch."
        )

        # Build prompt with self-awareness + monitor grounding
        prompt_parts = []

        if self_awareness:
            prompt_parts.append(
                "Du bist Frank, ein KI-System. Du schaust auf deinen eigenen Desktop.\n\n"
                f"{self_awareness}\n\n"
                "Wenn du deine eigenen Komponenten siehst, benenne sie als DEINE "
                "(z.B. 'mein Chat-Overlay' statt 'ein Fenster')."
            )

        if monitor_info:
            prompt_parts.append(monitor_info)

        prompt_parts.append(question if question else base_prompt)

        prompt = "\n\n".join(prompt_parts)

        # Try each available model
        for model in self.models:
            if not self._is_model_available(model):
                continue

            payload = {
                "model": model,
                "prompt": prompt,
                "images": [image_b64],
                "stream": False,
                "options": {
                    "num_predict": 300,  # Shorter responses = less hallucination
                    "temperature": 0.1,  # Very low for factual output
                    "top_p": 0.5,        # More focused sampling
                }
            }

            try:
                data = json.dumps(payload).encode('utf-8')
                req = urllib.request.Request(
                    self.url, data=data,
                    headers={"Content-Type": "application/json"}
                )

                with urllib.request.urlopen(req, timeout=self.timeout) as response:
                    result = json.loads(response.read().decode('utf-8'))
                    text = result.get("response", "").strip()
                    if text:
                        # Fix known hallucinations before returning
                        text = self._fix_known_hallucinations(text)
                        LOG.info(f"Vision analysis successful with {model} ({len(text)} chars)")
                        return text, model
                    LOG.warning(f"{model} returned empty response")

            except urllib.error.URLError as e:
                LOG.warning(f"{model} connection failed: {e}")
            except Exception as e:
                LOG.warning(f"{model} error: {e}")

        LOG.error("All vision models failed")
        return None, ""

    def _is_model_available(self, model: str) -> bool:
        """Check if a specific model is available."""
        if self._available_models is None:
            self._refresh_available_models()
        return model in (self._available_models or [])

    def _refresh_available_models(self):
        """Refresh list of available models."""
        try:
            req = urllib.request.Request("http://localhost:11434/api/tags")
            with urllib.request.urlopen(req, timeout=CONFIG["ollama_health_timeout"]) as r:
                if r.status == 200:
                    data = json.loads(r.read().decode())
                    self._available_models = [m.get("name", "") for m in data.get("models", [])]
                    LOG.debug(f"Available Ollama models: {self._available_models}")
        except Exception as e:
            LOG.warning(f"Failed to get Ollama models: {e}")
            self._available_models = []

    def is_available(self) -> bool:
        """Check if Ollama with a vision model is running."""
        now = time.time()
        if now - self._last_health_check < 30 and self._available_models is not None:
            return any(m in (self._available_models or []) for m in self.models)

        self._last_health_check = now
        self._refresh_available_models()

        available = any(m in (self._available_models or []) for m in self.models)
        if not available:
            LOG.warning(f"No vision models found. Available: {self._available_models}, Need: {self.models}")
        return available


# =============================================================================
# UOLG INTEGRATION
# =============================================================================

class UOLGIntegration:
    """Integrates with UOLG for log correlation."""

    @staticmethod
    def get_concurrent_logs(window_sec: int = 5) -> List[dict]:
        """Get recent UOLG insights."""
        try:
            req = urllib.request.Request(f"{UOLG_API_URL}/insights")
            with urllib.request.urlopen(req, timeout=5) as r:
                data = json.loads(r.read().decode())
                return data.get("insights", [])[-10:]
        except Exception:
            return []

    @staticmethod
    def get_anomaly_score() -> float:
        """Get current anomaly score."""
        try:
            req = urllib.request.Request(f"{UOLG_API_URL}/status")
            with urllib.request.urlopen(req, timeout=5) as r:
                data = json.loads(r.read().decode())
                stats = data.get("statistics", {})
                alerts = stats.get("alerts", 0)
                investigations = stats.get("investigations", 0)
                return min(1.0, (alerts * 0.3 + investigations * 0.1))
        except Exception:
            return 0.0

    @staticmethod
    def get_recent_errors(limit: int = 5) -> List[str]:
        """Get recent error messages from UOLG status."""
        try:
            # Use /status endpoint which has recent_alerts
            req = urllib.request.Request(f"{UOLG_API_URL}/status")
            with urllib.request.urlopen(req, timeout=5) as r:
                data = json.loads(r.read().decode())

                errors = []

                # Get from troubled_entities
                for entity in data.get("troubled_entities", []):
                    top_event = entity.get("top_event", {})
                    event_class = top_event.get("event_class", "")
                    if "error" in event_class.lower() or "security" in event_class.lower():
                        desc = top_event.get("description", "")
                        if desc:
                            # Extract first line only (before OCR section)
                            first_line = desc.split('\n')[0][:100]
                            errors.append(f"[{entity.get('entity', '?')}] {first_line}")

                # Get from recent_alerts
                for alert in data.get("recent_alerts", [])[:limit]:
                    event_class = alert.get("event_class", "")
                    entity = alert.get("entity", "System")
                    hypotheses = alert.get("hypotheses", [])
                    if hypotheses:
                        top_cause = hypotheses[0].get("cause", "Unknown").replace("_", " ")
                        errors.append(f"[{entity}] {event_class}: {top_cause}")

                return errors[:limit]
        except Exception as e:
            LOG.debug(f"Failed to get UOLG errors: {e}")
            return []

    @staticmethod
    def ingest_visual_insight(description: str, confidence: float = 0.8, context: str = ""):
        """Send visual insight to UOLG."""
        try:
            insight = {
                "time": datetime.now().isoformat(),
                "entity": "Visual_Observation",
                "event_class": "Visual_Evidence",
                "hypotheses": [
                    {"cause": "Visual_Confirmation", "weight": confidence},
                    {"cause": "Partial_Observation", "weight": 1.0 - confidence}
                ],
                "confidence": confidence,
                "actionability": "observe",
                "intrusive_methods_used": False,
                "correlation_ids": [],
                "description": f"{context}\n{description}" if context else description[:500],
            }

            body = json.dumps({"insight": insight}).encode()
            req = urllib.request.Request(
                f"{UOLG_API_URL}/ingest",
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            urllib.request.urlopen(req, timeout=5)
        except Exception:
            pass


# =============================================================================
# MAIN VCB CLASS
# =============================================================================

class VisualCausalBridge:
    """
    Main VCB class - Frank's Eyes (Local Only).

    Uses hybrid OCR + Vision for accurate screen understanding.
    - OCR provides accurate text extraction (grounding)
    - Vision model provides layout/element descriptions
    No external API dependencies.
    """

    def __init__(self):
        self.rate_limiter = RateLimiter()
        self.gaming_guard = GamingModeGuard()
        self.capture = ScreenCapture()
        self.moondream = LocalVisionVLM()  # Name kept for compatibility
        self.ocr = OCREngine()
        self.uolg = UOLGIntegration()

        # Ensure error screenshot directory exists
        ERROR_SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)

    def _analyze_image(self, image_bytes: bytes, question: Optional[str] = None,
                       screenshot_path: Optional[Path] = None,
                       is_screenshot: bool = False) -> Tuple[Optional[str], str]:
        """
        Analyze image with hybrid OCR + Vision approach.

        1. Extract text via OCR (accurate grounding)
        2. Use vision model for layout/element understanding
        3. Combine results for accurate description

        Args:
            image_bytes: JPEG image bytes
            question: Optional question about the image
            screenshot_path: Original screenshot path for OCR
            is_screenshot: If True, include self-awareness context in prompt

        Returns:
            Tuple of (description, model_used)
        """
        # Step 1: Extract text via OCR (accurate grounding)
        ocr_text = ""
        window_titles = []

        if screenshot_path and screenshot_path.exists():
            ocr_text = self.ocr.extract_text(screenshot_path)
            window_titles = self.ocr.get_window_titles(screenshot_path)
        else:
            ocr_text = self.ocr.extract_text_from_bytes(image_bytes)

        # Build grounding context from OCR
        ocr_context = ""
        if window_titles:
            ocr_context += f"Erkannte Fenstertitel: {', '.join(window_titles[:3])}\n"
        if ocr_text:
            # Limit OCR text to prevent prompt overflow
            ocr_preview = ocr_text[:500].replace('\n', ' ').strip()
            if ocr_preview:
                ocr_context += f"Erkannter Text (OCR): {ocr_preview}...\n"

        # Step 2: Vision model analysis (with OCR grounding)
        if not self.moondream.is_available():
            # Fallback to OCR-only if no vision model
            if ocr_context:
                LOG.info("VCB: Using OCR-only (no vision model available)")
                return f"[OCR-Analyse]\n{ocr_context}", "ocr_only"
            LOG.error("Neither vision model nor OCR available")
            return None, ""

        LOG.info("VCB: Analyzing with hybrid OCR + Vision...")

        # Build vision prompt with OCR grounding
        if ocr_context:
            grounded_prompt = (
                f"OCR hat bereits folgenden Text erkannt:\n{ocr_context}\n\n"
                "Beschreibe NUR was du WIRKLICH siehst. "
                "Erfinde KEINE Details die nicht sichtbar sind. "
                "Welche Fenster/Programme sind offen? Beschreibe das Layout kurz."
            )
            if question:
                grounded_prompt += f"\n\nFrage: {question}"
        else:
            grounded_prompt = question if question else (
                "Beschreibe NUR was du tatsächlich siehst. Keine Vermutungen."
            )

        vision_desc, model = self.moondream.caption_image(
            image_bytes, grounded_prompt, include_self_awareness=is_screenshot
        )

        # Get verified system info
        monitor_count = SystemInfo.get_monitor_count()
        monitor_info = f"🖥️ System: {monitor_count} Monitor(e) angeschlossen" if monitor_count > 0 else ""

        # Step 3: Combine results
        if vision_desc and ocr_context:
            # Hybrid result with disclaimer
            combined = (
                f"{vision_desc}\n\n"
                f"---\n"
                f"📋 OCR-verifizierter Text:\n{ocr_context.strip()}\n"
            )
            if monitor_info:
                combined += f"{monitor_info}\n"
            combined += f"⚠️ Hinweis: Lokales Vision-Modell kann ungenau sein. OCR-Text und System-Info sind verifiziert."
            return combined, f"{model}+ocr"
        elif vision_desc:
            suffix = f"\n\n{monitor_info}\n" if monitor_info else "\n\n"
            suffix += "⚠️ Hinweis: Lokales 7B Vision-Modell - Details können ungenau sein."
            return f"{vision_desc}{suffix}", model
        elif ocr_context:
            result = f"[OCR-Analyse]\n{ocr_context}"
            if monitor_info:
                result += f"\n{monitor_info}"
            return result, "ocr_only"

        LOG.error("VCB: Both vision and OCR failed")
        return None, ""

    def take_screenshot(self, query: Optional[str] = None) -> Optional[VisualEvidence]:
        """
        Take and analyze screenshot.

        Args:
            query: Optional question about the screen

        Returns:
            VisualEvidence with description and metadata
        """
        # Check gaming mode
        if self.gaming_guard.is_gaming():
            LOG.warning("VCB disabled in gaming mode")
            return None

        # Check rate limits and loop protection
        can_proceed, reason = self.rate_limiter.can_proceed()
        if not can_proceed:
            LOG.warning(f"Rate limit: {reason}")
            return None

        start_time = time.time()
        timestamp = datetime.now()

        # Capture screenshot
        screenshot_path = self.capture.capture()
        if not screenshot_path:
            LOG.error("Screenshot capture failed")
            self.rate_limiter.record_failure()
            return None

        try:
            # Compress for inference
            image_bytes = self.capture.compress_if_needed(screenshot_path)

            # Analyze with hybrid OCR + Vision (pass original path for OCR)
            # is_screenshot=True enables self-awareness context in the vision prompt
            description, model = self._analyze_image(
                image_bytes, query, screenshot_path, is_screenshot=True
            )

            if not description:
                self.rate_limiter.record_failure()
                return None

            # Record success
            self.rate_limiter.record_request()

            # Get correlated logs
            correlated_logs = self.uolg.get_concurrent_logs()

            # Create evidence
            evidence = VisualEvidence(
                timestamp=timestamp,
                description=description,
                confidence=CONFIG["default_confidence"],
                correlated_logs=correlated_logs,
                model_used=model,
                backend="moondream_local",
                processing_time_sec=time.time() - start_time,
            )

            # Send to UOLG
            self.uolg.ingest_visual_insight(description)

            LOG.info(f"VCB: Analysis complete ({evidence.processing_time_sec:.1f}s)")
            return evidence

        finally:
            self.capture.cleanup(screenshot_path)

    def analyze_image_file(self, image_path: str, question: Optional[str] = None,
                           is_screenshot: bool = False) -> Optional[VisualEvidence]:
        """Analyze an image file."""
        # Check gaming mode
        if self.gaming_guard.is_gaming():
            LOG.warning("VCB disabled in gaming mode")
            return None

        # Check rate limits
        can_proceed, reason = self.rate_limiter.can_proceed()
        if not can_proceed:
            LOG.warning(f"Rate limit: {reason}")
            return None

        path = Path(image_path)
        if not path.exists():
            LOG.error(f"Image not found: {image_path}")
            return None

        start_time = time.time()
        timestamp = datetime.now()

        try:
            # Compress
            image_bytes = self.capture.compress_if_needed(path)

            # Analyze with hybrid OCR + Vision
            description, model = self._analyze_image(
                image_bytes, question, path, is_screenshot=is_screenshot
            )

            if not description:
                self.rate_limiter.record_failure()
                return None

            # Record success
            self.rate_limiter.record_request()

            return VisualEvidence(
                timestamp=timestamp,
                description=description,
                confidence=CONFIG["default_confidence"],
                correlated_logs=[],
                model_used=model,
                backend="moondream_local",
                processing_time_sec=time.time() - start_time,
            )

        except Exception as e:
            LOG.error(f"Image analysis failed: {e}")
            self.rate_limiter.record_failure()
            return None

    def capture_error_screenshot(self, error_context: str = "") -> Optional[dict]:
        """
        Capture screenshot for error analysis.

        Used to understand system state during errors.
        Has separate rate limiting to prevent spam.

        Args:
            error_context: Description of the error that triggered this

        Returns:
            Dict with screenshot path and analysis, or None if blocked
        """
        # Check if we can take an error screenshot
        can_proceed, reason = self.rate_limiter.can_error_screenshot()
        if not can_proceed:
            LOG.debug(f"Error screenshot blocked: {reason}")
            return None

        # Check gaming mode
        if self.gaming_guard.is_gaming():
            return None

        timestamp = datetime.now()
        screenshot_filename = f"error_{timestamp.strftime('%Y%m%d_%H%M%S')}.png"
        screenshot_path = ERROR_SCREENSHOT_DIR / screenshot_filename

        # Capture screenshot
        captured_path = self.capture.capture(screenshot_path)
        if not captured_path:
            return None

        # Record that we took an error screenshot
        self.rate_limiter.record_error_screenshot()

        try:
            # Compress for analysis
            image_bytes = self.capture.compress_if_needed(captured_path)

            # Analyze with error-specific prompt (using hybrid OCR + Vision)
            error_prompt = (
                f"Ein Fehler ist aufgetreten: {error_context}\n\n"
                "Beschreibe was auf dem Bildschirm zu sehen ist. "
                "Achte besonders auf: Fehlermeldungen, Dialoge, Warnungen, "
                "ungewöhnliche Zustände oder Hinweise auf das Problem."
            )

            description, model = self._analyze_image(image_bytes, error_prompt, captured_path)

            # Get recent error logs
            recent_errors = self.uolg.get_recent_errors()

            # Send to UOLG with error context
            if description:
                self.uolg.ingest_visual_insight(
                    description,
                    confidence=0.7,
                    context=f"Error Screenshot: {error_context}"
                )

            # Build structured result with clear OCR/Vision separation
            result = {
                "timestamp": timestamp.isoformat(),
                "screenshot_path": str(captured_path),
                "error_context": error_context,
                "visual_description": description or "Analysis failed",
                "recent_log_errors": recent_errors,
                "model_used": model,
                # Flag to indicate hybrid analysis was used
                "ocr_grounded": "+ocr" in model if model else False,
            }

            # Add correlation summary for easier debugging
            if recent_errors:
                result["log_correlation_summary"] = (
                    f"UOLG meldet {len(recent_errors)} relevante Events. "
                    f"Screenshot-Analyse mit {'OCR-Grounding' if result['ocr_grounded'] else 'Vision-only'}."
                )

            LOG.info(f"Error screenshot captured: {screenshot_path} (OCR grounded: {result['ocr_grounded']})")
            return result

        except Exception as e:
            LOG.error(f"Error screenshot analysis failed: {e}")
            return {
                "timestamp": timestamp.isoformat(),
                "screenshot_path": str(captured_path),
                "error_context": error_context,
                "visual_description": f"Analysis failed: {e}",
                "recent_log_errors": [],
                "model_used": "",
            }

    def cleanup_old_error_screenshots(self):
        """Delete error screenshots older than retention period."""
        try:
            cutoff = time.time() - (CONFIG["error_screenshot_retention_hours"] * 3600)
            for f in ERROR_SCREENSHOT_DIR.glob("error_*.png"):
                if f.stat().st_mtime < cutoff:
                    f.unlink()
                    LOG.debug(f"Deleted old error screenshot: {f}")
        except Exception as e:
            LOG.warning(f"Error cleaning up screenshots: {e}")

    def visual_audit(self, anomaly_score: Optional[float] = None) -> Optional[VisualEvidence]:
        """Trigger visual audit based on anomaly score."""
        if anomaly_score is None:
            anomaly_score = self.uolg.get_anomaly_score()

        if anomaly_score < 0.85:
            LOG.debug(f"Anomaly score {anomaly_score:.2f} below threshold")
            return None

        LOG.info(f"Visual audit triggered (anomaly={anomaly_score:.2f})")
        return self.take_screenshot(
            query="Beschreibe alle Fehlermeldungen, Warnungen oder Probleme die sichtbar sind"
        )

    def get_status(self) -> dict:
        """Get VCB status."""
        stats = self.rate_limiter.get_stats()
        return {
            "enabled": not self.gaming_guard.is_gaming(),
            "gaming_mode": self.gaming_guard.is_gaming(),
            "backend": "moondream_local",
            "moondream_available": self.moondream.is_available(),
            "external_api": False,  # No external APIs used
            **stats,
        }


# =============================================================================
# SINGLETON & PUBLIC API
# =============================================================================

_vcb: Optional[VisualCausalBridge] = None
_vcb_lock = threading.Lock()


def get_vcb() -> VisualCausalBridge:
    """Get singleton VCB instance (thread-safe)."""
    global _vcb
    if _vcb is None:
        with _vcb_lock:
            if _vcb is None:
                _vcb = VisualCausalBridge()
    return _vcb


def take_screenshot(query: Optional[str] = None) -> Optional[dict]:
    """Take and analyze screenshot."""
    evidence = get_vcb().take_screenshot(query)
    return evidence.to_dict() if evidence else None


def analyze_screen(question: str = "Beschreibe was auf dem Bildschirm zu sehen ist") -> Optional[str]:
    """Simple interface: analyze screen, return description."""
    evidence = get_vcb().take_screenshot(question)
    return evidence.description if evidence else None


def analyze_image(image_path: str, question: Optional[str] = None,
                   is_screenshot: bool = False) -> Optional[str]:
    """Analyze an image file."""
    evidence = get_vcb().analyze_image_file(image_path, question, is_screenshot=is_screenshot)
    return evidence.description if evidence else None


def capture_error_screenshot(error_context: str = "") -> Optional[dict]:
    """Capture screenshot for error analysis (with spam protection)."""
    return get_vcb().capture_error_screenshot(error_context)


def visual_audit(anomaly_score: Optional[float] = None) -> Optional[dict]:
    """Trigger visual audit based on anomaly."""
    evidence = get_vcb().visual_audit(anomaly_score)
    return evidence.to_dict() if evidence else None


def vcb_status() -> dict:
    """Get VCB status and statistics."""
    return get_vcb().get_status()


def cleanup_error_screenshots():
    """Cleanup old error screenshots."""
    get_vcb().cleanup_old_error_screenshots()


# Compatibility aliases for existing code
_analyze_with_moondream = analyze_screen
_analyze_with_vcb = analyze_screen
_analyze_image_with_moondream = analyze_image
_analyze_image_with_vcb = analyze_image


# =============================================================================
# CLI
# =============================================================================

def main():
    """CLI entry point."""
    import argparse
    parser = argparse.ArgumentParser(description="Visual-Causal-Bridge (VCB) v3.0 - Local Only")
    parser.add_argument("--screenshot", action="store_true", help="Take and analyze screenshot")
    parser.add_argument("--query", type=str, help="Question about the screen/image")
    parser.add_argument("--image", type=str, help="Analyze image file")
    parser.add_argument("--error", type=str, help="Capture error screenshot with context")
    parser.add_argument("--audit", action="store_true", help="Trigger visual audit")
    parser.add_argument("--status", action="store_true", help="Show VCB status")
    parser.add_argument("--cleanup", action="store_true", help="Cleanup old error screenshots")
    args = parser.parse_args()

    if args.status:
        status = vcb_status()
        print(json.dumps(status, indent=2))
        return

    if args.cleanup:
        cleanup_error_screenshots()
        print("Cleanup complete")
        return

    if args.error:
        result = capture_error_screenshot(args.error)
        if result:
            print(json.dumps(result, indent=2))
        else:
            print("Error screenshot blocked (rate limit or gaming mode)")
        return

    if args.image:
        result = analyze_image(args.image, args.query)
        if result:
            print(f"Description: {result}")
        else:
            print("Analysis failed")
        return

    if args.audit:
        result = visual_audit()
        if result:
            print(json.dumps(result, indent=2))
        else:
            print("No visual audit needed")
        return

    if args.screenshot or args.query:
        result = take_screenshot(args.query)
        if result:
            print(f"Backend: {result['backend']}")
            print(f"Model: {result['model_used']}")
            print(f"Time: {result['processing_time_sec']}s")
            print(f"Description: {result['description']}")
        else:
            print("Screenshot analysis failed")
        return

    # Default: show status
    status = vcb_status()
    print("VCB Status v3.0 (Local Only):")
    print(f"  Enabled: {status['enabled']}")
    print(f"  Gaming Mode: {status['gaming_mode']}")
    print(f"  Backend: Moondream Local (available: {status['moondream_available']})")
    print(f"  External APIs: None")
    print(f"  Today's Usage: {status['daily_count']}/{status['daily_limit']}")
    print(f"  Consecutive Failures: {status['consecutive_failures']}")
    print(f"  Error Screenshots This Hour: {status['error_screenshots_this_hour']}")
    print(f"  Total Analyses: {status['total_analyses']}")


if __name__ == "__main__":
    main()
