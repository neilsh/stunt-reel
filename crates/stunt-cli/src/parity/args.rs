//! `stuntreel parity` command-line arguments.

use std::path::PathBuf;

use clap::{CommandFactory, Parser};

/// Parsed `stuntreel parity` arguments.
#[derive(Debug, Parser)]
#[command(
    bin_name = "stuntreel parity",
    about = "Score rendered frames against a PLAYONE capture"
)]
pub(super) struct Args {
    /// Capture directory holding meta.json and the captured frames
    #[arg(long, value_name = "DIR")]
    pub(super) reference: PathBuf,
    /// Render directory written by `stuntreel --out-dir`
    #[arg(long, value_name = "DIR")]
    pub(super) test: PathBuf,
    /// Directory for report.json and the contact sheets
    #[arg(long, value_name = "DIR")]
    pub(super) output: PathBuf,
    /// Frames whose measured palette fade level is below F are reported but left out of the
    /// scored means
    #[arg(
        long,
        value_name = "F",
        default_value_t = 0.25,
        value_parser = parse_min_fade_level,
        allow_negative_numbers = true
    )]
    pub(super) min_fade_level: f32,
    /// Match frames by film_tick against a previous report and print mean SSIM/IoU deltas,
    /// the 5 most improved/regressed frames and the counts changed by more than 0.005;
    /// writes compare.json
    #[arg(long, value_name = "REPORT.JSON")]
    pub(super) compare: Option<PathBuf>,
    /// The previous run's render directory; with --compare, writes before/after contact
    /// sheets for the most regressed and most improved frame (skipped, with a note, when
    /// absent)
    #[arg(long, value_name = "DIR", requires = "compare")]
    pub(super) compare_test: Option<PathBuf>,
}

/// Help text for `stuntreel parity`, also listed under the main `--help`.
pub(crate) fn usage() -> String {
    Args::command().render_help().to_string()
}

fn parse_min_fade_level(text: &str) -> Result<f32, String> {
    let level = text.parse::<f32>().map_err(|e| e.to_string())?;
    if !level.is_finite() || level < 0.0 {
        return Err("expected a finite number >= 0".to_string());
    }
    Ok(level)
}

impl Args {
    /// Parses `args` (without `stuntreel parity`).
    pub(super) fn try_parse_args(
        args: impl IntoIterator<Item = String>,
    ) -> Result<Self, clap::Error> {
        Self::try_parse_from(std::iter::once("stuntreel parity".to_string()).chain(args))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::path::Path;

    fn parse(extra: &[&str]) -> Result<Args, String> {
        let base = ["--reference", "r", "--test", "t", "--output", "o"];
        Args::try_parse_args(base.iter().chain(extra).map(|s| (*s).to_string()))
            .map_err(|e| e.to_string())
    }

    #[test]
    fn min_fade_level_flag_parses_defaults_and_rejects_bad_values() {
        assert_eq!(parse(&[]).unwrap().min_fade_level, 0.25);
        assert_eq!(
            parse(&["--min-fade-level", "0.5"]).unwrap().min_fade_level,
            0.5
        );
        assert_eq!(
            parse(&["--min-fade-level", "0"]).unwrap().min_fade_level,
            0.0
        );
        for bad in ["-0.1", "NaN", "inf", "abc"] {
            let error = parse(&["--min-fade-level", bad]).unwrap_err();
            assert!(error.contains("--min-fade-level"), "{bad}: {error}");
        }
        assert!(parse(&["--min-fade-level"]).is_err());
    }

    #[test]
    fn the_retired_clear_index_flag_is_rejected() {
        let error = parse(&["--clear-index", "233"]).unwrap_err();
        assert!(error.contains("--clear-index"), "{error}");
    }

    #[test]
    fn compare_flags_parse_and_compare_test_needs_compare() {
        let args = parse(&["--compare", "p/report.json", "--compare-test", "p/ours"]).unwrap();
        assert_eq!(args.compare.as_deref(), Some(Path::new("p/report.json")));
        assert_eq!(args.compare_test.as_deref(), Some(Path::new("p/ours")));
        assert!(parse(&[]).unwrap().compare.is_none());
        assert!(
            parse(&["--compare-test", "p"])
                .unwrap_err()
                .contains("--compare")
        );
    }

    #[test]
    fn usage_names_the_subcommand_and_its_flags() {
        let text = usage();
        assert!(text.contains("stuntreel parity"), "{text}");
        assert!(
            text.contains("--min-fade-level") && text.contains("--compare-test"),
            "{text}"
        );
    }
}
