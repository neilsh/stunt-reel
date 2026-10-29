# Unit A: the render artifact seam

Status: design agreed 2026-10-24; all four landings merged. Source: architecture review card 1 (the render artifact seam) plus the report-aggregation rider.

## 1. Problem

A render is never described: it is a directory of files whose names, page-to-film-clock rule, plane packing, raster dimensions and optional untyped sidecar are conventions held in six modules across two languages. Rust and Python already disagree about what an artifact may contain, and the accepted decision in ADR 0005 (typed, required `render.json` carrying width, height and viewport rows; remove the authored-fade fallback) is not implemented.

## 2. Constraints

- ADR 0005 completes here (T13): `render.json` is typed and required after migration; `palette_controls.json` is read as a legacy fallback with a warning; `authored.unwrap_or(measured)` is removed.
- ADR 0004 keeps the I6 thresholds and `i6_gate()` in the CLI parity module.
- ADR 0010 keeps the shipped Python package dependency-free; the adapter is standard library only.
- Invariant I7: no I/O in `stunt-core`. The port crate stays pure.
- Offline synthetic-fixture tests; no corpus.
- No behaviour change to the local parity baseline (report fields identical, sampled planes identical).
- The page rule (file `tick NNNNN` is the frame drawn at film state N-1) is artifact semantics. The window and `export-gltf` keep their own sampling; they are not migrated by this unit.
- Capture directories are read through the port; the capture writer stays with unit D, which already rewrites the capture loop.

## 3. Decisions settled in the design round

- **Design:** the hybrid of both variants - the ports-and-adapters seam placement with the deep journal and reader grafted in.
- **Versioning:** `render.json` and `meta.json` carry `schema_version: 1`. `report.json` keeps serde-defaulted optional fields plus shared cross-language fixtures; no required-field-set version files until a change genuinely needs one.
- **Report aggregation:** one builder in the CLI parity module; `i6_gate()` remains there. The report schema stays in the port crate.
- **Capture:** port and read side only in this unit.
- **Python page-rule mapping:** the `--frames` mapping for captures gets one helper in the Python adapter rather than being duplicated in the sweep and the probe.

## 4. Chosen design

### Seam placement

- `crates/stunt-parity` - a new pure port crate. It holds the render record, the capture set, the report record, the schema version and the artifact errors. Dependencies: serde and `stunt-core` only. No filesystem, no image decoding, no wgpu.
- `crates/stunt-cli/src/parity_artifacts.rs` - the Rust adapter. It owns discovery, naming, the streaming journal writer, the streaming reader, PNG decoding, the report builder and `render_png`.
- `python/stunt_reel/parity_artifacts.py` - the Python adapter, standard library only, frozen dataclasses and readers/writers. It also owns `frames_for_captured_ticks`, the one named home for the `--frames` mapping.
- `python/scripts/parity_inputs.py` becomes a shim during migration and is then deleted. `parity_sweep`, `parity_probe` and `parity_run` consume the adapter.

### Interface sketch

Port (pure):

    pub struct RenderRecord { schema_version, film: FilmId, geometry: Geometry, ticks: Vec<RenderTick> }
    pub struct Geometry { width, height, viewport_rows }
    pub struct RenderTick { tick: u32, palette: RenderPalette, camera: CameraPose }
    pub struct CaptureSet { schema_version, film: FilmId, geometry: Geometry, frames: Vec<CapturedFrame> }
    pub struct CapturedFrame { ordinal, film_tick, frame_file, palette_file }

The port's palette record is its own versioned type with serde defaults; it does not embed the core palette contract directly, so a later field there cannot break old documents.

Rust adapter:

    impl RenderJournal { begin(dir, film, geometry); record(shown_at, &Page); finish() -> RenderDigest }
    impl Round { open(capture_dir, render_dir); frames() -> Iterator<Result<PairedFrame>>; geometry() }
    impl ReportBuilder { push(frame_rows); finish() -> Report }

Python adapter:

    open_round(capture, render) -> Round        # frames, geometry, film, warnings
    read_report(path) -> Report                 # headline(), gate, per_frame
    write_render(path, record); read_render(path)
    frames_for_captured_ticks(ticks) -> str     # the one --frames mapping

### Invariants

- `render.json` is written last, via temp file and rename; absence means the render is incomplete and parity says to re-render.
- `RenderTick.tick` is the film clock in the file name; its palette and camera are the scene frame drawn at `tick - 1`. That offset never crosses the port's interface.
- Ticks are strictly increasing and unique; sparse sets are legal; a captured tick without a render entry is unmatched.
- Geometry is positive; parity requires the render geometry to equal the capture geometry and `1 <= viewport_rows <= height`, checked before any plane is read.
- Capture ordinals are contiguous but never a time axis; duplicate `film_tick` values are legal (end hold); filenames are basenames.
- Report identities hold: `reference_frames == frames + unmatched`, `frames == scored_frames + excluded_frames`, and both scored means are null exactly when `scored_frames == 0`.
- Errors are `Missing`, `WrongType`, `UnsupportedVersion`, `Ordering`, `Conflict` and `Geometry`, each naming the path and the field; legacy-only renders are `LegacyRender` with the re-render action.

### What the interface hides

File naming and numbering; the page-to-film-clock rule; plane layouts and lengths; layer-id semantics; PNG size and decoding; palette expansion; the 320x240 aspect rescale; the legacy sidecar name, its empty-map fallback and the measured-fade fallback; capture ordinal versus film clock; film tags; report field derivations, null semantics and compare basis; the write order; and the version rules.

## 5. Dependency strategy and adapters

- In-process: serde, the port records, report aggregation identities. No seam.
- Local-substitutable: the artifact directory. Adapters: the real filesystem, and temp directories built by the journal in tests.
- Ports and adapters: the schema is the port. Real adapters: the Rust adapter, the Python adapter, and the legacy sidecar adapter. A memory-only adapter is not built: it varies nothing.
- True external: PLAYONE under DOSBox-X and ffmpeg; parity never calls them.

## 6. Migration

1. **Land the port, adapters and fixtures with no call-site change.** `--headless` writes both `render.json` and the legacy sidecar; parity reads `render.json` when present and the legacy sidecar with a warning otherwise; report output unchanged. Acceptance: `mise run check` green, local reports field-identical, sampled planes identical.
2. **Require `render.json`.** Remove `authored.unwrap_or(measured)`; a render without the document is `LegacyRender` with the re-render message. Re-render the local baseline once in this phase and record the before/after report diff.
3. **Switch the Python tools.** `parity_inputs` becomes a shim; retime rewrites `render.json` preserving unknown keys and syncs the legacy sidecar while it exists; the probe and sweep drop their constants; one sweep round compares the old and new reports through `--compare`.
4. **Stop writing the legacy sidecar** after a baseline re-render, keep reading it per ADR 0005, delete the shim and the raw-validator tests.

## 7. Tests

- Survive through the new interface: the Rust parity behaviour tests (fade floor, null scored means, film-tick matching, missing planes re-render message, untagged capture, I6 gate), the sweep rank/table/check/preflight/noise tests, the probe retime tests, the CLI tests, and the headless file-name tests moved into the adapter.
- Move: `test_render_range_covers_captured_ticks` becomes a test of `frames_for_captured_ticks` in the Python adapter.
- Die: the raw `parity_inputs` validator tests, the sidecar unknown-key test (replaced by a round-trip test), `parse_report`, and the duplicated `RENDER_SIDECAR` and geometry constants.
- New, offline: shared `render_v1`, `capture_v1` and `report_v1` fixtures read and rewritten by both adapters; unknown-version refusal; legacy-versus-record conflict; missing or incomplete `render.json`; geometry mismatch before planes; tick ordering; report identities and null means; journal-to-round round-trip; retime round-trip preserving unknown keys.

**Follow-up (2026-10-28).** The shared fixtures above never landed: neither language has a conformance document, and the page bytes have no cross-language pin. The corpus that lands them — the three documents, a legacy capture, and the `.idx`/`.layer` page pair — is specified in [parity-conformance-corpus.md](../parity-conformance-corpus.md).

**Landed (2026-10-29).** That corpus now exists in `tests/fixtures/parity/v1/` and both adapters are pinned against it: a `conformance` module in [parity_artifacts.rs](../../../../crates/stunt-cli/src/parity_artifacts.rs) and [test_parity_conformance.py](../../../../tests/test_parity_conformance.py). The page bytes stay pinned end to end now that `parity_artifacts.read_page` replaces the four hand-decoded reads. The `Round` and `ReportBuilder` half of the unit is still unlanded and is tracked separately.

## 8. Deletions

`write_planes`, `tick_png_name` and the sidecar constant move behind the adapter; `read_render_palettes` and `read_film_ticks` are replaced by the port; the second sidecar parse in `warn_on_film_mismatch` disappears; the Python `RENDER_SIDECAR`, `RENDER_SUFFIXES`, `WIDTH`, `ROWS`, `ACTOR_LAYER_MIN` and `parse_report` disappear; the aggregate computation in line inside `parity/mod.rs` becomes one builder.

## 9. Kill criteria

Abandon or re-shape the unit if: the port crate needs `stunt-render` or wgpu to read artifacts; the local report diff cannot be made identical; Python cannot mirror the records without codegen or a dependency; the journal cannot stream one frame at a time; `Round` grows past three entry points because callers need contact sheets, compare and retime; or a raw `json.loads` of a report or meta document survives outside the capture writer after phase 3.

## 10. Open items for implementation

- Crate and module names (`stunt-parity`, `parity_artifacts`) are proposals; confirm at the first PR.
- Whether `RenderPalette` mirrors or wraps the core palette contract is settled in favour of a port-owned record; record the decision in the first PR.
- The Python adapter module joins the shipped package (ADR 0010 keeps it dependency-free); confirm this is intended in the first PR.

## 11. Landing log

1. **Landing 1 merged 2026-10-24.** The `stunt-parity` port crate (schema, validation, unit tests); the CLI adapter (`RenderJournal`, capture loader, render-record reader with legacy sidecar fallback, report read/write); `--headless` dual-writes `palette_controls.json` and `render.json` last; parity reads through the adapter; the report schema moved to the port crate. Verification: `mise run check` green; the pre-change binary and the new one produce semantically identical `report.json` on `build/parity/ours/ctry_current` (124 frames); three re-rendered ticks have byte-identical PNG, `.idx` and `.layer` against the baseline.

2. **Landing 2 merged 2026-10-24.** A render directory must carry one of the two documents: with neither, parity refuses with the re-render message; the legacy sidecar is still read. The measured fade no longer decides `scored` (ADR 0005): the floor comes from authored brightness, and a tick with no authored entry is not excluded. The baseline was regenerated - 1333 CTRY frames and 2876 INTRO frames - and the pre-change binary and the landing-2 binary produce semantically identical reports on both regenerated directories and on the legacy-only baseline render directory.

3. **Landing 3 merged 2026-10-24.** The Python adapter `python/stunt_reel/parity_artifacts.py` mirrors the port (records, validation, naming, the `--frames` mapping, retime document rewriting); `parity_inputs.py` was a thin shim at this point; the probe and sweep consume the adapter and drop their 320/185/16 and sidecar constants. Retime on a real CLI-written directory preserved 1333 ticks, film, geometry, palette and camera, synced the legacy sidecar and kept unknown keys. Verification: scoped ruff, mypy and parity tests green (72 passed); full Python suite 247 passed, 4 skipped; retime byte-compared against `build/tmp/a2-render/ctry`.

4. **Landing 4 merged 2026-10-24.** The render writer no longer writes the legacy `palette_controls.json` sidecar; parity still reads it from renders made before the record. The `parity_inputs.py` shim and its tests are deleted, and ADR 0010's validation-home sentence now points at the adapter alone. Verification: a three-tick render writes only `render.json` (no sidecar) with the same PNG/`.idx`/`.layer` bytes; the Python suite is green without the shim; the full `mise run check` runs at integration with unit C's deletion stage.
