//! The world stream's GPU buffer: one growable buffer holding the frame's vertex, apex, index
//! and outline sections, written once a frame.
//!
//! [`StreamBuffers::write`] packs a [`WorldStream`]'s four sections back to back and uploads them
//! with one `write_buffer`; [`StreamBuffers::draw_slices`] and [`StreamBuffers::draw_edges`] then
//! draw the slices [`WorldStream::restage`] rewrote, as [`GpuModel`](crate::mesh::GpuModel) draws its own.

use std::mem::size_of;
use std::ops::Range;

use stunt_core::contracts::SodVertex;

use crate::mesh::{ApexVertex, GpuMeshSlice};
use crate::world_stream::WorldStream;

/// The smallest buffer the stream creates, in bytes.
///
/// The probe's largest frame is `3.74` MiB with a 12 B apex, and `75,576 * 4` B more with the
/// 16 B [`ApexVertex`], about `4.03` MiB (journal, 2026-11-23): 8 MiB holds it. Another film,
/// lens or viewport may need more, which [`grown_capacity`] handles.
const MIN_CAPACITY: u64 = 8 << 20;

/// Where each section of a frame's stream lies in the buffer, in bytes.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub(crate) struct StreamLayout {
    /// The [`SodVertex`] section, vertex buffer 0.
    pub vertices: Range<u64>,
    /// The [`ApexVertex`] section, vertex buffer 1.
    pub apex: Range<u64>,
    /// The `u32` triangle indices.
    pub indices: Range<u64>,
    /// The `u32` outline indices.
    pub edges: Range<u64>,
    /// The bytes the sections span.
    pub len: u64,
}

/// `count` items of `stride` bytes laid out from `start`, with the section's end.
fn section(start: u64, count: usize, stride: usize) -> Range<u64> {
    let bytes = count as u64 * stride as u64;
    assert!(
        bytes.is_multiple_of(wgpu::COPY_BUFFER_ALIGNMENT)
            && start.is_multiple_of(wgpu::COPY_BUFFER_ALIGNMENT),
        "a section is a whole number of 4 B words"
    );
    start..start + bytes
}

/// The sections of `stream` back to back: vertices, apex, indices, then outline indices, each
/// exactly `count * stride` bytes long, since a draw is checked against the bound slice's size.
pub(crate) fn layout(stream: &WorldStream) -> StreamLayout {
    let vertices = section(0, stream.vertices.len(), size_of::<SodVertex>());
    let apex = section(vertices.end, stream.apex.len(), size_of::<ApexVertex>());
    let indices = section(apex.end, stream.indices.len(), size_of::<u32>());
    let edges = section(indices.end, stream.edges.len(), size_of::<u32>());
    StreamLayout {
        len: edges.end,
        vertices,
        apex,
        indices,
        edges,
    }
}

/// The capacity a buffer of `current` bytes needs to hold `needed`: `current` when it fits,
/// otherwise the next power of two at or above `needed` and twice `current`, and at least
/// [`MIN_CAPACITY`]. Never smaller than `current`.
pub(crate) fn grown_capacity(current: u64, needed: u64) -> u64 {
    if needed <= current {
        return current;
    }
    needed
        .max(current.saturating_mul(2))
        .max(MIN_CAPACITY)
        .next_power_of_two()
}

/// The GPU copy of a [`WorldStream`], rewritten each frame.
///
/// Two frames in flight need no second buffer: `write_buffer` is ordered on the queue after
/// the submission that read the previous contents, and the renderer prepares once per submit.
#[derive(Debug, Default)]
pub(crate) struct StreamBuffers {
    /// The buffer, created by the first non-empty write.
    buffer: Option<wgpu::Buffer>,
    /// `buffer`'s size in bytes.
    capacity: u64,
    /// Where the last write put each section.
    layout: StreamLayout,
    /// The packed sections, kept between frames.
    staging: Vec<u8>,
}

impl StreamBuffers {
    /// Uploads `stream` with one `write_buffer`, growing the buffer first when it does not
    /// fit; an empty stream writes nothing and draws nothing.
    pub(crate) fn write(
        &mut self,
        device: &wgpu::Device,
        queue: &wgpu::Queue,
        stream: &WorldStream,
    ) {
        self.layout = layout(stream);
        if self.layout.len == 0 {
            return;
        }
        let capacity = grown_capacity(self.capacity, self.layout.len);
        if self.buffer.is_none() || capacity != self.capacity {
            self.buffer = Some(device.create_buffer(&wgpu::BufferDescriptor {
                label: Some("stunt_world_stream"),
                size: capacity,
                usage: wgpu::BufferUsages::VERTEX
                    | wgpu::BufferUsages::INDEX
                    | wgpu::BufferUsages::COPY_DST,
                mapped_at_creation: false,
            }));
            self.capacity = capacity;
        }
        self.staging.clear();
        self.staging
            .extend_from_slice(bytemuck::cast_slice(&stream.vertices));
        self.staging
            .extend_from_slice(bytemuck::cast_slice(&stream.apex));
        self.staging
            .extend_from_slice(bytemuck::cast_slice(&stream.indices));
        self.staging
            .extend_from_slice(bytemuck::cast_slice(&stream.edges));
        debug_assert_eq!(
            self.staging.len() as u64,
            self.layout.len,
            "the packed sections fill the layout"
        );
        if let Some(buffer) = &self.buffer {
            queue.write_buffer(buffer, 0, &self.staging);
        }
    }

    /// Encodes `meshes`' triangles into `rpass`, one `draw_indexed` a slice, the sections bound
    /// once. The pipeline and bind groups must already be set.
    pub(crate) fn draw_slices(&self, rpass: &mut wgpu::RenderPass<'_>, meshes: &[GpuMeshSlice]) {
        if !self.bind(rpass, &self.layout.indices) {
            return;
        }
        for mesh in meshes {
            rpass.draw_indexed(
                mesh.index_offset..mesh.index_offset + mesh.index_count,
                0,
                0..1,
            );
        }
    }

    /// Encodes `meshes`' outlines into `rpass` as a line list, skipping slices without one.
    pub(crate) fn draw_edges(&self, rpass: &mut wgpu::RenderPass<'_>, meshes: &[GpuMeshSlice]) {
        if !self.bind(rpass, &self.layout.edges) {
            return;
        }
        for mesh in meshes.iter().filter(|m| m.edge_count > 0) {
            rpass.draw_indexed(
                mesh.edge_offset..mesh.edge_offset + mesh.edge_count,
                0,
                0..1,
            );
        }
    }

    /// Binds the vertex sections and `indices` as the index buffer; false, binding nothing,
    /// while nothing was written or when the section is empty.
    fn bind(&self, rpass: &mut wgpu::RenderPass<'_>, indices: &Range<u64>) -> bool {
        let Some(buffer) = self.buffer.as_ref().filter(|_| !indices.is_empty()) else {
            return false;
        };
        rpass.set_vertex_buffer(0, buffer.slice(self.layout.vertices.clone()));
        rpass.set_vertex_buffer(1, buffer.slice(self.layout.apex.clone()));
        rpass.set_index_buffer(buffer.slice(indices.clone()), wgpu::IndexFormat::Uint32);
        true
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::mesh::ApexVertex;

    fn stream(vertices: usize, indices: usize, edges: usize) -> WorldStream {
        WorldStream {
            vertices: vec![bytemuck::Zeroable::zeroed(); vertices],
            apex: vec![ApexVertex::default(); vertices],
            indices: vec![0; indices],
            edges: vec![0; edges],
            ..WorldStream::default()
        }
    }

    #[test]
    fn sections_lie_back_to_back_and_aligned() {
        let layout = layout(&stream(3, 6, 8));
        assert_eq!(layout.vertices, 0..84);
        assert_eq!(layout.apex, 84..132);
        assert_eq!(layout.indices, 132..156);
        assert_eq!(layout.edges, 156..188);
        assert_eq!(layout.len, 188);
        for start in [
            layout.vertices.start,
            layout.apex.start,
            layout.indices.start,
            layout.edges.start,
        ] {
            assert_eq!(start % wgpu::COPY_BUFFER_ALIGNMENT, 0);
            assert_eq!(start % 4, 0, "an index buffer slice starts on a word");
        }
        assert_eq!(super::layout(&stream(0, 0, 0)), StreamLayout::default());
    }

    #[test]
    fn capacity_keeps_doubles_rounds_up_and_never_shrinks() {
        let mib = 1u64 << 20;
        assert_eq!(grown_capacity(0, 100), MIN_CAPACITY, "the floor");
        assert_eq!(grown_capacity(8 * mib, 5 * mib), 8 * mib, "fits");
        assert_eq!(grown_capacity(8 * mib, 8 * mib), 8 * mib, "fits exactly");
        assert_eq!(
            grown_capacity(8 * mib, 8 * mib + 1),
            16 * mib,
            "at least double"
        );
        assert_eq!(
            grown_capacity(8 * mib, 40 * mib),
            64 * mib,
            "next power of two"
        );
        assert_eq!(grown_capacity(64 * mib, 1), 64 * mib, "never shrinks");
        assert_eq!(grown_capacity(16 * mib, 17 * mib), 32 * mib);
    }
}
