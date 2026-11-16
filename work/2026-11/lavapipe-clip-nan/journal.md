# Journal: an isolated repro of the clipper's NaN noperspective varying

## 2026-11-16: the repro on two Mesa builds and the GPU

- **Question**: does a standalone program, with no Stunt Reel code or data, draw a NaN `noperspective` varying on lavapipe through each of the two mechanisms in [`lavapipe.md`](../../../research/parity/lavapipe.md) section 2, and none on a GPU?
- **Method**: on `7b9b63c5` (the repro does not build or read `crates/`), RTX 4070 laptop, Windows 11. [`repro/`](repro/) is a standalone cargo project: `ash` 0.38, and `naga` 30 compiling the GLSL shaders to SPIR-V in-process, with naga's y flip and bounds clamps off so `gl_Position` reaches the driver as written. It draws one triangle per case into two 64×64 `R8G8B8A8_UNORM` targets with no depth buffer, culling off and depth clamp off. The vertex shader reads the three clip-space positions and the attribute from push constants, indexed by `gl_VertexIndex`, so no compiler can fold the varying to a constant. The attribute is 1.0 at every vertex, and is written to a `noperspective` and a perspective varying. The fragment shader classifies each varying by its bits: NaN red, infinite yellow, 1.0 within 1e-5 green, other finite blue. The program reads both targets back and counts each colour. The cases (x, y, z, w):
  - A, an edge left on x = w by the x ≤ w pass, cut by x ≥ -w at w = 0: (-0.5, -0.5, 0.75, 1), (3.5, -0.5, 1.75, 2), (-2.5, -0.5, -4.25, -4).
  - B, the near plane alone on an edge whose ends share screen x 0.5: (1, -1, -1, 2), (2, 3, 1, 4), (-3, 3, 1, 4).
  - control, B with the first vertex at screen x 0: (0, -1, -1, 2), (2, 3, 1, 4), (-3, 3, 1, 4).

  The vertices were chosen with [`replay_interp.py`](replay_interp.py), a float32 port of `do_clip_tri`, `getclipdist`, `interp()` and `LINTERP` from `draw_pipe_clip.c`, with the plane order of `draw_context.c` and the half-z near plane `(0, 0, 1, 0)` from `draw_pt_post_vs.c` line 163, all fetched from `gitlab.freedesktop.org` at `mesa-25.2.8` and `main`. Lines 90-260 of `draw_pipe_clip.c`, `LINTERP` and `interp()` included, are identical at both refs. A first case A, (-0.5, -0.5, 0.5, 1), (4, -0.5, 1.5, 2), (0.2, -0.5, -1, -1), stayed finite in the replay: the x ≤ w pass put its second cut point at x -0.11111112, w -0.1111111, a rounding off the plane, so the later cut landed at w 7.45e-9 with a divisor of -1.19e-7 and a finite weight. Dyadic coordinates put both cut points exactly on x = w. The program ran with `VK_DRIVER_FILES` naming only `E:\git\stunt-reel.data\tools\mesa-<version>\x64\lvp_icd.x86_64.json`, then with it unset and the device chosen by the substring `NVIDIA`.
- **Result**: the replay gives `t_nopersp` = NaN / 0 at case A's x ≥ -w cut, at (0, -0.5, -0.25, 0): `dst_x/dst_w` is 0/0, and the divisor is 1 - 1 because both ends of the edge lie at screen x 1. The y ≥ -w pass then cuts both edges at that vertex, and both new vertices read NaN. The emitted polygon is v0, N1, N5, N6, N4, and each of its three fan triangles has N5 or N6 as a vertex. Case B gives 0/0 at the near-plane cut (1.5, 1, 0, 3), which becomes the first vertex of the emitted polygon, so every fan triangle has it. The control's cuts have finite weights. The program, pixels per class out of 4,096 per target:

  | Adapter (driver info) | Case | `noperspective` | perspective |
  |---|---|---|---|
  | `llvmpipe (LLVM 21.1.7, 256 bits)` (Mesa 25.2.8, git-766909b321) | A | NaN 1,077 | 1.0 on 1,077 |
  | | B | NaN 442 | 1.0 on 442 |
  | | control | 1.0 on 434 | 1.0 on 434 |
  | `llvmpipe (LLVM 23.1.4, 256 bits)` (Mesa 26.2.6, git-a44c011e2d) | A | NaN 1,077 | 1.0 on 1,077 |
  | | B | NaN 442 | 1.0 on 442 |
  | | control | 1.0 on 434 | 1.0 on 434 |
  | NVIDIA GeForce RTX 4070 Laptop GPU (610.88) | A | 1.0 on 1,082 | 1.0 on 1,082 |
  | | B | 1.0 on 442 | 1.0 on 442 |
  | | control | 1.0 on 434 | 1.0 on 434 |

  No pixel was infinite, finite and wrong, or of any other colour on any adapter. On lavapipe every covered pixel of cases A and B reads NaN in the `noperspective` target: 1,519 in all on each build. The GPU covers five more pixels of case A than lavapipe (1,082 against 1,077); why its coverage differs at the polygon's edge was not checked. `replay_interp.py --suggested-fix`, which picks the axis by screen-space difference and falls back to the 3D `t` when no axis gives a finite weight, gives every emitted vertex of all three cases a finite `noperspective` value of 1.0; this is a replay, not a Mesa build.
- **Verdict**: control. Both mechanisms reproduce outside Stunt Reel on both builds, and the GPU draws no NaN pixel. The issue text is [`issue-draft.md`](issue-draft.md), not filed.
- **Lives in**: [`lavapipe.md`](../../../research/parity/lavapipe.md) section 2.
