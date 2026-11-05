//! Frame-scoring math: Rec. 601 luminance, the 320x200 to 320x240 stretch and windowed SSIM.
//!
//! Complies with Architectural Invariants:
//! - `[I6]` Visual parity acceptance thresholds (the gate itself lives in the parity report).
//! - `[I3]` VGA Mode 13h aspect ratio correction ($320 \times 200 \to 320 \times 240$, 1.2x vertical stretch).
//!
//! Pure CPU math over `f32` planes. The parity scorer is its only consumer, which is why it sits
//! here and not in the renderer crate; the raster dimensions it is called with come from
//! `stunt_render` (`MODE13H_WIDTH`, `MODE13H_HEIGHT`, `ASPECT_CORRECTED_HEIGHT`).

/// SSIM stability constant C1 for dynamic range [0, 255]: (0.01 * 255)^2 = 6.5025.
pub(super) const C1_CONSTANT: f32 = 6.5025;

/// SSIM stability constant C2 for dynamic range [0, 255]: (0.03 * 255)^2 = 58.5225.
pub(super) const C2_CONSTANT: f32 = 58.5225;

/// Computes Rec. 601 perceptual luminance from RGB in [0.0, 255.0].
#[inline]
pub(super) fn compute_luminance(r: f32, g: f32, b: f32) -> f32 {
    0.299 * r + 0.587 * g + 0.114 * b
}

/// Converts a contiguous RGB8 buffer to a flat luminance float slice.
pub(super) fn rgb_to_luminance(rgb: &[u8]) -> Vec<f32> {
    let mut lum = Vec::with_capacity(rgb.len() / 3);
    for chunk in rgb.as_chunks::<3>().0 {
        lum.push(compute_luminance(
            f32::from(chunk[0]),
            f32::from(chunk[1]),
            f32::from(chunk[2]),
        ));
    }
    lum
}

/// Rescales 320x200 Mode 13h raster to 320x240 physical 4:3 CRT aspect (1.2x stretch) via nearest-neighbor.
///
/// # Panics
/// Panics if `height` is zero or `src` holds fewer than `width * height` values.
pub(super) fn rescale_mode13h_frame(
    src: &[f32],
    width: usize,
    height: usize,
    target_height: usize,
) -> Vec<f32> {
    assert!(height > 0, "source frame has no rows");
    assert!(
        src.len() >= width * height,
        "source holds {} values, fewer than {width}x{height}",
        src.len()
    );
    let mut target = vec![0.0f32; width * target_height];
    if width == 0 {
        return target;
    }
    let scale_y = height as f32 / target_height as f32; // 200 / 240 = 5/6
    let rows_in: Vec<&[f32]> = src.chunks_exact(width).take(height).collect();

    for (y_out, row_out) in target.chunks_exact_mut(width).enumerate() {
        #[expect(
            clippy::cast_possible_truncation,
            clippy::cast_sign_loss,
            reason = "a row of a frame of a few hundred rows, floored"
        )]
        let y_in = ((y_out as f32 * scale_y) as usize).min(height.saturating_sub(1));
        if let Some(row_in) = rows_in.get(y_in) {
            row_out.copy_from_slice(row_in);
        }
    }

    target
}

/// Computes SSIM for a single local window between two image patches.
pub(super) fn compute_window_ssim(window_x: &[f32], window_y: &[f32], c1: f32, c2: f32) -> f32 {
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

    for (&x, &y) in window_x.iter().zip(window_y) {
        let dx = x - mu_x;
        let dy = y - mu_y;
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
pub(super) fn compute_frame_ssim(
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
pub(super) struct WindowScore {
    /// Window column.
    pub(super) x: usize,
    /// Window row.
    pub(super) y: usize,
    /// SSIM of the window.
    pub(super) score: f32,
}

/// SSIM of every window not touching `excluded` (row-major, `width * height`), in scan order.
///
/// Returns no windows when `window_size` or `stride` is zero or the window is larger than
/// the frame in either dimension.
///
/// # Panics
/// Panics if `frame_a` and `frame_b` differ in length or hold fewer than `width * height`
/// values, or `excluded` is given with a length other than theirs.
pub(super) fn compute_window_scores(
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
    assert!(
        frame_a.len() >= width * height,
        "frames hold {} values, fewer than {width}x{height}",
        frame_a.len()
    );

    if window_size == 0 || stride == 0 || window_size > width || window_size > height {
        return Vec::new();
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
                // The asserts above with `x <= max_x` and `y <= max_y` keep each row in the
                // frame, so every `get` here is `Some`.
                let row_idx = (y + wy) * width + x;
                let row = row_idx..row_idx + window_size;
                win_a.extend(frame_a.get(row.clone()).into_iter().flatten());
                win_b.extend(frame_b.get(row.clone()).into_iter().flatten());
                if let Some(mask) = excluded {
                    touches_mask |= mask.get(row).into_iter().flatten().any(|&m| m);
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
pub(super) fn compute_frame_ssim_masked(
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

#[cfg(test)]
mod tests {
    use super::*;
    use stunt_render::{ASPECT_CORRECTED_HEIGHT, MODE13H_HEIGHT, MODE13H_WIDTH};

    #[test]
    fn degenerate_windows_yield_no_scores_instead_of_panicking_or_hanging() {
        let frame = [0.5f32];
        // A window wider than the frame used to slice past it; a zero stride never advanced.
        assert!(compute_window_scores(&frame, &frame, 1, 1, 2, 1, None).is_empty());
        assert!(compute_window_scores(&frame, &frame, 1, 1, 1, 0, None).is_empty());
        assert!(compute_window_scores(&frame, &frame, 1, 1, 0, 1, None).is_empty());
        assert_eq!(
            compute_window_scores(&frame, &frame, 1, 1, 1, 1, None).len(),
            1
        );
    }

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

    #[test]
    fn test_ssim_evaluator() {
        let size = MODE13H_WIDTH * ASPECT_CORRECTED_HEIGHT;
        let mut frame_ref = vec![100.0f32; size];
        // Add patterned details
        for (i, item) in frame_ref.iter_mut().enumerate() {
            *item = ((i % 128) + 50) as f32;
        }

        // Identical frame -> SSIM must be 1.0
        let ssim_ident = compute_frame_ssim(
            &frame_ref,
            &frame_ref,
            MODE13H_WIDTH,
            ASPECT_CORRECTED_HEIGHT,
            11,
            8,
        );
        assert!(
            (ssim_ident - 1.0).abs() < 1e-4,
            "Expected 1.0, got {ssim_ident}"
        );

        // Slightly perturbed frame (0.5 LSB average) -> SSIM should easily exceed the sign-off
        // threshold (>= 0.90)
        let frame_test: Vec<f32> = frame_ref.iter().map(|&v| (v + 0.5).min(255.0)).collect();
        let ssim_test = compute_frame_ssim(
            &frame_ref,
            &frame_test,
            MODE13H_WIDTH,
            ASPECT_CORRECTED_HEIGHT,
            11,
            8,
        );
        assert!(ssim_test >= 0.90, "SSIM {ssim_test} must be >= 0.90");
    }

    #[test]
    fn test_blank_page_luminance_is_flat() {
        let rgb = vec![255u8; MODE13H_WIDTH * ASPECT_CORRECTED_HEIGHT * 3];
        let lum = rgb_to_luminance(&rgb);
        assert_eq!(lum.len(), MODE13H_WIDTH * ASPECT_CORRECTED_HEIGHT);
        assert!(lum.iter().all(|&value| (value - 255.0).abs() < 1e-3));
    }
}

/// Cross-check of the hand-written SSIM above against `image-compare`.
///
/// The in-tree SSIM is intentional (`[I6]` thresholds are tied to its exact variant, and it adds
/// masks and fade compensation); `image-compare` is a dev-dependency used only as an independent
/// witness. Frames are synthetic gradients, so the test needs no `corpus/` data (`[I7]`).
///
/// Both implementations use uniform 8x8 windows over `[0, 255]` with `C1 = (0.01 * 255)^2` and
/// `C2 = (0.03 * 255)^2`, but they differ in one normalisation: `image-compare` uses the *sum* of
/// squared deviations as "variance"/"covariance", while this module divides by `n - 1` (= 63).
/// At the production constants the two scores therefore differ (only identical frames agree), so:
///
/// 1. with `C2` rescaled to `C2 / 63` the two formulas are algebraically identical and must
///    agree to float precision, which checks the window arithmetic and the tiling;
/// 2. at the production constants only identity (`1.0`) and monotonic ordering are asserted.
#[cfg(test)]
mod crosscheck_tests {
    use super::{C1_CONSTANT, C2_CONSTANT, compute_frame_ssim, compute_window_ssim};
    use image::GrayImage;
    use image_compare::{Algorithm, gray_similarity_structure};

    const WIDTH: u32 = 64;
    const HEIGHT: u32 = 48;
    const WINDOW: usize = 8;

    /// A smooth diagonal gradient with a little texture, as integer luminance (`image-compare`
    /// works on `u8`).
    fn reference() -> Vec<u8> {
        let mut out = Vec::new();
        for y in 0..HEIGHT {
            for x in 0..WIDTH {
                let base = 40 + 2 * x + 3 * y;
                let texture = (x * 7 + y * 13) % 11;
                out.push((base + texture).min(255) as u8);
            }
        }
        out
    }

    /// The reference with a deterministic perturbation of the given amplitude.
    fn perturbed(amplitude: u32) -> Vec<u8> {
        reference()
            .iter()
            .enumerate()
            .map(|(i, &v)| {
                let i = u32::try_from(i).unwrap();
                let noise = (i.wrapping_mul(2_654_435_761) >> 24) % (2 * amplitude + 1);
                let noisy = i32::from(v) + i32::try_from(noise).unwrap()
                    - i32::try_from(amplitude).unwrap();
                u8::try_from(noisy.clamp(0, 255)).unwrap()
            })
            .collect()
    }

    fn gray(pixels: &[u8]) -> GrayImage {
        GrayImage::from_raw(WIDTH, HEIGHT, pixels.to_vec()).expect("dimensions")
    }

    fn theirs(a: &[u8], b: &[u8]) -> f64 {
        gray_similarity_structure(&Algorithm::MSSIMSimple, &gray(a), &gray(b))
            .expect("same dimensions")
            .score
    }

    fn ours(a: &[u8], b: &[u8], c2: f32) -> f32 {
        let to_f32 = |p: &[u8]| p.iter().map(|&v| f32::from(v)).collect::<Vec<_>>();
        // `compute_frame_ssim` fixes the production constants; rebuild the same non-overlapping
        // tiling with a custom `C2` through the window scorer instead.
        let (fa, fb) = (to_f32(a), to_f32(b));
        if c2.to_bits() == C2_CONSTANT.to_bits() {
            return compute_frame_ssim(&fa, &fb, WIDTH as usize, HEIGHT as usize, WINDOW, WINDOW);
        }
        let mut scores = Vec::new();
        let (w, h) = (WIDTH as usize, HEIGHT as usize);
        for y in (0..h).step_by(WINDOW) {
            for x in (0..w).step_by(WINDOW) {
                let (mut wa, mut wb) = (Vec::new(), Vec::new());
                for row in y..y + WINDOW {
                    wa.extend_from_slice(&fa[row * w + x..row * w + x + WINDOW]);
                    wb.extend_from_slice(&fb[row * w + x..row * w + x + WINDOW]);
                }
                scores.push(compute_window_ssim(&wa, &wb, C1_CONSTANT, c2));
            }
        }
        scores.iter().sum::<f32>() / scores.len() as f32
    }

    #[test]
    fn ssim_agrees_with_image_compare() {
        let base = reference();
        let rescaled_c2 = C2_CONSTANT / (WINDOW * WINDOW - 1) as f32;

        let mild = perturbed(6);
        let heavy = perturbed(40);

        // Identical frames score exactly 1 in both.
        assert!((theirs(&base, &base) - 1.0).abs() < 1e-12);
        assert_eq!(ours(&base, &base, C2_CONSTANT), 1.0);

        // Same formula once the variance normalisation is matched.
        for other in [&mild, &heavy] {
            let a = f64::from(ours(&base, other, rescaled_c2));
            let b = theirs(&base, other);
            assert!(
                (a - b).abs() < 2e-4,
                "rescaled-C2 ours {a} vs image-compare {b}"
            );
        }

        // Production constants: monotonic in perturbation for both implementations.
        let (our_mild, our_heavy) = (
            ours(&base, &mild, C2_CONSTANT),
            ours(&base, &heavy, C2_CONSTANT),
        );
        let (their_mild, their_heavy) = (theirs(&base, &mild), theirs(&base, &heavy));
        assert!(
            1.0 > our_mild && our_mild > our_heavy,
            "{our_mild} {our_heavy}"
        );
        assert!(
            1.0 > their_mild && their_mild > their_heavy,
            "{their_mild} {their_heavy}"
        );
    }
}
