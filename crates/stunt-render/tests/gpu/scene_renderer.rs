//! Verifies the scene renderer through the Renderer entry point: per-draw matrices,
//! state-mask visibility, and the world draw, all read from `RenderedPage`.
//!
//! Skips when no GPU adapter is available, like the other render tests (see common); fails
//! instead of skipping under `STUNT_REQUIRE_GPU=1` (ADR 0006).

use crate::common;

use std::collections::HashMap;

use stunt_core::contracts::palette::PaletteControls;
use stunt_core::contracts::{
    ActorTransform, CameraTransform, NodeKind, ShapeExtent, SodModelIr, SodVertex,
    TrajectoryRecord, VisibilityCondition,
};
use stunt_core::flm::{FilmTimeline, SliceKeyframe};
use stunt_core::scene::{FilmScene, ViewCamera};
use stunt_core::world::{TerrainSurface, World};
use stunt_render::{CameraController, LAYER_FIRST_ACTOR, LAYER_NONE, Offscreen, RenderOptions};

const SHAPE_ID: u16 = 7;
const CLEAR_INDEX: u8 = 180;

/// A 2 m wide triangle in the XY plane, visible only where visibility allows.
#[expect(
    clippy::indexing_slicing,
    reason = "test helper outside #[test]: an out-of-range index is the assertion failure"
)]
fn triangle(name: &str, visibility: VisibilityCondition) -> SodModelIr {
    let vertex = |x: f32, y: f32| SodVertex {
        position: [x, y, 0.0],
        normal: [0.0, 0.0, 1.0],
        palette_index: 40,
        flags: 4,
        scenery_class: 0,
        _padding: 0,
    };
    let mut ir = SodModelIr::new(name);
    ir.vertices = vec![vertex(-1.0, -1.0), vertex(1.0, -1.0), vertex(0.0, 1.0)];
    // Clockwise, like the SOD models: the pipeline culls back faces with FrontFace::Cw.
    ir.indices = vec![0, 2, 1];
    ir.allocate_node(
        "TRI",
        None,
        glam::Mat4::IDENTITY.to_cols_array(),
        visibility,
        NodeKind::Mesh {
            vertex_offset: 0,
            vertex_count: 3,
            index_offset: 0,
            index_count: 3,
            is_decal: false,
        },
    );
    ir.root_nodes = vec![ir.nodes[0].id];
    ir
}

/// An unrotated actor of the test shape at `x` on the X axis, casting no shadow.
fn actor_at(x: f32, state_mask: u16) -> ActorTransform {
    ActorTransform {
        actor_id: 0,
        model_name: "TRI".to_string(),
        shape_id: SHAPE_ID,
        rotation_quat: [0.0, 0.0, 0.0, 1.0],
        position_meters: [x, 0.0, 0.0],
        state_mask,
        casts_shadow: false,
        joint_angles_bam: Vec::new(),
    }
}

fn timeline(actors: Vec<ActorTransform>) -> FilmTimeline {
    timeline_with_palette(actors, PaletteControls::default())
}

fn timeline_with_palette(actors: Vec<ActorTransform>, palette: PaletteControls) -> FilmTimeline {
    let record = TrajectoryRecord {
        tick: 0,
        camera: CameraTransform {
            eye: [0.0, 0.0, 8.0],
            target: [0.0, 0.0, 0.0],
            fov_degrees: 45.0,
            roll_radians: 0.0,
            cut_from_previous: false,
            ..Default::default()
        },
        actors,
        audio_cues: Vec::new(),
        palette,
    };
    FilmTimeline::new(
        vec![SliceKeyframe {
            record,
            tick: 0,
            tick_duration: 1,
        }],
        Vec::new(),
    )
}

fn scene(actors: Vec<ActorTransform>, visibility: VisibilityCondition) -> FilmScene {
    let shapes = HashMap::from([(SHAPE_ID, triangle("TRI", visibility))]);
    FilmScene::new(timeline(actors), shapes, None)
}

/// Renders tick 0 and returns (width, height, per-pixel "covered by geometry" flags).
fn render(scene: &FilmScene) -> Option<(usize, usize, Vec<bool>)> {
    let mut test = common::gpu_or_skip(scene)?;
    let page = test.draw(&scene.frame(0.0));
    let (w, h) = (page.width() as usize, page.height() as usize);
    // The sky paints every uncovered pixel, so geometry is told apart by its layer.
    let drawn = page
        .layers()
        .iter()
        .map(|&layer| layer != LAYER_NONE)
        .collect();
    Some((w, h, drawn))
}

#[expect(
    clippy::indexing_slicing,
    reason = "test helper outside #[test]: an out-of-range index is the assertion failure"
)]
fn drawn_in_columns(drawn: &[bool], w: usize, h: usize, cols: std::ops::Range<usize>) -> usize {
    (0..h)
        .flat_map(|y| cols.clone().map(move |x| (x, y)))
        .filter(|&(x, y)| drawn[y * w + x])
        .count()
}

#[test]
fn two_actors_sharing_a_shape_both_render_at_their_own_matrix() {
    let scene = scene(
        vec![actor_at(-2.5, 0), actor_at(2.5, 0)],
        VisibilityCondition::Always,
    );
    let Some((w, h, drawn)) = render(&scene) else {
        return;
    };
    let left = drawn_in_columns(&drawn, w, h, 0..w * 2 / 5);
    let middle = drawn_in_columns(&drawn, w, h, w * 2 / 5..w * 3 / 5);
    let right = drawn_in_columns(&drawn, w, h, w * 3 / 5..w);
    assert!(left > 100, "left actor missing: {left}");
    assert!(right > 100, "right actor missing: {right}");
    assert_eq!(middle, 0, "nothing should be drawn between the actors");
    // Same shape, mirrored placement: equal coverage.
    assert!(left.abs_diff(right) <= left / 20 + 4, "{left} vs {right}");
}

/// A `FacesEye` gate draws its mesh with the normal toward the eye and hides it when reversed.
#[test]
fn facing_gate_draws_only_while_its_face_points_at_the_eye() {
    // The eye is at +Z 8 m and the actor at the origin, so a +Z normal faces it.
    let gate = |z: f32| VisibilityCondition::FacesEye {
        point: [0.0, 0.0, 0.0],
        normal: [0.0, 0.0, z],
    };
    let Some((w, h, toward)) = render(&scene(vec![actor_at(0.0, 0)], gate(1.0))) else {
        return;
    };
    assert!(drawn_in_columns(&toward, w, h, 0..w) > 100);
    let Some((w, h, away)) = render(&scene(vec![actor_at(0.0, 0)], gate(-1.0))) else {
        return;
    };
    assert_eq!(drawn_in_columns(&away, w, h, 0..w), 0);
}

/// A camera override tests facing gates against its own eye, not the film's.
#[test]
fn facing_gate_follows_the_override_cameras_eye() {
    // The gate's plane is at z = 4: the film eye (z = 8) is in front of it, an override eye
    // at z = 2 behind it, while both still see the triangle's front face.
    let gate = VisibilityCondition::FacesEye {
        point: [0.0, 0.0, 4.0],
        normal: [0.0, 0.0, 1.0],
    };
    let scene = scene(vec![actor_at(0.0, 0)], gate);
    let Some(mut test) = common::gpu_or_skip(&scene) else {
        return;
    };
    let frame = scene.frame(0.0);
    let drawn = |page: &stunt_render::RenderedPage| {
        page.layers()
            .iter()
            .filter(|&&layer| layer != LAYER_NONE)
            .count()
    };
    assert!(
        drawn(&test.draw(&frame)) > 100,
        "the film eye opens the gate"
    );
    let mut camera = CameraController::default();
    camera.set_authored_transform(ViewCamera {
        eye: [0.0, 0.0, 2.0],
        target: [0.0, 0.0, 0.0],
        fov_degrees: 45.0,
        roll_radians: 0.0,
    });
    assert_eq!(
        drawn(&test.draw_with(&frame, Some(&camera))),
        0,
        "the override eye closes it"
    );
}

#[test]
fn state_mask_that_hides_geometry_draws_nothing() {
    let gated = VisibilityCondition::ActorState {
        mask: 1,
        expected: 1,
    };
    let hidden = scene(vec![actor_at(0.0, 0)], gated);
    let Some((w, h, drawn)) = render(&hidden) else {
        return;
    };
    assert_eq!(drawn_in_columns(&drawn, w, h, 0..w), 0);

    let shown = scene(vec![actor_at(0.0, 1)], gated);
    let (w, h, drawn) = render(&shown).expect("adapter was available");
    assert!(drawn_in_columns(&drawn, w, h, 0..w) > 100);
}

/// A `SIF_SHADOW` actor 3 m up draws its shape again on `y = 0` in palette index 0, with its
/// own layer, whichever way its face is wound; an actor without the flag draws no shadow.
#[test]
fn a_shadow_casting_actor_draws_its_flattened_shape_in_index_0() {
    // A 2 m floor triangle in the XZ plane, in both windings: one faces up, one down.
    let floor = |indices: Vec<u32>| {
        let mut ir = triangle("FLOOR", VisibilityCondition::Always);
        for (vertex, [x, z]) in ir
            .vertices
            .iter_mut()
            .zip([[-1.0, 1.0], [1.0, 1.0], [0.0, -1.0]])
        {
            vertex.position = [x, 0.0, z];
            vertex.normal = [0.0, 1.0, 0.0];
        }
        ir.indices = indices;
        ir
    };
    let shadow_pixels = |indices: Vec<u32>, casts_shadow: bool| {
        let actor = ActorTransform {
            position_meters: [0.0, 3.0, 0.0],
            casts_shadow,
            ..actor_at(0.0, 0)
        };
        // Looking down at 45 degrees, so the actor and its shadow land on different rows.
        let record = TrajectoryRecord {
            tick: 0,
            camera: CameraTransform {
                eye: [0.0, 10.0, 10.0],
                target: [0.0, 0.0, 0.0],
                fov_degrees: 45.0,
                ..Default::default()
            },
            actors: vec![actor],
            audio_cues: Vec::new(),
            palette: PaletteControls::default(),
        };
        let timeline = FilmTimeline::new(
            vec![SliceKeyframe {
                record,
                tick: 0,
                tick_duration: 1,
            }],
            Vec::new(),
        );
        let shapes = HashMap::from([(SHAPE_ID, floor(indices))]);
        let scene = FilmScene::new(timeline, shapes, None);
        let mut test = common::gpu_or_skip(&scene)?;
        let page = test.draw(&scene.frame(0.0));
        Some(
            page.indices()
                .iter()
                .zip(page.layers())
                .filter(|&(&index, &layer)| index == 0 && layer == LAYER_FIRST_ACTOR)
                .count(),
        )
    };
    for indices in [vec![0, 1, 2], vec![0, 2, 1]] {
        let Some(shadow) = shadow_pixels(indices.clone(), true) else {
            return;
        };
        assert!(shadow > 100, "winding {indices:?}: shadow {shadow}");
        assert_eq!(shadow_pixels(indices, false), Some(0));
    }
}

/// A scene with a world draws it even with no actors.
#[test]
fn world_is_drawn_when_present() {
    let mut ir = triangle("WORLD_BASE", VisibilityCondition::Always);
    // World vertices carry their scenery class; the layer plane reads it.
    for vertex in &mut ir.vertices {
        vertex.scenery_class = stunt_core::contracts::SCENERY_TERRAIN;
    }
    let world = World {
        ir,
        terrain_patches: 0,
        props_placed: 0,
        bounds: ShapeExtent {
            min: [-1.0, -1.0, 0.0],
            max: [1.0, 1.0, 0.0],
            radius: 1.0,
        },
        scenery_stop: None,
        terrain: TerrainSurface::default(),
    };
    let scene = FilmScene::new(timeline(Vec::new()), HashMap::new(), Some(world));
    let Some((w, h, drawn)) = render(&scene) else {
        return;
    };
    assert!(drawn_in_columns(&drawn, w, h, w / 3..w * 2 / 3) > 100);
}

#[test]
fn zero_brightness_frame_renders_black_including_the_clear_colour() {
    let faded = PaletteControls {
        brightness: 0,
        ..PaletteControls::default()
    };
    let shapes = HashMap::from([(SHAPE_ID, triangle("TRI", VisibilityCondition::Always))]);
    let scene = FilmScene::new(
        timeline_with_palette(vec![actor_at(0.0, 0)], faded),
        shapes,
        None,
    );
    let frame = scene.frame(0.0);
    assert_eq!(frame.palette, faded);
    let Some(mut test) = common::gpu_or_skip_offscreen(
        &scene,
        Offscreen::default(),
        RenderOptions {
            clear_palette_index: CLEAR_INDEX,
            ..RenderOptions::default()
        },
    ) else {
        return;
    };
    let page = test.draw(&frame);
    assert!(
        page.rgba()
            .as_chunks::<4>()
            .0
            .iter()
            .all(|p| p[..3] == [0, 0, 0])
    );
}

/// A 1 km square on the ground plane at palette index `index`, wound both ways so no
/// face is culled.
#[expect(
    clippy::indexing_slicing,
    reason = "test helper outside #[test]: an out-of-range index is the assertion failure"
)]
fn ground_square(index: u8) -> SodModelIr {
    let vertex = |x: f32, z: f32| SodVertex {
        position: [x, 0.0, z],
        normal: [0.0, 1.0, 0.0],
        palette_index: index,
        flags: 4,
        scenery_class: 0,
        _padding: 0,
    };
    let mut ir = SodModelIr::new("GROUND");
    ir.vertices = vec![
        vertex(-500.0, -500.0),
        vertex(500.0, -500.0),
        vertex(500.0, 500.0),
        vertex(-500.0, 500.0),
    ];
    ir.indices = vec![0, 1, 2, 0, 2, 3, 0, 2, 1, 0, 3, 2];
    ir.allocate_node(
        "GROUND",
        None,
        glam::Mat4::IDENTITY.to_cols_array(),
        VisibilityCondition::Always,
        NodeKind::Mesh {
            vertex_offset: 0,
            vertex_count: 4,
            index_offset: 0,
            index_count: 12,
            is_decal: false,
        },
    );
    ir.root_nodes = vec![ir.nodes[0].id];
    ir
}

/// A ground polygon that reaches behind a low eye and past the side planes keeps its own
/// index on every pixel. Mesa's software clipper (lavapipe, CI's adapter) can interpolate
/// the `linear` shade varying of such a polygon to NaN, which used to draw index 0
/// (`research/parity/method.md` section 3).
#[test]
fn a_ground_polygon_under_a_low_eye_keeps_its_index() {
    const GROUND_INDEX: u8 = 40;
    let record = TrajectoryRecord {
        tick: 0,
        camera: CameraTransform {
            eye: [0.0, 3.0, 0.0],
            target: [0.0, 0.0, -20.0],
            fov_degrees: 45.0,
            roll_radians: 0.0,
            cut_from_previous: false,
            ..Default::default()
        },
        actors: vec![actor_at(0.0, 0)],
        audio_cues: Vec::new(),
        palette: PaletteControls::default(),
    };
    let timeline = FilmTimeline::new(
        vec![SliceKeyframe {
            record,
            tick: 0,
            tick_duration: 1,
        }],
        Vec::new(),
    );
    let shapes = HashMap::from([(SHAPE_ID, ground_square(GROUND_INDEX))]);
    let scene = FilmScene::new(timeline, shapes, None);
    let Some(mut test) = common::gpu_or_skip_software(&scene) else {
        return;
    };
    let page = test.draw(&scene.frame(0.0));
    let ground: Vec<u8> = page
        .layers()
        .iter()
        .zip(page.indices())
        .filter(|&(&layer, _)| layer == LAYER_FIRST_ACTOR)
        .map(|(_, &index)| index)
        .collect();
    assert!(
        ground.len() > 10_000,
        "ground covers {} pixels",
        ground.len()
    );
    let wrong = ground
        .iter()
        .filter(|&&index| index != GROUND_INDEX)
        .count();
    assert_eq!(
        wrong,
        0,
        "{wrong} of {} ground pixels lost their index",
        ground.len()
    );
}
