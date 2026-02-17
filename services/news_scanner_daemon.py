#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
News Scanner Daemon - Frank's Autonomous Daily Knowledge Acquisition

Scannt 3x täglich konfigurierte Webseiten (AI, Tech, Open Source, Linux)
um Franks Wissen aktuell zu halten und potenzielle neue Features zu identifizieren.

Constraints:
- Gaming Mode wird VOR und ZWISCHEN jeder Aktion geprüft
- Keine Loops: 23h 55min Schlaf, ~5min aktive Arbeit pro Tag
- Ultra-konservative Ressourcen: Nice=15, CPU 10%, RAM 50MB max
- Alle Netzwerk-Requests gehen über den lokalen webd Service (127.0.0.1:8093)
"""

import argparse
import hashlib
import json
import logging
import os
import re
import signal
import sqlite3
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ---------- Paths ----------
try:
    from config.paths import AICORE_ROOT, get_db
    DB_PATH = get_db("news_scanner")
except ImportError:
    AICORE_ROOT = Path(__file__).resolve().parents[1]
    DB_PATH = Path.home() / ".local" / "share" / "frank" / "db" / "news_scanner.db"
SOURCES_FILE = AICORE_ROOT / "services" / "news_scanner_sources.json"
try:
    from config.paths import get_temp as _ns_get_temp, get_runtime as _ns_get_runtime
    GAMING_STATE_FILE = _ns_get_temp("gaming_mode_state.json")
    STATE_FILE = _ns_get_temp("news_scanner_state.json")
    PID_FILE = _ns_get_runtime("news_scanner.pid")
    LOG_FILE = _ns_get_temp("news_scanner.log")
except ImportError:
    GAMING_STATE_FILE = Path("/tmp/frank/gaming_mode_state.json")
    STATE_FILE = Path("/tmp/frank/news_scanner_state.json")
    PID_FILE = Path(f"/run/user/{os.getuid()}/frank/news_scanner.pid")
    LOG_FILE = Path("/tmp/frank/news_scanner.log")

# ---------- Configuration ----------
CHECK_INTERVAL_SECONDS = 300   # Check every 5 minutes if scan is due
SCANS_PER_DAY = 3              # Scan 3x per day (morning, midday, evening)
SCAN_HOURS = [8, 13, 18]      # Target hours for scans (08:00, 13:00, 18:00)
QUIET_HOURS_START = 23         # No scanning after 23:00
QUIET_HOURS_END = 6            # No scanning before 06:00
MAX_ARTICLES_PER_SOURCE = 15   # Max articles to store per source per scan
ARTICLE_RETENTION_DAYS = 90    # Delete articles older than this
MAX_FETCH_CHARS = 5000         # Max chars per page fetch
PAUSE_BETWEEN_SOURCES = 2      # Seconds between source fetches

# webd endpoint (local only)
WEBD_BASE = "http://127.0.0.1:8093"

# Feature candidate detection keywords
FEATURE_KEYWORDS = [
    "open source", "self-hosted", "linux tool", "ai agent",
    "automation", "home assistant", "local ai", "privacy",
    "python tool", "cli tool", "systemd", "ubuntu",
    "llm", "local llm", "ollama", "self-hosting",
    "voice assistant", "speech recognition", "tts",
    "monitoring", "dashboard", "homelab",
]

# ---------- Deep Analysis Configuration ----------
DEEP_ANALYSIS_MAX_PER_SCAN = 3     # Max articles to deep-analyze per scan cycle
DEEP_ANALYSIS_PAUSE = 3            # Seconds between deep analysis runs
DEEP_ANALYSIS_MAX_CHARS = 15000    # Max chars to fetch for full article text
GITHUB_URL_RE = re.compile(r'https?://github\.com/([\w.-]+/[\w.-]+)')
CORE_CHAT_URL = "http://127.0.0.1:8088/chat"
try:
    from config.paths import get_db as _get_db
    FAS_DB_PATH = _get_db("fas_scavenger")
    WORLD_EXP_DB = _get_db("world_experience")
except ImportError:
    FAS_DB_PATH = Path.home() / ".local" / "share" / "frank" / "db" / "fas_scavenger.db"
    WORLD_EXP_DB = Path.home() / ".local" / "share" / "frank" / "db" / "world_experience.db"

# ---------- Logging ----------
LOG = logging.getLogger("news_scanner")

# ---------- DB Schema ----------
_SCHEMA_SQL = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;

CREATE TABLE IF NOT EXISTS articles (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    url_hash                TEXT    NOT NULL UNIQUE,
    source_name             TEXT    NOT NULL,
    url                     TEXT    NOT NULL,
    title                   TEXT    NOT NULL DEFAULT '',
    summary                 TEXT    NOT NULL DEFAULT '',
    published_date          TEXT    DEFAULT '',
    fetched_at              TEXT    NOT NULL,
    category                TEXT    DEFAULT '',
    lang                    TEXT    DEFAULT 'de',
    is_feature_candidate    INTEGER DEFAULT 0,
    feature_keywords_matched TEXT   DEFAULT '',
    content_length          INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_articles_source ON articles(source_name);
CREATE INDEX IF NOT EXISTS idx_articles_fetched ON articles(fetched_at);
CREATE INDEX IF NOT EXISTS idx_articles_category ON articles(category);
CREATE INDEX IF NOT EXISTS idx_articles_feature ON articles(is_feature_candidate);

CREATE TABLE IF NOT EXISTS scan_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_date       TEXT    NOT NULL,
    source_name     TEXT    NOT NULL,
    status          TEXT    NOT NULL,
    articles_found  INTEGER DEFAULT 0,
    articles_new    INTEGER DEFAULT 0,
    error_detail    TEXT    DEFAULT '',
    duration_ms     INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_scanlog_date ON scan_log(scan_date);

CREATE TABLE IF NOT EXISTS daemon_meta (
    key     TEXT PRIMARY KEY,
    value   TEXT NOT NULL,
    updated TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS deep_analysis (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    article_id          INTEGER NOT NULL,
    article_url         TEXT    NOT NULL,
    full_text           TEXT    DEFAULT '',
    github_urls_found   TEXT    DEFAULT '[]',
    llm_analysis        TEXT    DEFAULT '',
    self_improvement    TEXT    DEFAULT '',
    relevance_score     REAL    DEFAULT 0.0,
    analyzed_at         TEXT    NOT NULL,
    fas_feature_written INTEGER DEFAULT 0,
    genesis_injected    INTEGER DEFAULT 0,
    world_exp_recorded  INTEGER DEFAULT 0,
    FOREIGN KEY (article_id) REFERENCES articles(id)
);
CREATE INDEX IF NOT EXISTS idx_deep_article ON deep_analysis(article_id);
"""


# =============================================================================
# Minimal HTTP helper (local webd only, no external network calls)
# =============================================================================

def _http_post_json(url: str, payload: dict, timeout_s: float = 15.0) -> dict:
    """POST JSON to webd. Only calls 127.0.0.1."""
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            return json.loads(resp.read().decode("utf-8", errors="replace"))
    except Exception as e:
        return {"ok": False, "error": str(e)}


# =============================================================================
# Database
# =============================================================================

class NewsDB:
    """Lightweight SQLite wrapper for news_scanner.db."""

    def __init__(self, db_path: Path):
        self._path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path), timeout=10)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self):
        for stmt in _SCHEMA_SQL.strip().split(";"):
            stmt = stmt.strip()
            if stmt:
                self._conn.execute(stmt)
        self._conn.commit()

    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        return self._conn.execute(sql, params)

    def commit(self):
        self._conn.commit()

    def close(self):
        try:
            self._conn.close()
        except Exception:
            pass

    def insert_article(self, article: dict) -> bool:
        """Insert article with dedup. Returns True if new, False if duplicate."""
        try:
            self._conn.execute(
                "INSERT INTO articles "
                "(url_hash, source_name, url, title, summary, published_date, "
                " fetched_at, category, lang, is_feature_candidate, "
                " feature_keywords_matched, content_length) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    article["url_hash"],
                    article["source_name"],
                    article["url"],
                    article.get("title", "")[:500],
                    article.get("summary", "")[:1000],
                    article.get("published_date", ""),
                    article["fetched_at"],
                    article.get("category", ""),
                    article.get("lang", "de"),
                    article.get("is_feature_candidate", 0),
                    article.get("feature_keywords_matched", ""),
                    article.get("content_length", 0),
                ),
            )
            self._conn.commit()
            return True
        except sqlite3.IntegrityError:
            # Duplicate url_hash
            return False

    def log_scan(self, scan_date: str, source_name: str, status: str,
                 articles_found: int = 0, articles_new: int = 0,
                 error_detail: str = "", duration_ms: int = 0):
        self._conn.execute(
            "INSERT INTO scan_log (scan_date, source_name, status, "
            "articles_found, articles_new, error_detail, duration_ms) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (scan_date, source_name, status, articles_found,
             articles_new, error_detail, duration_ms),
        )
        self._conn.commit()

    def get_meta(self, key: str, default: str = "") -> str:
        row = self._conn.execute(
            "SELECT value FROM daemon_meta WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else default

    def set_meta(self, key: str, value: str):
        now = datetime.now().isoformat()
        self._conn.execute(
            "INSERT OR REPLACE INTO daemon_meta (key, value, updated) "
            "VALUES (?, ?, ?)", (key, value, now),
        )
        self._conn.commit()

    def get_recent_headlines(self, days: int = 1, limit: int = 20) -> List[dict]:
        """Get recent articles."""
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        rows = self._conn.execute(
            "SELECT source_name, title, summary, url, category, fetched_at "
            "FROM articles WHERE fetched_at >= ? "
            "ORDER BY fetched_at DESC LIMIT ?",
            (cutoff, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_feature_candidates(self, days: int = 7, limit: int = 10) -> List[dict]:
        """Get articles flagged as feature candidates."""
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        rows = self._conn.execute(
            "SELECT source_name, title, summary, url, feature_keywords_matched, fetched_at "
            "FROM articles WHERE is_feature_candidate = 1 AND fetched_at >= ? "
            "ORDER BY fetched_at DESC LIMIT ?",
            (cutoff, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def cleanup_old_articles(self, retention_days: int = 90) -> int:
        """Delete articles older than retention_days. Returns count deleted."""
        cutoff = (datetime.now() - timedelta(days=retention_days)).isoformat()
        cur = self._conn.execute(
            "DELETE FROM articles WHERE fetched_at < ?", (cutoff,)
        )
        self._conn.commit()
        return cur.rowcount

    def get_scan_stats(self) -> dict:
        """Get scan statistics."""
        today = datetime.now().strftime("%Y-%m-%d")
        total = self._conn.execute("SELECT COUNT(*) as c FROM articles").fetchone()["c"]
        today_new = self._conn.execute(
            "SELECT COUNT(*) as c FROM articles WHERE fetched_at >= ?",
            (today,),
        ).fetchone()["c"]
        features = self._conn.execute(
            "SELECT COUNT(*) as c FROM articles WHERE is_feature_candidate = 1"
        ).fetchone()["c"]
        last_scan = self.get_meta("last_scan_date", "never")
        return {
            "total_articles": total,
            "today_new": today_new,
            "feature_candidates": features,
            "last_scan_date": last_scan,
        }


# =============================================================================
# News Scanner Daemon
# =============================================================================

class NewsScannerDaemon:
    """
    Autonomous daily news scanner.

    Lifecycle: start() -> _daemon_loop() [sleeps 5min, checks if scan due] -> stop()
    """

    def __init__(self):
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._shutdown_event = threading.Event()
        self._db: Optional[NewsDB] = None
        self._sources: List[dict] = []
        self._load_sources()
        LOG.info("News Scanner initialized (%d sources)", len(self._sources))

    def _load_sources(self):
        """Load news sources from JSON config."""
        if SOURCES_FILE.exists():
            try:
                self._sources = json.loads(SOURCES_FILE.read_text())
                LOG.info("Loaded %d sources from %s", len(self._sources), SOURCES_FILE)
            except Exception as e:
                LOG.error("Failed to load sources: %s", e)
                self._sources = []
        else:
            LOG.warning("Sources file not found: %s", SOURCES_FILE)
            self._sources = []

    def _ensure_db(self):
        """Lazy-init database connection."""
        if self._db is None:
            self._db = NewsDB(DB_PATH)

    # === Guard Checks ===

    def _is_gaming_mode(self) -> bool:
        """Check if gaming mode is active. Read-only file check."""
        try:
            if GAMING_STATE_FILE.exists():
                data = json.loads(GAMING_STATE_FILE.read_text())
                return data.get("active", False)
        except Exception:
            pass
        return False

    def _is_quiet_hours(self) -> bool:
        """Check if current time is in quiet hours."""
        hour = datetime.now().hour
        if QUIET_HOURS_START > QUIET_HOURS_END:
            return hour >= QUIET_HOURS_START or hour < QUIET_HOURS_END
        return QUIET_HOURS_START <= hour < QUIET_HOURS_END

    def _get_next_scan_slot(self) -> Optional[int]:
        """
        Determine which scan slot (0, 1, 2) is next.
        Returns the slot index if a scan is due, None if all done for today.
        """
        self._ensure_db()
        now = datetime.now()
        today = now.strftime("%Y-%m-%d")

        # How many scans done today?
        scans_done = int(self._db.get_meta(f"scans_done_{today}", "0"))

        if scans_done >= SCANS_PER_DAY:
            return None  # All scans done for today

        # Check if current hour is past the next scan hour
        next_slot = scans_done  # 0-indexed
        if next_slot < len(SCAN_HOURS) and now.hour >= SCAN_HOURS[next_slot]:
            return next_slot

        return None  # Not time yet

    def _can_scan(self) -> Tuple[bool, str]:
        """Combined guard check. Returns (can_scan, reason)."""
        if self._is_gaming_mode():
            return False, "Gaming mode active"
        if self._is_quiet_hours():
            return False, "Quiet hours"
        if not self._sources:
            return False, "No sources configured"
        slot = self._get_next_scan_slot()
        if slot is None:
            return False, "All scans done for today or not scan time yet"
        return True, f"Scan slot {slot + 1}/{SCANS_PER_DAY} due"

    # === Scanning ===

    def _run_daily_scan(self):
        """Scan all sources sequentially. Re-checks gaming mode between each."""
        self._ensure_db()
        today = datetime.now().strftime("%Y-%m-%d")
        total_new = 0
        total_found = 0
        scanned_count = 0

        LOG.info("=== Daily scan starting (%d sources) ===", len(self._sources))

        for source in self._sources:
            # Re-check gaming mode BETWEEN each source
            if self._is_gaming_mode():
                LOG.info("Gaming mode activated mid-scan, aborting remaining sources")
                break

            name = source.get("name", "unknown")
            start_ms = int(time.time() * 1000)

            try:
                rss_url = source.get("rss_url")
                if rss_url:
                    articles = self._scan_source_rss(source)
                else:
                    articles = self._scan_source_html(source)

                new_count = 0
                for article in articles:
                    # Check for feature candidate
                    is_feature, matched = self._check_feature_candidate(
                        article.get("title", ""), article.get("summary", "")
                    )
                    article["is_feature_candidate"] = 1 if is_feature else 0
                    article["feature_keywords_matched"] = matched
                    article["fetched_at"] = datetime.now().isoformat()

                    if self._db.insert_article(article):
                        new_count += 1

                duration_ms = int(time.time() * 1000) - start_ms
                self._db.log_scan(today, name, "ok", len(articles), new_count,
                                  duration_ms=duration_ms)

                total_found += len(articles)
                total_new += new_count
                scanned_count += 1

                LOG.info("  [%s] %d found, %d new (%dms)",
                         name, len(articles), new_count, duration_ms)

            except Exception as e:
                duration_ms = int(time.time() * 1000) - start_ms
                self._db.log_scan(today, name, "error", error_detail=str(e)[:500],
                                  duration_ms=duration_ms)
                LOG.error("  [%s] ERROR: %s", name, e)

            # Polite pause between sources (respect system resources)
            time.sleep(PAUSE_BETWEEN_SOURCES)

        # Increment scan counter for today (even partial scans count)
        if scanned_count > 0:
            self._db.set_meta("last_scan_date", today)
            prev = int(self._db.get_meta(f"scans_done_{today}", "0"))
            self._db.set_meta(f"scans_done_{today}", str(prev + 1))

        # Cleanup old articles
        deleted = self._db.cleanup_old_articles(ARTICLE_RETENTION_DAYS)
        if deleted > 0:
            LOG.info("Cleaned up %d old articles", deleted)

        LOG.info("=== Daily scan complete: %d/%d sources, %d found, %d new ===",
                 scanned_count, len(self._sources), total_found, total_new)

        # Deep Analysis Phase: analyze feature candidates
        if total_new > 0 or self._has_unanalyzed_candidates():
            if not self._is_gaming_mode():
                LOG.info("=== Deep Analysis Phase ===")
                try:
                    self._run_deep_analysis()
                except Exception as e:
                    LOG.error("Deep analysis phase error: %s", e)

    def _scan_source_rss(self, source: dict) -> List[dict]:
        """Fetch RSS feed via webd /rss endpoint."""
        rss_url = source["rss_url"]
        result = _http_post_json(
            f"{WEBD_BASE}/rss",
            {"url": rss_url, "limit": MAX_ARTICLES_PER_SOURCE},
            timeout_s=15.0,
        )
        if not result.get("ok"):
            raise RuntimeError(f"RSS fetch failed: {result.get('error', 'unknown')}")

        articles = []
        for item in result.get("items", [])[:MAX_ARTICLES_PER_SOURCE]:
            url = item.get("link", "")
            if not url:
                continue
            title = (item.get("title") or "")[:500]
            summary = (item.get("summary") or "")[:1000]
            articles.append({
                "url": url,
                "url_hash": hashlib.sha256(url.encode()).hexdigest(),
                "source_name": source["name"],
                "title": title,
                "summary": summary,
                "published_date": item.get("published", ""),
                "category": source.get("category", ""),
                "lang": source.get("lang", "de"),
                "content_length": len(title) + len(summary),
            })
        return articles

    def _scan_source_html(self, source: dict) -> List[dict]:
        """Fetch HTML page via webd /fetch endpoint and store as digest."""
        result = _http_post_json(
            f"{WEBD_BASE}/fetch",
            {"url": source["url"], "max_chars": MAX_FETCH_CHARS},
            timeout_s=20.0,
        )
        if not result.get("ok"):
            raise RuntimeError(f"HTML fetch failed: {result.get('error', 'unknown')}")

        title = (result.get("title") or source["name"])[:500]
        text = (result.get("text") or "")[:1000]
        url = source["url"]

        # Daily hash: same page gets a new entry each day (content may change)
        date_str = datetime.now().strftime("%Y-%m-%d")
        url_hash = hashlib.sha256(f"{url}#{date_str}".encode()).hexdigest()

        return [{
            "url": url,
            "url_hash": url_hash,
            "source_name": source["name"],
            "title": title,
            "summary": text,
            "published_date": date_str,
            "category": source.get("category", ""),
            "lang": source.get("lang", "de"),
            "content_length": len(text),
        }]

    def _check_feature_candidate(self, title: str, summary: str) -> Tuple[bool, str]:
        """Check if article might suggest a feature for Frank."""
        text = f"{title} {summary}".lower()
        matched = [kw for kw in FEATURE_KEYWORDS if kw in text]
        return (len(matched) > 0, ", ".join(matched))

    # === Deep Analysis ===

    def _has_unanalyzed_candidates(self) -> bool:
        """Check if there are feature candidates not yet deep-analyzed."""
        self._ensure_db()
        row = self._db.execute(
            "SELECT COUNT(*) as c FROM articles "
            "WHERE is_feature_candidate = 1 "
            "AND id NOT IN (SELECT article_id FROM deep_analysis)",
        ).fetchone()
        return row["c"] > 0

    def _run_deep_analysis(self):
        """Deep-analyze unanalyzed feature candidates after regular scan."""
        self._ensure_db()

        # Get unanalyzed feature candidates
        candidates = self._db.execute(
            "SELECT id, url, title, summary, source_name, category "
            "FROM articles "
            "WHERE is_feature_candidate = 1 "
            "AND id NOT IN (SELECT article_id FROM deep_analysis) "
            "ORDER BY fetched_at DESC LIMIT ?",
            (DEEP_ANALYSIS_MAX_PER_SCAN,),
        ).fetchall()

        if not candidates:
            LOG.debug("No unanalyzed feature candidates")
            return

        LOG.info("Deep analysis: %d candidates to analyze", len(candidates))

        for article_row in candidates:
            # Re-check gaming mode BETWEEN each article
            if self._is_gaming_mode():
                LOG.info("Gaming mode activated, aborting deep analysis")
                return

            article = dict(article_row)
            try:
                self._deep_analyze_article(article)
            except Exception as e:
                LOG.error("Deep analysis failed for article %d: %s",
                          article["id"], e)

            time.sleep(DEEP_ANALYSIS_PAUSE)

    def _deep_analyze_article(self, article: dict):
        """Full deep analysis of one feature candidate article."""
        article_id = article["id"]
        url = article["url"]
        title = article.get("title", "")

        LOG.info("  Deep analyzing: %s", title[:80])

        # 1. Fetch full article text via webd
        full_text = ""
        try:
            result = _http_post_json(
                f"{WEBD_BASE}/fetch",
                {"url": url, "max_chars": DEEP_ANALYSIS_MAX_CHARS},
                timeout_s=20.0,
            )
            if result.get("ok"):
                full_text = result.get("text", "")[:DEEP_ANALYSIS_MAX_CHARS]
        except Exception as e:
            LOG.warning("  Failed to fetch full text: %s", e)

        # 2. Extract GitHub URLs
        search_text = f"{title} {article.get('summary', '')} {full_text}"
        github_matches = GITHUB_URL_RE.findall(search_text)
        # Deduplicate and clean (findall returns the capture group: owner/repo)
        github_urls = list(dict.fromkeys(
            f"https://github.com/{m}" for m in github_matches
        ))

        # 3. LLM analysis
        llm_result = self._llm_analyze(title, full_text or article.get("summary", ""),
                                        github_urls)

        # 4. Store in deep_analysis table
        now = datetime.now().isoformat()
        self._db.execute(
            "INSERT INTO deep_analysis "
            "(article_id, article_url, full_text, github_urls_found, "
            " llm_analysis, self_improvement, relevance_score, analyzed_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                article_id,
                url,
                full_text[:5000],  # Truncate for storage
                json.dumps(github_urls),
                llm_result.get("analysis", "")[:2000],
                llm_result.get("self_improvement", "")[:1000],
                llm_result.get("relevance_score", 0.0),
                now,
            ),
        )
        self._db.commit()

        LOG.info("  Analysis stored (relevance=%.2f, github_urls=%d)",
                 llm_result.get("relevance_score", 0.0), len(github_urls))

        # 5. Bridge to FAS if GitHub URLs found
        if github_urls:
            try:
                self._bridge_to_fas(article, llm_result, github_urls)
                self._db.execute(
                    "UPDATE deep_analysis SET fas_feature_written = 1 "
                    "WHERE article_id = ?", (article_id,),
                )
                self._db.commit()
            except Exception as e:
                LOG.warning("  FAS bridge failed: %s", e)

        # 6. Record world experience observation
        try:
            self._record_world_observation(article, llm_result)
            self._db.execute(
                "UPDATE deep_analysis SET world_exp_recorded = 1 "
                "WHERE article_id = ?", (article_id,),
            )
            self._db.commit()
        except Exception as e:
            LOG.warning("  World experience recording failed: %s", e)

    def _llm_analyze(self, title: str, text: str, github_urls: list) -> dict:
        """Call local LLM via core chat API for deep analysis."""
        result = {
            "analysis": "",
            "self_improvement": "",
            "relevance_score": 0.0,
        }

        # Build analysis prompt
        github_info = ""
        if github_urls:
            github_info = f"\nFound GitHub repos: {', '.join(github_urls[:3])}"

        prompt = (
            f"You are Frank, an autonomous AI system on Linux. "
            f"Analyze this article briefly and concisely:\n\n"
            f"Title: {title}\n"
            f"Content: {text[:3000]}\n"
            f"{github_info}\n\n"
            f"Answer in at most 5 sentences:\n"
            f"1. ANALYSIS: What is the key message?\n"
            f"2. SELF-IMPROVEMENT: What could you as an AI system learn from this "
            f"or implement as a feature?\n"
            f"3. RELEVANCE: Rate the relevance for you as a number 0.0-1.0\n"
            f"Answer ONLY with the 3 points, no introduction."
        )

        try:
            resp = _http_post_json(
                CORE_CHAT_URL,
                {
                    "text": prompt,
                    "want_tools": False,
                    "max_tokens": 800,
                    "timeout_s": 120,
                    "task": "news_analysis",
                },
                timeout_s=180.0,  # LLM can be slow
            )
            if resp.get("ok") and (resp.get("text") or resp.get("reply")):
                reply = resp.get("text") or resp.get("reply")
                result["analysis"] = reply

                # Try to extract relevance score from response
                score_match = re.search(
                    r'RELEVANZ[:\s]*(\d+\.?\d*)', reply, re.IGNORECASE
                )
                if score_match:
                    try:
                        score = float(score_match.group(1))
                        result["relevance_score"] = min(1.0, max(0.0, score))
                    except ValueError:
                        pass

                # Try to extract self-improvement section
                si_match = re.search(
                    r'SELBSTVERBESSERUNG[:\s]*(.*?)(?:RELEVANZ|\Z)',
                    reply, re.IGNORECASE | re.DOTALL
                )
                if si_match:
                    result["self_improvement"] = si_match.group(1).strip()

        except Exception as e:
            LOG.warning("  LLM analysis failed: %s", e)

        return result

    def _bridge_to_fas(self, article: dict, analysis: dict, github_urls: list):
        """Write discovered features to fas_scavenger.db extracted_features.

        GitHubEcho sensor picks them up emergently via Genesis.
        """
        if not FAS_DB_PATH.parent.exists():
            LOG.warning("FAS database directory not found")
            return

        try:
            conn = sqlite3.connect(str(FAS_DB_PATH), timeout=10)
            now = datetime.now().isoformat()

            # Ensure source_url and quarantine_count columns exist
            try:
                conn.execute("SELECT source_url FROM extracted_features LIMIT 0")
            except sqlite3.OperationalError:
                conn.execute("ALTER TABLE extracted_features ADD COLUMN source_url TEXT")
                conn.execute("ALTER TABLE extracted_features ADD COLUMN quarantine_count INTEGER DEFAULT 0")
                conn.commit()

            for github_url in github_urls[:3]:  # Max 3 repos per article
                # Extract owner/repo from URL
                match = GITHUB_URL_RE.search(github_url)
                if not match:
                    continue
                repo_name = match.group(1)

                # Check if already exists
                existing = conn.execute(
                    "SELECT id FROM extracted_features WHERE repo_name = ? AND name = ?",
                    (repo_name, article.get("title", "")[:200]),
                ).fetchone()
                if existing:
                    continue

                conn.execute(
                    "INSERT INTO extracted_features "
                    "(repo_name, feature_type, name, description, file_path, "
                    " code_snippet, relevance_score, created_at, "
                    " source_url, confidence_score, integration_status) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        repo_name,
                        "news_discovery",
                        article.get("title", "")[:200],
                        analysis.get("analysis", "")[:1000],
                        "",   # file_path
                        "",   # code_snippet
                        analysis.get("relevance_score", 0.5),
                        now,
                        article.get("url", ""),
                        analysis.get("relevance_score", 0.5),
                        "pending",
                    ),
                )
                LOG.info("  Bridged to FAS: %s from %s", repo_name,
                         article.get("source_name", "?"))

            conn.commit()
            conn.close()
        except Exception as e:
            LOG.error("  FAS bridge error: %s", e)

    def _record_world_observation(self, article: dict, analysis: dict):
        """Record causal observation in world_experience.db.

        Follows the world_experience_daemon's observe() pattern via direct DB insert.
        """
        if not WORLD_EXP_DB.exists():
            LOG.debug("World experience DB not found, skipping")
            return

        try:
            conn = sqlite3.connect(str(WORLD_EXP_DB), timeout=10)
            conn.row_factory = sqlite3.Row
            now = datetime.now().isoformat()

            source_name = article.get("source_name", "unknown_source")
            cause_name = f"news_scan_{source_name}"
            effect_name = "feature_discovery" if analysis.get("relevance_score", 0) > 0.5 \
                else "knowledge_acquisition"

            # Upsert cause entity
            cause_row = conn.execute(
                "SELECT id FROM entities WHERE name = ?", (cause_name,)
            ).fetchone()
            if cause_row:
                conn.execute(
                    "UPDATE entities SET last_seen = ? WHERE id = ?",
                    (now, cause_row["id"]),
                )
                cause_id = cause_row["id"]
            else:
                cur = conn.execute(
                    "INSERT INTO entities (entity_type, name, metadata, first_seen, last_seen) "
                    "VALUES (?, ?, ?, ?, ?)",
                    ("news_source", cause_name, json.dumps({"source": source_name}), now, now),
                )
                cause_id = cur.lastrowid

            # Upsert effect entity
            effect_row = conn.execute(
                "SELECT id FROM entities WHERE name = ?", (effect_name,)
            ).fetchone()
            if effect_row:
                conn.execute(
                    "UPDATE entities SET last_seen = ? WHERE id = ?",
                    (now, effect_row["id"]),
                )
                effect_id = effect_row["id"]
            else:
                cur = conn.execute(
                    "INSERT INTO entities (entity_type, name, metadata, first_seen, last_seen) "
                    "VALUES (?, ?, ?, ?, ?)",
                    ("learning_outcome", effect_name, "{}", now, now),
                )
                effect_id = cur.lastrowid

            # Upsert causal link
            link_row = conn.execute(
                "SELECT id, confidence, observation_count FROM causal_links "
                "WHERE cause_entity_id = ? AND effect_entity_id = ? AND relation_type = ?",
                (cause_id, effect_id, "triggers"),
            ).fetchone()

            evidence = analysis.get("relevance_score", 0.1)
            if link_row:
                # Bayesian update: new_conf = old + delta * (1 - old)
                old_conf = link_row["confidence"]
                new_conf = old_conf + evidence * (1 - old_conf)
                conn.execute(
                    "UPDATE causal_links SET confidence = ?, observation_count = observation_count + 1, "
                    "last_observed = ? WHERE id = ?",
                    (min(1.0, new_conf), now, link_row["id"]),
                )
            else:
                conn.execute(
                    "INSERT INTO causal_links "
                    "(cause_entity_id, effect_entity_id, relation_type, confidence, "
                    " observation_count, first_observed, last_observed) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (cause_id, effect_id, "triggers", 0.5, 1, now, now),
                )

            conn.commit()
            conn.close()
            LOG.debug("  World experience recorded: %s -> %s", cause_name, effect_name)

        except Exception as e:
            LOG.warning("  World experience error: %s", e)

    # === Daemon Lifecycle ===

    def _daemon_loop(self):
        """Main loop: check every 5 minutes if scan is due."""
        LOG.info("Daemon loop started (check every %ds)", CHECK_INTERVAL_SECONDS)

        while self._running and not self._shutdown_event.is_set():
            try:
                can_scan, reason = self._can_scan()
                if can_scan:
                    LOG.info("Daily scan triggered")
                    self._run_daily_scan()
                else:
                    LOG.debug("Scan not due: %s", reason)
            except Exception as e:
                LOG.error("Daemon loop error: %s", e, exc_info=True)

            # Sleep until next check (or shutdown signal)
            self._shutdown_event.wait(CHECK_INTERVAL_SECONDS)

        LOG.info("Daemon loop ended")

    def start(self):
        """Start the daemon."""
        if self._running:
            LOG.warning("Daemon already running")
            return

        self._running = True
        self._shutdown_event.clear()
        self._thread = threading.Thread(target=self._daemon_loop, daemon=True)
        self._thread.start()
        LOG.info("News Scanner Daemon started")

    def stop(self):
        """Stop the daemon gracefully."""
        LOG.info("Stopping News Scanner Daemon...")
        self._running = False
        self._shutdown_event.set()

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)

        if self._db:
            self._db.close()
            self._db = None

        LOG.info("News Scanner Daemon stopped")

    # === Query API (for context injection and CLI) ===

    def run_once(self):
        """Run a single scan cycle (for testing/manual trigger)."""
        self._ensure_db()
        LOG.info("Running single scan cycle...")
        self._run_daily_scan()

    def get_status(self) -> dict:
        """Get daemon status."""
        self._ensure_db()
        can_scan, reason = self._can_scan()
        stats = self._db.get_scan_stats()
        return {
            "running": self._running,
            "can_scan": can_scan,
            "scan_blocked_reason": reason if not can_scan else None,
            "gaming_mode": self._is_gaming_mode(),
            "quiet_hours": self._is_quiet_hours(),
            "sources_count": len(self._sources),
            **stats,
        }

    def get_digest(self, days: int = 1) -> dict:
        """Get a news digest for the last N days."""
        self._ensure_db()
        articles = self._db.get_recent_headlines(days=days, limit=30)
        features = self._db.get_feature_candidates(days=days, limit=10)
        return {
            "period_days": days,
            "articles": articles,
            "feature_candidates": features,
            "total_articles": len(articles),
            "total_features": len(features),
        }

    def get_feature_candidates(self, days: int = 7) -> List[dict]:
        """Get articles flagged as potential features for Frank."""
        self._ensure_db()
        return self._db.get_feature_candidates(days=days)


# =============================================================================
# Context Injection (for overlay chat integration)
# =============================================================================

def context_inject(user_message: str, max_items: int = 5) -> str:
    """
    Return recent news context for LLM prompt injection.

    Only triggers for news/tech/AI related queries to avoid unnecessary context.
    """
    msg_lower = user_message.lower()

    # Only inject for news/tech/AI related queries
    triggers = [
        "news", "nachrichten", "neues", "neuigkeiten",
        "was gibt", "aktuell", "trends", "schlagzeilen",
        "headlines", "tech news", "ai news", "ki news",
        "was tut sich", "open source news",
    ]
    if not any(t in msg_lower for t in triggers):
        return ""

    try:
        db = NewsDB(DB_PATH)
        articles = db.get_recent_headlines(days=2, limit=max_items)
        db.close()
    except Exception:
        return ""

    if not articles:
        return ""

    lines = []
    for a in articles:
        source = a.get("source_name", "?")
        title = a.get("title", "")
        if title:
            lines.append(f"- [{source}] {title}")

    if not lines:
        return ""

    return (
        "[Recent news from Frank's daily scan:\n"
        + "\n".join(lines)
        + "]\n"
    )


# =============================================================================
# CLI / main
# =============================================================================

_daemon: Optional[NewsScannerDaemon] = None


def get_daemon() -> NewsScannerDaemon:
    """Get daemon singleton."""
    global _daemon
    if _daemon is None:
        _daemon = NewsScannerDaemon()
    return _daemon


def signal_handler(sig, frame):
    """Handle shutdown signals."""
    LOG.info("Received signal %s, shutting down...", sig)
    if _daemon:
        _daemon.stop()
    sys.exit(0)


def _is_process_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def write_pid():
    PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    if PID_FILE.exists():
        try:
            old_pid = int(PID_FILE.read_text().strip())
            if not _is_process_running(old_pid):
                LOG.info("Removing stale PID file (PID %d not running)", old_pid)
                PID_FILE.unlink()
        except (ValueError, OSError):
            try:
                PID_FILE.unlink()
            except OSError:
                pass
    PID_FILE.write_text(str(os.getpid()))


def remove_pid():
    try:
        if PID_FILE.exists():
            PID_FILE.unlink()
    except Exception:
        pass


def _format_digest(digest: dict) -> str:
    """Format digest for CLI output."""
    lines = []
    articles = digest.get("articles", [])
    features = digest.get("feature_candidates", [])

    if not articles:
        lines.append("No articles in the last %d days." % digest.get("period_days", 1))
    else:
        lines.append(f"=== News Digest ({len(articles)} articles) ===\n")
        # Group by source
        by_source: Dict[str, list] = {}
        for a in articles:
            src = a.get("source_name", "?")
            by_source.setdefault(src, []).append(a)
        for src, arts in by_source.items():
            lines.append(f"--- {src} ({len(arts)}) ---")
            for a in arts[:5]:
                title = a.get("title", "(no title)")[:80]
                lines.append(f"  * {title}")
            if len(arts) > 5:
                lines.append(f"  ... and {len(arts) - 5} more")
            lines.append("")

    if features:
        lines.append(f"\n=== Feature Candidates ({len(features)}) ===\n")
        for f in features:
            title = f.get("title", "")[:60]
            kw = f.get("feature_keywords_matched", "")
            lines.append(f"  * {title}")
            if kw:
                lines.append(f"    Keywords: {kw}")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="News Scanner Daemon - Frank's Daily Knowledge Acquisition"
    )
    parser.add_argument("--daemon", action="store_true", help="Run as daemon")
    parser.add_argument("--once", action="store_true", help="Run single scan now")
    parser.add_argument("--status", action="store_true", help="Show status")
    parser.add_argument("--digest", action="store_true", help="Show today's digest")
    parser.add_argument("--digest-days", type=int, default=1, help="Days for digest (default: 1)")
    parser.add_argument("--features", action="store_true", help="Show feature candidates")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    # Setup logging
    log_level = logging.DEBUG if args.debug else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(LOG_FILE),
        ],
    )

    daemon = get_daemon()

    if args.status:
        status = daemon.get_status()
        print(json.dumps(status, indent=2, default=str))
        return

    if args.digest:
        digest = daemon.get_digest(days=args.digest_days)
        print(_format_digest(digest))
        return

    if args.features:
        features = daemon.get_feature_candidates(days=7)
        if not features:
            print("No feature candidates in the last 7 days.")
        else:
            print(f"=== Feature Candidates ({len(features)}) ===\n")
            for f in features:
                print(f"  * {f.get('title', '')[:80]}")
                print(f"    URL: {f.get('url', '')}")
                print(f"    Keywords: {f.get('feature_keywords_matched', '')}")
                print(f"    Source: {f.get('source_name', '')}")
                print()
        return

    if args.once:
        daemon.run_once()
        # Show quick summary
        stats = daemon.get_status()
        print(f"\nScan complete. Total articles: {stats['total_articles']}, "
              f"Today new: {stats['today_new']}, "
              f"Feature candidates: {stats['feature_candidates']}")
        return

    if args.daemon:
        LOG.info("=" * 60)
        LOG.info("NEWS SCANNER DAEMON - Frank's Daily Knowledge Acquisition")
        LOG.info("=" * 60)
        LOG.info("Sources: %d", len(daemon._sources))
        LOG.info("Scans per day: %d (at hours %s)", SCANS_PER_DAY,
                 ", ".join(f"{h}:00" for h in SCAN_HOURS))
        LOG.info("Check interval: %ds", CHECK_INTERVAL_SECONDS)
        LOG.info("Quiet hours: %d:00 - %d:00", QUIET_HOURS_START, QUIET_HOURS_END)
        LOG.info("DB: %s", DB_PATH)
        LOG.info("")

        signal.signal(signal.SIGTERM, signal_handler)
        signal.signal(signal.SIGINT, signal_handler)

        write_pid()

        try:
            daemon.start()

            # Keep main thread alive
            while daemon._running:
                time.sleep(1)

        except KeyboardInterrupt:
            LOG.info("Interrupted by user")
        finally:
            daemon.stop()
            remove_pid()

        return

    # Default: show help
    parser.print_help()


if __name__ == "__main__":
    main()
