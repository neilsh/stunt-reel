"""DOS-era math helpers used by the TAC client.

Mirrors the Rust helpers in stunt-core (`flm::interpolate` and
`ActorTransform::compute_world_matrix`) and is guarded against drift by
tests/fixtures/dos_math_goldens.json.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = [
    "bam_to_radians",
    "compute_world_matrix",
    "focal_to_fov_y",
    "quat_from_euler",
    "quat_norm",
    "quat_norm_diff",
    "quat_normalize",
    "vec3_sub",
]


def bam_to_radians(raw_u16: int) -> float:
    """Convert a 16-bit Binary Angular Measurement (BAM) to radians [0, 2*pi)."""
    return (float(raw_u16 & 0xFFFF) / 65536.0) * (2.0 * math.pi)


def focal_to_fov_y(focal_dist: float) -> float:
    """Convert Stunt Island integer focal distance scalar to vertical FOV in degrees.

    Uses aspect-corrected half-height H_half = 120.0 for 320x240 (4:3) Mode 13h:
    FOV_y = 2 * arctan(120.0 / focal_dist) * (180.0 / pi).
    """
    if focal_dist <= 0.0:
        raise ValueError("focal_dist must be positive")
    return 2.0 * math.atan(120.0 / focal_dist) * (180.0 / math.pi)


def quat_from_euler(yaw: float, pitch: float, roll: float) -> list[float]:
    """Compute unit quaternion [x, y, z, w] from Euler angles under Invariant [I1].

    Rotations conform to Invariant [I1] metric right-handed basis:
      - Pitch theta: rotation around X axis (+X Right), positive pitch tilts +Y toward -Z.
      - Yaw psi:     rotation around Y axis (+Y Up), positive yaw turns +X toward +Z.
      - Roll phi:    rotation around Z axis (+Z Backward), positive roll banks +X toward +Y.

    Intrinsic rotation sequence: q = q_yaw(Y) * q_pitch(X) * q_roll(Z).
    Guarantees unit quaternion invariant: | ||q|| - 1.0 | < 1e-4.
    """
    cy = math.cos(yaw * 0.5)
    sy = math.sin(yaw * 0.5)
    cp = math.cos(pitch * 0.5)
    sp = math.sin(pitch * 0.5)
    cr = math.cos(roll * 0.5)
    sr = math.sin(roll * 0.5)

    qx = -(sp * cy * cr + cp * sy * sr)
    qy = -(cp * sy * cr - sp * cy * sr)
    qz = cp * cy * sr - sp * sy * cr
    qw = cp * cy * cr + sp * sy * sr

    return quat_normalize([qx, qy, qz, qw])


def quat_norm(q: Sequence[float]) -> float:
    """Compute Euclidean norm of quaternion [x, y, z, w]."""
    return math.sqrt(q[0] * q[0] + q[1] * q[1] + q[2] * q[2] + q[3] * q[3])


def quat_norm_diff(q: Sequence[float]) -> float:
    """Compute deviation from unit length: | ||q|| - 1.0 |."""
    return abs(quat_norm(q) - 1.0)


def quat_normalize(q: Sequence[float]) -> list[float]:
    """Normalize quaternion [x, y, z, w] to unit length."""
    norm = quat_norm(q)
    if norm <= 1e-12:
        return [0.0, 0.0, 0.0, 1.0]
    inv = 1.0 / norm
    return [q[0] * inv, q[1] * inv, q[2] * inv, q[3] * inv]


def vec3_sub(a: Sequence[float], b: Sequence[float]) -> list[float]:
    """Subtract vector b from vector a."""
    return [a[0] - b[0], a[1] - b[1], a[2] - b[2]]


def compute_world_matrix(position: Sequence[float], quat: Sequence[float]) -> list[float]:
    """Compute 16-element column-major 4x4 world transformation matrix.

    Directly matches Rust ActorTransform::compute_world_matrix() in contracts/trajectory.rs.
    """
    qx, qy, qz, qw = quat[0], quat[1], quat[2], quat[3]
    tx, ty, tz = position[0], position[1], position[2]

    x2 = qx + qx
    y2 = qy + qy
    z2 = qz + qz
    xx = qx * x2
    xy = qx * y2
    xz = qx * z2
    yy = qy * y2
    yz = qy * z2
    zz = qz * z2
    wx = qw * x2
    wy = qw * y2
    wz = qw * z2

    return [
        1.0 - (yy + zz),
        xy + wz,
        xz - wy,
        0.0,
        xy - wz,
        1.0 - (xx + zz),
        yz + wx,
        0.0,
        xz + wy,
        yz - wx,
        1.0 - (xx + yy),
        0.0,
        tx,
        ty,
        tz,
        1.0,
    ]
