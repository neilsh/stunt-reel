//! `stuntreel --workers 2` writes the same render store, byte for byte, as `--workers 1`.
//!
//! The film is `synthetic_timeline.flm` with its last slice stretched to 200 ticks, so the
//! render spans five film seconds and the two workers each draw some. It renders on the
//! software adapter; with no adapter the test skips, unless `STUNT_REQUIRE_GPU=1` (ADR 0006).

use std::collections::BTreeMap;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::{Command, Output};

/// Byte of `synthetic_timeline.flm` holding slice 2's `tick_duration` (10).
const LAST_SLICE_DURATION: usize = 103;

/// The `stuntreel` binary Cargo built for this test, read at run time (issue #486).
fn stuntreel() -> PathBuf {
    std::env::var_os("CARGO_BIN_EXE_stuntreel")
        .map(PathBuf::from)
        .expect("CARGO_BIN_EXE_stuntreel is unset: run the tests through cargo")
}

fn workspace_root() -> PathBuf {
    let manifest = PathBuf::from(std::env::var_os("CARGO_MANIFEST_DIR").expect("run under cargo"));
    manifest
        .ancestors()
        .nth(2)
        .expect("crates/<name>")
        .to_path_buf()
}

/// Every file under `dir`, by path relative to it, with its bytes.
fn tree(dir: &Path) -> BTreeMap<PathBuf, Vec<u8>> {
    let mut files = BTreeMap::new();
    let mut pending = vec![dir.to_path_buf()];
    while let Some(at) = pending.pop() {
        for entry in fs::read_dir(&at).expect("read dir") {
            let path = entry.expect("entry").path();
            if path.is_dir() {
                pending.push(path);
            } else {
                let bytes = fs::read(&path).expect("read");
                let name = path.strip_prefix(dir).expect("under dir").to_path_buf();
                files.insert(name, bytes);
            }
        }
    }
    files
}

fn render(film: &Path, out: &Path, workers: &str) -> Output {
    Command::new(stuntreel())
        .arg("--headless")
        .arg(film)
        .arg("--out-dir")
        .arg(out)
        .args(["--software-only", "--width", "64", "--height", "48"])
        .args(["--workers", workers])
        .output()
        .expect("run stuntreel")
}

#[test]
fn two_workers_write_the_store_one_worker_writes() {
    let root = std::env::temp_dir().join(format!("stunt-reel-workers-{}", std::process::id()));
    drop(fs::remove_dir_all(&root));
    fs::create_dir_all(&root).expect("create temp dir");
    let mut film = fs::read(workspace_root().join("tests/fixtures/synthetic_timeline.flm"))
        .expect("read fixture");
    assert_eq!(
        film.get(LAST_SLICE_DURATION),
        Some(&10),
        "the fixture moved"
    );
    film[LAST_SLICE_DURATION] = 200;
    let film_path = root.join("LONG.FLM");
    fs::write(&film_path, film).expect("write film");

    let one = root.join("one");
    let output = render(&film_path, &one, "1");
    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        let no_adapter = stderr.contains("Headless renderer failed");
        assert!(
            no_adapter && std::env::var("STUNT_REQUIRE_GPU").as_deref() != Ok("1"),
            "1-worker render failed: {stderr}"
        );
        eprintln!("skipping: no software adapter ({stderr})");
        drop(fs::remove_dir_all(&root));
        return;
    }
    let two = root.join("two");
    let output = render(&film_path, &two, "2");
    assert!(
        output.status.success(),
        "2-worker render failed: {}",
        String::from_utf8_lossy(&output.stderr)
    );

    let one = tree(&one);
    let seconds = one
        .keys()
        .filter(|name| name.starts_with("preview"))
        .count();
    assert!(seconds >= 4, "the render spans {seconds} film seconds");
    assert_eq!(
        tree(&two),
        one,
        "the stores differ, or the workers' were left behind"
    );
    drop(fs::remove_dir_all(&root));
}
