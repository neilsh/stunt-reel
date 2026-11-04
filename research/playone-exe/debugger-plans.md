# `PLAYONE.EXE`: Breakpoint Plans on DOSBox-X's Debugger

* **Tool**: `mise run debug-x -- --plan <toml> [--film F] [--build unpatched|patched]`
  ([`debug_x.py`](../../python/scripts/debug_x.py), [`dbx/`](../../python/scripts/dbx/), plans in
  `tools/dosbox-x/plans/`), [ADR 0034](../../docs/adr/0034-breakpoints-run-on-dosbox-x.md)
* **Emulator**: DOSBox-X v2026.10.01, SDL1 build, `core = normal`, `output = surface`,
  `cycles = 8000`, `memsize = 16`
* **Scope**: how a plan reaches a breakpoint and back (link, boot, addresses, the watch filter,
  the hit loop) and what it costs. Findings about `PLAYONE` go in the note for their subject.
* **Evidence tier**: `[Bounded Observation]` for the measured behaviour (one emulator version,
  `CTRY.FLM`, 2026-11-04); `[Established]` for the address arithmetic

The retired capture harness's knowledge of DOSBox-X (link framing, debugger commands, emulator
constraints) is in [`dosbox-x-legacy.md`](dosbox-x-legacy.md) § 1–3 and still applies.

---

## 1. Link and Boot

DOSBox-X dials the controller's port-0 listener (`-set "dosbox mcp_server=<port>"`) and takes
`REQ <id> <command>` frames. Every read of guest memory is `MEMDUMPBIN` to a per-run file
`D0000001.BIN`, `D0000002.BIN` and so on, read back; registers come from
`EV CS IP SS SP DS ES AX BX CX DX SI DI BP`.

A boot stages the film on the chosen build (`<data root>/builds/<build>`), launches with a
generated conf, then:

1. sends `PING`, and only `A000:0000 FA00` page dumps until the film dialog has settled (five
   identical pages of six colours), since reads during the LZEXE unpack crashed the old harness;
2. reads `DOS MCBS`: `PLAYONE`'s block gives the PSP, and the image loads at PSP + `0x10`;
3. types the film's selection keys into the BIOS buffer (`0040:001E..003D`) one second apart,
   all but Enter. `SM` byte tokens get a leading `0`, because `SM` reads a bare `AF` or `DF` as
   a flag name;
4. arms the plan's `dialog` probes, then sends Enter, so they see the film load.

| Measure (CTRY.FLM, unpatched) | Value |
|---|---|
| PSP / load paragraph | `0x0814` / `0x0824` (dosbox-automation: `0x01F5`) |
| Launch to settled dialog | 7 s (the spike, with a slower settle rule, took about 25 s) |
| Whole smoke run (boot, two hits, teardown) | 9 s |
| Film clock while the controller polls | about 52 ticks per second (200, 253, 305 one second apart) |

## 2. Addresses

* Image offset `x` sits at linear `load * 16 + x` and runs with `CS = load + p`, `p` being the
  nearest code segment at or below it: the targets of the image's relocated far calls and jumps
  (`0x0`, `0x824`, `0x1DEA`, `0x20F6` unpatched; `0x0`, `0x754`, `0x1CD5`, `0x1DC7` patched)
  plus `vm`, the paragraph where the build's 108-slot dispatch run starts
  ([`world-scene.md`](world-scene.md) § 4), which is where the display-list handlers run. The
  light setup `0x9100` is therefore `1048:0EC0` unpatched. A stop matches a break by linear
  address, so the segment DOSBox-X reports does not matter.
* Before a break is armed, its 8 live bytes are compared with the image, with relocated words
  masked; a mismatch refuses the probe (exit 2).
* Plans hold unpatched offsets. On `--build patched` a code offset maps through #78's pairing
  only where it is aligned inside a function of similarity 1.0 ([`patch3.md`](patch3.md) § 4);
  literal DS offsets map through its data mapping. The smoke plan's `0x9100` became `0x83F7` and
  `DS:0x49EC` became `DS:0x4372`, which read the same light vector as the registers: the data
  mapping holds live.
* Every `CS:IP`, return address and writer is also recorded as an image offset of the build
  that ran.

## 3. The Watch Filter

A `BPM`/`BPLM` stop leaves `IP` after the instruction that changed the byte, or on a `rep`
string instruction re-executed in place. The tool decodes one instruction with iced-x86 at
each start from `IP-6` to `IP-1` and keeps those that end exactly at `IP` and whose
`used_memory()` writes into the watched range. Registers are post-instruction, so `SP` is
worked back by the instruction's stack increment and string ops get one element of slack. One
survivor is the writer; several are kept as `ambiguous`; none is `spurious` and dropped.
Writes by the build's own slot run (the slots patching the display list) are counted as
`ignored`. A `rep` store sitting at `IP` whose segment holds the watch is kept as `ambiguous`
("rep, span unknown"): if DOSBox runs a `rep` in chunks between breakpoint checks, `DI` may be
far past the byte the chunk changed (`[Hypothesis]`; no live `rep` writer has been watched yet).

*[Bounded Observation], 2026-11-04.* DOSBox-X arms a `BPM` with a stored value of `00`
(`BPLIST` shows `BPMEM 1575:49EC (00)` while the byte holds `0x63`), so every watched byte that
is not zero stops once, spuriously, right after arming, at whatever instruction runs next. The
filter drops these; in the `light-writers` run all five such stops sat on the `rep stosw` at
`0x75B5` with `ES:DI` nowhere near the watch.

A `mem:DS:<offset>` capture or watch with a literal offset reads DGROUP (`load + dgroup`); with
a register offset (`mem:DS:DX:16`) it reads the live `DS`, since a caller such as an `INT 21h`
buffer need not be in DGROUP.

On the unpacked image the spike's two film-clock stops resolve as expected: the stop at `0x43EA`
to `adc ds:[4896h], ax` at `0x43E6`, and the stop at `0x759C` (after `mov cx, ax`) to nothing.
`BPM` compares values, so a write of the value already there is never seen.

## 4. The Hit Loop

The link has no stop event: a stop is two equal register snapshots 50 ms apart. A stop counts
for an armed break site, then for an interrupt probe whose `AH` matches on a `CD nn` or at the
vector, then for a watch the filter attributes. A stop equal to the previous one is not counted again;
the loop sends `RUN` once more, so a `RUN` that had not yet resumed the guest neither counts one
hit twice nor leaves the guest stopped.
The guest's clock keeps running while the controller reads (`dosbox-x-legacy.md` § 5), so each
hit carries its own `film_tick`; spurious stops are written too (the first 50), with their code
bytes. A run ends `spent`, `stop_tick`, `timeout` (no counted stop in 120 s), `link_lost`,
`refused` or `error`, and always writes an `end` record.

## Ruled out

- **A code hook on dosbox-automation**: it cannot see memory writes and rebuilds a debugger
  ([ADR 0034](../../docs/adr/0034-breakpoints-run-on-dosbox-x.md)).
- **`dosbox-x-mcp-server` for agents**: harness-bound and session-shaped; the link alone does
  the job.
- **The SDL2 build**: chosen by the old pin for OpenGL output, which this tool never uses; the
  spike and every run here used SDL1.

## Open questions

1. Where an `INT` breakpoint stops: on the `CD nn` or at the vector target. The loop accepts
   either; the first `int` probe run (#65's file reads) settles it.
2. The cost of large captures. Two 64 KB `lin:` dumps at one hit took a whole 14 s run (`terrain-tree`); 300 hits with a 40-byte capture take about 3 minutes, most of it the 50 ms stop polls and `MEMDUMPBIN` round trips. Whether a hit's cost grows with capture size beyond that is unmeasured.

_Found 2026-11-04 with `tools/dosbox-x/plans/smoke.toml`; see the [parity log](../parity/log.md)._
