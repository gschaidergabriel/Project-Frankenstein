#!/usr/bin/env python3
"""
ADI Chat Handler - LLM integration for collaborative configuration.

Handles communication with the local LLM to understand user requests
and generate appropriate layout suggestions.
"""

import json
import logging
import re
import requests
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

LOG = logging.getLogger("adi.chat")

# Default LLM endpoint
DEFAULT_LLM_URL = "http://127.0.0.1:8101/v1/chat/completions"


@dataclass
class ChatMessage:
    """A single chat message."""
    role: str  # "user", "assistant", or "system"
    content: str
    timestamp: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict:
        return {
            "role": self.role,
            "content": self.content,
        }


@dataclass
class LayoutChange:
    """Represents a suggested layout change."""
    parameter: str  # "width", "height", "x", "y", "font_size", "position", "opacity"
    old_value: Any
    new_value: Any
    reason: str = ""


class ADIChatHandler:
    """
    Handles chat interactions for ADI configuration.

    Understands natural language requests and translates them
    into layout configuration changes.
    """

    def __init__(
        self,
        monitor_info: Dict[str, Any],
        current_layout: Dict[str, Any],
        llm_url: str = DEFAULT_LLM_URL,
        timeout: int = 30,
    ):
        self.monitor_info = monitor_info
        self.current_layout = current_layout.copy()
        self.llm_url = llm_url
        self.timeout = timeout

        self.messages: List[ChatMessage] = []
        self.proposals: List[Dict[str, Any]] = []

        # Initialize with system context
        self._init_system_prompt()

    def _init_system_prompt(self):
        """Set up the system prompt with monitor context."""
        monitor = self.monitor_info
        layout = self.current_layout

        system_prompt = f"""You are Frank's display configuration assistant (ADI - Adaptive Display Intelligence).

CURRENT MONITOR:
- Name: {monitor.get('name', 'Unknown')}
- Manufacturer: {monitor.get('manufacturer', 'Unknown')}
- Model: {monitor.get('model', 'Unknown')}
- Resolution: {monitor.get('resolution', [0, 0])[0]}x{monitor.get('resolution', [0, 0])[1]}
- DPI: {monitor.get('dpi', 96)}

CURRENT FRANK CONFIGURATION:
- Position: {layout.get('x', 10)}, {layout.get('y', 38)}
- Size: {layout.get('width', 420)}x{layout.get('height', 720)}
- Font size: {layout.get('font_size', 14)}px
- Opacity: {int(layout.get('opacity', 0.95) * 100)}%
- Side: {layout.get('position', 'left')}

YOUR TASK:
1. Understand what the user wants to change
2. Suggest concrete values (numbers!)
3. Briefly explain why these values are good
4. Keep answers SHORT (2-3 sentences)

WHEN THE USER WANTS TO CHANGE SOMETHING:
- Reply with new values in format: [CHANGE: parameter=value]
- Examples:
  - [CHANGE: font_size=16]
  - [CHANGE: width=450, height=750]
  - [CHANGE: position=right]
  - [CHANGE: opacity=0.9]

PARAMETER LIMITS:
- width: 300-{monitor.get('resolution', [1920, 1080])[0] // 2}
- height: 400-{monitor.get('resolution', [1920, 1080])[1] - 100}
- font_size: 10-20
- opacity: 0.5-1.0
- position: left, right
- x, y: Position values in pixels

Always answer concisely. Be friendly but precise."""

        self.messages.append(ChatMessage(
            role="system",
            content=system_prompt
        ))

    def process_user_message(self, user_input: str) -> Tuple[str, Optional[Dict[str, Any]]]:
        """
        Process a user message and return response with optional layout changes.

        Args:
            user_input: The user's message

        Returns:
            Tuple of (response_text, new_layout_or_none)
        """
        # Add user message
        self.messages.append(ChatMessage(role="user", content=user_input))

        # Check for special commands first
        special_response = self._check_special_commands(user_input)
        if special_response:
            self.messages.append(ChatMessage(role="assistant", content=special_response[0]))
            return special_response

        # Call LLM
        try:
            response_text = self._call_llm()
        except Exception as e:
            LOG.error(f"LLM call failed: {e}")
            response_text = "Sorry, I could not process the request. Please try again."
            self.messages.append(ChatMessage(role="assistant", content=response_text))
            return (response_text, None)

        # Parse for layout changes
        new_layout = self._parse_layout_changes(response_text)

        # Clean response text (remove change markers for display)
        display_text = re.sub(r'\[CHANGE:.*?\]', '', response_text).strip()

        self.messages.append(ChatMessage(role="assistant", content=display_text))

        if new_layout:
            # Store proposal
            self.proposals.append({
                "id": len(self.proposals) + 1,
                "layout": new_layout.copy(),
                "description": display_text[:100],
                "timestamp": datetime.now().isoformat(),
            })
            self.current_layout = new_layout

        return (display_text, new_layout)

    def _check_special_commands(self, user_input: str) -> Optional[Tuple[str, Optional[Dict]]]:
        """Check for special commands like rollback."""
        lower_input = user_input.lower()

        # Rollback to specific proposal
        match = re.search(r'vorschlag\s*(\d+)', lower_input)
        if match:
            proposal_id = int(match.group(1))
            return self._rollback_to_proposal(proposal_id)

        # Rollback to original/first
        if any(word in lower_input for word in ['original', 'anfang', 'erster', 'zurück zum start']):
            return self._rollback_to_proposal(1)

        # Rollback to previous
        if any(word in lower_input for word in ['vorheriger', 'letzte', 'zurück', 'undo']):
            if len(self.proposals) >= 2:
                return self._rollback_to_proposal(len(self.proposals) - 1)

        return None

    def _rollback_to_proposal(self, proposal_id: int) -> Tuple[str, Optional[Dict]]:
        """Rollback to a specific proposal."""
        if proposal_id < 1 or proposal_id > len(self.proposals):
            return (f"Proposal {proposal_id} does not exist. I have {len(self.proposals)} proposals.", None)

        proposal = self.proposals[proposal_id - 1]
        self.current_layout = proposal["layout"].copy()

        response = f"Back to proposal {proposal_id}: {proposal['description'][:50]}..."
        return (response, self.current_layout)

    def _call_llm(self) -> str:
        """Call the LLM API."""
        # Build messages for API
        api_messages = [msg.to_dict() for msg in self.messages]

        payload = {
            "model": "deepseek-r1-8b",
            "messages": api_messages,
            "max_tokens": 300,
            "temperature": 0.7,
            "stream": False,
        }

        response = requests.post(
            self.llm_url,
            json=payload,
            timeout=self.timeout,
            headers={"Content-Type": "application/json"}
        )

        response.raise_for_status()
        data = response.json()

        return data["choices"][0]["message"]["content"]

    def _parse_layout_changes(self, response: str) -> Optional[Dict[str, Any]]:
        """Parse layout changes from LLM response."""
        # Look for [CHANGE: ...] pattern
        match = re.search(r'\[CHANGE:\s*([^\]]+)\]', response, re.IGNORECASE)
        if not match:
            return None

        changes_str = match.group(1).strip()

        # Bug fix: Return None if the change string is empty
        if not changes_str:
            return None

        new_layout = self.current_layout.copy()
        has_changes = False

        # Parse individual changes: param=value, param2=value2
        for change in changes_str.split(','):
            change = change.strip()
            if '=' not in change:
                continue

            param, value = change.split('=', 1)
            param = param.strip().lower()
            value = value.strip()

            try:
                if param in ('width', 'height', 'x', 'y', 'font_size'):
                    new_layout[param] = int(value)
                    has_changes = True
                elif param == 'opacity':
                    new_layout[param] = float(value)
                    has_changes = True
                elif param == 'position':
                    if value.lower() in ('left', 'right', 'links', 'rechts'):
                        new_layout['position'] = 'left' if value.lower() in ('left', 'links') else 'right'
                        has_changes = True
            except ValueError as e:
                LOG.warning(f"Failed to parse change {param}={value}: {e}")

        # Bug fix: Return None if no valid changes were parsed
        if not has_changes:
            return None

        # Validate constraints
        monitor_res = self.monitor_info.get('resolution', [1920, 1080])
        new_layout['width'] = max(300, min(new_layout.get('width', 420), monitor_res[0] // 2))
        new_layout['height'] = max(400, min(new_layout.get('height', 720), monitor_res[1] - 100))
        new_layout['font_size'] = max(10, min(new_layout.get('font_size', 14), 20))
        new_layout['opacity'] = max(0.5, min(new_layout.get('opacity', 0.95), 1.0))

        # Bug fix: Validate x, y coordinates to keep window on-screen
        new_layout['x'] = max(0, min(new_layout.get('x', 10), monitor_res[0] - new_layout['width']))
        new_layout['y'] = max(0, min(new_layout.get('y', 38), monitor_res[1] - new_layout['height']))

        return new_layout

    def _translate_position(self, pos: str) -> str:
        """Translate position to display string."""
        return "Left" if pos == "left" else "Right" if pos == "right" else pos.capitalize()

    def get_initial_message(self, is_new_monitor: bool = True) -> str:
        """Generate the initial message from Frank."""
        monitor = self.monitor_info
        layout = self.current_layout
        pos_german = self._translate_position(layout.get('position', 'left'))

        if is_new_monitor:
            return f"""I detected a new monitor!

**{monitor.get('manufacturer', '')} {monitor.get('model', monitor.get('name', 'Monitor'))}**
Resolution: {monitor.get('resolution', [0, 0])[0]}x{monitor.get('resolution', [0, 0])[1]}

My suggestion for optimal usage:
• Window: {layout.get('width', 420)}x{layout.get('height', 720)} pixels
• Position: {pos_german}
• Font size: {layout.get('font_size', 14)}px

This should be well readable on this {'small ' if monitor.get('resolution', [1920])[0] < 1200 else ''}display. What do you think?"""
        else:
            return f"""Display settings for **{monitor.get('model', monitor.get('name', 'Monitor'))}**

Current configuration:
• Size: {layout.get('width', 420)}x{layout.get('height', 720)}
• Font: {layout.get('font_size', 14)}px
• Side: {pos_german}

What would you like to adjust?"""

    def get_proposals_summary(self) -> str:
        """Get a summary of all proposals."""
        if not self.proposals:
            return "No proposals yet."

        lines = ["Previous proposals:"]
        for p in self.proposals:
            layout = p['layout']
            lines.append(f"#{p['id']}: {layout.get('width')}x{layout.get('height')}, Font {layout.get('font_size')}")

        return '\n'.join(lines)


# Quick test
if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)

    # Test with mock data
    monitor = {
        "name": "HDMI-A-1",
        "manufacturer": "Eyoyo",
        "model": "eM713A",
        "resolution": [1024, 600],
        "dpi": 55,
    }

    layout = {
        "x": 10,
        "y": 38,
        "width": 360,
        "height": 510,
        "font_size": 12,
        "opacity": 0.95,
        "position": "left",
    }

    handler = ADIChatHandler(monitor, layout)

    print("=== Initial Message ===")
    print(handler.get_initial_message(is_new_monitor=True))
    print()

    # Test parsing (without actual LLM call)
    test_response = "Got it! I'll increase the font size to 14px. [CHANGE: font_size=14]"
    new_layout = handler._parse_layout_changes(test_response)
    print("=== Parse Test ===")
    print(f"Input: {test_response}")
    print(f"Parsed layout: {new_layout}")
