//! The per-frame scoring call: one captured frame against one render, in memory.
//!
//! [`score_frame`] owns every per-frame measurement (SSIM, mask `IoU`, index agreement, loss
//! attribution and the fade floor), so `run` only loads files, matches frames by film tick
//! and writes the report.

use std::collections::BTreeMap;

use stunt_core::contracts::{PALETTE_CONTROL_FULL, PaletteControls};
use stunt_core::frame::{ASPECT_CORRECTED_HEIGHT, MODE13H_HEIGHT, MODE13H_WIDTH};

use crate::render_store::Palette;

use super::fade::fade_level;
use super::frames::reference_luminance;
use super::loss::{LOSS_CLASSES, attribute_loss, attribute_shape_loss, loss_class};
use super::mask::{index_agreement, mask_iou_planes, rescale_mask, ui_overlay_mask};
use super::ssim::{compute_window_scores, rescale_mode13h_frame};

/// SSIM window edge, in pixels.
pub(super) const SSIM_WINDOW: usize = 11;

/// SSIM window stride, in pixels.
pub(super) const SSIM_STRIDE: usize = 8;

/// One captured frame: its 320x200 palette-index plane and its captured palette.
pub(super) struct ReferenceFrame {
    pub(super) indices: Vec<u8>,
    pub(super) palette: Palette,
}

/// One rendered frame at the capture's film tick.
pub(super) struct RenderFrame {
    /// 320x200 Rec. 601 luminance of the rendered PNG.
    pub(super) luminance: Vec<f32>,
    /// 320x200 palette-index plane.
    pub(super) indices: Vec<u8>,
    /// 320x200 layer-id plane; `LAYER_NONE` is sky.
    pub(super) layers: Vec<u16>,
    /// 320x200 shape-word plane (`shape id + 1` of the prop drawing each pixel, 0 for none);
    /// `None` when the render stored no shape plane.
    pub(super) shapes: Option<Vec<u16>>,
    /// The palette controls the film authors at this tick, from the render's `render.json`.
    pub(super) controls: Option<PaletteControls>,
    /// The film shows credits at this tick, from the render's `render.json`.
    pub(super) credits: bool,
}

/// What decides whether a frame is scored.
pub(super) struct ScorePolicy<'a> {
    /// Indices the fade level is measured over (see [`super::fade::fade_reference_set`]).
    pub(super) fade_set: &'a [u8],
    /// The `--min-fade-level` floor.
    pub(super) min_fade_level: f32,
}

/// Per-frame parity measurements.
#[derive(Debug, Clone, Copy)]
pub(super) struct FrameMetrics {
    /// SSIM of the render against the capture.
    pub(super) ssim: f32,
    /// Median ratio of the captured palette's brightness to the static palette's.
    pub(super) fade_level: f32,
    /// Brightness the film authors at this tick (var 14 over [`PALETTE_CONTROL_FULL`]); `None`
    /// when the render record has no entry for the tick.
    pub(super) authored_fade_level: Option<f32>,
    /// Whether the fade reaches the `--min-fade-level` floor, decided by the authored
    /// brightness. The measured `fade_level` is a cross-check, never the decision
    /// (ADR 0005); a tick with no authored entry is not excluded.
    pub(super) scored: bool,
    pub(super) iou: f32,
    /// Fraction of non-overlay pixels whose palette index equals the capture's.
    pub(super) index_agreement: f32,
    /// This frame's SSIM loss (`1 - ssim`) split by what the window covers. The entries sum
    /// to `1 - ssim`.
    pub(super) loss_by_class: [f32; LOSS_CLASSES.len()],
}

/// A frame's measurements plus the aspect-corrected luminance pair, kept for contact sheets.
pub(super) struct FrameScore {
    pub(super) metrics: FrameMetrics,
    pub(super) reference_luminance: Vec<f32>,
    pub(super) render_luminance: Vec<f32>,
    /// The `props` loss of this frame by shape word ([`attribute_shape_loss`]); `None` when
    /// the render has no shape plane.
    pub(super) shape_loss: Option<BTreeMap<u16, f64>>,
}

/// Scores one render against one capture, given the capture's sky mask
/// ([`super::mask::capture_sky_mask`]).
pub(super) fn score_frame(
    reference: &ReferenceFrame,
    render: &RenderFrame,
    capture_sky: &[bool],
    policy: &ScorePolicy<'_>,
) -> FrameScore {
    let reference_rescaled = reference_luminance(&reference.indices, &reference.palette);
    let render_rescaled = rescale_mode13h_frame(
        &render.luminance,
        MODE13H_WIDTH,
        MODE13H_HEIGHT,
        ASPECT_CORRECTED_HEIGHT,
    );
    let overlay = ui_overlay_mask(&reference.indices, render.credits);
    let windows = compute_window_scores(
        &reference_rescaled,
        &render_rescaled,
        MODE13H_WIDTH,
        ASPECT_CORRECTED_HEIGHT,
        SSIM_WINDOW,
        SSIM_STRIDE,
        Some(&rescale_mask(&overlay)),
    );
    let ssim = if windows.is_empty() {
        1.0
    } else {
        windows.iter().map(|w| w.score).sum::<f32>() / windows.len() as f32
    };
    let codes: Vec<f32> = capture_sky
        .iter()
        .zip(&render.layers)
        .map(|(&sky, &layer)| f32::from(loss_class(layer, !sky)))
        .collect();
    #[expect(
        clippy::cast_possible_truncation,
        clippy::cast_sign_loss,
        reason = "rescaling picks among the source codes, loss classes 0..=9"
    )]
    let classes: Vec<u8> = rescale_mode13h_frame(
        &codes,
        MODE13H_WIDTH,
        MODE13H_HEIGHT,
        ASPECT_CORRECTED_HEIGHT,
    )
    .into_iter()
    .map(|code| code as u8)
    .collect();
    let shape_loss = render.shapes.as_ref().map(|shapes| {
        let words: Vec<f32> = shapes.iter().map(|&word| f32::from(word)).collect();
        #[expect(
            clippy::cast_possible_truncation,
            clippy::cast_sign_loss,
            reason = "rescaling picks among the source words, which are u16 values"
        )]
        let rescaled: Vec<u16> = rescale_mode13h_frame(
            &words,
            MODE13H_WIDTH,
            MODE13H_HEIGHT,
            ASPECT_CORRECTED_HEIGHT,
        )
        .into_iter()
        .map(|word| word as u16)
        .collect();
        attribute_shape_loss(&windows, &classes, &rescaled, SSIM_WINDOW)
    });
    let fade = fade_level(policy.fade_set, &reference.palette);
    let authored_fade = render
        .controls
        .map(|controls| f32::from(controls.brightness) / f32::from(PALETTE_CONTROL_FULL));

    FrameScore {
        metrics: FrameMetrics {
            ssim,
            fade_level: fade,
            authored_fade_level: authored_fade,
            scored: authored_fade.is_none_or(|level| level >= policy.min_fade_level),
            iou: mask_iou_planes(capture_sky, &render.layers, &overlay),
            index_agreement: index_agreement(&reference.indices, &render.indices, &overlay),
            loss_by_class: attribute_loss(&windows, &classes, SSIM_WINDOW),
        },
        reference_luminance: reference_rescaled,
        render_luminance: render_rescaled,
        shape_loss,
    }
}

#[cfg(test)]
mod tests {
    use stunt_core::contracts::get_palette_rgb;
    use stunt_core::frame::{LAYER_NONE, LAYER_PROP, LAYER_TERRAIN};

    use super::*;
    use crate::parity::fade::fade_reference_set;
    use crate::parity::mask::{capture_sky_mask, is_capture_sky};
    use crate::parity::test_support::{plane_index, scaled_palette};

    const PIXELS: usize = MODE13H_WIDTH * MODE13H_HEIGHT;

    /// A capture's sky mask, with no previous frame to carry from.
    fn sky(reference: &ReferenceFrame) -> Vec<bool> {
        capture_sky_mask(&reference.indices, None).sky
    }

    fn capture(scale: f32) -> ReferenceFrame {
        ReferenceFrame {
            indices: (0..PIXELS).map(plane_index).collect(),
            palette: scaled_palette(scale),
        }
    }

    /// A render whose planes match the synthetic capture: its own indices, with a layer
    /// wherever the capture is not sky. `luminance` is the unfaded palette view.
    fn matching_render() -> RenderFrame {
        let indices: Vec<u8> = (0..PIXELS).map(plane_index).collect();
        let layers = indices
            .iter()
            .map(|&index| {
                if is_capture_sky(index) {
                    u16::try_from(LAYER_NONE).unwrap()
                } else {
                    u16::try_from(LAYER_TERRAIN).unwrap()
                }
            })
            .collect();
        let rgb: Vec<u8> = indices
            .iter()
            .flat_map(|&index| {
                let (r, g, b) = get_palette_rgb(index);
                [r, g, b]
            })
            .collect();
        RenderFrame {
            luminance: crate::parity::ssim::rgb_to_luminance(&rgb),
            indices,
            layers,
            shapes: None,
            controls: None,
            credits: false,
        }
    }

    fn score(reference: &ReferenceFrame, render: &RenderFrame) -> FrameMetrics {
        let fade_set = fade_reference_set(&capture(1.0).indices);
        let policy = ScorePolicy {
            fade_set: &fade_set,
            min_fade_level: 0.25,
        };
        score_frame(reference, render, &sky(reference), &policy).metrics
    }

    #[test]
    fn the_fade_floor_uses_authored_brightness_when_the_render_has_controls() {
        // The capture looks fully bright; the film authors a fade below the floor.
        let render = RenderFrame {
            controls: Some(PaletteControls {
                sky: 0,
                brightness: 0x1000,
                saturation: 0x8000,
            }),
            ..matching_render()
        };
        let metrics = score(&capture(1.0), &render);
        assert_eq!(metrics.authored_fade_level, Some(0.125));
        assert!(!metrics.scored);
        assert!(metrics.fade_level > 0.9);
    }

    #[test]
    fn without_authored_controls_a_frame_is_not_excluded() {
        // ADR 0005: the measured fade is a cross-check, never the scored decision.
        let faded = score(&capture(0.1), &matching_render());
        assert!(faded.scored);
        assert!(faded.authored_fade_level.is_none());
        assert!((faded.fade_level - 0.1).abs() < 0.02);
    }

    #[test]
    fn iou_and_index_agreement_come_from_the_render_planes_not_its_colours() {
        let render = RenderFrame {
            luminance: (0..PIXELS).map(|i| (i % 251) as f32).collect(),
            ..matching_render()
        };
        let metrics = score(&capture(1.0), &render);
        assert_eq!(metrics.index_agreement, 1.0);
        assert_eq!(metrics.iou, 1.0);
        assert!(metrics.ssim < 0.9);
    }

    #[test]
    fn every_sky_band_counts_as_sky() {
        // The capture's sky spans two bands (227 and 233); a render whose layer plane is
        // empty over both matches it exactly, while one that fills either band does not.
        let matching = score(&capture(1.0), &matching_render());
        assert_eq!(matching.iou, 1.0);
        let mut filled = matching_render();
        filled.layers[..MODE13H_WIDTH * 2].fill(u16::try_from(LAYER_TERRAIN).unwrap());
        assert!(score(&capture(1.0), &filled).iou < 1.0);
    }

    /// A faded capture against a render whose non-sky pixels are props of three shapes, split
    /// by column band, scores a props loss that its shape split reproduces.
    #[test]
    fn the_shape_split_of_a_frame_sums_to_its_props_loss() {
        let mut render = matching_render();
        let props = u16::try_from(LAYER_PROP).unwrap();
        let shapes: Vec<u16> = (0..PIXELS)
            .map(|i| match (i % MODE13H_WIDTH) / 107 {
                0 => 4,
                1 => 9,
                _ => 0,
            })
            .collect();
        for layer in &mut render.layers {
            if *layer != 0 {
                *layer = props;
            }
        }
        render.shapes = Some(shapes);
        render
            .luminance
            .iter_mut()
            .enumerate()
            .for_each(|(i, l)| *l += (i % 13) as f32 * 3.0);
        let fade_set = fade_reference_set(&capture(1.0).indices);
        let policy = ScorePolicy {
            fade_set: &fade_set,
            min_fade_level: 0.0,
        };
        let reference = capture(1.0);
        let scored = score_frame(&reference, &render, &sky(&reference), &policy);
        let by_shape = scored.shape_loss.expect("a shape plane was given");
        let props_loss = f64::from(scored.metrics.loss_by_class[4]);
        assert!(props_loss > 0.01, "the disturbed render loses on props");
        assert_eq!(by_shape.keys().copied().collect::<Vec<_>>(), [0, 4, 9]);
        let total: f64 = by_shape.values().sum();
        assert!((total - props_loss).abs() < 1e-6, "{total} != {props_loss}");
        let without = score_frame(
            &reference,
            &RenderFrame {
                shapes: None,
                ..render
            },
            &sky(&reference),
            &policy,
        );
        assert!(without.shape_loss.is_none());
    }

    #[test]
    fn a_matching_render_loses_nothing() {
        let metrics = score(&capture(1.0), &matching_render());
        assert!((metrics.ssim - 1.0).abs() < 1e-5);
        assert!(metrics.loss_by_class.iter().all(|&loss| loss.abs() < 1e-5));
    }
}
