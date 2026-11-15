---
title: "How to read these notes"
---

## Evidence tags

Findings carry one of these tags. The definitions are in [SPEC § 2.4](../docs/SPEC.md#24-evidentiary-tiers--contract-anchor-system).

- `[Established]`: proven directly from the disassembled machine code of `PLAYONE.EXE` or `MAKEONE.EXE`, or verified by a bit-exact runtime memory trap.
- `[Supported Inference]`: confirmed by cross-file byte alignment and by passing trajectory or visual parity gates across multiple corpus files.
- `[Bounded Observation]`: seen in a single film or fixture; behaviour outside the observed value ranges is unverified.
- `[Hypothesis]`: proposed from reasoning, community notes or an offline mock, and not observed in the binary or a corpus file. Do not cite it as fact.
- `[Unknown]`: unmapped padding bytes or unencountered opcodes.
- `[Superseded]`: not a confidence level but a retired claim or label, kept so old references still resolve and pointing to its replacement.

## Anchors

Permanent bracketed tokens mark facts that code, tests and notes cite. `[FMT-*]` is a format fact, `[MEM-*]` is a runtime memory fact, and `[I1]` to `[I8]` are architectural invariants. [SPEC § 2](../docs/SPEC.md#2-system-architectural-invariants--guardrails) defines the invariants.

## Links to GitHub

A link to a page on this site stays on the site. Work journals, design docs and code are not part of the site, so their links open on github.com.

## Licence

The notes are licensed [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/), except quoted third-party material, cited community research, captured game frames in comparison images, the Stunt Island master palette and the `.SOD` scale table, which are not relicensed. See [NOTICE](../NOTICE.md) and the [research README](../research/README.md).
