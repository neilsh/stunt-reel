//! The render store: the one place a render's plane files are encoded and decoded (ADR 0027).
//!
//! A render directory holds `frames.zst` (one palette-index byte per pixel), `layers.zst` (one
//! little-endian u16 layer per pixel) and `palettes.zst` (768-byte palettes). Each plane file is
//! a run of independent zstd frames, one per film second, holding that second's ticks back to
//! back; `render.json`, written last, is their table of contents. `preview/sec_NNNN.png` shows
//! each second's first tick for people. A render the Rust store writes also holds `shapes.zst`
//! beside them: a run of `[u64 LE packed length][zstd frame]` records, one per chunk in the
//! chunk table's order, each frame that second's ticks back to back with a little-endian u16
//! per pixel, the shape word of `stunt_render::RenderedPage::shapes`. Only the Rust store
//! reads and writes it; `render.json` does not list it, and a render without the file (the
//! Python writer's, which removes a stale one, or one older than the file) has no shape plane.
//! The Python mirror is `RenderStore` in `python/stunt_reel/parity_artifacts/`.

use std::collections::HashMap;
use std::fs::{self, File};
use std::io::{BufWriter, Read as _, Seek as _, SeekFrom, Write as _};
use std::path::{Path, PathBuf};

use stunt_parity::{
    Geometry, PALETTE_BYTES, RENDER_CHUNK_TICKS, RenderChunk, RenderRecord, RenderTick, StoreSpan,
};

use crate::parity_artifacts::{self, AdapterError};

/// Index planes, one byte per pixel.
pub(crate) const INDEX_FILE: &str = "frames.zst";
/// Layer planes, one little-endian u16 per pixel.
pub(crate) const LAYER_FILE: &str = "layers.zst";
/// Shape planes, one little-endian u16 per pixel, each chunk behind its u64 packed length.
pub(crate) const SHAPE_FILE: &str = "shapes.zst";
/// The distinct palettes, [`PALETTE_BYTES`] each, as one zstd frame.
pub(crate) const PALETTE_FILE: &str = "palettes.zst";
/// One indexed PNG per film second, for people.
pub(crate) const PREVIEW_DIR: &str = "preview";
/// zstd level of every chunk: fast to write, and the ratio levels above it add little.
const ZSTD_LEVEL: i32 = 3;

/// A 256-entry RGB palette.
pub(crate) type Palette = [(u8, u8, u8); 256];

/// The colour `palette` gives `index`.
#[expect(
    clippy::indexing_slicing,
    reason = "a u8 index cannot leave the 256-entry palette"
)]
pub(crate) fn palette_rgb(palette: &Palette, index: u8) -> (u8, u8, u8) {
    palette[usize::from(index)]
}

/// A store that could not be written or read, naming the file.
#[derive(Debug, thiserror::Error)]
pub enum StoreError {
    /// Reading or writing a file failed.
    #[error("{path}: {source}")]
    Io {
        /// File the operation touched.
        path: PathBuf,
        /// Underlying I/O error.
        source: std::io::Error,
    },
    /// `render.json` is missing, unreadable or from another schema version.
    #[error("{source}; re-render {dir} with the current `stuntreel --headless --out-dir`")]
    Document {
        /// Render directory.
        dir: PathBuf,
        /// What the adapter could not read.
        source: AdapterError,
    },
    /// A plane, palette or chunk does not have the size or content the record promises.
    #[error("{path}: {message}")]
    Corrupt {
        /// File (or render directory) the error names.
        path: PathBuf,
        /// What is wrong with it.
        message: String,
    },
    /// Writing `render.json` failed.
    #[error(transparent)]
    Record(AdapterError),
    /// The render does not hold the tick asked for.
    #[error("{dir} holds no render of tick {tick}")]
    MissingTick {
        /// Render directory.
        dir: PathBuf,
        /// Film tick asked for.
        tick: u32,
    },
}

fn io(path: &Path) -> impl FnOnce(std::io::Error) -> StoreError + '_ {
    move |source| StoreError::Io {
        path: path.to_path_buf(),
        source,
    }
}

fn corrupt(path: &Path, message: impl Into<String>) -> StoreError {
    StoreError::Corrupt {
        path: path.to_path_buf(),
        message: message.into(),
    }
}

/// `words` as little-endian u16s, or the first word that does not fit, named as `what` of
/// `tick` in `path`.
fn u16_bytes(words: &[u32], path: &Path, tick: u32, what: &str) -> Result<Vec<u8>, StoreError> {
    let mut bytes = Vec::with_capacity(words.len() * 2);
    for (pixel, &word) in words.iter().enumerate() {
        let word = u16::try_from(word).map_err(|_| {
            corrupt(
                path,
                format!("tick {tick} pixel {pixel} {what} {word} does not fit a u16"),
            )
        })?;
        bytes.extend_from_slice(&word.to_le_bytes());
    }
    Ok(bytes)
}

/// The film second a tick's planes are stored in.
fn second_of(tick: u32) -> u32 {
    tick / RENDER_CHUNK_TICKS
}

/// Checks that a page's picture is `palette[index]` at every pixel, which is what lets the
/// store keep the index plane and the palette instead of the picture.
pub(crate) fn check_derivable(
    palette: &Palette,
    indices: &[u8],
    rgba: &[u8],
    width: u32,
) -> Result<(), String> {
    if rgba.len() != indices.len() * 4 {
        return Err(format!(
            "the picture holds {} RGBA bytes for {} pixels",
            rgba.len(),
            indices.len()
        ));
    }
    for (pixel, (&index, colour)) in indices.iter().zip(rgba.as_chunks::<4>().0).enumerate() {
        let expected = palette_rgb(palette, index);
        if (colour[0], colour[1], colour[2]) != expected {
            let width = width.max(1) as usize;
            return Err(format!(
                "pixel ({}, {}) is {:?} but palette[{index}] is {expected:?}, so the picture is \
                 not derivable from the index plane",
                pixel % width,
                pixel / width,
                (colour[0], colour[1], colour[2])
            ));
        }
    }
    Ok(())
}

/// The second being gathered before it is compressed.
struct OpenChunk {
    second: u32,
    ticks: u32,
    indices: Vec<u8>,
    layers: Vec<u8>,
    shapes: Vec<u8>,
}

/// The plane files, opened on the first tick.
struct PlaneFiles {
    index: BufWriter<File>,
    layer: BufWriter<File>,
    shape: BufWriter<File>,
}

/// What a finished store adds to its `render.json`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) struct StoreTable {
    /// Palettes written to `palettes.zst`.
    pub(crate) palette_count: u32,
    /// One entry per film second written.
    pub(crate) chunks: Vec<RenderChunk>,
}

/// Writes a render's planes in tick order, a chunk per film second.
///
/// Nothing is created until the first tick, so a run with no whole-tick frame leaves no store.
/// The writer replaces its own files and leaves anything else in the directory.
pub(crate) struct StoreWriter {
    dir: PathBuf,
    geometry: Geometry,
    files: Option<PlaneFiles>,
    index_end: u64,
    layer_end: u64,
    last_tick: Option<u32>,
    palettes: Vec<Palette>,
    palette_ids: HashMap<Palette, u32>,
    open: Option<OpenChunk>,
    chunks: Vec<RenderChunk>,
}

impl StoreWriter {
    /// A writer for `dir`, which must exist, at `geometry`.
    pub(crate) fn new(dir: &Path, geometry: &Geometry) -> Self {
        Self {
            dir: dir.to_path_buf(),
            geometry: *geometry,
            files: None,
            index_end: 0,
            layer_end: 0,
            last_tick: None,
            palettes: Vec::new(),
            palette_ids: HashMap::new(),
            open: None,
            chunks: Vec::new(),
        }
    }

    /// Appends one tick's planes and returns the index of its palette in the store.
    ///
    /// Ticks must be strictly ascending. The layer and shape files hold a u16 per pixel, so a
    /// layer or shape word that does not fit is an error rather than a silent truncation.
    pub(crate) fn push(
        &mut self,
        tick: u32,
        palette: &Palette,
        indices: &[u8],
        layers: &[u32],
        shapes: &[u32],
    ) -> Result<u32, StoreError> {
        let expected = self.geometry.pixel_count();
        let at = self.dir.join(INDEX_FILE);
        if indices.len() != expected || layers.len() != expected || shapes.len() != expected {
            return Err(corrupt(
                &at,
                format!(
                    "tick {tick} has {} indices, {} layers and {} shapes, expected {expected} \
                     for {}x{}",
                    indices.len(),
                    layers.len(),
                    shapes.len(),
                    self.geometry.width,
                    self.geometry.height
                ),
            ));
        }
        if self.last_tick.is_some_and(|last| tick <= last) {
            return Err(corrupt(
                &at,
                format!("tick {tick} does not follow tick {:?}", self.last_tick),
            ));
        }
        let layer_bytes = u16_bytes(layers, &self.dir.join(LAYER_FILE), tick, "layer")?;
        let shape_bytes = u16_bytes(shapes, &self.dir.join(SHAPE_FILE), tick, "shape word")?;
        if self.files.is_none() {
            self.files = Some(self.create_files()?);
        }
        let second = second_of(tick);
        if self.open.as_ref().is_some_and(|open| open.second != second) {
            self.close_chunk()?;
        }
        if self.open.is_none() {
            self.write_preview(second, palette, indices)?;
        }
        let open = self.open.get_or_insert_with(|| OpenChunk {
            second,
            ticks: 0,
            indices: Vec::with_capacity(expected * RENDER_CHUNK_TICKS as usize),
            layers: Vec::with_capacity(expected * 2 * RENDER_CHUNK_TICKS as usize),
            shapes: Vec::with_capacity(expected * 2 * RENDER_CHUNK_TICKS as usize),
        });
        open.ticks += 1;
        open.indices.extend_from_slice(indices);
        open.layers.extend_from_slice(&layer_bytes);
        open.shapes.extend_from_slice(&shape_bytes);
        self.last_tick = Some(tick);
        self.palette_id(palette)
    }

    /// Writes the last chunk and `palettes.zst`; `None` when no tick was pushed.
    pub(crate) fn finish(mut self) -> Result<Option<StoreTable>, StoreError> {
        self.close_chunk()?;
        let Some(files) = self.files.take() else {
            return Ok(None);
        };
        for (mut file, name) in [
            (files.index, INDEX_FILE),
            (files.layer, LAYER_FILE),
            (files.shape, SHAPE_FILE),
        ] {
            file.flush().map_err(io(&self.dir.join(name)))?;
        }
        let path = self.dir.join(PALETTE_FILE);
        let mut raw = Vec::with_capacity(self.palettes.len() * PALETTE_BYTES);
        for palette in &self.palettes {
            for &(r, g, b) in palette {
                raw.extend_from_slice(&[r, g, b]);
            }
        }
        let packed = zstd::bulk::compress(&raw, ZSTD_LEVEL).map_err(io(&path))?;
        fs::write(&path, packed).map_err(io(&path))?;
        Ok(Some(StoreTable {
            palette_count: u32::try_from(self.palettes.len())
                .map_err(|_| corrupt(&path, "more than u32::MAX palettes"))?,
            chunks: self.chunks,
        }))
    }

    fn create_files(&self) -> Result<PlaneFiles, StoreError> {
        let preview = self.dir.join(PREVIEW_DIR);
        if preview.is_dir() {
            fs::remove_dir_all(&preview).map_err(io(&preview))?;
        }
        fs::create_dir_all(&preview).map_err(io(&preview))?;
        let create = |name: &str| {
            let path = self.dir.join(name);
            File::create(&path).map(BufWriter::new).map_err(io(&path))
        };
        Ok(PlaneFiles {
            index: create(INDEX_FILE)?,
            layer: create(LAYER_FILE)?,
            shape: create(SHAPE_FILE)?,
        })
    }

    fn palette_id(&mut self, palette: &Palette) -> Result<u32, StoreError> {
        if let Some(&id) = self.palette_ids.get(palette) {
            return Ok(id);
        }
        let id = u32::try_from(self.palettes.len())
            .map_err(|_| corrupt(&self.dir.join(PALETTE_FILE), "more than u32::MAX palettes"))?;
        self.palettes.push(*palette);
        self.palette_ids.insert(*palette, id);
        Ok(id)
    }

    fn close_chunk(&mut self) -> Result<(), StoreError> {
        let (Some(open), Some(files)) = (self.open.take(), self.files.as_mut()) else {
            return Ok(());
        };
        let mut spans = [StoreSpan {
            offset: 0,
            length: 0,
        }; 2];
        for (span, (raw, file, end, name)) in spans.iter_mut().zip([
            (
                &open.indices,
                &mut files.index,
                &mut self.index_end,
                INDEX_FILE,
            ),
            (
                &open.layers,
                &mut files.layer,
                &mut self.layer_end,
                LAYER_FILE,
            ),
        ]) {
            let path = self.dir.join(name);
            let packed = zstd::bulk::compress(raw, ZSTD_LEVEL).map_err(io(&path))?;
            file.write_all(&packed).map_err(io(&path))?;
            *span = StoreSpan {
                offset: *end,
                length: packed.len() as u64,
            };
            *end += packed.len() as u64;
        }
        // The shape file's records follow the chunk table's order and carry their own length.
        let path = self.dir.join(SHAPE_FILE);
        let packed = zstd::bulk::compress(&open.shapes, ZSTD_LEVEL).map_err(io(&path))?;
        for part in [&(packed.len() as u64).to_le_bytes()[..], &packed] {
            files.shape.write_all(part).map_err(io(&path))?;
        }
        self.chunks.push(RenderChunk {
            second: open.second,
            ticks: open.ticks,
            index: spans[0],
            layer: spans[1],
        });
        Ok(())
    }

    fn write_preview(
        &self,
        second: u32,
        palette: &Palette,
        indices: &[u8],
    ) -> Result<(), StoreError> {
        let path = self
            .dir
            .join(PREVIEW_DIR)
            .join(format!("sec_{second:04}.png"));
        let file = File::create(&path).map_err(io(&path))?;
        let mut encoder = png::Encoder::new(
            BufWriter::new(file),
            self.geometry.width,
            self.geometry.height,
        );
        encoder.set_color(png::ColorType::Indexed);
        encoder.set_depth(png::BitDepth::Eight);
        encoder.set_palette(
            palette
                .iter()
                .flat_map(|&(r, g, b)| [r, g, b])
                .collect::<Vec<u8>>(),
        );
        let encode = |error: png::EncodingError| corrupt(&path, error.to_string());
        let mut writer = encoder.write_header().map_err(encode)?;
        writer.write_image_data(indices).map_err(encode)?;
        writer.finish().map_err(encode)
    }
}

/// One stored tick: its planes and the palette its picture is drawn in.
#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) struct StoredFrame {
    /// One palette index per pixel, top row first, over the full raster.
    pub(crate) indices: Vec<u8>,
    /// One layer id per pixel.
    pub(crate) layers: Vec<u16>,
    /// One shape word per pixel (`shape id + 1` of the prop drawing it, 0 for none); `None` when
    /// the render has no `shapes.zst`.
    pub(crate) shapes: Option<Vec<u16>>,
    /// The colours of the frame: its picture is `palette[index]`.
    pub(crate) palette: Palette,
}

impl StoredFrame {
    /// The frame's picture as tightly packed RGB bytes.
    pub(crate) fn rgb(&self) -> Vec<u8> {
        self.indices
            .iter()
            .flat_map(|&index| {
                let (r, g, b) = palette_rgb(&self.palette, index);
                [r, g, b]
            })
            .collect()
    }
}

/// A decoded chunk: its position in the record and its two raw plane runs.
struct DecodedChunk {
    chunk: usize,
    indices: Vec<u8>,
    layers: Vec<u8>,
    shapes: Option<Vec<u8>>,
}

/// Reads a render directory's store, keeping the last decoded chunk.
pub(crate) struct RenderStore {
    dir: PathBuf,
    record: RenderRecord,
    palettes: Vec<Palette>,
    /// The packed span of each chunk's record in `shapes.zst`; `None` without the file.
    shape_spans: Option<Vec<StoreSpan>>,
    cached: Option<DecodedChunk>,
}

impl RenderStore {
    /// Opens `dir`: reads and validates `render.json`, checks the plane files against its chunk
    /// table and reads the palettes.
    pub(crate) fn open(dir: &Path) -> Result<Self, StoreError> {
        let record =
            parity_artifacts::read_render_record(dir).map_err(|source| StoreError::Document {
                dir: dir.to_path_buf(),
                source,
            })?;
        let ends = record.chunks.last().map_or((0, 0), |chunk| {
            (
                chunk.index.offset + chunk.index.length,
                chunk.layer.offset + chunk.layer.length,
            )
        });
        if !record.ticks.is_empty() {
            for (name, end) in [(INDEX_FILE, ends.0), (LAYER_FILE, ends.1)] {
                let path = dir.join(name);
                let size = fs::metadata(&path).map_err(io(&path))?.len();
                if size != end {
                    return Err(corrupt(
                        &path,
                        format!("holds {size} bytes but render.json's chunks end at {end}"),
                    ));
                }
            }
        }
        let palettes = read_palettes(&dir.join(PALETTE_FILE), record.palette_count)?;
        let shape_spans = read_shape_spans(&dir.join(SHAPE_FILE), record.chunks.len())?;
        Ok(Self {
            dir: dir.to_path_buf(),
            record,
            palettes,
            shape_spans,
            cached: None,
        })
    }

    /// The validated `render.json`.
    pub(crate) fn record(&self) -> &RenderRecord {
        &self.record
    }

    /// Whether the render holds film tick `tick`.
    pub(crate) fn holds(&self, tick: u32) -> bool {
        self.record.locate(tick).is_some()
    }

    /// The planes and palette of film tick `tick`, decoding its chunk unless it is cached.
    pub(crate) fn frame(&mut self, tick: u32) -> Result<StoredFrame, StoreError> {
        let slot = self
            .record
            .locate(tick)
            .ok_or_else(|| StoreError::MissingTick {
                dir: self.dir.clone(),
                tick,
            })?;
        let decoded = match self.cached.take() {
            Some(cached) if cached.chunk == slot.chunk => cached,
            _ => self.decode(slot.chunk)?,
        };
        let cached = self.cached.insert(decoded);
        let pixels = self.record.geometry.pixel_count();
        // `decode` checked each plane holds the chunk's ticks, and `locate` placed the tick in it.
        let outside = |name: &str| {
            corrupt(
                &self.dir.join(name),
                format!("tick {tick} lies outside its decoded chunk"),
            )
        };
        let indices = cached
            .indices
            .get(slot.position * pixels..(slot.position + 1) * pixels)
            .ok_or_else(|| outside(INDEX_FILE))?
            .to_vec();
        let layers = cached
            .layers
            .get(slot.position * pixels * 2..(slot.position + 1) * pixels * 2)
            .ok_or_else(|| outside(LAYER_FILE))?
            .as_chunks::<2>()
            .0
            .iter()
            .map(|pair| u16::from_le_bytes(*pair))
            .collect();
        let shapes = cached
            .shapes
            .as_ref()
            .map(|bytes| {
                Ok::<_, StoreError>(
                    bytes
                        .get(slot.position * pixels * 2..(slot.position + 1) * pixels * 2)
                        .ok_or_else(|| outside(SHAPE_FILE))?
                        .as_chunks::<2>()
                        .0
                        .iter()
                        .map(|pair| u16::from_le_bytes(*pair))
                        .collect(),
                )
            })
            .transpose()?;
        let entry: &RenderTick = self
            .record
            .ticks
            .binary_search_by_key(&tick, |entry| entry.tick)
            .ok()
            .and_then(|at| self.record.ticks.get(at))
            .ok_or_else(|| StoreError::MissingTick {
                dir: self.dir.clone(),
                tick,
            })?;
        // `validate` holds every palette index below the count `read_palettes` checked.
        let palette = *self
            .palettes
            .get(entry.palette_index as usize)
            .ok_or_else(|| {
                corrupt(
                    &self.dir.join(PALETTE_FILE),
                    format!("tick {tick} names missing palette {}", entry.palette_index),
                )
            })?;
        Ok(StoredFrame {
            indices,
            layers,
            shapes,
            palette,
        })
    }

    fn decode(&self, chunk: usize) -> Result<DecodedChunk, StoreError> {
        let entry =
            *self.record.chunks.get(chunk).ok_or_else(|| {
                corrupt(&self.dir, format!("the chunk table has no chunk {chunk}"))
            })?;
        let pixels = self.record.geometry.pixel_count() * entry.ticks as usize;
        let read = |name: &str, span: StoreSpan, expected: usize| {
            let path = self.dir.join(name);
            let mut file = File::open(&path).map_err(io(&path))?;
            file.seek(SeekFrom::Start(span.offset)).map_err(io(&path))?;
            let file_len = file.metadata().map_err(io(&path))?.len();
            let length = span
                .offset
                .checked_add(span.length)
                .filter(|&end| end <= file_len)
                .and_then(|_| usize::try_from(span.length).ok())
                .ok_or_else(|| {
                    corrupt(
                        &path,
                        format!(
                            "a chunk of {} bytes at offset {} runs past the file's {file_len} bytes",
                            span.length, span.offset
                        ),
                    )
                })?;
            let mut packed = vec![0u8; length];
            file.read_exact(&mut packed).map_err(io(&path))?;
            let raw = zstd::decode_all(packed.as_slice()).map_err(|error| {
                corrupt(
                    &path,
                    format!("second {} does not decompress: {error}", entry.second),
                )
            })?;
            if raw.len() != expected {
                return Err(corrupt(
                    &path,
                    format!(
                        "second {} decompresses to {} bytes, expected {expected}",
                        entry.second,
                        raw.len()
                    ),
                ));
            }
            Ok(raw)
        };
        let shapes = match self
            .shape_spans
            .as_deref()
            .and_then(|spans| spans.get(chunk))
        {
            Some(&span) => Some(read(SHAPE_FILE, span, pixels * 2)?),
            None => None,
        };
        Ok(DecodedChunk {
            chunk,
            indices: read(INDEX_FILE, entry.index, pixels)?,
            layers: read(LAYER_FILE, entry.layer, pixels * 2)?,
            shapes,
        })
    }
}

/// The packed span of each record in `shapes.zst`, which must hold exactly `chunks` of them
/// and nothing else; `None` when the render has no such file.
fn read_shape_spans(path: &Path, chunks: usize) -> Result<Option<Vec<StoreSpan>>, StoreError> {
    let mut file = match File::open(path) {
        Ok(file) => file,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(None),
        Err(source) => return Err(io(path)(source)),
    };
    let size = file.metadata().map_err(io(path))?.len();
    let mut spans = Vec::with_capacity(chunks);
    let mut at = 0u64;
    while at < size {
        let mut header = [0u8; 8];
        file.read_exact(&mut header).map_err(|_| {
            corrupt(
                path,
                format!("a record header at offset {at} runs past the file's {size} bytes"),
            )
        })?;
        let length = u64::from_le_bytes(header);
        let offset = at + 8;
        let end = offset.checked_add(length).filter(|&end| end <= size);
        let Some(end) = end else {
            return Err(corrupt(
                path,
                format!(
                    "a record of {length} bytes at offset {offset} runs past the file's {size} bytes"
                ),
            ));
        };
        spans.push(StoreSpan { offset, length });
        file.seek(SeekFrom::Start(end)).map_err(io(path))?;
        at = end;
    }
    if spans.len() != chunks {
        return Err(corrupt(
            path,
            format!(
                "holds {} records but render.json has {chunks} chunks; re-render",
                spans.len()
            ),
        ));
    }
    Ok(Some(spans))
}

/// Reads `palettes.zst`, which must hold exactly `count` palettes.
fn read_palettes(path: &Path, count: u32) -> Result<Vec<Palette>, StoreError> {
    if count == 0 && !path.exists() {
        return Ok(Vec::new());
    }
    let packed = fs::read(path).map_err(io(path))?;
    let expected = count as usize * PALETTE_BYTES;
    // Decoded without a size cap, so a payload of the wrong length is reported by its length,
    // as the Python reader does, rather than as a decode failure.
    let raw = zstd::decode_all(packed.as_slice())
        .map_err(|error| corrupt(path, format!("does not decompress: {error}")))?;
    if raw.len() != expected {
        return Err(corrupt(
            path,
            format!(
                "holds {} bytes, expected {expected} for {count} palettes",
                raw.len()
            ),
        ));
    }
    Ok(raw
        .as_chunks::<PALETTE_BYTES>()
        .0
        .iter()
        .map(|bytes| {
            let mut palette = [(0u8, 0u8, 0u8); 256];
            for (entry, rgb) in palette.iter_mut().zip(bytes.as_chunks::<3>().0) {
                *entry = (rgb[0], rgb[1], rgb[2]);
            }
            palette
        })
        .collect())
}

#[cfg(test)]
mod tests;
