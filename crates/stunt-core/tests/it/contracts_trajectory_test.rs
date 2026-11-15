//! `contracts::trajectory` contract tests (Seam 2): camera, LOD, world matrices and serde.

use stunt_core::contracts::palette::PaletteControls;
use stunt_core::contracts::trajectory::*;

#[test]
fn lens_zoom_follows_playone_normalisation() {
    let camera = |lens| CameraTransform {
        lens,
        ..CameraTransform::default()
    };
    // 0x229C = 0x7FFF after three shifts, no depth shift.
    assert_eq!(camera(DEFAULT_CAMERA_LENS).lens_zoom(), 32767.0 / 32768.0);
    // One shift: 0x229C = 0x4FFF, depth shifted right twice.
    assert_eq!(camera(20480).lens_zoom(), 20479.0 / 8192.0);
    // No shift: 0x229C = 0x5665, depth shifted right three times.
    assert_eq!(camera(44236).lens_zoom(), 22117.0 / 4096.0);
    assert_eq!(camera(0).lens_zoom(), 0.0);
    // A zoomed lens narrows the field of view; a zero lens keeps it.
    assert_eq!(camera(DEFAULT_CAMERA_LENS).lens_fov_degrees(45.0), 45.0);
    let narrow = camera(44236).lens_fov_degrees(45.0);
    assert!((narrow - 8.77).abs() < 0.01, "{narrow}");
    assert_eq!(camera(0).lens_fov_degrees(45.0), 45.0);
}

#[test]
fn lod_lens_words_follow_playone_normalisation() {
    let camera = |lens| CameraTransform {
        lens,
        ..CameraTransform::default()
    };
    // 0x22A4 = (0x229C * 0xFFFF * 2) >> 16 at full detail; 0x229E is the shifts left over.
    assert_eq!(camera(DEFAULT_CAMERA_LENS).lod_lens_words(), (0xFFFD, 0));
    assert_eq!(camera(20480).lod_lens_words(), (0x9FFD, 2));
    assert_eq!(camera(44236).lod_lens_words(), (0xACC9, 3));
}

#[test]
fn lod_keeps_subtree_compares_halved_shifted_depth() {
    // Looking down -z from the origin; node 1000 m ahead, ext 400 (half 200), split 600:
    // the threshold is 200 + (400 * 0xFFFD >> 16) = 599.
    let camera = |lens| CameraTransform {
        eye: [0.0, 0.0, 0.0],
        target: [0.0, 0.0, -1.0],
        lens,
        ..CameraTransform::default()
    };
    let at = |depth: f32| [0.0, 0.0, -depth];
    let default = camera(DEFAULT_CAMERA_LENS);
    // Depth is halved: 1198 m reads 599, 1200 m reads 600.
    assert!(default.lod_keeps_subtree(at(1198.0), 400, 600));
    assert!(!default.lod_keeps_subtree(at(1200.0), 400, 600));
    // A split under half the extent is the threshold itself.
    assert!(default.lod_keeps_subtree(at(200.0), 400, 100));
    assert!(!default.lod_keeps_subtree(at(204.0), 400, 100));
    // Lens 44236 shifts depth right three more times and scales the span by 0xACC9:
    // 200 + (400 * 0xACC9 >> 16) = 469, so the subtree holds to 470 * 16 = 7520 m.
    let zoomed = camera(44236);
    assert!(zoomed.lod_keeps_subtree(at(7519.0), 400, 600));
    assert!(!zoomed.lod_keeps_subtree(at(7520.0), 400, 600));
    // A node behind the eye is near.
    assert!(default.lod_keeps_subtree(at(-5000.0), 400, 600));
}

#[test]
fn view_depth_exceeds_compares_halved_shifted_depth() {
    let camera = |lens| CameraTransform {
        eye: [0.0, 0.0, 0.0],
        target: [0.0, 0.0, -1.0],
        lens,
        ..CameraTransform::default()
    };
    let at = |depth: f32| [3.0, 4.0, -depth];
    // Default lens: depth halved, so a 50 m threshold is passed beyond 100 m.
    let default = camera(DEFAULT_CAMERA_LENS);
    assert!(!default.view_depth_exceeds(at(100.0), 50.0));
    assert!(default.view_depth_exceeds(at(100.5), 50.0));
    // Lens 44236 shifts three more times: beyond 800 m.
    let zoomed = camera(44236);
    assert!(!zoomed.view_depth_exceeds(at(800.0), 50.0));
    assert!(zoomed.view_depth_exceeds(at(801.0), 50.0));
    // A point behind the eye is near.
    assert!(!default.view_depth_exceeds(at(-500.0), 50.0));
    // No view direction: the far section is kept.
    let blind = CameraTransform {
        eye: [0.0; 3],
        target: [0.0; 3],
        ..CameraTransform::default()
    };
    assert!(blind.view_depth_exceeds(at(1.0), 50.0));
}

#[test]
fn test_camera_transform_default() {
    let cam = CameraTransform::default();
    assert_eq!(cam.eye, [0.0, 10.0, 50.0]);
    assert_eq!(cam.target, [0.0, 0.0, 0.0]);
    assert_eq!(cam.fov_degrees.to_bits(), PLAYONE_FOV_Y_DEGREES.to_bits());
    assert_eq!(cam.roll_radians, 0.0);
    assert!(!cam.cut_from_previous);
}

#[test]
fn playone_fov_is_a_256_pixel_focal_length_over_100_rows() {
    let focal_px = 100.0 / (PLAYONE_FOV_Y_DEGREES.to_radians() / 2.0).tan();
    assert!((focal_px - 256.0).abs() < 1e-3, "focal {focal_px}");
}

/// An unrotated actor's world matrix is the identity rotation plus its position.
#[test]
fn test_compute_world_matrix_identity() {
    let actor = ActorTransform {
        actor_id: 0,
        model_name: "TEST".to_string(),
        shape_id: 0,
        rotation_quat: [0.0, 0.0, 0.0, 1.0], // Identity quaternion
        position_meters: [10.0, 20.0, 30.0],
        state_mask: 0,
        casts_shadow: false,
        joint_angles_bam: Vec::new(),
    };

    let matrix = actor.compute_world_matrix();
    let expected = [
        1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 10.0, 20.0, 30.0, 1.0,
    ];
    assert_eq!(matrix, expected);
}

#[cfg(feature = "serde")]
#[test]
fn test_scene_header_ignores_legacy_tick_rate_hz() {
    let json = r#"{
        "film_name": "INTRO",
        "tick_rate_hz": 20,
        "horizon_sky_palette": [12, 45],
        "terrain_set_name": null,
        "static_props": []
    }"#;
    let header: SceneHeader = serde_json::from_str(json).expect("legacy header still loads");
    assert_eq!(header.film_name, "INTRO");
    assert_eq!(header.horizon_sky_palette, (12, 45));
}

/// A trajectory record survives a JSON round trip unchanged.
#[cfg(feature = "serde")]
#[test]
fn test_contracts_serde_roundtrip() {
    let record = TrajectoryRecord {
        tick: 42,
        camera: CameraTransform {
            eye: [10.0, 20.0, 30.0],
            target: [0.0, 0.0, 0.0],
            fov_degrees: 60.0,
            roll_radians: 0.1,
            cut_from_previous: true,
            lens: 20480,
        },
        actors: vec![ActorTransform {
            actor_id: 1,
            model_name: "FOKKER".to_string(),
            shape_id: 0x0107,
            rotation_quat: [0.0, 0.0, 0.0, 1.0],
            position_meters: [10.0, 20.0, 30.0],
            state_mask: 0x0001,
            casts_shadow: false,
            joint_angles_bam: vec![(0, 0x4000)],
        }],
        audio_cues: vec![AudioCue {
            tick: 42,
            sample_name: "ENGINE.VOC".to_string(),
            volume: 0.8,
            pan: 0.0,
        }],
        palette: PaletteControls {
            sky: 0x2000,
            brightness: 0x4000,
            saturation: 0x8000,
        },
    };

    let json = serde_json::to_string_pretty(&record).expect("serialization succeeds");
    let deserialized: TrajectoryRecord =
        serde_json::from_str(&json).expect("deserialization succeeds");
    assert_eq!(record, deserialized);

    // Test FilmCapture roundtrip
    let capture = FilmCapture {
        header: SceneHeader {
            film_name: "INTRO".to_string(),
            horizon_sky_palette: (12, 45),
            terrain_set_name: Some("ISLAND".to_string()),
            static_props: vec![StaticPropPlacement {
                model_name: "HANGAR".to_string(),
                position_meters: [100.0, 0.0, 200.0],
                rotation_quat: [0.0, 0.0, 0.0, 1.0],
            }],
        },
        ticks: vec![record],
    };
    let cap_json = serde_json::to_string(&capture).expect("capture serialization succeeds");
    let cap_deserialized: FilmCapture =
        serde_json::from_str(&cap_json).expect("capture deserialization succeeds");
    assert_eq!(capture, cap_deserialized);
}

/// World matrices match the DOS-math goldens in `tests/fixtures/dos_math_goldens.json`.
#[test]
fn compute_world_matrix_matches_shared_goldens() {
    let text = include_str!("../../../../tests/fixtures/dos_math_goldens.json");
    let goldens: serde_json::Value = serde_json::from_str(text).expect("valid golden json");
    #[expect(
        clippy::cast_possible_truncation,
        reason = "the goldens are f32 values written out as JSON numbers"
    )]
    let floats = |v: &serde_json::Value| -> Vec<f32> {
        v.as_array()
            .expect("array")
            .iter()
            .map(|x| x.as_f64().expect("number") as f32)
            .collect()
    };

    for (case_index, case) in goldens["world_matrix"]
        .as_array()
        .expect("section")
        .iter()
        .enumerate()
    {
        let pos = floats(&case["position"]);
        let quat = floats(&case["quat"]);
        let expected = floats(&case["expected"]);
        let actor = ActorTransform {
            actor_id: 0,
            model_name: "GOLDEN".to_string(),
            shape_id: 0,
            rotation_quat: [quat[0], quat[1], quat[2], quat[3]],
            position_meters: [pos[0], pos[1], pos[2]],
            state_mask: 0,
            casts_shadow: false,
            joint_angles_bam: Vec::new(),
        };
        let actual = actor.compute_world_matrix();
        for i in 0..16 {
            assert!(
                (actual[i] - expected[i]).abs() <= 1e-5,
                "case {case_index} element {i}: rust {} vs golden {}",
                actual[i],
                expected[i]
            );
        }
    }
}
