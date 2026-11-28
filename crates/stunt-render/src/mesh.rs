//! GPU Mesh and Display-List Scene Graph Arena.
//!
//! Complies with Architectural Invariants:
//! - `[I2]` Flat contiguous arena allocation (`Vec<SodNode>` indexed by `NodeId(u32)`).
//! - `[I5]` Separation of base meshes from coplanar decal batches.
//!
//! A shape is uploaded unchanged as one vertex/index buffer pair. The static world, the one
//! model that can outgrow a buffer (a `--sidata` world can need 500 MB of vertices), is not
//! uploaded: [`GpuModel::plan_outlined`] plans its nodes, slices and outline on the CPU, and the
//! scene renderer streams the slices a frame draws (`crate::world_stream`).

use std::ops::Range;

use crate::outline::{Apex, Outlined, own_apexes};
use glam::{Mat4, Vec3};
use stunt_core::contracts::{
    CameraTransform, NodeId, SodModelIr, SodVertex, VERTEX_FLAG_DISC, VisibilityCondition,
    arena_index,
};
use stunt_core::world::{GROUND_NODE, PropRun};

/// One vertex of the second vertex stream, which follows the first vertex for vertex.
///
/// `apex` is the vertex's apex ([`Outlined`], [`Apex`]): a point and a radius. `prop_shape` is the shape
/// word of a world prop vertex, `shape id + 1` of the prop that placed it ([`PropRun`]), and 0
/// for every other vertex; the plane's shape word reads it, so the fragment stage searches
/// nothing.
#[repr(C)]
#[derive(Clone, Copy, Debug, Default, PartialEq, bytemuck::Pod, bytemuck::Zeroable)]
pub(crate) struct ApexVertex {
    pub apex: Apex,
    pub prop_shape: u32,
}

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
    /// The node's geometry; `None` for a pure transform group.
    pub mesh: Option<GpuMeshSlice>,
    /// Box around this node's slices and every descendant's, in the model's space; `None` when
    /// neither holds a vertex.
    pub bounds: Option<NodeBounds>,
    /// Whether this node's slices or a descendant's hold a disc's rim vertex
    /// ([`VERTEX_FLAG_DISC`]), which the vertex shader moves off its position under a lens other
    /// than the default (`squeeze_disc`), so [`Self::bounds`] no longer bounds where it draws.
    pub discs: bool,
    /// The offsets in the model's index arena [`GpuModel::cut`] may cut this node's slice at,
    /// ascending, each with where its outline is cut in the model's outline list; empty unless
    /// the plan was asked for them ([`GpuModel::plan_outlined`]).
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
    add_subtrees_to_parents(ir, &mut bounds, |subtree, parent| {
        subtree.map_or(parent, |subtree| Some(subtree.union(parent)))
    });
    bounds
}

/// Whether each node's slices or a descendant's hold a disc rim vertex, as [`node_bounds`] boxes
/// them.
fn node_discs(ir: &SodModelIr) -> Vec<bool> {
    let mut discs = vec![false; ir.nodes.len()];
    for mesh in ir.meshes() {
        if mesh
            .vertices
            .iter()
            .any(|vertex| vertex.flags & VERTEX_FLAG_DISC != 0)
            && let Some(slot) = discs.get_mut(mesh.node.id.0 as usize)
        {
            *slot = true;
        }
    }
    add_subtrees_to_parents(ir, &mut discs, |subtree, parent| subtree || parent);
    discs
}

/// Folds each node's per-node value, its own slices' plus its descendants' so far, into its
/// parent's with `merge(subtree, parent)`.
fn add_subtrees_to_parents<T: Copy>(ir: &SodModelIr, values: &mut [T], merge: impl Fn(T, T) -> T) {
    for (n, node) in ir.nodes.iter().enumerate().rev() {
        let Some(subtree) = values.get(n).copied() else {
            continue;
        };
        let Some(parent) = node
            .parent
            .and_then(|parent| values.get_mut(parent.0 as usize))
        else {
            continue;
        };
        *parent = merge(subtree, *parent);
    }
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
fn frustum_keeps(view_proj: Mat4, bounds: NodeBounds) -> bool {
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

/// Whether the vertex shader may move a disc rim vertex of a model or node that holds `discs`
/// under the lens `disc_depth_scale`, so its box no longer bounds where the vertex draws.
///
/// It rescales a rim vertex's clip depth and `w` about the disc's centre (`squeeze_disc`), which
/// can bring a vertex outside the box's side planes into the view; the default lens sets the
/// scale to exactly 1, where it moves none.
fn squeezes_discs(discs: bool, disc_depth_scale: f32) -> bool {
    #[expect(
        clippy::float_cmp,
        reason = "the default lens sets the scale to exactly 1, where the shader moves no rim"
    )]
    let moved = disc_depth_scale != 1.0;
    discs && moved
}

/// Polygonal geometry slice of a model's index buffer, whose indices address its whole vertex
/// buffer, or of the world stream's.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct GpuMeshSlice {
    /// First index of the slice within the consolidated index buffer.
    pub index_offset: u32,
    /// Number of indices in the slice (three per triangle).
    pub index_count: u32,
    /// Whether the slice is a coplanar decal drawn through the depth-bias pipeline `[I5]`.
    pub is_decal: bool,
    /// First index of the slice's outline in its model's outline list.
    pub edge_offset: u32,
    /// Number of outline indices of the slice (two per edge); zero when it has no outline.
    pub edge_count: u32,
}

/// Which vertices' triangles a model's outline takes, and the index offsets a slice may be
/// cut at ([`GpuModel::plan_outlined`]).
type Outlines<'a> = (fn(&SodVertex) -> bool, &'a [u32]);

/// GPU-resident representation of a transpiled `SodModelIr`.
#[derive(Debug)]
pub struct GpuModel {
    /// Model name identifier.
    pub name: String,
    /// The model's buffers; `None` for the world, which is planned ([`Self::plan_outlined`])
    /// and drawn from the world stream.
    pub buffers: Option<GpuBuffers>,
    /// Total vertex count of the source model.
    pub vertex_count: u32,
    /// Total index count of the source model.
    pub index_count: u32,
    /// Flat arena of scene nodes per `[I2]`.
    pub nodes: Vec<GpuNode>,
    /// Root node IDs.
    pub root_nodes: Vec<NodeId>,
    /// Box around every vertex the model can draw, in its own space: the union of its roots'
    /// [`GpuNode::bounds`], or `None` when it has no mesh. [`Self::rewrite_vertices`] leaves it,
    /// and every node's box, as uploaded.
    pub bounds: Option<NodeBounds>,
    /// Whether any vertex is a disc's rim vertex ([`VERTEX_FLAG_DISC`]), which the vertex shader
    /// moves off its position under a lens other than the default (`squeeze_disc`).
    pub discs: bool,
}

impl GpuModel {
    /// Uploads a `SodModelIr` into GPU buffers.
    ///
    /// Each vertex's apex ([`Outlined`]) is its own position, so no line corner is culled.
    pub fn from_ir(device: &wgpu::Device, queue: &wgpu::Queue, ir: &SodModelIr) -> Self {
        Self::upload(device, queue, ir, &own_apexes(ir))
    }

    /// Uploads an outlined shape with its apexes, so its outline corners cull with the
    /// triangles their edges bound.
    pub(crate) fn from_outlined(
        device: &wgpu::Device,
        queue: &wgpu::Queue,
        shape: &Outlined,
    ) -> Self {
        Self::upload(device, queue, &shape.ir, &shape.apex)
    }

    /// Uploads `ir` with `apex`, one per vertex, as one buffer set.
    fn upload(device: &wgpu::Device, queue: &wgpu::Queue, ir: &SodModelIr, apex: &[Apex]) -> Self {
        let (mut model, _) = Self::plan(ir, None);
        model.buffers = Some(GpuBuffers::upload(device, queue, ir, apex));
        model
    }

    /// Plans the model without creating any buffer: its nodes, each with its slice, its box and
    /// its disc flag. With `outlined` (which vertices' triangles the outline takes, and the
    /// index offsets a slice may be cut at), each slice gets its outline and its marks, and the
    /// outline list is returned; without, the list is empty.
    fn plan(ir: &SodModelIr, outlined: Option<Outlines<'_>>) -> (Self, Vec<u32>) {
        // `meshes()` walks the nodes in arena order and already skips a node whose window is
        // unsafe, so each node takes the next mesh if that mesh is its own.
        let mut meshes = ir.meshes().peekable();
        let mut slices: Vec<Option<GpuMeshSlice>> = ir
            .nodes
            .iter()
            .map(|node| {
                let mesh = meshes.next_if(|mesh| std::ptr::eq(mesh.node, node))?;
                // The IR's indices are absolute, so the whole buffer is drawn from vertex 0.
                Some(GpuMeshSlice {
                    index_offset: mesh.index_offset,
                    index_count: arena_index(mesh.indices.len()),
                    is_decal: mesh.is_decal(),
                    edge_offset: 0,
                    edge_count: 0,
                })
            })
            .collect();
        let (edges, mut marks) = match outlined {
            Some((keep, marks)) => plan_edges(&mut slices, ir, keep, marks),
            None => (Vec::new(), Vec::new()),
        };
        marks.resize_with(slices.len(), Vec::new);
        let bounds = node_bounds(ir);
        let discs = node_discs(ir);
        let nodes = ir
            .nodes
            .iter()
            .zip(slices.into_iter().zip(marks))
            .enumerate()
            .map(|(n, (node, (mesh, marks)))| GpuNode {
                id: node.id,
                name: node.name.clone(),
                parent: node.parent,
                children: node.children.clone(),
                local_matrix: Mat4::from_cols_array(&node.local_matrix),
                visibility: node.visibility,
                mesh,
                bounds: bounds.get(n).copied().flatten(),
                discs: discs.get(n).copied().unwrap_or(false),
                marks,
            })
            .collect();

        let bounds = model_bounds(&ir.root_nodes, &bounds);
        let model = Self {
            name: ir.name.clone(),
            buffers: None,
            vertex_count: arena_index(ir.vertices.len()),
            index_count: arena_index(ir.indices.len()),
            nodes,
            root_nodes: ir.root_nodes.clone(),
            bounds,
            discs: ir
                .vertices
                .iter()
                .any(|vertex| vertex.flags & VERTEX_FLAG_DISC != 0),
        };
        (model, edges)
    }

    /// Plans the static world without a device buffer, for the world stream: the model, with no
    /// [`Self::buffers`], and its outline list, two indices into `ir.vertices` an edge.
    ///
    /// Each slice's outline is every edge exactly one of its triangles uses, so it costs eight
    /// bytes an edge; triangles with a corner `outlined` rejects are left out. `marks` are
    /// offsets in `ir.indices`, ascending, where [`Self::cut`] may cut a slice; a cut keeps the
    /// outline whole only where no edge is shared across it.
    pub(crate) fn plan_outlined(
        ir: &SodModelIr,
        outlined: fn(&SodVertex) -> bool,
        marks: &[u32],
    ) -> (Self, Vec<u32>) {
        Self::plan(ir, Some((outlined, marks)))
    }

    /// Whether any vertex the model can draw may land inside `view_proj`'s view frustum, by
    /// [`Self::bounds`] and `frustum_keeps`; false for a model with no mesh. `view_proj` takes a
    /// model vertex to clip space, as the vertex shader does.
    ///
    /// A model with [`Self::discs`] is always kept when `disc_depth_scale` (the camera's) is not
    /// 1: the shader then rescales a rim vertex's clip depth and `w` about the disc's centre,
    /// which can bring a vertex outside the box's side planes into the view.
    pub(crate) fn in_frustum(&self, view_proj: Mat4, disc_depth_scale: f32) -> bool {
        self.bounds.is_some_and(|bounds| {
            squeezes_discs(self.discs, disc_depth_scale) || frustum_keeps(view_proj, bounds)
        })
    }

    /// Overwrites the vertices and apexes with `shape`'s, keeping the indices, nodes and slices, and returns
    /// true; returns false, writing nothing, when `shape`'s vertex or index count differs from
    /// the uploaded model's.
    ///
    /// `shape` must have the indices and nodes the model was uploaded from: only the counts are
    /// checked here, and other indices at equal counts would bind triangles to the wrong
    /// vertices. For a model whose geometry stays and whose vertex attributes change, such as
    /// an actor's shape decoded under another light: it costs two buffer writes instead of a
    /// new model's buffers.
    pub(crate) fn rewrite_vertices(&self, queue: &wgpu::Queue, shape: &Outlined) -> bool {
        let ir = &shape.ir;
        if arena_index(ir.vertices.len()) != self.vertex_count
            || arena_index(ir.indices.len()) != self.index_count
        {
            return false;
        }
        if let Some(buffers) = &self.buffers {
            buffers.rewrite_vertices(queue, &ir.vertices, &shape.apex);
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
            disc_depth_scale: 1.0,
            flattened_by: None,
        }
        .collect()
    }

    /// [`Self::collect_visible_meshes`] for the shadow draw of an actor whose eye-relative
    /// shadow matrix is `shadow`: each facing gate tests its face flattened by `shadow`, as
    /// `PLAYONE`'s `REJ` reads the vertex registers the flattening matrix produced
    /// ([`faces_flattened`]).
    pub fn collect_shadow_meshes(
        &self,
        state_mask: u16,
        distance_to_cam: f32,
        shadow: Mat4,
        view: Option<&CameraTransform>,
    ) -> (Vec<GpuMeshSlice>, Vec<GpuMeshSlice>) {
        VisibleWalk {
            nodes: &self.nodes,
            roots: &self.root_nodes,
            state_mask,
            dist_sq: distance_to_cam * distance_to_cam,
            eye: Vec3::ZERO,
            view,
            view_proj: None,
            disc_depth_scale: 1.0,
            flattened_by: Some(shadow),
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
    /// an off-screen slice covers none, and keeps the order of the slices that survive. A node
    /// whose subtree holds disc rim vertices is kept whenever `disc_depth_scale` (the camera's)
    /// is not 1, as [`Self::in_frustum`] keeps a model with them.
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
        disc_depth_scale: f32,
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
            disc_depth_scale,
            flattened_by: None,
        }
        .collect_world()
    }

    /// The part `start..end` of the index arena of node `node`'s one slice, with its share
    /// of the slice's outline; `None` unless both ends are among the node's marks
    /// ([`Self::plan_outlined`]) and `start <= end`.
    #[must_use]
    pub fn cut(&self, node: NodeId, start: u32, end: u32) -> Option<GpuMeshSlice> {
        let node = self.nodes.get(node.0 as usize)?;
        let whole = node.mesh.as_ref()?;
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

    /// Encodes `meshes` into `rpass`; nothing for a model without buffers.
    ///
    /// The pipeline and bind groups must already be set.
    pub fn draw_slices(&self, rpass: &mut wgpu::RenderPass<'_>, meshes: &[GpuMeshSlice]) {
        let Some(buffers) = self.buffers.as_ref().filter(|_| !meshes.is_empty()) else {
            return;
        };
        rpass.set_vertex_buffer(0, buffers.vertices.slice(..));
        rpass.set_vertex_buffer(1, buffers.apex.slice(..));
        rpass.set_index_buffer(buffers.indices.slice(..), wgpu::IndexFormat::Uint32);
        for mesh in meshes {
            rpass.draw_indexed(
                mesh.index_offset..(mesh.index_offset + mesh.index_count),
                0,
                0..1,
            );
        }
    }
}

/// Fills in each slice's outline and returns the model's outline list, then each slice's
/// `marks` (offsets in `ir.indices`, ascending) that lie within it, each with its edge offset.
pub(crate) fn plan_edges(
    slices: &mut [Option<GpuMeshSlice>],
    ir: &SodModelIr,
    keep: fn(&SodVertex) -> bool,
    marks: &[u32],
) -> (Vec<u32>, Vec<Vec<(u32, u32)>>) {
    let mut edges = Vec::new();
    let mut slice_marks = Vec::with_capacity(slices.len());
    for slice in slices.iter_mut() {
        let mut found_marks = Vec::new();
        let start = slice.map_or(0, |s| s.index_offset as usize);
        let triangles = slice.and_then(|s| ir.indices.get(start..start + s.index_count as usize));
        if let (Some(slice), Some(triangles)) = (slice.as_mut(), triangles) {
            let found = crate::outline::numbered_boundary_edges(triangles, |i| {
                ir.vertices.get(i as usize).is_some_and(keep)
            });
            slice.edge_offset = arena_index(edges.len());
            slice.edge_count = arena_index(2 * found.len());
            // Edges come in first-use order, so the ones before a mark are a prefix.
            let end = slice.index_offset + slice.index_count;
            let first = marks.partition_point(|&m| m < slice.index_offset);
            for &mark in marks.iter().skip(first).take_while(|&&m| m <= end) {
                let triangle = ((mark - slice.index_offset) / 3) as usize;
                let before = found.partition_point(|&(_, number)| number < triangle);
                found_marks.push((mark, slice.edge_offset + arena_index(2 * before)));
            }
            edges.extend(found.into_iter().flat_map(|(edge, _)| edge));
        }
        slice_marks.push(found_marks);
    }
    (edges, slice_marks)
}

/// The vertex, apex and index buffers of a [`GpuModel`].
#[derive(Debug)]
pub struct GpuBuffers {
    /// The vertices.
    pub vertices: wgpu::Buffer,
    /// The second vertex stream ([`ApexVertex`]: each vertex's apex and prop shape word), in
    /// `vertices`' order.
    pub apex: wgpu::Buffer,
    /// The 32-bit indices.
    pub indices: wgpu::Buffer,
}

impl GpuBuffers {
    fn upload(device: &wgpu::Device, queue: &wgpu::Queue, ir: &SodModelIr, apex: &[Apex]) -> Self {
        let vertex_count = ir.vertices.len();
        let vertex_bytes: &[u8] = bytemuck::cast_slice(&ir.vertices);
        let vertex_buffer = device.create_buffer(&wgpu::BufferDescriptor {
            label: Some(&format!("{}_vertex_buffer", ir.name)),
            size: (vertex_count.max(1) * size_of::<SodVertex>()) as u64,
            usage: wgpu::BufferUsages::VERTEX | wgpu::BufferUsages::COPY_DST,
            mapped_at_creation: false,
        });
        if !vertex_bytes.is_empty() {
            queue.write_buffer(&vertex_buffer, 0, vertex_bytes);
        }
        // Filled where it is mapped, so the stream is built once, in place.
        let apex_buffer = device.create_buffer(&wgpu::BufferDescriptor {
            label: Some(&format!("{}_apex_buffer", ir.name)),
            size: (vertex_count.max(1) * size_of::<ApexVertex>()) as u64,
            usage: wgpu::BufferUsages::VERTEX | wgpu::BufferUsages::COPY_DST,
            mapped_at_creation: true,
        });
        {
            #[expect(
                clippy::expect_used,
                reason = "a buffer created mapped maps its whole range"
            )]
            let mut mapped = apex_buffer
                .slice(..)
                .get_mapped_range_mut()
                .expect("a buffer created mapped maps its whole range");
            // A shape has no prop runs: its vertices carry no shape word.
            let stream: Vec<ApexVertex> = apex_vertices(apex, 0..vertex_count, &[]).collect();
            let bytes: &[u8] = bytemuck::cast_slice(&stream);
            mapped.slice(..bytes.len()).copy_from_slice(bytes);
        }
        apex_buffer.unmap();

        let index_bytes: &[u8] = bytemuck::cast_slice(&ir.indices);
        let index_buffer = device.create_buffer(&wgpu::BufferDescriptor {
            label: Some(&format!("{}_index_buffer", ir.name)),
            size: (index_bytes.len().max(size_of::<u32>())) as u64,
            usage: wgpu::BufferUsages::INDEX | wgpu::BufferUsages::COPY_DST,
            mapped_at_creation: false,
        });
        if !index_bytes.is_empty() {
            queue.write_buffer(&index_buffer, 0, index_bytes);
        }
        Self {
            vertices: vertex_buffer,
            apex: apex_buffer,
            indices: index_buffer,
        }
    }

    /// Writes `vertices` and their apexes over the uploaded ones, one write each, since each
    /// write allocates a staging buffer (`research/parity/lavapipe-render-time.md`).
    fn rewrite_vertices(&self, queue: &wgpu::Queue, vertices: &[SodVertex], apex: &[Apex]) {
        let stream: Vec<ApexVertex> = apex_vertices(apex, 0..vertices.len(), &[]).collect();
        if !stream.is_empty() {
            queue.write_buffer(&self.apex, 0, bytemuck::cast_slice(&stream));
        }
        if !vertices.is_empty() {
            queue.write_buffer(&self.vertices, 0, bytemuck::cast_slice(vertices));
        }
    }
}

/// `apex`'s `range` as [`ApexVertex`]es, each with the shape word of the run in `runs` (in
/// vertex order) that holds its source vertex, 0 when none does; nothing when the range leaves
/// `apex`.
pub(crate) fn apex_vertices<'a>(
    apex: &'a [Apex],
    range: Range<usize>,
    runs: &'a [PropRun],
) -> impl Iterator<Item = ApexVertex> + 'a {
    let window = apex.get(range.clone()).unwrap_or_default();
    shaped(window.iter().copied(), range, runs)
}

/// `apexes`, one per source vertex of `range`, as [`ApexVertex`]es with their runs' shape
/// words, as [`apex_vertices`] gives them.
pub(crate) fn shaped<'a>(
    apexes: impl Iterator<Item = Apex> + 'a,
    range: Range<usize>,
    runs: &'a [PropRun],
) -> impl Iterator<Item = ApexVertex> + 'a {
    let mut run = runs.partition_point(|run| run.end as usize <= range.start);
    apexes.zip(range).map(move |(apex, source)| {
        while runs.get(run).is_some_and(|r| r.end as usize <= source) {
            run += 1;
        }
        let prop_shape = runs
            .get(run)
            .filter(|r| r.first as usize <= source)
            .map_or(0, |r| u32::from(r.shape).saturating_add(1));
        ApexVertex { apex, prop_shape }
    })
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
    /// The camera's disc depth scale, which decides whether a node with disc rim vertices can be
    /// culled by its box ([`squeezes_discs`]); read only with `view_proj`.
    disc_depth_scale: f32,
    /// The eye-relative shadow matrix of a shadow draw, which takes a [`VisibilityCondition::FacesEye`]
    /// face to the plane it is flattened on before testing it ([`faces_flattened`]); `None` tests
    /// the face where it is, against `eye`.
    flattened_by: Option<Mat4>,
}

/// Whether a face points at the eye once `shadow`, an eye-relative shadow matrix, flattens it.
///
/// `PLAYONE`'s `REJ` computes the face normal `(a - b) x (c - b)` from the vertex registers,
/// which hold the points the draw matrix produced, and tests it against `b` plus the object's
/// origin relative to the eye (`research/playone-exe/sod-vm-execution.md` section 8.6). In a
/// shadow draw that matrix flattens the shape onto the ground plane (`0x1C0D`), so a face is
/// tested where the shadow puts it: the normal is `shadow`'s linear part's cofactor matrix
/// times the model-space normal, the point is the flattened one, and the eye is the origin.
fn faces_flattened(shadow: &Mat4, point: Vec3, normal: Vec3) -> bool {
    let linear = glam::Mat3::from_mat4(*shadow);
    let cofactor = glam::Mat3::from_cols(
        linear.y_axis.cross(linear.z_axis),
        linear.z_axis.cross(linear.x_axis),
        linear.x_axis.cross(linear.y_axis),
    );
    (cofactor * normal).dot(shadow.transform_point3(point)) < 0.0
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
                && !squeezes_discs(node.discs, self.disc_depth_scale)
                && !frustum_keeps(view_proj, bounds)
            {
                continue;
            }
            if !self.is_visible(&node.visibility) {
                continue;
            }
            if let Some(mesh) = node.mesh {
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
                let (point, normal) = (Vec3::from_array(point), Vec3::from_array(normal));
                match self.flattened_by {
                    Some(shadow) => faces_flattened(&shadow, point, normal),
                    None => normal.dot(point - self.eye) < 0.0,
                }
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

    #[test]
    fn a_flattened_face_faces_the_eye_by_its_vertical_normal() {
        // A level plane 0.15 m below the eye, which stands inside the shape.
        let shadow = Mat4::from_cols_array(&[
            1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, -0.15, 0.0, 1.0,
        ]);
        let point = Vec3::new(0.1, 0.3, 0.2);
        // A roof faces up and is seen from above once flattened, though the eye is below it.
        assert!(faces_flattened(&shadow, point, Vec3::Y));
        // A floor faces down, and a wall flattens to no area.
        assert!(!faces_flattened(&shadow, point, -Vec3::Y));
        assert!(!faces_flattened(&shadow, point, Vec3::X));
    }

    /// A slice of `index_count` indices from `index_offset`, before its outline is planned.
    fn slice(index_offset: u32, index_count: u32) -> GpuMeshSlice {
        GpuMeshSlice {
            index_offset,
            index_count,
            is_decal: false,
            edge_offset: 0,
            edge_count: 0,
        }
    }

    /// A unit quad of two triangles, as a model with one mesh node.
    fn quad_ir() -> SodModelIr {
        let vertex = |x: f32, y: f32| SodVertex {
            position: [x, y, 0.0],
            normal: [0.0, 0.0, 1.0],
            palette_index: 7,
            flags: 0,
            scenery_class: 0,
            decal_tie: 0,
            list_rank: 0,
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
    fn a_slice_is_outlined_without_its_diagonal() {
        let ir = quad_ir();
        let mut slices = [Some(slice(0, 6)), None];
        let edges = plan_edges(&mut slices, &ir, |_| true, &[]).0;
        assert_eq!(edges, vec![0, 1, 1, 2, 2, 3, 3, 0]);
        let planned = slices[0].expect("a mesh");
        assert_eq!((planned.edge_offset, planned.edge_count), (0, 8));
        assert_eq!(slices[1], None);
        // Rejecting every vertex leaves no outline.
        let edges = plan_edges(&mut slices, &ir, |_| false, &[]).0;
        assert!(edges.is_empty());
        assert_eq!(slices[0].map(|s| s.edge_count), Some(0));
    }

    /// Two quads on their own vertices: a mark between them cuts the outline between them
    /// too, and each end of the slice is a mark of its own.
    #[test]
    fn a_mark_cuts_the_outline_where_it_cuts_the_triangles() {
        let ir = numbered_ir(8, &[0, 1, 2, 0, 2, 3, 4, 5, 6, 4, 6, 7]);
        let mut slices = [Some(slice(0, 12))];
        let (edges, marks) = plan_edges(&mut slices, &ir, |_| true, &[0, 6, 12, 18]);
        assert_eq!(edges.len(), 16, "four edges a quad");
        assert_eq!(marks, vec![vec![(0, 0), (6, 8), (12, 16)]]);
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
                decal_tie: 0,
                list_rank: 0,
            })
            .collect();
        ir.indices = indices.to_vec();
        ir
    }

    #[test]
    fn an_edge_whose_other_triangle_is_rejected_is_outlined() {
        // Vertex 1 is rejected, so triangle (0,1,2) is skipped and the diagonal 0-2 is used
        // by one triangle only.
        let ir = numbered_ir(4, &[0, 1, 2, 0, 2, 3]);
        let mut slices = [Some(slice(0, 6))];
        let edges = plan_edges(&mut slices, &ir, |v| v.palette_index != 1, &[]).0;
        let pairs: std::collections::BTreeSet<(u32, u32)> = edges
            .as_chunks::<2>()
            .0
            .iter()
            .map(|&[p, q]| (p.min(q), p.max(q)))
            .collect();
        assert_eq!(pairs, [(0, 2), (0, 3), (2, 3)].into_iter().collect());
    }

    #[test]
    fn a_shapes_apexes_are_taken_in_its_vertex_order() {
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
        let packed: Vec<ApexVertex> =
            apex_vertices(&shape.apex, 0..shape.apex.len(), &[]).collect();
        assert_eq!(packed.len(), shape.apex.len());
        let bits = |p: [f32; 4]| p.map(f32::to_bits);
        let point = |p: [f32; 4]| [p[0], p[1], p[2]].map(f32::to_bits);
        assert!(
            packed
                .iter()
                .zip(&shape.apex)
                .all(|(a, b)| bits(a.apex) == bits(*b) && a.prop_shape == 0)
        );
        // An outline corner's apex is not its own position; a filled vertex's is.
        let own = |v: &SodVertex| v.position.map(f32::to_bits);
        assert_ne!(point(packed[4].apex), own(&shape.ir.vertices[4]));
        assert_eq!(point(packed[0].apex), own(&shape.ir.vertices[0]));
        assert_eq!(apex_vertices(&shape.apex, 0..1000, &[]).count(), 0);
    }

    /// Each vertex takes the shape word of the run it lies in, from any window.
    #[test]
    fn apex_vertices_carry_their_runs_shape_words() {
        let run = |first, end, shape| PropRun { first, end, shape };
        let runs = [run(2, 4, 7), run(4, 6, 9), run(10, 12, 0)];
        let apex = vec![[1.0, 2.0, 3.0, 0.0]; 14];
        let words = |range: Range<usize>| {
            apex_vertices(&apex, range, &runs)
                .map(|v| v.prop_shape)
                .collect::<Vec<_>>()
        };
        let whole = words(0..14);
        assert_eq!(whole, [0, 0, 8, 8, 10, 10, 0, 0, 0, 0, 1, 1, 0, 0]);
        assert_eq!(words(10..14), whole[10..14]);
        assert_eq!(words(3..5), whole[3..5]);
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
            mesh: Some(GpuMeshSlice {
                is_decal,
                ..slice(id, 3)
            }),
            bounds: None,
            discs: false,
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
            disc_depth_scale: 1.0,
            flattened_by: None,
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
                disc_depth_scale: 1.0,
                flattened_by: None,
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
            disc_depth_scale: 1.0,
            flattened_by: None,
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
            disc_depth_scale: 1.0,
            flattened_by: None,
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
            decal_tie: 0,
            list_rank: 0,
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

    /// Planning the world gives each node its own slice of the absolute index arena, the
    /// outline list and marks `plan_edges` gives for those slices, and no buffer.
    #[test]
    fn plan_outlined_gives_the_slices_and_outline_without_buffers() {
        let ir = two_node_ir(0.0);
        let mut slices = [Some(slice(0, 3)), Some(slice(3, 3))];
        let (edges, marks) = plan_edges(&mut slices, &ir, |_| true, &[0, 3, 6]);

        let (model, outline) = GpuModel::plan_outlined(&ir, |_| true, &[0, 3, 6]);
        assert!(model.buffers.is_none());
        assert_eq!(outline, edges);
        assert_eq!(model.nodes.len(), 2);
        for (node, (slice, marks)) in model.nodes.iter().zip(slices.iter().zip(&marks)) {
            assert_eq!(&node.mesh, slice);
            assert_eq!(&node.marks, marks);
        }
        // The child's indices address the whole vertex buffer: it draws vertices 3 to 5.
        let child = model.nodes[1].mesh.expect("a mesh");
        let start = child.index_offset as usize;
        assert_eq!(
            ir.indices[start..start + child.index_count as usize],
            [3, 4, 5]
        );
        assert_eq!(model.vertex_count, 6);
        assert_eq!(model.root_nodes, ir.root_nodes);
    }

    /// A meshless model holding only its box and whether it has discs.
    fn boxed_model(bounds: Option<NodeBounds>, discs: bool) -> GpuModel {
        GpuModel {
            name: "BOX".to_string(),
            buffers: None,
            vertex_count: 0,
            index_count: 0,
            nodes: Vec::new(),
            root_nodes: Vec::new(),
            bounds,
            discs,
        }
    }

    #[test]
    fn a_model_beside_the_view_is_kept_only_for_its_discs_under_a_zoomed_lens() {
        let beside = Some(boxed([20.0, 0.0, -10.0], 1.0));
        assert!(!boxed_model(beside, false).in_frustum(test_view_proj(), 1.0));
        assert!(!boxed_model(beside, false).in_frustum(test_view_proj(), 2.0));
        assert!(!boxed_model(beside, true).in_frustum(test_view_proj(), 1.0));
        assert!(boxed_model(beside, true).in_frustum(test_view_proj(), 2.0));
        let ahead = Some(boxed([0.0, 0.0, -10.0], 1.0));
        assert!(boxed_model(ahead, false).in_frustum(test_view_proj(), 1.0));
        assert!(!boxed_model(None, true).in_frustum(test_view_proj(), 2.0));
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

    /// `two_node_ir` with its child's vertices flagged as a disc rim.
    fn disc_child_ir(offset: f32) -> SodModelIr {
        let mut ir = two_node_ir(offset);
        for vertex in ir.vertices.iter_mut().skip(3) {
            vertex.flags |= VERTEX_FLAG_DISC;
        }
        ir
    }

    #[test]
    fn a_node_with_discs_marks_its_ancestors_but_not_its_children() {
        assert_eq!(node_discs(&two_node_ir(10.0)), vec![false, false]);
        // The child's vertices are the disc's: the parent holds them in its subtree.
        assert_eq!(node_discs(&disc_child_ir(10.0)), vec![true, true]);
        // The parent's own vertices are the disc's: its child holds none.
        let mut ir = two_node_ir(10.0);
        for vertex in ir.vertices.iter_mut().take(3) {
            vertex.flags |= VERTEX_FLAG_DISC;
        }
        assert_eq!(node_discs(&ir), vec![true, false]);
    }

    /// #644's world cull drops a baked prop whose box lies outside the view, and its disc rim
    /// vertices with it; `squeeze_disc` can bring one into the view under a zoomed lens, so the
    /// walk keeps a node whose subtree holds discs there, and still drops one without.
    #[test]
    fn the_world_walk_keeps_a_disc_node_beside_the_view_under_a_zoomed_lens() {
        let beside = Some(boxed([20.0, 0.0, -10.0], 1.0));
        let walk = |discs: bool, scale: f32| {
            let mut root = node(0, None, &[], false);
            root.bounds = beside;
            root.discs = discs;
            let nodes = [root];
            VisibleWalk {
                nodes: &nodes,
                roots: &[NodeId(0)],
                state_mask: 0,
                dist_sq: 0.0,
                eye: Vec3::ZERO,
                view: None,
                view_proj: Some(test_view_proj()),
                disc_depth_scale: scale,
                flattened_by: None,
            }
            .collect()
            .0
            .len()
        };
        assert_eq!(walk(true, 1.0), 0, "the default lens moves no rim");
        assert_eq!(
            walk(false, 2.0),
            0,
            "a node with no disc is outside the view"
        );
        assert_eq!(walk(true, 2.0), 1, "a zoomed lens can squeeze a rim in");
    }

    /// A disc node's plain child beside the view is dropped by its own box, not kept by its
    /// parent's discs.
    #[test]
    fn a_plain_child_of_a_disc_node_is_still_culled_by_its_own_box() {
        let mut root = node(0, None, &[1], false);
        root.bounds = Some(boxed([0.0, 0.0, -10.0], 30.0));
        root.discs = true;
        let mut child = node(1, Some(0), &[], false);
        child.bounds = Some(boxed([20.0, 0.0, -10.0], 1.0));
        let nodes = [root, child];
        let order: Vec<u32> = VisibleWalk {
            nodes: &nodes,
            roots: &[NodeId(0)],
            state_mask: 0,
            dist_sq: 0.0,
            eye: Vec3::ZERO,
            view: None,
            view_proj: Some(test_view_proj()),
            disc_depth_scale: 2.0,
            flattened_by: None,
        }
        .collect()
        .0
        .iter()
        .map(|mesh| mesh.index_offset)
        .collect();
        assert_eq!(order, vec![0]);
    }

    /// The gap in #644's world cull, on a synthetic disc: its centre and rim vertex both lie
    /// outside the left plane, so the box around them is culled, yet the vertex shader's
    /// `squeeze_disc` under a zoomed lens moves the rim vertex's clip `w` out and brings it
    /// inside the view.
    #[test]
    fn a_squeezed_rim_vertex_can_enter_the_view_from_a_culled_box() {
        let view_proj = test_view_proj();
        // Clip x grows with the model x at `a` per metre; the centre sits at clip x / w = 1.7
        // (w = 10 m deep) and the rim vertex 5 m behind it at 17 / 15 = 1.13, both beyond the
        // plane at 1.
        let a = view_proj.row(0).x;
        let x = 17.0 / a;
        let centre = Vec3::new(x, 0.0, -10.0);
        let rim = Vec3::new(x, 0.0, -15.0);
        let bounds = NodeBounds {
            min: centre.min(rim),
            max: centre.max(rim),
        };
        assert!(!frustum_keeps(view_proj, bounds), "the box is culled");
        let clip = |point: Vec3| view_proj * point.extend(1.0);
        // The shader's `squeeze_disc`: the rim's clip offset from the centre, depth terms scaled.
        let squeezed = |scale: f32| {
            let offset = clip(rim) - clip(centre);
            clip(centre) + glam::Vec4::new(offset.x, offset.y, offset.z * scale, offset.w * scale)
        };
        let inside = |c: glam::Vec4| c.x.abs() <= c.w;
        assert!(!inside(squeezed(1.0)), "an unzoomed rim stays outside");
        assert!(inside(squeezed(2.0)), "a zoomed rim enters the view");
        // So the walk keeps the disc's node under that lens, as its box alone would not.
        assert!(squeezes_discs(true, 2.0) && !squeezes_discs(true, 1.0));
    }
}
