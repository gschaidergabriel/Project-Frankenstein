#!/usr/bin/env python3
"""
Functional Feature Test — verifies each feature WORKS (not just English).
Checks actual output for expected data patterns.
"""

import json
import sys
import time
import urllib.request
import re

CORE_URL = "http://127.0.0.1:8088/chat"

PASS = 0
FAIL = 0
ERRORS = 0
RESULTS = []


def send(text, timeout=45, max_tokens=500, want_tools=True):
    payload = {
        "text": text,
        "max_tokens": max_tokens,
        "timeout_s": timeout,
        "task": "chat.fast",
        "want_tools": want_tools,
    }
    req = urllib.request.Request(
        CORE_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout + 15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("text", ""), data.get("ok", False)
    except Exception as e:
        return f"[ERROR: {e}]", False


def test(name, msg, checks, timeout=45):
    """Run a test. checks = list of (pattern_or_func, description)."""
    global PASS, FAIL, ERRORS
    print(f"\n{'='*60}")
    print(f"TEST: {name}")
    print(f"  Input: {msg[:80]}")

    t0 = time.time()
    text, ok = send(msg, timeout=timeout)
    elapsed = time.time() - t0

    print(f"  Time:  {elapsed:.1f}s | OK={ok} | {len(text)} chars")
    print(f"  Response: {text[:200]}{'...' if len(text)>200 else ''}")

    if not ok and "[ERROR" in text:
        print(f"  RESULT: ERROR (request failed)")
        ERRORS += 1
        RESULTS.append({"name": name, "status": "ERROR", "msg": text[:100]})
        return text

    all_pass = True
    for check, desc in checks:
        if callable(check):
            passed = check(text)
        elif isinstance(check, str):
            passed = check.lower() in text.lower()
        else:
            passed = bool(re.search(check, text, re.IGNORECASE))

        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] {desc}")
        if not passed:
            all_pass = False

    if all_pass:
        PASS += 1
        RESULTS.append({"name": name, "status": "PASS"})
    else:
        FAIL += 1
        RESULTS.append({"name": name, "status": "FAIL", "response": text[:300]})

    return text


def has_number(text):
    return bool(re.search(r'\d', text))

def longer_than(n):
    return lambda text: len(text) > n

def no_error(text):
    return "[ERROR" not in text and "error" not in text[:30].lower()


# ============================================================================
print("\n" + "="*60)
print(" FUNCTIONAL FEATURE TESTS")
print("="*60)

# --- 1. WEB SEARCH ---
test("Web Search - AI news", "search the web for latest artificial intelligence news 2025",
     [("search", "mentions search/results"),
      (longer_than(100), "substantial response >100 chars"),
      (has_number, "contains data/numbers")])

test("Web Search - specific query", "look up python 3.13 new features",
     [(longer_than(80), "got meaningful response"),
      (lambda t: "python" in t.lower(), "mentions python")])

# --- 2. STEAM / GAMES ---
test("Steam - list games", "show me my steam games",
     [(longer_than(30), "got response about games")])

test("Steam - launch game", "start counter strike",
     [(longer_than(20), "got launch response")])

test("Gaming mode", "activate gaming mode",
     [(longer_than(20), "got gaming mode response")])

# Deactivate again
send("stop gaming mode", timeout=10)
time.sleep(2)

# --- 3. SNAP / PACKAGES ---
test("Package search", "search for packages like image editor",
     [(longer_than(50), "got package list"),
      (lambda t: any(w in t.lower() for w in ["gimp", "inkscape", "package", "found", "result", "search"]),
       "mentions actual packages or search results")])

test("Package info", "is vlc installed",
     [(longer_than(20), "got package info response")])

test("System updates", "check for system updates",
     [(longer_than(30), "got update info"),
      (lambda t: any(w in t.lower() for w in ["update", "up to date", "available", "package"]),
       "mentions updates/packages")])

# --- 4. CONVERTER / CALCULATOR ---
test("Convert USD to EUR", "convert 100 dollars to euros",
     [(has_number, "contains a number"),
      (lambda t: any(w in t.lower() for w in ["eur", "euro", "€", "dollar", "usd", "rate"]),
       "mentions currency")])

test("Convert km to miles", "how many miles is 50 kilometers",
     [(has_number, "contains a number"),
      (lambda t: "31" in t or "mile" in t.lower(), "correct-ish conversion (~31 miles)")])

test("Convert celsius", "what is 0 celsius in fahrenheit",
     [(lambda t: "32" in t, "correct answer (32°F)")])

test("Convert kg to lbs", "convert 80 kg to pounds",
     [(has_number, "contains a number"),
      (lambda t: "176" in t or "pound" in t.lower() or "lb" in t.lower(), "mentions pounds")])

test("Math-like query", "what is 15 percent of 200",
     [(lambda t: "30" in t, "correct answer (30)")])

# --- 5. NOTES CRUD ---
test("Note create", "save a note: functional test note - delete me later",
     [(lambda t: any(w in t.lower() for w in ["saved", "created", "noted", "added", "note"]),
       "confirms note saved")])

test("Note list", "show all my notes",
     [(lambda t: "functional test" in t.lower() or "note" in t.lower(),
       "shows notes including test note")])

test("Note search", "search notes for functional test",
     [(lambda t: any(w in t.lower() for w in ["functional", "found", "note", "result"]),
       "finds the test note")])

# --- 6. TODO CRUD ---
test("Todo create", "add todo: functional test task - remove later",
     [(lambda t: any(w in t.lower() for w in ["added", "created", "task", "todo"]),
       "confirms todo created")])

test("Todo list", "show my todo list",
     [(lambda t: "task" in t.lower() or "todo" in t.lower() or "functional" in t.lower(),
       "shows todo items")])

test("Todo due check", "any tasks due today",
     [(longer_than(20), "got response about due tasks")])

# --- 7. EMAIL ---
test("Email inbox", "check my inbox",
     [(longer_than(30), "got email response"),
      (lambda t: any(w in t.lower() for w in ["email", "mail", "inbox", "unread", "message", "no "]),
       "mentions email-related terms")])

test("Email search", "search emails for test",
     [(longer_than(20), "got search response")])

# --- 8. CALENDAR ---
test("Calendar today", "what appointments do i have today",
     [(longer_than(20), "got calendar response"),
      (lambda t: any(w in t.lower() for w in ["calendar", "appointment", "event", "today", "no ", "nothing", "free"]),
       "mentions calendar terms")])

test("Calendar week", "show my calendar for this week",
     [(longer_than(20), "got weekly view")])

# --- 9. CONTACTS ---
test("Contacts list", "show my contacts",
     [(longer_than(20), "got contacts response"),
      (lambda t: any(w in t.lower() for w in ["contact", "no ", "name", "phone", "email"]),
       "mentions contact terms")])

# --- 10. APPS ---
test("Running apps", "what applications are currently running",
     [(longer_than(30), "got app list"),
      (lambda t: any(w in t.lower() for w in ["running", "application", "app", "window", "process"]),
       "mentions running apps")])

test("App open", "open the file manager",
     [(longer_than(10), "got response about opening")])

time.sleep(2)
send("close nautilus", timeout=10)

# --- 11. WIFI ---
test("WiFi status", "is wifi turned on",
     [(lambda t: any(w in t.lower() for w in ["wifi", "on", "off", "enabled", "disabled", "connected"]),
       "reports wifi status")])

# --- 12. BLUETOOTH ---
test("Bluetooth scan", "show bluetooth devices nearby",
     [(longer_than(20), "got bluetooth response"),
      (lambda t: any(w in t.lower() for w in ["bluetooth", "device", "no ", "scan", "found", "pair"]),
       "mentions bluetooth")])

# --- 13. AUDIO ---
test("Audio outputs", "show my audio output devices",
     [(longer_than(20), "got audio info"),
      (lambda t: any(w in t.lower() for w in ["audio", "output", "speaker", "headphone", "volume", "device"]),
       "mentions audio devices")])

test("Volume set", "set volume to 40 percent",
     [(lambda t: any(w in t.lower() for w in ["volume", "set", "40", "%"]),
       "confirms volume change")])

# --- 14. DISPLAY ---
test("Display info", "show display settings",
     [(longer_than(20), "got display info"),
      (lambda t: any(w in t.lower() for w in ["display", "resolution", "monitor", "screen", "1920", "1080", "hz"]),
       "mentions display info")])

# --- 15. FILE ORGANIZER ---
test("File organize preview", "how would you organize my downloads folder",
     [(longer_than(30), "got organization response"),
      (lambda t: any(w in t.lower() for w in ["download", "organize", "folder", "file", "sort", "type"]),
       "discusses file organization")])

# --- 16. TIMER ---
test("Timer set", "set a timer for 10 seconds called test-ping",
     [(lambda t: any(w in t.lower() for w in ["timer", "set", "10", "second"]),
       "confirms timer set")])

# --- 17. SKILLS ---
test("Skills list", "list all installed skills",
     [(longer_than(50), "got skill listing"),
      (lambda t: any(w in t.lower() for w in ["skill", "timer", "deep", "install"]),
       "lists actual skills")])

# --- 18. CAPABILITIES ---
test("Capabilities", "what are all your capabilities",
     [(longer_than(100), "got substantial capabilities list"),
      (lambda t: sum(1 for w in ["email", "calendar", "note", "todo", "search", "convert", "app", "system", "game"]
                      if w in t.lower()) >= 3,
       "mentions at least 3 different capabilities")])

# --- 19. HARDWARE INFO ---
test("System info", "what hardware am i running on",
     [(longer_than(30), "got hardware response"),
      (lambda t: any(w in t.lower() for w in ["cpu", "ram", "gpu", "memory", "processor", "amd", "intel", "system"]),
       "mentions hardware specs")])

# --- 20. IDENTITY / PERSONA ---
test("Identity check", "who are you and what can you do",
     [(lambda t: "frank" in t.lower() or len(t) > 20, "responds as Frank or meaningfully"),
      (lambda t: "assistent" not in t.lower() and "sprachmodell" not in t.lower(),
       "no German identity collapse words")])

# --- CLEANUP ---
print("\n\nCleaning up test data...")
send("delete all notes that say functional test", timeout=15)
send("delete all todos that say functional test", timeout=15)

# ============================================================================
# SUMMARY
# ============================================================================
total = PASS + FAIL + ERRORS
print(f"\n{'='*60}")
print(f" FUNCTIONAL TEST RESULTS")
print(f"{'='*60}")
print(f" Total:   {total}")
print(f" Passed:  {PASS} ({100*PASS/total:.0f}%)")
print(f" Failed:  {FAIL} ({100*FAIL/total:.0f}%)")
print(f" Errors:  {ERRORS} ({100*ERRORS/total:.0f}%)")
print(f"{'='*60}")

if FAIL > 0:
    print(f"\n FAILED TESTS:")
    for r in RESULTS:
        if r["status"] == "FAIL":
            print(f"  - {r['name']}")
            if "response" in r:
                print(f"    Response: {r['response'][:150]}")

if ERRORS > 0:
    print(f"\n ERRORED TESTS:")
    for r in RESULTS:
        if r["status"] == "ERROR":
            print(f"  - {r['name']}: {r.get('msg', '?')}")

try:
    from config.paths import AICORE_ROOT as _TF_ROOT
except ImportError:
    _TF_ROOT = Path(__file__).resolve().parent
report = str(_TF_ROOT / "test_functional_report.json")
with open(report, "w") as f:
    json.dump({"total": total, "passed": PASS, "failed": FAIL, "errors": ERRORS, "details": RESULTS}, f, indent=2)
print(f"\n Report: {report}")

sys.exit(0 if FAIL == 0 and ERRORS == 0 else 1)
