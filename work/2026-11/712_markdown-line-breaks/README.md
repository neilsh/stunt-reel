---
title: "docs: break Markdown lines at sentences"
started: 2026-11-18
issue: 712
outcome: "Markdown starts each sentence on its own line (ADR 0051); 129 files reflowed in #714, which .git-blame-ignore-revs skips"
---

# docs: break Markdown lines at sentences

Should Markdown put one sentence on each line, and can the repository move to that without losing `git blame` history?
The owner's answers are in [`spec.md`](spec.md).

## Files

- [`spec.md`](spec.md): the decisions and the reflow's scope.
- [`plan.md`](plan.md): three pull requests, in order.
- [`journal.md`](journal.md): the blame experiment, the branch survey, the dry runs, blame after the reflow, and the hand fixes.
- [`reflow.py`](reflow.py): the one-off script that reflowed the files.
