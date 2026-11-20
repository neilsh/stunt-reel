use stunt_parity::*;

fn frame() -> FrameReport {
    FrameReport {
        ordinal: 1,
        film_tick: 9,
        ssim: 0.7,
        iou: 0.9,
        index_agreement: Some(0.5),
        loss_by_class: None,
        fade_level: Some(1.0),
        authored_fade_level: Some(1.0),
        scored: Some(true),
    }
}

fn report() -> Report {
    Report {
        reference_frames: 2,
        frames: 2,
        unmatched: 0,
        sky_indices: [227, 238],
        mean_ssim: 0.7,
        min_ssim: 0.7,
        mean_iou: 0.9,
        min_fade_level: 0.25,
        mean_ssim_scored: Some(0.7),
        i6_gate: I6Gate::default(),
        mean_iou_scored: Some(0.9),
        mean_index_agreement_scored: Some(0.5),
        mean_loss_by_class_scored: None,
        mean_loss_by_shape_scored: None,
        scored_frames: 2,
        excluded_frames: 0,
        credits_missing_frames: 0,
        adapter: None,
        archive_conflict_waived: false,
        crates: None,
        sha256: Some("a".repeat(64)),
        all_sha256: Some("b".repeat(64)),
        per_frame: vec![frame(), frame()],
    }
}

#[test]
fn credits_missing_frames_defaults_to_zero_and_is_bounded_by_frames() {
    let mut doc = serde_json::to_value(report()).expect("serialise");
    doc.as_object_mut()
        .expect("object")
        .remove("credits_missing_frames");
    let old: Report = serde_json::from_value(doc).expect("a report without the field");
    assert_eq!(old.credits_missing_frames, 0);
    let mut over = report();
    over.credits_missing_frames = 3;
    assert!(over.validate().is_err());
}

#[test]
fn consistent_report_passes_and_round_trips() {
    let report = report();
    report.validate().expect("consistent");
    let text = serde_json::to_string(&report).expect("serialize");
    let back: Report = serde_json::from_str(&text).expect("deserialize");
    assert_eq!(back, report);
}

#[test]
fn identities_are_checked() {
    let mut broken = report();
    broken.frames = 1;
    assert!(matches!(
        broken.validate(),
        Err(ArtifactError::ReportInconsistent { .. })
    ));

    let mut unscored = report();
    unscored.scored_frames = 0;
    unscored.excluded_frames = 2;
    assert!(matches!(
        unscored.validate(),
        Err(ArtifactError::ReportInconsistent { .. })
    ));
}

#[test]
fn old_reports_without_optional_fields_parse() {
    let text = r#"{"per_frame":[{"film_tick":9,"ssim":0.7,"iou":0.9}]}"#;
    let report: Report = serde_json::from_str(text).expect("legacy report");
    assert_eq!(report.per_frame.len(), 1);
    assert_eq!(report.per_frame[0].scored, None);
    assert_eq!(report.adapter, None);
    assert_eq!(report.crates, None);
    assert_eq!(report.sha256, None);
    assert_eq!(report.all_sha256, None);
}
