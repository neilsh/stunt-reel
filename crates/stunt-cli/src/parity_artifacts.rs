//! Filesystem adapter for the parity artifact port (`stunt-parity`).
//!
//! The port owns the schema; this module owns the files. It is the only place
//! the CLI learns artifact names and JSON details, and the only place that
//! writes `render.json`. During the migration it also writes the legacy
//! `palette_controls.json` sidecar and reads it as a fallback.

use std::collections::BTreeMap;
use std::fs;
use std::path::{Path, PathBuf};

use serde::Serialize;
use serde_json::{Value, json};
use stunt_core::contracts::{CameraTransform, PaletteControls};
use stunt_core::scene::SceneFrame;
use stunt_parity::{
    ArtifactError as SchemaError, CameraPose, CaptureSet, CapturedFrame, FilmId, Geometry,
    RenderPalette, RenderRecord, RenderTick, Report, SCHEMA_VERSION,
};

/// Document written beside a render directory's frames, last.
pub(crate) const RENDER_DOCUMENT: &str = "render.json";
/// Legacy render sidecar, read until renders made before the record age out.
pub(crate) const LEGACY_SIDECAR: &str = "palette_controls.json";

/// A broken artifact read or write, naming the file.
#[derive(Debug, thiserror::Error)]
pub(crate) enum AdapterError {
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

/// Film identity recorded beside a render or compared against a capture.
pub(crate) fn film_identity(path: Option<&Path>) -> FilmId {
    FilmId {
        name: path
            .and_then(Path::file_name)
            .map(|name| name.to_string_lossy().into_owned()),
        flm_bytes: path
            .and_then(|path| fs::metadata(path).ok())
            .map(|meta| meta.len()),
        flm_sha256: None,
    }
}

fn render_palette(controls: PaletteControls) -> RenderPalette {
    RenderPalette {
        sky: controls.sky,
        brightness: controls.brightness,
        saturation: controls.saturation,
    }
}

fn core_palette(palette: RenderPalette) -> PaletteControls {
    PaletteControls {
        sky: palette.sky,
        brightness: palette.brightness,
        saturation: palette.saturation,
    }
}

fn camera_pose(camera: CameraTransform) -> CameraPose {
    CameraPose {
        eye: camera.eye,
        target: camera.target,
        fov_degrees: camera.fov_degrees,
        roll_radians: camera.roll_radians,
    }
}

fn legacy_sidecar(film: &FilmId, ticks: &[RenderTick]) -> Value {
    let ticks: Vec<Value> = ticks
        .iter()
        .map(|tick| {
            json!({
                "tick": tick.tick,
                "sky": tick.palette.sky,
                "brightness": tick.palette.brightness,
                "saturation": tick.palette.saturation,
                "camera": {
                    "eye": tick.camera.eye,
                    "target": tick.camera.target,
                    "fov_degrees": tick.camera.fov_degrees,
                    "roll_radians": tick.camera.roll_radians,
                },
            })
        })
        .collect();
    json!({
        "film": film.name,
        "flm_bytes": film.flm_bytes,
        "ticks": ticks,
    })
}

/// Collects one render directory's document and writes it last.
///
/// Frame files themselves are still written by the caller during this landing;
/// the journal owns the tick metadata and the two document files.
#[derive(Debug)]
pub(crate) struct RenderJournal {
    dir: PathBuf,
    film: FilmId,
    geometry: Geometry,
    ticks: Vec<RenderTick>,
}

impl RenderJournal {
    /// Starts a journal for `dir`; the caller has already created the directory.
    pub(crate) fn begin(dir: &Path, film: FilmId, geometry: Geometry) -> Self {
        Self {
            dir: dir.to_path_buf(),
            film,
            geometry,
            ticks: Vec::new(),
        }
    }

    /// Records the controls and camera of the frame drawn for film-clock `tick`.
    pub(crate) fn record(&mut self, tick: u32, frame: &SceneFrame) {
        self.ticks.push(RenderTick {
            tick,
            palette: render_palette(frame.palette),
            camera: camera_pose(frame.camera),
        });
    }

    /// Writes the legacy sidecar, then `render.json` last; both are omitted
    /// when no whole-tick frame was recorded, matching the sidecar's old behaviour.
    pub(crate) fn finish(self) -> Result<(), AdapterError> {
        if self.ticks.is_empty() {
            return Ok(());
        }
        write_json(
            &self.dir.join(LEGACY_SIDECAR),
            &legacy_sidecar(&self.film, &self.ticks),
            false,
        )?;
        let path = self.dir.join(RENDER_DOCUMENT);
        let record = RenderRecord {
            schema_version: SCHEMA_VERSION,
            film: self.film,
            geometry: self.geometry,
            ticks: self.ticks,
        };
        record.validate().map_err(|error| schema(&path, error))?;
        write_json(&path, &record, true)
    }
}

/// Palette controls and film identity of a render directory, whichever document exists.
#[derive(Debug)]
pub(crate) struct RenderControls {
    /// Film identity, when the document recorded one.
    pub(crate) film: FilmId,
    /// Raster geometry, present only for a `render.json` render.
    pub(crate) geometry: Option<Geometry>,
    /// Film palette controls by film-clock tick.
    pub(crate) controls: BTreeMap<u32, PaletteControls>,
}

/// Reads a render's controls, preferring `render.json` and falling back to the
/// legacy sidecar. A directory with neither yields empty controls, as before.
pub(crate) fn load_render_controls(dir: &Path) -> Result<RenderControls, AdapterError> {
    let record_path = dir.join(RENDER_DOCUMENT);
    if record_path.is_file() {
        let value = read_json(&record_path)?;
        let record: RenderRecord =
            serde_json::from_value(value).map_err(|source| AdapterError::Parse {
                path: record_path.clone(),
                source,
            })?;
        record
            .validate()
            .map_err(|error| schema(&record_path, error))?;
        let controls = record
            .ticks
            .iter()
            .map(|tick| (tick.tick, core_palette(tick.palette)))
            .collect();
        return Ok(RenderControls {
            film: record.film,
            geometry: Some(record.geometry),
            controls,
        });
    }

    let legacy_path = dir.join(LEGACY_SIDECAR);
    if !legacy_path.is_file() {
        return Ok(RenderControls {
            film: FilmId::default(),
            geometry: None,
            controls: BTreeMap::new(),
        });
    }
    let value = read_json(&legacy_path)?;
    let film = FilmId {
        name: value
            .get("film")
            .and_then(Value::as_str)
            .map(str::to_string),
        flm_bytes: value.get("flm_bytes").and_then(Value::as_u64),
        flm_sha256: None,
    };
    let mut controls = BTreeMap::new();
    if let Some(ticks) = value.get("ticks").and_then(Value::as_array) {
        for entry in ticks {
            let field = |name: &str| {
                entry
                    .get(name)
                    .and_then(Value::as_u64)
                    .and_then(|value| u16::try_from(value).ok())
            };
            let tick = entry.get("tick").and_then(Value::as_u64).ok_or_else(|| {
                schema(
                    &legacy_path,
                    SchemaError::MissingField {
                        field: "tick".to_string(),
                    },
                )
            })?;
            let (Some(sky), Some(brightness), Some(saturation)) =
                (field("sky"), field("brightness"), field("saturation"))
            else {
                return Err(schema(
                    &legacy_path,
                    SchemaError::MissingField {
                        field: "sky/brightness/saturation".to_string(),
                    },
                ));
            };
            controls.insert(
                u32::try_from(tick)
                    .map_err(|_| schema(&legacy_path, SchemaError::TickOrder { index: 0 }))?,
                PaletteControls {
                    sky,
                    brightness,
                    saturation,
                },
            );
        }
    }
    Ok(RenderControls {
        film,
        geometry: None,
        controls,
    })
}

/// Reads a capture directory's `meta.json` into the port's capture set.
pub(crate) fn load_capture(dir: &Path) -> Result<CaptureSet, AdapterError> {
    let path = dir.join("meta.json");
    let value = read_json(&path)?;
    let frames = value
        .get("frames")
        .and_then(Value::as_array)
        .ok_or_else(|| {
            schema(
                &path,
                SchemaError::MissingField {
                    field: "frames".to_string(),
                },
            )
        })?;
    let film = FilmId {
        name: value
            .get("film")
            .and_then(Value::as_str)
            .map(str::to_string),
        flm_bytes: value.get("flm_bytes").and_then(Value::as_u64),
        flm_sha256: value
            .get("flm_sha256")
            .and_then(Value::as_str)
            .map(str::to_string),
    };
    let geometry = Geometry {
        width: value
            .get("width")
            .and_then(Value::as_u64)
            .and_then(|width| u32::try_from(width).ok())
            .unwrap_or(320),
        height: value
            .get("height")
            .and_then(Value::as_u64)
            .and_then(|height| u32::try_from(height).ok())
            .unwrap_or(200),
        viewport_rows: None,
    };
    let mut captured = Vec::with_capacity(frames.len());
    for (index, frame) in frames.iter().enumerate() {
        let ordinal = u32::try_from(index + 1).unwrap_or(u32::MAX);
        let film_tick = frame
            .get("film_tick")
            .and_then(Value::as_u64)
            .and_then(|tick| u32::try_from(tick).ok())
            .ok_or_else(|| {
                schema(
                    &path,
                    SchemaError::Frame {
                        ordinal,
                        reason: "has no film_tick: the capture predates film-clock tagging \
                            and must be recaptured (mise run capture-ref)"
                            .to_string(),
                    },
                )
            })?;
        let name = |key: &str, fallback: String| {
            frame
                .get(key)
                .and_then(Value::as_str)
                .map(str::to_string)
                .unwrap_or(fallback)
        };
        captured.push(CapturedFrame {
            ordinal,
            film_tick,
            frame_file: name("frame_file", format!("tick_{ordinal:04}.idx")),
            palette_file: name("palette_file", format!("palettes_{ordinal:04}.json")),
        });
    }
    let set = CaptureSet {
        schema_version: value
            .get("schema_version")
            .and_then(Value::as_u64)
            .and_then(|version| u32::try_from(version).ok()),
        film,
        geometry,
        frames: captured,
    };
    set.validate().map_err(|error| schema(&path, error))?;
    Ok(set)
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

#[cfg(test)]
mod tests {
    use super::*;
    use stunt_core::contracts::{CameraTransform, PaletteControls};
    use stunt_core::scene::SceneFrame;

    fn temp_dir(name: &str) -> PathBuf {
        let dir = std::env::temp_dir().join(format!(
            "stunt-reel-parity-artifacts-{name}-{}",
            std::process::id()
        ));
        let _ = fs::remove_dir_all(&dir);
        fs::create_dir_all(&dir).expect("create temp dir");
        dir
    }

    fn frame() -> SceneFrame {
        SceneFrame {
            tick: 7.0,
            camera: CameraTransform::default(),
            world: false,
            actors: Vec::new(),
            palette: PaletteControls {
                sky: 0x2000,
                brightness: 0x8000,
                saturation: 0x8000,
            },
        }
    }

    fn geometry() -> Geometry {
        Geometry {
            width: 320,
            height: 200,
            viewport_rows: Some(185),
        }
    }

    #[test]
    fn journal_writes_both_documents_and_the_record_wins() {
        let dir = temp_dir("journal");
        let mut journal = RenderJournal::begin(&dir, FilmId::default(), geometry());
        journal.record(7, &frame());
        journal.finish().expect("finish");

        assert!(dir.join(RENDER_DOCUMENT).is_file());
        assert!(dir.join(LEGACY_SIDECAR).is_file());

        let controls = load_render_controls(&dir).expect("load");
        assert_eq!(controls.geometry, Some(geometry()));
        assert_eq!(controls.controls.len(), 1);
        assert_eq!(controls.controls[&7].sky, 0x2000);
    }

    #[test]
    fn an_empty_journal_writes_no_documents() {
        let dir = temp_dir("empty");
        RenderJournal::begin(&dir, FilmId::default(), geometry())
            .finish()
            .expect("finish");
        assert!(!dir.join(RENDER_DOCUMENT).exists());
        assert!(!dir.join(LEGACY_SIDECAR).exists());
    }

    #[test]
    fn legacy_sidecar_still_loads() {
        let dir = temp_dir("legacy");
        let sidecar = json!({
            "film": "CTRY.FLM",
            "flm_bytes": 1234,
            "ticks": [
                {"tick": 7, "sky": 1, "brightness": 2, "saturation": 3, "camera": {}},
            ],
        });
        write_json(&dir.join(LEGACY_SIDECAR), &sidecar, false).expect("write legacy");
        let controls = load_render_controls(&dir).expect("load");
        assert!(controls.geometry.is_none());
        assert_eq!(controls.film.name.as_deref(), Some("CTRY.FLM"));
        assert_eq!(controls.controls[&7].brightness, 2);
    }

    #[test]
    fn capture_names_are_resolved_and_film_tick_is_required() {
        let dir = temp_dir("capture");
        let meta = json!({
            "film": "CTRY.FLM",
            "flm_bytes": 10,
            "width": 320,
            "height": 200,
            "frames": [
                {"film_tick": 9},
                {"film_tick": 10, "frame_file": "other.idx", "palette_file": "palettes_0002.json"},
            ],
        });
        write_json(&dir.join("meta.json"), &meta, false).expect("write meta");
        let set = load_capture(&dir).expect("load capture");
        assert_eq!(set.frames.len(), 2);
        assert_eq!(set.frames[0].frame_file, "tick_0001.idx");
        assert_eq!(set.frames[1].frame_file, "other.idx");
        assert_eq!(set.frames[1].ordinal, 2);
    }

    #[test]
    fn a_capture_without_a_film_tick_is_rejected() {
        let dir = temp_dir("untagged");
        let meta = json!({
            "frames": [{"film_tick": 1}, {}],
        });
        write_json(&dir.join("meta.json"), &meta, false).expect("write meta");
        let error = load_capture(&dir).expect_err("untagged frame");
        assert!(error.to_string().contains("frame 2"), "{error}");
    }

    #[test]
    fn a_wrong_schema_version_is_rejected() {
        let dir = temp_dir("version");
        write_json(
            &dir.join(RENDER_DOCUMENT),
            &json!({
                "schema_version": 9,
                "film": {},
                "geometry": {"width": 320, "height": 200},
                "ticks": [],
            }),
            true,
        )
        .expect("write record");
        let error = load_render_controls(&dir).expect_err("future version");
        assert!(error.to_string().contains("schema version 9"), "{error}");
    }
}
