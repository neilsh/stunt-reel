"""Invariant [I6] Visual Parity Pipeline and SSIM Verification.

Implements:
- Aspect ratio normalization (VGA Mode 13h 320x200 -> 320x240 4:3 physical CRT stretch, 1.2x).
- Pure standard library Structural Similarity Index (SSIM) evaluator.
- VisualParityReport adhering to Seam 4 contracts (crates/stunt-core/src/contracts/parity.rs).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

__all__ = [
    "C1_CONSTANT",
    "C2_CONSTANT",
    "PHASE1_SSIM_THRESHOLD",
    "PHASE2_SSIM_THRESHOLD",
    "VisualParityReport",
    "compute_frame_ssim",
    "compute_luminance",
    "compute_window_ssim",
    "evaluate_visual_parity",
    "rescale_mode13h_frame",
]

# Standard SSIM stability constants for 8-bit dynamic range [0, 255]
# C1 = (0.01 * 255)^2 = 6.5025
# C2 = (0.03 * 255)^2 = 58.5225
C1_CONSTANT: float = 6.5025
C2_CONSTANT: float = 58.5225

# Architectural Invariant [I6] Acceptance Thresholds
PHASE1_SSIM_THRESHOLD: float = 0.88  # Gate 1 sign-off threshold
PHASE2_SSIM_THRESHOLD: float = 0.90  # Gate 2 native engine threshold


@dataclass(slots=True)
class VisualParityReport:
    """Summary report emitted by visual regression comparators (Seam 4)."""

    film_name: str
    frames_evaluated: int
    mean_ssim: float
    min_ssim: float
    threshold: float = PHASE1_SSIM_THRESHOLD
    passed: bool = False

    def is_passing(self) -> bool:
        """Evaluate whether the report meets acceptance criteria."""
        return self.passed and self.mean_ssim >= self.threshold


def compute_luminance(r: float, g: float, b: float) -> float:
    """Compute Rec. 601 perceptual luminance from RGB in [0, 255]."""
    return 0.299 * r + 0.587 * g + 0.114 * b


def _normalize_frame_to_floats(
    frame: Sequence[int] | Sequence[float] | Sequence[Sequence[float]] | bytes,
) -> list[float]:
    """Convert arbitrary frame formats (bytes, ints, floats, RGB tuples) to flat float luminance list."""
    if isinstance(frame, (bytes, bytearray)):
        return [float(b) for b in frame]

    res: list[float] = []
    for item in frame:
        if isinstance(item, (int, float)):
            res.append(float(item))
        elif isinstance(item, Sequence) and len(item) >= 3:
            res.append(compute_luminance(float(item[0]), float(item[1]), float(item[2])))

    return res


def rescale_mode13h_frame(
    frame: Sequence[int] | Sequence[float] | Sequence[Sequence[float]] | bytes,
    width: int = 320,
    height: int = 200,
    target_height: int = 240,
    interpolation: str = "nearest",
) -> list[float]:
    """Rescale 320x200 Mode 13h raster to 320x240 physical 4:3 CRT aspect (1.2x stretch).

    Returns a flat list of 320 * 240 floating-point luminance values.
    """
    total_src = width * height
    src_pixels = _normalize_frame_to_floats(frame)[:total_src]

    # Pad if source was shorter
    if len(src_pixels) < total_src:
        src_pixels.extend([0.0] * (total_src - len(src_pixels)))

    target_pixels: list[float] = [0.0] * (width * target_height)
    scale_y = height / float(target_height)  # 200 / 240 = 5/6

    if interpolation == "bilinear":
        for y_out in range(target_height):
            src_y_f = y_out * scale_y
            y0 = int(src_y_f)
            y1 = min(y0 + 1, height - 1)
            frac_y = src_y_f - y0

            row_out_idx = y_out * width
            row_in0_idx = y0 * width
            row_in1_idx = y1 * width

            for x in range(width):
                val0 = src_pixels[row_in0_idx + x]
                val1 = src_pixels[row_in1_idx + x]
                target_pixels[row_out_idx + x] = val0 * (1.0 - frac_y) + val1 * frac_y
    else:
        # Nearest neighbor
        for y_out in range(target_height):
            y_in = int(y_out * scale_y)
            if y_in >= height:
                y_in = height - 1
            row_out_idx = y_out * width
            row_in_idx = y_in * width
            for x in range(width):
                target_pixels[row_out_idx + x] = src_pixels[row_in_idx + x]

    return target_pixels


def compute_window_ssim(
    window_x: Sequence[float],
    window_y: Sequence[float],
    c1: float = C1_CONSTANT,
    c2: float = C2_CONSTANT,
) -> float:
    """Compute SSIM for a single local window between two image patches."""
    n = len(window_x)
    if n == 0 or len(window_y) != n:
        return 0.0

    # Means
    mu_x = sum(window_x) / n
    mu_y = sum(window_y) / n

    # Variances and Covariance
    var_x = 0.0
    var_y = 0.0
    cov_xy = 0.0
    for i in range(n):
        dx = window_x[i] - mu_x
        dy = window_y[i] - mu_y
        var_x += dx * dx
        var_y += dy * dy
        cov_xy += dx * dy

    deg_free = max(1, n - 1)
    sig_sq_x = var_x / deg_free
    sig_sq_y = var_y / deg_free
    sig_xy = cov_xy / deg_free

    num = (2.0 * mu_x * mu_y + c1) * (2.0 * sig_xy + c2)
    den = (mu_x * mu_x + mu_y * mu_y + c1) * (sig_sq_x + sig_sq_y + c2)

    if den <= 1e-12:
        return 1.0 if num <= 1e-12 else 0.0

    return num / den


def compute_frame_ssim(
    frame_a: Sequence[float],
    frame_b: Sequence[float],
    width: int = 320,
    height: int = 240,
    window_size: int = 11,
    stride: int = 8,
) -> float:
    """Compute mean Structural Similarity Index (SSIM) between two 2D normalized frames."""
    if len(frame_a) != len(frame_b):
        raise ValueError(f"Frame length mismatch: {len(frame_a)} vs {len(frame_b)}")

    ssim_values: list[float] = []

    for y in range(0, height - window_size + 1, stride):
        for x in range(0, width - window_size + 1, stride):
            win_a: list[float] = []
            win_b: list[float] = []
            for wy in range(window_size):
                row_idx = (y + wy) * width + x
                win_a.extend(frame_a[row_idx : row_idx + window_size])
                win_b.extend(frame_b[row_idx : row_idx + window_size])

            score = compute_window_ssim(win_a, win_b)
            ssim_values.append(score)

    if not ssim_values:
        return compute_window_ssim(frame_a, frame_b)

    return sum(ssim_values) / len(ssim_values)


def evaluate_visual_parity(
    reference_frames: Sequence[Sequence[int] | Sequence[float] | Sequence[Sequence[float]] | bytes],
    test_frames: Sequence[Sequence[int] | Sequence[float] | Sequence[Sequence[float]] | bytes],
    film_name: str = "INTRO.ALL",
    threshold: float = PHASE1_SSIM_THRESHOLD,
    apply_aspect_stretch: bool = True,
) -> VisualParityReport:
    """Execute visual parity verification suite across multi-frame sequences."""
    num_frames = min(len(reference_frames), len(test_frames))
    if num_frames == 0:
        return VisualParityReport(
            film_name=film_name,
            frames_evaluated=0,
            mean_ssim=0.0,
            min_ssim=0.0,
            threshold=threshold,
            passed=False,
        )

    ssim_scores: list[float] = []

    for i in range(num_frames):
        ref = reference_frames[i]
        test = test_frames[i]

        norm_ref: list[float]
        norm_test: list[float]
        if apply_aspect_stretch:
            norm_ref = rescale_mode13h_frame(ref, width=320, height=200, target_height=240)
            norm_test = rescale_mode13h_frame(test, width=320, height=200, target_height=240)
        else:
            norm_ref = _normalize_frame_to_floats(ref)
            norm_test = _normalize_frame_to_floats(test)

        frame_score = compute_frame_ssim(norm_ref, norm_test, width=320, height=240)
        ssim_scores.append(frame_score)

    mean_score = sum(ssim_scores) / len(ssim_scores)
    min_score = min(ssim_scores)
    is_passed = mean_score >= threshold

    return VisualParityReport(
        film_name=film_name,
        frames_evaluated=num_frames,
        mean_ssim=float(mean_score),
        min_ssim=float(min_score),
        threshold=threshold,
        passed=is_passed,
    )
