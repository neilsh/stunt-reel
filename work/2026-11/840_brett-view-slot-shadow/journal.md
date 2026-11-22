# Journal: #840 the view slot's shadow footprint in `BRETT.FLM`

## 2026-11-22: the shadow draw's facing gates test the flattened face

**Question**: why does the view slot's shadow draw 22 of `BRETT.FLM`'s 4,856 index-0 pixels in rows 150 to 184 on 19 view-slot frames and 3,327 on tick 716 ([#840](https://github.com/neilsh/stunt-reel/issues/840), after [#499](../499_view-slot-shadow-gpu/journal.md#2026-11-20-the-gpu-judge-and-the-view-slots-shadow-against-brettflms-capture))?

**Method**: local-windows, NVIDIA GeForce RTX 4070 Laptop GPU, on `2aa45d25` (`crates/` as `main`'s, near plane 0.1 m since [#905](https://github.com/neilsh/stunt-reel/issues/905), not the 0.5 m the issue quotes).
`stuntreel --headless corpus/siarchive/Films/OldPLAY/Vault/BRETT.FLM --all <data root>/captures/vault-brett/archives/BRETT.ALL --at-ticks 409,419,431,442,452,606,617,628,639,651,661,673,683,694,705,716,727,738,749,761 --sidata <SIDATA> --width 320 --height 200 --viewport-rows 185`, then the index-0 pixels of rows 150 to 184 counted on the render store's index plane and on the capture's, per tick, as the #499 entry counts.
The view slot's create flags and the break at `0x1A18` come from [#510](../510_view-slot-shadow/journal.md#2026-11-16-the-view-slots-shadow-live-and-a-reference-film-for-it): flags `0x1F`.
A scratch `eprintln!` (not committed) printed, for the view actor on ticks 639 and 716, each node of shape `0x415C` (`MODEL_415C.SOD`) with its visibility gate, whether the walk kept it, and its index count.
The capture's band was measured from `captures/vault-brett/frames` (row extents of index 0 on ticks 431, 639 and 716).
The fix is `f1ab20bf`.
Scores: `mise run parity -- --jobs 4` on `main`'s `crates/` (stashed change) and on the change, on the GPU, then again with `VK_DRIVER_FILES` set to the mesa-25.2.8 ICD and `--software-only` (`llvmpipe (LLVM 21.1.7, 256 bits)`), each pair judged with `mise run judge -- <baseline reports> <candidate reports> --track evidence`.

**Result**:

- **`SIF_MOVES`.** The view slot's flags are `0x1F` (bit 3 set) and the probe's plane branch `0x1A18` hit on it, so `PLAYONE` probes it and the static-slot rule ([`.out-of-scope/static-slot-shadow-plane.md`](../../../.out-of-scope/static-slot-shadow-plane.md)) does not apply.
- **The capture's band is the car's footprint.** On ticks 431, 639 and 716 the index-0 pixels of rows 168 to 185 are the same: row 168 spans columns 31 to 287 (257 pixels), widening about 3.4 columns per row to the full width at row 185.
  With the eye 0.1509 m above the plane and the 42.67 degree lens that is a rectangle as wide as the car (0.503 m) whose front edge is at the car's nose, z = 0.503 m: the flattened roof, hood and floor, filled in index 0.
- **Ours drew none of it.** The view actor's shadow had 5 meshes (270 indices) on tick 639 and 6 (324) on tick 716, all of them `FacesEye` groups of vertical walls, which flatten to no area; tick 716's sixth is a sloped lip, the source of its 3,327.
  The groups that carry the flat faces (roof `MODEL_415C.SOD_BASE_5`, hood `_4`, floor `_20`) were culled by the gate, which tested the real face against the real eye, and the eye (y 0.1509 m) is inside the car (roof at 0.30 m).
- **Why `PLAYONE` keeps them.** `REJ` (`0x9567`) computes the normal from the vertex registers and tests `n . (b + o)` ([`sod-vm-execution.md` § 8.6](../../../research/playone-exe/sod-vm-execution.md#86-facing-flags-op_rej-and-op_ifvis)); in the shadow draw those registers hold the points the flattening matrix of `0x1C0D` produced and `o` is the shadow's ground point.
  Flattened along `y` onto a plane with normal `p`, a face's normal becomes `(n_y / p_y) p`, so a face passes when its world normal points up (the eye above the plane), whatever the eye's side of the real face.
- **The change.** The shadow draw collects its slices with each `FacesEye` gate tested as `cofactor(L) * n . (M b) < 0`, `M` the eye-relative shadow matrix and `L` its linear part (`GpuModel::collect_shadow_meshes`, `faces_flattened`); the actor draw keeps the real-eye test.
- **`BRETT.FLM`, 20 view-slot frames.** Index-0 pixels in rows 150 to 184 before (near plane 0.1 m): 22 on 19 frames, 3,327 on tick 716; after: 4,809 on all 20, against the capture's 4,856.
  The 47 missing are edge pixels (the band's slanted sides and one lip at its lower left).
  The pictures: [tick 639](images/brett-639-view-shadow-faces.png) and [tick 716](images/brett-716-view-shadow-faces.png), rows 120 to 185 at 2x, each the capture, before and after left to right.
- **Reference films, GPU.** `mean_ssim_scored` before and after: ctry 0.9377 to 0.9385, intro 0.8825 to 0.8833, land 0.9240 to 0.9245, balloon 0.9059 to 0.9059, traintnl 0.9107 to 0.9107, bomb 0.8948 to 0.8949, location 0.8725 to 0.8727; IoU equal to four decimals on every film; no frame falls by more than 0.005 (worst -0.0013); index agreement frames better/worse: ctry 44/0, intro 84/8, land 51/2, bomb 23/4, location 21/0; loss by class falls on props and actors (ctry props -0.0005, actors -0.0003).
  Winner line: `winner: run=candidate adopts (evidence, film means)`.
- **Reference films, lavapipe (local mesa 25.2.8, LLVM 21.1.7).** The same scores to four decimals (location 0.8725 to 0.8728), 0 frames down more than 0.005, the same winner line.
- **Not run.** The other candidates the issue lists (the cull `0x1B0C`, a near-plane clip of the shadow polygon at `0x1C0D`, the winding seen from inside, the 1 mm lift at near depths) were not tested: the cull passes this slot by break ([#510](../510_view-slot-shadow/journal.md#2026-11-16-the-view-slots-shadow-live-and-a-reference-film-for-it)), and the facing gate accounts for the band without them.

**Verdict**: adopted on the evidence track (the `REJ` reading at `0x9567` is the rule; the judge's film-mean branch has films that rise on the GPU and on lavapipe, and no guard fires).
The `lavapipe` expected table was not repinned: the canonical lavapipe is the WSL one ([`render-on-lavapipe.md` § 5](../../../docs/howto/render-on-lavapipe.md#5-render-the-canonical-lavapipe-under-wsl)) and this session ran the local build only; the `gpu` table was repinned.

**Lives in**: [`hero-shadow.md`](../../../research/parity/hero-shadow.md) question 10, [`sod-vm-execution.md` § 8.6](../../../research/playone-exe/sod-vm-execution.md#86-facing-flags-op_rej-and-op_ifvis).
