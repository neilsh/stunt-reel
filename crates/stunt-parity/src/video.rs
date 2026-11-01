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
    /// Returns an artifact error when a check fails, including a geometry validation error.
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
        for (index, pair) in log.frame.windows(2).enumerate() {
            if pair[0].checked_add(1) != Some(pair[1]) {
                return Err(ArtifactError::video_log(format!(
                    "frames must ascend by one: index {} is {} after {}",
                    index + 1,
                    pair[1],
                    pair[0]
                )));
            }
        }
        let Some(start) = log.frame.iter().position(|&f| f == self.film_start_frame) else {
            return Err(ArtifactError::video_log(format!(
                "film_start_frame {} is not a logged frame",
                self.film_start_frame
            )));
        };
        for offset in start + 1..rows {
            if log.film_tick[offset] < log.film_tick[offset - 1] {
                return Err(ArtifactError::video_log(format!(
                    "film_tick falls at frame {}: {} after {}",
                    log.frame[offset],
                    log.film_tick[offset],
                    log.film_tick[offset - 1]
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

#[cfg(test)]
mod tests {
    use super::*;

    fn capture() -> VideoCapture {
        VideoCapture {
            schema_version: crate::SCHEMA_VERSION,
            kind: "video".to_string(),
            film: FilmId::default(),
            geometry: Geometry {
                width: 4,
                height: 2,
                viewport_rows: None,
            },
            playone_build: "synthetic".to_string(),
            cpu_profile: "capture".to_string(),
            capture_start_frame: 100,
            film_start_frame: 103,
            end: CaptureEnd::Hold,
            log: TickLog {
                frame: vec![101, 102, 103, 104],
                film_tick: vec![7, 7, 8, 9],
                global_tick: vec![0, 1, 2, 3],
            },
            palettes: PaletteLog {
                initial: vec![[0, 0, 0]; 256],
                changes: vec![PaletteChange {
                    frame: 103,
                    first: 32,
                    rgb: vec![[255, 0, 0]; 32],
                }],
            },
        }
    }

    fn reason(error: ArtifactError) -> String {
        match error {
            ArtifactError::VideoLog { reason } => reason,
            other => panic!("expected VideoLog, got {other:?}"),
        }
    }

    #[test]
    fn a_valid_log_passes() {
        capture().validate().expect("valid");
    }

    #[test]
    fn a_kind_other_than_video_is_rejected() {
        let mut absent = capture();
        absent.kind = String::new();
        assert_eq!(
            absent.validate(),
            Err(ArtifactError::MissingField {
                field: "kind".to_string()
            })
        );
        let mut frames = capture();
        frames.kind = "frames".to_string();
        reason(frames.validate().expect_err("kind"));
    }

    #[test]
    fn columns_of_different_length_are_rejected() {
        let mut document = capture();
        document.log.global_tick.pop();
        assert!(reason(document.validate().expect_err("columns")).contains("length"));
    }

    #[test]
    fn frames_must_ascend_by_one() {
        let mut document = capture();
        document.log.frame = vec![101, 103, 104, 105];
        assert!(reason(document.validate().expect_err("gap")).contains("index 1"));
    }

    #[test]
    fn film_tick_may_not_fall_after_the_film_starts() {
        let mut document = capture();
        document.log.film_tick = vec![7, 7, 9, 8];
        assert!(reason(document.validate().expect_err("fall")).contains("frame 104"));
    }

    #[test]
    fn film_start_frame_must_be_a_logged_frame() {
        let mut document = capture();
        document.film_start_frame = 200;
        assert!(reason(document.validate().expect_err("start")).contains("film_start_frame"));
    }

    #[test]
    fn the_initial_palette_has_256_entries() {
        let mut document = capture();
        document.palettes.initial.pop();
        assert!(reason(document.validate().expect_err("palette")).contains("256"));
    }

    #[test]
    fn a_change_must_fit_inside_256_entries() {
        let mut document = capture();
        document.palettes.changes[0].first = 250;
        assert!(reason(document.validate().expect_err("overflow")).contains("past entry"));
    }

    #[test]
    fn changes_must_ascend_and_lie_in_the_log() {
        let mut outside = capture();
        outside.palettes.changes[0].frame = 105;
        assert!(reason(outside.validate().expect_err("outside")).contains("outside the log"));
        let mut unordered = capture();
        let again = unordered.palettes.changes[0].clone();
        unordered.palettes.changes.push(PaletteChange {
            frame: 102,
            ..again
        });
        assert!(reason(unordered.validate().expect_err("order")).contains("ascend"));
    }

    #[test]
    fn video_index_counts_from_the_capture_start() {
        let document = capture();
        assert_eq!(document.video_index(101), Some(1));
        assert_eq!(document.video_index(99), None);
    }
}
