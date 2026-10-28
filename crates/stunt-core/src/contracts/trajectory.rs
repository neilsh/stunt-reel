//! Seam 2: Kinematic Trajectory & Film Timeline Contract
//!
//! Reference specs: `[fmt flm]`, `[R-FLM-CAM-01]`, `[R-MEM-ACTOR-01]`, `[I4]`
//! Governed by architectural invariants:
//! - `[I1]` Metric right-handed coordinate basis (+Y up, +Z toward viewer, -Z forward)
//! - `[I4]` Decoupled fixed simulation ticks (50 Hz) with sub-tick interpolation

use crate::contracts::palette::PaletteControls;

/// Evaluated camera transform at a discrete simulation tick.
///
/// Coordinates adhere to metric right-handed basis `[I1]`:
/// - `eye`: World position in meters [x, y, z]
/// - `target`: Focus look-at position in meters [x, y, z]
/// - `fov_degrees`: Vertical field of view in degrees
/// - `roll_radians`: View roll angle in radians (BAM conversion)
/// - `lens`: The view camera's zoom word, film variable `view_obj`
/// - `cut_from_previous`: Instantaneous camera cut flag suppressing sub-tick lerp `[I4]`
#[derive(Debug, Clone, Copy, PartialEq)]
#[cfg_attr(feature = "serde", derive(serde::Serialize, serde::Deserialize))]
pub struct CameraTransform {
    /// Camera world position in meters `[x, y, z]` per `[I1]`.
    pub eye: [f32; 3],
    /// Look-at point in meters `[x, y, z]`; `eye - target` is the view direction.
    pub target: [f32; 3],
    /// Vertical field of view in degrees.
    pub fov_degrees: f32,
    /// View roll about the forward axis in radians.
    pub roll_radians: f32,
    /// True when the film cuts here, suppressing sub-tick interpolation `[I4]`.
    #[cfg_attr(feature = "serde", serde(default))]
    pub cut_from_previous: bool,
    /// Zoom word of the view camera: film variable `n` while `view_obj` is `n`
    /// (research/playone-exe/lod.md section 2). It sets [`Self::lens_zoom`].
    #[cfg_attr(feature = "serde", serde(default = "default_camera_lens"))]
    pub lens: u16,
}

/// Lens word `CTRY.FLM` and `INTRO.FLM` give every camera before any zoom.
pub const DEFAULT_CAMERA_LENS: u16 = 8192;

#[cfg(feature = "serde")]
fn default_camera_lens() -> u16 {
    DEFAULT_CAMERA_LENS
}

impl CameraTransform {
    /// PLAYONE's projection zoom for this camera, 1.0 at [`DEFAULT_CAMERA_LENS`].
    ///
    /// Mirrors image `0x120A..0x1226` and `0x12DC`: `lens * 0x7FFF` is shifted left until
    /// bit 30 is set, at most three times; the high word `0x229C` scales the view
    /// matrix's two screen rows as a Q15 factor and the unused shift count `0x229E`
    /// shifts its depth row right (research/playone-exe/lod.md section 2.2). The zoom is
    /// therefore `0x229C / 0x8000 * 2^0x229E`, about `lens / 8192`.
    #[must_use]
    pub fn lens_zoom(&self) -> f32 {
        let mut product = u32::from(self.lens) * 0x7FFF;
        let mut shifts_left = 3;
        while product & 0x4000_0000 == 0 && shifts_left > 0 {
            product <<= 1;
            shifts_left -= 1;
        }
        (product >> 16) as f32 / 32768.0 * f32::from(1u16 << shifts_left)
    }

    /// Vertical field of view for this camera's lens, given `base_fov_degrees` at
    /// [`DEFAULT_CAMERA_LENS`], which it returns exactly. A zero lens keeps the base.
    #[must_use]
    pub fn lens_fov_degrees(&self, base_fov_degrees: f32) -> f32 {
        let default_zoom = Self {
            lens: DEFAULT_CAMERA_LENS,
            ..*self
        }
        .lens_zoom();
        let zoom = self.lens_zoom() / default_zoom;
        if zoom <= 0.0 || self.lens == DEFAULT_CAMERA_LENS {
            return base_fov_degrees;
        }
        let half = (base_fov_degrees.to_radians() / 2.0).tan() / zoom;
        2.0 * half.atan().to_degrees()
    }
}

impl Default for CameraTransform {
    fn default() -> Self {
        Self {
            eye: [0.0, 10.0, 50.0],
            target: [0.0, 0.0, 0.0],
            fov_degrees: 45.0,
            roll_radians: 0.0,
            cut_from_previous: false,
            lens: DEFAULT_CAMERA_LENS,
        }
    }
}

/// Evaluated transform and state for an active actor entity in the scene.
#[derive(Debug, Clone, PartialEq)]
#[cfg_attr(feature = "serde", derive(serde::Serialize, serde::Deserialize))]
pub struct ActorTransform {
    /// Unique actor index within the `.FLM` choreography channel table.
    pub actor_id: u32,
    /// Reference name of the `.SOD` model bound to this actor (e.g. `"FOKKER"`).
    pub model_name: String,
    /// Resource ID of the `.SOD` chunk in the paired `.ALL` archive; `0` when the
    /// slot carries no drawn model.
    #[cfg_attr(feature = "serde", serde(default))]
    pub shape_id: u16,
    /// Unit quaternion rotation `[x, y, z, w]` converted from direction cosines.
    pub rotation_quat: [f32; 4],
    /// World position `[x, y, z]` in meters per `[I1]`.
    pub position_meters: [f32; 3],
    /// Dynamic state bitmask (gear, smoke, visibility, damage state).
    pub state_mask: u16,
    /// Articulated subobject BAM rotation angles `(subobject_id, raw_bam_u16)`.
    #[cfg_attr(feature = "serde", serde(default))]
    pub joint_angles_bam: Vec<(u16, u16)>,
}

impl ActorTransform {
    /// Computes the canonical column-major 4x4 world transformation matrix
    /// from `position_meters` (x, y, z) and unit `rotation_quat` [x, y, z, w].
    pub fn compute_world_matrix(&self) -> [f32; 16] {
        let [qx, qy, qz, qw] = self.rotation_quat;
        let [tx, ty, tz] = self.position_meters;

        let x2 = qx + qx;
        let y2 = qy + qy;
        let z2 = qz + qz;
        let xx = qx * x2;
        let xy = qx * y2;
        let xz = qx * z2;
        let yy = qy * y2;
        let yz = qy * z2;
        let zz = qz * z2;
        let wx = qw * x2;
        let wy = qw * y2;
        let wz = qw * z2;

        [
            1.0 - (yy + zz),
            xy + wz,
            xz - wy,
            0.0,
            xy - wz,
            1.0 - (xx + zz),
            yz + wx,
            0.0,
            xz + wy,
            yz - wx,
            1.0 - (xx + yy),
            0.0,
            tx,
            ty,
            tz,
            1.0,
        ]
    }
}

/// Discrete sound trigger cue emitted by the film stream.
#[derive(Debug, Clone, PartialEq)]
#[cfg_attr(feature = "serde", derive(serde::Serialize, serde::Deserialize))]
pub struct AudioCue {
    /// Authored film tick timestamp when this cue triggers.
    pub tick: u32,
    /// Sound effect asset identifier or filename (e.g. `"ENGINE.VOC"`).
    pub sample_name: String,
    /// Playback volume factor `[0.0, 1.0]`.
    pub volume: f32,
    /// Stereo panning position `[-1.0 (left), 1.0 (right)]`.
    pub pan: f32,
}

/// Complete snapshot of the cinematic world state at 50 Hz tick `t`.
///
/// Implements `Seam 2: TrajectoryRecord` per `docs/ARCHITECTURE.md`.
/// Used as the golden oracle format for `corpus/oracle/intro_trajectory.json`.
#[derive(Debug, Clone, PartialEq)]
#[cfg_attr(feature = "serde", derive(serde::Serialize, serde::Deserialize))]
pub struct TrajectoryRecord {
    /// Cumulative authored 50 Hz tick (`[I4]`, `TIMELINE_HZ`), never a list index or slice ordinal.
    pub tick: u32,
    /// Active camera orientation and projection parameters.
    pub camera: CameraTransform,
    /// Slice of all active actors present and transformed at this tick.
    pub actors: Vec<ActorTransform>,
    /// Sound triggers initiated on this exact tick.
    pub audio_cues: Vec<AudioCue>,
    /// Film variables 13-15 that drive the palette at this tick.
    #[cfg_attr(feature = "serde", serde(default))]
    pub palette: PaletteControls,
}

/// Static prop placed once in the stage at film start.
#[derive(Debug, Clone, PartialEq)]
#[cfg_attr(feature = "serde", derive(serde::Serialize, serde::Deserialize))]
pub struct StaticPropPlacement {
    /// Name of the `.SOD` model placed on the stage.
    pub model_name: String,
    /// World-space placement in meters `[x, y, z]` per `[I1]`.
    pub position_meters: [f32; 3],
    /// Unit quaternion `[x, y, z, w]` giving the prop's orientation.
    pub rotation_quat: [f32; 4],
}

/// Static stage setup and environment metadata for a film sequence.
#[derive(Debug, Clone, PartialEq, Default)]
#[cfg_attr(feature = "serde", derive(serde::Serialize, serde::Deserialize))]
pub struct SceneHeader {
    /// Eight-character film name from the `.FLM` container header.
    pub film_name: String,
    /// VGA palette indices `(zenith, horizon)` used for the sky gradient `[I3]`.
    pub horizon_sky_palette: (u8, u8),
    /// Terrain palette set name, when the film declares one.
    pub terrain_set_name: Option<String>,
    /// Props that never move, placed at film start.
    pub static_props: Vec<StaticPropPlacement>,
}

/// Self-contained kinematic capture of a film containing static stage metadata and all timeline ticks.
#[derive(Debug, Clone, PartialEq)]
#[cfg_attr(feature = "serde", derive(serde::Serialize, serde::Deserialize))]
pub struct FilmCapture {
    /// Stage setup and environment metadata shared by every tick.
    pub header: SceneHeader,
    /// Evaluated records in ascending tick order; each record's `tick` is its cumulative 50 Hz tick.
    pub ticks: Vec<TrajectoryRecord>,
}

#[cfg(test)]
mod tests {
    use super::*;

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
    fn test_camera_transform_default() {
        let cam = CameraTransform::default();
        assert_eq!(cam.eye, [0.0, 10.0, 50.0]);
        assert_eq!(cam.target, [0.0, 0.0, 0.0]);
        assert_eq!(cam.fov_degrees, 45.0);
        assert_eq!(cam.roll_radians, 0.0);
        assert!(!cam.cut_from_previous);
    }

    #[test]
    fn test_compute_world_matrix_identity() {
        let actor = ActorTransform {
            actor_id: 0,
            model_name: "TEST".to_string(),
            shape_id: 0,
            rotation_quat: [0.0, 0.0, 0.0, 1.0], // Identity quaternion
            position_meters: [10.0, 20.0, 30.0],
            state_mask: 0,
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

    #[test]
    fn compute_world_matrix_matches_shared_goldens() {
        let text = include_str!("../../../../tests/fixtures/dos_math_goldens.json");
        let goldens: serde_json::Value = serde_json::from_str(text).expect("valid golden json");
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
}
