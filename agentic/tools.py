"""
Tool Registry with JSON Schema definitions for structured function calling.

Each tool has:
- name: Unique identifier
- description: What the tool does (for LLM context)
- parameters: JSON Schema for input validation
- returns: Description of return value
- risk_level: 0.0-1.0 for E-SIR integration
- category: Grouping for tool discovery
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Union
import logging

LOG = logging.getLogger("agentic.tools")


class ToolCategory(str, Enum):
    """Tool categories for organization and discovery."""
    FILESYSTEM = "filesystem"
    SYSTEM = "system"
    DESKTOP = "desktop"
    APP = "app"
    STEAM = "steam"
    WEB = "web"
    MEMORY = "memory"
    CODE = "code"
    COMMUNICATION = "communication"


@dataclass
class ToolParameter:
    """Single parameter definition."""
    name: str
    type: str  # string, integer, number, boolean, array, object
    description: str
    required: bool = True
    default: Any = None
    enum: Optional[List[Any]] = None
    items: Optional[Dict[str, Any]] = None  # For array types


@dataclass
class Tool:
    """Tool definition with schema."""
    name: str
    description: str
    parameters: List[ToolParameter]
    category: ToolCategory
    risk_level: float = 0.1  # 0.0 = safe, 1.0 = dangerous
    returns: str = "Dict with 'ok' boolean and result data"
    requires_approval: bool = False  # If True, always ask user
    endpoint: Optional[str] = None  # HTTP endpoint if applicable
    handler: Optional[Callable[..., Dict[str, Any]]] = None  # Direct function

    def to_schema(self) -> Dict[str, Any]:
        """Convert to JSON Schema format for LLM."""
        properties = {}
        required = []

        for param in self.parameters:
            prop: Dict[str, Any] = {
                "type": param.type,
                "description": param.description,
            }
            if param.enum:
                prop["enum"] = param.enum
            if param.items:
                prop["items"] = param.items
            if param.default is not None:
                prop["default"] = param.default

            properties[param.name] = prop
            if param.required:
                required.append(param.name)

        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
            "category": self.category.value,
            "risk_level": self.risk_level,
        }

    def to_prompt_description(self) -> str:
        """Generate description for LLM prompt."""
        params_str = ", ".join(
            f"{p.name}: {p.type}" + ("?" if not p.required else "")
            for p in self.parameters
        )
        return f"{self.name}({params_str}) - {self.description} [risk: {self.risk_level:.1f}]"


@dataclass
class ToolResult:
    """Result from tool execution."""
    tool_name: str
    success: bool
    data: Dict[str, Any]
    error: Optional[str] = None
    execution_time_ms: float = 0.0

    def to_context(self) -> str:
        """Convert to string for LLM context injection."""
        if self.success:
            # Truncate large results
            data_str = json.dumps(self.data, ensure_ascii=False)
            if len(data_str) > 2000:
                data_str = data_str[:2000] + "... [truncated]"
            return f"[{self.tool_name}] SUCCESS: {data_str}"
        else:
            return f"[{self.tool_name}] FAILED: {self.error}"


class ToolRegistry:
    """Central registry of all available tools."""

    def __init__(self):
        self._tools: Dict[str, Tool] = {}
        self._by_category: Dict[ToolCategory, List[str]] = {
            cat: [] for cat in ToolCategory
        }
        self._register_builtin_tools()

    def register(self, tool: Tool) -> None:
        """Register a new tool."""
        self._tools[tool.name] = tool
        if tool.name not in self._by_category[tool.category]:
            self._by_category[tool.category].append(tool.name)
        LOG.debug(f"Registered tool: {tool.name} [{tool.category.value}]")

    def get(self, name: str) -> Optional[Tool]:
        """Get tool by name."""
        return self._tools.get(name)

    def list_all(self) -> List[Tool]:
        """List all registered tools."""
        return list(self._tools.values())

    def list_by_category(self, category: ToolCategory) -> List[Tool]:
        """List tools in a category."""
        return [self._tools[name] for name in self._by_category.get(category, [])]

    def get_schema_for_prompt(self, max_tools: int = 30) -> str:
        """Generate tool descriptions for LLM system prompt."""
        lines = ["## Available Tools\n"]

        for category in ToolCategory:
            tools = self.list_by_category(category)
            if not tools:
                continue
            lines.append(f"\n### {category.value.upper()}")
            for tool in tools[:max_tools]:
                lines.append(f"- {tool.to_prompt_description()}")

        lines.append("\n## Tool Call Format")
        lines.append("To use a tool, respond with JSON in this format:")
        lines.append("```json")
        lines.append('{"action": "tool_name", "action_input": {"param1": "value1"}}')
        lines.append("```")
        lines.append("\nTo complete without a tool, respond with:")
        lines.append("```json")
        lines.append('{"action": "final_answer", "action_input": {"response": "your response"}}')
        lines.append("```")

        return "\n".join(lines)

    def get_all_schemas(self) -> List[Dict[str, Any]]:
        """Get JSON schemas for all tools (for API/validation)."""
        return [tool.to_schema() for tool in self._tools.values()]

    def _register_builtin_tools(self) -> None:
        """Register all built-in Frank tools."""

        # ============ FILESYSTEM TOOLS ============

        self.register(Tool(
            name="fs_list",
            description="List files and directories at a path. Returns names, sizes, and types.",
            category=ToolCategory.FILESYSTEM,
            risk_level=0.1,
            endpoint="/fs/list",
            parameters=[
                ToolParameter("path", "string", "Directory path to list", required=True),
                ToolParameter("recursive", "boolean", "Include subdirectories", required=False, default=False),
                ToolParameter("max_entries", "integer", "Maximum entries to return", required=False, default=100),
                ToolParameter("include_hidden", "boolean", "Include hidden files (starting with .)", required=False, default=False),
            ],
        ))

        self.register(Tool(
            name="fs_read",
            description="Read contents of a file. Returns text for text files, base64 for binary.",
            category=ToolCategory.FILESYSTEM,
            risk_level=0.1,
            endpoint="/fs/read",
            parameters=[
                ToolParameter("path", "string", "File path to read", required=True),
                ToolParameter("max_bytes", "integer", "Maximum bytes to read", required=False, default=256000),
            ],
        ))

        self.register(Tool(
            name="fs_write",
            description="Write content to a file. Creates parent directories if needed.",
            category=ToolCategory.FILESYSTEM,
            risk_level=0.5,
            requires_approval=True,
            endpoint="/fs/write",
            parameters=[
                ToolParameter("path", "string", "File path to write", required=True),
                ToolParameter("content", "string", "Content to write", required=True),
                ToolParameter("overwrite", "boolean", "Overwrite if exists", required=False, default=False),
            ],
        ))

        self.register(Tool(
            name="fs_move",
            description="Move or rename a file or directory.",
            category=ToolCategory.FILESYSTEM,
            risk_level=0.4,
            endpoint="/fs/move",
            parameters=[
                ToolParameter("src", "string", "Source path", required=True),
                ToolParameter("dst", "string", "Destination path", required=True),
                ToolParameter("overwrite", "boolean", "Overwrite if destination exists", required=False, default=False),
            ],
        ))

        self.register(Tool(
            name="fs_copy",
            description="Copy a file or directory.",
            category=ToolCategory.FILESYSTEM,
            risk_level=0.3,
            endpoint="/fs/copy",
            parameters=[
                ToolParameter("src", "string", "Source path", required=True),
                ToolParameter("dst", "string", "Destination path", required=True),
                ToolParameter("overwrite", "boolean", "Overwrite if destination exists", required=False, default=False),
            ],
        ))

        self.register(Tool(
            name="fs_delete",
            description="Delete a file or directory. USE WITH CAUTION.",
            category=ToolCategory.FILESYSTEM,
            risk_level=0.8,
            requires_approval=True,
            endpoint="/fs/delete",
            parameters=[
                ToolParameter("path", "string", "Path to delete", required=True),
            ],
        ))

        self.register(Tool(
            name="fs_backup",
            description="Create timestamped backup of files/directories.",
            category=ToolCategory.FILESYSTEM,
            risk_level=0.2,
            endpoint="/fs/backup",
            parameters=[
                ToolParameter("src_paths", "array", "List of paths to backup", required=True, items={"type": "string"}),
                ToolParameter("backup_dir", "string", "Backup destination directory", required=False),
                ToolParameter("mode", "string", "Backup mode", required=False, default="copy", enum=["copy", "move"]),
            ],
        ))

        # ============ SYSTEM TOOLS ============

        self.register(Tool(
            name="sys_summary",
            description="Get system summary: CPU, memory, disk, temperatures, load.",
            category=ToolCategory.SYSTEM,
            risk_level=0.0,
            endpoint="/sys/summary",
            parameters=[],
        ))

        self.register(Tool(
            name="sys_mem",
            description="Get detailed memory usage (RAM and swap).",
            category=ToolCategory.SYSTEM,
            risk_level=0.0,
            endpoint="/sys/mem",
            parameters=[],
        ))

        self.register(Tool(
            name="sys_disk",
            description="Get disk usage for specified paths.",
            category=ToolCategory.SYSTEM,
            risk_level=0.0,
            endpoint="/sys/disk",
            parameters=[
                ToolParameter("paths", "array", "Paths to check", required=False, items={"type": "string"}),
            ],
        ))

        self.register(Tool(
            name="sys_temps",
            description="Get CPU and component temperatures.",
            category=ToolCategory.SYSTEM,
            risk_level=0.0,
            endpoint="/sys/temps",
            parameters=[],
        ))

        self.register(Tool(
            name="sys_cpu",
            description="Get CPU information (model, cores, frequency).",
            category=ToolCategory.SYSTEM,
            risk_level=0.0,
            endpoint="/sys/cpu",
            parameters=[],
        ))

        self.register(Tool(
            name="sys_os",
            description="Get operating system information.",
            category=ToolCategory.SYSTEM,
            risk_level=0.0,
            endpoint="/sys/os",
            parameters=[],
        ))

        self.register(Tool(
            name="sys_network",
            description="Get network interfaces with IPs and MACs.",
            category=ToolCategory.SYSTEM,
            risk_level=0.0,
            endpoint="/sys/network",
            parameters=[],
        ))

        self.register(Tool(
            name="sys_usb",
            description="List connected USB devices.",
            category=ToolCategory.SYSTEM,
            risk_level=0.0,
            endpoint="/sys/usb",
            parameters=[],
        ))

        self.register(Tool(
            name="sys_usb_storage",
            description="List USB storage devices with mount status, partitions, labels and filesystems.",
            category=ToolCategory.SYSTEM,
            risk_level=0.0,
            endpoint="/sys/usb/storage",
            parameters=[],
        ))

        self.register(Tool(
            name="sys_usb_mount",
            description="Mount a USB storage device. Accepts device path (/dev/sdb1), label or name.",
            category=ToolCategory.SYSTEM,
            risk_level=0.3,
            endpoint="/sys/usb/mount",
            parameters=[
                ToolParameter(name="device", type="string", description="Device path, label or name to mount"),
            ],
        ))

        self.register(Tool(
            name="sys_usb_unmount",
            description="Unmount a USB storage device. Accepts device path, mountpoint or label.",
            category=ToolCategory.SYSTEM,
            risk_level=0.2,
            endpoint="/sys/usb/unmount",
            parameters=[
                ToolParameter(name="device", type="string", description="Device path, mountpoint or label to unmount"),
            ],
        ))

        self.register(Tool(
            name="sys_usb_eject",
            description="Safely eject a USB device: unmounts all partitions and powers off the drive.",
            category=ToolCategory.SYSTEM,
            risk_level=0.3,
            endpoint="/sys/usb/eject",
            parameters=[
                ToolParameter(name="device", type="string", description="Device path or label to eject"),
            ],
        ))

        self.register(Tool(
            name="sys_services",
            description="List user systemd services and their status.",
            category=ToolCategory.SYSTEM,
            risk_level=0.0,
            endpoint="/sys/services_user",
            parameters=[],
        ))

        # ============ DESKTOP TOOLS ============

        self.register(Tool(
            name="desktop_screenshot",
            description="Take a screenshot of the current desktop.",
            category=ToolCategory.DESKTOP,
            risk_level=0.1,
            endpoint="/desktop/screenshot",
            parameters=[],
        ))

        self.register(Tool(
            name="desktop_open_url",
            description="Open a URL in the default browser.",
            category=ToolCategory.DESKTOP,
            risk_level=0.2,
            endpoint="/desktop/open_url",
            parameters=[
                ToolParameter("url", "string", "URL to open", required=True),
            ],
        ))

        # ============ APP TOOLS ============

        self.register(Tool(
            name="app_list",
            description="List installed desktop applications.",
            category=ToolCategory.APP,
            risk_level=0.0,
            endpoint="/app/list",
            parameters=[],
        ))

        self.register(Tool(
            name="app_search",
            description="Search for applications by name.",
            category=ToolCategory.APP,
            risk_level=0.0,
            endpoint="/app/search",
            parameters=[
                ToolParameter("query", "string", "Search query", required=True),
            ],
        ))

        self.register(Tool(
            name="app_open",
            description="Open/launch an application.",
            category=ToolCategory.APP,
            risk_level=0.3,
            endpoint="/app/open",
            parameters=[
                ToolParameter("name", "string", "Application name or .desktop file", required=True),
            ],
        ))

        self.register(Tool(
            name="app_close",
            description="Close a running application.",
            category=ToolCategory.APP,
            risk_level=0.4,
            endpoint="/app/close",
            parameters=[
                ToolParameter("name", "string", "Application name or window title", required=True),
            ],
        ))

        # ============ STEAM TOOLS ============

        self.register(Tool(
            name="steam_list",
            description="List installed Steam games.",
            category=ToolCategory.STEAM,
            risk_level=0.0,
            endpoint="/steam/list",
            parameters=[],
        ))

        self.register(Tool(
            name="steam_search",
            description="Search installed Steam games by name.",
            category=ToolCategory.STEAM,
            risk_level=0.0,
            endpoint="/steam/search",
            parameters=[
                ToolParameter("query", "string", "Game name to search", required=True),
            ],
        ))

        self.register(Tool(
            name="steam_launch",
            description="Launch a Steam game.",
            category=ToolCategory.STEAM,
            risk_level=0.2,
            endpoint="/steam/launch",
            parameters=[
                ToolParameter("game", "string", "Game name or app ID", required=True),
            ],
        ))

        self.register(Tool(
            name="steam_close",
            description="Close a running Steam game.",
            category=ToolCategory.STEAM,
            risk_level=0.3,
            endpoint="/steam/close",
            parameters=[
                ToolParameter("game", "string", "Game name", required=True),
            ],
        ))

        # ============ WEB TOOLS ============

        self.register(Tool(
            name="web_search",
            description="Search the web using DuckDuckGo.",
            category=ToolCategory.WEB,
            risk_level=0.1,
            endpoint="http://127.0.0.1:8093/search",
            parameters=[
                ToolParameter("query", "string", "Search query", required=True),
                ToolParameter("max_results", "integer", "Maximum results", required=False, default=8),
            ],
        ))

        self.register(Tool(
            name="web_fetch",
            description="Fetch and parse a web page.",
            category=ToolCategory.WEB,
            risk_level=0.2,
            endpoint="http://127.0.0.1:8093/fetch",
            parameters=[
                ToolParameter("url", "string", "URL to fetch", required=True),
            ],
        ))

        # ============ DOCUMENT TOOLS ============

        self.register(Tool(
            name="doc_read",
            description="Read and extract text from documents (PDF, DOCX, TXT, images). Returns extracted text content. Use this instead of fs_read for PDF and DOCX files.",
            category=ToolCategory.FILESYSTEM,
            risk_level=0.1,
            endpoint="http://127.0.0.1:8094/read_file",
            parameters=[
                ToolParameter("path", "string", "Absolute path to the document file", required=True),
            ],
        ))

        # ============ MEMORY TOOLS ============

        self.register(Tool(
            name="memory_search",
            description="Search Frank's episodic memory (Titan) for relevant information.",
            category=ToolCategory.MEMORY,
            risk_level=0.0,
            endpoint="http://127.0.0.1:8088/memory/search",
            parameters=[
                ToolParameter("query", "string", "What to search for", required=True),
                ToolParameter("limit", "integer", "Maximum results", required=False, default=5),
            ],
        ))

        self.register(Tool(
            name="memory_store",
            description="Store a fact or event in Frank's memory.",
            category=ToolCategory.MEMORY,
            risk_level=0.2,
            endpoint="http://127.0.0.1:8088/memory/store",
            parameters=[
                ToolParameter("content", "string", "What to remember", required=True),
                ToolParameter("category", "string", "Category (fact, event, preference)", required=False, default="fact"),
            ],
        ))

        # ============ ENTITY SESSION TOOLS ============

        self.register(Tool(
            name="entity_sessions",
            description="List past sessions with Frank's entities (Kairos, Dr. Hibbert, Atlas, Echo). Use to recall what was discussed.",
            category=ToolCategory.MEMORY,
            risk_level=0.0,
            endpoint="/entity/sessions",
            parameters=[
                ToolParameter("entity", "string", "Entity name filter: kairos, hibbert, atlas, echo, or 'all'", required=False, default="all"),
                ToolParameter("limit", "integer", "Max sessions to return", required=False, default=10),
            ],
        ))

        self.register(Tool(
            name="entity_session_read",
            description="Read full transcript of a specific entity session by session_id. Includes summary, topics, observations, and conversation history.",
            category=ToolCategory.MEMORY,
            risk_level=0.0,
            endpoint="/entity/session",
            parameters=[
                ToolParameter("session_id", "string", "Session ID (e.g. 'kairos_20260220_043716')", required=True),
                ToolParameter("include_history", "boolean", "Include full conversation history", required=False, default=True),
            ],
        ))

        self.register(Tool(
            name="entity_sessions_search",
            description="Search across all entity session logs for a keyword or topic. Searches summaries and conversation history.",
            category=ToolCategory.MEMORY,
            risk_level=0.0,
            endpoint="/entity/search",
            parameters=[
                ToolParameter("query", "string", "Search term", required=True),
                ToolParameter("entity", "string", "Entity filter (optional)", required=False, default="all"),
                ToolParameter("limit", "integer", "Max results", required=False, default=5),
            ],
        ))

        # ============ CODE TOOLS ============

        self.register(Tool(
            name="code_execute",
            description="Execute Python code in a sandboxed environment. Returns stdout/stderr.",
            category=ToolCategory.CODE,
            risk_level=0.6,
            requires_approval=True,
            parameters=[
                ToolParameter("code", "string", "Python code to execute", required=True),
                ToolParameter("timeout", "integer", "Timeout in seconds", required=False, default=30),
            ],
        ))

        self.register(Tool(
            name="bash_execute",
            description="Execute a bash command. USE WITH EXTREME CAUTION.",
            category=ToolCategory.CODE,
            risk_level=0.8,
            requires_approval=True,
            parameters=[
                ToolParameter("command", "string", "Bash command to execute", required=True),
                ToolParameter("timeout", "integer", "Timeout in seconds", required=False, default=30),
            ],
        ))

        LOG.info(f"Registered {len(self._tools)} built-in tools")


# Global singleton with thread-safe initialization
import threading
_registry: Optional[ToolRegistry] = None
_registry_lock = threading.Lock()


def get_registry() -> ToolRegistry:
    """Get the global tool registry (thread-safe)."""
    global _registry
    if _registry is None:
        with _registry_lock:
            if _registry is None:  # Double-check inside lock
                _registry = ToolRegistry()
    return _registry


# ============ TOOL CALL PARSING ============

# Regex patterns for extracting tool calls from LLM output
TOOL_CALL_PATTERN = re.compile(
    r'```(?:json)?\s*\n?(\{[^`]+\})\s*\n?```',
    re.DOTALL | re.IGNORECASE
)

@dataclass
class ParsedToolCall:
    """Parsed tool call from LLM output."""
    action: str
    action_input: Dict[str, Any]
    raw_json: str
    is_final_answer: bool = False


def _extract_json_object(text: str, start: int) -> Optional[str]:
    """Extract a balanced JSON object starting at position start (must be '{')."""
    if start >= len(text) or text[start] != '{':
        return None
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if escape:
            escape = False
            continue
        if ch == '\\' and in_string:
            escape = True
            continue
        if ch == '"' and not escape:
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                return text[start:i+1]
    return None


def _repair_json(json_str: str) -> str:
    """Repair common Qwen JSON mistakes before parsing."""
    s = json_str
    # Fix bash-style escaped spaces: first\ programming → first programming
    # \<space> is NEVER valid JSON, so safe to replace globally
    s = s.replace('\\ ', ' ')
    # Fix "key"="value" → "key":"value" (Qwen sometimes uses = instead of :)
    s = re.sub(r'"(content|code|command|path|response|query|question|overwrite)"\s*=\s*"', r'"\1":"', s)
    # Fix "key","value" → "key":"value" (comma instead of colon after key)
    s = re.sub(r'"(content|code|command|path|response|query|question|overwrite)"\s*,\s*"', r'"\1":"', s)
    # Remove trailing extra braces (e.g., }}} → }})
    while s.rstrip().endswith('}}}'):
        s = s.rstrip()[:-1]
    # Fix single-quoted string values → double-quoted (Qwen sometimes uses Python-style quotes)
    # Handles nested double quotes: 'print("Hello")' → "print(\"Hello\")"
    def _sq_to_dq(m):
        val = m.group(1)
        val = val.replace('"', '\\"')  # escape inner double quotes
        return f': "{val}"'
    s = re.sub(r""":\s*'((?:[^'\\]|\\.)*)'""", _sq_to_dq, s)
    # Fix truncated JSON: if the string ends mid-value, try to close it
    open_braces = s.count('{') - s.count('}')
    if open_braces > 0:
        # Truncated — try to salvage by closing the string and braces
        in_str = False
        prev = ''
        for ch in s:
            if ch == '"' and prev != '\\':
                in_str = not in_str
            prev = ch
        if in_str:
            s += '"'
        s += '}' * open_braces
    return s


def parse_tool_call(llm_output: str) -> Optional[ParsedToolCall]:
    """
    Extract tool call from LLM output.

    Looks for JSON in format:
    {"action": "tool_name", "action_input": {"param": "value"}}

    Returns None if no valid tool call found.
    """
    # Try code block first
    match = TOOL_CALL_PATTERN.search(llm_output)
    if match:
        json_str = match.group(1).strip()
    else:
        # Find {"action" anywhere in text and extract balanced JSON
        idx = llm_output.find('{"action"')
        if idx == -1:
            idx = llm_output.find('{ "action"')
        if idx >= 0:
            json_str = _extract_json_object(llm_output, idx)
            if not json_str:
                return None
        else:
            return None

    # Try parsing, with repair on failure
    for attempt, s in enumerate([json_str, _repair_json(json_str)]):
        try:
            data = json.loads(s)
            action = data.get("action", "")
            action_input = data.get("action_input", {})

            if not action:
                continue

            if not isinstance(action_input, dict):
                action_input = {}

            # Merge top-level keys (like "overwrite") into action_input
            # Qwen sometimes puts params outside action_input
            for k, v in data.items():
                if k not in ("action", "action_input") and k not in action_input:
                    action_input[k] = v

            # Clean up paths: remove literal backslashes before spaces
            # (Qwen adds bash-style \  escaping inside JSON strings)
            for key in ("path", "src", "dst"):
                if key in action_input and isinstance(action_input[key], str):
                    action_input[key] = action_input[key].replace("\\ ", " ")

            if attempt > 0:
                LOG.info(f"JSON repaired successfully for action: {action}")

            return ParsedToolCall(
                action=action,
                action_input=action_input,
                raw_json=s,
                is_final_answer=(action == "final_answer"),
            )
        except json.JSONDecodeError:
            if attempt == 0:
                continue  # Try repair
            LOG.warning(f"Failed to parse tool call JSON (even after repair): {json_str[:200]}")
            return None
    return None


def validate_tool_call(call: ParsedToolCall, registry: ToolRegistry) -> Optional[str]:
    """
    Validate a parsed tool call against the registry.
    Returns error message if invalid, None if valid.
    """
    if call.is_final_answer:
        return None  # Final answers are always valid

    tool = registry.get(call.action)
    if not tool:
        available = ", ".join(t.name for t in registry.list_all()[:10])
        return f"Unknown tool '{call.action}'. Available: {available}..."

    # Check required parameters
    for param in tool.parameters:
        if param.required and param.name not in call.action_input:
            return f"Missing required parameter '{param.name}' for tool '{call.action}'"

    return None
