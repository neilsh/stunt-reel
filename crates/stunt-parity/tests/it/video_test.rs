use stunt_parity::*;

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
        },
        palettes: PaletteLog {
            initial: vec![[0, 0, 0]; 256],
            changes: vec![PaletteChange {
                frame: 103,
                first: 32,
                rgb: vec![[255, 0, 0]; 32],
            }],
        },
    }
}

fn reason(error: ArtifactError) -> String {
    match error {
        ArtifactError::VideoLog { reason } => reason,
        other => panic!("expected VideoLog, got {other:?}"),
    }
}

#[test]
fn the_engine_hash_is_optional_on_read_and_kept_when_present() {
    let without = serde_json::to_value(capture()).expect("serialise");
    assert!(without.get("playone_sha256").is_none());
    let old: VideoCapture = serde_json::from_value(without).expect("a capture without it");
    assert_eq!(old.playone_sha256, None);
    old.validate().expect("valid");

    let mut named = capture();
    named.playone_sha256 = Some("ab".repeat(32));
    let json = serde_json::to_value(&named).expect("serialise");
    assert_eq!(json["playone_sha256"], "ab".repeat(32));
    let back: VideoCapture = serde_json::from_value(json).expect("a capture with it");
    assert_eq!(back, named);
}

#[test]
fn a_valid_log_passes() {
    capture().validate().expect("valid");
}

#[test]
fn a_kind_other_than_video_is_rejected() {
    let mut absent = capture();
    absent.kind = String::new();
    assert_eq!(
        absent.validate(),
        Err(ArtifactError::MissingField {
            field: "kind".to_string()
        })
    );
    let mut frames = capture();
    frames.kind = "frames".to_string();
    reason(frames.validate().expect_err("kind"));
}

#[test]
fn columns_of_different_length_are_rejected() {
    let mut document = capture();
    document.log.global_tick.pop();
    assert!(reason(document.validate().expect_err("columns")).contains("length"));
}

#[test]
fn frames_must_ascend_by_one() {
    let mut document = capture();
    document.log.frame = vec![101, 103, 104, 105];
    assert!(reason(document.validate().expect_err("gap")).contains("index 1"));
}

#[test]
fn film_tick_may_not_fall_after_the_film_starts() {
    let mut document = capture();
    document.log.film_tick = vec![7, 7, 9, 8];
    assert!(reason(document.validate().expect_err("fall")).contains("frame 104"));
}

#[test]
fn film_start_frame_must_be_a_logged_frame() {
    let mut document = capture();
    document.film_start_frame = 200;
    assert!(reason(document.validate().expect_err("start")).contains("film_start_frame"));
}

#[test]
fn the_initial_palette_has_256_entries() {
    let mut document = capture();
    document.palettes.initial.pop();
    assert!(reason(document.validate().expect_err("palette")).contains("256"));
}

#[test]
fn a_change_must_fit_inside_256_entries() {
    let mut document = capture();
    document.palettes.changes[0].first = 250;
    assert!(reason(document.validate().expect_err("overflow")).contains("past entry"));
}

#[test]
fn changes_must_ascend_and_lie_in_the_log() {
    let mut outside = capture();
    outside.palettes.changes[0].frame = 105;
    assert!(reason(outside.validate().expect_err("outside")).contains("outside the log"));
    let mut unordered = capture();
    let again = unordered.palettes.changes[0].clone();
    unordered.palettes.changes.push(PaletteChange {
        frame: 102,
        ..again
    });
    assert!(reason(unordered.validate().expect_err("order")).contains("ascend"));
}

#[test]
fn video_index_counts_from_the_capture_start() {
    let document = capture();
    assert_eq!(document.video_index(101), Some(1));
    assert_eq!(document.video_index(99), None);
}
