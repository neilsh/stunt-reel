---
summary: "dosbox-automation 0.85.1 as capture emulator: frame-locked capture reading `film_tick` per frame at `DS = 0x0F46`, bit-identical `CTRY.FLM` runs with the demo archive, replays made to differ by sound samples in the archive, torn pages, DAC lag and the Lua instruction budget."
---
# `PLAYONE.EXE`: Capture with dosbox-automation (Frame-Locked Video)

[dosbox-automation](https://github.com/dosbox-automation/dosbox-automation/) 0.85.1, a DOSBox Staging fork with a REST and Lua API (GPL-2.0-or-later), is the capture emulator. `stunt_reel/tac` drives it ([ADR 0025](../../docs/adr/0025-capture-runs-are-plans-not-sessions.md)): [`luagen.py`](../../python/stunt_reel/tac/luagen.py) writes the scripts, [`plan.py`](../../python/stunt_reel/tac/plan.py) runs the passes, [`framebuffer.py`](../../python/stunt_reel/tac/framebuffer.py) writes the capture. The retired DOSBox-X harness: [`dosbox-x-legacy.md`](dosbox-x-legacy.md). Measurements ran 2026-10-30 to 2026-11-01 on one host with 16 logical cores.

---

## 1. What the Tool Offers

* **Install:** pinned in `mise.toml`; `mise exec -- dosbox` runs it.
* **Control:** REST on `127.0.0.1:<webserver_port>` with a bearer token (`DOSBOX_API_TOKEN`, 64 hex characters or the emulator discards it), and a Lua script on the emulation thread (`POST /api/v1/script/load`, `/start`, `GET /status`; results in `dosbox.output`).
* **Guest access:** REST `memory`, `cpu/state` and `io/port`; Lua `dosbox.mem_read[_word]`, `frame()` and `wait_frames(n)`.
* **Capture:** `dosbox.capture_start()` / `capture_stop()` records lossless ZMBV AVI, one video frame per emulated frame. The REST call takes only `mode` (`raw` or `rendered`); nothing drops the audio stream.
* **Absent:** the debugger (`debugger` is `false` in the OpenAPI document): no breakpoints, pause, step or address hooks ([ADR 0034](../../docs/adr/0034-breakpoints-run-on-dosbox-x.md)).
* **Mounts:** a mount under `Temp` or far from its conf is refused (`MOUNT: Blocked`), so the conf and mount sit together under the data root.

_Source: [first evaluation](../../work/2026-11/distill-capture-dosbox-automation/journal.md#2026-10-30-first-evaluation), [scratch driver](../../work/2026-11/distill-capture-dosbox-automation/journal.md#2026-10-30-scratch-driver), [whole-film video](../../work/2026-11/distill-capture-dosbox-automation/journal.md#2026-10-31-video-capture)._

## 2. Frame-Locked Capture

A script starts capture and presses the dialog keys at fixed emulated frames (`dosbox.frame()` counts from boot), then reads guest memory each frame.

* **`DGROUP` is `DS = 0x0F46`** for `CTRY.FLM` and `INTRO.FLM` on the unpatched build, with DOSBox-X's offsets. `cpu/state` reports the running code's `DS` (`0x17C9` while `CS` is `0x0A19`, § 4.3), so scripts read `0x0F46:offset`. `[Bounded Observation]`
* **`CTRY.FLM` replays bit for bit with the demo's `.ALL`.** Nine runs at 8,000 cycles and 12, 16 and 24 runs started together gave identical video and tick logs, with no dropped frames; three `INTRO.FLM` runs gave identical video, all on the unpatched build with the demo's `.ALL`. Not every film replays (§ 4.4), and with a Patch 3 `MAKEONE` archive, which carries in full the sound samples the demo's `.ALL` shortens (§ 4.4), two captures run one after the other differed on 27 of 104 paired `CTRY.FLM` pages and 78 of 172 `INTRO.FLM` pages (2026-11-08, [`../parity/method.md`](../parity/method.md) § 2.2.1). `[Bounded Observation]`
* **Video frame *j* is emulated frame `capture_start_frame + j`**, at 70.087 Hz. The HUD timer (`film_tick / 50`, redrawn per render loop) trails the live tick by 0 to 3 ticks between render loops. `[Bounded Observation]`
* **Recorded RGB is the DAC**, each 6-bit component expanded as `round(x * 255 / 63)` with zero error on the indices checked. Two indices can share an RGB, so video does not always give the index plane: index scoring uses the page (§ 4.1). `[Bounded Observation]`

_Source: [first evaluation](../../work/2026-11/distill-capture-dosbox-automation/journal.md#2026-10-30-first-evaluation), [follow-up](../../work/2026-11/distill-capture-dosbox-automation/journal.md#2026-10-30-follow-up), [second round](../../work/2026-11/distill-capture-dosbox-automation/journal.md#2026-10-30-second-round)._

## 3. DOSBox-X Video for Comparison

* **The guest runs at another speed.** At 8,000 cycles dosbox-automation completes 424 render loops of `CTRY.FLM` against DOSBox-X's 369; at 7,000 the counts agree (370), yet none of 58 timer-aligned frames is byte-identical. `[Bounded Observation]`
* **DOSBox-X expands the DAC as `(v << 2) | (v >> 4)`**, one away from `round(v * 255 / 63)` at levels 11 to 15 and 48 to 52, read from its source, not measured. `[Supported Inference]`
* **Wider differences are mostly another instant** of `vault-ctry/frames/001`: index differences before the fade, another fade phase in it (96%); the page lags the clock by a different number of ticks in each emulator. `[Bounded Observation]`

_Source: [first evaluation](../../work/2026-11/distill-capture-dosbox-automation/journal.md#2026-10-30-first-evaluation), [second round](../../work/2026-11/distill-capture-dosbox-automation/journal.md#2026-10-30-second-round), [third round](../../work/2026-11/distill-capture-dosbox-automation/journal.md#2026-10-30-third-round), [fourth round](../../work/2026-11/distill-capture-dosbox-automation/journal.md#2026-10-30-fourth-round)._

## 4. Measurements

### 4.1 Guest Speed, Cores and Page Reads

* **Render loops scale with `cpu_cycles`** (`CTRY.FLM`, normal core): 318 at 6,000, 370 at 7,000, 424 at 8,000, 631 at 12,000, 827 at 16,000. `[Bounded Observation]`
* **At 8,000 cycles the dynamic core does not replay the normal core**: 417 loops, clocks a tick or two apart from frame 2067, pictures different from frame 1280. `[Bounded Observation]`
* **A page and working palette read in one Lua step see one instant**, since Lua blocks the emulation: `mem_read(0xA000, 0, 64000)` and `mem_read(0x0F46, 0x2768, 768)` (6-bit). The game draws straight into `A000`. The Lua heap limits a pass: 90 pages (about 11.5 MB of hex) failed with `not enough memory`, 40 work (`MAX_DUMPS`). `[Bounded Observation]`
* **A page can match no video frame**: of 97 `INTRO.FLM` pages, four palette races and ten mid-render reads (§ 4.5). `[Bounded Observation]`

_Source: [follow-up](../../work/2026-11/distill-capture-dosbox-automation/journal.md#2026-10-30-follow-up), [second round](../../work/2026-11/distill-capture-dosbox-automation/journal.md#2026-10-30-second-round), [third round](../../work/2026-11/distill-capture-dosbox-automation/journal.md#2026-10-30-third-round), [fourth round](../../work/2026-11/distill-capture-dosbox-automation/journal.md#2026-10-30-fourth-round), [production harness](../../work/2026-11/distill-capture-dosbox-automation/journal.md#2026-10-30-production-harness)._

### 4.2 No Render Counter in `DGROUP`

A per-frame diff of `DS:0000..FFFE` over 90 `CTRY.FLM` frames found no render counter: the one byte that stepped near the loop rate, `DS:0x578C`, is a cycling index. A render-complete signal has to come from the code. `[Bounded Observation]` _Source: [third round](../../work/2026-11/distill-capture-dosbox-automation/journal.md#2026-10-30-third-round)._

### 4.3 The Render Path and Segments

`[Supported Inference]`, static, from the unpacked image.

* **`set_palette` (image `0x7B70`, vtable `DS:0x2252`) uploads the DAC in two retrace-gated 384-byte halves**: `call 7B79` waits for retrace and runs `rep outsb`, and its `ret` at `0x7B8E` (`0F17:0C5E`) returns into `0x7B79` for the second half. Whether DOSBox-X's `BP 0D51:0C5E` named these bytes is open ([`dosbox-x-legacy.md`](dosbox-x-legacy.md)).
* **The `A000` update never waits for retrace.** Vtable entry `0x738C` swaps the buffers `[22CA]`/`[22CC]`, diff-copies to `A000` (`0x73A8` to `0x73D6`), draws sprites and ends at `0x7417`, not tried as a breakpoint.
* **`CS = 0x0A19` and `DS = 0x17C9` are the same image**, loaded at paragraph `0x1F5`: the VM code segment (image `0x8240`) and a second work segment of about 111 KB (image `0x15D40`) holding the anchor table and VM variables, set by `mov ax,15D4h` at image `0xB012`. `0x336B` and `0x430B` lie past the image end, DOS-allocated `[Hypothesis]`, and hold the composed pages (§ 4.5).

_Source: [fourth round](../../work/2026-11/distill-capture-dosbox-automation/journal.md#2026-10-30-fourth-round), [torn pages](../../work/2026-11/distill-capture-dosbox-automation/journal.md#2026-10-31-torn-pages)._

### 4.4 The Capture Profile and Replays

* **The render rate saturates near 45,000 cycles** (`CTRY.FLM`, normal core): new pages on 46% of frames at 7,000, 98% at 30,000, 99% from 35,000 to about 100,000, fewer above (`max`: 80% to 95%). Wall time is the same at every value. `[Bounded Observation]`
* **The `capture` profile, shared by `play`, is the dynamic core at 45,000 cycles**: the normal core's rate within about 1%, 0.22 to 0.24 of a host core against 0.39, its own traces byte-identical. Dump passes run up to eight at once, each launch with its own `dosbox-<port>.conf`. `[Bounded Observation]`
* **Replays are not always identical.** Five `COUNT.FLM` traces gave four variants, a tick apart in 10 to 18 of 157 frames; `nosound` kept it, and `sbtype = none` stopped the film. The cause is untested on `COUNT.FLM` (open question 5). Each page carries the tick its own pass read (§ 4.8). `[Bounded Observation]`
* **Sound samples in the archive make replays differ** (`[Bounded Observation]` on `BALLOON.FLM`, 2026-11-09). Two captures of `MAKEONE`'s `BALLOON.ALL` on Patch 3, the second started 0.1 s after the first, differed on 26 of 102 pages they both hold; the same archive with both its chunks in `0xC000`–`0xCFFF` (the samples `0xC307` and `0xC565`) cut to one byte, captured the same way, agreed on 108 of 108. `CTRY.FLM` fits without a controlled pair: the 2026-11-08 pair from `MAKEONE`'s `CTRY.ALL`, captured one after the other, differed on 27 of the 111 pages both held, and a pair from the same archive with its five chunks in that range cut to one byte, started 0.1 s apart, agreed on 121 of 121 (2026-11-09). The demo's `CTRY.ALL`, whose samples `0xC302` and `0xC31E` are one byte and `0xC319` 1,839 bytes, also agreed on 121 of 121 across three captures. Which chunk in the range matters is not isolated. `vault-location` replays nearly bit for bit although `MAKEONE`'s `LOCATION.ALL` holds a sample-like chunk (`0xC447`, 6,034 bytes) and six music chunks in the range: why is open question 16. Stubbing also changes the pictures: the stubbed `BALLOON` capture differs from the with-sound reference on 66 of 96 pages, more than two with-sound captures differ, so the samples change what is drawn, not only how repeatably. How is not measured. _Source: [sound samples in the archive](../../work/2026-11/305_recapture-noise/journal.md#2026-11-09-sound-samples-in-the-archive-make-replays-differ)._
* **Captures play the film with its sound samples stubbed** ([ADR 0043](../../docs/adr/0043-captures-play-with-the-archives-sound-samples-stubbed.md)).
  - Staging replaces each payload in `0xC000`–`0xCFFF` with the one byte `0x04`, the stub the demo's `CTRY.ALL` holds in `0xC302`. `--sound-samples kept` plays the archive as is, and `meta.json` records which was used.
  - The range holds two kinds of chunk: sample-like chunks, whose first byte is `0x00` or `0x02` (the source of those under `0xC4` and `0xC5` is unchecked), and music, chunks that begin `03 'FORM'` under `0xC0` and `0xC1` ([`linking.md`](../makeone-exe/linking.md) § 5). The demo's `CTRY.ALL` shortens its samples and keeps its music chunk (`0xC010`) whole; the stub replaces both kinds. `[Bounded Observation]`
  - What is known: two captures with the stub replayed identically on `BALLOON.FLM` and `CTRY.FLM`, from `MAKEONE`'s archives.
  - What is not known: what it does with the byte, whether it skips the sample or plays a click. A zero-length payload and a minimal well-formed sample were not tried. `[Bounded Observation]`
* **The mouse cursor is parked** below the 3D view by `dosbox.mouse_move(-2000, 2000)`, lighting no button; captures before 2026-10-31 show it at screen centre. `[Bounded Observation]`

_Source: [production harness](../../work/2026-11/distill-capture-dosbox-automation/journal.md#2026-10-30-production-harness)._

### 4.5 Torn Pages and the DAC Lag

* **A page read in the frame callback can be torn** (`[Supported Inference]`): the `A000` update (§ 4.3) takes tens of thousands of cycles and a frame boundary can land inside it. The composed pages' segments are in `DS:0x22CA` and `0x22CC`, swapped every render; after a finished copy rows 0–191 of `A000` equal one, and a torn page takes its top rows from one and the rest from the other.
* **How often** (`[Bounded Observation]`, `capture` profile): 66 of 1,908 `CTRY.FLM` frames (4.1% of changed frames) and 127 of 5,384 `INTRO.FLM` frames (2.9%). Rate against cycles: open question 7.
* **The DAC lags the working palette** (`[Bounded Observation]`, one `CTRY.FLM` fade, five steps): with page *f* the DAC's low half is `W(f-1)` and its high half `W(f-2)`. An `INTRO.FLM` fade showed each step's mixed frame as low half new, high half previous in 180 of 180 samples.
* **The harness** skips torn frames and the two frames of each palette step ([`plan.py`](../../python/stunt_reel/tac/plan.py)). `meta.json` counts `composed_matches`; zero, which `capture-ref` warns about, means wrong `composed_pages` offsets.
* **Skipping torn pages did not raise the score**: `vault-ctry/frames/005` SSIM 0.7800 against `004`'s 0.7808, `vault-intro/frames/005` 0.5444 against 0.5488. Why `INTRO.FLM` falls is open question 9. `[Bounded Observation]`

_Source: [torn pages](../../work/2026-11/distill-capture-dosbox-automation/journal.md#2026-10-31-torn-pages), [fourth round](../../work/2026-11/distill-capture-dosbox-automation/journal.md#2026-10-30-fourth-round)._

### 4.6 Whole-Film Video Capture

`mise run capture-video` ([`video.py`](../../python/stunt_reel/tac/video.py)) logs both clocks every frame and the working palette when it changes, until the clock holds 30 frames. `[Bounded Observation]`:

* **One log row per video frame** in three films; the first four ticks run before recording starts.
* **The ZMBV decoder** ([`zmbv.rs`](../../crates/stunt-cli/src/zmbv.rs)) matches `ffmpeg -pix_fmt bgr0` byte for byte on all 1,907 frames of `vault-ctry/video/001`.
* **Audio is stripped after the run** (`video_only`): `CTRY.FLM` is then 2.5 MB, `INTRO.FLM` 6.2 MB.
* **A long film runs out of Lua budget** (§ 4.7): `COL3-1.FLM` died near 24,500 frames, so `capture-video` covers films up to about 5.5 minutes.
* **Sky colours are not unique in RGB**: an RGB sky mask mislabels 3.6% of pixels over 6,047 frames of 95 captures, touching the per-second scorer's IoU, not its SSIM.

_Source: [whole-film video](../../work/2026-11/distill-capture-dosbox-automation/journal.md#2026-10-31-video-capture)._

### 4.7 The Instruction Budget and Three Retail Archives

* **A script runs one million Lua instructions, counted across yields.** `[Established]` from the source (`src/lua/lua_engine.{h,cpp}`, `DefaultInstructionLimit`); no REST parameter sets it. The old per-frame trace cost about 92 instructions on a composed frame and 723 on another, so one script held about 10,900 or 1,380 frames (`[Bounded Observation]`).
* **Patch #3's `PLAYONE.EXE` stalls on the retail `NewPLAY` archives of `TOD.FLM` and `INTRO.FLM`** (`[Supported Inference]`, one run per pairing): `TOD.FLM`'s clock falls to 0 near tick 200, `INTRO.FLM` holds its title card, so the trace spends its budget waiting for a held clock. Changing only the executable or only the archive makes each play; the engine files did not matter on `TOD.FLM`. Compare `BIGMAN` in [`patch3.md` § 3](patch3.md#3-which-build-each-film-needs).
* **`LOCATION.FLM` failed on length** (`[Supported Inference]`): it plays, but its 8,266 ticks outlast one per-frame trace. It captures on the passes of § 4.8.
* **Build choice** (`[Established]` from the code): [`staging._engine_root`](../../python/stunt_reel/tac/staging.py) uses a film's own `PLAYONE.EXE`, and [`capture_run`](../../python/stunt_reel/capture_run.py) retries a stalled patch3 capture on the unpatched build. `meta.json` records `playone_build` and, since this round, `playone_sha256` ([`playone.layout_for`](../../python/stunt_reel/tac/playone.py)).

_Source: [instruction budget](../../work/2026-11/distill-capture-dosbox-automation/journal.md#2026-11-01-instruction-budget), [archive, engine files or build](../../work/2026-11/distill-capture-dosbox-automation/journal.md#2026-11-01-archive-or-build)._

### 4.8 Clock and Window Passes

* **The budget stopped every long capture** (`[Bounded Observation]`, five films of 11,060 to 20,825 ticks). 209 of 529 distinct corpus films outlast the about 7,800 ticks one per-frame trace held.
* **Composed or torn** (`[Bounded Observation]`, four captures' meta): composed matches plus torn frames account for almost every traced frame, so "usable only when composed" rejects nearly the frames the 24-band tear test does.
* **Two passes cost per kept frame** ([`plan.run_stride_plan`](../../python/stunt_reel/tac/plan.py)). The clock pass reads only the film clock every 6 frames (`CLOCK_EVERY`); one window opens after the last sample below each stride goal; window passes, up to 40 windows each and eight at a time, dump the first frame at or past the goal that is changed, composed and outside a palette step. The dense trace stays for the light probe.
* **Drift between boots reached 5 ticks on `Act1.flm`** (`[Bounded Observation]`): 217 of 1,363 windows were more than 2 ticks off the clock pass, at most 5. A window labels its page with its own clock; a pass fails only past `MAX_WINDOW_SKEW_TICKS`.
* **Cost** (`[Bounded Observation]`): `Act1.flm` captured 1,341 frames over ticks 12 to 14,994 in 21 minutes (35 passes). Each pass runs in real time to its last window, so a 2,000-frame long film should exceed 30 minutes (`[Supported Inference]`); the batch's capture timeout is 3,600 s.

_Source: [clock and window passes](../../work/2026-11/distill-capture-dosbox-automation/journal.md#2026-11-01-window-passes)._

## 5. HUD Timer Glyphs

`CTRY.FLM`'s HUD timer, `MM:SS.cc` in 3x5 digits at rows 179 to 183, decodes from video by a glyph table. _Source: [scratch driver](../../work/2026-11/distill-capture-dosbox-automation/journal.md#2026-10-30-scratch-driver)._

---

## Ruled out

* A wall-clock start: one run in three began a frame late ([first evaluation](../../work/2026-11/distill-capture-dosbox-automation/journal.md#2026-10-30-first-evaluation)).
* A frame-for-frame match with DOSBox-X video: no timer-aligned pair is byte-identical ([second round](../../work/2026-11/distill-capture-dosbox-automation/journal.md#2026-10-30-second-round)).
* The dynamic core as a drop-in for the normal core at 8,000 cycles ([second round](../../work/2026-11/distill-capture-dosbox-automation/journal.md#2026-10-30-second-round)).
* A palette change at frame 2400: a one-frame offset in the HUD rows ([second round](../../work/2026-11/distill-capture-dosbox-automation/journal.md#2026-10-30-second-round)).
* REST port reads of the DAC per scored frame: 5.75 s per palette, not frame-locked ([second round](../../work/2026-11/distill-capture-dosbox-automation/journal.md#2026-10-30-second-round)).
* `Ctrl+Alt+F5` and `F11+I` through `SendInput` to start DOSBox-X video ([first evaluation](../../work/2026-11/distill-capture-dosbox-automation/journal.md#2026-10-30-first-evaluation)).
* A cheaper tear test as the fix for the `TOD.FLM` and `INTRO.FLM` stalls ([instruction budget](../../work/2026-11/distill-capture-dosbox-automation/journal.md#2026-11-01-instruction-budget)).
* A harness change since the `vault-intro` captures ([instruction budget](../../work/2026-11/distill-capture-dosbox-automation/journal.md#2026-11-01-instruction-budget)).
* The archive alone as the cause of the two stalls, or the engine files as the cause of `TOD.FLM`'s ([archive, engine files or build](../../work/2026-11/distill-capture-dosbox-automation/journal.md#2026-11-01-archive-or-build)).
* `LOCATION.FLM`'s archive or build as its cause ([archive, engine files or build](../../work/2026-11/distill-capture-dosbox-automation/journal.md#2026-11-01-archive-or-build)).
* The Patch 3 build, the window-pass harness, or a still scene as the cause of replays that differ: unpatched builds also differ (`BALLOON` 24 of 101 pages, `BOMB` 110 of 292), the demo `CTRY.ALL` replays identically under the current harness on either build, and `vault-location` moves more than the short films ([what does not make recaptures differ](../../work/2026-11/305_recapture-noise/journal.md#2026-11-09-what-does-not-make-recaptures-differ), [sound samples](../../work/2026-11/305_recapture-noise/journal.md#2026-11-09-sound-samples-in-the-archive-make-replays-differ)).
* Matching a page to the render tick it agrees with best, to see which tick it shows: our render agrees too loosely to resolve one tick from the next ([what does not make recaptures differ](../../work/2026-11/305_recapture-noise/journal.md#2026-11-09-what-does-not-make-recaptures-differ)).

## Open questions

1. What leaves 653, 489 and 1,082 pixels at DOSBox-X ticks 220, 495 and 660 with no exact dosbox-automation page (§ 3)? Is it a sub-tick state, a tear, or DOSBox-X variance? Capture two DOSBox-X runs of the same film to measure its own variance first.
2. Does a breakpoint at image `0x7417` (end of the `A000` diff-copy) give a whole page? It was read from the listing, not tried (§ 4.3).
3. Does an `INTRO.FLM` fade (frames 6140–6400), or a second cycle count, show the one-frame and two-frame DAC lag of § 4.5?
4. What else lives in the `DS = 0x15D4` segment (image `0x15D40` onward) that deserves a [`memory-map.md`](memory-map.md) entry, and what are the other relocated segment words `0x1DE7`, `0x1DEA` and `0x20F6`?
5. Does `COUNT.FLM` vary for the same reason as `BALLOON.FLM`, sound samples in its archive (§ 4.4)? Its `nosound` traces still varied; `nosound` silences the host mixer, and whether the emulated Sound Blaster still paces playback then is not known. A capture pair from its archive with the samples stubbed would show it.
6. Do the patched `PLAYONE.EXE` (Patch #3) and its `DS`, film clock and working-palette offsets match the unpatched build's, and which films need which build?
7. Does the torn rate scale as 1/cycles (§ 4.5)? A trace at 7,000 cycles should show about six times the rate at 45,000.
8. Do other films double-buffer through `DS:0x22CA` and `0x22CC`? A film that does not would read as never torn; `torn_frames` per film in a batch survey would show it.
9. Why does `vault-intro/frames/005`, with torn pages replaced by their clean neighbours, score 0.0044 SSIM below `004` (§ 4.5)? Scoring the ten `004` picks that were torn against their `005` replacements, tick by tick, would show whether the tear or the render dominates.
10. What in the retail `NewPLAY` archives of `TOD.FLM` and `INTRO.FLM` stalls the patched `PLAYONE.EXE` (§ 4.7), which `MAKEONE` built them, and what does the patched build do at the stall? The retail `TOD.ALL` is 140,260 bytes and the patched `MAKEONE`'s 49,732, so a resource-by-resource diff would show the first; after the stall the working palette at `0x20EE` reads values above 63.
11. Answered for `TOD.FLM` and `INTRO.FLM`: a stalled film needs a playing pairing (§ 4.7), not an end test on a clock back at 0 or a one-colour page, which would turn a stall into a valid-looking capture of the wrong picture.
12. Which other `NewPLAY` films stall on the patched build? Five played on it in the batch (`CTRY`, `HIGHWAYS`, `SPLANES`, `BALLOON`, `TRAINTNL`); the rest of the folder was not surveyed on both builds.
13. Should a film whose clock already runs at the clock pass's first sample keep its first goal? `Act1.flm`'s first window goal (tick 1) was left out because no sample below it exists, so its capture starts at tick 12; a window at the first sample frame would cover it.
14. Is drift between boots (§ 4.8, up to 5 ticks on `Act1.flm`) a property of film length, of the film, or of host load? Two clock passes of one long film, alone and under `--jobs 3`, would separate them.
15. Do two pages labelled with one `film_tick` show the same moment? On `vault-balloon` tick 265 a reference page and a recapture page agree best with renders 3 ticks apart (264 and 267), which § 4.4's "never mislabels" would not allow, if confirmed; one page checked ([`../parity/method.md`](../parity/method.md) § 2.2.1). Matching pages to render ticks cannot settle it at today's render fidelity (Ruled out).
16. Why does `vault-location` replay nearly bit for bit when its archive holds a sample-like chunk (`0xC447`) and six music chunks (§ 4.4)? The film may never play `0xC447`; its `0x9C` cues are not checked.
17. How does sound playback move the picture (§ 4.4): the render loop's pacing, the tick a page's render starts from, or something else? And does a page captured without samples show its labelled tick more often than one with them?
18. What leaves 2 to 3 differing pages per `vault-location` pair (§ 4.4)? A stubbed pair would show whether its sound-range chunks do.
