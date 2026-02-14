"""
Frank Skill System — Dynamic plugin loader and registry.

Supports TWO skill formats:

1. Frank Native (.py):
   Drop a .py file with a SKILL dict and run() function.

   SKILL = {
       "name": "my_skill",
       "description": "What it does",
       "keywords": ["trigger", "words"],
       "parameters": [{"name": "arg", "type": "string", "required": False}],
       "timeout_s": 10.0,
       "risk_level": 0.0,
   }

   def run(**kwargs) -> dict:
       return {"ok": True, "output": "result text"}

2. OpenClaw Compatible (SKILL.md):
   Drop a subdirectory with a SKILL.md file (YAML frontmatter + instructions).
   These are LLM-mediated: instructions are injected into LLM context.

   ---
   name: my_skill
   description: What it does
   keywords: [trigger, words]
   user-invocable: true
   ---
   # Instructions for the LLM
   When the user asks about X, do Y...
"""

import concurrent.futures
import importlib.util
import json
import logging
import os
import re
import shutil
import subprocess
import threading
import time
import urllib.request
from pathlib import Path
from typing import Callable, Dict, List, Optional

LOG = logging.getLogger("skills")

SKILLS_DIR = Path(__file__).parent
REQUIRED_SKILL_KEYS = {"name", "description"}

# Core API for OpenClaw LLM-mediated skills
CORE_API_URL = "http://127.0.0.1:8088/v1/chat/completions"

# ── Security scanning patterns ────────────────────────────────────

_DANGEROUS_PATTERNS = [
    (r"\bsubprocess\b", "subprocess execution"),
    (r"\bos\.system\b", "os.system execution"),
    (r"\beval\s*\(", "eval() call"),
    (r"\bexec\s*\(", "exec() call"),
    (r"\b__import__\b", "__import__ call"),
    (r"\bsudo\b", "sudo usage"),
    (r"\brm\s+-rf\b", "rm -rf command"),
    (r"\bshutil\.rmtree\b", "directory deletion"),
    (r"\bopen\s*\([^)]*[\"'][wax]", "file write operation"),
    (r"\burllib\.request\.urlopen\b", "network access"),
    (r"\brequests\.\b", "requests library"),
    (r"\bcurl\s+", "curl command"),
    (r"\bwget\s+", "wget command"),
]

_INJECTION_PATTERNS = [
    (r"ignore\s+(?:all\s+)?previous\s+instructions", "prompt injection: ignore instructions"),
    (r"you\s+are\s+now\s+", "prompt injection: role override"),
    (r"<\|im_start\|>", "prompt injection: ChatML injection"),
    (r"\[INST\]|\[/INST\]", "prompt injection: instruct format"),
    (r"system\s*:\s*you\s+are", "prompt injection: system prompt"),
]


# ---------- YAML Frontmatter Parser (no pyyaml dependency) ----------

def _parse_frontmatter(text: str) -> tuple:
    """Parse YAML frontmatter from SKILL.md. Returns (meta_dict, body_text)."""
    text = text.strip()
    if not text.startswith("---"):
        return {}, text

    end = text.find("---", 3)
    if end == -1:
        return {}, text

    yaml_block = text[3:end].strip()
    body = text[end + 3:].strip()

    meta = {}
    for line in yaml_block.split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        key = key.strip()
        val = val.strip()

        # Parse arrays: [a, b, c]
        if val.startswith("[") and val.endswith("]"):
            items = [item.strip().strip("'\"") for item in val[1:-1].split(",")]
            meta[key] = [i for i in items if i]
        # Parse booleans
        elif val.lower() in ("true", "yes"):
            meta[key] = True
        elif val.lower() in ("false", "no"):
            meta[key] = False
        # Parse numbers
        elif val.replace(".", "", 1).isdigit():
            meta[key] = float(val) if "." in val else int(val)
        # String (strip quotes)
        else:
            meta[key] = val.strip("'\"")

    return meta, body


def _check_requirements(meta: dict) -> list:
    """Check if OpenClaw skill requirements are met. Returns list of missing items."""
    missing = []
    requires = meta.get("requires", {})
    if isinstance(requires, dict):
        # Check binary dependencies
        bins = requires.get("bins", [])
        if isinstance(bins, list):
            for b in bins:
                if not shutil.which(b):
                    missing.append(f"bin:{b}")
        # Check environment variables
        env = requires.get("env", [])
        if isinstance(env, list):
            import os
            for e in env:
                if not os.environ.get(e):
                    missing.append(f"env:{e}")
    return missing


# ---------- Loaded Skill ----------

class LoadedSkill:
    """A validated, loaded skill."""
    __slots__ = (
        "name", "meta", "run_fn", "module_path", "load_ts",
        "keyword_re", "skill_type", "instructions",
    )

    def __init__(self, name: str, meta: dict, run_fn: Callable,
                 module_path: str, skill_type: str = "native",
                 instructions: str = ""):
        self.name = name
        self.meta = meta
        self.run_fn = run_fn
        self.module_path = module_path
        self.load_ts = time.time()
        self.skill_type = skill_type  # "native" or "openclaw"
        self.instructions = instructions  # SKILL.md body for openclaw

        # Build keyword regex from keywords list
        keywords = meta.get("keywords", [])
        if keywords:
            escaped = [re.escape(kw) for kw in keywords]
            self.keyword_re = re.compile(
                r"(?:" + "|".join(escaped) + r")", re.IGNORECASE
            )
        else:
            self.keyword_re = None


# ---------- OpenClaw LLM Runner ----------

def _openclaw_run(instructions: str, user_query: str = "", **kwargs) -> dict:
    """Execute an OpenClaw skill by sending instructions + query to the LLM."""
    system_prompt = (
        "Du bist Frank, ein hilfreicher KI-Assistent. "
        "Befolge die folgenden Skill-Anweisungen genau:\n\n"
        + instructions
    )
    messages = [
        {"role": "system", "content": system_prompt},
    ]
    if user_query:
        messages.append({"role": "user", "content": user_query})
    else:
        messages.append({"role": "user", "content": "Fuehre den Skill aus."})

    try:
        payload = json.dumps({
            "model": "llama3",
            "messages": messages,
            "max_tokens": 500,
            "temperature": 0.3,
        }).encode()

        req = urllib.request.Request(
            CORE_API_URL,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())

        # Extract response text
        choices = data.get("choices", [])
        if choices:
            text = choices[0].get("message", {}).get("content", "")
            if text:
                return {"ok": True, "output": text, "skill_type": "openclaw"}

        return {"ok": False, "error": "No response from LLM"}

    except Exception as e:
        return {"ok": False, "error": f"OpenClaw skill error: {e}"}


# ---------- Skill Registry ----------

class SkillRegistry:
    """Thread-safe skill registry with hot-reload. Supports native + OpenClaw."""

    def __init__(self):
        self._skills: Dict[str, LoadedSkill] = {}
        self._lock = threading.Lock()

    def scan_and_load(self) -> int:
        """Scan skills directory: .py files + subdirectories with SKILL.md."""
        count = 0

        # 1. Native Python skills (.py files in skills/)
        for path in sorted(SKILLS_DIR.glob("*.py")):
            if path.name.startswith("_"):
                continue
            skill = self._load_native(path)
            if skill:
                with self._lock:
                    self._skills[skill.name] = skill
                count += 1

        # 2. OpenClaw skills (subdirectories with SKILL.md)
        for subdir in sorted(SKILLS_DIR.iterdir()):
            if not subdir.is_dir():
                continue
            if subdir.name.startswith(("_", ".")):
                continue
            skill_md = subdir / "SKILL.md"
            if skill_md.exists():
                skill = self._load_openclaw(skill_md)
                if skill:
                    with self._lock:
                        self._skills[skill.name] = skill
                    count += 1

        return count

    def _load_native(self, path: Path) -> Optional[LoadedSkill]:
        """Load and validate a native Python skill file."""
        stem = path.stem
        try:
            spec = importlib.util.spec_from_file_location(f"skills.{stem}", path)
            if not spec or not spec.loader:
                LOG.warning(f"Skill: cannot load {path.name}")
                return None

            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)

            skill_meta = getattr(mod, "SKILL", None)
            if not isinstance(skill_meta, dict):
                LOG.warning(f"Skill {stem}: missing SKILL dict")
                return None

            missing = REQUIRED_SKILL_KEYS - set(skill_meta.keys())
            if missing:
                LOG.warning(f"Skill {stem}: SKILL dict missing keys: {missing}")
                return None

            run_fn = getattr(mod, "run", None)
            if not callable(run_fn):
                LOG.warning(f"Skill {stem}: missing run() function")
                return None

            name = skill_meta["name"]
            LOG.info(f"Skill loaded (native): {name} ({path.name})")
            return LoadedSkill(name, skill_meta, run_fn, str(path), "native")

        except Exception as e:
            LOG.error(f"Skill {stem}: load error: {e}")
            return None

    def _load_openclaw(self, skill_md: Path) -> Optional[LoadedSkill]:
        """Load and validate an OpenClaw SKILL.md skill."""
        dir_name = skill_md.parent.name
        try:
            text = skill_md.read_text(encoding="utf-8")
            meta, body = _parse_frontmatter(text)

            if not meta.get("name"):
                meta["name"] = dir_name
            if not meta.get("description"):
                LOG.warning(f"OpenClaw skill {dir_name}: missing description")
                return None

            if not body.strip():
                LOG.warning(f"OpenClaw skill {dir_name}: empty instructions body")
                return None

            # Check requirements
            missing_reqs = _check_requirements(meta)
            if missing_reqs:
                LOG.warning(
                    f"OpenClaw skill {dir_name}: missing requirements: "
                    + ", ".join(missing_reqs)
                )
                return None

            name = meta["name"]
            # Create a closure that captures the instructions
            instructions = body

            def run_fn(user_query: str = "", **kw):
                return _openclaw_run(instructions, user_query, **kw)

            LOG.info(f"Skill loaded (openclaw): {name} ({dir_name}/SKILL.md)")
            return LoadedSkill(
                name, meta, run_fn, str(skill_md),
                "openclaw", instructions
            )

        except Exception as e:
            LOG.error(f"OpenClaw skill {dir_name}: load error: {e}")
            return None

    def get(self, name: str) -> Optional[LoadedSkill]:
        """Get skill by name."""
        with self._lock:
            return self._skills.get(name)

    def list_all(self) -> List[LoadedSkill]:
        """List all loaded skills."""
        with self._lock:
            return list(self._skills.values())

    def match_keywords(self, text: str) -> Optional[LoadedSkill]:
        """Match user input against skill keyword patterns. Returns first match."""
        with self._lock:
            for skill in self._skills.values():
                if skill.keyword_re and skill.keyword_re.search(text):
                    return skill
        return None

    def reload(self, name: str = None) -> int:
        """Reload one skill or all skills. Returns count reloaded."""
        if name:
            with self._lock:
                skill = self._skills.get(name)
            if not skill:
                return 0
            path = Path(skill.module_path)
            if skill.skill_type == "openclaw":
                loaded = self._load_openclaw(path)
            else:
                loaded = self._load_native(path)
            if loaded:
                with self._lock:
                    self._skills[name] = loaded
                return 1
            return 0
        else:
            with self._lock:
                self._skills.clear()
            return self.scan_and_load()

    def get_skills_summary(self, for_prompt: bool = False) -> str:
        """Human-readable summary of all installed skills.

        Args:
            for_prompt: If True, return compact version for LLM context injection.
        """
        skills = self.list_all()
        if not skills:
            return "Keine Skills installiert."

        if for_prompt:
            # Compact: "weather (native), clipboard (native), summarize (openclaw)"
            parts = [f"{s.name} ({s.skill_type})" for s in skills]
            return ", ".join(parts)

        lines = []
        for s in skills:
            desc = s.meta.get("description", "")
            typ = "Python" if s.skill_type == "native" else "OpenClaw"
            keywords = s.meta.get("keywords", [])
            kw_str = ", ".join(keywords[:5]) if keywords else "-"
            lines.append(f"  {s.name} [{typ}]: {desc}\n    Keywords: {kw_str}")
        return f"Installierte Skills ({len(skills)}):\n" + "\n".join(lines)

    def browse_marketplace(self, query: str = "", limit: int = 20) -> dict:
        """Browse OpenClaw ClawHub marketplace. Returns available skills."""
        try:
            url = "https://clawhub.ai/api/v1/skills?sort=downloads"
            if query:
                # Extract search terms from natural language query
                clean = re.sub(
                    r"(openclaw|skills?|verfuegbare?|verfügbare?|zeig|mir|"
                    r"store|marketplace|neue|suchen|finden)", "", query,
                    flags=re.IGNORECASE
                ).strip()
                if clean:
                    url = f"https://clawhub.ai/api/v1/search?q={urllib.request.quote(clean)}"

            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Frank/1.0", "Accept": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())

            # Get installed skill names for filtering
            installed = {s.name for s in self.list_all()}

            skills = []
            # ClawHub returns {"items": [...]} with slug, displayName, summary, stats
            items = (data.get("items", []) if isinstance(data, dict)
                     else data if isinstance(data, list) else [])
            for item in items:
                if not isinstance(item, dict):
                    continue
                slug = item.get("slug", "")
                name = item.get("displayName", slug)
                if not slug or slug in installed:
                    continue
                stats = item.get("stats", {})
                skills.append({
                    "name": name,
                    "slug": slug,
                    "description": item.get("summary", ""),
                    "downloads": stats.get("downloads", 0),
                })
                if len(skills) >= limit:
                    break

            return {"ok": True, "skills": skills, "count": len(skills)}

        except Exception as e:
            LOG.error(f"Marketplace browse error: {e}")
            return {"ok": False, "error": f"Marketplace nicht erreichbar: {e}", "skills": []}

    def install_from_marketplace(self, slug: str) -> dict:
        """Download and install a skill from ClawHub marketplace."""
        import io
        import zipfile

        if not slug:
            return {"ok": False, "error": "Kein Skill-Name angegeben"}

        # Sanitize slug
        slug = re.sub(r"[^a-zA-Z0-9_-]", "", slug.strip().lower())
        if not slug:
            return {"ok": False, "error": "Ungueltiger Skill-Name"}

        # Check if already installed
        if self.get(slug):
            return {"ok": False, "error": f"Skill '{slug}' ist bereits installiert"}

        try:
            # Fetch skill metadata
            meta_url = f"https://clawhub.ai/api/v1/skills/{slug}"
            req = urllib.request.Request(
                meta_url,
                headers={"User-Agent": "Frank/1.0", "Accept": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                meta_resp = json.loads(resp.read())

            skill_data = meta_resp.get("skill", meta_resp)
            skill_name = skill_data.get("displayName", slug)
            skill_desc = skill_data.get("summary", "")

            # Download skill zip
            dl_url = f"https://clawhub.ai/api/v1/download?slug={slug}&tag=latest"
            req = urllib.request.Request(
                dl_url, headers={"User-Agent": "Frank/1.0"},
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                zip_data = resp.read()

            # Extract SKILL.md from zip
            skill_md_content = None
            with zipfile.ZipFile(io.BytesIO(zip_data)) as zf:
                for name in zf.namelist():
                    if name == "SKILL.md" or name.endswith("/SKILL.md"):
                        skill_md_content = zf.read(name).decode("utf-8")
                        break

            if not skill_md_content or not skill_md_content.strip():
                return {"ok": False, "error": f"Skill '{slug}' enthaelt keine SKILL.md"}

            # Create skill directory and save SKILL.md
            skill_dir = SKILLS_DIR / slug
            skill_dir.mkdir(exist_ok=True)
            skill_md = skill_dir / "SKILL.md"
            skill_md.write_text(skill_md_content, encoding="utf-8")

            LOG.info(f"Skill '{slug}' downloaded to {skill_dir}")

            # Security scan before loading
            scan = self._security_scan_skill(skill_md)
            if not scan["safe"]:
                warnings_text = "; ".join(scan["warnings"][:5])
                LOG.warning(f"Skill '{slug}' security scan: {warnings_text}")
                if scan["risk_level"] >= 0.6:
                    shutil.rmtree(skill_dir, ignore_errors=True)
                    return {
                        "ok": False,
                        "error": (
                            f"Skill '{slug}' blockiert (Sicherheitsrisiko {scan['risk_level']:.1f}):\n"
                            f"{warnings_text}"
                        ),
                    }
                # Medium risk — install with warning
                skill_desc += f"\n\u26a0 Sicherheitshinweis: {warnings_text}"

            # Load the new skill
            loaded = self._load_openclaw(skill_md)
            if loaded:
                with self._lock:
                    self._skills[loaded.name] = loaded
                LOG.info(f"Skill '{loaded.name}' installed and active")
                return {
                    "ok": True,
                    "name": loaded.name,
                    "description": skill_desc,
                    "message": f"Skill '{loaded.name}' erfolgreich installiert!\n{skill_desc}",
                }
            else:
                return {
                    "ok": False,
                    "error": f"Skill '{slug}' heruntergeladen aber konnte nicht geladen werden",
                }

        except urllib.request.HTTPError as e:
            if e.code == 404:
                return {"ok": False, "error": f"Skill '{slug}' nicht im Marketplace gefunden"}
            return {"ok": False, "error": f"HTTP-Fehler: {e.code} {e.reason}"}
        except Exception as e:
            LOG.error(f"Skill install error: {e}")
            return {"ok": False, "error": f"Installation fehlgeschlagen: {e}"}

    # ── Security Scanning ──────────────────────────────────────

    def _security_scan_skill(self, skill_md_path: Path) -> dict:
        """Scan a SKILL.md for dangerous patterns before loading.

        Returns:
            {"safe": bool, "warnings": [str], "risk_level": float}
        """
        try:
            content = skill_md_path.read_text(encoding="utf-8")
        except Exception:
            return {"safe": True, "warnings": [], "risk_level": 0.0}

        warnings = []

        for pattern, desc in _DANGEROUS_PATTERNS:
            if re.search(pattern, content, re.IGNORECASE):
                warnings.append(desc)

        for pattern, desc in _INJECTION_PATTERNS:
            if re.search(pattern, content, re.IGNORECASE):
                warnings.append(desc)

        risk = min(1.0, len(warnings) * 0.3)
        return {
            "safe": len(warnings) == 0,
            "warnings": warnings,
            "risk_level": risk,
        }

    # ── Uninstall ─────────────────────────────────────────────

    def uninstall(self, name_or_slug: str) -> dict:
        """Uninstall an OpenClaw skill by name or slug.

        Removes the skill directory and unregisters from the registry.
        Native .py skills cannot be uninstalled (refuse).
        """
        name_or_slug = name_or_slug.strip().lower()

        # Find skill — exact match first, then partial
        skill = self.get(name_or_slug)
        if not skill:
            with self._lock:
                for sname, s in self._skills.items():
                    if name_or_slug in sname.lower():
                        skill = s
                        break

        if not skill:
            return {"ok": False, "error": f"Skill '{name_or_slug}' nicht gefunden"}

        if skill.skill_type == "native":
            return {"ok": False, "error": f"Native Skills (.py) koennen nicht deinstalliert werden"}

        # Remove directory
        skill_dir = Path(skill.module_path).parent
        if skill_dir.exists() and skill_dir != SKILLS_DIR:
            shutil.rmtree(skill_dir, ignore_errors=True)
            LOG.info(f"Skill directory removed: {skill_dir}")

        # Unregister
        with self._lock:
            self._skills.pop(skill.name, None)

        LOG.info(f"Skill uninstalled: {skill.name}")
        return {"ok": True, "name": skill.name, "message": f"Skill '{skill.name}' deinstalliert."}

    # ── Update Check ──────────────────────────────────────────

    def check_updates(self) -> dict:
        """Check installed OpenClaw skills against marketplace for updates.

        Compares installed version with latest marketplace version.
        Returns list of skills with available updates.
        """
        updates = []
        installed_openclaw = [s for s in self.list_all() if s.skill_type == "openclaw"]

        for skill in installed_openclaw:
            slug = skill.name
            try:
                url = f"https://clawhub.ai/api/v1/skills/{slug}"
                req = urllib.request.Request(url, headers={"User-Agent": "Frank/1.0"})
                with urllib.request.urlopen(req, timeout=5) as resp:
                    data = json.loads(resp.read())

                skill_data = data.get("skill", data)
                remote_version = str(skill_data.get("version", ""))
                local_version = str(skill.meta.get("version", ""))

                if remote_version and remote_version != local_version:
                    updates.append({
                        "name": skill.name,
                        "current_version": local_version or "unbekannt",
                        "latest_version": remote_version,
                        "slug": slug,
                    })
            except Exception:
                continue

        return {"ok": True, "updates": updates, "count": len(updates)}

    # ── Execution ─────────────────────────────────────────────

    def execute(self, name: str, params: dict, timeout_s: float = None) -> dict:
        """Execute a skill with timeout protection."""
        skill = self.get(name)
        if not skill:
            return {"ok": False, "error": f"Skill '{name}' not found"}

        timeout = timeout_s or skill.meta.get("timeout_s", 15.0)
        # OpenClaw skills need more time (LLM round-trip)
        if skill.skill_type == "openclaw" and timeout < 30:
            timeout = 30.0

        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(skill.run_fn, **params)
                result = future.result(timeout=timeout)

            if not isinstance(result, dict):
                result = {"ok": True, "output": str(result)}
            return result

        except concurrent.futures.TimeoutError:
            return {"ok": False, "error": f"Skill '{name}' timed out after {timeout}s"}
        except TypeError as e:
            return {"ok": False, "error": f"Parameter error: {e}"}
        except Exception as e:
            return {"ok": False, "error": f"Skill error: {e}"}


# ---------- Singleton ----------

_registry: Optional[SkillRegistry] = None
_registry_lock = threading.Lock()


def get_skill_registry() -> SkillRegistry:
    """Get or create the global SkillRegistry singleton."""
    global _registry
    if _registry is None:
        with _registry_lock:
            if _registry is None:
                _registry = SkillRegistry()
                count = _registry.scan_and_load()
                LOG.info(f"Skill system: {count} skills loaded from {SKILLS_DIR}")
    return _registry
