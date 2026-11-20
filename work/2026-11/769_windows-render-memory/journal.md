# Journal

## 2026-11-19: `--report-memory` on Windows, GPU and lavapipe

- **Question**: does `--report-memory`'s Windows path (a PowerShell `Get-Process` query for `WorkingSet64` and `PeakWorkingSet64`, never run on Windows before) read the process, what does LOCATION ticks 12-120 measure there, and are the stores unchanged by the flag?
- **Method**: `77a9a49` (`origin/main`), `cargo build --release -p stunt-cli`, then the command in [`measure-a-renders-memory.md`](../../../docs/howto/measure-a-renders-memory.md) § 1 from Git Bash on the owner's Windows 11 laptop.
  GPU: no `VK_DRIVER_FILES`, no `--software-only`; `render.json` recorded `NVIDIA GeForce RTX 4070 Laptop GPU`.
  Lavapipe: `VK_DRIVER_FILES` naming mesa-dist-win 25.2.8's `lvp_icd.x86_64.json`, plus `--software-only`; `render.json` recorded `llvmpipe (LLVM 21.1.7, 256 bits)`.
  Four GPU runs with the flag and one without; two lavapipe runs with the flag and one without; `diff -r` between the stores of each backend's flag-on and flag-off runs.
- **Result**: every stage printed a reading; none printed `unavailable`.
  In MiB, the GPU's first run after the build, then the range of its next three, then the two lavapipe runs:

  | Stage | GPU, first run | GPU, runs 2-4 | Lavapipe, runs 1-2 |
  |---|---|---|---|
  | scene built | 289.8 | 288.5-288.7 | 289.6, 289.0 |
  | renderer opened | 511.1 | 475.0-475.6 | 654.3, 653.8 |
  | world mesh released | 250.2 | 214.5-215.3 | 395.1, 395.0 |
  | frames rendered | 268.8 | 232.5-233.3 | 513.6, 512.2 |
  | peak | 638.3 | 603.1-604.3 | 715.2, 714.6 |

  The GPU's first run took 15.5 s and read 35-36 MiB more than the next three from the renderer opening on; the cause is not identified.
  The peak so far at "scene built" was 342-344 MiB on both backends, against 303 MiB on Linux lavapipe.
  `diff -r` printed nothing for either backend, and the GPU's first and third runs' stores were also identical.
  Lavapipe took 10.6 and 8.1 s with the flag and 7.2 s without; each reading starts a PowerShell.
- **Verdict**: control. The Windows path works unchanged, so no code fix; the existing read-back test now runs on Windows too.
- **Lives in**: [`research/parity/evidence-limits.md` § 3](../../../research/parity/evidence-limits.md#3-what-is-not-yet-evidence), the LOCATION item; [`measure-a-renders-memory.md`](../../../docs/howto/measure-a-renders-memory.md).
