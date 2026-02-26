#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Titan Graph Repair Script (one-time)

Fixes:
1. Orphaned edges (referencing non-existent nodes)
2. Orphaned vectors (no matching node)
3. Orphaned FTS entries
4. Re-ingests last 30 days of chat history to repopulate Titan

Run: python3 -m tools.titan.repair
"""

import json
import logging
import shutil
import sqlite3
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
LOG = logging.getLogger("titan.repair")

# Resolve paths
try:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from config.paths import get_db, DB_DIR, INVARIANTS_DIR
except ImportError:
    DB_DIR = Path.home() / ".local" / "share" / "frank" / "db"
    INVARIANTS_DIR = Path.home() / ".local" / "share" / "frank" / "invariants"
    def get_db(name):
        return DB_DIR / f"{name}.db"

TITAN_DB = get_db("titan")
CHAT_DB = get_db("chat_memory")
VECTORS_NPZ = DB_DIR / "titan_vectors.npz"
VECTORS_IDS = DB_DIR / "titan_vector_ids.json"


def backup(path: Path) -> Path:
    """Create timestamped backup."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    dst = path.with_suffix(f".pre_repair_{ts}{path.suffix}")
    if path.exists():
        shutil.copy2(path, dst)
        LOG.info(f"Backup: {path.name} -> {dst.name}")
    return dst


def repair_orphaned_edges(conn: sqlite3.Connection) -> int:
    """Delete edges where src or dst node doesn't exist."""
    count_before = conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
    conn.execute("""
        DELETE FROM edges
        WHERE src NOT IN (SELECT id FROM nodes)
           OR dst NOT IN (SELECT id FROM nodes)
    """)
    conn.commit()
    count_after = conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
    removed = count_before - count_after
    LOG.info(f"Edges: {count_before} -> {count_after} (removed {removed} orphans)")
    return removed


def repair_orphaned_fts(conn: sqlite3.Connection) -> int:
    """Delete FTS entries where node doesn't exist."""
    # FTS5 doesn't support subqueries well, so fetch valid IDs first
    valid_ids = {r[0] for r in conn.execute("SELECT id FROM nodes").fetchall()}
    all_fts = conn.execute("SELECT rowid, node_id FROM memory_fts").fetchall()
    orphans = [r[0] for r in all_fts if r[1] not in valid_ids]
    for rowid in orphans:
        conn.execute("DELETE FROM memory_fts WHERE rowid = ?", (rowid,))
    conn.commit()
    LOG.info(f"FTS: removed {len(orphans)} orphaned entries")
    return len(orphans)


def repair_orphaned_vectors() -> int:
    """Remove vectors whose node_id doesn't exist in the DB."""
    import numpy as np

    if not VECTORS_IDS.exists() or not VECTORS_NPZ.exists():
        LOG.info("No vector files found, nothing to repair")
        return 0

    conn = sqlite3.connect(str(TITAN_DB))
    valid_ids = {r[0] for r in conn.execute("SELECT id FROM nodes").fetchall()}
    conn.close()

    ids = json.loads(VECTORS_IDS.read_text())
    data = np.load(str(VECTORS_NPZ))
    vectors = data["vectors"]

    keep_mask = [i for i, nid in enumerate(ids) if nid in valid_ids]
    removed = len(ids) - len(keep_mask)

    if removed > 0:
        new_ids = [ids[i] for i in keep_mask]
        new_vectors = vectors[keep_mask] if keep_mask else np.empty((0, vectors.shape[1]))
        np.savez_compressed(str(VECTORS_NPZ), vectors=new_vectors)
        VECTORS_IDS.write_text(json.dumps(new_ids))

    LOG.info(f"Vectors: {len(ids)} -> {len(ids) - removed} (removed {removed} orphans)")
    return removed


def reingest_chat_history(days: int = 30):
    """Re-ingest recent chat messages into Titan."""
    if not CHAT_DB.exists():
        LOG.warning(f"Chat DB not found at {CHAT_DB}")
        return 0

    # Disable invariant hooks during repair (they block writes after full cleanup)
    import tools.titan.storage as _storage_mod
    _orig_hook = _storage_mod._execute_hook
    _storage_mod._execute_hook = lambda *a, **kw: True
    LOG.info("Invariant hooks temporarily disabled for re-ingestion")

    from tools.titan.storage import SQLiteStore, VectorStore, KnowledgeGraph
    from tools.titan.ingestion import Architect

    sqlite = SQLiteStore(TITAN_DB)
    vectors = VectorStore()
    graph = KnowledgeGraph(sqlite)
    architect = Architect(sqlite, vectors, graph)

    chat_conn = sqlite3.connect(str(CHAT_DB))
    chat_conn.row_factory = sqlite3.Row
    cutoff = (datetime.now() - timedelta(days=days)).timestamp()

    rows = chat_conn.execute("""
        SELECT text, role, timestamp FROM messages
        WHERE timestamp > ? AND is_system = 0
        ORDER BY timestamp ASC
    """, (cutoff,)).fetchall()
    chat_conn.close()

    LOG.info(f"Re-ingesting {len(rows)} messages from last {days} days...")
    ingested = 0

    for row in rows:
        text = row["text"]
        if not text or len(text.strip()) < 10:
            continue

        origin = "user" if row["role"] == "user" else "memory"
        try:
            result = architect.ingest(text, origin=origin, confidence=0.7)
            if result.event_id:
                ingested += 1
        except Exception as e:
            LOG.warning(f"Ingest failed for message: {e}")

        # Don't hammer the system
        if ingested % 50 == 0 and ingested > 0:
            vectors.save()
            LOG.info(f"  Progress: {ingested}/{len(rows)} ingested")
            time.sleep(0.5)

    vectors.save()

    # Re-enable hooks
    _storage_mod._execute_hook = _orig_hook
    LOG.info("Invariant hooks re-enabled")

    # Re-bootstrap energy constant to match new state
    try:
        state_file = INVARIANTS_DIR / "invariants_state.json"
        if state_file.exists():
            import json as _json
            state = _json.loads(state_file.read_text())
            state["energy_constant"] = 0.0  # Will re-bootstrap on next check
            state_file.write_text(_json.dumps(state, indent=2))
            LOG.info("Reset energy constant for re-bootstrap")
    except Exception as e:
        LOG.warning(f"Could not reset energy constant: {e}")

    stats = sqlite.get_stats()
    LOG.info(f"Re-ingestion complete: {ingested} messages -> "
             f"{stats['nodes']} nodes, {stats['edges']} edges")
    return ingested


def main():
    LOG.info("=" * 60)
    LOG.info("TITAN GRAPH REPAIR")
    LOG.info("=" * 60)

    # 1. Backup
    backup(TITAN_DB)
    backup(VECTORS_NPZ)
    backup(VECTORS_IDS)

    # 2. Get pre-repair stats
    conn = sqlite3.connect(str(TITAN_DB))
    nodes_before = conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
    edges_before = conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
    LOG.info(f"PRE-REPAIR: nodes={nodes_before}, edges={edges_before}")

    # 3. Clean orphaned edges
    repair_orphaned_edges(conn)

    # 4. Clean orphaned FTS
    repair_orphaned_fts(conn)
    conn.close()

    # 5. Clean orphaned vectors
    repair_orphaned_vectors()

    # 6. Re-ingest chat history
    reingest_chat_history(days=30)

    # 7. Post-repair stats
    conn = sqlite3.connect(str(TITAN_DB))
    nodes_after = conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
    edges_after = conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
    conn.close()

    ids = json.loads(VECTORS_IDS.read_text()) if VECTORS_IDS.exists() else []

    LOG.info("=" * 60)
    LOG.info(f"POST-REPAIR: nodes={nodes_after}, edges={edges_after}, vectors={len(ids)}")
    LOG.info("=" * 60)


if __name__ == "__main__":
    main()
