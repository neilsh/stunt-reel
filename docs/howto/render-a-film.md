# Render a film in the native engine

## Watch it

```bash
cargo run -p stunt-cli -- "<data root>/corpus/stisldem/VAULT/CTRY.FLM" --all "<data root>/corpus/stisldem/VAULT/CTRY.ALL" \
    --sidata "<data root>/corpus/siarchive/Developer/FreeFlight/SIDATA"
```

Opens the interactive presentation (Space pauses, C toggles authored/free camera, WASD/QE fly the free camera, Esc exits).
Interactive playback follows the authored 50 Hz timeline and interpolates between slices.
`--help` lists the headless flags, `--tick-range <A..=B>` (0-based, inclusive 50 Hz ticks), `--at-ticks`, and the `parity` subcommand.

`ANCHORPT.DAT`, `MAP.BIN`, and `SCENERY.scn` are searched for in `--sidata <dir>` first, then the archive's directory, its parent and grandparent, then `sidata/` or `SIDATA/` inside the parent (filename case ignored); the demo's `corpus/siarchive/Developer/FreeFlight/SIDATA` needs an explicit `--sidata`.

## Watch it lit and fogged

```bash
stuntreel --look modern <film and flags as above>
stuntreel --look modern --headless <film and flags as above> --video film.mp4
stuntreel --look modern --headless <film and flags as above> -o still.png
```

`--look modern` lights the film in RGB against its sun, with a sky fill, and fogs distance toward the horizon sky, through pipelines and shader entry points beside the parity ones; `--look mode13h` is the default.
A facet takes `min(SUN * lambert + fill, 1)` per channel of its palette colour at full brightness: the fill is a hemisphere term, brighter facing up than facing down and tinted toward the sky, so a wall turned from the sun keeps about four fifths of its colour where it once fell to half (`ModernUniform::SUN`, `FILL_UP`, `FILL_DOWN` and `FILL_TINT` in `camera.rs`).
A Gouraud ramp (`GVPOLY`) is smooth: the fragment blends the palette entries either side of its fractional index where Mode 13h steps by whole entries; a flat polygon is one index and stays a single colour, faceted from its neighbours.
Polygons whose colour already carries `OP_SHADES` light keep their palette colour, ramp smoothed, with no sun and no fill, so nothing is lit twice, and so do discs and facet-less lines, which have no normal to light; the letterbox and the pixel snapping are the Mode 13h look's.
The sky is a smooth gradient, not the Mode 13h look's bands: each pixel's view ray is placed on `PLAYONE`'s band edges (edge `j` is the point `1024 j` out and `2048 - 128 j` up, so a ray's elevation gives a continuous `j`) and takes the blend of palette entries `224 + j`, the zenith colour straight up.
At and below the horizon (edge 14's elevation, about 1 degree up) and in an orthographic view it is the horizon colour, index 238, the colour distance fogs to, so fog and sky meet with no seam; PLAYONE's `0xD0` ground fill is not drawn.
The gradient follows the view's elevation, so it matches the bands on the view's centre column and differs from their straight edges under pitch.
The sun is a soft glow toward its colour (index 239) rather than the hard disc: strongest, 0.9 of the way to the sun colour, within 1 degree of the sun and gone beyond 5 (`ModernUniform::GLOW_INNER_DEGREES`, `GLOW_OUTER_DEGREES`, `GLOW`).
The sky entry points are `fs_sky_modern` and `fs_sky_modern_plane` in the modern section of `mode13h.wgsl`; the plane still holds the Mode 13h sky's index, so picking and the layer plane are unchanged.
It is a viewer: `--out-dir` refuses it, since the render store holds Mode 13h renders that are scored, and `stuntreel shape-views` stays on the Mode 13h look.

## Sample it at an interval

```bash
# Capture one frame every 25 ticks (0.5 s) across the full 1,342-tick film
cargo run -p stunt-cli -- --headless "<data root>/corpus/stisldem/VAULT/CTRY.FLM" \
    --all "<data root>/corpus/stisldem/VAULT/CTRY.ALL" --tick-range 0..=1342 --frame-step 25 \
    --sidata "<data root>/corpus/siarchive/Developer/FreeFlight/SIDATA" --out-dir build/parity/ours/ctry_sparse
```

`--tick-range A..=B` takes 0-based, inclusive 50 Hz ticks, `0..=1342` by default (the old `--frames A..B` is now an error; it rendered ticks A-1 through B-2); `--frame-step <N>` renders every Nth tick into the render store, keyed by 0-based tick.
`--sample-count <N>` writes `sample_0001.png`… (1-based sample index) instead; those are not parity inputs.
A render for scoring, and the store's files, are [Score a render change, § 4](score-a-render-change.md#4-render-by-hand).

## Render one film on several cores

```bash
stuntreel --headless <film and flags as above> --software-only --out-dir DIR --workers 4
```

`--workers N` splits a whole-tick `--out-dir` render across N child processes of `stuntreel`, each drawing a run of whole film seconds with `LP_NUM_THREADS=1`, then joins their stores into `DIR`, byte for byte the store a 1-worker render writes (checked at 2 and 4 workers on the seven reference films), and on success removes the workers' stores from `DIR/workers/`.
A failed worker stops the others and leaves their stores there for inspection, with no `render.json` in `DIR`.
It needs `--out-dir` and refuses `--video`, `--sample-count` and `-o`.
Lavapipe draws a device on one thread, so this is how one film uses more than one core; each worker holds the whole world, about 953 MiB (0.93 GiB) for `LOCATION` ([lavapipe render workers, § 2](../../research/parity/lavapipe-render-workers.md#2-multi-vkdevice-in-process-versus-child-processes)).
`mise run parity -- --workers N` passes it on, cutting N so the jobs' worker processes fit the cores and that much memory each.
`mise run parity` always starts the film with the most captured ticks first, whatever `--workers` is.

## Render chosen ticks beside their capture

`mise run frame -- --film intro --ticks 48,92,1009 [--crop x0,y0,x1,y1] [--scale N] [--no-build]` renders the listed ticks in one process and writes each beside its reference capture frame; a tick the capture holds no frame for is rendered, and its nearest captured ticks are printed instead of a picture; PNGs and the render store go to `build/scratch/frame/<film>/`.
`stuntreel --at-ticks T,T,... --out-dir DIR` is the underlying flag.
