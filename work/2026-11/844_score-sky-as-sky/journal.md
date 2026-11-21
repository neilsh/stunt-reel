# Journal

## 2026-11-21: Scoring the sun disc and the sky fill as sky

**Question**: What does counting a captured sun disc (239) and the sky drawer's `0xD0` fill (208) as sky by position do to each reference film's `mean_iou_scored`, rule by rule, and how far does the fill rule reach?

**Method**: One RTX 4070 render of the seven `VAULT` references (`adapter` `NVIDIA GeForce RTX 4070 Laptop GPU`, class `hardware`), rendered on crates `d6a7d2d` (`52377c4`), re-scored with `mise run parity -- --no-render` under each scorer below; only `crates/stunt-score/src/parity/mask.rs` differs between them.
- **before**: the scorer of `52377c4` (crates `d6a7d2d`), which counts 227 to 238 by index and 224 to 226 by position.
- **and 239**: the scorer of `dff90fb` with its fill pass removed, so only the sun rule is added.
- **and 208 (adopted)**: the scorer of `dff90fb` (crates `d3e5472`): the sun rule, then a row run of 208 with counted sky directly above one of its pixels, judged against the sky counted before the fill pass.
- **row cascade**: the adopted scorer with each row judged against the sky the fill pass has marked so far, so a counted run makes the run below it count.
- **region cascade**: the sun rule's 4-connected region rule applied to 208.
- **no viewport-band test**: the adopted scorer without its test for a 224 to 238 pixel anywhere in the plane before counting an all-208 viewport.

The before run reproduces every film's `ssim` and `iou` that `52377c4`'s `research/parity/expected/gpu.toml` pins (crates `8e4e65d`).
Every run scores the same render: each film's `mean_ssim_scored`, `sha256` and `all_sha256` are identical in all of them.

**Result**: Unrounded `mean_iou_scored`:

| Film | before | and 239 | and 208 (adopted) | row cascade | region cascade |
|---|---|---|---|---|---|
| `balloon` | 0.8977981 | 0.9496850 | 0.9499894 | 0.9466899 | 0.9466899 |
| `bomb` | 0.9625832 | 0.9625832 | 0.9648129 | 0.9633336 | 0.9633336 |
| `traintnl` | 0.9658796 | 0.9658796 | 0.9689963 | 0.9893312 | 0.9893310 |
| `location` | 0.9796185 | 0.9795565 | 0.9818136 | 0.9424457 | 0.9342565 |
| `intro` | 0.9865466 | 0.9865382 | 0.9873148 | 0.9715539 | 0.9352053 |
| `ctry` | 0.9910141 | 0.9910141 | 0.9954595 | 0.9968634 | 0.9968920 |
| `land` | 0.9851943 | 0.9851453 | 0.9868560 | 0.9933228 | 0.9933228 |

- The sun rule raises `balloon` by 0.0518869 and lowers `land` by 0.0000490, `location` by 0.0000620 and `intro` by 0.0000084; it leaves the other three unchanged.
  `balloon`'s 18 scored ticks 12 to 200 rise from 0.4777 to 0.7719 with it and do not move with the fill rule.
- The fill rule, on top of the sun rule, raises every film: `ctry` by 0.0044454, `traintnl` 0.0031167, `location` 0.0022571, `bomb` 0.0022297, `land` 0.0017107, `intro` 0.0007766, `balloon` 0.0003044.
- With both rules every film rises against before.
- Both cascades count the fill down into the 208 ocean: `location` falls to 0.9424 (row) or 0.9343 (region), `intro` to 0.9716 or 0.9352.
  They raise `traintnl`, `land` and `ctry` above the adopted rule, so on those films the fill strip is taller than the rows the adopted rule counts.
- Removing the viewport-band test changes no film's score: an all-208 viewport holds no band pixel, so the test could only react to the button bar rows.
- The adopted rule's reach: a 208 run is one row of 208 pixels, so under a level band edge it counts only the row directly below the band, and under a banked edge each row's run touches the band at the edge column and counts out to the frame side, a wedge between the edge's highest and lowest rows.
  Its `ocean_render_only` loss, our ocean where the capture's mask says sky, here the capture's ocean (also 208, [`attribution.md`](../../../research/parity/attribution.md) section 5) counted as fill, rises from 0 on four films: `location` 0.0001010, `intro` 0.0000795, `ctry` 0.0000167, `land` 0.0000077.

**Verdict**: Adopted (both rules): with both, every film's `mean_iou_scored` rises.
Both cascades are rejected by `location`'s and `intro`'s falls; the row cascade's `intro` 0.9715539 matches the 0.9715 that `dff90fb`'s note quoted for its cascade, but neither reproduces that note's `location` 0.9297.
The viewport-band test is dropped, changing no score; a looking-down frame whose viewport holds any non-208 pixel still counts none of its fill.
The `gpu` table is repinned from the final run in [the roll-independent entry](#2026-11-21-a-roll-independent-fill-rule).

**Lives in**: [`method.md`](../../../research/parity/method.md) section 2.0; [`attribution.md`](../../../research/parity/attribution.md) section 7.

## 2026-11-21: A roll-independent fill rule

**Question**: Does a fill rule that reads each column alone, so its reach does not depend on the horizon's roll, score at least as well as the adopted row-run rule on every film?

**Method**: The same render and `mise run parity -- --no-render` as the entry above, one round, two variants of the fill pass, each judged against the sky counted before it:
- **one pixel per column**: a 208 pixel counts when the pixel directly above it is counted sky.
- **column run**: from such a pixel, the 208 pixels below it in its column down to the first other index.

**Result**: Unrounded `mean_iou_scored`, beside the adopted row-run rule:

| Film | adopted | one pixel per column | column run |
|---|---|---|---|
| `balloon` | 0.9499894 | 0.9499546 | 0.9494502 |
| `bomb` | 0.9648129 | 0.9648120 | 0.9636520 |
| `traintnl` | 0.9689963 | 0.9685672 | 0.9894257 |
| `location` | 0.9818136 | 0.9818324 | 0.9539356 |
| `intro` | 0.9873148 | 0.9870648 | 0.9882634 |
| `ctry` | 0.9954595 | 0.9925559 | 0.9968073 |
| `land` | 0.9868560 | 0.9868600 | 0.9933181 |

One pixel per column zeroes `ocean_render_only` on `ctry`, `intro` and `location`, so their leak is the banked wedge; `land`'s 0.0000077 stays, so it comes from 208 pixels directly under the band, which are either captured ocean or fill where our horizon sits too high; this run does not tell which.
The column run raises `ocean_render_only` to 0.0013581 on `location`.

**Verdict**: Rejected: one pixel per column lowers five films (`ctry` by 0.0029036), and the column run lowers `location` by 0.0278780 by walking into the ocean.
The adopted row-run rule stays; a rule that tells the fill strip from the ocean below it is [#893](https://github.com/neilsh/stunt-reel/issues/893).
Final run, crates `bf72b96` (the adopted rule without the viewport-band test, with its new tests): every film's `mean_iou_scored` and `mean_ssim_scored` are identical to the adopted run in the entry above, and `mise run parity-repin -- --class gpu` repins the `gpu` table from it.

**Lives in**: [`method.md`](../../../research/parity/method.md) section 2.0.
