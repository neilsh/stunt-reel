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
#[derive(Debug, Clone, Copy, PartialEq)]
#[cfg_attr(feature = "serde", derive(serde::Serialize, serde::Deserialize))]
pub struct CameraTransform {
    pub eye: [f32; 3],
    pub target: [f32; 3],
    pub fov_degrees: f32,
    pub roll_radians: f32,
}

impl Default for CameraTransform {
    fn default() -> Self {
        Self {
            eye: [0.0, 10.0, 50.0],
            target: [0.0, 0.0, 0.0],
            fov_degrees: 45.0,
            roll_radians: 0.0,
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
    /// 4x4 column-major affine model-to-world transform matrix.
    pub world_matrix: [f32; 16],
    /// Unit quaternion rotation `[x, y, z, w]` converted from direction cosines.
    pub rotation_quat: [f32; 4],
    /// World position `[x, y, z]` in meters per `[I1]`.
    pub position_meters: [f32; 3],
    /// Dynamic state bitmask (gear, smoke, visibility, damage state).
    pub state_mask: u16,
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
            },
            actors: vec![ActorTransform {
                actor_id: 1,
                model_name: "FOKKER".to_string(),
                world_matrix: [
                    1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 10.0, 20.0, 30.0,
                    1.0,
                ],
                rotation_quat: [0.0, 0.0, 0.0, 1.0],
                position_meters: [10.0, 20.0, 30.0],
                state_mask: 0x0001,
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
    }
}
