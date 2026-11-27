//! Loading captured frames and stored render ticks: index planes, palettes and luminance.

use super::ParityError;
use std::fs;
use std::path::Path;

use stunt_parity::Geometry;

use stunt_core::frame::{ASPECT_CORRECTED_HEIGHT, MODE13H_HEIGHT, MODE13H_WIDTH};

use super::score::RenderFrame;
use super::ssim::{rescale_mode13h_frame, rgb_to_luminance};
use crate::render_store::RenderStore;

use crate::render_store::{Palette, palette_rgb};

/// Loads a captured frame: its palette-index plane and its captured palette.
pub(super) fn load_reference(
    reference_file: &Path,
    palette_file: &Path,
) -> Result<(Vec<u8>, Palette), ParityError> {
    Ok((
        read_index_plane(reference_file)?,
        read_palette(palette_file)?,
    ))
}

/// Aspect-corrected luminance of an index plane seen through `palette`.
pub(super) fn reference_luminance(indices: &[u8], palette: &Palette) -> Vec<f32> {
    let mut reference_rgb = Vec::with_capacity(MODE13H_WIDTH * MODE13H_HEIGHT * 3);
    for &index in indices {
        let (r, g, b) = palette_rgb(palette, index);
        reference_rgb.extend_from_slice(&[r, g, b]);
    }
    rescale_mode13h_frame(
        &rgb_to_luminance(&reference_rgb),
        MODE13H_WIDTH,
        MODE13H_HEIGHT,
        ASPECT_CORRECTED_HEIGHT,
    )
}

/// Loads a stored render tick: the luminance of its picture (`palette[index]`), its
/// palette-index plane and its layer plane, all 320x200, and the record's credits flag. The
/// palette controls are left `None`; the caller sets them when it has the render record.
pub(super) fn load_render_frame(
    store: &mut RenderStore,
    tick: u32,
) -> Result<RenderFrame, ParityError> {
    let Geometry { width, height, .. } = store.record().geometry;
    if width as usize != MODE13H_WIDTH || height as usize != MODE13H_HEIGHT {
        return Err(ParityError::Input(format!(
            "the render is {width}x{height}, expected {MODE13H_WIDTH}x{MODE13H_HEIGHT}"
        )));
    }
    let credits = store
        .record()
        .ticks
        .iter()
        .find(|entry| entry.tick == tick)
        .is_some_and(|entry| entry.credits);
    let frame = store.frame(tick)?;
    Ok(RenderFrame {
        luminance: rgb_to_luminance(&frame.rgb()),
        indices: frame.indices,
        layers: frame.layers,
        shapes: frame.shapes,
        controls: None,
        credits,
    })
}

/// Reads a 64000-byte Mode 13h palette-index raster.
pub(super) fn read_index_plane(path: &Path) -> Result<Vec<u8>, ParityError> {
    let bytes = fs::read(path).map_err(ParityError::io("read", path))?;
    let expected = MODE13H_WIDTH * MODE13H_HEIGHT;
    if bytes.len() != expected {
        return Err(ParityError::Input(format!(
            "{} holds {} bytes, expected {expected}",
            path.display(),
            bytes.len()
        )));
    }
    Ok(bytes)
}

/// Reads a 256-entry RGB palette written by the capture harness.
fn read_palette(path: &Path) -> Result<Palette, ParityError> {
    let text = fs::read_to_string(path).map_err(ParityError::io("read", path))?;
    let raw: Vec<[i64; 3]> = serde_json::from_str(&text).map_err(|source| ParityError::Parse {
        path: path.to_path_buf(),
        source,
    })?;
    let raw: [[i64; 3]; 256] = raw.try_into().map_err(|raw: Vec<_>| {
        ParityError::Input(format!(
            "{} holds {} palette entries, expected 256",
            path.display(),
            raw.len()
        ))
    })?;
    let channel = |v: i64| {
        u8::try_from(v).map_err(|_| {
            ParityError::Input(format!(
                "{} holds palette value {v}, outside 0..=255",
                path.display()
            ))
        })
    };
    let mut palette = [(0, 0, 0); 256];
    for (entry, [r, g, b]) in palette.iter_mut().zip(raw) {
        *entry = (channel(r)?, channel(g)?, channel(b)?);
    }
    Ok(palette)
}
