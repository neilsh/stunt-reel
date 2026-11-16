# Draft: Mesa issue (not filed)

**Title:** draw/clip (llvmpipe, lavapipe): a `noperspective` varying becomes NaN after clipping when `t_nopersp`'s divisor is zero

---

### Summary

When llvmpipe clips a triangle in software, `interp()` in `src/gallium/auxiliary/draw/draw_pipe_clip.c` can divide by zero when it computes the `noperspective` weight `t_nopersp` (0/0 and NaN/0 in the cases below). `LINTERP` then gives NaN even for an attribute that is the same at every vertex, and in the repro's cases the NaN reaches every triangle of the clipped polygon. In the attached Vulkan repro, a `noperspective` varying that is 1.0 at all three vertices reads NaN on every covered pixel of two clipped triangles on lavapipe; a perspective copy of the same varying reads 1.0, and an NVIDIA RTX 4070 reads 1.0 for both.

Context: found while rendering a 1992 game's scenes on lavapipe, where large ground polygons under a low camera drew in the wrong colour.

### Affected versions

- Reproduced with lavapipe from the mesa-dist-win MSVC builds of Mesa 25.2.8 (`llvmpipe (LLVM 21.1.7, 256 bits)`, driver info `Mesa 25.2.8 (git-766909b321)`) and Mesa 26.2.6 (`llvmpipe (LLVM 23.1.4, 256 bits)`, `Mesa 26.2.6 (git-a44c011e2d)`), Windows 11 x64.
- The same symptom showed in the application with Ubuntu 24.04's `mesa-vulkan-drivers` 25.2.8 (LLVM 20.1.2); the repro itself was not run on Linux.
- `draw_pipe_clip.c` is the same file at `mesa-26.2.6` and on `main` (read 2026-11-16; its last commit is `8a1a4103`, "treewide: use SWAP macro"), and differs from `mesa-25.2.8` only by that commit's `SWAP` in `do_clip_tri()`; the line numbers below hold at all three.
- llvmpipe's GL driver goes through the same clipper, but it was not tested.

### Mechanism

llvmpipe turns the guard band off (`src/gallium/drivers/llvmpipe/lp_context.c`, line 339 at `mesa-25.2.8`, line 390 on `main`):

```c
   /* initial state for clipping - enabled, with no guardband */
   draw_set_driver_clipping(llvmpipe->draw, false, false, false, true);
```

so `do_clip_tri()` clips against x ≤ w, x ≥ -w, y ≤ w, y ≥ -w, then the near plane, in that order (`draw_context.c` lines 142-147 at `mesa-25.2.8` and on `main`; with `clip_halfz` the near plane is `(0, 0, 1, 0)`, `draw_pt_post_vs.c` line 163). For each new vertex, `interp()` gives perspective attributes the 3D weight `t`, but computes a screen-space weight for `noperspective` ones (`draw_pipe_clip.c`):

```c
 98 #define LINTERP(T, OUT, IN) ((OUT) + (T) * ((IN) - (OUT)))
...
187    * The points can be aligned with the X axis, so in that case try
188    * the Y.  When both points are at the same screen position, we can
189    * pick whatever value (the interpolated point won't be in front
190    * anyway), so just use the 3d t.
191    */
192   if (clip->num_linear_attribs) {
193      float t_nopersp = t;
194      /* find either in.x != out.x or in.y != out.y */
195      for (int k = 0; k < 2; k++) {
196         if (in->clip_pos[k] != out->clip_pos[k]) {
197            /* do divide by W, then compute linear interpolation factor */
198            float in_coord = in->clip_pos[k] / in->clip_pos[3];
199            float out_coord = out->clip_pos[k] / out->clip_pos[3];
200            float dst_coord = dst->clip_pos[k] / dst->clip_pos[3];
201            t_nopersp = (dst_coord - out_coord) / (in_coord - out_coord);
202            break;
203         }
204      }
205      for (unsigned j = 0; j < clip->num_linear_attribs; j++) {
206         const unsigned attr = clip->linear_attribs[j];
207         interp_attr(dst->data[attr], t_nopersp, in->data[attr], out->data[attr]);
```

The axis is chosen by comparing the endpoints' clip-space coordinates (line 196), but the divisor is their screen-space difference on that axis (line 201). Two endpoints can differ in clip x and share a screen x, so the divisor can be 0, and the loop has already broken on x without trying y, whose screen values differ in both cases below. The comment's fallback to the 3D `t` is not reached either. With `t_nopersp` NaN or infinite, `LINTERP(t, a, a) = a + t * 0` is NaN. Two ways to get there:

- **A. An edge an earlier pass left on a side plane.** After the x ≤ w pass, an edge can lie on x = w from w > 0 to w < 0. Both its ends are at screen x 1, so the divisor is 1 - 1 = 0. The x ≥ -w pass cuts that edge at w = 0, x = 0, where `dst_coord` is 0/0 as well. `t_nopersp` is NaN.
- **B. The near plane alone.** An edge whose ends share a screen x while their clip x differ: (1, -1, -1, 2) to (2, 3, 1, 4) has screen x 0.5 at both ends. The half-z near plane cuts it at (1.5, 1, 0, 3), also at screen x 0.5, so `t_nopersp` = (0.5 - 0.5) / (0.5 - 0.5) = 0/0.

Every vertex later interpolated from a NaN vertex is NaN too. `emit_poly()` emits the clipped polygon as a fan from `inlist[0]` (lines 246-256). In both cases below every fan triangle has a NaN vertex, so the varying is NaN over the whole polygon. In case B the NaN vertex is `inlist[0]` itself.

The attached `replay_interp.py` replays `do_clip_tri()`/`interp()` in float32 (numpy) on the repro's vertices and prints each new vertex with `t_nopersp`'s numerator and divisor.

### Shaders

Vertex:

```glsl
#version 450
layout(push_constant) uniform Triangle {
    vec4 clip_pos[3];
    vec4 attr; // x, y, z: the attribute at vertex 0, 1, 2 (all 1.0)
} tri;
layout(location = 0) noperspective out float v_noperspective;
layout(location = 1) out float v_perspective;
void main() {
    gl_Position = tri.clip_pos[gl_VertexIndex];
    v_noperspective = tri.attr[gl_VertexIndex];
    v_perspective = tri.attr[gl_VertexIndex];
}
```

Fragment (two colour attachments; the bit test is there so no optimiser can assume `isnan` false):

```glsl
#version 450
layout(location = 0) noperspective in float v_noperspective;
layout(location = 1) in float v_perspective;
layout(location = 0) out vec4 noperspective_class;
layout(location = 1) out vec4 perspective_class;
// red: NaN; yellow: infinite; green: finite and 1.0; blue: finite, not 1.0
vec4 classify(float v) {
    uint bits = floatBitsToUint(v);
    if ((bits & 0x7f800000u) == 0x7f800000u) {
        if ((bits & 0x007fffffu) != 0u) {
            return vec4(1.0, 0.0, 0.0, 1.0);
        }
        return vec4(1.0, 1.0, 0.0, 1.0);
    }
    if (abs(v - 1.0) <= 1.0e-5) {
        return vec4(0.0, 1.0, 0.0, 1.0);
    }
    return vec4(0.0, 0.0, 1.0, 1.0);
}
void main() {
    noperspective_class = classify(v_noperspective);
    perspective_class = classify(v_perspective);
}
```

Pipeline state: one triangle (`TRIANGLE_LIST`, 3 vertices, no vertex buffers), 64×64 `R8G8B8A8_UNORM` targets cleared to black, viewport (0, 0, 64, 64) with depth 0 to 1, no depth attachment, cull mode none, depth clamp off.

### Vertex positions (clip space, x, y, z, w, in draw order)

| Case | v0 | v1 | v2 |
|---|---|---|---|
| A: edge on x = w cut by x = -w at w = 0 | (-0.5, -0.5, 0.75, 1) | (3.5, -0.5, 1.75, 2) | (-2.5, -0.5, -4.25, -4) |
| B: near plane, both ends at screen x 0.5 | (1, -1, -1, 2) | (2, 3, 1, 4) | (-3, 3, 1, 4) |
| control: B with v0 at screen x 0 | (0, -1, -1, 2) | (2, 3, 1, 4) | (-3, 3, 1, 4) |

### Expected and actual

Expected: every covered pixel reads 1.0 in both varyings. The RTX 4070 (NVIDIA 610.88) does: A 1,082 pixels, B 442, control 434, all 1.0 in both targets.

Actual, lavapipe 25.2.8 and 26.2.6 alike, pixels out of 4,096:

| Case | `noperspective` | perspective |
|---|---|---|
| A | NaN on all 1,077 covered | 1.0 on 1,077 |
| B | NaN on all 442 covered | 1.0 on 442 |
| control | 1.0 on 434 | 1.0 on 434 |

### How to run the repro

The repro is a small Rust program (`ash` for Vulkan, `naga` to compile the GLSL above to SPIR-V at start-up, so no SDK or `glslc` is needed). With a Rust toolchain:

```sh
cd repro
VK_DRIVER_FILES=/path/to/lvp_icd.x86_64.json cargo run --release   # lavapipe
cargo run --release -- NVIDIA                                       # first device whose name contains "NVIDIA"
python ../replay_interp.py                                          # the host-side replay (numpy)
```

It prints the adapter name and driver info, then, per case and per target, the number of NaN, infinite, correct (1.0), wrong (finite, not 1.0) and uncovered pixels.

### Suggested direction (a suggestion, untested in Mesa)

Choose the axis by the screen-space difference that is actually divided by, and fall back to the 3D `t`, as the comment on lines 187-190 intends, when no axis gives a finite weight:

```c
      for (int k = 0; k < 2; k++) {
         float in_coord = in->clip_pos[k] / in->clip_pos[3];
         float out_coord = out->clip_pos[k] / out->clip_pos[3];
         if (in_coord != out_coord) {
            float dst_coord = dst->clip_pos[k] / dst->clip_pos[3];
            float w = (dst_coord - out_coord) / (in_coord - out_coord);
            if (isfinite(w)) {
               t_nopersp = w;
               break;
            }
         }
      }
```

In the float32 replay (`replay_interp.py --suggested-fix`), this gives every emitted vertex of cases A and B the value 1.0. Case A's NaN vertex lies at w = 0, at infinity in screen space, so no screen-space weight exists there; the fallback only keeps it finite. The vertices later interpolated from it are not shown to get exact screen-space values for an attribute that varies, which is the wider problem of #190.

### Related

- [#190](https://gitlab.freedesktop.org/mesa/mesa/-/work_items/190) (bug 98851): triangle clipping causes wrong interpolation of non-perspective corrected attributes. Same `t_nopersp` code, wrong finite values; open.
- [!12355](https://gitlab.freedesktop.org/mesa/mesa/-/merge_requests/12355): draw: improve numerical stability in clipper (merged).
- [#16681](https://gitlab.freedesktop.org/mesa/mesa/-/work_items/16681): lavapipe rasterizes a triangle that crosses the viewport as separate fan triangles.

No existing report of this NaN was found.
