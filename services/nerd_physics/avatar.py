"""Frank's articulated rigid-body avatar.

15 links, 18 1-DOF revolute joints, 70 kg total.
Kinematic tree rooted at pelvis (floating base).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

import numpy as np

# ---------------------------------------------------------------------------
# Link definitions
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class LinkDef:
    name: str
    parent: str          # "" for root
    mass: float          # kg
    length: float        # m (along local Y for limbs, along local Z for torso)
    width: float         # m
    joint_offset: np.ndarray = field(default_factory=lambda: np.zeros(3))

LINKS: Dict[str, LinkDef] = {}

def _link(name: str, parent: str, mass: float, length: float, width: float,
          offset: Tuple[float, float, float] = (0.0, 0.0, 0.0)) -> None:
    LINKS[name] = LinkDef(name, parent, mass, length, width, np.array(offset, dtype=np.float64))

# Root
_link("pelvis",       "",             12.0, 0.20, 0.30, (0, 0, 0))
# Torso chain
_link("torso",        "pelvis",       18.0, 0.45, 0.30, (0, 0.20, 0))   # top of pelvis
_link("head",         "torso",         5.0, 0.20, 0.18, (0, 0.45, 0))   # top of torso
# Left arm
_link("l_upper_arm",  "torso",         2.5, 0.30, 0.07, (-0.18, 0.42, 0))
_link("l_forearm",    "l_upper_arm",   1.5, 0.28, 0.06, (0, -0.30, 0))
_link("l_hand",       "l_forearm",     0.5, 0.10, 0.08, (0, -0.28, 0))
# Right arm
_link("r_upper_arm",  "torso",         2.5, 0.30, 0.07, (0.18, 0.42, 0))
_link("r_forearm",    "r_upper_arm",   1.5, 0.28, 0.06, (0, -0.30, 0))
_link("r_hand",       "r_forearm",     0.5, 0.10, 0.08, (0, -0.28, 0))
# Left leg
_link("l_thigh",      "pelvis",        8.0, 0.42, 0.10, (-0.10, 0.0, 0))
_link("l_shin",       "l_thigh",       4.0, 0.40, 0.08, (0, -0.42, 0))
_link("l_foot",       "l_shin",        1.0, 0.25, 0.10, (0, -0.40, 0))
# Right leg
_link("r_thigh",      "pelvis",        8.0, 0.42, 0.10, (0.10, 0.0, 0))
_link("r_shin",       "r_thigh",       4.0, 0.40, 0.08, (0, -0.42, 0))
_link("r_foot",       "r_shin",        1.0, 0.25, 0.10, (0, -0.40, 0))

TOTAL_MASS = sum(lk.mass for lk in LINKS.values())  # 70.0 kg

# ---------------------------------------------------------------------------
# Joint definitions
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class JointDef:
    name: str
    parent_link: str
    child_link: str
    axis: np.ndarray       # unit vector in parent frame
    lo: float              # lower limit (rad)
    hi: float              # upper limit (rad)
    damping: float         # Ns/rad
    spring: float          # N/rad (restoring torque toward zero)
    kp: float              # PD proportional gain
    kd: float              # PD derivative gain

JOINTS: List[JointDef] = []
JOINT_INDEX: Dict[str, int] = {}

def _joint(name: str, parent_link: str, child_link: str,
           axis: Tuple[float, float, float],
           lo: float, hi: float, damping: float, spring: float,
           kp: float = 200.0, kd: float = 20.0) -> None:
    idx = len(JOINTS)
    JOINTS.append(JointDef(
        name, parent_link, child_link,
        np.array(axis, dtype=np.float64), lo, hi, damping, spring, kp, kd,
    ))
    JOINT_INDEX[name] = idx

# Pelvis (floating base orientation)
_joint("pelvis_yaw",   "pelvis", "pelvis",  (0, 1, 0), -math.pi, math.pi, 5.0, 0.0, 100.0, 15.0)
_joint("pelvis_pitch", "pelvis", "pelvis",  (1, 0, 0), -0.5, 0.5,        8.0, 2.0, 100.0, 15.0)
# Torso
_joint("torso_pitch",  "pelvis", "torso",   (1, 0, 0), -0.4, 0.3,  6.0, 3.0, 150.0, 18.0)
# Neck
_joint("neck_pitch",   "torso",  "head",    (1, 0, 0), -0.5, 0.5,  2.0, 1.0, 50.0, 10.0)
_joint("neck_yaw",     "torso",  "head",    (0, 1, 0), -1.2, 1.2,  2.0, 0.5, 50.0, 10.0)
# Left arm
_joint("l_shoulder_pitch", "torso", "l_upper_arm", (1, 0, 0), -math.pi, math.pi, 3.0, 0.0, 50.0, 10.0)
_joint("l_shoulder_yaw",   "torso", "l_upper_arm", (0, 1, 0), -1.5, 1.5,        3.0, 0.0, 50.0, 10.0)
_joint("l_elbow",          "l_upper_arm", "l_forearm", (1, 0, 0), -2.5, 0.0,    2.0, 0.0, 50.0, 10.0)
# Right arm
_joint("r_shoulder_pitch", "torso", "r_upper_arm", (1, 0, 0), -math.pi, math.pi, 3.0, 0.0, 50.0, 10.0)
_joint("r_shoulder_yaw",   "torso", "r_upper_arm", (0, 1, 0), -1.5, 1.5,        3.0, 0.0, 50.0, 10.0)
_joint("r_elbow",          "r_upper_arm", "r_forearm", (1, 0, 0), -2.5, 0.0,    2.0, 0.0, 50.0, 10.0)
# Left leg
_joint("l_hip_pitch",  "pelvis", "l_thigh", (1, 0, 0), -1.5, 1.0, 5.0, 0.0, 200.0, 20.0)
_joint("l_hip_yaw",    "pelvis", "l_thigh", (0, 1, 0), -0.5, 0.5, 5.0, 0.0, 200.0, 20.0)
_joint("l_knee",       "l_thigh", "l_shin", (1, 0, 0),  0.0, 2.5, 4.0, 0.0, 200.0, 20.0)
_joint("l_ankle",      "l_shin",  "l_foot", (1, 0, 0), -0.5, 0.5, 3.0, 1.0, 150.0, 15.0)
# Right leg
_joint("r_hip_pitch",  "pelvis", "r_thigh", (1, 0, 0), -1.5, 1.0, 5.0, 0.0, 200.0, 20.0)
_joint("r_hip_yaw",    "pelvis", "r_thigh", (0, 1, 0), -0.5, 0.5, 5.0, 0.0, 200.0, 20.0)
_joint("r_knee",       "r_thigh", "r_shin", (1, 0, 0),  0.0, 2.5, 4.0, 0.0, 200.0, 20.0)
_joint("r_ankle",      "r_shin",  "r_foot", (1, 0, 0), -0.5, 0.5, 3.0, 1.0, 150.0, 15.0)

NUM_JOINTS = len(JOINTS)  # 19

# Pre-built lookup: (parent_link, child_link) -> list of (JointDef, joint_index)
# Handles multi-joint links (e.g. shoulder pitch+yaw, hip pitch+yaw, neck pitch+yaw)
_JOINTS_BY_LINK_PAIR: Dict[Tuple[str, str], List[Tuple['JointDef', int]]] = {}
for _j in JOINTS:
    _key = (_j.parent_link, _j.child_link)
    if _key not in _JOINTS_BY_LINK_PAIR:
        _JOINTS_BY_LINK_PAIR[_key] = []
    _JOINTS_BY_LINK_PAIR[_key].append((_j, JOINT_INDEX[_j.name]))

# ---------------------------------------------------------------------------
# Forward Kinematics helpers
# ---------------------------------------------------------------------------

def _rot_axis(axis: np.ndarray, angle: float) -> np.ndarray:
    """Rodrigues rotation matrix for *unit* axis and angle (rad)."""
    c, s = math.cos(angle), math.sin(angle)
    t = 1.0 - c
    x, y, z = axis
    return np.array([
        [t * x * x + c,     t * x * y - s * z, t * x * z + s * y],
        [t * x * y + s * z, t * y * y + c,     t * y * z - s * x],
        [t * x * z - s * y, t * y * z + s * x, t * z * z + c],
    ], dtype=np.float64)


def _make_transform(R: np.ndarray, t: np.ndarray) -> np.ndarray:
    """Build 4x4 homogeneous transform from 3x3 rotation + 3-vec translation."""
    T = np.eye(4, dtype=np.float64)
    T[:3, :3] = R
    T[:3, 3] = t
    return T


def forward_kinematics(q: np.ndarray, root_pos: np.ndarray) -> Dict[str, np.ndarray]:
    """Compute world-frame 4x4 transforms for every link.

    Parameters
    ----------
    q : (18,) joint angles
    root_pos : (3,) world position of pelvis centre

    Returns
    -------
    Dict mapping link name -> 4x4 homogeneous transform.
    """
    transforms: Dict[str, np.ndarray] = {}

    # Pelvis — compose yaw then pitch
    R_yaw = _rot_axis(np.array([0, 1, 0]), q[JOINT_INDEX["pelvis_yaw"]])
    R_pitch = _rot_axis(np.array([1, 0, 0]), q[JOINT_INDEX["pelvis_pitch"]])
    R_pelvis = R_yaw @ R_pitch
    transforms["pelvis"] = _make_transform(R_pelvis, root_pos)

    # Helper to propagate down the tree
    def _propagate(link_name: str) -> None:
        lk = LINKS[link_name]
        parent_T = transforms[lk.parent]

        # Find ALL joints connecting parent to this link (O(1) lookup)
        joint_pairs = _JOINTS_BY_LINK_PAIR.get((lk.parent, link_name))

        if not joint_pairs:
            # Fallback: offset only
            T_local = _make_transform(np.eye(3), lk.joint_offset)
            transforms[link_name] = parent_T @ T_local
            return

        # Compose all joint rotations (e.g. shoulder pitch + yaw)
        R_combined = np.eye(3, dtype=np.float64)
        for jnt, jnt_idx in joint_pairs:
            R_combined = R_combined @ _rot_axis(jnt.axis, q[jnt_idx])
        T_local = _make_transform(R_combined, lk.joint_offset)
        transforms[link_name] = parent_T @ T_local

    # Traverse tree in definition order (parents always before children)
    for link_name in LINKS:
        if link_name == "pelvis":
            continue
        _propagate(link_name)

    return transforms


def get_link_world_pos(transforms: Dict[str, np.ndarray], link_name: str) -> np.ndarray:
    """Extract world-space position (3,) of a link origin."""
    return transforms[link_name][:3, 3].copy()


def get_foot_positions(transforms: Dict[str, np.ndarray]) -> Tuple[np.ndarray, np.ndarray]:
    """Return (left_foot_pos, right_foot_pos) in world frame."""
    return get_link_world_pos(transforms, "l_foot"), get_link_world_pos(transforms, "r_foot")


def get_hand_positions(transforms: Dict[str, np.ndarray]) -> Tuple[np.ndarray, np.ndarray]:
    """Return (left_hand_pos, right_hand_pos) in world frame."""
    return get_link_world_pos(transforms, "l_hand"), get_link_world_pos(transforms, "r_hand")


# Default standing pose — all joints at zero except legs slightly bent
DEFAULT_Q = np.zeros(NUM_JOINTS, dtype=np.float64)
DEFAULT_Q[JOINT_INDEX["l_hip_pitch"]] = -0.1
DEFAULT_Q[JOINT_INDEX["r_hip_pitch"]] = -0.1
DEFAULT_Q[JOINT_INDEX["l_knee"]] = 0.2
DEFAULT_Q[JOINT_INDEX["r_knee"]] = 0.2
DEFAULT_Q[JOINT_INDEX["l_ankle"]] = -0.1
DEFAULT_Q[JOINT_INDEX["r_ankle"]] = -0.1

# Standing root height: calibrated so feet touch floor at Y≈0.0 with default pose
# Leg chain: thigh(0.42) + shin(0.40) ≈ 0.82m below pelvis (with slight bends)
DEFAULT_ROOT_POS = np.array([0.0, 0.82, 0.0], dtype=np.float64)
