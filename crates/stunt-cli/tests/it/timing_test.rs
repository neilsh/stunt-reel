//! `stuntreel --report-timing` prints the phase times to stderr and changes no byte of the
//! render store.
//!
//! The film is `synthetic_timeline.flm` on the software adapter; without one offering clip
//! distances it skips, even under `STUNT_REQUIRE_GPU=1` (ADR 0054), and any other failure
//! fails.

use std::fs;
use std::path::Path;
use std::process::{Command, Output};

use super::workers_test::{skips_without_software_adapter, stuntreel, tree, workspace_root};

fn render(film: &Path, out: &Path, flags: &[&str]) -> Output {
    Command::new(stuntreel())
        .arg("--headless")
        .arg(film)
        .arg("--out-dir")
        .arg(out)
        .args(["--software-only", "--width", "64", "--height", "48"])
        .args(flags)
        .output()
        .expect("run stuntreel")
}

/// The phase names and times of the `[stuntreel] timing <phase> <ms> ms` lines of `stderr`.
fn timing_lines(stderr: &str) -> Vec<(String, f64)> {
    stderr
        .lines()
        .filter_map(|line| line.strip_prefix("[stuntreel] timing "))
        .map(|rest| {
            let words: Vec<&str> = rest.split_whitespace().collect();
            let [phase, ms, "ms"] = words[..] else {
                panic!("not `<phase> <ms> ms`: {rest:?}");
            };
            (phase.to_string(), ms.parse().expect("milliseconds"))
        })
        .collect()
}

#[test]
fn report_timing_prints_each_phase_and_leaves_the_store_alone() {
    let root = std::env::temp_dir().join(format!("stunt-reel-timing-{}", std::process::id()));
    drop(fs::remove_dir_all(&root));
    fs::create_dir_all(&root).expect("create temp dir");
    let film = workspace_root().join("tests/fixtures/synthetic_timeline.flm");

    let plain = root.join("plain");
    let output = render(&film, &plain, &[]);
    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        assert!(
            skips_without_software_adapter(&stderr),
            "plain render failed: {stderr}"
        );
        eprintln!(
            "[test] Skipping software-only test: no software fallback adapter with clip \
             distances (WARP lacks them; ADR 0054): {stderr}"
        );
        drop(fs::remove_dir_all(&root));
        return;
    }
    assert!(
        timing_lines(&String::from_utf8_lossy(&output.stderr)).is_empty(),
        "timing is off by default"
    );

    let timed = root.join("timed");
    let output = render(&film, &timed, &["--report-timing"]);
    assert!(
        output.status.success(),
        "timed render failed: {}",
        String::from_utf8_lossy(&output.stderr)
    );
    let lines = timing_lines(&String::from_utf8_lossy(&output.stderr));
    let phases: Vec<&str> = lines.iter().map(|(phase, _)| phase.as_str()).collect();
    assert_eq!(
        phases,
        [
            "scene_build",
            "world_build",
            "renderer_open",
            "world_upload",
            "shape_uploads",
            "loop"
        ]
    );
    assert!(lines.iter().all(|(_, ms)| *ms >= 0.0));
    let ms = |name: &str| lines.iter().find(|(phase, _)| phase == name).expect(name).1;
    assert!(ms("world_build") <= ms("scene_build"));
    // The synthetic film has no archive and no game tree, so no world is built or uploaded.
    assert_eq!(ms("world_build"), 0.0);
    assert_eq!(ms("world_upload"), 0.0);
    assert!(ms("world_upload") + ms("shape_uploads") <= ms("renderer_open"));

    assert_eq!(tree(&timed), tree(&plain), "the flag changed the store");
    drop(fs::remove_dir_all(&root));
}
