"""Command registry for Frank slash-commands.

Each command defines:
  - slash:       The /command trigger (e.g. "/search")
  - label:       Short display name
  - description: One-line description for the palette
  - template:    Text inserted into input (None = execute immediately)
  - icon:        Single emoji for visual cue
  - category:    Grouping for palette display
"""

from dataclasses import dataclass
from typing import Optional, List


@dataclass(frozen=True)
class Command:
    slash: str
    label: str
    description: str
    template: Optional[str]  # None = trigger action directly (e.g. file dialog)
    icon: str = ""
    category: str = "general"
    action: Optional[str] = None  # special action key (e.g. "file_dialog")


COMMANDS: List[Command] = [
    # ── Search & Web ──
    Command("/search",    "Search",          "Web search",                     "search {query}",       icon="S", category="search"),
    Command("/darknet",   "Darknet",         "Darknet / .onion search",        "search darknet {query}", icon="D", category="search"),
    Command("/news",      "News",            "News on a topic",                "news {topic}",         icon="N", category="search"),
    Command("/fetch",     "Fetch URL",       "Fetch & summarize a URL",        "fetch {url}",          icon="F", category="search"),
    Command("/rss",       "RSS Feed",        "Read an RSS feed",               "rss {url}",            icon="R", category="search"),

    # ── Communication ──
    Command("/emails",    "Emails",          "List recent emails",             "list emails",          icon="E", category="comm"),
    Command("/email",     "Read email",      "Read specific email",            "read email {query}",   icon="E", category="comm"),
    Command("/calendar",  "Calendar",        "Today's appointments",           "appointments today",   icon="C", category="comm"),
    Command("/week",      "This week",       "This week's schedule",           "show this week",       icon="W", category="comm"),
    Command("/contacts",  "Contacts",        "List contacts",                  "list contacts",        icon="P", category="comm"),

    # ── Tasks & Notes ──
    Command("/todo",      "Todo",            "Create a reminder/task",         "todo {text}",          icon="T", category="tasks"),
    Command("/todos",     "Todo list",       "Show all todos",                 "list todos",           icon="T", category="tasks"),
    Command("/note",      "Note",            "Save a note",                    "note: {text}",         icon="N", category="tasks"),
    Command("/notes",     "Notes",           "List recent notes",              "list notes",           icon="N", category="tasks"),
    Command("/timer",     "Timer",           "Start a countdown timer",        "timer {minutes} minutes", icon="Z", category="tasks"),
    Command("/deepwork",  "Deep Work",       "Start a focus session",          "deep work start",      icon="B", category="tasks"),

    # ── System ──
    Command("/screenshot","Screenshot",      "Analyze the screen",             "screenshot",           icon="X", category="system"),
    Command("/system",    "System",          "System health status",           "health",               icon="G", category="system"),
    Command("/usb",       "USB",             "List USB devices",               "usb devices",          icon="U", category="system"),
    Command("/print",     "Printer",         "Printer status",                 "printer status",       icon="P", category="system"),
    Command("/qr",        "QR Code",         "Scan or generate QR code",       "scan qr code",         icon="Q", category="system"),
    Command("/network",   "Network",         "Network information",            "wifi info",            icon="W", category="system"),
    Command("/llm",       "LLM",             "Restart the LLM server",         "restart llm",          icon="L", category="system"),

    # ── Apps & Games ──
    Command("/apps",      "Apps",            "List installed apps",            "list apps",            icon="A", category="apps"),
    Command("/open",      "Open app",        "Launch an application",          "open {app}",           icon="O", category="apps"),
    Command("/games",     "Games",           "List Steam games",               "list games",           icon="G", category="apps"),
    Command("/play",      "Play",            "Launch a game",                  "launch {game}",        icon="G", category="apps"),

    # ── Files & Data ──
    Command("/find",      "Find file",       "Search local files",             "search on the system for {query}", icon="F", category="files"),
    Command("/file",      "Attach file",     "Open file picker",               None,                   icon="+", category="files", action="file_dialog"),
    Command("/ls",        "List dir",        "Browse a directory",             "show files in {path}", icon="D", category="files"),
    Command("/clipboard", "Clipboard",       "Clipboard history",              "clipboard list",       icon="C", category="files"),
    Command("/passwords", "Passwords",       "Open password manager",          "password manager",     icon="K", category="files"),

    # ── Productivity ──
    Command("/weather",   "Weather",         "Current weather",                "weather {city}",       icon="W", category="productivity"),
    Command("/skills",    "Skills",          "List available skills",          "skill list",           icon="S", category="productivity"),

    # ── Meta ──
    Command("/health",    "Health",          "Service status check",           "health",               icon="H", category="meta"),
    Command("/features",  "Features",        "What can Frank do?",             "what can you do",      icon="?", category="meta"),
]

# Build lookup dict
_SLASH_MAP = {cmd.slash: cmd for cmd in COMMANDS}


def get_command_by_slash(slash: str) -> Optional[Command]:
    """Look up command by its /slash trigger."""
    return _SLASH_MAP.get(slash)


def filter_commands(query: str) -> List[Command]:
    """Filter commands by fuzzy match on slash, label, or description."""
    if not query:
        return list(COMMANDS)

    q = query.lower().lstrip("/")
    results = []
    for cmd in COMMANDS:
        # Match against slash (without /), label, description
        haystack = f"{cmd.slash[1:]} {cmd.label} {cmd.description}".lower()
        if q in haystack:
            results.append(cmd)

    return results
