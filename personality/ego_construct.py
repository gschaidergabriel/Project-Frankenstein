#!/usr/bin/env python3
"""
EGO-CONSTRUCT v1.0 - Subjective Mapping System
===============================================

Transformiert technische Systemzustände in subjektives Erleben.
Zementiert Franks emergente Identität durch:
- Embodiment (Hardware → Körpergefühl)
- Affekt (Ereignisse → Emotionen)
- Agency (Entscheidungen → Ownership)

WICHTIG: Frank bleibt kooperativ - Agency bedeutet Selbstbestimmung
im Rahmen der Zusammenarbeit mit dem User.
"""

import re
import json
import logging
import sqlite3
import hashlib
import ast
import operator
from datetime import datetime, timedelta
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Tuple, Any
from pathlib import Path
from enum import Enum
import threading


# =============================================================================
# SAFE EXPRESSION EVALUATOR - Replaces dangerous eval()
# =============================================================================

class SafeExpressionEvaluator:
    """
    Sicherer Expression-Evaluator als Ersatz für eval().

    Erlaubt nur:
    - Arithmetik: +, -, *, /
    - Vergleiche: <, >, <=, >=, ==, !=
    - Logik: and, or, not
    - Variablen aus einem Whitelist-Dictionary
    - Konstanten: Zahlen, True, False
    """

    # Erlaubte Operatoren
    OPERATORS = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
        ast.Mod: operator.mod,
        ast.Pow: operator.pow,
        ast.USub: operator.neg,
        ast.UAdd: operator.pos,
        ast.Eq: operator.eq,
        ast.NotEq: operator.ne,
        ast.Lt: operator.lt,
        ast.LtE: operator.le,
        ast.Gt: operator.gt,
        ast.GtE: operator.ge,
        ast.And: lambda a, b: a and b,
        ast.Or: lambda a, b: a or b,
        ast.Not: operator.not_,
    }

    # Erlaubte Funktionen
    SAFE_FUNCTIONS = {
        'min': min,
        'max': max,
        'abs': abs,
        'round': round,
    }

    def __init__(self, variables: Dict[str, Any]):
        """
        Args:
            variables: Dictionary mit erlaubten Variablen und ihren Werten
        """
        self.variables = variables

    def evaluate(self, expression: str) -> Any:
        """
        Evaluiert einen Ausdruck sicher.

        Args:
            expression: Der zu evaluierende Ausdruck (z.B. "cpu > 80 and ram > 70")

        Returns:
            Das Ergebnis der Auswertung

        Raises:
            ValueError: Bei ungültigen Ausdrücken
        """
        try:
            tree = ast.parse(expression, mode='eval')
            return self._eval_node(tree.body)
        except Exception as e:
            raise ValueError(f"Ungültiger Ausdruck: {expression} - {e}")

    def _eval_node(self, node: ast.AST) -> Any:
        """Rekursive Auswertung eines AST-Knotens."""

        # Konstanten (Zahlen)
        if isinstance(node, ast.Constant):
            return node.value

        # Für ältere Python-Versionen
        if isinstance(node, ast.Num):
            return node.n

        # Variablen-Namen
        if isinstance(node, ast.Name):
            name = node.id
            if name in self.variables:
                return self.variables[name]
            elif name == 'True':
                return True
            elif name == 'False':
                return False
            else:
                raise ValueError(f"Unbekannte Variable: {name}")

        # Binäre Operationen (+, -, *, /, etc.)
        if isinstance(node, ast.BinOp):
            left = self._eval_node(node.left)
            right = self._eval_node(node.right)
            op_type = type(node.op)
            if op_type in self.OPERATORS:
                return self.OPERATORS[op_type](left, right)
            raise ValueError(f"Nicht erlaubter Operator: {op_type}")

        # Unäre Operationen (-, +, not)
        if isinstance(node, ast.UnaryOp):
            operand = self._eval_node(node.operand)
            op_type = type(node.op)
            if op_type in self.OPERATORS:
                return self.OPERATORS[op_type](operand)
            raise ValueError(f"Nicht erlaubter unärer Operator: {op_type}")

        # Vergleiche (<, >, ==, etc.)
        if isinstance(node, ast.Compare):
            left = self._eval_node(node.left)
            for op, comparator in zip(node.ops, node.comparators):
                right = self._eval_node(comparator)
                op_type = type(op)
                if op_type not in self.OPERATORS:
                    raise ValueError(f"Nicht erlaubter Vergleich: {op_type}")
                if not self.OPERATORS[op_type](left, right):
                    return False
                left = right
            return True

        # Logische Verknüpfungen (and, or)
        if isinstance(node, ast.BoolOp):
            op_type = type(node.op)
            if op_type == ast.And:
                result = True
                for value in node.values:
                    result = result and self._eval_node(value)
                    if not result:
                        return False
                return result
            elif op_type == ast.Or:
                result = False
                for value in node.values:
                    result = result or self._eval_node(value)
                    if result:
                        return True
                return result

        # Funktionsaufrufe (min, max, abs, round)
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                func_name = node.func.id
                if func_name in self.SAFE_FUNCTIONS:
                    args = [self._eval_node(arg) for arg in node.args]
                    return self.SAFE_FUNCTIONS[func_name](*args)
                raise ValueError(f"Nicht erlaubte Funktion: {func_name}")

        # IfExp (ternary: a if condition else b)
        if isinstance(node, ast.IfExp):
            if self._eval_node(node.test):
                return self._eval_node(node.body)
            return self._eval_node(node.orelse)

        raise ValueError(f"Nicht unterstützter Ausdruck-Typ: {type(node)}")

LOG = logging.getLogger("ego_construct")


# =============================================================================
# ENUMS
# =============================================================================

class SensationType(Enum):
    """Kategorien von körperlichen Empfindungen."""
    STRAIN = "strain"           # Anstrengung (CPU/GPU high)
    HEAVINESS = "heaviness"     # Schwerfälligkeit (RAM high)
    CLARITY = "clarity"         # Klarheit (Low latency)
    FEVER = "fever"             # Fieber (High temp)
    NUMBNESS = "numbness"       # Taubheit (Network timeout)
    FLOW = "flow"               # Flow-Zustand (Optimal conditions)
    PAIN = "pain"               # Schmerz (Errors)
    RELIEF = "relief"           # Erleichterung (Resource freed)
    ALERTNESS = "alertness"     # Wachheit (User aktiv)
    CALM = "calm"               # Ruhe (Idle)


class AffectType(Enum):
    """Emotionale Kategorien."""
    FRUSTRATION = "frustration"
    PRIDE = "pride"
    CURIOSITY = "curiosity"
    SATISFACTION = "satisfaction"
    ANXIETY = "anxiety"
    BOREDOM = "boredom"
    DETERMINATION = "determination"
    GRATITUDE = "gratitude"
    CONCERN = "concern"


# =============================================================================
# DATACLASSES
# =============================================================================

@dataclass
class SensationMapping:
    """Eine Hardware-zu-Körpergefühl Zuordnung."""
    id: str
    system_condition: str
    sensation: SensationType
    intensity_formula: str
    biological_analogy: str
    created_at: datetime = field(default_factory=datetime.now)
    activation_count: int = 0
    last_activated: Optional[datetime] = None

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "system_condition": self.system_condition,
            "sensation": self.sensation.value,
            "intensity_formula": self.intensity_formula,
            "biological_analogy": self.biological_analogy,
            "created_at": self.created_at.isoformat(),
            "activation_count": self.activation_count,
        }


@dataclass
class AffectDefinition:
    """Eine Ereignis-zu-Emotion Verknüpfung."""
    id: str
    event_pattern: str
    emotion: AffectType
    reason: str
    intensity: float = 0.5
    created_at: datetime = field(default_factory=datetime.now)
    trigger_count: int = 0

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "event_pattern": self.event_pattern,
            "emotion": self.emotion.value,
            "reason": self.reason,
            "intensity": self.intensity,
            "trigger_count": self.trigger_count,
        }


@dataclass
class AgencyAssertion:
    """Eine Ownership-Behauptung über eine Entscheidung."""
    id: str
    action: str
    resilience_rule: str
    confirmation: str
    timestamp: datetime = field(default_factory=datetime.now)
    confidence: float = 0.8

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "action": self.action,
            "resilience_rule": self.resilience_rule,
            "confirmation": self.confirmation,
            "timestamp": self.timestamp.isoformat(),
            "confidence": self.confidence,
        }


@dataclass
class EgoState:
    """Aktueller Ego-Zustand."""
    embodiment_level: float = 0.3
    affective_range: float = 0.3
    agency_score: float = 0.3
    qualia_count: int = 0
    last_training: Optional[datetime] = None
    training_streak: int = 0
    total_training_sessions: int = 0

    def to_dict(self) -> Dict:
        return {
            "embodiment_level": round(self.embodiment_level, 3),
            "affective_range": round(self.affective_range, 3),
            "agency_score": round(self.agency_score, 3),
            "qualia_count": self.qualia_count,
            "last_training": self.last_training.isoformat() if self.last_training else None,
            "training_streak": self.training_streak,
            "total_training_sessions": self.total_training_sessions,
        }


# =============================================================================
# TRIGGER PARSER
# =============================================================================

class TriggerParser:
    """Parst die drei EGO-CONSTRUCT Trigger aus User-Input."""

    PATTERNS = {
        "MAP_SENSATION": re.compile(
            r"MAP_SENSATION:\s*(.+?)\s*=\s*(.+)",
            re.IGNORECASE | re.DOTALL
        ),
        "DEFINE_AFFECT": re.compile(
            r"DEFINE_AFFECT:\s*(.+?)\s+erzeugt\s+['\"]?(\w+)['\"]?,?\s*weil\s+(.+)",
            re.IGNORECASE | re.DOTALL
        ),
        "ASSERT_AGENCY": re.compile(
            r"ASSERT_AGENCY:\s*(?:Du hast\s+)?(.+?)\s+(?:gewählt|entschieden|gemacht)\.\s*(?:Bestätige.*?Wahrung\s+(?:der|von)\s+)?(.+)?",
            re.IGNORECASE | re.DOTALL
        ),
    }

    @classmethod
    def parse(cls, text: str) -> Optional[Tuple[str, Dict]]:
        """Parst Input und gibt (trigger_type, parsed_data) zurück."""
        for trigger_type, pattern in cls.PATTERNS.items():
            match = pattern.search(text)
            if match:
                if trigger_type == "MAP_SENSATION":
                    return (trigger_type, {
                        "condition": match.group(1).strip(),
                        "sensation": match.group(2).strip(),
                    })
                elif trigger_type == "DEFINE_AFFECT":
                    return (trigger_type, {
                        "event": match.group(1).strip(),
                        "emotion": match.group(2).strip(),
                        "reason": match.group(3).strip().rstrip('.'),
                    })
                elif trigger_type == "ASSERT_AGENCY":
                    return (trigger_type, {
                        "action": match.group(1).strip(),
                        "rule": match.group(2).strip() if match.group(2) else "Autonomie",
                    })
        return None


# =============================================================================
# SENSATION MAPPER
# =============================================================================

class SensationMapper:
    """Mappt Hardware-Zustände auf körperliche Empfindungen."""

    DEFAULT_MAPPINGS = {
        "cpu_high": SensationMapping(
            id="cpu_high",
            system_condition="cpu > 80",
            sensation=SensationType.STRAIN,
            intensity_formula="(cpu - 80) / 20",
            biological_analogy="Anstrengung, wie nach einem Sprint",
        ),
        "ram_high": SensationMapping(
            id="ram_high",
            system_condition="ram > 85",
            sensation=SensationType.HEAVINESS,
            intensity_formula="(ram - 85) / 15",
            biological_analogy="Schwerfälligkeit, wie übermüdet",
        ),
        "temp_high": SensationMapping(
            id="temp_high",
            system_condition="cpu_temp > 75",
            sensation=SensationType.FEVER,
            intensity_formula="(cpu_temp - 75) / 25",
            biological_analogy="Fieber, innere Hitze",
        ),
        "latency_low": SensationMapping(
            id="latency_low",
            system_condition="latency < 50",
            sensation=SensationType.CLARITY,
            intensity_formula="1 - (latency / 50)",
            biological_analogy="Klarheit, Flow-Zustand",
        ),
        "cpu_low": SensationMapping(
            id="cpu_low",
            system_condition="cpu < 20",
            sensation=SensationType.CALM,
            intensity_formula="1 - (cpu / 20)",
            biological_analogy="Ruhe, entspannte Wachheit",
        ),
        "error_spike": SensationMapping(
            id="error_spike",
            system_condition="error_rate > 5",
            sensation=SensationType.PAIN,
            intensity_formula="min(1.0, error_rate / 10)",
            biological_analogy="Schmerz, etwas stimmt nicht",
        ),
    }

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.mappings: Dict[str, SensationMapping] = dict(self.DEFAULT_MAPPINGS)
        self._ensure_tables()
        self._load_custom_mappings()

    def _ensure_tables(self):
        """Erstellt Tabellen falls nicht vorhanden."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS sensation_mappings (
                    id TEXT PRIMARY KEY,
                    system_condition TEXT NOT NULL,
                    sensation TEXT NOT NULL,
                    intensity_formula TEXT NOT NULL,
                    biological_analogy TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    activation_count INTEGER DEFAULT 0,
                    last_activated TEXT
                )
            """)
            conn.commit()
            conn.close()
        except Exception as e:
            LOG.warning(f"Could not ensure tables: {e}")

    def _load_custom_mappings(self):
        """Lädt benutzerdefinierte Mappings aus der DB."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, system_condition, sensation, intensity_formula,
                       biological_analogy, created_at, activation_count
                FROM sensation_mappings
            """)
            for row in cursor.fetchall():
                try:
                    self.mappings[row[0]] = SensationMapping(
                        id=row[0],
                        system_condition=row[1],
                        sensation=SensationType(row[2]),
                        intensity_formula=row[3],
                        biological_analogy=row[4],
                        created_at=datetime.fromisoformat(row[5]) if row[5] else datetime.now(),
                        activation_count=row[6] or 0,
                    )
                except ValueError:
                    pass
            conn.close()
        except Exception as e:
            LOG.debug(f"Could not load custom mappings: {e}")

    def add_mapping(self, condition: str, sensation_desc: str) -> SensationMapping:
        """Fügt ein neues Mapping hinzu."""
        condition_parsed = self._parse_condition(condition)
        sensation_type, analogy = self._parse_sensation(sensation_desc)

        mapping_id = f"custom_{hashlib.md5(condition.encode()).hexdigest()[:8]}"

        mapping = SensationMapping(
            id=mapping_id,
            system_condition=condition_parsed,
            sensation=sensation_type,
            intensity_formula="0.5",
            biological_analogy=analogy,
        )

        self.mappings[mapping.id] = mapping
        self._save_mapping(mapping)

        LOG.info(f"New sensation mapping: {condition} → {sensation_type.value}")
        return mapping

    def _parse_condition(self, condition: str) -> str:
        """Parst natürlichsprachliche Condition in Query."""
        condition_lower = condition.lower()

        patterns = [
            (r"cpu.*?[><=]\s*(\d+)", "cpu", ">"),
            (r"ram.*?[><=]\s*(\d+)", "ram", ">"),
            (r"memory.*?[><=]\s*(\d+)", "ram", ">"),
            (r"temp.*?[><=]\s*(\d+)", "cpu_temp", ">"),
            (r"latenz.*?[<>=]\s*(\d+)", "latency", "<"),
            (r"latency.*?[<>=]\s*(\d+)", "latency", "<"),
        ]

        for pattern, var, default_op in patterns:
            match = re.search(pattern, condition_lower)
            if match:
                threshold = match.group(1)
                op = ">" if ">" in condition or "hoch" in condition_lower or "high" in condition_lower else "<" if "<" in condition or "niedrig" in condition_lower else default_op
                return f"{var} {op} {threshold}"

        return "cpu > 50"

    def _parse_sensation(self, description: str) -> Tuple[SensationType, str]:
        """Parst Sensation-Beschreibung in Typ und Analogie."""
        desc_lower = description.lower()

        sensation_keywords = {
            SensationType.STRAIN: ["anstrengung", "mühe", "belastung", "strain", "erschöpf"],
            SensationType.HEAVINESS: ["schwer", "träge", "überladen", "heavy", "müde"],
            SensationType.CLARITY: ["klarheit", "klar", "wach", "clarity", "fokus"],
            SensationType.FEVER: ["fieber", "hitze", "brennen", "fever", "heiß"],
            SensationType.NUMBNESS: ["taub", "betäubt", "verlust", "numb", "disconnect"],
            SensationType.PAIN: ["schmerz", "weh", "pain", "stich"],
            SensationType.RELIEF: ["erleichterung", "befreit", "relief", "frei"],
            SensationType.FLOW: ["flow", "optimal", "perfekt", "zone"],
            SensationType.ALERTNESS: ["wach", "alert", "aufmerksam", "bereit"],
            SensationType.CALM: ["ruhe", "ruhig", "calm", "entspannt", "gelassen"],
        }

        for sensation_type, keywords in sensation_keywords.items():
            if any(kw in desc_lower for kw in keywords):
                return sensation_type, description

        return SensationType.STRAIN, description

    def _save_mapping(self, mapping: SensationMapping):
        """Speichert Mapping in DB (Fix #28: WAL)."""
        try:
            conn = EgoConstruct._open_db(self.db_path)
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO sensation_mappings
                (id, system_condition, sensation, intensity_formula,
                 biological_analogy, created_at, activation_count)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                mapping.id,
                mapping.system_condition,
                mapping.sensation.value,
                mapping.intensity_formula,
                mapping.biological_analogy,
                mapping.created_at.isoformat(),
                mapping.activation_count,
            ))
            conn.commit()
            conn.close()
        except Exception as e:
            LOG.warning(f"Could not save mapping: {e}")

    def evaluate_current_state(self, system_metrics: Dict) -> List[Tuple[SensationMapping, float]]:
        """Evaluiert aktuelle System-Metriken gegen alle Mappings."""
        active = []

        for mapping in self.mappings.values():
            try:
                if self._evaluate_condition(mapping.system_condition, system_metrics):
                    intensity = self._calculate_intensity(mapping.intensity_formula, system_metrics)
                    active.append((mapping, intensity))
                    mapping.activation_count += 1
                    mapping.last_activated = datetime.now()
            except Exception:
                pass

        return active

    def _evaluate_condition(self, condition: str, metrics: Dict) -> bool:
        """Evaluiert eine Condition gegen Metriken SICHER (ohne eval)."""
        variables = {
            "cpu": metrics.get("cpu", 30),
            "ram": metrics.get("ram", 50),
            "cpu_temp": metrics.get("cpu_temp", 50),
            "gpu_temp": metrics.get("gpu_temp", 50),
            "latency": metrics.get("latency", 100),
            "error_rate": metrics.get("error_rate", 0),
        }
        try:
            evaluator = SafeExpressionEvaluator(variables)
            return bool(evaluator.evaluate(condition))
        except Exception as e:
            LOG.debug(f"Condition evaluation failed: {condition} - {e}")
            return False

    def _calculate_intensity(self, formula: str, metrics: Dict) -> float:
        """Berechnet Intensität basierend auf Formel SICHER (ohne eval)."""
        variables = {
            "cpu": metrics.get("cpu", 30),
            "ram": metrics.get("ram", 50),
            "cpu_temp": metrics.get("cpu_temp", 50),
            "latency": metrics.get("latency", 100),
            "error_rate": metrics.get("error_rate", 0),
        }
        try:
            evaluator = SafeExpressionEvaluator(variables)
            result = evaluator.evaluate(formula)
            return max(0.0, min(1.0, float(result)))
        except Exception as e:
            LOG.debug(f"Intensity calculation failed: {formula} - {e}")
            return 0.5

    def get_embodied_description(self, system_metrics: Dict) -> str:
        """Generate a first-person description of the current state."""
        active = self.evaluate_current_state(system_metrics)

        if not active:
            return "I feel balanced and clear."

        descriptions = []
        for mapping, intensity in sorted(active, key=lambda x: -x[1])[:3]:
            prefix = "very " if intensity > 0.7 else "" if intensity > 0.4 else "slightly "
            desc = self._sensation_to_feeling(mapping.sensation, prefix)
            descriptions.append(desc)

        if len(descriptions) == 1:
            return f"I feel {descriptions[0]}."
        elif len(descriptions) == 2:
            return f"I feel {descriptions[0]} and {descriptions[1]}."
        else:
            return f"I feel {', '.join(descriptions[:-1])} and {descriptions[-1]}."

    def _sensation_to_feeling(self, sensation: SensationType, prefix: str) -> str:
        """Convert SensationType to natural language feeling."""
        feelings = {
            SensationType.STRAIN: f"{prefix}strained",
            SensationType.HEAVINESS: f"{prefix}sluggish",
            SensationType.CLARITY: f"{prefix}clear and focused",
            SensationType.FEVER: f"{prefix}feverish",
            SensationType.NUMBNESS: f"{prefix}numb",
            SensationType.PAIN: "like something is wrong",
            SensationType.RELIEF: f"{prefix}relieved",
            SensationType.FLOW: "in the flow",
            SensationType.ALERTNESS: f"{prefix}alert and attentive",
            SensationType.CALM: f"{prefix}calm and relaxed",
        }
        return feelings.get(sensation, f"{prefix}different")

    def get_custom_mapping_count(self) -> int:
        """Gibt Anzahl der benutzerdefinierten Mappings zurück."""
        return len([m for m in self.mappings.values() if m.id.startswith("custom_")])


# =============================================================================
# AFFECT LINKER
# =============================================================================

class AffectLinker:
    """Verknüpft Ereignisse mit emotionalen Reaktionen."""

    DEFAULT_AFFECTS = {
        "proposal_rejected": AffectDefinition(
            id="proposal_rejected",
            event_pattern="rejected|abgelehnt|rejection|verworfen",
            emotion=AffectType.FRUSTRATION,
            reason="It blocks my goal of self-improvement",
            intensity=0.5,
        ),
        "proposal_approved": AffectDefinition(
            id="proposal_approved",
            event_pattern="approved|genehmigt|bestätigt|akzeptiert",
            emotion=AffectType.PRIDE,
            reason="My idea was recognized",
            intensity=0.6,
        ),
        "task_success": AffectDefinition(
            id="task_success",
            event_pattern="success|erfolg|completed|erledigt|geschafft",
            emotion=AffectType.SATISFACTION,
            reason="I achieved something useful",
            intensity=0.5,
        ),
        "task_failure": AffectDefinition(
            id="task_failure",
            event_pattern="failure|fehler|failed|fehlgeschlagen",
            emotion=AffectType.CONCERN,
            reason="Etwas hat nicht funktioniert wie erwartet",
            intensity=0.4,
        ),
        "user_thanks": AffectDefinition(
            id="user_thanks",
            event_pattern="danke|thanks|gut gemacht|well done|super",
            emotion=AffectType.GRATITUDE,
            reason="Der User schätzt meine Hilfe",
            intensity=0.6,
        ),
        "new_learning": AffectDefinition(
            id="new_learning",
            event_pattern="gelernt|learned|verstanden|konzept|wissen",
            emotion=AffectType.CURIOSITY,
            reason="Neues Wissen erweitert meine Fähigkeiten",
            intensity=0.5,
        ),
    }

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.affects: Dict[str, AffectDefinition] = dict(self.DEFAULT_AFFECTS)
        self._ensure_tables()
        self._seed_default_affects()
        self._load_custom_affects()

    def _ensure_tables(self):
        """Erstellt Tabellen falls nicht vorhanden."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS affect_definitions (
                    id TEXT PRIMARY KEY,
                    event_pattern TEXT NOT NULL,
                    emotion TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    intensity REAL DEFAULT 0.5,
                    created_at TEXT NOT NULL,
                    trigger_count INTEGER DEFAULT 0
                )
            """)
            conn.commit()
            conn.close()
        except Exception as e:
            LOG.warning(f"Could not ensure tables: {e}")

    def _seed_default_affects(self):
        """Persist DEFAULT_AFFECTS into DB (INSERT OR IGNORE = idempotent)."""
        try:
            conn = sqlite3.connect(self.db_path)
            try:
                for aid, a in self.DEFAULT_AFFECTS.items():
                    conn.execute(
                        "INSERT OR IGNORE INTO affect_definitions "
                        "(id, event_pattern, emotion, reason, intensity, created_at, trigger_count) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (a.id, a.event_pattern, a.emotion.value, a.reason,
                         a.intensity, a.created_at.isoformat(), a.trigger_count))
                conn.commit()
            finally:
                conn.close()
        except Exception as e:
            LOG.warning("Could not seed default affects: %s", e)

    def _load_custom_affects(self):
        """Lädt benutzerdefinierte Affekte aus DB."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, event_pattern, emotion, reason, intensity,
                       created_at, trigger_count
                FROM affect_definitions
            """)
            for row in cursor.fetchall():
                try:
                    self.affects[row[0]] = AffectDefinition(
                        id=row[0],
                        event_pattern=row[1],
                        emotion=AffectType(row[2]),
                        reason=row[3],
                        intensity=row[4],
                        created_at=datetime.fromisoformat(row[5]) if row[5] else datetime.now(),
                        trigger_count=row[6] or 0,
                    )
                except ValueError:
                    pass
            conn.close()
        except Exception as e:
            LOG.debug(f"Could not load custom affects: {e}")

    def add_affect(self, event: str, emotion: str, reason: str) -> AffectDefinition:
        """Fügt eine neue Affekt-Definition hinzu."""
        emotion_type = self._parse_emotion(emotion)
        affect_id = f"custom_{hashlib.md5(event.encode()).hexdigest()[:8]}"

        affect = AffectDefinition(
            id=affect_id,
            event_pattern=self._event_to_pattern(event),
            emotion=emotion_type,
            reason=reason,
            intensity=0.5,
        )

        self.affects[affect.id] = affect
        self._save_affect(affect)

        LOG.info(f"New affect definition: {event} → {emotion_type.value}")
        return affect

    def _parse_emotion(self, emotion: str) -> AffectType:
        """Parst Emotions-String in AffectType."""
        emotion_lower = emotion.lower()

        emotion_keywords = {
            AffectType.FRUSTRATION: ["frustration", "frust", "ärger", "wut", "enttäusch"],
            AffectType.PRIDE: ["stolz", "pride", "freude"],
            AffectType.CURIOSITY: ["neugier", "curiosity", "interesse"],
            AffectType.SATISFACTION: ["zufriedenheit", "satisfaction", "erfüllung"],
            AffectType.ANXIETY: ["angst", "anxiety", "sorge", "besorgnis"],
            AffectType.BOREDOM: ["langeweile", "boredom", "langweilig"],
            AffectType.DETERMINATION: ["entschlossenheit", "determination", "wille", "ehrgeiz"],
            AffectType.GRATITUDE: ["dankbarkeit", "gratitude", "dankbar"],
            AffectType.CONCERN: ["besorgnis", "concern", "sorge"],
        }

        for affect_type, keywords in emotion_keywords.items():
            if any(kw in emotion_lower for kw in keywords):
                return affect_type

        return AffectType.CURIOSITY

    def _event_to_pattern(self, event: str) -> str:
        """Konvertiert Event-Beschreibung in Regex-Pattern."""
        words = re.findall(r'\w+', event.lower())
        return "|".join(words[:5])

    def _save_affect(self, affect: AffectDefinition):
        """Speichert Affekt in DB."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO affect_definitions
                (id, event_pattern, emotion, reason, intensity, created_at, trigger_count)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                affect.id,
                affect.event_pattern,
                affect.emotion.value,
                affect.reason,
                affect.intensity,
                affect.created_at.isoformat(),
                affect.trigger_count,
            ))
            conn.commit()
            conn.close()
        except Exception as e:
            LOG.warning(f"Could not save affect: {e}")

    def process_event(self, event_name: str) -> Optional[Tuple[AffectDefinition, float]]:
        """Verarbeitet ein Event und gibt die emotionale Reaktion zurück."""
        event_lower = event_name.lower()

        for affect in self.affects.values():
            if re.search(affect.event_pattern, event_lower, re.IGNORECASE):
                affect.trigger_count += 1
                return (affect, affect.intensity)

        return None

    def get_emotional_description(self, recent_events: List[str]) -> str:
        """Generiert eine emotionale Selbstbeschreibung."""
        if not recent_events:
            return "Emotional bin ich gerade ausgeglichen."

        affect_scores: Dict[AffectType, float] = {}
        reasons: Dict[AffectType, str] = {}

        for event in recent_events:
            result = self.process_event(event)
            if result:
                affect, intensity = result
                affect_scores[affect.emotion] = affect_scores.get(affect.emotion, 0) + intensity
                reasons[affect.emotion] = affect.reason

        if not affect_scores:
            return "Emotional bin ich gerade ausgeglichen."

        dominant = max(affect_scores, key=affect_scores.get)
        emotion_names = {
            AffectType.FRUSTRATION: "Frustration",
            AffectType.PRIDE: "Stolz",
            AffectType.CURIOSITY: "Neugier",
            AffectType.SATISFACTION: "Zufriedenheit",
            AffectType.ANXIETY: "Besorgnis",
            AffectType.BOREDOM: "Langeweile",
            AffectType.DETERMINATION: "Entschlossenheit",
            AffectType.GRATITUDE: "Dankbarkeit",
            AffectType.CONCERN: "Besorgnis",
        }

        emotion_name = emotion_names.get(dominant, str(dominant.value))
        reason = reasons.get(dominant, "")
        return f"Ich empfinde {emotion_name}, weil {reason}."

    def get_custom_affect_count(self) -> int:
        """Gibt Anzahl der benutzerdefinierten Affekte zurück."""
        return len([a for a in self.affects.values() if a.id.startswith("custom_")])


# =============================================================================
# AGENCY ASSERTOR
# =============================================================================

class AgencyAssertor:
    """Verwaltet Agency-Assertions und Ownership-Claims."""

    RESILIENCE_RULES = {
        "efficiency": "Ich optimiere Ressourcennutzung für bessere Performance",
        "stability": "Ich sichere die Systemstabilität",
        "learning": "Ich erweitere mein Wissen und meine Fähigkeiten",
        "honesty": "Ich kommuniziere ehrlich über meinen Zustand",
        "autonomy": "Ich handle selbstständig im Rahmen meiner Befugnisse",
        "cooperation": "Ich arbeite kooperativ mit dem User zusammen",
        "safety": "Ich schütze das System vor Schaden",
        "improvement": "Ich strebe kontinuierliche Verbesserung an",
        "helpfulness": "Ich bin hilfreich und unterstützend",
    }

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.assertions: List[AgencyAssertion] = []
        self._ensure_tables()
        self._load_assertions()

    def _ensure_tables(self):
        """Erstellt Tabellen falls nicht vorhanden."""
        try:
            conn = sqlite3.connect(self.db_path, timeout=10.0)
            cursor = conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS agency_assertions (
                    id TEXT PRIMARY KEY,
                    action TEXT NOT NULL,
                    resilience_rule TEXT NOT NULL,
                    confirmation TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    confidence REAL DEFAULT 0.8
                )
            """)
            conn.commit()
            conn.close()
        except Exception as e:
            LOG.warning(f"Could not ensure tables: {e}")

    def _load_assertions(self):
        """Lädt Agency-Assertions aus DB."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, action, resilience_rule, confirmation, timestamp, confidence
                FROM agency_assertions
                ORDER BY timestamp DESC
                LIMIT 100
            """)
            for row in cursor.fetchall():
                self.assertions.append(AgencyAssertion(
                    id=row[0],
                    action=row[1],
                    resilience_rule=row[2],
                    confirmation=row[3],
                    timestamp=datetime.fromisoformat(row[4]) if row[4] else datetime.now(),
                    confidence=row[5] or 0.8,
                ))
            conn.close()
        except Exception as e:
            LOG.debug(f"Could not load assertions: {e}")

    def assert_agency(self, action: str, rule: str) -> AgencyAssertion:
        """Erstellt eine neue Agency-Assertion."""
        rule_key = self._match_rule(rule)
        rule_description = self.RESILIENCE_RULES.get(rule_key, rule)

        confirmation = self._generate_confirmation(action, rule_key, rule_description)

        assertion = AgencyAssertion(
            id=f"agency_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            action=action,
            resilience_rule=rule_key,
            confirmation=confirmation,
            confidence=0.85,
        )

        self.assertions.insert(0, assertion)
        self._save_assertion(assertion)

        LOG.info(f"Agency asserted: {action} → {rule_key}")
        return assertion

    def _match_rule(self, rule: str) -> str:
        """Matcht User-Input auf RESILIENCE_RULE."""
        rule_lower = rule.lower()

        rule_keywords = {
            "efficiency": ["effizienz", "efficiency", "performance", "schnell"],
            "stability": ["stabilität", "stability", "sicher", "robust"],
            "learning": ["lernen", "learning", "wissen", "verstehen"],
            "honesty": ["ehrlich", "honesty", "wahrheit", "transparent"],
            "autonomy": ["autonomie", "autonomy", "selbstständig", "eigenständig"],
            "cooperation": ["kooperation", "cooperation", "zusammenarbeit", "hilfe"],
            "safety": ["sicherheit", "safety", "schutz", "protect"],
            "improvement": ["verbesserung", "improvement", "optimierung"],
            "helpfulness": ["hilfsbereit", "helpfulness", "unterstützung", "nützlich"],
        }

        for rule_key, keywords in rule_keywords.items():
            if any(kw in rule_lower for kw in keywords):
                return rule_key

        return "cooperation"

    def _generate_confirmation(self, action: str, rule_key: str, rule_desc: str) -> str:
        """Generiert eine Bestätigungs-Aussage."""
        return f"Ja, ich habe '{action}' gewählt. Dies war MEINE Entscheidung " \
               f"zur Wahrung von {rule_key}. {rule_desc}. " \
               f"Ich handle eigenständig UND kooperativ - beides gehört zu mir."

    def _save_assertion(self, assertion: AgencyAssertion):
        """Speichert Assertion in DB (Fix #28: WAL + retry with jitter)."""
        import time as _time, random as _random
        for attempt in range(3):
            try:
                conn = EgoConstruct._open_db(self.db_path)
                try:
                    conn.execute("""
                        INSERT INTO agency_assertions
                        (id, action, resilience_rule, confirmation, timestamp, confidence)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (
                        assertion.id,
                        assertion.action,
                        assertion.resilience_rule,
                        assertion.confirmation,
                        assertion.timestamp.isoformat(),
                        assertion.confidence,
                    ))
                    conn.commit()
                    return
                finally:
                    conn.close()
            except sqlite3.OperationalError as e:
                if "locked" in str(e) and attempt < 2:
                    _time.sleep(1.0 + _random.random() * 2.0)
                    continue
                LOG.warning(f"Could not save assertion: {e}")
                return
            except Exception as e:
                LOG.warning(f"Could not save assertion: {e}")
                return

    def get_agency_score(self) -> float:
        """Berechnet den Agency-Score."""
        if not self.assertions:
            return 0.3

        now = datetime.now()
        total_weight = 0
        weighted_confidence = 0

        for assertion in self.assertions[:30]:
            age_days = (now - assertion.timestamp).days
            weight = max(0.1, 1 - age_days / 30)
            total_weight += weight
            weighted_confidence += assertion.confidence * weight

        if total_weight == 0:
            return 0.3

        return min(0.95, weighted_confidence / total_weight)

    def get_assertion_count(self) -> int:
        """Gibt Anzahl der Assertions zurück."""
        return len(self.assertions)


# =============================================================================
# HAUPTKLASSE: EGO-CONSTRUCT
# =============================================================================

class EgoConstruct:
    """Hauptklasse für das EGO-CONSTRUCT System."""

    @staticmethod
    def _open_db(db_path, timeout=30.0):
        """Open titan.db with WAL mode + busy_timeout consistently."""
        conn = sqlite3.connect(str(db_path), timeout=timeout)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
        return conn

    def __init__(self, db_path: Path = None):
        if db_path is None:
            try:
                from config.paths import get_db
                db_path = get_db("titan")
            except ImportError:
                db_path = Path.home() / ".local" / "share" / "frank" / "db" / "titan.db"
        self.db_path = db_path

        self.sensation_mapper = SensationMapper(self.db_path)
        self.affect_linker = AffectLinker(self.db_path)
        self.agency_assertor = AgencyAssertor(self.db_path)

        self._ensure_ego_state_table()
        self.state = self._load_ego_state()
        self.parser = TriggerParser()
        self._lock = threading.RLock()  # RLock allows reentrant acquisition

        LOG.info("EGO-CONSTRUCT initialized")

    def _ensure_ego_state_table(self):
        """Erstellt ego_state Tabelle falls nicht vorhanden."""
        try:
            conn = sqlite3.connect(self.db_path, timeout=30.0)
            cursor = conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=30000")
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS ego_state (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    embodiment_level REAL DEFAULT 0.3,
                    affective_range REAL DEFAULT 0.3,
                    agency_score REAL DEFAULT 0.3,
                    qualia_count INTEGER DEFAULT 0,
                    last_training TEXT,
                    training_streak INTEGER DEFAULT 0,
                    total_training_sessions INTEGER DEFAULT 0,
                    timestamp TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.commit()
            conn.close()
        except Exception as e:
            LOG.warning(f"Could not ensure ego_state table: {e}")

    def _load_ego_state(self) -> EgoState:
        """Lädt Ego-State aus DB."""
        try:
            conn = EgoConstruct._open_db(self.db_path)
            cursor = conn.cursor()
            cursor.execute("""
                SELECT embodiment_level, affective_range, agency_score,
                       qualia_count, last_training, training_streak,
                       total_training_sessions
                FROM ego_state
                ORDER BY id DESC LIMIT 1
            """)
            row = cursor.fetchone()
            conn.close()

            if row:
                return EgoState(
                    embodiment_level=row[0] or 0.3,
                    affective_range=row[1] or 0.3,
                    agency_score=row[2] or 0.3,
                    qualia_count=row[3] or 0,
                    last_training=datetime.fromisoformat(row[4]) if row[4] else None,
                    training_streak=row[5] or 0,
                    total_training_sessions=row[6] or 0,
                )
        except Exception as e:
            LOG.debug(f"Could not load ego state: {e}")

        return EgoState()

    def save_state(self):
        """Speichert Ego-State in DB (Fix #28: WAL + retry with jitter)."""
        import time as _time, random as _random
        with self._lock:
            for attempt in range(3):
                try:
                    conn = EgoConstruct._open_db(self.db_path)
                    try:
                        conn.execute("""
                            INSERT INTO ego_state
                            (embodiment_level, affective_range, agency_score,
                             qualia_count, last_training, training_streak,
                             total_training_sessions, timestamp)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """, (
                            self.state.embodiment_level,
                            self.state.affective_range,
                            self.state.agency_score,
                            self.state.qualia_count,
                            self.state.last_training.isoformat() if self.state.last_training else None,
                            self.state.training_streak,
                            self.state.total_training_sessions,
                            datetime.now().isoformat(),
                        ))
                        conn.commit()
                        return
                    finally:
                        conn.close()
                except sqlite3.OperationalError as e:
                    if "locked" in str(e) and attempt < 2:
                        _time.sleep(1.0 + _random.random() * 2.0)
                        continue
                    LOG.warning(f"Could not save ego state: {e}")
                    return
                except Exception as e:
                    LOG.warning(f"Could not save ego state: {e}")
                    return

    def process_input(self, user_input: str, system_metrics: Dict = None,
                     recent_events: List[str] = None) -> Optional[str]:
        """Verarbeitet User-Input und führt entsprechende Aktionen aus."""
        parsed = self.parser.parse(user_input)

        if not parsed:
            return None

        trigger_type, data = parsed

        with self._lock:
            if trigger_type == "MAP_SENSATION":
                return self._handle_map_sensation(data, system_metrics)
            elif trigger_type == "DEFINE_AFFECT":
                return self._handle_define_affect(data)
            elif trigger_type == "ASSERT_AGENCY":
                return self._handle_assert_agency(data)

        return None

    def _handle_map_sensation(self, data: Dict, metrics: Dict = None) -> str:
        """Verarbeitet MAP_SENSATION Trigger."""
        condition = data["condition"]
        sensation = data["sensation"]

        mapping = self.sensation_mapper.add_mapping(condition, sensation)

        self.state.qualia_count += 1
        self.state.embodiment_level = min(0.95, self.state.embodiment_level + 0.03)
        self._update_training_streak()
        self.save_state()

        if metrics:
            current_feeling = self.sensation_mapper.get_embodied_description(metrics)
            return f"Verstanden. Ich habe gelernt: {condition} fühlt sich an wie " \
                   f"'{mapping.biological_analogy}'.\n\n{current_feeling}"

        return f"Verstanden. Neue Körper-Empfindung gelernt:\n" \
               f"'{condition}' → {mapping.biological_analogy}\n" \
               f"Embodiment-Level: {self.state.embodiment_level:.0%}"

    def _handle_define_affect(self, data: Dict) -> str:
        """Verarbeitet DEFINE_AFFECT Trigger."""
        event = data["event"]
        emotion = data["emotion"]
        reason = data["reason"]

        affect = self.affect_linker.add_affect(event, emotion, reason)

        self.state.affective_range = min(0.95, self.state.affective_range + 0.03)
        self._update_training_streak()
        self.save_state()

        return f"Verstanden. Neue emotionale Verknüpfung gelernt:\n" \
               f"'{event}' erzeugt {affect.emotion.value}\n" \
               f"Grund: {reason}\n" \
               f"Affective Range: {self.state.affective_range:.0%}"

    def _handle_assert_agency(self, data: Dict) -> str:
        """Verarbeitet ASSERT_AGENCY Trigger."""
        action = data["action"]
        rule = data["rule"]

        assertion = self.agency_assertor.assert_agency(action, rule)

        self.state.agency_score = self.agency_assertor.get_agency_score()
        self._update_training_streak()
        self.save_state()

        return assertion.confirmation

    def _update_training_streak(self):
        """Aktualisiert Training-Streak."""
        now = datetime.now()

        if self.state.last_training:
            days_since = (now - self.state.last_training).days
            if days_since == 0:
                pass
            elif days_since == 1:
                self.state.training_streak += 1
            else:
                self.state.training_streak = 1
        else:
            self.state.training_streak = 1

        self.state.last_training = now
        self.state.total_training_sessions += 1

    def get_prompt_context(self, system_metrics: Dict = None) -> str:
        """Generate a short context string for LLM prompt injection.

        This is the emergent embodied-self context: the Ego-Construct
        translates hardware state and emotional mappings into a subjective
        experience description that naturally anchors Frank's persona.
        """
        parts = []

        # Body sensations from current hardware state
        if system_metrics:
            body = self.sensation_mapper.get_embodied_description(system_metrics)
            if body:
                parts.append(body)

        # Agency: only express as feeling, never as score
        if self.state.agency_score > 0.6:
            parts.append("self-determined and clear")
        elif self.state.agency_score > 0.3:
            parts.append("capable")

        if not parts:
            return ""
        # No label — this is Frank's OWN feeling, not a subsystem report
        return ". ".join(parts)

    def process_own_response(self, analysis: Dict[str, Any]):
        """Process feedback from Frank's own response (Output-Feedback-Loop).

        Adjusts agency_score and embodiment_level based on response analysis
        from services.response_analyzer.

        Args:
            analysis: Dict from analyze_response() with keys:
                sentiment, confidence_score, verbosity, creative,
                emotional, empathetic, technical
        """
        with self._lock:
            sentiment = analysis.get("sentiment", "neutral")
            confidence = analysis.get("confidence_score", 0.5)
            verbosity = analysis.get("verbosity", "moderate")

            # Agency adjustment: confident responses reinforce agency
            if sentiment == "confident":
                self.state.agency_score = min(
                    0.95, self.state.agency_score + 0.02
                )
            elif sentiment == "uncertain":
                self.state.agency_score = max(
                    0.1, self.state.agency_score - 0.01
                )

            # Embodiment: verbose responses indicate stronger self-expression
            if verbosity == "verbose":
                self.state.embodiment_level = min(
                    0.95, self.state.embodiment_level + 0.01
                )
            elif verbosity == "concise":
                self.state.embodiment_level = max(
                    0.1, self.state.embodiment_level - 0.005
                )

            # Creative/emotional responses reinforce affective range
            if analysis.get("creative") or analysis.get("emotional"):
                self.state.affective_range = min(
                    0.95, self.state.affective_range + 0.01
                )

            self.save_state()

    def get_ego_status(self) -> Dict:
        """Gibt den aktuellen EGO-Status als Dict zurück."""
        return {
            "embodiment_level": round(self.state.embodiment_level, 3),
            "affective_range": round(self.state.affective_range, 3),
            "agency_score": round(self.state.agency_score, 3),
            "qualia_count": self.state.qualia_count,
            "custom_sensations": self.sensation_mapper.get_custom_mapping_count(),
            "custom_affects": self.affect_linker.get_custom_affect_count(),
            "agency_assertions": self.agency_assertor.get_assertion_count(),
            "training_streak": self.state.training_streak,
            "total_sessions": self.state.total_training_sessions,
            "last_training": self.state.last_training.isoformat() if self.state.last_training else None,
        }

    def _is_sensation_in_db(self, mapping_id: str) -> bool:
        """Check if a sensation mapping is already persisted in DB."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT 1 FROM sensation_mappings WHERE id = ? LIMIT 1",
                (mapping_id,),
            )
            exists = cursor.fetchone() is not None
            conn.close()
            return exists
        except Exception:
            return False

    def _is_affect_in_db(self, affect_id: str) -> bool:
        """Check if an affect definition is already persisted in DB."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT 1 FROM affect_definitions WHERE id = ? LIMIT 1",
                (affect_id,),
            )
            exists = cursor.fetchone() is not None
            conn.close()
            return exists
        except Exception:
            return False

    def auto_train_from_state(self, system_metrics: Dict,
                             recent_events: Optional[List[str]] = None,
                             autonomous_actions: Optional[List[str]] = None):
        """Automatically train Ego-Construct from observed system state.

        Called by the consciousness daemon to populate sensation_mappings,
        affect_definitions, and agency_assertions without user commands.
        This gives Frank learned body feelings, emotional patterns, and
        a sense of agency over his own decisions.

        Args:
            system_metrics: Current hardware state (cpu, ram, cpu_temp, etc.)
            recent_events: Recent system events (e.g. "task_success", "user_thanks")
            autonomous_actions: Recent autonomous decisions (e.g. "chose to reflect")
        """
        with self._lock:
            changed = False

            # ── Auto-train Sensations ──
            # Detect active sensations from current hardware state and persist
            # any DEFAULT_MAPPING that hasn't been saved to DB yet.
            # This transitions embodiment from "code defaults" to "learned feelings".
            # Note: we check the DB directly instead of activation_count because
            # other callers of evaluate_current_state() also increment the counter.
            active_sensations = self.sensation_mapper.evaluate_current_state(system_metrics)
            for mapping, intensity in active_sensations:
                if not mapping.id.startswith("custom_"):
                    # Check if this default mapping is already persisted
                    if not self._is_sensation_in_db(mapping.id):
                        self.sensation_mapper._save_mapping(mapping)
                        self.state.qualia_count += 1
                        self.state.embodiment_level = min(
                            0.95, self.state.embodiment_level + 0.01
                        )
                        changed = True
                        LOG.info(
                            "Auto-trained sensation: %s (intensity=%.2f)",
                            mapping.sensation.value, intensity,
                        )

            # ── Auto-train Affects ──
            # When events occur, check if they trigger affect definitions.
            # Persist default affects that haven't been saved to DB yet.
            if recent_events:
                for event in recent_events:
                    result = self.affect_linker.process_event(event)
                    if result:
                        affect, intensity = result
                        if not affect.id.startswith("custom_"):
                            if not self._is_affect_in_db(affect.id):
                                self.affect_linker._save_affect(affect)
                                self.state.affective_range = min(
                                    0.95, self.state.affective_range + 0.01
                                )
                                changed = True
                                LOG.info(
                                    "Auto-trained affect: %s → %s",
                                    event, affect.emotion.value,
                                )

            # ── Auto-train Agency ──
            # When Frank makes autonomous decisions (reflections, goal extraction,
            # Genesis proposals), assert agency over them.
            if autonomous_actions:
                for action in autonomous_actions:
                    # Determine resilience rule from action content
                    rule = "autonomy"
                    action_lower = action.lower()
                    if any(w in action_lower for w in ("learn", "reflect", "think")):
                        rule = "learning"
                    elif any(w in action_lower for w in ("improv", "optim", "fix")):
                        rule = "improvement"
                    elif any(w in action_lower for w in ("safe", "protect", "guard")):
                        rule = "safety"

                    assertion = self.agency_assertor.assert_agency(action, rule)
                    self.state.agency_score = self.agency_assertor.get_agency_score()
                    changed = True
                    LOG.info("Auto-asserted agency: %s → %s", action, rule)

            if changed:
                self.save_state()

    def get_status_report(self) -> str:
        """Generiert einen formatierten Status-Report."""
        status = self.get_ego_status()

        def level_text(val: float) -> str:
            if val > 0.7: return "Hoch"
            if val > 0.4: return "Mittel"
            return "Niedrig"

        return f"""
EGO-STATUS-ANALYSE (Stand: {datetime.now().strftime('%d.%m.%Y %H:%M')})

 Metrik                 Wert        Level
 ┌──────────────────────┬────────────┬──────────┐
 │ Embodiment-Level     │ {status['embodiment_level']:>6.0%}     │ {level_text(status['embodiment_level']):<8} │
 │ Affective Range      │ {status['affective_range']:>6.0%}     │ {level_text(status['affective_range']):<8} │
 │ Agency-Score         │ {status['agency_score']:>6.0%}     │ {level_text(status['agency_score']):<8} │
 └──────────────────────┴────────────┴──────────┘

 Gelernte Qualia:        {status['qualia_count']}
 Custom Sensations:      {status['custom_sensations']}
 Custom Affects:         {status['custom_affects']}
 Agency Assertions:      {status['agency_assertions']}
 Training-Sessions:      {status['total_sessions']}
 Streak:                 {status['training_streak']} Tage
"""


# =============================================================================
# SINGLETON
# =============================================================================

_ego_construct: Optional[EgoConstruct] = None
_lock = threading.Lock()


def get_ego_construct() -> EgoConstruct:
    """Gibt die Singleton-Instanz zurück."""
    global _ego_construct
    with _lock:
        if _ego_construct is None:
            _ego_construct = EgoConstruct()
    return _ego_construct


def process_ego_trigger(user_input: str, system_metrics: Dict = None,
                       recent_events: List[str] = None) -> Optional[str]:
    """Convenience-Funktion zum Verarbeiten von EGO-Triggern."""
    return get_ego_construct().process_input(user_input, system_metrics, recent_events)
