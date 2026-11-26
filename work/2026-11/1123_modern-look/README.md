---
title: A viewer-only modern look
started: 2026-11-26
issue: 1123
outcome: "`stuntreel --look modern` lights and fogs a film in the window, `--video` and `-o`, through pipelines beside the parity ones; seven reference films render byte-identical stores on lavapipe."
---

# A viewer-only modern look

[#1123](https://github.com/neilsh/stunt-reel/issues/1123) asked for `--look modern`: directional lighting and distance fog beside the Mode 13h parity look.
The plan is the issue's `## Tentative plan` comment; the evidence is in [`journal.md`](journal.md).

The look and its flag are in [Render a film](../../../docs/howto/render-a-film.md#watch-it-lit-and-fogged); the `[I3]` exemption is in [`docs/SPEC.md`](../../../docs/SPEC.md#2-system-architectural-invariants--guardrails); the flag bit is in [`palette-and-shading.md`](../../../research/formats/concepts/palette-and-shading.md#vertex-flag-bitfield-flags-u8).
