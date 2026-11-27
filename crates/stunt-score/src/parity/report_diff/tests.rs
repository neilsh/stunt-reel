use super::*;
use serde_json::{Value, json};

/// Parses a report document, as `--compare` does.
fn parse(doc: Value) -> Result<Report, serde_json::Error> {
    serde_json::from_value(doc)
}

fn report(frames: &[(u64, f64, f64)]) -> Report {
    parse(json!({
        "per_frame": frames
            .iter()
            .enumerate()
            .map(|(i, (tick, ssim, iou))| json!({
                "ordinal": i + 1, "film_tick": tick, "ssim": ssim, "iou": iou,
            }))
            .collect::<Vec<Value>>(),
    }))
    .unwrap()
}

/// A report whose entries carry the fade-scoring fields:
/// `(film_tick, ssim, iou, scored)`.
fn fade_report(frames: &[(u64, f64, f64, bool)]) -> Report {
    parse(json!({
        "per_frame": frames
            .iter()
            .enumerate()
            .map(|(i, (tick, ssim, iou, scored))| json!({
                "ordinal": i + 1, "film_tick": tick, "ssim": ssim, "iou": iou,
                "fade_level": 1.0, "scored": scored,
            }))
            .collect::<Vec<Value>>(),
    }))
    .unwrap()
}

#[test]
fn compare_uses_ssim_over_frames_scored_in_both() {
    let before = fade_report(&[
        (10, 0.5, 0.8, true),
        (20, 0.6, 0.8, true),
        (30, 0.9, 0.8, false),
    ]);
    let after = fade_report(&[
        (10, 0.7, 0.9, true),
        (20, 0.1, 0.9, false),
        (30, 0.9, 0.9, true),
        (40, 0.5, 0.9, true),
    ]);
    let c = compare_reports(&before, &after).expect("comparable");
    assert_eq!(c.basis, CompareBasis::Scored);
    // Only tick 10 is scored in both; 20 and 30 are scored on one side only.
    assert_eq!((c.common, c.before_only, c.after_only), (1, 1, 2));
    assert!((c.ssim.before - 0.5).abs() < 1e-6);
    assert!((c.ssim.after - 0.7).abs() < 1e-6);
    assert!((c.iou.before - 0.8).abs() < 1e-6);
    assert!((c.iou.after - 0.9).abs() < 1e-6);
    assert_eq!(
        serde_json::to_value(c.document(None)).unwrap()["basis"],
        "scored"
    );
    let text = c.summary();
    assert!(
        text.starts_with("[compare] basis: SSIM over frames scored"),
        "{text}"
    );
    // A report from the compensation era is compared on its raw `ssim`.
    let legacy = parse(json!({ "per_frame": [
        { "film_tick": 10, "ssim": 0.4, "iou": 0.8, "ssim_compensated": 0.9, "scored": true },
    ]}))
    .unwrap();
    let c = compare_reports(&legacy, &after).expect("comparable");
    assert_eq!(c.basis, CompareBasis::Scored);
    assert!((c.ssim.before - 0.4).abs() < 1e-6);
    assert!(text.contains("1 frame(s) scored in both reports"), "{text}");
}

#[test]
fn compare_falls_back_to_all_frames_when_a_report_predates_fade_scoring() {
    let old = report(&[(10, 0.5, 0.8), (20, 0.6, 0.8)]);
    let new = fade_report(&[(10, 0.7, 0.9, true), (20, 0.8, 0.9, false)]);
    for (before, after) in [(&old, &new), (&new, &old)] {
        let c = compare_reports(before, after).expect("comparable");
        assert_eq!(c.basis, CompareBasis::All);
        assert_eq!(c.common, 2);
        assert_eq!(
            serde_json::to_value(c.document(None)).unwrap()["basis"],
            "all"
        );
        let text = c.summary();
        assert!(
            text.starts_with("[compare] basis: SSIM over all common"),
            "{text}"
        );
        assert!(text.contains("2 frame(s) in both reports"), "{text}");
    }
    let c = compare_reports(&old, &new).unwrap();
    assert!((c.ssim.before - 0.55).abs() < 1e-6);
    assert!((c.ssim.after - 0.75).abs() < 1e-6);
    // A report with `scored` on only some entries is old-style too.
    let partial = parse(json!({ "per_frame": [
        { "film_tick": 10, "ssim": 0.5, "iou": 0.5, "scored": true },
        { "film_tick": 20, "ssim": 0.5, "iou": 0.5 },
    ]}))
    .unwrap();
    assert_eq!(
        compare_reports(&partial, &new).unwrap().basis,
        CompareBasis::All
    );
}

#[test]
fn compare_matches_by_film_tick_and_averages_the_common_frames() {
    // Ticks 10..=40 are common; 5 exists only before, 50 only after. The ordinals
    // differ between the reports, so only film_tick may be used to pair frames.
    let before = report(&[
        (5, 0.9, 0.9),
        (10, 0.50, 0.80),
        (20, 0.60, 0.80),
        (30, 0.70, 0.80),
        (40, 0.40, 0.80),
    ]);
    let after = report(&[
        (10, 0.50, 0.90),
        (20, 0.70, 0.90),
        (30, 0.62, 0.90),
        (40, 0.404, 0.90),
        (50, 0.1, 0.1),
    ]);
    let c = compare_reports(&before, &after).expect("comparable");
    assert_eq!((c.common, c.before_only, c.after_only), (4, 1, 1));
    assert!((c.ssim.before - 0.55).abs() < 1e-6);
    assert!((c.ssim.after - 0.556).abs() < 1e-6);
    assert!((c.iou.before - 0.80).abs() < 1e-6);
    assert!((c.iou.after - 0.90).abs() < 1e-6);
    // Tick 40 moved by only +0.004: listed as improved, but under the 0.005 count.
    let ticks = |list: &[FrameDelta]| list.iter().map(|d| d.film_tick).collect::<Vec<_>>();
    assert_eq!(ticks(&c.improved), vec![20, 40]);
    assert_eq!(ticks(&c.regressed), vec![30]);
    assert_eq!((c.improved_count, c.regressed_count), (1, 1));
    assert!((c.regressed[0].delta() + 0.08).abs() < 1e-6);
}

#[test]
fn compare_lists_at_most_five_frames_worst_and_best_first() {
    let before: Vec<(u64, f64, f64)> = (0..12).map(|t| (t, 0.5, 0.5)).collect();
    // Even ticks regress by t/100, odd ticks improve by t/100.
    let after: Vec<(u64, f64, f64)> = (0..12)
        .map(|t| {
            let step = t as f64 / 100.0;
            (t, if t % 2 == 0 { 0.5 - step } else { 0.5 + step }, 0.5)
        })
        .collect();
    let c = compare_reports(&report(&before), &report(&after)).expect("comparable");
    let ticks = |list: &[FrameDelta]| list.iter().map(|d| d.film_tick).collect::<Vec<_>>();
    assert_eq!(ticks(&c.improved), vec![11, 9, 7, 5, 3]);
    assert_eq!(ticks(&c.regressed), vec![10, 8, 6, 4, 2]);
    // Odd ticks 1..=11 and even ticks 2..=10 all move by more than 0.005.
    assert_eq!(c.improved_count, 6);
    assert_eq!(c.regressed_count, 5);
}

#[test]
fn compare_of_identical_reports_has_no_movers() {
    let r = report(&[(1, 0.5, 0.7), (2, 0.6, 0.8)]);
    let c = compare_reports(&r, &r).expect("comparable");
    assert!(c.improved.is_empty() && c.regressed.is_empty());
    assert_eq!((c.improved_count, c.regressed_count), (0, 0));
    assert_eq!(c.ssim.before, c.ssim.after);
    let text = c.summary();
    assert!(text.contains("2 frame(s) in both reports"), "{text}");
    assert!(text.contains("mean SSIM 0.550 -> 0.550 (+0.000)"), "{text}");
    assert!(text.contains("none"), "{text}");
}

#[test]
fn compare_rejects_disjoint_or_malformed_reports() {
    let a = report(&[(1, 0.5, 0.5)]);
    let b = report(&[(2, 0.5, 0.5)]);
    assert!(
        compare_reports(&a, &b)
            .unwrap_err()
            .to_string()
            .contains("share no film_tick")
    );
    // Malformed reports are rejected when parsed, naming the missing field.
    let missing_tick = parse(json!({ "per_frame": [{ "ordinal": 1, "ssim": 0.5, "iou": 0.5 }] }));
    assert!(missing_tick.unwrap_err().to_string().contains("film_tick"));
    let missing_frames = parse(json!({}));
    assert!(
        missing_frames
            .unwrap_err()
            .to_string()
            .contains("per_frame")
    );
}

#[test]
fn compare_json_and_summary_carry_the_same_figures() {
    let before = report(&[(7, 0.5, 0.8), (9, 0.6, 0.8)]);
    let after = report(&[(7, 0.4, 0.8), (9, 0.7, 0.8)]);
    let c = compare_reports(&before, &after).expect("comparable");
    let doc = serde_json::to_value(c.document(None)).unwrap();
    assert_eq!(doc["common_frames"], 2);
    assert_eq!(doc["regressed_count"], 1);
    assert_eq!(doc["most_regressed"][0]["film_tick"], 7);
    assert!((doc["most_improved"][0]["delta"].as_f64().unwrap() - 0.1).abs() < 1e-6);
    let text = c.summary();
    assert!(
        text.contains("tick     7  0.500 -> 0.400  -0.100"),
        "{text}"
    );
    assert!(text.contains("1 improved, 1 regressed, 0 within"), "{text}");
}
