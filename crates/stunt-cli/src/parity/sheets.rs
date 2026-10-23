//! Contact sheets: reference | test | difference panels as grayscale PNGs.

use std::path::Path;

use stunt_render::{ASPECT_CORRECTED_HEIGHT, MODE13H_WIDTH};

/// Horizontal gap between contact-sheet panels, in pixels.
pub(super) const CONTACT_SHEET_GAP: usize = 8;

/// Absolute per-pixel difference of two equally sized luminance planes.
pub(super) fn abs_difference(a: &[f32], b: &[f32]) -> Vec<f32> {
    a.iter().zip(b).map(|(x, y)| (x - y).abs()).collect()
}

/// Writes a `reference | test | |difference|` contact sheet for one frame.
pub(super) fn write_contact_sheet(
    out_dir: &Path,
    ordinal: usize,
    reference: &[f32],
    test: &[f32],
) -> Result<(), String> {
    let path = out_dir.join(format!("contact_{ordinal:04}.png"));
    write_panel_sheet(&path, &[reference, test, &abs_difference(reference, test)])
}

/// Writes aspect-corrected luminance panels side by side, separated by
/// [`CONTACT_SHEET_GAP`] pixels, as one grayscale PNG.
pub(super) fn write_panel_sheet(path: &Path, panels: &[&[f32]]) -> Result<(), String> {
    let width = MODE13H_WIDTH;
    let height = ASPECT_CORRECTED_HEIGHT;
    let panel_stride = width + CONTACT_SHEET_GAP;
    let sheet_width = panel_stride * panels.len() - CONTACT_SHEET_GAP;
    let mut buffer = vec![0u8; sheet_width * height];

    for (panel_index, panel) in panels.iter().enumerate() {
        for y in 0..height {
            let row = y * sheet_width + panel_index * panel_stride;
            for x in 0..width {
                buffer[row + x] = panel[y * width + x].clamp(0.0, 255.0) as u8;
            }
        }
    }

    let image = image::GrayImage::from_raw(sheet_width as u32, height as u32, buffer)
        .ok_or("failed to build contact sheet buffer")?;
    image
        .save(path)
        .map_err(|e| format!("write {}: {e}", path.display()))
}
