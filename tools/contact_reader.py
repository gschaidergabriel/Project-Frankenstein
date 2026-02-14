#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
contact_reader.py – Google Contacts integration via CardDAV for Frank.

Accesses Google Contacts through CardDAV protocol using Thunderbird's
OAuth2 credentials. Stdlib only – no external dependencies.

Google's CardDAV quirks:
- addressbook-query REPORT returns 400 (unsupported)
- addressbook-multiget REPORT works (two-step: PROPFIND hrefs → multiget)
- Google assigns its own hex UIDs, ignoring client-set UIDs
- PUT creates, DELETE uses the server-assigned href ID
"""

from __future__ import annotations

import logging
import re
import urllib.error
import urllib.parse
import urllib.request
import uuid
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional

LOG = logging.getLogger("contact_reader")

# ── CardDAV configuration ─────────────────────────────────────────

_CARDDAV_BASE = "https://www.googleapis.com/carddav/v1/principals"

# XML namespaces
_NS_DAV = "DAV:"
_NS_CARDDAV = "urn:ietf:params:xml:ns:carddav"


# ── OAuth2 access (reuse from email_reader) ───────────────────────

def _get_access_token() -> Optional[str]:
    """Get OAuth2 access token from email_reader's credential cache."""
    try:
        from email_reader import _get_imap_credentials
        creds = _get_imap_credentials()
        if creds and creds.get("access_token"):
            return creds["access_token"]
    except Exception as e:
        LOG.warning(f"Failed to get access token: {e}")
    return None


def _get_user_email() -> Optional[str]:
    """Get the user's email address."""
    try:
        from email_reader import _get_imap_credentials
        creds = _get_imap_credentials()
        if creds:
            return creds.get("user")
    except Exception:
        pass
    return None


# ── CardDAV HTTP helpers ──────────────────────────────────────────

def _carddav_request(
    method: str,
    path: str = "",
    body: Optional[str] = None,
    content_type: str = "application/xml",
    extra_headers: Optional[Dict[str, str]] = None,
    timeout_s: float = 15.0,
) -> tuple:
    """
    Make an authenticated CardDAV request.
    Returns (status_code, response_body_str).
    """
    token = _get_access_token()
    if not token:
        raise RuntimeError("Kein OAuth2-Token verfuegbar")

    user = _get_user_email()
    if not user:
        raise RuntimeError("Keine User-Email gefunden")

    url = f"{_CARDDAV_BASE}/{urllib.parse.quote(user)}/lists/default{path}"

    headers = {"Authorization": f"Bearer {token}"}
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


# ── vCard parser ──────────────────────────────────────────────────

def _parse_vcard(vcard_text: str) -> Optional[Dict[str, Any]]:
    """Parse a single vCard into a contact dict."""
    if "BEGIN:VCARD" not in vcard_text:
        return None

    contact: Dict[str, Any] = {
        "uid": "",
        "name": "",
        "emails": [],
        "phones": [],
        "org": "",
        "note": "",
    }

    # Unfold long lines (RFC 2425: continuation lines start with space/tab)
    text = vcard_text.replace("\r\n ", "").replace("\r\n\t", "").replace("\n ", "").replace("\n\t", "")

    for line in text.splitlines():
        line = line.strip()
        if not line or line in ("BEGIN:VCARD", "END:VCARD", "VERSION:3.0", "VERSION:4.0"):
            continue

        # Split property;params:value
        if ":" not in line:
            continue
        prop_part, value = line.split(":", 1)
        value = value.strip()

        # Separate property name from parameters
        prop_name = prop_part.split(";")[0].upper()

        if prop_name == "FN":
            contact["name"] = _unescape_vcard(value)
        elif prop_name == "N":
            # N:Last;First;Middle;Prefix;Suffix - use as fallback if no FN
            if not contact["name"]:
                parts = value.split(";")
                first = parts[1] if len(parts) > 1 else ""
                last = parts[0] if parts else ""
                contact["name"] = f"{first} {last}".strip()
        elif prop_name == "UID":
            contact["uid"] = value
        elif prop_name == "TEL":
            phone = value.strip()
            if phone:
                contact["phones"].append(phone)
        elif prop_name == "EMAIL":
            email = value.strip()
            if email:
                contact["emails"].append(email)
        elif prop_name == "ORG":
            contact["org"] = _unescape_vcard(value.replace(";", " ").strip())
        elif prop_name == "NOTE":
            contact["note"] = _unescape_vcard(value)

    if not contact["uid"] and not contact["name"]:
        return None

    return contact


def _unescape_vcard(text: str) -> str:
    """Unescape vCard special characters."""
    return text.replace("\\n", "\n").replace("\\,", ",").replace("\\;", ";").replace("\\\\", "\\")


def _escape_vcard(text: str) -> str:
    """Escape special characters for vCard."""
    return text.replace("\\", "\\\\").replace(",", "\\,").replace(";", "\\;").replace("\n", "\\n")


# ── CardDAV two-step listing ─────────────────────────────────────
# Google rejects addressbook-query REPORT (400). We use:
#   1. PROPFIND Depth:1 → list of contact hrefs
#   2. addressbook-multiget REPORT → vCard data for those hrefs

def _list_contact_hrefs() -> List[str]:
    """PROPFIND Depth:1 to get all contact hrefs in the addressbook."""
    xml_body = (
        '<?xml version="1.0"?>'
        '<d:propfind xmlns:d="DAV:">'
        "<d:prop><d:getetag/><d:resourcetype/></d:prop>"
        "</d:propfind>"
    )
    status, body = _carddav_request(
        "PROPFIND", "/", body=xml_body,
        extra_headers={"Depth": "1"},
    )
    if status not in (200, 207):
        LOG.warning(f"PROPFIND failed: HTTP {status}")
        return []

    hrefs = []
    try:
        root = ET.fromstring(body)
    except ET.ParseError as e:
        LOG.warning(f"PROPFIND XML parse error: {e}")
        return []

    for response in root.iter(f"{{{_NS_DAV}}}response"):
        href_el = response.find(f"{{{_NS_DAV}}}href")
        if href_el is None or not href_el.text:
            continue
        href = href_el.text
        # Skip the collection itself (has <d:collection/> resourcetype)
        rt = response.find(f".//{{{_NS_DAV}}}collection")
        if rt is not None:
            continue
        hrefs.append(href)

    return hrefs


def _multiget_contacts(hrefs: List[str]) -> List[Dict[str, Any]]:
    """addressbook-multiget REPORT to fetch vCard data for given hrefs."""
    if not hrefs:
        return []

    # Build multiget XML with href elements
    href_xml = "".join(f"<d:href>{h}</d:href>" for h in hrefs)
    xml_body = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<card:addressbook-multiget xmlns:d="DAV:" '
        'xmlns:card="urn:ietf:params:xml:ns:carddav">'
        "<d:prop><d:getetag/><card:address-data/></d:prop>"
        f"{href_xml}"
        "</card:addressbook-multiget>"
    )

    status, body = _carddav_request(
        "REPORT", "/", body=xml_body,
        extra_headers={"Depth": "1"},
    )
    if status not in (200, 207):
        LOG.warning(f"Multiget failed: HTTP {status}")
        return []

    contacts = []
    try:
        root = ET.fromstring(body)
    except ET.ParseError as e:
        LOG.warning(f"Multiget XML parse error: {e}")
        return []

    for response in root.iter(f"{{{_NS_DAV}}}response"):
        href_el = response.find(f"{{{_NS_DAV}}}href")
        href = href_el.text if href_el is not None else ""

        for propstat in response.iter(f"{{{_NS_DAV}}}propstat"):
            addr_data = propstat.find(f".//{{{_NS_CARDDAV}}}address-data")
            if addr_data is not None and addr_data.text:
                contact = _parse_vcard(addr_data.text)
                if contact:
                    contact["href"] = href
                    contacts.append(contact)

    contacts.sort(key=lambda c: c.get("name", "").lower())
    return contacts


# ── Sanitizer ─────────────────────────────────────────────────────

_INJECTION_PATTERNS = re.compile(
    r"(ignore\s+(all\s+)?previous\s+instructions?"
    r"|you\s+are\s+now"
    r"|system\s*:"
    r"|<\|im_start\|>)",
    re.IGNORECASE,
)


def _sanitize(text: str) -> str:
    """Sanitize contact text against prompt injection."""
    if not text:
        return ""
    text = _INJECTION_PATTERNS.sub("[FILTERED]", text)
    return text[:500]


# ── Public API ────────────────────────────────────────────────────

def list_contacts() -> Dict[str, Any]:
    """List all contacts from Google Contacts via CardDAV (two-step)."""
    try:
        hrefs = _list_contact_hrefs()
        if not hrefs:
            return {"ok": True, "contacts": [], "count": 0}

        contacts = _multiget_contacts(hrefs)

        result = []
        for c in contacts:
            result.append({
                "uid": c.get("uid", ""),
                "name": _sanitize(c.get("name", "")),
                "phones": [_sanitize(p) for p in c.get("phones", [])],
                "emails": [_sanitize(e) for e in c.get("emails", [])],
                "org": _sanitize(c.get("org", "")),
            })

        return {"ok": True, "contacts": result, "count": len(result)}

    except Exception as e:
        return {"error": f"Kontakt-Fehler: {e}"}


def search_contacts(query: str) -> Dict[str, Any]:
    """Search contacts by name, email, or phone."""
    if not query:
        return {"error": "Kein Suchbegriff angegeben"}

    result = list_contacts()
    if "error" in result:
        return result

    q = query.lower()
    matches = []
    for c in result.get("contacts", []):
        name = (c.get("name") or "").lower()
        phones = " ".join(c.get("phones", [])).lower()
        emails = " ".join(c.get("emails", [])).lower()
        org = (c.get("org") or "").lower()

        if q in name or q in phones or q in emails or q in org:
            matches.append(c)

    return {"ok": True, "contacts": matches, "count": len(matches), "query": query}


def get_contact(uid: str) -> Dict[str, Any]:
    """Get a single contact by UID (Google's server-assigned hex ID)."""
    if not uid:
        return {"error": "Keine Kontakt-UID angegeben"}

    try:
        status, body = _carddav_request("GET", f"/{uid}", content_type="text/vcard")
        if status == 404:
            return {"error": "Kontakt nicht gefunden"}
        if status != 200:
            return {"error": f"CardDAV-Fehler: HTTP {status}"}

        contact = _parse_vcard(body)
        if not contact:
            return {"error": "Kontakt konnte nicht geparst werden"}

        return {
            "ok": True,
            "contact": {
                "uid": contact.get("uid", ""),
                "name": _sanitize(contact.get("name", "")),
                "phones": [_sanitize(p) for p in contact.get("phones", [])],
                "emails": [_sanitize(e) for e in contact.get("emails", [])],
                "org": _sanitize(contact.get("org", "")),
                "note": _sanitize(contact.get("note", "")),
            },
        }
    except Exception as e:
        return {"error": f"Kontakt-Fehler: {e}"}


def create_contact(
    name: str,
    phone: str = "",
    email: str = "",
    org: str = "",
) -> Dict[str, Any]:
    """Create a new contact via CardDAV PUT."""
    if not name:
        return {"error": "Kein Name angegeben"}

    slug = uuid.uuid4().hex[:12]

    vcard = "BEGIN:VCARD\r\n"
    vcard += "VERSION:3.0\r\n"
    vcard += f"FN:{_escape_vcard(name)}\r\n"
    vcard += f"N:;{_escape_vcard(name)};;;\r\n"
    vcard += f"UID:frank-{slug}\r\n"
    if phone:
        vcard += f"TEL;TYPE=CELL:{phone}\r\n"
    if email:
        vcard += f"EMAIL:{email}\r\n"
    if org:
        vcard += f"ORG:{_escape_vcard(org)}\r\n"
    vcard += "END:VCARD\r\n"

    try:
        status, body = _carddav_request(
            "PUT", f"/frank-{slug}.vcf",
            body=vcard,
            content_type="text/vcard; charset=utf-8",
            extra_headers={"If-None-Match": "*"},
        )
        if status in (201, 204):
            LOG.info(f"Contact created: {name}")
            # Google assigns its own UID; find it via search
            sr = search_contacts(name)
            server_uid = ""
            if sr.get("ok"):
                for c in sr.get("contacts", []):
                    if c.get("name") == name:
                        server_uid = c.get("uid", "")
                        break
            return {"ok": True, "uid": server_uid or f"frank-{slug}", "name": name}
        else:
            return {"error": f"CardDAV PUT fehlgeschlagen: HTTP {status}"}
    except Exception as e:
        return {"error": f"Kontakt-Erstellung fehlgeschlagen: {e}"}


def delete_contact(uid: str) -> Dict[str, Any]:
    """Delete a contact by UID (Google's server-assigned hex ID)."""
    if not uid:
        return {"error": "Keine Kontakt-UID angegeben"}

    try:
        status, body = _carddav_request("DELETE", f"/{uid}")
        if status == 204:
            LOG.info(f"Contact deleted: {uid}")
            return {"ok": True, "deleted": uid}
        elif status == 404:
            return {"error": "Kontakt nicht gefunden"}
        else:
            return {"error": f"CardDAV DELETE fehlgeschlagen: HTTP {status}"}
    except Exception as e:
        return {"error": f"Loeschen fehlgeschlagen: {e}"}


# ── CLI test ──────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    print("=== Contact Reader Test ===\n")

    token = _get_access_token()
    print(f"Access token: {'OK' if token else 'FAIL'}")
    user = _get_user_email()
    print(f"User: {user}\n")

    if not token:
        print("ERROR: No access token!")
        exit(1)

    # Test 1: List contacts
    print("--- All Contacts ---")
    result = list_contacts()
    if result.get("ok"):
        for c in result["contacts"]:
            phones = ", ".join(c.get("phones", []))
            emails = ", ".join(c.get("emails", []))
            print(f"  {c['name']} [uid={c['uid']}]: {phones or emails or '(keine Daten)'}")
        print(f"Total: {result['count']}")
    else:
        print(f"  Error: {result.get('error')}")

    # Test 2: Search
    print("\n--- Search 'Mama' ---")
    result = search_contacts("Mama")
    if result.get("ok"):
        print(f"  Found: {result['count']}")
        for c in result["contacts"]:
            print(f"  {c['name']}: {', '.join(c.get('phones', []) + c.get('emails', []))}")
    else:
        print(f"  Error: {result.get('error')}")

    # Test 3: Create + search + delete
    print("\n--- Create/Delete Test ---")
    cr = create_contact("Frank Test-Kontakt", phone="+43 123 456 789")
    if cr.get("ok"):
        uid = cr["uid"]
        print(f"  Created: {cr['name']} (UID: {uid})")

        # Verify via search
        sr = search_contacts("Frank Test")
        found = sr.get("count", 0)
        print(f"  Found in search: {found > 0} ({found})")

        # Delete using the server-assigned UID
        if uid:
            dr = delete_contact(uid)
            print(f"  Deleted: {dr.get('ok', False)}")
        else:
            print("  Skipping delete (no UID)")
    else:
        print(f"  Create failed: {cr.get('error')}")

    print("\n=== Test Complete ===")
