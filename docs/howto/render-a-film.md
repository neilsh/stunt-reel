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
stuntreel --look modern --grade --vignette <film and flags as above>
```

`--look modern` lights the film in RGB against its sun, with a sky fill, and fogs distance toward the horizon sky, through pipelines and shader entry points beside the parity ones; `--look mode13h` is the default.
A facet takes `min(SUN * lambert + fill, 1)` per channel of its palette colour at full brightness: the fill is a hemisphere term, brighter facing up than facing down and tinted toward the sky, so a wall turned from the sun keeps about four fifths of its colour where it once fell to half (`ModernUniform::SUN`, `FILL_UP`, `FILL_DOWN` and `FILL_TINT` in `camera.rs`).
A Gouraud ramp (`GVPOLY`) is smooth: the fragment blends the palette entries either side of its fractional index where Mode 13h steps by whole entries; a flat polygon is one index and stays a single colour, faceted from its neighbours.
Polygons whose colour already carries `OP_SHADES` light keep their palette colour, ramp smoothed, with no sun and no fill, so nothing is lit twice, and so do discs and facet-less lines, which have no normal to light; the letterbox and the pixel snapping are the Mode 13h look's.
The sky is a smooth gradient, not the Mode 13h look's bands: each pixel's view ray is placed on `PLAYONE`'s band edges (edge `j` is the point `1024 j` out and `2048 - 128 j` up, so a ray's elevation gives a continuous `j`) and takes the blend of palette entries `224 + j`, the zenith colour straight up.
At and below the horizon (edge 14's elevation, about 1 degree up) and in an orthographic view it is the horizon colour, index 238, the colour distance fogs to, so fog and sky meet with no seam, a low sun's glow included; PLAYONE's `0xD0` ground fill is not drawn.
The gradient follows the view's elevation, so it matches the bands on the view's centre column and differs from their straight edges under pitch.
The sun is a soft glow toward its colour (index 239) rather than the hard disc: strongest, 0.9 of the way to the sun colour, within 1 degree of the sun and gone beyond 5, and it tints only the sky above the horizon (`ModernUniform::GLOW_INNER_DEGREES`, `GLOW_OUTER_DEGREES`, `GLOW`).
The sky entry points are `fs_sky_modern` and `fs_sky_modern_plane` in the modern section of `mode13h.wgsl`; the plane still holds the Mode 13h sky's index, so picking and the layer plane are unchanged.
Two finishes sit on top, each its own flag, off by default and refused without `--look modern`; with both off the page is byte-identical to one rendered without them.
`--grade` raises saturation and contrast about mid-grey a little and warms the colour a touch, in the target's sRGB values (`ModernUniform::GRADE_SATURATION` 1.10, `GRADE_CONTRAST` 1.05, `GRADE_WARM` 0.010, added to red, 0.35 of it to green, taken from blue).
`--vignette` darkens toward the corners by `1 - VIGNETTE * smoothstep(VIGNETTE_START, VIGNETTE_END, r)`, `r` the distance from the centre of the rectangle the scene is drawn into (the 4:3 window area, the top `--viewport-rows` rows, or the whole page headless) over its half-diagonal; `VIGNETTE` is 0.25, from 0.5 to 1.0 (`ModernUniform`).
Both are applied to every modern fragment, the sky included, in `modern_finish` in the modern section of `mode13h.wgsl`; the letterbox bars are neither graded nor vignetted, and the planes are unchanged.
It is a viewer: `--out-dir` refuses it, since the render store holds Mode 13h renders that are scored, and `stuntreel shape-views` stays on the Mode 13h look.

## See what each pixel is

```bash
stuntreel --look diagnostic <film and flags as above>
stuntreel --look diagnostic --headless <film and flags as above> --video film.mp4
stuntreel --look diagnostic --headless <film and flags as above> -o still.png
```

`--look diagnostic` colours each object by what it is, outlines it and lays a world grid over the ground, to read which object a pixel belongs to and which draws over which.
It has no lighting, fog, grade or vignette, so `--grade` and `--vignette` stay modern-only; like `--look modern` it is a viewer, and `--out-dir` refuses it.
Each filled object's colour (not the overlay, a shadow or an outline) is its base colour times a facing factor, `0.55 + 0.45 * abs(normal . view)`, which keeps it reading as solid; a fragment with no facet normal (pre-shaded, disc, a line with no facet) takes `0.45 + 0.75 * luma` of its palette colour at full brightness, at most 1.2.
`hue(k)` is HSV with hue `fract(k * 0.618034)`, saturation 0.6 and value 1.

| Pixel | Colour |
|---|---|
| Sky | flat near-black `#101018` |
| Ocean | blue `(40, 70, 140)` times facing, with the grid |
| Terrain | grey `(110, 120, 110)` times facing, with the grid |
| Prop | `hue(shape word)` times facing: the same shape is the same colour wherever it stands; a world prop's shape comes from its prop run |
| Flat world prop (ground-like: scenery class prop, normal within about 18 degrees of vertical, not a decal) | its hue mixed 65% toward the terrain grey, with the grid, so a ground drawn as one large prop does not shout |
| Actor or sprite | `hue(layer)` times facing: an actor's shape word is 0 in the stored planes, so its colour is keyed by its layer, `LAYER_FIRST_ACTOR + n` |
| Overlay and credits | white |
| Decal tie (a decal and the polygon it lies on, `SodVertex::decal_tie`) | its object's colour, every other 4-pixel diagonal screen stripe mixed 35% toward white |
| Shadow | 0.2 of its actor's colour with a 1-pixel cross-hatch every 6 pixels mixed 30% toward it; a shadow is the actor's shape drawn again, so it shares the actor's layer |
| Outline | 0.25 of its object's colour: every per-frame shape's and world prop's polygon edges (terrain has no edge list, hence the grid) |

The grid is in world x and z: a minor line every 100 m (25% toward `(170, 200, 255)`) and a major line every 1000 m (another 50% on top), each about one pixel wide and faded out where a cell is a few pixels across.
The world defines no terrain cell size, so the spacings are fixed.
The entry points are `vs_diagnostic`, `vs_diagnostic_edge`, `fs_diagnostic`, `fs_sky_diagnostic` and their `_plane` variants in the diagnostic section of `mode13h.wgsl`; the plane variants write the Mode 13h index, layer and shape word, so a diagnostic page's planes are a Mode 13h page's.

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
