//! Command-line options for the playback modes (`stuntreel [options] [<film>]`).

use std::env;
use std::path::{Path, PathBuf};

use clap::error::ErrorKind;
use clap::{CommandFactory, FromArgMatches, Parser};

use crate::{export, parity, sod_census};

/// Options as clap parses them, before cross-option rules and companion discovery.
#[derive(Debug, Parser)]
#[command(
    name = "stuntreel",
    about = "StuntReel Presentation Engine (stuntreel)"
)]
struct Options {
    /// A .FLM film and/or its .ALL archive; a missing companion is looked up beside the other
    #[arg(value_name = "FILM", num_args = 0..=2)]
    inputs: Vec<PathBuf>,
    /// Procedural .SOD model to bind to actor 1
    #[arg(long, value_name = "MODEL.SOD")]
    sod: Option<PathBuf>,
    /// Bind every actor `shape_id` to its .SOD chunk in the archive
    #[arg(long, value_name = "MOVIE.ALL")]
    all: Option<PathBuf>,
    /// Write the render store to DIR (`frames.zst`, `layers.zst`, `palettes.zst`,
    /// `preview/` and `render.json`, by 0-based 50 Hz tick); with --sample-count or
    /// --video, `DIR/sample_NNNN.png` instead
    #[arg(long, value_name = "DIR")]
    out_dir: Option<PathBuf>,
    /// Half-open 1-based tick ordinals to render; 1..N+2 covers ticks 0..=N
    /// (default: ticks 0..=total, the film's last tick included)
    #[arg(long, value_name = "A..B", value_parser = parse_frame_range)]
    frames: Option<FrameRange>,
    /// Directory searched first for ANCHORPT.DAT, MAP.BIN and SCENERY.scn; then the archive's
    /// directory, its parent and grandparent, then sidata/ or SIDATA/ inside the parent
    /// (names match any case)
    #[arg(long, value_name = "DIR")]
    sidata: Option<PathBuf>,
    /// Render the film to a video container (.mp4, .webm, .mkv, .avi) via ffmpeg
    #[arg(long, value_name = "FILE")]
    video: Option<PathBuf>,
    /// Tick stride for --out-dir frame extraction
    #[arg(long, value_name = "N", default_value_t = 1, value_parser = parse_positive_usize)]
    frame_step: usize,
    /// Render N evenly spaced frames across the selected tick range
    #[arg(
        long,
        value_name = "N",
        value_parser = parse_positive_usize,
        requires = "out_dir",
        conflicts_with = "video"
    )]
    sample_count: Option<usize>,
    /// Video sampling rate; container duration follows authored ticks
    #[arg(long, value_name = "HZ", default_value_t = 30.0, value_parser = parse_fps)]
    fps: f32,
    /// Offscreen framebuffer width
    #[arg(long, value_name = "PX", default_value_t = 320, value_parser = clap::value_parser!(u32).range(1..))]
    width: u32,
    /// Offscreen framebuffer height
    #[arg(long, value_name = "PX", default_value_t = 240, value_parser = clap::value_parser!(u32).range(1..))]
    height: u32,
    /// Offscreen only: draw the scene into the top N rows (PLAYONE uses 185 of 200)
    #[arg(long, value_name = "N")]
    viewport_rows: Option<u32>,
    /// Mode 13h palette index used to clear the framebuffer (default: 233 with an archive,
    /// else 180)
    #[arg(long, value_name = "I")]
    clear_index: Option<u8>,
    /// Run offscreen without opening a window
    #[arg(long)]
    headless: bool,
    /// Save the offscreen rendered frame to a PNG file
    #[arg(short = 'o', long = "output", value_name = "FILE")]
    output: Option<PathBuf>,
    /// Maximum authored 50 Hz ticks to evaluate/render
    #[arg(long = "ticks", value_name = "COUNT")]
    max_ticks: Option<usize>,
}

/// CLI configuration parsed from command-line arguments.
#[derive(Debug, Clone)]
pub(crate) struct CliConfig {
    pub flm_path: Option<PathBuf>,
    pub sod_path: Option<PathBuf>,
    pub all_path: Option<PathBuf>,
    pub out_dir: Option<PathBuf>,
    /// Half-open `[start, end)` 1-based tick ordinals to render, resolved against the
    /// film clock by [`crate::playback`]; `None` renders ticks `0..=total_ticks`.
    pub frame_range: Option<FrameRange>,
    /// Directory searched first for `ANCHORPT.DAT`, `MAP.BIN` and `SCENERY.scn`.
    pub sidata_dir: Option<PathBuf>,
    pub width: u32,
    pub height: u32,
    /// Draw the scene into the top this-many rows of the target only (`--viewport-rows`).
    pub viewport_rows: Option<u32>,
    pub clear_index: u8,
    pub headless: bool,
    pub output_png: Option<PathBuf>,
    pub max_ticks: Option<usize>,
    pub video_path: Option<PathBuf>,
    pub frame_step: usize,
    pub sample_count: Option<usize>,
    pub fps: f32,
}

impl CliConfig {
    pub(crate) fn parse() -> Result<Self, clap::Error> {
        Self::parse_from(env::args().skip(1))
    }

    /// Parses `args` (without the program name).
    pub(crate) fn parse_from(args: impl IntoIterator<Item = String>) -> Result<Self, clap::Error> {
        let mut command = Options::command().after_help(after_help());
        let argv = std::iter::once("stuntreel".to_string()).chain(args);
        let options = Options::from_arg_matches(&command.try_get_matches_from_mut(argv)?)?;
        Self::from_options(options).map_err(|msg| command.error(ErrorKind::ArgumentConflict, msg))
    }

    fn from_options(options: Options) -> Result<Self, String> {
        let Options {
            inputs,
            sod: sod_path,
            all: mut all_path,
            out_dir,
            frames: frame_range,
            sidata: sidata_dir,
            video: video_path,
            frame_step,
            sample_count,
            fps,
            width,
            height,
            viewport_rows,
            clear_index,
            headless,
            output: output_png,
            max_ticks,
        } = options;

        let mut flm_path = None;
        for path in inputs {
            let is_all = path
                .extension()
                .is_some_and(|ext| ext.eq_ignore_ascii_case("all"));
            if is_all && all_path.is_none() {
                all_path = Some(path);
            } else if flm_path.is_none() {
                flm_path = Some(path);
            } else if all_path.is_none() {
                all_path = Some(path);
            } else {
                return Err(format!("Unrecognized argument: {}", path.display()));
            }
        }

        let headless =
            headless || out_dir.is_some() || video_path.is_some() || output_png.is_some();
        if viewport_rows.is_some() && !headless {
            return Err(
                "--viewport-rows applies to offscreen renders only; add --headless, -o, --out-dir or --video"
                    .to_string(),
            );
        }

        if sod_path.is_none() {
            if let Some(flm) = &flm_path
                && all_path.is_none()
            {
                all_path = companion(flm, "ALL");
            } else if let Some(all) = &all_path
                && flm_path.is_none()
            {
                flm_path = companion(all, "FLM");
            }
        }

        let clear_index = clear_index.unwrap_or(if all_path.is_some() { 233 } else { 180 });

        Ok(Self {
            flm_path,
            sod_path,
            all_path,
            out_dir,
            frame_range,
            sidata_dir,
            width,
            height,
            viewport_rows,
            clear_index,
            headless,
            output_png,
            max_ticks,
            video_path,
            frame_step,
            sample_count,
            fps,
        })
    }
}

/// The file beside `path` with extension `ext` in upper or lower case, if it exists.
fn companion(path: &Path, ext: &str) -> Option<PathBuf> {
    [ext.to_ascii_uppercase(), ext.to_ascii_lowercase()]
        .into_iter()
        .map(|e| path.with_extension(e))
        .find(|p| p.is_file())
}

/// The half-open range of 1-based tick ordinals `--frames` asked for.
///
/// `A..B` renders tick ordinals `A` through `B - 1`, i.e. 0-based ticks `A - 1`
/// through `B - 2`. T12 replaces the flag with 0-based inclusive `--tick-range
/// A..=B`; until then [`crate::playback`] resolves these ordinals against the film.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) struct FrameRange {
    start: usize,
    end: usize,
}

impl FrameRange {
    /// A half-open range of 1-based tick ordinals.
    pub(crate) fn new(start: usize, end: usize) -> Self {
        Self { start, end }
    }

    /// The first rendered tick ordinal (1-based).
    #[must_use]
    pub(crate) fn start(self) -> usize {
        self.start
    }

    /// One past the last rendered tick ordinal (1-based).
    #[must_use]
    pub(crate) fn end(self) -> usize {
        self.end
    }
}

/// Parses a half-open `A..B` frame range into 1-based tick ordinals.
fn parse_frame_range(spec: &str) -> Result<FrameRange, String> {
    let (start, end) = spec
        .split_once("..")
        .ok_or_else(|| format!("expected A..B, got {spec:?}"))?;
    let start = start
        .trim()
        .parse::<usize>()
        .map_err(|e| format!("invalid range start: {e}"))?;
    let end = end
        .trim()
        .parse::<usize>()
        .map_err(|e| format!("invalid range end: {e}"))?;
    if end <= start {
        return Err(format!("{spec:?}: end must be greater than start"));
    }
    Ok(FrameRange::new(start, end))
}

fn parse_positive_usize(text: &str) -> Result<usize, String> {
    match text.parse::<usize>() {
        Ok(0) => Err("must be greater than zero".to_string()),
        Ok(n) => Ok(n),
        Err(e) => Err(e.to_string()),
    }
}

fn parse_fps(text: &str) -> Result<f32, String> {
    let rate = text.parse::<f32>().map_err(|e| e.to_string())?;
    if rate <= 0.0 || !rate.is_finite() {
        return Err("must be a positive finite number".to_string());
    }
    Ok(rate)
}

/// Help text after the options: the subcommands and the window's key bindings.
fn after_help() -> String {
    let indent = |usage: &str| format!("  {}", usage.replace('\n', "\n  "));
    format!(
        "Subcommands:\n{}\n\n{}\n\n{}\n\n\
         Interactive Keyboard Controls:\n  \
         Space   Pause / Resume timeline playback\n  \
         C       Toggle between Authored Camera and Free-Cam\n  \
         W / S   Free-Cam: Move Forward / Backward\n  \
         A / D   Free-Cam: Strafe Left / Right\n  \
         Q / E   Free-Cam: Move Down / Up\n  \
         Esc     Exit presentation",
        indent(&parity::usage()),
        indent(&export::usage()),
        indent(&sod_census::usage()),
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::path::Path;

    fn parse(args: &[&str]) -> Result<CliConfig, clap::Error> {
        CliConfig::parse_from(args.iter().map(|a| (*a).to_string()))
    }

    #[test]
    fn test_viewport_rows_needs_an_offscreen_render() {
        let Err(err) = parse(&["--viewport-rows", "185"]) else {
            panic!("a window run must reject --viewport-rows");
        };
        assert!(err.to_string().contains("--viewport-rows"), "{err}");
        let config = parse(&["--viewport-rows", "185", "--headless"]).expect("headless takes it");
        assert_eq!(config.viewport_rows, Some(185));
        assert!(parse(&["--viewport-rows", "185", "-o", "f.png"]).is_ok());
    }

    #[test]
    fn test_sample_count_needs_out_dir_and_no_video() {
        assert!(parse(&["--sample-count", "5"]).is_err());
        assert!(parse(&["--sample-count", "5", "--out-dir", "o", "--video", "v.mp4"]).is_err());
        assert!(parse(&["--sample-count", "0", "--out-dir", "o"]).is_err());
        assert!(parse(&["--fps", "0"]).is_err());
        assert!(parse(&["--frames", "5..5"]).is_err());
    }

    #[test]
    fn test_help_lists_subcommands_and_keys() {
        let err = parse(&["--help"]).expect_err("help exits early");
        assert_eq!(err.kind(), ErrorKind::DisplayHelp);
        let text = err.to_string();
        assert!(
            text.contains("--viewport-rows") && text.contains("export-gltf"),
            "{text}"
        );
        assert!(text.contains("Free-Cam"), "{text}");
    }

    #[test]
    fn test_any_nonzero_width_parses() {
        let config = parse(&["--width", "100", "--headless"]).expect("unaligned width is fine");
        assert_eq!(config.width, 100);
        assert!(parse(&["--width", "0", "--headless"]).is_err());
    }

    #[test]
    fn test_tick_range_and_sample_options_parse() {
        let config = CliConfig::parse_from(vec![
            "film.flm".to_string(),
            "--frames".to_string(),
            "2..10".to_string(),
            "--frame-step".to_string(),
            "3".to_string(),
            "--sample-count".to_string(),
            "5".to_string(),
            "--out-dir".to_string(),
            "out".to_string(),
            "--fps".to_string(),
            "50".to_string(),
            "--sidata".to_string(),
            "data/SIDATA".to_string(),
        ])
        .expect("parse succeeds");

        assert_eq!(config.frame_range, Some(FrameRange::new(2, 10)));
        assert_eq!(config.frame_step, 3);
        assert_eq!(config.sample_count, Some(5));
        assert_eq!(config.fps, 50.0);
        assert_eq!(config.sidata_dir, Some(PathBuf::from("data/SIDATA")));

        assert!(
            CliConfig::parse_from(vec![
                "film.flm".to_string(),
                "--sample-count".to_string(),
                "5".to_string()
            ])
            .is_err()
        );
    }

    #[test]
    fn test_all_companion_autodiscovery() {
        let manifest_dir = Path::new(env!("CARGO_MANIFEST_DIR"));
        let workspace_root = manifest_dir.parent().unwrap().parent().unwrap();
        let fixture_flm = workspace_root.join("tests/fixtures/synthetic_minimal.flm");
        let expected_all = workspace_root.join("tests/fixtures/synthetic_minimal.all");
        let config = CliConfig::parse_from(vec![
            fixture_flm.to_string_lossy().to_string(),
            "--headless".to_string(),
        ]);
        let cfg = config.expect("parse succeeds");
        assert!(cfg.all_path.is_some());
        assert_eq!(
            cfg.all_path.unwrap().to_string_lossy().to_ascii_lowercase(),
            expected_all.to_string_lossy().to_ascii_lowercase()
        );
        assert_eq!(cfg.clear_index, 233);
    }

    #[test]
    fn test_flm_companion_autodiscovery_from_all() {
        let manifest_dir = Path::new(env!("CARGO_MANIFEST_DIR"));
        let workspace_root = manifest_dir.parent().unwrap().parent().unwrap();
        let fixture_flm = workspace_root.join("tests/fixtures/synthetic_minimal.flm");
        let fixture_all = workspace_root.join("tests/fixtures/synthetic_minimal.all");
        let config = CliConfig::parse_from(vec![
            fixture_all.to_string_lossy().to_string(),
            "-o".to_string(),
            "out.png".to_string(),
        ]);
        let cfg = config.expect("parse succeeds");
        assert!(cfg.headless, "output_png implies headless");
        assert!(cfg.all_path.is_some());
        assert!(cfg.flm_path.is_some());
        assert_eq!(
            cfg.flm_path.unwrap().to_string_lossy().to_ascii_lowercase(),
            fixture_flm.to_string_lossy().to_ascii_lowercase()
        );
        assert_eq!(cfg.clear_index, 233);
    }
}
