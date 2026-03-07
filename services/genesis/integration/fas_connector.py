#!/usr/bin/env python3
"""
F.A.S. Popup Connector - Connects Genesis to the user interface.

NEW FLOW (Mar 2026):
  Genesis Crystal → consciousness.db genesis_proposals → Frank reviews during idle
  → Frank-approved proposals accumulate in _pending_proposals → FAS popup at threshold

Frank is the gatekeeper. Only proposals he approves reach the user.
"""

from typing import Dict, Optional, List
from pathlib import Path
from datetime import datetime
import json
import sqlite3
import subprocess
import os
import logging
import time

from ..core.manifestation import Crystal

LOG = logging.getLogger("genesis.fas_connector")

# System Python (not venv) — GTK4/gi only available there
SYSTEM_PYTHON = "/usr/bin/python3"
try:
    from config.paths import TEMP_FILES as _fas_temp_files
    RESULT_FILE = _fas_temp_files["genesis_popup_result"]
    PENDING_FILE = _fas_temp_files["genesis_pending_proposals"]
except ImportError:
    RESULT_FILE = Path("/tmp/frank/genesis_popup_result.json")
    PENDING_FILE = Path("/tmp/frank/genesis_pending_proposals.json")

try:
    from config.paths import UI_DIR as _FAS_UI_DIR, AICORE_LOG as _FAS_LOG_DIR
    _FAS_POPUP_SCRIPT = _FAS_UI_DIR / "fas_popup" / "main_window.py"
    _FAS_POPUP_LOG = _FAS_LOG_DIR / "genesis" / "fas_popup.log"
except ImportError:
    _FAS_POPUP_SCRIPT = Path(__file__).resolve().parents[3] / "ui" / "fas_popup" / "main_window.py"
    _FAS_POPUP_LOG = Path.home() / ".local" / "share" / "frank" / "logs" / "genesis" / "fas_popup.log"

# Minimum Frank-approved proposals before showing popup
MIN_PROPOSALS_FOR_POPUP = 7

# consciousness.db path (lazy-init)
_CONSCIOUSNESS_DB: Optional[Path] = None


def _get_consciousness_db() -> Path:
    """Get consciousness.db path."""
    global _CONSCIOUSNESS_DB
    if _CONSCIOUSNESS_DB is None:
        try:
            from config.paths import DB_FILES
            _CONSCIOUSNESS_DB = DB_FILES["consciousness"]
        except (ImportError, KeyError):
            _CONSCIOUSNESS_DB = (
                Path.home() / ".local" / "share" / "frank" / "db" / "consciousness.db"
            )
    return _CONSCIOUSNESS_DB


class FASConnector:
    """
    Connects Genesis manifestations to Frank's review queue and the F.A.S. Popup.

    Flow:
      1. manifest_crystal() → writes to consciousness.db genesis_proposals
      2. Frank reviews during idle time (consciousness daemon)
      3. Frank-approved proposals arrive via submit_frank_approved()
      4. FAS popup launches when enough Frank-approved proposals accumulate
    """

    def __init__(self):
        self.popup_script = _FAS_POPUP_SCRIPT
        try:
            from config.paths import TEMP_FILES as _fas_temp_files2
            self.notification_file = _fas_temp_files2["genesis_notification"]
        except ImportError:
            self.notification_file = Path("/tmp/frank/genesis_notification.json")
        self.popup_process = None
        self._pending_proposals: List[Dict] = []
        self._load_pending()

    # ── Persistence (Frank-approved proposals waiting for FAS) ────

    def _load_pending(self):
        """Load pending proposals from disk (survives restarts)."""
        try:
            if PENDING_FILE.exists():
                self._pending_proposals = json.loads(PENDING_FILE.read_text())
                LOG.info(f"Loaded {len(self._pending_proposals)} pending proposals")
        except Exception as e:
            LOG.warning(f"Failed to load pending proposals: {e}")
            self._pending_proposals = []

    def _save_pending(self):
        """Save pending proposals to disk."""
        try:
            PENDING_FILE.write_text(json.dumps(self._pending_proposals, indent=2))
        except Exception as e:
            LOG.warning(f"Failed to save pending proposals: {e}")

    # ── Genesis → Frank's Review Queue ────────────────────────────

    def manifest_crystal(self, crystal: Crystal) -> bool:
        """Queue a crystal for Frank's review in consciousness.db.

        This is the new entry point. Proposals no longer go directly to FAS.
        Frank reviews them during idle time and decides what reaches the user.
        """
        return self.queue_for_frank_review(crystal)

    def queue_for_frank_review(self, crystal: Crystal) -> bool:
        """Write crystal to genesis_proposals table for Frank's idle review."""
        try:
            proposal = crystal.to_proposal_dict()
            target = getattr(crystal.organism.genome, "target", "")

            # Reject category-string targets (not real file paths)
            if target and "/" not in target and not target.endswith(".py"):
                LOG.debug("Rejected non-file target for review: %s", target)
                return False

            db_path = _get_consciousness_db()
            conn = sqlite3.connect(str(db_path), timeout=10.0)
            conn.execute("PRAGMA busy_timeout = 10000")
            try:
                # Dedup: skip if a proposal with the same file_path+approach
                # already exists and hasn't been rejected
                existing = conn.execute(
                    "SELECT id FROM genesis_proposals "
                    "WHERE file_path = ? AND approach = ? "
                    "AND status != 'reject' LIMIT 1",
                    (target, crystal.approach or ""),
                ).fetchone()
                if existing:
                    LOG.debug("Dedup: proposal for %s/%s already exists (id=%s)",
                              target, crystal.approach, existing[0])
                    conn.close()
                    return False

                conn.execute(
                    "INSERT OR IGNORE INTO genesis_proposals "
                    "(crystal_id, title, description, approach, risk_assessment, "
                    "expected_benefit, resonance, feature_type, file_path, "
                    "code_snippet, proposal_json, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        crystal.id,
                        crystal.title or "Genesis Proposal",
                        crystal.description or "",
                        crystal.approach or "",
                        crystal.risk_assessment or "",
                        crystal.expected_benefit or "",
                        crystal.resonance,
                        getattr(crystal.organism.genome, "idea_type", "optimization"),
                        target,
                        proposal.get("code_snippet", ""),
                        json.dumps(proposal),
                        time.time(),
                    ),
                )
                conn.commit()
                LOG.info("Crystal %s queued for Frank review (resonance=%.2f)",
                         crystal.id, crystal.resonance)
                return True
            finally:
                conn.close()
        except Exception as e:
            LOG.error("Failed to queue crystal for Frank: %s", e)
            return False

    # ── Frank-approved → FAS Queue ────────────────────────────────

    def submit_frank_approved(self, proposal_dict: Dict,
                              source: str = "frank_approved") -> bool:
        """Add a Frank-approved proposal to the FAS pending queue.

        This is the ONLY path proposals reach the FAS popup now.
        Called by consciousness daemon after Frank's idle review.
        """
        proposal_dict["source"] = source
        proposal_dict["manifest_time"] = datetime.now().isoformat()

        # Dedup
        existing_ids = {p.get("id") for p in self._pending_proposals}
        if proposal_dict.get("id") in existing_ids:
            LOG.debug("Proposal %s already in FAS queue", proposal_dict.get("id"))
            return True

        self._pending_proposals.append(proposal_dict)
        self._save_pending()
        self._write_notification(proposal_dict)

        pending_count = len(self._pending_proposals)
        LOG.info("Frank-approved proposal queued for FAS (%d/%d)",
                 pending_count, MIN_PROPOSALS_FOR_POPUP)

        if pending_count >= MIN_PROPOSALS_FOR_POPUP:
            if not self.is_popup_active():
                LOG.info("FAS threshold reached (%d proposals), launching popup",
                         pending_count)
                return self._launch_popup(self._pending_proposals)

        return True

    # ── User Decision Feedback ────────────────────────────────────

    def notify_user_decision(self, crystal_ids: list, decision: str):
        """Update genesis_proposals table with user's FAS decision.

        Called after FAS popup closes. Updates fas_status so consciousness
        daemon can give mood rewards for accepted proposals.
        """
        fas_status = "user_approved" if decision == "approve" else "user_rejected"
        try:
            db_path = _get_consciousness_db()
            conn = sqlite3.connect(str(db_path), timeout=10.0)
            conn.execute("PRAGMA busy_timeout = 10000")
            now = time.time()
            for cid in crystal_ids:
                conn.execute(
                    "UPDATE genesis_proposals SET fas_status = ?, fas_decided_at = ? "
                    "WHERE crystal_id = ?",
                    (fas_status, now, cid),
                )
            conn.commit()
            conn.close()
            LOG.info("Updated %d proposals → fas_status=%s", len(crystal_ids), fas_status)
        except Exception as e:
            LOG.warning("Failed to notify user decision: %s", e)

    # ── Existing popup methods (unchanged) ────────────────────────

    def get_pending_count(self) -> int:
        """Return how many proposals are pending."""
        return len(self._pending_proposals)

    def _write_notification(self, proposal: Dict):
        """Write notification for the popup daemon."""
        try:
            notification = {
                "type": "genesis_proposal",
                "timestamp": datetime.now().isoformat(),
                "proposal": proposal,
            }
            self.notification_file.write_text(json.dumps(notification, indent=2))
        except Exception as e:
            LOG.warning(f"Failed to write notification: {e}")

    def _is_popup_daemon_running(self) -> bool:
        """Check if the F.A.S. popup daemon is running."""
        try:
            result = subprocess.run(
                ["systemctl", "--user", "is-active", "aicore-fas-popup"],
                capture_output=True,
                text=True,
                timeout=5
            )
            return result.stdout.strip() == "active"
        except Exception:
            return False

    def _launch_popup(self, proposals: List[Dict]) -> bool:
        """Launch the F.A.S. popup directly."""
        if not self.popup_script.exists():
            LOG.error(f"Popup script not found: {self.popup_script}")
            return False

        try:
            features = []
            for p in proposals:
                features.append({
                    "id": p.get("id"),
                    "name": p.get("title", "Genesis Proposal"),
                    "description": p.get("description", ""),
                    "confidence": p.get("resonance", 0.7),
                    "feature_type": p.get("feature_type", p.get("genome", {}).get("type", "optimization")),
                    "file_path": p.get("file_path", p.get("genome", {}).get("target", "")),
                    "repo_name": p.get("repo_name", p.get("genome", {}).get("origin", "genesis")),
                    "confidence_score": p.get("confidence_score", p.get("fitness", 0.5)),
                    "code_snippet": p.get("code_snippet", ""),
                    "why_specific": p.get("why_specific", ""),
                    "source": p.get("source", "genesis"),
                    "approach": p.get("approach", ""),
                    "risk_assessment": p.get("risk_assessment", ""),
                    "expected_benefit": p.get("expected_benefit", ""),
                    "genome": p.get("genome", {}),
                    "metadata": p.get("metadata", {}),
                })

            env = os.environ.copy()
            env["DISPLAY"] = os.environ.get("DISPLAY", ":0")
            env["PYTHONPATH"] = str(self.popup_script.parent.parent.parent)

            if RESULT_FILE.exists():
                RESULT_FILE.unlink()

            log_file = _FAS_POPUP_LOG
            log_file.parent.mkdir(parents=True, exist_ok=True)
            log_fh = open(log_file, "a")

            self.popup_process = subprocess.Popen(
                [
                    SYSTEM_PYTHON,
                    str(self.popup_script),
                    "--features", json.dumps(features),
                    "--force",
                ],
                env=env,
                stdout=log_fh,
                stderr=log_fh,
            )

            LOG.info(f"Popup launched with {len(features)} proposals (PID: {self.popup_process.pid})")
            return True

        except Exception as e:
            LOG.error(f"Failed to launch popup: {e}")
            return False

    def check_popup_result(self) -> Optional[Dict]:
        """Check if popup returned a result."""
        if RESULT_FILE.exists():
            try:
                result = json.loads(RESULT_FILE.read_text())
                RESULT_FILE.unlink()

                decision = result.get("decision", "defer")
                if decision in ("approve", "reject"):
                    self._pending_proposals.clear()
                    self._save_pending()
                    LOG.info(f"Cleared pending proposals after {decision}")
                elif decision == "defer":
                    LOG.info(f"User deferred, keeping {len(self._pending_proposals)} proposals")

                return result
            except Exception as e:
                LOG.warning(f"Failed to read popup result: {e}")

        return None

    def is_popup_active(self) -> bool:
        """Check if popup is currently showing."""
        if self.popup_process:
            return self.popup_process.poll() is None
        return False
