//! Procedural `.SOD` bytecode virtual machine and register file execution.
//!
//! Governed by architectural invariants:
//! - `[I1]` Metric right-handed coordinates (+X right, +Y up, +Z toward viewer, -Z forward)
//! - `[I2]` Flat arena layout compatibility with [`crate::contracts::shape::SodModelIr`]
//! - `[I3]` VGA Mode 13h palette index mapping (0..=255)
//!
//! Reference specs: `# [FMT-SOD-OPCODES]`, `# [FMT-SOD-IFVIS]`, historical `DECODE.C`/`SOD.H`.

use crate::anchor::AnchorPoint;
use crate::contracts::shape::{
    ShapeSprite, SodHeader, SodStop, SodStopReason, VERTEX_FLAG_LINE, VisibilityCondition,
};
use crate::reader::ByteReader;
use crate::sod::SodError;
use crate::sod::light::ShadeLight;
use std::collections::HashMap;

// Standard .SOD Opcodes per historical SOD.H and specification
/// Clear the accumulator vertex to `[0.0, 0.0, 0.0]` (no operands).
pub const OP_CLRV: u16 = 0x0000;
/// Load `regs[reg_off / 12]` into the accumulator vertex (`reg_off: u16`).
pub const OP_GETV: u16 = 0x0009;
/// Identity/header sentinel (`0x000C`); encountered mid-stream it is ignored.
pub const OP_ID: u16 = 0x000C;
/// Store the accumulator vertex into `regs[reg_off / 12]` (`reg_off: u16`).
pub const OP_PUTV: u16 = 0x0012;
/// Interpolate the accumulator halfway toward `regs[reg_off / 12]` (`reg_off: u16`).
pub const OP_INTV: u16 = 0x001B;
/// Add `regs[reg_off / 12]` to the accumulator vertex (`reg_off: u16`).
pub const OP_ADDV: u16 = 0x0024;
/// Subtract `regs[reg_off / 12]` from the accumulator vertex (`reg_off: u16`).
pub const OP_SUBV: u16 = 0x002D;
/// Negate the accumulator vertex component-wise (no operands).
pub const OP_NEGV: u16 = 0x0036;
/// Multiply the accumulator vertex by `2^shift` (`shift: u16`).
pub const OP_SHLV: u16 = 0x003F;
/// Divide the accumulator vertex by `2^shift`, rounding toward negative infinity (`shift: u16`).
pub const OP_SHRV: u16 = 0x0048;
/// `SOD.H`'s `OP_VEC`, which has no `PLAYONE` dispatch slot: this VM consumes three operand
/// words without effect, a width the binary does not give.
pub const OP_VEC: u16 = 0x004B;
/// Procedural primitive generator (`type`, then its operands): cube, ground quad, object
/// bucket, streamer or vertical quad for types 0, 2, 4, 6 and 8.
pub const OP_IPG: u16 = 0x0063;
/// Batch-upload vectors into consecutive registers (`count, reg, count*3 words`), each stored as
/// `(-x, -y, z)`, the frame the `OP_IPG` cube and `OP_TAP` write.
pub const OP_VECTORS: u16 = 0x0075;
/// Perspective-divide a register range into screen space (`start_reg, count`).
pub const OP_PERS: u16 = 0x0099;
/// Move the pen to vertex `regs[reg_off / 12]` without drawing (`reg_off: u16`).
pub const OP_MOVETO: u16 = 0x00A2;
/// Set the active line color palette index (`color: u16`, `0..=255`).
pub const OP_LINECOL: u16 = 0x00B4;
/// Depth-tested line from the pen to `regs[reg_off / 12]` (`reg_off: u16`).
pub const OP_ZLINETO: u16 = 0x00BD;
/// Emit a depth-sorted flat polygon (`count, regs...`).
pub const OP_POLYZ: u16 = 0x00F3;
/// Emit a procedural sphere centered at `regs[center_reg]` with `radius`.
pub const OP_SPHERE: u16 = 0x00FC;
/// A disc (`center_reg, radius, axis_reg`), its normal `regs[center] - regs[axis]`; this VM
/// consumes the three words and draws nothing.
pub const OP_PERFDISK: u16 = 0x010E;
/// Branches (SORT pushes, `GOTO`, `GOSUB`) one walk may take before it is malformed.
const MAX_BRANCHES: usize = 4096;
/// Set the active polygon fill palette index (`color: u16`, `0..=255`).
pub const OP_COLOR: u16 = 0x0129;
/// Batch-upload shading normal vectors (`count, ...triplets`).
pub const OP_SHADES: u16 = 0x0156;
/// Colour a following polygon from a front-facing lighting ramp (`normal, ramp base`).
pub const OP_SHADE1: u16 = 0x0144;
/// Back-facing counterpart of [`OP_SHADE1`] (`normal, ramp base`).
pub const OP_SHADE2: u16 = 0x014D;
/// Back-facing 16-level ramp (`normal, ramp base`).
pub const OP_SHADE216: u16 = 0x02C7;
/// Emit a normal-lit shaded polygon (`count, regs..., normal, shades...`).
pub const OP_GVPOLY: u16 = 0x0168;
/// Conditionally skip the enclosed section based on a visibility code (`cond, size`).
pub const OP_IFVIS: u16 = 0x017A;
/// Reserved BSP branch (`plane, left_off, right_off`); operands are skipped and stream order is kept.
pub const OP_SORT: u16 = 0x018C;
/// End the display list or return from a bytecode subroutine (no operands).
pub const OP_RETURN: u16 = 0x0195;
/// Push the rotation-centre origin (no operands).
pub const OP_PUSHCENTRE: u16 = 0x007E;
/// Pop the rotation-centre origin (no operands).
pub const OP_POPCENTRE: u16 = 0x0087;
/// Add `regs[reg_off / 12]` to the rotation-centre origin (`reg_off: u16`).
pub const OP_MOVECENTRE: u16 = 0x0090;
/// Push the relative orientation matrix (no operands).
pub const OP_PUSHRELMAT: u16 = 0x01E6;
/// Pop the relative orientation matrix (no operands).
pub const OP_POPRELMAT: u16 = 0x01EF;
/// Draw one frame of an image table at a register's projected point (`reg_off, size,
/// selector, count, count * resource ids`); the frame comes from the angle-bank word
/// `selector` names (`PLAYONE` image `0xA9DC`).
pub const OP_ANIMATE: u16 = 0x01F8;
/// Rotate about Y by an animation variable (`var_off: u16`).
pub const OP_ROTY: u16 = 0x01DD;
/// Rotate about X by an animation variable (`var_off: u16`).
pub const OP_ROTX: u16 = 0x02E2;
/// Rotate about Z by an animation variable (`var_off: u16`).
pub const OP_ROTZ: u16 = 0x02EB;
/// Branch when an animation variable is at least a value (`var_off, val, rel`).
pub const OP_BVGT: u16 = 0x02FD;
/// Jump by a signed byte offset from the operand word (`rel_offset: i16`).
pub const OP_GOTO: u16 = 0x019E;
/// Call by a signed byte offset from the operand word; `RETURN` resumes after it.
pub const OP_GOSUB: u16 = 0x01A7;
/// Alias for [`OP_RETURN`]: ends the display list (no operands).
pub const OP_END: u16 = 0x0195;
/// Facing test (`first_flag, count, count * (reg_a, reg_b, reg_c)`): face `i` sets flag
/// `first_flag + i` when `(a - b) x (c - b)` points at the eye (`PLAYONE` `0x9567`).
pub const OP_REJ: u16 = 0x01B9;
/// Copy `count` anchor-table points into consecutive vertex registers
/// (`reg_off, count, count * anchor_byte_offsets`).
pub const OP_TAP: u16 = 0x022E;
/// Sample a 16-level directional lighting ramp (`normal_reg, ramp`); no geometry.
pub const OP_SHADE16: u16 = 0x02B5;
/// Emit a 16-level shaded polygon (`count, regs..., normal, shades...`).
pub const OP_GVPOLY16: u16 = 0x02BE;
/// Draw a single point at `regs[reg_off / 12]` (`reg_off: u16`).
pub const OP_DOT: u16 = 0x02D0;
/// Draw a solid rectangular block (`reg_off, size`).
pub const OP_BLOCK: u16 = 0x02D9;

/// Power-of-2 scaling multiplier table: `sod_scale_table` from the community
/// `SODParse/SOD.H` (Dave Palmowski), 18 entries; `5 / 2^(k-1)` for `k >= 2`.
pub const SOD_SCALE_TABLE: [f32; 18] = [
    10.0,
    5.0,
    5.0 / 2.0,
    5.0 / 4.0,
    5.0 / 8.0,
    5.0 / 16.0,
    5.0 / 32.0,
    5.0 / 64.0,
    5.0 / 128.0,
    5.0 / 256.0,
    5.0 / 512.0,
    5.0 / 1024.0,
    5.0 / 2048.0,
    5.0 / 4096.0,
    5.0 / 8192.0,
    5.0 / 16384.0,
    5.0 / 32768.0,
    5.0 / 65536.0,
];

/// A VM table addressed modulo its length, as `PLAYONE` masks register and shade offsets.
#[derive(Debug)]
struct WrapTable<T, const N: usize>([T; N]);

impl<T: Copy, const N: usize> WrapTable<T, N> {
    #[expect(
        clippy::indexing_slicing,
        clippy::arithmetic_side_effects,
        reason = "`index % N` is always inside the N-entry table, and every instantiation has N > 0"
    )]
    fn get(&self, index: usize) -> T {
        self.0[index % N]
    }

    #[expect(
        clippy::indexing_slicing,
        clippy::arithmetic_side_effects,
        reason = "`index % N` is always inside the N-entry table, and every instantiation has N > 0"
    )]
    fn set(&mut self, index: usize, value: T) {
        self.0[index % N] = value;
    }
}

/// `OP_SHLV` and `OP_SHRV`: applies `shift` to each coordinate of `v` as a 32-bit integer.
#[expect(
    clippy::cast_possible_truncation,
    reason = "the shift works on the integer part: `as` truncates toward zero (OP_INTV can \n              leave a half) and saturates past i32, as the cast it replaces did"
)]
fn shift_vertex(v: [f32; 3], shift: impl Fn(i32) -> i32) -> [f32; 3] {
    v.map(|c| shift(c as i32) as f32)
}

/// Negates a shade word.
#[expect(
    clippy::arithmetic_side_effects,
    reason = "shade words are clamped to +-0x3FFF, so negation cannot overflow"
)]
fn neg_shade(s: i32) -> i32 {
    -s
}

/// The ramp step of a shade word: `(s >> 1 >> 8)`, minus 2 when `base == 0x10`.
#[expect(
    clippy::arithmetic_side_effects,
    reason = "a shade word within +-0x3FFF shifted right 9 is tiny, so subtracting 2 cannot overflow"
)]
fn shade_level(s: i32, base: i32) -> i32 {
    ((s >> 1) >> 8) - if base == 0x10 { 2 } else { 0 }
}

/// The colour index `base + max(0, level)` before clamping.
#[expect(
    clippy::arithmetic_side_effects,
    reason = "`base` is a byte and `level` is a few dozen at most, so the sum cannot overflow"
)]
fn shade_colour(base: i32, level: i32) -> i32 {
    base + level.max(0)
}

/// Computes the metric scale multiplier (meters per integer unit).
#[must_use]
pub fn compute_scale_factor(scale_index: usize) -> f32 {
    let scale_raw = if let Some(&scale) = SOD_SCALE_TABLE.get(scale_index) {
        scale
    } else if let Some(exponent) = scale_index.checked_sub(1) {
        // An index past `i32::MAX` gives the zero scale that any past 128 already does.
        5.0 / 2.0f32.powi(i32::try_from(exponent).unwrap_or(i32::MAX))
    } else {
        10.0
    };
    scale_raw / 10.0
}

/// Intermediate polygonal facet emitted by the bytecode VM before decal resolution and welding.
#[derive(Debug, Clone, PartialEq)]
pub(crate) struct RawPolygon {
    /// Polygon vertex coordinates in metric units `[x, y, z]` per `[I1]`.
    pub vertices: Vec<[f32; 3]>,
    /// VGA Mode 13h palette index `0..=255` per `[I3]`.
    pub palette_index: u8,
    /// Palette index at each vertex of a Gouraud polygon (`GVPOLY`), one per entry of
    /// `vertices`, which the renderer interpolates across it; empty for a flat polygon,
    /// which is drawn at `palette_index` throughout.
    pub vertex_palette: Vec<u8>,
    /// Outward unit surface normal `[nx, ny, nz]`.
    pub normal: [f32; 3],
    /// Bitflags (e.g. `0x01` for coplanar decal `[I5]`).
    pub flags: u8,
    /// Indicates whether this polygon is a coplanar decal.
    pub is_decal: bool,
    /// Visibility condition inherited from `OP_IFVIS` sections.
    pub visibility: VisibilityCondition,
}

/// Approximates an `OP_SPHERE` primitive with an icosahedron (20 triangles).
///
/// `center` and `radius` are in raw register units like polygon vertices; the result is in
/// metres. The vertices sit at 0.92 of the radius so the faces straddle the true sphere.
/// Splitting the faces once makes the world's vertex buffer exceed wgpu's 256 MiB limit on
/// `CTRY.FLM` (its 2,300 trees carry 19 spheres each).
fn sphere_polygons(
    center: [f32; 3],
    radius: f32,
    ground_y_offset: f32,
    scale_factor: f32,
    palette_index: u8,
    visibility: VisibilityCondition,
) -> Vec<RawPolygon> {
    // The golden ratio as its f32 bit pattern (1.6180339887...): `std::f32::consts::GOLDEN_RATIO`
    // is newer than the 1.88 MSRV in Cargo.toml. Spelled as bits rather than the decimal because
    // clippy's `approx_constant` rejects a retyped constant, and the bits pin the exact value.
    const PHI: f32 = f32::from_bits(0x3FCF_1BBD);
    // Clockwise seen from outside, the winding the pipeline keeps (`FrontFace::Cw`), so the
    // near half draws: `PLAYONE` draws the sphere as a screen disc no side culls (`0x9DB5`).
    const FACES: [[usize; 3]; 20] = [
        [0, 5, 11],
        [0, 1, 5],
        [0, 7, 1],
        [0, 10, 7],
        [0, 11, 10],
        [1, 9, 5],
        [5, 4, 11],
        [11, 2, 10],
        [10, 6, 7],
        [7, 8, 1],
        [3, 4, 9],
        [3, 2, 4],
        [3, 6, 2],
        [3, 8, 6],
        [3, 9, 8],
        [4, 5, 9],
        [2, 11, 4],
        [6, 10, 2],
        [8, 7, 6],
        [9, 1, 8],
    ];
    let unit = |v: [f32; 3]| {
        let len = (v[0] * v[0] + v[1] * v[1] + v[2] * v[2]).sqrt();
        [v[0] / len, v[1] / len, v[2] / len]
    };
    let corners: [[f32; 3]; 12] = [
        unit([-1.0, PHI, 0.0]),
        unit([1.0, PHI, 0.0]),
        unit([-1.0, -PHI, 0.0]),
        unit([1.0, -PHI, 0.0]),
        unit([0.0, -1.0, PHI]),
        unit([0.0, 1.0, PHI]),
        unit([0.0, -1.0, -PHI]),
        unit([0.0, 1.0, -PHI]),
        unit([PHI, 0.0, -1.0]),
        unit([PHI, 0.0, 1.0]),
        unit([-PHI, 0.0, -1.0]),
        unit([-PHI, 0.0, 1.0]),
    ];
    let reach = radius * 0.92;
    let metric = |c: [f32; 3]| {
        [
            (center[0] + c[0] * reach) * scale_factor,
            (center[1] + c[1] * reach + ground_y_offset) * scale_factor,
            (center[2] + c[2] * reach) * scale_factor,
        ]
    };
    FACES
        .iter()
        .map(|face| {
            #[expect(
                clippy::indexing_slicing,
                reason = "FACES holds only the corner indices 0..12"
            )]
            let vertices: Vec<[f32; 3]> = face.iter().map(|&i| metric(corners[i])).collect();
            // The faces wind clockwise from outside, so the edge cross product points inward;
            // `normal` is the outward normal, which the shader lights.
            let [nx, ny, nz] = compute_polygon_normal(&vertices);
            RawPolygon {
                vertex_palette: Vec::new(),
                vertices,
                palette_index,
                normal: [-nx, -ny, -nz],
                flags: 0,
                is_decal: false,
                visibility,
            }
        })
        .collect()
}

/// Outline vertices of an `OP_PERFDISK` disc. `PLAYONE` steps an ellipse's row spans
/// (`0xD11D`); 16 vertices is a guess at round enough, not a measured bound.
const DISC_SEGMENTS: usize = 16;

/// Builds an `OP_PERFDISK` disc: `DISC_SEGMENTS` vertices on a circle of `radius` about
/// `centre`, in the plane perpendicular to `normal`, emitted with both windings because
/// `PLAYONE` tests no facing (`0xA040`). `centre`, `normal` and `radius` are raw register
/// units; the result is in metres. A zero `normal` has no plane and yields nothing.
fn disc_polygons(
    centre: [f32; 3],
    normal: [f32; 3],
    radius: f32,
    ground_y_offset: i16,
    scale_factor: f32,
    palette_index: u8,
    visibility: VisibilityCondition,
) -> Vec<RawPolygon> {
    let len = (normal[0] * normal[0] + normal[1] * normal[1] + normal[2] * normal[2]).sqrt();
    if len < 1e-6 || radius <= 0.0 {
        return Vec::new();
    }
    let n = [normal[0] / len, normal[1] / len, normal[2] / len];
    let cross = |a: [f32; 3], b: [f32; 3]| {
        [
            a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0],
        ]
    };
    // Any axis the normal is least aligned with gives a non-degenerate first basis vector.
    let helper = if n[0].abs() <= n[1].abs() && n[0].abs() <= n[2].abs() {
        [1.0, 0.0, 0.0]
    } else if n[1].abs() <= n[2].abs() {
        [0.0, 1.0, 0.0]
    } else {
        [0.0, 0.0, 1.0]
    };
    let u = cross(n, helper);
    let u_len = (u[0] * u[0] + u[1] * u[1] + u[2] * u[2]).sqrt();
    let u = [u[0] / u_len, u[1] / u_len, u[2] / u_len];
    let v = cross(n, u);
    // Counter-clockwise seen from `+n`, so its edge cross product points along `+n`.
    let ccw: Vec<[f32; 3]> = (0..DISC_SEGMENTS)
        .map(|i| {
            let angle = std::f32::consts::TAU * i as f32 / DISC_SEGMENTS as f32;
            let (s, c) = angle.sin_cos();
            metric_point(
                [
                    centre[0] + radius * (c * u[0] + s * v[0]),
                    centre[1] + radius * (c * u[1] + s * v[1]),
                    centre[2] + radius * (c * u[2] + s * v[2]),
                ],
                ground_y_offset,
                scale_factor,
            )
        })
        .collect();
    let mut cw = ccw.clone();
    cw.reverse();
    // The pipeline keeps clockwise faces; `normal` is the side the face looks toward, which
    // is opposite the edge cross product of a clockwise loop.
    [(cw, n), (ccw, [-n[0], -n[1], -n[2]])]
        .into_iter()
        .map(|(vertices, normal)| RawPolygon {
            vertex_palette: Vec::new(),
            vertices,
            palette_index,
            normal,
            flags: 0,
            is_decal: false,
            visibility,
        })
        .collect()
}

/// World-space radius in metres of the octahedron that stands in for a 1-pixel dot.
const DOT_RADIUS_M: f32 = 0.03;

/// Builds the line a `MOVETO`/`ZLINETO` segment or a two-vertex polygon draws, from `a` to `b`
/// in metres: one polygon of the two endpoints flagged [`VERTEX_FLAG_LINE`], which
/// tessellation turns into a quad the renderer draws one pixel wide at any distance
/// (`sod-vm.md` § 8.9). Its zero normal keeps it out of decal matching. `None` when the
/// endpoints coincide.
fn line_polygons(
    a: [f32; 3],
    b: [f32; 3],
    palette_index: u8,
    visibility: VisibilityCondition,
) -> Option<RawPolygon> {
    let d = [b[0] - a[0], b[1] - a[1], b[2] - a[2]];
    if (d[0] * d[0] + d[1] * d[1] + d[2] * d[2]).sqrt() < 1e-6 {
        return None;
    }
    Some(RawPolygon {
        vertex_palette: Vec::new(),
        vertices: vec![a, b],
        palette_index,
        normal: [0.0; 3],
        flags: VERTEX_FLAG_LINE,
        is_decal: false,
        visibility,
    })
}

/// Builds a tiny octahedron (8 triangles) for an `OP_DOT` at metric position `c`.
fn dot_polygons(
    c: [f32; 3],
    palette_index: u8,
    visibility: VisibilityCondition,
) -> Vec<RawPolygon> {
    let r = DOT_RADIUS_M;
    let v = |x: f32, y: f32, z: f32| [c[0] + x * r, c[1] + y * r, c[2] + z * r];
    let top = v(0.0, 1.0, 0.0);
    let bot = v(0.0, -1.0, 0.0);
    let ring = [
        v(1.0, 0.0, 0.0),
        v(0.0, 0.0, 1.0),
        v(-1.0, 0.0, 0.0),
        v(0.0, 0.0, -1.0),
    ];
    let mut out = Vec::with_capacity(8);
    for (&p, &q) in ring.iter().zip(ring.iter().cycle().skip(1)) {
        for tri in [[top, q, p], [bot, p, q]] {
            let verts = tri.to_vec();
            let normal = compute_polygon_normal(&verts);
            out.push(RawPolygon {
                vertex_palette: Vec::new(),
                vertices: verts,
                palette_index,
                normal,
                flags: 0,
                is_decal: false,
                visibility,
            });
        }
    }
    out
}

/// Computes the unit outward surface normal from a polygon vertex loop.
///
/// Attempts edge cross product from first three vertices, falling back to Newell's method.
#[must_use]
pub(crate) fn compute_polygon_normal(vertices: &[[f32; 3]]) -> [f32; 3] {
    // Edge cross product from first three vertices
    let &[v0, v1, v2, ..] = vertices else {
        return [0.0, 1.0, 0.0];
    };

    let e1 = [v1[0] - v0[0], v1[1] - v0[1], v1[2] - v0[2]];
    let e2 = [v2[0] - v0[0], v2[1] - v0[1], v2[2] - v0[2]];

    let c = [
        e1[1] * e2[2] - e1[2] * e2[1],
        e1[2] * e2[0] - e1[0] * e2[2],
        e1[0] * e2[1] - e1[1] * e2[0],
    ];
    let len = (c[0] * c[0] + c[1] * c[1] + c[2] * c[2]).sqrt();

    if len > 1e-12 {
        return [c[0] / len, c[1] / len, c[2] / len];
    }

    // Newell's method fallback for non-planar or collinear initial vertices
    let mut nx = 0.0f32;
    let mut ny = 0.0f32;
    let mut nz = 0.0f32;
    for (curr, nxt) in vertices.iter().zip(vertices.iter().cycle().skip(1)) {
        nx += (curr[1] - nxt[1]) * (curr[2] + nxt[2]);
        ny += (curr[2] - nxt[2]) * (curr[0] + nxt[0]);
        nz += (curr[0] - nxt[0]) * (curr[1] + nxt[1]);
    }

    let newell_len = (nx * nx + ny * ny + nz * nz).sqrt();
    if newell_len > 1e-12 {
        [nx / newell_len, ny / newell_len, nz / newell_len]
    } else {
        [0.0, 1.0, 0.0]
    }
}

/// The gate of an `OP_IFVIS` section: its operand is the byte offset of a facing flag.
///
/// `PLAYONE` (`0x9BCC`) runs the section while `work:0x7C68[flag]` is nonzero, which
/// `OP_REJ` (`0x9567`) sets when its face points at the eye. A flag this shape never set
/// holds whatever an earlier shape left there, so its section is drawn.
fn parse_visibility_condition(
    flag: u16,
    faces: &HashMap<u16, VisibilityCondition>,
) -> VisibilityCondition {
    faces
        .get(&flag)
        .copied()
        .unwrap_or(VisibilityCondition::Always)
}

/// A raw register point (rotation-centre origin included) in `[I1]` metres, converted as a
/// polygon vertex is.
fn metric_point(raw: [f32; 3], ground_y_offset: i16, scale_factor: f32) -> [f32; 3] {
    [
        raw[0] * scale_factor,
        (raw[1] + f32::from(ground_y_offset)) * scale_factor,
        raw[2] * scale_factor,
    ]
}

/// How a VM pass treats an opcode it cannot execute.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum Policy {
    /// Fail the decode.
    Strict,
    /// Stop at the blocking opcode, keeping the geometry decoded so far.
    Lenient,
    /// Step over a blocking opcode whose width is known and log it; stop on one without
    /// a width.
    Census,
}

/// The VM's verdict on one opcode it cannot execute.
enum Blockage {
    /// Fail the decode.
    Fail(SodError),
    /// End the run and report the stop.
    Stop(SodStop),
    /// Log the stop and continue past the opcode's operands.
    StepOver(SodStop),
}

/// The one stop-or-step-over decision, shared by every blocking site.
///
/// `steppable` is true when the site knows how many operand words the opcode owns; only a
/// census run may then continue past it. Strict fails and lenient stops at any blockage.
fn blocked(
    policy: Policy,
    offset: usize,
    opcode: u16,
    reason: SodStopReason,
    steppable: bool,
) -> Blockage {
    let stop = SodStop {
        offset,
        opcode,
        reason,
    };
    match policy {
        Policy::Strict => Blockage::Fail(stop.into_error()),
        Policy::Census if steppable => Blockage::StepOver(stop),
        Policy::Lenient | Policy::Census => Blockage::Stop(stop),
    }
}

/// Everything one VM pass produced.
pub(crate) struct VmRun {
    /// The parsed 10-byte header.
    pub header: SodHeader,
    /// Polygons emitted before the stream ended, in draw order.
    pub polygons: Vec<RawPolygon>,
    /// The first blocking opcode the run stopped on.
    pub stop: Option<SodStop>,
    /// Blocking opcodes a census run stepped over, in stream order.
    pub stepped_over: Vec<SodStop>,
    /// Byte offset of the first `OP_RETURN`; `None` when the stream ended without one.
    pub returned_at: Option<usize>,
    /// Images `OP_ANIMATE` drew before the stream ended, in stream order.
    pub sprites: Vec<ShapeSprite>,
}

/// One instruction a traced VM walk executed.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TraceStep {
    /// Byte offset of the opcode word within the shape.
    pub offset: usize,
    /// The opcode word.
    pub opcode: u16,
    /// The operand words the VM consumed, in stream order.
    pub operands: Vec<u16>,
    /// Where execution continued when the instruction moved it (`GOTO`, `GOSUB`, a taken
    /// `BVGT`, a `RETURN` that resumes); `None` when it fell through.
    pub branch: Option<usize>,
}

impl TraceStep {
    /// The step for the instruction at `offset` whose operands end at `end`.
    fn new(data: &[u8], offset: usize, opcode: u16, end: usize, branch: Option<usize>) -> Self {
        let operands = data
            .get(offset.saturating_add(2)..end)
            .unwrap_or_default()
            .as_chunks::<2>()
            .0
            .iter()
            .map(|&w| u16::from_le_bytes(w))
            .collect();
        Self {
            offset,
            opcode,
            operands,
            branch,
        }
    }
}

/// Runs one pass of the VM.
///
/// The policy decides, at every blocking site, whether to fail, stop or step over;
/// header parsing, register arithmetic and geometry emission are shared by every mode.
/// With `trace`, every instruction the walk executes or steps over is appended to it, the
/// steps before an error included.
#[expect(
    clippy::expect_used,
    reason = "a steppable opcode always has a census width"
)]
pub(crate) fn run_vm(
    data: &[u8],
    policy: Policy,
    anchors: Option<&[AnchorPoint]>,
    light: ShadeLight,
    mut trace: Option<&mut Vec<TraceStep>>,
) -> Result<VmRun, SodError> {
    let light = light.0.map(i64::from);
    if data.len() < 10 {
        return Err(SodError::UnexpectedEof {
            expected: 10,
            actual: data.len(),
        });
    }

    let mut r = ByteReader::new(data);
    let op_id = r.read_u16_le()?;
    if op_id != OP_ID {
        return Err(SodError::InvalidMagic {
            expected: OP_ID,
            actual: op_id,
        });
    }

    let bounding_size = r.read_u16_le()?;
    let ground_y_offset = r.read_i16_le()?;
    let flags_scale = r.read_u16_le()?;
    let collision_meta = r.read_u16_le()?;

    let scale_index = (flags_scale & 0xFF) as u8;
    let header_flags = (flags_scale >> 8) as u8;
    let scale_factor = compute_scale_factor(scale_index as usize);

    let header = SodHeader {
        bounding_size,
        ground_y_offset,
        scale_index,
        header_flags,
        scale_factor,
        collision_meta,
    };

    // 1024 3D vector registers per specification
    let mut regs = WrapTable([[0.0f32; 3]; 1024]);
    let mut cur_vert = [0.0f32; 3];
    let mut cur_color = 0u8;
    // Per-normal shade words (`PLAYONE` `work:0x7468`), indexed by byte offset / 2.
    let mut shade_words = WrapTable([0i32; 2048]);
    // Line colour (`OP_LINECOL`); falls back to the fill colour until first set.
    let mut line_color: Option<u8> = None;
    // Pen position in metres for `OP_MOVETO` / `OP_ZLINETO`.
    let mut pen = [0.0f32; 3];
    let mut polygons = Vec::new();
    let mut stepped_over: Vec<SodStop> = Vec::new();
    let mut returned_at: Option<usize> = None;
    let mut sprites: Vec<ShapeSprite> = Vec::new();
    let mut current_visibility = VisibilityCondition::Always;
    let mut visibility_scope_end = 0usize;
    // Facing flags (`PLAYONE` `work:0x7C68`) that `OP_REJ` writes and `OP_IFVIS` tests,
    // keyed by flag byte offset, each kept as the gate it opens.
    let mut faces: HashMap<u16, VisibilityCondition> = HashMap::new();
    // Where each pending `RETURN` resumes, with the `IFVIS` scope to restore there: a SORT
    // pushes its second branch and its continuation, a GOSUB the instruction after it.
    let mut branch_resume: Vec<(usize, VisibilityCondition, usize)> = Vec::new();
    // Rotation-centre origin (raw units) added to every emitted vertex, and its stack.
    let mut relpos = [0.0f32; 3];
    let mut centre_stack: Vec<[f32; 3]> = Vec::new();
    // Branches taken (SORT pushes, GOTO, GOSUB); every target lies ahead except a GOTO or
    // GOSUB's, so this budget is what ends a malformed loop.
    let mut subs_run = 0usize;

    let total_len = data.len();

    while r.pos() < total_len {
        if r.pos() >= visibility_scope_end && current_visibility != VisibilityCondition::Always {
            current_visibility = VisibilityCondition::Always;
        }

        let opcode_end = r.pos().checked_add(2).ok_or(SodError::UnexpectedEof {
            expected: usize::MAX,
            actual: total_len,
        })?;
        if opcode_end > total_len {
            return Err(SodError::UnexpectedEof {
                expected: opcode_end,
                actual: total_len,
            });
        }

        let op_offset = r.pos();
        let opcode = r.read_u16_le()?;
        // Set by a branch that leaves the stream or spends the budget, or by a polygon with
        // fewer than two vertices: strict fails, lenient and census keep the geometry so far
        // and report the stop.
        let mut malformed: Option<SodStopReason> = None;
        // Where a branch sends the walk, applied once the instruction is traced.
        let mut jump: Option<usize> = None;
        // Set by the instruction that ends the walk.
        let mut halt = false;

        match opcode {
            OP_CLRV => {
                cur_vert = [0.0, 0.0, 0.0];
            }
            OP_GETV => {
                let reg_off = r.read_u16_le()?;
                let reg_idx = ((reg_off / 12) & 1023) as usize;
                cur_vert = regs.get(reg_idx);
            }
            OP_PUTV => {
                let reg_off = r.read_u16_le()?;
                let reg_idx = ((reg_off / 12) & 1023) as usize;
                regs.set(reg_idx, cur_vert);
            }
            OP_INTV => {
                let reg_off = r.read_u16_le()?;
                let reg_idx = ((reg_off / 12) & 1023) as usize;
                let target = regs.get(reg_idx);
                cur_vert = [
                    f32::midpoint(cur_vert[0], target[0]),
                    f32::midpoint(cur_vert[1], target[1]),
                    f32::midpoint(cur_vert[2], target[2]),
                ];
            }
            OP_ADDV => {
                let reg_off = r.read_u16_le()?;
                let reg_idx = ((reg_off / 12) & 1023) as usize;
                let target = regs.get(reg_idx);
                cur_vert = [
                    cur_vert[0] + target[0],
                    cur_vert[1] + target[1],
                    cur_vert[2] + target[2],
                ];
            }
            OP_SUBV => {
                let reg_off = r.read_u16_le()?;
                let reg_idx = ((reg_off / 12) & 1023) as usize;
                let target = regs.get(reg_idx);
                cur_vert = [
                    cur_vert[0] - target[0],
                    cur_vert[1] - target[1],
                    cur_vert[2] - target[2],
                ];
            }
            OP_NEGV => {
                cur_vert = [-cur_vert[0], -cur_vert[1], -cur_vert[2]];
            }
            OP_SHLV => {
                let shift = r.read_u16_le()?;
                let s = u32::from(shift) & 31;
                cur_vert = shift_vertex(cur_vert, |c| c.wrapping_shl(s));
            }
            OP_SHRV => {
                let shift = r.read_u16_le()?;
                let s = u32::from(shift) & 31;
                cur_vert = shift_vertex(cur_vert, |c| c.wrapping_shr(s));
            }
            OP_IPG => {
                let ipg_type = r.read_u16_le()?;
                match ipg_type {
                    0 => {
                        // Cube
                        let dx = f32::from(r.read_i16_le()?);
                        let dy = f32::from(r.read_i16_le()?);
                        let dz = f32::from(r.read_i16_le()?);
                        let start_off = r.read_u16_le()?;
                        let start_reg = ((start_off / 12) & 1023) as usize;

                        regs.set((start_reg) & 1023, [-dx, -dy, -dz]);
                        regs.set((start_reg + 1) & 1023, [-dx, -dy, dz]);
                        regs.set((start_reg + 2) & 1023, [dx, -dy, dz]);
                        regs.set((start_reg + 3) & 1023, [dx, -dy, -dz]);
                        regs.set((start_reg + 4) & 1023, [-dx, dy, -dz]);
                        regs.set((start_reg + 5) & 1023, [-dx, dy, dz]);
                        regs.set((start_reg + 6) & 1023, [dx, dy, dz]);
                        regs.set((start_reg + 7) & 1023, [dx, dy, -dz]);
                    }
                    2 => {
                        // Ground quad: `0xB41E` stores raw `(+dx, 0, -dz)`, `(+dx, 0, +dz)`,
                        // `(-dx, 0, +dz)`, `(-dx, 0, -dz)`, turned half a turn about z.
                        let dx = f32::from(r.read_i16_le()?);
                        let dz = f32::from(r.read_i16_le()?);
                        let start_off = r.read_u16_le()?;
                        let start_reg = ((start_off / 12) & 1023) as usize;

                        regs.set((start_reg) & 1023, [-dx, 0.0, -dz]);
                        regs.set((start_reg + 1) & 1023, [-dx, 0.0, dz]);
                        regs.set((start_reg + 2) & 1023, [dx, 0.0, dz]);
                        regs.set((start_reg + 3) & 1023, [dx, 0.0, -dz]);
                    }
                    8 => {
                        // Vertical quad: `0xB4B5` stores raw `(+dx, +dy, 0)`, `(-dx, +dy, 0)`,
                        // `(-dx, -dy, 0)`, `(+dx, -dy, 0)`, turned half a turn about z.
                        let dx = f32::from(r.read_i16_le()?);
                        let dy = f32::from(r.read_i16_le()?);
                        let start_off = r.read_u16_le()?;
                        let start_reg = ((start_off / 12) & 1023) as usize;

                        regs.set((start_reg) & 1023, [-dx, -dy, 0.0]);
                        regs.set((start_reg + 1) & 1023, [dx, -dy, 0.0]);
                        regs.set((start_reg + 2) & 1023, [dx, dy, 0.0]);
                        regs.set((start_reg + 3) & 1023, [-dx, dy, 0.0]);
                    }
                    4 => {
                        // Object bucket (`0xB54C`): one word, the offset of a pending-object
                        // list at `DGROUP:0x2346` drawn through `0x1B75`; no register written.
                        // Skipping two words swallowed the following `RETURN` and
                        // exposed that return word as a bogus opcode (`0x0002`).
                        r.read_u16_le()?;
                    }
                    6 => {
                        // Streamer (`0xB58D`): no stream operand. It writes registers 4..=10
                        // from the tick and leftover CPU registers, which are not modelled.
                    }
                    _ => {
                        // Unrecognized IPG type arguments skipped safely
                        r.read_u16_le()?;
                        r.read_u16_le()?;
                    }
                }
            }
            OP_VECTORS => {
                let count = r.read_u16_le()?;
                let start_off = r.read_u16_le()?;
                let start_reg = ((start_off / 12) & 1023) as usize;

                for i in 0..count {
                    let vx = f32::from(r.read_i16_le()?);
                    let vy = f32::from(r.read_i16_le()?);
                    let vz = f32::from(r.read_i16_le()?);
                    // Turned half a turn about z, as the `OP_IPG` cube and `TAP` are: `PLAYONE`
                    // stores both loaders in one raw frame (`0x9C51`, `0xB275`).
                    // Register numbers wrap modulo 1024, as `PLAYONE` masks them.
                    regs.set(start_reg.wrapping_add(i as usize) & 1023, [-vx, -vy, vz]);
                }
            }
            OP_COLOR => {
                cur_color = (r.read_u16_le()? & 0xFF) as u8;
            }
            OP_LINECOL => {
                // [Hypothesis] one word: line colour index, as OP_COLOR is for fills.
                line_color = Some((r.read_u16_le()? & 0xFF) as u8);
            }
            OP_MOVETO | OP_ZLINETO | OP_DOT => {
                // [Hypothesis] one word: register byte offset (`/12` = register).
                let reg_off = r.read_u16_le()?;
                let raw_v = add3(regs.get(((reg_off / 12) & 1023) as usize), relpos);
                let p = [
                    raw_v[0] * scale_factor,
                    (raw_v[1] + f32::from(ground_y_offset)) * scale_factor,
                    raw_v[2] * scale_factor,
                ];
                let color = line_color.unwrap_or(cur_color);
                match opcode {
                    OP_ZLINETO => {
                        polygons.extend(line_polygons(pen, p, color, current_visibility));
                        pen = p;
                    }
                    OP_DOT => polygons.extend(dot_polygons(p, color, current_visibility)),
                    _ => pen = p,
                }
            }
            OP_POLYZ => {
                let count = r.read_u16_le()?;
                if count < 2 {
                    if policy == Policy::Strict {
                        return Err(SodError::MalformedPolygon {
                            reason: format!(
                                "OP_POLYZ with count {count} < 2 at offset 0x{op_offset:04X}"
                            ),
                        });
                    }
                    malformed = Some(SodStopReason::MalformedPolygon);
                } else {
                    let mut poly_verts = Vec::with_capacity(count as usize);
                    for _ in 0..count {
                        let reg_off = r.read_u16_le()?;
                        let reg_idx = ((reg_off / 12) & 1023) as usize;
                        let raw_v = add3(regs.get(reg_idx), relpos);

                        // Convert to metric coordinates per Invariant [I1]
                        let mx = raw_v[0] * scale_factor;
                        let my = (raw_v[1] + f32::from(ground_y_offset)) * scale_factor;
                        let mz = raw_v[2] * scale_factor;
                        poly_verts.push([mx, my, mz]);
                    }

                    if let [a, b] = poly_verts[..] {
                        // PLAYONE draws two vertices as a thin line, not an error (`sod-vm.md` § 8.9).
                        polygons.extend(line_polygons(a, b, cur_color, current_visibility));
                    } else {
                        let norm = compute_polygon_normal(&poly_verts);
                        polygons.push(RawPolygon {
                            vertex_palette: Vec::new(),
                            vertices: poly_verts,
                            palette_index: cur_color,
                            normal: norm,
                            flags: 0,
                            is_decal: false,
                            visibility: current_visibility,
                        });
                    }
                }
            }
            OP_GVPOLY | OP_GVPOLY16 => {
                let count = r.read_u16_le()?;
                if count < 2 {
                    if policy == Policy::Strict {
                        return Err(SodError::MalformedPolygon {
                            reason: format!(
                                "GVPOLY with count {count} < 2 at offset 0x{op_offset:04X}"
                            ),
                        });
                    }
                    malformed = Some(SodStopReason::MalformedPolygon);
                } else {
                    let mut reg_indices = Vec::with_capacity(count as usize);
                    for _ in 0..count {
                        let reg_off = r.read_u16_le()?;
                        reg_indices.push(((reg_off / 12) & 1023) as usize);
                    }

                    // The word after the register list is `(ramp_base << 8) | count` (`0x1004`
                    // is a four-vertex polygon on the red ramp), not a normal register; one
                    // shade offset per vertex follows, each a byte offset into the `SHADES` words.
                    let ramp = r.read_u16_le()?;
                    let mut vertex_shades = Vec::with_capacity(count as usize);
                    for _ in 0..count {
                        vertex_shades.push(usize::from(r.read_u16_le()?));
                    }

                    let mut poly_verts = Vec::with_capacity(count as usize);
                    for &r_idx in &reg_indices {
                        let raw_v = add3(regs.get(r_idx), relpos);
                        let mx = raw_v[0] * scale_factor;
                        let my = (raw_v[1] + f32::from(ground_y_offset)) * scale_factor;
                        let mz = raw_v[2] * scale_factor;
                        poly_verts.push([mx, my, mz]);
                    }

                    // Each vertex gets its own ramp index, which the renderer interpolates in
                    // screen space as the filler `0x75DB` does (`research/playone-exe/
                    // terrain-shade.md` sections 5-6); the vertex fraction is dropped. The mean
                    // level is the polygon's own index, which decal detection compares.
                    let base = i32::from((ramp >> 8) as u8);
                    let sixteen = opcode == OP_GVPOLY16;
                    let levels: Vec<i32> = vertex_shades
                        .iter()
                        .map(|&off| {
                            let mut s = shade_words.get((off / 2) & 2047);
                            if sixteen {
                                s >>= 1;
                            }
                            shade_level(s, base)
                        })
                        .collect();
                    let level_sum: i32 = levels.iter().sum();
                    let level = level_sum
                        .checked_div(i32::try_from(vertex_shades.len()).unwrap_or(1))
                        .unwrap_or(0);
                    #[expect(clippy::cast_sign_loss, reason = "clamped to the palette's 0..=255")]
                    let palette_index = shade_colour(base, level).clamp(0, 255) as u8;

                    #[expect(clippy::cast_sign_loss, reason = "clamped to the palette's 0..=255")]
                    let vertex_palette: Vec<u8> = levels
                        .iter()
                        .map(|&l| shade_colour(base, l).clamp(0, 255) as u8)
                        .collect();
                    if let [a, b] = poly_verts[..] {
                        // Two vertices are a thin line in PLAYONE (`0x75DB` spans are inclusive);
                        // one colour, the mean level, stands for its shade.
                        polygons.extend(line_polygons(a, b, palette_index, current_visibility));
                    } else {
                        polygons.push(RawPolygon {
                            vertex_palette,
                            normal: compute_polygon_normal(&poly_verts),
                            vertices: poly_verts,
                            palette_index,
                            flags: 0,
                            is_decal: false,
                            visibility: current_visibility,
                        });
                    }
                }
            }
            OP_IFVIS => {
                let cond_code = r.read_u16_le()?;
                let sec_len = r.read_u16_le()? as usize;
                if let Some(scope_end) =
                    r.pos().checked_add(sec_len).filter(|&end| end <= total_len)
                {
                    current_visibility = parse_visibility_condition(cond_code, &faces);
                    visibility_scope_end = scope_end;
                } else {
                    // Clamped beyond EOF
                    halt = true;
                }
            }
            OP_SORT => {
                // `siobj.cpp` `case 0x18c`: the three words are byte offsets from the
                // opcode; the branch after the operands runs first, the second branch is at
                // `op + 4 + second`, and the stream continues at `op + 2 + first`. Targets
                // must lie ahead; a SORT re-entered through a loop spends the branch budget.
                let first = usize::from(r.read_u16_le()?);
                let second = usize::from(r.read_u16_le()?);
                r.read_u16_le()?;
                let target = |skip: usize, delta: usize| {
                    op_offset
                        .checked_add(skip)
                        .and_then(|p| p.checked_add(delta))
                        .filter(|&at| at > r.pos() && at < total_len)
                };
                if let (Some(second_at), Some(after_at)) = (target(4, second), target(2, first)) {
                    // A counter: the branch below stops the stream once it passes MAX_BRANCHES.
                    subs_run = subs_run.saturating_add(1);
                    if subs_run > MAX_BRANCHES {
                        malformed = Some(SodStopReason::MalformedBranch);
                    } else {
                        let scope = (current_visibility, visibility_scope_end);
                        branch_resume.push((after_at, scope.0, scope.1));
                        branch_resume.push((second_at, scope.0, scope.1));
                    }
                }
            }
            OP_PUSHCENTRE => centre_stack.push(relpos),
            OP_POPCENTRE => {
                if let Some(c) = centre_stack.pop() {
                    relpos = c;
                }
            }
            OP_MOVECENTRE => {
                let reg_off = r.read_u16_le()?;
                relpos = add3(relpos, regs.get(((reg_off / 12) & 1023) as usize));
            }
            OP_GOTO | OP_GOSUB => {
                // Target = address of the operand word + signed byte offset (`siobj.cpp`).
                let operand_at = r.pos();
                let rel = r.read_i16_le()?;
                let target = operand_at
                    .checked_add_signed(isize::from(rel))
                    .filter(|target| (10..total_len).contains(target));
                // A counter: the branch below stops the stream once it passes MAX_BRANCHES.
                subs_run = subs_run.saturating_add(1);
                if let Some(target) = target
                    && subs_run <= MAX_BRANCHES
                {
                    if opcode == OP_GOSUB {
                        branch_resume.push((r.pos(), current_visibility, visibility_scope_end));
                    }
                    jump = Some(target);
                } else {
                    malformed = Some(SodStopReason::MalformedBranch);
                }
            }
            OP_ID | OP_PUSHRELMAT | OP_POPRELMAT => {
                // `OP_ID`: secondary ID sentinel in stream; safely ignored.
                // `OP_PUSHRELMAT` and `OP_POPRELMAT`: the relative matrix stays the identity: its only users here are `ROT*`,
                // and the animation variables they read are zero in a resting pose.
            }
            OP_ROTX | OP_ROTY | OP_ROTZ => {
                // Operand is an animation-variable byte offset; variable 0 is a zero angle.
                r.read_u16_le()?;
            }
            OP_BVGT => {
                // `variable >= val` branches by `rel` bytes from the third operand word
                // (si-tools); the animation variable reads zero, so only `val == 0` takes it.
                let _var = r.read_u16_le()?;
                let val = r.read_u16_le()?;
                let operand_at = r.pos();
                let rel = r.read_u16_le()?;
                let taken = val == 0;
                if taken {
                    match operand_at
                        .checked_add(usize::from(rel))
                        .filter(|&target| target < total_len)
                    {
                        Some(target) => jump = Some(target),
                        None => malformed = Some(SodStopReason::MalformedBranch),
                    }
                }
            }
            OP_PERFDISK => {
                // `0xA040`: a filled disc of `radius` about `regs[centre]`, its plane
                // perpendicular to `regs[centre] - regs[axis]`, drawn from both sides.
                let centre_off = r.read_u16_le()?;
                let radius = f32::from(r.read_u16_le()?);
                let axis_off = r.read_u16_le()?;
                let centre_reg = regs.get(((centre_off / 12) & 1023) as usize);
                let axis_reg = regs.get(((axis_off / 12) & 1023) as usize);
                polygons.extend(disc_polygons(
                    add3(centre_reg, relpos),
                    [
                        centre_reg[0] - axis_reg[0],
                        centre_reg[1] - axis_reg[1],
                        centre_reg[2] - axis_reg[2],
                    ],
                    radius,
                    ground_y_offset,
                    scale_factor,
                    cur_color,
                    current_visibility,
                ));
            }
            OP_VEC => {
                r.read_u16_le()?;
                r.read_u16_le()?;
                r.read_u16_le()?;
            }
            OP_ANIMATE => {
                // `0xA9DC`: a square `(size * work:0x8070 >> 8) / depth` pixels across, the
                // screen radius `OP_SPHERE` gives a sphere of radius `size`, centred on the
                // register's projected point. Frame `(count * bank word) >> 16` of the id
                // table, the word at `work:0x810E + selector`; skipped in the shadow pass.
                let reg_off = r.read_u16_le()?;
                let size = f32::from(r.read_u16_le()?);
                let selector = r.read_u16_le()?;
                let count = r.read_u16_le()?;
                if policy == Policy::Census {
                    // The census keeps no sprite: read past the table without holding it, so a
                    // looping stream cannot pile up tables.
                    for _ in 0..count {
                        r.read_u16_le()?;
                    }
                } else {
                    let frames = std::iter::repeat_with(|| r.read_u16_le())
                        .take(usize::from(count))
                        .collect::<Result<Vec<_>, _>>()?;
                    let anchor = add3(regs.get(((reg_off / 12) & 1023) as usize), relpos);
                    sprites.push(ShapeSprite {
                        anchor: metric_point(anchor, ground_y_offset, scale_factor),
                        size: size * scale_factor,
                        selector,
                        frames,
                        visibility: current_visibility,
                    });
                }
            }
            OP_SPHERE => {
                let center_off = r.read_u16_le()?;
                let radius = f32::from(r.read_u16_le()?);
                let center = add3(regs.get(((center_off / 12) & 1023) as usize), relpos);
                polygons.extend(sphere_polygons(
                    center,
                    radius,
                    f32::from(ground_y_offset),
                    scale_factor,
                    cur_color,
                    current_visibility,
                ));
            }
            OP_BLOCK | OP_PERS => {
                r.read_u16_le()?;
                r.read_u16_le()?;
            }
            OP_REJ => {
                // `0x9567` (normal by `0xB621`): flag = sign of ((a - b) x (c - b)) . (b - eye),
                // set while negative. The eye is known only per frame, so the face is kept as
                // the gate the renderer evaluates.
                let first = r.read_u16_le()?;
                let num_faces = r.read_u16_le()?;
                for i in 0..num_faces {
                    let mut corner = || -> Result<[f32; 3], SodError> {
                        let reg_idx = ((r.read_u16_le()? / 12) & 1023) as usize;
                        Ok(metric_point(
                            add3(regs.get(reg_idx), relpos),
                            ground_y_offset,
                            scale_factor,
                        ))
                    };
                    let (a, b, c) = (corner()?, corner()?, corner()?);
                    let u = [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
                    let v = [c[0] - b[0], c[1] - b[1], c[2] - b[2]];
                    let normal = [
                        u[1] * v[2] - u[2] * v[1],
                        u[2] * v[0] - u[0] * v[2],
                        u[0] * v[1] - u[1] * v[0],
                    ];
                    faces.insert(
                        first.wrapping_add(i),
                        VisibilityCondition::FacesEye { point: b, normal },
                    );
                }
            }
            OP_TAP => {
                let reg_off = r.read_u16_le()? as usize;
                let count = r.read_u16_le()? as usize;

                if !reg_off.is_multiple_of(12) {
                    return Err(SodError::MalformedOpcode {
                        opcode,
                        offset: op_offset,
                        reason: format!("TAP register offset {reg_off} is not a multiple of 12"),
                    });
                }
                if count == 0 || count > 64 {
                    return Err(SodError::MalformedOpcode {
                        opcode,
                        offset: op_offset,
                        reason: format!("TAP point count {count} is outside 1..=64"),
                    });
                }

                let table = match anchors {
                    Some(points) if !points.is_empty() => Some(points),
                    _ => match blocked(
                        policy,
                        op_offset,
                        opcode,
                        SodStopReason::MissingAnchors,
                        true,
                    ) {
                        Blockage::Fail(error) => return Err(error),
                        Blockage::Stop(stop) => {
                            return Ok(VmRun {
                                header,
                                polygons,
                                stop: Some(stop),
                                stepped_over,
                                returned_at,
                                sprites,
                            });
                        }
                        Blockage::StepOver(stop) => {
                            // The point count is in the operand, so the walk can skip it.
                            for _ in 0..count {
                                r.read_u16_le()?;
                            }
                            stepped_over.push(stop);
                            None
                        }
                    },
                };

                if let Some(table) = table {
                    // Anchors are metres; a scale index past the table has no shape unit for
                    // them, so every point would collapse onto the lift.
                    if scale_factor <= 0.0 {
                        return Err(SodError::MalformedOpcode {
                            opcode,
                            offset: op_offset,
                            reason: format!(
                                "TAP in a shape whose scale index {scale_index} has no unit"
                            ),
                        });
                    }
                    let units = 1.0 / scale_factor;
                    let start_reg = (reg_off / 12) & 1023;
                    for i in 0..count {
                        let anchor_off = r.read_u16_le()? as usize;
                        if !anchor_off.is_multiple_of(28) {
                            return Err(SodError::MalformedOpcode {
                                opcode,
                                offset: op_offset,
                                reason: format!(
                                    "TAP anchor offset 0x{anchor_off:04X} is not a multiple of 28"
                                ),
                            });
                        }

                        let Some(anchor) = table.get(anchor_off / 28) else {
                            // Mid-operand, so there is no width to step over: every policy ends
                            // the run here (strict fails, lenient and census report a stop).
                            match blocked(
                                policy,
                                op_offset,
                                opcode,
                                SodStopReason::MissingAnchors,
                                false,
                            ) {
                                Blockage::Fail(error) => return Err(error),
                                Blockage::Stop(stop) | Blockage::StepOver(stop) => {
                                    return Ok(VmRun {
                                        header,
                                        polygons,
                                        stop: Some(stop),
                                        stepped_over,
                                        returned_at,
                                        sprites,
                                    });
                                }
                            }
                        };

                        // `PLAYONE` (image `0xAD88`) loads the anchor's view-space position less
                        // the object's lifted origin, in the shape's units. For an unrotated shape
                        // at the island origin that is the anchor in shape units less the lift;
                        // `world/mod.rs` shifts the table by the placement.
                        let [x, y, z] = anchor.register_position();
                        regs.set(
                            start_reg.wrapping_add(i) & 1023, // register numbers wrap modulo 1024
                            [x * units, y * units - f32::from(ground_y_offset), z * units],
                        );
                    }
                }
            }
            OP_SHADES => {
                // `PLAYONE` 0x9481: `s = -clamp((N . L) >> 16, +-0x3FFF)` with `N`, `L` at
                // 1.0 = 32767, both in the shape's raw model frame. `L` is the light the
                // caller handed this object (`ShadeLight`).
                let first = r.read_u16_le()? as usize;
                let count = r.read_u16_le()? as usize;
                for i in 0..count {
                    let n = [
                        i64::from(r.read_i16_le()?),
                        i64::from(r.read_i16_le()?),
                        i64::from(r.read_i16_le()?),
                    ];
                    #[expect(
                        clippy::arithmetic_side_effects,
                        reason = "each n[k] and light[k] is an i16, so the i64 sum cannot overflow"
                    )]
                    let dot = (n[0] * light[0] + n[1] * light[1] + n[2] * light[2]) >> 16;
                    #[expect(clippy::cast_possible_truncation, reason = "clamped to +-0x3FFF")]
                    let shade = dot.clamp(-0x3FFF, 0x3FFF) as i32;
                    // Shade offsets wrap modulo 2048, as `PLAYONE` masks them.
                    shade_words.set((first / 2).wrapping_add(i) & 2047, neg_shade(shade));
                }
            }
            OP_SHADE1 | OP_SHADE2 | OP_SHADE16 | OP_SHADE216 => {
                // `PLAYONE` 0xA526 / 0xA519 / 0xA550 / 0xA55D into the shared tail 0xA52F: the
                // polygon colour is `base + max(0, (s >> 1 [>> 1 for the 16-level forms]) >> 8
                // + adj)`, `adj = -2` when `base == 0x10`; the SHADE2 forms negate `s`.
                let norm = r.read_u16_le()? as usize;
                let [base, _] = r.read_u16_le()?.to_le_bytes();
                let base = i32::from(base);
                let mut s = shade_words.get((norm / 2) & 2047);
                if matches!(opcode, OP_SHADE2 | OP_SHADE216) {
                    s = neg_shade(s);
                }
                if matches!(opcode, OP_SHADE16 | OP_SHADE216) {
                    s >>= 1;
                }
                let level = shade_level(s, base);
                // `base` is a byte and `level.max(0)` is not negative, so only the top clamps.
                cur_color = u8::try_from(shade_colour(base, level)).unwrap_or(u8::MAX);
            }
            OP_RETURN => {
                returned_at = Some(op_offset);
                // End of a SORT branch: run the next one; the last RETURN ends the stream.
                if let Some((resume, visibility, scope_end)) = branch_resume.pop() {
                    jump = Some(resume);
                    current_visibility = visibility;
                    visibility_scope_end = scope_end;
                } else {
                    halt = true;
                }
            }
            _ => {
                let skip = census_skip(opcode);
                match blocked(
                    policy,
                    op_offset,
                    opcode,
                    SodStopReason::UnknownOpcode,
                    skip.is_some(),
                ) {
                    Blockage::Fail(error) => return Err(error),
                    Blockage::Stop(stop) => {
                        return Ok(VmRun {
                            header,
                            polygons,
                            stop: Some(stop),
                            stepped_over,
                            returned_at,
                            sprites,
                        });
                    }
                    Blockage::StepOver(stop) => {
                        let skip = skip.expect("a steppable opcode has a census width");
                        let mut words = usize::from(skip.fixed_words);
                        for i in 0..skip.fixed_words {
                            let word = r.read_u16_le()?;
                            if skip.count_word == Some(i) {
                                words = words.checked_add(usize::from(word)).ok_or_else(|| {
                                    SodError::MalformedOpcode {
                                        opcode,
                                        offset: op_offset,
                                        reason: "skipped operand count overflows".to_string(),
                                    }
                                })?;
                            }
                        }
                        for _ in usize::from(skip.fixed_words)..words {
                            r.read_u16_le()?;
                        }
                        stepped_over.push(stop);
                    }
                }
            }
        }
        if let Some(steps) = trace.as_deref_mut() {
            steps.push(TraceStep::new(data, op_offset, opcode, r.pos(), jump));
        }
        if let Some(target) = jump {
            r.set_pos(target);
        }
        if halt {
            break;
        }
        if let Some(reason) = malformed {
            match blocked(policy, op_offset, opcode, reason, false) {
                Blockage::Fail(error) => return Err(error),
                Blockage::Stop(stop) | Blockage::StepOver(stop) => {
                    return Ok(VmRun {
                        header,
                        polygons,
                        stop: Some(stop),
                        stepped_over,
                        returned_at,
                        sprites,
                    });
                }
            }
        }
    }

    Ok(VmRun {
        header,
        polygons,
        stop: None,
        stepped_over,
        returned_at,
        sprites,
    })
}

/// A lenient VM walk of one shape, instruction by instruction.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SodTrace {
    /// Executed and stepped-over instructions in execution order; a jump shows as the next
    /// step's offset.
    pub steps: Vec<TraceStep>,
    /// The blocking opcode the walk stopped on, as a lenient decode reports it.
    pub stop: Option<SodStop>,
    /// The decode error that ended the walk; the steps before it are kept.
    pub error: Option<SodError>,
}

/// Walks `data` as a lenient [`crate::sod::decode_sod`] does and records every instruction.
///
/// `anchors` and `light` are as for [`crate::sod::decode_sod_lit`]. The trace never fails: a
/// decode error ends it and is kept in [`SodTrace::error`].
#[must_use]
pub fn trace_sod(data: &[u8], anchors: Option<&[AnchorPoint]>, light: ShadeLight) -> SodTrace {
    let mut steps = Vec::new();
    let (stop, error) = match run_vm(data, Policy::Lenient, anchors, light, Some(&mut steps)) {
        Ok(run) => (run.stop, None),
        Err(error) => (None, Some(error)),
    };
    SodTrace { steps, stop, error }
}

/// The mnemonic of `opcode` without the `OP_` prefix: the VM's own name for an opcode it
/// runs, the [`CENSUS_SKIPS`] name for one it steps over, else `None`.
#[must_use]
pub fn opcode_mnemonic(opcode: u16) -> Option<&'static str> {
    Some(match opcode {
        OP_CLRV => "CLRV",
        OP_GETV => "GETV",
        OP_ID => "ID",
        OP_PUTV => "PUTV",
        OP_INTV => "INTV",
        OP_ADDV => "ADDV",
        OP_SUBV => "SUBV",
        OP_NEGV => "NEGV",
        OP_SHLV => "SHLV",
        OP_SHRV => "SHRV",
        OP_VEC => "VEC",
        OP_IPG => "IPG",
        OP_VECTORS => "VECTORS",
        OP_PERS => "PERS",
        OP_MOVETO => "MOVETO",
        OP_LINECOL => "LINECOL",
        OP_ZLINETO => "ZLINETO",
        OP_POLYZ => "POLYZ",
        OP_SPHERE => "SPHERE",
        OP_PERFDISK => "PERFDISK",
        OP_COLOR => "COLOR",
        OP_SHADES => "SHADES",
        OP_SHADE1 => "SHADE1",
        OP_SHADE2 => "SHADE2",
        OP_SHADE216 => "SHADE216",
        OP_GVPOLY => "GVPOLY",
        OP_IFVIS => "IFVIS",
        OP_SORT => "SORT",
        OP_RETURN => "RETURN",
        OP_PUSHCENTRE => "PUSHCENTRE",
        OP_POPCENTRE => "POPCENTRE",
        OP_MOVECENTRE => "MOVECENTRE",
        OP_PUSHRELMAT => "PUSHRELMAT",
        OP_POPRELMAT => "POPRELMAT",
        OP_ANIMATE => "ANIMATE",
        OP_ROTY => "ROTY",
        OP_ROTX => "ROTX",
        OP_ROTZ => "ROTZ",
        OP_BVGT => "BVGT",
        OP_GOTO => "GOTO",
        OP_GOSUB => "GOSUB",
        OP_REJ => "REJ",
        OP_TAP => "TAP",
        OP_SHADE16 => "SHADE16",
        OP_GVPOLY16 => "GVPOLY16",
        OP_DOT => "DOT",
        OP_BLOCK => "BLOCK",
        _ => return census_skip(opcode).map(|skip| skip.mnemonic),
    })
}

fn add3(a: [f32; 3], b: [f32; 3]) -> [f32; 3] {
    [a[0] + b[0], a[1] + b[1], a[2] + b[2]]
}

/// Operand layout the census walk assumes when stepping over an unimplemented opcode.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct CensusSkip {
    /// The opcode word.
    pub opcode: u16,
    /// Mnemonic from `formats/sod.md` § 3.2, without the `OP_` prefix.
    pub mnemonic: &'static str,
    /// Operand words that always follow the opcode.
    pub fixed_words: u16,
    /// Index, among the fixed words, of a count of further words that follow them.
    pub count_word: Option<u16>,
}

const fn skip(opcode: u16, mnemonic: &'static str, fixed_words: u16) -> CensusSkip {
    CensusSkip {
        opcode,
        mnemonic,
        fixed_words,
        count_word: None,
    }
}

/// Operand widths for opcodes the VM does not implement, used only by a census decode.
///
/// Widths come from the operand column of `research/formats/sod.md` § 3.2, which follows the
/// community `SOD.H` rather than the binary, so a wrong entry
/// desynchronises the walk. Opcodes whose operands § 3.2 gives as `...` or unknown are left
/// out, and the walk ends on them.
///
/// The table holds only unimplemented opcodes: implementing an opcode in the VM loop means
/// deleting its entry here. `vm_tests` fails while an entry shadows a real handler.
pub const CENSUS_SKIPS: &[CensusSkip] = &[
    skip(0x0051, "BLOKADD", 3),
    skip(0x005A, "BLOKNEG", 3),
    skip(0x00AB, "LINETO", 1),
    skip(0x00C6, "HUGELINETO", 1),
    skip(0x00CF, "VLINETO", 1),
    skip(0x00D8, "VOTEVIS", 1),
    skip(0x00E1, "VOTEHID", 1),
    CensusSkip {
        opcode: 0x00EA,
        mnemonic: "POLY",
        fixed_words: 1,
        count_word: Some(0),
    },
    skip(0x0105, "DISC", 2),
    skip(0x0183, "BVIS", 2),
    skip(0x02F4, "BVLT", 3),
    skip(0x0306, "WIDELINE", 3),
    skip(0x0318, "BZLT", 2),
    skip(0x0321, "SCALEIT", 1),
    skip(0x032A, "SPRITE", 2),
    skip(0x034E, "LETTER", 2),
    skip(0x0360, "CLR2D", 0),
    skip(0x0369, "GET2D", 1),
    skip(0x0372, "PUT2D", 1),
    skip(0x037B, "INT2D", 1),
    skip(0x0384, "ADD2D", 1),
    skip(0x038D, "SUB2D", 1),
    skip(0x0396, "SHL2D", 1),
    skip(0x039F, "SHR2D", 1),
    skip(0x03B1, "CIRCLE", 2),
];

/// The [`CENSUS_SKIPS`] entry for `opcode`, if any.
#[must_use]
pub fn census_skip(opcode: u16) -> Option<CensusSkip> {
    CENSUS_SKIPS.iter().copied().find(|s| s.opcode == opcode)
}
