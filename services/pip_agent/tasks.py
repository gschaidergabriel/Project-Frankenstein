"""Pip's task execution — lightweight system tasks for Frank."""

from __future__ import annotations

import ast
import json
import logging
import operator
import sqlite3
import time
import urllib.request
from pathlib import Path
from typing import Any, Dict, List

LOG = logging.getLogger("pip_agent.tasks")

# Frank's service ports for health checking
SERVICE_PORTS: Dict[str, int] = {
    "core": 8088, "router": 8091, "modeld": 8090,
    "toolboxd": 8096, "desktopd": 8092, "webd": 8093,
    "ingestd": 8094, "qr": 8097, "aura": 8098,
    "nerd": 8100, "llama": 8101, "whisper": 8103,
    "micro_llm": 8105,
}

AVAILABLE_TASKS: Dict[str, str] = {
    "system_check": "Check health of Frank's services",
    "log_read": "Read recent entries from a log file",
    "memory_search": "Search Frank's reflections and memories",
    "web_search": "Search the web via Frank's web daemon",
    "file_find": "Find files matching a pattern in the codebase",
    "calculate": "Evaluate a mathematical expression safely",
}


def execute_task(task_type: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """Execute a task and return results dict."""
    handler = _HANDLERS.get(task_type)
    if handler is None:
        return {"error": f"Unknown task: {task_type}",
                "available": list(AVAILABLE_TASKS.keys())}
    try:
        return handler(params)
    except Exception as e:
        LOG.warning("Task %s failed: %s", task_type, e)
        return {"error": str(e)}


# ---- task implementations ------------------------------------------

def _task_system_check(params: Dict) -> Dict:
    results: Dict[str, Dict] = {}
    for name, port in SERVICE_PORTS.items():
        try:
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/health", method="GET")
            urllib.request.urlopen(req, timeout=2.0)
            results[name] = {"status": "up", "port": port}
        except Exception:
            results[name] = {"status": "down", "port": port}
    up = sum(1 for v in results.values() if v["status"] == "up")
    return {
        "services": results,
        "summary": f"{up}/{len(results)} services running",
        "down": [k for k, v in results.items() if v["status"] == "down"],
    }


def _task_log_read(params: Dict) -> Dict:
    log_dir = Path.home() / ".local" / "share" / "frank" / "logs"
    log_name = params.get("log", "consciousness")
    n_lines = int(params.get("lines", 20))

    log_file = log_dir / f"{log_name}.log"
    if not log_file.exists():
        available = [f.stem for f in log_dir.glob("*.log")]
        return {"error": f"Log not found: {log_name}",
                "available": available}

    with open(log_file, "r") as f:
        all_lines = f.readlines()
    recent = all_lines[-n_lines:]
    return {"log": log_name,
            "lines": [l.rstrip() for l in recent],
            "total_lines": len(all_lines)}


def _task_memory_search(params: Dict) -> Dict:
    query = params.get("query", "")
    limit = int(params.get("limit", 10))
    db_path = (Path.home() / ".local" / "share" / "frank"
               / "db" / "consciousness.db")
    if not db_path.exists():
        return {"error": "consciousness.db not found"}

    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute(
            "SELECT content, thought_type, ts FROM reflections "
            "WHERE content LIKE ? ORDER BY ts DESC LIMIT ?",
            (f"%{query}%", limit),
        ).fetchall()
    finally:
        conn.close()
    return {
        "results": [{"content": r[0][:300], "type": r[1], "ts": r[2]}
                     for r in rows],
        "count": len(rows),
    }


def _task_web_search(params: Dict) -> Dict:
    query = params.get("query", "")
    if not query:
        return {"error": "No query provided"}
    data = json.dumps({"query": query, "max_results": 5}).encode()
    req = urllib.request.Request(
        "http://127.0.0.1:8093/search",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    resp = urllib.request.urlopen(req, timeout=15.0)
    return json.loads(resp.read())


def _task_file_find(params: Dict) -> Dict:
    pattern = params.get("pattern", "*.py")
    base = Path(params.get("base",
                str(Path.home() / "aicore" / "opt" / "aicore")))
    limit = int(params.get("limit", 20))
    if not base.exists():
        return {"error": f"Path not found: {base}"}
    matches = sorted(base.rglob(pattern))[:limit]
    return {
        "files": [str(m.relative_to(base)) for m in matches],
        "count": len(matches),
        "pattern": pattern,
    }


def _task_calculate(params: Dict) -> Dict:
    expr = params.get("expression", "")
    if not expr:
        return {"error": "No expression provided"}

    _SAFE_OPS = {
        ast.Add: operator.add, ast.Sub: operator.sub,
        ast.Mult: operator.mul, ast.Div: operator.truediv,
        ast.Pow: operator.pow, ast.Mod: operator.mod,
        ast.USub: operator.neg,
    }

    def _eval(node: ast.AST) -> float:
        if isinstance(node, ast.Constant) and isinstance(node.value,
                                                          (int, float)):
            return float(node.value)
        if isinstance(node, ast.BinOp):
            op = _SAFE_OPS.get(type(node.op))
            if op is None:
                raise ValueError(f"Unsupported op: {type(node.op).__name__}")
            return op(_eval(node.left), _eval(node.right))
        if isinstance(node, ast.UnaryOp):
            op = _SAFE_OPS.get(type(node.op))
            if op is None:
                raise ValueError(f"Unsupported op: {type(node.op).__name__}")
            return op(_eval(node.operand))
        raise ValueError(f"Unsupported: {type(node).__name__}")

    tree = ast.parse(expr, mode="eval")
    result = _eval(tree.body)
    return {"expression": expr, "result": result}


_HANDLERS = {
    "system_check": _task_system_check,
    "log_read": _task_log_read,
    "memory_search": _task_memory_search,
    "web_search": _task_web_search,
    "file_find": _task_file_find,
    "calculate": _task_calculate,
}
