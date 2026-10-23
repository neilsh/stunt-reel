//! Overlay and sky masks, IoU and index agreement.

use std::ops::RangeInclusive;

use stunt_render::{
    ASPECT_CORRECTED_HEIGHT, LAYER_NONE, MODE13H_HEIGHT, MODE13H_WIDTH, rescale_mode13h_frame,
};

/// First row of the button bar `PLAYONE.EXE` draws over the 3D viewport (rows 185-199).
const UI_BAR_FIRST_ROW: usize = 185;

/// Palette index of the mouse cursor in captured frames.
const CURSOR_INDEX: u8 = 255;

/// Palette indices `PLAYONE.EXE` paints the sky with: elevation bands from 227 at the top
/// of the view to 238 at the horizon (`research/parity-findings.md` §7). This describes
/// captures only; the renderer's band table in `mode13h.wgsl` is a separate model and is
/// deliberately not shared.
pub(super) const CAPTURE_SKY_INDICES: RangeInclusive<u8> = 227..=238;

/// Whether a captured pixel shows sky rather than geometry.
pub(super) fn is_capture_sky(index: u8) -> bool {
    CAPTURE_SKY_INDICES.contains(&index)
}

/// Pixels of a captured frame covered by the UI overlay: the button bar rows and the
/// cursor. Scoring leaves them out because the renderer does not draw them.
pub(super) fn ui_overlay_mask(indices: &[u8]) -> Vec<bool> {
    indices
        .iter()
        .enumerate()
        .map(|(position, &index)| {
            position / MODE13H_WIDTH >= UI_BAR_FIRST_ROW || index == CURSOR_INDEX
        })
        .collect()
}

/// Stretches a 320x200 mask to the 320x240 raster with the same row mapping as the frames.
pub(super) fn rescale_mask(mask: &[bool]) -> Vec<bool> {
    let plane: Vec<f32> = mask.iter().map(|&m| f32::from(u8::from(m))).collect();
    rescale_mode13h_frame(
        &plane,
        MODE13H_WIDTH,
        MODE13H_HEIGHT,
        ASPECT_CORRECTED_HEIGHT,
    )
    .into_iter()
    .map(|v| v > 0.5)
    .collect()
}

/// Fraction of non-`overlay` pixels where both index planes agree.
pub(super) fn index_agreement(reference: &[u8], render: &[u8], overlay: &[bool]) -> f32 {
    let (mut equal, mut total) = (0usize, 0usize);
    for ((a, b), &masked) in reference.iter().zip(render).zip(overlay) {
        if masked {
            continue;
        }
        total += 1;
        equal += usize::from(a == b);
    }
    if total == 0 {
        1.0
    } else {
        equal as f32 / total as f32
    }
}

/// Like [`mask_iou`], but the render side is filled where its layer plane is not
/// [`stunt_render::LAYER_NONE`].
pub(super) fn mask_iou_planes(
    reference_indices: &[u8],
    render_layers: &[u16],
    overlay: &[bool],
) -> f32 {
    let (mut intersection, mut union) = (0usize, 0usize);
    for ((index, layer), &masked) in reference_indices.iter().zip(render_layers).zip(overlay) {
        if masked {
            continue;
        }
        let reference_filled = !is_capture_sky(*index);
        let test_filled = u32::from(*layer) != LAYER_NONE;
        intersection += usize::from(reference_filled && test_filled);
        union += usize::from(reference_filled || test_filled);
    }
    if union == 0 {
        1.0
    } else {
        intersection as f32 / union as f32
    }
}

/// Intersection-over-union of the non-sky masks of both 320x200 frames, skipping `overlay`
/// pixels. The capture's sky is [`CAPTURE_SKY_INDICES`].
pub(super) fn mask_iou(
    reference_indices: &[u8],
    test_luminance: &[f32],
    clear_luminance: f32,
    overlay: &[bool],
) -> f32 {
    let mut intersection = 0usize;
    let mut union = 0usize;
    for (position, (index, luminance)) in reference_indices
        .iter()
        .zip(test_luminance.iter())
        .enumerate()
    {
        if overlay[position] {
            continue;
        }
        let reference_filled = !is_capture_sky(*index);
        let test_filled = (*luminance - clear_luminance).abs() > 0.5;
        if reference_filled && test_filled {
            intersection += 1;
        }
        if reference_filled || test_filled {
            union += 1;
        }
    }
    if union == 0 {
        1.0
    } else {
        intersection as f32 / union as f32
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn overlay_mask_covers_the_button_bar_rows_and_cursor_pixels() {
        let mut indices = vec![7u8; MODE13H_WIDTH * MODE13H_HEIGHT];
        indices[100 * MODE13H_WIDTH + 160] = CURSOR_INDEX;
        let mask = ui_overlay_mask(&indices);
        assert!(mask[100 * MODE13H_WIDTH + 160]);
        assert!(!mask[100 * MODE13H_WIDTH + 161]);
        assert!(!mask[(UI_BAR_FIRST_ROW - 1) * MODE13H_WIDTH]);
        assert!(mask[UI_BAR_FIRST_ROW * MODE13H_WIDTH]);
        assert!(mask[MODE13H_WIDTH * MODE13H_HEIGHT - 1]);
        let rescaled = rescale_mask(&mask);
        assert_eq!(rescaled.len(), MODE13H_WIDTH * ASPECT_CORRECTED_HEIGHT);
        // Row 185 of 200 stretches to row 222 of 240.
        assert!(rescaled[222 * MODE13H_WIDTH]);
        assert!(!rescaled[221 * MODE13H_WIDTH]);
    }

    #[test]
    fn index_agreement_counts_equal_indices_outside_the_overlay() {
        let reference = [1u8, 2, 3, 4];
        let render = [1u8, 9, 3, 9];
        let overlay = [false, false, false, true];
        // Three counted pixels, two equal.
        assert!((index_agreement(&reference, &render, &overlay) - 2.0 / 3.0).abs() < 1e-6);
        assert_eq!(index_agreement(&reference, &render, &[true; 4]), 1.0);
    }

    #[test]
    fn every_sky_band_counts_as_sky_and_nothing_else_does() {
        for index in 0..=255u8 {
            assert_eq!(
                is_capture_sky(index),
                (227..=238).contains(&index),
                "{index}"
            );
        }
        // The rare 224-226 shades sit below the horizon, never in the top rows.
        assert!(!is_capture_sky(224) && !is_capture_sky(226));
    }

    #[test]
    fn layer_mask_iou_fills_the_render_side_where_a_layer_covers() {
        let reference = [227u8, 238, 7, 7];
        let layers = [0u16, 1, 1, 0];
        // Reference fills pixels 2 and 3 (227 and 238 are sky bands); the render fills
        // pixels 1 and 2.
        let iou = mask_iou_planes(&reference, &layers, &[false; 4]);
        assert!((iou - 1.0 / 3.0).abs() < 1e-6);
    }

    #[test]
    fn every_sky_band_of_one_capture_is_masked_out() {
        // A capture whose sky spans several bands, with no render geometry: before the
        // band rule only the modal band counted as sky and the rest scored as misses.
        let reference = [227u8, 230, 233, 238, 40];
        let layers = [0u16; 5];
        let iou = mask_iou_planes(&reference, &layers, &[false; 5]);
        // Only pixel 4 is filled (reference only), so the union is 1 and IoU is 0.
        assert_eq!(iou, 0.0);
        let layers = [0u16, 0, 0, 0, 1];
        assert_eq!(mask_iou_planes(&reference, &layers, &[false; 5]), 1.0);
    }
}
