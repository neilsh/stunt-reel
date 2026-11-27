use stunt_parity::*;

fn capture() -> CaptureSet {
    CaptureSet {
        schema_version: SCHEMA_VERSION,
        film: FilmId::default(),
        geometry: Geometry {
            width: 320,
            height: 200,
            viewport_rows: None,
        },
        frames: vec![CapturedFrame {
            ordinal: 1,
            film_tick: 9,
            slot_clock: Some(9),
            slot_ticks: Some(1),
            frame_file: "tick_0001.idx".to_string(),
            palette_file: "palettes_0001.json".to_string(),
        }],
    }
}

#[test]
fn a_current_capture_round_trips_through_the_flat_document() {
    let text = serde_json::to_string(&capture()).expect("serialize");
    let value: serde_json::Value = serde_json::from_str(&text).expect("value");
    assert_eq!(value["schema_version"], SCHEMA_VERSION);
    assert_eq!(value["width"], 320);
    assert_eq!(value["frames"][0]["ordinal"], 1);
    let back: CaptureSet = serde_json::from_str(&text).expect("deserialize");
    assert_eq!(back, capture());
}

#[test]
fn a_legacy_capture_reads_as_version_one_with_default_names_and_geometry() {
    let set: CaptureSet = serde_json::from_str(
        r#"{
            "film": "CTRY.FLM",
            "flm_bytes": 100,
            "frames": [
                {"ordinal": 1, "film_tick": 9},
                {"film_tick": 10, "frame_file": "other.idx"}
            ]
        }"#,
    )
    .expect("legacy capture");
    assert_eq!(set.schema_version, SCHEMA_VERSION);
    assert_eq!(set.geometry.width, 320);
    assert_eq!(set.geometry.height, 200);
    assert_eq!(set.frames[0].ordinal, 1);
    assert_eq!(set.frames[0].frame_file, "tick_0001.idx");
    assert_eq!(set.frames[0].palette_file, "palettes_0001.json");
    assert_eq!(set.frames[1].ordinal, 2);
    assert_eq!(set.frames[1].frame_file, "other.idx");
    assert_eq!(set.frames[1].palette_file, "palettes_0002.json");
    set.validate().expect("legacy capture");
}

#[test]
fn a_capture_with_a_viewport_is_refused() {
    let mut set = capture();
    set.geometry.viewport_rows = Some(185);
    assert!(matches!(
        set.validate(),
        Err(ArtifactError::Geometry { .. })
    ));
    serde_json::to_string(&set).unwrap_err();
}

#[test]
fn a_future_version_is_rejected() {
    let mut future = capture();
    future.schema_version = 9;
    assert!(matches!(
        future.validate(),
        Err(ArtifactError::UnsupportedVersion { found: 9, .. })
    ));
}

#[test]
fn frames_must_name_a_basename() {
    let mut set = capture();
    set.frames[0].frame_file = "../tick_0001.idx".to_string();
    assert!(matches!(set.validate(), Err(ArtifactError::Frame { .. })));

    let mut set = capture();
    set.frames[0].palette_file = "palettes/0001.json".to_string();
    assert!(matches!(set.validate(), Err(ArtifactError::Frame { .. })));

    for bad in [
        "frames/",
        "frames/../tick_0001.idx",
        "frames/frames/tick_0001.idx",
    ] {
        let mut set = capture();
        set.frames[0].frame_file = bad.to_string();
        assert!(
            matches!(set.validate(), Err(ArtifactError::Frame { .. })),
            "{bad}"
        );
    }
}

#[test]
fn a_frame_may_sit_under_the_frames_directory() {
    let mut set = capture();
    set.frames[0].frame_file = "frames/tick_0001.idx".to_string();
    set.frames[0].palette_file = "frames/palettes_0001.json".to_string();
    set.validate().unwrap();
}

#[test]
fn a_frame_without_a_film_tick_names_its_ordinal() {
    let error = serde_json::from_str::<CaptureSet>(r#"{"frames": [{"film_tick": 1}, {}]}"#)
        .expect_err("untagged frame");
    assert!(
        error.to_string().contains("frame 2 has no film_tick"),
        "{error}"
    );
}

#[test]
fn a_page_is_scored_at_the_state_before_the_slot_pass_that_drew_it() {
    let frame = |slot_clock, slot_ticks| CapturedFrame {
        slot_clock,
        slot_ticks,
        ..capture().frames[0].clone()
    };
    // Tag 9, clock 9, one tick since the last pass: the state at 8, stored at tick 9.
    assert_eq!(frame(Some(9), Some(1)).render_tick(), 9);
    // Two passes in one tick: the pass before is at the same clock.
    assert_eq!(frame(Some(9), Some(0)).render_tick(), 10);
    // A skipped tick: the page is two states old.
    assert_eq!(frame(Some(9), Some(2)).render_tick(), 8);
    // An older capture, or a ticks word larger than the clock, scores at its tag.
    assert_eq!(frame(None, None).render_tick(), 9);
    assert_eq!(frame(Some(9), None).render_tick(), 9);
    assert_eq!(frame(Some(1), Some(2)).render_tick(), 9);
    // The largest clock with no ticks cannot add its one: the tag stands.
    assert_eq!(frame(Some(u32::MAX), Some(0)).render_tick(), 9);
}

#[test]
fn the_clock_words_are_optional_in_the_document() {
    let set: CaptureSet = serde_json::from_str(
        r#"{"film": "CTRY.FLM", "flm_bytes": 1, "frames": [{"film_tick": 9}]}"#,
    )
    .expect("older document");
    assert_eq!(set.frames[0].slot_clock, None);
    let text = serde_json::to_string(&set).expect("serialize");
    assert!(!text.contains("slot_clock"), "{text}");
}
