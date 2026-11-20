# Journal

## 2026-11-20: Counting the sky the balloon cuts off

**Question**: Does rule G, which counts a 224 to 226 run as sky when its full-width rule holds or when it overlaps a 224 to 226 pixel the previous captured frame counted by that rule, count none of the shape paint [#616](https://github.com/neilsh/stunt-reel/issues/616) attributed, and what does it do to each reference film's `mean_iou_scored`?

**Method**: A scratch script (not committed) built rules F and G over every captured frame of the seven `VAULT` references in capture order and counted the 224 to 226 pixels each marks.
It tried the carry against the previous frame's full sky mask, its 227 to 238 band, its F-counted zenith pixels and its G-counted zenith pixels; the last reproduces the count [the positional rule](../718_positional-zenith-sky/journal.md#2026-11-18-a-positional-rule-for-the-zenith-sky) recorded, 77,063 `balloon` pixels and none on any other film.
The scorer change was scored on one render of all seven references: `mise run parity -- --software-only` with the lavapipe ICD (`llvmpipe (LLVM 21.1.7, 256 bits)`) on `fd6c57ec`, whose `_current` trees were re-scored with `--no-render` after it, so each before and after cell is the same render.
Every captured frame matched its render (0 unmatched), so the carry spans each film's whole capture sequence.
GPU: `mise run parity` on the RTX 4070, then `mise run parity-repin -- --class gpu`.

**Result**: Rule G adds 77,063 `balloon` pixels and none on `bomb`, `traintnl`, `location`, `intro`, `ctry` or `land`.
Carrying the 227 to 238 band as well would have added 617 `location`, 310 `intro`, 41 `land` and 1 `traintnl` pixels (and 446 more on `balloon`), which is why the carried mask holds the counted 224 to 226 pixels only.

| Film (224 to 226 pixels) | rule F counts | rule G adds | `mean_iou_scored` before | after |
|---|---|---|---|---|
| `balloon` (1,123,487) | 1,039,844 | 77,063 | 0.8868 | 0.8978 |
| `bomb` (164,739) | 59,520 | 0 | 0.9626 | 0.9626 |
| `traintnl` (19,850) | 0 | 0 | 0.9659 | 0.9659 |
| `location` (7,155) | 0 | 0 | 0.9796 | 0.9796 |
| `intro` (1,227) | 0 | 0 | 0.9865 | 0.9865 |
| `ctry` (473) | 0 | 0 | 0.9910 | 0.9910 |
| `land` (76) | 0 | 0 | 0.9852 | 0.9852 |

Only `balloon` moves: 13 of its 107 scored frames change, tick 144 from 0.2762 to 0.8978, tick 243 from 0.4403 to 0.8916 and tick 254 from 0.4532 to 0.5555, and the film mean rises by 0.0110.
It keeps 6,580 of its 224 to 226 pixels uncounted by either rule.
GPU: `balloon` `mean_iou_scored` 0.8867882 -> 0.8977981, the other six films unchanged to seven digits and every `mean_ssim_scored` unchanged; the `gpu` table is repinned from that run (`crates` `4a3688f`).
Its `[balloon.loss]` moves with the mask: sky 0.0169743 -> 0.0178227, reference_only 0.0064285 -> 0.0055801, actors 0.0525339 -> 0.0523499, props_and_actors_render_only 0.0009776 -> 0.0011617.
The `lavapipe` table is not repinned here: this machine's lavapipe is LLVM 21.1.7, not the pinned LLVM 20.1.2, so its catch-up repin is on [#830](https://github.com/neilsh/stunt-reel/issues/830).

**Verdict**: Adopted: the rule counts none of the paint #616 attributed (`traintnl`'s wall rectangle and rear-car windows, `bomb`'s emblem, `location`'s helicopter windows) or any other film's 224 to 226 pixel, and it raises the only film that changes, `balloon`, by 0.0110 IoU.

**Lives in**: [`method.md`](../../../research/parity/method.md#20-sky-mask-and-iou-scale) section 2.0; [`attribution.md`](../../../research/parity/attribution.md#7-balloons-mask-iou-two-runs-of-frames) section 7.