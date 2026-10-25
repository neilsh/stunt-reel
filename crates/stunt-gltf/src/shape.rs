//! Shape-to-glTF mapping: one shared vertex buffer, one glTF node per [`SodNode`].
//!
//! The model's vertex buffer is written once as `POSITION`, `NORMAL` and `COLOR_0`
//! accessors (`[I1]` metres unchanged, `[I3]` palette colours). Each
//! [`NodeKind::Mesh`] node becomes a glTF mesh whose single primitive reads its slice of
//! the consolidated index buffer. Indices in the IR are global into the vertex buffer (the
//! tessellator's per-batch weld map stores `ir.vertices.len()` positions), so they are
//! written unchanged and `vertex_offset` is not added.
//!
//! `[I5]`: decal slices own their vertices (a fresh weld map per batch) and the tessellator
//! has already displaced them by 0.001 m along their normal, so positions are copied as-is.

use serde_json::{Value, json};
use stunt_core::contracts::{
    NodeId, NodeKind, SodModelIr, SodNode, VisibilityCondition, get_palette_rgb_float,
};

use crate::GltfError;
use crate::glb::{
    AccessorSpec, COMPONENT_FLOAT, COMPONENT_UNSIGNED_INT, GlbBuilder, TARGET_ARRAY_BUFFER,
    TARGET_ELEMENT_ARRAY_BUFFER, num_array,
};

/// glTF mesh index for each node of a model, `None` for nodes that draw nothing.
#[derive(Debug)]
pub(crate) struct ShapeAssets {
    mesh_of_node: Vec<Option<usize>>,
}

/// Exports one model as a `.glb`.
///
/// The scene's root nodes are the model's root nodes; every [`SodNode`] becomes a glTF node
/// with its `local_matrix`, and carries its visibility condition in `extras` (visibility is
/// recorded, not evaluated). Returns [`GltfError::EmptyModel`] when the model has no
/// vertices or indices. The shape IR owns its slices and bounds, so nothing here
/// re-validates or re-measures them.
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
        for axis in 0..3 {
            positions.extend_from_slice(&v.position[axis].to_le_bytes());
            normals.extend_from_slice(&v.normal[axis].to_le_bytes());
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

    let index_bytes: Vec<u8> = model.indices.iter().flat_map(|i| i.to_le_bytes()).collect();
    let index_view = builder.add_view(&index_bytes, TARGET_ELEMENT_ARRAY_BUFFER);

    for mesh in model.meshes() {
        if mesh.indices.is_empty() {
            continue;
        }
        let indices = builder.add_accessor(&AccessorSpec {
            view: index_view,
            byte_offset: mesh.index_offset as usize * 4,
            component_type: COMPONENT_UNSIGNED_INT,
            count: mesh.indices.len(),
            kind: "SCALAR",
            bounds: None,
        });
        mesh_of_node[mesh.node.id.0 as usize] = Some(builder.meshes.len());
        builder.meshes.push(json!({
            "name": mesh.node.name,
            "primitives": [{
                "attributes": { "POSITION": position, "NORMAL": normal, "COLOR_0": color },
                "indices": indices,
                "material": 0,
            }],
        }));
    }
    Ok(ShapeAssets { mesh_of_node })
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
    builder.nodes[index] = node_json(node, assets, &children);
    Ok(index)
}

fn node_json(node: &SodNode, assets: &ShapeAssets, children: &[usize]) -> Value {
    let mut extras = json!({ "visibility": visibility_text(node.visibility) });
    if let NodeKind::ArticulatedJoint { joint_tag, .. } = &node.kind {
        extras["joint_tag"] = json!(joint_tag);
    }
    let mut out = json!({
        "name": node.name,
        "matrix": num_array(&node.local_matrix),
        "extras": extras,
    });
    if let Some(mesh) = assets
        .mesh_of_node
        .get(node.id.0 as usize)
        .copied()
        .flatten()
    {
        out["mesh"] = json!(mesh);
    }
    if !children.is_empty() {
        out["children"] = json!(children);
    }
    out
}

fn visibility_text(visibility: VisibilityCondition) -> String {
    format!("{visibility:?}")
}
