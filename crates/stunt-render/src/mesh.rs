//! GPU Mesh and Display-List Scene Graph Arena.
//!
//! Complies with Architectural Invariants:
//! - `[I2]` Flat contiguous arena allocation (`Vec<SodNode>` indexed by `NodeId(u32)`).
//! - `[I5]` Separation of base meshes from coplanar decal batches.
//!
//! A model larger than `max_buffer_size` (a `--sidata` world can need 500 MB of vertices)
//! is uploaded as several vertex/index buffer pairs, or chunks: `plan_upload` splits each
//! mesh slice into runs of whole triangles, in draw order, that fit one chunk. A model that
//! fits is uploaded unchanged as a single chunk.

use std::ops::Range;

use crate::outline::Outlined;
use glam::{Mat4, Vec3};
use stunt_core::contracts::{
    CameraTransform, NodeId, SodModelIr, SodVertex, VisibilityCondition, arena_index,
};
use stunt_core::world::{GROUND_NODE, PropRun};
use wgpu::util::DeviceExt as _;

use crate::pipeline::PROP_RUNS_GROUP;

/// Cached node data inside GPU model representation.
#[derive(Debug, Clone)]
pub struct GpuNode {
    /// Arena identifier matching the source `SodNode`.
    pub id: NodeId,
    /// Authoring or procedural node name.
    pub name: String,
    /// Parent node, or `None` for a scene root.
    pub parent: Option<NodeId>,
    /// Child nodes in draw order.
    pub children: Vec<NodeId>,
    /// Local transform relative to the parent node.
    pub local_matrix: Mat4,
    /// Dynamic visibility gate evaluated at presentation time.
    pub visibility: VisibilityCondition,
    /// Geometry slices in draw order: none for pure transform groups, several when the
    /// node's mesh spans more than one chunk.
    pub meshes: Vec<GpuMeshSlice>,
    /// Box around this node's slices and every descendant's, in the model's space; `None` when
    /// neither holds a vertex.
    pub bounds: Option<NodeBounds>,
    /// The offsets in the model's index arena [`GpuModel::cut`] may cut this node's slice at,
    /// ascending, each with where its outline is cut in the chunk's edge buffer; empty unless
    /// the upload was asked for them and kept the model in one chunk.
    pub marks: Vec<(u32, u32)>,
}

/// An axis-aligned box in a model's space, the unit of the view-frustum cull.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct NodeBounds {
    /// Corner holding the smallest value on every axis.
    pub min: Vec3,
    /// Corner holding the largest value on every axis.
    pub max: Vec3,
}

impl NodeBounds {
    /// The box around a slice's vertices, or `None` when there are none.
    fn around<'a>(vertices: impl Iterator<Item = &'a SodVertex>) -> Option<Self> {
        let mut box_: Option<Self> = None;
        for vertex in vertices {
            let point = Vec3::from_array(vertex.position);
            box_ = Some(match box_ {
                None => Self {
                    min: point,
                    max: point,
                },
                Some(current) => Self {
                    min: current.min.min(point),
                    max: current.max.max(point),
                },
            });
        }
        box_
    }

    /// This box with *other*'s extent added, if there is one.
    fn union(self, other: Option<Self>) -> Self {
        match other {
            Some(other) => Self {
                min: self.min.min(other.min),
                max: self.max.max(other.max),
            },
            None => self,
        }
    }
}

/// Every node's box: its own slices' vertices and its descendants', as the vertex shader
/// takes them, in the model's space.
///
/// A node's `local_matrix` is not applied: the draw does not apply it either (a slice is
/// drawn with its model's one matrix), so the box is around the vertices that are drawn. The
/// arena numbers a parent before its children (`SodModelIr::allocate_node`), so one pass
/// backward adds each subtree's box to its parent's.
fn node_bounds(ir: &SodModelIr) -> Vec<Option<NodeBounds>> {
    let mut bounds: Vec<Option<NodeBounds>> = vec![None; ir.nodes.len()];
    for mesh in ir.meshes() {
        let Some(own) = NodeBounds::around(mesh.vertices.iter()) else {
            continue;
        };
        if let Some(slot) = bounds.get_mut(mesh.node.id.0 as usize) {
            *slot = Some(own.union(*slot));
        }
    }
    for (n, node) in ir.nodes.iter().enumerate().rev() {
        let Some(subtree) = bounds.get(n).copied().flatten() else {
            continue;
        };
        let Some(parent) = node
            .parent
            .and_then(|parent| bounds.get_mut(parent.0 as usize))
        else {
            continue;
        };
        *parent = Some(subtree.union(*parent));
    }
    bounds
}

/// The box around every root's subtree, from [`node_bounds`]; `None` when no root has one.
fn model_bounds(roots: &[NodeId], bounds: &[Option<NodeBounds>]) -> Option<NodeBounds> {
    roots
        .iter()
        .filter_map(|root| bounds.get(root.0 as usize).copied().flatten())
        .reduce(|all, root| all.union(Some(root)))
}

/// Whether any of `bounds` is inside `view_proj`'s view frustum; `false` only when the box lies
/// wholly outside one plane, so a box that touches the frustum is kept.
///
/// `bounds` is in the space `view_proj` takes to clip space. The six planes are its rows, for a
/// clip space whose depth runs over `[0, w]` as `glam::rh::proj::directx` gives and the vertex
/// shader multiplies by: left `w + x`, right `w - x`, bottom `w + y`, top `w - y`, far `z` and
/// near `w - z`, depth being reversed. Under the infinite perspective clip z is the constant
/// near distance, so the far plane keeps every box in front of the eye
/// (`docs/adr/0054-depth-is-reversed-and-infinite.md`).
///
/// The test has no margin: `view_proj` is an `f32` product the GPU does not form, so a box
/// within rounding of a plane can fall either way; such a box covers no more than a
/// sub-pixel sliver of the view.
pub(crate) fn frustum_keeps(view_proj: Mat4, bounds: NodeBounds) -> bool {
    let [x, y, z, w] = [
        view_proj.row(0),
        view_proj.row(1),
        view_proj.row(2),
        view_proj.row(3),
    ];
    let planes = [w + x, w - x, w + y, w - y, z, w - z];
    planes.into_iter().all(|plane| {
        // The corner farthest along the plane's inward normal: when even it is outside, the
        // whole box is.
        let corner = Vec3::new(
            if plane.x >= 0.0 {
                bounds.max.x
            } else {
                bounds.min.x
            },
            if plane.y >= 0.0 {
                bounds.max.y
            } else {
                bounds.min.y
            },
            if plane.z >= 0.0 {
                bounds.max.z
            } else {
                bounds.min.z
            },
        );
        plane.truncate().dot(corner) + plane.w >= 0.0
    })
}

/// Polygonal geometry slice pointing into consolidated GPU vertex and index buffers.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct GpuMeshSlice {
    /// Chunk (vertex/index buffer pair) of [`GpuModel::chunks`] the slice is drawn from.
    pub chunk: u32,
    /// Base vertex `draw_indexed` adds to each index: 0 for an unsplit model, whose indices
    /// already address the whole vertex buffer, or a run's first vertex in its chunk.
    pub vertex_offset: i32,
    /// First index of the slice within the consolidated index buffer.
    pub index_offset: u32,
    /// Number of indices in the slice (three per triangle).
    pub index_count: u32,
    /// Whether the slice is a coplanar decal drawn through the depth-bias pipeline `[I5]`.
    pub is_decal: bool,
    /// First index of the slice's outline in its chunk's edge buffer.
    pub edge_offset: u32,
    /// Number of outline indices of the slice (two per edge); zero when it has no outline.
    pub edge_count: u32,
}

/// Which vertices' triangles a model's outline takes, and the index offsets a slice may be
/// cut at ([`GpuModel::from_ir_outlined`]).
type Outlines<'a> = (fn(&SodVertex) -> bool, &'a [u32]);

/// GPU-resident representation of a transpiled `SodModelIr`.
#[derive(Debug)]
pub struct GpuModel {
    /// Model name identifier.
    pub name: String,
    /// Vertex/index buffer pairs; one unless the model exceeds `max_buffer_size`.
    pub chunks: Vec<GpuChunk>,
    /// Total vertex count of the source model.
    pub vertex_count: u32,
    /// Total index count of the source model.
    pub index_count: u32,
    /// Flat arena of scene nodes per `[I2]`.
    pub nodes: Vec<GpuNode>,
    /// Root node IDs.
    pub root_nodes: Vec<NodeId>,
    /// Box around every vertex the model can draw, in its own space: the union of its roots'
    /// [`GpuNode::bounds`], or `None` when it has no mesh.
    pub bounds: Option<NodeBounds>,
}

impl GpuModel {
    /// Uploads a `SodModelIr` into GPU buffers.
    ///
    /// Each vertex's apex ([`Outlined`]) is its own position, so no line corner is culled.
    pub fn from_ir(device: &wgpu::Device, queue: &wgpu::Queue, ir: &SodModelIr) -> Self {
        Self::upload(device, queue, ir, &own_positions(ir), None)
    }

    /// Uploads an outlined shape with its apexes, so its outline corners cull with the
    /// triangles their edges bound.
    pub(crate) fn from_outlined(
        device: &wgpu::Device,
        queue: &wgpu::Queue,
        shape: &Outlined,
    ) -> Self {
        Self::upload(device, queue, &shape.ir, &shape.apex, None)
    }

    /// Like [`Self::from_ir`], and gives each mesh slice its outline for [`Self::draw_edges`]:
    /// every edge exactly one of the slice's triangles uses, as two indices into the same
    /// vertices, so it costs eight bytes an edge. Triangles with a corner `outlined` rejects
    /// are left out. A slice split over chunks gets the outline of the unsplit slice: each run
    /// draws its share of it.
    ///
    /// `marks` are offsets in `ir.indices`, ascending, where [`Self::cut`] may cut a slice; a
    /// cut keeps the outline whole only where no edge is shared across it.
    pub fn from_ir_outlined(
        device: &wgpu::Device,
        queue: &wgpu::Queue,
        ir: &SodModelIr,
        outlined: fn(&SodVertex) -> bool,
        marks: &[u32],
    ) -> Self {
        Self::upload(
            device,
            queue,
            ir,
            &own_positions(ir),
            Some((outlined, marks)),
        )
    }

    /// Uploads `ir`; `outlined` is [`Self::from_ir_outlined`]'s filter and marks.
    fn upload(
        device: &wgpu::Device,
        queue: &wgpu::Queue,
        ir: &SodModelIr,
        apex: &[[f32; 3]],
        outlined: Option<Outlines<'_>>,
    ) -> Self {
        let limit = device.limits().max_buffer_size;
        // A buffer larger than the address space is capped at what it can address.
        let max_vertices =
            usize::try_from(limit / size_of::<SodVertex>() as u64).unwrap_or(usize::MAX);
        let max_indices = usize::try_from(limit / size_of::<u32>() as u64).unwrap_or(usize::MAX);
        // One source per mesh slice, keyed by node so the planned slices can be handed
        // back to the same nodes. `meshes()` already skips a node whose window is unsafe.
        // `meshes()` walks the nodes in arena order, so each node takes the next mesh if
        // that mesh is its own.
        let mut meshes = ir.meshes().peekable();
        let sources: Vec<Option<SourceSlice>> = ir
            .nodes
            .iter()
            .map(|node| {
                let mesh = meshes.next_if(|mesh| std::ptr::eq(mesh.node, node))?;
                Some(SourceSlice {
                    index_offset: mesh.index_offset,
                    index_count: arena_index(mesh.indices.len()),
                    is_decal: mesh.is_decal(),
                })
            })
            .collect();
        let mesh_sources: Vec<SourceSlice> = sources.iter().flatten().copied().collect();
        let mut plan = plan_upload(
            ir.vertices.len(),
            &ir.indices,
            &mesh_sources,
            max_vertices,
            max_indices,
        );
        let (edges, mut marks) = match outlined {
            Some((keep, marks)) => plan_edges(&mut plan, ir, keep, marks),
            None => (vec![Vec::new(); plan.chunks.len()], Vec::new()),
        };
        let chunks = plan
            .chunks
            .iter()
            .zip(&edges)
            .enumerate()
            .map(|(n, (chunk, edges))| GpuChunk::upload(device, queue, ir, apex, n, chunk, edges))
            .collect();

        // Translate nodes into GpuNode flat arena
        marks.resize_with(plan.slices.len(), Vec::new);
        let mut planned = plan.slices.into_iter().zip(marks);
        let bounds = node_bounds(ir);
        let nodes = ir
            .nodes
            .iter()
            .zip(&sources)
            .enumerate()
            .map(|(n, (node, source))| {
                let (meshes, marks) = source.and_then(|_| planned.next()).unwrap_or_default();
                GpuNode {
                    id: node.id,
                    name: node.name.clone(),
                    parent: node.parent,
                    children: node.children.clone(),
                    local_matrix: Mat4::from_cols_array(&node.local_matrix),
                    visibility: node.visibility,
                    meshes,
                    bounds: bounds.get(n).copied().flatten(),
                    marks,
                }
            })
            .collect();

        let bounds = model_bounds(&ir.root_nodes, &bounds);
        Self {
            name: ir.name.clone(),
            chunks,
            vertex_count: arena_index(ir.vertices.len()),
            index_count: arena_index(ir.indices.len()),
            nodes,
            root_nodes: ir.root_nodes.clone(),
            bounds,
        }
    }

    /// Overwrites the vertices and apexes with `shape`'s, keeping the indices, nodes and slices, and returns
    /// true; returns false, writing nothing, when `shape`'s vertex or index count differs from
    /// the uploaded model's.
    ///
    /// `shape` must have the indices and nodes the model was uploaded from: only the counts are
    /// checked here, and other indices at equal counts would bind triangles to the wrong
    /// vertices. For a model whose geometry stays and whose vertex attributes change, such as
    /// an actor's shape decoded under another light: it costs one buffer write per chunk
    /// instead of a new model's buffers.
    pub(crate) fn rewrite_vertices(&self, queue: &wgpu::Queue, shape: &Outlined) -> bool {
        let ir = &shape.ir;
        if arena_index(ir.vertices.len()) != self.vertex_count
            || arena_index(ir.indices.len()) != self.index_count
        {
            return false;
        }
        for chunk in &self.chunks {
            chunk.rewrite_vertices(queue, &ir.vertices, &shape.apex);
        }
        true
    }

    /// Evaluates visibility and collects visible mesh slices split by decal pass flag.
    ///
    /// `eye` is the camera position in this model's space, for
    /// [`VisibilityCondition::FacesEye`]. `view` is the camera that tests
    /// [`VisibilityCondition::LodBranch`], [`VisibilityCondition::BeyondDepth`] and
    /// [`VisibilityCondition::ScaleReach`] gates, whose points must then be in its space;
    /// without one every subtree branch, every far section and every far object is drawn
    /// and no stand-in is.
    ///
    /// Base slices come last sibling first, decal slices in the nodes' own order: the base
    /// pipeline's `Greater` keeps the first draw of an exact depth tie and the decal pipeline's
    /// `GreaterEqual` the last, so both let `PLAYONE`'s later sibling win the tie.
    pub fn collect_visible_meshes(
        &self,
        state_mask: u16,
        distance_to_cam: f32,
        eye: Vec3,
        view: Option<&CameraTransform>,
    ) -> (Vec<GpuMeshSlice>, Vec<GpuMeshSlice>) {
        VisibleWalk {
            nodes: &self.nodes,
            roots: &self.root_nodes,
            state_mask,
            dist_sq: distance_to_cam * distance_to_cam,
            eye,
            view,
            view_proj: None,
        }
        .collect()
    }

    /// Like [`Self::collect_visible_meshes`] for the static world, with the slices of its
    /// [`GROUND_NODE`] nodes taken out first, in the nodes' own order: ground, base and decal
    /// slices. A ground slice is drawn over whatever is there, so the walk's order is the
    /// order the flat ground is painted in (`stunt_core::world::GROUND_NODE`).
    ///
    /// `view_proj` takes a world vertex to clip space: the camera's `rotation_proj` composed
    /// with the world's eye-relative model matrix ([`crate::camera::eye_relative_matrix`]). A node whose box it cannot
    /// see is skipped with its subtree (`frustum_keeps`), which draws no fewer pixels because
    /// an off-screen slice covers none, and keeps the order of the slices that survive.
    ///
    /// Each base and decal slice comes with its node, so a caller can draw some apart.
    #[expect(
        clippy::type_complexity,
        reason = "the three slice lists of one walk, the last two with their nodes"
    )]
    pub fn collect_world_meshes(
        &self,
        eye: Vec3,
        view: Option<&CameraTransform>,
        view_proj: Mat4,
    ) -> (
        Vec<GpuMeshSlice>,
        Vec<(NodeId, GpuMeshSlice)>,
        Vec<(NodeId, GpuMeshSlice)>,
    ) {
        VisibleWalk {
            nodes: &self.nodes,
            roots: &self.root_nodes,
            state_mask: 0,
            dist_sq: 0.0,
            eye,
            view,
            view_proj: Some(view_proj),
        }
        .collect_world()
    }

    /// Gives each chunk `runs`, the source model's prop runs in its vertex order, in the
    /// chunk's own vertex numbering ([`chunk_prop_runs`]), as a bind group of `layout` that
    /// [`Self::draw_slices`] and [`Self::draw_edges`] bind with the chunk.
    pub fn attach_prop_runs(
        &mut self,
        device: &wgpu::Device,
        layout: &wgpu::BindGroupLayout,
        runs: &[PropRun],
    ) {
        for chunk in &mut self.chunks {
            let table = chunk_prop_runs(runs, &chunk.vertex_ranges);
            chunk.prop_runs = Some(prop_runs_group(device, layout, &table));
        }
    }

    /// The part `start..end` of the index arena of node `node`'s one slice, with its share
    /// of the slice's outline; `None` unless both ends are among the node's marks
    /// ([`Self::from_ir_outlined`]) and `start <= end`.
    #[must_use]
    pub fn cut(&self, node: NodeId, start: u32, end: u32) -> Option<GpuMeshSlice> {
        let node = self.nodes.get(node.0 as usize)?;
        let [whole] = node.meshes.as_slice() else {
            return None;
        };
        let edge_at = |at: u32| {
            let found = node.marks.binary_search_by_key(&at, |&(index, _)| index);
            found
                .ok()
                .and_then(|i| node.marks.get(i))
                .map(|&(_, edge)| edge)
        };
        let (from, to) = (edge_at(start)?, edge_at(end)?);
        (start <= end).then_some(GpuMeshSlice {
            index_offset: start,
            index_count: end - start,
            edge_offset: from,
            edge_count: to.checked_sub(from)?,
            ..*whole
        })
    }

    /// Encodes `meshes` into `rpass`, binding each slice's chunk buffers when it changes.
    ///
    /// The pipeline and bind groups must already be set.
    pub fn draw_slices(&self, rpass: &mut wgpu::RenderPass<'_>, meshes: &[GpuMeshSlice]) {
        let mut bound = None;
        for mesh in meshes {
            #[expect(
                clippy::indexing_slicing,
                reason = "draw slices come from this upload's plan, which numbers only its own chunks"
            )]
            let chunk = &self.chunks[mesh.chunk as usize];
            if bound != Some(mesh.chunk) {
                rpass.set_vertex_buffer(0, chunk.vertex_buffer.slice(..));
                rpass.set_vertex_buffer(1, chunk.apex_buffer.slice(..));
                rpass.set_index_buffer(chunk.index_buffer.slice(..), wgpu::IndexFormat::Uint32);
                if let Some(runs) = &chunk.prop_runs {
                    rpass.set_bind_group(PROP_RUNS_GROUP, runs, &[]);
                }
                bound = Some(mesh.chunk);
            }
            rpass.draw_indexed(
                mesh.index_offset..(mesh.index_offset + mesh.index_count),
                mesh.vertex_offset,
                0..1,
            );
        }
    }

    /// Encodes the outlines of `meshes` into `rpass` as a line list, binding each slice's
    /// chunk buffers when it changes; slices without an outline are skipped.
    ///
    /// The pipeline (a `LineList` one) and bind groups must already be set.
    pub fn draw_edges(&self, rpass: &mut wgpu::RenderPass<'_>, meshes: &[GpuMeshSlice]) {
        let mut bound = None;
        for mesh in meshes.iter().filter(|m| m.edge_count > 0) {
            #[expect(
                clippy::indexing_slicing,
                reason = "draw slices come from this upload's plan, which numbers only its own chunks"
            )]
            let chunk = &self.chunks[mesh.chunk as usize];
            if bound != Some(mesh.chunk) {
                rpass.set_vertex_buffer(0, chunk.vertex_buffer.slice(..));
                rpass.set_vertex_buffer(1, chunk.apex_buffer.slice(..));
                rpass.set_index_buffer(chunk.edges.slice(..), wgpu::IndexFormat::Uint32);
                if let Some(runs) = &chunk.prop_runs {
                    rpass.set_bind_group(PROP_RUNS_GROUP, runs, &[]);
                }
                bound = Some(mesh.chunk);
            }
            rpass.draw_indexed(
                mesh.edge_offset..(mesh.edge_offset + mesh.edge_count),
                mesh.vertex_offset,
                0..1,
            );
        }
    }
}

/// Fills in each planned slice's outline and returns each chunk's edge indices, then each
/// slice's `marks` (offsets in `ir.indices`, ascending) that lie within it, each with its
/// edge offset: none when the plan splits the model, whose slices' indices are rebased.
#[expect(
    clippy::type_complexity,
    reason = "the edges and the marks are planned in one pass over the same runs"
)]
fn plan_edges(
    plan: &mut UploadPlan,
    ir: &SodModelIr,
    keep: fn(&SodVertex) -> bool,
    marks: &[u32],
) -> (Vec<Vec<u32>>, Vec<Vec<(u32, u32)>>) {
    let unsplit = matches!(plan.chunks.as_slice(), [only] if only.indices.is_none());
    let mut slice_marks = Vec::with_capacity(plan.slices.len());
    // A split chunk's vertices, in buffer order, as source vertex numbers.
    let local: Vec<Option<Vec<usize>>> = plan
        .chunks
        .iter()
        .map(|c| {
            c.indices
                .as_ref()
                .map(|_| c.vertex_ranges.iter().flat_map(Clone::clone).collect())
        })
        .collect();
    let mut edges = vec![Vec::new(); plan.chunks.len()];
    for runs in &mut plan.slices {
        // A run's source vertex number for each of its chunk indices.
        let source_of = |run: &GpuMeshSlice, i: u32| -> Option<u32> {
            let at = run.vertex_offset.cast_unsigned().saturating_add(i) as usize;
            let local = local.get(run.chunk as usize)?;
            let source = local.as_ref().map_or(Some(at), |l| l.get(at).copied())?;
            u32::try_from(source).ok()
        };
        let triangles_of = |run: &GpuMeshSlice| -> Option<&[u32]> {
            let chunk = plan.chunks.get(run.chunk as usize)?;
            let indices = chunk.indices.as_deref().unwrap_or(&ir.indices);
            let start = run.index_offset as usize;
            indices.get(start..start + run.index_count as usize)
        };
        let outlined = |source: Option<u32>| {
            source
                .and_then(|s| ir.vertices.get(s as usize))
                .is_some_and(keep)
        };
        // The slice's boundary over all its runs, in source vertex numbers: an edge along a
        // cut is used once in each of two runs, so it is not a boundary of the slice. An
        // unsplit slice has one run, whose own boundary is the slice's.
        let boundary: Option<std::collections::HashSet<(u32, u32)>> = (runs.len() > 1).then(|| {
            let whole: Vec<u32> = runs
                .iter()
                .filter_map(|run| {
                    let tris = triangles_of(run)?;
                    tris.iter()
                        .map(|&i| source_of(run, i))
                        .collect::<Option<Vec<_>>>()
                })
                .flatten()
                .collect();
            crate::outline::boundary_edges(&whole, |s| outlined(Some(s)))
                .into_iter()
                .map(|[p, q]| (p.min(q), p.max(q)))
                .collect()
        });
        let mut found_marks = Vec::new();
        for run in runs.iter_mut() {
            let (Some(triangles), Some(out)) =
                (triangles_of(run), edges.get_mut(run.chunk as usize))
            else {
                continue;
            };
            let mut found =
                crate::outline::numbered_boundary_edges(triangles, |i| outlined(source_of(run, i)));
            if let Some(boundary) = &boundary {
                found.retain(
                    |&([p, q], _)| match (source_of(run, p), source_of(run, q)) {
                        (Some(p), Some(q)) => boundary.contains(&(p.min(q), p.max(q))),
                        _ => false,
                    },
                );
            }
            run.edge_offset = arena_index(out.len());
            run.edge_count = arena_index(2 * found.len());
            if unsplit && boundary.is_none() {
                // Edges come in first-use order, so the ones before a mark are a prefix.
                let (start, end) = (run.index_offset, run.index_offset + run.index_count);
                let first = marks.partition_point(|&m| m < start);
                for &mark in marks.iter().skip(first).take_while(|&&m| m <= end) {
                    let triangle = ((mark - start) / 3) as usize;
                    let before = found.partition_point(|&(_, number)| number < triangle);
                    found_marks.push((mark, run.edge_offset + arena_index(2 * before)));
                }
            }
            out.extend(found.into_iter().flat_map(|(edge, _)| edge));
        }
        slice_marks.push(found_marks);
    }
    (edges, slice_marks)
}

/// One vertex/index buffer pair of a [`GpuModel`].
#[derive(Debug)]
pub struct GpuChunk {
    /// Vertex buffer of the chunk.
    pub vertex_buffer: wgpu::Buffer,
    /// Each vertex's apex ([`Outlined`]), the second vertex stream, in `vertex_buffer`'s order.
    pub apex_buffer: wgpu::Buffer,
    /// 32-bit index buffer of the chunk.
    pub index_buffer: wgpu::Buffer,
    /// 32-bit line-list index buffer of the chunk's outlines, into the same vertices.
    pub edges: wgpu::Buffer,
    /// The source vertex ranges copied back to back into `vertex_buffer`.
    pub vertex_ranges: Vec<Range<usize>>,
    /// The model's prop runs in this chunk's vertex numbering, bound at [`PROP_RUNS_GROUP`]
    /// with the chunk's buffers; `None` unless [`GpuModel::attach_prop_runs`] gave them.
    pub prop_runs: Option<wgpu::BindGroup>,
}

impl GpuChunk {
    fn upload(
        device: &wgpu::Device,
        queue: &wgpu::Queue,
        ir: &SodModelIr,
        apex: &[[f32; 3]],
        n: usize,
        plan: &ChunkPlan,
        edges: &[u32],
    ) -> Self {
        // Chunk 0 keeps the labels of an unsplit model.
        let suffix = if n == 0 {
            String::new()
        } else {
            format!("_{n}")
        };
        let vertex_size = size_of::<SodVertex>();
        let vertex_buffer = device.create_buffer(&wgpu::BufferDescriptor {
            label: Some(&format!("{}_vertex_buffer{suffix}", ir.name)),
            size: (plan.vertex_count.max(1) * vertex_size) as u64,
            usage: wgpu::BufferUsages::VERTEX | wgpu::BufferUsages::COPY_DST,
            mapped_at_creation: false,
        });
        let mut offset = 0;
        for range in &plan.vertex_ranges {
            #[expect(
                clippy::indexing_slicing,
                reason = "the plan's vertex ranges are windows of `ir.meshes()`, inside `ir.vertices`"
            )]
            let bytes: &[u8] = bytemuck::cast_slice(&ir.vertices[range.clone()]);
            if !bytes.is_empty() {
                queue.write_buffer(&vertex_buffer, offset, bytes);
            }
            offset += bytes.len() as u64;
        }
        let apex_buffer = device.create_buffer(&wgpu::BufferDescriptor {
            label: Some(&format!("{}_apex_buffer{suffix}", ir.name)),
            size: (plan.vertex_count.max(1) * size_of::<[f32; 3]>()) as u64,
            usage: wgpu::BufferUsages::VERTEX | wgpu::BufferUsages::COPY_DST,
            mapped_at_creation: false,
        });
        write_windows(queue, &apex_buffer, apex, &plan.vertex_ranges);

        let indices = plan.indices.as_deref().unwrap_or(&ir.indices);
        let index_bytes: &[u8] = bytemuck::cast_slice(indices);
        let index_buffer = device.create_buffer(&wgpu::BufferDescriptor {
            label: Some(&format!("{}_index_buffer{suffix}", ir.name)),
            size: (index_bytes.len().max(size_of::<u32>())) as u64,
            usage: wgpu::BufferUsages::INDEX | wgpu::BufferUsages::COPY_DST,
            mapped_at_creation: false,
        });
        if !index_bytes.is_empty() {
            queue.write_buffer(&index_buffer, 0, index_bytes);
        }
        let edge_bytes: &[u8] = bytemuck::cast_slice(edges);
        let edge_buffer = device.create_buffer(&wgpu::BufferDescriptor {
            label: Some(&format!("{}_edge_buffer{suffix}", ir.name)),
            size: (edge_bytes.len().max(size_of::<u32>())) as u64,
            usage: wgpu::BufferUsages::INDEX | wgpu::BufferUsages::COPY_DST,
            mapped_at_creation: false,
        });
        if !edge_bytes.is_empty() {
            queue.write_buffer(&edge_buffer, 0, edge_bytes);
        }
        Self {
            vertex_buffer,
            apex_buffer,
            index_buffer,
            edges: edge_buffer,
            vertex_ranges: plan.vertex_ranges.clone(),
            prop_runs: None,
        }
    }

    /// Writes `vertices`' windows of this chunk into its vertex buffer with one write, since
    /// each write allocates a staging buffer (`research/parity/lavapipe-render-time.md`).
    fn rewrite_vertices(&self, queue: &wgpu::Queue, vertices: &[SodVertex], apex: &[[f32; 3]]) {
        write_windows(queue, &self.apex_buffer, apex, &self.vertex_ranges);
        // An unsplit chunk is one window: write it straight from the source.
        if let [range] = self.vertex_ranges.as_slice() {
            if let Some(window) = vertices.get(range.clone()).filter(|w| !w.is_empty()) {
                queue.write_buffer(&self.vertex_buffer, 0, bytemuck::cast_slice(window));
            }
            return;
        }
        let mut packed = Vec::new();
        for range in &self.vertex_ranges {
            let Some(window) = vertices.get(range.clone()) else {
                return;
            };
            packed.extend_from_slice(window);
        }
        if !packed.is_empty() {
            queue.write_buffer(&self.vertex_buffer, 0, bytemuck::cast_slice(&packed));
        }
    }
}

/// Each of `ir`'s vertices' own position, the apex that culls no line corner.
fn own_positions(ir: &SodModelIr) -> Vec<[f32; 3]> {
    ir.vertices.iter().map(|v| v.position).collect()
}

/// Writes `source`'s `ranges` back to back into `buffer` with one write; writes nothing when
/// a range leaves `source`.
fn write_windows<T: bytemuck::Pod>(
    queue: &wgpu::Queue,
    buffer: &wgpu::Buffer,
    source: &[T],
    ranges: &[Range<usize>],
) {
    let packed = packed_windows(source, ranges);
    if let Some(packed) = packed.filter(|p| !p.is_empty()) {
        queue.write_buffer(buffer, 0, bytemuck::cast_slice(&packed));
    }
}

/// `source`'s `ranges` back to back, or `None` when a range leaves `source`.
fn packed_windows<T: Copy>(source: &[T], ranges: &[Range<usize>]) -> Option<Vec<T>> {
    let mut packed = Vec::new();
    for range in ranges {
        packed.extend_from_slice(source.get(range.clone())?);
    }
    Some(packed)
}

/// A mesh node's slice as the IR stores it: its indices address the whole vertex buffer.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) struct SourceSlice {
    pub index_offset: u32,
    pub index_count: u32,
    pub is_decal: bool,
}

/// Contents of one chunk.
#[derive(Debug, Default, PartialEq, Eq)]
pub(crate) struct ChunkPlan {
    /// Source vertex ranges, copied back to back from the start of the vertex buffer.
    pub vertex_ranges: Vec<Range<usize>>,
    /// Total vertices of `vertex_ranges`.
    pub vertex_count: usize,
    /// Rebased indices, or `None` to upload the source indices unchanged.
    pub indices: Option<Vec<u32>>,
}

impl ChunkPlan {
    fn split() -> Self {
        Self {
            indices: Some(Vec::new()),
            ..Self::default()
        }
    }

    fn index_count(&self) -> usize {
        self.indices.as_ref().map_or(0, Vec::len)
    }
}

/// How a model's geometry is laid out over chunks.
#[derive(Debug, PartialEq, Eq)]
pub(crate) struct UploadPlan {
    pub chunks: Vec<ChunkPlan>,
    /// Draw slices of each source slice, in the order given.
    pub slices: Vec<Vec<GpuMeshSlice>>,
}

/// Lays out a model over chunks of at most `max_vertices` vertices and `max_indices` indices.
///
/// A model within both budgets is one chunk holding the source buffers unchanged. Otherwise
/// each source slice is cut into runs of whole triangles in draw order; a run copies the
/// contiguous vertex window its triangles reference and rebases their indices to it, and a
/// chunk takes runs until the next triangle would overflow it.
#[expect(
    clippy::expect_used,
    reason = "`chunks` is seeded with a first chunk before `last()` is read"
)]
pub(crate) fn plan_upload(
    vertex_count: usize,
    indices: &[u32],
    sources: &[SourceSlice],
    max_vertices: usize,
    max_indices: usize,
) -> UploadPlan {
    if vertex_count <= max_vertices && indices.len() <= max_indices {
        let slices = sources
            .iter()
            .map(|s| {
                // The IR's indices are absolute, so the whole buffer is drawn from vertex 0.
                vec![GpuMeshSlice {
                    chunk: 0,
                    vertex_offset: 0,
                    index_offset: s.index_offset,
                    index_count: s.index_count,
                    is_decal: s.is_decal,
                    edge_offset: 0,
                    edge_count: 0,
                }]
            })
            .collect();
        let whole = ChunkPlan {
            vertex_ranges: std::iter::once(0..vertex_count).collect(),
            vertex_count,
            indices: None,
        };
        return UploadPlan {
            chunks: vec![whole],
            slices,
        };
    }

    let mut chunks = vec![ChunkPlan::split()];
    let mut slices = Vec::with_capacity(sources.len());
    for source in sources {
        let mut out = Vec::new();
        // The IR owns its windows: `meshes()` only hands out slices contained in the buffers,
        // and every slice is whole triangles, so no triangle needs checking or dropping.
        let start = source.index_offset as usize;
        let end = start + source.index_count as usize;
        // The open run: its source vertex window and its triangles as source vertices.
        let mut run: Option<(Range<usize>, Vec<[usize; 3]>)> = None;
        #[expect(
            clippy::indexing_slicing,
            reason = "sources are windows of `SodModelIr::meshes`, which lie inside `indices`"
        )]
        let window = &indices[start..end];
        for tri in window.as_chunks::<3>().0 {
            let tri = tri.map(|v| v as usize);
            let lo = tri.into_iter().min().unwrap_or(0);
            let hi = tri.into_iter().max().unwrap_or(0) + 1;
            let last = chunks.last().expect("a split plan starts with a chunk");
            let (used_v, used_i) = (last.vertex_count, last.index_count());
            if let Some((window, tris)) = &mut run {
                let grown = window.start.min(lo)..window.end.max(hi);
                if used_v + grown.len() <= max_vertices
                    && used_i + 3 * (tris.len() + 1) <= max_indices
                {
                    *window = grown;
                    tris.push(tri);
                    continue;
                }
            }
            if let Some((window, tris)) = run.take() {
                out.push(flush_run(&mut chunks, source.is_decal, window, &tris));
            }
            let last = chunks.last().expect("a split plan starts with a chunk");
            let room = last.vertex_count + (hi - lo) <= max_vertices
                && last.index_count() + 3 <= max_indices;
            if last.vertex_count > 0 && !room {
                chunks.push(ChunkPlan::split());
            }
            run = Some((lo..hi, vec![tri]));
        }
        if let Some((window, tris)) = run.take() {
            out.push(flush_run(&mut chunks, source.is_decal, window, &tris));
        }
        slices.push(out);
    }
    UploadPlan { chunks, slices }
}

/// `runs`, in source vertex order, as `[first, end, shape id + 1]` in the vertex numbering of
/// a chunk that holds the source vertices `ranges` back to back: each run is cut to every
/// range it meets and moved to where that range lies in the chunk. A run that meets no range
/// is left out.
pub(crate) fn chunk_prop_runs(runs: &[PropRun], ranges: &[Range<usize>]) -> Vec<[u32; 3]> {
    let mut table = Vec::new();
    let mut at = 0usize;
    for range in ranges {
        let from = runs.partition_point(|run| run.end as usize <= range.start);
        for run in runs
            .iter()
            .skip(from)
            .take_while(|run| (run.first as usize) < range.end)
        {
            // Both ends lie in `range`, so neither subtraction can wrap.
            let first = (run.first as usize).max(range.start) - range.start;
            let end = (run.end as usize).min(range.end) - range.start;
            table.push([
                arena_index(at.saturating_add(first)),
                arena_index(at.saturating_add(end)),
                u32::from(run.shape).saturating_add(1),
            ]);
        }
        at = at.saturating_add(range.len());
    }
    table
}

/// A bind group of `layout` holding `table` ([`chunk_prop_runs`]) as its storage buffer; an
/// empty table holds one run that covers no vertex, as a binding cannot be empty.
pub(crate) fn prop_runs_group(
    device: &wgpu::Device,
    layout: &wgpu::BindGroupLayout,
    table: &[[u32; 3]],
) -> wgpu::BindGroup {
    let contents: &[[u32; 3]] = if table.is_empty() { &[[0; 3]] } else { table };
    let buffer = device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
        label: Some("stunt_prop_runs"),
        contents: bytemuck::cast_slice(contents),
        usage: wgpu::BufferUsages::STORAGE,
    });
    device.create_bind_group(&wgpu::BindGroupDescriptor {
        label: Some("stunt_prop_runs"),
        layout,
        entries: &[wgpu::BindGroupEntry {
            binding: 0,
            resource: buffer.as_entire_binding(),
        }],
    })
}

/// A chunk's vertex count as the `i32` base vertex `draw_indexed` takes.
#[expect(
    clippy::cast_possible_truncation,
    clippy::cast_possible_wrap,
    reason = "a chunk holds one vertex buffer's worth, far below i32::MAX vertices"
)]
const fn base_vertex(count: usize) -> i32 {
    count as i32
}

/// Appends a run to the last chunk and returns its draw slice.
#[expect(
    clippy::expect_used,
    reason = "`plan_upload` seeds `chunks` with a first chunk before any run is flushed"
)]
fn flush_run(
    chunks: &mut [ChunkPlan],
    is_decal: bool,
    window: Range<usize>,
    tris: &[[usize; 3]],
) -> GpuMeshSlice {
    let (n, chunk) = chunks
        .iter_mut()
        .enumerate()
        .last()
        .expect("a split plan starts with a chunk");
    let indices = chunk.indices.get_or_insert_with(Vec::new);
    let slice = GpuMeshSlice {
        chunk: arena_index(n),
        vertex_offset: base_vertex(chunk.vertex_count),
        index_offset: arena_index(indices.len()),
        index_count: arena_index(3 * tris.len()),
        is_decal,
        edge_offset: 0,
        edge_count: 0,
    };
    indices.extend(
        tris.iter()
            .flatten()
            .map(|&v| arena_index(v - window.start)),
    );
    chunk.vertex_count += window.len();
    chunk.vertex_ranges.push(window);
    slice
}

/// One visibility pass over a model's node arena from `roots`, for
/// [`GpuModel::collect_visible_meshes`].
struct VisibleWalk<'a> {
    nodes: &'a [GpuNode],
    roots: &'a [NodeId],
    state_mask: u16,
    dist_sq: f32,
    eye: Vec3,
    view: Option<&'a CameraTransform>,
    /// The matrix the vertex shader takes a vertex of the model to clip space by, for the
    /// world's view-frustum cull; `None` draws every node the gates keep.
    view_proj: Option<Mat4>,
}

impl VisibleWalk<'_> {
    /// The visible base slices, last sibling first, and decal slices, in draw order.
    fn collect(&self) -> (Vec<GpuMeshSlice>, Vec<GpuMeshSlice>) {
        let (_, base, decals) = self.split(|_| false);
        let untag = |tagged: Vec<(NodeId, GpuMeshSlice)>| tagged.into_iter().map(|(_, m)| m);
        (untag(base).collect(), untag(decals).collect())
    }

    /// The visible ground slices in draw order, then [`Self::collect`]'s base and decal
    /// slices of the other nodes, each with its node.
    #[expect(
        clippy::type_complexity,
        reason = "the three slice lists of one walk, the last two with their nodes"
    )]
    fn collect_world(
        &self,
    ) -> (
        Vec<GpuMeshSlice>,
        Vec<(NodeId, GpuMeshSlice)>,
        Vec<(NodeId, GpuMeshSlice)>,
    ) {
        self.split(|node| node.name == GROUND_NODE)
    }

    /// The visible slices of the nodes `is_ground` picks, in draw order, then the others'
    /// base slices, last sibling first, and decal slices, in draw order, each with its node.
    #[expect(
        clippy::type_complexity,
        reason = "the three slice lists of one walk, the last two with their nodes"
    )]
    fn split(
        &self,
        is_ground: impl Fn(&GpuNode) -> bool,
    ) -> (
        Vec<GpuMeshSlice>,
        Vec<(NodeId, GpuMeshSlice)>,
        Vec<(NodeId, GpuMeshSlice)>,
    ) {
        let mut ground_meshes = Vec::new();
        let mut base_meshes = Vec::new();
        let mut decal_meshes = Vec::new();
        self.walk(false, |node, mesh| {
            if !is_ground(node) && !mesh.is_decal {
                base_meshes.push((node.id, mesh));
            }
        });
        self.walk(true, |node, mesh| {
            if is_ground(node) {
                ground_meshes.push(mesh);
            } else if mesh.is_decal {
                decal_meshes.push((node.id, mesh));
            }
        });
        (ground_meshes, base_meshes, decal_meshes)
    }

    /// Calls `emit` with each slice of every visible node and the node, depth first:
    /// siblings in draw order when `forward`, last sibling first otherwise.
    fn walk(&self, forward: bool, mut emit: impl FnMut(&GpuNode, GpuMeshSlice)) {
        let mut stack: Vec<NodeId> = Vec::new();
        if forward {
            stack.extend(self.roots.iter().rev());
        } else {
            stack.extend(self.roots);
        }
        while let Some(node_id) = stack.pop() {
            let Some(node) = self.nodes.get(node_id.0 as usize) else {
                continue;
            };
            // Off-screen geometry draws no pixels, and skipping it keeps the survivors' order.
            if let Some(view_proj) = self.view_proj
                && let Some(bounds) = node.bounds
                && !frustum_keeps(view_proj, bounds)
            {
                continue;
            }
            if !self.is_visible(&node.visibility) {
                continue;
            }
            for &mesh in &node.meshes {
                emit(node, mesh);
            }
            if forward {
                stack.extend(node.children.iter().rev());
            } else {
                stack.extend(&node.children);
            }
        }
    }

    fn is_visible(&self, visibility: &VisibilityCondition) -> bool {
        match *visibility {
            // An angle cone is not tested here, so it defaults to visible.
            VisibilityCondition::Always | VisibilityCondition::AngleCone { .. } => true,
            VisibilityCondition::LodDistanceSq(max_sq) => self.dist_sq <= max_sq,
            VisibilityCondition::FacesEye { point, normal } => {
                Vec3::from_array(normal).dot(Vec3::from_array(point) - self.eye) < 0.0
            }
            VisibilityCondition::ActorState { mask, expected } => {
                (self.state_mask & mask) == expected
            }
            VisibilityCondition::LodBranch {
                point,
                ext,
                splitdist,
                near,
            } => {
                self.view
                    .is_none_or(|v| v.lod_keeps_subtree(point, ext, splitdist))
                    == near
            }
            VisibilityCondition::BeyondDepth { point, depth } => {
                self.view.is_none_or(|v| v.view_depth_exceeds(point, depth))
            }
            VisibilityCondition::ScaleReach { point, scale_index } => self
                .view
                .is_none_or(|v| v.scale_reach_keeps(point, scale_index)),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// An unsplit chunk keeps the runs' vertex numbers; a split one cuts each run to the
    /// windows it copied and renumbers it from where its window lies in the chunk.
    #[test]
    fn chunk_prop_runs_follow_the_chunks_vertex_windows() {
        let runs = [
            PropRun {
                first: 2,
                end: 5,
                shape: 7,
            },
            PropRun {
                first: 5,
                end: 8,
                shape: 9,
            },
            PropRun {
                first: 12,
                end: 14,
                shape: 3,
            },
        ];
        let whole = chunk_prop_runs(&runs, std::slice::from_ref(&(0..14)));
        assert_eq!(whole, [[2, 5, 8], [5, 8, 10], [12, 14, 4]]);
        // Source vertices 6..10 then 0..4: chunk vertices 0..4 then 4..8; run 12..14 lies
        // in neither.
        let split = chunk_prop_runs(&runs, &[6..10, 0..4]);
        assert_eq!(split, [[0, 2, 10], [6, 8, 8]]);
        assert!(chunk_prop_runs(&[], std::slice::from_ref(&(0..14))).is_empty());
    }

    fn source(index_offset: u32, index_count: u32) -> SourceSlice {
        SourceSlice {
            index_offset,
            index_count,
            is_decal: false,
        }
    }

    /// Resolves every drawn triangle of `slices` back to source vertex numbers.
    fn drawn(plan: &UploadPlan, slices: &[GpuMeshSlice]) -> Vec<usize> {
        let mut out = Vec::new();
        for slice in slices {
            let chunk = &plan.chunks[slice.chunk as usize];
            let indices = chunk.indices.as_ref().expect("split chunk");
            assert!(
                chunk.vertex_count <= 6 && indices.len() <= 9,
                "chunk over budget"
            );
            // Map chunk-local vertex positions to source vertices via the copied ranges.
            let local: Vec<usize> = chunk.vertex_ranges.iter().flat_map(Clone::clone).collect();
            let start = slice.index_offset as usize;
            for &i in &indices[start..start + slice.index_count as usize] {
                out.push(local[(slice.vertex_offset.cast_unsigned() + i) as usize]);
            }
        }
        out
    }

    /// A unit quad of two triangles, as a model with one mesh node.
    fn quad_ir() -> SodModelIr {
        let vertex = |x: f32, y: f32| SodVertex {
            position: [x, y, 0.0],
            normal: [0.0, 0.0, 1.0],
            palette_index: 7,
            flags: 0,
            scenery_class: 0,
            _padding: 0,
        };
        let mut ir = SodModelIr::new("QUAD");
        ir.vertices = vec![
            vertex(0.0, 0.0),
            vertex(1.0, 0.0),
            vertex(1.0, 1.0),
            vertex(0.0, 1.0),
        ];
        ir.indices = vec![0, 1, 2, 0, 2, 3];
        ir
    }

    #[test]
    fn an_unsplit_slice_is_outlined_without_its_diagonal() {
        let ir = quad_ir();
        let mut plan = plan_upload(4, &ir.indices, &[source(0, 6)], 4, 6);
        let edges = plan_edges(&mut plan, &ir, |_| true, &[]).0;
        assert_eq!(edges, vec![vec![0, 1, 1, 2, 2, 3, 3, 0]]);
        let slice = plan.slices[0][0];
        assert_eq!((slice.edge_offset, slice.edge_count), (0, 8));
    }

    /// Two quads on their own vertices: a mark between them cuts the outline between them
    /// too, and each end of the slice is a mark of its own.
    #[test]
    fn a_mark_cuts_the_outline_where_it_cuts_the_triangles() {
        let ir = numbered_ir(8, &[0, 1, 2, 0, 2, 3, 4, 5, 6, 4, 6, 7]);
        let mut plan = plan_upload(8, &ir.indices, &[source(0, 12)], 8, 12);
        let (edges, marks) = plan_edges(&mut plan, &ir, |_| true, &[0, 6, 12, 18]);
        assert_eq!(edges[0].len(), 16, "four edges a quad");
        assert_eq!(marks, vec![vec![(0, 0), (6, 8), (12, 16)]]);
        // A split plan rebases its indices, so it takes no marks.
        let mut split = plan_upload(8, &ir.indices, &[source(0, 12)], 4, 12);
        let (_, marks) = plan_edges(&mut split, &ir, |_| true, &[0, 6, 12]);
        assert!(marks.iter().all(Vec::is_empty));
    }

    /// A model of `n` vertices, each with its number as palette index, over `indices`.
    fn numbered_ir(n: u8, indices: &[u32]) -> SodModelIr {
        let mut ir = SodModelIr::new("NUMBERED");
        ir.vertices = (0..n)
            .map(|i| SodVertex {
                position: [f32::from(i), 0.0, 0.0],
                normal: [0.0, 0.0, 1.0],
                palette_index: i,
                flags: 0,
                scenery_class: 0,
                _padding: 0,
            })
            .collect();
        ir.indices = indices.to_vec();
        ir
    }

    /// Each run's edges of `slice` as pairs of source vertex numbers, in draw order.
    fn run_edges(
        plan: &UploadPlan,
        edges: &[Vec<u32>],
        ir: &SodModelIr,
        slice: usize,
    ) -> Vec<Vec<u32>> {
        plan.slices[slice]
            .iter()
            .map(|run| {
                let chunk = &plan.chunks[run.chunk as usize];
                let local: Vec<usize> = chunk.vertex_ranges.iter().flat_map(Clone::clone).collect();
                let start = run.edge_offset as usize;
                edges[run.chunk as usize][start..start + run.edge_count as usize]
                    .iter()
                    .map(|&i| {
                        let at = run.vertex_offset.cast_unsigned() + i;
                        let source = if chunk.indices.is_some() {
                            local[at as usize]
                        } else {
                            at as usize
                        };
                        assert!(source < ir.vertices.len());
                        u32::try_from(source).expect("small")
                    })
                    .collect()
            })
            .collect()
    }

    /// Every run's edges of `slice` as unordered source vertex pairs.
    fn edge_set(
        plan: &UploadPlan,
        edges: &[Vec<u32>],
        ir: &SodModelIr,
        slice: usize,
    ) -> std::collections::BTreeSet<(u32, u32)> {
        run_edges(plan, edges, ir, slice)
            .iter()
            .flat_map(|run| {
                run.as_chunks::<2>()
                    .0
                    .iter()
                    .map(|&[p, q]| (p.min(q), p.max(q)))
            })
            .collect()
    }

    #[test]
    fn a_split_slice_is_outlined_as_a_whole_in_chunk_indices() {
        let ir = quad_ir();
        // Three vertices a chunk: each triangle is its own run; the cut (the diagonal) is no
        // boundary of the slice, so each run draws its two outer edges.
        let mut plan = plan_upload(4, &ir.indices, &[source(0, 6)], 3, 6);
        let edges = plan_edges(&mut plan, &ir, |_| true, &[]).0;
        assert_eq!(edges.len(), 2);
        assert!(edges.iter().all(|e| e.len() == 4));
        for slice in &plan.slices[0] {
            assert_eq!(slice.edge_count, 4);
        }
        assert_eq!(
            run_edges(&plan, &edges, &ir, 0),
            vec![vec![0, 1, 1, 2], vec![2, 3, 3, 0]]
        );
        // Rejecting every vertex leaves no outline.
        let edges = plan_edges(&mut plan, &ir, |_| false, &[]).0;
        assert!(edges.iter().all(Vec::is_empty));
        assert!(plan.slices[0].iter().all(|s| s.edge_count == 0));
    }

    #[test]
    fn a_cut_edge_whose_other_triangle_is_rejected_is_still_outlined() {
        // Vertex 1 is rejected, so triangle (0,1,2) is skipped and the diagonal 0-2 is used
        // by one triangle only: outlined, as in the unsplit slice.
        let ir = numbered_ir(4, &[0, 1, 2, 0, 2, 3]);
        let keep: fn(&SodVertex) -> bool = |v| v.palette_index != 1;
        let mut unsplit = plan_upload(4, &ir.indices, &[source(0, 6)], 4, 6);
        let whole = plan_edges(&mut unsplit, &ir, keep, &[]).0;
        let mut split = plan_upload(4, &ir.indices, &[source(0, 6)], 3, 6);
        let cut = plan_edges(&mut split, &ir, keep, &[]).0;
        let want = edge_set(&unsplit, &whole, &ir, 0);
        assert_eq!(want, [(0, 2), (0, 3), (2, 3)].into_iter().collect());
        assert_eq!(edge_set(&split, &cut, &ir, 0), want);
    }

    #[test]
    fn a_slice_in_three_runs_has_the_unsplit_outline() {
        // Three triangles: the first is apart from the others, so it is a run of its own
        // beside the second in chunk 0; the third shares an edge with the second and
        // opens chunk 1.
        let ir = numbered_ir(12, &[0, 1, 2, 6, 7, 8, 7, 8, 11]);
        let mut unsplit = plan_upload(12, &ir.indices, &[source(0, 9)], 12, 9);
        let whole = plan_edges(&mut unsplit, &ir, |_| true, &[]).0;
        let mut split = plan_upload(12, &ir.indices, &[source(0, 9)], 8, 9);
        let cut = plan_edges(&mut split, &ir, |_| true, &[]).0;
        assert_eq!(split.slices[0].len(), 3);
        let chunks: Vec<u32> = split.slices[0].iter().map(|r| r.chunk).collect();
        assert_eq!(chunks, vec![0, 0, 1]);
        let want = edge_set(&unsplit, &whole, &ir, 0);
        // Nine triangle edges, the one shared pair 7-8 among them used twice.
        assert_eq!(want.len(), 7);
        assert!(!want.contains(&(7, 8)));
        assert_eq!(edge_set(&split, &cut, &ir, 0), want);
    }

    #[test]
    fn a_chunks_apexes_are_packed_in_its_vertex_windows_order() {
        // An outlined quad's apex stream, split into two windows as a chunk copies them.
        let mut ir = quad_ir();
        ir.allocate_node(
            "BASE",
            None,
            [0.0; 16],
            VisibilityCondition::Always,
            stunt_core::contracts::NodeKind::Mesh {
                vertex_offset: 0,
                vertex_count: 4,
                index_offset: 0,
                index_count: 6,
                is_decal: false,
            },
        );
        let shape = crate::outline::outlined(&ir);
        let ranges = [4..8, 0..2];
        let packed = packed_windows(&shape.apex, &ranges).expect("windows inside the shape");
        assert_eq!(packed.len(), 6);
        let bits = |p: &[f32; 3]| p.map(f32::to_bits);
        let expected = shape.apex[4..8].iter().chain(&shape.apex[..2]);
        assert!(packed.iter().zip(expected).all(|(a, b)| bits(a) == bits(b)));
        // An outline corner's apex is not its own position; a filled vertex's is.
        assert_ne!(bits(&packed[0]), bits(&shape.ir.vertices[4].position));
        assert_eq!(bits(&packed[4]), bits(&shape.ir.vertices[0].position));
        assert!(packed_windows(&shape.apex, &[0..1000, 0..1]).is_none());
    }

    #[test]
    fn model_within_budget_is_one_unchanged_chunk() {
        let indices = [0, 1, 2, 0, 2, 3];
        let plan = plan_upload(4, &indices, &[source(0, 3), source(3, 3)], 4, 6);
        assert_eq!(plan.chunks.len(), 1);
        assert_eq!(plan.chunks[0].vertex_ranges.first(), Some(&(0..4)));
        assert_eq!(plan.chunks[0].indices, None);
        assert_eq!(plan.slices[1][0].vertex_offset, 0);
        assert_eq!(plan.slices[1][0].index_offset, 3);
    }

    #[test]
    fn oversized_model_splits_on_triangles_and_keeps_draw_order() {
        // Ten fans of two triangles over four vertices each, as the world builder emits
        // terrain polygons, then a decal slice whose indices are absolute.
        let mut indices = Vec::new();
        for quad in 0..10u32 {
            let b = 4 * quad;
            indices.extend([b, b + 1, b + 2, b, b + 2, b + 3]);
        }
        let base_count = arena_index(indices.len());
        indices.extend([40, 41, 42]);
        let sources = [
            source(0, base_count),
            SourceSlice {
                is_decal: true,
                ..source(base_count, 3)
            },
        ];
        let plan = plan_upload(43, &indices, &sources, 6, 9);

        assert!(plan.chunks.len() > 1);
        for chunk in &plan.chunks {
            assert!(chunk.vertex_count <= 6 && chunk.index_count() <= 9);
        }
        let expected: Vec<usize> = indices[..base_count as usize]
            .iter()
            .map(|&i| i as usize)
            .collect();
        assert_eq!(drawn(&plan, &plan.slices[0]), expected);
        assert_eq!(drawn(&plan, &plan.slices[1]), vec![40, 41, 42]);
        assert!(plan.slices[1].iter().all(|s| s.is_decal));
    }

    #[test]
    fn split_reads_absolute_indices_and_keeps_whole_triangles() {
        let indices = [5, 6, 7, 7, 8, 9];
        let plan = plan_upload(10, &indices, &[source(0, 6)], 6, 9);
        // The IR's indices are already absolute, so `vertex_offset` is not added; the run
        // copies the contiguous window 5..10 and rebases the indices into it.
        assert_eq!(drawn(&plan, &plan.slices[0]), vec![5, 6, 7, 7, 8, 9]);
        for range in &plan.chunks[0].vertex_ranges {
            assert!(range.end <= 10, "vertex range {range:?} leaves the buffer");
        }
    }

    /// Resolves an unsplit plan's draw the way `draw_indexed` does: index plus base vertex.
    fn drawn_whole(indices: &[u32], slice: &GpuMeshSlice) -> Vec<usize> {
        let start = slice.index_offset as usize;
        indices[start..start + slice.index_count as usize]
            .iter()
            .map(|&i| usize::try_from(slice.vertex_offset + i32::try_from(i).unwrap()).unwrap())
            .collect()
    }

    #[test]
    fn two_nodes_draw_the_vertices_their_absolute_indices_name() {
        // A second mesh at vertex_offset 3 whose indices, as `stunt-core` stores them,
        // address the shape's whole vertex buffer.
        let indices = [0, 1, 2, 3, 4, 5];
        let sources = [source(0, 3), source(3, 3)];

        let whole = plan_upload(6, &indices, &sources, 6, 9);
        assert_eq!(drawn_whole(&indices, &whole.slices[1][0]), vec![3, 4, 5]);

        let split = plan_upload(6, &indices, &sources, 3, 3);
        assert_eq!(drawn(&split, &split.slices[0]), vec![0, 1, 2]);
        assert_eq!(drawn(&split, &split.slices[1]), vec![3, 4, 5]);
        for chunk in &split.chunks {
            for range in &chunk.vertex_ranges {
                assert!(range.end <= 6, "vertex range {range:?} leaves the buffer");
            }
        }
    }

    /// A node `id` under `parent` holding one slice tagged by `index_offset`.
    fn node(id: u32, parent: Option<u32>, children: &[u32], is_decal: bool) -> GpuNode {
        GpuNode {
            id: NodeId(id),
            name: format!("N{id}"),
            parent: parent.map(NodeId),
            children: children.iter().copied().map(NodeId).collect(),
            local_matrix: Mat4::IDENTITY,
            visibility: VisibilityCondition::Always,
            meshes: vec![GpuMeshSlice {
                chunk: 0,
                vertex_offset: 0,
                index_offset: id,
                index_count: 3,
                is_decal,
                edge_offset: 0,
                edge_count: 0,
            }],
            bounds: None,
            marks: Vec::new(),
        }
    }

    #[test]
    fn base_slices_come_last_sibling_first_and_decals_in_draw_order() {
        // Root 0 draws base 1 then base 2, then group 3 with decals 4 then 5.
        let nodes = [
            node(0, None, &[1, 2, 3], false),
            node(1, Some(0), &[], false),
            node(2, Some(0), &[], false),
            node(3, Some(0), &[4, 5], false),
            node(4, Some(3), &[], true),
            node(5, Some(3), &[], true),
        ];
        let walk = VisibleWalk {
            nodes: &nodes,
            roots: &[NodeId(0)],
            state_mask: 0,
            dist_sq: 0.0,
            eye: Vec3::ZERO,
            view: None,
            view_proj: None,
        };
        let (base, decal) = walk.collect();
        let order = |slices: &[GpuMeshSlice]| -> Vec<u32> {
            slices.iter().map(|s| s.index_offset).collect()
        };
        // `Greater` keeps the first draw of a tie, so the later sibling must come first.
        assert_eq!(order(&base), vec![0, 3, 2, 1]);
        // `GreaterEqual` keeps the last draw, so decals keep the authored order.
        assert_eq!(order(&decal), vec![4, 5]);
    }

    /// A node behind a `ScaleReach` gate draws while the frame camera keeps it inside its
    /// cut and not past it; with no camera it draws.
    #[test]
    fn a_scale_reach_node_draws_only_inside_its_cut() {
        let camera = CameraTransform {
            eye: [0.0, 0.0, 0.0],
            target: [0.0, 0.0, -1.0],
            ..CameraTransform::default()
        };
        let drawn = |z: f32, view: Option<&CameraTransform>| -> Vec<u32> {
            let mut gated = node(1, Some(0), &[], false);
            // `scale_index` 14 is cut at 256 m at the default lens.
            gated.visibility = VisibilityCondition::ScaleReach {
                point: [0.0, 0.0, z],
                scale_index: 14,
            };
            let nodes = [node(0, None, &[1], false), gated];
            let walk = VisibleWalk {
                nodes: &nodes,
                roots: &[NodeId(0)],
                state_mask: 0,
                dist_sq: 0.0,
                eye: Vec3::ZERO,
                view,
                view_proj: None,
            };
            walk.collect().0.iter().map(|m| m.index_offset).collect()
        };
        assert_eq!(drawn(-255.0, Some(&camera)), vec![0, 1]);
        assert_eq!(drawn(-256.0, Some(&camera)), vec![0]);
        assert_eq!(drawn(-256.0, None), vec![0, 1]);
    }

    /// The view-projection matrix the vertex shader multiplies by, from the same
    /// `CameraController` the renderer builds: the eye at the origin looking down -Z through a
    /// 45-degree lens, so at 10 m the frustum is 4.14 m tall and 6.63 m wide either side.
    fn test_view_proj() -> Mat4 {
        let mut controller = crate::camera::CameraController::default();
        controller.set_authored_transform(stunt_core::scene::ViewCamera {
            eye: [0.0, 0.0, 0.0],
            target: [0.0, 0.0, -1.0],
            fov_degrees: 45.0,
            roll_radians: 0.0,
        });
        // With the eye at the origin the world's eye-relative matrix is the identity.
        Mat4::from_cols_array(&controller.build_uniform().rotation_proj)
    }

    /// A box of half-extent `half` on every axis around `center`.
    fn boxed(center: [f32; 3], half: f32) -> NodeBounds {
        let center = Vec3::from_array(center);
        NodeBounds {
            min: center - Vec3::splat(half),
            max: center + Vec3::splat(half),
        }
    }

    #[test]
    fn a_box_wholly_behind_the_eye_is_culled() {
        assert!(!frustum_keeps(
            test_view_proj(),
            boxed([0.0, 0.0, 10.0], 1.0)
        ));
    }

    #[test]
    fn a_box_wholly_beside_the_frustum_is_culled() {
        // At z = -10 the lens spans x in [-6.63, 6.63] and y in [-4.14, 4.14].
        assert!(!frustum_keeps(
            test_view_proj(),
            boxed([20.0, 0.0, -10.0], 1.0)
        ));
        assert!(!frustum_keeps(
            test_view_proj(),
            boxed([0.0, 20.0, -10.0], 1.0)
        ));
    }

    #[test]
    fn a_box_straddling_a_plane_is_kept() {
        let straddling = NodeBounds {
            min: Vec3::new(-7.5, -1.0, -11.0),
            max: Vec3::new(-6.0, 1.0, -9.0),
        };
        assert!(frustum_keeps(test_view_proj(), straddling));
        assert!(frustum_keeps(
            test_view_proj(),
            boxed([0.0, 0.0, -10.0], 1.0)
        ));
    }

    #[test]
    fn a_box_containing_the_eye_is_kept() {
        assert!(frustum_keeps(test_view_proj(), boxed([0.0, 0.0, 0.0], 1.0)));
    }

    #[test]
    fn a_box_beyond_the_old_far_plane_is_kept() {
        // The perspective is infinite: 100 km ahead is past the old 25 km far plane.
        assert!(frustum_keeps(
            test_view_proj(),
            boxed([0.0, 0.0, -100_000.0], 1.0)
        ));
    }

    #[test]
    fn a_node_culled_with_its_subtree() {
        let view_proj = test_view_proj();
        let mut root = node(0, None, &[1], false);
        root.bounds = Some(boxed([0.0, 0.0, 10.0], 1.0));
        let mut child = node(1, Some(0), &[], false);
        child.bounds = Some(boxed([0.0, 0.0, -10.0], 1.0));
        let nodes = [root.clone(), child];
        let walk = VisibleWalk {
            nodes: &nodes,
            roots: &[NodeId(0)],
            state_mask: 0,
            dist_sq: 0.0,
            eye: Vec3::ZERO,
            view: None,
            view_proj: Some(view_proj),
        };
        let (base, decals) = walk.collect();
        assert!(
            base.is_empty(),
            "the culled root's subtree was walked: {base:?}"
        );
        assert!(decals.is_empty(), "the culled root drew a decal");

        // The same subtree with the root's box in view keeps both slices, parent first.
        let mut seen = root;
        seen.bounds = Some(boxed([0.0, 0.0, -10.0], 1.0));
        let nodes = [seen, nodes[1].clone()];
        let walk = VisibleWalk {
            nodes: &nodes,
            roots: &[NodeId(0)],
            state_mask: 0,
            dist_sq: 0.0,
            eye: Vec3::ZERO,
            view: None,
            view_proj: Some(view_proj),
        };
        let order: Vec<u32> = walk
            .collect()
            .0
            .iter()
            .map(|mesh| mesh.index_offset)
            .collect();
        assert_eq!(order, vec![0, 1]);
    }

    /// A model of two mesh nodes: a parent at the origin, and a child whose `local_matrix`
    /// translates it by `offset`, which the draw does not apply.
    fn two_node_ir(offset: f32) -> SodModelIr {
        use stunt_core::contracts::NodeKind;

        let vertex = |x: f32, y: f32| SodVertex {
            position: [x, y, 0.0],
            normal: [0.0, 0.0, 1.0],
            palette_index: 7,
            flags: 0,
            scenery_class: 0,
            _padding: 0,
        };
        let mut ir = SodModelIr::new("TWO");
        ir.vertices = vec![
            vertex(0.0, 0.0),
            vertex(1.0, 0.0),
            vertex(1.0, 1.0),
            vertex(2.0, 0.0),
            vertex(3.0, 0.0),
            vertex(3.0, 1.0),
        ];
        ir.indices = vec![0, 1, 2, 3, 4, 5];
        let mesh = |vertex_offset, index_offset| NodeKind::Mesh {
            vertex_offset,
            vertex_count: 3,
            index_offset,
            index_count: 3,
            is_decal: false,
        };
        let parent = ir.allocate_node(
            "PARENT",
            None,
            Mat4::IDENTITY.to_cols_array(),
            VisibilityCondition::Always,
            mesh(0, 0),
        );
        ir.allocate_node(
            "CHILD",
            Some(parent),
            Mat4::from_translation(Vec3::new(offset, 0.0, 0.0)).to_cols_array(),
            VisibilityCondition::Always,
            mesh(3, 3),
        );
        ir.root_nodes = vec![parent];
        ir
    }

    #[test]
    fn a_model_box_covers_every_root() {
        let bounds = [
            Some(boxed([0.0, 0.0, 0.0], 1.0)),
            Some(boxed([0.0, 0.0, 0.0], 0.5)),
            None,
            Some(boxed([5.0, 0.0, 0.0], 1.0)),
        ];
        // Node 1 is a child, so its box is already in its root's; node 2 has no mesh.
        let roots = [NodeId(0), NodeId(2), NodeId(3)];
        assert_eq!(
            model_bounds(&roots, &bounds),
            Some(NodeBounds {
                min: Vec3::new(-1.0, -1.0, -1.0),
                max: Vec3::new(6.0, 1.0, 1.0),
            })
        );
        assert_eq!(model_bounds(&[NodeId(2)], &bounds), None);
    }

    #[test]
    fn a_node_box_covers_its_descendants_as_drawn() {
        let bounds = node_bounds(&two_node_ir(10.0));
        assert_eq!(
            bounds.first().copied().flatten(),
            Some(NodeBounds {
                min: Vec3::new(0.0, 0.0, 0.0),
                max: Vec3::new(3.0, 1.0, 0.0),
            })
        );
        assert_eq!(
            bounds.get(1).copied().flatten(),
            Some(NodeBounds {
                min: Vec3::new(2.0, 0.0, 0.0),
                max: Vec3::new(3.0, 1.0, 0.0),
            })
        );
    }
}
