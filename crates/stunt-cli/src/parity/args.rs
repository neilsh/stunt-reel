//! `stuntreel parity` command-line arguments.

use std::path::PathBuf;

use clap::{CommandFactory as _, Parser};

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
        value_parser = parse_non_negative,
        allow_negative_numbers = true
    )]
    pub(super) min_fade_level: f32,
    /// Score a render that read another archive than the capture played (a deliberate
    /// stand-in, such as a superset archive), marking the report; any other film conflict
    /// still refuses
    #[arg(long)]
    pub(super) waive_archive_conflict: bool,
    /// The `crates/` git tree the render was built from, written to the report as `crates`;
    /// leave it out when that tree is unknown or had uncommitted changes
    #[arg(long, value_name = "TREE")]
    pub(super) crates: Option<String>,
    /// The reference capture's content hash the score is made against, written to the report as
    /// `sha256`; leave it out when it is unknown
    #[arg(long, value_name = "SHA256")]
    pub(super) sha256: Option<String>,
    /// The reference film's archive pin, written to the report as `all_sha256`; leave it out
    /// when the row pins no archive
    #[arg(long, value_name = "SHA256")]
    pub(super) all_sha256: Option<String>,
    /// Match frames by `film_tick` against a previous report and print mean SSIM/IoU deltas,
    /// the 5 most improved/regressed frames and the counts changed by more than 0.005;
    /// writes compare.json
    #[arg(long, value_name = "REPORT.JSON")]
    pub(super) compare: Option<PathBuf>,
    /// The previous run's render directory; with --compare, writes before/after contact
    /// sheets for the most regressed and most improved frame (skipped, with a note, when
    /// absent)
    #[arg(long, value_name = "DIR", requires = "compare")]
    pub(super) compare_test: Option<PathBuf>,
    /// Recapture noise of the whole-frame SSIM (the film's `noise_sigma` in references.toml, when its row has one),
    /// a lower bound for the noise of Δ on a few touched windows; a frame whose |Δ| is below
    /// it is "within noise". Without it the verdict goes by the sign of Δ alone
    #[arg(long, value_name = "F", requires = "compare_test", value_parser = parse_non_negative)]
    pub(super) noise_sigma: Option<f32>,
    /// Frames with at most N changed pixels are build noise, not judged
    #[arg(long, value_name = "N", default_value_t = 0, requires = "compare_test")]
    pub(super) build_floor: usize,
}

/// Help text for `stuntreel parity`, also listed under the main `--help`.
pub(crate) fn usage() -> String {
    Args::command().render_help().to_string()
}

fn parse_non_negative(text: &str) -> Result<f32, String> {
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
        parse(&["--min-fade-level"]).unwrap_err();
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
    fn noise_sigma_requires_compare_test() {
        let args = parse(&[
            "--compare",
            "p/report.json",
            "--compare-test",
            "p/ours",
            "--noise-sigma",
            "0.002",
            "--build-floor",
            "30",
        ])
        .unwrap();
        assert_eq!(args.noise_sigma, Some(0.002));
        assert_eq!(args.build_floor, 30);
        let defaults = parse(&["--compare", "p/report.json", "--compare-test", "p"]).unwrap();
        assert_eq!((defaults.noise_sigma, defaults.build_floor), (None, 0));
        for flag in [["--noise-sigma", "0.1"], ["--build-floor", "3"]] {
            let error = parse(&["--compare", "p/report.json", flag[0], flag[1]]).unwrap_err();
            assert!(error.contains("--compare-test"), "{flag:?}: {error}");
        }
    }

    #[test]
    fn reference_pin_flags_parse_and_default_to_none() {
        let args = parse(&["--sha256", "aa", "--all-sha256", "bb"]).unwrap();
        assert_eq!(args.sha256.as_deref(), Some("aa"));
        assert_eq!(args.all_sha256.as_deref(), Some("bb"));
        let defaults = parse(&[]).unwrap();
        assert!(defaults.sha256.is_none() && defaults.all_sha256.is_none());
    }

    #[test]
    fn usage_names_the_subcommand_and_its_flags() {
        let text = usage();
        assert!(text.contains("stuntreel parity"), "{text}");
        assert!(
            text.contains("--min-fade-level") && text.contains("--compare-test"),
            "{text}"
        );
        assert!(
            text.contains("--sha256") && text.contains("--all-sha256"),
            "{text}"
        );
    }
}
