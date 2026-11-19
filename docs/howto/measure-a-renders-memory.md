# Measure a headless render's memory

`--report-memory` makes a headless `stuntreel` render print its resident memory after each stage and its peak at the end.
It reads the process and writes no file, so the render store is byte-identical with the flag on or off (checked below).
Where the memory goes, with figures, is [`evidence-limits.md` § 3](../../research/parity/evidence-limits.md#3-what-is-not-yet-evidence), the LOCATION item.

## 1. Run it

`<data root>` is `STUNT_DATA_ROOT`, as in [Render on lavapipe beside a GPU](render-on-lavapipe.md).
This is the render #733 measured, LOCATION ticks 12-120 on the software adapter, with the flags the parity loop passes (`RENDER_FLAGS` in [`parity_pipeline.py`](../../python/stunt_reel/parity_pipeline.py)); build the release binary first (`cargo build --release -p stunt-cli`).

```bash
target/release/stuntreel --headless "<data root>/builds/patch3/VAULT/LOCATION.FLM" \
    --all "<data root>/captures/vault-location/archives/LOCATION.ALL" --tick-range 12..=120 \
    --sidata "<data root>/corpus/siarchive/Developer/FreeFlight/SIDATA" \
    --width 320 --height 200 --viewport-rows 185 --software-only \
    --out-dir build/scratch/mem --report-memory
```

The flag needs a headless render (`--headless`, `-o`, `--out-dir` or `--video`) and goes with any film and any of its flags.

## 2. Read it

```text
[stuntreel] memory scene built: rss 300.7 MiB (peak so far 303.4 MiB)
[stuntreel] memory renderer opened: rss 686.8 MiB (peak so far 748.6 MiB)
[stuntreel] memory world mesh released: rss 434.3 MiB (peak so far 748.6 MiB)
[stuntreel] memory frames rendered: rss 556.3 MiB (peak so far 748.6 MiB)
[stuntreel] memory peak 748.6 MiB
```

* **scene built** is the resident set when `run_headless` starts, after `build_identified_scene`, with the world mesh's CPU copy still held.
* **renderer opened** is after `Renderer::offscreen` has opened the device and uploaded the shapes, sprites and world.
* **world mesh released** is after `FilmScene::release_world_mesh`, before the first submit.
* **frames rendered** (or **frame drawn**, for a single PNG) is after the last page lands, before the renderer is dropped.
* **peak** is the process's high-water mark at the end: `VmHWM` from `/proc/self/status` on Linux.

The lines above are LOCATION ticks 12-120 on a cloud session's lavapipe (Ubuntu's Mesa 25.2.8), one run built from `75b9106` plus this flag and one from the same change on `4153a85` (`[Bounded Observation]`): the scene at about 301 MiB and the peak at about 749 MiB match [#733](https://github.com/neilsh/stunt-reel/pull/733)'s figures.
The frames-rendered reading was 556 and 549 MiB, against #733's steady median of 558 to 563 MiB.
The other stage readings repeated to under 1 MiB between the two runs, and the frames-rendered reading varied by 7 MiB, so compare stages to a MiB or two and the frames-rendered reading to about 10 MiB, not to the digit.

## 3. Windows

Windows has no `/proc`, and `GetProcessMemoryInfo` needs `unsafe` FFI, which the workspace denies (`unsafe_code`).
The flag therefore asks PowerShell for the process's `WorkingSet64` and `PeakWorkingSet64`, which are the working set and the peak working set (`PeakWorkingSetSize`, as [#769](https://github.com/neilsh/stunt-reel/issues/769) names it) that [#645](https://github.com/neilsh/stunt-reel/issues/645) quotes in MB.
Each reading starts a PowerShell, which takes a moment but adds nothing to the render's own process.
That path is not yet run on Windows: the parsing is unit-tested on Linux and the query is `Get-Process -Id <pid>` read for `WorkingSet64` and `PeakWorkingSet64` (`read_windows` in [`memory_report.rs`](../../crates/stunt-cli/src/memory_report.rs)), but the first run on a Windows machine is the check.
If `powershell` is missing or fails, the stage prints `unavailable: <reason>` on stderr and the render goes on.

## 4. Check that it changes nothing

Render once with the flag and once without, to two `--out-dir`s, then `diff -r` the two; the 2026-11-18 run above printed nothing for LOCATION ticks 12-120.
