//! `--compare`: previous-run comparison, `compare.json` and before/after sheets.

use super::ParityError;
use std::collections::BTreeMap;
use std::fs;
use std::path::Path;

use super::frames::{load_render_frame, reference_luminance};
use super::matched::{ReportFrames, load_captured};
use super::options::Options;
use super::report::Report;
use super::report_diff::compare_reports;
use super::score::RenderFrame;
use super::sheets::{grey_panel, index_map_panel, overlay_panel, sheet_mask, write_panel_sheet};
use super::ssim::rescale_mode13h_frame;
use super::verdict::{FrameVerdict, Verdict, frame_verdict};

use stunt_core::frame::{ASPECT_CORRECTED_HEIGHT, MODE13H_HEIGHT, MODE13H_WIDTH};

use crate::parity_artifacts;
use crate::render_store::RenderStore;

/// Compares the fresh `report` with the previous report at `previous_path`: prints the
/// summary, writes `compare.json`, and renders before/after sheets when the previous
/// render directory was given.
#[expect(
    clippy::print_stdout,
    reason = "`run_compare` reports to the terminal of `stuntreel parity --compare`"
)]
pub(super) fn run_compare(
    args: &Options,
    previous_path: &Path,
    report: &Report,
    frames: &ReportFrames<'_>,
) -> Result<(), ParityError> {
    let previous = parity_artifacts::read_report(previous_path)?;
    let comparison = compare_reports(&previous, report).map_err(|e| {
        ParityError::Input(format!("compare with {}: {e}", previous_path.display()))
    })?;

    let verdict = match args.compare_test.as_deref() {
        Some(previous_render) => judge(args, previous_render, report, frames)?,
        None => None,
    };

    let document = comparison.document(verdict.as_ref());
    // Written through a `Value`, as the document always was: serialising the `f32` fields
    // directly would print their shortest `f32` form, not the `f64` digits `compare.json` holds.
    let value = serde_json::to_value(&document).map_err(|source| ParityError::Serialize {
        what: "comparison",
        source,
    })?;
    let text = serde_json::to_string_pretty(&value).map_err(|source| ParityError::Serialize {
        what: "comparison",
        source,
    })?;
    let compare_path = args.output.join("compare.json");
    fs::write(&compare_path, text).map_err(ParityError::io("write", &compare_path))?;
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
    let mut before_store = match RenderStore::open(previous_render) {
        Ok(store) => store,
        Err(error) => {
            println!("[compare] {error}: before/after contact sheets skipped");
            return Ok(());
        }
    };
    let mut after_store = RenderStore::open(&args.test)?;
    let rows: BTreeMap<u64, _> = report
        .per_frame
        .iter()
        .map(|row| (row.film_tick, row))
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
        let row = rows.get(&film_tick).ok_or_else(|| {
            ParityError::Input(format!(
                "film_tick {film_tick} missing from the fresh report"
            ))
        })?;
        let captured_frame = frames.frame(row)?;
        let tick = captured_frame.render_tick();
        if !before_store.holds(tick) {
            println!(
                "[compare] {} holds no tick {tick}: {label} sheet skipped",
                previous_render.display()
            );
            continue;
        }
        let captured = load_captured(&args.reference, captured_frame)?;
        let reference = reference_luminance(&captured.indices, &captured.palette);
        let before_frame = load_render_frame(&mut before_store, tick)?;
        let after_frame = load_render_frame(&mut after_store, tick)?;
        let rescale = |luminance: &[f32]| {
            rescale_mode13h_frame(
                luminance,
                MODE13H_WIDTH,
                MODE13H_HEIGHT,
                ASPECT_CORRECTED_HEIGHT,
            )
        };
        let before = rescale(&before_frame.luminance);
        let after = rescale(&after_frame.luminance);
        // Each render's panels are masked by its own credits flag, as it was scored.
        let before_mask = sheet_mask(&captured.indices, before_frame.credits);
        let after_mask = sheet_mask(&captured.indices, after_frame.credits);
        let index_map = |frame: &RenderFrame, mask: &[bool]| {
            index_map_panel(
                &reference,
                &captured.indices,
                &frame.indices,
                &frame.layers,
                mask,
            )
        };
        let path = args
            .output
            .join(format!("compare_{label}_tick_{film_tick:05}.png"));
        write_panel_sheet(
            &path,
            &[
                &grey_panel(&reference),
                &grey_panel(&before),
                &grey_panel(&after),
                &overlay_panel(&reference, &before, &before_mask),
                &overlay_panel(&reference, &after, &after_mask),
                &index_map(&before_frame, &before_mask),
                &index_map(&after_frame, &after_mask),
            ],
        )?;
        println!("[compare] wrote {}", path.display());
    }
    Ok(())
}

/// The note printed in place of the verdict summary when the previous render cannot be read.
fn skipped_note(previous_render: &Path) -> String {
    format!(
        "[verdict] skipped: {} is not a readable render store; re-render it to judge changes",
        previous_render.display()
    )
}

/// Judges every fresh frame against the previous render of the same tick; `None` when the
/// previous render is not a readable store (one made before it, for instance), which the
/// verdict cannot do without.
fn judge(
    args: &Options,
    previous_render: &Path,
    report: &Report,
    frames: &ReportFrames<'_>,
) -> Result<Option<Verdict>, ParityError> {
    let Ok(mut before_store) = RenderStore::open(previous_render) else {
        return Ok(None);
    };
    let mut after_store = RenderStore::open(&args.test)?;
    let mut judged = Vec::with_capacity(report.per_frame.len());
    for entry in &report.per_frame {
        let captured_frame = frames.frame(entry)?;
        let tick = captured_frame.render_tick();
        if !before_store.holds(tick) {
            judged.push(FrameVerdict::missing(entry.film_tick));
            continue;
        }
        let captured = load_captured(&args.reference, captured_frame)?;
        let before: RenderFrame = load_render_frame(&mut before_store, tick)?;
        let after: RenderFrame = load_render_frame(&mut after_store, tick)?;
        judged.push(frame_verdict(
            entry.film_tick,
            &captured,
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
        Picture, TempDir, run_parity, write_reference, write_render, write_render_store,
        write_version_1_render,
    };
    use serde_json::Value;

    #[test]
    fn compare_run_writes_compare_json_and_before_after_sheets() {
        let tmp = TempDir::new("compare_run");
        write_reference(&tmp.join("ref"), &[7, 12], true);
        let previous = tmp.join("prev");
        let current = tmp.join("cur");
        write_render(&previous, &[7, 12]);
        // The fresh render of tick 12 matches the capture, which scores higher.
        write_render_store(
            &current,
            &[(7, 0x8000, Picture::Grey), (12, 0x8000, Picture::Matching)],
        );

        run_parity(&tmp.join("ref"), &previous, &tmp.join("base")).expect("baseline");
        let options = |compare_test: bool| Options {
            compare: Some(tmp.join("base").join("report.json")),
            compare_test: compare_test.then(|| previous.clone()),
            ..Options::new(tmp.join("ref"), current.clone(), tmp.join("out"))
        };

        run(&options(false)).expect("compare without sheets");
        assert!(tmp.join("out").join("compare.json").is_file());
        assert!(
            !tmp.join("out")
                .join("compare_improved_tick_00012.png")
                .exists()
        );

        run(&options(true)).expect("compare with sheets");
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
            (MODE13H_WIDTH + CONTACT_SHEET_GAP) * 7 - CONTACT_SHEET_GAP
        );
        assert_eq!(sheet.height() as usize, ASPECT_CORRECTED_HEIGHT);
        assert_eq!(sheet.color(), image::ColorType::Rgb8);
    }

    /// Runs the compare on synthetic renders and returns `compare.json` as written. `previous`
    /// is the earlier render; the fresh one always holds ticks 7 and 12.
    fn compare_json_of(tmp: &TempDir, name: &str, previous: &Path) -> String {
        let base = tmp.join(&format!("base_{name}"));
        run_parity(&tmp.join("ref"), previous, &base).expect("baseline");
        let out = tmp.join(&format!("out_{name}"));
        run(&Options {
            compare: Some(base.join("report.json")),
            compare_test: Some(previous.to_path_buf()),
            ..Options::new(tmp.join("ref"), tmp.join("cur"), out.clone())
        })
        .expect("compare");
        fs::read_to_string(out.join("compare.json")).unwrap()
    }

    /// `compare.json` is pinned byte for byte, so the typed writer must reproduce the
    /// document it replaced. The `partial` run holds no tick 12 in the previous render, so
    /// its `before_after_ssim` is `null`.
    #[test]
    fn compare_json_matches_the_pinned_documents() {
        let tmp = TempDir::new("compare_json_pin");
        write_reference(&tmp.join("ref"), &[7, 12], true);
        write_render_store(
            &tmp.join("cur"),
            &[(7, 0x8000, Picture::Grey), (12, 0x8000, Picture::Matching)],
        );
        let full = tmp.join("prev_full");
        write_render(&full, &[7, 12]);
        let partial = tmp.join("prev_partial");
        write_render(&partial, &[7]);

        let full_json = compare_json_of(&tmp, "full", &full);
        let partial_json = compare_json_of(&tmp, "partial", &partial);
        assert_eq!(
            format!("{full_json}\n"),
            include_str!("golden/compare_full.json")
        );
        assert_eq!(
            format!("{partial_json}\n"),
            include_str!("golden/compare_partial.json")
        );
    }

    #[test]
    fn a_before_render_from_before_the_store_skips_the_verdict_and_sheets_only() {
        let tmp = TempDir::new("verdict_no_planes");
        write_reference(&tmp.join("ref"), &[7, 12], true);
        let previous = tmp.join("prev");
        let current = tmp.join("cur");
        write_render(&previous, &[7, 12]);
        write_render_store(
            &current,
            &[(7, 0x8000, Picture::Grey), (12, 0x8000, Picture::Matching)],
        );
        run_parity(&tmp.join("ref"), &previous, &tmp.join("base")).expect("baseline");
        // A render made before the store: its record is version 1 and its planes are gone.
        write_version_1_render(&previous);
        let options = Options {
            compare: Some(tmp.join("base").join("report.json")),
            compare_test: Some(previous.clone()),
            ..Options::new(tmp.join("ref"), current, tmp.join("out"))
        };
        run(&options).expect("an unreadable before render is not an error");

        let doc: Value = serde_json::from_str(
            &fs::read_to_string(tmp.join("out").join("compare.json")).unwrap(),
        )
        .unwrap();
        assert_eq!(doc["common_frames"], 2);
        assert_eq!(doc["most_improved"][0]["film_tick"], 12);
        assert!(doc.get("verdict").is_none());
        assert!(
            !tmp.join("out")
                .join("compare_improved_tick_00012.png")
                .exists()
        );
        assert_eq!(
            skipped_note(&previous),
            format!(
                "[verdict] skipped: {} is not a readable render store; re-render it to judge \
                 changes",
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
        write_render(&current, &[7, 12]);
        write_render(&previous, &[7]);
        run_parity(&tmp.join("ref"), &current, &tmp.join("base")).expect("baseline");
        let options = Options {
            compare: Some(tmp.join("base").join("report.json")),
            compare_test: Some(previous),
            ..Options::new(tmp.join("ref"), current, tmp.join("out"))
        };
        run(&options).expect("a missing before tick is not an error");
        let doc: Value = serde_json::from_str(
            &fs::read_to_string(tmp.join("out").join("compare.json")).unwrap(),
        )
        .unwrap();
        assert_eq!(doc["verdict"]["counts"]["missing"], 1);
        assert_eq!(doc["verdict"]["counts"]["unchanged"], 1);
    }
}
