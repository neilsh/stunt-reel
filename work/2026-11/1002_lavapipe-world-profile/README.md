---
title: "Profile where lavapipe spends the world draws' time on the whole LOCATION film"
started: 2026-11-23
issue: 1002
outcome: "control: a user-mode stack profile puts the whole LOCATION film's lavapipe loop on lavapipe's queue thread, with six parts above 5% (rasterizer wait 26.7%, vertex 21.4%, line setup 14.6%, fragment-state store 10.2%, other state 8.5%, triangle setup 5.4%); no issue filed for them without the owner"
---

# Profile where lavapipe spends the world draws' time on the whole LOCATION film

Issue #1002, measurement only: a user-mode stack sampler ([`stack_sampler.py`](stack_sampler.py)) with mesa-dist-win's debug-info PDB profiles Windows lavapipe on the whole `LOCATION` film and Span B, with `#920`'s skip-all switch as the control ([`profile-probe.patch`](profile-probe.patch), against `f6976e67`; never committed in `crates/`).
The method, the per-part tables and the unattributed share are in [`journal.md`](journal.md), the per-run counts in [`profile-parts.json`](profile-parts.json), and the finding and its levers in [`lavapipe-render-time.md`](../../../research/parity/lavapipe-render-time.md) § 3 and Open questions item 1.

Handoff: each lever above 5% names the issue it would justify there; the owner decides which to file.
To profile again, unpack `x64\vulkan_lvp.pdb` from `mesa3d-25.2.8-debug-info-msvc.7z` into the data root's `tools\mesa-25.2.8-debug-info\x64`, build the patched binary, and run `stack_sampler.py record --out <base> -- <stuntreel command>` then `report <base> --search <pdb dir>`; kernel ETW (`wpr`) needs an elevated shell.
