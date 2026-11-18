//! The parity engine: scores a render store against a capture (`[I6]`).
//!
//! Moved out of `stunt-cli` (#699) so the scorer is callable as a library; it depends on no
//! GPU crate. `stuntreel parity` parses its arguments and calls [`parity::run`].

#[expect(
    dead_code,
    reason = "only tests read video captures until a video scorer is merged (method.md § 4.4)"
)]
mod avi;
pub mod parity;
pub mod parity_artifacts;
pub mod render_store;
#[cfg(test)]
mod test_support;
#[expect(
    dead_code,
    reason = "only tests read video captures until a video scorer is merged (method.md § 4.4)"
)]
mod zmbv;
