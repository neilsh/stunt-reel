//! Shared proptest configuration for the crate's own property tests.
//!
//! Integration tests carry a copy in `tests/common/props.rs`: they cannot see `cfg(test)`
//! items of the library.

use proptest::test_runner::{Config, RngSeed};

/// Seed for gate runs, so `mise run check` sees the same cases every time.
const SEED: u64 = 0x5354_554E_5452_4545;

/// 256 cases from a fixed seed, with no regression files.
///
/// `PROPTEST_CASES` and `PROPTEST_RNG_SEED` still apply, so a local run can explore further.
/// A failure's shrunk input becomes a named test in the matching `*_spec.rs` file instead of
/// a regression file.
pub(crate) fn config() -> Config {
    let mut config = Config::default();
    if std::env::var_os("PROPTEST_RNG_SEED").is_none() {
        config.rng_seed = RngSeed::Fixed(SEED);
    }
    config.failure_persistence = None;
    config
}
