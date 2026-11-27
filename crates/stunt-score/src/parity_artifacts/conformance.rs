use super::*;
use crate::render_store::{Palette, RenderStore};
use std::collections::BTreeMap;
use stunt_parity::AdapterClass;
use stunt_parity::SCHEMA_VERSION;

/// The shared corpus, resolved without the process working directory.
fn corpus() -> PathBuf {
    crate::test_support::workspace_root().join("tests/fixtures/parity/v1")
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

/// The version-4 render under `tests/fixtures/parity/v4/render`.
fn v4_render() -> PathBuf {
    crate::test_support::workspace_root().join("tests/fixtures/parity/v4/render")
}

/// The adapter the v4 render and the v1 report name.
fn fixture_adapter() -> RenderAdapter {
    RenderAdapter {
        name: "Test GPU".to_string(),
        class: AdapterClass::Hardware,
    }
}

/// Tick 7: sky over two actor pixels, with a layer-16 row below the 2-row viewport.
const TICK_7_ROWS: [([u8; 4], [u16; 4]); 3] = [
    ([180, 180, 180, 180], [0, 0, 0, 0]),
    ([0, 40, 40, 0], [0, 16, 16, 0]),
    ([0, 0, 0, 0], [16, 16, 16, 16]),
];

/// The fixture's ticks: three in second 0, none in second 1, two in second 2.
const V4_TICKS: [u32; 5] = [7, 9, 30, 100, 149];
/// The one fixture tick whose record expects credits.
const V4_CREDITS_TICK: u32 = 9;

/// Every other tick is tick 7 with its indices raised by `tick - 7`.
fn v4_planes(tick: u32) -> (Vec<u8>, Vec<u32>) {
    let shift = u8::try_from(tick - 7).unwrap();
    TICK_7_ROWS
        .iter()
        .flat_map(|(indices, layers)| indices.iter().zip(layers))
        .map(|(&index, &layer)| (index.wrapping_add(shift), u32::from(layer)))
        .unzip()
}

/// The shape plane of every tick: shape word 5 on each layer-16 pixel, 0 elsewhere.
fn v4_shapes(layers: &[u32]) -> Vec<u32> {
    layers
        .iter()
        .map(|&layer| if layer == 16 { 5 } else { 0 })
        .collect()
}

/// Ticks 30 and 149 use the second palette, entry i = (255 - i, i, 0); the rest a grey ramp.
fn v4_palette(tick: u32) -> Palette {
    std::array::from_fn(|i| {
        let i = u8::try_from(i).unwrap();
        if tick == 30 || tick == 149 {
            (255 - i, i, 0)
        } else {
            (i, i, i)
        }
    })
}

/// Regenerates the v4 render fixture. Run it by hand after a format change:
/// `cargo test -p stunt-score write_v4_render_fixture -- --ignored`.
#[test]
#[ignore = "writes the committed fixture"]
fn write_v4_render_fixture() {
    let dir = v4_render();
    fs::create_dir_all(&dir).expect("create fixture dir");
    let geometry = Geometry {
        width: 4,
        height: 3,
        viewport_rows: Some(2),
    };
    let mut writer = StoreWriter::new(&dir, &geometry);
    let mut ticks = Vec::new();
    for tick in V4_TICKS {
        let (indices, layers) = v4_planes(tick);
        let palette_index = writer
            .push(
                tick,
                &v4_palette(tick),
                &indices,
                &layers,
                &v4_shapes(&layers),
            )
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
            credits: tick == V4_CREDITS_TICK,
        });
    }
    let table = writer.finish().expect("finish").expect("a store");
    let record = RenderRecord {
        schema_version: RENDER_SCHEMA_VERSION,
        film: FilmId {
            name: Some("SYNTH.FLM".to_string()),
            flm_bytes: Some(17),
            flm_sha256: None,
            all_sha256: None,
        },
        geometry,
        ticks,
        palette_count: table.palette_count,
        chunks: table.chunks,
        planes: table.planes,
        adapter: Some(fixture_adapter()),
    };
    write_render_record(&dir, &record).expect("write record");
}

#[test]
fn render_fixture_pins_identity_geometry_chunks_and_controls() {
    let store = RenderStore::open(&v4_render()).expect("open the v4 render");
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
    assert_eq!(ticks, V4_TICKS);
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
    let credits: Vec<u32> = record
        .ticks
        .iter()
        .filter(|t| t.credits)
        .map(|t| t.tick)
        .collect();
    assert_eq!(credits, vec![V4_CREDITS_TICK]);
    assert_eq!(record.adapter, Some(fixture_adapter()));
}

#[test]
fn render_fixture_pins_every_tick_planes_and_palette() {
    let mut store = RenderStore::open(&v4_render()).expect("open the v4 render");
    for tick in V4_TICKS {
        let frame = store.frame(tick).expect("frame");
        let (indices, layers) = v4_planes(tick);
        assert_eq!(frame.indices, indices, "tick {tick} indices");
        let layers: Vec<u16> = layers
            .iter()
            .map(|&layer| u16::try_from(layer).unwrap())
            .collect();
        // Row 2 lies outside the 2-row viewport but the reader still returns it.
        assert_eq!(frame.layers, layers, "tick {tick} layers");
        let shapes: Vec<u16> = frame
            .layers
            .iter()
            .map(|&layer| if layer == 16 { 5 } else { 0 })
            .collect();
        assert_eq!(frame.shapes, Some(shapes), "tick {tick} shapes");
        assert_eq!(frame.palette, v4_palette(tick), "tick {tick} palette");
    }
    let (indices, _) = v4_planes(7);
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
    let dir = crate::test_support::workspace_root().join("tests/fixtures/parity/video");
    let capture = load_video_capture(&dir).expect("load video capture");
    assert_eq!(capture.log.frame.len(), 4);
    assert_eq!(capture.palettes.changes.len(), 1);
    assert_eq!(capture.palettes.changes[0].frame, 103);
    assert_eq!(capture.film_start_frame, 103);
}

#[test]
fn the_video_fixture_with_slot_columns_loads() {
    let dir = crate::test_support::workspace_root().join("tests/fixtures/parity/video/with-slots");
    let capture = load_video_capture(&dir).expect("load video capture");
    assert_eq!(capture.log.slot_clock.as_deref(), Some(&[5, 5, 6, 7][..]));
    assert_eq!(capture.log.slot_ticks.as_deref(), Some(&[0, 1, 2, 1][..]));
    assert_eq!(capture.film_ticks, Some([7, 9]));
    let video = capture.video.expect("video");
    assert_eq!(video.frame_rate, [2_190_197, 31_250]);
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
    assert_eq!(report.adapter, Some(fixture_adapter()));

    let text = serde_json::to_string(&report).expect("re-serialise report");
    let back: Report = serde_json::from_str(&text).expect("re-read report");

    assert_eq!(back.reference_frames, report.reference_frames);
    assert_eq!(back.frames, report.frames);
    assert_eq!(back.unmatched, report.unmatched);
    assert_eq!(back.sky_indices, report.sky_indices);
    assert_eq!(back.i6_gate, report.i6_gate);
    assert_eq!(back.scored_frames, report.scored_frames);
    assert_eq!(back.excluded_frames, report.excluded_frames);
    assert_eq!(back.adapter, report.adapter);
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
    assert_close_map(
        back.mean_loss_by_shape_scored.as_ref(),
        report.mean_loss_by_shape_scored.as_ref(),
        "mean_loss_by_shape_scored",
    );

    assert_eq!(back.per_frame.len(), report.per_frame.len());
    for (index, (back_frame, frame)) in back.per_frame.iter().zip(&report.per_frame).enumerate() {
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
