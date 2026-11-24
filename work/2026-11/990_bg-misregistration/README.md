---
title: "Is background misregistration a time offset or a page shift?"
started: 2026-11-23
issue: 990
outcome: "control: on 84 readout ticks no film's backdrop error is one time offset or one page shift (40 of 69 move under neither); a one-row vertical shift recurs (13 of 23 page-shift ticks, ours low), filed as #1027 on the projection side, and time offsets are per tick and of either sign"
---

# Is background misregistration a time offset or a page shift?

Issue #990, measurement only: `parity_probe.py register` (added here) searches render-tick offsets and whole-page shifts on our backdrop's edge pixels against the capture, on the twelve readout ticks of each reference film.
The method, the classification rule and the per-tick figures are in [`journal.md`](journal.md), the raw output in [`register-backdrop.txt`](register-backdrop.txt), [`register-with-props.txt`](register-with-props.txt) and [`time-profiles.txt`](time-profiles.txt), and the finding in [`framing-and-actors.md`](../../../research/parity/framing-and-actors.md) § 4.

Handoff: the projection-side fix is #1027 (does `PLAYONE` truncate projected vertices toward the centre?).
To rerun, `mise run parity`, then `mise exec -- uv run python work/2026-11/990_bg-misregistration/run_register.py ctry,intro,land,balloon,traintnl,bomb,location [--with-props]` and `python work/2026-11/990_bg-misregistration/classify.py <output>`.
