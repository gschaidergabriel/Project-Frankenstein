"""
Frank Personality Module

Single source of truth for Frank's identity, capabilities, and behavior.
All clients (Core, Router, Overlay, CLI) should use this module.

Quick Start:
    from personality import build_system_prompt, get_persona

    # Get system prompt for LLM
    prompt = build_system_prompt()

    # Get full persona data
    persona = get_persona()

    # Check tool permissions
    from personality import is_tool_allowed
    if is_tool_allowed("fs.delete"):
        # proceed

E-PQ v2.1 (Digitales Ego):
    from personality import get_personality_context, process_event

    # Get current personality context for prompt injection
    ctx = get_personality_context()
    # ctx = {"temperament": "...", "mood": "...", "style_hints": [...]}

    # Process an event (updates personality)
    result = process_event("positive_feedback", sentiment="positive")
"""

from .personality import (
    # Core functions
    load,
    reload,
    get_persona,
    get_prompt_hash,

    # Prompt building
    build_system_prompt,
    build_minimal_prompt,
    build_full_prompt,

    # Policy & capabilities
    get_tool_policy,
    is_tool_allowed,
    get_capability_description,

    # Voice/style
    get_style_rules,
    get_tone,

    # Auto-reload
    start_auto_reload,
    stop_auto_reload,

    # Exceptions
    PersonaLoadError,
    PersonaValidationError,
)

# E-PQ v2.1 - Digitales Ego Protokoll
from .e_pq import (
    get_epq,
    get_personality_context,
    process_event,
    record_interaction,
    EPQ,
    PersonalityState,
    MoodState,
    SarcasmFilter,
    EVENT_WEIGHTS,
)

# Self-Knowledge System - Intrinsische Selbsterkenntnis
from .self_knowledge import (
    get_self_knowledge,
    explain_self,
    get_implicit_context,
    get_identity_context,
    get_core_identity,
    get_resilience_rules,
    CORE_IDENTITY,
    RESILIENCE_RULES,
    SelfKnowledge,
    BehaviorRules,
    # Location Service - Autonome Standort-Erkennung
    get_location_service,
    get_location,
    get_local_time,
    LocationService,
    LocationInfo,
)

__all__ = [
    # Static Personality
    "load",
    "reload",
    "get_persona",
    "get_prompt_hash",
    "build_system_prompt",
    "build_minimal_prompt",
    "build_full_prompt",
    "get_tool_policy",
    "is_tool_allowed",
    "get_capability_description",
    "get_style_rules",
    "get_tone",
    "start_auto_reload",
    "stop_auto_reload",
    "PersonaLoadError",
    "PersonaValidationError",
    # E-PQ v2.1 Dynamic Personality
    "get_epq",
    "get_personality_context",
    "process_event",
    "record_interaction",
    "EPQ",
    "PersonalityState",
    "MoodState",
    "SarcasmFilter",
    "EVENT_WEIGHTS",
    # Self-Knowledge System
    "get_self_knowledge",
    "explain_self",
    "get_implicit_context",
    "get_identity_context",
    "get_core_identity",
    "get_resilience_rules",
    "CORE_IDENTITY",
    "RESILIENCE_RULES",
    "SelfKnowledge",
    "BehaviorRules",
    # Location Service
    "get_location_service",
    "get_location",
    "get_local_time",
    "LocationService",
    "LocationInfo",
    # EGO-CONSTRUCT v1.0
    "get_ego_construct",
    "process_ego_trigger",
    "EgoConstruct",
    "EgoState",
]

# EGO-CONSTRUCT v1.0 - Subjective Mapping System
from .ego_construct import (
    get_ego_construct,
    process_ego_trigger,
    EgoConstruct,
    EgoState,
)

__version__ = "2.4.0"  # Updated for EGO-CONSTRUCT
