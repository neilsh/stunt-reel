//! Tessellation, attribute-preserving vertex welding, and Scene Graph IR generation.
//!
//! Governed by architectural invariants:
//! - `[I1]` Metric right-handed coordinates and attribute-preserving vertex welding
//! - `[I2]` Flat arena allocation (`Vec<SodNode>` indexed by `NodeId(u32)`)
//! - `[I3]` VGA Mode 13h palette index preservation
//! - `[I5]` Coplanar decal identification and normal displacement
//!
//! Reference verification: Gate G03 (`std::mem::size_of::<SodVertex>() == 28`).

use std::collections::HashMap;

use crate::contracts::scene::{NodeId, NodeKind, SodModelIr, SodVertex, VisibilityCondition};
use crate::sod::SodError;
use crate::sod::decal::identify_coplanar_decals;
use crate::sod::vm::{
    RawPolygon, SodAnchorPoint, SodHeader, SodStop, execute_sod_vm, execute_sod_vm_impl,
};

// Compile-time assertion of Gate G03 requirements
const _: () = assert!(std::mem::size_of::<SodVertex>() == 28);
const _: () = assert!(std::mem::align_of::<SodVertex>() == 4);

/// Standard 4x4 affine identity matrix in column-major order.
pub const IDENTITY_MATRIX: [f32; 16] = [
    1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0,
];

/// Attribute tuple key used for vertex deduplication per Invariant `[I1]`.
pub(crate) type WeldKey = (i64, i64, i64, i32, i32, i32, u8, u8);

/// Quantizes vertex attributes into a deduplication key per Invariant `[I1]`.
///
/// Snaps positions within `1e-4 m` and normals within `1e-3` while strictly preserving
/// distinct palette indices and decal flags to prevent normal/color bleeding.
#[must_use]
pub(crate) fn quantize_weld_key(
    pos: &[f32; 3],
    normal: &[f32; 3],
    palette_index: u8,
    flags: u8,
) -> WeldKey {
    let px = (pos[0] * 10_000.0).round() as i64;
    let py = (pos[1] * 10_000.0).round() as i64;
    let pz = (pos[2] * 10_000.0).round() as i64;
    let nx = (normal[0] * 1_000.0).round() as i32;
    let ny = (normal[1] * 1_000.0).round() as i32;
    let nz = (normal[2] * 1_000.0).round() as i32;
    (px, py, pz, nx, ny, nz, palette_index, flags)
}

/// Builds a [`SodModelIr`] from a parsed header and processed polygon list.
pub(crate) fn build_sod_model_ir(
    name: &str,
    _header: &SodHeader,
    polygons: &[RawPolygon],
) -> Result<SodModelIr, SodError> {
    let mut ir = SodModelIr::new(name);

    // Invariant [I2]: Allocate root transform group
    let root_id = ir.allocate_node(
        name,
        None,
        IDENTITY_MATRIX,
        VisibilityCondition::Always,
        NodeKind::TransformGroup,
    );

    if polygons.is_empty() {
        return Ok(ir);
    }

    // Group polygons into batches partitioned by (is_decal, visibility) preserving order.
    // Base geometry meshes (is_decal: false) are processed first, followed by decal meshes (is_decal: true) per Invariant [I5].
    for is_decal in [false, true] {
        let matching_polys: Vec<&RawPolygon> =
            polygons.iter().filter(|p| p.is_decal == is_decal).collect();
        if matching_polys.is_empty() {
            continue;
        }

        // Determine unique visibility conditions in order of appearance
        let mut vis_conditions: Vec<VisibilityCondition> = Vec::new();
        for p in &matching_polys {
            if !vis_conditions.contains(&p.visibility) {
                vis_conditions.push(p.visibility);
            }
        }

        let prefix = if is_decal { "DECAL" } else { "BASE" };

        for (batch_idx, &vis) in vis_conditions.iter().enumerate() {
            let batch: Vec<&RawPolygon> = matching_polys
                .iter()
                .copied()
                .filter(|p| p.visibility == vis)
                .collect();
            if batch.is_empty() {
                continue;
            }

            let node_name = if batch_idx == 0 {
                format!("{name}_{prefix}")
            } else {
                format!("{name}_{prefix}_{batch_idx}")
            };

            let mut weld_map: HashMap<WeldKey, u32> = HashMap::new();
            process_polygon_batch(
                &mut ir,
                root_id,
                &node_name,
                &batch,
                is_decal,
                vis,
                &mut weld_map,
            )?;
        }
    }

    Ok(ir)
}

/// Tessellates and welds a slice of polygons into the model's consolidated buffers,
/// allocating a child [`NodeKind::Mesh`] node under `parent_id`.
fn process_polygon_batch(
    ir: &mut SodModelIr,
    parent_id: NodeId,
    node_name: &str,
    polys: &[&RawPolygon],
    is_decal: bool,
    visibility: VisibilityCondition,
    weld_map: &mut HashMap<WeldKey, u32>,
) -> Result<(), SodError> {
    let vertex_offset = ir.vertices.len() as u32;
    let index_offset = ir.indices.len() as u32;

    for poly in polys {
        let num_v = poly.vertices.len();
        if num_v < 3 {
            continue;
        }

        let mut poly_indices = Vec::with_capacity(num_v);
        for v_pos in &poly.vertices {
            let weld_key = quantize_weld_key(v_pos, &poly.normal, poly.palette_index, poly.flags);
            if let Some(&existing_idx) = weld_map.get(&weld_key) {
                poly_indices.push(existing_idx);
            } else {
                let new_idx = ir.vertices.len() as u32;
                ir.vertices.push(SodVertex {
                    position: *v_pos,
                    normal: poly.normal,
                    palette_index: poly.palette_index,
                    flags: poly.flags,
                    _padding: [0, 0],
                });
                weld_map.insert(weld_key, new_idx);
                poly_indices.push(new_idx);
            }
        }

        // Convex polygon fan triangulation: (0, 1, 2), (0, 2, 3), ...
        let root_idx = poly_indices[0];
        for i in 1..num_v - 1 {
            ir.indices.push(root_idx);
            ir.indices.push(poly_indices[i]);
            ir.indices.push(poly_indices[i + 1]);
        }
    }

    let vertex_count = ir.vertices.len() as u32 - vertex_offset;
    let index_count = ir.indices.len() as u32 - index_offset;

    if index_count > 0 {
        ir.allocate_node(
            node_name,
            Some(parent_id),
            IDENTITY_MATRIX,
            visibility,
            NodeKind::Mesh {
                vertex_offset,
                vertex_count,
                index_offset,
                index_count,
                is_decal,
            },
        );
    }

    Ok(())
}

/// Transpiles procedural `.SOD` bytecode into [`SodModelIr`] adhering to Seam 3 contracts.
pub fn transpile_sod(
    data: &[u8],
    name: &str,
    anchors: Option<&[SodAnchorPoint]>,
) -> Result<SodModelIr, SodError> {
    let (header, raw_polygons) = execute_sod_vm(data, anchors)?;
    let processed_polygons = identify_coplanar_decals(&raw_polygons, 0.001, 1e-4, 1e-4);
    build_sod_model_ir(name, &header, &processed_polygons)
}

/// Transpiles `.SOD` bytecode leniently, keeping the geometry decoded before a stop.
///
/// Returns the model built from every polygon parsed up to an unrecognized opcode,
/// plus that [`SodStop`] when one was hit. Used for parity scene assembly, where the
/// geometry already decoded is what the original engine draws for that tick.
pub fn transpile_sod_lenient(
    data: &[u8],
    name: &str,
    anchors: Option<&[SodAnchorPoint]>,
) -> Result<(SodModelIr, Option<SodStop>), SodError> {
    let (header, raw_polygons, stop) = execute_sod_vm_impl(data, true, anchors)?;
    let processed_polygons = identify_coplanar_decals(&raw_polygons, 0.001, 1e-4, 1e-4);
    Ok((
        build_sod_model_ir(name, &header, &processed_polygons)?,
        stop,
    ))
}
