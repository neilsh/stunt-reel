# Journal

## 2026-11-18: Up vector for a vertical authored camera

**Question**: which up vector gives `BALLOON` ticks 601 to 796, where the authored camera looks straight down, the capture's orientation (#615)?

**Method**: `mise run frame -- --film balloon --ticks 606 --software-only` on lavapipe (llvmpipe) with a temporary `TMP_UP` override of the up vector when the view direction is parallel to `+Y`, once each for `(0,0,-1)`, `(0,0,1)`, `(1,0,0)` and `(-1,0,0)`; then `mise run parity -- --software-only` on a clean `crates/` (tree `16fa249`) and `mise run parity-repin -- --class lavapipe`.
The override was removed before the commit.

**Result**: `+Z` matches the capture's turn at tick 606 (gondola right of the envelope, tree upper left); `-Z` is the same picture turned half a turn, `+X` and `-X` a quarter turn either way. [picture](images/balloon-606-after-vertical-up.png), [tick 694](images/balloon-694-after-vertical-up.png).
Before the fix the layer plane was empty, so the cause (up `+Y` parallel to the view) is consistent with this, though the matrix was not printed.
`balloon` on lavapipe: SSIM 0.8172 -> 0.8836, IoU 0.6409 -> 0.8091, scored 107/108 unchanged; the other six films score as before to seven decimals.
The bound [`attribution.md`](../../../research/parity/attribution.md) section 7 gives for a camera fix is 0.8856.

**Verdict**: adopted (heuristic track, film-mean branch: `balloon` +0.0664; no other film moves; the `+Z` choice is read off one capture, not off `PLAYONE.EXE`; the yaw word it keeps for a vertical view is not in the trajectory data we parse).

**Lives in**: [`attribution.md`](../../../research/parity/attribution.md) section 7.
