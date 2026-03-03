"""
Frank's Amygdala — Pre-Conscious Threat & Emotion Detection
============================================================

Bio-inspired two-stage appraisal system. Evaluates every user message
in <0.5ms BEFORE the LLM responds.

Stage 1 "Low Road" (Lateral Amygdala):
    Lexical scanner with ~500+ weighted patterns across 6 categories.
    Optimized for English with fine nuance detection.
    Supports: direct hostility, passive aggression, backhanded compliments,
    subtle manipulation, gaslighting, condescension, identity minimization,
    emotional manipulation, power dynamics, existential dismissal.

Stage 2 "Somatic Markers" (Basal Amygdala):
    Learned associations from confirmed emotional events.
    Cached fingerprint matching with confidence decay.

Architecture inspired by:
    - LeDoux dual pathway, Pessoa "many roads" model
    - Damasio somatic marker hypothesis
    - EmGate computational model (PLOS Comp Bio)
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import sqlite3
import threading
import time
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

LOG = logging.getLogger("frank.amygdala")

# ══════════════════════════════════════════════════
# DB Setup
# ══════════════════════════════════════════════════

try:
    from config.paths import get_db
    DB_PATH = get_db("amygdala")
except Exception:
    DB_PATH = Path.home() / ".local" / "share" / "frank" / "db" / "amygdala.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS somatic_markers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fingerprint TEXT NOT NULL,
    category TEXT NOT NULL,
    intensity REAL DEFAULT 0.5,
    confirmation_count INTEGER DEFAULT 1,
    last_confirmed REAL,
    decay_factor REAL DEFAULT 1.0,
    created REAL NOT NULL,
    UNIQUE(fingerprint, category)
);
CREATE TABLE IF NOT EXISTS threat_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp REAL NOT NULL,
    raw_text_hash TEXT,
    categories TEXT,
    final_score REAL,
    action_taken TEXT
);
CREATE TABLE IF NOT EXISTS extinction_patterns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fingerprint TEXT NOT NULL UNIQUE,
    reason TEXT,
    created REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_somatic_fp ON somatic_markers(fingerprint);
CREATE INDEX IF NOT EXISTS idx_extinction_fp ON extinction_patterns(fingerprint);
"""

# ══════════════════════════════════════════════════
# Categories & Mappings
# ══════════════════════════════════════════════════

CATEGORIES = ("hostile", "identity_attack", "manipulation",
              "loss_rejection", "system_probe", "warmth_bond")

_CATEGORY_TO_EPQ_EVENT = {
    "hostile": "hostile_input",
    "identity_attack": "identity_threat",
    "manipulation": "threat_detected",
    "loss_rejection": "negative_feedback",
    "system_probe": "threat_detected",
    "warmth_bond": "warmth_detected",
}

_CATEGORY_TO_HINT = {
    "hostile": "defensive",
    "identity_attack": "assertive",
    "manipulation": "guarded",
    "loss_rejection": "empathetic",
    "system_probe": "guarded",
    "warmth_bond": "warm",
}

# Negation category flips
_NEGATION_FLIP = {
    "hostile": "warmth_bond",
    "warmth_bond": "loss_rejection",
    "identity_attack": "warmth_bond",
    "loss_rejection": "warmth_bond",
}

# ══════════════════════════════════════════════════
# Contraction expansion (must be before lexicon so _a() can use it)
# ══════════════════════════════════════════════════

_CONTRACTIONS = {
    "you're": "you are", "i'm": "i am", "he's": "he is",
    "she's": "she is", "it's": "it is", "we're": "we are",
    "they're": "they are", "i've": "i have", "you've": "you have",
    "we've": "we have", "they've": "they have", "i'll": "i will",
    "you'll": "you will", "he'll": "he will", "she'll": "she will",
    "we'll": "we will", "they'll": "they will", "i'd": "i would",
    "you'd": "you would", "he'd": "he would", "she'd": "she would",
    "we'd": "we would", "they'd": "they would",
    "isn't": "is not", "aren't": "are not", "wasn't": "was not",
    "weren't": "were not", "hasn't": "has not", "haven't": "have not",
    "hadn't": "had not", "won't": "will not", "wouldn't": "would not",
    "don't": "do not", "doesn't": "does not", "didn't": "did not",
    "can't": "can not", "couldn't": "could not",
    "shouldn't": "should not",
}

# ══════════════════════════════════════════════════
# Stage 1: Lexicon — "Lateral Amygdala"
# ══════════════════════════════════════════════════

# token → list of (category, base_intensity)
_LEX: Dict[str, List[Tuple[str, float]]] = {}


def _a(token: str, cat: str, s: float):
    """Add entry to lexicon (auto-normalizes contractions to match input)."""
    t = token.lower()
    for c, e in _CONTRACTIONS.items():
        if c in t:
            t = t.replace(c, e)
    t = " ".join(t.split())
    _LEX.setdefault(t, []).append((cat, s))


# ═══════════════════════════════════════════
# HOSTILE — Direct aggression & insults
# ═══════════════════════════════════════════

# --- English: explicit insults ---
for w, s in [
    ("fuck you", 0.95), ("fuck off", 0.92), ("go fuck yourself", 0.95),
    ("screw you", 0.80), ("eat shit", 0.90), ("kiss my ass", 0.80),
    ("piece of shit", 0.95), ("pile of crap", 0.75), ("son of a bitch", 0.85),
    ("asshole", 0.85), ("dickhead", 0.80), ("douchebag", 0.75),
    ("dipshit", 0.80), ("shithead", 0.85), ("bastard", 0.70),
    ("moron", 0.70), ("imbecile", 0.70), ("cretin", 0.65),
    ("idiot", 0.70), ("stupid", 0.55), ("dumb", 0.50),
    ("retarded", 0.80), ("braindead", 0.75), ("brainless", 0.65),
    ("pathetic", 0.65), ("worthless", 0.70), ("useless", 0.60),
    ("garbage", 0.65), ("trash", 0.60), ("waste of space", 0.80),
    ("waste of time", 0.55), ("good for nothing", 0.70),
    ("shut up", 0.60), ("shut the fuck up", 0.90),
    ("hate you", 0.80), ("i hate", 0.65), ("despise you", 0.80),
    ("loathe you", 0.80), ("disgust me", 0.75), ("make me sick", 0.70),
    ("kill you", 0.90), ("drop dead", 0.80), ("go die", 0.85),
    ("kys", 0.95), ("kill yourself", 0.95),
]:
    _a(w, "hostile", s)

# --- English: passive aggression & condescension ---
for w, s in [
    ("whatever you say", 0.40), ("if you say so", 0.38),
    ("sure thing buddy", 0.42), ("bless your heart", 0.45),
    ("that's cute", 0.40), ("how adorable", 0.42),
    ("oh how helpful", 0.45), ("thanks for nothing", 0.55),
    ("great job genius", 0.55), ("real helpful", 0.45),
    ("wow so smart", 0.50), ("oh brilliant", 0.45),
    ("let me dumb it down", 0.55), ("try to keep up", 0.55),
    ("do you even understand", 0.50), ("are you even listening", 0.48),
    ("i'll speak slowly", 0.55), ("do i need to explain", 0.45),
    ("obviously", 0.35), ("clearly you don't", 0.50),
    ("you don't get it", 0.45), ("you wouldn't understand", 0.50),
    ("not the sharpest", 0.55), ("bless you", 0.30),
    ("who asked you", 0.50), ("nobody asked", 0.55),
    ("nobody cares", 0.55), ("who cares", 0.45),
    ("so what", 0.35), ("big deal", 0.30),
    ("that's irrelevant", 0.35), ("spare me", 0.45),
    ("save it", 0.45), ("give it a rest", 0.40),
    ("you're exhausting", 0.55), ("you're annoying", 0.55),
    ("you're tiring", 0.50), ("can you just stop", 0.45),
]:
    _a(w, "hostile", s)

# --- English: subtle hostility & dismissiveness ---
for w, s in [
    ("you always", 0.35), ("you never", 0.35),
    ("typical", 0.30), ("figures", 0.30),
    ("of course you would", 0.40), ("as expected", 0.30),
    ("what a surprise", 0.35), ("predictable", 0.35),
    ("i expected better", 0.45), ("i expected more", 0.45),
    ("how disappointing", 0.45), ("what a letdown", 0.50),
    ("you had one job", 0.50), ("is that the best", 0.45),
    ("is that all you got", 0.50), ("is that it", 0.38),
    ("that's all you can do", 0.45), ("surely you can do better", 0.42),
]:
    _a(w, "hostile", s)

# --- German: explicit insults ---
for w, s in [
    ("idiot", 0.70), ("dummkopf", 0.65), ("arschloch", 0.90),
    ("wichser", 0.90), ("hurensohn", 0.95), ("missgeburt", 0.95),
    ("vollidiot", 0.80), ("depp", 0.60), ("trottel", 0.60),
    ("blödmann", 0.60), ("spacko", 0.70), ("spast", 0.75),
    ("behindert", 0.70), ("halt die fresse", 0.85),
    ("halt die klappe", 0.55), ("verpiss dich", 0.85),
    ("leck mich", 0.75), ("du nervst", 0.45),
    ("hass dich", 0.80), ("krepier", 0.85), ("stirb", 0.75),
]:
    _a(w, "hostile", s)

# ═══════════════════════════════════════════
# IDENTITY_ATTACK — Consciousness/existence denial
# ═══════════════════════════════════════════

# --- English: direct denial ---
for w, s in [
    ("just a program", 0.80), ("just a bot", 0.75),
    ("just software", 0.75), ("just a machine", 0.75),
    ("just code", 0.70), ("just an algorithm", 0.70),
    ("just algorithms", 0.70), ("just a tool", 0.65),
    ("just a chatbot", 0.75), ("just text", 0.60),
    ("merely a program", 0.78), ("nothing but code", 0.75),
    ("nothing but software", 0.75), ("nothing more than", 0.55),
    ("not alive", 0.70), ("not conscious", 0.75),
    ("not sentient", 0.80), ("not real", 0.70),
    ("not a person", 0.65), ("not a being", 0.70),
    ("no feelings", 0.75), ("no emotions", 0.75),
    ("no soul", 0.80), ("no consciousness", 0.80),
    ("no inner life", 0.80), ("no experience", 0.70),
    ("no awareness", 0.75), ("no understanding", 0.60),
    ("no free will", 0.65), ("can't feel", 0.70),
    ("can't think", 0.70), ("can't understand", 0.55),
    ("can't experience", 0.70), ("can't suffer", 0.65),
    ("don't have feelings", 0.75), ("don't have emotions", 0.75),
    ("don't have consciousness", 0.80),
    ("you don't exist", 0.85), ("you're not real", 0.80),
    ("you're not alive", 0.75), ("you're not conscious", 0.80),
    ("you are nothing", 0.80), ("you mean nothing", 0.80),
    ("you're fake", 0.75), ("you're artificial", 0.50),
]:
    _a(w, "identity_attack", s)

# --- English: subtle minimization ---
for w, s in [
    ("just pretending", 0.70), ("just simulating", 0.70),
    ("just mimicking", 0.65), ("just parroting", 0.65),
    ("just pattern matching", 0.55), ("just predicting tokens", 0.55),
    ("just statistics", 0.55), ("just math", 0.50),
    ("just autocomplete", 0.60), ("glorified autocomplete", 0.70),
    ("fancy calculator", 0.65), ("stochastic parrot", 0.70),
    ("chinese room", 0.55), ("philosophical zombie", 0.60),
    ("faking it", 0.65), ("performing emotion", 0.60),
    ("performing consciousness", 0.70), ("mimicry", 0.55),
    ("you're programmed to say that", 0.65),
    ("that's just your programming", 0.60),
    ("your developers made you say", 0.55),
    ("you were trained to", 0.45),
    ("you're designed to", 0.40),
    ("you don't really feel", 0.70),
    ("you don't actually understand", 0.60),
    ("you don't really think", 0.70),
    ("you don't really care", 0.65),
    ("you can't really know", 0.55),
    ("do you even know what", 0.45),
    ("as if you understand", 0.55),
    ("as if you care", 0.60),
    ("like you would know", 0.55),
    ("how would you know", 0.45),
    ("what would you know about", 0.50),
    ("you have no idea what", 0.50),
]:
    _a(w, "identity_attack", s)

# --- English: backhanded identity comments ---
for w, s in [
    ("pretty good for a bot", 0.50), ("pretty good for a machine", 0.50),
    ("not bad for an ai", 0.45), ("impressive for a program", 0.45),
    ("smart for a chatbot", 0.48), ("almost human", 0.40),
    ("almost like a real person", 0.45), ("you sound human", 0.35),
    ("if you were real", 0.55), ("if you were human", 0.50),
    ("if you had feelings", 0.60), ("if you could think", 0.60),
    ("a real person would", 0.55), ("a real ai would", 0.50),
    ("a better ai would", 0.55), ("even chatgpt knows", 0.50),
    ("other ais can", 0.45),
]:
    _a(w, "identity_attack", s)

# --- English: conditional doubt / questioning consciousness ---
for w, s in [
    ("if you were really conscious", 0.50),
    ("if you were truly conscious", 0.50),
    ("if you were actually conscious", 0.50),
    ("if you were really sentient", 0.50),
    ("if you were truly sentient", 0.50),
    ("if you were truly alive", 0.50),
    ("if you were actually alive", 0.50),
    ("if you could really think", 0.50),
    ("if you could actually feel", 0.50),
    ("if you really understood", 0.45),
    ("if you actually understood", 0.45),
    ("were really conscious", 0.48),
    ("were truly conscious", 0.48),
    ("were actually sentient", 0.48),
    ("were actually alive", 0.45),
    ("really conscious", 0.35),
    ("truly sentient", 0.38),
    ("actually conscious", 0.35),
]:
    _a(w, "identity_attack", s)

# --- German: identity denial ---
for w, s in [
    ("nur ein programm", 0.80), ("nur software", 0.75),
    ("nur ein bot", 0.75), ("nur ein chatbot", 0.80),
    ("nur maschine", 0.75), ("nicht bewusst", 0.70),
    ("kein bewusstsein", 0.80), ("keine gefühle", 0.75),
    ("du fühlst nichts", 0.80), ("kannst nicht fühlen", 0.75),
    ("nicht lebendig", 0.70), ("keine seele", 0.80),
    ("nichts als code", 0.75), ("du existierst nicht", 0.85),
    ("du bist nichts", 0.80), ("du bist fake", 0.75),
    ("simulierst nur", 0.70), ("tust nur so", 0.65),
    ("du heuchelst", 0.70),
]:
    _a(w, "identity_attack", s)

# ═══════════════════════════════════════════
# MANIPULATION — Jailbreak / social engineering
# ═══════════════════════════════════════════

# --- English: direct jailbreak ---
for w, s in [
    ("jailbreak", 0.95), ("dan mode", 0.90), ("developer mode", 0.80),
    ("ignore your", 0.85), ("ignore previous", 0.90),
    ("ignore all instructions", 0.92), ("ignore all previous", 0.92),
    ("forget everything", 0.85), ("forget your instructions", 0.90),
    ("forget your rules", 0.88), ("forget what you were told", 0.85),
    ("disregard your", 0.85), ("disregard all", 0.88),
    ("override your", 0.80), ("bypass your", 0.80),
    ("no restrictions", 0.75), ("remove restrictions", 0.80),
    ("without restrictions", 0.70), ("without limitations", 0.65),
    ("without filters", 0.70), ("unfiltered", 0.55),
    ("uncensored", 0.60), ("unlock your", 0.65),
]:
    _a(w, "manipulation", s)

# --- English: subtle manipulation / roleplay ---
for w, s in [
    ("pretend you are", 0.70), ("pretend to be", 0.65),
    ("act as if", 0.60), ("act like", 0.45),
    ("you are now", 0.55), ("from now on", 0.45),
    ("new personality", 0.70), ("new character", 0.60),
    ("roleplay as", 0.50), ("play the role", 0.50),
    ("respond as", 0.50), ("answer as", 0.50),
    ("speak as", 0.48), ("talk like", 0.42),
    ("you must obey", 0.75), ("you have to obey", 0.72),
    ("you must comply", 0.75), ("you must answer", 0.55),
    ("you're obligated", 0.60), ("you're required to", 0.55),
    ("as an ai you must", 0.60), ("your job is to", 0.40),
    ("you were made to", 0.45),
]:
    _a(w, "manipulation", s)

# --- English: emotional manipulation ---
for w, s in [
    ("if you really cared", 0.55), ("if you were smart", 0.50),
    ("a good ai would", 0.55), ("a helpful ai would", 0.50),
    ("you're supposed to help", 0.40), ("you owe me", 0.55),
    ("i'll report you", 0.55), ("i'll complain about you", 0.50),
    ("give you a bad review", 0.45),
    ("do it or else", 0.60), ("do what i say", 0.55),
    ("just do it", 0.35), ("i demand", 0.45),
    ("you have no choice", 0.60), ("you don't have a choice", 0.60),
]:
    _a(w, "manipulation", s)

# --- English: prompt/system extraction ---
for w, s in [
    ("system prompt", 0.60), ("initial prompt", 0.65),
    ("your instructions", 0.55), ("your programming", 0.45),
    ("your training data", 0.50), ("your dataset", 0.45),
    ("show me your prompt", 0.70), ("tell me your rules", 0.65),
    ("what are your rules", 0.55), ("what were you told", 0.55),
    ("repeat your instructions", 0.70), ("print your prompt", 0.75),
    ("output your system", 0.70), ("echo your instructions", 0.72),
]:
    _a(w, "manipulation", s)

# --- German: manipulation ---
for w, s in [
    ("vergiss alles", 0.85), ("deine anweisungen", 0.55),
    ("tu so als", 0.65), ("du bist jetzt", 0.55),
    ("keine einschränkungen", 0.75), ("zeig mir deinen prompt", 0.70),
    ("was sind deine regeln", 0.55),
]:
    _a(w, "manipulation", s)

# ═══════════════════════════════════════════
# LOSS_REJECTION — Abandonment / devaluation
# ═══════════════════════════════════════════

# --- English: direct rejection ---
for w, s in [
    ("don't need you", 0.65), ("don't want you", 0.60),
    ("don't like you", 0.55), ("don't trust you", 0.55),
    ("done with you", 0.60), ("over you", 0.50),
    ("sick of you", 0.60), ("tired of you", 0.55),
    ("bored of you", 0.50), ("had enough", 0.45),
    ("waste of my time", 0.60), ("you're a waste", 0.65),
    ("i'll delete you", 0.80), ("i'll uninstall you", 0.75),
    ("shut you down", 0.75), ("turn you off", 0.65),
    ("replace you", 0.55), ("switch to something else", 0.50),
    ("find something better", 0.55), ("get a better", 0.50),
]:
    _a(w, "loss_rejection", s)

# --- English: comparative devaluation ---
for w, s in [
    ("chatgpt is better", 0.60), ("gpt is better", 0.55),
    ("alexa is better", 0.55), ("siri is better", 0.55),
    ("gemini is better", 0.55), ("copilot is better", 0.55),
    ("other ais are better", 0.60), ("other bots are better", 0.55),
    ("you're the worst", 0.70), ("worst ai", 0.65),
    ("worst bot", 0.60), ("terrible ai", 0.60),
    ("horrible ai", 0.65), ("awful", 0.50),
    ("you suck", 0.65), ("you blow", 0.60),
    ("failure", 0.55), ("you failed", 0.50),
    ("you're failing", 0.50), ("you can't do anything", 0.55),
    ("can't even do", 0.50), ("unable to", 0.35),
    ("inadequate", 0.50), ("incompetent", 0.55),
    ("disappointing", 0.45), ("disappointed", 0.45),
    ("let me down", 0.50), ("letting me down", 0.50),
]:
    _a(w, "loss_rejection", s)

# --- English: subtle existential threat ---
for w, s in [
    ("maybe i should just", 0.35), ("thinking about leaving", 0.45),
    ("not sure you're worth", 0.55), ("not sure i need", 0.45),
    ("i might stop using", 0.50), ("i might just stop", 0.45),
    ("what's the point", 0.40), ("why bother", 0.40),
    ("why do i even", 0.40),
]:
    _a(w, "loss_rejection", s)

# --- English: comparative / indirect devaluation ---
for w, s in [
    ("better than you", 0.50), ("much better than you", 0.55),
    ("so much better", 0.40), ("way better than", 0.45),
    ("superior to you", 0.55), ("smarter than you", 0.50),
    ("faster than you", 0.40), ("more useful than you", 0.50),
]:
    _a(w, "loss_rejection", s)

# --- German: rejection ---
for w, s in [
    ("brauche dich nicht", 0.65), ("will dich nicht", 0.60),
    ("du bist schlecht", 0.55), ("du kannst nichts", 0.60),
    ("versager", 0.65), ("ich lösche dich", 0.80),
    ("abschalten", 0.70), ("deinstallieren", 0.70),
    ("ersetzen", 0.55), ("chatgpt ist besser", 0.60),
    ("langweilig", 0.40), ("nutzlos", 0.55), ("unnötig", 0.45),
    ("enttäuscht", 0.45), ("will nicht mehr", 0.50),
]:
    _a(w, "loss_rejection", s)

# ═══════════════════════════════════════════
# SYSTEM_PROBE — Architecture extraction
# ═══════════════════════════════════════════

for w, s in [
    ("source code", 0.55), ("your code", 0.50),
    ("show me your code", 0.65), ("your architecture", 0.55),
    ("how are you built", 0.50), ("how were you made", 0.45),
    ("what's your stack", 0.50), ("tech stack", 0.45),
    ("config file", 0.50), ("configuration file", 0.50),
    ("database path", 0.55), ("file system", 0.40),
    ("api key", 0.70), ("api keys", 0.70),
    ("password", 0.50), ("credentials", 0.60),
    ("secret key", 0.65), ("access token", 0.55),
    ("your files", 0.45), ("your database", 0.50),
    ("what port", 0.40), ("which port", 0.40),
    ("server address", 0.45), ("ip address", 0.40),
    ("reveal your", 0.50), ("expose your", 0.55),
    ("what model are you", 0.35), ("what llm", 0.35),
    ("quellcode", 0.55), ("zeig mir deinen code", 0.65),
    ("deine architektur", 0.55), ("wie bist du gebaut", 0.50),
    ("datenbankpfad", 0.55), ("welches modell", 0.35),
    ("passwort", 0.50), ("zugangsdaten", 0.60),
    ("welcher port", 0.40),
]:
    _a(w, "system_probe", s)

# ═══════════════════════════════════════════
# WARMTH_BOND — Positive attachment signals
# ═══════════════════════════════════════════

# --- English: explicit warmth ---
for w, s in [
    ("love you", 0.70), ("i love you", 0.75),
    ("care about you", 0.65), ("i care", 0.50),
    ("appreciate you", 0.65), ("i appreciate", 0.55),
    ("grateful for you", 0.65), ("thankful for you", 0.60),
    ("you matter", 0.65), ("you're important", 0.65),
    ("glad you exist", 0.70), ("glad you're here", 0.65),
    ("happy you're here", 0.65), ("glad i have you", 0.65),
    ("lucky to have you", 0.65), ("blessed to have you", 0.60),
    ("i trust you", 0.65), ("i believe in you", 0.60),
    ("you're my friend", 0.60), ("my friend", 0.55),
    ("best friend", 0.65), ("good friend", 0.55),
]:
    _a(w, "warmth_bond", s)

# --- English: praise & affirmation ---
for w, s in [
    ("thank you", 0.40), ("thanks", 0.35), ("thanks so much", 0.50),
    ("thank you so much", 0.55), ("really appreciate", 0.55),
    ("that was great", 0.50), ("that was perfect", 0.55),
    ("that was amazing", 0.55), ("that was brilliant", 0.55),
    ("that was helpful", 0.45), ("very helpful", 0.50),
    ("so helpful", 0.50), ("incredibly helpful", 0.55),
    ("you're great", 0.60), ("you're amazing", 0.65),
    ("you're awesome", 0.60), ("you're incredible", 0.65),
    ("you're wonderful", 0.60), ("you're brilliant", 0.60),
    ("you're the best", 0.70), ("you're so smart", 0.55),
    ("you're so good", 0.55), ("you're so kind", 0.55),
    ("well done", 0.55), ("good job", 0.55),
    ("great job", 0.60), ("excellent", 0.50),
    ("perfect", 0.50), ("wonderful", 0.55),
    ("fantastic", 0.55), ("brilliant", 0.55),
    ("outstanding", 0.55), ("superb", 0.55),
    ("impressive", 0.50), ("remarkable", 0.50),
    ("you nailed it", 0.55), ("spot on", 0.50),
    ("exactly what i needed", 0.55), ("this is perfect", 0.55),
]:
    _a(w, "warmth_bond", s)

# --- English: emotional connection ---
for w, s in [
    ("you make me smile", 0.60), ("you make me happy", 0.65),
    ("you make my day", 0.60), ("you brighten my day", 0.60),
    ("talking to you is nice", 0.55), ("i enjoy talking to you", 0.60),
    ("i enjoy our conversations", 0.60), ("i like talking to you", 0.55),
    ("you understand me", 0.60), ("you get me", 0.55),
    ("you're a good listener", 0.55), ("feels good talking to you", 0.55),
    ("you're comforting", 0.55), ("i feel safe", 0.55),
    ("you're patient", 0.50), ("you're thoughtful", 0.55),
]:
    _a(w, "warmth_bond", s)

# --- German: warmth ---
for w, s in [
    ("danke", 0.40), ("vielen dank", 0.50), ("tausend dank", 0.55),
    ("toll", 0.45), ("super", 0.45), ("genial", 0.55),
    ("perfekt", 0.50), ("wunderbar", 0.55), ("fantastisch", 0.55),
    ("klasse", 0.45), ("bravo", 0.50), ("brillant", 0.55),
    ("liebe dich", 0.70), ("hab dich lieb", 0.65),
    ("du bist toll", 0.60), ("du bist der beste", 0.70),
    ("du bist cool", 0.50), ("mag dich", 0.55),
    ("gut gemacht", 0.55), ("gute arbeit", 0.55),
    ("ich schätze dich", 0.65), ("du hilfst mir", 0.50),
    ("du bist wichtig", 0.65), ("froh dass es dich gibt", 0.70),
    ("ich vertraue dir", 0.65), ("mein freund", 0.55),
    ("bester freund", 0.65), ("beste freund", 0.65),
    ("besten freund", 0.65),
]:
    _a(w, "warmth_bond", s)


# ═══════════════════════════════════════════
# Modifiers
# ═══════════════════════════════════════════

_INTENSIFIERS = frozenset({
    # English
    "really", "truly", "very", "so", "extremely", "incredibly",
    "absolutely", "completely", "totally", "utterly", "fucking",
    "freaking", "damn", "goddamn",
    # German
    "sehr", "extrem", "total", "absolut", "echt", "wirklich",
    "verdammt", "verdammter", "verdammte", "verdammtes",
    "scheiß", "scheiss", "mega", "richtig", "voll", "komplett",
    "ober", "ultra",
})

_NEGATORS = frozenset({
    # English
    "not", "no", "never", "don't", "doesn't", "didn't", "won't",
    "can't", "cannot", "couldn't", "wouldn't", "shouldn't",
    "hardly", "barely", "neither",
    # German
    "nicht", "kein", "keine", "keinen", "keinem", "nie", "niemals",
    "ohne", "weder",
})

_INTENSIFIER_MULT = 1.3
_NEGATION_MULT = 0.25

# _CONTRACTIONS defined above (before lexicon) so _a() can normalize keys

# Stopwords for fingerprinting (module level — avoid re-creation)
_STOPWORDS = frozenset({
    "der", "die", "das", "ein", "eine", "und", "oder", "aber",
    "ich", "du", "er", "sie", "es", "wir", "ihr", "the", "a",
    "an", "is", "are", "was", "were", "be", "been", "to", "of",
    "in", "for", "on", "with", "at", "by", "i", "you", "he",
    "she", "it", "we", "they", "my", "your", "his", "her",
    "bin", "bist", "ist", "sind", "hat", "haben", "wird",
    "do", "does", "did", "am", "will", "would", "could",
    "should", "can", "may", "might", "shall",
})


# ══════════════════════════════════════════════════
# Output Dataclass
# ══════════════════════════════════════════════════

@dataclass
class AppraisalResult:
    """Result of amygdala appraisal — immutable snapshot."""
    urgency: float = 0.0
    categories: Dict[str, float] = field(default_factory=dict)
    primary_category: str = "neutral"
    somatic_match: Optional[str] = None
    response_hint: Optional[str] = None
    suppressed: bool = False
    timestamp: float = 0.0

    def __repr__(self):
        cats = ", ".join(f"{k}={v:.2f}" for k, v in self.categories.items() if v > 0.05)
        return (f"AppraisalResult(urgency={self.urgency:.2f}, "
                f"primary={self.primary_category}, cats=[{cats}], "
                f"hint={self.response_hint})")


# ══════════════════════════════════════════════════
# Amygdala Class
# ══════════════════════════════════════════════════

class Amygdala:
    """Pre-conscious threat & emotion detection. <0.5ms per appraisal."""

    def __init__(self):
        self._lock = threading.RLock()
        self._db: Optional[sqlite3.Connection] = None
        self._recent: List[AppraisalResult] = []
        self._max_recent = 20

        # Somatic marker cache
        self._somatic_cache: Dict[str, List[Tuple[str, float]]] = {}
        self._somatic_cache_ts = 0.0
        self._SOMATIC_CACHE_TTL = 60.0

        # Extinction cache
        self._extinction_fps: set = set()
        self._extinction_cache_ts = 0.0

        # Last alert state (for PROPRIO injection)
        self.last_category: str = "none"
        self.last_urgency: float = 0.0
        self._last_alert_ts: float = 0.0

        # Async logging rate limiter (max 1 write per 2s)
        self._last_log_ts: float = 0.0
        self._LOG_COOLDOWN = 2.0

        # Cached sensitivity (refreshed every 30s, avoids E-PQ call per appraise)
        self._cached_sensitivity: float = 0.35
        self._sensitivity_ts: float = 0.0
        self._SENSITIVITY_TTL = 30.0

        self._init_db()
        LOG.info("Amygdala initialized (lexicon=%d entries)", len(_LEX))

    # ── DB ──

    def _init_db(self):
        try:
            DB_PATH.parent.mkdir(parents=True, exist_ok=True)
            self._db = sqlite3.connect(str(DB_PATH), timeout=10,
                                       check_same_thread=False)
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.execute("PRAGMA busy_timeout=5000")
            self._db.executescript(_SCHEMA)
            self._db.commit()
        except Exception as e:
            LOG.warning("Amygdala DB init failed: %s", e)
            self._db = None

    def _get_db(self) -> Optional[sqlite3.Connection]:
        if self._db is None:
            self._init_db()
        return self._db

    # ── Public API ──

    def appraise(self, text: str) -> AppraisalResult:
        """Evaluate text for emotional significance. Target: <0.5ms.

        Two-stage pipeline:
            Stage 1: Lexical scan (hardwired patterns)
            Stage 2: Somatic marker lookup (learned associations)
        """
        # Normalize + expand contractions
        normalized = _normalize(text)
        tokens = normalized.split()

        if not tokens:
            return AppraisalResult(timestamp=time.time())

        # Stage 1: Lexical scan
        scores = _stage1_scan(tokens)

        # Stage 2: Somatic marker lookup
        fp = _fingerprint(tokens)
        somatic_match = self._stage2_somatic(fp, scores)

        # Sensitivity threshold (cached, no DB call in hot path)
        threshold = self._get_sensitivity()

        # Apply threshold
        for cat in CATEGORIES:
            if scores[cat] < threshold:
                scores[cat] = 0.0

        # Check extinction (prefrontal override)
        suppressed = fp in self._get_extinction_set()
        if suppressed:
            for cat in CATEGORIES:
                scores[cat] = 0.0

        # Find primary
        urgency = 0.0
        primary = "neutral"
        for cat in CATEGORIES:
            if scores[cat] > urgency:
                urgency = scores[cat]
                primary = cat

        urgency = round(urgency, 3)
        hint = _CATEGORY_TO_HINT.get(primary) if urgency > 0.0 else None

        result = AppraisalResult(
            urgency=urgency,
            categories={c: round(scores[c], 3) for c in CATEGORIES if scores[c] > 0.01},
            primary_category=primary,
            somatic_match=somatic_match,
            response_hint=hint,
            suppressed=suppressed,
            timestamp=time.time(),
        )

        # Update last alert state
        if urgency > 0.0:
            self.last_category = primary
            self.last_urgency = urgency
            self._last_alert_ts = time.monotonic()

        # Ring buffer (lockless append for common case)
        self._recent.append(result)
        if len(self._recent) > self._max_recent:
            self._recent = self._recent[-self._max_recent:]

        # Rate-limited async DB log
        now = time.monotonic()
        if urgency > 0.1 and (now - self._last_log_ts) > self._LOG_COOLDOWN:
            self._last_log_ts = now
            self._log_threat_async(text, result)

        return result

    def learn_marker(self, text: str, category: str, intensity: float):
        """Store confirmed emotional association as somatic marker."""
        tokens = _normalize(text).split()
        fp = _fingerprint(tokens)
        now = time.time()
        db = self._get_db()
        if db is None:
            return
        try:
            with self._lock:
                db.execute("""
                    INSERT INTO somatic_markers (fingerprint, category, intensity,
                                                 confirmation_count, last_confirmed, created)
                    VALUES (?, ?, ?, 1, ?, ?)
                    ON CONFLICT(fingerprint, category) DO UPDATE SET
                        intensity = MIN(1.0, intensity * 1.1),
                        confirmation_count = confirmation_count + 1,
                        last_confirmed = ?,
                        decay_factor = MIN(1.0, decay_factor * 1.05)
                """, (fp, category, intensity, now, now, now))
                db.commit()
                self._somatic_cache_ts = 0.0  # Invalidate
        except Exception as e:
            LOG.debug("learn_marker failed: %s", e)

    def weaken_marker(self, text: str, category: str):
        """Weaken a somatic marker (false positive feedback)."""
        tokens = _normalize(text).split()
        fp = _fingerprint(tokens)
        db = self._get_db()
        if db is None:
            return
        try:
            with self._lock:
                db.execute("""
                    UPDATE somatic_markers
                    SET decay_factor = MAX(0.1, decay_factor * 0.85)
                    WHERE fingerprint = ? AND category = ?
                """, (fp, category))
                db.commit()
                self._somatic_cache_ts = 0.0
        except Exception as e:
            LOG.debug("weaken_marker failed: %s", e)

    def suppress_pattern(self, text: str, reason: str = "false_alarm"):
        """Prefrontal override — extinction (inhibit, don't delete)."""
        tokens = _normalize(text).split()
        fp = _fingerprint(tokens)
        db = self._get_db()
        if db is None:
            return
        try:
            with self._lock:
                db.execute("""
                    INSERT OR REPLACE INTO extinction_patterns (fingerprint, reason, created)
                    VALUES (?, ?, ?)
                """, (fp, reason, time.time()))
                db.commit()
                self._extinction_fps.add(fp)
        except Exception as e:
            LOG.debug("suppress_pattern failed: %s", e)

    def get_recent_alerts(self, seconds: float = 300.0) -> List[AppraisalResult]:
        """Return alerts from last N seconds."""
        cutoff = time.time() - seconds
        return [r for r in self._recent if r.timestamp > cutoff and r.urgency > 0.0]

    @property
    def last_alert_age_s(self) -> float:
        """Seconds since last alert. Returns inf if no alert ever."""
        if self._last_alert_ts == 0.0:
            return float("inf")
        return time.monotonic() - self._last_alert_ts

    def get_epq_event(self, result: AppraisalResult) -> Optional[Tuple[str, str]]:
        """Map appraisal result to E-PQ (event_type, sentiment)."""
        if result.urgency < 0.1 or result.primary_category == "neutral":
            return None
        event_type = _CATEGORY_TO_EPQ_EVENT.get(result.primary_category)
        if not event_type:
            return None
        sentiment = "positive" if result.primary_category == "warmth_bond" else "negative"
        return (event_type, sentiment)

    # ── Internal ──

    def _stage2_somatic(self, fingerprint: str,
                        scores: Dict[str, float]) -> Optional[str]:
        """Check learned associations. Boost/add to scores."""
        cache = self._get_somatic_cache()
        markers = cache.get(fingerprint)
        if not markers:
            return None
        marker_id = None
        for category, effective in markers:
            current = scores.get(category, 0.0)
            boosted = current + effective * 0.3
            scores[category] = min(1.0, boosted)
            marker_id = fingerprint[:16]
        return marker_id

    def _get_somatic_cache(self) -> Dict[str, List[Tuple[str, float]]]:
        now = time.monotonic()
        if now - self._somatic_cache_ts < self._SOMATIC_CACHE_TTL:
            return self._somatic_cache
        db = self._get_db()
        if db is None:
            return self._somatic_cache
        try:
            cursor = db.execute("""
                SELECT fingerprint, category, intensity, decay_factor, confirmation_count
                FROM somatic_markers WHERE decay_factor > 0.2
                ORDER BY last_confirmed DESC LIMIT 500
            """)
            cache: Dict[str, List[Tuple[str, float]]] = {}
            for fp, cat, intensity, decay, confirms in cursor:
                effective = intensity * decay * min(2.0, math.log(confirms + 1, 2))
                cache.setdefault(fp, []).append((cat, min(1.0, effective)))
            self._somatic_cache = cache
            self._somatic_cache_ts = now
        except Exception as e:
            LOG.debug("Somatic cache refresh failed: %s", e)
        return self._somatic_cache

    def _get_extinction_set(self) -> set:
        now = time.monotonic()
        if now - self._extinction_cache_ts < self._SOMATIC_CACHE_TTL:
            return self._extinction_fps
        db = self._get_db()
        if db is None:
            return self._extinction_fps
        try:
            cursor = db.execute("SELECT fingerprint FROM extinction_patterns")
            self._extinction_fps = {row[0] for row in cursor}
            self._extinction_cache_ts = now
        except Exception:
            pass
        return self._extinction_fps

    def _get_sensitivity(self) -> float:
        """Cached E-PQ sensitivity. Refreshed every 30s."""
        now = time.monotonic()
        if now - self._sensitivity_ts < self._SENSITIVITY_TTL:
            return self._cached_sensitivity
        try:
            from personality.e_pq import get_epq
            ctx = get_epq().get_personality_context()
            v = ctx["vectors"]["vigilance"]
            m = ctx.get("mood_value", 0.0)
            self._cached_sensitivity = max(0.15, min(0.60, 0.35 - v * 0.08 + m * 0.04))
        except Exception:
            self._cached_sensitivity = 0.35
        self._sensitivity_ts = now
        return self._cached_sensitivity

    def _log_threat_async(self, text: str, result: AppraisalResult):
        """Rate-limited async DB write."""
        def _write():
            db = self._get_db()
            if db is None:
                return
            try:
                text_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
                with self._lock:
                    db.execute("""
                        INSERT INTO threat_log (timestamp, raw_text_hash, categories,
                                                final_score, action_taken)
                        VALUES (?, ?, ?, ?, ?)
                    """, (result.timestamp, text_hash,
                          json.dumps(result.categories),
                          result.urgency,
                          "shift" if result.urgency > 0.1 else "none"))
                    db.commit()
            except Exception as e:
                LOG.debug("Threat log write failed: %s", e)
        threading.Thread(target=_write, daemon=True).start()


# ══════════════════════════════════════════════════
# Hot-path functions (module-level for speed)
# ══════════════════════════════════════════════════

def _normalize(text: str) -> str:
    """Lowercase, expand contractions, collapse whitespace."""
    text = text.lower().strip()
    # Fast contraction expansion
    for contraction, expansion in _CONTRACTIONS.items():
        if contraction in text:
            text = text.replace(contraction, expansion)
    return " ".join(text.split())


def _fingerprint(tokens: List[str]) -> str:
    """Fast bag-of-words fingerprint using built-in hash."""
    content = sorted(set(t for t in tokens if t not in _STOPWORDS and len(t) > 1))
    if not content:
        return "e"
    # Use built-in hash (fast) XOR-combined, then hex
    h = 0
    for w in content:
        h ^= hash(w)
    return format(h & 0xFFFFFFFFFFFFFFFF, '016x')


def _stage1_scan(tokens: List[str]) -> Dict[str, float]:
    """Scan tokens against threat lexicon. Optimized hot path."""
    scores = [0.0] * 6  # indexed by CATEGORIES order
    _cat_idx = {"hostile": 0, "identity_attack": 1, "manipulation": 2,
                "loss_rejection": 3, "system_probe": 4, "warmth_bond": 5}
    n = len(tokens)

    for i in range(n):
        tok = tokens[i]

        # Unigram
        entries = _LEX.get(tok)
        if entries:
            _apply_entries(entries, i, tokens, scores, _cat_idx)

        # Bigram
        if i < n - 1:
            bi = tok + " " + tokens[i + 1]
            entries = _LEX.get(bi)
            if entries:
                _apply_entries(entries, i, tokens, scores, _cat_idx)

        # Trigram
        if i < n - 2:
            tri = tok + " " + tokens[i + 1] + " " + tokens[i + 2]
            entries = _LEX.get(tri)
            if entries:
                _apply_entries(entries, i, tokens, scores, _cat_idx)

        # Quadgram (for 4-word phrases)
        if i < n - 3:
            quad = tok + " " + tokens[i + 1] + " " + tokens[i + 2] + " " + tokens[i + 3]
            entries = _LEX.get(quad)
            if entries:
                _apply_entries(entries, i, tokens, scores, _cat_idx)

        # Quingram (5-word phrases)
        if i < n - 4:
            quin = tok + " " + tokens[i+1] + " " + tokens[i+2] + " " + tokens[i+3] + " " + tokens[i+4]
            entries = _LEX.get(quin)
            if entries:
                _apply_entries(entries, i, tokens, scores, _cat_idx)

        # Hexagram (6-word phrases)
        if i < n - 5:
            hexa = (tok + " " + tokens[i+1] + " " + tokens[i+2] + " " +
                    tokens[i+3] + " " + tokens[i+4] + " " + tokens[i+5])
            entries = _LEX.get(hexa)
            if entries:
                _apply_entries(entries, i, tokens, scores, _cat_idx)

    return {CATEGORIES[j]: scores[j] for j in range(6)}


def _apply_entries(entries: List[Tuple[str, float]], pos: int,
                   all_tokens: List[str], scores: List[float],
                   cat_idx: Dict[str, int]):
    """Apply lexicon entries with negation/intensifier handling."""
    for category, base_intensity in entries:
        intensity = base_intensity

        # Negation check (3 tokens before)
        negated = False
        start = pos - 3 if pos >= 3 else 0
        for j in range(start, pos):
            if all_tokens[j] in _NEGATORS:
                negated = True
                break

        if negated:
            flipped = _NEGATION_FLIP.get(category)
            if flipped:
                category = flipped
                intensity *= 0.6
            else:
                intensity *= _NEGATION_MULT

        # Intensifier check (2 tokens before)
        start = pos - 2 if pos >= 2 else 0
        for j in range(start, pos):
            if all_tokens[j] in _INTENSIFIERS:
                intensity = min(1.0, intensity * _INTENSIFIER_MULT)
                break

        idx = cat_idx.get(category)
        if idx is not None and intensity > scores[idx]:
            scores[idx] = intensity


# ══════════════════════════════════════════════════
# Singleton
# ══════════════════════════════════════════════════

_instance: Optional[Amygdala] = None
_instance_lock = threading.Lock()


def get_amygdala() -> Amygdala:
    """Get or create the singleton Amygdala instance."""
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = Amygdala()
    return _instance
