"""
Package Manager -- unified package management for Frank.

Supports apt (via E-SMC Sovereign), pip (--user only), snap, flatpak.
All installations require user confirmation via the approval queue.
"""

import json
import logging
import re
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Tuple

LOG = logging.getLogger("system_control.package_manager")

try:
    from config.paths import SYSTEM_CONTROL_DIR
    INSTALL_LOG = SYSTEM_CONTROL_DIR / "install_log.json"
except ImportError:
    INSTALL_LOG = Path("/home/ai-core-node/aicore/database/system_control/install_log.json")


class PackageBackend(Enum):
    APT = "apt"
    PIP = "pip"
    SNAP = "snap"
    FLATPAK = "flatpak"


@dataclass
class PackageInfo:
    name: str
    version: str = ""
    description: str = ""
    size_human: str = ""
    backend: PackageBackend = PackageBackend.APT
    installed: bool = False


BLACKLISTED_PACKAGES = frozenset({
    "linux-kernel", "linux-image", "systemd", "grub", "grub-pc", "grub-common",
    "libc6", "libstdc++6", "apt", "dpkg", "bash", "sudo",
    "python3", "python3-minimal", "init", "login", "passwd",
})

MAX_PACKAGES_PER_REQUEST = 5


class PackageManager:
    """Unified package manager with safety guardrails."""

    def __init__(self):
        self._lock = threading.Lock()
        INSTALL_LOG.parent.mkdir(parents=True, exist_ok=True)

    # === SEARCH ===

    def search(self, term: str, backend: Optional[PackageBackend] = None) -> List[PackageInfo]:
        """Search for packages across backends."""
        results = []
        backends = [backend] if backend else [PackageBackend.APT, PackageBackend.PIP]

        for b in backends:
            try:
                if b == PackageBackend.APT:
                    results.extend(self._search_apt(term))
                elif b == PackageBackend.PIP:
                    results.extend(self._search_pip(term))
                elif b == PackageBackend.SNAP:
                    results.extend(self._search_snap(term))
                elif b == PackageBackend.FLATPAK:
                    results.extend(self._search_flatpak(term))
            except Exception as e:
                LOG.warning(f"Search failed for {b.value}: {e}")

        return results[:10]

    def _search_apt(self, term: str) -> List[PackageInfo]:
        r = subprocess.run(["apt-cache", "search", term], capture_output=True, text=True, timeout=10)
        results = []
        for line in r.stdout.strip().splitlines()[:5]:
            parts = line.split(" - ", 1)
            if len(parts) == 2:
                results.append(PackageInfo(name=parts[0].strip(), description=parts[1].strip(), backend=PackageBackend.APT))
        return results

    def _search_pip(self, term: str) -> List[PackageInfo]:
        # pip doesn't have a great search; just check if the exact name exists
        r = subprocess.run(["pip", "index", "versions", term], capture_output=True, text=True, timeout=15)
        if r.returncode == 0 and term in r.stdout:
            return [PackageInfo(name=term, description="Python package", backend=PackageBackend.PIP)]
        return []

    def _search_snap(self, term: str) -> List[PackageInfo]:
        if not shutil.which("snap"):
            return []
        r = subprocess.run(["snap", "find", term], capture_output=True, text=True, timeout=15)
        results = []
        for line in r.stdout.strip().splitlines()[1:4]:  # skip header
            parts = line.split()
            if len(parts) >= 2:
                results.append(PackageInfo(name=parts[0], description=" ".join(parts[4:]) if len(parts) > 4 else "", backend=PackageBackend.SNAP))
        return results

    def _search_flatpak(self, term: str) -> List[PackageInfo]:
        if not shutil.which("flatpak"):
            return []
        r = subprocess.run(["flatpak", "search", term], capture_output=True, text=True, timeout=15)
        results = []
        for line in r.stdout.strip().splitlines()[:3]:
            parts = line.split("\t")
            if parts:
                results.append(PackageInfo(name=parts[0].strip(), description=parts[1].strip() if len(parts) > 1 else "", backend=PackageBackend.FLATPAK))
        return results

    # === INFO ===

    def get_info(self, package: str, backend: PackageBackend) -> Optional[PackageInfo]:
        """Get package info including size."""
        try:
            if backend == PackageBackend.APT:
                return self._apt_info(package)
        except Exception as e:
            LOG.warning(f"Info failed for {package}: {e}")
        return None

    def _apt_info(self, package: str) -> Optional[PackageInfo]:
        r = subprocess.run(["apt-cache", "show", package], capture_output=True, text=True, timeout=10)
        if r.returncode != 0:
            return None
        info = PackageInfo(name=package, backend=PackageBackend.APT)
        for line in r.stdout.splitlines():
            if line.startswith("Description:"):
                info.description = line.split(":", 1)[1].strip()
            elif line.startswith("Size:"):
                try:
                    size_b = int(line.split(":", 1)[1].strip())
                    if size_b > 1048576:
                        info.size_human = f"{size_b / 1048576:.1f} MB"
                    else:
                        info.size_human = f"{size_b / 1024:.0f} KB"
                except ValueError:
                    pass
            elif line.startswith("Version:"):
                info.version = line.split(":", 1)[1].strip()
        return info

    # === VALIDATE ===

    def validate(self, packages: List[str], backend: PackageBackend) -> Tuple[bool, str]:
        """Validate packages before install. Returns (ok, message)."""
        if len(packages) > MAX_PACKAGES_PER_REQUEST:
            return False, f"Max {MAX_PACKAGES_PER_REQUEST} Pakete pro Anfrage."

        for pkg in packages:
            if pkg.lower() in BLACKLISTED_PACKAGES:
                return False, f"Paket '{pkg}' ist geschuetzt und darf nicht veraendert werden."
            # Sanitize: only allow alphanumeric, dash, dot, underscore, plus
            if not re.match(r'^[a-zA-Z0-9._+\-]+$', pkg):
                return False, f"Ungueltiger Paketname: '{pkg}'"

        return True, ""

    # === INSTALL ===

    def install(self, packages: List[str], backend: PackageBackend) -> Tuple[bool, str]:
        """Execute installation. Only call after user approval."""
        ok, err = self.validate(packages, backend)
        if not ok:
            return False, err

        try:
            if backend == PackageBackend.APT:
                return self._install_apt(packages)
            elif backend == PackageBackend.PIP:
                return self._install_pip(packages)
            elif backend == PackageBackend.SNAP:
                return self._install_snap(packages)
            elif backend == PackageBackend.FLATPAK:
                return self._install_flatpak(packages)
        except Exception as e:
            return False, str(e)
        return False, "Unbekanntes Backend"

    def _install_apt(self, packages: List[str]) -> Tuple[bool, str]:
        # Try using E-SMC Sovereign if available
        try:
            from ext.sovereign.e_smc import propose_installation
            results = []
            for pkg in packages:
                ok, msg = propose_installation(pkg)
                results.append(f"{pkg}: {'OK' if ok else msg}")
            return all("OK" in r for r in results), "\n".join(results)
        except ImportError:
            pass

        # Fallback: direct apt
        pkg_str = " ".join(packages)
        r = subprocess.run(
            ["sudo", "apt-get", "install", "-y"] + packages,
            capture_output=True, text=True, timeout=300
        )
        self._log_action("install", packages, "apt", r.returncode == 0)
        if r.returncode == 0:
            return True, f"Installiert: {pkg_str}"
        return False, f"Fehler: {r.stderr[:300]}"

    def _install_pip(self, packages: List[str]) -> Tuple[bool, str]:
        r = subprocess.run(
            ["pip", "install", "--user"] + packages,
            capture_output=True, text=True, timeout=120
        )
        self._log_action("install", packages, "pip", r.returncode == 0)
        if r.returncode == 0:
            return True, f"Python-Pakete installiert: {', '.join(packages)}"
        return False, f"Fehler: {r.stderr[:300]}"

    def _install_snap(self, packages: List[str]) -> Tuple[bool, str]:
        if not shutil.which("snap"):
            return False, "Snap ist nicht installiert."
        results = []
        for pkg in packages:
            r = subprocess.run(["snap", "install", pkg], capture_output=True, text=True, timeout=120)
            results.append((pkg, r.returncode == 0, r.stderr[:200]))
        self._log_action("install", packages, "snap", all(ok for _, ok, _ in results))
        failed = [(p, e) for p, ok, e in results if not ok]
        if not failed:
            return True, f"Snap-Pakete installiert: {', '.join(packages)}"
        return False, f"Fehler: {'; '.join(f'{p}: {e}' for p, e in failed)}"

    def _install_flatpak(self, packages: List[str]) -> Tuple[bool, str]:
        if not shutil.which("flatpak"):
            return False, "Flatpak ist nicht installiert."
        results = []
        for pkg in packages:
            r = subprocess.run(["flatpak", "install", "-y", "flathub", pkg], capture_output=True, text=True, timeout=180)
            results.append((pkg, r.returncode == 0, r.stderr[:200]))
        self._log_action("install", packages, "flatpak", all(ok for _, ok, _ in results))
        failed = [(p, e) for p, ok, e in results if not ok]
        if not failed:
            return True, f"Flatpak-Pakete installiert: {', '.join(packages)}"
        return False, f"Fehler: {'; '.join(f'{p}: {e}' for p, e in failed)}"

    # === REMOVE ===

    def remove(self, packages: List[str], backend: PackageBackend) -> Tuple[bool, str]:
        """Execute removal. Only call after user approval."""
        ok, err = self.validate(packages, backend)
        if not ok:
            return False, err

        if backend == PackageBackend.APT:
            # Check reverse dependencies
            for pkg in packages:
                rdeps = self._check_rdeps(pkg)
                if rdeps:
                    return False, f"'{pkg}' wird von {len(rdeps)} anderen Paketen benoetigt: {', '.join(rdeps[:5])}"
            r = subprocess.run(["sudo", "apt-get", "remove", "-y"] + packages, capture_output=True, text=True, timeout=120)
            self._log_action("remove", packages, "apt", r.returncode == 0)
            return r.returncode == 0, r.stdout[:300] if r.returncode == 0 else r.stderr[:300]
        elif backend == PackageBackend.PIP:
            r = subprocess.run(["pip", "uninstall", "-y"] + packages, capture_output=True, text=True, timeout=60)
            self._log_action("remove", packages, "pip", r.returncode == 0)
            return r.returncode == 0, "Entfernt" if r.returncode == 0 else r.stderr[:300]
        elif backend == PackageBackend.SNAP:
            for pkg in packages:
                subprocess.run(["snap", "remove", pkg], capture_output=True, text=True, timeout=60)
            self._log_action("remove", packages, "snap", True)
            return True, f"Snap-Pakete entfernt: {', '.join(packages)}"
        elif backend == PackageBackend.FLATPAK:
            for pkg in packages:
                subprocess.run(["flatpak", "uninstall", "-y", pkg], capture_output=True, text=True, timeout=60)
            self._log_action("remove", packages, "flatpak", True)
            return True, f"Flatpak-Pakete entfernt: {', '.join(packages)}"
        return False, "Unbekanntes Backend"

    def _check_rdeps(self, package: str) -> List[str]:
        r = subprocess.run(["apt-cache", "rdepends", "--installed", package], capture_output=True, text=True, timeout=10)
        deps = []
        for line in r.stdout.strip().splitlines()[2:]:  # skip header lines
            dep = line.strip()
            if dep and not dep.startswith("|"):
                deps.append(dep)
        return deps

    # === SYSTEM UPDATE ===

    def check_updates(self) -> Tuple[int, str]:
        """Run apt update and return count of upgradeable packages."""
        subprocess.run(["sudo", "apt-get", "update", "-qq"], capture_output=True, text=True, timeout=120)
        r = subprocess.run(["apt", "list", "--upgradeable"], capture_output=True, text=True, timeout=30)
        lines = [l for l in r.stdout.strip().splitlines() if "/" in l]
        if not lines:
            return 0, "System ist aktuell."
        summary = "\n".join(lines[:15])
        if len(lines) > 15:
            summary += f"\n... und {len(lines) - 15} weitere"
        return len(lines), f"{len(lines)} Aktualisierungen verfuegbar:\n{summary}"

    def execute_update(self) -> Tuple[bool, str]:
        """Execute system update after confirmation."""
        r = subprocess.run(["sudo", "apt-get", "upgrade", "-y"], capture_output=True, text=True, timeout=600)
        self._log_action("update", ["system"], "apt", r.returncode == 0)
        if r.returncode == 0:
            return True, "System wurde aktualisiert."
        return False, f"Update-Fehler: {r.stderr[:300]}"

    # === DETECT BACKEND ===

    def detect_backend(self, message: str) -> PackageBackend:
        """Detect package backend from user message context."""
        low = message.lower()
        if any(w in low for w in ("python", "pip", "bibliothek", "library", "modul")):
            return PackageBackend.PIP
        if "snap" in low:
            return PackageBackend.SNAP
        if "flatpak" in low:
            return PackageBackend.FLATPAK
        return PackageBackend.APT

    def extract_packages(self, message: str) -> List[str]:
        """Extract package names from user message."""
        # Remove common command words
        cleaned = re.sub(
            r'(installier[e]?|install|deinstallier[e]?|uninstall|entfern[e]?|remove|'
            r'such[e]?|search|paket[e]?|package[s]?|programm[e]?|'
            r'apt|pip|snap|flatpak|bitte|mal|mir|das|die|den|fuer mich)',
            '', message, flags=re.IGNORECASE
        ).strip()
        # Split remaining words, filter empty
        packages = [w.strip() for w in cleaned.split() if w.strip() and len(w.strip()) > 1]
        return packages[:MAX_PACKAGES_PER_REQUEST]

    # === LOGGING ===

    def _log_action(self, action: str, packages: List[str], backend: str, success: bool):
        try:
            log_data = []
            if INSTALL_LOG.exists():
                try:
                    log_data = json.loads(INSTALL_LOG.read_text())
                except (json.JSONDecodeError, OSError):
                    pass
            log_data.append({
                "action": action,
                "packages": packages,
                "backend": backend,
                "success": success,
                "timestamp": time.time(),
            })
            # Keep last 500 entries
            log_data = log_data[-500:]
            INSTALL_LOG.write_text(json.dumps(log_data, indent=2))
        except Exception as e:
            LOG.warning(f"Failed to log action: {e}")


# Singleton
_manager: Optional[PackageManager] = None

def get_manager() -> PackageManager:
    global _manager
    if _manager is None:
        _manager = PackageManager()
    return _manager
