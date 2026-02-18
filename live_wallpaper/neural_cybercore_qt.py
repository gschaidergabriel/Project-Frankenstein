#!/usr/bin/env python3
"""
Neural Cybercore v5.2 - GLSL Shader (Ridged Noise)
==================================================
Volumetric plasma using GPU shaders.
v5.2: Aggressive electric effects with ridged multi-fractal noise.
"""

import json
import math
import os
import random
import signal
import socket
import subprocess
import sys
import threading
import time

# =============================================================================
# DISABLE QT SCALING - Must be BEFORE Qt imports
# =============================================================================
os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "0"
os.environ["QT_SCALE_FACTOR"] = "1"
os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "0"

from PySide6.QtCore import Qt, QTimer, Signal, QThread
from PySide6.QtGui import QFont, QShortcut, QKeySequence, QSurfaceFormat, QPixmap, QColor, QPainter
from PySide6.QtWidgets import QApplication, QWidget, QLabel
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtOpenGL import QOpenGLShaderProgram, QOpenGLShader

try:
    from OpenGL.GL import *
    from OpenGL.GL import shaders
    OPENGL_AVAILABLE = True
except ImportError:
    OPENGL_AVAILABLE = False
    print("[CYBERCORE] Warning: PyOpenGL not available")

# =============================================================================
# CONSTANTS
# =============================================================================
MONITOR_WIDTH = 1920
MONITOR_HEIGHT = 1080
MONITOR_X = 0
MONITOR_Y = 0
CENTER_X = MONITOR_WIDTH // 2 + 80
CENTER_Y = MONITOR_HEIGHT // 2 + 40
PANEL_OFFSET = 40  # HUD offset from top
_shutdown = threading.Event()

# Frank character icon for core texture rendering
try:
    from config.paths import AICORE_ROOT as _AICORE_ROOT_PATH
    FRANK_ICON_PATH = os.path.join(str(_AICORE_ROOT_PATH), "assets", "icons", "frank-overlay.png")
except ImportError:
    _SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
    FRANK_ICON_PATH = os.path.join(os.path.dirname(_SCRIPT_DIR), "assets", "icons", "frank-overlay.png")


def detect_primary_monitor():
    """
    Detect PRIMARY monitor for the wallpaper.
    The wallpaper should ALWAYS appear on the primary/main monitor.
    Falls back to first available monitor if no primary is marked.
    """
    global MONITOR_WIDTH, MONITOR_HEIGHT, MONITOR_X, MONITOR_Y, CENTER_X, CENTER_Y
    try:
        result = subprocess.run(
            ["xrandr", "--listmonitors"],
            capture_output=True, text=True, timeout=2
        )
        if result.returncode == 0:
            monitors = []
            for line in result.stdout.splitlines():
                if ':' in line and ('/' in line or 'x' in line):
                    is_primary = '+*' in line
                    parts = line.split()
                    for part in parts:
                        if '/' in part and 'x' in part and '+' in part:
                            geo = part.split('+')
                            dims = geo[0]
                            x = int(geo[1])
                            y = int(geo[2])
                            w_part, h_part = dims.split('x')
                            w = int(w_part.split('/')[0])
                            h = int(h_part.split('/')[0])
                            monitors.append({
                                'primary': is_primary,
                                'x': x, 'y': y, 'w': w, 'h': h
                            })

            # ALWAYS prefer primary monitor for wallpaper
            primary = [m for m in monitors if m['primary']]
            if primary:
                mon = primary[0]
                print(f"[CYBERCORE] Using PRIMARY monitor: {mon['w']}x{mon['h']} at +{mon['x']}+{mon['y']}")
            elif monitors:
                mon = monitors[0]
                print(f"[CYBERCORE] No primary marked, using first monitor: {mon['w']}x{mon['h']}")
            else:
                return

            MONITOR_X = mon['x']
            MONITOR_Y = mon['y']
            MONITOR_WIDTH = mon['w']
            MONITOR_HEIGHT = mon['h']
            CENTER_X = MONITOR_WIDTH // 2 + 80
            CENTER_Y = MONITOR_HEIGHT // 2 + 40

    except Exception as e:
        print(f"[CYBERCORE] Monitor detection failed: {e}")


# =============================================================================
# GLSL SHADERS (OpenGL 2.1 compatible for broad support)
# =============================================================================

VERTEX_SHADER_SRC = """
#version 120
attribute vec2 position;
varying vec2 fragCoord;
void main() {
    fragCoord = position * 0.5 + 0.5;
    gl_Position = vec4(position, 0.0, 1.0);
}
"""

FRAGMENT_SHADER_SRC = """
#version 120
varying vec2 fragCoord;

uniform float u_time;
uniform vec2 u_resolution;
uniform vec2 u_center;

// Kollaborations-Layer Uniforms
uniform float u_mood;       // 0.0 = passive (deep red), 1.0 = active (bright/cyan)
uniform float u_halo;       // Halo intensity (0.0 - 1.0)
uniform float u_glitch;     // Glitch intensity (0.0 = none, 1.0 = max)
uniform float u_think;      // Thinking intensity (0.0 = idle, 1.0 = deep thought)
uniform vec3 u_event_color; // Event-specific color (each event has unique color)
uniform sampler2D u_frank_tex; // Frank character texture
uniform float u_eye_blink;      // 0.0 = eyes open, 1.0 = eyes fully closed
uniform vec2  u_eye_look;       // gaze direction: x(-1=left,1=right), y(-1=down,1=up)
uniform float u_eye_open_top;   // top lid openness (1.0=normal, 0.5=droopy/tired, 0.0=closed)
uniform float u_eye_open_bot;   // bottom lid openness (1.0=normal, 0.7=happy squint, 0.0=closed)

// ============================================
// SIMPLEX NOISE
// ============================================
vec3 mod289(vec3 x) { return x - floor(x * (1.0 / 289.0)) * 289.0; }
vec2 mod289(vec2 x) { return x - floor(x * (1.0 / 289.0)) * 289.0; }
vec3 permute(vec3 x) { return mod289(((x*34.0)+1.0)*x); }

float snoise(vec2 v) {
    const vec4 C = vec4(0.211324865405187, 0.366025403784439,
                        -0.577350269189626, 0.024390243902439);
    vec2 i  = floor(v + dot(v, C.yy));
    vec2 x0 = v - i + dot(i, C.xx);
    vec2 i1 = (x0.x > x0.y) ? vec2(1.0, 0.0) : vec2(0.0, 1.0);
    vec4 x12 = x0.xyxy + C.xxzz;
    x12.xy -= i1;
    i = mod289(i);
    vec3 p = permute(permute(i.y + vec3(0.0, i1.y, 1.0))
                            + i.x + vec3(0.0, i1.x, 1.0));
    vec3 m = max(0.5 - vec3(dot(x0,x0), dot(x12.xy,x12.xy),
                            dot(x12.zw,x12.zw)), 0.0);
    m = m*m;
    m = m*m;
    vec3 x = 2.0 * fract(p * C.www) - 1.0;
    vec3 h = abs(x) - 0.5;
    vec3 ox = floor(x + 0.5);
    vec3 a0 = x - ox;
    m *= 1.79284291400159 - 0.85373472095314 * (a0*a0 + h*h);
    vec3 g;
    g.x = a0.x * x0.x + h.x * x0.y;
    g.yz = a0.yz * x12.xz + h.yz * x12.yw;
    return 130.0 * dot(m, g);
}

// ============================================
// OPTIMIZED FBM - Nur 2 Oktaven
// ============================================
float fbm2(vec2 p) {
    return snoise(p) * 0.6 + snoise(p * 2.0) * 0.4;
}

// ============================================
// MAIN SHADER - DENSE PLASMA KNÄUEL
// Triple-Layer + High-Freq Jitter + Deep Crimson
// ============================================
void main() {
    float t = u_time * 0.07;
    float tFast = u_time * 0.5;

    // ========================================
    // 1. KOORDINATEN
    // ========================================
    vec2 uv = (gl_FragCoord.xy - u_center) / u_resolution.y;
    float d = length(uv);

    // ========================================
    // 2. DEEP CRIMSON PALETTE (Kein Orange!)
    // ========================================
    vec3 BLOOD_BLACK = vec3(0.08, 0.0, 0.0);      // Fast Schwarz
    vec3 DEEP_CRIMSON = vec3(0.35, 0.0, 0.0);     // Tiefes Karmesin
    vec3 CRIMSON = vec3(0.7, 0.0, 0.0);           // Karmesin
    vec3 BRIGHT_RED = vec3(0.95, 0.08, 0.0);      // Hellrot
    vec3 WHITE_HOT = vec3(1.0, 0.92, 0.85);       // Weißglut

    // ========================================
    // 3. DOMAIN WARPING + HIGH-FREQ JITTER
    // ========================================
    vec2 uvW = uv;
    // Grobe Verzerrung
    uvW += cos(uvW.yx * 3.5 + t * 0.8) * 0.12;
    uvW += sin(uvW.yx * 7.0 - t * 0.6) * 0.06;
    // HIGH-FREQ JITTER (sanftes Kanten-Atmen)
    uvW += sin(uvW.yx * 15.0 + tFast * 1.0) * 0.008;

    // Filament-Puls (langsames Atmen)
    float pulse = 0.85 + 0.15 * sin(t * 3.0);

    // ========================================
    // 4. LAYER 1: GROBE STRUKTUREN (Volumen)
    // ========================================
    float thinkSpeed = 1.0 + u_think * 0.3;  // Filamente drehen nur leicht schneller beim Denken
    float rotA = t * 0.3 * thinkSpeed;
    vec2 uvA = vec2(
        uvW.x * cos(rotA) - uvW.y * sin(rotA),
        uvW.x * sin(rotA) + uvW.y * cos(rotA)
    );

    // Mehrere Noise-Stränge für Dichte
    float nA1 = snoise(uvA * 3.0 + t * 0.2);
    float nA2 = snoise(uvA * 3.5 + vec2(0.7, 0.3) + t * 0.15);
    float nA3 = snoise(uvA * 4.0 - t * 0.18 + 20.0);

    // Scharfe Filamente: 1/(1 + abs(n)*k)
    float filA = 1.0 / (1.0 + abs(nA1) * 35.0);
    filA += 1.0 / (1.0 + abs(nA2) * 40.0) * 0.8;
    filA += 1.0 / (1.0 + abs(nA3) * 45.0) * 0.6;

    // ========================================
    // 5. LAYER 2: FEINE FILAMENTE (gegenläufig)
    // ========================================
    float rotB = -t * 0.25 * thinkSpeed;
    vec2 uvB = vec2(
        uvW.x * cos(rotB) - uvW.y * sin(rotB),
        uvW.x * sin(rotB) + uvW.y * cos(rotB)
    );

    float nB1 = snoise(uvB * 4.5 - t * 0.22 + 50.0);
    float nB2 = snoise(uvB * 5.0 + vec2(0.4, 0.8) - t * 0.18 + 70.0);

    float filB = 1.0 / (1.0 + abs(nB1) * 50.0);
    filB += 1.0 / (1.0 + abs(nB2) * 55.0) * 0.7;

    // ========================================
    // 6. LAYER 3: MICRO-FILAMENTE (schnell)
    // ========================================
    float rotC = t * 0.4 * thinkSpeed;
    vec2 uvC = vec2(
        uvW.x * cos(rotC) - uvW.y * sin(rotC),
        uvW.x * sin(rotC) + uvW.y * cos(rotC)
    );

    float nC = snoise(uvC * 6.0 + tFast * 0.5 + 100.0);
    float filC = 1.0 / (1.0 + abs(nC) * 60.0) * 0.5;

    // ========================================
    // 7. KOMBINATION + PULS
    // ========================================
    float filTotal = (filA + filB + filC) * pulse;

    // Kreuzungs-Boost
    float cross = filA * filB * 3.0 + filB * filC * 2.0;
    cross = min(cross, 1.5);

    // ========================================
    // 8. MASKEN
    // ========================================
    float edgeMask = 1.0 - d * 5.5;
    edgeMask = max(0.0, edgeMask);
    edgeMask *= edgeMask;
    float coreMask = min(d * 60.0, 1.0);
    float mask = coreMask * edgeMask;

    // ========================================
    // 9. FARBEN (Deep Crimson Gradient + Think Color Shift)
    // ========================================
    // Think-Farben: Electric Blue/Cyan beim Denken
    vec3 THINK_DEEP    = vec3(0.0, 0.05, 0.35);     // Tiefes Blau (statt DEEP_CRIMSON)
    vec3 THINK_MID     = vec3(0.0, 0.2, 0.7);       // Mittleres Blau (statt CRIMSON)
    vec3 THINK_BRIGHT  = vec3(0.0, 0.5, 0.95);      // Helles Cyan-Blau (statt BRIGHT_RED)
    vec3 THINK_BLACK   = vec3(0.0, 0.0, 0.08);      // Blau-Schwarz (statt BLOOD_BLACK)

    // Palette smooth blenden basierend auf u_think
    vec3 col_black  = mix(BLOOD_BLACK, THINK_BLACK, u_think);
    vec3 col_deep   = mix(DEEP_CRIMSON, THINK_DEEP, u_think);
    vec3 col_mid    = mix(CRIMSON, THINK_MID, u_think);
    vec3 col_bright = mix(BRIGHT_RED, THINK_BRIGHT, u_think);

    vec3 color = vec3(0.0);

    // Additives Glühen
    color += col_black * mask * 0.5;
    color += col_deep * filTotal * mask * 2.0;
    color += col_mid * filTotal * filTotal * mask * 3.0;
    color += col_bright * filTotal * filTotal * filTotal * mask * 2.0;

    // Kreuzungen werden weiß
    color += WHITE_HOT * cross * cross * mask * 2.0;

    // ========================================
    // 10. FRANK CHARACTER (Sample texture, remove plasma behind)
    // ========================================

    // Sample Frank texture
    float frankRadius = 0.14;
    vec2 texCoord = uv / (frankRadius * 2.0) + 0.5;

    // ---- Skeletal animation: rigid body-part rotation ----
    // Each body part rotates as a rigid piece around its joint pivot.
    // Hierarchy: base → torso → head, plus independent bolt wiggles.
    float anim = u_time;

    // Organic time signals (non-harmonic frequencies → never-repeating pattern)
    float m1 = sin(anim * 0.71);
    float m2 = sin(anim * 0.53 + 2.3);
    float m3 = sin(anim * 0.43 + 5.1);
    float m4 = sin(anim * 1.13 + 1.1);
    float m5 = sin(anim * 0.37 + 3.7);
    float m6 = sin(anim * 0.89 + 0.7);

    // Joint rotation angles (radians) — enhanced for visible life
    float baseRot  = m1 * 0.012 + m3 * 0.008;                   // Base sway
    float torsoRot = m2 * 0.025 + m5 * 0.016;                   // Torso lean
    float headRot  = m4 * 0.048 + m6 * 0.032 + m2 * 0.020;     // Head tilt (most motion)
    float lBoltRot = m3 * 0.10 + m1 * 0.06;                     // Left bolt wiggle
    float rBoltRot = -m5 * 0.10 - m4 * 0.06;                    // Right bolt (counter-phase)

    // Occasional attention shift (when two slow waves align → larger movement)
    float shiftWave = sin(anim * 0.067) * sin(anim * 0.113);
    float shiftActive = smoothstep(0.4, 0.8, abs(shiftWave));
    headRot  += shiftWave * 0.05 * shiftActive;
    torsoRot += shiftWave * 0.025 * shiftActive;

    // Breathing: horizontal torso pulse (more visible)
    float breathAmt = sin(anim * 1.27) * 0.008 + sin(anim * 0.61) * 0.005;
    // Vertical bob
    float bob = m1 * 0.005 + m6 * 0.003;

    vec2 tc = texCoord;
    float yN = texCoord.y;  // Original y for region masks (0=bottom, 1=top)

    // Global vertical bob
    tc.y += bob;

    // --- BASE SWAY: pivot at character base (0.50, 0.11) ---
    float baseW = smoothstep(0.05, 0.18, yN);
    float baseA = -baseRot * baseW;
    float baseCa = cos(baseA); float baseSa = sin(baseA);
    vec2 baseD = tc - vec2(0.50, 0.11);
    tc = vec2(0.50, 0.11) + vec2(baseD.x*baseCa - baseD.y*baseSa,
                                  baseD.x*baseSa + baseD.y*baseCa);

    // --- TORSO LEAN: pivot at waist (0.50, 0.45) ---
    float torsoW = smoothstep(0.35, 0.50, yN);
    float torsoA = -torsoRot * torsoW;
    float torsoCa = cos(torsoA); float torsoSa = sin(torsoA);
    vec2 torsoD = tc - vec2(0.50, 0.45);
    tc = vec2(0.50, 0.45) + vec2(torsoD.x*torsoCa - torsoD.y*torsoSa,
                                  torsoD.x*torsoSa + torsoD.y*torsoCa);

    // --- BREATHING: torso horizontal scale ---
    float breathW = smoothstep(0.15, 0.35, yN) * (1.0 - smoothstep(0.52, 0.65, yN));
    tc.x += (tc.x - 0.5) * breathAmt * breathW * 3.0;

    // --- HEAD TILT: pivot at neck (0.50, 0.50) ---
    float headW = smoothstep(0.46, 0.56, yN);
    float headA = -headRot * headW;
    float headCa = cos(headA); float headSa = sin(headA);
    vec2 headD = tc - vec2(0.50, 0.50);
    tc = vec2(0.50, 0.50) + vec2(headD.x*headCa - headD.y*headSa,
                                  headD.x*headSa + headD.y*headCa);

    // --- LEFT BOLT WIGGLE: pivot at bolt attachment (0.18, 0.63) ---
    float lBoltW = (1.0 - smoothstep(0.05, 0.22, tc.x))
                 * smoothstep(0.56, 0.62, yN) * (1.0 - smoothstep(0.72, 0.78, yN));
    float lBoltA = -lBoltRot * lBoltW;
    float lBoltCa = cos(lBoltA); float lBoltSa = sin(lBoltA);
    vec2 lBoltD = tc - vec2(0.18, 0.63);
    tc = mix(tc, vec2(0.18, 0.63) + vec2(lBoltD.x*lBoltCa - lBoltD.y*lBoltSa,
                                          lBoltD.x*lBoltSa + lBoltD.y*lBoltCa), lBoltW);

    // --- RIGHT BOLT WIGGLE: pivot at bolt attachment (0.82, 0.63) ---
    float rBoltW = smoothstep(0.78, 0.95, tc.x)
                 * smoothstep(0.56, 0.62, yN) * (1.0 - smoothstep(0.72, 0.78, yN));
    float rBoltA = -rBoltRot * rBoltW;
    float rBoltCa = cos(rBoltA); float rBoltSa = sin(rBoltA);
    vec2 rBoltD = tc - vec2(0.82, 0.63);
    tc = mix(tc, vec2(0.82, 0.63) + vec2(rBoltD.x*rBoltCa - rBoltD.y*rBoltSa,
                                          rBoltD.x*rBoltSa + rBoltD.y*rBoltCa), rBoltW);

    texCoord = tc;
    // ---- End skeletal animation ----

    vec4 frankTex = texture2D(u_frank_tex, texCoord);
    float inBounds = step(0.001, texCoord.x) * step(texCoord.x, 0.999)
                   * step(0.001, texCoord.y) * step(texCoord.y, 0.999);
    frankTex *= inBounds;

    // ========================================
    // 10b. EYE ANIMATION (RoboEyes-style)
    // ========================================
    // Eye socket centers and dimensions in texture UV space
    // (0,0)=bottom-left after OpenGL flip; eyes at ~32% from top of character)
    const vec2 EYE_L = vec2(0.355, 0.675);   // Left eye center
    const vec2 EYE_R = vec2(0.645, 0.675);   // Right eye center
    const float EYE_W = 0.078;               // Eye half-width
    const float EYE_H = 0.036;               // Eye half-height

    // Smooth eye region masks (1.0 = fully inside eye, 0.0 = outside)
    vec2 dL = abs(texCoord - EYE_L);
    float inL = (1.0 - smoothstep(EYE_W * 0.82, EYE_W, dL.x))
              * (1.0 - smoothstep(EYE_H * 0.82, EYE_H, dL.y));
    vec2 dR = abs(texCoord - EYE_R);
    float inR = (1.0 - smoothstep(EYE_W * 0.82, EYE_W, dR.x))
              * (1.0 - smoothstep(EYE_H * 0.82, EYE_H, dR.y));
    float eyeRegion = max(inL, inR);

    if (eyeRegion > 0.01) {
        // Which eye? Get local coordinates (-1..1 within eye)
        vec2 eyeC = inL > inR ? EYE_L : EYE_R;
        vec2 loc = (texCoord - eyeC) / vec2(EYE_W, EYE_H);

        // Dark socket base (dim original texture for empty socket look)
        vec3 socketDark = frankTex.rgb * 0.08;

        // --- BLINK + MOOD LIDS (asymmetric, EMO-style expressions) ---
        // Blink overrides everything; mood modifies resting lid position
        float blinkOpen = 1.0 - u_eye_blink;
        float topOpen = min(blinkOpen, u_eye_open_top);  // mood can droop top lid
        float botOpen = min(blinkOpen, u_eye_open_bot);  // mood can raise bottom lid (happy squint)
        float topLid = smoothstep(topOpen, topOpen + 0.18, loc.y);
        float botLid = smoothstep(botOpen, botOpen + 0.18, -loc.y);
        float eyeVisible = (1.0 - topLid) * (1.0 - botLid);

        // Eyelid color: dark face material with slight green tint
        vec3 lidColor = vec3(0.02, 0.04, 0.02);

        // --- GAZE: bright pupil area shifts with look direction ---
        vec2 gaze = u_eye_look * vec2(0.38, 0.28);
        vec2 gazeLoc = loc - gaze;

        // Pupil: soft rounded rectangle (brighter in center)
        vec2 pd = abs(gazeLoc);
        float pupilX = 1.0 - smoothstep(0.20, 0.70, pd.x);
        float pupilY = 1.0 - smoothstep(0.15, 0.60, pd.y);
        float pupil = pupilX * pupilY;

        // Inner bright core (gives depth to the gaze)
        float coreX = 1.0 - smoothstep(0.05, 0.35, pd.x);
        float coreY = 1.0 - smoothstep(0.03, 0.25, pd.y);
        float core = coreX * coreY;

        // --- LED SCAN LINES (horizontal, matching cyberpunk aesthetic) ---
        float scanFreq = texCoord.y * 300.0;
        float scanWave = sin(scanFreq * 3.14159) * 0.5 + 0.5;
        float scanMask = mix(0.6, 1.0, smoothstep(0.25, 0.75, scanWave));

        // --- COMPOSE EYE ---
        vec3 glowColor = vec3(0.60, 0.95, 0.12);  // Yellow-green LED
        vec3 coreColor = vec3(0.85, 1.0, 0.65);    // Brighter center

        float brightness = (0.15 + pupil * 0.55 + core * 0.30) * scanMask;
        vec3 eyeGlow = mix(glowColor, coreColor, core * 0.6) * brightness * eyeVisible;

        // Edge ambient (subtle glow at socket edges even when looking away)
        float edgeDist = max(abs(loc.x), abs(loc.y));
        float ambient = (1.0 - smoothstep(0.5, 1.0, edgeDist)) * 0.08 * eyeVisible;
        eyeGlow += glowColor * ambient;

        // Final eye pixel: dark socket + glow, with eyelid overlay
        vec3 eyeResult = socketDark + eyeGlow;
        eyeResult = mix(eyeResult, lidColor, max(topLid, botLid) * (1.0 - eyeVisible));

        // Blend procedural eyes into frank texture
        frankTex.rgb = mix(frankTex.rgb, eyeResult, eyeRegion);
    }

    // DEBUG: Red dots at eye centers to verify coordinate alignment
    float dbgL = step(length(texCoord - EYE_L), 0.02);
    float dbgR = step(length(texCoord - EYE_R), 0.02);
    if (dbgL > 0.5 || dbgR > 0.5) {
        frankTex.rgb = vec3(1.0, 0.0, 0.0);
        frankTex.a = 1.0;
    }

    // Hard cutoff: remove ALL plasma within entire visible core area
    // Plasma edge is at d≈0.182 (edgeMask=1-d*5.5), cut at 0.22 for margin
    float suppressPlasma = step(0.22, length(uv));
    color *= suppressPlasma;

    // Core glow value (used by section 11 for mood/event effects)
    float coreGlow = exp(-d * 45.0);

    // ========================================
    // 11. KOLLABORATIONS-LAYER (Mood, Halo, Glitch)
    // ========================================

    // EVENT-FARBE: Jedes Event hat seine eigene Farbe
    // u_event_color wird direkt von Python pro Event-Typ gesetzt
    vec3 eventColor = u_event_color;

    // MOOD: Event-Farbe wird in den Kern gemischt
    color = mix(color, color + eventColor * 0.4, u_mood * coreGlow);
    // Zusätzlich leichtes Glühen der Filamente in Event-Farbe
    color += eventColor * filTotal * mask * u_mood * 0.15;

    // HALO: Sanfte radiale Lichtwelle in Event-Farbe
    float haloWave = sin(d * 8.0 - u_time * 0.8) * 0.5 + 0.5;
    float haloRing = exp(-d * 6.0) * haloWave * u_halo;
    color += eventColor * haloRing * 1.8;

    // GLITCH: Verzerrung und Farbseparation bei Errors
    vec2 glitchOffset = vec2(
        sin(uv.y * 50.0 + u_time * 20.0) * u_glitch * 0.02,
        cos(uv.x * 40.0 + u_time * 15.0) * u_glitch * 0.015
    );
    float glitchNoise = snoise(uv * 30.0 + u_time * 5.0) * u_glitch;

    // Chromatic Aberration bei Glitch
    vec3 glitchColor = color;
    glitchColor.r += glitchNoise * 0.3;
    glitchColor.b -= glitchNoise * 0.2;
    color = mix(color, glitchColor, u_glitch);

    // Scanline-Glitch
    float scanGlitch = step(0.98, sin(uv.y * 200.0 + u_time * 50.0)) * u_glitch;
    color += vec3(1.0, 0.0, 0.0) * scanGlitch * 0.5;

    // ========================================
    // 12. COMPOSITING
    // ========================================
    // Scharfer Rand
    float falloff = 1.0 - d * 5.2;
    falloff = max(0.0, falloff);
    falloff *= falloff;

    vec3 finalColor = color * falloff;

    // Gamma
    finalColor = sqrt(finalColor * 0.85);

    finalColor = min(finalColor, vec3(1.0));

    // Composite Frank character ON TOP (after falloff/gamma, not darkened)
    vec3 frankColor = frankTex.rgb * 1.4;  // Well-lit character
    frankColor = min(frankColor, vec3(1.0));
    // Smooth alpha edge for anti-aliasing (slightly soften hard alpha transitions)
    float frankAlpha = smoothstep(0.02, 0.15, frankTex.a);
    finalColor = mix(finalColor, frankColor, frankAlpha);

    gl_FragColor = vec4(finalColor, 1.0);
}
"""


# =============================================================================
# TELEMETRY COLLECTOR
# =============================================================================
class TelemetryCollector(QThread):
    data_updated = Signal(dict)

    def __init__(self):
        super().__init__()
        self.running = True
        self.data = {
            'cpu_load': 0.0, 'gpu_load': 0.0, 'ram_used': 0.0, 'ram_total': 32.0,
            'cpu_temp': 0.0, 'gpu_temp': 0.0
        }
        self._last_idle = 0
        self._last_total = 0
        # Cache für Hardware-Pfade (einmalig ermitteln)
        self._gpu_load_path = None
        self._cpu_temp_path = None
        self._gpu_temp_path = None
        self._paths_initialized = False

    def _init_hardware_paths(self):
        """Einmalig Hardware-Pfade ermitteln."""
        if self._paths_initialized:
            return
        self._gpu_load_path = self._find_gpu_load_path()
        self._cpu_temp_path = self._find_cpu_temp_path()
        self._gpu_temp_path = self._find_gpu_temp_path()
        self._paths_initialized = True

    def _find_gpu_load_path(self):
        """Dynamisch GPU-Load-Pfad finden."""
        for card in range(5):
            path = f'/sys/class/drm/card{card}/device/gpu_busy_percent'
            if os.path.exists(path):
                return path
        return None

    def _find_cpu_temp_path(self):
        """Dynamisch CPU-Temperatur-Pfad finden."""
        # Suche in hwmon-Geräten nach coretemp oder k10temp
        hwmon_base = '/sys/class/hwmon'
        if os.path.exists(hwmon_base):
            for hwmon in sorted(os.listdir(hwmon_base)):
                hwmon_path = os.path.join(hwmon_base, hwmon)
                name_file = os.path.join(hwmon_path, 'name')
                if os.path.exists(name_file):
                    try:
                        with open(name_file, 'r') as f:
                            name = f.read().strip()
                            if name in ('coretemp', 'k10temp', 'zenpower'):
                                temp_input = os.path.join(hwmon_path, 'temp1_input')
                                if os.path.exists(temp_input):
                                    return temp_input
                    except (IOError, OSError):
                        pass
        # Fallback: Suche generisch
        for hwmon in range(10):
            path = f'/sys/class/hwmon/hwmon{hwmon}/temp1_input'
            if os.path.exists(path):
                return path
        return None

    def _find_gpu_temp_path(self):
        """Dynamisch GPU-Temperatur-Pfad finden."""
        # AMD GPU: drm/card*/device/hwmon/*/temp1_input
        for card in range(5):
            hwmon_base = f'/sys/class/drm/card{card}/device/hwmon'
            if os.path.exists(hwmon_base):
                for hwmon in os.listdir(hwmon_base):
                    temp_path = os.path.join(hwmon_base, hwmon, 'temp1_input')
                    if os.path.exists(temp_path):
                        return temp_path
        # NVIDIA: nvidia-smi oder hwmon mit amdgpu/nouveau
        hwmon_base = '/sys/class/hwmon'
        if os.path.exists(hwmon_base):
            for hwmon in sorted(os.listdir(hwmon_base)):
                hwmon_path = os.path.join(hwmon_base, hwmon)
                name_file = os.path.join(hwmon_path, 'name')
                if os.path.exists(name_file):
                    try:
                        with open(name_file, 'r') as f:
                            name = f.read().strip()
                            if name in ('amdgpu', 'nouveau', 'nvidia'):
                                temp_input = os.path.join(hwmon_path, 'temp1_input')
                                if os.path.exists(temp_input):
                                    return temp_input
                    except (IOError, OSError):
                        pass
        return None

    def run(self):
        # Einmalig Hardware-Pfade ermitteln
        self._init_hardware_paths()
        while self.running and not _shutdown.is_set():
            try:
                self._collect()
                self.data_updated.emit(self.data.copy())
            except Exception as e:
                print(f"[CYBERCORE] Telemetry collection error: {type(e).__name__}: {e}")
            time.sleep(2.0)

    def _collect(self):
        try:
            with open('/proc/stat', 'r') as f:
                parts = f.readline().split()
                idle = int(parts[4])
                total = sum(int(p) for p in parts[1:])
                if self._last_total > 0:
                    d_idle = idle - self._last_idle
                    d_total = total - self._last_total
                    if d_total > 0:
                        self.data['cpu_load'] = 100.0 * (1.0 - d_idle / d_total)
                self._last_idle, self._last_total = idle, total
        except (IOError, OSError, ValueError, IndexError):
            pass  # HIGH #6: Specific exceptions for /proc/stat parsing

        # GPU Load (cached path)
        if self._gpu_load_path:
            try:
                with open(self._gpu_load_path, 'r') as f:
                    self.data['gpu_load'] = float(f.read().strip())
            except (IOError, OSError, ValueError):
                pass

        try:
            with open('/proc/meminfo', 'r') as f:
                lines = f.readlines()
                total = int(lines[0].split()[1])
                avail = int(lines[2].split()[1])
                self.data['ram_total'] = total / 1024 / 1024  # GB
                self.data['ram_used'] = (total - avail) / 1024 / 1024  # GB
        except (IOError, OSError, ValueError, IndexError):
            pass  # HIGH #6: Specific exceptions for /proc/meminfo parsing

        # CPU Temp (cached path)
        if self._cpu_temp_path:
            try:
                with open(self._cpu_temp_path, 'r') as f:
                    self.data['cpu_temp'] = float(f.read().strip()) / 1000
            except (IOError, OSError, ValueError):
                pass

        # GPU Temp (cached path)
        if self._gpu_temp_path:
            try:
                with open(self._gpu_temp_path, 'r') as f:
                    self.data['gpu_temp'] = float(f.read().strip()) / 1000
            except (IOError, OSError, ValueError):
                self.data['gpu_temp'] = self.data['cpu_temp'] * 0.9
        else:
            self.data['gpu_temp'] = self.data['cpu_temp'] * 0.9

    def stop(self):
        self.running = False
        self.wait()


# =============================================================================
# EVENT LISTENER (UDP)
# =============================================================================
EVENT_PORT = 8198

class EventListener(QThread):
    """Listens for events from aicore components via UDP."""
    event_received = Signal(dict)

    def __init__(self):
        super().__init__()
        self.running = True
        self.sock = None

    def run(self):
        # HIGH #5: Use try/finally to ensure socket is always closed
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.sock.bind(("127.0.0.1", EVENT_PORT))
            self.sock.settimeout(0.5)  # 500ms timeout for clean shutdown
            print(f"[CYBERCORE] Event listener started on port {EVENT_PORT}")
        except OSError as e:
            print(f"[CYBERCORE] Event listener bind failed: {e}")
            return
        except Exception as e:
            print(f"[CYBERCORE] Event listener setup failed: {type(e).__name__}: {e}")
            return

        try:
            while self.running and not _shutdown.is_set():
                try:
                    data, addr = self.sock.recvfrom(4096)
                    event = json.loads(data.decode('utf-8'))
                    self.event_received.emit(event)
                except socket.timeout:
                    continue
                except json.JSONDecodeError as e:
                    print(f"[CYBERCORE] Invalid JSON event: {e}")
                    continue
                except UnicodeDecodeError as e:
                    print(f"[CYBERCORE] Event decode error: {e}")
                    continue
                except OSError as e:
                    if self.running:
                        print(f"[CYBERCORE] Socket error: {e}")
                    break
        finally:
            # HIGH #5: Ensure socket is always closed
            if self.sock:
                try:
                    self.sock.close()
                except OSError:
                    pass
                self.sock = None

    def stop(self):
        self.running = False
        self.wait()


# =============================================================================
# GLSL PLASMA RENDERER
# =============================================================================
class PlasmaGLWidget(QOpenGLWidget):
    """
    OpenGL widget with GLSL fragment shader.
    Uses OpenGL 2.1 for maximum compatibility.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.time = 0.0
        self.shader_program = None
        self.initialized = False
        self.frank_tex_id = 0

        # Kollaborations-Layer state
        self.mood = 0.0      # 0.0 = passive, 1.0 = active (CPU-driven)
        self.halo = 0.0      # Halo intensity
        self.glitch = 0.0    # Glitch intensity
        self.think = 0.0     # Thinking intensity (0.0 = idle, 1.0 = deep thought)
        self.event_color = (0.3, 0.0, 0.0)  # Default: dim red (blends into base)

        # Eye animation state (driven by CPU)
        self.eye_blink = 0.0      # 0.0 = eyes open, 1.0 = fully closed
        self.eye_look_x = 0.0     # Horizontal gaze (-1 left, +1 right)
        self.eye_look_y = 0.0     # Vertical gaze (-1 down, +1 up)
        self.eye_open_top = 1.0   # Top lid (1.0=normal, 0.5=tired/angry)
        self.eye_open_bot = 1.0   # Bottom lid (1.0=normal, 0.7=happy squint)

        # Animation timer - 20 FPS (optimized for GPU budget)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(50)  # 50ms = 20 FPS

    def _tick(self):
        self.time += 0.05
        self.update()

    def initializeGL(self):
        """Initialize OpenGL resources."""
        if not OPENGL_AVAILABLE:
            print("[CYBERCORE] OpenGL not available")
            return

        try:
            # Compile shaders using PyOpenGL
            vertex_shader = shaders.compileShader(VERTEX_SHADER_SRC, GL_VERTEX_SHADER)
            fragment_shader = shaders.compileShader(FRAGMENT_SHADER_SRC, GL_FRAGMENT_SHADER)
            self.shader_program = shaders.compileProgram(vertex_shader, fragment_shader)

            print("[CYBERCORE] GLSL shaders compiled successfully")
            self.initialized = True

            # Load Frank character texture
            self._load_frank_texture()

        except Exception as e:
            print(f"[CYBERCORE] Shader compilation failed: {e}")
            self.initialized = False

    def _load_frank_texture(self):
        """Load Frank character PNG as OpenGL texture with high-quality scaling."""
        try:
            from PIL import Image, ImageFilter
            if not os.path.exists(FRANK_ICON_PATH):
                print(f"[CYBERCORE] Frank icon not found: {FRANK_ICON_PATH}")
                return

            img = Image.open(FRANK_ICON_PATH).convert("RGBA")
            orig_size = img.size

            # Pre-scale to display size with LANCZOS for best quality.
            # frankRadius=0.14, screen height=600 → render diameter ~168px.
            # Use 256x256 (slight oversample for GL_LINEAR quality).
            target_size = 256
            img = img.resize((target_size, target_size), Image.LANCZOS)

            # Sharpen to counteract any softness from downscale
            img = img.filter(ImageFilter.SHARPEN)

            # Flip vertically for OpenGL coordinate system (origin at bottom-left)
            img = img.transpose(Image.FLIP_TOP_BOTTOM)
            img_data = img.tobytes()

            self.frank_tex_id = int(glGenTextures(1))
            glBindTexture(GL_TEXTURE_2D, self.frank_tex_id)
            glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, img.width, img.height,
                         0, GL_RGBA, GL_UNSIGNED_BYTE, img_data)
            # GL_LINEAR (no mipmaps) - texture is pre-scaled to ~display size
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE)
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE)
            # Anisotropic filtering for sharper texture sampling
            try:
                from OpenGL.GL.EXT.texture_filter_anisotropic import (
                    GL_MAX_TEXTURE_MAX_ANISOTROPY_EXT,
                    GL_TEXTURE_MAX_ANISOTROPY_EXT,
                )
                max_aniso = glGetFloatv(GL_MAX_TEXTURE_MAX_ANISOTROPY_EXT)
                glTexParameterf(GL_TEXTURE_2D, GL_TEXTURE_MAX_ANISOTROPY_EXT, max_aniso)
                print(f"[CYBERCORE] Anisotropic filtering: {max_aniso}x")
            except Exception:
                pass  # Extension not available, GL_LINEAR is fine
            glBindTexture(GL_TEXTURE_2D, 0)

            print(f"[CYBERCORE] Frank texture loaded: {orig_size[0]}x{orig_size[1]} → {target_size}x{target_size} (LANCZOS+SHARPEN)")
        except Exception as e:
            print(f"[CYBERCORE] Frank texture loading failed: {e}")
            self.frank_tex_id = 0

    def paintGL(self):
        """Render using GLSL shader."""
        if not OPENGL_AVAILABLE or not self.initialized:
            # Fallback: just clear to black
            glClearColor(0.01, 0.0, 0.0, 1.0)
            glClear(GL_COLOR_BUFFER_BIT)
            return

        # Clear
        glClearColor(0.01, 0.0, 0.0, 1.0)
        glClear(GL_COLOR_BUFFER_BIT)

        # Use shader program
        glUseProgram(self.shader_program)

        # Set uniforms
        w = self.width() or MONITOR_WIDTH
        h = self.height() or MONITOR_HEIGHT

        loc_time = glGetUniformLocation(self.shader_program, "u_time")
        loc_res = glGetUniformLocation(self.shader_program, "u_resolution")
        loc_center = glGetUniformLocation(self.shader_program, "u_center")
        loc_mood = glGetUniformLocation(self.shader_program, "u_mood")
        loc_halo = glGetUniformLocation(self.shader_program, "u_halo")
        loc_glitch = glGetUniformLocation(self.shader_program, "u_glitch")
        loc_think = glGetUniformLocation(self.shader_program, "u_think")
        loc_event_color = glGetUniformLocation(self.shader_program, "u_event_color")

        if loc_time >= 0:
            glUniform1f(loc_time, self.time)
        if loc_res >= 0:
            glUniform2f(loc_res, float(w), float(h))
        if loc_center >= 0:
            glUniform2f(loc_center, float(CENTER_X), float(h - CENTER_Y))
        if loc_mood >= 0:
            glUniform1f(loc_mood, self.mood)
        if loc_halo >= 0:
            glUniform1f(loc_halo, self.halo)
        if loc_glitch >= 0:
            glUniform1f(loc_glitch, self.glitch)
        if loc_think >= 0:
            glUniform1f(loc_think, self.think)
        if loc_event_color >= 0:
            glUniform3f(loc_event_color, self.event_color[0], self.event_color[1], self.event_color[2])

        # Eye animation uniforms
        loc_eye_blink = glGetUniformLocation(self.shader_program, "u_eye_blink")
        loc_eye_look = glGetUniformLocation(self.shader_program, "u_eye_look")
        loc_eye_top = glGetUniformLocation(self.shader_program, "u_eye_open_top")
        loc_eye_bot = glGetUniformLocation(self.shader_program, "u_eye_open_bot")
        if loc_eye_blink >= 0:
            glUniform1f(loc_eye_blink, self.eye_blink)
        if loc_eye_look >= 0:
            glUniform2f(loc_eye_look, self.eye_look_x, self.eye_look_y)
        if loc_eye_top >= 0:
            glUniform1f(loc_eye_top, self.eye_open_top)
        if loc_eye_bot >= 0:
            glUniform1f(loc_eye_bot, self.eye_open_bot)

        # Bind Frank character texture
        loc_frank = glGetUniformLocation(self.shader_program, "u_frank_tex")
        if loc_frank >= 0 and self.frank_tex_id:
            glActiveTexture(GL_TEXTURE0)
            glBindTexture(GL_TEXTURE_2D, self.frank_tex_id)
            glUniform1i(loc_frank, 0)

        # Draw fullscreen quad using immediate mode (most compatible)
        glBegin(GL_TRIANGLE_STRIP)
        glVertex2f(-1.0, -1.0)
        glVertex2f(1.0, -1.0)
        glVertex2f(-1.0, 1.0)
        glVertex2f(1.0, 1.0)
        glEnd()

        glUseProgram(0)

    def resizeGL(self, w, h):
        """Handle resize."""
        glViewport(0, 0, w, h)


# =============================================================================
# MAIN WINDOW
# =============================================================================
class NeuralCybercoreWindow(QWidget):
    """Main wallpaper window."""

    def __init__(self):
        super().__init__()

        self.setWindowTitle("FRANK NEURAL CORE")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnBottomHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)

        self._setup_emergency_exit()
        self.setGeometry(MONITOR_X, MONITOR_Y, MONITOR_WIDTH, MONITOR_HEIGHT)

        # Background layer (deep carmine-black + radial vignette)
        self._create_background()

        # Ghost text layer (hex data fog)
        self._create_ghost_text()

        # OpenGL plasma renderer
        self.renderer = PlasmaGLWidget(self)
        self.renderer.setGeometry(0, 0, MONITOR_WIDTH, MONITOR_HEIGHT)

        # Scanline overlay
        self._create_scanlines()

        # Corner markers
        self._create_corner_markers()

        self._create_hud()

        self.telemetry = TelemetryCollector()
        self.telemetry.data_updated.connect(self._on_telemetry)
        self.telemetry.start()

        # CPU timers for atmosphere
        self._breath_phase = 0.0
        self._ram_total = 1  # Will be set from telemetry
        self._ram_used = 0
        self._glitch_active = False
        self._base_loads_x = 0  # Store original position

        # Kollaborations-Layer state
        # HIGH #7: Add lock for thread-safe access to shared state
        self._state_lock = threading.Lock()
        self._mood_target = 0.0      # Target mood (0.0 passive - 1.0 active)
        self._mood_current = 0.0     # Current mood (smoothed)
        self._halo_target = 0.0      # Target halo intensity
        self._halo_current = 0.0     # Current halo (smoothed)
        self._glitch_intensity = 0.0 # Core glitch intensity
        self._cpu_load = 0.0         # Last CPU load
        self._think_target = 0.0     # Target thinking intensity
        self._think_current = 0.0    # Current thinking (smoothed)
        # Event color: each event type sets its own RGB color
        self._event_color_target = (0.3, 0.0, 0.0)   # Default: dim red
        self._event_color_current = [0.3, 0.0, 0.0]   # Mutable for interpolation

        # Error display label (near core)
        self._create_error_display()

        # Breathing pulse timer (0.5 Hz = 2000ms period)
        self.breath_timer = QTimer(self)
        self.breath_timer.timeout.connect(self._update_breathing)
        self.breath_timer.start(100)  # Update every 100ms for smooth breathing

        # Ghost text update timer (every 20s)
        self.ghost_timer = QTimer(self)
        self.ghost_timer.timeout.connect(self._update_ghost_text)
        self.ghost_timer.start(20000)

        # Glitch timer (every 12s)
        self.glitch_timer = QTimer(self)
        self.glitch_timer.timeout.connect(self._trigger_glitch)
        self.glitch_timer.start(12000)

        # Mood/Halo smoothing timer (60fps for smooth transitions)
        self.mood_timer = QTimer(self)
        self.mood_timer.timeout.connect(self._update_mood_smooth)
        self.mood_timer.start(16)  # ~60fps

        # Event listener for aicore events
        self.event_listener = EventListener()
        self.event_listener.event_received.connect(self._on_event)
        self.event_listener.start()

        # Thinking state tracking (protected by _state_lock)
        self._thinking = False
        self._thinking_pulse_count = 0

        # Eye animation state (protected by _state_lock)
        self._eye_blink_current = 0.0     # Current blink amount (0=open, 1=closed)
        self._eye_blink_phase = 'open'    # 'open', 'closing', 'closed', 'opening'
        self._eye_blink_timer = random.uniform(2.0, 5.0)  # Time to next blink
        self._eye_closed_hold = 0.0       # How long to stay closed
        self._eye_double_blink = False    # Trigger second blink after first

        self._eye_look_current = [0.0, 0.0]  # Current gaze position [x, y]
        self._eye_look_target = [0.0, 0.0]   # Target gaze position
        self._eye_look_timer = random.uniform(1.0, 4.0)  # Time to next gaze shift
        self._eye_look_speed = 0.06           # Interpolation speed (higher = faster)

        # Mood expression state (driven by E-PQ personality mood_value)
        self._eye_open_top_target = 1.0   # Target top lid openness
        self._eye_open_top_current = 1.0  # Current (smoothed)
        self._eye_open_bot_target = 1.0   # Target bottom lid openness
        self._eye_open_bot_current = 1.0  # Current (smoothed)
        self._eye_mood_value = 0.0        # Last known mood (-1 to 1)

        # Idle micro-animation state
        self._eye_idle_timer = random.uniform(5.0, 12.0)  # Time to next idle anim
        self._eye_idle_active = None      # Currently playing idle animation
        self._eye_idle_phase = 0.0        # Progress of current idle animation
        self._eye_idle_direction = 1      # Direction for slow_look animation
        self._eye_debug_counter = 0       # Debug log throttle

        self._desktop_configured = False

        # --- Adaptive resolution: track current size and monitor for changes ---
        self._last_w = MONITOR_WIDTH
        self._last_h = MONITOR_HEIGHT
        self._relayout_pending = False

        # Connect QScreen geometry change signals
        app = QApplication.instance()
        if app:
            for screen in app.screens():
                screen.geometryChanged.connect(self._on_screen_changed)
            app.screenAdded.connect(self._on_screen_added)
            app.screenRemoved.connect(lambda: self._on_screen_changed())

        # Fallback: periodic xrandr check every 30s
        self._resolution_check_timer = QTimer(self)
        self._resolution_check_timer.timeout.connect(self._check_resolution_change)
        self._resolution_check_timer.start(30000)

        print(f"[CYBERCORE] GLSL Shader Mode initialized (CPU-enhanced)")
        print(f"[CYBERCORE] SAFETY: Press Alt+1 to exit")

    def _setup_emergency_exit(self):
        QShortcut(QKeySequence("Alt+1"), self).activated.connect(self._emergency_exit)

    def _emergency_exit(self):
        print("[CYBERCORE] EMERGENCY EXIT!")
        _shutdown.set()
        QApplication.quit()

    # --- Adaptive Resolution ---

    def _on_screen_added(self, screen):
        """New screen connected — attach signal and check."""
        screen.geometryChanged.connect(self._on_screen_changed)
        self._on_screen_changed()

    def _on_screen_changed(self):
        """QScreen geometry changed — debounce and relayout."""
        if self._relayout_pending:
            return
        self._relayout_pending = True
        QTimer.singleShot(500, self._deferred_relayout)

    def _check_resolution_change(self):
        """Periodic fallback: re-detect via xrandr and relayout if changed."""
        detect_primary_monitor()
        if MONITOR_WIDTH != self._last_w or MONITOR_HEIGHT != self._last_h:
            print(f"[CYBERCORE] Resolution change detected: {self._last_w}x{self._last_h} → {MONITOR_WIDTH}x{MONITOR_HEIGHT}")
            self._relayout()

    def _deferred_relayout(self):
        """Debounced relayout after screen change signal."""
        self._relayout_pending = False
        detect_primary_monitor()
        if MONITOR_WIDTH != self._last_w or MONITOR_HEIGHT != self._last_h:
            print(f"[CYBERCORE] Screen signal: {self._last_w}x{self._last_h} → {MONITOR_WIDTH}x{MONITOR_HEIGHT}")
            self._relayout()

    def _relayout(self):
        """Reposition and resize all elements to current monitor dimensions."""
        self._last_w = MONITOR_WIDTH
        self._last_h = MONITOR_HEIGHT

        # Window geometry
        self.setGeometry(MONITOR_X, MONITOR_Y, MONITOR_WIDTH, MONITOR_HEIGHT)

        # Background
        self.bg_widget.setGeometry(0, 0, MONITOR_WIDTH, MONITOR_HEIGHT)

        # OpenGL renderer
        self.renderer.setGeometry(0, 0, MONITOR_WIDTH, MONITOR_HEIGHT)

        # Scanlines (recreate baked pixmap)
        self._recreate_scanlines()

        # Corner markers
        self._reposition_corners()

        # HUD boxes
        self._reposition_hud()

        # Ghost text
        self._reposition_ghost_text()

        # Error display
        self.lbl_error.setGeometry(CENTER_X - 150, CENTER_Y + 120, 300, 30)

        # Re-configure as desktop window (xid may change)
        self._desktop_configured = False
        self._configure_as_desktop()

        print(f"[CYBERCORE] Relayout complete: {MONITOR_WIDTH}x{MONITOR_HEIGHT}+{MONITOR_X}+{MONITOR_Y}")

    def _recreate_scanlines(self):
        """Recreate scanline overlay pixmap for current resolution."""
        pattern = QPixmap(1, 4)
        pattern.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pattern)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.fillRect(0, 2, 1, 2, QColor(0, 0, 0, 8))
        painter.end()

        self.scanline_widget.setGeometry(0, 0, MONITOR_WIDTH, MONITOR_HEIGHT)
        scanline_pixmap = QPixmap(MONITOR_WIDTH, MONITOR_HEIGHT)
        scanline_pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(scanline_pixmap)
        for y in range(0, MONITOR_HEIGHT, 4):
            painter.drawPixmap(0, y, MONITOR_WIDTH, 4, pattern.scaled(MONITOR_WIDTH, 4))
        painter.end()
        self.scanline_widget.setPixmap(scanline_pixmap)

    def _reposition_corners(self):
        """Reposition corner markers to current monitor dimensions."""
        marker_len = 40
        marker_thick = 1

        # Top-left (stays at 10,10)
        self.corner_tl_h.setGeometry(10, 10, marker_len, marker_thick)
        self.corner_tl_v.setGeometry(10, 10, marker_thick, marker_len)

        # Top-right
        self.corner_tr_h.setGeometry(MONITOR_WIDTH - 10 - marker_len, 10, marker_len, marker_thick)
        self.corner_tr_v.setGeometry(MONITOR_WIDTH - 10 - marker_thick, 10, marker_thick, marker_len)

        # Bottom-left
        self.corner_bl_h.setGeometry(10, MONITOR_HEIGHT - 10 - marker_thick, marker_len, marker_thick)
        self.corner_bl_v.setGeometry(10, MONITOR_HEIGHT - 10 - marker_len, marker_thick, marker_len)

        # Bottom-right
        self.corner_br_h.setGeometry(MONITOR_WIDTH - 10 - marker_len, MONITOR_HEIGHT - 10 - marker_thick, marker_len, marker_thick)
        self.corner_br_v.setGeometry(MONITOR_WIDTH - 10 - marker_thick, MONITOR_HEIGHT - 10 - marker_len, marker_thick, marker_len)

    def _reposition_hud(self):
        """Reposition HUD and modules boxes to current monitor width."""
        box_width = 420
        box_height = 70
        box_x = MONITOR_WIDTH - 60 - box_width
        box_y = PANEL_OFFSET + 40

        self.hud_box.setGeometry(box_x, box_y, box_width, box_height)

        mod_box_width = 180
        mod_box_height = 130
        self._modules_base_x = MONITOR_WIDTH - mod_box_width - 60
        self._modules_base_y = PANEL_OFFSET + 120
        self.modules_box.setGeometry(self._modules_base_x, self._modules_base_y, mod_box_width, mod_box_height)

    def _reposition_ghost_text(self):
        """Reposition ghost text labels relative to current CENTER_X/CENTER_Y."""
        positions = [
            # Left side
            (CENTER_X - 420, CENTER_Y - 200), (CENTER_X - 380, CENTER_Y - 120),
            (CENTER_X - 450, CENTER_Y - 40), (CENTER_X - 400, CENTER_Y + 60),
            (CENTER_X - 360, CENTER_Y + 140), (CENTER_X - 420, CENTER_Y + 220),
            # Right side
            (CENTER_X + 250, CENTER_Y - 190), (CENTER_X + 300, CENTER_Y - 100),
            (CENTER_X + 280, CENTER_Y - 20), (CENTER_X + 320, CENTER_Y + 80),
            (CENTER_X + 260, CENTER_Y + 160), (CENTER_X + 300, CENTER_Y + 240),
            # Top/Bottom scattered
            (CENTER_X - 180, CENTER_Y - 280), (CENTER_X + 120, CENTER_Y - 260),
            (CENTER_X - 150, CENTER_Y + 280), (CENTER_X + 80, CENTER_Y + 300),
        ]
        for i, lbl in enumerate(self.ghost_labels):
            if i < len(positions):
                lbl.move(positions[i][0], positions[i][1])

    def showEvent(self, event):
        super().showEvent(event)
        if not self._desktop_configured:
            self._configure_as_desktop()
            self._desktop_configured = True

    def _configure_as_desktop(self):
        """Configure window as desktop with proper subprocess handling to avoid zombies."""
        xid = None
        try:
            # CRITICAL #2: Increased timeout and proper error handling
            result = subprocess.run(
                ["xdotool", "search", "--name", "FRANK NEURAL CORE"],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode != 0:
                print(f"[CYBERCORE] xdotool search failed: {result.stderr}")
                return

            xids = result.stdout.strip().split('\n')
            if not xids or not xids[0]:
                print("[CYBERCORE] No window ID found")
                return

            xid = xids[0]

            # Set window type with proper error handling
            xprop_result = subprocess.run([
                "xprop", "-id", xid, "-f", "_NET_WM_WINDOW_TYPE", "32a",
                "-set", "_NET_WM_WINDOW_TYPE", "_NET_WM_WINDOW_TYPE_DESKTOP"
            ], capture_output=True, text=True, timeout=5)

            if xprop_result.returncode != 0:
                print(f"[CYBERCORE] xprop failed: {xprop_result.stderr}")

            # Set window below and sticky with proper error handling
            wmctrl_result = subprocess.run([
                "wmctrl", "-ir", xid, "-b", "add,below,sticky"
            ], capture_output=True, text=True, timeout=5)

            if wmctrl_result.returncode != 0:
                print(f"[CYBERCORE] wmctrl failed: {wmctrl_result.stderr}")
            else:
                print(f"[CYBERCORE] Desktop mode configured (xid: {xid})")

        except subprocess.TimeoutExpired as e:
            print(f"[CYBERCORE] Desktop config timeout: {e.cmd}")
        except FileNotFoundError as e:
            print(f"[CYBERCORE] Required tool not found: {e.filename}")
        except Exception as e:
            print(f"[CYBERCORE] Desktop config failed: {type(e).__name__}: {e}")

    def _create_background(self):
        """Deep carmine-black background with radial vignette."""
        self.bg_widget = QWidget(self)
        self.bg_widget.setGeometry(0, 0, MONITOR_WIDTH, MONITOR_HEIGHT)
        # Radial vignette: dark center (#050000) fading to pure black at edges
        self.bg_widget.setStyleSheet("""
            background: qradialgradient(
                cx: 0.5, cy: 0.5,
                radius: 0.7,
                fx: 0.5, fy: 0.5,
                stop: 0 #050000,
                stop: 0.5 #030000,
                stop: 1 #000000
            );
        """)
        self.bg_widget.lower()  # Send to back

    def _create_ghost_text(self):
        """CPU-generated system data matrix behind the core."""
        self.ghost_labels = []
        self.ghost_opacities = []  # Current opacity for each label
        self.ghost_targets = []    # Target opacity for fading

        font_ghost = QFont("JetBrains Mono", 8)
        if not font_ghost.exactMatch():
            font_ghost = QFont("monospace", 8)

        # System-relevant text fragments (Frank's architecture)
        self.ghost_fragments = [
            # Core Systems
            "E-CPMM v5.1 active", "E-PQ personality engaged", "E-SIR routing...",
            "E-SMC context sync", "GENESIS core online", "TITAN-MEM allocated",
            "ROUTER handshake OK", "VOICE-IO standby", "WORLD-EXP scanning",
            # Audit & Hash
            "Audit Log Hash-Chain... OK", "Integrity: VERIFIED", "Chain Block #4F2A",
            "Hash: 0x7E3B91F2", "Signature: VALID", "Trust Level: LOCAL",
            # Memory & Data
            "MEM:0x00FF:ACTIVE", "CACHE:HIT:94.2%", "VECTOR-DB:INDEXED",
            "EMBEDDING:SYNC", "CONTEXT:LOADED", "PERSONALITY:STABLE",
            # Network & Router
            "ROUTER:INTERNAL", "ENDPOINT:/chat", "LATENCY:<12ms",
            "OLLAMA:CONNECTED", "MODEL:ACTIVE", "STREAM:READY",
            # Technical
            f"PID:{os.getpid()}", "UPTIME:COUNTING", "STATE:NOMINAL",
            "QUANTUM:STABLE", "NEURAL:FIRING", "SYNAPSE:ACTIVE",
        ]

        # Scattered positions around center (avoiding core area)
        positions = [
            # Left side
            (CENTER_X - 420, CENTER_Y - 200), (CENTER_X - 380, CENTER_Y - 120),
            (CENTER_X - 450, CENTER_Y - 40), (CENTER_X - 400, CENTER_Y + 60),
            (CENTER_X - 360, CENTER_Y + 140), (CENTER_X - 420, CENTER_Y + 220),
            # Right side
            (CENTER_X + 250, CENTER_Y - 190), (CENTER_X + 300, CENTER_Y - 100),
            (CENTER_X + 280, CENTER_Y - 20), (CENTER_X + 320, CENTER_Y + 80),
            (CENTER_X + 260, CENTER_Y + 160), (CENTER_X + 300, CENTER_Y + 240),
            # Top/Bottom scattered
            (CENTER_X - 180, CENTER_Y - 280), (CENTER_X + 120, CENTER_Y - 260),
            (CENTER_X - 150, CENTER_Y + 280), (CENTER_X + 80, CENTER_Y + 300),
        ]

        for i, (x, y) in enumerate(positions):
            text = random.choice(self.ghost_fragments)
            lbl = QLabel(text, self)
            lbl.setFont(font_ghost)
            # Start with random opacity 5-12% (13-31 out of 255)
            opacity = random.randint(13, 31)
            self.ghost_opacities.append(opacity)
            self.ghost_targets.append(random.randint(13, 31))
            lbl.setStyleSheet(f"color: rgba(100, 0, 0, {opacity}); background: transparent;")
            lbl.adjustSize()
            lbl.move(x, y)
            lbl.lower()
            self.ghost_labels.append(lbl)

    def _update_ghost_text(self):
        """Rotate ghost texts every 20s with fade effect."""
        if self.ghost_labels:
            # Pick 2-3 random labels to update
            for _ in range(random.randint(2, 3)):
                idx = random.randint(0, len(self.ghost_labels) - 1)
                lbl = self.ghost_labels[idx]
                lbl.setText(random.choice(self.ghost_fragments))
                lbl.adjustSize()
                # Set new target opacity for fade
                self.ghost_targets[idx] = random.randint(13, 31)

    def _update_ghost_fade(self):
        """Smooth fade animation for ghost texts (called from breathing timer)."""
        for i, lbl in enumerate(self.ghost_labels):
            current = self.ghost_opacities[i]
            target = self.ghost_targets[i]
            # Slow fade towards target
            if current < target:
                current = min(current + 1, target)
            elif current > target:
                current = max(current - 1, target)

            if current != self.ghost_opacities[i]:
                self.ghost_opacities[i] = current
                lbl.setStyleSheet(f"color: rgba(100, 0, 0, {current}); background: transparent;")

    def _update_breathing(self):
        """0.5Hz breathing pulse for background + ghost fade + module float."""
        self._breath_phase += 0.05  # 100ms * 0.05 = 2s period = 0.5Hz

        # Background pulse
        brightness = 0.05 + 0.02 * math.sin(self._breath_phase * math.pi)
        r = int(brightness * 255)
        self.bg_widget.setStyleSheet(f"""
            background: qradialgradient(
                cx: 0.5, cy: 0.5,
                radius: 0.7,
                fx: 0.5, fy: 0.5,
                stop: 0 rgb({r}, 0, 0),
                stop: 0.5 rgb({r // 2}, 0, 0),
                stop: 1 #000000
            );
        """)

        # Ghost text fade animation
        self._update_ghost_fade()

        # Module box float animation
        self._update_module_float()

    def _update_module_float(self):
        """Subtle floating animation for modules box."""
        if hasattr(self, 'modules_box'):
            # Irregular float using multiple sine waves
            float_x = math.sin(self._breath_phase * 0.7) * 1.5 + math.sin(self._breath_phase * 1.3) * 0.5
            float_y = math.cos(self._breath_phase * 0.5) * 1.0 + math.cos(self._breath_phase * 1.1) * 0.5
            new_x = self._modules_base_x + int(float_x)
            new_y = self._modules_base_y + int(float_y)
            self.modules_box.move(new_x, new_y)

    def set_module_status(self, module_name: str, active: bool):
        """Update a module's status (green if active, red if inactive)."""
        if not hasattr(self, 'module_labels'):
            return
        for lbl, name in self.module_labels:
            if name == module_name:
                prefix = ">" if active else "×"
                color = "#00CC88" if active else "#CC0000"
                lbl.setText(f"{prefix} {name}")
                lbl.setStyleSheet(f"color: {color}; background: transparent; border: none;")
                # Trigger error if module goes inactive
                if not active:
                    self.trigger_error(f"MODULE_{name}_OFFLINE")
                break

    def _create_error_display(self):
        """Create error code display near core."""
        font_error = QFont("JetBrains Mono", 12)
        if not font_error.exactMatch():
            font_error = QFont("monospace", 12)
        font_error.setBold(True)

        self.lbl_error = QLabel("", self)
        self.lbl_error.setFont(font_error)
        self.lbl_error.setStyleSheet("color: #FF0000; background: transparent;")
        self.lbl_error.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_error.setGeometry(CENTER_X - 150, CENTER_Y + 120, 300, 30)
        self.lbl_error.hide()

    def _update_mood_smooth(self):
        """Smooth mood/halo/glitch/think/color transitions (60fps)."""
        with self._state_lock:
            # Smooth mood transition (very gradual for organic feel)
            diff = self._mood_target - self._mood_current
            self._mood_current += diff * 0.018

            # Smooth halo transition (gentle glow breathing)
            diff_halo = self._halo_target - self._halo_current
            self._halo_current += diff_halo * 0.022

            # Smooth glitch decay (lingers longer)
            self._glitch_intensity *= 0.98

            # Smooth thinking transition (slow ramp-up, gradual fade)
            diff_think = self._think_target - self._think_current
            self._think_current += diff_think * 0.02

            # Smooth event color transition (RGB interpolation - slow blend)
            for i in range(3):
                diff_c = self._event_color_target[i] - self._event_color_current[i]
                self._event_color_current[i] += diff_c * 0.025

            # Cache values for renderer update
            mood = self._mood_current
            halo = self._halo_current
            glitch = self._glitch_intensity
            think = self._think_current
            event_color = tuple(self._event_color_current)

        # Update renderer outside lock
        if hasattr(self, 'renderer'):
            self.renderer.mood = mood
            self.renderer.halo = halo
            self.renderer.glitch = glitch
            self.renderer.think = think
            self.renderer.event_color = event_color

        # Eye animation update (also at 60fps)
        self._update_eye_animation()

    # =============================================
    # EYE ANIMATION ENGINE (EMO-inspired, mood-driven)
    # =============================================

    def _update_eye_animation(self):
        """Full eye animation: blink, gaze, mood expression, idle micro-anims."""
        dt = 0.016  # ~60fps (16ms per frame)

        try:
            with self._state_lock:
                # === BLINK STATE MACHINE ===
                if self._eye_blink_phase == 'open':
                    self._eye_blink_timer -= dt
                    if self._eye_blink_timer <= 0:
                        self._eye_blink_phase = 'closing'
                        self._eye_double_blink = random.random() < 0.2

                elif self._eye_blink_phase == 'closing':
                    self._eye_blink_current += dt * 8.0  # Close in ~125ms
                    if self._eye_blink_current >= 1.0:
                        self._eye_blink_current = 1.0
                        self._eye_blink_phase = 'closed'
                        self._eye_closed_hold = random.uniform(0.04, 0.10)

                elif self._eye_blink_phase == 'closed':
                    self._eye_closed_hold -= dt
                    if self._eye_closed_hold <= 0:
                        self._eye_blink_phase = 'opening'

                elif self._eye_blink_phase == 'opening':
                    self._eye_blink_current -= dt * 6.0  # Open in ~167ms
                    if self._eye_blink_current <= 0.0:
                        self._eye_blink_current = 0.0
                        if self._eye_double_blink:
                            self._eye_double_blink = False
                            self._eye_blink_phase = 'closing'
                        else:
                            self._eye_blink_phase = 'open'
                            base_interval = 4.0
                            if self._eye_mood_value < -0.3:
                                base_interval = 2.5
                            elif self._eye_mood_value > 0.3:
                                base_interval = 4.5
                            self._eye_blink_timer = random.uniform(
                                base_interval * 0.6, base_interval * 1.5
                            )

                # === GAZE SYSTEM (smooth random look-around) ===
                self._eye_look_timer -= dt
                if self._eye_look_timer <= 0:
                    h_range = 0.7
                    v_range = 0.35
                    roll = random.random()
                    if roll < 0.25:
                        # Focused glance in one direction
                        self._eye_look_target = [
                            random.choice([-1, 1]) * random.uniform(0.4, h_range),
                            random.uniform(-v_range * 0.5, v_range * 0.5)
                        ]
                        self._eye_look_speed = 0.10
                        self._eye_look_timer = random.uniform(0.8, 2.0)
                    elif roll < 0.50:
                        # Return to center
                        self._eye_look_target = [
                            random.uniform(-0.1, 0.1),
                            random.uniform(-0.05, 0.05)
                        ]
                        self._eye_look_speed = 0.04
                        self._eye_look_timer = random.uniform(3.0, 6.0)
                    else:
                        # Random gentle gaze shift
                        self._eye_look_target = [
                            random.uniform(-h_range * 0.6, h_range * 0.6),
                            random.uniform(-v_range * 0.6, v_range * 0.6)
                        ]
                        self._eye_look_speed = 0.06
                        self._eye_look_timer = random.uniform(2.0, 5.0)

                # Smooth interpolation to gaze target
                for i in range(2):
                    diff = self._eye_look_target[i] - self._eye_look_current[i]
                    self._eye_look_current[i] += diff * self._eye_look_speed

                # Micro-saccade: tiny random jitter
                if random.random() < 0.08:
                    self._eye_look_current[0] += random.uniform(-0.015, 0.015)
                    self._eye_look_current[1] += random.uniform(-0.008, 0.008)

                # === MOOD EXPRESSION (lid shape from E-PQ mood_value) ===
                mv = self._eye_mood_value
                if mv > 0.4:
                    self._eye_open_top_target = 1.0
                    self._eye_open_bot_target = 0.78
                elif mv > 0.15:
                    self._eye_open_top_target = 1.0
                    self._eye_open_bot_target = 0.88
                elif mv > -0.15:
                    self._eye_open_top_target = 1.0
                    self._eye_open_bot_target = 1.0
                elif mv > -0.35:
                    self._eye_open_top_target = 0.85
                    self._eye_open_bot_target = 1.0
                else:
                    self._eye_open_top_target = 0.72
                    self._eye_open_bot_target = 0.95

                if self._thinking:
                    self._eye_open_top_target = min(self._eye_open_top_target, 0.88)
                    self._eye_open_bot_target = min(self._eye_open_bot_target, 0.92)

                # Smooth lid transitions
                self._eye_open_top_current += (self._eye_open_top_target - self._eye_open_top_current) * 0.03
                self._eye_open_bot_current += (self._eye_open_bot_target - self._eye_open_bot_current) * 0.03

                # === IDLE MICRO-ANIMATIONS ===
                self._eye_idle_timer -= dt
                if self._eye_idle_timer <= 0 and self._eye_idle_active is None:
                    anims = ['squint', 'widen', 'slow_look', 'drift_up']
                    weights = [0.3, 0.2, 0.35, 0.15]
                    self._eye_idle_active = random.choices(anims, weights=weights, k=1)[0]
                    self._eye_idle_phase = 0.0
                    # Pre-set direction for slow_look
                    if self._eye_idle_active == 'slow_look':
                        self._eye_idle_direction = random.choice([-1, 1])

                if self._eye_idle_active:
                    self._eye_idle_phase += dt
                    anim = self._eye_idle_active

                    if anim == 'squint':
                        if self._eye_idle_phase < 0.15:
                            t = self._eye_idle_phase / 0.15
                            self._eye_open_top_current -= 0.12 * t
                            self._eye_open_bot_current -= 0.08 * t
                        elif self._eye_idle_phase < 0.45:
                            self._eye_open_top_current -= 0.12
                            self._eye_open_bot_current -= 0.08
                        elif self._eye_idle_phase >= 0.6:
                            self._eye_idle_active = None
                            self._eye_idle_timer = random.uniform(8.0, 18.0)

                    elif anim == 'widen':
                        if self._eye_idle_phase < 0.1:
                            t = self._eye_idle_phase / 0.1
                            self._eye_open_top_current = min(1.0, self._eye_open_top_current + 0.05 * t)
                        elif self._eye_idle_phase < 0.5:
                            self._eye_open_top_current = min(1.0, self._eye_open_top_target + 0.05)
                        elif self._eye_idle_phase >= 0.5:
                            self._eye_idle_active = None
                            self._eye_idle_timer = random.uniform(12.0, 25.0)

                    elif anim == 'slow_look':
                        if self._eye_idle_phase < 1.0:
                            t = self._eye_idle_phase
                            self._eye_look_target[0] = self._eye_idle_direction * 0.55 * min(t * 2, 1.0)
                        elif self._eye_idle_phase < 2.0:
                            pass
                        elif self._eye_idle_phase < 3.0:
                            t = (self._eye_idle_phase - 2.0)
                            self._eye_look_target[0] *= (1.0 - t)
                        else:
                            self._eye_idle_active = None
                            self._eye_idle_timer = random.uniform(6.0, 15.0)

                    elif anim == 'drift_up':
                        if self._eye_idle_phase < 0.8:
                            t = self._eye_idle_phase / 0.8
                            self._eye_look_target[1] = 0.25 * t
                        elif self._eye_idle_phase < 1.5:
                            pass
                        elif self._eye_idle_phase < 2.3:
                            t = (self._eye_idle_phase - 1.5) / 0.8
                            self._eye_look_target[1] = 0.25 * (1.0 - t)
                        else:
                            self._eye_idle_active = None
                            self._eye_idle_timer = random.uniform(10.0, 20.0)

                # Clamp all values
                self._eye_blink_current = max(0.0, min(1.0, self._eye_blink_current))
                self._eye_look_current[0] = max(-1.0, min(1.0, self._eye_look_current[0]))
                self._eye_look_current[1] = max(-1.0, min(1.0, self._eye_look_current[1]))
                self._eye_open_top_current = max(0.0, min(1.0, self._eye_open_top_current))
                self._eye_open_bot_current = max(0.0, min(1.0, self._eye_open_bot_current))

                # Cache values
                blink = self._eye_blink_current
                look_x = self._eye_look_current[0]
                look_y = self._eye_look_current[1]
                open_top = self._eye_open_top_current
                open_bot = self._eye_open_bot_current

            # Push to renderer (outside lock)
            if hasattr(self, 'renderer'):
                self.renderer.eye_blink = blink
                self.renderer.eye_look_x = look_x
                self.renderer.eye_look_y = look_y
                self.renderer.eye_open_top = open_top
                self.renderer.eye_open_bot = open_bot

            # Debug log every 5 seconds
            self._eye_debug_counter += 1
            if self._eye_debug_counter % 300 == 0:  # Every ~5s at 60fps
                print(f"[CYBERCORE] Eye: blink={blink:.2f} look=({look_x:.2f},{look_y:.2f}) "
                      f"lids=({open_top:.2f},{open_bot:.2f}) phase={self._eye_blink_phase} "
                      f"idle={self._eye_idle_active}")

        except Exception as e:
            print(f"[CYBERCORE] Eye animation error: {type(e).__name__}: {e}")

    def set_mood_value(self, mood_value: float):
        """Set Frank's mood for eye expressions. Called from mood events.
        mood_value: -1.0 (stressed/angry) to +1.0 (happy/content)
        """
        with self._state_lock:
            self._eye_mood_value = max(-1.0, min(1.0, mood_value))

    def trigger_error(self, error_code: str = None):
        """Trigger error effect with glitch and error code display."""
        # Generate random error code if not provided
        if error_code is None:
            error_code = f"ERR_{random.randint(100, 999)}"

        # Randomize position near core
        offset_x = random.randint(-100, 100)
        offset_y = random.randint(80, 150)
        self.lbl_error.move(CENTER_X - 75 + offset_x, CENTER_Y + offset_y)
        self.lbl_error.setText(f"[ {error_code} ]")
        self.lbl_error.adjustSize()
        self.lbl_error.show()
        self.lbl_error.raise_()

        # Trigger strong glitch
        self._glitch_intensity = 1.0

        # Trigger halo pulse
        self._halo_target = 0.8

        # Hide error after 1.5s
        QTimer.singleShot(1500, self._hide_error)

        # Reset halo after 2s
        QTimer.singleShot(2000, lambda: setattr(self, '_halo_target', 0.0))

    def _hide_error(self):
        """Hide error display with fade."""
        if hasattr(self, 'lbl_error'):
            self.lbl_error.hide()

    def _set_mood_target(self, value: float):
        """Thread-safe setter for mood target."""
        with self._state_lock:
            self._mood_target = value

    def _set_halo_target(self, value: float):
        """Thread-safe setter for halo target."""
        with self._state_lock:
            self._halo_target = value

    def _set_think_target(self, value: float):
        """Thread-safe setter for think target."""
        with self._state_lock:
            self._think_target = value

    def _set_event_color(self, r: float, g: float, b: float):
        """Thread-safe setter for event color."""
        with self._state_lock:
            self._event_color_target = (r, g, b)

    def pulse_halo(self, intensity: float = 0.5):
        """Trigger a halo pulse (for events)."""
        with self._state_lock:
            self._halo_target = min(intensity, 1.0)
        QTimer.singleShot(5000, lambda: self._set_halo_target(0.0))

    def _trigger_glitch(self):
        """Trigger RAM text glitch for 100ms."""
        if hasattr(self, 'lbl_loads') and not self._glitch_active:
            self._glitch_active = True
            # Store original position
            if self._base_loads_x == 0:
                self._base_loads_x = self.lbl_loads.x()
            # Offset by 1-2px
            offset = random.choice([-2, -1, 1, 2])
            self.lbl_loads.move(self._base_loads_x + offset, self.lbl_loads.y())
            # Reset after 100ms
            QTimer.singleShot(100, self._reset_glitch)

    def _reset_glitch(self):
        """Reset glitch position."""
        if hasattr(self, 'lbl_loads'):
            self.lbl_loads.move(self._base_loads_x, self.lbl_loads.y())
        self._glitch_active = False

    def _create_scanlines(self):
        """Subtle scanline overlay for CRT atmosphere using tiled pattern."""
        # Create a 1x4 pixel pattern (2px transparent, 2px dark)
        pattern = QPixmap(1, 4)
        pattern.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pattern)
        painter.setPen(Qt.PenStyle.NoPen)
        # Draw dark line at rows 2-3 (very subtle)
        painter.fillRect(0, 2, 1, 2, QColor(0, 0, 0, 8))  # ~3% opacity
        painter.end()

        self.scanline_widget = QLabel(self)
        self.scanline_widget.setGeometry(0, 0, MONITOR_WIDTH, MONITOR_HEIGHT)
        self.scanline_widget.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        # Create full-size tiled pattern
        scanline_pixmap = QPixmap(MONITOR_WIDTH, MONITOR_HEIGHT)
        scanline_pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(scanline_pixmap)
        for y in range(0, MONITOR_HEIGHT, 4):
            painter.drawPixmap(0, y, MONITOR_WIDTH, 4, pattern.scaled(MONITOR_WIDTH, 4))
        painter.end()

        self.scanline_widget.setPixmap(scanline_pixmap)

    def _create_corner_markers(self):
        """L-shaped corner markers in dim red."""
        marker_color = "#440000"
        marker_len = 40  # Length of each L arm
        marker_thick = 1  # Thickness

        # Top-left
        self.corner_tl_h = QWidget(self)
        self.corner_tl_h.setGeometry(10, 10, marker_len, marker_thick)
        self.corner_tl_h.setStyleSheet(f"background: {marker_color};")

        self.corner_tl_v = QWidget(self)
        self.corner_tl_v.setGeometry(10, 10, marker_thick, marker_len)
        self.corner_tl_v.setStyleSheet(f"background: {marker_color};")

        # Top-right
        self.corner_tr_h = QWidget(self)
        self.corner_tr_h.setGeometry(MONITOR_WIDTH - 10 - marker_len, 10, marker_len, marker_thick)
        self.corner_tr_h.setStyleSheet(f"background: {marker_color};")

        self.corner_tr_v = QWidget(self)
        self.corner_tr_v.setGeometry(MONITOR_WIDTH - 10 - marker_thick, 10, marker_thick, marker_len)
        self.corner_tr_v.setStyleSheet(f"background: {marker_color};")

        # Bottom-left
        self.corner_bl_h = QWidget(self)
        self.corner_bl_h.setGeometry(10, MONITOR_HEIGHT - 10 - marker_thick, marker_len, marker_thick)
        self.corner_bl_h.setStyleSheet(f"background: {marker_color};")

        self.corner_bl_v = QWidget(self)
        self.corner_bl_v.setGeometry(10, MONITOR_HEIGHT - 10 - marker_len, marker_thick, marker_len)
        self.corner_bl_v.setStyleSheet(f"background: {marker_color};")

        # Bottom-right
        self.corner_br_h = QWidget(self)
        self.corner_br_h.setGeometry(MONITOR_WIDTH - 10 - marker_len, MONITOR_HEIGHT - 10 - marker_thick, marker_len, marker_thick)
        self.corner_br_h.setStyleSheet(f"background: {marker_color};")

        self.corner_br_v = QWidget(self)
        self.corner_br_v.setGeometry(MONITOR_WIDTH - 10 - marker_thick, MONITOR_HEIGHT - 10 - marker_len, marker_thick, marker_len)
        self.corner_br_v.setStyleSheet(f"background: {marker_color};")

        # Raise all corner markers above scanlines
        for widget in [self.corner_tl_h, self.corner_tl_v,
                       self.corner_tr_h, self.corner_tr_v,
                       self.corner_bl_h, self.corner_bl_v,
                       self.corner_br_h, self.corner_br_v]:
            widget.raise_()

    def _create_hud(self):
        # Fonts - prefer JetBrains Mono for cyberpunk look
        font_title = QFont("JetBrains Mono", 11)
        if not font_title.exactMatch():
            font_title = QFont("monospace", 11)
        font_title.setBold(True)

        font_data = QFont("JetBrains Mono", 10)
        if not font_data.exactMatch():
            font_data = QFont("monospace", 10)

        font_small = QFont("JetBrains Mono", 9)
        if not font_small.exactMatch():
            font_small = QFont("monospace", 9)

        # Cyberpunk HUD box container (rechtsbündig mit Modul-Box)
        box_width = 420
        box_height = 70
        box_x = MONITOR_WIDTH - 60 - box_width
        box_y = PANEL_OFFSET + 40  # 40px lower

        self.hud_box = QWidget(self)
        self.hud_box.setGeometry(box_x, box_y, box_width, box_height)
        # Cyberpunk styling: dark semi-transparent bg, thin red border
        # Using border-image trick for asymmetric corners effect
        self.hud_box.setStyleSheet("""
            background: rgba(10, 0, 0, 180);
            border: 1px solid #660000;
            border-top-left-radius: 0px;
            border-top-right-radius: 12px;
            border-bottom-left-radius: 12px;
            border-bottom-right-radius: 0px;
        """)

        # Title inside box
        self.lbl_title = QLabel("F.R.A.N.K.", self.hud_box)
        self.lbl_title.setFont(font_title)
        self.lbl_title.setStyleSheet("color: #00FFFF; background: transparent; border: none;")
        self.lbl_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_title.setGeometry(0, 8, box_width, 18)

        # Temps inside box
        self.lbl_temps = QLabel("CPU: --°C | GPU: --°C", self.hud_box)
        self.lbl_temps.setFont(font_data)
        self.lbl_temps.setStyleSheet("color: #E0E0E0; background: transparent; border: none;")
        self.lbl_temps.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_temps.setGeometry(0, 28, box_width, 16)

        # Loads inside box (RAM as percentage)
        self.lbl_loads = QLabel("CPU: --% | GPU: --% | RAM: --%", self.hud_box)
        self.lbl_loads.setFont(font_data)
        self.lbl_loads.setStyleSheet("color: #E0E0E0; background: transparent; border: none;")
        self.lbl_loads.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_loads.setGeometry(0, 46, box_width, 16)

        # Core Modules Box (right side, below main HUD)
        font_module = QFont("JetBrains Mono", 8)
        if not font_module.exactMatch():
            font_module = QFont("monospace", 8)

        mod_box_width = 180
        mod_box_height = 130
        self._modules_base_x = MONITOR_WIDTH - mod_box_width - 60
        self._modules_base_y = PANEL_OFFSET + 120

        self.modules_box = QWidget(self)
        self.modules_box.setGeometry(self._modules_base_x, self._modules_base_y, mod_box_width, mod_box_height)
        # Cyberpunk styling: smaller, filigraner
        self.modules_box.setStyleSheet("""
            background: rgba(8, 0, 0, 160);
            border: 1px solid #880000;
            border-top-left-radius: 8px;
            border-top-right-radius: 0px;
            border-bottom-left-radius: 0px;
            border-bottom-right-radius: 8px;
        """)

        # Module header
        self.lbl_mod_header = QLabel("[ CORE MODULES ]", self.modules_box)
        self.lbl_mod_header.setFont(font_module)
        self.lbl_mod_header.setStyleSheet("color: #00AAAA; background: transparent; border: none;")
        self.lbl_mod_header.setGeometry(8, 6, mod_box_width - 16, 14)

        # Module list with ">" prefix for active, color based on status
        # (name, active) - inactive modules show in red
        self.module_states = [
            ("GENESIS", True),
            ("TITAN", True),
            ("ROUTER", True),
            ("MEMORY", True),
            ("PERS-ENGINE", True),
        ]

        y_offset = 24
        self.module_labels = []
        for mod_name, active in self.module_states:
            prefix = ">" if active else "×"
            lbl = QLabel(f"{prefix} {mod_name}", self.modules_box)
            lbl.setFont(font_module)
            # Active: green, Inactive: red
            color = "#00CC88" if active else "#CC0000"
            lbl.setStyleSheet(f"color: {color}; background: transparent; border: none;")
            lbl.setGeometry(12, y_offset, mod_box_width - 24, 14)
            self.module_labels.append((lbl, mod_name))
            y_offset += 18

        # Status line at bottom
        self.lbl_mod_status = QLabel("STATUS: ACTIVE", self.modules_box)
        self.lbl_mod_status.setFont(font_module)
        self.lbl_mod_status.setStyleSheet("color: #00FF00; background: transparent; border: none;")
        self.lbl_mod_status.setGeometry(8, mod_box_height - 18, mod_box_width - 16, 14)

        # Raise all HUD elements to top
        self.hud_box.raise_()
        self.modules_box.raise_()

    def _on_telemetry(self, data: dict):
        self.lbl_temps.setText(
            f"CPU: {int(data.get('cpu_temp', 0))}°C | GPU: {int(data.get('gpu_temp', 0))}°C"
        )
        # Calculate RAM percentage
        ram_used_gb = data.get('ram_used', 0)
        ram_total_gb = data.get('ram_total', 32)  # Default 32GB if not available
        ram_percent = int((ram_used_gb / ram_total_gb) * 100) if ram_total_gb > 0 else 0

        self.lbl_loads.setText(
            f"CPU: {int(data.get('cpu_load', 0))}% | GPU: {int(data.get('gpu_load', 0))}% | RAM: {ram_percent}%"
        )

        # Kollaborations-Layer: Mood from CPU load
        # CPU > 50% = "thinking" mode (active), < 20% = passive
        cpu_load = data.get('cpu_load', 0)
        cpu_temp = data.get('cpu_temp', 0)

        # HIGH #7: Use lock for thread-safe state updates
        with self._state_lock:
            self._cpu_load = cpu_load

            # Calculate mood: 0-20% CPU = 0.0 mood, 50-100% CPU = 0.5-1.0 mood
            if cpu_load < 20:
                self._mood_target = 0.0
            elif cpu_load < 50:
                self._mood_target = (cpu_load - 20) / 60  # 0.0 to 0.5
            else:
                self._mood_target = 0.5 + (cpu_load - 50) / 100  # 0.5 to 1.0

            # Small halo pulse on high CPU
            if cpu_load > 70 and self._halo_current < 0.2:
                self._halo_target = 0.3

            # Warning: High temp triggers subtle glitch
            if cpu_temp > 85:
                self._glitch_intensity = max(self._glitch_intensity, 0.3)

    def closeEvent(self, event):
        # Stop all timers and listeners
        self.breath_timer.stop()
        self.ghost_timer.stop()
        self.glitch_timer.stop()
        self.mood_timer.stop()
        self.event_listener.stop()
        self.telemetry.stop()

        # HIGH #4: Clean up OpenGL resources to prevent leaks
        if hasattr(self, 'renderer') and self.renderer:
            self.renderer.timer.stop()
            # Must make context current before deleting OpenGL resources
            if hasattr(self.renderer, 'shader_program') and self.renderer.shader_program:
                try:
                    self.renderer.makeCurrent()
                    from OpenGL.GL import glDeleteProgram
                    glDeleteProgram(self.renderer.shader_program)
                    self.renderer.shader_program = None
                    if self.renderer.frank_tex_id:
                        glDeleteTextures([self.renderer.frank_tex_id])
                        self.renderer.frank_tex_id = 0
                    self.renderer.doneCurrent()
                except Exception as e:
                    print(f"[CYBERCORE] OpenGL cleanup warning: {e}")

        _shutdown.set()
        event.accept()

    # =============================================
    # EVENT COLOR MAP - Jedes Event hat eigene Farbe
    # =============================================
    EVENT_COLORS = {
        # Thinking/Inference: Electric Blue
        "thinking":    (0.1, 0.4, 1.0),
        # Chat: Cyan/Teal
        "chat.request":  (0.0, 1.0, 0.9),
        "chat.response": (0.0, 0.8, 0.4),
        # Desktop/System: Amber/Gold
        "screenshot":    (1.0, 0.8, 0.0),
        # Files: Purple/Violet
        "file.read":     (0.5, 0.2, 0.9),
        # Web: Magenta/Pink
        "web.search":    (1.0, 0.0, 0.8),
        # Tools: Orange
        "tool":          (1.0, 0.5, 0.0),
        # Gaming: Bright Green
        "game.launch":   (0.0, 1.0, 0.3),
        "game.exit":     (0.5, 0.3, 0.0),
        # Error: Pure Red
        "error":         (1.0, 0.0, 0.0),
        # Warning: Yellow-Orange
        "warning":       (1.0, 0.6, 0.0),
        # Voice: Soft Cyan
        "voice":         (0.3, 0.8, 1.0),
        # Memory: Deep Purple
        "memory":        (0.6, 0.0, 1.0),
        # Default idle: Dim Red
        "idle":          (0.3, 0.0, 0.0),
    }

    def _on_event(self, event: dict):
        """Handle incoming events from aicore components."""
        event_type = event.get("type", "")
        level = event.get("level", "info")
        source = event.get("source", "")

        # =============================================
        # THINKING EVENTS (Chat/Inference) — DRAMATIC
        # =============================================
        if event_type == "thinking.start" or event_type == "inference.start":
            with self._state_lock:
                self._thinking = True
                self._thinking_pulse_count = 0
                self._mood_target = 0.75
                self._halo_target = 0.65
                self._think_target = 0.8
                self._event_color_target = self.EVENT_COLORS["thinking"]
            self.pulse_halo(0.65)

        elif event_type == "thinking.pulse":
            with self._state_lock:
                if self._thinking:
                    self._thinking_pulse_count += 1
                    self._halo_target = 0.45 + (self._thinking_pulse_count % 3) * 0.08
                    self._mood_target = min(0.8, 0.55 + self._thinking_pulse_count * 0.02)

        elif event_type == "thinking.end" or event_type == "inference.end":
            with self._state_lock:
                self._thinking = False
                self._mood_target = 0.25
                self._halo_target = 0.2
                self._think_target = 0.0
            QTimer.singleShot(8000, lambda: self._set_halo_target(0.0))
            QTimer.singleShot(12000, lambda: self._set_mood_target(0.0))
            QTimer.singleShot(12000, lambda: self._set_event_color(*self.EVENT_COLORS["idle"]))

        # =============================================
        # CHAT EVENTS — Cyan/Teal + Green
        # =============================================
        elif event_type == "chat.request":
            self.pulse_halo(0.5)
            with self._state_lock:
                self._mood_target = 0.55
                self._event_color_target = self.EVENT_COLORS["chat.request"]

        elif event_type == "chat.response":
            self.pulse_halo(0.35)
            with self._state_lock:
                self._mood_target = 0.25
                self._event_color_target = self.EVENT_COLORS["chat.response"]

        # =============================================
        # SCREENSHOT / FILE / WEB — each with own color
        # =============================================
        elif event_type == "screenshot":
            self.pulse_halo(0.55)
            with self._state_lock:
                self._mood_target = 0.6
                self._event_color_target = self.EVENT_COLORS["screenshot"]

        elif event_type == "file.read":
            self.pulse_halo(0.35)
            with self._state_lock:
                self._mood_target = 0.25
                self._event_color_target = self.EVENT_COLORS["file.read"]

        elif event_type == "web.search":
            self.pulse_halo(0.5)
            with self._state_lock:
                self._mood_target = 0.5
                self._event_color_target = self.EVENT_COLORS["web.search"]

        # =============================================
        # TOOL EVENTS — Orange
        # =============================================
        elif event_type.startswith("tool."):
            self.pulse_halo(0.4)
            with self._state_lock:
                self._mood_target = 0.3
                self._event_color_target = self.EVENT_COLORS["tool"]

        # =============================================
        # VOICE EVENTS — Soft Cyan
        # =============================================
        elif event_type.startswith("voice."):
            self.pulse_halo(0.35)
            with self._state_lock:
                self._mood_target = 0.3
                self._event_color_target = self.EVENT_COLORS["voice"]

        # =============================================
        # MEMORY EVENTS — Deep Purple
        # =============================================
        elif event_type.startswith("memory."):
            self.pulse_halo(0.35)
            with self._state_lock:
                self._mood_target = 0.3
                self._event_color_target = self.EVENT_COLORS["memory"]

        # =============================================
        # GAME EVENTS — Green / Amber
        # =============================================
        elif event_type == "game.launch":
            with self._state_lock:
                self._mood_target = 0.8
                self._event_color_target = self.EVENT_COLORS["game.launch"]
            self.pulse_halo(0.7)

        elif event_type == "game.exit":
            with self._state_lock:
                self._mood_target = 0.15
                self._event_color_target = self.EVENT_COLORS["game.exit"]
            self.pulse_halo(0.3)

        # =============================================
        # ERROR / WARNING EVENTS — Red / Yellow-Orange
        # =============================================
        elif level == "error":
            error_code = event.get("data", {}).get("code", f"ERR_{random.randint(100,999)}")
            with self._state_lock:
                self._event_color_target = self.EVENT_COLORS["error"]
            self.trigger_error(error_code)

        elif level == "warning":
            self._glitch_intensity = max(self._glitch_intensity, 0.5)
            with self._state_lock:
                self._event_color_target = self.EVENT_COLORS["warning"]
            self.pulse_halo(0.6)

        # =============================================
        # MOOD EVENTS — Drive eye expressions from E-PQ
        # =============================================
        if event_type == "mood.update":
            mood_val = event.get("data", {}).get("mood", 0.0)
            self.set_mood_value(mood_val)

        # Eye reactions to events (EMO-style reactive behavior)
        if level == "error":
            # Quick blink on errors
            with self._state_lock:
                if self._eye_blink_phase == 'open':
                    self._eye_blink_phase = 'closing'
        elif event_type in ("thinking.start", "inference.start"):
            # Center gaze when thinking, slow down gaze shifts
            with self._state_lock:
                self._eye_look_target = [0.0, 0.08]  # Slight upward (thinking)
                self._eye_look_timer = 3.0  # Hold longer
        elif event_type == "chat.request":
            # Look slightly toward user (center-right)
            with self._state_lock:
                self._eye_look_target = [0.15, 0.0]
                self._eye_look_speed = 0.08


# =============================================================================
# MAIN
# =============================================================================
def main():
    # CRITICAL #1: Check DISPLAY before starting Qt
    if not os.environ.get('DISPLAY'):
        print("[CYBERCORE] CRITICAL: No DISPLAY environment variable - cannot start wallpaper")
        sys.exit(1)

    # Also check XAUTHORITY if needed
    xauth = os.environ.get('XAUTHORITY')
    if not xauth and not os.path.exists(os.path.expanduser('~/.Xauthority')):
        print("[CYBERCORE] WARNING: No XAUTHORITY set and ~/.Xauthority not found")

    detect_primary_monitor()

    # MUST be called before QApplication
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    def shutdown_handler(signum, frame):
        _shutdown.set()
        QApplication.quit()

    signal.signal(signal.SIGINT, shutdown_handler)
    signal.signal(signal.SIGTERM, shutdown_handler)

    crash_count = 0
    last_crash = 0

    while not _shutdown.is_set():
        try:
            print(f"[CYBERCORE] Starting v5.2 GLSL Shader (attempt {crash_count})...")

            app = QApplication.instance() or QApplication(sys.argv)
            window = NeuralCybercoreWindow()
            window.show()
            app.exec()

            if _shutdown.is_set():
                break

        except Exception as e:
            import traceback
            print(f"[CYBERCORE] Crash: {e}")
            traceback.print_exc()

            now = time.time()
            if now - last_crash > 60:
                crash_count = 0
            crash_count += 1
            last_crash = now

            delay = min(2 ** crash_count, 30)
            print(f"[CYBERCORE] Recovery in {delay}s...")
            time.sleep(delay)

    print("[CYBERCORE] Shutdown complete")


if __name__ == "__main__":
    main()
