# Journal: modern look polish

## 2026-11-26: Does the RGB fill and smooth shading leave the parity path unchanged? (#1143)

- **Question**: does lighting the modern look in RGB with a sky fill, and blending adjacent palette entries per fragment (`modern_shade`), change anything the parity look draws or stores?
- **Method**: on the canonical lavapipe (Ubuntu `mesa-vulkan-drivers 25.2.8-0ubuntu0.24.04.5`, a cloud container), `mise run parity -- --software-only` at `origin/main` (`69126dc`, a detached worktree) and at the branch head, then `cmp` of each film's `frames.zst`, `layers.zst`, `palettes.zst` and `shapes.zst`, and `mise run judge` over the two report trees.
- **Result**: the raw `cmp` and judge output is [`parity-1143.txt`](parity-1143.txt), the candidate being `dc1ae10` (later commits touch tests and the work folder only).
  All 28 store files (seven reference films, four planes each) are byte-identical; the judge shows 0 frames down more than 0.005, no class loss moved, index agreement equal on every film, and mean SSIM 0.9162 on both sides.
  The GPU tests in `crates/stunt-render/tests/gpu/modern.rs` pass on lavapipe: a wall turned from the sun keeps at least 0.6 of its parity colour and no more than all of it; an upward facet is brighter than a downward one at the same angle; a pre-shaded 16 to 31 ramp shows more distinct colours than the parity look's steps with no larger jump between neighbours, and its index, layer and shape planes equal the parity look's.
- **Verdict**: control; the parity path is unchanged on lavapipe, so `lavapipe.toml` is not repinned.
  The GPU was not run.
  `mode13h.wgsl` changes only below the `// The modern look` comment's first line; `VertexOutput`, `vertex_output`, `fragment_index`, the parity and sky entry points are untouched, so nothing goes to the next class-agreement batch.
- **Lives in**: [Render a film](../../../docs/howto/render-a-film.md#watch-it-lit-and-fogged).

## 2026-11-26: Fill constants tuned on stills (#1143)

- **Question**: what `SUN`, `FILL_UP`, `FILL_DOWN` and `FILL_TINT` lift the back-facing walls of the `bomb` hangar and church?
- **Method**: stills of `bomb` ticks 5 (church) and 300 (hangar) and `location` ticks 2850 (stadium) and 3600 (city), `stuntreel --look modern --headless ... --tick-range T..=T -o`, at the plan's start (0.5, 0.8, 0.55, 0.4), (0.4, 0.9, 0.7, 0.25), (0.35, 0.95, 0.8, 0.15), then 0.4, 0.92, 0.72, 0.2.
- **Result**: at the plan's start a hangar or church wall read as a dull, blue-grey 0.68 of its parity white and the tint was strong on the city blocks; the last two lifted the walls, but 0.35/0.95/0.8 flattened sunlit against shaded faces.
  The chosen 0.4, 0.92, 0.72, 0.2 puts the church wall at (167, 185, 199) and the hangar wall at (167, 185, 198) against the parity (224, 220, 220), 0.83 of its brightness by channel sum, where the old floor gave 0.51, and still leaves sunlit roofs and tops brighter than the walls.
- **Verdict**: adopted: `SUN 0.4`, `FILL_UP 0.92`, `FILL_DOWN 0.72`, `FILL_TINT 0.2`, decided by eye on the stills (walls lifted, sunlit faces still brighter); Neil judges the stills.
- **Stills** (Mode 13h left, modern right, single screens at 2x): [church](images/bomb-church-mode13h-vs-modern.png), [hangar](images/bomb-hangar-mode13h-vs-modern.png), [stadium](images/location-stadium-mode13h-vs-modern.png), [city](images/location-city-mode13h-vs-modern.png), and the #1131 span, `CTRY.FLM` ticks 300, 700 and 1100: [`images/ctry-300-700-1100-mode13h-vs-modern.png`](images/ctry-300-700-1100-mode13h-vs-modern.png).
  The clips are not in git: `/mnt/project-files/1143-modern-fill/`.
- **Lives in**: [Render a film](../../../docs/howto/render-a-film.md#watch-it-lit-and-fogged); the constants are `ModernUniform` in `crates/stunt-render/src/camera.rs`.

## 2026-11-26: Does the gradient sky leave the parity path unchanged? (#1144)

- **Question**: does drawing the modern look's sky through `fs_sky_modern` and `fs_sky_modern_plane`, with a view-ray basis added to `ModernUniform`, change anything the parity look draws or stores?
- **Method**: on the canonical lavapipe (Ubuntu `mesa-vulkan-drivers 25.2.8-0ubuntu0.24.04.5`, a cloud container), `mise run parity -- --software-only` at `origin/main` (`d5416d1`, a detached checkout) and at the branch commit `371fade`, then `cmp` of each film's `frames.zst`, `layers.zst`, `palettes.zst` and `shapes.zst`, and `mise run judge` over the two report trees.
  An earlier run on `2f383d1`, before the glow constants changed from 1.5 and 9.0 degrees to 1.0 and 5.0, gave the same result.
- **Result**: the raw `cmp` and judge output is [`parity-1144.txt`](parity-1144.txt).
  All 28 store files (seven reference films, four planes each) are byte-identical; the judge shows 0 frames down more than 0.005, no class loss moved, index agreement equal on every film, and mean SSIM 0.9162 on both sides.
  The GPU tests in `crates/stunt-render/tests/gpu/modern.rs` pass on lavapipe: a level view's sky from two rows above the horizon down is index 238's colour (column 10, clear of any geometry); a far fogged facet on the horizon equals the sky beside it; a view just short of straight up is index 224's colour to within 1 per channel; down a column of a view pitched up 20 degrees no channel reverses and no step exceeds the largest step between adjacent palette entries the Mode 13h sky shows; a view pitched down 60 degrees is index 238's colour throughout; the sun's centre is far nearer index 239's colour than the sky 40 pixels beside it and no step along the row across it reaches 20; and the index, layer and shape planes of four pitches (0, 20, 60 and -30 degrees) equal the Mode 13h look's.
- **Verdict**: control; the parity path is unchanged on lavapipe, so `lavapipe.toml` is not repinned.
  The GPU was not run.
  `mode13h.wgsl` changes only inside the modern section (below the `// The modern look` comment's first line, plus one line in that comment block): `fs_sky`, `fs_sky_plane`, `vs_sky` and everything above are untouched, and `pipeline.rs` keeps `fs_sky` and `fs_sky_plane` for `Look::Mode13h`, so nothing goes to the next class-agreement batch.
  The #1143 test `a_facet_turned_from_the_sun_keeps_most_of_its_colour` read the sky at the centre pixel when the camera stood behind the facet (the facet is culled from behind), where the two looks now differ; it counts only the shot that draws the facet.
- **Lives in**: [Render a film](../../../docs/howto/render-a-film.md#watch-it-lit-and-fogged).

## 2026-11-26: Sun glow size and the horizon, on stills (#1144)

- **Question**: what angular size makes the sun glow read near PLAYONE's disc, and does the gradient meet the fog at the horizon with no seam?
- **Method**: `stuntreel --look <look> --headless ... --tick-range T..=T -o` for `CTRY.FLM` ticks 0, 300, 400, 700, 1000 and 1100 and `INTRO.FLM` ticks 900 and 1200 in both looks; no film looks up (the highest camera pitch sampled every 25 ticks is 5.99853528742373 degrees), so the sun, which sits nearly straight overhead at film variable 13 `0x002D`, was drawn by a throwaway GPU test aimed 40 and 60 degrees up and at the sun, in both looks.
  The glow is `smoothstep` of the cosine between an outer and an inner angle, `GLOW` 0.9 of the way to index 239's colour at its centre.
- **Result**: with 1.5 and 9.0 degrees the glow was a soft blob well over the parity disc's size; with 1.0 and 5.0 it is a soft disc about the parity disc's size with no hard edge.
  On the stills the modern sky is a smooth blue-to-grey fade that reaches the fogged terrain colour at the horizon: at 4x in `CTRY.FLM` tick 0 the sky's last rows and the distant terrain's fog are one colour with no seam, where Mode 13h shows stepped bands and a dark sea strip against them.
  A view looking up shows no band steps.
- **Verdict**: adopted: `GLOW_INNER_DEGREES 1.0`, `GLOW_OUTER_DEGREES 5.0`, `GLOW 0.9`, decided by eye on the stills; Neil judges the stills.
- **Stills** (Mode 13h left, modern right, single screens at 1x, 320 by 240): the #1131 span [`CTRY.FLM` ticks 300, 700 and 1100](images/ctry-300-700-1100-sky-mode13h-vs-modern.png); the horizon in [`CTRY.FLM` ticks 0, 400 and 1000 and `INTRO.FLM` ticks 900 and 1200](images/horizon-ctry-intro-mode13h-vs-modern.png); and a synthetic [view looking up and at the sun](images/sky-looking-up-mode13h-vs-modern.png), pitched 40 and 60 degrees and straight at it.
  The clips `ctry_flight_mode13h-left_modern-right.mp4` (`CTRY.FLM` ticks 0 to 600) and `intro_flight_mode13h-left_modern-right.mp4` (`INTRO.FLM` ticks 880 to 1250) are not in git: `/mnt/project-files/1144-modern-sky/`.
- **Lives in**: [Render a film](../../../docs/howto/render-a-film.md#watch-it-lit-and-fogged); the constants are `ModernUniform` in `crates/stunt-render/src/camera.rs`.
