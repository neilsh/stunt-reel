//! Parity scene assembly: binds `.FLM` actor `shape_id`s to `.SOD` models inside the
//! film's paired `.ALL` archive, and reconstructs static world scenery and terrain
//! (`SCENERY.scn`, `MAP.BIN`, `ANCHORPT.DAT`).
//!
//! Archive chunk names follow `# [FMT-ALL-CHUNKS]` (`MODEL_%04X.SOD`, Invariant `[I8]`),
//! so the resource ID hex in the name is the same value `ActorTransform::shape_id`
//! carries. Chunks that stop at an opcode outside the decoded table are kept with the
//! geometry parsed so far and reported as partial.
//!
//! World scenery adheres to Architectural Invariants:
//! - `[I1]` Metric right-handed coordinates (+X Right, +Y Up, -Z Forward, +Z Backward).
//! - `[I2]` Flat arena allocation for all mesh nodes.
//! - `[I3]` Authentic Mode 13h palette index color mapping.
//! - `[I5]` Separation of base meshes from coplanar decal batches.

use std::collections::{HashMap, HashSet};
use std::fs;
use std::path::{Path, PathBuf};

use glam::Mat4;
use stunt_core::contracts::{NodeKind, SodModelIr, SodVertex, VisibilityCondition};
use stunt_core::sod::{SodStop, transpile_sod_lenient};
use stunt_render::GpuModel;

/// Every renderable model decoded from one `.ALL` archive, keyed by resource ID,
/// plus the consolidated static world scenery and terrain mesh.
#[derive(Debug)]
pub(crate) struct SceneBundle {
    /// Dynamic GPU models keyed by the `shape_id` their chunk name encodes.
    pub(crate) models: HashMap<u16, GpuModel>,
    /// Consolidated static world scenery and terrain model (identity world matrix).
    pub(crate) world_model: Option<GpuModel>,
    /// Number of `MODEL_*.SOD` chunks that failed to decode and were skipped.
    pub(crate) skipped: usize,
    /// Chunks that decoded only up to an unrecognized opcode.
    pub(crate) partial: Vec<(u16, SodStop)>,
}

impl SceneBundle {
    /// Decodes every `MODEL_*.SOD` chunk of the archive at `path` into GPU models,
    /// and searches for static terrain and scenery tables to build the world model.
    pub(crate) fn from_all(
        device: &wgpu::Device,
        queue: &wgpu::Queue,
        model_bind_group_layout: &wgpu::BindGroupLayout,
        path: &Path,
    ) -> Result<Self, String> {
        let bytes = fs::read(path).map_err(|e| format!("read {}: {e}", path.display()))?;
        let archive = stunt_core::vfs::parse_all(&bytes)
            .map_err(|e| format!("parse {}: {e}", path.display()))?;

        let mut models = HashMap::new();
        let mut ir_models = HashMap::new();
        let mut skipped = 0usize;
        let mut partial = Vec::new();

        for entry in archive.entries.values() {
            let Some(shape_id) = model_shape_id(&entry.name) else {
                continue;
            };
            match transpile_sod_lenient(&entry.data, &entry.name) {
                Ok((ir, stop)) => {
                    if let Some(stop) = stop {
                        partial.push((shape_id, stop));
                    }
                    models.insert(
                        shape_id,
                        GpuModel::from_ir(device, queue, model_bind_group_layout, &ir),
                    );
                    ir_models.insert(shape_id, ir);
                }
                Err(e) => {
                    eprintln!("[stuntreel] scene: {} failed to decode: {e}", entry.name);
                    skipped += 1;
                }
            }
        }

        // Search for static scenery and terrain tables
        let world_model =
            load_world_model(device, queue, model_bind_group_layout, path, &ir_models);

        Ok(Self {
            models,
            world_model,
            skipped,
            partial,
        })
    }

    /// Returns the model bound to `shape_id`, if the archive carries one.
    #[must_use]
    pub(crate) fn get(&self, shape_id: u16) -> Option<&GpuModel> {
        self.models.get(&shape_id)
    }
}

/// Extracts the resource ID from a `MODEL_%04X.SOD` archive entry name.
fn model_shape_id(name: &str) -> Option<u16> {
    let hex = name.strip_prefix("MODEL_")?.strip_suffix(".SOD")?;
    u16::from_str_radix(hex, 16).ok()
}

/// Topological anchor point from `ANCHORPT.DAT`.
#[derive(Clone, Copy, Debug)]
struct AnchorPoint {
    x: f32,
    y: f32,
    z: f32,
    valid: bool,
}

/// Polygonal terrain patch from `MAP.BIN`.
#[derive(Clone, Debug)]
struct MapArea {
    color: u8,
    verts: Vec<usize>,
}

/// Locates a scenery data file across standard candidate directories.
fn find_scenery_file(all_path: &Path, filename: &str) -> Option<PathBuf> {
    let mut candidates = Vec::new();
    if let Some(parent) = all_path.parent() {
        candidates.push(parent.to_path_buf());
        if let Some(grandparent) = parent.parent() {
            candidates.push(grandparent.to_path_buf());
            candidates.push(grandparent.join("sidata"));
            candidates.push(grandparent.join("SIDATA"));
        }
    }
    let is_test_fixture = all_path.components().any(|c| {
        let s = c.as_os_str().to_string_lossy();
        s.eq_ignore_ascii_case("tests")
            || s.eq_ignore_ascii_case("fixtures")
            || s.eq_ignore_ascii_case("target")
    });
    let is_corpus = all_path.components().any(|c| {
        let s = c.as_os_str().to_string_lossy();
        s.eq_ignore_ascii_case("corpus")
    });

    if !cfg!(test) && is_corpus && !is_test_fixture {
        candidates.push(PathBuf::from(
            "corpus/si_archive/Developer/FreeFlight/SIDATA",
        ));
        candidates.push(PathBuf::from("corpus/si_archive/Developer/SIRes/SiData"));
    }
    candidates.push(PathBuf::from("sidata"));
    candidates.push(PathBuf::from("SIDATA"));

    for dir in candidates {
        if !dir.is_dir() {
            continue;
        }
        let exact = dir.join(filename);
        if exact.is_file() {
            return Some(exact);
        }
        let upper = dir.join(filename.to_ascii_uppercase());
        if upper.is_file() {
            return Some(upper);
        }
        let lower = dir.join(filename.to_ascii_lowercase());
        if lower.is_file() {
            return Some(lower);
        }
        if let Ok(entries) = fs::read_dir(&dir) {
            for entry in entries.flatten() {
                if entry
                    .file_name()
                    .to_string_lossy()
                    .eq_ignore_ascii_case(filename)
                {
                    return Some(entry.path());
                }
            }
        }
    }
    None
}

/// Parses 28-byte anchor point records from `ANCHORPT.DAT`.
fn parse_anchorpt(data: &[u8]) -> Vec<AnchorPoint> {
    let count = data.len() / 28;
    let mut pts = Vec::with_capacity(count);
    for i in 0..count {
        let offset = i * 28;
        let x = i16::from_le_bytes([data[offset], data[offset + 1]]);
        let y = i16::from_le_bytes([data[offset + 2], data[offset + 3]]);
        let z = i16::from_le_bytes([data[offset + 4], data[offset + 5]]);
        let valid = y > -32000 && y < 32000;
        pts.push(AnchorPoint {
            x: -(x as f32),
            y: -(y as f32), // invert raw negative elevation
            z: z as f32,
            valid,
        });
    }
    pts
}

/// Parses 30-byte polygon patch records from `MAP.BIN`.
fn parse_map_bin(data: &[u8], anchor_count: usize) -> Vec<MapArea> {
    let count = data.len() / 30;
    let mut areas = Vec::new();
    for i in 0..count {
        let offset = i * 30;
        if offset + 30 > data.len() {
            break;
        }
        let pos = i16::from_le_bytes([data[offset + 2], data[offset + 3]]);
        if (pos & 0xFF) == 0 {
            continue;
        }
        let color = data[offset + 12];
        let num_verts = i16::from_le_bytes([data[offset + 14], data[offset + 15]]) as usize;
        let nverts = num_verts.min(7);
        if nverts < 3 {
            continue;
        }
        let mut verts = Vec::with_capacity(nverts);
        let mut valid = true;
        for j in 0..nverts {
            let v_off = offset + 16 + j * 2;
            let v_idx = u16::from_le_bytes([data[v_off], data[v_off + 1]]) as usize;
            if v_idx >= anchor_count {
                valid = false;
                break;
            }
            verts.push(v_idx);
        }
        if valid {
            areas.push(MapArea { color, verts });
        }
    }
    areas
}

/// Fast approximate distance metric matching original engine and `simap.cpp`.
#[cfg(test)]
fn aprox_dist(x1: i32, y1: i32, x2: i32, y2: i32) -> i32 {
    let dx = (x2 - x1).abs();
    let dy = (y2 - y1).abs();
    dx + dy - (dx.min(dy) / 2)
}

/// Traverses `SCENERY.scn` hierarchical BSP tree to collect prop placements.
#[allow(clippy::too_many_arguments)]
fn traverse_scn(
    words: &[i32],
    mut ni: usize,
    mut cx: i32,
    mut cy: i32,
    mut cz: i32,
    instances: &mut Vec<(u16, [f32; 3])>,
    available_models: &HashSet<u16>,
    depth: usize,
) {
    if depth > 128 {
        return;
    }
    while ni != 0 && ni < words.len() {
        let op = words[ni];
        match op {
            0 => {
                // SP_POS: x, y, z, next
                if ni + 4 >= words.len() {
                    break;
                }
                let x = words[ni + 1] as u16 as i16 as i32;
                let y = words[ni + 2] as u16 as i16 as i32;
                let z = words[ni + 3] as u16 as i16 as i32;
                let next = (words[ni + 4] as u32 as usize) / 2;
                cx += x;
                cy += y;
                cz += z;
                ni = next;
            }
            22 => {
                // SP_POSXZ: x, z, next
                if ni + 3 >= words.len() {
                    break;
                }
                let x = words[ni + 1] as u16 as i16 as i32;
                let z = words[ni + 2] as u16 as i16 as i32;
                let next = (words[ni + 3] as u32 as usize) / 2;
                cx += x;
                cz += z;
                ni = next;
            }
            2 => {
                // SP_1NODE: obj, ext, splitdist, next
                if ni + 4 >= words.len() {
                    break;
                }
                let next = (words[ni + 4] as u32 as usize) / 2;
                ni = next;
            }
            4 | 6 | 8 | 16 | 18 => {
                // SP_2NODE, SP_XPLANE, SP_ZPLANE, SP_HSLOPE, SP_VSLOPE
                if ni + 2 >= words.len() {
                    break;
                }
                let ptr = (words[ni + 1] as u32 as usize) / 2;
                let next = (words[ni + 2] as u32 as usize) / 2;
                traverse_scn(
                    words,
                    ptr,
                    cx,
                    cy,
                    cz,
                    instances,
                    available_models,
                    depth + 1,
                );
                ni = next;
            }
            10 => {
                // SP_LEAF: obj
                if ni + 1 < words.len() {
                    let obj = words[ni + 1] as u16;
                    if available_models.contains(&obj) {
                        instances.push((obj, [-(cx as f32), -(cy as f32), cz as f32]));
                    }
                }
                break;
            }
            12 => {
                // SP_GROUND
                if ni + 7 >= words.len() {
                    break;
                }
                let ptr = (words[ni + 6] as u32 as usize) / 2;
                let next = (words[ni + 7] as u32 as usize) / 2;
                traverse_scn(
                    words,
                    ptr,
                    cx,
                    cy,
                    cz,
                    instances,
                    available_models,
                    depth + 1,
                );
                ni = next;
            }
            14 => {
                // SP_GLEAF
                if ni + 1 >= words.len() {
                    break;
                }
                let next = (words[ni + 1] as u32 as usize) / 2;
                ni = next;
            }
            20 => {
                // SP_LIST
                let mut curr = ni + 1;
                while curr < words.len() && words[curr] != 0 {
                    let child = (words[curr] as u32 as usize) / 2;
                    traverse_scn(
                        words,
                        child,
                        cx,
                        cy,
                        cz,
                        instances,
                        available_models,
                        depth + 1,
                    );
                    curr += 1;
                }
                ni = curr + 1;
            }
            _ => break,
        }
    }
}

/// Builds the consolidated static world scenery and terrain intermediate representation.
fn build_world_ir(
    pts: &[AnchorPoint],
    map_areas: &[MapArea],
    instances: &[(u16, [f32; 3])],
    ir_models: &HashMap<u16, SodModelIr>,
    base_y: f32,
) -> SodModelIr {
    let mut ir = SodModelIr::new("WORLD_SCENERY");
    let up = [0.0, 1.0, 0.0];
    let flags_unshaded = 0x04;

    // 1. Global ocean water quad at base_y - 1.0 per research/formats/auxiliary/map.md § 3.1
    let o_start = ir.vertices.len() as u32;
    let ocean_color = 208u8;
    ir.vertices.push(SodVertex {
        position: [-32000.0, base_y - 1.0, -32000.0],
        normal: up,
        palette_index: ocean_color,
        flags: flags_unshaded,
        _padding: [0, 0],
    });
    ir.vertices.push(SodVertex {
        position: [32000.0, base_y - 1.0, -32000.0],
        normal: up,
        palette_index: ocean_color,
        flags: flags_unshaded,
        _padding: [0, 0],
    });
    ir.vertices.push(SodVertex {
        position: [32000.0, base_y - 1.0, 32000.0],
        normal: up,
        palette_index: ocean_color,
        flags: flags_unshaded,
        _padding: [0, 0],
    });
    ir.vertices.push(SodVertex {
        position: [-32000.0, base_y - 1.0, 32000.0],
        normal: up,
        palette_index: ocean_color,
        flags: flags_unshaded,
        _padding: [0, 0],
    });
    ir.indices.extend_from_slice(&[
        o_start,
        o_start + 1,
        o_start + 2,
        o_start,
        o_start + 2,
        o_start + 3,
    ]);

    // 2. Island terrain polygons from MAP.BIN and ANCHORPT.DAT
    if map_areas.is_empty() {
        // Fallback ground plane at base_y if MAP.BIN is absent
        let g_start = ir.vertices.len() as u32;
        let ground_color = 194u8;
        ir.vertices.push(SodVertex {
            position: [-32000.0, base_y, -32000.0],
            normal: up,
            palette_index: ground_color,
            flags: flags_unshaded,
            _padding: [0, 0],
        });
        ir.vertices.push(SodVertex {
            position: [32000.0, base_y, -32000.0],
            normal: up,
            palette_index: ground_color,
            flags: flags_unshaded,
            _padding: [0, 0],
        });
        ir.vertices.push(SodVertex {
            position: [32000.0, base_y, 32000.0],
            normal: up,
            palette_index: ground_color,
            flags: flags_unshaded,
            _padding: [0, 0],
        });
        ir.vertices.push(SodVertex {
            position: [-32000.0, base_y, 32000.0],
            normal: up,
            palette_index: ground_color,
            flags: flags_unshaded,
            _padding: [0, 0],
        });
        ir.indices.extend_from_slice(&[
            g_start,
            g_start + 1,
            g_start + 2,
            g_start,
            g_start + 2,
            g_start + 3,
        ]);
    } else {
        for area in map_areas {
            if area.verts.len() < 3 {
                continue;
            }
            if !area
                .verts
                .iter()
                .all(|&idx| pts.get(idx).is_some_and(|p| p.valid))
            {
                continue;
            }

            let p0 = pts[area.verts[0]];
            let p1 = pts[area.verts[1]];
            let p2 = pts[area.verts[2]];
            let v01 = [p1.x - p0.x, p1.y - p0.y, p1.z - p0.z];
            let v02 = [p2.x - p0.x, p2.y - p0.y, p2.z - p0.z];
            let norm = [
                v01[1] * v02[2] - v01[2] * v02[1],
                v01[2] * v02[0] - v01[0] * v02[2],
                v01[0] * v02[1] - v01[1] * v02[0],
            ];
            let len = (norm[0] * norm[0] + norm[1] * norm[1] + norm[2] * norm[2]).sqrt();
            let normal = if len > 1e-6 {
                [norm[0] / len, norm[1] / len, norm[2] / len]
            } else {
                up
            };

            let start_idx = ir.vertices.len() as u32;
            for &v_idx in &area.verts {
                let p = pts[v_idx];
                ir.vertices.push(SodVertex {
                    position: [p.x, p.y + base_y, p.z],
                    normal,
                    palette_index: area.color,
                    flags: flags_unshaded,
                    _padding: [0, 0],
                });
            }
            for k in 1..(area.verts.len() as u32 - 1) {
                ir.indices.push(start_idx);
                ir.indices.push(start_idx + k);
                ir.indices.push(start_idx + k + 1);
            }
        }
    }

    // 3. Static Props: Base Geometry Batch
    for &(shape_id, pos) in instances {
        let Some(model_ir) = ir_models.get(&shape_id) else {
            continue;
        };
        for node in &model_ir.nodes {
            if let NodeKind::Mesh {
                vertex_offset,
                vertex_count,
                index_offset,
                index_count,
                is_decal: false,
            } = node.kind
            {
                if index_count == 0 {
                    continue;
                }
                let base_start = ir.vertices.len() as u32;
                let v_start = vertex_offset as usize;
                let v_end = (vertex_offset + vertex_count) as usize;
                for v in &model_ir.vertices[v_start..v_end] {
                    ir.vertices.push(SodVertex {
                        position: [
                            v.position[0] + pos[0],
                            v.position[1] + pos[1] + base_y,
                            v.position[2] + pos[2],
                        ],
                        normal: v.normal,
                        palette_index: v.palette_index,
                        flags: v.flags,
                        _padding: [0, 0],
                    });
                }
                let i_start = index_offset as usize;
                let i_end = (index_offset + index_count) as usize;
                for &idx in &model_ir.indices[i_start..i_end] {
                    if idx >= vertex_offset && idx < vertex_offset + vertex_count {
                        let local = idx - vertex_offset;
                        ir.indices.push(base_start + local);
                    }
                }
            }
        }
    }

    let total_base_indices = ir.indices.len() as u32;
    let total_base_vertices = ir.vertices.len() as u32;

    // 4. Static Props: Decal Geometry Batch (hardware depth-bias pass per [I5])
    let decal_index_start = total_base_indices;
    for &(shape_id, pos) in instances {
        let Some(model_ir) = ir_models.get(&shape_id) else {
            continue;
        };
        for node in &model_ir.nodes {
            if let NodeKind::Mesh {
                vertex_offset,
                vertex_count,
                index_offset,
                index_count,
                is_decal: true,
            } = node.kind
            {
                if index_count == 0 {
                    continue;
                }
                let decal_start = ir.vertices.len() as u32;
                let v_start = vertex_offset as usize;
                let v_end = (vertex_offset + vertex_count) as usize;
                for v in &model_ir.vertices[v_start..v_end] {
                    ir.vertices.push(SodVertex {
                        position: [
                            v.position[0] + pos[0],
                            v.position[1] + pos[1] + base_y,
                            v.position[2] + pos[2],
                        ],
                        normal: v.normal,
                        palette_index: v.palette_index,
                        flags: v.flags,
                        _padding: [0, 0],
                    });
                }
                let i_start = index_offset as usize;
                let i_end = (index_offset + index_count) as usize;
                for &idx in &model_ir.indices[i_start..i_end] {
                    if idx >= vertex_offset && idx < vertex_offset + vertex_count {
                        let local = idx - vertex_offset;
                        ir.indices.push(decal_start + local);
                    }
                }
            }
        }
    }

    let total_decal_indices = ir.indices.len() as u32 - decal_index_start;
    let total_decal_vertices = ir.vertices.len() as u32 - total_base_vertices;

    let root_base = ir.allocate_node(
        "WORLD_BASE",
        None,
        Mat4::IDENTITY.to_cols_array(),
        VisibilityCondition::Always,
        NodeKind::Mesh {
            vertex_offset: 0,
            vertex_count: total_base_vertices,
            index_offset: 0,
            index_count: total_base_indices,
            is_decal: false,
        },
    );

    if total_decal_indices > 0 {
        ir.allocate_node(
            "WORLD_DECAL",
            Some(root_base),
            Mat4::IDENTITY.to_cols_array(),
            VisibilityCondition::Always,
            NodeKind::Mesh {
                vertex_offset: 0,
                vertex_count: total_decal_vertices,
                index_offset: decal_index_start,
                index_count: total_decal_indices,
                is_decal: true,
            },
        );
    }

    ir
}

/// Locates scenery assets and compiles the consolidated static world `GpuModel`.
fn load_world_model(
    device: &wgpu::Device,
    queue: &wgpu::Queue,
    model_bind_group_layout: &wgpu::BindGroupLayout,
    all_path: &Path,
    ir_models: &HashMap<u16, SodModelIr>,
) -> Option<GpuModel> {
    let scn_bytes = find_scenery_file(all_path, "SCENERY.scn").and_then(|p| fs::read(p).ok());

    let pts = find_scenery_file(all_path, "ANCHORPT.DAT")
        .and_then(|p| fs::read(p).ok())
        .map(|b| parse_anchorpt(&b))
        .unwrap_or_default();

    let map_areas = find_scenery_file(all_path, "MAP.BIN")
        .and_then(|p| fs::read(p).ok())
        .map(|b| parse_map_bin(&b, pts.len()))
        .unwrap_or_default();

    if scn_bytes.is_none() && pts.is_empty() && map_areas.is_empty() {
        return None;
    }

    let available_models: HashSet<u16> = ir_models.keys().copied().collect();
    let mut instances = Vec::new();

    if let Some(scn_bytes) = scn_bytes {
        let (chunks, _) = scn_bytes.as_chunks::<4>();
        let mut words = Vec::with_capacity(chunks.len());
        for chunk in chunks {
            words.push(i32::from_le_bytes(*chunk));
        }

        traverse_scn(&words, 1, 0, 0, 0, &mut instances, &available_models, 0);
    }

    // Deduplicate identical prop positions (normalizing -0.0 to 0.0 to prevent duplicate bits)
    let norm_zero = |v: f32| if v == 0.0 { 0.0f32 } else { v };
    let mut seen = HashSet::new();
    let mut unique_instances = Vec::with_capacity(instances.len());
    for (shape_id, pos) in instances {
        let key = (
            shape_id,
            norm_zero(pos[0]).to_bits(),
            norm_zero(pos[1]).to_bits(),
            norm_zero(pos[2]).to_bits(),
        );
        if seen.insert(key) {
            unique_instances.push((shape_id, pos));
        }
    }

    println!(
        "[stuntreel] world scenery: {} terrain patches, {} static props placed",
        map_areas.len(),
        unique_instances.len()
    );

    let base_y = 0.0;
    let world_ir = build_world_ir(&pts, &map_areas, &unique_instances, ir_models, base_y);
    let mut min_x = f32::INFINITY;
    let mut max_x = f32::NEG_INFINITY;
    let mut min_y = f32::INFINITY;
    let mut max_y = f32::NEG_INFINITY;
    let mut min_z = f32::INFINITY;
    let mut max_z = f32::NEG_INFINITY;
    for v in &world_ir.vertices {
        min_x = min_x.min(v.position[0]);
        max_x = max_x.max(v.position[0]);
        min_y = min_y.min(v.position[1]);
        max_y = max_y.max(v.position[1]);
        min_z = min_z.min(v.position[2]);
        max_z = max_z.max(v.position[2]);
    }
    println!(
        "[stuntreel] world_ir: {} vertices, {} indices, bounds: X({}..{}), Y({}..{}), Z({}..{})",
        world_ir.vertices.len(),
        world_ir.indices.len(),
        min_x,
        max_x,
        min_y,
        max_y,
        min_z,
        max_z
    );
    Some(GpuModel::from_ir(
        device,
        queue,
        model_bind_group_layout,
        &world_ir,
    ))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parse_anchorpt_valid_and_invalid() {
        let mut data = vec![0u8; 56]; // 2 records of 28 bytes
        // Record 0: x = 100, y = -500, z = 200
        data[0..2].copy_from_slice(&100i16.to_le_bytes());
        data[2..4].copy_from_slice(&(-500i16).to_le_bytes());
        data[4..6].copy_from_slice(&200i16.to_le_bytes());

        // Record 1: x = 0, y = -32500 (invalid tap point), z = 0
        data[28..30].copy_from_slice(&0i16.to_le_bytes());
        data[30..32].copy_from_slice(&(-32500i16).to_le_bytes());
        data[32..34].copy_from_slice(&0i16.to_le_bytes());

        let pts = parse_anchorpt(&data);
        assert_eq!(pts.len(), 2);
        assert_eq!(pts[0].x, -100.0);
        assert_eq!(pts[0].y, 500.0); // inverted elevation
        assert_eq!(pts[0].z, 200.0);
        assert!(pts[0].valid);

        assert_eq!(pts[1].y, 32500.0);
        assert!(!pts[1].valid);
    }

    #[test]
    fn test_parse_map_bin_filtering() {
        let mut data = vec![0u8; 60]; // 2 records of 30 bytes
        // Record 0: valid active quad, color 150, 4 vertices (indices 0, 1, 2, 3)
        data[0..2].copy_from_slice(&1i16.to_le_bytes()); // num
        data[2..4].copy_from_slice(&0x01FFi16.to_le_bytes()); // pos (active)
        data[12] = 150; // color
        data[14..16].copy_from_slice(&4i16.to_le_bytes()); // num_verts = 4
        data[16..18].copy_from_slice(&0u16.to_le_bytes());
        data[18..20].copy_from_slice(&1u16.to_le_bytes());
        data[20..22].copy_from_slice(&2u16.to_le_bytes());
        data[22..24].copy_from_slice(&3u16.to_le_bytes());

        // Record 1: inactive polygon (pos & 0xFF == 0)
        data[30..32].copy_from_slice(&2i16.to_le_bytes());
        data[32..34].copy_from_slice(&0x0100i16.to_le_bytes()); // pos & 0xFF == 0
        data[42] = 160;
        data[44..46].copy_from_slice(&3i16.to_le_bytes());

        let areas = parse_map_bin(&data, 10);
        assert_eq!(areas.len(), 1);
        assert_eq!(areas[0].color, 150);
        assert_eq!(areas[0].verts, vec![0, 1, 2, 3]);

        // If anchor_count is too low, the polygon is rejected
        let areas_low = parse_map_bin(&data, 3);
        assert_eq!(areas_low.len(), 0);
    }

    #[test]
    fn test_traverse_scn_opcodes() {
        // Construct a small SCENERY.scn bytecode stream:
        // Node 1: SP_POS (op 0) -> x=10, y=20, z=30, next=6 (word index 6)
        let mut words = vec![0i32; 10];
        words[1] = 0;
        words[2] = 10; // x
        words[3] = 20; // y
        words[4] = 30; // z
        words[5] = 12; // next half-word offset = 12 (word index 6)

        // Node 6: SP_LEAF (op 10) -> obj=0x0105
        words[6] = 10;
        words[7] = 0x0105;

        let mut available = HashSet::new();
        available.insert(0x0105);

        let mut instances = Vec::new();
        traverse_scn(&words, 1, 0, 0, 0, &mut instances, &available, 0);

        assert_eq!(instances.len(), 1);
        assert_eq!(instances[0].0, 0x0105);
        // x=-10, y=-20, z=30
        assert_eq!(instances[0].1, [-10.0, -20.0, 30.0]);
    }

    #[test]
    fn test_build_world_ir_structure() {
        let pts = vec![
            AnchorPoint {
                x: 0.0,
                y: 10.0,
                z: 0.0,
                valid: true,
            },
            AnchorPoint {
                x: 10.0,
                y: 10.0,
                z: 0.0,
                valid: true,
            },
            AnchorPoint {
                x: 10.0,
                y: 10.0,
                z: 10.0,
                valid: true,
            },
        ];
        let map_areas = vec![MapArea {
            color: 42,
            verts: vec![0, 1, 2],
        }];

        let mut ir_models = HashMap::new();
        let mut prop_ir = SodModelIr::new("TEST_PROP");
        prop_ir.allocate_node(
            "BASE",
            None,
            [0.0; 16],
            VisibilityCondition::Always,
            NodeKind::Mesh {
                vertex_offset: 0,
                vertex_count: 3,
                index_offset: 0,
                index_count: 3,
                is_decal: false,
            },
        );
        prop_ir.allocate_node(
            "DECAL",
            None,
            [0.0; 16],
            VisibilityCondition::Always,
            NodeKind::Mesh {
                vertex_offset: 0,
                vertex_count: 3,
                index_offset: 3,
                index_count: 3,
                is_decal: true,
            },
        );
        prop_ir.vertices.resize(
            3,
            SodVertex {
                position: [1.0, 2.0, 3.0],
                normal: [0.0, 1.0, 0.0],
                palette_index: 10,
                flags: 0,
                _padding: [0, 0],
            },
        );
        prop_ir.indices = vec![0, 1, 2, 0, 1, 2];
        ir_models.insert(0x0100, prop_ir);

        let instances = vec![(0x0100, [100.0, 50.0, 200.0])];
        let world_ir = build_world_ir(&pts, &map_areas, &instances, &ir_models, 0.0);

        // Should contain ocean quad (4 verts), terrain triangle (3 verts), and prop base + decal
        assert!(world_ir.vertices.len() >= 7);
        assert!(world_ir.indices.len() >= 9);

        // Check node separation: WORLD_BASE and WORLD_DECAL
        let base_node = world_ir.nodes.iter().find(|n| n.name == "WORLD_BASE");
        assert!(base_node.is_some());
        let decal_node = world_ir.nodes.iter().find(|n| n.name == "WORLD_DECAL");
        assert!(decal_node.is_some());
    }

    #[test]
    fn test_aprox_dist() {
        assert_eq!(aprox_dist(0, 0, 3, 4), 3 + 4 - 3 / 2);
        assert_eq!(aprox_dist(10, 20, 10, 20), 0);
    }

    #[test]
    fn test_find_scenery_file_cleanroom_isolation() {
        let fixture_path = Path::new("tests/fixtures/synthetic_minimal.all");
        // Test fixture path must NOT resolve to corpus directories
        let found = find_scenery_file(fixture_path, "SCENERY.scn");
        assert!(
            found.is_none(),
            "find_scenery_file must not look in corpus/ when path is a test fixture"
        );
    }

    #[test]
    fn test_find_scenery_file_non_corpus_isolation() {
        // Any path not under corpus/ must NOT resolve into corpus/
        let temp_path = std::env::temp_dir().join("cleanroom_test.all");
        let found = find_scenery_file(&temp_path, "SCENERY.scn");
        assert!(
            found.is_none(),
            "find_scenery_file must never resolve to corpus/ for paths outside corpus/"
        );
    }

    #[test]
    fn test_prop_deduplication_signed_zero() {
        let instances = vec![
            (0x0100u16, [0.0f32, 0.0f32, 10.0f32]),
            (0x0100u16, [-0.0f32, 0.0f32, 10.0f32]),
            (0x0100u16, [0.0f32, -0.0f32, 10.0f32]),
            (0x0101u16, [0.0f32, 0.0f32, 10.0f32]),
        ];
        let norm_zero = |v: f32| if v == 0.0 { 0.0f32 } else { v };
        let mut seen = HashSet::new();
        let mut unique = Vec::new();
        for (shape_id, pos) in instances {
            let key = (
                shape_id,
                norm_zero(pos[0]).to_bits(),
                norm_zero(pos[1]).to_bits(),
                norm_zero(pos[2]).to_bits(),
            );
            if seen.insert(key) {
                unique.push((shape_id, pos));
            }
        }
        // First 3 instances share shape_id 0x0100 and (0,0,10) position despite sign bits
        assert_eq!(unique.len(), 2);
        assert_eq!(unique[0].0, 0x0100);
        assert_eq!(unique[1].0, 0x0101);
    }

    #[test]
    fn test_build_world_ir_out_of_bounds_index() {
        let pts = Vec::new();
        let map_areas = Vec::new();
        let mut ir_models = HashMap::new();
        let mut prop_ir = SodModelIr::new("CORRUPT_PROP");
        prop_ir.allocate_node(
            "BASE",
            None,
            [0.0; 16],
            VisibilityCondition::Always,
            NodeKind::Mesh {
                vertex_offset: 10,
                vertex_count: 2,
                index_offset: 0,
                index_count: 3,
                is_decal: false,
            },
        );
        prop_ir.vertices.resize(
            12,
            SodVertex {
                position: [0.0; 3],
                normal: [0.0, 1.0, 0.0],
                palette_index: 1,
                flags: 0,
                _padding: [0, 0],
            },
        );
        // Indices intentionally include:
        // - 5 (< vertex_offset 10)
        // - 10 (valid, in [10, 12))
        // - 99 (> vertex_offset + vertex_count 12)
        prop_ir.indices = vec![5, 10, 99];
        ir_models.insert(0x0200, prop_ir);

        let instances = vec![(0x0200, [0.0, 0.0, 0.0])];
        // Must not panic on underflow or out-of-bounds index
        let world_ir = build_world_ir(&pts, &map_areas, &instances, &ir_models, 0.0);
        // Ocean quad uses 6 indices, fallback ground plane uses 6 indices, valid prop index pushed 1 index (index 10)
        assert_eq!(world_ir.indices.len(), 6 + 6 + 1);
    }
}
