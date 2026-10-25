//! Procedural `.SOD` bytecode virtual machine and register file execution.
//!
//! Governed by architectural invariants:
//! - `[I1]` Metric right-handed coordinates (+X right, +Y up, +Z toward viewer, -Z forward)
//! - `[I2]` Flat arena layout compatibility with [`crate::contracts::shape::SodModelIr`]
//! - `[I3]` VGA Mode 13h palette index mapping (0..=255)
//!
//! Reference specs: `# [FMT-SOD-OPCODES]`, `# [FMT-SOD-IFVIS]`, historical `DECODE.C`/`SOD.H`.

use crate::anchor::AnchorPoint;
use crate::contracts::shape::{SodHeader, SodStop, SodStopReason, VisibilityCondition};
use crate::reader::ByteReader;
use crate::sod::SodError;

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
/// Reserved opcode: consumes three operand words without producing geometry in this VM.
pub const OP_VEC: u16 = 0x004B;
/// Procedural primitive generator: cube, ground plane, or quad (`type, dims, reg`).
pub const OP_IPG: u16 = 0x0063;
/// Batch-upload vectors into consecutive registers (`count, reg, count*3 words`).
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
/// Emit a perforated disc ring (`center_reg, r_in, r_out`).
pub const OP_PERFDISK: u16 = 0x010E;
/// Set the active polygon fill palette index (`color: u16`, `0..=255`).
pub const OP_COLOR: u16 = 0x0129;
/// Batch-upload shading normal vectors (`count, ...triplets`).
pub const OP_SHADES: u16 = 0x0156;
/// Emit a normal-lit shaded polygon (`count, regs..., normal, shades...`).
pub const OP_GVPOLY: u16 = 0x0168;
/// Conditionally skip the enclosed section based on a visibility code (`cond, size`).
pub const OP_IFVIS: u16 = 0x017A;
/// Reserved BSP branch (`plane, left_off, right_off`); operands are skipped and stream order is kept.
pub const OP_SORT: u16 = 0x018C;
/// End the display list or return from a bytecode subroutine (no operands).
pub const OP_RETURN: u16 = 0x0195;
/// Alias for [`OP_RETURN`]: ends the display list (no operands).
pub const OP_END: u16 = 0x0195;
/// 3D bounding-box culling test (`box_reg, count, ...faces`).
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

/// Power-of-2 scaling multiplier table (`sod_scale_table` in historical C implementation).
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

/// Computes the metric scale multiplier (meters per integer unit).
#[must_use]
pub fn compute_scale_factor(scale_index: usize) -> f32 {
    let scale_raw = if scale_index < SOD_SCALE_TABLE.len() {
        SOD_SCALE_TABLE[scale_index]
    } else if scale_index > 0 {
        5.0 / 2.0f32.powi((scale_index - 1) as i32)
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
    const PHI: f32 = std::f32::consts::GOLDEN_RATIO;
    const FACES: [[usize; 3]; 20] = [
        [0, 11, 5],
        [0, 5, 1],
        [0, 1, 7],
        [0, 7, 10],
        [0, 10, 11],
        [1, 5, 9],
        [5, 11, 4],
        [11, 10, 2],
        [10, 7, 6],
        [7, 1, 8],
        [3, 9, 4],
        [3, 4, 2],
        [3, 2, 6],
        [3, 6, 8],
        [3, 8, 9],
        [4, 9, 5],
        [2, 4, 11],
        [6, 2, 10],
        [8, 6, 7],
        [9, 8, 1],
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
            let vertices: Vec<[f32; 3]> = face.iter().map(|&i| metric(corners[i])).collect();
            let normal = compute_polygon_normal(&vertices);
            RawPolygon {
                vertices,
                palette_index,
                normal,
                flags: 0,
                is_decal: false,
                visibility,
            }
        })
        .collect()
}

/// World-space thickness in metres of the ribbons that stand in for 1-pixel lines and dots.
const LINE_WIDTH_M: f32 = 0.03;

/// Builds a thin geometry for a `MOVETO`/`ZLINETO` segment: two perpendicular ribbons, each
/// emitted with both windings so back-face culling cannot hide it. Endpoints are metres.
fn line_polygons(
    a: [f32; 3],
    b: [f32; 3],
    palette_index: u8,
    visibility: VisibilityCondition,
) -> Vec<RawPolygon> {
    let d = [b[0] - a[0], b[1] - a[1], b[2] - a[2]];
    let len = (d[0] * d[0] + d[1] * d[1] + d[2] * d[2]).sqrt();
    if len < 1e-6 {
        return Vec::new();
    }
    let dir = [d[0] / len, d[1] / len, d[2] / len];
    // Any axis not parallel to the segment seeds the perpendicular basis.
    let seed = if dir[1].abs() < 0.9 {
        [0.0, 1.0, 0.0]
    } else {
        [1.0, 0.0, 0.0]
    };
    let cross = |u: [f32; 3], v: [f32; 3]| {
        [
            u[1] * v[2] - u[2] * v[1],
            u[2] * v[0] - u[0] * v[2],
            u[0] * v[1] - u[1] * v[0],
        ]
    };
    let norm = |v: [f32; 3]| {
        let l = (v[0] * v[0] + v[1] * v[1] + v[2] * v[2]).sqrt();
        [v[0] / l, v[1] / l, v[2] / l]
    };
    let p1 = norm(cross(dir, seed));
    let p2 = norm(cross(dir, p1));
    let h = LINE_WIDTH_M * 0.5;
    let mut out = Vec::with_capacity(4);
    for p in [p1, p2] {
        let quad = [
            [a[0] - p[0] * h, a[1] - p[1] * h, a[2] - p[2] * h],
            [a[0] + p[0] * h, a[1] + p[1] * h, a[2] + p[2] * h],
            [b[0] + p[0] * h, b[1] + p[1] * h, b[2] + p[2] * h],
            [b[0] - p[0] * h, b[1] - p[1] * h, b[2] - p[2] * h],
        ];
        let n = compute_polygon_normal(&quad);
        out.push(RawPolygon {
            vertices: quad.to_vec(),
            palette_index,
            normal: n,
            flags: 0,
            is_decal: false,
            visibility,
        });
        let rev: Vec<[f32; 3]> = quad.iter().rev().copied().collect();
        out.push(RawPolygon {
            vertices: rev,
            palette_index,
            normal: [-n[0], -n[1], -n[2]],
            flags: 0,
            is_decal: false,
            visibility,
        });
    }
    out
}

/// Builds a tiny octahedron (8 triangles) for an `OP_DOT` at metric position `c`.
fn dot_polygons(
    c: [f32; 3],
    palette_index: u8,
    visibility: VisibilityCondition,
) -> Vec<RawPolygon> {
    let r = LINE_WIDTH_M;
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
    for i in 0..4 {
        let (p, q) = (ring[i], ring[(i + 1) % 4]);
        for tri in [[top, q, p], [bot, p, q]] {
            let verts = tri.to_vec();
            let normal = compute_polygon_normal(&verts);
            out.push(RawPolygon {
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
    if vertices.len() < 3 {
        return [0.0, 1.0, 0.0];
    }

    // Edge cross product from first three vertices
    let v0 = vertices[0];
    let v1 = vertices[1];
    let v2 = vertices[2];

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
    let n_v = vertices.len();
    for i in 0..n_v {
        let curr = vertices[i];
        let nxt = vertices[(i + 1) % n_v];
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

/// Evaluates dynamic `OP_IFVIS` condition code to [`VisibilityCondition`].
fn parse_visibility_condition(code: u16) -> VisibilityCondition {
    match code {
        0 => VisibilityCondition::Always,
        1 => VisibilityCondition::LodDistanceSq(1000.0),
        _ => VisibilityCondition::Always,
    }
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
        Policy::Lenient => Blockage::Stop(stop),
        Policy::Census if steppable => Blockage::StepOver(stop),
        Policy::Census => Blockage::Stop(stop),
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
}

/// Runs one pass of the VM.
///
/// The policy decides, at every blocking site, whether to fail, stop or step over;
/// header parsing, register arithmetic and geometry emission are shared by every mode.
pub(crate) fn run_vm(
    data: &[u8],
    policy: Policy,
    anchors: Option<&[AnchorPoint]>,
) -> Result<VmRun, SodError> {
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
    let mut regs = [[0.0f32; 3]; 1024];
    let mut cur_vert = [0.0f32; 3];
    let mut cur_color = 0u8;
    // Line colour (`OP_LINECOL`); falls back to the fill colour until first set.
    let mut line_color: Option<u8> = None;
    // Pen position in metres for `OP_MOVETO` / `OP_ZLINETO`.
    let mut pen = [0.0f32; 3];
    let mut polygons = Vec::new();
    let mut stepped_over: Vec<SodStop> = Vec::new();
    let mut returned_at: Option<usize> = None;
    let mut current_visibility = VisibilityCondition::Always;
    let mut visibility_scope_end = 0usize;

    let total_len = data.len();

    while r.pos() < total_len {
        if r.pos() >= visibility_scope_end && current_visibility != VisibilityCondition::Always {
            current_visibility = VisibilityCondition::Always;
        }

        if r.pos() + 2 > total_len {
            return Err(SodError::UnexpectedEof {
                expected: r.pos() + 2,
                actual: total_len,
            });
        }

        let op_offset = r.pos();
        let opcode = r.read_u16_le()?;

        match opcode {
            OP_CLRV => {
                cur_vert = [0.0, 0.0, 0.0];
            }
            OP_GETV => {
                let reg_off = r.read_u16_le()?;
                let reg_idx = ((reg_off / 12) & 1023) as usize;
                cur_vert = regs[reg_idx];
            }
            OP_ID => {
                // Secondary ID sentinel in stream; safely ignored
            }
            OP_PUTV => {
                let reg_off = r.read_u16_le()?;
                let reg_idx = ((reg_off / 12) & 1023) as usize;
                regs[reg_idx] = cur_vert;
            }
            OP_INTV => {
                let reg_off = r.read_u16_le()?;
                let reg_idx = ((reg_off / 12) & 1023) as usize;
                let target = regs[reg_idx];
                cur_vert = [
                    (cur_vert[0] + target[0]) * 0.5,
                    (cur_vert[1] + target[1]) * 0.5,
                    (cur_vert[2] + target[2]) * 0.5,
                ];
            }
            OP_ADDV => {
                let reg_off = r.read_u16_le()?;
                let reg_idx = ((reg_off / 12) & 1023) as usize;
                let target = regs[reg_idx];
                cur_vert = [
                    cur_vert[0] + target[0],
                    cur_vert[1] + target[1],
                    cur_vert[2] + target[2],
                ];
            }
            OP_SUBV => {
                let reg_off = r.read_u16_le()?;
                let reg_idx = ((reg_off / 12) & 1023) as usize;
                let target = regs[reg_idx];
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
                let s = (shift as u32) & 31;
                cur_vert = [
                    ((cur_vert[0] as i32).wrapping_shl(s)) as f32,
                    ((cur_vert[1] as i32).wrapping_shl(s)) as f32,
                    ((cur_vert[2] as i32).wrapping_shl(s)) as f32,
                ];
            }
            OP_SHRV => {
                let shift = r.read_u16_le()?;
                let s = (shift as u32) & 31;
                cur_vert = [
                    ((cur_vert[0] as i32).wrapping_shr(s)) as f32,
                    ((cur_vert[1] as i32).wrapping_shr(s)) as f32,
                    ((cur_vert[2] as i32).wrapping_shr(s)) as f32,
                ];
            }
            OP_IPG => {
                let ipg_type = r.read_u16_le()?;
                match ipg_type {
                    0 => {
                        // Cube
                        let dx = r.read_i16_le()? as f32;
                        let dy = r.read_i16_le()? as f32;
                        let dz = r.read_i16_le()? as f32;
                        let start_off = r.read_u16_le()?;
                        let start_reg = ((start_off / 12) & 1023) as usize;

                        regs[(start_reg) & 1023] = [-dx, -dy, -dz];
                        regs[(start_reg + 1) & 1023] = [-dx, -dy, dz];
                        regs[(start_reg + 2) & 1023] = [dx, -dy, dz];
                        regs[(start_reg + 3) & 1023] = [dx, -dy, -dz];
                        regs[(start_reg + 4) & 1023] = [-dx, dy, -dz];
                        regs[(start_reg + 5) & 1023] = [-dx, dy, dz];
                        regs[(start_reg + 6) & 1023] = [dx, dy, dz];
                        regs[(start_reg + 7) & 1023] = [dx, dy, -dz];
                    }
                    2 => {
                        // Ground Quad
                        let dx = r.read_i16_le()? as f32;
                        let dz = r.read_i16_le()? as f32;
                        let start_off = r.read_u16_le()?;
                        let start_reg = ((start_off / 12) & 1023) as usize;

                        regs[(start_reg) & 1023] = [-dx, 0.0, -dz];
                        regs[(start_reg + 1) & 1023] = [-dx, 0.0, dz];
                        regs[(start_reg + 2) & 1023] = [dx, 0.0, dz];
                        regs[(start_reg + 3) & 1023] = [dx, 0.0, -dz];
                    }
                    8 => {
                        // Flat Vertical Quad
                        let dx = r.read_i16_le()? as f32;
                        let dy = r.read_i16_le()? as f32;
                        let start_off = r.read_u16_le()?;
                        let start_reg = ((start_off / 12) & 1023) as usize;

                        regs[(start_reg) & 1023] = [-dx, -dy, 0.0];
                        regs[(start_reg + 1) & 1023] = [-dx, dy, 0.0];
                        regs[(start_reg + 2) & 1023] = [dx, dy, 0.0];
                        regs[(start_reg + 3) & 1023] = [dx, -dy, 0.0];
                    }
                    4 => {
                        // Subobject template (`subobjs`): a single operand word.
                        // Skipping two words swallowed the following `RETURN` and
                        // exposed that return word as a bogus opcode (`0x0002`).
                        r.read_u16_le()?;
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
                    let vx = r.read_i16_le()? as f32;
                    let vy = r.read_i16_le()? as f32;
                    let vz = r.read_i16_le()? as f32;
                    regs[(start_reg + (i as usize)) & 1023] = [vx, vy, vz];
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
                let raw_v = regs[((reg_off / 12) & 1023) as usize];
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
                if count < 3 {
                    return Err(SodError::MalformedPolygon {
                        reason: format!(
                            "OP_POLYZ with count {count} < 3 at offset 0x{op_offset:04X}"
                        ),
                    });
                }

                let mut poly_verts = Vec::with_capacity(count as usize);
                for _ in 0..count {
                    let reg_off = r.read_u16_le()?;
                    let reg_idx = ((reg_off / 12) & 1023) as usize;
                    let raw_v = regs[reg_idx];

                    // Convert to metric coordinates per Invariant [I1]
                    let mx = raw_v[0] * scale_factor;
                    let my = (raw_v[1] + f32::from(ground_y_offset)) * scale_factor;
                    let mz = raw_v[2] * scale_factor;
                    poly_verts.push([mx, my, mz]);
                }

                let norm = compute_polygon_normal(&poly_verts);
                polygons.push(RawPolygon {
                    vertices: poly_verts,
                    palette_index: cur_color,
                    normal: norm,
                    flags: 0,
                    is_decal: false,
                    visibility: current_visibility,
                });
            }
            OP_GVPOLY | OP_GVPOLY16 => {
                let count = r.read_u16_le()?;
                if count < 3 {
                    return Err(SodError::MalformedPolygon {
                        reason: format!(
                            "GVPOLY with count {count} < 3 at offset 0x{op_offset:04X}"
                        ),
                    });
                }

                let mut reg_indices = Vec::with_capacity(count as usize);
                for _ in 0..count {
                    let reg_off = r.read_u16_le()?;
                    reg_indices.push(((reg_off / 12) & 1023) as usize);
                }

                let norm_off = r.read_u16_le()?;
                let norm_reg = ((norm_off / 12) & 1023) as usize;

                // Skip per-vertex shade offsets
                for _ in 0..count {
                    r.read_u16_le()?;
                }

                let mut poly_verts = Vec::with_capacity(count as usize);
                for &r_idx in &reg_indices {
                    let raw_v = regs[r_idx];
                    let mx = raw_v[0] * scale_factor;
                    let my = (raw_v[1] + f32::from(ground_y_offset)) * scale_factor;
                    let mz = raw_v[2] * scale_factor;
                    poly_verts.push([mx, my, mz]);
                }

                let raw_n = regs[norm_reg];
                let n_len =
                    (raw_n[0] * raw_n[0] + raw_n[1] * raw_n[1] + raw_n[2] * raw_n[2]).sqrt();
                let norm = if n_len > 1e-12 {
                    [raw_n[0] / n_len, raw_n[1] / n_len, raw_n[2] / n_len]
                } else {
                    compute_polygon_normal(&poly_verts)
                };

                polygons.push(RawPolygon {
                    vertices: poly_verts,
                    palette_index: cur_color,
                    normal: norm,
                    flags: 0,
                    is_decal: false,
                    visibility: current_visibility,
                });
            }
            OP_IFVIS => {
                let cond_code = r.read_u16_le()?;
                let sec_len = r.read_u16_le()? as usize;
                if r.pos() + sec_len > total_len {
                    // Clamped beyond EOF
                    break;
                }
                current_visibility = parse_visibility_condition(cond_code);
                visibility_scope_end = r.pos() + sec_len;
            }
            OP_SORT | OP_PERFDISK | OP_VEC => {
                r.read_u16_le()?;
                r.read_u16_le()?;
                r.read_u16_le()?;
            }
            OP_SPHERE => {
                let center_off = r.read_u16_le()?;
                let radius = f32::from(r.read_u16_le()?);
                let center = regs[((center_off / 12) & 1023) as usize];
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
                r.read_u16_le()?;
                let num_faces = r.read_u16_le()?;
                for _ in 0..(num_faces as usize) * 3 {
                    r.read_u16_le()?;
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
                    Some(points) if !points.is_empty() => points,
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
                            });
                        }
                        Blockage::StepOver(stop) => {
                            // The point count is in the operand, so the walk can skip it.
                            for _ in 0..count {
                                r.read_u16_le()?;
                            }
                            stepped_over.push(stop);
                            continue;
                        }
                    },
                };

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
                                });
                            }
                        }
                    };

                    regs[(start_reg + i) & 1023] = anchor.register_position();
                }
            }
            OP_SHADES => {
                r.read_u16_le()?;
                let count = r.read_u16_le()?;
                for _ in 0..(count as usize) * 3 {
                    r.read_u16_le()?;
                }
            }
            OP_SHADE16 => {
                // Normal register and ramp index. The lighting state is not modelled
                // yet, but the established two-word width keeps the stream aligned.
                r.read_u16_le()?;
                r.read_u16_le()?;
            }
            OP_RETURN => {
                // Bytecode termination
                returned_at = Some(op_offset);
                break;
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
                        });
                    }
                    Blockage::StepOver(stop) => {
                        let skip = skip.expect("a steppable opcode has a census width");
                        let mut words = usize::from(skip.fixed_words);
                        for i in 0..skip.fixed_words {
                            let word = r.read_u16_le()?;
                            if skip.count_word == Some(i) {
                                words += usize::from(word);
                            }
                        }
                        for _ in usize::from(skip.fixed_words)..words {
                            r.read_u16_le()?;
                        }
                        stepped_over.push(stop);
                        continue;
                    }
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
    })
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
/// community `SOD.H` rather than the binary (`OP_ANIMATE` excepted), so a wrong entry
/// desynchronises the walk. Opcodes whose operands § 3.2 gives as `...` or unknown are left
/// out, and the walk ends on them.
///
/// The table holds only unimplemented opcodes: implementing an opcode in the VM loop means
/// deleting its entry here. `vm_tests` fails while an entry shadows a real handler.
pub const CENSUS_SKIPS: &[CensusSkip] = &[
    skip(0x0051, "BLOKADD", 3),
    skip(0x005A, "BLOKNEG", 3),
    skip(0x007E, "PUSHCENTRE", 0),
    skip(0x0087, "POPCENTRE", 0),
    skip(0x0090, "MOVECENTRE", 1),
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
    skip(0x0144, "SHADE1", 2),
    skip(0x014D, "SHADE2", 2),
    skip(0x0183, "BVIS", 2),
    skip(0x019E, "GOTO", 1),
    skip(0x01A7, "GOSUB", 1),
    skip(0x01DD, "ROTY", 1),
    skip(0x01E6, "PUSHRELMAT", 0),
    skip(0x01EF, "POPRELMAT", 0),
    // `OP_ANIMATE` is a clipped screen-space image draw, not geometry (T10), so the census
    // steps over it. When the draw channel lands: delete this entry, collect the draws beside
    // the polygon stream, and add a sibling accessor to the shape IR. `meshes()` stays
    // geometry-only, `extent()` stays metric, and the stop policy does not change.
    CensusSkip {
        opcode: 0x01F8,
        mnemonic: "ANIMATE",
        fixed_words: 4,
        count_word: Some(3),
    },
    skip(0x02C7, "SHADE216", 2),
    skip(0x02E2, "ROTX", 1),
    skip(0x02EB, "ROTZ", 1),
    skip(0x02F4, "BVLT", 3),
    skip(0x02FD, "BVGT", 3),
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
