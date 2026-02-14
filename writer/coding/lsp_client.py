"""
LSP Client for Frank Writer
Language Server Protocol client for code intelligence features
"""

import asyncio
import json
import logging
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
from enum import Enum

logger = logging.getLogger(__name__)


class LSPMessageType(Enum):
    """LSP message types"""
    REQUEST = "request"
    RESPONSE = "response"
    NOTIFICATION = "notification"


@dataclass
class Position:
    """Position in a text document (0-indexed)"""
    line: int
    character: int

    def to_dict(self) -> Dict:
        return {"line": self.line, "character": self.character}

    @classmethod
    def from_dict(cls, d: Dict) -> 'Position':
        return cls(line=d.get("line", 0), character=d.get("character", 0))


@dataclass
class Range:
    """Range in a text document"""
    start: Position
    end: Position

    def to_dict(self) -> Dict:
        return {"start": self.start.to_dict(), "end": self.end.to_dict()}

    @classmethod
    def from_dict(cls, d: Dict) -> 'Range':
        return cls(
            start=Position.from_dict(d.get("start", {})),
            end=Position.from_dict(d.get("end", {}))
        )


@dataclass
class Location:
    """Location in a document"""
    uri: str
    range: Range

    @classmethod
    def from_dict(cls, d: Dict) -> 'Location':
        return cls(
            uri=d.get("uri", ""),
            range=Range.from_dict(d.get("range", {}))
        )


@dataclass
class Diagnostic:
    """Diagnostic information (error, warning, etc.)"""
    range: Range
    message: str
    severity: int = 1  # 1=Error, 2=Warning, 3=Info, 4=Hint
    source: str = ""
    code: Optional[str] = None

    @classmethod
    def from_dict(cls, d: Dict) -> 'Diagnostic':
        return cls(
            range=Range.from_dict(d.get("range", {})),
            message=d.get("message", ""),
            severity=d.get("severity", 1),
            source=d.get("source", ""),
            code=d.get("code")
        )


@dataclass
class CompletionItem:
    """Completion suggestion"""
    label: str
    kind: int = 1  # 1=Text, 2=Method, 3=Function, 4=Constructor, etc.
    detail: str = ""
    documentation: str = ""
    insert_text: str = ""
    sort_text: str = ""

    @classmethod
    def from_dict(cls, d: Dict) -> 'CompletionItem':
        doc = d.get("documentation", "")
        if isinstance(doc, dict):
            doc = doc.get("value", "")
        return cls(
            label=d.get("label", ""),
            kind=d.get("kind", 1),
            detail=d.get("detail", ""),
            documentation=doc,
            insert_text=d.get("insertText", d.get("label", "")),
            sort_text=d.get("sortText", "")
        )


@dataclass
class LSPServerConfig:
    """Configuration for an LSP server"""
    name: str
    command: List[str]
    languages: List[str]
    initialization_options: Dict = field(default_factory=dict)
    root_patterns: List[str] = field(default_factory=list)


# Built-in LSP server configurations
LSP_SERVERS: Dict[str, LSPServerConfig] = {
    "python": LSPServerConfig(
        name="python-lsp-server",
        command=["pylsp"],
        languages=["python"],
        initialization_options={
            "pylsp": {
                "plugins": {
                    "pycodestyle": {"enabled": True},
                    "pyflakes": {"enabled": True},
                    "pylint": {"enabled": False},
                    "rope_completion": {"enabled": True},
                }
            }
        },
        root_patterns=["pyproject.toml", "setup.py", "requirements.txt", ".git"]
    ),
    "typescript": LSPServerConfig(
        name="typescript-language-server",
        command=["typescript-language-server", "--stdio"],
        languages=["typescript", "javascript", "typescriptreact", "javascriptreact"],
        initialization_options={},
        root_patterns=["package.json", "tsconfig.json", "jsconfig.json", ".git"]
    ),
    "rust": LSPServerConfig(
        name="rust-analyzer",
        command=["rust-analyzer"],
        languages=["rust"],
        initialization_options={
            "cargo": {"allFeatures": True},
            "checkOnSave": {"command": "clippy"}
        },
        root_patterns=["Cargo.toml", ".git"]
    ),
    "go": LSPServerConfig(
        name="gopls",
        command=["gopls", "serve"],
        languages=["go"],
        initialization_options={},
        root_patterns=["go.mod", "go.sum", ".git"]
    ),
}


class LSPClient:
    """
    Language Server Protocol client.

    Manages communication with LSP servers for features like:
    - Code completion
    - Go to definition
    - Find references
    - Diagnostics (errors/warnings)
    - Hover information
    """

    # Protocol constants
    CONTENT_LENGTH_HEADER = "Content-Length: "
    HEADER_SEPARATOR = "\r\n\r\n"

    def __init__(self, workspace_root: Optional[Path] = None):
        """
        Initialize the LSP client.

        Args:
            workspace_root: Root path of the workspace/project
        """
        self._workspace_root = workspace_root or Path.cwd()
        self._process: Optional[asyncio.subprocess.Process] = None
        self._reader_task: Optional[asyncio.Task] = None
        self._current_language: Optional[str] = None
        self._current_config: Optional[LSPServerConfig] = None

        # Message handling
        self._request_id = 0
        self._pending_requests: Dict[int, asyncio.Future] = {}
        self._notification_handlers: Dict[str, List[Callable]] = {}

        # Server state
        self._initialized = False
        self._server_capabilities: Dict = {}
        self._open_documents: Dict[str, int] = {}  # uri -> version

        # Diagnostics storage
        self._diagnostics: Dict[str, List[Diagnostic]] = {}

    @property
    def is_running(self) -> bool:
        """Check if server is running"""
        return self._process is not None and self._process.returncode is None

    @property
    def is_initialized(self) -> bool:
        """Check if server is initialized"""
        return self._initialized

    def get_supported_languages(self) -> List[str]:
        """Get list of supported languages"""
        languages = set()
        for config in LSP_SERVERS.values():
            languages.update(config.languages)
        return sorted(languages)

    async def start_server(self, language: str) -> bool:
        """
        Start LSP server for a language.

        Args:
            language: Programming language (e.g., 'python', 'typescript')

        Returns:
            True if server started successfully
        """
        # Check if already running for this language
        if self.is_running and self._current_language == language:
            return True

        # Stop any existing server
        await self.stop_server()

        # Find server config
        config = self._find_server_config(language)
        if not config:
            logger.error(f"No LSP server configured for language: {language}")
            return False

        # Verify server executable exists
        executable = config.command[0]
        resolved = shutil.which(executable)
        if not resolved:
            logger.error(f"LSP server not found: {executable}")
            return False

        self._current_language = language
        self._current_config = config

        # Start server process
        try:
            cmd = config.command.copy()
            cmd[0] = resolved  # Use resolved path

            self._process = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self._workspace_root)
            )

            logger.info(f"Started LSP server: {config.name} (PID: {self._process.pid})")

            # Start message reader
            self._reader_task = asyncio.create_task(self._read_messages())

            # Initialize server
            success = await self._initialize()
            if not success:
                await self.stop_server()
                return False

            return True

        except Exception as e:
            logger.error(f"Failed to start LSP server: {e}")
            await self.stop_server()
            return False

    async def stop_server(self):
        """Stop the LSP server"""
        if not self._process:
            return

        try:
            # Send shutdown request
            if self._initialized:
                try:
                    await asyncio.wait_for(
                        self._request("shutdown", {}),
                        timeout=5.0
                    )
                    await self._notify("exit", {})
                except asyncio.TimeoutError:
                    logger.warning("Shutdown request timed out")

            # Cancel reader task
            if self._reader_task:
                self._reader_task.cancel()
                try:
                    await self._reader_task
                except asyncio.CancelledError:
                    pass

            # Terminate process
            if self._process.returncode is None:
                self._process.terminate()
                try:
                    await asyncio.wait_for(self._process.wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    self._process.kill()
                    await self._process.wait()

            logger.info("LSP server stopped")

        except Exception as e:
            logger.error(f"Error stopping LSP server: {e}")

        finally:
            self._process = None
            self._reader_task = None
            self._initialized = False
            self._pending_requests.clear()
            self._open_documents.clear()
            self._current_language = None

    async def get_completions(self, uri: str, position: Position) -> List[CompletionItem]:
        """
        Get completion suggestions at a position.

        Args:
            uri: Document URI (file:// format)
            position: Cursor position

        Returns:
            List of completion items
        """
        if not self._initialized:
            return []

        try:
            result = await asyncio.wait_for(
                self._request("textDocument/completion", {
                    "textDocument": {"uri": uri},
                    "position": position.to_dict()
                }),
                timeout=5.0
            )

            if result is None:
                return []

            # Handle CompletionList or array of CompletionItem
            items = result.get("items", result) if isinstance(result, dict) else result
            if not isinstance(items, list):
                return []

            return [CompletionItem.from_dict(item) for item in items]

        except asyncio.TimeoutError:
            logger.warning("Completion request timed out")
            return []
        except Exception as e:
            logger.error(f"Completion request failed: {e}")
            return []

    async def get_diagnostics(self, uri: str = None) -> Dict[str, List[Diagnostic]]:
        """
        Get diagnostics (errors/warnings).

        Args:
            uri: Optional specific document URI

        Returns:
            Dict mapping URIs to lists of diagnostics
        """
        if uri:
            return {uri: self._diagnostics.get(uri, [])}
        return self._diagnostics.copy()

    async def goto_definition(self, uri: str, position: Position) -> Optional[Location]:
        """
        Go to definition of symbol at position.

        Args:
            uri: Document URI
            position: Cursor position

        Returns:
            Location of definition, or None
        """
        if not self._initialized:
            return None

        try:
            result = await asyncio.wait_for(
                self._request("textDocument/definition", {
                    "textDocument": {"uri": uri},
                    "position": position.to_dict()
                }),
                timeout=5.0
            )

            if not result:
                return None

            # Handle array or single location
            if isinstance(result, list) and len(result) > 0:
                return Location.from_dict(result[0])
            elif isinstance(result, dict):
                return Location.from_dict(result)

            return None

        except asyncio.TimeoutError:
            logger.warning("Definition request timed out")
            return None
        except Exception as e:
            logger.error(f"Definition request failed: {e}")
            return None

    async def find_references(self, uri: str, position: Position,
                            include_declaration: bool = True) -> List[Location]:
        """
        Find all references to symbol at position.

        Args:
            uri: Document URI
            position: Cursor position
            include_declaration: Include the declaration in results

        Returns:
            List of locations
        """
        if not self._initialized:
            return []

        try:
            result = await asyncio.wait_for(
                self._request("textDocument/references", {
                    "textDocument": {"uri": uri},
                    "position": position.to_dict(),
                    "context": {"includeDeclaration": include_declaration}
                }),
                timeout=10.0
            )

            if not result or not isinstance(result, list):
                return []

            return [Location.from_dict(loc) for loc in result]

        except asyncio.TimeoutError:
            logger.warning("References request timed out")
            return []
        except Exception as e:
            logger.error(f"References request failed: {e}")
            return []

    async def get_hover(self, uri: str, position: Position) -> Optional[str]:
        """
        Get hover information at position.

        Args:
            uri: Document URI
            position: Cursor position

        Returns:
            Hover content as markdown string, or None
        """
        if not self._initialized:
            return None

        try:
            result = await asyncio.wait_for(
                self._request("textDocument/hover", {
                    "textDocument": {"uri": uri},
                    "position": position.to_dict()
                }),
                timeout=5.0
            )

            if not result:
                return None

            contents = result.get("contents", "")

            # Handle MarkupContent
            if isinstance(contents, dict):
                return contents.get("value", "")

            # Handle MarkedString array
            if isinstance(contents, list):
                parts = []
                for item in contents:
                    if isinstance(item, str):
                        parts.append(item)
                    elif isinstance(item, dict):
                        lang = item.get("language", "")
                        value = item.get("value", "")
                        if lang:
                            parts.append(f"```{lang}\n{value}\n```")
                        else:
                            parts.append(value)
                return "\n\n".join(parts)

            return str(contents) if contents else None

        except asyncio.TimeoutError:
            logger.warning("Hover request timed out")
            return None
        except Exception as e:
            logger.error(f"Hover request failed: {e}")
            return None

    async def format_document(self, uri: str) -> List[Dict]:
        """
        Format entire document.

        Args:
            uri: Document URI

        Returns:
            List of text edits
        """
        if not self._initialized:
            return []

        try:
            result = await asyncio.wait_for(
                self._request("textDocument/formatting", {
                    "textDocument": {"uri": uri},
                    "options": {
                        "tabSize": 4,
                        "insertSpaces": True,
                        "trimTrailingWhitespace": True,
                        "insertFinalNewline": True
                    }
                }),
                timeout=10.0
            )

            return result if isinstance(result, list) else []

        except asyncio.TimeoutError:
            logger.warning("Format request timed out")
            return []
        except Exception as e:
            logger.error(f"Format request failed: {e}")
            return []

    # Document synchronization

    async def open_document(self, uri: str, language_id: str, content: str):
        """Notify server that a document was opened"""
        if not self._initialized:
            return

        version = 1
        self._open_documents[uri] = version

        await self._notify("textDocument/didOpen", {
            "textDocument": {
                "uri": uri,
                "languageId": language_id,
                "version": version,
                "text": content
            }
        })

    async def change_document(self, uri: str, content: str):
        """Notify server of document changes"""
        if not self._initialized or uri not in self._open_documents:
            return

        version = self._open_documents[uri] + 1
        self._open_documents[uri] = version

        await self._notify("textDocument/didChange", {
            "textDocument": {"uri": uri, "version": version},
            "contentChanges": [{"text": content}]
        })

    async def close_document(self, uri: str):
        """Notify server that a document was closed"""
        if not self._initialized or uri not in self._open_documents:
            return

        del self._open_documents[uri]

        await self._notify("textDocument/didClose", {
            "textDocument": {"uri": uri}
        })

    # Notification handlers

    def on_diagnostics(self, callback: Callable[[str, List[Diagnostic]], None]):
        """Register handler for diagnostic notifications"""
        handlers = self._notification_handlers.setdefault("textDocument/publishDiagnostics", [])
        handlers.append(callback)

    def on_log_message(self, callback: Callable[[int, str], None]):
        """Register handler for log messages from server"""
        handlers = self._notification_handlers.setdefault("window/logMessage", [])
        handlers.append(callback)

    # Internal methods

    def _find_server_config(self, language: str) -> Optional[LSPServerConfig]:
        """Find server configuration for a language"""
        # Direct match
        if language in LSP_SERVERS:
            return LSP_SERVERS[language]

        # Check languages list
        for config in LSP_SERVERS.values():
            if language in config.languages:
                return config

        return None

    async def _initialize(self) -> bool:
        """Initialize the LSP server"""
        try:
            result = await asyncio.wait_for(
                self._request("initialize", {
                    "processId": os.getpid(),
                    "rootUri": self._workspace_root.as_uri(),
                    "rootPath": str(self._workspace_root),
                    "capabilities": {
                        "textDocument": {
                            "completion": {
                                "completionItem": {
                                    "snippetSupport": True,
                                    "documentationFormat": ["markdown", "plaintext"]
                                }
                            },
                            "hover": {
                                "contentFormat": ["markdown", "plaintext"]
                            },
                            "definition": {"dynamicRegistration": False},
                            "references": {"dynamicRegistration": False},
                            "formatting": {"dynamicRegistration": False},
                            "publishDiagnostics": {
                                "relatedInformation": True
                            }
                        },
                        "workspace": {
                            "workspaceFolders": True
                        }
                    },
                    "initializationOptions": self._current_config.initialization_options if self._current_config else {},
                    "workspaceFolders": [{
                        "uri": self._workspace_root.as_uri(),
                        "name": self._workspace_root.name
                    }]
                }),
                timeout=30.0
            )

            if result:
                self._server_capabilities = result.get("capabilities", {})
                self._initialized = True

                # Send initialized notification
                await self._notify("initialized", {})

                logger.info(f"LSP server initialized with capabilities: {list(self._server_capabilities.keys())}")
                return True

            return False

        except asyncio.TimeoutError:
            logger.error("LSP initialization timed out")
            return False
        except Exception as e:
            logger.error(f"LSP initialization failed: {e}")
            return False

    async def _request(self, method: str, params: Dict) -> Optional[Dict]:
        """Send a request and wait for response"""
        if not self._process or not self._process.stdin:
            return None

        self._request_id += 1
        request_id = self._request_id

        message = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params
        }

        future: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending_requests[request_id] = future

        await self._send_message(message)

        try:
            return await future
        finally:
            self._pending_requests.pop(request_id, None)

    async def _notify(self, method: str, params: Dict):
        """Send a notification (no response expected)"""
        if not self._process or not self._process.stdin:
            return

        message = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params
        }

        await self._send_message(message)

    async def _send_message(self, message: Dict):
        """Send a message to the server"""
        if not self._process or not self._process.stdin:
            return

        try:
            content = json.dumps(message)
            header = f"{self.CONTENT_LENGTH_HEADER}{len(content.encode('utf-8'))}{self.HEADER_SEPARATOR}"
            data = header.encode('utf-8') + content.encode('utf-8')

            self._process.stdin.write(data)
            await self._process.stdin.drain()

            logger.debug(f"Sent: {message.get('method', 'response')}")

        except Exception as e:
            logger.error(f"Failed to send message: {e}")

    async def _read_messages(self):
        """Read messages from server stdout"""
        if not self._process or not self._process.stdout:
            return

        try:
            while self._process.returncode is None:
                # Read headers
                headers = {}
                while True:
                    line = await self._process.stdout.readline()
                    if not line:
                        return

                    line = line.decode('utf-8').strip()
                    if not line:
                        break

                    if ':' in line:
                        key, value = line.split(':', 1)
                        headers[key.strip().lower()] = value.strip()

                # Get content length
                content_length = int(headers.get('content-length', 0))
                if content_length == 0:
                    continue

                # Read content
                content = await self._process.stdout.read(content_length)
                if not content:
                    return

                try:
                    message = json.loads(content.decode('utf-8'))
                    await self._handle_message(message)
                except json.JSONDecodeError as e:
                    logger.error(f"Failed to parse message: {e}")

        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"Error reading messages: {e}")

    async def _handle_message(self, message: Dict):
        """Handle incoming message from server"""
        # Response to a request
        if 'id' in message and 'method' not in message:
            request_id = message['id']
            if request_id in self._pending_requests:
                future = self._pending_requests[request_id]
                if 'error' in message:
                    error = message['error']
                    logger.error(f"LSP error: {error.get('message', 'Unknown error')}")
                    future.set_result(None)
                else:
                    future.set_result(message.get('result'))
            return

        # Notification from server
        method = message.get('method', '')
        params = message.get('params', {})

        logger.debug(f"Received notification: {method}")

        # Handle diagnostics
        if method == "textDocument/publishDiagnostics":
            uri = params.get("uri", "")
            diagnostics = [Diagnostic.from_dict(d) for d in params.get("diagnostics", [])]
            self._diagnostics[uri] = diagnostics

            # Call registered handlers
            for handler in self._notification_handlers.get(method, []):
                try:
                    handler(uri, diagnostics)
                except Exception as e:
                    logger.error(f"Diagnostic handler error: {e}")

        # Handle log messages
        elif method == "window/logMessage":
            msg_type = params.get("type", 4)
            msg = params.get("message", "")
            log_level = {1: logging.ERROR, 2: logging.WARNING, 3: logging.INFO, 4: logging.DEBUG}.get(msg_type, logging.DEBUG)
            logger.log(log_level, f"LSP: {msg}")

            for handler in self._notification_handlers.get(method, []):
                try:
                    handler(msg_type, msg)
                except Exception as e:
                    logger.error(f"Log message handler error: {e}")

        # Handle other notifications
        elif method in self._notification_handlers:
            for handler in self._notification_handlers[method]:
                try:
                    handler(params)
                except Exception as e:
                    logger.error(f"Notification handler error for {method}: {e}")


# Utility functions

def uri_to_path(uri: str) -> Path:
    """Convert file:// URI to Path"""
    if uri.startswith("file://"):
        path = uri[7:]
        # Handle Windows paths
        if path.startswith("/") and len(path) > 2 and path[2] == ':':
            path = path[1:]
        return Path(path)
    return Path(uri)


def path_to_uri(path: Path) -> str:
    """Convert Path to file:// URI"""
    return path.resolve().as_uri()
