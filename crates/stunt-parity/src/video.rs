//! A video capture's description: the tick and palette log beside `capture.avi`.
//!
//! The capture harness records one AVI per film and writes `meta.json` last. The
//! AVI carries the pixels; this document carries what the pixels cannot: which
//! film clock each recorded frame shows and every palette write the game made.
//! The log is columnar (one array per field) so a long film stays compact, and
//! `kind` marks the document so a frame capture's `meta.json` is not mistaken
//! for one.

use schemars::JsonSchema;
use serde::{Deserialize, Serialize};

use crate::error::ArtifactError;
use crate::film::FilmId;
use crate::render::Geometry;

/// File name of the recorded video inside a video capture directory.
pub const VIDEO_FILE: &str = "capture.avi";

/// The `kind` a video capture's `meta.json` carries.
const KIND: &str = "video";

/// Entries in a VGA palette.
const PALETTE_ENTRIES: usize = 256;

/// How the recording stopped.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
#[serde(rename_all = "lowercase")]
pub enum CaptureEnd {
    /// The film ended and the harness held on its last frame.
    Hold,
    /// The harness stopped at its frame cap before the film ended.
    Capped,
}

/// Per-frame clocks, one entry per recorded video frame, as parallel columns.
#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
pub struct TickLog {
    /// Capture frame number of each row; ascends by one.
    pub frame: Vec<u64>,
    /// Film clock the frame shows.
    pub film_tick: Vec<u32>,
    /// Game-wide tick counter at the frame.
    pub global_tick: Vec<u32>,
    /// Clock of the slot pass at the frame (ADR 0057); present with
    /// `slot_ticks` or not at all.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub slot_clock: Option<Vec<u16>>,
    /// Ticks since the previous slot pass at the frame; present with `slot_clock` or not at all.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub slot_ticks: Option<Vec<u16>>,
}

/// A run of palette entries the game rewrote at one frame.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
pub struct PaletteChange {
    /// Capture frame number at which the new entries took effect.
    pub frame: u64,
    /// Index of the first rewritten entry.
    pub first: u16,
    /// The rewritten entries, 8-bit RGB.
    pub rgb: Vec<[u8; 3]>,
}

/// The palette at the start of the log and every later write.
#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
pub struct PaletteLog {
    /// The 256 entries in force at the first logged frame.
    pub initial: Vec<[u8; 3]>,
    /// Palette writes in ascending frame order.
    pub changes: Vec<PaletteChange>,
}

/// The recorded video beside `meta.json`, as the emulator wrote it with audio stripped.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
pub struct VideoFileInfo {
    /// File name; always [`VIDEO_FILE`].
    pub file: String,
    /// SHA-256 of the file, which pins the recording.
    pub sha256: String,
    /// Length of the file in bytes.
    pub bytes: u64,
    /// Video codec of the recording, such as `zmbv`.
    pub codec: String,
    /// Exact frame rate as numerator and denominator (`[2190197, 31250]`), which containers round.
    pub frame_rate: [u32; 2],
}

/// The emulator that recorded the film, and the stage conf it ran under.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
pub struct EmulatorInfo {
    /// Emulator name, such as `dosbox-automation`.
    pub name: String,
    /// Emulator version, such as `0.85.1`.
    pub version: String,
    /// `core` from the stage conf, such as `dynamic`.
    pub core: String,
    /// `cpu_cycles` from the stage conf, such as `45000` or `max`.
    pub cpu_cycles: String,
}

/// The `DGROUP` offsets the log read, as `0x` and four upper-case hex digits.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
pub struct LayoutOffsets {
    /// Film clock word.
    pub film_clock: String,
    /// Game-wide tick counter word.
    pub global_tick: String,
    /// Working palette, 768 bytes.
    pub working_palette: String,
    /// Slot pass clock word; present when the log carries `slot_clock`.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub slot_clock: Option<String>,
    /// Ticks word of the slot pass; present when the log carries `slot_ticks`.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub slot_ticks: Option<String>,
    /// Names of the offsets above that were inferred, not read from this build's code (ADR 0057).
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub inferred: Vec<String>,
}

/// Document written by the video capture harness as `meta.json`.
///
/// Fields the harness adds beyond these are ignored on read. Every field after `palettes` is
/// optional, so a capture made before it was recorded still reads.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
pub struct VideoCapture {
    /// Schema version of the document.
    pub schema_version: u32,
    /// Document kind; always `"video"`. Absent in a frame capture's `meta.json`.
    #[serde(default)]
    pub kind: String,
    /// Film the capture shows.
    pub film: FilmId,
    /// Raster geometry of the video.
    pub geometry: Geometry,
    /// Build of `PLAYONE.EXE` that was recorded.
    pub playone_build: String,
    /// SHA-256 of the `PLAYONE.EXE` that was recorded; absent from captures made before the
    /// harness recorded it.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub playone_sha256: Option<String>,
    /// CPU profile the emulator ran under.
    pub cpu_profile: String,
    /// Capture frame number of video frame 0.
    pub capture_start_frame: u64,
    /// First logged frame at which the film clock moved.
    pub film_start_frame: u64,
    /// How the recording stopped.
    pub end: CaptureEnd,
    /// Per-frame clocks.
    pub log: TickLog,
    /// Palette history.
    pub palettes: PaletteLog,
    /// Number of video frames the recording holds, which may differ from `rows` by one.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub video_frames: Option<u64>,
    /// Number of rows in `log`.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub rows: Option<u64>,
    /// Number of entries in `palettes.changes`.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub palette_changes: Option<u64>,
    /// Runtime `DGROUP` segment as four upper-case hex digits.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub dgroup_segment: Option<String>,
    /// Date of the capture, `YYYY-MM-DD`.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub captured_on: Option<String>,
    /// Name of the checkout the capture ran from.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub checkout: Option<String>,
    /// How the `.ALL`'s sound range was staged, `stubbed` or `kept` (ADR 0043).
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub sound_samples: Option<String>,
    /// The recorded video beside this file.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub video: Option<VideoFileInfo>,
    /// What recorded it.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub emulator: Option<EmulatorInfo>,
    /// The `DGROUP` offsets the log read.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub layout: Option<LayoutOffsets>,
    /// First and last `film_tick` in the log.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub film_ticks: Option<[u32; 2]>,
}

impl VideoCapture {
    /// Checks the schema version, kind, geometry, log columns, palette history and the
    /// whole-film fields that summarise them.
    ///
    /// # Errors
    /// - [`ArtifactError::UnsupportedVersion`] if `schema_version` is not [`crate::SCHEMA_VERSION`].
    /// - [`ArtifactError::MissingField`] if `kind` is empty.
    /// - [`ArtifactError::Geometry`] if the geometry fails [`Geometry::validate`].
    /// - [`ArtifactError::VideoLog`] if `kind` is not `"video"`, the tick log columns differ in
    ///   length, frames do not ascend by one, `film_start_frame` is not a logged frame,
    ///   `film_tick` falls after the film start, the slot columns are not both present or differ
    ///   in length, the palette history is malformed, or `rows`, `palette_changes`, `film_ticks`
    ///   or `video` disagree with the log.
    pub fn validate(&self) -> Result<(), ArtifactError> {
        if self.schema_version != crate::SCHEMA_VERSION {
            return Err(ArtifactError::UnsupportedVersion {
                found: self.schema_version,
                expected: crate::SCHEMA_VERSION,
            });
        }
        if self.kind.is_empty() {
            return Err(ArtifactError::MissingField {
                field: "kind".to_string(),
            });
        }
        if self.kind != KIND {
            return Err(ArtifactError::video_log(format!(
                "kind is {:?}, expected {KIND:?}",
                self.kind
            )));
        }
        self.geometry.validate()?;
        self.validate_log()?;
        self.validate_palettes()?;
        self.validate_summary()
    }

    /// Index of capture `frame` relative to the recording start, or `None` before it or if the
    /// index does not fit in `usize`. The result is not checked against the recording's length.
    /// The log row of `frame` is one lower (`capture_start_frame + 1` is row 0, AVI frame 0).
    #[must_use]
    pub fn video_index(&self, frame: u64) -> Option<usize> {
        let index = frame.checked_sub(self.capture_start_frame)?;
        usize::try_from(index).ok()
    }

    fn validate_log(&self) -> Result<(), ArtifactError> {
        let log = &self.log;
        let rows = log.frame.len();
        if log.film_tick.len() != rows || log.global_tick.len() != rows {
            return Err(ArtifactError::video_log(format!(
                "log columns differ in length: frame {rows}, film_tick {}, global_tick {}",
                log.film_tick.len(),
                log.global_tick.len()
            )));
        }
        match (&log.slot_clock, &log.slot_ticks) {
            (None, None) => {}
            (Some(clock), Some(ticks)) => {
                if clock.len() != rows || ticks.len() != rows {
                    return Err(ArtifactError::video_log(format!(
                        "log columns differ in length: frame {rows}, slot_clock {}, slot_ticks {}",
                        clock.len(),
                        ticks.len()
                    )));
                }
            }
            _ => {
                return Err(ArtifactError::video_log(
                    "slot_clock and slot_ticks must come together",
                ));
            }
        }
        let pairs = log.frame.iter().zip(log.frame.iter().skip(1));
        for (index, (&prev, &next)) in pairs.enumerate() {
            if prev.checked_add(1) != Some(next) {
                return Err(ArtifactError::video_log(format!(
                    "frames must ascend by one: index {} is {next} after {prev}",
                    index + 1,
                )));
            }
        }
        let Some(start) = log.frame.iter().position(|&f| f == self.film_start_frame) else {
            return Err(ArtifactError::video_log(format!(
                "film_start_frame {} is not a logged frame",
                self.film_start_frame
            )));
        };
        let ticks = log.film_tick.iter().skip(start);
        let frames = log.frame.iter().skip(start + 1);
        for (&frame, (&prev, &tick)) in frames.zip(ticks.clone().zip(ticks.skip(1))) {
            if tick < prev {
                return Err(ArtifactError::video_log(format!(
                    "film_tick falls at frame {frame}: {tick} after {prev}"
                )));
            }
        }
        Ok(())
    }

    /// Checks the whole-film fields against the log they summarise.
    fn validate_summary(&self) -> Result<(), ArtifactError> {
        let log = &self.log;
        let counts = [
            ("rows", self.rows, log.frame.len()),
            (
                "palette_changes",
                self.palette_changes,
                self.palettes.changes.len(),
            ),
        ];
        for (name, stated, actual) in counts {
            if stated.is_some_and(|n| usize::try_from(n) != Ok(actual)) {
                return Err(ArtifactError::video_log(format!(
                    "{name} is {}, the log holds {actual}",
                    stated.unwrap_or_default()
                )));
            }
        }
        if let Some([first, last]) = self.film_ticks {
            let logged = [
                log.film_tick.first().copied(),
                log.film_tick.last().copied(),
            ];
            if logged != [Some(first), Some(last)] {
                return Err(ArtifactError::video_log(format!(
                    "film_ticks {first}..{last} differ from the log's {logged:?}"
                )));
            }
        }
        if let Some(video) = &self.video {
            if video.file != VIDEO_FILE {
                return Err(ArtifactError::video_log(format!(
                    "video.file is {:?}, expected {VIDEO_FILE:?}",
                    video.file
                )));
            }
            let hex = video.sha256.len() == 64
                && video
                    .sha256
                    .bytes()
                    .all(|b| matches!(b, b'0'..=b'9' | b'a'..=b'f'));
            if !hex {
                return Err(ArtifactError::video_log(
                    "video.sha256 is not 64 lower-case hex digits",
                ));
            }
        }
        Ok(())
    }

    fn validate_palettes(&self) -> Result<(), ArtifactError> {
        let palettes = &self.palettes;
        if palettes.initial.len() != PALETTE_ENTRIES {
            return Err(ArtifactError::video_log(format!(
                "the initial palette must have {PALETTE_ENTRIES} entries, got {}",
                palettes.initial.len()
            )));
        }
        let first_frame = self.log.frame.first().copied();
        let last_frame = self.log.frame.last().copied();
        let mut previous: Option<u64> = None;
        for (index, change) in palettes.changes.iter().enumerate() {
            if usize::from(change.first) + change.rgb.len() > PALETTE_ENTRIES {
                return Err(ArtifactError::video_log(format!(
                    "palette change {index} writes {} entries from {}, past entry {}",
                    change.rgb.len(),
                    change.first,
                    PALETTE_ENTRIES - 1
                )));
            }
            if previous.is_some_and(|before| change.frame <= before) {
                return Err(ArtifactError::video_log(format!(
                    "palette changes must ascend: change {index} is at frame {}",
                    change.frame
                )));
            }
            previous = Some(change.frame);
            if first_frame.is_none_or(|low| change.frame < low)
                || last_frame.is_none_or(|high| change.frame > high)
            {
                return Err(ArtifactError::video_log(format!(
                    "palette change {index} at frame {} lies outside the log",
                    change.frame
                )));
            }
        }
        Ok(())
    }
}
