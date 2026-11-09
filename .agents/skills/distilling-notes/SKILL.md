---
name: distilling-notes
description: "Use when asked to distill a research note or `docs/` page into current truth, when a note is over its 20 KB budget, or when `mise run doc-health` reports an evergreen file over budget, a note without `summary:`, or a dated, ordinal-round or session-style heading."
---

# Distilling notes

A distillation rewrites an evergreen note as what is true now and moves its dated narrative, verbatim, into a work folder, where `git log -S` still finds it. One file per PR; the daily [gardening routine](routine.md) runs this skill.

## Steps

1. **Pick the file.** The one you were given, else the first `size`, `summary` or `heading` finding of `mise run doc-health -- --json`. Done when one file is chosen and its findings are noted. A `summary`-only file needs no folder: add its `summary:` line and go to step 6.
2. **Make the folder.** By hand (it has no issue): `work/<YYYY-MM>/distill-<stem>/` for this month and the file's stem in lower case (`docs/SPEC.md` gives `distill-spec`), `-2` for a second one in a month, with a `README.md` whose frontmatter is `title`, `started` and `outcome: ""` ([layout](../../../work/README.md#layout)). Done when `mise run work -- list` shows it.
3. **Move the narrative.** Cut each dated round, session log and superseded result from the note into the folder's `journal.md`, unchanged apart from relative link paths: one `## YYYY-MM-DD: <title>` entry per round, dated as its text is, ending with **Lives in** and the note. Link the work folder the text came from, if any; frozen folders are not appended to. Done when doc-health flags no heading in the note and every removed paragraph is in `journal.md`.
4. **Rewrite as current truth.** State what the moved text established, by subject. Each finding ends with an inline `_Source:` link to its entry's heading, and each rejected hypothesis is one line under `## Ruled out` with its journal link. Keep each claim no broader than its evidence: `only`, `all`, `noise`, `within` and `equivalent` stay literally true, and each tier tag stays on the claim it qualifies. Done when the note reads as current truth, every finding has a provenance line, and its `summary:` still holds.
5. **Move how-to out.** Commands, flags and troubleshooting for running our tools go to `docs/howto/<task>.md`, one task per file, linked from the note and any skill that repeated them. Done when the note holds only reference and explanation.
6. **Review and land.** Run `mise run fix` and `mise run check`; fix each broken heading link it reports. A fresh reviewer subagent works from [its brief](reviewer-brief.md) (AGENTS.md rule 7). Write the README's `outcome` with no figure review can change: it freezes once set. Commit; open a PR titled `docs(distill): <path>`. Done when each reviewer finding is fixed or answered, the check passes, and the note is under 20 KB or the PR says why not.

An offset registry (`research/playone-exe/memory-map.md`) is split by segment, not distilled. Text a test reads by path moves only in its own PR, with the code.
