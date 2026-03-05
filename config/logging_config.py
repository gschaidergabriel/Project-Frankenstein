"""Centralized file logging for all Frank services.

Usage (one line in any service's __main__ block):

    from config.logging_config import setup_file_logging
    setup_file_logging("consciousness")  # creates ~/.local/share/frank/logs/consciousness.log

This adds a RotatingFileHandler alongside the existing stderr/journald output.
Logs rotate at 5MB, keeping 3 backups (max ~20MB per service).

All services share the same directory: ~/.local/share/frank/logs/
"""

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

# Default log directory
_LOG_DIR = Path.home() / ".local" / "share" / "frank" / "logs"

# 5 MB per file, 3 backups = ~20 MB max per service
_MAX_BYTES = 5 * 1024 * 1024
_BACKUP_COUNT = 3

_FORMAT = "[%(asctime)s] %(levelname)s %(name)s: %(message)s"


def setup_file_logging(
    service_name: str,
    level: int = logging.INFO,
    log_dir: Path | None = None,
) -> Path:
    """Add a rotating file handler to the root logger.

    Args:
        service_name: Name for the log file (e.g. "consciousness" → consciousness.log)
        level: Logging level (default: INFO)
        log_dir: Override log directory (default: ~/.local/share/frank/logs/)

    Returns:
        Path to the log file.
    """
    target_dir = log_dir or _LOG_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    log_path = target_dir / f"{service_name}.log"

    # Configure root logger with both stderr and file
    root = logging.getLogger()
    root.setLevel(level)

    # Stderr handler (for journald / terminal)
    has_stderr = any(
        isinstance(h, logging.StreamHandler) and h.stream in (sys.stdout, sys.stderr)
        for h in root.handlers
    )
    if not has_stderr:
        sh = logging.StreamHandler(sys.stdout)
        sh.setFormatter(logging.Formatter(_FORMAT))
        root.addHandler(sh)

    # Rotating file handler
    fh = RotatingFileHandler(
        str(log_path),
        maxBytes=_MAX_BYTES,
        backupCount=_BACKUP_COUNT,
        encoding="utf-8",
    )
    fh.setFormatter(logging.Formatter(_FORMAT))
    root.addHandler(fh)

    logging.getLogger(service_name).info(
        "File logging active: %s (max %dMB × %d backups)",
        log_path, _MAX_BYTES // (1024 * 1024), _BACKUP_COUNT,
    )
    return log_path
