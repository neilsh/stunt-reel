//! Per-class SSIM loss attribution.

use std::collections::BTreeMap;

use stunt_core::frame::{
    LAYER_NONE, LAYER_OCEAN, LAYER_OVERLAY, LAYER_PROP, LAYER_TERRAIN, MODE13H_WIDTH,
};

use super::ssim::WindowScore;

/// What a scored pixel shows, by the render's layer and whether the capture has geometry
/// there (anything but the sky index). Indexed by [`loss_class`]; `*_render_only` is the
/// render drawing where the capture shows sky. `overlay` is the credits text, wherever it is.
pub(super) const LOSS_CLASSES: [&str; 10] = [
    "sky",
    "reference_only",
    "ocean",
    "terrain",
    "props",
    "actors",
    "ocean_render_only",
    "terrain_render_only",
    "props_and_actors_render_only",
    "overlay",
];

/// Index into [`LOSS_CLASSES`] of a pixel: `layer` from the render plane, `reference_filled`
/// whether the capture shows non-sky there.
pub(super) fn loss_class(layer: u16, reference_filled: bool) -> u8 {
    match (u32::from(layer), reference_filled) {
        (LAYER_OVERLAY, _) => 9,
        (LAYER_NONE, false) => 0,
        (LAYER_NONE, true) => 1,
        (LAYER_OCEAN, true) => 2,
        (LAYER_TERRAIN, true) => 3,
        (LAYER_PROP, true) => 4,
        (_, true) => 5,
        (LAYER_OCEAN, false) => 6,
        (LAYER_TERRAIN, false) => 7,
        (_, false) => 8,
    }
}

/// Splits `1 - ssim` of each window among the classes of its pixels in proportion to pixel
/// count, and averages over the windows. `classes` is a 320x240 plane of [`loss_class`]
/// codes. The result sums to `1 - mean(window scores)`.
pub(super) fn attribute_loss(
    windows: &[WindowScore],
    classes: &[u8],
    window_size: usize,
) -> [f32; LOSS_CLASSES.len()] {
    let mut loss = [0.0f32; LOSS_CLASSES.len()];
    if windows.is_empty() {
        return loss;
    }
    for window in windows {
        let mut counts = [0usize; LOSS_CLASSES.len()];
        #[expect(
            clippy::indexing_slicing,
            reason = "windows were scored over the same 320x240 plane as `classes`, and \
                      every class code comes from `loss_class`, below `LOSS_CLASSES.len()`"
        )]
        for row in window.y..window.y + window_size {
            let start = row * MODE13H_WIDTH + window.x;
            for &class in &classes[start..start + window_size] {
                counts[usize::from(class)] += 1;
            }
        }
        let window_loss = 1.0 - window.score;
        let pixels = (window_size * window_size) as f32;
        for (total, count) in loss.iter_mut().zip(counts) {
            *total += window_loss * count as f32 / pixels;
        }
    }
    for total in &mut loss {
        *total /= windows.len() as f32;
    }
    loss
}

/// Index into [`LOSS_CLASSES`] of `props`, the class [`attribute_shape_loss`] splits.
pub(super) const PROPS_CLASS: u8 = 4;

/// Splits the `props` share of each window's `1 - ssim` among the shapes of its props pixels,
/// as [`attribute_loss`] splits it among classes, and averages over the windows.
///
/// `classes` is the 320x240 plane of [`loss_class`] codes and `shapes` the 320x240 plane of
/// shape words (`shape id + 1`, 0 for a props pixel with no shape), both aligned with the
/// windows. The map is keyed by shape word and sums to `attribute_loss`'s `props` entry.
pub(super) fn attribute_shape_loss(
    windows: &[WindowScore],
    classes: &[u8],
    shapes: &[u16],
    window_size: usize,
) -> BTreeMap<u16, f64> {
    let mut loss = BTreeMap::new();
    if windows.is_empty() {
        return loss;
    }
    let pixels = (window_size * window_size) as f64;
    for window in windows {
        let window_loss = f64::from(1.0 - window.score);
        for row in window.y..window.y + window_size {
            let start = row * MODE13H_WIDTH + window.x;
            let span = start..start + window_size;
            let (Some(classes), Some(shapes)) = (classes.get(span.clone()), shapes.get(span))
            else {
                continue;
            };
            for (&class, &shape) in classes.iter().zip(shapes) {
                if class == PROPS_CLASS {
                    *loss.entry(shape).or_insert(0.0) += window_loss / pixels;
                }
            }
        }
    }
    for total in loss.values_mut() {
        *total /= windows.len() as f64;
    }
    loss
}

#[cfg(test)]
mod tests {
    use super::*;
    use stunt_core::frame::ASPECT_CORRECTED_HEIGHT;

    #[test]
    fn loss_classes_follow_the_render_layer_and_the_capture() {
        let class = |layer: u32, filled: bool| {
            LOSS_CLASSES[usize::from(loss_class(u16::try_from(layer).unwrap(), filled))]
        };
        assert_eq!(class(LAYER_NONE, false), "sky");
        assert_eq!(class(LAYER_NONE, true), "reference_only");
        assert_eq!(class(LAYER_OCEAN, true), "ocean");
        assert_eq!(class(LAYER_TERRAIN, true), "terrain");
        assert_eq!(class(LAYER_PROP, true), "props");
        assert_eq!(class(16, true), "actors");
        assert_eq!(class(LAYER_TERRAIN, false), "terrain_render_only");
        assert_eq!(class(17, false), "props_and_actors_render_only");
        assert_eq!(class(LAYER_OVERLAY, true), "overlay");
        assert_eq!(class(LAYER_OVERLAY, false), "overlay");
    }

    #[test]
    fn attributed_loss_sums_to_one_minus_the_mean_window_score() {
        let window = 4;
        let mut classes = vec![0u8; MODE13H_WIDTH * ASPECT_CORRECTED_HEIGHT];
        // The second window is half terrain, half props.
        for row in 0..window {
            for col in 0..window {
                classes[row * MODE13H_WIDTH + 8 + col] = if col < 2 { 3 } else { 4 };
            }
        }
        let windows = [
            WindowScore {
                x: 0,
                y: 0,
                score: 1.0,
            },
            WindowScore {
                x: 8,
                y: 0,
                score: 0.5,
            },
        ];
        let loss = attribute_loss(&windows, &classes, window);
        assert!((loss.iter().sum::<f32>() - 0.25).abs() < 1e-6);
        assert!((loss[3] - 0.125).abs() < 1e-6);
        assert!((loss[4] - 0.125).abs() < 1e-6);
        assert_eq!(loss[0], 0.0);
    }

    #[test]
    fn shape_loss_splits_the_props_loss_and_sums_to_it() {
        let window = 4;
        let mut classes = vec![0u8; MODE13H_WIDTH * ASPECT_CORRECTED_HEIGHT];
        let mut shapes = vec![0u16; classes.len()];
        // Window at x = 8: columns 0..2 terrain, column 2 props of shape word 5, column 3
        // props of shape word 9; window at x = 16: all props, with no shape.
        for row in 0..window {
            for col in 0..window {
                let at = row * MODE13H_WIDTH + 8 + col;
                classes[at] = if col < 2 { 3 } else { 4 };
                shapes[at] = if col == 2 { 5 } else { 9 };
                let at = row * MODE13H_WIDTH + 16 + col;
                classes[at] = 4;
            }
        }
        let windows = [
            WindowScore {
                x: 8,
                y: 0,
                score: 0.5,
            },
            WindowScore {
                x: 16,
                y: 0,
                score: 0.75,
            },
        ];
        let by_shape = attribute_shape_loss(&windows, &classes, &shapes, window);
        let by_class = attribute_loss(&windows, &classes, window);
        // Window 1 has 1 - ssim = 0.5, a quarter of it on each shape; window 2 has 0.25, all
        // of it unattributed; the mean over the two windows halves each.
        assert!((by_shape[&5] - 0.0625).abs() < 1e-9, "{by_shape:?}");
        assert!((by_shape[&9] - 0.0625).abs() < 1e-9, "{by_shape:?}");
        assert!((by_shape[&0] - 0.125).abs() < 1e-9, "{by_shape:?}");
        assert_eq!(by_shape.len(), 3);
        let total: f64 = by_shape.values().sum();
        assert!((total - f64::from(by_class[usize::from(PROPS_CLASS)])).abs() < 1e-6);
    }
}
