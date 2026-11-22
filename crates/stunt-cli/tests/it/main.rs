//! One integration-test binary for stunt-cli: each sibling file is a module here, so the crate links once.

#![allow(
    clippy::unwrap_used,
    clippy::expect_used,
    clippy::panic,
    clippy::print_stderr,
    clippy::indexing_slicing,
    reason = "integration tests assert by panicking, and their helpers sit outside #[test] fns"
)]

mod workers_test;
