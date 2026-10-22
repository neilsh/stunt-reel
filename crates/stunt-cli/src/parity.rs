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

use std::collections::BTreeSet;
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
    ssim: f32,
    iou: f32,
}

/// Parsed `stuntreel parity` arguments.
#[derive(Debug)]
struct Args {
    reference: PathBuf,
    test: PathBuf,
    output: PathBuf,
    clear_index: u8,
}

impl Args {
    fn parse(mut args: impl Iterator<Item = String>) -> Result<Self, String> {
        let mut reference = None;
        let mut test = None;
        let mut output = None;
        let mut clear_index = 180u8;

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
                "--help" | "-h" => {
                    println!(
                        "Usage: stuntreel parity --reference <dir> --test <dir> --output <dir> \
                         [--clear-index N]"
                    );
                    std::process::exit(0);
                }
                other => return Err(format!("Unrecognized parity argument: {other}")),
            }
        }

        Ok(Self {
            reference: reference.ok_or("parity requires --reference <dir>")?,
            test: test.ok_or("parity requires --test <dir>")?,
            output: output.ok_or("parity requires --output <dir>")?,
            clear_index,
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

    let mut sheet_ordinals: BTreeSet<usize> = CONTACT_SHEET_ORDINALS.iter().copied().collect();
    sheet_ordinals.insert(film_ticks.len());

    let mut scores: Vec<FrameScore> = Vec::with_capacity(frames.len());
    let mut unmatched = 0usize;
    let mut written_sheets: BTreeSet<usize> = BTreeSet::new();
    let mut worst: Vec<(f32, usize, Vec<f32>, Vec<f32>)> = Vec::new();

    for (index, frame) in frames.iter().enumerate() {
        let ordinal = index + 1;
        let film_tick = film_ticks[index];
        let reference_file = args.reference.join(
            frame
                .get("frame_file")
                .and_then(Value::as_str)
                .map_or_else(|| format!("tick_{ordinal:04}.idx"), str::to_string),
        );
        let palette_file = args.reference.join(
            frame
                .get("palette_file")
                .and_then(Value::as_str)
                .map_or_else(|| format!("palettes_{ordinal:04}.json"), str::to_string),
        );
        let test_file = args.test.join(crate::tick_png_name(film_tick));

        if !reference_file.is_file() || !palette_file.is_file() || !test_file.is_file() {
            unmatched += 1;
            continue;
        }

        let indices = read_index_plane(&reference_file)?;
        let palette = read_palette(&palette_file)?;
        let mut reference_rgb = Vec::with_capacity(MODE13H_WIDTH * MODE13H_HEIGHT * 3);
        for &index in &indices {
            let (r, g, b) = palette[index as usize];
            reference_rgb.extend_from_slice(&[r, g, b]);
        }
        let reference_luminance = rgb_to_luminance(&reference_rgb);
        let test_luminance = read_png_luminance(&test_file)?;

        let reference_rescaled = rescale_mode13h_frame(
            &reference_luminance,
            MODE13H_WIDTH,
            MODE13H_HEIGHT,
            ASPECT_CORRECTED_HEIGHT,
        );
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
        let iou = mask_iou(&indices, sky_index, &test_luminance, clear_luminance);

        scores.push(FrameScore {
            ordinal,
            film_tick,
            ssim,
            iou,
        });

        if sheet_ordinals.contains(&ordinal) {
            write_contact_sheet(&args.output, ordinal, &reference_rescaled, &test_rescaled)?;
            written_sheets.insert(ordinal);
        }

        worst.push((ssim, ordinal, reference_rescaled, test_rescaled));
        worst.sort_by(|a, b| a.0.total_cmp(&b.0));
        worst.truncate(CONTACT_SHEET_WORST);
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

    let report = json!({
        "reference_frames": frames.len(),
        "frames": scores.len(),
        "unmatched": unmatched,
        "sky_index": sky_index,
        "clear_index": args.clear_index,
        "mean_ssim": mean_ssim,
        "min_ssim": min_ssim,
        "mean_iou": mean_iou,
        "per_frame": scores
            .iter()
            .map(|s| json!({
                "ordinal": s.ordinal,
                "film_tick": s.film_tick,
                "ssim": s.ssim,
                "iou": s.iou,
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
    if unmatched > 0 {
        println!("[parity] {unmatched} frame(s) missing on one side and skipped");
    }
    Ok(())
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
fn read_palette(path: &Path) -> Result<Vec<(u8, u8, u8)>, String> {
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

/// Writes a `reference | test | |difference|` contact sheet for one frame.
fn write_contact_sheet(
    out_dir: &Path,
    ordinal: usize,
    reference: &[f32],
    test: &[f32],
) -> Result<(), String> {
    let width = MODE13H_WIDTH;
    let height = ASPECT_CORRECTED_HEIGHT;
    let panel_stride = width + CONTACT_SHEET_GAP;
    let sheet_width = panel_stride * 2 + width;
    let mut buffer = vec![0u8; sheet_width * height];

    for y in 0..height {
        let row = y * sheet_width;
        for x in 0..width {
            let pixel = y * width + x;
            buffer[row + x] = reference[pixel].clamp(0.0, 255.0) as u8;
            buffer[row + panel_stride + x] = test[pixel].clamp(0.0, 255.0) as u8;
            buffer[row + panel_stride * 2 + x] =
                (reference[pixel] - test[pixel]).abs().clamp(0.0, 255.0) as u8;
        }
    }

    let image = image::GrayImage::from_raw(sheet_width as u32, height as u32, buffer)
        .ok_or("failed to build contact sheet buffer")?;
    let path = out_dir.join(format!("contact_{ordinal:04}.png"));
    image
        .save(&path)
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
        fs::create_dir_all(dir).unwrap();
        let palette: Vec<[u8; 3]> = (0..=255u8).map(|i| [i, i, i]).collect();
        let palette_json = serde_json::to_string(&palette).unwrap();
        let mut frames = Vec::new();
        for (position, film_tick) in film_ticks.iter().enumerate() {
            let ordinal = position + 1;
            let plane: Vec<u8> = (0..MODE13H_WIDTH * MODE13H_HEIGHT)
                .map(|i| {
                    if i < MODE13H_WIDTH * 4 {
                        0
                    } else {
                        (i % 7) as u8 + 1
                    }
                })
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
