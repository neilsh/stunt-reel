//! `--compare`: previous-run comparison, `compare.json` and before/after sheets.

use std::collections::BTreeMap;
use std::fs;
use std::path::Path;

use super::args::Args;
use super::frames::{load_reference, load_render_frame, load_render_rescaled, reference_luminance};
use super::report::Report;
use super::report_diff::compare_reports;
use super::score::{ReferenceFrame, RenderFrame};
use super::sheets::{abs_difference, write_panel_sheet};
use super::verdict::{FrameVerdict, Verdict, frame_verdict};
use stunt_parity::CapturedFrame;

use crate::parity_artifacts;

/// Compares the fresh `report` with the previous report at `previous_path`: prints the
/// summary, writes `compare.json`, and renders before/after sheets when the previous
/// render directory was given.
pub(super) fn run_compare(
    args: &Args,
    previous_path: &Path,
    report: &Report,
    frames: &[CapturedFrame],
) -> Result<(), String> {
    let previous =
        parity_artifacts::read_report(previous_path).map_err(|error| error.to_string())?;
    let comparison = compare_reports(&previous, report)
        .map_err(|e| format!("compare with {}: {e}", previous_path.display()))?;

    let verdict = match args.compare_test.as_deref() {
        Some(previous_render) => judge(args, previous_render, report, frames)?,
        None => None,
    };

    let mut document = comparison.to_json();
    if let (Some(verdict), Some(object)) = (&verdict, document.as_object_mut()) {
        object.insert("verdict".to_string(), verdict.to_json());
    }
    let compare_path = args.output.join("compare.json");
    fs::write(
        &compare_path,
        serde_json::to_string_pretty(&document)
            .map_err(|e| format!("serialize comparison: {e}"))?,
    )
    .map_err(|e| format!("write {}: {e}", compare_path.display()))?;
    println!("{}", comparison.summary());
    match (&verdict, args.compare_test.as_deref()) {
        (Some(verdict), _) => println!("{}", verdict.summary()),
        (None, Some(previous_render)) => println!("{}", skipped_note(previous_render)),
        (None, None) => {}
    }

    let Some(previous_render) = &args.compare_test else {
        println!("[compare] no --compare-test <dir>: before/after contact sheets skipped");
        return Ok(());
    };
    let ordinals: BTreeMap<u64, usize> = report
        .per_frame
        .iter()
        .map(|f| (f.film_tick, f.ordinal))
        .collect();
    // The sheets show the frames that moved most: by the windows the change touched when the
    // verdict ran, else by the frame SSIM.
    let picks = match &verdict {
        Some(verdict) => {
            let (worst, best) = verdict.worst_and_best();
            [("regressed", worst), ("improved", best)]
        }
        None => [
            (
                "regressed",
                comparison.regressed.first().map(|d| d.film_tick),
            ),
            ("improved", comparison.improved.first().map(|d| d.film_tick)),
        ],
    };
    for (label, pick) in picks {
        let Some(film_tick) = pick else {
            println!("[compare] no {label} frame: sheet skipped");
            continue;
        };
        let ordinal = ordinals
            .get(&film_tick)
            .copied()
            .ok_or_else(|| format!("film_tick {film_tick} missing from the fresh report"))?;
        let tick = usize::try_from(film_tick).map_err(|e| e.to_string())?;
        let before_png = previous_render.join(crate::headless::tick_png_name(tick));
        if !before_png.is_file() {
            println!(
                "[compare] {} not found: {label} sheet skipped",
                before_png.display()
            );
            continue;
        }
        let frame = frames
            .get(ordinal - 1)
            .ok_or_else(|| format!("frame {ordinal} missing from the capture"))?;
        let reference_file = args.reference.join(&frame.frame_file);
        let palette_file = args.reference.join(&frame.palette_file);
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

/// The note printed in place of the verdict summary when the previous render has no planes.
fn skipped_note(previous_render: &Path) -> String {
    format!(
        "[verdict] skipped: {} has no index planes; re-render it to judge changes",
        previous_render.display()
    )
}

/// Judges every fresh frame against the previous render of the same tick; `None` when the
/// previous render predates the index and layer planes, which the verdict cannot do without.
fn judge(
    args: &Args,
    previous_render: &Path,
    report: &Report,
    frames: &[CapturedFrame],
) -> Result<Option<Verdict>, String> {
    let lacks_planes = report.per_frame.iter().any(|entry| {
        usize::try_from(entry.film_tick).is_ok_and(|tick| {
            let png = previous_render.join(crate::headless::tick_png_name(tick));
            let (idx, layer) = crate::plane_codec::plane_paths(&png);
            png.is_file() && !(idx.is_file() && layer.is_file())
        })
    });
    if lacks_planes {
        return Ok(None);
    }
    let mut judged = Vec::with_capacity(report.per_frame.len());
    for entry in &report.per_frame {
        let tick = usize::try_from(entry.film_tick).map_err(|e| e.to_string())?;
        let before_png = previous_render.join(crate::headless::tick_png_name(tick));
        if !before_png.is_file() {
            judged.push(FrameVerdict::missing(entry.film_tick));
            continue;
        }
        let frame = frames
            .get(entry.ordinal - 1)
            .ok_or_else(|| format!("frame {} missing from the capture", entry.ordinal))?;
        let (indices, palette) = load_reference(
            &args.reference.join(&frame.frame_file),
            &args.reference.join(&frame.palette_file),
        )?;
        let before: RenderFrame = load_render_frame(previous_render, tick)?;
        let after: RenderFrame = load_render_frame(&args.test, tick)?;
        judged.push(frame_verdict(
            entry.film_tick,
            &ReferenceFrame { indices, palette },
            &before,
            &after,
            args.noise_sigma,
            args.build_floor,
        ));
    }
    Ok(Some(Verdict {
        frames: judged,
        has_sigma: args.noise_sigma.is_some(),
    }))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::parity::run;
    use crate::parity::sheets::CONTACT_SHEET_GAP;
    use crate::parity::test_support::{
        TempDir, run_parity, write_matching_render, write_reference, write_render,
    };
    use serde_json::Value;
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
        assert_eq!(doc["verdict"]["counts"]["closer"], 1);
        assert_eq!(doc["verdict"]["counts"]["unchanged"], 1);
        let sheet = image::open(tmp.join("out").join("compare_improved_tick_00012.png")).unwrap();
        assert_eq!(
            sheet.width() as usize,
            (MODE13H_WIDTH + CONTACT_SHEET_GAP) * 5 - CONTACT_SHEET_GAP
        );
    }

    #[test]
    fn a_before_tree_without_planes_skips_the_verdict_and_keeps_the_comparison() {
        let tmp = TempDir::new("verdict_no_planes");
        write_reference(&tmp.join("ref"), &[7, 12], true);
        let previous = tmp.join("prev");
        let current = tmp.join("cur");
        fs::create_dir_all(&previous).unwrap();
        fs::create_dir_all(&current).unwrap();
        for tick in [7, 12] {
            write_render(&previous.join(crate::headless::tick_png_name(tick)));
            write_render(&current.join(crate::headless::tick_png_name(tick)));
        }
        write_matching_render(&current.join(crate::headless::tick_png_name(12)));
        run_parity(&tmp.join("ref"), &previous, &tmp.join("base")).expect("baseline");
        // An old render: the PNGs stay, the planes go.
        for tick in [7, 12] {
            let png = previous.join(crate::headless::tick_png_name(tick));
            let (idx, layer) = crate::plane_codec::plane_paths(&png);
            fs::remove_file(idx).unwrap();
            fs::remove_file(layer).unwrap();
        }
        let argv = [
            "--reference",
            &tmp.join("ref").display().to_string(),
            "--test",
            &current.display().to_string(),
            "--output",
            &tmp.join("out").display().to_string(),
            "--compare",
            &tmp.join("base").join("report.json").display().to_string(),
            "--compare-test",
            &previous.display().to_string(),
        ]
        .map(String::from);
        run(argv.into_iter()).expect("a before tree without planes is not an error");

        let doc: Value = serde_json::from_str(
            &fs::read_to_string(tmp.join("out").join("compare.json")).unwrap(),
        )
        .unwrap();
        assert_eq!(doc["common_frames"], 2);
        assert_eq!(doc["most_improved"][0]["film_tick"], 12);
        assert!(doc.get("verdict").is_none());
        assert!(
            tmp.join("out")
                .join("compare_improved_tick_00012.png")
                .is_file()
        );
        assert_eq!(
            skipped_note(&previous),
            format!(
                "[verdict] skipped: {} has no index planes; re-render it to judge changes",
                previous.display()
            )
        );
    }

    #[test]
    fn a_missing_before_tick_is_counted_not_fatal() {
        let tmp = TempDir::new("verdict_missing");
        write_reference(&tmp.join("ref"), &[7, 12], true);
        let previous = tmp.join("prev");
        let current = tmp.join("cur");
        fs::create_dir_all(&previous).unwrap();
        fs::create_dir_all(&current).unwrap();
        for tick in [7, 12] {
            write_render(&current.join(crate::headless::tick_png_name(tick)));
        }
        write_render(&previous.join(crate::headless::tick_png_name(7)));
        run_parity(&tmp.join("ref"), &current, &tmp.join("base")).expect("baseline");
        let argv = [
            "--reference",
            &tmp.join("ref").display().to_string(),
            "--test",
            &current.display().to_string(),
            "--output",
            &tmp.join("out").display().to_string(),
            "--compare",
            &tmp.join("base").join("report.json").display().to_string(),
            "--compare-test",
            &previous.display().to_string(),
        ]
        .map(String::from);
        run(argv.into_iter()).expect("a missing before tick is not an error");
        let doc: Value = serde_json::from_str(
            &fs::read_to_string(tmp.join("out").join("compare.json")).unwrap(),
        )
        .unwrap();
        assert_eq!(doc["verdict"]["counts"]["missing"], 1);
        assert_eq!(doc["verdict"]["counts"]["unchanged"], 1);
    }
}
