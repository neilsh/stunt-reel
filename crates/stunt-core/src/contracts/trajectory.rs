//! Seam 2: Kinematic Trajectory & Film Timeline Contract
//!
//! Reference specs: `[fmt flm]`, `[R-FLM-CAM-01]`, `[R-MEM-ACTOR-01]`, `[I4]`
//! Governed by architectural invariants:
//! - `[I1]` Metric right-handed coordinate basis (+Y up, +Z toward viewer, -Z forward)
//! - `[I4]` Decoupled fixed simulation ticks (20/30 Hz) with sub-tick interpolation

/// Evaluated camera transform at a discrete simulation tick.
///
/// Coordinates adhere to metric right-handed basis `[I1]`:
/// - `eye`: World position in meters [x, y, z]
/// - `target`: Focus look-at position in meters [x, y, z]
/// - `fov_degrees`: Vertical field of view in degrees
/// - `roll_radians`: View roll angle in radians (BAM conversion)
/// - `cut_from_previous`: Instantaneous camera cut flag suppressing sub-tick lerp `[I4]`
#[derive(Debug, Clone, Copy, PartialEq)]
#[cfg_attr(feature = "serde", derive(serde::Serialize, serde::Deserialize))]
pub struct CameraTransform {
    pub eye: [f32; 3],
    pub target: [f32; 3],
    pub fov_degrees: f32,
    pub roll_radians: f32,
    #[cfg_attr(feature = "serde", serde(default))]
    pub cut_from_previous: bool,
}

impl Default for CameraTransform {
    fn default() -> Self {
        Self {
            eye: [0.0, 10.0, 50.0],
            target: [0.0, 0.0, 0.0],
            fov_degrees: 45.0,
            roll_radians: 0.0,
            cut_from_previous: false,
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
    /// 4x4 column-major affine model-to-world transform matrix.
    pub world_matrix: [f32; 16],
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

/// Complete snapshot of the cinematic world state at simulation tick `t`.
///
/// Implements `Seam 2: TrajectoryRecord` per `docs/ARCHITECTURE.md`.
/// Used as the golden oracle format for `corpus/oracle/intro_trajectory.json`.
#[derive(Debug, Clone, PartialEq)]
#[cfg_attr(feature = "serde", derive(serde::Serialize, serde::Deserialize))]
pub struct TrajectoryRecord {
    /// Simulation tick index (advancing at 20 Hz or 30 Hz per `[I4]`).
    pub tick: u32,
    /// Active camera orientation and projection parameters.
    pub camera: CameraTransform,
    /// Slice of all active actors present and transformed at this tick.
    pub actors: Vec<ActorTransform>,
    /// Sound triggers initiated on this exact tick.
    pub audio_cues: Vec<AudioCue>,
}

/// Static prop placed once in the stage at film start.
#[derive(Debug, Clone, PartialEq)]
#[cfg_attr(feature = "serde", derive(serde::Serialize, serde::Deserialize))]
pub struct StaticPropPlacement {
    pub model_name: String,
    pub position_meters: [f32; 3],
    pub rotation_quat: [f32; 4],
}

/// Static stage setup and environment metadata for a film sequence.
#[derive(Debug, Clone, PartialEq)]
#[cfg_attr(feature = "serde", derive(serde::Serialize, serde::Deserialize))]
pub struct SceneHeader {
    pub film_name: String,
    pub tick_rate_hz: u32,
    pub horizon_sky_palette: (u8, u8),
    pub terrain_set_name: Option<String>,
    pub static_props: Vec<StaticPropPlacement>,
}

impl Default for SceneHeader {
    fn default() -> Self {
        Self {
            film_name: String::new(),
            tick_rate_hz: 20,
            horizon_sky_palette: (0, 0),
            terrain_set_name: None,
            static_props: Vec::new(),
        }
    }
}

/// Self-contained kinematic capture of a film containing static stage metadata and all timeline ticks.
#[derive(Debug, Clone, PartialEq)]
#[cfg_attr(feature = "serde", derive(serde::Serialize, serde::Deserialize))]
pub struct FilmCapture {
    pub header: SceneHeader,
    pub ticks: Vec<TrajectoryRecord>,
}

#[cfg(test)]
mod tests {
    use super::*;

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
            world_matrix: [0.0; 16],
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
    fn test_contracts_serde_roundtrip() {
        let record = TrajectoryRecord {
            tick: 42,
            camera: CameraTransform {
                eye: [10.0, 20.0, 30.0],
                target: [0.0, 0.0, 0.0],
                fov_degrees: 60.0,
                roll_radians: 0.1,
                cut_from_previous: true,
            },
            actors: vec![ActorTransform {
                actor_id: 1,
                model_name: "FOKKER".to_string(),
                shape_id: 0x0107,
                world_matrix: [
                    1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 10.0, 20.0, 30.0,
                    1.0,
                ],
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
        };

        let json = serde_json::to_string_pretty(&record).expect("serialization succeeds");
        let deserialized: TrajectoryRecord =
            serde_json::from_str(&json).expect("deserialization succeeds");
        assert_eq!(record, deserialized);

        // Test FilmCapture roundtrip
        let capture = FilmCapture {
            header: SceneHeader {
                film_name: "INTRO".to_string(),
                tick_rate_hz: 30,
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
}
