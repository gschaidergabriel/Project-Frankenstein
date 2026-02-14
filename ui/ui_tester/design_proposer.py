#!/usr/bin/env python3
"""
Design Proposer - Generates color patches for chat_overlay.

Takes Claude's analysis and translates it into applicable color changes
for the COLORS dictionary in chat_overlay.py (tkinter-based).
"""

import json
import logging
import os
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .claude_client import ClaudeClient

LOG = logging.getLogger("ui_tester.proposer")

# Target: chat_overlay.py COLORS dictionary (tkinter-based)
try:
    from config.paths import UI_DIR as _UI_DIR
except ImportError:
    _UI_DIR = Path("/home/ai-core-node/aicore/opt/aicore/ui")
CHAT_OVERLAY_PY = _UI_DIR / "chat_overlay.py"
BACKUP_DIR = _UI_DIR / "ui_tester" / "style_backups"
BACKUP_DIR.mkdir(parents=True, exist_ok=True)

# Export proposed colors to config file
COLORS_CONFIG = BACKUP_DIR / "proposed_colors.json"


class DesignProposer:
    """Generates and applies color patches for chat_overlay."""

    def __init__(self):
        self.claude = ClaudeClient()
        self.current_colors: Dict[str, str] = {}
        self.proposed_colors: Dict[str, str] = {}
        self.changes: List[Dict[str, Any]] = []
        self._load_current_colors()

    def _load_current_colors(self):
        """Load the current COLORS dictionary from chat_overlay.py."""
        if not CHAT_OVERLAY_PY.exists():
            LOG.warning(f"chat_overlay.py not found: {CHAT_OVERLAY_PY}")
            return

        try:
            content = CHAT_OVERLAY_PY.read_text(encoding="utf-8")

            # Find the COLORS dictionary
            colors_match = re.search(
                r'^COLORS\s*=\s*\{([^}]+(?:\{[^}]*\}[^}]*)*)\}',
                content,
                re.MULTILINE | re.DOTALL
            )

            if colors_match:
                # Parse the dictionary content
                dict_content = colors_match.group(1)
                # Extract key-value pairs
                for match in re.finditer(r'"([^"]+)":\s*"([^"]+)"', dict_content):
                    key, value = match.groups()
                    self.current_colors[key] = value

                LOG.info(f"Loaded {len(self.current_colors)} colors from chat_overlay.py")
            else:
                LOG.warning("COLORS dictionary not found in chat_overlay.py")

        except Exception as e:
            LOG.error(f"Failed to load colors: {e}")

    def generate_proposal(
        self,
        issues: List[str],
        observations: List[str],
        screenshots: List[Path]
    ) -> Dict[str, Any]:
        """
        Generate a color proposal based on test results.

        Args:
            issues: List of identified issues
            observations: List of observations from testing
            screenshots: Representative screenshots

        Returns:
            Dict with proposed changes
        """
        system_prompt = """Du bist ein UI/UX Design-Experte für Cyberpunk-Styling.
Deine Aufgabe: Analysiere die Issues und generiere KONKRETE FARBÄNDERUNGEN.

AKTUELLER STYLE (Cyberpunk - chat_overlay.py):
- Hauptfarbe: Magenta (#cc44cc)
- Sekundär: Neon Cyan (#00fff9)
- Hintergründe: Ultra-dunkel (#08080f, #0a0a12, #12121a)
- Text: Hell (#e0e0e0)
- Font: Consolas, monospace

VERFÜGBARE FARB-KEYS (änderbar):
""" + "\n".join(f"- {k}: {v}" for k, v in list(self.current_colors.items())[:20]) + """

AUSGABE-FORMAT (JSON):
{
    "summary": "Kurze Zusammenfassung",
    "changes": [
        {
            "color_key": "bg_main",
            "old_value": "#0a0a12",
            "new_value": "#0c0c14",
            "reason": "Etwas heller für besseren Kontrast"
        }
    ]
}

Nutze NUR existierende color_keys! Gib konkrete Hex-Werte an!"""

        issues_text = "\n".join(f"- {issue}" for issue in issues) if issues else "Keine Issues"
        obs_text = "\n".join(f"- {obs}" for obs in observations[:10]) if observations else "Keine"

        prompt = f"""ANALYSE-ERGEBNISSE:

GEFUNDENE ISSUES:
{issues_text}

BEOBACHTUNGEN:
{obs_text}

AKTUELLE FARBEN:
{json.dumps(dict(list(self.current_colors.items())[:15]), indent=2)}

Generiere konkrete Farbverbesserungen im Cyberpunk-Style.
Fokus: Lesbarkeit, Kontrast, Glow-Effekte, Neon-Ästhetik."""

        images = [p for p in screenshots[:3] if p.exists()]
        response = self.claude.chat(prompt, system_prompt, images)

        # Parse JSON - try multiple patterns
        try:
            # First try: find JSON block in response
            json_patterns = [
                r'```json\s*([\s\S]*?)\s*```',  # Markdown code block
                r'```\s*([\s\S]*?)\s*```',       # Plain code block
                r'(\{[^{}]*"changes"[^{}]*\[[\s\S]*?\]\s*\})',  # Object with changes array
            ]

            for pattern in json_patterns:
                match = re.search(pattern, response)
                if match:
                    try:
                        proposal = json.loads(match.group(1))
                        self._process_proposal(proposal)
                        return proposal
                    except json.JSONDecodeError:
                        continue

            # Fallback: try to parse the whole response as JSON
            proposal = json.loads(response)
            self._process_proposal(proposal)
            return proposal

        except (json.JSONDecodeError, AttributeError) as e:
            LOG.warning(f"Failed to parse proposal JSON: {e}")

        return {
            "summary": response[:500] if response else "Keine Analyse möglich",
            "changes": []
        }

    def _process_proposal(self, proposal: Dict[str, Any]):
        """Process and validate a proposal."""
        self.changes = []
        self.proposed_colors = self.current_colors.copy()

        for change in proposal.get("changes", []):
            key = change.get("color_key", "")
            new_val = change.get("new_value", "")

            # Validate: key must exist, value must be hex color
            if key in self.current_colors and re.match(r'^#[0-9a-fA-F]{6,8}$', new_val):
                self.changes.append(change)
                self.proposed_colors[key] = new_val

    def refine_proposal(self, user_feedback: str) -> Dict[str, Any]:
        """Refine the proposal based on user feedback."""
        current_changes = json.dumps(self.changes, indent=2, ensure_ascii=False) if self.changes else "Keine"

        prompt = f"""Der User hat Feedback:

"{user_feedback}"

BISHERIGE ÄNDERUNGEN:
{current_changes}

VERFÜGBARE FARBEN:
{json.dumps(dict(list(self.current_colors.items())[:15]), indent=2)}

Passe an. Ausgabe als JSON mit "summary" und "changes" Array."""

        response = self.claude.chat(prompt)

        try:
            for pattern in [r'```json\s*([\s\S]*?)\s*```', r'(\{[\s\S]*"changes"[\s\S]*\})']:
                match = re.search(pattern, response)
                if match:
                    proposal = json.loads(match.group(1))
                    self._process_proposal(proposal)
                    return proposal
        except (json.JSONDecodeError, AttributeError):
            pass

        return {"summary": response[:500], "changes": self.changes}

    def apply_changes(self) -> Tuple[bool, str]:
        """Apply the proposed color changes to chat_overlay.py."""
        if not self.changes:
            return False, "Keine Änderungen zum Anwenden"

        if not CHAT_OVERLAY_PY.exists():
            return False, f"chat_overlay.py nicht gefunden: {CHAT_OVERLAY_PY}"

        try:
            # Read current file
            content = CHAT_OVERLAY_PY.read_text(encoding="utf-8")

            # Backup
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = BACKUP_DIR / f"chat_overlay_backup_{timestamp}.py"
            backup_path.write_text(content, encoding="utf-8")
            LOG.info(f"Backup saved: {backup_path}")

            # Apply each change
            modified = content
            applied_count = 0

            for change in self.changes:
                key = change.get("color_key", "")
                old_val = change.get("old_value", "")
                new_val = change.get("new_value", "")

                if not key or not new_val:
                    continue

                # Pattern to find the specific color definition
                pattern = rf'("{key}":\s*)"#[0-9a-fA-F]{{6,8}}"'
                replacement = rf'\1"{new_val}"'

                new_modified, count = re.subn(pattern, replacement, modified)
                if count > 0:
                    modified = new_modified
                    applied_count += 1
                    LOG.info(f"Changed {key}: {old_val} -> {new_val}")

            if applied_count == 0:
                return False, "Keine Änderungen konnten angewendet werden"

            # Write modified file
            CHAT_OVERLAY_PY.write_text(modified, encoding="utf-8")

            # Save proposed colors for reference
            COLORS_CONFIG.write_text(
                json.dumps(self.proposed_colors, indent=2, ensure_ascii=False),
                encoding="utf-8"
            )

            # Trigger reload
            self._trigger_reload()

            return True, f"{applied_count} Farbänderungen angewendet! Overlay wird neu geladen..."

        except PermissionError:
            return False, "Keine Schreibberechtigung für chat_overlay.py"
        except Exception as e:
            LOG.error(f"Failed to apply changes: {e}")
            return False, f"Fehler: {e}"

    def _trigger_reload(self):
        """Trigger the chat_overlay to reload (restart it)."""
        try:
            # Find and restart chat_overlay
            result = subprocess.run(
                ["pgrep", "-f", "chat_overlay.py"],
                capture_output=True,
                text=True,
                timeout=5
            )

            if result.stdout.strip():
                pids = result.stdout.strip().split()
                for pid_str in pids:
                    try:
                        pid = int(pid_str)
                        # Send SIGHUP for reload, not SIGKILL
                        subprocess.run(["kill", "-HUP", str(pid)], timeout=5)
                        LOG.info(f"Sent reload signal to chat_overlay (PID {pid})")
                    except (ValueError, subprocess.TimeoutExpired):
                        continue

        except Exception as e:
            LOG.debug(f"Could not trigger reload: {e}")

    def get_preview_diff(self) -> str:
        """Get a visual diff of the changes."""
        if not self.changes:
            return "Keine Änderungen"

        lines = ["FARBÄNDERUNGEN:", "=" * 30]

        for i, change in enumerate(self.changes, 1):
            key = change.get("color_key", "???")
            old = change.get("old_value", "???")
            new = change.get("new_value", "???")
            reason = change.get("reason", "")

            lines.append(f"\n{i}. {key}")
            lines.append(f"   ALT: {old}")
            lines.append(f"   NEU: {new}")
            if reason:
                lines.append(f"   → {reason}")

        return "\n".join(lines)

    def rollback(self) -> Tuple[bool, str]:
        """Rollback to the most recent backup."""
        backups = sorted(BACKUP_DIR.glob("chat_overlay_backup_*.py"), reverse=True)

        if not backups:
            return False, "Keine Backups vorhanden"

        try:
            backup_content = backups[0].read_text(encoding="utf-8")
            CHAT_OVERLAY_PY.write_text(backup_content, encoding="utf-8")

            # Reload colors
            self._load_current_colors()
            self._trigger_reload()

            return True, f"Rollback zu {backups[0].name} erfolgreich"
        except Exception as e:
            return False, f"Rollback fehlgeschlagen: {e}"


# Quick test
if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)

    proposer = DesignProposer()

    print("=== Design Proposer Test ===")
    print(f"Loaded {len(proposer.current_colors)} colors")

    for key, val in list(proposer.current_colors.items())[:5]:
        print(f"  {key}: {val}")
