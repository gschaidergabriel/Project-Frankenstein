"""
ApprovalMixin -- Autonomous Action Approval system for the Frank overlay.

Polls approval_queue.json for daemon requests,
shows them in-chat with anti-annoyance guardrails,
writes responses to approval_responses.json.

Integrates with CommandRouterMixin for pending-approval interception
of user input (ja/nein/zeig).
"""

import json
import os
import re
import time
from pathlib import Path
from typing import Dict, List, Optional, Set

from overlay.constants import LOG

# Regex for user approval responses
APPROVAL_YES_RE = re.compile(
    r"^(ja|yes|ok|okay|jep|jup|mach|do it|klar|passt|genehmigt|erlaubt)$",
    re.IGNORECASE,
)
APPROVAL_NO_RE = re.compile(
    r"^(nein|no|nope|stopp|halt|abbrechen|cancel|nicht|ablehnen)$",
    re.IGNORECASE,
)
APPROVAL_SHOW_RE = re.compile(
    r"^(zeig|show|anzeigen|was wartet|pending|queue)$",
    re.IGNORECASE,
)

GAMING_STATE_FILE = Path("/tmp/gaming_mode_state.json")


class ApprovalMixin:
    """Mixin providing the autonomous action approval system."""

    # ---- Init ----

    def _init_approval_system(self):
        """Initialize approval system state. Call from __init__."""
        try:
            from config.paths import TEMP_FILES as _TF_appr
            self._approval_queue_file = _TF_appr["approval_queue"]
            self._approval_response_file = _TF_appr["approval_responses"]
        except ImportError:
            self._approval_queue_file = Path("/tmp/frank/approval_queue.json")
            self._approval_response_file = Path("/tmp/frank/approval_responses.json")
        self._approval_pending: Optional[Dict] = None
        self._approval_last_shown_ts: float = 0.0
        self._approval_daily_count: int = 0
        self._approval_daily_reset_ts: float = time.time()
        self._approval_last_user_activity_ts: float = time.time()
        self._approval_responded_ids: Set[str] = set()
        self._approval_origin_chain: Set[str] = set()
        self._approval_cleanup_ts: float = time.time()
        self.after(5000, self._poll_approval_queue)
        LOG.info("Approval system initialized")

    # ---- Polling ----

    def _poll_approval_queue(self):
        """Poll queue file every 2000ms."""
        try:
            self._approval_process_queue()
        except Exception as e:
            LOG.debug(f"Approval poll error: {e}")
        self.after(2000, self._poll_approval_queue)

    def _approval_process_queue(self):
        """Core processing: read queue, apply guardrails, show or batch."""
        now = time.time()

        # Daily counter reset
        if now - self._approval_daily_reset_ts > 86400:
            self._approval_daily_count = 0
            self._approval_daily_reset_ts = now

        # Periodic cleanup of origin chain (cap at 50)
        if len(self._approval_origin_chain) > 50:
            self._approval_origin_chain = set(list(self._approval_origin_chain)[-30:])

        # Periodic stale cleanup (every 30 min)
        if now - self._approval_cleanup_ts > 1800:
            self._approval_cleanup_ts = now
            self._approval_cleanup_stale()

        # If a request is currently shown and awaiting answer, don't process more
        if self._approval_pending is not None:
            return

        # Read queue
        requests = self._approval_read_queue()
        if not requests:
            return

        # Filter: remove already-responded, expired, and loop-causing requests
        actionable = []
        for req in requests:
            rid = req["request_id"]
            if rid in self._approval_responded_ids:
                continue
            # Expiry check
            exp = req.get("expires_at", 0)
            if exp and exp > 0 and now > exp:
                self._approval_write_response(rid, "expired")
                continue
            # Anti-loop
            oid = req.get("origin_action_id")
            if oid and oid in self._approval_origin_chain:
                LOG.warning(f"Approval loop suppressed: {rid} from {oid}")
                self._approval_write_response(rid, "suppressed")
                continue
            if req.get("status") == "pending":
                actionable.append(req)

        if not actionable:
            return

        # Separate critical from non-critical
        critical = [r for r in actionable if r["urgency"] == "critical"]
        non_critical = [r for r in actionable if r["urgency"] != "critical"]

        # Critical requests bypass all guardrails except gaming mode
        if critical and not self._approval_is_gaming():
            self._approval_show_request(critical[0])
            return

        # Non-critical guardrails
        if self._approval_is_gaming():
            return
        if self._approval_daily_count >= 15:
            return
        if now - self._approval_last_shown_ts < 60:
            return
        if now - self._approval_last_user_activity_ts < 30:
            return

        # Show medium individually, batch low
        medium = [r for r in non_critical if r["urgency"] == "medium"]
        low = [r for r in non_critical if r["urgency"] == "low"]

        if medium:
            self._approval_show_request(medium[0])
        elif low:
            self._approval_show_batch_summary(low)

    # ---- Display Methods ----

    def _approval_show_request(self, req: Dict):
        """Show a single approval request as a chat message."""
        self._approval_pending = req
        self._approval_last_shown_ts = time.time()
        self._approval_daily_count += 1
        self._approval_update_queue_status(req["request_id"], "shown")

        tag = "URGENT: " if req["urgency"] == "critical" else ""
        msg = (
            f"{tag}{req['title_de']}\n"
            f"{req['detail_de']}\n\n"
            f"Say 'yes' or 'no'."
        )
        self._add_message("Frank", msg, is_system=False)
        LOG.info(f"Approval shown: {req['request_id']} ({req['daemon']}/{req['urgency']})")

    def _approval_show_batch_summary(self, requests: List[Dict]):
        """Show a batched summary for low-priority items."""
        self._approval_pending = {"_batch": True, "items": requests}
        self._approval_last_shown_ts = time.time()
        self._approval_daily_count += 1

        count = len(requests)
        msg = f"{count} proposals waiting. Say 'show' to view them, or just ignore."
        self._add_message("Frank", msg, is_system=False)

    def _approval_show_batch_detail(self):
        """Expand the batch: show each item with index."""
        if not self._approval_pending or not self._approval_pending.get("_batch"):
            return
        items = self._approval_pending["items"]
        lines = []
        for i, req in enumerate(items, 1):
            lines.append(f"{i}. {req['title_de']} ({req['daemon']})")
        msg = "\n".join(lines) + "\n\nSay 'yes' for all, 'no' for all, or 'yes 2' / 'no 1' for individual items."
        self._add_message("Frank", msg, is_system=False)

    # ---- User Input Handling ----

    def _approval_check_input(self, msg: str) -> bool:
        """
        Check if user input is an approval response.
        Called from _on_send() BEFORE other routing.
        Returns True if handled.
        """
        if self._approval_pending is None:
            return False

        low = msg.strip().lower()

        # Batch mode
        if self._approval_pending.get("_batch"):
            if APPROVAL_SHOW_RE.match(low):
                self._add_message("Du", msg, is_user=True)
                self._approval_show_batch_detail()
                return True

            if APPROVAL_YES_RE.match(low):
                self._add_message("Du", msg, is_user=True)
                for item in self._approval_pending["items"]:
                    self._approval_write_response(item["request_id"], "approved", msg)
                    self._approval_origin_chain.add(item["request_id"])
                self._add_message("Frank", f"All {len(self._approval_pending['items'])} approved.", is_system=True)
                self._approval_pending = None
                return True

            if APPROVAL_NO_RE.match(low):
                self._add_message("Du", msg, is_user=True)
                for item in self._approval_pending["items"]:
                    self._approval_write_response(item["request_id"], "rejected", msg)
                self._add_message("Frank", "All rejected.", is_system=True)
                self._approval_pending = None
                return True

            # Individual: "ja 2" or "nein 1"
            m = re.match(r"(ja|nein|yes|no)\s+(\d+)", low)
            if m:
                decision = "approved" if m.group(1) in ("ja", "yes") else "rejected"
                idx = int(m.group(2)) - 1
                items = self._approval_pending["items"]
                if 0 <= idx < len(items):
                    self._add_message("Du", msg, is_user=True)
                    self._approval_write_response(items[idx]["request_id"], decision, msg)
                    if decision == "approved":
                        self._approval_origin_chain.add(items[idx]["request_id"])
                    items.pop(idx)
                    if not items:
                        self._add_message("Frank", "All processed.", is_system=True)
                        self._approval_pending = None
                    else:
                        self._approval_show_batch_detail()
                    return True

            # Something else → dismiss batch, fall through to normal routing
            self._approval_pending = None
            return False

        # Single request mode
        if APPROVAL_YES_RE.match(low):
            rid = self._approval_pending["request_id"]
            self._add_message("Du", msg, is_user=True)
            self._approval_write_response(rid, "approved", msg)
            self._approval_origin_chain.add(rid)
            self._add_message("Frank", "Approved.", is_system=True)
            self._approval_pending = None
            return True

        if APPROVAL_NO_RE.match(low):
            rid = self._approval_pending["request_id"]
            self._add_message("Du", msg, is_user=True)
            self._approval_write_response(rid, "rejected", msg)
            self._add_message("Frank", "Rejected.", is_system=True)
            self._approval_pending = None
            return True

        # Something else → dismiss approval silently, fall through
        self._approval_pending = None
        return False

    # ---- Activity Tracking ----

    def _approval_record_user_activity(self):
        """Call whenever user types or sends a message."""
        self._approval_last_user_activity_ts = time.time()

    # ---- File I/O ----

    def _approval_read_queue(self) -> List[Dict]:
        """Read all pending requests from queue file."""
        try:
            if self._approval_queue_file.exists():
                data = json.loads(self._approval_queue_file.read_text())
                return data.get("requests", [])
        except (json.JSONDecodeError, OSError) as e:
            LOG.debug(f"Approval queue read error: {e}")
        return []

    def _approval_write_response(self, request_id: str, decision: str, user_text: str = ""):
        """Write a response to the response file."""
        self._approval_responded_ids.add(request_id)
        try:
            data = {"responses": []}
            if self._approval_response_file.exists():
                try:
                    data = json.loads(self._approval_response_file.read_text())
                except (json.JSONDecodeError, OSError):
                    pass

            data["responses"].append({
                "request_id": request_id,
                "decision": decision,
                "responded_at": time.time(),
                "user_text": user_text,
            })

            tmp = self._approval_response_file.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False))
            os.replace(str(tmp), str(self._approval_response_file))
        except Exception as e:
            LOG.error(f"Approval response write error: {e}")

    def _approval_update_queue_status(self, request_id: str, new_status: str):
        """Update a request's status in the queue file."""
        try:
            data = {"requests": []}
            if self._approval_queue_file.exists():
                try:
                    data = json.loads(self._approval_queue_file.read_text())
                except (json.JSONDecodeError, OSError):
                    pass
            for req in data.get("requests", []):
                if req["request_id"] == request_id:
                    req["status"] = new_status
                    break
            tmp = self._approval_queue_file.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False))
            os.replace(str(tmp), str(self._approval_queue_file))
        except Exception as e:
            LOG.debug(f"Approval queue update error: {e}")

    def _approval_cleanup_stale(self):
        """Remove stale entries from both files."""
        now = time.time()
        try:
            if self._approval_queue_file.exists():
                data = json.loads(self._approval_queue_file.read_text())
                before = len(data.get("requests", []))
                data["requests"] = [
                    r for r in data.get("requests", [])
                    if now - r.get("created_at", 0) < 7200
                ]
                if len(data["requests"]) < before:
                    tmp = self._approval_queue_file.with_suffix(".tmp")
                    tmp.write_text(json.dumps(data, ensure_ascii=False))
                    os.replace(str(tmp), str(self._approval_queue_file))
        except Exception:
            pass

        try:
            if self._approval_response_file.exists():
                data = json.loads(self._approval_response_file.read_text())
                before = len(data.get("responses", []))
                data["responses"] = [
                    r for r in data.get("responses", [])
                    if now - r.get("responded_at", 0) < 7200
                ]
                if len(data["responses"]) < before:
                    tmp = self._approval_response_file.with_suffix(".tmp")
                    tmp.write_text(json.dumps(data, ensure_ascii=False))
                    os.replace(str(tmp), str(self._approval_response_file))
        except Exception:
            pass

        # Trim responded IDs set
        if len(self._approval_responded_ids) > 200:
            self._approval_responded_ids = set(list(self._approval_responded_ids)[-100:])

    # ---- Guardrails ----

    def _approval_is_gaming(self) -> bool:
        """Check if user is in gaming mode."""
        try:
            if GAMING_STATE_FILE.exists():
                data = json.loads(GAMING_STATE_FILE.read_text())
                return data.get("gaming", False)
        except (json.JSONDecodeError, OSError):
            pass
        return False
