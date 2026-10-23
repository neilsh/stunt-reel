//! Frame-by-frame comparison of two `report.json` documents.

use std::collections::BTreeMap;

use serde_json::{Value, json};

/// Per-frame SSIM change between two reports, matched by `film_tick`.
#[derive(Debug, Clone, Copy, PartialEq)]
pub(super) struct FrameDelta {
    pub(super) film_tick: u64,
    before: f64,
    after: f64,
}

impl FrameDelta {
    fn delta(&self) -> f64 {
        self.after - self.before
    }
}

/// A mean before and after, over the frames present in both reports.
#[derive(Debug, Clone, Copy, PartialEq)]
struct MeanChange {
    before: f64,
    after: f64,
}

/// SSIM changes beyond this magnitude count as a changed frame.
const CHANGED_THRESHOLD: f64 = 0.005;

/// Number of most improved / most regressed frames listed.
const COMPARE_TOP: usize = 5;

/// Which SSIM a comparison used.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum CompareBasis {
    /// `ssim` over frames scored in both reports.
    Scored,
    /// `ssim` over every common frame (a report predates fade scoring).
    All,
}

/// Result of [`compare_reports`].
#[derive(Debug, Clone, PartialEq)]
pub(super) struct Comparison {
    basis: CompareBasis,
    /// Frames (by `film_tick`) present in both reports.
    common: usize,
    before_only: usize,
    after_only: usize,
    ssim: MeanChange,
    iou: MeanChange,
    /// Up to [`COMPARE_TOP`] frames with the largest SSIM gain, best first.
    pub(super) improved: Vec<FrameDelta>,
    /// Up to [`COMPARE_TOP`] frames with the largest SSIM loss, worst first.
    pub(super) regressed: Vec<FrameDelta>,
    /// Common frames whose SSIM rose by more than [`CHANGED_THRESHOLD`].
    improved_count: usize,
    /// Common frames whose SSIM fell by more than [`CHANGED_THRESHOLD`].
    regressed_count: usize,
}

/// Measurements of one report frame.
#[derive(Debug, Clone, Copy)]
struct ReportFrame {
    ssim: f64,
    iou: f64,
    /// Whether the frame reached the fade floor; absent in reports that predate fade
    /// scoring.
    scored: Option<bool>,
}

/// Per-`film_tick` frames of a parsed report.
struct ReportScores {
    frames: BTreeMap<u64, ReportFrame>,
    /// Whether every entry carries `scored`.
    fade_aware: bool,
}

/// Frames of a parsed report keyed by `film_tick`; the first entry wins when a
/// `film_tick` repeats.
fn report_scores(report: &Value) -> Result<ReportScores, String> {
    let per_frame = report
        .get("per_frame")
        .and_then(Value::as_array)
        .ok_or("report has no per_frame array")?;
    let mut scores = BTreeMap::new();
    let mut fade_aware = true;
    for (position, frame) in per_frame.iter().enumerate() {
        let field = |key: &str| {
            frame
                .get(key)
                .and_then(Value::as_f64)
                .ok_or_else(|| format!("per_frame[{position}] has no numeric {key}"))
        };
        let film_tick = frame
            .get("film_tick")
            .and_then(Value::as_u64)
            .ok_or_else(|| format!("per_frame[{position}] has no film_tick"))?;
        let scored = frame.get("scored").and_then(Value::as_bool);
        fade_aware &= scored.is_some();
        scores.entry(film_tick).or_insert(ReportFrame {
            ssim: field("ssim")?,
            iou: field("iou")?,
            scored,
        });
    }
    Ok(ReportScores {
        frames: scores,
        fade_aware,
    })
}

/// Compares two parsed `report.json` values frame by frame, matching on `film_tick`.
///
/// Means cover only the frames present in both reports, so a different matched-frame
/// count (for example an extended render range) cannot masquerade as a change. When both
/// reports carry fade scoring, only frames scored in both are compared; otherwise every
/// common frame. Reports that also carry the retired `ssim_compensated` are read for
/// their raw `ssim`.
pub(super) fn compare_reports(before: &Value, after: &Value) -> Result<Comparison, String> {
    let (before_report, after_report) = (report_scores(before)?, report_scores(after)?);
    let basis = if before_report.fade_aware && after_report.fade_aware {
        CompareBasis::Scored
    } else {
        CompareBasis::All
    };
    // `(ssim, iou)` of the frames the basis counts.
    let counted = |report: &ReportScores| -> BTreeMap<u64, (f64, f64)> {
        report
            .frames
            .iter()
            .filter(|(_, f)| basis == CompareBasis::All || f.scored == Some(true))
            .map(|(tick, f)| (*tick, (f.ssim, f.iou)))
            .collect()
    };
    let before_scores = counted(&before_report);
    let after_scores = counted(&after_report);

    let mut deltas = Vec::new();
    let (mut ssim_before, mut ssim_after) = (0.0, 0.0);
    let (mut iou_before, mut iou_after) = (0.0, 0.0);
    for (film_tick, (b_ssim, b_iou)) in &before_scores {
        let Some((a_ssim, a_iou)) = after_scores.get(film_tick) else {
            continue;
        };
        deltas.push(FrameDelta {
            film_tick: *film_tick,
            before: *b_ssim,
            after: *a_ssim,
        });
        ssim_before += b_ssim;
        ssim_after += a_ssim;
        iou_before += b_iou;
        iou_after += a_iou;
    }
    if deltas.is_empty() {
        return Err(match basis {
            CompareBasis::All => "the reports share no film_tick".to_string(),
            CompareBasis::Scored => "the reports share no film_tick scored in both".to_string(),
        });
    }
    let common = deltas.len();
    let n = common as f64;

    let mut improved: Vec<FrameDelta> =
        deltas.iter().copied().filter(|d| d.delta() > 0.0).collect();
    improved.sort_by(|a, b| {
        b.delta()
            .total_cmp(&a.delta())
            .then(a.film_tick.cmp(&b.film_tick))
    });
    let mut regressed: Vec<FrameDelta> =
        deltas.iter().copied().filter(|d| d.delta() < 0.0).collect();
    regressed.sort_by(|a, b| {
        a.delta()
            .total_cmp(&b.delta())
            .then(a.film_tick.cmp(&b.film_tick))
    });
    let improved_count = deltas
        .iter()
        .filter(|d| d.delta() > CHANGED_THRESHOLD)
        .count();
    let regressed_count = deltas
        .iter()
        .filter(|d| d.delta() < -CHANGED_THRESHOLD)
        .count();
    improved.truncate(COMPARE_TOP);
    regressed.truncate(COMPARE_TOP);

    Ok(Comparison {
        basis,
        common,
        before_only: before_scores.len() - common,
        after_only: after_scores.len() - common,
        ssim: MeanChange {
            before: ssim_before / n,
            after: ssim_after / n,
        },
        iou: MeanChange {
            before: iou_before / n,
            after: iou_after / n,
        },
        improved,
        regressed,
        improved_count,
        regressed_count,
    })
}

impl Comparison {
    /// Human-readable summary printed to stdout.
    pub(super) fn summary(&self) -> String {
        use std::fmt::Write as _;

        let mut out = String::new();
        let (basis, both) = match self.basis {
            CompareBasis::Scored => (
                "SSIM over frames scored in both runs",
                "scored in both reports",
            ),
            CompareBasis::All => (
                "SSIM over all common frames (a report predates fade scoring)",
                "in both reports",
            ),
        };
        let _ = writeln!(out, "[compare] basis: {basis}");
        let _ = writeln!(
            out,
            "[compare] {} frame(s) {both} ({} only in the previous, {} only in this run)",
            self.common, self.before_only, self.after_only
        );
        for (name, mean) in [("SSIM", self.ssim), ("IoU", self.iou)] {
            let _ = writeln!(
                out,
                "[compare] mean {name} {:.3} -> {:.3} ({:+.3})",
                mean.before,
                mean.after,
                mean.after - mean.before
            );
        }
        for (title, list) in [
            ("most improved", &self.improved),
            ("most regressed", &self.regressed),
        ] {
            let _ = writeln!(
                out,
                "[compare] {title} frames (film_tick before -> after, delta):"
            );
            if list.is_empty() {
                let _ = writeln!(out, "[compare]   none");
            }
            for d in list {
                let _ = writeln!(
                    out,
                    "[compare]   tick {:>5}  {:.3} -> {:.3}  {:+.3}",
                    d.film_tick,
                    d.before,
                    d.after,
                    d.delta()
                );
            }
        }
        let unchanged = self.common - self.improved_count - self.regressed_count;
        let _ = write!(
            out,
            "[compare] SSIM changed by more than {CHANGED_THRESHOLD}: {} improved, {} regressed, {unchanged} within +/-{CHANGED_THRESHOLD}",
            self.improved_count, self.regressed_count
        );
        out
    }

    /// The `compare.json` document.
    pub(super) fn to_json(&self) -> Value {
        let deltas = |list: &[FrameDelta]| {
            list.iter()
                .map(|d| {
                    json!({
                        "film_tick": d.film_tick,
                        "before": d.before,
                        "after": d.after,
                        "delta": d.delta(),
                    })
                })
                .collect::<Vec<Value>>()
        };
        let mean = |m: MeanChange| json!({ "before": m.before, "after": m.after, "delta": m.after - m.before });
        json!({
            "basis": match self.basis {
                CompareBasis::Scored => "scored",
                CompareBasis::All => "all",
            },
            "common_frames": self.common,
            "before_only_frames": self.before_only,
            "after_only_frames": self.after_only,
            "changed_threshold": CHANGED_THRESHOLD,
            "mean_ssim": mean(self.ssim),
            "mean_iou": mean(self.iou),
            "improved_count": self.improved_count,
            "regressed_count": self.regressed_count,
            "most_improved": deltas(&self.improved),
            "most_regressed": deltas(&self.regressed),
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn report(frames: &[(u64, f64, f64)]) -> Value {
        json!({
            "per_frame": frames
                .iter()
                .enumerate()
                .map(|(i, (tick, ssim, iou))| json!({
                    "ordinal": i + 1, "film_tick": tick, "ssim": ssim, "iou": iou,
                }))
                .collect::<Vec<Value>>(),
        })
    }

    /// A report whose entries carry the fade-scoring fields:
    /// `(film_tick, ssim, iou, scored)`.
    fn fade_report(frames: &[(u64, f64, f64, bool)]) -> Value {
        json!({
            "per_frame": frames
                .iter()
                .enumerate()
                .map(|(i, (tick, ssim, iou, scored))| json!({
                    "ordinal": i + 1, "film_tick": tick, "ssim": ssim, "iou": iou,
                    "fade_level": 1.0, "scored": scored,
                }))
                .collect::<Vec<Value>>(),
        })
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
        assert!((c.ssim.before - 0.5).abs() < 1e-9);
        assert!((c.ssim.after - 0.7).abs() < 1e-9);
        assert!((c.iou.before - 0.8).abs() < 1e-9);
        assert!((c.iou.after - 0.9).abs() < 1e-9);
        assert_eq!(c.to_json()["basis"], "scored");
        let text = c.summary();
        assert!(
            text.starts_with("[compare] basis: SSIM over frames scored"),
            "{text}"
        );
        // A report from the compensation era is compared on its raw `ssim`.
        let legacy = json!({ "per_frame": [
            { "film_tick": 10, "ssim": 0.4, "iou": 0.8, "ssim_compensated": 0.9, "scored": true },
        ]});
        let c = compare_reports(&legacy, &after).expect("comparable");
        assert_eq!(c.basis, CompareBasis::Scored);
        assert!((c.ssim.before - 0.4).abs() < 1e-9);
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
            assert_eq!(c.to_json()["basis"], "all");
            let text = c.summary();
            assert!(
                text.starts_with("[compare] basis: SSIM over all common"),
                "{text}"
            );
            assert!(text.contains("2 frame(s) in both reports"), "{text}");
        }
        let c = compare_reports(&old, &new).unwrap();
        assert!((c.ssim.before - 0.55).abs() < 1e-9);
        assert!((c.ssim.after - 0.75).abs() < 1e-9);
        // A report with `scored` on only some entries is old-style too.
        let partial = json!({ "per_frame": [
            { "film_tick": 10, "ssim": 0.5, "iou": 0.5, "scored": true },
            { "film_tick": 20, "ssim": 0.5, "iou": 0.5 },
        ]});
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
        assert!((c.ssim.before - 0.55).abs() < 1e-9);
        assert!((c.ssim.after - 0.556).abs() < 1e-9);
        assert!((c.iou.before - 0.80).abs() < 1e-9);
        assert!((c.iou.after - 0.90).abs() < 1e-9);
        // Tick 40 moved by only +0.004: listed as improved, but under the 0.005 count.
        let ticks = |list: &[FrameDelta]| list.iter().map(|d| d.film_tick).collect::<Vec<_>>();
        assert_eq!(ticks(&c.improved), vec![20, 40]);
        assert_eq!(ticks(&c.regressed), vec![30]);
        assert_eq!((c.improved_count, c.regressed_count), (1, 1));
        assert!((c.regressed[0].delta() + 0.08).abs() < 1e-9);
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
                .contains("share no film_tick")
        );
        let legacy = json!({ "per_frame": [{ "ordinal": 1, "ssim": 0.5, "iou": 0.5 }] });
        assert!(
            compare_reports(&legacy, &a)
                .unwrap_err()
                .contains("film_tick")
        );
        assert!(
            compare_reports(&json!({}), &a)
                .unwrap_err()
                .contains("per_frame")
        );
    }

    #[test]
    fn compare_json_and_summary_carry_the_same_figures() {
        let before = report(&[(7, 0.5, 0.8), (9, 0.6, 0.8)]);
        let after = report(&[(7, 0.4, 0.8), (9, 0.7, 0.8)]);
        let c = compare_reports(&before, &after).expect("comparable");
        let doc = c.to_json();
        assert_eq!(doc["common_frames"], 2);
        assert_eq!(doc["regressed_count"], 1);
        assert_eq!(doc["most_regressed"][0]["film_tick"], 7);
        assert!((doc["most_improved"][0]["delta"].as_f64().unwrap() - 0.1).abs() < 1e-9);
        let text = c.summary();
        assert!(
            text.contains("tick     7  0.500 -> 0.400  -0.100"),
            "{text}"
        );
        assert!(text.contains("1 improved, 1 regressed, 0 within"), "{text}");
    }
}
