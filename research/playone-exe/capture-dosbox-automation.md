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
* **Recorded RGB is the DAC.** Pages read at emulated frames 1500, 1800, 2100 and 2400 (`mem_read` of `A000:0000`) against the video frame `F - 1200`, and the DAC read through `PUT /api/v1/io/port` `3C7` then three `GET` of `3C9` (256 entries in 5.75 s, palette unchanged while reading): each index maps to one RGB at three of the four frames, one pair of indices shares an RGB at frame 1800, and every colour equals `round(x * 255 / 63)` of the 6-bit DAC component with zero error (48 and 72 indices checked). `(x << 2) | (x >> 4)` is off by up to 1 and `x << 2` by up to 3. At frame 2400 three indices have two RGB values (79 pixels) and the video matches the page one frame earlier: a palette change or a one-frame offset, not resolved. The Lua conversion of a page to hex hit the instruction limit in one frame and had to be spread across frames.

## 5. Consequences

* **Determinism.** A frame-locked dosbox-automation capture is byte-repeatable where the DOSBox-X debugger runs vary by a few ticks (the baseline noise in [`capture-speed.md`](capture-speed.md) § 1), and it records every emulated frame, so no sampling stride decides which pages exist.
* **Exact tick per frame.** The log supplies `film_tick` for every video frame from guest memory, which the DOSBox-X video lacks ("carries no film tick", [`capture-speed.md`](capture-speed.md)). The tags are the tick at the end of each emulated frame, with no debugger latency (compare the 5.75-tick slice jitter in [`capture-speed.md`](capture-speed.md) § 2).
* **What video does not give.** The frames are RGB: index agreement, IoU on the index plane and fade-compensated scoring ([`../parity/method.md`](../parity/method.md)) need the palette indices. The video's colours are exactly the scaled DAC (§ 4), but two indices can share an RGB (one pair in four sampled frames), so the index plane is not always recoverable from video alone. A page read and a DAC read (`3C7`/`3C9`) at the frames to be scored would supply it; the REST path is not frame-locked, and the Lua path has no port access.
* **Not built.** `stunt_reel/tac` still drives DOSBox-X only. A dosbox-automation driver would sit behind the operations seam in [`transport.py`](../../python/stunt_reel/tac/transport.py) and replace the capture loop in [`framebuffer.py`](../../python/stunt_reel/tac/framebuffer.py), not extend it.

## 6. Reference: the Lua Driver and the Timer Glyphs

The scratch scripts are not committed; this is what a driver needs. Launch `dosbox.exe -conf <conf>` with `DOSBOX_API_TOKEN` set to 64 hex characters, `[webserver] webserver_enabled = true`, `webserver_port = <port>`, a mount under the data root (not `Temp`) and `[capture] capture_dir`. Then `POST /api/v1/script/load` (body is the Lua, `text/plain`), `POST /api/v1/script/start`, and poll `GET /api/v1/script/status` until `state` is `completed`; the log is in `output`. The per-frame log must be written in chunks of 100 into separate `dosbox.output` keys; a 64,000-byte page converted to hex in one frame exceeds the Lua instruction limit.

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
* **Frame-for-frame match with DOSBox-X video.** Different guest speed at equal cycles; zero identical frames at the same timer value (§ 3).
* **`Ctrl+Alt+F5` and `F11+I` as DOSBox-X video start through `SendInput`.** No file appeared in the capture directory; the menu command did (§ 3).

**Open questions**

1. At `cpu_cycles = 7000` (interpolated, § 4), do the render-loop count and the frames match DOSBox-X's free-running capture closely enough for a frame-for-frame comparison, and do the two emulators draw identical pixels for the same scene?
2. What is the one-frame mismatch at emulated frame 2400 (§ 4): a palette change that the video shows a frame late, or a capture offset? Sample every frame around a fade.
3. Does a page read and DAC read at the frames to be scored fit the REST path, since REST is not frame-locked? A palette-changing frame needs a pause or a frame-locked read, and Lua has no port access.
4. How much memory does a long capture use, and does 12 instances at once hold at higher counts (the 12 here ran beside other jobs on 16 logical cores)?
5. Does the dynamic core's slightly different loop count (417 against 424) change any rendered frame, not just timing?
