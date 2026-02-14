"""
Project Manager for Frank Writer
Multi-file project management and detection
"""

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Callable
from enum import Enum
import fnmatch

try:
    import tomli
    HAS_TOMLI = True
except ImportError:
    HAS_TOMLI = False

try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False

logger = logging.getLogger(__name__)


class ProjectType(Enum):
    """Types of detected projects"""
    UNKNOWN = "unknown"
    PYTHON_PACKAGE = "python_package"
    PYTHON_PROJECT = "python_project"
    NODE_PROJECT = "node_project"
    RUST_PROJECT = "rust_project"
    GO_PROJECT = "go_project"
    JAVA_PROJECT = "java_project"
    MIXED = "mixed"


@dataclass
class ProjectDependency:
    """Represents a project dependency"""
    name: str
    version: str = ""
    dev: bool = False
    optional: bool = False

    def __str__(self) -> str:
        if self.version:
            return f"{self.name}=={self.version}"
        return self.name


@dataclass
class ProjectMetadata:
    """Project metadata extracted from config files"""
    name: str = ""
    version: str = ""
    description: str = ""
    authors: List[str] = field(default_factory=list)
    license: str = ""
    homepage: str = ""
    repository: str = ""
    keywords: List[str] = field(default_factory=list)
    python_version: str = ""
    node_version: str = ""


@dataclass
class ProjectFile:
    """Represents a file in the project"""
    path: Path
    relative_path: str
    language: str = ""
    size: int = 0
    modified_time: float = 0

    @property
    def name(self) -> str:
        return self.path.name

    @property
    def extension(self) -> str:
        return self.path.suffix.lower()


# File patterns for project detection
PROJECT_INDICATORS: Dict[ProjectType, List[str]] = {
    ProjectType.PYTHON_PACKAGE: ["pyproject.toml", "setup.py", "setup.cfg"],
    ProjectType.PYTHON_PROJECT: ["requirements.txt", "Pipfile", "environment.yml"],
    ProjectType.NODE_PROJECT: ["package.json"],
    ProjectType.RUST_PROJECT: ["Cargo.toml"],
    ProjectType.GO_PROJECT: ["go.mod"],
    ProjectType.JAVA_PROJECT: ["pom.xml", "build.gradle", "build.gradle.kts"],
}

# Default ignore patterns
DEFAULT_IGNORE_PATTERNS = [
    ".git",
    ".svn",
    ".hg",
    "__pycache__",
    "*.pyc",
    "node_modules",
    ".venv",
    "venv",
    "env",
    ".env",
    "target",
    "build",
    "dist",
    "*.egg-info",
    ".idea",
    ".vscode",
    "*.so",
    "*.dll",
    "*.dylib",
    ".DS_Store",
    "Thumbs.db",
]

# Language detection by extension
EXTENSION_TO_LANGUAGE: Dict[str, str] = {
    ".py": "python",
    ".pyi": "python",
    ".pyw": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".rs": "rust",
    ".go": "go",
    ".java": "java",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".hpp": "cpp",
    ".cc": "cpp",
    ".cxx": "cpp",
    ".rb": "ruby",
    ".php": "php",
    ".swift": "swift",
    ".scala": "scala",
    ".clj": "clojure",
    ".ex": "elixir",
    ".exs": "elixir",
    ".erl": "erlang",
    ".hs": "haskell",
    ".ml": "ocaml",
    ".fs": "fsharp",
    ".lua": "lua",
    ".sh": "bash",
    ".bash": "bash",
    ".zsh": "zsh",
    ".fish": "fish",
    ".ps1": "powershell",
    ".sql": "sql",
    ".html": "html",
    ".htm": "html",
    ".css": "css",
    ".scss": "scss",
    ".sass": "sass",
    ".less": "less",
    ".json": "json",
    ".xml": "xml",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".md": "markdown",
    ".rst": "rst",
    ".tex": "latex",
}


class Project:
    """
    Manages a code project.

    Features:
    - Project type detection
    - File listing and filtering
    - Dependency parsing
    - Metadata extraction
    """

    def __init__(self, root_path: Optional[Path] = None):
        """
        Initialize a Project.

        Args:
            root_path: Root directory of the project
        """
        self._root: Optional[Path] = None
        self._project_type: ProjectType = ProjectType.UNKNOWN
        self._metadata: ProjectMetadata = ProjectMetadata()
        self._dependencies: List[ProjectDependency] = []
        self._files: Dict[str, ProjectFile] = {}  # relative path -> ProjectFile
        self._ignore_patterns: List[str] = DEFAULT_IGNORE_PATTERNS.copy()
        self._change_callbacks: List[Callable] = []

        if root_path:
            self.open_project(root_path)

    @property
    def root(self) -> Optional[Path]:
        """Get project root path"""
        return self._root

    @property
    def name(self) -> str:
        """Get project name"""
        return self._metadata.name or (self._root.name if self._root else "")

    @property
    def project_type(self) -> ProjectType:
        """Get detected project type"""
        return self._project_type

    @property
    def metadata(self) -> ProjectMetadata:
        """Get project metadata"""
        return self._metadata

    @property
    def dependencies(self) -> List[ProjectDependency]:
        """Get project dependencies"""
        return self._dependencies.copy()

    def open_project(self, path: Path) -> bool:
        """
        Open a project from a directory.

        Args:
            path: Path to project directory

        Returns:
            True if project was opened successfully
        """
        path = Path(path).resolve()

        if not path.is_dir():
            logger.error(f"Project path is not a directory: {path}")
            return False

        self._root = path
        self._files.clear()
        self._dependencies.clear()
        self._metadata = ProjectMetadata()

        # Detect project type
        self._project_type = self._detect_project_type()
        logger.info(f"Detected project type: {self._project_type.value}")

        # Load project configuration
        self._load_project_config()

        # Load gitignore patterns
        self._load_gitignore()

        # Scan files
        self._scan_files()

        # Notify callbacks
        self._notify_change("project_opened", {"path": str(path)})

        return True

    def close_project(self):
        """Close the current project"""
        if self._root:
            self._notify_change("project_closed", {"path": str(self._root)})

        self._root = None
        self._project_type = ProjectType.UNKNOWN
        self._metadata = ProjectMetadata()
        self._dependencies.clear()
        self._files.clear()

    def get_files(self, language: str = None, pattern: str = None) -> List[ProjectFile]:
        """
        Get list of project files.

        Args:
            language: Filter by language (e.g., 'python')
            pattern: Glob pattern to filter (e.g., '*.py')

        Returns:
            List of ProjectFile objects
        """
        files = list(self._files.values())

        if language:
            files = [f for f in files if f.language == language]

        if pattern:
            files = [f for f in files if fnmatch.fnmatch(f.name, pattern)]

        return sorted(files, key=lambda f: f.relative_path)

    def get_file(self, relative_path: str) -> Optional[ProjectFile]:
        """Get a specific file by relative path"""
        return self._files.get(relative_path)

    def add_file(self, path: Path) -> Optional[ProjectFile]:
        """
        Add a file to the project.

        Args:
            path: Absolute or relative path to file

        Returns:
            ProjectFile if added, None if failed
        """
        if not self._root:
            logger.error("No project open")
            return None

        path = Path(path)
        if not path.is_absolute():
            path = self._root / path

        path = path.resolve()

        # Verify file is within project
        try:
            relative = path.relative_to(self._root)
        except ValueError:
            logger.error(f"File is outside project root: {path}")
            return None

        if not path.exists():
            logger.error(f"File does not exist: {path}")
            return None

        # Check ignore patterns
        if self._should_ignore(relative):
            logger.warning(f"File matches ignore pattern: {relative}")

        # Create ProjectFile
        project_file = self._create_project_file(path)
        self._files[str(relative)] = project_file

        self._notify_change("file_added", {"path": str(relative)})
        return project_file

    def remove_file(self, path: Path) -> bool:
        """
        Remove a file from the project tracking.

        Args:
            path: Path to file (absolute or relative)

        Returns:
            True if removed
        """
        if not self._root:
            return False

        path = Path(path)
        if path.is_absolute():
            try:
                path = path.relative_to(self._root)
            except ValueError:
                return False

        relative = str(path)

        if relative in self._files:
            del self._files[relative]
            self._notify_change("file_removed", {"path": relative})
            return True

        return False

    def refresh(self):
        """Refresh project file list"""
        if not self._root:
            return

        self._scan_files()
        self._notify_change("project_refreshed", {})

    def get_languages(self) -> Dict[str, int]:
        """
        Get languages used in project with file counts.

        Returns:
            Dict mapping language names to file counts
        """
        languages: Dict[str, int] = {}
        for file in self._files.values():
            if file.language:
                languages[file.language] = languages.get(file.language, 0) + 1
        return dict(sorted(languages.items(), key=lambda x: -x[1]))

    def get_statistics(self) -> Dict[str, Any]:
        """
        Get project statistics.

        Returns:
            Dict with various statistics
        """
        languages = self.get_languages()
        total_size = sum(f.size for f in self._files.values())

        return {
            "name": self.name,
            "type": self._project_type.value,
            "root": str(self._root) if self._root else None,
            "file_count": len(self._files),
            "total_size_bytes": total_size,
            "languages": languages,
            "dependency_count": len(self._dependencies),
        }

    # Project Detection

    def _detect_project_type(self) -> ProjectType:
        """Detect the type of project based on config files"""
        if not self._root:
            return ProjectType.UNKNOWN

        detected_types: Set[ProjectType] = set()

        for project_type, indicators in PROJECT_INDICATORS.items():
            for indicator in indicators:
                if (self._root / indicator).exists():
                    detected_types.add(project_type)
                    break

        if not detected_types:
            return ProjectType.UNKNOWN
        elif len(detected_types) == 1:
            return detected_types.pop()
        else:
            return ProjectType.MIXED

    # Configuration Loading

    def _load_project_config(self):
        """Load project configuration based on type"""
        if not self._root:
            return

        # Try different config files in priority order
        config_loaders = [
            ("pyproject.toml", self._load_pyproject_toml),
            ("package.json", self._load_package_json),
            ("Cargo.toml", self._load_cargo_toml),
            ("go.mod", self._load_go_mod),
            ("setup.py", self._load_setup_py),
            ("requirements.txt", self._load_requirements_txt),
        ]

        for filename, loader in config_loaders:
            config_path = self._root / filename
            if config_path.exists():
                try:
                    loader(config_path)
                except Exception as e:
                    logger.warning(f"Failed to load {filename}: {e}")

    def _load_pyproject_toml(self, path: Path):
        """Load Python pyproject.toml"""
        if not HAS_TOMLI:
            logger.warning("tomli not available, skipping pyproject.toml parsing")
            return

        try:
            with open(path, "rb") as f:
                data = tomli.load(f)
        except Exception as e:
            logger.error(f"Failed to parse pyproject.toml: {e}")
            return

        # Extract project metadata
        project = data.get("project", {})
        self._metadata.name = project.get("name", "")
        self._metadata.version = project.get("version", "")
        self._metadata.description = project.get("description", "")
        self._metadata.license = project.get("license", {}).get("text", "")

        authors = project.get("authors", [])
        self._metadata.authors = [
            a.get("name", "") + (f" <{a.get('email', '')}>" if a.get("email") else "")
            for a in authors
        ]

        self._metadata.keywords = project.get("keywords", [])
        self._metadata.python_version = project.get("requires-python", "")

        # Extract dependencies
        deps = project.get("dependencies", [])
        for dep in deps:
            self._dependencies.append(self._parse_python_dependency(dep))

        # Optional dependencies
        optional_deps = project.get("optional-dependencies", {})
        for group, deps in optional_deps.items():
            for dep in deps:
                parsed = self._parse_python_dependency(dep)
                parsed.optional = True
                self._dependencies.append(parsed)

        # Poetry format
        poetry = data.get("tool", {}).get("poetry", {})
        if poetry:
            if not self._metadata.name:
                self._metadata.name = poetry.get("name", "")
            if not self._metadata.version:
                self._metadata.version = poetry.get("version", "")

            for dep, version in poetry.get("dependencies", {}).items():
                if dep != "python":
                    ver = version if isinstance(version, str) else version.get("version", "")
                    self._dependencies.append(ProjectDependency(name=dep, version=ver))

            for dep, version in poetry.get("dev-dependencies", {}).items():
                ver = version if isinstance(version, str) else version.get("version", "")
                self._dependencies.append(ProjectDependency(name=dep, version=ver, dev=True))

    def _load_package_json(self, path: Path):
        """Load Node.js package.json"""
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            logger.error(f"Failed to parse package.json: {e}")
            return

        self._metadata.name = data.get("name", "")
        self._metadata.version = data.get("version", "")
        self._metadata.description = data.get("description", "")
        self._metadata.license = data.get("license", "")
        self._metadata.homepage = data.get("homepage", "")
        self._metadata.keywords = data.get("keywords", [])

        author = data.get("author", "")
        if isinstance(author, str):
            self._metadata.authors = [author]
        elif isinstance(author, dict):
            name = author.get("name", "")
            email = author.get("email", "")
            self._metadata.authors = [f"{name} <{email}>" if email else name]

        repo = data.get("repository", "")
        if isinstance(repo, str):
            self._metadata.repository = repo
        elif isinstance(repo, dict):
            self._metadata.repository = repo.get("url", "")

        # Node version
        engines = data.get("engines", {})
        self._metadata.node_version = engines.get("node", "")

        # Dependencies
        for dep, version in data.get("dependencies", {}).items():
            self._dependencies.append(ProjectDependency(name=dep, version=version))

        for dep, version in data.get("devDependencies", {}).items():
            self._dependencies.append(ProjectDependency(name=dep, version=version, dev=True))

    def _load_cargo_toml(self, path: Path):
        """Load Rust Cargo.toml"""
        if not HAS_TOMLI:
            logger.warning("tomli not available, skipping Cargo.toml parsing")
            return

        try:
            with open(path, "rb") as f:
                data = tomli.load(f)
        except Exception as e:
            logger.error(f"Failed to parse Cargo.toml: {e}")
            return

        package = data.get("package", {})
        self._metadata.name = package.get("name", "")
        self._metadata.version = package.get("version", "")
        self._metadata.description = package.get("description", "")
        self._metadata.license = package.get("license", "")
        self._metadata.authors = package.get("authors", [])
        self._metadata.repository = package.get("repository", "")
        self._metadata.keywords = package.get("keywords", [])

        # Dependencies
        for dep, info in data.get("dependencies", {}).items():
            if isinstance(info, str):
                self._dependencies.append(ProjectDependency(name=dep, version=info))
            elif isinstance(info, dict):
                self._dependencies.append(ProjectDependency(
                    name=dep,
                    version=info.get("version", ""),
                    optional=info.get("optional", False)
                ))

        for dep, info in data.get("dev-dependencies", {}).items():
            ver = info if isinstance(info, str) else info.get("version", "")
            self._dependencies.append(ProjectDependency(name=dep, version=ver, dev=True))

    def _load_go_mod(self, path: Path):
        """Load Go go.mod"""
        try:
            content = path.read_text(encoding="utf-8")
        except Exception as e:
            logger.error(f"Failed to read go.mod: {e}")
            return

        lines = content.splitlines()

        for line in lines:
            line = line.strip()
            if line.startswith("module "):
                self._metadata.name = line[7:].strip()
            elif line.startswith("go "):
                # Go version
                pass

        # Parse require block
        in_require = False
        for line in lines:
            line = line.strip()
            if line == "require (":
                in_require = True
            elif line == ")":
                in_require = False
            elif in_require or line.startswith("require "):
                # Parse dependency line
                if line.startswith("require "):
                    line = line[8:]
                parts = line.split()
                if len(parts) >= 2:
                    self._dependencies.append(ProjectDependency(
                        name=parts[0],
                        version=parts[1]
                    ))

    def _load_setup_py(self, path: Path):
        """Load Python setup.py (basic parsing)"""
        # Note: Full parsing would require executing the file
        # This is a basic regex-based extraction
        try:
            content = path.read_text(encoding="utf-8")
        except Exception as e:
            logger.error(f"Failed to read setup.py: {e}")
            return

        import re

        # Extract name
        match = re.search(r'name\s*=\s*["\']([^"\']+)["\']', content)
        if match:
            self._metadata.name = match.group(1)

        # Extract version
        match = re.search(r'version\s*=\s*["\']([^"\']+)["\']', content)
        if match:
            self._metadata.version = match.group(1)

    def _load_requirements_txt(self, path: Path):
        """Load Python requirements.txt"""
        try:
            content = path.read_text(encoding="utf-8")
        except Exception as e:
            logger.error(f"Failed to read requirements.txt: {e}")
            return

        for line in content.splitlines():
            line = line.strip()

            # Skip comments and empty lines
            if not line or line.startswith("#"):
                continue

            # Skip options like -r, -e, etc.
            if line.startswith("-"):
                continue

            self._dependencies.append(self._parse_python_dependency(line))

    def _parse_python_dependency(self, spec: str) -> ProjectDependency:
        """Parse a Python dependency specification"""
        import re

        # Handle various formats: pkg, pkg==1.0, pkg>=1.0, pkg[extra]>=1.0
        match = re.match(r'^([a-zA-Z0-9_-]+)(?:\[.*?\])?(?:([<>=!~]+)(.+))?$', spec.strip())
        if match:
            name = match.group(1)
            version = match.group(3) if match.group(3) else ""
            return ProjectDependency(name=name, version=version)

        return ProjectDependency(name=spec)

    # File Scanning

    def _load_gitignore(self):
        """Load .gitignore patterns"""
        if not self._root:
            return

        gitignore = self._root / ".gitignore"
        if not gitignore.exists():
            return

        try:
            content = gitignore.read_text(encoding="utf-8")
            for line in content.splitlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    self._ignore_patterns.append(line)
        except Exception as e:
            logger.warning(f"Failed to read .gitignore: {e}")

    def _should_ignore(self, path: Path) -> bool:
        """Check if path matches ignore patterns"""
        path_str = str(path)
        path_parts = path.parts

        for pattern in self._ignore_patterns:
            # Check full path match
            if fnmatch.fnmatch(path_str, pattern):
                return True

            # Check against each path component
            for part in path_parts:
                if fnmatch.fnmatch(part, pattern):
                    return True

            # Check path ends with pattern
            if fnmatch.fnmatch(path_str, f"*/{pattern}"):
                return True

        return False

    def _scan_files(self):
        """Scan project directory for files"""
        if not self._root:
            return

        self._files.clear()

        for root, dirs, files in os.walk(self._root):
            root_path = Path(root)

            # Filter directories in-place
            dirs[:] = [
                d for d in dirs
                if not self._should_ignore(root_path / d)
            ]

            for filename in files:
                file_path = root_path / filename
                try:
                    relative = file_path.relative_to(self._root)
                except ValueError:
                    continue

                if self._should_ignore(relative):
                    continue

                project_file = self._create_project_file(file_path)
                self._files[str(relative)] = project_file

        logger.info(f"Found {len(self._files)} files in project")

    def _create_project_file(self, path: Path) -> ProjectFile:
        """Create ProjectFile from path"""
        try:
            stat = path.stat()
            size = stat.st_size
            mtime = stat.st_mtime
        except Exception:
            size = 0
            mtime = 0

        ext = path.suffix.lower()
        language = EXTENSION_TO_LANGUAGE.get(ext, "")

        try:
            relative = str(path.relative_to(self._root)) if self._root else str(path)
        except ValueError:
            relative = str(path)

        return ProjectFile(
            path=path,
            relative_path=relative,
            language=language,
            size=size,
            modified_time=mtime
        )

    # Callbacks

    def on_change(self, callback: Callable[[str, Dict], None]):
        """
        Register callback for project changes.

        Args:
            callback: Function taking (event_type, data)
        """
        if callback not in self._change_callbacks:
            self._change_callbacks.append(callback)

    def off_change(self, callback: Callable):
        """Unregister change callback"""
        if callback in self._change_callbacks:
            self._change_callbacks.remove(callback)

    def _notify_change(self, event: str, data: Dict):
        """Notify callbacks of change"""
        for callback in self._change_callbacks:
            try:
                callback(event, data)
            except Exception as e:
                logger.error(f"Change callback error: {e}")


# Factory function

def find_project_root(start_path: Path) -> Optional[Path]:
    """
    Find project root by walking up directories.

    Args:
        start_path: Path to start searching from

    Returns:
        Project root path, or None if not found
    """
    path = Path(start_path).resolve()

    # If start_path is a file, start from its parent
    if path.is_file():
        path = path.parent

    # Walk up until we find a project indicator or hit root
    indicators = set()
    for patterns in PROJECT_INDICATORS.values():
        indicators.update(patterns)

    # Also check for .git
    indicators.add(".git")

    while path != path.parent:
        for indicator in indicators:
            if (path / indicator).exists():
                return path
        path = path.parent

    return None
