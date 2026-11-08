# Expected Parity Scores Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `mise run parity` prints each film's score beside a committed expected score for the renderer class it rendered on, and flags drift only when the comparison is valid.

**Architecture:** The renderer reports the adapter it drew on; the render journal writes it into `render.json` and `stuntreel parity` copies it into `report.json` (both optional fields, ADR 0011). `references.toml` gains `[<film>.expected.<class>]` tables, parsed by `references.py`. A new `python/stunt_reel/expected_scores.py` turns a report, a reference row and a git check into one comparison line, which `parity_run.py` prints under each film's summary line.

**Tech Stack:** Rust (wgpu 30, serde), Python 3.14 standard library (`tomllib`, `subprocess`), git.

**Spec:** issue #307 spec § 4.4 (on branch `claude/docs-reorganization-agent-85ba65`, `work/2026-11/307_docs-streamline/spec.md`).

## Global Constraints

* `mise run check` passes with no warnings before every commit; the commit body ends with the gate line it prints ([commit messages](../../../docs/development.md#commit-messages)). Stage paths by name; never `git add -A`; never anything under `corpus/`.
* No new runtime or dev dependency. Python files: module docstring, `from __future__ import annotations`, library code in `python/stunt_reel/`, scripts in `python/scripts/`.
* Renderer classes are exactly `gpu` and `lavapipe`; each entry is `{ ssim, iou, commit, adapter }`: `ssim` the headline `mean_ssim_scored`, `iou` its `mean_iou_scored`, `adapter` the adapter name it was measured on.
* Drift is `|delta| > noise_sigma` on SSIM, flagged only when the adapter name matches and nothing under `crates/` and neither pin (`sha256`, `all_sha256`) of the film's row changed since `commit`. Otherwise print the delta and why it is not comparable. A class with no entry prints `no expected score for <class> yet: add it`, never drift.
* Drift is printed, not an exit status: `mise run parity` keeps exiting 0 when every film scored.
* `crates/stunt-parity` stays pure types (no filesystem, GPU or image code); `stunt-render` signatures carry no wgpu types; `stunt-render` gains no dependency on `stunt-parity`.
* PR says "Part of #307", not "Fixes". A push that changes `research/` gets a fresh-reviewer read first (AGENTS.md working rule 7).

## Decisions this plan makes

* **No schema bump.** ADR 0011 bumps a version only when a field becomes required. `adapter` is optional in both documents, so `render.json` stays version 3 and old renders and reports (a `_previous` tree, `--reuse`) still score; they print "not comparable" instead. The writer always records it.
* **Report class to key:** the report says `hardware` or `cpu` (what `preferred_adapter` distinguishes); `gpu` is the key for `hardware` and `lavapipe` for `cpu`. A CPU adapter that is not lavapipe (WARP) falls under `lavapipe` and is then refused as another adapter by name.
* **"No reference pin changed"** reads the pins of the scored film's own row: another film's pins cannot move this film's score.
* **A film without `noise_sigma`** (INTRO today) prints its delta and `drift not judged: <film> has no noise_sigma`.
* **Seed `commit`:** see Task 5.

## Review Focus

1. **A report without `adapter`** (rendered before this change, or a `--reuse` of an old tree) prints `no adapter in the report: re-render to compare`, not a traceback. Test in Task 4.
2. **An expected `commit` this clone lacks** (a shallow cloud clone, a squash-merged branch commit) or a failing `git` prints `not comparable: commit <short> is not in this clone`. Test in Task 4.
3. **Uncommitted or untracked files under `crates/`** count as changed, so a local experiment reads "not comparable", never drift. Test in Task 4.
4. **A report with no scored frame** (`mean_ssim_scored` null) prints `not comparable: no frame scored`; the all-frames mean is never compared with a scored expectation. Test in Task 4.
5. **`--retime` and `--reuse`** score something other than this checkout's render: `not comparable: scored with --retime` / `--reuse`. Test in Task 4.

---

### Task 1: The adapter in `render.json` and `report.json` (Rust)

**Files:**
- Modify: `crates/stunt-parity/src/render.rs`, `report.rs`, `lib.rs`
- Modify: `crates/stunt-render/src/renderer.rs` (and its `lib.rs` re-exports)
- Modify: `crates/stunt-cli/src/parity_artifacts.rs` (`RenderJournal`), `headless.rs`, `parity/mod.rs` (`build_report`), every other `RenderRecord {`/`Report {` literal the compiler names
- Modify: `research/parity/method.md` § 1.3 `report.json` table; § 1 step 3 or § 2.1 where `render.json` fields are described

**Interfaces:**
- Produces (stunt-parity): `#[serde(rename_all = "lowercase")] pub enum AdapterClass { Hardware, Cpu }`; `pub struct RenderAdapter { pub name: String, pub class: AdapterClass }`, both re-exported from `lib.rs`. `RenderRecord.adapter: Option<RenderAdapter>` (`serde(default, skip_serializing_if = "Option::is_none")`); `Report.adapter: Option<RenderAdapter>` (`serde(default)`, written as `null` when unknown, like the report's other optional values).
- Produces (stunt-render): `pub struct AdapterIdentity { pub name: String, pub is_cpu: bool }` and `Renderer::adapter(&self) -> &AdapterIdentity`, filled from `adapter.get_info()` by both `offscreen` and `surface`. `preferred_adapter` and the identity share one predicate, `device_type == wgpu::DeviceType::Cpu`.
- Produces (stunt-cli): `RenderJournal::finish(self, adapter: RenderAdapter)`; `build_report(.., adapter: Option<RenderAdapter>)` copies `RenderStore::record().adapter`.

- [ ] **Step 1: Failing tests.** In `render.rs`: `a_render_without_an_adapter_parses` (a version-3 document with no `adapter` key deserializes with `adapter == None` and validates) and `the_adapter_round_trips` (`{"name": "llvmpipe (LLVM 19.1.7, 256 bits)", "class": "cpu"}` survives serialize/deserialize; JSON `class` is `"cpu"`). In `report.rs`: extend `old_reports_without_optional_fields_parse` to assert `report.adapter == None`. In `parity_artifacts.rs`: a journal finished with `RenderAdapter { name: "Test GPU", class: Hardware }` writes `"adapter": {"name": "Test GPU", "class": "hardware"}` into `render.json`. In `parity/tests.rs`: a scored render whose record carries an adapter yields a report with the same adapter, and one without yields `"adapter": null`.
- [ ] **Step 2: Run** `mise run check-rust`. Expected: the new tests fail to compile or fail.
- [ ] **Step 3: Implement** the interfaces above. `headless.rs` hands `renderer.adapter()` to the journal (mapped to `RenderAdapter`, `is_cpu` to `Cpu`) when it finishes it. `lib.rs` doc: the adapter is optional, so no version moved. Add the `adapter` row to the `report.json` fields table (`object or null, optional`: the adapter the render was drawn on, `name` as the driver reports it and `class` `hardware` or `cpu`, from `render.json`; absent in older reports) and one sentence where `method.md` describes `render.json` fields.
- [ ] **Step 4: Run** `mise run check-rust`. Expected: pass, including `report_doc.rs`'s `method_md_documents_every_key_of_report_json_and_compare_json`.
- [ ] **Step 5: Commit** `feat(parity): record the adapter a render was drawn on`.

### Task 2: The adapter in the Python artifact adapter

**Files:**
- Modify: `python/stunt_reel/parity_artifacts/render.py`, `report.py`, `__init__.py` (exports)
- Modify: `tests/fixtures/parity/v3/render/render.json`, `tests/fixtures/parity/v1/report.json` (add an `adapter`)
- Test: `tests/test_parity_artifacts_render.py`, `test_parity_artifacts_report.py`, `test_parity_artifacts_round_trip.py`

**Interfaces:**
- Consumes: the JSON shape of Task 1.
- Produces: `RenderAdapter(name: str, adapter_class: Literal["hardware", "cpu"])` (frozen dataclass; JSON key `class`); `RenderRecord.adapter: RenderAdapter | None = None`; `Report.adapter: RenderAdapter | None = None`. Readers accept an absent key or `null`; writers emit what Rust emits (render: key omitted when `None`; report: `null`).

- [ ] **Step 1: Failing tests.** `test_a_report_records_its_adapter` (the v1 fixture reads `RenderAdapter("Test GPU", "hardware")`); `test_a_report_without_an_adapter_reads_none`; `test_an_unknown_adapter_class_is_refused` (`"class": "quantum"` raises `ArtifactError` naming `adapter.class`); the same two for `render.json`. The round-trip test keeps passing with the fixtures' new `adapter`.
- [ ] **Step 2: Run** `mise run test-py -- tests/test_parity_artifacts_render.py tests/test_parity_artifacts_report.py tests/test_parity_artifacts_round_trip.py`. Expected: FAIL.
- [ ] **Step 3: Implement** with the module's existing `_as_object`/`_wrong_type` helpers. Update both fixtures; the Rust fixture tests in `parity_artifacts.rs` read the same files, so assert the adapter there too.
- [ ] **Step 4: Run** the same tests and `mise run check-rust`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(parity): read the render's adapter in the Python artifact adapter`.

### Task 3: Expected scores in `references.toml`

**Files:**
- Modify: `python/stunt_reel/references.py`
- Test: `tests/test_references.py`

**Interfaces:**
- Produces: `RENDERER_CLASSES: tuple[str, ...] = ("gpu", "lavapipe")`; `@dataclass(frozen=True) class Expected: ssim: float; iou: float; commit: str; adapter: str`; `Reference.expected: Mapping[str, Expected]` (read-only, empty when the row has none) and `Reference.noise_sigma: float | None`, both read by `read_reference`.

- [ ] **Step 1: Failing tests.** `test_a_row_reads_its_expected_scores_and_noise_sigma`: a row with `[ctry.expected.gpu] ssim = 0.8725, iou = 0.9897, commit = "740c608", adapter = "NVIDIA GeForce RTX 4070"` and `noise_sigma = 0.000303` reads back exactly, with no `lavapipe` key. `test_a_row_without_expected_scores_reads_empty`. `test_a_malformed_expected_entry_is_named`, parametrized: an unknown class `warp`; `ssim` missing, a string, or `1.5`; `iou` below 0; `commit = "xyz"` (not 7 to 40 lowercase hex); `adapter = ""`; `noise_sigma = 0` or `-1`. Each raises `ReferenceCaptureError` whose message names the file, `[ctry]` and the field. `test_the_committed_rows_name_valid_builds` also reads every committed row's expected scores.
- [ ] **Step 2: Run** `mise run test-py -- tests/test_references.py`. Expected: FAIL.
- [ ] **Step 3: Implement** in `read_reference`, with a helper per table like `_builds` and `_pin`. Add a comment block above `[ctry]` in `references.toml` saying what `[<film>.expected.<class>]` holds and that an adopting PR updates the line for the class it measured.
- [ ] **Step 4: Run** the same tests. Expected: PASS.
- [ ] **Step 5: Commit** `feat(parity): read expected scores per renderer class from references.toml`.

### Task 4: The comparison in `mise run parity`

**Files:**
- Create: `python/stunt_reel/expected_scores.py`
- Modify: `python/scripts/parity_run.py`, `docs/ARCHITECTURE.md` (row of `parity_pipeline.py`: add `expected_scores.py`)
- Test: `tests/test_expected_scores.py`

**Interfaces:**
- Consumes: `Reference`, `Expected`, `RENDERER_CLASSES` (Task 3); `Report.adapter`, `RenderAdapter` (Task 2).
- Produces:
  - `CLASS_KEYS: Mapping[str, str] = {"hardware": "gpu", "cpu": "lavapipe"}`
  - `changed_since(commit: str, reference: Reference, *, repo: Path = REPO_ROOT) -> str | None`: `None` when nothing under `crates/` (tracked changes against the working tree, or untracked files) and neither pin of the reference's row changed since `commit`; else the reason: `commit <short> is not in this clone`, `crates/ changed since <short>`, `reference pin changed since <short>`. Pins at `commit` come from `git show <commit>:research/parity/references.toml`. Never raises for a git failure.
  - `comparison_line(reference: Reference, report: Report, *, rescored: str | None = None, changed: Callable[[str, Reference], str | None] = changed_since) -> str`: one line, indented six spaces. `rescored` is `"--retime"` or `"--reuse"` when the run scored such a tree.

Line forms, in the order checked (`<s>` the 6-decimal expected SSIM, `<i>` IoU, `<d>` signed 6-decimal SSIM delta, `<short>` the first 7 characters of `commit`):

```
      no adapter in the report: re-render to compare
      no expected score for <class> yet: add it
      <class> expected ssim <s>  iou <i>  delta <d>  not comparable: <reason>
      <class> expected ssim <s>  iou <i>  delta <d>  drift not judged: <film> has no noise_sigma
      <class> expected ssim <s>  iou <i>  delta <d>  DRIFT: |delta| <abs> > noise_sigma <sigma> on <adapter>
      <class> expected ssim <s>  iou <i>  delta <d>  no drift
```

`<reason>`, first that applies: `no frame scored` (the delta is then printed as `n/a`), `other adapter (expected on <adapter>)`, `scored with <rescored>`, then `changed(...)`.

- [ ] **Step 1: Failing tests** in `tests/test_expected_scores.py`, with a stub `changed` and `Report`s built in memory: each line form above, asserted as the exact string; Review Focus 1, 4 and 5; `|delta|` equal to `noise_sigma` is `no drift`. `changed_since` against a throwaway git repo in `tmp_path` (`git init`, commit `crates/a.rs` and a `references.toml`): unchanged is `None`; an edit to `crates/a.rs` without a commit, and an untracked `crates/b.rs`, are `crates/ changed since …`; a committed change to the film's `sha256` is `reference pin changed since …`, while a change to another film's pin is `None`; an unknown commit is `commit … is not in this clone` (Review Focus 2 and 3).
- [ ] **Step 2: Run** `mise run test-py -- tests/test_expected_scores.py`. Expected: FAIL (module missing).
- [ ] **Step 3: Implement** `expected_scores.py` (git through `subprocess.run(["git", "-C", repo, ...], capture_output=True, check=False)`); in `parity_run.py`, after each film's `format_summary` line, print `comparison_line(read_reference(root, film), read_report(report / "report.json"), rescored=...)` to stdout. Update the module docstring's description of stdout.
- [ ] **Step 4: Run** `mise run test-py -- tests/test_expected_scores.py` then `mise run check`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(parity): print each film's expected score and flag drift`.

### Task 5: Seed the GPU entries, document adoption, verify (controller, not a subagent)

**Files:**
- Modify: `research/parity/references.toml`, `research/parity/method.md` § 1 step 0, `.agents/skills/improving-render-parity/loop-rules.md` § Adoption rule

- [x] **Step 1: Baseline on `main`.** `mise run parity` at `740c608` (= `origin/main`), before any change, 2026-11-07: CTRY `mean_ssim_scored` 0.8986135, `mean_iou_scored` 0.9896689 (114/121 scored); INTRO 0.8336824, 0.9856165 (209/346). Reports kept in `build/scratch/main-baseline/`.
- [ ] **Step 2: Branch run.** `mise run parity` on the branch after Task 4. Expected: every score equal to Step 1 (the change draws nothing new), and each report names this machine's adapter, class `hardware`. A difference larger than `noise_sigma` stops the plan: separately built binaries would then false-alarm at that threshold (method.md § 3 reports build-to-build spread up to 0.0012), and that is a finding for `method.md` and the parent session.
- [ ] **Step 3: Seed** `[ctry.expected.gpu]` and `[intro.expected.gpu]` with the Step 1 scores at full report precision, the Step 2 adapter name, and `commit`: the full SHA of the branch commit measured in Step 2 (decided 2026-11-07: the check is live on this machine at once and keeps working after a squash merge while that commit object exists here; `740c608` would read `not comparable: crates/ changed` until the next measurement). No `lavapipe` entries.
- [ ] **Step 4: Document adoption.** One sentence each in `method.md` § 1 step 0 (what the expected line says and when it flags drift) and in `loop-rules.md` § Adoption rule: an adopting PR updates the expected line for the renderer class it measured (`ssim`, `iou`, `commit`, `adapter`); the other class keeps its older commit until someone measures it.
- [ ] **Step 5: Verify.** `mise run parity -- --no-build --no-render` prints a `gpu expected … no drift` line for both films (CTRY judged against `noise_sigma`, INTRO `drift not judged`). Then `mise run check -- --full`.
- [ ] **Step 6: Fresh review and commit.** A fresh Opus reviewer reads the `research/` diff and the notes it cites (AGENTS.md rule 7). Commit `feat(parity): seed the GPU expected scores`.
- [ ] **Step 7: PR.** Push, open against `main` with "Part of #307", bind it, and wait for green CI.
