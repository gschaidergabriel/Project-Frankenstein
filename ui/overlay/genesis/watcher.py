"""GenesisWatcher class extracted from the monolith overlay."""

from __future__ import annotations

import json
import threading
import tkinter as tk
from pathlib import Path

from overlay.constants import LOG
from overlay.genesis.proposal import GenesisProposal
from overlay.genesis.popup import GenesisNotificationPopup


try:
    from config.paths import TRAINING_LOG_DIR
except ImportError:
    TRAINING_LOG_DIR = Path("/home/ai-core-node/.local/share/frank/logs/training")

PROPOSALS_FILE = TRAINING_LOG_DIR / "proposals.jsonl"
GENESIS_SHOWN_FILE = Path("/tmp/frank_genesis_shown.json")


class GenesisWatcher:
    """Watches for new Genesis proposals and triggers notifications.
    CRITICAL #3 fix: Added stop_event for graceful shutdown.
    """

    def __init__(self, overlay):
        self.overlay = overlay
        self.shown_ids = set()
        self.popup = None
        self._load_shown()
        # CRITICAL #3 fix: Use threading.Event for graceful shutdown
        self._stop_event = threading.Event()
        self._running = True
        self._thread = threading.Thread(target=self._watch_loop, daemon=True)
        self._thread.start()

    def _load_shown(self):
        """Load IDs of proposals already shown to user."""
        try:
            if GENESIS_SHOWN_FILE.exists():
                data = json.loads(GENESIS_SHOWN_FILE.read_text())
                self.shown_ids = set(data.get("shown", []))
        except json.JSONDecodeError as e:
            LOG.debug(f"Genesis shown file parse error: {e}")
        except OSError as e:
            LOG.debug(f"Genesis shown file read error: {e}")
        except Exception as e:
            LOG.warning(f"Unexpected error loading Genesis shown IDs: {e}")

    def _save_shown(self):
        """Save shown proposal IDs."""
        try:
            GENESIS_SHOWN_FILE.write_text(json.dumps({"shown": list(self.shown_ids)}))
        except OSError as e:
            LOG.debug(f"Genesis shown file write error: {e}")
        except Exception as e:
            LOG.warning(f"Unexpected error saving Genesis shown IDs: {e}")

    def _watch_loop(self):
        """Background loop checking for new proposals."""
        # Use stop_event.wait() instead of time.sleep() for responsive shutdown
        self._stop_event.wait(10)  # Initial delay
        while self._running and not self._stop_event.is_set():
            try:
                self._check_proposals()
            except Exception as e:
                LOG.debug(f"Genesis watcher error: {e}")
            # Use stop_event.wait() for interruptible sleep
            self._stop_event.wait(30)  # Check every 30 seconds

    def _check_proposals(self):
        """Check for new pending proposals."""
        if not PROPOSALS_FILE.exists():
            return

        pending = []
        try:
            with open(PROPOSALS_FILE, 'r') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        if data.get("status") == "pending" and data.get("id") not in self.shown_ids:
                            pending.append(GenesisProposal(data))
                    except json.JSONDecodeError:
                        continue  # Skip malformed lines
        except OSError as e:
            LOG.debug(f"Could not read proposals file: {e}")
            return
        except Exception as e:
            LOG.warning(f"Unexpected error reading proposals: {e}")
            return

        if pending and not self.popup:
            # Schedule notification on main thread
            self.overlay._ui_queue.put(lambda: self._show_notification(pending))

    def _show_notification(self, proposals):
        """Show notification popup (called from main thread)."""
        # HIGH #5 fix: Destroy old popup before creating new one to prevent memory leak
        if self.popup:
            try:
                if self.popup.winfo_exists():
                    # Popup still exists and visible - don't create another
                    return
            except tk.TclError:
                pass  # Widget was already destroyed
            # Cleanup old popup reference
            try:
                self.popup.destroy()
            except (tk.TclError, AttributeError):
                pass  # Already destroyed or invalid
            self.popup = None

        # Mark as shown
        for p in proposals:
            self.shown_ids.add(p.id)
        self._save_shown()

        # Show popup
        self.popup = GenesisNotificationPopup(
            self.overlay,
            proposals,
            self._on_proposal_action
        )

        # Also add a message to chat
        self.overlay._ui_queue.put(
            lambda: self.overlay._add_message(
                "GENESIS",
                f"◈ {len(proposals)} neue Verbesserungsvorschläge verfügbar! Popup geöffnet.",
                is_system=True
            )
        )

    def _on_proposal_action(self, proposal_id: int, action: str):
        """Handle approve/reject action."""
        LOG.info(f"Genesis proposal {proposal_id}: {action}")

        # Update the proposals file
        try:
            lines = []
            with open(PROPOSALS_FILE, 'r') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        if data.get("id") == proposal_id:
                            data["status"] = "approved" if action == "approve" else "rejected"
                            data["validator"] = "user"
                            data["validation_reason"] = f"User {action}d via Genesis UI"
                        lines.append(json.dumps(data))
                    except json.JSONDecodeError:
                        lines.append(line)  # Keep malformed lines as-is

            with open(PROPOSALS_FILE, 'w') as f:
                f.write("\n".join(lines) + "\n")

            # Notify user
            status_msg = "✓ Genehmigt" if action == "approve" else "✕ Abgelehnt"
            self.overlay._ui_queue.put(
                lambda: self.overlay._add_message(
                    "GENESIS",
                    f"Proposal #{proposal_id}: {status_msg}",
                    is_system=True
                )
            )
        except OSError as e:
            LOG.error(f"Failed to read/write proposals file: {e}")
        except Exception as e:
            LOG.error(f"Failed to update proposal: {e}")

    def stop(self):
        """Stop the watcher thread gracefully (CRITICAL #3 fix)."""
        self._running = False
        self._stop_event.set()  # Signal thread to wake up and exit
        # Wait for thread to finish with timeout
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
            if self._thread.is_alive():
                LOG.warning("Genesis watcher thread did not stop in time")
