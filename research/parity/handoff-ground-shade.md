# Handoff: ground shading needs PLAYONE's baked display list

**Goal that ran:** raise `CTRY.FLM` and `INTRO.FLM` `mean_ssim_scored` (adoption rule 0.002 both /
0.004 one). Eight rounds produced no adoption; every remaining lever needs the player's baked
ground colours. This note is the repo-resident continuation brief; the dated observations are in
[`parity-findings.md`](../parity-findings.md) sections 15-21 and the mechanism in
[`playone-exe/terrain-shade.md`](../playone-exe/terrain-shade.md).

## Baseline (unchanged)

```
ctry  ssim 0.7732  iou 0.9783  idx 0.505  scored 114/140
intro ssim 0.6799  iou 0.9205  idx 0.534  scored 209/213
```

Reproduce with `mise run parity`; rescore existing renders with `mise run parity -- --no-build
--no-render`.

## Where the loss is and why it cannot be fixed from our data

* Terrain carries about 45% of the loss on both films (CTRY 0.1026 of 0.227, INTRO 0.1434 of
  0.320). Oracle ceilings from section 16: matching the flat-ground colour exactly is worth
  +0.0493 CTRY / +0.0693 INTRO, split into +0.0105 / +0.0029 for the same-ramp shade and
  +0.0306 / +0.0575 for the off-ramp pixels (sand, aircraft, shadow on CTRY; the montage on INTRO).
* PLAYONE Gouraud-interpolates the palette index in 8.8 across each ground polygon and writes the
  high byte; the index is `base + max(0, (s >> 1) >> 8)` with `s = -clamp((N . L) >> 16)`, and the
  base colour is a display-list byte, not `MAP.BIN`'s. Because the offset is non-negative, the
  captures' 193/194/196 around our 195 prove the base colours are baked per polygon (section 19).
* `MAP.BIN` is never opened by the player; our terrain is a reconstruction whose colours cannot
  match by construction. A renderer-side fit has failed every time (sections 13, 15-17).

## Tools that exist (do not rebuild them)

* [`probe_playone_light.py`](../../python/scripts/probe_playone_light.py): drives the film through
  the DOSBox-X TAC harness and prints `L`, the sun billboard, the sun position and the shade array
  at chosen film clocks, with `--dump-all-segments` for 16 x 60 KiB memory dumps. Run it with
  `mise exec -- uv run python python/scripts/probe_playone_light.py --ticks 276
  --dump-all-segments --out build/scratch/round6`. Under PowerShell it exits 1 because mise logs
  to stderr; the run itself succeeds.
* `mise run parity`, `mise run sweep -- --var DBG_X=a,b`, `parity_probe.py` (`retime`, `crop`,
  `shift`, `iou`), `parity_run.py` (`--no-build`, `--no-render`, `--reuse`, `--retime`).

## Next probes, in order

1. **Find the builder that writes the ground display list.** It is the code that reads the world
   data and emits the polygon records (colour byte at `es:[si+1]`, shade-array offset word at
   `es:[si+2]`, opcodes `0x0168`/`0x02BE`; handler `0x995C`). Start from `0x995C`'s callers in the
   unpacked image and follow the output buffer. Use the image-to-memory map:
   `runtime_linear = image_offset + 0x8240` (DGROUP at image `0xD510` runs at `0x1575`).
2. **Or dump the EMS page frame.** The image carries the `EMMXXXX0` EMS check string and no
   display list appears in any of the 16 conventional segments (section 20).
3. **Then decode**: polygon records with colour byte, vertex registers and `SHADES` normal blocks,
   and compare their colours with `MAP.BIN`'s patches. Two possible fixes follow: re-bake our
   terrain colours from the player's bake rule, or build the terrain from the player's list.
4. Only after that is a renderer round meaningful again. Keep the adoption rule.

## Constraints

* Never `git add -A`: a parallel session shares this worktree. Stage explicit paths and commit with
  a pathspec. `corpus/`, `target_bin/`, `build/` stay unstaged; leave `%SystemDrive%/` alone.
* `mise run check` must exit 0 before any commit; it does at `097bfd2`.
* Scratch goes in `build/scratch/`, never `$TEMP`; use `--no-build` when the parallel session holds
  the release binary.


---

## Goal outcome (round 10 of 10)

The goal reached its round limit with **no adoption**: rounds 1-4 were negative diagnostics that
closed the data-side explanations, round 4's delegation disassembled the mechanism, rounds 5-6
measured the live inputs and eliminated conventional memory as the display list's location, round 7
mapped image offsets to runtime memory and flagged the candidate embedded data, and rounds 8-10 are
checkpoints. Every attempt is recorded in `parity-findings.md` sections 15-21, with no rows added
to `log.md` because no renderer change was adopted.

Baseline at the close, re-verified: `ctry ssim 0.7732 iou 0.9783 idx 0.505 scored 114/140`;
`intro ssim 0.6799 iou 0.9205 idx 0.534 scored 209/213`.

Commits for this work item: `213cb23`, `42cb36f`, `48a7576`, `b44c6bc`, `f61e792`, `48b955a`,
`097bfd2`, `ca691fb`.

Next session: start from this note. The one blocking unknown is the player's baked ground display
list; recovering it (builder routine or EMS page frame), decoding it, and re-baking or rebuilding
the terrain from it is the whole remaining path. Then resume normal renderer rounds with the
adoption rule.

---

## Round 11 update: record layout corrected, no resident list

Delegated decode result (`parity-findings.md` section 22): the ground record is
`w0 = (colour << 8) | (count & 0x0F)`, then `N` words indexing the shade array `work:0x7468`, then
the next code address (threaded stream) - colour and count share one word, which is why the earlier
scans missed. Rescanned with that layout: no ground display list resident in the image or the
round-5/6 dumps at clocks 276/277. The player has no `MAP.BIN`/`ANCHORPT.DAT`; world data comes from
the `res\*.res` cache (packed payloads) or the image, and the image carries `OP_FRACTAL` (`0x1D4`) and
`OP_IPG` (Ground), so the terrain colours may be *generated at load* rather than baked into a list.

Next: one harness run - break at `0x9982`/`0x99A6` and recover `ES:SI`/`CS:IP` for a ground
polygon (or dump the EMS page frame and grep it for `colour << 8 | count` headers). Then either
decode the stream and its builder, or pivot to the generated-terrain route.

---

## Round 12 update: the ground colour is stored per polygon; the builder is the remaining unknown

Static trace (`parity-findings.md` section 23): the handler consumes `es:[si+1]` (the high byte of
`w0 = (colour << 8) | (count & 0x0F)`) and adds only the light term - no palette lookup, no table.
The stream is self-patching threaded code (handler tail `0x996E`: `lodsw; and ax,0xF; shl ax,1;
add si,ax; lodsw; jmp ax`), generated at runtime and absent from all 72 memory dumps (handler IPs,
slot aliases and record headers all searched - the earlier scans only looked for opcodes/colours).
`OP_IPG` (`0x965F`) and `OP_FRACTAL` (`0xA56C`) can emit terrain records with a supplied colour.

Next: find the first-pass dispatcher that translates opcodes into the patched stream (search for a
walker over `table + op + 5` or `slot + 3`, and for writes of `0x2551`-style IPs into the work
segment; no literal `0x1316`, so look for the `call $+3`/`pop si` self-relative base at `0x7B76`,
`0x15D45`, `0x163A1`, `0x163BD`, `0x17148`, `0x17329`). Cheap cross-check: dump `work:0x1DF8` and
grep for words in `0x1F00-0x3000` or `0x1400-0x1A00`.

---

## Round 13 update: the ground scene is in `CTRY.ALL`

Delegated trace (`parity-findings.md` section 24): the ground opcodes and operands are in the
`.ALL` archive - op `0x168` records at `0x13FC`, op `0x2BE` records at `0xEFE4` - not in the image or
the film. Colour reaches the driver only through `work:0x41E8 = colour << 8` (`0x999C`) and
`lcall 0,0x8010`; `work:0x806C` is the only mode switch (`0x1CE7` sets it `0xFF`, calls `0x1D5F`,
clears it at `0x1CF4`). No static dispatcher was found (no `0x1316`/`0x8246` literal, no table
call, the six `E8 00 00` sites are dead ends). `OP_FRACTAL` uses a constant `0x50` colour and
`OP_IPG`'s type table is zero BSS, so the colour is stored, not computed.

**New priority (no emulator needed):** decode `CTRY.ALL` offline with the section-22 record layout
from `0x13FC` and `0xEFE4` - enumerate ground polygons, `w0 = (colour << 8) | count` headers, shade
words and any per-vertex data, and compare against the captures' 193/194/196. If the `.ALL` records
have no usable colour, break at `0x995C` (with `work:0x806C != 0`) and `0x8010` and dump `es:si` and
`DS:0x1952`, then chase the writers of `DS:0x1952`.

---

## Round 14 update: the slots patch the stream; still not resident

The dispatch slots patch the stream themselves, so there is no first-pass dispatcher to find (`parity-findings.md` section 25). Each slot writes its handler IP into the stream at `es:[si-2]`, in VM-segment coordinates: ground `0x171C`, not `0x995C` or `0x2A2C`. A rescan of all dumps in those coordinates still finds no ground record.

Next: one harness run with a breakpoint on the ground slot `0x83A8` (VM `CS:0x0168`, runtime `0x1048:0x0168` in the CTRY session). Its first hit gives `ES:SI` of a live ground record, or else dump the EMS page frame.
