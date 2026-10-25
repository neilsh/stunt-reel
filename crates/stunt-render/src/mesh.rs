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
use glam::Mat4;
use stunt_core::contracts::{NodeId, SodModelIr, SodVertex, VisibilityCondition};

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
    /// First vertex of the slice within the consolidated vertex buffer.
    pub vertex_offset: i32,
    /// First index of the slice within the consolidated index buffer.
    pub index_offset: u32,
    /// Number of indices in the slice (three per triangle).
    pub index_count: u32,
    /// Whether the slice is a coplanar decal drawn through the depth-bias pipeline `[I5]`.
    pub is_decal: bool,
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
        let limit = device.limits().max_buffer_size;
        let max_vertices = (limit / std::mem::size_of::<SodVertex>() as u64) as usize;
        let max_indices = (limit / std::mem::size_of::<u32>() as u64) as usize;
        // One source per mesh slice, keyed by node so the planned slices can be handed
        // back to the same nodes. `meshes()` already skips a node whose window is unsafe.
        let mut sources: Vec<Option<SourceSlice>> = vec![None; ir.nodes.len()];
        for mesh in ir.meshes() {
            sources[mesh.node.id.0 as usize] = Some(SourceSlice {
                vertex_offset: mesh.vertex_offset,
                index_offset: mesh.index_offset,
                index_count: mesh.indices.len() as u32,
                is_decal: mesh.is_decal(),
            });
        }
        let mesh_sources: Vec<SourceSlice> = sources.iter().flatten().copied().collect();
        let plan = plan_upload(
            ir.vertices.len(),
            &ir.indices,
            &mesh_sources,
            max_vertices,
            max_indices,
        );
        let chunks = plan
            .chunks
            .iter()
            .enumerate()
            .map(|(n, chunk)| GpuChunk::upload(device, queue, ir, n, chunk))
            .collect();

        // Model uniform buffer & bind group
        let model_uniform = ModelUniform::default();
        let model_uniform_buffer = device.create_buffer(&wgpu::BufferDescriptor {
            label: Some(&format!("{}_model_uniform", ir.name)),
            size: std::mem::size_of::<ModelUniform>() as u64,
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
            vertex_count: ir.vertices.len() as u32,
            index_count: ir.indices.len() as u32,
            nodes,
            root_nodes: ir.root_nodes.clone(),
            model_uniform_buffer,
            model_bind_group,
        }
    }

    /// Updates the model-to-world transformation matrix in the GPU uniform buffer.
    pub fn update_world_matrix(&self, queue: &wgpu::Queue, matrix: &[f32; 16]) {
        let uniform = ModelUniform::new(*matrix, 0);
        queue.write_buffer(&self.model_uniform_buffer, 0, bytemuck::bytes_of(&uniform));
    }

    /// Evaluates visibility and collects visible mesh slices split by decal pass flag.
    pub fn collect_visible_meshes(
        &self,
        state_mask: u16,
        distance_to_cam: f32,
    ) -> (Vec<GpuMeshSlice>, Vec<GpuMeshSlice>) {
        let mut base_meshes = Vec::new();
        let mut decal_meshes = Vec::new();

        let dist_sq = distance_to_cam * distance_to_cam;

        // Traverse flat arena starting from root nodes
        let mut stack = Vec::new();
        for &root_id in &self.root_nodes {
            stack.push(root_id);
        }

        while let Some(node_id) = stack.pop() {
            let Some(node) = self.nodes.get(node_id.0 as usize) else {
                continue;
            };

            // Evaluate dynamic visibility condition
            let is_visible = match node.visibility {
                VisibilityCondition::Always => true,
                VisibilityCondition::LodDistanceSq(max_sq) => dist_sq <= max_sq,
                VisibilityCondition::ActorState { mask, expected } => {
                    (state_mask & mask) == expected
                }
                VisibilityCondition::AngleCone { .. } => true, // default visible if cone not tested
            };

            if !is_visible {
                continue;
            }

            for &mesh in &node.meshes {
                if mesh.is_decal {
                    decal_meshes.push(mesh);
                } else {
                    base_meshes.push(mesh);
                }
            }

            for &child_id in &node.children {
                stack.push(child_id);
            }
        }

        (base_meshes, decal_meshes)
    }

    /// Encodes `meshes` into `rpass`, binding each slice's chunk buffers when it changes.
    ///
    /// The pipeline and bind groups must already be set.
    pub fn draw_slices(&self, rpass: &mut wgpu::RenderPass<'_>, meshes: &[GpuMeshSlice]) {
        let mut bound = None;
        for mesh in meshes {
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
}

/// One vertex/index buffer pair of a [`GpuModel`].
#[derive(Debug)]
pub struct GpuChunk {
    /// Vertex buffer of the chunk.
    pub vertex_buffer: wgpu::Buffer,
    /// 32-bit index buffer of the chunk.
    pub index_buffer: wgpu::Buffer,
}

impl GpuChunk {
    fn upload(
        device: &wgpu::Device,
        queue: &wgpu::Queue,
        ir: &SodModelIr,
        n: usize,
        plan: &ChunkPlan,
    ) -> Self {
        // Chunk 0 keeps the labels of an unsplit model.
        let suffix = if n == 0 {
            String::new()
        } else {
            format!("_{n}")
        };
        let vertex_size = std::mem::size_of::<SodVertex>();
        let vertex_buffer = device.create_buffer(&wgpu::BufferDescriptor {
            label: Some(&format!("{}_vertex_buffer{suffix}", ir.name)),
            size: (plan.vertex_count.max(1) * vertex_size) as u64,
            usage: wgpu::BufferUsages::VERTEX | wgpu::BufferUsages::COPY_DST,
            mapped_at_creation: false,
        });
        let mut offset = 0;
        for range in &plan.vertex_ranges {
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
            size: (index_bytes.len().max(std::mem::size_of::<u32>())) as u64,
            usage: wgpu::BufferUsages::INDEX | wgpu::BufferUsages::COPY_DST,
            mapped_at_creation: false,
        });
        if !index_bytes.is_empty() {
            queue.write_buffer(&index_buffer, 0, index_bytes);
        }
        Self {
            vertex_buffer,
            index_buffer,
        }
    }
}

/// A mesh node's slice as the IR stores it: an index plus `vertex_offset` is a vertex.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) struct SourceSlice {
    pub vertex_offset: u32,
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
                vec![GpuMeshSlice {
                    chunk: 0,
                    vertex_offset: s.vertex_offset as i32,
                    index_offset: s.index_offset,
                    index_count: s.index_count,
                    is_decal: s.is_decal,
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
        let base = source.vertex_offset as usize;
        // The open run: its source vertex window and its triangles as source vertices.
        let mut run: Option<(Range<usize>, Vec<[usize; 3]>)> = None;
        for tri in indices[start..end].as_chunks::<3>().0 {
            let tri = tri.map(|v| base + v as usize);
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

/// Appends a run to the last chunk and returns its draw slice.
fn flush_run(
    chunks: &mut [ChunkPlan],
    is_decal: bool,
    window: Range<usize>,
    tris: &[[usize; 3]],
) -> GpuMeshSlice {
    let n = chunks.len() - 1;
    let chunk = &mut chunks[n];
    let indices = chunk.indices.get_or_insert_with(Vec::new);
    let slice = GpuMeshSlice {
        chunk: n as u32,
        vertex_offset: chunk.vertex_count as i32,
        index_offset: indices.len() as u32,
        index_count: 3 * tris.len() as u32,
        is_decal,
    };
    indices.extend(tris.iter().flatten().map(|&v| (v - window.start) as u32));
    chunk.vertex_count += window.len();
    chunk.vertex_ranges.push(window);
    slice
}

#[cfg(test)]
mod tests {
    use super::*;

    fn source(vertex_offset: u32, index_offset: u32, index_count: u32) -> SourceSlice {
        SourceSlice {
            vertex_offset,
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
                out.push(local[(slice.vertex_offset as u32 + i) as usize]);
            }
        }
        out
    }

    #[test]
    fn model_within_budget_is_one_unchanged_chunk() {
        let indices = [0, 1, 2, 0, 2, 3];
        let plan = plan_upload(4, &indices, &[source(0, 0, 3), source(1, 3, 3)], 4, 6);
        assert_eq!(plan.chunks.len(), 1);
        assert_eq!(plan.chunks[0].vertex_ranges.first(), Some(&(0..4)));
        assert_eq!(plan.chunks[0].indices, None);
        assert_eq!(plan.slices[1][0].vertex_offset, 1);
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
        let base_count = indices.len() as u32;
        indices.extend([40, 41, 42]);
        let sources = [
            source(0, 0, base_count),
            SourceSlice {
                is_decal: true,
                ..source(0, base_count, 3)
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
    fn split_honours_vertex_offset_and_keeps_whole_triangles() {
        let indices = [0, 1, 2, 2, 3, 4];
        let plan = plan_upload(10, &indices, &[source(5, 0, 6)], 6, 9);
        // Every index addresses the vertex window from offset 5 onward; the run copies the
        // contiguous window 5..10 and rebases the indices into it.
        assert_eq!(drawn(&plan, &plan.slices[0]), vec![5, 6, 7, 7, 8, 9]);
    }
}
