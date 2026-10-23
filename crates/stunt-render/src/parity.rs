//! Invariant `[I6]` Visual Parity and Structural Similarity (SSIM) Evaluator.
//!
//! Complies with Architectural Invariants:
//! - `[I6]` Visual parity acceptance thresholds (SSIM >= 0.88 Phase 1, >= 0.90 Phase 2).
//! - `[I3]` VGA Mode 13h aspect ratio correction ($320 \times 200 \to 320 \times 240$, 1.2x vertical stretch).

use stunt_core::contracts::VisualParityReport;

/// SSIM stability constant C1 for dynamic range [0, 255]: (0.01 * 255)^2 = 6.5025.
pub const C1_CONSTANT: f32 = 6.5025;

/// SSIM stability constant C2 for dynamic range [0, 255]: (0.03 * 255)^2 = 58.5225.
pub const C2_CONSTANT: f32 = 58.5225;

/// Phase 1 glTF export threshold (Gate G05).
pub const PHASE1_SSIM_THRESHOLD: f32 = 0.88;

/// Phase 2 Native wgpu engine threshold (Gate G06).
pub const PHASE2_SSIM_THRESHOLD: f32 = 0.90;

/// Base Mode 13h framebuffer width in pixels.
pub const MODE13H_WIDTH: usize = 320;

/// Original Mode 13h framebuffer height in pixels.
pub const MODE13H_HEIGHT: usize = 200;

/// Aspect-corrected 4:3 presentation height in pixels ($200 \times 1.2$).
pub const ASPECT_CORRECTED_HEIGHT: usize = 240;

/// Computes Rec. 601 perceptual luminance from RGB in [0.0, 255.0].
#[inline]
pub fn compute_luminance(r: f32, g: f32, b: f32) -> f32 {
    0.299 * r + 0.587 * g + 0.114 * b
}

/// Converts a contiguous RGBA8 buffer to a flat luminance float slice.
pub fn rgba_to_luminance(rgba: &[u8]) -> Vec<f32> {
    let pixel_count = rgba.len() / 4;
    let mut lum = Vec::with_capacity(pixel_count);
    for chunk in rgba.as_chunks::<4>().0 {
        lum.push(compute_luminance(
            chunk[0] as f32,
            chunk[1] as f32,
            chunk[2] as f32,
        ));
    }
    lum
}

/// Converts a contiguous RGB8 buffer to a flat luminance float slice.
pub fn rgb_to_luminance(rgb: &[u8]) -> Vec<f32> {
    let mut lum = Vec::with_capacity(rgb.len() / 3);
    for chunk in rgb.as_chunks::<3>().0 {
        lum.push(compute_luminance(
            chunk[0] as f32,
            chunk[1] as f32,
            chunk[2] as f32,
        ));
    }
    lum
}

/// Rescales 320x200 Mode 13h raster to 320x240 physical 4:3 CRT aspect (1.2x stretch) via nearest-neighbor.
pub fn rescale_mode13h_frame(
    src: &[f32],
    width: usize,
    height: usize,
    target_height: usize,
) -> Vec<f32> {
    let mut target = vec![0.0f32; width * target_height];
    let scale_y = height as f32 / target_height as f32; // 200 / 240 = 5/6

    for y_out in 0..target_height {
        let mut y_in = (y_out as f32 * scale_y) as usize;
        if y_in >= height {
            y_in = height - 1;
        }
        let row_out = y_out * width;
        let row_in = y_in * width;
        target[row_out..row_out + width].copy_from_slice(&src[row_in..row_in + width]);
    }

    target
}

/// Computes SSIM for a single local window between two image patches.
pub fn compute_window_ssim(window_x: &[f32], window_y: &[f32], c1: f32, c2: f32) -> f32 {
    let n = window_x.len();
    if n == 0 || window_y.len() != n {
        return 0.0;
    }

    let n_f = n as f32;
    let mu_x = window_x.iter().sum::<f32>() / n_f;
    let mu_y = window_y.iter().sum::<f32>() / n_f;

    let mut var_x = 0.0f32;
    let mut var_y = 0.0f32;
    let mut cov_xy = 0.0f32;

    for i in 0..n {
        let dx = window_x[i] - mu_x;
        let dy = window_y[i] - mu_y;
        var_x += dx * dx;
        var_y += dy * dy;
        cov_xy += dx * dy;
    }

    let deg_free = ((n - 1).max(1)) as f32;
    let sig_sq_x = var_x / deg_free;
    let sig_sq_y = var_y / deg_free;
    let sig_xy = cov_xy / deg_free;

    let num = (2.0 * mu_x * mu_y + c1) * (2.0 * sig_xy + c2);
    let den = (mu_x * mu_x + mu_y * mu_y + c1) * (sig_sq_x + sig_sq_y + c2);

    if den <= 1e-12 {
        if num <= 1e-12 { 1.0 } else { 0.0 }
    } else {
        num / den
    }
}

/// Computes mean Structural Similarity Index (SSIM) between two 2D normalized frames.
pub fn compute_frame_ssim(
    frame_a: &[f32],
    frame_b: &[f32],
    width: usize,
    height: usize,
    window_size: usize,
    stride: usize,
) -> f32 {
    compute_frame_ssim_masked(frame_a, frame_b, width, height, window_size, stride, None)
}

/// SSIM of one window of a frame pair, with the window's top-left corner.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct WindowScore {
    /// Window column.
    pub x: usize,
    /// Window row.
    pub y: usize,
    /// SSIM of the window.
    pub score: f32,
}

/// SSIM of every window not touching `excluded` (row-major, `width * height`), in scan order.
pub fn compute_window_scores(
    frame_a: &[f32],
    frame_b: &[f32],
    width: usize,
    height: usize,
    window_size: usize,
    stride: usize,
    excluded: Option<&[bool]>,
) -> Vec<WindowScore> {
    assert_eq!(
        frame_a.len(),
        frame_b.len(),
        "Frame length mismatch: {} vs {}",
        frame_a.len(),
        frame_b.len()
    );
    if let Some(mask) = excluded {
        assert_eq!(mask.len(), frame_a.len(), "Mask length mismatch");
    }

    let mut scores = Vec::new();
    let mut win_a = Vec::with_capacity(window_size * window_size);
    let mut win_b = Vec::with_capacity(window_size * window_size);

    let max_y = height.saturating_sub(window_size);
    let max_x = width.saturating_sub(window_size);

    let mut y = 0;
    while y <= max_y {
        let mut x = 0;
        while x <= max_x {
            win_a.clear();
            win_b.clear();
            let mut touches_mask = false;

            for wy in 0..window_size {
                let row_idx = (y + wy) * width + x;
                win_a.extend_from_slice(&frame_a[row_idx..row_idx + window_size]);
                win_b.extend_from_slice(&frame_b[row_idx..row_idx + window_size]);
                if let Some(mask) = excluded {
                    touches_mask |= mask[row_idx..row_idx + window_size].iter().any(|&m| m);
                }
            }

            if !touches_mask {
                scores.push(WindowScore {
                    x,
                    y,
                    score: compute_window_ssim(&win_a, &win_b, C1_CONSTANT, C2_CONSTANT),
                });
            }

            x += stride;
        }
        y += stride;
    }
    scores
}

/// Like [`compute_frame_ssim`], but a window that touches any `true` pixel of `excluded`
/// (row-major, `width * height`) contributes nothing to the mean. When every window is
/// excluded the result is `1.0`, since nothing disagrees.
pub fn compute_frame_ssim_masked(
    frame_a: &[f32],
    frame_b: &[f32],
    width: usize,
    height: usize,
    window_size: usize,
    stride: usize,
    excluded: Option<&[bool]>,
) -> f32 {
    let scores = compute_window_scores(
        frame_a,
        frame_b,
        width,
        height,
        window_size,
        stride,
        excluded,
    );
    if scores.is_empty() {
        if excluded.is_some() {
            1.0
        } else {
            compute_window_ssim(frame_a, frame_b, C1_CONSTANT, C2_CONSTANT)
        }
    } else {
        scores.iter().map(|w| w.score).sum::<f32>() / scores.len() as f32
    }
}

/// Executes visual parity verification suite across multi-frame sequences.
pub fn evaluate_visual_parity(
    reference_frames: &[Vec<f32>],
    test_frames: &[Vec<f32>],
    film_name: impl Into<String>,
    threshold: f32,
    apply_aspect_stretch: bool,
) -> VisualParityReport {
    let film_name = film_name.into();
    let num_frames = reference_frames.len().min(test_frames.len());

    if num_frames == 0 {
        return VisualParityReport {
            film_name,
            frames_evaluated: 0,
            mean_ssim: 0.0,
            min_ssim: 0.0,
            threshold,
            passed: false,
        };
    }

    let mut ssim_scores = Vec::with_capacity(num_frames);

    for i in 0..num_frames {
        let ref_f = &reference_frames[i];
        let test_f = &test_frames[i];

        let (norm_ref, norm_test) = if apply_aspect_stretch {
            (
                rescale_mode13h_frame(
                    ref_f,
                    MODE13H_WIDTH,
                    MODE13H_HEIGHT,
                    ASPECT_CORRECTED_HEIGHT,
                ),
                rescale_mode13h_frame(
                    test_f,
                    MODE13H_WIDTH,
                    MODE13H_HEIGHT,
                    ASPECT_CORRECTED_HEIGHT,
                ),
            )
        } else {
            (ref_f.clone(), test_f.clone())
        };

        let score = compute_frame_ssim(
            &norm_ref,
            &norm_test,
            MODE13H_WIDTH,
            ASPECT_CORRECTED_HEIGHT,
            11,
            8,
        );
        ssim_scores.push(score);
    }

    let mean_score = ssim_scores.iter().sum::<f32>() / ssim_scores.len() as f32;
    let min_score = ssim_scores.iter().copied().fold(f32::INFINITY, f32::min);
    let passed = mean_score >= threshold;

    VisualParityReport {
        film_name,
        frames_evaluated: num_frames,
        mean_ssim: mean_score,
        min_ssim: min_score,
        threshold,
        passed,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn masked_ssim_ignores_windows_touching_the_mask() {
        let (w, h) = (32, 32);
        let a: Vec<f32> = (0..w * h).map(|i| (i % 7) as f32 * 20.0).collect();
        let mut b = a.clone();
        let mut excluded = vec![false; w * h];
        // Corrupt the bottom rows and mask them; the unmasked windows are untouched.
        for i in (24 * w)..(h * w) {
            b[i] = 255.0 - b[i];
            excluded[i] = true;
        }
        let unmasked = compute_frame_ssim(&a, &b, w, h, 8, 8);
        let masked = compute_frame_ssim_masked(&a, &b, w, h, 8, 8, Some(&excluded));
        assert!(unmasked < 0.9, "corruption must hurt the unmasked score");
        assert!((masked - 1.0).abs() < 1e-6, "masked score {masked}");
        let all = vec![true; w * h];
        assert_eq!(
            compute_frame_ssim_masked(&a, &b, w, h, 8, 8, Some(&all)),
            1.0
        );
    }

    #[test]
    fn test_identity_frame_ssim() {
        let size = MODE13H_WIDTH * ASPECT_CORRECTED_HEIGHT;
        let frame: Vec<f32> = (0..size).map(|i| (i % 256) as f32).collect();

        let ssim = compute_frame_ssim(
            &frame,
            &frame,
            MODE13H_WIDTH,
            ASPECT_CORRECTED_HEIGHT,
            11,
            8,
        );
        assert!(
            (ssim - 1.0).abs() < 1e-4,
            "Identity frames must have SSIM == 1.0, got {ssim}"
        );
    }

    #[test]
    fn test_near_identical_frame_high_ssim() {
        let size = MODE13H_WIDTH * ASPECT_CORRECTED_HEIGHT;
        let frame_a: Vec<f32> = (0..size).map(|i| (i % 256) as f32).collect();
        // Slightly perturbed frame (1 LSB change)
        let frame_b: Vec<f32> = frame_a.iter().map(|&v| (v + 1.0).min(255.0)).collect();

        let ssim = compute_frame_ssim(
            &frame_a,
            &frame_b,
            MODE13H_WIDTH,
            ASPECT_CORRECTED_HEIGHT,
            11,
            8,
        );
        assert!(
            ssim > 0.98,
            "Near-identical frames must have SSIM > 0.98, got {ssim}"
        );
    }

    #[test]
    fn test_rescale_mode13h_frame_dimensions() {
        let src = vec![128.0f32; MODE13H_WIDTH * MODE13H_HEIGHT];
        let rescaled =
            rescale_mode13h_frame(&src, MODE13H_WIDTH, MODE13H_HEIGHT, ASPECT_CORRECTED_HEIGHT);
        assert_eq!(rescaled.len(), MODE13H_WIDTH * ASPECT_CORRECTED_HEIGHT);
    }
}
