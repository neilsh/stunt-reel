# Hoisting the view-facing shape lookup and the camera's gate words

Spans and command shape: as in [`#934`'s journal](../934_filmscene-frame-cost/journal.md): Span A `LOCATION 12..=300`, Span B `LOCATION 3680..=3979`, Span C `INTRO 2500..=2949`, headless `320x200`, `--viewport-rows 185`, `--software-only` with `VK_DRIVER_FILES` naming mesa-dist-win `25.2.8`'s lavapipe ICD on Windows lavapipe (`llvmpipe (LLVM 21.1.7, 256 bits)`, confirmed in each run's `render.json`), neither on the RTX 4070.

## Environment

- **Machine.**
  The laptop of `#918`, `#931` and `#934` (Ryzen 7 7745HX, 16 logical processors, Windows 11 build 26300, `rustc 1.100.0`); other agents built, tested and rendered on it throughout.
- **Binaries.**
  Both built with `cargo build --release --locked -p stunt-cli` on `9d70db21` (`#945`'s docs-only merge and `#946`'s readback copy came after, so neither binary has them): `base` is that tree, `new` is that tree plus this change's `film.rs` and `projection.rs` edits.
  Each also carries [`timer.patch`](timer.patch) (a `PROBE942` line with the loop's and `FilmScene::frame`'s wall time; never committed under `crates/`), which prints the same on both.
- **Runs.**
  3 rounds; in each round, per adapter and span, `base` then `new` back to back ([`runs_main.log`](runs_main.log): start load, both timers and the digest of `frames.zst`, `layers.zst`, `shapes.zst` and `palettes.zst` together).
  Each run waited for the CPU load (`Win32_Processor.LoadPercentage`) to fall under `25%` for up to `120 s`; the starts were `3%..24%` except two lavapipe Span A `base` runs that started at `100%` once the wait ran out (the `1,489.9..3,338.6 ms` and `1,357.7..2,884.6 ms` loop spreads below).
  Because `base` always ran first in a pair, three more rounds on Windows lavapipe ran `new` then `base` ([`runs_swap.log`](runs_swap.log)).
  The second set's other work was heavier: its `base` loop on Span B spans `2,522.0..5,738.0 ms`.
- **Ubuntu lavapipe.**
  Not measured: this run had no cloud session.

---

## 2026-11-22: Byte-identical stores and unchanged scores

- **Question**: Does the change leave every pixel `stuntreel` draws where it was?
- **Method**: The four store digests above for `base` and `new` in every run; `mise run parity -- --software-only` on `base` and on `new` (this machine's Windows lavapipe), comparing each of the seven films' `frames.zst`, `layers.zst`, `shapes.zst` and `palettes.zst` digest and `report.json` mean SSIM and IoU; `mise run parity` on the RTX 4070 on `new` against `expected/gpu.toml`.
- **Result**: Every `new` run's digest equals its `base` run's (`18` of `18` pairs on the first set, `9` of `9` on the second), and each cell's digest is the same in all its runs: Span A lavapipe `e78af0dd5a752670`, B `f89ad44392c9f0d6`, C `ef55e1c5210bb21d`; RTX A `113bfec5a02cd0fc`, B `28b8e1aba4759a01`, C `eca47385a8518dc2`.
  On Windows lavapipe all seven reference films' store digests and mean SSIM and IoU are identical between `base` and `new`; on the RTX 4070 `new`'s deltas against `expected/gpu.toml` are `+0.0000000` or `-0.0000000` on all seven films (that row's `crates/` tree differs, so the line reads `not comparable`, but the scores equal the pinned ones to seven places).
  `expected/lavapipe.toml` is pinned on Ubuntu's Mesa and says `not comparable: other adapter` here, as `render-on-lavapipe.md` § 4 warns.
- **Verdict**: Adopted on the pixels: no store or score moved.
- **Lives in**: [`lavapipe-render-time.md` § 6](../../../research/parity/lavapipe-render-time.md#6-optimization-verdicts).

---

## 2026-11-22: `scene_frame` and loop time before and after

- **Question**: How much of `FilmScene::frame`, and of the headless loop, does hoisting the `self.shapes` lookup and the camera's gate words remove?
- **Method**: As in Environment; medians `[min..max]` of 3 runs in ms.
- **Result**: Interleaved, `base` first:

| Cell | `scene_frame` base | `scene_frame` new | Change | Loop base | Loop new | Change | Loop ranges |
|---|---|---|---|---|---|---|---|
| Win lvp A | `552.8` [`472.3..1,151.2`] | `269.8` [`253.1..353.6`] | `-51.2%` | `1,574.4` [`1,489.9..3,338.6`] | `1,245.3` [`1,215.9..1,423.0`] | `-20.9%` | disjoint |
| Win lvp B | `554.4` [`551.1..580.3`] | `382.0` [`366.9..386.8`] | `-31.1%` | `2,612.6` [`2,567.9..2,635.1`] | `2,673.0` [`2,641.7..2,725.6`] | `+2.3%` | disjoint |
| Win lvp C | `607.4` [`601.1..626.6`] | `482.4` [`456.0..493.4`] | `-20.6%` | `2,294.7` [`2,232.9..2,310.1`] | `2,173.8` [`2,115.6..2,211.9`] | `-5.3%` | disjoint |
| RTX A | `394.0` [`362.2..526.9`] | `237.9` [`215.9..238.0`] | `-39.6%` | `922.5` [`873.4..1,125.1`] | `750.5` [`731.2..797.8`] | `-18.6%` | disjoint |
| RTX B | `307.2` [`291.0..329.5`] | `181.0` [`173.1..198.6`] | `-41.1%` | `904.1` [`880.9..936.6`] | `788.1` [`743.7..796.7`] | `-12.8%` | disjoint |
| RTX C | `473.9` [`440.1..538.6`] | `322.7` [`321.0..460.8`] | `-31.9%` | `1,602.2` [`1,521.2..1,671.3`] | `1,415.8` [`1,415.8..1,682.4`] | `-11.6%` | overlap |

  Interleaved, `new` first (Windows lavapipe only):

| Cell | `scene_frame` base | `scene_frame` new | Change | Loop base | Loop new | Change | Loop ranges |
|---|---|---|---|---|---|---|---|
| Win lvp A | `427.7` [`416.6..962.5`] | `341.1` [`259.3..401.4`] | `-20.2%` | `1,382.1` [`1,357.7..2,884.6`] | `1,394.8` [`1,213.3..1,495.1`] | `+0.9%` | overlap |
| Win lvp B | `637.1` [`531.9..1,219.4`] | `381.0` [`354.6..390.7`] | `-40.2%` | `2,753.8` [`2,522.0..5,738.0`] | `2,655.3` [`2,528.6..2,661.8`] | `-3.6%` | overlap |
| Win lvp C | `853.3` [`601.4..858.0`] | `592.1` [`443.9..602.9`] | `-30.6%` | `2,693.4` [`2,274.7..2,731.3`] | `2,383.2` [`2,091.3..2,437.3`] | `-11.5%` | overlap |

  `scene_frame` fell in all nine cells, `-20.2%..-51.2%`, its runs' ranges disjoint in seven (the two that overlap are RTX Span C and the second set's Span C).
  The loop fell `-5.3%..-20.9%` with disjoint ranges on Windows lavapipe Spans A and C and RTX Spans A and B in the first set, but Span B on lavapipe rose `+2.3%` with disjoint ranges (new slower) and fell `-3.6%` within its ranges in the second set; the other cells of the second set and RTX Span C overlap.
- **Verdict**: Adopted: `scene_frame` falls by a fifth to a half on both adapters with stores and scores unchanged.
  The loop saving is only established where its ranges do not overlap (Windows lavapipe A and C, RTX A and B in the first set); on lavapipe Span B, `scene_frame` fell `31.1%` and `40.2%` (`172.4..256.1 ms`) yet the loop moved `+2.3%` and `-3.6%`, so no loop saving is claimed there.
  `#934` saw the same scatter in its loop medians under concurrent load.
- **Lives in**: [`lavapipe-render-time.md` § 6](../../../research/parity/lavapipe-render-time.md#6-optimization-verdicts).
