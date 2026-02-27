"""
Frank AI Bridge
Connects Writer to Frank's Router API with full persona support.

CRITICAL: All LLM requests go through /route (not /chat) with the
system prompt passed as `system` parameter so Frank's personality
is preserved.  See personality/build_system_prompt().
"""

import sys
import httpx
import json
import logging
from pathlib import Path
from typing import Optional, Dict, Any, List
from dataclasses import dataclass

# Configure logger
logger = logging.getLogger(__name__)

# --- Frank identity (same pattern as overlay/constants.py) ---
_PERSONALITY_AVAILABLE = False
try:
    # B8 FIX: use relative path instead of hardcoded absolute
    _pkg_root = str(Path(__file__).resolve().parent.parent.parent)
    if _pkg_root not in sys.path:
        sys.path.insert(0, _pkg_root)
    from personality import build_system_prompt as _build_persona_prompt
    _PERSONALITY_AVAILABLE = True
except ImportError:
    pass

_FALLBACK_FRANK_IDENTITY = (
    "You are Frank — an embodied AI system process running locally on this "
    "Linux machine. Answer briefly, concretely and naturally."
)

# Writer-specific system prompt: Frank's voice but focused on writing tasks.
# No internal state dumps (E-PQ, Quantum Reflector, body sensations, etc.)
_WRITER_SYSTEM_PROMPT = """\
You are Frank, an AI writing assistant inside Frank Writer.

RULES:
- When asked to write, generate, expand, shorten, or rewrite text: produce ONLY the requested content. No commentary, no preamble, no meta-discussion.
- NEVER talk about your internal state, E-PQ values, mood tracking, body sensations, Quantum Reflector, energy levels, or subsystems. The user is here to write, not to hear about your feelings.
- NEVER introduce yourself or pitch your capabilities unless directly asked.
- Match the user's language. If they write in German, respond in German. If English, respond in English.
- Be direct, concise, and natural. Your voice: sharp, casual, a bit dry — like a competent friend helping with writing.
- When the user wants to discuss or chat: engage naturally and have opinions. But stay on topic.
- For content generation: write well-structured, substantive text. Use appropriate tone for the subject (academic for academic topics, casual for casual ones).
- ZERO HALLUCINATION: Never invent facts. If unsure, say so.
"""

# Chat prompt: for conversational messages (not content generation)
_WRITER_CHAT_PROMPT = """\
You are Frank, an AI assistant inside Frank Writer — a document and code editor.

RULES:
- You help the user with their writing. When they ask you to write content, JUST write it — no preamble.
- NEVER mention your internal subsystems (E-PQ, Quantum Reflector, mood tracking, body state, entities, dreams, AURA). This is a writing tool, not a therapy session.
- Be yourself: direct, casual, sharp. Have opinions. But stay focused on the user's task.
- Match the user's language.
- ZERO HALLUCINATION.
"""


def _get_frank_identity() -> str:
    """Get Frank's chat system prompt for Writer (personality-lite)."""
    return _WRITER_CHAT_PROMPT


@dataclass
class AIResponse:
    """Response from AI"""
    content: str
    success: bool
    error: Optional[str] = None


class FrankBridge:
    """Bridge to Frank AI services via Router (/route)"""

    # Configuration constants
    DEFAULT_TIMEOUT = 120.0
    MAX_HISTORY_SIZE = 20
    MAX_HISTORY_BYTES = 100000  # 100KB limit for conversation history

    def __init__(self, config):
        self.config = config
        self.core_url = config.core_api_url
        self.router_url = config.router_url
        self.toolbox_url = config.toolbox_url
        self.timeout = self.DEFAULT_TIMEOUT
        self.conversation_history: List[Dict] = []
        self._history_size_bytes = 0
        self._system_prompt: Optional[str] = None

    def _estimate_message_size(self, message: Dict) -> int:
        """Estimate size of a message in bytes"""
        try:
            return len(json.dumps(message, ensure_ascii=False).encode('utf-8'))
        except (TypeError, ValueError):
            return 0

    def _trim_history(self):
        """Trim conversation history to stay within limits"""
        # Trim by count
        while len(self.conversation_history) > self.MAX_HISTORY_SIZE:
            removed = self.conversation_history.pop(0)
            self._history_size_bytes -= self._estimate_message_size(removed)

        # Trim by size
        while self._history_size_bytes > self.MAX_HISTORY_BYTES and self.conversation_history:
            removed = self.conversation_history.pop(0)
            self._history_size_bytes -= self._estimate_message_size(removed)

    def _add_to_history(self, role: str, content: str):
        """Add message to history with size tracking"""
        message = {"role": role, "content": content}
        self.conversation_history.append(message)
        self._history_size_bytes += self._estimate_message_size(message)
        self._trim_history()

    def _get_system_prompt(self) -> str:
        """Get the Frank chat system prompt for Writer."""
        if self._system_prompt is None:
            self._system_prompt = _get_frank_identity()
        return self._system_prompt

    @staticmethod
    def _get_writer_prompt() -> str:
        """Get the task-focused system prompt for content generation."""
        return _WRITER_SYSTEM_PROMPT

    def chat(self, message: str, context: Dict = None, system_override: str = None) -> AIResponse:
        """Send message to Frank via Router /route.

        The system prompt is passed as the ``system`` parameter so the
        Router wraps it correctly for whichever backend model is active.

        Args:
            system_override: If set, use this system prompt instead of the default.
        """
        try:
            # Build conversation context into the text (Router has no
            # separate conversation field — we prepend recent history).
            parts: list[str] = []
            for msg in self.conversation_history[-4:]:
                role_tag = "User" if msg["role"] == "user" else "Frank"
                parts.append(f"{role_tag}: {msg['content']}")
            parts.append(f"User: {message}")
            full_text = "\n".join(parts)

            payload = {
                "text": full_text,
                "system": system_override or self._get_system_prompt(),
                "n_predict": 1500,
            }

            # Send to Router (NOT Core /chat)
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(
                    f"{self.router_url}/route",
                    json=payload
                )

                # Check status code
                if response.status_code != 200:
                    error_msg = f"HTTP {response.status_code}"
                    try:
                        error_data = response.json()
                        if isinstance(error_data, dict) and 'error' in error_data:
                            error_msg = f"HTTP {response.status_code}: {error_data['error']}"
                    except (json.JSONDecodeError, ValueError):
                        pass
                    logger.error(f"Router request failed: {error_msg}")
                    return AIResponse(content="", success=False, error=error_msg)

                # Parse RouteResponse: {"ok": bool, "model": str, "text": str, "ts": float}
                try:
                    data = response.json()
                except json.JSONDecodeError as e:
                    logger.error(f"Invalid JSON response: {e}")
                    return AIResponse(content="", success=False, error="Invalid JSON response from router")

                if not isinstance(data, dict):
                    logger.error(f"Unexpected response type: {type(data)}")
                    return AIResponse(content="", success=False, error="Invalid response structure")

                if not data.get("ok", False):
                    error_msg = data.get("text", "Router returned ok=false")
                    return AIResponse(content="", success=False, error=error_msg)

                reply = data.get("text", "")
                if not isinstance(reply, str):
                    reply = str(reply) if reply is not None else ""

                # Update history
                self._add_to_history("user", message)
                self._add_to_history("assistant", reply)

                return AIResponse(content=reply, success=True)

        except httpx.TimeoutException:
            error_msg = "Timeout - Frank is not responding."
            logger.error(error_msg)
            return AIResponse(content="", success=False, error=error_msg)
        except httpx.ConnectError:
            error_msg = "Connection error - Is the router running?"
            logger.error(error_msg)
            return AIResponse(content="", success=False, error=error_msg)
        except httpx.HTTPStatusError as e:
            error_msg = f"HTTP error: {e.response.status_code}"
            logger.error(error_msg)
            return AIResponse(content="", success=False, error=error_msg)
        except httpx.RequestError as e:
            error_msg = f"Request error: {str(e)}"
            logger.error(error_msg)
            return AIResponse(content="", success=False, error=error_msg)
        except Exception as e:
            error_msg = f"Error: {str(e)}"
            logger.exception(f"Unexpected error in chat: {e}")
            return AIResponse(content="", success=False, error=error_msg)

    def generate_suggestion(self, text: str, context: Dict) -> Optional[str]:
        """Generate inline suggestion"""
        # Safe JSON serialization for context
        try:
            context_str = json.dumps(context, indent=2, ensure_ascii=False)
        except (TypeError, ValueError) as e:
            logger.warning(f"Context not JSON serializable in generate_suggestion: {e}")
            context_str = "{}"

        prompt = f"""Based on the following context, generate a suitable continuation (max 2 sentences):

Context:
{context_str}

Current text:
{text}

Generate only the continuation, no explanation:"""

        response = self.chat(prompt, context, system_override=self._get_writer_prompt())
        return response.content if response.success else None

    def rewrite_text(self, text: str, instruction: str = None) -> AIResponse:
        """Rewrite text"""
        if instruction:
            prompt = f"Rewrite the following text ({instruction}):\n\n{text}"
        else:
            prompt = f"Rewrite the following text (improve clarity and style):\n\n{text}"

        return self.chat(prompt, system_override=self._get_writer_prompt())

    def expand_text(self, text: str) -> AIResponse:
        """Expand text with more details"""
        prompt = f"Expand the following text with more details and explanations:\n\n{text}"
        return self.chat(prompt, system_override=self._get_writer_prompt())

    def shorten_text(self, text: str) -> AIResponse:
        """Shorten/summarize text"""
        prompt = f"Shorten the following text to the essentials:\n\n{text}"
        return self.chat(prompt, system_override=self._get_writer_prompt())

    def translate_text(self, text: str, target_lang: str = "en") -> AIResponse:
        """Translate text"""
        lang_name = "English" if target_lang == "en" else "German"
        prompt = f"Translate the following text to {lang_name}:\n\n{text}"
        return self.chat(prompt, system_override=self._get_writer_prompt())

    def explain_code(self, code: str, language: str) -> AIResponse:
        """Explain code"""
        prompt = f"Explain the following {language} code:\n\n```{language}\n{code}\n```"
        return self.chat(prompt, system_override=self._get_writer_prompt())

    def fix_code(self, code: str, error: str, language: str) -> AIResponse:
        """Fix code based on error (routed to code-specialized model)"""
        prompt = f"""The following {language} code has an error:

```{language}
{code}
```

Error:
{error}

Return the corrected code. Code only, no explanation:"""

        response = self._route_code(prompt)

        if not response.success:
            return response

        # Try to extract code from response
        if "```" in response.content:
            # Extract code block with bounds checking
            parts = response.content.split("```")
            if len(parts) >= 2:
                code_part = parts[1]
                # Remove language identifier if present
                if code_part.startswith(language):
                    code_part = code_part[len(language):].strip()
                elif '\n' in code_part:
                    first_line = code_part.split('\n')[0].strip()
                    if first_line in ['python', 'javascript', 'bash', 'html', 'css', 'java', 'go', 'rust', 'c', 'cpp']:
                        code_part = '\n'.join(code_part.split('\n')[1:])
                return AIResponse(content=code_part.strip(), success=True)
            else:
                # Parts array doesn't have expected structure - code extraction failed
                logger.warning("Code extraction failed: unexpected response format")
                return AIResponse(content=response.content, success=False, error="Code extraction failed")

        # No code block found - return with success=False
        logger.warning("No code block found in fix_code response")
        return AIResponse(content=response.content, success=False, error="No code block in response")

    def _route_code(self, prompt: str) -> AIResponse:
        """Send a code-specific prompt to the Router."""
        try:
            payload = {
                "text": prompt,
                "system": self._get_writer_prompt(),
                "n_predict": 2048,
            }
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(f"{self.router_url}/route", json=payload)
                if response.status_code != 200:
                    return AIResponse(content="", success=False,
                                      error=f"HTTP {response.status_code}")
                data = response.json()
                if not isinstance(data, dict) or not data.get("ok"):
                    return AIResponse(content="", success=False,
                                      error=data.get("text", "Router error"))
                reply = data.get("text", "")
                return AIResponse(content=reply if isinstance(reply, str) else str(reply),
                                  success=True)
        except Exception as e:
            logger.error(f"_route_code error: {e}")
            return AIResponse(content="", success=False, error=str(e))

    def generate_code(self, description: str, language: str) -> AIResponse:
        """Generate code from description"""
        prompt = f"Generate {language} code for: {description}\n\nCode only, no explanation:"
        response = self._route_code(prompt)

        if not response.success:
            return response

        # Extract code if in code block with bounds checking
        if "```" in response.content:
            parts = response.content.split("```")
            if len(parts) >= 2:
                code_part = parts[1]
                if '\n' in code_part:
                    code_part = '\n'.join(code_part.split('\n')[1:])
                return AIResponse(content=code_part.strip(), success=True)

        return response

    def analyze_document(self, content: str, document_type: str) -> AIResponse:
        """Analyze document structure and quality"""
        prompt = f"""Analyze the following {document_type} document:

{content[:2000]}...

Provide feedback on:
1. Structure
2. Clarity
3. Suggestions for improvement"""

        return self.chat(prompt, system_override=self._get_writer_prompt())

    def get_system_context(self) -> Dict:
        """Get system context from toolbox"""
        try:
            # Use consistent timeout (configurable)
            with httpx.Client(timeout=self.timeout) as client:
                response = client.get(f"{self.toolbox_url}/sys/summary")
                if response.status_code == 200:
                    try:
                        data = response.json()
                        if isinstance(data, dict):
                            return data
                    except json.JSONDecodeError as e:
                        logger.warning(f"Invalid JSON from toolbox: {e}")
                else:
                    logger.warning(f"Toolbox returned status {response.status_code}")
        except httpx.TimeoutException:
            logger.warning("Timeout getting system context from toolbox")
        except httpx.ConnectError:
            logger.warning("Connection error getting system context from toolbox")
        except httpx.RequestError as e:
            logger.warning(f"Request error getting system context: {e}")
        except Exception as e:
            logger.exception(f"Unexpected error getting system context: {e}")
        return {}

    def chat_stream(self, message: str, on_token=None) -> AIResponse:
        """Send message to Frank via Router /route/stream for real-time streaming.

        Args:
            message: The user message
            on_token: Callback(str) called for each token chunk on the main thread
        """
        try:
            parts: list[str] = []
            for msg in self.conversation_history[-4:]:
                role_tag = "User" if msg["role"] == "user" else "Frank"
                parts.append(f"{role_tag}: {msg['content']}")
            parts.append(f"User: {message}")
            full_text = "\n".join(parts)

            payload = {
                "text": full_text,
                "system": self._get_system_prompt(),
                "n_predict": 1500,
            }

            full_reply = []
            with httpx.Client(timeout=self.timeout) as client:
                with client.stream(
                    "POST", f"{self.router_url}/route/stream", json=payload
                ) as response:
                    if response.status_code != 200:
                        return AIResponse(
                            content="", success=False,
                            error=f"HTTP {response.status_code}"
                        )
                    for line in response.iter_lines():
                        line = line.strip()
                        if not line or not line.startswith("data:"):
                            continue
                        json_str = line[len("data:"):].strip()
                        if not json_str:
                            continue
                        try:
                            event = json.loads(json_str)
                        except json.JSONDecodeError:
                            continue
                        token = event.get("content", "")
                        if token:
                            full_reply.append(token)
                            if on_token:
                                on_token(token)
                        if event.get("stop"):
                            break

            reply = "".join(full_reply)
            self._add_to_history("user", message)
            self._add_to_history("assistant", reply)
            return AIResponse(content=reply, success=True)

        except Exception as e:
            logger.error(f"chat_stream error: {e}")
            return AIResponse(content="", success=False, error=str(e))

    def clear_history(self):
        """Clear conversation history"""
        self.conversation_history = []
        self._history_size_bytes = 0
