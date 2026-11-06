#![allow(
    clippy::unwrap_used,
    clippy::expect_used,
    clippy::panic,
    clippy::print_stderr,
    clippy::default_trait_access,
    clippy::items_after_statements,
    reason = "integration tests assert by panicking, and their helpers sit outside #[test] fns"
)]
//! Palette LUT and camera tests that need no GPU adapter.
//!
//! The offscreen render tests moved to `gpu/renderer.rs`, where they cross the Renderer entry
//! point and assert on `RenderedPage`: the plane is the test seam.

use stunt_core::contracts::trajectory::PLAYONE_FOV_Y_DEGREES;
use stunt_core::scene::ViewCamera;
use stunt_render::{
    CameraController, CameraMode, MODE13H_PROJECTION_ASPECT, build_palette_lut_bytes,
};

#[test]
fn test_palette_lut_data_integrity() {
    let bytes = build_palette_lut_bytes();
    assert_eq!(bytes.len(), 32768);

    // Verify row 31 (full brightness)
    // Palette 0: Black (0, 0, 0)
    let idx_0 = 31 * 256 * 4;
    assert_eq!(&bytes[idx_0..idx_0 + 4], &[0, 0, 0, 255]);

    // Palette 255: White (252, 252, 252)
    let idx_255 = (31 * 256 + 255) * 4;
    assert_eq!(&bytes[idx_255..idx_255 + 4], &[252, 252, 252, 255]);

    // Palette 40: Light Grey (120, 108, 108)
    let (r40, g40, b40) = stunt_core::contracts::get_palette_rgb(40);
    let idx_40 = (31 * 256 + 40) * 4;
    assert_eq!(bytes[idx_40], r40);
    assert_eq!(bytes[idx_40 + 1], g40);
    assert_eq!(bytes[idx_40 + 2], b40);
    assert_eq!(bytes[idx_40 + 3], 255);

    // Verify row 0 (ambient floor factor 0.2)
    let idx_40_amb = 40 * 4;
    #[expect(
        clippy::cast_possible_truncation,
        clippy::cast_sign_loss,
        reason = "a fifth of a byte channel, rounded"
    )]
    let expected_r = (f32::from(r40) * 0.2).round() as u8;
    assert_eq!(bytes[idx_40_amb], expected_r);
}

#[test]
fn test_camera_controller_and_aspect_ratio() {
    let mut cam = CameraController::default();
    assert!((cam.aspect_ratio - MODE13H_PROJECTION_ASPECT).abs() < 1e-4);

    let authored = ViewCamera {
        eye: [10.0, 20.0, 30.0],
        target: [0.0, 0.0, 0.0],
        fov_degrees: 60.0,
        roll_radians: 0.0,
    };
    cam.set_authored_transform(authored);

    let view = cam.compute_view_matrix();
    let proj = cam.compute_proj_matrix();
    // Square raster pixels: the same focal length in pixels across 320 columns and 200 rows.
    let fx_px = proj.x_axis.x * 160.0;
    let fy_px = proj.y_axis.y * 100.0;
    assert!((fx_px - fy_px).abs() < 1e-3, "fx {fx_px} fy {fy_px}");

    // The parity path: PLAYONE's default lens drawn into a 185-row viewport of the 200-row
    // page keeps 256 raster pixels of focal length on both axes.
    let mut parity = CameraController::default();
    parity.set_authored_transform(ViewCamera {
        fov_degrees: PLAYONE_FOV_Y_DEGREES,
        ..authored
    });
    parity.projection_y_scale = 200.0 / 185.0;
    let squeezed = parity.compute_proj_matrix();
    let fx_256 = squeezed.x_axis.x * 160.0;
    let fy_256 = squeezed.y_axis.y * 185.0 / 2.0;
    assert!((fx_256 - 256.0).abs() < 1e-2, "fx {fx_256}");
    assert!((fy_256 - 256.0).abs() < 1e-2, "fy {fy_256}");
    let uniform = cam.build_uniform();

    assert_eq!(uniform.camera_pos, [10.0, 20.0, 30.0]);
    assert_eq!(uniform.view_proj, (proj * view).to_cols_array());

    // Switch to FreeCam
    cam.toggle_mode();
    assert_eq!(cam.mode, CameraMode::FreeCam);

    cam.free_cam.move_forward(10.0);
    cam.free_cam.move_right(5.0);
    cam.free_cam.move_up(2.0);
    cam.free_cam.rotate(0.1, -0.05);

    let free_uniform = cam.build_uniform();
    assert_ne!(free_uniform.camera_pos, [10.0, 20.0, 30.0]);
}
