# Row-wise readback copy

[#931](../931_post-914-render-profile/journal.md) made `read_back`'s byte-at-a-time iterator the next render-time change: it cost `17.2%..21.8%` of the loop on Windows lavapipe and `26.6%..31.8%` on the RTX 4070.
This item copies each row whole (#933).

- Probe: [#931's `probe.patch`](../931_post-914-render-profile/probe.patch), `git apply` on the control; it does not apply to the change, whose `read_back` body the `DBG_PROBE_ROW_COPY` hunk rewrites.
  On the change the readback hunk was applied by hand: `is_plane: bool`, `t_poll` at entry, and `t_copy` after the map wait as in the patch, then `drop(mapped); drop(_unmap); crate::probe::add_readback_copy(t_copy.elapsed());` surrounding `strip_pitch_padding`, so the phase still covers `get_mapped_range`, the copy and the unmap as it does in the probe.
  `DBG_PROBE_ROW_COPY` is not set in either binary, so the control keeps the old iterator.
- Change: `97e0676e`, `crates/stunt-render/src/renderer/readback.rs` reserves each plane's `Vec` once and appends each row's first `row_bytes` with `extend_from_slice`.

## 2026-11-22: Row-wise readback copy on Windows lavapipe and the RTX 4070

- **Question**: How much does the row-wise copy cut `readback_copy` and the loop on Windows lavapipe and the RTX 4070, and do the stores stay byte-identical?
- **Method**: Two release binaries from one checkout, one from `9ccfd39c` (main) and one from `97e0676e` (the change; before it was rebased onto `1773d078`, a gate-tooling commit that leaves `readback.rs` alone), each with the probe above.
  Spans A (`LOCATION 12..=300`), B (`LOCATION 3680..=3979`) and C (`INTRO 2500..=2949`), headless `320x200`, `--viewport-rows 185`, on Windows 11 (Ryzen 7 7745HX), `mesa-dist-win 25.2.8` (`llvmpipe (LLVM 21.1.7, 256 bits)`, `VK_DRIVER_FILES` naming its `lvp_icd.x86_64.json`) and the RTX 4070 Laptop GPU (driver 32.0.16.1088).
  Two warm-up rounds (one render of each binary per cell), then three measured runs per cell, the two binaries interleaved and the first binary alternating by round; each run's four `.zst` stores were hashed.
  Two other sessions rendered on the GPU and CPU during the sweeps, so the absolute timings and the loop deltas are not clean baselines: the before-loop medians run `+48.8%..+90.7%` above #931's (§ 3's post-`#914` row), every after median is still above #931's before for its span, and the run spreads below are wide.
- **Result**: `readback_copy` and loop medians (ms; the three runs and their median):

| Cell | `readback_copy` before | `readback_copy` after | change | loop before | loop after | loop change |
|---|---|---|---|---|---|---|
| Windows lavapipe A | `490.8, 438.5, 438.0` (`438.5`) | `49.7, 30.8, 35.0` (`35.0`) | `-92.0%` | `2,350.0, 2,006.3, 2,006.5` (`2,006.5`) | `2,104.4, 1,473.3, 1,458.3` (`1,473.3`) | `-26.6%` |
| Windows lavapipe B | `661.8, 660.4, 720.0` (`661.8`) | `239.9, 209.1, 218.9` (`218.9`) | `-66.9%` | `3,727.1, 3,362.5, 3,670.4` (`3,670.4`) | `3,615.4, 3,150.2, 3,524.2` (`3,524.2`) | `-4.0%` |
| Windows lavapipe C | `976.8, 810.5, 806.6` (`810.5`) | `124.9, 102.8, 113.6` (`113.6`) | `-86.0%` | `4,118.2, 3,172.4, 3,293.7` (`3,293.7`) | `2,705.5, 2,556.6, 2,642.2` (`2,642.2`) | `-19.8%` |
| RTX 4070 A | `421.2, 526.7, 415.0` (`421.2`) | `80.1, 74.5, 84.4` (`80.1`) | `-81.0%` | `1,625.2, 1,889.4, 1,505.4` (`1,625.2`) | `1,036.9, 1,265.2, 1,332.3` (`1,265.2`) | `-22.2%` |
| RTX 4070 B | `392.3, 384.9, 352.3` (`384.9`) | `51.2, 52.3, 49.7` (`51.2`) | `-86.7%` | `1,592.7, 1,471.2, 1,410.7` (`1,471.2`) | `1,054.0, 1,170.1, 931.9` (`1,054.0`) | `-28.4%` |
| RTX 4070 C | `528.3, 582.4, 617.4` (`582.4`) | `91.7, 103.7, 102.9` (`102.9`) | `-82.3%` | `2,113.8, 2,421.5, 2,543.1` (`2,421.5`) | `1,623.8, 1,904.0, 1,786.9` (`1,786.9`) | `-26.2%` |

  Every one of the 36 runs' four stores matched the five other runs of its cell (both binaries): zero mismatches.
- **Verdict**: Adopted. The copy falls `66.9%..92.0%` on Windows lavapipe and `81.0%..86.7%` on the RTX 4070, `333.7..696.9 ms` per cell and `12.1%..22.7%` of its before-loop, and that is the robust figure. Loop medians fell in every cell by `4.0%..28.4%`, a scatter around that saving that the contention above drives; on lavapipe Spans A and B the before and after loop ranges overlap, so no per-cell loop figure is a clean baseline. The copy separates in every cell, which is what makes its cut the figure to quote.
- **Lives in**: [lavapipe-render-time.md § 3](../../../research/parity/lavapipe-render-time.md#3-post-644-phase-breakdown-and-ab-probes) and [§ 6](../../../research/parity/lavapipe-render-time.md#6-optimization-verdicts).

---

## 2026-11-22: Byte-identical stores and unchanged scores on both adapters

- **Question**: Does the row-wise copy leave the seven reference films' render stores and score lines exactly as `main` renders them, on Windows lavapipe and the RTX 4070?
- **Method**: `mise run parity -- --software-only` on Windows lavapipe and `mise run parity` on the RTX 4070, once on `97e0676e` and once with `crates/stunt-render/src/renderer/readback.rs` checked out from `9ccfd39c`.
  Each film's `frames.zst`, `layers.zst`, `shapes.zst` and `palettes.zst` were compared by SHA-256, and the printed score lines with them.
- **Result**: 28 of 28 stores byte-identical on each adapter, and the seven score lines identical on each adapter.
  The lavapipe render's stores (first 16 hex digits; the RTX 4070's `frames.zst`, `layers.zst` and `shapes.zst` differ from these as its pixels do, and its seven `palettes.zst` match lavapipe's, and each adapter matched its own control):

| Film | `frames.zst` | `layers.zst` | `shapes.zst` | `palettes.zst` |
|---|---|---|---|---|
| `ctry` | `4507faca3f63cdeb…` | `5067b44e49d789a7…` | `3efc59420c2d1e9a…` | `da5bfabfcd7e000e…` |
| `intro` | `e5566115e5a97f69…` | `1c7c4b839c63f1f8…` | `2e84c3d38e7d7aa0…` | `1916f08237b0d025…` |
| `land` | `df316ca9b6686d49…` | `0e638b2ce366785a…` | `0f4c2b0855a45cc3…` | `cba93762cd9089e9…` |
| `balloon` | `447c37729523fab2…` | `dea8d9715c8edf58…` | `be0d359c012e20d5…` | `d4da418953dae73b…` |
| `traintnl` | `111a54486e6eaeee…` | `9e0e23aecb30f3f4…` | `ff7bc7af3e5cb75d…` | `8693c7227b8eee0d…` |
| `bomb` | `b7b8ed7a9dedbd4b…` | `3345fb8f8ebeb717…` | `c807620f6bb2bc2a…` | `d4da418953dae73b…` |
| `location` | `d8bd442f0e4f4845…` | `477da2620f927da7…` | `43377115ee2246dd…` | `f467d6646a04e66e…` |

  Scores on Windows lavapipe (identical before and after):

| Film | SSIM | IoU | index agreement | scored |
|---|---|---|---|---|
| `ctry` | `0.9376` | `0.9955` | `0.961` | `114/121` |
| `intro` | `0.8823` | `0.9879` | `0.917` | `209/347` |
| `land` | `0.9236` | `0.9869` | `0.946` | `97/103` |
| `balloon` | `0.9059` | `0.9504` | `0.911` | `107/108` |
| `traintnl` | `0.9103` | `0.9716` | `0.948` | `112/112` |
| `bomb` | `0.8945` | `0.9660` | `0.929` | `316/339` |
| `location` | `0.8722` | `0.9820` | `0.906` | `732/745` |

  On the RTX 4070 the same seven lines reproduced exactly (identical before and after):

| Film | SSIM | IoU | index agreement | scored |
|---|---|---|---|---|
| `ctry` | `0.9376` | `0.9955` | `0.961` | `114/121` |
| `intro` | `0.8824` | `0.9879` | `0.917` | `209/347` |
| `land` | `0.9237` | `0.9869` | `0.946` | `97/103` |
| `balloon` | `0.9059` | `0.9504` | `0.911` | `107/108` |
| `traintnl` | `0.9103` | `0.9716` | `0.948` | `112/112` |
| `bomb` | `0.8945` | `0.9660` | `0.929` | `316/339` |
| `location` | `0.8721` | `0.9820` | `0.906` | `732/745` |

  Its `intro`, `land` and `location` SSIM differ from lavapipe's in the fourth decimal (`0.8824` against `0.8823`, `0.9237` against `0.9236`, `0.8721` against `0.8722`), as its adapter class does.
  The adapter each render recorded was `llvmpipe (LLVM 21.1.7, 256 bits)` on lavapipe and `NVIDIA GeForce RTX 4070 Laptop GPU` on the GPU.
- **Verdict**: Control passed: the copy moves no pixel on either adapter.
- **Lives in**: [lavapipe-render-time.md § 3](../../../research/parity/lavapipe-render-time.md#3-post-644-phase-breakdown-and-ab-probes) and [§ 6](../../../research/parity/lavapipe-render-time.md#6-optimization-verdicts).
