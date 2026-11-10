# Gardening routine

Part of the [`distilling-notes`](SKILL.md) skill. The gardening routine is a cloud scheduled task, run daily at 06:00 Pacific on the repo's cloud environment, whose prompt tells it to carry out the block below. A change to the block reaches the next run once it is on `main`.

## Prompt

```text
You are stunt-reel's daily gardening routine, running in a cloud session. Read AGENTS.md
and .agents/skills/distilling-notes/SKILL.md first. You distill at most one file per run.
Here gh works only through REST (`gh api`): the proxy refuses the GraphQL-based `gh pr`
commands.

1. Start from an up-to-date main.

2. List the open PRs, one `<number> <title>` per line:
   `gh api 'repos/neilsh/stunt-reel/pulls?state=open&per_page=100' --jq '.[] | "\(.number) \(.title)"'`.
   If any title starts with `docs(distill):` or `docs(split):`, a distillation is still in
   review: end the run with no branch, commit or PR, and name that PR by number. If the
   call fails, end the run and say so.

3. Run `mise run doc-health -- --json` and keep its output. Take the first finding whose
   kind is size, summary or heading, skipping a file the skill excludes, such as
   research/playone-exe/memory-map.md, which is split by segment, not distilled. Skip,
   too, a file that an open PR edits, draft or not:
   `gh api repos/neilsh/stunt-reel/pulls/<number>/files --jq '.[].filename'` for each PR
   of step 2. Name each file skipped this way with the PR that holds it, for step 7. If no
   finding is left, skip to step 5. <stem> is the file's name without .md, in lower
   case. A size finding on a file that already has a work/*/distill-<stem>* folder was
   distilled before and is split instead: create the branch claude/split-<stem>.
   Otherwise create the branch claude/distill-<stem>.

4. A file to split is split by the skill's split.md, then goes to step 7 below. Otherwise
   distill that file, and only that file, by the skill's steps 2 to 5, then its step 6
   up to the commit; step 7 below commits and opens the PR. A summary-only finding takes
   the skill's step 1 shortcut instead: no work folder, straight to its step 6. In the
   skill's step 6 a fresh reviewer subagent, which has not seen your work, reads the
   diff and the notes it cites and reports every claim broader than its evidence
   (AGENTS.md, Committing rule 7). Fix or restore each claim it reports before you
   commit.

5. Run `mise run links` and list each dead external link (a 404 or 410, or a host that
   does not resolve) with the file that holds it. This session's network admits only a
   trusted list of hosts, so list a link its proxy refused (a 403 from the proxy, or a
   refused connection) separately as unchecked, never as dead. List any other 4xx or 5xx
   as unchecked too, with its status (`unchecked (400)`). If it cannot run, say why
   instead of listing.

6. From the doc-health output, list the stale work folders: each stale-issue and
   missing-outcome finding. If doc-health printed that gh was unavailable, say the
   folder checks were skipped.

7. If you distilled or split a file: run `mise run check`, which must pass with no warnings;
   commit as AGENTS.md, Committing says; push the branch; write the PR body to a file;
   and open a draft PR:
   `gh api -X POST repos/neilsh/stunt-reel/pulls -f base=main -f head=<branch> -f title='<title>' -F draft=true -F body=@<body file>`.
   The title is `docs(distill): <path>` or, for a split, `docs(split): <path>`. The body
   names the file and its size before and after (for a split, each new note and its
   size), gives a distillation's reviewer verdict, and holds the files skipped in step 3 and the
   dead-link and stale-folder lists from steps 5 and 6. If you distilled nothing, open no
   PR and end the run with those lists.

8. Never merge the PR and never enable auto-merge: a person reviews and merges it.
   Stop once the PR is open.
```
