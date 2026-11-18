//! Frame-by-frame comparison of two `report.json` documents.

use std::collections::BTreeMap;

use serde_json::{Value, json};

use super::report::Report;

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

/// Per-`film_tick` frames of a report.
struct ReportScores {
    frames: BTreeMap<u64, ReportFrame>,
    /// Whether every entry carries `scored`.
    fade_aware: bool,
}

/// Frames of a report keyed by `film_tick`; the first entry wins when a `film_tick`
/// repeats.
fn report_scores(report: &Report) -> ReportScores {
    let mut scores = BTreeMap::new();
    for frame in &report.per_frame {
        scores
            .entry(frame.film_tick)
            .or_insert_with(|| ReportFrame {
                ssim: f64::from(frame.ssim),
                iou: f64::from(frame.iou),
                scored: frame.scored,
            });
    }
    ReportScores {
        frames: scores,
        fade_aware: report.per_frame.iter().all(|f| f.scored.is_some()),
    }
}

/// Compares two `report.json` documents frame by frame, matching on `film_tick`.
///
/// Means cover only the frames present in both reports, so a different matched-frame
/// count (for example an extended render range) cannot masquerade as a change. When both
/// reports carry fade scoring, only frames scored in both are compared; otherwise every
/// common frame. Reports that also carry the retired `ssim_compensated` are read for
/// their raw `ssim`.
pub(super) fn compare_reports(before: &Report, after: &Report) -> Result<Comparison, String> {
    let (before_report, after_report) = (report_scores(before), report_scores(after));
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
mod tests;
