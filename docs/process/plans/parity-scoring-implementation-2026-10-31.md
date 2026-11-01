# Parity Scoring Implementation Plan (parts 1 and 2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A numpy bench that plants render faults and measures which parity metrics see them against
recapture noise (with a Haiku judge as an experiment), and a regression verdict in `stuntreel parity
--compare` scored on the windows a render change touched.

**Architecture:** The bench is a Python package, `python/stunt_reel/bench/`, behind
`python/scripts/parity_bench.py` and `mise run parity-bench`. It reads captures and render trees as numpy
arrays, reproduces the Rust SSIM exactly, plants faults in memory and writes `bench.json`. The verdict
is a new Rust module, `crates/stunt-cli/src/parity/verdict.rs`, called from `compare.rs`. One committed
synthetic fixture with golden values pins the numpy and Rust implementations to each other.

**Tech Stack:** Python 3.15, numpy 2.5, Pillow 13 (dev group); Rust (`stunt-cli`, `stunt-render`).

**Spec:** [`parity-scoring-2026-10-31.md`](parity-scoring-2026-10-31.md). Parts 3 (sign-off scale) and 4
(fault readouts) get their own plan once part 1's result is recorded: part 3's metric choice and gate
values are decided on that result (spec § 3 and Stop conditions).

## Global Constraints

- numpy and Pillow go in `[dependency-groups] dev` of `pyproject.toml`, never `[project] dependencies`.
- Every agent-facing script has a `mise` task; the bench's is `parity-bench`.
- `mise run check` passes at the end of every task (AGENTS.md Directive 2).
- Tests run offline on synthetic fixtures; nothing from `corpus/` or the data root enters git.
- Fixtures are documented in [`tests/fixtures/README.md`](../../../tests/fixtures/README.md).
- [I6], `docs/SPEC.md` and `references.toml`'s existing keys are not changed by this plan; only an
  optional `noise_sigma` key is added.
- A research note never links into `docs/process/` (the prek doc-invariant hook refuses it).
- Commit subjects are Conventional Commits with a body that says why; end with the gate line and
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Rulings on the spec

- **Changed pixel (spec § 2).** A pixel counts as changed when its `.idx` value *or* its Rec. 601 luma
  differs between before and after; the verdict reports both fractions. A lighting change alters the
  picture only (`.idx` is the unlit index), and the spec's own flicker fault would otherwise read as
  unchanged. Luma rather than RGB, because the Rust scorer holds only the render's luma
  (`RenderFrame::luminance`); a chroma-only change is invisible to every luma metric anyway.
- **Where the verdict prints (spec § 2).** `stuntreel parity --compare ... --compare-test ...` prints it
  beside the existing `[compare]` summary. `mise run parity` does not run `--compare` today; wiring it in
  is left out of this plan.
- **Position bias (spec § 1.1).** Every pair is shown in both orders, so plain accuracy over all answers
  already cancels a fixed preference for A or B; the score also reports the share of `A` answers.

## Review Focus

1. A render tree without `.idx`/`.layer` planes (an old render): the bench stops with the message
   `stuntreel parity` gives, naming a re-render. Test in Task 1.
2. A `report.json` from a different render than `--render`: the fidelity check fails and names the first
   tick and both SSIM values. Test in Task 4.
3. Too few paired ticks between the two captures: below 20, the bench stops and prints the count rather
   than reporting a σ from a handful of frames. Test in Task 4.
4. A `--compare-test` render missing ticks the fresh render has: the verdict skips them and counts them
   as `missing`, never panics. Test in Task 7.
5. A Haiku answers file with a missing, duplicated or unparsable line: scoring counts it as
   unanswered and reports the count. Test in Task 5.

---

### Task 1: Load planes, reproduce the Rust SSIM, and pin both to one fixture

**Files:**
- Modify: `pyproject.toml` (dev group: `numpy>=2.5`, `pillow>=13`), `uv.lock`
- Create: `python/stunt_reel/bench/__init__.py`, `python/stunt_reel/bench/planes.py`,
  `python/stunt_reel/bench/ssim.py`
- Create: `tests/fixtures/parity/bench/make_fixture.py` and its output under
  `tests/fixtures/parity/bench/{capture,render,render_before}/`, `tests/fixtures/parity/bench/golden.json`
- Modify: `tests/fixtures/README.md`, `crates/stunt-cli/src/parity/tests.rs`, `.gitattributes`
  (`*.idx binary` and `*.layer binary`: `* text=auto eol=lf` would otherwise treat an index plane
  with no NUL byte as text and rewrite its `0x0D 0x0A` pairs)
- Test: `tests/test_bench_ssim.py`

**Interfaces:**
- Produces, in `planes.py`:
  - `@dataclass(frozen=True) class RenderPlanes: rgb: NDArray[np.uint8]  # (200, 320, 3)`;
    `idx: NDArray[np.uint8] | None  # (200, 320)`; `layer: NDArray[np.uint16]  # (200, 320)`
  - `@dataclass(frozen=True) class CapturePlanes: idx: NDArray[np.uint8]`; `palette: NDArray[np.uint8]  # (256, 3), 8-bit`
  - `class RenderSource(Protocol)` with `ticks(self) -> list[int]` and `load(self, tick: int) -> RenderPlanes`.
    Faults, metrics and the bench take a `RenderSource`, so their tests build sources in memory
    instead of writing render trees.
  - `class RenderTree(RenderSource)` with `__init__(self, root: Path)`; `load` decodes the PNG with
    Pillow, keeps the 64 most recent ticks in an LRU cache (a whole tree is about 500 MB in memory),
    and raises `BenchError` naming a re-render when a tick's `.idx` or `.layer` is missing.
  - `def load_capture(directory: Path) -> dict[int, CapturePlanes]` keyed by `film_tick`, via
    `parity_artifacts.read_capture` and `read_capture_palette`.
  - `class BenchError(RuntimeError)`.
- Produces, in `ssim.py`:
  - `def capture_luma(planes: CapturePlanes) -> NDArray[np.float64]  # (200, 320)`: the palette lookup
    and luma of `frames.rs::reference_luminance`, *without* its stretch (the Rust function stretches
    inside; here `stretch` is a separate step).
  - `def render_luma(rgb: NDArray[np.uint8]) -> NDArray[np.float64]` as `rgb_to_luminance`.
  - `def stretch(plane: NDArray) -> NDArray` rows 200 to 240 as `rescale_mode13h_frame`
    (row `y_out` takes row `int(y_out * 200 / 240)`, computed in float32).
  - `def overlay_mask(capture_idx: NDArray[np.uint8]) -> NDArray[np.bool_]` as `mask.rs::ui_overlay_mask`
    (rows 185 and below, or index 255).
  - `def window_grid(mask240: NDArray[np.bool_] | None) -> NDArray[np.bool_]` the windows (11x11,
    stride 8 over 320x240) not touching the mask, shape `(29, 39)`.
  - `def window_ssim(a240: NDArray, b240: NDArray) -> NDArray[np.float64]  # (29, 39)` per window,
    the `compute_window_ssim` formula (sample variance with `n - 1`, C1 6.5025, C2 58.5225, the
    `den <= 1e-12` branch).
  - `def frame_ssim(capture: CapturePlanes, render_rgb: NDArray[np.uint8]) -> float` the
    `score_frame` SSIM: mean over allowed windows, 1.0 when none.

- [ ] **Step 1: Add the dev dependencies.** `numpy>=2.5` and `pillow>=13` in the dev group; run
  `mise exec -- uv lock`. Pillow decodes the render PNGs and writes the judge's composites.
- [ ] **Step 2: Write the fixture generator** `tests/fixtures/parity/bench/make_fixture.py`. It writes
  two film ticks (10 and 20) of 320x200 content. The capture's `meta.json` goes through
  `parity_artifacts.write_capture` and the render's `render.json` through `parity_artifacts.write_render`,
  so both validate; the planes and palettes are laid out as `test_support.rs::write_reference_faded` and
  `write_render_record` lay out theirs (capture: `tick_NNNN.idx`, `palettes_NNNN.json`; render:
  `tick_NNNNN.png`, `.idx`, `.layer` as little-endian u16). Content: rows 0–59 sky indices cycling
  227–238, rows 60–184 terrain (layer 2) in an 8-pixel checker of indices 40 and 41, a 20x16 actor
  (index 16, layer 16) at x 100, y 120; rows 185–199 a bar of index 250. Capture palette: entry *i* =
  (i, 255 − i, i // 2). The render's PNG is that palette scaled by 0.9 and rounded, so neither tick
  scores 1.0 and the golden tests the arithmetic, not just the identity. The capture at tick 20 has
  the actor 4 columns right; `render_before/` is `render/` with the terrain checker phase flipped at
  tick 20. Run it once and commit its output.
- [ ] **Step 3: Write golden values with the real scorer.** Run
  `cargo run -p stunt-cli --release -- parity --reference tests/fixtures/parity/bench/capture --test tests/fixtures/parity/bench/render --output <tmp>`;
  copy each frame's `film_tick` and `ssim` into `golden.json` as
  `{"ssim": {"10": <value>, "20": <value>}}`.
- [ ] **Step 4: Write the Rust guard** `bench_fixture_matches_its_golden_ssim` in
  `crates/stunt-cli/src/parity/tests.rs`: run parity on the fixture (path from `CARGO_MANIFEST_DIR`)
  and assert each frame's `ssim` equals `golden.json` within 1e-6. A future scorer change then has to
  regenerate the golden, which re-tests the numpy copy.
- [ ] **Step 5: Write the failing Python tests** in `tests/test_bench_ssim.py`:

```python
def test_numpy_ssim_matches_the_rust_golden(bench_fixture):
    golden = json.loads((bench_fixture / "golden.json").read_text())["ssim"]
    capture = load_capture(bench_fixture / "capture")
    tree = RenderTree(bench_fixture / "render")
    for tick in (10, 20):
        assert abs(frame_ssim(capture[tick], tree.load(tick).rgb) - golden[str(tick)]) < 1e-4


def test_identical_frames_score_one(bench_fixture):
    capture = load_capture(bench_fixture / "capture")[10]
    rgb = capture.palette[capture.idx]
    assert abs(frame_ssim(capture, rgb) - 1.0) < 1e-9


def test_a_render_without_planes_names_a_rerender(tmp_path, bench_fixture):
    shutil.copytree(bench_fixture / "render", tmp_path / "r")
    (tmp_path / "r" / "tick_00010.layer").unlink()
    with pytest.raises(BenchError, match="re-render"):
        RenderTree(tmp_path / "r").load(10)


def test_stretch_repeats_every_fifth_row():
    plane = np.arange(200, dtype=np.float64)[:, None].repeat(320, axis=1)
    out = stretch(plane)
    assert out.shape == (240, 320)
    assert out[:7, 0].tolist() == [0, 0, 1, 2, 3, 4, 5]
```

  `bench_fixture` is a fixture in `tests/conftest.py` returning `tests/fixtures/parity/bench`.
- [ ] **Step 6: Run** `mise exec -- uv run pytest tests/test_bench_ssim.py -v`; expect failures
  (module missing).
- [ ] **Step 7: Implement `planes.py` and `ssim.py`.** Vectorise windows with
  `numpy.lib.stride_tricks.sliding_window_view` over the stretched planes, taking every 8th window.
  Check `test_stretch_repeats_every_fifth_row`'s row list against the Rust float32 arithmetic before
  trusting it; if they differ, the Rust behaviour is right and the test's list changes.
- [ ] **Step 8: Run** the Python tests and `mise run check-rust`; expect PASS.
- [ ] **Step 9: Document the fixture** in `tests/fixtures/README.md` (what each directory holds, the
  generator, the golden and which test pins it).
- [ ] **Step 10: Run `mise run check`, then commit** `feat(bench): reproduce the parity SSIM in numpy`.

### Task 2: Plant faults

**Files:**
- Create: `python/stunt_reel/bench/faults.py`
- Test: `tests/test_bench_faults.py`

**Interfaces:**
- Consumes: `RenderPlanes`, `RenderSource` (Task 1).
- Produces:
  - `@dataclass(frozen=True) class Fault: name: str; magnitude: int | None` with a `key` property:
    `name`, or `name:magnitude`.
  - `ALL_FAULTS: tuple[Fault, ...]` in this order: `none`; `actors_removed`; `shift_x` 1, 2, 4, 8;
    `shift_y` 1, 2, 4; `advance` 1, 3, 5; `flat_terrain`; `flicker` 3, 10; `wrong_tick`; `grey`.
  - `def plant(fault: Fault, tick: int, source: RenderSource, rng_seed: int) -> RenderPlanes | None`;
    `None` means the fault has no frame at this tick (advance past the end, no qualifying wrong tick).
  - `WRONG_TICK_DRAWS = 50`: `wrong_tick` draws candidates (ticks at least 100 away) in the RNG's order
    without replacement and takes the first whose `.idx` differs in at least 10% of pixels; after 50
    draws it returns `None`. Testing every candidate would read every plane of the tree for every
    frame.

Each fault's effect on each plane, from the spec's table:

| Fault | RGB and `.idx` | `.layer` |
|---|---|---|
| `actors_removed` | each pixel on layer ≥ 16 takes the nearest pixel to its left in the same row that is not on layer ≥ 16; with none to its left it stays | same rule |
| `shift_x` *k* | rows move right by *k*; columns 0..*k* repeat column 0 | same |
| `shift_y` *k* | columns move down by *k*; rows 0..*k* repeat row 0 | same |
| `advance` *k* | all planes of tick *t* + *k* | same |
| `flat_terrain` | layer-2 pixels take the mean layer-2 RGB (rounded); `.idx` the modal layer-2 index | unchanged |
| `flicker` *a* | RGB + *a* on even ticks, − *a* on odd, clipped to 0..255; `.idx` unchanged | unchanged |
| `wrong_tick` | all planes of a tick drawn by `random.Random(rng_seed * 1_000_003 + tick)` (see `WRONG_TICK_DRAWS`) | same |
| `grey` | every RGB channel = round(mean render luma); `.idx` `None` | unchanged |

- [ ] **Step 1: Write the failing tests** on in-memory sources, a helper
  `MemorySource(ticks: dict[int, RenderPlanes])` in `tests/pytest_helpers.py` that Tasks 3 and 4 reuse:
  - `test_actor_pixels_take_their_left_neighbour`: a row `[5, 7(actor), 7(actor), 9]` becomes
    `[5, 5, 5, 9]`, layers `[2, 2, 2, 2]`; a row starting with an actor keeps it.
  - `test_shift_x_repeats_the_first_column` (k = 2) and `test_shift_y_repeats_the_first_row` (k = 1).
  - `test_advance_past_the_end_is_none`.
  - `test_flicker_alternates_and_clips`: tick 4 with value 250 and *a* = 10 gives 255; tick 5 gives 240.
  - `test_wrong_tick_is_far_and_different_and_repeatable`: the chosen tick is ≥ 100 away, its `.idx`
    differs in ≥ 10%, and the same seed picks the same tick; with no qualifying tick, `None`.
  - `test_grey_has_no_index_plane`.
- [ ] **Step 2: Run** them; expect FAIL.
- [ ] **Step 3: Implement `faults.py`.**
- [ ] **Step 4: Run** them; expect PASS.
- [ ] **Step 5: Run `mise run check`, commit** `feat(bench): plant render faults in memory`.

### Task 3: Candidate metrics and the differential score

**Files:**
- Create: `python/stunt_reel/bench/metrics.py`
- Test: `tests/test_bench_metrics.py`
- Modify: `tests/fixtures/parity/bench/golden.json` (adds the differential golden)

**Interfaces:**
- Consumes: Task 1's `ssim.py` and planes.
- Produces:
  - `@dataclass(frozen=True) class Regions: layer: NDArray[np.uint16]; control_mean_luma: float` from
    the **control** render at the tick (spec, Shared rules); every metric takes its regions and its grey
    level from here, never from the fault's planes.
  - `Metric = Callable[[CapturePlanes, RenderPlanes, Regions], float | None]`; `None` is `n/a`.
  - `METRICS: dict[str, Metric]` with keys `ssim`, `ssim_structured`, `grey_skill`, `index_ocean`,
    `index_terrain`, `index_props`, `index_actors`, `edge_f`, `ssim_actors`.
  - `def differential(capture: CapturePlanes, before: RenderPlanes, after: RenderPlanes) -> Differential`
    with `@dataclass(frozen=True) class Differential: changed_idx: float; changed_luma: float;
    changed_by_layer: dict[str, float]; delta: float | None` (fractions of the 320x200 pixels;
    `delta` `None` when no window changed).

Definitions:

- `ssim`: Task 1's `frame_ssim`.
- `ssim_structured`: mean window SSIM over allowed windows whose stretched capture luma has
  max − min > 3; `None` when there are none.
- `grey_skill`: (S − G) / (1 − G), S = `ssim`, G = `ssim` of a uniform frame at
  `round(Regions.control_mean_luma)`; `None` when G ≥ 1.
- `index_<layer>`: share of pixels outside the overlay, on that layer in `Regions` (ocean 1, terrain 2,
  props 3, actors ≥ 16), where capture `.idx` equals render `.idx`; `None` when the render has no
  `.idx` or the layer has no pixels.
- `edge_f`: on the unstretched 200-row luma, rows 0–184, edges where Sobel |gx| + |gy| ≥ 64; precision
  and recall with a 1-pixel tolerance (each side's edges dilated by a 3x3 square), F = 2PR / (P + R);
  1.0 when neither side has an edge, 0.0 when only one does.
- `ssim_actors`: mean window SSIM over allowed windows whose stretched `Regions` layer has a pixel ≥ 16;
  `None` when none.
- `differential`: a pixel changed when `.idx` or luma differs (`changed_by_layer` keyed `ocean`,
  `terrain`, `props`, `actors`, `none` by the *after* render's layer); changed windows are allowed windows
  (overlay from the capture) containing a stretched changed pixel; `delta` = mean window SSIM of
  capture against *after* minus that against *before*, over the changed windows. Positive is closer.

- [ ] **Step 1: Write the failing tests:**
  - `test_every_metric_is_at_its_best_on_a_perfect_render`: capture tick 10 against its own palette RGB
    and `.idx`: `ssim`, `ssim_structured`, `edge_f`, `ssim_actors` = 1.0; every `index_*` that is not
    `None` = 1.0.
  - `test_grey_skill_is_zero_for_the_grey_frame_itself`.
  - `test_index_metrics_are_na_without_an_index_plane`.
  - `test_regions_come_from_the_control_render`: with `Regions` from the control, `ssim_actors` of the
    `actors_removed` planes is a number; with `Regions` built from those planes it would be `None`,
    since no actor is left to define the windows.
  - `test_differential_of_identical_renders_has_no_delta`.
  - `test_differential_matches_its_golden`: on the fixture, `render_before` against `render` at tick 20;
    assert fractions and `delta` equal `golden.json["differential"]["20"]` to 1e-9.
- [ ] **Step 2: Run** them; expect FAIL.
- [ ] **Step 3: Implement `metrics.py`.** Then write `golden.json["differential"]` from the
  implementation (`{"20": {"changed_idx": ..., "changed_luma": ..., "changed_by_layer": {...}, "delta": ...}}`)
  with a short script run once; Task 7's Rust test reads the same entry. A `grey` after (no `.idx`)
  is not a valid differential input: `differential` raises `BenchError`.
- [ ] **Step 4: Run** them; expect PASS.
- [ ] **Step 5: Run `mise run check`, commit** `feat(bench): add candidate parity metrics`.

### Task 4: The bench run, its noise yardstick and the task

**Files:**
- Create: `python/stunt_reel/bench/run.py`, `python/scripts/parity_bench.py`
- Modify: `mise.toml` (task `parity-bench`)
- Test: `tests/test_bench_run.py`

**Interfaces:**
- Consumes: Tasks 1–3.
- Produces:
  - `MIN_PAIRED_TICKS = 20`, `DETECT_SIGMAS = 3.0`, `FIDELITY_TOLERANCE = 1e-4`.
  - `def check_fidelity(report: Path, captures: dict[int, CapturePlanes], tree: RenderTree) -> None`:
    raises `BenchError` naming the first tick whose numpy `ssim` differs from `report.json`'s by more
    than `FIDELITY_TOLERANCE`, with both values.
  - `def recapture_sigma(metric: str, a: dict[int, CapturePlanes], b: dict[int, CapturePlanes], source: RenderSource, ticks: list[int]) -> float`
    over the exactly paired scored ticks; `BenchError` with the count when fewer than
    `MIN_PAIRED_TICKS`.
  - `def bench(reference: dict[int, CapturePlanes], recapture: dict[int, CapturePlanes], source: RenderSource, scored_ticks: list[int], seed: int, floor: RenderSource | None) -> dict[str, Any]`:
    the in-memory core that the tests drive, returning the `bench.json` document:
    `{"film_ticks": [...], "sigma": {metric: float}, "results": {metric: {fault_key: {"mean_change": float | None, "sigmas": float | None, "detected": bool, "frames": int}}}, "detectable": {metric: {fault_name: int | None}}, "passes": {metric: bool}, "differential": {fault_key: {"mean_delta": float | None, "negative": bool}}, "build_floor": {"max_changed_pixels": int, "mean_changed_pixels": float} | None}`.
    `detectable` lists only the faults with magnitudes (`shift_x`, `shift_y`, `advance`, `flicker`).
    When σ is 0, `sigmas` is `None` and `detected` is `mean_change < 0`.
  - `def run_bench(reference: Path, recapture: Path, render: Path, report: Path, seed: int, floor_render: Path | None) -> dict[str, Any]`:
    loads the paths, runs `check_fidelity`, reads the scored ticks from `report.json`, and calls `bench`.
  - `def plant_tree(render: Path, out: Path, plants: list[tuple[Fault, range]]) -> None`: copies the
    render tree to `out` and writes each fault over its tick range (PNG, `.idx`, `.layer`; `grey` is
    refused, having no `.idx`). Task 8 uses it to make a render with known errors.
- Script subcommands:
  - `run --film ctry [--render DIR] [--report FILE] [--recapture ID] [--seed N] [--floor-render DIR] [--out DIR]`.
    Defaults: reference from `references.read_reference`, recapture `005`, render
    `build/parity/ours/<film>_current`, report `build/parity/report/<film>_current/report.json`, seed 1,
    out `build/parity/bench/<film>`. Prints one row per metric: pass, σ, and per fault the change in σ.
  - `plant --render DIR --out DIR --fault KEY@FIRST-LAST ...` (for example `shift_x:4@500-599`).

Rules (spec § 1): only frames `report.json` marks `scored` count. A fault's mean change is the mean over
its frames of (metric of fault − metric of control) against the reference capture; `detected` when
`−mean_change ≥ DETECT_SIGMAS × σ`. A metric's detectable magnitude for a fault is the smallest detected
magnitude, or `None`. A metric `passes` when every fault other than `none` is detected and no fault has
every frame `n/a` (a frame without actors may be `n/a` for `ssim_actors`; a fault where all frames are is
a fail). `differential[fault].negative`, for every fault but `none` and `grey`, is the bench's check of
Task 7's verdict: the mean `delta` of the control as *before* and the fault as *after* must be below 0. The build floor counts changed pixels (Task
3's rule) between `--render` and `--floor-render`, per tick.

- [ ] **Step 1: Write the failing tests.** `bench` tests use a `MemorySource` of 300 ticks with a
  moving actor and captures at every 10th tick, so `advance` and `wrong_tick` have frames; the
  fidelity and `plant_tree` tests use the Task 1 fixture copied to `tmp_path`:
  - `test_a_stale_report_names_the_tick` (Review Focus 2: the fixture's report with tick 20's `ssim`
    changed by 0.01).
  - `test_too_few_paired_ticks_stops_with_the_count` (Review Focus 3: 19 paired ticks).
  - `test_plant_tree_changes_only_the_planted_ticks` (tick 20 planted with `shift_x:4`; tick 10's files
    byte-identical to the source).
  - `test_a_fault_that_does_nothing_is_not_detected` (a `flat_terrain` on a render with no terrain).
  - `test_a_large_shift_is_detected_by_ssim_structured`.
  - `test_bench_json_has_every_metric_and_fault`.
  - `test_unscored_frames_are_left_out`.
- [ ] **Step 2: Run** them; expect FAIL.
- [ ] **Step 3: Implement `run.py`, the script and the task** (`run = "uv run python python/scripts/parity_bench.py"`,
  description naming `run`, `plant`, `judge-make` and `judge-score`).
- [ ] **Step 4: Run** them; expect PASS.
- [ ] **Step 5: Run `mise run check`, commit** `feat(bench): score planted faults against recapture noise`.

### Task 5: The Haiku judge's composites and scoring

**Files:**
- Create: `python/stunt_reel/bench/judge.py`
- Modify: `python/scripts/parity_bench.py` (subcommands `judge-make`, `judge-score`)
- Test: `tests/test_bench_judge.py`

**Interfaces:**
- Consumes: Tasks 1–2.
- Produces:
  - `def make_composites(reference: Path, render: Path, report: Path, out: Path, seed: int, frames_per_fault: int = 10) -> int`
    (`report` supplies the scored ticks):
    for each fault key except `none` and `grey`, picks `frames_per_fault` scored ticks with
    `random.Random(seed)`, and for each writes two composites (both orders) plus
    `frames_per_fault` control pairs (control twice). Each composite is one PNG, capture | A | B, each
    panel 320x240 (rows stretched as Task 1), 8-pixel white gaps, named `<id>.png` where `id` is
    `sha256(f"{seed}:{fault_key}:{tick}:{order}")[:12]`. Writes `ids.txt` (ids in shuffled order, one
    per line) and returns the count. Writes no key.
  - `def answer_key(reference: Path, render: Path, report: Path, seed: int, frames_per_fault: int = 10) -> dict[str, tuple[str, str]]`:
    id → (`fault_key`, correct answer `"A"`, `"B"` or `"either"` for control pairs), recomputed from the
    seed.
  - `def score_answers(answers: Path, key: dict[str, tuple[str, str]]) -> dict[str, Any]`: reads lines
    `<id> <A|B> <reason>`; per fault key `{"accuracy": float, "answered": int, "a_share": float}`;
    top-level `"unanswered": int` (missing, duplicated or unparsable ids) and `"control_a_share"`; per
    fault key also `"passes": accuracy >= 0.9`.
- Subcommands: `judge-make --film ctry --seed N [--out DIR]` and
  `judge-score --film ctry --seed N --answers FILE [--out DIR]`, writing `judge.json`.

- [ ] **Step 1: Write the failing tests:**
  - `test_composites_carry_no_key` (no file under `out` other than PNGs and `ids.txt`).
  - `test_the_key_is_recomputed_from_the_seed` (two calls agree; another seed differs).
  - `test_each_pair_appears_in_both_orders`.
  - `test_bad_answer_lines_count_as_unanswered` (Review Focus 5: one missing id, one duplicate, one
    `zzz` line).
  - `test_accuracy_counts_both_orders`.
- [ ] **Step 2: Run** them; expect FAIL.
- [ ] **Step 3: Implement `judge.py` and the subcommands.**
- [ ] **Step 4: Run** them; expect PASS.
- [ ] **Step 5: Run `mise run check`, commit** `feat(bench): make blind composites for a Haiku judge`.

### Task 6: Run the bench on CTRY.FLM and record it

No code. The controller runs this task (subagents for the judging only).

- [ ] **Step 1: Fresh render.** `mise run parity -- --films ctry`, so `ctry_current` and its
  `report.json` come from this revision's binary.
- [ ] **Step 2: Floor render.** `mise run build-at -- HEAD build/scratch/bench/floor-bin`, then render
  `CTRY.FLM` with that binary into `build/scratch/bench/ctry_floor`, using the command line
  `parity_pipeline.render_film` builds, with the floor binary in place of `binary_path()`.
- [ ] **Step 2a: Bench.** `mise run parity-bench -- run --film ctry --floor-render build/scratch/bench/ctry_floor`.
  Expect the fidelity check to pass; if it does not, stop and report.
- [ ] **Step 3: Judge.** `mise run parity-bench -- judge-make --film ctry --seed <random>`; split
  `ids.txt` into 4–8 equal lists; dispatch one Haiku subagent per list (`model: haiku`), each with its
  own answers file, with the brief: "Read each `<id>.png` listed in `<list>`. Each image shows three
  panels: the reference, then A, then B. For each, decide which of A or B matches the reference more
  closely. Append one line per image to `<answers_N.txt>` with the shell:
  `<id> <A or B> <one sentence on the difference you see>`. Do not read any other file. If writing is
  refused, return the lines as your final message." Concatenate the answer files; run `judge-score`
  with the same seed.
  If `wrong_tick` does not pass, the arm is dropped (spec, Stop conditions): record that and skip the
  rest of its reading.
- [ ] **Step 3a: `INTRO.FLM`.** Once `CTRY.FLM` has run cleanly, run Steps 1 and 2a (no floor) with
  `--films intro` / `--film intro`, against `vault-intro/frames/005`, as the second column; the judge
  stays `CTRY.FLM` only. If the two `INTRO.FLM` captures share fewer than 20 ticks, record the count and
  go on without the column.
- [ ] **Step 4: Record.** Add `method.md` § 2.2 "The metric bench" (what was measured, the table of
  metrics × faults in σ, detectable magnitudes, which metrics pass, the Haiku accuracy per fault, the
  differential check, the build floor) and one `log.md` row at the end. Answer what can be answered
  of the spec's Open questions in the spec.
- [ ] **Step 5: Commit** `docs(parity): record the metric bench on CTRY.FLM` (gate: documentation only;
  run `mise run check` anyway, since the spec edit is in `docs/process/`).

### Task 7: The regression verdict in `--compare`

**Files:**
- Create: `crates/stunt-cli/src/parity/verdict.rs`
- Modify: `crates/stunt-cli/src/parity/mod.rs` (module), `compare.rs` (call it; order sheets by Δ),
  `args.rs` (`--noise-sigma <F>` and `--build-floor <N>`, both `requires = "compare_test"`)
- Test: unit tests in `verdict.rs`; the golden test in `tests.rs`

**Interfaces:**
- Consumes: `load_reference`; `compute_window_scores`; `golden.json["differential"]` (Task 3). The
  render planes are loaded inline in `mod.rs` (where it builds `&RenderFrame { ... }`); extract that
  into `fn load_render_frame(dir: &Path, tick: usize) -> Result<RenderFrame, String>` and use it for both
  the fresh and the `--compare-test` render.
- Produces:
  - `pub(super) struct FrameVerdict { film_tick: u64, changed_idx: f32, changed_luma: f32, changed_by_layer: BTreeMap<&'static str, f32>, before_after_ssim: f32, delta: Option<f32>, class: VerdictClass }`
    (`before_after_ssim` is `compute_frame_ssim` of before against after, stretched, no mask)
  - `pub(super) enum VerdictClass { Unchanged, BuildNoise, WithinNoise, Closer, Further, Missing }`
  - `pub(super) fn frame_verdict(reference: &ReferenceFrame, before: &RenderFrame, after: &RenderFrame, sigma: Option<f32>, build_floor: usize) -> FrameVerdict`
  - `pub(super) struct Verdict { frames: Vec<FrameVerdict> }` with `summary(&self) -> String` and
    `to_json(&self) -> serde_json::Value`.

Classes, in order: `Missing` when the before tick is absent; `Unchanged` with no changed pixel;
`BuildNoise` with at most `build_floor` changed pixels; then by `delta`: with `sigma`, `WithinNoise` when
|Δ| < σ, else `Closer` or `Further` by sign; without `sigma`, `Closer` when Δ > 0, `Further` when Δ < 0,
`WithinNoise` when Δ = 0. A changed frame with no changed window (all its changes under the overlay) is
`Unchanged`.

Summary line, exactly:
`[verdict] changed {c}/{n} frames: {closer} closer, {further} further, {within} within noise; mean Δ {mean:+.3} on changed windows`
followed by `({build} build noise, {missing} missing)` when either is non-zero, and
`(no noise sigma: Δ by sign only)` without `--noise-sigma`. `compare.json` gains `"verdict": {"frames": [...], "counts": {...}, "mean_delta": f}`.
The worst-mover sheets pick the most negative and most positive Δ when the verdict ran, else the
existing SSIM deltas.

- [ ] **Step 1: Write the failing Rust tests:**
  - `verdict_matches_the_numpy_golden`: on the fixture, before `render_before`, after `render`, tick 20;
    fractions within 1e-6 and Δ within 1e-4 of `golden.json["differential"]["20"]`.
  - `an_identical_frame_is_unchanged`, `a_frame_under_the_floor_is_build_noise`,
    `sigma_buckets_small_deltas`, `without_sigma_the_sign_decides`.
  - `a_missing_before_tick_is_counted_not_fatal` (Review Focus 4).
  - `noise_sigma_requires_compare_test` in `args.rs`.
- [ ] **Step 2: Run** `mise run check-rust`; expect FAIL.
- [ ] **Step 3: Implement** `verdict.rs`, `load_render_frame`, the flags, and the `compare.rs` call and
  sheet order.
- [ ] **Step 4: Run** them; expect PASS.
- [ ] **Step 5: Run `mise run check`, commit** `feat(parity): judge a render change on the windows it touched`.

### Task 8: Check the verdict on the planted render and record σ

No new code. The controller runs it.

- [ ] **Step 1: Plant.** `mise run parity-bench -- plant --render build/parity/ours/ctry_current --out build/scratch/bench/ctry_alt --fault actors_removed@250-349 --fault shift_x:4@500-599 --fault advance:5@750-849`
  (the three errors of the dropped per-second validation, now made by tested code).
- [ ] **Step 2: Score and compare.**
  `stuntreel parity --reference <ctry 004> --test build/scratch/bench/ctry_alt --output build/scratch/bench/ctry_alt_report --compare build/parity/report/ctry_current/report.json --compare-test build/parity/ours/ctry_current --noise-sigma <σ of ssim from bench.json> --build-floor <max_changed_pixels>`.
  The before render is the planted tree's own source, so only planted ticks can change. Expect every
  scored tick in 250–349, 500–599 and 750–849 changed (an `actors_removed` tick without actors stays
  `Unchanged`) and every other tick `Unchanged`; record how many changed frames read `Further`.
- [ ] **Step 3: Record.** Add `noise_sigma` for `ctry` to `research/parity/references.toml` (the
  bench's `ssim` σ; `references.read_reference` ignores keys it does not know), extend `method.md` § 1
  step 5 with the verdict line and its flags, and add a `log.md` row.
- [ ] **Step 4: Run `mise run check`, commit** `docs(parity): record the regression verdict on planted faults`.
