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
use scene::SceneBundle;
use stunt_core::contracts::{
    CameraTransform, NodeKind, SodModelIr, SodVertex, TrajectoryRecord, VisibilityCondition,
    get_palette_rgb_float,
};
use stunt_core::flm::{CAMERA_FORWARD, FlmPlayer};
use stunt_core::sod::transpile_sod;
use stunt_render::{
    ASPECT_4_3, CameraController, CameraGpuResources, CameraMode, GpuMeshSlice, GpuModel,
    HeadlessRenderer, PaletteLut, RenderPipelines,
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
    /// Half-open `[start, end)` trajectory ordinals to render; `None` renders all.
    pub frame_range: Option<(usize, usize)>,
    pub width: u32,
    pub height: u32,
    pub clear_index: u8,
    pub headless: bool,
    pub output_png: Option<PathBuf>,
    pub max_ticks: Option<usize>,
}

impl CliConfig {
    pub fn parse() -> Result<Self, String> {
        let mut args = env::args().skip(1);
        let mut flm_path = None;
        let mut sod_path = None;
        let mut all_path = None;
        let mut out_dir = None;
        let mut frame_range = None;
        let mut width = 320u32;
        let mut height = 240u32;
        let mut clear_index = 180u8;
        let mut headless = false;
        let mut output_png = None;
        let mut max_ticks = None;

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
                other if !other.starts_with('-') && flm_path.is_none() => {
                    flm_path = Some(PathBuf::from(other));
                }
                other => {
                    return Err(format!("Unrecognized argument: {other}"));
                }
            }
        }

        if width == 0 || height == 0 {
            return Err("Framebuffer dimensions must be non-zero".to_string());
        }
        if !(width * 4).is_multiple_of(256) {
            return Err("row pitch must be 256-byte aligned".to_string());
        }

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
        println!("  --out-dir <dir>      Render every trajectory tick to <dir>/frame_NNNN.png");
        println!(
            "  --frames <A..B>      Half-open ordinals to render with --out-dir (default: all)"
        );
        println!(
            "  --width <px>         Offscreen framebuffer width (default 320, 256-byte pitch)"
        );
        println!("  --height <px>        Offscreen framebuffer height (default 240)");
        println!("  --clear-index <i>    Mode 13h palette index used to clear the framebuffer");
        println!("  --headless           Run in offscreen headless mode without opening a window");
        println!("  --output, -o <file>  Save offscreen rendered frame to PNG file");
        println!("  --ticks <count>      Maximum simulation ticks to evaluate");
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
    match transpile_sod(&bytes, stem) {
        Ok(ir) => ir,
        Err(e) => {
            eprintln!("[stuntreel] .SOD load failed for {}: {e}", path.display());
            create_default_aircraft_ir()
        }
    }
}

/// Evaluates trajectory records from an authored .FLM file, or synthesizes a circular orbit.
pub fn load_or_synthesize_trajectory(
    path: Option<&Path>,
    max_ticks: Option<usize>,
) -> Vec<TrajectoryRecord> {
    let authored = path.and_then(|p| {
        let bytes = fs::read(p).ok()?;
        let mut player = FlmPlayer::new(&bytes).ok()?;
        let limit = max_ticks.unwrap_or(600);
        let mut records = Vec::new();
        while let Some(rec) = player.step_tick() {
            records.push(rec);
            if records.len() >= limit {
                break;
            }
        }
        if let Some(err) = player.take_last_error() {
            eprintln!("[stuntreel] trajectory ended early: {err}");
        }
        (!records.is_empty()).then_some(records)
    });
    if let Some(records) = authored {
        return records;
    }

    // Synthesize 60-tick circular fly-by trajectory
    let count = max_ticks.unwrap_or(60);
    let mut records = Vec::with_capacity(count);

    for tick in 0..count {
        let t = tick as f32 * 0.1;
        let eye_x = 40.0 * t.cos();
        let eye_z = 40.0 * t.sin();

        let camera = CameraTransform {
            eye: [eye_x, 15.0, eye_z],
            target: [0.0, 0.0, 0.0],
            fov_degrees: 45.0,
            roll_radians: 0.0,
            cut_from_previous: tick == 0,
        };

        records.push(TrajectoryRecord {
            tick: tick as u32,
            camera,
            actors: Vec::new(),
            audio_cues: Vec::new(),
        });
    }

    records
}

/// Executes headless rendering without window creation.
pub fn run_headless(config: &CliConfig) -> Result<(), String> {
    println!("[stuntreel] Starting headless offscreen presentation...");

    if let Some(out_dir) = &config.out_dir {
        if config.all_path.is_none() {
            return Err("--out-dir requires --all".to_string());
        }
        fs::create_dir_all(out_dir)
            .map_err(|e| format!("create output directory {}: {e}", out_dir.display()))?;
    }

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
                    "[stuntreel] partial SOD 0x{shape_id:04X} stopped at 0x{:04X} opcode 0x{:04X}",
                    stop.offset, stop.opcode
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

    let trajectory = load_or_synthesize_trajectory(config.flm_path.as_deref(), config.max_ticks);
    println!("[stuntreel] Loaded {} trajectory ticks", trajectory.len());

    let mut camera = CameraController::default();
    let Some(out_dir) = &config.out_dir else {
        let Some(gpu_model) = &single_model else {
            return Err("--all requires --out-dir".to_string());
        };
        let (base_meshes, decal_meshes) = gpu_model.collect_visible_meshes(1, 30.0);

        let output_path = config
            .output_png
            .clone()
            .unwrap_or_else(|| PathBuf::from("stuntreel_capture.png"));

        if let Some(first_tick) = trajectory.first() {
            camera.set_authored_transform(first_tick.camera);
        }

        let models_slice: [(&GpuModel, &[GpuMeshSlice], &[GpuMeshSlice]); 1] =
            [(gpu_model, &base_meshes, &decal_meshes)];

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
    };

    let Some(bundle) = &bundle else {
        return Err("--out-dir requires --all".to_string());
    };

    let (start, end) = config.frame_range.unwrap_or((1, trajectory.len() + 1));
    let mut written = 0usize;

    for (idx, record) in trajectory.iter().enumerate() {
        let ordinal = idx + 1;
        if ordinal < start || ordinal >= end {
            continue;
        }

        camera.set_authored_transform(record.camera);
        let eye = Vec3::from_array(record.camera.eye);

        // One draw per distinct shape: a shared model uniform cannot hold two poses.
        let mut drawn_shapes: Vec<u16> = Vec::new();
        let mut draws: Vec<(&GpuModel, Vec<GpuMeshSlice>, Vec<GpuMeshSlice>)> = Vec::new();
        for actor in &record.actors {
            if drawn_shapes.contains(&actor.shape_id) {
                continue;
            }
            let Some(model) = bundle.get(actor.shape_id) else {
                continue;
            };
            drawn_shapes.push(actor.shape_id);

            model.update_world_matrix(&renderer.queue, &actor.world_matrix);
            let distance = eye.distance(Vec3::from_array(actor.position_meters));
            let (base_meshes, decal_meshes) =
                model.collect_visible_meshes(actor.state_mask, distance);
            draws.push((model, base_meshes, decal_meshes));
        }

        let models_slice: Vec<(&GpuModel, &[GpuMeshSlice], &[GpuMeshSlice])> = draws
            .iter()
            .map(|(model, base, decals)| (*model, base.as_slice(), decals.as_slice()))
            .collect();

        let frame_path = out_dir.join(format!("frame_{ordinal:04}.png"));
        renderer
            .render_to_png(
                &camera,
                &models_slice,
                Some(config.clear_index),
                &frame_path,
            )
            .map_err(|e| format!("render frame {ordinal}: {e}"))?;
        written += 1;
    }

    println!(
        "[stuntreel] Wrote {written} parity frames to {}",
        out_dir.display()
    );
    Ok(())
}

/// Simulation ticks advance at one of two authored rates; interactive playback uses the
/// 30 Hz default while the headless path renders one record per ordinal.
const INTERACTIVE_TICK_HZ: f32 = 30.0;

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
    trajectory: Vec<TrajectoryRecord>,
    current_tick_idx: usize,
    tick_accumulator: f32,
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
        let trajectory =
            load_or_synthesize_trajectory(config.flm_path.as_deref(), config.max_ticks);
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
            trajectory,
            current_tick_idx: 0,
            tick_accumulator: 0.0,
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

    /// Advances the authored timeline at the fixed simulation rate `[I4]`.
    fn advance_timeline(&mut self, dt: f32) {
        if self.paused || self.trajectory.is_empty() {
            return;
        }
        let tick_duration = 1.0 / INTERACTIVE_TICK_HZ;
        self.tick_accumulator += dt;
        while self.tick_accumulator >= tick_duration {
            self.tick_accumulator -= tick_duration;
            self.current_tick_idx = (self.current_tick_idx + 1) % self.trajectory.len();
        }
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

        let record = self.trajectory.get(self.current_tick_idx);
        if self.camera.mode == CameraMode::Authored
            && let Some(record) = record
        {
            self.camera.set_authored_transform(record.camera);
        }
        let eye = self.camera.eye_position();

        // One draw per distinct shape: a shared model uniform cannot hold two poses.
        let mut draws: Vec<(&GpuModel, Vec<GpuMeshSlice>, Vec<GpuMeshSlice>)> = Vec::new();
        match self.scene.as_ref() {
            Some(InteractiveScene::Single(model)) => {
                let (base, decals) = model.collect_visible_meshes(1, eye.length());
                draws.push((model, base, decals));
            }
            Some(InteractiveScene::Archive(bundle)) => {
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

                        model.update_world_matrix(queue, &actor.world_matrix);
                        let distance = eye.distance(Vec3::from_array(actor.position_meters));
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
