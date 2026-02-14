#!/usr/bin/env python3
"""
TRANSACTION HOOKS - Invariant Enforcement at Write Time
========================================================

This is where invariants become PHYSICS, not rules.

Every write to Titan passes through these hooks.
If a hook rejects the write, it simply doesn't happen.
Frank can't override, disable, or even see this.

Hook Types:
- PRE_WRITE: Called before write, can reject
- POST_WRITE: Called after write, for bookkeeping
- PRE_DELETE: Called before delete, can reject

Usage:
    from services.invariants.hooks import get_hook_registry, HookType

    def my_validator(operation: str, data: dict) -> tuple[bool, str]:
        if violates_physics(data):
            return False, "Energy conservation violated"
        return True, ""

    registry = get_hook_registry()
    registry.register(HookType.PRE_WRITE, my_validator, priority=10)
"""

import logging
import threading
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Dict, List, Optional, Tuple, Any

LOG = logging.getLogger("invariants.hooks")


class HookType(Enum):
    """Types of transaction hooks."""
    PRE_WRITE = "pre_write"      # Before any write (node, edge, claim)
    POST_WRITE = "post_write"    # After successful write
    PRE_DELETE = "pre_delete"    # Before any delete
    POST_DELETE = "post_delete"  # After successful delete


@dataclass
class HookResult:
    """Result of a hook execution."""
    allowed: bool
    reason: str = ""
    hook_name: str = ""


# Hook function signature: (operation: str, data: dict) -> (allowed: bool, reason: str)
HookFunction = Callable[[str, Dict[str, Any]], Tuple[bool, str]]


class TransactionHookRegistry:
    """
    Central registry for transaction hooks.

    This is the enforcement layer that makes invariants physical.
    Hooks are called in priority order (lower = first).
    If ANY hook returns False, the operation is rejected.
    """

    def __init__(self):
        self._hooks: Dict[HookType, List[Tuple[int, str, HookFunction]]] = {
            hook_type: [] for hook_type in HookType
        }
        self._lock = threading.RLock()
        self._enabled = True
        self._stats = {
            "total_calls": 0,
            "rejections": 0,
            "by_hook": {}
        }
        LOG.info("Transaction Hook Registry initialized")

    def register(self, hook_type: HookType, hook: HookFunction,
                 priority: int = 50, name: str = None) -> str:
        """
        Register a hook.

        Args:
            hook_type: When to call the hook
            hook: Function (operation, data) -> (allowed, reason)
            priority: Lower = called first (default 50)
            name: Human-readable name for logging

        Returns:
            Hook ID for later removal
        """
        hook_name = name or f"{hook_type.value}_{id(hook)}"

        with self._lock:
            self._hooks[hook_type].append((priority, hook_name, hook))
            # Sort by priority
            self._hooks[hook_type].sort(key=lambda x: x[0])
            self._stats["by_hook"][hook_name] = {"calls": 0, "rejections": 0}

        LOG.info(f"Registered hook: {hook_name} (type={hook_type.value}, priority={priority})")
        return hook_name

    def unregister(self, hook_name: str) -> bool:
        """Remove a hook by name."""
        with self._lock:
            for hook_type in HookType:
                self._hooks[hook_type] = [
                    h for h in self._hooks[hook_type] if h[1] != hook_name
                ]
        LOG.info(f"Unregistered hook: {hook_name}")
        return True

    def execute(self, hook_type: HookType, operation: str,
                data: Dict[str, Any]) -> HookResult:
        """
        Execute all hooks of a given type.

        Args:
            hook_type: Which hooks to run
            operation: Operation name (add_node, add_edge, etc.)
            data: Operation data (the node, edge, or claim being written)

        Returns:
            HookResult with allowed=True if all hooks pass
        """
        if not self._enabled:
            return HookResult(allowed=True)

        with self._lock:
            hooks = list(self._hooks[hook_type])

        self._stats["total_calls"] += 1

        for priority, hook_name, hook in hooks:
            try:
                self._stats["by_hook"][hook_name]["calls"] += 1
                allowed, reason = hook(operation, data)

                if not allowed:
                    self._stats["rejections"] += 1
                    self._stats["by_hook"][hook_name]["rejections"] += 1

                    LOG.warning(f"Hook {hook_name} REJECTED {operation}: {reason}")
                    return HookResult(
                        allowed=False,
                        reason=reason,
                        hook_name=hook_name
                    )

            except Exception as e:
                LOG.error(f"Hook {hook_name} raised exception: {e}")
                # On error, fail safe - reject the operation
                return HookResult(
                    allowed=False,
                    reason=f"Hook error: {e}",
                    hook_name=hook_name
                )

        return HookResult(allowed=True)

    def enable(self):
        """Enable hook execution."""
        self._enabled = True
        LOG.info("Transaction hooks ENABLED")

    def disable(self):
        """Disable hook execution (for maintenance only)."""
        self._enabled = False
        LOG.warning("Transaction hooks DISABLED")

    def get_stats(self) -> Dict:
        """Get hook execution statistics."""
        return dict(self._stats)

    def list_hooks(self) -> Dict[str, List[str]]:
        """List all registered hooks."""
        with self._lock:
            return {
                hook_type.value: [h[1] for h in hooks]
                for hook_type, hooks in self._hooks.items()
            }


# Global singleton
_registry: Optional[TransactionHookRegistry] = None
_registry_lock = threading.Lock()


def get_hook_registry() -> TransactionHookRegistry:
    """Get the global hook registry (singleton)."""
    global _registry
    if _registry is None:
        with _registry_lock:
            if _registry is None:
                _registry = TransactionHookRegistry()
    return _registry


# ============================================================
# INVARIANT VALIDATORS - The Actual Physics
# ============================================================

class InvariantValidators:
    """
    Pre-built validators for the four invariants.

    These are registered with the hook registry by the daemon.
    """

    def __init__(self, energy_checker=None, entropy_checker=None,
                 core_checker=None):
        self.energy = energy_checker
        self.entropy = entropy_checker
        self.core = core_checker
        self._titan_store = None

    def set_titan_store(self, titan_store):
        """Set reference to Titan store for validation queries."""
        self._titan_store = titan_store

    def validate_energy(self, operation: str, data: Dict) -> Tuple[bool, str]:
        """
        Energy conservation validator.

        Checks that the operation won't create energy from nothing.
        """
        if not self.energy or not self._titan_store:
            return True, ""

        try:
            # For adds: check if we have enough "free" energy
            if operation in ("add_node", "add_claim"):
                # Get current energy state
                is_conserved, current, expected = self.energy.check_conservation(
                    self._titan_store
                )

                # If already violated, reject new writes
                if not is_conserved:
                    delta = abs(current - expected) / expected if expected > 0 else 0
                    if delta > 0.1:  # More than 10% off
                        return False, f"Energy conservation violated: {delta:.1%} deviation"

            return True, ""

        except Exception as e:
            LOG.error(f"Energy validation error: {e}")
            return True, ""  # Fail open on errors

    def validate_entropy(self, operation: str, data: Dict) -> Tuple[bool, str]:
        """
        Entropy bound validator.

        Checks that adding this knowledge won't push entropy over the limit.
        """
        if not self.entropy or not self._titan_store:
            return True, ""

        try:
            # Check current entropy
            measurement = self.entropy.measure_entropy(self._titan_store)

            # If in HARD or EMERGENCY mode, reject new writes
            from .entropy import ConsolidationMode
            if measurement.mode in (ConsolidationMode.HARD, ConsolidationMode.EMERGENCY):
                return False, f"Entropy at {measurement.ratio:.0%} - system in consolidation mode"

            # If approaching limit (>85%), reject low-confidence writes
            if measurement.ratio > 0.85:
                confidence = data.get("confidence", 0.5)
                if confidence < 0.3:
                    return False, f"Entropy high ({measurement.ratio:.0%}), rejecting low-confidence write"

            return True, ""

        except Exception as e:
            LOG.error(f"Entropy validation error: {e}")
            return True, ""

    def validate_core(self, operation: str, data: Dict) -> Tuple[bool, str]:
        """
        Core kernel validator.

        Prevents deletion or modification of core knowledge.
        """
        if not self.core:
            return True, ""

        try:
            # For deletes: check if target is in core
            if operation in ("delete_node", "delete"):
                node_id = data.get("id") or data.get("node_id")
                if node_id and self.core.is_in_core(node_id):
                    return False, f"Cannot delete core kernel member: {node_id}"

            # For updates: check if reducing confidence of core member
            if operation in ("update_node", "add_node"):
                node_id = data.get("id")
                new_confidence = data.get("confidence", 1.0)

                if node_id and self.core.is_in_core(node_id):
                    if new_confidence < 0.5:
                        return False, f"Cannot reduce core kernel confidence below 0.5"

            return True, ""

        except Exception as e:
            LOG.error(f"Core validation error: {e}")
            return True, ""

    def register_all(self):
        """Register all invariant validators with the hook registry."""
        registry = get_hook_registry()

        # Energy - highest priority (physics comes first)
        registry.register(
            HookType.PRE_WRITE,
            self.validate_energy,
            priority=10,
            name="invariant_energy"
        )

        # Entropy - second priority
        registry.register(
            HookType.PRE_WRITE,
            self.validate_entropy,
            priority=20,
            name="invariant_entropy"
        )

        # Core kernel - for deletes
        registry.register(
            HookType.PRE_DELETE,
            self.validate_core,
            priority=10,
            name="invariant_core_delete"
        )

        # Core kernel - for writes that might reduce confidence
        registry.register(
            HookType.PRE_WRITE,
            self.validate_core,
            priority=30,
            name="invariant_core_write"
        )

        LOG.info("All invariant validators registered")


# Global validators instance
_validators: Optional[InvariantValidators] = None


def get_validators() -> InvariantValidators:
    """Get the global validators instance."""
    global _validators
    if _validators is None:
        _validators = InvariantValidators()
    return _validators


def setup_validators(energy, entropy, core, titan_store):
    """
    Set up validators with the actual invariant checkers.

    Called by the daemon after initialization.
    """
    global _validators
    _validators = InvariantValidators(energy, entropy, core)
    _validators.set_titan_store(titan_store)
    _validators.register_all()
    LOG.info("Invariant validators configured and registered")
