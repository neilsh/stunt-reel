//! Visual parity comparator: `PLAYONE.EXE` Mode 13h captures against rendered frames.
//!
//! Reference frames are palette-index planes (`tick_NNNN.idx` + `palettes_NNNN.json`,
//! numbered by capture order) dumped from the emulator's scanned-out page. Each frame's
//! `meta.json` entry carries `film_tick`, the film clock read when it was captured.
//! Rendered frames come from the render store `stuntreel --out-dir` writes, keyed by the
//! 0-based 50 Hz tick they show, so a capture is compared against the render at the
//! same `film_tick`. Captures that predate film-clock tagging are rejected.
//!
//! Each matched pair is scored by [`score::score_frame`]. Scores follow Invariant `[I6]`:
//! both sides are reduced to Rec. 601 luminance, stretched from 320x200 to the 320x240
//! physical 4:3 raster, and compared window by window with the shared
//! `compute_window_scores` evaluator, whose windows the gate averages itself so the same
//! windows also attribute the loss by class.
//! `IoU` compares each side's non-sky mask, which measures framing agreement independently
//! of shading. A capture's sky is every
//! pixel in the sky bands ([`mask::CAPTURE_SKY_INDICES`]), not one modal index.
//!
//! The original fades its palette with the film's brightness variable, and so does the
//! render. Each capture's fade level (see [`fade::fade_level`]) is measured from its captured
//! palette; frames whose level falls below `--min-fade-level` are reported but not
//! scored, because SSIM of near-black frames says little. The floor is applied to the film's
//! authored brightness (var 14) from `render.json` instead, with the measured level kept in the
//! report as a cross-check. The headline is raw SSIM over the scored frames.
//!
//! A render's picture is `palette[index]` over its stored index plane, and `IoU` and loss
//! attribution read its coverage from the stored layer plane, never from its colours
//! (`crate::render_store`, ADR 0027).
//!
//! `--compare <report.json>` additionally matches the fresh scores against a previous
//! run by `film_tick` (see [`report_diff::compare_reports`]), so a change is judged frame by frame
//! rather than only by the means.

mod args;
mod compare;
mod fade;
mod frames;
mod loss;
mod mask;
mod matched;
mod report;
mod report_diff;
#[cfg(test)]
mod report_doc;
mod score;
mod sheets;
mod ssim;
#[cfg(test)]
mod test_support;
#[cfg(test)]
mod tests;
mod verdict;

use std::collections::BTreeMap;
use std::fs;
use std::path::Path;

use args::Args;
use compare::run_compare;
use fade::fade_reference_set;
use frames::{load_render_frame, read_index_plane};
use loss::LOSS_CLASSES;
use mask::{CAPTURE_SKY_INDICES, overlay_drawn};
use matched::{Matching, ReportFrames};
use report::{FrameReport, I6Gate, Report};
use score::{FrameMetrics, RenderFrame, ScorePolicy, score_frame};
use sheets::ContactSheets;
use stunt_parity::{CapturedFrame, FilmCheck, FilmField, FilmId, RenderAdapter};

use crate::parity_artifacts;
use crate::render_store::RenderStore;

pub(crate) use args::usage;

/// `[I6]` initial acceptance threshold on the scored mean SSIM.
const I6_INITIAL_SSIM: f32 = 0.88;

/// `[I6]` sign-off threshold on the scored mean SSIM.
const I6_SIGN_OFF_SSIM: f32 = 0.90;

/// Whether the scored mean SSIM reaches each `[I6]` threshold; both fail when no frame is scored.
fn i6_gate(mean_ssim_scored: Option<f32>) -> I6Gate {
    let reaches = |threshold: f32| mean_ssim_scored.is_some_and(|ssim| ssim >= threshold);
    I6Gate {
        initial: reaches(I6_INITIAL_SSIM),
        sign_off: reaches(I6_SIGN_OFF_SSIM),
    }
}

/// A film-identity field's value as a message shows it, `?` when the side lacks it.
fn film_value(film: &FilmId, field: FilmField) -> String {
    match field {
        FilmField::Name => film.name.clone(),
        FilmField::FlmBytes => film.flm_bytes.map(|bytes| bytes.to_string()),
        FilmField::FlmSha256 => film.flm_sha256.clone(),
        FilmField::AllSha256 => film.all_sha256.clone(),
    }
    .unwrap_or_else(|| "?".to_string())
}

/// The terms on which a render may be scored against a capture, by their film identities.
#[derive(Debug, PartialEq, Eq)]
struct FilmClearance {
    /// The archives differ and `--waive-archive-conflict` let the score through.
    archive_conflict_waived: bool,
    /// The one line parity prints about the film check, if any.
    note: Option<String>,
}

/// Refuses a render whose film identity conflicts with the capture's ([`FilmId::check`]),
/// naming each conflicting field's two values.
fn check_film(
    capture: &FilmId,
    render: &FilmId,
    waive_archive: bool,
) -> Result<FilmClearance, String> {
    let archives = || {
        (
            film_value(capture, FilmField::AllSha256),
            film_value(render, FilmField::AllSha256),
        )
    };
    match render.check(capture, waive_archive) {
        FilmCheck::Agree => Ok(FilmClearance {
            archive_conflict_waived: false,
            note: None,
        }),
        FilmCheck::ArchiveUnchecked => {
            let reason = match (&capture.all_sha256, &render.all_sha256) {
                (None, None) => "neither side records an archive hash",
                (None, Some(_)) => "the capture records no archive hash",
                _ => "the render records no archive hash",
            };
            Ok(FilmClearance {
                archive_conflict_waived: false,
                note: Some(format!("[parity] archive not checked: {reason}")),
            })
        }
        FilmCheck::ArchiveWaived => {
            let (captured, rendered) = archives();
            Ok(FilmClearance {
                archive_conflict_waived: true,
                note: Some(format!(
                    "[parity] warning: scoring across archives (--waive-archive-conflict): the \
                     capture played .ALL {captured} but the render read {rendered}"
                )),
            })
        }
        FilmCheck::Refused(fields) => {
            let differences = fields
                .iter()
                .map(|&field| {
                    format!(
                        "the capture's {field} is {} but the render's is {}",
                        film_value(capture, field),
                        film_value(render, field)
                    )
                })
                .collect::<Vec<_>>()
                .join("; ");
            let remedy = if fields == [FilmField::AllSha256] {
                "re-render with the capture's archive, or pass --waive-archive-conflict to score a \
                 deliberate stand-in"
            } else {
                "re-render the capture's film"
            };
            Err(format!(
                "the render is not of the captured film: {differences}; {remedy}"
            ))
        }
    }
}

/// A per-class loss array as the report's name-to-value map.
fn loss_by_class(values: [f32; LOSS_CLASSES.len()]) -> BTreeMap<String, f32> {
    LOSS_CLASSES
        .iter()
        .zip(values)
        .map(|(name, value)| ((*name).to_string(), value))
        .collect()
}

/// One matched frame's place in the capture and its measurements.
#[derive(Debug, Clone, Copy)]
struct FrameRow {
    /// 1-based capture order.
    ordinal: usize,
    /// Film clock the frame was captured at; selects the stored render tick.
    film_tick: usize,
    metrics: FrameMetrics,
    /// The record expects credits here but the render drew no overlay pixel.
    credits_missing: bool,
}

/// Aggregates the matched frames into the `report.json` document, naming *adapter* as the one
/// the render was drawn on.
///
/// `scores` must not be empty: the means over every matched frame divide by its length.
/// The `*_scored` means cover only the frames that reached the fade floor and are `None`
/// when no frame did.
fn build_report(
    reference_frames: usize,
    scores: &[FrameRow],
    unmatched: usize,
    min_fade_level: f32,
    adapter: Option<RenderAdapter>,
) -> Report {
    let matched = scores.len() as f32;
    let mean_ssim = scores.iter().map(|s| s.metrics.ssim).sum::<f32>() / matched;
    let min_ssim = scores
        .iter()
        .map(|s| s.metrics.ssim)
        .fold(f32::INFINITY, f32::min);
    let mean_iou = scores.iter().map(|s| s.metrics.iou).sum::<f32>() / matched;
    let scored_frames: Vec<&FrameRow> = scores.iter().filter(|s| s.metrics.scored).collect();
    let excluded_frames = scores.len() - scored_frames.len();
    let scored_mean = |value: fn(&FrameRow) -> f32| {
        (!scored_frames.is_empty()).then(|| {
            scored_frames.iter().map(|s| value(s)).sum::<f32>() / scored_frames.len() as f32
        })
    };
    let mean_ssim_scored = scored_mean(|s| s.metrics.ssim);
    let mean_iou_scored = scored_mean(|s| s.metrics.iou);
    let attributed: Vec<[f32; LOSS_CLASSES.len()]> = scored_frames
        .iter()
        .map(|s| s.metrics.loss_by_class)
        .collect();
    let mean_loss_by_class = (!attributed.is_empty()).then(|| {
        let mut mean = [0.0f32; LOSS_CLASSES.len()];
        for loss in &attributed {
            for (total, value) in mean.iter_mut().zip(loss) {
                *total += value / attributed.len() as f32;
            }
        }
        loss_by_class(mean)
    });
    let mean_index_agreement_scored = scored_mean(|s| s.metrics.index_agreement);

    Report {
        reference_frames,
        frames: scores.len(),
        unmatched,
        sky_indices: [*CAPTURE_SKY_INDICES.start(), *CAPTURE_SKY_INDICES.end()],
        mean_ssim,
        min_ssim,
        mean_iou,
        min_fade_level,
        mean_ssim_scored,
        i6_gate: i6_gate(mean_ssim_scored),
        mean_iou_scored,
        mean_index_agreement_scored,
        mean_loss_by_class_scored: mean_loss_by_class,
        scored_frames: scored_frames.len(),
        excluded_frames,
        credits_missing_frames: scores.iter().filter(|s| s.credits_missing).count(),
        adapter,
        archive_conflict_waived: false,
        crates: None,
        per_frame: scores
            .iter()
            .map(|s| FrameReport {
                ordinal: s.ordinal,
                film_tick: s.film_tick as u64,
                ssim: s.metrics.ssim,
                iou: s.metrics.iou,
                index_agreement: Some(s.metrics.index_agreement),
                loss_by_class: Some(loss_by_class(s.metrics.loss_by_class)),
                fade_level: Some(s.metrics.fade_level),
                authored_fade_level: s.metrics.authored_fade_level,
                scored: Some(s.metrics.scored),
            })
            .collect(),
    }
}

/// Scores each matched frame against the render at its film clock, offering every scored
/// pair to the contact sheets; rows come back in capture order.
fn score_matched(
    reference_dir: &Path,
    store: &mut RenderStore,
    matched: &[&CapturedFrame],
    policy: &ScorePolicy<'_>,
    sheets: &mut ContactSheets<'_>,
) -> Result<Vec<FrameRow>, String> {
    let render_palettes: BTreeMap<u32, _> = store
        .record()
        .ticks
        .iter()
        .map(|tick| (tick.tick, parity_artifacts::core_palette(tick.palette)))
        .collect();
    let mut rows = Vec::with_capacity(matched.len());
    for frame in matched {
        let reference = matched::load_captured(reference_dir, frame)?;
        let render = load_render_frame(store, frame.film_tick)?;
        let credits_missing = render.credits && !overlay_drawn(&render.layers);
        let score = score_frame(
            &reference,
            &RenderFrame {
                controls: render_palettes.get(&frame.film_tick).copied(),
                ..render
            },
            policy,
        );
        let ordinal = frame.ordinal as usize;
        rows.push(FrameRow {
            ordinal,
            film_tick: frame.film_tick as usize,
            metrics: score.metrics,
            credits_missing,
        });
        sheets.offer(
            ordinal,
            score.metrics.scored.then_some(score.metrics.ssim),
            score.reference_luminance,
            score.render_luminance,
        )?;
    }
    Ok(rows)
}

/// Prints the run's headline, scored, loss and unmatched lines.
fn print_summary(report: &Report, min_fade_level: f32) {
    let (mean_ssim, mean_iou) = (report.mean_ssim, report.mean_iou);
    let excluded_frames = report.excluded_frames;
    println!(
        "[parity] {} frames, mean SSIM {mean_ssim:.3}, mean IoU {mean_iou:.3}",
        report.frames
    );
    match (report.mean_ssim_scored, report.mean_iou_scored) {
        (Some(ssim), Some(iou)) => println!(
            "[parity] {} scored frame(s) (fade level >= {min_fade_level:.2}), mean SSIM {ssim:.3}, mean IoU {iou:.3}; {excluded_frames} excluded",
            report.scored_frames
        ),
        _ => println!(
            "[parity] no frame reaches the fade floor (fade level >= {min_fade_level:.2}); {excluded_frames} excluded"
        ),
    }
    if let Some(loss) = &report.mean_loss_by_class_scored {
        let line = LOSS_CLASSES
            .iter()
            .filter_map(|name| Some(format!("{name} {:.3}", loss.get(*name)?)))
            .collect::<Vec<_>>()
            .join(", ");
        println!("[parity] SSIM loss by class (sums to 1 - mean SSIM over scored frames): {line}");
    }
    if let Some(agreement) = report.mean_index_agreement_scored {
        println!("[parity] mean index agreement {agreement:.3} over the scored frames with planes");
    }
    if report.unmatched > 0 {
        println!(
            "[parity] {} frame(s) missing on one side and skipped",
            report.unmatched
        );
    }
}

/// Runs the comparator and writes `report.json` plus contact sheets.
pub(crate) fn run(args: impl Iterator<Item = String>) -> Result<(), String> {
    let args = Args::try_parse_args(args).unwrap_or_else(|e| e.exit());
    fs::create_dir_all(&args.output)
        .map_err(|e| format!("create output directory {}: {e}", args.output.display()))?;

    let capture =
        parity_artifacts::load_capture(&args.reference).map_err(|error| error.to_string())?;
    let mut store = RenderStore::open(&args.test).map_err(|error| error.to_string())?;
    let clearance = check_film(
        &capture.film,
        &store.record().film,
        args.waive_archive_conflict,
    )?;
    if let Some(note) = &clearance.note {
        println!("{note}");
    }
    matched::check_geometry(&capture.geometry, &store.record().geometry)?;
    let frames = &capture.frames;
    let first_frame = frames
        .first()
        .ok_or_else(|| format!("{} has no captured frames", args.reference.display()))?;
    let first_plane = read_index_plane(&args.reference.join(&first_frame.frame_file))?;
    let fade_set = fade_reference_set(&first_plane);
    let policy = ScorePolicy {
        fade_set: &fade_set,
        min_fade_level: args.min_fade_level,
    };

    let Matching { matched, unmatched } = matched::pair(
        frames,
        |name| args.reference.join(name).is_file(),
        |tick| store.holds(tick),
    );
    let mut sheets = ContactSheets::new(&args.output, frames.len());
    let scores = score_matched(&args.reference, &mut store, &matched, &policy, &mut sheets)?;
    sheets.finish()?;

    if scores.is_empty() {
        return Err(format!(
            "no comparable frames: {} reference frame(s), {unmatched} unmatched",
            frames.len()
        ));
    }

    let report = Report {
        archive_conflict_waived: clearance.archive_conflict_waived,
        crates: args.crates.clone(),
        ..build_report(
            frames.len(),
            &scores,
            unmatched,
            args.min_fade_level,
            store.record().adapter.clone(),
        )
    };
    if let Some(tick) = scores
        .iter()
        .find(|s| s.credits_missing)
        .map(|s| s.film_tick)
    {
        eprintln!(
            "[parity warning] {} frame(s) expect credits the render did not draw, first at tick {tick} (no PFONT.BIN?); their ink is scored",
            report.credits_missing_frames
        );
    }
    let report_path = args.output.join("report.json");
    parity_artifacts::write_report(&report_path, &report).map_err(|error| error.to_string())?;

    print_summary(&report, args.min_fade_level);

    if let Some(previous_path) = &args.compare {
        run_compare(&args, previous_path, &report, &ReportFrames::new(frames))?;
    }
    Ok(())
}
