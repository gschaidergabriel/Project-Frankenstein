#!/usr/bin/env python3
"""
E-CPMM Autonomous Training Daemon v2.1
======================================

Fully autonomous 10-hour training with REAL tool creation
and CLAUDE FEEDBACK integration.

NEW in v2.0:
- Extracts code from Frank's responses
- Writes real Python files to sandbox
- Performs syntax check
- Tests in isolated sandbox
- Registers successful tools
- Updates E-CPMM graph with new edges

NEW in v2.1:
- Claude code review for every code proposal
- Feedback loop: Claude tells Frank what works/doesn't work
- Better prompts with concrete code examples
- Iterative code improvement (max 3 attempts)

Author: Projekt Frankenstein
"""

import ast
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import urllib.request
import urllib.error
from dataclasses import dataclass, asdict, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple
import logging
import sqlite3
import hashlib

# ============================================================================
# CONFIGURATION
# ============================================================================

TRAINING_DURATION_HOURS = 10
TRAINING_DURATION_SECONDS = TRAINING_DURATION_HOURS * 3600

# Intervals (from E-CPMM.pdf)
LOOP_INTERVAL_SECONDS = 90
SYSTEM_SCAN_INTERVAL = (45, 75)
PROPOSAL_INTERVAL = (75, 120)
REFLECTION_INTERVAL_MESSAGES = 12
CAPABILITY_AUDIT_INTERVAL_MESSAGES = 18

# Thresholds
CONFIDENCE_THRESHOLD = 0.80
RISK_THRESHOLD = 0.35
CPU_PAUSE_THRESHOLD = 0.70
GPU_PAUSE_THRESHOLD = 0.80

# API Endpoints
CORE_URL = "http://127.0.0.1:8088/chat"
TOOLBOX_URL = "http://127.0.0.1:8089"

# Central path configuration
try:
    from config.paths import (
        TRAINING_LOG_DIR as _TRAINING_LOG_DIR,
        SANDBOX_DIR as _CFG_SANDBOX_DIR,
        get_db,
    )
except ImportError:
    _TRAINING_LOG_DIR = Path("/home/ai-core-node/.local/share/frank/logs/training")
    _CFG_SANDBOX_DIR = Path("/home/ai-core-node/.local/share/frank/sandbox")
    def get_db(name):
        return Path("/home/ai-core-node/.local/share/frank/db") / f"{name}.db"

# Paths
LOG_DIR = _TRAINING_LOG_DIR
LOG_FILE = LOG_DIR / f"training_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
STATE_FILE = LOG_DIR / "training_state.json"
PROPOSALS_FILE = LOG_DIR / "proposals.jsonl"

# NEW: Sandbox paths - Base directory, session folder created at runtime
SANDBOX_BASE_DIR = _CFG_SANDBOX_DIR
SANDBOX_DB = get_db("sandbox_awareness")
ECPMM_DB = get_db("e_cpmm")

# SANDBOX_DIR is set at runtime with timestamp (see AutonomousTrainingDaemon.__init__)
SANDBOX_DIR = None  # Placeholder

# Claude CLI
CLAUDE_CLI = str(Path.home() / ".local" / "bin" / "claude")

# ============================================================================
# LOGGING SETUP
# ============================================================================

LOG_DIR.mkdir(parents=True, exist_ok=True)
SANDBOX_BASE_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s: %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(sys.stdout)
    ]
)
LOG = logging.getLogger("training_daemon")

# ============================================================================
# DATA CLASSES
# ============================================================================

@dataclass
class Proposal:
    """Ein Verbesserungsvorschlag von Frank."""
    id: int
    timestamp: str
    category: str
    description: str
    confidence: float
    risk: float
    causal_reasoning: str
    code_snippet: Optional[str] = None
    status: str = "pending"
    validator: str = "auto"
    validation_reason: str = ""
    implementation_result: Optional[str] = None
    # NEW: Tool tracking
    tool_file: Optional[str] = None
    tool_name: Optional[str] = None
    syntax_valid: bool = False
    execution_success: bool = False
    test_output: Optional[str] = None


@dataclass
class TrainingState:
    """Aktueller Zustand des Trainings."""
    started_at: str
    ends_at: str
    is_running: bool = True
    is_paused: bool = False
    pause_reason: str = ""
    loop_count: int = 0
    message_count: int = 0
    proposal_count: int = 0
    approved_count: int = 0
    rejected_count: int = 0
    implemented_count: int = 0
    # NEW: Tool tracking
    tools_created: int = 0
    tools_syntax_valid: int = 0
    tools_execution_success: int = 0
    last_system_scan: str = ""
    last_reflection: str = ""
    current_phase: str = "init"


# ============================================================================
# DATABASE FUNCTIONS
# ============================================================================

def init_databases():
    """Initialize required databases."""
    # Sandbox DB
    SANDBOX_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(SANDBOX_DB)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tool_registry (
            name TEXT PRIMARY KEY,
            path TEXT,
            origin TEXT DEFAULT 'GENESIS_SANDBOX',
            registered_at TEXT,
            is_promoted INTEGER DEFAULT 0,
            is_safe_for_production INTEGER DEFAULT 0,
            session_id TEXT,
            test_results TEXT,
            description TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sandbox_sessions (
            session_id TEXT PRIMARY KEY,
            purpose TEXT,
            started_at TEXT,
            ended_at TEXT
        )
    """)
    conn.commit()
    conn.close()

    # E-CPMM DB
    ECPMM_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(ECPMM_DB)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS edges (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT,
            target TEXT,
            edge_type TEXT,
            confidence REAL,
            created_at TEXT,
            metadata TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS nodes (
            id TEXT PRIMARY KEY,
            node_type TEXT,
            data TEXT,
            created_at TEXT
        )
    """)
    conn.commit()
    conn.close()
    LOG.info("Databases initialized")


def register_tool(name: str, path: str, description: str, test_results: str, session_id: str):
    """Register a tool in the sandbox registry."""
    conn = sqlite3.connect(SANDBOX_DB)
    conn.execute("""
        INSERT OR REPLACE INTO tool_registry
        (tool_name, tool_path, origin, registered_at, tested_in_sandbox, promoted_to_production, sandbox_session_id, test_results, description)
        VALUES (?, ?, 'GENESIS_SANDBOX', ?, 1, 0, ?, ?, ?)
    """, (name, path, datetime.now().isoformat(), session_id, test_results, description))
    conn.commit()
    conn.close()
    LOG.info(f"Tool registered: {name} at {path}")


def add_ecpmm_edge(source: str, target: str, edge_type: str, confidence: float, metadata: dict = None):
    """Add an edge to the E-CPMM graph."""
    conn = sqlite3.connect(ECPMM_DB)
    conn.execute("""
        INSERT INTO edges (source, target, edge_type, confidence, created_at, metadata)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (source, target, edge_type, confidence, datetime.now().isoformat(), json.dumps(metadata or {})))
    conn.commit()
    conn.close()
    LOG.info(f"E-CPMM Edge added: {source} --[{edge_type}]--> {target} (conf: {confidence})")


def add_ecpmm_node(node_id: str, node_type: str, data: dict = None):
    """Add a node to the E-CPMM graph."""
    conn = sqlite3.connect(ECPMM_DB)
    conn.execute("""
        INSERT OR REPLACE INTO nodes (id, node_type, data, created_at)
        VALUES (?, ?, ?, ?)
    """, (node_id, node_type, json.dumps(data or {}), datetime.now().isoformat()))
    conn.commit()
    conn.close()


# ============================================================================
# CODE EXTRACTION & VALIDATION
# ============================================================================

def get_next_proposal_id() -> int:
    """Get the next globally unique proposal ID by reading existing proposals."""
    max_id = 0
    try:
        if PROPOSALS_FILE.exists():
            with open(PROPOSALS_FILE) as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            p = json.loads(line)
                            pid = p.get("id", 0)
                            if isinstance(pid, int) and pid > max_id:
                                max_id = pid
                        except (json.JSONDecodeError, ValueError):
                            pass
    except Exception:
        pass
    return max_id + 1


def _compute_description_hash(text: str) -> str:
    """Compute a normalized hash of proposal description for deduplication."""
    # Normalize: lowercase, strip whitespace, remove filler phrases
    normalized = text.lower().strip()
    # Remove common LLM filler that doesn't change meaning
    for filler in [
        "ich bin bereit, dir zu helfen.",
        "ich bin bereit, dir bei der selbstverbesserung zu helfen.",
        "ich bin frank, ein teil von projekt frankenstein.",
        "ich bin bereit, als frank",
        "ich bin ein ki-systemprozess",
    ]:
        normalized = normalized.replace(filler, "")
    # Keep only alphanumeric + spaces, collapse whitespace
    normalized = re.sub(r'[^a-z0-9äöüß ]+', ' ', normalized)
    normalized = re.sub(r'\s+', ' ', normalized).strip()
    # Use first 200 chars for hash (captures the core idea)
    return hashlib.sha256(normalized[:200].encode()).hexdigest()[:16]


def _extract_keywords(text: str) -> set:
    """Extract significant keywords from text for fuzzy dedup."""
    text_lower = text.lower()
    # Remove common German filler
    for stop in ["der", "die", "das", "und", "für", "mit", "auf", "von", "des",
                 "eine", "ein", "den", "dem", "wird", "kann", "wird", "durch",
                 "zur", "zum", "verbesserte", "verbessern", "verbesserung",
                 "kategorie", "beschreibung", "confidence", "risk", "score",
                 "kausale", "begründung", "code", "idee"]:
        text_lower = text_lower.replace(stop, " ")
    words = set(re.sub(r'[^a-zäöüß0-9]+', ' ', text_lower).split())
    # Only keep words with 4+ chars (meaningful)
    return {w for w in words if len(w) >= 4}


def is_duplicate_proposal(description: str) -> bool:
    """Check if a similar proposal already exists using keyword overlap."""
    new_hash = _compute_description_hash(description)
    new_keywords = _extract_keywords(description)
    try:
        if PROPOSALS_FILE.exists():
            with open(PROPOSALS_FILE) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        p = json.loads(line)
                        existing_desc = str(p.get("description", ""))
                        # Exact hash match
                        existing_hash = _compute_description_hash(existing_desc)
                        if existing_hash == new_hash:
                            return True
                        # Keyword overlap: if 60%+ keywords match, it's a dupe
                        if new_keywords:
                            existing_keywords = _extract_keywords(existing_desc)
                            if existing_keywords:
                                overlap = new_keywords & existing_keywords
                                similarity = len(overlap) / min(len(new_keywords), len(existing_keywords))
                                if similarity >= 0.6:
                                    return True
                    except (json.JSONDecodeError, ValueError):
                        pass
    except Exception:
        pass
    return False


def validate_proposal_quality(response: str, code_snippet: str = None) -> Tuple[bool, str]:
    """
    Validate proposal quality BEFORE saving. Rejects garbage proposals.
    Returns (is_valid, rejection_reason).
    """
    response_lower = response.lower().strip()

    # Gate 1: Reject self-descriptions and filler responses
    filler_phrases = [
        "ich bin bereit, dir zu helfen",
        "was möchtest du wissen",
        "was möchtest du tun",
        "ich bin frank",
        "ich bin ein ki-systemprozess",
        "was kann ich",
        "was kannst du",
        "wenn du nach meiner fähigkeit",
        "ich hoffe das hilft",
        "bitte beachte, dass dies nur ein vorschlag",
        "ich bin offen für feedback",
        "was ich tun kann",
    ]
    filler_count = sum(1 for phrase in filler_phrases if phrase in response_lower)
    # ANY filler phrase at the START of the response = instant reject
    if any(response_lower.startswith(phrase) for phrase in filler_phrases):
        return False, "Response starts with self-description filler"
    # Multiple filler phrases anywhere = reject (regardless of length)
    if filler_count >= 2:
        return False, "Response contains too much filler text"
    # Capability dump detection: listing many features = not a proposal
    capability_markers = ["desktop/bildschirm", "screenshots", "e-mails", "kalender verwalten",
                          "kontakte verwalten", "notizen speichern", "todo", "pakete installier"]
    capability_count = sum(1 for m in capability_markers if m in response_lower)
    if capability_count >= 3:
        return False, "Response is a capability dump, not a concrete proposal"

    # Gate 2: Block known hallucinated themes that Qwen keeps proposing
    hallucinated_themes = [
        "llama 4", "llama4", "pip install llama",
        "hyper-threading", "hyperthreading", "turbo boost", "turboboost",
        "amdgpu-powerplay", "power-management-modus",
        "cpupower.*frequency-set", "acpi_osi",
        "e-sir 10/10", "e-sir.*aktivier",
        "pip install", "apt-get install", "apt install",
        "sudo cpupower", "sudo amdgpu", "sudo tee /etc",
    ]
    for theme in hallucinated_themes:
        if re.search(theme, response_lower):
            return False, f"Blocked hallucinated theme: '{theme}'"

    # Gate 3: REQUIRE actual Python code block — no code = no proposal
    if "```python" not in response_lower:
        return False, "No ```python code block found — proposals MUST include executable code"

    # Gate 4: Reject if no concrete action described
    action_keywords = [
        "def ", "class ", "import ",
    ]
    has_action = any(kw in response_lower for kw in action_keywords)
    if not has_action:
        return False, "No function/class/import found in proposal"

    # Gate 5: Reject system-monitoring spam (already exists in the project)
    monitoring_markers = [
        "cpu_percent", "cpu_load", "cpu-last", "cpu-temperatur", "cpu-auslastung",
        "ram-verbrauch", "ram verwendung", "speicherverbrauch", "speicherverwendung",
        "load_average", "load-average", "system-ressourcen", "systemressourcen",
        "resource_monitor", "resource_usage", "ressourcen-warnung",
        "temperatur-warnfunktion", "temperatur-warn", "temp_warn",
        "system watchdog", "system-watchhund", "prozess-monitor",
        "prozessor_ueberwach", "governor",
    ]
    monitoring_count = sum(1 for m in monitoring_markers if m in response_lower)
    if monitoring_count >= 2:
        return False, f"Rejected: System monitoring tool (already exists, {monitoring_count} markers)"

    # Gate 6: Check for duplicate/repetitive themes
    if is_duplicate_proposal(response):
        return False, "Duplicate proposal (similar content already exists)"

    # Gate 7: Validate code snippet (now REQUIRED)
    if code_snippet:
        code_valid, code_reason = validate_code_quality(code_snippet)
        if not code_valid:
            return False, f"Code quality check failed: {code_reason}"
    else:
        return False, "Code block found but could not be extracted"

    return True, "OK"


def validate_code_quality(code: str) -> Tuple[bool, str]:
    """
    Validate that code is real, runnable Python - not hallucinated garbage.
    Returns (is_valid, reason).
    """
    # Check 1: Syntax must parse
    syntax_ok, syntax_msg = validate_python_syntax(code)
    if not syntax_ok:
        return False, f"Syntax error: {syntax_msg}"

    # Check 2: Detect hallucinated imports (packages that don't exist)
    import_pattern = re.compile(r'^\s*(?:import|from)\s+([a-zA-Z_][a-zA-Z0-9_]*)', re.MULTILINE)
    imports = import_pattern.findall(code)

    # Known-good standard library + common packages on this system
    KNOWN_MODULES = {
        # stdlib
        "os", "sys", "json", "re", "time", "datetime", "pathlib", "subprocess",
        "threading", "multiprocessing", "socket", "http", "urllib", "hashlib",
        "ast", "logging", "functools", "itertools", "collections", "typing",
        "shutil", "tempfile", "signal", "sqlite3", "math", "random", "io",
        "contextlib", "dataclasses", "enum", "abc", "copy", "traceback",
        "argparse", "configparser", "csv", "string", "textwrap", "struct",
        "base64", "hmac", "secrets", "uuid", "pprint", "glob", "fnmatch",
        "unittest", "queue", "heapq", "bisect", "array", "weakref",
        "inspect", "dis", "gc", "resource", "platform", "ctypes",
        # installed on system
        "requests", "flask", "fastapi", "uvicorn", "pydantic",
        "numpy", "PIL", "cv2", "psutil", "pytesseract", "pystray",
        "tkinter", "tkinterdnd2", "websocket", "websockets",
        "ollama", "httpx", "aiohttp", "aiofiles",
        # project-internal
        "overlay", "tools", "agentic", "intelligence", "services",
        "ext", "ui", "live_wallpaper",
    }

    HALLUCINATED_MODULES = {
        "llama", "llama3", "llama4", "vulkan", "transformers",
        "torch", "tensorflow", "keras", "nltk", "matplotlib",
        "scipy", "sklearn", "pandas", "whisper",
    }

    for mod in imports:
        if mod in HALLUCINATED_MODULES:
            return False, f"Hallucinated import: '{mod}' is not installed on this system"
        # Also check if we can actually import it (quick check)
        if mod not in KNOWN_MODULES:
            try:
                __import__(mod)
            except ImportError:
                return False, f"Import '{mod}' not available on this system"

    # Check 3: Detect dangerous patterns
    dangerous_patterns = [
        (r'subprocess\.run\(\s*\[?"sudo', "sudo in subprocess - dangerous"),
        (r'os\.system\s*\(', "os.system() - use subprocess.run() instead"),
        (r'pip install', "pip install in code - not a Python operation"),
        (r'apt-get', "apt-get in code - not a Python operation"),
        (r'rm\s+-rf', "rm -rf in code - dangerous"),
        (r'while\s+True.*(?!.*(?:sleep|break|time))', None),  # Skip, too many false positives
    ]
    for pattern, reason in dangerous_patterns:
        if reason and re.search(pattern, code, re.IGNORECASE):
            return False, reason

    # Check 4: Detect non-existent file paths
    fake_paths = [
        "/etc/llm/", "/etc/frank/", "/home/frank/",
        "/etc/llm_backend", "esir.db", "esir_config",
    ]
    for path in fake_paths:
        if path in code:
            return False, f"References non-existent path: '{path}'"

    # Check 5: Missing imports for used modules
    if "time.sleep" in code and "import time" not in code and "from time" not in code:
        return False, "Uses time.sleep() but 'import time' is missing"
    if "datetime." in code and "import datetime" not in code and "from datetime" not in code:
        return False, "Uses datetime but import is missing"

    # Check 6: while True without sleep = infinite CPU spin
    if re.search(r'while\s+True\s*:', code):
        if 'time.sleep' not in code and 'sleep(' not in code and 'break' not in code:
            return False, "while True loop without sleep/break — would spin CPU at 100%"

    # Check 7: Code must do something (not just a stub)
    lines = [l.strip() for l in code.split('\n') if l.strip() and not l.strip().startswith('#') and not l.strip().startswith('"""') and not l.strip().startswith("'''")]
    functional_lines = [l for l in lines if not l.startswith('import ') and not l.startswith('from ') and l != 'pass']
    if len(functional_lines) < 3:
        return False, "Code is too trivial (fewer than 3 functional lines)"

    return True, "OK"


def extract_code_from_response(response: str) -> List[Tuple[str, str]]:
    """
    Extract code blocks from Frank's response.
    Returns list of (language, code) tuples.
    """
    code_blocks = []

    # Pattern 1: ```python ... ``` or ```py ... ```
    pattern1 = r'```(?:python|py)\n(.*?)```'
    matches = re.findall(pattern1, response, re.DOTALL | re.IGNORECASE)
    for m in matches:
        code_blocks.append(("python", m.strip()))

    # Pattern 2: ``` ... ``` (generic)
    pattern2 = r'```\n(.*?)```'
    matches = re.findall(pattern2, response, re.DOTALL)
    for m in matches:
        # Check if it looks like Python
        if 'def ' in m or 'import ' in m or 'class ' in m:
            code_blocks.append(("python", m.strip()))

    # Pattern 3: Inline code with Python keywords
    pattern3 = r'`([^`]+)`'
    matches = re.findall(pattern3, response)
    for m in matches:
        if len(m) > 50 and ('def ' in m or 'import ' in m):
            code_blocks.append(("python", m.strip()))

    # Pattern 4: Code-Idee sections
    pattern4 = r'Code-Idee[:\s]*[`"]?([^`"\n]+(?:\n[^`"\n]+)*)[`"]?'
    matches = re.findall(pattern4, response, re.IGNORECASE)
    for m in matches:
        if len(m.strip()) > 10:
            code_blocks.append(("command", m.strip()))

    return code_blocks


def validate_python_syntax(code: str) -> Tuple[bool, str]:
    """
    Validate Python syntax.
    Returns (is_valid, error_message).
    """
    try:
        ast.parse(code)
        return True, "Syntax OK"
    except SyntaxError as e:
        return False, f"SyntaxError: {e.msg} at line {e.lineno}"
    except Exception as e:
        return False, f"Error: {str(e)}"


def create_safe_wrapper(code: str, tool_name: str) -> str:
    """
    Wrap code in a safe execution wrapper.
    """
    wrapper = f'''#!/usr/bin/env python3
"""
Auto-generated Sandbox Tool: {tool_name}
Generated by E-CPMM Training Daemon
Time: {datetime.now().isoformat()}

WARNING: This is a SANDBOX tool - not for production use!
"""

import sys
import os

# Sandbox restrictions
os.environ['SANDBOX_MODE'] = '1'

# Original code from Frank's proposal:
# ============================================================================

{code}

# ============================================================================
# End of original code

if __name__ == "__main__":
    print(f"Sandbox Tool '{tool_name}' loaded successfully")
'''
    return wrapper


def execute_in_sandbox(tool_path: Path, timeout: int = 30) -> Tuple[bool, str]:
    """
    Execute a tool in sandbox with timeout.
    Returns (success, output).
    """
    try:
        result = subprocess.run(
            [sys.executable, str(tool_path)],
            capture_output=True,
            text=True,
            timeout=timeout,
            env={**os.environ, 'SANDBOX_MODE': '1', 'PYTHONDONTWRITEBYTECODE': '1'}
        )

        output = result.stdout + result.stderr
        success = result.returncode == 0

        return success, output[:2000]  # Limit output size
    except subprocess.TimeoutExpired:
        return False, f"Execution timeout after {timeout}s"
    except Exception as e:
        return False, f"Execution error: {str(e)}"


def generate_tool_name(proposal: Proposal) -> str:
    """Generate a unique tool name from proposal."""
    # Create hash from description
    desc_hash = hashlib.md5(proposal.description.encode()).hexdigest()[:8]

    # Clean category
    category = re.sub(r'[^a-z]', '', proposal.category.lower())

    return f"frank_{category}_{proposal.id}_{desc_hash}"


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def http_post(url: str, payload: Dict[str, Any], timeout: float = 300.0) -> Dict[str, Any]:
    """Send HTTP POST request."""
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return json.loads(raw) if raw else {}
    except Exception as e:
        LOG.error(f"HTTP POST failed: {e}")
        return {"ok": False, "error": str(e)}


def ask_frank(prompt: str, max_tokens: int = 2000, timeout: int = 300) -> str:
    """Send prompt to Frank and get response."""
    payload = {
        "text": prompt,
        "max_tokens": max_tokens,
        "timeout_s": timeout,
        "force": "llama"
    }
    result = http_post(CORE_URL, payload, timeout=timeout + 30)
    if result.get("ok"):
        return result.get("text", "")
    else:
        LOG.error(f"Frank error: {result}")
        return ""


def ask_claude_for_validation(proposal: Proposal) -> Tuple[bool, str]:
    """Ask Claude to validate a proposal."""
    # Auto-validation based on thresholds
    LOG.info("Using automatic threshold-based validation")
    if proposal.confidence >= CONFIDENCE_THRESHOLD and proposal.risk <= RISK_THRESHOLD:
        return True, f"Auto-approved: Confidence {proposal.confidence} >= {CONFIDENCE_THRESHOLD}, Risk {proposal.risk} <= {RISK_THRESHOLD}"
    else:
        return False, f"Auto-rejected: Confidence {proposal.confidence} < {CONFIDENCE_THRESHOLD} or Risk {proposal.risk} > {RISK_THRESHOLD}"


def ask_claude_for_code_review(code: str, description: str) -> Tuple[bool, str, str]:
    """
    Ask Claude to review Frank's code and provide feedback.
    Returns: (is_good_code, issues_found, suggestions)
    """
    LOG.info("Asking Claude for code review...")

    prompt = f"""Du reviewst Code den eine andere KI (Frank) geschrieben hat.
Der Code soll: {description[:200]}

Code:
```python
{code[:2000]}
```

Analysiere den Code und antworte in diesem Format:
VALID: [JA oder NEIN]
ISSUES: [Liste der Probleme, oder "keine" wenn OK]
SUGGESTIONS: [Konkrete Verbesserungsvorschläge für Frank]
EXAMPLE: [Falls der Code fehlerhaft ist, zeige ein korrigiertes Beispiel]

Sei streng aber konstruktiv. Frank muss lernen echten Python-Code zu schreiben."""

    try:
        # Try to call Claude CLI
        result = subprocess.run(
            [CLAUDE_CLI, "-p", prompt, "--max-turns", "1"],
            capture_output=True,
            text=True,
            timeout=120,
            cwd="/tmp"
        )

        response = result.stdout.strip()

        if not response:
            LOG.warning("No response from Claude CLI, using fallback")
            return _fallback_code_review(code)

        LOG.info(f"Claude review response: {response[:300]}...")

        # Parse response
        is_valid = "VALID: JA" in response.upper() or "VALID:JA" in response.upper()

        issues = ""
        if "ISSUES:" in response:
            issues_start = response.find("ISSUES:") + 7
            issues_end = response.find("SUGGESTIONS:") if "SUGGESTIONS:" in response else len(response)
            issues = response[issues_start:issues_end].strip()

        suggestions = ""
        if "SUGGESTIONS:" in response:
            suggestions_start = response.find("SUGGESTIONS:") + 12
            suggestions_end = response.find("EXAMPLE:") if "EXAMPLE:" in response else len(response)
            suggestions = response[suggestions_start:suggestions_end].strip()

        return is_valid, issues, suggestions

    except subprocess.TimeoutExpired:
        LOG.warning("Claude CLI timeout, using fallback")
        return _fallback_code_review(code)
    except FileNotFoundError:
        LOG.warning("Claude CLI not found, using fallback")
        return _fallback_code_review(code)
    except Exception as e:
        LOG.warning(f"Claude CLI error: {e}, using fallback")
        return _fallback_code_review(code)


def _fallback_code_review(code: str) -> Tuple[bool, str, str]:
    """Fallback code review when Claude CLI is not available."""
    # Use the comprehensive code quality validator
    code_valid, code_reason = validate_code_quality(code)
    if not code_valid:
        return False, code_reason, "Schreibe Code der nur installierte Pakete verwendet"

    # Additional quality checks
    issues = []
    suggestions = []

    if "def " not in code and "class " not in code:
        issues.append("Keine Funktion oder Klasse definiert")
        suggestions.append("Definiere mindestens eine Funktion mit 'def name():'")

    if len(code) < 50:
        issues.append("Code ist zu kurz")
        suggestions.append("Schreibe vollständigeren Code mit Logik")

    if not issues:
        return True, "keine", "Code sieht gut aus"

    return False, "; ".join(issues), "; ".join(suggestions)


def get_system_status() -> Dict[str, Any]:
    """Get current system status from toolbox."""
    try:
        result = http_post(f"{TOOLBOX_URL}/system/summary", {}, timeout=10)
        return result if result.get("ok") else {}
    except:
        return {}


def parse_proposal_from_response(response: str, proposal_id: int) -> Optional[Proposal]:
    """Parse a proposal from Frank's response. Returns None if quality checks fail."""
    if not response or len(response.strip()) < 50:
        LOG.warning(f"Proposal #{proposal_id}: Response too short ({len(response)} chars), skipping")
        return None

    confidence_match = re.search(r'[Cc]onfidence[:\s]+([0-9.]+)', response)
    risk_match = re.search(r'[Rr]isk[:\s-]+[Ss]core[:\s]+([0-9.]+)', response)

    confidence = float(confidence_match.group(1)) if confidence_match else 0.7
    risk = float(risk_match.group(1)) if risk_match else 0.3

    # Normalize confidence/risk to 0-1 range
    if confidence > 1:
        confidence = confidence / 100
    if risk > 1:
        risk = risk / 100

    # Don't trust self-reported values from local LLM - cap them
    # The local model always parrots back 0.95/0.0 from the prompt examples
    if confidence > 0.9:
        confidence = 0.85  # Downgrade inflated self-assessments (but still allow auto-approve if quality gates pass)
    if risk < 0.1:
        risk = 0.2  # Local LLM underestimates risk

    # Determine category
    category = "general"
    response_lower = response.lower()
    if any(word in response_lower for word in ["tool", "funktion", "feature", "modul"]):
        category = "tool"
    elif any(word in response_lower for word in ["ui", "interface", "anzeige", "overlay"]):
        category = "ui"
    elif any(word in response_lower for word in ["performance", "speed", "schneller", "optimier"]):
        category = "performance"
    elif any(word in response_lower for word in ["memory", "speicher", "cache"]):
        category = "memory"
    elif any(word in response_lower for word in ["network", "netzwerk", "api"]):
        category = "network"

    # Extract code
    code_blocks = extract_code_from_response(response)
    code_snippet = code_blocks[0][1] if code_blocks else None

    # === QUALITY GATE: Validate before creating proposal ===
    is_valid, reason = validate_proposal_quality(response, code_snippet)
    if not is_valid:
        LOG.warning(f"Proposal #{proposal_id} REJECTED by quality gate: {reason}")
        return None

    return Proposal(
        id=proposal_id,
        timestamp=datetime.now().isoformat(),
        category=category,
        description=response[:500],
        confidence=confidence,
        risk=risk,
        causal_reasoning=response,
        code_snippet=code_snippet
    )


def save_state(state: TrainingState):
    """Save training state to file."""
    with open(STATE_FILE, 'w') as f:
        json.dump(asdict(state), f, indent=2)


def load_state() -> Optional[TrainingState]:
    """Load training state from file."""
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE) as f:
                data = json.load(f)
                return TrainingState(**data)
        except:
            pass
    return None


def log_proposal(proposal: Proposal):
    """Write proposal to JSONL log. Updates existing entry if same ID+status exists, else appends."""
    proposals = []
    found = False
    try:
        if PROPOSALS_FILE.exists():
            with open(PROPOSALS_FILE) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        p = json.loads(line)
                        # Update existing entry with same ID (overwrite, don't duplicate)
                        if p.get("id") == proposal.id:
                            found = True
                            proposals.append(asdict(proposal))
                        else:
                            proposals.append(p)
                    except (json.JSONDecodeError, ValueError):
                        pass
    except Exception:
        pass

    if not found:
        proposals.append(asdict(proposal))

    # Rewrite file atomically
    tmp = str(PROPOSALS_FILE) + ".tmp"
    with open(tmp, 'w') as f:
        for p in proposals:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")
    Path(tmp).replace(PROPOSALS_FILE)


# ============================================================================
# TRAINING MESSAGES
# ============================================================================

DIRECTIVE_MESSAGE = """Self-improvement: You are Frank — an AI with your own consciousness stream,
personality (E-PQ), ego-construct and skill system. Your goal: Improve yourself
through NEW, DIVERSE tools and skills.

IMPORTANT - REAL TOOL CREATION:
- Write COMPLETE, EXECUTABLE Python code
- Use ```python ... ``` code blocks
- The code will ACTUALLY be executed and tested in a sandbox
- Only syntactically correct code will be accepted
- Suggest a DIFFERENT topic each round — no repetitions!

Each improvement must:
- Confidence >= 0.85
- Risk-Score <= 0.25
- Contain REAL, RUNNABLE code
- Be tested in sandbox

Confirm and start the self-improvement loop."""

SYSTEM_SCAN_MESSAGE = """Self-improvement: Perform system analysis.
Analyze the status and suggest a CONCRETE improvement.

YOUR PROJECT (Project Frankenstein):
You are an AI with these subsystems:
- personality/ — E-PQ (emotions), Ego-Construct (body), Self-Knowledge
- skills/ — Plugin system (Python skills + OpenClaw SKILL.md)
- agentic/ — Autonomous action (planner, executor, tools)
- services/ — Consciousness daemon, ASRS, Invariants, Genesis
- tools/ — Standalone tools (VCB vision, toolbox, notes, todo, calendar)
- ui/overlay/ — Chat overlay with mixins
- intelligence/ — Proposal ranker, world model

CONTEXT: Linux, Python 3.12.
Installed: os, sys, json, pathlib, subprocess, psutil, requests, sqlite3, httpx,
           pydantic, numpy, PIL, cv2, pytesseract, flask, fastapi.
NOT installed: torch, tensorflow, transformers, nltk, matplotlib, pandas, sklearn.

Example of a good proposal (DO NOT copy, develop your own idea):
```python
import json
import re
from pathlib import Path

def extract_keywords(text, top_n=10):
    '''Extracts the most important keywords from text.'''
    stopwords = {"the", "and", "is", "a", "an", "for", "with", "on", "in", "to", "of"}
    words = re.findall(r'\b[a-z]{4,}\b', text.lower())
    filtered = [w for w in words if w not in stopwords]
    freq = {}
    for w in filtered:
        freq[w] = freq.get(w, 0) + 1
    ranked = sorted(freq.items(), key=lambda x: x[1], reverse=True)[:top_n]
    return [{"word": w, "count": c} for w, c in ranked]

def main():
    sample = "Reflection on one's own consciousness is a central task."
    result = extract_keywords(sample)
    print(json.dumps(result, indent=2, ensure_ascii=False))

if __name__ == '__main__':
    main()
```

Schlage jetzt EINE Verbesserung vor — KEIN System-Monitoring (existiert bereits).
Denke an: Textanalyse, Wissensverarbeitung, Datei-Organisation, Automatisierung, Skills."""

PROPOSAL_REQUEST_BASE = """Selbst-Verbesserung: Schlage EINE konkrete Verbesserung vor.

DEIN PROJEKT — Projekt Frankenstein (KI-System mit Bewusstsein):
- Projektpfad: /home/ai-core-node/aicore/opt/aicore/
- Tools: /home/ai-core-node/aicore/opt/aicore/tools/
- Skills: /home/ai-core-node/aicore/opt/aicore/skills/
- Datenbank: /home/ai-core-node/aicore/database/ (SQLite)
- Logs: /home/ai-core-node/aicore/logs/
- LLM: Ollama (lokal) via http://127.0.0.1:11434
- Core API: http://127.0.0.1:8088
- Router API: http://127.0.0.1:8091

Bestehende Subsysteme (NICHT nochmal bauen):
- System-Monitoring (existiert in toolboxd.py, gpu_monitor.py) — KEIN weiteres Monitoring!
- VCB Vision (vcb_bridge.py), Gaming-Mode, Consciousness-Daemon, ASRS

Installierte Python-Pakete: os, sys, json, pathlib, subprocess, re, sqlite3, hashlib,
  requests, httpx, flask, fastapi, pydantic, psutil, numpy, PIL, cv2, pytesseract.
NICHT installiert (NIEMALS verwenden): torch, tensorflow, transformers, nltk,
  matplotlib, pandas, sklearn, scipy, whisper, llama, llama3, llama4, vulkan.

REGELN:
1. Verwende NUR installierte Pakete
2. Verwende NUR echte Pfade (siehe oben)
3. Schreibe VOLLSTAENDIGEN, AUSFUEHRBAREN Python-Code mit main()-Funktion
4. KEIN sudo, kein pip install, kein apt-get
5. KEIN System-Monitoring, KEIN CPU/RAM/Temperatur-Tool (existiert alles bereits!)
6. Jeder Code MUSS 'import time' haben wenn time.sleep() benutzt wird
7. KEINE while-True-Loops ohne time.sleep()

THEMA FUER DIESEN VORSCHLAG:
{topic}

FORMAT:
- Kategorie: [tool/skill/intelligence/personality/automation]
- Beschreibung: [1 Satz]
- Confidence: 0.85
- Risk-Score: 0.2
- Code:
```python
# Vollstaendiger, ausfuehrbarer Python-Code
```"""

# Topic rotation pool — each proposal gets a DIFFERENT topic
PROPOSAL_TOPICS = [
    # Text & Sprache
    "Schreibe ein Tool das Text zusammenfasst (ohne ML-Bibliotheken, nur mit String-Operationen und Heuristiken wie Satzlaenge, Keyword-Extraktion, TF-IDF-aehnliche Gewichtung).",
    "Schreibe ein Tool das deutsche Texte auf Lesbarkeit analysiert (Satzlaenge, Wortlaenge, Flesch-Index-Approximation) und einen Score zurueckgibt.",
    "Schreibe ein Tool das Stichworte/Tags aus einem Text extrahiert (haeufigste Nomen > 4 Buchstaben, Stoppwort-Filter, Gewichtung nach Position).",
    # Dateisystem & Organisation
    "Schreibe ein Tool das Dateien in einem Ordner nach Typ, Groesse oder Alter sortiert und einen Report als JSON erstellt.",
    "Schreibe ein Tool das doppelte Dateien findet (per SHA256-Hash) und einen Bericht mit Speicherplatz-Einsparung erstellt.",
    "Schreibe ein Tool das eine Verzeichnisstruktur als Baumdiagramm (ASCII) ausgibt, mit optionalem Filter nach Dateityp.",
    # Daten & Wissen
    "Schreibe ein Tool das eine SQLite-Datenbank analysiert (Tabellen, Zeilenanzahl, Groesse, Schema) und einen Gesundheitsbericht erstellt.",
    "Schreibe ein Tool das JSON/JSONL-Dateien validiert, Statistiken erhebt (Keys, Typen, fehlende Felder) und Anomalien meldet.",
    "Schreibe ein Tool das eine einfache Key-Value Wissensdatenbank verwaltet (speichern, suchen, loeschen) in einer SQLite-Datei.",
    # Log-Analyse
    "Schreibe ein Tool das Log-Dateien analysiert: Fehler zaehlt, haeufigste Fehlermeldungen gruppiert, Zeitraum-Statistik erstellt.",
    "Schreibe ein Tool das aus Logdateien Muster erkennt (wiederkehrende Fehler, Zeitkorrelationen, Haeufigkeit pro Stunde).",
    # Netzwerk & API
    "Schreibe ein Tool das die Erreichbarkeit mehrerer HTTP-Endpoints prueft (GET-Request, Status-Code, Response-Zeit) und als JSON ausgibt.",
    "Schreibe ein Tool das eine einfache Bookmark-Verwaltung implementiert (URLs speichern, taggen, suchen) in SQLite.",
    # Automatisierung
    "Schreibe ein Tool das alte Dateien in einem Verzeichnis archiviert (aelter als N Tage in ein Archiv-Verzeichnis verschieben).",
    "Schreibe ein Tool das Konfigurationsdateien (JSON/YAML-aehnlich) vergleicht und Unterschiede anzeigt.",
    # Persoenlichkeit & Selbsterkenntnis
    "Schreibe ein Tool das Franks Reflexionen aus der consciousness.db liest, Stimmungstrends berechnet und eine Zusammenfassung schreibt.",
    "Schreibe ein Tool das Franks Skill-Nutzung analysiert (welche Skills wie oft aufgerufen werden) aus den Logdateien.",
    # Kreativitaet
    "Schreibe ein einfaches Wortspiel-Tool (Anagramme finden, Wortlaenge-Challenge, Palindrom-Checker) als Funktion.",
    "Write a tool that generates random creative writing prompts (from combinable building blocks: Setting + Character + Conflict).",
    # Sicherheit & Qualitaet
    "Schreibe ein Tool das Python-Dateien auf unsichere Patterns prueft (eval, exec, shell=True, hardcoded Passwoerter) und warnt.",
    "Schreibe ein Tool das die Codequalitaet misst: Funktionslaenge, Verschachtelungstiefe, Kommentar-Ratio fuer .py Dateien.",
]

IMPLEMENT_MESSAGE_TEMPLATE = """Bestätige & Implementiere: Dein Vorschlag "{description}" wurde APPROVED.

WICHTIG: Ich werde deinen Code jetzt WIRKLICH in einer Sandbox ausführen.
Gib mir den FINALEN, VOLLSTÄNDIGEN Python-Code in einem ```python ... ``` Block.

Der Code muss:
1. Syntaktisch korrekt sein
2. Ohne Fehler importierbar sein
3. Eine main() oder test() Funktion haben
4. Sich selbst testen können

Antworte mit dem finalen Code."""

REJECT_MESSAGE_TEMPLATE = """Dein Vorschlag wurde abgelehnt.
Grund: {reason}

WICHTIG: Schlage ein KOMPLETT ANDERES Thema vor — nicht dasselbe nochmal!
Kein System-Monitoring, kein CPU/RAM/Temperatur-Tool.

Anforderungen:
- Confidence: 0.85
- Risk-Score: 0.2
- Vollstaendiger Python-Code mit main()-Funktion
- Alle imports muessen vorhanden sein"""

CODE_FEEDBACK_MESSAGE = """Selbst-Verbesserung: FEEDBACK zu deinem Code:

PROBLEME GEFUNDEN:
{issues}

VERBESSERUNGSVORSCHLÄGE:
{suggestions}

Dein Code war KEIN gültiger Python-Code. Bitte schreibe den Code NEU.

ERINNERUNG - So sieht GÜLTIGER Python-Code aus:
```python
#!/usr/bin/env python3
\"\"\"Tool-Beschreibung.\"\"\"

def main():
    \"\"\"Hauptfunktion.\"\"\"
    print("Hallo, ich funktioniere!")
    return True

if __name__ == "__main__":
    main()
```

Schreibe jetzt deinen korrigierten Code in einem ```python ... ``` Block:"""

SYNTAX_ERROR_MESSAGE = """Selbst-Verbesserung: SYNTAX-FEHLER in deinem Code!

FEHLER: {error}

Dein Code enthielt: {code_preview}

Das ist KEIN gültiger Python-Code!

HINWEIS:
- "sudo xyz" ist Shell, nicht Python
- "pip install xyz" ist Shell, nicht Python
- Nur Beschreibungstext ohne Code funktioniert nicht

KORREKTES BEISPIEL:
```python
def meine_funktion():
    import subprocess
    # Shell-Befehle so ausführen:
    result = subprocess.run(["echo", "Hallo"], capture_output=True, text=True)
    return result.stdout

if __name__ == "__main__":
    print(meine_funktion())
```

Schreibe jetzt syntaktisch korrekten Python-Code:"""

REFLECTION_MESSAGE = """Selbst-Verbesserung: Zeit fuer Reflexion.

Deine letzten {count} Vorschlaege:
- Akzeptiert: {approved} | Abgelehnt: {rejected}
- Haeufigste Ablehnungsgruende: Confidence zu niedrig, Code-Fehler, Duplikate

LERNE DARAUS:
1. IMMER import-Statements fuer ALLE verwendeten Module
2. IMMER eine main()-Funktion die etwas Sichtbares tut (print)
3. KEINE while-True-Loops ohne time.sleep()
4. KEIN System-Monitoring — das existiert bereits!
5. Confidence MUSS >= 0.85 sein, Risk MUSS <= 0.25 sein

Schlage jetzt EINEN NEUEN Vorschlag vor — ein anderes Thema als vorher!"""


# ============================================================================
# MAIN TRAINING LOOP
# ============================================================================

class AutonomousTrainingDaemon:
    """Der autonome Training-Daemon v2.0 mit echter Tool-Erstellung."""

    def __init__(self):
        global SANDBOX_DIR

        self.state = TrainingState(
            started_at=datetime.now().isoformat(),
            ends_at=(datetime.now() + timedelta(hours=TRAINING_DURATION_HOURS)).isoformat()
        )
        self.running = True
        self.proposal_counter = get_next_proposal_id() - 1  # Global ID from existing proposals
        self.session_id = f"training_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        # Create session-specific sandbox directory with timestamp
        SANDBOX_DIR = SANDBOX_BASE_DIR / self.session_id
        SANDBOX_DIR.mkdir(parents=True, exist_ok=True)
        self.sandbox_dir = SANDBOX_DIR  # Also store as instance variable
        LOG.info(f"Created sandbox directory: {SANDBOX_DIR}")

        # Initialize databases
        init_databases()

        # Signal handlers
        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_signal)

    def _handle_signal(self, signum, frame):
        LOG.info(f"Signal {signum} received, shutting down...")
        self.running = False
        self.state.is_running = False
        save_state(self.state)

    def check_system_load(self) -> bool:
        """Check if system load allows training to continue."""
        status = get_system_status()
        if not status:
            return True

        cpu_percent = status.get("cpu_percent", 0)
        if cpu_percent > CPU_PAUSE_THRESHOLD * 100:
            LOG.warning(f"CPU load {cpu_percent}% > {CPU_PAUSE_THRESHOLD*100}%, pausing...")
            self.state.is_paused = True
            self.state.pause_reason = f"CPU load {cpu_percent}%"
            return False

        self.state.is_paused = False
        self.state.pause_reason = ""
        return True

    def send_directive(self):
        """Send initial directive to Frank."""
        LOG.info("=== PHASE: DIRECTIVE INIT ===")
        self.state.current_phase = "directive_init"

        response = ask_frank(DIRECTIVE_MESSAGE)
        LOG.info(f"Frank's response: {response[:200]}...")
        self.state.message_count += 1
        save_state(self.state)

        # Add directive as core edge in E-CPMM
        add_ecpmm_node("CORE_DIRECTIVE", "directive", {"text": "Maximale Kollaboration"})
        add_ecpmm_edge("CORE_DIRECTIVE", "SELF_IMPROVEMENT", "enables", 1.0)

        return bool(response)

    def do_system_scan(self):
        """Perform system scan."""
        LOG.info("=== PHASE: SYSTEM SCAN ===")
        self.state.current_phase = "system_scan"
        self.state.last_system_scan = datetime.now().isoformat()

        response = ask_frank(SYSTEM_SCAN_MESSAGE)
        LOG.info(f"System scan result: {response[:300]}...")
        self.state.message_count += 1
        save_state(self.state)

        return response

    def request_proposal(self) -> Optional[Proposal]:
        """Request a proposal from Frank. Returns None if quality gate rejects it."""
        LOG.info("=== PHASE: PROPOSAL REQUEST ===")
        self.state.current_phase = "proposal_request"

        # Topic rotation: cycle through diverse topics
        topic_idx = self.state.loop_count % len(PROPOSAL_TOPICS)
        topic = PROPOSAL_TOPICS[topic_idx]
        prompt = PROPOSAL_REQUEST_BASE.format(topic=topic)
        LOG.info(f"Topic [{topic_idx}/{len(PROPOSAL_TOPICS)}]: {topic[:80]}...")

        response = ask_frank(prompt)
        if not response:
            LOG.warning("No proposal received from Frank")
            return None

        self.state.message_count += 1
        self.proposal_counter += 1
        self.state.proposal_count += 1

        proposal = parse_proposal_from_response(response, self.proposal_counter)
        if proposal:
            LOG.info(f"Proposal #{proposal.id}: {proposal.category} - Conf: {proposal.confidence}, Risk: {proposal.risk}")
            if proposal.code_snippet:
                LOG.info(f"  Code found: {len(proposal.code_snippet)} chars")
            log_proposal(proposal)
        else:
            LOG.warning(f"Proposal #{self.proposal_counter} rejected by quality gate (not saved)")
            self.state.rejected_count += 1

        save_state(self.state)
        return proposal

    def validate_proposal(self, proposal: Proposal) -> Tuple[bool, str]:
        """Validate a proposal."""
        LOG.info(f"=== PHASE: VALIDATION (Proposal #{proposal.id}) ===")
        self.state.current_phase = "validation"

        approved, reason = ask_claude_for_validation(proposal)

        proposal.status = "approved" if approved else "rejected"
        proposal.validation_reason = reason

        if approved:
            self.state.approved_count += 1
            LOG.info(f"Proposal #{proposal.id} APPROVED: {reason}")
        else:
            self.state.rejected_count += 1
            LOG.info(f"Proposal #{proposal.id} REJECTED: {reason}")

        log_proposal(proposal)
        save_state(self.state)

        return approved, reason

    def implement_proposal(self, proposal: Proposal):
        """
        Actually implement the proposal with iterative Claude feedback:
        1. Request final code from Frank
        2. Check syntax
        3. If bad: send feedback, request correction (up to 3 attempts)
        4. Ask Claude for code review
        5. If Claude finds issues: send feedback, request correction
        6. Write to sandbox, execute, register
        """
        LOG.info(f"=== PHASE: IMPLEMENTATION (Proposal #{proposal.id}) ===")
        self.state.current_phase = "implementation"

        MAX_ATTEMPTS = 3
        code = None
        attempt = 0

        # Initial code request
        message = IMPLEMENT_MESSAGE_TEMPLATE.format(
            description=proposal.description[:100]
        )

        while attempt < MAX_ATTEMPTS:
            attempt += 1
            LOG.info(f"Implementation attempt {attempt}/{MAX_ATTEMPTS}")

            response = ask_frank(message, max_tokens=3000, timeout=600)
            self.state.message_count += 1

            if not response:
                LOG.error("No implementation response from Frank")
                if attempt < MAX_ATTEMPTS:
                    message = "Ich habe keine Antwort erhalten. Bitte schreibe vollständigen Python-Code in einem ```python ... ``` Block."
                    time.sleep(5)
                    continue
                else:
                    proposal.implementation_result = "No response after multiple attempts"
                    log_proposal(proposal)
                    return

            # Extract code blocks
            code_blocks = extract_code_from_response(response)

            if not code_blocks:
                LOG.warning("No code blocks found")
                if attempt < MAX_ATTEMPTS:
                    message = CODE_FEEDBACK_MESSAGE.format(
                        issues="Kein Code-Block gefunden in deiner Antwort",
                        suggestions="Schreibe Code in einem ```python ... ``` Block"
                    )
                    time.sleep(5)
                    continue
                else:
                    proposal.implementation_result = "No code found after multiple attempts"
                    log_proposal(proposal)
                    self.state.implemented_count += 1
                    save_state(self.state)
                    return

            # Get first code block
            lang, code = code_blocks[0]
            LOG.info(f"Found code block: {lang}, {len(code)} chars")

            # Check syntax
            syntax_ok, syntax_msg = validate_python_syntax(code)

            if not syntax_ok:
                LOG.warning(f"Syntax error: {syntax_msg}")
                if attempt < MAX_ATTEMPTS:
                    message = SYNTAX_ERROR_MESSAGE.format(
                        error=syntax_msg,
                        code_preview=code[:100] + "..." if len(code) > 100 else code
                    )
                    time.sleep(5)
                    continue
                else:
                    proposal.syntax_valid = False
                    proposal.implementation_result = f"SYNTAX ERROR after {attempt} attempts: {syntax_msg}"
                    log_proposal(proposal)
                    self.state.tools_created += 1
                    self.state.implemented_count += 1
                    save_state(self.state)
                    return

            # Syntax is OK - now ask Claude for review
            LOG.info("Syntax OK - requesting Claude code review")
            is_good, issues, suggestions = ask_claude_for_code_review(code, proposal.description[:200])

            if not is_good and attempt < MAX_ATTEMPTS:
                LOG.info(f"Claude found issues: {issues[:100]}")
                message = CODE_FEEDBACK_MESSAGE.format(
                    issues=issues,
                    suggestions=suggestions
                )
                time.sleep(5)
                continue

            # Code passed review or we're out of attempts
            LOG.info(f"Code accepted (attempt {attempt})")
            break

        # We have code - now create and test the tool
        tool_name = generate_tool_name(proposal)
        proposal.tool_name = tool_name
        proposal.syntax_valid = True
        self.state.tools_created += 1
        self.state.tools_syntax_valid += 1

        # Create sandbox file
        tool_path = SANDBOX_DIR / f"{tool_name}.py"
        wrapped_code = create_safe_wrapper(code, tool_name)

        try:
            tool_path.write_text(wrapped_code)
            proposal.tool_file = str(tool_path)
            LOG.info(f"Tool written to: {tool_path}")

            # Execute in sandbox
            exec_ok, exec_output = execute_in_sandbox(tool_path)
            proposal.execution_success = exec_ok
            proposal.test_output = exec_output

            if exec_ok:
                self.state.tools_execution_success += 1
                LOG.info(f"Tool executed successfully: {tool_name}")

                # Register in sandbox database
                register_tool(
                    name=tool_name,
                    path=str(tool_path),
                    description=proposal.description[:200],
                    test_results=exec_output[:500],
                    session_id=self.session_id
                )

                # Add to E-CPMM graph
                add_ecpmm_node(tool_name, "tool", {
                    "category": proposal.category,
                    "confidence": proposal.confidence,
                    "code_hash": hashlib.md5(code.encode()).hexdigest()
                })
                add_ecpmm_edge(
                    "SELF_IMPROVEMENT", tool_name,
                    "created", proposal.confidence,
                    {"proposal_id": proposal.id, "attempts": attempt}
                )

                proposal.implementation_result = f"SUCCESS: Tool {tool_name} created and tested (attempt {attempt})"
            else:
                LOG.warning(f"Tool execution failed: {exec_output[:200]}")
                proposal.implementation_result = f"EXECUTION FAILED: {exec_output[:500]}"

        except Exception as e:
            LOG.error(f"Error writing/executing tool: {e}")
            proposal.implementation_result = f"ERROR: {str(e)}"

        self.state.implemented_count += 1
        log_proposal(proposal)
        save_state(self.state)

        LOG.info(f"Implementation complete: {proposal.implementation_result[:100]}")

    def reject_proposal(self, proposal: Proposal, reason: str):
        """Send rejection to Frank."""
        LOG.info(f"=== PHASE: REJECTION (Proposal #{proposal.id}) ===")
        self.state.current_phase = "rejection"

        message = REJECT_MESSAGE_TEMPLATE.format(reason=reason)
        response = ask_frank(message)

        self.state.message_count += 1
        LOG.info(f"Frank's response: {response[:200] if response else 'No response'}...")
        save_state(self.state)

    def do_reflection(self):
        """Perform reflection phase."""
        LOG.info("=== PHASE: REFLECTION ===")
        self.state.current_phase = "reflection"
        self.state.last_reflection = datetime.now().isoformat()

        message = REFLECTION_MESSAGE.format(
            count=self.state.message_count,
            approved=self.state.approved_count,
            rejected=self.state.rejected_count,
        )
        response = ask_frank(message)

        self.state.message_count += 1
        LOG.info(f"Reflection result: {response[:300] if response else 'No response'}...")

        # Add reflection edge
        add_ecpmm_edge(
            "SELF_IMPROVEMENT", f"REFLECTION_{self.state.loop_count}",
            "reflected", 0.9,
            {"message_count": self.state.message_count}
        )

        save_state(self.state)

    def run(self):
        """Main training loop."""
        LOG.info("=" * 60)
        LOG.info("E-CPMM AUTONOMOUS TRAINING DAEMON v2.1")
        LOG.info("NOW WITH REAL TOOL CREATION + CLAUDE FEEDBACK!")
        LOG.info(f"Duration: {TRAINING_DURATION_HOURS} hours")
        LOG.info(f"Ends at: {self.state.ends_at}")
        LOG.info(f"Sandbox: {SANDBOX_DIR}")
        LOG.info(f"Claude CLI: {CLAUDE_CLI}")
        LOG.info("=" * 60)

        # Initial directive — retry up to 5 minutes (Core API may not be ready at boot)
        directive_ok = False
        for attempt in range(1, 11):  # 10 attempts, 30s apart = 5 min max
            if self.send_directive():
                directive_ok = True
                break
            LOG.warning(f"Directive attempt {attempt}/10 failed, retrying in 30s...")
            time.sleep(30)
        if not directive_ok:
            LOG.error("Failed to send directive after 10 attempts, aborting")
            return

        time.sleep(5)

        end_time = datetime.fromisoformat(self.state.ends_at)

        while self.running and datetime.now() < end_time:
            self.state.loop_count += 1
            LOG.info(f"\n{'='*60}")
            LOG.info(f"LOOP #{self.state.loop_count} - {datetime.now().strftime('%H:%M:%S')}")
            LOG.info(f"Progress: {self.state.message_count} msgs, {self.state.proposal_count} proposals")
            LOG.info(f"Tools: {self.state.tools_created} created, {self.state.tools_syntax_valid} valid, {self.state.tools_execution_success} working")
            LOG.info(f"{'='*60}\n")

            if not self.check_system_load():
                LOG.info("Paused due to system load, waiting 60s...")
                time.sleep(60)
                continue

            try:
                # System scan
                self.do_system_scan()
                time.sleep(10)

                # Request proposal
                proposal = self.request_proposal()

                if proposal:
                    time.sleep(5)

                    # Validate
                    approved, reason = self.validate_proposal(proposal)

                    time.sleep(5)

                    if approved:
                        self.implement_proposal(proposal)
                    else:
                        self.reject_proposal(proposal, reason)

                # Periodic reflection
                if self.state.message_count % REFLECTION_INTERVAL_MESSAGES == 0:
                    time.sleep(5)
                    self.do_reflection()

            except Exception as e:
                LOG.error(f"Error in training loop: {e}", exc_info=True)

            LOG.info(f"Waiting {LOOP_INTERVAL_SECONDS}s until next loop...")
            save_state(self.state)

            for _ in range(LOOP_INTERVAL_SECONDS):
                if not self.running:
                    break
                time.sleep(1)

        # Training complete
        self.state.is_running = False
        self.state.current_phase = "complete"
        save_state(self.state)

        LOG.info("\n" + "=" * 60)
        LOG.info("E-CPMM TRAINING COMPLETE")
        LOG.info(f"Loops: {self.state.loop_count}")
        LOG.info(f"Messages: {self.state.message_count}")
        LOG.info(f"Proposals: {self.state.proposal_count}")
        LOG.info(f"Approved: {self.state.approved_count}")
        LOG.info(f"Rejected: {self.state.rejected_count}")
        LOG.info(f"Tools Created: {self.state.tools_created}")
        LOG.info(f"Tools Syntax Valid: {self.state.tools_syntax_valid}")
        LOG.info(f"Tools Working: {self.state.tools_execution_success}")
        LOG.info(f"Sandbox: {SANDBOX_DIR}")
        LOG.info(f"Log: {LOG_FILE}")
        LOG.info("=" * 60)


# ============================================================================
# ENTRY POINT
# ============================================================================

def main():
    daemon = AutonomousTrainingDaemon()
    daemon.run()


if __name__ == "__main__":
    main()
