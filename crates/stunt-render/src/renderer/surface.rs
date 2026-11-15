//! The presented surface, its configuration and its depth view.

use super::{RenderError, create_depth_view};

/// The presented surface, its configuration and its depth view.
pub(super) struct SurfaceTarget {
    pub(super) surface: wgpu::Surface<'static>,
    pub(super) config: wgpu::SurfaceConfiguration,
    pub(super) depth_view: wgpu::TextureView,
    max_texture_dimension_2d: u32,
}

impl SurfaceTarget {
    pub(super) fn new(
        surface: wgpu::Surface<'static>,
        adapter: &wgpu::Adapter,
        device: &wgpu::Device,
    ) -> Result<Self, RenderError> {
        let capabilities = surface.get_capabilities(adapter);
        let format = pick_surface_format(&capabilities.formats).ok_or_else(|| {
            RenderError::SurfaceConfig("the surface offers no texture format".to_string())
        })?;
        let alpha_mode = capabilities.alpha_modes.first().copied().ok_or_else(|| {
            RenderError::SurfaceConfig("the surface offers no alpha mode".to_string())
        })?;
        let max_texture_dimension_2d = adapter.limits().max_texture_dimension_2d;

        // The caller resizes to the window's inner size before the first draw.
        let config = wgpu::SurfaceConfiguration {
            usage: wgpu::TextureUsages::RENDER_ATTACHMENT,
            format,
            color_space: wgpu::SurfaceColorSpace::Auto,
            width: 1,
            height: 1,
            present_mode: wgpu::PresentMode::AutoVsync,
            desired_maximum_frame_latency: 2,
            alpha_mode,
            view_formats: vec![],
        };
        surface.configure(device, &config);
        let depth_view = create_depth_view(device, 1, 1);
        Ok(Self {
            surface,
            config,
            depth_view,
            max_texture_dimension_2d,
        })
    }

    pub(super) fn resize(&mut self, device: &wgpu::Device, width: u32, height: u32) {
        let width = width.clamp(1, self.max_texture_dimension_2d);
        let height = height.clamp(1, self.max_texture_dimension_2d);
        if self.config.width == width && self.config.height == height {
            return;
        }
        self.config.width = width;
        self.config.height = height;
        self.surface.configure(device, &self.config);
        self.depth_view = create_depth_view(device, width, height);
    }
}

/// The window surface format: plain Rgba8Unorm/Bgra8Unorm when offered, else the first.
///
/// The palette LUT holds display-ready Mode 13h colours, as the offscreen `Rgba8Unorm` target
/// stores them; an sRGB surface would encode them a second time and wash the window out.
fn pick_surface_format(formats: &[wgpu::TextureFormat]) -> Option<wgpu::TextureFormat> {
    formats
        .iter()
        .copied()
        .find(|format| {
            matches!(
                format,
                wgpu::TextureFormat::Rgba8Unorm | wgpu::TextureFormat::Bgra8Unorm
            )
        })
        .or_else(|| formats.first().copied())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn surface_format_prefers_non_srgb() {
        use wgpu::TextureFormat::{
            Bgra8Unorm, Bgra8UnormSrgb, Rgb10a2Unorm, Rgba8Unorm, Rgba8UnormSrgb,
        };
        assert_eq!(
            pick_surface_format(&[Bgra8UnormSrgb, Bgra8Unorm]),
            Some(Bgra8Unorm)
        );
        assert_eq!(
            pick_surface_format(&[Rgb10a2Unorm, Rgba8UnormSrgb, Rgba8Unorm]),
            Some(Rgba8Unorm)
        );
        // Nothing plain on offer: the surface's first format.
        assert_eq!(
            pick_surface_format(&[Bgra8UnormSrgb, Rgb10a2Unorm]),
            Some(Bgra8UnormSrgb)
        );
        assert_eq!(pick_surface_format(&[]), None);
    }
}
