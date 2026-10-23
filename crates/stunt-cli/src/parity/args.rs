//! `stuntreel parity` command-line arguments.

use std::path::PathBuf;

/// Parsed `stuntreel parity` arguments.
#[derive(Debug)]
pub(super) struct Args {
    pub(super) reference: PathBuf,
    pub(super) test: PathBuf,
    pub(super) output: PathBuf,
    pub(super) clear_index: u8,
    /// Frames fading below this level are reported but excluded from the scored means.
    pub(super) min_fade_level: f32,
    /// Previous `report.json` to compare the fresh scores against.
    pub(super) compare: Option<PathBuf>,
    /// Render directory of the previous run, used for before/after contact sheets.
    pub(super) compare_test: Option<PathBuf>,
}

/// Usage text printed by `--help`.
pub(crate) const USAGE: &str =
    "Usage: stuntreel parity --reference <dir> --test <dir> --output <dir> \
[--clear-index N] [--min-fade-level F] [--compare <report.json> [--compare-test <dir>]]

  --min-fade-level F       Frames whose measured palette fade level is below F (default
                           0.25) are reported but left out of the scored means
  --compare <report.json>  Match frames by film_tick against a previous report and print
                           mean SSIM/IoU deltas, the 5 most improved/regressed frames and
                           the counts changed by more than 0.005; writes compare.json
  --compare-test <dir>     The previous run's render directory; with --compare, writes
                           before/after contact sheets for the most regressed and most
                           improved frame (skipped, with a note, when absent)";

impl Args {
    pub(super) fn parse(mut args: impl Iterator<Item = String>) -> Result<Self, String> {
        let mut reference = None;
        let mut test = None;
        let mut output = None;
        let mut clear_index = 180u8;
        let mut min_fade_level = 0.25f32;
        let mut compare = None;
        let mut compare_test = None;

        while let Some(arg) = args.next() {
            match arg.as_str() {
                "--reference" => {
                    reference = Some(PathBuf::from(
                        args.next().ok_or("Expected directory after --reference")?,
                    ));
                }
                "--test" => {
                    test = Some(PathBuf::from(
                        args.next().ok_or("Expected directory after --test")?,
                    ));
                }
                "--output" => {
                    output = Some(PathBuf::from(
                        args.next().ok_or("Expected directory after --output")?,
                    ));
                }
                "--clear-index" => {
                    let value = args.next().ok_or("Expected number after --clear-index")?;
                    clear_index = value
                        .parse::<u8>()
                        .map_err(|e| format!("Invalid clear index: {e}"))?;
                }
                "--min-fade-level" => {
                    let value = args
                        .next()
                        .ok_or("Expected number after --min-fade-level")?;
                    min_fade_level = value
                        .parse::<f32>()
                        .map_err(|e| format!("Invalid min fade level: {e}"))?;
                    if !min_fade_level.is_finite() || min_fade_level < 0.0 {
                        return Err(format!(
                            "Invalid min fade level: {value} (expected a finite number >= 0)"
                        ));
                    }
                }
                "--compare" => {
                    compare = Some(PathBuf::from(
                        args.next().ok_or("Expected report.json after --compare")?,
                    ));
                }
                "--compare-test" => {
                    compare_test = Some(PathBuf::from(
                        args.next()
                            .ok_or("Expected directory after --compare-test")?,
                    ));
                }
                "--help" | "-h" => {
                    println!("{USAGE}");
                    std::process::exit(0);
                }
                other => return Err(format!("Unrecognized parity argument: {other}")),
            }
        }

        if compare_test.is_some() && compare.is_none() {
            return Err("--compare-test requires --compare <report.json>".to_string());
        }

        Ok(Self {
            reference: reference.ok_or("parity requires --reference <dir>")?,
            test: test.ok_or("parity requires --test <dir>")?,
            output: output.ok_or("parity requires --output <dir>")?,
            clear_index,
            min_fade_level,
            compare,
            compare_test,
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::path::Path;

    #[test]
    fn min_fade_level_flag_parses_defaults_and_rejects_bad_values() {
        let parse = |extra: &[&str]| {
            let mut v: Vec<String> = ["--reference", "r", "--test", "t", "--output", "o"]
                .iter()
                .map(|s| (*s).to_string())
                .collect();
            v.extend(extra.iter().map(|s| (*s).to_string()));
            Args::parse(v.into_iter())
        };
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
            assert!(error.contains("min fade level"), "{bad}: {error}");
        }
        assert!(parse(&["--min-fade-level"]).is_err());
    }

    #[test]
    fn compare_flags_parse_and_compare_test_needs_compare() {
        let parse = |extra: &[&str]| {
            let mut v: Vec<String> = ["--reference", "r", "--test", "t", "--output", "o"]
                .iter()
                .map(|s| (*s).to_string())
                .collect();
            v.extend(extra.iter().map(|s| (*s).to_string()));
            Args::parse(v.into_iter())
        };
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
}
