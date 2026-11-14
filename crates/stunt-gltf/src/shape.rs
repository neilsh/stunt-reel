//! Shape-to-glTF mapping: one shared vertex buffer, one glTF node per [`SodNode`].
//!
//! The model's vertex buffer is written once as `POSITION`, `NORMAL` and `COLOR_0`
//! accessors (`[I1]` metres unchanged, `[I3]` palette colours). Each
//! [`NodeKind::Mesh`] node becomes a glTF mesh whose single primitive reads its slice of
//! the consolidated index buffer. Indices in the IR are global into the vertex buffer (the
//! tessellator's per-batch weld map stores `ir.vertices.len()` positions), so they are
//! written unchanged and `vertex_offset` is not added.
//!
//! A slice's screen-space lines (`VERTEX_FLAG_LINE` quads, which have no world width) become
//! a second primitive in `LINES` mode, one segment per quad, and leave the triangle primitive.
//!
//! `[I5]`: decal slices own their vertices (a fresh weld map per batch) and lie in their
//! base's plane. glTF has no depth bias or draw order, so the exporter alone lifts each decal
//! vertex [`EPSILON_DISPLACEMENT`] along its triangle's front normal (the side that winds
//! clockwise, opposite the edge cross product).

use serde_json::{Value, json};
use stunt_core::contracts::{
    NodeId, NodeKind, ShapeMesh, SodModelIr, SodNode, SodVertex, VERTEX_FLAG_LINE,
    VERTEX_FLAG_LINE_END, VERTEX_FLAG_LINE_SIDE, VisibilityCondition, get_palette_rgb_float,
};
use stunt_core::sod::EPSILON_DISPLACEMENT;

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
    if model.vertices.is_empty() {
        return Ok(ShapeAssets { mesh_of_node });
    }
    let vertex_count = model.vertices.len();
    let lifted = lifted_positions(model);
    let mut lo = [f32::INFINITY; 3];
    let mut hi = [f32::NEG_INFINITY; 3];
    for p in &lifted {
        for ((l, h), c) in lo.iter_mut().zip(&mut hi).zip(p) {
            *l = l.min(*c);
            *h = h.max(*c);
        }
    }

    let mut positions = Vec::with_capacity(vertex_count * 12);
    let mut normals = Vec::with_capacity(vertex_count * 12);
    let mut colors = Vec::with_capacity(vertex_count * 16);
    for (v, lifted) in model.vertices.iter().zip(&lifted) {
        for (p, n) in lifted.iter().zip(&v.normal) {
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
        Some((lo.to_vec(), hi.to_vec())),
    );
    let normal = vec_accessor(builder, &normals, "VEC3", None);
    let color = vec_accessor(builder, &colors, "VEC4", None);

    let index_bytes: Vec<u8> = model.indices.iter().flat_map(|i| i.to_le_bytes()).collect();
    let index_view = builder.add_view(&index_bytes, TARGET_ELEMENT_ARRAY_BUFFER);

    for mesh in model.meshes() {
        if mesh.indices.is_empty() {
            continue;
        }
        let attributes = json!({ "POSITION": position, "NORMAL": normal, "COLOR_0": color });
        let (triangles, lines) = split_lines(mesh.indices, &model.vertices);
        let mut primitives = Vec::new();
        if lines.is_empty() {
            let indices = builder.add_accessor(&AccessorSpec {
                view: index_view,
                byte_offset: mesh.index_offset as usize * 4,
                component_type: COMPONENT_UNSIGNED_INT,
                count: mesh.indices.len(),
                kind: "SCALAR",
                bounds: None,
            });
            primitives.push(json!({ "attributes": attributes, "indices": indices, "material": 0 }));
        } else {
            for (list, mode) in [(&triangles, MODE_TRIANGLES), (&lines, MODE_LINES)] {
                if list.is_empty() {
                    continue;
                }
                let bytes: Vec<u8> = list.iter().flat_map(|i| i.to_le_bytes()).collect();
                let view = builder.add_view(&bytes, TARGET_ELEMENT_ARRAY_BUFFER);
                let indices = builder.add_accessor(&AccessorSpec {
                    view,
                    byte_offset: 0,
                    component_type: COMPONENT_UNSIGNED_INT,
                    count: list.len(),
                    kind: "SCALAR",
                    bounds: None,
                });
                primitives.push(json!({
                    "attributes": attributes,
                    "indices": indices,
                    "material": 0,
                    "mode": mode,
                }));
            }
        }
        let node_id = mesh.node.id.0;
        *mesh_of_node
            .get_mut(node_id as usize)
            .ok_or(GltfError::InvalidNodeReference(node_id))? = Some(builder.meshes.len());
        builder
            .meshes
            .push(json!({ "name": mesh.node.name, "primitives": primitives }));
    }
    Ok(ShapeAssets { mesh_of_node })
}

/// glTF primitive mode `LINES`.
const MODE_LINES: u32 = 1;
/// glTF primitive mode `TRIANGLES`.
const MODE_TRIANGLES: u32 = 4;

/// Splits a slice's triangle indices into the triangles that are not line quads and one
/// `LINES` segment per line quad: from its corner at the first endpoint to its corner at the
/// second, both on the negative side (`VERTEX_FLAG_LINE*`). A segment welded into several
/// triangles is listed once.
/// Each vertex's exported position: a vertex of a decal slice's filled triangle lifted
/// [`EPSILON_DISPLACEMENT`] toward the front of the first such triangle that uses it, every
/// other vertex as decoded (`[I5]`).
fn lifted_positions(model: &SodModelIr) -> Vec<[f32; 3]> {
    let mut out: Vec<[f32; 3]> = model.vertices.iter().map(|v| v.position).collect();
    let mut done = vec![false; out.len()];
    for mesh in model.meshes().filter(ShapeMesh::is_decal) {
        let (triangles, _) = split_lines(mesh.indices, &model.vertices);
        for tri in triangles.as_chunks::<3>().0 {
            let [Some(a), Some(b), Some(c)] =
                tri.map(|i| model.vertices.get(i as usize).map(|v| v.position))
            else {
                continue;
            };
            let (u, w) = (sub(b, a), sub(c, a));
            // Front = -(u x w) = w x u.
            let n = [
                w[1] * u[2] - w[2] * u[1],
                w[2] * u[0] - w[0] * u[2],
                w[0] * u[1] - w[1] * u[0],
            ];
            let len = (n[0] * n[0] + n[1] * n[1] + n[2] * n[2]).sqrt();
            if len < 1e-12 {
                continue;
            }
            for &i in tri {
                let i = i as usize;
                if let (Some(p), Some(seen)) = (out.get_mut(i), done.get_mut(i))
                    && !*seen
                {
                    *seen = true;
                    for (c, nc) in p.iter_mut().zip(n) {
                        *c += EPSILON_DISPLACEMENT * nc / len;
                    }
                }
            }
        }
    }
    out
}

fn sub(a: [f32; 3], b: [f32; 3]) -> [f32; 3] {
    [a[0] - b[0], a[1] - b[1], a[2] - b[2]]
}

fn split_lines(indices: &[u32], vertices: &[SodVertex]) -> (Vec<u32>, Vec<u32>) {
    const MASK: u8 = VERTEX_FLAG_LINE | VERTEX_FLAG_LINE_END | VERTEX_FLAG_LINE_SIDE;
    let flags = |i: u32| vertices.get(i as usize).map_or(0, |v| v.flags);
    let mut triangles = Vec::with_capacity(indices.len());
    let mut lines: Vec<u32> = Vec::new();
    for tri in indices.chunks(3) {
        if !tri.iter().any(|&i| flags(i) & VERTEX_FLAG_LINE != 0) {
            triangles.extend_from_slice(tri);
            continue;
        }
        let start = tri.iter().find(|&&i| flags(i) & MASK == VERTEX_FLAG_LINE);
        let end = tri
            .iter()
            .find(|&&i| flags(i) & MASK == VERTEX_FLAG_LINE | VERTEX_FLAG_LINE_END);
        if let (Some(&a), Some(&b)) = (start, end)
            && !lines.chunks(2).any(|seg| seg == [a, b])
        {
            lines.extend([a, b]);
        }
    }
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
