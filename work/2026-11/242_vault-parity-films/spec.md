# VAULT Films in the Parity Corpus (design note)

Status: design under review; tickets filed (#242, § 8); implementation plan in [`vault-parity-films-implementation-2026-11-06.md`](plan.md); no code yet. Owner: unassigned.

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
| D2 | Adoption rule | The rule stays per film, with no aggregate across films. **Evidence-backed:** adopt when no film falls by more than 0.002 and at least one rises. **Heuristic:** adopt when no film falls by 0.002 or more, and either every film gains more than 0.002 or at least one gains more than 0.004. For two films this is today's rule restated, boundaries included: the evidence track tolerates a fall of exactly 0.002, the heuristic track does not. With four films, "every film gains more than 0.002" rarely holds, so in practice a heuristic change needs one film above 0.004 and none falling by 0.002. |
| D3 | Which films, in what order | Two at a time. Phase 1 is `vault-splanes` and `vault-land`. Phase 2 (`vault-balloon`, `vault-traintnl`) begins when two rounds in a row aimed at a phase-1 film's errors end as negatives in `log.md`, or on request. It needs only new reference rows, no code. |
| D4 | Films left out | `vault-tod` waits for a fade floor that works on night films (§ 7). `vault-bomb` and `vault-location` mostly repeat the aircraft errors CTRY already shows, and they are the two longest films. |
| D5 | Engine build of the new references | `playone = "unpatched"`, as for CTRY and INTRO. `makeone = "unpatched"` too: the film plays an archive made with `mise run make-all` on the unpatched `MAKEONE`, committed as a manifest (ADR 0032) and pinned by D9, because the archives shipped under `siarchive/` have no known build (§ 4.1). A film that stalls on an unpatched executable takes that executable's `patch3` build, with the cause written in `reason`. |
| D6 | Parallel scoring | `--jobs N` on `mise run parity` and `mise run sweep` runs (variant, film) render-and-score pairs at once. The default is `min(8, os.cpu_count() or 1, pairs)`. There is no live RAM or VRAM probe; the cost per job (§ 3.1) is documented instead. |
| D7 | Output under parallelism | Results on stdout print in the same fixed (variant, film) order as a sequential run, so the table, the winner line and the film summary lines are unchanged. Progress lines on stderr (`[parity] rendering …`, `[i/n] …`) may interleave. |
| D8 | Render start-up | The offscreen path tries a Vulkan-only instance first and falls back to `Backends::all()` when Vulkan yields no adapter, or only a CPU one, which it keeps if no backend has hardware. This saves about 1 s and 80 MiB per process, with byte-identical output (§ 3.2). The windowed path is unchanged. |
| D9 | Which archive a film plays | The reference pins it. Each `references.toml` row gains `all_sha256`. Archive resolution (`all_archive.resolve_all`) takes a pinned hash and returns the archive with those bytes (a stored `make-all` archive, a linked rebuild, or a shipped copy), or refuses. `parity` and `capture-ref` both resolve this way, so a render and its capture play the same archive (§ 4.1). It changes what a reference pins, so it needs an ADR amending ADR 0029. |

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
  [ADR 0006](../../../docs/adr/0006-ci-renders-on-lavapipe.md)). The GPU tests' software path
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
   `make-all` also writes `manifests/all/<slug>.toml` (ADR 0032). Commit it, so that another
   machine rebuilds the same bytes with `stuntreel link build` instead of running `MAKEONE`.
   `MAKEONE` sometimes never returns to DOS (#87). After two failed runs, try the `patch3`
   `MAKEONE` (D5). If that fails too, the film leaves phase 1 and the first phase-2 film takes its
   place.
2. Write the row: `film`, `all_sha256` of that archive (the manifest's), and
   `makeone = playone = "unpatched"` (D5). `capture-ref` reads its builds from the row (ADR 0029).
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
* An ADR amends ADR 0029: a reference pins its archive as well as its capture and builds.

### 4.2 `run_matrix` in `parity_pipeline`

One function owns running (variant, film) pairs in parallel. What a pair does is passed in,
because the two scripts lay out their trees differently: `sweep` renders into
`<workdir>/<film>`, while `parity` renders into a scratch tree and rotates `_current` into
`_previous` (`parity_run.prepare_source`).

```
Work = Callable[[FilmJob, V], FilmScore]          # V: the caller's variant (workdir, env, ...)

run_matrix(films, root, variants: Sequence[V], work: Work[V], *,
           jobs=1, on_variant=None)  # on_variant(index, results) as each variant completes
    -> list[list[FilmScore | FilmFailure]]   # [variant][film], in input order
```

`run_films` becomes `run_matrix` over one variant, with `run_film` (or `score_film` when
`render=False`) as the work. `parity_run` passes a work function made of `prepare_source` and
`score_film`. Each film has its own scratch, `_current` and `_previous` trees, so pairs never share
a tree.

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
  for them. The calling thread waits with `concurrent.futures.wait(..., timeout=0.5)` in a loop
  rather than a bare `result()`, so the interrupt is delivered on Windows, where a blocking lock
  wait may not be interruptible. The same loop dispatches `on_variant`.

### 4.3 The scripts

* **`parity_run.py`** gains `--jobs`. Its film loop moves onto `run_matrix` with a single
  variant and a work function made of `prepare_source` and `score_film`. `--reuse`, `--no-render`
  and `--retime` keep their meaning. The film summary lines print after the matrix returns, in
  film order.
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

Offline only, except where a live check is named. The tests for each piece are listed here.

**D8 (Rust).** The backend order is a pure step: a function takes the attempts
(`[VULKAN, all()]`), a preference and a request closure, and returns the first preferred adapter,
else the first found. A unit test drives it with a fake request, covering the case where Vulkan
finds an adapter, the case where it falls back, and a software Vulkan adapter passed over for
hardware but kept when nothing better exists, so the fallback is tested without a GPU. The existing GPU tests still pass, on lavapipe in
CI and locally. Live check: `mise run parity` gives identical score lines before and after.

**D9 (Python).** On a temporary data root holding two copies of a film with different `.ALL`
files:

* resolution follows the pin, including a pin that names a manifest rebuild;
* a pin that matches nothing is refused, and the error names the hash;
* a film with no row resolves as today;
* `parity` refuses a capture whose `meta.json` `all_sha256` differs from the pin.

Live check: with CTRY and INTRO pinned, `mise run parity` still prints 0.8725 and 0.8273.

**`run_matrix` (Python).** A fake work function stands in for `stuntreel`, as
[`tests/test_parity_pipeline.py`](../../../tests/test_parity_pipeline.py) already fakes `Run` for
`run_films`.

* **Order:** with `jobs=4` and a fake that sleeps a random time per call, results come back in
  [variant][film] input order.
* **Equivalence:** `jobs=1` and `jobs=4` give the same results for the same fake.
* **Isolation:** one failing pair yields a `FilmFailure`, and every other pair still runs. A film
  whose reference fails to open fails in every variant.
* **Environment:** through `run_film`, each render call receives its own variant's `env`, never
  another variant's.
* **`parity_run`:** with `--jobs 2`, each film's `_current` and `_previous` trees rotate exactly as
  at `--jobs 1`.
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

0. **The Vulkan-first instance (D8), in a PR of its own**, with its tests (§ 5). The output is
   byte-identical, so the PR needs no capture-beside-render picture; it says so instead. Update
   the `offscreen_adapter` comment, which quotes the 2 s cost, with § 3.2's figures.
1. **`run_matrix`, its tests, and `--jobs` on both scripts.** One commit. It changes no score, so
   it needs no log row.
2. **Docs and skill wording (§ 4.4)**, in the same PR as step 1.
3. **Archive pinning (D9, § 4.1)**, with its ADR and tests, in a PR of its own. It is independent
   of steps 0 to 2.
4. **Phase-1 reference rows (§ 4.1)**: one commit per film, each with its manifest and its
   `log.md` row. These need DOSBox and `MAKEONE`, are the only steps that do, and wait for step 3.

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

## 8. Tickets

Filed 2026-11-06. One parent and five tickets. T5 is labelled `research` and has no parent,
because `vault-tod` is out of this note's scope. Each ticket is one PR. Blocking is a native issue
dependency ([`docs/agents/issue-tracker.md`](../../../docs/agents/issue-tracker.md)). A ticket's body
copies its part of this note; when the note changes, the body is updated to match.

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
