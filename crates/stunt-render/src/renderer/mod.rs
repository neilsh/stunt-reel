//! One renderer entry point for offscreen readback and a presented surface.
//!
//! Opens an instance, an adapter and a device through a single acquisition policy, uploads the
//! film's shapes once, and then draws one `SceneFrame` per `Renderer::draw` call. The destination is
//! fixed at open: an Offscreen renderer keeps up to two frames in flight and hands each page to its
//! `PageSink` in submission order; a surface renderer presents it. The caller never branches on the
//! destination and never sees a readback.
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
use std::sync::Arc;

use stunt_core::font::PFont;
use stunt_core::scene::{FilmScene, SceneFrame};

use crate::camera::{CameraController, CameraGpuResources};
use crate::palette::PaletteLut;
use crate::pipeline::RenderPipelines;
use crate::scene_renderer::SceneRenderer;

mod adapter;
mod credits;
mod offscreen;
mod readback;
mod surface;

pub use adapter::AdapterIdentity;

use adapter::{acquire, create_instance, offscreen_adapter, open_device};
use credits::paint_credits;
use offscreen::OffscreenTarget;
use surface::SurfaceTarget;

pub use stunt_core::frame::{ASPECT_CORRECTED_HEIGHT, MODE13H_HEIGHT, MODE13H_WIDTH};

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
    /// setting this only forces that attempt, which `stuntreel --software-only` and the GPU
    /// tests' software path both ask for.
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

/// Consumes the pages an offscreen Renderer reads back.
///
/// What an offscreen frame paints over its page once the page is read back: owned, because the
/// frame that asked for it is gone by then.
type Overlay = Box<dyn FnOnce(&mut RenderedPage)>;

/// The renderer calls `PageSink::accept` exactly once per submitted frame, in submission order,
/// and does not know what a page becomes; the sink owns every file. An error is terminal for the
/// run.
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
    /// The page size is fixed here; `Renderer::resize` is a no-op. `Renderer::draw` hands the
    /// sink exactly one page, and each frame queued by `Renderer::submit` hands one back from
    /// `submit` or `Renderer::finish`.
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
    /// Offscreen submits the frame and reads its page back before returning, handing it to the
    /// sink; a surface presents it, and a lost, outdated, timed-out or occluded surface skips the
    /// frame without error.
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
            self.submit_offscreen(frame, camera)?;
            self.finish()
        } else {
            self.draw_surface(frame, camera);
            Ok(())
        }
    }

    /// Submits the frame for offscreen readback without waiting for its page.
    ///
    /// A submission queues one frame; once two are queued it reads the oldest page back to the
    /// sink before returning, so at most one frame stays queued between calls and pages arrive
    /// in submission order. A surface destination presents the frame now, as `draw` does.
    ///
    /// # Errors
    /// - [`RenderError::Readback`] if a page this submission retires cannot be read back.
    /// - [`RenderError::Sink`] if the sink rejects a retired page.
    pub fn submit(
        &mut self,
        frame: &SceneFrame,
        camera: Option<&CameraController>,
    ) -> Result<(), RenderError> {
        if matches!(&self.destination, Destination::Offscreen(_)) {
            self.submit_offscreen(frame, camera)
        } else {
            self.draw_surface(frame, camera);
            Ok(())
        }
    }

    /// Reads back every submitted offscreen frame, handing each page to the sink in submission
    /// order; a surface destination has nothing queued.
    ///
    /// # Errors
    /// - [`RenderError::Readback`] if a page cannot be read back from the GPU.
    /// - [`RenderError::Sink`] if the sink rejects a page.
    pub fn finish(&mut self) -> Result<(), RenderError> {
        let device = &self.device;
        let Destination::Offscreen(target) = &mut self.destination else {
            return Ok(());
        };
        target.finish(device)
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

    fn submit_offscreen(
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
        let viewport_rows = target.viewport_rows;
        // The credits are painted when the page is read back, after this frame is gone, so the
        // overlay owns what it draws.
        let credits: Option<Overlay> =
            font.as_ref()
                .zip(frame.credits.as_ref())
                .map(|(font, lines)| -> Overlay {
                    let font = font.clone();
                    let lines = lines.clone();
                    let palette = frame.palette.film_palette();
                    Box::new(move |page| {
                        paint_credits(page, &font, &lines, viewport_rows, &palette);
                    })
                });
        target.submit(
            device,
            queue,
            clear_color,
            *clear_palette_index,
            |rpass| scene_pass.draw(rpass, pipelines, camera_resources, palette_lut),
            credits,
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

/// A viewport edge or size in window pixels as the `u32` a scissor rect takes.
#[expect(
    clippy::cast_possible_truncation,
    clippy::cast_sign_loss,
    reason = "edges lie inside the window; `as` saturates, so a negative or NaN edge is 0"
)]
fn viewport_px(v: f32) -> u32 {
    v as u32
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
}
