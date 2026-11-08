//! One renderer entry point for offscreen readback and a presented surface.
//!
//! Opens an instance, an adapter and a device through a single acquisition policy, uploads the
//! film's shapes once, and then draws one `SceneFrame` per `Renderer::draw` call. The destination is
//! fixed at open: an Offscreen renderer reads every drawn page back and hands it to its `PageSink`,
//! a surface renderer presents it. The caller never branches on the destination and never sees a
//! readback.
//!
//! Invariants:
//! - `[I3]` the frame palette is uploaded into the 256x32 LUT before anything is drawn, and the
//!   clear colour is a palette index.
//! - `[I5]` base meshes of every draw precede the decal meshes of every draw.
//! - `[I6]` offscreen pages are 320x240 unless the caller asks otherwise; a surface keeps a 4:3
//!   letterbox inside its window.
//! - `[I7]` stays untouched: nothing here decodes or reads files.
//!
//! No public signature names a GPU handle type. The surface constructor bounds its window with
//! the raw-window-handle windowing traits, the recorded exception.

use std::fmt;
use std::sync::{Arc, OnceLock};

use stunt_core::credits::{ClipRect, CreditLines, draw_credits};
use stunt_core::font::PFont;
use stunt_core::scene::{FilmScene, SceneFrame};

use crate::camera::{CameraController, CameraGpuResources};
use crate::palette::PaletteLut;
use crate::pipeline::{LAYER_OVERLAY, PLANE_FORMAT, RenderPipelines};
use crate::scene_renderer::SceneRenderer;

/// Base Mode 13h framebuffer width in pixels.
pub const MODE13H_WIDTH: usize = 320;

/// Original Mode 13h framebuffer height in pixels.
pub const MODE13H_HEIGHT: usize = 200;

/// Aspect-corrected 4:3 presentation height in pixels ($200 \times 1.2$).
pub const ASPECT_CORRECTED_HEIGHT: usize = 240;

/// Default offscreen page width in pixels (Mode 13h).
pub const DEFAULT_PAGE_WIDTH: u32 = 320;

/// Default offscreen page height in pixels (4:3 aspect correction of 320x200).
pub const DEFAULT_PAGE_HEIGHT: u32 = 240;

/// Default palette index the target is cleared with: daytime horizon sky blue.
pub const DEFAULT_CLEAR_PALETTE_INDEX: u8 = 180;

/// Colour format of the offscreen readback target.
const COLOR_FORMAT: wgpu::TextureFormat = wgpu::TextureFormat::Rgba8Unorm;

/// Depth format of the offscreen and surface passes.
const DEPTH_FORMAT: wgpu::TextureFormat = wgpu::TextureFormat::Depth24Plus;

/// Pixel geometry of a page: the offscreen target or the configured window surface.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct PageSize {
    /// Width in pixels, at least 1.
    pub width: u32,
    /// Height in pixels, at least 1.
    pub height: u32,
}

impl PageSize {
    /// A page of width x height pixels; zero dimensions clamp to 1.
    #[must_use]
    pub fn new(width: u32, height: u32) -> Self {
        Self {
            width: width.max(1),
            height: height.max(1),
        }
    }

    /// Number of pixels in the page.
    #[must_use]
    pub fn pixel_count(self) -> usize {
        self.width as usize * self.height as usize
    }
}

impl Default for PageSize {
    fn default() -> Self {
        Self::new(DEFAULT_PAGE_WIDTH, DEFAULT_PAGE_HEIGHT)
    }
}

/// An offscreen destination: the page size plus how many target rows the 3D scene fills.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Offscreen {
    /// Fixed page size; `Renderer::resize` is a no-op offscreen.
    pub size: PageSize,
    /// When set, the scene is drawn into the top this-many rows only, with the vertical focal
    /// scale kept, as PLAYONE.EXE does above its button bar. None fills the target.
    pub viewport_rows: Option<u32>,
}

impl Offscreen {
    /// An offscreen target of width x height pixels filling the whole target.
    #[must_use]
    pub fn new(width: u32, height: u32) -> Self {
        Self {
            size: PageSize::new(width, height),
            viewport_rows: None,
        }
    }

    /// Draws the 3D scene into the top rows target rows and leaves the rest at the clear
    /// palette index.
    #[must_use]
    pub fn with_viewport_rows(self, rows: u32) -> Self {
        Self {
            viewport_rows: Some(rows),
            ..self
        }
    }
}

impl Default for Offscreen {
    fn default() -> Self {
        Self::new(DEFAULT_PAGE_WIDTH, DEFAULT_PAGE_HEIGHT)
    }
}

/// What every open renderer does identically for both destinations.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct RenderOptions {
    /// Mode 13h palette index the target is cleared with, from the frame's loaded palette.
    pub clear_palette_index: u8,
    /// Restrict adapter acquisition to the software fallback adapter.
    ///
    /// The normal policy already falls back to a software adapter when no other is available;
    /// setting this only forces that attempt, for tests that must exercise the software path.
    pub software_only: bool,
}

impl Default for RenderOptions {
    fn default() -> Self {
        Self {
            clear_palette_index: DEFAULT_CLEAR_PALETTE_INDEX,
            software_only: false,
        }
    }
}

/// A `PageSink` could not consume a page; a sink failure is terminal.
#[derive(Debug, Clone, PartialEq, Eq, thiserror::Error)]
#[error("{message}")]
pub struct SinkError {
    message: String,
}

impl SinkError {
    /// A sink failure described by its message.
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self {
            message: message.into(),
        }
    }

    /// The failure message.
    #[must_use]
    pub fn message(&self) -> &str {
        &self.message
    }
}

/// One rendered page: tightly packed RGBA8 pixels and its two plane views.
///
/// The GPU writes one `layer << 8 | palette index` word per pixel. The page splits that word
/// once, so a sink reads [`RenderedPage::indices`] and [`RenderedPage::layers`] instead of
/// repacking it.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct RenderedPage {
    size: PageSize,
    rgba: Vec<u8>,
    indices: Vec<u8>,
    layers: Vec<u32>,
}

impl RenderedPage {
    /// Builds a page, refusing buffers that do not match the size.
    ///
    /// `rgba` is `size.pixel_count() * 4` bytes; `plane` is one `layer << 8 | unlit palette index`
    /// word per pixel (uncovered pixels: the clear index on `LAYER_NONE`), split here into
    /// [`RenderedPage::indices`] and [`RenderedPage::layers`]. Layers stay u32; the render
    /// store's writer checks the narrowing to u16.
    ///
    /// # Errors
    /// Returns [`RenderError::Readback`] if `rgba` is not `size.pixel_count() * 4` bytes or
    /// `plane` is not `size.pixel_count()` words.
    pub fn new(size: PageSize, rgba: Vec<u8>, plane: &[u32]) -> Result<Self, RenderError> {
        let pixels = size.pixel_count();
        if rgba.len() != pixels * 4 {
            return Err(RenderError::Readback(format!(
                "page is {pixels} pixels but {} RGBA bytes were read back",
                rgba.len()
            )));
        }
        if plane.len() != pixels {
            return Err(RenderError::Readback(format!(
                "page is {pixels} pixels but {} plane words were read back",
                plane.len()
            )));
        }
        let indices = plane.iter().map(|word| (*word & 0xFF) as u8).collect();
        let layers = plane.iter().map(|word| *word >> 8).collect();
        Ok(Self {
            size,
            rgba,
            indices,
            layers,
        })
    }

    /// The page geometry.
    #[must_use]
    pub fn size(&self) -> PageSize {
        self.size
    }

    /// Page width in pixels.
    #[must_use]
    pub fn width(&self) -> u32 {
        self.size.width
    }

    /// Page height in pixels.
    #[must_use]
    pub fn height(&self) -> u32 {
        self.size.height
    }

    /// Tightly packed RGBA8 pixels, one row after another with no pitch padding.
    #[must_use]
    pub fn rgba(&self) -> &[u8] {
        &self.rgba
    }

    /// One palette index per pixel, top row first: the low byte of each plane word.
    #[must_use]
    pub fn indices(&self) -> &[u8] {
        &self.indices
    }

    /// One layer id per pixel, top row first: the plane word's layer.
    ///
    /// The render store keeps a u16 per pixel; its writer checks that narrowing rather than
    /// truncating silently.
    #[must_use]
    pub fn layers(&self) -> &[u32] {
        &self.layers
    }
}

/// Draws `lines` over `page` as `PLAYONE.EXE` draws them over its 320x200 page, centred in the
/// view: the top `viewport_rows` page rows when set, else the whole page. Each Mode 13h pixel
/// covers the page pixels it scales to; they take the palette index, its unlit `palette`
/// colour and [`LAYER_OVERLAY`].
fn paint_credits(
    page: &mut RenderedPage,
    font: &PFont,
    lines: &CreditLines,
    viewport_rows: Option<u32>,
    palette: &[(u8, u8, u8); 256],
) {
    #[expect(
        clippy::cast_possible_wrap,
        reason = "page sizes are bounded by the GPU texture limit, far inside i32"
    )]
    let (width, height) = (page.width() as i32, page.height() as i32);
    #[expect(
        clippy::cast_possible_truncation,
        clippy::cast_possible_wrap,
        reason = "the 320x200 Mode 13h constants"
    )]
    let (mode_w, mode_h) = (MODE13H_WIDTH as i32, MODE13H_HEIGHT as i32);
    // A row count past i32::MAX wraps negative and draws nothing, as it always has.
    let view_rows = viewport_rows.map_or(height, u32::cast_signed);
    let rect = ClipRect {
        left: 0,
        top: 0,
        right: mode_w - 1,
        bottom: view_rows * mode_h / height - 1,
    };
    draw_credits(font, lines, rect, &mut |x, y, index| {
        if !(0..mode_w).contains(&x) || !(0..mode_h).contains(&y) {
            return;
        }
        #[expect(
            clippy::indexing_slicing,
            reason = "a u8 index cannot leave the 256-entry palette"
        )]
        let (r, g, b) = palette[usize::from(index)];
        for py in scaled_span(y, mode_h, height) {
            for px in scaled_span(x, mode_w, width) {
                // Glyph coordinates are not negative, so neither is the index; skip one if so.
                let Ok(at) = usize::try_from(py * width + px) else {
                    continue;
                };
                // A pixel outside the page is clipped, like a glyph outside the mode raster.
                if let (Some(slot), Some(layer), Some(rgb)) = (
                    page.indices.get_mut(at),
                    page.layers.get_mut(at),
                    page.rgba.get_mut(at * 4..at * 4 + 3),
                ) {
                    *slot = index;
                    *layer = LAYER_OVERLAY;
                    rgb.copy_from_slice(&[r, g, b]);
                }
            }
        }
    });
}

/// The page pixels, along one axis, that Mode 13h pixel `at` of `from` covers on a page `to`
/// pixels long.
fn scaled_span(at: i32, from: i32, to: i32) -> std::ops::Range<i32> {
    at * to / from..(at + 1) * to / from
}

/// A viewport edge or size in window pixels as the `u32` a scissor rect takes.
#[expect(
    clippy::cast_possible_truncation,
    clippy::cast_sign_loss,
    reason = "edges lie inside the window; `as` saturates, so a negative or NaN edge is 0"
)]
fn viewport_px(v: f32) -> u32 {
    v as u32
}

/// Consumes the pages an offscreen Renderer reads back.
///
/// The renderer calls `PageSink::accept` exactly once per `Renderer::draw` and does not know what a
/// page becomes; the sink owns every file. An error is terminal for the run.
pub trait PageSink {
    /// Consumes one rendered page.
    ///
    /// # Errors
    /// Returns a [`SinkError`] if the sink cannot store or forward the page; the run stops there.
    fn accept(&mut self, page: RenderedPage) -> Result<(), SinkError>;
}

/// Opening or drawing a Renderer failed.
#[derive(Debug, thiserror::Error)]
pub enum RenderError {
    /// No adapter could be acquired by either acquisition attempt.
    #[error("no compatible GPU adapter found on this system")]
    NoGpuAdapter,
    /// The adapter refused to create a logical device.
    #[error("failed to request a GPU device: {0}")]
    DeviceRequest(String),
    /// The window surface could not be created.
    #[error("failed to create the window surface: {0}")]
    SurfaceCreate(String),
    /// The window surface could not be configured.
    #[error("failed to configure the window surface: {0}")]
    SurfaceConfig(String),
    /// The rendered pixels or plane could not be read back.
    #[error("failed to read the rendered page back: {0}")]
    Readback(String),
    /// The page sink rejected a page; a sink failure is terminal.
    #[error(transparent)]
    Sink(#[from] SinkError),
}

/// The adapter a renderer draws on.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct AdapterIdentity {
    /// Adapter name as its driver reports it.
    pub name: String,
    /// The adapter is a CPU implementation (lavapipe, WARP), not a GPU.
    pub is_cpu: bool,
}

impl AdapterIdentity {
    /// The identity *adapter*'s driver reports.
    fn of(adapter: &wgpu::Adapter) -> Self {
        let info = adapter.get_info();
        Self {
            is_cpu: is_cpu_adapter(&info),
            name: info.name,
        }
    }
}

/// A renderer bound to one destination and one `FilmScene`.
pub struct Renderer {
    adapter: AdapterIdentity,
    device: wgpu::Device,
    queue: wgpu::Queue,
    pipelines: RenderPipelines,
    palette_lut: PaletteLut,
    camera_resources: CameraGpuResources,
    scene_pass: SceneRenderer,
    clear_palette_index: u8,
    destination: Destination,
    /// The scene's credits font; without one, credits are not drawn.
    font: Option<PFont>,
}

impl fmt::Debug for Renderer {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        let destination = match self.destination {
            Destination::Offscreen(_) => "offscreen",
            Destination::Surface(_) => "surface",
        };
        f.debug_struct("Renderer")
            .field("destination", &destination)
            .finish_non_exhaustive()
    }
}

impl Renderer {
    /// Opens an offscreen renderer that reads every page back into the sink.
    ///
    /// The page size is fixed here; `Renderer::resize` is a no-op. Every `Renderer::draw` calls
    /// sink.accept exactly once.
    ///
    /// # Errors
    /// - [`RenderError::NoGpuAdapter`] if no adapter can be acquired.
    /// - [`RenderError::DeviceRequest`] if the adapter refuses to create a device.
    pub fn offscreen(
        scene: &FilmScene,
        target: Offscreen,
        sink: Box<dyn PageSink>,
        options: RenderOptions,
    ) -> Result<Self, RenderError> {
        let adapter = offscreen_adapter(options)?;
        let (device, queue) = open_device(&adapter)?;
        let camera_resources = CameraGpuResources::new(&device);
        let palette_lut = PaletteLut::new(&device, &queue);
        let pipelines = RenderPipelines::new_with_plane(
            &device,
            COLOR_FORMAT,
            DEPTH_FORMAT,
            &camera_resources.bind_group_layout,
            &palette_lut.bind_group_layout,
        );
        let scene_pass = SceneRenderer::new(&device, &queue, &pipelines, scene);
        let destination =
            Destination::Offscreen(Box::new(OffscreenTarget::new(&device, target, sink)));
        Ok(Self {
            adapter: AdapterIdentity::of(&adapter),
            device,
            queue,
            pipelines,
            palette_lut,
            camera_resources,
            scene_pass,
            clear_palette_index: options.clear_palette_index,
            destination,
            font: scene.font().cloned(),
        })
    }

    /// Opens a renderer that presents every drawn frame to the window.
    ///
    /// The surface starts at 1x1; call `Renderer::resize` with the window's inner size before
    /// drawing. `W` is bounded by the raw-window-handle traits, the recorded exception to the
    /// no-GPU-types-in-signatures rule.
    ///
    /// # Errors
    /// - [`RenderError::SurfaceCreate`] if `window` cannot back a surface.
    /// - [`RenderError::NoGpuAdapter`] if no adapter compatible with the surface can be acquired.
    /// - [`RenderError::DeviceRequest`] if the adapter refuses to create a device.
    /// - [`RenderError::SurfaceConfig`] if the surface cannot be configured.
    pub fn surface<W>(
        scene: &FilmScene,
        window: Arc<W>,
        options: RenderOptions,
    ) -> Result<Self, RenderError>
    where
        W: wgpu::rwh::HasWindowHandle + wgpu::rwh::HasDisplayHandle + Send + Sync + 'static,
    {
        // A window keeps every backend: the start-up probe behind OFFSCREEN_BACKENDS did not cover
        // presentation surfaces.
        let instance = create_instance(wgpu::Backends::all());
        let surface = instance
            .create_surface(window)
            .map_err(|error| RenderError::SurfaceCreate(error.to_string()))?;
        let (adapter, device, queue) = acquire(&instance, Some(&surface), options)?;
        let camera_resources = CameraGpuResources::new(&device);
        let palette_lut = PaletteLut::new(&device, &queue);
        let surface_target = SurfaceTarget::new(surface, &adapter, &device)?;
        let pipelines = RenderPipelines::new(
            &device,
            surface_target.config.format,
            DEPTH_FORMAT,
            &camera_resources.bind_group_layout,
            &palette_lut.bind_group_layout,
        );
        let scene_pass = SceneRenderer::new(&device, &queue, &pipelines, scene);
        Ok(Self {
            adapter: AdapterIdentity::of(&adapter),
            device,
            queue,
            pipelines,
            palette_lut,
            camera_resources,
            scene_pass,
            clear_palette_index: options.clear_palette_index,
            destination: Destination::Surface(Box::new(surface_target)),
            // Credits are drawn on offscreen pages only; the window shows the scene alone.
            font: None,
        })
    }

    /// The adapter this renderer draws on, chosen at open.
    #[must_use]
    pub fn adapter(&self) -> &AdapterIdentity {
        &self.adapter
    }

    /// Draws the frame, exactly once, to the destination fixed at open.
    ///
    /// A `camera` override replaces the frame's view but not its per-actor LOD distances.
    /// Offscreen reads the page back and hands it to the sink; a surface presents it, and a lost,
    /// outdated, timed-out or occluded surface skips the frame without error.
    ///
    /// # Errors
    /// - [`RenderError::Readback`] if an offscreen page cannot be read back from the GPU.
    /// - [`RenderError::Sink`] if the sink rejects the page.
    pub fn draw(
        &mut self,
        frame: &SceneFrame,
        camera: Option<&CameraController>,
    ) -> Result<(), RenderError> {
        if matches!(&self.destination, Destination::Offscreen(_)) {
            self.draw_offscreen(frame, camera)
        } else {
            self.draw_surface(frame, camera);
            Ok(())
        }
    }

    /// Reconfigures a surface destination to the given size, clamped to the adapter's maximum
    /// texture dimension; a no-op offscreen, whose page size is fixed at open.
    pub fn resize(&mut self, width: u32, height: u32) {
        let device = &self.device;
        let Destination::Surface(target) = &mut self.destination else {
            return;
        };
        target.resize(device, width, height);
    }

    fn draw_offscreen(
        &mut self,
        frame: &SceneFrame,
        camera: Option<&CameraController>,
    ) -> Result<(), RenderError> {
        let Self {
            adapter: _,
            device,
            queue,
            pipelines,
            palette_lut,
            camera_resources,
            scene_pass,
            clear_palette_index,
            destination,
            font,
        } = self;
        let Destination::Offscreen(target) = destination else {
            return Ok(());
        };

        palette_lut.set_controls(queue, frame.palette);
        let squeezed = target.viewport_rows.map(|rows| {
            let mut controller = CameraController::default();
            controller.set_authored_transform(frame.view);
            controller.projection_y_scale = target.size.height as f32 / rows.max(1) as f32;
            controller
        });
        scene_pass.prepare(
            device,
            queue,
            camera_resources,
            frame,
            camera.or(squeezed.as_ref()),
        );

        let (r, g, b) = palette_lut.rgb_float(*clear_palette_index);
        let clear_color = wgpu::Color {
            r: f64::from(r),
            g: f64::from(g),
            b: f64::from(b),
            a: 1.0,
        };
        let credits = font.as_ref().zip(frame.credits.as_ref());
        let viewport_rows = target.viewport_rows;
        target.capture(
            device,
            queue,
            clear_color,
            *clear_palette_index,
            |rpass| scene_pass.draw(rpass, pipelines, camera_resources, palette_lut),
            |page| {
                if let Some((font, lines)) = credits {
                    paint_credits(
                        page,
                        font,
                        lines,
                        viewport_rows,
                        &frame.palette.film_palette(),
                    );
                }
            },
        )
    }

    fn draw_surface(&mut self, frame: &SceneFrame, camera: Option<&CameraController>) {
        let Self {
            adapter: _,
            device,
            queue,
            pipelines,
            palette_lut,
            camera_resources,
            scene_pass,
            clear_palette_index,
            destination,
            font: _,
        } = self;
        let Destination::Surface(target) = destination else {
            return;
        };

        palette_lut.set_controls(queue, frame.palette);
        scene_pass.prepare(device, queue, camera_resources, frame, camera);

        let surface_texture = match target.surface.get_current_texture() {
            wgpu::CurrentSurfaceTexture::Success(texture)
            | wgpu::CurrentSurfaceTexture::Suboptimal(texture) => texture,
            wgpu::CurrentSurfaceTexture::Lost | wgpu::CurrentSurfaceTexture::Outdated => {
                target.surface.configure(device, &target.config);
                return;
            }
            wgpu::CurrentSurfaceTexture::Timeout
            | wgpu::CurrentSurfaceTexture::Occluded
            | wgpu::CurrentSurfaceTexture::Validation => return,
        };
        let view = surface_texture
            .texture
            .create_view(&wgpu::TextureViewDescriptor::default());

        let mut encoder = device.create_command_encoder(&wgpu::CommandEncoderDescriptor {
            label: Some("stunt_renderer_encoder"),
        });

        // 4:3 letterbox per [I6]: the scene fills the largest centred 4:3 rectangle.
        let win_w = target.config.width as f32;
        let win_h = target.config.height as f32;
        let cur_aspect = win_w / win_h.max(1.0);
        let aspect = crate::camera::ASPECT_4_3;

        let (vp_x, vp_y, vp_w, vp_h) = if cur_aspect > aspect {
            // Pillarbox: bars on left and right.
            let vp_h = win_h;
            let vp_w = win_h * aspect;
            let vp_x = (win_w - vp_w) / 2.0;
            (vp_x, 0.0, vp_w, vp_h)
        } else {
            // Letterbox: bars on top and bottom.
            let vp_w = win_w;
            let vp_h = win_w / aspect;
            let vp_y = (win_h - vp_h) / 2.0;
            (0.0, vp_y, vp_w, vp_h)
        };

        let width = target.config.width;
        let height = target.config.height;
        let sc_x = viewport_px(vp_x.max(0.0));
        let sc_y = viewport_px(vp_y.max(0.0));
        let sc_w = viewport_px(vp_w).clamp(1, width.saturating_sub(sc_x).max(1));
        let sc_h = viewport_px(vp_h).clamp(1, height.saturating_sub(sc_y).max(1));

        let right_edge = viewport_px((vp_x + vp_w).min(win_w));
        let bottom_edge = viewport_px((vp_y + vp_h).min(win_h));
        let bars: [(u32, u32, u32, u32); 2] = if cur_aspect > aspect {
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

        let (cr, cg, cb) = palette_lut.rgb_float(*clear_palette_index);
        let clear_color = wgpu::Color {
            r: f64::from(cr),
            g: f64::from(cg),
            b: f64::from(cb),
            a: 1.0,
        };

        {
            let mut rpass = encoder.begin_render_pass(&wgpu::RenderPassDescriptor {
                label: Some("stunt_renderer_render_pass"),
                color_attachments: &[Some(wgpu::RenderPassColorAttachment {
                    view: &view,
                    resolve_target: None,
                    depth_slice: None,
                    ops: wgpu::Operations {
                        load: wgpu::LoadOp::Clear(clear_color),
                        store: wgpu::StoreOp::Store,
                    },
                })],
                depth_stencil_attachment: Some(wgpu::RenderPassDepthStencilAttachment {
                    view: &target.depth_view,
                    depth_ops: Some(wgpu::Operations {
                        load: wgpu::LoadOp::Clear(1.0),
                        store: wgpu::StoreOp::Store,
                    }),
                    stencil_ops: None,
                }),
                timestamp_writes: None,
                occlusion_query_set: None,
                multiview_mask: None,
            });

            rpass.set_viewport(vp_x, vp_y, vp_w, vp_h, 0.0, 1.0);
            rpass.set_scissor_rect(sc_x, sc_y, sc_w, sc_h);
            scene_pass.draw(&mut rpass, pipelines, camera_resources, palette_lut);

            // Letterbox bars, painted black last.
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
        queue.present(surface_texture);
    }
}

/// Where an open renderer sends the frames it draws.
enum Destination {
    Offscreen(Box<OffscreenTarget>),
    Surface(Box<SurfaceTarget>),
}

/// The offscreen colour and plane targets and their CPU readback buffers.
struct OffscreenTarget {
    color_texture: wgpu::Texture,
    color_view: wgpu::TextureView,
    plane_texture: wgpu::Texture,
    plane_view: wgpu::TextureView,
    depth_view: wgpu::TextureView,
    readback_buffer: wgpu::Buffer,
    plane_readback_buffer: wgpu::Buffer,
    size: PageSize,
    padded_row_bytes: u32,
    viewport_rows: Option<u32>,
    sink: Box<dyn PageSink>,
}

impl OffscreenTarget {
    fn new(device: &wgpu::Device, target: Offscreen, sink: Box<dyn PageSink>) -> Self {
        let size = target.size;
        let extent = wgpu::Extent3d {
            width: size.width,
            height: size.height,
            depth_or_array_layers: 1,
        };
        let color_texture = device.create_texture(&wgpu::TextureDescriptor {
            label: Some("stunt_renderer_color_target"),
            size: extent,
            mip_level_count: 1,
            sample_count: 1,
            dimension: wgpu::TextureDimension::D2,
            format: COLOR_FORMAT,
            usage: wgpu::TextureUsages::RENDER_ATTACHMENT | wgpu::TextureUsages::COPY_SRC,
            view_formats: &[],
        });
        let color_view = color_texture.create_view(&wgpu::TextureViewDescriptor::default());

        let plane_texture = device.create_texture(&wgpu::TextureDescriptor {
            label: Some("stunt_renderer_plane_target"),
            size: extent,
            mip_level_count: 1,
            sample_count: 1,
            dimension: wgpu::TextureDimension::D2,
            format: PLANE_FORMAT,
            usage: wgpu::TextureUsages::RENDER_ATTACHMENT | wgpu::TextureUsages::COPY_SRC,
            view_formats: &[],
        });
        let plane_view = plane_texture.create_view(&wgpu::TextureViewDescriptor::default());

        let depth_view = create_depth_view(device, size.width, size.height);

        // Texture-to-buffer copies need a 256-byte row pitch; 320 * 4 = 1280 already is one.
        let padded_row_bytes =
            (size.width * 4).next_multiple_of(wgpu::COPY_BYTES_PER_ROW_ALIGNMENT);
        let buffer_size = u64::from(padded_row_bytes) * u64::from(size.height);
        let readback_usage = wgpu::BufferUsages::COPY_DST | wgpu::BufferUsages::MAP_READ;
        let readback_buffer = device.create_buffer(&wgpu::BufferDescriptor {
            label: Some("stunt_renderer_readback_buffer"),
            size: buffer_size,
            usage: readback_usage,
            mapped_at_creation: false,
        });
        let plane_readback_buffer = device.create_buffer(&wgpu::BufferDescriptor {
            label: Some("stunt_renderer_plane_readback_buffer"),
            size: buffer_size,
            usage: readback_usage,
            mapped_at_creation: false,
        });

        Self {
            color_texture,
            color_view,
            plane_texture,
            plane_view,
            depth_view,
            readback_buffer,
            plane_readback_buffer,
            size,
            padded_row_bytes,
            viewport_rows: target.viewport_rows,
            sink,
        }
    }

    /// Clears both targets, runs the draw inside the pass, reads the page back and offers it to
    /// the sink exactly once.
    fn capture(
        &mut self,
        device: &wgpu::Device,
        queue: &wgpu::Queue,
        clear_color: wgpu::Color,
        clear_palette_index: u8,
        draw: impl FnOnce(&mut wgpu::RenderPass<'_>),
        overlay: impl FnOnce(&mut RenderedPage),
    ) -> Result<(), RenderError> {
        let mut encoder = device.create_command_encoder(&wgpu::CommandEncoderDescriptor {
            label: Some("stunt_renderer_encoder"),
        });

        {
            let mut rpass = encoder.begin_render_pass(&wgpu::RenderPassDescriptor {
                label: Some("stunt_renderer_render_pass"),
                color_attachments: &[
                    Some(wgpu::RenderPassColorAttachment {
                        view: &self.color_view,
                        resolve_target: None,
                        depth_slice: None,
                        ops: wgpu::Operations {
                            load: wgpu::LoadOp::Clear(clear_color),
                            store: wgpu::StoreOp::Store,
                        },
                    }),
                    Some(wgpu::RenderPassColorAttachment {
                        view: &self.plane_view,
                        resolve_target: None,
                        depth_slice: None,
                        ops: wgpu::Operations {
                            load: wgpu::LoadOp::Clear(wgpu::Color {
                                r: f64::from(clear_palette_index),
                                g: 0.0,
                                b: 0.0,
                                a: 0.0,
                            }),
                            store: wgpu::StoreOp::Store,
                        },
                    }),
                ],
                depth_stencil_attachment: Some(wgpu::RenderPassDepthStencilAttachment {
                    view: &self.depth_view,
                    depth_ops: Some(wgpu::Operations {
                        load: wgpu::LoadOp::Clear(1.0),
                        store: wgpu::StoreOp::Store,
                    }),
                    stencil_ops: None,
                }),
                timestamp_writes: None,
                occlusion_query_set: None,
                multiview_mask: None,
            });

            if let Some(rows) = self.viewport_rows {
                rpass.set_viewport(0.0, 0.0, self.size.width as f32, rows as f32, 0.0, 1.0);
            }
            draw(&mut rpass);
        }

        let extent = wgpu::Extent3d {
            width: self.size.width,
            height: self.size.height,
            depth_or_array_layers: 1,
        };
        for (texture, buffer) in [
            (&self.color_texture, &self.readback_buffer),
            (&self.plane_texture, &self.plane_readback_buffer),
        ] {
            encoder.copy_texture_to_buffer(
                wgpu::TexelCopyTextureInfo {
                    texture,
                    mip_level: 0,
                    origin: wgpu::Origin3d::ZERO,
                    aspect: wgpu::TextureAspect::All,
                },
                wgpu::TexelCopyBufferInfo {
                    buffer,
                    layout: wgpu::TexelCopyBufferLayout {
                        offset: 0,
                        bytes_per_row: Some(self.padded_row_bytes),
                        rows_per_image: Some(self.size.height),
                    },
                },
                extent,
            );
        }

        queue.submit(Some(encoder.finish()));

        let rgba = read_back(
            device,
            &self.readback_buffer,
            self.size.width,
            self.padded_row_bytes,
        )?;
        let plane: Vec<u32> = read_back(
            device,
            &self.plane_readback_buffer,
            self.size.width,
            self.padded_row_bytes,
        )?
        .as_chunks::<4>()
        .0
        .iter()
        .map(|word| u32::from_le_bytes(*word))
        .collect();

        let mut page = RenderedPage::new(self.size, rgba, &plane)?;
        overlay(&mut page);
        self.sink.accept(page)?;
        Ok(())
    }
}

/// The presented surface, its configuration and its depth view.
struct SurfaceTarget {
    surface: wgpu::Surface<'static>,
    config: wgpu::SurfaceConfiguration,
    depth_view: wgpu::TextureView,
    max_texture_dimension_2d: u32,
}

impl SurfaceTarget {
    fn new(
        surface: wgpu::Surface<'static>,
        adapter: &wgpu::Adapter,
        device: &wgpu::Device,
    ) -> Result<Self, RenderError> {
        let capabilities = surface.get_capabilities(adapter);
        let format = pick_surface_format(&capabilities.formats).ok_or_else(|| {
            RenderError::SurfaceConfig("the surface offers no texture format".to_string())
        })?;
        let alpha_mode = capabilities.alpha_modes.first().copied().ok_or_else(|| {
            RenderError::SurfaceConfig("the surface offers no alpha mode".to_string())
        })?;
        let max_texture_dimension_2d = adapter.limits().max_texture_dimension_2d;

        // The caller resizes to the window's inner size before the first draw.
        let config = wgpu::SurfaceConfiguration {
            usage: wgpu::TextureUsages::RENDER_ATTACHMENT,
            format,
            color_space: wgpu::SurfaceColorSpace::Auto,
            width: 1,
            height: 1,
            present_mode: wgpu::PresentMode::AutoVsync,
            desired_maximum_frame_latency: 2,
            alpha_mode,
            view_formats: vec![],
        };
        surface.configure(device, &config);
        let depth_view = create_depth_view(device, 1, 1);
        Ok(Self {
            surface,
            config,
            depth_view,
            max_texture_dimension_2d,
        })
    }

    fn resize(&mut self, device: &wgpu::Device, width: u32, height: u32) {
        let width = width.clamp(1, self.max_texture_dimension_2d);
        let height = height.clamp(1, self.max_texture_dimension_2d);
        if self.config.width == width && self.config.height == height {
            return;
        }
        self.config.width = width;
        self.config.height = height;
        self.surface.configure(device, &self.config);
        self.depth_view = create_depth_view(device, width, height);
    }
}

/// The one acquisition policy both destinations use.
///
/// Instance, then surface when there is one, then a high-performance adapter compatible with
/// the surface, then a low-power fallback adapter, then a device built from downlevel defaults
/// raised to the adapter's limits. A software adapter is an outcome of the fallback attempt, not
/// an offscreen privilege.
fn acquire(
    instance: &wgpu::Instance,
    surface: Option<&wgpu::Surface<'static>>,
    options: RenderOptions,
) -> Result<(wgpu::Adapter, wgpu::Device, wgpu::Queue), RenderError> {
    let adapter = select_adapter(instance, surface, options).ok_or(RenderError::NoGpuAdapter)?;
    let (device, queue) = open_device(&adapter)?;
    Ok((adapter, device, queue))
}

/// The instances the offscreen path tries, in order: Vulkan alone, then every backend.
///
/// An all-backends instance costs about 1.9 s on a Windows workstation with an RTX 4070: about
/// 0.95 s in the Vulkan loader and 0.95 s more enumerating DX12 adapters, before it picks the same
/// Vulkan adapter. Trying Vulkan alone first saves about 1 s and 80 MiB per process, with
/// byte-identical output: a one-tick CTRY render starts in a median 1.39 s against 3.15 s with
/// every backend (six alternating runs each; `research/parity/method.md` § 3). The second attempt keeps every other machine working: it runs when
/// Vulkan finds no adapter, or only a CPU one such as CI's lavapipe (kept if nothing better
/// turns up), and gives the software path WARP where Vulkan has no software adapter.
const OFFSCREEN_BACKENDS: [wgpu::Backends; 2] = [wgpu::Backends::VULKAN, wgpu::Backends::all()];

/// The first *preferred* adapter *request* finds over *attempts*, tried in order; when none
/// is preferred, the first adapter found at all.
///
/// A Vulkan-only instance on a machine whose Vulkan has only a software driver finds a CPU
/// adapter while DX12 may have the GPU, so the offscreen path prefers hardware and keeps
/// trying; a machine with no hardware adapter still renders on the first software one.
fn first_adapter<A>(
    attempts: &[wgpu::Backends],
    preferred: impl Fn(&A) -> bool,
    mut request: impl FnMut(wgpu::Backends) -> Option<A>,
) -> Option<A> {
    let mut fallback = None;
    for &backends in attempts {
        if let Some(adapter) = request(backends) {
            if preferred(&adapter) {
                return Some(adapter);
            }
            fallback.get_or_insert(adapter);
        }
    }
    fallback
}

/// Whether *adapter* is the kind the offscreen path asked for: any adapter when the caller
/// asked for software, else one that is not a CPU implementation.
fn preferred_adapter(adapter: &wgpu::Adapter, options: RenderOptions) -> bool {
    options.software_only || !is_cpu_adapter(&adapter.get_info())
}

/// Whether *info* describes a CPU implementation rather than a GPU.
fn is_cpu_adapter(info: &wgpu::AdapterInfo) -> bool {
    info.device_type == wgpu::DeviceType::Cpu
}

/// The offscreen adapter of the acquisition policy, chosen once per process.
///
/// Creating the instance and enumerating its adapters is the expensive part of start-up (see
/// [`OFFSCREEN_BACKENDS`]: a median 1.39 s per one-tick render with Vulkan first, against 3.15 s
/// with every backend), against about 30 ms for a device. A process that opens several
/// offscreen renderers, as the GPU integration tests do, pays that once: the adapter keeps its
/// instance alive, and each renderer still opens a device of its own. A process that found no
/// adapter keeps finding none.
fn offscreen_adapter(options: RenderOptions) -> Result<wgpu::Adapter, RenderError> {
    static PREFERRED: OnceLock<Option<wgpu::Adapter>> = OnceLock::new();
    static SOFTWARE: OnceLock<Option<wgpu::Adapter>> = OnceLock::new();
    let chosen = if options.software_only {
        &SOFTWARE
    } else {
        &PREFERRED
    };
    chosen
        .get_or_init(|| {
            first_adapter(
                &OFFSCREEN_BACKENDS,
                |adapter| preferred_adapter(adapter, options),
                |backends| select_adapter(&create_instance(backends), None, options),
            )
        })
        .clone()
        .ok_or(RenderError::NoGpuAdapter)
}

/// The adapter step of the acquisition policy: high-performance first, then the fallback.
fn select_adapter(
    instance: &wgpu::Instance,
    surface: Option<&wgpu::Surface<'static>>,
    options: RenderOptions,
) -> Option<wgpu::Adapter> {
    if options.software_only {
        return request_fallback_adapter(instance, surface);
    }
    pollster::block_on(instance.request_adapter(&wgpu::RequestAdapterOptions {
        power_preference: wgpu::PowerPreference::HighPerformance,
        compatible_surface: surface,
        force_fallback_adapter: false,
        apply_limit_buckets: false,
    }))
    .ok()
    .or_else(|| request_fallback_adapter(instance, surface))
}

/// The device step of the acquisition policy: downlevel defaults raised to the adapter's limits.
fn open_device(adapter: &wgpu::Adapter) -> Result<(wgpu::Device, wgpu::Queue), RenderError> {
    pollster::block_on(adapter.request_device(&wgpu::DeviceDescriptor {
        label: Some("stunt_renderer_device"),
        required_features: wgpu::Features::empty(),
        required_limits: wgpu::Limits::downlevel_defaults().using_resolution(adapter.limits()),
        memory_hints: wgpu::MemoryHints::Performance,
        experimental_features: wgpu::ExperimentalFeatures::disabled(),
        trace: wgpu::Trace::Off,
    }))
    .map_err(|error| RenderError::DeviceRequest(error.to_string()))
}

/// The low-power fallback attempt of the acquisition policy.
fn request_fallback_adapter(
    instance: &wgpu::Instance,
    surface: Option<&wgpu::Surface<'static>>,
) -> Option<wgpu::Adapter> {
    pollster::block_on(instance.request_adapter(&wgpu::RequestAdapterOptions {
        power_preference: wgpu::PowerPreference::LowPower,
        compatible_surface: surface,
        force_fallback_adapter: true,
        apply_limit_buckets: false,
    }))
    .ok()
}

/// A renderer instance over *backends*: every backend for a window, [`OFFSCREEN_BACKENDS`] offscreen.
fn create_instance(backends: wgpu::Backends) -> wgpu::Instance {
    wgpu::Instance::new(wgpu::InstanceDescriptor {
        backends,
        ..wgpu::InstanceDescriptor::new_without_display_handle()
    })
}

/// The window surface format: plain Rgba8Unorm/Bgra8Unorm when offered, else the first.
///
/// The palette LUT holds display-ready Mode 13h colours, as the offscreen `Rgba8Unorm` target
/// stores them; an sRGB surface would encode them a second time and wash the window out.
fn pick_surface_format(formats: &[wgpu::TextureFormat]) -> Option<wgpu::TextureFormat> {
    formats
        .iter()
        .copied()
        .find(|format| {
            matches!(
                format,
                wgpu::TextureFormat::Rgba8Unorm | wgpu::TextureFormat::Bgra8Unorm
            )
        })
        .or_else(|| formats.first().copied())
}

/// The depth attachment of one page or surface configuration.
fn create_depth_view(device: &wgpu::Device, width: u32, height: u32) -> wgpu::TextureView {
    device
        .create_texture(&wgpu::TextureDescriptor {
            label: Some("stunt_renderer_depth_texture"),
            size: wgpu::Extent3d {
                width: width.max(1),
                height: height.max(1),
                depth_or_array_layers: 1,
            },
            mip_level_count: 1,
            sample_count: 1,
            dimension: wgpu::TextureDimension::D2,
            format: DEPTH_FORMAT,
            usage: wgpu::TextureUsages::RENDER_ATTACHMENT,
            view_formats: &[],
        })
        .create_view(&wgpu::TextureViewDescriptor::default())
}

/// Maps a buffer, copies its rows out without the pitch padding, and unmaps it.
fn read_back(
    device: &wgpu::Device,
    buffer: &wgpu::Buffer,
    width: u32,
    padded_row_bytes: u32,
) -> Result<Vec<u8>, RenderError> {
    let buffer_slice = buffer.slice(..);
    let (sender, receiver) = std::sync::mpsc::channel();
    buffer_slice.map_async(wgpu::MapMode::Read, move |result| {
        // A send fails only once `receiver` is gone, when nobody waits for the result.
        let _: Result<(), _> = sender.send(result);
    });

    device
        .poll(wgpu::PollType::wait_indefinitely())
        .map_err(|error| RenderError::Readback(error.to_string()))?;

    receiver
        .recv()
        .map_err(|error| RenderError::Readback(error.to_string()))?
        .map_err(|error| RenderError::Readback(error.to_string()))?;

    let mapped = buffer_slice
        .get_mapped_range()
        .map_err(|error| RenderError::Readback(error.to_string()))?;
    let row_bytes = width as usize * 4;
    let bytes = mapped
        .chunks_exact(padded_row_bytes as usize)
        .flat_map(|row| row.iter().take(row_bytes))
        .copied()
        .collect();
    drop(mapped);
    buffer.unmap();
    Ok(bytes)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn page_size_clamps_to_at_least_one_pixel() {
        assert_eq!(
            PageSize::new(0, 0),
            PageSize {
                width: 1,
                height: 1
            }
        );
        assert_eq!(PageSize::new(320, 240).pixel_count(), 320 * 240);
        assert_eq!(PageSize::default(), PageSize::new(320, 240));
        assert_eq!(
            Offscreen::new(320, 200)
                .with_viewport_rows(185)
                .viewport_rows,
            Some(185)
        );
    }

    #[test]
    fn rendered_page_rejects_mismatched_buffer_lengths() {
        let size = PageSize::new(2, 2);
        let page = RenderedPage::new(size, vec![7; 16], &[0x1000; 4]).expect("page");
        assert_eq!(page.width(), 2);
        assert_eq!(page.height(), 2);
        assert_eq!(page.size(), size);
        assert_eq!(page.rgba().len(), 16);
        assert_eq!(page.indices(), [0; 4].as_slice());
        assert_eq!(page.layers(), [0x10; 4].as_slice());
        let word = (0x10 << 8) | 0x28;
        let split = RenderedPage::new(size, vec![7; 16], &[word; 4]).expect("page");
        assert_eq!(split.indices(), [40; 4].as_slice());
        assert_eq!(split.layers(), [0x10; 4].as_slice());
        RenderedPage::new(size, vec![0; 15], &[0; 4]).unwrap_err();
        RenderedPage::new(size, vec![0; 16], &[0; 3]).unwrap_err();
    }

    #[test]
    fn credits_paint_index_layer_and_colour_in_mode13h_pixels() {
        use stunt_core::contracts::PaletteControls;
        use stunt_core::credits::CreditLines;
        use stunt_core::font::PFont;

        let font = PFont::parse(include_bytes!(
            "../../../tests/fixtures/synthetic_pfont.bin"
        ))
        .expect("synthetic font");
        let lines = CreditLines::new("I", "");
        let palette = PaletteControls::default().film_palette();
        let white = palette[255];
        let rgb_at = |page: &RenderedPage, x: u32, y: u32| {
            let at = ((y * page.width() + x) * 4) as usize;
            (page.rgba()[at], page.rgba()[at + 1], page.rgba()[at + 2])
        };

        // 320x200 with the scene in 185 rows: ink at (158, 78), shadow at (159, 78).
        let mut page = RenderedPage::new(
            PageSize::new(320, 200),
            vec![9; 320 * 200 * 4],
            &vec![0; 320 * 200],
        )
        .expect("page");
        paint_credits(&mut page, &font, &lines, Some(185), &palette);
        let at = |x: u32, y: u32| (y * 320 + x) as usize;
        assert_eq!(page.indices()[at(158, 78)], 255);
        assert_eq!(page.layers()[at(158, 78)], LAYER_OVERLAY);
        assert_eq!(rgb_at(&page, 158, 78), white);
        assert_eq!(page.indices()[at(159, 78)], 0);
        assert_eq!(page.layers()[at(159, 78)], LAYER_OVERLAY);
        assert_eq!(page.layers()[at(157, 78)], crate::pipeline::LAYER_NONE);
        assert_eq!(rgb_at(&page, 157, 78), (9, 9, 9));

        // 320x240 without a viewport: y = (199 - 28) >> 1 = 85, rows 85..92 map to 102..110.
        let mut page = RenderedPage::new(
            PageSize::new(320, 240),
            vec![0; 320 * 240 * 4],
            &vec![0; 320 * 240],
        )
        .expect("page");
        paint_credits(&mut page, &font, &lines, None, &palette);
        let ink: Vec<u32> = (0..240)
            .filter(|&y| page.indices()[(y * 320 + 158) as usize] == 255)
            .collect();
        assert_eq!(ink, (102..110).collect::<Vec<_>>());
    }

    #[test]
    fn surface_format_prefers_non_srgb() {
        use wgpu::TextureFormat::{
            Bgra8Unorm, Bgra8UnormSrgb, Rgb10a2Unorm, Rgba8Unorm, Rgba8UnormSrgb,
        };
        assert_eq!(
            pick_surface_format(&[Bgra8UnormSrgb, Bgra8Unorm]),
            Some(Bgra8Unorm)
        );
        assert_eq!(
            pick_surface_format(&[Rgb10a2Unorm, Rgba8UnormSrgb, Rgba8Unorm]),
            Some(Rgba8Unorm)
        );
        // Nothing plain on offer: the surface's first format.
        assert_eq!(
            pick_surface_format(&[Bgra8UnormSrgb, Rgb10a2Unorm]),
            Some(Bgra8UnormSrgb)
        );
        assert_eq!(pick_surface_format(&[]), None);
    }

    #[test]
    fn first_adapter_stops_at_the_first_backend_that_finds_one() {
        let mut tried = Vec::new();
        let got = first_adapter(
            &OFFSCREEN_BACKENDS,
            |_| true,
            |backends| {
                tried.push(backends);
                Some(backends)
            },
        );
        assert_eq!(got, Some(wgpu::Backends::VULKAN));
        assert_eq!(tried, vec![wgpu::Backends::VULKAN]);
    }

    #[test]
    fn first_adapter_falls_back_to_all_backends() {
        let mut tried = Vec::new();
        let got = first_adapter(
            &OFFSCREEN_BACKENDS,
            |_| true,
            |backends| {
                tried.push(backends);
                (backends == wgpu::Backends::all()).then_some(backends)
            },
        );
        assert_eq!(got, Some(wgpu::Backends::all()));
        assert_eq!(tried, vec![wgpu::Backends::VULKAN, wgpu::Backends::all()]);
    }

    #[test]
    fn first_adapter_is_none_when_no_backend_finds_one() {
        assert_eq!(
            first_adapter(&OFFSCREEN_BACKENDS, |_| true, |_| None::<u8>),
            None
        );
    }

    /// A fake adapter: the backends that found it, and whether it is hardware.
    type Fake = (wgpu::Backends, bool);

    #[test]
    fn first_adapter_passes_over_a_software_vulkan_adapter_for_hardware() {
        let got = first_adapter(
            &OFFSCREEN_BACKENDS,
            |&(_, hardware): &Fake| hardware,
            |backends| Some((backends, backends == wgpu::Backends::all())),
        );
        assert_eq!(got, Some((wgpu::Backends::all(), true)));
    }

    #[test]
    fn first_adapter_keeps_the_first_software_adapter_when_no_backend_has_hardware() {
        let got = first_adapter(
            &OFFSCREEN_BACKENDS,
            |&(_, hardware): &Fake| hardware,
            |backends| Some((backends, false)),
        );
        assert_eq!(got, Some((wgpu::Backends::VULKAN, false)));
    }
}
