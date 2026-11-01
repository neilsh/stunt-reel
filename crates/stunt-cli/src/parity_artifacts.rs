//! Filesystem adapter for the parity artifact port (`stunt-parity`).
//!
//! The port owns the schema; this module owns the files. It is the only place
//! the CLI learns artifact names and JSON details, and the only place that
//! writes `render.json`; the plane files beside it belong to `render_store`.

#[cfg(test)]
use std::collections::BTreeMap;
use std::fs;
use std::path::{Path, PathBuf};

use serde::Serialize;
use serde_json::Value;
use stunt_core::contracts::PaletteControls;
use stunt_core::scene::ViewCamera;
#[cfg(test)]
use stunt_parity::SCHEMA_VERSION;
use stunt_parity::{
    ArtifactError as SchemaError, CameraPose, CaptureSet, FilmId, Geometry, RENDER_SCHEMA_VERSION,
    RenderPalette, RenderRecord, RenderTick, Report, VideoCapture,
};
use stunt_render::RenderedPage;

use crate::render_store::{StoreError, StoreWriter, check_derivable};

/// Document written beside a render directory's frames, last.
pub(crate) const RENDER_DOCUMENT: &str = "render.json";
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

fn camera_pose(camera: ViewCamera) -> CameraPose {
    CameraPose {
        eye: camera.eye,
        target: camera.target,
        fov_degrees: camera.fov_degrees,
        roll_radians: camera.roll_radians,
    }
}

/// Collects one render directory: its planes through the store, and its document, written last.
pub(crate) struct RenderJournal {
    dir: PathBuf,
    film: FilmId,
    geometry: Geometry,
    ticks: Vec<RenderTick>,
    store: StoreWriter,
}

impl RenderJournal {
    /// Starts a journal for `dir`; the caller has already created the directory.
    pub(crate) fn begin(dir: &Path, film: FilmId, geometry: Geometry) -> Self {
        Self {
            dir: dir.to_path_buf(),
            film,
            store: StoreWriter::new(dir, &geometry),
            geometry,
            ticks: Vec::new(),
        }
    }

    /// Stores the page drawn for film-clock `tick` with `controls` from `camera`.
    ///
    /// The page's picture is not kept: it must be `palette[index]` at every pixel for the
    /// film palette of `controls`, and a page that is not is refused.
    pub(crate) fn write(
        &mut self,
        tick: u32,
        controls: PaletteControls,
        camera: ViewCamera,
        page: &RenderedPage,
    ) -> Result<(), StoreError> {
        let palette = controls.film_palette();
        check_derivable(&palette, page.indices(), page.rgba(), page.width()).map_err(
            |message| StoreError::Corrupt {
                path: self.dir.clone(),
                message: format!("tick {tick}: {message}"),
            },
        )?;
        let palette_index = self
            .store
            .push(tick, &palette, page.indices(), page.layers())?;
        self.ticks.push(RenderTick {
            tick,
            palette: render_palette(controls),
            camera: camera_pose(camera),
            palette_index,
        });
        Ok(())
    }

    /// Closes the store and writes `render.json` last; neither is written when no whole-tick
    /// frame was stored.
    pub(crate) fn finish(self) -> Result<(), StoreError> {
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
        };
        write_render_record(&self.dir, &record).map_err(StoreError::Record)
    }
}

/// Reads and validates a render directory's `render.json`.
pub(crate) fn read_render_record(dir: &Path) -> Result<RenderRecord, AdapterError> {
    let path = dir.join(RENDER_DOCUMENT);
    let value = read_json(&path)?;
    let version = value.get("schema_version").and_then(Value::as_u64);
    if version != Some(u64::from(RENDER_SCHEMA_VERSION)) {
        return Err(schema(
            &path,
            SchemaError::UnsupportedVersion {
                found: version.and_then(|v| u32::try_from(v).ok()).unwrap_or(0),
                expected: RENDER_SCHEMA_VERSION,
            },
        ));
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
pub(crate) fn write_render_record(dir: &Path, record: &RenderRecord) -> Result<(), AdapterError> {
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
#[allow(
    dead_code,
    reason = "only tests read video captures until a video scorer is merged (method.md § 4.4)"
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
/// `tests/fixtures/parity/v2` (renders), read through this adapter.
#[cfg(test)]
mod conformance {
    use super::*;
    use crate::render_store::{Palette, RenderStore};
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

    /// The version-2 render under `tests/fixtures/parity/v2/render`.
    fn v2_render() -> PathBuf {
        Path::new(env!("CARGO_MANIFEST_DIR")).join("../../tests/fixtures/parity/v2/render")
    }

    /// Tick 7: sky over two actor pixels, with a layer-16 row below the 2-row viewport.
    const TICK_7_ROWS: [([u8; 4], [u16; 4]); 3] = [
        ([180, 180, 180, 180], [0, 0, 0, 0]),
        ([0, 40, 40, 0], [0, 16, 16, 0]),
        ([0, 0, 0, 0], [16, 16, 16, 16]),
    ];

    /// The fixture's ticks: three in second 0, none in second 1, two in second 2.
    const V2_TICKS: [u32; 5] = [7, 9, 30, 100, 149];

    /// Every other tick is tick 7 with its indices raised by `tick - 7`.
    fn v2_planes(tick: u32) -> (Vec<u8>, Vec<u32>) {
        let shift = (tick - 7) as u8;
        TICK_7_ROWS
            .iter()
            .flat_map(|(indices, layers)| indices.iter().zip(layers))
            .map(|(&index, &layer)| (index.wrapping_add(shift), u32::from(layer)))
            .unzip()
    }

    /// Ticks 30 and 149 use the second palette, entry i = (255 - i, i, 0); the rest a grey ramp.
    fn v2_palette(tick: u32) -> Palette {
        std::array::from_fn(|i| {
            let i = i as u8;
            if tick == 30 || tick == 149 {
                (255 - i, i, 0)
            } else {
                (i, i, i)
            }
        })
    }

    /// Regenerates the v2 render fixture. Run it by hand after a format change:
    /// `cargo test -p stunt-cli write_v2_render_fixture -- --ignored`.
    #[test]
    #[ignore = "writes the committed fixture"]
    fn write_v2_render_fixture() {
        let dir = v2_render();
        fs::create_dir_all(&dir).expect("create fixture dir");
        let geometry = Geometry {
            width: 4,
            height: 3,
            viewport_rows: Some(2),
        };
        let mut writer = StoreWriter::new(&dir, &geometry);
        let mut ticks = Vec::new();
        for tick in V2_TICKS {
            let (indices, layers) = v2_planes(tick);
            let palette_index = writer
                .push(tick, &v2_palette(tick), &indices, &layers)
                .expect("push");
            let half = tick == 30 || tick == 149;
            ticks.push(RenderTick {
                tick,
                palette: RenderPalette {
                    sky: 0,
                    brightness: if half { 16384 } else { 32768 },
                    saturation: 32768,
                },
                camera: CameraPose {
                    eye: [0.0, 10.0, 43.0 + tick as f32],
                    target: [0.0, 10.0, 0.0],
                    fov_degrees: 45.0,
                    roll_radians: 0.0,
                },
                palette_index,
            });
        }
        let table = writer.finish().expect("finish").expect("a store");
        let record = RenderRecord {
            schema_version: RENDER_SCHEMA_VERSION,
            film: FilmId {
                name: Some("SYNTH.FLM".to_string()),
                flm_bytes: Some(17),
                flm_sha256: None,
            },
            geometry,
            ticks,
            palette_count: table.palette_count,
            chunks: table.chunks,
        };
        write_render_record(&dir, &record).expect("write record");
    }

    #[test]
    fn render_fixture_pins_identity_geometry_chunks_and_controls() {
        let store = RenderStore::open(&v2_render()).expect("open the v2 render");
        let record = store.record();
        assert_eq!(record.film.name.as_deref(), Some("SYNTH.FLM"));
        assert_eq!(record.film.flm_bytes, Some(17));
        assert_eq!(
            record.geometry,
            Geometry {
                width: 4,
                height: 3,
                viewport_rows: Some(2),
            }
        );
        let ticks: Vec<u32> = record.ticks.iter().map(|tick| tick.tick).collect();
        assert_eq!(ticks, V2_TICKS);
        let seconds: Vec<(u32, u32)> = record
            .chunks
            .iter()
            .map(|chunk| (chunk.second, chunk.ticks))
            .collect();
        assert_eq!(seconds, vec![(0, 3), (2, 2)]);
        assert_eq!(record.palette_count, 2);
        let indices: Vec<u32> = record.ticks.iter().map(|t| t.palette_index).collect();
        assert_eq!(indices, vec![0, 0, 1, 0, 1]);
        assert_eq!(record.ticks[0].palette.brightness, 32768);
        assert_eq!(record.ticks[2].palette.brightness, 16384);
    }

    #[test]
    fn render_fixture_pins_every_tick_planes_and_palette() {
        let mut store = RenderStore::open(&v2_render()).expect("open the v2 render");
        for tick in V2_TICKS {
            let frame = store.frame(tick).expect("frame");
            let (indices, layers) = v2_planes(tick);
            assert_eq!(frame.indices, indices, "tick {tick} indices");
            let layers: Vec<u16> = layers.iter().map(|&layer| layer as u16).collect();
            // Row 2 lies outside the 2-row viewport but the reader still returns it.
            assert_eq!(frame.layers, layers, "tick {tick} layers");
            assert_eq!(frame.palette, v2_palette(tick), "tick {tick} palette");
        }
        let (indices, _) = v2_planes(7);
        assert_eq!(&indices[4..8], &[0, 40, 40, 0]);
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
    fn the_video_fixture_loads() {
        let dir = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../tests/fixtures/parity/video");
        let capture = load_video_capture(&dir).expect("load video capture");
        assert_eq!(capture.log.frame.len(), 4);
        assert_eq!(capture.palettes.changes.len(), 1);
        assert_eq!(capture.palettes.changes[0].frame, 103);
        assert_eq!(capture.film_start_frame, 103);
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

    fn page(controls: PaletteControls, tamper: bool) -> RenderedPage {
        let palette = controls.film_palette();
        let plane: Vec<u32> = (0..320 * 200)
            .map(|pixel: u32| (16 << 8) | (pixel % 251))
            .collect();
        let mut rgba: Vec<u8> = plane
            .iter()
            .flat_map(|&word| {
                let (r, g, b) = palette[(word & 0xFF) as usize];
                [r, g, b, 255]
            })
            .collect();
        if tamper {
            rgba[0] ^= 1;
        }
        RenderedPage::new(stunt_render::PageSize::new(320, 200), rgba, plane).expect("page")
    }

    #[test]
    fn journal_writes_the_store_and_the_record_last() {
        let dir = temp_dir("journal");
        let mut journal = RenderJournal::begin(&dir, FilmId::default(), geometry());
        let frame = frame();
        journal
            .write(7, frame.palette, frame.view, &page(frame.palette, false))
            .expect("write");
        assert!(
            !dir.join(RENDER_DOCUMENT).exists(),
            "the record is written last"
        );
        journal.finish().expect("finish");

        let record = read_render_record(&dir).expect("read");
        assert_eq!(record.geometry, geometry());
        assert_eq!(record.ticks.len(), 1);
        assert_eq!(record.ticks[0].palette.sky, 0x2000);
        assert_eq!(record.palette_count, 1);
        let mut store = crate::render_store::RenderStore::open(&dir).expect("open");
        let stored = store.frame(7).expect("frame");
        assert_eq!(stored.palette, frame.palette.film_palette());
        assert_eq!(stored.layers[0], 16);
    }

    #[test]
    fn a_page_whose_picture_is_not_its_palette_lookup_is_refused() {
        let dir = temp_dir("tampered");
        let mut journal = RenderJournal::begin(&dir, FilmId::default(), geometry());
        let frame = frame();
        let error = journal
            .write(7, frame.palette, frame.view, &page(frame.palette, true))
            .unwrap_err()
            .to_string();
        assert!(error.contains("tick 7: pixel (0, 0)"), "{error}");
    }

    #[test]
    fn an_empty_journal_writes_no_documents() {
        let dir = temp_dir("empty");
        RenderJournal::begin(&dir, FilmId::default(), geometry())
            .finish()
            .expect("finish");
        assert!(!dir.join(RENDER_DOCUMENT).exists());
        assert!(!dir.join(crate::render_store::INDEX_FILE).exists());
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
    fn a_render_without_a_record_is_refused() {
        let dir = temp_dir("no-document");
        let error = read_render_record(&dir).expect_err("no document");
        assert!(error.to_string().contains("render.json"), "{error}");
    }

    #[test]
    fn a_wrong_schema_version_is_rejected_before_its_fields() {
        let dir = temp_dir("version");
        for version in [1, 9] {
            write_json(
                &dir.join(RENDER_DOCUMENT),
                &json!({
                    "schema_version": version,
                    "film": {},
                    "geometry": {"width": 320, "height": 200},
                    "ticks": [],
                }),
                true,
            )
            .expect("write record");
            let error = read_render_record(&dir).expect_err("other version");
            assert!(
                error
                    .to_string()
                    .contains(&format!("schema version {version}; expected 2")),
                "{error}"
            );
        }
    }
}
