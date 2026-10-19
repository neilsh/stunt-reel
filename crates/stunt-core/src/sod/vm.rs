//! Procedural `.SOD` bytecode virtual machine and register file execution.
//!
//! Governed by architectural invariants:
//! - `[I1]` Metric right-handed coordinates (+X right, +Y up, +Z toward viewer, -Z forward)
//! - `[I2]` Flat arena layout compatibility with [`crate::contracts::scene::SodModelIr`]
//! - `[I3]` VGA Mode 13h palette index mapping (0..=255)
//!
//! Reference specs: `# [FMT-SOD-OPCODES]`, `# [FMT-SOD-IFVIS]`, historical `DECODE.C`/`SOD.H`.

use crate::contracts::scene::VisibilityCondition;
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

/// Parsed 10-byte header of a `.SOD` procedural model.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct SodHeader {
    /// Bounding volume diameter in model units (`u16`), used for coarse culling.
    pub bounding_size: u16,
    /// Signed vertical offset of the model origin above its ground plane, in model units.
    pub ground_y_offset: i16,
    /// Index into [`SOD_SCALE_TABLE`] selecting the integer-to-meter multiplier.
    pub scale_index: u8,
    /// High byte of the header's flags/scale word, preserved verbatim for consumers.
    pub header_flags: u8,
    /// Metric multiplier (meters per integer unit) derived from `scale_index`.
    pub scale_factor: f32,
    /// Engine collision metadata word copied verbatim from the header.
    pub collision_meta: u16,
}

/// Intermediate polygonal facet emitted by the bytecode VM before decal resolution and welding.
#[derive(Debug, Clone, PartialEq)]
pub struct RawPolygon {
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

/// Computes the unit outward surface normal from a polygon vertex loop.
///
/// Attempts edge cross product from first three vertices, falling back to Newell's method.
#[must_use]
pub fn compute_polygon_normal(vertices: &[[f32; 3]]) -> [f32; 3] {
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

/// Helper function to read a 16-bit unsigned little-endian word from a byte slice.
fn read_u16(data: &[u8], pos: &mut usize) -> Result<u16, SodError> {
    if *pos + 2 > data.len() {
        return Err(SodError::UnexpectedEof {
            expected: *pos + 2,
            actual: data.len(),
        });
    }
    let val = u16::from_le_bytes([data[*pos], data[*pos + 1]]);
    *pos += 2;
    Ok(val)
}

/// Helper function to read a 16-bit signed little-endian word from a byte slice.
fn read_i16(data: &[u8], pos: &mut usize) -> Result<i16, SodError> {
    if *pos + 2 > data.len() {
        return Err(SodError::UnexpectedEof {
            expected: *pos + 2,
            actual: data.len(),
        });
    }
    let val = i16::from_le_bytes([data[*pos], data[*pos + 1]]);
    *pos += 2;
    Ok(val)
}

/// Evaluates dynamic `OP_IFVIS` condition code to [`VisibilityCondition`].
fn parse_visibility_condition(code: u16) -> VisibilityCondition {
    match code {
        0 => VisibilityCondition::Always,
        1 => VisibilityCondition::LodDistanceSq(1000.0),
        _ => VisibilityCondition::Always,
    }
}

/// Location and opcode of a bytecode stream that stopped at an unknown opcode.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct SodStop {
    /// Byte offset of the unrecognized opcode within the model payload.
    pub offset: usize,
    /// The unrecognized opcode word.
    pub opcode: u16,
}

/// Executes the `.SOD` bytecode virtual machine against input bytes.
///
/// Returns the parsed header and raw polygon stream, and fails on any opcode outside
/// the decoded table.
pub fn execute_sod_vm(data: &[u8]) -> Result<(SodHeader, Vec<RawPolygon>), SodError> {
    let (header, polygons, stop) = execute_sod_vm_impl(data, false)?;
    match stop {
        None => Ok((header, polygons)),
        Some(SodStop { offset, opcode }) => Err(SodError::InvalidOpcode { opcode, offset }),
    }
}

/// Executes the `.SOD` bytecode virtual machine, optionally tolerating unknown opcodes.
///
/// When `lenient` is set, an opcode outside the decoded table ends execution and is
/// reported as [`SodStop`] alongside the polygons decoded up to that offset, so a
/// partially decoded model stays renderable. Strict mode returns the same polygons
/// only for streams that decode to completion.
pub fn execute_sod_vm_impl(
    data: &[u8],
    lenient: bool,
) -> Result<(SodHeader, Vec<RawPolygon>, Option<SodStop>), SodError> {
    if data.len() < 10 {
        return Err(SodError::UnexpectedEof {
            expected: 10,
            actual: data.len(),
        });
    }

    let mut pos = 0;
    let op_id = read_u16(data, &mut pos)?;
    if op_id != OP_ID {
        return Err(SodError::InvalidMagic {
            expected: OP_ID,
            actual: op_id,
        });
    }

    let bounding_size = read_u16(data, &mut pos)?;
    let ground_y_offset = read_i16(data, &mut pos)?;
    let flags_scale = read_u16(data, &mut pos)?;
    let collision_meta = read_u16(data, &mut pos)?;

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
    let mut polygons = Vec::new();
    let mut current_visibility = VisibilityCondition::Always;
    let mut visibility_scope_end = 0usize;

    let total_len = data.len();

    while pos < total_len {
        if pos >= visibility_scope_end && current_visibility != VisibilityCondition::Always {
            current_visibility = VisibilityCondition::Always;
        }

        if pos + 2 > total_len {
            return Err(SodError::UnexpectedEof {
                expected: pos + 2,
                actual: total_len,
            });
        }

        let op_offset = pos;
        let opcode = read_u16(data, &mut pos)?;

        match opcode {
            OP_CLRV => {
                cur_vert = [0.0, 0.0, 0.0];
            }
            OP_GETV => {
                let reg_off = read_u16(data, &mut pos)?;
                let reg_idx = ((reg_off / 12) & 1023) as usize;
                cur_vert = regs[reg_idx];
            }
            OP_ID => {
                // Secondary ID sentinel in stream; safely ignored
            }
            OP_PUTV => {
                let reg_off = read_u16(data, &mut pos)?;
                let reg_idx = ((reg_off / 12) & 1023) as usize;
                regs[reg_idx] = cur_vert;
            }
            OP_INTV => {
                let reg_off = read_u16(data, &mut pos)?;
                let reg_idx = ((reg_off / 12) & 1023) as usize;
                let target = regs[reg_idx];
                cur_vert = [
                    (cur_vert[0] + target[0]) * 0.5,
                    (cur_vert[1] + target[1]) * 0.5,
                    (cur_vert[2] + target[2]) * 0.5,
                ];
            }
            OP_ADDV => {
                let reg_off = read_u16(data, &mut pos)?;
                let reg_idx = ((reg_off / 12) & 1023) as usize;
                let target = regs[reg_idx];
                cur_vert = [
                    cur_vert[0] + target[0],
                    cur_vert[1] + target[1],
                    cur_vert[2] + target[2],
                ];
            }
            OP_SUBV => {
                let reg_off = read_u16(data, &mut pos)?;
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
                let shift = read_u16(data, &mut pos)?;
                let s = (shift as u32) & 31;
                cur_vert = [
                    ((cur_vert[0] as i32).wrapping_shl(s)) as f32,
                    ((cur_vert[1] as i32).wrapping_shl(s)) as f32,
                    ((cur_vert[2] as i32).wrapping_shl(s)) as f32,
                ];
            }
            OP_SHRV => {
                let shift = read_u16(data, &mut pos)?;
                let s = (shift as u32) & 31;
                cur_vert = [
                    ((cur_vert[0] as i32).wrapping_shr(s)) as f32,
                    ((cur_vert[1] as i32).wrapping_shr(s)) as f32,
                    ((cur_vert[2] as i32).wrapping_shr(s)) as f32,
                ];
            }
            OP_IPG => {
                let ipg_type = read_u16(data, &mut pos)?;
                match ipg_type {
                    0 => {
                        // Cube
                        let dx = read_i16(data, &mut pos)? as f32;
                        let dy = read_i16(data, &mut pos)? as f32;
                        let dz = read_i16(data, &mut pos)? as f32;
                        let start_off = read_u16(data, &mut pos)?;
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
                        let dx = read_i16(data, &mut pos)? as f32;
                        let dz = read_i16(data, &mut pos)? as f32;
                        let start_off = read_u16(data, &mut pos)?;
                        let start_reg = ((start_off / 12) & 1023) as usize;

                        regs[(start_reg) & 1023] = [-dx, 0.0, -dz];
                        regs[(start_reg + 1) & 1023] = [-dx, 0.0, dz];
                        regs[(start_reg + 2) & 1023] = [dx, 0.0, dz];
                        regs[(start_reg + 3) & 1023] = [dx, 0.0, -dz];
                    }
                    8 => {
                        // Flat Vertical Quad
                        let dx = read_i16(data, &mut pos)? as f32;
                        let dy = read_i16(data, &mut pos)? as f32;
                        let start_off = read_u16(data, &mut pos)?;
                        let start_reg = ((start_off / 12) & 1023) as usize;

                        regs[(start_reg) & 1023] = [-dx, -dy, 0.0];
                        regs[(start_reg + 1) & 1023] = [-dx, dy, 0.0];
                        regs[(start_reg + 2) & 1023] = [dx, dy, 0.0];
                        regs[(start_reg + 3) & 1023] = [dx, -dy, 0.0];
                    }
                    _ => {
                        // Unrecognized IPG type arguments skipped safely
                        read_u16(data, &mut pos)?;
                        read_u16(data, &mut pos)?;
                    }
                }
            }
            OP_VECTORS => {
                let count = read_u16(data, &mut pos)?;
                let start_off = read_u16(data, &mut pos)?;
                let start_reg = ((start_off / 12) & 1023) as usize;

                for i in 0..count {
                    let vx = read_i16(data, &mut pos)? as f32;
                    let vy = read_i16(data, &mut pos)? as f32;
                    let vz = read_i16(data, &mut pos)? as f32;
                    regs[(start_reg + (i as usize)) & 1023] = [vx, vy, vz];
                }
            }
            OP_COLOR => {
                cur_color = (read_u16(data, &mut pos)? & 0xFF) as u8;
            }
            OP_LINECOL | OP_MOVETO | OP_ZLINETO | OP_DOT => {
                read_u16(data, &mut pos)?;
            }
            OP_POLYZ => {
                let count = read_u16(data, &mut pos)?;
                if count < 3 {
                    return Err(SodError::MalformedPolygon {
                        reason: format!(
                            "OP_POLYZ with count {count} < 3 at offset 0x{op_offset:04X}"
                        ),
                    });
                }

                let mut poly_verts = Vec::with_capacity(count as usize);
                for _ in 0..count {
                    let reg_off = read_u16(data, &mut pos)?;
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
                let count = read_u16(data, &mut pos)?;
                if count < 3 {
                    return Err(SodError::MalformedPolygon {
                        reason: format!(
                            "GVPOLY with count {count} < 3 at offset 0x{op_offset:04X}"
                        ),
                    });
                }

                let mut reg_indices = Vec::with_capacity(count as usize);
                for _ in 0..count {
                    let reg_off = read_u16(data, &mut pos)?;
                    reg_indices.push(((reg_off / 12) & 1023) as usize);
                }

                let norm_off = read_u16(data, &mut pos)?;
                let norm_reg = ((norm_off / 12) & 1023) as usize;

                // Skip per-vertex shade offsets
                for _ in 0..count {
                    read_u16(data, &mut pos)?;
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
                let cond_code = read_u16(data, &mut pos)?;
                let sec_len = read_u16(data, &mut pos)? as usize;
                if pos + sec_len > total_len {
                    // Clamped beyond EOF
                    break;
                }
                current_visibility = parse_visibility_condition(cond_code);
                visibility_scope_end = pos + sec_len;
            }
            OP_SORT | OP_PERFDISK | OP_VEC => {
                read_u16(data, &mut pos)?;
                read_u16(data, &mut pos)?;
                read_u16(data, &mut pos)?;
            }
            OP_SPHERE | OP_BLOCK | OP_PERS => {
                read_u16(data, &mut pos)?;
                read_u16(data, &mut pos)?;
            }
            OP_REJ => {
                read_u16(data, &mut pos)?;
                let num_faces = read_u16(data, &mut pos)?;
                for _ in 0..(num_faces as usize) * 3 {
                    read_u16(data, &mut pos)?;
                }
            }
            OP_SHADES => {
                read_u16(data, &mut pos)?;
                let count = read_u16(data, &mut pos)?;
                for _ in 0..(count as usize) * 3 {
                    read_u16(data, &mut pos)?;
                }
            }
            OP_RETURN => {
                // Bytecode termination
                break;
            }
            _ => {
                if lenient {
                    return Ok((
                        header,
                        polygons,
                        Some(SodStop {
                            offset: op_offset,
                            opcode,
                        }),
                    ));
                }
                return Err(SodError::InvalidOpcode {
                    opcode,
                    offset: op_offset,
                });
            }
        }
    }

    Ok((header, polygons, None))
}
