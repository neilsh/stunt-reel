//! The offscreen colour and plane targets, their readback buffers and the per-page capture.

use crate::pipeline::PLANE_FORMAT;

use super::readback::read_back;
use super::{
    COLOR_FORMAT, Offscreen, PageSink, PageSize, RenderError, RenderedPage, create_depth_view,
};

/// The offscreen colour and plane targets and their CPU readback buffers.
pub(super) struct OffscreenTarget {
    color_texture: wgpu::Texture,
    color_view: wgpu::TextureView,
    plane_texture: wgpu::Texture,
    plane_view: wgpu::TextureView,
    depth_view: wgpu::TextureView,
    readback_buffer: wgpu::Buffer,
    plane_readback_buffer: wgpu::Buffer,
    pub(super) size: PageSize,
    padded_row_bytes: u32,
    pub(super) viewport_rows: Option<u32>,
    sink: Box<dyn PageSink>,
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

        // Texture-to-buffer copies need a 256-byte row pitch; 320 * 4 = 1280 already is one.
        let padded_row_bytes =
            (size.width * 4).next_multiple_of(wgpu::COPY_BYTES_PER_ROW_ALIGNMENT);
        let buffer_size = u64::from(padded_row_bytes) * u64::from(size.height);
        let readback_usage = wgpu::BufferUsages::COPY_DST | wgpu::BufferUsages::MAP_READ;
        let readback_buffer = device.create_buffer(&wgpu::BufferDescriptor {
            label: Some("stunt_renderer_readback_buffer"),
            size: buffer_size,
            usage: readback_usage,
            mapped_at_creation: false,
        });
        let plane_readback_buffer = device.create_buffer(&wgpu::BufferDescriptor {
            label: Some("stunt_renderer_plane_readback_buffer"),
            size: buffer_size,
            usage: readback_usage,
            mapped_at_creation: false,
        });

        Self {
            color_texture,
            color_view,
            plane_texture,
            plane_view,
            depth_view,
            readback_buffer,
            plane_readback_buffer,
            size,
            padded_row_bytes,
            viewport_rows: target.viewport_rows,
            sink,
        }
    }

    /// Clears both targets, runs the draw inside the pass, reads the page back and offers it to
    /// the sink exactly once.
    pub(super) fn capture(
        &mut self,
        device: &wgpu::Device,
        queue: &wgpu::Queue,
        clear_color: wgpu::Color,
        clear_palette_index: u8,
        draw: impl FnOnce(&mut wgpu::RenderPass<'_>),
        overlay: impl FnOnce(&mut RenderedPage),
    ) -> Result<(), RenderError> {
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
        for (texture, buffer) in [
            (&self.color_texture, &self.readback_buffer),
            (&self.plane_texture, &self.plane_readback_buffer),
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
                        bytes_per_row: Some(self.padded_row_bytes),
                        rows_per_image: Some(self.size.height),
                    },
                },
                extent,
            );
        }

        queue.submit(Some(encoder.finish()));

        let rgba = read_back(
            device,
            &self.readback_buffer,
            self.size.width,
            self.padded_row_bytes,
        )?;
        let plane: Vec<u32> = read_back(
            device,
            &self.plane_readback_buffer,
            self.size.width,
            self.padded_row_bytes,
        )?
        .as_chunks::<4>()
        .0
        .iter()
        .map(|word| u32::from_le_bytes(*word))
        .collect();

        let mut page = RenderedPage::new(self.size, rgba, &plane)?;
        overlay(&mut page);
        self.sink.accept(page)?;
        Ok(())
    }
}
