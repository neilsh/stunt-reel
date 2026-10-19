//! GPU Mesh and Display-List Scene Graph Arena.
//!
//! Complies with Architectural Invariants:
//! - `[I2]` Flat contiguous arena allocation (`Vec<SodNode>` indexed by `NodeId(u32)`).
//! - `[I5]` Separation of base meshes from coplanar decal batches.

use crate::pipeline::ModelUniform;
use glam::Mat4;
use stunt_core::contracts::{NodeId, NodeKind, SodModelIr, SodVertex, VisibilityCondition};

/// Cached node data inside GPU model representation.
#[derive(Debug, Clone)]
pub struct GpuNode {
    pub id: NodeId,
    pub name: String,
    pub parent: Option<NodeId>,
    pub children: Vec<NodeId>,
    pub local_matrix: Mat4,
    pub visibility: VisibilityCondition,
    pub mesh: Option<GpuMeshSlice>,
}

/// Polygonal geometry slice pointing into consolidated GPU vertex and index buffers.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct GpuMeshSlice {
    pub vertex_offset: i32,
    pub index_offset: u32,
    pub index_count: u32,
    pub is_decal: bool,
}

/// GPU-resident representation of a transpiled `SodModelIr`.
#[derive(Debug)]
pub struct GpuModel {
    /// Model name identifier.
    pub name: String,
    /// Consolidated vertex buffer.
    pub vertex_buffer: wgpu::Buffer,
    /// Total vertex count.
    pub vertex_count: u32,
    /// Consolidated 32-bit index buffer.
    pub index_buffer: wgpu::Buffer,
    /// Total index count.
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
        // Vertex buffer
        let vertex_bytes: &[u8] = bytemuck::cast_slice(&ir.vertices);
        let vertex_buf_size = (vertex_bytes.len().max(std::mem::size_of::<SodVertex>())) as u64;
        let vertex_buffer = device.create_buffer(&wgpu::BufferDescriptor {
            label: Some(&format!("{}_vertex_buffer", ir.name)),
            size: vertex_buf_size,
            usage: wgpu::BufferUsages::VERTEX | wgpu::BufferUsages::COPY_DST,
            mapped_at_creation: false,
        });
        if !vertex_bytes.is_empty() {
            queue.write_buffer(&vertex_buffer, 0, vertex_bytes);
        }

        // Index buffer
        let index_bytes: &[u8] = bytemuck::cast_slice(&ir.indices);
        let index_buf_size = (index_bytes.len().max(std::mem::size_of::<u32>())) as u64;
        let index_buffer = device.create_buffer(&wgpu::BufferDescriptor {
            label: Some(&format!("{}_index_buffer", ir.name)),
            size: index_buf_size,
            usage: wgpu::BufferUsages::INDEX | wgpu::BufferUsages::COPY_DST,
            mapped_at_creation: false,
        });
        if !index_bytes.is_empty() {
            queue.write_buffer(&index_buffer, 0, index_bytes);
        }

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
        let mut nodes = Vec::with_capacity(ir.nodes.len());
        for node in &ir.nodes {
            let mesh = match &node.kind {
                NodeKind::Mesh {
                    vertex_offset,
                    index_offset,
                    index_count,
                    is_decal,
                    ..
                } => Some(GpuMeshSlice {
                    vertex_offset: *vertex_offset as i32,
                    index_offset: *index_offset,
                    index_count: *index_count,
                    is_decal: *is_decal,
                }),
                _ => None,
            };

            nodes.push(GpuNode {
                id: node.id,
                name: node.name.clone(),
                parent: node.parent,
                children: node.children.clone(),
                local_matrix: Mat4::from_cols_array(&node.local_matrix),
                visibility: node.visibility,
                mesh,
            });
        }

        Self {
            name: ir.name.clone(),
            vertex_buffer,
            vertex_count: ir.vertices.len() as u32,
            index_buffer,
            index_count: ir.indices.len() as u32,
            nodes,
            root_nodes: ir.root_nodes.clone(),
            model_uniform_buffer,
            model_bind_group,
        }
    }

    /// Updates the model-to-world transformation matrix in the GPU uniform buffer.
    pub fn update_world_matrix(&self, queue: &wgpu::Queue, matrix: &[f32; 16]) {
        let uniform = ModelUniform {
            model_matrix: *matrix,
        };
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

            if let Some(mesh) = node.mesh {
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
}
