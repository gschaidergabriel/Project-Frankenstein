import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    from config.paths import JOURNAL_DIR, get_db, DB_DIR
    DB_PATH = get_db("aicore")
    STATE_FILE = DB_DIR / "materializer.state"
except ImportError:
    JOURNAL_DIR = Path.home() / ".local" / "share" / "frank" / "journal"
    DB_PATH = Path.home() / ".local" / "share" / "frank" / "db" / "aicore.sqlite"
    STATE_FILE = Path.home() / ".local" / "share" / "frank" / "db" / "materializer.state"

def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {"last_file": "", "last_line": 0}

def save_state(st):
    STATE_FILE.write_text(json.dumps(st), encoding="utf-8")

def iter_lines(files, state):
    last_file = state["last_file"]
    last_line = state["last_line"]
    for f in files:
        start = 0
        if f.name == last_file:
            start = last_line
        with f.open("r", encoding="utf-8") as fh:
            for i, line in enumerate(fh):
                if i < start:
                    continue
                yield f.name, i + 1, line

def main():
    JOURNAL_DIR.mkdir(parents=True, exist_ok=True)
    files = sorted(JOURNAL_DIR.glob("*.jsonl"))
    if not files:
        print("No journal files found.")
        return

    state = load_state()
    inserted = 0

    with sqlite3.connect(DB_PATH) as con:
        con.execute("PRAGMA journal_mode=WAL;")
        for fname, lineno, line in iter_lines(files, state):
            line = line.strip()
            if not line:
                continue
            ev = json.loads(line)
            con.execute(
                "INSERT INTO events(ts, type, source, payload) VALUES(?,?,?,?)",
                (ev.get("ts",""), ev.get("type",""), ev.get("source",""), json.dumps(ev.get("payload",{}), ensure_ascii=False)),
            )
            inserted += 1
            state["last_file"] = fname
            state["last_line"] = lineno

    save_state(state)
    print(f"OK: inserted {inserted} events")

if __name__ == "__main__":
    main()
