#!/usr/bin/env python3
"""
F.R.A.N.K. Adaptive Visual Pipeline
====================================
Stage 1: Fast detectors (~100ms, always)
Stage 2: VLM via Ollama (~800ms, only when escalation triggers)

Frank decides whether Stage 2 is needed.

Usage:
    from tools.frank_adaptive_vision import FrankVisionService

    vision = FrankVisionService()
    result = vision.process("foto.jpg", "Was siehst du?")
    llm_context = result.final_summary
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("frank_vision")

try:
    from tools.frank_visual_pipeline import VisualPipeline, ImageAnalysis, SummaryComposer
except ImportError:
    from frank_visual_pipeline import VisualPipeline, ImageAnalysis, SummaryComposer


# ═══════════════════════════════════════════════════════════
#  ESCALATION DECISION
# ═══════════════════════════════════════════════════════════

@dataclass
class EscalationDecision:
    needs_vlm: bool
    reason: str
    confidence_without_vlm: float  # 0.0–1.0
    triggers: list = field(default_factory=list)


class EscalationEngine:
    """
    Decides whether Stage 1 analysis is sufficient
    or if VLM (Stage 2) is needed.
    """

    def decide(self, analysis: ImageAnalysis,
               user_question: Optional[str] = None) -> EscalationDecision:
        triggers = []
        confidence = 1.0

        # TRIGGER 1: Nothing detected
        if not analysis.objects and not analysis.ocr_text:
            triggers.append("keine_objekte_kein_text")
            confidence -= 0.5

        # TRIGGER 2: Scene unclear
        if analysis.scene == "unbekannt" or analysis.scene_confidence < 0.4:
            triggers.append("szene_unklar")
            confidence -= 0.2

        # TRIGGER 3: Low object confidence
        if analysis.objects:
            avg_conf = sum(o.confidence for o in analysis.objects) / len(analysis.objects)
            if avg_conf < 0.5:
                triggers.append(f"niedrige_konfidenz:{avg_conf:.2f}")
                confidence -= 0.25

        # TRIGGER 4: People without context
        if analysis.face_count > 0 and not analysis.is_screenshot:
            triggers.append("personen_ohne_kontext")
            confidence -= 0.2

        # TRIGGER 5: Photo without text
        if analysis.is_photo and not analysis.has_text:
            triggers.append("foto_ohne_text")
            confidence -= 0.15

        # TRIGGER 6: User question requires understanding
        if user_question:
            q = user_question.lower()

            understanding_keywords = [
                "warum", "wieso", "weshalb",
                "was passiert", "was geschieht",
                "was bedeutet", "was heißt",
                "stimmung", "gefühl", "emotion",
                "zusammenhang", "beziehung",
                "meme", "witz", "ironisch",
                "beschreib", "erzähl",
                "was siehst du", "was ist das",
                "erkläre", "interpretier",
                "vergleich",
                "was ist falsch", "fehler",
                "wie finde ich", "wo ist",
                "style", "design", "ästhetik",
                "qualität", "gut oder schlecht",
            ]

            for kw in understanding_keywords:
                if kw in q:
                    triggers.append(f"frage_erfordert_verständnis:{kw}")
                    confidence -= 0.4
                    break

            simple_keywords = [
                "wie viele", "anzahl", "zähl",
                "welche farbe", "farben",
                "text", "was steht", "lies",
                "auflösung", "größe", "format",
                "screenshot",
                "hell", "dunkel", "beleuchtung",
            ]

            for kw in simple_keywords:
                if kw in q:
                    triggers.append(f"einfache_frage:{kw}")
                    confidence += 0.2
                    break

        # TRIGGER 7: Complex scene (many objects)
        if len(analysis.objects) > 5:
            triggers.append(f"komplexe_szene:{len(analysis.objects)}_objekte")
            confidence -= 0.15

        # TRIGGER 8: Screenshot with little text
        if analysis.is_screenshot and len(analysis.ocr_text) < 3:
            triggers.append("screenshot_wenig_text")
            confidence -= 0.15

        # OVERRIDE: Text-heavy screenshot → OCR is enough
        if analysis.is_screenshot and len(analysis.ocr_text) > 5:
            return EscalationDecision(
                needs_vlm=False,
                reason="Screenshot mit viel Text — OCR reicht",
                confidence_without_vlm=0.9,
                triggers=["screenshot_textreich"],
            )

        # OVERRIDE: Diagram with text labels
        if analysis.is_diagram and analysis.has_text:
            return EscalationDecision(
                needs_vlm=False,
                reason="Diagramm mit Text-Labels — Pipeline reicht",
                confidence_without_vlm=0.75,
                triggers=["diagram_mit_text"],
            )

        # FINAL DECISION
        confidence = max(0.0, min(1.0, confidence))
        needs_vlm = confidence < 0.55

        if needs_vlm:
            reason = f"Confidence {confidence:.0%} zu niedrig. Trigger: {', '.join(triggers)}"
        else:
            reason = f"Confidence {confidence:.0%} ausreichend"

        return EscalationDecision(
            needs_vlm=needs_vlm,
            reason=reason,
            confidence_without_vlm=confidence,
            triggers=triggers,
        )


# ═══════════════════════════════════════════════════════════
#  VLM BACKEND (Stage 2) — Ollama
# ═══════════════════════════════════════════════════════════

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
VLM_MODELS = ["moondream", "llava"]
VLM_TIMEOUT = 120

class LocalVLM:
    """VLM via Ollama (Moondream2 or LLaVA). No torch/transformers needed."""

    def __init__(self):
        self.available = False
        self._working_model: Optional[str] = None

    def _check_available(self) -> bool:
        try:
            req = urllib.request.Request(f"{OLLAMA_URL}/api/tags", method="GET")
            with urllib.request.urlopen(req, timeout=3) as resp:
                data = json.loads(resp.read())
                models = [m.get("name", "") for m in data.get("models", [])]
                for candidate in VLM_MODELS:
                    for m in models:
                        if candidate in m:
                            self._working_model = m
                            self.available = True
                            logger.info("VLM available: %s via Ollama", m)
                            return True
        except Exception:
            pass
        self.available = False
        return False

    def describe(self, image_path: str, context: str = "",
                 question: str = "") -> str:
        if not self._working_model and not self._check_available():
            return "[VLM nicht verfügbar]"

        # Encode image as base64
        import base64
        try:
            with open(image_path, "rb") as f:
                img_b64 = base64.b64encode(f.read()).decode("utf-8")
        except Exception as e:
            return f"[Bild nicht lesbar: {e}]"

        # Build prompt
        if question:
            if context:
                prompt = f"Pre-analysis: {context}\nQuestion: {question}\nDescribe what you see and answer the question."
            else:
                prompt = question
        else:
            prompt = "Describe this image in detail in 2-3 sentences."

        payload = {
            "model": self._working_model,
            "prompt": prompt,
            "images": [img_b64],
            "stream": False,
        }

        try:
            t0 = time.time()
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                f"{OLLAMA_URL}/api/generate",
                data=data,
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=VLM_TIMEOUT) as resp:
                result = json.loads(resp.read())
                text = result.get("response", "").strip()
                dt = (time.time() - t0) * 1000
                logger.info("VLM response in %.0fms (%s)", dt, self._working_model)
                return text
        except Exception as e:
            logger.error("VLM call failed: %s", e)
            return f"[VLM Fehler: {e}]"


# ═══════════════════════════════════════════════════════════
#  ADAPTIVE RESULT
# ═══════════════════════════════════════════════════════════

@dataclass
class AdaptiveResult:
    pipeline_summary: str
    pipeline_analysis: Optional[ImageAnalysis]
    pipeline_ms: float

    escalated: bool
    escalation_reason: str
    escalation_confidence: float
    escalation_triggers: list

    vlm_description: str = ""
    vlm_ms: float = 0.0

    final_summary: str = ""
    total_ms: float = 0.0
    vlm_saved: bool = False


# ═══════════════════════════════════════════════════════════
#  ADAPTIVE VISUAL PIPELINE
# ═══════════════════════════════════════════════════════════

class AdaptiveVisualPipeline:
    """
    Stage 1 (always):    Fast detectors → ~100ms
    Escalation check:    Is VLM needed? → ~0ms
    Stage 2 (optional):  Ollama VLM → ~800ms

    ~90% of images don't need VLM.
    """

    def __init__(self, enable_vlm: bool = True, force_vlm: bool = False):
        self.pipeline = VisualPipeline()
        self.escalation = EscalationEngine()
        self.vlm = LocalVLM() if enable_vlm else None
        self.composer = SummaryComposer()
        self.force_vlm = force_vlm

        self.stats = {
            "total_images": 0,
            "pipeline_only": 0,
            "vlm_escalated": 0,
            "avg_pipeline_ms": 0.0,
            "avg_vlm_ms": 0.0,
            "vlm_save_rate": 0.0,
        }

    def analyze(self, image_path: str,
                user_question: str = None) -> AdaptiveResult:
        t_total = time.time()
        self.stats["total_images"] += 1

        # Stage 1: Fast Pipeline
        t0 = time.time()
        analysis = self.pipeline.analyze(image_path)
        pipeline_ms = (time.time() - t0) * 1000

        pipeline_summary = self.composer.compose(analysis)

        # Escalation Check
        decision = self.escalation.decide(analysis, user_question)
        escalated = decision.needs_vlm or self.force_vlm

        result = AdaptiveResult(
            pipeline_summary=pipeline_summary,
            pipeline_analysis=analysis,
            pipeline_ms=pipeline_ms,
            escalated=escalated,
            escalation_reason=decision.reason,
            escalation_confidence=decision.confidence_without_vlm,
            escalation_triggers=decision.triggers,
        )

        if escalated and self.vlm:
            # Stage 2: VLM
            t0 = time.time()
            vlm_desc = self.vlm.describe(
                image_path,
                context=pipeline_summary,
                question=user_question or "",
            )
            result.vlm_ms = (time.time() - t0) * 1000
            result.vlm_description = vlm_desc

            result.final_summary = (
                f"[Detektoren: {pipeline_summary}] "
                f"[Beschreibung: {vlm_desc}]"
            )
            self.stats["vlm_escalated"] += 1
        else:
            result.final_summary = pipeline_summary
            result.vlm_saved = True
            self.stats["pipeline_only"] += 1

        result.total_ms = (time.time() - t_total) * 1000

        # Update stats
        total = self.stats["total_images"]
        self.stats["vlm_save_rate"] = self.stats["pipeline_only"] / max(total, 1)
        self.stats["avg_pipeline_ms"] = (
            (self.stats["avg_pipeline_ms"] * (total - 1) + pipeline_ms) / total
        )
        if result.vlm_ms > 0:
            vlm_count = self.stats["vlm_escalated"]
            self.stats["avg_vlm_ms"] = (
                (self.stats["avg_vlm_ms"] * (vlm_count - 1) + result.vlm_ms) / vlm_count
            )

        if escalated:
            logger.info(
                "ESCALATED: %s | Pipeline: %.0fms | VLM: %.0fms | %s",
                image_path, pipeline_ms, result.vlm_ms, decision.reason,
            )
        else:
            logger.info(
                "PIPELINE OK: %s | %.0fms | Confidence: %.0f%%",
                image_path, pipeline_ms, decision.confidence_without_vlm * 100,
            )

        return result

    def get_stats(self) -> dict:
        return {
            **self.stats,
            "vlm_save_rate_pct": f"{self.stats['vlm_save_rate']:.0%}",
        }


# ═══════════════════════════════════════════════════════════
#  FRANK INTEGRATION SERVICE
# ═══════════════════════════════════════════════════════════

class FrankVisionService:
    """
    Drop-in service for Frank's vision system.

    Usage:
        vision = FrankVisionService()
        context = vision.get_llm_context("bild.png", "Was siehst du?")
    """

    _instance: Optional[FrankVisionService] = None

    @classmethod
    def get_instance(cls) -> FrankVisionService:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self, enable_vlm: bool = True):
        self.pipeline = AdaptiveVisualPipeline(enable_vlm=enable_vlm)
        logger.info("FrankVisionService ready (VLM=%s)", enable_vlm)

    def process(self, image_path: str,
                user_question: str = None) -> AdaptiveResult:
        return self.pipeline.analyze(image_path, user_question)

    def get_llm_context(self, image_path: str,
                        user_question: str = None) -> str:
        result = self.pipeline.analyze(image_path, user_question)
        return result.final_summary

    def stats(self) -> str:
        s = self.pipeline.get_stats()
        return (
            f"Vision Stats: {s['total_images']} images, "
            f"{s['vlm_save_rate_pct']} without VLM, "
            f"avg pipeline: {s['avg_pipeline_ms']:.0f}ms, "
            f"avg VLM: {s['avg_vlm_ms']:.0f}ms"
        )


# ═══════════════════════════════════════════════════════════
#  CLI
# ═══════════════════════════════════════════════════════════

def main():
    import sys
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")

    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <image.png> [question] [--no-vlm] [--force-vlm]")
        sys.exit(1)

    image_path = sys.argv[1]
    question = None
    enable_vlm = True
    force_vlm = False

    for arg in sys.argv[2:]:
        if arg == "--no-vlm":
            enable_vlm = False
        elif arg == "--force-vlm":
            force_vlm = True
        else:
            question = arg

    pipeline = AdaptiveVisualPipeline(enable_vlm=enable_vlm, force_vlm=force_vlm)
    result = pipeline.analyze(image_path, question)

    print(f"\n{'='*60}")
    print(f"  ADAPTIVE VISUAL ANALYSIS")
    print(f"{'='*60}\n")
    print(f"  Stage 1 (Pipeline):  {result.pipeline_ms:.0f}ms")
    print(f"  Summary:  {result.pipeline_summary}\n")
    print(f"  Escalation:  {'JA → VLM' if result.escalated else 'NEIN → Pipeline reicht'}")
    print(f"  Confidence:  {result.escalation_confidence:.0%}")
    print(f"  Reason:      {result.escalation_reason}")
    if result.escalation_triggers:
        print(f"  Triggers:    {', '.join(result.escalation_triggers)}")
    if result.escalated:
        print(f"\n  Stage 2 (VLM):  {result.vlm_ms:.0f}ms")
        print(f"  VLM says:  {result.vlm_description}")
    print(f"\n  {'─'*60}")
    print(f"  FINAL ({result.total_ms:.0f}ms):")
    print(f"  {result.final_summary}")
    print(f"\n  VLM saved: {'YES' if result.vlm_saved else 'NO — VLM was needed'}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
