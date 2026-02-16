"""Context-aware suggestion engine.

Analyzes user query + Frank response to offer relevant follow-up actions.
Returns max 2 suggestion chips.
"""

import re
from typing import List, Tuple

# (compiled_regex, suggestion_text, command_to_execute)
_TRIGGERS = [
    (re.compile(r"(wifi|wlan|netzwerk|network|internet|verbindung|connection)", re.I),
     "Network scan?", "network info"),
    (re.compile(r"(usb|stick|festplatte|drive|external|extern)", re.I),
     "USB devices?", "usb storage"),
    (re.compile(r"\b(mails?|emails?|nachricht|inbox)\b", re.I),
     "Check emails?", "list emails"),
    (re.compile(r"(termin|meeting|appointment|kalender|calendar|schedule)", re.I),
     "Calendar today?", "appointments today"),
    (re.compile(r"(screenshot|bildschirm|screen|display|monitor)", re.I),
     "Screenshot?", "screenshot"),
    (re.compile(r"(code|programm|script|bug|debug|python|javascript)", re.I),
     "Attach file?", "/file"),
    (re.compile(r"(musik|song|spotify|playlist|music)", re.I),
     "Open Spotify?", "open spotify"),
    (re.compile(r"(browser|firefox|website|webseite|chrome)", re.I),
     "Open Firefox?", "open firefox"),
    (re.compile(r"(download|heruntergeladen|gespeichert)", re.I),
     "Show Downloads?", "ls ~/Downloads"),
    (re.compile(r"(drucker|printer|drucken|print)", re.I),
     "Printer status?", "print status"),
    (re.compile(r"(passwort|password|login|credentials|kennwort)", re.I),
     "Passwords?", "passwords"),
    (re.compile(r"(timer|countdown|wecker|alarm|stopwatch)", re.I),
     "Set timer?", "timer 5 minutes"),
    (re.compile(r"(todo|aufgabe|task|reminder|erinner)", re.I),
     "Show todos?", "list todos"),
    (re.compile(r"(notiz|note|memo|merken|aufschreiben)", re.I),
     "Show notes?", "list notes"),
    (re.compile(r"(wetter|weather|temperatur|regen|rain|forecast)", re.I),
     "Check weather?", "weather"),
    (re.compile(r"(game|spiel|steam|zocken|gaming)", re.I),
     "List games?", "list games"),
    (re.compile(r"(system|cpu|ram|speicher|memory|disk|festplatte)", re.I),
     "System status?", "system status"),
    (re.compile(r"(qr|barcode|scan)", re.I),
     "QR scan?", "qr scan"),
    (re.compile(r"(kontakt|contact|telefon|phone|anruf)", re.I),
     "List contacts?", "list contacts"),
]


def get_context_suggestions(text: str, exclude_commands: set = None) -> List[Tuple[str, str]]:
    """Return up to 2 context-aware suggestions based on combined text.

    Args:
        text: Combined user query + Frank response
        exclude_commands: Set of command strings to skip (already executed)

    Returns:
        List of (display_text, command) tuples, max 2.
    """
    if not text:
        return []

    exclude = exclude_commands or set()
    results = []
    seen_commands = set()

    for pattern, label, command in _TRIGGERS:
        if command in exclude or command in seen_commands:
            continue
        if pattern.search(text):
            results.append((label, command))
            seen_commands.add(command)
            if len(results) >= 2:
                break

    return results
