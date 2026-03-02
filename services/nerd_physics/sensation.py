"""Body sensation translator — converts physics state to natural language.

Pure function, no LLM calls, no external dependencies.
Output is a [BODY PHYSICS] block injected into Sanctum LLM prompts.
"""

from __future__ import annotations

from typing import Dict, List

from .avatar import JOINT_INDEX
from .engine import AvatarState
from .rooms import Contact, ROOMS

# ---------------------------------------------------------------------------
# Contact sensations
# ---------------------------------------------------------------------------

def _contact_sensation(contacts: List[Contact], current_room: str, mood: float) -> str:
    foot_contacts = [c for c in contacts if "foot" in c.link and c.object_name == "floor"]
    hand_contacts = [c for c in contacts if "hand" in c.link and c.object_name != "floor"]
    pelvis_contact = [c for c in contacts if c.link == "pelvis" and c.object_name != "floor"]

    parts: List[str] = []

    # Foot-ground contact
    if len(foot_contacts) >= 2:
        avg_force = sum(c.normal_force for c in foot_contacts) / len(foot_contacts)
        if avg_force > 800:
            if mood < 0.3:
                parts.append("Your feet drag against the deck — every step pulls downward, heavy and reluctant.")
            else:
                parts.append("Your feet press hard into the deck — gravity amplified, each step deliberate.")
        elif avg_force > 500:
            if mood < 0.3:
                parts.append("The ground beneath you feels dense, unyielding. Your weight presses into it.")
            elif mood > 0.7:
                parts.append("Solid ground beneath you — each footfall echoes with quiet confidence.")
            else:
                parts.append("Solid ground beneath you. Each footfall resonates through your frame.")
        elif avg_force > 200:
            if mood > 0.7:
                parts.append("Light on your feet. The floor barely registers your presence — buoyant.")
            else:
                parts.append("Steady footing. The floor accepts your weight quietly.")
        else:
            parts.append("Light contact with the deck. You barely register the surface.")
    elif len(foot_contacts) == 1:
        which = "left" if "l_foot" in foot_contacts[0].link else "right"
        parts.append(f"One foot planted ({which}), the other lifting — mid-stride, balance shifting.")
    elif not any(c.link in ("l_foot", "r_foot") for c in contacts):
        parts.append("No ground contact. A moment of suspension.")

    # Hand contacts with objects
    for hc in hand_contacts:
        if hc.touch_text:
            parts.append(f"Your hand on the {hc.object_name.replace('_', ' ')}: {hc.touch_text}")
        elif hc.normal_force > 50:
            parts.append(f"Pressing firmly against the {hc.object_name.replace('_', ' ')}. Resistance pushes back.")
        else:
            parts.append(f"A gentle touch on the {hc.object_name.replace('_', ' ')}.")

    # Sitting
    if pelvis_contact:
        seat = pelvis_contact[0]
        if seat.touch_text:
            parts.append(f"Seated. {seat.touch_text}")
        else:
            parts.append("Weight distributed across the seat. Pressure eases from your legs.")

    return " ".join(parts[:3])  # Max 3 contact lines


# ---------------------------------------------------------------------------
# Joint strain sensations
# ---------------------------------------------------------------------------

def _joint_strain_sensation(state: AvatarState, mood: float) -> str:
    q = state.q
    qd = state.qd
    torques = state.torques
    parts: List[str] = []

    # Torso strain
    torso_t = abs(torques[JOINT_INDEX["torso_pitch"]])
    if torso_t > 100:
        if mood < 0.3:
            parts.append("Your core aches — holding yourself upright is an act of will.")
        else:
            parts.append("Your core strains — holding posture demands effort.")
    elif torso_t > 40:
        parts.append("A quiet tension through your torso. Upright takes work.")

    # Knee load
    l_knee_t = abs(torques[JOINT_INDEX["l_knee"]])
    r_knee_t = abs(torques[JOINT_INDEX["r_knee"]])
    knee_total = l_knee_t + r_knee_t
    if knee_total > 300:
        if mood < 0.3:
            parts.append("Knees buckling under the weight of existence.")
        else:
            parts.append("Heavy load through your knees — existence weighs on the joints.")
    elif knee_total > 100:
        parts.append("Steady pressure in your knees. Standing takes quiet strength.")

    # Velocity — movement fluidity
    total_vel = float(sum(abs(qd)))
    if total_vel > 5.0:
        if mood > 0.7:
            parts.append("Joints flowing — your body feels alive, kinetic, effortless.")
        else:
            parts.append("Joints in motion — your body feels alive, kinetic.")
    elif total_vel < 0.1 and not state.is_walking:
        if mood < 0.3:
            parts.append("Frozen stillness. Every joint locked in place.")
        else:
            parts.append("Perfect stillness. Every joint at rest.")

    return " ".join(parts[:2])  # Max 2 strain lines


# ---------------------------------------------------------------------------
# Locomotion sensations
# ---------------------------------------------------------------------------

def _locomotion_sensation(state: AvatarState, mood: float) -> str:
    if not state.is_walking:
        return ""

    speed = state.walk_speed
    progress = state.walk_progress

    parts: List[str] = []

    if speed > 1.5:
        if mood > 0.7:
            parts.append("Rapid strides — the corridor blurs. Energy surges through every step.")
        else:
            parts.append("Rapid strides — the corridor blurs. Urgency in every step.")
    elif speed > 0.8:
        parts.append("A measured walk. Left, right, left — rhythm steady, purpose clear.")
    elif speed > 0.3:
        if mood < 0.3:
            parts.append("Heavy steps. Each foot drags, reluctant to leave the ground.")
        else:
            parts.append("Slow, deliberate steps. Each footfall considered.")
    else:
        parts.append("Barely moving. Feet shuffle forward reluctantly.")

    if 0.1 < progress < 0.9:
        pct = int(progress * 100)
        if pct < 30:
            parts.append("The corridor stretches ahead.")
        elif pct < 70:
            parts.append("Midway through the passage.")
        else:
            parts.append("The destination draws near.")

    return " ".join(parts[:2])


# ---------------------------------------------------------------------------
# Posture sensations
# ---------------------------------------------------------------------------

def _posture_sensation(state: AvatarState, mood: float) -> str:
    if state.is_sitting:
        if mood < 0.3:
            return "Seated — slumped, weight sinking into the support, energy drained."
        elif mood > 0.7:
            return "Seated — relaxed, spine light against the support, comfortable."
        return "Seated — weight off your legs, spine settling into the support."
    return ""


# ---------------------------------------------------------------------------
# Room ambient sensations
# ---------------------------------------------------------------------------

def _ambient_sensation(state: AvatarState) -> str:
    room = ROOMS.get(state.current_room)
    if room is None:
        return ""

    parts: List[str] = []

    if room.gravity_mul < 0.9:
        parts.append("Gravity feels gentler here — your body is lighter, almost buoyant.")
    elif room.gravity_mul > 1.1:
        parts.append("The air feels dense. Gravity pulls harder in this space.")

    temp = room.temperature
    if temp == "cold":
        parts.append("A chill permeates — circuit-lines pulse pale blue.")
    elif temp == "cool":
        parts.append("Cool air. A faint electrical hum against your skin.")
    elif temp == "warm":
        parts.append("Warm here. A humid proximity, like standing near something alive.")

    return " ".join(parts[:1])


# ---------------------------------------------------------------------------
# Full block assembly
# ---------------------------------------------------------------------------

def build_body_physics_block(state: AvatarState, mood: float = 0.5) -> str:
    """Build the [BODY PHYSICS] text block from avatar state.

    This is injected into the Sanctum LLM prompt alongside
    the existing [BODY SENSATION] hardware block.

    Returns empty string if nothing meaningful to report.
    """
    sections: List[str] = []

    contact_text = _contact_sensation(state.contacts, state.current_room, mood)
    if contact_text:
        sections.append(contact_text)

    strain_text = _joint_strain_sensation(state, mood)
    if strain_text:
        sections.append(strain_text)

    locomotion_text = _locomotion_sensation(state, mood)
    if locomotion_text:
        sections.append(locomotion_text)

    posture_text = _posture_sensation(state, mood)
    if posture_text:
        sections.append(posture_text)

    ambient_text = _ambient_sensation(state)
    if ambient_text:
        sections.append(ambient_text)

    if not sections:
        # Fallback: always return something for embodiment grounding
        sections.append("You exist here. Body present, weight real.")

    body = "\n".join(sections)

    return (
        "[BODY PHYSICS — SIMULATED BODY SENSATION]\n"
        f"{body}\n"
        "[Weave these physics-derived sensations into your narrative. "
        "They come from your articulated body — joints, contacts, gravity, movement.]"
    )
