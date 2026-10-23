//! Per-class SSIM loss attribution.

use stunt_render::{
    LAYER_NONE, LAYER_OCEAN, LAYER_PROP, LAYER_TERRAIN, MODE13H_WIDTH, WindowScore,
};

/// What a scored pixel shows, by the render's layer and whether the capture has geometry
/// there (anything but the sky index). Indexed by [`loss_class`]; `*_render_only` is the
/// render drawing where the capture shows sky.
pub(super) const LOSS_CLASSES: [&str; 9] = [
    "sky",
    "reference_only",
    "ocean",
    "terrain",
    "props",
    "actors",
    "ocean_render_only",
    "terrain_render_only",
    "props_and_actors_render_only",
];

/// Index into [`LOSS_CLASSES`] of a pixel: `layer` from the render plane, `reference_filled`
/// whether the capture shows non-sky there.
pub(super) fn loss_class(layer: u16, reference_filled: bool) -> u8 {
    match (u32::from(layer), reference_filled) {
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

#[cfg(test)]
mod tests {
    use super::*;
    use stunt_render::ASPECT_CORRECTED_HEIGHT;

    #[test]
    fn loss_classes_follow_the_render_layer_and_the_capture() {
        let class =
            |layer: u32, filled: bool| LOSS_CLASSES[usize::from(loss_class(layer as u16, filled))];
        assert_eq!(class(LAYER_NONE, false), "sky");
        assert_eq!(class(LAYER_NONE, true), "reference_only");
        assert_eq!(class(LAYER_OCEAN, true), "ocean");
        assert_eq!(class(LAYER_TERRAIN, true), "terrain");
        assert_eq!(class(LAYER_PROP, true), "props");
        assert_eq!(class(16, true), "actors");
        assert_eq!(class(LAYER_TERRAIN, false), "terrain_render_only");
        assert_eq!(class(17, false), "props_and_actors_render_only");
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
}
