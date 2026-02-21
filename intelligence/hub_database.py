#!/usr/bin/env python3
"""
F.I.H. Hub Database
Central database for all intelligence proposals.
"""

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any
import logging

from intelligence.unified_proposal import (
    UnifiedProposal, Correlation, Prediction,
    ProposalStatus, SourceType
)

LOG = logging.getLogger("fih")


class HubDatabase:
    """
    Central database for F.I.H. proposals.
    Stores proposals from all sources in a unified format.
    """

    try:
        from config.paths import get_db
        DB_PATH = get_db("intelligence_hub")
    except ImportError:
        DB_PATH = Path.home() / ".local/share/frank/db/intelligence_hub.db"

    def __init__(self, db_path: Path = None):
        self.db_path = db_path or self.DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: Optional[sqlite3.Connection] = None
        self._ensure_schema()

    def _get_conn(self) -> sqlite3.Connection:
        """Get database connection."""
        if self._conn is None:
            self._conn = sqlite3.connect(
                self.db_path,
                check_same_thread=False,
                timeout=30.0
            )
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def _ensure_schema(self):
        """Create database schema."""
        conn = self._get_conn()

        # Unified proposals table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS proposals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_type TEXT NOT NULL,
                source_id TEXT,
                category TEXT NOT NULL,
                name TEXT NOT NULL,
                description TEXT,

                problem_statement TEXT,
                proposed_solution TEXT,
                expected_benefit TEXT,

                confidence_score REAL DEFAULT 0.0,
                priority_score REAL DEFAULT 0.0,
                urgency TEXT DEFAULT 'medium',
                user_relevance REAL DEFAULT 0.0,

                evidence TEXT,
                related_events TEXT,
                correlations TEXT,

                complexity TEXT DEFAULT 'moderate',
                estimated_impact TEXT DEFAULT 'moderate',
                dependencies TEXT,

                code_snippet TEXT,
                full_code TEXT,
                file_path TEXT,
                repo_name TEXT,

                sandbox_tested INTEGER DEFAULT 0,
                sandbox_passed INTEGER DEFAULT 0,
                test_output TEXT,
                test_iterations INTEGER DEFAULT 0,

                status TEXT DEFAULT 'discovered',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                notified_at TEXT,
                approved_at TEXT,
                integrated_at TEXT,

                user_notified INTEGER DEFAULT 0,
                user_approved INTEGER DEFAULT 0,
                user_response TEXT,

                integration_path TEXT,
                source_data TEXT,

                UNIQUE(source_type, source_id)
            )
        """)

        # Correlations table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS correlations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                topic TEXT NOT NULL,
                proposal_ids TEXT NOT NULL,
                source_types TEXT NOT NULL,
                combined_confidence REAL DEFAULT 0.0,
                message TEXT,
                recommended_action TEXT,
                created_at TEXT NOT NULL
            )
        """)

        # Predictions table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS predictions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                what TEXT NOT NULL,
                why TEXT,
                expected_when TEXT,
                confidence REAL DEFAULT 0.0,
                related_proposal_ids TEXT,
                created_at TEXT NOT NULL,
                acted_upon INTEGER DEFAULT 0
            )
        """)

        # Scan history
        conn.execute("""
            CREATE TABLE IF NOT EXISTS scan_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_type TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                proposals_found INTEGER DEFAULT 0,
                duration_ms INTEGER DEFAULT 0,
                success INTEGER DEFAULT 1,
                error_message TEXT
            )
        """)

        # User interactions
        conn.execute("""
            CREATE TABLE IF NOT EXISTS user_interactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                proposal_id INTEGER,
                action TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                response TEXT,
                FOREIGN KEY (proposal_id) REFERENCES proposals(id)
            )
        """)

        # Indexes
        conn.execute("CREATE INDEX IF NOT EXISTS idx_proposals_status ON proposals(status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_proposals_source ON proposals(source_type)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_proposals_priority ON proposals(priority_score DESC)")

        conn.commit()

    def save_proposal(self, proposal: UnifiedProposal) -> int:
        """
        Save or update a proposal.
        Returns the proposal ID.
        """
        conn = self._get_conn()

        data = proposal.to_dict()

        # Convert lists to JSON
        for field in ["evidence", "related_events", "correlations", "dependencies"]:
            if isinstance(data.get(field), list):
                data[field] = json.dumps(data[field])

        if isinstance(data.get("source_data"), dict):
            data["source_data"] = json.dumps(data["source_data"])

        # Check if exists
        existing = conn.execute(
            "SELECT id FROM proposals WHERE source_type = ? AND source_id = ?",
            (proposal.source_type, proposal.source_id)
        ).fetchone()

        if existing:
            # Update
            data["updated_at"] = datetime.now().isoformat()
            conn.execute("""
                UPDATE proposals SET
                    category = ?, name = ?, description = ?,
                    problem_statement = ?, proposed_solution = ?, expected_benefit = ?,
                    confidence_score = ?, priority_score = ?, urgency = ?, user_relevance = ?,
                    evidence = ?, related_events = ?, correlations = ?,
                    complexity = ?, estimated_impact = ?, dependencies = ?,
                    code_snippet = ?, full_code = ?, file_path = ?, repo_name = ?,
                    sandbox_tested = ?, sandbox_passed = ?, test_output = ?, test_iterations = ?,
                    status = ?, updated_at = ?,
                    user_notified = ?, user_approved = ?, user_response = ?,
                    integration_path = ?, source_data = ?
                WHERE id = ?
            """, (
                data["category"], data["name"], data["description"],
                data["problem_statement"], data["proposed_solution"], data["expected_benefit"],
                data["confidence_score"], data["priority_score"], data["urgency"], data["user_relevance"],
                data["evidence"], data["related_events"], data["correlations"],
                data["complexity"], data["estimated_impact"], data["dependencies"],
                data["code_snippet"], data["full_code"], data["file_path"], data["repo_name"],
                data["sandbox_tested"], data["sandbox_passed"], data["test_output"], data["test_iterations"],
                data["status"], data["updated_at"],
                data["user_notified"], data["user_approved"], data["user_response"],
                data["integration_path"], data["source_data"],
                existing["id"]
            ))
            conn.commit()
            return existing["id"]
        else:
            # Insert
            data["created_at"] = datetime.now().isoformat()
            data["updated_at"] = data["created_at"]

            cursor = conn.execute("""
                INSERT INTO proposals (
                    source_type, source_id, category, name, description,
                    problem_statement, proposed_solution, expected_benefit,
                    confidence_score, priority_score, urgency, user_relevance,
                    evidence, related_events, correlations,
                    complexity, estimated_impact, dependencies,
                    code_snippet, full_code, file_path, repo_name,
                    sandbox_tested, sandbox_passed, test_output, test_iterations,
                    status, created_at, updated_at,
                    user_notified, user_approved, user_response,
                    integration_path, source_data
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                data["source_type"], data["source_id"], data["category"], data["name"], data["description"],
                data["problem_statement"], data["proposed_solution"], data["expected_benefit"],
                data["confidence_score"], data["priority_score"], data["urgency"], data["user_relevance"],
                data["evidence"], data["related_events"], data["correlations"],
                data["complexity"], data["estimated_impact"], data["dependencies"],
                data["code_snippet"], data["full_code"], data["file_path"], data["repo_name"],
                data["sandbox_tested"], data["sandbox_passed"], data["test_output"], data["test_iterations"],
                data["status"], data["created_at"], data["updated_at"],
                data["user_notified"], data["user_approved"], data["user_response"],
                data["integration_path"], data["source_data"]
            ))
            conn.commit()
            return cursor.lastrowid

    def _row_to_proposal(self, row: sqlite3.Row) -> UnifiedProposal:
        """Convert database row to UnifiedProposal."""
        data = dict(row)

        # Parse JSON fields
        for field in ["evidence", "related_events", "correlations", "dependencies"]:
            if data.get(field):
                try:
                    data[field] = json.loads(data[field])
                except Exception:
                    data[field] = []

        if data.get("source_data"):
            try:
                data["source_data"] = json.loads(data["source_data"])
            except Exception:
                data["source_data"] = {}

        # Convert boolean fields
        for field in ["sandbox_tested", "sandbox_passed", "user_notified", "user_approved"]:
            data[field] = bool(data.get(field, 0))

        return UnifiedProposal.from_dict(data)

    def get_proposal(self, proposal_id: int) -> Optional[UnifiedProposal]:
        """Get a specific proposal by ID."""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM proposals WHERE id = ?",
            (proposal_id,)
        ).fetchone()

        if row:
            return self._row_to_proposal(row)
        return None

    def get_proposals_by_status(self, status: str) -> List[UnifiedProposal]:
        """Get all proposals with a specific status."""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM proposals WHERE status = ? ORDER BY priority_score DESC",
            (status,)
        ).fetchall()

        return [self._row_to_proposal(row) for row in rows]

    def get_ready_proposals(self, min_confidence: float = 0.85) -> List[UnifiedProposal]:
        """Get proposals ready for user review."""
        conn = self._get_conn()
        rows = conn.execute("""
            SELECT * FROM proposals
            WHERE status IN ('ready', 'notified')
              AND confidence_score >= ?
              AND user_approved = 0
            ORDER BY priority_score DESC
        """, (min_confidence,)).fetchall()

        return [self._row_to_proposal(row) for row in rows]

    def get_proposals_by_source(self, source_type: str) -> List[UnifiedProposal]:
        """Get all proposals from a specific source."""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM proposals WHERE source_type = ? ORDER BY priority_score DESC",
            (source_type,)
        ).fetchall()

        return [self._row_to_proposal(row) for row in rows]

    def get_approved_proposals(self) -> List[UnifiedProposal]:
        """Get all approved proposals awaiting integration."""
        conn = self._get_conn()
        rows = conn.execute("""
            SELECT * FROM proposals
            WHERE user_approved = 1
              AND status = 'approved'
            ORDER BY approved_at DESC
        """).fetchall()

        return [self._row_to_proposal(row) for row in rows]

    def get_archived_proposals(self) -> List[UnifiedProposal]:
        """Get rejected/archived proposals."""
        conn = self._get_conn()
        rows = conn.execute("""
            SELECT * FROM proposals
            WHERE status IN ('rejected', 'rejected_permanent')
            ORDER BY updated_at DESC
            LIMIT 100
        """).fetchall()

        return [self._row_to_proposal(row) for row in rows]

    def update_proposal_status(self, proposal_id: int, status: str):
        """Update proposal status."""
        conn = self._get_conn()
        conn.execute(
            "UPDATE proposals SET status = ?, updated_at = ? WHERE id = ?",
            (status, datetime.now().isoformat(), proposal_id)
        )
        conn.commit()

    def save_correlation(self, correlation: Correlation) -> int:
        """Save a correlation."""
        conn = self._get_conn()
        cursor = conn.execute("""
            INSERT INTO correlations
            (topic, proposal_ids, source_types, combined_confidence, message, recommended_action, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            correlation.topic,
            json.dumps(correlation.proposal_ids),
            json.dumps(correlation.source_types),
            correlation.combined_confidence,
            correlation.message,
            correlation.recommended_action,
            correlation.created_at
        ))
        conn.commit()
        return cursor.lastrowid

    def get_statistics(self) -> Dict[str, Any]:
        """Get hub statistics."""
        conn = self._get_conn()

        stats = {}

        # Count by status
        for status in ProposalStatus:
            row = conn.execute(
                "SELECT COUNT(*) as count FROM proposals WHERE status = ?",
                (status.value,)
            ).fetchone()
            stats[f"status_{status.value}"] = row["count"] if row else 0

        # Count by source
        for source in SourceType:
            row = conn.execute(
                "SELECT COUNT(*) as count FROM proposals WHERE source_type = ?",
                (source.value,)
            ).fetchone()
            stats[f"source_{source.value}"] = row["count"] if row else 0

        # Totals
        row = conn.execute("SELECT COUNT(*) as count FROM proposals").fetchone()
        stats["total_proposals"] = row["count"] if row else 0

        row = conn.execute("SELECT COUNT(*) as count FROM correlations").fetchone()
        stats["total_correlations"] = row["count"] if row else 0

        return stats

    def log_scan(self, source_type: str, proposals_found: int, duration_ms: int, success: bool = True, error: str = None):
        """Log a scan operation."""
        conn = self._get_conn()
        conn.execute("""
            INSERT INTO scan_history (source_type, timestamp, proposals_found, duration_ms, success, error_message)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            source_type,
            datetime.now().isoformat(),
            proposals_found,
            duration_ms,
            1 if success else 0,
            error
        ))
        conn.commit()

    def log_user_interaction(self, proposal_id: int, action: str, response: str = None):
        """Log user interaction with a proposal."""
        conn = self._get_conn()
        conn.execute("""
            INSERT INTO user_interactions (proposal_id, action, timestamp, response)
            VALUES (?, ?, ?, ?)
        """, (proposal_id, action, datetime.now().isoformat(), response))
        conn.commit()
