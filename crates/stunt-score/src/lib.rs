//! The parity engine: scores a render store against a capture (`[I6]`).
//!
//! Moved out of `stunt-cli` (#699) so the scorer is callable as a library; it depends on no
//! GPU crate. `stuntreel parity` parses its arguments into [`parity::Options`] and calls [`parity::run`].

pub mod parity;
pub mod parity_artifacts;
pub mod render_store;
#[cfg(test)]
mod test_support;

use std::fmt::Write as _;

use sha2::{Digest as _, Sha256};

/// Lowercase hex SHA-256.
#[must_use]
pub fn sha256(bytes: &[u8]) -> String {
    Sha256::digest(bytes)
        .iter()
        .fold(String::with_capacity(64), |mut hex, b| {
            let _ = write!(hex, "{b:02x}");
            hex
        })
}
