//! The GPU integration tests, kept as their own binary so `mise run test-gpu` can run them alone in the hang-rate loop.

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
mod disc;
mod draw_order;
mod fragment_index;
mod lines;
mod modern;
mod renderer;
mod scene_renderer;
