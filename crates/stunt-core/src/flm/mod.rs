//! Native `.FLM` choreography evaluator and its oracle-trajectory check.
//!
//! Evaluates binary `.FLM` film streams into [`crate::contracts::trajectory::TrajectoryRecord`]
//! time-series streams adhering to Seam 2 and Invariants `[I1]`, `[I4]`.
//!
//! Slots are authored in DOS axes (GLOSSARY.md); [`SlotState::position_meters`] and
//! [`SlotState::rotation_quat`] convert them to `[I1]`, so every evaluated record, camera
//! included, is already `[I1]` and consumers apply no further axis heuristic.

mod interpolate;
mod oracle;
mod parser;
#[cfg(test)]
mod parser_tests;
mod timeline;

pub use oracle::{GATE_G04_RMSE_THRESHOLD_METERS, compute_position_rmse};
use parser::FlmParser;
pub use parser::{
    SIF_ANIMATES, SIF_DRAW, SIF_EXISTS, SIF_MOVES, SIF_ROTATES, SIF_SHADOW, SIFILM_MAX_OBJ,
    SlotState,
};
pub use timeline::{FilmTimeline, SliceKeyframe, TIMELINE_HZ, TIMELINE_TICK_SECONDS};

use interpolate::{bam_to_radians, detect_camera_cut, focal_to_fov_y, rotate_quat};

use crate::contracts::palette::{PALETTE_CONTROL_FULL, PaletteControls};
use crate::contracts::trajectory::{ActorTransform, CameraTransform, TrajectoryRecord};

/// Camera-space viewing axis that the film's view-slot rotation maps into world space.
///
/// `.FLM` stores each slot's orientation as BAM angles whose rotation maps camera space
/// to world space with `+Z` pointing into the screen, so rotating `+Z` by the view slot's
/// `[I1]` quaternion yields the `[I1]` look direction (research/formats/concepts/coordinates-and-units.md). That equals
/// the DOS-axes look direction with the (-x, -y, z) map applied, because the quaternion
/// already carries `q_z180` ([`SlotState::rotation_quat`]).
pub const CAMERA_FORWARD: [f32; 3] = [0.0, 0.0, 1.0];

/// Distance in meters from the view slot to its look-at point.
///
/// The film stream stores view orientation as a BAM rotation with no range, so the
/// camera target is an arbitrary point along the rotated forward axis.
pub const CAMERA_LOOKAHEAD_METERS: f32 = 1000.0;

/// Errors that can occur during `.FLM` choreography parsing and evaluation.
#[derive(Debug, Clone, PartialEq, Eq, thiserror::Error)]
pub enum FlmError {
    /// Magic signature mismatch (expected `b"FILM"`).
    #[error("invalid FILM signature: expected {:?}, found {:?}", .expected.map(|b| b as char), .actual.map(|b| b as char))]
    InvalidSignature {
        /// Signature the parser expected (`b"FILM"`).
        expected: [u8; 4],
        /// Signature bytes found in the stream.
        actual: [u8; 4],
    },
    /// The input buffer was smaller than expected.
    #[error("unexpected EOF: expected at least {expected} bytes, found {actual}")]
    UnexpectedEof {
        /// Buffer length the parse required at the failure point.
        expected: usize,
        /// Buffer length actually available.
        actual: usize,
    },
    /// Malformed time slice or unexpected termination.
    #[error("invalid slice: {reason}")]
    InvalidSlice {
        /// Human-readable description of the malformed slice.
        reason: String,
    },
    /// Unrecognized or invalid opcode in the slice stream.
    #[error("invalid FLM opcode 0x{opcode:02X} at byte offset 0x{offset:04X}")]
    InvalidOpcode {
        /// Opcode byte outside the decoded table.
        opcode: u8,
        /// Byte offset of the opcode within the file.
        offset: usize,
    },
}

/// Film variable 13: the palette's night term (`research/playone-exe/palette-fade.md`).
const VAR_SKY: usize = 13;
/// Film variable 14: palette brightness.
const VAR_BRIGHTNESS: usize = 14;
/// Film variable 15: palette saturation.
const VAR_SATURATION: usize = 15;

/// Film variables before the first slice.
///
/// `PLAYONE` zeroes all 16 at every film start (`CS:0x37AA`), which leaves a film that
/// never sets brightness black (see `research/playone-exe/palette-fade.md`). All but
/// three corpus films set var 14; starting both at full keeps those three visible.
fn initial_variables() -> [u16; 16] {
    let mut variables = [0; 16];
    variables[VAR_BRIGHTNESS] = PALETTE_CONTROL_FULL;
    variables[VAR_SATURATION] = PALETTE_CONTROL_FULL;
    variables
}

/// State machine that decodes `.FLM` slices into per-slice [`TrajectoryRecord`] snapshots.
///
/// Internal feeder for [`FilmTimeline::from_bytes`], the only public way to evaluate a film.
#[derive(Debug, Clone)]
pub(crate) struct FlmPlayer<'a> {
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

impl<'a> FlmPlayer<'a> {
    /// Initialize a new film player from a byte buffer, verifying the `FILM` signature.
    pub(crate) fn new(data: &'a [u8]) -> Result<Self, FlmError> {
        let parser = FlmParser::new(data)?;
        Ok(Self {
            parser,
            current_tick: 0,
            slots: std::array::from_fn(|_| SlotState::default()),
            variables: initial_variables(),
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

    /// Advance to the next authored slice and return its evaluated state plus duration.
    ///
    /// Returns `None` when the film stream terminates or if an unrecoverable error occurs.
    ///
    /// The returned record's `tick` is only the slice ordinal; [`Self::evaluate_timeline`]
    /// rewrites it to the cumulative 50 Hz tick.
    pub(crate) fn step_slice(&mut self) -> Option<(TrajectoryRecord, u8)> {
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

        // Each camera's zoom word is the film variable of its view index (image `0x11FC`
        // reads `[0x4888 + 0x7E + 2 * view_obj]`; research/playone-exe/lod.md section 2).
        let lens = self.variables.get(view_idx).copied().unwrap_or(0);

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
            lens,
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

        Some((
            TrajectoryRecord {
                tick,
                camera,
                actors,
                audio_cues: slice.sound_cues,
                palette: PaletteControls {
                    sky: self.variables[VAR_SKY],
                    brightness: self.variables[VAR_BRIGHTNESS],
                    saturation: self.variables[VAR_SATURATION],
                },
            },
            slice.tick_duration,
        ))
    }

    /// Evaluate all remaining slices into a 50 Hz timeline with authored timestamps.
    ///
    /// A slice decode error ends the walk without failing: the error is kept as the
    /// timeline's [`FilmTimeline::stop_reason`].
    ///
    /// Each record's `tick` is the cumulative `tick_duration` at which that slice is
    /// reached, and its audio cues carry the same authored tick.
    pub(crate) fn evaluate_timeline(&mut self) -> Result<FilmTimeline, FlmError> {
        let mut slices = Vec::new();
        let mut total_ticks = 0u32;

        while let Some((mut record, tick_duration)) = self.step_slice() {
            total_ticks = total_ticks.saturating_add(u32::from(tick_duration));
            record.tick = total_ticks;
            for cue in &mut record.audio_cues {
                cue.tick = total_ticks;
            }
            slices.push(SliceKeyframe {
                record,
                tick: total_ticks,
                tick_duration,
            });
        }

        let timeline = FilmTimeline::new(slices, self.warnings().to_vec());
        Ok(match self.take_last_error() {
            Some(err) => timeline.with_stop_reason(err),
            None => timeline,
        })
    }

    /// Non-fatal inconsistencies encountered while decoding the film stream.
    #[inline]
    pub(crate) fn warnings(&self) -> &[String] {
        self.parser.warnings()
    }

    /// Take and clear any recorded parsing error.
    #[inline]
    pub(crate) fn take_last_error(&mut self) -> Option<FlmError> {
        self.last_error.take()
    }
}

impl From<crate::reader::Eof> for FlmError {
    fn from(e: crate::reader::Eof) -> Self {
        Self::UnexpectedEof {
            expected: e.expected,
            actual: e.actual,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Minimal two-slice synthetic film (`tests/fixtures/synthetic_minimal.flm`).
    const SYNTHETIC_MINIMAL_FLM: &[u8] =
        include_bytes!("../../../../tests/fixtures/synthetic_minimal.flm");

    /// Append one slice with a 3-byte header whose width is all `FlmParser` needs here.
    fn push_slice(film: &mut Vec<u8>, body: &[u8]) {
        film.push(1);
        film.extend_from_slice(&(body.len() as u16).to_le_bytes());
        film.extend_from_slice(body);
    }

    #[test]
    fn synthetic_minimal_fixture_sets_timeline_variable() {
        let mut player = FlmPlayer::new(SYNTHETIC_MINIMAL_FLM).expect("player initialization");

        // Slice 0: var_set 0 = 0x9890, view_obj 0, clear credits, 0xFF
        let (record, _) = player.step_slice().expect("slice 0");
        assert_eq!(player.variables[0], 0x9890);
        // Camera 0's lens is variable 0.
        assert_eq!(record.camera.lens, 0x9890);

        assert!(player.step_slice().is_some());
        assert!(player.step_slice().is_none());
        assert!(player.last_error.is_none());
    }

    #[test]
    fn credits_max_obj_and_variables_follow_control_opcodes() {
        let mut film = Vec::from(&b"FILM"[..]);
        let mut slice0 = Vec::new();

        // 0x9B: max_obj = 5
        slice0.push(0x9B);
        slice0.push(5);

        // 0x99: set credits ("Directed by", "Stunt Island")
        slice0.push(0x99);
        slice0.extend_from_slice(b"Directed by\0");
        slice0.extend_from_slice(b"Stunt Island\0");

        // 0x82: variable 2 = 1234
        slice0.push(0x82);
        slice0.extend_from_slice(&1234u16.to_le_bytes());

        // 0xA2: before word
        slice0.push(0xA2);
        slice0.extend_from_slice(&5678u16.to_le_bytes());

        slice0.push(0xFF);
        push_slice(&mut film, &slice0);

        // Slice 1: 0x98: clear credits
        push_slice(&mut film, &[0x98, 0xFF]);

        let mut player = FlmPlayer::new(&film).unwrap();
        let _t0 = player.step_slice().unwrap();
        assert_eq!(player.max_obj, 5);
        assert_eq!(player.credits[0], "Directed by");
        assert_eq!(player.credits[1], "Stunt Island");
        assert_eq!(player.variables[2], 1234);

        let _t1 = player.step_slice().unwrap();
        assert_eq!(player.credits[0], "");
        assert_eq!(player.credits[1], "");
    }

    #[test]
    fn all_sixteen_timeline_variables_are_addressable() {
        let mut film = Vec::from(&b"FILM"[..]);
        let mut var_body = Vec::new();
        for var_idx in 0..16u8 {
            var_body.push(0x80 | var_idx);
            var_body.extend_from_slice(&((u16::from(var_idx) + 1) * 100).to_le_bytes());
        }
        var_body.push(0xFF);
        push_slice(&mut film, &var_body);

        let mut player = FlmPlayer::new(&film).unwrap();
        let _t = player.step_slice().unwrap();
        for (var_idx, value) in player.variables.iter().enumerate() {
            assert_eq!(*value, (var_idx as u16 + 1) * 100);
        }
    }

    #[test]
    fn palette_variables_reach_records_and_interpolate_between_slices() {
        let mut film = Vec::from(&b"FILM"[..]);
        // Slice 0 sets var 13 = 0x3000 and leaves 14/15 at their full start values.
        push_slice(&mut film, &[0x8D, 0x00, 0x30, 0xFF]);
        // Slice 1, 10 ticks after slice 0 (tick 0), ramps brightness (var 14) to 0 and
        // saturation (var 15) to 0x100.
        film.extend_from_slice(&[7, 0, 10]);
        film.extend_from_slice(&[0x8E, 0x00, 0x00, 0x8F, 0x00, 0x01, 0xFF]);

        let timeline = FilmTimeline::from_bytes(&film).expect("timeline");
        let first = timeline.sample(0.0).expect("sample").palette;
        assert_eq!(
            first,
            PaletteControls {
                sky: 0x3000,
                brightness: PALETTE_CONTROL_FULL,
                saturation: PALETTE_CONTROL_FULL,
            }
        );

        // 2.5 ticks into the 10-tick span: 0x8000 * 0.75 = 0x6000 exactly, and
        // 0x8000 - 0x7F00 * 0.25 = 0x6040.
        let mid = timeline.sample(2.5).expect("sample").palette;
        assert_eq!(mid.sky, 0x3000);
        assert_eq!(mid.brightness, 0x6000);
        assert_eq!(mid.saturation, 0x6040);

        let last = timeline.sample(10.0).expect("sample").palette;
        assert_eq!((last.brightness, last.saturation), (0, 0x100));
    }

    #[test]
    fn decode_error_latches_and_take_clears_it() {
        let mut film = Vec::from(&b"FILM"[..]);
        // Valid slice 0
        push_slice(&mut film, &[0x98, 0xFF]);
        // Corrupted slice 1 (invalid opcode 0xFE)
        push_slice(&mut film, &[0xFE, 0xFF]);

        let mut player = FlmPlayer::new(&film).unwrap();

        // Slice 0 succeeds
        assert!(player.step_slice().is_some());
        assert!(player.last_error.is_none());

        // Slice 1 fails with InvalidOpcode
        assert!(player.step_slice().is_none());
        assert!(matches!(
            player.last_error,
            Some(FlmError::InvalidOpcode { opcode: 0xFE, .. })
        ));

        // Subsequent calls must immediately return None without crashing
        for _ in 0..10 {
            assert!(player.step_slice().is_none());
            assert!(player.last_error.is_some());
        }

        // take_last_error clears it
        assert!(player.take_last_error().is_some());
        assert!(player.last_error.is_none());
    }
}
