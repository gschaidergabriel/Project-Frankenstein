import sqlite3
from pathlib import Path

DB_PATH = Path.home() / "aicore/var/lib/aicore/db/aicore.sqlite"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

schema = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL,
  type TEXT NOT NULL,
  source TEXT NOT NULL,
  payload TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts);
CREATE INDEX IF NOT EXISTS idx_events_type ON events(type);

CREATE TABLE IF NOT EXISTS episodes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts_start TEXT NOT NULL,
  ts_end TEXT NOT NULL,
  summary TEXT NOT NULL,
  meta TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_episodes_ts ON episodes(ts_start, ts_end);
"""

with sqlite3.connect(DB_PATH) as con:
    con.executescript(schema)

print(f"OK: initialized {DB_PATH}")
