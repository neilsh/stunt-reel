//! Contact sheets: reference | test | difference panels as grayscale PNGs.

use std::collections::BTreeSet;
use std::fs::File;
use std::path::Path;

use stunt_core::frame::{ASPECT_CORRECTED_HEIGHT, MODE13H_WIDTH};

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
    worst: WorstFrames<(Vec<f32>, Vec<f32>)>,
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

    /// Offers frame `ordinal`'s luminance planes; `scored_ssim` is its SSIM when it is scored,
    /// and only scored frames compete for the worst sheets.
    pub(super) fn offer(
        &mut self,
        ordinal: usize,
        scored_ssim: Option<f32>,
        reference: Vec<f32>,
        test: Vec<f32>,
    ) -> Result<(), String> {
        if self.fixed.contains(&ordinal) {
            write_contact_sheet(self.out_dir, ordinal, &reference, &test)?;
            self.written.insert(ordinal);
        }
        if let Some(ssim) = scored_ssim {
            self.worst.offer(ssim, ordinal, (reference, test));
        }
        Ok(())
    }

    /// Writes the worst-scoring frames' sheets that a fixed ordinal did not already write.
    pub(super) fn finish(mut self) -> Result<(), String> {
        for (_ssim, ordinal, (reference, test)) in self.worst.into_entries() {
            if self.written.insert(ordinal) {
                write_contact_sheet(self.out_dir, ordinal, &reference, &test)?;
            }
        }
        Ok(())
    }
}

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

/// A sheet value as a grey level, clamped to 0..=255.
#[expect(
    clippy::cast_possible_truncation,
    clippy::cast_sign_loss,
    reason = "clamped to 0..=255"
)]
fn grey_level(value: f32) -> u8 {
    value.clamp(0.0, 255.0) as u8
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
        if panel.len() < width * height {
            return Err(format!(
                "panel {panel_index} holds {} values, fewer than {width}x{height}",
                panel.len()
            ));
        }
        let sheet_rows = buffer.chunks_exact_mut(sheet_width);
        for (sheet_row, panel_row) in sheet_rows.zip(panel.chunks_exact(width)) {
            let cells = sheet_row.iter_mut().skip(panel_index * panel_stride);
            for (cell, &value) in cells.zip(panel_row) {
                *cell = grey_level(value);
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
    encoder.set_color(png::ColorType::Grayscale);
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

    #[test]
    fn a_panel_sheet_decodes_as_eight_bit_grayscale() {
        let tmp = crate::parity::test_support::TempDir::new("panel_sheet");
        let path = tmp.join("sheet.png");
        let panel: Vec<f32> = (0..MODE13H_WIDTH * ASPECT_CORRECTED_HEIGHT)
            .map(|i| f32::from(u8::try_from(i % 251).unwrap()))
            .collect();
        write_panel_sheet(&path, &[&panel]).unwrap();

        let mut reader = png::Decoder::new(BufReader::new(File::open(&path).unwrap()))
            .read_info()
            .unwrap();
        let mut buffer = vec![0; reader.output_buffer_size().unwrap()];
        let info = reader.next_frame(&mut buffer).unwrap();
        assert_eq!(info.width as usize, MODE13H_WIDTH);
        assert_eq!(info.height as usize, ASPECT_CORRECTED_HEIGHT);
        assert_eq!(info.color_type, png::ColorType::Grayscale);
        assert_eq!(info.bit_depth, png::BitDepth::Eight);
        let expected: Vec<u8> = panel.iter().map(|&value| grey_level(value)).collect();
        assert_eq!(&buffer[..info.buffer_size()], expected.as_slice());
    }
}
