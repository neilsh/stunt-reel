# Agents and harnesses

This repository is worked by more than one agent harness — DeepSeek Harness, Claude Code and Antigravity today, some of them hosted in T3 Code, and whichever one the next contributor brings — as well as by people.
The policy below is the same for all of them because it is a policy of the repository; the notes under it are capability facts about one harness on one host, which is why they are dated and kept apart.
Nothing here is a fact about Stunt Island.

## Policy (any agent)

* **The gate, `mise run` and the one-writer rule are in [AGENTS.md](../AGENTS.md#working-economically)**; worktree placement and reaping are under [Worktrees](../AGENTS.md#worktrees).
* **Worktree-per-writer is an opt-in mode** for at least two genuinely independent tickets: disjoint files, separately verifiable, no shared file.
  Each writer branches from the Lead's current `HEAD`, commits only on its own branch, and at most two writers plus the Lead work at once; the Lead integrates in the same session, in dependency order, with the full gate at the tip.
  The contract is [the retro-hardening plan](../work/2026-10/retro-hardening/retro-hardening-2026-10-25.md).
  Unattended runs use about two implementers the same way, except each opens its own PR; a dependent item starts after its parent merges, or is stacked and armed after it.
* **Route implementers by fit:** dsh first where the spec is clear and the task needs no judgment over evidence (prefix-cache hit rate is not the test); `Sonnet` for other well-specified implementation; `Opus` for research, diagnosis, design, and items expected to need rounds of hypotheses.
  Otherwise subagents use the session model (`inherit`) and the same provider's `fast` tier only for simple bounded work (`Haiku` on Claude Code, `Gemini 4 Hydrogen` / `flash` on Antigravity): surveys, mapping tables, mechanical edits, grading against a calibrated rubric, and browser UI; never escalate above the session model or switch provider families outside this routing.
* **Review:** dispatch the Sonnet [reviewer agent](../.claude/agents/reviewer.md) by default, for first reviews and re-reviews.
  The first review of a Sonnet- or dsh-built PR is the exception: Opus or Antigravity, as a general-purpose subagent with `model: opus` and `Opus` as `<Reviewer>` in the brief, or as an Antigravity worker; not the `reviewer` agent with a model override, which names `Sonnet`.
  On #160 a Sonnet review missed four real bugs that an Opus review then found, among them a preflight that built despite `--no-build`.
  Re-reviews prefer Antigravity when Gemini quota allows, otherwise the `reviewer` agent; they cover only what changed since the last reviewed commit, run once after every finding is fixed, and are skipped for a wording-only fix (reply with the new text), except on a PR whose diff touches a path rule 5 names: any fix, rebase or merge there is committed locally and re-reviewed at its SHA before the push, and a rebase or merge needs a fresh `clean` comment at the new head; for a conflict only in `research/MAP.md`, that re-review only confirms `mise run knowledge-map -- --check` and a diff showing only `main`'s files ([`pr-and-filing.md`](../.agents/skills/running-unattended/pr-and-filing.md) step 1).
* **An unattended run has a coordinator and workers.**
  The coordinator runs on Sonnet from the start, reads no diffs or issue bodies (workers read them and report), appends every item transition to `build/scratch/run-state.md`, and hands off, when its context passes about 150k tokens, instead of compacting: it starts a fresh coordinator from that file's content (a cloud session's new container cannot read the gitignored file, so the content goes in the new session's prompt), or runs Shutdown where it cannot start one.
  In a cloud session either waits until no worker is in flight, or until every in-flight item has a pushed branch (a rule 5 item only after its review and push), since an unpushed commit is lost with the container; any other item is released and listed under Needs you.
  When a person has asked CodeRabbit for a review, it checks once, at the 20-minute timeout.
  The skill lists the `orca orchestration` flags the coordinator and workers need, so nobody loads `--help` or the orchestration guide into context.
  The contract is [`coordinator.md`](../.agents/skills/running-unattended/coordinator.md); the reasons are in #509.
* **A Claude implementer ends when its PR opens** (for a diff that changes a path rule 5 names, when it commits: the coordinator pushes after the fresh review, and a spec or plan is reviewed before its commit), or earlier if its context passes about 150k tokens; a fresh worker starts from the PR and the review comment to make the fixes, while dsh workers may keep their session.
  Before asking for review, the implementer scans its own diff for the `AGENTS.md` § 3 rule 5 words and checks every quoted figure against its source.
* **Prototypes stop once measured:** no PR polish, review or docs until one is chosen; run parallel prototypes only for decisions that are hard to undo.
  Measuring is optional — compare cost with `ccusage` blocks and sessions joined to roles; the quality guard is that no merged PR needs a fix or revert afterwards.
* **Subagent-driven development reviews once per PR.**
  `superpowers:subagent-driven-development` runs one fresh-context review of the finished branch before the PR — the `reviewer` agent, or Opus or Antigravity for a Sonnet- or dsh-built branch; a fix wave goes straight to the gate.
  Size each task so its implementer finishes within about 150 turns.
* **A subagent leaves nothing running when it reports.**
  It runs the gate in the foreground (on Claude Code, with a 600 s timeout) and stops any background job or monitor before its report: on #578 a Haiku implementer's leftover monitors woke it after its report, and it reported three more times.
* **Approvals the user need not give.**
  * A fresh subagent reviews each spec or plan and the author revises it before presenting it, so the user sees the revised version.
  * A [startable](agents/issue-tracker.md#conventions) issue labelled `status:ready-for-agent` goes straight to a plan, or to implementation when it needs none; brainstorming is for the rest.
* **Glob and search from a named folder.**
  Claude Code's Glob ignores `.gitignore` and `.ignore`, so from the root it walks every worktree under `.claude/worktrees/` (about 200,000 files each through their data-root links) and can time out.
  Pass `path`, or `ls` the root.
* No harness enforces any of this for you: `mise.toml` and `gate.py` enforce the gate, and the rest is reviewed.

## DeepSeek Harness

What it confines, asks and gives you on this host is on its own page, [`harness/deepseek.md`](harness/deepseek.md).

## Claude Code

[.claude/settings.json](../.claude/settings.json) is committed, so this harness's settings *can* ship with the checkout and be reviewed in a PR, unlike DeepSeek Harness's.
Its `permissions.allow` block covers `mise run *`, the git and `gh` commands a [`running-unattended`](../.agents/skills/running-unattended/SKILL.md) run uses (branch, commit, push to a branch, open a PR, arm or disarm squash auto-merge, file and edit issues) and the `orca orchestration` commands, so a worker in a fresh checkout or Orca workspace runs most of the loop without a permission prompt.
The git and `gh` rules are written for the Bash tool; the same commands through the PowerShell tool, a cloud session's REST auto-merge route and a rebase onto a stack parent still ask.
Its `permissions.deny` block is a best-effort backstop for what that skill forbids, matched on common spellings: a push to `main`, a force push, skipping hooks, `gh pr merge --admin`, staging everything, `mise run reap -- --force` and `git worktree remove`.
The server-side guard is the `main` ruleset on GitHub (required status checks and linear history; no force push or deletion), not this list.
A rule matches the whole command, commit message included, so a message containing ` -a `, ` -n `, `--all` or `--no-verify` is refused too: reword it.
Anything else still asks per command unless `.claude/settings.local.json` allows it.
[`CLAUDE.md`](../CLAUDE.md) is a stub that imports `AGENTS.md`, because Claude Code reads `CLAUDE.md` and this repo's guide has the other name.
`.claude/skills` is likewise a committed symlink to `../.agents/skills`, because Claude Code looks for project skills in `.claude/skills/`, not `.agents/skills/`.
A checkout made without symlink support (`core.symlinks=false`, common on Windows without Developer Mode) gets a one-line text file there instead, and Claude Code sees no project skills.

Python one-offs go in a file here too, because a Bash tool's heredoc (`python - <<'EOF'`) loses backslashes and quotes through its shell; write the script to `build/scratch/<name>.py` and run it.

Not yet documented: its timeout behaviour, and its sandboxing beyond the integrity label below.
Fill that in from observation, not from vendor documentation — this page records what we have seen.

### Fixing a branch another worktree holds

Git refuses to check out a branch another worktree holds, and a session may be unable to write outside its own worktree.
So the fix is committed in your own worktree and the branch is moved underneath the other one; leave the other worktree's `HEAD` where it is until the fix is in.

**A local branch, such as a stack layer.**
Observed 2026-10-31, stacked PRs under `gh stack`, one worktree per layer.
A fix to a lower layer is made on a detached `HEAD`:

```sh
git -C <worktree-holding-layer> status --porcelain  # must print nothing: stop here if it does
git switch --detach <layer>                 # in your own worktree; the layer's tip, no branch
# edit, mise run check, git commit
git update-ref refs/heads/<layer> HEAD <old-tip> &&
  git -C <worktree-holding-layer> reset --hard     # its index and files catch up with the branch
```

The `status` check comes first because once the branch moves, the other worktree still has the old files checked out under it and `git status` there reports your commit reversed as staged changes, so a check made afterward cannot tell those from real uncommitted work.
`reset --hard` discards anything uncommitted, and the `&&` keeps it from running when `<old-tip>` no longer matches and `update-ref` refuses.
Writing into another worktree may need approval.
Then work up the stack: rebase the next layer onto the one below, run `mise run check` in its own worktree, and repeat.
`gh stack add` works only from the top branch of the stack, so run it in the worktree that holds the top.

**A pushed branch, such as another session's open PR.**
Observed once, 2026-11-12.
Build the fix on a branch of your own from the remote tip and push it to the PR's branch:

```sh
git fetch origin
git -C <worktree-holding-branch> status --porcelain       # must print nothing: stop if it does
git -C <worktree-holding-branch> rev-list origin/<branch>..HEAD  # likewise: unpushed commits
git switch -c <tmp> origin/<branch>                       # in your own worktree
# edit, mise run check, git commit
git push origin HEAD:<branch>                             # refuses if the PR moved on
```

Then bring the holding worktree up to the pushed tip with `git -C <worktree-holding-branch> merge --ff-only origin/<branch>` when it has the branch checked out, which refuses if it has diverged, or with `git -C <worktree-holding-branch> switch --detach origin/<branch>` when it sits on a detached `HEAD`.
Delete `<tmp>` once the PR merges.

### Desktop app: Auto-fix and isolated subagents

Observed 2026-11-08.

* **The user turns on Auto-fix for a PR `gh stack submit` opened.**
  `mcp__ccd_pr__set_monitor` attaches only to a PR the app is sure this session opened, and refused it for each of #309, #310, #312 and #313; ask the user rather than retry.
* **An isolated subagent starts from `origin/HEAD`, not the session's `HEAD`.**
  Worktree isolation cuts its `worktree-agent-*` branch from the remote default branch as last fetched; all five subagents on 2026-11-08 started there.
  A brief whose work needs the Lead's unmerged commits, a worktree-per-writer task among them, names the Lead's commit and has the subagent run `git switch -c <branch> <commit>`, and the subagent reports `<branch>` as the one holding its work.
  That worktree and branch outlive it and go as [`managing-worktrees`](../.agents/skills/managing-worktrees/SKILL.md) step 6 says.
* **A session that hands the rest of its work to a session it starts stays quiet.**
  The app wakes it whenever that session ends a turn.
  It answers each progress note in one line with no tool calls and checks the result once, when the session reports it done.
  Observed 2026-11-15: the #576 planning session spent 16 Opus turns at about 190k tokens of context relaying its build session, 6 of them re-running `git log`.
* **A started session's brief asks for its whole answer in its wrap-up recap.**
  The note that wakes the starting session quotes the recap, then the final message, cut at 400 characters ("first 400 of 1176 characters"), so an answer in the recap needs no read of the session's events.
  Observed 2026-11-15: the #576 planning session called `list_events` 5 times, twice paging back, for two started sessions' reports its notes had cut off.
* **A started session's branch and PR state comes from `gh`.**
  A turn the user drives in that session sends no note, so its notes go stale.
  Observed 2026-11-15: the #576 planning session told the user two spike branches were unpushed after the user had them opened as #580 and #581.

### A low-integrity virtualenv

Seen once (2026-11-01): every `mise run` Python task failed with a bare `PermissionError` (`WinError 5` on `mkdir`) while PowerShell wrote the same paths.
The checkout root carried an inheritable `Mandatory Label\Low`, which `.venv` inherited; `icacls .venv` shows it.
The machine's owner removes it with `icacls <checkout> /setintegritylevel (OI)(CI)M` and recreates `.venv`.
Evidence and sources: [the research note](../work/2026-11/windows-sandbox-integrity-label/windows-sandbox-integrity-label-2026-11-01.md).

## Antigravity

Observed on `local-windows`, 2026-11-13:

* **What it confines:** File tools write inside the active workspace and the conversation's artifact directory under `~/.gemini/antigravity/brain/<conversation-id>` (reads can also reach installed skills under `~/.gemini/`).
  When `Orchestrator (Argon)` is selected, planning and `[plan review]` turns run on Argon with editing tools (`edit_file`, `write_file`) refused until `exit_plan_mode` hands the plan to the Hydrogen execution turn.
* **The shell it gives you:** Each `run_command` call starts a fresh Windows PowerShell process in the workspace root (`$env:` assignments and `Set-Location` do not persist across calls), so the [Windows PowerShell 5.1](#windows-powershell-51) rules below apply.
  Commands that run past `WaitMsBeforeAsync` continue as background tasks and wake the turn on completion; `schedule` sets one-shot timers without shell polling.
* **Approvals and settings:** Project skills under [`.agents/skills/`](../.agents/skills/) and [`AGENTS.md`](../AGENTS.md) ship with the checkout.
  Model selection, sandbox mode, and command allowlists live in `~/.gemini/antigravity` on the host and cannot be committed.

Observed on a Debian 12 cloud VM, 2026-11-18 ([`cloud-antigravity.md`](../.agents/skills/working-in-an-environment/cloud-antigravity.md)):

* **What it confines:** Runs as non-root `antigravity` (`uid=1000`) with `/` read-only (`RUSTUP_HOME=/usr/local/rustup`, `/usr/local/bin/uv` `0.13.8`); writable storage includes `/home/antigravity` (19 GB XFS, persists across sleep/wake) and `/tmp` (overlay, resets on sleep/wake).
* **The shell and setup:** Each `run_command` starts a fresh non-interactive `bash` sourcing `~/.bashrc` via `BASH_ENV`.
  [`.agents/environment.json`](../.agents/environment.json) runs `bash .claude/cloud-setup.sh --antigravity`, and project-local `/home/antigravity/env-setup.sh` fetches archives and builds the game trees; `.claude/settings.json` `SessionStart` hooks do not run.
* **Proxy and plugins:** Outbound HTTPS goes through `agy-plugin-proxy` (`gh` GraphQL commands work; `gdrive` reads Drive resources).

## T3 Code

Observed on `local-windows`, 2026-11-22, with Claude as the thread's provider:

* **What it is:** A desktop app that runs a provider's agent (Claude through the Agent SDK, dsh, Antigravity and others) in a thread, and adds its own MCP tools for delegating to child threads of any enabled provider, scheduling and pull requests; [`t3.md`](../.agents/skills/running-unattended/t3.md) is how an unattended run uses them.
* **What it confines and asks:** Each thread has a permission mode (Supervised, Auto-accept edits, Auto, Full access); a child inherits its parent's and cannot exceed it.
  The Claude provider's own settings, `.claude/settings.json` and the `SessionStart` hook included, still apply.
* **Where it works:** A new thread's worktree goes under the T3 home's `worktrees` folder (`~/.t3/worktrees/<project>/<name>`) unless [`harness-setup.md` § T3 Code](harness-setup.md#t3-code) moves it, on a `t3/` branch; it reaches the data root by configuration like any worktree ([ADR 0036](adr/0036-worktrees-reach-shared-state-by-configuration.md)).
* **Settings:** Host settings live in the T3 home (`~/.t3`) and cannot be committed; a `t3.json` at the repository root would ship worktree checkout options, and none exists.

## Windows PowerShell 5.1

Any harness that shells out through the host's Windows PowerShell 5.1 meets these; observed under DeepSeek Harness (2026-10-25), Claude Code (2026-10-31) and Antigravity (2026-11-13).
They are the shell of the `local-windows` environment ([`working-in-an-environment` § local-windows](../.agents/skills/working-in-an-environment/local-windows.md)).

* **No `utf8NoBOM`.**
  `Set-Content -Encoding utf8NoBOM` fails with "Unable to match the identifier name utf8NoBOM to a valid enumerator name", and one sweep's writes all failed while the sweep kept going, which reads like "nothing to change". 5.1's `Set-Content` and `Out-File` also write CRLF.
  Write UTF-8 without a BOM and with LF through `[IO.File]::WriteAllText($path, $text, (New-Object System.Text.UTF8Encoding($false)))`, with `` "`n" `` as the only line break in `$text`, and read one file back before running such a write over many.
* **Commit messages from a file.**
  A here-string piped to `git commit -F -` does not reach git.
  Write the message with `WriteAllText` above and run `git commit -F <file>`.
* **Issue and PR bodies from a file.**
  Double-quoted PowerShell strings (`"..."` and `@"..."@`) treat backticks (`` ` ``) as escape characters and corrupt Markdown code spans.
  Write the body to `build/scratch/<name>.md` (with the harness's file-write tool, or `WriteAllText` with a single-quoted `@'...'@` string) and pass `--body-file <file>` to `gh issue` and `gh pr`.
* **Python one-offs go in a file.**
  A nested `python -c "..."` loses backslashes and quotes through PowerShell 5.1; write the script to `build/scratch/<name>.py` with the file-write tool and run `python build/scratch/<name>.py`.
  A long JSON request body for `gh api` goes in a file with `gh api --input <file>`; a long jq filter has no from-file form, so ask for the fields with `--json` and filter with `ConvertFrom-Json` below.
* **`;`, not `&&`.** 5.1 rejects `cmd1 && cmd2` with a `ParserError`; chain with `;`, and put a step that must stop on failure in its own call.
* **Here-strings keep their text.**
  `@'` must end its line (`$x = @'`) and `'@` must start one, at column 0; the single-quoted form passes text unchanged, while `@"..."@` expands `$` and backtick escapes.
* **JSON written with a BOM.** 5.1's `-Encoding UTF8` writes a BOM, which Python's `json` rejects (`Unexpected UTF-8 BOM`); read such a file with `encoding="utf-8-sig"`, which strips it, or write the JSON from Python.
* **Search with the Grep tool, not a shell.**
  A pattern with quotes in it does not survive 5.1's quoting into a native command's arguments intact; the harness's own search tool takes it as written.
* **Parse `gh` output with `ConvertFrom-Json`.**
  A `gh ... --jq '<expression>'` filter loses its quotes the same way; ask for `--json <fields>` and pipe it to `ConvertFrom-Json` instead.

## Adding another harness

Add a section when you have used the harness here, and state what it confines, what shell it gives you, what it asks before running a command, where its settings live, and whether those settings can be committed.
Do not assume a behaviour because a different harness has it.
Give a harness its own `docs/harness/<tool>.md`, as DeepSeek Harness has, when its section outgrows a screen.

## Where the settings live

| Harness | Settings | Ship with the checkout? |
| --- | --- | --- |
| DeepSeek Harness | `~/.dsh` on this host | no — host-local |
| Claude Code | [.claude/settings.json](../.claude/settings.json), `.claude/skills` (link to `.agents/skills/`) plus `~/.claude/settings.json` | repo files yes, user file no |
| Antigravity | [`.agents/environment.json`](../.agents/environment.json), [`.agents/skills/`](../.agents/skills/) plus `~/.gemini/antigravity` and cloud `/home/antigravity/env-setup.sh` | repo files yes, user files no |
| T3 Code | `~/.t3` on this host, plus the thread provider's own settings | no — host-local |

A checkout cannot ship the DeepSeek Harness policy, so [`harness/deepseek.md`](harness/deepseek.md) and this page are the repository's record of what it should be.
