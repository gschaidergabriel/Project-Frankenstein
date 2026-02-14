"""
Approval Queue -- shared library for daemons to request user approval.

Any daemon (ASRS, Genesis, E-WISH, System Control, Package Manager)
imports this module to submit approval requests. The Frank overlay
polls the queue file and shows requests in the chat.

Usage:
    from tools.approval_queue import submit_request, check_response, ApprovalUrgency

    req_id = submit_request(
        daemon="genesis",
        urgency=ApprovalUrgency.MEDIUM,
        category="code_change",
        title_de="Neues Modul erstellen",
        detail_de="Genesis moechte cache_manager.py erstellen...",
        action_payload={"file": "cache_manager.py", "lines": 47},
    )

    # Later, poll for response:
    resp = check_response(req_id)
    if resp and resp["decision"] == "approved":
        do_the_thing()
"""

import json
import logging
import os
import threading
import time
import uuid
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Optional

LOG = logging.getLogger("approval_queue")

QUEUE_FILE = Path("/tmp/frank_approval_queue.json")
RESPONSE_FILE = Path("/tmp/frank_approval_responses.json")
_lock = threading.Lock()


class ApprovalUrgency(Enum):
    LOW = "low"            # expires 10 min, can be batched
    MEDIUM = "medium"      # expires 30 min, shown individually
    CRITICAL = "critical"  # never expires, bypasses cooldown


# Expiry durations in seconds
_EXPIRY = {
    "low": 600,       # 10 minutes
    "medium": 1800,   # 30 minutes
    "critical": 0,    # never (0 = no expiry)
}


def submit_request(
    daemon: str,
    urgency: ApprovalUrgency,
    category: str,
    title_de: str,
    detail_de: str,
    action_payload: Dict[str, Any],
    origin_action_id: Optional[str] = None,
) -> str:
    """Submit an approval request. Returns the request_id."""
    now = time.time()
    expiry_s = _EXPIRY[urgency.value]
    request_id = f"{daemon}_{int(now * 1000)}_{uuid.uuid4().hex[:4]}"

    entry = {
        "request_id": request_id,
        "daemon": daemon,
        "urgency": urgency.value,
        "category": category,
        "title_de": title_de,
        "detail_de": detail_de,
        "action_payload": action_payload,
        "created_at": now,
        "expires_at": now + expiry_s if expiry_s > 0 else 0,
        "origin_action_id": origin_action_id,
        "status": "pending",
    }

    with _lock:
        data = _read_json(QUEUE_FILE, {"requests": []})

        # Dedup guard: skip if same daemon+category already pending within 5 min
        for existing in data["requests"]:
            if (existing["daemon"] == daemon
                    and existing["category"] == category
                    and existing["status"] in ("pending", "shown")
                    and now - existing.get("created_at", 0) < 300):
                LOG.debug(f"Dedup: request similar to {existing['request_id']}, returning existing")
                return existing["request_id"]

        data["requests"].append(entry)
        _write_json_atomic(QUEUE_FILE, data)

    LOG.info(f"Approval request submitted: {request_id} ({daemon}/{urgency.value}/{category})")
    return request_id


def check_response(request_id: str, consume: bool = True) -> Optional[Dict]:
    """
    Check if overlay has responded to a request.
    If consume=True, remove the response entry after reading.
    Returns the response dict or None.
    """
    with _lock:
        data = _read_json(RESPONSE_FILE, {"responses": []})
        for i, resp in enumerate(data["responses"]):
            if resp["request_id"] == request_id:
                if consume:
                    data["responses"].pop(i)
                    _write_json_atomic(RESPONSE_FILE, data)
                return resp
    return None


def wait_for_response(request_id: str, timeout_s: float = 120, poll_interval: float = 2.0) -> Optional[Dict]:
    """
    Block until a response arrives or timeout.
    Returns the response dict or None on timeout.
    """
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        resp = check_response(request_id, consume=True)
        if resp:
            return resp
        time.sleep(poll_interval)
    return None


def cleanup_stale(max_age_s: float = 7200):
    """Remove entries older than max_age_s from both files. Call periodically."""
    now = time.time()
    with _lock:
        # Clean queue
        qdata = _read_json(QUEUE_FILE, {"requests": []})
        before = len(qdata["requests"])
        qdata["requests"] = [
            r for r in qdata["requests"]
            if now - r.get("created_at", 0) < max_age_s
        ]
        if len(qdata["requests"]) < before:
            _write_json_atomic(QUEUE_FILE, qdata)

        # Clean responses
        rdata = _read_json(RESPONSE_FILE, {"responses": []})
        before_r = len(rdata["responses"])
        rdata["responses"] = [
            r for r in rdata["responses"]
            if now - r.get("responded_at", 0) < max_age_s
        ]
        if len(rdata["responses"]) < before_r:
            _write_json_atomic(RESPONSE_FILE, rdata)


def _read_json(path: Path, default: Dict) -> Dict:
    """Read JSON file, return default on any error."""
    try:
        if path.exists():
            return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        pass
    return dict(default)


def _write_json_atomic(path: Path, data: Dict):
    """Atomic write: write to .tmp then rename (prevents partial reads)."""
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False))
    os.replace(str(tmp), str(path))
