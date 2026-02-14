import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

DB_PATH = Path.home() / "aicore/var/lib/aicore/db/aicore.sqlite"

def iso(dt): return dt.isoformat()

def main(minutes=30):
    now = datetime.now(timezone.utc)
    start = now - timedelta(minutes=minutes)

    with sqlite3.connect(DB_PATH) as con:
        rows = con.execute(
            "SELECT ts, type, source, payload FROM events WHERE ts >= ? ORDER BY ts ASC",
            (iso(start),)
        ).fetchall()

        if not rows:
            print("No events in window.")
            return

        lines = []
        for ts, typ, src, payload in rows:
            try:
                pl = json.loads(payload)
            except Exception:
                pl = {}
            text = pl.get("text") or pl.get("message") or ""
            if text:
                lines.append(f"- [{ts}] {typ} ({src}): {text}")
            else:
                lines.append(f"- [{ts}] {typ} ({src})")

        summary = "\n".join(lines[-50:])  # cap
        meta = {"window_minutes": minutes, "event_count": len(rows)}

        con.execute(
            "INSERT INTO episodes(ts_start, ts_end, summary, meta) VALUES(?,?,?,?)",
            (iso(start), iso(now), summary, json.dumps(meta))
        )
        con.commit()

    print(f"OK: wrote episode with {len(rows)} events")

if __name__ == "__main__":
    main()
