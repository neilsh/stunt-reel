# Breakpoints on DOSBox-X for the Ground and Light Questions (2026-11-04)

Status: **design approved in conversation 2026-11-04; spec awaiting review**. Implementation
plan: `debugger-breakpoints-implementation-2026-11-04.md` (not written yet). Issues:
[#65](https://github.com/neilsh/stunt-reel/issues/65) (where `PLAYONE` draws its ground polygons
and their colours from) and [#66](https://github.com/neilsh/stunt-reel/issues/66) (what sets its
per-shot terrain light), both blocking [#69](https://github.com/neilsh/stunt-reel/issues/69).
Depends on [#78](https://github.com/neilsh/stunt-reel/issues/78)'s branch
`claude/sad-khorana-d54142` (function pairing between the two builds, iced-x86).

## 1. Goal

Answer #65 and #66 on both `PLAYONE.EXE` builds with a committed tool a subagent can drive:

- **#66:** the caller of the light setup `0x9100`, its inputs, and every writer of what it passes,
  at image offsets; the light per frame on `CTRY.FLM` compared with film variable 13 and
  `DS:0x49EC`.
- **#65:** the producer of the ground display-list records and the source of their colour byte,
  at image offsets; the ground polygons' colours compared with `MAP.BIN`'s on `CTRY.FLM`; the
  renderer change the finding licenses, with its predicted sign on each film.

Both are findings. The renderer change is #69's.

Not in scope: per-frame capture on DOSBox-X (capture stays on dosbox-automation,
[ADR 0025](../../adr/0025-capture-runs-are-plans-not-sessions.md)); the MCP server
`dosbox-x-mcp-server`; INTRO.FLM beyond one stream dump (section 5, step 6).

## 2. Why DOSBox-X, and what the spike showed

dosbox-automation has no debugger: no breakpoints, pause or step
([`capture-dosbox-automation.md`](../../../research/playone-exe/capture-dosbox-automation.md) § 1).
A code-hook probe (patching a jump stub into the guest) was designed first and dropped: it rebuilds
part of a debugger, cannot see memory writes, and costs a stub assembler, a ring buffer and
patch-safety rules. #65's last step is "who writes this byte", which only a memory breakpoint
answers.

DOSBox-X v2026.10.01 (still in the mise installs) has the debugger link built in: with
`-set "dosbox mcp_server=<port>"` it dials a TCP listener and takes `REQ <id> EXEC <command>`,
answering `BEGIN <id> OK|ERR`, body lines, `END <id>`
([`dosbox-x-legacy.md`](../../../research/playone-exe/dosbox-x-legacy.md) § 1). No MCP server is
needed. A throwaway spike on 2026-11-04 (scratch script, unpatched build, `CTRY.FLM`,
`core = normal`, `cycles = 8000`) found, all `[Bounded Observation]` pending the committed tool:

| Check | Result |
|---|---|
| Debugger commands over the link | `HELP` lists `BP`, `BPM`, `BPLM`, `BPINT`, `EV`, `MEMDUMPBIN`, `SM`, `DOS MCBS/EMS/XMS`, `LOGC` |
| Boot to film | about 25 s: dialog settles after 14 page dumps, keys `c`, Down, Enter through the BIOS buffer |
| `BP 1048:0EC0` (image `0x9100`) | stops, about 0.3 s per hit; `EV` gives every register |
| Light at the hit | `AX/BX/DX = 0x0063/0x7FFE/0xFFEF`, i.e. `L = (99, 32766, -17)`, the value `probe-light` reads at tick 261 |
| Caller | every hit returns to `0824:2350`: the call is `lcall 1048:0EC0` at image `0x234B` |
| Caller's inputs | the bytes before it are `mov ch,es:[8]; mov bp,es:[4]; mov si,es:[2]; mov ax,[0x49EC]; mov bx,[0x49EE]; mov dx,[0x49F0]; push [0x22EC]` |
| Calls per frame | one per object, each with its own `ES` (`6B71`..`6BC2` seen) and `SI = 0x000C`; stack words `782C, 782E, 7830, 7832` step through an object list |
| Stream head at `ES:SI` | `1F 14 ...`: `0x141F`, `OP_IPG`'s VM-space IP, so the live stream is in conventional memory, already slot-patched |
| `BPM 1575:4896` (film clock) | two of three stops follow `adc [0x4896], ax` at image `0x43E6`; one stop (IP `0x759C`) follows no write, so watch stops need a filter |
| EMS | one 384 KiB handle at linear `0x110000`, page frame `E000` |

Disassembler: iced-x86 over Capstone (comparison 2026-11-04: identical decoding on all valid code
in `0x0000..0xD510`, effective segments and implicit stack and string accesses in
`used_memory()`, typed, about 12x faster). #78's branch switches to it before merging.

## 3. The tool: `python/stunt_reel/dbx/`

One `mise run debug-x` call boots a film in DOSBox-X, arms the probes of one plan, records the
hits as JSON lines and exits. A subagent explores by rerunning with another plan, about a minute
per boot. Nothing holds a session across commands.

### 3.1 Units

| Module | Does | Depends on |
|---|---|---|
| `link.py` | TCP listener on port 0 ([ADR 0021](../../adr/0021-capture-chooses-its-control-port.md)); `req(cmd)` with exact id match and a per-request timeout; `dump(addr, len)` as `MEMDUMPBIN` to a run-scoped scratch file read back; `regs()` parsing `EV CS IP SS SP DS ES AX BX CX DX SI DI BP` | stdlib only |
| `boot.py` | stages the build's tree with one film under the data root's `stage/` through `staging.py`'s film-tree staging; writes its own `dosbox-x-<port>.conf`; launches DOSBox-X; waits for the six-index dialog by `A000` dumps; sends the film's keys through the BIOS keyboard buffer (`0040:001A..003D`); finds the load paragraph | `link`, `staging.py` where it fits, `game_builds` |
| `plan.py` | parses a plan; arms probes; runs the hit loop; writes the JSONL | `link`, `boot`, `addr`, `watch` |
| `addr.py` | image offset to runtime `seg:off` and back for a build; patched offsets through #78's pairing | `build_pairing` |
| `watch.py` | decides whether a watch stop is a write to the watched address (section 3.4) | iced-x86 |

`python/scripts/debug_x.py` is the CLI; `mise run debug-x -- --plan <toml> --film <path>
--build unpatched|patched [--out <dir>]`.

### 3.2 Plan format

Plans live in `tools/dosbox-x/plans/`, beside the conf template `tools/dosbox-x/dosbox-x.conf`.
Offsets are unpatched image offsets; `--build patched` maps them.

```toml
[run]
cycles = 8000            # core is always normal (legacy: dynamic aborts under the debugger)
stop_tick = 1300         # end the run once film_tick reaches this, or when every probe is spent

[[probe]]
name = "light-entry"
kind = "break"           # break | watch | int
at = 0x9100              # image offset
arm = { tick = 10 }      # "dialog" (before Enter) or { tick = N }
hits = 3
capture = ["stack:8", "mem:ES:SI:64", "mem:DS:0x49EC:6", "mem:DS:0x22EC:2"]

[[probe]]
name = "light-writers"
kind = "watch"
mem = "DS:0x49EC"        # or linear = 0x6BC2C
size = 6
arm = "dialog"
hits = 50
ignore_ip = [[0x8240, 0x860B]]   # image ranges whose writes are dropped (the slot run)

[[probe]]
name = "file-reads"
kind = "int"
int = 0x21
ah = 0x3F
hits = 200
capture = ["mem:DS:DX:16"]
```

Every hit records the registers and `film_tick` (`DS:0x4896` in the build's layout). `capture`
adds `stack:<words>` and `mem:<seg>:<off>:<len>`, where `seg` and `off` may name a register.

### 3.3 Addresses

- **Load paragraph.** Read once, after the dialog settles, from `DOS MCBS`: the block owned by
  `PLAYONE` gives the PSP, and the image starts at PSP + `0x10`. Unpatched under DOSBox-X this is
  `0x0824`, so `DGROUP = 0x0824 + 0x0D51 = 0x1575`. The patched build takes its `DGROUP` image
  paragraph from [`patch3.md`](../../../research/playone-exe/patch3.md) § 2.
- **Code sites.** Image offset `x` becomes linear `load * 16 + x`. A breakpoint is set as
  `<seg>:<off>` with the segment the code runs in: module code runs at `CS = load`, the VM
  handlers at `CS = load + vm`, where `vm` is the build's VM paragraph (the slot run's image
  paragraph: `0x824` unpatched, `0x754` patched, found by the slot-run signature). A site at or
  above `vm * 16` takes the VM segment; a probe may override with `cs = "module"`.
- **Before arming**, the tool reads 8 bytes at each code site and compares them with the image,
  relocated words masked by the build's relocation table. A mismatch refuses the probe.
- **Output.** Every `CS:IP`, return address and stack word that falls inside the image is also
  written as an image offset.
- **Patched build.** An unpatched offset maps through #78's function pairing (function start plus
  offset within it, accepted only where the pairing marks the function identical in shape);
  otherwise the probe is refused with the reason.

### 3.4 Watch stops

A `BPM`/`BPLM` stop leaves `IP` after the writing instruction. For each start point `IP-1` to
`IP-6`, decode one instruction with iced-x86; keep the candidates that end exactly at `IP` and
whose `used_memory()` includes a write or conditional write resolving (effective segment
from the stopped registers, base, index, displacement) to an address inside the watched range. The
hit is recorded with `writer` set when exactly one candidate survives, `writer = null` with the
candidate list when several do, and is dropped and counted as `spurious` when none does, or as
`ignored` when the writer lies in `ignore_ip`. The spike's `0x43EA` stop resolves to `adc [0x4896], ax` at
`0x43E6`; its `0x759C` stop resolves to nothing.

### 3.5 Hit loop and halting

After `RUN` the tool polls `regs()` every 50 ms. A stop is two identical register snapshots that
match an armed break site, or, for a watch or interrupt probe, two identical snapshots in a row.
The debugger does not freeze guest time (legacy § 5), so the tool records `film_tick` at each hit
and never infers time from hit order. A probe with `arm = { tick = N }` is armed once a poll of
`film_tick` (a 2-byte dump every 100 ms while the guest runs) reads `N` or more; the guest runs at
about 50 ticks per second, so arming lands within a few ticks of `N`, and each hit's own
`film_tick` is what the findings cite.

### 3.6 Output and errors

- JSONL under `<data root>/debug/<film>/<plan>-<build>-<stamp>.jsonl`: one `run` record (build,
  load paragraph, emulator version, plan hash), one record per hit, one `end` record (reason:
  `spent`, `stop_tick`, `timeout`, `link_lost`). Stdout prints a summary table of at most
  40 lines: probe, hits, spurious, distinct callers and writers by image offset.
- A link timeout or a lost connection writes the `end` record, kills the emulator and exits 1;
  hits already written stay. A refused probe exits 2 before boot finishes.
- The conf and stage are per run, so runs can go side by side.

### 3.7 Tests

Offline, in the gate:

- `link`: a fake DOSBox-X peer over a socket pair (framing, exact id match, a `BEGIN 10` answering
  request 1, timeout, dump rewriting);
- `plan`: parsing, defaults, refusal of bad probes;
- `addr`: translation both ways on both builds with synthetic relocation tables;
- `watch`: the filter on synthetic bytes, including `adc`, `mov`, `stosw`, `rep movsw`, `push`, a
  two-candidate case and a no-candidate case.

Live runs stay outside the gate (`mise run debug-x`).

### 3.8 Records

- ADR 0033 (to be written in PR A): breakpoints run on DOSBox-X, capture and per-frame sampling on
  dosbox-automation; guest time is not halted at a stop.
- `research/playone-exe/debugger-plans.md`: the mechanics (link, boot, addresses, the watch
  filter, measured costs), reusing `dosbox-x-legacy.md` § 2-3; `dosbox-x-legacy.md` points to it.
- `mise.toml`: DOSBox-X v2026.10.01 pinned again; the `debug-x` task.

## 4. #66: what sets the per-shot light

1. `plans/light-caller.toml`: break at `0x9100`, armed at ticks 10 and 448, three hits each,
   capturing `stack:8`, `mem:DS:0x49EC:6`, `mem:DS:0x22EC:2`. Confirms the return to `0x2350`
   (call site `0x234B`) and `AX/BX/DX = DS:0x49EC..0x49F0` on every hit.
2. `plans/light-writers.toml`: watch `DS:0x49EC`, 6 bytes, armed at the dialog, for the whole
   film. Lists every writer by image offset and the ticks it fires at. Expected: the
   film-variable-13 handler at `0x196C`. Any other writer matters, above all at ticks where `L`
   leaves straight up (155, 276, 345, 564,
   [`terrain-shade.md`](../../../research/playone-exe/terrain-shade.md) § 8). Add a break at
   `0x196C` capturing the variable-13 value it is handed.
3. Static decode with iced-x86 of the routine around `0x234B`: the object loop whose stack words
   step, the object header fields (`es:[2]` to `SI`, `es:[4]` to `BP`, `es:[8]` to `CH`), what
   `[0x22EC]` is, and how variable 13 becomes `DS:0x49EC` (angle = var13 - `0x4000`, trig at
   `0x824:0x05D2`).
4. Per frame, on dosbox-automation: add `DS:0x49EC..0x49F0` and the variable-13 value to
   `probe-light`'s sampled words and run every frame of `CTRY.FLM`. The note gets a per-shot
   table (tick range, var 13, `DS:0x49EC`, `L`, agree?); the raw output stays in the data root.
5. Steps 1 and 2 again with `--build patched`.

Write-up: `terrain-shade.md` § 4 gains the caller, its inputs and the writers at image offsets on
both builds, at `[Bounded Observation]` or better, and says whether a renderer can reproduce `L`
from variable 13 alone; open question 1 closes. `memory-map.md` gains a `DS:0x49EC` row if it has
none. A row in [`log.md`](../../../research/parity/log.md).

## 5. #65: who produces the ground records

1. `plans/ground-objects.toml`: break at `0x9100` for one frame at ticks 10, 273 and 448, capturing
   `mem:ES:0:16` (the object header) and `mem:ES:SI:4096` (the stream); break at `0x995C` (op
   `0x168`) and `0x9A24` (op `0x2BE`), 300 hits each, capturing `ES`, `SI` and `mem:ES:SI:40`.
   This names the objects that hold ground records and where.
2. `python/stunt_reel/ground_stream.py` (with tests on synthetic streams and a `mise run` task):
   walks the threaded stream of [`world-scene.md`](../../../research/playone-exe/world-scene.md)
   § 2 (`w0 = colour << 8 | count`, `count` shade indices, the next IP in VM terms, handler IPs
   resolved through the slot table) and lists every ground polygon: colour, vertex count, shade
   indices and the nearest preceding `SHADES` block.
3. `plans/ground-writer.toml`: run 1 takes the linear address of one airfield ground record's
   colour byte from step 1; run 2 arms `BPLM` on it at the dialog, before Enter, so the first
   write is caught (slot-run writes ignored). If the writer is a copy loop, the hit's `DS:SI` is
   its source; an `int` probe on `INT 21h` `AH = 3Fh`/`42h` logs which file, offset and buffer
   fed that source.
   - **Fallback** if the address moves between runs: arm the `INT 21h` probe alone, find the read
     of `CTRY.ALL` into the buffer the stream is built from, and watch that buffer instead.
   - Result: the producer's image offset and either a `CTRY.ALL` offset or a computation for the
     colour byte.
4. Offline cross-check: decode `CTRY.ALL` at the offset found, with the relocation rule, and
   confirm its colours equal the live stream's (closes `world-scene.md` open question 1 and tests
   § 5's reading that the ground ops are in `CTRY.ALL`).
5. Compare with `MAP.BIN` on `CTRY.FLM`: per ground polygon, colour, vertex count, centroid in
   world coordinates (object origin plus vertices, where the vertex operands decode), and the
   `MAP.BIN` patch under the centroid with its colour. Focus on the airfield (capture 193/194/196
   against our 195) and the coastline sand
   ([#71](https://github.com/neilsh/stunt-reel/issues/71)). If vertex positions do not decode,
   compare colour sets and polygon counts per region instead and say so.
6. Name the renderer change: re-bake terrain colours from the player's records if the geometry
   matches `MAP.BIN` one to one, or draw the player's ground records if it does not. Predict its
   sign on each film from [`attribution.md`](../../../research/parity/attribution.md)'s terrain
   bounds (shade law alone +0.0105 CTRY, +0.0029 INTRO; more where the capture draws sand). One
   `ground-objects` dump of `INTRO.FLM` checks that its stream carries the sand the capture shows
   ([#70](https://github.com/neilsh/stunt-reel/issues/70)).
7. Steps 1 and 3 again with `--build patched`.

Write-up: `world-scene.md` gains the producer and colour source at image offsets on both builds,
tiers promoted from `[Unknown]`, open questions 1 to 4 closed or narrowed, and **Ruled out**
entries for what the runs exclude. A row in the parity log.

## 6. Delivery

1. #78's branch merges first, with iced-x86.
2. Three PRs stacked with `gh-stack` on `main`:
   - **A, the tool:** `dbx/`, the CLI and task, `tools/dosbox-x/`, the DOSBox-X pin, ADR 0033,
     `debugger-plans.md`, offline tests.
   - **B, #66:** the light plans, the `probe-light` words, `terrain-shade.md` and `memory-map.md`,
     a parity-log row. Closes #66.
   - **C, #65:** `ground_stream.py` and its task, the ground plans, `world-scene.md`, the `MAP.BIN`
     table, a parity-log row. Closes #65 and comments the renderer change on #69.
3. Each PR passes `mise run check`; commit bodies follow `AGENTS.md`.
4. A is written in the main session. The live runs and decodes of B and C can go to cheaper
   subagents, each briefed with the plan file, the command and the expected JSONL shape; reviews
   use the strongest model ([`docs/harness.md`](../../harness.md)).
5. The spike's findings (section 2) reach the research notes only once B and C reproduce them
   with the committed tool.

## 7. Risks

| Risk | Effect | Handling |
|---|---|---|
| Halting is inferred from unchanged registers | a busy-wait loop could look halted | a break stop must also match an armed site; watch stops must pass the filter |
| Guest time runs while stopped | ticks jump between hits | `film_tick` per hit; no cadence claims |
| Stream address differs between runs | the two-run writer search misses | the `INT 21h` fallback in section 5, step 3 |
| DOSBox-X lays out EMS or memory differently from dosbox-automation | addresses do not carry across emulators | findings are recorded at image offsets and file offsets only |
| Legacy crashes (`opengl` output, `VRT` during playback, reads during the LZEXE unpack) | lost runs | `output = surface`, no `VRT`, nothing but `A000` dumps before the dialog settles |
| #78's pairing marks a function non-identical | a probe cannot map to the patched build | refused with the reason; the plan gives the patched offset by hand, checked by the 8-byte compare |

## 8. Decisions taken

- DOSBox-X's debugger over a code-hook probe on dosbox-automation (section 2).
- The built-in TCP link over the MCP server: scriptable, pre-approved through `mise run`, the same
  in every harness.
- One-shot plans, not a held session, as [ADR 0025](../../adr/0025-capture-runs-are-plans-not-sessions.md) chose for capture.
- iced-x86 over Capstone, for this work and for #78's pairing.
- Both builds; patched offsets from #78's pairing, not a hand table.
- Spec and plan under `docs/process/plans/`, the repo's convention.
