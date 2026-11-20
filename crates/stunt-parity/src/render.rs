//! `render.json`: the description of one render directory.
//!
//! A render directory holds its planes in per-film-second zstd chunks: `frames.zst` (one palette
//! index byte per pixel), `layers.zst` (one little-endian u16 layer per pixel) and `palettes.zst`
//! (768-byte palettes). This record is the table of contents of those files; the adapters own the
//! bytes. It also lists each optional per-pixel plane the directory holds beside them (ADR 0052),
//! such as `shapes.zst`: a plane file it does not list is not part of the render.

use std::collections::BTreeMap;

use schemars::JsonSchema;
use serde::{Deserialize, Serialize};

use crate::error::ArtifactError;
use crate::film::FilmId;

/// Film ticks per chunk: one film second of the authored 50 Hz clock (`[I4]`).
pub const RENDER_CHUNK_TICKS: u32 = 50;

/// Bytes of one stored palette: 256 RGB triples.
pub const PALETTE_BYTES: usize = 768;

/// Raster geometry an artifact describes.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
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
    ///
    /// # Errors
    /// Returns [`ArtifactError::Geometry`] if `width` or `height` is zero, or `viewport_rows`
    /// is zero or taller than `height`.
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
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
pub struct RenderPalette {
    /// Film variable 13, the palette's night term.
    pub sky: u16,
    /// Film variable 14, palette brightness.
    pub brightness: u16,
    /// Film variable 15, palette saturation.
    pub saturation: u16,
}

/// Camera pose the frame was drawn from.
#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize, JsonSchema)]
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
#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize, JsonSchema)]
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
    /// The film shows credits at this tick, as `PLAYONE` draws them. Parity masks the
    /// cursor's palette index only when this is false, whatever the render drew.
    pub credits: bool,
}

/// A byte range of one of a render's plane files.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
pub struct StoreSpan {
    /// First byte of the chunk in the file.
    pub offset: u64,
    /// Compressed length of the chunk in bytes.
    pub length: u64,
}

/// One film second of a render: an independent zstd frame in each plane file.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
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

/// The `.zst` files every render holds, whose names no optional plane may take.
pub const CORE_FILES: [&str; 3] = ["frames.zst", "layers.zst", "palettes.zst"];

/// One optional plane file of a render, listed in its record so a reader can tell the file is
/// this render's own.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
pub struct PlaneListing {
    /// Lowercase hex SHA-256 of the whole file.
    pub sha256: String,
    /// The file's chunk for each entry of [`RenderRecord::chunks`], in the same order, tiling
    /// the file from offset 0.
    pub chunks: Vec<StoreSpan>,
}

impl PlaneListing {
    /// Bytes the listed chunks cover, which is the file's length; `None` when they overflow a
    /// u64.
    #[must_use]
    pub fn end(&self) -> Option<u64> {
        self.chunks
            .iter()
            .try_fold(0u64, |end, span| end.checked_add(span.length))
    }
}

/// Where a tick's planes are: its chunk, and its position within that chunk.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct TickSlot {
    /// Index into [`RenderRecord::chunks`].
    pub chunk: usize,
    /// Position of the tick's planes within the decoded chunk.
    pub position: usize,
}

/// What kind of adapter drew a render.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
#[serde(rename_all = "lowercase")]
pub enum AdapterClass {
    /// A GPU: any adapter that is not a CPU implementation.
    Hardware,
    /// A CPU implementation, such as lavapipe or WARP.
    Cpu,
}

/// The graphics adapter a render was drawn on.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
pub struct RenderAdapter {
    /// Adapter name as its driver reports it.
    pub name: String,
    /// Whether the adapter is a GPU or a CPU implementation.
    pub class: AdapterClass,
}

/// Document written beside a render directory's plane files, last.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema)]
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
    /// Each optional plane file the render holds, keyed by file name (`shapes.zst`); empty when
    /// it holds none.
    pub planes: BTreeMap<String, PlaneListing>,
    /// Adapter the frames were drawn on; absent in renders written before it was recorded.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub adapter: Option<RenderAdapter>,
}

impl RenderRecord {
    /// Checks the schema version, geometry, tick ordering, palette indices and chunk table.
    ///
    /// # Errors
    /// - [`ArtifactError::UnsupportedVersion`] if `schema_version` is not
    ///   [`crate::RENDER_SCHEMA_VERSION`].
    /// - [`ArtifactError::Geometry`] if the geometry fails [`Geometry::validate`].
    /// - [`ArtifactError::TickDuplicate`] or [`ArtifactError::TickOrder`] if two neighbouring
    ///   ticks carry the same film clock or descend.
    /// - [`ArtifactError::RenderStore`] if a tick's `palette_index` is not below `palette_count`,
    ///   or the chunk table does not cover the ticks second by second with contiguous spans of
    ///   both plane files, or a plane listing has a name that is not a bare `.zst` file name or
    ///   is one of [`CORE_FILES`], a digest that is not 64 lowercase hex digits, or chunks that
    ///   do not pair one to one with the chunk table and tile its file from offset 0. The plane
    ///   files are not read; checking their lengths and digests is the caller's.
    pub fn validate(&self) -> Result<(), ArtifactError> {
        if self.schema_version != crate::RENDER_SCHEMA_VERSION {
            return Err(ArtifactError::UnsupportedVersion {
                found: self.schema_version,
                expected: crate::RENDER_SCHEMA_VERSION,
            });
        }
        self.geometry.validate()?;
        let pairs = self.ticks.iter().zip(self.ticks.iter().skip(1));
        for (index, (prev, next)) in pairs.enumerate() {
            match prev.tick.cmp(&next.tick) {
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
        self.validate_chunks()?;
        self.validate_planes()
    }

    /// Checks each plane listing's name, digest and chunk spans.
    fn validate_planes(&self) -> Result<(), ArtifactError> {
        for (name, listing) in &self.planes {
            let at = |reason: String| ArtifactError::store(format!("planes[{name:?}]: {reason}"));
            let bare = name.strip_suffix(".zst").is_some_and(|stem| {
                !stem.is_empty()
                    && stem
                        .bytes()
                        .all(|byte| byte.is_ascii_alphanumeric() || byte == b'_' || byte == b'-')
            });
            if !bare {
                return Err(at(
                    "is not a bare file name of letters, digits, `_` and `-` ending `.zst`"
                        .to_string(),
                ));
            }
            if CORE_FILES.contains(&name.as_str()) {
                return Err(at("names a file every render holds".to_string()));
            }
            if listing.sha256.len() != 64
                || !listing
                    .sha256
                    .bytes()
                    .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
            {
                return Err(at(format!(
                    "sha256 {:?} is not 64 lowercase hex digits",
                    listing.sha256
                )));
            }
            if listing.chunks.len() != self.chunks.len() {
                return Err(at(format!(
                    "lists {} chunks but the chunk table has {}",
                    listing.chunks.len(),
                    self.chunks.len()
                )));
            }
            let mut end = 0u64;
            for (number, span) in listing.chunks.iter().enumerate() {
                if span.offset != end {
                    return Err(at(format!(
                        "chunks[{number}] offset {} does not continue the previous chunk \
                         (expected {end})",
                        span.offset
                    )));
                }
                end = end.checked_add(span.length).ok_or_else(|| {
                    at(format!(
                        "chunks[{number}] runs past the largest file offset"
                    ))
                })?;
            }
        }
        Ok(())
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
            let (Some(index), Some(layer)) = (
                index_end.checked_add(chunk.index.length),
                layer_end.checked_add(chunk.layer.length),
            ) else {
                return Err(at("lengths run past the largest file offset".to_string()));
            };
            index_end = index;
            layer_end = layer;
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
