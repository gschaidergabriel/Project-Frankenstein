"""IO worker methods – web search, file ingest, filesystem ops, Steam integration, USB management."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from overlay.constants import LOG, FRANK_IDENTITY, DEFAULT_TIMEOUT_S
from overlay.services.core_api import _core_chat
from overlay.services.search import (
    _search_web, _search_darknet, _fetch_url, _format_fetched_content,
    _read_rss_feed, _format_rss_result,
    _get_news, _format_news_result, _detect_news_category,
)
from overlay.services.toolbox import (
    _list_files, _move_file, _copy_file, _delete_file,
    _usb_storage, _usb_mount, _usb_unmount, _usb_eject,
)
from overlay.file_utils import _format_file_list, _try_ingest_upload


class IOWorkersMixin:
    """Web search, file ingest, filesystem listing/actions, and Steam integration workers."""

    def _do_search_worker(self, query: str, limit: int = 8, voice: bool = False):
        self._ui_call(self._show_typing)
        res = _search_web(query, limit=limit)
        self._pending_results = res
        self._ui_call(self._hide_typing)

        if not res:
            self._ui_call(lambda: self._add_message("Frank", "No results found.", is_system=True))
        elif len(res) == 1:
            self._ui_call(lambda: self._add_message("Frank", "1 result found. Opening automatically.", is_system=True))
            self._io_q.put(("open", res[0].url))
        else:
            self._ui_call(lambda r=res: self._add_message("Frank", f"{len(r)} results found.", is_system=True))
            self._ui_call(lambda r=res: self._render_results(r))

    def _do_darknet_search_worker(self, query: str, limit: int = 8):
        """Search the darknet via Torch (.onion search engine through Tor)."""
        self._ui_call(self._show_typing)
        res = _search_darknet(query, limit=limit)
        self._pending_results = res
        # Mark results as darknet for opening in Tor Browser
        self._pending_darknet = True
        self._ui_call(self._hide_typing)

        if not res:
            self._ui_call(lambda: self._add_message(
                "Frank", "No darknet results found. Check your Tor connection.", is_system=True))
        else:
            self._ui_call(lambda r=res: self._add_message(
                "Frank", f"{len(r)} darknet results found.", is_system=True))
            self._ui_call(lambda r=res: self._render_darknet_results(r))

    def _do_ingest_worker(self, path: Path):
        ok, msg = _try_ingest_upload(path)
        # Provide brief feedback
        if ok:
            fname = path.name if hasattr(path, 'name') else str(path).split('/')[-1]
            self._ui_call(lambda f=fname: self._add_message("Frank", f"File '{f}' processed.", is_system=True))

    def _do_fs_list_worker(self, path: str, user_query: str = "", voice: bool = False):
        """List files in a directory and provide natural response via LLM."""
        self._ui_call(self._show_typing)

        result = _list_files(path)
        formatted = _format_file_list(result, path)

        # Always route through LLM for natural response
        prompt = (
            f"[Identity: {FRANK_IDENTITY}]\n\n"
            f"The user asks: '{user_query or path}'\n\n"
            f"Here is the filesystem data:\n{formatted}\n\n"
            f"Answer the user's question based on this data. "
            f"Be specific and helpful."
        )

        try:
            res = _core_chat(prompt, max_tokens=500, timeout_s=60, task="chat.fast", force="llama")
            reply = (res.get("text") or "").strip() if res.get("ok") else formatted
        except Exception:
            reply = formatted  # Fallback to raw data

        self._ui_call(self._hide_typing)
        if voice:
            self._ui_call(lambda r=reply: self._voice_respond(r))
        else:
            self._ui_call(lambda r=reply: self._add_message("Frank", r))

    def _do_fs_action_worker(self, action: str, params: Dict[str, Any]):
        """Execute a filesystem action (move, copy, delete)."""
        self._ui_call(self._show_typing)

        result = None
        if action == "move":
            result = _move_file(params["src"], params["dst"])
            action_desc = f"Moving {params['src']} to {params['dst']}"
        elif action == "copy":
            result = _copy_file(params["src"], params["dst"])
            action_desc = f"Copying {params['src']} to {params['dst']}"
        elif action == "delete":
            result = _delete_file(params["path"])
            action_desc = f"Deleting {params['path']}"
        else:
            action_desc = "Unknown action"

        self._ui_call(self._hide_typing)

        if result and result.get("ok"):
            self._ui_call(lambda a=action_desc: self._add_message("Frank", f"Success: {a}", is_system=True))
        else:
            error = result.get("error", "Unknown error") if result else "No response"
            self._ui_call(lambda a=action_desc, e=error: self._add_message("Frank", f"Error during {a}: {e}", is_system=True))

    # ---------- Local File Search ----------

    def _do_file_search_worker(self, query: str):
        """Fast local file search using find. Results have clickable file:// links."""
        import subprocess
        self._ui_call(self._show_typing)

        home = str(Path.home())
        search_paths = [home, "/tmp", "/opt"]
        # Only include paths that exist
        search_paths = [p for p in search_paths if Path(p).is_dir()]

        cmd = [
            "find", *search_paths,
            "-maxdepth", "8",
            "-iname", f"*{query}*",
            "-not", "-path", "*/.*",
            "-not", "-path", "*/snap/*",
            "-not", "-path", "*/__pycache__/*",
            "-not", "-path", "*/node_modules/*",
            "-not", "-path", "*/venv/*",
            "-not", "-path", "*/.venv/*",
        ]

        try:
            proc = subprocess.run(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                text=True, timeout=10,
            )
            raw = proc.stdout.strip()
            results = [line for line in raw.split("\n") if line][:20]
        except subprocess.TimeoutExpired:
            results = []
            self._ui_call(self._hide_typing)
            self._ui_call(lambda q=query: self._add_message(
                "Frank", f"Search timed out for \"{q}\". Try a more specific name.",
                is_system=True))
            return
        except Exception as e:
            LOG.error(f"File search error: {e}")
            results = []

        self._ui_call(self._hide_typing)

        if results:
            lines = [f"Found {len(results)} file(s) matching \"{query}\":\n"]
            for fpath in results:
                lines.append(f"  file://{fpath}")
            text = "\n".join(lines)
        else:
            text = f"No files found matching \"{query}\"."

        self._ui_call(lambda t=text: self._add_message("Frank", t))

    # ---------- Steam Integration ----------
    def _do_steam_list_worker(self, voice: bool = False):
        """List installed Steam games."""
        try:
            from tools.steam_integration import list_games_formatted
            result = list_games_formatted()
            if voice:
                self._ui_call(lambda r=result: self._voice_respond(r))
            else:
                self._ui_call(lambda r=result: self._add_message("Frank", r))
        except ImportError:
            # Try alternative import path
            try:
                import sys
                try:
                    from config.paths import AICORE_ROOT as _AICORE_ROOT
                except ImportError:
                    from pathlib import Path as _P
                    _AICORE_ROOT = _P(__file__).resolve().parents[3]
                sys.path.insert(0, str(_AICORE_ROOT))
                from tools.steam_integration import list_games_formatted
                result = list_games_formatted()
                if voice:
                    self._ui_call(lambda r=result: self._voice_respond(r))
                else:
                    self._ui_call(lambda r=result: self._add_message("Frank", r))
            except Exception as e:
                msg = f"Steam integration not available: {e}"
                if voice:
                    self._ui_call(lambda m=msg: self._voice_respond(m))
                else:
                    self._ui_call(lambda: self._add_message("Frank", msg, is_system=True))

    def _do_steam_launch_worker(self, game: str, voice: bool = False):
        """Launch a Steam game by name."""
        try:
            import sys
            try:
                from config.paths import AICORE_ROOT as _AICORE_ROOT
            except ImportError:
                from pathlib import Path as _P
                _AICORE_ROOT = _P(__file__).resolve().parents[3]
            sys.path.insert(0, str(_AICORE_ROOT))
            from tools.steam_integration import launch_game_by_name

            success, msg = launch_game_by_name(game)
            if voice:
                self._ui_call(lambda m=msg: self._voice_respond(m))
            else:
                self._ui_call(lambda m=msg: self._add_message("Frank", m))
        except Exception as e:
            msg = f"Error launching: {e}"
            if voice:
                self._ui_call(lambda m=msg: self._voice_respond(m))
            else:
                self._ui_call(lambda: self._add_message("Frank", msg, is_system=True))

    def _do_steam_close_worker(self, voice: bool = False):
        """Close the currently running game."""
        try:
            import sys
            try:
                from config.paths import AICORE_ROOT as _AICORE_ROOT
            except ImportError:
                from pathlib import Path as _P
                _AICORE_ROOT = _P(__file__).resolve().parents[3]
            sys.path.insert(0, str(_AICORE_ROOT))
            from tools.steam_integration import close_game

            success, msg = close_game()
            if voice:
                self._ui_call(lambda m=msg: self._voice_respond(m))
            else:
                self._ui_call(lambda m=msg: self._add_message("Frank", m))
        except Exception as e:
            msg = f"Error closing: {e}"
            if voice:
                self._ui_call(lambda m=msg: self._voice_respond(m))
            else:
                self._ui_call(lambda: self._add_message("Frank", msg, is_system=True))

    # ---------- External Data: URL Fetch, RSS, News ----------

    def _do_fetch_url_worker(self, url: str, voice: bool = False):
        """Fetch a URL and display extracted content."""
        self._ui_call(self._show_typing)
        result = _fetch_url(url)
        formatted = _format_fetched_content(result)
        self._ui_call(self._hide_typing)

        if voice:
            self._ui_call(lambda r=formatted: self._voice_respond(r))
        else:
            self._ui_call(lambda r=formatted: self._add_message("Frank", r))

    def _do_rss_feed_worker(self, url: str, voice: bool = False):
        """Read an RSS/Atom feed and display entries."""
        self._ui_call(self._show_typing)
        result = _read_rss_feed(url)
        formatted = _format_rss_result(result)
        self._ui_call(self._hide_typing)

        if voice:
            self._ui_call(lambda r=formatted: self._voice_respond(r))
        else:
            self._ui_call(lambda r=formatted: self._add_message("Frank", r))

    def _do_news_worker(self, msg: str = "", voice: bool = False):
        """Get news from pre-configured feeds by detected category."""
        self._ui_call(self._show_typing)
        category = _detect_news_category(msg) if msg else "tech_de"
        result = _get_news(category)
        formatted = _format_news_result(result)
        self._ui_call(self._hide_typing)

        if voice:
            self._ui_call(lambda r=formatted: self._voice_respond(r))
        else:
            self._ui_call(lambda r=formatted: self._add_message("Frank", r))

    # ---------- System Status Deep ----------

    def _do_sys_status_deep_worker(self):
        """Comprehensive system status report via toolboxd."""
        import json
        import urllib.request
        self._ui_call(self._show_typing)

        TOOLBOX = "http://127.0.0.1:8096"
        lines = []

        def _post(endpoint, payload=None, timeout=5):
            data = json.dumps(payload or {}).encode()
            req = urllib.request.Request(
                TOOLBOX + endpoint, data=data,
                headers={"Content-Type": "application/json"},
            )
            try:
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    return json.loads(resp.read())
            except Exception as e:
                LOG.debug("sys_status_deep %s failed: %s", endpoint, e)
                return None

        # 1) sys/summary — CPU, RAM, temps, disk, services
        summary = _post("/sys/summary")
        if summary and summary.get("ok"):
            # CPU
            cpu = summary.get("cpu", {})
            lines.append(f"CPU: {cpu.get('model', '?')} — "
                         f"{cpu.get('cores', '?')} threads, "
                         f"load {cpu.get('load_1m', '?')}")

            # Temps
            temps = summary.get("temps", {})
            if temps.get("ok"):
                entries = temps.get("entries", [])
                temp_parts = []
                for e in entries:
                    label = e.get("label", "")
                    current = e.get("current")
                    if current and label:
                        temp_parts.append(f"{label}: {current}°C")
                if temp_parts:
                    lines.append("Temps: " + ", ".join(temp_parts[:6]))

            # Memory
            mem = summary.get("mem", {})
            mk = mem.get("mem_kb", {})
            if mk:
                total_gb = mk.get("total", 0) / 1048576
                used_gb = mk.get("used", 0) / 1048576
                avail_gb = mk.get("available", 0) / 1048576
                lines.append(f"RAM: {used_gb:.1f} / {total_gb:.1f} GB "
                             f"({avail_gb:.1f} GB free)")
            sk = mem.get("swap_kb", {})
            if sk and sk.get("used", 0) > 0:
                swap_used = sk["used"] / 1048576
                swap_total = sk.get("total", 0) / 1048576
                lines.append(f"Swap: {swap_used:.1f} / {swap_total:.1f} GB "
                             f"({mem.get('swap_percent', 0):.0f}%)")

            # Uptime
            ul = summary.get("uptime_load", {})
            if ul.get("ok"):
                up_h = ul.get("uptime_s", 0) / 3600
                la = ul.get("loadavg", {})
                lines.append(f"Uptime: {up_h:.1f}h — "
                             f"Load: {la.get('1', '?')}/{la.get('5', '?')}/{la.get('15', '?')}")

            # Disk
            disks = summary.get("disk", [])
            seen = set()
            for d in disks:
                if d.get("ok") and d.get("path") not in seen:
                    seen.add(d["path"])
                    total_gb = d.get("total", 0) / (1024**3)
                    used_gb = d.get("used", 0) / (1024**3)
                    free_gb = d.get("free", 0) / (1024**3)
                    lines.append(f"Disk [{d['path']}]: "
                                 f"{used_gb:.0f} / {total_gb:.0f} GB "
                                 f"({free_gb:.0f} GB free, "
                                 f"{d.get('percent_used', 0):.1f}%)")

            # Services
            services = summary.get("services", [])
            if services:
                running = [s for s in services if s.get("sub") == "running"]
                failed = [s for s in services if s.get("sub") == "failed"]
                lines.append(f"Services: {len(running)} running"
                             + (f", {len(failed)} FAILED" if failed else ""))
                if failed:
                    for s in failed:
                        unit = s.get("unit", "?")
                        if unit == "\u25cf":
                            unit = s.get("load", "?")
                        lines.append(f"  FAILED: {unit}")

        # 2) Top processes
        procs = _post("/sys/processes", {"limit": 8})
        if procs and procs.get("ok"):
            proc_list = procs.get("processes", procs.get("items", []))
            if proc_list:
                lines.append("Top processes (CPU):")
                for p in proc_list[:8]:
                    name = p.get("name", p.get("comm", "?"))
                    cpu_pct = p.get("cpu_percent", p.get("cpu", "?"))
                    mem_pct = p.get("memory_percent", p.get("mem", "?"))
                    if isinstance(cpu_pct, float):
                        cpu_pct = f"{cpu_pct:.1f}"
                    if isinstance(mem_pct, float):
                        mem_pct = f"{mem_pct:.1f}"
                    lines.append(f"  {name}: CPU {cpu_pct}%, RAM {mem_pct}%")

        # 3) Network
        net = _post("/sys/network")
        if net and net.get("ok"):
            ifaces = net.get("interfaces", net.get("items", []))
            for iface in ifaces:
                name = iface.get("name", "?")
                ip = iface.get("ip", iface.get("ipv4", ""))
                state = iface.get("state", iface.get("operstate", ""))
                if ip or state == "UP":
                    lines.append(f"Network [{name}]: {ip or 'no IP'} ({state})")

        if not lines:
            lines.append("Could not retrieve system status.")

        report = "\n".join(lines)
        self._ui_call(self._hide_typing)
        self._ui_call(lambda r=report: self._add_message("Frank", r))

    # ---------- Skill System ----------

    def _do_skill_worker(self, skill_name: str, user_query: str = "",
                         voice: bool = False):
        """Execute a skill and display the result."""
        from overlay.constants import LOG
        self._ui_call(self._show_typing)
        try:
            from skills import get_skill_registry
            registry = get_skill_registry()
            result = registry.execute(skill_name, {"user_query": user_query})
            LOG.info(f"Skill '{skill_name}' result: ok={result.get('ok')}")
        except Exception as e:
            result = {"ok": False, "error": str(e)}
        self._ui_call(self._hide_typing)

        if result.get("ok"):
            text = result.get("output", "(no output)")
        else:
            text = f"Skill error: {result.get('error', 'unknown')}"

        if voice:
            self._ui_call(lambda r=text: self._voice_respond(r))
        else:
            self._ui_call(lambda r=text: self._add_message("Frank", r))

    def _do_skill_reload_worker(self):
        """Hot-reload all skills."""
        from overlay.constants import LOG
        self._ui_call(self._show_typing)
        try:
            from skills import get_skill_registry
            count = get_skill_registry().reload()
            text = f"Skills reloaded: {count} skills active."
            LOG.info(text)
        except Exception as e:
            text = f"Skill reload error: {e}"
        self._ui_call(self._hide_typing)
        self._ui_call(lambda r=text: self._add_message("Frank", r, is_system=True))

    def _do_skill_list_worker(self):
        """Show all installed skills."""
        from overlay.constants import LOG
        self._ui_call(self._show_typing)
        try:
            from skills import get_skill_registry
            text = get_skill_registry().get_skills_summary()
            LOG.info("Skill list displayed to user")
        except Exception as e:
            text = f"Skill list error: {e}"
        self._ui_call(self._hide_typing)
        self._ui_call(lambda r=text: self._add_message("Frank", r))

    def _do_skill_browse_worker(self, query: str = ""):
        """Browse OpenClaw marketplace for available skills."""
        from overlay.constants import LOG
        self._ui_call(self._show_typing)
        self._ui_call(lambda: self._add_message(
            "Frank", "Browsing OpenClaw Marketplace...", is_system=True))
        try:
            from skills import get_skill_registry
            result = get_skill_registry().browse_marketplace(query)
            if result.get("ok") and result.get("skills"):
                lines = [f"OpenClaw Marketplace ({result['count']} available):\n"]
                for s in result["skills"]:
                    dl = s.get("downloads", 0)
                    dl_str = f" ({dl} Downloads)" if dl else ""
                    lines.append(f"  {s['name']}{dl_str}\n    {s.get('description', '')}")
                lines.append(f"\nInstall with: \"install skill <name>\"")
                text = "\n".join(lines)
            elif result.get("ok"):
                text = "No new skills found in marketplace (or all already installed)."
            else:
                text = f"Marketplace error: {result.get('error', 'unknown')}"
            LOG.info(f"Marketplace browse: {result.get('count', 0)} results")
        except Exception as e:
            text = f"Marketplace error: {e}"
        self._ui_call(self._hide_typing)
        self._ui_call(lambda r=text: self._add_message("Frank", r))

    def _do_skill_install_worker(self, slug: str):
        """Install a skill from OpenClaw marketplace."""
        from overlay.constants import LOG
        self._ui_call(self._show_typing)
        self._ui_call(lambda s=slug: self._add_message(
            "Frank", f"Installing skill '{s}' from marketplace...", is_system=True))
        try:
            from skills import get_skill_registry
            result = get_skill_registry().install_from_marketplace(slug)
            if result.get("ok"):
                text = result.get("message", f"Skill '{slug}' installed!")
            else:
                text = f"Installation failed: {result.get('error', 'unknown')}"
            LOG.info(f"Skill install '{slug}': ok={result.get('ok')}")
        except Exception as e:
            text = f"Installation error: {e}"
        self._ui_call(self._hide_typing)
        self._ui_call(lambda r=text: self._add_message("Frank", r))

    def _do_skill_uninstall_worker(self, slug: str):
        """Uninstall a skill."""
        from overlay.constants import LOG
        self._ui_call(self._show_typing)
        try:
            from skills import get_skill_registry
            result = get_skill_registry().uninstall(slug)
            if result.get("ok"):
                text = result.get("message", f"Skill '{slug}' uninstalled.")
            else:
                text = f"Uninstall failed: {result.get('error', 'unknown')}"
            LOG.info(f"Skill uninstall '{slug}': ok={result.get('ok')}")
        except Exception as e:
            text = f"Error: {e}"
        self._ui_call(self._hide_typing)
        self._ui_call(lambda r=text: self._add_message("Frank", r))

    def _do_skill_updates_worker(self):
        """Check for skill updates from marketplace."""
        from overlay.constants import LOG
        self._ui_call(self._show_typing)
        self._ui_call(lambda: self._add_message(
            "Frank", "Checking for skill updates...", is_system=True))
        try:
            from skills import get_skill_registry
            result = get_skill_registry().check_updates()
            if result.get("ok") and result.get("updates"):
                lines = [f"**Available updates** ({result['count']}):"]
                for u in result["updates"]:
                    lines.append(
                        f"- `{u['name']}`: {u['current_version']} -> {u['latest_version']}")
                lines.append("\nUpdate with: `install skill <name>`")
                text = "\n".join(lines)
            elif result.get("ok"):
                text = "All skills are up to date."
            else:
                text = f"Update check failed: {result.get('error', 'unknown')}"
        except Exception as e:
            text = f"Update check error: {e}"
        self._ui_call(self._hide_typing)
        self._ui_call(lambda r=text: self._add_message("Frank", r))

    # ---------- Package List ----------

    def _do_package_list_worker(self, backend: str = "all"):
        """List installed packages — direct subprocess, no LLM."""
        import subprocess
        self._ui_call(self._show_typing)

        sections = []

        try:
            if backend in ("snap", "all"):
                r = subprocess.run(["snap", "list"], capture_output=True, text=True, timeout=10)
                if r.returncode == 0 and r.stdout.strip():
                    lines = r.stdout.strip().split("\n")
                    # First line is header, rest are packages
                    pkgs = [l.split()[0] for l in lines[1:] if l.strip()]
                    sections.append(f"Snaps ({len(pkgs)}): {', '.join(pkgs)}")

            if backend in ("flatpak", "all"):
                r = subprocess.run(["flatpak", "list", "--app", "--columns=name"],
                                   capture_output=True, text=True, timeout=10)
                if r.returncode == 0 and r.stdout.strip():
                    pkgs = [l.strip() for l in r.stdout.strip().split("\n") if l.strip()]
                    if pkgs:
                        sections.append(f"Flatpaks ({len(pkgs)}): {', '.join(pkgs)}")

            if backend == "pip":
                r = subprocess.run(["pip", "list", "--format=columns"],
                                   capture_output=True, text=True, timeout=10)
                if r.returncode == 0 and r.stdout.strip():
                    lines = r.stdout.strip().split("\n")
                    pkgs = [l.split()[0] for l in lines[2:] if l.strip() and not l.startswith("---")]
                    sections.append(f"Pip packages ({len(pkgs)}): {', '.join(pkgs[:50])}")
                    if len(pkgs) > 50:
                        sections[-1] += f" ... +{len(pkgs) - 50} more"

            if backend == "apt":
                r = subprocess.run(["dpkg-query", "-f", "${Package}\n", "-W"],
                                   capture_output=True, text=True, timeout=10)
                if r.returncode == 0 and r.stdout.strip():
                    pkgs = [l.strip() for l in r.stdout.strip().split("\n") if l.strip()]
                    sections.append(f"APT packages ({len(pkgs)}): too many to list. Use 'apt list --installed | grep NAME' to search.")

        except FileNotFoundError:
            pass  # Backend not installed
        except subprocess.TimeoutExpired:
            sections.append("Package query timed out.")
        except Exception as e:
            LOG.error(f"Package list error: {e}")
            sections.append(f"Error: {e}")

        self._ui_call(self._hide_typing)

        if sections:
            text = "\n".join(sections)
        else:
            text = "No packages found or backend not available."

        self._ui_call(lambda r=text: self._add_message("Frank", r))

    # ---------- USB Device Management ----------

    def _do_usb_storage_worker(self):
        """List USB storage devices with mount status."""
        self._ui_call(self._show_typing)
        result = _usb_storage()
        self._ui_call(self._hide_typing)

        if not result or not result.get("ok"):
            error = result.get("error", "No response") if result else "No response"
            self._ui_call(lambda e=error: self._add_message(
                "Frank", f"USB query failed: {e}", is_system=True))
            return

        devices = result.get("devices", [])
        if not devices:
            self._ui_call(lambda: self._add_message(
                "Frank", "No USB storage devices connected.", is_system=True))
            return

        lines = [f"**USB storage devices** ({len(devices)}):"]
        for d in devices:
            name = d.get("name", "?")
            size = d.get("size", "?")
            label = d.get("label") or "no label"
            fstype = d.get("fstype") or "?"
            mp = d.get("mountpoint")
            status = f"mounted at: {mp}" if mp else "not mounted"
            vendor = d.get("vendor", "").strip()
            model = d.get("model", "").strip()
            dev_name = f"{vendor} {model}".strip() or name
            lines.append(f"  {dev_name} ({size}, {fstype}, {label}) — {status}")
        text = "\n".join(lines)
        self._ui_call(lambda r=text: self._add_message("Frank", r))

    def _do_usb_mount_worker(self, device: str = "auto"):
        """Mount a USB storage device."""
        self._ui_call(self._show_typing)
        result = _usb_mount(device)
        self._ui_call(self._hide_typing)

        if result and result.get("ok"):
            mp = result.get("mountpoint", "")
            dev = result.get("device", device)
            self._ui_call(lambda d=dev, m=mp: self._add_message(
                "Frank", f"USB device {d} mounted at {m}", is_system=True))
        else:
            error = result.get("error", "Unknown error") if result else "No response"
            self._ui_call(lambda e=error: self._add_message(
                "Frank", f"USB mount failed: {e}", is_system=True))

    def _do_usb_unmount_worker(self, device: str = "auto"):
        """Unmount a USB storage device."""
        self._ui_call(self._show_typing)
        result = _usb_unmount(device)
        self._ui_call(self._hide_typing)

        if result and result.get("ok"):
            dev = result.get("device", device)
            self._ui_call(lambda d=dev: self._add_message(
                "Frank", f"USB device {d} unmounted.", is_system=True))
        else:
            error = result.get("error", "Unknown error") if result else "No response"
            self._ui_call(lambda e=error: self._add_message(
                "Frank", f"USB unmount failed: {e}", is_system=True))

    def _do_usb_eject_worker(self, device: str = "auto"):
        """Safely eject a USB device (unmount + power-off)."""
        self._ui_call(self._show_typing)
        self._ui_call(lambda: self._add_message(
            "Frank", "Safely ejecting USB device...", is_system=True))
        result = _usb_eject(device)
        self._ui_call(self._hide_typing)

        if result and result.get("ok"):
            dev = result.get("device", device)
            self._ui_call(lambda d=dev: self._add_message(
                "Frank", f"USB device {d} safely ejected. You can remove it now.", is_system=True))
        else:
            error = result.get("error", "Unknown error") if result else "No response"
            self._ui_call(lambda e=error: self._add_message(
                "Frank", f"USB eject failed: {e}", is_system=True))
