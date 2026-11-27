---
summary: "Valgrind counts of a lavapipe render moved up to 0.07% between repeats, almost all in glibc's malloc and memmove; outside them 0.01%, and #951's 0.13% to 0.23% cuts were 10x to 40x that range."
sidebar_label: "Instruction counts on lavapipe"
---
# Parity: Instruction Counts of a Lavapipe Render

* **Scope**: whether a Valgrind instruction count of a short headless render on lavapipe can gate a perf change without a quiet machine, beside the wall-time runs of `mise run ab` ([`time-a-headless-render.md`](../../docs/howto/time-a-headless-render.md) § 3), whose noise is in [`lavapipe-render-time.md` § 3](lavapipe-render-time.md#3-where-loop-time-goes) and [`lavapipe-ab-pair-count.md`](lavapipe-ab-pair-count.md).
* **Sources**: `#1122`'s runs in a Claude cloud session (Intel Xeon @ 2.10 GHz, 4 vCPUs, `avx2` and `avx512f`), Valgrind 3.22.0, Ubuntu 24.04's `mesa-vulkan-drivers 25.2.8-0ubuntu0.24.04.5` with `LP_NUM_THREADS=1`, release builds of `70b0f76`, of PR #951 (`7728e1e3`) and of its parent.
  * **Evidence tier**: `[Bounded Observation]` throughout: 3 repeats a span, one loaded run, one machine, one day.
* **Spans**: `B30` and `B60` are the first 30 and 60 ticks of Span B (`LOCATION 3680..=3709`, `3680..=3739`), `C30` and `C60` those of Span C (`INTRO 2500..=2529`, `2500..=2559`), rendered with `mise run ab`'s film, `.ALL`, `--sidata` and render flags.

## 1. Setup

Each counted run is the render under `setarch "$(uname -m)" -R valgrind --tool=cachegrind --cache-sim=no --smc-check=all-non-file`, with `MESA_SHADER_CACHE_DISABLE=true` and `LP_NUM_THREADS=1`; `valgrind --tool=callgrind --separate-threads=yes` splits the count by thread.
Mesa's shader cache must be off (or a fresh `MESA_SHADER_CACHE_DIR` each run): with it on, a second run of the synthetic film counted 71% fewer instructions than the first, having loaded its compiled shaders.
Every counted store matched the native store of its span and build.
Rust's `HashMap` seed (`RandomState`) cannot be pinned from outside the process; the count does not need it pinned (section 2).
_Source: [the smoke run and the shader cache](../../work/2026-11/1122_instruction-count-gate/journal.md#2026-11-27-a-valgrind-smoke-run-on-the-synthetic-film-and-mesas-shader-cache), [counts in a cloud session](../../work/2026-11/1122_instruction-count-gate/journal.md#2026-11-27-instruction-counts-of-lavapipe-renders-in-a-cloud-session)._

## 2. Spread, load and builds

| Count | `B30` (3 repeats) | `B60` (3 repeats) | Loop, `B60 - B30` |
|---|---|---|---|
| Whole run | `28,159,327,819`, spread `0.0684%` | `31,928,942,180`, `0.0163%` | `3,769,614,361`, `0.65%` wide |
| Outside glibc's `malloc.c` and `memmove` | spread `0.0017%` | `0.0094%` | `3,499,729,339`, `0.0941%` wide |

"Wide" is the gap between the largest and smallest difference of a `B60` and a `B30` repeat.
Almost all the difference between two repeats is in glibc's `malloc.c` and `memmove` (`20,781,153` and `-1,986,505` of one pair's `19,244,742`); in three Callgrind repeats of `B30` the main thread spread `0.0459%`, lavapipe's two other busy threads `0.0258%` and `0.0059%`. Why the allocator's path changes between repeats is not traced.
One `B30` run with 4 busy-loop shells on the 4 vCPUs counted `28,159,248,755`, inside the unloaded range, and took `115.0 s` against `94.8 s`; a second build of the same commit, whose binary was not byte-identical, counted `28,160,263,581`, also inside it.
Outside the allocator, the five `B30` runs spread `0.0027%`.
_Source: [counts in a cloud session](../../work/2026-11/1122_instruction-count-gate/journal.md#2026-11-27-instruction-counts-of-lavapipe-renders-in-a-cloud-session)._

**Where the loop's instructions are.**
The main thread, our CPU-side Rust, did `18.0%` of the loop's Callgrind instructions (`677,984,961` of `3,758,711,131` for 30 ticks of Span B); lavapipe's busiest thread, which runs the JIT-compiled shader code (no symbols), did `66.4%` (`2,496,834,763`), and its other thread `15.5%` (`583,892,365`), in one Callgrind run of each span.
A short span's count is mostly start-up: `B30`'s whole run counts about 7.5 times its 30 ticks' loop.
_Source: [counts in a cloud session](../../work/2026-11/1122_instruction-count-gate/journal.md#2026-11-27-instruction-counts-of-lavapipe-renders-in-a-cloud-session)._

## 3. A small change: #951

PR #951 walks only collision-bearing placement records in `shadow_top` (`#944`); its wall-time record is a phase cut with no loop saving claimed ([`lavapipe-render-time.md` § 1](lavapipe-render-time.md#1-changes-that-cut-render-time)).

| Span | Whole run | Outside the allocator |
|---|---|---|
| `C30` | `-11,871,076` (`-0.1156%`), `16.1x` the parent's repeat range | `-11,995,105` (`-0.1274%`), `10.2x` |
| `C60` | `-26,599,751` (`-0.2034%`), `16.7x` | `-26,970,720` (`-0.2257%`), `40.2x` |

Each change is against the median of three repeats of the parent, and each multiple against their range.
`C30`'s whole-run change is `0.62x` `B30`'s whole-run repeat range, so the allocator's noise differs by film and a gate needs the range of its own span.

Per function, `PlacementRecords::shadow_top` fell from `46,373,376` to `30,033,201` instructions on `C30` (`-35.2%`), while `VisibilityCondition::eq` rose `5,746,932`.
The stores were identical.
_Source: [counts in a cloud session](../../work/2026-11/1122_instruction-count-gate/journal.md#2026-11-27-instruction-counts-of-lavapipe-renders-in-a-cloud-session)._

## 4. Cost

Under Cachegrind `B30` took `93.7..95.7 s` (`29x` its `3.23 s` native run), `B60` `108.8..112.7 s` (`32x`), `C30` `49.4..53.0 s` (`46x`) and `C60` `60.8..63.4 s` (`47x` to `49x`); Callgrind took `109.7..122.4 s` on `B30` and `B60`.
Peak resident memory on `LOCATION` was `1,160 MiB` under Cachegrind against `950 MiB` natively.
_Source: [counts in a cloud session](../../work/2026-11/1122_instruction-count-gate/journal.md#2026-11-27-instruction-counts-of-lavapipe-renders-in-a-cloud-session)._

## 5. Verdict

**Adopt a count step for perf tickets, wall time kept for final confirmation and the GPU.**
A count compares the whole-run counts of one span on two builds, three repeats each, and reads the change outside glibc's `malloc.c` and `memmove` against that span's own repeat range, and per function: on that reading the repeats spread at most `0.0094%`, the one loaded run counted inside the unloaded range, and #951's change was `10x` to `40x` its repeat range with the expected sign, in the function it changed.
Differences of two spans add both spans' allocator noise (`0.65%` wide on the whole count), so a gate does not use them on the raw count.
The count cannot see memory traffic, cache use or parallelism, so fewer instructions is not always faster; JIT-compiled shader code counts but has no symbols; and GPU timing still needs the hardware.
_Source: [counts in a cloud session](../../work/2026-11/1122_instruction-count-gate/journal.md#2026-11-27-instruction-counts-of-lavapipe-renders-in-a-cloud-session)._

## Ruled out

* **Pinning Rust's hash seed from the environment**: `std`'s `RandomState` has no such switch; the count moved `0.0017%` outside the allocator without it, so it is not needed; [journal](../../work/2026-11/1122_instruction-count-gate/journal.md#2026-11-27-instruction-counts-of-lavapipe-renders-in-a-cloud-session).
* **The loop's count as `B60 - B30` on the raw count**: `0.65%` wide between repeats, over the `0.1%` bar, from the allocator noise of both spans; [journal](../../work/2026-11/1122_instruction-count-gate/journal.md#2026-11-27-instruction-counts-of-lavapipe-renders-in-a-cloud-session).
* **Counting with Mesa's shader cache on**: a second run counted 71% fewer instructions than the first; [journal](../../work/2026-11/1122_instruction-count-gate/journal.md#2026-11-27-a-valgrind-smoke-run-on-the-synthetic-film-and-mesas-shader-cache).

## Open questions

1. Whether `perf stat -e instructions:u` works under WSL 2 on the owner's laptop, and whether a Valgrind count of one build agrees between that laptop and a cloud session (`#1154`).
2. Why glibc's allocator takes a different path between repeats of one binary (thread interleaving, `RandomState`'s seed, or both), and whether pinning it would let a gate read the whole count.
3. How the spread grows with the span and on other spans and films: these figures rest on 30 and 60 ticks of Spans B and C.
