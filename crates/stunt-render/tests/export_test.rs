//! Automated offline verification for interval frame capture and video container export.
//!
//! Validates Gate G08 and system invariants:
//! - `[I4]` Discrete simulation ticks temporal authoring.
//! - `[I6]` 4:3 physical display aspect ratio presentation.
//! - `[I7]` Cleanroom synthetic fixture execution.

mod common;

use std::fs;
use std::path::PathBuf;
use stunt_core::contracts::CameraTransform;
use stunt_core::scene::FilmScene;
use stunt_render::{CameraController, FfmpegVideoWriter, SceneRenderer, VideoExportError};

fn get_temp_test_dir(name: &str) -> PathBuf {
    let nonce = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .expect("time calculation")
        .as_nanos();
    let dir = std::env::temp_dir().join(format!("stuntreel_{name}_{nonce}"));
    fs::create_dir_all(&dir).expect("create test temp dir");
    dir
}

#[test]
fn test_interval_frame_capture_exact_count_magic_and_dimensions() {
    let Some(mut renderer) = common::gpu_or_skip() else {
        return;
    };

    let out_dir = get_temp_test_dir("interval_test");

    // An empty scene: each frame is the camera override over the clear colour.
    let scene = FilmScene::new(
        common::still_timeline(CameraTransform {
            eye: [0.0, 10.0, 50.0],
            target: [0.0, 0.0, 0.0],
            fov_degrees: 45.0,
            roll_radians: 0.0,
            cut_from_previous: true,
            ..Default::default()
        }),
        Default::default(),
        None,
    );
    let mut scene_renderer = SceneRenderer::new(
        &renderer.device,
        &renderer.queue,
        &renderer.pipelines,
        &scene,
    );

    // 10 simulation ticks, interval step = 2 (should produce exactly 5 frames: 1, 3, 5, 7, 9)
    let total_ticks = 10;
    let step = 2;
    let mut camera = CameraController::default();
    let mut expected_ordinals = Vec::new();

    for tick in 0..total_ticks {
        let ordinal = tick + 1;
        if (ordinal - 1) % step != 0 {
            continue;
        }
        expected_ordinals.push(ordinal);

        camera.set_authored_transform(CameraTransform {
            eye: [0.0, 10.0, 50.0 - (tick as f32 * 0.5)],
            target: [0.0, 0.0, 0.0],
            fov_degrees: 45.0,
            roll_radians: 0.0,
            cut_from_previous: tick == 0,
            ..Default::default()
        });

        let frame_path = out_dir.join(format!("frame_{ordinal:04}.png"));
        let rgba = renderer
            .render_scene(
                &mut scene_renderer,
                &scene.frame(tick as f32),
                Some(&camera),
                Some(180),
            )
            .expect("render frame");
        image::save_buffer(
            &frame_path,
            &rgba,
            renderer.width,
            renderer.height,
            image::ColorType::Rgba8,
        )
        .expect("save frame png");
    }

    // (a) Verify exact count
    let entries: Vec<_> = fs::read_dir(&out_dir)
        .expect("read out dir")
        .filter_map(Result::ok)
        .collect();
    assert_eq!(
        entries.len(),
        5,
        "Expected exactly 5 frames for 10 ticks with step 2"
    );

    // (b) Verify valid PNG headers, non-empty data, correct dimensions
    let png_magic = [0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A];
    for ordinal in expected_ordinals {
        let path = out_dir.join(format!("frame_{ordinal:04}.png"));
        assert!(path.exists(), "Frame file must exist: {}", path.display());

        let bytes = fs::read(&path).expect("read frame png");
        assert!(bytes.len() > 100, "PNG file must be non-empty");

        // Standard PNG 8-byte magic: \x89PNG\r\n\x1a\n
        assert_eq!(&bytes[0..8], &png_magic, "Valid PNG header magic required");

        // Verify dimensions via image crate
        let img = image::load_from_memory(&bytes).expect("decode png bytes");
        assert_eq!(img.width(), 320, "Width must be 320 [I6]");
        assert_eq!(img.height(), 240, "Height must be 240 [I6]");
    }

    // Cleanup
    let _ = fs::remove_dir_all(&out_dir);
}

#[test]
fn test_video_export_container_validity_or_graceful_missing_dep() {
    let test_dir = get_temp_test_dir("video_test");
    let video_path = test_dir.join("test_export.mp4");

    if !FfmpegVideoWriter::is_available() {
        // (c) Verify graceful missing-dependency behavior
        let res = FfmpegVideoWriter::open(&video_path, 320, 240, 30.0);
        assert!(matches!(res, Err(VideoExportError::FfmpegNotFound)));
        let err_msg = format!("{}", res.err().unwrap());
        assert!(
            err_msg.contains("ffmpeg"),
            "Error message must clearly mention ffmpeg"
        );
        let _ = fs::remove_dir_all(&test_dir);
        return;
    }

    // When ffmpeg is available, verify container creation
    let mut exporter =
        FfmpegVideoWriter::open(&video_path, 320, 240, 30.0).expect("spawn ffmpeg exporter");

    assert_eq!(exporter.width(), 320);
    assert_eq!(exporter.height(), 240);
    assert!((exporter.fps() - 30.0).abs() < 1e-4);

    // Push 10 frames of dummy RGBA data (320 * 240 * 4 bytes)
    let frame_bytes = vec![180u8; 320 * 240 * 4];
    for _ in 0..10 {
        exporter
            .write_frame(&frame_bytes)
            .expect("write frame to video stream");
    }
    exporter.finish().expect("finish video encoding");

    assert!(video_path.exists(), "Exported video file must exist");
    let metadata = fs::metadata(&video_path).expect("read video metadata");
    assert!(
        metadata.len() > 1000,
        "Video container must be non-empty and well-formed"
    );

    // Verify MP4 ftyp box in bytes 4..8
    let video_bytes = fs::read(&video_path).expect("read video bytes");
    assert!(video_bytes.len() > 32);
    assert_eq!(&video_bytes[4..8], b"ftyp", "Valid MP4 ftyp container box");

    // Cleanup
    let _ = fs::remove_dir_all(&test_dir);
}

#[test]
fn test_video_export_error_display_and_traits() {
    let not_found = VideoExportError::FfmpegNotFound;
    let not_found_str = format!("{not_found}");
    assert!(not_found_str.contains("ffmpeg executable was not found"));
    assert!(not_found_str.contains("https://ffmpeg.org"));

    let failed = VideoExportError::EncoderFailed {
        exit_code: Some(1),
        stderr: "codec error".to_string(),
    };
    let failed_str = format!("{failed}");
    assert!(failed_str.contains("status Some(1)"));
    assert!(failed_str.contains("codec error"));

    let io_err = VideoExportError::IoError(std::io::Error::new(
        std::io::ErrorKind::BrokenPipe,
        "broken pipe",
    ));
    use std::error::Error;
    assert!(io_err.source().is_some());
}
