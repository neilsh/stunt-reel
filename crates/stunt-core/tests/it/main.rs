//! One integration-test binary for stunt-core: each sibling file is a module here, so the crate links once.

#![allow(
    clippy::unwrap_used,
    clippy::expect_used,
    clippy::panic,
    clippy::print_stderr,
    clippy::default_trait_access,
    clippy::items_after_statements,
    reason = "integration tests assert by panicking, and their helpers sit outside #[test] fns"
)]

mod common;
mod fixtures_test;
mod flm_axes_test;
mod flm_camera_test;
mod flm_fuzz;
mod flm_spec;
mod flm_timeline_test;
mod font_spec;
mod link_spec;
mod scene_test;
mod sod_census_test;
mod sod_fuzz;
mod sod_spec;
mod sod_tap_test;
mod vfs_fuzz;
mod vfs_spec;
mod world_test;
