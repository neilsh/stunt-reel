//! Pins the viewer-only diagnostic look beside the parity look: it changes no index, layer or
//! shape word of the page, only its colour; colours an object by its shape word, so two shapes
//! differ and one shape keeps its colour; stripes a decal; draws a shadow dark; lays a world
//! grid over flat terrain; and paints the sky one flat colour.
//!
//! Skips when no GPU adapter is available (see common); fails instead of skipping under
//! `STUNT_REQUIRE_GPU=1` (ADR 0006).

#![expect(
    clippy::indexing_slicing,
    reason = "test helpers outside #[test]: an out-of-range index is the assertion failure"
)]

use crate::common;
use crate::draw_order::{film_looking_at, push_mesh, vertex};
use crate::scene_renderer::world_of;

use std::collections::HashMap;

use stunt_core::contracts::{
    ActorTransform, NodeKind, SCENERY_PROP, SCENERY_TERRAIN, SodModelIr, SodVertex,
    VisibilityCondition,
};
use stunt_core::scene::FilmScene;
use stunt_core::world::{GROUND_NODE, PropRun};
use stunt_render::{
    LAYER_FIRST_ACTOR, LAYER_NONE, LAYER_PROP, LAYER_TERRAIN, Look, Offscreen, RenderOptions,
    RenderedPage,
};

/// The flat colour of the diagnostic sky (`DIAG_SKY` in `mode13h.wgsl`).
const SKY: [u8; 3] = [16, 16, 24];

fn shoot(scene: &FilmScene, look: Look) -> Option<RenderedPage> {
    let mut test = common::gpu_or_skip_offscreen(
        scene,
        Offscreen::default(),
        RenderOptions {
            look,
            ..RenderOptions::default()
        },
    )?;
    Some(test.draw(&scene.frame(0.0)))
}

/// The diagnostic page of `scene`, after checking that its index, layer and shape planes are the
/// parity look's.
fn diagnostic(scene: &FilmScene) -> Option<RenderedPage> {
    let parity = shoot(scene, Look::Mode13h)?;
    let page = shoot(scene, Look::Diagnostic)?;
    assert_ne!(parity.rgba(), page.rgba(), "the looks draw differently");
    assert_eq!(parity.indices(), page.indices(), "index planes differ");
    assert_eq!(parity.layers(), page.layers(), "layer planes differ");
    assert_eq!(parity.shapes(), page.shapes(), "shape planes differ");
    Some(page)
}

fn colour(page: &RenderedPage, n: usize) -> [u8; 3] {
    page.rgba()[n * 4..n * 4 + 3].try_into().unwrap()
}

fn luma(rgb: [f32; 3]) -> f32 {
    0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]
}

/// The luma of the pixel `n` of `page`.
fn luma_at(page: &RenderedPage, n: usize) -> f32 {
    luma(colour(page, n).map(f32::from))
}

/// `diagnostic_hue` of `mode13h.wgsl`, in 8-bit channels.
fn hue(k: u32) -> [f32; 3] {
    let h = (k as f32 * 0.618_034).fract();
    [1.0, 2.0 / 3.0, 1.0 / 3.0].map(|offset: f32| {
        let c = (((h + offset).fract() * 6.0 - 3.0).abs() - 1.0).clamp(0.0, 1.0);
        255.0 * (1.0 - 0.6 * (1.0 - c))
    })
}

/// A world of square facets facing a camera at `+z`, each of half-width 1 at `x`, in one mesh;
/// `runs` give the shape word of the first `n` quads.
fn facets(centres: &[f32], decal: bool, words: &[u16]) -> FilmScene {
    let mut ir = SodModelIr::new("WORLD_SCENERY");
    let mut indices = Vec::new();
    for (n, &x) in centres.iter().enumerate() {
        let at = |dx: f32, dy: f32| SodVertex {
            decal_tie: u8::from(decal),
            ..vertex([x + dx, dy, 0.0], [0.0, 0.0, 1.0], 40, SCENERY_PROP)
        };
        ir.vertices
            .extend([at(-1.0, -1.0), at(-1.0, 1.0), at(1.0, 1.0), at(1.0, -1.0)]);
        let b = u32::try_from(4 * n).unwrap();
        indices.extend([b, b + 1, b + 2, b, b + 2, b + 3]);
    }
    push_mesh(&mut ir, "WORLD_PROP", 4 * centres.len(), &indices, decal);
    let mut world = world_of(ir);
    world.prop_runs = words
        .iter()
        .enumerate()
        .map(|(n, &shape)| PropRun {
            first: u32::try_from(4 * n).unwrap(),
            end: u32::try_from(4 * n + 4).unwrap(),
            // The run holds the shape id; the plane's word is one more.
            shape: shape - 1,
        })
        .collect();
    let film = film_looking_at([0.0, 0.0, 10.0], [0.0, 0.0, 0.0], Vec::new(), 0x002D);
    FilmScene::new(film, HashMap::new(), Some(world))
}

/// The pixels of `page` whose shape word is `word` on the prop layer.
fn shape_pixels(page: &RenderedPage, word: u16) -> Vec<usize> {
    (0..page.layers().len())
        .filter(|&n| page.layers()[n] == LAYER_PROP && page.shapes()[n] == u32::from(word))
        .collect()
}

/// The colour `rgb` over `hue(word)`: its brightness factor, or `None` if the colour is not
/// that hue at one brightness (within 4 levels).
fn facing(rgb: [u8; 3], word: u16) -> Option<f32> {
    let key = hue(u32::from(word));
    let widest = (0..3).max_by(|&a, &b| key[a].total_cmp(&key[b]))?;
    let factor = f32::from(rgb[widest]) / key[widest];
    let fits = (0..3).all(|c| (f32::from(rgb[c]) - key[c] * factor).abs() <= 4.0);
    (fits && (0.5..=1.02).contains(&factor)).then_some(factor)
}

#[test]
fn two_shapes_differ_in_colour_and_one_shape_keeps_its_colour() {
    common::gpu_test(|| {
        let scene = facets(&[-3.0, 0.0, 3.0], false, &[40, 41, 40]);
        let Some(page) = diagnostic(&scene) else {
            return;
        };
        let mean = |word: u16, left: bool| {
            let w = page.width() as usize;
            let pixels: Vec<usize> = shape_pixels(&page, word)
                .into_iter()
                .filter(|&n| (n % w < w / 2) == left)
                .collect();
            assert!(
                pixels.len() > 100,
                "word {word} drew {} pixels",
                pixels.len()
            );
            let sum = pixels.iter().fold([0u32; 3], |mut sum, &n| {
                let rgb = colour(&page, n);
                (0..3).for_each(|c| sum[c] += u32::from(rgb[c]));
                sum
            });
            sum.map(|s| u8::try_from(s / u32::try_from(pixels.len()).unwrap()).unwrap())
        };
        let (left, middle, right) = (mean(40, true), mean(41, true), mean(40, false));
        for (rgb, word) in [(left, 40), (middle, 41), (right, 40)] {
            assert!(
                facing(rgb, word).is_some(),
                "{rgb:?} is not shape {word}'s hue"
            );
        }
        let apart: i32 = (0..3)
            .map(|c| (i32::from(left[c]) - i32::from(middle[c])).abs())
            .sum();
        assert!(
            apart > 60,
            "shapes 40 and 41 are {apart} apart: {left:?} {middle:?}"
        );
        assert!(
            (0..3).all(|c| left[c].abs_diff(right[c]) <= 12),
            "one shape, two colours: {left:?} {right:?}"
        );
    });
}

#[test]
fn a_decal_facet_shows_stripes_and_a_plain_one_does_not() {
    common::gpu_test(|| {
        let spread = |decal: bool| {
            let scene = facets(&[0.0], decal, &[41]);
            let page = diagnostic(&scene)?;
            let lumas: Vec<f32> = shape_pixels(&page, 41)
                .into_iter()
                .map(|n| luma_at(&page, n))
                .collect();
            assert!(lumas.len() > 100, "{} pixels", lumas.len());
            Some(lumas)
        };
        let (Some(plain), Some(decal)) = (spread(false), spread(true)) else {
            return;
        };
        // The fill's brightness: the median, past the darker outline pixels at the edge.
        let mut sorted = plain;
        sorted.sort_by(f32::total_cmp);
        let fill = sorted[sorted.len() / 2];
        assert!(
            sorted.iter().all(|&l| l <= fill * 1.08),
            "a plain facet shows stripes: fill {fill}, max {:?}",
            sorted.last()
        );
        let striped = decal.iter().filter(|&&l| l > fill * 1.08).count();
        let unstriped = decal
            .iter()
            .filter(|&&l| (l - fill).abs() <= fill * 0.03)
            .count();
        assert!(
            striped > 20 && unstriped > 20,
            "{striped} striped, {unstriped} plain of {}",
            decal.len()
        );
    });
}

/// A floor triangle at 3 m up that casts a shadow, seen from above.
fn shadow_scene() -> FilmScene {
    let at = |x: f32, z: f32| SodVertex {
        normal: [0.0, 1.0, 0.0],
        ..vertex([x, 0.0, z], [0.0, 1.0, 0.0], 45, 0)
    };
    let mut ir = SodModelIr::new("FLOOR");
    ir.vertices = vec![at(-1.0, 1.0), at(1.0, 1.0), at(0.0, -1.0)];
    push_mesh(&mut ir, "FLOOR", 3, &[0, 2, 1], false);
    let actor = ActorTransform {
        actor_id: 0,
        model_name: "FLOOR".to_string(),
        shape_id: 1,
        rotation_quat: [0.0, 0.0, 0.0, 1.0],
        position_meters: [0.0, 3.0, 0.0],
        state_mask: 0,
        casts_shadow: true,
        view: false,
        joint_angles_bam: Vec::new(),
    };
    let film = film_looking_at([0.0, 10.0, 10.0], [0.0, 0.0, 0.0], vec![actor], 0x002D);
    FilmScene::new(film, HashMap::from([(1, ir)]), None)
}

#[test]
fn a_shadow_is_dark_beside_its_actors_colour() {
    common::gpu_test(|| {
        let scene = shadow_scene();
        let (Some(parity), Some(page)) = (shoot(&scene, Look::Mode13h), diagnostic(&scene)) else {
            return;
        };
        let actor = hue(LAYER_FIRST_ACTOR);
        let full = luma(actor);
        // The parity look fills a shadow with palette index 0 on its actor's layer.
        let (mut shadow, mut body) = (Vec::new(), Vec::new());
        for n in 0..parity.layers().len() {
            if parity.layers()[n] == LAYER_FIRST_ACTOR {
                if parity.indices()[n] == 0 {
                    &mut shadow
                } else {
                    &mut body
                }
                .push(n);
            }
        }
        assert!(
            shadow.len() > 50 && body.len() > 50,
            "{} {}",
            shadow.len(),
            body.len()
        );
        let dark = shadow
            .iter()
            .filter(|&&n| luma_at(&page, n) < 0.3 * full)
            .count();
        assert!(
            dark * 2 > shadow.len(),
            "{dark} of {} shadow pixels are dark",
            shadow.len()
        );
        assert!(
            shadow.iter().all(|&n| luma_at(&page, n) < 0.5 * full),
            "a shadow pixel is lighter than its hatch"
        );
        assert!(
            body.iter().any(|&n| luma_at(&page, n) > 0.5 * full),
            "the actor itself is bright"
        );
    });
}

/// A 600 m wide, 2 km long terrain quad under a camera at `eye_x` 12 m up looking 80 m ahead.
fn terrain_scene(eye_x: f32) -> FilmScene {
    let mut ir = SodModelIr::new("WORLD_SCENERY");
    let root = ir.allocate_node(
        "WORLD_BASE",
        None,
        glam::Mat4::IDENTITY.to_cols_array(),
        VisibilityCondition::Always,
        NodeKind::TransformGroup,
    );
    ir.vertices = [
        [-300.0, -2000.0],
        [300.0, -2000.0],
        [300.0, -1.0],
        [-300.0, -1.0],
    ]
    .map(|[x, z]| vertex([x, 0.0, z], [0.0, 1.0, 0.0], 40, SCENERY_TERRAIN))
    .to_vec();
    ir.indices = vec![0, 1, 2, 0, 2, 3];
    ir.allocate_node(
        GROUND_NODE,
        Some(root),
        glam::Mat4::IDENTITY.to_cols_array(),
        VisibilityCondition::Always,
        NodeKind::Mesh {
            vertex_offset: 0,
            vertex_count: 4,
            index_offset: 0,
            index_count: 6,
            is_decal: false,
        },
    );
    ir.root_nodes = vec![root];
    let film = film_looking_at([eye_x, 12.0, 0.0], [eye_x, 0.0, -80.0], Vec::new(), 0x002D);
    FilmScene::new(film, HashMap::new(), Some(world_of(ir)))
}

#[test]
fn flat_terrain_shows_grid_lines_and_plain_ground() {
    common::gpu_test(|| {
        let scene = terrain_scene(0.0);
        let Some(page) = diagnostic(&scene) else {
            return;
        };
        let w = page.width() as usize;
        let ground: Vec<usize> = (0..page.layers().len())
            .filter(|&n| page.layers()[n] == LAYER_TERRAIN)
            .collect();
        assert!(ground.len() > 10_000, "{} terrain pixels", ground.len());
        // The grid tints toward blue; plain ground is grey (red equals blue).
        let gridded = |page: &RenderedPage, n: usize| {
            let rgb = colour(page, n);
            i32::from(rgb[2]) - i32::from(rgb[0]) > 8
        };
        let lines = ground.iter().filter(|&&n| gridded(&page, n)).count();
        let plain = ground
            .iter()
            .filter(|&&n| colour(&page, n)[2].abs_diff(colour(&page, n)[0]) <= 2)
            .count();
        assert!(lines > 100, "{lines} grid pixels of {}", ground.len());
        assert!(
            plain > ground.len() / 2,
            "{plain} plain pixels of {}",
            ground.len()
        );
        // The grid is in world coordinates: the bottom row, 0.09 m a pixel, crosses the x = 0 line
        // from an eye at x = 0 and no line from one at x = 50, whose view spans x 36 to 64.
        let bottom = |page: &RenderedPage| (0..w).filter(|&x| gridded(page, 239 * w + x)).count();
        assert!(
            (1..=4).contains(&bottom(&page)),
            "{} gridded pixels in the bottom row",
            bottom(&page)
        );
        let Some(shifted) = diagnostic(&terrain_scene(50.0)) else {
            return;
        };
        assert_eq!(bottom(&shifted), 0, "the grid ignored the eye");
    });
}

#[test]
fn the_sky_is_one_flat_colour() {
    common::gpu_test(|| {
        let scene = terrain_scene(0.0);
        let Some(page) = diagnostic(&scene) else {
            return;
        };
        let sky: Vec<usize> = (0..page.layers().len())
            .filter(|&n| page.layers()[n] == LAYER_NONE)
            .collect();
        assert!(sky.len() > 1_000, "{} sky pixels", sky.len());
        assert!(
            sky.iter().all(|&n| colour(&page, n) == SKY),
            "the sky is not flat {SKY:?}"
        );
    });
}
