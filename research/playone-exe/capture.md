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
2. **Drive the dialog through the BIOS ring buffer** ([`navigation.md` § 4](../../research/playone-exe/navigation.md#4-keyboard-architecture--input-injection)): `c` (prefix jump to `CTRY.ALL`), `Down` (`CTRY.FLM`), `Enter` (confirm). The keys are written to `0040:001E`/`0040:001C` while the emulator free-runs; stepping would stop the modal loop from reaching `INT 16h`.
3. **Arm the frame trap:** `BP 0D51:0C5E`, the post-retrace loop boundary (`# [MEM-VSYNC-03DA]`; the address's static meaning is an open conflict, see [`MEMORY_MAP.md`](../../docs/MEMORY_MAP.md#-mem-vsync-03da)). Every `RUN` then stops at the next rendered frame.
4. **Sample one frame per trap hit:** `RUN`, then `MEMDUMPBIN A000:0000 FA00 <scratch>`. A page is recorded when it differs from the previous page and carries at least 20 distinct palette indices — the dialog and load screens use six. Frames are named `tick_NNNN.idx` by capture order (a file name only, not a tick).
5. **Record the live DAC palette** per frame with `VGA DACPAL` (6-bit channels scaled to `0..=255`), writing `palettes_NNNN.json` alongside.
6. **Tag each recorded frame with the film clock:** while the guest is still halted at the trap, read the two words `DS:0x4896` (`film_tick`, `# [MEM-FLM-TICK]`) and `DS:0x22B8` (`global_tick`; evidence for both: [`memory.md` § 3.2](memory.md#32-tick-counter-evidence)) and store them in the frame's `meta.json` entry. The debugger has no register read, so `DS` is the T11-observed `0x1575` (`--dgroup-segment` overrides it). `stuntreel parity` compares each capture against the render at its `film_tick`.

The camera rig and actor table are deliberately **not** read during the loop: they are not needed for the reference rasters, and each extra guest-memory access is another chance to trip the emulator. The two tick words are the exception, read once per recorded frame because parity cannot align a capture without them.

---

## 4. Observed Results

* `mise run capture-ref` records **140 consecutive `CTRY.FLM` frames**, each `A000:0000` page being 64,000 bytes; wall time ≈ 26 s including emulator launch.
* The dialog page carries 6 distinct palette indices; film frames carry 33–84.
* `stuntreel parity` over those 140 frames reports finite per-frame scores and `unmatched: 0`; the first contact sheet's reference panel shows the film's opening shot (airfield, hero aircraft, player HUD), not the dialog.
* **First-frame offset (`[Bounded Observation]`):** the first recorded frame carries the player's HUD timecode `00:00.08`, i.e. one render-loop iteration into the film, so reference ordinal 1 sits ≈ 65 ms after film time zero.

---

## 5. Failure Signatures

| Message | Meaning |
|---|---|
| `LOAD FILM dialog never settled after 600 dumps` | the dialog never painted, or the page kept animating; the emulator is not where the harness expects |
| `no new frame after N trap hits (… dominant index M)` | the film never started (wrong list selection) or ended; `M` distinguishes a static UI page from a blank one |
| `emulator exit status 3221226505` | `0xC0000409` crash — a debugger command was issued while the guest was in a state this build cannot step (see § 2) |
| `DOSBox-X command error … *** Debugger command not recognized` | a shell command (`AUTOTYPE`, `MOUNT`, …) was sent through `EXEC`; only debugger verbs are valid |
