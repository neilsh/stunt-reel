//! Tessellation, attribute-preserving vertex welding, and Scene Graph IR generation.
//!
//! Governed by architectural invariants:
//! - `[I1]` Metric right-handed coordinates and attribute-preserving vertex welding
//! - `[I2]` Flat arena allocation (`Vec<SodNode>` indexed by `NodeId(u32)`)
//! - `[I3]` VGA Mode 13h palette index preservation
//! - `[I5]` Coplanar decal identification and normal displacement
//!
//! Reference verification: Gate G03 (`std::mem::size_of::<SodVertex>() == 28`).

use crate::anchor::AnchorPoint;
use std::collections::HashMap;

use crate::contracts::shape::{
    DecodeMode, DecodeRecord, NodeId, NodeKind, SodModelIr, SodVertex, VisibilityCondition,
};
use crate::sod::SodError;
use crate::sod::decal::identify_coplanar_decals;
use crate::sod::vm::{Policy, RawPolygon, run_vm};

// Compile-time assertion of Gate G03 requirements
const _: () = assert!(size_of::<SodVertex>() == 28);
const _: () = assert!(align_of::<SodVertex>() == 4);

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

/// Builds a [`SodModelIr`] from a processed polygon list.
pub(crate) fn build_sod_model_ir(
    name: &str,
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
                    scenery_class: 0,
                    _padding: 0,
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

/// Decodes one `.SOD` bytecode stream into a shape (Seam 3).
///
/// This is the only entry point: `mode` selects the stop policy over one VM run.
/// - [`DecodeMode::Strict`]: a blocked stream is an error.
/// - [`DecodeMode::Lenient`]: a blocked stream stops the decode, the geometry decoded so
///   far is kept, and the model's [`DecodeRecord`] carries the stop (a partial shape).
/// - [`DecodeMode::Census`]: anchors are ignored, blocking opcodes with a known width are
///   stepped over and recorded in [`DecodeRecord::stepped_over`], and the returned shape
///   carries no geometry (its vertices and indices are empty).
///
/// `anchors` supplies the global anchor table `OP_TAP` resolves against.
///
/// # Errors
///
/// A malformed header, operand or truncation fails in every mode; a blocked stream fails
/// only in [`DecodeMode::Strict`]. A violated shape invariant is a decoder defect and is
/// reported as [`SodError::InvariantViolation`].
pub fn decode_sod(
    data: &[u8],
    name: &str,
    anchors: Option<&[AnchorPoint]>,
    mode: DecodeMode,
) -> Result<SodModelIr, SodError> {
    let (policy, anchors, geometry) = match mode {
        DecodeMode::Strict => (Policy::Strict, anchors, true),
        DecodeMode::Lenient => (Policy::Lenient, anchors, true),
        DecodeMode::Census => (Policy::Census, None, false),
    };
    let run = run_vm(data, policy, anchors)?;
    let polygons = if geometry {
        identify_coplanar_decals(&run.polygons, 0.001, 1e-4, 1e-4)
    } else {
        Vec::new()
    };
    let mut ir = build_sod_model_ir(name, &polygons)?;
    ir.set_decode(DecodeRecord {
        header: run.header,
        stop: run.stop,
        stepped_over: run.stepped_over,
        returned_at: run.returned_at,
    });
    check_shape_invariants(&ir)?;
    Ok(ir)
}

/// Enforces the invariants every decoded shape must satisfy.
///
/// A violation is a decoder defect, not a property of the input bytes, so it is reported
/// loudly: a dense arena, symmetric parent/child handles under exactly one root, mesh
/// slices contained in the buffers with whole triangles whose indices stay inside their
/// own node's vertex window, and non-decal slices before decal slices in ascending index
/// order. Authored IRs (the world, the synthetic aircraft) are trusted constructions and
/// are not checked here.
pub(crate) fn check_shape_invariants(ir: &SodModelIr) -> Result<(), SodError> {
    let defect = |reason: String| SodError::InvariantViolation { reason };
    for (index, node) in ir.nodes.iter().enumerate() {
        if node.id != NodeId(index as u32) {
            return Err(defect(format!(
                "node {index} carries id {}; the arena must be dense",
                node.id
            )));
        }
        if let Some(parent) = node.parent {
            let parent_node = ir
                .nodes
                .get(parent.0 as usize)
                .ok_or_else(|| defect(format!("node {} names missing parent {parent}", node.id)))?;
            if !parent_node.children.contains(&node.id) {
                return Err(defect(format!(
                    "node {} is not listed among the children of its parent {parent}",
                    node.id
                )));
            }
        }
        for &child in &node.children {
            let child_node = ir
                .nodes
                .get(child.0 as usize)
                .ok_or_else(|| defect(format!("node {} names missing child {child}", node.id)))?;
            if child_node.parent != Some(node.id) {
                return Err(defect(format!(
                    "child {child} of node {} does not point back at it",
                    node.id
                )));
            }
        }
    }

    let roots: Vec<&crate::contracts::shape::SodNode> = ir
        .nodes
        .iter()
        .filter(|node| node.parent.is_none())
        .collect();
    if let [root] = roots.as_slice() {
        if ir.root_nodes.as_slice() != [root.id] {
            return Err(defect(format!(
                "root_nodes {:?} must name the single parentless node {}",
                ir.root_nodes, root.id
            )));
        }
    } else {
        return Err(defect(format!(
            "arena has {} parentless nodes, expected exactly one root",
            roots.len()
        )));
    }

    let mut decal_seen = false;
    let mut last_index_offset: Option<usize> = None;
    for node in &ir.nodes {
        let NodeKind::Mesh {
            vertex_offset,
            vertex_count,
            index_offset,
            index_count,
            is_decal,
        } = &node.kind
        else {
            continue;
        };
        let vertex_offset = *vertex_offset as usize;
        let vertex_count = *vertex_count as usize;
        let index_offset = *index_offset as usize;
        let index_count = *index_count as usize;
        if !index_count.is_multiple_of(3) {
            return Err(defect(format!(
                "mesh node {} has {index_count} indices, not whole triangles",
                node.name
            )));
        }
        if let Some(last) = last_index_offset
            && index_offset <= last
        {
            return Err(defect(format!(
                "mesh node {} starts at index {index_offset}, not after {last}",
                node.name
            )));
        }
        last_index_offset = Some(index_offset);
        let vertex_end = vertex_offset
            .checked_add(vertex_count)
            .ok_or_else(|| defect(format!("mesh node {} vertex window overflows", node.name)))?;
        let index_end = index_offset
            .checked_add(index_count)
            .ok_or_else(|| defect(format!("mesh node {} index window overflows", node.name)))?;
        if ir.vertices.get(vertex_offset..vertex_end).is_none() {
            return Err(defect(format!(
                "mesh node {} vertex window {vertex_offset}..{vertex_end} leaves the buffer",
                node.name
            )));
        }
        let indices = ir.indices.get(index_offset..index_end).ok_or_else(|| {
            defect(format!(
                "mesh node {} index window {index_offset}..{index_end} leaves the buffer",
                node.name
            ))
        })?;
        for &index in indices {
            if !(vertex_offset..vertex_end).contains(&(index as usize)) {
                return Err(defect(format!(
                    "mesh node {} index {index} leaves its vertex window \
                     {vertex_offset}..{vertex_end}",
                    node.name
                )));
            }
        }
        if *is_decal {
            decal_seen = true;
        } else if decal_seen {
            return Err(defect(format!(
                "mesh node {} is base geometry after a decal slice",
                node.name
            )));
        }
    }
    Ok(())
}
