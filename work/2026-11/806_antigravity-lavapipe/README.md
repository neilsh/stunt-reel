---
title: "cloud-antigravity: lavapipe (LLVM 15) is not comparable to expected.lavapipe (LLVM 20.1.2)"
started: 2026-11-19
issue: 806
outcome: ""
---

# cloud-antigravity: lavapipe (LLVM 15) is not comparable to expected.lavapipe (LLVM 20.1.2)

## Handoff

Option 1 of #806, unpacking the lavapipe build that `expected.lavapipe` names onto Debian 12, is ruled out as a drop-in under the system glibc: Ubuntu 24.04's `libvulkan_lvp.so` and `libLLVM.so.20.1` import `GLIBC_2.38` symbols, which Debian 12's glibc 2.36 lacks, and `libLLVM` also needs `GLIBCXX_3.4.32`; running the renderer under a separate, newer glibc was not tried ([journal](journal.md#2026-11-19-whether-ubuntus-llvm-2012-lavapipe-can-run-on-debian-12)).
What is left is option 2, and it needs the owner to decide.
To inform that decision, someone on cloud-antigravity runs `mise run parity` on all seven films on a clean `crates/` tree matching the rows, then records each film's delta against `expected.lavapipe`.
CTRY and LOCATION are already measured.
If the owner accepts the LLVM 15 build, `comparison_line` in `python/stunt_reel/expected_scores.py` needs to treat its adapter name as matching the rows', or the films need a third expected-score class for it; both builds report as `cpu`, so that also means a new adapter classification for `CLASS_KEYS` in that file and a new `RENDERER_CLASSES` entry in `references.py`.
Until then, cloud-antigravity hands off `expected.lavapipe` checks as `local-only`, as `cloud-antigravity.md` says.
