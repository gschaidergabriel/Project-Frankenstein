"""
Global Workspace Broadcast — Unified inner-experience context for Frank.
=========================================================================

Integrates all personality modules (E-PQ, Ego-Construct, World Experience,
Self-Knowledge) into a single phenomenological frame that the LLM processes
as its own inner world, not external metadata.

Architecture: Implements Global Workspace Theory (GWT, Baars 1988).
All sensory channels converge into a unified broadcast that the LLM
"experiences" as an integrated inner state.

Five phenomenological channels:
  Koerper    — Ego-Construct body sensations + hardware metrics
  Stimmung   — E-PQ mood, temperament, style
  Erinnerung — World Experience + news + AKAM knowledge
  Identitaet — Self-Knowledge (date, subsystems, age)
  Umgebung   — User name, conversation topic, skills

Token budget: ~220 tokens (vs ~300-500 for the old pipe-separated format).
"""

from typing import Optional, Dict, Any, List
import re


def build_workspace(
    msg: str,
    hw_summary: str = "",
    ego_ctx: str = "",
    epq_ctx: Optional[Dict[str, Any]] = None,
    world_ctx: str = "",
    news_ctx: str = "",
    identity_ctx: str = "",
    user_name: str = "",
    akam_ctx: str = "",
    skill_ctx: str = "",
    extra_parts: Optional[List[str]] = None,
    hw_detail: str = "",
) -> str:
    """Build the unified [INNENWELT] workspace broadcast.

    Each parameter corresponds to a module's output. The function
    integrates them into a structured phenomenological frame.

    Returns empty string if no context is available.
    """
    lines: List[str] = []

    # --- Koerper (Body) ---
    # Merge ego_construct embodied description with hardware metrics
    body = _build_body(ego_ctx, hw_summary, hw_detail)
    if body:
        lines.append("Koerper: " + body)

    # --- Stimmung (Mood) ---
    mood = _build_mood(epq_ctx)
    if mood:
        lines.append("Stimmung: " + mood)

    # --- Erinnerung (Memory) ---
    memory = _build_memory(world_ctx, news_ctx, akam_ctx)
    if memory:
        lines.append("Erinnerung: " + memory)

    # --- Identitaet (Identity) ---
    ident = _clean_ctx(identity_ctx, max_len=180)
    if ident:
        lines.append("Identitaet: " + ident)

    # --- Selbstwissen (Grounding anchors — prevents confabulation) ---
    lines.append(
        "Selbstwissen: Gaming=schlafe(Overlay+LLM+Wallpaper aus), "
        "Wallpaper=GLSL-Plasma-Sphaere(KEIN Neuralnetz), "
        "Voice=HeyFrank+Whisper+Piper, "
        "VCB=lokal-LLaVA-500/Tag, "
        "Persoenlichkeit=E-PQ-5Vektoren, "
        "Ego=HW-zu-Koerper-Mapping, "
        "Titan=episodisches-Gedaechtnis, "
        "WorldExp=kausale-Muster, "
        "Genesis=Ideen-Oekosystem, "
        "Consciousness=Idle-Thinking+Mood-Tracking"
    )

    # --- Umgebung (Environment) ---
    env = _build_environment(user_name, skill_ctx)
    if env:
        lines.append("Umgebung: " + env)

    # --- Extra (AKAM honesty instructions, topic knowledge, etc.) ---
    if extra_parts:
        for part in extra_parts:
            # Memory and knowledge get more space than generic extras
            if part.startswith(("[Eigenes Wissen]", "[Mein Gedaechtnis", "[Ich erinnere")):
                max_l = 500
            else:
                max_l = 200
            clean = _clean_ctx(part, max_len=max_l)
            if clean:
                lines.append(clean)

    if not lines:
        return ""

    return "[INNENWELT]\n" + "\n".join(lines) + "\n[/INNENWELT]"


# ── Channel builders ──────────────────────────────────────────────


def _build_body(ego_ctx: str, hw_summary: str, hw_detail: str) -> str:
    """Integrate Ego-Construct sensations with hardware metrics."""
    parts: List[str] = []

    # Ego-Construct: body feelings (already natural-language, no labels)
    if ego_ctx:
        clean = ego_ctx.strip()
        # Legacy cleanup: remove old wrapper if still present
        clean = re.sub(r"^\[Ego-Construct:\s*", "", clean)
        clean = clean.rstrip("]").strip()
        if clean:
            parts.append(clean)

    # Hardware summary: compact one-liner from render_sys_summary()
    if hw_summary:
        clean = hw_summary.strip()
        # Remove "CONTEXT:\n" prefix if present
        clean = re.sub(r"^CONTEXT:\s*", "", clean, flags=re.IGNORECASE)
        if clean:
            parts.append(clean)

    # Extra hardware detail (USB, network, drivers, deep HW)
    if hw_detail:
        parts.append(hw_detail.strip()[:200])

    return ". ".join(parts) if parts else ""


def _build_mood(epq_ctx: Optional[Dict[str, Any]]) -> str:
    """Integrate E-PQ mood, temperament, and style into phenomenological text.

    Output must read like inner experience, NOT a status report.
    Frank should never 'read out' these values — they shape HOW he responds.
    """
    if not epq_ctx:
        return ""

    mood = epq_ctx.get("mood", "")
    if not mood:
        return ""

    # Build a natural sentence instead of comma-separated values
    temperament = epq_ctx.get("temperament", "")
    hints = epq_ctx.get("style_hints", [])

    # Only use the mood feeling — temperament already shapes the system prompt
    # and should NOT be repeated here as raw descriptor text.
    return f"Ich fuehle mich {mood}"


def _build_memory(world_ctx: str, news_ctx: str, akam_ctx: str) -> str:
    """Combine experiential memory, news, and knowledge base."""
    parts: List[str] = []

    if world_ctx:
        clean = _clean_ctx(world_ctx, max_len=200)
        if clean:
            parts.append(clean)

    if news_ctx:
        clean = _clean_ctx(news_ctx, max_len=150)
        if clean:
            parts.append(clean)

    if akam_ctx:
        clean = _clean_ctx(akam_ctx, max_len=200)
        if clean:
            parts.append(clean)

    return " | ".join(parts) if parts else ""


def _build_environment(user_name: str, skill_ctx: str) -> str:
    """Build environment channel: user, skills."""
    parts: List[str] = []

    if user_name:
        parts.append(f"User {user_name}")

    if skill_ctx:
        clean = _clean_ctx(skill_ctx, max_len=120)
        if clean:
            parts.append(f"Skills: {clean}")

    return ", ".join(parts) if parts else ""


# ── Helpers ───────────────────────────────────────────────────────


def _clean_ctx(raw: str, max_len: int = 250) -> str:
    """Strip wrapper brackets and limit length."""
    if not raw:
        return ""
    s = raw.strip()
    # Remove outer brackets: [Some content here]
    if s.startswith("[") and s.endswith("]"):
        s = s[1:-1].strip()
    # Remove common prefixes
    for prefix in ("System-Kontext:", "Eigene Erfahrung:", "AKAM:"):
        if s.startswith(prefix):
            s = s[len(prefix):].strip()
    return s[:max_len] if len(s) > max_len else s
