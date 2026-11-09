# Reviewer brief for a distillation

Give the fresh reviewer subagent of step 6 the old note (`git show origin/main:<path>`), the diff, and the notes it cites, and ask for three lists, each item with `file:line`:

1. **Claims broader than their evidence.** A claim in the rewritten note or the how-to that says more than its source: `only`, `all`, `noise`, `within`, `equivalent`, a scope widened from one film or run to all, or a tier tag moved off the claim it qualifies.
2. **Dropped facts.** Each fact of the old note found in none of the rewritten note, `journal.md` and the how-to. Condensing undated text loses facts that step 3's move does not catch: in the 2026-11-09 distillation of `research/parity/method.md` about a dozen were gone before review. A fact still true now that survives only in `journal.md` counts as dropped too, since step 4 states current truth in the note. Restore each, or say in the PR why it is obsolete.
3. **How-to lines the code does not bear out.** For each command, flag, path or value in the how-to diff, the `file:line` of the code that implements it (the argument definition and the code that acts on it), or a finding where the code says otherwise. A how-to moved from a note carries the note's stale claims: in that same distillation all twelve review-bot findings were of this kind (a capture that "never changes" a stored one but replaces it, a wrong capture path, a wrong `DS`).

Fix each finding or answer it in the PR.
