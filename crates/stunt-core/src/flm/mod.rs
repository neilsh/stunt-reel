//! Native `.FLM` choreography evaluator and parity suite.
//!
//! Evaluates binary `.FLM` film streams into [`crate::contracts::trajectory::TrajectoryRecord`]
//! time-series streams adhering to Seam 2 and Invariants `[I1]`, `[I4]`.

pub mod interpolate;
pub mod parity;
pub mod parser;

pub use interpolate::{
    CAMERA_CUT_DISPLACEMENT_THRESHOLD_METERS, bam_to_radians, detect_camera_cut, evaluate_sub_tick,
    focal_to_fov_y, interpolate_trajectory, lerp_f32, lerp_vec3, quat_from_euler, quat_norm,
    quat_norm_diff, quat_normalize, radians_to_bam, rotate_quat, slerp_quat,
};
pub use parity::{
    GATE_G04_RMSE_THRESHOLD_METERS, assert_parity_gate_g04, build_synthetic_intro_flm,
    compute_position_rmse,
};
pub use parser::{
    FlmParser, SIF_ANIMATES, SIF_DRAW, SIF_EXISTS, SIF_MOVES, SIF_ROTATES, SIF_SHADOW,
    SIFILM_MAX_OBJ, Slice, SlotState,
};

use crate::contracts::trajectory::{ActorTransform, CameraTransform, TrajectoryRecord};
use std::fmt;

/// Camera-space viewing axis that the film's view-slot rotation maps into world space.
///
/// `.FLM` stores each slot's orientation as BAM angles whose rotation maps camera space
/// to world space with `+Z` pointing into the screen, so rotating `+Z` by the view slot's
/// quaternion yields the world-space look direction (docs/SPEC.md § 3.7).
pub const CAMERA_FORWARD: [f32; 3] = [0.0, 0.0, 1.0];

/// Distance in meters from the view slot to its look-at point.
///
/// The film stream stores view orientation as a BAM rotation with no range, so the
/// camera target is an arbitrary point along the rotated forward axis.
pub const CAMERA_LOOKAHEAD_METERS: f32 = 1000.0;

/// Errors that can occur during `.FLM` choreography parsing and evaluation.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum FlmError {
    /// Magic signature mismatch (expected `b"FILM"`).
    InvalidSignature { expected: [u8; 4], actual: [u8; 4] },
    /// The input buffer was smaller than expected.
    UnexpectedEof { expected: usize, actual: usize },
    /// Malformed time slice or unexpected termination.
    InvalidSlice { reason: String },
    /// Unrecognized or invalid opcode in the slice stream.
    InvalidOpcode { opcode: u8, offset: usize },
}

impl fmt::Display for FlmError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::InvalidSignature { expected, actual } => {
                write!(
                    f,
                    "invalid FILM signature: expected {:?}, found {:?}",
                    expected.map(|b| b as char),
                    actual.map(|b| b as char)
                )
            }
            Self::UnexpectedEof { expected, actual } => {
                write!(
                    f,
                    "unexpected EOF: expected at least {expected} bytes, found {actual}"
                )
            }
            Self::InvalidSlice { reason } => {
                write!(f, "invalid slice: {reason}")
            }
            Self::InvalidOpcode { opcode, offset } => {
                write!(
                    f,
                    "invalid FLM opcode 0x{opcode:02X} at byte offset 0x{offset:04X}"
                )
            }
        }
    }
}

impl std::error::Error for FlmError {}

/// State machine evaluator for playing `.FLM` choreography streams.
///
/// Steps through slices and emits continuous [`TrajectoryRecord`] kinematic snapshots.
#[derive(Debug, Clone)]
pub struct FlmPlayer<'a> {
    parser: FlmParser<'a>,
    current_tick: u32,
    slots: [SlotState; SIFILM_MAX_OBJ],
    variables: [u16; 16],
    view_obj: u8,
    max_obj: usize,
    credits: [String; 2],
    last_eye: Option<[f32; 3]>,
    last_view_obj: Option<u8>,
    last_error: Option<FlmError>,
    focal_distance: f32,
    default_camera_target: [f32; 3],
}

/// Type alias for `FlmPlayer` matching alternate naming in specification.
pub type FlmEvaluator<'a> = FlmPlayer<'a>;

impl<'a> FlmPlayer<'a> {
    /// Initialize a new film player from a byte buffer, verifying the `FILM` signature.
    pub fn new(data: &'a [u8]) -> Result<Self, FlmError> {
        let parser = FlmParser::new(data)?;
        Ok(Self {
            parser,
            current_tick: 0,
            slots: std::array::from_fn(|_| SlotState::default()),
            variables: [0; 16],
            view_obj: 0,
            max_obj: 0,
            credits: [String::new(), String::new()],
            last_eye: None,
            last_view_obj: None,
            last_error: None,
            focal_distance: 0.0,
            default_camera_target: [0.0, 0.0, 0.0],
        })
    }

    /// Advance simulation by one discrete tick and return the evaluated [`TrajectoryRecord`].
    ///
    /// Returns `None` when the film stream terminates or if an unrecoverable error occurs.
    pub fn step_tick(&mut self) -> Option<TrajectoryRecord> {
        if self.last_error.is_some() {
            return None;
        }

        let slice_res = self.parser.parse_slice(
            self.current_tick,
            &mut self.slots,
            &mut self.variables,
            &mut self.view_obj,
            &mut self.max_obj,
            &mut self.credits,
        );

        let slice = match slice_res {
            Ok(Some(s)) => s,
            Ok(None) => return None,
            Err(err) => {
                self.last_error = Some(err);
                return None;
            }
        };

        let tick = self.current_tick;
        self.current_tick += 1;

        // Camera evaluation
        let view_idx = self.view_obj as usize;
        let view_slot_active = view_idx < SIFILM_MAX_OBJ && self.slots[view_idx].active;
        let (eye, target) = if view_slot_active {
            let eye = self.slots[view_idx].position_meters();
            let forward = rotate_quat(self.slots[view_idx].rotation_quat(), CAMERA_FORWARD);
            (
                eye,
                [
                    eye[0] + forward[0] * CAMERA_LOOKAHEAD_METERS,
                    eye[1] + forward[1] * CAMERA_LOOKAHEAD_METERS,
                    eye[2] + forward[2] * CAMERA_LOOKAHEAD_METERS,
                ],
            )
        } else {
            ([0.0, 10.0, 50.0], self.default_camera_target)
        };

        let cut = detect_camera_cut(eye, self.last_eye, self.view_obj, self.last_view_obj);
        self.last_eye = Some(eye);
        self.last_view_obj = Some(self.view_obj);

        let fov = if self.focal_distance > 0.0 {
            focal_to_fov_y(self.focal_distance)
        } else {
            45.0
        };

        let roll = if view_slot_active {
            bam_to_radians(self.slots[view_idx].rot_bam[0])
        } else {
            0.0
        };

        let camera = CameraTransform {
            eye,
            target,
            fov_degrees: fov,
            roll_radians: roll,
            cut_from_previous: cut,
        };

        // Active actors evaluation (all active slots except the view_obj camera slot)
        let mut actors = Vec::new();
        for (idx, slot) in self.slots.iter().enumerate() {
            if !slot.active || idx == view_idx {
                continue;
            }

            let actor_id = idx as u32;
            let model_name = slot.model_name.clone().unwrap_or_else(|| {
                if slot.shape_id == 1 || idx == 1 {
                    "FOKKER".to_string()
                } else {
                    format!("ACTOR_{actor_id}")
                }
            });

            let position_meters = slot.position_meters();
            let rotation_quat = slot.rotation_quat();
            let state_mask = if slot.type_flags != 0 {
                slot.type_flags as u16
            } else {
                1
            };

            let joint_angles_bam = if slot.animate != 0 {
                vec![(0, slot.animate)]
            } else {
                Vec::new()
            };

            let mut actor = ActorTransform {
                actor_id,
                model_name,
                shape_id: slot.shape_id,
                world_matrix: [0.0; 16],
                rotation_quat,
                position_meters,
                state_mask,
                joint_angles_bam,
            };
            actor.world_matrix = actor.compute_world_matrix();
            actors.push(actor);
        }

        Some(TrajectoryRecord {
            tick,
            camera,
            actors,
            audio_cues: slice.sound_cues,
        })
    }

    /// Evaluate all remaining slices in the film stream into a continuous sequence of records.
    pub fn evaluate_all(&mut self) -> Result<Vec<TrajectoryRecord>, FlmError> {
        let mut records = Vec::new();
        while let Some(record) = self.step_tick() {
            records.push(record);
        }
        if let Some(err) = self.take_last_error() {
            return Err(err);
        }
        Ok(records)
    }

    /// Current simulation tick count.
    #[inline]
    pub fn current_tick(&self) -> u32 {
        self.current_tick
    }

    /// Active view object slot index driving camera view.
    #[inline]
    pub fn view_obj(&self) -> u8 {
        self.view_obj
    }

    /// Highest active object slot index.
    #[inline]
    pub fn max_obj(&self) -> usize {
        self.max_obj
    }

    /// Internal 16-element timeline variable table.
    #[inline]
    pub fn variables(&self) -> &[u16; 16] {
        &self.variables
    }

    /// Current credits strings `[line1, line2]`.
    #[inline]
    pub fn credits(&self) -> &[String; 2] {
        &self.credits
    }

    /// Access the object slot table.
    #[inline]
    pub fn slots(&self) -> &[SlotState; SIFILM_MAX_OBJ] {
        &self.slots
    }

    /// Override the focal distance scalar (default 0.0 -> 45.0 degrees).
    pub fn set_focal_distance(&mut self, focal: f32) {
        self.focal_distance = focal;
    }

    /// Set camera look-at target coordinate.
    pub fn set_default_camera_target(&mut self, target: [f32; 3]) {
        self.default_camera_target = target;
    }

    /// Assign an explicit `.SOD` model name to an object slot.
    pub fn set_slot_model_name(&mut self, slot_idx: usize, name: impl Into<String>) {
        if slot_idx < SIFILM_MAX_OBJ {
            self.slots[slot_idx].model_name = Some(name.into());
        }
    }

    /// Last recorded parsing error, if any.
    #[inline]
    pub fn last_error(&self) -> Option<&FlmError> {
        self.last_error.as_ref()
    }

    /// Take and clear any recorded parsing error.
    #[inline]
    pub fn take_last_error(&mut self) -> Option<FlmError> {
        self.last_error.take()
    }
}

/// Convenience high-level function: parse and evaluate a full `.FLM` binary buffer.
pub fn evaluate_film(data: &[u8]) -> Result<Vec<TrajectoryRecord>, FlmError> {
    let mut player = FlmPlayer::new(data)?;
    player.evaluate_all()
}
