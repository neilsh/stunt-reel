# Journal: distilling `lavapipe-render-time.md`, third pass

Text cut from [`lavapipe-render-time.md`](../../../research/parity/lavapipe-render-time.md) as of commit `82f0265`, moved here verbatim: section 3's five per-issue blocks, which the note now states condensed, and the `summary:` this pass shortened.
Only relative link paths changed; a section number in the moved text names a section of the note as it stood at `82f0265` (`git show 82f0265:research/parity/lavapipe-render-time.md`), and "below" or "section N" mean that note there.
Sections 4, 5 and 7, section 6's memory case, one Ruled out entry and open questions 3 and 4 moved, unchanged apart from section numbers and links, to [`lavapipe-render-workers.md`](../../../research/parity/lavapipe-render-workers.md), which is current reference, not journal.

## 2026-11-23: Where lavapipe spends the loop on the whole LOCATION film, as § 3 stated it (#1002)

**Where lavapipe spends the loop on the whole `LOCATION` film (`#1002`).**
`[Bounded Observation]`, 2026-11-23, `f6976e67` + the patch in the source below (`#920`'s loop timer and skip-all switch), Windows `mesa-dist-win 25.2.8`, a user-mode stack sampler at about 190 Hz with mesa-dist-win's `vulkan_lvp.pdb` (from `mesa3d-25.2.8-debug-info-msvc.7z`), two sampled runs a cell on the whole film (`12..=8262`) and on Span B (one for Span B's skip-all), the sampler adding `1.9%..6.9%` to the loop, each variant's stores byte-identical to its unsampled runs'.
The main thread waits on lavapipe's queue fence for `59.3%` of the whole film's loop, so lavapipe's queue thread, which executes every command buffer and is busy or waiting on the rasterizers for `96.5%..96.8%` of the loop, is its critical path; a part's share of that thread's samples is its share of the loop while the main thread waits, and the main thread's own work (`37.3%`, `wgpu` included) would cap what any part saves, if that work does not change.
Over the whole film the queue thread's parts are the rasterizers' work it waits for (`26.7%`; the rasterizers' busy samples are about `78%` JIT fragment shading, and primitives with 4 edge planes, lines among them, `7.6%..8.2%`), the draw module's vertex work (`21.4%`), line setup and binning (`14.6%`), storing the fragment state in the scene (`10.2%`), other state changes and pipeline binds (`8.5%`) and triangle setup and binning (`5.4%`); the queue submit's own overhead is `2.1%` there and `1.5%` on the main thread.
Base minus skip-all puts the world's part of these at `13.0%` of the loop for lines, `11.0%` vertex, `7.5%` rasterization, `4.5%` the state store, `4.2%` other state and `2.3%` triangles.
These are differences of sampled loops whose sampler cost differs (`+1.9%` base, `+6.1%` skip-all, so the sampled loops cut `47.1%` where the unsampled ones cut `49.2%`), so each world's part leans low, by about 2 points of the base loop in total; and the triangle lever's `5.4%` is `0.4` points above the 5% bar, less than the sampler's cost to the loop, so it may not clear the bar unsampled.
The state store is llvmpipe's `try_update_scene_state`, whose `memcpy` and `memcmp` take `9.2%` of the queue thread's samples.
On Span B the store is `28.3%` of the loop (`745 ms`, `5 ms` with skip-all), and llvmpipe's first-use shader compiles take a further `17.2%` there, all in the loop's first half second.
So the whole film's world cost is mostly line setup, vertex work and rasterization (`9,102` of `13,620 ms`), and the state store is the largest single part of Span B's loop (`28.3%`; `740` of the world's `1,948.5 ms` there, about `38%`), consistent with `#920`'s grouping probe saving far more on Span B than on the whole film.
The JIT fragment-shading samples cannot be split between `fs_main_plane`, `prop_shape` and the rest (JIT code has no symbols), and `3.5%..3.7%` of the rasterizers' busy samples have no Mesa owner.
By Mesa 25.2.8's source the store compares the current fragment state with the one last stored and, when they differ, copies a `32,440`-byte `lp_rast_state` into the scene (its `lp_jit_resources` arrays are `32,384` bytes, by the PDB): `[Supported Inference]`, from the source and the PDB, with the stores a frame not counted.
_Source: [where Windows lavapipe spends the loop on the whole LOCATION film](../1002_lavapipe-world-profile/journal.md#2026-11-23-where-windows-lavapipe-spends-the-loop-on-the-whole-location-film), sampler [`stack_sampler.py`](../1002_lavapipe-world-profile/stack_sampler.py), patch [`profile-probe.patch`](../1002_lavapipe-world-profile/profile-probe.patch)._

**Lives in** [`lavapipe-render-time.md`](../../../research/parity/lavapipe-render-time.md), § 3, condensed.

## 2026-11-23: One binary against itself through the interleaved runner, as § 3 stated it (#1004)

**One binary against itself through the interleaved runner (`#1004`).**
`[Bounded Observation]`, 2026-11-23, `main` at `71b6e10d`, Windows `mesa-dist-win 25.2.8`, `mise run ab` ([`time-a-headless-render.md`](../../../docs/howto/time-a-headless-render.md) § 3) with the same release binary as both variants, Span B (`3680..=3979`), 4 pairs, the order alternated.
The loop medians were `4319.0 ms` (`a`) and `3914.5 ms` (`b`), a change of `-9.4%`, with `b` faster in `2` of `4` pairs and the eight runs spread `32.2%` (`3680.8` to `4867.3 ms`); the stores hashed alike in every run.
In this one run, on one machine, a 4-pair median on this cell differed by `9.4%` between two identical binaries, so the owner's A/A bar (a median within `±1%`) was missed; it says nothing about other days or cells.
_Source: [the same binary on both sides of `mise run ab`](../1004_ab-timing-runner/journal.md#2026-11-23-the-same-binary-on-both-sides-of-mise-run-ab-span-b-on-lavapipe)._

**Lives in** [`lavapipe-render-time.md`](../../../research/parity/lavapipe-render-time.md), § 3, condensed with `#1018` under timing noise.

## 2026-11-23: World stream sizes a frame, as § 3 stated it (#999)

**How much of the world one frame's walk emits, the size of a frame-streamed world (`#999`).**
`[Bounded Observation]`, 2026-11-23, `eabff61a` + the patch in the source below, a CPU count over every frame of the seven reference films' captured tick ranges at `320 x 200` with `185` viewport rows, no render and no timing.
The probe plans the world as the upload does (one chunk on every film), walks it on each frame's camera, and checks on every frame that its slices are `collect_world_meshes`'s, in order; it counts each emitted node's vertex window, its indices and its outline indices.
The largest frame of the seven films emits `75,576` vertices, `76,008` indices and `149,956` outline indices, all on `INTRO` tick 3635: `2.88` MiB at `28` B a vertex and `4` B an index or outline index (`3.74` MiB with the `12` B apex), against `LOCATION`'s `333.75` MiB of baked world buffers (`#920`, section 6).
`LOCATION`'s largest frame is `60,838`, `62,712` and `116,832` (tick 5151), its mean frame `7,013.8` vertices, `8,140.3` indices and `8,812.3` outline indices (about `0.26` MB); the ground slices alone peak at `14,935` vertices (`TRAINTNL` 101), and a per-frame prop-runs table at `987` pieces (`LOCATION` 3824) against the world's `31,441` runs.
These are the maxima of these films' captured ranges at this size and viewport, not a bound for any film or lens.
_Source: [world stream sizes a frame on the seven reference films](../999_frame-streamed-world/journal.md#2026-11-23-world-stream-sizes-a-frame-on-the-seven-reference-films), patch [`world-stream-probe.patch`](../999_frame-streamed-world/world-stream-probe.patch)._

**Lives in** [`lavapipe-render-time.md`](../../../research/parity/lavapipe-render-time.md), § 3, condensed.

## 2026-11-24: What spreads one binary's Span B lavapipe runs, as § 3 stated it (#1018)

**What spreads one binary's Span B lavapipe runs (`#1018`).**
`[Bounded Observation]`, 2026-11-24, `main` at `d4f00c76`, Windows `mesa-dist-win 25.2.8`, one release binary run back to back on Span B on the owner's 16-thread Ryzen 7 7745HX laptop, recording per run the share of all logical CPUs other processes used.
Other processes' CPU load slows the loop: 8 spinning processes (about `55%` of the CPUs) raised the median `19.3%` over a quiet probe's (`2885.5` against `2418.05 ms`) and 16 (about `92%`) `75.2%` (`4237.3 ms`, its runs `4103.2..4318.1 ms`, inside `#1004`'s `3680.8..4867.3 ms`, whose load was not recorded).
A steady load moved every run alike (spreads `3.7%` and `5.2%` under 8 and 16 spinners).
In `#1018`'s A/A the one run at `10.3%` other load was `16.3%` slower than the slowest of the four runs before it (`2815.1 ms`; those at `3.1%..4.5%`); no probe tested whether that load caused it, and in a quiet probe a run at `12.7%` was faster than one at `5.3%` (`2482.7` against `2563.4 ms`).
The effective clock (`119.2%..128.5%` of base) did not order the runs, and run order was already ruled out by `#1004`'s A/A; a slow first run (`11.0%` over the median of the next seven in one quiet probe, the fastest after 120 s idle in another) is not separated from the load of starting the runner.
On a quiet machine (other load `4.5%..12.7%`) seven runs still spread `9.6%` (`2338.1..2563.4 ms`), unexplained by load or clock.
`mise run ab` now records other processes' load per run, waits before each timed run for the machine to be at most `10%` busy, stops after a timed run over it, and runs one untimed, ungated warm-up round ([`time-a-headless-render.md`](../../../docs/howto/time-a-headless-render.md) § 3).
Its A/A with those checks stopped on the load check twice (after 5 and 2 of 8 runs, at `10.3%` and `10.2%` other load); a third, at a `15%` load bar, completed at `8.9%..11.2%` other load with a median change of `-1.07%` against `±1%`, each side faster in 2 of 4 pairs, and its eight loops spread `6.2%` (`2302.9..2445.3 ms`), so the bar was missed and the owner accepted that one result as an exception, not a pass.
So between two identical binaries a 4-pair median on this cell moved `1.07%` and the eight runs spread `6.2%`, in one run on one machine.
_Source: [what spreads one binary's Span B lavapipe runs](../1018_lavapipe-ab-variance/journal.md#2026-11-24-what-spreads-one-binarys-span-b-lavapipe-runs), [the A/A check after the fix](../1018_lavapipe-ab-variance/journal.md#2026-11-24-the-aa-check-after-the-fix-stopped-by-the-load-check), [the second re-run, completed](../1018_lavapipe-ab-variance/journal.md#2026-11-25-the-second-owner-approved-aa-re-run-at-a-15-load-bar-completed-missed-the-median-bar)._

**Lives in** [`lavapipe-render-time.md`](../../../research/parity/lavapipe-render-time.md), § 3, condensed with `#1004` under timing noise.

## 2026-11-26: Placements in the shared world slices on the seven reference films, as § 3 stated it (#1090)

**Whether a placement lies in the shared `WORLD_BASE` and `WORLD_DECAL` slices, on the seven reference films (`#1090`).**
`[Bounded Observation]`, 2026-11-26, `main` at `25eb9586` + the patch in the source below, a CPU count of each film's world as `build_world` makes it and `WorldPlacements::new` reads it, run with the parity render's own arguments, no renderer, no timing.
It repeats the check `#920` ran on `LOCATION` and `INTRO` (the Ruled out entry below): for each placement record with mesh spans, whether its `MeshSpans::base` or `::decal` run of indices is non-empty, and whether it lies inside the `WORLD_BASE` run (indices `0..342`) or the `WORLD_DECAL` run (`342..360`), which are the same on every film.
`WorldPlacements::split` takes the cuts it makes out of those slices from such spans (`WorldPlacements::spans`, through `cut_out`), so a film with none has nothing to cut at any tick.

| Film | Records | With mesh spans | Non-empty base span | Non-empty decal span |
|---|---|---|---|---|
| `CTRY` | 316 | 306 | 0 | 0 |
| `INTRO` | 26,386 | 10,723 | 0 | 0 |
| `LAND` | 845 | 834 | 0 | 0 |
| `BALLOON` | 8,983 | 1,589 | 0 | 0 |
| `TRAINTNL` | 1,049 | 1,049 | 0 | 0 |
| `BOMB` | 1,158 | 970 | 0 | 0 |
| `LOCATION` | 56,585 | 35,481 | 0 | 0 |

On each of the seven films no placement holds an index in either run, so no placement is cut out of the shared slices; each placement with mesh spans has nodes of its own (`MeshSpans::nodes` non-empty, the same counts).
The five films `#920` did not check (`CTRY`, `LAND`, `BALLOON`, `TRAINTNL`, `BOMB`) match its `LOCATION` and `INTRO` result; the probe's `INTRO` and `LOCATION` rows also reproduce `#920`'s zero.
The counts are of each film's whole world build (the patch returns before playback, so the captured tick range does not bound them), not of a rendered tick; records of a placement the walk prunes as far from every camera eye are absent from them, as from the world mesh.
For `#999`'s byte-identical test (design note section 6, open call 8) this means none of the seven films exercises a stream builder's span-per-placement range: the test over them needs none on these films, and such a range, if built, would be covered by a synthetic fixture, not a film.
This note decides no design.
The probe's `LOCATION` and `INTRO` world totals differ slightly from `#920`'s and `#999`'s (`INTRO` `128,772` nodes and `819,745` vertices against `128,768` and `819,265`; `LOCATION` `35,481` records with mesh spans against `35,479`); `[Hypothesis]` the OP_BLOCK cube change (`#1032`, `1e1d5680`) between their trees and this one added them, not isolated.
_Source: [placements cut out of the shared slices on the seven reference films](../1090_placement-cut-probe/journal.md#2026-11-26-placements-cut-out-of-the-shared-slices-on-the-seven-reference-films), patch [`world-cuts-probe.patch`](../1090_placement-cut-probe/world-cuts-probe.patch), driven by [`probe_world_cuts.py`](../1090_placement-cut-probe/probe_world_cuts.py)._

**Lives in** [`lavapipe-render-time.md`](../../../research/parity/lavapipe-render-time.md), § 3, condensed, its table as one sentence.

## 2026-11-26: The summary as it stood at 82f0265

```yaml
summary: "Which renderer changes cut headless render time on lavapipe and the GPU, where the time goes now, and what a render's memory goes to per worker. Landed: #596, #602, #644, #811, the view-facing cull #914 (52.4% to 80.6% of the Windows lavapipe loop in its probe), #933, #942, #943, #944 and stuntreel --workers (#916: four child processes render LOCATION 1.85x faster on 4 vCPUs, while four in-process VkDevices sharing one instance regress on Ubuntu Mesa 25.2.8). On lavapipe the world's base and decal draws hold 49.0% of the whole LOCATION loop; #1002's stack profile puts that loop on lavapipe's queue thread (rasterizers 26.7%, vertex work 21.4%, line setup 14.6%, the fragment-state store 10.2%, and 28.3% of Span B). #999 sizes a frame-streamed world at up to 2.88 MiB a frame (INTRO tick 3635) against LOCATION's 333.75 MiB baked. A LOCATION render's memory is mostly its world mesh (1,004 MiB Linux lavapipe peak, 749 MiB once release_world_mesh frees it; each extra lavapipe device adds 751..796 MiB RSS). Other processes' CPU load slows the Span B lavapipe loop (16 spinners +75.2%), so mise run ab now records it and gates on it (#1018). No-go: culling actors, #919, #915b, #926, #622, #920 and #1000."
```

**Lives in** [`lavapipe-render-time.md`](../../../research/parity/lavapipe-render-time.md), shortened, with the workers and memory clauses in [`lavapipe-render-workers.md`](../../../research/parity/lavapipe-render-workers.md).
