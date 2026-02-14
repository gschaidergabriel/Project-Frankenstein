#!/usr/bin/env python3
"""
F.A.S. Popup Connector - Connects Genesis to the user interface.
Accumulates crystals and only launches the popup when enough proposals are ready.
"""

from typing import Dict, Optional, List
from pathlib import Path
from datetime import datetime
import json
import subprocess
import os
import logging

from ..core.manifestation import Crystal

LOG = logging.getLogger("genesis.fas_connector")

# System Python (not venv) — GTK4/gi only available there
SYSTEM_PYTHON = "/usr/bin/python3"
RESULT_FILE = Path("/tmp/genesis_popup_result.json")
PENDING_FILE = Path("/tmp/genesis_pending_proposals.json")

try:
    from config.paths import UI_DIR as _FAS_UI_DIR, AICORE_LOG as _FAS_LOG_DIR
    _FAS_POPUP_SCRIPT = _FAS_UI_DIR / "fas_popup" / "main_window.py"
    _FAS_POPUP_LOG = _FAS_LOG_DIR / "genesis" / "fas_popup.log"
except ImportError:
    _FAS_POPUP_SCRIPT = Path("/home/ai-core-node/aicore/opt/aicore/ui/fas_popup/main_window.py")
    _FAS_POPUP_LOG = Path("/home/ai-core-node/aicore/logs/genesis/fas_popup.log")

# Minimum proposals before showing popup
MIN_PROPOSALS_FOR_POPUP = 7


class FASConnector:
    """
    Connects Genesis manifestations to the F.A.S. Popup system.
    Accumulates proposals and only shows popup when threshold is reached.
    """

    def __init__(self):
        self.popup_script = _FAS_POPUP_SCRIPT
        self.notification_file = Path("/tmp/genesis_notification.json")
        self.popup_process = None
        self._pending_proposals: List[Dict] = []
        self._load_pending()

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

    def manifest_crystal(self, crystal: Crystal) -> bool:
        """
        Queue a crystal for the F.A.S. popup.
        Only launches popup when MIN_PROPOSALS_FOR_POPUP are accumulated.
        Returns True if crystal was queued (or popup launched).
        """
        try:
            # Create proposal data
            proposal = crystal.to_proposal_dict()
            proposal["source"] = "genesis_emergent"
            proposal["manifest_time"] = datetime.now().isoformat()

            # Dedup: don't add if same id already pending
            existing_ids = {p.get("id") for p in self._pending_proposals}
            if proposal.get("id") in existing_ids:
                LOG.debug(f"Crystal {crystal.id} already pending, skipping")
                return True

            # Add to pending list
            self._pending_proposals.append(proposal)
            self._save_pending()

            # Write notification file (for external monitoring)
            self._write_notification(proposal)

            pending_count = len(self._pending_proposals)
            LOG.info(f"Crystal {crystal.id} queued ({pending_count}/{MIN_PROPOSALS_FOR_POPUP})")

            # Check if we have enough to show popup
            if pending_count >= MIN_PROPOSALS_FOR_POPUP:
                if not self.is_popup_active():
                    LOG.info(f"Threshold reached ({pending_count} proposals), launching popup")
                    return self._launch_popup(self._pending_proposals)
                else:
                    LOG.debug("Popup already active, waiting for it to close")

            return True

        except Exception as e:
            LOG.error(f"Failed to manifest crystal: {e}")
            return False

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
            # Format proposals for popup
            features = []
            for p in proposals:
                features.append({
                    "id": p.get("id"),
                    "name": p.get("title", "Genesis Proposal"),
                    "description": p.get("description", ""),
                    "confidence": p.get("resonance", 0.7),
                    "source": "genesis",
                    "approach": p.get("approach", ""),
                    "risk_assessment": p.get("risk_assessment", ""),
                    "expected_benefit": p.get("expected_benefit", ""),
                    "genome": p.get("genome", {}),
                })

            env = os.environ.copy()
            env["DISPLAY"] = os.environ.get("DISPLAY", ":0")
            env["PYTHONPATH"] = str(self.popup_script.parent.parent.parent)

            # Clean stale result file before launching
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
        """
        Check if popup returned a result.
        Returns the decision if available.
        Clears pending proposals after user decision.
        """
        if RESULT_FILE.exists():
            try:
                result = json.loads(RESULT_FILE.read_text())
                RESULT_FILE.unlink()  # Clean up

                # Clear pending proposals after any user decision
                decision = result.get("decision", "defer")
                if decision in ("approve", "reject"):
                    self._pending_proposals.clear()
                    self._save_pending()
                    LOG.info(f"Cleared pending proposals after {decision}")
                elif decision == "defer":
                    # Keep proposals but don't re-show until more accumulate
                    # Mark as deferred so we need MIN more before showing again
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
