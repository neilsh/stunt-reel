//! `.FLM` decode state and per-slice evaluation.
//!
//! One player owns the film's decode state - the byte walk, the object slots, the film
//! variables and the active view slot - so each slice leaves it evaluated and stamped
//! with the cumulative 50 Hz tick at which that slice is reached.
//! [`FilmTimeline::from_bytes`](super::timeline::FilmTimeline::from_bytes) is the only
//! caller, so the byte walk lives beside the state it mutates instead of behind a
//! second object.

use super::interpolate::{
    bam_to_radians, detect_camera_cut, focal_to_fov_y, quat_from_euler, rotate_quat,
};
use super::timeline::SliceKeyframe;
use super::{CAMERA_FORWARD, CAMERA_LOOKAHEAD_METERS, FlmError};
use crate::contracts::palette::PaletteControls;
use crate::contracts::trajectory::{
    ActorTransform, AudioCue, BankVariables, CameraTransform, PLAYONE_FOV_Y_DEGREES,
    TrajectoryRecord,
};
use crate::credits::{CreditLines, CreditsChange};
use crate::reader::ByteReader;

/// Object slot flags from `sifilm.h`.
/// Slot flag: the object slot is allocated and participates in the scene.
pub const SIF_EXISTS: u8 = 0x01;
/// Slot flag: the object is rendered this tick.
pub const SIF_DRAW: u8 = 0x02;
/// Slot flag: the object casts a ground shadow.
pub const SIF_SHADOW: u8 = 0x04;
/// Slot flag: the slot's position is animated.
pub const SIF_MOVES: u8 = 0x08;
/// Slot flag: the slot's orientation is animated.
pub const SIF_ROTATES: u8 = 0x10;
/// Slot flag: the slot carries a raw per-slice animation input.
pub const SIF_ANIMATES: u8 = 0x20;

/// Maximum number of object slots addressable in `.FLM` opcodes (6-bit index).
pub const SIFILM_MAX_OBJ: usize = 64;

/// Internal simulation state for an entity slot in the `.FLM` timeline.
#[derive(Debug, Clone, PartialEq, Eq, Default)]
pub struct SlotState {
    /// Whether the slot currently holds a live object.
    pub active: bool,
    /// `SIF_*` flag byte describing what the slot draws and animates.
    pub type_flags: u8,
    /// Shape/model table index the slot instantiates.
    pub shape_id: u16,
    /// Resolved model name, once the shape table maps `shape_id`.
    pub model_name: Option<String>,
    /// Position as 16.16 fixed-point `[x, y, z]` in engine units.
    pub pos_fixed: [i32; 3],
    /// Orientation as binary-angle units in BAM order `[rz, rx, ry]`.
    pub rot_bam: [u16; 3],
    /// Raw 16-bit animation input; mapping to SOD resource selection is unresolved.
    pub animate: u16,
}

/// Map a position from DOS axes to `[I1]`: a 180° rotation about Z, `(x, y, z) -> (-x, -y, z)`.
///
/// DOS axes are the raw frame of `.FLM` slots and anchor points (GLOSSARY.md "DOS axes").
/// The same rule terrain applies to anchor points (research/formats/auxiliary/map.md).
#[inline]
pub(crate) fn dos_to_i1_position(p: [f32; 3]) -> [f32; 3] {
    // `+ 0.0` turns the `-0.0` produced by negating zero back into `0.0`.
    [-p[0] + 0.0, -p[1] + 0.0, p[2]]
}

/// Map an orientation `[x, y, z, w]` from DOS axes to `[I1]`: `q' = q_z180 * q`.
///
/// `q_z180 = [0, 0, 1, 0]` is the 180° rotation about Z that maps DOS positions to `[I1]`
/// (see `dos_to_i1_position`), so `rotate(q', v) == rz180(rotate(q, v))` for every `v`.
/// The product expands to `(-y, x, w, -z)`; since `q` and `-q` are the same rotation, the
/// result is returned with `w >= 0` so a DOS yaw of 180° about Z evaluates to the identity
/// `[0, 0, 0, 1]` rather than `[0, 0, 0, -1]`.
#[inline]
pub(crate) fn dos_to_i1_quat(q: [f32; 4]) -> [f32; 4] {
    let [x, y, z, w] = q;
    let mut out = [-y + 0.0, x + 0.0, w + 0.0, -z + 0.0];
    if out[3] < 0.0 {
        out = [-out[0] + 0.0, -out[1] + 0.0, -out[2] + 0.0, -out[3] + 0.0];
    }
    out
}

/// Map an actor orientation `[x, y, z, w]` from DOS axes to `[I1]`: the conjugate
/// `q' = q_z180 * q * q_z180^-1 = (-x, -y, z, w)`.
///
/// A shape's vertices are decoded already in `[I1]` (+Y up: wheels at the bottom), while its
/// slot rotation acts in DOS axes, so the rotation is carried into `[I1]` on both sides.
/// Left-multiplying alone (`dos_to_i1_quat`, right for the view) rolls every shape 180°
/// about Z, upside down and mirrored (`INTRO.FLM` tick 1009: the triplane's stacked wings sank
/// below the ground; research/parity/framing-and-actors.md § 1).
#[inline]
pub(crate) fn dos_to_i1_actor_quat(q: [f32; 4]) -> [f32; 4] {
    let [x, y, z, w] = q;
    [-x + 0.0, -y + 0.0, z, w]
}

impl SlotState {
    /// Slot position as 16.16 fixed-point converted to meters, still in DOS axes.
    #[inline]
    #[must_use]
    pub fn position_dos_meters(&self) -> [f32; 3] {
        [
            self.pos_fixed[0] as f32 / 65536.0,
            self.pos_fixed[1] as f32 / 65536.0,
            self.pos_fixed[2] as f32 / 65536.0,
        ]
    }

    /// Slot BAM rotation `[rz, rx, ry]` as a unit quaternion, still in DOS axes.
    ///
    /// This is `PLAYONE.EXE`'s matrix builder `0824:04E5`, `Ry(-ry) * Rx(rx) * Rz(rz)` on
    /// column vectors; `rx` is negated because `quat_from_euler` turns by `-pitch`
    /// (research/formats/concepts/coordinates-and-units.md § 3.4).
    #[must_use]
    pub fn rotation_quat_dos(&self) -> [f32; 4] {
        if self.rot_bam == [0, 0, 0] {
            [0.0, 0.0, 0.0, 1.0]
        } else {
            let rz_rad = bam_to_radians(self.rot_bam[0]);
            let rx_rad = bam_to_radians(self.rot_bam[1]);
            let ry_rad = bam_to_radians(self.rot_bam[2]);
            quat_from_euler(ry_rad, -rx_rad, rz_rad)
        }
    }

    /// Slot position in right-handed metric meters `[I1]`: the DOS-axes position through
    /// `dos_to_i1_position`. This is the single place the evaluator converts positions.
    #[inline]
    #[must_use]
    pub fn position_meters(&self) -> [f32; 3] {
        dos_to_i1_position(self.position_dos_meters())
    }

    /// Slot orientation as a unit quaternion in `[I1]`: the DOS-axes rotation through
    /// `dos_to_i1_quat`. This is the single place the evaluator converts orientations.
    ///
    /// A zero rotation evaluates to `q_z180 = [0, 0, 1, 0]`, not the identity.
    #[must_use]
    pub fn rotation_quat(&self) -> [f32; 4] {
        dos_to_i1_quat(self.rotation_quat_dos())
    }

    /// Orientation of the shape this slot draws, in `[I1]`: the DOS-axes rotation through
    /// `dos_to_i1_actor_quat`. A zero rotation evaluates to the identity.
    #[must_use]
    pub fn actor_rotation_quat(&self) -> [f32; 4] {
        dos_to_i1_actor_quat(self.rotation_quat_dos())
    }
}

/// Film variable 10: the angle bank's part phase (`research/playone-exe/angle-bank.md`).
const VAR_BANK_PHASE: usize = 10;
/// Film variable 12: the angle bank's words `0x18` and `0x1A`.
const VAR_BANK_TILT: usize = 12;
/// Film variable 13: the palette's night term (`research/playone-exe/palette-fade.md`).
const VAR_SKY: usize = 13;
/// Film variable 14: palette brightness.
const VAR_BRIGHTNESS: usize = 14;
/// Film variable 15: palette saturation.
const VAR_SATURATION: usize = 15;

/// Film variables before the first slice.
///
/// `PLAYONE` zeroes all 16 at every film start (`CS:0x37AA`), so the scene stays black until
/// the film first keys brightness (var 14): `INTRO.FLM`'s first title card, keyed at tick
/// 760, and the three corpus films that never key it (`research/playone-exe/palette-fade.md`).
fn initial_variables() -> [u16; 16] {
    [0; 16]
}

/// One slice decoded from the stream, before its slots are evaluated.
struct DecodedSlice {
    /// Slice duration in simulation ticks.
    tick_duration: u8,
    /// Sound events triggered while this slice runs, stamped with the slice's tick.
    sound_cues: Vec<AudioCue>,
    /// Credits set or cleared in this slice, kept apart until the slice decodes whole.
    credits: Vec<CreditsChange>,
}

/// State machine that walks and evaluates `.FLM` slices at their authored ticks.
///
/// The player owns the film's decode state: the byte reader, the back-pointer chain, the
/// object slots, the 16 film variables and the active view slot. It stamps each slice
/// once, adding the authored `tick_duration` before walking the slice's opcodes, so a
/// returned [`SliceKeyframe`]'s record and cues already carry the cumulative 50 Hz tick.
///
/// Internal feeder for [`FilmTimeline::from_bytes`](super::timeline::FilmTimeline::from_bytes),
/// the only public way to evaluate a film.
#[derive(Debug, Clone)]
pub(crate) struct FlmPlayer<'a> {
    reader: ByteReader<'a>,
    /// Length of the most recently decoded slice, used to validate the back-pointer chain.
    last_slice_len: Option<usize>,
    /// Non-fatal stream inconsistencies, such as a broken `prev_slice_len` chain.
    warnings: Vec<String>,
    /// Cumulative authored tick at which the next returned slice is reached.
    current_tick: u32,
    slots: [SlotState; SIFILM_MAX_OBJ],
    variables: [u16; 16],
    view_obj: u8,
    last_view_obj: Option<u8>,
    last_error: Option<FlmError>,
    focal_distance: f32,
    default_camera_target: [f32; 3],
    /// Every `0x99` set and `0x98` clear so far, in film order.
    credits: Vec<CreditsChange>,
}

impl<'a> FlmPlayer<'a> {
    /// Initialize a new film player from a byte buffer, verifying the `FILM` signature.
    pub(crate) fn new(data: &'a [u8]) -> Result<Self, FlmError> {
        let &sig = data.first_chunk::<4>().ok_or(FlmError::UnexpectedEof {
            expected: 4,
            actual: data.len(),
        })?;
        if &sig != b"FILM" {
            return Err(FlmError::InvalidSignature {
                expected: *b"FILM",
                actual: sig,
            });
        }
        Ok(Self {
            reader: ByteReader::at(data, 4),
            last_slice_len: None,
            warnings: Vec::new(),
            current_tick: 0,
            slots: std::array::from_fn(|_| SlotState::default()),
            variables: initial_variables(),
            view_obj: 0,
            last_view_obj: None,
            last_error: None,
            focal_distance: 0.0,
            default_camera_target: [0.0, 0.0, 0.0],
            credits: Vec::new(),
        })
    }

    /// Decode and evaluate the next authored slice.
    ///
    /// Returns `None` at the film's epilogue or once a decode error has been latched;
    /// [`Self::take_last_error`] then reports why the walk stopped. The returned
    /// keyframe's record and audio cues carry the cumulative 50 Hz tick at which the
    /// slice is reached.
    pub(crate) fn step_slice(&mut self) -> Option<SliceKeyframe> {
        if self.last_error.is_some() {
            return None;
        }

        let decoded = match self.decode_slice() {
            Ok(Some(decoded)) => decoded,
            Ok(None) => return None,
            Err(err) => {
                self.last_error = Some(err);
                return None;
            }
        };

        let DecodedSlice {
            tick_duration,
            sound_cues,
            credits,
        } = decoded;
        self.credits.extend(credits);
        let tick = self.current_tick;
        let record = self.evaluate_slice(sound_cues);
        Some(SliceKeyframe {
            record,
            tick,
            tick_duration,
        })
    }

    /// Non-fatal inconsistencies encountered while decoding the film stream.
    #[inline]
    pub(crate) fn warnings(&self) -> &[String] {
        &self.warnings
    }

    /// Take the credits changes decoded so far.
    #[inline]
    pub(crate) fn take_credits(&mut self) -> Vec<CreditsChange> {
        std::mem::take(&mut self.credits)
    }

    /// Take and clear any recorded parsing error.
    #[inline]
    pub(crate) fn take_last_error(&mut self) -> Option<FlmError> {
        self.last_error.take()
    }

    /// Walk one slice's bytes, advancing the cumulative tick by its authored duration.
    ///
    /// Returns `None` at end of stream or at the header-only epilogue.
    fn decode_slice(&mut self) -> Result<Option<DecodedSlice>, FlmError> {
        if !self.has_more() {
            return Ok(None);
        }

        let slice_start = self.reader.pos();
        let prev_slice_len = self.read_u16_le()?;
        let tick_duration = self.read_u8()?;

        // A film ends with a header-only epilogue: the final slice's length followed by
        // the `0xFF` end-of-stream marker (`0x00` in a few corpus films). Some films
        // append filler after the marker, so `0xFF` - never an authored duration in the
        // 627,696-slice corpus, whose maximum is `0x7F` - also ends the stream.
        if self.reader.pos() == self.reader.len() || tick_duration == 0xFF {
            if let Some(last_len) = self.last_slice_len
                && prev_slice_len as usize != last_len
            {
                self.warnings.push(format!(
                    "end-of-film epilogue at 0x{slice_start:04X} has prev_slice_len {prev_slice_len} (expected {last_len})"
                ));
            }
            self.reader.set_pos(self.reader.len());
            return Ok(None);
        }

        if let Some(last_len) = self.last_slice_len
            && prev_slice_len as usize != last_len
        {
            self.warnings.push(format!(
                "slice at 0x{slice_start:04X} has prev_slice_len {prev_slice_len} (expected {last_len})"
            ));
        }

        // The authored duration is the slice's distance from the previous one. Add it
        // once, before reading the opcodes, so every cue and the record it produces
        // carry the same cumulative tick.
        self.current_tick = self
            .current_tick
            .checked_add(u32::from(tick_duration))
            .ok_or_else(|| FlmError::InvalidSlice {
                reason: "cumulative tick count overflows u32".to_string(),
            })?;

        let mut sound_cues = Vec::new();
        let mut credits = Vec::new();

        loop {
            if self.reader.pos() >= self.reader.len() {
                return Err(FlmError::InvalidSlice {
                    reason: format!(
                        "slice starting at offset 0x{slice_start:04X} ended abruptly without 0xFF terminator"
                    ),
                });
            }

            let op_offset = self.reader.pos();
            let c = self.read_u8()?;

            if c == 0xFF {
                // Slice terminator
                break;
            }

            let top = c >> 6;
            let slot_idx = (c & 0x3F) as usize;

            match top {
                0 => {
                    // Group 0: CREATE slot. Read every operand before touching the slot,
                    // because the reads borrow the player that also owns the slots.
                    let type_flags = self.read_u8()?;
                    let active = (type_flags & SIF_EXISTS) != 0;
                    let mut shape_id = None;
                    let mut static_position = None;
                    let mut static_rotation = None;

                    if active {
                        if (type_flags & SIF_DRAW) != 0 {
                            shape_id = Some(self.read_u16_le()?);
                        }
                        if (type_flags & SIF_MOVES) == 0 {
                            let x = self.read_i32_le()?;
                            let y = self.read_i32_le()?;
                            let z = self.read_i32_le()?;
                            static_position = Some([x, y, z]);
                        }
                        if (type_flags & SIF_ROTATES) == 0 {
                            let rz = self.read_u16_le()?;
                            let rx = self.read_u16_le()?;
                            let ry = self.read_u16_le()?;
                            static_rotation = Some([rz, rx, ry]);
                        }
                    }

                    let slot = self.slot_mut(slot_idx, c, op_offset)?;
                    slot.type_flags = type_flags;
                    slot.active = active;
                    if let Some(shape_id) = shape_id {
                        slot.shape_id = shape_id;
                    }
                    if let Some(position) = static_position {
                        slot.pos_fixed = position;
                    }
                    if let Some(rotation) = static_rotation {
                        slot.rot_bam = rotation;
                    }
                }
                1 => {
                    // Group 1: INTERP slot
                    let flags = self.slot_mut(slot_idx, c, op_offset)?.type_flags;
                    let mut position = None;
                    let mut rotation = None;
                    let mut animate = None;

                    if (flags & SIF_MOVES) != 0 {
                        let x = self.read_i32_le()?;
                        let y = self.read_i32_le()?;
                        let z = self.read_i32_le()?;
                        position = Some([x, y, z]);
                    }
                    if (flags & SIF_ROTATES) != 0 {
                        let rz = self.read_u16_le()?;
                        let rx = self.read_u16_le()?;
                        let ry = self.read_u16_le()?;
                        rotation = Some([rz, rx, ry]);
                    }
                    if (flags & SIF_ANIMATES) != 0 {
                        animate = Some(self.read_u16_le()?);
                    }

                    let slot = self.slot_mut(slot_idx, c, op_offset)?;
                    if let Some(position) = position {
                        slot.pos_fixed = position;
                    }
                    if let Some(rotation) = rotation {
                        slot.rot_bam = rotation;
                    }
                    if let Some(animate) = animate {
                        slot.animate = animate;
                    }
                    slot.active = true;
                }
                2 => {
                    // Group 2: MISC Controls
                    if c < 0x90 {
                        let var_idx = (c & 0x0F) as usize;
                        let val = self.read_u16_le()?;
                        *self
                            .variables
                            .get_mut(var_idx)
                            .ok_or(FlmError::InvalidOpcode {
                                opcode: c,
                                offset: op_offset,
                            })? = val;
                    } else if c < 0x98 {
                        self.view_obj = c & 0x0F;
                    } else if c == 0x98 {
                        credits.push(CreditsChange {
                            tick: self.current_tick,
                            lines: None,
                        });
                    } else if c == 0x99 {
                        let first = self.read_cstring()?;
                        let second = self.read_cstring()?;
                        credits.push(CreditsChange {
                            tick: self.current_tick,
                            lines: Some(CreditLines::new(first, second)),
                        });
                    } else if c == 0x9B {
                        // `max_obj` bounds the original engine's slot scan, not this one.
                        self.read_u8()?;
                    } else if c == 0x9C {
                        let sample_id = self.read_u8()?;
                        let param = self.read_u16_le()?;

                        let sample_name = match sample_id {
                            0 | 1 => "ENGINE.VOC".to_string(),
                            2 => "WIND.VOC".to_string(),
                            3 => "FLYBY.VOC".to_string(),
                            other => format!("SOUND_{other:02X}.VOC"),
                        };

                        let volume = if param != 0 && (param >> 8) != 0 {
                            f32::from(param >> 8) / 255.0
                        } else {
                            0.8
                        };

                        let pan = if param != 0 && (param & 0xFF) != 0 {
                            (f32::from(param & 0xFF) - 128.0) / 128.0
                        } else {
                            0.0
                        };

                        sound_cues.push(AudioCue {
                            tick: self.current_tick,
                            sample_name,
                            volume,
                            pan,
                        });
                    } else if c >= 0xA0 {
                        // Before-state word (prior variable value)
                        self.read_u16_le()?;
                    } else {
                        return Err(FlmError::InvalidOpcode {
                            opcode: c,
                            offset: op_offset,
                        });
                    }
                }
                _ => {
                    return Err(FlmError::InvalidOpcode {
                        opcode: c,
                        offset: op_offset,
                    });
                }
            }
        }

        let slice_len =
            self.reader
                .pos()
                .checked_sub(slice_start)
                .ok_or_else(|| FlmError::InvalidSlice {
                    reason: "reader moved before the slice start".to_string(),
                })?;
        self.last_slice_len = Some(slice_len);

        Ok(Some(DecodedSlice {
            tick_duration,
            sound_cues,
            credits,
        }))
    }

    /// The slot an opcode addresses; `c` and `offset` name the opcode in the error.
    fn slot_mut(&mut self, idx: usize, c: u8, offset: usize) -> Result<&mut SlotState, FlmError> {
        self.slots
            .get_mut(idx)
            .ok_or(FlmError::InvalidOpcode { opcode: c, offset })
    }

    /// Evaluate the player's current slot and variable state into a record.
    fn evaluate_slice(&mut self, sound_cues: Vec<AudioCue>) -> TrajectoryRecord {
        // Camera evaluation
        let view_idx = self.view_obj as usize;
        let view_slot = self.slots.get(view_idx).filter(|slot| slot.active);
        let (eye, target) = if let Some(view_slot) = view_slot {
            let eye = view_slot.position_meters();
            let forward = rotate_quat(view_slot.rotation_quat(), CAMERA_FORWARD);
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
        let roll = view_slot.map_or(0.0, |slot| bam_to_radians(slot.rot_bam[0]));

        let cut = detect_camera_cut(self.view_obj, self.last_view_obj);
        self.last_view_obj = Some(self.view_obj);

        let fov = if self.focal_distance > 0.0 {
            focal_to_fov_y(self.focal_distance)
        } else {
            PLAYONE_FOV_Y_DEGREES
        };

        // Each camera's zoom word is the film variable of its view index (image `0x11FC`
        // reads `[0x4888 + 0x7E + 2 * view_obj]`; research/playone-exe/lod.md section 2).
        let lens = self.variables.get(view_idx).copied().unwrap_or(0);

        let camera = CameraTransform {
            eye,
            target,
            fov_degrees: fov,
            roll_radians: roll,
            cut_from_previous: cut,
            lens,
        };

        // Every active slot, and the view slot only for its shadow: PLAYONE's scene walk
        // skips the view slot's actor draw (image `0x1E26`) but still queues the shadow of a
        // drawn, shadowed slot with a nonzero shape (`0x1E35`; research/playone-exe/sod-vm-frame.md
        // section 9.1, research/parity/hero-shadow.md question 10).
        let mut actors = Vec::new();
        for (actor_id, (idx, slot)) in (0u32..).zip(self.slots.iter().enumerate()) {
            let view = idx == view_idx;
            let view_shadow = SIF_DRAW | SIF_SHADOW;
            let shadow_queued = slot.type_flags & view_shadow == view_shadow && slot.shape_id != 0;
            if !slot.active || (view && !shadow_queued) {
                continue;
            }

            let model_name = slot.model_name.clone().unwrap_or_else(|| {
                if slot.shape_id == 1 || idx == 1 {
                    "FOKKER".to_string()
                } else {
                    format!("ACTOR_{actor_id}")
                }
            });

            let position_meters = slot.position_meters();
            let rotation_quat = slot.actor_rotation_quat();
            // The slot's SIF create flags, not a SOD visibility state: PLAYONE's `OP_IFVIS`
            // tests a facing flag (`0x9BCC`), so no decoded gate reads this mask. Swept as
            // 1, all-ones and these flags on 2026-11-05 with identical scores on both films
            // (work/2026-10/parity-log/log.md); kept because the flags carry `SIF_SHADOW`.
            let state_mask = if slot.type_flags != 0 {
                u16::from(slot.type_flags)
            } else {
                1
            };

            let joint_angles_bam = if slot.animate != 0 {
                vec![(0, slot.animate)]
            } else {
                Vec::new()
            };

            actors.push(ActorTransform {
                actor_id,
                model_name,
                shape_id: slot.shape_id,
                rotation_quat,
                position_meters,
                state_mask,
                casts_shadow: (slot.type_flags & SIF_SHADOW) != 0,
                view,
                joint_angles_bam,
            });
        }

        TrajectoryRecord {
            tick: self.current_tick,
            camera,
            actors,
            audio_cues: sound_cues,
            palette: PaletteControls {
                sky: self.variables[VAR_SKY],
                brightness: self.variables[VAR_BRIGHTNESS],
                saturation: self.variables[VAR_SATURATION],
            },
            bank: BankVariables {
                var10: self.variables[VAR_BANK_PHASE],
                var12: self.variables[VAR_BANK_TILT],
            },
        }
    }

    /// True if there are remaining bytes to decode.
    #[inline]
    fn has_more(&self) -> bool {
        self.reader.has_more()
    }

    /// Read a single byte.
    fn read_u8(&mut self) -> Result<u8, FlmError> {
        Ok(self.reader.read_u8()?)
    }

    /// Read an unsigned 16-bit little-endian integer.
    fn read_u16_le(&mut self) -> Result<u16, FlmError> {
        Ok(self.reader.read_u16_le()?)
    }

    /// Read a signed 32-bit little-endian integer (16.16 fixed-point).
    fn read_i32_le(&mut self) -> Result<i32, FlmError> {
        Ok(self.reader.read_i32_le()?)
    }

    /// Read a null-terminated C string as raw bytes.
    fn read_cstring(&mut self) -> Result<Vec<u8>, FlmError> {
        Ok(self.reader.read_cstring()?)
    }
}

#[cfg(test)]
mod tests;
