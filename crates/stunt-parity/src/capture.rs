//! A capture directory's description: capture ordinals, film clocks and file names.

use serde::{Deserialize, Serialize};

use crate::error::ArtifactError;
use crate::film::FilmId;
use crate::render::Geometry;

/// One captured frame's place in a capture directory.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct CapturedFrame {
    /// Capture order, 1-based; not a time axis.
    pub ordinal: u32,
    /// Film clock the captured page shows; parity matches on this.
    pub film_tick: u32,
    /// Raster file name, a basename inside the capture directory.
    pub frame_file: String,
    /// Palette file name, a basename inside the capture directory.
    pub palette_file: String,
}

/// Document written by the capture harness as `meta.json`.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct CaptureSet {
    /// Schema version when the writer recorded one; older captures lack it.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub schema_version: Option<u32>,
    /// Film the capture shows.
    pub film: FilmId,
    /// Raster geometry of every captured frame.
    pub geometry: Geometry,
    /// Captured frames in capture order.
    pub frames: Vec<CapturedFrame>,
}

impl CaptureSet {
    /// Checks the optional schema version, geometry and frame identity.
    pub fn validate(&self) -> Result<(), ArtifactError> {
        if let Some(version) = self.schema_version
            && version != crate::SCHEMA_VERSION
        {
            return Err(ArtifactError::UnsupportedVersion {
                found: version,
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
            if frame.frame_file.contains('/') || frame.frame_file.contains('\\') {
                return Err(ArtifactError::Frame {
                    ordinal: frame.ordinal,
                    reason: "frame_file must be a basename".to_string(),
                });
            }
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn capture(schema_version: Option<u32>) -> CaptureSet {
        CaptureSet {
            schema_version,
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
    fn legacy_captures_without_a_version_are_accepted() {
        capture(None).validate().expect("legacy capture");
        capture(Some(crate::SCHEMA_VERSION))
            .validate()
            .expect("current capture");
        let mut future = capture(Some(9));
        future.schema_version = Some(9);
        assert!(matches!(
            future.validate(),
            Err(ArtifactError::UnsupportedVersion { .. })
        ));
    }

    #[test]
    fn frames_must_name_a_basename() {
        let mut set = capture(None);
        set.frames[0].frame_file = "../tick_0001.idx".to_string();
        assert!(matches!(set.validate(), Err(ArtifactError::Frame { .. })));
    }
}
