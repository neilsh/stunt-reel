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

/// PLAYONE's vertical field of view at [`DEFAULT_CAMERA_LENS`].
///
/// A focal length of 256 raster pixels over the 200-row page's half-height, `2 * atan(100 / 256)`.
/// Fitted to the capture's horizon and confirmed by sweep (research/parity/framing-and-actors.md,
/// section 2); 256 matches the `x 256` screen slopes at `0x22A0`/`0x22A2`.
pub const PLAYONE_FOV_Y_DEGREES: f32 = 42.673_717;

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
    #[expect(
        clippy::arithmetic_side_effects,
        reason = "`lens` is a u16, so `lens * 0x7FFF` is below 2^31, and `shifts_left` starts at 3 and is only decremented while above 0, so it stays in 0..=3"
    )]
    pub fn lens_zoom(&self) -> f32 {
        let mut product = u32::from(self.lens) * 0x7FFF;
        let mut shifts_left = 3;
        while product & 0x4000_0000 == 0 && shifts_left > 0 {
            product <<= 1;
            shifts_left -= 1;
        }
        (product >> 16) as f32 / 32768.0 * f32::from(1u16 << shifts_left)
    }

    /// PLAYONE's lens words for this camera: the level-of-detail mantissa `0x22A4` and the
    /// depth shift `0x229E`.
    ///
    /// Mirrors image `0x120A..0x124D` at detail `0xFFFF` (research/playone-exe/lod.md
    /// section 2): `0x229C` is the high word of `lens * 0x7FFF` after the normalising
    /// shifts, `0x22A4 = (0x229C * 0xFFFF * 2) >> 16`, and `0x229E` is the shifts left over.
    #[must_use]
    #[expect(
        clippy::arithmetic_side_effects,
        reason = "`lens` is a u16, so `lens * 0x7FFF` is below 2^31; `shifts_left` stays in 0..=3; `0x229C * 0xFFFF * 2` is below 2^32"
    )]
    pub fn lod_lens_words(&self) -> (u16, u8) {
        let mut product = u32::from(self.lens) * 0x7FFF;
        let mut shifts_left = 3u8;
        while product & 0x4000_0000 == 0 && shifts_left > 0 {
            product <<= 1;
            shifts_left -= 1;
        }
        let scale = product >> 16;
        let mantissa = u16::try_from((u64::from(scale) * 0xFFFF * 2) >> 16).unwrap_or(u16::MAX);
        (mantissa, shifts_left)
    }

    /// Whether PLAYONE's `SP_1NODE` switch (image `0x2121..0x2147`) descends into the
    /// subtree of a node at `point` (`[I1]` metres) with extent `ext` and split distance
    /// `splitdist`, seen from this camera, rather than drawing its stand-in.
    ///
    /// The depth compared is the high word of the zoomed view matrix's depth row (image
    /// `0x211E`): the node's distance along the view axis halved, by the Q15 rows, and shifted
    /// right by `0x229E`. With `half = ext >> 1` the threshold is `splitdist` when
    /// `splitdist < half`, else `half + ((splitdist - half) * 0x22A4 >> 16)`
    /// (research/playone-exe/lod.md sections 1.1 and 2.2).
    #[must_use]
    #[expect(
        clippy::arithmetic_side_effects,
        reason = "ext and splitdist are 16-bit words and the mantissa a u16, so the i64 maths cannot overflow"
    )]
    pub fn lod_keeps_subtree(&self, point: [f32; 3], ext: i32, splitdist: i32) -> bool {
        let (mantissa, shift) = self.lod_lens_words();
        let forward = [
            self.target[0] - self.eye[0],
            self.target[1] - self.eye[1],
            self.target[2] - self.eye[2],
        ];
        let len =
            (forward[0] * forward[0] + forward[1] * forward[1] + forward[2] * forward[2]).sqrt();
        if len <= 0.0 {
            return true;
        }
        let depth = ((point[0] - self.eye[0]) * forward[0]
            + (point[1] - self.eye[1]) * forward[1]
            + (point[2] - self.eye[2]) * forward[2])
            / len;
        // The depth row's high word: Q15 rows halve it, and `0x229E` shifts it further.
        let depth = (depth / f32::from(2u16 << shift)).floor();
        let half = i64::from(ext >> 1);
        let split = i64::from(splitdist);
        let threshold = if split < half {
            split
        } else {
            half + (((split - half) * i64::from(mantissa)) >> 16)
        };
        depth <= threshold as f32
    }

    /// Whether PLAYONE's scenery cull keeps an object of `scale_index` at `point` (`[I1]`
    /// metres) by its distance cut (image `0x1B28`), seen from this camera.
    ///
    /// `0x31CF` shifts the eye-relative position right by `s`, one more than the bit length
    /// of the whole metres of its largest absolute coordinate, and the cull `0x1B0C` drops the
    /// object when `scale_index + s - 16` exceeds `0x229E + 7`: once that coordinate reaches
    /// `2^(22 + 0x229E - scale_index)` metres
    /// (research/playone-exe/world-scene-residuals.md section 6.4).
    #[must_use]
    #[expect(
        clippy::cast_possible_truncation,
        clippy::cast_sign_loss,
        reason = "the coordinate is clamped to 0..=65535 first, PLAYONE's 16-bit high word"
    )]
    pub fn scale_reach_keeps(&self, point: [f32; 3], scale_index: u8) -> bool {
        let (_, shift) = self.lod_lens_words();
        let largest = point
            .iter()
            .zip(&self.eye)
            .map(|(p, e)| (p - e).abs())
            .fold(0.0f32, f32::max);
        let high = largest.clamp(0.0, 65535.0) as u16;
        // One more than the bit length of `high`, from `0x31CF`'s table at `0x323A`.
        let s = 17u32.saturating_sub(high.leading_zeros());
        let gap = (u32::from(scale_index).saturating_add(s)).saturating_sub(16);
        gap <= u32::from(shift).saturating_add(7)
    }

    /// Whether `point`'s depth along this camera's view axis exceeds `depth` as PLAYONE's
    /// `OP_BZLT` compares it, i.e. whether the section after a `BZLT` runs.
    ///
    /// `BZLT reg, val, rel` (image `0x9BE5`) skips its section while the register's view
    /// depth is at most `val`. Registers hold the zoomed depth row's high word, so depth
    /// halved and shifted right by `0x229E` (research/playone-exe/sod-vm-execution.md section 8.6):
    /// the section runs while `true depth / 2^(1 + 0x229E) > depth`, with `depth` the
    /// threshold `val` in the shape's metres. A camera with no view direction keeps it.
    #[must_use]
    pub fn view_depth_exceeds(&self, point: [f32; 3], depth: f32) -> bool {
        let (_, shift) = self.lod_lens_words();
        let forward = [
            self.target[0] - self.eye[0],
            self.target[1] - self.eye[1],
            self.target[2] - self.eye[2],
        ];
        let len =
            (forward[0] * forward[0] + forward[1] * forward[1] + forward[2] * forward[2]).sqrt();
        if len <= 0.0 {
            return true;
        }
        let along = ((point[0] - self.eye[0]) * forward[0]
            + (point[1] - self.eye[1]) * forward[1]
            + (point[2] - self.eye[2]) * forward[2])
            / len;
        along / f32::from(2u16 << shift) > depth
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
    /// The authored default: eye 50 m back and 10 m up, looking at the origin.
    fn default() -> Self {
        Self {
            eye: [0.0, 10.0, 50.0],
            target: [0.0, 0.0, 0.0],
            fov_degrees: PLAYONE_FOV_Y_DEGREES,
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
    /// The slot casts a ground shadow: its create flags carry `SIF_SHADOW` (`0x04`), on
    /// which PLAYONE's actor loop queues the flattened shadow draw (image `0x1E35`,
    /// `research/playone-exe/sod-vm-frame.md` section 9.1).
    #[cfg_attr(feature = "serde", serde(default))]
    pub casts_shadow: bool,
    /// The slot is the view camera's (`[0x22DE]`): PLAYONE queues no actor draw for it
    /// (image `0x1E26`) but still queues its shadow, so the player lists it only when it
    /// casts one (`research/playone-exe/sod-vm-frame.md` section 9.1).
    #[cfg_attr(feature = "serde", serde(default))]
    pub view: bool,
    /// Articulated subobject BAM rotation angles `(subobject_id, raw_bam_u16)`.
    #[cfg_attr(feature = "serde", serde(default))]
    pub joint_angles_bam: Vec<(u16, u16)>,
}

impl ActorTransform {
    /// The slot's `.FLM` `animate` word, which the player carries as joint slot 0 of
    /// [`Self::joint_angles_bam`]; 0 when the actor has none.
    ///
    /// `PLAYONE` keeps it at the slot record's `+0x16` and hands it to the shape as the bank
    /// word an `OP_ANIMATE` with selector `0x16` reads (`research/playone-exe/sod-animate.md`).
    #[must_use]
    pub fn animate(&self) -> u16 {
        self.joint_angles_bam
            .iter()
            .find(|&&(joint, _)| joint == 0)
            .map_or(0, |&(_, value)| value)
    }

    /// Computes the canonical column-major 4x4 world transformation matrix
    /// from `position_meters` (x, y, z) and unit `rotation_quat` [x, y, z, w].
    #[must_use]
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
/// Used as the format of the synthetic `build/oracle/intro_trajectory.json`.
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
    /// Film variables 10 and 12, which fill the angle bank at this tick.
    #[cfg_attr(feature = "serde", serde(default))]
    pub bank: BankVariables,
}

/// The film variables `PLAYONE` fills its angle bank from once a frame (`0x1D96`): the words
/// articulated parts turn by (`research/playone-exe/angle-bank.md`).
///
/// Sampled per frame with the same linear interpolation as the palette's variables
/// (`CS:0x136F`). [`Self::default`], both 0, is a film that never sets them.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
#[cfg_attr(feature = "serde", derive(serde::Serialize, serde::Deserialize))]
pub struct BankVariables {
    /// Var 10: its low byte is the propeller and rotor phase, in 1/256 turns (bank `0x14`);
    /// its change over a frame is bank `0x12`.
    pub var10: u16,
    /// Var 12: bank `0x18`, and its negation bank `0x1A`.
    pub var12: u16,
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
