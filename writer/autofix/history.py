"""
Fix History
Track autofix attempt history and learn from past fixes
"""

import sqlite3
import logging
import json
import threading
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple
from contextlib import contextmanager
from enum import Enum

from .error_analyzer import ErrorInfo, ErrorCategory

logger = logging.getLogger(__name__)


class FixOutcome(Enum):
    """Outcome of a fix attempt"""
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILURE = "failure"
    SKIPPED = "skipped"


@dataclass
class FixAttempt:
    """A single fix attempt within a session"""
    attempt_id: Optional[int] = None
    session_id: Optional[int] = None
    attempt_num: int = 1
    error_type: str = ""
    error_category: str = ""
    error_message: str = ""
    error_line: Optional[int] = None
    fix_strategy: str = ""
    fix_description: str = ""
    code_before_hash: str = ""
    code_after_hash: str = ""
    outcome: FixOutcome = FixOutcome.FAILURE
    confidence: float = 0.0
    execution_time_ms: float = 0.0
    timestamp: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            "attempt_id": self.attempt_id,
            "session_id": self.session_id,
            "attempt_num": self.attempt_num,
            "error_type": self.error_type,
            "error_category": self.error_category,
            "error_message": self.error_message,
            "error_line": self.error_line,
            "fix_strategy": self.fix_strategy,
            "fix_description": self.fix_description,
            "code_before_hash": self.code_before_hash,
            "code_after_hash": self.code_after_hash,
            "outcome": self.outcome.value,
            "confidence": self.confidence,
            "execution_time_ms": self.execution_time_ms,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class FixSession:
    """A fix session for a document"""
    session_id: Optional[int] = None
    document_id: str = ""
    language: str = ""
    initial_code_hash: str = ""
    final_code_hash: str = ""
    total_attempts: int = 0
    successful_fixes: int = 0
    success: bool = False
    started_at: datetime = field(default_factory=datetime.now)
    ended_at: Optional[datetime] = None
    attempts: List[FixAttempt] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            "session_id": self.session_id,
            "document_id": self.document_id,
            "language": self.language,
            "initial_code_hash": self.initial_code_hash,
            "final_code_hash": self.final_code_hash,
            "total_attempts": self.total_attempts,
            "successful_fixes": self.successful_fixes,
            "success": self.success,
            "started_at": self.started_at.isoformat(),
            "ended_at": self.ended_at.isoformat() if self.ended_at else None,
            "attempts": [a.to_dict() for a in self.attempts],
            "metadata": self.metadata,
        }

    @property
    def duration_ms(self) -> float:
        """Get session duration in milliseconds"""
        if self.ended_at:
            delta = self.ended_at - self.started_at
            return delta.total_seconds() * 1000
        return 0.0


@dataclass
class ErrorStatistics:
    """Statistics about error types"""
    error_type: str
    error_category: str
    total_occurrences: int
    successful_fixes: int
    failed_fixes: int
    avg_attempts_to_fix: float
    most_effective_strategy: str
    fix_rate: float

    @property
    def success_rate(self) -> float:
        """Calculate success rate"""
        total = self.successful_fixes + self.failed_fixes
        return self.successful_fixes / total if total > 0 else 0.0


@dataclass
class SessionStatistics:
    """Statistics about fix sessions"""
    total_sessions: int
    successful_sessions: int
    total_attempts: int
    avg_attempts_per_session: float
    avg_session_duration_ms: float
    most_common_errors: List[Tuple[str, int]]
    most_successful_strategies: List[Tuple[str, float]]

    @property
    def success_rate(self) -> float:
        """Calculate session success rate"""
        return self.successful_sessions / self.total_sessions if self.total_sessions > 0 else 0.0


class FixHistory:
    """Track and manage fix attempt history"""

    # Database schema version for migrations
    SCHEMA_VERSION = 1

    def __init__(self, db_path: Optional[Path] = None):
        """
        Initialize fix history.

        Args:
            db_path: Path to SQLite database. Defaults to writer data directory.
        """
        if db_path is None:
            try:
                from config.paths import AICORE_ROOT
                db_path = AICORE_ROOT / "writer" / "data" / "writer.db"
            except ImportError:
                db_path = Path(__file__).resolve().parents[2] / "writer" / "data" / "writer.db"

        self.db_path = db_path
        self._local = threading.local()
        self._init_database()

        # Cache for frequently accessed data
        self._strategy_success_cache: Dict[str, float] = {}
        self._cache_timestamp: Optional[datetime] = None
        self._cache_ttl_seconds = 300  # 5 minutes

    @property
    def _conn(self) -> sqlite3.Connection:
        """Get thread-local database connection"""
        if not hasattr(self._local, 'conn') or self._local.conn is None:
            self._local.conn = sqlite3.connect(
                str(self.db_path),
                detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES
            )
            self._local.conn.row_factory = sqlite3.Row
        return self._local.conn

    @contextmanager
    def _transaction(self):
        """Context manager for database transactions"""
        try:
            yield self._conn
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    def _init_database(self):
        """Initialize database schema"""
        # Ensure directory exists
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        with self._transaction() as conn:
            cursor = conn.cursor()

            # Create schema version table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS schema_version (
                    version INTEGER PRIMARY KEY
                )
            """)

            # Check current version
            cursor.execute("SELECT version FROM schema_version LIMIT 1")
            row = cursor.fetchone()
            current_version = row[0] if row else 0

            if current_version < self.SCHEMA_VERSION:
                self._migrate_schema(cursor, current_version)
                cursor.execute("DELETE FROM schema_version")
                cursor.execute("INSERT INTO schema_version (version) VALUES (?)",
                             (self.SCHEMA_VERSION,))

    def _migrate_schema(self, cursor: sqlite3.Cursor, from_version: int):
        """Migrate database schema to current version"""
        if from_version < 1:
            # Create fix_sessions table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS fix_sessions (
                    session_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    document_id TEXT NOT NULL,
                    language TEXT NOT NULL,
                    initial_code_hash TEXT,
                    final_code_hash TEXT,
                    total_attempts INTEGER DEFAULT 0,
                    successful_fixes INTEGER DEFAULT 0,
                    success INTEGER DEFAULT 0,
                    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    ended_at TIMESTAMP,
                    metadata TEXT
                )
            """)

            # Create fix_attempts table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS fix_attempts (
                    attempt_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id INTEGER NOT NULL,
                    attempt_num INTEGER NOT NULL,
                    error_type TEXT NOT NULL,
                    error_category TEXT,
                    error_message TEXT,
                    error_line INTEGER,
                    fix_strategy TEXT,
                    fix_description TEXT,
                    code_before_hash TEXT,
                    code_after_hash TEXT,
                    outcome TEXT DEFAULT 'failure',
                    confidence REAL DEFAULT 0.0,
                    execution_time_ms REAL DEFAULT 0.0,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (session_id) REFERENCES fix_sessions(session_id)
                        ON DELETE CASCADE
                )
            """)

            # Create indexes for common queries
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_sessions_document
                ON fix_sessions(document_id)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_sessions_language
                ON fix_sessions(language)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_attempts_session
                ON fix_attempts(session_id)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_attempts_error_type
                ON fix_attempts(error_type)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_attempts_strategy
                ON fix_attempts(fix_strategy)
            """)

    def start_session(
        self,
        document_id: str,
        language: str = "",
        initial_code_hash: str = "",
        metadata: Dict[str, Any] = None
    ) -> FixSession:
        """
        Start a new fix session.

        Args:
            document_id: Unique identifier for the document
            language: Programming language
            initial_code_hash: Hash of the initial code
            metadata: Additional session metadata

        Returns:
            New FixSession object
        """
        session = FixSession(
            document_id=document_id,
            language=language,
            initial_code_hash=initial_code_hash,
            metadata=metadata or {},
            started_at=datetime.now()
        )

        with self._transaction() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO fix_sessions
                (document_id, language, initial_code_hash, started_at, metadata)
                VALUES (?, ?, ?, ?, ?)
            """, (
                session.document_id,
                session.language,
                session.initial_code_hash,
                session.started_at,
                json.dumps(session.metadata)
            ))
            session.session_id = cursor.lastrowid

        logger.debug(f"Started fix session {session.session_id} for document {document_id}")
        return session

    def record_attempt(
        self,
        session: FixSession,
        error_info: ErrorInfo,
        fix_strategy: str = "",
        fix_description: str = "",
        code_before_hash: str = "",
        code_after_hash: str = "",
        outcome: FixOutcome = FixOutcome.FAILURE,
        confidence: float = 0.0,
        execution_time_ms: float = 0.0
    ) -> FixAttempt:
        """
        Record a fix attempt within a session.

        Args:
            session: The active fix session
            error_info: Parsed error information
            fix_strategy: Name of the fix strategy used
            fix_description: Description of the fix applied
            code_before_hash: Hash of code before fix
            code_after_hash: Hash of code after fix
            outcome: Outcome of the fix attempt
            confidence: Confidence level of the fix
            execution_time_ms: Time taken to apply fix

        Returns:
            New FixAttempt object
        """
        attempt = FixAttempt(
            session_id=session.session_id,
            attempt_num=session.total_attempts + 1,
            error_type=error_info.error_type,
            error_category=error_info.category.value,
            error_message=error_info.message[:1000],  # Truncate long messages
            error_line=error_info.line_number,
            fix_strategy=fix_strategy,
            fix_description=fix_description,
            code_before_hash=code_before_hash,
            code_after_hash=code_after_hash,
            outcome=outcome,
            confidence=confidence,
            execution_time_ms=execution_time_ms,
            timestamp=datetime.now()
        )

        with self._transaction() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO fix_attempts
                (session_id, attempt_num, error_type, error_category, error_message,
                 error_line, fix_strategy, fix_description, code_before_hash,
                 code_after_hash, outcome, confidence, execution_time_ms, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                attempt.session_id,
                attempt.attempt_num,
                attempt.error_type,
                attempt.error_category,
                attempt.error_message,
                attempt.error_line,
                attempt.fix_strategy,
                attempt.fix_description,
                attempt.code_before_hash,
                attempt.code_after_hash,
                attempt.outcome.value,
                attempt.confidence,
                attempt.execution_time_ms,
                attempt.timestamp
            ))
            attempt.attempt_id = cursor.lastrowid

            # Update session counters
            cursor.execute("""
                UPDATE fix_sessions
                SET total_attempts = total_attempts + 1,
                    successful_fixes = successful_fixes + ?
                WHERE session_id = ?
            """, (1 if outcome == FixOutcome.SUCCESS else 0, session.session_id))

        # Update local session object
        session.total_attempts += 1
        if outcome == FixOutcome.SUCCESS:
            session.successful_fixes += 1
        session.attempts.append(attempt)

        logger.debug(f"Recorded attempt {attempt.attempt_num} in session {session.session_id}")
        return attempt

    def end_session(
        self,
        session: FixSession,
        success: bool,
        final_code_hash: str = ""
    ) -> None:
        """
        End a fix session.

        Args:
            session: The session to end
            success: Whether the overall fix was successful
            final_code_hash: Hash of the final code
        """
        session.success = success
        session.final_code_hash = final_code_hash
        session.ended_at = datetime.now()

        with self._transaction() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE fix_sessions
                SET success = ?, final_code_hash = ?, ended_at = ?,
                    metadata = ?
                WHERE session_id = ?
            """, (
                1 if success else 0,
                final_code_hash,
                session.ended_at,
                json.dumps(session.metadata),
                session.session_id
            ))

        # Invalidate cache
        self._cache_timestamp = None

        logger.debug(f"Ended session {session.session_id} (success={success})")

    def get_session(self, session_id: int) -> Optional[FixSession]:
        """Get a session by ID"""
        cursor = self._conn.cursor()
        cursor.execute("""
            SELECT * FROM fix_sessions WHERE session_id = ?
        """, (session_id,))
        row = cursor.fetchone()

        if not row:
            return None

        session = self._row_to_session(row)

        # Load attempts
        cursor.execute("""
            SELECT * FROM fix_attempts WHERE session_id = ?
            ORDER BY attempt_num
        """, (session_id,))
        session.attempts = [self._row_to_attempt(r) for r in cursor.fetchall()]

        return session

    def get_sessions_for_document(
        self,
        document_id: str,
        limit: int = 10
    ) -> List[FixSession]:
        """Get recent sessions for a document"""
        cursor = self._conn.cursor()
        cursor.execute("""
            SELECT * FROM fix_sessions
            WHERE document_id = ?
            ORDER BY started_at DESC
            LIMIT ?
        """, (document_id, limit))

        return [self._row_to_session(row) for row in cursor.fetchall()]

    def get_session_stats(self) -> SessionStatistics:
        """Get overall session statistics"""
        cursor = self._conn.cursor()

        # Basic stats
        cursor.execute("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) as successful,
                SUM(total_attempts) as attempts,
                AVG(total_attempts) as avg_attempts,
                AVG(
                    (julianday(ended_at) - julianday(started_at)) * 86400000
                ) as avg_duration_ms
            FROM fix_sessions
            WHERE ended_at IS NOT NULL
        """)
        row = cursor.fetchone()

        # Most common errors
        cursor.execute("""
            SELECT error_type, COUNT(*) as count
            FROM fix_attempts
            GROUP BY error_type
            ORDER BY count DESC
            LIMIT 10
        """)
        common_errors = [(r['error_type'], r['count']) for r in cursor.fetchall()]

        # Most successful strategies
        cursor.execute("""
            SELECT
                fix_strategy,
                AVG(CASE WHEN outcome = 'success' THEN 1.0 ELSE 0.0 END) as success_rate
            FROM fix_attempts
            WHERE fix_strategy != ''
            GROUP BY fix_strategy
            HAVING COUNT(*) >= 5
            ORDER BY success_rate DESC
            LIMIT 10
        """)
        successful_strategies = [(r['fix_strategy'], r['success_rate'])
                                for r in cursor.fetchall()]

        return SessionStatistics(
            total_sessions=row['total'] or 0,
            successful_sessions=row['successful'] or 0,
            total_attempts=row['attempts'] or 0,
            avg_attempts_per_session=row['avg_attempts'] or 0.0,
            avg_session_duration_ms=row['avg_duration_ms'] or 0.0,
            most_common_errors=common_errors,
            most_successful_strategies=successful_strategies
        )

    def get_common_errors(
        self,
        language: Optional[str] = None,
        limit: int = 20
    ) -> List[ErrorStatistics]:
        """
        Get statistics about common errors.

        Args:
            language: Filter by language (optional)
            limit: Maximum number of error types to return

        Returns:
            List of ErrorStatistics
        """
        cursor = self._conn.cursor()

        query = """
            SELECT
                a.error_type,
                a.error_category,
                COUNT(*) as total,
                SUM(CASE WHEN a.outcome = 'success' THEN 1 ELSE 0 END) as successes,
                SUM(CASE WHEN a.outcome = 'failure' THEN 1 ELSE 0 END) as failures,
                AVG(a.attempt_num) as avg_attempts
            FROM fix_attempts a
            JOIN fix_sessions s ON a.session_id = s.session_id
        """
        params = []

        if language:
            query += " WHERE s.language = ?"
            params.append(language)

        query += """
            GROUP BY a.error_type, a.error_category
            ORDER BY total DESC
            LIMIT ?
        """
        params.append(limit)

        cursor.execute(query, params)

        results = []
        for row in cursor.fetchall():
            # Get most effective strategy for this error type
            cursor.execute("""
                SELECT fix_strategy,
                       AVG(CASE WHEN outcome = 'success' THEN 1.0 ELSE 0.0 END) as rate
                FROM fix_attempts
                WHERE error_type = ? AND fix_strategy != ''
                GROUP BY fix_strategy
                ORDER BY rate DESC
                LIMIT 1
            """, (row['error_type'],))
            strategy_row = cursor.fetchone()
            best_strategy = strategy_row['fix_strategy'] if strategy_row else ""

            total = row['successes'] + row['failures']
            results.append(ErrorStatistics(
                error_type=row['error_type'],
                error_category=row['error_category'],
                total_occurrences=row['total'],
                successful_fixes=row['successes'],
                failed_fixes=row['failures'],
                avg_attempts_to_fix=row['avg_attempts'] or 0.0,
                most_effective_strategy=best_strategy,
                fix_rate=row['successes'] / total if total > 0 else 0.0
            ))

        return results

    def get_strategy_success_rate(
        self,
        strategy: str,
        error_type: Optional[str] = None
    ) -> float:
        """
        Get success rate for a specific strategy.

        Args:
            strategy: Name of the fix strategy
            error_type: Filter by error type (optional)

        Returns:
            Success rate between 0.0 and 1.0
        """
        # Check cache
        cache_key = f"{strategy}:{error_type or '*'}"
        if self._is_cache_valid() and cache_key in self._strategy_success_cache:
            return self._strategy_success_cache[cache_key]

        cursor = self._conn.cursor()

        query = """
            SELECT
                AVG(CASE WHEN outcome = 'success' THEN 1.0 ELSE 0.0 END) as rate
            FROM fix_attempts
            WHERE fix_strategy = ?
        """
        params = [strategy]

        if error_type:
            query += " AND error_type = ?"
            params.append(error_type)

        cursor.execute(query, params)
        row = cursor.fetchone()

        rate = row['rate'] if row and row['rate'] is not None else 0.0

        # Update cache
        self._strategy_success_cache[cache_key] = rate
        if self._cache_timestamp is None:
            self._cache_timestamp = datetime.now()

        return rate

    def get_suggested_fix_order(
        self,
        error_info: ErrorInfo,
        available_strategies: List[str]
    ) -> List[Tuple[str, float]]:
        """
        Get suggested order of fix strategies based on historical success.

        Args:
            error_info: The error to fix
            available_strategies: List of available strategy names

        Returns:
            List of (strategy_name, expected_success_rate) sorted by rate descending
        """
        if not available_strategies:
            return []

        results = []
        for strategy in available_strategies:
            # Get success rate for this specific error type
            rate = self.get_strategy_success_rate(strategy, error_info.error_type)

            # If no data for specific error type, use overall rate
            if rate == 0.0:
                rate = self.get_strategy_success_rate(strategy)

            results.append((strategy, rate))

        # Sort by success rate descending
        results.sort(key=lambda x: x[1], reverse=True)
        return results

    def cleanup_old_sessions(self, days: int = 30) -> int:
        """
        Clean up old sessions from the database.

        Args:
            days: Delete sessions older than this many days

        Returns:
            Number of sessions deleted
        """
        with self._transaction() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                DELETE FROM fix_sessions
                WHERE ended_at < datetime('now', ?)
            """, (f'-{days} days',))
            deleted = cursor.rowcount

        logger.info(f"Cleaned up {deleted} old fix sessions")
        return deleted

    def _is_cache_valid(self) -> bool:
        """Check if the cache is still valid"""
        if self._cache_timestamp is None:
            return False
        age = (datetime.now() - self._cache_timestamp).total_seconds()
        return age < self._cache_ttl_seconds

    def _row_to_session(self, row: sqlite3.Row) -> FixSession:
        """Convert a database row to FixSession"""
        metadata = {}
        if row['metadata']:
            try:
                metadata = json.loads(row['metadata'])
            except json.JSONDecodeError:
                pass

        return FixSession(
            session_id=row['session_id'],
            document_id=row['document_id'],
            language=row['language'],
            initial_code_hash=row['initial_code_hash'] or "",
            final_code_hash=row['final_code_hash'] or "",
            total_attempts=row['total_attempts'],
            successful_fixes=row['successful_fixes'],
            success=bool(row['success']),
            started_at=row['started_at'] if isinstance(row['started_at'], datetime)
                       else datetime.fromisoformat(row['started_at']),
            ended_at=row['ended_at'] if isinstance(row['ended_at'], datetime)
                     else (datetime.fromisoformat(row['ended_at']) if row['ended_at'] else None),
            metadata=metadata
        )

    def _row_to_attempt(self, row: sqlite3.Row) -> FixAttempt:
        """Convert a database row to FixAttempt"""
        return FixAttempt(
            attempt_id=row['attempt_id'],
            session_id=row['session_id'],
            attempt_num=row['attempt_num'],
            error_type=row['error_type'],
            error_category=row['error_category'] or "",
            error_message=row['error_message'] or "",
            error_line=row['error_line'],
            fix_strategy=row['fix_strategy'] or "",
            fix_description=row['fix_description'] or "",
            code_before_hash=row['code_before_hash'] or "",
            code_after_hash=row['code_after_hash'] or "",
            outcome=FixOutcome(row['outcome']) if row['outcome'] else FixOutcome.FAILURE,
            confidence=row['confidence'] or 0.0,
            execution_time_ms=row['execution_time_ms'] or 0.0,
            timestamp=row['timestamp'] if isinstance(row['timestamp'], datetime)
                      else datetime.fromisoformat(row['timestamp'])
        )

    def close(self):
        """Close database connection"""
        if hasattr(self._local, 'conn') and self._local.conn:
            self._local.conn.close()
            self._local.conn = None
