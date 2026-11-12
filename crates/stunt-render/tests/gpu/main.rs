//! The GPU integration tests, kept as their own binary so `mise run test-render` can run them under the hang watchdog.

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
mod fragment_index;
mod lines;
mod renderer;
mod scene_renderer;
