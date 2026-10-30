#![allow(
    clippy::unwrap_used,
    clippy::expect_used,
    clippy::panic,
    clippy::print_stderr,
    clippy::default_trait_access,
    clippy::items_after_statements,
    reason = "integration tests assert by panicking, and their helpers sit outside #[test] fns"
)]
//! Cross-check of the hand-written SSIM in `stunt_render::parity` against `image-compare`.
//!
//! The in-tree SSIM is intentional (`[I6]` thresholds are tied to its exact variant, and it adds
//! masks and fade compensation); `image-compare` is a dev-dependency used only as an independent
//! witness. Frames are synthetic gradients, so the test needs no `corpus/` data (`[I7]`).
//!
//! Both implementations use uniform 8x8 windows over `[0, 255]` with `C1 = (0.01 * 255)^2` and
//! `C2 = (0.03 * 255)^2`, but they differ in one normalisation: `image-compare` uses the *sum* of
//! squared deviations as "variance"/"covariance", while `stunt_render` divides by `n - 1` (= 63).
//! At the production constants the two scores therefore differ (only identical frames agree), so:
//!
//! 1. with `C2` rescaled to `C2 / 63` the two formulas are algebraically identical and must
//!    agree to float precision, which checks the window arithmetic and the tiling;
//! 2. at the production constants only identity (`1.0`) and monotonic ordering are asserted.

use image::GrayImage;
use image_compare::{Algorithm, gray_similarity_structure};
use stunt_render::parity::{C1_CONSTANT, C2_CONSTANT, compute_frame_ssim};

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
            let i = i as u32;
            let noise = (i.wrapping_mul(2_654_435_761) >> 24) % (2 * amplitude + 1);
            (i32::from(v) + noise as i32 - amplitude as i32).clamp(0, 255) as u8
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
    if c2 == C2_CONSTANT {
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
            scores.push(stunt_render::parity::compute_window_ssim(
                &wa,
                &wb,
                C1_CONSTANT,
                c2,
            ));
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
