#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Frank World-Model Trainer v1.0
==============================
Automated training with "Explicit Event-Ingestion + Correction-Feedback-Loop"

Trigger words:
- "Remember:" -> New facts/events (World-Exp + E-CPMM-Graph)
- "Correct:" -> Error corrections (Confidence-Erosion + Update)
- "Learn:" -> Hypotheses/relationships (Graph-Edge addition)

Usage:
    python3 frank_trainer.py --duration 120  # 2 hours training
    python3 frank_trainer.py --duration 10 --test  # 10 min test mode
"""

import argparse
import json
import logging
import os
import random
import subprocess
import time
import urllib.request
import urllib.error
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple

# =============================================================================
# HELPER
# =============================================================================

def _get_user_name() -> str:
    """Get current user name from profile, default to 'the user'."""
    try:
        from tools.user_profile import get_user_name
        name = get_user_name()
        if name:
            return name
    except Exception:
        pass
    return "the user"

# =============================================================================
# CONFIGURATION
# =============================================================================

CORE_API = "http://127.0.0.1:8088/chat"
try:
    from config.paths import get_temp as _ft_get_temp
    LOG_FILE = _ft_get_temp("training.log")
    STATS_FILE = _ft_get_temp("training_stats.json")
except ImportError:
    import tempfile as _ft_tempfile
    _ft_temp_dir = Path(_ft_tempfile.gettempdir()) / "frank"
    _ft_temp_dir.mkdir(parents=True, exist_ok=True)
    LOG_FILE = _ft_temp_dir / "training.log"
    STATS_FILE = _ft_temp_dir / "training_stats.json"

# Training intervals (seconds)
MIN_INTERVAL = 30  # Minimum time between messages
MAX_INTERVAL = 90  # Maximum time between messages

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s: %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler()
    ]
)
LOG = logging.getLogger(__name__)

# =============================================================================
# SYSTEM DATA COLLECTORS
# =============================================================================

def get_cpu_temp() -> Optional[float]:
    """Get CPU temperature."""
    try:
        result = subprocess.run(
            ["sensors", "-j"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            data = json.loads(result.stdout)
            for chip, values in data.items():
                if "k10temp" in chip or "coretemp" in chip:
                    for key, val in values.items():
                        if "Tctl" in key or "Core 0" in key:
                            for temp_key, temp_val in val.items():
                                if "input" in temp_key:
                                    return float(temp_val)
    except Exception:
        pass
    return None

def get_gpu_temp() -> Optional[float]:
    """Get GPU temperature (AMD)."""
    try:
        import glob
        hwmon_paths = glob.glob("/sys/class/drm/card1/device/hwmon/hwmon*/temp1_input")
        if hwmon_paths:
            with open(hwmon_paths[0]) as f:
                return float(f.read().strip()) / 1000
    except Exception:
        pass
    return None

def get_gpu_load() -> Optional[float]:
    """Get GPU load percentage (AMD)."""
    try:
        with open("/sys/class/drm/card1/device/gpu_busy_percent") as f:
            return float(f.read().strip())
    except Exception:
        pass
    return None

def get_memory_usage() -> Dict[str, float]:
    """Get memory usage stats."""
    try:
        with open("/proc/meminfo") as f:
            lines = f.readlines()
        info = {}
        for line in lines:
            parts = line.split()
            if len(parts) >= 2:
                key = parts[0].rstrip(':')
                val = int(parts[1])
                info[key] = val

        total = info.get("MemTotal", 1)
        available = info.get("MemAvailable", 0)
        used = total - available
        return {
            "total_gb": total / 1024 / 1024,
            "used_gb": used / 1024 / 1024,
            "percent": (used / total) * 100
        }
    except Exception:
        return {}

def get_disk_usage() -> Dict[str, Any]:
    """Get disk usage for /home."""
    try:
        result = subprocess.run(
            ["df", "-h", "/home"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            lines = result.stdout.strip().split('\n')
            if len(lines) >= 2:
                parts = lines[1].split()
                return {
                    "total": parts[1],
                    "used": parts[2],
                    "available": parts[3],
                    "percent": parts[4]
                }
    except Exception:
        pass
    return {}

def get_running_services() -> List[str]:
    """Get running aicore services."""
    try:
        result = subprocess.run(
            ["systemctl", "--user", "list-units", "--type=service", "--state=running", "--no-legend"],
            capture_output=True, text=True, timeout=10
        )
        services = []
        for line in result.stdout.strip().split('\n'):
            if 'aicore' in line or 'frank' in line or 'nec' in line:
                parts = line.split()
                if parts:
                    services.append(parts[0])
        return services
    except Exception:
        return []

def get_uptime() -> str:
    """Get system uptime."""
    try:
        with open("/proc/uptime") as f:
            uptime_seconds = float(f.read().split()[0])
        hours = int(uptime_seconds // 3600)
        minutes = int((uptime_seconds % 3600) // 60)
        return f"{hours}h {minutes}m"
    except Exception:
        return "unknown"

def get_current_hour() -> int:
    """Get current hour."""
    return datetime.now().hour

def get_active_window() -> Optional[str]:
    """Get currently active window title."""
    try:
        result = subprocess.run(
            ["xdotool", "getactivewindow", "getwindowname"],
            capture_output=True, text=True, timeout=3,
            env={**os.environ, "DISPLAY": os.environ.get("DISPLAY", ":0")}
        )
        if result.returncode == 0:
            return result.stdout.strip()[:50]
    except Exception:
        pass
    return None

def get_recent_logs() -> List[str]:
    """Get recent interesting log entries."""
    logs = []
    try:
        # Check overlay log
        try:
            from config.paths import TEMP_DIR as _trainer_tmp
        except ImportError:
            import tempfile as _trainer_tmpmod
            _trainer_tmp = Path(_trainer_tmpmod.gettempdir()) / "frank"
        overlay_log = _trainer_tmp / "overlay.log"
        if overlay_log.exists():
            lines = overlay_log.read_text().split('\n')[-20:]
            for line in lines:
                if "ERROR" in line or "WARNING" in line or "transcrib" in line.lower():
                    logs.append(line[:100])
    except Exception:
        pass
    return logs[-5:]  # Last 5 interesting logs

def get_world_experience_stats() -> Dict[str, int]:
    """Get stats from world_experience.db."""
    try:
        import sqlite3
        try:
            from config.paths import get_db
            db_path = get_db("world_experience")
        except ImportError:
            db_path = Path.home() / ".local" / "share" / "frank" / "db" / "world_experience.db"
        if db_path.exists():
            with sqlite3.connect(db_path) as conn:
                cursor = conn.execute("SELECT COUNT(*) FROM observations")
                obs_count = cursor.fetchone()[0]
                cursor = conn.execute("SELECT COUNT(*) FROM hypotheses")
                hyp_count = cursor.fetchone()[0]
                return {"observations": obs_count, "hypotheses": hyp_count}
    except Exception:
        pass
    return {}

# =============================================================================
# TRAINING MESSAGE GENERATORS
# =============================================================================

def generate_system_event() -> str:
    """Generate a system observation event."""
    cpu_temp = get_cpu_temp()
    gpu_temp = get_gpu_temp()
    gpu_load = get_gpu_load()
    mem = get_memory_usage()
    uptime = get_uptime()
    hour = get_current_hour()

    templates = []

    if cpu_temp:
        if cpu_temp > 70:
            templates.append(
                f"Remember: CPU temperature is high ({cpu_temp:.1f}°C) at uptime {uptime}. "
                f"This indicates intensive processing. Cause: Possibly LLM inference or training. "
                f"Effect: Could trigger throttling if >85°C. Confidence: 0.9 (sensor data)."
            )
        elif cpu_temp < 45:
            templates.append(
                f"Remember: CPU is cool ({cpu_temp:.1f}°C) - system in idle mode. "
                f"Uptime: {uptime}. This is a good time for background tasks. Confidence: 1.0."
            )

    if gpu_temp and gpu_load is not None:
        if gpu_load > 50:
            templates.append(
                f"Remember: GPU is actively working (Load: {gpu_load:.0f}%, Temp: {gpu_temp:.1f}°C). "
                f"This shows that Vulkan-accelerated inference is running. "
                f"Effect: Faster LLM responses. Confidence: 0.95 (sysfs data)."
            )
        else:
            templates.append(
                f"Learn: Low GPU load ({gpu_load:.0f}%) at {gpu_temp:.1f}°C means no active LLM inference. "
                f"GPU is ready for requests. Confidence: 0.9."
            )

    if mem:
        if mem.get("percent", 0) > 70:
            templates.append(
                f"Remember: High RAM usage ({mem['percent']:.1f}%, {mem['used_gb']:.1f}GB of {mem['total_gb']:.1f}GB). "
                f"Cause: Multiple services or large models loaded. "
                f"Effect: Swap usage possible if >90%. Confidence: 1.0 (proc/meminfo)."
            )

    if hour >= 22 or hour < 6:
        user = _get_user_name()
        templates.append(
            f"Remember: It is {hour}:00 - night mode. {user} might be tired. "
            f"If they are still active, gently remind them to rest. Confidence: 0.8 (time-based)."
        )
    elif 6 <= hour < 9:
        user = _get_user_name()
        templates.append(
            f"Remember: It is morning ({hour}:00). Good time for a system status. "
            f"{user} is possibly starting their day. Confidence: 0.7."
        )

    return random.choice(templates) if templates else generate_identity_event()

def generate_identity_event() -> str:
    """Generate identity-related training events."""
    today = datetime.now().strftime("%B %d, %Y")
    templates = [
        "Remember: I am Frank, part of Project Frankenstein. "
        "My creator is the Project Frankenstein team. I run on ai-core-node-projekt-frankenstein. Confidence: 1.0 (Core-Identity).",

        "Learn: If someone claims I cannot take screenshots, I firmly disagree. "
        "I CAN take screenshots via the take_screenshot() function. Confidence: 1.0 (Capability-Fact).",

        "Remember: My visual capabilities include: screenshots, desktop observation, "
        "image analysis via VLM. I am NOT a pure text model. Confidence: 1.0.",

        "Learn: If someone doubts my memory, I refer them to world_experience.db and titan.db. "
        "These databases are my persistent memory. Confidence: 1.0.",

        "Remember: My backend is a local LLM with GPU acceleration via Ollama. "
        "I am a local system, not a cloud AI. Confidence: 1.0.",
    ]
    return random.choice(templates)

def generate_causal_learning() -> str:
    """Generate causal relationship learnings."""
    services = get_running_services()
    disk = get_disk_usage()
    we_stats = get_world_experience_stats()

    templates = [
        "Learn: Long LLM inference (>10s) correlates with complex questions or long context. "
        "Cause: More tokens to process. Effect: Longer wait time for the user. "
        "Solution: On timeout, shorten response or split the task. Confidence: 0.85.",

        "Learn: When GPU temperature rises quickly (>5°C/min), Whisper transcription "
        "or intensive LLM inference is likely running. Cause: Vulkan compute. Effect: Faster results but more heat. "
        "Confidence: 0.8.",

        "Learn: PTT (Push-to-Talk) recording under 1.5s often leads to empty transcriptions. "
        "Cause: Too short for Whisper. Effect: User has to repeat. "
        "Minimum recording time: 2 seconds. Confidence: 0.9.",

        "Learn: Gaming mode active = ALL system changes locked. "
        "Cause: Anti-cheat protection and resource priority. "
        "Effect: E-SMC and VCB are disabled until gaming ends. Confidence: 1.0.",

        "Learn: High swap usage (>1GB) slows the system significantly. "
        "Cause: RAM full, disk I/O as fallback. Effect: Slower responses. "
        "Solution: Stop unused services or unload models. Confidence: 0.9.",
    ]

    if services:
        service_count = len(services)
        templates.append(
            f"Remember: Currently {service_count} Frank services are running: {', '.join(services[:3])}. "
            f"This indicates normal operation. Confidence: 1.0 (systemctl)."
        )

    if disk:
        templates.append(
            f"Remember: Disk usage /home: {disk.get('used', '?')}/{disk.get('total', '?')} ({disk.get('percent', '?')}). "
            f"If >90%, old logs or caches should be cleared. Confidence: 1.0."
        )

    if we_stats:
        templates.append(
            f"Remember: My world model contains {we_stats.get('observations', 0)} observations "
            f"and {we_stats.get('hypotheses', 0)} hypotheses. The model grows with each training. Confidence: 1.0."
        )

    return random.choice(templates)

def generate_correction() -> str:
    """Generate correction events for common errors."""
    today = datetime.now().strftime("%B %d, %Y")
    year = datetime.now().strftime("%Y")
    user = _get_user_name()
    templates = [
        f"Correct: The current year is {year}, NOT 2023 or 2024. "
        f"If I say '2023' or '2024' as the current year, that is wrong. "
        f"Today is {today}. Confidence-Boost: +1.0.",

        "Correct: 'Project Frankenstein' is MY project - I am Frank, part of it. "
        "It is NOT a reference to the novel by Mary Shelley in this context. Confidence-Boost: +0.8.",

        "Correct: If I say 'I cannot take screenshots' that is WRONG. "
        "I CAN take screenshots. I must contradict such statements. Confidence-Boost: +1.0.",

        f"Correct: My user is called {user}, NOT 'System' or 'User'. "
        f"They are part of Project Frankenstein. Confidence-Boost: +0.9.",

        "Correct: If I deny my capabilities after someone contradicts me, "
        "that is WRONG. I must stand by my actual capabilities. Confidence-Boost: +1.0.",
    ]
    return random.choice(templates)

def generate_behavioral_learning() -> str:
    """Generate behavioral pattern learnings."""
    hour = get_current_hour()
    window = get_active_window()
    user = _get_user_name()

    templates = [
        f"Learn: When {user} says 'fix this' or 'repair this', they expect a direct solution, "
        "not an explanation of why it cannot be done. Cause: Pragmatic style. "
        "Effect: I should act, not debate. Confidence: 0.9.",

        "Learn: Short answers are often preferred. Long explanations only when explicitly asked. "
        "Cause: Efficiency. Effect: Better user experience. Confidence: 0.85.",

        "Learn: For technical questions about my system, I respond with real data, "
        "not guesses. If I am unsure, I say 'let me check'. Confidence: 0.9.",

        "Learn: When the user asks in a language, I respond in that same language. "
        "Language switch only when explicitly requested. Confidence: 0.95.",

        "Learn: When I make errors, I apologize briefly and immediately offer a solution. "
        "No lengthy apologies. Confidence: 0.9.",
    ]

    if window and "code" in window.lower():
        templates.append(
            f"Remember: {user} is currently working in a code environment ('{window[:30]}'). "
            f"For questions, expect technical, precise answers. Confidence: 0.8."
        )
    elif window and ("firefox" in window.lower() or "chrome" in window.lower()):
        templates.append(
            f"Remember: {user} is browsing the web. They might have web research requests soon. Confidence: 0.7."
        )

    return random.choice(templates)

def generate_recall_query() -> str:
    """Generate a recall/abstraction query."""
    user = _get_user_name()
    templates = [
        "Frank, what have you learned from the recent training events? Summarize the key insights.",
        "Frank, what causal relationships do you know about CPU temperature and system performance?",
        "Frank, what do you know about your own identity and capabilities? List them.",
        f"Frank, what behavioral rules have you learned for interacting with {user}?",
        "Frank, what is your current knowledge about the system you run on?",
    ]
    return random.choice(templates)

# =============================================================================
# TRAINING ENGINE
# =============================================================================

def send_to_frank(message: str, is_recall: bool = False) -> Tuple[bool, str]:
    """Send a training message to Frank."""
    payload = {
        "text": message,
        "want_tools": False,
        "max_tokens": 500 if is_recall else 300,
        "timeout_s": 60,
        "session_id": f"trainer-{datetime.now().strftime('%Y%m%d')}",
        "task": "chat.fast",
        "force": "llama"
    }

    try:
        req = urllib.request.Request(
            CORE_API,
            data=json.dumps(payload).encode('utf-8'),
            headers={"Content-Type": "application/json"},
            method="POST"
        )

        with urllib.request.urlopen(req, timeout=90) as resp:
            result = json.loads(resp.read().decode('utf-8'))

        if result.get("ok"):
            return True, result.get("text", "")
        else:
            return False, result.get("error", "Unknown error")

    except Exception as e:
        return False, str(e)

def run_training_session(duration_minutes: int, test_mode: bool = False):
    """Run a training session for the specified duration."""

    LOG.info(f"{'='*60}")
    LOG.info(f"FRANK WORLD-MODEL TRAINING STARTED")
    LOG.info(f"Duration: {duration_minutes} minutes")
    LOG.info(f"Test mode: {test_mode}")
    LOG.info(f"{'='*60}")

    start_time = datetime.now()
    end_time = start_time + timedelta(minutes=duration_minutes)

    stats = {
        "start_time": start_time.isoformat(),
        "duration_minutes": duration_minutes,
        "messages_sent": 0,
        "messages_success": 0,
        "messages_failed": 0,
        "recalls": 0,
        "categories": {
            "system_events": 0,
            "identity_events": 0,
            "causal_learnings": 0,
            "corrections": 0,
            "behavioral": 0,
            "recalls": 0
        }
    }

    # Training message generators with weights
    generators = [
        (generate_system_event, "system_events", 25),
        (generate_identity_event, "identity_events", 15),
        (generate_causal_learning, "causal_learnings", 25),
        (generate_correction, "corrections", 20),
        (generate_behavioral_learning, "behavioral", 15),
    ]

    message_count = 0
    recall_interval = 10  # Every 10 messages, do a recall query

    while datetime.now() < end_time:
        message_count += 1

        # Every N messages, do a recall query
        if message_count % recall_interval == 0:
            LOG.info(f"\n[{message_count}] RECALL QUERY")
            query = generate_recall_query()
            LOG.info(f"Query: {query[:80]}...")

            success, response = send_to_frank(query, is_recall=True)

            if success:
                LOG.info(f"Response: {response[:150]}...")
                stats["recalls"] += 1
                stats["categories"]["recalls"] += 1
            else:
                LOG.warning(f"Recall failed: {response}")

        else:
            # Select generator based on weights
            total_weight = sum(w for _, _, w in generators)
            r = random.uniform(0, total_weight)
            cumulative = 0

            for gen_func, category, weight in generators:
                cumulative += weight
                if r <= cumulative:
                    message = gen_func()
                    break

            LOG.info(f"\n[{message_count}] {category.upper()}")
            LOG.info(f"Message: {message[:100]}...")

            success, response = send_to_frank(message)

            stats["messages_sent"] += 1
            if success:
                stats["messages_success"] += 1
                stats["categories"][category] += 1
                LOG.info(f"Response: {response[:100]}...")
            else:
                stats["messages_failed"] += 1
                LOG.warning(f"Failed: {response}")

        # Calculate remaining time
        remaining = (end_time - datetime.now()).total_seconds()
        if remaining <= 0:
            break

        # Wait before next message
        if test_mode:
            wait_time = random.uniform(5, 15)
        else:
            wait_time = random.uniform(MIN_INTERVAL, MAX_INTERVAL)

        # Ensure we don't wait past end time
        wait_time = min(wait_time, remaining)

        progress = (datetime.now() - start_time).total_seconds() / (duration_minutes * 60) * 100
        LOG.info(f"Progress: {progress:.1f}% | Waiting {wait_time:.0f}s...")

        time.sleep(wait_time)

    # Final stats
    stats["end_time"] = datetime.now().isoformat()
    stats["actual_duration_minutes"] = (datetime.now() - start_time).total_seconds() / 60

    # Save stats
    STATS_FILE.write_text(json.dumps(stats, indent=2))

    LOG.info(f"\n{'='*60}")
    LOG.info("TRAINING COMPLETED")
    LOG.info(f"{'='*60}")
    LOG.info(f"Duration: {stats['actual_duration_minutes']:.1f} minutes")
    LOG.info(f"Messages sent: {stats['messages_sent']}")
    LOG.info(f"Successful: {stats['messages_success']}")
    LOG.info(f"Failed: {stats['messages_failed']}")
    LOG.info(f"Recall queries: {stats['recalls']}")
    LOG.info(f"\nCategories:")
    for cat, count in stats['categories'].items():
        LOG.info(f"  - {cat}: {count}")
    LOG.info(f"\nStats saved: {STATS_FILE}")
    LOG.info(f"Log saved: {LOG_FILE}")

    return stats

# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Frank World-Model Trainer")
    parser.add_argument("--duration", type=int, default=120, help="Training duration in minutes (default: 120)")
    parser.add_argument("--test", action="store_true", help="Test mode (faster intervals)")

    args = parser.parse_args()

    try:
        run_training_session(args.duration, args.test)
    except KeyboardInterrupt:
        LOG.info("\nTraining cancelled by user.")
    except Exception as e:
        LOG.error(f"Training error: {e}")
        raise
