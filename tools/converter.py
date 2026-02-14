#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
converter.py – Unit and currency converter for Frank.

Local unit conversion tables + live currency rates via frankfurter.app (ECB).
Stdlib only – no external dependencies.
"""

from __future__ import annotations

import json
import logging
import re
import time
import urllib.request
import urllib.error
from typing import Any, Dict, Optional, Tuple

LOG = logging.getLogger("converter")

# ── Unit conversion tables ────────────────────────────────────────
# Each category maps unit → factor to base unit.
# Conversion: value * (from_factor / to_factor)

_DATA_UNITS = {
    "b":   1,
    "kb":  1000,
    "mb":  1000**2,
    "gb":  1000**3,
    "tb":  1000**4,
    "pb":  1000**5,
    "kib": 1024,
    "mib": 1024**2,
    "gib": 1024**3,
    "tib": 1024**4,
    "pib": 1024**5,
}

_LENGTH_UNITS = {
    "mm":  0.001,
    "cm":  0.01,
    "m":   1.0,
    "km":  1000.0,
    "in":  0.0254,
    "ft":  0.3048,
    "yd":  0.9144,
    "mi":  1609.344,
    "nm":  1852.0,  # nautical mile
}

_WEIGHT_UNITS = {
    "mg":  0.000001,
    "g":   0.001,
    "kg":  1.0,
    "t":   1000.0,
    "oz":  0.0283495,
    "lb":  0.453592,
    "st":  6.35029,
}

_SPEED_UNITS = {
    "m/s":  1.0,
    "km/h": 1 / 3.6,
    "kmh":  1 / 3.6,
    "mph":  0.44704,
    "kn":   0.514444,
}

_VOLUME_UNITS = {
    "ml":    0.001,
    "l":     1.0,
    "m3":    1000.0,
    "gal":   3.78541,
    "qt":    0.946353,
    "pt":    0.473176,
    "fl_oz": 0.0295735,
    "cup":   0.236588,
}

_AREA_UNITS = {
    "mm2":  0.000001,
    "cm2":  0.0001,
    "m2":   1.0,
    "km2":  1000000.0,
    "ha":   10000.0,
    "ac":   4046.86,
    "sqft": 0.092903,
    "sqmi": 2589988.0,
    "sqm":  1.0,
}

_TIME_UNITS = {
    "s":   1.0,
    "sec": 1.0,
    "min": 60.0,
    "h":   3600.0,
    "hr":  3600.0,
    "d":   86400.0,
    "wk":  604800.0,
    "mo":  2592000.0,   # 30 days
    "yr":  31536000.0,  # 365 days
}

# Temperature is special — not a simple ratio
_TEMP_UNITS = {"c", "f", "k"}

# All categories for lookup
_CATEGORIES = [
    ("data", _DATA_UNITS),
    ("length", _LENGTH_UNITS),
    ("weight", _WEIGHT_UNITS),
    ("speed", _SPEED_UNITS),
    ("volume", _VOLUME_UNITS),
    ("area", _AREA_UNITS),
    ("time", _TIME_UNITS),
]

# ── Unit aliases (DE + EN) ───────────────────────────────────────

_ALIASES = {
    # Data
    "byte": "b", "bytes": "b",
    "kilobyte": "kb", "kilobytes": "kb",
    "megabyte": "mb", "megabytes": "mb",
    "gigabyte": "gb", "gigabytes": "gb",
    "terabyte": "tb", "terabytes": "tb",
    "petabyte": "pb", "petabytes": "pb",
    # Length
    "millimeter": "mm", "zentimeter": "cm", "centimeter": "cm",
    "meter": "m", "kilometer": "km", "meile": "mi", "meilen": "mi",
    "inch": "in", "zoll": "in", "fuss": "ft", "fuß": "ft", "fußß": "ft",
    "foot": "ft", "feet": "ft", "yard": "yd", "yards": "yd",
    "mile": "mi", "miles": "mi", "seemeile": "nm", "seemeilen": "nm",
    # Weight
    "milligramm": "mg", "gramm": "g", "kilogramm": "kg", "tonne": "t", "tonnen": "t",
    "unze": "oz", "unzen": "oz", "ounce": "oz", "ounces": "oz",
    "pfund": "lb", "pound": "lb", "pounds": "lb",
    "stone": "st",
    # Temperature
    "celsius": "c", "fahrenheit": "f", "kelvin": "k",
    "°c": "c", "°f": "f", "°k": "k",
    "grad": "c",  # "72 grad" → assume Celsius
    # Speed
    "knoten": "kn", "knot": "kn", "knots": "kn",
    # Volume
    "liter": "l", "milliliter": "ml",
    "gallone": "gal", "gallonen": "gal", "gallon": "gal", "gallons": "gal",
    "quart": "qt", "pint": "pt",
    # Area
    "hektar": "ha", "acre": "ac", "acres": "ac",
    "quadratmeter": "m2", "quadratkilometer": "km2",
    # Time
    "sekunde": "s", "sekunden": "s", "second": "s", "seconds": "s", "sek": "s",
    "minute": "min", "minuten": "min", "minutes": "min",
    "stunde": "h", "stunden": "h", "std": "h", "hour": "h", "hours": "h",
    "tag": "d", "tage": "d", "tagen": "d", "day": "d", "days": "d",
    "woche": "wk", "wochen": "wk", "week": "wk", "weeks": "wk",
    "monat": "mo", "monate": "mo", "month": "mo", "months": "mo",
    "jahr": "yr", "jahre": "yr", "jahren": "yr", "year": "yr", "years": "yr",
    # Currency aliases
    "euro": "eur", "euros": "eur", "€": "eur",
    "dollar": "usd", "dollars": "usd", "$": "usd", "us-dollar": "usd",
    "britische pfund": "gbp", "british pound": "gbp", "£": "gbp", "sterling": "gbp",
    "schweizer franken": "chf", "franken": "chf", "sfr": "chf",
    "yen": "jpy", "¥": "jpy",
    "kanadische dollar": "cad", "australische dollar": "aud",
    "schwedische kronen": "sek_cur", "norwegische kronen": "nok",
    "kronen": "sek_cur",
}

# Known currency codes
_CURRENCIES = {
    "eur", "usd", "gbp", "chf", "jpy", "cad", "aud",
    "sek_cur", "nok", "dkk", "pln", "czk", "huf", "try",
    "cny", "brl", "inr", "krw", "mxn", "zar", "nzd",
    "sgd", "hkd", "thb", "idr", "php", "myr", "ron", "bgn", "isk", "hrk",
}

# ── Currency cache ────────────────────────────────────────────────

_currency_cache: Dict[str, Tuple[float, float]] = {}  # "FROM_TO" → (rate, timestamp)
_CACHE_TTL = 3600  # 1 hour


def _normalize_unit(raw: str) -> str:
    """Normalize a unit string to its canonical form."""
    s = raw.strip().lower().rstrip(".")
    # Remove trailing question mark/punctuation
    s = s.rstrip("?!,;")
    # Check aliases first
    if s in _ALIASES:
        return _ALIASES[s]
    return s


def _find_category(unit: str):
    """Find which category a unit belongs to. Returns (category_name, units_dict) or None."""
    for name, table in _CATEGORIES:
        if unit in table:
            return name, table
    return None


def _is_currency(unit: str) -> bool:
    """Check if a unit is a currency code."""
    # Handle sek_cur vs sek (Swedish Krona vs seconds)
    if unit == "sek_cur":
        return True
    return unit.upper() in {c.upper() for c in _CURRENCIES if c != "sek_cur"}


def _currency_code(unit: str) -> str:
    """Get the API currency code."""
    if unit == "sek_cur":
        return "SEK"
    return unit.upper()


def _convert_temperature(value: float, from_u: str, to_u: str) -> float:
    """Convert between C, F, K."""
    # Normalize to Celsius first
    if from_u == "f":
        c = (value - 32) * 5 / 9
    elif from_u == "k":
        c = value - 273.15
    else:
        c = value

    # Convert from Celsius to target
    if to_u == "f":
        return c * 9 / 5 + 32
    elif to_u == "k":
        return c + 273.15
    return c


# ── Public API ────────────────────────────────────────────────────

def convert_units(value: float, from_unit: str, to_unit: str) -> Dict[str, Any]:
    """Convert between units of the same category."""
    fu = _normalize_unit(from_unit)
    tu = _normalize_unit(to_unit)

    # Temperature special case
    if fu in _TEMP_UNITS and tu in _TEMP_UNITS:
        if fu == tu:
            return {"ok": True, "result": value, "formatted": f"{value} {from_unit}"}
        result = _convert_temperature(value, fu, tu)
        # Format nicely
        unit_labels = {"c": "°C", "f": "°F", "k": "K"}
        fmt = f"{value:g} {unit_labels.get(fu, fu)} = {result:.2f} {unit_labels.get(tu, tu)}"
        return {"ok": True, "result": result, "formatted": fmt}

    # Find categories
    cat_from = _find_category(fu)
    cat_to = _find_category(tu)

    if not cat_from:
        return {"error": f"Unbekannte Einheit: {from_unit}"}
    if not cat_to:
        return {"error": f"Unbekannte Einheit: {to_unit}"}
    if cat_from[0] != cat_to[0]:
        return {"error": f"Kann {from_unit} ({cat_from[0]}) nicht in {to_unit} ({cat_to[0]}) umrechnen"}

    table = cat_from[1]
    from_factor = table[fu]
    to_factor = table[tu]
    result = value * (from_factor / to_factor)

    # Format with appropriate precision
    if result >= 100:
        fmt_val = f"{result:,.2f}"
    elif result >= 1:
        fmt_val = f"{result:.4g}"
    else:
        fmt_val = f"{result:.6g}"

    # Nice unit labels
    fmt = f"{value:g} {from_unit} = {fmt_val} {to_unit}"
    return {"ok": True, "result": result, "formatted": fmt}


def convert_currency(value: float, from_cur: str, to_cur: str) -> Dict[str, Any]:
    """Convert between currencies using frankfurter.app (ECB rates)."""
    fc = _currency_code(_normalize_unit(from_cur))
    tc = _currency_code(_normalize_unit(to_cur))

    if fc == tc:
        return {"ok": True, "result": value, "rate": 1.0, "formatted": f"{value:g} {fc}"}

    cache_key = f"{fc}_{tc}"
    now = time.time()

    # Check cache
    if cache_key in _currency_cache:
        rate, ts = _currency_cache[cache_key]
        if now - ts < _CACHE_TTL:
            result = value * rate
            fmt = f"{value:g} {fc} = {result:,.2f} {tc} (Kurs: {rate:.4f})"
            return {"ok": True, "result": result, "rate": rate, "formatted": fmt}

    # Fetch from API
    try:
        url = f"https://api.frankfurter.app/latest?from={fc}&to={tc}&amount={value}"
        req = urllib.request.Request(url, headers={"User-Agent": "Frank/1.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read())

        rates = data.get("rates", {})
        if tc not in rates:
            return {"error": f"Kein Wechselkurs fuer {fc} → {tc} verfuegbar"}

        result = rates[tc]
        rate = result / value if value else 0

        # Cache the rate
        _currency_cache[cache_key] = (rate, now)

        fmt = f"{value:g} {fc} = {result:,.2f} {tc} (Kurs: {rate:.4f})"
        return {"ok": True, "result": result, "rate": rate, "formatted": fmt}

    except urllib.error.URLError as e:
        LOG.warning(f"Currency API error: {e}")
        return {"error": "Waehrungskurs nicht verfuegbar (Netzwerk-Fehler)"}
    except Exception as e:
        LOG.warning(f"Currency conversion error: {e}")
        return {"error": f"Waehrungsfehler: {e}"}


def parse_conversion(text: str) -> Optional[Tuple[float, str, str]]:
    """Extract (value, from_unit, to_unit) from natural text."""
    # Pattern 1: "150 USD in EUR", "500 MB in GB"
    m = re.search(
        r"(\d+[.,]?\d*)\s*(\S+)\s+(?:in|zu|nach|=)\s+(\S+)",
        text, re.IGNORECASE,
    )
    if m:
        val_str = m.group(1).replace(",", ".")
        try:
            val = float(val_str)
        except ValueError:
            return None
        return val, m.group(2).strip(), m.group(3).strip()

    # Pattern 2: "was sind 150 dollar in euro"
    m = re.search(
        r"(?:was|wieviel|wie\s?viel|rechne|convert)\s+(?:sind|ist)?\s*"
        r"(\d+[.,]?\d*)\s*(\S+(?:\s\S+)?)\s+(?:in|zu|nach)\s+(\S+(?:\s\S+)?)",
        text, re.IGNORECASE,
    )
    if m:
        val_str = m.group(1).replace(",", ".")
        try:
            val = float(val_str)
        except ValueError:
            return None
        return val, m.group(2).strip(), m.group(3).strip()

    return None


def convert(text: str) -> Dict[str, Any]:
    """High-level: parse text and perform conversion."""
    parsed = parse_conversion(text)
    if not parsed:
        return {"error": "Konnte keine Umrechnung aus der Nachricht lesen"}

    value, from_raw, to_raw = parsed
    fu = _normalize_unit(from_raw)
    tu = _normalize_unit(to_raw)

    # Determine if currency or unit
    fu_is_cur = _is_currency(fu) or fu in _CURRENCIES
    tu_is_cur = _is_currency(tu) or tu in _CURRENCIES

    if fu_is_cur and tu_is_cur:
        return convert_currency(value, from_raw, to_raw)
    elif fu_is_cur or tu_is_cur:
        # Mixed — one is currency, other isn't
        return {"error": f"Kann keine Einheit ({from_raw}) in Waehrung ({to_raw}) umrechnen"}
    else:
        return convert_units(value, from_raw, to_raw)


# ── CLI test ──────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    print("=== Converter Test ===\n")

    # Unit conversions
    tests = [
        ("500 MB in GB", convert_units, (500, "MB", "GB")),
        ("1024 MiB in GiB", convert_units, (1024, "MiB", "GiB")),
        ("100 km/h in mph", convert_units, (100, "km/h", "mph")),
        ("72 fahrenheit in celsius", convert_units, (72, "fahrenheit", "celsius")),
        ("0 celsius in fahrenheit", convert_units, (0, "celsius", "fahrenheit")),
        ("100 celsius in kelvin", convert_units, (100, "celsius", "kelvin")),
        ("1 mi in km", convert_units, (1, "mi", "km")),
        ("1 kg in lb", convert_units, (1, "kg", "lb")),
        ("1 liter in gal", convert_units, (1, "liter", "gal")),
        ("3600 sekunden in stunden", convert_units, (3600, "sekunden", "stunden")),
        ("1 ha in m2", convert_units, (1, "ha", "m2")),
    ]

    print("--- Unit conversions ---")
    for label, fn, args in tests:
        r = fn(*args)
        status = "OK" if r.get("ok") else "FAIL"
        print(f"  {status}: {label} → {r.get('formatted', r.get('error'))}")

    # Parse tests
    print("\n--- parse_conversion ---")
    parse_tests = [
        "500 MB in GB",
        "was sind 150 dollar in euro",
        "rechne 100 km/h in mph",
        "72 Fahrenheit in Celsius",
        "wieviel sind 1.5 kg in pfund",
    ]
    for text in parse_tests:
        r = parse_conversion(text)
        print(f"  {text!r} → {r}")

    # High-level convert
    print("\n--- convert() high-level ---")
    hl_tests = [
        "500 MB in GB",
        "100 km/h in mph",
        "72 Fahrenheit in Celsius",
        "1.5 kg in pfund",
        "3600 sekunden in stunden",
    ]
    for text in hl_tests:
        r = convert(text)
        status = "OK" if r.get("ok") else "FAIL"
        print(f"  {status}: {text!r} → {r.get('formatted', r.get('error'))}")

    # Currency (requires network)
    print("\n--- Currency (live) ---")
    r = convert_currency(150, "USD", "EUR")
    print(f"  150 USD → EUR: {r.get('formatted', r.get('error'))}")
    r = convert("100 euro in dollar")
    print(f"  100 EUR → USD: {r.get('formatted', r.get('error'))}")

    print("\n=== Test Complete ===")
