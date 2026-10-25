//! Mode 13h 256x32 Palette Lookup Texture (LUT) Generator.
//!
//! Complies with Architectural Invariant `[I3]` (Authentic 8-bit VGA Mode 13h palette index color mapping).

use stunt_core::contracts::{MODE_13H_PALETTE, PaletteControls};

/// Width of the palette lookup texture in texels (256 distinct palette indices).
pub const PALETTE_LUT_WIDTH: u32 = 256;

/// Height of the palette lookup texture in texels (32 discrete directional lighting levels).
pub const PALETTE_LUT_HEIGHT: u32 = 32;

/// Total byte size of the uncompressed 256x32 RGBA8 lookup texture (32,768 bytes).
pub(crate) const PALETTE_LUT_BYTE_SIZE: usize =
    (PALETTE_LUT_WIDTH * PALETTE_LUT_HEIGHT * 4) as usize;

/// Generates the 256x32 RGBA8 lookup table texture bytes for the static Mode 13h table.
///
/// - X coordinate (`0..=255`): Authentic VGA Mode 13h palette index.
/// - Y coordinate (`0..=31`): Discrete directional lighting / ambient level,
///   where row 0 is ambient floor (0.2) and row 31 is full direct sunlight (1.0).
pub fn build_palette_lut_bytes() -> [u8; PALETTE_LUT_BYTE_SIZE] {
    build_palette_lut_bytes_from(&MODE_13H_PALETTE)
}

/// Generates the 256x32 RGBA8 lookup table texture bytes for `palette`, laid out as in
/// [`build_palette_lut_bytes`].
pub fn build_palette_lut_bytes_from(palette: &[(u8, u8, u8); 256]) -> [u8; PALETTE_LUT_BYTE_SIZE] {
    let mut lut_bytes = [0u8; PALETTE_LUT_BYTE_SIZE];

    for level in 0..PALETTE_LUT_HEIGHT {
        // Discrete shading factor: row 0 is ambient floor (0.2), row 31 is full sun (1.0)
        let factor = 0.2 + 0.8 * (level as f32 / 31.0);

        for color_idx in 0..PALETTE_LUT_WIDTH {
            let (r0, g0, b0) = palette[color_idx as usize];
            let r = (r0 as f32 * factor).round().clamp(0.0, 255.0) as u8;
            let g = (g0 as f32 * factor).round().clamp(0.0, 255.0) as u8;
            let b = (b0 as f32 * factor).round().clamp(0.0, 255.0) as u8;

            let offset = ((level * PALETTE_LUT_WIDTH + color_idx) * 4) as usize;
            lut_bytes[offset] = r;
            lut_bytes[offset + 1] = g;
            lut_bytes[offset + 2] = b;
            lut_bytes[offset + 3] = 255;
        }
    }

    lut_bytes
}

/// GPU-resident representation of the Mode 13h 256x32 palette LUT.
///
/// Starts with the static table; [`Self::set_controls`] switches it to the film palette
/// for a frame's [`PaletteControls`].
#[derive(Debug)]
pub(crate) struct PaletteLut {
    /// Texture handle on the device.
    pub(crate) texture: wgpu::Texture,
    /// Bind group containing the palette LUT texture at `@binding(0)`.
    pub(crate) bind_group: wgpu::BindGroup,
    /// Shared bind group layout.
    pub(crate) bind_group_layout: wgpu::BindGroupLayout,
    /// Palette currently in the texture.
    palette: [(u8, u8, u8); 256],
    /// Controls the texture was built from; `None` for the static table.
    controls: Option<PaletteControls>,
}

impl PaletteLut {
    /// Creates the bind group layout for `@group(1) @binding(0) var palette_lut: texture_2d<f32>;`.
    pub(crate) fn create_bind_group_layout(device: &wgpu::Device) -> wgpu::BindGroupLayout {
        device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
            label: Some("stunt_mode13h_palette_lut_layout"),
            entries: &[wgpu::BindGroupLayoutEntry {
                binding: 0,
                visibility: wgpu::ShaderStages::FRAGMENT,
                ty: wgpu::BindingType::Texture {
                    sample_type: wgpu::TextureSampleType::Float { filterable: false },
                    view_dimension: wgpu::TextureViewDimension::D2,
                    multisampled: false,
                },
                count: None,
            }],
        })
    }

    /// Initializes and uploads the 256x32 palette texture to GPU memory.
    pub(crate) fn new(device: &wgpu::Device, queue: &wgpu::Queue) -> Self {
        let bind_group_layout = Self::create_bind_group_layout(device);
        let lut_bytes = build_palette_lut_bytes();

        let texture = device.create_texture(&wgpu::TextureDescriptor {
            label: Some("stunt_mode13h_palette_lut_texture"),
            size: wgpu::Extent3d {
                width: PALETTE_LUT_WIDTH,
                height: PALETTE_LUT_HEIGHT,
                depth_or_array_layers: 1,
            },
            mip_level_count: 1,
            sample_count: 1,
            dimension: wgpu::TextureDimension::D2,
            format: wgpu::TextureFormat::Rgba8Unorm,
            usage: wgpu::TextureUsages::TEXTURE_BINDING | wgpu::TextureUsages::COPY_DST,
            view_formats: &[],
        });

        Self::write_texture(queue, &texture, &lut_bytes);

        let view = texture.create_view(&wgpu::TextureViewDescriptor::default());

        let bind_group = device.create_bind_group(&wgpu::BindGroupDescriptor {
            label: Some("stunt_mode13h_palette_lut_bind_group"),
            layout: &bind_group_layout,
            entries: &[wgpu::BindGroupEntry {
                binding: 0,
                resource: wgpu::BindingResource::TextureView(&view),
            }],
        });

        Self {
            texture,
            bind_group,
            bind_group_layout,
            palette: MODE_13H_PALETTE,
            controls: None,
        }
    }

    /// Rebuilds the texture from the film palette for `controls`, if they changed.
    pub(crate) fn set_controls(&mut self, queue: &wgpu::Queue, controls: PaletteControls) {
        if self.controls != Some(controls) {
            self.upload(queue, controls.film_palette(), Some(controls));
        }
    }

    /// Normalized `(R, G, B)` of `index` in the palette currently loaded.
    #[must_use]
    pub(crate) fn rgb_float(&self, index: u8) -> (f32, f32, f32) {
        let (r, g, b) = self.palette[usize::from(index)];
        (
            f32::from(r) / 255.0,
            f32::from(g) / 255.0,
            f32::from(b) / 255.0,
        )
    }

    fn upload(
        &mut self,
        queue: &wgpu::Queue,
        palette: [(u8, u8, u8); 256],
        controls: Option<PaletteControls>,
    ) {
        Self::write_texture(
            queue,
            &self.texture,
            &build_palette_lut_bytes_from(&palette),
        );
        self.palette = palette;
        self.controls = controls;
    }

    fn write_texture(queue: &wgpu::Queue, texture: &wgpu::Texture, lut_bytes: &[u8]) {
        queue.write_texture(
            wgpu::TexelCopyTextureInfo {
                texture,
                mip_level: 0,
                origin: wgpu::Origin3d::ZERO,
                aspect: wgpu::TextureAspect::All,
            },
            lut_bytes,
            wgpu::TexelCopyBufferLayout {
                offset: 0,
                bytes_per_row: Some(PALETTE_LUT_WIDTH * 4),
                rows_per_image: Some(PALETTE_LUT_HEIGHT),
            },
            wgpu::Extent3d {
                width: PALETTE_LUT_WIDTH,
                height: PALETTE_LUT_HEIGHT,
                depth_or_array_layers: 1,
            },
        );
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_palette_lut_dimensions_and_bytes() {
        let bytes = build_palette_lut_bytes();
        assert_eq!(bytes.len(), 32768);

        // Row 31 (full brightness, level = 31, factor = 1.0)
        // Color 0: (0, 0, 0, 255)
        let row31_c0 = 31 * 256 * 4;
        assert_eq!(&bytes[row31_c0..row31_c0 + 4], &[0, 0, 0, 255]);

        // Color 255: (252, 252, 252, 255)
        let row31_c255 = ((31 * 256 + 255) * 4) as usize;
        assert_eq!(&bytes[row31_c255..row31_c255 + 4], &[252, 252, 252, 255]);

        // Row 0 (ambient floor, level = 0, factor = 0.2)
        // Color 255: 252 * 0.2 = 50.4 -> 50
        let row0_c255 = 255 * 4;
        assert_eq!(&bytes[row0_c255..row0_c255 + 4], &[50, 50, 50, 255]);
    }

    #[test]
    fn film_palette_lut_uses_the_given_palette() {
        let faded = PaletteControls {
            brightness: 0,
            ..PaletteControls::default()
        };
        let bytes = build_palette_lut_bytes_from(&faded.film_palette());
        // Row 31, entry 63 (a scene grey) is black; entry 255 (UI white) is untouched.
        let row31 = 31 * 256 * 4;
        assert_eq!(&bytes[row31 + 63 * 4..row31 + 64 * 4], &[0, 0, 0, 255]);
        assert_eq!(&bytes[row31 + 255 * 4..], &[252, 252, 252, 255]);
    }
}
