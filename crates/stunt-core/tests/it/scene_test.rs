#![expect(
    clippy::cast_possible_truncation,
    reason = "these tests pack synthetic values into the fixed-width fields of fixture bytes"
)]
//! Film scene assembly and frame sampling through the public [`stunt_core::scene`] interface.
//!
//! Everything is synthetic: fixture SODs and anchors from `tests/fixtures/`, plus
//! hand-built `.FLM` and `.ALL` bytes, so nothing depends on `corpus/`.

use crate::common;

use std::collections::HashMap;
use std::path::PathBuf;

use common::{ACTOR_RZ_BAM, push_interp, res_file};
use stunt_core::contracts::{SodModelIr, SodStop, SodStopReason};
use stunt_core::flm::{
    FilmTimeline, FlmError, SIF_DRAW, SIF_EXISTS, SIF_MOVES, SIF_ROTATES, SIF_SHADOW,
};
use stunt_core::link::LinkError;
use stunt_core::scene::{FilmScene, SceneError, SceneInputs, ShapeSource, SpriteDraw, bank_word};
use stunt_core::sod::{DecodeMode, EPSILON_DISPLACEMENT, OP_TAP, decode_sod};
use stunt_core::vfs::{res_regions, write_all};
use stunt_core::world::ScnStopReason;

fn fixture(name: &str) -> Vec<u8> {
    let dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("..")
        .join("..")
        .join("tests")
        .join("fixtures");
    std::fs::read(dir.join(name)).unwrap_or_else(|e| panic!("read {name}: {e}"))
}

/// A one-slice film: camera at `eye` in slot 0, then one actor per `(shape_id, position)`.
fn film(eye: [f32; 3], actors: &[(u16, [f32; 3])]) -> Vec<u8> {
    film_with_actor_rotation(eye, actors, ACTOR_RZ_BAM, ACTOR_FLAGS)
}

/// The create flags of every actor slot [`film`] writes.
const ACTOR_FLAGS: u8 = SIF_EXISTS | SIF_DRAW | SIF_MOVES | SIF_ROTATES;

/// Like [`film`], with every actor turned `actor_rz_bam` and created with `actor_flags`.
fn film_with_actor_rotation(
    eye: [f32; 3],
    actors: &[(u16, [f32; 3])],
    actor_rz_bam: u16,
    actor_flags: u8,
) -> Vec<u8> {
    let mut body = vec![0x9B, (actors.len() + 1) as u8];
    body.extend_from_slice(&[0x00, SIF_EXISTS | SIF_MOVES | SIF_ROTATES, 0x90]);
    for (i, (shape_id, _)) in actors.iter().enumerate() {
        body.push(1 + i as u8);
        body.push(actor_flags);
        body.extend_from_slice(&shape_id.to_le_bytes());
    }
    push_interp(&mut body, 0x40, eye, 0);
    for (i, (_, pos)) in actors.iter().enumerate() {
        push_interp(&mut body, 0x41 + i as u8, *pos, actor_rz_bam);
    }
    body.push(0xFF);

    let mut bytes = b"FILM".to_vec();
    bytes.extend_from_slice(&0u16.to_le_bytes());
    bytes.push(0);
    bytes.extend_from_slice(&body);
    bytes
}

/// An `.ALL` archive of `(resource id, payload)` chunks.
fn archive(chunks: &[(u16, &[u8])]) -> Vec<u8> {
    let n = chunks.len();
    let mut out = (n as u16).to_le_bytes().to_vec();
    for (id, _) in chunks {
        out.extend_from_slice(&id.to_le_bytes());
    }
    let mut offset = 2 + n * 6;
    for (_, data) in chunks {
        out.extend_from_slice(&(offset as u32).to_le_bytes());
        offset += data.len();
    }
    for (_, data) in chunks {
        out.extend_from_slice(data);
    }
    out
}

fn model(bytes: &[u8]) -> SodModelIr {
    decode_sod(bytes, "MODEL", None, DecodeMode::Strict).expect("fixture model")
}

fn scene_inputs(film: &[u8]) -> SceneInputs<'_> {
    SceneInputs {
        film,
        shapes: None,
        anchors: None,
        map: None,
        scenery: None,
    }
}

#[test]
fn actors_sharing_a_shape_get_separate_draws() {
    let film = film(
        [0.0, 0.0, 10.0],
        &[(7, [3.0, 0.0, 0.0]), (7, [0.0, 4.0, 10.0])],
    );
    let all = archive(&[(7, &fixture("synthetic_minimal.sod"))]);
    let (scene, report) = FilmScene::load(&SceneInputs {
        shapes: Some(ShapeSource::Archive(&all)),
        ..scene_inputs(&film)
    })
    .expect("load");

    assert!(report.skipped.is_empty());
    assert!(
        scene
            .shape(7)
            .and_then(SodModelIr::decode)
            .expect("decoded shape")
            .stop
            .is_none()
    );
    assert!(report.film_stop.is_none());
    assert!(!report.anchors_loaded);
    assert!(report.world.is_none());
    assert!(scene.shape(7).is_some());
    assert_eq!(scene.shapes().count(), 1);

    let frame = scene.frame(0.0);
    assert!(!frame.world);
    assert_eq!(frame.view.eye, [0.0, 0.0, 10.0]);
    assert_eq!(frame.actors.len(), 2);
    assert!(frame.actors.iter().all(|a| a.shape_id == 7));
    assert_ne!(frame.actors[0].world_matrix, frame.actors[1].world_matrix);
    // Column-major translation lives in elements 12..15.
    assert_eq!(&frame.actors[0].world_matrix[12..15], &[3.0, 0.0, 0.0]);
    assert_eq!(&frame.actors[1].world_matrix[12..15], &[0.0, 4.0, 10.0]);
}

/// A slot created with `SIF_SHADOW` gets a shadow matrix: its own x and z rows, every model
/// height dropped, on `y = 0` (no world) lifted the `[I5]` 1 mm. A slot without it gets none.
#[test]
fn a_shadow_slot_gets_its_matrix_flattened_onto_the_ground() {
    let all = archive(&[(7, &fixture("synthetic_minimal.sod"))]);
    let draw = |flags: u8| {
        let film = film_with_actor_rotation(
            [0.0, 0.0, 10.0],
            &[(7, [3.0, 2.0, 0.0])],
            ACTOR_RZ_BAM,
            flags,
        );
        let (scene, _) = FilmScene::load(&SceneInputs {
            shapes: Some(ShapeSource::Archive(&all)),
            ..scene_inputs(&film)
        })
        .expect("load");
        let actor = &scene.frame(0.0).actors[0];
        (actor.world_matrix, actor.shadow_matrix)
    };
    assert_eq!(draw(ACTOR_FLAGS).1, None);

    let (world, shadow) = draw(ACTOR_FLAGS | SIF_SHADOW);
    let shadow = shadow.expect("a SIF_SHADOW slot casts a shadow");
    // Column-major: row 1 (y) is elements 1, 5, 9, 13.
    assert_eq!([shadow[1], shadow[5], shadow[9]], [0.0; 3]);
    assert!(
        (shadow[13] - EPSILON_DISPLACEMENT).abs() < 1e-7,
        "{}",
        shadow[13]
    );
    for i in [0, 2, 4, 6, 8, 10, 12, 14] {
        assert_eq!(shadow[i], world[i], "x and z rows kept, element {i}");
    }
}

#[test]
fn actor_is_drawn_without_its_shapes_ground_offset() {
    // The decoder lifts every vertex by `ground_y_offset`; an actor's film position is
    // already its model origin, so the draw takes the lift back out along the actor's +Y.
    let mut sod = fixture("synthetic_minimal.sod");
    sod[4..6].copy_from_slice(&40i16.to_le_bytes());
    // A quarter turn, so the actor's +Y is not world +Y and the lift's axis is tested.
    let film = film_with_actor_rotation(
        [0.0, 0.0, 10.0],
        &[(7, [3.0, 2.0, 0.0])],
        0x4000,
        ACTOR_FLAGS,
    );
    let all = archive(&[(7, &sod)]);
    let (scene, _) = FilmScene::load(&SceneInputs {
        shapes: Some(ShapeSource::Archive(&all)),
        ..scene_inputs(&film)
    })
    .expect("load");
    let header = scene
        .shape(7)
        .and_then(SodModelIr::decode)
        .expect("decoded shape")
        .header;
    let lift = f32::from(header.ground_y_offset) * header.scale_factor;
    assert!(lift > 0.0);

    let frame = scene.frame(0.0);
    let m = frame.actors[0].world_matrix;
    assert!(
        (m[5] - 1.0).abs() > 0.5,
        "actor basis is unrotated: {:?}",
        &m[4..7]
    );
    let expected = [3.0 - m[4] * lift, 2.0 - m[5] * lift, -m[6] * lift];
    for (got, want) in m[12..15].iter().zip(expected) {
        assert!(
            (got - want).abs() < 1e-5,
            "{:?} != {expected:?}",
            &m[12..15]
        );
    }
}

#[test]
fn distance_is_eye_to_actor_position() {
    let film = film(
        [0.0, 0.0, 10.0],
        &[(7, [3.0, 0.0, 10.0]), (7, [0.0, 4.0, 10.0])],
    );
    let all = archive(&[(7, &fixture("synthetic_minimal.sod"))]);
    let (scene, _) = FilmScene::load(&SceneInputs {
        shapes: Some(ShapeSource::Archive(&all)),
        ..scene_inputs(&film)
    })
    .expect("load");

    let frame = scene.frame(0.0);
    assert!((frame.actors[0].distance - 3.0).abs() < 1e-4);
    assert!((frame.actors[1].distance - 4.0).abs() < 1e-4);
}

#[test]
fn actor_without_a_shape_is_not_drawn() {
    let film = film([0.0, 0.0, 10.0], &[(7, [0.0; 3]), (9, [1.0, 0.0, 0.0])]);
    let all = archive(&[(7, &fixture("synthetic_minimal.sod"))]);
    let (scene, _) = FilmScene::load(&SceneInputs {
        shapes: Some(ShapeSource::Archive(&all)),
        ..scene_inputs(&film)
    })
    .expect("load");

    let frame = scene.frame(0.0);
    assert_eq!(frame.actors.len(), 1);
    assert_eq!(frame.actors[0].shape_id, 7);
    assert!(scene.shape(9).is_none());
}

#[test]
fn undecodable_chunk_is_skipped_and_reported() {
    let film = film([0.0, 0.0, 10.0], &[(7, [0.0; 3])]);
    // Header word 0x000C names the chunk MODEL_*.SOD but the body is truncated.
    let bad = [0x0C, 0x00, 0x01];
    let all = archive(&[(7, &fixture("synthetic_minimal.sod")), (8, &bad)]);
    let (scene, report) = FilmScene::load(&SceneInputs {
        shapes: Some(ShapeSource::Archive(&all)),
        ..scene_inputs(&film)
    })
    .expect("load");

    assert_eq!(report.skipped.len(), 1);
    assert_eq!(report.skipped[0].name, "MODEL_0008.SOD");
    assert_eq!(scene.shapes().count(), 1);
}

#[test]
fn tap_shape_without_anchors_is_reported_partial() {
    let film = film([0.0, 0.0, 10.0], &[(5, [0.0; 3])]);
    let all = archive(&[(5, &fixture("synthetic_tap.sod"))]);

    let (scene, report) = FilmScene::load(&SceneInputs {
        shapes: Some(ShapeSource::Archive(&all)),
        ..scene_inputs(&film)
    })
    .expect("load");
    assert!(!report.anchors_loaded);
    let record = scene
        .shape(5)
        .and_then(SodModelIr::decode)
        .expect("decoded shape");
    assert_eq!(
        record.stop,
        Some(SodStop {
            offset: 10,
            opcode: OP_TAP,
            reason: SodStopReason::MissingAnchors,
        })
    );
    assert_eq!(scene.frame(0.0).actors.len(), 1);

    let anchors = fixture("synthetic_anchors.bin");
    let (scene, report) = FilmScene::load(&SceneInputs {
        shapes: Some(ShapeSource::Archive(&all)),
        anchors: Some(&anchors),
        ..scene_inputs(&film)
    })
    .expect("load");
    assert!(report.anchors_loaded);
    assert!(
        scene
            .shape(5)
            .and_then(SodModelIr::decode)
            .expect("decoded shape")
            .stop
            .is_none()
    );
}

#[test]
fn truncated_film_surfaces_stop_reason() {
    let mut bytes = film([0.0, 0.0, 10.0], &[(7, [0.0; 3])]);
    // A second slice holding an unknown opcode stops the walk.
    bytes.extend_from_slice(&[0x10, 0x00, 0x01, 0xEF, 0xFF]);
    let (scene, report) = FilmScene::load(&scene_inputs(&bytes)).expect("load");
    assert!(matches!(
        report.film_stop,
        Some(FlmError::InvalidOpcode { opcode: 0xEF, .. })
    ));
    assert_eq!(scene.timeline().slices().len(), 1);
    assert_eq!(report.film_stop.as_ref(), scene.timeline().stop_reason());
}

#[test]
fn unreadable_inputs_are_errors() {
    let err = FilmScene::load(&scene_inputs(b"NOPE")).expect_err("bad film");
    assert!(matches!(
        err,
        SceneError::Film(FlmError::InvalidSignature { .. })
    ));

    let film = film([0.0, 0.0, 10.0], &[]);
    let err = FilmScene::load(&SceneInputs {
        shapes: Some(ShapeSource::Archive(&[0x05])),
        ..scene_inputs(&film)
    })
    .expect_err("bad archive");
    assert!(matches!(err, SceneError::Archive(_)));
}

#[test]
fn world_is_present_when_anchors_and_map_are_supplied() {
    let film = film([0.0, 0.0, 10.0], &[]);
    let anchors = fixture("synthetic_anchors.bin");
    // A MAP.BIN of one patch after the 2-byte list head: in use, color 4, anchors 0, 1, 2.
    let mut patch = vec![0u8; 2 + 30];
    patch[2..4].copy_from_slice(&0x01FFu16.to_le_bytes());
    patch[12] = 4;
    patch[14..16].copy_from_slice(&3i16.to_le_bytes());
    for (j, v) in [0u16, 1, 2].iter().enumerate() {
        patch[16 + j * 2..18 + j * 2].copy_from_slice(&v.to_le_bytes());
    }

    let (scene, report) = FilmScene::load(&SceneInputs {
        anchors: Some(&anchors),
        map: Some(&patch),
        ..scene_inputs(&film)
    })
    .expect("load");

    let stats = report.world.expect("world stats");
    assert_eq!(stats.terrain_patches, 1);
    assert!(scene.world().is_some());
    assert!(scene.frame(0.0).world);

    let (bare, report) = FilmScene::load(&scene_inputs(&film)).expect("load");
    assert!(report.world.is_none());
    assert!(bare.world().is_none());
    assert!(!bare.frame(0.0).world);
}

#[test]
fn single_model_binds_first_actor_with_a_nonzero_shape() {
    let film = film(
        [0.0, 0.0, 10.0],
        &[(0, [1.0, 0.0, 0.0]), (6, [2.0, 0.0, 0.0])],
    );
    let timeline = FilmTimeline::from_bytes(&film).expect("timeline");
    let scene = FilmScene::with_single_model(timeline, model(&fixture("synthetic_minimal.sod")));

    assert_eq!(scene.shapes().map(|(id, _)| id).collect::<Vec<_>>(), [6]);
    let frame = scene.frame(0.0);
    assert_eq!(frame.actors.len(), 1);
    assert_eq!(frame.actors[0].shape_id, 6);
    assert_eq!(&frame.actors[0].world_matrix[12..15], &[2.0, 0.0, 0.0]);
}

#[test]
fn single_model_falls_back_to_first_actor() {
    let film = film([0.0, 0.0, 10.0], &[(0, [1.0, 0.0, 0.0])]);
    let timeline = FilmTimeline::from_bytes(&film).expect("timeline");
    let scene = FilmScene::with_single_model(timeline, model(&fixture("synthetic_minimal.sod")));

    let frame = scene.frame(0.0);
    assert_eq!(frame.actors.len(), 1);
    assert_eq!(&frame.actors[0].world_matrix[12..15], &[1.0, 0.0, 0.0]);
}

#[test]
fn single_model_without_actors_draws_at_the_origin() {
    let film = film([0.0, 0.0, 10.0], &[]);
    let timeline = FilmTimeline::from_bytes(&film).expect("timeline");
    let scene = FilmScene::with_single_model(timeline, model(&fixture("synthetic_minimal.sod")));

    let frame = scene.frame(0.0);
    assert_eq!(frame.actors.len(), 1);
    let identity = [
        1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0,
    ];
    assert_eq!(frame.actors[0].world_matrix, identity);
    assert!((frame.actors[0].distance - 10.0).abs() < 1e-4);
}

#[test]
fn empty_timeline_yields_an_empty_frame() {
    let scene = FilmScene::new(
        FilmTimeline::new(Vec::new(), Vec::new()),
        HashMap::new(),
        None,
    );
    let frame = scene.frame(5.0);
    assert_eq!(frame.tick, 5.0);
    assert!(frame.actors.is_empty());
    assert!(!frame.world);
}

#[test]
fn caller_supplied_timeline_keeps_archive_shapes() {
    let film = film([0.0, 0.0, 10.0], &[(7, [3.0, 0.0, 0.0])]);
    let all = archive(&[(7, &fixture("synthetic_minimal.sod"))]);
    let inputs = SceneInputs {
        shapes: Some(ShapeSource::Archive(&all)),
        ..scene_inputs(&[])
    };
    let timeline = FilmTimeline::from_bytes(&film).expect("film");
    let (scene, report) = FilmScene::load_with_timeline(timeline, &inputs).expect("load");

    assert!(report.skipped.is_empty());
    assert!(scene.shape(7).is_some());
    assert_eq!(scene.frame(0.0).actors.len(), 1);
}

/// Shapes from the game's `RES` files and from a `.ALL` copying the same items are the same:
/// same ids, same decode (anchors and light included), same skipped items, same draws.
#[test]
fn res_files_give_the_shapes_of_an_archive_of_their_items() {
    let minimal = fixture("synthetic_minimal.sod");
    let tap = fixture("synthetic_tap.sod");
    let anchors = fixture("synthetic_anchors.bin");
    // Item 1 is a name table, not a shape; item 4 starts like a shape but does not decode.
    let broken: &[u8] = &[0x0C, 0x00, 0x01];
    let props = res_file(0x01, &[b"NAMES\0", &minimal, &tap, broken]);
    let planes = res_file(0x7F, &[&minimal]);
    let sound = res_file(0xC0, &[&minimal]);
    let files = [&sound, &props, &planes].map(|bytes| res_regions(bytes).expect("split"));
    let all = write_all(&[
        (0x0101, b"NAMES\0"),
        (0x0102, &minimal),
        (0x0103, &tap),
        (0x0104, broken),
        (0x7F01, &minimal),
    ])
    .expect("archive");

    let film = film(
        [0.0, 0.0, 10.0],
        &[(0x0103, [3.0, 0.0, 0.0]), (0x7F01, [0.0, 4.0, 10.0])],
    );
    let load = |shapes| {
        FilmScene::load(&SceneInputs {
            shapes: Some(shapes),
            anchors: Some(&anchors),
            ..scene_inputs(&film)
        })
        .expect("load")
    };
    let (from_res, res_report) = load(ShapeSource::Res(&files));
    let (from_all, all_report) = load(ShapeSource::Archive(&all));

    let sorted = |scene: &FilmScene| {
        let mut shapes: Vec<(u16, SodModelIr)> =
            scene.shapes().map(|(id, ir)| (id, ir.clone())).collect();
        shapes.sort_by_key(|(id, _)| *id);
        shapes
    };
    let ids: Vec<u16> = sorted(&from_res).iter().map(|(id, _)| *id).collect();
    assert_eq!(ids, [0x0102, 0x0103, 0x7F01]);
    assert_eq!(sorted(&from_res), sorted(&from_all));
    assert_eq!(res_report, all_report);
    assert_eq!(res_report.skipped.len(), 1);
    assert_eq!(res_report.skipped[0].name, "MODEL_0104.SOD");
    assert_eq!(from_res.frame(0.0), from_all.frame(0.0));
    assert_eq!(from_res.frame(0.0).actors.len(), 2);
}

#[test]
fn res_files_sharing_a_shape_index_are_an_error() {
    let minimal = fixture("synthetic_minimal.sod");
    let a = res_file(0x05, &[&minimal]);
    let b = res_file(0x05, &[&minimal]);
    let files = [&a, &b].map(|bytes| res_regions(bytes).expect("split"));
    let film = film([0.0, 0.0, 10.0], &[]);
    let err = FilmScene::load(&SceneInputs {
        shapes: Some(ShapeSource::Res(&files)),
        ..scene_inputs(&film)
    })
    .expect_err("duplicate index");
    assert_eq!(
        err,
        SceneError::Res(LinkError::DuplicateIndex { index: 0x05 })
    );
}

#[test]
fn cyclic_scenery_surfaces_its_stop_in_the_report() {
    let film = film([0.0, 0.0, 10.0], &[]);
    let scenery = fixture("synthetic_cyclic.scn");
    let (_, report) = FilmScene::load(&SceneInputs {
        scenery: Some(&scenery),
        ..scene_inputs(&film)
    })
    .expect("load");
    let stop = report.world.expect("a world").scenery_stop;
    assert_eq!(stop.map(|s| s.reason), Some(ScnStopReason::Cycle));
}

#[test]
fn an_animated_shape_draws_its_sprite_at_the_actor() {
    let film = film(
        [0.0, 0.0, 10.0],
        &[(0, [9.0, 9.0, 9.0]), (7, [3.0, 0.0, 0.0])],
    );
    let sprite = fixture("synthetic_sprite.bin");
    let all = archive(&[
        (7, &fixture("synthetic_animate.sod")),
        (0x1F01, &sprite),
        (0x1F02, &sprite),
    ]);
    let (scene, _) = FilmScene::load(&SceneInputs {
        shapes: Some(ShapeSource::Archive(&all)),
        ..scene_inputs(&film)
    })
    .expect("load");
    assert_eq!(scene.images().count(), 2);
    assert_eq!(
        scene.image(0x1F01).map(|i| i.pixels.clone()),
        Some(vec![5, 0, 0, 7])
    );

    // No animate word: frame 0 of the table, 2 m across at the actor's origin. Shape 0 is not
    // in the archive, so the animated actor is draw 0.
    let frame = scene.frame(0.0);
    assert_eq!(
        frame.sprites,
        vec![SpriteDraw {
            image_id: 0x1F01,
            centre: [3.0, 0.0, 0.0],
            size: 2.0,
            actor: 0,
        }]
    );
    assert_eq!(frame.actors[0].shape_id, 7);
}

#[test]
fn a_sprite_whose_frame_is_missing_is_not_drawn() {
    let film = film([0.0, 0.0, 10.0], &[(7, [3.0, 0.0, 0.0])]);
    let all = archive(&[(7, &fixture("synthetic_animate.sod"))]);
    let (scene, _) = FilmScene::load(&SceneInputs {
        shapes: Some(ShapeSource::Archive(&all)),
        ..scene_inputs(&film)
    })
    .expect("load");
    assert_eq!(scene.images().count(), 0);
    let frame = scene.frame(0.0);
    assert_eq!(frame.actors.len(), 1);
    assert!(frame.sprites.is_empty());
}

#[test]
fn bank_words_follow_the_film_clock_and_the_animate_word() {
    // `0x10`: tick << 12, one sweep per 16 ticks, from the whole tick.
    assert_eq!(bank_word(0x10, 5.7, 999), 0x5000);
    assert_eq!(bank_word(0x10, 16.0, 999), 0);
    assert_eq!(bank_word(0x10, 31.0, 999), 0xF000);
    // `0x16`: the slot's animate word.
    assert_eq!(bank_word(0x16, 3.0, 1234), 1234);
    // Unmodelled words read as 0.
    assert_eq!(bank_word(0x12, 3.0, 1234), 0);
}

/// A `SCENERY.scn` of `words`, each a little-endian `i32`.
fn scenery(words: &[i32]) -> Vec<u8> {
    words.iter().flat_map(|w| w.to_le_bytes()).collect()
}

/// A drawn-only scene loaded with `SP_1NODE` scenery keeps the actor's shape and the
/// view-facing child of the node, and drops the baked child, whose geometry stays in the
/// world mesh, and a shape nothing places.
#[test]
fn a_drawn_only_scene_keeps_the_actor_and_the_view_facing_lod_child() {
    use stunt_core::contracts::SCENERY_PROP;
    use stunt_core::sod::{OP_ID, OP_IPG, OP_POLYZ, OP_RETURN};

    const ACTOR: u16 = 0x0001;
    const TREE: u16 = 0x0102;
    const BAKED: u16 = 0x0105;
    const UNUSED: u16 = 0x0107;
    // A shape the archive lacks, standing in for the node's subtree.
    const STAND_IN: u16 = 0x0200;

    // A view-facing tree: header flag 0x0100 marks the shape as facing the camera.
    let tree: Vec<u8> = [
        OP_ID, 100, 0, 0x0100, 0, OP_IPG, 8, 100, 50, 0, OP_POLYZ, 3, 0, 12, 24, OP_RETURN,
    ]
    .iter()
    .flat_map(|w| w.to_le_bytes())
    .collect();
    let sod = fixture("synthetic_minimal.sod");
    let all = archive(&[(ACTOR, &sod), (TREE, &tree), (BAKED, &sod), (UNUSED, &sod)]);
    // Word 1: SP_POS at the origin, next -> word 6.
    // Word 6: SP_1NODE (stand-in, ext 10, splitdist 105), its subtree -> word 11.
    // Word 11: SP_LIST of the leaves at words 15 and 17.
    let words = [
        0,
        0,
        0,
        0,
        0,
        12,
        2,
        i32::from(STAND_IN),
        10,
        105,
        22,
        20,
        30,
        34,
        0,
        10,
        i32::from(TREE),
        10,
        i32::from(BAKED),
    ];
    let scenery = scenery(&words);
    let film = film([0.0, 0.0, 10.0], &[(ACTOR, [1.0, 0.0, 0.0])]);

    let (scene, _) = FilmScene::load(&SceneInputs {
        shapes: Some(ShapeSource::Archive(&all)),
        scenery: Some(&scenery),
        ..scene_inputs(&film)
    })
    .expect("load");
    let world = scene.world().expect("a world");
    let facing: Vec<u16> = world.view_facing.iter().map(|p| p.shape).collect();
    assert_eq!(facing, [TREE], "the tree is placed behind the node's gate");
    assert_eq!(world.view_facing[0].gates.len(), 1);
    let baked = world
        .ir
        .vertices
        .iter()
        .filter(|v| v.scenery_class == SCENERY_PROP)
        .count();
    assert_eq!(
        baked,
        model(&sod).vertices.len(),
        "the baked child's geometry"
    );

    let scene = scene.drawn_only();
    let mut kept: Vec<u16> = scene.shapes().map(|(id, _)| id).collect();
    kept.sort_unstable();
    assert_eq!(kept, [ACTOR, TREE]);
    let still_baked = scene.world().map_or(0, |w| {
        w.ir.vertices
            .iter()
            .filter(|v| v.scenery_class == SCENERY_PROP)
            .count()
    });
    assert_eq!(
        still_baked, baked,
        "the world keeps the dropped shape's geometry"
    );
}

#[test]
fn a_drawn_only_scene_keeps_its_origin_shape() {
    let film = film([0.0, 0.0, 10.0], &[]);
    let timeline = FilmTimeline::from_bytes(&film).expect("timeline");
    let scene = FilmScene::with_single_model(timeline, model(&fixture("synthetic_minimal.sod")))
        .drawn_only();

    assert_eq!(scene.shapes().count(), 1);
    assert_eq!(scene.frame(0.0).actors.len(), 1);
}
