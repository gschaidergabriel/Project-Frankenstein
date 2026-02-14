#!/usr/bin/env python3
"""
Personality Module Tests

Run: python3 -m pytest tests/test_personality.py -v
Or:  python3 tests/test_personality.py
"""

import json
import sys
from pathlib import Path

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from personality import (
    load,
    reload,
    get_persona,
    get_prompt_hash,
    build_system_prompt,
    build_minimal_prompt,
    build_full_prompt,
    get_tool_policy,
    is_tool_allowed,
    get_capability_description,
    get_style_rules,
    get_tone,
    PersonaLoadError,
    PersonaValidationError,
)


def test_load():
    """Test loading persona from file."""
    persona = load(force=True)
    assert persona is not None
    assert persona["id"] == "frank.v1"
    assert persona["name"] == "Frank"
    assert persona["language"] == "de"
    print("✓ test_load")


def test_get_prompt_hash():
    """Test hash generation."""
    info = get_prompt_hash()
    assert "id" in info
    assert "version" in info
    assert "sha256" in info
    assert len(info["sha256"]) == 64  # SHA256 hex length
    print(f"✓ test_get_prompt_hash: {info['id']} v{info['version']}")


def test_build_system_prompt():
    """Test system prompt building."""
    prompt = build_system_prompt()
    assert len(prompt) > 100
    assert "Frank" in prompt
    assert len(prompt) <= 4096  # Max length
    print(f"✓ test_build_system_prompt: {len(prompt)} chars")


def test_build_minimal_prompt():
    """Test minimal prompt."""
    minimal = build_minimal_prompt()
    full = build_full_prompt()
    assert len(minimal) < len(full)
    assert "Frank" in minimal
    print(f"✓ test_build_minimal_prompt: {len(minimal)} chars (vs {len(full)} full)")


def test_build_with_runtime_context():
    """Test prompt with runtime context."""
    prompt = build_system_prompt(runtime_context={
        "CPU": "45°C",
        "RAM": "8GB/32GB",
        "Uptime": "2 days"
    })
    assert "SYSTEM-KONTEXT" in prompt
    assert "45°C" in prompt
    print("✓ test_build_with_runtime_context")


def test_tool_policy():
    """Test tool policy functions."""
    policy = get_tool_policy()
    assert "default" in policy
    assert "allow" in policy
    assert "deny" in policy

    # Test specific tools
    assert is_tool_allowed("fs.read") == True
    assert is_tool_allowed("fs.list") == True
    assert is_tool_allowed("fs.delete_system") == False
    assert is_tool_allowed("network.exfiltration") == False
    print("✓ test_tool_policy")


def test_capability_description():
    """Test capability descriptions."""
    desc = get_capability_description("desktop")
    assert desc is not None
    assert "Screenshot" in desc or "Bildschirm" in desc

    desc = get_capability_description("nonexistent")
    assert desc is None
    print("✓ test_capability_description")


def test_voice_style():
    """Test voice/style functions."""
    rules = get_style_rules()
    assert len(rules) > 0
    assert isinstance(rules[0], str)

    tone = get_tone()
    assert len(tone) > 0
    print(f"✓ test_voice_style: tone='{tone}'")


def test_profiles():
    """Test different profiles."""
    default_prompt = build_system_prompt(profile="default")
    minimal_prompt = build_system_prompt(profile="minimal")
    full_prompt = build_system_prompt(profile="full")

    # Minimal should be shorter
    assert len(minimal_prompt) <= len(default_prompt)
    print("✓ test_profiles")


def run_all_tests():
    """Run all tests."""
    print("=" * 50)
    print("Running Personality Module Tests")
    print("=" * 50)

    tests = [
        test_load,
        test_get_prompt_hash,
        test_build_system_prompt,
        test_build_minimal_prompt,
        test_build_with_runtime_context,
        test_tool_policy,
        test_capability_description,
        test_voice_style,
        test_profiles,
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            test()
            passed += 1
        except AssertionError as e:
            print(f"✗ {test.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"✗ {test.__name__}: Exception: {e}")
            failed += 1

    print("=" * 50)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 50)

    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
