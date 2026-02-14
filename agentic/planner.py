"""
Planner Module - Goal Decomposition and Multi-Step Planning.

Uses LLM to break complex goals into executable steps,
considering available tools and their capabilities.
"""

from __future__ import annotations

import json
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
import logging

from .tools import ToolRegistry, get_registry
from .state import AgentState, ExecutionStep, StepStatus

LOG = logging.getLogger("agentic.planner")


@dataclass
class PlanStep:
    """A planned step before conversion to ExecutionStep."""
    description: str
    tool_name: Optional[str] = None
    tool_input: Optional[Dict[str, Any]] = None
    depends_on: List[str] = field(default_factory=list)
    estimated_risk: float = 0.1
    reasoning: str = ""

    def to_execution_step(self, step_id: str) -> ExecutionStep:
        """Convert to ExecutionStep for state tracking."""
        return ExecutionStep(
            id=step_id,
            description=self.description,
            tool_name=self.tool_name,
            tool_input=self.tool_input,
            status=StepStatus.PENDING,
        )


@dataclass
class Plan:
    """A complete plan with multiple steps."""
    goal: str
    steps: List[PlanStep]
    reasoning: str = ""
    estimated_total_risk: float = 0.0
    created_at: float = field(default_factory=time.time)

    def to_execution_steps(self) -> List[ExecutionStep]:
        """Convert all steps to ExecutionSteps."""
        return [
            step.to_execution_step(f"step_{i+1}_{uuid.uuid4().hex[:6]}")
            for i, step in enumerate(self.steps)
        ]

    def get_summary(self) -> str:
        """Get human-readable plan summary."""
        lines = [f"Plan for: {self.goal}", ""]
        for i, step in enumerate(self.steps, 1):
            tool_info = f" [{step.tool_name}]" if step.tool_name else ""
            lines.append(f"{i}. {step.description}{tool_info}")
        return "\n".join(lines)


# System prompt for the planner LLM
PLANNER_SYSTEM_PROMPT = """Du bist ein Planungsagent. Erstelle einen konkreten Ausfuehrungsplan mit Tool-Aufrufen.

## Tools
{tools_description}

## WICHTIG
- Jeder Schritt MUSS ein tool_name haben (fs_write, code_execute, oder bash_execute).
- Fuer Programmieraufgaben: Erstelle die Dateien mit fs_write, dann fuehre sie mit bash_execute aus.
- Kein Schritt ohne tool_name!
- NIEMALS Backslashes in Pfaden! Weder im JSON noch im tool_input content!
  FALSCH: /home/user/mein\\ ordner   RICHTIG: /home/user/mein ordner
- Bei fs_write IMMER "overwrite": true setzen!
- EINE Datei pro fs_write Schritt. Teile grosse Programme in mehrere Dateien auf.
- Halte jede Datei unter 150 Zeilen.
- Schreibe NUR valides JSON. Doppelte Anfuehrungszeichen und Doppelpunkt als Separator.
- Im generierten Python-Code: Pfade OHNE Backslashes!
  FALSCH: open('/pfad/mein\\ ordner/datei.txt')
  RICHTIG: open('/pfad/mein ordner/datei.txt')

## Antwortformat
NUR JSON, kein anderer Text:
```json
{{
  "reasoning": "Kurze Begruendung",
  "steps": [
    {{
      "description": "Verzeichnis erstellen",
      "tool_name": "bash_execute",
      "tool_input": {{"command": "mkdir -p '/home/user/mein ordner'"}},
      "estimated_risk": 0.1
    }},
    {{
      "description": "Hauptdatei schreiben",
      "tool_name": "fs_write",
      "tool_input": {{"path": "/home/user/mein ordner/main.py", "content": "#!/usr/bin/env python3\\nprint('hello')\\n", "overwrite": true}},
      "estimated_risk": 0.3
    }},
    {{
      "description": "Programm starten",
      "tool_name": "bash_execute",
      "tool_input": {{"command": "cd '/home/user/mein ordner' && python3 main.py"}},
      "estimated_risk": 0.3
    }}
  ],
  "needs_user_input": false,
  "clarification_question": null
}}
```
"""


class Planner:
    """
    Goal decomposition planner using LLM.

    Takes a natural language goal and produces a structured plan
    with executable steps.
    """

    def __init__(
        self,
        tool_registry: Optional[ToolRegistry] = None,
        llm_endpoint: str = "http://127.0.0.1:8091/route",
    ):
        self.registry = tool_registry or get_registry()
        self.llm_endpoint = llm_endpoint

    def create_plan(
        self,
        goal: str,
        context: str = "",
        max_steps: int = 10,
    ) -> Tuple[Plan, Optional[str]]:
        """
        Create an execution plan for a goal.

        Args:
            goal: The user's goal/request
            context: Additional context (previous results, etc.)
            max_steps: Maximum number of steps in plan

        Returns:
            Tuple of (Plan, clarification_question_or_none)
        """
        # Build the planning prompt
        tools_desc = self.registry.get_schema_for_prompt(max_tools=25)
        system_prompt = PLANNER_SYSTEM_PROMPT.format(tools_description=tools_desc)

        user_prompt = f"Ziel: {goal}"
        if context:
            user_prompt += f"\n\nKontext:\n{context}"

        # Call LLM for planning
        try:
            response = self._call_llm(system_prompt, user_prompt)
            plan_data = self._parse_plan_response(response)
        except Exception as e:
            LOG.error(f"Planning failed: {e}")
            # Fallback: single-step plan with final answer
            return self._create_fallback_plan(goal, str(e)), None

        # Check if clarification needed
        if plan_data.get("needs_user_input"):
            question = plan_data.get("clarification_question", "Kannst du das genauer erklären?")
            return Plan(goal=goal, steps=[], reasoning="Brauche mehr Informationen"), question

        # Build plan from response
        steps = []
        for i, step_data in enumerate(plan_data.get("steps", [])[:max_steps]):
            step = PlanStep(
                description=step_data.get("description", f"Schritt {i+1}"),
                tool_name=step_data.get("tool_name"),
                tool_input=step_data.get("tool_input", {}),
                estimated_risk=float(step_data.get("estimated_risk", 0.1)),
                reasoning=step_data.get("reasoning", ""),
            )
            steps.append(step)

        # Calculate total risk
        total_risk = max(s.estimated_risk for s in steps) if steps else 0.0

        plan = Plan(
            goal=goal,
            steps=steps,
            reasoning=plan_data.get("reasoning", ""),
            estimated_total_risk=total_risk,
        )

        LOG.info(f"Created plan with {len(steps)} steps for goal: {goal[:50]}...")
        return plan, None

    def replan(
        self,
        state: AgentState,
        failure_reason: str,
    ) -> Plan:
        """
        Create a new plan after a failure.

        Considers what was already tried and what failed.
        """
        # Build context from execution history
        context_parts = [
            f"Ursprüngliches Ziel: {state.goal}",
            "",
            "Bereits ausgeführte Schritte:",
        ]

        for step in state.plan_steps:
            if step.status == StepStatus.COMPLETED:
                context_parts.append(f"✓ {step.description}")
            elif step.status == StepStatus.FAILED:
                context_parts.append(f"✗ {step.description} - FEHLGESCHLAGEN: {step.error}")

        context_parts.extend([
            "",
            f"Letzter Fehler: {failure_reason}",
            "",
            "Bitte erstelle einen neuen Plan, der das Problem umgeht.",
        ])

        context = "\n".join(context_parts)
        plan, _ = self.create_plan(state.goal, context=context)

        LOG.info(f"Replanned with {len(plan.steps)} new steps after failure")
        return plan

    def analyze_complexity(self, goal: str) -> Dict[str, Any]:
        """
        Analyze the complexity of a goal without creating a full plan.

        Returns estimation of steps, risk, and required tools.
        """
        # Simple heuristic analysis
        goal_lower = goal.lower()

        # Detect keywords that suggest complexity
        complexity_indicators = {
            "und dann": 1,
            "danach": 1,
            "anschließend": 1,
            "mehrere": 1,
            "alle": 1,
            "jede": 1,
            "automatisch": 1,
            "überwache": 2,
            "installiere": 2,
            "lösche": 2,
            "ändere": 1,
            "programmier": 3,
            "entwickle": 3,
            "implementier": 3,
            "code schreib": 3,
            "erstelle mir": 2,
            "baue mir": 2,
            "bau mir": 2,
            "schreib mir": 2,
            "spiel": 2,
            "game": 2,
            "skript": 2,
            "script": 2,
            "webapp": 3,
            "webseite": 2,
            "website": 2,
        }

        complexity_score = sum(
            weight for keyword, weight in complexity_indicators.items()
            if keyword in goal_lower
        )

        # Detect mentioned tools
        mentioned_tools = []
        for tool in self.registry.list_all():
            if any(kw in goal_lower for kw in [tool.name, tool.description.lower()[:20]]):
                mentioned_tools.append(tool.name)

        # Estimate
        estimated_steps = max(1, min(10, complexity_score + len(mentioned_tools)))
        needs_planning = estimated_steps > 2 or complexity_score > 1

        return {
            "complexity_score": complexity_score,
            "estimated_steps": estimated_steps,
            "mentioned_tools": mentioned_tools,
            "needs_planning": needs_planning,
            "recommended_approach": "multi_step" if needs_planning else "single_turn",
        }

    def _call_llm(self, system_prompt: str, user_prompt: str) -> str:
        """Call LLM for planning."""
        import urllib.request

        payload = {
            "text": user_prompt,
            "system": system_prompt,
            "force": "qwen",
            "n_predict": 4000,
        }

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self.llm_endpoint,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=300) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                return result.get("text", result.get("response", ""))
        except urllib.request.URLError as e:
            raise RuntimeError(f"Planner LLM network error: {e}")
        except json.JSONDecodeError as e:
            raise RuntimeError(f"Planner LLM response parse error: {e}")

    def _parse_plan_response(self, response: str) -> Dict[str, Any]:
        """Parse LLM planning response."""
        # Try to extract JSON from response
        json_match = re.search(r'```(?:json)?\s*\n?(\{.+?\})\s*\n?```', response, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
        else:
            # Try to find inline JSON
            json_match = re.search(r'\{[^{}]*"steps"\s*:\s*\[[^\]]*\][^{}]*\}', response, re.DOTALL)
            if json_match:
                json_str = json_match.group(0)
            else:
                raise ValueError(f"No valid JSON found in response: {response[:200]}")

        try:
            return json.loads(json_str)
        except json.JSONDecodeError as e:
            LOG.warning(f"JSON parse error: {e}")
            raise

    def _create_fallback_plan(self, goal: str, error: str) -> Plan:
        """Create a simple fallback plan when planning fails."""
        return Plan(
            goal=goal,
            steps=[
                PlanStep(
                    description=f"Direkte Antwort auf: {goal}",
                    tool_name=None,
                    estimated_risk=0.0,
                    reasoning=f"Fallback wegen Planungsfehler: {error}",
                )
            ],
            reasoning="Fallback-Plan nach Planungsfehler",
            estimated_total_risk=0.0,
        )


# Convenience function
def analyze_and_plan(
    goal: str,
    context: str = "",
    registry: Optional[ToolRegistry] = None,
) -> Tuple[Plan, Optional[str]]:
    """
    Analyze a goal and create an execution plan.

    Returns (plan, clarification_question_or_none)
    """
    planner = Planner(tool_registry=registry)

    # First analyze complexity
    analysis = planner.analyze_complexity(goal)
    LOG.info(f"Goal analysis: {analysis}")

    if not analysis["needs_planning"]:
        # Simple goal - create minimal plan
        return Plan(
            goal=goal,
            steps=[
                PlanStep(
                    description=goal,
                    tool_name=None,
                    estimated_risk=0.1,
                )
            ],
            reasoning="Einfaches Ziel - direkte Ausführung",
        ), None

    # Complex goal - full planning
    return planner.create_plan(goal, context)
