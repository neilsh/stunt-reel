//! Streaming video container exporter piping raw RGBA frames to `ffmpeg`.
//!
//! Complies with Architectural Invariants:
//! - `[I4]` Discrete simulation ticks (50 Hz) temporal authoring.
//! - `[I6]` 4:3 physical display aspect ratio presentation.

use std::io::Write;
use std::path::Path;
use std::process::{Child, ChildStdin, Command, Stdio};

/// Errors occurring during video container export via ffmpeg.
#[derive(Debug)]
pub enum VideoExportError {
    /// The `ffmpeg` executable was not found on `PATH`.
    FfmpegNotFound,
    /// Failed to spawn the `ffmpeg` subprocess.
    SpawnFailed(std::io::Error),
    /// An I/O error occurred communicating with `ffmpeg`.
    IoError(std::io::Error),
    /// The `ffmpeg` process exited with a non-zero exit code.
    EncoderFailed {
        /// Process exit code, if available.
        exit_code: Option<i32>,
        /// Captured standard error output.
        stderr: String,
    },
}

impl std::fmt::Display for VideoExportError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::FfmpegNotFound => write!(
                f,
                "ffmpeg executable was not found on PATH. Video export requires ffmpeg (https://ffmpeg.org). Please install ffmpeg or add it to PATH."
            ),
            Self::SpawnFailed(err) => write!(f, "Failed to spawn ffmpeg: {err}"),
            Self::IoError(err) => write!(f, "I/O error communicating with ffmpeg: {err}"),
            Self::EncoderFailed { exit_code, stderr } => write!(
                f,
                "ffmpeg exited with status {:?}: {}",
                exit_code,
                stderr.trim()
            ),
        }
    }
}

impl std::error::Error for VideoExportError {
    fn source(&self) -> Option<&(dyn std::error::Error + 'static)> {
        match self {
            Self::SpawnFailed(err) | Self::IoError(err) => Some(err),
            _ => None,
        }
    }
}

/// Streaming video container exporter piping raw RGBA frames over a subprocess pipe to `ffmpeg`.
#[derive(Debug)]
pub struct FfmpegVideoWriter {
    child: Child,
    stdin: Option<ChildStdin>,
    width: u32,
    height: u32,
    fps: f32,
}

/// Type alias for [`FfmpegVideoWriter`].
pub type VideoExporter = FfmpegVideoWriter;

impl FfmpegVideoWriter {
    /// Checks whether the `ffmpeg` executable is installed and accessible on `PATH`.
    #[must_use]
    pub fn is_available() -> bool {
        Command::new("ffmpeg")
            .arg("-version")
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .status()
            .map(|s| s.success())
            .unwrap_or(false)
    }

    /// Alias for [`is_available`][Self::is_available].
    #[must_use]
    pub fn is_ffmpeg_available() -> bool {
        Self::is_available()
    }

    /// Spawns an `ffmpeg` process ready to receive raw RGBA frames over standard input.
    ///
    /// # Parameters
    /// - `path`: Destination video file path (`.mp4`, `.webm`, `.mkv`, `.avi`).
    /// - `width`: Frame width in pixels (e.g. 320).
    /// - `height`: Frame height in pixels (e.g. 240).
    /// - `fps`: Container framerate matching simulation tick frequency (Invariant `[I4]`, e.g. 30.0).
    pub fn open(path: &Path, width: u32, height: u32, fps: f32) -> Result<Self, VideoExportError> {
        Self::open_with_duration(path, width, height, fps, None)
    }

    /// Spawns an `ffmpeg` process and trims the container to an authored duration.
    ///
    /// A constant frame rate cannot represent an arbitrary authored span exactly
    /// (`frame_count / fps` rounds to whole frames). Passing the authored duration
    /// adds ffmpeg's `-t` cut so the container length matches the film clock rather
    /// than the last encoded frame boundary.
    pub fn open_with_duration(
        path: &Path,
        width: u32,
        height: u32,
        fps: f32,
        duration_seconds: Option<f32>,
    ) -> Result<Self, VideoExportError> {
        let mut cmd = Command::new("ffmpeg");
        cmd.arg("-y")
            .arg("-f")
            .arg("rawvideo")
            .arg("-vcodec")
            .arg("rawvideo")
            .arg("-pix_fmt")
            .arg("rgba")
            .arg("-s")
            .arg(format!("{width}x{height}"))
            .arg("-r")
            .arg(format!("{fps}"))
            .arg("-i")
            .arg("-");

        let ext = path
            .extension()
            .and_then(|s| s.to_str())
            .unwrap_or("")
            .to_ascii_lowercase();

        if ext == "webm" {
            cmd.arg("-c:v").arg("libvpx-vp9");
        } else {
            cmd.arg("-c:v").arg("libx264").arg("-preset").arg("fast");
        }

        cmd.arg("-pix_fmt")
            .arg("yuv420p")
            .arg("-aspect")
            .arg("4:3")
            .arg("-an");

        if let Some(duration) = duration_seconds
            && duration.is_finite()
            && duration > 0.0
        {
            cmd.arg("-t").arg(format!("{duration:.6}"));
        }

        cmd.arg(path);

        cmd.stdin(Stdio::piped())
            .stdout(Stdio::null())
            .stderr(Stdio::piped());

        let mut child = cmd.spawn().map_err(|err| {
            if err.kind() == std::io::ErrorKind::NotFound {
                VideoExportError::FfmpegNotFound
            } else {
                VideoExportError::SpawnFailed(err)
            }
        })?;

        let stdin = child.stdin.take();
        Ok(Self {
            child,
            stdin,
            width,
            height,
            fps,
        })
    }

    /// Alias for [`open`][Self::open].
    pub fn new(path: &Path, width: u32, height: u32, fps: f32) -> Result<Self, VideoExportError> {
        Self::open(path, width, height, fps)
    }

    /// Configured frame width in pixels.
    #[must_use]
    pub fn width(&self) -> u32 {
        self.width
    }

    /// Configured frame height in pixels.
    #[must_use]
    pub fn height(&self) -> u32 {
        self.height
    }

    /// Configured container framerate in Hertz.
    #[must_use]
    pub fn fps(&self) -> f32 {
        self.fps
    }

    /// Writes a single raw RGBA frame to the encoder pipe.
    pub fn write_frame(&mut self, rgba_bytes: &[u8]) -> Result<(), VideoExportError> {
        let Some(stdin) = &mut self.stdin else {
            return Err(VideoExportError::IoError(std::io::Error::new(
                std::io::ErrorKind::BrokenPipe,
                "ffmpeg stdin stream is not open",
            )));
        };

        stdin
            .write_all(rgba_bytes)
            .map_err(VideoExportError::IoError)?;
        Ok(())
    }

    /// Closes standard input and waits for `ffmpeg` to finish encoding.
    pub fn finish(mut self) -> Result<(), VideoExportError> {
        drop(self.stdin.take());
        let output = self
            .child
            .wait_with_output()
            .map_err(VideoExportError::IoError)?;
        if !output.status.success() {
            let stderr = String::from_utf8_lossy(&output.stderr).to_string();
            return Err(VideoExportError::EncoderFailed {
                exit_code: output.status.code(),
                stderr,
            });
        }
        Ok(())
    }
}
