#!/usr/bin/env python3
import json
import time
import urllib.request
import urllib.error
import socket
import re
import xml.etree.ElementTree as ET
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, quote_plus, unquote

try:
    import socks as _socks
    _SOCKS_AVAILABLE = True
except ImportError:
    _SOCKS_AVAILABLE = False

HOST = "127.0.0.1"
PORT = 8093

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"

# ----------------------------- utils ----------------------------------------

def now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + "Z"

def json_read(handler):
    n = int(handler.headers.get("Content-Length", "0"))
    raw = handler.rfile.read(n) if n else b"{}"
    try:
        return json.loads(raw.decode("utf-8"))
    except Exception:
        return None

def json_write(handler, code, obj):
    data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    handler.send_response(code)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    try:
        handler.wfile.write(data)
    except (BrokenPipeError, ConnectionResetError):
        pass

def http_get(url, timeout=10):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read().decode("utf-8", errors="replace")

# ----------------------------- HTML parsing ---------------------------------

RE_A = re.compile(r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', re.I | re.S)
RE_SNIP = re.compile(r'<a[^>]+class="result__snippet"[^>]*>(.*?)</a>', re.I | re.S)
RE_TAGS = re.compile(r"<[^>]+>")

def strip_tags(s: str) -> str:
    s = RE_TAGS.sub("", s or "")
    s = s.replace("&nbsp;", " ").replace("&#160;", " ").strip()
    return re.sub(r"\s+", " ", s)

def html_unescape_min(s: str) -> str:
    if not s:
        return s
    s = (s.replace("&amp;", "&")
          .replace("&quot;", "\"")
          .replace("&#39;", "'")
          .replace("&lt;", "<")
          .replace("&gt;", ">"))
    # Decode numeric HTML entities: &#8211; → –, &#x2013; → –, etc.
    s = re.sub(r"&#(\d+);", lambda m: chr(int(m.group(1))), s)
    s = re.sub(r"&#x([0-9a-fA-F]+);", lambda m: chr(int(m.group(1), 16)), s)
    return s

# ----------------------------- URL validation --------------------------------

_DANGEROUS_SCHEMES = frozenset(["javascript", "data", "vbscript", "file"])

def _is_safe_url(url: str) -> bool:
    """
    Validate URL against dangerous schemes (javascript:, data:, etc.)
    Returns True if URL is safe, False if it should be rejected.
    """
    if not url:
        return False
    url_lower = url.strip().lower()
    # Check for dangerous schemes
    for scheme in _DANGEROUS_SCHEMES:
        if url_lower.startswith(scheme + ":"):
            return False
    # Must start with http:// or https://
    if not (url_lower.startswith("http://") or url_lower.startswith("https://")):
        return False
    return True

# ----------------------------- DDG redirect resolver -------------------------

def _double_unquote(s: str) -> str:
    # DDG "uddg" is often percent-encoded; sometimes twice.
    try:
        s1 = unquote(s)
        s2 = unquote(s1)
        return s2
    except Exception:
        return s

def resolve_ddg_redirect(href: str) -> str:
    """
    Converts DuckDuckGo redirect links to direct target URLs.

    Handles:
      - /l/?uddg=...
      - https://duckduckgo.com/l/?uddg=...
      - html entity &amp;
      - double encoding

    Also validates URLs against dangerous schemes (javascript:, data:, etc.)
    """
    href = (href or "").strip()
    href = html_unescape_min(href)

    # Normalize relative DDG links
    if href.startswith("/"):
        href_full = "https://duckduckgo.com" + href
    elif href.startswith("//"):
        href_full = "https:" + href
    else:
        href_full = href

    # Fast-path: manual uddg extraction (most robust)
    if "duckduckgo.com/l/" in href_full and "uddg=" in href_full:
        # extract uddg=... until & or end
        try:
            uddg_part = href_full.split("uddg=", 1)[1]
            uddg_val = uddg_part.split("&", 1)[0]
            uddg_val = html_unescape_min(uddg_val)
            target = _double_unquote(uddg_val).strip()
            if _is_safe_url(target):
                return target
        except Exception:
            pass

    # Fallback: parse_qs
    try:
        u = urlparse(href_full)
        if u.netloc.endswith("duckduckgo.com") and u.path.startswith("/l/"):
            qs = parse_qs(u.query)
            if "uddg" in qs and qs["uddg"]:
                target = qs["uddg"][0]
                target = html_unescape_min(target)
                target = _double_unquote(target).strip()
                if _is_safe_url(target):
                    return target
    except Exception:
        pass

    # Not a DDG redirect; validate and return as-is
    if _is_safe_url(href_full):
        return href_full
    # Unsafe URL - return empty
    return ""

# ----------------------------- Search ----------------------------------------

def ddg_search_html(query: str, limit: int = 5):
    q = (query or "").strip()
    if not q:
        return []

    url = "https://duckduckgo.com/html/?q=" + quote_plus(q)
    status, html = http_get(url, timeout=12)
    if status != 200 or not html:
        return []

    links = RE_A.findall(html)
    snippets = RE_SNIP.findall(html)

    results = []
    for i, (href, title_html) in enumerate(links):
        if len(results) >= limit:
            break

        title = strip_tags(html_unescape_min(title_html))
        direct = resolve_ddg_redirect(href)

        # Skip results with unsafe/empty URLs
        if not direct:
            continue

        snip = ""
        if i < len(snippets):
            snip = strip_tags(html_unescape_min(snippets[i]))

        results.append({
            "title": title or direct,
            "url": direct,
            "snippet": snip,
            "source": "duckduckgo",
        })
    return results

# ----------------------------- URL Fetch (Content Extraction) ----------------

# Block list for private/internal networks
_BLOCKED_HOSTS = re.compile(
    r"^(localhost|127\.|10\.|172\.(1[6-9]|2\d|3[01])\.|192\.168\.|0\.0\.0\.0|::1|\[::1\])",
    re.I,
)

_MAX_FETCH_BYTES = 2 * 1024 * 1024  # 2MB max download

# Tags that usually contain main content
_CONTENT_TAGS_RE = re.compile(
    r"<(article|main|section|div\s+[^>]*(?:content|article|post|entry|body)[^>]*)[\s>]",
    re.I,
)

# Tags to remove entirely (with content)
_REMOVE_TAGS_RE = re.compile(
    r"<(script|style|nav|header|footer|aside|iframe|noscript|svg|form)\b[^>]*>.*?</\1>",
    re.I | re.S,
)

# Block elements that indicate paragraph breaks
_BLOCK_TAGS_RE = re.compile(
    r"</?(?:p|div|br|h[1-6]|li|tr|blockquote|pre|hr)\b[^>]*>",
    re.I,
)


def _extract_text_from_html(html: str, max_chars: int = 15000) -> dict:
    """Extract readable text, title, and description from HTML."""
    result = {"title": "", "description": "", "text": "", "lang": ""}

    if not html:
        return result

    # Extract <title>
    title_match = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
    if title_match:
        result["title"] = strip_tags(html_unescape_min(title_match.group(1))).strip()[:200]

    # Extract meta description
    desc_match = re.search(
        r'<meta\s+[^>]*name=["\']description["\']\s+content=["\']([^"\']*)["\']',
        html, re.I,
    )
    if not desc_match:
        desc_match = re.search(
            r'<meta\s+[^>]*content=["\']([^"\']*)["\'][^>]*name=["\']description["\']',
            html, re.I,
        )
    if desc_match:
        result["description"] = html_unescape_min(desc_match.group(1)).strip()[:500]

    # Extract lang
    lang_match = re.search(r'<html[^>]*\slang=["\']([^"\']+)["\']', html, re.I)
    if lang_match:
        result["lang"] = lang_match.group(1)[:10]

    # Remove script/style/nav etc.
    cleaned = _REMOVE_TAGS_RE.sub(" ", html)

    # Replace block-level tags with newlines
    cleaned = _BLOCK_TAGS_RE.sub("\n", cleaned)

    # Strip all remaining tags
    text = strip_tags(html_unescape_min(cleaned))

    # Collapse whitespace while preserving paragraph breaks
    lines = []
    for line in text.split("\n"):
        line = re.sub(r"[ \t]+", " ", line).strip()
        if line:
            lines.append(line)

    text = "\n".join(lines)

    # Truncate
    if len(text) > max_chars:
        text = text[:max_chars] + "\n[... Text gekürzt]"

    result["text"] = text
    return result


def fetch_url(url: str, max_chars: int = 15000) -> dict:
    """Fetch URL and extract readable text content."""
    if not _is_safe_url(url):
        return {"ok": False, "error": "unsafe_url", "detail": "URL must be http:// or https://"}

    parsed = urlparse(url)
    if _BLOCKED_HOSTS.match(parsed.hostname or ""):
        return {"ok": False, "error": "blocked_host", "detail": "Cannot fetch from local/private networks"}

    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": UA,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,text/plain;q=0.8,*/*;q=0.7",
                "Accept-Language": "de,en;q=0.9",
            },
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=15) as r:
            content_type = r.headers.get("Content-Type", "")
            # Read limited bytes
            raw = r.read(_MAX_FETCH_BYTES)

        # Determine encoding
        charset = "utf-8"
        ct_match = re.search(r"charset=([^\s;]+)", content_type, re.I)
        if ct_match:
            charset = ct_match.group(1)

        html = raw.decode(charset, errors="replace")

        if "text/plain" in content_type:
            text = html[:max_chars]
            if len(html) > max_chars:
                text += "\n[... Text gekürzt]"
            return {
                "ok": True,
                "ts": now_iso(),
                "url": url,
                "content_type": content_type,
                "title": "",
                "description": "",
                "text": text,
                "chars": len(text),
            }

        extracted = _extract_text_from_html(html, max_chars=max_chars)
        return {
            "ok": True,
            "ts": now_iso(),
            "url": url,
            "content_type": content_type,
            "title": extracted["title"],
            "description": extracted["description"],
            "text": extracted["text"],
            "lang": extracted["lang"],
            "chars": len(extracted["text"]),
        }

    except urllib.error.HTTPError as e:
        return {"ok": False, "error": "http_error", "detail": f"HTTP {e.code}: {e.reason}"}
    except (socket.timeout, TimeoutError):
        return {"ok": False, "error": "timeout", "detail": "Request timed out (15s)"}
    except Exception as e:
        return {"ok": False, "error": "fetch_failed", "detail": str(e)[:500]}


# ----------------------------- RSS/Atom Feed Parser --------------------------

_DEFAULT_RSS_FEEDS = {
    "tech_de": [
        "https://www.heise.de/rss/heise-atom.xml",
        "https://www.golem.de/rss.php?feed=ATOM1.0",
    ],
    "tech_en": [
        "https://feeds.arstechnica.com/arstechnica/index",
        "https://hnrss.org/frontpage",
    ],
    "news_de": [
        "https://www.tagesschau.de/xml/rss2/",
        "https://www.spiegel.de/schlagzeilen/index.rss",
    ],
    "science": [
        "https://www.nature.com/nature.rss",
    ],
    "ai": [
        "https://hnrss.org/newest?q=AI+OR+LLM+OR+GPT",
    ],
}


def _parse_rss_item(item, ns: dict) -> dict:
    """Parse a single RSS/Atom item/entry."""
    result = {"title": "", "link": "", "published": "", "summary": ""}

    # Atom namespace prefix for direct lookup
    _a = "{http://www.w3.org/2005/Atom}"

    # Title: try atom namespace, then plain
    for t in [f"{_a}title", "title"]:
        el = item.find(t)
        if el is not None and el.text:
            result["title"] = el.text.strip()[:200]
            break

    # Link: atom uses href attribute, RSS uses text
    for t in [f"{_a}link", "link"]:
        el = item.find(t)
        if el is not None:
            href = el.get("href", "")
            if href:
                result["link"] = href
                break
            elif el.text:
                result["link"] = el.text.strip()
                break

    # Published date
    for t in [f"{_a}published", f"{_a}updated", "pubDate", "published", "updated"]:
        el = item.find(t)
        if el is not None and el.text:
            result["published"] = el.text.strip()[:50]
            break
    if not result["published"]:
        # Try with namespace prefix for dc:date
        dc_el = item.find("dc:date", ns)
        if dc_el is not None and dc_el.text:
            result["published"] = dc_el.text.strip()[:50]

    # Summary/description
    for t in [f"{_a}summary", f"{_a}content", "description", "summary", "content"]:
        el = item.find(t)
        if el is not None and el.text:
            text = strip_tags(html_unescape_min(el.text))
            result["summary"] = text[:500]
            break

    return result


def parse_rss_feed(url: str, limit: int = 10) -> dict:
    """Fetch and parse an RSS/Atom feed."""
    if not _is_safe_url(url):
        return {"ok": False, "error": "unsafe_url"}

    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Frank-AI-Core/2.0 RSS-Reader",
                "Accept": "application/rss+xml,application/atom+xml,application/xml,text/xml,*/*;q=0.5",
            },
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=12) as r:
            raw = r.read(1024 * 1024)  # 1MB max for feeds

        xml_text = raw.decode("utf-8", errors="replace")

        # Namespace handling
        ns = {
            "atom": "http://www.w3.org/2005/Atom",
            "dc": "http://purl.org/dc/elements/1.1/",
            "content": "http://purl.org/rss/1.0/modules/content/",
        }

        root = ET.fromstring(xml_text)

        feed_title = ""
        items = []

        # Detect RSS vs Atom
        _a = "{http://www.w3.org/2005/Atom}"
        if root.tag.endswith("feed") or root.tag == f"{_a}feed":
            # Atom format
            title_el = root.find(f"{_a}title") or root.find("title")
            if title_el is not None and title_el.text:
                feed_title = title_el.text.strip()
            entries = root.findall(f"{_a}entry") or root.findall("entry")
            for entry in entries[:limit]:
                items.append(_parse_rss_item(entry, ns))
        else:
            # RSS 2.0 format
            channel = root.find("channel")
            if channel is not None:
                title_el = channel.find("title")
                if title_el is not None and title_el.text:
                    feed_title = title_el.text.strip()
                for item in channel.findall("item")[:limit]:
                    items.append(_parse_rss_item(item, ns))

        return {
            "ok": True,
            "ts": now_iso(),
            "url": url,
            "feed_title": feed_title,
            "items": items,
            "count": len(items),
        }

    except ET.ParseError as e:
        return {"ok": False, "error": "xml_parse_error", "detail": str(e)[:200]}
    except urllib.error.HTTPError as e:
        return {"ok": False, "error": "http_error", "detail": f"HTTP {e.code}"}
    except (socket.timeout, TimeoutError):
        return {"ok": False, "error": "timeout", "detail": "Feed timed out (12s)"}
    except Exception as e:
        return {"ok": False, "error": "rss_failed", "detail": str(e)[:500]}


def get_news(category: str = "tech_de", limit: int = 10) -> dict:
    """Get news from pre-configured RSS feeds by category."""
    feeds = _DEFAULT_RSS_FEEDS.get(category)
    if not feeds:
        available = list(_DEFAULT_RSS_FEEDS.keys())
        return {"ok": False, "error": "unknown_category", "available": available}

    all_items = []
    feed_titles = []

    for feed_url in feeds:
        result = parse_rss_feed(feed_url, limit=limit)
        if result.get("ok"):
            all_items.extend(result.get("items", []))
            if result.get("feed_title"):
                feed_titles.append(result["feed_title"])

    # Sort by published date (newest first, best effort)
    all_items.sort(key=lambda x: x.get("published", ""), reverse=True)

    return {
        "ok": True,
        "ts": now_iso(),
        "category": category,
        "feeds": feed_titles,
        "items": all_items[:limit],
        "count": len(all_items[:limit]),
        "available_categories": list(_DEFAULT_RSS_FEEDS.keys()),
    }


# ----------------------------- Darknet search (Ahmia + Torch via Tor) --------

AHMIA_ONION = "juhanurmihxlp77nkq76byazcldy2hlmovfu2epvl5ankdibsot4csyd.onion"
TORCH_ONION = "xmh57jrknzkhv6y3ls3ubitzfqnkrwxhopf5aygthi7d6rplyvk3noyd.onion"
TOR_SOCKS_HOST = "127.0.0.1"
TOR_SOCKS_PORT = 9050

# Torch result regex
_RE_TORCH_RESULT = re.compile(
    r'<td><b><a\s+href="(https?://[a-z2-7]{16,56}\.onion[^"]*)">(.*?)</a></b>'
    r'<br>\s*<small>(.*?)</small>',
    re.DOTALL | re.IGNORECASE,
)

# Ahmia result regex: <li class="result">...<a href="/search/redirect?...redirect_url=http://xxx.onion/...">Title</a>...<p>Snippet</p>
_RE_AHMIA_RESULT = re.compile(
    r'<li\s+class="result">\s*<h4>\s*<a\s+href="[^"]*redirect_url=(https?://[a-z2-7]{16,56}\.onion[^"&]*)[^"]*">\s*(.*?)\s*</a>',
    re.DOTALL | re.IGNORECASE,
)
_RE_AHMIA_SNIPPET = re.compile(
    r'<p>(.*?)</p>',
    re.DOTALL | re.IGNORECASE,
)
# Ahmia anti-bot hidden field
_RE_AHMIA_HIDDEN = re.compile(
    r'<input\s+type="hidden"\s+name="([a-f0-9]+)"\s+value="([a-f0-9]+)"',
    re.IGNORECASE,
)

# Cached Ahmia session token
_ahmia_token: dict = {"name": "", "value": "", "cookies": "", "ts": 0}


def _tor_http_get(host: str, port: int, path: str, timeout: int = 25) -> str:
    """HTTP GET through Tor SOCKS5 proxy to a .onion host."""
    if not _SOCKS_AVAILABLE:
        raise RuntimeError("PySocks not installed (pip install pysocks)")

    s = _socks.socksocket()
    s.set_proxy(_socks.SOCKS5, TOR_SOCKS_HOST, TOR_SOCKS_PORT, rdns=True)
    s.settimeout(timeout)
    try:
        s.connect((host, port))
        request = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}\r\n"
            f"User-Agent: Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36\r\n"
            f"Accept: text/html,*/*\r\n"
            f"Connection: close\r\n"
            f"\r\n"
        ).encode()
        s.sendall(request)

        data = b""
        while True:
            chunk = s.recv(8192)
            if not chunk:
                break
            data += chunk
            if len(data) > 2 * 1024 * 1024:
                break
    finally:
        s.close()

    raw = data.decode("utf-8", errors="replace")
    # Split headers and body
    body_idx = raw.find("\r\n\r\n")
    headers = raw[:body_idx] if body_idx > 0 else ""
    html = raw[body_idx + 4:] if body_idx > 0 else raw
    # Handle chunked transfer encoding
    if "transfer-encoding: chunked" in headers.lower():
        html = re.sub(r"^[0-9a-fA-F]+\r?\n", "", html, flags=re.MULTILINE)
    return html, headers


def _tor_http_get_follow(host: str, port: int, path: str, timeout: int = 25, cookies: str = "") -> str:
    """HTTP GET through Tor with redirect following and cookie support."""
    if not _SOCKS_AVAILABLE:
        raise RuntimeError("PySocks not installed (pip install pysocks)")

    s = _socks.socksocket()
    s.set_proxy(_socks.SOCKS5, TOR_SOCKS_HOST, TOR_SOCKS_PORT, rdns=True)
    s.settimeout(timeout)
    try:
        s.connect((host, port))
        cookie_header = f"Cookie: {cookies}\r\n" if cookies else ""
        request = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}\r\n"
            f"User-Agent: Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36\r\n"
            f"Accept: text/html,*/*\r\n"
            f"{cookie_header}"
            f"Connection: close\r\n"
            f"\r\n"
        ).encode()
        s.sendall(request)

        data = b""
        while True:
            chunk = s.recv(8192)
            if not chunk:
                break
            data += chunk
            if len(data) > 2 * 1024 * 1024:
                break
    finally:
        s.close()

    raw = data.decode("utf-8", errors="replace")
    body_idx = raw.find("\r\n\r\n")
    headers = raw[:body_idx] if body_idx > 0 else ""
    html = raw[body_idx + 4:] if body_idx > 0 else raw

    # Extract cookies
    set_cookies = re.findall(r"Set-Cookie:\s*([^;\r\n]+)", headers, re.IGNORECASE)
    new_cookies = "; ".join(set_cookies) if set_cookies else cookies

    # Follow redirect
    loc = re.search(r"Location:\s*(\S+)", headers, re.IGNORECASE)
    if loc and ("301" in headers[:30] or "302" in headers[:30] or "303" in headers[:30]):
        redir = loc.group(1)
        if redir.startswith("/"):
            return _tor_http_get_follow(host, port, redir, timeout, new_cookies)

    if "transfer-encoding: chunked" in headers.lower():
        html = re.sub(r"^[0-9a-fA-F]+\r?\n", "", html, flags=re.MULTILINE)
    return html, new_cookies


# German → English keyword map for darknet search translation
_DE_EN_KEYWORDS: dict = {
    "tauschbörse": "marketplace exchange trading",
    "tauschbörsen": "marketplace exchange trading",
    "marktplatz": "marketplace market",
    "marktplätze": "marketplace market",
    "handel": "trading commerce",
    "kaufen": "buy purchase",
    "verkaufen": "sell",
    "waffen": "weapons guns firearms",
    "drogen": "drugs narcotics",
    "forum": "forum community",
    "foren": "forum community board",
    "hacking": "hacking exploit",
    "hacken": "hacking exploit tools",
    "werkzeuge": "tools utilities",
    "sicherheit": "security privacy",
    "datenschutz": "privacy anonymous",
    "anonym": "anonymous anonymity",
    "email": "email secure mail",
    "chat": "chat messaging encrypted",
    "nachrichten": "news messages",
    "suchmaschine": "search engine",
    "wiki": "wiki directory index",
    "verzeichnis": "directory index list",
    "links": "links directory hidden services",
    "hosting": "hosting onion service",
    "bücher": "books library ebooks",
    "dokumente": "documents files leaked",
    "leaks": "leaks leaked data",
    "passwörter": "passwords credentials",
    "krypto": "crypto cryptocurrency bitcoin",
    "bitcoin": "bitcoin btc cryptocurrency",
    "geld": "money currency finance",
    "betrug": "fraud scam",
    "fälschung": "counterfeit fake",
    "ausweis": "identity documents ID",
    "wie": "",
    "und": "",
    "oder": "",
    "nach": "",
    "für": "",
    "mit": "",
    "von": "",
    "den": "",
    "die": "",
    "das": "",
    "der": "",
    "ein": "",
    "eine": "",
}


def _translate_query_de_en(query: str) -> str:
    """Translate German darknet query to English keywords using word map."""
    words = query.lower().split()
    en_parts = []
    has_translation = False
    for w in words:
        if w in _DE_EN_KEYWORDS:
            trans = _DE_EN_KEYWORDS[w]
            if trans:  # Skip stop words (empty translation)
                en_parts.append(trans)
                has_translation = True
        else:
            en_parts.append(w)  # Keep unknown words as-is (might be English already)
    if not has_translation:
        return ""  # No German words found, skip translation
    return " ".join(en_parts)


def _ahmia_get_token() -> tuple:
    """Fetch Ahmia homepage to get anti-bot token. Returns (name, value, cookies)."""
    now = time.time()
    if _ahmia_token["name"] and now - _ahmia_token["ts"] < 300:
        return _ahmia_token["name"], _ahmia_token["value"], _ahmia_token["cookies"]

    html, cookies = _tor_http_get_follow(AHMIA_ONION, 80, "/", timeout=20)
    m = _RE_AHMIA_HIDDEN.search(html)
    if not m:
        raise RuntimeError("Ahmia anti-bot token not found")

    _ahmia_token["name"] = m.group(1)
    _ahmia_token["value"] = m.group(2)
    _ahmia_token["cookies"] = cookies
    _ahmia_token["ts"] = now
    return m.group(1), m.group(2), cookies


def _ahmia_search(query: str, limit: int = 10) -> list:
    """Search via Ahmia .onion (primary darknet search)."""
    token_name, token_value, cookies = _ahmia_get_token()
    q = quote_plus(query)
    path = f"/search/?q={q}&{token_name}={token_value}"

    html, _ = _tor_http_get_follow(AHMIA_ONION, 80, path, timeout=30, cookies=cookies)

    # Parse results
    results = []
    # Split by result blocks
    blocks = re.findall(r'<li\s+class="result">(.*?)</li>', html, re.DOTALL)

    for block in blocks:
        if len(results) >= limit:
            break

        # Extract URL from redirect link
        url_m = re.search(r'redirect_url=(https?://[a-z2-7]{16,56}\.onion[^"&]*)', block)
        if not url_m:
            continue
        url = unquote(url_m.group(1))

        # Extract title
        title_m = re.search(r'<a[^>]*>\s*(.*?)\s*</a>', block, re.DOTALL)
        title = strip_tags(html_unescape_min(title_m.group(1))).strip() if title_m else ""

        # Extract snippet (first <p> after the link)
        snip_m = re.search(r'</h4>.*?<p>(.*?)</p>', block, re.DOTALL)
        snippet = strip_tags(html_unescape_min(snip_m.group(1))).strip()[:200] if snip_m else ""

        if not title:
            title = url

        results.append({
            "title": title,
            "snippet": snippet,
            "url": url,
            "source": "ahmia",
        })

    return results


def _torch_fetch_pages(query: str, max_pages: int = 3) -> list:
    """Fetch raw matches from Torch for a single query string."""
    matches = []
    for start in (0, 10, 20)[:max_pages]:
        q = quote_plus(query)
        path = f"/cgi-bin/omega/omega?P={q}&DEFAULTOP=and"
        if start > 0:
            path += f"&STARTDOC={start}"
        try:
            html, _ = _tor_http_get(TORCH_ONION, 80, path, timeout=20)
            page = _RE_TORCH_RESULT.findall(html)
            matches.extend(page)
            if len(page) < 5:
                break
        except Exception:
            if matches:
                break
            raise
        if len(matches) >= 32:
            break
    return matches


def _filter_torch_results(all_matches: list, limit: int) -> list:
    """Deduplicate and filter Torch raw matches into clean results."""
    results = []
    seen_base_urls: set = set()
    seen_titles: set = set()
    domain_counts: dict = {}

    for raw_url, raw_title, raw_snippet in all_matches:
        title = html_unescape_min(strip_tags(raw_title).strip())
        snippet = html_unescape_min(strip_tags(raw_snippet).strip())
        url = html_unescape_min(raw_url)
        if not title or not url:
            continue
        if not re.match(r"https?://[a-z2-7]{56}\.onion", url):
            continue
        # Dedup by base URL (strip query params)
        base_url = url.split("?")[0].rstrip("/")
        if base_url in seen_base_urls:
            continue
        seen_base_urls.add(base_url)
        # Dedup by title (same content on different domains)
        title_key = title.lower().strip()
        if title_key in seen_titles:
            continue
        seen_titles.add(title_key)
        # Max 2 results per .onion domain
        domain_m = re.search(r"(https?://[a-z2-7]{56}\.onion)", url)
        domain = domain_m.group(1) if domain_m else url
        domain_counts[domain] = domain_counts.get(domain, 0) + 1
        if domain_counts[domain] > 2:
            continue
        results.append({
            "title": title,
            "snippet": snippet[:200],
            "url": url,
            "source": "torch",
        })
        if len(results) >= limit:
            break
    return results


def darknet_search(query: str, limit: int = 8) -> list:
    """Search the Tor darknet. Ahmia primary, Torch fallback.

    Strategy: try Ahmia first (most reliable), fall back to Torch,
    then try DE→EN translation if not enough results.
    """
    results = []
    engine = "ahmia"

    # 1. Try Ahmia (primary)
    try:
        results = _ahmia_search(query, limit=limit)
    except Exception:
        pass

    # 2. If Ahmia failed or not enough results, try Torch
    if len(results) < limit:
        try:
            torch_matches = _torch_fetch_pages(query, max_pages=2)
            torch_results = _filter_torch_results(torch_matches, limit)
            if torch_results:
                engine = "torch" if not results else "ahmia+torch"
                seen = {r["url"].split("?")[0].rstrip("/") for r in results}
                for r in torch_results:
                    if r["url"].split("?")[0].rstrip("/") not in seen:
                        results.append(r)
                        if len(results) >= limit:
                            break
        except Exception:
            pass

    # 3. If still not enough, try English translation on whichever engine works
    if len(results) < limit:
        en_query = _translate_query_de_en(query)
        if en_query and en_query.lower() != query.lower():
            try:
                en_results = _ahmia_search(en_query, limit=limit)
                seen = {r["url"].split("?")[0].rstrip("/") for r in results}
                for r in en_results:
                    if r["url"].split("?")[0].rstrip("/") not in seen:
                        results.append(r)
                        if len(results) >= limit:
                            break
            except Exception:
                pass

    return results[:limit], engine


# Keep old name for backward compat
def darknet_search_torch(query: str, limit: int = 8) -> list:
    """Legacy wrapper."""
    results, _ = darknet_search(query, limit)
    return results


# ----------------------------- HTTP server ----------------------------------

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        return

    def do_GET(self):
        if self.path == "/health":
            json_write(self, 200, {"ok": True})
            return
        json_write(self, 404, {"ok": False, "error": "not_found"})

    def do_POST(self):
        payload = json_read(self)
        if payload is None:
            json_write(self, 400, {"ok": False, "error": "invalid_json"})
            return

        if self.path == "/search":
            try:
                query = payload.get("query", "")
                limit = int(payload.get("limit", 5))
                limit = max(1, min(limit, 10))

                res = ddg_search_html(query, limit=limit)
                json_write(self, 200, {
                    "ok": True,
                    "ts": now_iso(),
                    "query": query,
                    "limit": limit,
                    "results": res,
                })
            except urllib.error.HTTPError as e:
                try:
                    body = e.read().decode("utf-8", errors="replace")
                except Exception:
                    body = ""
                json_write(self, 502, {"ok": False, "error": "upstream_http_error", "detail": f"{e}", "body": body[:500]})
            except (socket.timeout, TimeoutError) as e:
                json_write(self, 504, {"ok": False, "error": "upstream_timeout", "detail": repr(e)})
            except Exception as e:
                json_write(self, 500, {"ok": False, "error": "search_failed", "detail": str(e)})
            return

        if self.path == "/fetch":
            try:
                url = payload.get("url", "")
                max_chars = int(payload.get("max_chars", 15000))
                max_chars = max(500, min(max_chars, 50000))

                result = fetch_url(url, max_chars=max_chars)
                code = 200 if result.get("ok") else 400
                json_write(self, code, result)
            except (socket.timeout, TimeoutError) as e:
                json_write(self, 504, {"ok": False, "error": "timeout", "detail": repr(e)})
            except Exception as e:
                json_write(self, 500, {"ok": False, "error": "fetch_failed", "detail": str(e)})
            return

        if self.path == "/rss":
            try:
                url = payload.get("url", "")
                limit = int(payload.get("limit", 10))
                limit = max(1, min(limit, 50))

                result = parse_rss_feed(url, limit=limit)
                code = 200 if result.get("ok") else 400
                json_write(self, code, result)
            except Exception as e:
                json_write(self, 500, {"ok": False, "error": "rss_failed", "detail": str(e)})
            return

        if self.path == "/darknet":
            try:
                query = payload.get("query", "")
                limit = int(payload.get("limit", 8))
                limit = max(1, min(limit, 10))

                res, engine = darknet_search(query, limit=limit)
                json_write(self, 200, {
                    "ok": True,
                    "ts": now_iso(),
                    "query": query,
                    "limit": limit,
                    "results": res,
                    "engine": engine,
                })
            except (socket.timeout, TimeoutError) as e:
                json_write(self, 504, {"ok": False, "error": "tor_timeout", "detail": repr(e)})
            except Exception as e:
                json_write(self, 500, {"ok": False, "error": "darknet_search_failed", "detail": str(e)})
            return

        if self.path == "/news":
            try:
                category = payload.get("category", "tech_de")
                limit = int(payload.get("limit", 10))
                limit = max(1, min(limit, 30))

                result = get_news(category, limit=limit)
                code = 200 if result.get("ok") else 400
                json_write(self, code, result)
            except Exception as e:
                json_write(self, 500, {"ok": False, "error": "news_failed", "detail": str(e)})
            return

        json_write(self, 404, {"ok": False, "error": "not_found"})

def main():
    print(f"webd listening on http://{HOST}:{PORT}", flush=True)
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    httpd.daemon_threads = True
    httpd.serve_forever()

if __name__ == "__main__":
    main()

