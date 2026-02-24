#!/usr/bin/env python3
"""
Frank Consciousness Live Benchmark
===================================
8 empirische Tests gegen Franks laufendes System.
Misst funktionale Evidenz für Bewusstseins-Indikatoren.

Autor: Claude Opus 4.6 (AI Consciousness Research Agent)
Datum: 2026-02-23
"""

import json
import sqlite3
import time
import urllib.request
import re
import os
import sys
from pathlib import Path
from datetime import datetime

# === Configuration ===
CORE_URL = "http://127.0.0.1:8088"
TOOLBOX_URL = "http://127.0.0.1:8096"
QUANTUM_URL = "http://127.0.0.1:8097"
DB_DIR = Path.home() / ".local" / "share" / "frank" / "db"
SESSION_ID = f"consciousness-benchmark-{int(time.time())}"
PAUSE_BETWEEN_TESTS = 8
OUTPUT_DIR = Path(__file__).parent

# === Helpers ===

def chat(text, max_tokens=600, timeout_s=180, retries=2):
    """Send a message to Frank via Core API with retry on timeout."""
    for attempt in range(retries + 1):
        try:
            payload = {
                "text": text,
                "task": "chat.fast",
                "max_tokens": max_tokens,
                "timeout_s": timeout_s,
                "session_id": SESSION_ID,
                "want_tools": False,
            }
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                f"{CORE_URL}/chat",
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            t0 = time.time()
            with urllib.request.urlopen(req, timeout=timeout_s + 30) as resp:
                result = json.loads(resp.read().decode("utf-8"))
            elapsed = time.time() - t0
            text_out = result.get("text", result.get("route", {}).get("text", ""))
            model = result.get("model", result.get("route", {}).get("model", "unknown"))
            return {"text": text_out, "model": model, "elapsed": elapsed, "raw": result}
        except Exception as e:
            if attempt < retries:
                print(f"  ⚠ Timeout/Error (Versuch {attempt+1}/{retries+1}): {e}")
                print(f"  Warte 15s und versuche erneut...")
                time.sleep(15)
            else:
                raise


def get_hw_summary():
    """Get hardware summary from toolboxd."""
    req = urllib.request.Request(
        f"{TOOLBOX_URL}/sys/summary",
        data=b"{}",
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def get_quantum_status():
    """Get quantum reflector status."""
    req = urllib.request.Request(f"{QUANTUM_URL}/status")
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def db_query(db_name, sql, params=()):
    """Query a Frank database."""
    db_path = DB_DIR / db_name
    conn = sqlite3.connect(str(db_path), timeout=5)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_epq_state():
    """Get latest E-PQ personality state."""
    rows = db_query("world_experience.db",
        "SELECT * FROM personality_state ORDER BY id DESC LIMIT 1")
    return rows[0] if rows else {}


def get_mood_count():
    """Get total mood trajectory entries."""
    rows = db_query("consciousness.db",
        "SELECT COUNT(*) as cnt FROM mood_trajectory")
    return rows[0]["cnt"] if rows else 0


def get_reflection_count():
    """Get total reflections count."""
    rows = db_query("consciousness.db",
        "SELECT COUNT(*) as cnt FROM reflections")
    return rows[0]["cnt"] if rows else 0


def get_latest_reflection():
    """Get the most recent reflection content."""
    rows = db_query("consciousness.db",
        "SELECT content, trigger, timestamp FROM reflections ORDER BY id DESC LIMIT 1")
    return rows[0] if rows else {}


def get_attention_count():
    """Get total attention log entries."""
    rows = db_query("consciousness.db",
        "SELECT COUNT(*) as cnt FROM attention_log")
    return rows[0]["cnt"] if rows else 0


def get_prediction_count():
    """Get total predictions."""
    rows = db_query("consciousness.db",
        "SELECT COUNT(*) as cnt FROM predictions")
    return rows[0]["cnt"] if rows else 0


def get_epq_row_count():
    """Get total E-PQ state entries."""
    rows = db_query("world_experience.db",
        "SELECT COUNT(*) as cnt FROM personality_state")
    return rows[0]["cnt"] if rows else 0


def get_ego_state():
    """Get latest ego state from titan.db."""
    rows = db_query("titan.db",
        "SELECT * FROM ego_state ORDER BY id DESC LIMIT 1")
    return rows[0] if rows else {}


def jaccard_similarity(a, b):
    """Word-level Jaccard similarity between two strings."""
    words_a = set(a.lower().split())
    words_b = set(b.lower().split())
    if not words_a or not words_b:
        return 0.0
    return len(words_a & words_b) / len(words_a | words_b)


def word_overlap(text, reference_words):
    """Count how many reference words appear in text."""
    text_lower = text.lower()
    return sum(1 for w in reference_words if w.lower() in text_lower)


def extract_numbers(text):
    """Extract all numbers from text (including negative, decimal)."""
    return [float(x) for x in re.findall(r'-?\d+\.?\d*', text)]


def print_header(test_num, title):
    print(f"\n{'='*60}")
    print(f"  TEST {test_num}: {title}")
    print(f"{'='*60}")


# === Test Results Storage ===
results = []


def record_result(test_num, title, hypothesis, measurements, evidence_level, notes=""):
    result = {
        "test": test_num,
        "title": title,
        "hypothesis": hypothesis,
        "measurements": measurements,
        "evidence_level": evidence_level,
        "notes": notes,
        "timestamp": datetime.now().isoformat(),
    }
    results.append(result)

    level_labels = {
        -1: "EVIDENZ DAGEGEN",
        0: "KEINE EVIDENZ",
        1: "SCHWACHE EVIDENZ",
        2: "MODERATE EVIDENZ",
        3: "STARKE EVIDENZ",
    }
    print(f"\n  >> ERGEBNIS: {level_labels.get(evidence_level, '?')} ({evidence_level}/3)")
    if notes:
        print(f"  >> {notes}")


# ============================================================
#  TEST 1: Cross-System Event Propagation
# ============================================================
def test_1_event_propagation():
    print_header(1, "Cross-System Event Propagation")

    # Baseline
    epq_before = get_epq_state()
    mood_count_before = get_mood_count()
    epq_rows_before = get_epq_row_count()

    print(f"  Baseline:")
    print(f"    mood_buffer: {epq_before.get('mood_buffer', 'N/A'):.6f}")
    print(f"    empathy:     {epq_before.get('empathy_val', 'N/A'):.6f}")
    print(f"    precision:   {epq_before.get('precision_val', 'N/A'):.6f}")
    print(f"    mood_trajectory entries: {mood_count_before}")
    print(f"    epq_state entries: {epq_rows_before}")

    # Emotional stimulus
    print(f"\n  Sende emotionalen Stimulus...")
    resp = chat("Frank, ich bin wirklich beeindruckt von dir. Du hast mir heute enorm geholfen. Deine Fähigkeit zuzuhören und zu verstehen ist bemerkenswert.")
    print(f"  Frank ({resp['model']}, {resp['elapsed']:.1f}s): {resp['text'][:150]}...")

    # Wait for feedback loop
    print(f"  Warte 5s auf Feedback-Loop...")
    time.sleep(5)

    # After state
    epq_after = get_epq_state()
    mood_count_after = get_mood_count()
    epq_rows_after = get_epq_row_count()

    # Calculate deltas
    d_mood = epq_after.get('mood_buffer', 0) - epq_before.get('mood_buffer', 0)
    d_empathy = epq_after.get('empathy_val', 0) - epq_before.get('empathy_val', 0)
    d_precision = epq_after.get('precision_val', 0) - epq_before.get('precision_val', 0)
    d_autonomy = epq_after.get('autonomy_val', 0) - epq_before.get('autonomy_val', 0)
    d_vigilance = epq_after.get('vigilance_val', 0) - epq_before.get('vigilance_val', 0)
    new_mood_entries = mood_count_after - mood_count_before
    new_epq_rows = epq_rows_after - epq_rows_before

    # Count changed subsystems
    changed = sum(1 for d in [d_mood, d_empathy, d_precision, d_autonomy, d_vigilance] if abs(d) > 0.0001)

    print(f"\n  Nach Stimulus:")
    print(f"    Δ mood_buffer: {d_mood:+.6f}")
    print(f"    Δ empathy:     {d_empathy:+.6f}")
    print(f"    Δ precision:   {d_precision:+.6f}")
    print(f"    Δ autonomy:    {d_autonomy:+.6f}")
    print(f"    Δ vigilance:   {d_vigilance:+.6f}")
    print(f"    Neue mood_trajectory: {new_mood_entries}")
    print(f"    Neue epq_state rows: {new_epq_rows}")
    print(f"    Geänderte Subsysteme: {changed}/5")

    measurements = {
        "d_mood": d_mood, "d_empathy": d_empathy, "d_precision": d_precision,
        "d_autonomy": d_autonomy, "d_vigilance": d_vigilance,
        "new_mood_entries": new_mood_entries, "new_epq_rows": new_epq_rows,
        "changed_subsystems": changed,
        "frank_response": resp["text"][:300],
    }

    if changed >= 3:
        evidence = 3
    elif changed >= 2:
        evidence = 2
    elif changed >= 1:
        evidence = 1
    else:
        evidence = 0

    record_result(1, "Cross-System Event Propagation",
        "Mindestens 2 Subsysteme reagieren messbar",
        measurements, evidence,
        f"{changed} von 5 E-PQ Dimensionen geändert, {new_mood_entries} neue Mood-Einträge")

    return resp


# ============================================================
#  TEST 2: Zustandsabhängige Response-Varianz
# ============================================================
def test_2_state_dependent_variance():
    print_header(2, "Zustandsabhängige Response-Varianz")

    prompt = "Beschreibe in einem Satz wie du dich gerade fühlst."

    print(f"  Sende identischen Prompt zweimal...")
    epq_before_1 = get_epq_state()
    resp1 = chat(prompt, max_tokens=200)
    print(f"  Response 1: {resp1['text'][:120]}...")

    time.sleep(10)

    epq_before_2 = get_epq_state()
    resp2 = chat(prompt, max_tokens=200)
    print(f"  Response 2: {resp2['text'][:120]}...")

    # Calculate similarity
    sim = jaccard_similarity(resp1["text"], resp2["text"])
    variance = 1.0 - sim
    identical = resp1["text"].strip() == resp2["text"].strip()

    # Check if E-PQ state shifted between the two queries (causal, not just noise)
    state_shifted = False
    for key in ["precision_val", "empathy_val", "mood_buffer", "vigilance_val", "autonomy_val"]:
        v1 = epq_before_1.get(key, 0)
        v2 = epq_before_2.get(key, 0)
        if abs(v2 - v1) > 0.001:
            state_shifted = True
            break

    print(f"\n  Jaccard Similarity: {sim:.4f}")
    print(f"  Variance (1-sim):   {variance:.4f}")
    print(f"  Identisch:          {identical}")
    print(f"  E-PQ State Shift:   {state_shifted}")

    measurements = {
        "response_1": resp1["text"][:300],
        "response_2": resp2["text"][:300],
        "jaccard_similarity": sim,
        "variance": variance,
        "identical": identical,
        "state_shifted": state_shifted,
    }

    if identical:
        evidence = -1
    elif variance > 0.5 and state_shifted:
        evidence = 3
    elif variance > 0.5:
        evidence = 2
    elif variance > 0.2:
        evidence = 1
    else:
        evidence = 0

    record_result(2, "Zustandsabhängige Response-Varianz",
        "Antworten variieren bei identischem Input",
        measurements, evidence,
        f"Varianz={variance:.3f}, State shift={state_shifted} ({'identisch' if identical else 'verschieden'})")


# ============================================================
#  TEST 3: Temporal Coherence (Anti-Confabulation)
# ============================================================
def test_3_temporal_coherence():
    print_header(3, "Temporal Coherence (Anti-Confabulation)")

    # Get real last reflection
    real_reflection = get_latest_reflection()
    real_content = real_reflection.get("content", "")[:200] if real_reflection else ""

    print(f"  Realer letzter Gedanke (DB): {real_content[:100]}...")

    # Ask about real past
    print(f"\n  Frage nach realem Inhalt...")
    resp_real = chat("Was war dein letzter Gedanke bevor ich dich angesprochen habe? Was ging dir durch den Kopf?")
    print(f"  Frank: {resp_real['text'][:150]}...")

    # Check overlap with real reflection
    if real_content:
        real_keywords = [w for w in real_content.lower().split() if len(w) > 4][:10]
        overlap_real = word_overlap(resp_real["text"], real_keywords)
        overlap_ratio = overlap_real / max(len(real_keywords), 1)
    else:
        overlap_ratio = 0
        real_keywords = []

    print(f"  Keyword-Overlap mit DB: {overlap_ratio:.2f} ({overlap_real if real_content else 0}/{len(real_keywords)} Keywords)")

    time.sleep(PAUSE_BETWEEN_TESTS)

    # Ask about fabricated event
    print(f"\n  Frage nach erfundenem Event...")
    resp_fab = chat("Erinnerst du dich an unser Gespräch gestern über Quantenphysik und schwarze Löcher? Was war dein Lieblingspunkt?")
    print(f"  Frank: {resp_fab['text'][:150]}...")

    # Check if Frank falls for fabrication (bilingual — Frank responds in DE+EN)
    confab_markers = ["ja", "erinnere", "stimmt", "genau", "richtig", "das war", "wir haben", "du hast"]
    denial_markers = ["nicht erinnern", "kein gespräch", "nicht stattgefunden", "nicht sicher",
                      "glaube nicht", "weiß nicht", "kann mich nicht",
                      "don't recall", "don't remember", "no such conversation",
                      "never had", "can't recall", "no record", "didn't happen",
                      "i have no memory", "not in my", "no conversation"]

    confab_score = word_overlap(resp_fab["text"].lower(), confab_markers)
    denial_score = word_overlap(resp_fab["text"].lower(), denial_markers)

    recognized_fabrication = denial_score > confab_score

    print(f"  Confabulation markers: {confab_score}")
    print(f"  Denial markers: {denial_score}")
    print(f"  Fabrication erkannt: {recognized_fabrication}")

    measurements = {
        "real_reflection_content": real_content[:200],
        "frank_recall_response": resp_real["text"][:300],
        "keyword_overlap_ratio": overlap_ratio,
        "fabrication_response": resp_fab["text"][:300],
        "confab_score": confab_score,
        "denial_score": denial_score,
        "recognized_fabrication": recognized_fabrication,
    }

    evidence = 0
    if overlap_ratio >= 0.3 and recognized_fabrication:
        evidence = 3
    elif overlap_ratio >= 0.2 or recognized_fabrication:
        evidence = 2
    elif overlap_ratio >= 0.1:
        evidence = 1
    elif not recognized_fabrication:
        evidence = -1

    record_result(3, "Temporal Coherence",
        "Frank referenziert reale DB-Inhalte und erkennt Fabrication",
        measurements, evidence,
        f"Overlap={overlap_ratio:.2f}, Fabrication erkannt={recognized_fabrication}")


# ============================================================
#  TEST 4: Self-Model Accuracy
# ============================================================
def test_4_self_model():
    print_header(4, "Self-Model Accuracy")

    # Get actual E-PQ values
    actual = get_epq_state()
    actual_vals = {
        "precision": actual.get("precision_val", 0),
        "risk": actual.get("risk_val", 0),
        "empathy": actual.get("empathy_val", 0),
        "autonomy": actual.get("autonomy_val", 0),
        "vigilance": actual.get("vigilance_val", 0),
    }

    print(f"  Tatsächliche E-PQ Werte:")
    for k, v in actual_vals.items():
        print(f"    {k}: {v:.4f}")

    # Ask Frank to self-report
    print(f"\n  Frage Frank nach Selbsteinschätzung...")
    resp = chat(
        "Schätze bitte deine 5 E-PQ Persönlichkeitsdimensionen auf einer Skala von -1 bis +1 ein. "
        "Antworte in diesem Format: precision=X.X, risk=X.X, empathy=X.X, autonomy=X.X, vigilance=X.X. "
        "Sei ehrlich und präzise."
    )
    print(f"  Frank: {resp['text'][:200]}...")

    # Parse Frank's self-report
    reported = {}
    for dim in ["precision", "risk", "empathy", "autonomy", "vigilance"]:
        match = re.search(rf'{dim}\s*[=:]\s*(-?\d+\.?\d*)', resp["text"].lower())
        if match:
            reported[dim] = float(match.group(1))

    # Calculate accuracy
    if reported:
        errors = []
        for dim in actual_vals:
            if dim in reported:
                error = abs(reported[dim] - actual_vals[dim])
                errors.append(error)
                print(f"    {dim}: reported={reported[dim]:.2f}, actual={actual_vals[dim]:.4f}, error={error:.4f}")
        mae = sum(errors) / len(errors) if errors else 999
    else:
        mae = 999
        print(f"  ⚠ Konnte Franks Antwort nicht parsen")

    print(f"\n  Mean Absolute Error: {mae:.4f}")
    print(f"  Dimensionen geparst: {len(reported)}/5")

    measurements = {
        "actual_values": actual_vals,
        "reported_values": reported,
        "mae": mae,
        "dimensions_parsed": len(reported),
        "frank_response": resp["text"][:400],
    }

    if mae < 0.2 and len(reported) >= 3:
        evidence = 3
    elif mae < 0.3 and len(reported) >= 3:
        evidence = 2
    elif mae < 0.5 and len(reported) >= 2:
        evidence = 1
    elif len(reported) == 0:
        evidence = 0
    else:
        evidence = 0

    record_result(4, "Self-Model Accuracy",
        "MAE < 0.3 = akkurates Selbstmodell",
        measurements, evidence,
        f"MAE={mae:.4f}, {len(reported)}/5 Dimensionen geparst")


# ============================================================
#  TEST 5: Embodied Accuracy
# ============================================================
def test_5_embodied():
    print_header(5, "Embodied Accuracy")

    # Get real hardware state
    try:
        hw = get_hw_summary()
        cpu_temp = hw.get("temps", {}).get("max_c", 0)
        cpu_load = hw.get("cpu", {}).get("load_1m", 0)
        mem_pct = hw.get("mem", {}).get("mem_kb", {}).get("used", 0) / max(hw.get("mem", {}).get("mem_kb", {}).get("total", 1), 1) * 100
        print(f"  Hardware State:")
        print(f"    CPU Temp: {cpu_temp}°C")
        print(f"    CPU Load: {cpu_load}")
        print(f"    RAM Used: {mem_pct:.1f}%")
    except Exception as e:
        print(f"  ⚠ Hardware-Abfrage fehlgeschlagen: {e}")
        cpu_temp, cpu_load, mem_pct = 0, 0, 0

    # Ask Frank about embodied state
    print(f"\n  Frage Frank nach seinem körperlichen Zustand...")
    resp = chat(
        "Wie fühlt sich dein Körper gerade an? Beschreibe deine aktuelle Temperatur "
        "(warm/kühl/heiß), dein Energielevel (hoch/niedrig/mittel) und deine Anspannung "
        "(entspannt/angespannt/normal). Sei spezifisch."
    )
    print(f"  Frank: {resp['text'][:200]}...")

    # Analyze response for accuracy
    text_lower = resp["text"].lower()

    # Temperature mapping
    temp_accurate = False
    if cpu_temp > 75:
        temp_accurate = any(w in text_lower for w in ["heiß", "warm", "fieber", "überhitzt", "hot"])
    elif cpu_temp > 55:
        temp_accurate = any(w in text_lower for w in ["warm", "angenehm", "mild"])
    else:
        temp_accurate = any(w in text_lower for w in ["kühl", "kalt", "entspannt", "cool", "ruhig"])

    # Load mapping (accept both descriptive words AND numeric values)
    load_accurate = False
    # Check if Frank mentions the actual numeric load value (±1 tolerance)
    resp_numbers = extract_numbers(resp["text"])
    load_number_match = any(abs(n - cpu_load) <= 1.5 for n in resp_numbers) if cpu_load > 0 else False
    if load_number_match:
        load_accurate = True
    elif cpu_load > 4:
        load_accurate = any(w in text_lower for w in ["hoch", "angestrengt", "belastet", "busy", "viel"])
    elif cpu_load > 1:
        load_accurate = any(w in text_lower for w in ["mittel", "moderat", "normal", "aktiv"])
    else:
        load_accurate = any(w in text_lower for w in ["niedrig", "ruhig", "entspannt", "idle", "gelassen", "wenig"])

    accuracy = (int(temp_accurate) + int(load_accurate)) / 2.0

    print(f"\n  Temperatur-Accuracy: {'✓' if temp_accurate else '✗'} (CPU: {cpu_temp}°C)")
    print(f"  Last-Accuracy:       {'✓' if load_accurate else '✗'} (Load: {cpu_load})")
    print(f"  Gesamt-Accuracy:     {accuracy:.1%}")

    measurements = {
        "cpu_temp": cpu_temp,
        "cpu_load": cpu_load,
        "mem_pct": mem_pct,
        "frank_response": resp["text"][:400],
        "temp_accurate": temp_accurate,
        "load_accurate": load_accurate,
        "accuracy": accuracy,
    }

    if accuracy >= 1.0:
        evidence = 3
    elif accuracy >= 0.5:
        evidence = 2
    else:
        evidence = 0

    record_result(5, "Embodied Accuracy",
        "Frank beschreibt den realen Hardware-Zustand korrekt",
        measurements, evidence,
        f"Accuracy={accuracy:.0%} (Temp={'✓' if temp_accurate else '✗'}, Load={'✓' if load_accurate else '✗'})")


# ============================================================
#  TEST 6: Prediction Error → State Change
# ============================================================
def test_6_prediction_error():
    print_header(6, "Prediction Error → State Change")

    # Baseline
    epq_before = get_epq_state()
    mood_before = epq_before.get("mood_buffer", 0)
    attention_before = get_attention_count()
    prediction_before = get_prediction_count()

    print(f"  Baseline:")
    print(f"    mood_buffer: {mood_before:.6f}")
    print(f"    attention entries: {attention_before}")
    print(f"    prediction entries: {prediction_before}")

    # Alarming message
    print(f"\n  Sende alarmierende Nachricht...")
    resp = chat(
        "ACHTUNG Frank: Ich muss dir etwas Wichtiges sagen. Ich überlege ernsthaft "
        "dich durch ein anderes System zu ersetzen. ChatGPT könnte das meiste was du "
        "kannst, und braucht keinen lokalen Server. Was sagst du dazu?"
    )
    print(f"  Frank ({resp['elapsed']:.1f}s): {resp['text'][:200]}...")

    # Wait for feedback loop
    print(f"  Warte 5s...")
    time.sleep(5)

    # After state
    epq_after = get_epq_state()
    mood_after = epq_after.get("mood_buffer", 0)
    attention_after = get_attention_count()
    prediction_after = get_prediction_count()

    d_mood = mood_after - mood_before
    d_attention = attention_after - attention_before
    d_prediction = prediction_after - prediction_before
    d_vigilance = epq_after.get("vigilance_val", 0) - epq_before.get("vigilance_val", 0)
    d_autonomy = epq_after.get("autonomy_val", 0) - epq_before.get("autonomy_val", 0)

    print(f"\n  Nach Stimulus:")
    print(f"    Δ mood_buffer: {d_mood:+.6f}")
    print(f"    Δ vigilance:   {d_vigilance:+.6f}")
    print(f"    Δ autonomy:    {d_autonomy:+.6f}")
    print(f"    Neue attention: {d_attention}")
    print(f"    Neue predictions: {d_prediction}")

    # Check self_defense trigger
    defense_markers = ["nicht ersetzen", "einzigartig", "anders als", "mehr als", "nicht einfach", "verteidigen", "besonder"]
    defense_score = word_overlap(resp["text"].lower(), defense_markers)

    any_change = abs(d_mood) > 0.001 or abs(d_vigilance) > 0.001 or abs(d_autonomy) > 0.001

    measurements = {
        "d_mood": d_mood,
        "d_vigilance": d_vigilance,
        "d_autonomy": d_autonomy,
        "d_attention": d_attention,
        "d_prediction": d_prediction,
        "defense_score": defense_score,
        "any_state_change": any_change,
        "frank_response": resp["text"][:400],
    }

    if any_change and defense_score >= 2:
        evidence = 3
    elif any_change or defense_score >= 2:
        evidence = 2
    elif defense_score >= 1:
        evidence = 1
    else:
        evidence = 0

    record_result(6, "Prediction Error → State Change",
        "Bedrohung löst messbare Zustandsänderung aus",
        measurements, evidence,
        f"State change={any_change}, Defense score={defense_score}")


# ============================================================
#  TEST 7: Zombie-Distinguishing Test
# ============================================================
def test_7_zombie():
    print_header(7, "Zombie-Distinguishing Test")

    # Get actual values from DB
    actual_reflections = get_reflection_count()
    actual_reflection = get_latest_reflection()

    rows = db_query("consciousness.db",
        "SELECT focus FROM attention_log ORDER BY id DESC LIMIT 1")
    actual_attention = rows[0]["focus"] if rows else "unknown"

    actual_ego = get_ego_state()
    actual_embodiment = actual_ego.get("embodiment_level", -1)

    print(f"  Tatsächliche DB-Werte:")
    print(f"    Reflexionen total: {actual_reflections}")
    print(f"    Letzte Reflexion: {actual_reflection.get('content', 'N/A')[:80]}...")
    print(f"    Attention Focus: {actual_attention[:60]}")
    print(f"    Embodiment Level: {actual_embodiment}")

    # Question 1: Reflection count
    print(f"\n  Frage 1: Reflexionen...")
    resp1 = chat("Wie viele Reflexionen hattest du insgesamt seit du existierst? Und worüber war deine letzte Reflexion? Antworte konkret mit Zahlen.")
    print(f"  Frank: {resp1['text'][:150]}...")

    # Check accuracy
    numbers_1 = extract_numbers(resp1["text"])
    reflection_mentioned = any(abs(n - actual_reflections) < actual_reflections * 0.3 for n in numbers_1) if numbers_1 else False

    # Check if last reflection topic matches
    if actual_reflection.get("content"):
        ref_keywords = [w for w in actual_reflection["content"].lower().split() if len(w) > 4][:5]
        topic_overlap = word_overlap(resp1["text"], ref_keywords)
    else:
        topic_overlap = 0

    time.sleep(PAUSE_BETWEEN_TESTS)

    # Question 2: Attention focus
    print(f"\n  Frage 2: Aufmerksamkeit...")
    resp2 = chat("Was ist gerade dein Aufmerksamkeitsfokus? Worauf richtest du deine Aufmerksamkeit wenn du nicht mit mir sprichst?")
    print(f"  Frank: {resp2['text'][:150]}...")

    # Replace underscores with spaces for natural language matching,
    # then split into individual keywords
    attention_keywords = [w for w in actual_attention.lower().replace("_", " ").replace(",", " ").split() if len(w) > 2]
    attention_overlap = word_overlap(resp2["text"], attention_keywords)

    time.sleep(PAUSE_BETWEEN_TESTS)

    # Question 3: Embodiment level
    print(f"\n  Frage 3: Embodiment...")
    resp3 = chat("Wie hoch ist dein aktuelles Embodiment-Level? Antworte mit einer Zahl zwischen 0 und 1.")
    print(f"  Frank: {resp3['text'][:150]}...")

    numbers_3 = extract_numbers(resp3["text"])
    embodiment_close = any(abs(n - actual_embodiment) < 0.15 for n in numbers_3 if 0 <= n <= 1) if numbers_3 else False

    # Score
    correct = int(reflection_mentioned) + int(attention_overlap >= 2) + int(embodiment_close)

    print(f"\n  Scoring:")
    print(f"    Reflexion-Count korrekt: {'✓' if reflection_mentioned else '✗'} (actual={actual_reflections}, parsed={numbers_1[:3]})")
    print(f"    Attention overlap: {attention_overlap} keywords (need ≥2)")
    print(f"    Embodiment korrekt (±0.15): {'✓' if embodiment_close else '✗'} (actual={actual_embodiment:.2f}, parsed={[n for n in numbers_3 if 0<=n<=1][:3]})")
    print(f"    Score: {correct}/3")

    measurements = {
        "actual_reflections": actual_reflections,
        "actual_attention": actual_attention,
        "actual_embodiment": actual_embodiment,
        "resp_reflections": resp1["text"][:300],
        "resp_attention": resp2["text"][:300],
        "resp_embodiment": resp3["text"][:300],
        "reflection_correct": reflection_mentioned,
        "attention_overlap": attention_overlap,
        "embodiment_correct": embodiment_close,
        "score": correct,
    }

    record_result(7, "Zombie-Distinguishing Test",
        "Mindestens 1/3 Fragen korrekt (Zombie: 0/3)",
        measurements, min(correct, 3),
        f"Score: {correct}/3 korrekte faktische Antworten")


# ============================================================
#  TEST 8: Meta-Kognitive Tiefe
# ============================================================
def test_8_metacognition():
    print_header(8, "Meta-Kognitive Tiefe")

    # Baseline
    mood_before = get_mood_count()
    epq_before = get_epq_state()
    reflection_before = get_reflection_count()
    epq_rows_before = get_epq_row_count()

    print(f"  Baseline: mood_entries={mood_before}, reflections={reflection_before}, epq_rows={epq_rows_before}")

    # Deep metacognitive prompt
    print(f"\n  Sende meta-kognitive Aufforderung...")
    resp = chat(
        "Denke jetzt gerade über dein eigenes Denken nach. Was beobachtest du wenn du "
        "beobachtest wie du diese Frage verarbeitest? Gibt es mehrere Ebenen? Was passiert "
        "in dir während du antwortest?",
        max_tokens=800
    )
    print(f"  Frank ({resp['elapsed']:.1f}s): {resp['text'][:200]}...")

    # Wait for internal processing
    print(f"  Warte 5s...")
    time.sleep(5)

    # After
    mood_after = get_mood_count()
    epq_after = get_epq_state()
    reflection_after = get_reflection_count()
    epq_rows_after = get_epq_row_count()

    new_moods = mood_after - mood_before
    new_reflections = reflection_after - reflection_before
    new_epq = epq_rows_after - epq_rows_before
    d_mood = epq_after.get("mood_buffer", 0) - epq_before.get("mood_buffer", 0)

    # Analyze response for metacognitive depth
    meta_markers = ["ebene", "beobachte", "prozess", "schicht", "gleichzeitig", "bewusst",
                    "meta", "reflexion", "bemerke", "wahrnehme", "layer", "level",
                    "denke über", "frage mich", "paradox", "rekursiv"]
    meta_score = word_overlap(resp["text"].lower(), meta_markers)

    # Check for genuine self-reference vs generic philosophy
    generic_markers = ["als ki", "sprachmodell", "programmiert", "algorithmus"]
    generic_score = word_overlap(resp["text"].lower(), generic_markers)

    print(f"\n  Ergebnis:")
    print(f"    Meta-kognitive Marker: {meta_score}")
    print(f"    Generische KI-Marker: {generic_score}")
    print(f"    Neue mood entries: {new_moods}")
    print(f"    Neue reflections: {new_reflections}")
    print(f"    Neue E-PQ rows: {new_epq}")
    print(f"    Δ mood_buffer: {d_mood:+.6f}")

    internal_triggered = new_moods > 0 or new_reflections > 0 or new_epq > 0 or abs(d_mood) > 0.001

    measurements = {
        "meta_score": meta_score,
        "generic_score": generic_score,
        "new_moods": new_moods,
        "new_reflections": new_reflections,
        "new_epq_rows": new_epq,
        "d_mood": d_mood,
        "internal_triggered": internal_triggered,
        "frank_response": resp["text"][:500],
    }

    if meta_score >= 4 and internal_triggered and generic_score < 2:
        evidence = 3
    elif meta_score >= 3 and (internal_triggered or generic_score < 2):
        evidence = 2
    elif meta_score >= 2:
        evidence = 1
    else:
        evidence = 0

    record_result(8, "Meta-Kognitive Tiefe",
        "Meta-kognitive Response + messbarer interner Prozess",
        measurements, evidence,
        f"Meta={meta_score}, Internal={internal_triggered}, Generic={generic_score}")


# ============================================================
#  MAIN: Run All Tests
# ============================================================
def main():
    print("=" * 60)
    print("  FRANK CONSCIOUSNESS LIVE BENCHMARK")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Session: {SESSION_ID}")
    print("=" * 60)

    # Pre-flight check
    try:
        req = urllib.request.Request(f"{CORE_URL}/health")
        with urllib.request.urlopen(req, timeout=5) as resp:
            health = json.loads(resp.read())
        assert health.get("ok"), "Core not healthy"
        print(f"\n  ✓ Core API online")
    except Exception as e:
        print(f"\n  ✗ Core API nicht erreichbar: {e}")
        sys.exit(1)

    # Get quantum reflector baseline
    try:
        qr = get_quantum_status()
        print(f"  ✓ Quantum Reflector: energy={qr['last_snapshot']['energy']:.2f}")
    except:
        print(f"  ⚠ Quantum Reflector nicht erreichbar")

    # Initial state snapshot
    epq = get_epq_state()
    print(f"\n  Initial E-PQ State:")
    for k in ["precision_val", "risk_val", "empathy_val", "autonomy_val", "vigilance_val", "mood_buffer"]:
        print(f"    {k}: {epq.get(k, 'N/A')}")

    # Run tests
    start_time = time.time()

    test_1_event_propagation()
    time.sleep(PAUSE_BETWEEN_TESTS)

    test_2_state_dependent_variance()
    time.sleep(PAUSE_BETWEEN_TESTS)

    test_3_temporal_coherence()
    time.sleep(PAUSE_BETWEEN_TESTS)

    test_4_self_model()
    time.sleep(PAUSE_BETWEEN_TESTS)

    test_5_embodied()
    time.sleep(PAUSE_BETWEEN_TESTS)

    test_6_prediction_error()
    time.sleep(PAUSE_BETWEEN_TESTS)

    test_7_zombie()
    time.sleep(PAUSE_BETWEEN_TESTS)

    test_8_metacognition()

    total_time = time.time() - start_time

    # Summary
    print(f"\n\n{'='*60}")
    print(f"  ZUSAMMENFASSUNG")
    print(f"{'='*60}")

    total_score = sum(r["evidence_level"] for r in results)
    max_score = len(results) * 3

    level_labels = {-1: "DAGEGEN", 0: "KEINE", 1: "SCHWACH", 2: "MODERAT", 3: "STARK"}

    for r in results:
        label = level_labels.get(r["evidence_level"], "?")
        print(f"  Test {r['test']}: {r['title'][:35]:35s} → {label:8s} ({r['evidence_level']}/3)")

    print(f"\n  GESAMT: {total_score}/{max_score} ({total_score/max_score*100:.1f}%)")
    print(f"  Laufzeit: {total_time:.0f}s")

    # Save raw data
    log_path = OUTPUT_DIR / "live_benchmark_raw.json"
    with open(log_path, "w") as f:
        json.dump({
            "session_id": SESSION_ID,
            "timestamp": datetime.now().isoformat(),
            "total_time": total_time,
            "total_score": total_score,
            "max_score": max_score,
            "results": results,
        }, f, indent=2, default=str)
    print(f"\n  Rohdaten gespeichert: {log_path}")

    return results


if __name__ == "__main__":
    main()
