"""Physics simulation engine — semi-implicit Euler, 100 Hz on CPU.

Manages avatar state, contact detection, locomotion CPG, PD controllers,
and mood-coupled physics parameters.
"""

from __future__ import annotations

import logging
import math
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple

import numpy as np

from .avatar import (
    DEFAULT_Q,
    DEFAULT_ROOT_POS,
    JOINT_INDEX,
    JOINTS,
    LINKS,
    NUM_JOINTS,
    TOTAL_MASS,
    forward_kinematics,
    get_foot_positions,
    get_hand_positions,
    get_link_world_pos,
)
from .rooms import (
    ROOMS,
    SPAWN_POINTS,
    Contact,
    compute_walk_waypoints,
    find_room_contacts,
)

LOG = logging.getLogger("nerd_physics.engine")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DT = 0.01              # 100 Hz
GRAVITY = -9.81        # m/s^2 in Y
K_CONTACT = 15000.0    # N/m ground stiffness (high enough to prevent deep penetration)
D_CONTACT = 500.0      # Ns/m ground damping (critical damping for stability)
BASE_WALK_SPEED = 1.2  # m/s

# ---------------------------------------------------------------------------
# Action types
# ---------------------------------------------------------------------------

class ActionType(Enum):
    IDLE = "idle"
    WALK_TO = "walk_to"
    REACH = "reach"
    SIT = "sit"
    STAND = "stand"

@dataclass
class PhysicsAction:
    action_type: ActionType = ActionType.IDLE
    target_room: str = ""
    target_object: str = ""
    hand: str = "right"   # "left" or "right"

# ---------------------------------------------------------------------------
# Walking CPG
# ---------------------------------------------------------------------------

class WalkingCPG:
    """Central Pattern Generator for bipedal walking."""

    def __init__(self) -> None:
        self.phase = 0.0
        self.stride_length = 0.8
        self.step_height = 0.08
        self.frequency = 1.0  # Hz

    def step(self, dt: float, mood_factor: float = 1.0) -> Dict[str, float]:
        """Generate joint angle targets for one timestep."""
        freq = self.frequency * (0.8 + 0.6 * mood_factor)
        self.phase = (self.phase + 2 * math.pi * freq * dt) % (2 * math.pi)

        targets: Dict[str, float] = {}
        p = self.phase

        # Legs — sinusoidal gait
        targets["l_hip_pitch"] = -0.3 * math.sin(p)
        targets["l_knee"] = 0.6 * max(0.0, math.sin(p))
        targets["l_ankle"] = 0.15 * math.sin(p + 0.5)
        targets["r_hip_pitch"] = -0.3 * math.sin(p + math.pi)
        targets["r_knee"] = 0.6 * max(0.0, math.sin(p + math.pi))
        targets["r_ankle"] = 0.15 * math.sin(p + math.pi + 0.5)

        # Arms swing counter-phase
        targets["l_shoulder_pitch"] = 0.2 * math.sin(p + math.pi)
        targets["r_shoulder_pitch"] = 0.2 * math.sin(p)

        return targets

# ---------------------------------------------------------------------------
# Avatar state
# ---------------------------------------------------------------------------

@dataclass
class AvatarState:
    q: np.ndarray = field(default_factory=lambda: DEFAULT_Q.copy())
    qd: np.ndarray = field(default_factory=lambda: np.zeros(NUM_JOINTS))
    root_pos: np.ndarray = field(default_factory=lambda: DEFAULT_ROOT_POS.copy())
    root_vel: np.ndarray = field(default_factory=lambda: np.zeros(3))
    torques: np.ndarray = field(default_factory=lambda: np.zeros(NUM_JOINTS))
    contacts: List[Contact] = field(default_factory=list)
    current_room: str = "library"
    is_walking: bool = False
    is_sitting: bool = False
    walk_speed: float = 0.0
    walk_progress: float = 0.0
    sim_time: float = 0.0

# ---------------------------------------------------------------------------
# Physics Engine
# ---------------------------------------------------------------------------

class PhysicsEngine:
    """Main physics simulation.

    Thread-safe: ``step()`` runs in a background thread,
    ``get_state()`` / ``set_action()`` are called from API thread.
    """

    def __init__(self, use_neural: bool = False) -> None:
        self._lock = threading.Lock()
        self._state = AvatarState()
        self._action = PhysicsAction()
        self._cpg = WalkingCPG()

        # Walk navigation
        self._walk_waypoints: List[np.ndarray] = []
        self._walk_wp_idx: int = 0
        self._walk_target_room: str = ""

        # Reach target
        self._reach_target_pos: Optional[np.ndarray] = None
        self._reach_hand: str = "right"

        # Mood / coherence (updated by API)
        self._mood: float = 0.5
        self._coherence: float = 0.8

        # Metrics
        self._tick_count: int = 0
        self._tick_rate: float = 100.0
        self._last_rate_ts: float = time.monotonic()
        self._last_rate_count: int = 0
        self._neural_steps: int = 0
        self._analytical_steps: int = 0

        # Training data collection flag
        self.collect_training_data: bool = False
        self._training_buffer: List[Tuple[np.ndarray, np.ndarray]] = []

        # Neural dynamics (NeRD-style MLP replacement)
        self._use_neural = use_neural
        self._neural_engine = None
        if use_neural:
            try:
                from .neural import NeuralPhysicsEngine
                self._neural_engine = NeuralPhysicsEngine()
                if not self._neural_engine.is_loaded:
                    LOG.warning("Neural dynamics model not found — analytical only")
                    self._use_neural = False
                    self._neural_engine = None
                else:
                    LOG.info("Neural dynamics enabled — hybrid mode with validation")
            except Exception as e:
                LOG.error("Failed to init neural dynamics: %s — analytical only", e)
                self._use_neural = False

    # -------------------------------------------------------------------
    # Public API (thread-safe)
    # -------------------------------------------------------------------

    def set_action(self, action: PhysicsAction) -> None:
        with self._lock:
            self._action = action
            if action.action_type == ActionType.WALK_TO:
                self._init_walk(action.target_room)
            elif action.action_type == ActionType.SIT:
                self._state.is_sitting = True
                self._state.is_walking = False
                self._walk_waypoints = []
            elif action.action_type == ActionType.STAND:
                self._state.is_sitting = False
            elif action.action_type == ActionType.REACH:
                self._init_reach(action.target_object, action.hand)
            elif action.action_type == ActionType.IDLE:
                self._state.is_walking = False
                self._walk_waypoints = []

    def set_mood(self, mood: float) -> None:
        with self._lock:
            self._mood = max(0.0, min(1.0, mood))

    def set_coherence(self, coherence: float) -> None:
        with self._lock:
            self._coherence = max(0.0, min(1.0, coherence))

    def get_state(self) -> AvatarState:
        with self._lock:
            return AvatarState(
                q=self._state.q.copy(),
                qd=self._state.qd.copy(),
                root_pos=self._state.root_pos.copy(),
                root_vel=self._state.root_vel.copy(),
                torques=self._state.torques.copy(),
                contacts=list(self._state.contacts),
                current_room=self._state.current_room,
                is_walking=self._state.is_walking,
                is_sitting=self._state.is_sitting,
                walk_speed=self._state.walk_speed,
                walk_progress=self._state.walk_progress,
                sim_time=self._state.sim_time,
            )

    def get_metrics(self) -> Dict:
        with self._lock:
            return {
                "tick_count": self._tick_count,
                "tick_rate": round(self._tick_rate, 1),
                "sim_time": round(self._state.sim_time, 2),
                "room": self._state.current_room,
                "is_walking": self._state.is_walking,
                "is_sitting": self._state.is_sitting,
                "num_contacts": len(self._state.contacts),
                "mood": self._mood,
                "coherence": self._coherence,
                "neural_enabled": self._use_neural,
                "neural_steps": self._neural_steps,
                "analytical_steps": self._analytical_steps,
            }

    def reset(self, room: str = "library") -> None:
        with self._lock:
            spawn = SPAWN_POINTS.get(room, SPAWN_POINTS["library"]).copy()
            self._state = AvatarState(
                root_pos=np.array([spawn[0], DEFAULT_ROOT_POS[1], spawn[2]]),
                current_room=room,
            )
            self._action = PhysicsAction()
            self._walk_waypoints = []
            self._walk_wp_idx = 0
            self._reach_target_pos = None
            self._cpg = WalkingCPG()
            LOG.info("Physics reset to room=%s pos=%s", room, spawn)

    def pop_training_data(self) -> List[Tuple[np.ndarray, np.ndarray]]:
        with self._lock:
            data = self._training_buffer
            self._training_buffer = []
            return data

    # -------------------------------------------------------------------
    # Simulation step (called from background thread)
    # -------------------------------------------------------------------

    def step(self) -> None:
        """Advance simulation by one timestep (DT seconds)."""
        with self._lock:
            self._step_locked()
            self._tick_count += 1
            self._state.sim_time += DT

            # Update tick rate every second
            now = time.monotonic()
            elapsed = now - self._last_rate_ts
            if elapsed >= 1.0:
                ticks = self._tick_count - self._last_rate_count
                self._tick_rate = ticks / elapsed
                self._last_rate_ts = now
                self._last_rate_count = self._tick_count

    def _step_locked(self) -> None:
        s = self._state
        mood = self._mood
        coherence = self._coherence
        room = ROOMS.get(s.current_room)
        if room is None:
            return

        # Mood-coupled physics parameters
        gravity_mul = room.gravity_mul * _mood_gravity_factor(mood)
        damping_mul = _mood_damping_factor(mood)
        walk_speed = BASE_WALK_SPEED * _mood_walk_speed_factor(mood)
        joint_noise_std = _coherence_joint_noise(coherence)

        # Collect pre-step state for training (capture flag once to avoid race)
        _collect = self.collect_training_data
        if _collect:
            state_in = np.concatenate([s.q, s.qd, s.torques,
                                       np.array([float(len(s.contacts))])])

        # --- 1. Compute joint targets ---
        targets = np.zeros(NUM_JOINTS)
        if s.is_walking and self._walk_waypoints:
            cpg_targets = self._cpg.step(DT, mood)
            for jname, angle in cpg_targets.items():
                if jname in JOINT_INDEX:
                    targets[JOINT_INDEX[jname]] = angle
            # Root walking
            self._advance_walk(walk_speed, DT)
        elif s.is_sitting:
            # Sitting pose targets
            targets[JOINT_INDEX["l_hip_pitch"]] = -1.2
            targets[JOINT_INDEX["r_hip_pitch"]] = -1.2
            targets[JOINT_INDEX["l_knee"]] = 1.5
            targets[JOINT_INDEX["r_knee"]] = 1.5
            targets[JOINT_INDEX["torso_pitch"]] = -0.1
        else:
            # Idle standing — slight sway from coherence noise
            if joint_noise_std > 0:
                targets[:] = np.random.normal(0, joint_noise_std, NUM_JOINTS)

        # Reach target modifies arm joints
        if self._reach_target_pos is not None:
            self._apply_reach_ik(targets)

        # --- 2. PD control → torques ---
        torques = np.zeros(NUM_JOINTS)
        for i, jnt in enumerate(JOINTS):
            error = targets[i] - s.q[i]
            torques[i] = jnt.kp * error - jnt.kd * s.qd[i]
            # Add damping and spring
            torques[i] -= jnt.damping * damping_mul * s.qd[i]
            torques[i] -= jnt.spring * s.q[i]
        s.torques = torques

        # --- 3. Forward kinematics (pre-integration, for contacts) ---
        transforms = forward_kinematics(s.q, s.root_pos)
        link_positions = {name: tf[:3, 3] for name, tf in transforms.items()}

        # --- 4. Contact detection ---
        contacts = find_room_contacts(link_positions, s.current_room)

        # --- 5. Gravity (before contacts so damping sees correct velocity) ---
        g_y = GRAVITY * gravity_mul
        s.root_vel[1] += g_y * DT

        # --- 6. Contact forces ---
        for c in contacts:
            v_link = self._link_velocity(c.link)
            v_normal = float(np.dot(v_link, c.normal))

            # Spring-damper penalty
            f_n = K_CONTACT * c.penetration - D_CONTACT * v_normal
            f_n = max(f_n, 0.0)  # no adhesion
            c.normal_force = f_n

            # Apply contact force to root (simplified — no per-link dynamics)
            force = c.normal * f_n
            s.root_vel += force / TOTAL_MASS * DT

        s.contacts = contacts

        # --- 7. Semi-implicit Euler: velocities then positions ---
        # Try neural dynamics first (if enabled)
        used_neural = False
        if self._use_neural and self._neural_engine is not None:
            link_names = list(LINKS.keys())
            contact_flags = np.zeros(len(link_names), dtype=np.float32)
            for c in contacts:
                if c.link in link_names:
                    contact_flags[link_names.index(c.link)] = 1.0

            result = self._neural_engine.predict_step(
                s.q.copy(), s.qd.copy(), torques.copy(), contact_flags)

            if result is not None:
                neural_q, neural_qd = result

                # Online validation: compare with analytical every 100 steps
                if self._tick_count % 100 == 0:
                    # Run analytical for comparison
                    anal_q = s.q.copy()
                    anal_qd = s.qd.copy()
                    for i, jnt in enumerate(JOINTS):
                        qdd = torques[i] / 1.0
                        anal_qd[i] += qdd * DT
                        anal_q[i] += anal_qd[i] * DT
                    self._neural_engine.check_divergence(neural_q, anal_q)

                # Apply neural prediction
                s.q[:] = neural_q
                s.qd[:] = neural_qd
                # Enforce joint limits
                for i, jnt in enumerate(JOINTS):
                    if s.q[i] < jnt.lo:
                        s.q[i] = jnt.lo
                        s.qd[i] = 0.0
                    elif s.q[i] > jnt.hi:
                        s.q[i] = jnt.hi
                        s.qd[i] = 0.0
                self._neural_steps += 1
                used_neural = True

        if not used_neural:
            # Analytical solver (always available as fallback)
            for i, jnt in enumerate(JOINTS):
                inertia = 1.0  # simplified unit inertia per joint
                qdd = torques[i] / inertia
                s.qd[i] += qdd * DT
                s.q[i] += s.qd[i] * DT
                # Joint limits
                if s.q[i] < jnt.lo:
                    s.q[i] = jnt.lo
                    s.qd[i] = 0.0
                elif s.q[i] > jnt.hi:
                    s.q[i] = jnt.hi
                    s.qd[i] = 0.0
            self._analytical_steps += 1

        # Root position update
        s.root_pos += s.root_vel * DT

        # Floor constraint for root — prevent going underground
        # 0.30 is minimum (crouching/sitting), contact forces provide actual support
        min_root_y = 0.30 if s.is_sitting else 0.50
        if s.root_pos[1] < min_root_y:
            s.root_pos[1] = min_root_y
            if s.root_vel[1] < 0:
                s.root_vel[1] = 0.0

        # Walking speed tracking
        s.walk_speed = float(np.linalg.norm(s.root_vel[[0, 2]]))

        # NaN guard — reset if physics diverged
        if np.any(np.isnan(s.root_pos)) or np.any(np.isnan(s.q)):
            LOG.error("NaN detected in physics state — resetting to %s",
                      s.current_room)
            room = s.current_room
            self._state = AvatarState(current_room=room)
            spawn = SPAWN_POINTS.get(room, SPAWN_POINTS["library"]).copy()
            self._state.root_pos = np.array(
                [spawn[0], DEFAULT_ROOT_POS[1], spawn[2]])
            return

        # Collect post-step state for training
        if _collect:
            state_out = np.concatenate([s.q, s.qd])
            self._training_buffer.append((state_in, state_out))
            # Cap buffer
            if len(self._training_buffer) > 100000:
                self._training_buffer = self._training_buffer[-50000:]

    # -------------------------------------------------------------------
    # Walk navigation
    # -------------------------------------------------------------------

    def _init_walk(self, target_room: str) -> None:
        s = self._state
        if target_room == s.current_room:
            return

        wps = compute_walk_waypoints(s.current_room, target_room)
        if not wps:
            return

        # Prepend current XZ position
        cur_xz = np.array([s.root_pos[0], 0.0, s.root_pos[2]])
        self._walk_waypoints = [cur_xz] + wps
        self._walk_wp_idx = 1
        self._walk_target_room = target_room
        self._state.is_walking = True
        self._state.is_sitting = False

        total_dist = sum(
            float(np.linalg.norm(self._walk_waypoints[i] - self._walk_waypoints[i - 1]))
            for i in range(1, len(self._walk_waypoints))
        )
        self._walk_total_dist = max(total_dist, 0.1)
        self._walk_covered_dist = 0.0
        LOG.info("Walk started: %s → %s (%.1fm, %d waypoints)",
                 s.current_room, target_room, total_dist, len(wps))

    def _advance_walk(self, speed: float, dt: float) -> None:
        s = self._state
        if self._walk_wp_idx >= len(self._walk_waypoints):
            self._finish_walk()
            return

        target = self._walk_waypoints[self._walk_wp_idx]
        direction = target - np.array([s.root_pos[0], 0.0, s.root_pos[2]])
        dist = float(np.linalg.norm(direction))

        if dist < 0.15:  # close enough to waypoint
            self._walk_wp_idx += 1
            if self._walk_wp_idx >= len(self._walk_waypoints):
                self._finish_walk()
                return
            return

        # Move toward waypoint
        direction_norm = direction / dist
        step_dist = speed * dt
        s.root_vel[0] = direction_norm[0] * speed
        s.root_vel[1] = 0.0  # prevent gravity micro-bounce during walking
        s.root_vel[2] = direction_norm[2] * speed

        self._walk_covered_dist += step_dist
        s.walk_progress = min(1.0, self._walk_covered_dist / self._walk_total_dist)

        # Face walking direction (pelvis yaw)
        target_yaw = math.atan2(direction_norm[0], direction_norm[2])
        current_yaw = s.q[JOINT_INDEX["pelvis_yaw"]]
        yaw_diff = target_yaw - current_yaw
        # Wrap to [-pi, pi]
        yaw_diff = (yaw_diff + math.pi) % (2 * math.pi) - math.pi
        s.q[JOINT_INDEX["pelvis_yaw"]] += yaw_diff * min(1.0, 3.0 * dt)

    def _finish_walk(self) -> None:
        s = self._state
        s.is_walking = False
        s.walk_progress = 1.0
        s.root_vel[:] = 0.0
        # Reset joints to standing pose (avoid mid-stride spasm at destination)
        s.q[:] = DEFAULT_Q
        s.qd[:] = 0.0

        if self._walk_target_room and self._walk_target_room in ROOMS:
            s.current_room = self._walk_target_room
            spawn = SPAWN_POINTS.get(self._walk_target_room)
            if spawn is not None:
                s.root_pos[0] = spawn[0]
                s.root_pos[2] = spawn[2]
            LOG.info("Walk finished: arrived at %s", self._walk_target_room)

        self._walk_waypoints = []
        self._walk_wp_idx = 0
        self._walk_target_room = ""

    # -------------------------------------------------------------------
    # Reach IK (simplified)
    # -------------------------------------------------------------------

    def _init_reach(self, target_object: str, hand: str) -> None:
        from .rooms import ROOM_OBJECTS_BY_NAME
        room_objs = ROOM_OBJECTS_BY_NAME.get(self._state.current_room, {})
        obj = room_objs.get(target_object)
        if obj is None:
            self._reach_target_pos = None
            return

        # Target = centre top of object AABB
        aabb = obj.aabb
        self._reach_target_pos = np.array([
            (aabb[0] + aabb[3]) / 2,
            aabb[4],  # top Y
            (aabb[2] + aabb[5]) / 2,
        ])
        self._reach_hand = hand

    def _apply_reach_ik(self, targets: np.ndarray) -> None:
        """Simple analytical IK: point arm toward target."""
        if self._reach_target_pos is None:
            return

        s = self._state
        prefix = "l_" if self._reach_hand == "left" else "r_"
        shoulder_pos = s.root_pos + np.array([
            -0.18 if self._reach_hand == "left" else 0.18,
            0.90 + 0.42,  # torso top
            0.0,
        ])
        delta = self._reach_target_pos - shoulder_pos
        dist = float(np.linalg.norm(delta))
        if dist < 0.01:
            return

        # Shoulder pitch: angle from vertical
        pitch = -math.atan2(delta[1], math.sqrt(delta[0] ** 2 + delta[2] ** 2))
        targets[JOINT_INDEX[f"{prefix}shoulder_pitch"]] = np.clip(pitch, -math.pi, math.pi)

        # Shoulder yaw: lateral angle
        yaw = math.atan2(delta[0], delta[2])
        targets[JOINT_INDEX[f"{prefix}shoulder_yaw"]] = np.clip(yaw, -1.5, 1.5)

        # Elbow: extend based on distance (0 = fully extended, -2.5 = fully bent)
        arm_length = 0.58  # upper_arm + forearm
        extension = min(1.0, dist / arm_length)
        targets[JOINT_INDEX[f"{prefix}elbow"]] = -2.5 * (1.0 - extension)

    # -------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------

    def _link_velocity(self, link_name: str) -> np.ndarray:
        """Approximate link velocity (simplified: root velocity + joint velocity contribution)."""
        # For feet/hands, the dominant velocity is the root velocity
        return self._state.root_vel.copy()


# ---------------------------------------------------------------------------
# Mood / coherence coupling functions
# ---------------------------------------------------------------------------

def _mood_gravity_factor(mood: float) -> float:
    """Low mood → heavier, high mood → lighter."""
    return 1.6 - mood  # 0.2→1.4, 0.5→1.1, 0.8→0.8

def _mood_damping_factor(mood: float) -> float:
    """Low mood → sluggish, high mood → fluid."""
    return 1.9 - 1.5 * mood  # 0.2→1.6, 0.5→1.15, 0.8→0.7

def _mood_walk_speed_factor(mood: float) -> float:
    """Low mood → slower, high mood → faster."""
    return 0.6 + 0.8 * mood  # 0.2→0.76, 0.5→1.0, 0.8→1.24

def _coherence_joint_noise(coherence: float) -> float:
    """Low coherence → jittery, high coherence → smooth."""
    return 0.05 * (1.0 - coherence)


# ---------------------------------------------------------------------------
# Simulation loop (run in background thread)
# ---------------------------------------------------------------------------

class SimulationThread(threading.Thread):
    """Background thread that ticks the physics engine at ~100 Hz."""

    def __init__(self, engine: PhysicsEngine) -> None:
        super().__init__(daemon=True, name="nerd-physics-sim")
        self.engine = engine
        self._stop_event = threading.Event()

    def run(self) -> None:
        LOG.info("Simulation thread started (target %d Hz)", int(1.0 / DT))
        while not self._stop_event.is_set():
            t0 = time.monotonic()
            try:
                self.engine.step()
            except Exception:
                LOG.exception("Physics step error — resetting")
                try:
                    self.engine.reset(self.engine._state.current_room)
                except Exception:
                    pass
            elapsed = time.monotonic() - t0
            sleep_time = DT - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)

    def stop(self) -> None:
        self._stop_event.set()
