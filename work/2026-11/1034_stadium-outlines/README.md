---
title: "How much of LOCATION's stadium (shape 613) loss is its lines and outlines?"
started: 2026-11-24
issue: 1034
outcome: "613's lines and outlines own 17% of its loss at 2729 (20% of the mean over 27 frames), 54% (60%) with the pixel band beside them, the chalk lines and their band only 16% (18%); the mismatch lies a pixel toward the projection centre, and #1027's truncation prototype cuts 613's loss by about a third, so the follow-up is #1064."
---

# How much of LOCATION's stadium (shape 613) loss is its lines and outlines?

Split the stadium 613's loss on `location` ticks 2586 to 2872 between its lines, outlines and fills with a capture-side oracle, and scored #1027's projector-truncation prototype on the same frames ([`journal.md`](journal.md)); the finding is in [`prop-shape-loss.md` § 2.5](../../../research/parity/prop-shape-loss.md#25-one-tick-phase-and-lines).

## Handoff

The chalk lines alone do not carry the loss; the edges a pixel off toward the projection centre do, which is [#1064](https://github.com/neilsh/stunt-reel/issues/1064)'s rule.
Under the prototype the outline pixels' own disagreement rises (17.1% to 23.2%), a lead for `sod-vm-lines-spans.md` § 10's polygon-outline question.
The temporary switches are kept in [`switches/`](switches/): `DBG_LINEMARK` tags what drew each pixel, `DBG_ORACLE_DIR` gives the capture our index on a mask's pixels and prints a shape's per-frame loss; the scripts beside this file build the masks, counts and sheet from `mise run frame` stores.
