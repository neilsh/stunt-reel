---
title: "Confirm the lavapipe clip-NaN repro on Linux before filing it with Mesa"
started: 2026-11-16
issue: 642
outcome: "The repro draws NaN noperspective pixels on Ubuntu 26.04's Mesa 26.0.8 (LLVM 21.1.8) under WSL 2: case A 1,077, case B 442, no NaN in the control. The draft's Affected versions are updated in a copy; no patched Mesa build was tried (no sudo, more than a short setup); filing upstream is left to the owner."
---

# Confirm the lavapipe clip-NaN repro on Linux before filing it with Mesa

**Question.** Does the repro in [`lavapipe-clip-nan`](../lavapipe-clip-nan/README.md) show the NaN `noperspective` varying on a Linux Mesa build, and can the draft's suggested fix be tried in a Mesa build under WSL? Issue #642, steps 1 and 3; step 2 (filing at gitlab.freedesktop.org) is the owner's.

## Contents

- [`journal.md`](journal.md): the run on WSL Ubuntu 26.04 with Mesa 26.0.8, and why no patched Mesa build.
- [`issue-draft.md`](issue-draft.md): a copy of the frozen draft with "Affected versions" updated. Not filed.

## Status

- 2026-11-16: both cases reproduce on Ubuntu 26.04's Mesa 26.0.8 (LLVM 21.1.8), 1,077 and 442 NaN pixels, no NaN in the control ([journal](journal.md)). Step 3 was skipped (no sudo for the build dependencies; more than a short setup). Left: filing the issue upstream, the owner's call.
