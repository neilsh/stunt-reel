//! Verifies the scene renderer through the Renderer entry point: per-draw matrices,
//! state-mask visibility, and the world draw, all read from RenderedPage.
//!
//! Skips when no GPU adapter is available, like the other render tests (see common); fails
//! instead of skipping under STUNT_REQUIRE_GPU=1 (ADR 0006).

mod common;

use std::collections::HashMap;

use stunt_core::contracts::palette::PaletteControls;
use stunt_core::contracts::{
    ActorTransform, CameraTransform, NodeKind, ShapeExtent, SodModelIr, SodVertex,
    TrajectoryRecord, VisibilityCondition,
};
use stunt_core::flm::{FilmTimeline, SliceKeyframe};
use stunt_core::scene::FilmScene;
use stunt_core::world::World;
use stunt_render::{LAYER_NONE, Offscreen, RenderOptions};

const SHAPE_ID: u16 = 7;
const CLEAR_INDEX: u8 = 180;

/// A 2 m wide triangle in the XY plane, visible only where visibility allows.
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

fn actor_at(x: f32, state_mask: u16) -> ActorTransform {
    ActorTransform {
        actor_id: 0,
        model_name: "TRI".to_string(),
        shape_id: SHAPE_ID,
        rotation_quat: [0.0, 0.0, 0.0, 1.0],
        position_meters: [x, 0.0, 0.0],
        state_mask,
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
