//! End-to-end `run` tests over synthetic captures and renders, and in-memory `build_report` tests.

use std::fs;

use serde_json::json;

use super::loss::LOSS_CLASSES;
use super::score::FrameMetrics;
use super::test_support::{
    TempDir, read_report, run_parity, write_reference, write_reference_faded, write_render,
    write_render_with_brightness,
};

#[test]
fn a_render_without_planes_is_an_error_that_says_to_re_render() {
    let tmp = TempDir::new("no_planes");
    write_reference(&tmp.join("ref"), &[12], true);
    let test = tmp.join("test");
    fs::create_dir_all(&test).unwrap();
    let png = test.join(crate::headless::tick_png_name(12));
    write_render(&png);
    fs::remove_file(png.with_extension("layer")).unwrap();
    let error = run_parity(&tmp.join("ref"), &test, &tmp.join("out")).unwrap_err();
    assert!(error.contains("re-render"), "{error}");
}

#[test]
fn faded_frames_below_the_floor_are_reported_but_not_scored() {
    let tmp = TempDir::new("faded");
    write_reference_faded(&tmp.join("ref"), &[7, 12, 20], true, &[1.0, 0.5, 0.1]);
    let test = tmp.join("test");
    fs::create_dir_all(&test).unwrap();
    for (tick, brightness) in [(7, 0x8000u16), (12, 0x4000), (20, 0x0800)] {
        write_render_with_brightness(&test.join(crate::headless::tick_png_name(tick)), brightness);
    }

    run_parity(&tmp.join("ref"), &test, &tmp.join("out")).expect("parity runs");
    let report = read_report(&tmp.join("out"));
    assert_eq!(report["scored_frames"], 2);
    assert_eq!(report["excluded_frames"], 1);
    assert_eq!(report["min_fade_level"], 0.25);
    // The 0.5 frame is scored against an unfaded render, so the scored mean misses 0.88.
    assert_eq!(
        report["i6_gate"],
        json!({ "initial": false, "sign_off": false })
    );
    let per_frame = report["per_frame"].as_array().unwrap();
    let scored: Vec<bool> = per_frame
        .iter()
        .map(|f| f["scored"].as_bool().unwrap())
        .collect();
    assert_eq!(scored, vec![true, true, false]);
    let level = |n: usize| per_frame[n]["fade_level"].as_f64().unwrap();
    assert!((level(0) - 1.0).abs() < 0.02);
    assert!((level(1) - 0.5).abs() < 0.02);
    assert!((level(2) - 0.1).abs() < 0.02);
    // `mean_ssim` spans all matched frames; `mean_ssim_scored` only the first two.
    let mean_scored =
        (per_frame[0]["ssim"].as_f64().unwrap() + per_frame[1]["ssim"].as_f64().unwrap()) / 2.0;
    assert!((report["mean_ssim_scored"].as_f64().unwrap() - mean_scored).abs() < 1e-5);
    assert!(report.get("mean_ssim_compensated").is_none());
    let mean_raw = per_frame
        .iter()
        .map(|f| f["ssim"].as_f64().unwrap())
        .sum::<f64>()
        / 3.0;
    assert!((report["mean_ssim"].as_f64().unwrap() - mean_raw).abs() < 1e-5);
    assert!(tmp.join("out").join("contact_0001.png").is_file());
}

#[test]
fn no_scored_frame_reports_null_scored_means() {
    let tmp = TempDir::new("none_scored");
    write_reference_faded(&tmp.join("ref"), &[7], true, &[0.1]);
    let test = tmp.join("test");
    fs::create_dir_all(&test).unwrap();
    write_render_with_brightness(&test.join(crate::headless::tick_png_name(7)), 0x0800);

    run_parity(&tmp.join("ref"), &test, &tmp.join("out")).expect("parity runs");
    let report = read_report(&tmp.join("out"));
    assert_eq!(report["scored_frames"], 0);
    assert_eq!(report["excluded_frames"], 1);
    assert!(report["mean_ssim_scored"].is_null());
    assert!(report["mean_iou_scored"].is_null());
    assert_eq!(
        report["i6_gate"],
        json!({ "initial": false, "sign_off": false })
    );
    assert_eq!(report["per_frame"][0]["scored"], false);
}

#[test]
fn meta_without_film_tick_is_rejected() {
    let tmp = TempDir::new("untagged");
    write_reference(&tmp.join("ref"), &[7, 12], false);
    fs::create_dir_all(tmp.join("test")).unwrap();
    write_render(&tmp.join("test").join("tick_00007.png"));

    let error = run_parity(&tmp.join("ref"), &tmp.join("test"), &tmp.join("out"))
        .expect_err("untagged capture must be rejected");
    assert!(error.contains("film_tick"), "{error}");
    assert!(error.contains("predates film-clock tagging"), "{error}");
    assert!(error.contains("recaptured"), "{error}");
}

#[test]
fn frames_match_renders_by_film_tick() {
    let tmp = TempDir::new("matched");
    write_reference(&tmp.join("ref"), &[7, 12], true);
    let test = tmp.join("test");
    fs::create_dir_all(&test).unwrap();
    write_render(&test.join(crate::headless::tick_png_name(7)));
    write_render(&test.join(crate::headless::tick_png_name(12)));
    // Neighbouring ticks and the old ordinal names must never be picked up.
    write_render(&test.join("tick_00001.png"));
    write_render(&test.join("frame_0001.png"));

    run_parity(&tmp.join("ref"), &test, &tmp.join("out")).expect("parity runs");
    let report = read_report(&tmp.join("out"));
    assert_eq!(report["frames"], 2);
    assert_eq!(report["unmatched"], 0);
    assert!(report.get("tick_to_frame_offset").is_none());
    assert_eq!(report["sky_indices"], json!([227, 238]));
    assert!(report.get("sky_index").is_none() && report.get("clear_index").is_none());
    let per_frame = report["per_frame"].as_array().unwrap();
    let ticks: Vec<u64> = per_frame
        .iter()
        .map(|f| f["film_tick"].as_u64().unwrap())
        .collect();
    let ordinals: Vec<u64> = per_frame
        .iter()
        .map(|f| f["ordinal"].as_u64().unwrap())
        .collect();
    assert_eq!(ticks, vec![7, 12]);
    assert_eq!(ordinals, vec![1, 2]);
}

#[test]
fn missing_render_for_a_film_tick_is_unmatched() {
    let tmp = TempDir::new("unmatched");
    write_reference(&tmp.join("ref"), &[7, 12], true);
    let test = tmp.join("test");
    fs::create_dir_all(&test).unwrap();
    // Only the render for the first capture's film tick exists; the old ordinal
    // names (`frame_0002.png`, `tick_00002.png`) must not satisfy the second.
    write_render(&test.join("tick_00007.png"));
    write_render(&test.join("tick_00002.png"));
    write_render(&test.join("frame_0002.png"));

    run_parity(&tmp.join("ref"), &test, &tmp.join("out")).expect("parity runs");
    let report = read_report(&tmp.join("out"));
    assert_eq!(report["frames"], 1);
    assert_eq!(report["unmatched"], 1);
    assert_eq!(report["per_frame"][0]["film_tick"], 7);
}

#[test]
fn the_i6_gate_passes_each_threshold_independently() {
    let gate = |ssim| {
        let g = super::i6_gate(ssim);
        (g.initial, g.sign_off)
    };
    assert_eq!(gate(Some(0.95)), (true, true));
    assert_eq!(gate(Some(0.89)), (true, false));
    assert_eq!(gate(Some(0.5)), (false, false));
    assert_eq!(gate(None), (false, false));
}

/// A matched frame with the given SSIM, IoU and scored flag; the other measurements are
/// derived so each frame's loss array sums to `1 - ssim`.
fn row(ordinal: usize, ssim: f32, iou: f32, scored: bool) -> super::FrameRow {
    let mut loss_by_class = [0.0; LOSS_CLASSES.len()];
    loss_by_class[0] = 1.0 - ssim;
    super::FrameRow {
        ordinal,
        film_tick: ordinal * 10,
        metrics: FrameMetrics {
            ssim,
            fade_level: if scored { 1.0 } else { 0.1 },
            authored_fade_level: None,
            scored,
            iou,
            index_agreement: ssim / 2.0,
            loss_by_class,
        },
    }
}

fn assert_close(actual: Option<f32>, expected: f32) {
    let actual = actual.expect("a mean over scored frames");
    assert!((actual - expected).abs() < 1e-6, "{actual} != {expected}");
}

#[test]
fn build_report_over_all_scored_frames_has_equal_overall_and_scored_means() {
    let rows = [row(1, 0.9, 0.8, true), row(2, 0.7, 0.6, true)];
    let report = super::build_report(5, &rows, 3, 0.25);

    assert_eq!(report.reference_frames, 5);
    assert_eq!(report.frames, 2);
    assert_eq!(report.unmatched, 3);
    assert_eq!(report.min_fade_level, 0.25);
    assert_eq!(report.scored_frames, 2);
    assert_eq!(report.excluded_frames, 0);
    assert!((report.mean_ssim - 0.8).abs() < 1e-6);
    assert!((report.min_ssim - 0.7).abs() < 1e-6);
    assert!((report.mean_iou - 0.7).abs() < 1e-6);
    assert_close(report.mean_ssim_scored, report.mean_ssim);
    assert_close(report.mean_iou_scored, report.mean_iou);
    assert_close(report.mean_index_agreement_scored, 0.4);
    let loss = report.mean_loss_by_class_scored.expect("class losses");
    assert_eq!(loss.len(), LOSS_CLASSES.len());
    assert!((loss[LOSS_CLASSES[0]] - 0.2).abs() < 1e-6);
    assert_eq!(report.per_frame.len(), 2);
    assert_eq!(report.per_frame[1].ordinal, 2);
    assert_eq!(report.per_frame[1].film_tick, 20);
    assert_eq!(report.per_frame[1].scored, Some(true));
}

#[test]
fn build_report_excludes_frames_below_the_fade_floor_from_scored_means() {
    let rows = [
        row(1, 0.9, 0.8, true),
        row(2, 0.7, 0.6, true),
        row(3, 0.1, 0.2, false),
    ];
    let report = super::build_report(3, &rows, 0, 0.25);

    assert_eq!(report.frames, 3);
    assert_eq!(report.scored_frames, 2);
    assert_eq!(report.excluded_frames, 1);
    // Overall means span every matched frame; the minimum is the excluded frame's.
    assert!((report.mean_ssim - 1.7 / 3.0).abs() < 1e-6);
    assert!((report.min_ssim - 0.1).abs() < 1e-6);
    assert!((report.mean_iou - 1.6 / 3.0).abs() < 1e-6);
    // Scored means skip it.
    assert_close(report.mean_ssim_scored, 0.8);
    assert_close(report.mean_iou_scored, 0.7);
    assert_close(report.mean_index_agreement_scored, 0.4);
    let loss = report.mean_loss_by_class_scored.expect("class losses");
    assert!((loss[LOSS_CLASSES[0]] - 0.2).abs() < 1e-6);
    // The per-frame list keeps the excluded frame, flagged unscored.
    let scored: Vec<_> = report.per_frame.iter().map(|f| f.scored).collect();
    assert_eq!(scored, vec![Some(true), Some(true), Some(false)]);
    assert_eq!(report.per_frame[2].fade_level, Some(0.1));
}

#[test]
fn build_report_with_no_scored_frame_has_no_scored_means() {
    let rows = [row(1, 0.4, 0.5, false), row(2, 0.2, 0.3, false)];
    let report = super::build_report(2, &rows, 0, 0.25);

    assert_eq!(report.scored_frames, 0);
    assert_eq!(report.excluded_frames, 2);
    assert!((report.mean_ssim - 0.3).abs() < 1e-6);
    assert!(report.mean_ssim_scored.is_none());
    assert!(report.mean_iou_scored.is_none());
    assert!(report.mean_index_agreement_scored.is_none());
    assert!(report.mean_loss_by_class_scored.is_none());
    assert_eq!(report.per_frame.len(), 2);
}

#[test]
fn build_report_gate_follows_the_scored_mean_not_the_overall_mean() {
    // The excluded frame drags the overall mean to 0.64, below both thresholds, but the
    // scored mean of 0.91 reaches both.
    let rows = [
        row(1, 0.92, 0.9, true),
        row(2, 0.90, 0.9, true),
        row(3, 0.10, 0.1, false),
    ];
    let report = super::build_report(3, &rows, 0, 0.25);
    assert!(report.mean_ssim < 0.88);
    assert_close(report.mean_ssim_scored, 0.91);
    assert_eq!(report.i6_gate, super::i6_gate(report.mean_ssim_scored));
    assert!(report.i6_gate.initial && report.i6_gate.sign_off);

    // A scored mean of 0.89 reaches only the initial threshold.
    let rows = [row(1, 0.89, 0.9, true), row(2, 0.1, 0.1, false)];
    let gate = super::build_report(2, &rows, 0, 0.25).i6_gate;
    assert!(gate.initial && !gate.sign_off);

    // No scored frame fails both.
    let gate = super::build_report(1, &[row(1, 0.99, 0.9, false)], 0, 0.25).i6_gate;
    assert!(!gate.initial && !gate.sign_off);
}
