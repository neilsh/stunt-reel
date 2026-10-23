# Playbook: Parity Scoring Call & Render Hardening

> **Active plan, 2026-10-23.** This is a process document, not a source of truth. Facts about the system belong in [`SPEC.md`](../SPEC.md), [`research/parity-findings.md`](../../research/parity-findings.md) and the code. When this plan ships, mark it **Historical** like [`m1-runtime-capture.md`](m1-runtime-capture.md).

It comes from the 2026-10-23 architecture review: candidate 2 (the frame-scoring call) plus the defects that review found. Decisions D1–D28 below were agreed in the grilling rounds, so don't reopen them here.

---

## 1. Tracks and file ownership

The work runs as two tracks in parallel, then a third later. Each file has one owner at a time, so two tracks never write the same file at once.

| Track | Runs in | Owns while active |
|---|---|---|
| **P: parity** (A → B → G → D → C) | this session, on `main` | `crates/stunt-cli/src/parity/**`, `python/scripts/parity_sweep.py`, `python/scripts/parity_probe.py`, `docs/SPEC.md`, `README.md`, `GLOSSARY.md`, `research/parity/**`, `research/parity-findings.md` |
| **R: render & CLI hardening** (H → E → F) | one worktree session | `.github/workflows/ci.yml`, `mise.toml`, `crates/stunt-render/**` (except `src/parity.rs` threshold constants), `crates/stunt-cli/src/main.rs`, `crates/stunt-cli/src/export.rs`, `crates/stunt-cli/src/scene.rs`, `crates/stunt-cli/tests/**`, `crates/stunt-core/src/contracts/parity.rs`, `AGENTS.md`, `docs/ARCHITECTURE.md` |
| **I: I6 gate** (after P and R merge) | this session | P's files plus `crates/stunt-render/src/parity.rs` and `crates/stunt-render/tests/render_test.rs` |
| **L: later** (C1 + C5, then the typed report) | fresh session(s) after I | decided at kickoff |

Changes from the first draft:
- **E, F and H are now one sequential session (R), not three.**
  - E and H both edit `render_test.rs` and `export_test.rs`.
  - E and F both edit `main.rs`.
- **The I6 gate and SPEC rework moved out of E into step I.**
  - The `PHASE*` constants are moving into `stunt-cli/src/parity`, which P owns.
  - The `G06`/`G07` rows are in `SPEC.md`, which B already edits.
- **Seam 4 stays.** It is the capture-and-compare seam (`VisualParityGate`): `palette.rs` and the capture tools in [`ARCHITECTURE.md`](../ARCHITECTURE.md) are mapped to it. Only the unused `VisualParityReport` type and `evaluate_visual_parity` are deleted.

---

## 2. Track P: parity (this session)

Each step is one Conventional Commit. While iterating, run `mise run check-rust` / `mise run check-py`. Run the full `mise run check` at the end of C (Directive 2).

### A: Sky-band fix in the pure functions (D1, D2, D4)
- Add a parity-local `CAPTURE_SKY_INDICES: RangeInclusive<u8> = 227..=238` in `parity/mask.rs`. Its doc comment links to parity-findings §7 and says it is deliberately not shared with `mode13h.wgsl`.
- Change `mask_iou_planes` and `loss_class`'s caller to "reference filled = index not in the sky bands", and drop the `sky_index` parameter.
- Add unit tests:
  - Every band index counts as sky.
  - 224–226 count as filled.
  - The layer-IoU test is rewritten to use band indices.
- **Done:** `check-rust` is green. The report still has `sky_index` (removed in B).

### B: Remove the luminance fallback and parity's `--clear-index` (D3, D7)
- Delete `mask_iou` (luminance) and its match arm. A missing render-planes file is now an error that says to re-render with the current `stunt-cli --headless`.
- Remove `--clear-index`, the clear-luminance plumbing and `sky_index()` from parity (`args.rs`, `mod.rs`, `frames.rs`). The arg parser rejects the flag as unknown.
- Remove `"clear_index"` / `"sky_index"` from report.json. Optionally add `"sky_indices": [227, 238]`.
- Update the callers and docs:
  - `parity_sweep.py:53, 241`
  - `README.md:96`
  - `research/parity/method.md:11`
  - `docs/SPEC.md:176` (`G07` command)
  - `research/parity-findings.md:56`
- The end-to-end tests that score luminance-only fixtures must write planes first. Delete `the_sky_mask_uses_the_render_palette_clear_colour` (D10).
- **Done:** `check-rust` and `check-py` are green. `rg -- "--clear-index"` matches only the render's own flag.

### G: Sweep guard (replaces candidate 6)
- Add a check in `parity_sweep.py`, with a pytest on a synthetic tree:
  - Refuse to score when the render directory's sidecar names a different film than the reference directory.
  - Refuse to score when the render directory has no planes.
- **Done:** `check-py` is green.

### D: Re-baseline (D5, D12)
- Re-render and re-score CTRY, INTRO and COL3-2 with the `improving-render-parity` skill (build once, batched sweep, scratch paths).
- Add a dated entry to `research/parity-findings.md` with before/after `mean_iou`, `mean_ssim` and index agreement per film, and record 227 as observed in §7. No report version field.
- `GLOSSARY.md`:
  - Fix the "Fade level" entry: the authored fade decides scoring, and measured fade is a cross-check.
  - Add a "Sky band" entry.
- Keep the three `report.json` files in scratch as C's golden files.
- **Done:** the findings entry is committed. The golden files are saved outside the repo.

### C: Extract the scoring call into `parity/score.rs` (D6, D8, D9, D10)
- Add `score_frame(reference: &ReferenceFrame, render: &RenderFrame, policy: &ScorePolicy) -> FrameScore`.
  - `RenderFrame` holds luminance, indices, layers and optional authored controls.
  - `ScorePolicy` holds the fade set and the floor.
  - `FrameScore` carries SSIM, IoU, index agreement, loss classes, `scored`, and the rescaled luminance pair that `run` needs for contact sheets.
- `run` keeps file I/O, matching, sheets and the report. Everything per-frame moves behind `score_frame`.
- Rewrite these as in-memory `score.rs` tests:
  - authored-floor
  - planes/index-agreement
  - sky-band
- Keep the five remaining end-to-end tests in `tests.rs`.
- **Done:**
  - All three `report.json` files match D's golden files byte for byte.
  - The full `mise run check` is green.
  - `git status` shows nothing staged from `corpus/` or `target_bin/`.

---

## 3. Track R: render & CLI hardening (one worktree session)

Three commits in this order. Touch only R's files (§1).

### H: GPU tests run in CI (D21, D22)
- Add a shared `gpu_or_skip()` helper in a `tests/common` module of each crate that needs it. It replaces the six copy-pasted adapter blocks:
  - `render_test.rs` (×3)
  - `scene_renderer_test.rs`
  - `export_test.rs` (×2)
- When `STUNT_REQUIRE_GPU=1` is set, a missing adapter panics instead of skipping.
- On the ubuntu `check` job, install lavapipe (`mesa-vulkan-drivers`) and set `STUNT_REQUIRE_GPU=1`.
- These tests have never run in CI, so expect failures under lavapipe. Fix each one, or mark it `#[ignore = "<reason>"]` and list it in the session's hand-off.
- **Done:** CI runs the GPU tests (the log shows no skips), and `mise run check` is green locally.

### E: Render cleanup (D13–D16, part of D17)
- **Window surface:** prefer a non-sRGB format (`Rgba8Unorm`/`Bgra8Unorm`) and fall back to the first format. Test the picker on a fake capability list.
- **Window `--viewport-rows`:** reject it with a clear error.
- **`HeadlessRenderer::with_dimensions`:** pad rows to the 256-byte pitch internally and strip the padding on readback. Delete the CLI check at `main.rs:217`. Add a test with a width whose row is not a multiple of 256 bytes.
- **Legacy callers:** port the `render_to_png` callers (`render_test.rs:333`, `export_test.rs:55`) to the current path, then delete `render_to_png`.
- **Unused parity code:**
  - Delete `VisualParityReport` (`stunt-core/src/contracts/parity.rs`, its re-export, and the use in `render_test.rs:207`) and `evaluate_visual_parity`.
  - Leave the `PHASE*` constants where they are (step I moves them).
  - Update `AGENTS.md:34` and `docs/ARCHITECTURE.md:12`. Leave the `SPEC.md` Seam 4 and `G06` text to step I.
- **Done:** `mise run check` is green.

### F: Film input errors (D18–D20)
- **Shared loader:** add one film loader used by both `--headless`/window and `export-gltf`.
- **Named inputs:** a `--film`, `--sod` or archive that the user names and that fails to load is an error with a non-zero exit. The orbit demo runs only when no input is named.
- **Empty films:** a film with zero slices is an error. First confirm CTRY and INTRO have more than zero slices, and note the counts in the commit body.
- **Tests:** use synthetic fixtures for the bad-path, empty-film and no-input cases.
- **Done:** `mise run check` is green. Hand off with the branch name and any `#[ignore]` list from H.

---

## 4. Track I: I6 gate (this session, after P and R merge) (D17)
- Move `PHASE1_SSIM_THRESHOLD` / `PHASE2_SSIM_THRESHOLD` into `stunt-cli/src/parity`. `render_test.rs:199` uses a local literal instead.
- report.json gains `"i6_gate": {"initial": bool, "sign_off": bool}` from `mean_ssim`. The exit code does not change.
- `docs/SPEC.md`:
  - Merge `G06` into `G07`.
  - Point the Seam 4 entry (`:160`) at the stunt-cli report instead of `contracts/parity.rs`.
- **Done:** the full `mise run check` is green.

---

## 5. Track L: later (fresh sessions)
- **C1 + C5, the render directory** (D23–D28):
  - `--tick-range A..=B` replaces `--frames`; using `--frames` is an error that names the replacement.
  - A typed serde sidecar `render.json` that still reads `palette_controls.json`, carries width, height and viewport_rows, and that parity requires.
  - `parity_probe.py` drops its hard-coded 320/185/16.
  - One film clock range, `0..=total_ticks`.
- **Typed parity report:** deferred until C shows what `FrameScore` and the per-film summary want to be.

---

## 6. Decisions (D1–D28)

| # | Decision |
|---|---|
| D1 | Reference sky = fixed palette range `227..=238`. |
| D2 | Parity-local constant `CAPTURE_SKY_INDICES` that links to parity-findings §7 and is not shared with the shader. |
| D3 | Delete the no-planes luminance fallback; missing planes = error saying to re-render. |
| D4 | Fix the sky rule in the pure functions first, as its own commit, then extract the call. |
| D5 | Dated parity-findings entry and re-baseline CTRY/INTRO/COL3-2; no report version field. |
| D6 | The scoring call decides `scored`; the floor is a policy parameter. |
| D7 | Remove parity's `--clear-index` (unknown-argument error); update the sweep, four docs and report.json. |
| D8 | The call takes the reference frame, render frame (luminance, indices, layers, optional controls) and policy (fade set, floor); it returns the score plus the rescaled luminance pair. |
| D9 | The call lives in `parity/score.rs`. |
| D10 | Rewrite the authored-floor, planes/index-agreement and sky-band tests in memory; delete the clear-colour sky test; keep five end-to-end tests. |
| D11 | The typed report and the Seam 4 cleanup are out of the scoring-call work (now in R/I/L). |
| D12 | GLOSSARY: fix "Fade level" and add "Sky band"; §7 records 227 as observed. |
| D13 | The window uses a non-sRGB surface format matching headless. |
| D14 | Window `--viewport-rows` is rejected, not implemented. |
| D15 | `with_dimensions` pads rows internally; the CLI pitch check is deleted. |
| D16 | Port the legacy `render_to_png` callers; delete only tests that exist just for the legacy path. |
| D17 | I6 constants move to stunt-cli parity; report records gate pass/fail without changing the exit code; SPEC `G06` merges into `G07`. |
| D18 | A named input that fails to load is a hard error; the orbit fallback applies only when nothing is named. |
| D19 | A film with zero slices is an error (after confirming CTRY/INTRO have more than zero). |
| D20 | export-gltf follows the same rules through one shared loader. |
| D21 | CI uses lavapipe on ubuntu plus `STUNT_REQUIRE_GPU=1`. |
| D22 | One shared `gpu_or_skip()` test helper. |
| D23 | `--tick-range A..=B` (0-based, inclusive) replaces `--frames`, which becomes an error naming it. |
| D24 | The sidecar is renamed `render.json`; the old name is still read. |
| D25 | The sidecar records width, height and viewport_rows; `parity_probe.py` drops its hard-coded values. |
| D26 | A typed serde sidecar is shared by the writer and parity. |
| D27 | Parity requires the sidecar; `authored.unwrap_or(measured)` goes away, and measured fade stays as a cross-check. |
| D28 | One inclusive film clock range `0..=total_ticks`; the window wraps at `% (total_ticks + 1)`. |

---

## 7. Open before starting
- **Commit cadence:** either commit each step as it lands (P: five commits on `main`; R: three on its branch), or hold commits for review.
- **Merging R:** R's branch is merged into `main` only when the user says so, and before track I starts.
