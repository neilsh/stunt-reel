#![deny(unsafe_code)]

//! StuntReel Modern CLI & Presentation Engine (`stuntreel`).
//!
//! Complies with Architectural Invariants:
//! - `[I1]` Right-handed metric coordinate basis (+X Right, +Y Up, -Z Forward).
//! - `[I3]` VGA Mode 13h flat-shaded presentation via 256x32 palette LUT.
//! - `[I5]` Dual-pipeline hardware depth bias pass for coplanar decals.
//! - `[I6]` Strict 4:3 physical aspect ratio letterbox presentation.

use std::env;
use std::fs;
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::time::Instant;

mod parity;
mod scene;

use glam::{Mat4, Vec3};
use scene::{SceneBundle, load_anchor_table};
use stunt_core::contracts::{
    CameraTransform, NodeKind, SodModelIr, SodVertex, TrajectoryRecord, VisibilityCondition,
    get_palette_rgb_float,
};
use stunt_core::flm::{
    CAMERA_FORWARD, FilmTimeline, SliceKeyframe, TIMELINE_HZ, TIMELINE_TICK_SECONDS,
};
use stunt_core::sod::transpile_sod;
use stunt_render::{
    ASPECT_4_3, CameraController, CameraGpuResources, CameraMode, FfmpegVideoWriter, GpuMeshSlice,
    GpuModel, HeadlessRenderer, PaletteLut, RenderPipelines,
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
    /// Half-open `[start, end)` 1-based tick ordinals to render; `None` renders all.
    pub frame_range: Option<(usize, usize)>,
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
        println!("  --out-dir <dir>      Render sampled 50 Hz ticks to <dir>/frame_NNNN.png");
        println!("  --frames <A..B>      Half-open 1-based tick ordinals to render (default: all)");
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
        println!("  parity --reference <dir> --test <dir> --output <dir> [--clear-index N]");
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

/// Synthesizes a cleanroom aircraft model IR if no external .SOD file was specified.
pub fn create_default_aircraft_ir() -> SodModelIr {
    let mut ir = SodModelIr::new("FOKKER");

    // Fuselage / wings vertices
    // Fuselage top: palette 40 (light grey)
    // Fuselage side: palette 36
    // Wing roundel decal: palette 220 (red/white/blue roundel), flag = 1 (coplanar decal)
    let v0 = SodVertex {
        position: [0.0, 0.5, 4.0], // nose
        normal: [0.0, 1.0, 0.0],
        palette_index: 40,
        flags: 0,
        _padding: [0, 0],
    };
    let v1 = SodVertex {
        position: [-4.0, 0.5, 0.0], // left wing tip
        normal: [0.0, 1.0, 0.0],
        palette_index: 40,
        flags: 0,
        _padding: [0, 0],
    };
    let v2 = SodVertex {
        position: [4.0, 0.5, 0.0], // right wing tip
        normal: [0.0, 1.0, 0.0],
        palette_index: 40,
        flags: 0,
        _padding: [0, 0],
    };
    let v3 = SodVertex {
        position: [0.0, 0.5, -4.0], // tail
        normal: [0.0, 1.0, 0.0],
        palette_index: 36,
        flags: 0,
        _padding: [0, 0],
    };

    // Coplanar decal roundel on left wing (Invariant [I5])
    let d0 = SodVertex {
        position: [-2.0, 0.5, 0.2],
        normal: [0.0, 1.0, 0.0],
        palette_index: 232, // roundel red
        flags: 1,           // coplanar decal
        _padding: [0, 0],
    };
    let d1 = SodVertex {
        position: [-2.5, 0.5, -0.2],
        normal: [0.0, 1.0, 0.0],
        palette_index: 232,
        flags: 1,
        _padding: [0, 0],
    };
    let d2 = SodVertex {
        position: [-1.5, 0.5, -0.2],
        normal: [0.0, 1.0, 0.0],
        palette_index: 232,
        flags: 1,
        _padding: [0, 0],
    };

    ir.vertices = vec![v0, v1, v2, v3, d0, d1, d2];
    ir.indices = vec![
        0, 1, 2, // main wing triangle
        1, 3, 2, // fuselage tail triangle
        4, 5, 6, // decal roundel triangle
    ];

    let root = ir.allocate_node(
        "FUSELAGE",
        None,
        Mat4::IDENTITY.to_cols_array(),
        VisibilityCondition::Always,
        NodeKind::Mesh {
            vertex_offset: 0,
            vertex_count: 4,
            index_offset: 0,
            index_count: 6,
            is_decal: false,
        },
    );

    ir.allocate_node(
        "ROUNDEL_LEFT",
        Some(root),
        Mat4::IDENTITY.to_cols_array(),
        VisibilityCondition::Always,
        NodeKind::Mesh {
            vertex_offset: 4,
            vertex_count: 3,
            index_offset: 6,
            index_count: 3,
            is_decal: true,
        },
    );

    ir
}

/// Loads a model from disk if provided, otherwise returns cleanroom synthetic model.
pub fn load_or_create_model(path: Option<&Path>) -> SodModelIr {
    let Some(path) = path else {
        return create_default_aircraft_ir();
    };

    let bytes = match fs::read(path) {
        Ok(bytes) => bytes,
        Err(e) => {
            eprintln!("[stuntreel] .SOD read failed for {}: {e}", path.display());
            return create_default_aircraft_ir();
        }
    };

    let stem = path.file_stem().and_then(|s| s.to_str()).unwrap_or("MODEL");
    let anchors = load_anchor_table(path);
    let anchor_slice = (!anchors.is_empty()).then_some(anchors.as_slice());
    match transpile_sod(&bytes, stem, anchor_slice) {
        Ok(ir) => ir,
        Err(e) => {
            eprintln!("[stuntreel] .SOD load failed for {}: {e}", path.display());
            create_default_aircraft_ir()
        }
    }
}

/// Evaluates a 50 Hz timeline from an authored `.FLM` file, or synthesizes a circular orbit.
pub fn load_or_synthesize_timeline(path: Option<&Path>, max_ticks: Option<usize>) -> FilmTimeline {
    if let Some(path) = path
        && let Ok(bytes) = fs::read(path)
    {
        match FilmTimeline::from_bytes(&bytes) {
            Ok(timeline) if !timeline.slices().is_empty() => {
                for warning in timeline.warnings() {
                    eprintln!("[stuntreel] {warning}");
                }
                return match max_ticks {
                    Some(limit) => {
                        timeline.truncated_to_ticks(u32::try_from(limit).unwrap_or(u32::MAX))
                    }
                    None => timeline,
                };
            }
            Ok(_) => eprintln!(
                "[stuntreel] {} contained no slices; using synthetic trajectory",
                path.display()
            ),
            Err(err) => eprintln!(
                "[stuntreel] failed to evaluate {}: {err}; using synthetic trajectory",
                path.display()
            ),
        }
    }

    // Synthesize a one-second circular fly-by: 60 keyframes, one per 20 ms tick.
    let count = max_ticks.unwrap_or(60).max(1);
    let mut slices = Vec::with_capacity(count);

    for tick in 0..count {
        let t = tick as f32 * TIMELINE_TICK_SECONDS;
        let eye_x = 40.0 * t.cos();
        let eye_z = 40.0 * t.sin();

        let camera = CameraTransform {
            eye: [eye_x, 15.0, eye_z],
            target: [0.0, 0.0, 0.0],
            fov_degrees: 45.0,
            roll_radians: 0.0,
            cut_from_previous: tick == 0,
        };

        slices.push(SliceKeyframe {
            record: TrajectoryRecord {
                tick: tick as u32,
                camera,
                actors: Vec::new(),
                audio_cues: Vec::new(),
            },
            tick: tick as u32,
            tick_duration: if tick == 0 { 0 } else { 1 },
        });
    }

    FilmTimeline::new(slices, Vec::new())
}

/// Backwards-compatible slice-level loader used by callers that do not sample time.
pub fn load_or_synthesize_trajectory(
    path: Option<&Path>,
    max_ticks: Option<usize>,
) -> Vec<TrajectoryRecord> {
    load_or_synthesize_timeline(path, max_ticks)
        .slices()
        .iter()
        .map(|slice| slice.record.clone())
        .collect()
}

fn is_legacy_refs(trajectory: &[&TrajectoryRecord]) -> bool {
    let has_positive_altitude = trajectory.iter().any(|rec| {
        rec.camera.eye[1] > 0.5 || rec.actors.iter().any(|act| act.position_meters[1] > 0.5)
    });
    if has_positive_altitude {
        return false;
    }

    trajectory.iter().any(|rec| {
        rec.camera.eye[1] < 0.0
            || rec.camera.target[1] < 0.0
            || rec.camera.eye[0] < -500.0
            || rec
                .actors
                .iter()
                .any(|act| act.position_meters[1] < 0.0 || act.position_meters[0] < -500.0)
    })
}

/// Determines whether an input trajectory uses legacy DOS fixed-point coordinates
/// (where altitude above sea level and east coordinates are negative).
#[cfg(test)]
fn is_legacy_trajectory(trajectory: &[TrajectoryRecord]) -> bool {
    let records: Vec<&TrajectoryRecord> = trajectory.iter().collect();
    is_legacy_refs(&records)
}

fn is_legacy_timeline(timeline: &FilmTimeline) -> bool {
    let records: Vec<&TrajectoryRecord> = timeline
        .slices()
        .iter()
        .map(|slice| &slice.record)
        .collect();
    is_legacy_refs(&records)
}

/// Adapts legacy raw negative elevation (.FLM coordinates where -X and -Y are flipped)
/// into the canonical right-handed metric space `[I1]` (+X is Right, +Y is Up).
fn adapt_camera_transform(mut cam: CameraTransform, is_legacy: bool) -> CameraTransform {
    if is_legacy {
        cam.eye[0] = -cam.eye[0];
        cam.eye[1] = -cam.eye[1];
        cam.target[0] = -cam.target[0];
        cam.target[1] = -cam.target[1];
    }
    cam
}

fn adapt_actor_matrix(mut mat: [f32; 16], is_legacy: bool) -> [f32; 16] {
    if is_legacy {
        mat[12] = -mat[12];
        mat[13] = -mat[13];
    }
    mat
}

fn adapt_actor_position(mut pos: [f32; 3], is_legacy: bool) -> [f32; 3] {
    if is_legacy {
        pos[0] = -pos[0];
        pos[1] = -pos[1];
    }
    pos
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

/// Executes headless rendering without window creation.
pub fn run_headless(config: &CliConfig) -> Result<(), String> {
    println!("[stuntreel] Starting headless offscreen presentation...");

    if let Some(out_dir) = &config.out_dir {
        fs::create_dir_all(out_dir)
            .map_err(|e| format!("create output directory {}: {e}", out_dir.display()))?;
    }

    let timeline = load_or_synthesize_timeline(config.flm_path.as_deref(), config.max_ticks);
    let first_record = timeline.sample(0.0);
    println!(
        "[stuntreel] Loaded {} slices, {} ticks ({:.3} s at {} Hz)",
        timeline.slices().len(),
        timeline.total_ticks(),
        timeline.duration_seconds(),
        TIMELINE_HZ
    );
    let is_legacy = is_legacy_timeline(&timeline);

    let cap_ticks = config
        .max_ticks
        .map_or(timeline.total_ticks(), |limit| {
            u32::try_from(limit).unwrap_or(u32::MAX)
        })
        .min(timeline.total_ticks());
    let (start_ord, end_ord) = config
        .frame_range
        .unwrap_or((1, usize::try_from(cap_ticks).unwrap_or(usize::MAX) + 1));
    let start_ord = start_ord.max(1);
    let end_ord = end_ord.min(usize::try_from(cap_ticks).unwrap_or(usize::MAX) + 1);
    let start_tick = start_ord - 1;
    let end_tick = end_ord.saturating_sub(1).max(start_tick + 1);
    let span_seconds = (end_tick - start_tick) as f32 * TIMELINE_TICK_SECONDS;

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
    println!(
        "[stuntreel] camera forward: {}",
        if CAMERA_FORWARD[2] < 0.0 { "-Z" } else { "+Z" }
    );

    // `--all` binds every actor to its archive chunk, so `--sod` and the synthetic
    // fallback model do not participate in parity frames.
    let bundle = match &config.all_path {
        Some(all_path) => {
            let bundle = SceneBundle::from_all(
                &renderer.device,
                &renderer.queue,
                &renderer.pipelines.model_bind_group_layout,
                all_path,
            )?;
            println!(
                "[stuntreel] scene: {} models loaded, {} skipped, {} partial",
                bundle.models.len(),
                bundle.skipped,
                bundle.partial.len()
            );
            for (shape_id, stop) in &bundle.partial {
                println!(
                    "[stuntreel] partial SOD 0x{shape_id:04X} stopped at 0x{:04X} opcode 0x{:04X} ({})",
                    stop.offset, stop.opcode, stop.reason
                );
            }
            Some(bundle)
        }
        None => None,
    };
    let single_model = if bundle.is_some() {
        None
    } else {
        let model_ir = load_or_create_model(config.sod_path.as_deref());
        Some(GpuModel::from_ir(
            &renderer.device,
            &renderer.queue,
            &renderer.pipelines.model_bind_group_layout,
            &model_ir,
        ))
    };

    let mut camera = CameraController::default();

    if config.out_dir.is_none() && video_writer.is_none() {
        let output_path = config
            .output_png
            .clone()
            .unwrap_or_else(|| PathBuf::from("stuntreel_capture.png"));

        if let Some(first_tick) = first_record.as_ref() {
            let cam = adapt_camera_transform(first_tick.camera, is_legacy);
            camera.set_authored_transform(cam);
            println!(
                "[stuntreel] first_tick.camera: eye={:?}, target={:?}, fov={}",
                cam.eye, cam.target, cam.fov_degrees
            );
            for actor in &first_tick.actors {
                let pos = adapt_actor_position(actor.position_meters, is_legacy);
                println!(
                    "[stuntreel] first_tick actor: shape_id=0x{:04X}, pos={:?}",
                    actor.shape_id, pos
                );
            }
        }

        let mut drawn_shapes: Vec<u16> = Vec::new();
        let mut draws: Vec<(&GpuModel, Vec<GpuMeshSlice>, Vec<GpuMeshSlice>)> = Vec::new();

        if let Some(bundle) = &bundle {
            if let Some(world_model) = &bundle.world_model {
                let (base_meshes, decal_meshes) = world_model.collect_visible_meshes(1, 0.0);
                println!(
                    "[stuntreel] world_model draws: {} base meshes, {} decal meshes",
                    base_meshes.len(),
                    decal_meshes.len()
                );
                draws.push((world_model, base_meshes, decal_meshes));
            }
            if let Some(first_tick) = first_record.as_ref() {
                let cam = adapt_camera_transform(first_tick.camera, is_legacy);
                let eye = Vec3::from_array(cam.eye);
                for actor in &first_tick.actors {
                    if drawn_shapes.contains(&actor.shape_id) {
                        continue;
                    }
                    let Some(model) = bundle.get(actor.shape_id) else {
                        continue;
                    };
                    drawn_shapes.push(actor.shape_id);

                    let world_mat = adapt_actor_matrix(actor.world_matrix, is_legacy);
                    let actor_pos = adapt_actor_position(actor.position_meters, is_legacy);
                    model.update_world_matrix(&renderer.queue, &world_mat);
                    let distance = eye.distance(Vec3::from_array(actor_pos));
                    let (base_meshes, decal_meshes) =
                        model.collect_visible_meshes(actor.state_mask, distance);
                    draws.push((model, base_meshes, decal_meshes));
                }
            }
        } else if let Some(gpu_model) = &single_model {
            if let Some(first_tick) = first_record.as_ref()
                && let Some(actor) = first_tick
                    .actors
                    .iter()
                    .find(|a| a.shape_id != 0)
                    .or_else(|| first_tick.actors.first())
            {
                let world_mat = adapt_actor_matrix(actor.world_matrix, is_legacy);
                let actor_pos = adapt_actor_position(actor.position_meters, is_legacy);
                gpu_model.update_world_matrix(&renderer.queue, &world_mat);
                let cam = adapt_camera_transform(first_tick.camera, is_legacy);
                let eye = Vec3::from_array(cam.eye);
                let distance = eye.distance(Vec3::from_array(actor_pos));
                let (base_meshes, decal_meshes) =
                    gpu_model.collect_visible_meshes(actor.state_mask, distance);
                draws.push((gpu_model, base_meshes, decal_meshes));
            } else {
                let (base_meshes, decal_meshes) = gpu_model.collect_visible_meshes(1, 30.0);
                draws.push((gpu_model, base_meshes, decal_meshes));
            }
        }

        let models_slice: Vec<(&GpuModel, &[GpuMeshSlice], &[GpuMeshSlice])> = draws
            .iter()
            .map(|(model, base, decals)| (*model, base.as_slice(), decals.as_slice()))
            .collect();

        renderer
            .render_to_png(
                &camera,
                &models_slice,
                Some(config.clear_index),
                &output_path,
            )
            .map_err(|e| format!("Offscreen render to PNG failed: {e}"))?;

        println!(
            "[stuntreel] Headless frame successfully saved to {}",
            output_path.display()
        );
        return Ok(());
    }

    let frame_step = config.frame_step.max(1);

    if video_writer.is_some() && config.sample_count.is_some() {
        return Err("--sample-count cannot be combined with --video".to_string());
    }

    let mut samples: Vec<(usize, TrajectoryRecord)> = Vec::new();
    if video_writer.is_some() {
        let count = (span_seconds * config.fps).ceil() as usize;
        let tick_step = TIMELINE_HZ / config.fps;
        for index in 0..count {
            let tick = start_tick as f32 + index as f32 * tick_step;
            if tick >= end_tick as f32 {
                break;
            }
            if let Some(record) = timeline.sample(tick) {
                samples.push((index + 1, record));
            }
        }
    } else if let Some(count) = config.sample_count {
        for (index, tick) in even_sample_ticks(start_tick, end_tick, count)
            .into_iter()
            .enumerate()
        {
            if let Some(record) = timeline.sample(tick) {
                samples.push((index + 1, record));
            }
        }
    } else {
        for ordinal in (start_ord..end_ord).step_by(frame_step) {
            let tick = ordinal - 1;
            if tick >= end_tick {
                break;
            }
            if let Some(record) = timeline.sample(tick as f32) {
                samples.push((ordinal, record));
            }
        }
    }

    let mut written_pngs = 0usize;
    let mut written_video_frames = 0usize;

    for (ordinal, record) in samples {
        let cam = adapt_camera_transform(record.camera, is_legacy);
        camera.set_authored_transform(cam);
        let eye = Vec3::from_array(cam.eye);

        let mut drawn_shapes: Vec<u16> = Vec::new();
        let mut draws: Vec<(&GpuModel, Vec<GpuMeshSlice>, Vec<GpuMeshSlice>)> = Vec::new();

        if let Some(bundle) = &bundle {
            if let Some(world_model) = &bundle.world_model {
                let (base_meshes, decal_meshes) = world_model.collect_visible_meshes(1, 0.0);
                if ordinal == start_ord {
                    println!(
                        "[stuntreel] loop frame {ordinal} world_model draws: {} base meshes ({:?}), {} decal meshes ({:?})",
                        base_meshes.len(),
                        base_meshes.first(),
                        decal_meshes.len(),
                        decal_meshes.first()
                    );
                }
                draws.push((world_model, base_meshes, decal_meshes));
            }
            for actor in &record.actors {
                if drawn_shapes.contains(&actor.shape_id) {
                    continue;
                }
                let Some(model) = bundle.get(actor.shape_id) else {
                    continue;
                };
                drawn_shapes.push(actor.shape_id);

                let world_mat = adapt_actor_matrix(actor.world_matrix, is_legacy);
                let actor_pos = adapt_actor_position(actor.position_meters, is_legacy);
                model.update_world_matrix(&renderer.queue, &world_mat);
                let distance = eye.distance(Vec3::from_array(actor_pos));
                let (base_meshes, decal_meshes) =
                    model.collect_visible_meshes(actor.state_mask, distance);
                draws.push((model, base_meshes, decal_meshes));
            }
        } else if let Some(model) = &single_model {
            if let Some(actor) = record
                .actors
                .iter()
                .find(|a| a.shape_id != 0)
                .or_else(|| record.actors.first())
            {
                let world_mat = adapt_actor_matrix(actor.world_matrix, is_legacy);
                let actor_pos = adapt_actor_position(actor.position_meters, is_legacy);
                model.update_world_matrix(&renderer.queue, &world_mat);
                let distance = eye.distance(Vec3::from_array(actor_pos));
                let (base_meshes, decal_meshes) =
                    model.collect_visible_meshes(actor.state_mask, distance);
                draws.push((model, base_meshes, decal_meshes));
            } else {
                let (base_meshes, decal_meshes) = model.collect_visible_meshes(1, 30.0);
                draws.push((model, base_meshes, decal_meshes));
            }
        }

        let models_slice: Vec<(&GpuModel, &[GpuMeshSlice], &[GpuMeshSlice])> = draws
            .iter()
            .map(|(model, base, decals)| (*model, base.as_slice(), decals.as_slice()))
            .collect();

        if config.out_dir.is_some() && video_writer.is_some() {
            let rgba_bytes = renderer
                .render_frame(&camera, &models_slice, Some(config.clear_index))
                .map_err(|e| format!("render frame {ordinal}: {e}"))?;

            if let Some(writer) = &mut video_writer {
                writer
                    .write_frame(&rgba_bytes)
                    .map_err(|e| format!("write video frame {ordinal}: {e}"))?;
                written_video_frames += 1;
            }

            if let Some(out_dir) = &config.out_dir {
                let frame_path = out_dir.join(format!("frame_{ordinal:04}.png"));
                let img = image::RgbaImage::from_raw(config.width, config.height, rgba_bytes)
                    .ok_or_else(|| format!("failed to create image buffer for frame {ordinal}"))?;
                img.save(&frame_path).map_err(|e| {
                    format!("save frame {ordinal} to {}: {e}", frame_path.display())
                })?;
                written_pngs += 1;
            }
        } else if let Some(out_dir) = &config.out_dir {
            let frame_path = out_dir.join(format!("frame_{ordinal:04}.png"));
            renderer
                .render_to_png(
                    &camera,
                    &models_slice,
                    Some(config.clear_index),
                    &frame_path,
                )
                .map_err(|e| format!("render frame {ordinal}: {e}"))?;
            written_pngs += 1;
        } else if let Some(writer) = &mut video_writer {
            let rgba_bytes = renderer
                .render_frame(&camera, &models_slice, Some(config.clear_index))
                .map_err(|e| format!("render frame {ordinal}: {e}"))?;
            writer
                .write_frame(&rgba_bytes)
                .map_err(|e| format!("write video frame {ordinal}: {e}"))?;
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

/// Renderable scene bound for interactive presentation.
enum InteractiveScene {
    /// Single cleanroom or `--sod` model anchored at the world origin.
    Single(GpuModel),
    /// Every `MODEL_*.SOD` chunk of the film's paired `.ALL` archive.
    Archive(SceneBundle),
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
    window: Option<Arc<Window>>,
    device: Option<wgpu::Device>,
    queue: Option<wgpu::Queue>,
    surface: Option<wgpu::Surface<'static>>,
    surface_config: Option<wgpu::SurfaceConfiguration>,
    pipelines: Option<RenderPipelines>,
    palette_lut: Option<PaletteLut>,
    camera_resources: Option<CameraGpuResources>,
    depth_view: Option<wgpu::TextureView>,
    camera: CameraController,
    scene: Option<InteractiveScene>,
    timeline: FilmTimeline,
    is_legacy: bool,
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
    fn new(config: CliConfig) -> Self {
        let timeline = load_or_synthesize_timeline(config.flm_path.as_deref(), config.max_ticks);
        let is_legacy = is_legacy_timeline(&timeline);
        Self {
            config,
            window: None,
            device: None,
            queue: None,
            surface: None,
            surface_config: None,
            pipelines: None,
            palette_lut: None,
            camera_resources: None,
            depth_view: None,
            camera: CameraController::default(),
            scene: None,
            timeline,
            is_legacy,
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
        if self.paused {
            return;
        }
        let total_ticks = self.timeline.total_ticks();
        if total_ticks == 0 {
            return;
        }
        self.current_tick = (self.current_tick + dt * TIMELINE_HZ) % total_ticks as f32;
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
        ) = (
            &self.device,
            &self.queue,
            &self.surface,
            &self.surface_config,
            &self.pipelines,
            &self.camera_resources,
            &self.palette_lut,
            &self.depth_view,
        )
        else {
            return;
        };

        let record = self.timeline.sample(self.current_tick);
        if self.camera.mode == CameraMode::Authored
            && let Some(record) = record.as_ref()
        {
            let cam = adapt_camera_transform(record.camera, self.is_legacy);
            self.camera.set_authored_transform(cam);
        }
        let eye = self.camera.eye_position();

        // One draw per distinct shape: a shared model uniform cannot hold two poses.
        let mut draws: Vec<(&GpuModel, Vec<GpuMeshSlice>, Vec<GpuMeshSlice>)> = Vec::new();
        match self.scene.as_ref() {
            Some(InteractiveScene::Single(model)) => {
                if let Some(record) = record
                    && let Some(actor) = record
                        .actors
                        .iter()
                        .find(|a| a.shape_id != 0)
                        .or_else(|| record.actors.first())
                {
                    let world_mat = adapt_actor_matrix(actor.world_matrix, self.is_legacy);
                    let actor_pos = adapt_actor_position(actor.position_meters, self.is_legacy);
                    model.update_world_matrix(queue, &world_mat);
                    let distance = eye.distance(Vec3::from_array(actor_pos));
                    let (base, decals) = model.collect_visible_meshes(actor.state_mask, distance);
                    draws.push((model, base, decals));
                } else {
                    let (base, decals) = model.collect_visible_meshes(1, eye.length());
                    draws.push((model, base, decals));
                }
            }
            Some(InteractiveScene::Archive(bundle)) => {
                if let Some(world_model) = &bundle.world_model {
                    let (base, decals) = world_model.collect_visible_meshes(1, 0.0);
                    draws.push((world_model, base, decals));
                }
                if let Some(record) = record {
                    let mut drawn_shapes: Vec<u16> = Vec::new();
                    for actor in &record.actors {
                        if drawn_shapes.contains(&actor.shape_id) {
                            continue;
                        }
                        let Some(model) = bundle.get(actor.shape_id) else {
                            continue;
                        };
                        drawn_shapes.push(actor.shape_id);

                        let world_mat = adapt_actor_matrix(actor.world_matrix, self.is_legacy);
                        let actor_pos = adapt_actor_position(actor.position_meters, self.is_legacy);
                        model.update_world_matrix(queue, &world_mat);
                        let distance = eye.distance(Vec3::from_array(actor_pos));
                        let (base, decals) =
                            model.collect_visible_meshes(actor.state_mask, distance);
                        draws.push((model, base, decals));
                    }
                }
            }
            None => return,
        }

        let cam_uniform = self.camera.build_uniform();
        cam_res.upload(queue, &cam_uniform);

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

            // Pass 1: Base solid geometry
            rpass.set_pipeline(&pipelines.base_pipeline);
            rpass.set_bind_group(0, &cam_res.bind_group, &[]);
            rpass.set_bind_group(1, &lut.bind_group, &[]);
            for (model, base_meshes, _) in &draws {
                if base_meshes.is_empty() {
                    continue;
                }
                rpass.set_bind_group(2, &model.model_bind_group, &[]);
                rpass.set_vertex_buffer(0, model.vertex_buffer.slice(..));
                rpass.set_index_buffer(model.index_buffer.slice(..), wgpu::IndexFormat::Uint32);

                for mesh in base_meshes {
                    rpass.draw_indexed(
                        mesh.index_offset..(mesh.index_offset + mesh.index_count),
                        mesh.vertex_offset,
                        0..1,
                    );
                }
            }

            // Pass 2: Decal pass with Invariant [I5] hardware depth bias
            rpass.set_pipeline(&pipelines.decal_pipeline);
            for (model, _, decal_meshes) in &draws {
                if decal_meshes.is_empty() {
                    continue;
                }
                rpass.set_bind_group(2, &model.model_bind_group, &[]);
                rpass.set_vertex_buffer(0, model.vertex_buffer.slice(..));
                rpass.set_index_buffer(model.index_buffer.slice(..), wgpu::IndexFormat::Uint32);

                for mesh in decal_meshes {
                    rpass.draw_indexed(
                        mesh.index_offset..(mesh.index_offset + mesh.index_count),
                        mesh.vertex_offset,
                        0..1,
                    );
                }
            }

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

        let scene = match &self.config.all_path {
            Some(all_path) => match SceneBundle::from_all(
                &device,
                &queue,
                &pipelines.model_bind_group_layout,
                all_path,
            ) {
                Ok(bundle) => {
                    println!(
                        "[stuntreel] scene: {} models loaded, {} skipped, {} partial",
                        bundle.models.len(),
                        bundle.skipped,
                        bundle.partial.len()
                    );
                    InteractiveScene::Archive(bundle)
                }
                Err(e) => {
                    eprintln!("[stuntreel] {e}");
                    event_loop.exit();
                    return;
                }
            },
            None => {
                let model_ir = load_or_create_model(self.config.sod_path.as_deref());
                InteractiveScene::Single(GpuModel::from_ir(
                    &device,
                    &queue,
                    &pipelines.model_bind_group_layout,
                    &model_ir,
                ))
            }
        };

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
        self.scene = Some(scene);

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
    if subcommand_args.next().as_deref() == Some("parity") {
        if let Err(e) = parity::run(subcommand_args) {
            eprintln!("[stuntreel error] {e}");
            std::process::exit(1);
        }
        return;
    }

    let config = match CliConfig::parse() {
        Ok(c) => c,
        Err(err) => {
            eprintln!("[stuntreel error] {err}");
            CliConfig::print_usage();
            std::process::exit(1);
        }
    };

    if config.headless {
        if let Err(e) = run_headless(&config) {
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

    let mut app = WindowApp::new(config);
    if let Err(e) = event_loop.run_app(&mut app) {
        eprintln!("[stuntreel] Application error: {e}");
        std::process::exit(1);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_even_sample_ticks_include_endpoints() {
        assert_eq!(even_sample_ticks(0, 3, 3), vec![0.0, 1.0, 2.0]);
        assert_eq!(even_sample_ticks(0, 1342, 3), vec![0.0, 670.5, 1341.0]);
        assert_eq!(even_sample_ticks(5, 6, 1), vec![5.0]);
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
            ]
            .into_iter(),
        )
        .expect("parse succeeds");

        assert_eq!(config.frame_range, Some((2, 10)));
        assert_eq!(config.frame_step, 3);
        assert_eq!(config.sample_count, Some(5));
        assert_eq!(config.fps, 50.0);

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
    fn test_is_legacy_trajectory_detection() {
        let rec_legacy = TrajectoryRecord {
            tick: 0,
            camera: CameraTransform {
                eye: [3306.0, -14.0, 2614.0],
                target: [0.0, 0.0, 0.0],
                fov_degrees: 45.0,
                roll_radians: 0.0,
                cut_from_previous: false,
            },
            actors: Vec::new(),
            audio_cues: Vec::new(),
        };
        assert!(is_legacy_trajectory(&[rec_legacy]));

        let rec_legacy_x_at_sea_level = TrajectoryRecord {
            tick: 0,
            camera: CameraTransform {
                eye: [-3306.0, 0.0, 2614.0],
                target: [0.0, 0.0, 0.0],
                fov_degrees: 45.0,
                roll_radians: 0.0,
                cut_from_previous: false,
            },
            actors: Vec::new(),
            audio_cues: Vec::new(),
        };
        assert!(is_legacy_trajectory(&[rec_legacy_x_at_sea_level]));

        let rec_metric = TrajectoryRecord {
            tick: 0,
            camera: CameraTransform {
                eye: [0.0, 10.0, 50.0],
                target: [0.0, 0.0, 0.0],
                fov_degrees: 45.0,
                roll_radians: 0.0,
                cut_from_previous: false,
            },
            actors: Vec::new(),
            audio_cues: Vec::new(),
        };
        assert!(!is_legacy_trajectory(&[rec_metric]));

        let rec_metric_west = TrajectoryRecord {
            tick: 0,
            camera: CameraTransform {
                eye: [-1200.0, 50.0, 0.0],
                target: [0.0, 50.0, 0.0],
                fov_degrees: 45.0,
                roll_radians: 0.0,
                cut_from_previous: false,
            },
            actors: Vec::new(),
            audio_cues: Vec::new(),
        };
        assert!(!is_legacy_trajectory(&[rec_metric_west]));
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

    #[test]
    fn test_adapt_coordinate_transforms() {
        let cam = CameraTransform {
            eye: [-100.0, -20.0, 300.0],
            target: [-50.0, -10.0, 200.0],
            fov_degrees: 45.0,
            roll_radians: 0.0,
            cut_from_previous: false,
        };
        let adapted = adapt_camera_transform(cam, true);
        assert_eq!(adapted.eye, [100.0, 20.0, 300.0]);
        assert_eq!(adapted.target, [50.0, 10.0, 200.0]);

        let not_adapted = adapt_camera_transform(cam, false);
        assert_eq!(not_adapted.eye, [-100.0, -20.0, 300.0]);

        let mut mat = [0.0; 16];
        mat[12] = -123.0;
        mat[13] = -456.0;
        mat[14] = 789.0;
        let adapted_mat = adapt_actor_matrix(mat, true);
        assert_eq!(adapted_mat[12], 123.0);
        assert_eq!(adapted_mat[13], 456.0);
        assert_eq!(adapted_mat[14], 789.0);

        let not_adapted_mat = adapt_actor_matrix(mat, false);
        assert_eq!(not_adapted_mat[12], -123.0);
        assert_eq!(not_adapted_mat[13], -456.0);
        assert_eq!(not_adapted_mat[14], 789.0);
    }
}
