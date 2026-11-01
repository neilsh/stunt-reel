//! Offscreen playback: a single PNG, an --out-dir render store or sample sequence, or an ffmpeg
//! video.

use std::cell::RefCell;
use std::fs;
use std::path::PathBuf;
use std::rc::Rc;

use stunt_core::contracts::PaletteControls;
use stunt_core::flm::CAMERA_FORWARD;
use stunt_core::scene::{FilmScene, SceneFrame, ViewCamera};
use stunt_parity::Geometry;
use stunt_render::{
    FfmpegVideoWriter, Offscreen, PageSink, RenderOptions, RenderedPage, Renderer, SinkError,
};

use crate::config::CliConfig;
use crate::parity_artifacts::{RenderJournal, film_identity};
use crate::playback::{Playback, SampleKey, capture_tick};

/// File name written under --out-dir for an evenly spaced sample; whole ticks go to the
/// render store instead.
fn sample_png_name(index: usize) -> String {
    format!("sample_{index:04}.png")
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

/// The sink of a single --output PNG.
struct SinglePngSink {
    path: PathBuf,
}

impl PageSink for SinglePngSink {
    fn accept(&mut self, page: RenderedPage) -> Result<(), SinkError> {
        save_rgba_png(&self.path, page.width(), page.height(), page.rgba()).map_err(SinkError::new)
    }
}

/// The sink of a multi-sample run: the render store and its document for whole ticks, a PNG
/// per evenly spaced sample, and/or video frames, whichever the run asked for.
struct SampleSink {
    out_dir: Option<PathBuf>,
    video: Option<FfmpegVideoWriter>,
    journal: Option<RenderJournal>,
    pending: Option<(SampleKey, PaletteControls, ViewCamera)>,
    written_frames: usize,
    written_video_frames: usize,
}

impl SampleSink {
    /// Announces the sample the next accepted page belongs to.
    fn begin(&mut self, key: SampleKey, frame: &SceneFrame) {
        self.pending = Some((key, frame.palette, frame.view));
    }

    /// Writes one accepted page to every destination the run selected.
    fn accept_page(&mut self, page: RenderedPage) -> Result<(), SinkError> {
        let (key, controls, camera) = self
            .pending
            .take()
            .ok_or_else(|| SinkError::new("rendered a page with no planned sample"))?;
        if let Some(out_dir) = &self.out_dir {
            match key {
                SampleKey::Tick(tick) => {
                    let tick = u32::try_from(tick)
                        .map_err(|_| SinkError::new(format!("{key}: tick does not fit a u32")))?;
                    if let Some(journal) = self.journal.as_mut() {
                        journal
                            .write(tick, controls, camera, &page)
                            .map_err(|e| SinkError::new(format!("{key}: {e}")))?;
                    }
                }
                SampleKey::Index(index) => {
                    let frame_path = out_dir.join(sample_png_name(index));
                    save_rgba_png(&frame_path, page.width(), page.height(), page.rgba())
                        .map_err(|e| SinkError::new(format!("{key}: {e}")))?;
                }
            }
            self.written_frames += 1;
        }
        if let Some(writer) = &mut self.video {
            writer
                .write_frame(page.rgba())
                .map_err(|e| SinkError::new(format!("write video frame for {key}: {e}")))?;
            self.written_video_frames += 1;
        }
        Ok(())
    }

    /// Closes the render store and writes its document, if the run has one.
    fn finish_journal(&mut self) -> Result<(), String> {
        if let Some(journal) = self.journal.take() {
            journal.finish().map_err(|e| e.to_string())?;
        }
        Ok(())
    }
    /// Closes the ffmpeg video stream, if the run has one.
    fn finish_video(&mut self) -> Result<(), String> {
        if let Some(writer) = self.video.take() {
            writer
                .finish()
                .map_err(|e| format!("finish video export: {e}"))?;
        }
        Ok(())
    }
}

/// The boxed page sink the renderer owns, paired with the handle the loop uses to announce
/// each sample. Interior mutability is needed because the renderer owns the sink once open.
struct SharedSink(Rc<RefCell<SampleSink>>);

impl PageSink for SharedSink {
    fn accept(&mut self, page: RenderedPage) -> Result<(), SinkError> {
        self.0.borrow_mut().accept_page(page)
    }
}

/// Executes headless rendering without window creation.
pub(crate) fn run_headless(config: &CliConfig, scene: &FilmScene) -> Result<(), String> {
    println!("[stuntreel] Starting headless offscreen presentation...");

    if let Some(out_dir) = &config.out_dir {
        fs::create_dir_all(out_dir)
            .map_err(|e| format!("create output directory {}: {e}", out_dir.display()))?;
    }

    let playback = Playback::new(config, scene);
    let range = playback.range();
    let start_tick = range.start();
    let span_seconds = range.span_seconds();

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

    let mut offscreen = Offscreen::new(config.width, config.height);
    if let Some(rows) = config.viewport_rows {
        offscreen = offscreen.with_viewport_rows(rows);
    }
    let options = RenderOptions {
        clear_palette_index: config.clear_index,
        software_only: false,
    };

    if config.out_dir.is_none() && video_writer.is_none() {
        let output_path = config
            .output_png
            .clone()
            .unwrap_or_else(|| PathBuf::from("stuntreel_capture.png"));

        let frame = scene.frame(start_tick as f32);
        let cam = frame.view;
        println!(
            "[stuntreel] camera forward: {}",
            if CAMERA_FORWARD[2] < 0.0 { "-Z" } else { "+Z" }
        );
        let mut renderer = Renderer::offscreen(
            scene,
            offscreen,
            Box::new(SinglePngSink {
                path: output_path.clone(),
            }),
            options,
        )
        .map_err(|e| format!("Headless renderer failed: {e}"))?;
        println!(
            "[stuntreel] tick {start_tick} camera: eye={:?}, target={:?}, fov={}; {} actor draws",
            cam.eye,
            cam.target,
            cam.fov_degrees,
            frame.actors.len()
        );
        renderer
            .draw(&frame, None)
            .map_err(|e| format!("Offscreen render to PNG failed: {e}"))?;

        println!(
            "[stuntreel] Headless frame successfully saved to {}",
            output_path.display()
        );
        return Ok(());
    }

    let samples = playback.samples();

    let geometry = Geometry {
        width: config.width,
        height: config.height,
        viewport_rows: config.viewport_rows,
    };
    let journal = config
        .out_dir
        .as_ref()
        .map(|dir| RenderJournal::begin(dir, film_identity(config.flm_path.as_deref()), geometry));
    let sink = Rc::new(RefCell::new(SampleSink {
        out_dir: config.out_dir.clone(),
        video: video_writer.take(),
        journal,
        pending: None,
        written_frames: 0,
        written_video_frames: 0,
    }));
    let mut renderer = Renderer::offscreen(
        scene,
        offscreen,
        Box::new(SharedSink(Rc::clone(&sink))),
        options,
    )
    .map_err(|e| format!("Headless renderer failed: {e}"))?;
    println!(
        "[stuntreel] camera forward: {}",
        if CAMERA_FORWARD[2] < 0.0 { "-Z" } else { "+Z" }
    );

    for (key, tick) in samples {
        let frame = scene.frame(capture_tick(tick));
        sink.borrow_mut().begin(key, &frame);
        renderer
            .draw(&frame, None)
            .map_err(|e| format!("render {key}: {e}"))?;
    }
    drop(renderer);

    sink.borrow_mut().finish_journal().map_err(|e| e.clone())?;
    if let Some(out_dir) = &config.out_dir {
        let written_frames = sink.borrow().written_frames;
        println!(
            "[stuntreel] Wrote {written_frames} frames to {}",
            out_dir.display()
        );
    }

    sink.borrow_mut().finish_video().map_err(|e| e.clone())?;
    if let Some(video_path) = &config.video_path {
        let written_video_frames = sink.borrow().written_video_frames;
        println!(
            "[stuntreel] Wrote {written_video_frames} frames to video {}",
            video_path.display()
        );
    }

    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn evenly_spaced_samples_are_named_by_their_index() {
        assert_eq!(sample_png_name(1), "sample_0001.png");
        assert_eq!(sample_png_name(140), "sample_0140.png");
    }
}
