---
title: "Agreement: land and location ground props beat terrain on lavapipe after #905"
started: 2026-11-21
issue: 922
outcome: "Outline line lists clipped to 1.1 times the view through user clip distances (ADR 0055); LAND agreement 309.42 to 5.23 pixels a tick, LOCATION 79.24 to 8.60; no GPU score moved by the adoption rule's margin."
---

# Agreement: land and location ground props beat terrain on lavapipe after #905

Lavapipe drew outline lines cut by the 0.1 m near plane beside the eye as wedges; the outline line lists are now clipped to a band around the view.

- Decision: [ADR 0055](../../../docs/adr/0055-outline-lines-are-clipped-to-a-band-around-the-view.md)
- Finding: [`lavapipe-line-clip.md`](../../../research/parity/lavapipe-line-clip.md)
- Experiments: [`journal.md`](journal.md)
- Upstream report, not filed: [`mesa-issue-draft.md`](mesa-issue-draft.md)
