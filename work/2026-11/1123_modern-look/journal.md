# Journal: a viewer-only modern look

## 2026-11-26: Does the modern look leave the parity path unchanged?

- **Question**: does adding the modern pipelines, a second camera uniform and a reserved vertex flag bit change anything the parity look draws or hashes?
- **Method**: on the canonical lavapipe (Ubuntu `mesa-vulkan-drivers 25.2.8-0ubuntu0.24.04.5`, a cloud container), `mise run parity -- --software-only` at `origin/main` (`c2b23b4`) and at the branch head, then `cmp` of each film's `frames.zst`, `layers.zst`, `palettes.zst` and `shapes.zst`, `mise run judge` over the two report trees, and `stuntreel shape-views --views top` over `CTRY.ALL` and the superset archive at both commits.
- **Result**: all 28 store files (seven reference films, four planes each) are byte-identical; the judge shows the same headline scores to four decimals on every film (mean SSIM 0.9157 both sides) and no class loss moved; the shape-views manifests give identical geometry hashes for all 131 `CTRY.ALL` shapes and all 2,516 superset shapes.
  The four GPU tests in `crates/stunt-render/tests/gpu/modern.rs` pass on lavapipe: an upright facet (nearly edge-on to the overhead sun) is dimmer in the modern look than in the parity look and every index, layer and shape plane is the same; a facet tilted toward the sun is brighter than one tilted away and no brighter than in the parity look; a pre-shaded facet draws the same colour in both looks; a pre-shaded facet 20 km away is exactly the horizon index's colour.
  The side-by-side stills of `CTRY.FLM` ticks 300, 700 and 1100 (parity left, modern right) are [`images/ctry-300-700-1100-mode13h-vs-modern.png`](images/ctry-300-700-1100-mode13h-vs-modern.png): wings, trees and hillsides take light by their facing, shadows and the sky are unchanged, and fog is slight at these ranges.
- **Verdict**: control; the parity path is unchanged on lavapipe, so `lavapipe.toml` is not repinned.
  The GPU was not run: it is Legion's.
- **Lives in**: [Render a film](../../../docs/howto/render-a-film.md#watch-it-lit-and-fogged).
