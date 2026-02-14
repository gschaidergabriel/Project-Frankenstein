"""
Frank Agentic Core - Autonomous Agent Framework

Transforms Frank from a reactive chatbot into a goal-driven autonomous agent
with structured tool-calling, persistent execution state, planning, and
iterative reasoning loops.

Components:
- tools: Tool registry with JSON schemas for structured calling
- state: Persistent execution state tracker across turns
- planner: Goal decomposition and multi-step planning
- loop: Think-Act-Observe agentic execution loop
- executor: Tool execution with safety checks
"""

from .tools import ToolRegistry, Tool, ToolResult
from .state import AgentState, ExecutionStep, StepStatus
from .planner import Planner, Plan, PlanStep
from .loop import AgentLoop, AgentConfig, AgentEvent
from .executor import ToolExecutor

__all__ = [
    "ToolRegistry",
    "Tool",
    "ToolResult",
    "AgentState",
    "ExecutionStep",
    "StepStatus",
    "Planner",
    "Plan",
    "PlanStep",
    "AgentLoop",
    "AgentConfig",
    "AgentEvent",
    "ToolExecutor",
]

__version__ = "1.0.0"
