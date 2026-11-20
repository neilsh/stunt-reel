---
title: "research: do THE.FLM's high-actor shadows show in a captured frame (#512 pixels)"
started: 2026-11-20
issue: 628
outcome: "THE.FLM's capture shows a shadow mark on a hillside at ticks 837 to 892, removed by a one-byte no-shadow control and given to slots 3 to 16 by position, with their actors' 181 to 270 m read at ticks 884 and 885; by inference the 2026-11-16 capture lacked per-pass progress lines rather than looping (#846)."
---

# research: do THE.FLM's high-actor shadows show in a captured frame (#512 pixels)

The record is [`journal.md`](journal.md), with the control script [`shadow_control.py`](shadow_control.py); the findings live in [`sod-vm-frame.md` § 9.1](../../../research/playone-exe/sod-vm-frame.md#91-the-actor-shadow-draw), [`hero-shadow.md`](../../../research/parity/hero-shadow.md) question 8 and [`capture-dosbox-automation.md`](../../../research/playone-exe/capture-dosbox-automation.md) Ruled out.
Left open: a shadow in view above about 270 m or in a second film, and whether the cull ends the mark after tick 892 ([`sod-vm-frame.md` § 10](../../../research/playone-exe/sod-vm-frame.md#10-open-questions)).
