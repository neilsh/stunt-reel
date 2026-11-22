# Testing each shared LOD gate once per frame

Spans and command shape: as in [`#942`'s journal](../942_frame-gate-cache/journal.md): Span A `LOCATION 12..=300`, Span B `LOCATION 3680..=3979`, Span C `INTRO 2500..=2949`, headless `320x200`, `--viewport-rows 185`, `--software-only` with `VK_DRIVER_FILES` naming mesa-dist-win `25.2.8`'s lavapipe ICD on Windows lavapipe (`llvmpipe (LLVM 21.1.7, 256 bits)`, confirmed in each run's `render.json`), neither on the RTX 4070 (`NVIDIA GeForce RTX 4070 Laptop GPU`).

## Environment

- **Machine.**
  The laptop of `#942` (Ryzen 7 7745HX, 16 logical processors, Windows 11 build 26300, `rustc 1.100.0`); other agents may have built and rendered on it.
- **Binaries.**
  Both built with `cargo build --release --locked -p stunt-cli` on `b9441a06`: `base` is that tree, `new` is that tree plus this change.
  Each also carries `#942`'s [`timer.patch`](../942_frame-gate-cache/timer.patch), applied unchanged (a `PROBE942` line with the loop's and `FilmScene::frame`'s wall time; never committed under `crates/`).
- **Runs.**
  3 rounds; in each round, per adapter and span, `base` then `new` back to back ([`runs_main.txt`](runs_main.txt): start load, both timers and a digest of `frames.zst`, `layers.zst`, `shapes.zst` and `palettes.zst`), then three more rounds on Windows lavapipe with `new` first ([`runs_swap.txt`](runs_swap.txt)); `54` runs.
  The digest is the SHA-256 of the four files' SHA-256 digests in that order, cut to 16 hex digits, so it is not comparable with `#942`'s.
  Each run waited for the CPU load (`Win32_Processor.LoadPercentage`) to fall under `25%` for up to `120 s`; the starts were `4%..65%`, nine of the `54` at `25%` or more.
- **Ubuntu lavapipe.**
  Not measured: this run had no cloud session.

---

## 2026-11-22: Byte-identical stores

- **Question**: Does testing each gate node once per frame leave every pixel `stuntreel` draws where it was?
- **Method**: The four store digests above for `base` and `new` in every run.
- **Result**: Every `new` run's digest equals its `base` run's (`27` of `27` pairs), and each cell's digest is the same in all its runs: Span A lavapipe `33a62e15dce9c4a7`, B `516366edb6421b21`, C `98ee166940506257`; RTX A `06fc33afdd7cb0cd`, B `b42d1486c4369a5d`, C `cf17270ba74080d6`.
  The seven reference films' scores were not re-run.
- **Verdict**: Adopted on the pixels for the three spans on both adapters.
- **Lives in**: [`lavapipe-render-time.md` § 6](../../../research/parity/lavapipe-render-time.md#6-optimization-verdicts).

---

## 2026-11-22: Gate tests per frame

- **Question**: How many gates can a frame now test?
- **Method**: A throwaway print of `World::gate_nodes.len()` and `World::view_facing.len()` after `FilmScene::load` on each film (not committed).
- **Result**: `LOCATION` holds `27,719` gate nodes for its `20,916` view-facing props, `INTRO` `20,985` for `15,663`.
  The forward pass tests a node only when its parent is open, so a frame tests at most that many gates, against `116,791` (Span A), `75,994.1` (B) and `65,606.5` (C) tests per tick before (`#934`'s counts).
  The runs did not count the tests made; the bound follows from the pass, and a unit test (`open_nodes`) counts a pass that leaves the children of a closed node untested.
- **Verdict**: Adopted: each gate node is tested at most once a frame.
- **Lives in**: [`lavapipe-render-time.md` § 6](../../../research/parity/lavapipe-render-time.md#6-optimization-verdicts).

---

## 2026-11-22: `scene_frame` and loop time before and after

- **Question**: How much of `FilmScene::frame`, and of the headless loop, does the shared gate tree remove?
- **Method**: As in Environment; medians `[min..max]` of 3 runs in ms.
- **Result**: Interleaved, `base` first:

| Cell | `scene_frame` base | `scene_frame` new | Change | Loop base | Loop new | Change | Loop ranges |
|---|---|---|---|---|---|---|---|
| Win lvp A | `310.7` [`237.8..366.4`] | `82.0` [`80.3..83.1`] | `-73.6%` | `1,119.9` [`949.2..1,188.1`] | `861.9` [`837.8..884.5`] | `-23.0%` | disjoint |
| Win lvp B | `353.9` [`338.9..403.1`] | `98.5` [`95.9..115.6`] | `-72.2%` | `2,633.3` [`2,512.6..2,697.7`] | `2,491.7` [`2,482.1..2,817.5`] | `-5.4%` | overlap |
| Win lvp C | `407.6` [`364.0..429.6`] | `188.2` [`183.4..193.2`] | `-53.8%` | `1,782.3` [`1,737.3..1,824.5`] | `1,592.5` [`1,581.9..1,643.5`] | `-10.6%` | disjoint |
| RTX A | `195.3` [`173.3..213.5`] | `92.0` [`89.3..98.7`] | `-52.9%` | `475.3` [`447.2..528.3`] | `434.3` [`405.3..435.2`] | `-8.6%` | disjoint |
| RTX B | `143.9` [`138.6..200.2`] | `61.7` [`58.4..84.8`] | `-57.1%` | `496.0` [`494.6..572.7`] | `444.4` [`413.8..529.6`] | `-10.4%` | overlap |
| RTX C | `290.0` [`274.9..307.4`] | `176.4` [`171.7..188.8`] | `-39.2%` | `1,089.9` [`1,058.6..1,118.9`] | `991.2` [`982.2..1,051.1`] | `-9.1%` | disjoint |

  Interleaved, `new` first (Windows lavapipe only):

| Cell | `scene_frame` base | `scene_frame` new | Change | Loop base | Loop new | Change | Loop ranges |
|---|---|---|---|---|---|---|---|
| Win lvp A | `228.6` [`223.7..264.3`] | `79.1` [`78.3..79.3`] | `-65.4%` | `921.2` [`917.4..969.2`] | `831.1` [`827.9..844.8`] | `-9.8%` | disjoint |
| Win lvp B | `278.0` [`277.8..303.2`] | `87.3` [`83.2..87.4`] | `-68.6%` | `2,395.7` [`2,284.5..2,611.1`] | `2,379.8` [`2,364.4..2,474.7`] | `-0.7%` | overlap |
| Win lvp C | `347.0` [`343.2..423.7`] | `189.0` [`175.4..192.6`] | `-45.5%` | `1,695.1` [`1,682.9..1,823.0`] | `1,631.8` [`1,553.6..1,650.0`] | `-3.7%` | disjoint |

  `scene_frame` fell in all nine cells, `-39.2%..-73.6%`, every cell's runs' ranges disjoint.
  The loop median fell in all nine, `-0.7%..-23.0%`, its ranges disjoint in six (lavapipe A and C in both orders, RTX A and C) and overlapping in three (lavapipe B in both orders, RTX B).
- **Verdict**: Adopted: `scene_frame` falls by `39.2%` to `73.6%` on both adapters with the three spans' stores unchanged, and the loop median moved down in every cell, `0.7%` to `23.0%`, with its ranges separating in six of nine.
  Other agents' load was not controlled, so the loop figures carry no saving of their own; `#942` and `#944` saw the same scatter.
- **Lives in**: [`lavapipe-render-time.md` § 6](../../../research/parity/lavapipe-render-time.md#6-optimization-verdicts).
