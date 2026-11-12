//! Verifies that SOD lines (`MOVETO`/`ZLINETO`) draw one Mode 13h pixel wide at any distance,
//! decoded from synthetic shapes and read from `RenderedPage`.
//!
//! Skips when no GPU adapter is available (see common); fails instead of skipping under
//! `STUNT_REQUIRE_GPU=1` (ADR 0006).

use crate::common;

use stunt_core::contracts::{CameraTransform, DecodeMode, SodModelIr};
use stunt_core::scene::FilmScene;
use stunt_core::sod::{
    OP_ID, OP_LINECOL, OP_MOVETO, OP_RETURN, OP_VECTORS, OP_ZLINETO, decode_sod,
};
use stunt_render::{LAYER_NONE, Offscreen, PageSize, RenderOptions};

const LINE_INDEX: u8 = 33;

/// A shape of one `ZLINETO` segment between two raw points, at scale 1.0.
fn line_shape(from: [i16; 3], to: [i16; 3]) -> SodModelIr {
    let mut words: Vec<u16> = vec![OP_ID, 100, 0, 0, 0, OP_VECTORS, 2, 0];
    words.extend(from.iter().chain(&to).map(|&c| c.cast_unsigned()));
    words.extend([
        OP_LINECOL,
        u16::from(LINE_INDEX),
        OP_MOVETO,
        0,
        OP_ZLINETO,
        12,
        OP_RETURN,
    ]);
    let bytes: Vec<u8> = words.iter().flat_map(|w| w.to_le_bytes()).collect();
    decode_sod(&bytes, "LINE", None, DecodeMode::Strict).expect("the line shape decodes")
}

/// Renders the shape from `distance` metres down -Z on PLAYONE's 320x200 page with its
/// 185-row view, and returns the pixels the line covers as (column, row).
fn covered(ir: SodModelIr, distance: f32) -> Option<Vec<(usize, usize)>> {
    let camera = CameraTransform {
        eye: [0.0, 0.0, distance],
        target: [0.0, 0.0, 0.0],
        fov_degrees: 45.0,
        roll_radians: 0.0,
        cut_from_previous: false,
        ..Default::default()
    };
    let scene = FilmScene::with_single_model(common::still_timeline(camera), ir);
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
            .filter(|&(_, (&layer, &index))| layer != LAYER_NONE && index == LINE_INDEX)
            .map(|(at, _)| (at % width, at / width))
            .collect(),
    )
}

/// How many covered pixels fall on each value of one coordinate, over the values covered.
fn per_line(pixels: &[(usize, usize)], key: impl Fn(&(usize, usize)) -> usize) -> Vec<usize> {
    let lo = pixels
        .iter()
        .map(&key)
        .min()
        .expect("the line covers a pixel");
    let hi = pixels
        .iter()
        .map(&key)
        .max()
        .expect("the line covers a pixel");
    (lo..=hi)
        .map(|k| pixels.iter().filter(|p| key(p) == k).count())
        .collect()
}

#[test]
fn a_shallow_line_covers_one_pixel_per_column_near_and_far() {
    common::gpu_test(|| {
        // 40 m across, sloping 4 m: about 9 to 45 columns long between 1000 m and 200 m.
        for distance in [200.0, 1000.0] {
            let Some(pixels) = covered(line_shape([-20, -2, 0], [20, 2, 0]), distance) else {
                return;
            };
            let columns = per_line(&pixels, |&(x, _)| x);
            assert!(columns.len() >= 8, "{distance} m: {pixels:?}");
            assert!(
                columns.iter().all(|&n| n == 1),
                "{distance} m: one pixel in every column the line crosses, got {columns:?}"
            );
            let rows = per_line(&pixels, |&(_, y)| y);
            assert!(
                rows.iter().all(|&n| n > 0),
                "{distance} m: connected, {rows:?}"
            );
        }
    });
}

#[test]
fn a_steep_line_covers_one_pixel_per_row_near_and_far() {
    common::gpu_test(|| {
        for distance in [200.0, 1000.0] {
            let Some(pixels) = covered(line_shape([-1, -20, 0], [1, 20, 0]), distance) else {
                return;
            };
            let rows = per_line(&pixels, |&(_, y)| y);
            assert!(rows.len() >= 8, "{distance} m: {pixels:?}");
            assert!(
                rows.iter().all(|&n| n == 1),
                "{distance} m: one pixel in every row the line crosses, got {rows:?}"
            );
        }
    });
}
