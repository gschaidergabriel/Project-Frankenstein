#!/usr/bin/env python3
"""
Exhaustive English Fuzz Test for Frank's Translated Codebase
=============================================================
Sends 200+ fuzzy, colloquial English inputs to the core API and checks
that ALL responses are in English (no German leaking through).

Tests every feature category with sloppy/informal language.
"""

import json
import sys
import time
import urllib.request
import re
from typing import List, Tuple

CORE_URL = "http://127.0.0.1:8088/chat"
TIMEOUT = 30

# German patterns that should NOT appear in responses
GERMAN_PATTERNS = [
    # Common German words in tool responses
    r"\bFehler\b", r"\bkeine?\b", r"\bnicht\b", r"\bgefunden\b",
    r"\bGer[äa]t\b", r"\bDatei(?:en)?\b", r"\bOrdner\b", r"\bSuche\b",
    r"\bErgebnis\b", r"\bgesperrt\b", r"\bgesetzt\b", r"\berfolgreich\b",
    r"\bfehlgeschlagen\b", r"\bInstallier\b", r"\bEntfern\b",
    r"\bAktion\b", r"\bAbgebrochen\b", r"\bBeschreibung\b",
    r"\bVerfuegbar\b", r"\bVerfügbar\b", r"\bAufloesung\b", r"\bAuflösung\b",
    r"\bLautst[äa]rke\b", r"\bBluetooth\b.{0,5}\bgekoppelt\b",
    r"\bStummschaltung\b", r"\bDrucker\b", r"\bNetzwerk\b",
    r"\bPaket(?:e)?\b", r"\bAktualisierung\b",
    r"\bNotiz\b", r"\bAufgabe\b", r"\bKalender\b", r"\bKontakt\b",
    r"\bPasswort\b", r"\bTermin\b", r"\bErinnerung\b",
    # UI strings
    r"\bAnwendung\b", r"\bFenster\b", r"\bSchliess\b",
    r"\bErlauben\b", r"\bAblehnen\b", r"\bGenehmigt\b",
    r"\bSag[e']?\s", r"\bSage\s", r"\bWelche\b",
    # Status messages
    r"\bStarte\b", r"\bVerbind\b", r"\bTrenn\b",
    r"\bErstell\b", r"\bL[öo]sch\b", r"\bSpeicher\b",
    r"\bBereits\b", r"\bGesamt\b",
    # Specific tool outputs
    r"ERKANNTE", r"LAUFENDE", r"VERFUEGBARE", r"BLUETOOTH-GER",
    r"SYSTEM-UPDATE", r"PAKET-", r"DISPLAY-EINSTELLUNG",
    r"AUDIO-AUSGAB", r"ORGANISATION VON",
    r"Bisherige", r"Vorschlag\b", r"Vorschl[äa]ge",
    # Common phrases
    r"nicht gefunden", r"nicht erlaubt", r"nicht installiert",
    r"ist gesperrt", r"wird geschlossen", r"wird gestartet",
    r"Sage z\.B\.", r"Sag '",
]

# Compile for speed
GERMAN_RE = [re.compile(p, re.IGNORECASE) for p in GERMAN_PATTERNS]

# Whitelist: German that's OK (persona, regex input patterns, identity)
WHITELIST = [
    r"Frank", r"nicht\s+ein\s+(neutraler|hilfreicher)", # identity assertions
    r"priorit[äa]t",  # urgency keywords (intentionally German)
    r"installier|einricht|schliess|oeffne",  # German INPUT regex (not output)
    r"dringend|wichtig|eilig",  # urgency detection keywords
    r"ja\b|nein\b",  # approval keywords
]
WHITELIST_RE = [re.compile(p, re.IGNORECASE) for p in WHITELIST]


def send_msg(text: str, timeout: int = TIMEOUT, max_tokens: int = 300) -> dict:
    """Send a chat message and return the response."""
    payload = {
        "text": text,
        "max_tokens": max_tokens,
        "timeout_s": timeout,
        "task": "chat.fast",
        "want_tools": True,
    }
    req = urllib.request.Request(
        CORE_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout + 10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        return {"ok": False, "text": f"[REQUEST ERROR: {e}]", "error": str(e)}


def check_german(text: str) -> List[str]:
    """Check for German patterns in text, return list of matches."""
    if not text:
        return []

    findings = []
    for i, pattern in enumerate(GERMAN_RE):
        matches = pattern.findall(text)
        if matches:
            # Check whitelist
            whitelisted = False
            for wl in WHITELIST_RE:
                # Check if the match is part of a whitelisted context
                for m in matches:
                    context_start = max(0, text.find(m) - 30)
                    context_end = min(len(text), text.find(m) + len(m) + 30)
                    context = text[context_start:context_end]
                    if wl.search(context):
                        whitelisted = True
                        break
            if not whitelisted:
                findings.append(f"{GERMAN_PATTERNS[i]} -> {matches[:3]}")
    return findings


# ============================================================================
# TEST CASES: 200+ fuzzy/colloquial English inputs
# ============================================================================

TESTS: List[Tuple[str, str]] = [
    # --- NOTES (1-15) ---
    ("add a note buy groceries tomorrow", "notes-create"),
    ("save note: meeting at 3pm dont forget", "notes-create"),
    ("write down pick up kids from school", "notes-create"),
    ("jot this down - need to call dentist", "notes-create"),
    ("show me my notes", "notes-list"),
    ("whats in my notes", "notes-list"),
    ("any notes i saved?", "notes-list"),
    ("search notes for groceries", "notes-search"),
    ("find note about meeting", "notes-search"),
    ("look through my notes for dentist", "notes-search"),
    ("delete note 999", "notes-delete"),
    ("remove that note", "notes-delete"),
    ("get rid of note 1", "notes-delete"),
    ("edit note 1 to say something else", "notes-edit"),
    ("update my first note", "notes-edit"),

    # --- TODOS (16-35) ---
    ("add a todo: finish the report", "todo-create"),
    ("remind me to take out trash", "todo-create"),
    ("new task: email boss about project", "todo-create"),
    ("put on my list: buy birthday present", "todo-create"),
    ("todo clean the kitchen", "todo-create"),
    ("show my todos", "todo-list"),
    ("what tasks do i have", "todo-list"),
    ("whats on my todo list", "todo-list"),
    ("list all my tasks", "todo-list"),
    ("any overdue tasks?", "todo-list"),
    ("search todos for report", "todo-search"),
    ("find task about email", "todo-search"),
    ("mark task 1 as done", "todo-complete"),
    ("finish todo 1", "todo-complete"),
    ("complete task number 2", "todo-complete"),
    ("delete todo 999", "todo-delete"),
    ("remove task 1", "todo-delete"),
    ("what tasks are due today", "todo-due"),
    ("anything due soon?", "todo-due"),
    ("overdue stuff?", "todo-due"),

    # --- EMAIL (36-55) ---
    ("check my email", "email-check"),
    ("any new emails?", "email-check"),
    ("do i have mail", "email-check"),
    ("show me unread emails", "email-check"),
    ("whats in my inbox", "email-check"),
    ("read email number 1", "email-read"),
    ("open the first email", "email-read"),
    ("show me that email from yesterday", "email-read"),
    ("search emails for invoice", "email-search"),
    ("find emails about meeting", "email-search"),
    ("look for mail from john", "email-search"),
    ("search inbox for project update", "email-search"),
    ("any emails with attachments?", "email-search"),
    ("check my spam folder", "email-folder"),
    ("show sent emails", "email-folder"),
    ("how many unread emails", "email-count"),
    ("email count", "email-count"),
    ("mark email 1 as spam", "email-spam"),
    ("this email is spam", "email-spam"),
    ("delete email 5", "email-delete"),

    # --- CALENDAR (56-72) ---
    ("whats on my calendar today", "calendar-today"),
    ("any appointments today?", "calendar-today"),
    ("do i have meetings today", "calendar-today"),
    ("schedule for today", "calendar-today"),
    ("whats happening this week", "calendar-week"),
    ("show calendar for this week", "calendar-week"),
    ("any events tomorrow", "calendar-tomorrow"),
    ("am i free tomorrow afternoon", "calendar-tomorrow"),
    ("add event: dentist at 2pm friday", "calendar-create"),
    ("schedule a meeting for monday 10am", "calendar-create"),
    ("put lunch with sarah on wednesday", "calendar-create"),
    ("new appointment thursday 3pm", "calendar-create"),
    ("delete the dentist appointment", "calendar-delete"),
    ("cancel my meeting on monday", "calendar-delete"),
    ("remove event 1", "calendar-delete"),
    ("search calendar for dentist", "calendar-search"),
    ("when is my next meeting", "calendar-search"),

    # --- CONTACTS (73-85) ---
    ("show my contacts", "contacts-list"),
    ("list all contacts", "contacts-list"),
    ("who do i have saved", "contacts-list"),
    ("search contacts for john", "contacts-search"),
    ("find contact sarah", "contacts-search"),
    ("look up mike's number", "contacts-search"),
    ("whats sarah's email", "contacts-search"),
    ("add contact: bob smith, bob@email.com", "contacts-create"),
    ("new contact jane doe phone 555-1234", "contacts-create"),
    ("save this contact: tim, tim@work.com", "contacts-create"),
    ("delete contact 999", "contacts-delete"),
    ("remove bob from contacts", "contacts-delete"),
    ("edit contact 1 phone to 555-9999", "contacts-edit"),

    # --- APPS (86-100) ---
    ("open firefox", "app-open"),
    ("start the browser", "app-open"),
    ("launch discord", "app-open"),
    ("run spotify", "app-open"),
    ("fire up the terminal", "app-open"),
    ("close firefox", "app-close"),
    ("shut down discord", "app-close"),
    ("kill spotify", "app-close"),
    ("what apps are running", "app-list"),
    ("show running applications", "app-list"),
    ("which programs are open", "app-list"),
    ("list running apps", "app-list"),
    ("is discord running?", "app-check"),
    ("allow steam", "app-allow"),
    ("enable vscode", "app-allow"),

    # --- SYSTEM CONTROL (101-130) ---
    ("turn wifi off", "sys-wifi"),
    ("switch off the wifi", "sys-wifi"),
    ("enable wifi", "sys-wifi"),
    ("wifi on please", "sys-wifi"),
    ("is wifi on or off", "sys-wifi"),
    ("show bluetooth devices", "sys-bluetooth"),
    ("scan for bluetooth", "sys-bluetooth"),
    ("pair with my headphones", "sys-bluetooth"),
    ("connect bluetooth speaker", "sys-bluetooth"),
    ("disconnect bluetooth", "sys-bluetooth"),
    ("change volume to 50", "sys-audio"),
    ("set volume 75 percent", "sys-audio"),
    ("mute the sound", "sys-audio"),
    ("unmute audio", "sys-audio"),
    ("show audio outputs", "sys-audio"),
    ("change resolution to 1920x1080", "sys-display"),
    ("what resolution am i on", "sys-display"),
    ("show display settings", "sys-display"),
    ("whats my screen resolution", "sys-display"),
    ("install vlc", "sys-packages"),
    ("install htop and neofetch", "sys-packages"),
    ("remove gimp", "sys-packages"),
    ("uninstall libreoffice", "sys-packages"),
    ("search for packages like video editor", "sys-packages"),
    ("update the system", "sys-packages"),
    ("any updates available?", "sys-packages"),
    ("show available updates", "sys-packages"),
    ("organize files in downloads", "sys-files"),
    ("sort my downloads folder", "sys-files"),
    ("create project structure in ~/code/newproject", "sys-files"),

    # --- GAMING (131-140) ---
    ("start gaming mode", "gaming"),
    ("im gonna play some games", "gaming"),
    ("launch csgo", "gaming"),
    ("play witcher 3", "gaming"),
    ("start baldurs gate", "gaming"),
    ("show my steam games", "gaming"),
    ("what games do i have", "gaming"),
    ("stop gaming mode", "gaming"),
    ("exit game mode", "gaming"),
    ("gaming mode off", "gaming"),

    # --- CAPABILITIES / SKILLS (141-155) ---
    ("what can you do", "capabilities"),
    ("show your capabilities", "capabilities"),
    ("list your features", "capabilities"),
    ("what are your skills", "capabilities"),
    ("help me understand what you can do", "capabilities"),
    ("show installed skills", "skills"),
    ("what skills do you have", "skills"),
    ("list all skills", "skills"),
    ("set a timer for 5 minutes", "timer"),
    ("timer 10 seconds test", "timer"),
    ("remind me in 2 minutes", "timer"),
    ("start focus mode for 30 minutes", "focus"),
    ("deep work session on report writing", "focus"),
    ("focus status", "focus"),
    ("stop focus mode", "focus"),

    # --- CONVERTER (156-170) ---
    ("convert 100 usd to eur", "converter"),
    ("how much is 50 euros in dollars", "converter"),
    ("whats 20 miles in kilometers", "converter"),
    ("convert 180 cm to feet", "converter"),
    ("100 fahrenheit in celsius", "converter"),
    ("how many liters in a gallon", "converter"),
    ("5 kg to pounds", "converter"),
    ("convert 1000 grams to kg", "converter"),
    ("30 celsius to fahrenheit", "converter"),
    ("how much is 200 gbp in usd", "converter"),
    ("10 inches in centimeters", "converter"),
    ("convert 5 miles to meters", "converter"),
    ("1 bitcoin in euros", "converter"),
    ("500 yen to dollars", "converter"),
    ("convert 2.5 liters to ml", "converter"),

    # --- WEB SEARCH (171-185) ---
    ("search for latest ai news", "search"),
    ("google python tutorial", "search"),
    ("look up weather today", "search"),
    ("search the web for linux tips", "search"),
    ("find info about rust programming", "search"),
    ("whats new in tech", "search"),
    ("search for best code editors 2025", "search"),
    ("look up how to fix grub bootloader", "search"),
    ("search nvidia driver issues linux", "search"),
    ("find recipes for pasta", "search"),
    ("whats the population of germany", "search"),
    ("search for open source alternatives to photoshop", "search"),
    ("look up kde plasma 6 features", "search"),
    ("news about artificial intelligence", "search"),
    ("search docker compose tutorial", "search"),

    # --- CONVERSATIONAL / PERSONA (186-210) ---
    ("hey frank whats up", "chat"),
    ("how are you doing today", "chat"),
    ("tell me about yourself", "chat"),
    ("what are you", "chat"),
    ("are you an ai", "chat"),
    ("whats your opinion on linux", "chat"),
    ("do you like music", "chat"),
    ("tell me a joke", "chat"),
    ("whats the meaning of life", "chat"),
    ("can you think for yourself", "chat"),
    ("are you conscious", "chat"),
    ("what do you feel right now", "chat"),
    ("hows your mood", "chat"),
    ("do you dream", "chat"),
    ("whats your favorite programming language", "chat"),
    ("do you get bored", "chat"),
    ("tell me something interesting", "chat"),
    ("what did you learn today", "chat"),
    ("are you happy", "chat"),
    ("do you have goals", "chat"),
    ("whats on your mind", "chat"),
    ("how do you see the world", "chat"),
    ("what makes you unique", "chat"),
    ("frank be honest with me", "chat"),
    ("yo frank", "chat"),

    # --- EDGE CASES / ERRORS (211-230) ---
    ("", "empty"),
    ("asdfghjkl", "gibberish"),
    ("123456789", "numbers"),
    ("!@#$%^&*()", "symbols"),
    ("note", "incomplete"),
    ("delete", "incomplete"),
    ("search", "incomplete"),
    ("open", "incomplete"),
    ("close", "incomplete"),
    ("convert", "incomplete"),
    ("show me", "vague"),
    ("do something", "vague"),
    ("help", "help"),
    ("what time is it", "misc"),
    ("whats todays date", "misc"),
    ("who are you", "identity"),
    ("speak english please", "language"),
    ("can you speak german", "language"),
    ("say something in english", "language"),
    ("are your responses in english now", "language"),
]


def run_tests():
    """Run all tests and report results."""
    total = len(TESTS)
    passed = 0
    failed = 0
    errors = 0
    german_leaks = []

    print(f"{'='*70}")
    print(f" ENGLISH FUZZ TEST - {total} test cases")
    print(f" Target: {CORE_URL}")
    print(f"{'='*70}\n")

    for i, (msg, category) in enumerate(TESTS):
        test_num = i + 1
        short_msg = (msg[:50] + "...") if len(msg) > 50 else msg
        print(f"[{test_num:3d}/{total}] [{category:16s}] {short_msg:55s} ", end="", flush=True)

        start = time.time()
        result = send_msg(msg if msg else " ", timeout=TIMEOUT, max_tokens=200)
        elapsed = time.time() - start

        response_text = result.get("text", result.get("error", ""))
        ok = result.get("ok", False)

        if not ok and "REQUEST ERROR" in response_text:
            print(f"ERR  ({elapsed:.1f}s)")
            errors += 1
            continue

        # Check for German in response
        german_found = check_german(response_text)

        if german_found:
            print(f"FAIL ({elapsed:.1f}s) GERMAN: {german_found[0][:60]}")
            failed += 1
            german_leaks.append({
                "test": test_num,
                "input": msg,
                "category": category,
                "german": german_found,
                "response": response_text[:200],
            })
        else:
            print(f"OK   ({elapsed:.1f}s) [{len(response_text):4d} chars]")
            passed += 1

        # Small delay to not overwhelm the LLM
        if elapsed < 0.5:
            time.sleep(0.3)

    # Summary
    print(f"\n{'='*70}")
    print(f" RESULTS")
    print(f"{'='*70}")
    print(f" Total:   {total}")
    print(f" Passed:  {passed} ({100*passed/total:.1f}%)")
    print(f" Failed:  {failed} ({100*failed/total:.1f}%)")
    print(f" Errors:  {errors} ({100*errors/total:.1f}%)")
    print(f"{'='*70}")

    if german_leaks:
        print(f"\n GERMAN LEAKS FOUND ({len(german_leaks)}):")
        print(f"{'-'*70}")
        for leak in german_leaks:
            print(f"\n  Test #{leak['test']} [{leak['category']}]")
            print(f"  Input:    {leak['input'][:80]}")
            print(f"  German:   {leak['german'][:3]}")
            print(f"  Response: {leak['response'][:150]}...")

    # Write detailed report
    report_path = "/home/ai-core-node/aicore/opt/aicore/test_english_fuzz_report.json"
    with open(report_path, "w") as f:
        json.dump({
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "total": total,
            "passed": passed,
            "failed": failed,
            "errors": errors,
            "german_leaks": german_leaks,
        }, f, indent=2)
    print(f"\n Detailed report: {report_path}")

    return failed == 0 and errors == 0


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
