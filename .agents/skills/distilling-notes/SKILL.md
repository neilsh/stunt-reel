---
name: distilling-notes
description: "Use when asked to distill a research note or `docs/` page into current truth, when a note is over its 20 KB budget, or when `mise run doc-health` reports a size, missing-summary or dated-heading finding on an evergreen file."
---

# Distilling notes

A distillation rewrites an evergreen note as what is true now and moves its dated narrative, verbatim, into a work folder, where `git log -S` still finds it. One file per PR. The weekly gardening routine runs this skill: [`routine.md`](routine.md).

## Steps

1. **Pick the file.** The one you were given, else the first `size`, `summary` or `heading` finding of `mise run doc-health -- --json`. Done when one file is chosen and its findings are noted.
2. **Make the folder.** By hand, since it has no issue: `work/<YYYY-MM>/distill-<stem>/` for this month and the file's stem, `-2` for a second one in a month, with a `README.md` whose frontmatter is `title`, `started` and `outcome: ""` ([layout](../../../work/README.md#layout)). Done when `mise run work -- list` shows it.
3. **Move the narrative.** Cut each dated round, session log and superseded result from the note into the folder's `journal.md`, unchanged apart from relative link paths: one `## YYYY-MM-DD: <title>` entry per round, dated as its text is, ending with **Lives in** and the note. Link the work folder the text came from, if any, since a frozen folder is not appended to. Done when the note has no dated or session-style heading and every removed paragraph is in `journal.md`.
4. **Rewrite as current truth.** State what the moved text established, by subject. Each finding ends with an inline `_Source:` link to its entry's heading, and each rejected hypothesis is one line under `## Ruled out` with its journal link. Keep each claim no broader than its evidence: `only`, `all`, `every`, `never` and `within` stay literally true, and each tier tag stays on the claim it qualifies. Done when the note reads as current truth, every finding has a provenance line, and its `summary:` still holds.
5. **Move how-to out.** Commands, flags and troubleshooting for running our tools go to `docs/howto/<task>.md`, one task per file, linked from the note and from any skill that repeated them. Done when the note holds only reference and explanation.
6. **Review and land.** Run `mise run fix` and `mise run check`; fix each broken heading link it reports. A fresh reviewer subagent reads the diff and the notes it cites and reports every claim broader than its evidence (AGENTS.md, Committing rule 7); fix or restore each one. Write the folder README's `outcome`, commit, and open the PR. Done when the reviewer reports nothing broader, the check passes, and the note is under 20 KB or the PR says why not.

An offset registry (`research/playone-exe/memory-map.md`) is split by segment, not distilled.

## Common mistakes

- **Rewording while moving.** Reworded text escapes `git log -S` and hides edits inside a move: move first, then rewrite the note.
