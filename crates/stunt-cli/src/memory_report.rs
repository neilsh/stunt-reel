//! `--report-memory`: the resident set at each stage of a headless render, and its peak.
//!
//! Reading memory only reads the process; it never changes what the render writes.

use std::fs;
use std::process::Command;

/// One reading of the process's resident memory, in KiB.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) struct Reading {
    /// Resident set now (`VmRSS`, or the working set on Windows).
    pub rss_kib: u64,
    /// Highest resident set so far (`VmHWM`, or `PeakWorkingSetSize` on Windows).
    pub peak_kib: u64,
}

/// Prints one line per [`stage`](Self::stage) and the peak at [`finish`](Self::finish); both do
/// nothing when constructed disabled.
#[derive(Debug)]
pub(crate) struct MemoryReport {
    enabled: bool,
}

impl MemoryReport {
    /// A report that prints only when `enabled` (`--report-memory`).
    pub(crate) fn new(enabled: bool) -> Self {
        Self { enabled }
    }

    /// Prints the resident set after `stage`.
    pub(crate) fn stage(&self, stage: &str) {
        if !self.enabled {
            return;
        }
        match read_process() {
            Ok(reading) => println!("[stuntreel] memory {}", stage_line(stage, reading)),
            Err(error) => eprintln!("[stuntreel] memory {stage}: unavailable: {error}"),
        }
    }

    /// Prints the process's peak resident set, for the end of the run.
    pub(crate) fn finish(&self) {
        if !self.enabled {
            return;
        }
        match read_process() {
            Ok(reading) => println!("[stuntreel] memory peak {} MiB", mib(reading.peak_kib)),
            Err(error) => eprintln!("[stuntreel] memory peak: unavailable: {error}"),
        }
    }
}

/// `stage: rss N MiB (peak so far M MiB)`.
fn stage_line(stage: &str, reading: Reading) -> String {
    format!(
        "{stage}: rss {} MiB (peak so far {} MiB)",
        mib(reading.rss_kib),
        mib(reading.peak_kib)
    )
}

/// KiB as MiB, to one decimal.
fn mib(kib: u64) -> String {
    let tenths = kib.saturating_mul(10) / 1024;
    format!("{}.{}", tenths / 10, tenths % 10)
}

/// This process's resident memory: `/proc/self/status` on Linux, a PowerShell query of the
/// process's working set on Windows.
fn read_process() -> Result<Reading, String> {
    if cfg!(windows) {
        read_windows(std::process::id())
    } else {
        let status = fs::read_to_string("/proc/self/status")
            .map_err(|error| format!("read /proc/self/status: {error}"))?;
        parse_proc_status(&status)
    }
}

/// `VmRSS` and `VmHWM` from the text of `/proc/<pid>/status` (both in kB).
fn parse_proc_status(status: &str) -> Result<Reading, String> {
    let field = |name: &str| -> Result<u64, String> {
        status
            .lines()
            .find_map(|line| line.strip_prefix(name)?.strip_prefix(':'))
            .and_then(|rest| rest.trim().strip_suffix("kB"))
            .and_then(|kb| kb.trim().parse().ok())
            .ok_or_else(|| format!("no {name} line in /proc status"))
    };
    Ok(Reading {
        rss_kib: field("VmRSS")?,
        peak_kib: field("VmHWM")?,
    })
}

/// Windows has no `/proc`, and reading `GetProcessMemoryInfo` needs `unsafe` FFI, which the
/// workspace denies, so ask PowerShell for `WorkingSet64` and `PeakWorkingSet64`.
fn read_windows(pid: u32) -> Result<Reading, String> {
    let script =
        format!("$p = Get-Process -Id {pid}; \"$($p.WorkingSet64) $($p.PeakWorkingSet64)\"");
    let output = Command::new("powershell")
        .args(["-NoProfile", "-NonInteractive", "-Command", &script])
        .output()
        .map_err(|error| format!("run powershell: {error}"))?;
    if !output.status.success() {
        return Err(format!("powershell exited with {}", output.status));
    }
    parse_working_set(&String::from_utf8_lossy(&output.stdout))
}

/// `"<working set bytes> <peak working set bytes>"` as [`read_windows`]'s script prints it.
fn parse_working_set(text: &str) -> Result<Reading, String> {
    let mut words = text.split_whitespace();
    let mut next_kib = |what: &str| -> Result<u64, String> {
        words
            .next()
            .and_then(|word| word.parse::<u64>().ok())
            .map(|bytes| bytes / 1024)
            .ok_or_else(|| format!("no {what} in powershell's answer {text:?}"))
    };
    Ok(Reading {
        rss_kib: next_kib("working set")?,
        peak_kib: next_kib("peak working set")?,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn proc_status_gives_the_current_and_peak_resident_set() {
        let status =
            "Name:\tstuntreel\nVmPeak:\t  900000 kB\nVmHWM:\t  767000 kB\nVmRSS:\t  309000 kB\n";
        assert_eq!(
            parse_proc_status(status),
            Ok(Reading {
                rss_kib: 309_000,
                peak_kib: 767_000
            })
        );
    }

    #[test]
    fn a_status_without_the_fields_is_an_error_naming_the_missing_one() {
        let error = parse_proc_status("Name:\tx\nVmRSS:\t5 kB\n").unwrap_err();
        assert!(error.contains("VmHWM"), "{error}");
    }

    #[test]
    fn a_working_set_answer_is_two_byte_counts() {
        assert_eq!(
            parse_working_set("1073741824 2147483648\r\n"),
            Ok(Reading {
                rss_kib: 1_048_576,
                peak_kib: 2_097_152
            })
        );
        parse_working_set("1073741824").unwrap_err();
        parse_working_set("oops").unwrap_err();
    }

    #[test]
    fn a_stage_line_reports_mebibytes_to_a_tenth() {
        let reading = Reading {
            rss_kib: 308_224,
            peak_kib: 767_000,
        };
        assert_eq!(
            stage_line("scene built", reading),
            "scene built: rss 301.0 MiB (peak so far 749.0 MiB)"
        );
    }

    #[test]
    fn this_process_reads_back_on_linux_and_windows() {
        if cfg!(any(target_os = "linux", windows)) {
            let reading = read_process().expect("/proc/self/status, or powershell on Windows");
            assert!(reading.rss_kib > 0 && reading.peak_kib >= reading.rss_kib);
        }
    }
}
