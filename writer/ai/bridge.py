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
    "Du bist Frank - ein verkörperter KI-Systemprozess, der lokal auf diesem "
    "Ubuntu-Rechner läuft. Antworte kurz, konkret und natürlich auf Deutsch."
)


def _get_frank_identity() -> str:
    """Get Frank's system prompt from the personality module (with fallback)."""
    if _PERSONALITY_AVAILABLE:
        try:
            return _build_persona_prompt()
        except Exception:
            pass
    return _FALLBACK_FRANK_IDENTITY


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
        """Get (and cache) the Frank system prompt."""
        if self._system_prompt is None:
            self._system_prompt = _get_frank_identity()
        return self._system_prompt

    def chat(self, message: str, context: Dict = None) -> AIResponse:
        """Send message to Frank via Router /route with full persona.

        The system prompt is passed as the ``system`` parameter so the
        Router wraps it correctly for whichever backend model is active.
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
                "system": self._get_system_prompt(),
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
            error_msg = "Timeout - Frank antwortet nicht."
            logger.error(error_msg)
            return AIResponse(content="", success=False, error=error_msg)
        except httpx.ConnectError:
            error_msg = "Verbindungsfehler - Ist der Router aktiv?"
            logger.error(error_msg)
            return AIResponse(content="", success=False, error=error_msg)
        except httpx.HTTPStatusError as e:
            error_msg = f"HTTP Fehler: {e.response.status_code}"
            logger.error(error_msg)
            return AIResponse(content="", success=False, error=error_msg)
        except httpx.RequestError as e:
            error_msg = f"Request Fehler: {str(e)}"
            logger.error(error_msg)
            return AIResponse(content="", success=False, error=error_msg)
        except Exception as e:
            error_msg = f"Fehler: {str(e)}"
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

        prompt = f"""Basierend auf folgendem Kontext, generiere eine passende Fortsetzung (max 2 Satze):

Kontext:
{context_str}

Aktueller Text:
{text}

Generiere nur die Fortsetzung, keine Erklarung:"""

        response = self.chat(prompt, context)
        return response.content if response.success else None

    def rewrite_text(self, text: str, instruction: str = None) -> AIResponse:
        """Rewrite text"""
        if instruction:
            prompt = f"Schreibe folgenden Text um ({instruction}):\n\n{text}"
        else:
            prompt = f"Schreibe folgenden Text um (verbessere Klarheit und Stil):\n\n{text}"

        return self.chat(prompt)

    def expand_text(self, text: str) -> AIResponse:
        """Expand text with more details"""
        prompt = f"Erweitere folgenden Text mit mehr Details und Erklarungen:\n\n{text}"
        return self.chat(prompt)

    def shorten_text(self, text: str) -> AIResponse:
        """Shorten/summarize text"""
        prompt = f"Kurze folgenden Text auf das Wesentliche:\n\n{text}"
        return self.chat(prompt)

    def translate_text(self, text: str, target_lang: str = "en") -> AIResponse:
        """Translate text"""
        lang_name = "Englisch" if target_lang == "en" else "Deutsch"
        prompt = f"Ubersetze folgenden Text auf {lang_name}:\n\n{text}"
        return self.chat(prompt)

    def explain_code(self, code: str, language: str) -> AIResponse:
        """Explain code"""
        prompt = f"Erklare folgenden {language} Code:\n\n```{language}\n{code}\n```"
        return self.chat(prompt)

    def fix_code(self, code: str, error: str, language: str) -> AIResponse:
        """Fix code based on error (routed to code-specialized model)"""
        prompt = f"""Folgender {language} Code hat einen Fehler:

```{language}
{code}
```

Fehler:
{error}

Gib den korrigierten Code zuruck. Nur Code, keine Erklarung:"""

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
        """Send a code-specific prompt to the Router with force=coder."""
        try:
            payload = {
                "text": prompt,
                "system": self._get_system_prompt(),
                "n_predict": 2048,
                "force": "coder",
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
        prompt = f"Generiere {language} Code fur: {description}\n\nNur Code, keine Erklarung:"
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
        prompt = f"""Analysiere folgendes {document_type} Dokument:

{content[:2000]}...

Gib Feedback zu:
1. Struktur
2. Klarheit
3. Verbesserungsvorschlage"""

        return self.chat(prompt)

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
                    for chunk in response.iter_text():
                        if chunk:
                            full_reply.append(chunk)
                            if on_token:
                                on_token(chunk)

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
