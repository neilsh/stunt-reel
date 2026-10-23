//! Interactive winit playback with the authored camera or Free-Cam.

use std::sync::Arc;
use std::time::Instant;

use stunt_core::flm::TIMELINE_HZ;
use stunt_core::scene::FilmScene;
use stunt_render::{
    ASPECT_4_3, CameraController, CameraGpuResources, CameraMode, PaletteLut, RenderPipelines,
    SceneRenderer,
};
use winit::application::ApplicationHandler;
use winit::dpi::LogicalSize;
use winit::event::{DeviceEvent, ElementState, KeyEvent, WindowEvent};
use winit::event_loop::ActiveEventLoop;
use winit::keyboard::{Key, NamedKey};
use winit::window::{Window, WindowId};

use crate::config::CliConfig;
use crate::headless::playback_ticks;

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
pub(crate) struct WindowApp {
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
    pub(crate) fn new(config: CliConfig, scene: FilmScene) -> Self {
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
            &mut self.palette_lut,
            &self.depth_view,
            &mut self.scene_renderer,
        )
        else {
            return;
        };

        let frame = self.scene.frame(self.current_tick);
        lut.set_controls(queue, frame.palette);
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
        let (cr, cg, cb) = lut.rgb_float(self.config.clear_index);
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

/// The window surface format: plain `Rgba8Unorm`/`Bgra8Unorm` when offered, else the first.
///
/// The palette LUT holds display-ready Mode 13h colours, as the headless `Rgba8Unorm` target
/// stores them; an sRGB surface would encode them a second time and wash the window out.
fn pick_surface_format(formats: &[wgpu::TextureFormat]) -> wgpu::TextureFormat {
    formats
        .iter()
        .copied()
        .find(|f| {
            matches!(
                f,
                wgpu::TextureFormat::Rgba8Unorm | wgpu::TextureFormat::Bgra8Unorm
            )
        })
        .unwrap_or(formats[0])
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
        let surface_format = pick_surface_format(&surface_caps.formats);

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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_surface_format_prefers_non_srgb() {
        use wgpu::TextureFormat::{Bgra8Unorm, Bgra8UnormSrgb, Rgb10a2Unorm, Rgba8UnormSrgb};
        assert_eq!(
            pick_surface_format(&[Bgra8UnormSrgb, Bgra8Unorm]),
            Bgra8Unorm
        );
        assert_eq!(
            pick_surface_format(&[
                Rgb10a2Unorm,
                Rgba8UnormSrgb,
                wgpu::TextureFormat::Rgba8Unorm
            ]),
            wgpu::TextureFormat::Rgba8Unorm
        );
        // Nothing plain on offer: the surface's first format.
        assert_eq!(
            pick_surface_format(&[Bgra8UnormSrgb, Rgb10a2Unorm]),
            Bgra8UnormSrgb
        );
    }
}
