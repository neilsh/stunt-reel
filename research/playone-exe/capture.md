# `PLAYONE.EXE`: Debugger Capture Harness (DOSBox-X)

This document describes how the parity reference set is captured from the original player: the control topology, the emulator behaviours that constrain the harness, the protocol that survives them, and the observed results. It is the runtime companion to [`startup.md`](startup.md), [`navigation.md`](navigation.md), and [`memory.md`](memory.md).

Reference rasters are evidence only and land under `build/parity/` (gitignored); `mise run capture-ref` drives the capture.

---

## 1. Control Topology

* **Direction (`[Established]`):** DOSBox-X configured with `[dosbox] mcp_server = 58991` is a TCP **client** — it dials the controller, which listens (`ListenTransport` in [`python/stunt_reel/tac/transport.py`](../../python/stunt_reel/tac/transport.py)).
* **Framing (`[Established]`):** requests are `REQ <id> <command>`; responses are `BEGIN <id> OK|ERR`, body lines, `END <id>`. Only `PING` and `BREAK` are bare verbs; every other command is sent as `EXEC <command>` and must be a **debugger** command.
* **No key command (`[Established]`):** `EXEC AUTOTYPE ENTER` is rejected with `*** Debugger command not recognized`. The handler table exposes memory/breakpoint/VGA/register verbs (`SM`, `SR`, `BP`, `BPINT`, `BPDEL`, `FM`, `RUN`, `RUNWATCH`, `VRT`, `MEMDUMPBIN`, `VGA MODE|CRTC|DAC|DACPAL|SEQ|GC|DRAW`, `LOG`, …) and nothing that queues a guest keystroke. Keystrokes therefore come from the BIOS Data Area, not from the debugger.
* **`D` translation (`[Established]`):** the live `D <seg>:<off> <len>` only moves the debugger's data view; the transport rewrites it as `MEMDUMPBIN <target> <len hex> <host path>` and reads the host file back.

---

## 2. Emulator Constraints

| Probe | Observed result |
|---|---|
| `[cpu] core = dynamic` + repeated `VRT` | emulator aborts with `run out of cacheblocks` |
| `[sdl] output = opengl` + debugger command with a Mode 13h guest | emulator exits `0xC0000409` (`STATUS_STACK_BUFFER_OVERRUN`) |
| `VRT` after `CTRY.FLM` playback starts (`core = normal`, `output = surface`) | emulator exits `0xC0000409` on the next `VRT` |
| `MEMDUMPBIN` of `DGROUP` or low memory while LZEXE unpacks (≈ first 2 s) | guest spins on `Illegal Unhandled Interrupt Called 6`; a later read can kill the emulator |
| `autotype` queueing several keys at boot | only the earliest key survives; the dialog discards keys queued before it opens |
| BIOS Data Area writes (`0040:001E` + tail `0040:001C`) while the emulator free-runs | works: the guest's `INT 16h` consumes them, advancing the head pointer at `0040:001A` |
| `EXEC PING` | rejected; `PING` is a bare verb only (§ 1) |
| `BPIO 3DA` | error; the port must be written as four hex digits, `BPIO 03DA` |
| `MEMDUMPBIN A000:0000 64000` | dumps 409,600 bytes: lengths are hex, so `64000` is `0x64000`; use `FA00` for one Mode 13h page |
| `R`, `REGS`, or `SR` to read a register | `R`/`REGS` are not recognized and `SR` only sets one; there is no register read (`DS` comes from `--dgroup-segment`, § 3 step 6) |
| An address with an expression, e.g. `0C10+00` | rejected; pass a literal `seg:off` |
| `MEMDUMPBIN` to a quoted, backslashed, or not-yet-existing path | fails; use an unquoted forward-slash path whose parent directory already exists |

Response matching compares the id token exactly (`transport.py`): a prefix test would take `BEGIN 10 OK` as the reply to request 1.

**Code addresses are seg:off views of one linear address.** The unpacked image has `CS = 0`, the captured session loads it at paragraph `0x0824` ([`palette-fade.md`](palette-fade.md)), and the saved memory dumps use other segment bases, so the same instruction can appear as different `seg:off` pairs. For example the SOD dispatch table is image offset `0x8246` and `0F17:1316` in [`sod-vm.md`](sod-vm.md); with the image at `0x0824` both are linear `0x10486`, which a debugger whose `CS` is `0x1048` shows as `1048:0006`. A breakpoint copied from a dump without this conversion lands on the wrong bytes. Convert to linear before comparing a dump address with a live one (`[Supported Inference]`, arithmetic from the load segment).

Consequences for the parity profile (`dosbox-parity.conf`):

* `core = normal` — the dynamic recompiler cannot survive the stepping the harness needs.
* `output = surface` — the OpenGL renderer dies when the debugger touches a Mode 13h guest.
* no `autotype` line — the dialog is driven by the controller instead.
* `MEMDUMPBIN A000:0000 FA00` is the only access used before the load finishes; it is safe from boot and is what lets the harness wait for the dialog without touching `DGROUP`.

The load lockout itself is recorded in [`memory.md` § 3.4](memory.md#34-lzexe-unpack-lockout--mem-unpack-lockout).

---

## 3. Working Protocol

Implemented in [`python/stunt_reel/tac/playone.py`](../../python/stunt_reel/tac/playone.py) (dialog and trap) and [`python/stunt_reel/tac/framebuffer.py`](../../python/stunt_reel/tac/framebuffer.py) (sampling loop); launched by [`python/scripts/capture_playone_reference.py`](../../python/scripts/capture_playone_reference.py).

1. **Wait for the dialog with framebuffer dumps only.** The page sequence at boot is DOSBox-X splash (41 indices) → blank (1) → two graphics pages (5, 6) → the `LOAD FILM` dialog (6 indices, static). Return once at least three distinct pages have been seen and the page has been identical for five consecutive dumps; up to 600 dumps. No debugger command that touches guest memory is issued before this point.
2. **Drive the dialog through the BIOS ring buffer** ([`navigation.md` § 4](navigation.md#4-keyboard-architecture--input-injection)): `c` (prefix jump to `CTRY.ALL`), `Down` (`CTRY.FLM`), `Enter` (confirm). The keys are written to `0040:001E`/`0040:001C` while the emulator free-runs; stepping would stop the modal loop from reaching `INT 16h`.
3. **Arm the frame trap:** `BP 0D51:0C5E`, the post-retrace loop boundary (`# [MEM-VSYNC-03DA]`; the address's static meaning is an open conflict, see [`MEMORY_MAP.md`](memory-map.md#-mem-vsync-03da)). Every `RUN` then stops at the next rendered frame.
4. **Sample one frame per trap hit:** `RUN`, then `MEMDUMPBIN A000:0000 FA00 <scratch>` (`[Established]`: playback scans out the Mode 13h page at `A000:0000`, and `VGA MODE` reports `disp-start=0h`; the 64000-byte page is written under an upper-case DOS 8.3 name). A page is recorded when it differs from the previous page and carries at least 20 distinct palette indices — the dialog and load screens use six. Frames are named `tick_NNNN.idx` by capture order (a file name only, not a tick).
5. **Record the live DAC palette** per frame with `VGA DACPAL` (`[Established]`: 8 entries per line as 6-hex-digit RGB triples in 6-bit DAC units, scaled to `0..=255` before the luminance comparison; the scaling and its difference from the renderer's authored palette are in [`palette-and-shading.md` § 1.1](../formats/concepts/palette-and-shading.md#11-vga-hardware-dac-principles)), writing `palettes_NNNN.json` alongside.
6. **Tag each recorded frame with the film clock:** while the guest is still halted at the trap, read the two words `DS:0x4896` (`film_tick`, `# [MEM-FLM-TICK]`) and `DS:0x22B8` (`global_tick`; evidence for both: [`memory.md` § 3.2](memory.md#32-tick-counter-evidence)) and store them in the frame's `meta.json` entry. The debugger has no register read, so `DS` is the T11-observed `0x1575` (`--dgroup-segment` overrides it). `stuntreel parity` compares each capture against the render at its `film_tick`. The two words are not a constant offset apart, so `global_tick` cannot stand in for `film_tick`.

The camera rig and actor table are deliberately **not** read during the loop: they are not needed for the reference rasters, and each extra guest-memory access is another chance to trip the emulator. The two tick words are the exception, read once per recorded frame because parity cannot align a capture without them.

---

## 4. Observed Results

* `mise run capture-ref` records **140 consecutive `CTRY.FLM` frames**, each `A000:0000` page being 64,000 bytes; wall time ≈ 26 s including emulator launch.
* The dialog page carries 6 distinct palette indices; film frames carry 33–84.
* `stuntreel parity` over those 140 frames reports finite per-frame scores and `unmatched: 0`; the first contact sheet's reference panel shows the film's opening shot (airfield, hero aircraft, player HUD), not the dialog.
* **First-frame offset (`[Bounded Observation]`):** the first recorded frame carries the player's HUD timecode `00:00.08`, i.e. one render-loop iteration into the film, so reference ordinal 1 sits ≈ 65 ms after film time zero.
* **Another film (`[Established]`, `INTRO.FLM` captured 2026-10-22):** `mise run capture-ref -- --film <path to X.FLM>` (default `CTRY.FLM`). `PLAYONE.EXE` takes no film argument and its listbox only jumps by first letter, so the script stages the demo's engine files (`DRIVER*.BIN`, `GAME.CFG`, `INSTALL.CFG`, `PFONT.BIN`, `PLAYONE.EXE`, `VDATA.BIN`) and a `VAULT` holding only that film's `.FLM` and `.ALL` under `build/parity/stage/<name>/`, writes a conf that mounts it (`build/parity/stage/stage-<name>.conf`), and always sends `<first letter>`, Down, Enter. `meta.json` records `film`, `flm_bytes` and `flm_sha256`; renders record `film` and `flm_bytes` in `palette_controls.json`, and `parity` warns when the two disagree. The output defaults to `build/parity/reference/<film name, lower case>`. Capture stops by itself: after 3 consecutive frames at one film clock (a held last picture), or after 300 trap hits with no new film frame once frames exist (the film faded to black or returned to the dialog); `--max-frames` (default 2000) is only a cap. A crashed or interrupted run still writes no `meta.json`.
* **`INTRO.FLM` capture (`[Bounded Observation]`):** 213 frames in about 2 minutes 10 seconds, film ticks 769 to 3,640 (one frame per 11 ticks). Nothing was captured for ticks 0 to 768 (`[Hypothesis]`: those pictures have fewer than 20 distinct colours, the harness's film-content threshold, or the page did not change between trap hits), and the film's last 180 ticks (to 3,822) were not captured (the fade to black). The sky index measured from the first frame is 229, not CTRY's 233.
* **Capture runs are not repeatable to the tick (`[Bounded Observation]`, four runs, 2026-10-22):** the first frame's `film_tick` was 10, 10, 9, 9 and later frames differ by 0 to 2 ticks between runs, so `film_tick` tagging is what makes runs comparable (see `../parity/method.md` § 3).
* **End-hold crash (`[Bounded Observation]`):** 3 of 4 later full-length runs (`--max-frames 140`) lost the connection (`WinError 10054`, emulator still running) around capture 131 to 133 of 140, after the film had reached its final tick 1342 and was holding; no `meta.json` was written, so the run left frames but no usable set. One run also timed out waiting for the emulator to dial in (a stale `dosbox-x.exe` from an earlier killed run held the control port; kill it first). Capturing only to the end of the film (`--max-frames 124` reached tick 1342 once) completed both times. Frames are only written to `meta.json` at the end of a run, so a crashed run is unrecoverable by design.
* **3D viewport is 185 rows (`[Supported Inference]`):** with `CTRY.FLM` playing, the VM work segment (`0x1DF8`) holds `0x41C8 = 160` and `0x41CA = 92` (one session, frame 6): a projection centre at column 160, row 92 of 200, not row 100. Row 92 is the middle of a 185-row viewport above the 15-row button bar. Rendering the scene into the top 185 target rows with the vertical focal scale kept raised `CTRY` `mean_ssim_scored` from 0.662 to 0.689 (183 rows: 0.689, 187: 0.686, 180: 0.662, 190: 0.681), so the optimum sits at the memory-read value. Not found in the disassembly; the setter is unidentified.

* **The captured page lags the film clock by one tick (`[Bounded Observation]`).** The capture reads the film clock and the displayed page at the same post-retrace trap, but `PLAYONE` advances the clock at the start of a frame, so the page captured for clock `t` shows the state at `t - 1`. Copying every rendered file one tick back (`tick_t` to `tick_{t-1}`, official scorer) raised `mean_ssim_scored` CTRY 0.7713 to **0.7732** and INTRO 0.6775 to **0.6793**; a two-tick shift gives 0.7723 and 0.6773, so one tick is the match, not a monotone blur. The gain concentrates on the fast-cut montage: +0.0126 over the 19 frames at ticks 1290 to 1500, +0.0027 over the 28 at 2600 to 2900, +0.0009 over the other 161. `headless.rs` now samples the scene at `tick - 1` while keeping the requested file name, so parity frames and the palette sidecar describe the page the original displays. Fresh release renders: CTRY **0.7732** (IoU 0.978 to 0.9783), INTRO **0.6799** (IoU 0.9194 to 0.9205, index agreement 0.503 to 0.535).
* **The page phase is a whole tick (`[Bounded Observation]`).** Shifting the sampled scene by fractions of a tick around that offset (`mean_ssim_scored`, CTRY / INTRO): -0.5 0.7718 / 0.6774, -0.25 0.7731 / 0.6776, 0 0.7732 / **0.6799**, +0.25 0.7723 / 0.6762, +0.5 0.7711 / 0.6778. Zero peaks on both films, so the page corresponds to the state at an integer `t - 1`.

_Found 2026-10-22; see the [parity log](../parity/log.md)._

---

## 5. Failure Signatures

| Message | Meaning |
|---|---|
| `LOAD FILM dialog never settled after 600 dumps` | the dialog never painted, or the page kept animating; the emulator is not where the harness expects |
| `no new frame after N trap hits (… dominant index M)` | the film never started (wrong list selection) or ended; `M` distinguishes a static UI page from a blank one |
| `emulator exit status 3221226505` | `0xC0000409` crash — a debugger command was issued while the guest was in a state this build cannot step (see § 2) |
| `DOSBox-X command error … *** Debugger command not recognized` | a shell command (`AUTOTYPE`, `MOUNT`, …) was sent through `EXEC`; only debugger verbs are valid |
