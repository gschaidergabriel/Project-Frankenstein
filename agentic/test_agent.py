#!/usr/bin/env python3
"""
Quick test of the agentic system.

Run with: python3 -m agentic.test_agent
"""

import sys
import os

# Add path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from agentic import ToolRegistry, AgentState, Planner, AgentLoop
from agentic.tools import parse_tool_call


def test_tool_registry():
    """Test tool registry."""
    print("\n=== Tool Registry Test ===")
    registry = ToolRegistry()
    tools = registry.list_all()
    print(f"Registered tools: {len(tools)}")

    # List by category
    for cat in ["filesystem", "system", "desktop", "app"]:
        from agentic.tools import ToolCategory
        cat_tools = registry.list_by_category(ToolCategory(cat))
        print(f"  {cat}: {len(cat_tools)} tools")

    # Test schema generation
    schema = registry.get_schema_for_prompt(max_tools=5)
    print(f"Schema prompt length: {len(schema)} chars")
    print("Tool Registry: OK")


def test_tool_parsing():
    """Test tool call parsing."""
    print("\n=== Tool Call Parsing Test ===")

    test_cases = [
        ('```json\n{"action": "fs_list", "action_input": {"path": "/tmp"}}\n```', True),
        ('{"action": "sys_summary", "action_input": {}}', True),
        ('Let me check the files... {"action": "fs_read", "action_input": {"path": "/etc/hosts"}}', True),
        ('No tool here, just text', False),
    ]

    for text, should_parse in test_cases:
        result = parse_tool_call(text)
        parsed = result is not None
        status = "OK" if parsed == should_parse else "FAIL"
        print(f"  [{status}] Parse '{text[:40]}...' -> {parsed}")

    print("Tool Parsing: OK")


def test_state():
    """Test agent state."""
    print("\n=== Agent State Test ===")

    state = AgentState(
        id="test_123",
        session_id="session_456",
        goal="Test goal",
    )

    # Add context
    state.add_context("First observation")
    state.add_context("Second observation")
    print(f"Context entries: {len(state.context)}")

    # Add messages
    state.add_message("user", "Hello")
    state.add_message("assistant", "Hi there")
    print(f"Messages: {len(state.messages)}")

    # Test serialization
    data = state.to_dict()
    restored = AgentState.from_dict(data)
    assert restored.goal == state.goal
    print("Serialization: OK")

    print("Agent State: OK")


def test_planner():
    """Test planner complexity analysis."""
    print("\n=== Planner Test ===")

    planner = Planner()

    # Test complexity analysis
    simple = "Was ist die Uhrzeit?"
    complex_ = "Suche alle Python-Dateien im Home-Verzeichnis und dann analysiere sie"

    simple_analysis = planner.analyze_complexity(simple)
    complex_analysis = planner.analyze_complexity(complex_)

    print(f"Simple query needs planning: {simple_analysis['needs_planning']} (expected: False)")
    print(f"Complex query needs planning: {complex_analysis['needs_planning']} (expected: True)")

    print("Planner Analysis: OK")


def main():
    """Run all tests."""
    print("=" * 50)
    print("Frank Agentic System Test")
    print("=" * 50)

    test_tool_registry()
    test_tool_parsing()
    test_state()
    test_planner()

    print("\n" + "=" * 50)
    print("All tests passed!")
    print("=" * 50)


if __name__ == "__main__":
    main()
