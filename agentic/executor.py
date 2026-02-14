"""
Tool Executor - Safe execution of tools with E-SIR integration.

Handles:
- Tool invocation via HTTP or direct function call
- Risk assessment and approval flow
- Result capture and error handling
- Timeout management
"""

from __future__ import annotations

import json
import subprocess
import tempfile
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Optional
import logging

from .tools import Tool, ToolResult, ToolRegistry, get_registry

LOG = logging.getLogger("agentic.executor")

# Toolbox base URL
TOOLBOX_URL = "http://127.0.0.1:8096"

# Approval queue file for integration with overlay
APPROVAL_QUEUE_FILE = Path("/tmp/frank_approval_queue.json")
APPROVAL_RESPONSE_FILE = Path("/tmp/frank_approval_responses.json")


@dataclass
class ExecutionConfig:
    """Configuration for tool execution."""
    timeout_s: float = 30.0
    require_approval_above_risk: float = 0.6
    auto_approve_below_risk: float = 0.3
    sandbox_code_execution: bool = True
    max_retries: int = 2
    retry_delay_s: float = 1.0


class ToolExecutor:
    """
    Executes tools with safety checks and result capture.
    """

    def __init__(
        self,
        registry: Optional[ToolRegistry] = None,
        config: Optional[ExecutionConfig] = None,
    ):
        self.registry = registry or get_registry()
        self.config = config or ExecutionConfig()
        self._pending_approvals: Dict[str, Dict[str, Any]] = {}

    def execute(
        self,
        tool_name: str,
        tool_input: Dict[str, Any],
        skip_approval: bool = False,
    ) -> ToolResult:
        """
        Execute a tool and return the result.

        Args:
            tool_name: Name of the tool to execute
            tool_input: Parameters for the tool
            skip_approval: Skip approval even for high-risk tools

        Returns:
            ToolResult with success/failure and data
        """
        start_time = time.time()

        # Get tool definition
        tool = self.registry.get(tool_name)
        if not tool:
            return ToolResult(
                tool_name=tool_name,
                success=False,
                data={},
                error=f"Unknown tool: {tool_name}",
                execution_time_ms=(time.time() - start_time) * 1000,
            )

        # Check if approval needed
        if not skip_approval and self._needs_approval(tool):
            return ToolResult(
                tool_name=tool_name,
                success=False,
                data={"approval_required": True, "risk_level": tool.risk_level},
                error="Approval required for this action",
                execution_time_ms=(time.time() - start_time) * 1000,
            )

        # Execute with retry logic
        last_error = None
        for attempt in range(self.config.max_retries + 1):
            try:
                result = self._execute_tool(tool, tool_input)
                result.execution_time_ms = (time.time() - start_time) * 1000
                return result
            except Exception as e:
                last_error = str(e)
                LOG.warning(f"Tool {tool_name} attempt {attempt + 1} failed: {e}")
                if attempt < self.config.max_retries:
                    time.sleep(self.config.retry_delay_s)

        return ToolResult(
            tool_name=tool_name,
            success=False,
            data={},
            error=f"Failed after {self.config.max_retries + 1} attempts: {last_error}",
            execution_time_ms=(time.time() - start_time) * 1000,
        )

    def _needs_approval(self, tool: Tool) -> bool:
        """Check if tool needs user approval."""
        if tool.requires_approval:
            return True
        if tool.risk_level >= self.config.require_approval_above_risk:
            return True
        return False

    def _execute_tool(self, tool: Tool, tool_input: Dict[str, Any]) -> ToolResult:
        """Execute a single tool."""
        LOG.info(f"Executing tool: {tool.name} with input: {tool_input}")

        # Auto-fix: fs_write should always overwrite in agentic mode
        if tool.name == "fs_write" and not tool_input.get("overwrite"):
            tool_input["overwrite"] = True

        # Auto-fix: Remove backslashes before spaces in paths (Qwen habit)
        for key in ("path", "src", "dst", "command"):
            if key in tool_input and isinstance(tool_input[key], str):
                tool_input[key] = tool_input[key].replace("\\ ", " ")

        # Auto-fix: Qwen writes \\n instead of \n in JSON content strings
        # After json.loads, \\n becomes literal two-char "\n" instead of newline
        if tool.name == "fs_write" and "content" in tool_input:
            content = tool_input["content"]
            if isinstance(content, str) and "\\n" in content:
                content = content.replace("\\n", "\n")
                content = content.replace("\\t", "\t")
                tool_input["content"] = content
                LOG.info("Auto-fixed literal \\n/\\t in fs_write content")

        # Special handling for code execution
        if tool.name == "code_execute":
            return self._execute_code(tool_input)
        if tool.name == "bash_execute":
            return self._execute_bash(tool_input)

        # Handler function takes priority
        if tool.handler:
            try:
                result = tool.handler(**tool_input)
                if not isinstance(result, dict):
                    result = {"ok": bool(result), "result": result}
                return ToolResult(
                    tool_name=tool.name,
                    success=result.get("ok", True),
                    data=result,
                    error=result.get("error"),
                )
            except Exception as e:
                return ToolResult(
                    tool_name=tool.name,
                    success=False,
                    data={},
                    error=str(e),
                )

        # HTTP endpoint
        if tool.endpoint:
            return self._execute_http(tool, tool_input)

        return ToolResult(
            tool_name=tool.name,
            success=False,
            data={},
            error="Tool has no handler or endpoint",
        )

    def _execute_http(self, tool: Tool, tool_input: Dict[str, Any]) -> ToolResult:
        """Execute tool via HTTP endpoint."""
        # Determine URL
        if tool.endpoint.startswith("http"):
            url = tool.endpoint
        else:
            url = f"{TOOLBOX_URL}{tool.endpoint}"

        # POST with JSON body
        data = json.dumps(tool_input).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=self.config.timeout_s) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                return ToolResult(
                    tool_name=tool.name,
                    success=result.get("ok", True),
                    data=result,
                    error=result.get("error"),
                )
        except urllib.error.URLError as e:
            return ToolResult(
                tool_name=tool.name,
                success=False,
                data={},
                error=f"HTTP error: {e}",
            )
        except json.JSONDecodeError as e:
            return ToolResult(
                tool_name=tool.name,
                success=False,
                data={},
                error=f"Invalid JSON response: {e}",
            )

    def _execute_code(self, tool_input: Dict[str, Any]) -> ToolResult:
        """Execute Python code in sandbox."""
        code = tool_input.get("code", "")
        timeout = tool_input.get("timeout", 30)

        if not code.strip():
            return ToolResult(
                tool_name="code_execute",
                success=False,
                data={},
                error="No code provided",
            )

        # Write to temp file
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False
        ) as f:
            f.write(code)
            code_file = f.name

        try:
            # Execute in subprocess with limited resources
            result = subprocess.run(
                ["python3", code_file],
                capture_output=True,
                text=True,
                timeout=timeout,
                env={
                    "PATH": "/usr/bin:/bin",
                    "HOME": "/tmp",
                    "PYTHONDONTWRITEBYTECODE": "1",
                },
            )

            return ToolResult(
                tool_name="code_execute",
                success=(result.returncode == 0),
                data={
                    "stdout": result.stdout[:5000] if result.stdout else "",
                    "stderr": result.stderr[:2000] if result.stderr else "",
                    "returncode": result.returncode,
                },
                error=result.stderr[:500] if result.returncode != 0 else None,
            )
        except subprocess.TimeoutExpired:
            return ToolResult(
                tool_name="code_execute",
                success=False,
                data={},
                error=f"Code execution timed out after {timeout}s",
            )
        except Exception as e:
            return ToolResult(
                tool_name="code_execute",
                success=False,
                data={},
                error=str(e),
            )
        finally:
            Path(code_file).unlink(missing_ok=True)

    def _execute_bash(self, tool_input: Dict[str, Any]) -> ToolResult:
        """Execute bash command with safety checks."""
        command = tool_input.get("command", "")
        timeout = tool_input.get("timeout", 30)

        if not command.strip():
            return ToolResult(
                tool_name="bash_execute",
                success=False,
                data={},
                error="No command provided",
            )

        # Safety checks - block dangerous commands using regex for better matching
        import re
        dangerous_patterns = [
            (r"rm\s+(-[rf]+\s+)*[/]($|\s|;)", "rm with root path"),
            (r"rm\s+(-[rf]+\s+)+\*", "rm -rf with wildcard"),
            (r"mkfs", "mkfs filesystem format"),
            (r"dd\s+if=", "dd disk write"),
            (r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;", "fork bomb"),
            (r"chmod\s+(-R\s+)?777\s+/", "chmod 777 on root"),
            (r">\s*/dev/sd[a-z]", "write to disk device"),
            (r"(curl|wget)[^|]*\|\s*(ba)?sh", "pipe download to shell"),
            (r"shred\s+.*\s+/", "shred on root"),
            (r"fdisk\s+/dev/", "fdisk partition edit"),
            (r"eval\s+.*\$", "eval with variable expansion"),
        ]

        for pattern, desc in dangerous_patterns:
            if re.search(pattern, command, re.IGNORECASE):
                return ToolResult(
                    tool_name="bash_execute",
                    success=False,
                    data={},
                    error=f"Blocked dangerous command: {desc}",
                )

        try:
            result = subprocess.run(
                ["bash", "-c", command],
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=str(Path.home()),
            )

            return ToolResult(
                tool_name="bash_execute",
                success=(result.returncode == 0),
                data={
                    "stdout": result.stdout[:5000] if result.stdout else "",
                    "stderr": result.stderr[:2000] if result.stderr else "",
                    "returncode": result.returncode,
                },
                error=result.stderr[:500] if result.returncode != 0 else None,
            )
        except subprocess.TimeoutExpired:
            return ToolResult(
                tool_name="bash_execute",
                success=False,
                data={},
                error=f"Command timed out after {timeout}s",
            )
        except Exception as e:
            return ToolResult(
                tool_name="bash_execute",
                success=False,
                data={},
                error=str(e),
            )

    # ============ Approval Flow ============

    def request_approval(
        self,
        tool: Tool,
        tool_input: Dict[str, Any],
        reason: str = "",
    ) -> str:
        """
        Request user approval for a tool execution.

        Returns approval_id for tracking.
        """
        import uuid

        approval_id = str(uuid.uuid4())[:8]

        request = {
            "id": approval_id,
            "tool_name": tool.name,
            "tool_input": tool_input,
            "risk_level": tool.risk_level,
            "reason": reason or f"Executing {tool.name} requires approval",
            "timestamp": time.time(),
        }

        self._pending_approvals[approval_id] = request

        # Write to approval queue file for overlay
        self._write_approval_request(request)

        LOG.info(f"Approval requested: {approval_id} for {tool.name}")
        return approval_id

    def check_approval(self, approval_id: str) -> Optional[bool]:
        """
        Check if an approval has been granted.

        Returns:
            True if approved, False if rejected, None if pending
        """
        responses = self._read_approval_responses()
        if approval_id in responses:
            return responses[approval_id].get("approved", False)
        return None

    def wait_for_approval(
        self,
        approval_id: str,
        timeout_s: float = 120.0,
        poll_interval_s: float = 1.0,
    ) -> bool:
        """
        Wait for approval with timeout.

        Returns True if approved, False if rejected or timeout.
        """
        start = time.time()
        while (time.time() - start) < timeout_s:
            result = self.check_approval(approval_id)
            if result is not None:
                return result
            time.sleep(poll_interval_s)
        return False

    def _write_approval_request(self, request: Dict[str, Any]) -> None:
        """Write approval request to queue file with file locking."""
        import fcntl
        try:
            # Use file locking to prevent race conditions
            APPROVAL_QUEUE_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(APPROVAL_QUEUE_FILE, "a+") as f:
                fcntl.flock(f.fileno(), fcntl.LOCK_EX)
                try:
                    f.seek(0)
                    content = f.read()
                    queue = json.loads(content) if content.strip() else []

                    # Add new request
                    queue.append(request)

                    # Write back
                    f.seek(0)
                    f.truncate()
                    json.dump(queue, f)
                finally:
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)

        except Exception as e:
            LOG.error(f"Failed to write approval request: {e}")

    def _read_approval_responses(self) -> Dict[str, Dict[str, Any]]:
        """Read approval responses from file with file locking."""
        import fcntl
        try:
            if APPROVAL_RESPONSE_FILE.exists():
                with open(APPROVAL_RESPONSE_FILE, "r") as f:
                    fcntl.flock(f.fileno(), fcntl.LOCK_SH)
                    try:
                        responses = json.load(f)
                        return {r["id"]: r for r in responses if "id" in r}
                    finally:
                        fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        except Exception as e:
            LOG.error(f"Failed to read approval responses: {e}")
        return {}


# Convenience function for simple tool execution
def execute_tool(
    tool_name: str,
    tool_input: Dict[str, Any],
    skip_approval: bool = False,
) -> ToolResult:
    """Execute a tool with default configuration."""
    executor = ToolExecutor()
    return executor.execute(tool_name, tool_input, skip_approval)
