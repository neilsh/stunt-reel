//! Command-line options for the playback modes (`stuntreel [options] [<film>]`).

use std::env;
use std::path::PathBuf;

use crate::{export, parity};

/// CLI configuration parsed from command-line arguments.
#[derive(Debug, Clone)]
pub(crate) struct CliConfig {
    pub flm_path: Option<PathBuf>,
    pub sod_path: Option<PathBuf>,
    pub all_path: Option<PathBuf>,
    pub out_dir: Option<PathBuf>,
    /// Half-open `[start, end)` 1-based tick ordinals to render; `None` renders ticks
    /// `0..=total_ticks`.
    pub frame_range: Option<(usize, usize)>,
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
    pub(crate) fn parse() -> Result<Self, String> {
        Self::parse_from(env::args().skip(1))
    }

    pub(crate) fn parse_from(mut args: impl Iterator<Item = String>) -> Result<Self, String> {
        let mut flm_path = None;
        let mut sod_path = None;
        let mut all_path = None;
        let mut out_dir = None;
        let mut frame_range = None;
        let mut sidata_dir = None;
        let mut width = 320u32;
        let mut height = 240u32;
        let mut viewport_rows: Option<u32> = None;
        let mut clear_index = 180u8;
        let mut explicit_clear_index = false;
        let mut headless = false;
        let mut output_png = None;
        let mut max_ticks = None;
        let mut video_path = None;
        let mut frame_step = 1usize;
        let mut sample_count = None;
        let mut fps = 30.0f32;

        while let Some(arg) = args.next() {
            match arg.as_str() {
                "--help" | "-h" => {
                    Self::print_usage();
                    std::process::exit(0);
                }
                "--headless" => {
                    headless = true;
                }
                "--sod" => {
                    let val = args.next().ok_or("Expected path after --sod")?;
                    sod_path = Some(PathBuf::from(val));
                }
                "--all" => {
                    let val = args.next().ok_or("Expected path after --all")?;
                    all_path = Some(PathBuf::from(val));
                }
                "--out-dir" => {
                    let val = args.next().ok_or("Expected directory after --out-dir")?;
                    out_dir = Some(PathBuf::from(val));
                }
                "--frames" => {
                    let val = args.next().ok_or("Expected A..B after --frames")?;
                    frame_range = Some(Self::parse_frame_range(&val)?);
                }
                "--sidata" => {
                    let val = args.next().ok_or("Expected directory after --sidata")?;
                    sidata_dir = Some(PathBuf::from(val));
                }
                "--video" => {
                    let val = args.next().ok_or("Expected path after --video")?;
                    video_path = Some(PathBuf::from(val));
                }
                "--frame-step" => {
                    let val = args.next().ok_or("Expected number after --frame-step")?;
                    let step = val
                        .parse::<usize>()
                        .map_err(|e| format!("Invalid frame step: {e}"))?;
                    if step == 0 {
                        return Err("Frame step must be greater than zero".to_string());
                    }
                    frame_step = step;
                }
                "--sample-count" => {
                    let val = args.next().ok_or("Expected number after --sample-count")?;
                    let count = val
                        .parse::<usize>()
                        .map_err(|e| format!("Invalid sample count: {e}"))?;
                    if count == 0 {
                        return Err("Sample count must be greater than zero".to_string());
                    }
                    sample_count = Some(count);
                }
                "--fps" => {
                    let val = args.next().ok_or("Expected number after --fps")?;
                    let rate = val
                        .parse::<f32>()
                        .map_err(|e| format!("Invalid fps: {e}"))?;
                    if rate <= 0.0 || !rate.is_finite() {
                        return Err("FPS must be a positive finite number".to_string());
                    }
                    fps = rate;
                }
                "--width" => {
                    let val = args.next().ok_or("Expected number after --width")?;
                    width = val
                        .parse::<u32>()
                        .map_err(|e| format!("Invalid width: {e}"))?;
                }
                "--height" => {
                    let val = args.next().ok_or("Expected number after --height")?;
                    height = val
                        .parse::<u32>()
                        .map_err(|e| format!("Invalid height: {e}"))?;
                }
                "--viewport-rows" => {
                    let val = args.next().ok_or("Expected number after --viewport-rows")?;
                    viewport_rows = Some(
                        val.parse::<u32>()
                            .map_err(|e| format!("Invalid viewport rows: {e}"))?,
                    );
                }
                "--clear-index" => {
                    let val = args.next().ok_or("Expected number after --clear-index")?;
                    clear_index = val
                        .parse::<u8>()
                        .map_err(|e| format!("Invalid palette index: {e}"))?;
                    explicit_clear_index = true;
                }
                "--output" | "-o" => {
                    let val = args.next().ok_or("Expected path after --output")?;
                    output_png = Some(PathBuf::from(val));
                }
                "--ticks" => {
                    let val = args.next().ok_or("Expected number after --ticks")?;
                    let n = val
                        .parse::<usize>()
                        .map_err(|e| format!("Invalid tick count: {e}"))?;
                    max_ticks = Some(n);
                }
                other => {
                    if other.starts_with('-') {
                        return Err(format!("Unrecognized argument: {other}"));
                    }
                    let path = PathBuf::from(other);
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
                        return Err(format!("Unrecognized argument: {other}"));
                    }
                }
            }
        }

        if width == 0 || height == 0 {
            return Err("Framebuffer dimensions must be non-zero".to_string());
        }
        if out_dir.is_some() || video_path.is_some() || output_png.is_some() {
            headless = true;
        }
        if viewport_rows.is_some() && !headless {
            return Err(
                "--viewport-rows applies to offscreen renders only; add --headless, -o, --out-dir or --video"
                    .to_string(),
            );
        }

        if video_path.is_some() && sample_count.is_some() {
            return Err("--sample-count cannot be combined with --video".to_string());
        }
        if sample_count.is_some() && out_dir.is_none() {
            return Err("--sample-count requires --out-dir".to_string());
        }

        if sod_path.is_none() {
            if let Some(flm) = &flm_path
                && all_path.is_none()
            {
                let candidate_upper = flm.with_extension("ALL");
                if candidate_upper.is_file() {
                    all_path = Some(candidate_upper);
                } else {
                    let candidate_lower = flm.with_extension("all");
                    if candidate_lower.is_file() {
                        all_path = Some(candidate_lower);
                    }
                }
            } else if let Some(all) = &all_path
                && flm_path.is_none()
            {
                let candidate_upper = all.with_extension("FLM");
                if candidate_upper.is_file() {
                    flm_path = Some(candidate_upper);
                } else {
                    let candidate_lower = all.with_extension("flm");
                    if candidate_lower.is_file() {
                        flm_path = Some(candidate_lower);
                    }
                }
            }
        }

        let clear_index = if explicit_clear_index {
            clear_index
        } else if all_path.is_some() {
            233
        } else {
            180
        };

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

    /// Parses a half-open `A..B` frame range.
    fn parse_frame_range(spec: &str) -> Result<(usize, usize), String> {
        let (start, end) = spec
            .split_once("..")
            .ok_or_else(|| format!("Invalid frame range {spec:?}, expected A..B"))?;
        let start = start
            .trim()
            .parse::<usize>()
            .map_err(|e| format!("Invalid frame range start: {e}"))?;
        let end = end
            .trim()
            .parse::<usize>()
            .map_err(|e| format!("Invalid frame range end: {e}"))?;
        if end <= start {
            return Err(format!(
                "Invalid frame range {spec:?}: end must be greater than start"
            ));
        }
        Ok((start, end))
    }

    pub(crate) fn print_usage() {
        println!("StuntReel Presentation Engine (stuntreel)");
        println!("Usage: stuntreel [options] [<flight.flm>]");
        println!();
        println!("Arguments:");
        println!("  <flight.flm>         Path to authored .FLM choreography file (optional)");
        println!();
        println!("Options:");
        println!("  --sod <model.sod>    Path to procedural .SOD model to bind to actor 1");
        println!(
            "  --all <movie.all>    Bind every actor shape_id to its .SOD chunk in the archive"
        );
        println!("  --out-dir <dir>      Write <dir>/tick_NNNNN.png (NNNNN = 0-based 50 Hz tick);");
        println!(
            "                       with --sample-count or --video, <dir>/sample_NNNN.png instead"
        );
        println!(
            "  --frames <A..B>      Half-open 1-based tick ordinals to render; 1..N+2 covers ticks 0..=N"
        );
        println!(
            "                       (default: ticks 0..=total, the film's last tick included)"
        );
        println!(
            "  --sidata <dir>       Directory searched first for ANCHORPT.DAT, MAP.BIN and SCENERY.scn;"
        );
        println!(
            "                       then the archive's directory, its parent and grandparent,"
        );
        println!(
            "                       then sidata/ or SIDATA/ inside the parent (names match any case)"
        );
        println!(
            "  --video <file>       Render film to video container (.mp4, .webm, .mkv, .avi) via ffmpeg"
        );
        println!("  --frame-step <N>     Tick stride for --out-dir frame extraction (default: 1)");
        println!(
            "  --sample-count <N>   Render N evenly spaced frames across the selected tick range"
        );
        println!(
            "  --fps <HZ>           Video sampling rate; container duration follows authored ticks (default: 30)"
        );
        println!("  --width <px>         Offscreen framebuffer width (default 320)");
        println!("  --height <px>        Offscreen framebuffer height (default 240)");
        println!(
            "  --viewport-rows <n>  Offscreen only: draw the scene into the top n rows (PLAYONE uses 185 of 200)"
        );
        println!("  --clear-index <i>    Mode 13h palette index used to clear the framebuffer");
        println!("  --headless           Run in offscreen headless mode without opening a window");
        println!("  --output, -o <file>  Save offscreen rendered frame to PNG file");
        println!("  --ticks <count>      Maximum authored 50 Hz ticks to evaluate/render");
        println!("  -h, --help           Print this help information");
        println!();
        println!("Subcommands:");
        println!("  {}", parity::USAGE.replace('\n', "\n  "));
        println!();
        println!("  {}", export::USAGE.replace('\n', "\n  "));
        println!();
        println!("Interactive Keyboard Controls:");
        println!("  Space                Pause / Resume timeline playback");
        println!("  C                    Toggle between Authored Camera and Free-Cam");
        println!("  W / S                Free-Cam: Move Forward / Backward");
        println!("  A / D                Free-Cam: Strafe Left / Right");
        println!("  Q / E                Free-Cam: Move Down / Up");
        println!("  Esc                  Exit presentation");
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::path::Path;

    fn parse(args: &[&str]) -> Result<CliConfig, String> {
        CliConfig::parse_from(args.iter().map(|a| (*a).to_string()))
    }

    #[test]
    fn test_viewport_rows_needs_an_offscreen_render() {
        let Err(err) = parse(&["--viewport-rows", "185"]) else {
            panic!("a window run must reject --viewport-rows");
        };
        assert!(err.contains("--viewport-rows"), "{err}");
        let config = parse(&["--viewport-rows", "185", "--headless"]).expect("headless takes it");
        assert_eq!(config.viewport_rows, Some(185));
        assert!(parse(&["--viewport-rows", "185", "-o", "f.png"]).is_ok());
    }

    #[test]
    fn test_any_nonzero_width_parses() {
        let config = parse(&["--width", "100", "--headless"]).expect("unaligned width is fine");
        assert_eq!(config.width, 100);
        assert!(parse(&["--width", "0", "--headless"]).is_err());
    }

    #[test]
    fn test_tick_range_and_sample_options_parse() {
        let config = CliConfig::parse_from(
            vec![
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
            ]
            .into_iter(),
        )
        .expect("parse succeeds");

        assert_eq!(config.frame_range, Some((2, 10)));
        assert_eq!(config.frame_step, 3);
        assert_eq!(config.sample_count, Some(5));
        assert_eq!(config.fps, 50.0);
        assert_eq!(config.sidata_dir, Some(PathBuf::from("data/SIDATA")));

        assert!(
            CliConfig::parse_from(
                vec![
                    "film.flm".to_string(),
                    "--sample-count".to_string(),
                    "5".to_string()
                ]
                .into_iter()
            )
            .is_err()
        );
    }

    #[test]
    fn test_all_companion_autodiscovery() {
        let manifest_dir = Path::new(env!("CARGO_MANIFEST_DIR"));
        let workspace_root = manifest_dir.parent().unwrap().parent().unwrap();
        let fixture_flm = workspace_root.join("tests/fixtures/synthetic_minimal.flm");
        let expected_all = workspace_root.join("tests/fixtures/synthetic_minimal.all");
        let config = CliConfig::parse_from(
            vec![
                fixture_flm.to_string_lossy().to_string(),
                "--headless".to_string(),
            ]
            .into_iter(),
        );
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
        let config = CliConfig::parse_from(
            vec![
                fixture_all.to_string_lossy().to_string(),
                "-o".to_string(),
                "out.png".to_string(),
            ]
            .into_iter(),
        );
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
