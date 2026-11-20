//! The offscreen colour and plane targets, their readback buffers and the per-page capture.

use std::collections::VecDeque;

use crate::pipeline::PLANE_FORMAT;

use super::readback::read_back;
use super::{
    COLOR_FORMAT, Offscreen, Overlay, PageSink, PageSize, RenderError, RenderedPage,
    create_depth_view,
};

/// Bytes per texel of the colour target.
const COLOR_TEXEL_BYTES: u32 = 4;

/// Bytes per texel of the plane target: the layer and index word, then the shape word.
const PLANE_TEXEL_BYTES: u32 = 8;

/// Frames whose pages may be outstanding: one is read back while the next draws.
const FRAMES_IN_FLIGHT: usize = 2;

/// The offscreen colour and plane targets and their CPU readback buffers.
pub(super) struct OffscreenTarget {
    color_texture: wgpu::Texture,
    color_view: wgpu::TextureView,
    plane_texture: wgpu::Texture,
    plane_view: wgpu::TextureView,
    depth_view: wgpu::TextureView,
    /// A colour and a plane readback buffer per frame that may be in flight.
    readbacks: [Readback; FRAMES_IN_FLIGHT],
    /// The readback buffer the next submission fills.
    next_readback: usize,
    /// Submitted frames whose pages have not reached the sink, oldest first. The submission
    /// that fills the last slot drains the oldest before returning, so one slot is always free
    /// between calls.
    in_flight: VecDeque<InFlight>,
    pub(super) size: PageSize,
    padded_row_bytes: u32,
    plane_padded_row_bytes: u32,
    pub(super) viewport_rows: Option<u32>,
    sink: Box<dyn PageSink>,
}

/// The colour and plane readback buffers one submission copies its page into.
struct Readback {
    color: wgpu::Buffer,
    plane: wgpu::Buffer,
}

/// A submitted frame whose page is not read back yet.
struct InFlight {
    /// Index into `OffscreenTarget::readbacks` holding this frame's copy.
    readback: usize,
    /// The submission that wrote the copy; the readback waits for this one only, so a later
    /// frame's submission keeps running while this page is mapped.
    submission: wgpu::SubmissionIndex,
    /// What the frame paints over its page, owned because the frame is gone by readback.
    overlay: Option<Overlay>,
}

impl OffscreenTarget {
    pub(super) fn new(device: &wgpu::Device, target: Offscreen, sink: Box<dyn PageSink>) -> Self {
        let size = target.size;
        let extent = wgpu::Extent3d {
            width: size.width,
            height: size.height,
            depth_or_array_layers: 1,
        };
        let color_texture = device.create_texture(&wgpu::TextureDescriptor {
            label: Some("stunt_renderer_color_target"),
            size: extent,
            mip_level_count: 1,
            sample_count: 1,
            dimension: wgpu::TextureDimension::D2,
            format: COLOR_FORMAT,
            usage: wgpu::TextureUsages::RENDER_ATTACHMENT | wgpu::TextureUsages::COPY_SRC,
            view_formats: &[],
        });
        let color_view = color_texture.create_view(&wgpu::TextureViewDescriptor::default());

        let plane_texture = device.create_texture(&wgpu::TextureDescriptor {
            label: Some("stunt_renderer_plane_target"),
            size: extent,
            mip_level_count: 1,
            sample_count: 1,
            dimension: wgpu::TextureDimension::D2,
            format: PLANE_FORMAT,
            usage: wgpu::TextureUsages::RENDER_ATTACHMENT | wgpu::TextureUsages::COPY_SRC,
            view_formats: &[],
        });
        let plane_view = plane_texture.create_view(&wgpu::TextureViewDescriptor::default());

        let depth_view = create_depth_view(device, size.width, size.height);

        // Texture-to-buffer copies need a 256-byte row pitch; 320 * 4 = 1280 and 320 * 8 = 2560
        // already are one.
        let padded_row_bytes =
            (size.width * COLOR_TEXEL_BYTES).next_multiple_of(wgpu::COPY_BYTES_PER_ROW_ALIGNMENT);
        let plane_padded_row_bytes =
            (size.width * PLANE_TEXEL_BYTES).next_multiple_of(wgpu::COPY_BYTES_PER_ROW_ALIGNMENT);
        let buffer_size = u64::from(padded_row_bytes) * u64::from(size.height);
        let plane_buffer_size = u64::from(plane_padded_row_bytes) * u64::from(size.height);
        let readback_usage = wgpu::BufferUsages::COPY_DST | wgpu::BufferUsages::MAP_READ;
        let readbacks = std::array::from_fn(|_| Readback {
            color: device.create_buffer(&wgpu::BufferDescriptor {
                label: Some("stunt_renderer_readback_buffer"),
                size: buffer_size,
                usage: readback_usage,
                mapped_at_creation: false,
            }),
            plane: device.create_buffer(&wgpu::BufferDescriptor {
                label: Some("stunt_renderer_plane_readback_buffer"),
                size: plane_buffer_size,
                usage: readback_usage,
                mapped_at_creation: false,
            }),
        });

        Self {
            color_texture,
            color_view,
            plane_texture,
            plane_view,
            depth_view,
            readbacks,
            next_readback: 0,
            in_flight: VecDeque::new(),
            size,
            padded_row_bytes,
            plane_padded_row_bytes,
            viewport_rows: target.viewport_rows,
            sink,
        }
    }

    /// Clears both targets, runs the draw inside the pass, copies the page into a readback buffer
    /// and submits it, then retires the oldest page once two frames are in flight, so at most one
    /// stays queued between calls.
    pub(super) fn submit(
        &mut self,
        device: &wgpu::Device,
        queue: &wgpu::Queue,
        clear_color: wgpu::Color,
        clear_palette_index: u8,
        draw: impl FnOnce(&mut wgpu::RenderPass<'_>),
        overlay: Option<Overlay>,
    ) -> Result<(), RenderError> {
        let readback = self.next_readback;
        self.next_readback = (readback + 1) % FRAMES_IN_FLIGHT;

        let mut encoder = device.create_command_encoder(&wgpu::CommandEncoderDescriptor {
            label: Some("stunt_renderer_encoder"),
        });

        {
            let mut rpass = encoder.begin_render_pass(&wgpu::RenderPassDescriptor {
                label: Some("stunt_renderer_render_pass"),
                color_attachments: &[
                    Some(wgpu::RenderPassColorAttachment {
                        view: &self.color_view,
                        resolve_target: None,
                        depth_slice: None,
                        ops: wgpu::Operations {
                            load: wgpu::LoadOp::Clear(clear_color),
                            store: wgpu::StoreOp::Store,
                        },
                    }),
                    Some(wgpu::RenderPassColorAttachment {
                        view: &self.plane_view,
                        resolve_target: None,
                        depth_slice: None,
                        ops: wgpu::Operations {
                            load: wgpu::LoadOp::Clear(wgpu::Color {
                                r: f64::from(clear_palette_index),
                                g: 0.0,
                                b: 0.0,
                                a: 0.0,
                            }),
                            store: wgpu::StoreOp::Store,
                        },
                    }),
                ],
                depth_stencil_attachment: Some(wgpu::RenderPassDepthStencilAttachment {
                    view: &self.depth_view,
                    depth_ops: Some(wgpu::Operations {
                        load: wgpu::LoadOp::Clear(1.0),
                        store: wgpu::StoreOp::Store,
                    }),
                    stencil_ops: None,
                }),
                timestamp_writes: None,
                occlusion_query_set: None,
                multiview_mask: None,
            });

            if let Some(rows) = self.viewport_rows {
                rpass.set_viewport(0.0, 0.0, self.size.width as f32, rows as f32, 0.0, 1.0);
            }
            draw(&mut rpass);
        }

        let extent = wgpu::Extent3d {
            width: self.size.width,
            height: self.size.height,
            depth_or_array_layers: 1,
        };
        #[expect(
            clippy::indexing_slicing,
            reason = "readback counts from zero to FRAMES_IN_FLIGHT in steps of one"
        )]
        let buffers = &self.readbacks[readback];
        for (texture, buffer, padded_row_bytes) in [
            (&self.color_texture, &buffers.color, self.padded_row_bytes),
            (
                &self.plane_texture,
                &buffers.plane,
                self.plane_padded_row_bytes,
            ),
        ] {
            encoder.copy_texture_to_buffer(
                wgpu::TexelCopyTextureInfo {
                    texture,
                    mip_level: 0,
                    origin: wgpu::Origin3d::ZERO,
                    aspect: wgpu::TextureAspect::All,
                },
                wgpu::TexelCopyBufferInfo {
                    buffer,
                    layout: wgpu::TexelCopyBufferLayout {
                        offset: 0,
                        bytes_per_row: Some(padded_row_bytes),
                        rows_per_image: Some(self.size.height),
                    },
                },
                extent,
            );
        }

        let submission = queue.submit(Some(encoder.finish()));
        self.in_flight.push_back(InFlight {
            readback,
            submission,
            overlay,
        });
        if self.in_flight.len() == FRAMES_IN_FLIGHT {
            self.read_back_oldest(device)?;
        }
        Ok(())
    }

    /// Reads back every submitted frame, handing each page to the sink in submission order.
    pub(super) fn finish(&mut self, device: &wgpu::Device) -> Result<(), RenderError> {
        while !self.in_flight.is_empty() {
            self.read_back_oldest(device)?;
        }
        Ok(())
    }

    /// Maps the oldest submitted frame's buffers, builds its page and offers it to the sink once.
    fn read_back_oldest(&mut self, device: &wgpu::Device) -> Result<(), RenderError> {
        let Some(frame) = self.in_flight.pop_front() else {
            return Ok(());
        };
        #[expect(
            clippy::indexing_slicing,
            reason = "the recorded slot was below FRAMES_IN_FLIGHT when it was filled"
        )]
        let readback = &self.readbacks[frame.readback];
        let rgba = read_back(
            device,
            &readback.color,
            self.size.width,
            COLOR_TEXEL_BYTES,
            self.padded_row_bytes,
            &frame.submission,
        )?;
        let words: Vec<u32> = read_back(
            device,
            &readback.plane,
            self.size.width,
            PLANE_TEXEL_BYTES,
            self.plane_padded_row_bytes,
            &frame.submission,
        )?
        .as_chunks::<4>()
        .0
        .iter()
        .map(|word| u32::from_le_bytes(*word))
        .collect();
        // Each texel is two words: the layer and index word, then the shape word.
        let (plane, shapes): (Vec<u32>, Vec<u32>) = words
            .as_chunks::<2>()
            .0
            .iter()
            .map(|&[plane, shape]| (plane, shape))
            .unzip();

        let mut page = RenderedPage::new(self.size, rgba, &plane, &shapes)?;
        if let Some(overlay) = frame.overlay {
            overlay(&mut page);
        }
        self.sink.accept(page)?;
        Ok(())
    }
}
