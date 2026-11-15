//! Paths the tests read, found at run time.
#![allow(
    clippy::expect_used,
    reason = "a test helper outside #[test]: a missing CARGO_MANIFEST_DIR is the failure"
)]

use std::path::PathBuf;

/// The workspace root, two levels above the `CARGO_MANIFEST_DIR` Cargo sets for a test run.
///
/// Read at run time, never with `env!`, so no test binary records its checkout (issue #486).
///
/// # Panics
///
/// When `CARGO_MANIFEST_DIR` is unset or has fewer than two parents.
pub(crate) fn workspace_root() -> PathBuf {
    let manifest_dir = PathBuf::from(
        std::env::var_os("CARGO_MANIFEST_DIR")
            .expect("CARGO_MANIFEST_DIR is unset: run the tests through cargo"),
    );
    manifest_dir
        .ancestors()
        .nth(2)
        .expect("CARGO_MANIFEST_DIR is crates/<name> inside the workspace")
        .to_path_buf()
}
