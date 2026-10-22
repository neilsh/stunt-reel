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
//! The original fades its palette to black over the film's last ticks and our render has
//! no fade, so each capture's fade level (see [`fade_level`]) is measured from its
//! captured palette and the render's luminance is scaled by it before the compensated
//! SSIM. Frames whose level falls below `--min-fade-level` are reported but not scored.
//!
//! `--compare <report.json>` additionally matches the fresh scores against a previous
//! run by `film_tick` (see [`compare_reports`]), so a change is judged frame by frame
//! rather than only by the means.

use std::collections::{BTreeMap, BTreeSet};
use std::fs;
use std::path::{Path, PathBuf};

use serde_json::{Value, json};
use stunt_core::contracts::get_palette_rgb;
use stunt_render::{
    ASPECT_CORRECTED_HEIGHT, MODE13H_HEIGHT, MODE13H_WIDTH, compute_frame_ssim, compute_luminance,
    rescale_mode13h_frame, rgb_to_luminance, rgba_to_luminance,
};

/// Horizontal gap between contact-sheet panels, in pixels.
const CONTACT_SHEET_GAP: usize = 8;

/// Frame ordinals always rendered as contact sheets, plus the last captured frame.
const CONTACT_SHEET_ORDINALS: [usize; 5] = [1, 20, 40, 70, 100];

/// Number of additionally worst-scoring frames rendered as contact sheets.
const CONTACT_SHEET_WORST: usize = 3;

/// Per-frame parity measurements.
#[derive(Debug, Clone, Copy)]
struct FrameScore {
    /// 1-based capture order.
    ordinal: usize,
    /// Film clock the frame was captured at; selects the rendered `tick_NNNNN.png`.
    film_tick: usize,
    /// SSIM of the unmodified render.
    ssim: f32,
    /// SSIM of the render scaled by `fade_level`.
    ssim_compensated: f32,
    /// Median ratio of the captured palette's brightness to the static palette's.
    fade_level: f32,
    /// Whether `fade_level` reaches the `--min-fade-level` floor.
    scored: bool,
    iou: f32,
}

/// Parsed `stuntreel parity` arguments.
#[derive(Debug)]
struct Args {
    reference: PathBuf,
    test: PathBuf,
    output: PathBuf,
    clear_index: u8,
    /// Frames fading below this level are reported but excluded from the scored means.
    min_fade_level: f32,
    /// Previous `report.json` to compare the fresh scores against.
    compare: Option<PathBuf>,
    /// Render directory of the previous run, used for before/after contact sheets.
    compare_test: Option<PathBuf>,
}

/// Usage text printed by `--help`.
pub(crate) const USAGE: &str =
    "Usage: stuntreel parity --reference <dir> --test <dir> --output <dir> \
[--clear-index N] [--min-fade-level F] [--compare <report.json> [--compare-test <dir>]]

  --min-fade-level F       Frames whose measured palette fade level is below F (default
                           0.25) are reported but left out of the compensated means
  --compare <report.json>  Match frames by film_tick against a previous report and print
                           mean SSIM/IoU deltas, the 5 most improved/regressed frames and
                           the counts changed by more than 0.005; writes compare.json
  --compare-test <dir>     The previous run's render directory; with --compare, writes
                           before/after contact sheets for the most regressed and most
                           improved frame (skipped, with a note, when absent)";

impl Args {
    fn parse(mut args: impl Iterator<Item = String>) -> Result<Self, String> {
        let mut reference = None;
        let mut test = None;
        let mut output = None;
        let mut clear_index = 180u8;
        let mut min_fade_level = 0.25f32;
        let mut compare = None;
        let mut compare_test = None;

        while let Some(arg) = args.next() {
            match arg.as_str() {
                "--reference" => {
                    reference = Some(PathBuf::from(
                        args.next().ok_or("Expected directory after --reference")?,
                    ));
                }
                "--test" => {
                    test = Some(PathBuf::from(
                        args.next().ok_or("Expected directory after --test")?,
                    ));
                }
                "--output" => {
                    output = Some(PathBuf::from(
                        args.next().ok_or("Expected directory after --output")?,
                    ));
                }
                "--clear-index" => {
                    let value = args.next().ok_or("Expected number after --clear-index")?;
                    clear_index = value
                        .parse::<u8>()
                        .map_err(|e| format!("Invalid clear index: {e}"))?;
                }
                "--min-fade-level" => {
                    let value = args
                        .next()
                        .ok_or("Expected number after --min-fade-level")?;
                    min_fade_level = value
                        .parse::<f32>()
                        .map_err(|e| format!("Invalid min fade level: {e}"))?;
                    if !min_fade_level.is_finite() || min_fade_level < 0.0 {
                        return Err(format!(
                            "Invalid min fade level: {value} (expected a finite number >= 0)"
                        ));
                    }
                }
                "--compare" => {
                    compare = Some(PathBuf::from(
                        args.next().ok_or("Expected report.json after --compare")?,
                    ));
                }
                "--compare-test" => {
                    compare_test = Some(PathBuf::from(
                        args.next()
                            .ok_or("Expected directory after --compare-test")?,
                    ));
                }
                "--help" | "-h" => {
                    println!("{USAGE}");
                    std::process::exit(0);
                }
                other => return Err(format!("Unrecognized parity argument: {other}")),
            }
        }

        if compare_test.is_some() && compare.is_none() {
            return Err("--compare-test requires --compare <report.json>".to_string());
        }

        Ok(Self {
            reference: reference.ok_or("parity requires --reference <dir>")?,
            test: test.ok_or("parity requires --test <dir>")?,
            output: output.ok_or("parity requires --output <dir>")?,
            clear_index,
            min_fade_level,
            compare,
            compare_test,
        })
    }
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

    let film_ticks = read_film_ticks(frames, &meta_path)?;
    let sky_index = sky_index(frames.first(), &args.reference)?;
    let (clear_r, clear_g, clear_b) = get_palette_rgb(args.clear_index);
    let clear_luminance = compute_luminance(clear_r as f32, clear_g as f32, clear_b as f32);
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
        let test_luminance = read_png_luminance(&test_file)?;

        let test_rescaled = rescale_mode13h_frame(
            &test_luminance,
            MODE13H_WIDTH,
            MODE13H_HEIGHT,
            ASPECT_CORRECTED_HEIGHT,
        );
        let ssim = compute_frame_ssim(
            &reference_rescaled,
            &test_rescaled,
            MODE13H_WIDTH,
            ASPECT_CORRECTED_HEIGHT,
            11,
            8,
        );
        let compensated: Vec<f32> = test_rescaled.iter().map(|v| v * fade).collect();
        let ssim_compensated = compute_frame_ssim(
            &reference_rescaled,
            &compensated,
            MODE13H_WIDTH,
            ASPECT_CORRECTED_HEIGHT,
            11,
            8,
        );
        let iou = mask_iou(&indices, sky_index, &test_luminance, clear_luminance);
        let scored = fade >= args.min_fade_level;

        scores.push(FrameScore {
            ordinal,
            film_tick,
            ssim,
            ssim_compensated,
            fade_level: fade,
            scored,
            iou,
        });

        // Sheets show the compensated render, which is what was scored.
        if sheet_ordinals.contains(&ordinal) {
            write_contact_sheet(&args.output, ordinal, &reference_rescaled, &compensated)?;
            written_sheets.insert(ordinal);
        }

        if scored {
            worst.push((ssim_compensated, ordinal, reference_rescaled, compensated));
            worst.sort_by(|a, b| a.0.total_cmp(&b.0));
            worst.truncate(CONTACT_SHEET_WORST);
        }
    }

    for (_ssim, ordinal, reference_rescaled, compensated) in &worst {
        if written_sheets.contains(ordinal) {
            continue;
        }
        write_contact_sheet(&args.output, *ordinal, reference_rescaled, compensated)?;
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
    let mean_ssim_compensated = scored_mean(|s| s.ssim_compensated);
    let mean_iou_scored = scored_mean(|s| s.iou);

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
        "mean_ssim_compensated": mean_ssim_compensated,
        "mean_iou_scored": mean_iou_scored,
        "scored_frames": scored_frames.len(),
        "excluded_frames": excluded_frames,
        "per_frame": scores
            .iter()
            .map(|s| json!({
                "ordinal": s.ordinal,
                "film_tick": s.film_tick,
                "ssim": s.ssim,
                "iou": s.iou,
                "ssim_compensated": s.ssim_compensated,
                "fade_level": s.fade_level,
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
    match (mean_ssim_compensated, mean_iou_scored) {
        (Some(ssim), Some(iou)) => println!(
            "[parity] {} scored frame(s) (fade level >= {:.2}), mean compensated SSIM {ssim:.3}, mean IoU {iou:.3}; {excluded_frames} excluded",
            scored_frames.len(),
            args.min_fade_level
        ),
        _ => println!(
            "[parity] no frame reaches the fade floor (fade level >= {:.2}); {excluded_frames} excluded",
            args.min_fade_level
        ),
    }
    if unmatched > 0 {
        println!("[parity] {unmatched} frame(s) missing on one side and skipped");
    }

    if let Some(previous_path) = &args.compare {
        run_compare(&args, previous_path, &report, frames)?;
    }
    Ok(())
}

/// Index-plane and palette paths of one captured frame (`ordinal` is 1-based).
fn reference_paths(reference_dir: &Path, frame: &Value, ordinal: usize) -> (PathBuf, PathBuf) {
    let name = |key: &str, fallback: String| {
        reference_dir.join(
            frame
                .get(key)
                .and_then(Value::as_str)
                .map_or(fallback, str::to_string),
        )
    };
    (
        name("frame_file", format!("tick_{ordinal:04}.idx")),
        name("palette_file", format!("palettes_{ordinal:04}.json")),
    )
}

/// A 256-entry RGB palette.
type Palette = Vec<(u8, u8, u8)>;

/// Loads a captured frame: its palette-index plane and its captured palette.
fn load_reference(
    reference_file: &Path,
    palette_file: &Path,
) -> Result<(Vec<u8>, Palette), String> {
    Ok((
        read_index_plane(reference_file)?,
        read_palette(palette_file)?,
    ))
}

/// Aspect-corrected luminance of an index plane seen through `palette`.
fn reference_luminance(indices: &[u8], palette: &[(u8, u8, u8)]) -> Vec<f32> {
    let mut reference_rgb = Vec::with_capacity(MODE13H_WIDTH * MODE13H_HEIGHT * 3);
    for &index in indices {
        let (r, g, b) = palette[index as usize];
        reference_rgb.extend_from_slice(&[r, g, b]);
    }
    rescale_mode13h_frame(
        &rgb_to_luminance(&reference_rgb),
        MODE13H_WIDTH,
        MODE13H_HEIGHT,
        ASPECT_CORRECTED_HEIGHT,
    )
}

/// Static palette entries at or below this R+G+B sum are too dark to measure a fade by.
const FADE_MIN_STATIC_SUM: u32 = 60;

fn rgb_sum((r, g, b): (u8, u8, u8)) -> u32 {
    u32::from(r) + u32::from(g) + u32::from(b)
}

/// Palette indices present in `indices` that are bright enough in the static palette to
/// measure a fade by.
fn fade_reference_set(indices: &[u8]) -> Vec<u8> {
    let mut present = [false; 256];
    for &index in indices {
        present[index as usize] = true;
    }
    (0..=255u8)
        .filter(|&i| present[i as usize] && rgb_sum(get_palette_rgb(i)) > FADE_MIN_STATIC_SUM)
        .collect()
}

/// Fade level of a captured `palette`: the median, over the `set` indices, of the
/// captured R+G+B sum relative to the static palette's. 1.0 for an empty set; the raw
/// median is returned (a capture without fade reads about 1.0, slightly off either way).
fn fade_level(set: &[u8], palette: &[(u8, u8, u8)]) -> f32 {
    let mut ratios: Vec<f32> = set
        .iter()
        .map(|&i| rgb_sum(palette[i as usize]) as f32 / rgb_sum(get_palette_rgb(i)) as f32)
        .collect();
    if ratios.is_empty() {
        return 1.0;
    }
    ratios.sort_by(f32::total_cmp);
    let mid = ratios.len() / 2;
    if ratios.len().is_multiple_of(2) {
        (ratios[mid - 1] + ratios[mid]) / 2.0
    } else {
        ratios[mid]
    }
}

/// Loads a rendered PNG as aspect-corrected luminance.
fn load_render_rescaled(path: &Path) -> Result<Vec<f32>, String> {
    Ok(rescale_mode13h_frame(
        &read_png_luminance(path)?,
        MODE13H_WIDTH,
        MODE13H_HEIGHT,
        ASPECT_CORRECTED_HEIGHT,
    ))
}

/// Compares the fresh `report` with the previous report at `previous_path`: prints the
/// summary, writes `compare.json`, and renders before/after sheets when the previous
/// render directory was given.
fn run_compare(
    args: &Args,
    previous_path: &Path,
    report: &Value,
    frames: &[Value],
) -> Result<(), String> {
    let text = fs::read_to_string(previous_path)
        .map_err(|e| format!("read {}: {e}", previous_path.display()))?;
    let previous: Value = serde_json::from_str(&text)
        .map_err(|e| format!("parse {}: {e}", previous_path.display()))?;
    let comparison = compare_reports(&previous, report)
        .map_err(|e| format!("compare with {}: {e}", previous_path.display()))?;

    let compare_path = args.output.join("compare.json");
    fs::write(
        &compare_path,
        serde_json::to_string_pretty(&comparison.to_json())
            .map_err(|e| format!("serialize comparison: {e}"))?,
    )
    .map_err(|e| format!("write {}: {e}", compare_path.display()))?;
    println!("{}", comparison.summary());

    let Some(previous_render) = &args.compare_test else {
        println!("[compare] no --compare-test <dir>: before/after contact sheets skipped");
        return Ok(());
    };
    let ordinals: BTreeMap<u64, (usize, f32)> = report["per_frame"]
        .as_array()
        .into_iter()
        .flatten()
        .filter_map(|f| {
            Some((
                f["film_tick"].as_u64()?,
                (
                    usize::try_from(f["ordinal"].as_u64()?).ok()?,
                    f["fade_level"].as_f64()? as f32,
                ),
            ))
        })
        .collect();
    let picks = [
        ("regressed", comparison.regressed.first()),
        ("improved", comparison.improved.first()),
    ];
    for (label, pick) in picks {
        let Some(delta) = pick else {
            println!("[compare] no {label} frame: sheet skipped");
            continue;
        };
        let (ordinal, fade) = ordinals.get(&delta.film_tick).copied().ok_or_else(|| {
            format!(
                "film_tick {} missing from the fresh report",
                delta.film_tick
            )
        })?;
        let tick = usize::try_from(delta.film_tick).map_err(|e| e.to_string())?;
        let before_png = previous_render.join(crate::tick_png_name(tick));
        if !before_png.is_file() {
            println!(
                "[compare] {} not found: {label} sheet skipped",
                before_png.display()
            );
            continue;
        }
        let (reference_file, palette_file) =
            reference_paths(&args.reference, &frames[ordinal - 1], ordinal);
        let (indices, palette) = load_reference(&reference_file, &palette_file)?;
        let reference = reference_luminance(&indices, &palette);
        // Compensated comparisons show both renders as scored, at the fresh frame's fade.
        let scale = if comparison.basis == CompareBasis::Compensated {
            fade
        } else {
            1.0
        };
        let scaled = |mut plane: Vec<f32>| {
            plane.iter_mut().for_each(|v| *v *= scale);
            plane
        };
        let before = scaled(load_render_rescaled(&before_png)?);
        let after = scaled(load_render_rescaled(
            &args.test.join(crate::tick_png_name(tick)),
        )?);
        let path = args
            .output
            .join(format!("compare_{label}_tick_{tick:05}.png"));
        write_panel_sheet(
            &path,
            &[
                &reference,
                &before,
                &after,
                &abs_difference(&reference, &before),
                &abs_difference(&reference, &after),
            ],
        )?;
        println!("[compare] wrote {}", path.display());
    }
    Ok(())
}

/// Per-frame SSIM change between two reports, matched by `film_tick`.
#[derive(Debug, Clone, Copy, PartialEq)]
struct FrameDelta {
    film_tick: u64,
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
    /// `ssim_compensated` over frames scored in both reports.
    Compensated,
    /// Raw `ssim` over every common frame (a report predates fade scoring).
    Raw,
}

/// Result of [`compare_reports`].
#[derive(Debug, Clone, PartialEq)]
struct Comparison {
    basis: CompareBasis,
    /// Frames (by `film_tick`) present in both reports.
    common: usize,
    before_only: usize,
    after_only: usize,
    ssim: MeanChange,
    iou: MeanChange,
    /// Up to [`COMPARE_TOP`] frames with the largest SSIM gain, best first.
    improved: Vec<FrameDelta>,
    /// Up to [`COMPARE_TOP`] frames with the largest SSIM loss, worst first.
    regressed: Vec<FrameDelta>,
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
    /// `(ssim_compensated, scored)`, absent in reports that predate fade scoring.
    compensated: Option<(f64, bool)>,
}

/// Per-`film_tick` frames of a parsed report.
struct ReportScores {
    frames: BTreeMap<u64, ReportFrame>,
    /// Whether every entry carries the fade-scoring fields.
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
        let compensated = frame
            .get("ssim_compensated")
            .and_then(Value::as_f64)
            .zip(frame.get("scored").and_then(Value::as_bool));
        fade_aware &= compensated.is_some();
        scores.entry(film_tick).or_insert(ReportFrame {
            ssim: field("ssim")?,
            iou: field("iou")?,
            compensated,
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
/// reports carry fade scoring, the compensated SSIM of frames scored in both is compared;
/// otherwise the raw SSIM of every common frame.
fn compare_reports(before: &Value, after: &Value) -> Result<Comparison, String> {
    let (before_report, after_report) = (report_scores(before)?, report_scores(after)?);
    let basis = if before_report.fade_aware && after_report.fade_aware {
        CompareBasis::Compensated
    } else {
        CompareBasis::Raw
    };
    // `(ssim, iou)` of the frames the basis counts.
    let counted = |report: &ReportScores| -> BTreeMap<u64, (f64, f64)> {
        report
            .frames
            .iter()
            .filter_map(|(tick, f)| match (basis, f.compensated) {
                (CompareBasis::Raw, _) => Some((*tick, (f.ssim, f.iou))),
                (CompareBasis::Compensated, Some((ssim, true))) => Some((*tick, (ssim, f.iou))),
                (CompareBasis::Compensated, _) => None,
            })
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
            CompareBasis::Raw => "the reports share no film_tick".to_string(),
            CompareBasis::Compensated => {
                "the reports share no film_tick scored in both".to_string()
            }
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
    fn summary(&self) -> String {
        use std::fmt::Write as _;

        let mut out = String::new();
        let (basis, both) = match self.basis {
            CompareBasis::Compensated => (
                "compensated SSIM over frames scored in both runs",
                "scored in both reports",
            ),
            CompareBasis::Raw => (
                "raw SSIM (a report predates fade scoring)",
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
    fn to_json(&self) -> Value {
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
                CompareBasis::Compensated => "compensated",
                CompareBasis::Raw => "raw",
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

/// Reads the film clock of every captured frame.
///
/// A frame without an integer `film_tick` means the capture predates film-clock tagging;
/// there is no safe way to align it with a render, so the whole run is rejected.
fn read_film_ticks(frames: &[Value], meta_path: &Path) -> Result<Vec<usize>, String> {
    frames
        .iter()
        .enumerate()
        .map(|(position, frame)| {
            frame
                .get("film_tick")
                .and_then(Value::as_u64)
                .and_then(|tick| usize::try_from(tick).ok())
                .ok_or_else(|| {
                    format!(
                        "{} frame {} has no film_tick: the capture predates film-clock tagging                          and must be recaptured (mise run capture-ref)",
                        meta_path.display(),
                        position + 1
                    )
                })
        })
        .collect()
}

/// Reads a 64000-byte Mode 13h palette-index raster.
fn read_index_plane(path: &Path) -> Result<Vec<u8>, String> {
    let bytes = fs::read(path).map_err(|e| format!("read {}: {e}", path.display()))?;
    let expected = MODE13H_WIDTH * MODE13H_HEIGHT;
    if bytes.len() != expected {
        return Err(format!(
            "{} holds {} bytes, expected {expected}",
            path.display(),
            bytes.len()
        ));
    }
    Ok(bytes)
}

/// Reads a 256-entry RGB palette written by the capture harness.
fn read_palette(path: &Path) -> Result<Palette, String> {
    let text = fs::read_to_string(path).map_err(|e| format!("read {}: {e}", path.display()))?;
    let raw: Vec<[i64; 3]> =
        serde_json::from_str(&text).map_err(|e| format!("parse {}: {e}", path.display()))?;
    if raw.len() != 256 {
        return Err(format!(
            "{} holds {} palette entries, expected 256",
            path.display(),
            raw.len()
        ));
    }
    Ok(raw
        .into_iter()
        .map(|entry| (entry[0] as u8, entry[1] as u8, entry[2] as u8))
        .collect())
}

/// Reads a rendered PNG and reduces it to a 320x200 luminance plane.
fn read_png_luminance(path: &Path) -> Result<Vec<f32>, String> {
    let image = image::open(path).map_err(|e| format!("read {}: {e}", path.display()))?;
    let rgba = image.into_rgba8();
    if rgba.width() as usize != MODE13H_WIDTH || rgba.height() as usize != MODE13H_HEIGHT {
        return Err(format!(
            "{} is {}x{}, expected {MODE13H_WIDTH}x{MODE13H_HEIGHT}",
            path.display(),
            rgba.width(),
            rgba.height()
        ));
    }
    Ok(rgba_to_luminance(rgba.as_raw()))
}

/// Modal palette index across the top four rows of the first reference frame.
fn sky_index(first_frame: Option<&Value>, reference_dir: &Path) -> Result<u8, String> {
    let frame = first_frame.ok_or("reference meta.json carries no frames")?;
    let name = frame
        .get("frame_file")
        .and_then(Value::as_str)
        .ok_or("first reference frame has no frame_file")?;
    let indices = read_index_plane(&reference_dir.join(name))?;

    let mut counts = [0usize; 256];
    for row in 0..4 {
        let start = row * MODE13H_WIDTH;
        for &index in &indices[start..start + MODE13H_WIDTH] {
            counts[index as usize] += 1;
        }
    }
    let (index, _count) = counts
        .iter()
        .enumerate()
        .max_by_key(|&(position, count)| (*count, std::cmp::Reverse(position)))
        .ok_or("empty sky histogram")?;
    Ok(index as u8)
}

/// Intersection-over-union of the non-sky masks of both frames.
fn mask_iou(
    reference_indices: &[u8],
    sky_index: u8,
    test_luminance: &[f32],
    clear_luminance: f32,
) -> f32 {
    let mut intersection = 0usize;
    let mut union = 0usize;
    for (index, luminance) in reference_indices.iter().zip(test_luminance.iter()) {
        let reference_filled = *index != sky_index;
        let test_filled = (*luminance - clear_luminance).abs() > 0.5;
        if reference_filled && test_filled {
            intersection += 1;
        }
        if reference_filled || test_filled {
            union += 1;
        }
    }
    if union == 0 {
        1.0
    } else {
        intersection as f32 / union as f32
    }
}

/// Absolute per-pixel difference of two equally sized luminance planes.
fn abs_difference(a: &[f32], b: &[f32]) -> Vec<f32> {
    a.iter().zip(b).map(|(x, y)| (x - y).abs()).collect()
}

/// Writes a `reference | test | |difference|` contact sheet for one frame.
fn write_contact_sheet(
    out_dir: &Path,
    ordinal: usize,
    reference: &[f32],
    test: &[f32],
) -> Result<(), String> {
    let path = out_dir.join(format!("contact_{ordinal:04}.png"));
    write_panel_sheet(&path, &[reference, test, &abs_difference(reference, test)])
}

/// Writes aspect-corrected luminance panels side by side, separated by
/// [`CONTACT_SHEET_GAP`] pixels, as one grayscale PNG.
fn write_panel_sheet(path: &Path, panels: &[&[f32]]) -> Result<(), String> {
    let width = MODE13H_WIDTH;
    let height = ASPECT_CORRECTED_HEIGHT;
    let panel_stride = width + CONTACT_SHEET_GAP;
    let sheet_width = panel_stride * panels.len() - CONTACT_SHEET_GAP;
    let mut buffer = vec![0u8; sheet_width * height];

    for (panel_index, panel) in panels.iter().enumerate() {
        for y in 0..height {
            let row = y * sheet_width + panel_index * panel_stride;
            for x in 0..width {
                buffer[row + x] = panel[y * width + x].clamp(0.0, 255.0) as u8;
            }
        }
    }

    let image = image::GrayImage::from_raw(sheet_width as u32, height as u32, buffer)
        .ok_or("failed to build contact sheet buffer")?;
    image
        .save(path)
        .map_err(|e| format!("write {}: {e}", path.display()))
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Scratch directory removed on drop.
    struct TempDir(PathBuf);

    impl TempDir {
        fn new(name: &str) -> Self {
            let path =
                std::env::temp_dir().join(format!("stunt_parity_{name}_{}", std::process::id()));
            let _ = fs::remove_dir_all(&path);
            fs::create_dir_all(&path).expect("create temp dir");
            Self(path)
        }

        fn join(&self, name: &str) -> PathBuf {
            self.0.join(name)
        }
    }

    impl Drop for TempDir {
        fn drop(&mut self) {
            let _ = fs::remove_dir_all(&self.0);
        }
    }

    /// Writes a synthetic reference set with one capture per `film_ticks` entry, or no
    /// `film_tick` fields at all when `tag` is false.
    fn write_reference(dir: &Path, film_ticks: &[u64], tag: bool) {
        write_reference_faded(dir, film_ticks, tag, &vec![1.0; film_ticks.len()]);
    }

    /// Index plane of the synthetic captures: a black sky over bright static entries.
    fn plane_index(i: usize) -> u8 {
        if i < MODE13H_WIDTH * 4 {
            0
        } else {
            (i % 7) as u8 + 200
        }
    }

    /// The static palette with every channel scaled by `scale`.
    fn scaled_palette(scale: f32) -> Vec<(u8, u8, u8)> {
        let channel = |v: u8| (f32::from(v) * scale).round() as u8;
        (0..=255u8)
            .map(|i| {
                let (r, g, b) = get_palette_rgb(i);
                (channel(r), channel(g), channel(b))
            })
            .collect()
    }

    /// Like [`write_reference`], with capture `n`'s palette faded to `scales[n]`.
    fn write_reference_faded(dir: &Path, film_ticks: &[u64], tag: bool, scales: &[f32]) {
        fs::create_dir_all(dir).unwrap();
        let mut frames = Vec::new();
        for (position, film_tick) in film_ticks.iter().enumerate() {
            let ordinal = position + 1;
            let palette: Vec<[u8; 3]> = scaled_palette(scales[position])
                .into_iter()
                .map(|(r, g, b)| [r, g, b])
                .collect();
            let palette_json = serde_json::to_string(&palette).unwrap();
            let plane: Vec<u8> = (0..MODE13H_WIDTH * MODE13H_HEIGHT)
                .map(plane_index)
                .collect();
            fs::write(dir.join(format!("tick_{ordinal:04}.idx")), plane).unwrap();
            fs::write(
                dir.join(format!("palettes_{ordinal:04}.json")),
                &palette_json,
            )
            .unwrap();
            let mut frame = json!({
                "ordinal": ordinal,
                "frame_file": format!("tick_{ordinal:04}.idx"),
                "palette_file": format!("palettes_{ordinal:04}.json"),
            });
            if tag {
                frame["film_tick"] = json!(film_tick);
                frame["global_tick"] = json!(film_tick - 5);
            }
            frames.push(frame);
        }
        fs::write(
            dir.join("meta.json"),
            json!({ "frames": frames }).to_string(),
        )
        .unwrap();
    }

    fn write_render(path: &Path) {
        let image =
            image::RgbaImage::from_fn(MODE13H_WIDTH as u32, MODE13H_HEIGHT as u32, |x, y| {
                let v = ((x + y) % 251) as u8;
                image::Rgba([v, v, v, 255])
            });
        image.save(path).unwrap();
    }

    /// Writes the unfaded view of the synthetic capture planes as a render.
    fn write_matching_render(path: &Path) {
        let image =
            image::RgbaImage::from_fn(MODE13H_WIDTH as u32, MODE13H_HEIGHT as u32, |x, y| {
                let (r, g, b) =
                    get_palette_rgb(plane_index(y as usize * MODE13H_WIDTH + x as usize));
                image::Rgba([r, g, b, 255])
            });
        image.save(path).unwrap();
    }

    fn run_parity(reference: &Path, test: &Path, output: &Path) -> Result<(), String> {
        run(vec![
            "--reference".to_string(),
            reference.display().to_string(),
            "--test".to_string(),
            test.display().to_string(),
            "--output".to_string(),
            output.display().to_string(),
        ]
        .into_iter())
    }

    fn read_report(output: &Path) -> Value {
        let text = fs::read_to_string(output.join("report.json")).unwrap();
        serde_json::from_str(&text).unwrap()
    }

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
    /// `(film_tick, ssim, ssim_compensated, iou, scored)`.
    fn fade_report(frames: &[(u64, f64, f64, f64, bool)]) -> Value {
        json!({
            "per_frame": frames
                .iter()
                .enumerate()
                .map(|(i, (tick, ssim, compensated, iou, scored))| json!({
                    "ordinal": i + 1, "film_tick": tick, "ssim": ssim, "iou": iou,
                    "ssim_compensated": compensated, "fade_level": 1.0, "scored": scored,
                }))
                .collect::<Vec<Value>>(),
        })
    }

    #[test]
    fn fade_level_is_one_for_the_static_palette_and_tracks_the_scale() {
        let all: Vec<u8> = (0..=255).collect();
        let set = fade_reference_set(&all);
        assert!(!set.is_empty());
        assert!((fade_level(&set, &scaled_palette(1.0)) - 1.0).abs() < 1e-6);
        assert!((fade_level(&set, &scaled_palette(0.5)) - 0.5).abs() < 0.02);
        assert_eq!(fade_level(&[], &scaled_palette(0.5)), 1.0);
    }

    #[test]
    fn fade_level_median_ignores_outlier_entries() {
        let set = [200u8, 201, 202, 203, 204];
        let mut palette = scaled_palette(0.5);
        // Two unfading (UI-like) entries and one blacked out: the median stays put.
        palette[200] = get_palette_rgb(200);
        palette[201] = get_palette_rgb(201);
        palette[204] = (0, 0, 0);
        assert!((fade_level(&set, &palette) - 0.5).abs() < 0.02);
        // An even count averages the two middle values.
        let even = [200u8, 201, 202, 203];
        let mut palette = scaled_palette(0.2);
        palette[202] = scaled_palette(0.4)[202];
        palette[203] = scaled_palette(0.4)[203];
        assert!((fade_level(&even, &palette) - 0.3).abs() < 0.02);
    }

    #[test]
    fn fade_reference_set_keeps_only_present_bright_static_entries() {
        let indices = [0u8, 0, 1, 200, 200, 201];
        let set = fade_reference_set(&indices);
        assert!(set.iter().all(|&i| indices.contains(&i)));
        assert!(set.iter().all(|&i| rgb_sum(get_palette_rgb(i)) > 60));
        assert!(set.contains(&200) && set.contains(&201));
        let dark = (0..=255u8)
            .find(|&i| rgb_sum(get_palette_rgb(i)) <= 60)
            .unwrap();
        assert!(fade_reference_set(&[dark]).is_empty());
    }

    #[test]
    fn min_fade_level_flag_parses_defaults_and_rejects_bad_values() {
        let parse = |extra: &[&str]| {
            let mut v: Vec<String> = ["--reference", "r", "--test", "t", "--output", "o"]
                .iter()
                .map(|s| (*s).to_string())
                .collect();
            v.extend(extra.iter().map(|s| (*s).to_string()));
            Args::parse(v.into_iter())
        };
        assert_eq!(parse(&[]).unwrap().min_fade_level, 0.25);
        assert_eq!(
            parse(&["--min-fade-level", "0.5"]).unwrap().min_fade_level,
            0.5
        );
        assert_eq!(
            parse(&["--min-fade-level", "0"]).unwrap().min_fade_level,
            0.0
        );
        for bad in ["-0.1", "NaN", "inf", "abc"] {
            let error = parse(&["--min-fade-level", bad]).unwrap_err();
            assert!(error.contains("min fade level"), "{bad}: {error}");
        }
        assert!(parse(&["--min-fade-level"]).is_err());
    }

    #[test]
    fn faded_frames_below_the_floor_are_reported_but_not_scored() {
        let tmp = TempDir::new("faded");
        write_reference_faded(&tmp.join("ref"), &[7, 12, 20], true, &[1.0, 0.5, 0.1]);
        let test = tmp.join("test");
        fs::create_dir_all(&test).unwrap();
        for tick in [7, 12, 20] {
            write_matching_render(&test.join(crate::tick_png_name(tick)));
        }

        run_parity(&tmp.join("ref"), &test, &tmp.join("out")).expect("parity runs");
        let report = read_report(&tmp.join("out"));
        assert_eq!(report["scored_frames"], 2);
        assert_eq!(report["excluded_frames"], 1);
        assert_eq!(report["min_fade_level"], 0.25);
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
        // The render matches the unfaded reference, so scaling it by the fade helps.
        let half = &per_frame[1];
        assert!(half["ssim_compensated"].as_f64() > half["ssim"].as_f64());
        // Raw means span all matched frames; the scored means only the first two.
        let mean_scored = (per_frame[0]["ssim_compensated"].as_f64().unwrap()
            + half["ssim_compensated"].as_f64().unwrap())
            / 2.0;
        assert!((report["mean_ssim_compensated"].as_f64().unwrap() - mean_scored).abs() < 1e-5);
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
        write_matching_render(&test.join(crate::tick_png_name(7)));

        run_parity(&tmp.join("ref"), &test, &tmp.join("out")).expect("parity runs");
        let report = read_report(&tmp.join("out"));
        assert_eq!(report["scored_frames"], 0);
        assert_eq!(report["excluded_frames"], 1);
        assert!(report["mean_ssim_compensated"].is_null());
        assert!(report["mean_iou_scored"].is_null());
        assert_eq!(report["per_frame"][0]["scored"], false);
    }

    #[test]
    fn compare_uses_compensated_ssim_over_frames_scored_in_both() {
        let before = fade_report(&[
            (10, 0.2, 0.5, 0.8, true),
            (20, 0.2, 0.6, 0.8, true),
            (30, 0.9, 0.9, 0.8, false),
        ]);
        let after = fade_report(&[
            (10, 0.2, 0.7, 0.9, true),
            (20, 0.2, 0.1, 0.9, false),
            (30, 0.9, 0.9, 0.9, true),
            (40, 0.5, 0.5, 0.9, true),
        ]);
        let c = compare_reports(&before, &after).expect("comparable");
        assert_eq!(c.basis, CompareBasis::Compensated);
        // Only tick 10 is scored in both; 20 and 30 are scored on one side only.
        assert_eq!((c.common, c.before_only, c.after_only), (1, 1, 2));
        assert!((c.ssim.before - 0.5).abs() < 1e-9);
        assert!((c.ssim.after - 0.7).abs() < 1e-9);
        assert!((c.iou.before - 0.8).abs() < 1e-9);
        assert!((c.iou.after - 0.9).abs() < 1e-9);
        assert_eq!(c.to_json()["basis"], "compensated");
        let text = c.summary();
        assert!(text.starts_with("[compare] basis: compensated"), "{text}");
        assert!(text.contains("1 frame(s) scored in both reports"), "{text}");
    }

    #[test]
    fn compare_falls_back_to_raw_when_a_report_predates_fade_scoring() {
        let old = report(&[(10, 0.5, 0.8), (20, 0.6, 0.8)]);
        let new = fade_report(&[(10, 0.7, 0.99, 0.9, true), (20, 0.8, 0.1, 0.9, false)]);
        for (before, after) in [(&old, &new), (&new, &old)] {
            let c = compare_reports(before, after).expect("comparable");
            assert_eq!(c.basis, CompareBasis::Raw);
            assert_eq!(c.common, 2);
            assert_eq!(c.to_json()["basis"], "raw");
            let text = c.summary();
            assert!(text.starts_with("[compare] basis: raw SSIM"), "{text}");
            assert!(text.contains("2 frame(s) in both reports"), "{text}");
        }
        let c = compare_reports(&old, &new).unwrap();
        assert!((c.ssim.before - 0.55).abs() < 1e-9);
        assert!((c.ssim.after - 0.75).abs() < 1e-9);
        // A report with a partial set of the new fields is old-style too.
        let partial = json!({ "per_frame": [
            { "film_tick": 10, "ssim": 0.5, "iou": 0.5, "ssim_compensated": 0.5, "scored": true },
            { "film_tick": 20, "ssim": 0.5, "iou": 0.5 },
        ]});
        assert_eq!(
            compare_reports(&partial, &new).unwrap().basis,
            CompareBasis::Raw
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

    #[test]
    fn compare_flags_parse_and_compare_test_needs_compare() {
        let parse = |extra: &[&str]| {
            let mut v: Vec<String> = ["--reference", "r", "--test", "t", "--output", "o"]
                .iter()
                .map(|s| (*s).to_string())
                .collect();
            v.extend(extra.iter().map(|s| (*s).to_string()));
            Args::parse(v.into_iter())
        };
        let args = parse(&["--compare", "p/report.json", "--compare-test", "p/ours"]).unwrap();
        assert_eq!(args.compare.as_deref(), Some(Path::new("p/report.json")));
        assert_eq!(args.compare_test.as_deref(), Some(Path::new("p/ours")));
        assert!(parse(&[]).unwrap().compare.is_none());
        assert!(
            parse(&["--compare-test", "p"])
                .unwrap_err()
                .contains("--compare")
        );
    }

    #[test]
    fn compare_run_writes_compare_json_and_before_after_sheets() {
        let tmp = TempDir::new("compare_run");
        write_reference(&tmp.join("ref"), &[7, 12], true);
        let previous = tmp.join("prev");
        let current = tmp.join("cur");
        fs::create_dir_all(&previous).unwrap();
        fs::create_dir_all(&current).unwrap();
        for tick in [7, 12] {
            write_render(&previous.join(crate::tick_png_name(tick)));
            write_render(&current.join(crate::tick_png_name(tick)));
        }
        // Make the fresh render of tick 12 match the capture, which scores higher.
        write_matching_render(&current.join(crate::tick_png_name(12)));

        run_parity(&tmp.join("ref"), &previous, &tmp.join("base")).expect("baseline");
        let argv = |compare_test: bool| {
            let mut v = vec![
                "--reference".to_string(),
                tmp.join("ref").display().to_string(),
                "--test".to_string(),
                current.display().to_string(),
                "--output".to_string(),
                tmp.join("out").display().to_string(),
                "--compare".to_string(),
                tmp.join("base").join("report.json").display().to_string(),
            ];
            if compare_test {
                v.push("--compare-test".to_string());
                v.push(previous.display().to_string());
            }
            v
        };

        run(argv(false).into_iter()).expect("compare without sheets");
        assert!(tmp.join("out").join("compare.json").is_file());
        assert!(
            !tmp.join("out")
                .join("compare_improved_tick_00012.png")
                .exists()
        );

        run(argv(true).into_iter()).expect("compare with sheets");
        let doc: Value = serde_json::from_str(
            &fs::read_to_string(tmp.join("out").join("compare.json")).unwrap(),
        )
        .unwrap();
        assert_eq!(doc["common_frames"], 2);
        assert_eq!(doc["most_improved"][0]["film_tick"], 12);
        let sheet = image::open(tmp.join("out").join("compare_improved_tick_00012.png")).unwrap();
        assert_eq!(
            sheet.width() as usize,
            (MODE13H_WIDTH + CONTACT_SHEET_GAP) * 5 - CONTACT_SHEET_GAP
        );
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
    fn one_untagged_frame_rejects_the_whole_capture() {
        let tmp = TempDir::new("partial");
        write_reference(&tmp.join("ref"), &[7, 12], true);
        let meta_path = tmp.join("ref").join("meta.json");
        let mut meta: Value =
            serde_json::from_str(&fs::read_to_string(&meta_path).unwrap()).unwrap();
        meta["frames"][1]
            .as_object_mut()
            .unwrap()
            .remove("film_tick");
        fs::write(&meta_path, meta.to_string()).unwrap();

        let frames = meta["frames"].as_array().unwrap();
        let error = read_film_ticks(frames, &meta_path).expect_err("second frame is untagged");
        assert!(error.contains("frame 2"), "{error}");
    }

    #[test]
    fn frames_match_renders_by_film_tick() {
        let tmp = TempDir::new("matched");
        write_reference(&tmp.join("ref"), &[7, 12], true);
        let test = tmp.join("test");
        fs::create_dir_all(&test).unwrap();
        write_render(&test.join(crate::tick_png_name(7)));
        write_render(&test.join(crate::tick_png_name(12)));
        // Neighbouring ticks and the old ordinal names must never be picked up.
        write_render(&test.join("tick_00001.png"));
        write_render(&test.join("frame_0001.png"));

        run_parity(&tmp.join("ref"), &test, &tmp.join("out")).expect("parity runs");
        let report = read_report(&tmp.join("out"));
        assert_eq!(report["frames"], 2);
        assert_eq!(report["unmatched"], 0);
        assert!(report.get("tick_to_frame_offset").is_none());
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
}
