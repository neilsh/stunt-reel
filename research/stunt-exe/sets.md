# STUNT.EXE: The Set Engine and Its Event Vocabulary

**Scope:** what the authoring executable does with `.SET` files, read from its unpacked image. Byte layouts stay in [`formats/auxiliary/set.md`](../formats/auxiliary/set.md); this note records the code-side evidence that governs them.

## 1. Which builds the corpus holds

| File | Size | Unpacks to |
|---|---|---|
| `corpus/siarchive/Films/OldPLAY/STUNT.EXE` | 137,240 | `stunt.img` 248,460 |
| `target_bin/StuntIsl/STUNT.EXE` | 138,318 | not yet unpacked |
| `corpus/siarchive/Films/OldPLAY/MAKEONE.EXE` | 103,247 | `makeone.img` 201,884 |
| `corpus/siarchive/Films/OldPLAY/PLAYONE.EXE` | 102,703 | `playone.img` 200,524 |
| `corpus/siarchive/Films/MultiFLM/*/PLAYONE.EXE` | 97,790 | not yet unpacked |
| `corpus/stisldem/PLAYONE.EXE` | 102,703 | same build as `target_bin/` |

Two distinct `PLAYONE` builds circulate (97,790 and 102,703 bytes). `target_bin/PLAYONE.EXE` is the 102,703 one, so every `[MEM-*]` offset in [`playone-exe/`](../playone-exe/) describes that build and must be re-checked before being applied to the 97,790 one.

Unpack with `python python/scripts/unlzexe.py <exe> build/re/<name>.img`.

## 2. STUNT.EXE alone reads and writes `.SET`

String evidence in the unpacked image (offsets are into `stunt.img`):

| Offset | String |
|---|---|
| `0x182f9` | `SETS\*.SET` |
| `0x18304` | `SETS\TEMP.SET` |
| `0x18312` | `SETS\TEMP.$$$` |
| `0x18002` | `LOAD SET` |
| `0x1800b` | `SAVE SET` |
| `0x17f75` | `Save set before doing this?` |
| `0x1804a` | `Prop 1 needs to be placed` / `before the stunt can be flown.` |

Neither sibling executable carries a `.SET` string. `makeone.img` and `playone.img` each reference only `VAULT\*.TKE`, `VAULT\*.FLM`, `VAULT\SPOOL.$$$` and `VAULT\*.*`. So `.SET` is written and read by `STUNT.EXE` alone: the film linker and the player reach a set through the `.ALL` archive, never by opening the file. `[Established]` for the string evidence; the `.ALL` path is `[Hypothesis]`.

The `Prop 1 needs to be placed` string is independent support for prop slot 1 being the flown aircraft rather than a placed prop, which is what the size law in [`set.md` § 3.5](../formats/auxiliary/set.md) forced.

## 3. The event vocabulary, from the display templates

The editor renders each rule through printf-like templates, so the specifier type after each argument index gives the operand's width. `\\1O` = first argument, object index; `\\1b` = byte; `\\1w` = word; `\\3t` = time.

**IF** (`0x19532`–`0x1956c`): `\\1O hits \\2O`, `\\1O crashes`, `\\1p seconds have elapsed`, `Weapon Count = \\1w`, `nothing`.

**AND** (`0x19587`–`0x19621`): `it's before \\1p seconds`, `it's after \\1p seconds`, `event #\\1w has happened`, `event #\\1w hasn't happened`, `flag #\\1b = \\2b`, `flag #\\1b` + ` \\2b` (an operator is filled between them), `plane's speed < \\1m mph`, `plane's speed > \\1m mph`.

**THEN** (`0x19639`–`0x1971e`): `do nothing`, `award $\\3w`, `play '` + `' on chan ` + `, vol=`, `cut to \\1o`, `set time to \\3t`, `finish - \\r`, `change \\1o's \\2v to \\x`, `wait \\3p seconds`, `start recording`, `stop recording`, `stop \\1o`, `kill \\1o`, `explode \\1o`, `fade to \\3w%`, `set flag #\\2b to \\3b`, `modify flag #\\2b by \\3b`, `stop recording if autoediting`.

**The `change` property list** (`0x19772` onward) gives the `\\2v` domain: shape, WE position, altitude, SN position, roll, pitch, roll anim, pitch anim, yaw anim, heading pitch, heading yaw, heading pitch anim, heading yaw anim, speed, acceleration, zoom, watch obj, method, method obj, visibility, collideability, autozoom.

This is the authoritative operator list for [`set.md` § 3.6](../formats/auxiliary/set.md). It matches the handbook's wording and adds the operand widths.

## 4. What this buys the event-table work

The templates are fed from the record, so the code that formats a rule is the code that reads its fields. Finding the formatter and reading how it loads each `\\N` argument converts the current inferred field map into a direct one. That is the next step, and it needs a disassembler rather than byte diffing; [`playone-exe/static-tooling.md`](../playone-exe/static-tooling.md) records which ones were evaluated.

## 5. The retail install and TYPESET.EXE

`target_bin/StuntIsl/` is a full retail install, and it settles two things.

**It holds a second STUNT.EXE build**: 138,318 bytes against the corpus copy's 137,240, with `MAKEONE.EXE` and `PLAYONE.EXE` identical either side. As with `PLAYONE`, an address must name its build.

**It holds `TYPESET.EXE`, the tool that produced every printed set dump.** The install ships the wrapper: `SETINFO.BAT` is `TYPESET %1.SET > %1.TXT` and `PRINTSET.BAT` is `TYPESET %1.SET > PRN:`. Every `.TXT` in `Misc/Sets/` is therefore TYPESET's output, and its wording ("Event#1 One Shot", "If … And … Then …") is that program's, not the handbook's.

TYPESET is LZEXE-packed (28,411 to 39,786 bytes, `build/re/typeset.img`) and is a Microsoft C program. Its string table carries the same operator templates as `STUNT.EXE` plus one `STUNT.EXE` builds at run time: `flag #\1b <> \2b`, the not-equal qualifier. It also lists `yaw`, `auto zoom` and `distance` in the `change` property set.

The install's own `SETS/` directory holds 36 `.SET` files — the retail levels, including `CTRY.SET`, the set behind `CTRY.FLM` — which are additional layout samples the community archive does not duplicate.

## 6. Running the retail utilities

The install ships DOS programs, so the printer itself is a usable oracle.

```
dosbox-x -conf tools/dosbox/dosbox-utils.conf -c "typeset base.set > out.txt" -c "exit"
```

[`dosbox-utils.conf`](../../tools/dosbox/dosbox-utils.conf) mounts `build/utils` as `C:` and deliberately starts no MCP server, because the debugger port belongs to whichever MCP server session is running ([ADR 0021](../../docs/adr/0021-capture-chooses-its-control-port.md)). Copy `TYPESET.EXE` and the set under test into `build/utils` first. Verified: `TYPESET` on `BOMBING.SET` reproduces the same field list as `BOMBING.TXT`, so the oracle matches the shipped dumps.

That makes a byte-to-field map mechanical in principle — flip one byte, dump again, and diff the two outputs, ignoring the `Printed at` line. Two practical obstacles, both measured:

- **DOSBox-X detaches from the console.** A launch that is merely redirected returns in milliseconds while the guest is still starting, so a caller must run it in the foreground through a pipe or poll for the output file. Timings taken from a redirect are meaningless.
- **A guest run is slow enough to matter.** A ten-variant batch written against a 675-entry host directory did not finish inside 300 s, and one launch did not produce its dump within 60 s. Until that is fixed — a disk image instead of a host directory, or the capture harness's socket-driven approach — sweeping 663 offsets is not practical, and the oracle is sane only for single targeted runs.

## Ruled out

- *PLAYONE or MAKEONE reading `.SET`*: neither image contains the string, and both reference only the `VAULT` trio.
- *A fixed field map for the event record*: the same template set is rendered from records whose index marker sits at different offsets, so the record is a union keyed by rule shape.

## Open questions

1. **The event formatter.** Locate the code that references the templates at `0x19532`–`0x1971e` and read the record fields feeding each specifier. This is the shortest path to a complete field map.
2. **Which `PLAYONE` build the `[MEM-*]` offsets describe.** Two builds circulate; offsets taken from one may not hold in the other.
3. **`SETS\TEMP.SET` and `SETS\TEMP.$$$.`** The editor writes through temporary files; whether output is atomic, and whether `TEMP.$$$` is a spool like `SPOOL.$$$`, is unestablished.
