//! Filesystem adapter for the parity artifact port (`stunt-parity`).
//!
//! The port owns the schema; this module owns the files. It is the only place
//! the CLI learns artifact names and JSON details, and the only place that
//! writes `render.json`. It still reads the legacy `palette_controls.json`
//! sidecar as a fallback for renders made before the record existed.

use std::collections::BTreeMap;
use std::fs;
use std::path::{Path, PathBuf};

use serde::Serialize;
use serde_json::Value;
use stunt_core::contracts::PaletteControls;
use stunt_core::scene::{SceneFrame, ViewCamera};
use stunt_parity::{
    ArtifactError as SchemaError, CameraPose, CaptureSet, FilmId, Geometry, RenderPalette,
    RenderRecord, RenderTick, Report, SCHEMA_VERSION,
};

/// Document written beside a render directory's frames, last.
pub(crate) const RENDER_DOCUMENT: &str = "render.json";
/// Legacy render sidecar, read until renders made before the record age out.
pub(crate) const LEGACY_SIDECAR: &str = "palette_controls.json";
/// Document written by the capture harness in a capture directory.
pub(crate) const CAPTURE_META: &str = "meta.json";

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

fn camera_pose(camera: ViewCamera) -> CameraPose {
    CameraPose {
        eye: camera.eye,
        target: camera.target,
        fov_degrees: camera.fov_degrees,
        roll_radians: camera.roll_radians,
    }
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
            camera: camera_pose(frame.view),
        });
    }

    /// Writes `render.json` last; it is omitted when no whole-tick frame was
    /// recorded. The legacy sidecar is no longer written (ADR 0005 landing 4).
    pub(crate) fn finish(self) -> Result<(), AdapterError> {
        if self.ticks.is_empty() {
            return Ok(());
        }
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
/// legacy sidecar. A directory with neither is an error: ADR 0005 makes the
/// document required.
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
        return Err(schema(
            dir,
            SchemaError::MissingField {
                field: "render.json or palette_controls.json (re-render the directory with \
                        stuntreel --headless --out-dir)"
                    .to_string(),
            },
        ));
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

/// The committed corpus under `tests/fixtures/parity/v1`, read through this adapter.
#[cfg(test)]
mod conformance {
    use super::*;
    use crate::plane_codec::read_page_planes;

    /// The shared corpus, resolved without the process working directory.
    fn corpus() -> PathBuf {
        Path::new(env!("CARGO_MANIFEST_DIR")).join("../../tests/fixtures/parity/v1")
    }

    /// Fails unless `|actual - expected| <= 1e-6 * max(1, |actual|, |expected|)`.
    fn assert_close(actual: f32, expected: f32, field: &str) {
        let tolerance = 1e-6 * actual.abs().max(expected.abs()).max(1.0);
        assert!(
            (actual - expected).abs() <= tolerance,
            "{field}: {actual} != {expected} (tolerance {tolerance})"
        );
    }

    fn assert_close_option(actual: Option<f32>, expected: Option<f32>, field: &str) {
        match (actual, expected) {
            (Some(actual), Some(expected)) => assert_close(actual, expected, field),
            (None, None) => {}
            _ => panic!("{field}: one side is null"),
        }
    }

    fn assert_close_map(
        actual: Option<&BTreeMap<String, f32>>,
        expected: Option<&BTreeMap<String, f32>>,
        field: &str,
    ) {
        match (actual, expected) {
            (Some(actual), Some(expected)) => {
                assert_eq!(actual.len(), expected.len(), "{field}: key count");
                for (key, expected) in expected {
                    let actual = actual
                        .get(key)
                        .unwrap_or_else(|| panic!("{field}: {key} is missing"));
                    assert_close(*actual, *expected, &format!("{field}.{key}"));
                }
            }
            (None, None) => {}
            _ => panic!("{field}: one side is null"),
        }
    }

    #[test]
    fn render_fixture_pins_identity_geometry_and_controls() {
        let controls = load_render_controls(&corpus()).expect("load render.json");
        assert_eq!(controls.film.name.as_deref(), Some("SYNTH.FLM"));
        assert_eq!(controls.film.flm_bytes, Some(17));
        assert_eq!(
            controls.geometry,
            Some(Geometry {
                width: 4,
                height: 3,
                viewport_rows: Some(2),
            })
        );
        assert_eq!(controls.controls.len(), 2);
        let tick = controls.controls.get(&7).expect("tick 7 controls");
        assert_eq!(tick.sky, 0);
        assert_eq!(tick.brightness, 32768);
        assert_eq!(tick.saturation, 32768);
        assert!(controls.controls.contains_key(&9));
    }

    #[test]
    fn capture_fixture_pins_frames_and_ignores_harness_diagnostics() {
        let raw: Value = serde_json::from_str(
            &fs::read_to_string(corpus().join("meta.json")).expect("read meta.json"),
        )
        .expect("parse meta.json");
        assert_eq!(raw["palette_source"].as_str(), Some("measured"));
        assert_eq!(
            raw["frames"][0]["palette_source"].as_str(),
            Some("measured")
        );

        let capture = load_capture(&corpus()).expect("load capture");
        assert_eq!(capture.schema_version, SCHEMA_VERSION);
        assert_eq!(
            capture.geometry,
            Geometry {
                width: 4,
                height: 3,
                viewport_rows: None,
            }
        );
        assert_eq!(capture.frames.len(), 2);
        assert_eq!(
            (capture.frames[0].ordinal, capture.frames[0].film_tick),
            (1, 7)
        );
        assert_eq!(
            (capture.frames[1].ordinal, capture.frames[1].film_tick),
            (2, 9)
        );
        assert_eq!(capture.frames[0].frame_file, "tick_0001.idx");
        assert_eq!(capture.frames[1].frame_file, "tick_0002.idx");
        assert_eq!(capture.frames[1].palette_file, "palettes_0002.json");
    }

    #[test]
    fn legacy_capture_fixture_reads_as_version_one() {
        let raw: Value = serde_json::from_str(
            &fs::read_to_string(corpus().join("meta_legacy.json")).expect("read meta_legacy.json"),
        )
        .expect("parse meta_legacy.json");
        assert!(
            raw.get("schema_version").is_none(),
            "the fixture must stay a legacy document"
        );

        let legacy: CaptureSet = serde_json::from_value(raw).expect("legacy capture");
        assert_eq!(legacy.schema_version, SCHEMA_VERSION);
        assert_eq!(legacy.frames.len(), 2);
        assert_eq!(legacy.frames[0].film_tick, 7);
        legacy.validate().expect("legacy capture is valid");
    }

    #[test]
    fn report_fixture_round_trips_typed_and_satisfies_its_identities() {
        let report = read_report(&corpus().join("report.json")).expect("read report.json");
        report.validate().expect("valid report");
        assert_eq!(report.reference_frames, 3);
        assert_eq!(report.frames, 2);
        assert_eq!(report.scored_frames, 1);
        assert_eq!(report.excluded_frames, 1);
        assert_eq!(report.unmatched, 1);
        assert_eq!(report.sky_indices, [228, 238]);

        let text = serde_json::to_string(&report).expect("re-serialise report");
        let back: Report = serde_json::from_str(&text).expect("re-read report");

        assert_eq!(back.reference_frames, report.reference_frames);
        assert_eq!(back.frames, report.frames);
        assert_eq!(back.unmatched, report.unmatched);
        assert_eq!(back.sky_indices, report.sky_indices);
        assert_eq!(back.i6_gate, report.i6_gate);
        assert_eq!(back.scored_frames, report.scored_frames);
        assert_eq!(back.excluded_frames, report.excluded_frames);
        assert_close(back.mean_ssim, report.mean_ssim, "mean_ssim");
        assert_close(back.min_ssim, report.min_ssim, "min_ssim");
        assert_close(back.mean_iou, report.mean_iou, "mean_iou");
        assert_close(back.min_fade_level, report.min_fade_level, "min_fade_level");
        assert_close_option(
            back.mean_ssim_scored,
            report.mean_ssim_scored,
            "mean_ssim_scored",
        );
        assert_close_option(
            back.mean_iou_scored,
            report.mean_iou_scored,
            "mean_iou_scored",
        );
        assert_close_option(
            back.mean_index_agreement_scored,
            report.mean_index_agreement_scored,
            "mean_index_agreement_scored",
        );
        assert_close_map(
            back.mean_loss_by_class_scored.as_ref(),
            report.mean_loss_by_class_scored.as_ref(),
            "mean_loss_by_class_scored",
        );

        assert_eq!(back.per_frame.len(), report.per_frame.len());
        for (index, (back_frame, frame)) in back.per_frame.iter().zip(&report.per_frame).enumerate()
        {
            let field = |name: &str| format!("per_frame[{index}].{name}");
            assert_eq!(back_frame.ordinal, frame.ordinal);
            assert_eq!(back_frame.film_tick, frame.film_tick);
            assert_eq!(back_frame.scored, frame.scored);
            assert_close(back_frame.ssim, frame.ssim, &field("ssim"));
            assert_close(back_frame.iou, frame.iou, &field("iou"));
            assert_close_option(
                back_frame.index_agreement,
                frame.index_agreement,
                &field("index_agreement"),
            );
            assert_close_map(
                back_frame.loss_by_class.as_ref(),
                frame.loss_by_class.as_ref(),
                &field("loss_by_class"),
            );
            assert_close_option(
                back_frame.fade_level,
                frame.fade_level,
                &field("fade_level"),
            );
            assert_close_option(
                back_frame.authored_fade_level,
                frame.authored_fade_level,
                &field("authored_fade_level"),
            );
        }
    }

    #[test]
    fn page_fixture_pins_the_index_and_layer_rows() {
        let geometry = Geometry {
            width: 4,
            height: 3,
            viewport_rows: Some(2),
        };
        // read_page_planes derives the two plane paths from this stem and never opens the PNG.
        let planes = read_page_planes(&corpus().join("pages/tick_00007.png"), &geometry)
            .expect("read page planes");
        assert_eq!(planes.indices.len(), 12);
        assert_eq!(planes.layers.len(), 12);

        let rows: [([u8; 4], [u16; 4]); 3] = [
            ([180, 180, 180, 180], [0, 0, 0, 0]),
            ([0, 40, 40, 0], [0, 16, 16, 0]),
            ([0, 0, 0, 0], [16, 16, 16, 16]),
        ];
        for (row, (indices, layers)) in rows.into_iter().enumerate() {
            let start = row * 4;
            assert_eq!(
                &planes.indices[start..start + 4],
                &indices[..],
                "row {row} indices"
            );
            // Row 2 lies outside the 2-row viewport but the reader still returns it.
            assert_eq!(
                &planes.layers[start..start + 4],
                &layers[..],
                "row {row} layers"
            );
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    use stunt_core::contracts::PaletteControls;
    use stunt_core::scene::SceneFrame;

    fn temp_dir(name: &str) -> PathBuf {
        let dir = std::env::temp_dir().join(format!(
            "stunt-reel-parity-artifacts-{name}-{}",
            std::process::id()
        ));
        drop(fs::remove_dir_all(&dir));
        fs::create_dir_all(&dir).expect("create temp dir");
        dir
    }

    fn frame() -> SceneFrame {
        SceneFrame {
            tick: 7.0,
            view: ViewCamera::default(),
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
    fn journal_writes_the_record_and_no_legacy_sidecar() {
        let dir = temp_dir("journal");
        let mut journal = RenderJournal::begin(&dir, FilmId::default(), geometry());
        journal.record(7, &frame());
        journal.finish().expect("finish");

        assert!(dir.join(RENDER_DOCUMENT).is_file());
        assert!(!dir.join(LEGACY_SIDECAR).exists());

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
    fn capture_names_and_legacy_defaults_come_from_the_port() {
        let dir = temp_dir("capture");
        let meta = json!({
            "film": "CTRY.FLM",
            "flm_bytes": 10,
            "palette_source": "dacpal",
            "frames": [
                {"film_tick": 9, "global_tick": 12},
                {"film_tick": 10, "frame_file": "other.idx", "palette_file": "palettes_0002.json"},
            ],
        });
        write_json(&dir.join(CAPTURE_META), &meta, false).expect("write meta");
        let set = load_capture(&dir).expect("load capture");
        assert_eq!(set.schema_version, SCHEMA_VERSION);
        assert_eq!(set.geometry.width, 320);
        assert_eq!(set.geometry.height, 200);
        assert_eq!(set.frames.len(), 2);
        assert_eq!(set.frames[0].frame_file, "tick_0001.idx");
        assert_eq!(set.frames[0].palette_file, "palettes_0001.json");
        assert_eq!(set.frames[1].frame_file, "other.idx");
        assert_eq!(set.frames[1].ordinal, 2);
    }

    #[test]
    fn a_capture_palette_file_must_be_a_basename() {
        let dir = temp_dir("palette-basename");
        let meta = json!({
            "frames": [{"film_tick": 1, "palette_file": "../palettes_0001.json"}],
        });
        write_json(&dir.join(CAPTURE_META), &meta, false).expect("write meta");
        let error = load_capture(&dir).expect_err("palette path");
        assert!(error.to_string().contains("palette_file"), "{error}");
    }

    #[test]
    fn a_capture_without_a_film_tick_is_rejected_with_the_recapture_action() {
        let dir = temp_dir("untagged");
        let meta = json!({
            "frames": [{"film_tick": 1}, {}],
        });
        write_json(&dir.join(CAPTURE_META), &meta, false).expect("write meta");
        let error = load_capture(&dir).expect_err("untagged frame");
        assert!(error.to_string().contains("frame 2"), "{error}");
        assert!(error.to_string().contains("recaptured"), "{error}");
    }

    #[test]
    fn a_render_without_any_document_is_refused() {
        let dir = temp_dir("no-document");
        let error = load_render_controls(&dir).expect_err("no document");
        assert!(error.to_string().contains("re-render"), "{error}");
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
