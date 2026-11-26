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
    "readout_mask",
]

#: The player's HUD timer, ``MM:SS.cc`` in 3x5 glyphs, as (row0, row1, col0, col1), exclusive
#: ends: rows 179 to 183, cells at columns 1 to 27
#: (research/playone-exe/capture-dosbox-automation.md section 5). Films with no HUD lose these
#: 135 pixels too.
TIMECODE_BOX = (179, 184, 1, 28)


def readout_mask(
    capture_idx: NDArray[np.uint8], *, credits_drawn: bool = False
) -> NDArray[np.bool_]:
    """Pixels a readout ignores: :func:`overlay_mask` and the HUD timer, on any raster size."""
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
