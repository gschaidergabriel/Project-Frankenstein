#!/usr/bin/env python3
"""
File Organizer - Intelligent File Organization with Undo

Features:
- Context-aware file organization
- Custom folder structure creation
- Preview before action (single confirmation)
- Full undo capability
- Pattern-based custom organization rules

Author: Frank AI System
"""

import json
import logging
import os
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .sensitive_actions import (
    ConfirmationLevel,
    request_confirmation,
    is_action_confirmed,
    mark_action_executed,
    determine_confirmation_level,
)

LOG = logging.getLogger("system_control.file_organizer")

# Database path
try:
    from config.paths import SYSTEM_CONTROL_DIR as DB_DIR
except ImportError:
    DB_DIR = Path("/home/ai-core-node/aicore/database/system_control")
DB_DIR.mkdir(parents=True, exist_ok=True)
UNDO_HISTORY_FILE = DB_DIR / "file_undo_history.json"

# Maximum undo operations to keep
MAX_UNDO_HISTORY = 50


@dataclass
class FileMove:
    """Represents a single file move operation."""
    source: str
    destination: str
    timestamp: str
    success: bool = False

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "destination": self.destination,
            "timestamp": self.timestamp,
            "success": self.success
        }

    @classmethod
    def from_dict(cls, data: dict) -> "FileMove":
        return cls(**data)


@dataclass
class OrganizeOperation:
    """Represents a complete organize operation (can be undone)."""
    operation_id: str
    description: str
    timestamp: str
    moves: List[FileMove] = field(default_factory=list)
    completed: bool = False
    undone: bool = False

    def to_dict(self) -> dict:
        return {
            "operation_id": self.operation_id,
            "description": self.description,
            "timestamp": self.timestamp,
            "moves": [m.to_dict() for m in self.moves],
            "completed": self.completed,
            "undone": self.undone
        }

    @classmethod
    def from_dict(cls, data: dict) -> "OrganizeOperation":
        op = cls(
            operation_id=data["operation_id"],
            description=data["description"],
            timestamp=data["timestamp"],
            completed=data.get("completed", False),
            undone=data.get("undone", False)
        )
        op.moves = [FileMove.from_dict(m) for m in data.get("moves", [])]
        return op


class FileOrganizer:
    """Organizes files with preview and undo capability."""

    # Common file type categories
    FILE_CATEGORIES = {
        "images": {
            "extensions": [".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".svg", ".ico", ".tiff", ".raw", ".heic"],
            "folder": "Bilder"
        },
        "documents": {
            "extensions": [".pdf", ".doc", ".docx", ".odt", ".txt", ".rtf", ".xls", ".xlsx", ".ppt", ".pptx", ".csv", ".md"],
            "folder": "Dokumente"
        },
        "videos": {
            "extensions": [".mp4", ".avi", ".mkv", ".mov", ".wmv", ".flv", ".webm", ".m4v", ".mpeg"],
            "folder": "Videos"
        },
        "audio": {
            "extensions": [".mp3", ".wav", ".flac", ".aac", ".ogg", ".wma", ".m4a", ".opus"],
            "folder": "Musik"
        },
        "archives": {
            "extensions": [".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz", ".tar.gz", ".tgz"],
            "folder": "Archive"
        },
        "code": {
            "extensions": [".py", ".js", ".ts", ".java", ".cpp", ".c", ".h", ".html", ".css", ".json", ".xml", ".sh", ".go", ".rs"],
            "folder": "Code"
        },
        "executables": {
            "extensions": [".exe", ".msi", ".deb", ".rpm", ".AppImage", ".sh", ".run"],
            "folder": "Programme"
        }
    }

    # Custom structure templates
    STRUCTURE_TEMPLATES = {
        "projekt": {
            "folders": ["src", "docs", "tests", "assets", "config"],
            "description": "Projekt-Struktur mit src, docs, tests, assets, config"
        },
        "foto_sammlung": {
            "folders": ["Roh", "Bearbeitet", "Export", "Aussortiert"],
            "description": "Foto-Sammlung mit Workflow-Ordnern"
        },
        "musik_sammlung": {
            "folders": ["Alben", "Singles", "Playlists", "Podcasts"],
            "description": "Musik-Sammlung nach Format"
        }
    }

    def __init__(self):
        self._undo_history: List[OrganizeOperation] = []
        self._load_history()

    def _load_history(self):
        """Load undo history from disk."""
        try:
            if UNDO_HISTORY_FILE.exists():
                data = json.loads(UNDO_HISTORY_FILE.read_text())
                self._undo_history = [
                    OrganizeOperation.from_dict(op)
                    for op in data.get("operations", [])
                ]
        except Exception as e:
            LOG.error(f"Failed to load undo history: {e}")

    def _save_history(self):
        """Save undo history to disk."""
        try:
            # Keep only the last MAX_UNDO_HISTORY operations
            recent = self._undo_history[-MAX_UNDO_HISTORY:]
            data = {
                "timestamp": datetime.now().isoformat(),
                "operations": [op.to_dict() for op in recent]
            }
            UNDO_HISTORY_FILE.write_text(json.dumps(data, indent=2))
        except Exception as e:
            LOG.error(f"Failed to save undo history: {e}")

    def analyze_folder(self, folder_path: str) -> Dict[str, List[str]]:
        """
        Analyze a folder and group files by category.

        Returns:
            Dict mapping category name to list of file paths
        """
        folder = Path(folder_path).expanduser()
        if not folder.exists():
            return {}

        categorized: Dict[str, List[str]] = {}

        for item in folder.iterdir():
            if item.is_file():
                ext = item.suffix.lower()

                # Find category
                category = "other"
                for cat_name, cat_info in self.FILE_CATEGORIES.items():
                    if ext in cat_info["extensions"]:
                        category = cat_name
                        break

                if category not in categorized:
                    categorized[category] = []
                categorized[category].append(str(item))

        return categorized

    def plan_organization(
        self,
        source_folder: str,
        target_folder: Optional[str] = None,
        strategy: str = "by_type"
    ) -> Tuple[List[FileMove], str]:
        """
        Plan file organization without executing.

        Args:
            source_folder: Folder to organize
            target_folder: Destination folder (default: create subfolders in source)
            strategy: "by_type" (default), "by_date", or "by_name"

        Returns:
            (list of planned moves, preview text)
        """
        source = Path(source_folder).expanduser()
        if not source.exists():
            return [], f"Ordner existiert nicht: {source_folder}"

        moves: List[FileMove] = []
        preview_lines = [f"ORGANISATION VON: {source}", "=" * 50, ""]

        if target_folder:
            target = Path(target_folder).expanduser()
        else:
            target = source

        if strategy == "by_type":
            categorized = self.analyze_folder(str(source))

            for category, files in categorized.items():
                if not files:
                    continue

                # Get target subfolder name
                cat_info = self.FILE_CATEGORIES.get(category)
                if cat_info:
                    subfolder_name = cat_info["folder"]
                else:
                    subfolder_name = "Sonstiges"

                dest_folder = target / subfolder_name

                preview_lines.append(f"{subfolder_name}/ ({len(files)} Dateien)")

                for file_path in files:
                    file = Path(file_path)
                    dest = dest_folder / file.name
                    moves.append(FileMove(
                        source=str(file),
                        destination=str(dest),
                        timestamp=datetime.now().isoformat()
                    ))
                    preview_lines.append(f"  - {file.name}")

                preview_lines.append("")

        elif strategy == "by_date":
            for item in source.iterdir():
                if item.is_file():
                    # Get file modification date
                    mtime = datetime.fromtimestamp(item.stat().st_mtime)
                    date_folder = mtime.strftime("%Y-%m")
                    dest_folder = target / date_folder

                    moves.append(FileMove(
                        source=str(item),
                        destination=str(dest_folder / item.name),
                        timestamp=datetime.now().isoformat()
                    ))

            # Group preview by date
            by_date: Dict[str, List[str]] = {}
            for move in moves:
                date_folder = Path(move.destination).parent.name
                if date_folder not in by_date:
                    by_date[date_folder] = []
                by_date[date_folder].append(Path(move.source).name)

            for date, files in sorted(by_date.items()):
                preview_lines.append(f"{date}/ ({len(files)} Dateien)")
                for f in files[:5]:
                    preview_lines.append(f"  - {f}")
                if len(files) > 5:
                    preview_lines.append(f"  ... und {len(files) - 5} weitere")
                preview_lines.append("")

        preview_lines.append(f"GESAMT: {len(moves)} Dateien werden verschoben")
        preview = "\n".join(preview_lines)

        return moves, preview

    def request_organization(
        self,
        source_folder: str,
        target_folder: Optional[str] = None,
        strategy: str = "by_type",
        description: Optional[str] = None
    ) -> Tuple[str, str]:
        """
        Request file organization with confirmation.

        Returns:
            (action_id, confirmation_message)
        """
        moves, preview = self.plan_organization(source_folder, target_folder, strategy)

        if not moves:
            return "", "Keine Dateien zum Organisieren gefunden"

        # Determine confirmation level
        level = determine_confirmation_level(
            action_type="file_organize",
            file_count=len(moves)
        )

        desc = description or f"Organisiere {len(moves)} Dateien in {source_folder}"

        return request_confirmation(
            action_type="file_organize",
            description=desc,
            preview=preview,
            params={
                "source_folder": source_folder,
                "target_folder": target_folder,
                "strategy": strategy,
                "moves": [m.to_dict() for m in moves]
            },
            level=level,
            undo_info={
                "operation_type": "file_organize",
                "can_undo": True
            }
        )

    def execute_organization(self, action_id: str) -> Tuple[bool, str]:
        """Execute confirmed file organization."""
        if not is_action_confirmed(action_id):
            return False, "Aktion nicht bestätigt"

        from .sensitive_actions import get_handler
        action = get_handler().get_action(action_id)

        if not action:
            return False, "Aktion nicht gefunden"

        moves_data = action.params.get("moves", [])
        moves = [FileMove.from_dict(m) for m in moves_data]

        # Create operation for undo history
        operation = OrganizeOperation(
            operation_id=action_id,
            description=action.description,
            timestamp=datetime.now().isoformat()
        )

        success_count = 0
        error_count = 0

        for move in moves:
            try:
                source = Path(move.source)
                dest = Path(move.destination)

                if not source.exists():
                    LOG.warning(f"Source not found: {source}")
                    error_count += 1
                    continue

                # Create destination directory
                dest.parent.mkdir(parents=True, exist_ok=True)

                # Handle destination conflict
                if dest.exists():
                    # Add number suffix to avoid overwrite
                    base = dest.stem
                    suffix = dest.suffix
                    counter = 1
                    while dest.exists():
                        dest = dest.parent / f"{base}_{counter}{suffix}"
                        counter += 1
                    move.destination = str(dest)  # Update for undo

                # Move file
                shutil.move(str(source), str(dest))

                move.success = True
                success_count += 1
                LOG.debug(f"Moved: {source} -> {dest}")

            except Exception as e:
                LOG.error(f"Failed to move {move.source}: {e}")
                error_count += 1

            operation.moves.append(move)

        operation.completed = True
        self._undo_history.append(operation)
        self._save_history()

        mark_action_executed(action_id)

        if error_count == 0:
            return True, f"Organisation abgeschlossen: {success_count} Dateien verschoben"
        else:
            return True, f"Organisation abgeschlossen: {success_count} erfolgreich, {error_count} Fehler"

    def undo_last_operation(self) -> Tuple[bool, str]:
        """Undo the last file organization operation."""
        # Find the last undoable operation
        for op in reversed(self._undo_history):
            if op.completed and not op.undone:
                return self._undo_operation(op)

        return False, "Keine rückgängig machbare Operation gefunden"

    def _undo_operation(self, operation: OrganizeOperation) -> Tuple[bool, str]:
        """Undo a specific operation."""
        success_count = 0
        error_count = 0

        # Reverse all moves
        for move in reversed(operation.moves):
            if not move.success:
                continue

            try:
                source = Path(move.destination)  # Now the source
                dest = Path(move.source)  # Original location

                if not source.exists():
                    LOG.warning(f"File not found for undo: {source}")
                    error_count += 1
                    continue

                # Create destination directory if needed
                dest.parent.mkdir(parents=True, exist_ok=True)

                # Move back
                shutil.move(str(source), str(dest))
                success_count += 1
                LOG.debug(f"Undone: {source} -> {dest}")

            except Exception as e:
                LOG.error(f"Undo failed for {move.destination}: {e}")
                error_count += 1

        operation.undone = True
        self._save_history()

        if error_count == 0:
            return True, f"Rückgängig gemacht: {success_count} Dateien zurück verschoben"
        elif success_count > 0:
            return True, f"Teilweise rückgängig: {success_count} erfolgreich, {error_count} Fehler"
        else:
            return False, f"Rückgängig machen fehlgeschlagen: {error_count} Fehler"

    def get_undo_preview(self) -> Optional[str]:
        """Get preview of what would be undone."""
        for op in reversed(self._undo_history):
            if op.completed and not op.undone:
                lines = [
                    f"LETZTE OPERATION RÜCKGÄNGIG MACHEN:",
                    f"'{op.description}'",
                    f"Zeitpunkt: {op.timestamp}",
                    f"Betroffene Dateien: {len([m for m in op.moves if m.success])}",
                    "",
                    "Beispiele:"
                ]
                for move in op.moves[:5]:
                    if move.success:
                        lines.append(f"  {Path(move.destination).name} -> {Path(move.source).parent}")
                if len(op.moves) > 5:
                    lines.append(f"  ... und {len(op.moves) - 5} weitere")
                return "\n".join(lines)

        return None

    # =========================================================================
    # Custom Structure Creation
    # =========================================================================

    def create_folder_structure(
        self,
        base_path: str,
        structure: Dict[str, Any],
        description: str = ""
    ) -> Tuple[str, str]:
        """
        Create a custom folder structure.

        Args:
            base_path: Where to create the structure
            structure: Dict defining the structure, e.g.:
                {
                    "Projekte": {
                        "Projekt_A": ["src", "docs", "tests"],
                        "Projekt_B": ["src", "docs", "tests"]
                    },
                    "Archive": [],
                    "Temp": []
                }
            description: Description for the operation

        Returns:
            (action_id, confirmation_message)
        """
        base = Path(base_path).expanduser()

        # Build preview and collect folders to create
        folders_to_create = []
        preview_lines = [f"ORDNER-STRUKTUR ERSTELLEN IN: {base}", "=" * 50, ""]

        def process_structure(current_path: Path, struct: Any, indent: int = 0):
            prefix = "  " * indent

            if isinstance(struct, dict):
                for name, content in struct.items():
                    folder_path = current_path / name
                    folders_to_create.append(str(folder_path))
                    preview_lines.append(f"{prefix}{name}/")
                    process_structure(folder_path, content, indent + 1)

            elif isinstance(struct, list):
                for name in struct:
                    folder_path = current_path / name
                    folders_to_create.append(str(folder_path))
                    preview_lines.append(f"{prefix}{name}/")

        process_structure(base, structure)

        preview_lines.append("")
        preview_lines.append(f"GESAMT: {len(folders_to_create)} Ordner werden erstellt")
        preview = "\n".join(preview_lines)

        desc = description or f"Erstelle {len(folders_to_create)} Ordner in {base_path}"

        return request_confirmation(
            action_type="file_structure",
            description=desc,
            preview=preview,
            params={
                "base_path": base_path,
                "folders": folders_to_create
            },
            level=ConfirmationLevel.SINGLE,
            undo_info={
                "operation_type": "file_structure",
                "can_undo": True
            }
        )

    def execute_structure_creation(self, action_id: str) -> Tuple[bool, str]:
        """Execute confirmed folder structure creation."""
        if not is_action_confirmed(action_id):
            return False, "Aktion nicht bestätigt"

        from .sensitive_actions import get_handler
        action = get_handler().get_action(action_id)

        if not action:
            return False, "Aktion nicht gefunden"

        folders = action.params.get("folders", [])
        created_count = 0
        error_count = 0

        for folder_path in folders:
            try:
                folder = Path(folder_path)
                folder.mkdir(parents=True, exist_ok=True)
                created_count += 1
                LOG.debug(f"Created folder: {folder}")
            except Exception as e:
                LOG.error(f"Failed to create {folder_path}: {e}")
                error_count += 1

        mark_action_executed(action_id)

        if error_count == 0:
            return True, f"Struktur erstellt: {created_count} Ordner angelegt"
        else:
            return True, f"Struktur erstellt: {created_count} OK, {error_count} Fehler"

    def plan_custom_organization(
        self,
        source_folder: str,
        rules: List[Dict[str, Any]]
    ) -> Tuple[List[FileMove], str]:
        """
        Plan custom file organization based on user-defined rules.

        Args:
            source_folder: Folder to organize
            rules: List of rules, e.g.:
                [
                    {"pattern": "*.pdf", "target": "PDFs"},
                    {"pattern": "*.jpg", "target": "Fotos/2024"},
                    {"contains": "invoice", "target": "Rechnungen"},
                    {"extension": ".mp4", "target": "Videos/Filme"}
                ]

        Returns:
            (list of planned moves, preview text)
        """
        import fnmatch

        source = Path(source_folder).expanduser()
        if not source.exists():
            return [], f"Ordner existiert nicht: {source_folder}"

        moves: List[FileMove] = []
        preview_lines = [f"CUSTOM ORGANISATION VON: {source}", "=" * 50, ""]

        # Group moves by target folder for preview
        by_target: Dict[str, List[str]] = {}

        for item in source.iterdir():
            if not item.is_file():
                continue

            target_folder = None

            for rule in rules:
                # Pattern matching (*.pdf, *.jpg, etc.)
                if "pattern" in rule:
                    if fnmatch.fnmatch(item.name.lower(), rule["pattern"].lower()):
                        target_folder = rule["target"]
                        break

                # Extension matching
                if "extension" in rule:
                    if item.suffix.lower() == rule["extension"].lower():
                        target_folder = rule["target"]
                        break

                # Contains matching (filename contains string)
                if "contains" in rule:
                    if rule["contains"].lower() in item.name.lower():
                        target_folder = rule["target"]
                        break

            if target_folder:
                dest = source / target_folder / item.name
                moves.append(FileMove(
                    source=str(item),
                    destination=str(dest),
                    timestamp=datetime.now().isoformat()
                ))

                if target_folder not in by_target:
                    by_target[target_folder] = []
                by_target[target_folder].append(item.name)

        # Build preview
        for target, files in by_target.items():
            preview_lines.append(f"{target}/ ({len(files)} Dateien)")
            for f in files[:5]:
                preview_lines.append(f"  - {f}")
            if len(files) > 5:
                preview_lines.append(f"  ... und {len(files) - 5} weitere")
            preview_lines.append("")

        preview_lines.append(f"GESAMT: {len(moves)} Dateien werden verschoben")
        preview = "\n".join(preview_lines)

        return moves, preview

    def request_custom_organization(
        self,
        source_folder: str,
        rules: List[Dict[str, Any]],
        description: Optional[str] = None
    ) -> Tuple[str, str]:
        """
        Request custom file organization with user-defined rules.

        Returns:
            (action_id, confirmation_message)
        """
        moves, preview = self.plan_custom_organization(source_folder, rules)

        if not moves:
            return "", "Keine Dateien entsprechen den Regeln"

        desc = description or f"Custom Organisation: {len(moves)} Dateien"

        return request_confirmation(
            action_type="file_organize",
            description=desc,
            preview=preview,
            params={
                "source_folder": source_folder,
                "rules": rules,
                "moves": [m.to_dict() for m in moves]
            },
            level=ConfirmationLevel.SINGLE,
            undo_info={
                "operation_type": "file_organize",
                "can_undo": True
            }
        )


# Singleton
_organizer: Optional[FileOrganizer] = None


def get_organizer() -> FileOrganizer:
    """Get singleton organizer."""
    global _organizer
    if _organizer is None:
        _organizer = FileOrganizer()
    return _organizer


# Public API

def analyze_folder(folder_path: str) -> Dict[str, List[str]]:
    """Analyze folder contents by category."""
    return get_organizer().analyze_folder(folder_path)


def plan_organization(
    source_folder: str,
    target_folder: Optional[str] = None,
    strategy: str = "by_type"
) -> Tuple[List[Dict], str]:
    """Plan file organization."""
    moves, preview = get_organizer().plan_organization(source_folder, target_folder, strategy)
    return [m.to_dict() for m in moves], preview


def request_organization(
    source_folder: str,
    target_folder: Optional[str] = None,
    strategy: str = "by_type",
    description: Optional[str] = None
) -> Tuple[str, str]:
    """Request file organization with confirmation."""
    return get_organizer().request_organization(source_folder, target_folder, strategy, description)


def execute_organization(action_id: str) -> Tuple[bool, str]:
    """Execute confirmed organization."""
    return get_organizer().execute_organization(action_id)


def undo_last_organization() -> Tuple[bool, str]:
    """Undo last file organization."""
    return get_organizer().undo_last_operation()


def get_undo_preview() -> Optional[str]:
    """Get undo preview."""
    return get_organizer().get_undo_preview()


def create_folder_structure(
    base_path: str,
    structure: Dict[str, Any],
    description: str = ""
) -> Tuple[str, str]:
    """
    Create a custom folder structure.

    Example structure:
        {
            "Projekte": {
                "Projekt_A": ["src", "docs", "tests"],
                "Projekt_B": ["src", "docs", "tests"]
            },
            "Archive": []
        }
    """
    return get_organizer().create_folder_structure(base_path, structure, description)


def execute_structure_creation(action_id: str) -> Tuple[bool, str]:
    """Execute confirmed folder structure creation."""
    return get_organizer().execute_structure_creation(action_id)


def request_custom_organization(
    source_folder: str,
    rules: List[Dict[str, Any]],
    description: Optional[str] = None
) -> Tuple[str, str]:
    """
    Request custom file organization with user-defined rules.

    Example rules:
        [
            {"pattern": "*.pdf", "target": "PDFs"},
            {"pattern": "*.jpg", "target": "Fotos/2024"},
            {"contains": "invoice", "target": "Rechnungen"}
        ]
    """
    return get_organizer().request_custom_organization(source_folder, rules, description)


# Quick test
if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)

    print("=== File Organizer Test ===")

    organizer = get_organizer()

    # Test folder analysis
    test_folder = Path.home() / "Downloads"
    if test_folder.exists():
        print(f"\nAnalyzing: {test_folder}")
        categories = organizer.analyze_folder(str(test_folder))

        for cat, files in categories.items():
            print(f"\n{cat}: {len(files)} files")
            for f in files[:3]:
                print(f"  - {Path(f).name}")
            if len(files) > 3:
                print(f"  ... and {len(files) - 3} more")

        # Plan organization
        print("\n--- Organization Plan ---")
        moves, preview = organizer.plan_organization(str(test_folder))
        print(preview)
    else:
        print(f"Test folder not found: {test_folder}")
