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

* **`DS` is `0x0F46` here** (`/api/v1/cpu/state`), not DOSBox-X's `0x1575` of [`capture.md`](capture.md) § 3: the image loads at a different paragraph. The offsets are the same.
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

## 4. Consequences

* **Determinism.** A frame-locked dosbox-automation capture is byte-repeatable where the DOSBox-X debugger runs vary by a few ticks (the baseline noise in [`capture-speed.md`](capture-speed.md) § 1), and it records every emulated frame, so no sampling stride decides which pages exist.
* **Exact tick per frame.** The log supplies `film_tick` for every video frame from guest memory, which the DOSBox-X video lacks ("carries no film tick", [`capture-speed.md`](capture-speed.md)). The tags are the tick at the end of each emulated frame, with no debugger latency (compare the 5.75-tick slice jitter in [`capture-speed.md`](capture-speed.md) § 2).
* **What video does not give.** The frames are RGB: index agreement, IoU on the index plane and fade-compensated scoring ([`../parity/method.md`](../parity/method.md)) need the palette indices. A page read (`mem_read` of `A000:0000`, 64,000 bytes) and the DAC (ports `3C7`/`3C9`) per frame would supply them; neither was run.
* **Not built.** `stunt_reel/tac` still drives DOSBox-X only. A dosbox-automation driver would sit behind the operations seam in [`transport.py`](../../python/stunt_reel/tac/transport.py) and replace the capture loop in [`framebuffer.py`](../../python/stunt_reel/tac/framebuffer.py), not extend it.

---

**Ruled out**

* **A wall-clock start for dosbox-automation.** Capture start and keys by REST delays: one run in three started a frame late and sampled different instants; use frame-locked starts (§ 2).
* **Frame-for-frame match with DOSBox-X video.** Different guest speed at equal cycles; zero identical frames at the same timer value (§ 3).
* **`Ctrl+Alt+F5` and `F11+I` as DOSBox-X video start through `SendInput`.** No file appeared in the capture directory; the menu command did (§ 3).

**Open questions**

1. Do the dosbox-automation raw frames and the DAC read agree (the raw RGB scaling against the 6-bit DAC, and the P22 colour profile the log says the renderer selects)? A page and palette read per frame, compared with the AVI, answers it.
2. Which `cpu_cycles` makes the render-loop rate match DOSBox-X's, so the two can be compared frame for frame? A sweep of 6,000, 8,000 and 10,000 is cheap.
3. Does `core = dynamic` run the guest and change the frames? It crashed DOSBox-X under stepping and was not tried here.
4. Does the capture hold past the film's end and for long runs (the end-hold loss in [`capture.md`](capture.md) § 4), and under heavier parallel load?
5. Does `INTRO.FLM` (no HUD) give the same repeatability and tick alignment?
