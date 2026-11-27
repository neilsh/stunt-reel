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
            slot_clock: None,
            slot_ticks: None,
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

fn with_slots() -> VideoCapture {
    let mut document = capture();
    document.log.slot_clock = Some(vec![5, 5, 6, 7]);
    document.log.slot_ticks = Some(vec![0, 1, 2, 1]);
    document
}

fn described() -> VideoCapture {
    let mut document = with_slots();
    document.video_frames = Some(4);
    document.rows = Some(4);
    document.palette_changes = Some(1);
    document.dgroup_segment = Some("0E66".to_string());
    document.captured_on = Some("2026-11-27".to_string());
    document.checkout = Some("stunt-reel".to_string());
    document.sound_samples = Some("stubbed".to_string());
    document.video = Some(VideoFileInfo {
        file: VIDEO_FILE.to_string(),
        sha256: "ab".repeat(32),
        bytes: 1234,
        codec: "zmbv".to_string(),
        frame_rate: [2_190_197, 31_250],
    });
    document.emulator = Some(EmulatorInfo {
        name: "dosbox-automation".to_string(),
        version: "0.85.1".to_string(),
        core: "dynamic".to_string(),
        cpu_cycles: "45000".to_string(),
    });
    document.layout = Some(LayoutOffsets {
        film_clock: "0x421C".to_string(),
        global_tick: "0x1C3E".to_string(),
        working_palette: "0x20EE".to_string(),
        slot_clock: Some("0x4220".to_string()),
        slot_ticks: Some("0x1C62".to_string()),
        inferred: vec!["slot_clock".to_string(), "slot_ticks".to_string()],
    });
    document.film_ticks = Some([7, 9]);
    document
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

#[test]
fn slot_columns_are_optional_and_round_trip() {
    let without = serde_json::to_value(capture()).expect("serialise");
    assert!(without["log"].get("slot_clock").is_none());
    let old: VideoCapture = serde_json::from_value(without).expect("a log without slot columns");
    old.validate().expect("valid");

    let named = with_slots();
    named.validate().expect("valid");
    let back: VideoCapture =
        serde_json::from_value(serde_json::to_value(&named).expect("serialise")).expect("read");
    assert_eq!(back, named);
}

#[test]
fn the_slot_columns_come_together() {
    let mut clock_only = with_slots();
    clock_only.log.slot_ticks = None;
    assert!(reason(clock_only.validate().expect_err("pair")).contains("together"));
    let mut ticks_only = with_slots();
    ticks_only.log.slot_clock = None;
    assert!(reason(ticks_only.validate().expect_err("pair")).contains("together"));
}

#[test]
fn the_slot_columns_match_the_log_length() {
    let mut short = with_slots();
    short.log.slot_ticks.as_mut().expect("ticks").pop();
    assert!(reason(short.validate().expect_err("columns")).contains("slot_ticks"));
}

#[test]
fn the_whole_film_fields_round_trip_and_are_optional() {
    let document = described();
    document.validate().expect("valid");
    let json = serde_json::to_value(&document).expect("serialise");
    assert_eq!(
        json["video"]["frame_rate"],
        serde_json::json!([2_190_197, 31_250])
    );
    assert_eq!(json["film_ticks"], serde_json::json!([7, 9]));
    let back: VideoCapture = serde_json::from_value(json).expect("read");
    assert_eq!(back, document);
}

#[test]
fn the_whole_film_fields_must_agree_with_the_log() {
    let mut rows = described();
    rows.rows = Some(5);
    assert!(reason(rows.validate().expect_err("rows")).contains("rows"));
    let mut changes = described();
    changes.palette_changes = Some(0);
    assert!(reason(changes.validate().expect_err("changes")).contains("palette_changes"));
    let mut ticks = described();
    ticks.film_ticks = Some([7, 10]);
    assert!(reason(ticks.validate().expect_err("ticks")).contains("film_ticks"));
    let mut digest = described();
    digest.video.as_mut().expect("video").sha256 = "AB".repeat(32);
    assert!(reason(digest.validate().expect_err("sha")).contains("sha256"));
    let mut file = described();
    file.video.as_mut().expect("video").file = "other.avi".to_string();
    assert!(reason(file.validate().expect_err("file")).contains("video.file"));
}
