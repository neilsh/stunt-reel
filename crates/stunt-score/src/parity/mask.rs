//! Overlay and sky masks, `IoU` and index agreement.

use std::ops::RangeInclusive;

use stunt_core::frame::{
    ASPECT_CORRECTED_HEIGHT, LAYER_NONE, LAYER_OVERLAY, MODE13H_HEIGHT, MODE13H_WIDTH,
};

use super::ssim::rescale_mode13h_frame;

/// First row of the button bar `PLAYONE.EXE` draws over the 3D viewport (rows 185-199).
const UI_BAR_FIRST_ROW: usize = 185;

/// Palette index of the mouse cursor in captured frames.
const CURSOR_INDEX: u8 = 255;

/// Palette indices a captured pixel counts as sky by: elevation bands 227 to 238, down to the
/// horizon (research/formats/concepts/palette-and-shading.md). `PLAYONE.EXE`'s gradient starts at
/// 224, but shapes paint 224 to 226 too, so those count as sky only by position
/// ([`CAPTURE_ZENITH_INDICES`]). This describes captures only; the renderer's band table in
/// `mode13h.wgsl` is a separate model and is deliberately not shared.
pub(super) const CAPTURE_SKY_INDICES: RangeInclusive<u8> = 227..=238;

/// Palette indices of `PLAYONE.EXE`'s zenith sky above the 227 band, which shapes also
/// paint (research/parity/method.md section 2.0), so they count as sky only by position:
/// see [`capture_sky_mask`].
pub(super) const CAPTURE_ZENITH_INDICES: RangeInclusive<u8> = 224..=226;

/// Whether a captured pixel's index is a sky band, whatever its position.
pub(super) fn is_capture_sky(index: u8) -> bool {
    CAPTURE_SKY_INDICES.contains(&index)
}

/// Sky pixels of a captured plane, rows of [`MODE13H_WIDTH`]: every
/// [`CAPTURE_SKY_INDICES`] pixel, and every [`CAPTURE_ZENITH_INDICES`] pixel whose
/// 4-connected run of zenith pixels reaches row 0 and both side columns.
pub(super) fn capture_sky_mask(indices: &[u8]) -> Vec<bool> {
    let zenith = |position: usize| {
        indices
            .get(position)
            .is_some_and(|index| CAPTURE_ZENITH_INDICES.contains(index))
    };
    let mut sky: Vec<bool> = indices.iter().map(|&index| is_capture_sky(index)).collect();
    let mut seen = vec![false; indices.len()];
    let visit = |seen: &mut [bool], position: usize| {
        zenith(position)
            && seen
                .get_mut(position)
                .is_some_and(|cell| !std::mem::replace(cell, true))
    };
    for seed in 0..MODE13H_WIDTH {
        if !visit(&mut seen, seed) {
            continue;
        }
        let mut run = vec![seed];
        let mut stack = vec![seed];
        while let Some(position) = stack.pop() {
            let column = position % MODE13H_WIDTH;
            let next = [
                position.checked_sub(MODE13H_WIDTH),
                Some(position + MODE13H_WIDTH),
                (column > 0).then(|| position - 1),
                (column + 1 < MODE13H_WIDTH).then_some(position + 1),
            ];
            for next in next.into_iter().flatten() {
                if visit(&mut seen, next) {
                    run.push(next);
                    stack.push(next);
                }
            }
        }
        let touches = |column: usize| run.iter().any(|&p| p % MODE13H_WIDTH == column);
        if touches(0) && touches(MODE13H_WIDTH - 1) {
            for position in run {
                if let Some(cell) = sky.get_mut(position) {
                    *cell = true;
                }
            }
        }
    }
    sky
}

/// Pixels of a captured frame covered by the UI overlay: the button bar rows and the
/// cursor. Scoring leaves them out because the renderer does not draw them.
///
/// The cursor and the credits ink are both palette index 255. On a tick whose render
/// record says the film shows credits (`credits_drawn`) index 255 stays in play, so the
/// ink is scored; otherwise it is masked as the cursor. The flag comes from the film, not
/// from the render's pixels, so a render that misplaces or loses its credits is scored on
/// the ink it got wrong instead of masking it away.
pub(super) fn ui_overlay_mask(indices: &[u8], credits_drawn: bool) -> Vec<bool> {
    indices
        .iter()
        .enumerate()
        .map(|(position, &index)| {
            position / MODE13H_WIDTH >= UI_BAR_FIRST_ROW
                || (index == CURSOR_INDEX && !credits_drawn)
        })
        .collect()
}

/// True when a render's layer plane holds credits pixels: any [`LAYER_OVERLAY`] pixel.
/// Diagnostic only: the mask keys on the record's flag.
pub(super) fn overlay_drawn(render_layers: &[u16]) -> bool {
    render_layers
        .iter()
        .any(|&layer| u32::from(layer) == LAYER_OVERLAY)
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

/// Intersection-over-union of the non-sky masks of a capture and a render, skipping
/// `overlay` pixels. The capture's sky is [`capture_sky_mask`]; the render is filled
/// where its layer plane is not [`stunt_core::frame::LAYER_NONE`].
pub(super) fn mask_iou_planes(
    reference_indices: &[u8],
    render_layers: &[u16],
    overlay: &[bool],
) -> f32 {
    let (mut intersection, mut union) = (0usize, 0usize);
    let sky = capture_sky_mask(reference_indices);
    for ((&is_sky, layer), &masked) in sky.iter().zip(render_layers).zip(overlay) {
        if masked {
            continue;
        }
        let reference_filled = !is_sky;
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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn overlay_mask_covers_the_button_bar_rows_and_cursor_pixels() {
        let mut indices = vec![7u8; MODE13H_WIDTH * MODE13H_HEIGHT];
        indices[100 * MODE13H_WIDTH + 160] = CURSOR_INDEX;
        let mask = ui_overlay_mask(&indices, false);
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
    fn credits_ink_is_scored_on_a_tick_whose_film_shows_credits() {
        let mut indices = vec![7u8; MODE13H_WIDTH * MODE13H_HEIGHT];
        let ink = 100 * MODE13H_WIDTH + 160;
        indices[ink] = CURSOR_INDEX;
        let mut layers = vec![0u16; indices.len()];
        assert!(!overlay_drawn(&layers));
        assert!(ui_overlay_mask(&indices, false)[ink]);
        layers[50 * MODE13H_WIDTH] = u16::try_from(LAYER_OVERLAY).unwrap();
        assert!(overlay_drawn(&layers));
        // The film's flag keeps the ink, whatever the render drew.
        let mask = ui_overlay_mask(&indices, true);
        assert!(!mask[ink]);
        // The button bar stays masked either way.
        assert!(mask[UI_BAR_FIRST_ROW * MODE13H_WIDTH]);
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
        // The zenith bands 224-226 count as sky only by position: shapes paint them too
        // (capture_sky_mask, method.md section 2.0).
        assert!(!is_capture_sky(224) && !is_capture_sky(226));
    }

    /// A plane of `rows` full rows of `fill`.
    fn plane(rows: usize, fill: u8) -> Vec<u8> {
        vec![fill; rows * MODE13H_WIDTH]
    }

    #[test]
    fn full_width_zenith_rows_from_row_0_are_sky() {
        // bomb ticks 606-1002: the top rows are 226 across the frame, above 227.
        let mut indices = plane(6, 40);
        indices[..2 * MODE13H_WIDTH].fill(226);
        indices[2 * MODE13H_WIDTH..3 * MODE13H_WIDTH].fill(227);
        let sky = capture_sky_mask(&indices);
        assert!(sky[..3 * MODE13H_WIDTH].iter().all(|&s| s));
        assert!(!sky[3 * MODE13H_WIDTH..].iter().any(|&s| s));
    }

    #[test]
    fn a_zenith_run_bending_round_an_actor_is_sky_where_it_connects() {
        // Row 0 is zenith from side to side; below it the run steps down column 0.
        let mut indices = plane(4, 40);
        indices[..MODE13H_WIDTH].fill(225);
        indices[MODE13H_WIDTH] = 224;
        indices[2 * MODE13H_WIDTH] = 226;
        indices[2 * MODE13H_WIDTH + 50] = 226;
        let sky = capture_sky_mask(&indices);
        assert!(sky[MODE13H_WIDTH] && sky[2 * MODE13H_WIDTH]);
        // An isolated 226 below is not part of the run.
        assert!(!sky[2 * MODE13H_WIDTH + 50]);
    }

    #[test]
    fn zenith_paint_clipped_by_row_0_stays_geometry() {
        // traintnl tick 265: a window at 224 cut off by the top edge, not full width.
        let mut indices = plane(4, 40);
        for row in 0..3 {
            indices[row * MODE13H_WIDTH + 30..row * MODE13H_WIDTH + 42].fill(224);
        }
        assert!(!capture_sky_mask(&indices).iter().any(|&s| s));
    }

    #[test]
    fn zenith_paint_beside_a_sky_band_stays_geometry() {
        // location tick 1090: a helicopter window's 226 edge borders its 227-238
        // gradient; and bomb's 224 emblem on a wall, away from row 0.
        let mut indices = plane(6, 40);
        indices[2 * MODE13H_WIDTH + 10] = 230;
        indices[2 * MODE13H_WIDTH + 11] = 226;
        for row in 3..5 {
            indices[row * MODE13H_WIDTH + 100..row * MODE13H_WIDTH + 104].fill(224);
        }
        let sky = capture_sky_mask(&indices);
        assert!(sky[2 * MODE13H_WIDTH + 10]);
        assert_eq!(sky.iter().filter(|&&s| s).count(), 1);
    }

    #[test]
    fn zenith_runs_do_not_wrap_across_rows() {
        // Row 0 is zenith except its last pixel, which wrapping would reach from
        // row 1's first pixel; the run reaches column 0 only, so it stays geometry.
        let mut indices = plane(3, 40);
        indices[..MODE13H_WIDTH - 1].fill(224);
        indices[MODE13H_WIDTH] = 224;
        indices[2 * MODE13H_WIDTH - 1] = 224;
        assert!(!capture_sky_mask(&indices).iter().any(|&s| s));
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
