//! Film scene assembly and frame sampling through the public [`stunt_core::scene`] interface.
//!
//! Everything is synthetic: fixture SODs and anchors from `tests/fixtures/`, plus
//! hand-built `.FLM` and `.ALL` bytes, so nothing depends on `corpus/`.

mod common;

use std::collections::HashMap;
use std::path::PathBuf;

use common::{ACTOR_RZ_BAM, push_interp};
use stunt_core::contracts::SodModelIr;
use stunt_core::flm::{FilmTimeline, FlmError, SIF_DRAW, SIF_EXISTS, SIF_MOVES, SIF_ROTATES};
use stunt_core::scene::{FilmScene, SceneError, SceneInputs};
use stunt_core::sod::transpile_sod;

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
    let mut body = vec![0x9B, (actors.len() + 1) as u8];
    body.extend_from_slice(&[0x00, SIF_EXISTS | SIF_MOVES | SIF_ROTATES, 0x90]);
    for (i, (shape_id, _)) in actors.iter().enumerate() {
        body.push(1 + i as u8);
        body.push(SIF_EXISTS | SIF_DRAW | SIF_MOVES | SIF_ROTATES);
        body.extend_from_slice(&shape_id.to_le_bytes());
    }
    push_interp(&mut body, 0x40, eye, 0);
    for (i, (_, pos)) in actors.iter().enumerate() {
        push_interp(&mut body, 0x41 + i as u8, *pos, ACTOR_RZ_BAM);
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
    transpile_sod(bytes, "MODEL", None).expect("fixture model")
}

fn scene_inputs(film: &[u8]) -> SceneInputs<'_> {
    SceneInputs {
        film,
        archive: None,
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
        archive: Some(&all),
        ..scene_inputs(&film)
    })
    .expect("load");

    assert!(report.skipped.is_empty());
    assert!(report.partial.is_empty());
    assert!(report.film_stop.is_none());
    assert!(!report.anchors_loaded);
    assert!(report.world.is_none());
    assert!(scene.shape(7).is_some());
    assert_eq!(scene.shapes().count(), 1);

    let frame = scene.frame(0.0);
    assert!(!frame.world);
    assert_eq!(frame.camera.eye, [0.0, 0.0, 10.0]);
    assert_eq!(frame.actors.len(), 2);
    assert!(frame.actors.iter().all(|a| a.shape_id == 7));
    assert_ne!(frame.actors[0].world_matrix, frame.actors[1].world_matrix);
    // Column-major translation lives in elements 12..15.
    assert_eq!(&frame.actors[0].world_matrix[12..15], &[3.0, 0.0, 0.0]);
    assert_eq!(&frame.actors[1].world_matrix[12..15], &[0.0, 4.0, 10.0]);
}

#[test]
fn distance_is_eye_to_actor_position() {
    let film = film(
        [0.0, 0.0, 10.0],
        &[(7, [3.0, 0.0, 10.0]), (7, [0.0, 4.0, 10.0])],
    );
    let all = archive(&[(7, &fixture("synthetic_minimal.sod"))]);
    let (scene, _) = FilmScene::load(&SceneInputs {
        archive: Some(&all),
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
        archive: Some(&all),
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
        archive: Some(&all),
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
        archive: Some(&all),
        ..scene_inputs(&film)
    })
    .expect("load");
    assert!(!report.anchors_loaded);
    assert_eq!(report.partial.len(), 1);
    assert_eq!(report.partial[0].0, 5);
    assert!(scene.shape(5).is_some(), "partial shapes are kept");
    assert_eq!(scene.frame(0.0).actors.len(), 1);

    let anchors = fixture("synthetic_anchors.bin");
    let (_, report) = FilmScene::load(&SceneInputs {
        archive: Some(&all),
        anchors: Some(&anchors),
        ..scene_inputs(&film)
    })
    .expect("load");
    assert!(report.anchors_loaded);
    assert!(report.partial.is_empty());
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
        archive: Some(&[0x05]),
        ..scene_inputs(&film)
    })
    .expect_err("bad archive");
    assert!(matches!(err, SceneError::Archive(_)));
}

#[test]
fn world_is_present_when_anchors_and_map_are_supplied() {
    let film = film([0.0, 0.0, 10.0], &[]);
    let anchors = fixture("synthetic_anchors.bin");
    // One 30-byte MAP.BIN patch: active, color 4, three vertices of the anchor table.
    let mut patch = vec![0u8; 30];
    patch[0..2].copy_from_slice(&1i16.to_le_bytes());
    patch[2..4].copy_from_slice(&0x01FFi16.to_le_bytes());
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
