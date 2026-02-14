#!/usr/bin/env python3
"""
Claude API Client for UI Tester.

Handles communication with Anthropic's Claude API for intelligent
autonomous testing and design analysis.
"""

import base64
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

LOG = logging.getLogger("ui_tester.claude")

# API Configuration
API_URL = "https://api.anthropic.com/v1/messages"
API_KEY = "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"
DEFAULT_MODEL = "claude-sonnet-4-20250514"
API_VERSION = "2023-06-01"


class ClaudeClient:
    """Client for Anthropic Claude API with vision support."""

    def __init__(self, api_key: str = API_KEY, model: str = DEFAULT_MODEL):
        self.api_key = api_key
        self.model = model
        self.conversation_history: List[Dict] = []

    def _encode_image(self, image_path: Path) -> str:
        """Encode image to base64."""
        with open(image_path, "rb") as f:
            return base64.standard_b64encode(f.read()).decode("utf-8")

    def _get_media_type(self, image_path: Path) -> str:
        """Get media type from file extension."""
        ext = image_path.suffix.lower()
        return {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".gif": "image/gif",
            ".webp": "image/webp",
        }.get(ext, "image/png")

    def analyze_screenshot(
        self,
        image_path: Path,
        prompt: str,
        system_prompt: Optional[str] = None
    ) -> str:
        """
        Analyze a screenshot with Claude Vision.

        Args:
            image_path: Path to the screenshot
            prompt: What to analyze/look for
            system_prompt: Optional system context

        Returns:
            Claude's analysis as string
        """
        if not image_path.exists():
            return f"Error: Image not found at {image_path}"

        image_data = self._encode_image(image_path)
        media_type = self._get_media_type(image_path)

        message_content = [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": media_type,
                    "data": image_data,
                },
            },
            {
                "type": "text",
                "text": prompt,
            },
        ]

        return self._send_message(message_content, system_prompt)

    def chat(
        self,
        message: str,
        system_prompt: Optional[str] = None,
        images: Optional[List[Path]] = None
    ) -> str:
        """
        Send a chat message, optionally with images.

        Args:
            message: The text message
            system_prompt: Optional system context
            images: Optional list of image paths to include

        Returns:
            Claude's response as string
        """
        content = []

        # Add images if provided
        if images:
            for img_path in images:
                if img_path.exists():
                    content.append({
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": self._get_media_type(img_path),
                            "data": self._encode_image(img_path),
                        },
                    })

        # Add text
        content.append({"type": "text", "text": message})

        return self._send_message(content, system_prompt)

    def _send_message(
        self,
        content: List[Dict],
        system_prompt: Optional[str] = None
    ) -> str:
        """Send message to Claude API."""
        headers = {
            "Content-Type": "application/json",
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
        }

        # Add to conversation history
        self.conversation_history.append({
            "role": "user",
            "content": content,
        })

        payload = {
            "model": self.model,
            "max_tokens": 4096,
            "messages": self.conversation_history,
        }

        if system_prompt:
            payload["system"] = system_prompt

        try:
            response = requests.post(
                API_URL,
                headers=headers,
                json=payload,
                timeout=120
            )
            response.raise_for_status()
            data = response.json()

            assistant_message = data["content"][0]["text"]

            # Add assistant response to history
            self.conversation_history.append({
                "role": "assistant",
                "content": assistant_message,
            })

            return assistant_message

        except requests.exceptions.Timeout as e:
            LOG.error(f"API request timed out: {e}")
            return f"Error: API request timed out - {e}"
        except requests.exceptions.RequestException as e:
            LOG.error(f"API request failed: {e}")
            return f"Error: API request failed - {e}"
        except json.JSONDecodeError as e:
            LOG.error(f"Invalid JSON in response: {e}")
            return f"Error: Invalid JSON response - {e}"
        except (KeyError, IndexError) as e:
            LOG.error(f"Failed to parse response: {e}")
            return f"Error: Failed to parse API response - {e}"

    def reset_conversation(self):
        """Clear conversation history."""
        self.conversation_history = []

    def get_test_action(
        self,
        screenshot_path: Path,
        test_context: Dict[str, Any],
        previous_actions: List[str]
    ) -> Dict[str, Any]:
        """
        Decide the next test action based on current state.

        Args:
            screenshot_path: Current screenshot
            test_context: Context about the test (duration, goals, etc.)
            previous_actions: List of already performed actions

        Returns:
            Dict with action details: {"action": "type", "params": {...}, "reason": "..."}
        """
        system_prompt = """Du bist ein autonomer UI-Tester für das Frank AI Chat Overlay.
Deine Aufgabe ist es, das Overlay gründlich zu testen:
- Schreibe verschiedene Nachrichten (kurz, lang, mit Sonderzeichen, Code)
- Teste Resizing und Dragging
- Teste Datei-Ingest (Drag & Drop)
- Prüfe alle visuellen Elemente auf Konsistenz
- Suche nach Bugs, Glitches, Design-Problemen
- Dokumentiere alles was du findest

Antworte IMMER mit einem JSON-Objekt im Format:
{
    "action": "type|click|drag|resize|scroll|screenshot|ingest|wait|done",
    "params": {...},
    "reason": "Why this action",
    "observations": ["What you see on the screenshot"],
    "issues_found": ["Found problems, if any"]
}

Action parameters:
- type: {"text": "text to type"}
- click: {"x": 100, "y": 200}
- drag: {"from_x": 0, "from_y": 0, "to_x": 100, "to_y": 100}
- resize: {"edge": "right|bottom|corner", "delta_x": 50, "delta_y": 50}
- scroll: {"direction": "up|down", "amount": 3}
- screenshot: {} (takes screenshot for analysis)
- ingest: {"file_type": "image|text|pdf"}
- wait: {"seconds": 2}
- done: {} (test completed)
"""

        prompt = f"""CURRENT TEST STATUS:
- Remaining time: {test_context.get('remaining_time', 'unknown')}
- Actions so far: {len(previous_actions)}
- Last actions: {previous_actions[-5:] if previous_actions else 'None'}

TEST GOALS:
1. UI functionality (Chat, Resize, Drag)
2. Design consistency (Colors, Fonts, Spacing)
3. Edge cases (long text, special characters)
4. Performance (Response time)
5. Bug hunting

Analyze the screenshot and decide the next action.
Be thorough but efficient - use the time optimally."""

        response = self.analyze_screenshot(screenshot_path, prompt, system_prompt)

        # Parse JSON from response
        try:
            # Find JSON in response
            json_start = response.find("{")
            json_end = response.rfind("}") + 1
            if json_start >= 0 and json_end > json_start:
                json_str = response[json_start:json_end]
                return json.loads(json_str)
        except json.JSONDecodeError as e:
            LOG.warning(f"Failed to parse action JSON: {e}")

        # Fallback
        return {
            "action": "screenshot",
            "params": {},
            "reason": "Fallback - konnte Antwort nicht parsen",
            "observations": [response[:200]],
            "issues_found": []
        }

    def generate_design_proposal(
        self,
        screenshots: List[Path],
        test_results: Dict[str, Any],
        issues: List[str]
    ) -> Dict[str, Any]:
        """
        Generate a design proposal based on test results.

        Args:
            screenshots: Representative screenshots from testing
            test_results: Summary of test results
            issues: List of identified issues

        Returns:
            Dict with design proposal details
        """
        system_prompt = """Du bist ein UI/UX Design-Experte spezialisiert auf Cyberpunk-Ästhetik.
Basierend auf den Test-Ergebnissen erstellst du einen detaillierten Design-Vorschlag.

Der aktuelle Style ist Cyberpunk mit:
- Neon Orange (#FF6B00) als Akzent
- Dunkle Hintergründe (#0a0a12, #12121a)
- Glow-Effekte
- Monospace-Fonts

Dein Vorschlag sollte enthalten:
1. Konkrete CSS-Änderungen
2. Layout-Anpassungen
3. Farbverbesserungen (mit Hex-Codes)
4. Typography-Empfehlungen
5. Eine ASCII-Skizze des vorgeschlagenen Layouts

Antworte mit einem strukturierten JSON."""

        issues_text = "\n".join(f"- {issue}" for issue in issues)
        prompt = f"""TEST-ERGEBNISSE:
{json.dumps(test_results, indent=2, ensure_ascii=False)}

GEFUNDENE PROBLEME:
{issues_text}

Erstelle einen detaillierten Design-Vorschlag im Cyberpunk-Style.
Berücksichtige alle gefundenen Issues und schlage konkrete Verbesserungen vor."""

        # Include up to 4 screenshots
        images = screenshots[:4] if screenshots else []
        response = self.chat(prompt, system_prompt, images)

        try:
            json_start = response.find("{")
            json_end = response.rfind("}") + 1
            if json_start >= 0 and json_end > json_start:
                return json.loads(response[json_start:json_end])
        except json.JSONDecodeError:
            pass

        return {
            "summary": response,
            "css_changes": [],
            "layout_changes": [],
            "ascii_preview": "Konnte Vorschlag nicht strukturieren"
        }


# Quick test
if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)

    client = ClaudeClient()

    # Test simple chat
    print("=== Testing Claude Client ===")
    response = client.chat("Say 'Hello' and confirm that you are working.")
    print(f"Response: {response}")
