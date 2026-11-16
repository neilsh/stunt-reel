"""Replay Mesa's gallium draw clipper in float32 on the repro's triangles.

Mirrors `do_clip_tri`, `getclipdist` and `interp()` in
`src/gallium/auxiliary/draw/draw_pipe_clip.c`, with llvmpipe's state: no guard
band (`lp_context.c`: `draw_set_driver_clipping(llvmpipe->draw, false, false,
false, true)`), planes in `draw_context.c` order, and the half-z near plane
`(0, 0, 1, 0)` that `draw_pt_post_vs.c` installs for `clip_halfz`. Each vertex
carries one `noperspective` and one perspective attribute, both 1.0. Prints
every new vertex the clipper makes, with `t_nopersp`'s numerator and divisor,
and the polygon `emit_poly()` fans from its first vertex.

The lines it mirrors, the same text and line numbers at tag `mesa-25.2.8` and
on `main` (whose last change to the file, `8a1a4103` of 2025-07-23, touched only
a swap in `do_clip_tri`):

    98   #define LINTERP(T, OUT, IN) ((OUT) + (T) * ((IN) - (OUT)))
    ...
    192  if (clip->num_linear_attribs) {
    193     float t_nopersp = t;
    194     /* find either in.x != out.x or in.y != out.y */
    195     for (int k = 0; k < 2; k++) {
    196        if (in->clip_pos[k] != out->clip_pos[k]) {
    197           /* do divide by W, then compute linear interpolation factor */
    198           float in_coord = in->clip_pos[k] / in->clip_pos[3];
    199           float out_coord = out->clip_pos[k] / out->clip_pos[3];
    200           float dst_coord = dst->clip_pos[k] / dst->clip_pos[3];
    201           t_nopersp = (dst_coord - out_coord) / (in_coord - out_coord);
    202           break;
    203        }
    204     }
    205     for (unsigned j = 0; j < clip->num_linear_attribs; j++) {
    206        const unsigned attr = clip->linear_attribs[j];
    207        interp_attr(dst->data[attr], t_nopersp, in->data[attr], out->data[attr]);

`--suggested-fix` replays a variant of lines 195-204 that picks the axis by
screen-space difference and falls back to the 3D `t` when no axis gives a
finite weight; it is a sketch, not tested in Mesa.

Run: python replay_interp.py [--suggested-fix]
"""

from __future__ import annotations

import sys

import numpy as np

F = np.float32

# draw_context.c: plane[0..5]; plane[4] is (0, 0, 1, 0) under clip_halfz.
PLANES = [
    ("x <= w", (F(-1), F(0), F(0), F(1))),
    ("x >= -w", (F(1), F(0), F(0), F(1))),
    ("y <= w", (F(0), F(-1), F(0), F(1))),
    ("y >= -w", (F(0), F(1), F(0), F(1))),
    ("z >= 0", (F(0), F(0), F(1), F(0))),
    ("z <= w", (F(0), F(0), F(-1), F(1))),
]

# The repro's cases, in the vertex order the program draws them.
CASES = {
    "A: side-plane edge cut at w = 0": [
        (-0.5, -0.5, 0.75, 1.0),
        (3.5, -0.5, 1.75, 2.0),
        (-2.5, -0.5, -4.25, -4.0),
    ],
    "B: equal screen x, near plane": [
        (1.0, -1.0, -1.0, 2.0),
        (2.0, 3.0, 1.0, 4.0),
        (-3.0, 3.0, 1.0, 4.0),
    ],
    "control: near plane only, finite": [
        (0.0, -1.0, -1.0, 2.0),
        (2.0, 3.0, 1.0, 4.0),
        (-3.0, 3.0, 1.0, 4.0),
    ],
}


class Vert:
    def __init__(self, pos, nopersp, persp, name):
        self.pos = np.array(pos, dtype=F)
        self.nopersp = F(nopersp)
        self.persp = F(persp)
        self.name = name


def dot4(a, b):
    # draw_pipe_clip.c dot4(): a[0]*b[0] + a[1]*b[1] + a[2]*b[2] + a[3]*b[3]
    return F(F(F(a[0] * b[0]) + F(a[1] * b[1])) + F(a[2] * b[2])) + F(a[3] * b[3])


def clipmask(p):
    # draw_llvm.c generate_clipmask(), clip_xy and clip_halfz.
    x, y, z, w = p
    bits = [x > w, -w > x, y > w, -w > y, F(0) > z, z > w]
    return sum(1 << i for i, b in enumerate(bits) if b)


def linterp(t, out, inn):
    # draw_pipe_clip.c:98 LINTERP(T, OUT, IN) = OUT + T * (IN - OUT)
    return F(out + F(t * F(inn - out)))


SUGGESTED_FIX = "--suggested-fix" in sys.argv


def interp(t, out, inn, name):
    """draw_pipe_clip.c interp(): new vertex between `out` and `in`."""
    pos = np.array([linterp(t, out.pos[k], inn.pos[k]) for k in range(4)], dtype=F)
    persp = linterp(t, out.persp, inn.persp)
    t_nopersp = F(t)
    num = den = None
    for k in range(2):
        if SUGGESTED_FIX:
            in_c = F(inn.pos[k] / inn.pos[3])
            out_c = F(out.pos[k] / out.pos[3])
            if in_c != out_c:
                dst_c = F(pos[k] / pos[3])
                weight = F(F(dst_c - out_c) / F(in_c - out_c))
                if np.isfinite(weight):
                    num, den = F(dst_c - out_c), F(in_c - out_c)
                    t_nopersp = weight
                    axis = "xy"[k]
                    break
        elif inn.pos[k] != out.pos[k]:
            in_c = F(inn.pos[k] / inn.pos[3])
            out_c = F(out.pos[k] / out.pos[3])
            dst_c = F(pos[k] / pos[3])
            num, den = F(dst_c - out_c), F(in_c - out_c)
            t_nopersp = F(num / den)
            axis = "xy"[k]
            break
    nopersp = linterp(t_nopersp, out.nopersp, inn.nopersp)
    v = Vert(pos, nopersp, persp, name)
    detail = f"axis {axis}: ({num!r}) / ({den!r})" if num is not None else "3D t"
    print(
        f"    new {name} = lerp({out.name} -> {inn.name}, t={t!r}) at {pos.tolist()}; "
        f"t_nopersp = {detail} = {t_nopersp!r}; noperspective {nopersp!r}, perspective {persp!r}"
    )
    return v


def clip_tri(verts):
    mask = clipmask(verts[0].pos) | clipmask(verts[1].pos) | clipmask(verts[2].pos)
    inlist = list(verts)
    counter = 0
    while mask and len(inlist) >= 3:
        plane_idx = (mask & -mask).bit_length() - 1
        mask &= ~(1 << plane_idx)
        pname, plane = PLANES[plane_idx]
        print(f"  plane {plane_idx} ({pname}): in {[v.name for v in inlist]}")
        n = len(inlist)
        ring = inlist + [inlist[0]]
        out = []
        prev = ring[0]
        dp_prev = dot4(prev.pos, plane)
        for i in range(1, n + 1):
            vert = ring[i]
            dp = dot4(vert.pos, plane)
            if dp_prev >= 0:
                out.append(prev)
                different = dp < 0
            else:
                different = not (dp < 0)
            if different:
                counter += 1
                name = f"N{counter}"
                denom = F(dp - dp_prev)
                if dp < 0:  # going out
                    if -dp < dp_prev:
                        nv = interp(F(dp / denom), vert, prev, name)
                    else:
                        nv = interp(F(-dp_prev / denom), prev, vert, name)
                else:  # coming back in
                    if -dp_prev < dp:
                        nv = interp(F(-dp_prev / denom), prev, vert, name)
                    else:
                        nv = interp(F(dp / denom), vert, prev, name)
                out.append(nv)
            prev, dp_prev = vert, dp
        inlist = out
    return inlist


def main():
    np.seterr(all="ignore")
    for title, positions in CASES.items():
        print(f"{title}")
        verts = [Vert(p, 1.0, 1.0, f"v{i}") for i, p in enumerate(positions)]
        for v in verts:
            print(f"  {v.name} {v.pos.tolist()} clipmask {clipmask(v.pos):#04x}")
        poly = clip_tri(verts)
        # emit_poly(): a fan from poly[0], so a NaN at poly[0] reaches every triangle.
        print(f"  emitted fan from {poly[0].name if poly else '-'}:")
        for v in poly:
            sx, sy = v.pos[0] / v.pos[3], v.pos[1] / v.pos[3]
            print(
                f"    {v.name}: screen ({sx!r}, {sy!r}) noperspective {v.nopersp!r} "
                f"perspective {v.persp!r}"
            )
        nan = sum(np.isnan(v.nopersp) for v in poly)
        print(f"  {nan} of {len(poly)} emitted vertices have a NaN noperspective attribute\n")


if __name__ == "__main__":
    main()
