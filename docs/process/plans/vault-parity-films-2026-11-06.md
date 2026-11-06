# VAULT Films in the Parity Corpus (design note)

Status: design, not started. Owner: unassigned.

## 1. Why

The parity loop scores two films, `CTRY.FLM` and `INTRO.FLM`. The retail `VAULT` films show
errors those two rarely or never show ([`research/parity/batch.md`](../../../research/parity/batch.md)
§ 4): the sea band wrong on every graded `SPLANES.FLM` frame, the aircraft not drawn on 11 of 12
`LAND.FLM` frames, and the balloon's sky, sun and parachute. Adding films gives rounds work that
changes the picture where CTRY and INTRO cannot see it.

Goal: more films become **fidelity targets**, so a gain on any of them counts towards adoption, at
the smallest cost in scoring logic and sweep time.

## 2. Settled decisions

| # | Decision | Choice |
|---|---|---|
| D1 | What the new films are for | Fidelity targets, not just a regression guard: a gain on any film counts. |
| D2 | Adoption rule | The rule stays per film, with no aggregate across films. **Evidence-backed:** adopt when no film falls by more than 0.002 and at least one rises. **Heuristic:** adopt when no film falls by 0.002 or more, and either every film gains more than 0.002 or at least one gains more than 0.004. For two films this is today's rule restated. |
| D3 | Which films, in what order | Two at a time. Phase 1 is `vault-splanes` and `vault-land`. Phase 2 (`vault-balloon`, `vault-traintnl`) begins when two rounds in a row aimed at a phase-1 film's errors end as negatives in `log.md`, or on request. It needs only new reference rows, no code. |
| D4 | Films left out | `vault-tod` waits for a fade floor that works on night films (§ 7). `vault-bomb` and `vault-location` mostly repeat the aircraft errors CTRY already shows, and they are the two longest films. |
| D5 | Engine build of the new references | `playone = "unpatched"`, as for CTRY and INTRO. `makeone = "unpatched"` too: the film plays an archive made with `mise run make-all` on the unpatched `MAKEONE` and pinned by D9, because the archives shipped under `siarchive/` have no known build (§ 4.1). A film that stalls on the unpatched `PLAYONE` takes `patch3`, with the cause written in `reason`. |
| D6 | Parallel scoring | `--jobs N` on `mise run parity` and `mise run sweep` runs (variant, film) render-and-score pairs at once. The default is `min(8, os.cpu_count() or 1, pairs)`. There is no live RAM or VRAM probe; the cost per job (§ 3) is documented instead. |
| D7 | Output under parallelism | Results print in the same fixed (variant, film) order as a sequential run, so the table, the winner line and the `[parity]` lines are unchanged. |
| D8 | Render start-up | The offscreen path tries a Vulkan-only instance first and falls back to `Backends::all()` only when Vulkan yields no adapter. This saves about 1 s and 80 MiB per process, with byte-identical output (§ 3.2). The windowed path is unchanged. |
| D9 | Which archive a film plays | The reference pins it. Each `references.toml` row gains `all_sha256`. Archive resolution (`all_archive.resolve_all`) takes a pinned hash and returns the archive with those bytes (a stored `make-all` archive, a linked rebuild, or a shipped copy), or refuses. `parity` and `capture-ref` both resolve this way, so a render and its capture play the same archive (§ 4.1). |

## 3. Evidence

Throwaway probes, 2026-11-06, release builds of `48f5d49`. The machine has 16 logical and 8
physical cores, 31 GiB of RAM and an RTX 4070 Laptop GPU with 8 GiB. The scripts were not kept.

### 3.1 Parallel renders (D6)

* **Renders run on the GPU.** Headless mode asks wgpu for the `HighPerformance` adapter
  ([`renderer.rs`](../../../crates/stunt-render/src/renderer.rs) `select_adapter`). Each render
  runs about 57 threads but keeps only 0.4 to 0.65 of a core busy.
* **The cost per render is flat.** About 300 MiB of RAM and about 200 MiB of VRAM, the same for
  `BOMB.FLM` (339 ticks drawn), `LOCATION.FLM` (751 ticks), CTRY and INTRO. A score takes about
  35 MiB and under 1.2 CPU-seconds.
* **Render-and-score throughput**, CTRY and INTRO alternating, all backends:

  | Jobs | Pairs/s | Peak RAM | Peak VRAM | GPU load (mean / max) |
  |---|---|---|---|---|
  | 1 | 0.19–0.25 | 0.3 GiB | — | — |
  | 8 | 0.80–0.86 | 2.1 GiB | 1.8 GiB | 37% / 76% |
  | 16 | 1.0–1.16 | 4.1 GiB | 3.2 GiB | 64% / 92% |
  | 32 | 0.83–1.30 | 8.2 GiB | 6.4 GiB | 70% / 96% |

  Ranges are the spread over two to three runs.
* **Reading.** 8 jobs gives 3 to 4x the throughput of one job. 16 jobs adds 25 to 35% for twice
  the memory. At 32 jobs the GPU is saturated: throughput is noisy, and 6.4 of the 8 GiB of VRAM is
  in use. With 8 jobs, a 6-variant sweep takes about 30 s on four films and about 60 s on eight.

### 3.2 Start-up (D8)

* **Most of a render is start-up.** Drawing one tick takes 1.7 to 3.4 s wall and 0.8 to 0.9
  CPU-seconds. The whole of CTRY takes 3.1 to 3.7 s and the whole of INTRO 6.7 s. Memory is the
  same either way.
* **Start-up is the GPU instance, not the film.** A timer patch on a one-tick CTRY render,
  reverted after the probe, measured these phases:
  * Building the scene takes about 9 ms.
  * `create_instance()` with `Backends::all()` takes about 0.95 s, mostly the Vulkan loader.
  * `select_adapter` takes another 0.95 s, enumerating DX12 adapters, and still picks the RTX's
    Vulkan adapter.
  * Opening the device takes about 30 ms.
* **A Vulkan-only instance** picks the same adapter. Measured on the same build:
  * Process wall time for one tick: 1.7 s → 0.63 to 0.74 s.
  * The whole of CTRY: 3.13 s → 2.39 s.
  * Peak RAM: 261 → 183 MiB, because the DX12 runtime is never loaded.
  * A full CTRY render is byte-identical either way (31 files, `render.json` included).
* **A GL-only instance** starts in 0.26 s but picks the AMD integrated GPU, so it is not a
  candidate.
* **CI already renders through Vulkan** (lavapipe,
  [ADR 0006](../../adr/0006-ci-renders-on-lavapipe.md)). The GPU tests' software path
  (`software_only`, `force_fallback_adapter`) finds no Vulkan software adapter on Windows. There
  it takes the fallback to all backends and gets WARP, as it does today.
* **Effect under parallel load** (render and score, CTRY and INTRO):

  | Jobs | All backends | Vulkan only |
  |---|---|---|
  | 1 | 0.19 pairs/s, 261 MiB | 0.31 pairs/s, 183 MiB |
  | 8 | 0.86 pairs/s, 2.0 GiB | 0.94 pairs/s, 1.5 GiB |
  | 16 | 1.16 pairs/s, 4.1 GiB | 1.32 pairs/s, 2.9 GiB |

  The saving is largest on one sequential render (+60%) and smaller under parallel load (+9 to
  14%), where the GPU is the bottleneck.

## 4. Components

### 4.1 Reference rows (phase 1: `vault-splanes`, `vault-land`)

Data only. `--films` already defaults to every row `references.toml` pins
([`cli.py`](../../../python/scripts/cli.py) `parity_options`), so once a row lands, `parity` and
`sweep` score that film without any code change.

**Blocker: archive provenance** ([`method.md`](../../../research/parity/method.md) § 3, 2026-11-06).
`reference_job` plays the first non-duplicate copy of a slug in sorted path order
(`batch_films.find`), with the `.ALL` beside it. `capture-ref` resolves its archive the same way
from whatever `--film` path it is given:

| Film | Copy the pipeline plays | Its `.ALL` | Other copies |
|---|---|---|---|
| CTRY, INTRO | `siarchive/Films/NewPLAY/Vault/` | shipped there; differs from the demo archive the reference captures recorded | `stisldem/VAULT/` with the demo `.ALL` |
| `vault-splanes` | `siarchive/Films/NewPLAY/Vault/SPLANES.FLM` | shipped there | none |
| `vault-land` | `siarchive/Films/OldPLAY/Vault/LAND.FLM` | shipped there | `stuntisl/VAULT/LAND.FLM`, no `.ALL` |

For CTRY and INTRO the mismatch is harmless today: renders from either archive score the same to
four decimals. For the new films it blocks the work. `archive_makeone_build` calls a `.ALL`
shipped under `siarchive/` `unknown`, and `require_builds` refuses an unknown archive for any film
whose row names a `makeone`, so neither film can be captured against a row. D9 fixes both: the
row pins the archive, and every tool resolves the archive by that pin.

Per film, once D9 has landed:

1. Make the film's archive with `mise run make-all -- --film <the .FLM above>` on the unpatched
   `MAKEONE`. The stored archive's `meta.json` records `makeone_sha256`, so its build is known.
2. Write the row: `film`, `all_sha256` of that archive, and `makeone = playone = "unpatched"`
   (D5). `capture-ref` reads its builds from the row (ADR 0029).
3. Capture with `mise run capture-ref -- --film <the .FLM above>`.
4. Promote the capture through the skill's "Comparing a candidate reference" procedure, which
   fills in `sha256`. Leave out `noise_sigma` (§ 7).
5. Score it at HEAD and add a `log.md` row recording the film's baseline.
6. Run the error readout (`errors-make` / `errors-score`) once, so the film's starting categories
   are on record next to `batch.md` § 4.

The rows depend on D9, not on § 4.2 to § 4.4.

D9 itself:

* `references.toml` rows gain an optional `all_sha256`. CTRY and INTRO pin the demo archives
  their captures recorded (`9de1bc1e…`, `27935a36…`); their scores must not move.
* `resolve_all` takes an optional pinned hash and returns the first archive it knows with those
  bytes: a stored `make-all` archive, a linked rebuild, or a sibling of any corpus copy of the
  film. If none matches, it refuses and names the hash.
* `reference_job` and `capture-ref` pass the row's pin. A film with no row resolves as today.
* `parity` refuses a reference capture whose `meta.json` `all_sha256` differs from the row's pin.
* Tests: offline, with a temporary data root that holds two copies of a film with different
  `.ALL` files. Resolution follows the pin, refuses a pin that matches nothing, and leaves a film
  with no row unchanged.

### 4.2 `run_matrix` in `parity_pipeline`

One function owns rendering in parallel; `run_films` becomes its one-variant case.

```
run_matrix(films, root, variants: Sequence[tuple[Path, dict[str, str] | None]], *,
           jobs=1, retime=None, render=True, run=run_command,
           on_variant=None)  # callback(index, results) as each variant completes
    -> list[list[FilmScore | FilmFailure]]   # [variant][film], in input order
```

* **Each film's reference is opened once**, through `reference_job` in an `ExitStack`, on the
  calling thread. All variants share that verified snapshot (ADR 0031), so a sweep checks each
  film's hash once rather than once per variant. A film whose reference cannot be opened becomes a
  `FilmFailure` in every variant.
* **Every (variant, film) pair is submitted to a `ThreadPoolExecutor(max_workers=jobs)`.** Threads
  are enough because the work runs in `stuntreel` child processes. `jobs <= 1` runs on the calling
  thread, exactly as today.
* **A pair that fails becomes a `FilmFailure`**, and the other pairs still run.
* **`on_variant` fires on the calling thread** once every film of a variant has finished. It is
  how the sweep prints progress and frees disk without waiting for the whole matrix (§ 4.3).
* **Ctrl+C** follows `batch_parity`'s pattern: `shutdown(cancel_futures=True)` drops the pairs not
  yet started. Running pairs finish, since a render takes seconds, and then the interrupt
  propagates. Worker threads never see the interrupt, so the runner's own tree kill does not fire
  for them.

### 4.3 The scripts

* **`parity_run.py`** gains `--jobs`. Its film loop moves onto `run_matrix` with a single
  variant. `--reuse` and `--no-render` keep their meaning (`render=False`).
* **`parity_sweep.py`** gains `--jobs`. It builds the variant list (workdir and env per variant)
  and calls `run_matrix` once, with an `on_variant` callback that runs today's per-variant steps:
  * the notes and the progress line;
  * the `iou` probe;
  * `--keep-best`: delete the variant's render directories unless it is the best so far.

  `rank` breaks ties by variant index, so the best variant does not depend on completion order.
  Disk stays bounded by `jobs` variants in flight plus the best.
* **`--jobs` is a shared flag in [`cli.py`](../../../python/scripts/cli.py)**, next to `--films`,
  so the two scripts parse it once. The help text gives the cost per job from § 3.

### 4.4 Docs and skill

* **[`improving-render-parity`](../../../.agents/skills/improving-render-parity/SKILL.md):**
  * The adoption rule takes D2's wording.
  * "Score both films" becomes "Score every film".
  * The baseline step expects one line per film.
  * The cost rules mention `--jobs`.
* **[`research/parity/probes.md`](../../../research/parity/probes.md) § 4 and the `mise.toml`
  descriptions of `parity` and `sweep`** stop saying "CTRY and INTRO" and "both films".
* **[`research/parity/method.md`](../../../research/parity/method.md)** records the facts about
  the loop: renders use the high-performance GPU adapter; each costs about 180 MiB of RAM and
  200 MiB of VRAM, whatever the film's length (figures after D8); and the throughput by jobs.

## 5. Testing

Offline only. A fake `Run` adapter stands in for `stuntreel`, as
[`tests/test_parity_pipeline.py`](../../../tests/test_parity_pipeline.py) already does for
`run_films`.

* **Order:** with `jobs=4` and a fake that sleeps a random time per call, results come back in
  [variant][film] input order.
* **Equivalence:** `jobs=1` and `jobs=4` give the same results for the same fake.
* **Isolation:** one failing pair yields a `FilmFailure`, and every other pair still runs. A film
  whose reference fails to open fails in every variant.
* **Environment:** each render call receives its own variant's `env`, never another variant's.
* **One snapshot per film:** `reference_job` is entered once per film, whatever the number of
  variants.
* **Callback:** `on_variant` fires once per variant, on the calling thread, after that variant's
  last pair.
* **Interrupt:** a `KeyboardInterrupt` raised while pairs are pending cancels them, and the
  interrupt propagates.
* **Sweep:** `--keep-best` keeps the same variant at `jobs=1` and `jobs=4` when two variants tie.
* **CLI:** `--jobs` parses on both scripts and defaults to `min(8, cpu_count, pairs)`. `--jobs 0`
  is a usage error.

Live check (not in `tests/`): run `mise run parity -- --jobs 1` and `mise run parity -- --jobs 8`
on the same binary. Both must print identical score lines, since identical builds render
identically ([`method.md`](../../../research/parity/method.md) § 3).

## 6. Order of work

0. **The Vulkan-first instance (D8), in a PR of its own.**
   * Make the backend order a pure step: a function that takes the backend attempts
     (`[VULKAN, all()]`) and a request closure, and returns the first adapter. A Rust unit test
     drives it with a fake request, so the fallback is tested without a GPU.
   * The existing GPU tests still pass, on lavapipe in CI and locally.
   * Live check: `mise run parity` gives identical score lines before and after. The output is
     byte-identical, so the PR needs no capture-beside-render picture; it says so instead.
   * Update the `offscreen_adapter` comment, which quotes the 2 s cost, with § 3.2's figures.
1. **`run_matrix`, its tests, and `--jobs` on both scripts.** One commit. It changes no score, so
   it needs no log row.
2. **Docs and skill wording (§ 4.4)**, in the same PR as step 1.
3. **Archive pinning (D9, § 4.1)**, in a PR of its own. It is independent of steps 0 to 2.
4. **Phase-1 reference rows (§ 4.1)**, one commit per film, each with its `log.md` row. These need
   DOSBox and `MAKEONE`, are the only steps that do, and wait for step 3.

## 8. Tickets

Filed 2026-11-06. One parent and five tickets; T5 is labelled `research` and has no parent, because `vault-tod` is out of this note's scope. Each ticket is one PR; blocking is a native issue dependency
([`docs/agents/issue-tracker.md`](../../agents/issue-tracker.md)).

| # | Title | Labels | Covers | Blocked by |
|---|---|---|---|---|
| P [#242](https://github.com/neilsh/stunt-reel/issues/242) | VAULT films are not parity targets | none (parent) | this note | — |
| T1 [#243](https://github.com/neilsh/stunt-reel/issues/243) | Headless renders spend a second enumerating graphics backends they never use | `ready-for-agent` | D8, step 0 | — |
| T2 [#244](https://github.com/neilsh/stunt-reel/issues/244) | `parity` and `sweep` render one film at a time | `ready-for-agent` | D6, D7, § 4.2 to § 4.4, steps 1 and 2 | — |
| T3 [#245](https://github.com/neilsh/stunt-reel/issues/245) | Parity renders don't play the archive their reference capture recorded | `ready-for-agent` | D9, step 3 | — |
| T4 [#246](https://github.com/neilsh/stunt-reel/issues/246) | `SPLANES.FLM` and `LAND.FLM` are not parity references | `ready-for-human` (DOSBox, `MAKEONE`) | D3, D5, step 4 | T3 |
| T5 [#247](https://github.com/neilsh/stunt-reel/issues/247) | The fade floor drops most frames of a night film | `needs-triage`, `research` | § 7, a prerequisite for `vault-tod` | — |

T3 also fits under the existing parent #87 (films archived and captured reliably on both builds).
Phase 2 (`vault-balloon`, `vault-traintnl`) gets its own ticket when D3's trigger fires, not now.
Drawing only the captured ticks (§ 7) stays a note here until a sweep's render time is the
bottleneck again.

## 7. Out of scope (later specs or later steps)

* **A fade floor for night films**, which `vault-tod` needs. The fade floor drops most frames of a
  night film ([`method.md`](../../../research/parity/method.md) § 2.1).
* **Drawing only the captured ticks.** Parity renders draw every tick in the capture's range.
  Drawing only the scored ones (`--at-ticks`) would make each render cheaper, but retime needs the
  neighbouring ticks, so it would have to be optional.
* **`noise_sigma` for each new film.** Optional in `references.toml` (INTRO has none), and the
  adoption floor of 0.002 is a build-level bound, not this sigma.
* **One process rendering several jobs.** It would share one GPU instance and device, so it would
  save the per-process start-up (about 0.7 s once D8 lands) and most of the roughly 180 MiB of RAM
  per job. Rejected for now:
  * Under parallel load the GPU, not start-up, limits throughput (§ 3.2), so sharing a process
    would gain little speed.
  * At the default of 8 jobs, memory is not a constraint.
  * The `DBG_*` switches a sweep varies are added for one round, never committed, and read from
    the process environment with `std::env::var` (the skill's cost rule 8). Variants could share
    a process only if every such switch were threaded through a per-job config, which is the
    ceremony the throwaway switches exist to avoid.
  * One panic would lose every job in the process, and per-job timeouts would move into Rust.
* **A live RAM or VRAM cap on `--jobs`.** At the default of 8, § 3 leaves ample room on this
  machine.
* **D8 on the windowed path.** Presentation surfaces are not covered by the probe.
