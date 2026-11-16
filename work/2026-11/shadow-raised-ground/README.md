---
title: "#512: raised ground and a high actor's shadow in view"
started: 2026-11-16
outcome: "No ground leaf lies under a probe cube node, so the shadow plane depends on x and z only; THE.FLM shadows 129 to 270 m over raised ground keep their leaf plane and reach the draw with the ground point in view; the pixel check is #628."
---

# #512: raised ground and a high actor's shadow in view

The second record for [#512](https://github.com/neilsh/stunt-reel/issues/512), whose own folder, [`512_altitude-cutoff`](../512_altitude-cutoff/README.md), was frozen when its first PR landed. The record is [`journal.md`](journal.md), with the replay script [`ground_probe_replay.py`](ground_probe_replay.py); the findings live in [`sod-vm-frame.md` § 9.1](../../../research/playone-exe/sod-vm-frame.md#91-the-actor-shadow-draw) and [`hero-shadow.md`](../../../research/parity/hero-shadow.md) question 8.
