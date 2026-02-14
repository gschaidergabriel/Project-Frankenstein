#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
calendar_reader.py – Google Calendar integration via CalDAV for Frank.

Accesses Google Calendar through CalDAV protocol using Thunderbird's
OAuth2 credentials. Stdlib only – no external dependencies.
"""

from __future__ import annotations

import json
import logging
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

LOG = logging.getLogger("calendar_reader")

# ── CalDAV configuration ──────────────────────────────────────────

_CALDAV_BASE = "https://apidata.googleusercontent.com/caldav/v2"

# XML namespaces
_NS_DAV = "DAV:"
_NS_CALDAV = "urn:ietf:params:xml:ns:caldav"

# Timezone for local display — auto-detect from system, fallback to Vienna
try:
    import subprocess as _sp
    _tz_result = _sp.run(["timedatectl", "show", "-p", "Timezone", "--value"],
                         capture_output=True, text=True, timeout=2)
    _LOCAL_TZ = _tz_result.stdout.strip() or "Europe/Vienna"
except Exception:
    _LOCAL_TZ = "Europe/Vienna"

# ── Injection patterns (shared with email_reader) ─────────────────

_INJECTION_PATTERNS = re.compile(
    r"(ignore\s+(all\s+)?previous\s+instructions?"
    r"|you\s+are\s+now"
    r"|forget\s+(everything|all|your)\s+(above|previous)"
    r"|system\s*:"
    r"|<\|im_start\|>"
    r"|<\|im_end\|>"
    r"|\[INST\]"
    r"|\[/INST\]"
    r"|###\s*Instruction"
    r"|###\s*System"
    r"|<\|system\|>"
    r"|<\|user\|>)",
    re.IGNORECASE,
)


# ── OAuth2 access token ──────────────────────────────────────────

def _get_access_token() -> Optional[str]:
    """Get OAuth2 access token, reusing email_reader's credential cache."""
    try:
        from email_reader import _get_imap_credentials
        creds = _get_imap_credentials()
        if creds and creds.get("access_token"):
            return creds["access_token"]
    except Exception as e:
        LOG.warning(f"Failed to get access token: {e}")
    return None


def _get_user_email() -> Optional[str]:
    """Get the user's email address from email_reader credentials."""
    try:
        from email_reader import _get_imap_credentials
        creds = _get_imap_credentials()
        if creds:
            return creds.get("user")
    except Exception:
        pass
    return None


# ── CalDAV HTTP helpers ───────────────────────────────────────────

def _caldav_request(
    method: str,
    path: str,
    body: Optional[str] = None,
    content_type: str = "application/xml",
    extra_headers: Optional[Dict[str, str]] = None,
    timeout_s: float = 15.0,
) -> tuple:
    """
    Make an authenticated CalDAV request.
    Returns (status_code, response_body_str).
    """
    token = _get_access_token()
    if not token:
        raise RuntimeError("Kein OAuth2-Token verfuegbar")

    user = _get_user_email()
    if not user:
        raise RuntimeError("Keine User-Email gefunden")

    url = f"{_CALDAV_BASE}/{urllib.parse.quote(user)}/events{path}"

    headers = {
        "Authorization": f"Bearer {token}",
    }
    if body:
        headers["Content-Type"] = content_type
    if extra_headers:
        headers.update(extra_headers)

    data = body.encode("utf-8") if body else None
    req = urllib.request.Request(url, data=data, method=method, headers=headers)

    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        body_text = e.read().decode("utf-8", errors="replace") if e.fp else ""
        return e.code, body_text


# ── ICS parser ────────────────────────────────────────────────────

def _parse_ics_datetime(value: str, params: str = "") -> Optional[datetime]:
    """
    Parse an ICS datetime value.
    Supports:
      - 20260208T150000Z (UTC)
      - 20260208T150000 (local/naive)
      - 20260208 (all-day, VALUE=DATE)
      - TZID=Europe/Vienna:20260208T150000
    """
    # Handle TZID prefix in params
    if "TZID=" in params:
        # We note the timezone but parse as naive for simplicity
        pass

    # Strip any TZID prefix from value itself
    if ":" in value and not value.startswith("2"):
        value = value.split(":", 1)[-1]

    value = value.strip()

    try:
        if len(value) == 8:
            # All-day: 20260208
            return datetime.strptime(value, "%Y%m%d")
        elif value.endswith("Z"):
            # UTC: 20260208T150000Z
            return datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        else:
            # Local: 20260208T150000
            return datetime.strptime(value, "%Y%m%dT%H%M%S")
    except ValueError:
        LOG.warning(f"Failed to parse ICS datetime: {value}")
        return None


def _parse_vevent(ics_text: str) -> Optional[Dict[str, Any]]:
    """Parse a single VEVENT block from ICS text into a dict."""
    lines = ics_text.replace("\r\n ", "").replace("\r\n\t", "").splitlines()

    event: Dict[str, Any] = {}
    in_vevent = False
    in_valarm = False
    description_lines: list = []
    current_key = ""

    for line in lines:
        if line.strip() == "BEGIN:VEVENT":
            in_vevent = True
            continue
        if line.strip() == "END:VEVENT":
            break
        if line.strip() == "BEGIN:VALARM":
            in_valarm = True
            continue
        if line.strip() == "END:VALARM":
            in_valarm = False
            continue

        if not in_vevent:
            continue

        # Handle VALARM trigger
        if in_valarm:
            if line.startswith("TRIGGER:"):
                trigger = line.split(":", 1)[1].strip()
                # Parse -P0DT0H30M0S or -PT15M format
                m = re.search(r"(\d+)H", trigger)
                hours = int(m.group(1)) if m else 0
                m = re.search(r"(\d+)M", trigger)
                mins = int(m.group(1)) if m else 0
                event["alarm_minutes"] = hours * 60 + mins
            continue

        # Split property;params:value
        if ":" in line:
            prop_part, value = line.split(":", 1)
        else:
            continue

        # Separate property name from parameters
        if ";" in prop_part:
            prop_name, params = prop_part.split(";", 1)
        else:
            prop_name, params = prop_part, ""

        prop_name = prop_name.upper()

        if prop_name == "UID":
            event["uid"] = value.strip()
        elif prop_name == "SUMMARY":
            event["title"] = value.strip()
        elif prop_name == "DESCRIPTION":
            event["description"] = value.strip()
        elif prop_name == "LOCATION":
            event["location"] = value.strip()
        elif prop_name == "STATUS":
            event["status"] = value.strip()
        elif prop_name == "DTSTART":
            dt = _parse_ics_datetime(value, params)
            if dt:
                event["start"] = dt
                event["all_day"] = "VALUE=DATE" in params or len(value.strip()) == 8
        elif prop_name == "DTEND":
            dt = _parse_ics_datetime(value, params)
            if dt:
                event["end"] = dt
        elif prop_name == "CREATED":
            event["created"] = value.strip()
        elif prop_name == "LAST-MODIFIED":
            event["modified"] = value.strip()

    if "uid" not in event:
        return None

    # Defaults
    event.setdefault("title", "(Kein Titel)")
    event.setdefault("description", "")
    event.setdefault("location", "")
    event.setdefault("status", "CONFIRMED")
    event.setdefault("all_day", False)
    event.setdefault("alarm_minutes", 30)

    return event


def _format_dt(dt: Optional[datetime], all_day: bool = False) -> str:
    """Format a datetime for display."""
    if dt is None:
        return "?"
    if all_day:
        return dt.strftime("%d.%m.%Y (ganztaegig)")
    return dt.strftime("%d.%m.%Y %H:%M")


# ── XML response parser ──────────────────────────────────────────

def _parse_caldav_response(xml_text: str) -> List[Dict[str, Any]]:
    """Parse a CalDAV multistatus response and extract events."""
    events = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        LOG.warning(f"CalDAV XML parse error: {e}")
        return []

    for response in root.iter(f"{{{_NS_DAV}}}response"):
        href_el = response.find(f"{{{_NS_DAV}}}href")
        href = href_el.text if href_el is not None else ""

        for propstat in response.iter(f"{{{_NS_DAV}}}propstat"):
            cal_data = propstat.find(f".//{{{_NS_CALDAV}}}calendar-data")
            if cal_data is not None and cal_data.text:
                ev = _parse_vevent(cal_data.text)
                if ev:
                    ev["href"] = href
                    events.append(ev)

    # Sort by start time
    events.sort(key=lambda e: e.get("start", datetime.min))
    return events


# ── Sanitizer ─────────────────────────────────────────────────────

def sanitize_event_content(text: str) -> str:
    """Sanitize event content (description, title) against prompt injection."""
    if not text:
        return ""
    # Remove HTML tags
    text = re.sub(r"<[^>]+>", "", text)
    # Remove injection patterns
    text = _INJECTION_PATTERNS.sub("[FILTERED]", text)
    # Remove data URIs
    text = re.sub(r"data:[a-zA-Z/]+;base64,[A-Za-z0-9+/=]{100,}", "[BASE64]", text)
    # Truncate
    return text[:1000]


# ── Public API ────────────────────────────────────────────────────

def list_events(
    start: Optional[str] = None,
    end: Optional[str] = None,
    limit: int = 20,
) -> Dict[str, Any]:
    """
    List calendar events in a date range.

    Args:
        start: ISO date(time) string, defaults to now
        end: ISO date(time) string, defaults to start + 7 days
        limit: Max events to return

    Returns:
        {"ok": True, "events": [...]} or {"error": "..."}
    """
    now = datetime.now()

    if start:
        try:
            start_dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
        except ValueError:
            try:
                start_dt = datetime.strptime(start, "%Y-%m-%d")
            except ValueError:
                return {"error": f"Ungueltiges Startdatum: {start}"}
    else:
        start_dt = now.replace(hour=0, minute=0, second=0, microsecond=0)

    if end:
        try:
            end_dt = datetime.fromisoformat(end.replace("Z", "+00:00"))
        except ValueError:
            try:
                end_dt = datetime.strptime(end, "%Y-%m-%d") + timedelta(days=1)
            except ValueError:
                return {"error": f"Ungueltiges Enddatum: {end}"}
    else:
        end_dt = start_dt + timedelta(days=7)

    start_str = start_dt.strftime("%Y%m%dT%H%M%SZ")
    end_str = end_dt.strftime("%Y%m%dT%H%M%SZ")

    xml_body = f"""<?xml version="1.0" encoding="utf-8"?>
<c:calendar-query xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">
  <d:prop>
    <d:getetag/>
    <c:calendar-data/>
  </d:prop>
  <c:filter>
    <c:comp-filter name="VCALENDAR">
      <c:comp-filter name="VEVENT">
        <c:time-range start="{start_str}" end="{end_str}"/>
      </c:comp-filter>
    </c:comp-filter>
  </c:filter>
</c:calendar-query>"""

    try:
        status, body = _caldav_request(
            "REPORT", "", body=xml_body,
            extra_headers={"Depth": "1"},
        )
        if status not in (200, 207):
            return {"error": f"CalDAV-Fehler: HTTP {status}"}

        events = _parse_caldav_response(body)

        # Sanitize and format
        result_events = []
        for ev in events[:limit]:
            result_events.append({
                "uid": ev.get("uid", ""),
                "title": sanitize_event_content(ev.get("title", "")),
                "start": _format_dt(ev.get("start"), ev.get("all_day", False)),
                "end": _format_dt(ev.get("end"), ev.get("all_day", False)),
                "start_iso": ev["start"].isoformat() if ev.get("start") else None,
                "end_iso": ev["end"].isoformat() if ev.get("end") else None,
                "description": sanitize_event_content(ev.get("description", "")),
                "location": sanitize_event_content(ev.get("location", "")),
                "all_day": ev.get("all_day", False),
                "status": ev.get("status", "CONFIRMED"),
            })

        return {"ok": True, "events": result_events, "count": len(result_events)}

    except Exception as e:
        return {"error": f"Kalender-Fehler: {e}"}


def get_today_events() -> Dict[str, Any]:
    """Get all events for today."""
    now = datetime.now()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    return list_events(start=start.isoformat(), end=end.isoformat())


def get_week_events() -> Dict[str, Any]:
    """Get events for the next 7 days."""
    now = datetime.now()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=7)
    return list_events(start=start.isoformat(), end=end.isoformat())


def get_event(event_uid: str) -> Dict[str, Any]:
    """Get a single event by UID."""
    if not event_uid:
        return {"error": "Keine Event-UID angegeben"}

    # Fetch the event directly by href
    path = f"/{event_uid}.ics" if not event_uid.endswith(".ics") else f"/{event_uid}"
    try:
        status, body = _caldav_request("GET", path, content_type="text/calendar")
        if status == 404:
            return {"error": "Event nicht gefunden"}
        if status != 200:
            return {"error": f"CalDAV-Fehler: HTTP {status}"}

        ev = _parse_vevent(body)
        if not ev:
            return {"error": "Event konnte nicht geparst werden"}

        return {
            "ok": True,
            "event": {
                "uid": ev.get("uid", ""),
                "title": sanitize_event_content(ev.get("title", "")),
                "start": _format_dt(ev.get("start"), ev.get("all_day", False)),
                "end": _format_dt(ev.get("end"), ev.get("all_day", False)),
                "description": sanitize_event_content(ev.get("description", "")),
                "location": sanitize_event_content(ev.get("location", "")),
                "all_day": ev.get("all_day", False),
                "status": ev.get("status", "CONFIRMED"),
            },
        }
    except Exception as e:
        return {"error": f"Kalender-Fehler: {e}"}


def create_event(
    title: str,
    start: str,
    end: Optional[str] = None,
    description: str = "",
    location: str = "",
) -> Dict[str, Any]:
    """
    Create a new calendar event.

    Args:
        title: Event title
        start: Start datetime ISO format (YYYY-MM-DDTHH:MM or YYYY-MM-DD)
        end: End datetime ISO format (defaults to start + 1 hour)
        description: Event description
        location: Event location

    Returns:
        {"ok": True, "uid": "...", "title": "..."} or {"error": "..."}
    """
    if not title:
        return {"error": "Kein Titel angegeben"}
    if not start:
        return {"error": "Keine Startzeit angegeben"}

    # Parse start
    try:
        if "T" in start:
            start_dt = datetime.fromisoformat(start)
        else:
            start_dt = datetime.strptime(start, "%Y-%m-%d")
    except ValueError:
        return {"error": f"Ungueltiges Startdatum: {start}"}

    # Parse or default end
    all_day = "T" not in start
    if end:
        try:
            if "T" in end:
                end_dt = datetime.fromisoformat(end)
            else:
                end_dt = datetime.strptime(end, "%Y-%m-%d")
        except ValueError:
            end_dt = start_dt + timedelta(hours=1)
    else:
        if all_day:
            end_dt = start_dt + timedelta(days=1)
        else:
            end_dt = start_dt + timedelta(hours=1)

    event_uid = f"frank-{uuid.uuid4().hex[:12]}"

    # Build ICS
    if all_day:
        dt_start_line = f"DTSTART;VALUE=DATE:{start_dt.strftime('%Y%m%d')}"
        dt_end_line = f"DTEND;VALUE=DATE:{end_dt.strftime('%Y%m%d')}"
    else:
        dt_start_line = f"DTSTART;TZID={_LOCAL_TZ}:{start_dt.strftime('%Y%m%dT%H%M%S')}"
        dt_end_line = f"DTEND;TZID={_LOCAL_TZ}:{end_dt.strftime('%Y%m%dT%H%M%S')}"

    # Escape ICS special characters
    ics_title = title.replace("\\", "\\\\").replace(",", "\\,").replace(";", "\\;").replace("\n", "\\n")
    ics_desc = description.replace("\\", "\\\\").replace(",", "\\,").replace(";", "\\;").replace("\n", "\\n")
    ics_loc = location.replace("\\", "\\\\").replace(",", "\\,").replace(";", "\\;").replace("\n", "\\n")

    now_utc = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    ics = (
        "BEGIN:VCALENDAR\r\n"
        "VERSION:2.0\r\n"
        "PRODID:-//Frank AI-OS//Calendar//DE\r\n"
        "BEGIN:VEVENT\r\n"
        f"UID:{event_uid}\r\n"
        f"DTSTAMP:{now_utc}\r\n"
        f"{dt_start_line}\r\n"
        f"{dt_end_line}\r\n"
        f"SUMMARY:{ics_title}\r\n"
    )
    if ics_desc:
        ics += f"DESCRIPTION:{ics_desc}\r\n"
    if ics_loc:
        ics += f"LOCATION:{ics_loc}\r\n"
    ics += (
        "STATUS:CONFIRMED\r\n"
        "END:VEVENT\r\n"
        "END:VCALENDAR\r\n"
    )

    try:
        status, body = _caldav_request(
            "PUT", f"/{event_uid}.ics",
            body=ics,
            content_type="text/calendar; charset=utf-8",
            extra_headers={"If-None-Match": "*"},
        )
        if status in (201, 204):
            LOG.info(f"Calendar event created: {title} ({event_uid})")
            return {
                "ok": True,
                "uid": event_uid,
                "title": title,
                "start": _format_dt(start_dt, all_day),
                "end": _format_dt(end_dt, all_day),
            }
        else:
            return {"error": f"CalDAV PUT fehlgeschlagen: HTTP {status}"}

    except Exception as e:
        return {"error": f"Event-Erstellung fehlgeschlagen: {e}"}


def delete_event(event_uid: str) -> Dict[str, Any]:
    """Delete a calendar event by UID."""
    if not event_uid:
        return {"error": "Keine Event-UID angegeben"}

    path = f"/{event_uid}.ics" if not event_uid.endswith(".ics") else f"/{event_uid}"
    try:
        status, body = _caldav_request("DELETE", path)
        if status == 204:
            LOG.info(f"Calendar event deleted: {event_uid}")
            return {"ok": True, "deleted": event_uid}
        elif status == 404:
            return {"error": "Event nicht gefunden"}
        else:
            return {"error": f"CalDAV DELETE fehlgeschlagen: HTTP {status}"}
    except Exception as e:
        return {"error": f"Loeschen fehlgeschlagen: {e}"}


def check_upcoming(minutes: int = 15) -> Dict[str, Any]:
    """
    Check for events starting in the next N minutes.
    Used for reminder notifications.

    Returns:
        {"ok": True, "upcoming": [...], "count": N}
    """
    now = datetime.now()
    end = now + timedelta(minutes=minutes)

    result = list_events(start=now.isoformat(), end=end.isoformat())
    if "error" in result:
        return result

    upcoming = []
    for ev in result.get("events", []):
        if ev.get("start_iso"):
            try:
                ev_start = datetime.fromisoformat(ev["start_iso"])
                diff = (ev_start - now).total_seconds() / 60
                ev["minutes_until"] = max(0, int(diff))
                upcoming.append(ev)
            except (ValueError, TypeError):
                pass

    return {"ok": True, "upcoming": upcoming, "count": len(upcoming)}


# ── CLI test ──────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    print("=== Calendar Reader Test ===\n")

    # Test 1: OAuth2 token
    token = _get_access_token()
    print(f"Access token: {'OK (' + str(len(token)) + ' chars)' if token else 'FAIL'}")
    user = _get_user_email()
    print(f"User: {user}\n")

    if not token:
        print("ERROR: No access token!")
        exit(1)

    # Test 2: Today's events
    print("--- Today's Events ---")
    result = get_today_events()
    if result.get("ok"):
        events = result.get("events", [])
        print(f"Found {len(events)} events today")
        for ev in events:
            print(f"  {ev['start']} - {ev['title']}")
    else:
        print(f"  Error: {result.get('error')}")

    # Test 3: Create + verify + delete
    print("\n--- Create/Read/Delete Test ---")
    cr = create_event(
        title="Frank Calendar Test",
        start=(datetime.now() + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M"),
        description="Automatischer Test von calendar_reader.py",
    )
    if cr.get("ok"):
        uid = cr["uid"]
        print(f"  Created: {cr['title']} (UID: {uid})")

        # Verify
        today = get_today_events()
        found = any(e["uid"] == uid for e in today.get("events", []))
        print(f"  Verified in today's events: {found}")

        # Delete
        dr = delete_event(uid)
        print(f"  Deleted: {dr.get('ok', False)}")
    else:
        print(f"  Create failed: {cr.get('error')}")

    # Test 4: Week events
    print("\n--- Week Events ---")
    result = get_week_events()
    if result.get("ok"):
        print(f"Found {result['count']} events this week")
        for ev in result.get("events", []):
            print(f"  {ev['start']} - {ev['title']}")
    else:
        print(f"  Error: {result.get('error')}")

    # Test 5: Upcoming reminders
    print("\n--- Upcoming (15 min) ---")
    result = check_upcoming(15)
    if result.get("ok"):
        print(f"Found {result['count']} upcoming events")
    else:
        print(f"  Error: {result.get('error')}")

    print("\n=== Test Complete ===")
