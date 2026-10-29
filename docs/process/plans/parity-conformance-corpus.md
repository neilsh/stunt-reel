# Parity Conformance Corpus (unit E, design note)

Status: E1-E3 landed 2026-10-29; E4 (the page reader) is the stacked follow-up. This is the test half that unit A's brief
promised in §7 and never landed: `render_v1`, `capture_v1` and `report_v1` fixtures
read and rewritten by both adapters, plus the page bytes that sit beside them.

Owner: unassigned. One writer per file; the corpus is shared, read-only data.

## 1. Why

- [ADR 0011](../../adr/0011-parity-artifacts-are-a-versioned-port.md) makes
  [`crates/stunt-parity`](../../../crates/stunt-parity/) the single definition of the parity
  documents and says shared fixtures pin both adapters. No such fixture exists:
  `tests/fixtures/` holds only the palette, DOS-math and trajectory goldens, and
  [`tests/test_schema_contract.py`](../../../tests/test_schema_contract.py) covers Kaitai schemas.
- Both adapters are tested against their own inline literals, so a field renamed on one side is
  discovered only on a machine holding real `build/parity` artifacts.
- Parity is the repository's hot path: eight of the last thirty commits changed it.
- The pages beside a render are named by the port but decoded by hand in Python
  (`parity_probe.actor_pixels`, the raw `.idx` read in `parity_probe.render_region`,
  `parity_sweep.write_crops`), and the byte layout is pinned only by `plane_codec`'s Rust tests.

## 2. Settled decisions

| # | Decision | Choice |
|---|---|---|
| D1 | Corpus membership | `tests/fixtures/parity/v1/`: `render.json`, `meta.json`, `meta_legacy.json`, `report.json`, `pages/tick_00007.idx`, `pages/tick_00007.layer`. No legacy `palette_controls.json` (ADR 0005 retires it). |
| D2 | Authority and mutability | Python authors `meta.json`; Rust authors `render.json` and `report.json`; bytes are committed; tests never write fixtures. `v1/` may gain optional fields; a required change forks `v2/`. |
| D3 | What "pinned" means | Typed round-trip per side: read fixture → write through the adapter → read again → compare typed values. Floats use the combined tolerance below; unknown keys must be tolerated on read. Not byte equality. |
| D4 | Placement and wiring | Fixtures under `tests/fixtures/parity/v1/`; Rust tests in `crates/stunt-cli/src/parity_artifacts.rs`; Python tests in `tests/test_parity_conformance.py`; a section in [`tests/fixtures/README.md`](../../../tests/fixtures/README.md). No new mise task: `check-rust` and `check-py` already run both suites. |
| D5 | Evolution | Optional additions update v1 fixtures and tests without bumping `SCHEMA_VERSION`; making a field required forks `v2/` and bumps the version; v1 tests stay while v1 is accepted. |
| D6 | Corpus vs inline tests | Corpus: happy path, the legacy no-`schema_version` capture, and one narrowed-viewport page. Inline: palette-missing frame, unknown `schema_version` refusal, tick-order violation. |
| D7 | Comparator | Per-side helper, no new dependency. Rust: `assert_close` using `abs(a - b) <= 1e-6 * max(1.0, abs(a), abs(b))`, matching the house idiom in `fade.rs`, `loss.rs`, `mask.rs`, `report_diff.rs`. Python: `pytest.approx(rel=1e-6, abs=1e-9)`. |
| D8 | Page rider | Add `parity_artifacts.read_page(directory, tick, geometry) -> Page` carrying `indices`, `layers` and `geometry`, with `Page.actor_pixels()`; switch the four probe/sweep call sites; Rust needs no production change. |

## 3. The corpus

All paths are relative to `tests/fixtures/parity/v1/`. Every document carries
`schema_version: 1` unless noted. The geometry is deliberately tiny (4x3, viewport 2) so the
page files are hand-checkable.

### 3.1 `render.json` (Rust-authored)

```json
{
  "schema_version": 1,
  "film": { "name": "SYNTH.FLM", "flm_bytes": 17 },
  "geometry": { "width": 4, "height": 3, "viewport_rows": 2 },
  "ticks": [
    {
      "tick": 7,
      "palette": { "sky": 0, "brightness": 32768, "saturation": 32768 },
      "camera": { "eye": [0.0, 10.0, 50.0], "target": [0.0, 10.0, 0.0], "fov_degrees": 45.0, "roll_radians": 0.0 }
    },
    {
      "tick": 9,
      "palette": { "sky": 0, "brightness": 32768, "saturation": 32768 },
      "camera": { "eye": [0.0, 10.0, 55.0], "target": [0.0, 10.0, 0.0], "fov_degrees": 45.0, "roll_radians": 0.0 }
    }
  ]
}
```

### 3.2 `meta.json` (Python-authored, flat shape)

`CaptureSet` serialises through `CaptureDocument`: `film` is a string, geometry is flat
`width`/`height`, and frames carry the four port fields. Harness diagnostics are extra keys the
port ignores on read.

```json
{
  "schema_version": 1,
  "film": "SYNTH.FLM",
  "flm_bytes": 17,
  "frames": [
    { "ordinal": 1, "film_tick": 7, "frame_file": "tick_0001.idx", "palette_file": "palettes_0001.json", "palette_source": "measured" },
    { "ordinal": 2, "film_tick": 9, "frame_file": "tick_0002.idx", "palette_file": "palettes_0002.json" }
  ],
  "width": 4,
  "height": 3,
  "palette_source": "measured"
}
```

### 3.3 `meta_legacy.json` (Python-authored)

The same document with `schema_version`, `flm_bytes` and `palette_source` removed. The port
reads it as version 1 (ADR 0011); `film_tick` must stay, or the frame is rejected.

### 3.4 `report.json` (Rust-authored)

Identities from `Report::validate`: `reference_frames = frames + unmatched`,
`frames = scored_frames + excluded_frames`, scored means present exactly when
`scored_frames > 0`, and the I6 gate false when nothing scored. Frame 2 omits three optional
fields so `serde(default)` and Python's optional handling are exercised; a rewrite serialises
them as `null`, which is why the comparison is typed rather than byte-level.

```json
{
  "reference_frames": 3,
  "frames": 2,
  "unmatched": 1,
  "sky_indices": [228, 238],
  "mean_ssim": 0.74185,
  "min_ssim": 0.6125,
  "mean_iou": 0.83,
  "min_fade_level": 0.35,
  "mean_ssim_scored": 0.8712,
  "i6_gate": { "initial": false, "sign_off": false },
  "mean_iou_scored": 0.86,
  "mean_index_agreement_scored": 0.91,
  "mean_loss_by_class_scored": { "terrain": 0.02 },
  "scored_frames": 1,
  "excluded_frames": 1,
  "per_frame": [
    { "ordinal": 1, "film_tick": 7, "ssim": 0.8712, "iou": 0.86, "index_agreement": 0.91, "loss_by_class": { "terrain": 0.02 }, "fade_level": 0.41, "authored_fade_level": 0.4, "scored": true },
    { "ordinal": 2, "film_tick": 9, "ssim": 0.6125, "iou": 0.8, "fade_level": 0.31, "scored": false }
  ]
}
```

### 3.5 `pages/tick_00007.idx` and `.layer`

Render pages use the five-digit render stem (`tick_00007`), not the four-digit capture name.
The files span the **full** geometry (4x3), not the viewport: 12 index bytes, then 12
little-endian `u16` layers (24 bytes). `viewport_rows: 2` only narrows what consumers scan.

| Row | Indices | Layers | Meaning |
|---|---|---|---|
| 0 | 180 180 180 180 | 0 0 0 0 | sky, no draw |
| 1 | 0 40 40 0 | 0 16 16 0 | two actor pixels |
| 2 | 0 0 0 0 | 16 16 16 16 | outside the viewport; must be ignored |

Expected: `Page.actor_pixels()` returns `[5, 6]` (viewport offsets), while the Rust reader
returns all twelve layers including row 2. That difference is the narrowing rule, and it is why
the page is in the corpus.

## 4. The tests

### 4.1 Rust — `crates/stunt-cli/src/parity_artifacts.rs`

A `#[cfg(test)] mod conformance` that resolves the corpus through
`Path::new(env!("CARGO_MANIFEST_DIR")).join("../../tests/fixtures/parity/v1")` (the pattern in
`config.rs`). It must:

1. load `render.json` through the render reader; assert film identity, geometry including
   `viewport_rows`, and the tick-7 palette controls;
2. load `meta.json` through the capture reader; assert both frames and that the diagnostic keys
   are ignored; load `meta_legacy.json` and assert `schema_version == 1`;
3. read `report.json` through the adapter, re-serialise the typed `Report` with `serde_json`,
   re-read it, and compare field by field with `assert_close` on every float and nested float map;
4. read `pages/tick_00007` through `plane_codec::read_page_planes` with
   `Geometry { width: 4, height: 3, viewport_rows: Some(2) }`; assert 12 indices, 12 layers and
   the table in §3.5.

### 4.2 Python — `tests/test_parity_conformance.py`

Symmetrical, using the same files:

1. `read_render` → `write_render` into `tmp_path` → `read_render`: typed equality with
   `pytest.approx` on floats;
2. `read_capture` on `meta.json` (diagnostics tolerated) and on `meta_legacy.json`
   (version 1); `write_capture` of the typed set into `tmp_path` → read back → equality. The
   test does **not** assert that writing the typed set preserves diagnostics: the port does not
   carry them, and the retime path's raw-document preservation is tested in
   `tests/test_parity_artifacts.py`;
3. `read_report` → `write_report` → `read_report`: typed equality, `validate()` clean;
4. the page fixture through the **current** byte-level API — read the two files, decode the
   layers little-endian, and assert `actor_pixels(layer, geometry) == [5, 6]`. This keeps PR1
   self-contained; E4 rewrites the assertion through `read_page` in the same commit that adds it.

### 4.3 Proving the pin

In the PR body, record one mutation check: rename a field on one side (for example
`viewport_rows` in the Python geometry mapper) and show the conformance test failing, then
revert. A test that cannot fail pins nothing.

## 5. The page rider (E4)

```python
@dataclass(frozen=True)
class Page:
    indices: bytes
    layers: tuple[int, ...]
    geometry: Geometry

    def actor_pixels(self) -> list[int]: ...  # offsets within the viewport


def read_page(directory: Path, tick: int, geometry: Geometry) -> Page: ...
```

- Validate sizes exactly as `plane_codec` does (width*height indices, twice that for layers) and
  name the offending file in the error.
- Replace the four call sites: the index read at `parity_probe.py` (~line 150), the two layer
  reads that call `actor_pixels` (~lines 170 and 211), and `parity_sweep.write_crops` (~line 189).
- Delete the free `actor_pixels` once no caller uses it; the probe's crop path keeps its
  behaviour.
- Rust is unchanged: `plane_codec` already writes and reads the same bytes, and §4.1 pins them.

## 6. Non-goals

- No JSON-Schema generation or validation (ADR 0011 keeps that rejected until a second consumer
  appears).
- No change to writer behaviour, field names, or `SCHEMA_VERSION`.
- No fixture for the legacy `palette_controls.json` sidecar (ADR 0005 retires it).
- No new mise task, no corpus access, no writes outside `tmp_path` in tests.

## 7. Tasks and order

E1 → (E2 || E3), then E4. E1-E3 are one PR; E4 is a second, independently green PR.

| Task | Files (write scope) | Done when |
|---|---|---|
| E1 corpus | `tests/fixtures/parity/v1/**`, `tests/fixtures/README.md` | Six files match §3; provenance and the v1/v2 rule documented. |
| E2 Rust tests | `crates/stunt-cli/src/parity_artifacts.rs` (test module only) | `cargo test -p stunt-cli conformance` green, including the typed round-trip and the page. |
| E3 Python tests | `tests/test_parity_conformance.py` (new) | `pytest tests/test_parity_conformance.py` green; diagnostics and legacy version covered. |
| E4 page rider | `python/stunt_reel/parity_artifacts.py`, `python/scripts/parity_probe.py`, `python/scripts/parity_sweep.py`, their tests | Probe and sweep tests green; `read_page` used at the four sites; no byte-level reads left. |

Commit subjects: `test(parity): pin both artifact adapters with a shared corpus` (E1-E3) and
`refactor(parity): read render pages through one reader` (E4). Stage by path; never `git add -A`.

## 8. Verification

- While iterating: `mise run check-rust` and `mise run check-py`.
- Before handoff: `mise run check` (format, lint, typecheck, Rust and Python tests, rustdoc,
  no-default-features matrix).
- After a test run, `git status` must show the fixture files unchanged: tests read, never write.
- No test may require `corpus/`, `target_bin/` or `build/parity`.

## 9. Notes and risks

- The capture document is flat and has no `viewport_rows`; the page's geometry comes from
  `render.json`. Do not invent a narrowing field for captures.
- `FrameReport`/optional report fields serialise as `null` on rewrite; compare typed values.
- Fixture authoring: use the port types (a scratch test or snippet, not committed) or hand-write
  and prove via the tests. Either way, commit the bytes and record provenance in the README.
- If the corpus starts to drift into "golden output of the whole parity run", stop: it pins the
  wire contract, not a film.

## 10. References

- [A brief §7](architecture-deepening/A-render-artifact.md) — the unlanded fixture list.
- [ADR 0011](../../adr/0011-parity-artifacts-are-a-versioned-port.md) — the port and its adapters.
- [ADR 0005](../../adr/0005-parity-requires-the-render-sidecar.md) — the legacy sidecar window.
- [test fixtures README](../../../tests/fixtures/README.md) — inventory and conventions.
