//! Interactive winit playback with the authored camera or Free-Cam.
//!
//! The window owns input, time and the camera; the Renderer owns every GPU object, the surface,
//! the letterbox and the resize. Opening the renderer here is the thin, CI-untested window
//! adapter recorded by ADR 0006 and the unit C brief.

use std::sync::Arc;
use std::time::Instant;

use stunt_core::flm::TIMELINE_HZ;
use stunt_core::scene::FilmScene;
use stunt_render::{CameraController, CameraMode, RenderError, RenderOptions, Renderer};
use winit::application::ApplicationHandler;
use winit::dpi::LogicalSize;
use winit::event::{DeviceEvent, ElementState, KeyEvent, WindowEvent};
use winit::event_loop::ActiveEventLoop;
use winit::keyboard::{Key, NamedKey};
use winit::window::{Window, WindowId};

use crate::config::CliConfig;
use crate::headless::playback_ticks;

/// Reports why opening the window renderer failed, in the same words as the old bootstrap.
fn log_open_error(error: &RenderError) {
    match error {
        RenderError::NoGpuAdapter => {
            eprintln!("[stuntreel] No suitable GPU adapter for window");
        }
        RenderError::DeviceRequest(message) => {
            eprintln!("[stuntreel] Failed to create device: {message}");
        }
        RenderError::SurfaceCreate(message) => {
            eprintln!("[stuntreel] Failed to create surface: {message}");
        }
        other => eprintln!("[stuntreel] Failed to create renderer: {other}"),
    }
}

/// Interactive window application state.
pub(crate) struct WindowApp {
    config: CliConfig,
    /// The film scene, built once before the event loop and reused across resumes.
    scene: FilmScene,
    playback_ticks: u32,
    window: Option<Arc<Window>>,
    /// The renderer opened on the window's surface, or None before the first resume.
    renderer: Option<Renderer>,
    camera: CameraController,
    current_tick: f32,
    paused: bool,
    last_frame_time: Instant,
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
            renderer: None,
            camera: CameraController::default(),
            current_tick: 0.0,
            paused: false,
            last_frame_time: Instant::now(),
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

        let Some(renderer) = self.renderer.as_mut() else {
            return;
        };

        let frame = self.scene.frame(self.current_tick);
        if self.camera.mode == CameraMode::Authored {
            self.camera.set_authored_transform(frame.camera);
        }
        if let Err(error) = renderer.draw(&frame, Some(&self.camera)) {
            if matches!(error, RenderError::SurfaceOutOfMemory) {
                eprintln!("[stuntreel] Surface out of memory");
            } else {
                eprintln!("[stuntreel] Render failed: {error}");
            }
        }
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
            Ok(window) => Arc::new(window),
            Err(e) => {
                eprintln!("[stuntreel] Failed to create window: {e}");
                event_loop.exit();
                return;
            }
        };

        let options = RenderOptions {
            clear_palette_index: self.config.clear_index,
            software_only: false,
        };
        let mut renderer = match Renderer::surface(&self.scene, Arc::clone(&window), options) {
            Ok(renderer) => renderer,
            Err(error) => {
                log_open_error(&error);
                event_loop.exit();
                return;
            }
        };
        // The surface opens at 1x1; this explicit resize is where it learns the window size.
        let size = window.inner_size();
        renderer.resize(size.width, size.height);

        self.window = Some(Arc::clone(&window));
        self.renderer = Some(renderer);

        window.request_redraw();
    }

    fn window_event(&mut self, event_loop: &ActiveEventLoop, _id: WindowId, event: WindowEvent) {
        match event {
            WindowEvent::CloseRequested => {
                event_loop.exit();
            }
            WindowEvent::Resized(new_size) => {
                if let Some(renderer) = self.renderer.as_mut() {
                    renderer.resize(new_size.width, new_size.height);
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
