//! Offscreen playback: a single PNG, an --out-dir render store or sample sequence, or an ffmpeg
//! video.

use std::fs;
use std::path::PathBuf;
use stunt_core::credits::CreditLines;

use stunt_core::contracts::PaletteControls;
use stunt_core::flm::CAMERA_FORWARD;
use stunt_core::scene::{FilmScene, SceneFrame, ViewCamera};
use stunt_parity::{FilmId, Geometry, RenderAdapter};
use stunt_render::{
    FfmpegVideoWriter, Offscreen, PageSink, RenderOptions, RenderedPage, Renderer, SinkError,
};

use crate::config::CliConfig;
use crate::page_slot::PageSlot;
use crate::parity_artifacts::{RenderJournal, render_adapter};
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

/// What the render record keeps about the frame a sample shows, beside its page.
#[derive(Debug, Clone, Copy)]
struct FrameFacts {
    controls: PaletteControls,
    camera: ViewCamera,
    credits: bool,
}

impl FrameFacts {
    fn of(frame: &SceneFrame) -> Self {
        Self {
            controls: frame.palette,
            camera: frame.view,
            credits: frame.credits.as_ref().is_some_and(CreditLines::is_drawn),
        }
    }
}

/// Where a multi-sample run writes its pages: the render store and its record for whole
/// ticks, a PNG per evenly spaced sample, and/or video frames, whichever the run asked for.
struct SampleSink {
    out_dir: Option<PathBuf>,
    video: Option<FfmpegVideoWriter>,
    journal: Option<RenderJournal>,
    written_frames: usize,
    written_video_frames: usize,
}

impl SampleSink {
    /// Writes sample `key`'s `page`, showing a frame with `facts`, to every destination the
    /// run selected; an error names the sample.
    fn write(
        &mut self,
        key: SampleKey,
        facts: FrameFacts,
        page: &RenderedPage,
    ) -> Result<(), String> {
        if let Some(out_dir) = &self.out_dir {
            match key {
                SampleKey::Tick(tick) => {
                    let tick = u32::try_from(tick)
                        .map_err(|_| format!("{key}: tick does not fit a u32"))?;
                    if let Some(journal) = self.journal.as_mut() {
                        journal
                            .write(tick, facts.controls, facts.camera, facts.credits, page)
                            .map_err(|e| format!("{key}: {e}"))?;
                    }
                }
                SampleKey::Index(index) => {
                    let frame_path = out_dir.join(sample_png_name(index));
                    save_rgba_png(&frame_path, page.width(), page.height(), page.rgba())
                        .map_err(|e| format!("{key}: {e}"))?;
                }
            }
            self.written_frames += 1;
        }
        if let Some(writer) = &mut self.video {
            writer
                .write_frame(page.rgba())
                .map_err(|e| format!("write video frame for {key}: {e}"))?;
            self.written_video_frames += 1;
        }
        Ok(())
    }

    /// Closes the render store and writes its document, naming *adapter*, if the run has one.
    fn finish_journal(&mut self, adapter: RenderAdapter) -> Result<(), String> {
        if let Some(journal) = self.journal.take() {
            journal.finish(adapter).map_err(|e| e.to_string())?;
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

/// Executes headless rendering without window creation; a render store records `film`, the
/// identity of the bytes `scene` was built from.
pub(crate) fn run_headless(
    config: &CliConfig,
    scene: &FilmScene,
    film: FilmId,
) -> Result<(), String> {
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
        .map(|dir| RenderJournal::begin(dir, film, geometry))
        .transpose()
        .map_err(|error| error.to_string())?;
    let mut sink = SampleSink {
        out_dir: config.out_dir.clone(),
        video: video_writer.take(),
        journal,
        written_frames: 0,
        written_video_frames: 0,
    };
    let slot = PageSlot::default();
    let mut renderer = Renderer::offscreen(scene, offscreen, Box::new(slot.clone()), options)
        .map_err(|e| format!("Headless renderer failed: {e}"))?;
    println!(
        "[stuntreel] camera forward: {}",
        if CAMERA_FORWARD[2] < 0.0 { "-Z" } else { "+Z" }
    );

    for (key, tick) in samples {
        let frame = scene.frame(capture_tick(tick));
        renderer
            .draw(&frame, None)
            .map_err(|e| format!("render {key}: {e}"))?;
        // The renderer hands its sink exactly one page per successful draw.
        let page = slot
            .take()
            .ok_or_else(|| format!("render {key}: the renderer drew without producing a page"))?;
        sink.write(key, FrameFacts::of(&frame), &page)?;
    }
    let adapter = render_adapter(renderer.adapter());
    drop(renderer);

    sink.finish_journal(adapter)?;
    if let Some(out_dir) = &config.out_dir {
        let written_frames = sink.written_frames;
        println!(
            "[stuntreel] Wrote {written_frames} frames to {}",
            out_dir.display()
        );
    }

    sink.finish_video()?;
    if let Some(video_path) = &config.video_path {
        let written_video_frames = sink.written_video_frames;
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

    use stunt_parity::{FilmId, Geometry};
    use stunt_render::PageSize;

    use crate::parity_artifacts::read_render_record;

    #[test]
    fn evenly_spaced_samples_are_named_by_their_index() {
        assert_eq!(sample_png_name(1), "sample_0001.png");
        assert_eq!(sample_png_name(140), "sample_0140.png");
    }

    /// Scratch directory removed on drop.
    struct TempDir(PathBuf);

    impl TempDir {
        fn new(name: &str) -> Self {
            let path = std::env::temp_dir()
                .join(format!("stunt-reel-headless-{name}-{}", std::process::id()));
            drop(fs::remove_dir_all(&path));
            fs::create_dir_all(&path).expect("create temp dir");
            Self(path)
        }
    }

    impl Drop for TempDir {
        fn drop(&mut self) {
            drop(fs::remove_dir_all(&self.0));
        }
    }

    fn facts() -> FrameFacts {
        FrameFacts {
            controls: PaletteControls {
                sky: 0x2000,
                brightness: 0x8000,
                saturation: 0x8000,
            },
            camera: ViewCamera::default(),
            credits: false,
        }
    }

    /// A 320x200 page whose picture is its index plane through `facts()`'s film palette, as
    /// the renderer draws one.
    fn page() -> RenderedPage {
        let palette = facts().controls.film_palette();
        let plane: Vec<u32> = (0..320 * 200)
            .map(|pixel: u32| (16 << 8) | (pixel % 251))
            .collect();
        let rgba: Vec<u8> = plane
            .iter()
            .flat_map(|&word| {
                let (r, g, b) = palette[(word & 0xFF) as usize];
                [r, g, b, 255]
            })
            .collect();
        RenderedPage::new(PageSize::new(320, 200), rgba, &plane).expect("page")
    }

    /// A sink writing into `dir` with a render store, as a whole-tick `--out-dir` run has.
    fn store_sink(dir: &std::path::Path) -> SampleSink {
        let geometry = Geometry {
            width: 320,
            height: 200,
            viewport_rows: None,
        };
        SampleSink {
            out_dir: Some(dir.to_path_buf()),
            video: None,
            journal: Some(RenderJournal::begin(dir, FilmId::default(), geometry).expect("begin")),
            written_frames: 0,
            written_video_frames: 0,
        }
    }

    fn adapter() -> RenderAdapter {
        RenderAdapter {
            name: "Test GPU".to_string(),
            class: stunt_parity::AdapterClass::Hardware,
        }
    }

    #[test]
    fn whole_ticks_land_in_the_render_store_and_its_record() {
        let dir = TempDir::new("ticks");
        let mut sink = store_sink(&dir.0);
        for tick in [7, 9] {
            sink.write(SampleKey::Tick(tick), facts(), &page())
                .expect("write");
        }
        assert_eq!(sink.written_frames, 2);
        sink.finish_journal(adapter()).expect("finish");
        let record = read_render_record(&dir.0).expect("record");
        let ticks: Vec<u32> = record.ticks.iter().map(|tick| tick.tick).collect();
        assert_eq!(ticks, [7, 9]);
    }

    #[test]
    fn an_evenly_spaced_sample_lands_in_a_png_named_by_its_index() {
        let dir = TempDir::new("index");
        let mut sink = SampleSink {
            journal: None,
            ..store_sink(&dir.0)
        };
        sink.write(SampleKey::Index(3), facts(), &page())
            .expect("write");
        assert!(dir.0.join("sample_0003.png").is_file());
        assert_eq!(sink.written_frames, 1);
        assert_eq!(sink.written_video_frames, 0);
    }

    #[test]
    fn a_tick_that_does_not_fit_a_u32_is_an_error_naming_the_sample() {
        let dir = TempDir::new("wide");
        let mut sink = store_sink(&dir.0);
        let tick = usize::try_from(u64::from(u32::MAX) + 1).expect("64-bit usize");
        let error = sink
            .write(SampleKey::Tick(tick), facts(), &page())
            .unwrap_err();
        assert_eq!(error, format!("tick {tick}: tick does not fit a u32"));
        assert_eq!(sink.written_frames, 0);
    }
}
