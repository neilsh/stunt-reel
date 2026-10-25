//! Palette LUT, camera and SSIM tests that need no GPU adapter.
//!
//! The offscreen render tests moved to renderer_test.rs, where they cross the Renderer entry
//! point and assert on RenderedPage: the plane is the test seam.

use stunt_core::contracts::CameraTransform;
use stunt_render::{
    ASPECT_4_3, ASPECT_CORRECTED_HEIGHT, CameraController, CameraMode, MODE13H_WIDTH,
    build_palette_lut_bytes, compute_frame_ssim, rgba_to_luminance,
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
    let expected_r = (r40 as f32 * 0.2).round() as u8;
    assert_eq!(bytes[idx_40_amb], expected_r);
}

#[test]
fn test_camera_controller_and_aspect_ratio() {
    let mut cam = CameraController::default();
    assert!((cam.aspect_ratio - ASPECT_4_3).abs() < 1e-4);

    let authored = CameraTransform {
        eye: [10.0, 20.0, 30.0],
        target: [0.0, 0.0, 0.0],
        fov_degrees: 60.0,
        roll_radians: 0.0,
        cut_from_previous: false,
        ..Default::default()
    };
    cam.set_authored_transform(authored);

    let view = cam.compute_view_matrix();
    let proj = cam.compute_proj_matrix();
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

#[test]
fn test_ssim_evaluator() {
    let size = MODE13H_WIDTH * ASPECT_CORRECTED_HEIGHT;
    let mut frame_ref = vec![100.0f32; size];
    // Add patterned details
    for (i, item) in frame_ref.iter_mut().enumerate() {
        *item = ((i % 128) + 50) as f32;
    }

    // Identical frame -> SSIM must be 1.0
    let ssim_ident = compute_frame_ssim(
        &frame_ref,
        &frame_ref,
        MODE13H_WIDTH,
        ASPECT_CORRECTED_HEIGHT,
        11,
        8,
    );
    assert!(
        (ssim_ident - 1.0).abs() < 1e-4,
        "Expected 1.0, got {ssim_ident}"
    );

    // Slightly perturbed frame (0.5 LSB average) -> SSIM should easily exceed the sign-off
    // threshold (>= 0.90)
    let frame_test: Vec<f32> = frame_ref.iter().map(|&v| (v + 0.5).min(255.0)).collect();
    let ssim_test = compute_frame_ssim(
        &frame_ref,
        &frame_test,
        MODE13H_WIDTH,
        ASPECT_CORRECTED_HEIGHT,
        11,
        8,
    );
    assert!(ssim_test >= 0.90, "SSIM {ssim_test} must be >= 0.90");
}

#[test]
fn test_blank_page_luminance_is_flat() {
    let rgba = vec![255u8; MODE13H_WIDTH * ASPECT_CORRECTED_HEIGHT * 4];
    let lum = rgba_to_luminance(&rgba);
    assert_eq!(lum.len(), MODE13H_WIDTH * ASPECT_CORRECTED_HEIGHT);
    assert!(lum.iter().all(|&value| (value - 255.0).abs() < 1e-3));
}
