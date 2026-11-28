---
title: "Edges on the worst frames sit about a pixel off the capture's after vertex truncation"
started: 2026-11-28
issue: 1168
outcome: "No vertex or edge rule: on five of the seven frames a page 1 to 3 ticks after the one ADR 0057 pairs has 30% to 61% fewer mismatched pixels (#1232); the residual is a row or column of one sign across the centre. Added parity-probe edges."
---

# Edges on the worst frames sit about a pixel off the capture's after vertex truncation

## Handoff

Part of #1168; journal: [`journal.md`](journal.md).

* **Done.**
  `parity-probe -- edges` ([`probes.md` § 12](../../../research/parity/probes.md#12-edge-offsets-edges)) with tests; the seven frames measured on the canonical lavapipe at `57c59687`; findings in `framing-and-actors.md` § 4, `sod-vm-lines-spans.md` § 8.14, § 10 and Ruled out, and `sod-animate.md` Open questions.
* **Not done.**
  The largest class is the page's timing, so its "routine" is the slot pass the pairing reads ([`capture.md` § 4](../../../research/playone-exe/capture.md#4-observed-results)); why its words name a page one to three ticks early on these frames is #1232, not read here.
  No renderer issue: no vertex or edge rule resulted.
* **Environment.**
  The data root's `location`, `bomb` and `land` captures do not match `references.toml`; the run used the pinned `captures` archive fetched with `wrangler` into a private data root (journal, Method).
