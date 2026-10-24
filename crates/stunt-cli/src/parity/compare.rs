//! `--compare`: previous-run comparison, `compare.json` and before/after sheets.

use std::collections::BTreeMap;
use std::fs;
use std::path::Path;

use serde_json::Value;

use super::args::Args;
use super::frames::{load_reference, load_render_rescaled, reference_luminance, reference_paths};
use super::report::Report;
use super::report_diff::compare_reports;
use super::sheets::{abs_difference, write_panel_sheet};

/// Compares the fresh `report` with the previous report at `previous_path`: prints the
/// summary, writes `compare.json`, and renders before/after sheets when the previous
/// render directory was given.
pub(super) fn run_compare(
    args: &Args,
    previous_path: &Path,
    report: &Report,
    frames: &[Value],
) -> Result<(), String> {
    let text = fs::read_to_string(previous_path)
        .map_err(|e| format!("read {}: {e}", previous_path.display()))?;
    let previous: Report = serde_json::from_str(&text)
        .map_err(|e| format!("parse {}: {e}", previous_path.display()))?;
    let comparison = compare_reports(&previous, report)
        .map_err(|e| format!("compare with {}: {e}", previous_path.display()))?;

    let compare_path = args.output.join("compare.json");
    fs::write(
        &compare_path,
        serde_json::to_string_pretty(&comparison.to_json())
            .map_err(|e| format!("serialize comparison: {e}"))?,
    )
    .map_err(|e| format!("write {}: {e}", compare_path.display()))?;
    println!("{}", comparison.summary());

    let Some(previous_render) = &args.compare_test else {
        println!("[compare] no --compare-test <dir>: before/after contact sheets skipped");
        return Ok(());
    };
    let ordinals: BTreeMap<u64, usize> = report
        .per_frame
        .iter()
        .map(|f| (f.film_tick, f.ordinal))
        .collect();
    let picks = [
        ("regressed", comparison.regressed.first()),
        ("improved", comparison.improved.first()),
    ];
    for (label, pick) in picks {
        let Some(delta) = pick else {
            println!("[compare] no {label} frame: sheet skipped");
            continue;
        };
        let ordinal = ordinals.get(&delta.film_tick).copied().ok_or_else(|| {
            format!(
                "film_tick {} missing from the fresh report",
                delta.film_tick
            )
        })?;
        let tick = usize::try_from(delta.film_tick).map_err(|e| e.to_string())?;
        let before_png = previous_render.join(crate::headless::tick_png_name(tick));
        if !before_png.is_file() {
            println!(
                "[compare] {} not found: {label} sheet skipped",
                before_png.display()
            );
            continue;
        }
        let (reference_file, palette_file) =
            reference_paths(&args.reference, &frames[ordinal - 1], ordinal);
        let (indices, palette) = load_reference(&reference_file, &palette_file)?;
        let reference = reference_luminance(&indices, &palette);
        let before = load_render_rescaled(&before_png)?;
        let after = load_render_rescaled(&args.test.join(crate::headless::tick_png_name(tick)))?;
        let path = args
            .output
            .join(format!("compare_{label}_tick_{tick:05}.png"));
        write_panel_sheet(
            &path,
            &[
                &reference,
                &before,
                &after,
                &abs_difference(&reference, &before),
                &abs_difference(&reference, &after),
            ],
        )?;
        println!("[compare] wrote {}", path.display());
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::parity::run;
    use crate::parity::sheets::CONTACT_SHEET_GAP;
    use crate::parity::test_support::{
        TempDir, run_parity, write_matching_render, write_reference, write_render,
    };
    use stunt_render::MODE13H_WIDTH;

    #[test]
    fn compare_run_writes_compare_json_and_before_after_sheets() {
        let tmp = TempDir::new("compare_run");
        write_reference(&tmp.join("ref"), &[7, 12], true);
        let previous = tmp.join("prev");
        let current = tmp.join("cur");
        fs::create_dir_all(&previous).unwrap();
        fs::create_dir_all(&current).unwrap();
        for tick in [7, 12] {
            write_render(&previous.join(crate::headless::tick_png_name(tick)));
            write_render(&current.join(crate::headless::tick_png_name(tick)));
        }
        // Make the fresh render of tick 12 match the capture, which scores higher.
        write_matching_render(&current.join(crate::headless::tick_png_name(12)));

        run_parity(&tmp.join("ref"), &previous, &tmp.join("base")).expect("baseline");
        let argv = |compare_test: bool| {
            let mut v = vec![
                "--reference".to_string(),
                tmp.join("ref").display().to_string(),
                "--test".to_string(),
                current.display().to_string(),
                "--output".to_string(),
                tmp.join("out").display().to_string(),
                "--compare".to_string(),
                tmp.join("base").join("report.json").display().to_string(),
            ];
            if compare_test {
                v.push("--compare-test".to_string());
                v.push(previous.display().to_string());
            }
            v
        };

        run(argv(false).into_iter()).expect("compare without sheets");
        assert!(tmp.join("out").join("compare.json").is_file());
        assert!(
            !tmp.join("out")
                .join("compare_improved_tick_00012.png")
                .exists()
        );

        run(argv(true).into_iter()).expect("compare with sheets");
        let doc: Value = serde_json::from_str(
            &fs::read_to_string(tmp.join("out").join("compare.json")).unwrap(),
        )
        .unwrap();
        assert_eq!(doc["common_frames"], 2);
        assert_eq!(doc["most_improved"][0]["film_tick"], 12);
        let sheet = image::open(tmp.join("out").join("compare_improved_tick_00012.png")).unwrap();
        assert_eq!(
            sheet.width() as usize,
            (MODE13H_WIDTH + CONTACT_SHEET_GAP) * 5 - CONTACT_SHEET_GAP
        );
    }
}
