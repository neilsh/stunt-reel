//! Automated offline verification for video container export.
//!
//! Validates Gate G08 and system invariants:
//! - `[I4]` Discrete simulation ticks temporal authoring.
//! - `[I6]` 4:3 physical display aspect ratio presentation.
//! - `[I7]` Cleanroom synthetic fixture execution.
//!
//! The interval frame-capture test moved to renderer_test.rs, where it drives the Renderer
//! entry point with a counting sink instead of constructing GPU state.

use std::fs;
use std::path::PathBuf;
use stunt_render::{FfmpegVideoWriter, VideoExportError};

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
