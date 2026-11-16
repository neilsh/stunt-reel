---
title: "How we know what we know"
---

## Where the evidence comes from

*Stunt Island* never came with a description of its file formats or its player, so everything here is worked out from four kinds of source. They are not equally strong, and the tags in the next section say how firmly each finding is backed.

- **Disassembly of the original programs.** The original player is a compiled DOS program. We read its machine code with static tools, which show what the program contains without running it. Instructions read directly from it can earn the top tag, as can an exact trap on the running player's memory. Reading has gaps: the decompiler the project tried could not trace the player's drawing instructions to the code that runs each one, so the project wrote its own tools for that step. The output of a decompiler, which turns machine code back into readable code, counts only as a hypothesis until someone checks the underlying instructions.
- **Emulator captures of the original player.** We run the original player in a DOS emulator, play a film, and record its pictures and memory frame by frame. That shows what the player does while it runs, which reading its code cannot. Captures are not always repeatable: sound samples in a film's archive made some replays differ, so captures now replace them with stubs. Stubbing changes the pictures too: in the one film checked, most pages differed from a capture with its sounds, in ways not yet measured. We still record how far a result can be trusted along with the result.
- **The retail handbook.** The printed manual that came with the game, which we read as a scan turned into text. It is reliable about which options exist and what they are called. It is not reliable for numbers, because the text conversion corrupts digits, and its units are the game's own rather than measurements. It also describes the authoring side of the game, not the film player. A claim that rests on the handbook alone stays a hypothesis until the game's own files or code back it up.
- **Community research.** Fans have collected the game's files, tools, source code for extractors and notes about the file formats. We treat these as leads: a claim that rests on them alone stays a hypothesis until the game's own files or code show it. Some tutorial files and their printed descriptions disagree, so we do not treat them as an authority.

The game's files, the handbook and the community archive are not in the repository. A few game-derived tables, comparison images and archive manifests (lists of hashes, with no game bytes) are, as the [notice](../NOTICE.md) lists. To check a finding yourself, you need your own copy of the game, and for some findings the community archive too.

To see how the first two work in practice, read the notes on [static analysis tooling](../research/playone-exe/static-tooling.md) and on [capturing the original player in an emulator](../research/playone-exe/capture-dosbox-automation.md). The handbook has its own [source card](../research/handbook.md).

## Evidence tags

Findings carry one of these tags. The definitions are in [SPEC § 2.4](../docs/SPEC.md#24-evidentiary-tiers--contract-anchor-system).

- `[Established]`: proven directly from the disassembled machine code of `PLAYONE.EXE` (the original film player) or `MAKEONE.EXE` (its linking tool), or verified by a bit-exact runtime memory trap.
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
