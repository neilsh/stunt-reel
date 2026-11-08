# Gardening routine

Part of the [`distilling-notes`](SKILL.md) skill. The gardening routine is a cloud scheduled task, run daily at 06:00 Pacific on the repo's cloud environment, whose prompt is the block below. Change the prompt here first, then in the routine, so the two agree.

## Prompt

```text
You are stunt-reel's daily gardening routine, running in a cloud session. Read AGENTS.md
and .agents/skills/distilling-notes/SKILL.md first. You distill at most one file per run.
Here gh works only through REST (`gh api`): the proxy refuses the GraphQL-based `gh pr`
commands.

1. Start from an up-to-date main.

2. List the open PRs' titles:
   `gh api 'repos/neilsh/stunt-reel/pulls?state=open&per_page=100' --jq '.[].title'`.
   If any title starts with `docs(distill):`, a distillation is still in review: end the
   run with no branch, commit or PR, and name that PR. If the call fails, end the run
   and say so.

3. Run `mise run doc-health -- --json` and keep its output. Take the first finding whose
   kind is size, summary or heading, skipping a file the skill excludes, such as
   research/playone-exe/memory-map.md, which is split by segment, not distilled. If no
   finding is left, skip to step 5. <stem> is the file's name without .md, in lower
   case; create the branch claude/distill-<stem>.

4. Distill that file, and only that file, by the skill's steps 2 to 5, then its step 6
   up to the commit; step 7 below commits and opens the PR. A summary-only finding takes
   the skill's step 1 shortcut instead: no work folder, straight to its step 6. In the
   skill's step 6 a fresh reviewer subagent, which has not seen your work, reads the
   diff and the notes it cites and reports every claim broader than its evidence
   (AGENTS.md, Committing rule 7). Fix or restore each claim it reports before you
   commit.

5. Run `lychee --no-progress --exclude-path work .` and list each dead external link
   (http or https) with the file that holds it. If lychee is not installed, say so
   instead of listing.

6. From the doc-health output, list the stale work folders: each stale-issue and
   missing-outcome finding. If doc-health printed that gh was unavailable, say the
   folder checks were skipped.

7. If you distilled a file: run `mise run check`, which must pass with no warnings;
   commit as AGENTS.md, Committing says; push the branch; write the PR body to a file;
   and open a draft PR:
   `gh api -X POST repos/neilsh/stunt-reel/pulls -f base=main -f head=claude/distill-<stem> -f title='docs(distill): <path>' -F draft=true -F body=@<body file>`.
   The title starts with `docs(distill): ` and names the file. The body names the file
   and its size before and after, gives the reviewer's verdict, and holds the dead-link
   and stale-folder lists from steps 5 and 6. If you distilled nothing, open no PR and
   end the run with the two lists.

8. Never merge the PR and never enable auto-merge: a person reviews and merges it.
   Stop once the PR is open.
```
