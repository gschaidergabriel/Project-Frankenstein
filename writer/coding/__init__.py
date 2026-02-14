"""
Coding Mode Module for Frank Writer
Provides coding-specific features and components
"""

from writer.coding.mode_manager import (
    ModeManager,
    ModeConfig,
    WriterMode,
    MODE_CONFIGS,
)

from writer.coding.theme import (
    CodingTheme,
    CodingThemeDefinition,
    ThemeColor,
    BUILTIN_THEMES,
)

from writer.coding.lsp_client import (
    LSPClient,
    LSPServerConfig,
    LSP_SERVERS,
    Position,
    Range,
    Location,
    Diagnostic,
    CompletionItem,
    uri_to_path,
    path_to_uri,
)

from writer.coding.syntax_manager import (
    SyntaxManager,
    BracketType,
    BracketPair,
    FoldRegion,
    IndentInfo,
    LANGUAGE_CONFIG,
)

from writer.coding.project import (
    Project,
    ProjectType,
    ProjectFile,
    ProjectDependency,
    ProjectMetadata,
    find_project_root,
)

__all__ = [
    # Mode Manager
    "ModeManager",
    "ModeConfig",
    "WriterMode",
    "MODE_CONFIGS",
    # Theme
    "CodingTheme",
    "CodingThemeDefinition",
    "ThemeColor",
    "BUILTIN_THEMES",
    # LSP Client
    "LSPClient",
    "LSPServerConfig",
    "LSP_SERVERS",
    "Position",
    "Range",
    "Location",
    "Diagnostic",
    "CompletionItem",
    "uri_to_path",
    "path_to_uri",
    # Syntax Manager
    "SyntaxManager",
    "BracketType",
    "BracketPair",
    "FoldRegion",
    "IndentInfo",
    "LANGUAGE_CONFIG",
    # Project
    "Project",
    "ProjectType",
    "ProjectFile",
    "ProjectDependency",
    "ProjectMetadata",
    "find_project_root",
]
