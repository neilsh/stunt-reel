# Synthetic Test Fixtures (`tests/fixtures/`)

This directory contains committed, synthetically constructed minimal fixtures used by Rust and Python test suites. Because proprietary game data (`corpus/`) cannot be checked into the repository or downloaded in continuous integration environments, these mock fixtures ensure 100% offline, deterministic CI testing.

---

## Fixture Inventory

### 1. `synthetic_minimal.res` (72 bytes)
A synthetically constructed resource container conforming to `[fmt res]` and the binary offset layout discovered in `RIPRES.C`:
- **Header**: `RS` magic signature (2 bytes: `0x52, 0x53`) followed by `res_index` (`0x01`) and `item_count` (`0x03`); `item_count` equals `ofs_data / 4 - 2`.
- **Offset Table**:
  - `ofs[0] = 20` (`0x14`): Offset to the name table.
  - `ofs[1] = 40` (`0x28`): Offset to `PLANE.SOD` payload (16 bytes).
  - `ofs[2] = 56` (`0x38`): Offset to `PROP.SOD` payload (16 bytes).
  - `ofs[3] = 72` (`0x48`): Offset marking end-of-file.
- **Name Table**: Null-separated ASCII string list (`"PLANE.SOD\0PROP.SOD\0\0"`).
- **Payloads**: Deterministic test bytes verifying container offsets and payload slicing.

### 2. `synthetic_minimal.flm` (17 bytes)
A minimal film stream conforming to `[fmt flm]`:
- **Header**: ASCII `FILM` magic signature (4 bytes).
- **Slice 0** (header at 0x0004): `prev_slice_len` `0x0000`, `tick_duration` `0x01`, opcodes `0x80` (`var_set 0 = 0x9890`), `0x90` (`view_obj 0`), `0x98` (`clear_credits`), `0xFF` (`end_slice`).
- **Slice 1** (header at 0x000D): `prev_slice_len` `0x0009`, `tick_duration` `0x01`, opcode `0xFF` (`end_slice`).

### 3. `oracle_intro_trajectory.json`
Golden oracle trajectory snapshot conforming to `Seam 2: TrajectoryRecord` (`crates/stunt-core/src/contracts/trajectory.rs`):
- Holds evaluated `[I1]` records, not raw DOS axes. `build_synthetic_intro_flm` authors its slots in DOS axes to match: every `INTERP` stores the negated `x` and `y` of the position listed here, and the actor slot (slot 1) stores `rz = 0x8000` (a half turn about Z) so that `q_z180 * q` evaluates to the identity `rotation_quat` `[0, 0, 0, 1]` recorded below. The camera slot keeps `rz = 0`; its look direction is unaffected because `q_z180` fixes `+Z`.
- Contains a sequence of discrete simulation ticks (ticks 0 and 1). The ticks are 50 Hz cumulative ticks (slice $i$ at the sum of `tick_duration` over slices `0..=i`), not slice ordinals, of the film produced by `build_synthetic_intro_flm(2)` in `crates/stunt-core/tests/common/mod.rs` (test-only, not part of the library). Its slices are authored with `tick_duration` 0 and then 1, so slice $t$ lands on tick $t$. `compute_position_rmse` samples `FilmTimeline` at each oracle tick.
- Evaluates `CameraTransform` (`eye`, `target`, `fov_degrees`, `roll_radians`).
- Evaluates `ActorTransform` (`actor_id`, `model_name`, `rotation_quat`, `position_meters`, `state_mask`).
- Evaluates `AudioCue` events (`tick`, `sample_name`, `volume`, `pan`).
- Used to test serialization/deserialization and golden trajectory regression comparisons.

### 4. `synthetic_minimal.sod` (76 bytes)
A synthetically constructed minimal `.sod` bytecode model conforming to `[fmt sod]`:
- **Header**: 10 bytes (`OP_ID = 0x000c`, `bounding_size = 100`, `yoff = 0`, `scale = 1` ($0.5\text{ m}$), `collision = 0`).
- **Opcodes**:
  - `OP_VECTORS` (`0x0075`): 5 vertices uploading base triangular wing and inner coplanar decal triangle.
  - `OP_COLOR` (`0x0129`) + `OP_POLYZ` (`0x00f3`): Base facet (palette index 40).
  - `OP_COLOR` (`0x0129`) + `OP_POLYZ` (`0x00f3`): Overlapping coplanar decal facet (palette index 15) testing Invariant `[I5]`.
  - `OP_RETURN` (`0x0195`): Clean bytecode termination.

### 5. `synthetic_minimal.all` (84 bytes)
A synthetically constructed full-movie archive container conforming to `# [FMT-ALL-CHUNKS]` and `[fmt all]`:
- **Header**: 8 bytes (`num = 1`, `ids = [0x0001]`, `offsets = [0x00000008]`).
- **Payload**: Bundles `synthetic_minimal.sod` (76 bytes) as chunk `0x0001` (`MODEL_0001.SOD`).
- Used to verify end-to-end `.ALL` archive parsing, scene bundle assembly, and headless trajectory evaluation offline without requiring proprietary assets.

### 6. `synthetic_anchors.bin` (84 bytes)
A synthetically constructed 28-byte anchor-point table matching the `ANCHORPT.DAT` record layout consumed by `OP_TAP` (`0x022E`):
- **Record 0**: `x = 100`, `y = 0`, `z = 200`.
- **Record 1**: `x = 300`, `y = -500`, `z = 400`.
- **Record 2**: `x = 500`, `y = -32500` (boundary sentinel), `z = 600`.
- Remaining 22 bytes of each record are zero; the VM maps coordinates through `[-x, -y, z]` and decodes sentinel elevations as zero.

### 7. `synthetic_tap.sod` (38 bytes)
A minimal TAP display list referencing `synthetic_anchors.bin` by byte offset:
- **Header**: 10 bytes (`OP_ID = 0x000c`, `bounding_size = 100`, `yoff = 0`, `scale_index = 1`, `collision = 0`).
- **Opcodes**:
  - `OP_TAP` (`0x022e`): `reg_off = 0`, `count = 3`, anchor offsets `0, 28, 56` (variable-width operand form).
  - `OP_COLOR` (`0x0129`, palette index 40) then `OP_POLYZ` (`0x00f3`, 3 registers) and `OP_RETURN` (`0x0195`).
- Used by `sod_tap_test.rs` to prove variable operand width, anchor resolution, and non-degenerate polygon emission.

### 8. `synthetic_timeline.flm` (148 bytes)
A three-slice film exercising authored `tick_duration` and timeline sampling:
- **Slice 0** at tick 0 (`tick_duration = 0`): `max_obj = 2`, camera slot 0 (`view_obj 0`), actor slot 1 (`shape_id 1`), `ENGINE.VOC` cue, camera at `(0, 10, 50)` and actor at `(0, 10, 0)`.
- **Slice 1** at tick 2 (`tick_duration = 2`): camera to `(0, 10, 48)`, actor to `(0, 10, 2)`.
- **Slice 2** at tick 12 (`tick_duration = 10`): `view_obj 1` (camera cut), `WIND.VOC` cue, camera slot to `(0, 10, 40)`, actor remains at `(0, 10, 2)`.
- **Axes**: the coordinates above are the evaluated `[I1]` positions. The bytes are authored in DOS axes, so each `INTERP` opcode stores the negated `x` and `y` (`y = -10.0` is `0xFFF60000`, `x = 0` is unchanged) and the unchanged `z`. All rotations are zero; a zero DOS rotation evaluates to `q_z180 = [0, 0, 1, 0]`, which the timeline tests do not inspect and which fixes the `+Z` camera look axis.- Used by `crates/stunt-core/tests/flm_timeline_test.rs` to verify cumulative timestamps, interpolation, cut suppression, and audio-cue intervals.

### 9. `mode13h_palette.json`
A JSON array of 256 `[r, g, b]` triples: a dump of the Stunt Island master palette (`[I3]`) — 240 scene entries plus 16 UI entries, game-derived (see `crates/stunt-core/src/contracts/palette.rs`) — not a synthetic construction. `crates/stunt-core/src/contracts/palette.rs` asserts `MODE_13H_PALETTE` equals it exactly and `tests/test_goldens.py` asserts `stunt_reel.tac.palette` equals it, so the Rust and Python copies cannot drift.

### 10. `dos_math_goldens.json`
Golden vectors for the shared DOS math helpers, generated from the Python implementations at full float precision: `bam_to_radians`, `focal_to_fov_y`, `quat_from_euler` (`[yaw, pitch, roll]` -> `[x, y, z, w]`) and `world_matrix` (`position` + `quat` -> 16 column-major floats). Rust (`flm/interpolate.rs`, `contracts/trajectory.rs` tests) and Python (`tests/test_goldens.py`) both assert agreement within `1e-5`.

### 11. `synthetic_empty.flm` (4 bytes)
A film that is only the `FILM` magic: its header parses, but it holds zero slices. `crates/stunt-cli/src/scene.rs` and `export.rs` tests check that naming it is an error rather than a fall back to the synthetic orbit. The same tests cover a named path that does not exist and a named film with the wrong magic (`synthetic_minimal.sod`), which need no fixture of their own; the no-input case needs no file.

`crates/stunt-gltf/tests/export_test.rs` reuses `synthetic_minimal.all`, `synthetic_minimal.sod`, `synthetic_tap.sod` with `synthetic_anchors.bin`, and `synthetic_timeline.flm` to check exported `.glb` structure; it adds no fixtures of its own.

### 12. `synthetic_minimal.set` (282 bytes)
A synthetic scene exercising the three-record layout of `[FMT-SET-HEADER]`:
- **Header**: 84 bytes (`stunt_name` `"SYNTHETIC SET"`, `magic` `0x08` at `0x52`, `num_events = 2` at `0x53`).
- **Events**: two 67-byte records — `hits … Any Weapon` with `flag #3 =` and `wait 256` / `award $500` / `play` slots, then `500` ticks elapsed with one `explode` slot.
- **Prop**: one 64-byte record (`prop_slot_id = 0`, `behavior_flags = 0x09`, `placement_flags = 0x01`, `object_model_id = 0x0102`, `override_flags = 0x40`).
- Used by `tests/test_set_schema.py` to prove the schema consumes the header, the `num_events`-driven events and the trailing prop stride offline, and rejects a byte-truncated file.

### 13. `parity/v1/` (parity conformance corpus)

The shared wire-contract corpus for the two parity artifact adapters: the Rust port in `crates/stunt-parity` and the Python mirror in `python/stunt_reel/parity_artifacts.py` (see [ADR 0011](../../docs/adr/0011-parity-artifacts-are-a-versioned-port.md)). It pins the documents, not a run; the geometry is deliberately tiny (4x3 with a 2-row viewport) so the page bytes are hand-checkable.

| File | Pins |
|---|---|
| `render.json` | The Rust render document (`RenderRecord`): film `SYNTH.FLM` at 17 bytes, 4x3 geometry with `viewport_rows: 2`, and ticks 7 and 9 with palette controls `{sky 0, brightness 32768, saturation 32768}` and their camera poses. |
| `meta.json` | The Python capture document (`CaptureSet`): flat `film`/`flm_bytes`, two frames at film ticks 7 and 9, `width` 4 and `height` 3, plus the harness's `palette_source` diagnostics the port ignores on read. |
| `meta_legacy.json` | A pre-port capture: the same document with `schema_version`, `flm_bytes` and `palette_source` removed. It must read as version 1 with both `film_tick` values intact; a frame without one is rejected, so parity can still pair it with a render. |
| `report.json` | The Rust report document (`Report`): `reference_frames 3 = frames 2 + unmatched 1`, `frames 2 = scored_frames 1 + excluded_frames 1`, the I6 gate closed, and a second frame that omits `index_agreement`, `loss_by_class` and `authored_fade_level` so `serde(default)` and Python's optional handling are exercised. A rewrite serialises those as `null`, so comparisons are typed, never byte-level. |
| `pages/tick_00007.idx` | 12 index bytes over the full 4x3 raster, row-major: row 0 all sky (180), row 1 `0 40 40 0` (two actor pixels), row 2 `0 0 0 0`. Named with the five-digit render stem, not a capture's four-digit ordinal. |
| `pages/tick_00007.layer` | 12 little-endian `u16` layers (24 bytes): row 0 none, row 1 `0 16 16 0` (actor layer 16), row 2 `16 16 16 16` — outside the 2-row viewport, so consumers that scan the viewport must ignore it while the Rust reader returns all twelve. |

**Authorship.** Python authors `meta.json` and `meta_legacy.json` by building a `CaptureSet` and calling `write_capture`; Rust authors `render.json` and `report.json`, which are the port's own documents. The bytes are committed, and a change to a document is made on its authoring side while both adapters are re-run against the result.

**Evolution.** v1 may gain optional fields in place: a reader that uses `serde(default)` or `.get(...)` tolerates them, and the fixtures and both conformance tests are updated without touching `SCHEMA_VERSION`. A required change — a new required field, a rename, or a changed shape — forks `tests/fixtures/parity/v2/` and bumps `SCHEMA_VERSION`; the v1 fixtures and tests stay while v1 is accepted.

**Read-only.** The conformance tests read these files and never write them; round-trip tests write to their own temporary directories. `git status` after a test run must show the corpus unchanged.


### 14. `parity/video/` (video capture document)

A synthetic video capture directory holding only `meta.json`: the `VideoCapture` document (`kind` `video`) for film `SYNTH.FLM`, a 4x2 raster, a four-row tick log (frames 101 to 104, film ticks 7, 7, 8, 9, so `film_start_frame` is 103) and a palette history of a 256-entry grey-ramp `initial` plus one 32-entry red change at frame 103. There is no `capture.avi` and no game data; the Rust loader (`load_video_capture`) and the Python loader (`load_video_capture`) both read it in their conformance tests.

`parity/video/synthetic.avi` (22 KB) is a ZMBV recording the Rust decoder (`crates/stunt-cli/src/zmbv.rs`) is tested against: 12 frames of 64x48 `bgr0`, one keyframe (16x16 blocks, zlib) followed by delta frames. Frame `n`, pixel `(x, y)` is `[(x*4 + n*3) & 255, (y*5) & 255, ((x + y + n*7)*2) & 255, 0]`, plus an 8x8 block of `[255, 255, 255, 0]` at `(4 + 3n, 4 + 2n)`. It was made by writing those frames raw to `frames.raw` and running `ffmpeg -f rawvideo -pix_fmt bgr0 -s 64x48 -framerate 70 -i frames.raw -c:v zmbv -g 5 synthetic.avi`; the gate never runs ffmpeg. `zmbv::tests::the_synthetic_fixture_decodes_exactly` rebuilds the frames from the formula and compares byte for byte. FFmpeg's encoder emitted a single keyframe in spite of `-g 5`, so delta handling is covered by the later frames and by a hand-built raw delta test.

### 15. `parity/bench/` (parity bench, numpy against Rust)

Two film ticks (10 and 20) of 320x200 content, for the numpy copy of the scorer in `python/stunt_reel/bench/`. Rows 0-59 are sky (indices 227-238 cycling by row), rows 60-184 terrain (layer 2) in an 8-pixel checker of indices 40 and 41, a 20x16 actor (index 16, layer 16) sits at x 100, y 120, and rows 185-199 are a bar of index 250. The capture palette gives entry `i` the colour `(i, 255 - i, i // 2)`.

| Path | Holds |
|---|---|
| `capture/` | The reference: `meta.json` (via `write_capture`), `tick_0001.idx`, `tick_0002.idx` and `palettes_0001.json`, `palettes_0002.json`. At tick 20 the actor is 4 columns to the right. |
| `render/` | The test render: `render.json` (via `write_render`) and `tick_00010`, `tick_00020` as `.png`, `.idx`, `.layer` (little-endian `u16`). Each PNG is the capture palette scaled by 0.9 and rounded, so neither tick scores 1.0 and the golden tests the arithmetic, not just identity. |
| `render_before/` | `render/` with the terrain checker phase flipped at tick 20, the "before" side of a regression pair. |
| `golden.json` | `{"ssim": {"10": ..., "20": ...}}`: each frame's `ssim` from the Rust scorer. |

**Authorship.** `make_fixture.py` (run with `mise exec -- uv run python tests/fixtures/parity/bench/make_fixture.py`) writes the three directories. `golden.json` comes from `cargo run -p stunt-cli --release -- parity --reference tests/fixtures/parity/bench/capture --test tests/fixtures/parity/bench/render --output <tmp>`, copying `film_tick` and `ssim` from the report's `per_frame`.

**Pinned by.** `bench_fixture_matches_its_golden_ssim` (Rust, within 1e-6) keeps the golden equal to the real scorer; `tests/test_bench_ssim.py::test_numpy_ssim_matches_the_rust_golden` (within 1e-4) keeps numpy equal to the golden. `.gitattributes` marks `*.idx` and `*.layer` binary, since an index plane with no NUL byte would otherwise be treated as text and have its `0x0D 0x0A` pairs rewritten.
