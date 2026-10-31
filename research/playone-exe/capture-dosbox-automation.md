# `PLAYONE.EXE`: Capture with dosbox-automation (Frame-Locked Video)

The DOSBox-X debugger harness is in [`capture.md`](capture.md) and its speed and repeatability limits are in [`capture-speed.md`](capture-speed.md). This note evaluates a different capture tool: [dosbox-automation](https://github.com/dosbox-automation/dosbox-automation/) 0.85.1 (a DOSBox Staging fork with a REST and Lua API, GPL-2.0-or-later) recording lossless video of `CTRY.FLM`, with a per-frame film clock read from guest memory.

`[Bounded Observation]`, 2026-10-30, `CTRY.FLM` only, 16 logical cores, `cpu_cycles = 8000`, `core = normal`, three runs of DOSBox-X video and nine of dosbox-automation. No tracked code changed except the tool pin in [`mise.toml`](../../mise.toml); the driver scripts were scratch work under the data root and are not committed. Row in [`../parity/log.md`](../parity/log.md).

---

## 1. What the Tool Offers

* **Install:** `"github:dosbox-automation/dosbox-automation" = 0.85.1` in `mise.toml`, Windows zip, pinned by SHA-256; `mise exec -- dosbox` runs it.
* **Control:** REST on `127.0.0.1:<webserver_port>` with a bearer token (`DOSBOX_API_TOKEN`, which must be 64 hex characters or the emulator discards it and generates its own), and a Lua script on the emulation thread (`POST /api/v1/script/load`, `/start`, `GET /status`; results in `dosbox.output`).
* **Guest access:** `GET /api/v1/memory/<seg>/<off>/<len>` (raw, up to 128 MiB), `GET /api/v1/cpu/state` (all registers, `DS` included), `GET /api/v1/io/port`; in Lua `dosbox.mem_read_word(seg, off)`, `dosbox.frame()` and `dosbox.wait_frames(n)`.
* **Capture:** `dosbox.capture_start()` / `capture_stop()` (or `POST /api/v1/capture/video/start` with `mode: raw`) records lossless AVI (ZMBV) at the emulated display rate, one video frame per emulated frame.
* **Absent:** the debugger. Per the OpenAPI document `debugger` is `false`: no breakpoints, no pause or step, no hooks on an address or a port.
* **Mount policy:** a mount under a system path (the user's `Temp`) is refused; the staged mount and conf live under the data root (`<data root>/spike/`).

## 2. Frame-Locked Capture

`[Bounded Observation]`. One Lua script drives a whole run: wait for the absolute emulated frame 1200 (`dosbox.frame()` counts from emulator start), `capture_start()`, press `c`, Down and Enter at fixed frame offsets (20 frames before each press, 5 held), then once per frame append `dosbox.frame()`, `film_tick` (`DS:0x4896`) and `global_tick` (`DS:0x22B8`) to `dosbox.output` in chunks of 100, and `capture_stop()` after 3,100 logged frames.

* **`DS` is `0x0F46` here**, not DOSBox-X's `0x1575` of [`capture.md`](capture.md) § 3: the image loads at a different paragraph. The offsets are the same. `/api/v1/cpu/state` reports `DS` at the moment of the call, so read it while the film plays: after a long hold it reported `0x17C9`, and an `INTRO.FLM` run that took that value as its constant logged garbage (`film_tick` up to 65,535). `0x0F46` is right for both `CTRY.FLM` and `INTRO.FLM`.
* **Nine runs are bit-identical.** Five sequential and four started together (ports 8387 to 8390): 3,175 video frames each (the 75 frames before logging starts plus 3,100 logged), zero frames that differ by hash, zero differing rows in the tick logs, and the clock ends at 1,342 in all. An earlier set that started the capture and the keys by wall-clock delay (REST, three runs) had two identical runs and one that began a frame later and then sampled the film at different instants: only 11 of 206 shared timer values had identical frames.
* **No drops under this parallel load.** The logs hold 3,100 consecutive frame numbers (no gaps), `film_tick` never decreases, and the four parallel runs equal the sequential ones. Four instances on 16 logical cores is light; a heavier load was not tried.
* **Video frame *j* is emulated frame 1200 + *j*.** Against the decoded HUD timer, offset 0 minimises the gap between `2 * film_tick` and the timer (in centiseconds). At the first frame of each new timer value the timer equals `film_tick / 50` in 348 of 424 cases (0 cs), 58 at -2 cs and 18 at +2 cs. Between render loops the live tick runs 0 to 3 ticks ahead of the displayed timer, which is the render loop (about 17 loops per second) against the 50 Hz clock.
* **Frames per timer value.** 3 to 6 video frames per HUD timer value at 70.087 Hz, with a median of 4; no run shows a stall longer than 7 frames.

## 3. DOSBox-X Video for Comparison

`[Bounded Observation]`. Free-running DOSBox-X with the same `cycles = 8000`, recorded through its menu item 5218 "Record video to AVI" (`WM_COMMAND`; the `F11+I` mapper hotkey and a synthetic `Ctrl+Alt+F5` did not start a recording, while guest keys sent by `SendInput` did reach the game). [`capture-speed.md`](capture-speed.md) starts the same capture with `dx-capture /v` in `[autoexec]`.

| | dosbox-automation (frame-locked) | DOSBox-X (free-running) |
|---|---|---|
| Video frame | 320x200, RGB | 640x400, Mode 13h doubled, RGB |
| Timer changes in the film (0.06 to 23.8 s) | 424 in every run | 369 in every run |
| Video frames per timer value (mean) | 3.92 | 4.52 |
| Same-emulator runs identical | 9 of 9 | no: runs 5 and 6 share 271 timer values, 78 of them with identical frames; run 7 shares only 74 to 84 |
| Frames identical to the other emulator at the same timer value | 0 of 133 to 151 shared values | |

* **The two emulators run the guest at different speeds** at the same cycle setting: dosbox-automation completes about 15% more render loops per film second, so the two sample the film at different instants and no frame matches exactly. Whether they draw identical pixels for the same scene was not tested.
* **The HUD timer is a usable alignment key for CTRY** (digits are 3x5 glyphs at fixed positions, rows 179 to 183; ten glyph bitmaps cover them). `INTRO.FLM` has no such HUD, so there the per-frame tick log is the only signal.

## 4. Follow-up Measurements

`[Bounded Observation]`, 2026-10-30, same machine. The first three bullets were run by Haiku subagents from fully specified briefs (scratch scripts under the data root); their stress, long and INTRO figures were re-derived from the run files by the main session, the cycles and page/DAC figures are as reported.

* **Twelve instances at once.** Twelve frame-locked `CTRY.FLM` runs started together (ports 8410 to 8421, other emulator jobs running alongside on 16 logical cores) were all bit-identical to the baseline: 3,175 frames, equal tick logs, no gaps.
* **Long run.** One run of 12,000 logged frames (about 3 minutes, far past the film's end) completed: 12,075 video frames, no frame-number gaps, `film_tick` constant at 1,342 from log row 1,880 on. Memory use was not measured.
* **`INTRO.FLM`** (no HUD timer; engine files from the demo, `KBD_i` for the dialog jump, 6,200 logged frames): `film_tick` rises monotonically to 3,822 from tick 1, the tick logs of two correct runs are identical, and the video of all three runs is bit-identical (6,275 frames). So the per-frame log carries alignment for films without a HUD.
* **`cpu_cycles` and core** (normal core unless stated; render loops in the film, video frames per timer value):

  | `cpu_cycles` | 6,000 | 8,000 | 10,000 | 12,000 | 16,000 | 8,000 dynamic | max dynamic |
  |---|---|---|---|---|---|---|---|
  | Render loops | 318 | 424 | 524 | 631 | 827 | 417 | 1,163 |
  | Frames per value | 5.24 | 3.92 | 3.17 | 2.64 | 2.01 | 4.00 | 1.42 |

  DOSBox-X's 369 loops fall between 6,000 and 8,000 (about 7,000 by interpolation; not measured). The dynamic core completed without a crash and two runs at 8,000 were bit-identical, as were two at 6,000 on the normal core.
* **Recorded RGB is the DAC.** Pages read at emulated frames 1500, 1800, 2100 and 2400 (`mem_read` of `A000:0000`) against the video frame `F - 1200`, and the DAC read through `PUT /api/v1/io/port` `3C7` then three `GET` of `3C9` (256 entries in 5.75 s, palette unchanged while reading): each index maps to one RGB at three of the four frames, one pair of indices shares an RGB at frame 1800, and every colour equals `round(x * 255 / 63)` of the 6-bit DAC component with zero error (48 and 72 indices checked). `(x << 2) | (x >> 4)` is off by up to 1 and `x << 2` by up to 3. At frame 2400 three indices have two RGB values (79 pixels) and the video matches the page one frame earlier: a one-frame offset in the HUD, not a palette change (§ 4.1). The Lua conversion of a page to hex hit the instruction limit in one frame and had to be spread across frames; § 4.1 reads a page in one frame.

### 4.1 Second Round: Seven Questions Answered

`[Bounded Observation]`, 2026-10-30. Five Haiku subagents and one Sonnet subagent ran fully specified briefs (scripts and logs under `out\inv1` to `inv6` in the data root); the main session re-ran the page-versus-video comparison itself (`w1`, `w2`, `w3`) and read the DS logs from disk. The other subagents' tables are as they reported them.

* **7,000 cycles matches DOSBox-X's loop count, not its pixels.** Normal core, `CTRY.FLM`: 6,500 / 7,000 / 7,500 cycles give 344 / 370 / 396 render loops against DOSBox-X's 369 (three DOSBox-X runs, all 369). Two runs at 7,000 are bit-identical (3,175 frames, equal tick logs). Aligned by HUD timer, none of 58 shared timer values has a byte-identical pair. 96.3% of pixels are within 1 per channel and 14 of 58 best pairs differ by at most 1, which points at the 6-bit to 8-bit conversion (the DOSBox-X rounding was not read); about 3.7% of pixels differ widely and were not located. Only 58 of about 370 timer values are shared, so a comparison needs a tolerance and a nearest-frame search.
* **The dynamic core is not interchangeable.** At 8,000 cycles it gives 417 loops against the normal core's 424, with two bit-identical runs per core. The film clocks agree from frame 1276 to 2066, then differ by 1 to 2 ticks from frame 2067. Pictures already differ at frame 1280. Of 370 differing timer-paired frames, 341 are different content and 29 equal a neighbour. Use the normal core. Whether the dynamic core's pictures are wrong or only drawn at other instants was not resolved.
* **Memory and parallel limits.** One `INTRO.FLM` run to 200 frames past the hold (5,832 video frames, 83 s emulated) took 106 s wall (1.28x), 18.9 MB of AVI (227 KB per emulated second) and a 207 MB peak working set. Sixteen and 24 parallel `CTRY.FLM` runs on 16 logical cores and 31 GB of RAM were all bit-identical to the reference with zero dropped frames; wall time per run stayed about 69 to 73 s, and each instance holds about 0.21 GB (40 would need about 8.4 GB).
* **A page and palette read fits one frame.** In Lua, `dosbox.mem_read(0xA000, 0, 64000)` and `dosbox.mem_read(0x0F46, 0x2768, 768)` (the working palette, 6-bit units; base palette at `DS:0x2468`) in the same step see one instant, because Lua blocks the emulation. The page converts to hex with `raw:gsub(".", H)`, where `H` maps each byte to its `%02x` string; that loop is in C and fits the instruction limit. The game draws straight into `A000`. Runs are bit-identical (26 of 26 spread samples, then 100 of 100 consecutive frames). No render-complete flag turned up in DGROUP. The output store holds about 15 MB, which is about 100 samples per run; a long film needs one run per window of frames. The conf and the game mount must sit together under the data root, or the mount is refused (§ 6).
* **Frame 2400 is a HUD offset, and the offsets are not systematic.** Two runs of frames 2390 to 2409 are identical (page, palette and meta, 20 of 20). The page equals the video frame at `F - 1200` exactly in 14 of 20 samples and one frame earlier (`F - 1201`) in 4 more; at frame 2400 the 79 differing pixels lie in rows 181 to 184, the timer digits. Two samples (2393: 757 pixels in rows 103 to 184, 2405: 10 pixels in rows 104 to 108) match no video frame, which is the render loop writing `A000` while it is scanned out. In a fade window (frames 2690 to 2709) 16 of 20 samples have an exact video frame within two frames and four (2696, 2697, 2701, 2702) have none, best differing in 3,500 to 4,200 pixels; PLAYONE uploads the DAC in two retrace-gated halves (CS:0x7B70), so a video frame can mix two palettes. The mismatch is therefore the page being read at a frame boundary during a render loop (about 17 per second against 70 frames per second), not a palette change at frame 2400.
* **DS depends on the code segment.** In every REST sample of both films `film_tick` never goes backwards and equals `global_tick` before the hold, with `film_tick` ending at 1,342 and 3,822. DS is 0x0F46 while `CS` is 0x01F5, and 0x17C9 while `CS` is 0x0A19; 0x336B and 0x430B also occur with `CS` 0x01F5. So 0x17C9 is the data segment of another code module, and the Lua driver's explicit `0x0F46:offset` reads are correct throughout. What lives at segment 0x17C9 was not identified (its first bytes are not a PSP or an MCB).

### 4.2 Third Round: INTRO, DAC Rounding and a Render Counter

`[Bounded Observation]` for the measurements, `[Supported Inference]` for the DAC reading, 2026-10-30, same machine, main session only (scratch scripts under the data root).

* **The page and working-palette read holds for `INTRO.FLM`.** 7,000 cycles, normal core, 97 samples at frames 1300 to 6580 step 55 (the § 6 snippet with `KBD_i`): 83 pages render exactly to a video frame within one frame (79 at offset 0) through `DS:0x2768` and `round(x*255/63)`. The 14 that do not were not all inspected; two (frames 2345 and 4160) differ in about 59,000 of 64,000 pixels at every offset, which fits a cut or palette change between the page read and the video frame, and the rest differ in the HUD rows or in a band of rows, as a fade or a mid-render read would. The run took 99 s wall for 5,382 video frames and 97 pages, and the lossless AVI was 17.4 MB. A full-film dump needs one run per 97 samples (the output store limit).
* **DOSBox-X expands the 6-bit DAC differently, by exactly 1 on 10 of 64 levels.** Its `dacexpand` in `vga_dac.cpp` computes `(v << 2) | (v >> 4)`; dosbox-automation's video equals `round(v * 255 / 63)`. They agree except at levels 11 to 15 and 48 to 52, where DOSBox-X is one lower or one higher by `|d| = 1`. So the 1-per-channel shift in § 4.1 is the DAC expansion, from the source and the exact-match result above; it was not measured on a DOSBox-X page. The 3.7% of pixels that differ by more than 1 per channel are not explained by it.
* **No per-render counter was found in `DGROUP`.** Diffing the 64 KB `DS:0000..FFFE` once per frame over 90 frames of `CTRY.FLM` (frames 1500 to 1589) shows the page changing in 61 of 90 frames, because the guest draws straight into `A000` over several frames rather than flipping a finished page. The only byte that stepped by +1 at about the loop rate was `DS:0x578C`, which a 2,200-frame log rejected: at 8,000 cycles it changed 268 times before the hold against 424 render loops, and it drops by 9 twenty-six times, so it is a cycling index, not a loop count. A render-complete signal therefore has to come from the code, not from a data diff.

## 5. Consequences

* **Determinism.** A frame-locked dosbox-automation capture is byte-repeatable where the DOSBox-X debugger runs vary by a few ticks (the baseline noise in [`capture-speed.md`](capture-speed.md) § 1), and it records every emulated frame, so no sampling stride decides which pages exist.
* **Exact tick per frame.** The log supplies `film_tick` for every video frame from guest memory, which the DOSBox-X video lacks ("carries no film tick", [`capture-speed.md`](capture-speed.md)). The tags are the tick at the end of each emulated frame, with no debugger latency (compare the 5.75-tick slice jitter in [`capture-speed.md`](capture-speed.md) § 2).
* **What video does not give.** The frames are RGB: index agreement, IoU on the index plane and fade-compensated scoring ([`../parity/method.md`](../parity/method.md)) need the palette indices. The video's colours are exactly the scaled DAC (§ 4), but two indices can share an RGB (one pair in four sampled frames), so the index plane is not always recoverable from video alone. The Lua page and working-palette read of § 4.1 supplies it at chosen frames, with the caveat that a page read in the middle of a render loop can match no video frame, and in a fade the real DAC lags the working palette by up to a frame in two halves. Index and IoU scoring uses the page and the working palette, not the video.
* **Not built.** `stunt_reel/tac` still drives DOSBox-X only. A dosbox-automation driver would sit behind the operations seam in [`transport.py`](../../python/stunt_reel/tac/transport.py) and replace the capture loop in [`framebuffer.py`](../../python/stunt_reel/tac/framebuffer.py), not extend it.

## 6. Reference: the Lua Driver and the Timer Glyphs

The scratch scripts are not committed; this is what a driver needs. Launch `dosbox.exe -conf <conf>` with `DOSBOX_API_TOKEN` set to 64 hex characters, `[webserver] webserver_enabled = true`, `webserver_port = <port>`, a mount under the data root (not `Temp`) with the conf beside it (a conf in a distant folder gets `MOUNT: Blocked ... outside allowed directories`, the emulator sits at a DOS prompt and a stale `video0001.avi` can pass for a film; `mount_allowed_bases` is not a key) and `[capture] capture_dir`. Then `POST /api/v1/script/load` (body is the Lua, `text/plain`), `POST /api/v1/script/start`, and poll `GET /api/v1/script/status` until `state` is `completed`; the log is in `output`. The per-frame log must be written in chunks of 100 into separate `dosbox.output` keys; a 64,000-byte page converted to hex in one frame exceeds the Lua instruction limit.

```lua
local DS = 0x0F46                     -- DGROUP segment for this emulator (§ 2)
local out = dosbox.output
local function wait_until(f) while dosbox.frame() < f do dosbox.wait_frames(1) end end
wait_until(1200)                      -- an absolute emulated frame, so the start is boot-relative
dosbox.capture_start()                -- raw video; video frame j is emulated frame 1200 + j
out.cap_start_frame = dosbox.frame()
for _, k in ipairs({"KBD_c", "KBD_down", "KBD_enter"}) do   -- first letter of the film, Down, Enter
  dosbox.wait_frames(20); dosbox.key(k, true); dosbox.wait_frames(5); dosbox.key(k, false)
end
local chunk, n = {}, 0
for i = 1, 3100 do
  dosbox.wait_frames(1)
  chunk[#chunk + 1] = dosbox.frame() .. "," .. dosbox.mem_read_word(DS, 0x4896) .. "," .. dosbox.mem_read_word(DS, 0x22B8)
  if #chunk == 100 then out["k" .. string.format("%04d", n)] = table.concat(chunk, ";"); chunk = {}; n = n + 1 end
end
if #chunk > 0 then out["k" .. string.format("%04d", n)] = table.concat(chunk, ";") end
dosbox.capture_stop()
out.done = true
```

**Page and working palette at a chosen frame** (§ 4.1), replacing the per-frame loop body above:

```lua
local H = {}
for i = 0, 255 do H[string.char(i)] = string.format("%02x", i) end
for _, f in ipairs(frames) do                      -- at most about 100 frames per run (output store)
  wait_until(f)
  local pg = dosbox.mem_read(0xA000, 0, 64000)     -- indices; the game draws straight into A000
  local wp = dosbox.mem_read(DS, 0x2768, 768)      -- working palette, 6-bit units
  out["s" .. f] = dosbox.frame() .. "," .. dosbox.mem_read_word(DS, 0x4896) .. "|" .. wp:gsub(".", H) .. "|" .. pg:gsub(".", H)
end
```

Rebuild RGB as `round(x * 255 / 63)` per palette byte. Build the Python side with `str.replace`, not `%`, since `%02x` collides with `%` formatting.

**HUD timer decoding.** The AVI is read with `ffmpeg -vf scale=320:200:flags=neighbor -pix_fmt rgb24` (DOSBox-X's is 640x400; dosbox-automation's is already 320x200). The timer is `MM:SS.cc` at rows 179 to 183, six 3x5 digit cells at columns 1, 5, 11, 15, 21 and 25 (the colon and dot sit between), with a pixel counted as ink when its RGB sum is below 60. Glyphs, row by row (`#` is ink):

| Digit | Rows | Digit | Rows |
|---|---|---|---|
| 0 | `###` `#.#` `#.#` `#.#` `###` | 5 | `###` `#..` `###` `..#` `###` |
| 1 | `##.` `.#.` `.#.` `.#.` `###` | 6 | `###` `#..` `###` `#.#` `###` |
| 2 | `###` `..#` `###` `#..` `###` | 7 | `###` `..#` `..#` `..#` `..#` |
| 3 | `###` `..#` `.##` `..#` `###` | 8 | `###` `#.#` `###` `#.#` `###` |
| 4 | `#..` `#.#` `###` `..#` `..#` | 9 | `###` `#.#` `###` `..#` `###` |

A cell that matches none of these (a fade, a black frame, the dialog) means the frame has no timer.

---

**Ruled out**

* **A wall-clock start for dosbox-automation.** Capture start and keys by REST delays: one run in three started a frame late and sampled different instants; use frame-locked starts (§ 2).
* **Frame-for-frame match with DOSBox-X video.** Different guest speed at equal cycles (§ 3); at 7,000 cycles the loop counts agree (370 against 369) but no timer-aligned pair is byte-identical (§ 4.1).
* **The dynamic core as a drop-in for the normal core.** Its film clock departs by 1 to 2 ticks from frame 2067 and 341 of 370 differing frames are different content (§ 4.1).
* **A palette change at frame 2400.** The mismatch is a one-frame offset in the HUD timer rows (§ 4.1).
* **REST port reads for the DAC in a scoring loop.** About 5.75 s per palette and not frame-locked; the DGROUP working palette in the same Lua step replaces it (§ 4.1).
* **`Ctrl+Alt+F5` and `F11+I` as DOSBox-X video start through `SendInput`.** No file appeared in the capture directory; the menu command did (§ 3).

**Open questions**

1. Why do the two emulators differ in about 3.7% of pixels by more than 1 per channel at matched timers? DOSBox-X's DAC expansion explains only the 1-per-channel part (§ 4.2). Compare a DOSBox-X page (index plane) with a dosbox-automation page at one timer value.
2. Where is the render-complete point in the code? No data byte marks it (§ 4.2); the next step is static: the retrace loop and `render_frame_flush` of [`memory.md`](memory.md) § 3.1 are unverified, so find the loop that polls `0x03DA` in the unpacked image and see what it writes after the wait.
3. How do the two retrace-gated DAC halves (CS:0x7B70) map onto the video during a fade: does (low half from palette *n*, high half from *n+1*) reproduce every video frame of a fade, as the Sonnet run found for 95 frames?
4. What is at segment 0x17C9 (code segment 0x0A19)? Is it an overlay or a second module, and does it own other data worth a memory-map entry?
5. What are the 14 INTRO samples that match no video frame (§ 4.2)? Are they all fades, cuts or mid-render reads, and does a read that straddles a cut explain the two near-whole-screen differences?
