//! Binary `.FLM` choreography stream parser.
//!
//! Provides binary decoding for `FILM` container signatures, simulation time slices,
//! slot allocation and state updates, and sound cue event dispatch.

use super::FlmError;
use super::interpolate::{bam_to_radians, quat_from_euler};
use crate::contracts::trajectory::AudioCue;

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
/// Slot flag: the slot plays a keyframed model animation.
pub const SIF_ANIMATES: u8 = 0x20;

/// Maximum number of object slots addressable in `.FLM` opcodes (6-bit index).
pub const SIFILM_MAX_OBJ: usize = 64;

/// Internal simulation state for an entity slot in the `.FLM` timeline.
#[derive(Debug, Clone, PartialEq, Default)]
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
    /// Model animation frame counter.
    pub animate: u16,
}

impl SlotState {
    /// Convert 16.16 fixed-point position into right-handed metric meters `[I1]`.
    #[inline]
    pub fn position_meters(&self) -> [f32; 3] {
        [
            self.pos_fixed[0] as f32 / 65536.0,
            self.pos_fixed[1] as f32 / 65536.0,
            self.pos_fixed[2] as f32 / 65536.0,
        ]
    }

    /// Convert BAM rotation angles `[rz, rx, ry]` into a normalized unit quaternion `[I1]`.
    ///
    /// The stored pitch `rx` uses the opposite handedness from [`quat_from_euler`]'s
    /// `pitch` argument: negating it is what makes a view slot look at the drawn actor
    /// (`CTRY.FLM` tick 1 lands 1.4° off the actor bearing; docs/SPEC.md § 3.7).
    pub fn rotation_quat(&self) -> [f32; 4] {
        if self.rot_bam == [0, 0, 0] {
            [0.0, 0.0, 0.0, 1.0]
        } else {
            let rz_rad = bam_to_radians(self.rot_bam[0]);
            let rx_rad = bam_to_radians(self.rot_bam[1]);
            let ry_rad = bam_to_radians(self.rot_bam[2]);
            quat_from_euler(ry_rad, -rx_rad, rz_rad)
        }
    }
}

/// Metadata and events extracted from a single `.FLM` time slice.
#[derive(Debug, Clone, PartialEq)]
pub struct Slice {
    /// Back-pointer length of the preceding slice, used to walk the stream backwards.
    pub prev_slice_len: u16,
    /// Slice duration in simulation ticks.
    pub tick_duration: u8,
    /// Sound events triggered while this slice runs.
    pub sound_cues: Vec<AudioCue>,
}

/// Binary stream decoder for `.FLM` choreography files.
#[derive(Debug, Clone)]
pub struct FlmParser<'a> {
    data: &'a [u8],
    pos: usize,
    /// Length of the most recently decoded slice, used to validate the back-pointer chain.
    last_slice_len: Option<usize>,
    /// Non-fatal stream inconsistencies, such as a broken `prev_slice_len` chain.
    warnings: Vec<String>,
}

impl<'a> FlmParser<'a> {
    /// Create a new parser, validating the 4-byte ASCII signature `b"FILM"`.
    pub fn new(data: &'a [u8]) -> Result<Self, FlmError> {
        if data.len() < 4 {
            return Err(FlmError::UnexpectedEof {
                expected: 4,
                actual: data.len(),
            });
        }
        let sig: [u8; 4] = data[0..4].try_into().map_err(|_| FlmError::UnexpectedEof {
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
            data,
            pos: 4,
            last_slice_len: None,
            warnings: Vec::new(),
        })
    }

    /// Non-fatal inconsistencies observed while decoding the stream.
    #[inline]
    pub fn warnings(&self) -> &[String] {
        &self.warnings
    }

    /// Current read cursor offset in bytes.
    #[inline]
    pub fn position(&self) -> usize {
        self.pos
    }

    /// True if there are remaining bytes to decode.
    #[inline]
    pub fn has_more(&self) -> bool {
        self.pos < self.data.len()
    }

    /// Read a single byte.
    pub fn read_u8(&mut self) -> Result<u8, FlmError> {
        if self.pos >= self.data.len() {
            return Err(FlmError::UnexpectedEof {
                expected: self.pos + 1,
                actual: self.data.len(),
            });
        }
        let b = self.data[self.pos];
        self.pos += 1;
        Ok(b)
    }

    /// Read an unsigned 16-bit little-endian integer.
    pub fn read_u16_le(&mut self) -> Result<u16, FlmError> {
        if self.pos + 2 > self.data.len() {
            return Err(FlmError::UnexpectedEof {
                expected: self.pos + 2,
                actual: self.data.len(),
            });
        }
        let bytes = [self.data[self.pos], self.data[self.pos + 1]];
        self.pos += 2;
        Ok(u16::from_le_bytes(bytes))
    }

    /// Read a signed 32-bit little-endian integer (16.16 fixed-point).
    pub fn read_i32_le(&mut self) -> Result<i32, FlmError> {
        if self.pos + 4 > self.data.len() {
            return Err(FlmError::UnexpectedEof {
                expected: self.pos + 4,
                actual: self.data.len(),
            });
        }
        let bytes = [
            self.data[self.pos],
            self.data[self.pos + 1],
            self.data[self.pos + 2],
            self.data[self.pos + 3],
        ];
        self.pos += 4;
        Ok(i32::from_le_bytes(bytes))
    }

    /// Read a null-terminated ASCII C-string.
    pub fn read_cstring(&mut self) -> Result<String, FlmError> {
        let start = self.pos;
        while self.pos < self.data.len() {
            let b = self.data[self.pos];
            self.pos += 1;
            if b == 0 {
                let slice = &self.data[start..self.pos - 1];
                return Ok(String::from_utf8_lossy(slice).into_owned());
            }
        }
        Err(FlmError::UnexpectedEof {
            expected: self.pos + 1,
            actual: self.data.len(),
        })
    }

    /// Parse the next time slice from the binary stream.
    ///
    /// Applies state mutations to object slots, variables, active camera, credits,
    /// and returns the decoded [`Slice`] metadata.
    pub fn parse_slice(
        &mut self,
        current_tick: u32,
        slots: &mut [SlotState; SIFILM_MAX_OBJ],
        variables: &mut [u16; 16],
        view_obj: &mut u8,
        max_obj: &mut usize,
        credits: &mut [String; 2],
    ) -> Result<Option<Slice>, FlmError> {
        if !self.has_more() {
            return Ok(None);
        }

        let slice_start = self.pos;
        let prev_slice_len = self.read_u16_le()?;
        let tick_duration = self.read_u8()?;

        // A film ends with a header-only epilogue: the final slice's length followed by
        // the `0xFF` end-of-stream marker (`0x00` in a few corpus films). Some films
        // append filler after the marker, so `0xFF` - never an authored duration in the
        // 627,696-slice corpus, whose maximum is `0x7F` - also ends the stream.
        if self.pos == self.data.len() || tick_duration == 0xFF {
            if let Some(last_len) = self.last_slice_len
                && prev_slice_len as usize != last_len
            {
                self.warnings.push(format!(
                    "end-of-film epilogue at 0x{slice_start:04X} has prev_slice_len {prev_slice_len} (expected {last_len})"
                ));
            }
            self.pos = self.data.len();
            return Ok(None);
        }

        if let Some(last_len) = self.last_slice_len
            && prev_slice_len as usize != last_len
        {
            self.warnings.push(format!(
                "slice at 0x{slice_start:04X} has prev_slice_len {prev_slice_len} (expected {last_len})"
            ));
        }

        let mut sound_cues = Vec::new();

        loop {
            if self.pos >= self.data.len() {
                return Err(FlmError::InvalidSlice {
                    reason: format!(
                        "slice starting at offset 0x{slice_start:04X} ended abruptly without 0xFF terminator"
                    ),
                });
            }

            let op_offset = self.pos;
            let c = self.read_u8()?;

            if c == 0xFF {
                // Slice terminator
                break;
            }

            let top = c >> 6;
            let slot_idx = (c & 0x3F) as usize;

            match top {
                0 => {
                    // Group 0: CREATE slot
                    let type_flags = self.read_u8()?;
                    let slot = &mut slots[slot_idx];
                    slot.type_flags = type_flags;
                    slot.active = (type_flags & SIF_EXISTS) != 0;

                    if slot.active {
                        if (type_flags & SIF_DRAW) != 0 {
                            slot.shape_id = self.read_u16_le()?;
                        }
                        if (type_flags & SIF_MOVES) == 0 {
                            slot.pos_fixed[0] = self.read_i32_le()?;
                            slot.pos_fixed[1] = self.read_i32_le()?;
                            slot.pos_fixed[2] = self.read_i32_le()?;
                        }
                        if (type_flags & SIF_ROTATES) == 0 {
                            slot.rot_bam[0] = self.read_u16_le()?;
                            slot.rot_bam[1] = self.read_u16_le()?;
                            slot.rot_bam[2] = self.read_u16_le()?;
                        }
                    }
                    if slot_idx >= *max_obj {
                        *max_obj = slot_idx + 1;
                    }
                }
                1 => {
                    // Group 1: INTERP slot
                    let slot = &mut slots[slot_idx];
                    if (slot.type_flags & SIF_MOVES) != 0 {
                        slot.pos_fixed[0] = self.read_i32_le()?;
                        slot.pos_fixed[1] = self.read_i32_le()?;
                        slot.pos_fixed[2] = self.read_i32_le()?;
                    }
                    if (slot.type_flags & SIF_ROTATES) != 0 {
                        slot.rot_bam[0] = self.read_u16_le()?;
                        slot.rot_bam[1] = self.read_u16_le()?;
                        slot.rot_bam[2] = self.read_u16_le()?;
                    }
                    if (slot.type_flags & SIF_ANIMATES) != 0 {
                        slot.animate = self.read_u16_le()?;
                    }
                    slot.active = true;
                    if slot_idx >= *max_obj {
                        *max_obj = slot_idx + 1;
                    }
                }
                2 => {
                    // Group 2: MISC Controls
                    if c < 0x90 {
                        let var_idx = (c & 0x0F) as usize;
                        let val = self.read_u16_le()?;
                        variables[var_idx] = val;
                    } else if c < 0x98 {
                        *view_obj = c & 0x0F;
                    } else if c == 0x98 {
                        credits[0].clear();
                        credits[1].clear();
                    } else if c == 0x99 {
                        credits[0] = self.read_cstring()?;
                        credits[1] = self.read_cstring()?;
                    } else if c == 0x9B {
                        *max_obj = self.read_u8()? as usize;
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
                            ((param >> 8) as f32) / 255.0
                        } else {
                            0.8
                        };

                        let pan = if param != 0 && (param & 0xFF) != 0 {
                            ((param & 0xFF) as f32 - 128.0) / 128.0
                        } else {
                            0.0
                        };

                        sound_cues.push(AudioCue {
                            tick: current_tick,
                            sample_name,
                            volume,
                            pan,
                        });
                    } else if c >= 0xA0 {
                        // Before-state word (prior variable value)
                        let _before_val = self.read_u16_le()?;
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

        self.last_slice_len = Some(self.pos - slice_start);

        Ok(Some(Slice {
            prev_slice_len,
            tick_duration,
            sound_cues,
        }))
    }
}
