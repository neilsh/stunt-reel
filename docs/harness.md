# Agents and harnesses

This repository is worked by more than one agent harness — DeepSeek Harness and Claude Code
today, and whichever one the next contributor brings — as well as by people. The policy below is
the same for all of them because it is a policy of the repository; the notes under it are
capability facts about one harness on one host, which is why they are dated and kept apart.
Nothing here is a fact about Stunt Island.

## Policy (any agent)

* **The gate is `mise run check`** — one ordered script, one line per step, a PASS/FAIL verdict
  and `target/check.log` ([ADR 0014](adr/0014-the-gate-is-one-ordered-script.md)).
  `check-rust` and `check-py` run the same steps for one language.
* **Everything goes through `mise run`.** Every agent-facing script has a task, so `mise run *`
  is the one command shape to pre-approve and `mise tasks` is the exhaustive list; a task name
  that is not there does not exist ([AGENTS.md](../AGENTS.md) SOP 5.5).
* **One writer per checkout path, one branch per worktree.** A read-only scout may share a
  path; two writers must not ([AGENTS.md](../AGENTS.md) SOP 6).
* No harness enforces any of this for you: `mise.toml` and `gate.py` enforce the gate, and the
  rest is reviewed.

## DeepSeek Harness (this host, observed 2026-10-25)

| Mode | Read | Write | Typical use |
| --- | --- | --- | --- |
| `read-only` | yes | no | inspecting a worktree you do not own |
| `workspace-write` | yes | inside the workspace only | the default for a normal session |
| `danger-full-access` | yes | anywhere the user can write | builds and tool installs that live outside the checkout |

The mode is visible in every `run_code` result footer as `File sandbox: <mode>`, and
`enforcement: partial` means the host could not confine every operation. A mode change
mid-program aborts that program; re-run it rather than assuming it half-completed.

### What `workspace-write` cannot do here

Confirmed by failure on 2026-10-25, not by reading the packaged sources:

* `mise run ...` repairs its pinned Rust toolchain under `%LOCALAPPDATA%\mise` on every
  invocation, and `workspace-write` denies that write (`failed create_dir_all:
  ...\mise\downloads\rust\1.99.1: Access is denied (os error 5)`), so `mise run init` and
  `mise run check` stop before their first step. Two ways through: run the command escalated,
  or set `MISE_DISABLE_TOOLS=rust` and put the installed toolchain's `bin` on `PATH` (for the
  pin in `mise.toml`: `%LOCALAPPDATA%\mise\installs\rust\1.99.1\bin`) — mise then skips the
  tool check and the gate runs under `workspace-write`.
* Directory ACLs are only partially enforced: a directory created under the sandbox can refuse
  a later nested creation inside it, and a stale one can refuse removal.
* `cargo` writes `target/` inside the checkout, so a warm build is fine once the toolchain
  resolves. `uv`'s cache is redirected into the shared `.cache/` (ADR 0013), so it is inside
  the workspace.

A denied gate is an environment symptom before it is a code symptom.

### Approvals

Each operation the policy does not pre-approve stops and waits, and a wait that outlives the
program's deadline returns as `deadline reached` — which names the symptom and not the cause.
Cancelling is not free either: the operation is abandoned and the next step usually retries it.

* **Pre-approve `mise run *`.** That is why every agent-facing script has a task.
* **Keep the timeout short** (about 90 s) so a blocked command returns as a decision.
* **Surface the reason.** `blocked: awaiting approval — <reason>` is actionable; `deadline
  reached` is not.

### Timeouts

`run_code` defaults to a 120 s deadline. Long steps — a cold build, a sweep, a capture — must
pass `timeoutMs` or they die at 120 s. For anything over roughly ten minutes, start it as a
background job and keep working.

### Reading and editing

* A file must be read in the session before it can be edited, and the read is per checkout path:
  reading a file in the primary checkout does not authorise the same path in a worktree.
* `edit` returns the affected region, and a large edit returns both the old and new text, so
  editing a 13 KB file can add ~27 KB to the conversation. Prefer several small edits.
* `grep` over temp paths can fail on non-UTF-8 paths; that is a ripgrep input error, not a
  policy denial.

## Claude Code

[.claude/settings.json](../.claude/settings.json) is committed, so this harness's settings *can*
ship with the checkout and be reviewed in a PR — unlike the harness above. Today it carries no
`permissions.allow` block, so the `mise run *` policy above is unenforced for this agent: it
will ask per command until someone commits the allow rule. [`CLAUDE.md`](../CLAUDE.md) is a stub
that imports `AGENTS.md`, because Claude Code reads `CLAUDE.md` and this repo's guide has the
other name.

Not yet documented: its sandboxing and timeout behaviour. Fill that in from observation, not
from vendor documentation — this page records what we have seen.

## Adding another harness

Add a section when you have used the harness here, and state what it confines, what it asks
before running a command, where its settings live, and whether those settings can be committed.
Do not assume a behaviour because a different harness has it. Split this page into
`docs/harness/<tool>.md` when a second section outgrows a screen.

## Where the settings live

| Harness | Settings | Ship with the checkout? |
| --- | --- | --- |
| DeepSeek Harness | `~/.dsh` on this host | no — host-local |
| Claude Code | [.claude/settings.json](../.claude/settings.json) plus `~/.claude/settings.json` | repo file yes, user file no |

A checkout cannot ship the DeepSeek Harness policy, so this page is the repository's record of
what it should be.
