#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Core-Awareness Module for Frank

Gives Frank self-understanding of his own codebase:
- Indexes and analyzes all modules in <AICORE_BASE>
- Detects changes via file hashing
- Stores abstracted understanding in system_core.json
- Runs autonomously to keep knowledge up-to-date

Database location: <AICORE_BASE>/database/system_core.json
"""

import ast
import hashlib
import json
import logging
import os
import subprocess
import threading
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any

# Setup logging
logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(levelname)s: %(message)s')
LOG = logging.getLogger("core_awareness")

# Paths
try:
    from config.paths import AICORE_ROOT as _SRC_ROOT, get_state, STATE_DIR
    AICORE_ROOT = _SRC_ROOT.parent.parent  # source root -> project root
    DATABASE_DIR = STATE_DIR
    DATABASE_FILE = get_state("system_core")
except ImportError:
    _SRC_ROOT = Path(__file__).resolve().parents[1]
    AICORE_ROOT = _SRC_ROOT.parent.parent
    DATABASE_DIR = Path.home() / ".local" / "share" / "frank" / "state"
    DATABASE_DIR.mkdir(parents=True, exist_ok=True)
    DATABASE_FILE = DATABASE_DIR / "system_core.json"
LOCK_FILE = AICORE_ROOT / ".aicore_lock"
PAUSE_FILE = AICORE_ROOT / ".aicore_watch_paused"

# Configuration
DEBOUNCE_SECONDS = 35  # Wait 35 seconds after last change before analyzing
LOCK_TIMEOUT_MINUTES = 15  # Ignore lock files older than 15 minutes
BATCH_WINDOW_SECONDS = 120  # Collect changes for 2 minutes before batch processing
WATCH_EXTENSIONS = {".py", ".json", ".yaml", ".yml", ".toml", ".sh"}
IGNORE_PATTERNS = {
    "__pycache__", ".pyc", ".pyo", ".git", ".env", "venv", "node_modules",
    ".log", ".tmp", ".swp", ".swo", "~", ".aicore_lock", ".aicore_watch_paused",
    "database/",  # Don't watch our own database
}

# Core modules to track with higher priority
CORE_MODULES = [
    "opt/aicore/ui/chat_overlay.py",
    "opt/aicore/tools/toolboxd.py",
    "opt/aicore/tools/app_registry.py",
    "opt/aicore/tools/steam_integration.py",
    "opt/aicore/personality/personality.py",
]

# Feature detection - maps code patterns to user-facing capabilities
# Format: keyword -> (feature_name, description, category, priority, limitations)
#   priority: "core" = core feature, "extended" = extension
#   limitations: known limitations (empty string = none)
FEATURE_PATTERNS = {
    # App launching
    "app_registry": ("App Launcher", "Can open all desktop apps including Flatpak and Snap, auto-discovers new apps", "apps", "core", "Auto-rescan every 5 min, detects all .desktop entries"),
    "steam_integration": ("Steam Integration", "Can launch Steam games and browse the Steam library", "apps", "extended", "In gaming mode: overlay minimized, no active monitoring or reflection — only TinyLlama 1.1B active (saves GPU for the game). Steam client must be running"),
    "open_app": ("Open App", "Can launch any application on command", "apps", "core", ""),
    # Vision
    "screenshot": ("Screenshot Analysis", "Can take screenshots and analyze what's on screen", "vision", "core", "Local 7B model (LLaVA), may hallucinate details. Rate limit: 1/10s"),
    "vision_module": ("Computer Vision", "Can understand images and screen content", "vision", "core", "Local model, no cloud API. OCR text is verified, image descriptions may be inaccurate"),
    "desktop": ("Desktop View", "Can see and describe the desktop", "vision", "core", "Only visible windows, no multi-monitor"),
    # Voice
    "voice": ("Voice Input", "Can understand spoken commands via Whisper STT — 100% offline, English+German", "voice", "core", "Whisper local, latency ~2-5s depending on sentence length"),
    "tts": ("Text-to-Speech", "Can read responses aloud", "voice", "core", "Piper TTS offline, voice not customizable"),
    # Files
    "list_files": ("File Browser", "Can browse folders and list files", "files", "core", "No write access via chat, read-only"),
    "read_file": ("File Reader", "Can read and analyze text files", "files", "core", "Max ~100KB per file, binary formats via Ingestd"),
    "filesystem": ("Filesystem Access", "Can access the local filesystem", "files", "core", ""),
    # System
    "network": ("Network Info", "Can retrieve network status and router info", "system", "extended", ""),
    "hardware": ("Hardware Info", "Can display CPU, RAM, GPU status", "system", "core", "Sensor data via psutil/lm-sensors, GPU via Vulkan"),
    "usb": ("USB Devices", "Can detect, mount, unmount and safely eject USB storage devices", "system", "extended", "Mount/unmount/eject via udisksctl (no root required)"),
    "driver": ("Driver Info", "Can list installed drivers", "system", "extended", ""),
    "process": ("Process Monitor", "Can display running processes", "system", "extended", "Can list processes, cannot kill without agentic mode"),
    # Smart Home
    "smarthome": ("Smart Home", "Can control smart home devices", "smarthome", "extended", "Only configured devices on the local network"),
    "hue": ("Philips Hue", "Can control Hue lights", "smarthome", "extended", "Requires Hue Bridge on LAN"),
    "tasmota": ("Tasmota Devices", "Can control Tasmota plugs/devices", "smarthome", "extended", "HTTP API, LAN only"),
    # Email
    "email_reader": ("Email Access", "Can read, list, send, reply, forward, delete, spam, draft and manage emails", "chat", "core", "IMAP/SMTP via OAuth2, full read-write"),
    "email_mixin": ("Email UI & Notifications", "Email popup with reply/reply-all/forward/compose, CC/BCC, attachments, new-email notifications", "chat", "core", ""),
    # Calendar
    "calendar_reader": ("Calendar Access", "Can read, create and delete Google Calendar events via CalDAV", "chat", "core", "CalDAV, requires OAuth2 token"),
    "calendar_mixin": ("Calendar Reminders", "Automatically reminds about upcoming events", "chat", "core", ""),
    # Contacts
    "contact_reader": ("Contacts Access", "Can read, search, create and delete Google Contacts via CardDAV", "chat", "extended", "CardDAV, requires OAuth2 token"),
    "contacts_mixin": ("Contacts Management", "View, search, create and delete contacts via chat", "chat", "extended", ""),
    # Notes
    "notes_store": ("Notes Storage", "Persistent local notes with SQLite and FTS5 full-text search", "chat", "core", "Text only, no images/attachments"),
    "notes_mixin": ("Notes Management", "Create, search, list and delete notes via chat", "chat", "core", ""),
    # Todos
    "todo_store": ("Todo Storage", "Persistent task list with status and due dates, SQLite + FTS5", "chat", "core", ""),
    "todo_mixin": ("Todo Management", "Create, complete, delete tasks, reminders on due dates", "chat", "core", ""),
    # Converter
    "converter": ("Unit Converter", "Unit and currency conversion (date, length, weight, temperature, currency)", "chat", "extended", "Exchange rates offline, not real-time"),
    "calculator_mixin": ("Calculator Integration", "Convert units/currency directly in chat", "chat", "extended", ""),
    # Clipboard History
    "clipboard_store": ("Clipboard Storage", "Persistent clipboard history with SQLite, SHA-256 dedup, max 50 entries", "chat", "extended", "Text only, no images"),
    "clipboard_mixin": ("Clipboard History", "Passive clipboard monitoring, search, restore, delete via chat", "chat", "extended", ""),
    # Password Manager
    "password_store": ("Password Storage", "Encrypted password store with Fernet/AES and PBKDF2, master password", "chat", "extended", "Locally encrypted, no cloud sync"),
    "password_mixin": ("Password Manager", "Password popup, chat search, auto-login via xdotool", "chat", "extended", "Auto-login only for X11 apps"),
    # QR Code
    "qr_tool": ("QR Code Tool", "Scan QR codes (pyzbar+OpenCV) and generate them (qrcode library)", "tools", "extended", ""),
    "qr_mixin": ("QR Code Integration", "Scan QR from screen/camera, create QR codes and display in chat", "chat", "extended", ""),
    # Printer
    "printer_mixin": ("Printer Management", "Print files via lp, check printer status, view print queue", "chat", "extended", "CUPS-compatible printers only"),
    # Chat
    "chat": ("Chat Interface", "Can communicate in natural language", "chat", "core", ""),
    "personality": ("Personality", "Has a defined personality (Frank)", "chat", "core", "Frozen weights, no real learning from chats"),
    "llama": ("LLM Backend", "Uses local LLM for responses", "chat", "core", "Local 7B/8B model, ~8-12 tok/s via Vulkan GPU"),
    # Web browsing — all use "webd" keyword since webd/app.py is the indexed module
    "webd": ("Internet Search", "Can search the clearnet and darknet and display results in chat", "web", "core", "Clearnet via DuckDuckGo, darknet via Torch (Tor SOCKS proxy)"),
    "ddg_search": ("Web Proxy", "Can fetch, read and summarize web pages", "web", "core", "HTML extraction, no JavaScript rendering"),
    "resolve_ddg": ("Darknet Browsing", "Can open .onion sites in Tor Browser and search the darknet", "web", "core", "Tor Browser must be installed, latency ~5-15s via SOCKS proxy, text/HTML only (no images/videos). Results are NOT filtered — user assumes responsibility"),
    # Self-awareness
    "core_awareness": ("Self-Awareness", "Can analyze and understand its own codebase", "meta", "core", "Static analysis (AST), no runtime debugging"),
    "self": ("Self-Reflection", "Can think about itself", "meta", "core", "Reflection via LLM, no true introspection"),
    # Epistemic coherence
    "quantum_reflector": ("Epistemic Coherence", "Continuously monitors cognitive state coherence via QUBO optimization and simulated annealing — 40 variables, 47 implication rules, feeds into consciousness attention and Genesis scoring", "meta", "core", "Solve time ~3.5s, discretizes E-PQ into 3 buckets (information loss)"),
    "qubo_builder": ("QUBO State Encoder", "Encodes cognitive state into binary optimization matrix with one-hot constraints and quadratic implications", "meta", "core", ""),
    "annealer": ("Simulated Annealing Solver", "O(n) delta energy SA with multi-flip, 200 runs x 2000 steps, geometric cooling", "meta", "core", "Classical SA, not quantum hardware"),
    "coherence_monitor": ("Coherence Monitor", "Polling daemon that tracks energy history, detects drift, and triggers re-solves on state changes", "meta", "core", "5s polling interval, cumulative drift threshold 0.4"),
    "epq_bridge": ("E-PQ Coherence Bridge", "Translates coherence events into personality feedback with exponential backoff", "meta", "core", "Min 10s, max 300s between events"),
}


@dataclass
class ModuleEntry:
    """Represents Frank's understanding of a single module."""
    path: str
    name: str
    module_type: str  # "core", "tool", "config", "utility"
    purpose: str  # Abstracted description
    functions: List[str] = field(default_factory=list)  # Key functions/classes
    dependencies: List[str] = field(default_factory=list)
    last_hash: str = ""
    last_analyzed: str = ""
    last_modified: str = ""
    confidence_score: int = 100  # 0-100%
    status: str = "understood"  # "understood", "needs_review", "analyzing", "error"
    history: List[Dict[str, str]] = field(default_factory=list)  # Change history

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ModuleEntry":
        return cls(**data)


@dataclass
class CoreDatabase:
    """Frank's knowledge database about his own system."""
    version: str = "1.0.0"
    last_full_scan: str = ""
    total_modules: int = 0
    modules: Dict[str, ModuleEntry] = field(default_factory=dict)
    pending_changes: List[str] = field(default_factory=list)
    watch_paused: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "last_full_scan": self.last_full_scan,
            "total_modules": self.total_modules,
            "modules": {k: v.to_dict() for k, v in self.modules.items()},
            "pending_changes": self.pending_changes,
            "watch_paused": self.watch_paused,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CoreDatabase":
        db = cls(
            version=data.get("version", "1.0.0"),
            last_full_scan=data.get("last_full_scan", ""),
            total_modules=data.get("total_modules", 0),
            pending_changes=data.get("pending_changes", []),
            watch_paused=data.get("watch_paused", False),
        )
        for path, entry_data in data.get("modules", {}).items():
            db.modules[path] = ModuleEntry.from_dict(entry_data)
        return db


class CoreAwareness:
    """Main Core-Awareness system for Frank."""

    def __init__(self):
        self.database = CoreDatabase()
        self.file_hashes: Dict[str, str] = {}
        self.pending_files: Dict[str, float] = {}  # path -> last_modified_time
        self._lock = threading.Lock()
        self._running = False
        self._watcher_thread: Optional[threading.Thread] = None

        # Ensure database directory exists
        DATABASE_DIR.mkdir(parents=True, exist_ok=True)

        # Load existing database
        self._load_database()

    def _load_database(self):
        """Load database from disk."""
        if DATABASE_FILE.exists():
            try:
                with open(DATABASE_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.database = CoreDatabase.from_dict(data)
                LOG.info(f"Loaded database: {self.database.total_modules} modules")
            except Exception as e:
                LOG.error(f"Failed to load database: {e}")
                self.database = CoreDatabase()
        else:
            LOG.info("No existing database, starting fresh")

    def _save_database(self):
        """Save database to disk atomically."""
        try:
            temp_file = DATABASE_FILE.with_suffix(".tmp")
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(self.database.to_dict(), f, indent=2, ensure_ascii=False)
            temp_file.replace(DATABASE_FILE)
            LOG.debug("Database saved")
        except Exception as e:
            LOG.error(f"Failed to save database: {e}")

    def _should_ignore(self, path: Path) -> bool:
        """Check if a path should be ignored."""
        path_str = str(path)
        for pattern in IGNORE_PATTERNS:
            if pattern in path_str:
                return True
        return path.suffix not in WATCH_EXTENSIONS

    def _compute_file_hash(self, path: Path) -> str:
        """Compute hash of file content (excluding comments/whitespace for .py)."""
        try:
            content = path.read_text(encoding="utf-8", errors="replace")

            # For Python files, use AST-based hashing (ignores comments/whitespace)
            if path.suffix == ".py":
                try:
                    tree = ast.parse(content)
                    # Create a normalized representation
                    normalized = ast.dump(tree)
                    return hashlib.sha256(normalized.encode()).hexdigest()[:16]
                except SyntaxError:
                    pass  # Fall back to content hash

            return hashlib.sha256(content.encode()).hexdigest()[:16]
        except Exception:
            return ""

    def _is_lock_active(self) -> bool:
        """Check if development lock is active."""
        if not LOCK_FILE.exists():
            return False

        # Check if lock is stale (older than timeout)
        try:
            age_minutes = (time.time() - LOCK_FILE.stat().st_mtime) / 60
            if age_minutes > LOCK_TIMEOUT_MINUTES:
                LOG.warning(f"Stale lock file detected ({age_minutes:.1f} min), removing")
                LOCK_FILE.unlink()
                return False
        except Exception:
            pass

        return True

    def _is_paused(self) -> bool:
        """Check if watching is paused."""
        return PAUSE_FILE.exists() or self.database.watch_paused

    def _validate_python_syntax(self, path: Path) -> bool:
        """Validate Python file syntax."""
        if path.suffix != ".py":
            return True

        try:
            result = subprocess.run(
                ["python3", "-m", "py_compile", str(path)],
                capture_output=True, timeout=10
            )
            return result.returncode == 0
        except Exception:
            return False

    def _get_module_type(self, path: Path) -> str:
        """Determine module type based on path."""
        path_str = str(path)
        if any(core in path_str for core in CORE_MODULES):
            return "core"
        if "/tools/" in path_str:
            return "tool"
        if path.suffix in {".json", ".yaml", ".yml", ".toml"}:
            return "config"
        return "utility"

    def _analyze_python_file(self, path: Path) -> Dict[str, Any]:
        """Extract structure from a Python file using AST."""
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(content)

            functions = []
            classes = []
            imports = []

            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    functions.append(node.name)
                elif isinstance(node, ast.ClassDef):
                    classes.append(node.name)
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        imports.append(alias.name)
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        imports.append(node.module)

            # Get docstring if available
            docstring = ast.get_docstring(tree) or ""

            return {
                "functions": functions[:20],  # Limit to 20
                "classes": classes[:10],
                "imports": imports[:20],
                "docstring": docstring[:500],  # Limit length
                "lines": len(content.split("\n")),
            }
        except Exception as e:
            return {"error": str(e)}

    def _generate_purpose_summary(self, path: Path, analysis: Dict[str, Any]) -> str:
        """Generate a concise purpose summary for a module."""
        # For now, use heuristics. In future, could use LLM.
        name = path.stem
        docstring = analysis.get("docstring", "")
        functions = analysis.get("functions", [])
        classes = analysis.get("classes", [])

        if docstring:
            # Use first line of docstring
            first_line = docstring.split("\n")[0].strip()
            if len(first_line) > 10:
                return first_line[:200]

        # Generate from structure
        parts = []
        if classes:
            parts.append(f"Defines classes: {', '.join(classes[:3])}")
        if functions:
            key_funcs = [f for f in functions if not f.startswith("_")][:5]
            if key_funcs:
                parts.append(f"Functions: {', '.join(key_funcs)}")

        if parts:
            return "; ".join(parts)

        return f"Python module: {name}"

    def analyze_file(self, path: Path, force: bool = False) -> Optional[ModuleEntry]:
        """Analyze a single file and create/update its database entry."""
        if self._should_ignore(path):
            return None

        if not path.exists():
            # File was deleted
            rel_path = str(path.relative_to(AICORE_ROOT))
            if rel_path in self.database.modules:
                del self.database.modules[rel_path]
                LOG.info(f"Removed deleted module: {rel_path}")
            return None

        rel_path = str(path.relative_to(AICORE_ROOT))
        current_hash = self._compute_file_hash(path)

        # Check if we need to re-analyze
        existing = self.database.modules.get(rel_path)
        if existing and existing.last_hash == current_hash and not force:
            return existing  # No changes

        # Validate syntax for Python files
        if path.suffix == ".py" and not self._validate_python_syntax(path):
            LOG.warning(f"Syntax error in {rel_path}, skipping analysis")
            if existing:
                existing.status = "error"
            return existing

        LOG.info(f"Analyzing: {rel_path}")

        # Analyze file
        analysis = {}
        if path.suffix == ".py":
            analysis = self._analyze_python_file(path)

        # Create entry
        entry = ModuleEntry(
            path=rel_path,
            name=path.stem,
            module_type=self._get_module_type(path),
            purpose=self._generate_purpose_summary(path, analysis),
            functions=analysis.get("functions", []) + analysis.get("classes", []),
            dependencies=analysis.get("imports", []),
            last_hash=current_hash,
            last_analyzed=datetime.now().isoformat(),
            last_modified=datetime.fromtimestamp(path.stat().st_mtime).isoformat(),
            confidence_score=85 if analysis.get("docstring") else 70,
            status="understood",
        )

        # Add to history if this is an update
        if existing and existing.last_hash != current_hash:
            entry.history = existing.history[-9:]  # Keep last 9
            entry.history.append({
                "date": datetime.now().isoformat(),
                "change": f"Code updated (previous: {existing.last_hash[:8]})",
            })

        self.database.modules[rel_path] = entry
        return entry

    def full_scan(self):
        """Perform a full scan of the aicore directory."""
        LOG.info("Starting full scan...")

        scanned = 0
        for path in AICORE_ROOT.rglob("*"):
            if path.is_file() and not self._should_ignore(path):
                self.analyze_file(path)
                scanned += 1

        self.database.total_modules = len(self.database.modules)
        self.database.last_full_scan = datetime.now().isoformat()
        self._save_database()

        LOG.info(f"Full scan complete: {scanned} files, {self.database.total_modules} modules indexed")

    def get_module_info(self, module_name: str) -> Optional[ModuleEntry]:
        """Get information about a specific module."""
        # Try exact match first
        if module_name in self.database.modules:
            return self.database.modules[module_name]

        # Try partial match
        for path, entry in self.database.modules.items():
            if module_name.lower() in path.lower() or module_name.lower() == entry.name.lower():
                return entry

        return None

    def get_system_summary(self) -> Dict[str, Any]:
        """Get a summary of Frank's self-knowledge."""
        core_modules = [e for e in self.database.modules.values() if e.module_type == "core"]
        tools = [e for e in self.database.modules.values() if e.module_type == "tool"]

        return {
            "total_modules": self.database.total_modules,
            "last_scan": self.database.last_full_scan,
            "core_modules": len(core_modules),
            "tools": len(tools),
            "needs_review": sum(1 for e in self.database.modules.values() if e.confidence_score < 70),
            "watch_status": "paused" if self._is_paused() else "active",
        }

    def _analyze_complexity(self) -> Dict[str, Any]:
        """Analyze the complexity of Frank's codebase."""
        total_functions = 0
        total_dependencies = set()
        largest_modules = []
        low_confidence = []

        for entry in self.database.modules.values():
            func_count = len(entry.functions)
            total_functions += func_count
            total_dependencies.update(entry.dependencies)

            if func_count > 10:
                largest_modules.append((entry.name, func_count, entry.module_type))
            if entry.confidence_score < 70:
                low_confidence.append(entry.name)

        largest_modules.sort(key=lambda x: x[1], reverse=True)

        return {
            "total_functions": total_functions,
            "unique_dependencies": len(total_dependencies),
            "largest_modules": largest_modules[:5],
            "low_confidence_modules": low_confidence,
            "avg_functions_per_module": total_functions / max(len(self.database.modules), 1),
        }

    def _identify_improvements(self) -> List[str]:
        """Identify potential improvements in Frank's code."""
        improvements = []

        # Check for modules with many functions (might need splitting)
        for entry in self.database.modules.values():
            if len(entry.functions) > 30:
                improvements.append(f"'{entry.name}' has {len(entry.functions)} functions - could be split into smaller modules")

        # Check for low confidence modules
        low_conf = [e for e in self.database.modules.values() if e.confidence_score < 70]
        if low_conf:
            improvements.append(f"{len(low_conf)} modules have low confidence and need better documentation")

        # Check for modules without clear purpose
        unclear = [e for e in self.database.modules.values() if "Python module:" in e.purpose and e.module_type in ("core", "tool")]
        if unclear:
            improvements.append(f"{len(unclear)} modules have no clear description of their function")

        return improvements

    def _what_works_well(self) -> List[str]:
        """Identify what's working well in Frank's system."""
        positives = []

        # High confidence modules
        high_conf = [e for e in self.database.modules.values() if e.confidence_score >= 90]
        if high_conf:
            positives.append(f"{len(high_conf)} modules are well documented and understood")

        # Core modules
        core = [e for e in self.database.modules.values() if e.module_type == "core"]
        if core:
            positives.append(f"Clear separation of {len(core)} core modules")

        # Tools
        tools = [e for e in self.database.modules.values() if e.module_type == "tool"]
        if tools:
            positives.append(f"{len(tools)} specialized tools for various tasks")

        return positives

    def _what_needs_work(self) -> List[str]:
        """Identify what might not be working perfectly."""
        issues = []

        # Modules that might have issues
        for entry in self.database.modules.values():
            if entry.status == "needs_review":
                issues.append(f"'{entry.name}' still needs review")

        # Check for potential circular dependencies (simplified check)
        # Check for modules without dependencies (might be orphaned)
        orphans = [e for e in self.database.modules.values()
                   if not e.dependencies and e.module_type in ("tool", "utility") and len(e.functions) > 0]
        if len(orphans) > 10:
            issues.append(f"{len(orphans)} modules have no detected dependencies")

        return issues

    def get_all_features(self) -> Dict[str, List[Dict[str, str]]]:
        """Extract all features/capabilities from Frank's codebase."""
        features_by_category = {}
        seen_features = set()

        # Scan all modules for feature patterns
        for entry in self.database.modules.values():
            # Check module name, path, functions, and purpose for feature keywords
            searchable = f"{entry.name} {entry.path} {' '.join(entry.functions)} {entry.purpose}".lower()

            for keyword, pattern_data in FEATURE_PATTERNS.items():
                feature_name, description, category = pattern_data[0], pattern_data[1], pattern_data[2]
                priority = pattern_data[3] if len(pattern_data) > 3 else "extended"
                limitations = pattern_data[4] if len(pattern_data) > 4 else ""

                if keyword.lower() in searchable and feature_name not in seen_features:
                    seen_features.add(feature_name)
                    if category not in features_by_category:
                        features_by_category[category] = []
                    features_by_category[category].append({
                        "name": feature_name,
                        "description": description,
                        "source_module": entry.name,
                        "priority": priority,
                        "limitations": limitations,
                    })

        return features_by_category

    def list_features_text(self) -> str:
        """Generate a formatted text listing all features with priorities and limitations."""
        features = self.get_all_features()

        if not features:
            return "I could not find any features in my codebase."

        # Category labels
        category_labels = {
            "apps": "🚀 Apps & Programs",
            "vision": "👁️ Vision & Screenshots",
            "voice": "🎤 Voice",
            "files": "📁 Files",
            "system": "💻 System & Hardware",
            "web": "🌐 Internet & Darknet",
            "smarthome": "🏠 Smart Home",
            "ui": "🎨 User Interface",
            "chat": "💬 Chat & Communication",
            "meta": "🧠 Self-Awareness",
        }

        lines = ["**My Features and Capabilities:**\n"]
        core_count = 0
        ext_count = 0

        # Sort categories by label
        for cat_key in ["apps", "vision", "voice", "files", "system", "web", "smarthome", "ui", "chat", "meta"]:
            if cat_key in features:
                label = category_labels.get(cat_key, cat_key.title())
                lines.append(f"\n**{label}:**")
                # Core features first, then extended
                sorted_feats = sorted(features[cat_key], key=lambda f: (0 if f.get("priority") == "core" else 1, f["name"]))
                for feat in sorted_feats:
                    is_core = feat.get("priority") == "core"
                    if is_core:
                        core_count += 1
                    else:
                        ext_count += 1
                    prio_tag = " ★" if is_core else ""
                    limit_str = f" ⚠ _{feat['limitations']}_" if feat.get("limitations") else ""
                    lines.append(f"  • **{feat['name']}**{prio_tag}: {feat['description']}{limit_str}")

        # Count + legend
        total = core_count + ext_count
        lines.append(f"\n_{total} features detected across {len(self.database.modules)} modules ({core_count} core ★, {ext_count} extended)._")
        lines.append(f"\n_I am a privacy-focused, fully local AI assistant with hardware integration and self-awareness._")
        lines.append("\n**Known Limitations:** Frozen weights (no real learning from chats), all models local (7-8B), no real-time internet (proxy only), no webcam/video analysis.")
        lines.append("_100% offline and local — no cloud APIs, no telemetry, all data stays on this machine._")

        return "\n".join(lines)

    def describe_self(self) -> str:
        """Generate a reflective, natural language description of Frank's system."""
        summary = self.get_system_summary()
        complexity = self._analyze_complexity()
        improvements = self._identify_improvements()
        positives = self._what_works_well()
        issues = self._what_needs_work()

        lines = []

        # Overview
        lines.append(f"**My System Overview:**")
        lines.append(f"I consist of {summary['total_modules']} modules with a total of {complexity['total_functions']} functions.")
        lines.append(f"Of those, {summary['core_modules']} are core modules and {summary['tools']} are tools.")
        lines.append("")

        # Complexity reflection
        lines.append("**My Complexity Assessment:**")
        avg_funcs = complexity['avg_functions_per_module']
        if avg_funcs > 15:
            lines.append(f"With an average of {avg_funcs:.1f} functions per module, I'm quite complex.")
        elif avg_funcs > 5:
            lines.append(f"With an average of {avg_funcs:.1f} functions per module, I have moderate complexity.")
        else:
            lines.append(f"With an average of {avg_funcs:.1f} functions per module, I'm still manageable.")

        if complexity['largest_modules']:
            largest = complexity['largest_modules'][0]
            lines.append(f"My largest module is '{largest[0]}' with {largest[1]} functions.")
        lines.append("")

        # What works well
        if positives:
            lines.append("**What I like about myself:**")
            for p in positives[:3]:
                lines.append(f"  • {p}")
            lines.append("")

        # What could be improved
        if improvements:
            lines.append("**What could be improved:**")
            for i in improvements[:3]:
                lines.append(f"  • {i}")
            lines.append("")

        # Issues
        if issues:
            lines.append("**What doesn't quite work yet:**")
            for issue in issues[:3]:
                lines.append(f"  • {issue}")
            lines.append("")

        # Core modules
        core_modules = [e for e in self.database.modules.values() if e.module_type == "core"]
        if core_modules:
            lines.append("**My most important components:**")
            for entry in sorted(core_modules, key=lambda e: len(e.functions), reverse=True)[:5]:
                conf_emoji = "✓" if entry.confidence_score >= 80 else "?"
                lines.append(f"  {conf_emoji} {entry.name}: {entry.purpose[:60]}")

        return "\n".join(lines)

    def reflect_on_module(self, module_name: str) -> str:
        """Generate a reflective analysis of a specific module."""
        entry = self.get_module_info(module_name)
        if not entry:
            return f"I don't know a module called '{module_name}'."

        lines = [f"**My thoughts on '{entry.name}':**", ""]

        # Purpose
        lines.append(f"**Purpose:** {entry.purpose}")
        lines.append("")

        # Complexity assessment
        func_count = len(entry.functions)
        if func_count > 30:
            lines.append(f"**Complexity:** With {func_count} functions, this module is very complex. " +
                        "It could benefit from being split into smaller modules.")
        elif func_count > 15:
            lines.append(f"**Complexity:** With {func_count} functions, this module has moderate complexity.")
        elif func_count > 0:
            lines.append(f"**Complexity:** With {func_count} functions, this module is manageable.")
        else:
            lines.append("**Complexity:** This module contains no detected functions (possibly configuration).")
        lines.append("")

        # Confidence
        if entry.confidence_score >= 90:
            lines.append(f"**Understanding:** I understand this module very well ({entry.confidence_score}% confidence).")
        elif entry.confidence_score >= 70:
            lines.append(f"**Understanding:** I have a good basic understanding ({entry.confidence_score}% confidence).")
        else:
            lines.append(f"**Understanding:** I need to understand this module better ({entry.confidence_score}% confidence).")
        lines.append("")

        # Dependencies
        if entry.dependencies:
            dep_count = len(entry.dependencies)
            lines.append(f"**Dependencies:** {dep_count} external modules — " +
                        ("well encapsulated" if dep_count < 10 else "many dependencies"))

        # Key functions
        if entry.functions:
            lines.append("")
            lines.append(f"**Key Functions:** {', '.join(entry.functions[:8])}")
            if len(entry.functions) > 8:
                lines.append(f"  ...and {len(entry.functions) - 8} more")

        return "\n".join(lines)

    # === Watcher functionality ===

    def _watcher_loop(self):
        """Background thread that watches for file changes."""
        LOG.info("Watcher started")
        last_check = time.time()

        while self._running:
            try:
                # Check every 5 seconds
                time.sleep(5)

                # Skip if locked or paused
                if self._is_lock_active() or self._is_paused():
                    continue

                # Scan for changes
                current_time = time.time()

                for path in AICORE_ROOT.rglob("*"):
                    if not path.is_file() or self._should_ignore(path):
                        continue

                    try:
                        mtime = path.stat().st_mtime
                        rel_path = str(path.relative_to(AICORE_ROOT))

                        # Check if file changed since last check
                        if mtime > last_check:
                            self.pending_files[rel_path] = mtime
                    except Exception:
                        continue

                # Process pending files after debounce period
                files_to_process = []
                for rel_path, mtime in list(self.pending_files.items()):
                    if current_time - mtime > DEBOUNCE_SECONDS:
                        files_to_process.append(rel_path)
                        del self.pending_files[rel_path]

                # Batch process
                if files_to_process:
                    LOG.info(f"Processing {len(files_to_process)} changed files")
                    for rel_path in files_to_process:
                        full_path = AICORE_ROOT / rel_path
                        self.analyze_file(full_path)
                    self._save_database()

                last_check = current_time

            except Exception as e:
                LOG.error(f"Watcher error: {e}")

    def start_watcher(self):
        """Start the background file watcher."""
        if self._running:
            return

        self._running = True
        self._watcher_thread = threading.Thread(target=self._watcher_loop, daemon=True)
        self._watcher_thread.start()
        LOG.info("Core-Awareness watcher started")

    def stop_watcher(self):
        """Stop the background file watcher."""
        self._running = False
        if self._watcher_thread:
            self._watcher_thread.join(timeout=10)
        LOG.info("Core-Awareness watcher stopped")

    def pause_watch(self):
        """Pause the watcher (developer mode)."""
        PAUSE_FILE.touch()
        self.database.watch_paused = True
        self._save_database()
        LOG.info("Watcher paused")

    def resume_watch(self):
        """Resume the watcher."""
        if PAUSE_FILE.exists():
            PAUSE_FILE.unlink()
        self.database.watch_paused = False
        self._save_database()
        LOG.info("Watcher resumed")


# Global instance
_awareness: Optional[CoreAwareness] = None


def get_awareness() -> CoreAwareness:
    """Get or create the global CoreAwareness instance."""
    global _awareness
    if _awareness is None:
        _awareness = CoreAwareness()
    return _awareness


# === Public API ===

def full_scan() -> Dict[str, Any]:
    """Perform a full system scan."""
    awareness = get_awareness()
    awareness.full_scan()
    return {"ok": True, "summary": awareness.get_system_summary()}


def get_module(name: str) -> Dict[str, Any]:
    """Get information about a specific module."""
    awareness = get_awareness()
    entry = awareness.get_module_info(name)
    if entry:
        return {"ok": True, "module": entry.to_dict()}
    return {"ok": False, "error": "Module not found"}


def get_summary() -> Dict[str, Any]:
    """Get system summary."""
    awareness = get_awareness()
    return {"ok": True, "summary": awareness.get_system_summary()}


def describe_self() -> str:
    """Get natural language self-description."""
    awareness = get_awareness()
    return awareness.describe_self()


def start_watcher():
    """Start the file watcher."""
    awareness = get_awareness()
    awareness.start_watcher()


def stop_watcher():
    """Stop the file watcher."""
    awareness = get_awareness()
    awareness.stop_watcher()


def pause_watch():
    """Pause watching (developer mode)."""
    awareness = get_awareness()
    awareness.pause_watch()


def resume_watch():
    """Resume watching."""
    awareness = get_awareness()
    awareness.resume_watch()


def get_features() -> Dict[str, Any]:
    """Get all features/capabilities."""
    awareness = get_awareness()
    return {
        "ok": True,
        "features": awareness.get_all_features(),
        "features_text": awareness.list_features_text(),
    }


# CLI interface
if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: core_awareness.py <command>")
        print("Commands: scan, summary, describe, watch, pause, resume")
        sys.exit(1)

    cmd = sys.argv[1].lower()

    if cmd == "scan":
        result = full_scan()
        print(json.dumps(result, indent=2))
    elif cmd == "summary":
        result = get_summary()
        print(json.dumps(result, indent=2))
    elif cmd == "describe":
        print(describe_self())
    elif cmd == "watch":
        print("Starting watcher (Ctrl+C to stop)...")
        start_watcher()
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            stop_watcher()
    elif cmd == "pause":
        pause_watch()
        print("Watcher paused")
    elif cmd == "resume":
        resume_watch()
        print("Watcher resumed")
    elif cmd == "module" and len(sys.argv) > 2:
        result = get_module(sys.argv[2])
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(f"Unknown command: {cmd}")
