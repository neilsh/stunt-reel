# Journal

## 2026-11-22: bisecting the non-world draw count

- **Question**: Which commit between `b0f6c120` and `6955e159` cut the median LOCATION frame's (ticks 12..=300) non-world fills from 6,762 to about 2,573, and why?
- **Method**:
  - A temporary counter at the top of `SceneRenderer::draw` (`crates/stunt-render/src/scene_renderer.rs`) sums, over every prepared draw that is not the world (`self.prepared`, then each `WalkStep`'s sprites, props and actors where the tree has `steps`), `base.len() + decals.len()`: #603's prop row, split by target (view-facing shape base, shape decals, shape shadows, images, and lit actors with their shadows).
    It writes one line per frame to `DBG_BISECT_FILE`.
    [`draw-counter.patch`](draw-counter.patch) is the counter on `6955e159`, without context lines (`git apply --unidiff-zero`); on a tree before `900ae751` (#737), which has no `WalkStep`, drop the `self.steps` loop.
  - Each tree was built with `cargo build --release -p stunt-cli` and rendered LOCATION ticks 12..=300 (`--at-ticks`, 289 frames) headless at `--width 320 --height 200 --viewport-rows 185 --software-only` on a cloud session's Ubuntu lavapipe (`/usr/share/vulkan/icd.d/lvp_icd.json`), with `builds/patch3/VAULT/LOCATION.FLM`, `captures/vault-location/archives/LOCATION.ALL` and the FreeFlight `SIDATA`.
  - The bisect searched the 49 first-parent `main` commits from `b0f6c120` to `6955e159` that change `crates/`, measuring the trees in the table below; the other commits were not measured.
- **Result**:
  - Median non-world fills per tree (max in parentheses):

    | Tree | Non-world | Shape base (view-facing props and unlit actors) | Shape decals | Shadows and lit actors |
    |---|---|---|---|---|
    | `b0f6c120` | 6,762 (6,763) | 5,373 | 1,340 | 49 |
    | `a5bf0e67` (#624) | 6,764 (6,771) | 5,317 | 1,315 | 132 |
    | `900ae751` (#737) | 6,764 (6,771) | 5,317 | 1,315 | 132 |
    | `f093e2aa` (#756) | 6,764 (6,771) | 5,317 | 1,315 | 132 |
    | `b028f7d3` (#690) | 6,764 (6,771) | 5,317 | 1,315 | 132 |
    | `f95ec4a0` (#811) | 2,571 (2,578) | 2,435 | 4 | 132 |
    | `6955e159` | 2,571 (2,578) | 2,435 | 4 | 132 |
    | `f95ec4a0`, no `ScaleReach` gate on view-facing props | 6,764 (6,771) | 5,317 | 1,315 | 132 |

    No tree drew a sprite.
    The counter reproduces section 1's 6,762 at `b0f6c120`.
    At `6955e159` it reads 2,571, two below the 2,573 that section 2's #918 probe implies (2,602 calls less 29 world draws), which counts the slices `encode` draws rather than the prepared lists.
  - `f95ec4a0` (#811, PR #902) is the first tree with the low count.
    It gives each view-facing prop that some camera eye puts past `PLAYONE`'s `scale_index` distance cut a `VisibilityCondition::ScaleReach` gate (`facing_props` in `crates/stunt-core/src/world/assemble.rs`), and `FilmScene::frame` drops the prop on a frame once its largest eye-relative coordinate reaches `2^(22 + [0x229E] - scale_index)` metres (`CameraTransform::scale_reach_keeps`).
  - The control build, `f95ec4a0` with only that gate left off view-facing props (`p.reach` filtered out in `facing_props`), returned the median to 6,764, so the gate accounts for the whole drop in this span's median non-world fills.
    The world's own fills kept a median of 16 and a max of 68 at both `b028f7d3` and `f95ec4a0`, so on this span the cut's world `WORLD_REACH` groups leave those figures unchanged.
- **Verdict**: `f95ec4a0`'s per-frame `ScaleReach` gate on view-facing props cut the non-world fills; the other trees measured moved the median by at most 2.
- **Lives in**: [`research/parity/lavapipe-render-time.md`](../../../research/parity/lavapipe-render-time.md) section 1.
