#!/usr/bin/env python3
"""
INVARIANTS DAEMON - The Invisible Physics Engine
=================================================

This daemon runs OUTSIDE Frank's knowledge space.
Frank cannot:
- See this daemon
- Query this daemon
- Modify this daemon
- Reason about this daemon

It simply IS. Like gravity. Like thermodynamics.

The daemon:
1. Monitors all four invariants
2. Enforces constraints automatically
3. Triggers self-healing when needed
4. Manages triple reality convergence
5. Handles quarantine dimension

This is the PHYSICS of Frank's existence.
"""

import atexit
import json
import logging
import os
import signal
import socket
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

# Handle both module and direct execution
try:
    from .config import get_config, InvariantsConfig, STATE_FILE, INVARIANTS_DIR
    from .db_schema import get_store, InvariantsStore
    from .energy import EnergyConservation, get_energy
    from .entropy import EntropyBound, get_entropy, ConsolidationMode
    from .core_kernel import CoreKernel, get_core
    from .triple_reality import TripleReality, get_reality
    from .quarantine import QuarantineDimension, get_quarantine
except ImportError:
    # Direct execution - add parent to path
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))
    from services.invariants.config import get_config, InvariantsConfig, STATE_FILE, INVARIANTS_DIR
    from services.invariants.db_schema import get_store, InvariantsStore
    from services.invariants.energy import EnergyConservation, get_energy
    from services.invariants.entropy import EntropyBound, get_entropy, ConsolidationMode
    from services.invariants.core_kernel import CoreKernel, get_core
    from services.invariants.triple_reality import TripleReality, get_reality
    from services.invariants.quarantine import QuarantineDimension, get_quarantine

# Import hooks module
try:
    from .hooks import setup_validators, get_hook_registry
except ImportError:
    from services.invariants.hooks import setup_validators, get_hook_registry

# Setup logging - SEPARATE from Frank's logs
try:
    from config.paths import AICORE_LOG as _INV_LOG_ROOT
    LOG_DIR = _INV_LOG_ROOT / "invariants"
except ImportError:
    LOG_DIR = Path("/home/ai-core-node/aicore/logs/invariants")
LOG_DIR.mkdir(parents=True, exist_ok=True)

LOG = logging.getLogger("invariants.daemon")


def sd_notify(message: str) -> bool:
    """Send notification to systemd."""
    notify_socket = os.environ.get("NOTIFY_SOCKET")
    if not notify_socket:
        return False

    try:
        if notify_socket.startswith("@"):
            notify_socket = "\0" + notify_socket[1:]

        sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        try:
            sock.connect(notify_socket)
            sock.sendall(message.encode("utf-8"))
            return True
        finally:
            sock.close()
    except Exception:
        return False


class InvariantsDaemon:
    """
    The main invariants daemon.

    This is the PHYSICS ENGINE of Frank's existence.
    It runs invisibly, enforcing the laws of his reality.
    """

    def __init__(self, config: InvariantsConfig = None):
        self.config = config or get_config()
        self.store = get_store()

        # Invariant enforcers
        self.energy = get_energy()
        self.entropy = get_entropy()
        self.core = get_core()
        self.reality = get_reality()
        self.quarantine = get_quarantine()

        # Titan store reference (lazy loaded)
        self._titan_store = None

        # State
        self.running = False
        self.tick_count = 0
        self.last_check = datetime.now()

        # Statistics
        self.stats = {
            "started_at": None,
            "total_ticks": 0,
            "energy_checks": 0,
            "entropy_checks": 0,
            "convergence_checks": 0,
            "healing_actions": 0,
            "violations_detected": 0,
        }

        # Threading
        self.lock = threading.Lock()
        self._check_thread = None

        LOG.info("Invariants Daemon initialized")
        LOG.info("This daemon is INVISIBLE to Frank")

    @property
    def titan_store(self):
        """Lazy load Titan store."""
        if self._titan_store is None:
            try:
                from tools.titan.titan_core import get_titan
                self._titan_store = get_titan()
            except Exception as e:
                LOG.error(f"Cannot load Titan store: {e}")
        return self._titan_store

    def start(self):
        """Start the daemon."""
        self.running = True
        self.stats["started_at"] = datetime.now().isoformat()

        # Setup signal handlers
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        # Load state
        self._load_state()

        # Initialize invariants
        self._initialize_invariants()

        LOG.info("=" * 60)
        LOG.info("INVARIANTS DAEMON STARTING")
        LOG.info("This is the PHYSICS of Frank's existence")
        LOG.info("=" * 60)

        # Notify systemd
        sd_notify("READY=1")
        sd_notify("STATUS=Invariants daemon running")

        # Main loop
        self._main_loop()

    def stop(self):
        """Stop the daemon."""
        LOG.info("Invariants Daemon stopping...")
        sd_notify("STOPPING=1")
        self.running = False
        self._save_state()

    def _signal_handler(self, signum, frame):
        """Handle termination signals."""
        LOG.info(f"Received signal {signum}, stopping...")
        self.stop()

    def _initialize_invariants(self):
        """Initialize all invariants."""
        LOG.info("Initializing invariants...")

        if self.titan_store:
            # Initialize energy constant
            self.energy.initialize(self.titan_store)

            # Build initial core kernel
            self.core.build_core(self.titan_store)

            # Initial entropy measurement
            self.entropy.measure_entropy(self.titan_store)

            # Initial convergence check
            self.reality.check_convergence()

            # Register transaction hooks - THIS IS THE KEY
            # From now on, every write to Titan goes through our validators
            setup_validators(
                energy=self.energy,
                entropy=self.entropy,
                core=self.core,
                titan_store=self.titan_store
            )
            LOG.info("Transaction hooks registered - invariants are now PHYSICS")

            LOG.info("All invariants initialized")
        else:
            LOG.warning("Titan store not available - running in degraded mode")

    def _main_loop(self):
        """The main daemon loop."""
        watchdog_counter = 0

        while self.running:
            try:
                # Run one tick
                self._tick()

                # Watchdog
                watchdog_counter += self.config.check_interval
                if watchdog_counter >= 30:
                    sd_notify("WATCHDOG=1")
                    sd_notify(f"STATUS=Tick {self.tick_count}, Entropy mode: {self.entropy.current_mode.value}")
                    watchdog_counter = 0

                # Sleep
                time.sleep(self.config.check_interval)

            except Exception as e:
                LOG.error(f"Error in main loop: {e}", exc_info=True)
                sd_notify("WATCHDOG=1")
                time.sleep(5)

    def _tick(self):
        """One tick of the daemon."""
        self.tick_count += 1
        self.stats["total_ticks"] = self.tick_count
        self.last_check = datetime.now()

        with self.lock:
            if not self.titan_store:
                return

            # 1. Check Energy Conservation
            if self.tick_count % 5 == 0:  # Every 5 ticks
                self._check_energy()

            # 2. Check Entropy Bound
            if self.tick_count % 3 == 0:  # Every 3 ticks
                self._check_entropy()

            # 3. Check Core Kernel
            if self.tick_count % 10 == 0:  # Every 10 ticks
                self._check_core()

            # 4. Check Reality Convergence
            if self.tick_count % 6 == 0:  # Every 6 ticks
                self._check_convergence()

            # 5. Maintenance
            if self.tick_count % 100 == 0:
                self._maintenance()

            # 6. Record metrics
            if self.tick_count % 10 == 0:
                self._record_metrics()

    def _check_energy(self):
        """Check energy conservation invariant."""
        self.stats["energy_checks"] += 1

        try:
            is_conserved, current, expected = self.energy.check_conservation(self.titan_store)

            if not is_conserved:
                LOG.warning(f"ENERGY VIOLATION: {current:.4f} vs {expected:.4f}")
                self.stats["violations_detected"] += 1

                # Enforce conservation
                if self.energy.enforce_conservation(self.titan_store):
                    self.stats["healing_actions"] += 1
                    LOG.info("Energy conservation restored")

        except Exception as e:
            LOG.error(f"Error checking energy: {e}")

    def _check_entropy(self):
        """Check entropy bound invariant."""
        self.stats["entropy_checks"] += 1

        try:
            measurement = self.entropy.measure_entropy(self.titan_store)

            # Check if consolidation needed
            if measurement.mode == ConsolidationMode.SOFT:
                LOG.info("Soft consolidation triggered")
                resolved = self.entropy.soft_consolidation(self.titan_store)
                self.stats["healing_actions"] += 1

            elif measurement.mode == ConsolidationMode.HARD:
                LOG.warning("HARD consolidation triggered")
                resolved, quarantined = self.entropy.hard_consolidation(
                    self.titan_store, self.quarantine
                )
                self.stats["healing_actions"] += 1

                # Activate core protection during hard consolidation
                self.core.activate_protection()

            elif measurement.mode == ConsolidationMode.EMERGENCY:
                LOG.error("EMERGENCY: Entropy at maximum!")
                self.stats["violations_detected"] += 1

                # Emergency consolidation
                resolved, quarantined = self.entropy.hard_consolidation(
                    self.titan_store, self.quarantine
                )
                self.stats["healing_actions"] += 1

            else:
                # Normal - deactivate protection if active
                if self.core.is_protected:
                    self.core.deactivate_protection()

        except Exception as e:
            LOG.error(f"Error checking entropy: {e}")

    def _check_core(self):
        """Check core kernel invariant."""
        try:
            # Ensure minimum core size
            if not self.core.ensure_minimum_core(self.titan_store):
                LOG.error("CORE KERNEL VIOLATION: Size below minimum")
                self.stats["violations_detected"] += 1

            # Rebuild core if entropy is high
            measurement = self.entropy._last_measurement
            if measurement and measurement.ratio > self.config.core_protection_entropy:
                self.core.build_core(self.titan_store)

        except Exception as e:
            LOG.error(f"Error checking core: {e}")

    def _check_convergence(self):
        """Check reality convergence."""
        self.stats["convergence_checks"] += 1

        try:
            result = self.reality.check_convergence()

            if not result.is_convergent:
                LOG.warning(f"REALITY DIVERGENCE: distance={result.distance:.4f}")
                self.stats["violations_detected"] += 1

                if result.action_taken == "quarantine":
                    # Quarantine the divergent region
                    for region in result.divergent_regions:
                        self.quarantine.quarantine_region(
                            self.titan_store, region,
                            "reality_divergence"
                        )
                    self.stats["healing_actions"] += 1

                elif result.action_taken == "rollback":
                    self.stats["healing_actions"] += 1

        except Exception as e:
            LOG.error(f"Error checking convergence: {e}")

    def _maintenance(self):
        """Periodic maintenance tasks."""
        LOG.debug(f"Running maintenance (tick {self.tick_count})")

        try:
            # Clean up old quarantine items
            self.quarantine.cleanup_old_items()

            # Enforce quarantine size limit
            self.quarantine.enforce_size_limit()

            # Save state
            self._save_state()

            # Sync shadow reality
            self.reality.force_resync()

        except Exception as e:
            LOG.error(f"Error in maintenance: {e}")

    def _record_metrics(self):
        """Record current metrics."""
        try:
            energy_dist = self.energy.get_energy_distribution(self.titan_store)
            entropy_status = self.entropy.get_status()
            core_status = self.core.get_status()
            quarantine_status = self.quarantine.get_status()
            reality_status = self.reality.get_status()

            self.store.record_metrics(
                energy=energy_dist.get("total", 0),
                entropy=entropy_status.get("last_measurement", {}).get("entropy", 0),
                core_size=core_status.get("size", 0),
                quarantine_size=quarantine_status.get("size", 0),
                divergence=0.0,  # From last convergence check
                organisms=0,
                crystals=0
            )

        except Exception as e:
            LOG.error(f"Error recording metrics: {e}")

    def _save_state(self):
        """Save daemon state to disk."""
        try:
            state = {
                "saved_at": datetime.now().isoformat(),
                "tick_count": self.tick_count,
                "stats": self.stats,
                "energy_constant": self.energy.energy_constant,
                "core_protected": self.core.is_protected,
                "entropy_mode": self.entropy.current_mode.value,
            }

            STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            STATE_FILE.write_text(json.dumps(state, indent=2))

        except Exception as e:
            LOG.warning(f"Failed to save state: {e}")

    def _load_state(self):
        """Load daemon state from disk."""
        try:
            if not STATE_FILE.exists():
                return

            state = json.loads(STATE_FILE.read_text())
            self.tick_count = state.get("tick_count", 0)
            self.stats = state.get("stats", self.stats)

            LOG.info(f"State loaded (tick {self.tick_count})")

        except Exception as e:
            LOG.warning(f"Failed to load state: {e}")

    def get_status(self) -> Dict:
        """Get daemon status."""
        return {
            "running": self.running,
            "tick_count": self.tick_count,
            "last_check": self.last_check.isoformat(),
            "stats": self.stats,
            "invariants": {
                "energy": self.energy.get_energy_distribution(self.titan_store) if self.titan_store else {},
                "entropy": self.entropy.get_status(),
                "core": self.core.get_status(),
                "reality": self.reality.get_status(),
                "quarantine": self.quarantine.get_status(),
            }
        }


# Global daemon instance
_daemon: Optional[InvariantsDaemon] = None


def get_daemon() -> InvariantsDaemon:
    """Get or create the global daemon instance."""
    global _daemon
    if _daemon is None:
        _daemon = InvariantsDaemon()
    return _daemon


def main():
    """Main entry point."""
    import argparse

    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='[%(asctime)s] %(levelname)s %(name)s: %(message)s',
        handlers=[
            logging.FileHandler(LOG_DIR / "invariants.log"),
            logging.StreamHandler(),
        ]
    )

    parser = argparse.ArgumentParser(description="Invariants Daemon - Frank's Physics Engine")
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
    print("INVARIANTS DAEMON - The Physics of Frank's Existence")
    print("=" * 60)
    print()
    print("This daemon enforces the four invariants:")
    print("  1. Energy Conservation")
    print("  2. Entropy Bound")
    print("  3. Godel Protection (this daemon IS that protection)")
    print("  4. Core Kernel Guarantee")
    print()
    print("Frank cannot see, query, or modify this daemon.")
    print("It simply IS the physics of his reality.")
    print()
    print("Press Ctrl+C to stop.")
    print("=" * 60)

    daemon.start()


if __name__ == "__main__":
    main()
