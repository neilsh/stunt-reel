//! Camera Controller: projection on the Mode 13h raster, 4:3 presentation.
//!
//! Complies with Architectural Invariants:
//! - `[I1]` Metric right-handed coordinate basis (+X right, +Y up, -Z forward, +Z backward).
//! - `[I6]` VGA 4:3 physical aspect ratio ($320 \times 240$ base), applied after a
//!   square-pixel projection on the $320 \times 200$ raster.

use glam::{DMat4, DVec3, Mat4, Vec3, camera::rh};
use stunt_core::contracts::trajectory::PLAYONE_FOV_Y_DEGREES;
use stunt_core::scene::ViewCamera;
use stunt_core::sod::ShadeLight;

use crate::sky::{SkyCamera, SkyLayout};

/// Standard 4:3 physical aspect ratio for VGA Mode 13h ($320 \times 240$): the window's
/// letterbox, not the projection (see [`MODE13H_PROJECTION_ASPECT`]).
pub const ASPECT_4_3: f32 = 4.0 / 3.0;

/// Aspect ratio of PLAYONE's projection.
///
/// Square pixels on the $320 \times 200$ raster, so equal horizontal and vertical focal lengths in
/// raster pixels. The CRT's 1.2x vertical stretch happens after projection, at presentation
/// (research/parity/framing-and-actors.md section 2).
pub const MODE13H_PROJECTION_ASPECT: f32 = 320.0 / 200.0;

/// Free-Cam vertical field of view in degrees: PLAYONE's default lens, as authored cameras.
pub const DEFAULT_FOV_DEGREES: f32 = PLAYONE_FOV_Y_DEGREES;

/// Near clipping plane distance in meters: a sweep pick that keeps a car beside the camera
/// drawn, not a value read from PLAYONE (`research/parity/attribution.md`).
pub const DEFAULT_NEAR_CLIP: f32 = 0.1;

/// Far clipping plane distance in meters, for the orthographic projection only: the perspective
/// projection has no far plane.
pub const DEFAULT_FAR_CLIP: f32 = 25_000.0;

/// GPU uniform buffer structure for camera uniforms matching WGSL `@group(0) @binding(0)`.
#[repr(C)]
#[derive(Clone, Copy, Debug, PartialEq, bytemuck::Pod, bytemuck::Zeroable)]
pub struct CameraUniform {
    /// The view's rotation, then the projection, column-major: eye-relative space to clip
    /// space. It carries no translation; each draw's matrix arrives eye-relative
    /// ([`eye_relative_matrix`]).
    pub rotation_proj: [f32; 16],
    /// Normalized world direction vector towards the primary sun light source.
    pub sun_direction: [f32; 3],
    /// Ambient floor light intensity [0.0..1.0].
    pub ambient_intensity: f32,
    /// Inverse of `rotation_proj`, used by the sky pass to turn a pixel into a view ray from
    /// the eye.
    pub inv_rotation_proj: [f32; 16],
    /// Half a Mode 13h pixel of the view in NDC, `[x, y]`: the offset that widens a line
    /// vertex (`SodVertex::flags` bit 3) to a one-pixel line.
    pub line_half_ndc: [f32; 2],
    /// The lens zoom over `PLAYONE`'s default lens: the factor a disc's rim vertex
    /// (`SodVertex::flags` bit 6) has its depth offset from the disc's centre scaled by.
    pub disc_depth_scale: f32,
    /// Alignment padding to the 16-byte uniform stride.
    pub _pad1: f32,
    /// The screen direction of world down that orders the sky bands (`sky.rs`).
    pub sky_normal: [f32; 2],
    /// How many sky band edges are drawn.
    pub sky_edge_count: u32,
    /// Bit 0: the sun disc is drawn; bit 1: the last band fill covers it.
    pub sky_flags: u32,
    /// Each drawn band edge's `sky_normal · pixel` threshold, nearest the zenith first.
    pub sky_thresholds: [f32; 16],
    /// The sky index above the first edge, then below each drawn edge.
    pub sky_colours: [u32; 16],
    /// The sun disc's centre pixel `[x, y]` and radius, then padding.
    pub sun_disc: [i32; 4],
}

/// Half a Mode 13h pixel in NDC, `[x, y]`, for a view `MODE13H_WIDTH` pixels wide whose
/// projection squeezes its vertical scale by `y_scale` into `MODE13H_HEIGHT / y_scale` rows
/// (`CameraController::projection_y_scale`).
#[must_use]
fn line_half_ndc(y_scale: f32) -> [f32; 2] {
    [1.0 / 320.0, y_scale / 200.0]
}

impl Default for CameraUniform {
    fn default() -> Self {
        Self {
            rotation_proj: Mat4::IDENTITY.to_cols_array(),
            sun_direction: [0.3, 0.9, 0.3], // Sun shining from above and slightly to side
            ambient_intensity: 0.25,
            inv_rotation_proj: Mat4::IDENTITY.to_cols_array(),
            line_half_ndc: line_half_ndc(1.0),
            disc_depth_scale: 1.0,
            _pad1: 0.0,
            sky_normal: [0.0; 2],
            sky_edge_count: 0,
            sky_flags: 0,
            sky_thresholds: [0.0; 16],
            sky_colours: [238; 16],
            sun_disc: [0; 4],
        }
    }
}

/// `model` moved to eye-relative space: `translate(-eye) * model`, computed in `f64` and
/// rounded once to `f32`.
///
/// The camera uniform's `rotation_proj` then takes the result to clip space. The only
/// world-scale arithmetic left on the GPU is a world vertex's `position - eye`, whose identity
/// matrix rounds it once in any evaluation order; every other step works on values on the
/// scale of the vertex's distance from the eye (`research/parity/lavapipe.md` section 5).
#[must_use]
pub fn eye_relative_matrix(eye: Vec3, model: &[f32; 16]) -> [f32; 16] {
    let model = DMat4::from_cols_array(&model.map(f64::from));
    (DMat4::from_translation(-DVec3::from(eye)) * model)
        .as_mat4()
        .to_cols_array()
}

/// Operational mode of the presentation camera.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CameraMode {
    /// Tracking the authored cinematic camera track from `.FLM` trajectory stream.
    Authored,
    /// Detached 6-DOF Free-Cam for interactive scene exploration.
    FreeCam,
}

/// Dynamic 6-DOF Free-Cam orientation and position state.
#[derive(Debug, Clone, PartialEq)]
#[expect(
    missing_copy_implementations,
    reason = "navigation state the controller mutates in place; an implicit copy would fork it"
)]
pub struct FreeCamState {
    /// World position in meters.
    pub position: Vec3,
    /// Yaw angle in radians around world +Y axis (0 = looking down -Z).
    pub yaw: f32,
    /// Pitch angle in radians (-PI/2 to PI/2).
    pub pitch: f32,
    /// Movement speed in meters per second.
    pub move_speed: f32,
    /// Mouse look sensitivity in radians per pixel.
    pub look_sensitivity: f32,
}

impl Default for FreeCamState {
    fn default() -> Self {
        Self {
            position: Vec3::new(0.0, 15.0, 60.0),
            yaw: 0.0,
            pitch: -0.15, // Slight downward tilt towards horizon
            move_speed: 30.0,
            look_sensitivity: 0.003,
        }
    }
}

impl FreeCamState {
    /// Computes the normalized forward view direction vector (-Z forward at yaw=0).
    #[must_use]
    pub fn forward(&self) -> Vec3 {
        let cp = self.pitch.cos();
        Vec3::new(self.yaw.sin() * cp, self.pitch.sin(), -self.yaw.cos() * cp).normalize()
    }

    /// Computes the normalized right vector (+X right at yaw=0).
    #[must_use]
    pub fn right(&self) -> Vec3 {
        self.forward().cross(Vec3::Y).normalize()
    }

    /// Computes the normalized up vector (+Y up).
    #[must_use]
    pub fn up(&self) -> Vec3 {
        self.right().cross(self.forward()).normalize()
    }

    /// Translates position along forward/backward axis.
    pub fn move_forward(&mut self, distance: f32) {
        self.position += self.forward() * distance;
    }

    /// Translates position along right/left strafe axis.
    pub fn move_right(&mut self, distance: f32) {
        self.position += self.right() * distance;
    }

    /// Translates position along world vertical axis.
    pub fn move_up(&mut self, distance: f32) {
        self.position += Vec3::Y * distance;
    }

    /// Rotates camera by yaw and pitch deltas (in radians).
    pub fn rotate(&mut self, delta_yaw: f32, delta_pitch: f32) {
        self.yaw += delta_yaw;
        self.pitch = (self.pitch + delta_pitch).clamp(-1.55, 1.55);
    }
}

/// How a [`CameraController`] maps view space onto the target.
#[derive(Debug, Clone, Copy, PartialEq)]
pub enum Projection {
    /// Perspective at the active camera's vertical field of view.
    Perspective,
    /// Parallel projection spanning `half_height` metres above and below the view axis,
    /// and `half_height * aspect_ratio` to either side; the field of view is ignored.
    Orthographic {
        /// Half the visible height in metres; must be positive.
        half_height: f32,
    },
}

/// Unified presentation camera controller.
#[derive(Debug)]
pub struct CameraController {
    /// Active camera mode.
    pub mode: CameraMode,
    /// Current authored transform received from trajectory streamer.
    pub authored: ViewCamera,
    /// Detached Free-Cam navigation state.
    pub free_cam: FreeCamState,
    /// Perspective or orthographic projection (defaults to perspective).
    pub projection: Projection,
    /// Projection aspect ratio (defaults to [`MODE13H_PROJECTION_ASPECT`]; the 4:3
    /// presentation of `[I6]` is applied after projection).
    pub aspect_ratio: f32,
    /// Factor applied to the projection's vertical focal scale; above 1.0 squeezes the same
    /// view into a shorter viewport (see `Offscreen::viewport_rows`).
    pub projection_y_scale: f32,
    /// Near clip plane in meters.
    pub near_clip: f32,
    /// Far clip plane in meters, for [`Projection::Orthographic`] only; the perspective
    /// projection is infinite.
    pub far_clip: f32,
    /// Sun direction in world space.
    pub sun_direction: Vec3,
    /// Ambient floor lighting intensity.
    pub ambient_intensity: f32,
}

impl Default for CameraController {
    fn default() -> Self {
        Self {
            mode: CameraMode::Authored,
            authored: ViewCamera::default(),
            free_cam: FreeCamState::default(),
            projection: Projection::Perspective,
            aspect_ratio: MODE13H_PROJECTION_ASPECT,
            projection_y_scale: 1.0,
            near_clip: DEFAULT_NEAR_CLIP,
            far_clip: DEFAULT_FAR_CLIP,
            sun_direction: Vec3::new(0.3, 0.9, 0.3).normalize(),
            ambient_intensity: 0.25,
        }
    }
}

/// Squared sine of the angle between the view direction and `+Y` below which `+Y` cannot be
/// the up vector: `look_at` normalises their cross product, which is not finite there.
const VERTICAL_SIN2: f32 = 1e-6;

/// The up vector of an authored camera before roll: `+Y`, or `+Z` when `forward` runs along
/// `+Y` or `-Y`, where `+Y` leaves the view's side axis undefined.
///
/// `+Z` is the orientation of the `vault-balloon` capture at tick 606 (gondola right of the
/// envelope, tree upper left); a straight-up view has no capture, so it takes the same vector.
/// A view within about 0.057 degrees of vertical (`VERTICAL_SIN2`) snaps to `+Z` too, so the
/// picture's turn jumps at that threshold; other views are unchanged.
fn authored_up(forward: Vec3) -> Vec3 {
    if forward.cross(Vec3::Y).length_squared() < VERTICAL_SIN2 && forward.length_squared() > 0.5 {
        Vec3::Z
    } else {
        Vec3::Y
    }
}

impl CameraController {
    /// Toggles between authored trajectory playback and interactive Free-Cam.
    pub fn toggle_mode(&mut self) {
        self.mode = match self.mode {
            CameraMode::Authored => {
                // Initialize Free-Cam at current authored camera location
                self.free_cam.position = Vec3::from(self.authored.eye);
                let to_target =
                    (Vec3::from(self.authored.target) - self.free_cam.position).normalize();
                self.free_cam.pitch = to_target.y.asin().clamp(-1.55, 1.55);
                self.free_cam.yaw = to_target.x.atan2(-to_target.z);
                CameraMode::FreeCam
            }
            CameraMode::FreeCam => CameraMode::Authored,
        };
    }

    /// Updates the authored camera transform from a simulation tick.
    pub fn set_authored_transform(&mut self, transform: ViewCamera) {
        self.authored = transform;
    }

    /// Computes the 4x4 view matrix for the active camera state.
    #[must_use]
    pub fn compute_view_matrix(&self) -> Mat4 {
        match self.mode {
            CameraMode::Authored => {
                let eye = Vec3::from(self.authored.eye);
                let target = Vec3::from(self.authored.target);
                let forward = (target - eye).normalize_or_zero();

                let mut up = authored_up(forward);
                if self.authored.roll_radians.abs() > 1e-4 && forward.length_squared() > 1e-4 {
                    // Apply roll rotation around look axis
                    let roll_rot = glam::Quat::from_axis_angle(forward, self.authored.roll_radians);
                    up = roll_rot * up;
                }

                rh::view::look_at_mat4(eye, target, up)
            }
            CameraMode::FreeCam => {
                let eye = self.free_cam.position;
                let target = eye + self.free_cam.forward();
                rh::view::look_at_mat4(eye, target, self.free_cam.up())
            }
        }
    }

    /// Computes the 4x4 projection matrix of [`Self::projection`] at [`Self::aspect_ratio`],
    /// with reversed depth: the near plane maps to depth 1 and the far one to 0
    /// (`docs/adr/0054-depth-is-reversed-and-infinite.md`). The perspective projection
    /// has no far plane: its clip z is `near_clip`, so depth is `near_clip / w`.
    #[must_use]
    pub fn compute_proj_matrix(&self) -> Mat4 {
        let mut proj = match self.projection {
            Projection::Perspective => {
                let fov_deg = match self.mode {
                    CameraMode::Authored => self.authored.fov_degrees.clamp(1.0, 160.0),
                    CameraMode::FreeCam => DEFAULT_FOV_DEGREES,
                };
                rh::proj::directx::perspective_infinite_reverse(
                    fov_deg.to_radians(),
                    self.aspect_ratio,
                    self.near_clip,
                )
            }
            Projection::Orthographic { half_height } => {
                let half_width = half_height * self.aspect_ratio;
                rh::proj::directx::orthographic(
                    -half_width,
                    half_width,
                    -half_height,
                    half_height,
                    // Swapped, so the near plane maps to depth 1 and the far one to 0.
                    self.far_clip,
                    self.near_clip,
                )
            }
        };
        proj.y_axis.y *= self.projection_y_scale;
        proj
    }

    /// Returns the active eye position in world meters.
    #[must_use]
    pub fn eye_position(&self) -> Vec3 {
        match self.mode {
            CameraMode::Authored => Vec3::from(self.authored.eye),
            CameraMode::FreeCam => self.free_cam.position,
        }
    }

    /// The view matrix without its translation: eye-relative space to view space.
    #[must_use]
    pub fn compute_view_rotation(&self) -> Mat4 {
        let mut view = self.compute_view_matrix();
        view.w_axis = glam::Vec4::W;
        view
    }

    /// World space to clip space, `proj * view`, for CPU-side tests of world points; the GPU
    /// takes eye-relative points through [`CameraUniform::rotation_proj`] instead.
    #[must_use]
    pub fn world_view_proj(&self) -> Mat4 {
        self.compute_proj_matrix() * self.compute_view_matrix()
    }

    /// The lens zoom over `PLAYONE`'s default lens, `tan(base / 2) / tan(fov / 2)` of the
    /// perspective's field of view: 1 for the free camera and for an orthographic view.
    #[must_use]
    pub fn disc_depth_scale(&self) -> f32 {
        let fov_deg = match (self.projection, self.mode) {
            (Projection::Perspective, CameraMode::Authored) => {
                self.authored.fov_degrees.clamp(1.0, 160.0)
            }
            _ => return 1.0,
        };
        let zoom =
            (PLAYONE_FOV_Y_DEGREES.to_radians() / 2.0).tan() / (fov_deg.to_radians() / 2.0).tan();
        if zoom.is_finite() && zoom > 0.0 {
            zoom
        } else {
            1.0
        }
    }

    /// The view as `PLAYONE`'s sky code sees it, on the Mode 13h raster: 320 pixels wide and
    /// `200 / projection_y_scale` rows. An orthographic view has none.
    fn sky_camera(&self) -> Option<SkyCamera> {
        if !matches!(self.projection, Projection::Perspective) {
            return None;
        }
        let view = self.compute_view_rotation().as_dmat4();
        let rows = 200.0 / f64::from(self.projection_y_scale);
        let proj = self.compute_proj_matrix();
        Some(SkyCamera {
            right: view.row(0).truncate(),
            up: view.row(1).truncate(),
            forward: -view.row(2).truncate(),
            focal: [
                f64::from(proj.x_axis.x) * 160.0,
                f64::from(proj.y_axis.y) * rows / 2.0,
            ],
            centre: [160.0, rows / 2.0],
            size: [320.0, rows],
            zoom: f64::from(self.disc_depth_scale()),
        })
    }

    /// Builds the `CameraUniform` data ready for GPU buffer upload, the sun at film variable
    /// 13 = `0x002D` (the observed films' value).
    #[must_use]
    pub fn build_uniform(&self) -> CameraUniform {
        self.build_uniform_with_sky(0x002D)
    }

    /// Builds the `CameraUniform` for a film frame whose variable 13 is `variable_13`: the
    /// sky bands and sun disc `PLAYONE` draws for this view (`sky.rs`).
    #[must_use]
    pub fn build_uniform_with_sky(&self, variable_13: u16) -> CameraUniform {
        let rotation_proj = self.compute_proj_matrix() * self.compute_view_rotation();
        let sun = self.sun_direction.normalize();
        let disc_direction = DVec3::from(
            ShadeLight::world(variable_13)
                .sun_direction()
                .map(f64::from),
        );
        // A parallel projection (the shape views) has no horizon: one fill of the horizon index.
        let sky = self.sky_camera().map_or(SkyLayout::fill(238), |camera| {
            camera.layout(Some(disc_direction))
        });
        let mut sky_thresholds = [0.0; 16];
        for (slot, threshold) in sky_thresholds.iter_mut().zip(sky.thresholds) {
            *slot = threshold;
        }
        let mut sky_colours = [0; 16];
        for (slot, colour) in sky_colours.iter_mut().zip(sky.colours) {
            *slot = colour;
        }
        let (sky_flags, sun_disc) = sky.disc.map_or((0, [0; 4]), |disc| {
            (
                1 | (u32::from(disc.under_last_band) << 1),
                [disc.centre[0], disc.centre[1], disc.radius, 0],
            )
        });

        CameraUniform {
            rotation_proj: rotation_proj.to_cols_array(),
            sun_direction: [sun.x, sun.y, sun.z],
            ambient_intensity: self.ambient_intensity,
            inv_rotation_proj: rotation_proj.inverse().to_cols_array(),
            line_half_ndc: line_half_ndc(self.projection_y_scale),
            disc_depth_scale: self.disc_depth_scale(),
            _pad1: 0.0,
            sky_normal: sky.normal,
            sky_edge_count: sky.edge_count,
            sky_flags,
            sky_thresholds,
            sky_colours,
            sun_disc,
        }
    }
}

/// GPU-resident buffer and bind group manager for camera uniforms.
#[derive(Debug)]
pub(crate) struct CameraGpuResources {
    /// Uniform buffer containing `CameraUniform`.
    pub(crate) buffer: wgpu::Buffer,
    /// Bind group layout for `@group(0) @binding(0)`.
    pub(crate) bind_group_layout: wgpu::BindGroupLayout,
    /// Bind group containing the buffer.
    pub(crate) bind_group: wgpu::BindGroup,
}

impl CameraGpuResources {
    /// Creates the bind group layout for `@group(0) @binding(0) var<uniform> camera: CameraUniform;`.
    pub(crate) fn create_bind_group_layout(device: &wgpu::Device) -> wgpu::BindGroupLayout {
        device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
            label: Some("stunt_camera_uniform_layout"),
            entries: &[wgpu::BindGroupLayoutEntry {
                binding: 0,
                visibility: wgpu::ShaderStages::VERTEX | wgpu::ShaderStages::FRAGMENT,
                ty: wgpu::BindingType::Buffer {
                    ty: wgpu::BufferBindingType::Uniform,
                    has_dynamic_offset: false,
                    min_binding_size: None,
                },
                count: None,
            }],
        })
    }

    /// Instantiates buffer and bind group on the device.
    #[expect(
        clippy::expect_used,
        reason = "the buffer is created with `mapped_at_creation: true`, so its range is mapped"
    )]
    pub(crate) fn new(device: &wgpu::Device) -> Self {
        let bind_group_layout = Self::create_bind_group_layout(device);
        let buffer = device.create_buffer(&wgpu::BufferDescriptor {
            label: Some("stunt_camera_uniform_buffer"),
            size: size_of::<CameraUniform>() as u64,
            usage: wgpu::BufferUsages::UNIFORM | wgpu::BufferUsages::COPY_DST,
            mapped_at_creation: true,
        });
        buffer
            .slice(..)
            .get_mapped_range_mut()
            .expect("the camera uniform buffer is mapped at creation")
            .copy_from_slice(bytemuck::bytes_of(&CameraUniform::default()));
        buffer.unmap();

        let bind_group = device.create_bind_group(&wgpu::BindGroupDescriptor {
            label: Some("stunt_camera_bind_group"),
            layout: &bind_group_layout,
            entries: &[wgpu::BindGroupEntry {
                binding: 0,
                resource: buffer.as_entire_binding(),
            }],
        });

        Self {
            buffer,
            bind_group_layout,
            bind_group,
        }
    }

    /// Uploads updated camera uniform data to the GPU buffer.
    pub(crate) fn upload(&self, queue: &wgpu::Queue, uniform: &CameraUniform) {
        queue.write_buffer(&self.buffer, 0, bytemuck::bytes_of(uniform));
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn projection_y_scale_multiplies_only_the_vertical_focal_scale() {
        let base = CameraController::default().compute_proj_matrix();
        let squeezed = CameraController {
            projection_y_scale: 200.0 / 185.0,
            ..CameraController::default()
        }
        .compute_proj_matrix();
        assert_eq!(squeezed.x_axis.x, base.x_axis.x);
        assert!((squeezed.y_axis.y / base.y_axis.y - 200.0 / 185.0).abs() < 1e-6);
    }

    /// The default lens draws a disc unsqueezed; a wider lens squeezes it by its zoom, and the
    /// free camera and an orthographic view never do.
    #[test]
    fn disc_depth_scale_is_the_lens_zoom_of_an_authored_perspective() {
        let at = |fov_degrees: f32| CameraController {
            authored: ViewCamera {
                fov_degrees,
                ..ViewCamera::default()
            },
            ..CameraController::default()
        };
        assert!((at(PLAYONE_FOV_Y_DEGREES).disc_depth_scale() - 1.0).abs() < 1e-6);
        let wide = at(50.946_854).disc_depth_scale();
        assert!((wide - 0.82).abs() < 0.005, "{wide}");
        let free = CameraController {
            mode: CameraMode::FreeCam,
            ..at(50.946_854)
        };
        assert!((free.disc_depth_scale() - 1.0).abs() < f32::EPSILON);
        let ortho = CameraController {
            projection: Projection::Orthographic { half_height: 2.0 },
            ..at(50.946_854)
        };
        assert!((ortho.disc_depth_scale() - 1.0).abs() < f32::EPSILON);
    }

    /// The shader's `squeeze_disc` scales clip `z` and `w` of a rim vertex's offset from the
    /// centre: on this symmetric projection, the point whose view depth offset is scaled.
    #[test]
    fn squeezing_clip_depth_scales_the_view_depth_offset() {
        let camera = CameraController {
            projection_y_scale: 200.0 / 185.0,
            ..CameraController::default()
        };
        let proj = camera.compute_proj_matrix();
        let k = 0.82;
        let centre = Vec3::new(3.0, -8.0, -60.0);
        let rim = Vec3::new(-5.0, -8.5, -48.0);
        let clip = |p: Vec3| proj * p.extend(1.0);
        let offset = clip(rim) - clip(centre);
        let squeezed = clip(centre) + offset * glam::Vec4::new(1.0, 1.0, k, k);
        let moved = clip(centre + (rim - centre) * Vec3::new(1.0, 1.0, k));
        assert!(
            (squeezed - moved).abs().max_element() < 1e-4,
            "{squeezed} {moved}"
        );
    }

    #[test]
    fn orthographic_projection_keeps_size_at_any_depth() {
        let camera = CameraController {
            projection: Projection::Orthographic { half_height: 2.0 },
            aspect_ratio: 1.5,
            near_clip: 1.0,
            far_clip: 100.0,
            ..CameraController::default()
        };
        let proj = camera.compute_proj_matrix();
        for depth in [-2.0, -50.0, -99.0] {
            let corner = proj.project_point3(Vec3::new(3.0, 2.0, depth));
            assert!((corner.x - 1.0).abs() < 1e-6 && (corner.y - 1.0).abs() < 1e-6);
            assert!((0.0..=1.0).contains(&corner.z), "{corner}");
        }
        // Reversed, like the perspective: the near plane at depth 1, the far one at 0.
        assert!((proj.project_point3(Vec3::new(0.0, 0.0, -1.0)).z - 1.0).abs() < 1e-6);
        assert!(proj.project_point3(Vec3::new(0.0, 0.0, -100.0)).z.abs() < 1e-6);
    }

    #[test]
    fn perspective_depth_is_near_over_w() {
        let camera = CameraController::default();
        let proj = camera.compute_proj_matrix();
        for distance in [0.5f32, 1.0, 80.0, 1500.0, 25_000.0, 1.0e7] {
            let clip = proj * glam::Vec4::new(3.0, -2.0, -distance, 1.0);
            assert_eq!(clip.z, camera.near_clip, "clip z at {distance} m");
            assert_eq!(clip.w, distance, "clip w at {distance} m");
            let depth = clip.z / clip.w;
            assert!(
                (depth - camera.near_clip / distance).abs() <= f32::EPSILON * depth,
                "{distance} m: {depth}"
            );
        }
        // The near plane is depth 1, and nearer is larger.
        let at = |d: f32| proj.project_point3(Vec3::new(0.0, 0.0, -d)).z;
        assert_eq!(at(camera.near_clip), 1.0);
        assert!(at(80.0) > at(80.001));
    }

    #[test]
    fn the_far_limit_maps_to_depth_zero() {
        let proj = CameraController::default().compute_proj_matrix();
        // A direction (w = 0) is the limit of points going away along it: no far plane clips it.
        let infinity = proj * glam::Vec4::new(0.2, 0.1, -1.0, 0.0);
        assert_eq!(infinity.z, 0.0);
        assert!(infinity.w > 0.0);
        let far = proj.project_point3(Vec3::new(0.0, 0.0, -1.0e30)).z;
        assert!(far > 0.0 && far < 1.0e-30, "{far}");
    }

    /// An authored camera over the far corner of a large world, where the eye's coordinates
    /// are in the thousands of metres.
    fn far_camera() -> CameraController {
        let mut camera = CameraController::default();
        camera.set_authored_transform(ViewCamera {
            eye: [3200.25, 12.5, -4100.75],
            target: [3260.0, 2.0, -4180.0],
            fov_degrees: PLAYONE_FOV_Y_DEGREES,
            roll_radians: 0.1,
        });
        camera
    }

    #[test]
    fn straight_down_and_straight_up_authored_views_are_finite() {
        for dy in [-1000.0f32, 1000.0] {
            for roll_radians in [0.0, 0.3] {
                let mut camera = CameraController::default();
                camera.set_authored_transform(ViewCamera {
                    eye: [-2211.7, 159.9, 2073.1],
                    target: [-2211.7, 159.9 + dy, 2073.1],
                    fov_degrees: PLAYONE_FOV_Y_DEGREES,
                    roll_radians,
                });
                let view = camera.compute_view_matrix();
                assert!(view.is_finite(), "dy {dy} roll {roll_radians}: {view}");
                // The target lies on the view axis, `-Z` in view space.
                let at = view.transform_point3(Vec3::new(-2211.7, 159.9 + dy, 2073.1));
                assert!(at.x.abs() < 0.01 && at.y.abs() < 0.01, "{at}");
                assert!((at.z + dy.abs()).abs() < 0.01, "{at}");
            }
        }
    }

    #[test]
    fn straight_down_view_puts_world_plus_z_up_the_picture() {
        let mut camera = CameraController::default();
        camera.set_authored_transform(ViewCamera {
            eye: [0.0, 100.0, 0.0],
            target: [0.0, 0.0, 0.0],
            fov_degrees: PLAYONE_FOV_Y_DEGREES,
            roll_radians: 0.0,
        });
        let view = camera.compute_view_matrix();
        let north = view.transform_point3(Vec3::new(0.0, 0.0, 10.0));
        assert!(north.y > 9.99 && north.x.abs() < 1e-3, "{north}");
        // Seen from above with `+Z` up, `+X` falls on the left.
        let east = view.transform_point3(Vec3::new(10.0, 0.0, 0.0));
        assert!(east.x < -9.99 && east.y.abs() < 1e-3, "{east}");
    }

    #[test]
    fn tilted_authored_view_keeps_world_y_up() {
        let mut camera = CameraController::default();
        camera.set_authored_transform(ViewCamera {
            eye: [0.0, 100.0, 0.0],
            target: [0.0, 0.0, -50.0],
            fov_degrees: PLAYONE_FOV_Y_DEGREES,
            roll_radians: 0.0,
        });
        let view = camera.compute_view_matrix();
        let up = view.transform_vector3(Vec3::Y);
        assert!(up.y > 0.0 && up.x.abs() < 1e-5, "{up}");
    }

    #[test]
    fn eye_relative_matrix_takes_the_eye_off_the_translation_only() {
        let model = (Mat4::from_translation(Vec3::new(3210.5, 0.0, -4090.125))
            * Mat4::from_rotation_y(0.7))
        .to_cols_array();
        let eye = Vec3::new(3200.25, 12.5, -4100.75);
        let relative = Mat4::from_cols_array(&eye_relative_matrix(eye, &model));
        let model = Mat4::from_cols_array(&model);
        assert_eq!(relative.x_axis, model.x_axis);
        assert_eq!(relative.y_axis, model.y_axis);
        assert_eq!(relative.z_axis, model.z_axis);
        assert_eq!(relative.w_axis, glam::Vec4::new(10.25, -12.5, 10.625, 1.0));
    }

    #[test]
    fn rotation_proj_after_eye_relative_matches_view_proj_after_model() {
        let camera = far_camera();
        let rotation_proj =
            DMat4::from_cols_array(&camera.build_uniform().rotation_proj.map(f64::from));
        let world_view_proj = camera.world_view_proj().as_dmat4();
        let model = (Mat4::from_translation(Vec3::new(3230.0, 4.0, -4150.0))
            * Mat4::from_rotation_y(-1.2))
        .to_cols_array();
        let relative = DMat4::from_cols_array(
            &eye_relative_matrix(camera.eye_position(), &model).map(f64::from),
        );
        let model = DMat4::from_cols_array(&model.map(f64::from));
        for local in [
            DVec3::ZERO,
            DVec3::new(5.0, 2.0, -3.0),
            DVec3::new(-8.0, 0.5, 6.0),
        ] {
            let point = local.extend(1.0);
            let expected = world_view_proj * model * point;
            let actual = rotation_proj * relative * point;
            let error = (actual - expected).abs().max_element();
            assert!(
                error < 1e-4 * expected.w.abs(),
                "{local}: {actual} vs {expected}"
            );
        }
    }

    /// The view ray under `ndc` that `inverse` (the uniform's `inv_rotation_proj`) gives: from
    /// the pixel's point at depth 1 to its point at depth 0.5, both finite under the reversed
    /// infinite perspective, whose depth 0 lies at infinity.
    fn sky_ray(inverse: Mat4, ndc: [f32; 2]) -> Vec3 {
        let point = |depth: f32| {
            let p = inverse * glam::Vec4::new(ndc[0], ndc[1], depth, 1.0);
            p.truncate() / p.w
        };
        point(0.5) - point(1.0)
    }

    #[test]
    fn sky_ray_is_the_world_view_ray_under_the_pixel() {
        let camera = far_camera();
        let inverse = Mat4::from_cols_array(&camera.build_uniform().inv_rotation_proj);
        let world_inverse = camera.world_view_proj().as_dmat4().inverse();
        let eye = camera.eye_position().as_dvec3();
        for ndc in [
            [0.0, 0.0],
            [-1.0, -1.0],
            [3.0, -1.0],
            [-1.0, 3.0],
            [0.4, -0.7],
        ] {
            let ray = sky_ray(inverse, ndc).as_dvec3().normalize();
            // The world point 50 km out under the pixel (depth 1e-5), less the eye, in f64. A
            // nearer point would carry the f32 matrix's rounding of the eye's translation.
            let world = world_inverse * glam::DVec4::new(ndc[0].into(), ndc[1].into(), 1.0e-5, 1.0);
            let expected = (world.truncate() / world.w - eye).normalize();
            assert!(
                (ray - expected).length() < 1e-5,
                "{ndc:?}: {ray} vs {expected}"
            );
        }
    }

    #[test]
    fn orthographic_sky_ray_is_the_view_axis() {
        let mut camera = far_camera();
        camera.projection = Projection::Orthographic { half_height: 2.0 };
        camera.near_clip = 1.0;
        camera.far_clip = 100.0;
        let inverse = Mat4::from_cols_array(&camera.build_uniform().inv_rotation_proj);
        let forward = (Vec3::from(camera.authored.target) - camera.eye_position()).normalize();
        for ndc in [[0.0, 0.0], [-1.0, -1.0], [0.4, -0.7]] {
            let ray = sky_ray(inverse, ndc).normalize();
            assert!(
                (ray - forward).length() < 1e-5,
                "{ndc:?}: {ray} vs {forward}"
            );
        }
    }

    #[test]
    fn test_camera_uniform_size_and_alignment() {
        assert_eq!(size_of::<CameraUniform>(), 320);
        assert_eq!(size_of::<CameraUniform>() % 16, 0);
    }

    #[test]
    fn test_free_cam_navigation_vectors() {
        let cam = FreeCamState {
            yaw: 0.0,
            pitch: 0.0,
            ..Default::default()
        };

        let fwd = cam.forward();
        assert!((fwd.x).abs() < 1e-4);
        assert!((fwd.y).abs() < 1e-4);
        assert!((fwd.z - (-1.0)).abs() < 1e-4, "yaw=0 must look down -Z");

        let right = cam.right();
        assert!((right.x - 1.0).abs() < 1e-4, "yaw=0 right must be +X");
        assert!((right.y).abs() < 1e-4);
        assert!((right.z).abs() < 1e-4);

        let up = cam.up();
        assert!((up.x).abs() < 1e-4);
        assert!((up.y - 1.0).abs() < 1e-4, "up must be +Y");
        assert!((up.z).abs() < 1e-4);
    }

    #[test]
    fn test_camera_mode_toggle() {
        let mut controller = CameraController::default();
        assert_eq!(controller.mode, CameraMode::Authored);
        controller.toggle_mode();
        assert_eq!(controller.mode, CameraMode::FreeCam);
        controller.toggle_mode();
        assert_eq!(controller.mode, CameraMode::Authored);
    }
}
