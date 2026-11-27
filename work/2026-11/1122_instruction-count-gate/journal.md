## 2026-11-27: a Valgrind smoke run on the synthetic film, and Mesa's shader cache

- **Question**: does a lavapipe render run under Valgrind in a cloud session at all, and does anything make one counted run differ from the next?
- **Method**: a release `stuntreel` of `70b0f76` rendered `tests/fixtures/synthetic_timeline.flm` (13 frames, `--software-only --width 64 --height 48`) on Ubuntu 24.04's `mesa-vulkan-drivers 25.2.8-0ubuntu0.24.04.5`, `VK_DRIVER_FILES` naming its `lvp_icd.json`, `LP_NUM_THREADS=1`, once natively and twice under `setarch "$(uname -m)" -R valgrind --tool=cachegrind --cache-sim=no --smc-check=all-non-file` (Valgrind 3.22.0) with `MESA_SHADER_CACHE_DISABLE=true`, then twice more with the cache on in a fresh `MESA_SHADER_CACHE_DIR`.
  A Claude cloud session: Intel Xeon @ 2.10 GHz, 4 vCPUs, `avx2` and `avx512f` in `/proc/cpuinfo`.
  The planner ran it before posting the plan, so no raw file was kept; the figures were read from Valgrind's `I refs` line.
- **Result**: native `0.89 s`; counted `30.8 s` and `30.7 s`, `I refs` `2,106,700,314` and `2,106,554,792`, a spread of `0.0069%`.
  Both counted stores matched the native store (`diff -r` without `render.json`).
  With the cache on, the first run counted `2,110,342,267` and the second `610,819,679` (71% fewer).
- **Verdict**: control; it set the spike's method: the shader cache off on every counted run.

## 2026-11-27: instruction counts of lavapipe renders in a cloud session

- **Question**: how much does one binary's Valgrind instruction count move between repeats, under load and across two builds of one commit, and does it resolve a small CPU-side change (`#1122`)?
- **Method**: on `70b0f76` (`main`), in the cloud session above, with the game archives from `mise run cloud-assets -- fetch --replace-unmarked`, `mise run game-builds` and `mise run superset-all`.
  [`count.sh`](count.sh) runs one render with `mise run ab`'s film, `.ALL`, `--sidata` and render flags (`ab_timing.render_argv`), `--report-memory` in place of `--report-timing`, `LP_NUM_THREADS=1`, `MESA_SHADER_CACHE_DISABLE=true` and `setarch -R`, natively or under the step 1 Cachegrind command or `valgrind --tool=callgrind --separate-threads=yes --smc-check=all-non-file`, and appends a row to [`counts.csv`](counts.csv): the count, the wall from `date` around the command, the peak RSS (Valgrind's process under Valgrind), and a hash of the four stores.
  Spans: `B30` = `LOCATION 3680..=3709` and `B60` = `3680..=3739` (Span B's start), and `C30` = `INTRO 2500..=2529` and `C60` = `2500..=2559` (Span C's start).
  Runs, in order: `B30` and `B60` natively; three Cachegrind repeats of each; one Callgrind run of each; `B30` under Cachegrind with 4 busy-loop shells on the 4 vCPUs; `B30` on a second build of `70b0f76` (`CARGO_TARGET_DIR=build/scratch/icount/target-b`); then PR #951 (`7728e1e3`, `#944`'s `shadow_top` walk) and its parent `b87b3625`, each built in its own worktree: `C30` natively on both, `C30` and `C60` under Cachegrind on both, a second Cachegrind repeat of each on the parent, and one Callgrind `C30` on each; then two more Callgrind `B30` repeats; last, after the fresh review, `C60` natively on both and a third Cachegrind repeat of `C30` and `C60` on the parent.
  The release binary has symbols (`nm` finds `shadow_top`).
  [`summarize.py`](summarize.py) prints [`summary.txt`](summary.txt) from `counts.csv`, [`outside-allocator.txt`](outside-allocator.txt) (from [`outside_allocator.py`](outside_allocator.py) over `raw/*.cg.xz`) and [`callgrind-threads.txt`](callgrind-threads.txt) (each Callgrind thread file's `summary:` line); `mise exec -- uv run python -I work/2026-11/1122_instruction-count-gate/summarize.py`.
  [`diff-b30-r3-r1.txt`](diff-b30-r3-r1.txt), [`diff-b60-r2-r3.txt`](diff-b60-r2-r3.txt) and [`diff-c30-parent-951.txt`](diff-c30-parent-951.txt) are `cg_diff` then `cg_annotate --auto=no` of two runs; [`diff-b30-main-thread-cl-r2.txt`](diff-b30-main-thread-cl-r2.txt) is [`thread_diff.py`](thread_diff.py) over two `B30` Callgrind runs' main-thread listings; [`callgrind-b60-top.txt`](callgrind-b60-top.txt) lists `B60`'s top 20 functions per thread.
  The Cachegrind outputs and logs are in `raw/`; the Callgrind files (6.8 MB compressed) were not kept, only their per-thread totals and the listings above.
- **Result**:
  - Every counted store matched the native store of its span and build (`B30`, `B60`, `C30`, `C60`); #951 and its parent drew identical stores.
  - Whole-run counts: `B30` `28,151,461,402..28,170,706,144` in three repeats (`0.0684%`), `B60` `31,926,173,324..31,931,362,658` (`0.0163%`).
    The loaded run (`28,159,248,755`) and the second build (`28,160,263,581`) fall inside `B30`'s range.
    The two builds of `70b0f76` were not byte-identical (`sha256` `0f264f78…` and `6683c187…`, the target directory differing).
  - The loop's count, `B60 - B30` for 30 ticks: median `3,769,614,361`, and `3,755,467,180..3,779,901,256` (`0.65%` wide) between the repeats' extremes.
  - Almost all the repeat difference is in glibc's `malloc.c` and `memmove`: of `B30` r1 against r3's `19,244,742`, `malloc.c` holds `20,781,153` and `memmove` `-1,986,505`; of `B60` r2 against r3's, `malloc.c` `-14,859,835` and `memmove` `12,998,353`.
    Outside `malloc.c` and `memmove`, `B30`'s three repeats spread `0.0017%` (`450,094`), five with the loaded run and the second build `0.0027%`, `B60`'s `0.0094%` (`2,842,339`), and the loop's count is `3,499,729,339`, `0.0941%` wide between extremes.
  - Threads (three `B30` Callgrind repeats, whose whole-run counts are not compared with Cachegrind's): the main thread `20,156,671,323` (spread `9,255,779`, `0.0459%`), lavapipe's second thread `5,342,442,422` (`0.0258%`), its third, which runs the JIT-compiled shader code (unsymbolised addresses, `callgrind-b60-top.txt`), `2,605,055,005` (`0.0059%`).
    In two of the main thread's repeats, `_int_malloc` and `_int_free_maybe_consolidate` held `8,733,427` of the `9,252,353` difference.
    The main thread did `677,984,961` of the loop's `3,758,711,131` Callgrind instructions (`18.0%`), the JIT thread `2,496,834,763` (`66.4%`) and the second thread `583,892,365` (`15.5%`), from one Callgrind run of each span; its list in `B60` starts with `DefaultHasher::write` (`14.31%`), `path_distance` (`12.06%`) and `TerrainSurface::triangle_near` (`11.33%`).
  - #951, against the parent's three repeats: whole-run `C30` `-11,871,076` (`-0.1156%`), `16.1x` the parent's range (`737,254`); `C60` `-26,599,751` (`-0.2034%`), `16.7x` (`1,596,306`).
    Outside `malloc.c` and `memmove`, `C30` `-11,995,105` (`-0.1274%`, `10.2x`) and `C60` `-26,970,720` (`-0.2257%`, `40.2x`).
    `C30`'s whole-run change is `0.62x` `B30`'s whole-run repeat range (`19,244,742`): the allocator's noise differs by film, so one span's range does not bound another's.
    In `C30`, `PlacementRecords::shadow_top` went from `46,373,376` to `30,033,201` (`-16,340,175`, `-35.2%`), while `VisibilityCondition::eq` rose `5,746,932`.
  - Wall: `B30` `93.7..95.7 s` under Cachegrind against `3.23 s` natively (`29x`), `B60` `108.8..112.7 s` against `3.42 s` (`32x`), `C30` `49.4..53.0 s` against `1.08..1.11 s` (`46x`), `C60` `60.8..63.4 s` against `1.29..1.30 s` (`47x` to `49x`); Callgrind `109.7..122.4 s` on `B30`/`B60`.
    The loaded run took `115.0 s` against a `94.8 s` median.
    Peak RSS under Cachegrind `1,160 MiB` (`950 MiB` natively) on `LOCATION`.
- **Verdict**: adopted, with two departures from the plan's table: a gate compares whole-run counts of one span on two builds, not span differences, and reads the change outside the allocator and per function.
  The raw `B60 - B30` is `0.65%` wide, over the plan's `0.1%` bar, because the allocator's noise of both spans adds up; outside the allocator it is `0.0941%` wide, under it.
  The one loaded run counted inside the unloaded range; outside the allocator #951's change was `10x` to `40x` the parent's repeat range with the expected sign, and `shadow_top` alone fell more than the whole change; a counted span pair took under 4 minutes.
  A gate measures its own span's repeat range: `C30`'s whole-run change would be lost in `B30`'s whole-run range.
  `[Bounded Observation]`: 3 repeats a span, one loaded run, one machine, one day.
- **Lives in**: [`lavapipe-instruction-counts.md`](../../../research/parity/lavapipe-instruction-counts.md).
