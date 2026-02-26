"""
Version History for Frank Writer
Maintains local snapshots of document versions.
"""

import json
import hashlib
import logging
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, asdict
from typing import List, Optional

logger = logging.getLogger(__name__)

try:
    from config.paths import AICORE_DATA
    HISTORY_DIR = AICORE_DATA / "writer" / "versions"
except ImportError:
    HISTORY_DIR = Path.home() / ".local" / "share" / "frank" / "writer" / "versions"
MAX_VERSIONS_PER_DOC = 50


@dataclass
class VersionEntry:
    """A single version snapshot"""
    version_id: str
    timestamp: str
    title: str
    word_count: int
    content_hash: str
    label: str = ""  # Optional user label like "Before rewrite"

    @property
    def display_time(self) -> str:
        try:
            dt = datetime.fromisoformat(self.timestamp)
            return dt.strftime("%d.%m.%Y %H:%M")
        except (ValueError, TypeError):
            return self.timestamp


class VersionHistory:
    """Manages version snapshots for a document."""

    def __init__(self):
        HISTORY_DIR.mkdir(parents=True, exist_ok=True)

    def _doc_dir(self, doc_id: str) -> Path:
        """Get version directory for a document."""
        safe_id = "".join(c if c.isalnum() or c in '-_' else '_' for c in doc_id)
        d = HISTORY_DIR / safe_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _doc_id(self, file_path: Optional[Path], title: str) -> str:
        """Generate a stable ID for the document."""
        if file_path:
            return hashlib.sha256(str(file_path).encode()).hexdigest()[:16]
        return hashlib.sha256(title.encode()).hexdigest()[:16]

    def save_version(self, file_path: Optional[Path], title: str,
                     content: str, label: str = "") -> VersionEntry:
        """Save a version snapshot. Returns the new VersionEntry."""
        doc_id = self._doc_id(file_path, title)
        doc_dir = self._doc_dir(doc_id)

        content_hash = hashlib.sha256(content.encode()).hexdigest()[:16]

        # Check if identical to last version
        versions = self.list_versions(file_path, title)
        if versions and versions[0].content_hash == content_hash:
            return versions[0]  # No change

        timestamp = datetime.now().isoformat()
        version_id = hashlib.sha256(
            f"{timestamp}{content_hash}".encode()
        ).hexdigest()[:12]

        entry = VersionEntry(
            version_id=version_id,
            timestamp=timestamp,
            title=title,
            word_count=len(content.split()),
            content_hash=content_hash,
            label=label,
        )

        # Save content
        (doc_dir / f"{version_id}.txt").write_text(content, encoding='utf-8')

        # Save metadata
        meta_path = doc_dir / "versions.json"
        entries = self._load_meta(meta_path)
        entries.insert(0, asdict(entry))

        # Trim old versions
        if len(entries) > MAX_VERSIONS_PER_DOC:
            for old in entries[MAX_VERSIONS_PER_DOC:]:
                old_file = doc_dir / f"{old['version_id']}.txt"
                try:
                    old_file.unlink(missing_ok=True)
                except OSError:
                    pass
            entries = entries[:MAX_VERSIONS_PER_DOC]

        meta_path.write_text(
            json.dumps(entries, ensure_ascii=False, indent=1),
            encoding='utf-8'
        )

        return entry

    def list_versions(self, file_path: Optional[Path],
                      title: str) -> List[VersionEntry]:
        """List all versions for a document (newest first)."""
        doc_id = self._doc_id(file_path, title)
        meta_path = self._doc_dir(doc_id) / "versions.json"
        entries = self._load_meta(meta_path)
        return [VersionEntry(**e) for e in entries]

    def get_version_content(self, file_path: Optional[Path],
                            title: str, version_id: str) -> Optional[str]:
        """Get content of a specific version."""
        doc_id = self._doc_id(file_path, title)
        content_file = self._doc_dir(doc_id) / f"{version_id}.txt"
        if content_file.exists():
            return content_file.read_text(encoding='utf-8')
        return None

    def _load_meta(self, meta_path: Path) -> list:
        try:
            if meta_path.exists():
                return json.loads(meta_path.read_text(encoding='utf-8'))
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"Error loading version metadata: {e}")
        return []
