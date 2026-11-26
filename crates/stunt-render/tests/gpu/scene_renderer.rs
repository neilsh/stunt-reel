//! Verifies the scene renderer through the Renderer entry point: per-draw matrices,
//! state-mask visibility, and the world draw, all read from `RenderedPage`.
//!
//! Skips when no GPU adapter is available, like the other render tests (see common); fails
//! instead of skipping under `STUNT_REQUIRE_GPU=1` (ADR 0006).

use crate::common;

use std::collections::HashMap;
use std::time::Duration;

use stunt_core::contracts::palette::PaletteControls;
use stunt_core::contracts::{
    ActorTransform, CameraTransform, NodeKind, SCENERY_PROP, SCENERY_TERRAIN, ShapeExtent,
    SodModelIr, SodVertex, TrajectoryRecord, VERTEX_FLAG_LINE, VERTEX_FLAG_LINE_END,
    VERTEX_FLAG_LINE_SIDE, VisibilityCondition,
};
use stunt_core::flm::{FilmTimeline, SliceKeyframe};
use stunt_core::scene::{FilmScene, ViewCamera};
use stunt_core::world::{
    FacingProp, GROUND_NODE, GateNode, PlacementRecords, PropRun, TerrainSurface, World,
};
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
        decal_tie: 0,
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
        view: false,
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
        bank: Default::default(),
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
    common::gpu_test(|| {
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
    });
}

/// A `FacesEye` gate draws its mesh with the normal toward the eye and hides it when reversed.
#[test]
fn facing_gate_draws_only_while_its_face_points_at_the_eye() {
    common::gpu_test(|| {
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
    });
}

/// A camera override tests facing gates against its own eye, not the film's.
#[test]
fn facing_gate_follows_the_override_cameras_eye() {
    common::gpu_test(|| {
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
    });
}

#[test]
fn state_mask_that_hides_geometry_draws_nothing() {
    common::gpu_test(|| {
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
    });
}

/// A `SIF_SHADOW` actor 3 m up draws its shape again on `y = 0` in palette index 0, with its
/// own layer, outline included, whichever way its face is wound; an actor without the flag
/// draws no shadow, and the view slot draws the same shadow without its shape.
#[test]
fn a_shadow_casting_actor_draws_its_flattened_shape_in_index_0() {
    common::gpu_test(|| {
        // A 2 m floor triangle in the XZ plane, in both windings: one faces up, one down.
        let floor = |indices: Vec<u32>| {
            let mut ir = triangle("FLOOR", VisibilityCondition::Always);
            for (vertex, [x, z]) in
                ir.vertices
                    .iter_mut()
                    .zip([[-1.0, 1.0], [1.0, 1.0], [0.0, -1.0]])
            {
                vertex.position = [x, 0.0, z];
                vertex.normal = [0.0, 1.0, 0.0];
            }
            ir.indices = indices;
            ir
        };
        // The actor's layer's pixels in index 0 (its shadow) and in any other index.
        let pixels_from =
            |eye: [f32; 3], target: [f32; 3], indices: Vec<u32>, casts_shadow: bool, view: bool| {
                let actor = ActorTransform {
                    position_meters: [0.0, 3.0, 0.0],
                    casts_shadow,
                    view,
                    ..actor_at(0.0, 0)
                };
                // Looking down at 45 degrees, so the actor and its shadow land on different rows.
                let record = TrajectoryRecord {
                    tick: 0,
                    camera: CameraTransform {
                        eye,
                        target,
                        fov_degrees: 45.0,
                        ..Default::default()
                    },
                    actors: vec![actor],
                    audio_cues: Vec::new(),
                    palette: PaletteControls::default(),
                    bank: Default::default(),
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
                let mut counts = (0, 0);
                for (&index, &layer) in page.indices().iter().zip(page.layers()) {
                    if layer != LAYER_FIRST_ACTOR {
                        continue;
                    }
                    if index == 0 {
                        counts.0 += 1;
                    } else {
                        counts.1 += 1;
                    }
                }
                Some(counts)
            };
        let pixels = |indices: Vec<u32>, casts_shadow: bool, view: bool| {
            pixels_from(
                [0.0, 10.0, 10.0],
                [0.0, 0.0, 0.0],
                indices,
                casts_shadow,
                view,
            )
        };
        // The view slot is the camera: the eye sits at the actor, inside its model, looking
        // steeply down so that the ground point straight below stays in view. Its distance is
        // about 0, so the shape's LOD and view gates run there; the shadow still shows.
        let eye = [0.0, 3.0, 0.0];
        for indices in [vec![0, 1, 2], vec![0, 2, 1]] {
            let Some((shadow, body)) =
                pixels_from(eye, [0.0, 0.0, -0.5], indices.clone(), true, true)
            else {
                return;
            };
            assert!(
                shadow > 100 && body == 0,
                "eye at slot {indices:?}: {shadow} {body}"
            );
        }
        let mut shadows = Vec::new();
        for indices in [vec![0, 1, 2], vec![0, 2, 1]] {
            let Some((shadow, _)) = pixels(indices.clone(), true, false) else {
                return;
            };
            assert!(shadow > 100, "winding {indices:?}: shadow {shadow}");
            shadows.push(shadow);
            assert_eq!(pixels(indices.clone(), false, false).map(|p| p.0), Some(0));
            // With no body over it, the view slot's shadow shows at least as many pixels.
            let (view_shadow, view_body) = pixels(indices, true, true).expect("adapter");
            assert!(
                view_shadow >= shadow && view_body == 0,
                "{view_shadow} {view_body}"
            );
        }
        // The shadow pipeline culls no face, so neither winding's outline is culled (#717).
        assert_eq!(
            shadows[0], shadows[1],
            "both windings' shadows, outlines included"
        );
    });
}

/// An `OP_PERFDISK` disc draws on the actor's body and is skipped in its ground shadow,
/// while non-disc triangles on the same shape still cast their shadow
/// (`0xA045`, `research/playone-exe/sod-vm-generators.md` section 8.8).
#[test]
fn a_shadow_casting_actor_skips_its_perfdisk_discs_in_the_shadow() {
    use stunt_core::sod::{
        DecodeMode, OP_COLOR, OP_ID, OP_PERFDISK, OP_RETURN, OP_VECTORS, decode_sod,
    };

    common::gpu_test(|| {
        // Horizontal 2 m disc at y = 0 in palette index 45, scale 1.0 (centre reg 1, axis reg 2).
        let words = [
            OP_ID,
            100,
            0,
            0,
            0,
            OP_VECTORS,
            2,
            12,
            0,
            0,
            0,
            0,
            10,
            0,
            OP_COLOR,
            45,
            OP_PERFDISK,
            12,
            2,
            24,
            OP_RETURN,
        ];
        let bytes: Vec<u8> = words.iter().flat_map(|w| w.to_le_bytes()).collect();
        let disc = decode_sod(&bytes, "DISC", None, DecodeMode::Strict).expect("decode disc");
        let mut floor = triangle("FLOOR", VisibilityCondition::Always);
        for (vertex, [x, z]) in
            floor
                .vertices
                .iter_mut()
                .zip([[-1.0, 1.0], [1.0, 1.0], [0.0, -1.0]])
        {
            vertex.position = [x, 0.0, z];
            vertex.normal = [0.0, 1.0, 0.0];
        }
        // Combined shape: the floor triangle at y = 0 plus the disc lifted slightly above y = 0
        // so both draw on the body while only the floor casts a shadow.
        let mut combined = floor.clone();
        let base_verts = u32::try_from(combined.vertices.len()).expect("small vertex count");
        let base_indices = u32::try_from(combined.indices.len()).expect("small index count");
        combined
            .vertices
            .extend(disc.vertices.iter().map(|v| SodVertex {
                position: [v.position[0], v.position[1] + 0.2, v.position[2]],
                ..*v
            }));
        combined
            .indices
            .extend(disc.indices.iter().map(|&i| i + base_verts));
        combined.allocate_node(
            "DISC",
            None,
            glam::Mat4::IDENTITY.to_cols_array(),
            VisibilityCondition::Always,
            NodeKind::Mesh {
                vertex_offset: base_verts,
                vertex_count: u32::try_from(disc.vertices.len()).expect("small vertex count"),
                index_offset: base_indices,
                index_count: u32::try_from(disc.indices.len()).expect("small index count"),
                is_decal: false,
            },
        );
        let disc_node = combined.nodes.last().expect("disc node").id;
        combined.root_nodes.push(disc_node);

        let counts_for = |shape: SodModelIr| {
            let actor = ActorTransform {
                position_meters: [0.0, 3.0, 0.0],
                casts_shadow: true,
                ..actor_at(0.0, 0)
            };
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
                bank: Default::default(),
            };
            let timeline = FilmTimeline::new(
                vec![SliceKeyframe {
                    record,
                    tick: 0,
                    tick_duration: 1,
                }],
                Vec::new(),
            );
            let shapes = HashMap::from([(SHAPE_ID, shape)]);
            let scene = FilmScene::new(timeline, shapes, None);
            let mut test = common::gpu_or_skip(&scene)?;
            let page = test.draw(&scene.frame(0.0));
            let (mut shadow, mut body, mut disc_body) = (0usize, 0usize, 0usize);
            for (&index, &layer) in page.indices().iter().zip(page.layers()) {
                if layer != LAYER_FIRST_ACTOR {
                    continue;
                }
                if index == 0 {
                    shadow += 1;
                } else {
                    body += 1;
                    if index == 45 {
                        disc_body += 1;
                    }
                }
            }
            Some((shadow, body, disc_body))
        };

        let Some((disc_shadow, disc_only_body, _)) = counts_for(disc) else {
            return;
        };
        assert!(disc_only_body > 100, "disc draws on body: {disc_only_body}");
        assert_eq!(disc_shadow, 0, "disc alone casts no shadow: {disc_shadow}");

        let (floor_shadow, floor_body, _) = counts_for(floor).expect("adapter");
        let (combined_shadow, combined_body, combined_disc_body) =
            counts_for(combined).expect("adapter");
        assert!(floor_shadow > 100);
        assert!(combined_disc_body > 100 && combined_body > floor_body);
        assert_eq!(
            combined_shadow, floor_shadow,
            "adding a disc leaves the triangle's shadow pixel count unchanged"
        );
    });
}

/// A scene with a world draws it even with no actors.
#[test]
fn world_is_drawn_when_present() {
    common::gpu_test(|| {
        let mut ir = triangle("WORLD_BASE", VisibilityCondition::Always);
        // World vertices carry their scenery class; the layer plane reads it.
        for vertex in &mut ir.vertices {
            vertex.scenery_class = SCENERY_TERRAIN;
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
            tap_failures: Vec::new(),
            view_facing: Vec::new(),
            gate_nodes: Vec::new(),
            prop_runs: Vec::new(),
            placements: PlacementRecords::default(),
        };
        let scene = FilmScene::new(timeline(Vec::new()), HashMap::new(), Some(world));
        let Some((w, h, drawn)) = render(&scene) else {
            return;
        };
        assert!(drawn_in_columns(&drawn, w, h, w / 3..w * 2 / 3) > 100);
    });
}

/// The open's world upload time is zero without a world and positive with one.
#[test]
fn upload_times_charge_the_world_only_when_there_is_one() {
    common::gpu_test(|| {
        let no_world = scene(Vec::new(), VisibilityCondition::Always);
        let Some(test) = common::gpu_or_skip(&no_world) else {
            return;
        };
        assert_eq!(test.renderer.upload_times().world, Duration::ZERO);

        let world = FilmScene::new(
            timeline(Vec::new()),
            HashMap::new(),
            Some(world_of(triangle(
                "WORLD_BASE",
                VisibilityCondition::Always,
            ))),
        );
        let Some(test) = common::gpu_or_skip(&world) else {
            return;
        };
        assert!(test.renderer.upload_times().world > Duration::ZERO);
    });
}

/// A world holding `ir` alone.
pub(crate) fn world_of(ir: SodModelIr) -> World {
    World {
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
        tap_failures: Vec::new(),
        view_facing: Vec::new(),
        gate_nodes: Vec::new(),
        prop_runs: Vec::new(),
        placements: PlacementRecords::default(),
    }
}

/// A view-facing prop whose box crosses the top of the view still draws the part inside it,
/// so the frustum cull keeps it, and one wholly above the view draws nothing.
#[test]
fn a_view_facing_prop_crossing_the_view_edge_still_draws() {
    common::gpu_test(|| {
        // The 45-degree lens at 8 m sees 3.31 m either side of the axis vertically; the
        // triangle spans 2 m about its origin.
        let drawn_rows = |y: f32| {
            let mut world = world_of(SodModelIr::new("EMPTY"));
            world.view_facing = vec![FacingProp {
                shape: SHAPE_ID,
                position: [0.0, y, 0.0],
                node: GateNode::ROOT,
                reach: None,
            }];
            // The camera looks along -Z, so the prop turns a half turn to face it: wound the
            // other way, the triangle faces the eye.
            let mut tri = triangle("TRI", VisibilityCondition::Always);
            tri.indices.reverse();
            let shapes = HashMap::from([(SHAPE_ID, tri)]);
            let scene = FilmScene::new(timeline(Vec::new()), shapes, Some(world));
            let (w, h, drawn) = render(&scene)?;
            let rows: Vec<usize> = (0..w * h).filter(|&n| drawn[n]).map(|n| n / w).collect();
            Some((h, rows))
        };
        let Some((h, crossing)) = drawn_rows(4.0) else {
            return;
        };
        assert!(!crossing.is_empty(), "the crossing prop drew nothing");
        // Its base, inside the view, lands at the top.
        assert!(crossing.iter().all(|&row| row < h / 4), "{crossing:?}");
        let (_, above) = drawn_rows(6.0).expect("adapter");
        assert!(above.is_empty(), "{above:?}");
    });
}

/// A world prop's pixels carry the shape word of the prop run holding its vertices, and
/// nothing else carries one: a prop whose vertices no run holds, a terrain triangle and the
/// sky have no shape word.
#[test]
fn a_world_props_run_reaches_the_shape_plane() {
    common::gpu_test(|| {
        // Two triangles of scenery class `class` side by side; a run of shape 40 holds the
        // left one's vertices.
        let shapes_of = |class: u8| {
            let mut ir = triangle("WORLD_BASE", VisibilityCondition::Always);
            let one = ir.vertices.clone();
            let shifted = |dx: f32| {
                one.iter().map(move |v| SodVertex {
                    position: [v.position[0] + dx, v.position[1], v.position[2]],
                    scenery_class: class,
                    ..*v
                })
            };
            ir.vertices = shifted(-1.1).chain(shifted(1.1)).collect();
            ir.indices = vec![0, 2, 1, 3, 5, 4];
            ir.nodes[0].kind = NodeKind::Mesh {
                vertex_offset: 0,
                vertex_count: 6,
                index_offset: 0,
                index_count: 6,
                is_decal: false,
            };
            let mut world = world_of(ir);
            world.prop_runs = vec![PropRun {
                first: 0,
                end: 3,
                shape: 40,
            }];
            let scene = FilmScene::new(timeline(Vec::new()), HashMap::new(), Some(world));
            let mut test = common::gpu_or_skip(&scene)?;
            let page = test.draw(&scene.frame(0.0));
            let w = page.width() as usize;
            // The shape words of the drawn pixels left and right of the middle, and all words.
            let (mut left, mut right) = (Vec::new(), Vec::new());
            for (n, (&layer, &word)) in page.layers().iter().zip(page.shapes()).enumerate() {
                if layer != LAYER_NONE {
                    if n % w < w / 2 { &mut left } else { &mut right }.push(word);
                }
            }
            Some((left, right, page.shapes().to_vec()))
        };
        let Some((left, right, all)) = shapes_of(SCENERY_PROP) else {
            return;
        };
        assert!(
            left.len() > 50 && right.len() > 50,
            "{} {}",
            left.len(),
            right.len()
        );
        assert!(left.iter().all(|&word| word == 41), "{left:?}");
        assert!(right.iter().all(|&word| word == 0), "{right:?}");
        // Every pixel the left triangle leaves uncovered has no shape word.
        assert_eq!(all.iter().filter(|&&word| word != 0).count(), left.len());
        let (left, right, _) = shapes_of(SCENERY_TERRAIN).expect("adapter");
        assert!(left.iter().chain(&right).all(|&word| word == 0));
    });
}

/// Rows a world sliver of scenery class `class` draws, and the view's rows: a 2 m tall
/// triangle 3 mm wide, about a tenth of a pixel at the test camera's 8 m.
#[expect(
    clippy::indexing_slicing,
    reason = "test helper outside #[test]: an out-of-range index is the assertion failure"
)]
fn sliver_rows(class: u8) -> Option<(usize, usize)> {
    let mut ir = triangle("SLIVER", VisibilityCondition::Always);
    for (vertex, [x, y]) in ir
        .vertices
        .iter_mut()
        .zip([[0.0, -1.0], [0.003, -1.0], [0.0015, 1.0]])
    {
        vertex.position = [x, y, 0.0];
        vertex.scenery_class = class;
    }
    let scene = FilmScene::new(timeline(Vec::new()), HashMap::new(), Some(world_of(ir)));
    let (w, h, drawn) = render(&scene)?;
    let rows = (0..h)
        .filter(|&y| drawn[y * w..(y + 1) * w].iter().any(|&d| d))
        .count();
    Some((rows, h))
}

/// A prop polygon of the world under a pixel wide still draws a pixel on every row it
/// spans, as `PLAYONE`'s inclusive spans do; terrain is not outlined.
#[test]
fn a_world_props_sliver_draws_on_every_row() {
    common::gpu_test(|| {
        let Some((rows, h)) = sliver_rows(SCENERY_PROP) else {
            return;
        };
        // The sliver spans about 30% of the view's rows.
        assert!(rows > h / 4, "prop sliver drew {rows} of {h} rows");
        let Some((rows, h)) = sliver_rows(SCENERY_TERRAIN) else {
            return;
        };
        assert!(rows < h / 10, "terrain sliver drew {rows} of {h} rows");
    });
}

#[test]
fn zero_brightness_frame_renders_black_including_the_clear_colour() {
    common::gpu_test(|| {
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
    });
}

/// A 1 km square on the ground plane at palette index `index`, wound both ways so no
/// face is culled.
fn ground_square(index: u8) -> SodModelIr {
    ground_gradient(500.0, index, index)
}

/// A square of half-side `half` on the ground plane, wound both ways so no face is culled,
/// whose palette index runs from `west` at its -X edge to `east` at its +X edge (a Gouraud
/// polygon when they differ).
#[expect(
    clippy::indexing_slicing,
    reason = "test helper outside #[test]: an out-of-range index is the assertion failure"
)]
fn ground_gradient(half: f32, west: u8, east: u8) -> SodModelIr {
    let vertex = |x: f32, z: f32, index: u8| SodVertex {
        position: [x, 0.0, z],
        normal: [0.0, 1.0, 0.0],
        palette_index: index,
        flags: 4,
        scenery_class: 0,
        decal_tie: 0,
    };
    let mut ir = SodModelIr::new("GROUND");
    ir.vertices = vec![
        vertex(-half, -half, west),
        vertex(half, -half, east),
        vertex(half, half, east),
        vertex(-half, half, west),
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

/// A still film whose eye stands 3 m over `ground`, looking down 20 m ahead along -Z.
fn low_eye_scene(ground: SodModelIr) -> FilmScene {
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
        bank: Default::default(),
    };
    let timeline = FilmTimeline::new(
        vec![SliceKeyframe {
            record,
            tick: 0,
            tick_duration: 1,
        }],
        Vec::new(),
    );
    FilmScene::new(timeline, HashMap::from([(SHAPE_ID, ground)]), None)
}

/// A page's width and height in pixels.
type PagePixels = (u32, u32);

/// A pixel's column, row, and the palette index drawn at it.
type IndexedPixel = (u32, u32, u8);

/// The page size and the pixel position and palette index of every pixel `scene`'s ground
/// covers on the software adapter, or `None` when there is none.
fn ground_pixels_on_software(scene: &FilmScene) -> Option<(PagePixels, Vec<IndexedPixel>)> {
    let mut test = common::gpu_or_skip_software(scene)?;
    let page = test.draw(&scene.frame(0.0));
    let width = page.width();
    let ground: Vec<IndexedPixel> = page
        .layers()
        .iter()
        .zip(page.indices())
        .enumerate()
        .filter(|&(_, (&layer, _))| layer == LAYER_FIRST_ACTOR)
        .map(|(at, (_, &index))| {
            let at = u32::try_from(at).unwrap();
            (at % width, at / width, index)
        })
        .collect();
    assert!(
        ground.len() > 10_000,
        "ground covers {} pixels",
        ground.len()
    );
    Some(((width, page.height()), ground))
}

/// A ground polygon that reaches behind a low eye and past the side planes keeps its own
/// index on every pixel. Mesa's software clipper (lavapipe, CI's adapter) can interpolate
/// the `linear` shade varying of such a polygon to NaN, which used to draw index 0
/// (`research/parity/lavapipe.md` section 1).
#[test]
fn a_ground_polygon_under_a_low_eye_keeps_its_index() {
    common::gpu_test(|| {
        const GROUND_INDEX: u8 = 40;
        let scene = low_eye_scene(ground_square(GROUND_INDEX));
        let Some((_, ground)) = ground_pixels_on_software(&scene) else {
            return;
        };
        let wrong = ground
            .iter()
            .filter(|(_, _, index)| *index != GROUND_INDEX)
            .count();
        assert_eq!(
            wrong,
            0,
            "{wrong} of {} ground pixels lost their index",
            ground.len()
        );
    });
}

/// Where `playone_vertex` (`mode13h.wgsl`) draws a vertex that projects to NDC `ndc` in front of
/// the eye: the centre of the Mode 13h pixel its offset from the projection centre truncates
/// to, as `PLAYONE`'s projectors do (`sod-vm-lines-spans.md` section 8.14), as an NDC point.
/// `half_pixel` is the camera uniform's `line_half_ndc`, so the Mode 13h grid is
/// `0.5 / half_pixel` pixels from the centre to each edge, whatever the page's size.
fn playone_pixel_ndc(ndc: [f32; 2], half_pixel: [f32; 2]) -> [f32; 2] {
    let half = [0.5 / half_pixel[0], 0.5 / half_pixel[1]];
    // Pixels from the view's top left: x grows with NDC x, y against NDC y.
    let offset = [ndc[0] * half[0], -ndc[1] * half[1]];
    let pixel = [
        half[0].floor() + offset[0].trunc() + 0.5,
        half[1].floor() + offset[1].trunc() + 0.5,
    ];
    [
        (pixel[0] - half[0]) / half[0],
        -(pixel[1] - half[1]) / half[1],
    ]
}

/// The four corners of `ground_gradient(half, west, east)`'s quad in page pixels, with the
/// palette index each carries, projected through the camera the renderer draws `scene` with.
/// A corner in front of the eye is drawn on its truncated Mode 13h pixel (`playone_pixel_ndc`);
/// the slide along its ray to the ground plane that keeps it coplanar moves nothing on screen.
/// A corner behind the eye keeps its own projection.
fn projected_ground_corners(
    scene: &FilmScene,
    page: (u32, u32),
    half: f32,
    west: u8,
    east: u8,
) -> [[f32; 3]; 4] {
    let mut controller = CameraController::default();
    controller.set_authored_transform(scene.frame(0.0).view);
    let uniform = controller.build_uniform();
    let rotation_proj = glam::Mat4::from_cols_array(&uniform.rotation_proj);
    let eye = controller.eye_position();
    [
        (-half, -half, west),
        (half, -half, east),
        (half, half, east),
        (-half, half, west),
    ]
    .map(|(x, z, index)| {
        // The vertex stage's transform: the eye's translation comes off the model matrix.
        let clip = rotation_proj * (glam::Vec3::new(x, 0.0, z) - eye).extend(1.0);
        let mut ndc = [clip.x / clip.w, clip.y / clip.w];
        if clip.w > 0.0 {
            ndc = playone_pixel_ndc(ndc, uniform.line_half_ndc);
        }
        let [u, v] = ndc;
        let [half_width, half_height] = [page.0 as f32 / 2.0, page.1 as f32 / 2.0];
        [
            (u + 1.0) * half_width,
            (1.0 - v) * half_height,
            f32::from(index),
        ]
    })
}

/// The palette index `shade`'s screen-linear interpolation gives at pixel centre `(x, y)`: the
/// affine function of pixel position through the three projected corners of the triangle that
/// covers it. The quad's two triangles, `(0, 1, 2)` and `(0, 2, 3)`, meet on the diagonal from
/// corner 0 to corner 2, so which side of that line the pixel falls on picks the triangle; that
/// assumes corner 1 is in front of the eye, as it is here, since a corner behind it would flip
/// its side.
/// `None` within one pixel of the diagonal, where either triangle's rounding may land.
fn screen_linear_index(corners: &[[f32; 3]; 4], x: f32, y: f32) -> Option<f32> {
    let (corner_0, corner_1, corner_2, corner_3) = (corners[0], corners[1], corners[2], corners[3]);
    let diagonal = [corner_2[0] - corner_0[0], corner_2[1] - corner_0[1]];
    let side =
        |p: [f32; 3]| diagonal[0] * (p[1] - corner_0[1]) - diagonal[1] * (p[0] - corner_0[0]);
    let at = side([x, y, 0.0]);
    if at.abs() < diagonal[0].hypot(diagonal[1]) {
        return None;
    }
    let triangle = if at * side(corner_1) > 0.0 {
        [corner_0, corner_1, corner_2]
    } else {
        [corner_0, corner_2, corner_3]
    };
    let [start, row, last] = triangle;
    let det =
        (row[0] - start[0]) * (last[1] - start[1]) - (row[1] - start[1]) * (last[0] - start[0]);
    let along =
        ((x - start[0]) * (last[1] - start[1]) - (y - start[1]) * (last[0] - start[0])) / det;
    let up = ((row[0] - start[0]) * (y - start[1]) - (row[1] - start[1]) * (x - start[0])) / det;
    Some(start[2] + along * (row[2] - start[2]) + up * (last[2] - start[2]))
}

/// The palette index a perspective-correct render of `ground_gradient(half, west, east)` would
/// give at pixel centre `(x, y)`: the index is linear in world X, so it is read off the ground
/// point the pixel's ray meets. The rival `PLAYONE`'s filler does not draw
/// (`research/playone-exe/terrain-shade.md` section 6), kept to show the test can tell it apart.
fn perspective_ground_index(
    scene: &FilmScene,
    page: PagePixels,
    half: f32,
    west: u8,
    east: u8,
) -> impl Fn(f32, f32) -> f32 {
    let mut controller = CameraController::default();
    controller.set_authored_transform(scene.frame(0.0).view);
    let inverse = glam::Mat4::from_cols_array(&controller.build_uniform().rotation_proj).inverse();
    let eye = controller.eye_position();
    move |x, y| {
        let ndc = glam::Vec4::new(
            x / (page.0 as f32 / 2.0) - 1.0,
            1.0 - y / (page.1 as f32 / 2.0),
            0.5,
            1.0,
        );
        let ray = inverse * ndc;
        let ray = ray.truncate() / ray.w;
        let ground_x = eye.x - eye.y * ray.x / ray.y;
        f32::from(west) + (ground_x + half) / (2.0 * half) * (f32::from(east) - f32::from(west))
    }
}

/// A Gouraud ground polygon under a low eye keeps the gradient `PLAYONE`'s filler draws: linear
/// in screen space, not perspective-correct (`research/playone-exe/terrain-shade.md` section 6).
/// The polygon reaches behind the eye and past the side planes, which is what makes Mesa's
/// clipper interpolate the `@interpolate(linear)` varying to NaN (`research/parity/lavapipe.md`
/// section 2), so on lavapipe the index comes from the ratio of the perspective copies of
/// `shade * w` and `w`. Every pixel more than one pixel from the quad's diagonal is compared
/// against the affine function of pixel position through the quad's projected corners, which
/// is the screen-linear value wherever the clipper cut it.
///
/// The comparison allows one index, not zero: with the slide `playone_vertex` gives the two front
/// corners, lavapipe draws some pixels one index off, which a render with the slide disabled
/// does not show; the clipper's fallback bending the gradient is a hypothesis, see the journal.
/// `ONE_OFF_GUARD` bounds how many pixels may be one index off, and
/// `MIN_APART_PIXELS` how many a perspective-correct gradient must part from the model by 3
/// indices or more, so the looser bound still rejects it. The counts and how they were made are in
/// `work/2026-11/1103_gouraud-test-allowance/journal.md`, entry 2026-11-26.
#[test]
#[expect(
    clippy::cast_possible_truncation,
    clippy::cast_sign_loss,
    reason = "the value is clamped to 0..=255 just before the cast"
)]
fn a_gouraud_ground_polygon_under_a_low_eye_keeps_its_gradient() {
    common::gpu_test(|| {
        const WEST: u8 = 40;
        const EAST: u8 = 100;
        const HALF: f32 = 60.0;
        const ONE_OFF_GUARD: usize = 4_500;
        const MIN_APART_PIXELS: usize = 40_000;
        let scene = low_eye_scene(ground_gradient(HALF, WEST, EAST));
        let Some((page, ground)) = ground_pixels_on_software(&scene) else {
            return;
        };
        let corners = projected_ground_corners(&scene, page, HALF, WEST, EAST);
        let perspective = perspective_ground_index(&scene, page, HALF, WEST, EAST);
        let mut beyond_one = Vec::new();
        let mut one_off = 0usize;
        let mut checked = 0usize;
        let mut apart = 0usize;
        for &(x, y, index) in &ground {
            let centre = (x as f32 + 0.5, y as f32 + 0.5);
            let Some(shade) = screen_linear_index(&corners, centre.0, centre.1) else {
                continue;
            };
            let expected = (shade + 0.5).floor().clamp(0.0, 255.0) as u8;
            checked += 1;
            let gap = (perspective(centre.0, centre.1) - shade.clamp(0.0, 255.0)).abs();
            apart += usize::from(gap >= 3.0);
            match index.abs_diff(expected) {
                0 => {}
                1 => one_off += 1,
                _ => beyond_one.push((x, y, expected, index, shade)),
            }
        }
        assert!(
            checked > 10_000,
            "only {checked} ground pixels were checked"
        );
        assert!(
            beyond_one.is_empty(),
            "{} of {checked} ground pixels are more than one index from screen-linear; first: {:?}",
            beyond_one.len(),
            beyond_one.get(..8).unwrap_or(&beyond_one)
        );
        assert!(
            one_off <= ONE_OFF_GUARD,
            "{one_off} of {checked} ground pixels are one index off screen-linear"
        );
        assert!(
            apart >= MIN_APART_PIXELS,
            "a perspective-correct gradient would part from the model by 3 indices at only {apart} of {checked} pixels"
        );
    });
}

// The world's flat ground: `GROUND_NODE` slices drawn first, in walk order, each over what is
// there, as `PLAYONE` paints them with no depth buffer (research/playone-exe/world-scene-residuals.md
// section 6.6).

const FIRST: u8 = 40;
const SECOND: u8 = 220;
const RAIL: u8 = 33;
/// `SodVertex::flags` of a flat-coloured face.
const UNSHADED: u8 = 4;

/// A still timeline whose camera stands 12 m over the ground looking 80 m ahead along -Z.
fn timeline_over_ground() -> FilmTimeline {
    let record = TrajectoryRecord {
        tick: 0,
        camera: CameraTransform {
            eye: [0.0, 12.0, 0.0],
            target: [0.0, 0.0, -80.0],
            fov_degrees: 45.0,
            roll_radians: 0.0,
            cut_from_previous: false,
            ..Default::default()
        },
        actors: Vec::new(),
        audio_cues: Vec::new(),
        palette: PaletteControls::default(),
        bank: Default::default(),
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

fn ground_vertex(x: f32, z: f32, palette_index: u8, flags: u8, class: u8) -> SodVertex {
    SodVertex {
        position: [x, 0.0, z],
        normal: [0.0, 1.0, 0.0],
        palette_index,
        flags,
        scenery_class: class,
        decal_tie: 0,
    }
}

/// A world of an empty root and one `GROUND_NODE` child per `(vertices, indices)` part, in
/// order; each part's indices count from its own first vertex.
fn ground_world(parts: Vec<(Vec<SodVertex>, Vec<u32>)>) -> FilmScene {
    let mut ir = SodModelIr::new("WORLD_SCENERY");
    let root = ir.allocate_node(
        "WORLD_BASE",
        None,
        glam::Mat4::IDENTITY.to_cols_array(),
        VisibilityCondition::Always,
        NodeKind::TransformGroup,
    );
    for (vertices, indices) in parts {
        let vertex_offset = u32::try_from(ir.vertices.len()).unwrap();
        let index_offset = u32::try_from(ir.indices.len()).unwrap();
        ir.indices
            .extend(indices.iter().map(|&i| i + vertex_offset));
        ir.allocate_node(
            GROUND_NODE,
            Some(root),
            glam::Mat4::IDENTITY.to_cols_array(),
            VisibilityCondition::Always,
            NodeKind::Mesh {
                vertex_offset,
                vertex_count: u32::try_from(vertices.len()).unwrap(),
                index_offset,
                index_count: u32::try_from(indices.len()).unwrap(),
                is_decal: false,
            },
        );
        ir.vertices.extend(vertices);
    }
    ir.root_nodes = vec![root];
    FilmScene::new(timeline_over_ground(), HashMap::new(), Some(world_of(ir)))
}

/// Pixels drawn with each of `indices` on any layer but the sky's.
fn counts<const N: usize>(scene: &FilmScene, indices: [u8; N]) -> Option<[usize; N]> {
    let mut test = common::gpu_or_skip(scene)?;
    let page = test.draw(&scene.frame(0.0));
    Some(indices.map(|wanted| {
        page.layers()
            .iter()
            .zip(page.indices())
            .filter(|&(&layer, &index)| layer != LAYER_NONE && index == wanted)
            .count()
    }))
}

/// A flat ground slice drawn after another in the same plane covers it on every pixel,
/// although the two are triangulated along different diagonals and round their depths apart.
#[test]
fn a_later_ground_slice_wins_every_pixel_of_the_plane() {
    common::gpu_test(|| {
        let quad = |index: u8| -> Vec<SodVertex> {
            [
                [-300.0, -2000.0],
                [300.0, -2000.0],
                [300.0, -1.0],
                [-300.0, -1.0],
            ]
            .map(|[x, z]| ground_vertex(x, z, index, UNSHADED, SCENERY_TERRAIN))
            .to_vec()
        };
        // Clockwise from above: far-left, far-right, near-right, and the other diagonal.
        let scene = ground_world(vec![
            (quad(FIRST), vec![0, 1, 2, 0, 2, 3]),
            (quad(SECOND), vec![1, 2, 3, 1, 3, 0]),
        ]);
        let Some([first, second]) = counts(&scene, [FIRST, SECOND]) else {
            return;
        };
        assert!(second > 10_000, "the later slice covers {second} pixels");
        assert_eq!(first, 0, "the earlier slice shows on {first} pixels");
    });
}

/// A prop's line drawn after its fill keeps every pixel it draws alone, although the
/// fill's outline crosses it: the outline is drawn with its own slice, before the line's.
#[test]
fn a_ground_outline_does_not_cover_the_line_after_it() {
    common::gpu_test(|| {
        // A tie 6 m wide across the view, whose outline is drawn.
        let tie: Vec<SodVertex> = [[-3.0, -40.0], [3.0, -40.0], [3.0, -38.0], [-3.0, -38.0]]
            .map(|[x, z]| ground_vertex(x, z, FIRST, UNSHADED, SCENERY_PROP))
            .to_vec();
        // A rail along the view crossing the tie, laid out as the decoder lays out a line.
        let (a, b) = ([0.0, 0.0, -50.0], [0.0, 0.0, -30.0]);
        let ab = [0.0, 0.0, 20.0];
        let ba = [0.0, 0.0, -20.0];
        let rail: Vec<SodVertex> = [
            (a, ab, VERTEX_FLAG_LINE),
            (a, ab, VERTEX_FLAG_LINE | VERTEX_FLAG_LINE_SIDE),
            (
                b,
                ba,
                VERTEX_FLAG_LINE | VERTEX_FLAG_LINE_END | VERTEX_FLAG_LINE_SIDE,
            ),
            (b, ba, VERTEX_FLAG_LINE | VERTEX_FLAG_LINE_END),
        ]
        .map(|(position, normal, flags)| SodVertex {
            position,
            normal,
            palette_index: RAIL,
            flags: flags | UNSHADED,
            scenery_class: SCENERY_PROP,
            decal_tie: 0,
        })
        .to_vec();
        let rail_indices = vec![0, 1, 2, 0, 2, 3, 0, 2, 1, 0, 3, 2];
        let with_tie = ground_world(vec![
            (tie, vec![0, 1, 2, 0, 2, 3]),
            (rail.clone(), rail_indices.clone()),
        ]);
        let alone = ground_world(vec![(rail, rail_indices)]);
        let (Some([over, tie]), Some([alone])) =
            (counts(&with_tie, [RAIL, FIRST]), counts(&alone, [RAIL]))
        else {
            return;
        };
        assert!(tie > 100, "the tie covers {tie} pixels");
        assert!(alone > 20, "the rail alone covers {alone} pixels");
        assert_eq!(over, alone, "the rail keeps {over} of its {alone} pixels");
    });
}

/// A one-triangle shape stream whose colour `OP_SHADES` and `OP_SHADE1` take from the light:
/// its one normal points down, so a light from above shades it brightest.
/// Its corners run clockwise toward the test camera, so it faces it: a back-facing one draws
/// nothing, outline included.
fn shaded_triangle_stream() -> Vec<u8> {
    use stunt_core::sod::{OP_ID, OP_IPG, OP_POLYZ, OP_RETURN, OP_SHADE1, OP_SHADES};
    let down = 0x8001; // -32767
    let words = [
        OP_ID, 100, 0, 0, 0, OP_IPG, 8, 100, 50, 0, OP_SHADES, 0, 1, 0, down, 0, OP_SHADE1, 0,
        0x40, OP_POLYZ, 3, 0, 24, 12, OP_RETURN,
    ];
    words.iter().flat_map(|w| w.to_le_bytes()).collect()
}

/// A rotated actor draws its shape decoded under its own light, `R · L`, frame by frame: the
/// unrotated first frame keeps the world light, and each turn after it recolours the shape.
#[test]
fn a_rotated_actor_draws_in_the_colours_of_its_own_light() {
    use stunt_core::scene::RelitShapes;
    use stunt_core::sod::{DecodeMode, ShadeLight, decode_sod_lit};

    common::gpu_test(|| {
        let stream = shaded_triangle_stream();
        let decode = |light: ShadeLight| {
            decode_sod_lit(&stream, "SHADED", None, DecodeMode::Lenient, light)
                .expect("decode the shaded triangle")
        };
        let world = ShadeLight::WORLD_0X2D;
        // Roll about the view axis, so the triangle keeps facing the camera.
        let roll = |degrees: f32| {
            let half = degrees.to_radians() / 2.0;
            [0.0, 0.0, half.sin(), half.cos()]
        };
        let turns = [roll(0.0), roll(90.0), roll(45.0)];
        let keyframes = turns
            .iter()
            .zip(0u32..)
            .map(|(&rotation_quat, n)| {
                let mut actor = actor_at(0.0, 0);
                actor.rotation_quat = rotation_quat;
                let mut slice = timeline(vec![actor]).slices()[0].clone();
                slice.tick = n * 10;
                slice.record.tick = n * 10;
                slice.tick_duration = 10;
                slice
            })
            .collect();
        let shapes = HashMap::from([(SHAPE_ID, decode(world))]);
        let streams = HashMap::from([(SHAPE_ID, ("SHADED".to_string(), stream.clone()))]);
        let scene = FilmScene::new(FilmTimeline::new(keyframes, Vec::new()), shapes, None)
            .with_relit_shapes(RelitShapes::new(streams, world));
        let Some(mut test) = common::gpu_or_skip(&scene) else {
            return;
        };
        let mut seen = Vec::new();
        for (n, &rotation) in (0u8..).zip(&turns) {
            let frame = scene.frame(f32::from(n) * 10.0);
            let [actor] = frame.actors.as_slice() else {
                panic!("one actor draw at turn {n}");
            };
            assert_eq!(actor.light, world.for_actor(rotation));
            let expected = decode(actor.light).vertices[0].palette_index;
            let page = test.draw(&frame);
            let drawn: Vec<u8> = page
                .indices()
                .iter()
                .zip(page.layers())
                .filter(|&(_, &layer)| layer == LAYER_FIRST_ACTOR)
                .map(|(&index, _)| index)
                .collect();
            assert!(
                drawn.len() > 50,
                "turn {n}: the actor covers {} pixels",
                drawn.len()
            );
            assert!(
                drawn.iter().all(|&index| index == expected),
                "turn {n}: expected index {expected} everywhere, drew {:?}",
                drawn
                    .iter()
                    .copied()
                    .collect::<std::collections::BTreeSet<_>>()
            );
            seen.push(expected);
        }
        seen.dedup();
        assert_eq!(seen.len(), 3, "each turn shades differently: {seen:?}");
    });
}
