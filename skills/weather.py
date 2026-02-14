"""Weather skill — fetch current weather from wttr.in (no API key needed)."""

import json
import urllib.request

SKILL = {
    "name": "weather",
    "description": "Aktuelles Wetter fuer einen Ort abfragen (wttr.in).",
    "version": "1.0",
    "category": "web",
    "risk_level": 0.0,
    "parameters": [
        {
            "name": "location",
            "type": "string",
            "description": "Stadt oder Ort (z.B. Berlin, Munich, Tokyo)",
            "required": False,
            "default": "",
        },
    ],
    "keywords": [
        "wetter", "weather", "temperatur draussen", "wie warm",
        "wie kalt", "regnet es", "schneit es",
    ],
    "timeout_s": 10.0,
}


def run(location: str = "", user_query: str = "", **kwargs) -> dict:
    """Fetch weather from wttr.in."""
    # Try to extract location from user query if not given directly
    if not location and user_query:
        # Simple extraction: look for "in <city>" pattern
        import re
        m = re.search(r"\bin\s+([A-Za-zÄÖÜäöüß\s\-]+?)(?:\?|$|\s*$)", user_query)
        if m:
            location = m.group(1).strip()

    if not location:
        # Auto-detect from system timezone
        try:
            import subprocess as _sp
            _r = _sp.run(["timedatectl", "show", "-p", "Timezone", "--value"],
                         capture_output=True, text=True, timeout=2)
            _tz = _r.stdout.strip()  # e.g. "Europe/Berlin"
            location = _tz.split("/")[-1].replace("_", " ") if "/" in _tz else "Stuttgart"
        except Exception:
            location = "Stuttgart"

    try:
        url = f"https://wttr.in/{urllib.request.quote(location)}?format=j1&lang=de"
        req = urllib.request.Request(url, headers={"User-Agent": "Frank/1.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read())

        conditions = data.get("current_condition", [])
        current = conditions[0] if conditions else {}
        temp_c = current.get("temp_C", "?")
        feels = current.get("FeelsLikeC", "?")
        humidity = current.get("humidity", "?")
        desc_de = current.get("lang_de", [])
        weather_desc = current.get("weatherDesc", [])
        if isinstance(desc_de, list) and desc_de:
            fallback = weather_desc[0].get("value", "?") if weather_desc else "?"
            desc = desc_de[0].get("value", fallback)
        else:
            desc = weather_desc[0].get("value", "?") if weather_desc else "?"
        wind = current.get("windspeedKmph", "?")

        text = (
            f"Wetter in {location}:\n"
            f"  {desc}\n"
            f"  Temperatur: {temp_c}°C (gefuehlt {feels}°C)\n"
            f"  Luftfeuchtigkeit: {humidity}%\n"
            f"  Wind: {wind} km/h"
        )
        return {"ok": True, "output": text}

    except Exception as e:
        return {"ok": False, "error": f"Wetter-Abfrage fehlgeschlagen: {e}"}
