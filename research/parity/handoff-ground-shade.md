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
