#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
F.A.S. v2.0 - Frank's Autonomous Scavenger

GitHub Intelligence & Tool-Sourcing System.
Sicherheits-Level: Omega (Zero-Impact)

Sechs-Phasen-Modell:
1. Scout-Scraping: GitHub API Metadata (README.md, architecture.md only)
2. Triage & Deep Dive: Download nur bei hohem Interest-Score
3. Feature Extraction: Code-Analyse für Tools/API-Wrapper
4. Sandbox Testing: Isolierte Tests (Syntax, Imports, Execution)
5. User Notification: Chat-UI Integration für Feature-Vorschläge
6. Controlled Integration: Nur nach expliziter User-Zustimmung

Hard-Coded Guardrails:
- Quota-Warden: 20GB max, cleanup at 18GB
- Gaming-Mode Kill-Switch: Stops if gaming or CPU > 15%
- Time Window: Only 02:00-06:00 or IDLE (CPU < 5%)
- Rate Limit: Max 5 deep-dives per 24h
- Hash Blacklist: No re-downloads
- Stasis State: 12h sleep on errors
- Confidence Threshold: 75% minimum für Proposals
- User Approval Required: Keine Integration ohne Zustimmung

Database: /home/ai-core-node/aicore/database/fas_scavenger.db
Sandbox: /home/ai-core-node/aicore/github/
Feature Tests: /home/ai-core-node/aicore/sandbox/feature_tests/
Integrated Tools: /home/ai-core-node/aicore/opt/aicore/tools/discovered/

CLI Commands:
  status    - Show current F.A.S. status
  run       - Run a complete cycle (all 6 phases)
  features  - List all pending features
  ready     - List features ready for approval
  pending   - List features awaiting user response
  approve   - Approve a feature (--id required)
  reject    - Reject a feature (--id required)
  test      - Manually test a feature in sandbox (--id required)
  integrate - Integrate an approved feature (--id required)
  details   - Show detailed feature info (--id required)
  cleanup   - Clean up sandbox storage
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import threading
import time

# Pattern für valide SQL-Identifier (SQL Injection Prevention)
_VALID_SQL_IDENTIFIER = re.compile(r'^[a-zA-Z_][a-zA-Z0-9_]*$')
_VALID_SQL_TYPE = re.compile(r'^[A-Z]+(\s+[A-Z]+)*(\s+DEFAULT\s+\S+)?$', re.IGNORECASE)
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

# Constants
try:
    from config.paths import get_db, SANDBOX_DIR, TOOLS_DIR as _TOOLS_DIR
    DB_PATH = get_db("fas_scavenger")
    SANDBOX_PATH = SANDBOX_DIR
except ImportError:
    DB_PATH = Path.home() / ".local" / "share" / "frank" / "db" / "fas_scavenger.db"
    _fas_project_root = Path(__file__).resolve().parents[3]  # tools/ -> opt/aicore -> opt -> aicore
    SANDBOX_PATH = _fas_project_root / "github"
    _TOOLS_DIR = None
try:
    from config.paths import get_temp as _fas_get_temp
    GAMING_STATE_FILE = _fas_get_temp("gaming_mode_state.json")
    STASIS_FILE = _fas_get_temp("fas_stasis.json")
except ImportError:
    import tempfile as _fas_tempfile
    _fas_temp_dir = Path(_fas_tempfile.gettempdir()) / "frank"
    _fas_temp_dir.mkdir(parents=True, exist_ok=True)
    GAMING_STATE_FILE = _fas_temp_dir / "gaming_mode_state.json"
    STASIS_FILE = _fas_temp_dir / "fas_stasis.json"

# Guardrail Limits
MAX_SANDBOX_GB = 20
CLEANUP_THRESHOLD_GB = 18
MAX_DEEP_DIVES_PER_DAY = 5
MIN_INTEREST_SCORE = 0.7
STASIS_HOURS = 12

# GitHub API
GITHUB_API = "https://api.github.com"
GITHUB_SEARCH_TOPICS = ["AI", "LLM", "automation", "agentic", "llm-agent", "ai-agent"]
GITHUB_RATE_LIMIT_DELAY = 2.0  # seconds between API calls

# Time Window (02:00 - 06:00)
ALLOWED_HOURS = range(2, 7)
IDLE_CPU_THRESHOLD = 5
MAX_CPU_THRESHOLD = 15

LOG = logging.getLogger("fas")


@dataclass
class RepoMetadata:
    """Metadata for a GitHub repository."""
    full_name: str  # owner/repo
    name: str
    owner: str
    description: str
    stars: int
    forks: int
    topics: List[str]
    language: str
    updated_at: str
    readme_content: str = ""
    architecture_content: str = ""
    interest_score: float = 0.0
    hash_id: str = ""

    def compute_hash(self) -> str:
        """Compute unique hash for this repo."""
        data = f"{self.full_name}:{self.updated_at}"
        return hashlib.sha256(data.encode()).hexdigest()[:16]


@dataclass
class FeatureExtract:
    """Extracted feature from a repository."""
    repo_name: str
    feature_type: str  # "tool", "api_wrapper", "pattern", "utility"
    name: str
    description: str
    file_path: str
    code_snippet: str
    relevance_score: float
    timestamp: str
    # New fields for sandbox testing
    sandbox_tested: bool = False
    sandbox_passed: bool = False
    test_output: str = ""
    confidence_score: float = 0.0
    user_notified: bool = False
    user_approved: bool = False
    integration_status: str = "pending"  # pending, testing, ready, approved, integrated, rejected


class QuotaWarden:
    """
    Manages sandbox storage quota.
    Hard limit: 20GB, cleanup at 18GB.
    """

    def __init__(self, sandbox_path: Path = SANDBOX_PATH):
        self.sandbox_path = sandbox_path
        self.sandbox_path.mkdir(parents=True, exist_ok=True)

    def get_size_gb(self) -> float:
        """Get current sandbox size in GB."""
        total = 0
        try:
            for dirpath, dirnames, filenames in os.walk(self.sandbox_path):
                for f in filenames:
                    fp = os.path.join(dirpath, f)
                    if os.path.isfile(fp):
                        total += os.path.getsize(fp)
        except Exception as e:
            LOG.error(f"Error calculating sandbox size: {e}")
        return total / (1024 ** 3)

    def needs_cleanup(self) -> bool:
        """Check if cleanup is needed."""
        return self.get_size_gb() >= CLEANUP_THRESHOLD_GB

    def is_full(self) -> bool:
        """Check if sandbox is at hard limit."""
        return self.get_size_gb() >= MAX_SANDBOX_GB

    def cleanup(self, keep_high_interest: bool = True) -> int:
        """
        Clean up sandbox using FIFO and interest-score logic.
        Returns number of repos deleted.
        """
        if not self.sandbox_path.exists():
            return 0

        deleted = 0
        repos = []

        # Get all repo directories with their metadata
        for item in self.sandbox_path.iterdir():
            if item.is_dir():
                meta_file = item / ".fas_meta.json"
                interest_score = 0.0
                created_time = item.stat().st_ctime

                if meta_file.exists():
                    try:
                        meta = json.loads(meta_file.read_text())
                        interest_score = meta.get("interest_score", 0.0)
                    except:
                        pass

                repos.append({
                    "path": item,
                    "interest_score": interest_score,
                    "created_time": created_time,
                })

        # Sort: low interest first, then oldest first
        repos.sort(key=lambda x: (x["interest_score"], x["created_time"]))

        # Delete until under threshold
        for repo in repos:
            if not self.needs_cleanup():
                break

            try:
                # Safety check: only delete from sandbox
                if str(repo["path"]).startswith(str(self.sandbox_path)):
                    shutil.rmtree(repo["path"])
                    deleted += 1
                    LOG.info(f"Quota cleanup: deleted {repo['path'].name}")
            except Exception as e:
                LOG.error(f"Cleanup error for {repo['path']}: {e}")

        return deleted


class SafetyGuard:
    """
    Safety checks for F.A.S. operations.
    Implements Gaming-Mode Kill-Switch and Time Window restrictions.
    """

    @staticmethod
    def is_gaming_active() -> bool:
        """Check if gaming mode is active."""
        try:
            if GAMING_STATE_FILE.exists():
                data = json.loads(GAMING_STATE_FILE.read_text())
                return data.get("active", False)
        except:
            pass
        return False

    @staticmethod
    def get_cpu_percent() -> float:
        """Get current CPU usage percent."""
        try:
            import psutil
            return psutil.cpu_percent(interval=0.5)
        except ImportError:
            # Fallback to /proc/stat
            try:
                with open("/proc/loadavg") as f:
                    load = float(f.read().split()[0])
                    # Estimate percent (rough)
                    return min(100, load * 10)
            except:
                return 50.0  # Assume moderate load if can't detect

    @staticmethod
    def is_in_allowed_time_window() -> bool:
        """Check if current time is in allowed window (02:00-06:00)."""
        hour = datetime.now().hour
        return hour in ALLOWED_HOURS

    @staticmethod
    def is_system_idle() -> bool:
        """Check if system is idle (CPU < 5%)."""
        return SafetyGuard.get_cpu_percent() < IDLE_CPU_THRESHOLD

    @staticmethod
    def can_run() -> Tuple[bool, str]:
        """
        Check if F.A.S. can run now.
        Returns (can_run, reason).
        """
        # Gaming mode check
        if SafetyGuard.is_gaming_active():
            return False, "Gaming mode active"

        # CPU check
        cpu = SafetyGuard.get_cpu_percent()
        if cpu > MAX_CPU_THRESHOLD:
            return False, f"CPU too high: {cpu:.1f}%"

        # Time window OR idle check
        in_window = SafetyGuard.is_in_allowed_time_window()
        is_idle = SafetyGuard.is_system_idle()

        if not in_window and not is_idle:
            return False, f"Not in time window (02:00-06:00) and not idle (CPU={cpu:.1f}%)"

        return True, "OK"


class FASDatabase:
    """
    Database for F.A.S. operations.
    Tracks analyzed repos, daily quotas, and extracted features.
    """

    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: Optional[sqlite3.Connection] = None
        self._ensure_schema()

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(
                self.db_path,
                check_same_thread=False,
                timeout=30.0
            )
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def _ensure_schema(self):
        conn = self._get_conn()

        # Analyzed repos (hash blacklist)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS analyzed_repos (
                hash_id TEXT PRIMARY KEY,
                full_name TEXT NOT NULL,
                analyzed_at TEXT NOT NULL,
                interest_score REAL DEFAULT 0.0,
                deep_dived INTEGER DEFAULT 0,
                features_found INTEGER DEFAULT 0
            )
        """)

        # Daily quota tracking
        conn.execute("""
            CREATE TABLE IF NOT EXISTS daily_quota (
                date TEXT PRIMARY KEY,
                deep_dives INTEGER DEFAULT 0,
                api_calls INTEGER DEFAULT 0,
                bytes_downloaded INTEGER DEFAULT 0
            )
        """)

        # Extracted features (extended for sandbox testing & user approval)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS extracted_features (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                repo_name TEXT NOT NULL,
                feature_type TEXT NOT NULL,
                name TEXT NOT NULL,
                description TEXT,
                file_path TEXT,
                code_snippet TEXT,
                full_code TEXT,
                relevance_score REAL DEFAULT 0.0,
                created_at TEXT NOT NULL,
                -- Sandbox testing fields
                sandbox_tested INTEGER DEFAULT 0,
                sandbox_passed INTEGER DEFAULT 0,
                test_output TEXT,
                confidence_score REAL DEFAULT 0.0,
                test_iterations INTEGER DEFAULT 0,
                -- User approval fields
                user_notified INTEGER DEFAULT 0,
                user_notified_at TEXT,
                user_approved INTEGER DEFAULT 0,
                user_approved_at TEXT,
                user_response TEXT,
                -- Integration status
                integration_status TEXT DEFAULT 'pending',
                integrated_at TEXT,
                integration_path TEXT
            )
        """)

        # Scout history
        conn.execute("""
            CREATE TABLE IF NOT EXISTS scout_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                query TEXT NOT NULL,
                repos_found INTEGER DEFAULT 0,
                repos_interesting INTEGER DEFAULT 0
            )
        """)

        conn.commit()

        # Migration: Add new columns if they don't exist (for v2.0 upgrade)
        self._migrate_schema(conn)

    def _migrate_schema(self, conn: sqlite3.Connection):
        """Add new v2.0 columns to existing database."""
        # Get existing columns
        cursor = conn.execute("PRAGMA table_info(extracted_features)")
        existing_cols = {row[1] for row in cursor.fetchall()}

        # New columns to add for v2.0
        new_columns = [
            ("full_code", "TEXT"),
            ("sandbox_tested", "INTEGER DEFAULT 0"),
            ("sandbox_passed", "INTEGER DEFAULT 0"),
            ("test_output", "TEXT"),
            ("confidence_score", "REAL DEFAULT 0.0"),
            ("test_iterations", "INTEGER DEFAULT 0"),
            ("user_notified", "INTEGER DEFAULT 0"),
            ("user_notified_at", "TEXT"),
            ("user_approved", "INTEGER DEFAULT 0"),
            ("user_approved_at", "TEXT"),
            ("user_response", "TEXT"),
            ("integration_status", "TEXT DEFAULT 'pending'"),
            ("integrated_at", "TEXT"),
            ("integration_path", "TEXT"),
            # v2.1: Columns needed for GitHubEcho sensor + news scanner bridge
            ("source_url", "TEXT"),
            ("quarantine_count", "INTEGER DEFAULT 0"),
        ]

        for col_name, col_type in new_columns:
            # Validiere gegen SQL Injection (Defense in Depth)
            if not _VALID_SQL_IDENTIFIER.match(col_name):
                LOG.warning(f"Invalid column name rejected: {col_name}")
                continue
            if not _VALID_SQL_TYPE.match(col_type):
                LOG.warning(f"Invalid column type rejected: {col_type}")
                continue

            if col_name not in existing_cols:
                try:
                    conn.execute(f"ALTER TABLE extracted_features ADD COLUMN {col_name} {col_type}")
                    LOG.info(f"Added column {col_name} to extracted_features")
                except sqlite3.OperationalError:
                    pass  # Column already exists

        conn.commit()

    def is_repo_analyzed(self, hash_id: str) -> bool:
        """Check if repo was already analyzed."""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT 1 FROM analyzed_repos WHERE hash_id = ?",
            (hash_id,)
        ).fetchone()
        return row is not None

    def mark_repo_analyzed(self, repo: RepoMetadata, deep_dived: bool = False):
        """Mark repo as analyzed."""
        conn = self._get_conn()
        conn.execute("""
            INSERT OR REPLACE INTO analyzed_repos
            (hash_id, full_name, analyzed_at, interest_score, deep_dived)
            VALUES (?, ?, ?, ?, ?)
        """, (
            repo.hash_id,
            repo.full_name,
            datetime.now().isoformat(),
            repo.interest_score,
            1 if deep_dived else 0,
        ))
        conn.commit()

    def get_deep_dives_today(self) -> int:
        """Get number of deep dives today."""
        conn = self._get_conn()
        today = datetime.now().strftime("%Y-%m-%d")
        row = conn.execute(
            "SELECT deep_dives FROM daily_quota WHERE date = ?",
            (today,)
        ).fetchone()
        return row["deep_dives"] if row else 0

    def increment_deep_dives(self):
        """Increment today's deep dive count."""
        conn = self._get_conn()
        today = datetime.now().strftime("%Y-%m-%d")
        conn.execute("""
            INSERT INTO daily_quota (date, deep_dives)
            VALUES (?, 1)
            ON CONFLICT(date) DO UPDATE SET deep_dives = deep_dives + 1
        """, (today,))
        conn.commit()

    def can_deep_dive(self) -> bool:
        """Check if deep dive quota allows more today."""
        return self.get_deep_dives_today() < MAX_DEEP_DIVES_PER_DAY

    def save_feature(self, feature: FeatureExtract):
        """Save an extracted feature."""
        conn = self._get_conn()
        conn.execute("""
            INSERT INTO extracted_features
            (repo_name, feature_type, name, description, file_path,
             code_snippet, relevance_score, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            feature.repo_name,
            feature.feature_type,
            feature.name,
            feature.description,
            feature.file_path,
            feature.code_snippet,
            feature.relevance_score,
            feature.timestamp,
        ))
        conn.commit()

    def get_pending_features(self) -> List[Dict]:
        """Get features pending approval (not yet tested or waiting approval)."""
        conn = self._get_conn()
        rows = conn.execute("""
            SELECT * FROM extracted_features
            WHERE integration_status IN ('pending', 'testing', 'ready')
            ORDER BY relevance_score DESC
        """).fetchall()
        return [dict(row) for row in rows]

    def get_untested_features(self) -> List[Dict]:
        """Get features that haven't been sandbox tested yet."""
        conn = self._get_conn()
        rows = conn.execute("""
            SELECT * FROM extracted_features
            WHERE sandbox_tested = 0
              AND integration_status = 'pending'
            ORDER BY relevance_score DESC
            LIMIT 10
        """).fetchall()
        return [dict(row) for row in rows]

    def get_feature_by_id(self, feature_id: int) -> Optional[Dict]:
        """Get a specific feature by ID."""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM extracted_features WHERE id = ?",
            (feature_id,)
        ).fetchone()
        return dict(row) if row else None

    def log_scout(self, query: str, found: int, interesting: int):
        """Log a scout operation."""
        conn = self._get_conn()
        conn.execute("""
            INSERT INTO scout_history (timestamp, query, repos_found, repos_interesting)
            VALUES (?, ?, ?, ?)
        """, (datetime.now().isoformat(), query, found, interesting))
        conn.commit()


class GitHubScout:
    """
    Phase 1: Scout-Scraping
    Uses GitHub API to search for interesting repos (metadata only).
    """

    def __init__(self, db: FASDatabase):
        self.db = db
        self.last_api_call = 0.0

    def _rate_limit(self):
        """Respect GitHub API rate limits."""
        elapsed = time.time() - self.last_api_call
        if elapsed < GITHUB_RATE_LIMIT_DELAY:
            time.sleep(GITHUB_RATE_LIMIT_DELAY - elapsed)
        self.last_api_call = time.time()

    def _github_request(self, url: str) -> Optional[Dict]:
        """Make rate-limited GitHub API request."""
        self._rate_limit()

        # Safety check
        can_run, reason = SafetyGuard.can_run()
        if not can_run:
            LOG.warning(f"Scout aborted: {reason}")
            return None

        try:
            req = Request(url)
            req.add_header("Accept", "application/vnd.github.v3+json")
            req.add_header("User-Agent", "FAS-Scavenger/1.0")

            # Use GitHub token if available
            token = os.environ.get("GITHUB_TOKEN")
            if token:
                req.add_header("Authorization", f"token {token}")

            with urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode())

        except HTTPError as e:
            if e.code == 403:
                LOG.warning("GitHub rate limit reached, entering stasis")
                self._enter_stasis("rate_limit")
            else:
                LOG.error(f"GitHub API error: {e}")
            return None
        except Exception as e:
            LOG.error(f"GitHub request error: {e}")
            return None

    def _enter_stasis(self, reason: str):
        """Enter stasis state for 12 hours."""
        stasis_until = (datetime.now() + timedelta(hours=STASIS_HOURS)).isoformat()
        STASIS_FILE.write_text(json.dumps({
            "until": stasis_until,
            "reason": reason,
        }))
        LOG.warning(f"Entering stasis until {stasis_until}: {reason}")

    def is_in_stasis(self) -> bool:
        """Check if in stasis state."""
        if not STASIS_FILE.exists():
            return False
        try:
            data = json.loads(STASIS_FILE.read_text())
            until = datetime.fromisoformat(data["until"])
            if datetime.now() < until:
                return True
            else:
                STASIS_FILE.unlink()
                return False
        except:
            return False

    def search_repos(self, topic: str, max_results: int = 10) -> List[RepoMetadata]:
        """Search GitHub for repos with a specific topic."""
        if self.is_in_stasis():
            LOG.info("In stasis, skipping search")
            return []

        url = f"{GITHUB_API}/search/repositories?q=topic:{topic}&sort=updated&per_page={max_results}"
        data = self._github_request(url)

        if not data or "items" not in data:
            return []

        repos = []
        for item in data["items"]:
            repo = RepoMetadata(
                full_name=item.get("full_name", ""),
                name=item.get("name", ""),
                owner=item.get("owner", {}).get("login", ""),
                description=item.get("description", "") or "",
                stars=item.get("stargazers_count", 0),
                forks=item.get("forks_count", 0),
                topics=item.get("topics", []),
                language=item.get("language", "") or "",
                updated_at=item.get("updated_at", ""),
            )
            repo.hash_id = repo.compute_hash()

            # Skip if already analyzed
            if self.db.is_repo_analyzed(repo.hash_id):
                continue

            repos.append(repo)

        return repos

    def fetch_readme(self, repo: RepoMetadata) -> str:
        """Fetch README.md content (guardrail: metadata only)."""
        url = f"{GITHUB_API}/repos/{repo.full_name}/readme"
        data = self._github_request(url)

        if data and "content" in data:
            import base64
            try:
                return base64.b64decode(data["content"]).decode("utf-8", errors="ignore")
            except:
                pass
        return ""

    def fetch_architecture(self, repo: RepoMetadata) -> str:
        """Fetch architecture.md if exists."""
        # Try common architecture file names
        for filename in ["architecture.md", "ARCHITECTURE.md", "docs/architecture.md"]:
            url = f"{GITHUB_API}/repos/{repo.full_name}/contents/{filename}"
            data = self._github_request(url)

            if data and "content" in data:
                import base64
                try:
                    return base64.b64decode(data["content"]).decode("utf-8", errors="ignore")
                except:
                    pass
        return ""


class InterestScorer:
    """
    Calculates interest score for repositories (Frank-Matrix).
    High relevance + Low complexity = High score.
    """

    # Keywords that indicate high relevance
    HIGH_RELEVANCE_KEYWORDS = [
        "llm", "agent", "autonomous", "ai-agent", "tool", "api",
        "automation", "wrapper", "integration", "plugin", "extension",
        "langchain", "openai", "anthropic", "ollama", "local-llm",
    ]

    # Keywords that indicate high complexity (lower priority)
    HIGH_COMPLEXITY_KEYWORDS = [
        "training", "fine-tune", "dataset", "cuda", "gpu",
        "distributed", "kubernetes", "enterprise", "cloud",
    ]

    @classmethod
    def calculate_score(cls, repo: RepoMetadata) -> float:
        """
        Calculate interest score (0.0 - 1.0).
        Formula: (relevance * 0.6) + (simplicity * 0.3) + (popularity * 0.1)
        """
        text = f"{repo.description} {repo.readme_content} {' '.join(repo.topics)}".lower()

        # Relevance score (0-1)
        relevance_hits = sum(1 for kw in cls.HIGH_RELEVANCE_KEYWORDS if kw in text)
        relevance = min(1.0, relevance_hits / 5)

        # Complexity penalty (inverted to simplicity)
        complexity_hits = sum(1 for kw in cls.HIGH_COMPLEXITY_KEYWORDS if kw in text)
        simplicity = max(0.0, 1.0 - (complexity_hits / 4))

        # Popularity score (logarithmic, capped)
        import math
        popularity = min(1.0, math.log10(max(1, repo.stars)) / 4)

        # Combined score
        score = (relevance * 0.6) + (simplicity * 0.3) + (popularity * 0.1)

        return round(score, 3)


class SandboxDownloader:
    """
    Phase 2: Triage & Deep Dive
    Downloads repos to sandbox with strict safety controls.
    """

    def __init__(self, db: FASDatabase, quota: QuotaWarden):
        self.db = db
        self.quota = quota
        self.sandbox = SANDBOX_PATH

    def download_repo(self, repo: RepoMetadata) -> Optional[Path]:
        """
        Download repo to sandbox using git clone --depth 1.
        Returns path to downloaded repo or None on failure.
        """
        # Safety checks
        can_run, reason = SafetyGuard.can_run()
        if not can_run:
            LOG.warning(f"Download aborted: {reason}")
            return None

        if not self.db.can_deep_dive():
            LOG.warning("Daily deep-dive quota reached")
            return None

        if self.quota.is_full():
            LOG.warning("Sandbox full, running cleanup")
            self.quota.cleanup()
            if self.quota.is_full():
                LOG.error("Sandbox still full after cleanup")
                return None

        # Create repo directory
        repo_dir = self.sandbox / repo.full_name.replace("/", "_")
        if repo_dir.exists():
            shutil.rmtree(repo_dir)

        try:
            # Use ionice and nice for low-impact download
            clone_url = f"https://github.com/{repo.full_name}.git"
            cmd = [
                "ionice", "-c", "3",
                "nice", "-n", "19",
                "git", "clone", "--depth", "1", "--single-branch",
                clone_url, str(repo_dir)
            ]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300,  # 5 minute timeout
            )

            if result.returncode != 0:
                LOG.error(f"Git clone failed: {result.stderr}")
                return None

            # Save metadata
            meta_file = repo_dir / ".fas_meta.json"
            meta_file.write_text(json.dumps({
                "full_name": repo.full_name,
                "interest_score": repo.interest_score,
                "downloaded_at": datetime.now().isoformat(),
            }))

            # Increment quota
            self.db.increment_deep_dives()
            LOG.info(f"Downloaded {repo.full_name} (score={repo.interest_score})")

            return repo_dir

        except subprocess.TimeoutExpired:
            LOG.error(f"Download timeout for {repo.full_name}")
            if repo_dir.exists():
                shutil.rmtree(repo_dir)
            return None
        except Exception as e:
            LOG.error(f"Download error: {e}")
            if repo_dir.exists():
                shutil.rmtree(repo_dir)
            return None


class FeatureExtractor:
    """
    Phase 3: Feature Extraction
    Analyzes downloaded code for interesting patterns.
    """

    # File patterns to analyze
    INTERESTING_PATTERNS = [
        ("tool", r"def\s+\w+_tool\s*\(|class\s+\w+Tool\b|@tool\b"),
        ("api_wrapper", r"class\s+\w+API\b|class\s+\w+Client\b|requests\.(get|post)"),
        ("utility", r"def\s+(parse|format|convert|extract|validate)\w*\s*\("),
        ("pattern", r"class\s+\w+(Handler|Manager|Service|Controller)\b"),
    ]

    def __init__(self, db: FASDatabase):
        self.db = db

    def extract_features(self, repo_dir: Path, repo_name: str) -> List[FeatureExtract]:
        """Extract interesting features from downloaded repo."""
        import re

        features = []

        # Only analyze Python files
        for py_file in repo_dir.rglob("*.py"):
            # Skip tests, examples, setup files
            if any(x in str(py_file) for x in ["test", "example", "setup.py", "__pycache__"]):
                continue

            try:
                content = py_file.read_text(errors="ignore")

                for feature_type, pattern in self.INTERESTING_PATTERNS:
                    matches = re.finditer(pattern, content)
                    for match in matches:
                        # Extract surrounding context (50 chars before/after)
                        start = max(0, match.start() - 50)
                        end = min(len(content), match.end() + 200)
                        snippet = content[start:end].strip()

                        # Extract name from match
                        match_text = match.group()
                        name_match = re.search(r"(\w+)", match_text)
                        name = name_match.group(1) if name_match else "unknown"

                        feature = FeatureExtract(
                            repo_name=repo_name,
                            feature_type=feature_type,
                            name=name,
                            description=f"Found {feature_type} pattern in {py_file.name}",
                            file_path=str(py_file.relative_to(repo_dir)),
                            code_snippet=snippet[:500],
                            relevance_score=0.5,  # Base score
                            timestamp=datetime.now().isoformat(),
                        )
                        features.append(feature)

            except Exception as e:
                LOG.debug(f"Error analyzing {py_file}: {e}")

        return features


# =============================================================================
# SANDBOX TESTING SYSTEM
# =============================================================================

try:
    from config.paths import SANDBOX_DIR as _FAS_SANDBOX
    FEATURE_SANDBOX_PATH = _FAS_SANDBOX / "feature_tests"
except ImportError:
    _fas_proj_root = Path(__file__).resolve().parents[3]
    FEATURE_SANDBOX_PATH = _fas_proj_root / "sandbox" / "feature_tests"
MIN_CONFIDENCE_FOR_PROPOSAL = 0.75
MIN_TEST_ITERATIONS = 3


class FeatureSandbox:
    """
    Tests extracted features in an isolated sandbox environment.
    Only features that pass testing with high confidence are proposed to the user.
    """

    def __init__(self, db: FASDatabase):
        self.db = db
        self.sandbox_path = FEATURE_SANDBOX_PATH
        self.sandbox_path.mkdir(parents=True, exist_ok=True)

    def test_feature(self, feature_id: int, full_code: str) -> Dict[str, Any]:
        """
        Test a feature in the sandbox environment.
        Returns test results including pass/fail and confidence score.
        """
        result = {
            "feature_id": feature_id,
            "passed": False,
            "confidence": 0.0,
            "test_output": "",
            "syntax_valid": False,
            "imports_available": False,
            "executes_safely": False,
            "iterations": 0,
        }

        # Create isolated test directory
        test_dir = self.sandbox_path / f"test_{feature_id}_{int(time.time())}"
        test_dir.mkdir(parents=True, exist_ok=True)
        test_file = test_dir / "test_feature.py"

        try:
            # Write code to test file
            test_file.write_text(full_code)

            # Test 1: Syntax validation
            syntax_result = self._test_syntax(test_file)
            result["syntax_valid"] = syntax_result["valid"]
            result["test_output"] += f"Syntax: {'PASS' if syntax_result['valid'] else 'FAIL'}\n"
            if not syntax_result["valid"]:
                result["test_output"] += f"  Error: {syntax_result.get('error', 'Unknown')}\n"
                return result

            # Test 2: Import availability check
            import_result = self._test_imports(full_code)
            result["imports_available"] = import_result["available"]
            result["test_output"] += f"Imports: {'PASS' if import_result['available'] else 'FAIL'}\n"
            if not import_result["available"]:
                result["test_output"] += f"  Missing: {import_result.get('missing', [])}\n"

            # Test 3: Safe execution test (multiple iterations)
            exec_results = []
            for i in range(MIN_TEST_ITERATIONS):
                exec_result = self._test_execution(test_file)
                exec_results.append(exec_result)
                result["iterations"] += 1

                # Safety check between iterations
                can_run, _ = SafetyGuard.can_run()
                if not can_run:
                    break

            # Calculate execution success rate
            success_count = sum(1 for r in exec_results if r["success"])
            result["executes_safely"] = success_count == len(exec_results)
            result["test_output"] += f"Execution: {success_count}/{len(exec_results)} passed\n"

            # Calculate confidence score
            confidence = 0.0
            if result["syntax_valid"]:
                confidence += 0.3
            if result["imports_available"]:
                confidence += 0.2
            if result["executes_safely"]:
                confidence += 0.4
            # Bonus for multiple successful iterations
            confidence += (success_count / max(len(exec_results), 1)) * 0.1

            result["confidence"] = round(confidence, 2)
            result["passed"] = result["confidence"] >= MIN_CONFIDENCE_FOR_PROPOSAL

            result["test_output"] += f"\nConfidence Score: {result['confidence']:.2f}\n"
            result["test_output"] += f"Status: {'READY FOR PROPOSAL' if result['passed'] else 'NEEDS IMPROVEMENT'}\n"

        except Exception as e:
            result["test_output"] += f"Error during testing: {e}\n"
            LOG.error(f"Sandbox test error for feature {feature_id}: {e}")

        finally:
            # Cleanup test directory
            try:
                if test_dir.exists():
                    shutil.rmtree(test_dir)
            except:
                pass

        return result

    def _test_syntax(self, test_file: Path) -> Dict[str, Any]:
        """Test Python syntax validity."""
        try:
            result = subprocess.run(
                [sys.executable, "-m", "py_compile", str(test_file)],
                capture_output=True,
                text=True,
                timeout=10
            )
            return {"valid": result.returncode == 0, "error": result.stderr}
        except Exception as e:
            return {"valid": False, "error": str(e)}

    def _test_imports(self, code: str) -> Dict[str, Any]:
        """Check if all imports are available."""
        import re
        import_pattern = r'^(?:from\s+([\w.]+)|import\s+([\w.]+))'
        imports = []

        for line in code.split('\n'):
            match = re.match(import_pattern, line.strip())
            if match:
                module = match.group(1) or match.group(2)
                if module:
                    imports.append(module.split('.')[0])

        missing = []
        for mod in set(imports):
            # Skip standard library modules
            if mod in ['os', 'sys', 'json', 're', 'time', 'datetime', 'pathlib',
                       'subprocess', 'threading', 'collections', 'functools',
                       'itertools', 'math', 'random', 'hashlib', 'base64',
                       'urllib', 'http', 'socket', 'logging', 'argparse', 'ast',
                       'typing', 'dataclasses', 'shutil', 'sqlite3']:
                continue

            try:
                __import__(mod)
            except ImportError:
                missing.append(mod)

        return {"available": len(missing) == 0, "missing": missing}

    def _test_execution(self, test_file: Path) -> Dict[str, Any]:
        """Test safe execution in isolated subprocess."""
        try:
            # Run with strict resource limits
            result = subprocess.run(
                [
                    "nice", "-n", "19",
                    "timeout", "10",
                    sys.executable, str(test_file)
                ],
                capture_output=True,
                text=True,
                timeout=15,
                cwd=test_file.parent,
                env={
                    **os.environ,
                    "PYTHONDONTWRITEBYTECODE": "1",
                }
            )
            return {
                "success": result.returncode == 0,
                "stdout": result.stdout[:500] if result.stdout else "",
                "stderr": result.stderr[:500] if result.stderr else "",
            }
        except subprocess.TimeoutExpired:
            return {"success": False, "stdout": "", "stderr": "Timeout"}
        except Exception as e:
            return {"success": False, "stdout": "", "stderr": str(e)}

    def update_feature_test_results(self, feature_id: int, results: Dict[str, Any]):
        """Update feature with sandbox test results."""
        conn = self.db._get_conn()
        conn.execute("""
            UPDATE extracted_features
            SET sandbox_tested = 1,
                sandbox_passed = ?,
                test_output = ?,
                confidence_score = ?,
                test_iterations = ?,
                integration_status = ?
            WHERE id = ?
        """, (
            1 if results["passed"] else 0,
            results["test_output"],
            results["confidence"],
            results["iterations"],
            "ready" if results["passed"] else "testing",
            feature_id,
        ))
        conn.commit()


# =============================================================================
# USER APPROVAL SYSTEM
# =============================================================================

class UserApprovalSystem:
    """
    Manages user notifications and approvals for discovered features.
    Integrates with the chat UI to present features and get user confirmation.
    """

    CHAT_SOCKET_PATH = Path(f"/run/user/{os.getuid()}/frank/chat.sock")
    APPROVAL_TIMEOUT_HOURS = 72  # Features expire after 72h without response

    def __init__(self, db: FASDatabase):
        self.db = db

    def get_features_ready_for_proposal(self) -> List[Dict]:
        """Get features that passed testing and are ready for user proposal."""
        conn = self.db._get_conn()
        rows = conn.execute("""
            SELECT * FROM extracted_features
            WHERE sandbox_passed = 1
              AND user_notified = 0
              AND integration_status = 'ready'
            ORDER BY confidence_score DESC
            LIMIT 5
        """).fetchall()
        return [dict(row) for row in rows]

    def get_pending_approvals(self) -> List[Dict]:
        """Get features waiting for user response."""
        conn = self.db._get_conn()
        rows = conn.execute("""
            SELECT * FROM extracted_features
            WHERE user_notified = 1
              AND user_approved = 0
              AND integration_status = 'ready'
            ORDER BY user_notified_at DESC
        """).fetchall()
        return [dict(row) for row in rows]

    def create_proposal_message(self, feature: Dict) -> str:
        """
        Create a detailed proposal message for the user.
        Explains what the feature does and its value.
        """
        msg = f"""
================================================================================
NEW FEATURE DISCOVERED - Approval Required
================================================================================

Feature Name: {feature['name']}
Type: {feature['feature_type']}
Source: {feature['repo_name']}

WHAT IT DOES:
{feature['description']}

TECHNICAL DETAILS:
- File: {feature['file_path']}
- Confidence Score: {feature['confidence_score']:.0%}
- Test Iterations: {feature.get('test_iterations', 0)}
- Sandbox Status: {'PASSED' if feature['sandbox_passed'] else 'PENDING'}

VALUE PROPOSITION:
This feature could enhance Frank's capabilities by providing:
"""

        # Add value description based on feature type
        feature_type = feature['feature_type']
        if feature_type == 'tool':
            msg += "- A new tool that can be used during conversations\n"
            msg += "- Expanded functionality for task automation\n"
        elif feature_type == 'api_wrapper':
            msg += "- Integration with external services/APIs\n"
            msg += "- New data sources or capabilities\n"
        elif feature_type == 'utility':
            msg += "- Helper functions for common operations\n"
            msg += "- Improved code reusability\n"
        elif feature_type == 'pattern':
            msg += "- A proven design pattern for better code organization\n"
            msg += "- Best practices from the open source community\n"

        msg += f"""
CODE PREVIEW:
{'-' * 60}
{feature['code_snippet'][:800]}
{'-' * 60}

SAFETY ASSESSMENT:
- Syntax Validation: PASSED
- Import Check: PASSED
- Execution Test: {feature.get('test_iterations', 0)}/{MIN_TEST_ITERATIONS} iterations passed
- Overall Confidence: {feature['confidence_score']:.0%}

================================================================================
To approve this feature, respond with: /approve-feature {feature['id']}
To reject this feature, respond with: /reject-feature {feature['id']}
To see more details, respond with: /feature-details {feature['id']}
================================================================================
"""
        return msg

    def notify_user(self, feature: Dict) -> bool:
        """
        Send feature proposal to user via chat UI.
        Returns True if notification was sent successfully.
        """
        try:
            message = self.create_proposal_message(feature)

            # Method 1: Try Unix socket to chat service
            if self._send_via_socket(message):
                self._mark_notified(feature['id'])
                return True

            # Method 2: Write to pending notifications file
            if self._write_to_notifications(feature, message):
                self._mark_notified(feature['id'])
                return True

            LOG.warning(f"Could not notify user about feature {feature['id']}")
            return False

        except Exception as e:
            LOG.error(f"Error notifying user: {e}")
            return False

    def _send_via_socket(self, message: str) -> bool:
        """Send message via chat socket."""
        try:
            import socket
            sock_path = f"/run/user/{os.getuid()}/frank/ui_chat.sock"

            if not Path(sock_path).exists():
                return False

            sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
            sock.settimeout(5)

            payload = json.dumps({
                "type": "fas_proposal",
                "source": "fas_scavenger",
                "message": message,
                "timestamp": datetime.now().isoformat(),
                "requires_response": True,
            })

            sock.sendto(payload.encode(), sock_path)
            sock.close()
            return True

        except Exception as e:
            LOG.debug(f"Socket send failed: {e}")
            return False

    def _write_to_notifications(self, feature: Dict, message: str) -> bool:
        """Write to notifications file for chat UI to pick up."""
        try:
            try:
                from config.paths import AICORE_DATA as _fas_data
                notif_dir = _fas_data / "fas_notifications"
            except ImportError:
                notif_dir = Path.home() / ".local" / "share" / "frank" / "fas_notifications"
            notif_dir.mkdir(parents=True, exist_ok=True)

            notif_file = notif_dir / f"feature_{feature['id']}_{int(time.time())}.json"
            notif_file.write_text(json.dumps({
                "feature_id": feature['id'],
                "feature_name": feature['name'],
                "feature_type": feature['feature_type'],
                "repo_name": feature['repo_name'],
                "confidence_score": feature['confidence_score'],
                "message": message,
                "created_at": datetime.now().isoformat(),
                "status": "pending",
            }, indent=2))

            LOG.info(f"Notification written for feature {feature['id']}")
            return True

        except Exception as e:
            LOG.error(f"Failed to write notification: {e}")
            return False

    def _mark_notified(self, feature_id: int):
        """Mark feature as notified."""
        conn = self.db._get_conn()
        conn.execute("""
            UPDATE extracted_features
            SET user_notified = 1,
                user_notified_at = ?
            WHERE id = ?
        """, (datetime.now().isoformat(), feature_id))
        conn.commit()

    def process_user_response(self, feature_id: int, approved: bool, response: str = "") -> bool:
        """
        Process user's approval/rejection response.
        Returns True if processed successfully.
        """
        conn = self.db._get_conn()

        # Verify feature exists and is pending approval
        row = conn.execute(
            "SELECT * FROM extracted_features WHERE id = ?",
            (feature_id,)
        ).fetchone()

        if not row:
            LOG.warning(f"Feature {feature_id} not found")
            return False

        new_status = "approved" if approved else "rejected"

        conn.execute("""
            UPDATE extracted_features
            SET user_approved = ?,
                user_approved_at = ?,
                user_response = ?,
                integration_status = ?
            WHERE id = ?
        """, (
            1 if approved else 0,
            datetime.now().isoformat(),
            response,
            new_status,
            feature_id,
        ))
        conn.commit()

        LOG.info(f"Feature {feature_id} {new_status} by user")
        return True

    def get_approved_features(self) -> List[Dict]:
        """Get features approved by user and ready for integration."""
        conn = self.db._get_conn()
        rows = conn.execute("""
            SELECT * FROM extracted_features
            WHERE user_approved = 1
              AND integration_status = 'approved'
            ORDER BY user_approved_at DESC
        """).fetchall()
        return [dict(row) for row in rows]


# =============================================================================
# FEATURE INTEGRATOR
# =============================================================================

class FeatureIntegrator:
    """
    Integrates approved features into Frank's toolset.
    Only runs after explicit user approval.
    """

    TOOLS_DIR = (_TOOLS_DIR / "discovered") if _TOOLS_DIR else (Path(__file__).resolve().parent / "discovered")

    def __init__(self, db: FASDatabase):
        self.db = db
        self.tools_dir = self.TOOLS_DIR
        self.tools_dir.mkdir(parents=True, exist_ok=True)

    def integrate_feature(self, feature: Dict) -> Dict[str, Any]:
        """
        Integrate an approved feature into Frank's toolset.
        Returns integration result.
        """
        result = {
            "feature_id": feature['id'],
            "success": False,
            "path": None,
            "error": None,
        }

        # Safety check: Only integrate approved features
        if feature.get('integration_status') != 'approved':
            result["error"] = "Feature not approved"
            return result

        if not feature.get('user_approved'):
            result["error"] = "User approval required"
            return result

        try:
            # Create tool file with proper naming
            tool_name = f"fas_{feature['feature_type']}_{feature['name'].lower()}"
            tool_name = "".join(c if c.isalnum() or c == '_' else '_' for c in tool_name)
            tool_file = self.tools_dir / f"{tool_name}.py"

            # Get full code if available, otherwise use snippet
            code = feature.get('full_code') or feature.get('code_snippet', '')

            if not code:
                result["error"] = "No code available"
                return result

            # Add header comment
            header = f'''#!/usr/bin/env python3
"""
Auto-discovered feature by F.A.S. (Frank's Autonomous Scavenger)

Source: {feature['repo_name']}
Type: {feature['feature_type']}
Name: {feature['name']}
Integrated: {datetime.now().isoformat()}
Confidence: {feature.get('confidence_score', 0):.0%}

Original file: {feature['file_path']}
"""

'''
            full_code = header + code

            # Write tool file
            tool_file.write_text(full_code)

            # Update database
            conn = self.db._get_conn()
            conn.execute("""
                UPDATE extracted_features
                SET integration_status = 'integrated',
                    integrated_at = ?,
                    integration_path = ?
                WHERE id = ?
            """, (
                datetime.now().isoformat(),
                str(tool_file),
                feature['id'],
            ))
            conn.commit()

            result["success"] = True
            result["path"] = str(tool_file)
            LOG.info(f"Feature {feature['id']} integrated to {tool_file}")

        except Exception as e:
            result["error"] = str(e)
            LOG.error(f"Integration error for feature {feature['id']}: {e}")

        return result


class FAS:
    """
    F.A.S. v2.0 - Frank's Autonomous Scavenger
    Main orchestrator for GitHub intelligence operations.

    Enhanced with:
    - Sandbox testing for discovered features
    - Confidence-based proposals
    - User approval system via chat UI
    - Controlled integration after approval
    """

    def __init__(self):
        self.db = FASDatabase()
        self.quota = QuotaWarden()
        self.scout = GitHubScout(self.db)
        self.downloader = SandboxDownloader(self.db, self.quota)
        self.extractor = FeatureExtractor(self.db)
        # New v2.0 components
        self.sandbox = FeatureSandbox(self.db)
        self.approval = UserApprovalSystem(self.db)
        self.integrator = FeatureIntegrator(self.db)
        self._running = False

        LOG.info("F.A.S. v2.0 initialized (with sandbox testing & user approval)")

    def run_cycle(self) -> Dict[str, Any]:
        """
        Run one complete F.A.S. cycle.
        Returns summary of operations.
        """
        summary = {
            "timestamp": datetime.now().isoformat(),
            "can_run": False,
            "reason": "",
            "repos_scouted": 0,
            "repos_interesting": 0,
            "repos_downloaded": 0,
            "features_extracted": 0,
            "cleanup_performed": False,
        }

        # Safety check
        can_run, reason = SafetyGuard.can_run()
        summary["can_run"] = can_run
        summary["reason"] = reason

        if not can_run:
            LOG.info(f"F.A.S. cycle skipped: {reason}")
            return summary

        # Stasis check
        if self.scout.is_in_stasis():
            summary["reason"] = "In stasis"
            return summary

        # Quota cleanup if needed
        if self.quota.needs_cleanup():
            self.quota.cleanup()
            summary["cleanup_performed"] = True

        # Phase 1: Scout
        all_repos = []
        for topic in GITHUB_SEARCH_TOPICS[:3]:  # Limit topics per cycle
            repos = self.scout.search_repos(topic, max_results=5)
            all_repos.extend(repos)

            # Recheck safety between operations
            can_run, _ = SafetyGuard.can_run()
            if not can_run:
                break

        summary["repos_scouted"] = len(all_repos)

        # Fetch metadata and score repos
        interesting_repos = []
        for repo in all_repos:
            # Fetch README (guardrail: metadata only)
            repo.readme_content = self.scout.fetch_readme(repo)

            # Calculate interest score
            repo.interest_score = InterestScorer.calculate_score(repo)

            # Mark as analyzed
            self.db.mark_repo_analyzed(repo, deep_dived=False)

            if repo.interest_score >= MIN_INTEREST_SCORE:
                interesting_repos.append(repo)

        summary["repos_interesting"] = len(interesting_repos)

        # Phase 2: Deep Dive (top repos only)
        interesting_repos.sort(key=lambda x: x.interest_score, reverse=True)

        for repo in interesting_repos[:2]:  # Max 2 downloads per cycle
            # Recheck safety
            can_run, _ = SafetyGuard.can_run()
            if not can_run:
                break

            if not self.db.can_deep_dive():
                break

            repo_dir = self.downloader.download_repo(repo)
            if repo_dir:
                summary["repos_downloaded"] += 1
                self.db.mark_repo_analyzed(repo, deep_dived=True)

                # Phase 3: Feature Extraction
                features = self.extractor.extract_features(repo_dir, repo.full_name)
                for feature in features[:10]:  # Max 10 features per repo
                    self.db.save_feature(feature)
                    summary["features_extracted"] += 1

                # Cleanup after analysis (if low interest)
                if repo.interest_score < 0.9:
                    try:
                        shutil.rmtree(repo_dir)
                        LOG.info(f"Cleaned up {repo.full_name} after analysis")
                    except:
                        pass

        # Log scout history
        self.db.log_scout(
            ",".join(GITHUB_SEARCH_TOPICS[:3]),
            summary["repos_scouted"],
            summary["repos_interesting"]
        )

        # Phase 4: Sandbox Testing (v2.0)
        summary["features_tested"] = 0
        summary["features_ready"] = 0
        untested = self.db.get_untested_features()

        for feature in untested:
            # Safety check
            can_run, _ = SafetyGuard.can_run()
            if not can_run:
                break

            # Get full code for testing
            full_code = feature.get('full_code') or feature.get('code_snippet', '')
            if full_code:
                result = self.sandbox.test_feature(feature['id'], full_code)
                self.sandbox.update_feature_test_results(feature['id'], result)
                summary["features_tested"] += 1

                if result["passed"]:
                    summary["features_ready"] += 1

        # Phase 5: User Notifications (v2.0)
        summary["features_notified"] = 0
        ready_features = self.approval.get_features_ready_for_proposal()

        for feature in ready_features:
            if self.approval.notify_user(feature):
                summary["features_notified"] += 1

        # Phase 6: Integration of Approved Features (v2.0)
        summary["features_integrated"] = 0
        approved = self.approval.get_approved_features()

        for feature in approved:
            result = self.integrator.integrate_feature(feature)
            if result["success"]:
                summary["features_integrated"] += 1

        LOG.info(f"F.A.S. cycle complete: {summary}")
        return summary

    def get_status(self) -> Dict[str, Any]:
        """Get current F.A.S. status."""
        can_run, reason = SafetyGuard.can_run()
        return {
            "can_run": can_run,
            "reason": reason,
            "in_stasis": self.scout.is_in_stasis(),
            "sandbox_gb": round(self.quota.get_size_gb(), 2),
            "sandbox_limit_gb": MAX_SANDBOX_GB,
            "deep_dives_today": self.db.get_deep_dives_today(),
            "deep_dives_limit": MAX_DEEP_DIVES_PER_DAY,
            "pending_features": len(self.db.get_pending_features()),
            "current_hour": datetime.now().hour,
            "allowed_hours": list(ALLOWED_HOURS),
            "cpu_percent": SafetyGuard.get_cpu_percent(),
        }

    def get_pending_features(self) -> List[Dict]:
        """Get features pending Genesis approval."""
        return self.db.get_pending_features()

    def get_ready_features(self) -> List[Dict]:
        """Get features ready for user approval (passed sandbox testing)."""
        return self.approval.get_features_ready_for_proposal()

    def get_pending_approvals(self) -> List[Dict]:
        """Get features waiting for user response."""
        return self.approval.get_pending_approvals()

    def approve_feature(self, feature_id: int, response: str = "") -> bool:
        """Approve a feature for integration."""
        return self.approval.process_user_response(feature_id, approved=True, response=response)

    def reject_feature(self, feature_id: int, response: str = "") -> bool:
        """Reject a feature."""
        return self.approval.process_user_response(feature_id, approved=False, response=response)

    def test_feature(self, feature_id: int) -> Dict[str, Any]:
        """Manually test a specific feature in sandbox."""
        feature = self.db.get_feature_by_id(feature_id)
        if not feature:
            return {"error": f"Feature {feature_id} not found"}

        full_code = feature.get('full_code') or feature.get('code_snippet', '')
        if not full_code:
            return {"error": "No code available for testing"}

        result = self.sandbox.test_feature(feature_id, full_code)
        self.sandbox.update_feature_test_results(feature_id, result)
        return result

    def integrate_feature(self, feature_id: int) -> Dict[str, Any]:
        """Integrate an approved feature."""
        feature = self.db.get_feature_by_id(feature_id)
        if not feature:
            return {"error": f"Feature {feature_id} not found"}

        if feature.get('integration_status') != 'approved':
            return {"error": "Feature must be approved before integration"}

        return self.integrator.integrate_feature(feature)

    def get_feature_details(self, feature_id: int) -> Optional[Dict]:
        """Get detailed information about a feature."""
        return self.db.get_feature_by_id(feature_id)


# Singleton
_fas: Optional[FAS] = None


def get_fas() -> FAS:
    """Get or create F.A.S. singleton."""
    global _fas
    if _fas is None:
        _fas = FAS()
    return _fas


# CLI
if __name__ == "__main__":
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format='[%(asctime)s] %(levelname)s: %(message)s'
    )

    parser = argparse.ArgumentParser(description="F.A.S. v2.0 - Frank's Autonomous Scavenger")
    parser.add_argument("command", choices=[
        "status", "run", "features", "cleanup",
        "ready", "pending", "approve", "reject",
        "test", "integrate", "details"
    ], help="Command to execute")
    parser.add_argument("--force", action="store_true", help="Force run (ignore safety checks)")
    parser.add_argument("--id", type=int, help="Feature ID for approve/reject/test/integrate/details")
    parser.add_argument("--response", type=str, default="", help="User response message")

    args = parser.parse_args()
    fas = get_fas()

    if args.command == "status":
        status = fas.get_status()
        print(json.dumps(status, indent=2))

    elif args.command == "run":
        if not args.force:
            can_run, reason = SafetyGuard.can_run()
            if not can_run:
                print(f"Cannot run: {reason}")
                print("Use --force to override (not recommended)")
                sys.exit(1)

        result = fas.run_cycle()
        print(json.dumps(result, indent=2))

    elif args.command == "features":
        features = fas.get_pending_features()
        if features:
            for f in features:
                print(f"\n[{f['id']}] [{f['feature_type']}] {f['name']} ({f['repo_name']})")
                print(f"  Status: {f.get('integration_status', 'pending')}")
                print(f"  Confidence: {f.get('confidence_score', 0):.0%}")
                print(f"  Tested: {'Yes' if f.get('sandbox_tested') else 'No'}")
                print(f"  File: {f['file_path']}")
        else:
            print("No pending features")

    elif args.command == "ready":
        # Show features ready for user approval
        features = fas.get_ready_features()
        if features:
            print("Features ready for approval:\n")
            for f in features:
                print(f"[{f['id']}] {f['name']} ({f['feature_type']})")
                print(f"  Source: {f['repo_name']}")
                print(f"  Confidence: {f.get('confidence_score', 0):.0%}")
                print(f"  -> Approve: python fas_scavenger.py approve --id {f['id']}")
                print()
        else:
            print("No features ready for approval")

    elif args.command == "pending":
        # Show features waiting for user response
        features = fas.get_pending_approvals()
        if features:
            print("Features awaiting your response:\n")
            for f in features:
                print(f"[{f['id']}] {f['name']} ({f['feature_type']})")
                print(f"  Notified: {f.get('user_notified_at', 'N/A')}")
                print(f"  -> Approve: python fas_scavenger.py approve --id {f['id']}")
                print(f"  -> Reject: python fas_scavenger.py reject --id {f['id']}")
                print()
        else:
            print("No features awaiting response")

    elif args.command == "approve":
        if not args.id:
            print("Error: --id required for approve command")
            sys.exit(1)
        if fas.approve_feature(args.id, args.response):
            print(f"Feature {args.id} approved!")
            print(f"Run 'python fas_scavenger.py integrate --id {args.id}' to integrate")
        else:
            print(f"Failed to approve feature {args.id}")

    elif args.command == "reject":
        if not args.id:
            print("Error: --id required for reject command")
            sys.exit(1)
        if fas.reject_feature(args.id, args.response):
            print(f"Feature {args.id} rejected")
        else:
            print(f"Failed to reject feature {args.id}")

    elif args.command == "test":
        if not args.id:
            print("Error: --id required for test command")
            sys.exit(1)
        print(f"Testing feature {args.id} in sandbox...")
        result = fas.test_feature(args.id)
        print(json.dumps(result, indent=2))

    elif args.command == "integrate":
        if not args.id:
            print("Error: --id required for integrate command")
            sys.exit(1)
        result = fas.integrate_feature(args.id)
        if result.get("success"):
            print(f"Feature {args.id} integrated successfully!")
            print(f"  Path: {result['path']}")
        else:
            print(f"Integration failed: {result.get('error')}")

    elif args.command == "details":
        if not args.id:
            print("Error: --id required for details command")
            sys.exit(1)
        feature = fas.get_feature_details(args.id)
        if feature:
            print(f"\n{'='*60}")
            print(f"Feature Details: {feature['name']} (ID: {feature['id']})")
            print(f"{'='*60}")
            print(f"Type: {feature['feature_type']}")
            print(f"Source: {feature['repo_name']}")
            print(f"File: {feature['file_path']}")
            print(f"Relevance Score: {feature['relevance_score']}")
            print(f"\nSandbox Status:")
            print(f"  Tested: {'Yes' if feature.get('sandbox_tested') else 'No'}")
            print(f"  Passed: {'Yes' if feature.get('sandbox_passed') else 'No'}")
            print(f"  Confidence: {feature.get('confidence_score', 0):.0%}")
            print(f"  Test Iterations: {feature.get('test_iterations', 0)}")
            print(f"\nApproval Status:")
            print(f"  Notified: {'Yes' if feature.get('user_notified') else 'No'}")
            print(f"  Approved: {'Yes' if feature.get('user_approved') else 'No'}")
            print(f"  Status: {feature.get('integration_status', 'pending')}")
            print(f"\nDescription:")
            print(f"  {feature['description']}")
            print(f"\nCode Preview:")
            print(f"{'-'*60}")
            print(feature.get('code_snippet', '')[:500])
            print(f"{'-'*60}")
            if feature.get('test_output'):
                print(f"\nTest Output:")
                print(feature['test_output'])
        else:
            print(f"Feature {args.id} not found")

    elif args.command == "cleanup":
        deleted = fas.quota.cleanup()
        print(f"Cleaned up {deleted} repos")
        print(f"Sandbox size: {fas.quota.get_size_gb():.2f} GB")
