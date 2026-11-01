//! `render.json`: the description of one render directory.
//!
//! A render directory holds its planes in per-film-second zstd chunks: `frames.zst` (one palette
//! index byte per pixel), `layers.zst` (one little-endian u16 layer per pixel) and `palettes.zst`
//! (768-byte palettes). This record is the table of contents of those files; the adapters own the
//! bytes.

use serde::{Deserialize, Serialize};

use crate::error::ArtifactError;
use crate::film::FilmId;

/// Film ticks per chunk: one film second of the authored 50 Hz clock (`[I4]`).
pub const RENDER_CHUNK_TICKS: u32 = 50;

/// Bytes of one stored palette: 256 RGB triples.
pub const PALETTE_BYTES: usize = 768;

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

    /// Pixels in one plane: the full raster, not the narrowed viewport.
    #[must_use]
    pub fn pixel_count(&self) -> usize {
        self.width as usize * self.height as usize
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

/// One rendered tick: its film clock, how it was drawn, and which stored palette it shows.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct RenderTick {
    /// Film clock of the frame (0-based 50 Hz tick).
    pub tick: u32,
    /// Controls the frame was drawn with.
    pub palette: RenderPalette,
    /// Camera the frame was drawn from.
    pub camera: CameraPose,
    /// Index into `palettes.zst` of the colours the frame shows: its picture is
    /// `palette[index]` for every pixel.
    pub palette_index: u32,
}

/// A byte range of one of a render's plane files.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub struct StoreSpan {
    /// First byte of the chunk in the file.
    pub offset: u64,
    /// Compressed length of the chunk in bytes.
    pub length: u64,
}

/// One film second of a render: an independent zstd frame in each plane file.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub struct RenderChunk {
    /// Film second the chunk holds: the ticks with `tick / RENDER_CHUNK_TICKS == second`.
    pub second: u32,
    /// Ticks in the chunk, consecutive in the record and in film-clock order.
    pub ticks: u32,
    /// The chunk in `frames.zst`.
    pub index: StoreSpan,
    /// The chunk in `layers.zst`.
    pub layer: StoreSpan,
}

/// Where a tick's planes are: its chunk, and its position within that chunk.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct TickSlot {
    /// Index into [`RenderRecord::chunks`].
    pub chunk: usize,
    /// Position of the tick's planes within the decoded chunk.
    pub position: usize,
}

/// Document written beside a render directory's plane files, last.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct RenderRecord {
    /// Schema version; see [`crate::RENDER_SCHEMA_VERSION`].
    pub schema_version: u32,
    /// Film the render was made from.
    pub film: FilmId,
    /// Raster geometry of every frame.
    pub geometry: Geometry,
    /// One entry per whole-tick frame, in strictly ascending film-clock order.
    pub ticks: Vec<RenderTick>,
    /// Palettes stored in `palettes.zst`, [`PALETTE_BYTES`] each.
    pub palette_count: u32,
    /// One entry per film second that holds a tick, ascending.
    pub chunks: Vec<RenderChunk>,
}

impl RenderRecord {
    /// Checks the schema version, geometry, tick ordering, palette indices and chunk table.
    pub fn validate(&self) -> Result<(), ArtifactError> {
        if self.schema_version != crate::RENDER_SCHEMA_VERSION {
            return Err(ArtifactError::UnsupportedVersion {
                found: self.schema_version,
                expected: crate::RENDER_SCHEMA_VERSION,
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
        for (index, tick) in self.ticks.iter().enumerate() {
            if tick.palette_index >= self.palette_count {
                return Err(ArtifactError::store(format!(
                    "ticks[{index}].palette_index {} is not below palette_count {}",
                    tick.palette_index, self.palette_count
                )));
            }
        }
        self.validate_chunks()
    }

    /// Checks that the chunks cover the ticks second by second and tile both files.
    fn validate_chunks(&self) -> Result<(), ArtifactError> {
        let mut next_tick = 0usize;
        let mut index_end = 0u64;
        let mut layer_end = 0u64;
        let mut previous_second = None;
        for (number, chunk) in self.chunks.iter().enumerate() {
            let at = |reason: String| ArtifactError::store(format!("chunks[{number}]: {reason}"));
            if previous_second.is_some_and(|second| chunk.second <= second) {
                return Err(at(format!(
                    "second {} does not follow the previous chunk's",
                    chunk.second
                )));
            }
            previous_second = Some(chunk.second);
            if chunk.ticks == 0 {
                return Err(at("holds no ticks".to_string()));
            }
            if chunk.index.offset != index_end || chunk.layer.offset != layer_end {
                return Err(at(format!(
                    "offsets {} and {} do not continue the previous chunk (expected {index_end} \
                     and {layer_end})",
                    chunk.index.offset, chunk.layer.offset
                )));
            }
            index_end += chunk.index.length;
            layer_end += chunk.layer.length;
            let end = next_tick + chunk.ticks as usize;
            let Some(ticks) = self.ticks.get(next_tick..end) else {
                return Err(at(format!(
                    "claims {} ticks but only {} remain",
                    chunk.ticks,
                    self.ticks.len() - next_tick
                )));
            };
            if let Some(stray) = ticks
                .iter()
                .find(|tick| tick.tick / RENDER_CHUNK_TICKS != chunk.second)
            {
                return Err(at(format!(
                    "holds tick {}, which is not in second {}",
                    stray.tick, chunk.second
                )));
            }
            next_tick = end;
        }
        if next_tick != self.ticks.len() {
            return Err(ArtifactError::store(format!(
                "the chunks hold {next_tick} ticks but the record lists {}",
                self.ticks.len()
            )));
        }
        Ok(())
    }

    /// Where `tick`'s planes are stored, or `None` when the render does not hold it.
    ///
    /// Assumes a validated record.
    #[must_use]
    pub fn locate(&self, tick: u32) -> Option<TickSlot> {
        let row = self
            .ticks
            .binary_search_by_key(&tick, |entry| entry.tick)
            .ok()?;
        let mut first = 0usize;
        for (chunk, entry) in self.chunks.iter().enumerate() {
            let end = first + entry.ticks as usize;
            if row < end {
                return Some(TickSlot {
                    chunk,
                    position: row - first,
                });
            }
            first = end;
        }
        None
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
            palette_index: 0,
        }
    }

    /// A record whose chunk table matches `ticks`, with ten bytes per chunk in each file.
    fn record(ticks: Vec<u32>) -> RenderRecord {
        let mut chunks: Vec<RenderChunk> = Vec::new();
        for &value in &ticks {
            let second = value / RENDER_CHUNK_TICKS;
            match chunks.last_mut() {
                Some(chunk) if chunk.second == second => chunk.ticks += 1,
                _ => {
                    let offset = 10 * chunks.len() as u64;
                    chunks.push(RenderChunk {
                        second,
                        ticks: 1,
                        index: StoreSpan { offset, length: 10 },
                        layer: StoreSpan { offset, length: 10 },
                    });
                }
            }
        }
        RenderRecord {
            schema_version: crate::RENDER_SCHEMA_VERSION,
            film: FilmId::default(),
            geometry: Geometry {
                width: 320,
                height: 200,
                viewport_rows: Some(185),
            },
            ticks: ticks.into_iter().map(tick).collect(),
            palette_count: 1,
            chunks,
        }
    }

    fn store_error(record: &RenderRecord) -> String {
        match record.validate() {
            Err(ArtifactError::RenderStore { reason }) => reason,
            other => panic!("expected a render store error, got {other:?}"),
        }
    }

    #[test]
    fn a_valid_record_passes_and_round_trips() {
        let record = record(vec![0, 1, 2, 120, 149]);
        record.validate().expect("valid");
        let text = serde_json::to_string(&record).expect("serialize");
        let back: RenderRecord = serde_json::from_str(&text).expect("deserialize");
        assert_eq!(back, record);
    }

    #[test]
    fn version_ordering_and_geometry_are_checked() {
        let mut wrong = record(vec![0]);
        wrong.schema_version = 1;
        assert!(matches!(
            wrong.validate(),
            Err(ArtifactError::UnsupportedVersion {
                found: 1,
                expected: 2
            })
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
    fn a_palette_index_must_name_a_stored_palette() {
        let mut bad = record(vec![0, 1]);
        bad.ticks[1].palette_index = 1;
        assert!(store_error(&bad).contains("ticks[1].palette_index 1"));
    }

    #[test]
    fn chunks_must_follow_the_seconds_of_their_ticks() {
        let mut stray = record(vec![0, 1, 50]);
        stray.chunks[0].ticks = 3;
        stray.chunks.pop();
        assert!(store_error(&stray).contains("holds tick 50, which is not in second 0"));

        let mut descending = record(vec![0, 50]);
        descending.chunks[1].second = 0;
        assert!(store_error(&descending).contains("chunks[1]: second 0"));

        let mut short = record(vec![0, 1, 50]);
        short.chunks.pop();
        assert!(store_error(&short).contains("hold 2 ticks but the record lists 3"));

        let mut long = record(vec![0, 50]);
        long.chunks[1].ticks = 2;
        assert!(store_error(&long).contains("claims 2 ticks but only 1 remain"));

        let mut empty = record(vec![0]);
        empty.chunks[0].ticks = 0;
        assert!(store_error(&empty).contains("holds no ticks"));
    }

    #[test]
    fn chunks_must_tile_both_files() {
        let mut gap = record(vec![0, 50]);
        gap.chunks[1].index.offset = 11;
        assert!(store_error(&gap).contains("chunks[1]: offsets 11 and 10"));

        let mut late_start = record(vec![0]);
        late_start.chunks[0].layer.offset = 4;
        assert!(store_error(&late_start).contains("offsets 0 and 4"));
    }

    #[test]
    fn an_empty_render_has_no_chunks() {
        record(vec![]).validate().expect("an empty render is valid");
    }

    #[test]
    fn locate_finds_a_tick_by_chunk_and_position() {
        let record = record(vec![3, 7, 120, 149, 150]);
        assert_eq!(
            record.locate(7),
            Some(TickSlot {
                chunk: 0,
                position: 1
            })
        );
        assert_eq!(
            record.locate(149),
            Some(TickSlot {
                chunk: 1,
                position: 1
            })
        );
        assert_eq!(
            record.locate(150),
            Some(TickSlot {
                chunk: 2,
                position: 0
            })
        );
        assert_eq!(record.locate(8), None);
    }

    #[test]
    fn viewport_rows_may_be_absent() {
        let geometry = Geometry {
            width: 320,
            height: 240,
            viewport_rows: None,
        };
        geometry.validate().expect("full-target render");
        assert_eq!(geometry.pixel_count(), 76_800);
        let value = serde_json::to_value(&geometry).expect("serialize");
        assert!(value.get("viewport_rows").is_none());
    }
}
