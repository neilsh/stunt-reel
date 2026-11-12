//! Shape-to-glTF mapping: one shared vertex buffer, one glTF node per [`SodNode`].
//!
//! The model's vertex buffer is written once as `POSITION`, `NORMAL` and `COLOR_0`
//! accessors (`[I1]` metres unchanged, `[I3]` palette colours). Each
//! [`NodeKind::Mesh`] node becomes a glTF mesh: a `TRIANGLES` primitive for its opaque
//! triangles and, for [`VERTEX_FLAG_LINE`] quads, a `LINES` primitive (see
//! [`split_line_triangles`]). Each primitive has its own index buffer view. Indices in the IR
//! are global into the vertex buffer (the tessellator's per-batch weld map stores
//! `ir.vertices.len()` positions), so they are written unchanged and `vertex_offset` is not
//! added.
//!
//! `[I5]`: decal slices own their vertices (a fresh weld map per batch) and the tessellator
//! has already displaced them by 0.001 m along their normal, so positions are copied as-is.

use std::collections::BTreeSet;

use serde_json::{Value, json};
use stunt_core::contracts::{
    NodeId, NodeKind, SodModelIr, SodNode, SodVertex, VERTEX_FLAG_LINE, VisibilityCondition,
    get_palette_rgb_float,
};

use crate::GltfError;
use crate::glb::{
    AccessorSpec, COMPONENT_FLOAT, COMPONENT_UNSIGNED_INT, GlbBuilder, TARGET_ARRAY_BUFFER,
    TARGET_ELEMENT_ARRAY_BUFFER, num_array, object,
};

/// glTF mesh index for each node of a model, `None` for nodes that draw nothing.
#[derive(Debug)]
pub(crate) struct ShapeAssets {
    mesh_of_node: Vec<Option<usize>>,
}

/// Exports one model as a `.glb`.
///
/// The scene's roots are the model's root nodes; every [`SodNode`] becomes a glTF node with its
/// `local_matrix`, and its visibility condition goes in `extras` (recorded, not evaluated).
/// Slices and bounds are taken from the IR unchecked.
///
/// # Errors
/// - [`GltfError::EmptyModel`] if the model has no vertices or no indices.
/// - [`GltfError::InvalidNodeReference`] if a node lists a child that is not in the arena.
/// - [`GltfError::TooLarge`] if the output would not fit the 4 GiB GLB container.
pub fn export_shape(model: &SodModelIr) -> Result<Vec<u8>, GltfError> {
    if model.vertices.is_empty() || model.indices.is_empty() {
        return Err(GltfError::EmptyModel);
    }
    let mut builder = GlbBuilder::new();
    let assets = add_shape_assets(&mut builder, model)?;
    let roots = instantiate(&mut builder, model, &assets)?;
    builder.finish(&roots)
}

/// Writes `model`'s vertex/index data and meshes once; returns the node-to-mesh table.
///
/// A model without vertices yields no meshes (its nodes can still be instantiated).
///
/// # Errors
/// [`GltfError::InvalidNodeReference`] if a mesh names a node that is not in the arena.
pub(crate) fn add_shape_assets(
    builder: &mut GlbBuilder,
    model: &SodModelIr,
) -> Result<ShapeAssets, GltfError> {
    let mut mesh_of_node = vec![None; model.nodes.len()];
    let Some(extent) = model.extent() else {
        return Ok(ShapeAssets { mesh_of_node });
    };
    let vertex_count = model.vertices.len();

    let mut positions = Vec::with_capacity(vertex_count * 12);
    let mut normals = Vec::with_capacity(vertex_count * 12);
    let mut colors = Vec::with_capacity(vertex_count * 16);
    for v in &model.vertices {
        for (p, n) in v.position.iter().zip(&v.normal) {
            positions.extend_from_slice(&p.to_le_bytes());
            normals.extend_from_slice(&n.to_le_bytes());
        }
        let (r, g, b) = get_palette_rgb_float(v.palette_index);
        for c in [r, g, b, 1.0] {
            colors.extend_from_slice(&c.to_le_bytes());
        }
    }

    let vec_accessor = |builder: &mut GlbBuilder, data: &[u8], kind: &str, bounds| {
        let view = builder.add_view(data, TARGET_ARRAY_BUFFER);
        builder.add_accessor(&AccessorSpec {
            view,
            byte_offset: 0,
            component_type: COMPONENT_FLOAT,
            count: vertex_count,
            kind,
            bounds,
        })
    };
    let position = vec_accessor(
        builder,
        &positions,
        "VEC3",
        Some((extent.min.to_vec(), extent.max.to_vec())),
    );
    let normal = vec_accessor(builder, &normals, "VEC3", None);
    let color = vec_accessor(builder, &colors, "VEC4", None);

    for mesh in model.meshes() {
        if mesh.indices.is_empty() {
            continue;
        }
        let (triangles, lines) = split_line_triangles(&model.vertices, mesh.indices);
        let mut primitives = Vec::with_capacity(2);
        for (indices, mode) in [(triangles, None), (lines, Some(MODE_LINES))] {
            if indices.is_empty() {
                continue;
            }
            let bytes: Vec<u8> = indices.iter().flat_map(|i| i.to_le_bytes()).collect();
            let view = builder.add_view(&bytes, TARGET_ELEMENT_ARRAY_BUFFER);
            let accessor = builder.add_accessor(&AccessorSpec {
                view,
                byte_offset: 0,
                component_type: COMPONENT_UNSIGNED_INT,
                count: indices.len(),
                kind: "SCALAR",
                bounds: None,
            });
            let mut primitive = json!({
                "attributes": { "POSITION": position, "NORMAL": normal, "COLOR_0": color },
                "indices": accessor,
                "material": 0,
            });
            if let (Some(mode), Some(fields)) = (mode, primitive.as_object_mut()) {
                fields.insert("mode".to_owned(), json!(mode));
            }
            primitives.push(primitive);
        }
        if primitives.is_empty() {
            continue;
        }
        let node_id = mesh.node.id.0;
        *mesh_of_node
            .get_mut(node_id as usize)
            .ok_or(GltfError::InvalidNodeReference(node_id))? = Some(builder.meshes.len());
        builder.meshes.push(json!({
            "name": mesh.node.name,
            "primitives": primitives,
        }));
    }
    Ok(ShapeAssets { mesh_of_node })
}

/// glTF `LINES` primitive mode.
const MODE_LINES: u32 = 1;

/// Splits one mesh's triangle indices into opaque triangles and `LINES` endpoint pairs.
///
/// A [`VERTEX_FLAG_LINE`] quad has no world area, so its triangles would draw as nothing in a
/// glTF viewer. Each of its edges whose endpoints differ in position is exported as one line
/// instead (the on-screen renderer still widens the quad itself). Edges are deduplicated.
fn split_line_triangles(vertices: &[SodVertex], indices: &[u32]) -> (Vec<u32>, Vec<u32>) {
    let is_line = |i: u32| {
        vertices
            .get(i as usize)
            .is_some_and(|v| v.flags & VERTEX_FLAG_LINE != 0)
    };
    let mut triangles = Vec::with_capacity(indices.len());
    let mut edges = BTreeSet::new();
    for tri in indices.chunks(3) {
        let &[x, y, z] = tri else { continue };
        if !tri.iter().any(|&i| is_line(i)) {
            triangles.extend_from_slice(tri);
            continue;
        }
        for (a, b) in [(x, y), (y, z), (z, x)] {
            let (Some(va), Some(vb)) = (vertices.get(a as usize), vertices.get(b as usize)) else {
                continue;
            };
            // Compare bit patterns: the endpoints are equal or not, with no float tolerance.
            if va.position.map(f32::to_bits) != vb.position.map(f32::to_bits) {
                edges.insert((a.min(b), a.max(b)));
            }
        }
    }
    let lines = edges.into_iter().flat_map(|(a, b)| [a, b]).collect();
    (triangles, lines)
}

/// Emits one glTF node per model node (an instance of the shared assets); returns the glTF
/// indices of the model's root nodes.
pub(crate) fn instantiate(
    builder: &mut GlbBuilder,
    model: &SodModelIr,
    assets: &ShapeAssets,
) -> Result<Vec<usize>, GltfError> {
    model
        .root_nodes
        .iter()
        .map(|&id| emit_node(builder, model, assets, id))
        .collect()
}

fn emit_node(
    builder: &mut GlbBuilder,
    model: &SodModelIr,
    assets: &ShapeAssets,
    id: NodeId,
) -> Result<usize, GltfError> {
    let node = model
        .get_node(id)
        .ok_or(GltfError::InvalidNodeReference(id.0))?;
    let index = builder.nodes.len();
    builder.nodes.push(Value::Null);
    let children = node
        .children
        .iter()
        .map(|&child| emit_node(builder, model, assets, child))
        .collect::<Result<Vec<_>, _>>()?;
    *builder
        .nodes
        .get_mut(index)
        .ok_or(GltfError::InvalidNodeReference(id.0))? = node_json(node, assets, &children);
    Ok(index)
}

fn node_json(node: &SodNode, assets: &ShapeAssets, children: &[usize]) -> Value {
    let joint_tag = match &node.kind {
        NodeKind::ArticulatedJoint { joint_tag, .. } => Some(json!(joint_tag)),
        _ => None,
    };
    let extras = object([
        ("visibility", Some(json!(visibility_text(node.visibility)))),
        ("joint_tag", joint_tag),
    ]);
    let mesh = assets
        .mesh_of_node
        .get(node.id.0 as usize)
        .copied()
        .flatten();
    object([
        ("name", Some(json!(node.name))),
        ("matrix", Some(num_array(&node.local_matrix))),
        ("extras", Some(extras)),
        ("mesh", mesh.map(|mesh| json!(mesh))),
        ("children", (!children.is_empty()).then(|| json!(children))),
    ])
}

fn visibility_text(visibility: VisibilityCondition) -> String {
    format!("{visibility:?}")
}

#[cfg(test)]
mod tests {
    use super::*;

    fn vertex(position: [f32; 3], flags: u8) -> SodVertex {
        SodVertex {
            position,
            normal: [0.0, 0.0, 1.0],
            palette_index: 0,
            flags,
            scenery_class: 0,
            _padding: 0,
        }
    }

    #[test]
    fn a_line_quad_becomes_line_pairs_and_opaque_triangles_pass_through() {
        let a = [0.0, 0.0, 0.0];
        let b = [1.0, 0.0, 0.0];
        let c = [0.0, 1.0, 0.0];
        let vertices = [
            vertex(a, VERTEX_FLAG_LINE),
            vertex(a, VERTEX_FLAG_LINE | 0x10),
            vertex(b, VERTEX_FLAG_LINE | 0x20 | 0x10),
            vertex(b, VERTEX_FLAG_LINE | 0x20),
            vertex(c, 0),
            vertex(a, 0),
            vertex(b, 0),
        ];
        let (triangles, lines) = split_line_triangles(&vertices, &[0, 1, 2, 0, 2, 3, 4, 5, 6]);

        assert_eq!(triangles, [4, 5, 6]);
        assert_eq!(lines.len() % 2, 0);
        assert!(!lines.is_empty());
        for pair in lines.chunks(2) {
            let &[a, b] = pair else {
                panic!("lines come in endpoint pairs");
            };
            let p = vertices.get(a as usize).map(|v| v.position);
            let q = vertices.get(b as usize).map(|v| v.position);
            assert!(p.is_some() && p != q, "a zero-length line draws nothing");
        }
    }
}
