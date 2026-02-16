#!/usr/bin/env python3
"""
A.S.R.S. Database Schema
Manages database schema for A.S.R.S. tables.
"""

import re
import sqlite3
from pathlib import Path
import logging

LOG = logging.getLogger("asrs.db_schema")

# Pattern for valid SQL identifiers (SQL Injection Prevention)
_VALID_SQL_IDENTIFIER = re.compile(r'^[a-zA-Z_][a-zA-Z0-9_]*$')
_VALID_SQL_TYPE = re.compile(r'^[A-Z]+(\s+[A-Z]+)*(\s+DEFAULT\s+\S+)?$', re.IGNORECASE)

SCHEMA_VERSION = 1

# Schema definitions
EXTRACTED_FEATURES_ADDITIONS = """
-- Quarantine fields
ALTER TABLE extracted_features ADD COLUMN IF NOT EXISTS quarantine_count INTEGER DEFAULT 0;
ALTER TABLE extracted_features ADD COLUMN IF NOT EXISTS quarantine_reason TEXT;
ALTER TABLE extracted_features ADD COLUMN IF NOT EXISTS quarantined_at TEXT;
ALTER TABLE extracted_features ADD COLUMN IF NOT EXISTS retry_after TEXT;
ALTER TABLE extracted_features ADD COLUMN IF NOT EXISTS last_failure_report TEXT;
ALTER TABLE extracted_features ADD COLUMN IF NOT EXISTS retry_strategy TEXT;
ALTER TABLE extracted_features ADD COLUMN IF NOT EXISTS integrated_at TEXT;
"""

INTEGRATION_BASELINES_TABLE = """
CREATE TABLE IF NOT EXISTS integration_baselines (
    id TEXT PRIMARY KEY,
    feature_id INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    file_backups TEXT,
    file_checksums TEXT,
    config_state TEXT,
    service_states TEXT,
    baseline_metrics TEXT,
    affected_files TEXT,
    affected_services TEXT,
    FOREIGN KEY (feature_id) REFERENCES extracted_features(id)
);

CREATE INDEX IF NOT EXISTS idx_baselines_feature ON integration_baselines(feature_id);
CREATE INDEX IF NOT EXISTS idx_baselines_created ON integration_baselines(created_at);
"""

INTEGRATION_FAILURES_TABLE = """
CREATE TABLE IF NOT EXISTS integration_failures (
    id TEXT PRIMARY KEY,
    feature_id INTEGER NOT NULL,
    feature_name TEXT,
    occurred_at TEXT NOT NULL,
    severity TEXT,
    anomalies TEXT,
    system_state TEXT,
    baseline_diff TEXT,
    probable_cause TEXT,
    root_cause_analysis TEXT,
    recommended_actions TEXT,
    rollback_result TEXT,
    modified_files TEXT,
    affected_services TEXT,
    FOREIGN KEY (feature_id) REFERENCES extracted_features(id)
);

CREATE INDEX IF NOT EXISTS idx_failures_feature ON integration_failures(feature_id);
CREATE INDEX IF NOT EXISTS idx_failures_occurred ON integration_failures(occurred_at);
CREATE INDEX IF NOT EXISTS idx_failures_severity ON integration_failures(severity);
"""

ASRS_METADATA_TABLE = """
CREATE TABLE IF NOT EXISTS asrs_metadata (
    key TEXT PRIMARY KEY,
    value TEXT,
    updated_at TEXT
);
"""


def ensure_schema(db_path: Path):
    """
    Ensure all A.S.R.S. schema elements exist.

    Args:
        db_path: Path to the database file
    """
    conn = sqlite3.connect(str(db_path), timeout=30)
    cursor = conn.cursor()

    try:
        # Check schema version
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS asrs_metadata (
                key TEXT PRIMARY KEY,
                value TEXT,
                updated_at TEXT
            )
        """)

        cursor.execute("SELECT value FROM asrs_metadata WHERE key = 'schema_version'")
        row = cursor.fetchone()
        current_version = int(row[0]) if row else 0

        if current_version >= SCHEMA_VERSION:
            LOG.debug(f"Schema already at version {current_version}")
            return

        LOG.info(f"Upgrading schema from version {current_version} to {SCHEMA_VERSION}")

        # Add columns to extracted_features if they don't exist
        _add_columns_if_missing(cursor, 'extracted_features', [
            ('quarantine_count', 'INTEGER DEFAULT 0'),
            ('quarantine_reason', 'TEXT'),
            ('quarantined_at', 'TEXT'),
            ('retry_after', 'TEXT'),
            ('last_failure_report', 'TEXT'),
            ('retry_strategy', 'TEXT'),
            ('integrated_at', 'TEXT'),
        ])

        # Create baselines table
        cursor.executescript(INTEGRATION_BASELINES_TABLE)

        # Create failures table
        cursor.executescript(INTEGRATION_FAILURES_TABLE)

        # Update schema version
        cursor.execute("""
            INSERT OR REPLACE INTO asrs_metadata (key, value, updated_at)
            VALUES ('schema_version', ?, datetime('now'))
        """, (str(SCHEMA_VERSION),))

        conn.commit()
        LOG.info(f"Schema upgraded to version {SCHEMA_VERSION}")

    except Exception as e:
        LOG.error(f"Schema upgrade failed: {e}")
        conn.rollback()
        raise

    finally:
        conn.close()


def _add_columns_if_missing(cursor, table: str, columns: list):
    """Add columns to a table if they don't already exist (with SQL injection protection)."""
    # Validate table name against SQL injection
    if not _VALID_SQL_IDENTIFIER.match(table):
        raise ValueError(f"Invalid table name: {table}")

    # Get existing columns
    cursor.execute(f"PRAGMA table_info({table})")
    existing = {row[1] for row in cursor.fetchall()}

    for col_name, col_type in columns:
        # Validate column name against SQL injection
        if not _VALID_SQL_IDENTIFIER.match(col_name):
            LOG.warning(f"Invalid column name rejected: {col_name}")
            continue
        # Validate column type (only known SQL types)
        if not _VALID_SQL_TYPE.match(col_type):
            LOG.warning(f"Invalid column type rejected: {col_type}")
            continue

        if col_name not in existing:
            try:
                cursor.execute(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_type}")
                LOG.debug(f"Added column {col_name} to {table}")
            except sqlite3.OperationalError as e:
                if "duplicate column" not in str(e).lower():
                    raise


def get_statistics(db_path: Path) -> dict:
    """Get A.S.R.S. statistics from database."""
    conn = sqlite3.connect(str(db_path), timeout=30)
    cursor = conn.cursor()

    stats = {}

    try:
        # Quarantine stats
        cursor.execute("""
            SELECT
                COUNT(CASE WHEN integration_status = 'quarantined' THEN 1 END) as quarantined,
                COUNT(CASE WHEN integration_status = 'rejected_auto' THEN 1 END) as rejected,
                COUNT(CASE WHEN integration_status = 'integrated' THEN 1 END) as integrated,
                AVG(CASE WHEN quarantine_count > 0 THEN quarantine_count END) as avg_quarantine
            FROM extracted_features
        """)
        row = cursor.fetchone()
        stats['quarantined'] = row[0] or 0
        stats['auto_rejected'] = row[1] or 0
        stats['integrated'] = row[2] or 0
        stats['avg_quarantine_count'] = round(row[3] or 0, 2)

        # Baseline count
        cursor.execute("SELECT COUNT(*) FROM integration_baselines")
        stats['baselines'] = cursor.fetchone()[0]

        # Failure count
        cursor.execute("SELECT COUNT(*) FROM integration_failures")
        stats['failures'] = cursor.fetchone()[0]

        # Recent failures by severity
        cursor.execute("""
            SELECT severity, COUNT(*)
            FROM integration_failures
            WHERE occurred_at > datetime('now', '-7 days')
            GROUP BY severity
        """)
        stats['recent_failures_by_severity'] = dict(cursor.fetchall())

    except sqlite3.OperationalError:
        # Tables might not exist yet
        pass

    finally:
        conn.close()

    return stats


def cleanup_old_records(db_path: Path, days: int = 30):
    """Remove old baselines and failure records."""
    conn = sqlite3.connect(str(db_path), timeout=30)

    try:
        # Remove old baselines
        conn.execute("""
            DELETE FROM integration_baselines
            WHERE created_at < datetime('now', ? || ' days')
        """, (f'-{days}',))

        # Remove old failures (keep longer)
        conn.execute("""
            DELETE FROM integration_failures
            WHERE occurred_at < datetime('now', ? || ' days')
        """, (f'-{days * 3}',))  # Keep failures 3x longer

        conn.commit()
        LOG.info(f"Cleaned up records older than {days} days")

    finally:
        conn.close()


if __name__ == "__main__":
    # Run schema migration
    import sys
    logging.basicConfig(level=logging.INFO)

    if len(sys.argv) > 1:
        db_path = Path(sys.argv[1])
    else:
        try:
            from config.paths import get_db
            db_path = get_db("fas_scavenger")
        except ImportError:
            db_path = Path("/home/ai-core-node/aicore/database/fas_scavenger.db")

    print(f"Ensuring schema for {db_path}")
    ensure_schema(db_path)
    print("Done!")

    stats = get_statistics(db_path)
    print(f"Statistics: {stats}")
