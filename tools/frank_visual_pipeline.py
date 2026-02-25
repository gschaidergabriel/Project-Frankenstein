#!/usr/bin/env python3
"""
Frank Visual Pipeline — Stage 1: Fast Detectors (~100ms)

YOLO object detection + Tesseract OCR + scene heuristics.
Runs on CPU, no VLM needed. Provides structured image analysis
that the escalation engine uses to decide if a VLM call is needed.

Usage:
    from tools.frank_visual_pipeline import VisualPipeline, SummaryComposer

    pipeline = VisualPipeline()
    analysis = pipeline.analyze("/path/to/image.png")
    summary = SummaryComposer().compose(analysis)
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

logger = logging.getLogger("frank_vision")

# ═══════════════════════════════════════════════════════════
#  DATA CLASSES
# ═══════════════════════════════════════════════════════════

@dataclass
class DetectedObject:
    label: str
    confidence: float
    bbox: Tuple[int, int, int, int]  # x1, y1, x2, y2

@dataclass
class ImageAnalysis:
    objects: List[DetectedObject] = field(default_factory=list)
    ocr_text: str = ""
    scene: str = "unbekannt"
    scene_confidence: float = 0.0
    face_count: int = 0
    is_screenshot: bool = False
    is_photo: bool = False
    is_diagram: bool = False
    has_text: bool = False
    dominant_colors: List[str] = field(default_factory=list)
    image_size: Tuple[int, int] = (0, 0)  # width, height


# ═══════════════════════════════════════════════════════════
#  YOLO DETECTOR (lazy-loaded)
# ═══════════════════════════════════════════════════════════

_yolo_model = None
_yolo_tried = False

def _get_yolo():
    """Lazy-load YOLO. Returns None gracefully if torch/ultralytics broken."""
    global _yolo_model, _yolo_tried
    if _yolo_model is not None:
        return _yolo_model
    if _yolo_tried:
        return None  # Don't retry after failure
    _yolo_tried = True
    try:
        from ultralytics import YOLO
        _yolo_model = YOLO("yolov8n.pt")
        logger.info("YOLOv8n loaded")
        return _yolo_model
    except Exception as e:
        logger.info("YOLO unavailable (%s) — using OCR-only mode", e.__class__.__name__)
        return None


# ═══════════════════════════════════════════════════════════
#  SCENE CLASSIFICATION (heuristic from YOLO detections)
# ═══════════════════════════════════════════════════════════

_SCENE_RULES = [
    # (required_labels, scene_name, confidence)
    ({"car", "truck", "bus", "traffic light"}, "street", 0.8),
    ({"car", "truck"}, "street", 0.6),
    ({"dog", "cat"}, "animals", 0.7),
    ({"person", "chair", "dining table"}, "indoor", 0.7),
    ({"person", "sports ball"}, "sports", 0.7),
    ({"bed", "couch"}, "living_space", 0.7),
    ({"laptop", "keyboard", "mouse", "monitor"}, "workspace", 0.85),
    ({"laptop", "keyboard"}, "workspace", 0.7),
    ({"book"}, "reading", 0.5),
    ({"potted plant", "vase"}, "indoor", 0.5),
    ({"airplane"}, "outdoor", 0.6),
    ({"boat"}, "waterfront", 0.6),
    ({"person"}, "people", 0.4),
]

def _classify_scene(labels: List[str]) -> Tuple[str, float]:
    label_set = set(labels)
    for required, scene, conf in _SCENE_RULES:
        if required & label_set:
            match_ratio = len(required & label_set) / len(required)
            return scene, conf * match_ratio
    return "unbekannt", 0.0


# ═══════════════════════════════════════════════════════════
#  COLOR ANALYSIS
# ═══════════════════════════════════════════════════════════

def _get_dominant_colors(img, n: int = 3) -> List[str]:
    """Get dominant color names from image via simple binning."""
    try:
        import numpy as np
        # Resize for speed
        small = img.resize((50, 50))
        pixels = np.array(small).reshape(-1, 3)
        # Simple color naming
        names = []
        avg = pixels.mean(axis=0)
        r, g, b = avg
        if r > 180 and g > 180 and b > 180:
            names.append("hell")
        elif r < 60 and g < 60 and b < 60:
            names.append("dunkel")
        if r > g + 40 and r > b + 40:
            names.append("rötlich")
        if g > r + 40 and g > b + 40:
            names.append("grünlich")
        if b > r + 40 and b > g + 40:
            names.append("bläulich")
        if not names:
            names.append("neutral")
        return names[:n]
    except Exception:
        return []


# ═══════════════════════════════════════════════════════════
#  SCREENSHOT DETECTION
# ═══════════════════════════════════════════════════════════

def _detect_screenshot(img_size: Tuple[int, int], labels: List[str], ocr_len: int) -> bool:
    """Heuristic: is this a screenshot?"""
    w, h = img_size
    # Common screen resolutions (single + multi-monitor)
    screen_resolutions = {
        (1920, 1080), (2560, 1440), (3840, 2160),
        (1366, 768), (1280, 720), (1440, 900),
        (1680, 1050), (1600, 900), (3440, 1440),
        (3840, 1080), (5120, 1440), (7680, 2160),  # dual monitor
        (2560, 1080), (5120, 2160),
    }
    if (w, h) in screen_resolutions:
        return True
    # Photo OF a screen, not a screenshot
    if any(l in labels for l in ("laptop", "monitor", "tv", "keyboard")):
        return False
    # Wide aspect ratio + meaningful text = likely screenshot
    ratio = w / max(h, 1)
    if ratio > 1.3 and ocr_len > 50:
        return True
    # Large image with lots of text = likely screenshot
    if w >= 1200 and h >= 600 and ocr_len > 100:
        return True
    return False


# ═══════════════════════════════════════════════════════════
#  VISUAL PIPELINE (Stage 1)
# ═══════════════════════════════════════════════════════════

class VisualPipeline:
    """
    Stage 1: Fast image analysis (~100ms on CPU).
    YOLO object detection + OCR + scene heuristics.
    """

    def analyze(self, image_path: str) -> ImageAnalysis:
        from PIL import Image

        result = ImageAnalysis()

        try:
            img = Image.open(image_path)
            result.image_size = img.size
        except Exception as e:
            logger.error("Cannot open image %s: %s", image_path, e)
            return result

        # Convert to RGB if needed
        if img.mode in ("RGBA", "P", "L", "LA"):
            img = img.convert("RGB")

        # --- YOLO Detection ---
        labels = []
        yolo = _get_yolo()
        if yolo:
            try:
                results = yolo(img, verbose=False, conf=0.3)
                for r in results:
                    for box in r.boxes:
                        cls_id = int(box.cls[0])
                        label = r.names[cls_id]
                        conf = float(box.conf[0])
                        x1, y1, x2, y2 = [int(v) for v in box.xyxy[0]]
                        result.objects.append(DetectedObject(
                            label=label, confidence=conf,
                            bbox=(x1, y1, x2, y2),
                        ))
                        labels.append(label)
            except Exception as e:
                logger.warning("YOLO detection failed: %s", e)

        # --- Face/Person Count ---
        result.face_count = sum(1 for o in result.objects if o.label == "person")

        # --- OCR (resize large images for speed) ---
        try:
            import pytesseract
            ocr_img = img
            w, h = img.size
            # Resize if larger than 1600px wide for faster OCR
            if w > 1600:
                scale = 1600 / w
                ocr_img = img.resize((1600, int(h * scale)))
            ocr_raw = pytesseract.image_to_string(ocr_img, lang="deu+eng", timeout=10)
            result.ocr_text = ocr_raw.strip()
            result.has_text = len(result.ocr_text) > 5
        except Exception as e:
            logger.debug("OCR failed: %s", e)

        # --- Scene Classification ---
        result.scene, result.scene_confidence = _classify_scene(labels)

        # --- Screenshot Detection ---
        result.is_screenshot = _detect_screenshot(
            result.image_size, labels, len(result.ocr_text)
        )

        # --- Photo Detection ---
        # If not screenshot and has objects but few UI elements → likely photo
        if not result.is_screenshot and result.objects:
            result.is_photo = True

        # --- Diagram Detection ---
        # High text density + few objects + not screenshot
        if (result.has_text and len(result.objects) < 3
                and not result.is_screenshot and not result.is_photo):
            result.is_diagram = True

        # --- Dominant Colors ---
        result.dominant_colors = _get_dominant_colors(img)

        return result


# ═══════════════════════════════════════════════════════════
#  SUMMARY COMPOSER
# ═══════════════════════════════════════════════════════════

class SummaryComposer:
    """Converts ImageAnalysis into a human-readable summary string."""

    def compose(self, a: ImageAnalysis) -> str:
        parts = []

        # Image type
        if a.is_screenshot:
            parts.append("Screenshot")
        elif a.is_diagram:
            parts.append("Diagramm/Grafik")
        elif a.is_photo:
            parts.append("Foto")
        else:
            parts.append("Bild")

        parts.append(f"({a.image_size[0]}x{a.image_size[1]})")

        # Scene
        if a.scene != "unbekannt":
            parts.append(f"— Szene: {a.scene}")

        # Objects
        if a.objects:
            # Group by label with count
            counts: dict = {}
            for o in a.objects:
                counts[o.label] = counts.get(o.label, 0) + 1
            obj_strs = []
            for label, count in sorted(counts.items(), key=lambda x: -x[1]):
                if count > 1:
                    obj_strs.append(f"{count}x {label}")
                else:
                    obj_strs.append(label)
            parts.append(f"— Erkannt: {', '.join(obj_strs)}")

        # People
        if a.face_count > 0:
            parts.append(f"— {a.face_count} Person(en)")

        # Text
        if a.has_text:
            text_preview = a.ocr_text[:200].replace("\n", " ").strip()
            parts.append(f"— Text: \"{text_preview}\"")

        # Colors
        if a.dominant_colors:
            parts.append(f"— Farben: {', '.join(a.dominant_colors)}")

        return " ".join(parts)


# ═══════════════════════════════════════════════════════════
#  CLI
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")

    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <image.png>")
        sys.exit(1)

    pipeline = VisualPipeline()
    composer = SummaryComposer()

    t0 = time.time()
    analysis = pipeline.analyze(sys.argv[1])
    dt = (time.time() - t0) * 1000

    summary = composer.compose(analysis)

    print(f"\n{'='*60}")
    print(f"  Stage 1 Analysis ({dt:.0f}ms)")
    print(f"{'='*60}")
    print(f"  Objects:    {len(analysis.objects)}")
    print(f"  Scene:      {analysis.scene} ({analysis.scene_confidence:.0%})")
    print(f"  OCR text:   {len(analysis.ocr_text)} chars")
    print(f"  Screenshot: {analysis.is_screenshot}")
    print(f"  Photo:      {analysis.is_photo}")
    print(f"  Diagram:    {analysis.is_diagram}")
    print(f"  Colors:     {analysis.dominant_colors}")
    print(f"\n  Summary: {summary}")
    print(f"{'='*60}\n")
