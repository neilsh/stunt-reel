//! Verifies that an `OP_PERFDISK` disc covers the pixels `0xD11D` fills: rows `y - H` to
//! `y + H - 1` and, at its centre rows, `x - A` to `x + A`, about the pixel `(160, 92)` for a
//! disc on the view's axis (`research/playone-exe/sod-vm-generators.md` section 8.8).
//!
//! Skips when no GPU adapter is available (see common); fails instead of skipping under
//! `STUNT_REQUIRE_GPU=1` (ADR 0006).

use crate::common;

use stunt_core::contracts::{CameraTransform, DecodeMode, SodModelIr};
use stunt_core::scene::FilmScene;
use stunt_core::sod::{OP_COLOR, OP_ID, OP_PERFDISK, OP_RETURN, OP_VECTORS, decode_sod};
use stunt_render::{LAYER_NONE, Offscreen, PageSize, RenderOptions};

const DISC_INDEX: u8 = 45;

/// A shape of one disc of `radius` about the origin, facing +z, at scale 1.0.
fn disc_shape(radius: u16) -> SodModelIr {
    let mut words: Vec<u16> = vec![OP_ID, 100, 0, 0, 0, OP_VECTORS, 2, 12];
    // Register 1, the centre, at the origin; register 2, the axis, 10 units down -z.
    words.extend([0, 0, 0, 0, 0, (-10i16).cast_unsigned()]);
    words.extend([
        OP_COLOR,
        u16::from(DISC_INDEX),
        OP_PERFDISK,
        12,
        radius,
        24,
        OP_RETURN,
    ]);
    let bytes: Vec<u8> = words.iter().flat_map(|w| w.to_le_bytes()).collect();
    decode_sod(&bytes, "DISC", None, DecodeMode::Strict).expect("the disc shape decodes")
}

/// The pixels, as (column, row), the disc covers seen from `distance` metres down +z on
/// PLAYONE's 320x200 page with its 185-row view.
fn covered(radius: u16, distance: f32) -> Option<Vec<(usize, usize)>> {
    let camera = CameraTransform {
        eye: [0.0, 0.0, distance],
        target: [0.0, 0.0, 0.0],
        fov_degrees: 45.0,
        roll_radians: 0.0,
        cut_from_previous: false,
        ..Default::default()
    };
    let scene = FilmScene::with_single_model(common::still_timeline(camera), disc_shape(radius));
    let target = Offscreen {
        size: PageSize::new(320, 200),
        viewport_rows: Some(185),
    };
    let mut test = common::gpu_or_skip_offscreen(&scene, target, RenderOptions::default())?;
    let page = test.draw(&scene.frame(0.0));
    let width = page.width() as usize;
    Some(
        page.layers()
            .iter()
            .zip(page.indices())
            .enumerate()
            .filter(|&(_, (&layer, &index))| layer != LAYER_NONE && index == DISC_INDEX)
            .map(|(at, _)| (at % width, at / width))
            .collect(),
    )
}

#[test]
fn a_disc_on_the_axis_covers_an_even_run_of_rows_and_an_odd_run_of_columns() {
    common::gpu_test(|| {
        // Several pixel radii, from about 60 px down.
        for distance in [40.0, 57.0, 90.0, 150.0] {
            let Some(pixels) = covered(10, distance) else {
                return;
            };
            assert!(!pixels.is_empty(), "{distance} m: no disc drawn");
            let top = pixels.iter().map(|p| p.1).min().unwrap();
            let bottom = pixels.iter().map(|p| p.1).max().unwrap();
            // Rows y - H to y + H - 1 about the boundary above row 92.
            assert_eq!(
                top + bottom,
                2 * 92 - 1,
                "{distance} m: rows {top}..={bottom}"
            );
            // At the centre rows, x - A to x + A about column 160.
            for row in [91, 92] {
                let columns: Vec<usize> =
                    pixels.iter().filter(|p| p.1 == row).map(|p| p.0).collect();
                let left = columns.iter().copied().min().unwrap();
                let right = columns.iter().copied().max().unwrap();
                assert_eq!(
                    left + right,
                    2 * 160,
                    "{distance} m row {row}: {left}..={right}"
                );
                assert_eq!(
                    columns.len(),
                    right - left + 1,
                    "{distance} m row {row}: a gap"
                );
            }
        }
    });
}
