#!/usr/bin/env python3
"""
SENTIENT GENESIS Daemon - The awakening system
==============================================

This is the main daemon that orchestrates the emergent
self-improvement system. It does NOT control - it only
provides the environment for emergence.
"""

import signal
import threading
import time
import json
import logging
import os
import socket
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, List
from enum import Enum

from .config import GenesisConfig, get_config
from .core.wave import Wave, WaveBus
from .core.field import MotivationalField, EmotionState
from .core.soup import PrimordialSoup
from .core.organism import IdeaOrganism, IdeaGenome
from .core.manifestation import ManifestationGate, Crystal
from .sensors import (
    SystemPulse,
    UserPresence,
    ErrorTremor,
    TimeRhythm,
    GitHubEcho,
    NewsEcho,
    CodeAnalyzer,
)
from .reflection import SelfReflector
from .integration import FASConnector, ASRSConnector
from .integration.feedback_sync import FeedbackSync

# Setup logging
LOG = logging.getLogger("genesis.daemon")


def sd_notify(message: str) -> bool:
    """
    Send notification to systemd.

    Implements sd_notify for systemd watchdog integration.
    Messages like "READY=1", "WATCHDOG=1", "STATUS=..."
    """
    notify_socket = os.environ.get("NOTIFY_SOCKET")
    if not notify_socket:
        return False

    try:
        # Handle abstract sockets (Linux)
        if notify_socket.startswith("@"):
            notify_socket = "\0" + notify_socket[1:]

        sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        try:
            sock.connect(notify_socket)
            sock.sendall(message.encode("utf-8"))
            return True
        finally:
            sock.close()
    except Exception as e:
        LOG.debug(f"sd_notify failed: {e}")
        return False


class ContemplationState(Enum):
    """States of consciousness for the Genesis system."""
    DORMANT = "dormant"      # Minimal activity, just sensing
    STIRRING = "stirring"    # Beginning to activate
    AWAKENING = "awakening"  # Full analysis starting
    ACTIVE = "active"        # Full processing, manifestation possible
    PRESENTING = "presenting"  # Showing proposal to user
    REFLECTING = "reflecting"  # Learning from outcome


class GenesisDaemon:
    """
    The main daemon that runs the emergent self-improvement system.

    This does NOT control the system - it only provides:
    1. The environment (sensors, resources)
    2. The timing (tick intervals)
    3. The connections (to popup, A.S.R.S.)

    Behavior EMERGES from the interactions of components.
    """

    def __init__(self, config: GenesisConfig = None):
        self.config = config or get_config()

        # Core components
        self.wave_bus = WaveBus()
        self.field = MotivationalField(config=self.config)
        self.soup = PrimordialSoup(config=self.config)
        self.feedback_sync = FeedbackSync()
        self.manifestation_gate = ManifestationGate(
            config=self.config, feedback_sync=self.feedback_sync
        )

        # Sensors
        self.sensors = [
            SystemPulse(),
            UserPresence(),
            ErrorTremor(),
            TimeRhythm(),
            GitHubEcho(),
            NewsEcho(),
            CodeAnalyzer(),
        ]

        # Reflection
        self.reflector = SelfReflector()

        # Integration
        self.fas_connector = FASConnector()
        self.asrs_connector = ASRSConnector()

        # State
        self.state = ContemplationState.DORMANT
        self.running = False
        self.tick_count = 0
        self.last_state_change = datetime.now()

        # Current crystal being presented
        self.current_crystal: Optional[Crystal] = None

        # Statistics
        self.stats = {
            "started_at": None,
            "total_ticks": 0,
            "state_history": [],
            "manifestations": 0,
            "successful_manifestations": 0,
            "failed_manifestations": 0,
        }

        # Threading
        self.lock = threading.Lock()

        LOG.info("Genesis Daemon initialized")

    def start(self):
        """Start the daemon."""
        self.running = True
        self.stats["started_at"] = datetime.now().isoformat()

        # Setup signal handlers
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        # Load state
        self._load_state()

        LOG.info("Genesis Daemon starting...")
        LOG.info(f"Initial state: {self.state.value}")

        # Notify systemd we're ready
        sd_notify("READY=1")
        sd_notify(f"STATUS=Genesis starting in {self.state.value} state")

        # Main loop
        self._main_loop()

    def stop(self):
        """Stop the daemon."""
        LOG.info("Genesis Daemon stopping...")
        sd_notify("STOPPING=1")
        self.running = False
        self._save_state()

    def _signal_handler(self, signum, frame):
        """Handle termination signals."""
        LOG.info(f"Received signal {signum}, stopping...")
        self.stop()

    def _main_loop(self):
        """The main daemon loop."""
        last_watchdog = time.monotonic()

        while self.running:
            try:
                # Pet watchdog before tick (sensors can block 30+s)
                now = time.monotonic()
                if now - last_watchdog >= 25:
                    sd_notify("WATCHDOG=1")
                    sd_notify(f"STATUS=State: {self.state.value}, Tick: {self.tick_count}")
                    last_watchdog = now

                # Get tick interval based on state
                interval = self._get_tick_interval()

                # Run one tick
                self._tick()

                # Pet watchdog after tick too
                now = time.monotonic()
                if now - last_watchdog >= 25:
                    sd_notify("WATCHDOG=1")
                    sd_notify(f"STATUS=State: {self.state.value}, Tick: {self.tick_count}")
                    last_watchdog = now

                # Sleep
                time.sleep(interval)

            except Exception as e:
                LOG.error(f"Error in main loop: {e}", exc_info=True)
                sd_notify("WATCHDOG=1")  # Still alive despite error
                time.sleep(5)  # Back off on error

    def _get_tick_interval(self) -> float:
        """Get tick interval based on current state."""
        intervals = {
            ContemplationState.DORMANT: self.config.tick_interval_dormant,
            ContemplationState.STIRRING: self.config.tick_interval_stirring,
            ContemplationState.AWAKENING: self.config.tick_interval_awakening,
            ContemplationState.ACTIVE: self.config.tick_interval_active,
            ContemplationState.PRESENTING: 5.0,  # Check popup status
            ContemplationState.REFLECTING: 2.0,
        }
        return intervals.get(self.state, 30.0)

    def _tick(self):
        """
        One tick of the daemon.
        This is where the magic happens.
        """
        self.tick_count += 1
        self.stats["total_ticks"] = self.tick_count

        with self.lock:
            # 1. Sense the world (all states)
            self._sense()

            # 2. Evolve the field
            self.field.evolve(dt=1.0)

            # 3. Apply wave contributions to field
            contributions = self.wave_bus.tick()
            self.field.apply_wave_contributions(contributions)

            # 4. Update state based on conditions
            self._update_state()

            # 5. State-specific processing
            if self.state == ContemplationState.DORMANT:
                self._process_dormant()
            elif self.state == ContemplationState.STIRRING:
                self._process_stirring()
            elif self.state == ContemplationState.AWAKENING:
                self._process_awakening()
            elif self.state == ContemplationState.ACTIVE:
                self._process_active()
            elif self.state == ContemplationState.PRESENTING:
                self._process_presenting()
            elif self.state == ContemplationState.REFLECTING:
                self._process_reflecting()

            # 6. Periodic maintenance (every 50 ticks for fresher state snapshots)
            if self.tick_count % 50 == 0:
                self._maintenance()

    def _sense(self):
        """Run all sensors and collect waves."""
        for sensor in self.sensors:
            try:
                waves = sensor.tick()
                self.wave_bus.emit_many(waves)

                # Inject observations as potential seeds
                if self.state in [ContemplationState.STIRRING,
                                  ContemplationState.AWAKENING,
                                  ContemplationState.ACTIVE]:
                    observations = sensor.get_observations()
                    for obs in observations:
                        self.soup.inject_observation(obs)

            except Exception as e:
                LOG.warning(f"Sensor {sensor.name} error: {e}")

            # Pet watchdog between sensors (some block 30+s)
            sd_notify("WATCHDOG=1")

    def _update_state(self):
        """Update contemplation state based on conditions."""
        activation = self.field.get_activation_level()
        user_sensor = self._get_sensor("user_presence")
        system_sensor = self._get_sensor("system_pulse")

        # Get environment conditions
        user_active = True
        system_load = 0.5
        if user_sensor:
            user_active = user_sensor.is_user_active()

        # One-time override: GENESIS_FORCE_ACTIVE=1 bypasses user-idle check
        if os.environ.get("GENESIS_FORCE_ACTIVE") == "1":
            user_active = False
        if system_sensor:
            metrics = system_sensor.get_current_metrics()
            system_load = metrics.get("cpu", 0.5)

        # State transition logic
        old_state = self.state

        if self.state == ContemplationState.DORMANT:
            # Transition to stirring if activation high and conditions good
            if (activation > self.config.stirring_threshold and
                not user_active and
                system_load < self.config.max_cpu_for_awakening):
                self.state = ContemplationState.STIRRING

        elif self.state == ContemplationState.STIRRING:
            # Transition to awakening or back to dormant
            if user_active or system_load > self.config.max_cpu_for_awakening:
                self.state = ContemplationState.DORMANT
            elif activation > self.config.awakening_threshold:
                self.state = ContemplationState.AWAKENING

        elif self.state == ContemplationState.AWAKENING:
            # Transition to active or back
            if user_active or system_load > self.config.max_cpu_for_active:
                self.state = ContemplationState.STIRRING
            elif activation > self.config.active_threshold:
                self.state = ContemplationState.ACTIVE

        elif self.state == ContemplationState.ACTIVE:
            # Check for manifestation or go back
            if user_active:
                self.state = ContemplationState.DORMANT
            elif system_load > self.config.max_cpu_for_active:
                self.state = ContemplationState.AWAKENING

        elif self.state == ContemplationState.PRESENTING:
            # Stay presenting until popup done
            pass

        elif self.state == ContemplationState.REFLECTING:
            # Return to dormant after reflection
            elapsed = (datetime.now() - self.last_state_change).seconds
            if elapsed > 10:
                self.state = ContemplationState.DORMANT

        # Log state changes
        if self.state != old_state:
            LOG.info(f"State: {old_state.value} → {self.state.value} "
                    f"(activation={activation:.2f})")
            self.last_state_change = datetime.now()
            self.stats["state_history"].append({
                "time": datetime.now().isoformat(),
                "from": old_state.value,
                "to": self.state.value,
                "activation": activation,
            })

    def _process_dormant(self):
        """Process during dormant state - minimal activity."""
        # Just tick the soup very slowly
        if self.tick_count % 10 == 0:
            self.soup.tick(self.field)

    def _process_stirring(self):
        """Process during stirring state - beginning to wake."""
        # Tick soup more frequently
        if self.tick_count % 3 == 0:
            self.soup.tick(self.field)

    def _process_awakening(self):
        """Process during awakening state - full analysis."""
        # Tick soup every tick
        self.soup.tick(self.field)

        # Check for crystals
        crystals = self.soup.get_crystals()
        if crystals:
            LOG.debug(f"Awakening: {len(crystals)} crystals available")

    def _process_active(self):
        """Process during active state - manifestation possible."""
        # Tick soup
        new_crystals = self.soup.tick(self.field)

        if new_crystals:
            LOG.info(f"New crystals formed: {len(new_crystals)}")

        # Build environment for manifestation check
        user_sensor = self._get_sensor("user_presence")
        system_sensor = self._get_sensor("system_pulse")

        environment = {
            "user_active": user_sensor.is_user_active() if user_sensor else True,
            "user_idle_seconds": user_sensor.get_idle_seconds() if user_sensor else 0,
            "system_load": system_sensor.get_current_metrics().get("cpu", 0.5) if system_sensor else 0.5,
        }

        # Check for manifestation
        crystal = self.manifestation_gate.check_manifestation(
            self.soup, self.field, environment
        )

        if crystal:
            LOG.info(f"Manifestation! Crystal: {crystal.id} (pending: {self.fas_connector.get_pending_count() + 1})")
            self.current_crystal = crystal
            self.stats["manifestations"] += 1

            # Queue crystal — popup only launches when threshold reached
            self.fas_connector.manifest_crystal(crystal)

            # Only enter PRESENTING state if popup was actually launched
            if self.fas_connector.is_popup_active():
                self.state = ContemplationState.PRESENTING
                self.last_state_change = datetime.now()
                LOG.info("Popup launched, entering PRESENTING state")

    def _process_presenting(self):
        """Process while presenting to user."""
        # Check if popup returned result
        result = self.fas_connector.check_popup_result()

        if result:
            LOG.info(f"Popup result: {result}")
            self._handle_popup_result(result)
        elif not self.fas_connector.is_popup_active():
            # Popup closed without result - treat as defer
            LOG.info("Popup closed without result")
            self.state = ContemplationState.DORMANT

    def _process_reflecting(self):
        """Process during reflection."""
        # Run reflection
        reflection = self.reflector.reflect(use_llm=True)

        if reflection:
            LOG.info(f"Reflection: {reflection.self_insight[:100] if reflection.self_insight else 'None'}")

    def _handle_popup_result(self, result: Dict):
        """Handle user decision from popup."""
        decision = result.get("decision", "defer")
        crystal = self.current_crystal

        if not crystal:
            self.state = ContemplationState.DORMANT
            return

        # Record user feedback for future resonance tuning
        self.feedback_sync.record_decision(crystal, decision)

        if decision == "approve":
            LOG.info(f"Crystal {crystal.id} approved!")
            self.stats["successful_manifestations"] += 1

            genome = crystal.organism.genome

            # ── Genesis→E-PQ Bridge: Personality adjustments ──
            if genome.idea_type == "personality_adjustment":
                success = self._execute_personality_adjustment(crystal)
                if success:
                    self.reflector.record_outcome(crystal, True, "Personality adjusted")
                else:
                    self.reflector.record_outcome(crystal, False, "Personality adjustment failed")
                self.manifestation_gate.record_success(crystal) if success else None
                self.current_crystal = None
                self.state = ContemplationState.REFLECTING
                self.last_state_change = datetime.now()
                return

            # ── Genesis→Prompt Bridge: Prompt template evolution ──
            if genome.idea_type == "prompt_evolution":
                success = self._execute_prompt_evolution(crystal)
                if success:
                    self.reflector.record_outcome(crystal, True, "Prompt template evolved")
                else:
                    self.reflector.record_outcome(crystal, False, "Prompt evolution failed")
                self.manifestation_gate.record_success(crystal) if success else None
                self.current_crystal = None
                self.state = ContemplationState.REFLECTING
                self.last_state_change = datetime.now()
                return

            # ── Standard code integration via A.S.R.S. ──
            def implementation():
                LOG.info(f"Implementing: {crystal.title}")

            success = self.asrs_connector.integrate_with_safety(
                crystal,
                implementation,
                on_success=lambda: self._on_integration_success(crystal),
                on_failure=lambda r, a: self._on_integration_failure(crystal, r),
            )

            if success:
                self.reflector.record_outcome(crystal, True, "User approved")
            else:
                self.reflector.record_outcome(crystal, False, "Integration failed")

        elif decision == "reject":
            LOG.info(f"Crystal {crystal.id} rejected")
            self.stats["failed_manifestations"] += 1
            self.manifestation_gate.record_failure(crystal, result.get("reason", "User rejected"))
            self.reflector.record_outcome(crystal, False, result.get("reason", "User rejected"))

        else:  # defer
            LOG.info(f"Crystal {crystal.id} deferred")
            # Put crystal back in soup with reduced energy
            crystal.organism.energy *= 0.5
            self.soup.organisms.append(crystal.organism)

        self.current_crystal = None
        self.state = ContemplationState.REFLECTING
        self.last_state_change = datetime.now()

    def _execute_personality_adjustment(self, crystal: Crystal) -> bool:
        """Execute a personality vector adjustment via E-PQ.

        This is the Genesis→E-PQ Bridge: Genesis crystals can propose
        changes to Frank's personality vectors, executed through E-PQ
        process_event() with special event types.
        """
        try:
            import sys
            from pathlib import Path
            _root = Path(__file__).resolve().parents[2]
            if str(_root) not in sys.path:
                sys.path.insert(0, str(_root))

            from personality.e_pq import get_epq
            epq = get_epq()

            genome = crystal.organism.genome
            target_vector = genome.traits.get("target_vector", genome.target)
            amount = genome.traits.get("adjustment_amount", 0.1)

            if genome.approach == "vector_boost":
                event_type = "genesis_personality_boost"
            else:
                event_type = "genesis_personality_dampen"

            result = epq.process_event(
                event_type,
                data={
                    "target_vector": target_vector,
                    "amount": amount,
                    "event_id": f"genesis_{crystal.id}",
                },
                sentiment="positive",
            )
            LOG.info(
                "Genesis→E-PQ: %s %s by %.2f (changes=%s)",
                genome.approach, target_vector, amount,
                {k: f"{v:+.3f}" for k, v in result.get("changes", {}).items() if v},
            )
            return True
        except Exception as e:
            LOG.error("Genesis→E-PQ bridge failed: %s", e)
            return False

    def _execute_prompt_evolution(self, crystal: Crystal) -> bool:
        """Execute a prompt template modification on frank.persona.json.

        Modifies non-core prompt sections. Creates a backup before
        applying changes. Core identity section is PROTECTED.
        """
        import shutil
        from pathlib import Path

        _root = Path(__file__).resolve().parents[2]
        persona_path = _root / "personality" / "frank.persona.json"
        backup_path = persona_path.with_suffix(".json.genesis_backup")

        try:
            import sys
            if str(_root) not in sys.path:
                sys.path.insert(0, str(_root))

            if not persona_path.exists():
                LOG.error("Persona file not found: %s", persona_path)
                return False

            # Backup before modification
            shutil.copy2(persona_path, backup_path)

            genome = crystal.organism.genome
            target_section = genome.target
            modification = genome.traits.get("modification", "")

            if not modification:
                LOG.warning("No modification specified for prompt evolution")
                return False

            # PROTECTED sections that Genesis CANNOT modify
            protected = {"identity_core", "language_policy"}
            if target_section in protected:
                LOG.warning("Genesis tried to modify protected section: %s", target_section)
                return False

            # Load persona
            persona = json.loads(persona_path.read_text())
            prompts = persona.get("prompts", {})

            if target_section not in prompts:
                LOG.warning("Unknown prompt section: %s", target_section)
                return False

            # Apply modification
            prompts[target_section] = modification
            persona["prompts"] = prompts

            # Save modified persona
            persona_path.write_text(json.dumps(persona, indent=2, ensure_ascii=False))

            LOG.info(
                "Genesis→Prompt: Modified section '%s' (backup at %s)",
                target_section, backup_path,
            )
            return True
        except Exception as e:
            LOG.error("Genesis→Prompt evolution failed: %s", e)
            # Attempt rollback — shutil, backup_path, persona_path are
            # always defined (assigned before the try block).
            try:
                if backup_path.exists():
                    shutil.copy2(backup_path, persona_path)
                    LOG.info("Rolled back persona file from backup")
            except Exception:
                pass
            return False

    def _on_integration_success(self, crystal: Crystal):
        """Called when A.S.R.S. confirms successful integration."""
        LOG.info(f"Integration successful: {crystal.id}")
        self.manifestation_gate.record_success(crystal)

    def _on_integration_failure(self, crystal: Crystal, reason: str):
        """Called when A.S.R.S. reports integration failure."""
        LOG.warning(f"Integration failed: {crystal.id} - {reason}")
        self.manifestation_gate.record_failure(crystal, reason)

    def _get_sensor(self, name: str):
        """Get sensor by name."""
        for sensor in self.sensors:
            if sensor.name == name:
                return sensor
        return None

    def _maintenance(self):
        """Periodic maintenance tasks."""
        # Save state every maintenance call (every 50 ticks)
        self._save_state()

        # Clean up old data
        if len(self.stats["state_history"]) > 1000:
            self.stats["state_history"] = self.stats["state_history"][-500:]

        # Log status
        LOG.debug(f"Tick {self.tick_count}, State: {self.state.value}, "
                 f"Soup: {len(self.soup.organisms)} organisms, "
                 f"Field: {self.field.get_dominant_state().value}")

    def _save_state(self):
        """Save daemon state to disk."""
        try:
            state_path = self.config.state_path
            state_path.parent.mkdir(parents=True, exist_ok=True)

            state = {
                "saved_at": datetime.now().isoformat(),
                "tick_count": self.tick_count,
                "state": self.state.value,
                "field": self.field.to_dict(),
                "soup": self.soup.to_dict(),
                "reflector": self.reflector.to_dict(),
                "feedback_sync": self.feedback_sync.to_dict(),
                "stats": self.stats,
            }

            state_path.write_text(json.dumps(state, indent=2, default=str))
            LOG.debug("State saved")

        except Exception as e:
            LOG.warning(f"Failed to save state: {e}")

    def _load_state(self):
        """Load daemon state from disk."""
        try:
            state_path = self.config.state_path
            if not state_path.exists():
                return

            state = json.loads(state_path.read_text())

            self.tick_count = state.get("tick_count", 0)

            # Load field
            if "field" in state:
                field_data = state["field"]
                for key in ["curiosity", "frustration", "satisfaction",
                           "boredom", "concern", "drive"]:
                    if key in field_data:
                        setattr(self.field, key, field_data[key])

            # Load soup
            if "soup" in state:
                self.soup.from_dict(state["soup"])

            # Load reflector
            if "reflector" in state:
                self.reflector.load_state(state["reflector"])

            # Load feedback sync
            if "feedback_sync" in state:
                self.feedback_sync.from_dict(state["feedback_sync"])

            LOG.info(f"State loaded (tick {self.tick_count})")

        except Exception as e:
            LOG.warning(f"Failed to load state: {e}")

    def get_status(self) -> Dict:
        """Get current daemon status."""
        return {
            "running": self.running,
            "state": self.state.value,
            "tick_count": self.tick_count,
            "field": self.field.to_dict(),
            "soup": {
                "organisms": len(self.soup.organisms),
                "crystals": len(self.soup.crystals),
                "stats": {
                    "seeds": self.soup.stats.seeds,
                    "seedlings": self.soup.stats.seedlings,
                    "mature": self.soup.stats.mature,
                    "avg_energy": self.soup.stats.average_energy,
                    "avg_fitness": self.soup.stats.average_fitness,
                }
            },
            "stats": self.stats,
            "sensors": {s.name: s.get_stats() for s in self.sensors},
        }


# Global daemon instance
_daemon: Optional[GenesisDaemon] = None


def get_daemon() -> GenesisDaemon:
    """Get or create the global daemon instance."""
    global _daemon
    if _daemon is None:
        _daemon = GenesisDaemon()
    return _daemon


def main():
    """Main entry point."""
    import argparse

    # Setup logging
    try:
        from config.paths import AICORE_LOG as _daemon_log_root
        log_dir = _daemon_log_root / "genesis"
    except ImportError:
        log_dir = Path.home() / ".local" / "share" / "frank" / "logs" / "genesis"
    log_dir.mkdir(parents=True, exist_ok=True)

    logging.basicConfig(
        level=logging.INFO,
        format='[%(asctime)s] %(levelname)s %(name)s: %(message)s',
        handlers=[
            logging.FileHandler(log_dir / "genesis.log"),
            logging.StreamHandler(),
        ]
    )

    parser = argparse.ArgumentParser(description="SENTIENT GENESIS Daemon")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    parser.add_argument("--status", action="store_true", help="Show status and exit")

    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    daemon = get_daemon()

    if args.status:
        import pprint
        pprint.pprint(daemon.get_status())
        return

    print("=" * 60)
    print("SENTIENT GENESIS - Emergent Self-Improvement System")
    print("=" * 60)
    print()
    print("The system will now enter its contemplation cycles.")
    print("Behavior emerges from the interaction of components.")
    print("No central control - only environment and connections.")
    print()
    print("Press Ctrl+C to stop.")
    print("=" * 60)

    daemon.start()


if __name__ == "__main__":
    main()
