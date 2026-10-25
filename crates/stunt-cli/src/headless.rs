//! Offscreen playback: a single PNG, an `--out-dir` tick or sample sequence, or an ffmpeg video.

use std::fs;
use std::path::{Path, PathBuf};

use stunt_core::flm::{CAMERA_FORWARD, TIMELINE_HZ, TIMELINE_TICK_SECONDS};
use stunt_core::scene::FilmScene;
use stunt_parity::Geometry;
use stunt_render::{FfmpegVideoWriter, HeadlessRenderer, SceneRenderer};

use crate::config::CliConfig;
use crate::parity_artifacts::{RenderJournal, film_identity};

/// Evenly spaced ticks covering the half-open range `[start_tick, end_tick)`,
/// including the first tick and the final tick in the range.
///
/// Used by `--sample-count` so the final authored tick is represented.
fn even_sample_ticks(start_tick: usize, end_tick: usize, count: usize) -> Vec<f32> {
    let span = end_tick.saturating_sub(start_tick).max(1);
    let last_offset = span.saturating_sub(1) as f32;
    let divisor = count.saturating_sub(1).max(1) as f32;
    (0..count)
        .map(|index| {
            let offset = if count > 1 {
                index as f32 * last_offset / divisor
            } else {
                0.0
            };
            start_tick as f32 + offset
        })
        .collect()
}

/// Identifies one rendered sample in `--out-dir` output.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum SampleKey {
    /// A whole 0-based 50 Hz tick, as in `PLAYONE.EXE`'s film clock.
    Tick(usize),
    /// 1-based position among evenly spaced or video-rate samples, which need not
    /// fall on a whole tick.
    Index(usize),
}

impl std::fmt::Display for SampleKey {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Tick(tick) => write!(f, "tick {tick}"),
            Self::Index(index) => write!(f, "sample {index}"),
        }
    }
}

/// File name `parity` looks up for the render of 0-based 50 Hz `tick`.
pub(crate) fn tick_png_name(tick: usize) -> String {
    format!("tick_{tick:05}.png")
}

/// Writes the index and layer planes beside `png_path` as `<stem>.idx` (one palette-index
/// byte per pixel, before lighting) and `<stem>.layer` (one little-endian `u16` layer id per
/// pixel; see `stunt_render::LAYER_OCEAN`).
fn write_planes(png_path: &Path, plane: &[u32]) -> Result<(), String> {
    let indices: Vec<u8> = plane.iter().map(|&p| (p & 0xFF) as u8).collect();
    let layers: Vec<u8> = plane
        .iter()
        .flat_map(|&p| ((p >> 8) as u16).to_le_bytes())
        .collect();
    for (extension, bytes) in [("idx", indices), ("layer", layers)] {
        let path = png_path.with_extension(extension);
        std::fs::write(&path, bytes).map_err(|e| format!("write {}: {e}", path.display()))?;
    }
    Ok(())
}

/// File name written under `--out-dir` for a rendered sample.
fn sample_png_name(key: SampleKey) -> String {
    match key {
        SampleKey::Tick(tick) => tick_png_name(tick),
        SampleKey::Index(index) => format!("sample_{index:04}.png"),
    }
}

/// The authored tick count, capped by `--ticks`.
pub(crate) fn playback_ticks(config: &CliConfig, scene: &FilmScene) -> u32 {
    let total = scene.timeline().total_ticks();
    config
        .max_ticks
        .map_or(total, |limit| u32::try_from(limit).unwrap_or(u32::MAX))
        .min(total)
}

/// Resolves `--frames` against a film of `total_ticks` into 0-based tick bounds.
///
/// Returns `(start_tick, tick_end, span_end)`. Tick-per-PNG output renders
/// `start_tick..tick_end`, and with no `--frames` that is `0..=total_ticks`: the film clock
/// reaches `total_ticks` itself, so the end-hold captures need that render. Video and
/// `--sample-count` sample `start_tick..span_end`, which stops at the authored length.
fn tick_window(frame_range: Option<(usize, usize)>, total_ticks: usize) -> (usize, usize, usize) {
    let (start_ord, end_ord) = frame_range.unwrap_or((1, total_ticks + 2));
    let start_tick = start_ord.max(1) - 1;
    let tick_end = end_ord
        .saturating_sub(1)
        .min(total_ticks + 1)
        .max(start_tick + 1);
    let span_end = tick_end.min(total_ticks).max(start_tick + 1);
    (start_tick, tick_end, span_end)
}

/// Saves tightly packed RGBA8 bytes as a PNG.
fn save_rgba_png(
    path: &std::path::Path,
    width: u32,
    height: u32,
    rgba: &[u8],
) -> Result<(), String> {
    image::save_buffer(path, rgba, width, height, image::ColorType::Rgba8)
        .map_err(|e| format!("save {}: {e}", path.display()))
}

/// Executes headless rendering without window creation.
pub(crate) fn run_headless(config: &CliConfig, scene: &FilmScene) -> Result<(), String> {
    println!("[stuntreel] Starting headless offscreen presentation...");

    if let Some(out_dir) = &config.out_dir {
        fs::create_dir_all(out_dir)
            .map_err(|e| format!("create output directory {}: {e}", out_dir.display()))?;
    }

    let total_ticks = playback_ticks(config, scene) as usize;
    let (start_tick, tick_end, span_end) = tick_window(config.frame_range, total_ticks);
    let span_seconds = (span_end - start_tick) as f32 * TIMELINE_TICK_SECONDS;

    let mut video_writer = if let Some(video_path) = &config.video_path {
        if !FfmpegVideoWriter::is_available() {
            return Err("ffmpeg executable not found on PATH. Video export requires ffmpeg (https://ffmpeg.org). Please install ffmpeg or add it to PATH.".to_string());
        }
        let writer = FfmpegVideoWriter::open_with_duration(
            video_path,
            config.width,
            config.height,
            config.fps,
            Some(span_seconds),
        )
        .map_err(|e| format!("Failed to open video writer: {e}"))?;
        Some(writer)
    } else {
        None
    };

    let mut renderer = HeadlessRenderer::with_dimensions(config.width, config.height)
        .map_err(|e| format!("Headless renderer failed: {e}"))?;
    renderer.viewport_rows = config.viewport_rows;
    let mut scene_renderer = SceneRenderer::new(
        &renderer.device,
        &renderer.queue,
        &renderer.pipelines,
        scene,
    );
    println!(
        "[stuntreel] camera forward: {}",
        if CAMERA_FORWARD[2] < 0.0 { "-Z" } else { "+Z" }
    );

    if config.out_dir.is_none() && video_writer.is_none() {
        let output_path = config
            .output_png
            .clone()
            .unwrap_or_else(|| PathBuf::from("stuntreel_capture.png"));

        let frame = scene.frame(start_tick as f32);
        let cam = frame.camera;
        println!(
            "[stuntreel] tick {start_tick} camera: eye={:?}, target={:?}, fov={}; {} actor draws",
            cam.eye,
            cam.target,
            cam.fov_degrees,
            frame.actors.len()
        );
        let rgba = renderer
            .render_scene(&mut scene_renderer, &frame, None, Some(config.clear_index))
            .map_err(|e| format!("Offscreen render to PNG failed: {e}"))?;
        save_rgba_png(&output_path, config.width, config.height, &rgba)?;

        println!(
            "[stuntreel] Headless frame successfully saved to {}",
            output_path.display()
        );
        return Ok(());
    }

    let frame_step = config.frame_step.max(1);

    let mut samples: Vec<(SampleKey, f32)> = Vec::new();
    if video_writer.is_some() {
        let count = (span_seconds * config.fps).ceil() as usize;
        let tick_step = TIMELINE_HZ / config.fps;
        for index in 0..count {
            let tick = start_tick as f32 + index as f32 * tick_step;
            if tick >= span_end as f32 {
                break;
            }
            samples.push((SampleKey::Index(index + 1), tick));
        }
    } else if let Some(count) = config.sample_count {
        for (index, tick) in even_sample_ticks(start_tick, span_end, count)
            .into_iter()
            .enumerate()
        {
            samples.push((SampleKey::Index(index + 1), tick));
        }
    } else {
        for tick in (start_tick..tick_end).step_by(frame_step) {
            samples.push((SampleKey::Tick(tick), tick as f32));
        }
    }

    let mut render_journal = config.out_dir.as_ref().map(|dir| {
        RenderJournal::begin(
            dir,
            film_identity(config.flm_path.as_deref()),
            Geometry {
                width: config.width,
                height: config.height,
                viewport_rows: config.viewport_rows,
            },
        )
    });

    let mut written_pngs = 0usize;
    let mut written_video_frames = 0usize;

    for (key, tick) in samples {
        // `PLAYONE` advances the film clock at the start of a frame and the capture reads the
        // clock and the displayed page at the same post-retrace trap, so the page captured for
        // film clock `t` is the state at `t - 1`. Rendering the page one tick early matches the
        // capture on both films (CTRY 0.7713 -> 0.7732, INTRO 0.6775 -> 0.6793 when the renders
        // are shifted, research/playone-exe/capture.md).
        let frame = scene.frame((tick - 1.0).max(0.0));
        if let (Some(journal), SampleKey::Tick(tick)) = (render_journal.as_mut(), key)
            && let Ok(tick) = u32::try_from(tick)
        {
            journal.record(tick, &frame);
        }
        let (rgba_bytes, plane) = renderer
            .render_scene_with_plane(&mut scene_renderer, &frame, None, Some(config.clear_index))
            .map_err(|e| format!("render {key}: {e}"))?;

        if let Some(out_dir) = &config.out_dir {
            let frame_path = out_dir.join(sample_png_name(key));
            save_rgba_png(&frame_path, config.width, config.height, &rgba_bytes)
                .map_err(|e| format!("{key}: {e}"))?;
            write_planes(&frame_path, &plane).map_err(|e| format!("{key}: {e}"))?;
            written_pngs += 1;
        }
        if let Some(writer) = &mut video_writer {
            writer
                .write_frame(&rgba_bytes)
                .map_err(|e| format!("write video frame for {key}: {e}"))?;
            written_video_frames += 1;
        }
    }

    if let Some(out_dir) = &config.out_dir {
        if let Some(journal) = render_journal {
            journal.finish().map_err(|e| e.to_string())?;
        }
        println!(
            "[stuntreel] Wrote {written_pngs} parity frames to {}",
            out_dir.display()
        );
    }

    if let Some(writer) = video_writer {
        writer
            .finish()
            .map_err(|e| format!("finish video export: {e}"))?;
        if let Some(video_path) = &config.video_path {
            println!(
                "[stuntreel] Wrote {written_video_frames} frames to video {}",
                video_path.display()
            );
        }
    }

    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_out_dir_file_names_follow_tick_or_sample_index() {
        assert_eq!(sample_png_name(SampleKey::Tick(0)), "tick_00000.png");
        assert_eq!(sample_png_name(SampleKey::Tick(1341)), "tick_01341.png");
        assert_eq!(sample_png_name(SampleKey::Tick(1342)), "tick_01342.png");
        assert_eq!(sample_png_name(SampleKey::Tick(12345)), "tick_12345.png");
        assert_eq!(sample_png_name(SampleKey::Index(1)), "sample_0001.png");
        assert_eq!(sample_png_name(SampleKey::Index(140)), "sample_0140.png");
        assert_eq!(tick_png_name(7), sample_png_name(SampleKey::Tick(7)));
    }

    #[test]
    fn test_even_sample_ticks_include_endpoints() {
        assert_eq!(even_sample_ticks(0, 3, 3), vec![0.0, 1.0, 2.0]);
        assert_eq!(even_sample_ticks(0, 1342, 3), vec![0.0, 670.5, 1341.0]);
        assert_eq!(even_sample_ticks(5, 6, 1), vec![5.0]);
    }

    #[test]
    fn test_default_range_includes_the_final_tick() {
        // CTRY.FLM: 1,342 ticks, and the film clock reaches tick 1342 itself.
        assert_eq!(tick_window(None, 1342), (0, 1343, 1342));
        // The documented parity command.
        assert_eq!(tick_window(Some((1, 1344)), 1342), (0, 1343, 1342));
        // Half-open 1-based ordinals as before: 1..1343 stops at tick 1341.
        assert_eq!(tick_window(Some((1, 1343)), 1342), (0, 1342, 1342));
        assert_eq!(tick_window(Some((3, 6)), 1342), (2, 5, 5));
        // Past-the-end ranges clamp.
        assert_eq!(tick_window(Some((1, 99999)), 1342), (0, 1343, 1342));
    }
}
