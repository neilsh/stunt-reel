---
summary: "dosbox-automation 0.85.1 as capture emulator: frame-locked capture reading `film_tick` per frame at `DS = 0x0F46`, bit-identical `CTRY.FLM` runs with the demo archive, replays made to differ by sound samples in the archive, torn pages, DAC lag and the Lua instruction budget."
sidebar_label: "Capture with dosbox-automation"
---
# `PLAYONE.EXE`: Capture with dosbox-automation (Frame-Locked Video)

[dosbox-automation](https://github.com/dosbox-automation/dosbox-automation/) 0.85.1, a DOSBox Staging fork with a REST and Lua API (GPL-2.0-or-later), is the capture emulator.
`stunt_reel/tac` drives it ([ADR 0025](../../docs/adr/0025-capture-runs-are-plans-not-sessions.md)): [`luagen.py`](../../python/stunt_reel/tac/luagen.py) writes the scripts, [`plan.py`](../../python/stunt_reel/tac/plan.py) runs the passes, [`framebuffer.py`](../../python/stunt_reel/tac/framebuffer.py) writes the capture.
The retired DOSBox-X harness: [`dosbox-x-legacy.md`](dosbox-x-legacy.md).
Measurements ran 2026-10-30 to 2026-11-01 on one 16-core host.

---

## 1. What the Tool Offers

* **Install:** pinned in `mise.toml`; run `mise exec -- dosbox`.
* **Control:** REST on `127.0.0.1:<webserver_port>` with a bearer token (`DOSBOX_API_TOKEN`, 64 hex characters or it is discarded), and a Lua script on the emulation thread (`POST /api/v1/script/load`, `/start`, `GET /status`; results in `dosbox.output`).
* **Guest access:** REST `memory`, `cpu/state` and `io/port`; Lua `dosbox.mem_read[_word]`, `frame()` and `wait_frames(n)`.
* **Capture:** `dosbox.capture_start()` / `capture_stop()` records lossless ZMBV AVI, one video frame per emulated frame.
  The REST call takes only `mode` (`raw` or `rendered`); nothing drops the audio stream.
* **Absent:** the debugger (`debugger` is `false` in the OpenAPI document): no breakpoints, pause, step or hooks ([ADR 0034](../../docs/adr/0034-breakpoints-run-on-dosbox-x.md)).
* **`dosbox.debugmsg(s)` is a file sink** (`[Bounded Observation]`, `v0.85.1`, 500 lines of 128,000 characters and 500 real `A000` pages): with the script loaded as `POST /script/load?debug=true` it appends `[F:<frame> T:<time>] debugmsg: <s>` to `<config dir>/logs/lua-debug-<time>-<script name>.log` and flushes per call.
  The code has no size cap, and a string is cut at its first NUL (`nul\0tail` arrived as `nul`).
  500 synthetic lines (64 MB) arrived byte for byte, and 500 `A000` pages ran in 1.2 s without a heap error (their content was not checked); the 16 MB Lua heap (100 held strings of 128,000 characters ran, 140 died `not enough memory`) limits what a script keeps, not what it writes.
  The instruction count and peak heap were not measured (`collectgarbage` is removed).
  _Source: [where tears fall, and debugmsg as a sink](../../work/2026-11/1211_torn-video/journal.md#2026-11-27-where-tears-fall-and-debugmsg-as-a-sink)._
* **Mounts:** a mount under `Temp` or far from its conf is refused (`MOUNT: Blocked`): conf and mount sit together under the data root.

_Source: [first evaluation](../../work/2026-11/distill-capture-dosbox-automation/journal.md#2026-10-30-first-evaluation), [scratch driver](../../work/2026-11/distill-capture-dosbox-automation/journal.md#2026-10-30-scratch-driver), [whole-film video](../../work/2026-11/distill-capture-dosbox-automation/journal.md#2026-10-31-video-capture)._

## 2. Frame-Locked Capture

A script starts capture and presses the dialog keys at fixed emulated frames (`dosbox.frame()` counts from boot), then reads guest memory per frame.

* **`DGROUP` is `DS = 0x0F46`** for `CTRY.FLM` and `INTRO.FLM` on the unpatched build, with DOSBox-X's offsets.
  `cpu/state` reports the running code's `DS` (`0x17C9` while `CS` is `0x0A19`, § 4.3), so scripts read `0x0F46:offset`. `[Bounded Observation]`
* **`CTRY.FLM` replays bit for bit with the demo's `.ALL`.**
  Nine runs at 8,000 cycles and 12, 16 and 24 runs started together gave identical video and tick logs, no dropped frames; three `INTRO.FLM` runs gave identical video (unpatched build, demo `.ALL`).
  Not every film replays: with a Patch 3 `MAKEONE` archive, which carries in full the sound samples the demo's `.ALL` shortens (§ 4.4), two captures one after the other differed on 27 of 104 paired `CTRY.FLM` pages and 78 of 172 `INTRO.FLM` pages (2026-11-08, [`../parity/metric-bench.md`](../parity/metric-bench.md#221-recapture-noise-of-the-reference-films) § 2.2.1). `[Bounded Observation]`
* **Video frame *j* is emulated frame `capture_start_frame + j`**, at 70.087 Hz.
  The HUD timer (`film_tick / 50`, redrawn per render loop) trails the live tick by 0 to 3 ticks between render loops. `[Bounded Observation]`
* **Recorded RGB is the DAC**, each 6-bit component expanded as `round(x * 255 / 63)`, zero error on the indices checked.
  Two indices can share an RGB, so video does not always give the index plane: index scoring uses the page (§ 4.1). `[Bounded Observation]`

_Source: [first evaluation](../../work/2026-11/distill-capture-dosbox-automation/journal.md#2026-10-30-first-evaluation), [follow-up](../../work/2026-11/distill-capture-dosbox-automation/journal.md#2026-10-30-follow-up), [second round](../../work/2026-11/distill-capture-dosbox-automation/journal.md#2026-10-30-second-round)._

## 3. DOSBox-X Video for Comparison

* **The guest runs at another speed.**
  At 8,000 cycles dosbox-automation completes 424 render loops of `CTRY.FLM` to DOSBox-X's 369; at 7,000 the counts agree (370), yet none of 58 timer-aligned frames is byte-identical. `[Bounded Observation]`
* **DOSBox-X expands the DAC as `(v << 2) | (v >> 4)`**, one away from `round(v * 255 / 63)` at levels 11 to 15 and 48 to 52, read from its source, not measured. `[Supported Inference]`
* **Wider differences are mostly another instant** of `vault-ctry/frames/001`: index differences before the fade, another fade phase in it (96%); the page lags the clock by different ticks in each emulator. `[Bounded Observation]`

_Source: [first evaluation](../../work/2026-11/distill-capture-dosbox-automation/journal.md#2026-10-30-first-evaluation), [second round](../../work/2026-11/distill-capture-dosbox-automation/journal.md#2026-10-30-second-round), [third round](../../work/2026-11/distill-capture-dosbox-automation/journal.md#2026-10-30-third-round), [fourth round](../../work/2026-11/distill-capture-dosbox-automation/journal.md#2026-10-30-fourth-round)._

## 4. Measurements

### 4.1 Guest Speed, Cores and Page Reads

* **Render loops scale with `cpu_cycles`** (`CTRY.FLM`, normal core): 318 at 6,000, 370 at 7,000, 424 at 8,000, 631 at 12,000, 827 at 16,000. `[Bounded Observation]`
* **At 8,000 cycles the dynamic core does not replay the normal core**: 417 loops, clocks a tick or two apart from frame 2067, pictures different from frame 1280. `[Bounded Observation]`
* **A page and working palette read in one Lua step see one instant**, since Lua blocks the emulation: `mem_read(0xA000, 0, 64000)` and `mem_read(0x0F46, 0x2768, 768)` (6-bit).
  The game draws straight into `A000`.
  The Lua heap limits a pass: 90 pages (about 11.5 MB of hex) failed with `not enough memory`, 40 work (`MAX_DUMPS`). `[Bounded Observation]`
* **A page can match no video frame**: of 97 `INTRO.FLM` pages, four palette races, ten mid-render reads (§ 4.5). `[Bounded Observation]`

_Source: [follow-up](../../work/2026-11/distill-capture-dosbox-automation/journal.md#2026-10-30-follow-up), [second round](../../work/2026-11/distill-capture-dosbox-automation/journal.md#2026-10-30-second-round), [third round](../../work/2026-11/distill-capture-dosbox-automation/journal.md#2026-10-30-third-round), [fourth round](../../work/2026-11/distill-capture-dosbox-automation/journal.md#2026-10-30-fourth-round), [production harness](../../work/2026-11/distill-capture-dosbox-automation/journal.md#2026-10-30-production-harness)._

### 4.2 No Render Counter in `DGROUP`

A per-frame diff of `DS:0000..FFFE` over 90 `CTRY.FLM` frames found no render counter: the one byte that stepped near the loop rate, `DS:0x578C`, is a cycling index.
A render-complete signal must come from the code.
`[Bounded Observation]` _Source: [third round](../../work/2026-11/distill-capture-dosbox-automation/journal.md#2026-10-30-third-round)._

### 4.3 The Render Path and Segments

`[Supported Inference]`, static, from the unpacked image.

* **`set_palette` (image `0x7B70`, vtable `DS:0x2252`) uploads the DAC in two retrace-gated 384-byte halves**: `call 7B79` waits for retrace and runs `rep outsb`, and its `ret` at `0x7B8E` (`0F17:0C5E`) returns into `0x7B79` for the second half.
  Whether DOSBox-X's `BP 0D51:0C5E` named them is open ([`dosbox-x-legacy.md`](dosbox-x-legacy.md)).
* **The `A000` update never waits for retrace.**
  Vtable entry `0x738C` swaps buffers `[22CA]`/`[22CC]`, diff-copies to `A000` (`0x73A8` to `0x73D6`), draws sprites, ends at `0x7417` (untried as a breakpoint).
* **`CS = 0x0A19` and `DS = 0x17C9` are the same image**, loaded at paragraph `0x1F5`: the VM code segment (image `0x8240`) and a second work segment of about 111 KB (image `0x15D40`) holding the anchor table and VM variables, set by `mov ax,15D4h` at image `0xB012`.
  `0x336B` and `0x430B` lie past the image end, DOS-allocated `[Hypothesis]`, holding the composed pages (§ 4.5).

_Source: [fourth round](../../work/2026-11/distill-capture-dosbox-automation/journal.md#2026-10-30-fourth-round), [torn pages](../../work/2026-11/distill-capture-dosbox-automation/journal.md#2026-10-31-torn-pages)._

### 4.4 The Capture Profile and Replays

* **The render rate saturates near 45,000 cycles** (`CTRY.FLM`, normal core): new pages on 46% of frames at 7,000, 98% at 30,000, 99% from 35,000 to about 100,000, fewer above (`max`: 80% to 95%); wall time is constant. `[Bounded Observation]`
* **The `capture` profile, shared by `play`, is the dynamic core at 45,000 cycles**: the normal core's rate within about 1%, 0.22 to 0.24 of a host core against 0.39, own traces byte-identical.
  Dump passes run up to eight at once, each with its own `dosbox-<port>.conf`. `[Bounded Observation]`
* **Replays are not always identical.**
  Five `COUNT.FLM` traces gave four variants, a tick apart in 10 to 18 of 157 frames; `nosound` kept it, `sbtype = none` stopped the film.
  Each page carries its own pass's tick (§ 4.8). `[Bounded Observation]`
* **`COUNT.FLM`'s sound sample (`0xC31E`, 12 bytes) is what makes runs vary** (`[Bounded Observation]`, 2026-11-13).
  Ten `capture-ref` traces of its archive (unpatched build) with the sample stubbed were identical; ten with it kept gave five variants (a 1-pixel page, a 300-pixel page, an `emu_frame` 1354 for 1355; `torn_frames` 1 in 7 runs, 0 in all ten stubbed), never a different `film_tick`.
  A trace keeps 10 pages, one per window (one window pass), too few for `capture-compare`: pages were hashed.
  The stub shifts the windows' ticks.
  That the 157-frame jitter above has this cause is `[Supported Inference]`: that harness was not rerun stubbed, nor the `sb16`, `core = normal` and no-key setups.
  _Source: [2026-11-13: COUNT.FLM with its sound sample stubbed](../../work/2026-11/179_count-flm-jitter/journal.md#2026-11-13-countflm-with-its-sound-sample-stubbed)._
* **Sound samples in the archive make replays differ** (`[Bounded Observation]` on `BALLOON.FLM`, 2026-11-09).
  Two `MAKEONE` `BALLOON.ALL` captures on Patch 3, the second started 0.1 s after the first, differed on 26 of 102 shared pages; with both chunks in `0xC000`–`0xCFFF` (samples `0xC307`, `0xC565`) cut to one byte, they agreed on 108 of 108.
  `CTRY.FLM` fits without a controlled pair: the 2026-11-08 `MAKEONE` `CTRY.ALL` pair, one after the other, differed on 27 of 111 shared pages; a pair with its five chunks in that range cut to one byte, 0.1 s apart, agreed on 121 of 121 (2026-11-09).
  The demo's `CTRY.ALL` (samples `0xC302`, `0xC31E` one byte, `0xC319` 1,839 bytes) agreed on 121 of 121 across three captures.
  Which chunk in the range matters is not isolated.
  `vault-location` replays nearly bit for bit although its `LOCATION.ALL` holds a sample-like chunk (`0xC447`, 6,034 bytes) and six music chunks there (open question 16).
  Stubbing also changes the pictures: stubbed `BALLOON` differs from the with-sound reference on 66 of 96 pages, more than two with-sound captures differ; how is not measured.
  _Source: [sound samples in the archive](../../work/2026-11/305_recapture-noise/journal.md#2026-11-09-sound-samples-in-the-archive-make-replays-differ)._
* **Captures play the film with its sound samples stubbed** ([ADR 0043](../../docs/adr/0043-captures-play-with-the-archives-sound-samples-stubbed.md)).
  - Staging replaces each payload in `0xC000`–`0xCFFF` with the one byte `0x04`, the stub the demo's `CTRY.ALL` holds in `0xC302`.
    `--sound-samples kept` plays the archive as is, and `meta.json` records which was used.
  - The range holds two kinds of chunk: sample-like chunks, whose first byte is `0x00` or `0x02` (the source of those under `0xC4` and `0xC5` is unchecked), and music, chunks that begin `03 'FORM'` under `0xC0` and `0xC1` ([`linking.md`](../makeone-exe/linking.md) § 5).
    The demo's `CTRY.ALL` shortens its samples, keeps music `0xC010` whole; the stub replaces both. `[Bounded Observation]`
  - Known: with the stub, one pair of captures of each of the seven reference films replayed page for page ([`../parity/metric-bench.md`](../parity/metric-bench.md#221-recapture-noise-of-the-reference-films) § 2.2.1).
  - What is not known: what it does with the byte, whether it skips the sample or plays a click.
    A zero-length payload and a minimal well-formed sample were not tried. `[Bounded Observation]`
* **The mouse cursor is parked** below the 3D view by `dosbox.mouse_move(-2000, 2000)`, lighting no button; captures before 2026-10-31 show it at screen centre. `[Bounded Observation]`

_Source: [production harness](../../work/2026-11/distill-capture-dosbox-automation/journal.md#2026-10-30-production-harness)._

### 4.5 Torn Pages and the DAC Lag

* **A page read in the frame callback can be torn** (`[Supported Inference]`): the `A000` update (§ 4.3) takes tens of thousands of cycles and a frame boundary can land inside it.
  The composed pages' segments are in `DS:0x22CA` and `0x22CC`, swapped every render; after a finished copy rows 0–191 of `A000` equal one, and a torn page takes its top rows from one and the rest from the other.
* **How often** (`[Bounded Observation]`, `capture` profile): 66 of 1,908 `CTRY.FLM` frames (4.1% of changed frames) and 127 of 5,384 `INTRO.FLM` frames (2.9%).
  Rate against cycles: open question 7.
* **The DAC lags the working palette** (`[Bounded Observation]`, one `CTRY.FLM` fade, five steps): with page *f* the DAC's low half is `W(f-1)` and its high half `W(f-2)`.
  An `INTRO.FLM` fade showed each step's mixed frame as low half new, high half previous in 180 of 180 samples.
* **The harness** skips torn frames and each palette step's two frames ([`plan.py`](../../python/stunt_reel/tac/plan.py)).
  `meta.json` counts `composed_matches`; zero, which `capture-ref` warns about, means wrong `composed_pages` offsets.
* **Skipping torn pages did not raise the score:** `vault-ctry/frames/005` SSIM 0.7800 against `004`'s 0.7808, `vault-intro/frames/005` 0.5444 against 0.5488.
  Why `INTRO.FLM` falls is open question 9. `[Bounded Observation]`

_Source: [torn pages](../../work/2026-11/distill-capture-dosbox-automation/journal.md#2026-10-31-torn-pages), [fourth round](../../work/2026-11/distill-capture-dosbox-automation/journal.md#2026-10-30-fourth-round)._

### 4.6 Whole-Film Video Capture

`mise run capture-video` ([`video.py`](../../python/stunt_reel/tac/video.py)) logs both clocks every frame and the working palette when it changes, until the clock holds 30 frames.
`[Bounded Observation]`:

* **One log row per video frame** in three films; the first four ticks precede recording.
* **The row also reads the slot pass's clock and ticks word** (`slot_clock`, `slot_ticks`; Patch 3's offsets are inferred, ADR 0057), written as two optional `meta.json` columns that come together.
  `LOCATION.FLM` still ended `hold` at 11,616 frames and 118 palette changes, and two runs wrote one `capture.avi` hash and equal logs, slot columns included.
  The whole-film fields beside the log (`video`, `emulator`, `layout`, `film_ticks`) are optional, so version 1 stays.
* **Derived columns** (`mise run video-derive -- derive <film>`, local `derived.json`, never archived): `render_tick` by ADR 0057 per log row and `palette_step` on each palette write's frame.
  No `finished` column: the frame before a `slot_clock` change is not known to be a whole picture, because a video frame can be torn between the composed buffers (§ 4.5) and the neighbour rule that would spot it fails ([#1200 comment](https://github.com/neilsh/stunt-reel/issues/1200#issuecomment-7228756891)).
  An emulator-logged `composed` flag, which compares `A000` with both buffers each frame, was not built.
* **Row *i* of the log is AVI frame *i*** (`[Bounded Observation]`, `CTRY.FLM`): 1,197 of 1,200 `slot_clock` changes coincide with a changed picture at shift 0, and 1,106 to 1,148 at each other shift from -3 to +3.
  The row of `emu_frame` is `emu_frame - capture_start_frame - 1`; `video_index` is one above it.
* **Two recordings of one film are identical** (`[Bounded Observation]`, `CTRY.FLM` and `LOCATION.FLM`, one pair each, Patch 3, stubbed samples): equal `capture.avi` and `meta.json` bytes.
  `LOCATION`'s AVI hash equals that of a recording made in another container.
  ADR 0043's replay was shown for frame pages only.
  _Source: [reference check, replay and pairing](../../work/2026-11/1194_full-rate-video/journal.md#2026-11-27-reference-check-replay-and-the-pairing-rule-on-seven-full-rate-recordings)._
* **Against the pinned frame captures** (`[Bounded Observation]`, one recording per film, 1,875 pages): a page's RGB on rows 0..184 lies in the video at `emu_frame - capture_start_frame - 1` plus 0 on 1,122 pages and plus 1 on 731; 22 lie elsewhere.
  Medians are 99.9747% (`CTRY`) to 100% pixel-equal, minima 87.99% (`TRAINTNL`) to 97.14% (`INTRO`).
  By the journal's row rule (§ 4.5) 1,032 pages are exact, 503 split between two frames and 340 a band; no page is explained by its palette alone (0 of 466 mismatched on `CTRY` and `LOCATION`).
  The bands and splits match § 4.5's tears of a video frame built from `A000` while the game copies into it; that cause is `[Supported Inference]` (the emulator's capture path, how `capture_start` takes a finished frame into the AVI, was not read).
  The draw path was read (`vga_draw.cpp` at `v0.85.1`): in a VGA mode below 640x480 `VGA_DrawSingleLine` draws one row per PIC event and reads video memory then, so a tear's row is where the copy meets the beam, with no fixed strip rows (the four-part drawing is for Hercules and high-resolution modes).
  _Source: [reference check, replay and pairing](../../work/2026-11/1194_full-rate-video/journal.md#2026-11-27-reference-check-replay-and-the-pairing-rule-on-seven-full-rate-recordings), [where tears fall, and debugmsg as a sink](../../work/2026-11/1211_torn-video/journal.md#2026-11-27-where-tears-fall-and-debugmsg-as-a-sink)._
* **Where `CTRY.FLM`'s tears fall** (`[Bounded Observation]`, one recording, 121 pinned pages: 31 exact, 28 split, 62 band, rows 0..184): no fixed rows.
  Band pages start their unmatched rows at a median row 82.5 (34 of 62 within 80..97, no start row holds more than 6 pages; 833 of the 1,575 unmatched rows lie in rows 80 to 113) and span a median 20.5 rows (maximum 91); 22 of the 28 split pages differ from their best frame only on the HUD timer rows (179 to 183).
  A video-only test of row-to-row discontinuity is a weak detector (area under the ROC curve 0.60 over rows 0..183; at the best threshold 21 of 90 torn frames caught, 1 of 31 whole ones flagged).
  Comparing a frame with its two neighbours separates nothing in the form tried: 1,634 of 1,905 frames hold rows equal to neither, and that holds for 26 of 31 whole frames as well as 82 of 90 torn ones, so it separates nothing.
  The AVI is `zmbv` decoded as `bgr0`, not `pal8`.
  _Source: [where tears fall, and debugmsg as a sink](../../work/2026-11/1211_torn-video/journal.md#2026-11-27-where-tears-fall-and-debugmsg-as-a-sink)._
* **A per-frame stream of the composed buffers matched every pinned `CTRY.FLM` page** (`[Bounded Observation]`, one run, Patch 3, `?debug=true`): both buffers' rows 0..191 through `dosbox.debugmsg`, 1,907 frames, 469 MB of hex.
  Each of the 121 pages equals a streamed buffer at the page's own frame (119 the second word, 2 the first), and the working palette at that frame equals the page's on 121 of 121; the video is exact on 31 of the 121.
  That match holds by construction (the harness keeps a page only when `A000` equals a composed buffer), so it shows the stream is read at the right frame and replays, and that a whole picture is there on the 90 pages where the video is torn; it does not show the stream whole on frames the harness skips.
  `A000` equals the second word on 1,786 frames, the first on 31, both on 5 and neither buffer on 85, the frames the harness would count as torn; none of the 121 pinned pages is on one.
  The stream does not change `capture.avi` or `meta.json` and replays (two runs, equal payloads).
  It cost about 71 more Lua instructions a frame (estimate from a spin counter, one run each); with the row's own cost that leaves between about 7,300 and 12,300 frames a script, depending on how much of the 126,000 instructions the stream-off run used is boot.
  Not measured: which word is the newest finished picture on every frame, and any film but `CTRY`.
  _Source: [streaming the composed buffers of CTRY through debugmsg](../../work/2026-11/1211_torn-video/journal.md#2026-11-27-streaming-the-composed-buffers-of-ctry-through-debugmsg)._
* **`capture-video --stream` logs one composed picture a frame** (`[Bounded Observation]`, `CTRY.FLM`, one run): `p<f>:<flags>:<hex>` through `debugmsg` (the buffer `A000` equals, else the second), 234.9 MB for 1,907 frames, moved from the emulator's log directory to `stream.log` beside `capture.avi`.
  `capture.avi` equals the stream-off recording byte for byte, and each of the 121 pinned pages (rows 0..184) equals the logged picture at its own frame, which holds largely by construction (the harness keeps a page only when `A000` equals a buffer).
  The row costs about 49 more Lua instructions a frame (spin-counter estimate, one run), about 115 a frame if all of the stream-off run's 126,000 instructions are per-frame, so one script holds about 8,700 to 17,800 frames.
  _Source: [step 2, the stream inside capture-video](../../work/2026-11/1211_torn-video/journal.md#2026-11-28-step-2-the-stream-inside-capture-video)._
* **On frames where `A000` equals neither buffer, neither buffer is a picture the screen shows whole** (`[Bounded Observation]`, `CTRY.FLM`, one run of the two-buffer probe): on 85 of 1,907 frames, neither buffer's picture appears whole in `A000` in the 4 frames before, and the second word's appears in the 4 after on 5 of 85, the first word's on none.
  The second word's buffer changed with no word change on 967 frames, and 107 of its 1,623 distinct pictures never appear whole in `A000`, so a buffer can be read mid-compose.
  The second buffer that `--stream` logs on those frames is therefore not known to be whole; a decoder that wants whole pictures treats a `p` line with flags 0 as held and repeats the last picture with flags 1 to 3.
  _Source: [the front rule](../../work/2026-11/1211_torn-video/journal.md#2026-11-28-the-front-rule-on-frames-where-a000-equals-neither-buffer)._
* **ADR 0057's rule on run ends** (`[Bounded Observation]`, last frame of each `slot_clock` run, lavapipe renders): pairing by `render_tick` scores above the tag on `INTRO`, `BOMB`, `TRAINTNL` and `LOCATION` (+0.0054 to +0.0127 mean SSIM) and below it on `CTRY`, `LAND` and `BALLOON` (-0.0005 to -0.0014).
  The best offset is the rule's own on 46% to 75% of compared frames.
  `slot_ticks` varies within a run of one picture in 393 of 578 `CTRY` runs, so the tick a picture gets depends on which row of its run is read, and consecutive run ends share one `render_tick` while showing different pictures (296 of 296 shared keys on `CTRY`).
  Whether a run end is a whole picture is open.
  _Source: [reference check, replay and pairing](../../work/2026-11/1194_full-rate-video/journal.md#2026-11-27-reference-check-replay-and-the-pairing-rule-on-seven-full-rate-recordings)._

* **The ZMBV decoder** matched `ffmpeg -pix_fmt bgr0` byte for byte on all 1,907 frames of `vault-ctry/video/001` while it existed in `stunt-score`; #1133 deleted it, and the result is not reproducible from the tree.
* **Audio is stripped after the run** (`video_only`): `CTRY.FLM` 2.5 MB, `INTRO.FLM` 6.2 MB.
* **A long film runs out of Lua budget** (§ 4.7): `COL3-1.FLM` died near 24,500 frames, so `capture-video` covers films to about 5.5 minutes.
* **Sky colours are not unique in RGB**: an RGB sky mask mislabels 3.6% of pixels over 6,047 frames of 95 captures, touching the per-second scorer's IoU, not its SSIM.

_Source: [whole-film video](../../work/2026-11/distill-capture-dosbox-automation/journal.md#2026-10-31-video-capture), [slot words in the row](../../work/2026-11/1194_full-rate-video/journal.md#2026-11-27-location-with-the-slot-words-in-the-per-frame-row), [reference check, replay and pairing](../../work/2026-11/1194_full-rate-video/journal.md#2026-11-27-reference-check-replay-and-the-pairing-rule-on-seven-full-rate-recordings)._

### 4.7 The Instruction Budget and Three Retail Archives

* **A script runs one million Lua instructions across yields.**
  `[Established]` from the source (`src/lua/lua_engine.{h,cpp}`, `DefaultInstructionLimit`); no REST parameter sets it.
  The old per-frame trace cost about 92 instructions on a composed frame and 723 on another: about 10,900 or 1,380 frames a script (`[Bounded Observation]`).
* **`capture-video`'s row with the slot words fits `LOCATION.FLM`** (`[Bounded Observation]`, two runs): 11,616 frames ended `hold` under the million, so the row costs under about 86 instructions per frame including boot.
  The Lua host reports no count, so [#1194's](https://github.com/neilsh/stunt-reel/issues/1194#issuecomment-7227024791) estimate of 0.6 to 0.7M for the film (`[Supported Inference]`) is unchecked.
* **Patch #3's `PLAYONE.EXE` stalls on the retail `NewPLAY` archives of `TOD.FLM` and `INTRO.FLM`** (`[Supported Inference]`, one run per pairing): `TOD.FLM`'s clock falls to 0 near tick 200, `INTRO.FLM` holds its title card, so the trace spends its budget waiting for a held clock.
  Changing only the executable or only the archive makes each play; the engine files did not matter on `TOD.FLM`.
  Compare `BIGMAN` in [`patch3.md` § 3](patch3.md#3-which-build-each-film-needs).
* **`LOCATION.FLM` failed on length** (`[Supported Inference]`): it plays, but its 8,266 ticks outlast one per-frame trace; it captures on § 4.8's passes.
* **Build choice** (`[Established]` from the code): [`staging._engine_root`](../../python/stunt_reel/tac/staging.py) uses a film's own `PLAYONE.EXE`, and [`capture_run`](../../python/stunt_reel/capture_run.py) retries a stalled patch3 capture on the unpatched build.
  `meta.json` records `playone_build` and, since this round, `playone_sha256` ([`playone.layout_for`](../../python/stunt_reel/tac/playone.py)).

_Source: [instruction budget](../../work/2026-11/distill-capture-dosbox-automation/journal.md#2026-11-01-instruction-budget), [slot words in the row](../../work/2026-11/1194_full-rate-video/journal.md#2026-11-27-location-with-the-slot-words-in-the-per-frame-row), [archive, engine files or build](../../work/2026-11/distill-capture-dosbox-automation/journal.md#2026-11-01-archive-or-build)._

### 4.8 Clock and Window Passes

* **The budget stopped every long capture** (`[Bounded Observation]`, five films, 11,060 to 20,825 ticks). 209 of 529 distinct corpus films outlast the about 7,800 ticks one per-frame trace held.
* **Composed or torn** (`[Bounded Observation]`, four captures' meta): composed matches plus torn frames cover almost every traced frame, so "usable only when composed" rejects nearly what the 24-band tear test does.
* **Two passes cost per kept frame** ([`plan.run_stride_plan`](../../python/stunt_reel/tac/plan.py)).
  The clock pass reads only the film clock every 6 frames (`CLOCK_EVERY`); one window opens after the last sample below each stride goal; window passes, up to 40 windows each and eight at a time, dump the first frame at or past the goal that is changed, composed and outside a palette step.
  The dense trace stays for the light probe.
* **Drift between boots reached 5 ticks on `Act1.flm`** (`[Bounded Observation]`): 217 of 1,363 windows were more than 2 ticks off the clock pass, at most 5.
  A window labels its page with its own clock; a pass fails only past `MAX_WINDOW_SKEW_TICKS`.
* **Cost** (`[Bounded Observation]`): `Act1.flm` captured 1,341 frames, ticks 12 to 14,994, in 21 minutes (35 passes).
  Each pass runs in real time to its last window, so a 2,000-frame film should exceed 30 minutes (`[Supported Inference]`); the batch's capture timeout is 3,600 s.

_Source: [clock and window passes](../../work/2026-11/distill-capture-dosbox-automation/journal.md#2026-11-01-window-passes)._

## 5. HUD Timer Glyphs

`CTRY.FLM`'s HUD timer, `MM:SS.cc` in 3x5 digits at rows 179 to 183, decodes from video by a glyph table.
Its six digit cells start at columns 1, 5, 11, 15, 21 and 25, with the colon and dot between them, so the timer spans columns 1 to 27.
_Source: [scratch driver](../../work/2026-11/distill-capture-dosbox-automation/journal.md#2026-10-30-scratch-driver)._

---

## Ruled out

* A wall-clock start: one run in three began a frame late ([first evaluation](../../work/2026-11/distill-capture-dosbox-automation/journal.md#2026-10-30-first-evaluation)).
* A frame-for-frame match with DOSBox-X video: no timer-aligned pair is byte-identical ([second round](../../work/2026-11/distill-capture-dosbox-automation/journal.md#2026-10-30-second-round)).
* The dynamic core as a drop-in for the normal core at 8,000 cycles ([second round](../../work/2026-11/distill-capture-dosbox-automation/journal.md#2026-10-30-second-round)).
* A palette change at frame 2400: a one-frame offset in the HUD rows ([second round](../../work/2026-11/distill-capture-dosbox-automation/journal.md#2026-10-30-second-round)).
* REST port reads of the DAC per scored frame: 5.75 s per palette, not frame-locked ([second round](../../work/2026-11/distill-capture-dosbox-automation/journal.md#2026-10-30-second-round)).
* `Ctrl+Alt+F5` and `F11+I` through `SendInput` to start DOSBox-X video ([first evaluation](../../work/2026-11/distill-capture-dosbox-automation/journal.md#2026-10-30-first-evaluation)).
* A cheaper tear test as the fix for the `TOD.FLM`/`INTRO.FLM` stalls ([instruction budget](../../work/2026-11/distill-capture-dosbox-automation/journal.md#2026-11-01-instruction-budget)).
* A harness change since the `vault-intro` captures ([instruction budget](../../work/2026-11/distill-capture-dosbox-automation/journal.md#2026-11-01-instruction-budget)).
* The archive alone as the cause of the two stalls, or the engine files as `TOD.FLM`'s ([archive, engine files or build](../../work/2026-11/distill-capture-dosbox-automation/journal.md#2026-11-01-archive-or-build)).
* `LOCATION.FLM`'s archive or build as its cause ([archive, engine files or build](../../work/2026-11/distill-capture-dosbox-automation/journal.md#2026-11-01-archive-or-build)).
* The Patch 3 build, the window-pass harness, or a still scene as the cause of differing replays: unpatched builds also differ (`BALLOON` 24 of 101 pages, `BOMB` 110 of 292), the demo `CTRY.ALL` replays identically under the current harness on either build, and `vault-location` moves more than the short films ([what does not make recaptures differ](../../work/2026-11/305_recapture-noise/journal.md#2026-11-09-what-does-not-make-recaptures-differ), [sound samples](../../work/2026-11/305_recapture-noise/journal.md#2026-11-09-sound-samples-in-the-archive-make-replays-differ)).
* Matching a page to the render tick it agrees with best: our render agrees too loosely to resolve one tick from the next ([what does not make recaptures differ](../../work/2026-11/305_recapture-noise/journal.md#2026-11-09-what-does-not-make-recaptures-differ)).
* A palette (DAC lag) difference alone as the cause of a page not equal to a video frame: some palette index shows two video colours on every one of the 466 mismatched `CTRY` and `LOCATION` pages ([reference check](../../work/2026-11/1194_full-rate-video/journal.md#2026-11-27-reference-check-replay-and-the-pairing-rule-on-seven-full-rate-recordings)).
* The frame before a `slot_clock` change as a finished picture without a check: the neighbour-frame torn test failed on a `CTRY` window ([#1200 comment](https://github.com/neilsh/stunt-reel/issues/1200#issuecomment-7228756891)).
* A relaunch loop in a `THE.FLM` capture (`--max-frames 1200`) stopped after 20 minutes with no frame and no output, by inference (`[Hypothesis]`: its log is gone, so it is taken to have behaved like the rerun): the same command on 2026-11-20 finished in 1,004 s with 1,192 frames, its 30 window passes each launching a DOSBox with a new `dosbox-<n>.conf`; `capture-ref` printed no per-pass progress line after queueing them, only DOSBox's own launch chatter, and wrote the frames only at the end (§ 4.8) ([THE.FLM's high shadows in the captured pixels](../../work/2026-11/628_high-actor-shadow-pixels/journal.md#2026-11-20-theflms-high-shadows-in-the-captured-pixels)).
* Fixed strip-boundary rows as where the video tears: none in `CTRY.FLM`, and the emulator draws mode 13h one row at a time ([where tears fall, and debugmsg as a sink](../../work/2026-11/1211_torn-video/journal.md#2026-11-27-where-tears-fall-and-debugmsg-as-a-sink)).
* `nosound = true` to make `COUNT.FLM` repeat: three variants in four runs ([production harness](../../work/2026-11/distill-capture-dosbox-automation/journal.md#2026-10-30-production-harness)).

## Open questions

1. What leaves 653, 489 and 1,082 pixels at DOSBox-X ticks 220, 495 and 660 with no exact dosbox-automation page (§ 3)?
   Is it a sub-tick state, a tear, or DOSBox-X variance?
   Capture two DOSBox-X runs of the same film to measure its own variance first.
2. Does a breakpoint at image `0x7417` (end of the `A000` diff-copy) give a whole page?
   It was read from the listing, not tried (§ 4.3).
3. Does an `INTRO.FLM` fade (frames 6140–6400), or a second cycle count, show the one-frame and two-frame DAC lag of § 4.5?
4. What else lives in the `DS = 0x15D4` segment (image `0x15D40` onward) that deserves a [`memory-map-vm.md`](memory-map-vm.md) entry, and what are the other relocated segment words `0x1DE7`, `0x1DEA` and `0x20F6`?
5. Likely answered (`[Supported Inference]`, § 4.4): the sound sample in `COUNT.FLM`'s archive; the three fallback setups were not needed.
6. Do the patched `PLAYONE.EXE` (Patch #3) and its `DS`, film clock and working-palette offsets match the unpatched build's, and which films need which build?
7. Does the torn rate scale as 1/cycles (§ 4.5)?
   A trace at 7,000 cycles should show about six times the rate at 45,000.
8. Do other films double-buffer through `DS:0x22CA` and `0x22CC`?
   A film that does not would read as never torn; `torn_frames` per film in a batch survey would show it.
9. Why does `vault-intro/frames/005`, with torn pages replaced by their clean neighbours, score 0.0044 SSIM below `004` (§ 4.5)?
   Scoring the ten `004` picks that were torn against their `005` replacements, tick by tick, would show whether the tear or the render dominates.
10. What in the retail `NewPLAY` archives of `TOD.FLM` and `INTRO.FLM` stalls the patched `PLAYONE.EXE` (§ 4.7), which `MAKEONE` built them, and what does the patched build do at the stall?
    The retail `TOD.ALL` is 140,260 bytes and the patched `MAKEONE`'s 49,732, so a resource-by-resource diff would show the first; after the stall the working palette at `0x20EE` reads values above 63.
11. Answered for `TOD.FLM` and `INTRO.FLM`: a stalled film needs a playing pairing (§ 4.7), not an end test that would turn a stall into a valid-looking capture of the wrong picture.
12. Which other `NewPLAY` films stall on the patched build?
    Five played on it in the batch (`CTRY`, `HIGHWAYS`, `SPLANES`, `BALLOON`, `TRAINTNL`); the rest were not surveyed on both builds.
13. Should a film whose clock already runs at the clock pass's first sample keep its first goal?
    `Act1.flm`'s (tick 1) was left out, so its capture starts at tick 12.
14. Is drift between boots (§ 4.8, up to 5 ticks on `Act1.flm`) a property of film length, the film, or host load?
    Two clock passes of one film, alone and under `--jobs 3`, would tell.
15. Do two pages labelled with one `film_tick` show the same moment?
    On `vault-balloon` tick 265 a reference page and a recapture page agree best with renders 3 ticks apart (264 and 267), which § 4.4's "never mislabels" would not allow, if confirmed; one page checked ([`../parity/metric-bench.md`](../parity/metric-bench.md#221-recapture-noise-of-the-reference-films) § 2.2.1).
    Matching pages to render ticks cannot settle it at today's render fidelity (Ruled out).
    Across captures with different settings they often are not the same page: on LOCATION the stubbed Patch 3 reference's pages (rows 0..184) are index-identical at 406 of 645 shared tags with a Patch 3 capture with sound, 277 of 625 with an unpatched one with sound and 281 of 629 with an unpatched stubbed one, against 745 of 745 for a stubbed Patch 3 repeat.
    In aggregate, which is what escapes the single-page objection above, the differing pages also differ in tick: where the reference prefers a render offset off the page lag and the other page differs by over 100 pixels, the other capture prefers the same offset on 5 of 33 such tags, 6 of 64 and 8 of 58 (all ticks; outside the canyon run 4 of 32, 4 of 61, 4 of 53), nearly always preferring offset 0 instead ([`capture.md` § 4](capture.md#4-observed-results)).
    _Source: [a frame's off-model tick changes with the capture's settings](../../work/2026-11/1033_per-frame-time-offsets/journal.md#2026-11-23-a-frames-off-model-tick-changes-with-the-captures-settings)._
    On CTRY (unpatched build, sound stubbed, one capture of each archive, both scored against one render of the own archive with `--waive-archive-conflict`) two captures' pages at one tag can show different ticks: on 12 of the 23 viewpoint pages where the own and #348's padded archive differ, the padded page's agreement curve over render offsets, peaked, fits the own page's a tick apart, where 28 of the 29 other differing pages fit the same tick ([`film-load.md`](film-load.md) § 5).
    3 more viewpoint pages fit a tick apart on near-flat curves, where a level offset between the arms, which the waived archive conflict can give, can pass for a shift; 6 are undecided.
    What resolves one tick there is matching one capture's curve to the other's, not each page's best offset, which on CTRY's pages from 1145 sits at +1 or +2 in both captures.
    The film step sets the slots' fraction from the clock it reads before the render and the HUD clock is read after it, so the HUD clock does not date the slots either; 5 of the 12 pages show one HUD clock in both captures.
    How many ticks each captured page trails its tag stays open, on CTRY and the other films: the shift is relative, and no capture's page was dated by the film step's clock.
    _Source: [on 12 viewpoint pages the two arms' scenes are one tick apart](../../work/2026-11/826_ctry-padded-viewpoint/journal.md#2026-11-24-on-12-viewpoint-pages-the-two-arms-scenes-are-one-tick-apart)._
16. Why does `vault-location` replay nearly bit for bit when its archive holds a sample-like chunk (`0xC447`) and six music chunks (§ 4.4)?
    The film may never play `0xC447`; its `0x9C` cues are not checked.
17. How does sound playback move the picture (§ 4.4): the render loop's pacing, the tick a page's render starts from, or something else?
    And does a page captured without samples show its labelled tick more often than one with them?
    Not measurably on LOCATION, one capture per setting: a best render offset off the page lag that beats offset 0 by over 0.01 of index agreement falls on 168 of 732 scored frames stubbed and 172 of 733 with sound on Patch 3, and on 161 of 732 stubbed and 162 of 732 with sound on the unpatched build.
    _Source: [a frame's off-model tick changes with the capture's settings](../../work/2026-11/1033_per-frame-time-offsets/journal.md#2026-11-23-a-frames-off-model-tick-changes-with-the-captures-settings)._
18. Likely answered (`[Supported Inference]`): `vault-location`'s 2 to 3 differing pages per with-sound pair (captured one after the other) came from its sound-range chunks; a stubbed pair agreed on 745 of 745 (§ 4.4).
19. Is the last frame of a `slot_clock` run a whole picture?
    An emulator-logged per-frame `composed` flag (`A000` rows 0..191 against the buffers at `PlayoneLayout.composed_pages`) checked on `CTRY` video frames 300 to 317, where 8 are finished and 5 torn, would settle it and give `derived.json` a `finished` column; `TickLog` takes one more optional column without a schema bump.
