//! `render.json`: the description of one render directory.

use serde::{Deserialize, Serialize};

use crate::error::ArtifactError;
use crate::film::FilmId;

/// Raster geometry an artifact describes.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Geometry {
    /// Width in pixels.
    pub width: u32,
    /// Height in pixels.
    pub height: u32,
    /// Rows the 3D scene was drawn into when the render narrowed its viewport.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub viewport_rows: Option<u32>,
}

impl Geometry {
    /// Checks that the raster is positive and the viewport fits inside it.
    pub fn validate(&self) -> Result<(), ArtifactError> {
        if self.width == 0 || self.height == 0 {
            return Err(ArtifactError::geometry("width and height must be positive"));
        }
        if let Some(rows) = self.viewport_rows
            && (rows == 0 || rows > self.height)
        {
            return Err(ArtifactError::geometry(
                "viewport_rows must be between 1 and height",
            ));
        }
        Ok(())
    }
}

/// Film palette controls the frame at a tick was drawn with.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub struct RenderPalette {
    /// Film variable 13, the palette's night term.
    pub sky: u16,
    /// Film variable 14, palette brightness.
    pub brightness: u16,
    /// Film variable 15, palette saturation.
    pub saturation: u16,
}

/// Camera pose the frame was drawn from.
#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize)]
pub struct CameraPose {
    /// Camera world position in metres.
    pub eye: [f32; 3],
    /// Look-at point in metres.
    pub target: [f32; 3],
    /// Vertical field of view in degrees.
    pub fov_degrees: f32,
    /// View roll about the forward axis in radians.
    pub roll_radians: f32,
}

/// One rendered tick: the film clock its files are named for.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct RenderTick {
    /// Film clock the `tick_NNNNN` files are named for.
    pub tick: u32,
    /// Controls the frame was drawn with.
    pub palette: RenderPalette,
    /// Camera the frame was drawn from.
    pub camera: CameraPose,
}

/// Document written beside a render directory's frames, last.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct RenderRecord {
    /// Schema version; see [`crate::SCHEMA_VERSION`].
    pub schema_version: u32,
    /// Film the render was made from.
    pub film: FilmId,
    /// Raster geometry of every frame.
    pub geometry: Geometry,
    /// One entry per whole-tick frame, in strictly ascending film-clock order.
    pub ticks: Vec<RenderTick>,
}

impl RenderRecord {
    /// Checks the schema version, geometry and tick ordering.
    pub fn validate(&self) -> Result<(), ArtifactError> {
        if self.schema_version != crate::SCHEMA_VERSION {
            return Err(ArtifactError::UnsupportedVersion {
                found: self.schema_version,
                expected: crate::SCHEMA_VERSION,
            });
        }
        self.geometry.validate()?;
        for (index, pair) in self.ticks.windows(2).enumerate() {
            match pair[0].tick.cmp(&pair[1].tick) {
                std::cmp::Ordering::Less => {}
                std::cmp::Ordering::Equal => {
                    return Err(ArtifactError::TickDuplicate { index: index + 1 });
                }
                std::cmp::Ordering::Greater => {
                    return Err(ArtifactError::TickOrder { index: index + 1 });
                }
            }
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn tick(tick: u32) -> RenderTick {
        RenderTick {
            tick,
            palette: RenderPalette {
                sky: 0,
                brightness: 0x8000,
                saturation: 0x8000,
            },
            camera: CameraPose {
                eye: [0.0, 10.0, 50.0],
                target: [0.0; 3],
                fov_degrees: 45.0,
                roll_radians: 0.0,
            },
        }
    }

    fn record(ticks: Vec<u32>) -> RenderRecord {
        RenderRecord {
            schema_version: crate::SCHEMA_VERSION,
            film: FilmId::default(),
            geometry: Geometry {
                width: 320,
                height: 200,
                viewport_rows: Some(185),
            },
            ticks: ticks.into_iter().map(tick).collect(),
        }
    }

    #[test]
    fn a_valid_record_passes_and_round_trips() {
        let record = record(vec![0, 1, 2]);
        record.validate().expect("valid");
        let text = serde_json::to_string(&record).expect("serialize");
        let back: RenderRecord = serde_json::from_str(&text).expect("deserialize");
        assert_eq!(back, record);
    }

    #[test]
    fn version_ordering_and_geometry_are_checked() {
        let mut wrong = record(vec![0]);
        wrong.schema_version = 9;
        assert!(matches!(
            wrong.validate(),
            Err(ArtifactError::UnsupportedVersion { found: 9, .. })
        ));

        let unordered = record(vec![1, 0]);
        assert!(matches!(
            unordered.validate(),
            Err(ArtifactError::TickOrder { index: 1 })
        ));

        let duplicate = record(vec![1, 1]);
        assert!(matches!(
            duplicate.validate(),
            Err(ArtifactError::TickDuplicate { index: 1 })
        ));

        let mut bad_geometry = record(vec![]);
        bad_geometry.geometry.viewport_rows = Some(201);
        assert!(matches!(
            bad_geometry.validate(),
            Err(ArtifactError::Geometry { .. })
        ));
    }

    #[test]
    fn viewport_rows_may_be_absent() {
        let geometry = Geometry {
            width: 320,
            height: 240,
            viewport_rows: None,
        };
        geometry.validate().expect("full-target render");
        let value = serde_json::to_value(&geometry).expect("serialize");
        assert!(value.get("viewport_rows").is_none());
    }
}
