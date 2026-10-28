//! Camera Controller & 4:3 Aspect Presentation Architecture.
//!
//! Complies with Architectural Invariants:
//! - `[I1]` Metric right-handed coordinate basis (+X right, +Y up, -Z forward, +Z backward).
//! - `[I6]` VGA 4:3 physical aspect ratio correction ($320 \times 240$ base).

use glam::{Mat4, Vec3, camera::rh};
use stunt_core::contracts::CameraTransform;

/// Standard 4:3 physical aspect ratio for VGA Mode 13h ($320 \times 240$).
pub const ASPECT_4_3: f32 = 4.0 / 3.0;

/// Default field of view in degrees.
pub const DEFAULT_FOV_DEGREES: f32 = 45.0;

/// Near clipping plane distance in meters.
pub const DEFAULT_NEAR_CLIP: f32 = 0.5;

/// Far clipping plane distance in meters.
pub const DEFAULT_FAR_CLIP: f32 = 25_000.0;

/// GPU uniform buffer structure for camera uniforms matching WGSL `@group(0) @binding(0)`.
#[repr(C)]
#[derive(Clone, Copy, Debug, PartialEq, bytemuck::Pod, bytemuck::Zeroable)]
pub struct CameraUniform {
    /// Combined 4x4 view-projection matrix in column-major order.
    pub view_proj: [f32; 16],
    /// Camera world position in metric meters.
    pub camera_pos: [f32; 3],
    /// Alignment padding to maintain 16-byte boundary.
    pub _pad0: f32,
    /// Normalized world direction vector towards the primary sun light source.
    pub sun_direction: [f32; 3],
    /// Ambient floor light intensity [0.0..1.0].
    pub ambient_intensity: f32,
    /// Inverse of `view_proj`, used by the sky pass to turn a pixel into a world ray.
    pub inv_view_proj: [f32; 16],
}

impl Default for CameraUniform {
    fn default() -> Self {
        Self {
            view_proj: Mat4::IDENTITY.to_cols_array(),
            camera_pos: [0.0, 10.0, 50.0],
            _pad0: 0.0,
            sun_direction: [0.3, 0.9, 0.3], // Sun shining from above and slightly to side
            ambient_intensity: 0.25,
            inv_view_proj: Mat4::IDENTITY.to_cols_array(),
        }
    }
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
    pub fn forward(&self) -> Vec3 {
        let cp = self.pitch.cos();
        Vec3::new(self.yaw.sin() * cp, self.pitch.sin(), -self.yaw.cos() * cp).normalize()
    }

    /// Computes the normalized right vector (+X right at yaw=0).
    pub fn right(&self) -> Vec3 {
        self.forward().cross(Vec3::Y).normalize()
    }

    /// Computes the normalized up vector (+Y up).
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

/// Unified presentation camera controller.
#[derive(Debug)]
pub struct CameraController {
    /// Active camera mode.
    pub mode: CameraMode,
    /// Current authored transform received from trajectory streamer.
    pub authored: CameraTransform,
    /// Detached Free-Cam navigation state.
    pub free_cam: FreeCamState,
    /// Physical viewport aspect ratio (defaults to 4:3 = 1.3333333 per `[I6]`).
    pub aspect_ratio: f32,
    /// Factor applied to the projection's vertical focal scale; above 1.0 squeezes the same
    /// view into a shorter viewport (see `Offscreen::viewport_rows`).
    pub projection_y_scale: f32,
    /// Near clip plane in meters.
    pub near_clip: f32,
    /// Far clip plane in meters.
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
            authored: CameraTransform::default(),
            free_cam: FreeCamState::default(),
            aspect_ratio: ASPECT_4_3,
            projection_y_scale: 1.0,
            near_clip: DEFAULT_NEAR_CLIP,
            far_clip: DEFAULT_FAR_CLIP,
            sun_direction: Vec3::new(0.3, 0.9, 0.3).normalize(),
            ambient_intensity: 0.25,
        }
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
    pub fn set_authored_transform(&mut self, transform: CameraTransform) {
        self.authored = transform;
    }

    /// Computes the 4x4 view matrix for the active camera state.
    pub fn compute_view_matrix(&self) -> Mat4 {
        match self.mode {
            CameraMode::Authored => {
                let eye = Vec3::from(self.authored.eye);
                let target = Vec3::from(self.authored.target);
                let forward = (target - eye).normalize_or_zero();

                let mut up = Vec3::Y;
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

    /// Computes the 4x4 perspective projection matrix with 4:3 aspect correction.
    pub fn compute_proj_matrix(&self) -> Mat4 {
        let fov_deg = match self.mode {
            CameraMode::Authored => self.authored.fov_degrees.clamp(1.0, 160.0),
            CameraMode::FreeCam => DEFAULT_FOV_DEGREES,
        };
        let fov_rad = fov_deg.to_radians();

        let mut proj = rh::proj::directx::perspective(
            fov_rad,
            self.aspect_ratio,
            self.near_clip,
            self.far_clip,
        );
        proj.y_axis.y *= self.projection_y_scale;
        proj
    }

    /// Returns the active eye position in world meters.
    pub fn eye_position(&self) -> Vec3 {
        match self.mode {
            CameraMode::Authored => Vec3::from(self.authored.eye),
            CameraMode::FreeCam => self.free_cam.position,
        }
    }

    /// Builds the `CameraUniform` data ready for GPU buffer upload.
    pub fn build_uniform(&self) -> CameraUniform {
        let view = self.compute_view_matrix();
        let proj = self.compute_proj_matrix();
        let view_proj = proj * view;
        let eye = self.eye_position();
        let sun = self.sun_direction.normalize();

        CameraUniform {
            view_proj: view_proj.to_cols_array(),
            camera_pos: [eye.x, eye.y, eye.z],
            _pad0: 0.0,
            sun_direction: [sun.x, sun.y, sun.z],
            ambient_intensity: self.ambient_intensity,
            inv_view_proj: view_proj.inverse().to_cols_array(),
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
    pub(crate) fn new(device: &wgpu::Device) -> Self {
        let bind_group_layout = Self::create_bind_group_layout(device);
        let buffer = device.create_buffer(&wgpu::BufferDescriptor {
            label: Some("stunt_camera_uniform_buffer"),
            size: std::mem::size_of::<CameraUniform>() as u64,
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

    #[test]
    fn test_camera_uniform_size_and_alignment() {
        assert_eq!(std::mem::size_of::<CameraUniform>(), 160);
        assert_eq!(std::mem::size_of::<CameraUniform>() % 16, 0);
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
