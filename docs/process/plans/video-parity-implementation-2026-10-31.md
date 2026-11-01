# Video Parity Implementation Plan (parts 1–3)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Record each film as one dosbox-automation AVI with a tick and palette log, and score it per
film second against a render, beside the existing per-frame scorer.

**Architecture:** Python generates the Lua, runs it, strips the audio stream and writes the capture
document; Rust decodes the ZMBV video, samples frames per film second, searches a tick window per
sample, fits one film offset and writes a per-second report. Document types live in `stunt-parity`
(ADR 0011); file access and decoding live in the adapters.

**Tech Stack:** Python 3.12 standard library; Rust (`stunt-parity`, `stunt-cli`, new direct
dependency `flate2 = "1.1"`, already in `Cargo.lock` at 1.1.10); dosbox-automation (pinned in
`mise.toml`); ffmpeg only to make one committed fixture and for a one-off check.

**Spec:** [`video-parity-2026-10-31.md`](video-parity-2026-10-31.md). Parts 4 (switch) and 5
(retirement) get their own plan after Task 11 decides whether to switch.

## Global Constraints

- `stunt-core` is untouched ([I7]); `stunt-parity` stays types and validation only, no I/O (ADR 0011).
- The Python package stays dependency-free (`dependencies = []`); `parity_artifacts.py` is standard
  library only.
- `mise run check` needs neither ffmpeg nor the corpus; every test runs offline on committed or
  generated synthetic data ([`tests/fixtures/README.md`](../../../tests/fixtures/README.md)).
- Lua: no per-byte loops (instruction limit); every string written to `dosbox.output` starts with a
  letter (numeric-looking strings are coerced).
- The frame-capture path (`capture-ref`, `meta.json` frame captures, per-frame `report.json`) keeps
  working unchanged.
- Values from the spec: capture profile `capture` (dynamic core, 45,000 cycles); window `t - 8` to
  `t + 2`; three samples per second at film-second offsets 0, 17 and 33 ticks; `slip` when the local
  offset differs from the film offset by more than 2 ticks; sky indices 227–238; sky tolerance 2 frames
  after a palette change; [I6] thresholds 0.88 and 0.90; overlay is rows 185–199.
- Each task: `mise run check-py` or `mise run check-rust` while iterating, `mise run check` before its
  commit; stage paths by name; Conventional Commit subject with a why-body ending
  `mise run check passes.` (AGENTS.md SOP 3).
- Work on a branch from `main`; the first commit carries the two plan notes and this plan.

## Deviations from the Spec

1. **Per-second results go to `seconds.json`, not a new `report.json` version.** Every current reader
   of `report.json` (`report_diff`, `batch_stages`, the sweep and probe scripts, Python `Report`)
   assumes per-frame rows; a separate document lets both scorers coexist until part 4 picks one.
2. **Inspection is `--inspect-second S` on the scoring run, not a `parity inspect` subcommand**, and
   the default sheets are the five lowest seconds rather than one row per second. Adding a clap
   subcommand would change how `stuntreel parity --reference ...` parses today.
3. **Palette changes are logged as 32-entry bands** (8 per palette), not single entries. Comparing 256
   entries per changed frame risks the Lua instruction limit; 8 band compares do not (24 bands of page
   rows already fit). The document stores runs (`first`, `rgb[]`), so finer logging stays possible.
4. **The post-run check allows the video to differ from the log by one frame**, not zero. Video frame
   *j* is emulated frame `capture_start_frame + j` (research § 3), and each log row is taken after a
   one-frame wait, so the first and last rows can sit one frame off the recording's ends. Task 6
   records the relation actually seen.

## Review Focus

1. **A film whose clock never starts** (an unpatched build that never plays the film, clock stuck at
   one value): `capture-video` must fail with "the film clock never moved" and free its run number,
   not store a recording of the dialog. Test in Task 2.
2. **A recording cut short** (emulator killed, timeout): an AVI with a truncated `movi` list or no
   `idx1` must make `video_only` raise, and the run directory must be removed. Test in Task 3.
3. **Render shorter than the capture** (window ticks missing from the render directory): missing
   ticks are skipped; a second with no render tick in any sample's window is counted `unmatched`, not
   an error. Test in Task 9.
4. **Zero-length video chunks** (AVI's "repeat the previous frame"): the decoder must yield the
   previous frame for each, keeping video indices aligned with log rows. Test in Task 5.
5. **No sample finds a match inside the window** (every best offset on a bound): the run fails with
   a message naming `--window-before`/`--window-after` instead of reporting a film offset of nothing.
   Test in Task 9.

---

## Part 1: Video Capture and Decoder

### Task 1: Video capture document in the port

**Files:**
- Create: `crates/stunt-parity/src/video.rs`
- Modify: `crates/stunt-parity/src/lib.rs`, `crates/stunt-parity/src/error.rs`
- Modify: `python/stunt_reel/parity_artifacts.py`
- Modify: `crates/stunt-cli/src/parity_artifacts.rs` (loader)
- Create: `tests/fixtures/parity/video/meta.json`; Modify: `tests/fixtures/README.md`
- Test: `crates/stunt-parity/src/video.rs` (unit), `crates/stunt-cli/src/parity_artifacts.rs` (fixture),
  `tests/test_parity_artifacts.py`

**Interfaces:**
- Produces (Rust, `stunt_parity`): `VideoCapture { schema_version: u32, kind: String, film: FilmId, geometry:
  Geometry, playone_build: String, cpu_profile: String, capture_start_frame: u64,
  film_start_frame: u64, end: CaptureEnd, log: TickLog, palettes: PaletteLog }`;
  `enum CaptureEnd { Hold, Capped }` (serde lowercase); `TickLog { frame: Vec<u64>, film_tick:
  Vec<u32>, global_tick: Vec<u32> }`; `PaletteLog { initial: Vec<[u8; 3]>, changes:
  Vec<PaletteChange> }`; `PaletteChange { frame: u64, first: u16, rgb: Vec<[u8; 3]> }`;
  `VideoCapture::validate(&self) -> Result<(), ArtifactError>`;
  `VideoCapture::video_index(&self, frame: u64) -> Option<usize>` (`frame - capture_start_frame`);
  `pub const VIDEO_FILE: &str = "capture.avi"`; new `ArtifactError::VideoLog { reason: String }`
  ("video log: {reason}").
- Produces (Rust adapter): `parity_artifacts::load_video_capture(dir: &Path) ->
  Result<VideoCapture, AdapterError>` (reads `meta.json`, validates).
- Produces (Python): frozen dataclasses `VideoCapture`, `TickLog`, `PaletteLog`, `PaletteChange`
  with the same fields; `VIDEO_FILE = "capture.avi"`; `write_video_capture(directory: Path, capture:
  VideoCapture, *, diagnostics: Mapping[str, Any]) -> dict[str, Any]` (writes `meta.json` last, same
  diagnostics rule as `write_capture`); `load_video_capture(directory: Path) -> VideoCapture`.

`meta.json` shape (the fixture; `film` nested as in `render.json`, `kind` fixed):

```json
{"schema_version": 1, "kind": "video",
 "film": {"name": "SYNTH.FLM", "flm_bytes": 4, "flm_sha256": "00"},
 "geometry": {"width": 4, "height": 2},
 "playone_build": "synthetic", "cpu_profile": "capture",
 "capture_start_frame": 100, "film_start_frame": 102, "end": "hold",
 "log": {"frame": [101, 102, 103, 104], "film_tick": [7, 7, 8, 9], "global_tick": [0, 1, 2, 3]},
 "palettes": {"initial": [[0, 0, 0], "... 256 entries ..."],
              "changes": [{"frame": 103, "first": 32, "rgb": [[255, 0, 0], "... 32 entries ..."]}]}}
```

- [ ] **Step 0: Branch and commit the plan notes.** From `main`, branch `feat/video-parity`; commit
  the two plan notes and this plan as `docs(process): plan video parity`.
- [ ] **Step 1: Write the failing tests.** Rust unit tests in `video.rs`:
  `a_valid_log_passes`; `a_kind_other_than_video_is_rejected` (a frame capture's `meta.json` has no
  `kind` and fails with `MissingField`; `"kind": "frames"` fails with `VideoLog`);
  `columns_of_different_length_are_rejected`;
  `frames_must_ascend_by_one` (101, 103 fails, naming index 1);
  `film_tick_may_not_fall_after_the_film_starts` (rows after `film_start_frame` 9 then 8 fails with
  `VideoLog` naming the frame); `film_start_frame_must_be_a_logged_frame`;
  `the_initial_palette_has_256_entries`; `a_change_must_fit_inside_256_entries` (`first` 250 with 32
  entries fails); `changes_must_ascend_and_lie_in_the_log`;
  `video_index_counts_from_the_capture_start` (`video_index(101) == Some(1)`, `video_index(99) ==
  None`). Adapter test `the_video_fixture_loads` reads `tests/fixtures/parity/video/meta.json` and
  asserts 4 rows and one change at frame 103. Python `test_video_capture_round_trips` writes a
  `VideoCapture` with `write_video_capture` and reads it back equal, and
  `test_the_video_fixture_loads` reads the same fixture.
- [ ] **Step 2: Run them and see them fail.** `cargo test -p stunt-parity video` and
  `mise exec -- uv run pytest tests/test_parity_artifacts.py -k video -q`: FAIL (types missing).
- [ ] **Step 3: Implement the types, validation and both adapters.** Mirror the existing
  `CaptureSet` style: serde derive in Rust, unknown fields ignored because diagnostics ride beside the
  port's fields; hand-written validation in Python via the `_as_*` helpers; geometry validated through
  `Geometry::validate`; `kind` must equal `"video"` on both sides.
- [ ] **Step 4: Run the tests and see them pass.** Same commands: PASS.
- [ ] **Step 5: Document the fixture** in `tests/fixtures/README.md` (a 4x2 synthetic video log, no
  game data) **and commit** `feat(parity): add the video capture document`.

### Task 2: Lua video script and log decoding

**Files:**
- Modify: `python/stunt_reel/tac/luagen.py`
- Create: `python/stunt_reel/tac/video.py`
- Test: `tests/test_tac_video.py`

**Interfaces:**
- Consumes: `luagen._keys_lua`, `luagen.boot_end`, `PlayoneLayout` (`ds`, `film_clock`,
  `global_tick`, `working_palette`), `plan.palette_rgb`.
- Produces: `luagen.video_script(*, keys: Sequence[str], cap: int, end_hold: int, layout:
  PlayoneLayout) -> str`; `luagen.PALETTE_BANDS: int = 8`;
  `video.VIDEO_MAX_FRAMES: int = 30000` (7.1 min at 70.09 Hz; the longest survey film is about 257 s);
  `video.decode_video_log(output: Mapping[str, Any]) -> VideoLog`, where `VideoLog` is a frozen
  dataclass `{capture_start_frame: int, end: str, log: TickLog, palettes: PaletteLog}`;
  `video.film_start_frame(log: TickLog) -> int` (the first row whose `film_tick` differs from the row
  before it; raises `VideoCaptureError("the film clock never moved")` when none does);
  `class VideoCaptureError(RuntimeError)`; `plan.dac_rgb(units: bytes) -> list[RGB]` (any multiple
  of 3 bytes; `plan.palette_rgb` becomes a call to it).

The script, after the boot keys (same `wait_until`, `H` hex table and `DS` preamble as `script`):

```lua
dosbox.capture_start()
out.cs = "x" .. dosbox.frame()
out.pal0 = "x" .. dosbox.mem_read(DS, <working_palette>, 768):gsub(".", H)
local tr, pl, lt, hold, ppal = {}, {}, -1, 0, <palette read>
out["end"] = "xcapped"
for i = 1, <cap> do
  dosbox.wait_frames(1)
  local f = dosbox.frame()
  local t = <film clock word>; local g = <global tick word>
  tr[#tr + 1] = f .. ":" .. t .. ":" .. g
  local pal = <palette read>
  if pal ~= ppal then
    for b = 0, 7 do
      local s = pal:sub(b * 96 + 1, b * 96 + 96)
      if s ~= ppal:sub(b * 96 + 1, b * 96 + 96) then pl[#pl + 1] = f .. ":" .. b .. ":" .. s:gsub(".", H) end
    end
    ppal = pal
  end
  if t == lt then hold = hold + 1 else hold = 0; lt = t end
  if t > 0 and hold >= <end_hold> then out["end"] = "xhold"; break end
end
dosbox.capture_stop()
out.log = "x" .. table.concat(tr, ",")
out.pal = "x" .. table.concat(pl, ",")
out.done = true
```

`decode_video_log` turns each band into `PaletteChange(frame, first=band * 32, rgb=...)` and `pal0`
into `PaletteLog.initial`, scaling every 6-bit value with `round(v * 255 / 63)`, the rule
`plan.palette_rgb` applies (that helper takes only a whole 768-byte palette, so add a length-agnostic
`plan.dac_rgb(units: bytes) -> list[RGB]` and have `palette_rgb` call it).

- [ ] **Step 1: Write the failing tests.** `test_video_script_logs_rows_and_palette_bands` (the text
  contains `dosbox.capture_start()`, `dosbox.capture_stop()`, the layout's film-clock offset and
  `for b = 0, 7`); `test_video_script_rejects_a_cap_below_one`; `test_decode_video_log_reads_rows`
  (output `{"cs": "x100", "log": "x101:7:0,102:7:1,103:8:2", "pal0": "x" + "00" * 768, "pal": "x",
  "end": "xhold", "done": True}` gives frames `[101, 102, 103]`, `end == "hold"`, no changes);
  `test_a_palette_band_becomes_a_32_entry_change` (band `1` at frame 103 of all `3f` gives
  `first == 32` and 32 entries of `(255, 255, 255)`); `test_film_start_is_the_first_moving_row`
  (`[7, 7, 8]` gives the frame of the third row); `test_a_clock_that_never_moves_is_an_error`
  (Review Focus 1).
- [ ] **Step 2: Run and see them fail.** `mise exec -- uv run pytest tests/test_tac_video.py -q`.
- [ ] **Step 3: Implement** `video_script`, `decode_video_log`, `film_start_frame`.
- [ ] **Step 4: Run and see them pass.**
- [ ] **Step 5: Commit** `feat(tac): generate and decode the video capture log`.

### Task 3: AVI audio stripping

**Files:**
- Create: `python/stunt_reel/avi.py`
- Modify: `tests/pytest_helpers.py` (`build_avi`, shared with Task 4)
- Test: `tests/test_avi.py`

**Interfaces:**
- Produces: `avi.video_only(src: Path, dst: Path) -> int` (writes an AVI holding only stream 00's
  video chunks; returns their count); `class AviError(ValueError)`.

Rewrite rules: keep `avih` with `dwStreams = 1`; keep the `strl` whose `strh` type is `vids` and
require it to be stream 0; keep `movi` chunks with id `00dc` or `00db` (zero-length ones included);
rebuild `idx1` from the kept chunks, keeping each one's original flags (match by offset), offsets
relative to the `movi` fourcc; drop everything else. Refuse a second `RIFF AVIX` (OpenDML, over 1 GB),
a missing `idx1`, or a chunk that runs past its list.

- [ ] **Step 1: Write the failing tests.** A helper in `tests/pytest_helpers.py`,
  `build_avi(video: list[bytes], audio: list[bytes]) -> bytes`, assembles a minimal RIFF (avih, vids and auds `strl`, interleaved `movi`,
  `idx1` with keyframe flag `0x10` on the first video chunk). Tests:
  `test_video_only_keeps_video_chunks_in_order` (3 video + 3 audio in, returns 3, re-parsed `movi`
  holds only `00dc` with the same payloads); `test_video_only_keeps_keyframe_flags`;
  `test_video_only_sets_one_stream`; `test_zero_length_video_chunks_are_kept`;
  `test_a_truncated_movi_is_refused` and `test_a_missing_idx1_is_refused` (Review Focus 2);
  `test_an_opendml_continuation_is_refused`.
- [ ] **Step 2: Run and see them fail.** `mise exec -- uv run pytest tests/test_avi.py -q`.
- [ ] **Step 3: Implement** `video_only` with `struct`.
- [ ] **Step 4: Run and see them pass.**
- [ ] **Step 5: Commit** `feat(avi): strip the audio stream from a capture recording`.

### Task 4: `capture-video` task

**Files:**
- Modify: `python/stunt_reel/tac/staging.py` (`StagedMount.write_conf` gains `capture_dir: Path |
  None = None`, passed to `render_conf`)
- Modify: `python/stunt_reel/tac/video.py`, `python/stunt_reel/parity_layout.py`
- Create: `python/scripts/capture_video.py`; Modify: `mise.toml` (`[tasks.capture-video]`)
- Modify: `docs/adr/0024-captures-are-filed-by-film-then-kind.md` (add the `video` kind)
- Test: `tests/test_tac_video.py`, `tests/test_parity_layout.py`

**Interfaces:**
- Consumes: Task 1 `VideoCapture`, `write_video_capture`, `VIDEO_FILE`; Task 2 `video_script`,
  `decode_video_log`, `film_start_frame`, `VIDEO_MAX_FRAMES`; Task 3 `video_only`;
  `framebuffer.END_HOLD_FRAMES` (30); `runs.claim_run`.
- Produces: `parity_layout.video_root(slug: str) -> Path` (`build/parity/captures/<slug>/video`),
  `parity_layout.video_path(slug: str, run: str) -> Path`;
  `video.record_video(open_runner: Callable[[], AbstractContextManager[ScriptRunner]], out_dir: Path,
  recording_dir: Path, *, keys: Sequence[str], layout: PlayoneLayout, film: FilmId, provenance:
  Mapping[str, str], cap: int = VIDEO_MAX_FRAMES) -> VideoCapture`.

`record_video` runs the script, takes the single `*.avi` in `recording_dir` (error if none or
several), writes `out_dir / VIDEO_FILE` with `video_only`, requires `abs(video_frames - rows) <= 1`,
and writes `meta.json` last with diagnostics `video_frames`, `rows`, `palette_changes`,
`dgroup_segment`, plus provenance. `capture_video.py` mirrors `capture_playone_reference.py`
(`--film`, `--name`, `--out`, `--game-root`, `--max-frames`; run claimed with `runs.claim_run` under
`video_root(slug)` and removed when `meta.json` is missing), with the recording directory inside the
stage so `unstage` deletes the raw AVI.

- [ ] **Step 1: Write the failing tests.** `test_video_paths_sit_beside_frames`;
  `test_record_video_writes_meta_last_and_strips_audio` (`contextlib.nullcontext` around a
  `MockAutomation` whose handler writes a `pytest_helpers.build_avi` file with audio into
  `recording_dir` and returns a raw Lua output like Task 2's; asserts
  `capture.avi` has no `01wb` chunk, `meta.json` loads with `load_video_capture`, `end == "hold"`);
  `test_record_video_refuses_a_frame_count_mismatch` (rows 5, video 3);
  `test_record_video_refuses_no_recording`.
- [ ] **Step 2: Run and see them fail.**
- [ ] **Step 3: Implement** the layout helpers, `write_conf(capture_dir=...)`, `record_video`, the
  script and the mise task (description: "Record a film as one AVI with its tick and palette log into
  captures/<film>/video/ (mise run capture-video -- --film corpus/stisldem/VAULT/CTRY.FLM)"). Amend
  ADR 0024's Decision with one bullet for `captures/<film>/video/<run>/`.
- [ ] **Step 4: Run and see them pass.**
- [ ] **Step 5: Commit** `feat(tac): add the capture-video task`.

### Task 5: AVI reader and ZMBV decoder in Rust

**Files:**
- Create: `crates/stunt-cli/src/avi.rs`, `crates/stunt-cli/src/zmbv.rs`; Modify:
  `crates/stunt-cli/src/main.rs` (`mod` lines), `crates/stunt-cli/Cargo.toml` (`flate2 = "1.1"`)
- Create: `tests/fixtures/parity/video/synthetic.avi`; Modify: `tests/fixtures/README.md`
- Test: unit tests in both files

**Interfaces:**
- Produces: `avi::read_video(bytes: &[u8]) -> Result<AviVideo, AviError>` with `AviVideo { width:
  u32, height: u32, chunks: Vec<std::ops::Range<usize>> }` (stream 00 video chunks in order, other
  streams skipped); `zmbv::Decoder::new(width: u32, height: u32) -> Self`;
  `zmbv::Decoder::decode(&mut self, chunk: &[u8]) -> Result<&[u8], ZmbvError>` returning the current
  frame as `bgr0` bytes (4 per pixel, row-major); an empty chunk returns the previous frame;
  `avi::decode_frames(bytes: &[u8], mut visit: impl FnMut(usize, &[u8]) -> Result<(), String>) ->
  Result<usize, String>` (decodes every frame in order, calls `visit(index, bgr0)`, returns the
  count).

Decoder, after FFmpeg's `libavcodec/zmbv.c` (32-bit path):

```text
byte 0: flags; bit 0 = keyframe. Keyframe header bytes 1..6: version 0, 1; compression (0 raw,
1 zlib); format (must be 8 = 32 bpp); block width; block height. With zlib, a keyframe starts a new
stream (flate2::Decompress::new(true)) and later frames continue it (FlushDecompress::Sync); with
compression 0 the payload is stored as is.
Keyframe payload: width*height*4 bytes, the frame.
Delta payload: per block (row-major, ceil(w/bw) * ceil(h/bh)), two bytes: dx = (b0 as i8) >> 1,
xor = b0 & 1, dy = (b1 as i8) >> 1; the table is padded to a multiple of 4 bytes. Then, block by
block, copy the previous frame's block offset by (dx, dy), pixels outside the frame read as 0; if
xor, XOR the next bw'*bh'*4 bytes onto it (bw', bh' clipped at the right and bottom edges).
```

- [ ] **Step 1: Make the fixture.** 12 frames of 64x48 `bgr0`, frame `n` pixel `(x, y)` =
  `[(x*4 + n*3) & 255, (y*5) & 255, ((x + y + n*7)*2) & 255, 0]` plus an 8x8 block of
  `[255, 255, 255, 0]` at `(4 + 3n, 4 + 2n)`; write them raw and run
  `ffmpeg -f rawvideo -pix_fmt bgr0 -s 64x48 -framerate 70 -i frames.raw -c:v zmbv -g 5 synthetic.avi`.
  Record the formula and command in the fixtures README.
- [ ] **Step 2: Write the failing tests.** `zmbv::tests::the_synthetic_fixture_decodes_exactly`
  (every decoded frame equals the formula); `the_fixture_has_keyframes_and_deltas` (frame 0 is a
  keyframe and at least one later frame is a delta); `raw_keyframes_decode` (a hand-built keyframe
  with compression 0); `an_empty_chunk_repeats_the_previous_frame` (Review Focus 4);
  `an_unsupported_format_is_an_error` (format byte 4); `a_delta_before_any_keyframe_is_an_error`;
  `avi::tests::other_streams_are_skipped` (a hand-built RIFF with `01wb` chunks yields only video
  ranges); `a_chunk_past_its_list_is_an_error`.
- [ ] **Step 3: Run and see them fail.** `cargo test -p stunt-cli -- zmbv avi`.
- [ ] **Step 4: Implement** `avi.rs` and `zmbv.rs`.
- [ ] **Step 5: Add the ignored real-capture check** `zmbv::tests::matches_ffmpeg_on_a_real_capture`
  (`#[ignore]`; reads `STUNT_ZMBV_AVI` and `STUNT_ZMBV_RAW`, the latter from
  `ffmpeg -i capture.avi -f rawvideo -pix_fmt bgr0 out.raw`, and compares byte for byte).
- [ ] **Step 6: Run and see them pass; commit** `feat(parity): decode ZMBV video captures`.

### Task 6: Live checks for part 1

Needs the emulator and the corpus; nothing here runs in the gate.

**Files:**
- Modify: `research/playone-exe/capture-dosbox-automation.md` (new § 4.6)
- Create (if it qualifies): `tests/fixtures/parity/video/dosprompt.avi`; Modify:
  `tests/fixtures/README.md`

- [ ] **Step 1:** `mise run capture-video -- --film corpus/stisldem/VAULT/CTRY.FLM` and the same for
  `INTRO.FLM`. Expected: `captures/<slug>/video/001/` with `capture.avi` and `meta.json`, `end` is
  `hold`, `video_frames` within 1 of `rows`.
- [ ] **Step 2:** Run the ignored decoder check on the `CTRY.FLM` capture:
  `STUNT_ZMBV_AVI=... STUNT_ZMBV_RAW=... cargo test -p stunt-cli matches_ffmpeg -- --ignored`.
  Expected: PASS.
- [ ] **Step 3:** Check whether dosbox-automation can record video without audio (its capture conf
  keys and `POST /api/v1/capture/video/start` options). Record the answer; `video_only` stays either
  way, since it also counts frames.
- [ ] **Step 4:** Record about 30 frames at the DOS prompt with a scrolling `dir`; if `ffprobe`
  reports `bgr0`, commit it as `dosprompt.avi` with a decode test
  `zmbv::tests::the_dos_prompt_recording_decodes` (frame count and dimensions, and a 64-bit FNV-1a of
  the first frame, computed in the test, equal to the committed value). If text mode records another
  format, skip it and say why in the README.
- [ ] **Step 5:** Measure, by scratch script: the `pal` output size for the two films with the most
  palette changes in a 10-capture sample of the existing frame captures (`collage3-col3-1` and
  `flmonly-collisn`; each `meta.json` names its film), recorded with `capture-video`, against the Lua
  heap (about 11.5 MB of output failed); and sky-colour clashes (a non-sky index whose RGB equals an
  entry of 227–238) over every palette in the existing frame captures.
- [ ] **Step 6:** Write § 4.6 (the frame-count relation between rows and video, audio option,
  decoder check, palette log size, sky clashes) with evidentiary tiers, then commit
  `docs(research): record the live video capture checks`.

## Part 2: Segment Scorer

### Task 7: RGB reference scoring helpers

**Files:**
- Modify: `crates/stunt-cli/src/parity/frames.rs`, `mask.rs`, `score.rs`
- Create: `crates/stunt-cli/src/parity/video.rs`; Modify: `crates/stunt-cli/src/parity/mod.rs`
  (`mod video;`)
- Test: unit tests in each

**Interfaces:**
- Consumes: Task 1 `VideoCapture`, `PaletteLog`; Task 5 `avi::decode_frames`.
- Produces:
  - `frames::rgb_luminance(rgb: &[[u8; 3]]) -> Vec<f32>` (Rec. 601, stretched to 320x240);
    `reference_luminance` becomes a call to it.
  - `mask::bar_overlay_mask() -> Vec<bool>` (rows 185–199 of 320x200);
    `mask::mask_iou_filled(reference_filled: &[bool], layers: &[u16], overlay: &[bool]) -> f32`;
    `mask_iou_planes` delegates to it.
  - `score::RgbReference { rgb: Vec<[u8; 3]>, sky: Vec<bool> }`;
    `score::window_ssim(reference_rescaled: &[f32], render_luminance: &[f32]) -> f32` (pass 1:
    rescales the render, bar overlay, mean window score);
    `score::score_rgb_frame(reference: &RgbReference, render: &RenderFrame, min_fade_level: f32) ->
    RgbScore`, `RgbScore { ssim: f32, iou: f32, loss_by_class: [f32; LOSS_CLASSES.len()],
    authored_fade_level: Option<f32>, scored: bool, reference_luminance: Vec<f32>,
    render_luminance: Vec<f32> }`.
  - `video::SKY_TOLERANCE_FRAMES: u64 = 2`; `video::Palette = [[u8; 3]; 256]`;
    `video::palettes_at(capture: &VideoCapture, frame: u64) -> (Palette, Option<Palette>)` (the
    palette in effect, and the one before the latest change when that change is at most 2 frames
    earlier); `video::sky_mask(rgb: &[[u8; 3]], current: &Palette, previous: Option<&Palette>) ->
    Vec<bool>`; `video::load_frames(dir: &Path, wanted: &BTreeSet<usize>) ->
    Result<BTreeMap<usize, Vec<[u8; 3]>>, String>` (decodes `capture.avi` once, keeps wanted video
    indices as RGB; `bgr0` bytes are blue, green, red, unused).

- [ ] **Step 1: Write the failing tests.** `rgb_luminance_matches_reference_luminance` (same image
  via indices+palette and via RGB); `the_bar_overlay_covers_rows_185_to_199`;
  `mask_iou_filled_matches_mask_iou_planes`; `an_identical_rgb_frame_scores_one` (SSIM 1, IoU 1, no
  loss); `window_ssim_equals_score_rgb_frames_ssim`; `palettes_at_replays_changes`;
  `the_previous_palette_lasts_two_frames_after_a_change` (Some at +0, +1, +2; None at +3);
  `sky_mask_matches_either_palette_within_the_tolerance`; `load_frames_keeps_only_wanted_indices`
  (on `synthetic.avi`, indices {0, 7}).
- [ ] **Step 2: Run and see them fail.** `cargo test -p stunt-cli parity::`.
- [ ] **Step 3: Implement**, reusing `compute_window_scores`, `attribute_loss`, `loss_class`
  (reference filled = not sky) and the existing authored-fade rule.
- [ ] **Step 4: Run and see them pass; commit** `feat(parity): score RGB video frames`.

### Task 8: Seconds report document

**Files:**
- Create: `crates/stunt-parity/src/seconds.rs`; Modify: `crates/stunt-parity/src/lib.rs`
- Modify: `crates/stunt-cli/src/parity_artifacts.rs`
- Test: unit tests in both

**Interfaces:**
- Produces (`stunt_parity`): `SecondsReport { schema_version: u32, samples_per_second: u32,
  window_before: u32, window_after: u32, film_offset: i32, seconds: Vec<SecondReport>, scored_seconds:
  usize, unmatched_seconds: usize, mean_ssim_scored: Option<f32>, median_ssim_scored: Option<f32>,
  p10_ssim_scored: Option<f32>, share_initial: Option<f32>, share_sign_off: Option<f32>, i6_gate:
  I6Gate, mean_iou_scored: Option<f32>, mean_best_ssim_scored: Option<f32>, local_offsets:
  BTreeMap<i32, u32>, offset_drift_ticks_per_minute: Option<f32> }`;
  `SecondReport { second: u32, samples: Vec<SampleReport>, ssim: f32, best_ssim: f32, iou: f32,
  loss_by_class: BTreeMap<String, f32>, authored_fade_level: Option<f32>, scored: bool, edge: bool,
  slip: bool }`; `SampleReport { film_tick: u32, ssim: f32, best_ssim: f32, local_offset: i32, edge:
  bool }`; `SecondsReport::validate(&self) -> Result<(), ArtifactError>` (seconds ascending;
  `scored_seconds` equals the count of `scored`; every `samples` non-empty).
- Produces (adapter): `parity_artifacts::write_seconds_report(path: &Path, report: &SecondsReport)
  -> Result<(), AdapterError>`, `read_seconds_report(path: &Path) -> Result<SecondsReport,
  AdapterError>`; file name constant `SECONDS_REPORT: &str = "seconds.json"`. No Python reader yet:
  nothing in Python consumes `seconds.json` until part 4, so ADR 0011's "neither adapter invents a
  field the other does not read" holds.

- [ ] **Step 1: Write the failing tests.** `a_seconds_report_round_trips`;
  `seconds_must_ascend`; `scored_seconds_must_match_the_rows`.
- [ ] **Step 2: Run, fail; Step 3: implement; Step 4: run, pass.**
- [ ] **Step 5: Commit** `feat(parity): add the seconds report document`.

### Task 9: Per-second scorer

**Files:**
- Create: `crates/stunt-cli/src/parity/seconds.rs`; Modify: `crates/stunt-cli/src/parity/mod.rs`
- Test: unit tests in `seconds.rs`

**Interfaces:**
- Consumes: Task 7 `RgbReference`, `window_ssim`, `score_rgb_frame`, `palettes_at`, `sky_mask`,
  `rgb_luminance`; Task 8 report types; `score::RenderFrame`.
- Produces: `SLIP_TICKS: i32 = 2`; `struct SecondsOptions { samples_per_second: u32, window_before:
  u32, window_after: u32, min_fade_level: f32 }`; `struct Sample { second: u32, row: usize,
  video_index: usize, film_tick: u32, frame: u64 }`;
  `pick_samples(capture: &VideoCapture, samples_per_second: u32, video_frames: usize) -> Vec<Sample>`;
  `trait RenderSource { fn frame(&mut self, tick: u32) -> Result<Option<&RenderFrame>, String>; }`;
  `struct DirRenderSource` (reads `tick_NNNNN.png` and planes from a render directory with its
  controls, caching ticks and dropping those below the lowest still needed);
  `score_seconds(capture: &VideoCapture, frames: &BTreeMap<usize, Vec<[u8; 3]>>, samples: &[Sample],
  render: &mut dyn RenderSource, options: &SecondsOptions) -> Result<SecondsReport, String>`.

Rules the tests pin:
- Sample targets in second `s` are `50s + (k*50 + n/2) / n` for `k` in `0..n` (`n` = 3 gives 0, 17,
  33); each takes the first row at or after `film_start_frame` with `film_tick >= target` and
  `film_tick < 50(s+1)`; repeats are dropped; rows whose video index is past the recording are dropped.
- Offsets are render tick minus sample tick: a render that shows each picture 3 ticks before the
  capture does has offset −3.
- Pass 1: for offsets `-window_before..=window_after`, render tick `t + offset` (skipped when below 0
  or missing); best SSIM wins, ties go to the offset nearest 0; `edge` when the winner is exactly
  `-window_before` or `+window_after` (a bound cut short by tick 0 or a missing tick cannot win, so it
  never flags).
- Film offset: the median local offset over non-`edge` samples (lower median for an even count);
  none left is the error "no sample matched inside the window; widen --window-before/--window-after".
- Pass 2: each sample scored with `score_rgb_frame` at `t + film_offset`; a second's `ssim` is the
  median of its samples there, `best_ssim` the median of their pass-1 bests; `slip` when any sample's
  `|local_offset - film_offset| > SLIP_TICKS`; `scored` from the authored fade of the second's first
  sample; a second whose samples have no render tick at the film offset is `unmatched`.
- Drift: least-squares slope of local offset against film second over non-`edge` samples, times 60.

- [ ] **Step 1: Write the failing tests** with an in-memory `RenderSource` built from synthetic
  320x200 frames (a moving bright rectangle on a sky-index background, rendered per tick):
  `three_samples_fall_at_0_17_and_33`; `one_sample_per_second_takes_the_first_frame`;
  `a_constant_shift_becomes_the_film_offset` (the render shows each picture 3 ticks early:
  `film_offset == -3`, every second scores above 0.99); `a_stretch_further_off_is_flagged_slip`
  (seconds 4–5 shown 7 ticks early: local offset −7, `slip`, and their `ssim` below `best_ssim`);
  `a_shift_past_the_window_sets_edge` (12 ticks early: the winner is −8, `edge`);
  `no_match_inside_the_window_is_an_error` (Review Focus 5);
  `missing_render_ticks_leave_seconds_unmatched` (Review Focus 3);
  `seconds_below_the_fade_floor_are_listed_not_scored`;
  `the_sky_mask_uses_the_previous_palette_after_a_change`.
- [ ] **Step 2: Run, fail.** `cargo test -p stunt-cli parity::seconds`.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run, pass; commit** `feat(parity): score a video capture per film second`.

### Task 10: Wire the video path into `stuntreel parity`

**Files:**
- Modify: `crates/stunt-cli/src/parity/args.rs`, `mod.rs`, `sheets.rs`
- Modify: `crates/stunt-cli/src/parity/test_support.rs` (keyframe-only ZMBV writer for tests)
- Test: `crates/stunt-cli/src/parity/tests.rs`

**Interfaces:**
- Consumes: Tasks 7–9.
- Produces: flags `--samples-per-second N` (1..=5, default 3), `--window-before N` (default 8),
  `--window-after N` (default 2), `--inspect-second S` (repeatable); `run` takes the video path when
  `<reference>/capture.avi` exists and errors if those flags are given for a frame capture; writes
  `seconds.json`, sheets `second_SSSS.png` for the 5 lowest scored seconds (capture | render at the
  film offset | difference), and for each `--inspect-second` `inspect_SSSS.png` (capture, render at
  the film offset, render at the local offset, both difference maps, then the window's render
  frames); with `--compare <seconds.json>` prints the mean delta and the 5 most improved and regressed
  seconds (`--compare-test` is refused for a video capture); prints
  `[parity] scored N seconds (M samples) in X.X s`.
  `test_support::zmbv_keyframe_avi(width: u32, height: u32, frames: &[Vec<u8>]) -> Vec<u8>`
  (uncompressed keyframes, compression byte 0, plus `idx1`).

- [ ] **Step 1: Write the failing tests.** `a_video_capture_scores_end_to_end` (temp dir with a
  `capture.avi` from `zmbv_keyframe_avi` whose frames are the grey ramp `((x + y) % 251)` that
  `test_support::write_render` draws, and a `meta.json` covering 3 film seconds; a render dir with
  `write_render` at every tick; asserts `seconds.json` loads, `film_offset == 0` since every offset
  ties, 3 scored seconds, sheets written);
  `video_flags_are_refused_for_a_frame_capture`; `inspect_second_writes_its_panel`;
  `compare_prints_second_deltas`; `samples_per_second_outside_1_to_5_is_refused`.
- [ ] **Step 2: Run, fail; Step 3: implement; Step 4: run, pass.**
- [ ] **Step 5: Commit** `feat(parity): score video captures from stuntreel parity`.

## Part 3: Validation

### Task 11: Validate per-second scoring and decide on the switch

Needs the emulator, the corpus and release renders; results go to the research log, not the gate.

**Files:**
- Modify: [`research/parity/log.md`](../../../research/parity/log.md) (rows at the end),
  [`research/parity/method.md`](../../../research/parity/method.md) (a "per-second scoring" section)
- Modify: [`video-parity-2026-10-31.md`](video-parity-2026-10-31.md) (answer the open questions)

- [ ] **Step 1: Score.** Render `CTRY.FLM` and `INTRO.FLM` with the release build (`mise run
  parity` renders as today), then `stuntreel parity --reference <video capture> --test <render>
  --output <scratch>` for each. Record the headline, film offset, `edge` and `slip` rates, the
  per-sample spread and the printed time. If `INTRO.FLM` takes over 60 s to score, add the
  downscaled-MSE prefilter and per-second parallelism the spec names as a follow-up task.
- [ ] **Step 2: Sensitivity.** In a scratch copy of the `CTRY.FLM` render, alter three seconds:
  paint one actor's layer pixels with the neighbouring background in seconds 5–6; shift every pixel
  4 columns right in seconds 10–11; replace each tick *T* of seconds 15–16 with the frame of tick
  *T* + 5 (the picture arrives 5 ticks early, so the local offset moves by −5). Expected: seconds 5–6
  and 10–11 drop below every unaltered second's `ssim`; 15–16 are `slip`; the other seconds move by
  less than 0.005.
- [ ] **Step 3: Render pair.** Score `build/parity/previous/ctry_current` and `ours/ctry_current`
  against the same capture; the seconds whose `ssim` moves by more than 0.005 must be seconds where
  the two renders' PNGs differ.
- [ ] **Step 4: Against today.** Compare each second's `ssim` with the per-frame scores of the
  current references at the same ticks; look at the ten lowest seconds by eye with `--inspect-second`
  and note whether the ranking matches.
- [ ] **Step 5: Thresholds.** Say whether 0.88/0.90 separate the altered seconds from the
  unaltered ones at the film offset; if not, propose values.
- [ ] **Step 6: Decide and record.** Log rows, the method section and the spec's open questions.
  **Stop** (no part 4) if the ranking disagrees with the eye or the altered seconds do not stand out.
  Commit `docs(parity): record per-second scoring validation`, then write the plan for parts 4–5.
