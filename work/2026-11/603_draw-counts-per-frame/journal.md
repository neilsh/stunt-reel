# Journal

## 2026-11-16: draws per frame, and coalescing adjacent base slices

- **Question**: How many `draw_indexed` calls does a LOCATION frame issue, split by pass, and how
  many of the world's base-pass calls would coalescing contiguous base mesh slices remove?
- **Method**:
  - Built `origin/main` (`b0f6c120`) with a temporary, uncommitted counter in
    `SceneRenderer::draw` (`crates/stunt-render/src/scene_renderer.rs`). It counted the
    `draw_indexed` calls the prepared lists encode, one line per frame into a file, and ran the
    candidate `coalesce_base_meshes` (`mesh.rs`) over each base list to count what it would
    remove. Both files were reverted afterwards; no renderer change is committed.
  - Rendered LOCATION ticks 12-300 (289 frames) headless with the parity pipeline's arguments
    (`--at-ticks` for those ticks, `--width 320 --height 200 --viewport-rows 185`), one process
    per adapter: on mesa-dist-win 25.2.8 (`llvmpipe (LLVM 21.1.7, 256 bits)`,
    `VK_DRIVER_FILES` naming its `lvp_icd.x86_64.json`, `--software-only`) and on the RTX 4070
    Laptop.
- **Result**:
  - **Calls per frame**, median of the 289 frames. The counter reads the renderer's prepared
    lists, not anything the driver does, and both adapters printed the same 289 lines, differing
    in none:

    | `draw_indexed` calls | Median frame |
    |---|---|
    | world ground fill | 8,963 |
    | world ground outlines | 6,269 |
    | world base fill | 49,257 |
    | world base outlines | 45,560 |
    | world decal fill | 5,550 |
    | world decal outlines | 5,549 |
    | prop, actor and sprite fill | 6,762 |
    | **all** | **127,910** |

    Only the base and prop rows move across the span: on the frames whose gated props drop out,
    the base rows fall to 48,900 and 45,203 and the prop row rises to 6,763, so the lightest frame
    issues 127,197 calls.
  - The world uploads as one chunk: 6,702,496 vertices and 7,488,138 indices, so every base
    slice draws with base vertex 0 and its own absolute index range (the temporary counter read
    one distinct base vertex over the whole base list).
  - **Coalescing removes none.** In all 289 frames no adjacent pair of the base list had the
    second slice's index range start where the first's ends, so the candidate merge saves 0 of
    the 49,257 fill and 0 of the 45,560 outline calls. The base walk takes siblings last first
    (`VisibleWalk::walk`) while the IR numbers nodes in creation order, so a parent's child
    slices come out in the reverse of their index order, and none continued the one before it.
- **Verdict**: no-go. Coalescing contiguous base slices removes 0 of the median frame's 127,910
  `draw_indexed` calls, against the issue's 25% bar, so the counts decide it rather than a
  timing. They also replace the issue's estimate of 10^2-10^3 world mesh slices per frame: the
  median frame issues 1.3 x 10^5 calls, nearly three quarters of them in the world base pass.
- **Lives in**: [`research/parity/lavapipe.md`](../../../research/parity/lavapipe.md) section 6.
