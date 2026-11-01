# Video parity: score film seconds against an AVI capture

Status: spec, awaiting review. Sections A to C agreed in conversation 2026-10-31. Replaces the capture
half of [`capture-frame-storage-2026-10-31.md`](capture-frame-storage-2026-10-31.md); its render half
stays a separate project.

## Intent

Parity today compares individual captured pages with render frames at the same `film_tick`. Capturing
those pages is slow and complicated (trace pass, replayed dump passes of at most 40 pages, a stride of
about 11 ticks), the store is thousands of small files, and a page that lags its clock by a few ticks
scores as a picture difference.

Instead: record each film once as video, cut it into film seconds, score each second against the render
with a small search over time, aggregate the seconds into the film's parity, and inspect the weak seconds
to see what differs.

Success:

- one free-running capture per film, with no replay passes;
- one score per film second, robust to a few ticks of timing offset, with the offset itself reported;
- a film-level headline that ranks films and seconds the way a person judging by eye would;
- a way to look at any second and see what differs and at which offset.

What was said and what is assumed: the user proposed the AVI dump, one-second segments, a sliding window
to absorb offsets, aggregation and per-segment inspection, and the sampled-frame scoring of section B;
chose RGB scoring with palettes logged on change, ffmpeg for optional render video, and making the
segment score the headline once validated, and to drop audio from the stored video for now. The user also
accepted the review's changes: a film-wide offset for the headline, sensitivity tests in place of a
repeat-capture noise floor, changed-entry palette logging, a sky mask tolerant around palette changes,
and a compute budget. The window bounds, three samples per second and the 2-tick `slip` margin are this
spec's proposals.

## Evidence

- **Recording.** dosbox-automation's `dosbox.capture_start()`/`capture_stop()` record one video frame
  per emulated frame; video frame *j* is emulated frame `capture_start_frame + j`, and a per-frame Lua
  log carries `film_tick` for films without a HUD
  ([`capture-dosbox-automation.md`](../../../research/playone-exe/capture-dosbox-automation.md) §§ 1–4).
  Runs are bit-identical for `CTRY.FLM`, take about 1.3x real time, and 16 to 24 run side by side.
- **Format, checked 2026-10-31.** A 10 s `CTRY.FLM` recording on the `capture` profile (scratch script,
  not committed) is ZMBV with pixel format `bgr0` (32-bit RGB), 320x200, 70.09 frames per second, plus a
  PCM audio track. The 2.98 MB file is 1.03 MB of video (about 100 KB/s) and 1.91 MB of audio (about
  190 KB/s). Keyframes fall every 300 frames; the keyframe header reads version 0.1, zlib, format 8
  (32-bit), 16x16 blocks. ZMBV in its 8-bit mode would have
  carried indices and palette, but dosbox-automation does not record that mode, so the video holds no
  palette indices.
- **Colours.** The video's RGB is the 6-bit DAC scaled by `round(x * 255 / 63)` (§ 4); two indices can
  share an RGB (§ 5), so indices are not always recoverable from video alone.
- **Frame rate.** At 45,000 cycles `PLAYONE` draws a page on about 99% of emulated frames, about 1.4 per
  film tick (§ 4.4). Today's captures hold 4 to 5 frames per film second only because of the capture
  stride (`FILM_STRIDE_TICKS`, `plan.pick_every`).
- **Offsets.** The page lags its clock by an amount that differs between emulators: DOSBox-X tick 110
  equals dosbox-automation ticks 104–105, tick 770 equals 767 (§ 4.3), and an older harness matched pages
  7 to 10 ticks earlier than their tags ([`capture-speed.md`](../../../research/playone-exe/capture-speed.md)).
- **Palette uploads.** `set_palette` uploads the DAC in two retrace-gated halves: for one video frame
  entries 0–127 are new and 128–255 are the previous palette (§ 4.3). The working palette at
  `DS:0x2768` reads within one frame in Lua (§ 4.1).
- **Torn pages.** The `A000` update never waits for retrace; about 3 to 4% of changed frames are torn
  (§ 4.5). The video shows them as they were scanned out.

## Decisions

| Decision | Why | Rejected |
|---|---|---|
| One AVI recording per film | one pass, every emulated frame, no `MAX_DUMPS` or stride | full-rate page dumps (about 135 passes for `INTRO.FLM`) |
| Score in RGB luminance | the video is RGB; [I6] SSIM is already on Rec. 601 luminance | rebuilding indices from RGB (ambiguous where indices share a colour) |
| Log the working palette on change | sky mask under fades, and "wrong colours" vs "wrong picture" | logging every frame; a `set_palette` code hook (not known to work in dosbox-automation Lua); reading the DAC by port (5.75 s per palette) |
| Sample frames per second, search a tick window | cheap, absorbs the page-to-clock lag | best match over the whole render (hides timing errors, and static or repeated shots match the wrong moment) |
| Headline at one film-wide offset | absorbs the constant lag without the best-of-11 inflation, so [I6] keeps its meaning | best-in-window as the score (kept as the timing diagnostic) |
| SSIM stays the metric | [I6] is defined in SSIM; maps and attribution exist | VMAF (trained on compressed natural video, one opaque number per frame); LPIPS/DISTS (PyTorch); MS-SSIM, CW-SSIM and FLIP stay candidates for inspection |
| Own ZMBV decoder in Rust | ffmpeg is not pinned in `mise.toml`, and the gate must not need it | ffmpeg in the scoring path |
| Render keeps index and layer planes | the scorer needs the render's layer plane and palette; an RGB render video would lose them | render as video |
| Render video only as an optional ffmpeg export | viewing convenience; ffmpeg also gives MP4, `hstack`, 4:3 scaling, `drawtext` | our own ZMBV writer |

## Design

### A. Capture

One run per film on the `capture` profile (dynamic core, 45,000 cycles), unchanged. One Lua script,
generated by `luagen`:

1. boots, selects the film and parks the cursor (the existing key and park pieces);
2. calls `dosbox.capture_start()` at a fixed emulated frame and records `capture_start_frame`;
3. every frame logs `frame, film_tick, global_tick` into `dosbox.output` in chunks of 100 rows;
4. every frame reads the 768-byte working palette and, when it differs from the previous frame's, logs
   `frame` and only the entries that changed (index and 6-bit RGB), so a film full of fades stays far
   below the Lua heap limit (a 90-page dump pass of about 11.5 MB of output failed, § 4.4);
5. stops at the film's end hold (the trace pass's signal: `film_tick` stops changing) or a frame cap,
   then calls `capture_stop()`.

Store: a new kind under [ADR 0024](../../adr/0024-captures-are-filed-by-film-then-kind.md),
`captures/<film>/video/<run>/`, add-only like the others:

- `capture.avi`: the recorded video stream (ZMBV `bgr0`), without audio;
- `meta.json`, schema 1 of this kind, written last: film and archive hashes, the `PLAYONE` build, the CPU
  profile, `capture_start_frame`, `film_start_frame` (the first frame whose `film_tick` moved after the
  dialog keys), `end` (`hold` or `capped`), the tick log as column arrays (`frame`,
  `film_tick`, `global_tick`), and `palettes`: the palette at `capture_start_frame` in full, then a list
  of `{frame, entries}` changes, with 8-bit RGB. Readers rebuild the palette in effect at any frame.

Audio is dropped from the stored file for now (64% of the test recording) and may come back later.
Sound stays on in the emulator, because switching it off changed whether films start and replay
identically (§ 4.4). Part 1 first checks whether dosbox-automation can record video without audio;
otherwise the capture tool rewrites the AVI with its video stream only (the decoder's AVI reader plus a
small RIFF writer), so no ffmpeg is needed.

Checks after a run: the AVI's frame count equals the log's rows; `film_tick` never decreases; `end` is
recorded. A second run compared row by row is optional.

The trace and dump machinery stays for probes (`probe-light`, page dumps); parity captures stop using it.

### B. Scorer

`stuntreel parity` accepts a video capture beside today's frame captures.

- **Decoding.** A ZMBV decoder in Rust (`flate2` is already a dependency): one zlib stream per keyframe
  interval, raw keyframes, and per-16x16-block motion vectors with XOR deltas. Only the `bgr0` format is
  required. The decoder and its AVI reading sit behind one module, the only code that knows the layout.
- **Sampling.** For film second *s*, up to three samples: the first capture frame with
  `film_tick >= 50s`, `>= 50s + 17` and `>= 50s + 33`. `--samples-per-second 1` keeps only the first.
- **Matching.** A sample at tick *t* is scored against render ticks `t - 8` to `t + 2`
  (`--window-before`, `--window-after`), each with the existing [I6] path (Rec. 601 luminance, stretched
  to 320x240, `compute_window_scores`). Render luminance comes from the render's PNG at that tick, as
  today: `render.json` carries only each tick's palette parameters (`sky`, `brightness`, `saturation`),
  not its 256 colours, so the render store project must store the effective palette before PNGs go.
  Log rows before the film starts (`film_start_frame`) are ignored.
- **Two passes: local offsets, then one film offset.**
  - Pass 1: each sample keeps its best SSIM in the window and that offset, its *local offset*. A best
    offset on a window bound is flagged `edge`, except where the film's first or last tick clamped that
    bound. The *film offset* is the median local offset over scored samples without `edge`.
  - Pass 2: every sample is scored at the film offset. The second's score is the median of its samples
    there. This is the headline, so picking the best of 11 candidates cannot raise it, and the [I6]
    thresholds keep their per-frame meaning unless part 3 shows otherwise.
  - The best-in-window score and local offset stay in the report as the timing diagnostic: a second whose
    local offset differs from the film offset by more than 2 ticks is flagged `slip`.
- **Sky mask and IoU.** Capture: a pixel is sky when its RGB equals a `CAPTURE_SKY_INDICES` entry
  (227–238) of the palette in effect. For two frames after a logged change it is sky when it matches a
  sky entry of either the previous or the new palette, which covers the two-halves upload and the 0 to 2
  frame lead of the working palette over the DAC (§ 4.3). Render: its layer plane, as today. IoU is taken
  at the film offset.
- **Fade floor.** Unchanged: the render's authored brightness (var 14) from the sidecar
  ([ADR 0005](../../adr/0005-parity-requires-the-render-sidecar.md)); seconds below the floor are listed,
  not scored.
- **Report.** A new `report.json` version ([ADR 0011](../../adr/0011-parity-artifacts-are-a-versioned-port.md)).
  Per second: sample ticks; per sample, SSIM at the film offset, best-in-window SSIM and local offset;
  the second's median; `edge` and `slip`; IoU; and loss by class at the film offset. Film: the film
  offset; mean SSIM over scored seconds at the film offset (the headline), median, 10th percentile,
  share of seconds at or above 0.88 and 0.90, mean IoU; mean best-in-window SSIM as a diagnostic; and the
  local-offset distribution and its drift through the film.
- **Compute.** Pass 1 is 11 SSIMs per sample, so about 33 per film second against roughly 5 per second
  today, about 8,000 for a 4-minute film. Part 2 times the longest survey film; if it is slow, window
  candidates are ranked first by mean squared error on downscaled luminance and seconds are scored in
  parallel.
- **Inspection.** `stuntreel parity inspect --second S` writes the capture sample, the render
  frame at the film offset and at its local offset, an SSIM map for each, and a strip of the window's
  render frames. The contact sheet has one row per second.
- **Comparison.** `--compare` matches seconds by number.
- **Render video.** Later and optional: `export-video` encodes a render, or render and capture side by
  side, with ffmpeg when it is installed. Not part of scoring or the gate.

### C. Rollout

Each part lands on its own and passes `mise run check`.

1. **Video capture and decoder.** The script, the `video` store, a `mise run capture-video` task (a
   separate task, so `capture-ref` keeps its frame-dump meaning until part 5), the decoder, dropping the
   audio stream, and the ADR 0024 amendment. Measured here: the palette log of the survey film with the
   most palette changes, against the Lua heap; and sky-colour clashes (a non-sky index sharing a sky RGB)
   across every palette in the survey, since deep fades push colours together.
2. **Segment scorer** beside the per-frame scorer (section B), with its compute timed on the longest
   survey film.
3. **Validation** on `CTRY.FLM` and `INTRO.FLM`. A repeat capture is no noise floor, because
   `CTRY.FLM` replays bit for bit; sensitivity is tested instead:
   - a scratch copy of a render with chosen seconds altered (an object's layer painted over with the
     background, the camera shifted by a few pixels, a run of ticks delayed by one second): those seconds
     must drop, the delayed ones must show `slip`, and the others must not move;
   - the `previous` and `ours` renders scored against one capture: the seconds whose scores move must be
     the seconds where the two renders differ;
   - per-second against today's per-frame scores on the current references, and the ten worst seconds
     judged by eye;
   - whether 0.88/0.90 still separate good from bad seconds at the film offset.

   Results go to [`log.md`](../../../research/parity/log.md). **Stop here** if the ranking disagrees
   with the eye or the altered seconds do not stand out; the per-frame scorer then stays the headline.
4. **Switch.** SPEC [I6] restated over film seconds with the thresholds part 3 confirms, and a new ADR;
   [`references.toml`](../../../research/parity/references.toml) names video captures in a reviewed
   commit; the batch survey's capture stage records video and every film is recaptured;
   [`method.md`](../../../research/parity/method.md), the
   [`improving-render-parity`](../../../.agents/skills/improving-render-parity/SKILL.md) skill,
   [`GLOSSARY.md`](../../../GLOSSARY.md) (film second, sample, offset window) and
   [`ARCHITECTURE.md`](../../ARCHITECTURE.md) updated.
5. **Retirement.** Parity stops reading frame captures; v1 frame captures are reaped; `migrate_captures`
   is removed; the storage plan's capture half is closed. Its render half (per-second zstd chunks,
   per-second preview PNGs, no PNG per tick) proceeds separately; the scorer reads renders through the
   plane codec, so that change touches only the codec.

## Testing

- **Decoder fixtures**, both without game data, documented in
  [`tests/fixtures/README.md`](../../../tests/fixtures/README.md):
  - a synthetic AVI generated once with ffmpeg's ZMBV encoder (`-c:v zmbv -pix_fmt bgr0`) from made-up
    frames covering a keyframe, block motion and XOR deltas, committed with the command that made it, so
    the decoder is checked against an independent encoder;
  - a few frames recorded by dosbox-automation at its DOS prompt, so it is checked against the encoder
    that writes real captures.
- **One-off check**: the decoder equals ffmpeg's decode of a real capture byte for byte (recorded in the
  research note, not the gate).
- **Capture**: generated Lua for the per-frame row and changed-entry palette logging; rebuilding the
  palette in effect at a frame from the changes; `meta.json` round trip; the post-run checks on a mocked
  run (`MockAutomation`).
- **Scorer**, on synthetic data: a render shifted by a constant number of ticks gives that film offset
  and high scores at it; a few seconds delayed further are flagged `slip` and score lower at the film
  offset; a shift past the window sets `edge`; within two frames of a palette change a pixel matching a
  sky entry of either palette is sky; a second with no frames is skipped; seconds below the fade floor
  are listed and not scored.
- `mise run check` passes; nothing reads the corpus or needs ffmpeg.

## Out of scope

- The render store change (the storage plan's render half).
- `export-video`.
- Replacing SSIM as the metric; MS-SSIM, CW-SSIM and FLIP may be tried as inspection aids later.
- Full-rate frame-dump captures.

## Open questions

Answered 2026-10-31 by part 3 ([`research/parity/method.md`](../../../research/parity/method.md) § 4.4); per-second scoring is **not adopted** and parts 4–5 are not planned.

- Thresholds: moot; the planted errors did not separate from unaltered seconds at the film offset, so no threshold can.
- Defaults: at SSIM near 0.75 the local best offset is noise (median gain 0.009 over the film offset). With a 2-tick margin, 23 of 27 `CTRY.FLM` seconds read as `slip` and 20 of 81 samples as `edge`. A `slip` would need a significance margin of about 0.03, and the film offset would need to be fixed, not refitted per render.
- Audio: dosbox-automation has no audio-off option; `video_only` strips it ([`capture-dosbox-automation.md`](../../../research/playone-exe/capture-dosbox-automation.md) § 4.6).
- Replay jitter: not measured.
- Kept from this work: `capture-video`, whose recordings cover static stretches that frame captures skip (the `INTRO.FLM` title card), and the ZMBV decoder. Films past about 24,500 frames need the recording split across scripts.

Original questions:


- Do 0.88/0.90 still separate good from bad seconds at the film offset, or do they need recalibrating
  (part 3)?
- Are three samples per second, a −8 to +2 window and a 2-tick `slip` margin the right defaults? Part 3
  should report edge and slip rates and the per-sample spread.
- Can dosbox-automation record video without audio, or must the capture tool strip it (part 1)?
- `COUNT.FLM`-style replay jitter (§ 4.4): does a second run of the same film shift per-second offsets?
