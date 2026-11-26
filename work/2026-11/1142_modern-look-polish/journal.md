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
