//! Filesystem adapter for the parity artifact port (`stunt-parity`).
//!
//! The port owns the schema; this module owns the files. It is the only place
//! the CLI learns artifact names and JSON details, and the only place that
//! writes `render.json`; the plane files beside it belong to `render_store`.

use std::fs;
use std::path::{Path, PathBuf};

use serde::Serialize;
use serde_json::Value;
use stunt_core::contracts::PaletteControls;
use stunt_core::scene::ViewCamera;
use stunt_parity::{
    ArtifactError as SchemaError, CameraPose, CaptureSet, FilmId, Geometry, RENDER_SCHEMA_VERSION,
    RenderAdapter, RenderPalette, RenderRecord, RenderTick, Report, VideoCapture,
};

use crate::render_store::{StoreError, StoreWriter, check_derivable};
use crate::sha256;

/// Document written beside a render directory's frames, last.
pub(crate) const RENDER_DOCUMENT: &str = "render.json";
/// Document written by the capture harness in a capture directory.
pub(crate) const CAPTURE_META: &str = "meta.json";

/// A broken artifact read or write, naming the file.
#[derive(Debug, thiserror::Error)]
pub enum AdapterError {
    /// Reading a file failed.
    #[error("read {path}: {source}")]
    Read {
        /// File that could not be read.
        path: PathBuf,
        /// Underlying I/O error.
        source: std::io::Error,
    },
    /// Writing a file failed.
    #[error("write {path}: {source}")]
    Write {
        /// File that could not be written.
        path: PathBuf,
        /// Underlying I/O error.
        source: std::io::Error,
    },
    /// Parsing a document failed.
    #[error("parse {path}: {source}")]
    Parse {
        /// File that could not be parsed.
        path: PathBuf,
        /// Underlying JSON error.
        source: serde_json::Error,
    },
    /// Serializing a document failed.
    #[error("serialize {path}: {source}")]
    Serialize {
        /// File being serialized.
        path: PathBuf,
        /// Underlying JSON error.
        source: serde_json::Error,
    },
    /// The document parsed but does not satisfy the schema.
    #[error("{path}: {source}")]
    Schema {
        /// File that failed the schema.
        path: PathBuf,
        /// Schema defect.
        source: SchemaError,
    },
    /// The capture's frames predate film-clock tagging, so parity cannot match them.
    #[error(
        "{path}: {source}; the capture predates film-clock tagging and must be recaptured \
         (mise run capture-ref)"
    )]
    CaptureUntagged {
        /// File that has no film clock.
        path: PathBuf,
        /// Why the capture set did not parse.
        source: serde_json::Error,
    },
}

fn read_json(path: &Path) -> Result<Value, AdapterError> {
    let text = fs::read_to_string(path).map_err(|source| AdapterError::Read {
        path: path.to_path_buf(),
        source,
    })?;
    serde_json::from_str(&text).map_err(|source| AdapterError::Parse {
        path: path.to_path_buf(),
        source,
    })
}

fn write_json<T: Serialize>(path: &Path, value: &T, pretty: bool) -> Result<(), AdapterError> {
    let text = if pretty {
        serde_json::to_string_pretty(value)
    } else {
        serde_json::to_string(value)
    }
    .map_err(|source| AdapterError::Serialize {
        path: path.to_path_buf(),
        source,
    })?;
    fs::write(path, text).map_err(|source| AdapterError::Write {
        path: path.to_path_buf(),
        source,
    })
}

fn schema(path: &Path, source: SchemaError) -> AdapterError {
    AdapterError::Schema {
        path: path.to_path_buf(),
        source,
    }
}

/// Film identity recorded beside a render: the name and bytes of the `.FLM` at `flm`, and the
/// bytes of the archive, exactly as the scene loaded them; `None` for an input it did not read.
pub fn film_identity(flm: Option<(&Path, &[u8])>, archive: Option<&[u8]>) -> FilmId {
    FilmId {
        name: flm
            .and_then(|(path, _)| path.file_name())
            .map(|name| name.to_string_lossy().into_owned()),
        flm_bytes: flm.map(|(_, bytes)| bytes.len() as u64),
        flm_sha256: flm.map(|(_, bytes)| sha256(bytes)),
        all_sha256: archive.map(sha256),
    }
}

fn render_palette(controls: PaletteControls) -> RenderPalette {
    RenderPalette {
        sky: controls.sky,
        brightness: controls.brightness,
        saturation: controls.saturation,
    }
}

fn camera_pose(camera: ViewCamera) -> CameraPose {
    CameraPose {
        eye: camera.eye,
        target: camera.target,
        fov_degrees: camera.fov_degrees,
        roll_radians: camera.roll_radians,
    }
}

/// A drawn page as the journal reads it, row-major from the top row, one entry per pixel.
#[derive(Debug, Clone, Copy)]
pub struct PageView<'a> {
    /// Page width in pixels.
    pub width: u32,
    /// Tightly packed RGBA8 pixels.
    pub rgba: &'a [u8],
    /// Unlit palette indices.
    pub indices: &'a [u8],
    /// Layer ids.
    pub layers: &'a [u32],
    /// Shape words: `shape id + 1` of the prop drawing each pixel, 0 for none.
    pub shapes: &'a [u32],
}

/// Collects one render directory: its planes through the store, and its document, written last.
pub struct RenderJournal {
    dir: PathBuf,
    film: FilmId,
    geometry: Geometry,
    ticks: Vec<RenderTick>,
    store: StoreWriter,
}

impl std::fmt::Debug for RenderJournal {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("RenderJournal")
            .field("dir", &self.dir)
            .field("ticks", &self.ticks.len())
            .finish_non_exhaustive()
    }
}

impl RenderJournal {
    /// Starts a journal for `dir`; the caller has already created the directory.
    ///
    /// Any `render.json` already in `dir` is removed first, so a run that fails or renders no
    /// whole tick never leaves the previous render readable as its own.
    ///
    /// # Errors
    ///
    /// When an old `render.json` in `dir` cannot be removed.
    pub fn begin(dir: &Path, film: FilmId, geometry: Geometry) -> Result<Self, StoreError> {
        let record = dir.join(RENDER_DOCUMENT);
        match fs::remove_file(&record) {
            Ok(()) => {}
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
            Err(source) => {
                return Err(StoreError::Io {
                    path: record,
                    source,
                });
            }
        }
        Ok(Self {
            dir: dir.to_path_buf(),
            film,
            store: StoreWriter::new(dir, &geometry),
            geometry,
            ticks: Vec::new(),
        })
    }

    /// Stores the page drawn for film-clock `tick` with `controls` from `camera`; `credits`
    /// says whether the film shows credits there.
    ///
    /// The page's picture is not kept: it must be `palette[index]` at every pixel for the
    /// film palette of `controls`, and a page that is not is refused.
    ///
    /// # Errors
    ///
    /// When the page is not its palette over its index plane, or the store cannot be written.
    pub fn write(
        &mut self,
        tick: u32,
        controls: PaletteControls,
        camera: ViewCamera,
        credits: bool,
        page: PageView<'_>,
    ) -> Result<(), StoreError> {
        let palette = controls.film_palette();
        check_derivable(&palette, page.indices, page.rgba, page.width).map_err(|message| {
            StoreError::Corrupt {
                path: self.dir.clone(),
                message: format!("tick {tick}: {message}"),
            }
        })?;
        let palette_index =
            self.store
                .push(tick, &palette, page.indices, page.layers, page.shapes)?;
        self.ticks.push(RenderTick {
            tick,
            palette: render_palette(controls),
            camera: camera_pose(camera),
            palette_index,
            credits,
        });
        Ok(())
    }

    /// Closes the store and writes `render.json` last, naming *adapter* as the one that drew the
    /// frames; neither is written when no whole-tick frame was stored.
    ///
    /// # Errors
    ///
    /// When the store or `render.json` cannot be written.
    pub fn finish(self, adapter: RenderAdapter) -> Result<(), StoreError> {
        let Some(table) = self.store.finish()? else {
            return Ok(());
        };
        let record = RenderRecord {
            schema_version: RENDER_SCHEMA_VERSION,
            film: self.film,
            geometry: self.geometry,
            ticks: self.ticks,
            palette_count: table.palette_count,
            chunks: table.chunks,
            planes: table.planes,
            adapter: Some(adapter),
        };
        write_render_record(&self.dir, &record).map_err(StoreError::Record)
    }
}

/// Reads and validates a render directory's `render.json`.
///
/// # Errors
///
/// When `render.json` is missing, unreadable or invalid.
pub fn read_render_record(dir: &Path) -> Result<RenderRecord, AdapterError> {
    let path = dir.join(RENDER_DOCUMENT);
    let value = read_json(&path)?;
    let version = value.get("schema_version").and_then(Value::as_u64);
    if version != Some(u64::from(RENDER_SCHEMA_VERSION)) {
        let source = match version {
            None => SchemaError::MissingField {
                field: "schema_version (an unsigned integer)".to_string(),
            },
            // A version too large for `u32` saturates; it must not read as version 0.
            Some(found) => SchemaError::UnsupportedVersion {
                found: u32::try_from(found).unwrap_or(u32::MAX),
                expected: RENDER_SCHEMA_VERSION,
            },
        };
        return Err(schema(&path, source));
    }
    let record: RenderRecord =
        serde_json::from_value(value).map_err(|source| AdapterError::Parse {
            path: path.clone(),
            source,
        })?;
    record.validate().map_err(|error| schema(&path, error))?;
    Ok(record)
}

/// Validates and writes a render directory's `render.json`.
///
/// # Errors
///
/// When `render.json` cannot be serialised or written.
pub fn write_render_record(dir: &Path, record: &RenderRecord) -> Result<(), AdapterError> {
    let path = dir.join(RENDER_DOCUMENT);
    record.validate().map_err(|error| schema(&path, error))?;
    write_json(&path, record, true)
}

/// The film palette controls a render tick was drawn with.
pub(crate) fn core_palette(palette: RenderPalette) -> PaletteControls {
    PaletteControls {
        sky: palette.sky,
        brightness: palette.brightness,
        saturation: palette.saturation,
    }
}

/// Reads a capture directory's `meta.json` into the port's capture set.
///
/// The port owns the document's legacy defaults; the adapter only adds the
/// recapture action when a frame has no film clock, which is the one defect the
/// reader cannot fix for the user.
pub(crate) fn load_capture(dir: &Path) -> Result<CaptureSet, AdapterError> {
    let path = dir.join(CAPTURE_META);
    let value = read_json(&path)?;
    let set: CaptureSet = serde_json::from_value(value).map_err(|source| {
        if source.to_string().contains("has no film_tick") {
            AdapterError::CaptureUntagged {
                path: path.clone(),
                source,
            }
        } else {
            AdapterError::Parse {
                path: path.clone(),
                source,
            }
        }
    })?;
    set.validate().map_err(|error| schema(&path, error))?;
    Ok(set)
}

/// Reads a video capture directory's `meta.json` into the port's video document.
#[cfg_attr(
    not(test),
    expect(
        dead_code,
        reason = "only tests read video captures until a video scorer is merged (method.md § 4.4)"
    )
)]
pub(crate) fn load_video_capture(dir: &Path) -> Result<VideoCapture, AdapterError> {
    let path = dir.join(CAPTURE_META);
    let value = read_json(&path)?;
    let capture: VideoCapture =
        serde_json::from_value(value).map_err(|source| AdapterError::Parse {
            path: path.clone(),
            source,
        })?;
    capture.validate().map_err(|error| schema(&path, error))?;
    Ok(capture)
}

/// Writes a validated `report.json`.
pub(crate) fn write_report(path: &Path, report: &Report) -> Result<(), AdapterError> {
    report.validate().map_err(|error| schema(path, error))?;
    write_json(path, report, true)
}

/// Reads a `report.json`, including reports written before recent optional fields.
pub(crate) fn read_report(path: &Path) -> Result<Report, AdapterError> {
    let value = read_json(path)?;
    serde_json::from_value(value).map_err(|source| AdapterError::Parse {
        path: path.to_path_buf(),
        source,
    })
}

/// The committed corpus under `tests/fixtures/parity/v1` (captures and reports) and
/// `tests/fixtures/parity/v4` (renders), read through this adapter.
#[cfg(test)]
mod conformance;

#[cfg(test)]
mod tests;
