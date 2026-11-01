"""The Rust parity SSIM (``stunt-render::parity`` and ``stunt-cli::parity::score``) in numpy.

Pinned to the Rust scorer by ``tests/fixtures/parity/bench/golden.json``. The scorer's
arithmetic is f32 and this is f64; the two agree to well under 1e-4.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view

if TYPE_CHECKING:
    from numpy.typing import NDArray

    from stunt_reel.bench.planes import CapturePlanes

__all__ = [
    "capture_luma",
    "frame_ssim",
    "overlay_mask",
    "render_luma",
    "stretch",
    "window_grid",
    "window_ssim",
]

WIDTH = 320
HEIGHT = 200
STRETCHED_HEIGHT = 240
WINDOW = 11
STRIDE = 8
C1 = 6.5025
C2 = 58.5225
UI_BAR_FIRST_ROW = 185
CURSOR_INDEX = 255
_LUMA = np.array([0.299, 0.587, 0.114])


def render_luma(rgb: NDArray[np.uint8]) -> NDArray[np.float64]:
    """Luminance of an RGB image, as ``rgb_to_luminance``."""
    return cast("NDArray[np.float64]", rgb.astype(np.float64) @ _LUMA)


def capture_luma(planes: CapturePlanes) -> NDArray[np.float64]:
    """Luminance of a capture's index plane through its palette, before the stretch."""
    return render_luma(planes.palette[planes.idx])


def stretch(plane: NDArray[Any]) -> NDArray[Any]:
    """Rows 200 to 240 by nearest neighbour, as ``rescale_mode13h_frame``."""
    scale = np.float32(HEIGHT) / np.float32(STRETCHED_HEIGHT)
    rows = (np.arange(STRETCHED_HEIGHT, dtype=np.float32) * scale).astype(np.int64)
    return plane[np.minimum(rows, HEIGHT - 1)]


def overlay_mask(capture_idx: NDArray[np.uint8]) -> NDArray[np.bool_]:
    """Pixels the UI overlay covers: the button bar rows and the cursor index."""
    mask: NDArray[np.bool_] = capture_idx == CURSOR_INDEX
    mask[UI_BAR_FIRST_ROW:, :] = True
    return mask


def window_grid(mask240: NDArray[np.bool_] | None) -> NDArray[np.bool_]:
    """The windows (11x11, stride 8, over 320x240) that touch no masked pixel."""
    rows = len(range(0, STRETCHED_HEIGHT - WINDOW + 1, STRIDE))
    cols = len(range(0, WIDTH - WINDOW + 1, STRIDE))
    if mask240 is None:
        return np.ones((rows, cols), dtype=np.bool_)
    windows = sliding_window_view(mask240, (WINDOW, WINDOW))[::STRIDE, ::STRIDE]
    return ~windows.any(axis=(2, 3))


def window_ssim(a240: NDArray[Any], b240: NDArray[Any]) -> NDArray[np.float64]:
    """SSIM of every window, as ``compute_window_ssim`` (sample variance, ``n - 1``)."""
    wa = sliding_window_view(a240.astype(np.float64), (WINDOW, WINDOW))[::STRIDE, ::STRIDE]
    wb = sliding_window_view(b240.astype(np.float64), (WINDOW, WINDOW))[::STRIDE, ::STRIDE]
    n = WINDOW * WINDOW
    mu_a = wa.mean(axis=(2, 3))
    mu_b = wb.mean(axis=(2, 3))
    da = wa - mu_a[..., None, None]
    db = wb - mu_b[..., None, None]
    var_a = (da * da).sum(axis=(2, 3)) / (n - 1)
    var_b = (db * db).sum(axis=(2, 3)) / (n - 1)
    cov = (da * db).sum(axis=(2, 3)) / (n - 1)
    num = (2.0 * mu_a * mu_b + C1) * (2.0 * cov + C2)
    den = (mu_a * mu_a + mu_b * mu_b + C1) * (var_a + var_b + C2)
    degenerate = den <= 1e-12
    safe = np.where(degenerate, 1.0, den)
    flat = np.where(num <= 1e-12, 1.0, 0.0)
    return np.where(degenerate, flat, num / safe)


def frame_ssim(capture: CapturePlanes, render_rgb: NDArray[np.uint8]) -> float:
    """The ``score_frame`` SSIM: mean over windows clear of the overlay, 1.0 when none."""
    reference = stretch(capture_luma(capture))
    test = stretch(render_luma(render_rgb))
    allowed = window_grid(stretch(overlay_mask(capture.idx)))
    if not allowed.any():
        return 1.0
    return float(window_ssim(reference, test)[allowed].mean())
