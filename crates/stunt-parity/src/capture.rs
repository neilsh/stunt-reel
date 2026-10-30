//! A capture directory's description: capture ordinals, film clocks and file names.
//!
//! The capture harness writes `meta.json` through the Python adapter; older
//! captures were written by hand, so this module also reads their legacy shape.
//! A document without `schema_version` is version 1, a document without
//! `width`/`height` was captured at the Mode 13h raster, and a frame without an
//! ordinal or file names takes the capture-order defaults. Every adapter crosses
//! this one document; the defaults live here rather than in either reader.

use std::fmt;

use serde::{Deserialize, Serialize};

use crate::error::ArtifactError;
use crate::film::FilmId;
use crate::render::Geometry;

/// Width of the Mode 13h raster a legacy capture was made at.
const DEFAULT_WIDTH: u32 = 320;
/// Height of the Mode 13h raster a legacy capture was made at.
const DEFAULT_HEIGHT: u32 = 200;

/// The one subdirectory of a capture directory that file names may point into (ADR 0024).
const FRAMES_DIR: &str = "frames/";

/// One captured frame's place in a capture directory.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct CapturedFrame {
    /// Capture order, 1-based; not a time axis.
    pub ordinal: u32,
    /// Film clock the captured page shows; parity matches on this.
    pub film_tick: u32,
    /// Raster file name: a basename inside the capture directory, optionally under `frames/`.
    pub frame_file: String,
    /// Palette file name: a basename inside the capture directory, optionally under `frames/`.
    pub palette_file: String,
}

/// Document written by the capture harness as `meta.json`.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(try_from = "CaptureDocument", into = "CaptureDocument")]
pub struct CaptureSet {
    /// Schema version; older captures without the field read as the current version.
    pub schema_version: u32,
    /// Film the capture shows.
    pub film: FilmId,
    /// Raster geometry of every captured frame.
    pub geometry: Geometry,
    /// Captured frames in capture order.
    pub frames: Vec<CapturedFrame>,
}

impl CaptureSet {
    /// Checks the schema version, geometry and frame identity.
    pub fn validate(&self) -> Result<(), ArtifactError> {
        if self.schema_version != crate::SCHEMA_VERSION {
            return Err(ArtifactError::UnsupportedVersion {
                found: self.schema_version,
                expected: crate::SCHEMA_VERSION,
            });
        }
        self.geometry.validate()?;
        for frame in &self.frames {
            if frame.frame_file.is_empty() || frame.palette_file.is_empty() {
                return Err(ArtifactError::Frame {
                    ordinal: frame.ordinal,
                    reason: "frame_file and palette_file are required".to_string(),
                });
            }
            for (field, name) in [
                ("frame_file", &frame.frame_file),
                ("palette_file", &frame.palette_file),
            ] {
                let leaf = name.strip_prefix(FRAMES_DIR).unwrap_or(name);
                if leaf.is_empty() || leaf.contains('/') || name.contains('\\') {
                    return Err(ArtifactError::Frame {
                        ordinal: frame.ordinal,
                        reason: format!(
                            "{field} must be a basename, optionally under {FRAMES_DIR}"
                        ),
                    });
                }
            }
        }
        Ok(())
    }
}

/// The flat `meta.json` shape, which predates the port's nested film records.
#[derive(Debug, Clone, Serialize, Deserialize)]
struct CaptureDocument {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    schema_version: Option<u32>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    film: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    flm_bytes: Option<u64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    flm_sha256: Option<String>,
    frames: Vec<FrameDocument>,
    #[serde(default = "default_width")]
    width: u32,
    #[serde(default = "default_height")]
    height: u32,
}

/// One frame entry of the flat `meta.json`; the ordinal and names may be absent.
#[derive(Debug, Clone, Serialize, Deserialize)]
struct FrameDocument {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    ordinal: Option<u32>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    film_tick: Option<u32>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    frame_file: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    palette_file: Option<String>,
}

/// A legacy frame has no film clock, so parity cannot pair it with a render.
#[derive(Debug)]
struct MissingFilmTick {
    /// Capture ordinal of the untagged frame.
    ordinal: u32,
}

impl fmt::Display for MissingFilmTick {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "frame {} has no film_tick", self.ordinal)
    }
}

impl std::error::Error for MissingFilmTick {}

fn default_width() -> u32 {
    DEFAULT_WIDTH
}

fn default_height() -> u32 {
    DEFAULT_HEIGHT
}

fn default_frame_file(ordinal: u32) -> String {
    format!("tick_{ordinal:04}.idx")
}

fn default_palette_file(ordinal: u32) -> String {
    format!("palettes_{ordinal:04}.json")
}

impl TryFrom<CaptureDocument> for CaptureSet {
    type Error = MissingFilmTick;

    fn try_from(document: CaptureDocument) -> Result<Self, Self::Error> {
        let mut frames = Vec::with_capacity(document.frames.len());
        for (index, frame) in document.frames.into_iter().enumerate() {
            let ordinal = u32::try_from(index + 1).unwrap_or(u32::MAX);
            let Some(film_tick) = frame.film_tick else {
                return Err(MissingFilmTick { ordinal });
            };
            frames.push(CapturedFrame {
                ordinal,
                film_tick,
                frame_file: frame
                    .frame_file
                    .unwrap_or_else(|| default_frame_file(ordinal)),
                palette_file: frame
                    .palette_file
                    .unwrap_or_else(|| default_palette_file(ordinal)),
            });
        }
        Ok(Self {
            schema_version: document.schema_version.unwrap_or(crate::SCHEMA_VERSION),
            film: FilmId {
                name: document.film,
                flm_bytes: document.flm_bytes,
                flm_sha256: document.flm_sha256,
            },
            geometry: Geometry {
                width: document.width,
                height: document.height,
                viewport_rows: None,
            },
            frames,
        })
    }
}

impl From<CaptureSet> for CaptureDocument {
    fn from(capture: CaptureSet) -> Self {
        Self {
            schema_version: Some(capture.schema_version),
            film: capture.film.name,
            flm_bytes: capture.film.flm_bytes,
            flm_sha256: capture.film.flm_sha256,
            frames: capture
                .frames
                .into_iter()
                .map(|frame| FrameDocument {
                    ordinal: Some(frame.ordinal),
                    film_tick: Some(frame.film_tick),
                    frame_file: Some(frame.frame_file),
                    palette_file: Some(frame.palette_file),
                })
                .collect(),
            width: capture.geometry.width,
            height: capture.geometry.height,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn capture() -> CaptureSet {
        CaptureSet {
            schema_version: crate::SCHEMA_VERSION,
            film: FilmId::default(),
            geometry: Geometry {
                width: 320,
                height: 200,
                viewport_rows: None,
            },
            frames: vec![CapturedFrame {
                ordinal: 1,
                film_tick: 9,
                frame_file: "tick_0001.idx".to_string(),
                palette_file: "palettes_0001.json".to_string(),
            }],
        }
    }

    #[test]
    fn a_current_capture_round_trips_through_the_flat_document() {
        let text = serde_json::to_string(&capture()).expect("serialize");
        let value: serde_json::Value = serde_json::from_str(&text).expect("value");
        assert_eq!(value["schema_version"], crate::SCHEMA_VERSION);
        assert_eq!(value["width"], 320);
        assert_eq!(value["frames"][0]["ordinal"], 1);
        let back: CaptureSet = serde_json::from_str(&text).expect("deserialize");
        assert_eq!(back, capture());
    }

    #[test]
    fn a_legacy_capture_reads_as_version_one_with_default_names_and_geometry() {
        let set: CaptureSet = serde_json::from_str(
            r#"{
                "film": "CTRY.FLM",
                "flm_bytes": 100,
                "frames": [
                    {"ordinal": 1, "film_tick": 9},
                    {"film_tick": 10, "frame_file": "other.idx"}
                ]
            }"#,
        )
        .expect("legacy capture");
        assert_eq!(set.schema_version, crate::SCHEMA_VERSION);
        assert_eq!(set.geometry.width, 320);
        assert_eq!(set.geometry.height, 200);
        assert_eq!(set.frames[0].ordinal, 1);
        assert_eq!(set.frames[0].frame_file, "tick_0001.idx");
        assert_eq!(set.frames[0].palette_file, "palettes_0001.json");
        assert_eq!(set.frames[1].ordinal, 2);
        assert_eq!(set.frames[1].frame_file, "other.idx");
        assert_eq!(set.frames[1].palette_file, "palettes_0002.json");
        set.validate().expect("legacy capture");
    }

    #[test]
    fn a_future_version_is_rejected() {
        let mut future = capture();
        future.schema_version = 9;
        assert!(matches!(
            future.validate(),
            Err(ArtifactError::UnsupportedVersion { found: 9, .. })
        ));
    }

    #[test]
    fn frames_must_name_a_basename() {
        let mut set = capture();
        set.frames[0].frame_file = "../tick_0001.idx".to_string();
        assert!(matches!(set.validate(), Err(ArtifactError::Frame { .. })));

        let mut set = capture();
        set.frames[0].palette_file = "palettes/0001.json".to_string();
        assert!(matches!(set.validate(), Err(ArtifactError::Frame { .. })));

        for bad in [
            "frames/",
            "frames/../tick_0001.idx",
            "frames/frames/tick_0001.idx",
        ] {
            let mut set = capture();
            set.frames[0].frame_file = bad.to_string();
            assert!(
                matches!(set.validate(), Err(ArtifactError::Frame { .. })),
                "{bad}"
            );
        }
    }

    #[test]
    fn a_frame_may_sit_under_the_frames_directory() {
        let mut set = capture();
        set.frames[0].frame_file = "frames/tick_0001.idx".to_string();
        set.frames[0].palette_file = "frames/palettes_0001.json".to_string();
        assert!(set.validate().is_ok());
    }

    #[test]
    fn a_frame_without_a_film_tick_names_its_ordinal() {
        let error = serde_json::from_str::<CaptureSet>(r#"{"frames": [{"film_tick": 1}, {}]}"#)
            .expect_err("untagged frame");
        assert!(
            error.to_string().contains("frame 2 has no film_tick"),
            "{error}"
        );
    }
}
