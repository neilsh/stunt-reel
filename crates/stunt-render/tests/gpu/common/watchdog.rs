//! A per-test hang deadline for the `gpu` binary: one thread that names a stuck test and aborts.

use std::io::Write as _;
use std::sync::{Condvar, Mutex, MutexGuard, OnceLock, PoisonError};
use std::time::{Duration, Instant};

/// Environment variable that overrides the per-test deadline, in whole seconds.
pub(crate) const DEADLINE_ENV: &str = "STUNT_GPU_TEST_DEADLINE_S";

/// The per-test deadline when [`DEADLINE_ENV`] is unset.
///
/// The whole `gpu` binary took 4.7 s on lavapipe in CI, an upper bound on its slowest test
/// (<https://github.com/neilsh/stunt-reel/actions/runs/43765101119/job/132968312213>). The
/// deadline is `max(60, 10 x 4.7)` seconds rounded up to a multiple of 30.
pub(crate) const DEFAULT_DEADLINE: Duration = Duration::from_secs(60);

/// The deadline for `value` (the raw [`DEADLINE_ENV`] contents): `None` is
/// [`DEFAULT_DEADLINE`].
///
/// # Panics
///
/// Panics when `value` is not a positive whole number of seconds.
pub(crate) fn parse_deadline(value: Option<&str>) -> Duration {
    let Some(value) = value else {
        return DEFAULT_DEADLINE;
    };
    match value.parse::<u64>() {
        Ok(secs) if secs > 0 => Duration::from_secs(secs),
        _ => panic!("{DEADLINE_ENV} must be a positive whole number of seconds, got {value:?}"),
    }
}

/// The line written to stderr when `test` is still running `after` its start.
pub(crate) fn hang_message(test: &str, after: Duration) -> String {
    format!("HANG: {test} still running after {}s\n", after.as_secs())
}

/// The armed test's name, start and deadline.
type Slot = Option<(String, Instant, Duration)>;

/// One thread that aborts the process when the armed test outlives its deadline.
pub(crate) struct Watchdog {
    slot: Mutex<Slot>,
    changed: Condvar,
}

impl Watchdog {
    /// The process-wide watchdog; the first call spawns its thread.
    pub(crate) fn global() -> &'static Self {
        static GLOBAL: OnceLock<Watchdog> = OnceLock::new();
        static SPAWN: std::sync::Once = std::sync::Once::new();
        let watchdog = GLOBAL.get_or_init(|| Self {
            slot: Mutex::new(None),
            changed: Condvar::new(),
        });
        SPAWN.call_once(|| {
            std::thread::Builder::new()
                .name("gpu-watchdog".to_owned())
                .spawn(|| watchdog.run())
                .expect("spawn the GPU watchdog thread");
        });
        watchdog
    }

    /// Sets the deadline for `test`; dropping the result disarms it, unwinding included.
    ///
    /// The watchdog has one slot, so callers must hold `GPU_TEST_LOCK`, as `gpu_test` does.
    pub(crate) fn arm(&'static self, test: &str, after: Duration) -> Armed {
        *self.lock() = Some((test.to_owned(), Instant::now(), after));
        self.changed.notify_all();
        Armed(self)
    }

    fn lock(&self) -> MutexGuard<'_, Slot> {
        self.slot.lock().unwrap_or_else(PoisonError::into_inner)
    }

    fn run(&self) -> ! {
        let mut slot = self.lock();
        loop {
            slot = match slot.as_ref() {
                None => self
                    .changed
                    .wait(slot)
                    .unwrap_or_else(PoisonError::into_inner),
                Some((test, start, after)) => {
                    let left = after.saturating_sub(start.elapsed());
                    if left.is_zero() {
                        // `write_all`, not `eprintln!`: libtest captures the latter.
                        drop(std::io::stderr().write_all(hang_message(test, *after).as_bytes()));
                        std::process::abort();
                    }
                    self.changed
                        .wait_timeout(slot, left)
                        .unwrap_or_else(PoisonError::into_inner)
                        .0
                }
            };
        }
    }
}

/// An armed deadline; dropping it disarms the watchdog.
pub(crate) struct Armed(&'static Watchdog);

impl Drop for Armed {
    fn drop(&mut self) {
        *self.0.lock() = None;
        self.0.changed.notify_all();
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn an_unset_deadline_is_the_default() {
        assert_eq!(parse_deadline(None), DEFAULT_DEADLINE);
    }

    #[test]
    fn a_whole_number_of_seconds_is_the_deadline() {
        assert_eq!(parse_deadline(Some("7")), Duration::from_secs(7));
    }

    #[test]
    #[should_panic(expected = "STUNT_GPU_TEST_DEADLINE_S")]
    fn a_zero_deadline_is_refused() {
        parse_deadline(Some("0"));
    }

    #[test]
    #[should_panic(expected = "STUNT_GPU_TEST_DEADLINE_S")]
    fn a_non_number_is_refused() {
        parse_deadline(Some("abc"));
    }

    #[test]
    fn the_hang_line_names_the_test_and_the_bound() {
        assert_eq!(
            hang_message("renderer::draws", Duration::from_secs(120)),
            "HANG: renderer::draws still running after 120s\n"
        );
    }

    #[test]
    fn disarming_before_the_deadline_never_aborts() {
        // The watchdog has one slot; hold the GPU lock, as `gpu_test` does, so no GPU test arms
        // meanwhile. (The stuck self-test below runs in a child process and takes no lock.)
        let _lock = crate::common::GPU_TEST_LOCK
            .get_or_init(|| Mutex::new(()))
            .lock()
            .unwrap_or_else(PoisonError::into_inner);
        let result = std::panic::catch_unwind(|| {
            let _armed = Watchdog::global().arm("unwinds", Duration::from_millis(300));
            panic!("test body failed");
        });
        assert!(result.is_err());
        std::thread::sleep(Duration::from_millis(600)); // still alive past the deadline
    }

    const SELFTEST_ENV: &str = "STUNT_GPU_WATCHDOG_SELFTEST";

    /// The stuck body for [`a_stuck_test_is_named_and_aborted`]; a no-op unless run as its child.
    #[test]
    #[ignore = "run by a_stuck_test_is_named_and_aborted in a child process"]
    fn stuck_body() {
        if std::env::var(SELFTEST_ENV).as_deref() != Ok("1") {
            return;
        }
        let _armed = Watchdog::global().arm("stuck_body", Duration::from_secs(1));
        std::thread::sleep(Duration::from_secs(30));
    }

    #[test]
    fn a_stuck_test_is_named_and_aborted() {
        let output = std::process::Command::new(std::env::current_exe().expect("test exe path"))
            .args([
                "common::watchdog::tests::stuck_body",
                "--exact",
                "--ignored",
                "--nocapture",
            ])
            .env(SELFTEST_ENV, "1")
            .output()
            .expect("run the stuck child");
        assert!(!output.status.success());
        assert!(
            String::from_utf8_lossy(&output.stderr)
                .contains("HANG: stuck_body still running after 1s")
        );
    }
}
