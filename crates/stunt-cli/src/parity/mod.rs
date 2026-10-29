//! Visual parity comparator: `PLAYONE.EXE` Mode 13h captures against rendered frames.
//!
//! Reference frames are palette-index planes (`tick_NNNN.idx` + `palettes_NNNN.json`,
//! numbered by capture order) dumped from the emulator's scanned-out page. Each frame's
//! `meta.json` entry carries `film_tick`, the film clock read when it was captured.
//! Rendered frames are `tick_NNNNN.png` written by `stuntreel --out-dir`, named by the
//! 0-based 50 Hz tick they show, so a capture is compared against the render at the
//! same `film_tick`. Captures that predate film-clock tagging are rejected.
//!
//! Each matched pair is scored by [`score::score_frame`]. Scores follow Invariant `[I6]`:
//! both sides are reduced to Rec. 601 luminance, stretched from 320x200 to the 320x240
//! physical 4:3 raster, and compared with the shared `compute_frame_ssim` window evaluator. IoU compares each side's non-sky mask,
//! which measures framing agreement independently of shading. A capture's sky is every
//! pixel in the sky bands ([`mask::CAPTURE_SKY_INDICES`]), not one modal index.
//!
//! The original fades its palette with the film's brightness variable, and so does the
//! render. Each capture's fade level (see [`fade::fade_level`]) is measured from its captured
//! palette; frames whose level falls below `--min-fade-level` are reported but not
//! scored, because SSIM of near-black frames says little. When the render directory has a
//! palette sidecar the floor is applied to the film's authored brightness (var 14) instead,
//! with the measured level kept in the report as a cross-check. The headline is raw SSIM over
//! the scored frames.
//!
//! Every render needs its palette-index and layer planes (`tick_NNNNN.idx`/`.layer`, written
//! by `--headless`): IoU and loss attribution read the render's coverage from the layer
//! plane, never from its colours, so a render directory without planes is an error.
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
mod report;
mod report_diff;
mod score;
mod sheets;
#[cfg(test)]
mod test_support;
#[cfg(test)]
mod tests;

use std::collections::{BTreeMap, BTreeSet};
use std::fs;

use args::Args;
use compare::run_compare;
use fade::fade_reference_set;
use frames::{load_reference, read_index_plane, read_png_luminance};
use loss::LOSS_CLASSES;
use mask::CAPTURE_SKY_INDICES;
use report::{FrameReport, I6Gate, Report};
use score::{FrameMetrics, ReferenceFrame, RenderFrame, ScorePolicy, score_frame};
use sheets::write_contact_sheet;
use stunt_parity::FilmId;

use crate::{parity_artifacts, plane_codec};

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

/// Prints a warning when the capture and the render name different films or `.FLM` sizes.
fn warn_on_film_mismatch(capture: &FilmId, render: &FilmId) {
    if capture.names_conflict(render) {
        println!(
            "[parity] warning: the capture is of {} but the render is of {}",
            capture.name.as_deref().unwrap_or("?"),
            render.name.as_deref().unwrap_or("?")
        );
    }
    if capture.bytes_conflict(render) {
        println!(
            "[parity] warning: the capture's .FLM is {} bytes but the render's is {}",
            capture.flm_bytes.unwrap_or(0),
            render.flm_bytes.unwrap_or(0)
        );
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

/// Frame ordinals always rendered as contact sheets, plus the last captured frame.
const CONTACT_SHEET_ORDINALS: [usize; 5] = [1, 20, 40, 70, 100];

/// Number of additionally worst-scoring frames rendered as contact sheets.
const CONTACT_SHEET_WORST: usize = 3;

/// One matched frame's place in the capture and its measurements.
#[derive(Debug, Clone, Copy)]
struct FrameRow {
    /// 1-based capture order.
    ordinal: usize,
    /// Film clock the frame was captured at; selects the rendered `tick_NNNNN.png`.
    film_tick: usize,
    metrics: FrameMetrics,
}

/// Runs the comparator and writes `report.json` plus contact sheets.
pub(crate) fn run(args: impl Iterator<Item = String>) -> Result<(), String> {
    let args = Args::try_parse_args(args).unwrap_or_else(|e| e.exit());
    fs::create_dir_all(&args.output)
        .map_err(|e| format!("create output directory {}: {e}", args.output.display()))?;

    let capture =
        parity_artifacts::load_capture(&args.reference).map_err(|error| error.to_string())?;
    let render =
        parity_artifacts::load_render_controls(&args.test).map_err(|error| error.to_string())?;
    warn_on_film_mismatch(&capture.film, &render.film);
    let geometry = render
        .geometry
        .clone()
        .unwrap_or_else(|| capture.geometry.clone());
    if geometry.width != capture.geometry.width || geometry.height != capture.geometry.height {
        return Err(format!(
            "render geometry {}x{} differs from the capture's {}x{}; re-render \
             with --width {} --height {}",
            geometry.width,
            geometry.height,
            capture.geometry.width,
            capture.geometry.height,
            capture.geometry.width,
            capture.geometry.height
        ));
    }
    let frames = &capture.frames;
    let render_palettes = render.controls;
    let first_frame = frames
        .first()
        .ok_or_else(|| format!("{} has no captured frames", args.reference.display()))?;
    let first_plane = read_index_plane(&args.reference.join(&first_frame.frame_file))?;
    let fade_set = fade_reference_set(&first_plane);
    let policy = ScorePolicy {
        fade_set: &fade_set,
        min_fade_level: args.min_fade_level,
    };

    let mut sheet_ordinals: BTreeSet<usize> = CONTACT_SHEET_ORDINALS.iter().copied().collect();
    sheet_ordinals.insert(frames.len());

    let mut scores: Vec<FrameRow> = Vec::with_capacity(frames.len());
    let mut unmatched = 0usize;
    let mut written_sheets: BTreeSet<usize> = BTreeSet::new();
    let mut worst: Vec<(f32, usize, Vec<f32>, Vec<f32>)> = Vec::new();

    for frame in frames {
        let ordinal = frame.ordinal as usize;
        let film_tick = frame.film_tick as usize;
        let reference_file = args.reference.join(&frame.frame_file);
        let palette_file = args.reference.join(&frame.palette_file);
        let test_file = args.test.join(crate::headless::tick_png_name(film_tick));

        if !reference_file.is_file() || !palette_file.is_file() || !test_file.is_file() {
            unmatched += 1;
            continue;
        }

        let (indices, palette) = load_reference(&reference_file, &palette_file)?;
        let planes = plane_codec::read_page_planes(&test_file, &geometry)
            .map_err(|error| error.to_string())?;
        let score = score_frame(
            &ReferenceFrame { indices, palette },
            &RenderFrame {
                luminance: read_png_luminance(&test_file)?,
                indices: planes.indices,
                layers: planes.layers,
                controls: render_palettes.get(&(film_tick as u32)).copied(),
            },
            &policy,
        );
        let (metrics, reference_rescaled, test_rescaled) = (
            score.metrics,
            score.reference_luminance,
            score.render_luminance,
        );
        scores.push(FrameRow {
            ordinal,
            film_tick,
            metrics,
        });

        if sheet_ordinals.contains(&ordinal) {
            write_contact_sheet(&args.output, ordinal, &reference_rescaled, &test_rescaled)?;
            written_sheets.insert(ordinal);
        }

        if metrics.scored {
            worst.push((metrics.ssim, ordinal, reference_rescaled, test_rescaled));
            worst.sort_by(|a, b| a.0.total_cmp(&b.0));
            worst.truncate(CONTACT_SHEET_WORST);
        }
    }

    for (_ssim, ordinal, reference_rescaled, test_rescaled) in &worst {
        if written_sheets.contains(ordinal) {
            continue;
        }
        write_contact_sheet(&args.output, *ordinal, reference_rescaled, test_rescaled)?;
        written_sheets.insert(*ordinal);
    }

    if scores.is_empty() {
        return Err(format!(
            "no comparable frames: {} reference frame(s), {unmatched} unmatched",
            frames.len()
        ));
    }

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

    let report = Report {
        reference_frames: frames.len(),
        frames: scores.len(),
        unmatched,
        sky_indices: [*CAPTURE_SKY_INDICES.start(), *CAPTURE_SKY_INDICES.end()],
        mean_ssim,
        min_ssim,
        mean_iou,
        min_fade_level: args.min_fade_level,
        mean_ssim_scored,
        i6_gate: i6_gate(mean_ssim_scored),
        mean_iou_scored,
        mean_index_agreement_scored,
        mean_loss_by_class_scored: mean_loss_by_class,
        scored_frames: scored_frames.len(),
        excluded_frames,
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
    };
    let report_path = args.output.join("report.json");
    parity_artifacts::write_report(&report_path, &report).map_err(|error| error.to_string())?;

    println!(
        "[parity] {} frames, mean SSIM {mean_ssim:.3}, mean IoU {mean_iou:.3}",
        scores.len()
    );
    match (mean_ssim_scored, mean_iou_scored) {
        (Some(ssim), Some(iou)) => println!(
            "[parity] {} scored frame(s) (fade level >= {:.2}), mean SSIM {ssim:.3}, mean IoU {iou:.3}; {excluded_frames} excluded",
            scored_frames.len(),
            args.min_fade_level
        ),
        _ => println!(
            "[parity] no frame reaches the fade floor (fade level >= {:.2}); {excluded_frames} excluded",
            args.min_fade_level
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
    if let Some(agreement) = mean_index_agreement_scored {
        println!("[parity] mean index agreement {agreement:.3} over the scored frames with planes");
    }
    if unmatched > 0 {
        println!("[parity] {unmatched} frame(s) missing on one side and skipped");
    }

    if let Some(previous_path) = &args.compare {
        run_compare(&args, previous_path, &report, frames)?;
    }
    Ok(())
}
