//! One integration-test binary for stunt-parity: each sibling file is a module here, so the crate links once.

#![allow(
    clippy::unwrap_used,
    clippy::expect_used,
    clippy::panic,
    clippy::print_stderr,
    clippy::default_trait_access,
    clippy::items_after_statements,
    reason = "integration tests assert by panicking, and their helpers sit outside #[test] fns"
)]

mod capture_test;
mod film_test;
mod render_test;
mod report_test;
mod schema_test;
mod test_support;
mod video_derived_test;
mod video_test;
