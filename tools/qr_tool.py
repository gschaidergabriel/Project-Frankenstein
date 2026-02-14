#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
QR Code Tool — Scan and Generate QR Codes

Scan: pyzbar (primary) + cv2.QRCodeDetector (fallback)
Generate: qrcode library with Pillow backend

Author: Frank AI System
"""

import logging
import subprocess
import time
from pathlib import Path
from typing import List, Optional, Tuple

LOG = logging.getLogger("qr_tool")

# ── Scan backends ──────────────────────────────────────────────────

_PYZBAR_OK = False
try:
    from pyzbar.pyzbar import decode as _pyzbar_decode
    _PYZBAR_OK = True
except ImportError:
    LOG.info("pyzbar not available, using cv2 fallback only")

_CV2_OK = False
try:
    import cv2
    _CV2_OK = True
except ImportError:
    LOG.warning("cv2 not available")

# ── Generate backend ──────────────────────────────────────────────

_QRCODE_OK = False
try:
    import qrcode
    _QRCODE_OK = True
except ImportError:
    LOG.warning("qrcode library not available")

try:
    from PIL import Image
except ImportError:
    Image = None


# ══════════════════════════════════════════════════════════════════
# Scanning
# ══════════════════════════════════════════════════════════════════

def _scan_pyzbar(image_path: str) -> List[str]:
    """Scan QR codes using pyzbar (robust, multi-QR)."""
    if not _PYZBAR_OK or not Image:
        return []
    try:
        img = Image.open(image_path)
        results = _pyzbar_decode(img)
        return [r.data.decode("utf-8", errors="replace") for r in results if r.data]
    except Exception as e:
        LOG.warning(f"pyzbar scan failed: {e}")
        return []


def _scan_cv2(image_path: str) -> List[str]:
    """Scan QR codes using OpenCV QRCodeDetector (fallback)."""
    if not _CV2_OK:
        return []
    try:
        img = cv2.imread(image_path)
        if img is None:
            return []
        detector = cv2.QRCodeDetector()
        data, points, _ = detector.detectAndDecode(img)
        if data:
            return [data]
        # Try multi-detector if available (OpenCV 4.x)
        if hasattr(cv2, "QRCodeDetectorAruco"):
            multi = cv2.QRCodeDetectorAruco()
            ok, decoded = multi.detectAndDecodeMulti(img)[:2]
            if ok and decoded:
                return [d for d in decoded if d]
        return []
    except Exception as e:
        LOG.warning(f"cv2 QR scan failed: {e}")
        return []


def scan_from_file(image_path: str) -> List[str]:
    """
    Scan QR code(s) from an image file.
    Returns list of decoded strings (may be multiple QR codes).
    """
    path = Path(image_path)
    if not path.exists():
        LOG.error(f"Image not found: {image_path}")
        return []

    # Try pyzbar first (more robust)
    results = _scan_pyzbar(str(path))
    if results:
        return results

    # Fallback to cv2
    results = _scan_cv2(str(path))
    if results:
        return results

    return []


def scan_from_screenshot() -> Tuple[List[str], Optional[str]]:
    """
    Take a screenshot and scan for QR codes.
    Returns (decoded_list, screenshot_path) or ([], None) on failure.
    """
    screenshot_path = f"/tmp/frank_qr_scan_{int(time.time())}.png"

    # Try screenshot backends in order
    for cmd in [
        ["maim", "-u", screenshot_path],
        ["scrot", screenshot_path],
        ["import", "-window", "root", screenshot_path],
    ]:
        try:
            result = subprocess.run(cmd, capture_output=True, timeout=5)
            if result.returncode == 0 and Path(screenshot_path).exists():
                break
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
    else:
        LOG.error("No screenshot backend available (maim/scrot/import)")
        return [], None

    results = scan_from_file(screenshot_path)
    return results, screenshot_path


def scan_from_camera(device: int = 0, timeout_sec: float = 5.0) -> List[str]:
    """
    Grab a frame from webcam and scan for QR codes.
    Returns list of decoded strings.
    """
    if not _CV2_OK:
        LOG.error("cv2 not available for camera capture")
        return []

    try:
        cap = cv2.VideoCapture(device)
        if not cap.isOpened():
            LOG.error(f"Cannot open camera device {device}")
            return []

        deadline = time.time() + timeout_sec
        results = []
        try:
            while time.time() < deadline:
                ret, frame = cap.read()
                if not ret:
                    continue

                # Save frame temporarily for scanning
                tmp_path = "/tmp/frank_qr_camera_frame.png"
                cv2.imwrite(tmp_path, frame)
                results = scan_from_file(tmp_path)
                if results:
                    break
                time.sleep(0.3)
        finally:
            cap.release()

        return results
    except Exception as e:
        LOG.error(f"Camera QR scan failed: {e}")
        return []


# ══════════════════════════════════════════════════════════════════
# Generation
# ══════════════════════════════════════════════════════════════════

def generate(data: str, size: int = 300) -> Optional["Image.Image"]:
    """
    Generate a QR code as a PIL Image.
    Returns PIL Image or None on failure.
    """
    if not _QRCODE_OK:
        LOG.error("qrcode library not available")
        return None

    try:
        qr = qrcode.QRCode(
            version=None,  # auto-size
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=10,
            border=4,
        )
        qr.add_data(data)
        qr.make(fit=True)

        img = qr.make_image(fill_color="black", back_color="white")
        img = img.resize((size, size), Image.NEAREST if Image else 0)
        return img
    except Exception as e:
        LOG.error(f"QR generation failed: {e}")
        return None


def generate_to_file(data: str, path: Optional[str] = None, size: int = 300) -> Optional[str]:
    """
    Generate a QR code and save to PNG file.
    Returns file path or None on failure.
    """
    if path is None:
        path = f"/tmp/frank_qr_{int(time.time())}.png"

    img = generate(data, size)
    if img is None:
        return None

    try:
        img.save(path)
        return path
    except Exception as e:
        LOG.error(f"QR save failed: {e}")
        return None


# ══════════════════════════════════════════════════════════════════
# Standalone test
# ══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.DEBUG)

    print("=== QR Tool Tests ===")

    # Test 1: Generate QR code
    print("\n[1] Generate QR code...")
    out = generate_to_file("https://example.com", "/tmp/test_qr.png")
    if out:
        print(f"  OK: Generated {out}")
    else:
        print("  FAIL: Generation failed")
        sys.exit(1)

    # Test 2: Scan generated QR
    print("\n[2] Scan generated QR...")
    results = scan_from_file("/tmp/test_qr.png")
    if results and "example.com" in results[0]:
        print(f"  OK: Decoded '{results[0]}'")
    else:
        print(f"  FAIL: Got {results}")

    # Test 3: Generate with special characters
    print("\n[3] Generate QR with special chars...")
    out = generate_to_file("Hallo Welt! äöü 🚀", "/tmp/test_qr_special.png")
    if out:
        results = scan_from_file(out)
        print(f"  OK: Generated + decoded '{results[0] if results else 'FAIL'}'")
    else:
        print("  FAIL")

    # Test 4: Scan non-existent file
    print("\n[4] Scan non-existent file...")
    results = scan_from_file("/tmp/does_not_exist.png")
    if not results:
        print("  OK: Returns empty list")
    else:
        print(f"  FAIL: Got {results}")

    # Test 5: Screenshot scan (may fail without display)
    print("\n[5] Screenshot scan...")
    try:
        results, path = scan_from_screenshot()
        print(f"  OK: Found {len(results)} QR(s), screenshot at {path}")
    except Exception as e:
        print(f"  SKIP: {e}")

    print("\n=== Done ===")
