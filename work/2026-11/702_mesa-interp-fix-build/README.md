---
title: "Does the suggested interp() change stop lavapipe's clip NaN in a Mesa build?"
started: 2026-11-18
issue: 702
outcome: "Yes on the repro: a mesa-25.2.8 lavapipe build drew 1,519 NaN noperspective pixels without the change and 0 with it."
---

# Does the suggested interp() change stop lavapipe's clip NaN in a Mesa build?

**Question.** Does the `interp()` change suggested in [`642_wsl-clip-nan/issue-draft.md`](../642_wsl-clip-nan/issue-draft.md) (§ *Suggested direction*) stop the NaN `noperspective` pixels the [`lavapipe-clip-nan` repro](../lavapipe-clip-nan/README.md) draws, in a lavapipe built from Mesa's `mesa-25.2.8` tag?

## Contents

- [`journal.md`](journal.md): the stopped attempt, then the stock and patched builds and their counts.
- [`issue-draft.md`](issue-draft.md): a copy of [`642_wsl-clip-nan/issue-draft.md`](../642_wsl-clip-nan/issue-draft.md) with the builds' result in "Affected versions" and "Suggested direction".

## Status

- 2026-11-18: answered.
  Built from `mesa-25.2.8` with LLVM 20.1.2, stock lavapipe reproduces case A 1,077 and case B 442 NaN pixels; with the suggested change alone, both read 1.0 on every covered pixel and the control is unchanged ([journal](journal.md#2026-11-18-stock-and-patched-lavapipe-builds-of-mesa-2528)).
  The filed issue can call the fix tested on the repro; not tested: a varying that changes across the triangle, Mesa's test suites, and Mesa's `main` (the issue's optional step 3).
  An earlier session in the same day stopped at `meson setup`, refused by its permission classifier, until the owner allowed the build ([journal](journal.md#2026-11-18-a-cloud-build-stopped-at-meson-setup)).
