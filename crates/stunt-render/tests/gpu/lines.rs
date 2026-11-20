//! Verifies that SOD lines (`MOVETO`/`ZLINETO`) draw one Mode 13h pixel wide at any distance,
//! decoded from synthetic shapes and read from `RenderedPage`.
//!
//! Skips when no GPU adapter is available (see common); fails instead of skipping under
//! `STUNT_REQUIRE_GPU=1` (ADR 0006).

use crate::common;

use stunt_core::contracts::{
    CameraTransform, DecodeMode, NodeKind, SodModelIr, SodVertex, VisibilityCondition,
};
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

/// A shape of one flat triangle 40 m across in the z = 0 plane, wound clockwise as seen from
/// +z (front-facing toward the test camera) when `front`, else anticlockwise.
fn triangle_shape(front: bool) -> SodModelIr {
    let corners = [[0.0, 20.0, 0.0], [20.0, -20.0, 0.0], [-20.0, -20.0, 0.0]];
    triangle(corners, if front { [0, 1, 2] } else { [0, 2, 1] })
}

/// A shape of one triangle with `corners`, wound in the order `indices`.
fn triangle(corners: [[f32; 3]; 3], indices: [u32; 3]) -> SodModelIr {
    let vertex = |position: [f32; 3]| SodVertex {
        position,
        normal: [0.0, 0.0, 1.0],
        palette_index: LINE_INDEX,
        flags: 0,
        scenery_class: 0,
        _padding: 0,
    };
    let mut ir = SodModelIr::new("TRI");
    ir.vertices = corners.map(vertex).to_vec();
    ir.indices = indices.to_vec();
    let id = ir.allocate_node(
        "BASE",
        None,
        [
            1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0,
        ],
        VisibilityCondition::Always,
        NodeKind::Mesh {
            vertex_offset: 0,
            vertex_count: 3,
            index_offset: 0,
            index_count: 3,
            is_decal: false,
        },
    );
    if ir.root_nodes.is_empty() {
        ir.root_nodes = vec![id];
    }
    ir
}

/// A back-facing polygon's outline is culled with the polygon, as `PLAYONE` culls it, while a
/// front-facing one's is drawn (#686), however far away.
#[test]
fn only_a_front_facing_polygon_draws_its_outline() {
    common::gpu_test(|| {
        for distance in [200.0, 5000.0] {
            let Some(front) = covered(triangle_shape(true), distance) else {
                return;
            };
            assert!(
                !front.is_empty(),
                "{distance} m: the front-facing triangle draws"
            );
            let Some(back) = covered(triangle_shape(false), distance) else {
                return;
            };
            assert!(
                back.is_empty(),
                "{distance} m: the back-facing triangle and its outline draw nothing, got {back:?}"
            );
        }
    });
}

/// A triangle seen edge-on, its plane through the eye, draws its outline as one unbroken line
/// whichever way it winds: its screen winding is rounding noise, so it is not culled (#717).
/// Without the exemption its corners disagree on the cull, breaking the line into dashes and
/// dragging slivers to the screen centre.
#[test]
fn an_edge_on_polygon_draws_its_outline_unbroken() {
    common::gpu_test(|| {
        let distance = 200.0;
        for height in [-30.0_f32, -7.0, 11.0, 23.0] {
            // Two corners 40 m (50 columns) apart across the view, and the third halfway to
            // the eye on the ray through their midpoint: the plane holds the eye.
            let corners = [
                [-20.0, height, 0.0],
                [20.0, height, 0.0],
                [0.0, height / 2.0, distance / 2.0],
            ];
            for indices in [[0, 1, 2], [0, 2, 1]] {
                let Some(pixels) = covered(triangle(corners, indices), distance) else {
                    return;
                };
                assert!(
                    !pixels.is_empty(),
                    "{height} m, {indices:?}: the outline draws"
                );
                let rows = pixels.iter().map(|p| p.1);
                let (top, bottom) = (rows.clone().min().unwrap(), rows.max().unwrap());
                assert!(
                    bottom - top <= 1,
                    "{height} m, {indices:?}: the outline stays on its row, got rows {top}..={bottom}"
                );
                let columns = per_line(&pixels, |p| p.0);
                assert!(
                    columns.len() >= 48 && columns.iter().all(|&n| n >= 1),
                    "{height} m, {indices:?}: the outline is unbroken, got {columns:?}"
                );
            }
        }
    });
}
