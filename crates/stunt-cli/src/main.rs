#![deny(unsafe_code)]

//! StuntReel Modern CLI & Presentation Engine (`stuntreel`).
//!
//! The CLI parses arguments, locates input files ([`scene`]), owns the winit window, and
//! writes outputs (PNG, ffmpeg video, the `parity` subcommand). Every film-to-frame
//! decision goes through [`stunt_core::scene::FilmScene`] and
//! [`stunt_render::SceneRenderer`], the same path for headless and windowed playback.
//!
//! Complies with Architectural Invariants:
//! - `[I1]` Right-handed metric coordinate basis (+X Right, +Y Up, -Z Forward).
//! - `[I3]` VGA Mode 13h flat-shaded presentation via 256x32 palette LUT.
//! - `[I5]` Dual-pipeline hardware depth bias pass for coplanar decals.
//! - `[I6]` Strict 4:3 physical aspect ratio letterbox presentation.

use std::env;
use std::fs;
use std::path::PathBuf;
use std::sync::Arc;
use std::time::Instant;

mod export;
mod parity;
mod scene;

use scene::{SceneSources, build_scene};
use stunt_core::contracts::get_palette_rgb_float;
use stunt_core::flm::{CAMERA_FORWARD, TIMELINE_HZ, TIMELINE_TICK_SECONDS};
use stunt_core::scene::FilmScene;
use stunt_render::{
    ASPECT_4_3, CameraController, CameraGpuResources, CameraMode, FfmpegVideoWriter,
    HeadlessRenderer, PaletteLut, RenderPipelines, SceneRenderer,
};
use winit::application::ApplicationHandler;
use winit::dpi::LogicalSize;

use winit::event::{DeviceEvent, ElementState, KeyEvent, WindowEvent};
use winit::event_loop::{ActiveEventLoop, ControlFlow, EventLoop};
use winit::keyboard::{Key, NamedKey};
use winit::window::{Window, WindowId};

/// CLI configuration parsed from command-line arguments.
#[derive(Debug, Clone)]
pub struct CliConfig {
    pub flm_path: Option<PathBuf>,
    pub sod_path: Option<PathBuf>,
    pub all_path: Option<PathBuf>,
    pub out_dir: Option<PathBuf>,
    /// Half-open `[start, end)` 1-based tick ordinals to render; `None` renders ticks
    /// `0..=total_ticks`.
    pub frame_range: Option<(usize, usize)>,
    /// Directory searched first for `ANCHORPT.DAT`, `MAP.BIN` and `SCENERY.scn`.
    pub sidata_dir: Option<PathBuf>,
    pub width: u32,
    pub height: u32,
    pub clear_index: u8,
    pub headless: bool,
    pub output_png: Option<PathBuf>,
    pub max_ticks: Option<usize>,
    pub video_path: Option<PathBuf>,
    pub frame_step: usize,
    pub sample_count: Option<usize>,
    pub fps: f32,
}

impl CliConfig {
    pub fn parse() -> Result<Self, String> {
        Self::parse_from(env::args().skip(1))
    }

    pub fn parse_from(mut args: impl Iterator<Item = String>) -> Result<Self, String> {
        let mut flm_path = None;
        let mut sod_path = None;
        let mut all_path = None;
        let mut out_dir = None;
        let mut frame_range = None;
        let mut sidata_dir = None;
        let mut width = 320u32;
        let mut height = 240u32;
        let mut clear_index = 180u8;
        let mut explicit_clear_index = false;
        let mut headless = false;
        let mut output_png = None;
        let mut max_ticks = None;
        let mut video_path = None;
        let mut frame_step = 1usize;
        let mut sample_count = None;
        let mut fps = 30.0f32;

        while let Some(arg) = args.next() {
            match arg.as_str() {
                "--help" | "-h" => {
                    Self::print_usage();
                    std::process::exit(0);
                }
                "--headless" => {
                    headless = true;
                }
                "--sod" => {
                    let val = args.next().ok_or("Expected path after --sod")?;
                    sod_path = Some(PathBuf::from(val));
                }
                "--all" => {
                    let val = args.next().ok_or("Expected path after --all")?;
                    all_path = Some(PathBuf::from(val));
                }
                "--out-dir" => {
                    let val = args.next().ok_or("Expected directory after --out-dir")?;
                    out_dir = Some(PathBuf::from(val));
                }
                "--frames" => {
                    let val = args.next().ok_or("Expected A..B after --frames")?;
                    frame_range = Some(Self::parse_frame_range(&val)?);
                }
                "--sidata" => {
                    let val = args.next().ok_or("Expected directory after --sidata")?;
                    sidata_dir = Some(PathBuf::from(val));
                }
                "--video" => {
                    let val = args.next().ok_or("Expected path after --video")?;
                    video_path = Some(PathBuf::from(val));
                }
                "--frame-step" => {
                    let val = args.next().ok_or("Expected number after --frame-step")?;
                    let step = val
                        .parse::<usize>()
                        .map_err(|e| format!("Invalid frame step: {e}"))?;
                    if step == 0 {
                        return Err("Frame step must be greater than zero".to_string());
                    }
                    frame_step = step;
                }
                "--sample-count" => {
                    let val = args.next().ok_or("Expected number after --sample-count")?;
                    let count = val
                        .parse::<usize>()
                        .map_err(|e| format!("Invalid sample count: {e}"))?;
                    if count == 0 {
                        return Err("Sample count must be greater than zero".to_string());
                    }
                    sample_count = Some(count);
                }
                "--fps" => {
                    let val = args.next().ok_or("Expected number after --fps")?;
                    let rate = val
                        .parse::<f32>()
                        .map_err(|e| format!("Invalid fps: {e}"))?;
                    if rate <= 0.0 || !rate.is_finite() {
                        return Err("FPS must be a positive finite number".to_string());
                    }
                    fps = rate;
                }
                "--width" => {
                    let val = args.next().ok_or("Expected number after --width")?;
                    width = val
                        .parse::<u32>()
                        .map_err(|e| format!("Invalid width: {e}"))?;
                }
                "--height" => {
                    let val = args.next().ok_or("Expected number after --height")?;
                    height = val
                        .parse::<u32>()
                        .map_err(|e| format!("Invalid height: {e}"))?;
                }
                "--clear-index" => {
                    let val = args.next().ok_or("Expected number after --clear-index")?;
                    clear_index = val
                        .parse::<u8>()
                        .map_err(|e| format!("Invalid palette index: {e}"))?;
                    explicit_clear_index = true;
                }
                "--output" | "-o" => {
                    let val = args.next().ok_or("Expected path after --output")?;
                    output_png = Some(PathBuf::from(val));
                }
                "--ticks" => {
                    let val = args.next().ok_or("Expected number after --ticks")?;
                    let n = val
                        .parse::<usize>()
                        .map_err(|e| format!("Invalid tick count: {e}"))?;
                    max_ticks = Some(n);
                }
                other => {
                    if other.starts_with('-') {
                        return Err(format!("Unrecognized argument: {other}"));
                    }
                    let path = PathBuf::from(other);
                    let is_all = path
                        .extension()
                        .is_some_and(|ext| ext.eq_ignore_ascii_case("all"));
                    if is_all && all_path.is_none() {
                        all_path = Some(path);
                    } else if flm_path.is_none() {
                        flm_path = Some(path);
                    } else if all_path.is_none() {
                        all_path = Some(path);
                    } else {
                        return Err(format!("Unrecognized argument: {other}"));
                    }
                }
            }
        }

        if width == 0 || height == 0 {
            return Err("Framebuffer dimensions must be non-zero".to_string());
        }
        if !(width * 4).is_multiple_of(256) {
            return Err("row pitch must be 256-byte aligned".to_string());
        }

        if out_dir.is_some() || video_path.is_some() || output_png.is_some() {
            headless = true;
        }

        if video_path.is_some() && sample_count.is_some() {
            return Err("--sample-count cannot be combined with --video".to_string());
        }
        if sample_count.is_some() && out_dir.is_none() {
            return Err("--sample-count requires --out-dir".to_string());
        }

        if sod_path.is_none() {
            if let Some(flm) = &flm_path
                && all_path.is_none()
            {
                let candidate_upper = flm.with_extension("ALL");
                if candidate_upper.is_file() {
                    all_path = Some(candidate_upper);
                } else {
                    let candidate_lower = flm.with_extension("all");
                    if candidate_lower.is_file() {
                        all_path = Some(candidate_lower);
                    }
                }
            } else if let Some(all) = &all_path
                && flm_path.is_none()
            {
                let candidate_upper = all.with_extension("FLM");
                if candidate_upper.is_file() {
                    flm_path = Some(candidate_upper);
                } else {
                    let candidate_lower = all.with_extension("flm");
                    if candidate_lower.is_file() {
                        flm_path = Some(candidate_lower);
                    }
                }
            }
        }

        let clear_index = if explicit_clear_index {
            clear_index
        } else if all_path.is_some() {
            233
        } else {
            180
        };

        Ok(Self {
            flm_path,
            sod_path,
            all_path,
            out_dir,
            frame_range,
            sidata_dir,
            width,
            height,
            clear_index,
            headless,
            output_png,
            max_ticks,
            video_path,
            frame_step,
            sample_count,
            fps,
        })
    }

    /// Parses a half-open `A..B` frame range.
    fn parse_frame_range(spec: &str) -> Result<(usize, usize), String> {
        let (start, end) = spec
            .split_once("..")
            .ok_or_else(|| format!("Invalid frame range {spec:?}, expected A..B"))?;
        let start = start
            .trim()
            .parse::<usize>()
            .map_err(|e| format!("Invalid frame range start: {e}"))?;
        let end = end
            .trim()
            .parse::<usize>()
            .map_err(|e| format!("Invalid frame range end: {e}"))?;
        if end <= start {
            return Err(format!(
                "Invalid frame range {spec:?}: end must be greater than start"
            ));
        }
        Ok((start, end))
    }

    pub fn print_usage() {
        println!("StuntReel Presentation Engine (stuntreel)");
        println!("Usage: stuntreel [options] [<flight.flm>]");
        println!();
        println!("Arguments:");
        println!("  <flight.flm>         Path to authored .FLM choreography file (optional)");
        println!();
        println!("Options:");
        println!("  --sod <model.sod>    Path to procedural .SOD model to bind to actor 1");
        println!(
            "  --all <movie.all>    Bind every actor shape_id to its .SOD chunk in the archive"
        );
        println!("  --out-dir <dir>      Write <dir>/tick_NNNNN.png (NNNNN = 0-based 50 Hz tick);");
        println!(
            "                       with --sample-count or --video, <dir>/sample_NNNN.png instead"
        );
        println!(
            "  --frames <A..B>      Half-open 1-based tick ordinals to render; 1..N+2 covers ticks 0..=N"
        );
        println!(
            "                       (default: ticks 0..=total, the film's last tick included)"
        );
        println!(
            "  --sidata <dir>       Directory searched first for ANCHORPT.DAT, MAP.BIN and SCENERY.scn;"
        );
        println!(
            "                       then the archive's directory, its parent and grandparent,"
        );
        println!(
            "                       then sidata/ or SIDATA/ inside the parent (names match any case)"
        );
        println!(
            "  --video <file>       Render film to video container (.mp4, .webm, .mkv, .avi) via ffmpeg"
        );
        println!("  --frame-step <N>     Tick stride for --out-dir frame extraction (default: 1)");
        println!(
            "  --sample-count <N>   Render N evenly spaced frames across the selected tick range"
        );
        println!(
            "  --fps <HZ>           Video sampling rate; container duration follows authored ticks (default: 30)"
        );
        println!(
            "  --width <px>         Offscreen framebuffer width (default 320, 256-byte pitch)"
        );
        println!("  --height <px>        Offscreen framebuffer height (default 240)");
        println!("  --clear-index <i>    Mode 13h palette index used to clear the framebuffer");
        println!("  --headless           Run in offscreen headless mode without opening a window");
        println!("  --output, -o <file>  Save offscreen rendered frame to PNG file");
        println!("  --ticks <count>      Maximum authored 50 Hz ticks to evaluate/render");
        println!("  -h, --help           Print this help information");
        println!();
        println!("Subcommands:");
        println!("  {}", parity::USAGE.replace('\n', "\n  "));
        println!();
        println!("  {}", export::USAGE.replace('\n', "\n  "));
        println!();
        println!("Interactive Keyboard Controls:");
        println!("  Space                Pause / Resume timeline playback");
        println!("  C                    Toggle between Authored Camera and Free-Cam");
        println!("  W / S                Free-Cam: Move Forward / Backward");
        println!("  A / D                Free-Cam: Strafe Left / Right");
        println!("  Q / E                Free-Cam: Move Down / Up");
        println!("  Esc                  Exit presentation");
    }
}

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

/// File name written under `--out-dir` for a rendered sample.
fn sample_png_name(key: SampleKey) -> String {
    match key {
        SampleKey::Tick(tick) => tick_png_name(tick),
        SampleKey::Index(index) => format!("sample_{index:04}.png"),
    }
}

/// The authored tick count, capped by `--ticks`.
fn playback_ticks(config: &CliConfig, scene: &FilmScene) -> u32 {
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
pub fn run_headless(config: &CliConfig, scene: &FilmScene) -> Result<(), String> {
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

    let mut written_pngs = 0usize;
    let mut written_video_frames = 0usize;

    for (key, tick) in samples {
        let frame = scene.frame(tick);
        let rgba_bytes = renderer
            .render_scene(&mut scene_renderer, &frame, None, Some(config.clear_index))
            .map_err(|e| format!("render {key}: {e}"))?;

        if let Some(out_dir) = &config.out_dir {
            let frame_path = out_dir.join(sample_png_name(key));
            save_rgba_png(&frame_path, config.width, config.height, &rgba_bytes)
                .map_err(|e| format!("{key}: {e}"))?;
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

/// Creates the depth attachment used by the interactive surface pass.
fn create_depth_view(device: &wgpu::Device, width: u32, height: u32) -> wgpu::TextureView {
    device
        .create_texture(&wgpu::TextureDescriptor {
            label: Some("stunt_window_depth_texture"),
            size: wgpu::Extent3d {
                width: width.max(1),
                height: height.max(1),
                depth_or_array_layers: 1,
            },
            mip_level_count: 1,
            sample_count: 1,
            dimension: wgpu::TextureDimension::D2,
            format: wgpu::TextureFormat::Depth24Plus,
            usage: wgpu::TextureUsages::RENDER_ATTACHMENT,
            view_formats: &[],
        })
        .create_view(&wgpu::TextureViewDescriptor::default())
}

/// Interactive window application state.
struct WindowApp {
    config: CliConfig,
    /// The film scene, built once before the event loop and reused across resumes.
    scene: FilmScene,
    playback_ticks: u32,
    window: Option<Arc<Window>>,
    device: Option<wgpu::Device>,
    queue: Option<wgpu::Queue>,
    surface: Option<wgpu::Surface<'static>>,
    surface_config: Option<wgpu::SurfaceConfiguration>,
    pipelines: Option<RenderPipelines>,
    palette_lut: Option<PaletteLut>,
    camera_resources: Option<CameraGpuResources>,
    depth_view: Option<wgpu::TextureView>,
    scene_renderer: Option<SceneRenderer>,
    camera: CameraController,
    current_tick: f32,
    paused: bool,
    last_frame_time: Instant,
    max_texture_dimension_2d: u32,
    // Free-Cam input keys
    key_w: bool,
    key_s: bool,
    key_a: bool,
    key_d: bool,
    key_q: bool,
    key_e: bool,
}

impl WindowApp {
    fn new(config: CliConfig, scene: FilmScene) -> Self {
        let playback_ticks = playback_ticks(&config, &scene);
        Self {
            config,
            scene,
            playback_ticks,
            window: None,
            device: None,
            queue: None,
            surface: None,
            surface_config: None,
            pipelines: None,
            palette_lut: None,
            camera_resources: None,
            depth_view: None,
            scene_renderer: None,
            camera: CameraController::default(),
            current_tick: 0.0,
            paused: false,
            last_frame_time: Instant::now(),
            max_texture_dimension_2d: 2048,
            key_w: false,
            key_s: false,
            key_a: false,
            key_d: false,
            key_q: false,
            key_e: false,
        }
    }

    fn update_freecam(&mut self, dt: f32) {
        if self.camera.mode != CameraMode::FreeCam {
            return;
        }

        let speed = self.camera.free_cam.move_speed * dt;
        if self.key_w {
            self.camera.free_cam.move_forward(speed);
        }
        if self.key_s {
            self.camera.free_cam.move_forward(-speed);
        }
        if self.key_d {
            self.camera.free_cam.move_right(speed);
        }
        if self.key_a {
            self.camera.free_cam.move_right(-speed);
        }
        if self.key_e {
            self.camera.free_cam.move_up(speed);
        }
        if self.key_q {
            self.camera.free_cam.move_up(-speed);
        }
    }

    /// Advances the authored timeline in wall-clock time `[I4]`.
    fn advance_timeline(&mut self, dt: f32) {
        if self.paused || self.playback_ticks == 0 {
            return;
        }
        self.current_tick = (self.current_tick + dt * TIMELINE_HZ) % self.playback_ticks as f32;
    }

    fn render(&mut self, dt: f32) {
        self.advance_timeline(dt);

        let (
            Some(device),
            Some(queue),
            Some(surface),
            Some(surface_config),
            Some(pipelines),
            Some(cam_res),
            Some(lut),
            Some(depth_view),
            Some(scene_renderer),
        ) = (
            &self.device,
            &self.queue,
            &self.surface,
            &self.surface_config,
            &self.pipelines,
            &self.camera_resources,
            &self.palette_lut,
            &self.depth_view,
            &mut self.scene_renderer,
        )
        else {
            return;
        };

        let frame = self.scene.frame(self.current_tick);
        if self.camera.mode == CameraMode::Authored {
            self.camera.set_authored_transform(frame.camera);
        }
        scene_renderer.prepare(device, queue, cam_res, &frame, Some(&self.camera));

        let surface_texture = match surface.get_current_texture() {
            Ok(tex) => tex,
            Err(wgpu::SurfaceError::Lost) => {
                surface.configure(device, surface_config);
                return;
            }
            Err(wgpu::SurfaceError::OutOfMemory) => {
                eprintln!("[stuntreel] Surface out of memory");
                return;
            }
            Err(_) => return,
        };

        let view = surface_texture
            .texture
            .create_view(&wgpu::TextureViewDescriptor::default());

        let mut encoder = device.create_command_encoder(&wgpu::CommandEncoderDescriptor {
            label: Some("stunt_window_encoder"),
        });

        // Compute 4:3 letterbox viewport per Invariant [I6]
        let win_w = surface_config.width as f32;
        let win_h = surface_config.height as f32;
        let target_aspect = ASPECT_4_3;
        let cur_aspect = win_w / win_h.max(1.0);

        let (vp_x, vp_y, vp_w, vp_h) = if cur_aspect > target_aspect {
            // Pillarbox: bars on left and right
            let vp_h = win_h;
            let vp_w = win_h * target_aspect;
            let vp_x = (win_w - vp_w) / 2.0;
            (vp_x, 0.0, vp_w, vp_h)
        } else {
            // Letterbox: bars on top and bottom
            let vp_w = win_w;
            let vp_h = win_w / target_aspect;
            let vp_y = (win_h - vp_h) / 2.0;
            (0.0, vp_y, vp_w, vp_h)
        };

        let width = surface_config.width;
        let height = surface_config.height;
        let sc_x = vp_x.max(0.0) as u32;
        let sc_y = vp_y.max(0.0) as u32;
        let sc_w = (vp_w as u32).clamp(1, width.saturating_sub(sc_x).max(1));
        let sc_h = (vp_h as u32).clamp(1, height.saturating_sub(sc_y).max(1));

        let right_edge = (vp_x + vp_w).min(win_w) as u32;
        let bottom_edge = (vp_y + vp_h).min(win_h) as u32;
        let bars: [(u32, u32, u32, u32); 2] = if cur_aspect > target_aspect {
            [
                (0, 0, sc_x, height),
                (right_edge, 0, width.saturating_sub(right_edge), height),
            ]
        } else {
            [
                (0, 0, width, sc_y),
                (0, bottom_edge, width, height.saturating_sub(bottom_edge)),
            ]
        };

        // Palette-index clear color matches the headless capture (default sky index 180).
        let (cr, cg, cb) = get_palette_rgb_float(self.config.clear_index);
        let clear_color = wgpu::Color {
            r: cr as f64,
            g: cg as f64,
            b: cb as f64,
            a: 1.0,
        };

        {
            let mut rpass = encoder.begin_render_pass(&wgpu::RenderPassDescriptor {
                label: Some("stunt_window_render_pass"),
                color_attachments: &[Some(wgpu::RenderPassColorAttachment {
                    view: &view,
                    resolve_target: None,
                    ops: wgpu::Operations {
                        load: wgpu::LoadOp::Clear(clear_color),
                        store: wgpu::StoreOp::Store,
                    },
                })],
                depth_stencil_attachment: Some(wgpu::RenderPassDepthStencilAttachment {
                    view: depth_view,
                    depth_ops: Some(wgpu::Operations {
                        load: wgpu::LoadOp::Clear(1.0),
                        store: wgpu::StoreOp::Store,
                    }),
                    stencil_ops: None,
                }),
                timestamp_writes: None,
                occlusion_query_set: None,
            });

            // Set 4:3 letterbox viewport and scissor rect
            rpass.set_viewport(vp_x, vp_y, vp_w, vp_h, 0.0, 1.0);
            rpass.set_scissor_rect(sc_x, sc_y, sc_w, sc_h);

            // Passes 1-2: world and actors, base geometry then the `[I5]` decal pass
            scene_renderer.draw(&mut rpass, pipelines, cam_res, lut);

            // Pass 3: Paint the `[I6]` pillarbox/letterbox bars black
            rpass.set_viewport(0.0, 0.0, win_w, win_h, 0.0, 1.0);
            rpass.set_pipeline(&pipelines.bar_pipeline);
            for (bar_x, bar_y, bar_w, bar_h) in bars {
                if bar_w == 0 || bar_h == 0 {
                    continue;
                }
                rpass.set_scissor_rect(bar_x, bar_y, bar_w, bar_h);
                rpass.draw(0..3, 0..1);
            }
        }

        queue.submit(Some(encoder.finish()));
        surface_texture.present();
    }
}

impl ApplicationHandler for WindowApp {
    fn resumed(&mut self, event_loop: &ActiveEventLoop) {
        if self.window.is_some() {
            return;
        }

        let win_attrs = Window::default_attributes()
            .with_title("Stunt Reel - Stunt Island Modern Presentation")
            .with_inner_size(LogicalSize::new(960.0, 720.0)); // 4:3 3x scale of 320x240

        let window = match event_loop.create_window(win_attrs) {
            Ok(w) => Arc::new(w),
            Err(e) => {
                eprintln!("[stuntreel] Failed to create window: {e}");
                event_loop.exit();
                return;
            }
        };

        let instance = wgpu::Instance::new(&wgpu::InstanceDescriptor {
            backends: wgpu::Backends::all(),
            ..Default::default()
        });

        let surface = match instance.create_surface(Arc::clone(&window)) {
            Ok(s) => s,
            Err(e) => {
                eprintln!("[stuntreel] Failed to create surface: {e}");
                event_loop.exit();
                return;
            }
        };

        let adapter =
            match pollster::block_on(instance.request_adapter(&wgpu::RequestAdapterOptions {
                power_preference: wgpu::PowerPreference::HighPerformance,
                compatible_surface: Some(&surface),
                force_fallback_adapter: false,
            })) {
                Some(a) => a,
                None => {
                    eprintln!("[stuntreel] No suitable GPU adapter for window");
                    event_loop.exit();
                    return;
                }
            };

        let adapter_limits = adapter.limits();
        let max_dim = adapter_limits.max_texture_dimension_2d;
        self.max_texture_dimension_2d = max_dim;

        let (device, queue) = match pollster::block_on(adapter.request_device(
            &wgpu::DeviceDescriptor {
                label: Some("stunt_window_device"),
                required_features: wgpu::Features::empty(),
                required_limits:
                    wgpu::Limits::downlevel_defaults().using_resolution(adapter_limits),
                memory_hints: wgpu::MemoryHints::Performance,
            },
            None,
        )) {
            Ok(pair) => pair,
            Err(e) => {
                eprintln!("[stuntreel] Failed to create device: {e}");
                event_loop.exit();
                return;
            }
        };

        let size = window.inner_size();
        let surface_caps = surface.get_capabilities(&adapter);
        let surface_format = surface_caps
            .formats
            .iter()
            .copied()
            .find(|f| f.is_srgb())
            .unwrap_or(surface_caps.formats[0]);

        let surface_config = wgpu::SurfaceConfiguration {
            usage: wgpu::TextureUsages::RENDER_ATTACHMENT,
            format: surface_format,
            width: size.width.clamp(1, max_dim),
            height: size.height.clamp(1, max_dim),
            present_mode: wgpu::PresentMode::AutoVsync,
            desired_maximum_frame_latency: 2,
            alpha_mode: surface_caps.alpha_modes[0],
            view_formats: vec![],
        };
        surface.configure(&device, &surface_config);

        let camera_resources = CameraGpuResources::new(&device);
        let palette_lut = PaletteLut::new(&device, &queue);

        let pipelines = RenderPipelines::new(
            &device,
            surface_format,
            wgpu::TextureFormat::Depth24Plus,
            &camera_resources.bind_group_layout,
            &palette_lut.bind_group_layout,
        );

        let scene_renderer = SceneRenderer::new(&device, &queue, &pipelines, &self.scene);

        let depth_view = create_depth_view(&device, surface_config.width, surface_config.height);

        self.window = Some(Arc::clone(&window));
        self.device = Some(device);
        self.queue = Some(queue);
        self.surface = Some(surface);
        self.surface_config = Some(surface_config);
        self.pipelines = Some(pipelines);
        self.palette_lut = Some(palette_lut);
        self.camera_resources = Some(camera_resources);
        self.depth_view = Some(depth_view);
        self.scene_renderer = Some(scene_renderer);

        window.request_redraw();
    }

    fn window_event(&mut self, event_loop: &ActiveEventLoop, _id: WindowId, event: WindowEvent) {
        match event {
            WindowEvent::CloseRequested => {
                event_loop.exit();
            }
            WindowEvent::Resized(new_size) => {
                if let (Some(device), Some(surface), Some(config)) =
                    (&self.device, &self.surface, &mut self.surface_config)
                {
                    config.width = new_size.width.clamp(1, self.max_texture_dimension_2d);
                    config.height = new_size.height.clamp(1, self.max_texture_dimension_2d);
                    surface.configure(device, config);
                    self.depth_view = Some(create_depth_view(device, config.width, config.height));
                }
            }
            WindowEvent::KeyboardInput {
                event: KeyEvent {
                    state, logical_key, ..
                },
                ..
            } => {
                let pressed = state == ElementState::Pressed;
                match logical_key {
                    Key::Named(NamedKey::Escape) => {
                        event_loop.exit();
                    }
                    Key::Named(NamedKey::Space) if pressed => {
                        self.paused = !self.paused;
                        println!(
                            "[stuntreel] Playback {}",
                            if self.paused { "Paused" } else { "Resumed" }
                        );
                    }
                    Key::Character(s) => match s.to_ascii_lowercase().as_str() {
                        "c" if pressed => {
                            self.camera.toggle_mode();
                            println!("[stuntreel] Camera Mode: {:?}", self.camera.mode);
                        }
                        "w" => self.key_w = pressed,
                        "s" => self.key_s = pressed,
                        "a" => self.key_a = pressed,
                        "d" => self.key_d = pressed,
                        "q" => self.key_q = pressed,
                        "e" => self.key_e = pressed,
                        _ => {}
                    },
                    _ => {}
                }
            }
            WindowEvent::RedrawRequested => {
                let now = Instant::now();
                let dt = now
                    .duration_since(self.last_frame_time)
                    .as_secs_f32()
                    .min(0.1);
                self.last_frame_time = now;

                self.update_freecam(dt);
                self.render(dt);

                if let Some(win) = &self.window {
                    win.request_redraw();
                }
            }
            _ => {}
        }
    }

    fn device_event(
        &mut self,
        _event_loop: &ActiveEventLoop,
        _device_id: winit::event::DeviceId,
        event: DeviceEvent,
    ) {
        if self.camera.mode != CameraMode::FreeCam {
            return;
        }

        if let DeviceEvent::MouseMotion { delta: (dx, dy) } = event {
            let sens = self.camera.free_cam.look_sensitivity;
            self.camera
                .free_cam
                .rotate(dx as f32 * sens, -dy as f32 * sens);
        }
    }
}

fn main() {
    let mut subcommand_args = env::args().skip(1);
    match subcommand_args.next().as_deref() {
        Some("parity") => {
            if let Err(e) = parity::run(subcommand_args) {
                eprintln!("[stuntreel error] {e}");
                std::process::exit(1);
            }
            return;
        }
        Some("export-gltf") => {
            if let Err(e) = export::run(subcommand_args) {
                eprintln!("[stuntreel error] {e}");
                std::process::exit(1);
            }
            return;
        }
        _ => {}
    }

    let config = match CliConfig::parse() {
        Ok(c) => c,
        Err(err) => {
            eprintln!("[stuntreel error] {err}");
            CliConfig::print_usage();
            std::process::exit(1);
        }
    };

    let scene = match build_scene(&SceneSources {
        flm: config.flm_path.as_deref(),
        all: config.all_path.as_deref(),
        sod: config.sod_path.as_deref(),
        sidata: config.sidata_dir.as_deref(),
        max_ticks: config.max_ticks,
    }) {
        Ok(scene) => scene,
        Err(e) => {
            eprintln!("[stuntreel error] {e}");
            std::process::exit(1);
        }
    };

    if config.headless {
        if let Err(e) = run_headless(&config, &scene) {
            eprintln!("[stuntreel error] {e}");
            std::process::exit(1);
        }
        return;
    }

    let event_loop = match EventLoop::new() {
        Ok(el) => el,
        Err(e) => {
            eprintln!("[stuntreel] Failed to create event loop: {e}");
            std::process::exit(1);
        }
    };
    event_loop.set_control_flow(ControlFlow::Poll);

    let mut app = WindowApp::new(config, scene);
    if let Err(e) = event_loop.run_app(&mut app) {
        eprintln!("[stuntreel] Application error: {e}");
        std::process::exit(1);
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::path::Path;

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

    #[test]
    fn test_tick_range_and_sample_options_parse() {
        let config = CliConfig::parse_from(
            vec![
                "film.flm".to_string(),
                "--frames".to_string(),
                "2..10".to_string(),
                "--frame-step".to_string(),
                "3".to_string(),
                "--sample-count".to_string(),
                "5".to_string(),
                "--out-dir".to_string(),
                "out".to_string(),
                "--fps".to_string(),
                "50".to_string(),
                "--sidata".to_string(),
                "data/SIDATA".to_string(),
            ]
            .into_iter(),
        )
        .expect("parse succeeds");

        assert_eq!(config.frame_range, Some((2, 10)));
        assert_eq!(config.frame_step, 3);
        assert_eq!(config.sample_count, Some(5));
        assert_eq!(config.fps, 50.0);
        assert_eq!(config.sidata_dir, Some(PathBuf::from("data/SIDATA")));

        assert!(
            CliConfig::parse_from(
                vec![
                    "film.flm".to_string(),
                    "--sample-count".to_string(),
                    "5".to_string()
                ]
                .into_iter()
            )
            .is_err()
        );
    }

    #[test]
    fn test_all_companion_autodiscovery() {
        let manifest_dir = Path::new(env!("CARGO_MANIFEST_DIR"));
        let workspace_root = manifest_dir.parent().unwrap().parent().unwrap();
        let fixture_flm = workspace_root.join("tests/fixtures/synthetic_minimal.flm");
        let expected_all = workspace_root.join("tests/fixtures/synthetic_minimal.all");
        let config = CliConfig::parse_from(
            vec![
                fixture_flm.to_string_lossy().to_string(),
                "--headless".to_string(),
            ]
            .into_iter(),
        );
        let cfg = config.expect("parse succeeds");
        assert!(cfg.all_path.is_some());
        assert_eq!(
            cfg.all_path.unwrap().to_string_lossy().to_ascii_lowercase(),
            expected_all.to_string_lossy().to_ascii_lowercase()
        );
        assert_eq!(cfg.clear_index, 233);
    }

    #[test]
    fn test_flm_companion_autodiscovery_from_all() {
        let manifest_dir = Path::new(env!("CARGO_MANIFEST_DIR"));
        let workspace_root = manifest_dir.parent().unwrap().parent().unwrap();
        let fixture_flm = workspace_root.join("tests/fixtures/synthetic_minimal.flm");
        let fixture_all = workspace_root.join("tests/fixtures/synthetic_minimal.all");
        let config = CliConfig::parse_from(
            vec![
                fixture_all.to_string_lossy().to_string(),
                "-o".to_string(),
                "out.png".to_string(),
            ]
            .into_iter(),
        );
        let cfg = config.expect("parse succeeds");
        assert!(cfg.headless, "output_png implies headless");
        assert!(cfg.all_path.is_some());
        assert!(cfg.flm_path.is_some());
        assert_eq!(
            cfg.flm_path.unwrap().to_string_lossy().to_ascii_lowercase(),
            fixture_flm.to_string_lossy().to_ascii_lowercase()
        );
        assert_eq!(cfg.clear_index, 233);
    }
}
