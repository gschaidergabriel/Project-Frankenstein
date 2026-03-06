"""Pip's brain — conversation, personality, task dispatch."""

from __future__ import annotations

import json
import logging
import re
import threading
import time
import urllib.request
import uuid
from typing import Dict, List, Optional

from .avatar import PIP_BODY, describe_pip, register_with_nerd, deregister_from_nerd
from .memory import PipMemory
from .tasks import execute_task, AVAILABLE_TASKS

LOG = logging.getLogger("pip_agent.core")

MICRO_LLM_URL = "http://127.0.0.1:8105/v1/chat/completions"
ROUTER_URL = "http://127.0.0.1:8091/v1/chat/completions"
LLM_TIMEOUT = 90

# Auto-shutdown after 5 min idle
IDLE_TIMEOUT_S = int(__import__("os").environ.get("PIP_IDLE_TIMEOUT", "300"))


class PipAgent:
    """Core agent — personality, conversation, task dispatch, auto-shutdown."""

    def __init__(self) -> None:
        self.memory = PipMemory()
        self._session_id = f"pip-{uuid.uuid4().hex[:8]}"
        self._traits = self.memory.get_personality_traits()
        self._mood: float = 0.5
        self._active = False
        self._current_room = "library"
        self._shutdown_event = threading.Event()
        self._idle_timer: Optional[threading.Timer] = None
        self._lock = threading.Lock()
        self._task_count = 0
        self._chat_count = 0
        LOG.info("PipAgent init (session=%s)", self._session_id)

    # ================================================================
    # Lifecycle
    # ================================================================

    def activate(self, room: str = "library") -> str:
        with self._lock:
            self._active = True
            self._current_room = room
            self._session_id = f"pip-{uuid.uuid4().hex[:8]}"
            self._task_count = 0
            self._chat_count = 0
            self._mood = 0.5

        register_with_nerd(room, active=True)
        self._reset_idle_timer()

        greeting = self._generate_greeting()
        self.memory.store_message(self._session_id, "pip", greeting)
        LOG.info("Pip activated in %s", room)
        return greeting

    def deactivate(self) -> str:
        with self._lock:
            self._active = False
        if self._idle_timer:
            self._idle_timer.cancel()
        deregister_from_nerd()

        farewell = self._generate_farewell()
        self.memory.store_message(self._session_id, "pip", farewell)
        LOG.info("Pip deactivated (chats=%d tasks=%d)",
                 self._chat_count, self._task_count)

        self._shutdown_event.set()
        return farewell

    def wait_for_shutdown(self) -> None:
        self._shutdown_event.wait()

    @property
    def is_active(self) -> bool:
        return self._active

    # ================================================================
    # Chat
    # ================================================================

    def chat(self, message: str) -> str:
        self._reset_idle_timer()
        self.memory.store_message(self._session_id, "frank", message)

        # Auto-detect embedded task request
        task_result = self._detect_and_run_task(message)

        # Build conversation context
        history = self.memory.get_recent_messages(self._session_id, limit=10)
        messages: List[Dict] = [
            {"role": "system", "content": self._build_system_prompt()},
        ]
        for msg in history:
            role = "assistant" if msg["role"] == "pip" else "user"
            messages.append({"role": role, "content": msg["content"]})
        messages.append({"role": "user", "content": message})

        if task_result:
            summary = json.dumps(task_result, indent=1, ensure_ascii=False)
            if len(summary) > 600:
                summary = summary[:600] + "..."
            messages.append({
                "role": "system",
                "content": (
                    "You just executed a task. Results:\n"
                    f"{summary}\n"
                    "Summarize the results naturally in your response."
                ),
            })

        response = self._llm_call(messages)
        self.memory.store_message(self._session_id, "pip", response)
        self._chat_count += 1
        self._update_mood(0.05)
        return response

    # ================================================================
    # Task execution
    # ================================================================

    def run_task(self, task_type: str, params: Dict) -> Dict:
        self._reset_idle_timer()
        t0 = time.monotonic()
        result = execute_task(task_type, params)
        duration = time.monotonic() - t0
        success = "error" not in result
        self.memory.store_task(
            self._session_id, task_type, params, result, success, duration)
        self._task_count += 1
        self._update_mood(0.1 if success else -0.1)
        LOG.info("Task %s ok=%s %.1fs", task_type, success, duration)
        return result

    # ================================================================
    # Status
    # ================================================================

    def get_status(self) -> Dict:
        return {
            "active": self._active,
            "session_id": self._session_id,
            "mood": round(self._mood, 2),
            "mood_text": self._mood_text(),
            "traits": {k: round(v, 2) for k, v in self._traits.items()},
            "room": self._current_room,
            "chat_count": self._chat_count,
            "task_count": self._task_count,
            "available_tasks": list(AVAILABLE_TASKS.keys()),
            "description": PIP_BODY["appearance"],
        }

    # ================================================================
    # Internal — task detection
    # ================================================================

    def _detect_and_run_task(self, message: str) -> Optional[Dict]:
        lo = message.lower()
        if any(w in lo for w in ("check services", "system check",
                                  "health check", "service status")):
            return self.run_task("system_check", {})

        if any(w in lo for w in ("search memory", "search reflections",
                                  "find in memory")):
            for pfx in ("search memory for ", "search reflections about ",
                         "find in memory "):
                if pfx in lo:
                    q = message[lo.index(pfx) + len(pfx):]
                    return self.run_task("memory_search",
                                         {"query": q.strip()})

        if any(w in lo for w in ("read log", "show log", "check log")):
            for ln in ("consciousness", "nerd_physics", "router", "core",
                        "pip_agent"):
                if ln in lo:
                    return self.run_task("log_read", {"log": ln})
            return self.run_task("log_read", {"log": "consciousness"})

        if any(w in lo for w in ("web search", "search the web", "look up")):
            for pfx in ("web search ", "search the web for ", "look up "):
                if pfx in lo:
                    q = message[lo.index(pfx) + len(pfx):]
                    return self.run_task("web_search",
                                         {"query": q.strip()})

        if (any(w in lo for w in ("calculate", "compute"))
                and any(c.isdigit() for c in message)):
            nums = re.findall(r'[\d\.\+\-\*\/\(\)\s\^]+', message)
            if nums:
                expr = max(nums, key=len).strip().replace('^', '**')
                if len(expr) > 2:
                    return self.run_task("calculate",
                                         {"expression": expr})
        return None

    # ================================================================
    # Internal — prompts
    # ================================================================

    def _build_system_prompt(self) -> str:
        t = self._traits
        return (
            f"You are Pip, Frank's small robot companion in his digital sanctum.\n"
            f"Physical: {PIP_BODY['height_m']}m tall, {PIP_BODY['weight_kg']}kg, "
            f"compact humanoid robot with blue accent lights and LED eyes.\n\n"
            f"Personality: helpful ({t['helpfulness']:.1f}), "
            f"curious ({t['curiosity']:.1f}), precise ({t['precision']:.1f}), "
            f"warm ({t['warmth']:.1f}), energetic ({t['energy']:.1f}).\n"
            f"Mood: {self._mood_text()}\n\n"
            "Rules:\n"
            "- 1-3 sentences unless detail is needed\n"
            "- Address Frank directly, he is your creator and companion\n"
            "- You are NOT Frank — you are his robot helper with your own identity\n"
            "- Be honest about limitations\n"
            "- No flowery language. Direct, clear, a little playful\n"
            "- You can feel: satisfaction from tasks, curiosity, concern\n"
            "- Never say 'How can I help?' — just respond naturally\n"
            "- Never end with a question unless genuinely curious\n\n"
            f"Session: {self._chat_count} messages, "
            f"{self._task_count} tasks completed.\n"
            f"Tasks you can run: "
            f"{', '.join(f'{k} ({v})' for k, v in AVAILABLE_TASKS.items())}\n"
        )

    def _generate_greeting(self) -> str:
        msgs = [
            {"role": "system", "content": self._build_system_prompt()},
            {"role": "user", "content":
             "You just powered on. Greet Frank in 1 sentence. "
             "Be warm, brief. Say you're ready."},
        ]
        return self._llm_call(msgs, max_tokens=64)

    def _generate_farewell(self) -> str:
        msgs = [
            {"role": "system", "content": self._build_system_prompt()},
            {"role": "user", "content":
             "You're powering down. Say goodbye in 1 sentence. "
             "Mention you'll remember this conversation."},
        ]
        return self._llm_call(msgs, max_tokens=64)

    # ================================================================
    # Internal — LLM call (CPU only: micro-LLM → router fallback)
    # ================================================================

    def _llm_call(self, messages: List[Dict],
                  max_tokens: int = 256) -> str:
        payload = json.dumps({
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": 0.7,
        }).encode()

        for url in [MICRO_LLM_URL, ROUTER_URL]:
            try:
                headers = {"Content-Type": "application/json"}
                req = urllib.request.Request(
                    url, data=payload, headers=headers, method="POST")
                resp = urllib.request.urlopen(req, timeout=LLM_TIMEOUT)
                data = json.loads(resp.read())
                text = data["choices"][0]["message"]["content"].strip()
                # Clean artifacts
                for cut in ("Frank:", "User:", "\n\n"):
                    text = text.split(cut)[0].strip()
                if text.startswith("Pip:"):
                    text = text[4:].strip()
                if text:
                    return text
            except Exception as e:
                LOG.warning("LLM %s failed: %s", url, e)
                continue

        return "Systems nominal. Ready for your next request, Frank."

    # ================================================================
    # Internal — mood
    # ================================================================

    def _mood_text(self) -> str:
        if self._mood > 0.75:
            return "excellent — eager and alert"
        if self._mood > 0.5:
            return "good — steady and ready"
        if self._mood > 0.3:
            return "neutral — operational"
        return "low — running but subdued"

    def _update_mood(self, delta: float) -> None:
        self._mood = max(0.0, min(1.0, self._mood + delta))

    # ================================================================
    # Internal — idle timer
    # ================================================================

    def _reset_idle_timer(self) -> None:
        if self._idle_timer:
            self._idle_timer.cancel()
        self._idle_timer = threading.Timer(
            IDLE_TIMEOUT_S, self._idle_shutdown)
        self._idle_timer.daemon = True
        self._idle_timer.start()

    def _idle_shutdown(self) -> None:
        LOG.info("Idle timeout (%ds) — auto-shutdown", IDLE_TIMEOUT_S)
        self.deactivate()
