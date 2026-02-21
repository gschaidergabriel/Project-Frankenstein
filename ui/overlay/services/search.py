"""Web search, URL fetching, RSS feeds, and AKAM integration."""

from __future__ import annotations

import re
import webbrowser
from typing import Any, Dict, List, Optional

import subprocess

from overlay.constants import (
    LOG, WEBD_SEARCH_URL, WEBD_FETCH_URL, WEBD_RSS_URL, WEBD_NEWS_URL,
    WEBD_DARKNET_URL, DESKTOP_ACTION_URL, SearchResult,
)
from overlay.http_helpers import _http_get_json, _http_post_json


# ---------- URL opener ----------

def _open_url(url: str) -> None:
    try:
        _http_post_json(DESKTOP_ACTION_URL, {"type": "open_url", "url": url}, timeout_s=4.0)
    except Exception:
        try:
            webbrowser.open(url)
        except Exception:
            pass


def _open_file_in_manager(file_url: str) -> None:
    """Open the system file manager with the file highlighted.

    Uses D-Bus org.freedesktop.FileManager1.ShowItems for proper file
    selection/highlighting. Falls back to xdg-open on the parent directory.
    """
    from pathlib import Path as _P
    path = file_url.replace("file://", "", 1)
    try:
        # D-Bus ShowItems: opens file manager with the file selected
        subprocess.Popen(
            [
                "dbus-send", "--session", "--print-reply",
                "--dest=org.freedesktop.FileManager1",
                "--type=method_call",
                "/org/freedesktop/FileManager1",
                "org.freedesktop.FileManager1.ShowItems",
                f"array:string:file://{path}",
                "string:",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        LOG.info("File manager: ShowItems %s", path[:80])
    except Exception:
        # Fallback: open the parent directory
        try:
            parent = str(_P(path).parent)
            subprocess.Popen(
                ["xdg-open", parent],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception:
            pass


_TOR_OPEN_SCRIPT = str(
    __import__("pathlib").Path(__file__).with_name("tor_open_url.sh")
)


def _open_url_tor(url: str) -> None:
    """Open a URL in Tor Browser via helper shell script.

    The script handles both cases:
    - TB running  → `firefox --new-tab` with correct HOME (new tab)
    - TB not running → `start-tor-browser` (full launch)
    """
    try:
        subprocess.Popen(
            [_TOR_OPEN_SCRIPT, url],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        LOG.info("Tor Browser: %s", url[:60])
    except Exception as e:
        LOG.warning("tor_open_url.sh failed: %s — falling back", e)
        _open_url(url)


# ---------- Darknet search ----------

def _search_darknet(query: str, limit: int = 8) -> List[SearchResult]:
    """Search the darknet via webd /darknet endpoint (Torch via Tor)."""
    try:
        res = _http_post_json(WEBD_DARKNET_URL, {"query": query, "limit": int(limit)}, timeout_s=30.0)
    except Exception:
        return []
    out: List[SearchResult] = []
    if not isinstance(res, dict) or not res.get("ok"):
        return out
    for item in (res.get("results") or [])[:limit]:
        out.append(
            SearchResult(
                title=str(item.get("title", "")),
                snippet=str(item.get("snippet", "")),
                url=str(item.get("url", "")),
                source="darknet",
            )
        )
    return out


# ---------- Web search ----------

def _search_web(query: str, limit: int = 8) -> List[SearchResult]:
    try:
        res = _http_post_json(WEBD_SEARCH_URL, {"query": query, "limit": int(limit)}, timeout_s=12.0)
    except Exception:
        return []
    out: List[SearchResult] = []
    if not isinstance(res, dict) or not res.get("ok"):
        return out
    for item in (res.get("results") or [])[:limit]:
        out.append(
            SearchResult(
                title=str(item.get("title", "")),
                snippet=str(item.get("snippet", "")),
                url=str(item.get("url", "")),
                source=str(item.get("source", "")),
            )
        )
    return out


# =============================================================================
# AKAM INTEGRATION - Auto-search for factual questions
# =============================================================================

# Local knowledge base for common facts (fallback when search fails)
# This prevents hallucination for well-known facts
LOCAL_KNOWLEDGE_BASE = {
    # Schlumpfe / Smurfs
    "schlumpfine": {
        "keywords": ["schlumpfine", "smurfette", "schlumpfinne"],
        "facts": {
            "hut": "Schlumpfines Hut ist weiß.",
            "farbe": "Schlumpfine hat einen weißen Hut, ein weißes Kleid und weiße Schuhe. Sie hat lange blonde Haare.",
            "kleid": "Schlumpfines Kleid ist weiß.",
            "haare": "Schlumpfine hat lange blonde Haare.",
            "aussehen": "Schlumpfine ist ein weiblicher Schlumpf mit blauer Haut, langen blonden Haaren, einem weißen Hut, weißem Kleid und weißen Schuhen.",
        }
    },
    "papa_schlumpf": {
        "keywords": ["papa schlumpf", "papa schlupf", "papaschlumpf", "papaschlupf", "papa smurf", "oberschlumpf", "papa schlumpfs", "papa schlupfs"],
        "facts": {
            "hut": "Papa Schlumpfs Hut (Mütze) ist rot.",
            "mütze": "Papa Schlumpfs Mütze ist rot.",
            "farbe": "Papa Schlumpf trägt eine rote Mütze und eine rote Hose.",
            "bart": "Papa Schlumpf hat einen weißen Bart.",
            "aussehen": "Papa Schlumpf ist der älteste und weiseste Schlumpf. Er hat einen weißen Bart, trägt eine rote Mütze und eine rote Hose.",
        }
    },
    # Normale Schlumpfe
    "schlumpf": {
        "keywords": ["schlumpf ", "schlümpfe", "smurf", "smurfs", "die schlümpfe"],
        "facts": {
            "hut": "Normale Schlümpfe tragen weiße Mützen.",
            "mütze": "Normale Schlümpfe tragen weiße Mützen.",
            "farbe": "Schlümpfe haben blaue Haut und tragen weiße Mützen und weiße Hosen.",
            "aussehen": "Schlümpfe sind kleine blaue Wesen, die weiße Mützen und weiße Hosen tragen. Sie leben in Pilzhäusern im Wald.",
        }
    },
}


def _check_local_knowledge(query: str) -> str:
    """Check local knowledge base for known facts."""
    query_lower = query.lower()

    for topic, data in LOCAL_KNOWLEDGE_BASE.items():
        # Check if any keyword matches
        if any(kw in query_lower for kw in data["keywords"]):
            # Find matching fact
            for fact_key, fact_value in data["facts"].items():
                if fact_key in query_lower or any(word in query_lower for word in fact_key.split("_")):
                    LOG.info(f"Local knowledge match: {topic}.{fact_key}")
                    return f"[Known fact: {fact_value}]"
            # If topic matches but no specific fact, return general info if available
            if "aussehen" in data["facts"]:
                return f"[Known fact: {data['facts']['aussehen']}]"
    return ""


# Pattern to detect factual questions about the world (not about Frank/system)
FACTUAL_QUESTION_RE = re.compile(
    r"(welche farbe|what color|what colour|"
    r"wer ist|wer war|who is|who was|"
    r"was ist|was war|what is|what was|"
    r"wann wurde|wann ist|when did|when was|when is|"
    r"wo ist|wo war|wo liegt|where is|where was|"
    r"wie viele|how many|how much|"
    r"wie heißt|wie hei(ss|ß)t|what.s the name|"
    r"erkläre|explain|"
    r"beschreibe|describe|"
    r"nenne mir|tell me|"
    r"sage mir|sag mir|"
    r"stimmt es|is it true|"
    r"warum ist|why is|why does|why did|"
    r"woher kommt|where does.*come from|"
    r"die farbe von|the color of)",
    re.IGNORECASE
)

# Exclude questions about Frank himself or system status
EXCLUDE_FROM_SEARCH_RE = re.compile(
    r"(wer bist du|was bist du|dein name|wie heißt du|wie alt bist du|"
    r"projekt frankenstein|deine fähigkeiten|was kannst du|"
    r"cpu|ram|speicher|temperatur|system|hardware|software|"
    r"overlay|fenster|display|monitor)",
    re.IGNORECASE
)


def _should_auto_search(msg: str) -> bool:
    """Check if message is a factual question that should trigger auto-search."""
    # Must match factual question pattern
    if not FACTUAL_QUESTION_RE.search(msg):
        return False
    # Must not be about Frank/system
    if EXCLUDE_FROM_SEARCH_RE.search(msg):
        return False
    return True


def _akam_quick_search(query: str) -> str:
    """
    Perform a quick web search and format results for LLM context.
    Returns formatted context string or empty string if no results.
    Uses multiple search strategies for better coverage.
    """
    LOG.debug(f"AKAM quick search for: {query[:50]}...")

    # Extract key search terms from the question
    search_query = re.sub(
        r"^(sage mir|sag mir|tell me|erkläre|explain|beschreibe|describe|"
        r"was ist|what is|wer ist|who is|welche farbe hat|what color is|"
        r"die farbe von|the color of)\s*",
        "", query, flags=re.IGNORECASE
    ).strip()

    if not search_query or len(search_query) < 3:
        search_query = query

    # Multi-query search strategy for better results
    all_results = []
    search_queries = [
        search_query,
        f"{search_query} Wikipedia",
        f"{search_query} Beschreibung Aussehen",
    ]

    for sq in search_queries[:2]:  # Try up to 2 queries
        results = _search_web(sq, limit=4)
        for r in results:
            # Avoid duplicates
            if r.snippet and not any(r.snippet[:50] == existing.snippet[:50] for existing in all_results):
                all_results.append(r)
        if len(all_results) >= 5:
            break

    if not all_results:
        LOG.debug("AKAM: No search results found")
        return ""

    # Format results for LLM context - include more snippets
    ctx_parts = []
    for r in all_results[:5]:  # Top 5 results
        snippet = r.snippet.strip()
        if snippet and len(snippet) > 20:
            # Clean up snippet
            snippet = snippet.replace("\n", " ").strip()
            if len(snippet) > 350:
                snippet = snippet[:350] + "..."
            ctx_parts.append(f"- {snippet}")

    if not ctx_parts:
        return ""

    # CRITICAL: Add instruction for LLM to USE the search results
    context = (
        "[IMPORTANT: Use the following internet search results for your answer. "
        "If the results contain the answer, use these facts. "
        "Do NOT make up information!]\n\n"
        "[Internet search results]\n" + "\n".join(ctx_parts)
    )
    LOG.info(f"AKAM: Injecting search context ({len(context)} chars)")
    return context


# =============================================================================
# URL FETCH - Direct webpage content extraction
# =============================================================================

def _fetch_url(url: str, max_chars: int = 12000) -> Dict[str, Any]:
    """
    Fetch a URL and extract text content via webd /fetch endpoint.

    Returns dict with: ok, title, description, text, chars, url
    """
    LOG.info(f"Fetching URL: {url[:80]}...")
    try:
        result = _http_post_json(
            WEBD_FETCH_URL,
            {"url": url, "max_chars": max_chars},
            timeout_s=20.0,
        )
    except Exception as e:
        LOG.error(f"URL fetch failed: {e}")
        return {"ok": False, "error": str(e)}

    if not isinstance(result, dict):
        return {"ok": False, "error": "Invalid response from webd"}

    return result


def _format_fetched_content(result: Dict[str, Any]) -> str:
    """Format fetched URL content for display in chat."""
    if not result.get("ok"):
        error = result.get("error", "unknown")
        detail = result.get("detail", "")
        return f"Could not retrieve the page: {error} {detail}".strip()

    parts = []
    title = result.get("title", "")
    if title:
        parts.append(f"**{title}**\n")

    desc = result.get("description", "")
    if desc:
        parts.append(f"*{desc}*\n")

    text = result.get("text", "")
    if text:
        # Truncate for display (LLM will get more)
        display_text = text[:3000]
        if len(text) > 3000:
            display_text += f"\n\n[... {result.get('chars', len(text))} characters total]"
        parts.append(display_text)

    if not parts:
        return "Page retrieved, but no readable text found."

    return "\n".join(parts)


def _fetch_url_for_llm(url: str) -> str:
    """Fetch URL and format content for LLM context injection."""
    result = _fetch_url(url, max_chars=8000)
    if not result.get("ok"):
        return ""

    title = result.get("title", "")
    text = result.get("text", "")[:6000]

    context = f"[Webpage content from {url}]\n"
    if title:
        context += f"Title: {title}\n"
    context += f"\n{text}"
    return context


# =============================================================================
# RSS/ATOM FEED READING
# =============================================================================

def _read_rss_feed(url: str, limit: int = 10) -> Dict[str, Any]:
    """Read an RSS/Atom feed via webd /rss endpoint."""
    LOG.info(f"Reading RSS feed: {url[:80]}...")
    try:
        result = _http_post_json(
            WEBD_RSS_URL,
            {"url": url, "limit": limit},
            timeout_s=15.0,
        )
    except Exception as e:
        LOG.error(f"RSS fetch failed: {e}")
        return {"ok": False, "error": str(e)}

    if not isinstance(result, dict):
        return {"ok": False, "error": "Invalid response from webd"}

    return result


def _format_rss_result(result: Dict[str, Any]) -> str:
    """Format RSS feed for chat display."""
    if not result.get("ok"):
        error = result.get("error", "unknown")
        return f"Could not read RSS feed: {error}"

    parts = []
    feed_title = result.get("feed_title", "")
    if feed_title:
        parts.append(f"**{feed_title}**\n")

    items = result.get("items", [])
    if not items:
        return "Feed is empty or contains no entries."

    for i, item in enumerate(items[:15], 1):
        title = item.get("title", "Untitled")
        link = item.get("link", "")
        published = item.get("published", "")
        summary = item.get("summary", "")

        entry = f"**{i}.** {title}"
        if published:
            # Shorten date
            date_short = published[:16] if len(published) > 16 else published
            entry += f" ({date_short})"
        if link:
            entry += f"\n   {link}"
        if summary:
            entry += f"\n   {summary[:150]}"
        parts.append(entry)

    return "\n\n".join(parts)


# =============================================================================
# NEWS - Pre-configured category-based news
# =============================================================================

def _get_news(category: str = "tech_de", limit: int = 10) -> Dict[str, Any]:
    """Get news from pre-configured RSS feeds by category."""
    LOG.info(f"Getting news: category={category}, limit={limit}")
    try:
        result = _http_post_json(
            WEBD_NEWS_URL,
            {"category": category, "limit": limit},
            timeout_s=20.0,
        )
    except Exception as e:
        LOG.error(f"News fetch failed: {e}")
        return {"ok": False, "error": str(e)}

    if not isinstance(result, dict):
        return {"ok": False, "error": "Invalid response from webd"}

    return result


def _format_news_result(result: Dict[str, Any]) -> str:
    """Format news for chat display."""
    if not result.get("ok"):
        error = result.get("error", "unknown")
        available = result.get("available", [])
        msg = f"News could not be loaded: {error}"
        if available:
            msg += f"\n\nAvailable categories: {', '.join(available)}"
        return msg

    return _format_rss_result(result)


def _detect_news_category(msg: str) -> str:
    """Detect news category from user message."""
    msg_lower = msg.lower()

    if any(w in msg_lower for w in ["ai", "ki", "künstliche intelligenz", "artificial intelligence", "llm", "gpt"]):
        return "ai"
    if any(w in msg_lower for w in ["science", "wissenschaft", "forschung"]):
        return "science"
    if any(w in msg_lower for w in ["english", "englisch", "en "]):
        return "tech_en"
    if any(w in msg_lower for w in ["nachrichten", "tagesschau", "spiegel", "deutschland", "politik"]):
        return "news_de"
    # Default
    return "tech_de"
