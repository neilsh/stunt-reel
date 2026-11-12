# Journal: sprite draw order

## 2026-11-12: sprite with no depth test, in the actor's place in the sort

- **Question**: Does drawing the `OP_ANIMATE` square without a depth test, in its actor's place in `PLAYONE`'s far-to-near entry sort, put explosions over their neighbours as the capture does and raise the score?
- **Method**: Evidence-backed track (image `0xA9DC` handler, `0x7DE6` blit with no depth test, `0x1B88` entry sort, [`sod-vm.md`](../../../research/playone-exe/sod-vm.md) section 9.1), on `dbfd0ed4`, RTX 4070. A temporary sprite pipeline with depth compare `Always`, three orders: `0` the adopted depth-tested draw; `1` the sprite drawn among world and actors sorted by actor eye distance, far first, with and without depth write; `3` the sprite drawn after every base and decal draw. `mise run sweep -- --var DBG_SPRITE_MODE=0,1,3 --var DBG_SPRITE_WRITE=0,1 --films ctry,intro,bomb`. The switches were not committed.
- **Result**: `ctry` / `intro` / `bomb` SSIM:
  - `0` (baseline): 0.8996 / 0.8418 / 0.8101.
  - `1`, no depth write: 0.8984 / 0.8404 / 0.8100.
  - `1`, depth write: 0.8988 / 0.8418 / 0.8101.
  - `3` (write on or off, identical): 0.8984 / 0.8422 / 0.8101.
  - IoU unchanged at four places in every variant on the three films. Mode `3` rises `intro` by 0.0004 and falls `ctry` by 0.0012; mode `1` rises no film.
  - `CTRY` tick 871 (capture beside the three orders, [picture](images/ctry_871.png)): the capture appears to draw the explosion over the tower beside it but under the large foreground hill at the left, which appears to cut it. Orders `1` and `3` both draw the whole square over the hill. `[Hypothesis]`, from this one frame and not checked in code: the tower is an actor that sorts before the explosion, and the hill is terrain in the world draw (first in both orders) that the capture draws after it.
  - The sprite's reach over the hill is the likely loss, not isolated: where the capture keeps the hill in front, the no-depth draw pays more than the tower gains.
- **Verdict**: not adopted. Mode `3` meets the evidence-backed bar on paper (one film rises, none falls by 0.002) but does not match the capture at tick 871 where the hill appears to hide the explosion; mode `1` rises nothing. That the blit takes its actor's slot is inferred from the sort (sod-vm.md 9.1) and the painter's-order wording of sod-animate.md section 3, not traced through the actor draw (`0x1C00`). Matching the capture may need the terrain in the sort too (`[Hypothesis]`), which this renderer's one world draw does not give. Scores are one run on one GPU; the baseline differs from sod-animate.md section 4's because `main` has moved since.
- **Lives in**: [`sod-animate.md`](../../../research/playone-exe/sod-animate.md) § 3 and § Open questions.
