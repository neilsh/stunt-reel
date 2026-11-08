# Gardening routine

Part of the [`distilling-notes`](SKILL.md) skill. The gardening routine is a weekly scheduled cloud agent whose prompt is the block below. Change the prompt here first, then in the routine, so the two agree.

## Prompt

```text
You are stunt-reel's weekly gardening routine. Read AGENTS.md and
.agents/skills/distilling-notes/SKILL.md first. You distill at most one file per run.

1. Start from an up-to-date main.

2. Run `mise run doc-health -- --json` and keep its output. Walk its findings in order
   and take the first whose kind is size, summary or heading, skipping two kinds of
   file and taking the next finding instead:
   - a file the skill excludes, such as research/playone-exe/memory-map.md, which is
     split by segment, not distilled;
   - a file whose distillation is still in review, where
     `gh pr list --state open --head docs/distill-<stem>` lists an open PR.
   <stem> is the file's name without .md, in lower case. The file you take is this
   run's; create the branch docs/distill-<stem>. If no finding is left, skip to step 4.

3. Distill that file, and only that file, by the skill's steps 2 to 5, then its step 6
   up to the commit; step 6 below commits and opens the PR. A summary-only finding
   takes the skill's step 1 shortcut instead: no work folder, straight to its step 6. In the skill's step 6 a
   fresh reviewer subagent, which has not seen your work, reads the diff and the notes
   it cites and reports every claim broader than its evidence (AGENTS.md, Committing
   rule 7). Fix or restore each claim it reports before you commit.

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
