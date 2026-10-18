"""Pure standard library 3D mathematics utilities for Stunt Reel.

Adheres strictly to Architectural Invariants:
- [I1] Right-handed metric coordinate basis (+X right, +Y up, +Z toward viewer, -Z forward).
- [I4] Decoupled simulation ticks and sub-tick interpolation.
- [I5] Coplanar decal normal displacement.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

__all__ = [
    "bam_to_degrees",
    "bam_to_radians",
    "compute_world_matrix",
    "degrees_to_bam",
    "focal_to_fov_y",
    "fov_y_to_focal",
    "quat_from_direction_cosines",
    "quat_from_euler",
    "quat_norm",
    "quat_norm_diff",
    "quat_normalize",
    "radians_to_bam",
    "vec3_add",
    "vec3_cross",
    "vec3_displace",
    "vec3_dot",
    "vec3_length",
    "vec3_normalize",
    "vec3_scale",
    "vec3_sub",
]


def bam_to_radians(raw_u16: int) -> float:
    """Convert a 16-bit Binary Angular Measurement (BAM) to radians [0, 2*pi)."""
    return (float(raw_u16 & 0xFFFF) / 65536.0) * (2.0 * math.pi)


def radians_to_bam(rad: float) -> int:
    """Convert an angle in radians to a 16-bit BAM value."""
    two_pi = 2.0 * math.pi
    norm_rad = rad % two_pi
    if norm_rad < 0.0:
        norm_rad += two_pi
    return round((norm_rad / two_pi) * 65536.0) & 0xFFFF


def bam_to_degrees(raw_u16: int) -> float:
    """Convert a 16-bit BAM value to degrees [0, 360)."""
    return (float(raw_u16 & 0xFFFF) / 65536.0) * 360.0


def degrees_to_bam(deg: float) -> int:
    """Convert an angle in degrees to a 16-bit BAM value."""
    norm_deg = deg % 360.0
    if norm_deg < 0.0:
        norm_deg += 360.0
    return round((norm_deg / 360.0) * 65536.0) & 0xFFFF


def focal_to_fov_y(focal_dist: float) -> float:
    """Convert Stunt Island integer focal distance scalar to vertical FOV in degrees.

    Uses aspect-corrected half-height H_half = 120.0 for 320x240 (4:3) Mode 13h:
    FOV_y = 2 * arctan(120.0 / focal_dist) * (180.0 / pi).
    """
    if focal_dist <= 0.0:
        raise ValueError("focal_dist must be positive")
    return 2.0 * math.atan(120.0 / focal_dist) * (180.0 / math.pi)


def fov_y_to_focal(fov_degrees: float) -> float:
    """Convert vertical FOV in degrees back to focal distance scalar."""
    if not (0.0 < fov_degrees < 180.0):
        raise ValueError("fov_degrees must be strictly between 0 and 180")
    half_rad = math.radians(fov_degrees / 2.0)
    return 120.0 / math.tan(half_rad)


def vec3_add(a: Sequence[float], b: Sequence[float]) -> list[float]:
    """Add two 3D vectors."""
    return [a[0] + b[0], a[1] + b[1], a[2] + b[2]]


def vec3_sub(a: Sequence[float], b: Sequence[float]) -> list[float]:
    """Subtract vector b from vector a."""
    return [a[0] - b[0], a[1] - b[1], a[2] - b[2]]


def vec3_scale(v: Sequence[float], s: float) -> list[float]:
    """Scale a 3D vector by a scalar."""
    return [v[0] * s, v[1] * s, v[2] * s]


def vec3_dot(a: Sequence[float], b: Sequence[float]) -> float:
    """Compute dot product of two 3D vectors."""
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def vec3_cross(a: Sequence[float], b: Sequence[float]) -> list[float]:
    """Compute cross product of two 3D vectors adhering to [I1] right-handed basis."""
    return [
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    ]


def vec3_length(v: Sequence[float]) -> float:
    """Compute Euclidean norm (length) of a 3D vector."""
    return math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])


def vec3_normalize(v: Sequence[float]) -> list[float]:
    """Normalize a 3D vector to unit length."""
    length = vec3_length(v)
    if length <= 1e-12:
        return [0.0, 0.0, 0.0]
    inv = 1.0 / length
    return [v[0] * inv, v[1] * inv, v[2] * inv]


def vec3_displace(v: Sequence[float], normal: Sequence[float], eps: float = 0.001) -> list[float]:
    """Displace vertex along surface outward normal by epsilon meters (Invariant [I5])."""
    unit_n = vec3_normalize(normal)
    return [
        v[0] + eps * unit_n[0],
        v[1] + eps * unit_n[1],
        v[2] + eps * unit_n[2],
    ]


def quat_norm(q: Sequence[float]) -> float:
    """Compute Euclidean norm of quaternion [x, y, z, w]."""
    return math.sqrt(q[0] * q[0] + q[1] * q[1] + q[2] * q[2] + q[3] * q[3])


def quat_normalize(q: Sequence[float]) -> list[float]:
    """Normalize quaternion [x, y, z, w] to unit length."""
    norm = quat_norm(q)
    if norm <= 1e-12:
        return [0.0, 0.0, 0.0, 1.0]
    inv = 1.0 / norm
    return [q[0] * inv, q[1] * inv, q[2] * inv, q[3] * inv]


def quat_norm_diff(q: Sequence[float]) -> float:
    """Compute deviation from unit length: | ||q|| - 1.0 |."""
    return abs(quat_norm(q) - 1.0)


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


def quat_from_direction_cosines(
    matrix: Sequence[Sequence[float]] | Sequence[float],
) -> list[float]:
    """Compute normalized unit quaternion [x, y, z, w] from 3x3 direction cosine matrix.

    Accepts 3x3 nested sequence or 9-element flat row-major sequence.
    Guarantees unit quaternion invariant: | ||q|| - 1.0 | < 1e-4.
    """
    r00: float
    r01: float
    r02: float
    r10: float
    r11: float
    r12: float
    r20: float
    r21: float
    r22: float

    if len(matrix) == 3:
        row0 = matrix[0]
        row1 = matrix[1]
        row2 = matrix[2]
        if isinstance(row0, Sequence) and isinstance(row1, Sequence) and isinstance(row2, Sequence):
            r00, r01, r02 = float(row0[0]), float(row0[1]), float(row0[2])
            r10, r11, r12 = float(row1[0]), float(row1[1]), float(row1[2])
            r20, r21, r22 = float(row2[0]), float(row2[1]), float(row2[2])
        else:
            raise ValueError("Nested rows must be sequences of numbers")
    elif len(matrix) == 9:
        flat_vals: list[float] = []
        for elem in matrix:
            if isinstance(elem, (int, float)):
                flat_vals.append(float(elem))
            else:
                raise ValueError("Elements must be float or int")
        r00, r01, r02 = flat_vals[0], flat_vals[1], flat_vals[2]
        r10, r11, r12 = flat_vals[3], flat_vals[4], flat_vals[5]
        r20, r21, r22 = flat_vals[6], flat_vals[7], flat_vals[8]
    else:
        raise ValueError("Matrix must be 3x3 or flat 9 elements")

    trace = r00 + r11 + r22
    if trace > 0.0:
        s = 0.5 / math.sqrt(trace + 1.0)
        qw = 0.25 / s
        qx = (r21 - r12) * s
        qy = (r02 - r20) * s
        qz = (r10 - r01) * s
    elif (r00 > r11) and (r00 > r22):
        s = 2.0 * math.sqrt(1.0 + r00 - r11 - r22)
        qw = (r21 - r12) / s
        qx = 0.25 * s
        qy = (r01 + r10) / s
        qz = (r02 + r20) / s
    elif r11 > r22:
        s = 2.0 * math.sqrt(1.0 + r11 - r00 - r22)
        qw = (r02 - r20) / s
        qx = (r01 + r10) / s
        qy = 0.25 * s
        qz = (r12 + r21) / s
    else:
        s = 2.0 * math.sqrt(1.0 + r22 - r00 - r11)
        qw = (r10 - r01) / s
        qx = (r02 + r20) / s
        qy = (r12 + r21) / s
        qz = 0.25 * s

    return quat_normalize([qx, qy, qz, qw])


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
