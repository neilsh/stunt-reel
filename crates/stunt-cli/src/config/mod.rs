//! Command-line options for the playback modes (`stuntreel [options] [<film>]`).

use std::env;
use std::path::{Path, PathBuf};

use clap::error::ErrorKind;
use clap::{CommandFactory as _, FromArgMatches as _, Parser};

use stunt_render::RenderOptions;

use crate::{export, film_slots, link, shape_views, sod_census, sod_trace};

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
    /// Instead of an archive, read every shape from the game tree's RES/*.RES files (names
    /// match any case); scenery is then searched for from the film
    #[arg(long, value_name = "TREE", conflicts_with = "all")]
    game: Option<PathBuf>,
    /// Write the render store to DIR (`frames.zst`, `layers.zst`, `palettes.zst`,
    /// `preview/` and `render.json`, by 0-based 50 Hz tick); with --sample-count or
    /// --video, `DIR/sample_NNNN.png` instead
    #[arg(long, value_name = "DIR")]
    out_dir: Option<PathBuf>,
    /// 0-based, inclusive film ticks to render; 0..=N covers ticks 0 through N
    /// (default: ticks 0..=total, the film's last tick included)
    #[arg(long = "tick-range", value_name = "A..=B", value_parser = parse_tick_span)]
    tick_span: Option<TickSpan>,
    /// Removed: `--tick-range A..=B` replaces it (0-based, inclusive)
    #[arg(long, hide = true, num_args = 0.., value_name = "A..B")]
    frames: Option<Vec<String>>,
    /// Render exactly these 0-based film ticks (comma-separated), in one process
    #[arg(
        long = "at-ticks",
        value_name = "T,T,...",
        value_parser = parse_tick_list,
        requires = "out_dir",
        conflicts_with_all = ["tick_span", "sample_count", "video"]
    )]
    ticks: Option<TickList>,
    /// Directory searched first for ANCHORPT.DAT, MAP.BIN and SCENERY.scn; then the archive's
    /// directory (the film's with --game), its parent and grandparent, then sidata/ or SIDATA/
    /// inside the parent (names match any case)
    #[arg(long, value_name = "DIR")]
    sidata: Option<PathBuf>,
    /// PLAYONE's PFONT.BIN for the credits text; by default it is searched for in --sidata,
    /// then beside the archive, in the --game tree and beside the film, their parent and
    /// grandparent, and a sidata directory there (the engine root holds it, beside VAULT)
    #[arg(long, value_name = "PFONT.BIN")]
    font: Option<PathBuf>,
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
    /// Mode 13h palette index used to clear the framebuffer (default: 233 with an archive or
    /// --game, else 180)
    #[arg(long, value_name = "I")]
    clear_index: Option<u8>,
    /// Render on the software adapter (lavapipe), even when a GPU is available
    #[arg(long)]
    software_only: bool,
    /// Run offscreen without opening a window
    #[arg(long)]
    headless: bool,
    /// Headless only: print the resident memory after the scene is built, the renderer opened,
    /// the world mesh freed and the frames rendered, and the process peak at the end
    #[arg(long)]
    report_memory: bool,
    /// Save the offscreen rendered frame to a PNG file
    #[arg(short = 'o', long = "output", value_name = "FILE")]
    output: Option<PathBuf>,
    /// Maximum authored 50 Hz ticks to evaluate/render
    #[arg(long = "ticks", value_name = "COUNT")]
    max_ticks: Option<usize>,
    /// Render the --out-dir store in N child processes, each a run of whole film seconds with
    /// `LP_NUM_THREADS=1`, and join their stores into one byte-identical to a 1-worker render
    #[arg(long, value_name = "N", default_value_t = 1, value_parser = parse_positive_usize)]
    workers: usize,
    /// Internal: render only worker K's film seconds of a --workers run, into its own store
    #[arg(long, hide = true, value_name = "K", requires = "out_dir")]
    shard: Option<usize>,
}

/// CLI configuration parsed from command-line arguments.
#[derive(Debug, Clone)]
pub(crate) struct CliConfig {
    pub flm_path: Option<PathBuf>,
    pub sod_path: Option<PathBuf>,
    pub all_path: Option<PathBuf>,
    /// Game tree whose `RES` files supply the shapes (`--game`); never set with `all_path`.
    pub game_dir: Option<PathBuf>,
    pub out_dir: Option<PathBuf>,
    /// The 0-based inclusive ticks from `--tick-range`, resolved against the film clock
    /// by [`crate::playback`]; `None` renders ticks `0..=total_ticks`.
    pub tick_span: Option<TickSpan>,
    /// Exact 0-based film ticks from `--at-ticks`, ascending and distinct.
    pub tick_list: Option<TickList>,
    /// Directory searched first for `ANCHORPT.DAT`, `MAP.BIN` and `SCENERY.scn`.
    pub sidata_dir: Option<PathBuf>,
    /// `PFONT.BIN` named with `--font`; `None` searches as for the scenery files, from the
    /// archive and then from the film.
    pub font_path: Option<PathBuf>,
    pub width: u32,
    pub height: u32,
    /// Draw the scene into the top this-many rows of the target only (`--viewport-rows`).
    pub viewport_rows: Option<u32>,
    pub clear_index: u8,
    /// Render on the software adapter even when a GPU is available (`--software-only`).
    pub software_only: bool,
    pub headless: bool,
    /// Print the resident memory at each stage of a headless render (`--report-memory`).
    pub report_memory: bool,
    pub output_png: Option<PathBuf>,
    pub max_ticks: Option<usize>,
    pub video_path: Option<PathBuf>,
    pub frame_step: usize,
    pub sample_count: Option<usize>,
    pub fps: f32,
    /// Child processes the render store is split across (`--workers`); 1 renders in-process.
    pub workers: usize,
    /// The worker this process is in a `--workers` run (`--shard`); its `out_dir` is already
    /// [`crate::workers::shard_dir`] of the run's.
    pub shard: Option<usize>,
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

    /// The render options this configuration asks for, headless or windowed.
    #[must_use]
    pub(crate) fn render_options(&self) -> RenderOptions {
        RenderOptions {
            clear_palette_index: self.clear_index,
            software_only: self.software_only,
        }
    }

    fn from_options(options: Options) -> Result<Self, String> {
        let Options {
            inputs,
            sod: sod_path,
            all: mut all_path,
            game: game_dir,
            out_dir,
            tick_span,
            frames,
            ticks: tick_list,
            sidata: sidata_dir,
            font: font_path,
            video: video_path,
            frame_step,
            sample_count,
            fps,
            width,
            height,
            viewport_rows,
            clear_index,
            software_only,
            headless,
            report_memory,
            output: output_png,
            max_ticks,
            workers,
            shard,
        } = options;

        if frames.is_some() {
            return Err(
                "--frames was replaced by --tick-range A..=B (0-based film ticks, inclusive); \
                 --frames A..B rendered ticks A-1 through B-2, so use --tick-range A-1..=B-2"
                    .to_string(),
            );
        }

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

        if report_memory && !headless {
            return Err(
                "--report-memory applies to offscreen renders only; add --headless, -o, --out-dir or --video"
                    .to_string(),
            );
        }

        if let (Some(_), Some(all)) = (&game_dir, &all_path) {
            return Err(format!(
                "--game reads the shapes in place of an archive; drop {} or --game",
                all.display()
            ));
        }

        // With `--game` the shapes need no archive, so none is looked for beside the film.
        if sod_path.is_none() && game_dir.is_none() {
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

        if workers > 1 {
            if out_dir.is_none() {
                return Err(
                    "--workers splits the --out-dir render store; add --out-dir".to_string()
                );
            }
            if video_path.is_some() || sample_count.is_some() || output_png.is_some() {
                return Err(
                    "--workers splits whole-tick renders only; drop --video, --sample-count or -o"
                        .to_string(),
                );
            }
        }
        if let Some(shard) = shard
            && shard >= workers
        {
            return Err(format!("--shard {shard} is not below --workers {workers}"));
        }
        let out_dir = match (shard, out_dir) {
            (Some(shard), Some(dir)) => Some(crate::workers::shard_dir(&dir, shard)),
            (_, dir) => dir,
        };

        let has_shapes = all_path.is_some() || game_dir.is_some();
        let clear_index = clear_index.unwrap_or(if has_shapes { 233 } else { 180 });

        Ok(Self {
            flm_path,
            sod_path,
            all_path,
            game_dir,
            out_dir,
            tick_span,
            tick_list,
            sidata_dir,
            font_path,
            width,
            height,
            viewport_rows,
            clear_index,
            software_only,
            headless,
            report_memory,
            output_png,
            max_ticks,
            video_path,
            frame_step,
            sample_count,
            fps,
            workers,
            shard,
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

/// The 0-based, inclusive ticks `--tick-range A..=B` asked for.
///
/// `first` and `last` are film-clock ticks as everywhere else in the project;
/// [`crate::playback`] clamps `last` to the film's clock.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) struct TickSpan {
    first: usize,
    last: usize,
}

impl TickSpan {
    /// The inclusive span `first..=last` of 0-based ticks.
    pub(crate) fn new(first: usize, last: usize) -> Self {
        Self { first, last }
    }

    /// The first rendered tick.
    #[must_use]
    pub(crate) fn first(self) -> usize {
        self.first
    }

    /// The last rendered tick, included.
    #[must_use]
    pub(crate) fn last(self) -> usize {
        self.last
    }
}

/// The 0-based film ticks `--at-ticks` named, ascending and without repeats.
pub(crate) type TickList = Vec<usize>;

/// Parses `--at-ticks 48,92,1009` into an ascending, de-duplicated tick list.
fn parse_tick_list(spec: &str) -> Result<TickList, String> {
    let mut ticks = spec
        .split(',')
        .map(|part| {
            part.trim()
                .parse::<usize>()
                .map_err(|e| format!("invalid tick {part:?}: {e}"))
        })
        .collect::<Result<TickList, String>>()?;
    ticks.sort_unstable();
    ticks.dedup();
    Ok(ticks)
}

/// Parses `A..=B` into a 0-based inclusive tick span.
fn parse_tick_span(spec: &str) -> Result<TickSpan, String> {
    let (first, last) = spec
        .split_once("..=")
        .ok_or_else(|| format!("expected A..=B (0-based, inclusive), got {spec:?}"))?;
    let first = first
        .trim()
        .parse::<usize>()
        .map_err(|e| format!("invalid range start: {e}"))?;
    let last = last
        .trim()
        .parse::<usize>()
        .map_err(|e| format!("invalid range end: {e}"))?;
    if last < first {
        return Err(format!("{spec:?}: end must not be less than start"));
    }
    Ok(TickSpan::new(first, last))
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
        "Subcommands:\n{}\n\n{}\n\n{}\n\n{}\n\n{}\n\n{}\n\n{}\n\n\
         Interactive Keyboard Controls:\n  \
         Space   Pause / Resume timeline playback\n  \
         C       Toggle between Authored Camera and Free-Cam\n  \
         W / S   Free-Cam: Move Forward / Backward\n  \
         A / D   Free-Cam: Strafe Left / Right\n  \
         Q / E   Free-Cam: Move Down / Up\n  \
         Esc     Exit presentation",
        indent(&crate::parity::usage()),
        indent(&export::usage()),
        indent(&shape_views::usage()),
        indent(&sod_census::usage()),
        indent(&sod_trace::usage()),
        indent(&film_slots::usage()),
        indent(&link::usage()),
    )
}

#[cfg(test)]
mod tests;
