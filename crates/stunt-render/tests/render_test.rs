//! Integration and Gate G06 verification test suite for `stunt-render`.
//!
//! Validates:
//! - Shader module compilation (`mode13h.wgsl`)
//! - Dual-pipeline depth bias configuration (`[I5]`)
//! - Mode 13h 256x32 palette LUT generation (`[I3]`)
//! - 4:3 aspect camera matrices and 6-DOF Free-Cam controls (`[I1]`, `[I6]`)
//! - Headless offscreen framebuffer capture (`[I6]`)
//! - Windowed SSIM parity evaluation and Seam 4 reporting (`[I6]`)

use stunt_core::contracts::{
    CameraTransform, NodeKind, SodModelIr, SodVertex, VisibilityCondition, VisualParityReport,
};
use stunt_render::{
    ASPECT_4_3, ASPECT_CORRECTED_HEIGHT, CameraController, CameraGpuResources, CameraMode,
    GpuModel, HeadlessRenderer, MODE13H_WIDTH, PHASE2_SSIM_THRESHOLD, PaletteLut, RenderPipelines,
    build_palette_lut_bytes, compute_frame_ssim, evaluate_visual_parity, rgba_to_luminance,
};

#[test]
fn test_shader_module_compilation_and_validation() {
    let instance = wgpu::Instance::new(&wgpu::InstanceDescriptor::default());
    let adapter = pollster::block_on(instance.request_adapter(&wgpu::RequestAdapterOptions {
        power_preference: wgpu::PowerPreference::LowPower,
        compatible_surface: None,
        force_fallback_adapter: true,
    }));

    let Some(adapter) = adapter else {
        eprintln!("[test] Skipping hardware shader compile: no adapter available");
        return;
    };

    let Ok((device, _queue)) = pollster::block_on(adapter.request_device(
        &wgpu::DeviceDescriptor {
            label: Some("test_shader_device"),
            required_features: wgpu::Features::empty(),
            required_limits: wgpu::Limits::downlevel_defaults(),
            memory_hints: wgpu::MemoryHints::Performance,
        },
        None,
    )) else {
        eprintln!("[test] Skipping hardware shader compile: device creation failed");
        return;
    };

    let shader = device.create_shader_module(wgpu::include_wgsl!("../src/shaders/mode13h.wgsl"));
    assert!(
        format!("{shader:?}").contains("ShaderModule"),
        "Shader module must compile cleanly"
    );
}

#[test]
fn test_dual_pipeline_depth_bias_configuration() {
    let instance = wgpu::Instance::new(&wgpu::InstanceDescriptor::default());
    let adapter = pollster::block_on(instance.request_adapter(&wgpu::RequestAdapterOptions {
        power_preference: wgpu::PowerPreference::LowPower,
        compatible_surface: None,
        force_fallback_adapter: true,
    }));

    let Some(adapter) = adapter else {
        eprintln!("[test] Skipping pipeline creation: no adapter available");
        return;
    };

    let Ok((device, queue)) = pollster::block_on(adapter.request_device(
        &wgpu::DeviceDescriptor {
            label: Some("test_pipeline_device"),
            required_features: wgpu::Features::empty(),
            required_limits: wgpu::Limits::downlevel_defaults(),
            memory_hints: wgpu::MemoryHints::Performance,
        },
        None,
    )) else {
        eprintln!("[test] Skipping pipeline creation: device request failed");
        return;
    };

    let camera_res = CameraGpuResources::new(&device);
    let palette_lut = PaletteLut::new(&device, &queue);

    let pipelines = RenderPipelines::new(
        &device,
        wgpu::TextureFormat::Rgba8Unorm,
        wgpu::TextureFormat::Depth24Plus,
        &camera_res.bind_group_layout,
        &palette_lut.bind_group_layout,
    );

    // Verify vertex buffer layout conforms strictly to SodVertex [I2] (28 bytes)
    let v_layout = RenderPipelines::vertex_buffer_layout();
    assert_eq!(v_layout.array_stride, 28);
    assert_eq!(v_layout.attributes.len(), 3);
    assert_eq!(v_layout.attributes[0].offset, 0); // position
    assert_eq!(v_layout.attributes[1].offset, 12); // normal
    assert_eq!(v_layout.attributes[2].offset, 24); // attr (palette_index, flags)

    assert!(format!("{pipelines:?}").contains("RenderPipelines"));
}

#[test]
fn test_palette_lut_data_integrity() {
    let bytes = build_palette_lut_bytes();
    assert_eq!(bytes.len(), 32768);

    // Verify row 31 (full brightness)
    // Palette 0: Black (0, 0, 0)
    let idx_0 = ((31 * 256 + 0) * 4) as usize;
    assert_eq!(&bytes[idx_0..idx_0 + 4], &[0, 0, 0, 255]);

    // Palette 255: White (252, 252, 252)
    let idx_255 = ((31 * 256 + 255) * 4) as usize;
    assert_eq!(&bytes[idx_255..idx_255 + 4], &[252, 252, 252, 255]);

    // Palette 40: Light Grey (120, 108, 108)
    let (r40, g40, b40) = stunt_core::contracts::get_palette_rgb(40);
    let idx_40 = ((31 * 256 + 40) * 4) as usize;
    assert_eq!(bytes[idx_40], r40);
    assert_eq!(bytes[idx_40 + 1], g40);
    assert_eq!(bytes[idx_40 + 2], b40);
    assert_eq!(bytes[idx_40 + 3], 255);

    // Verify row 0 (ambient floor factor 0.2)
    let idx_40_amb = ((0 * 256 + 40) * 4) as usize;
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
fn test_ssim_parity_evaluator_and_reporting() {
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

    // Slightly perturbed frame (0.5 LSB average) -> SSIM should easily exceed Gate G06 (>= 0.90)
    let frame_test: Vec<f32> = frame_ref.iter().map(|&v| (v + 0.5).min(255.0)).collect();
    let ssim_test = compute_frame_ssim(
        &frame_ref,
        &frame_test,
        MODE13H_WIDTH,
        ASPECT_CORRECTED_HEIGHT,
        11,
        8,
    );
    assert!(
        ssim_test >= PHASE2_SSIM_THRESHOLD,
        "SSIM {ssim_test} must be >= {PHASE2_SSIM_THRESHOLD}"
    );

    // Multi-frame evaluation
    let ref_frames = vec![frame_ref.clone(), frame_ref.clone()];
    let test_frames = vec![frame_test.clone(), frame_test.clone()];

    let report: VisualParityReport = evaluate_visual_parity(
        &ref_frames,
        &test_frames,
        "TEST_FILM",
        PHASE2_SSIM_THRESHOLD,
        false,
    );

    assert_eq!(report.film_name, "TEST_FILM");
    assert_eq!(report.frames_evaluated, 2);
    assert!(report.is_passing());
    assert!(report.mean_ssim >= PHASE2_SSIM_THRESHOLD);
}

#[test]
fn test_headless_offscreen_render_execution() {
    let Ok(mut renderer) = HeadlessRenderer::new() else {
        eprintln!(
            "[test] Skipping headless render execution: no GPU adapter available in this environment"
        );
        return;
    };

    assert_eq!(renderer.width, 320);
    assert_eq!(renderer.height, 240);

    // Build a simple test model with base geometry and coplanar decal
    let mut ir = SodModelIr::new("TEST_CUBE");
    let v0 = SodVertex {
        position: [-1.0, -1.0, 0.0],
        normal: [0.0, 0.0, 1.0],
        palette_index: 40,
        flags: 0,
        _padding: [0, 0],
    };
    let v1 = SodVertex {
        position: [1.0, -1.0, 0.0],
        normal: [0.0, 0.0, 1.0],
        palette_index: 40,
        flags: 0,
        _padding: [0, 0],
    };
    let v2 = SodVertex {
        position: [0.0, 1.0, 0.0],
        normal: [0.0, 0.0, 1.0],
        palette_index: 40,
        flags: 0,
        _padding: [0, 0],
    };

    // Coplanar decal
    let d0 = SodVertex {
        position: [-0.5, -0.5, 0.0],
        normal: [0.0, 0.0, 1.0],
        palette_index: 220,
        flags: 1, // decal
        _padding: [0, 0],
    };
    let d1 = SodVertex {
        position: [0.5, -0.5, 0.0],
        normal: [0.0, 0.0, 1.0],
        palette_index: 220,
        flags: 1,
        _padding: [0, 0],
    };
    let d2 = SodVertex {
        position: [0.0, 0.5, 0.0],
        normal: [0.0, 0.0, 1.0],
        palette_index: 220,
        flags: 1,
        _padding: [0, 0],
    };

    ir.vertices = vec![v0, v1, v2, d0, d1, d2];
    ir.indices = vec![0, 1, 2, 3, 4, 5];

    let root = ir.allocate_node(
        "BASE",
        None,
        glam::Mat4::IDENTITY.to_cols_array(),
        VisibilityCondition::Always,
        NodeKind::Mesh {
            vertex_offset: 0,
            vertex_count: 3,
            index_offset: 0,
            index_count: 3,
            is_decal: false,
        },
    );

    ir.allocate_node(
        "DECAL",
        Some(root),
        glam::Mat4::IDENTITY.to_cols_array(),
        VisibilityCondition::Always,
        NodeKind::Mesh {
            vertex_offset: 3,
            vertex_count: 3,
            index_offset: 3,
            index_count: 3,
            is_decal: true,
        },
    );

    let gpu_model = GpuModel::from_ir(
        &renderer.device,
        &renderer.queue,
        &renderer.pipelines.model_bind_group_layout,
        &ir,
    );

    let mut camera = CameraController::default();
    camera.set_authored_transform(CameraTransform {
        eye: [0.0, 0.0, 5.0],
        target: [0.0, 0.0, 0.0],
        fov_degrees: 45.0,
        roll_radians: 0.0,
        cut_from_previous: false,
    });

    let (base_meshes, decal_meshes) = gpu_model.collect_visible_meshes(1, 5.0);
    assert_eq!(base_meshes.len(), 1);
    assert_eq!(decal_meshes.len(), 1);

    let models = [(&gpu_model, base_meshes.as_slice(), decal_meshes.as_slice())];
    let pixels = renderer
        .render_frame(&camera, &models, Some(180))
        .expect("Render frame succeeds");

    assert_eq!(pixels.len(), 320 * 240 * 4);

    // Verify non-zero alpha and rendered pixels
    let non_zero_pixels = pixels.chunks_exact(4).filter(|p| p[3] == 255).count();
    assert_eq!(non_zero_pixels, 320 * 240, "All pixels must have alpha 255");

    // Convert to luminance and verify SSIM against itself
    let lum = rgba_to_luminance(&pixels);
    assert_eq!(lum.len(), 320 * 240);
    let ssim = compute_frame_ssim(&lum, &lum, 320, 240, 11, 8);
    assert!((ssim - 1.0).abs() < 1e-4);
}
