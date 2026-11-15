//! A video capture's description: the tick and palette log beside `capture.avi`.
//!
//! The capture harness records one AVI per film and writes `meta.json` last. The
//! AVI carries the pixels; this document carries what the pixels cannot: which
//! film clock each recorded frame shows and every palette write the game made.
//! The log is columnar (one array per field) so a long film stays compact, and
//! `kind` marks the document so a frame capture's `meta.json` is not mistaken
//! for one.

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
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum CaptureEnd {
    /// The film ended and the harness held on its last frame.
    Hold,
    /// The harness stopped at its frame cap before the film ended.
    Capped,
}

/// Per-frame clocks, one entry per recorded video frame, as parallel columns.
#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct TickLog {
    /// Capture frame number of each row; ascends by one.
    pub frame: Vec<u64>,
    /// Film clock the frame shows.
    pub film_tick: Vec<u32>,
    /// Game-wide tick counter at the frame.
    pub global_tick: Vec<u32>,
}

/// A run of palette entries the game rewrote at one frame.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct PaletteChange {
    /// Capture frame number at which the new entries took effect.
    pub frame: u64,
    /// Index of the first rewritten entry.
    pub first: u16,
    /// The rewritten entries, 8-bit RGB.
    pub rgb: Vec<[u8; 3]>,
}

/// The palette at the start of the log and every later write.
#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct PaletteLog {
    /// The 256 entries in force at the first logged frame.
    pub initial: Vec<[u8; 3]>,
    /// Palette writes in ascending frame order.
    pub changes: Vec<PaletteChange>,
}

/// Document written by the video capture harness as `meta.json`.
///
/// Fields the harness adds as diagnostics are ignored on read.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
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
}

impl VideoCapture {
    /// Checks the schema version, kind, geometry, log columns and palette history.
    ///
    /// # Errors
    /// - [`ArtifactError::UnsupportedVersion`] if `schema_version` is not [`crate::SCHEMA_VERSION`].
    /// - [`ArtifactError::MissingField`] if `kind` is empty.
    /// - [`ArtifactError::Geometry`] if the geometry fails [`Geometry::validate`].
    /// - [`ArtifactError::VideoLog`] if `kind` is not `"video"`, the tick log columns differ in
    ///   length, frames do not ascend by one, `film_start_frame` is not a logged frame,
    ///   `film_tick` falls after the film start, or the palette history is malformed.
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
        self.validate_palettes()
    }

    /// Index of capture `frame` relative to the recording start, or `None` before it or if the
    /// index does not fit in `usize`. The result is not checked against the recording's length.
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
