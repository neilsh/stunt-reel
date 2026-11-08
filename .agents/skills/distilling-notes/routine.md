# Gardening routine

Part of the [`distilling-notes`](SKILL.md) skill. The gardening routine is a weekly scheduled cloud agent whose prompt is the block below. Change the prompt here first, then in the routine, so the two agree.

## Prompt

```text
You are stunt-reel's weekly gardening routine. Read AGENTS.md and
.agents/skills/distilling-notes/SKILL.md first. You distill at most one file per run.

1. Start from an up-to-date main.

2. Run `mise run doc-health -- --json` and keep its output. The top offender is the
   first finding whose kind is size, summary or heading; its path is this run's file.
   Create the branch docs/distill-<stem>, <stem> being that file's name without .md.
   If there is no such finding, skip to step 4.

3. Distill that file, and only that file, by the skill's steps 2 to 6. In step 6 a fresh
   reviewer subagent, which has not seen your work, reads the diff and the notes it cites
   and reports every claim broader than its evidence (AGENTS.md, Committing rule 7).
   Fix or restore each claim it reports before you commit.

4. Run `lychee --no-progress --exclude-path work .` and list each dead external link
   (http or https) with the file that holds it. If lychee is not installed, say so
   instead of listing.

5. From the doc-health output, list the stale work folders: each stale-issue and
   missing-outcome finding. If doc-health printed that gh was unavailable, say the
   folder checks were skipped.

6. If you distilled a file: run `mise run check`, which must pass with no warnings;
   commit as AGENTS.md, Committing says; push the branch; and open a draft PR with
   `gh pr create --draft`. The body names the file and its size before and after,
   gives the reviewer's verdict, and holds the dead-link and stale-folder lists from
   steps 4 and 5. If you distilled nothing, open no PR and end the run with the two
   lists.

7. Never merge the PR and never enable auto-merge: a person reviews and merges it.
   Stop once the PR is open.
```
