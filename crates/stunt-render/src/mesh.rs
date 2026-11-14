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

use crate::pipeline::ModelUniform;
use glam::{Mat4, Vec3};
use stunt_core::contracts::{
    CameraTransform, NodeId, SodModelIr, SodVertex, VisibilityCondition, arena_index,
};
use stunt_core::world::GROUND_NODE;

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
    /// Uniform buffer for model-to-world transformation matrix.
    pub model_uniform_buffer: wgpu::Buffer,
    /// Bind group for `@group(2) @binding(0)`.
    pub model_bind_group: wgpu::BindGroup,
}

impl GpuModel {
    /// Uploads a `SodModelIr` into GPU buffers.
    pub fn from_ir(
        device: &wgpu::Device,
        queue: &wgpu::Queue,
        model_bind_group_layout: &wgpu::BindGroupLayout,
        ir: &SodModelIr,
    ) -> Self {
        Self::upload(device, queue, model_bind_group_layout, ir, None)
    }

    /// Like [`Self::from_ir`], and gives each mesh slice its outline for [`Self::draw_edges`]:
    /// every edge exactly one of the slice's triangles uses, as two indices into the same
    /// vertices, so it costs eight bytes an edge. Triangles with a corner `outlined` rejects
    /// are left out. A slice split over chunks is outlined per run, so a split also outlines
    /// the edges along its cut.
    pub fn from_ir_outlined(
        device: &wgpu::Device,
        queue: &wgpu::Queue,
        model_bind_group_layout: &wgpu::BindGroupLayout,
        ir: &SodModelIr,
        outlined: fn(&SodVertex) -> bool,
    ) -> Self {
        Self::upload(device, queue, model_bind_group_layout, ir, Some(outlined))
    }

    fn upload(
        device: &wgpu::Device,
        queue: &wgpu::Queue,
        model_bind_group_layout: &wgpu::BindGroupLayout,
        ir: &SodModelIr,
        outlined: Option<fn(&SodVertex) -> bool>,
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
        let edges = match outlined {
            Some(keep) => plan_edges(&mut plan, ir, keep),
            None => vec![Vec::new(); plan.chunks.len()],
        };
        let chunks = plan
            .chunks
            .iter()
            .zip(&edges)
            .enumerate()
            .map(|(n, (chunk, edges))| GpuChunk::upload(device, queue, ir, n, chunk, edges))
            .collect();

        // Model uniform buffer & bind group
        let model_uniform = ModelUniform::default();
        let model_uniform_buffer = device.create_buffer(&wgpu::BufferDescriptor {
            label: Some(&format!("{}_model_uniform", ir.name)),
            size: size_of::<ModelUniform>() as u64,
            usage: wgpu::BufferUsages::UNIFORM | wgpu::BufferUsages::COPY_DST,
            mapped_at_creation: false,
        });
        queue.write_buffer(&model_uniform_buffer, 0, bytemuck::bytes_of(&model_uniform));

        let model_bind_group = device.create_bind_group(&wgpu::BindGroupDescriptor {
            label: Some(&format!("{}_model_bind_group", ir.name)),
            layout: model_bind_group_layout,
            entries: &[wgpu::BindGroupEntry {
                binding: 0,
                resource: model_uniform_buffer.as_entire_binding(),
            }],
        });

        // Translate nodes into GpuNode flat arena
        let mut planned = plan.slices.into_iter();
        let nodes = ir
            .nodes
            .iter()
            .zip(&sources)
            .map(|(node, source)| GpuNode {
                id: node.id,
                name: node.name.clone(),
                parent: node.parent,
                children: node.children.clone(),
                local_matrix: Mat4::from_cols_array(&node.local_matrix),
                visibility: node.visibility,
                meshes: source.and_then(|_| planned.next()).unwrap_or_default(),
            })
            .collect();

        Self {
            name: ir.name.clone(),
            chunks,
            vertex_count: arena_index(ir.vertices.len()),
            index_count: arena_index(ir.indices.len()),
            nodes,
            root_nodes: ir.root_nodes.clone(),
            model_uniform_buffer,
            model_bind_group,
        }
    }

    /// Evaluates visibility and collects visible mesh slices split by decal pass flag.
    ///
    /// `eye` is the camera position in this model's space, for
    /// [`VisibilityCondition::FacesEye`]. `view` is the camera that tests
    /// [`VisibilityCondition::LodBranch`] and [`VisibilityCondition::BeyondDepth`] gates,
    /// whose points must then be in its space; without one every subtree branch and every
    /// far section is drawn and no stand-in is.
    ///
    /// Base slices come last sibling first, decal slices in the nodes' own order: the base
    /// pipeline's `Less` keeps the first draw of an exact depth tie and the decal pipeline's
    /// `LessEqual` the last, so both let `PLAYONE`'s later sibling win the tie.
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
        }
        .collect()
    }

    /// Like [`Self::collect_visible_meshes`] for the static world, with the slices of its
    /// [`GROUND_NODE`] nodes taken out first, in the nodes' own order: ground, base and decal
    /// slices. A ground slice is drawn over whatever is there, so the walk's order is the
    /// order `PLAYONE` paints the flat ground in (`world-scene.md` section 6.6).
    pub fn collect_world_meshes(
        &self,
        eye: Vec3,
        view: Option<&CameraTransform>,
    ) -> (Vec<GpuMeshSlice>, Vec<GpuMeshSlice>, Vec<GpuMeshSlice>) {
        VisibleWalk {
            nodes: &self.nodes,
            roots: &self.root_nodes,
            state_mask: 0,
            dist_sq: 0.0,
            eye,
            view,
        }
        .collect_world()
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
                rpass.set_index_buffer(chunk.index_buffer.slice(..), wgpu::IndexFormat::Uint32);
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
                rpass.set_index_buffer(chunk.edges.slice(..), wgpu::IndexFormat::Uint32);
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

/// Fills in each planned slice's outline and returns each chunk's edge indices.
fn plan_edges(
    plan: &mut UploadPlan,
    ir: &SodModelIr,
    keep: fn(&SodVertex) -> bool,
) -> Vec<Vec<u32>> {
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
    for slice in plan.slices.iter_mut().flatten() {
        let n = slice.chunk as usize;
        let (Some(chunk), Some(local), Some(out)) =
            (plan.chunks.get(n), local.get(n), edges.get_mut(n))
        else {
            continue;
        };
        let indices = chunk.indices.as_deref().unwrap_or(&ir.indices);
        let start = slice.index_offset as usize;
        let Some(triangles) = indices.get(start..start + slice.index_count as usize) else {
            continue;
        };
        let base = slice.vertex_offset.cast_unsigned();
        let vertex = |i: u32| {
            let at = base.saturating_add(i) as usize;
            let source = local.as_ref().map_or(Some(at), |l| l.get(at).copied())?;
            ir.vertices.get(source)
        };
        let found = crate::outline::boundary_edges(triangles, |i| vertex(i).is_some_and(keep));
        slice.edge_offset = arena_index(out.len());
        slice.edge_count = arena_index(2 * found.len());
        out.extend(found.into_iter().flatten());
    }
    edges
}

/// One vertex/index buffer pair of a [`GpuModel`].
#[derive(Debug)]
pub struct GpuChunk {
    /// Vertex buffer of the chunk.
    pub vertex_buffer: wgpu::Buffer,
    /// 32-bit index buffer of the chunk.
    pub index_buffer: wgpu::Buffer,
    /// 32-bit line-list index buffer of the chunk's outlines, into the same vertices.
    pub edges: wgpu::Buffer,
}

impl GpuChunk {
    fn upload(
        device: &wgpu::Device,
        queue: &wgpu::Queue,
        ir: &SodModelIr,
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
            index_buffer,
            edges: edge_buffer,
        }
    }
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
}

impl VisibleWalk<'_> {
    /// The visible base slices, last sibling first, and decal slices, in draw order.
    fn collect(&self) -> (Vec<GpuMeshSlice>, Vec<GpuMeshSlice>) {
        let (_, base, decals) = self.split(|_| false);
        (base, decals)
    }

    /// The visible ground slices in draw order, then [`Self::collect`]'s base and decal
    /// slices of the other nodes.
    fn collect_world(&self) -> (Vec<GpuMeshSlice>, Vec<GpuMeshSlice>, Vec<GpuMeshSlice>) {
        self.split(|node| node.name == GROUND_NODE)
    }

    /// The visible slices of the nodes `is_ground` picks, in draw order, then the others'
    /// base slices, last sibling first, and decal slices, in draw order.
    fn split(
        &self,
        is_ground: impl Fn(&GpuNode) -> bool,
    ) -> (Vec<GpuMeshSlice>, Vec<GpuMeshSlice>, Vec<GpuMeshSlice>) {
        let mut ground_meshes = Vec::new();
        let mut base_meshes = Vec::new();
        let mut decal_meshes = Vec::new();
        self.walk(false, |node, mesh| {
            if !is_ground(node) && !mesh.is_decal {
                base_meshes.push(mesh);
            }
        });
        self.walk(true, |node, mesh| {
            if is_ground(node) {
                ground_meshes.push(mesh);
            } else if mesh.is_decal {
                decal_meshes.push(mesh);
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
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

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
        let edges = plan_edges(&mut plan, &ir, |_| true);
        assert_eq!(edges, vec![vec![0, 1, 1, 2, 2, 3, 3, 0]]);
        let slice = plan.slices[0][0];
        assert_eq!((slice.edge_offset, slice.edge_count), (0, 8));
    }

    #[test]
    fn a_split_slice_is_outlined_per_run_in_chunk_indices() {
        let ir = quad_ir();
        // Three vertices a chunk: each triangle is its own run, and the cut is outlined twice.
        let mut plan = plan_upload(4, &ir.indices, &[source(0, 6)], 3, 6);
        let edges = plan_edges(&mut plan, &ir, |_| true);
        assert_eq!(edges.len(), 2);
        assert!(edges.iter().all(|e| e.len() == 6));
        for slice in &plan.slices[0] {
            assert_eq!(slice.edge_count, 6);
        }
        // Rejecting every vertex leaves no outline.
        let edges = plan_edges(&mut plan, &ir, |_| false);
        assert!(edges.iter().all(Vec::is_empty));
        assert!(plan.slices[0].iter().all(|s| s.edge_count == 0));
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
        };
        let (base, decal) = walk.collect();
        let order = |slices: &[GpuMeshSlice]| -> Vec<u32> {
            slices.iter().map(|s| s.index_offset).collect()
        };
        // `Less` keeps the first draw of a tie, so the later sibling must come first.
        assert_eq!(order(&base), vec![0, 3, 2, 1]);
        // `LessEqual` keeps the last draw, so decals keep the authored order.
        assert_eq!(order(&decal), vec![4, 5]);
    }
}
