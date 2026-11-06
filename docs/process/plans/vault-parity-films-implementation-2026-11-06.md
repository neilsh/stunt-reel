# VAULT Parity Films Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the parity loop cheap to extend to more films, and pin each reference's archive so
`SPLANES.FLM` and `LAND.FLM` can become references.

**Architecture:** There are three independent PRs, one per ticket:

- **#243:** the renderer's offscreen path tries a Vulkan-only wgpu instance before all backends.
- **#244:** a generic `run_matrix` in `parity_pipeline` runs (variant, film) pairs on a thread
  pool, and `parity` and `sweep` gain `--jobs`.
- **#245:** a `references.toml` row pins its archive by `all_sha256`, and `resolve_all` resolves
  by that pin for both `parity` and `capture-ref`.

#246 is a human checklist at the end.

**Tech Stack:** Rust (wgpu 30, `stunt-render`), Python 3.15 (`uv` through `mise`, pytest),
`concurrent.futures`.

**Spec:** [`vault-parity-films-2026-11-06.md`](vault-parity-films-2026-11-06.md). Executors read
both; the plan cites the spec's decisions as D1 to D9.

## Global Constraints

- **Gates and commits:**
  - Run `mise run check-rust` or `mise run check-py` while iterating, and `mise run check` once
    before each commit. It must pass with zero warnings.
  - Stage files by name; never `git add -A`, never anything under `corpus/`.
  - Commits use a Conventional subject and a body that says why. The body closes with
    `mise run check passes.`, then `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
  - Each PR body ends with `🤖 Generated with [Claude Code](https://claude.com/claude-code)`.
- **Branches:** each task group is one PR on its own branch. Cut it from `main` once the spec PR
  (this branch, `claude/vault-films-rendering-parity-df9bab`) has merged, else from this branch's
  head. The three groups touch disjoint files except `research/parity/method.md` (groups A and B):
  whichever lands second rebases.
- **Tests:** offline only. Nothing under `tests/` reads `corpus/`, starts DOSBox or needs a GPU.
  Use `tmp_path` data roots (`tests/render_helpers.py` `reference_tree`, `pin_reference`) and the
  `FakeRun` adapter in `tests/test_parity_pipeline.py`.
- **Paths:** the literals `build/parity` and `build/scratch` appear only in
  `python/stunt_reel/parity_layout.py`.
- **Python style:** keep `__all__` lists sorted, and pass `encoding="utf-8"` on every text read and
  write. Generics use PEP 695 syntax (`def f[V](...)`); the floor is Python 3.15.
- **Live checks:**
  - `mise run parity` must print `ctry  ssim 0.8725 … iou 0.9897` and `intro ssim 0.8273 … iou
    0.9856` after every group. Any change is a regression; stop and report.
  - No group changes rendered output, so no PR carries a capture-beside-render picture; each PR
    says so.
- **Findings:** a measured figure that lands in `research/parity/method.md` comes with the commit
  that relies on it (AGENTS.md directive 4). `research/` never links into `docs/process/` (the
  doc-invariant test refuses it).

## Review Focus

1. **Interrupt during a sweep:** Ctrl+C mid-matrix leaves no variant work directories behind,
   apart from a `--keep-best` winner already chosen. Test in Task 4.
2. **One film's reference missing on this machine:** that film fails in every variant, the others
   still score, and the exit code is non-zero, as today. Test in Task 2.
3. **`--jobs` above the pair count, or `--jobs 1`:** the pool never exceeds the number of pairs,
   and `--jobs 1` runs on the calling thread with no executor. Test in Task 3.
4. **A pin that the film's own sibling `.ALL` already satisfies:** it resolves without scanning the
   corpus. A stored archive whose bytes no longer match its `meta.json` is still an error, not a
   reason to try the next candidate. Test in Task 7.
5. **The windowed renderer:** it still creates an all-backends instance; D8 is offscreen only.
   Test in Task 1.

---

## Group A — #243, Vulkan-first offscreen instance (D8)

### Task 1: Try Vulkan before all backends on the offscreen path

**Files:**
- Modify: `crates/stunt-render/src/renderer.rs`:
  - `offscreen_adapter` (≈ line 1001)
  - `create_instance` (≈ line 1062)
  - every caller of `create_instance`
  - `mod tests` (≈ line 1142)
- Modify: `research/parity/method.md` (§ 3, start-up figures)

**Interfaces:**
- Produces:
  - `fn create_instance(backends: wgpu::Backends) -> wgpu::Instance`
  - `const OFFSCREEN_BACKENDS: [wgpu::Backends; 2] = [wgpu::Backends::VULKAN, wgpu::Backends::all()]`
  - `fn first_adapter<A>(attempts: &[wgpu::Backends], preferred: impl Fn(&A) -> bool, request: impl FnMut(wgpu::Backends) -> Option<A>) -> Option<A>`
  - `fn preferred_adapter(adapter: &wgpu::Adapter, options: RenderOptions) -> bool`

- [ ] **Step 1: Write the failing tests** in `renderer.rs` `mod tests`:

```rust
#[test]
fn first_adapter_stops_at_the_first_backend_that_finds_one() {
    let mut tried = Vec::new();
    let got = first_adapter(&OFFSCREEN_BACKENDS, |_| true, |b| { tried.push(b); Some(b) });
    assert_eq!(got, Some(wgpu::Backends::VULKAN));
    assert_eq!(tried, vec![wgpu::Backends::VULKAN]);
}

#[test]
fn first_adapter_falls_back_to_all_backends() {
    let mut tried = Vec::new();
    let got = first_adapter(&OFFSCREEN_BACKENDS, |_| true, |b| {
        tried.push(b);
        (b == wgpu::Backends::all()).then_some(b)
    });
    assert_eq!(got, Some(wgpu::Backends::all()));
    assert_eq!(tried, vec![wgpu::Backends::VULKAN, wgpu::Backends::all()]);
}

#[test]
fn first_adapter_is_none_when_no_backend_finds_one() {
    assert_eq!(first_adapter(&OFFSCREEN_BACKENDS, |_| true, |_| None::<u8>), None);
}

/// A fake adapter: the backends that found it, and whether it is hardware.
type Fake = (wgpu::Backends, bool);

#[test]
fn first_adapter_passes_over_a_software_vulkan_adapter_for_hardware() {
    let got = first_adapter(&OFFSCREEN_BACKENDS, |&(_, hw): &Fake| hw, |b| {
        Some((b, b == wgpu::Backends::all()))
    });
    assert_eq!(got, Some((wgpu::Backends::all(), true)));
}

#[test]
fn first_adapter_keeps_the_first_software_adapter_when_no_backend_has_hardware() {
    let got = first_adapter(&OFFSCREEN_BACKENDS, |&(_, hw): &Fake| hw, |b| Some((b, false)));
    assert_eq!(got, Some((wgpu::Backends::VULKAN, false)));
}
```

- [ ] **Step 2: Run `mise run test-rust`.** Expected: the five tests fail to compile
  (`first_adapter` and `OFFSCREEN_BACKENDS` are not defined).

- [ ] **Step 3: Implement.**
  - `first_adapter`: the first `Some` over `attempts` that `preferred` accepts, else the first
    `Some` at all. Offscreen prefers any adapter but a CPU one (a software Vulkan driver must
    not hide DX12's GPU); `software_only` prefers any.
  - `create_instance`: takes its `backends`.
  - `offscreen_adapter`'s `get_or_init` closure: becomes
    `first_adapter(&OFFSCREEN_BACKENDS, |a| preferred_adapter(a, options), |b| select_adapter(&create_instance(b), None, options))`.
    `select_adapter` already runs the low-power fallback inside each instance.
  - Every other caller of `create_instance` (the windowed `acquire` path) passes
    `wgpu::Backends::all()`, which fixes Review Focus 5.
  - Rewrite the `offscreen_adapter` doc comment with the spec § 3.2 figures: about 0.95 s for the
    Vulkan loader, 0.95 s more enumerating DX12, and about 1 s saved by trying Vulkan first.

- [ ] **Step 4: Run `mise run check-rust`.** Expected: pass, including the GPU tests (locally;
  CI runs them on lavapipe).

- [ ] **Step 5: Live check.**
  - Run `mise run parity`. Expected: the two score lines in Global Constraints.
  - Time a one-tick headless CTRY render against a build of the parent commit, made with
    `mise run build-at -- HEAD~1 build/scratch/before`. Expected: about 1 s faster.
  - Add one bullet to `research/parity/method.md` § 3, tier `[Bounded Observation]`: start-up
    phases and the measured saving, with the commit hash.

- [ ] **Step 6: Commit** `perf(render): try a Vulkan-only instance before all backends offscreen`.
  The body cites the spec's § 3.2 measurement and says why GL was rejected (it picks the
  integrated GPU). Open the PR with `Fixes #243`.

---

## Group B — #244, parallel parity (D6, D7)

### Task 2: `run_matrix` in `parity_pipeline`

**Files:**
- Modify: `python/stunt_reel/parity_pipeline.py` (`run_film` ≈ 492, `run_films` ≈ 507, `__all__`)
- Test: `tests/test_parity_pipeline.py`

**Interfaces:**
- Consumes:
  - `reference_job(root, name)`
  - `run_film(job, workdir, *, env, retime, run)`
  - `score_film(...)`
  - `FilmScore`, `FilmFailure`
- Produces:

```python
type Attempt = FilmScore | FilmFailure
def run_matrix[V](
    films: Sequence[str], root: Path, variants: Sequence[V],
    work: Callable[[FilmJob, V], FilmScore], *, jobs: int = 1,
    on_variant: Callable[[int, list[Attempt]], None] | None = None,
) -> list[list[Attempt]]
```

  `run_films` keeps its signature and becomes `run_matrix` over one variant, with `jobs=1`.

- [ ] **Step 1: Write the failing tests.** Each uses `reference_tree(tmp_path, …)` and a `work`
  fake that returns a `FilmScore` built from `(job.name, variant)`:
  - `test_run_matrix_returns_results_in_input_order`: 3 variants × 2 films, `jobs=4`, `work`
    sleeping `random.uniform(0, 0.02)`. Assert `[[r.film for r in row] for row in out] ==
    [["ctry", "intro"]] * 3`, and that each result carries its own variant.
  - `test_run_matrix_jobs_one_and_four_agree`: same fake, deterministic; `jobs=1` and `jobs=4`
    give equal lists.
  - `test_run_matrix_isolates_a_failing_pair`: `work` raises `RuntimeError` for
    `("intro", variant 1)`. Assert exactly that cell is a `FilmFailure` and the other five are
    `FilmScore`.
  - `test_run_matrix_fails_a_film_without_a_reference_in_every_variant`: `films=["ctry", "nope"]`.
    Every row's second cell is a `FilmFailure`, and `work` is never called for it (Review Focus 2).
  - `test_run_matrix_opens_each_reference_once`: monkeypatch `parity_pipeline.reference_job` with
    a counting wrapper. With 4 variants, the count is 2.
  - `test_run_matrix_calls_on_variant_on_the_calling_thread`: record
    `threading.get_ident()` and the index in the callback. Each index is seen once, and every
    ident is the test's.
  - `test_run_matrix_cancels_pending_pairs_on_interrupt`: 6 variants × 2 films, `jobs=2`, and
    `on_variant` raising `KeyboardInterrupt` on the first row it sees. Assert
    `KeyboardInterrupt` propagates and `work` ran for fewer than 12 pairs.
  - Keep the existing `run_films` tests unchanged; they must still pass.

- [ ] **Step 2: Run `mise run test-py -- tests/test_parity_pipeline.py`.** Expected: the new tests
  fail (`run_matrix` missing).

- [ ] **Step 3: Implement `run_matrix`.**
  - Enter every film's `reference_job` in one `ExitStack` on the calling thread. A film whose
    `reference_job` raises becomes `FilmFailure(film, error)` in every row.
  - `jobs <= 1`: run on the calling thread, calling `on_variant` after each row.
  - Otherwise, submit every pair to a `ThreadPoolExecutor(max_workers=min(jobs, pairs))`.
  - Loop on `concurrent.futures.wait(pending, timeout=0.5, return_when=FIRST_COMPLETED)`, filling
    cells and calling `on_variant(index, row)` when a row completes.
  - On `KeyboardInterrupt` (or any exception from `on_variant`), call
    `pool.shutdown(wait=True, cancel_futures=True)` and re-raise.
  - Catch the same exception types as today's `run_films` in each pair:
    `(RuntimeError, ValueError, OSError, KeyError)`.
  - Rewrite `run_films` as a one-variant `run_matrix` whose `work` calls `run_film`, or
    `score_film` when `render=False`, with today's paths.

- [ ] **Step 4: Run `mise run test-py -- tests/test_parity_pipeline.py`, then `mise run lint-py`
  and `mise run typecheck`.** Expected: pass.

- [ ] **Step 5: Commit** `feat(parity): run film and variant pairs through one pool`.

### Task 3: `--jobs` and `parity_run` on `run_matrix`

**Files:**
- Modify: `python/scripts/cli.py` (`ParityOptions`, `add_parity_options`, `parity_options`)
- Modify: `python/scripts/parity_run.py` (`main`, ≈ lines 90–130)
- Test: `tests/test_parity_cli.py`

**Interfaces:**
- Consumes: `run_matrix` (Task 2).
- Produces:
  - `ParityOptions.jobs: int | None`, where `None` means use the default.
  - `def resolve_jobs(requested: int | None, pairs: int) -> int` in `cli.py`. It returns
    `min(requested or min(8, os.cpu_count() or 1), pairs)`, never below 1.

- [ ] **Step 1: Write the failing tests.**
  - `test_jobs_defaults_to_eight_capped_by_cores_and_pairs`: monkeypatch `os.cpu_count` to 16
    and expect `resolve_jobs(None, 24) == 8` and `resolve_jobs(None, 2) == 2`; with `cpu_count`
    `None`, expect `resolve_jobs(None, 24) == 1`.
  - `test_jobs_zero_is_a_usage_error`: `--jobs 0` and `--jobs -1` exit with argparse's usage
    error.
  - `test_jobs_above_pairs_is_clamped`: `resolve_jobs(32, 3) == 3` (Review Focus 3).
  - `test_parity_run_rotates_trees_the_same_at_any_jobs`: drive `parity_run.main` twice on a
    `reference_tree`, at `--jobs 1` and at `--jobs 2`, with `--no-build`. Monkeypatch
    `parity_run.render_film` (a fake that writes a render with `_write_render`),
    `parity_run.score_film` (a fake returning a `FilmScore`) and `parity_pipeline.REPO_ROOT`, as
    `tests/test_parity_frame.py` and `tests/test_parity_pipeline.py` already do. Each film's
    `_current` and `_previous` trees exist after the second run, and the stdout summary lines come
    in film order both times.

- [ ] **Step 2: Run `mise run test-py -- tests/test_parity_cli.py`.** Expected: fail.

- [ ] **Step 3: Implement.**
  - Add `--jobs` to `add_parity_options`, typed by a positive-int parser.
  - Add `resolve_jobs`.
  - In `parity_run.main`, call
    `run_matrix(options.films, root, (None,), work, jobs=resolve_jobs(options.jobs, len(films)))`.
    `work(job, _)` is today's loop body: `prepare_source`, then `score_film` with the retime
    request.
  - After `run_matrix` returns, print `format_summary` lines and failures in film order.

- [ ] **Step 4: Run `mise run test-py -- tests/test_parity_cli.py tests/test_parity_pipeline.py`.**
  Expected: pass.

- [ ] **Step 5: Commit** `feat(parity): add --jobs to mise run parity`.

### Task 4: `parity_sweep` on `run_matrix`

**Files:**
- Modify: `python/scripts/parity_sweep.py` (main loop ≈ 300–345, `run_reuse` ≈ 251)
- Test: `tests/test_parity_sweep.py`

**Interfaces:**
- Consumes: `run_matrix`, `run_film`, `resolve_jobs`, `rank`, `Variant`.
- Produces: no new public names. Inside the script, a variant is `(Variant, workdir, env)`.

- [ ] **Step 1: Write the failing tests**, with `FakeRun` or a `work` fake patched in:
  - `test_sweep_keeps_the_same_best_at_any_jobs`: two variants tie on SSIM and IoU. With
    `--keep-best`, the kept directory is `v001` at `--jobs 1` and at `--jobs 4`.
  - `test_sweep_prints_the_table_in_variant_order_at_any_jobs`: stdout is identical at
    `--jobs 1` and `--jobs 4`.
  - `test_sweep_interrupt_leaves_no_work_directories`: the fake raises `KeyboardInterrupt` in the
    second variant's callback. Afterwards `parity_layout.sweep_root()` holds no `v*` directory
    except an already-chosen best (Review Focus 1).

- [ ] **Step 2: Run `mise run test-py -- tests/test_parity_sweep.py`.** Expected: fail.

- [ ] **Step 3: Implement.**
  - Build the variant list up front: index, values, a fresh `workdir` and `env` for each.
  - Call `run_matrix(films, root, variants, work, jobs=resolve_jobs(options.jobs,
    len(variants) * len(films)), on_variant=…)`, where `work` calls `run_film(job, workdir,
    env=env, retime=options.retime)`.
  - The callback holds today's per-variant body:
    - notes and the `iou` probe;
    - `--keep-best`: compare with the current best through `rank([best, v])`, and delete the
      loser's directory;
    - the `[i/n]` progress line, timed from the start of the matrix.
  - Keep the `finally` that deletes every non-best `v*` directory.
  - Move `run_reuse` onto `run_films(..., render=False)`, unchanged in behaviour.

- [ ] **Step 4: Run `mise run test-py -- tests/test_parity_sweep.py`.** Expected: pass.

- [ ] **Step 5: Commit** `feat(parity): run sweep variants in parallel with --jobs`.

### Task 5: Docs, skill and live check for group B

**Files:**
- Modify: `.agents/skills/improving-render-parity/SKILL.md`:
  - Goal contract, Adoption rule, Workflow step 1, Cost rules 3 and 4
- Modify: `research/parity/probes.md` § 4
- Modify: `mise.toml`: `[tasks.sweep]` and `[tasks.parity]` descriptions
- Modify: `research/parity/method.md` § 3

- [ ] **Step 1: Skill.**
  - Replace the Adoption rule's two bullets with D2's wording verbatim from the spec.
  - "Score both films" becomes "Score every film".
  - Workflow step 1 reads "(one line per film)".
  - Cost rule 3 adds `--jobs N` (default 8; about 200 MiB of VRAM and 300 MiB of RAM per job, or
    180 MiB once #243 has landed).
  - Read `writing-for-agents` before editing the skill.
- [ ] **Step 2: `probes.md` and `mise.toml`.** Remove "CTRY and INTRO" and "both films" from the
  `sweep` and `parity` descriptions, and add `[--jobs N]` to both usage strings.
- [ ] **Step 3: `method.md` § 3.** Add the throughput table from spec § 3.1 as a
  `[Bounded Observation]` bullet with the commit hash.
- [ ] **Step 4: Live check.**
  - `mise run parity -- --jobs 1` and `mise run parity -- --jobs 8` must print identical score
    lines (Global Constraints values).
  - `mise run sweep -- --var DBG_NONE=0,1 --jobs 4` must print a table and a winner without error.
    `DBG_NONE` is unread, so expect the identical-variant warning.
- [ ] **Step 5: Run `mise run check`, commit** `docs(parity): describe parity for every film and
  --jobs`, and open the PR with `Fixes #244`.

---

## Group C — #245, archive pinning (D9)

### Task 6: A row pins its archive

**Files:**
- Modify: `python/stunt_reel/references.py`:
  - `Reference` (≈ 78)
  - `read_reference` (≈ 150)
  - a new `read_pin`
- Modify: `python/scripts/capture_digest.py` `report` (≈ 79), so the entry it prints carries
  `all_sha256`
- Test: `tests/test_references.py`, plus the digest test that covers `report`

**Interfaces:**
- Produces:
  - `Reference.all_sha256: str | None = None`, read from the row and validated as 64 hex
    characters when present.
  - `def read_pin(root: Path, slug: str) -> str | None`: the `all_sha256` of the row whose
    `film == slug`, else `None`.
  - `report(..., all_sha256: str | None = None)` prints `all_sha256 = "<hash>"` after `sha256`
    when given.

- [ ] **Step 1: Write the failing tests:**
  - `test_reference_reads_all_sha256`
  - `test_reference_without_all_sha256_is_none`
  - `test_reference_refuses_a_malformed_all_sha256`: `"abc"` raises `ReferenceCaptureError`
    naming the row.
  - `test_read_pin_finds_the_row_by_slug`
  - `test_digest_report_prints_the_archive_pin`
- [ ] **Step 2: Run them.** Expected: fail.
- [ ] **Step 3: Implement.** `capture_digest.main` passes the capture's `meta.json` `all_sha256`
  to `report`.
- [ ] **Step 4: Run `mise run test-py -- tests/test_references.py`** and the digest test file.
  Expected: pass.
- [ ] **Step 5: Commit** `feat(references): let a row pin its archive by all_sha256`.

### Task 7: `resolve_all` resolves by the pin

**Files:**
- Modify: `python/stunt_reel/all_archive.py` (`resolve_all` ≈ 201, `_from_manifest` ≈ 153)
- Test: `tests/test_all_archive.py`

**Interfaces:**
- Consumes: `file_sha256`, `_from_manifest`, the stored-archive branch.
- Produces: `resolve_all(flm, root, slug=None, *, link_build=None, pinned: str | None = None) ->
  Path`. With `pinned=None`, behaviour is unchanged.

- [ ] **Step 1: Write the failing tests.** Each uses a `tmp_path` corpus with two copies of one
  `.FLM` (`a/VAULT/X.FLM`, `b/VAULT/X.FLM`, same bytes) and different sibling `.ALL` files:
  - `test_pin_matching_the_sibling_returns_it_without_scanning`: monkeypatch `Path.rglob` to
    fail if called (Review Focus 4).
  - `test_pin_finds_the_other_copys_sibling`: resolving `a/…/X.FLM` with `b`'s hash returns
    `b/VAULT/X.ALL`.
  - `test_pin_names_a_manifest_rebuild`: use `no_link` plus a pre-built
    `target/linked/<slug>/X.ALL` with the manifest's `all_sha256`.
  - `test_pin_names_a_stored_archive`
  - `test_pin_matching_nothing_is_refused`: `ArchiveError` whose message contains the full pinned
    hash.
  - `test_stored_archive_that_drifted_is_an_error_not_skipped`: the stored archive's bytes no
    longer match its `meta.json`, and the pin equals the recorded hash. Expect `ArchiveError`
    (Review Focus 4).
  - `test_no_pin_resolves_as_before`: the existing tests pass unchanged.
- [ ] **Step 2: Run `mise run test-py -- tests/test_all_archive.py`.** Expected: fail.
- [ ] **Step 3: Implement.** With `pinned` set, return the first candidate whose bytes hash to
  `pinned`, in this order:
  1. the film's sibling `.ALL`;
  2. the manifest rebuild, if its `all_sha256 == pinned`;
  3. the stored archive (its existing integrity check runs first);
  4. any `.ALL` under `dataroot.corpus_of(root)` whose stem matches the film's (case-insensitive)
     and whose sibling `.FLM` has the film's `file_sha256`.

  If none matches, raise
  `ArchiveError(f"no archive of {flm.name} hashes to the pinned all_sha256 {pinned}")`.

  A pinned sibling outside `target/linked/` must keep its `MAKEONE` provenance: when the
  manifest rebuild is byte-identical to a `siarchive` sibling, the sibling wins, and
  `references.archive_makeone_build`, which judged by path, would call it `unknown` and
  `require_builds` would refuse the capture. So `archive_makeone_build` also takes the
  manifest's `makeone_sha256` for any archive whose SHA-256 is the manifest's `all_sha256`
  (`test_an_archive_with_the_manifests_bytes_takes_its_build_from_the_manifest`).
- [ ] **Step 4: Run the tests.** Expected: pass.
- [ ] **Step 5: Commit** `feat(archive): resolve a film's archive by its pinned hash`.

### Task 8: Wire the pin through parity and capture, pin CTRY and INTRO, ADR

**Files:**
- Modify: `python/stunt_reel/parity_pipeline.py` `reference_job` (≈ 111) and `render_film`
  (≈ 388)
- Modify: `python/stunt_reel/capture_run.py` (`resolve_all` call ≈ 333)
- Modify: `research/parity/references.toml` (`[ctry]`, `[intro]`)
- Create: `docs/adr/0037-a-reference-pins-its-archive.md`
- Modify: `research/parity/method.md` § 3 (the archive bullet: mark the gap closed)
- Test: `tests/test_parity_pipeline.py`, `tests/test_capture_run.py`

**Interfaces:**
- Consumes: `Reference.all_sha256`, `read_pin` (Task 6), and `resolve_all(..., pinned=)`
  (Task 7).
- Produces: `FilmJob.all_sha256: str | None = None`, set by `reference_job` from the row.
  `render_film` passes it to `resolve_all` as `pinned`.

- [ ] **Step 1: Write the failing tests:**
  - `test_reference_job_refuses_a_capture_recorded_with_another_archive`: the row pins `H1` and
    the capture's `meta.json` records `H2`. Expect `ReferenceCaptureError` naming both prefixes.
  - `test_render_film_plays_the_pinned_archive`: two copies with different `.ALL` files. The
    `--all` argument in `FakeRun.calls` is the pinned one.
  - `test_capture_run_resolves_the_rows_pin`: through the `launch` seam with `MockAutomation`,
    the staged archive is the pinned one.
- [ ] **Step 2: Run them.** Expected: fail.
- [ ] **Step 3: Implement.**
  - `reference_job` reads `pointer.all_sha256`. When it is set and the snapshot's
    `read_capture(...).film.all_sha256` differs, it raises. It stores the pin on the `FilmJob`.
  - `capture_run` calls `resolve_all(film, REPO_ROOT, slug, pinned=references.read_pin(REPO_ROOT,
    slug))`.
- [ ] **Step 4: Pin the references.** Add to `[ctry]`
  `all_sha256 = "9de1bc1e8dbe491a56edd899b7c333cb78e5251cbe1e4ed75610dbc081aeb9a9"`, and to
  `[intro]` `all_sha256 = "27935a3638950d4ec75fc1f84f4ac15aa7308f0975b2a9d2e0c5f8a0c843035d"`.
- [ ] **Step 5: ADR 0037.**
  - Status: accepted. It amends ADR 0029.
  - Context: the 2026-11-06 finding in `method.md` § 3.
  - Decision: a row pins `all_sha256`, and `parity` and `capture-ref` resolve by it.
  - Considered options: pin the `.FLM` path (rejected, because copies move); pin nothing and
    compare after the fact (rejected, because it lets the capture build check refuse `siarchive`
    archives).
  - Consequences: new references use a committed manifest (ADR 0032).
- [ ] **Step 6: Live check.** `mise run parity` prints the Global Constraints values. That is the
  proof that the demo archives render identically, as the spec measured.
- [ ] **Step 7: Run `mise run check`, commit** `feat(parity): play each reference's pinned
  archive`, and open the PR with `Fixes #245`.

---

## Group D — #246, phase-1 references (human, DOSBox and `MAKEONE`)

Not agent tasks: they need the emulator and the game builds on the owner's machine. Do these
after #245 merges, one film at a time (`SPLANES` first), as in spec § 4.1:

- [ ] `mise run make-all -- --film corpus/siarchive/Films/NewPLAY/Vault/SPLANES.FLM` on the
  unpatched `MAKEONE`. Check that `manifests/all/vault-splanes.toml` was written. If `MAKEONE`
  hangs twice, retry with the `patch3` build; if that fails too, swap in `BALLOON.FLM`.
- [ ] Add `[splanes]` to `references.toml`: `film = "vault-splanes"`, the manifest's
  `all_sha256`, `makeone = "unpatched"`, `playone = "unpatched"`, and `reason`.
- [ ] `mise run capture-ref -- --film corpus/siarchive/Films/NewPLAY/Vault/SPLANES.FLM`, then the
  skill's "Comparing a candidate reference" procedure. `capture-digest` now prints
  `all_sha256`, which must equal the row's.
- [ ] `mise run parity` prints three lines. Add the `log.md` baseline row, run the error readout,
  and commit the manifest, the row and the log row together.
- [ ] Repeat for `LAND.FLM` (`corpus/siarchive/Films/OldPLAY/Vault/LAND.FLM`, row `[land]`).
  Close #246 and #242.
