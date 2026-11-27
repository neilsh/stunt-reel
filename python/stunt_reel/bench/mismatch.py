"""Where a capture and a render disagree, outside what the game draws over the scene.

The readout mask is the scorer's overlay mask plus the HUD timer, which the scorer leaves in.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from stunt_reel.bench.ssim import overlay_mask

if TYPE_CHECKING:
    from numpy.typing import NDArray

__all__ = [
    "TIMECODE_BOX",
    "colour_mismatch",
    "index_mismatch",
    "mismatch_fraction",
    "object_shift",
    "readout_mask",
    "shift_gain",
]

#: The player's HUD timer, ``MM:SS.cc`` in 3x5 glyphs, as (row0, row1, col0, col1), exclusive
#: ends: rows 179 to 183, cells at columns 1 to 27
#: (research/playone-exe/capture-dosbox-automation.md section 5). Films with no HUD lose these
#: 135 pixels too.
TIMECODE_BOX = (179, 184, 1, 28)


def readout_mask(
    capture_idx: NDArray[np.uint8], *, credits_drawn: bool = False
) -> NDArray[np.bool_]:
    """Pixels a readout ignores: :func:`overlay_mask` and the HUD timer.

    The bar and timer sit where they do on the 320x200 screen; a smaller raster keeps what fits.
    """
    mask = overlay_mask(capture_idx, credits_drawn=credits_drawn)
    row0, row1, col0, col1 = TIMECODE_BOX
    mask[row0:row1, col0:col1] = True
    return mask


def index_mismatch(
    capture_idx: NDArray[np.uint8], render_idx: NDArray[np.uint8]
) -> NDArray[np.bool_]:
    """Pixels whose palette index differs."""
    return np.asarray(capture_idx != render_idx)


def colour_mismatch(
    capture_rgb: NDArray[np.uint8], render_rgb: NDArray[np.uint8]
) -> NDArray[np.bool_]:
    """Pixels whose colour differs in any channel, for a render with no index plane."""
    return np.asarray((capture_rgb != render_rgb).any(axis=-1))


def mismatch_fraction(mismatch: NDArray[np.bool_], mask: NDArray[np.bool_]) -> float:
    """The share of unmasked pixels that mismatch; 0.0 when every pixel is masked."""
    shown = int(np.count_nonzero(~mask))
    return int(np.count_nonzero(mismatch & ~mask)) / shown if shown else 0.0


def _match(
    capture_idx: NDArray[np.uint8],
    render_idx: NDArray[np.uint8],
    ys: NDArray[np.intp],
    xs: NDArray[np.intp],
    mask: NDArray[np.bool_],
    dy: int,
    dx: int,
) -> tuple[float, int]:
    height, width = render_idx.shape
    ty, tx = ys + dy, xs + dx
    inside = (ty >= 0) & (ty < height) & (tx >= 0) & (tx < width)
    ty, tx = ty[inside], tx[inside]
    kept = ~mask[ty, tx]
    ty, tx = ty[kept], tx[kept]
    if not len(ty):
        return 0.0, 0
    source = render_idx[ys[inside][kept], xs[inside][kept]]
    return float(np.mean(source == capture_idx[ty, tx])), len(ty)


def shift_gain(
    capture_idx: NDArray[np.uint8],
    render_idx: NDArray[np.uint8],
    pixels: NDArray[np.bool_],
    mask: NDArray[np.bool_],
    dx: int,
    dy: int,
) -> float:
    """``m(d) - m(0)`` for ``d = (dx, dy)`` over *pixels*, where ``m`` is the match share of :func:`object_shift`.

    May be negative; 0.0 when *pixels* is empty.
    """
    ys, xs = np.nonzero(pixels & ~mask)
    if not len(ys):
        return 0.0
    shifted, _ = _match(capture_idx, render_idx, ys, xs, mask, dy, dx)
    base, _ = _match(capture_idx, render_idx, ys, xs, mask, 0, 0)
    return shifted - base


def object_shift(
    capture_idx: NDArray[np.uint8],
    render_idx: NDArray[np.uint8],
    pixels: NDArray[np.bool_],
    mask: NDArray[np.bool_],
    reach: int,
) -> tuple[int, int, float]:
    """The shift ``(dx, dy)`` that best lines the capture up with the object's render pixels, and its gain.

    The match share ``m(d)`` is the share of the object's unmasked *pixels* ``p`` whose render
    index equals the capture's at ``p + d``, counting only ``p + d`` in frame and outside *mask*.
    The best ``d`` has ``2 <= max(|dx|, |dy|) <= reach``, and at least half the object's unmasked
    pixels land in frame and unmasked; the gain is :func:`shift_gain`, never below 0.
    Returns ``(0, 0, 0.0)`` when no shift beats no shift or *pixels* is empty.
    """
    ys, xs = np.nonzero(pixels & ~mask)
    best = (0, 0, 0.0)
    if not len(ys):
        return best
    base, _ = _match(capture_idx, render_idx, ys, xs, mask, 0, 0)
    for dy in range(-reach, reach + 1):
        for dx in range(-reach, reach + 1):
            if max(abs(dx), abs(dy)) < 2:
                continue
            share, landed = _match(capture_idx, render_idx, ys, xs, mask, dy, dx)
            if 2 * landed >= len(ys) and share - base > best[2]:
                best = (dx, dy, share - base)
    return best
