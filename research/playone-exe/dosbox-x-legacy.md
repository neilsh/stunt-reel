# `PLAYONE.EXE`: The Retired DOSBox-X Capture Harness

Capture moved to dosbox-automation ([`capture-dosbox-automation.md`](capture-dosbox-automation.md), plan [`dosbox-automation-switch-2026-10-30.md`](../../docs/process/plans/dosbox-automation-switch-2026-10-30.md)). This note keeps what is specific to DOSBox-X `2026.10.01` and `dosbox-x-mcp-server` `0.1.2`, so a reader of an old log row, a `references.toml` pin or a capture made before the switch can interpret it. The harness code (`transport.py`, `session.py`, `vsync.py`, `client.py`, `ensure_dosbox.py`, the `mcp` and `ensure-dosbox` tasks) exists through commit `81724a6`; the removal commit deletes it, and `git show 81724a6:python/stunt_reel/tac/transport.py` recovers it.

Findings about `PLAYONE.EXE` itself (clock words, palette upload, render path) are not DOSBox-X specific and stay in [`memory.md`](memory.md), [`palette-fade.md`](palette-fade.md) and [`capture-dosbox-automation.md`](capture-dosbox-automation.md). One correction applies: `0F17:0C5E` is the `ret` of `set_palette` (image `0x7B8E`), not a post-retrace loop boundary ([`capture-dosbox-automation.md` § 4.3](capture-dosbox-automation.md)). Whether the debugger's `0D51:0C5E` breakpoint named the same bytes is unresolved: its linear address `0xE16E` maps to another image offset under each recorded load base. The trap below stopped at "the next slice" in practice, not at that address.

---

## 1. Control Topology

* **Direction (`[Established]`):** `[dosbox] mcp_server = <port>` makes DOSBox-X a TCP **client** that dials the controller. The controller listens (`ListenTransport`). A capture bound port 0 and passed the port with `-set "dosbox mcp_server=<port>"` ([ADR 0021](../../docs/adr/0021-capture-chooses-its-control-port.md)). `[debugger] mcp_server` did nothing (`[Bounded Observation]`, 2026-10-29).
* **Framing:** `REQ <id> <command>` answered by `BEGIN <id> OK|ERR`, body lines, `END <id>`. `PING` and `BREAK` are bare verbs; everything else is `EXEC <debugger command>`. Response ids were matched exactly (a prefix test takes `BEGIN 10` for request 1).
* **No key command:** `EXEC AUTOTYPE` is rejected. Keys came from the BIOS Data Area: bytes at `0040:001E`, tail `0040:001C`, head at `0040:001A`, written while the emulator free-ran, consumed by the guest's `INT 16h`.
* **`D` translation:** the live `D` only moves the debugger view, so the transport rewrote it as `MEMDUMPBIN <target> <len hex> <host path>` and read the file back.
* **Windows ports:** port 58991 once failed with `WinError 10013` because it sat in a Hyper-V/WSL excluded range (58949 to 59048). The MCP server prefers 58991 and falls back on any bind error, so a conf pin could dial a port nothing held.
* **MCP registration** (interactive debugger, [`docs/development.md`](../../docs/development.md) § 2): `mise run mcp` launched `dosbox-x-mcp-server` over stdio and reported its port through `dosbox_mcp_port`; `mise run ensure-dosbox -- --mcp-port <port>` started DOSBox-X with `tools/dosbox/dosbox-mcp.conf` dialling it. Agents registered the server under an `mcpServers` entry named `dosbox-x`.

## 2. Debugger Commands

| Command | Notes |
|---|---|
| `SM seg:off b…` / `SR` | write memory / set a register. `SM` parses tokens as expressions: bytes `AF`, `CF`, `DF`, `AC` read as flag names (zero), so write `0AC`. `SR` only sets. |
| `BP seg:off`, `BPINT`, `BPIO 03DA`, `BPDEL` | breakpoints. Port must be four hex digits. |
| `RUN`, `RUNWATCH`, `VRT` | resume; `VRT` runs to the next vertical retrace. |
| `MEMDUMPBIN <seg:off> <len hex> <path>` | length is hex: `64000` is `0x64000` (409,600 bytes); one Mode 13h page is `FA00`. Unquoted forward-slash path, parent must exist. |
| `VGA MODE\|CRTC\|DAC\|DACPAL\|SEQ\|GC\|DRAW` | `DACPAL`: 8 entries per line, 6-hex-digit RGB in 6-bit units. |
| `INP`, `OUTP`, `OUTW`, `OUTD <port> <data>` | port I/O. `OUTP 21 FF` masks every IRQ and freezes the film clock. |
| `EV cs ip ss sp ax …`, `CPU`, `TIMERIRQ`, `LOG`, `FM` | register read via `EV`; others unprobed. |

Not accepted: `R`/`REGS`, an address expression such as `0C10+00` (pass a literal `seg:off`), a quoted, backslashed or missing-parent dump path, `EXEC PING`.

## 3. Emulator Constraints

| Probe | Result |
|---|---|
| `core = dynamic` with repeated `VRT` | aborts, `run out of cacheblocks` |
| `[sdl] output = opengl` and a debugger command in Mode 13h | exit `0xC0000409` |
| `VRT` after `CTRY.FLM` playback starts | exit `0xC0000409` |
| `MEMDUMPBIN` of `DGROUP` or low memory during the LZEXE unpack (first ~2 s) | guest loops on `Illegal Unhandled Interrupt Called 6`; later reads can kill the emulator ([`memory.md` § 3.4](memory.md)) |
| `autotype` with several keys at boot | only the earliest key survives |

The parity profile therefore used `core = normal`, `output = surface`, no `autotype`, and read only `A000:0000` until the dialog settled. A relative `mount` path failed twice in parallel runs: use an absolute path and no `-defaultdir`. `-time-limit N` is a wall-clock cap, `-fastlaunch` saves 0.3 to 0.4 s.

## 4. The Session Protocol

1. Wait for the dialog on page dumps only: splash (41 indices), blank, two graphics pages, then the six-index `LOAD FILM` dialog; settle after three distinct pages and five identical dumps (up to 600).
2. Keys: first letter of the film, `Down`, `Enter`, through the BDA.
3. Arm `BP 0D51:0C5E` and sample once per `RUN`.
4. Record a page when it differs from the last and has at least 20 distinct indices (dialog and load screens have six).
5. `VGA DACPAL` per frame.
6. Read `film_tick` (`DS:0x4896`) and `global_tick` (`DS:0x22B8`) at the trap. **`DS = 0x1575`** in DOSBox-X (image at paragraph `0x0824`); dosbox-automation uses `0x0F46` (image at `0x01F5`). The debugger had no register read, so `--dgroup-segment` overrode it.

Capture ended after 3 frames at one film clock, or 300 trap hits with no new film frame (`END_IDLE_HITS`); `--max-frames` (default 2000) capped it. Sampling was wall-paced: 0.25 s per frame and about 4 s of boot.

## 5. Measured Behaviour

Every item below is `[Bounded Observation]`.

* **Speed:** 140 `CTRY.FLM` frames in about 26 s; `INTRO.FLM` 213 frames in about 2 min 10 s (ticks 769 to 3,640, one frame per 11 ticks, nothing below 20 colours). Eight parallel captures finished in 64 s with the tick spread within 0 to 2, about 450 films per hour against 64 to 95 serial. No setting changed the 0.25 s per-frame cost (window size, frameskip, `core = dynamic`, `cycles = max`, `turbo`, `priority`, core pinning).
* **Not repeatable:** first-frame `film_tick` 6 to 10 across runs, later frames differ by 0 to 2 ticks, 93 of 112 pages differ between two baseline runs, mid-run dips of about -28 ticks under load. `film_tick` tagging is what made runs comparable.
* **The debugger does not halt the guest.** Guest time follows the host wall clock (about 49.3 ticks per host second paused). A RUN is "the next slice" about 50 ms later, and a 64,000-byte dump costs one slice (5.75 ticks, sd 0.47). Tags are therefore late: a baseline page matched a deterministic stepped page 7 to 10 ticks earlier than its tag. The fitted one-tick page lag (CTRY 0.7713 to 0.7732, INTRO 0.6775 to 0.6793, optimum at integer `t - 1`) came from this and is baked into `headless.rs` (`tick - 1`) and the pinned references.
* **End-hold crash:** 3 of 4 full-length runs lost the connection (`WinError 10054`) around capture 131 to 133, after the clock held at its final tick; no `meta.json` was written. A stale `dosbox-x.exe` could hold the control port.
* **Stuck clock:** `sbtype = none` with `nosound = true` froze the film clock at 14650 with global tick 0 and a 3-frame capture. The same signature appeared in survey captures; a validity check on tick advance and frame count rejects it.
* **Deterministic stepper (never built):** `OUTP 21 FF`, then per frame write `DS:4896`, `RUN` and dump until two dumps match (3.2 runs on average), `VGA DACPAL`, read the clock back. Two runs of 211 frames were 211 of 211 identical, at 0.58 s per frame, with no audio or keyboard (IRQs masked). It was a design for repeatability that dosbox-automation now gives for free.
* **Built-in video:** `dx-capture /v playone.exe` recorded ZMBV 640x400 at 70.09 Hz (Mode 13h doubled, RGB, no palette), 764 to 784 distinct frames per run; not index-preserving, no film tick, two free runs agreed on 1744 of 2939 frames.
* **DAC:** the video path used `dacexpand`, `(v << 2) | (v >> 4)`, which differs by 1 from dosbox-automation's `round(v * 255 / 63)` on 6-bit levels 11 to 15 and 48 to 52. Reference scores move by that amount when a reference changes emulator.
* **Viewport:** the VM work segment held `0x41C8 = 160` and `0x41CA = 92` (projection centre), supporting a 185-row 3D viewport (`[Supported Inference]`, mean SSIM 0.662 to 0.689).
* **Code addresses:** the image loaded at paragraph `0x0824` in DOSBox-X, so image `0x8246` appeared as `0F17:1316`, linear `0x10486`, shown by a debugger with `CS = 0x1048` as `1048:0006`. Convert to linear before comparing a dump with a live address.

## Ruled out

- **Any DOSBox-X setting for capture speed:** none changed the per-frame cost.
- **`nosound`/`sbtype = none` for capture:** freezes the clock.
- **Built-in video as the scored reference:** RGB, untagged, unrepeatable.
- **Fixed control port or a lock file:** [ADR 0021](../../docs/adr/0021-capture-chooses-its-control-port.md).

## Open questions

1. Whether the one-tick page lag in the pinned DOSBox-X references corresponds to a 0 or about 2 frame palette lead in dosbox-automation ([`capture-dosbox-automation.md` § 4.3](capture-dosbox-automation.md)).
2. The stepper's behaviour at film end, exit and `INTRO.FLM`, and its roughly 100-pixel residual against free-run pages, are unanswered and now moot unless DOSBox-X returns.

_Moved here 2026-10-30; the findings are in the [parity log](../parity/log.md)._
