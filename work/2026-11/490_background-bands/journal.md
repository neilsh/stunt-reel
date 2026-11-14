# Journal

## 2026-11-14: Backdrop bands for the six non-CTRY films

**Question**: which palette-index bands are backdrop on `intro`, `land`, `balloon`, `traintnl`, `bomb` and `location`, so `parity_probe.py shift` and `iou` can read them (#490, PR #501)?

**Method**: `mise run parity` on `crates` tree `d2cd090` (`expected.gpu` was measured on `adbde141`; every film's score matched it to 1e-6) on an RTX 4070. The rule and its reproduction snippet are in [`probes.md`](../../../research/parity/probes.md#3-actor-window-iou-iou). Figures below are over the scored frames of each render, from that snippet's statistics and from `parity_probe.py iou`'s every-2nd-frame window; a shape or node attribution that a figure names is the #501 round-2 review's readout, not reproduced here.

**Result**:

* *First round.* A looser rule (actor paint under 0.1 %, under 0.5 % for a mostly-sky index, plus props-layer masses that agreed with ours) put into the bands indices our actors paint: `balloon` 224 (0.33 % of actor pixels), `traintnl` 163 and 164 (7 px in 4 frames, 17 px in 14), sky 227-238 on `land` and `location`, and `location` 76 and 205 and `intro` 208 (24 to 43 frames each). It also took props-layer scenery no actor paints (13 and 14 on `land`, 14 on `bomb`, 172 to 176 and 193 to 196 on `intro`). Crops of `land` 540, `balloon` 595, `traintnl` 628, `bomb` 1750, `intro` 2454 and `location` 4148 looked right at the time; the #501 review found those bands wrong where a crop could not show it. The final bands were not re-cropped.
* *Why the strict sets are small.* Our actors paint these backdrop indices, so zero tolerance drops them. `land` 229 to 238: 5,605 px, 43 to 96 frames per index (the review reads them as canopy `0x7F09`; our actors paint 227 and 228 too). `intro`: 2,643 px over 229 to 238, 87 % of them at 236 to 238 (1,146 px at 237); 229 and 230 are 1 and 4 px (the review reads 1 to 5 px slivers of `0x7F04`). `bomb` 195, 24 % of its capture pixels, is dropped for 1 px in 1 scored frame (the review counts 2 px in 2 frames on `0x4142`, perhaps over unscored frames; the rule used the scored-frame count, 1 px). `traintnl` 231 is dropped for 1 px in 1 frame while 233 stays (0 px): the test is sensitive to rasterizer edges. `ctry`'s committed 237 has 9 actor px in 3 frames, so it breaks the same rule (follow-up issue).
* *Shift sensitivity.* Our actor pixels shifted by (dx, dy) before scoring, same window and every 2nd scored frame as `iou`:

  | Film | (0,0) | (0,-15) | (0,+10) | (+15,0) | (+25,+25) |
  |---|---|---|---|---|---|
  | `ctry` | 0.5405 | 0.1677 | 0.1842 | 0.2040 | 0.0840 |
  | `land` | 0.1879 | 0.1367 | 0.1160 | 0.1602 | 0.0898 |
  | `traintnl` | 0.3397 | 0.1803 | 0.2125 | 0.2143 | 0.1650 |
  | `balloon` | 0.6796 | 0.4572 | 0.5358 | 0.5005 | 0.3506 |
  | `bomb` | 0.2709 | 0.1615 | 0.1501 | 0.1922 | 0.1130 |
  | `intro` | 0.1487 | 0.1538 | 0.1492 | 0.1427 | 0.1332 |
  | `location` | 0.1164 | 0.1040 | 0.1055 | 0.1091 | 0.1029 |

  At (+25,+25) `land`, `traintnl`, `balloon` and `bomb` fall to 0.48, 0.49, 0.52 and 0.42 of their unshifted IoU; `intro` and `location` fall to 0.90 and 0.88, and on `intro` shifts of (0,-15) and (0,+10) score above (0,0).
* *Location's foreground fault* ([#504](https://github.com/neilsh/stunt-reel/issues/504)). Our actor pixels (layer 16 and up, per scored frame) run 3,509 at tick 717, 1,842 at 738, 6,339 at 782, about 7,400 from 805 to 903 (not monotonic: 1,842 at 738) and 9,391 at 914, and the per-frame IoU (every scored frame, not the probe's every-2nd sample) is 0.115 at 717, 0.055 at 738 and 0.116 at 760, then 0.376 at 782 and 0.34 to 0.35 at 805 to 892 (0.211 at 837). At tick 848 the capture holds index 76 under all 7,410 of our actor pixels, and we draw index 0 on 7,408 of them. 76 is not a band (an actor paints it elsewhere), so the oversized foreground overlaps capture object pixels and raises the IoU; it does not lower it.

**Verdict**: adopted: the six `background` rows and the rule in `probes.md`. The low IoUs are not a render score: they follow mainly from the strict bands and props-layer scenery.

**Lives in**: [`probes.md`](../../../research/parity/probes.md#3-actor-window-iou-iou) (rule, bands, limits) and `research/parity/references.toml` (the rows).
