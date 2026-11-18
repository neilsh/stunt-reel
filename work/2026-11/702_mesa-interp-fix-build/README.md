---
title: "Does the suggested interp() change stop lavapipe's clip NaN in a Mesa build?"
started: 2026-11-18
issue: 702
outcome: ""
---

# Does the suggested interp() change stop lavapipe's clip NaN in a Mesa build?

**Question.** Does the `interp()` change suggested in [`642_wsl-clip-nan/issue-draft.md`](../642_wsl-clip-nan/issue-draft.md) (§ *Suggested direction*) stop the NaN `noperspective` pixels the [`lavapipe-clip-nan` repro](../lavapipe-clip-nan/README.md) draws, in a lavapipe built from Mesa's `mesa-25.2.8` tag?

## Contents

- [`journal.md`](journal.md): the attempts and where they stopped.

## Status

- 2026-11-18: not answered.
  A cloud session fetched the `mesa-25.2.8` source and the build tools, but its permission classifier refused `meson setup` twice, so nothing was built ([journal](journal.md)).
  Left: the stock and patched builds and their NaN counts, a copy of the issue draft with its suggested-fix section updated, and a comment on #642.
  The next attempt needs a session where `meson setup` on a downloaded source tree is allowed (a permission rule for Bash, or local-windows' WSL with `sudo`); the commands are in the journal.
