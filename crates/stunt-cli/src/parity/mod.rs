//! Visual parity comparator: `PLAYONE.EXE` Mode 13h captures against rendered frames.
//!
//! Reference frames are palette-index planes (`tick_NNNN.idx` + `palettes_NNNN.json`,
//! numbered by capture order) dumped from the emulator's scanned-out page. Each frame's
//! `meta.json` entry carries `film_tick`, the film clock read when it was captured.
//! Rendered frames are `tick_NNNNN.png` written by `stuntreel --out-dir`, named by the
//! 0-based 50 Hz tick they show, so a capture is compared against the render at the
//! same `film_tick`. Captures that predate film-clock tagging are rejected.
//!
//! Scores follow Invariant `[I6]`: both sides are reduced to Rec. 601 luminance,
//! stretched from 320x200 to the 320x240 physical 4:3 raster, and compared with the
//! shared `compute_frame_ssim` window evaluator. IoU compares each side's non-sky mask,
//! which measures framing agreement independently of shading.
//!
//! The original fades its palette with the film's brightness variable, and so does the
//! render. Each capture's fade level (see [`fade::fade_level`]) is measured from its captured
//! palette; frames whose level falls below `--min-fade-level` are reported but not
//! scored, because SSIM of near-black frames says little. When the render directory has a
//! palette sidecar the floor is applied to the film's authored brightness (var 14) instead,
//! with the measured level kept in the report as a cross-check. The headline is raw SSIM over
//! the scored frames. The render's clear colour, needed for the IoU sky mask, comes from
//! the film palette recorded in its `palette_controls.json` (the static colour when a
//! render directory has none).
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
mod report_diff;
mod sheets;
#[cfg(test)]
mod test_support;
#[cfg(test)]
mod tests;

use std::collections::{BTreeMap, BTreeSet};
use std::fs;

use serde_json::{Value, json};
use stunt_core::contracts::{PALETTE_CONTROL_FULL, get_palette_rgb};
use stunt_render::{
    ASPECT_CORRECTED_HEIGHT, MODE13H_HEIGHT, MODE13H_WIDTH, compute_luminance,
    compute_window_scores, rescale_mode13h_frame,
};

use args::Args;
use compare::run_compare;
use fade::{fade_level, fade_reference_set};
use frames::{
    load_reference, read_film_ticks, read_index_plane, read_png_luminance, read_render_palettes,
    read_render_planes, reference_luminance, reference_paths, sky_index, warn_on_film_mismatch,
};
use loss::{LOSS_CLASSES, attribute_loss, loss_class};
use mask::{index_agreement, mask_iou, mask_iou_planes, rescale_mask, ui_overlay_mask};
use sheets::write_contact_sheet;

pub(crate) use args::USAGE;

/// Frame ordinals always rendered as contact sheets, plus the last captured frame.
const CONTACT_SHEET_ORDINALS: [usize; 5] = [1, 20, 40, 70, 100];

/// SSIM window edge, in pixels.
const SSIM_WINDOW: usize = 11;

/// SSIM window stride, in pixels.
const SSIM_STRIDE: usize = 8;

/// Number of additionally worst-scoring frames rendered as contact sheets.
const CONTACT_SHEET_WORST: usize = 3;

/// Per-frame parity measurements.
#[derive(Debug, Clone, Copy)]
struct FrameScore {
    /// 1-based capture order.
    ordinal: usize,
    /// Film clock the frame was captured at; selects the rendered `tick_NNNNN.png`.
    film_tick: usize,
    /// SSIM of the render against the capture.
    ssim: f32,
    /// Median ratio of the captured palette's brightness to the static palette's.
    fade_level: f32,
    /// Brightness the film authors at this tick (var 14 over [`PALETTE_CONTROL_FULL`]); `None`
    /// when the render directory carries no palette sidecar.
    authored_fade_level: Option<f32>,
    /// Whether the fade reaches the `--min-fade-level` floor: the authored level when
    /// known, else the measured `fade_level`.
    scored: bool,
    iou: f32,
    /// Fraction of non-overlay pixels whose palette index equals the capture's; `None`
    /// when the render directory carries no index plane for this tick.
    index_agreement: Option<f32>,
    /// This frame's SSIM loss (`1 - ssim`) split by what the window covers; `None` without
    /// render planes. The entries sum to `1 - ssim`.
    loss_by_class: Option<[f32; LOSS_CLASSES.len()]>,
}

/// Runs the comparator and writes `report.json` plus contact sheets.
pub(crate) fn run(args: impl Iterator<Item = String>) -> Result<(), String> {
    let args = Args::parse(args)?;
    fs::create_dir_all(&args.output)
        .map_err(|e| format!("create output directory {}: {e}", args.output.display()))?;

    let meta_path = args.reference.join("meta.json");
    let meta_text =
        fs::read_to_string(&meta_path).map_err(|e| format!("read {}: {e}", meta_path.display()))?;
    let meta: Value = serde_json::from_str(&meta_text)
        .map_err(|e| format!("parse {}: {e}", meta_path.display()))?;
    let frames = meta
        .get("frames")
        .and_then(Value::as_array)
        .ok_or_else(|| format!("{} has no frames array", meta_path.display()))?;

    warn_on_film_mismatch(&meta, &args.test);
    let film_ticks = read_film_ticks(frames, &meta_path)?;
    let sky_index = sky_index(frames.first(), &args.reference)?;
    let render_palettes = read_render_palettes(&args.test)?;
    let first_plane = read_index_plane(&reference_paths(&args.reference, &frames[0], 1).0)?;
    let fade_set = fade_reference_set(&first_plane);

    let mut sheet_ordinals: BTreeSet<usize> = CONTACT_SHEET_ORDINALS.iter().copied().collect();
    sheet_ordinals.insert(film_ticks.len());

    let mut scores: Vec<FrameScore> = Vec::with_capacity(frames.len());
    let mut unmatched = 0usize;
    let mut written_sheets: BTreeSet<usize> = BTreeSet::new();
    let mut worst: Vec<(f32, usize, Vec<f32>, Vec<f32>)> = Vec::new();

    for (index, frame) in frames.iter().enumerate() {
        let ordinal = index + 1;
        let film_tick = film_ticks[index];
        let (reference_file, palette_file) = reference_paths(&args.reference, frame, ordinal);
        let test_file = args.test.join(crate::tick_png_name(film_tick));

        if !reference_file.is_file() || !palette_file.is_file() || !test_file.is_file() {
            unmatched += 1;
            continue;
        }

        let (indices, palette) = load_reference(&reference_file, &palette_file)?;
        let reference_rescaled = reference_luminance(&indices, &palette);
        let fade = fade_level(&fade_set, &palette);
        let (clear_r, clear_g, clear_b) = match render_palettes.get(&film_tick) {
            Some(controls) => controls.film_palette()[usize::from(args.clear_index)],
            None => get_palette_rgb(args.clear_index),
        };
        let clear_luminance = compute_luminance(clear_r as f32, clear_g as f32, clear_b as f32);
        let test_luminance = read_png_luminance(&test_file)?;

        let test_rescaled = rescale_mode13h_frame(
            &test_luminance,
            MODE13H_WIDTH,
            MODE13H_HEIGHT,
            ASPECT_CORRECTED_HEIGHT,
        );
        let overlay = ui_overlay_mask(&indices);
        let overlay_rescaled = rescale_mask(&overlay);
        let windows = compute_window_scores(
            &reference_rescaled,
            &test_rescaled,
            MODE13H_WIDTH,
            ASPECT_CORRECTED_HEIGHT,
            SSIM_WINDOW,
            SSIM_STRIDE,
            Some(&overlay_rescaled),
        );
        let ssim = if windows.is_empty() {
            1.0
        } else {
            windows.iter().map(|w| w.score).sum::<f32>() / windows.len() as f32
        };
        let planes = read_render_planes(&args.test, film_tick)?;
        let loss_by_class = planes.as_ref().map(|(_, render_layers)| {
            let codes: Vec<f32> = indices
                .iter()
                .zip(render_layers)
                .map(|(&index, &layer)| f32::from(loss_class(layer, index != sky_index)))
                .collect();
            let classes: Vec<u8> = rescale_mode13h_frame(
                &codes,
                MODE13H_WIDTH,
                MODE13H_HEIGHT,
                ASPECT_CORRECTED_HEIGHT,
            )
            .into_iter()
            .map(|code| code as u8)
            .collect();
            attribute_loss(&windows, &classes, SSIM_WINDOW)
        });
        let (iou, index_agreement) = match &planes {
            Some((render_indices, render_layers)) => (
                mask_iou_planes(&indices, sky_index, render_layers, &overlay),
                Some(index_agreement(&indices, render_indices, &overlay)),
            ),
            None => (
                mask_iou(
                    &indices,
                    sky_index,
                    &test_luminance,
                    clear_luminance,
                    &overlay,
                ),
                None,
            ),
        };
        let authored_fade = render_palettes
            .get(&film_tick)
            .map(|controls| f32::from(controls.brightness) / f32::from(PALETTE_CONTROL_FULL));
        let scored = authored_fade.unwrap_or(fade) >= args.min_fade_level;

        scores.push(FrameScore {
            ordinal,
            film_tick,
            ssim,
            fade_level: fade,
            authored_fade_level: authored_fade,
            scored,
            iou,
            index_agreement,
            loss_by_class,
        });

        if sheet_ordinals.contains(&ordinal) {
            write_contact_sheet(&args.output, ordinal, &reference_rescaled, &test_rescaled)?;
            written_sheets.insert(ordinal);
        }

        if scored {
            worst.push((ssim, ordinal, reference_rescaled, test_rescaled));
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
    let mean_ssim = scores.iter().map(|s| s.ssim).sum::<f32>() / matched;
    let min_ssim = scores.iter().map(|s| s.ssim).fold(f32::INFINITY, f32::min);
    let mean_iou = scores.iter().map(|s| s.iou).sum::<f32>() / matched;
    let scored_frames: Vec<&FrameScore> = scores.iter().filter(|s| s.scored).collect();
    let excluded_frames = scores.len() - scored_frames.len();
    let scored_mean = |value: fn(&FrameScore) -> f32| {
        (!scored_frames.is_empty()).then(|| {
            scored_frames.iter().map(|s| value(s)).sum::<f32>() / scored_frames.len() as f32
        })
    };
    let mean_ssim_scored = scored_mean(|s| s.ssim);
    let mean_iou_scored = scored_mean(|s| s.iou);
    let attributed: Vec<[f32; LOSS_CLASSES.len()]> = scored_frames
        .iter()
        .filter_map(|s| s.loss_by_class)
        .collect();
    let mean_loss_by_class = (!attributed.is_empty()).then(|| {
        let mut mean = [0.0f32; LOSS_CLASSES.len()];
        for loss in &attributed {
            for (total, value) in mean.iter_mut().zip(loss) {
                *total += value / attributed.len() as f32;
            }
        }
        json!(LOSS_CLASSES.iter().zip(mean).collect::<BTreeMap<_, _>>())
    });
    let agreement: Vec<f32> = scored_frames
        .iter()
        .filter_map(|s| s.index_agreement)
        .collect();
    let mean_index_agreement_scored =
        (!agreement.is_empty()).then(|| agreement.iter().sum::<f32>() / agreement.len() as f32);

    let report = json!({
        "reference_frames": frames.len(),
        "frames": scores.len(),
        "unmatched": unmatched,
        "sky_index": sky_index,
        "clear_index": args.clear_index,
        "mean_ssim": mean_ssim,
        "min_ssim": min_ssim,
        "mean_iou": mean_iou,
        "min_fade_level": args.min_fade_level,
        "mean_ssim_scored": mean_ssim_scored,
        "mean_iou_scored": mean_iou_scored,
        "mean_index_agreement_scored": mean_index_agreement_scored,
        "mean_loss_by_class_scored": mean_loss_by_class,
        "scored_frames": scored_frames.len(),
        "excluded_frames": excluded_frames,
        "per_frame": scores
            .iter()
            .map(|s| json!({
                "ordinal": s.ordinal,
                "film_tick": s.film_tick,
                "ssim": s.ssim,
                "iou": s.iou,
                "index_agreement": s.index_agreement,
                "loss_by_class": s.loss_by_class.map(|loss| {
                    LOSS_CLASSES.iter().zip(loss).collect::<BTreeMap<_, _>>()
                }),
                "fade_level": s.fade_level,
                "authored_fade_level": s.authored_fade_level,
                "scored": s.scored,
            }))
            .collect::<Vec<Value>>(),
    });
    let report_path = args.output.join("report.json");
    fs::write(
        &report_path,
        serde_json::to_string_pretty(&report).map_err(|e| format!("serialize report: {e}"))?,
    )
    .map_err(|e| format!("write {}: {e}", report_path.display()))?;

    println!(
        "[parity] {} frames, mean SSIM {mean_ssim:.3}, mean IoU {mean_iou:.3}, sky index {sky_index}",
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
    if let Some(loss) = &mean_loss_by_class {
        let line = LOSS_CLASSES
            .iter()
            .filter_map(|name| Some(format!("{name} {:.3}", loss[name].as_f64()?)))
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
