//! The render store: the one place a render's plane files are encoded and decoded (ADR 0027).
//!
//! A render directory holds `frames.zst` (one palette-index byte per pixel), `layers.zst` (one
//! little-endian u16 layer per pixel) and `palettes.zst` (768-byte palettes). Each plane file is
//! a run of independent zstd frames, one per film second, holding that second's ticks back to
//! back; `render.json`, written last, is their table of contents. `preview/sec_NNNN.png` shows
//! each second's first tick for people. The Python mirror is `RenderStore` in
//! `python/stunt_reel/parity_artifacts.py`.

use std::collections::HashMap;
use std::fs::{self, File};
use std::io::{BufWriter, Read, Seek, SeekFrom, Write};
use std::path::{Path, PathBuf};

use stunt_parity::{
    Geometry, PALETTE_BYTES, RENDER_CHUNK_TICKS, RenderChunk, RenderRecord, RenderTick, StoreSpan,
};

use crate::parity_artifacts::{self, AdapterError};

/// Index planes, one byte per pixel.
pub(crate) const INDEX_FILE: &str = "frames.zst";
/// Layer planes, one little-endian u16 per pixel.
pub(crate) const LAYER_FILE: &str = "layers.zst";
/// The distinct palettes, [`PALETTE_BYTES`] each, as one zstd frame.
pub(crate) const PALETTE_FILE: &str = "palettes.zst";
/// One indexed PNG per film second, for people.
pub(crate) const PREVIEW_DIR: &str = "preview";
/// zstd level of every chunk: fast to write, and the ratio levels above it add little.
const ZSTD_LEVEL: i32 = 3;

/// A 256-entry RGB palette.
pub(crate) type Palette = [(u8, u8, u8); 256];

/// A store that could not be written or read, naming the file.
#[derive(Debug, thiserror::Error)]
pub(crate) enum StoreError {
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
        let expected = palette[usize::from(index)];
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
}

/// The two plane files, opened on the first tick.
struct PlaneFiles {
    index: BufWriter<File>,
    layer: BufWriter<File>,
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
            geometry: geometry.clone(),
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
    /// Ticks must be strictly ascending. The layer file holds a u16 per pixel, so a layer that
    /// does not fit is an error rather than a silent truncation.
    pub(crate) fn push(
        &mut self,
        tick: u32,
        palette: &Palette,
        indices: &[u8],
        layers: &[u32],
    ) -> Result<u32, StoreError> {
        let expected = self.geometry.pixel_count();
        let at = self.dir.join(INDEX_FILE);
        if indices.len() != expected || layers.len() != expected {
            return Err(corrupt(
                &at,
                format!(
                    "tick {tick} has {} indices and {} layers, expected {expected} for {}x{}",
                    indices.len(),
                    layers.len(),
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
        let mut layer_bytes = Vec::with_capacity(expected * 2);
        for (pixel, &layer) in layers.iter().enumerate() {
            let layer = u16::try_from(layer).map_err(|_| {
                corrupt(
                    &self.dir.join(LAYER_FILE),
                    format!("tick {tick} pixel {pixel} layer {layer} does not fit a u16"),
                )
            })?;
            layer_bytes.extend_from_slice(&layer.to_le_bytes());
        }
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
        });
        open.ticks += 1;
        open.indices.extend_from_slice(indices);
        open.layers.extend_from_slice(&layer_bytes);
        self.last_tick = Some(tick);
        self.palette_id(palette)
    }

    /// Writes the last chunk and `palettes.zst`; `None` when no tick was pushed.
    pub(crate) fn finish(mut self) -> Result<Option<StoreTable>, StoreError> {
        self.close_chunk()?;
        let Some(files) = self.files.take() else {
            return Ok(None);
        };
        for (mut file, name) in [(files.index, INDEX_FILE), (files.layer, LAYER_FILE)] {
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
    /// The colours of the frame: its picture is `palette[index]`.
    pub(crate) palette: Palette,
}

impl StoredFrame {
    /// The frame's picture as tightly packed RGB bytes.
    pub(crate) fn rgb(&self) -> Vec<u8> {
        self.indices
            .iter()
            .flat_map(|&index| {
                let (r, g, b) = self.palette[usize::from(index)];
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
}

/// Reads a render directory's store, keeping the last decoded chunk.
pub(crate) struct RenderStore {
    dir: PathBuf,
    record: RenderRecord,
    palettes: Vec<Palette>,
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
        Ok(Self {
            dir: dir.to_path_buf(),
            record,
            palettes,
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
        let indices = cached.indices[slot.position * pixels..(slot.position + 1) * pixels].to_vec();
        let layers = cached.layers[slot.position * pixels * 2..(slot.position + 1) * pixels * 2]
            .as_chunks::<2>()
            .0
            .iter()
            .map(|pair| u16::from_le_bytes(*pair))
            .collect();
        let entry: &RenderTick = &self.record.ticks[self
            .record
            .ticks
            .binary_search_by_key(&tick, |entry| entry.tick)
            .map_err(|_| StoreError::MissingTick {
                dir: self.dir.clone(),
                tick,
            })?];
        Ok(StoredFrame {
            indices,
            layers,
            palette: self.palettes[entry.palette_index as usize],
        })
    }

    fn decode(&self, chunk: usize) -> Result<DecodedChunk, StoreError> {
        let entry = self.record.chunks[chunk];
        let pixels = self.record.geometry.pixel_count() * entry.ticks as usize;
        let read = |name: &str, span: StoreSpan, expected: usize| {
            let path = self.dir.join(name);
            let mut file = File::open(&path).map_err(io(&path))?;
            file.seek(SeekFrom::Start(span.offset)).map_err(io(&path))?;
            let mut packed = vec![0u8; span.length as usize];
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
        Ok(DecodedChunk {
            chunk,
            indices: read(INDEX_FILE, entry.index, pixels)?,
            layers: read(LAYER_FILE, entry.layer, pixels * 2)?,
        })
    }
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
mod tests {
    use super::*;
    use stunt_parity::{CameraPose, FilmId, RENDER_SCHEMA_VERSION, RenderPalette};

    fn temp_dir(name: &str) -> PathBuf {
        let dir = std::env::temp_dir().join(format!(
            "stunt-reel-render-store-{name}-{}",
            std::process::id()
        ));
        drop(fs::remove_dir_all(&dir));
        fs::create_dir_all(&dir).expect("create temp dir");
        dir
    }

    fn geometry() -> Geometry {
        Geometry {
            width: 4,
            height: 3,
            viewport_rows: Some(2),
        }
    }

    fn grey(level: u8) -> Palette {
        let mut palette = [(0, 0, 0); 256];
        for (index, entry) in palette.iter_mut().enumerate() {
            let value = (index as u8).saturating_add(level);
            *entry = (value, value, value);
        }
        palette
    }

    /// Planes for `tick`: indices and layers that differ per tick and per pixel.
    fn planes(tick: u32) -> (Vec<u8>, Vec<u32>) {
        let indices = (0..12)
            .map(|pixel| (tick as u8).wrapping_add(pixel))
            .collect();
        let layers = (0..12).map(|pixel| tick * 100 + pixel).collect();
        (indices, layers)
    }

    /// Writes ticks 7, 9 and 40 (second 0), none in second 1, and 101 and 120 (second 2),
    /// alternating two palettes, then the record.
    fn write_store(dir: &Path) -> Vec<u32> {
        let ticks = vec![7, 9, 40, 101, 120];
        let mut writer = StoreWriter::new(dir, &geometry());
        let mut entries = Vec::new();
        for (row, &tick) in ticks.iter().enumerate() {
            let (indices, layers) = planes(tick);
            let palette = grey(if row % 2 == 0 { 0 } else { 10 });
            let palette_index = writer
                .push(tick, &palette, &indices, &layers)
                .expect("push");
            entries.push(RenderTick {
                tick,
                palette: RenderPalette {
                    sky: 0,
                    brightness: 0x8000,
                    saturation: 0x8000,
                },
                camera: CameraPose {
                    eye: [0.0; 3],
                    target: [0.0; 3],
                    fov_degrees: 45.0,
                    roll_radians: 0.0,
                },
                palette_index,
            });
        }
        let table = writer.finish().expect("finish").expect("a store");
        let record = RenderRecord {
            schema_version: RENDER_SCHEMA_VERSION,
            film: FilmId::default(),
            geometry: geometry(),
            ticks: entries,
            palette_count: table.palette_count,
            chunks: table.chunks,
        };
        parity_artifacts::write_render_record(dir, &record).expect("write record");
        ticks
    }

    #[test]
    fn every_tick_round_trips_across_seconds_and_an_empty_second() {
        let dir = temp_dir("round-trip");
        let ticks = write_store(&dir);
        let mut store = RenderStore::open(&dir).expect("open");
        let seconds: Vec<(u32, u32)> = store
            .record()
            .chunks
            .iter()
            .map(|chunk| (chunk.second, chunk.ticks))
            .collect();
        assert_eq!(seconds, vec![(0, 3), (2, 2)]);
        assert_eq!(store.record().palette_count, 2);
        // Out of order, so the cache has to swap chunks.
        for &tick in ticks.iter().rev().chain(&ticks) {
            let (indices, layers) = planes(tick);
            let frame = store.frame(tick).expect("frame");
            assert_eq!(frame.indices, indices);
            assert_eq!(
                frame.layers,
                layers.iter().map(|&l| l as u16).collect::<Vec<_>>()
            );
            let row = ticks.iter().position(|&t| t == tick).unwrap();
            assert_eq!(frame.palette, grey(if row % 2 == 0 { 0 } else { 10 }));
        }
        assert!(store.holds(101) && !store.holds(8));
        let error = store.frame(8).unwrap_err().to_string();
        assert!(error.contains("holds no render of tick 8"), "{error}");
        assert!(dir.join(PREVIEW_DIR).join("sec_0000.png").is_file());
        assert!(!dir.join(PREVIEW_DIR).join("sec_0001.png").exists());
        let preview = image::open(dir.join(PREVIEW_DIR).join("sec_0002.png"))
            .expect("preview")
            .into_rgb8();
        let rgb = store.frame(101).unwrap().rgb();
        assert_eq!(preview.as_raw(), &rgb);
    }

    #[test]
    fn a_run_without_ticks_writes_no_store() {
        let dir = temp_dir("empty");
        let writer = StoreWriter::new(&dir, &geometry());
        assert_eq!(writer.finish().expect("finish"), None);
        assert!(!dir.join(INDEX_FILE).exists() && !dir.join(PREVIEW_DIR).exists());
    }

    #[test]
    fn the_writer_refuses_bad_planes_and_unordered_ticks() {
        let dir = temp_dir("refusals");
        let mut writer = StoreWriter::new(&dir, &geometry());
        let (indices, layers) = planes(3);
        let error = writer
            .push(3, &grey(0), &indices[..11], &layers)
            .unwrap_err();
        assert!(error.to_string().contains("expected 12 for 4x3"), "{error}");
        let mut wide = layers.clone();
        wide[5] = 65_536;
        let error = writer.push(3, &grey(0), &indices, &wide).unwrap_err();
        assert!(
            error
                .to_string()
                .contains("pixel 5 layer 65536 does not fit"),
            "{error}"
        );
        writer.push(3, &grey(0), &indices, &layers).expect("push");
        let error = writer.push(3, &grey(0), &indices, &layers).unwrap_err();
        assert!(
            error.to_string().contains("does not follow tick Some(3)"),
            "{error}"
        );
    }

    #[test]
    fn a_version_1_render_is_refused_with_the_re_render_action() {
        let dir = temp_dir("v1");
        fs::write(
            dir.join("render.json"),
            r#"{"schema_version": 1, "film": {}, "geometry": {"width": 4, "height": 3},
                "ticks": []}"#,
        )
        .unwrap();
        let error = RenderStore::open(&dir).err().expect("refused").to_string();
        assert!(error.contains("re-render"), "{error}");
        assert!(error.contains("stuntreel --headless"), "{error}");
    }

    #[test]
    fn a_plane_file_of_the_wrong_size_is_refused() {
        let dir = temp_dir("short");
        write_store(&dir);
        let path = dir.join(LAYER_FILE);
        let mut bytes = fs::read(&path).unwrap();
        bytes.pop();
        fs::write(&path, bytes).unwrap();
        let error = RenderStore::open(&dir).err().expect("refused").to_string();
        assert!(error.contains("layers.zst"), "{error}");
        assert!(error.contains("chunks end at"), "{error}");
    }

    #[test]
    fn a_corrupt_chunk_names_its_second_and_file() {
        let dir = temp_dir("corrupt");
        write_store(&dir);
        let mut store = RenderStore::open(&dir).expect("open");
        let span = store.record().chunks[1].index;
        let path = dir.join(INDEX_FILE);
        let mut bytes = fs::read(&path).unwrap();
        for byte in &mut bytes[span.offset as usize..(span.offset + span.length) as usize] {
            *byte = 0xAA;
        }
        fs::write(&path, bytes).unwrap();
        store.frame(7).expect("second 0 is intact");
        let error = store.frame(101).unwrap_err().to_string();
        assert!(error.contains("frames.zst"), "{error}");
        assert!(error.contains("second 2"), "{error}");
    }

    #[test]
    fn a_chunk_of_the_wrong_decoded_length_names_its_second_and_file() {
        let dir = temp_dir("long-chunk");
        write_store(&dir);
        let mut record = RenderStore::open(&dir).expect("open").record().clone();
        let path = dir.join(INDEX_FILE);
        let mut bytes = fs::read(&path).unwrap();
        bytes.truncate(record.chunks[1].index.offset as usize);
        // Second 2 holds two 12-pixel ticks; store one byte too many.
        let packed = zstd::bulk::compress(&[0u8; 25], 3).unwrap();
        bytes.extend_from_slice(&packed);
        fs::write(&path, bytes).unwrap();
        record.chunks[1].index.length = packed.len() as u64;
        parity_artifacts::write_render_record(&dir, &record).expect("write record");
        let mut store = RenderStore::open(&dir).expect("open");
        store.frame(7).expect("second 0 is intact");
        let error = store.frame(101).unwrap_err().to_string();
        assert!(error.contains("frames.zst"), "{error}");
        assert!(
            error.contains("second 2 decompresses to 25 bytes, expected 24"),
            "{error}"
        );
    }

    #[test]
    fn palettes_of_the_wrong_length_are_refused() {
        let dir = temp_dir("palettes");
        write_store(&dir);
        for count in [1, 3] {
            fs::write(
                dir.join(PALETTE_FILE),
                zstd::bulk::compress(&vec![0u8; count * PALETTE_BYTES], 3).unwrap(),
            )
            .unwrap();
            let error = RenderStore::open(&dir).err().expect("refused").to_string();
            assert!(error.contains("palettes.zst"), "{error}");
            assert!(
                error.contains(&format!(
                    "holds {} bytes, expected 1536 for 2 palettes",
                    count * PALETTE_BYTES
                )),
                "{error}"
            );
        }
    }

    #[test]
    fn a_picture_that_is_not_palette_lookup_is_refused() {
        let palette = grey(0);
        let indices = [1u8, 2, 3];
        let mut rgba = vec![1, 1, 1, 255, 2, 2, 2, 255, 3, 3, 3, 255];
        check_derivable(&palette, &indices, &rgba, 3).expect("derivable");
        rgba[4] = 9;
        let error = check_derivable(&palette, &indices, &rgba, 3).unwrap_err();
        assert!(
            error.contains("pixel (1, 0) is (9, 2, 2) but palette[2] is (2, 2, 2)"),
            "{error}"
        );
    }
}
