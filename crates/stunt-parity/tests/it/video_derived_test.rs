use std::collections::BTreeMap;

use stunt_parity::*;

const META: &str = "ab";
const VIDEO: &str = "cd";

fn capture() -> VideoCapture {
    VideoCapture {
        schema_version: SCHEMA_VERSION,
        kind: "video".to_string(),
        film: FilmId::default(),
        geometry: Geometry {
            width: 4,
            height: 2,
            viewport_rows: None,
        },
        playone_build: "synthetic".to_string(),
        playone_sha256: None,
        cpu_profile: "capture".to_string(),
        capture_start_frame: 100,
        film_start_frame: 103,
        end: CaptureEnd::Hold,
        log: TickLog {
            frame: vec![101, 102, 103, 104],
            film_tick: vec![7, 7, 8, 9],
            global_tick: vec![0, 1, 2, 3],
            slot_clock: Some(vec![5, 5, 6, 7]),
            slot_ticks: Some(vec![0, 1, 2, 1]),
        },
        palettes: PaletteLog {
            initial: vec![[0, 0, 0]; 256],
            changes: vec![PaletteChange {
                frame: 103,
                first: 32,
                rgb: vec![[255, 0, 0]; 32],
            }],
        },
        video_frames: None,
        rows: None,
        palette_changes: None,
        dgroup_segment: None,
        captured_on: None,
        checkout: None,
        sound_samples: None,
        video: None,
        emulator: None,
        layout: None,
        film_ticks: None,
    }
}

fn derived(capture: &VideoCapture) -> VideoDerived {
    let (rules, frames) = capture.derive();
    VideoDerived {
        schema_version: SCHEMA_VERSION,
        kind: "video-derived".to_string(),
        source: DerivedSource {
            meta_sha256: META.repeat(32),
            video_sha256: VIDEO.repeat(32),
        },
        rules,
        frames,
        reference_check: None,
    }
}

fn reason(error: ArtifactError) -> String {
    match error {
        ArtifactError::VideoLog { reason } => reason,
        other => panic!("expected VideoLog, got {other:?}"),
    }
}

#[test]
fn render_tick_is_the_slot_clock_less_the_ticks_word_plus_one() {
    let (rules, columns) = capture().derive();
    assert_eq!(rules.render_tick, RenderTickRule::Adr0057);
    assert_eq!(columns.render_tick, vec![6, 5, 5, 7]);
}

#[test]
fn render_tick_falls_back_to_the_tag_when_the_ticks_word_exceeds_the_clock() {
    let mut document = capture();
    document.log.slot_ticks = Some(vec![0, 1, 9, 1]);
    let (_, columns) = document.derive();
    assert_eq!(columns.render_tick, vec![6, 5, 8, 7]);
}

#[test]
fn render_tick_is_the_tag_without_the_words() {
    let mut document = capture();
    document.log.slot_clock = None;
    document.log.slot_ticks = None;
    let (rules, columns) = document.derive();
    assert_eq!(rules.render_tick, RenderTickRule::FilmTick);
    assert_eq!(columns.render_tick, vec![7, 7, 8, 9]);
}

#[test]
fn palette_step_marks_the_frame_a_write_took_effect() {
    let (_, columns) = capture().derive();
    assert_eq!(columns.palette_step, vec![false, false, true, false]);
}

#[test]
fn the_columns_are_as_long_as_the_log() {
    let document = capture();
    let (_, columns) = document.derive();
    assert_eq!(columns.render_tick.len(), document.log.frame.len());
    assert_eq!(columns.palette_step.len(), document.log.frame.len());
}

#[test]
fn a_matching_document_validates_and_round_trips() {
    let document = derived(&capture());
    document
        .validate_against(&capture(), &META.repeat(32), &VIDEO.repeat(32))
        .expect("valid");
    let json = serde_json::to_value(&document).expect("serialise");
    assert!(json.get("reference_check").is_none());
    let back: VideoDerived = serde_json::from_value(json).expect("read");
    assert_eq!(back, document);
}

#[test]
fn columns_of_different_length_are_rejected() {
    let mut document = derived(&capture());
    document.frames.palette_step.pop();
    assert!(reason(document.validate().expect_err("length")).contains("length"));
}

#[test]
fn a_changed_source_hash_is_stale() {
    let document = derived(&capture());
    let error = document
        .validate_against(&capture(), &"00".repeat(32), &VIDEO.repeat(32))
        .expect_err("stale");
    assert!(reason(error).contains("stale"));
    let mut malformed = document;
    malformed.source.video_sha256 = "AB".to_string();
    assert!(reason(malformed.validate().expect_err("hex")).contains("video_sha256"));
}

#[test]
fn a_column_that_disagrees_with_the_rule_is_rejected() {
    let mut document = derived(&capture());
    document.frames.render_tick[0] = 7;
    let error = document
        .validate_against(&capture(), &META.repeat(32), &VIDEO.repeat(32))
        .expect_err("rule");
    assert!(reason(error).contains("render_tick"));
}

#[test]
fn the_reference_check_counts_must_agree() {
    let mut document = derived(&capture());
    let check = ReferenceCheck {
        capture_digest: "ef".repeat(32),
        rows: [0, 184],
        search: 8,
        pages: 3,
        skipped: 1,
        offsets: BTreeMap::from([("0".to_string(), 1), ("-1".to_string(), 1)]),
        pixel_equal: PixelEqual {
            min: 0.96,
            median: 0.9997,
        },
        exact_pages: 1,
        split_pages: 1,
        band_pages: 0,
    };
    document.reference_check = Some(check.clone());
    document.validate().expect("consistent");
    let mut wrong = check;
    wrong.pages = 5;
    document.reference_check = Some(wrong);
    assert!(reason(document.validate().expect_err("counts")).contains("disagree"));
}
