# `PLAYONE.EXE`: The Ground Records and Where the World Scene Comes From

* **Binary**: `PLAYONE.EXE` (unpacked load image `build/re/playone.img`), film `CTRY.FLM` played in the DOSBox-X harness
* **Method**: Capstone and Ghidra static work on the unpacked image; byte scans of 59 files (the image plus 56 `.bin` memory dumps under `build/scratch/round*` and `build/re/mem`, and the low/high saves); live probes with [`probe_playone_light.py`](../../python/scripts/probe_playone_light.py)
* **Scope**: the record format the ground handlers consume, how the colour byte reaches the driver, the self-patching dispatch slots, and every place the ground scene list was looked for. How the polygons are *shaded* is in [`terrain-shade.md`](terrain-shade.md)
* **Anchors**: none new; the slot table is summarised in [`sod-vm.md`](sod-vm.md) section 1, the relocation rule in [`memory-map.md`](memory-map.md) and [`memory.md`](memory.md) section 4
* **Evidence tier**: `[Established]` for the record layout, the colour chain and the slot patches; `[Bounded Observation]` for the absence of a resident list and for the ground ops living in `CTRY.ALL`; `[Unknown]` for the code that produces the ground records

---

## 1. Summary

PLAYONE never opens `MAP.BIN`. The ground it draws is a threaded stream of SOD-VM records whose colour byte is stored per polygon and consumed directly. The only ground opcode operands found offline are in `CTRY.ALL`, the scene archive ([`all.md`](../formats/all.md) section 3.6). No ground record survives in any memory dump, resident or patched. What builds the stream at runtime is the one open question.

## 2. Ground record layout and the colour chain

Ground handler `0x995C` (op `0x0168`) tests `work:0x806C/0x806B`, then runs the simple path at `0x9982` or the clipped path `0x99A6`; `0x9A24` (op `0x02BE`) does the same at `0x9A43`. The shared tail at `0x996E` is `lodsw; and ax, 0xF; shl ax, 1; add si, ax; lodsw; jmp ax`. So a record is:

| Word | Content |
|---|---|
| `w0` | `(colour << 8) \| (vertex_count & 0x0F)`, count at most 15 |
| `w1..wN` | indexes into `work:0x7468`, the per-vertex `s` written by `SHADES` (`0x99E1`/`0x99E5`) |
| `wN+1` | the next code address (the stream is threaded: `jmp ax`) |

Colour and count share one word, which is why scans for a separate colour byte, shade word and count never matched.

The base colour is `mov ch, es:[si+1]` at `0x9988` (the only other site is `0x9A50`): the high byte of `w0`, consumed directly with no palette lookup, table or arithmetic. `0x99E9` halves `s`, `0x99EB` adds `G = 0`, `0x99F3` adds the base, `0x99F5` stores the 8.8 index ([`terrain-shade.md`](terrain-shade.md) section 5). The colour reaches the driver as `work:0x41E8 = colour << 8` at `0x999C`, then `lcall 0,0x8010`, the single gateway that reads `CX = [0x41E8]` and calls the driver through `DS:0x2246`. The filler is `lcall 0,0x75DB` at `0x9A15` (other ground ops `0x9AE5`, `0x9B33`). `OP_COLOR` (op `0x129`, `0x975A`, same `work:0x41E8`) is not read on this path. `0x806C` is the only mode switch: module-A code `0x1CE7` sets it `0xFF`, calls `0x1D5F`, and clears it at `0x1CF4`.

## 3. The colour is stored, not computed

* `OP_FRACTAL` (op `0x01D4` -> `0xA56C`) builds a four-vertex ground quad but uses the constant `0x50` (push at `0xA578`, `[0x41E8]` at `0xA66B`), so it cannot supply the ramp colours.
* `OP_IPG` (op `0x0063` -> `0x965F`) dispatches on type through `DS:0x1954`, which is zero BSS in the image; type 2 is a ground quad, geometry only.
* The base byte is therefore a stored per-polygon value, and the additive-only light ([`terrain-shade.md`](terrain-shade.md) section 8) leaves the capture's 193/194/196 around `MAP.BIN`'s 195 unexplained by any single base.

_Found 2026-10-23 at `728b9ab`; see the [parity log](../parity/log.md)._

## 4. The dispatch slots patch the stream themselves

A search for `26 C7 44 FE` finds 108 consecutive 9-byte slots at image `0x8240..0x860B` (paragraph `0x824`), plus two handler-side patches at `0x92CD` (op `0x15F`, writes `0x1241`) and `0x93DD`. Each slot is `mov word es:[si-2], imm16; jmp rel16`, and for all 108, `imm16 + 0x8240` is the jump target. An opcode word is the offset of its own slot; on first execution the slot overwrites that word with the handler IP. There is no first-pass dispatcher to find.

| Op | Slot (`0x8246 + op`) | Handler | Patched word in the stream |
|---|---|---|---|
| `0x0156` `SHADES` | `0x839C` | `0x9481` | `0x1241` |
| `0x0168` ground | `0x83AE` | `0x995C` | `0x171C` |
| `0x02BE` ground | `0x8504` | `0x9A24` | `0x17E4` |

The `26 C7 44 FE imm16` tail seen after a slot's jump is a per-op module-A thunk (`0x1072`, `0x18B4`, `0x231D`), not a handler IP. Coordinates matter: IPs quoted in notebook `CS = 0x0F17` terms (`0x2551`, `0x2A2C`, `0x146C`, `0x147E`, `0x15D4`) differ from the VM's `CS = 0x824` terms by `0x1310` (notebook = image - `0x6F30`, VM = image - `0x8240`). Ghidra (12.1.4 via `rea` 6.7.0) recovers 222 functions, none in image `0x9100..0xB85C` where the handlers live, since every handler is reached through a slot; it reports no xrefs to the handlers, slots, the light-setup entry `0x9100`, `OP_IPG` or `OP_FRACTAL`, and cannot follow `jmp ax`. Its `search-bytes` is what exposed the slot run.

_Found 2026-10-23 at `6ae7b31`; see the [parity log](../parity/log.md)._

## 5. The ground ops are in `CTRY.ALL`

*[Bounded Observation].* Op `0x168` records start at `CTRY.ALL` offset `0x13FC` (`68 01 ...`) and op `0x2BE` records at `0xEFE4` (`BE 02 ...`); `CTRY.FLM` contains none ([`all.md`](../formats/all.md) section 3.6). `CTRY.ALL` also carries packed `(byte << 8) | count` words (`0x2BE` records end `03 E0`) and a 110-word scene colour table at `0x79`/`0x7B`/`0x7D` and `0xEF-0x9A0`, but a byte scan found no ground colour in `0xC0-0xCD`; decoding the records is still to do.

*[Bounded Observation], 2026-10-24.* Neither record start decodes as a threaded stream. Under the handler layout of section 2, the record at `0x13FC` is `w0 = 0x002D` (colour `0x00`, count 13) and the word after its thirteen shade words is `0x0009`; at `0xEFE4` the record is `w0 = 0x0004` (colour `0x00`, count 4) and its terminator is `0x3004`. Neither terminator is a file offset holding another op word, so the terminator is a VM-space address the loader relocates, and an offline walk needs that relocation rule ([memory.md](memory.md) section 4) before it can run. The byte census does not settle it either way: palette indices 193, 194 and 196 occur 25, 11 and 194 times respectively across the 71,216-byte archive.

The scene colour table at `0x79` does read, and it is a ramp directory rather than a polygon colour list: the first 67 entries are `(palette index << 8) | ramp length`, with lengths 3 to 7, after which the word shape changes. Its first five are `193`/3, `194`/3, `195`/3, `221`/3 and `222`/3, so 193, 194 and 195 are three shades of one contiguous ramp, and 196 is not among them. A capture drawing 196 on the airfield therefore draws a base outside that ramp or a different polygon, not the top of the 193 ramp.

## 6. Where the list is not

Everything below is searched negative. A scan for the ground stream means a word in `{0x0168, 0x171C, 0x02BE, 0x17E4}`, then `w0` (colour `0xB0..0xDF`, count 3-8), `count` shade words, then a next word that is a slot offset or slot `imm16`, at both alignments.

* **Conventional memory.** All 16 real-mode segments (60 KiB each, 960 KiB, linear `0x00000-0xF0000`) were dumped at film clock 276 with `--dump-all-segments`. The words `0x0156`, `0x0168` and `0x02BE` occur at most five times per segment, the chance rate, and every hit is inside code (the four `0x0156` hits in the work segment at `0x8C0D`, `0x8C33`, `0x8C59`, `0x8FDD` surround `mov word ptr [0x0153], 0` and the routine's `ret`; identical at clocks 276 and 277). The scan above finds no hit in any of the 59 files, unpatched or patched. The work segment (`0x1DF8`) and DGROUP (`0x1575`) hold code, tables and the light/shade words only.
* **The image.** No `0x9481`/`0x995C` word, no `(colour 0xC0-0xCD, count 3-8)` record with a valid next IP, no dense 192-199 byte map. The candidate embedded regions are templates, not a colour map: `0x23200-0x24E80` (dense 9k-opcode field with `0x20A`/`0x213`/`0x225`/`0x22E`, best match for a serialised scenery program), `0x2D500-0x2F000` (10-12-byte nodes with forward links that are not image addresses, consistent with a template relocated by the loader), `0x2AC00-0x2B000` (prop bytecode template). See [`memory.md`](memory.md) section 4 for the region.
* **Files.** The demo install has no `MAP.BIN` and no `ANCHORPT.DAT`; the player's file literals are `game.cfg/var`, `pfont.bin`, `pilots`, `res\*.res` (+ sound formats), `driver1..3.bin`, `vdata.bin` and `VAULT\*.FLM/.TKE`.
* **Static callers.** No literal `0x1316` or `0x8246` in the image, no call into the table, no handler-IP table; all six `E8 00 00` sites are dead ends (a palette out-delay at `0x7B76`; zero BSS or templates at `0x15D45`, `0x163A1`, `0x163BD`, `0x17148`, `0x17329`). The light-setup entry `0x9100` (writer `0x9106` of `L`) has no direct reference either.

What remains: the list is built per frame outside the 16 conventional segments (the image carries the `EMMXXXX0` EMS check string, so EMS/XMS is plausible), or in a 4 KiB segment tail the `0xF000`-byte dump skips, or the ground is reached through a path that never leaves a resident stream. The opcode handlers are shared with props, so which handler the ground uses should be confirmed by breaking at it.

_Found 2026-10-23 at `f61e792`, `48b955a`, `39a3868`, `728b9ab`, `6ae7b31`; see the [parity log](../parity/log.md)._

## Tools

* [`probe_playone_light.py`](../../python/scripts/probe_playone_light.py) drives a film through the DOSBox-X TAC harness and prints `L`, the sun billboard, the sun position and the shade array at chosen film clocks; `--dump-all-segments` writes 16 x 60 KiB dumps. Run `mise exec -- uv run python python/scripts/probe_playone_light.py --ticks 276 --dump-all-segments --out build/scratch/round6`. Under PowerShell it exits 1 because mise logs to stderr; the run itself succeeds.
* `mise run parity`, `mise run sweep -- --var DBG_X=a,b`, and `parity_probe.py` (`retime`, `crop`, `shift`, `iou`); see [`method.md`](../parity/method.md).

## Ruled out

* **A baked ground display list resident in conventional memory** (rounds 5-6 and 14 scans above): none at clocks 276/277 in either coordinate system.
* **A first-pass dispatcher translating opcodes** (searched for a walker over `table + op + 5`, `slot + 3`): the slots are the translation (section 4).
* **The archived stream threaded by file offset** (2026-10-24): walking from `0x13FC` or `0xEFE4` with `[w0][count shades][next]` stops at the first record, because its terminator (`0x0009`, `0x3004`) is not an offset into the file that holds an op word.
* **The live ground stream in conventional memory, relocated** (2026-10-24): the runner at `0x9161` does `lodsw es:[si]` then `call ax`, so a relocated op word is the *handler's* code offset (`0x995C` at image, `0x171C` in VM terms), and the earlier scans did not look for the image form. Across all 96 dumps under `build/re/mem` and `build/scratch`, `0x995C` occurs **zero** times and `0x9A24` twice, the chance rate. The list is therefore outside the 16 dumped segments — the EMS page frame or the 4 KiB segment tail the 0xF000-byte dump skips.
* **Colour computed at load by `OP_FRACTAL` or `OP_IPG`** (section 3): constant `0x50` and a zero type table.
* **Searching in notebook `CS = 0x0F17` coordinates and with a separate colour/count layout:** both made earlier scans unable to match; superseded by sections 2 and 4.

## Open questions

1. **Decode `CTRY.ALL` offline** (no emulator), now with the relocation rule: the section 5 attempt shows the record terminators are VM-space, so relocate them the way the loader does ([memory.md](memory.md) section 4) before walking, then enumerate the ground polygons and compare their colours with the captures' 193/194/196. ([#65](https://github.com/neilsh/stunt-reel/issues/65))
2. **Breakpoint the ground slot** `0x83A8` (VM `CS:0x0168`, runtime `0x1048:0x0168` in the `CTRY` session): it fires once per new ground record and gives `ES:SI` directly. If the handler is never reached for ground pixels, the terrain is a dedicated routine. Also break at `0x995C` with `work:0x806C != 0` and at `0x8010`, dumping `es:si` and `DS:0x1952`, then chase the writers of `DS:0x1952`. ([#65](https://github.com/neilsh/stunt-reel/issues/65))
3. **Dump the EMS page frame** during playback and grep it for `(colour << 8) | count` headers with colours 192-199, or for handler IPs `0x1F00-0x3000` / slot aliases `0x1400-0x1A00` in `work:0x1DF8`. ([#65](https://github.com/neilsh/stunt-reel/issues/65))
4. **Find the producer** of the stream (the code that reads the world data), then compare its colours with `MAP.BIN`'s; this decides between re-baking our terrain colours and rendering the player's records directly. Only then is a renderer round meaningful, under the [parity skill](../../.agents/skills/improving-render-parity/SKILL.md)'s adoption rule. ([#65](https://github.com/neilsh/stunt-reel/issues/65))
