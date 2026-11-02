"""Invariant [I1] Euler kinematics checks on the DOS math: axis mapping, orthogonality,
determinant and extreme angles.
"""

from __future__ import annotations

import math
import random

from stunt_reel.tac.dos_math import (
    compute_world_matrix,
    quat_from_euler,
    quat_norm_diff,
)

# ==============================================================================
# Invariant [I1] Euler Kinematics
# ==============================================================================


def test_euler_pitch_tilts_y_toward_neg_z() -> None:
    """Verify Invariant [I1]: Positive pitch tilts +Y toward -Z while +X is unchanged."""
    for deg in [10.0, 30.0, 45.0, 60.0, 80.0]:
        rad = math.radians(deg)
        q = quat_from_euler(yaw=0.0, pitch=rad, roll=0.0)
        assert quat_norm_diff(q) < 1e-14

        m = compute_world_matrix([0.0, 0.0, 0.0], q)
        x_prime = [m[0], m[1], m[2]]
        y_prime = [m[4], m[5], m[6]]
        z_prime = [m[8], m[9], m[10]]

        assert math.isclose(x_prime[0], 1.0, abs_tol=1e-5)
        assert math.isclose(x_prime[1], 0.0, abs_tol=1e-5)
        assert math.isclose(x_prime[2], 0.0, abs_tol=1e-5)

        assert math.isclose(y_prime[0], 0.0, abs_tol=1e-5)
        assert math.isclose(y_prime[1], math.cos(rad), abs_tol=1e-5)
        assert math.isclose(y_prime[2], -math.sin(rad), abs_tol=1e-5)
        assert y_prime[2] < 0.0

        assert math.isclose(z_prime[0], 0.0, abs_tol=1e-5)
        assert math.isclose(z_prime[1], math.sin(rad), abs_tol=1e-5)
        assert math.isclose(z_prime[2], math.cos(rad), abs_tol=1e-5)
        assert z_prime[1] > 0.0


def test_euler_yaw_turns_x_toward_pos_z() -> None:
    """Verify Invariant [I1]: Positive yaw turns +X toward +Z while +Y is unchanged."""
    for deg in [10.0, 30.0, 45.0, 60.0, 80.0]:
        rad = math.radians(deg)
        q = quat_from_euler(yaw=rad, pitch=0.0, roll=0.0)
        assert quat_norm_diff(q) < 1e-14

        m = compute_world_matrix([0.0, 0.0, 0.0], q)
        x_prime = [m[0], m[1], m[2]]
        y_prime = [m[4], m[5], m[6]]
        z_prime = [m[8], m[9], m[10]]

        assert math.isclose(y_prime[0], 0.0, abs_tol=1e-5)
        assert math.isclose(y_prime[1], 1.0, abs_tol=1e-5)
        assert math.isclose(y_prime[2], 0.0, abs_tol=1e-5)

        assert math.isclose(x_prime[0], math.cos(rad), abs_tol=1e-5)
        assert math.isclose(x_prime[1], 0.0, abs_tol=1e-5)
        assert math.isclose(x_prime[2], math.sin(rad), abs_tol=1e-5)
        assert x_prime[2] > 0.0

        assert math.isclose(z_prime[0], -math.sin(rad), abs_tol=1e-5)
        assert math.isclose(z_prime[1], 0.0, abs_tol=1e-5)
        assert math.isclose(z_prime[2], math.cos(rad), abs_tol=1e-5)
        assert z_prime[0] < 0.0


def test_euler_roll_banks_x_toward_pos_y() -> None:
    """Verify Invariant [I1]: Positive roll banks +X toward +Y while +Z is unchanged."""
    for deg in [10.0, 30.0, 45.0, 60.0, 80.0]:
        rad = math.radians(deg)
        q = quat_from_euler(yaw=0.0, pitch=0.0, roll=rad)
        assert quat_norm_diff(q) < 1e-14

        m = compute_world_matrix([0.0, 0.0, 0.0], q)
        x_prime = [m[0], m[1], m[2]]
        y_prime = [m[4], m[5], m[6]]
        z_prime = [m[8], m[9], m[10]]

        assert math.isclose(z_prime[0], 0.0, abs_tol=1e-5)
        assert math.isclose(z_prime[1], 0.0, abs_tol=1e-5)
        assert math.isclose(z_prime[2], 1.0, abs_tol=1e-5)

        assert math.isclose(x_prime[0], math.cos(rad), abs_tol=1e-5)
        assert math.isclose(x_prime[1], math.sin(rad), abs_tol=1e-5)
        assert math.isclose(x_prime[2], 0.0, abs_tol=1e-5)
        assert x_prime[1] > 0.0

        assert math.isclose(y_prime[0], -math.sin(rad), abs_tol=1e-5)
        assert math.isclose(y_prime[1], math.cos(rad), abs_tol=1e-5)
        assert math.isclose(y_prime[2], 0.0, abs_tol=1e-5)
        assert y_prime[0] < 0.0


def test_euler_matrix_orthogonality_and_determinant_1000_samples() -> None:
    """Stress test 1,000 random Euler angles: verify orthogonality (M^T M = I) and det(M) = +1.0."""
    rng = random.Random(42)  # noqa: S311

    for _ in range(1000):
        yaw = rng.uniform(-math.pi, math.pi)
        pitch = rng.uniform(-0.49 * math.pi, 0.49 * math.pi)
        roll = rng.uniform(-math.pi, math.pi)

        q = quat_from_euler(yaw=yaw, pitch=pitch, roll=roll)
        assert quat_norm_diff(q) < 1e-14

        m = compute_world_matrix([0.0, 0.0, 0.0], q)
        r0 = [m[0], m[1], m[2]]
        r1 = [m[4], m[5], m[6]]
        r2 = [m[8], m[9], m[10]]

        assert math.isclose(sum(x * x for x in r0), 1.0, abs_tol=1e-5)
        assert math.isclose(sum(x * x for x in r1), 1.0, abs_tol=1e-5)
        assert math.isclose(sum(x * x for x in r2), 1.0, abs_tol=1e-5)

        assert math.isclose(sum(a * b for a, b in zip(r0, r1, strict=True)), 0.0, abs_tol=1e-5)
        assert math.isclose(sum(a * b for a, b in zip(r0, r2, strict=True)), 0.0, abs_tol=1e-5)
        assert math.isclose(sum(a * b for a, b in zip(r1, r2, strict=True)), 0.0, abs_tol=1e-5)

        cross = [
            r1[1] * r2[2] - r1[2] * r2[1],
            r1[2] * r2[0] - r1[0] * r2[2],
            r1[0] * r2[1] - r1[1] * r2[0],
        ]
        det = sum(a * b for a, b in zip(r0, cross, strict=True))
        assert math.isclose(det, 1.0, abs_tol=1e-5)


def test_euler_extreme_angles() -> None:
    """Verify stability at extreme boundary angles (0, 180, -180, 360, 720 degrees)."""
    for ang in [0.0, math.pi, -math.pi, 2.0 * math.pi, 4.0 * math.pi]:
        for q in (
            quat_from_euler(yaw=0.0, pitch=ang, roll=0.0),
            quat_from_euler(yaw=ang, pitch=0.0, roll=0.0),
            quat_from_euler(yaw=0.0, pitch=0.0, roll=ang),
        ):
            assert quat_norm_diff(q) < 1e-14
