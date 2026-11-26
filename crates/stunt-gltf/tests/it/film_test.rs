#![allow(
    clippy::unwrap_used,
    clippy::expect_used,
    clippy::panic,
    clippy::indexing_slicing,
    clippy::unwrap_in_result,
    clippy::missing_asserts_for_indexing,
    clippy::default_trait_access,
    clippy::cast_possible_truncation,
    reason = "integration tests assert by panicking; glTF stores f32"
)]
//! Animated film export, checked by reading the animation back out of the `.glb` bytes.
//!
//! The films are `synthetic_timeline.flm` and timelines built in code; nothing reads `corpus/`.

use std::collections::HashMap;

use serde_json::Value;
use stunt_core::contracts::palette::PaletteControls;
use stunt_core::contracts::{
    ActorTransform, CameraTransform, DEFAULT_CAMERA_LENS, SodModelIr, TrajectoryRecord,
};
use stunt_core::flm::{FilmTimeline, SliceKeyframe};
use stunt_core::scene::FilmScene;
use stunt_gltf::{CUT_EPSILON, FilmExportOptions, GltfError, export_film, summarize};

use crate::export_test::{Glb, fixture, load, model, parse_glb};

fn options(first_tick: u32, last_tick: u32) -> FilmExportOptions {
    FilmExportOptions {
        first_tick,
        last_tick,
        lens_pointer: false,
    }
}

fn index(value: &Value) -> usize {
    usize::try_from(value.as_u64().expect("an index")).unwrap()
}

/// The `(times, values)` of the channel animating `path` of the node named `node`, or `None`
/// when the node has no such channel; values are flattened.
fn channel(glb: &Glb, node: &str, path: &str) -> Option<(Vec<f32>, Vec<f32>, String)> {
    let target = glb
        .array("nodes")
        .iter()
        .position(|n| n["name"] == node)
        .unwrap_or_else(|| panic!("no node {node}"));
    let animation = &glb.array("animations")[0];
    let channel = animation["channels"].as_array().unwrap().iter().find(|c| {
        c["target"]["node"].as_u64() == Some(target as u64) && c["target"]["path"] == path
    })?;
    let sampler = &animation["samplers"][index(&channel["sampler"])];
    Some((
        glb.floats(index(&sampler["input"])),
        glb.floats(index(&sampler["output"])),
        sampler["interpolation"].as_str().unwrap().to_owned(),
    ))
}

fn close(a: f32, b: f32) -> bool {
    (a - b).abs() < 1e-4
}

/// `G06`: across `synthetic_timeline.flm`'s cut at tick 12 the camera's translation holds the
/// pose of tick 2 up to `CUT_EPSILON` before the cut, so no key interpolates through it, and
/// thinning keeps only the corners.
#[test]
fn the_camera_holds_until_the_cut() {
    let scene = load(
        &fixture("synthetic_timeline.flm"),
        &fixture("synthetic_minimal.all"),
    );
    assert_eq!(scene.timeline().total_ticks(), 12, "fixture length");
    let film = export_film(&scene, options(0, 12)).expect("export");
    let glb = parse_glb(&film.bytes);
    let (times, values, interpolation) = channel(&glb, "Camera", "translation").expect("moves");
    assert_eq!(interpolation, "LINEAR", "interpolation");
    let expected_times = [0.0, 0.04, 0.24 - CUT_EPSILON, 0.24];
    assert_eq!(times.len(), expected_times.len(), "keys {times:?}");
    for (t, e) in times.iter().zip(expected_times) {
        assert!(close(*t, e), "time {t} against {e}");
    }
    let eye = |tick: f32| scene.frame(tick).view.eye;
    let expected: Vec<f32> = [eye(0.0), eye(2.0), eye(11.0), eye(12.0)]
        .concat()
        .into_iter()
        .collect();
    assert_eq!(eye(2.0), eye(11.0), "the slice into the cut holds");
    for (v, e) in values.iter().zip(&expected) {
        assert!(close(*v, *e), "value {v} against {e}");
    }
    assert!(film.keys_kept < film.keys_sampled, "thinning dropped keys");
    assert_eq!(
        summarize(&film.bytes).expect("summary").animations,
        1,
        "one animation"
    );
}

/// Every sampler's input strictly increases and carries `min` and `max`, as glTF requires.
#[test]
fn every_input_strictly_increases_and_is_bounded() {
    let scene = load(
        &fixture("synthetic_timeline.flm"),
        &fixture("synthetic_minimal.all"),
    );
    let glb = parse_glb(&export_film(&scene, options(0, 12)).expect("export").bytes);
    let animation = &glb.array("animations")[0];
    for sampler in animation["samplers"].as_array().unwrap() {
        let input = index(&sampler["input"]);
        let times = glb.floats(input);
        assert!(times.windows(2).all(|w| w[0] < w[1]), "{times:?} increases");
        let accessor = &glb.array("accessors")[input];
        assert!(
            accessor["min"].is_array() && accessor["max"].is_array(),
            "bounds"
        );
        let view = &glb.array("bufferViews")[index(&accessor["bufferView"])];
        assert!(
            view.get("target").is_none(),
            "animation views have no target"
        );
    }
}

/// A shorter span starts its clock at its own first tick, and a span past the film is refused.
#[test]
fn a_span_starts_at_zero_and_may_not_pass_the_film() {
    let scene = load(
        &fixture("synthetic_timeline.flm"),
        &fixture("synthetic_minimal.all"),
    );
    let glb = parse_glb(&export_film(&scene, options(1, 5)).expect("export").bytes);
    let (times, ..) = channel(&glb, "Camera", "translation").expect("moves");
    assert!(close(times[0], 0.0), "starts at 0");
    assert!(close(*times.last().unwrap(), 0.08), "ends 4 ticks later");
    for (first, last) in [(0, 13), (5, 4)] {
        let err = export_film(&scene, options(first, last)).expect_err("refused");
        assert!(
            matches!(err, GltfError::TickSpan { total: 12, .. }),
            "{err}"
        );
    }
}

fn record(tick: u32, lens: u16, actors: Vec<ActorTransform>) -> SliceKeyframe {
    SliceKeyframe {
        record: TrajectoryRecord {
            tick,
            camera: CameraTransform {
                eye: [0.0, 10.0, 50.0],
                target: [0.0, 0.0, 0.0],
                lens,
                ..CameraTransform::default()
            },
            actors,
            audio_cues: Vec::new(),
            palette: PaletteControls::default(),
            bank: Default::default(),
        },
        tick,
        tick_duration: 10,
    }
}

fn actor(actor_id: u32, shape_id: u16, x: f32, rotation_quat: [f32; 4]) -> ActorTransform {
    ActorTransform {
        actor_id,
        model_name: String::new(),
        shape_id,
        rotation_quat,
        position_meters: [x, 0.0, 0.0],
        state_mask: 0,
        casts_shadow: false,
        view: false,
        joint_angles_bam: Vec::new(),
    }
}

const IDENTITY: [f32; 4] = [0.0, 0.0, 0.0, 1.0];

/// Slots 1 and 2 drawing shapes 1 and 2 from the synthetic model.
fn scene(slices: Vec<SliceKeyframe>) -> FilmScene {
    let ir = model("synthetic_minimal.sod");
    let shapes: HashMap<u16, SodModelIr> = [(1, ir.clone()), (2, ir)].into_iter().collect();
    FilmScene::new(FilmTimeline::new(slices, Vec::new()), shapes, None)
}

/// An actor in the second slice only, and one that changes shape: a node per slot and shape,
/// each shown by a `STEP` scale channel from the tick the film first draws it.
#[test]
fn actors_appear_leave_and_change_shape_by_scale() {
    let scene = scene(vec![
        record(0, DEFAULT_CAMERA_LENS, vec![actor(1, 1, 0.0, IDENTITY)]),
        record(
            10,
            DEFAULT_CAMERA_LENS,
            vec![actor(1, 2, 5.0, IDENTITY), actor(2, 1, 9.0, IDENTITY)],
        ),
    ]);
    let glb = parse_glb(&export_film(&scene, options(0, 10)).expect("export").bytes);
    // `interpolate_trajectory` switches shape and presence at the slice's midpoint, tick 5.
    let switch = (0..=10u8)
        .find(|&t| scene.frame(f32::from(t)).actors.len() == 2)
        .map(|t| f32::from(t) / 50.0)
        .expect("the second actor appears");
    for (node, shown_first) in [
        ("actor_1_shape_1", true),
        ("actor_1_shape_2", false),
        ("actor_2_shape_1", false),
    ] {
        let (times, values, interpolation) = channel(&glb, node, "scale").expect(node);
        assert_eq!(interpolation, "STEP", "{node}");
        assert_eq!(times.len(), 2, "{node} keys {times:?}");
        assert!(
            close(times[1], switch),
            "{node} switches at {switch}: {times:?}"
        );
        let first = if shown_first { 1.0 } else { 0.0 };
        assert_eq!(&values[..3], &[first; 3], "{node} first");
        assert_eq!(&values[3..], &[1.0 - first; 3], "{node} after");
    }
    // The second actor moves nowhere: its translation channel is left out.
    assert!(
        channel(&glb, "actor_2_shape_1", "translation").is_none(),
        "static"
    );
    let node = glb.node_named("actor_2_shape_1").unwrap();
    assert_eq!(
        node["scale"],
        serde_json::json!([0, 0, 0]),
        "hidden at the start"
    );
}

/// A lens change writes `extras.yfov_keys`; `lens_pointer` adds a `KHR_animation_pointer`
/// channel, an extension used but not required.
#[test]
fn a_lens_change_is_kept_in_extras_and_optionally_animated() {
    let scene = scene(vec![
        record(0, DEFAULT_CAMERA_LENS, Vec::new()),
        record(10, DEFAULT_CAMERA_LENS * 2, Vec::new()),
    ]);
    let plain = parse_glb(&export_film(&scene, options(0, 10)).expect("export").bytes);
    let keys = plain.node_named("Camera").unwrap()["extras"]["yfov_keys"]
        .as_array()
        .expect("yfov keys")
        .clone();
    let yfov = |tick: f32| scene.frame(tick).view.fov_degrees.to_radians();
    let last = keys.last().unwrap();
    assert!(
        close(last[1].as_f64().unwrap() as f32, yfov(10.0)),
        "ends zoomed"
    );
    assert!(
        plain.json.get("extensionsRequired").is_none(),
        "nothing required"
    );
    assert!(
        !plain.json["extensionsUsed"].to_string().contains("pointer"),
        "no pointer without the option"
    );

    let mut with_pointer = options(0, 10);
    with_pointer.lens_pointer = true;
    let glb = parse_glb(&export_film(&scene, with_pointer).expect("export").bytes);
    assert!(
        glb.json["extensionsUsed"]
            .to_string()
            .contains("KHR_animation_pointer"),
        "pointer used"
    );
    assert!(
        glb.json.get("extensionsRequired").is_none(),
        "nothing required"
    );
    let pointer = glb.array("animations")[0]["channels"]
        .as_array()
        .unwrap()
        .iter()
        .find(|c| c["target"]["path"] == "pointer")
        .expect("pointer channel");
    assert_eq!(
        pointer["target"]["extensions"]["KHR_animation_pointer"]["pointer"],
        "/cameras/0/perspective/yfov"
    );
    // No lens change: no extras.
    let still = scene_still();
    let glb = parse_glb(&export_film(&still, options(0, 10)).expect("export").bytes);
    assert!(
        glb.node_named("Camera").unwrap().get("extras").is_none(),
        "no lens keys"
    );
}

fn scene_still() -> FilmScene {
    scene(vec![
        record(0, DEFAULT_CAMERA_LENS, Vec::new()),
        record(10, DEFAULT_CAMERA_LENS, Vec::new()),
    ])
}

/// A rotation authored as `q` then `-q` (the same turn) stays in one hemisphere, so a
/// per-component lerp does not spin the long way round.
#[test]
fn rotations_stay_in_one_hemisphere() {
    let half = std::f32::consts::FRAC_1_SQRT_2;
    let scene = scene(vec![
        record(
            0,
            DEFAULT_CAMERA_LENS,
            vec![actor(1, 1, 0.0, [0.0, half, 0.0, half])],
        ),
        record(
            10,
            DEFAULT_CAMERA_LENS,
            vec![actor(1, 1, 0.0, [0.0, 1.0, 0.0, 0.0])],
        ),
    ]);
    let glb = parse_glb(&export_film(&scene, options(0, 10)).expect("export").bytes);
    let (_, values, _) = channel(&glb, "actor_1_shape_1", "rotation").expect("turns");
    for pair in values.chunks(4).collect::<Vec<_>>().windows(2) {
        let dot: f32 = pair[0].iter().zip(pair[1]).map(|(a, b)| a * b).sum();
        assert!(dot > 0.0, "{pair:?} in one hemisphere");
    }
}
