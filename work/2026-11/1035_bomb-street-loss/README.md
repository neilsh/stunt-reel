---
title: "Why does BOMB's street (shape 1756) lose 0.02 to 0.07 a frame where it is drawn in place?"
started: 2026-11-24
issue: 1035
outcome: "On ticks 2036 to 2740 and 3312 to 3477 the street's own pixels own 88% and 74% of its loss and the pixels around it 11% and 26%, so the edge-window hypothesis is a negative for the bulk; its lane dashes, outline lines drawn a pixel off (mostly a row toward the projection centre), own 74% and 48%, and #1027's truncation prototype cuts its loss by 37% and 22%, so the follow-up is #1064."
---

# Why does BOMB's street (shape 1756) lose 0.02 to 0.07 a frame where it is drawn in place?

Split the street 1756's loss on `bomb` ticks 2036 to 2740 and 3312 to 3477 between windows it fills alone and windows it shares, between its own pixels and its neighbours' with a capture-side oracle, tagged what draws its dashes, and scored #1027's projector-truncation prototype on the same frames ([`journal.md`](journal.md)); the finding is in [`prop-shape-loss.md` § 2.6](../../../research/parity/prop-shape-loss.md#26-the-streets-dashes-are-drawn-a-pixel-off).

## Handoff

The street's loss is its lane dashes a pixel off, which [#1064](https://github.com/neilsh/stunt-reel/issues/1064)'s truncation rule removes about half of; the capture's dashes also lie a column to the right on both sides of the centre, which truncation toward the centre does not explain, a lead for `sod-vm-lines-spans.md` § 10's outline-pixel question.
Measured on the GPU, not the canonical lavapipe; 1756's film mean there rounds to #989's lavapipe figure.
The temporary scorer switch is kept in [`switches/DBG_WINDUMP.diff`](switches/DBG_WINDUMP.diff) (window dump, with #1034's oracle and shape print); the line tags are #1034's `DBG_LINEMARK`.
The scripts beside this file read its dumps, build the oracle masks and the sheet from `mise run parity` and `mise run frame` stores; their output is in [`logs/`](logs/).
