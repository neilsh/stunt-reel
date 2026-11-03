//! Loading captured frames and stored render ticks: index planes, palettes and luminance.

use std::fs;
use std::path::Path;

use stunt_parity::Geometry;

use stunt_render::{ASPECT_CORRECTED_HEIGHT, MODE13H_HEIGHT, MODE13H_WIDTH};

use super::score::RenderFrame;
use super::ssim::{rescale_mode13h_frame, rgb_to_luminance};
use crate::render_store::RenderStore;

/// A 256-entry RGB palette.
use crate::render_store::{Palette, palette_rgb};

/// Loads a captured frame: its palette-index plane and its captured palette.
pub(super) fn load_reference(
    reference_file: &Path,
    palette_file: &Path,
) -> Result<(Vec<u8>, Palette), String> {
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

/// Loads a stored render tick as aspect-corrected luminance.
pub(super) fn load_render_rescaled(store: &mut RenderStore, tick: u32) -> Result<Vec<f32>, String> {
    Ok(rescale_mode13h_frame(
        &load_render_frame(store, tick)?.luminance,
        MODE13H_WIDTH,
        MODE13H_HEIGHT,
        ASPECT_CORRECTED_HEIGHT,
    ))
}

/// Loads a stored render tick: the luminance of its picture (`palette[index]`), its
/// palette-index plane and its layer plane, all 320x200, and the record's credits flag. The
/// palette controls are left `None`; the caller sets them when it has the render record.
pub(super) fn load_render_frame(store: &mut RenderStore, tick: u32) -> Result<RenderFrame, String> {
    let Geometry { width, height, .. } = store.record().geometry;
    if width as usize != MODE13H_WIDTH || height as usize != MODE13H_HEIGHT {
        return Err(format!(
            "the render is {width}x{height}, expected {MODE13H_WIDTH}x{MODE13H_HEIGHT}"
        ));
    }
    let credits = store
        .record()
        .ticks
        .iter()
        .find(|entry| entry.tick == tick)
        .is_some_and(|entry| entry.credits);
    let frame = store.frame(tick).map_err(|e| e.to_string())?;
    Ok(RenderFrame {
        luminance: rgb_to_luminance(&frame.rgb()),
        indices: frame.indices,
        layers: frame.layers,
        controls: None,
        credits,
    })
}

/// Reads a 64000-byte Mode 13h palette-index raster.
pub(super) fn read_index_plane(path: &Path) -> Result<Vec<u8>, String> {
    let bytes = fs::read(path).map_err(|e| format!("read {}: {e}", path.display()))?;
    let expected = MODE13H_WIDTH * MODE13H_HEIGHT;
    if bytes.len() != expected {
        return Err(format!(
            "{} holds {} bytes, expected {expected}",
            path.display(),
            bytes.len()
        ));
    }
    Ok(bytes)
}

/// Reads a 256-entry RGB palette written by the capture harness.
fn read_palette(path: &Path) -> Result<Palette, String> {
    let text = fs::read_to_string(path).map_err(|e| format!("read {}: {e}", path.display()))?;
    let raw: Vec<[i64; 3]> =
        serde_json::from_str(&text).map_err(|e| format!("parse {}: {e}", path.display()))?;
    let raw: [[i64; 3]; 256] = raw.try_into().map_err(|raw: Vec<_>| {
        format!(
            "{} holds {} palette entries, expected 256",
            path.display(),
            raw.len()
        )
    })?;
    Ok(raw.map(|[r, g, b]| (r as u8, g as u8, b as u8)))
}
