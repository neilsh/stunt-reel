//! Contact sheets: reference | test | overlay | index-map panels as RGB PNGs.

use std::collections::BTreeSet;
use std::fs::File;
use std::path::Path;

use stunt_core::frame::{
    ASPECT_CORRECTED_HEIGHT, LAYER_FIRST_ACTOR, LAYER_NONE, LAYER_OCEAN, LAYER_OVERLAY, LAYER_PROP,
    LAYER_TERRAIN, MODE13H_HEIGHT, MODE13H_WIDTH,
};

use super::mask::{rescale_mask, ui_overlay_mask};
use super::ssim::rescale_mode13h_frame;

/// Frame ordinals always rendered as contact sheets, plus the last captured frame.
const CONTACT_SHEET_ORDINALS: [usize; 5] = [1, 20, 40, 70, 100];

/// Number of additionally worst-scoring frames rendered as contact sheets.
const CONTACT_SHEET_WORST: usize = 3;

/// The `keep` lowest-SSIM entries offered so far, lowest first; ties keep the earlier offer.
#[derive(Debug)]
pub(super) struct WorstFrames<T> {
    keep: usize,
    entries: Vec<(f32, usize, T)>,
}

impl<T> WorstFrames<T> {
    pub(super) const fn new(keep: usize) -> Self {
        Self {
            keep,
            entries: Vec::new(),
        }
    }

    /// Offers frame `ordinal` with its `ssim` and `payload`.
    pub(super) fn offer(&mut self, ssim: f32, ordinal: usize, payload: T) {
        self.entries.push((ssim, ordinal, payload));
        self.entries.sort_by(|a, b| a.0.total_cmp(&b.0));
        self.entries.truncate(self.keep);
    }

    /// The kept entries as `(ssim, ordinal, payload)`, lowest SSIM first.
    pub(super) fn into_entries(self) -> Vec<(f32, usize, T)> {
        self.entries
    }
}

/// The contact sheets of one run: the fixed ordinals and the last captured frame as each is
/// scored, then, at [`ContactSheets::finish`], the worst-scoring scored frames not yet written.
pub(super) struct ContactSheets<'a> {
    out_dir: &'a Path,
    fixed: BTreeSet<usize>,
    written: BTreeSet<usize>,
    worst: WorstFrames<ContactPanels>,
}

impl<'a> ContactSheets<'a> {
    /// Sheets written into `out_dir` for a capture of `frame_count` frames.
    pub(super) fn new(out_dir: &'a Path, frame_count: usize) -> Self {
        let mut fixed: BTreeSet<usize> = CONTACT_SHEET_ORDINALS.into_iter().collect();
        fixed.insert(frame_count);
        Self {
            out_dir,
            fixed,
            written: BTreeSet::new(),
            worst: WorstFrames::new(CONTACT_SHEET_WORST),
        }
    }

    /// Offers frame `ordinal`'s panels; `scored_ssim` is its SSIM when it is scored,
    /// and only scored frames compete for the worst sheets.
    pub(super) fn offer(
        &mut self,
        ordinal: usize,
        scored_ssim: Option<f32>,
        panels: ContactPanels,
    ) -> Result<(), String> {
        if self.fixed.contains(&ordinal) {
            write_contact_sheet(self.out_dir, ordinal, &panels)?;
            self.written.insert(ordinal);
        }
        if let Some(ssim) = scored_ssim {
            self.worst.offer(ssim, ordinal, panels);
        }
        Ok(())
    }

    /// Writes the worst-scoring frames' sheets that a fixed ordinal did not already write.
    pub(super) fn finish(mut self) -> Result<(), String> {
        for (_ssim, ordinal, panels) in self.worst.into_entries() {
            if self.written.insert(ordinal) {
                write_contact_sheet(self.out_dir, ordinal, &panels)?;
            }
        }
        Ok(())
    }
}

/// Horizontal gap between contact-sheet panels, in pixels.
pub(super) const CONTACT_SHEET_GAP: usize = 8;

/// What masked pixels show in the overlay and index map.
const MASKED: u8 = 128;

/// How much the overlay amplifies a luma difference.
const GAIN: f32 = 3.0;

/// The index map's base: capture luma scaled by this, so painted pixels stand out.
const DIM: f32 = 0.55;

/// The player's HUD timer as `(row0, row1, col0, col1)` on the 320x200 screen, exclusive
/// ends (research/playone-exe/capture-dosbox-automation.md section 5).
const TIMECODE_BOX: (usize, usize, usize, usize) = (179, 184, 1, 28);

/// The index map's colours by render layer: `(first layer, last layer, RGB)`, none of them the
/// overlay's magenta or green. Mirrors `LAYER_KEY` in `python/stunt_reel/bench/panels.py`.
const LAYER_KEY: [(u32, u32, [u8; 3]); 7] = [
    (LAYER_NONE, LAYER_NONE, [255, 220, 0]),
    (LAYER_OCEAN, LAYER_OCEAN, [0, 110, 255]),
    (LAYER_TERRAIN, LAYER_TERRAIN, [255, 120, 0]),
    (LAYER_PROP, LAYER_PROP, [255, 255, 255]),
    (LAYER_OVERLAY, LAYER_OVERLAY, [0, 230, 230]),
    (LAYER_FIRST_ACTOR, 0xFFFF, [230, 0, 0]),
    (LAYER_OVERLAY + 1, LAYER_FIRST_ACTOR - 1, [150, 90, 40]),
];

/// One 320x240 RGB panel, three bytes per pixel.
pub(super) type Panel = Vec<u8>;

/// The four panels of a contact sheet: reference, test, overlay and index map.
#[derive(Debug)]
pub(super) struct ContactPanels {
    reference: Panel,
    test: Panel,
    overlay: Panel,
    index_map: Panel,
}

/// A value rounded and clamped to a byte.
#[expect(
    clippy::cast_possible_truncation,
    clippy::cast_sign_loss,
    reason = "clamped to 0..=255"
)]
fn to_byte(value: f32) -> u8 {
    value.round().clamp(0.0, 255.0) as u8
}

/// A luminance plane as a grey RGB panel.
pub(super) fn grey_panel(luma: &[f32]) -> Panel {
    luma.iter()
        .flat_map(|&value| {
            let grey = to_byte(value);
            [grey, grey, grey]
        })
        .collect()
}

/// The pixels a sheet leaves out, on the 320x240 raster: the UI overlay (button bar and
/// cursor, see [`ui_overlay_mask`]) and the HUD timer, from the capture's index plane.
pub(super) fn sheet_mask(capture_indices: &[u8], credits_drawn: bool) -> Vec<bool> {
    let mut mask = ui_overlay_mask(capture_indices, credits_drawn);
    let (row0, row1, col0, col1) = TIMECODE_BOX;
    for row in row0..row1 {
        for cell in mask
            .iter_mut()
            .skip(row * MODE13H_WIDTH + col0)
            .take(col1 - col0)
        {
            *cell = true;
        }
    }
    rescale_mask(&mask)
}

/// Their mean luma, with the capture's excess times [`GAIN`] in red and blue and the
/// render's in green, so a capture-brighter pixel is magenta and a render-brighter one green;
/// `mask` pixels are [`MASKED`]. As `panels.composite` in the Python readout sheets.
pub(super) fn overlay_panel(capture: &[f32], render: &[f32], mask: &[bool]) -> Panel {
    capture
        .iter()
        .zip(render)
        .zip(mask)
        .flat_map(|((&c, &r), &masked)| {
            if masked {
                return [MASKED; 3];
            }
            let mean = f32::midpoint(c, r);
            let excess = (c - r) * GAIN / 2.0;
            [
                to_byte(mean + excess),
                to_byte(mean - excess),
                to_byte(mean + excess),
            ]
        })
        .collect()
}

/// The capture dimmed, each unmasked pixel whose palette index differs painted by the colour
/// of the render layer that drew there; `mask` pixels are [`MASKED`]. The index planes and
/// `layers` are 320x200, `capture_luma` and `mask` 320x240. As `panels.index_map`.
pub(super) fn index_map_panel(
    capture_luma: &[f32],
    capture_indices: &[u8],
    render_indices: &[u8],
    layers: &[u16],
    mask: &[bool],
) -> Panel {
    let mismatch: Vec<bool> = capture_indices
        .iter()
        .zip(render_indices)
        .map(|(c, r)| c != r)
        .collect();
    let mismatch = rescale_mask(&mismatch);
    let layers: Vec<f32> = layers.iter().map(|&layer| f32::from(layer)).collect();
    #[expect(
        clippy::cast_possible_truncation,
        clippy::cast_sign_loss,
        reason = "rescaling picks among the source layers, which are u16 values"
    )]
    let layers: Vec<u16> = rescale_mode13h_frame(
        &layers,
        MODE13H_WIDTH,
        MODE13H_HEIGHT,
        ASPECT_CORRECTED_HEIGHT,
    )
    .into_iter()
    .map(|layer| layer as u16)
    .collect();
    capture_luma
        .iter()
        .zip(&mismatch)
        .zip(&layers)
        .zip(mask)
        .flat_map(|(((&luma, &differs), &layer), &masked)| {
            if masked {
                return [MASKED; 3];
            }
            if differs {
                let layer = u32::from(layer);
                if let Some(&(_, _, colour)) = LAYER_KEY
                    .iter()
                    .find(|&&(first, last, _)| (first..=last).contains(&layer))
                {
                    return colour;
                }
            }
            let grey = to_byte(luma * DIM);
            [grey, grey, grey]
        })
        .collect()
}

/// The panels of one frame's contact sheet. `capture_indices`, `render_indices` and `layers` are
/// 320x200 planes, the luminances 320x240; `credits_drawn` is the film's credits flag.
pub(super) fn contact_panels(
    capture_luma: &[f32],
    render_luma: &[f32],
    capture_indices: &[u8],
    render_indices: &[u8],
    layers: &[u16],
    credits_drawn: bool,
) -> ContactPanels {
    let mask = sheet_mask(capture_indices, credits_drawn);
    ContactPanels {
        reference: grey_panel(capture_luma),
        test: grey_panel(render_luma),
        overlay: overlay_panel(capture_luma, render_luma, &mask),
        index_map: index_map_panel(capture_luma, capture_indices, render_indices, layers, &mask),
    }
}

/// Writes a `reference | test | overlay | index map` contact sheet for one frame.
pub(super) fn write_contact_sheet(
    out_dir: &Path,
    ordinal: usize,
    panels: &ContactPanels,
) -> Result<(), String> {
    let path = out_dir.join(format!("contact_{ordinal:04}.png"));
    write_panel_sheet(
        &path,
        &[
            &panels.reference,
            &panels.test,
            &panels.overlay,
            &panels.index_map,
        ],
    )
}

/// Writes 320x240 RGB panels side by side, separated by [`CONTACT_SHEET_GAP`] pixels, as one
/// 8-bit RGB PNG.
pub(super) fn write_panel_sheet(path: &Path, panels: &[&[u8]]) -> Result<(), String> {
    let width = MODE13H_WIDTH;
    let height = ASPECT_CORRECTED_HEIGHT;
    let panel_stride = width + CONTACT_SHEET_GAP;
    let sheet_width = panel_stride * panels.len() - CONTACT_SHEET_GAP;
    let mut buffer = vec![0u8; sheet_width * height * 3];

    for (panel_index, panel) in panels.iter().enumerate() {
        if panel.len() < width * height * 3 {
            return Err(format!(
                "panel {panel_index} holds {} bytes, fewer than {width}x{height}x3",
                panel.len()
            ));
        }
        let sheet_rows = buffer.chunks_exact_mut(sheet_width * 3);
        for (sheet_row, panel_row) in sheet_rows.zip(panel.chunks_exact(width * 3)) {
            let cells = sheet_row.iter_mut().skip(panel_index * panel_stride * 3);
            for (cell, &value) in cells.zip(panel_row) {
                *cell = value;
            }
        }
    }

    let too_large = |_| "contact sheet is too large for an image";
    let file = File::create(path).map_err(|e| format!("write {}: {e}", path.display()))?;
    let mut encoder = png::Encoder::new(
        file,
        u32::try_from(sheet_width).map_err(too_large)?,
        u32::try_from(height).map_err(too_large)?,
    );
    encoder.set_color(png::ColorType::Rgb);
    encoder.set_depth(png::BitDepth::Eight);
    let encode = |error: png::EncodingError| format!("write {}: {error}", path.display());
    let mut writer = encoder.write_header().map_err(encode)?;
    writer.write_image_data(&buffer).map_err(encode)?;
    writer.finish().map_err(encode)
}

#[cfg(test)]
mod tests {
    use std::io::BufReader;

    use super::*;

    #[test]
    fn the_worst_frames_are_the_lowest_ssim_and_ties_keep_the_earlier_frame() {
        let mut worst = WorstFrames::new(3);
        for (ordinal, ssim) in [(1, 0.9), (2, 0.4), (3, 0.7), (4, 0.4), (5, 0.95), (6, 0.1)] {
            worst.offer(ssim, ordinal, ());
        }
        let kept: Vec<(f32, usize)> = worst
            .into_entries()
            .into_iter()
            .map(|(ssim, ordinal, ())| (ssim, ordinal))
            .collect();
        assert_eq!(kept, [(0.1, 6), (0.4, 2), (0.4, 4)]);
    }

    #[test]
    fn fewer_frames_than_kept_are_all_worst() {
        let mut worst = WorstFrames::new(3);
        worst.offer(0.5, 1, ());
        assert_eq!(worst.into_entries().len(), 1);
    }

    const PIXELS: usize = MODE13H_WIDTH * ASPECT_CORRECTED_HEIGHT;

    /// A pixel of the 320x240 panel at row `y`, column `x`.
    fn pixel(panel: &[u8], x: usize, y: usize) -> [u8; 3] {
        let at = (y * MODE13H_WIDTH + x) * 3;
        [panel[at], panel[at + 1], panel[at + 2]]
    }

    #[test]
    fn the_overlay_is_magenta_where_the_capture_is_brighter_green_where_the_render_is() {
        let mut capture = vec![100.0; PIXELS];
        let mut render = vec![100.0; PIXELS];
        capture[0] = 110.0;
        render[1] = 110.0;
        let mask = vec![false; PIXELS];
        let panel = overlay_panel(&capture, &render, &mask);
        // mean 105, excess 10 * 3 / 2 = 15.
        assert_eq!(pixel(&panel, 0, 0), [120, 90, 120]);
        assert_eq!(pixel(&panel, 1, 0), [90, 120, 90]);
        assert_eq!(pixel(&panel, 2, 0), [100, 100, 100]);
    }

    #[test]
    fn the_sheet_mask_covers_the_timer_and_the_button_bar_on_the_stretched_raster() {
        let indices = vec![0u8; MODE13H_WIDTH * MODE13H_HEIGHT];
        let mask = sheet_mask(&indices, false);
        let at = |row200: usize, col: usize| mask[(row200 * 6).div_ceil(5) * MODE13H_WIDTH + col];
        assert!(at(179, 1) && at(183, 27));
        assert!(!at(178, 1) && !at(184, 1) && !at(181, 0) && !at(181, 28));
        assert!(mask[(185 * 6usize).div_ceil(5) * MODE13H_WIDTH]);

        let capture = vec![200.0; PIXELS];
        let render = vec![0.0; PIXELS];
        let panel = overlay_panel(&capture, &render, &mask);
        let timer_row = (181 * 6usize).div_ceil(5);
        assert_eq!(pixel(&panel, 5, timer_row), [128, 128, 128]);
        assert_ne!(pixel(&panel, 100, 10), [128, 128, 128]);
    }

    #[test]
    fn the_index_map_paints_each_mismatch_by_its_render_layer() {
        let pixels = MODE13H_WIDTH * MODE13H_HEIGHT;
        let capture_indices = vec![5u8; pixels];
        let mut render_indices = capture_indices.clone();
        let mut layers = vec![0u16; pixels];
        let layer_ids = [
            (LAYER_NONE, [255, 220, 0]),
            (LAYER_OCEAN, [0, 110, 255]),
            (LAYER_TERRAIN, [255, 120, 0]),
            (LAYER_PROP, [255, 255, 255]),
            (LAYER_OVERLAY, [0, 230, 230]),
            (LAYER_FIRST_ACTOR + 3, [230, 0, 0]),
            (LAYER_OVERLAY + 1, [150, 90, 40]),
        ];
        // One mismatch per layer on 200-space row 10, columns 0..7; the cell at column 8 agrees.
        for (column, (layer, _)) in layer_ids.iter().enumerate() {
            render_indices[10 * MODE13H_WIDTH + column] = 6;
            layers[10 * MODE13H_WIDTH + column] = u16::try_from(*layer).unwrap();
        }
        layers[10 * MODE13H_WIDTH + 8] = u16::try_from(LAYER_PROP).unwrap();
        let luma = vec![100.0; PIXELS];
        let mask = vec![false; PIXELS];
        let panel = index_map_panel(&luma, &capture_indices, &render_indices, &layers, &mask);
        let row240 = 12; // 200-space row 10 first appears at 240-space row 12.
        for (column, (_, colour)) in layer_ids.iter().enumerate() {
            assert_eq!(pixel(&panel, column, row240), *colour, "column {column}");
        }
        assert_eq!(pixel(&panel, 8, row240), [55, 55, 55]);
        let masked = vec![true; PIXELS];
        let panel = index_map_panel(&luma, &capture_indices, &render_indices, &layers, &masked);
        assert_eq!(pixel(&panel, 0, row240), [128, 128, 128]);
    }

    #[test]
    fn a_panel_sheet_decodes_as_eight_bit_rgb_of_the_expected_width() {
        let tmp = crate::parity::test_support::TempDir::new("panel_sheet");
        let path = tmp.join("sheet.png");
        let luma: Vec<f32> = (0..PIXELS)
            .map(|i| f32::from(u8::try_from(i % 251).unwrap()))
            .collect();
        let panel = grey_panel(&luma);
        write_panel_sheet(&path, &[&panel, &panel]).unwrap();

        let mut reader = png::Decoder::new(BufReader::new(File::open(&path).unwrap()))
            .read_info()
            .unwrap();
        let mut buffer = vec![0; reader.output_buffer_size().unwrap()];
        let info = reader.next_frame(&mut buffer).unwrap();
        assert_eq!(info.width as usize, MODE13H_WIDTH * 2 + CONTACT_SHEET_GAP);
        assert_eq!(info.height as usize, ASPECT_CORRECTED_HEIGHT);
        assert_eq!(info.color_type, png::ColorType::Rgb);
        assert_eq!(info.bit_depth, png::BitDepth::Eight);
        let sheet_width = info.width as usize;
        // Row 0, panel 0: grey pixels R=G=B.
        for x in 0..MODE13H_WIDTH {
            let grey = u8::try_from(x % 251).unwrap();
            assert_eq!(&buffer[x * 3..x * 3 + 3], &[grey; 3]);
        }
        assert_eq!(
            sheet_width * 3 * ASPECT_CORRECTED_HEIGHT,
            info.buffer_size()
        );
    }
}
