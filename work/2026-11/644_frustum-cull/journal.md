# Journal

## 2026-11-16: culling world nodes outside the view frustum

- **Question**: How many of a LOCATION frame's `draw_indexed` calls and how much of its render time
  go to world slices wholly outside the view, and does skipping them leave every pixel where it
  was?
- **Method**:
  - PR #652 at `3e956d1a` against `origin/main` `857f80a8`: each world node carries a box around
    its own and its descendants' vertices, and `VisibleWalk::walk` skips a node, subtree and
    all, when every corner lies outside one plane of the view-projection matrix
    (`frustum_keeps`, `crates/stunt-render/src/mesh.rs`).
  - Full GPU `mise run parity` (all seven films) on the RTX 4070 Laptop, SHA-256 of `frames.zst`,
    `layers.zst` and `palettes.zst` against `main`'s, and `mise run judge` between the two
    reports.
  - LOCATION ticks 12-300 with the parity pipeline's render command (`--at-ticks 12,...,300
    --width 320 --height 200 --viewport-rows 185`), one run each before and after, on
    mesa-dist-win 25.2.8 (`llvmpipe (LLVM 21.1.7, 256 bits)`, `--software-only`) and on the GPU,
    timed and byte-compared.
  - #603's counter ([`draw-counter.patch`](../603_draw-counts-per-frame/draw-counter.patch)),
    applied locally and not committed, over the same 289 frames.
- **Result**:
  - The GPU's stores are byte-identical for all seven films, 21 of 21 files, 20,621 ticks; the
    judge moves no scored frame (`none adopts`). Lavapipe's LOCATION 12-300 stores are
    byte-identical too.
  - Median `draw_indexed` calls per frame, before and after: world ground fill 8,963 to 5,
    ground outlines 6,269 to 3, base fill 49,257 to 11, base outlines 45,560 to 10, decal fill
    5,550 to 0, decal outlines 5,549 to 0, prop, actor and sprite fill 6,762 to 6,762; all
    127,910 to 6,791 (-94.7%). The six world categories' medians sum to 29 after (the world's
    per-frame total at most 133):
    these frames are a close-up of an aircraft against sea and sky.
  - LOCATION 12-300 wall clock: lavapipe 81.7 s to 13.7 s (-83.2%), GPU 14.6 s to 4.7 s (-67.8%),
    one run each.
- **Verdict**: adopted: no pixel of the seven films' captured ticks moves on the GPU, nor of
  LOCATION 12-300 on lavapipe, and both adapters render faster (one run each).
- **Lives in**: [`research/parity/lavapipe.md` § 6](../../../research/parity/lavapipe.md#6-render-time).

## 2026-11-17: the cull on top of eye-relative transforms

- **Question**: Does the cull still leave every pixel where it was once #636's eye-relative
  transforms (`e6fb29c`) and #635 (`734d3a8`) are under it?
- **Method**: PR #652 merged with `origin/main` `734d3a8`; the cull now takes the world to clip
  space by `rotation_proj` times the world's eye-relative matrix, the product the vertex shader
  forms. In a cloud session, `mise run parity -- --software-only` on all seven films, once on the
  branch (`6f58988`) and once on `734d3a8`, on Ubuntu's Mesa 25.2.8 (`llvmpipe (LLVM 20.1.2, 256
  bits)`), then SHA-256 of every `build/parity/ours/<film>_current/*.zst`.
- **Result**: all 21 files are byte-identical between the two trees, and the seven score lines
  match. The GPU check was not repeated on this base. `852db54`, which stops moving each box by
  the node's `local_matrix`, was not re-run; every world node's `local_matrix` is the identity
  (`stunt_core::world::mesh`), so no box changes.
- **Verdict**: control: the cull still moves no pixel of the seven films' captured ticks on
  Ubuntu's lavapipe.
- **Lives in**: [`research/parity/lavapipe.md` § 6](../../../research/parity/lavapipe.md#6-render-time).
