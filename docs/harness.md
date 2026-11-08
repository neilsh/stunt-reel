# Agents and harnesses

This repository is worked by more than one agent harness — DeepSeek Harness and Claude Code
today, and whichever one the next contributor brings — as well as by people. The policy below is
the same for all of them because it is a policy of the repository; the notes under it are
capability facts about one harness on one host, which is why they are dated and kept apart.
Nothing here is a fact about Stunt Island.

## Policy (any agent)

* **The gate, `mise run` and the one-writer rule are in [AGENTS.md](../AGENTS.md#working-economically)**;
  worktree placement and reaping are under [Worktrees](../AGENTS.md#worktrees).
* **Worktree-per-writer is an opt-in mode** for at least two genuinely independent tickets:
  disjoint files, separately verifiable, no shared file. Each writer branches from the Lead's
  current `HEAD`, commits only on its own branch, and at most two writers plus the Lead work
  at once; the Lead integrates in the same session, in dependency order, with the full gate at
  the tip. The contract is [the retro-hardening plan](../work/2026-10/retro-hardening/retro-hardening-2026-10-25.md).
* **Subagents take Haiku for simple work and Opus for everything else.** Haiku only where the
  brief fully specifies the work and the result is easy to check: surveys, mapping tables,
  mechanical edits, grading against a calibrated rubric. Diagnosis, design, implementation and
  every review subagent (a standards or spec axis, a whole-branch review before a PR) run on Opus;
  Sonnet only where a calibrated workflow names it, such as the parity readout's tie-break. On
  #160 a Sonnet review missed four real bugs that an Opus review then found, among them a
  preflight that built despite `--no-build`.
* **Glob and search from a named folder.** Claude Code's Glob ignores `.gitignore` and `.ignore`,
  so from the root it walks every worktree under `.claude/worktrees/` (about 200,000 files each
  through their data-root links) and can time out. Pass `path`, or `ls` the root.
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

* `mise run` used to repair its pinned Rust toolchain under `%LOCALAPPDATA%\mise` on every
  invocation, because `components = "llvm-tools-preview"` does not match the component rustup
  reports (`llvm-tools-x86_64-pc-windows-msvc`), and `workspace-write` denied that write
  (`failed create_dir_all: ...\mise\downloads\rust\1.99.1: Access is denied (os error 5)`).
  The pin is now `llvm-tools`, which verifies clean, so a plain `mise run` no longer attempts
  the install. If it returns, run `mise install` once outside the sandbox;
  `MISE_DISABLE_TOOLS=rust` with the installed toolchain's `bin` on `PATH` remains a fallback.
* Directory ACLs are only partially enforced: a directory created under the sandbox can refuse
  a later nested creation inside it, and a stale one can refuse removal.
* A directory created with `mkdir(mode=0o700)` cannot be listed or removed by the process that
  created it, although Windows ignores the mode. pytest creates every temporary root that way;
  [`tests/conftest.py`](../tests/conftest.py) installs a Windows-only `os.mkdir` shim that drops
  the mode, so the gate's Python half runs under `workspace-write`.
* `cargo` writes `target/` inside the checkout, so a warm build is fine once the toolchain
  resolves. `uv`'s cache is the primary checkout's `.cache/uv` by absolute path (ADR 0013,
  ADR 0036), which is outside a worktree's workspace.

A denied gate is an environment symptom before it is a code symptom.

### Temporary directories

The sandbox also denies the OS temp directory to the processes the tests spawn: a gate run whose
`TMP` and `TEMP` pointed at the user's temp directory panicked in the `test-rust` step with
`create temp dir: Os { code: 5, kind: PermissionDenied, message: "Access is denied." }`, and
`pytest` hit `PermissionError: [WinError 5]` under DSH's own per-session temp path — so that
directory is not a dependable exception either.

`mise.toml` used to point `TMP` and `TEMP` into the shared cache for this; since
[ADR 0036](adr/0036-worktrees-reach-shared-state-by-configuration.md) tasks use the OS temp
directory, and a DSH session runs `mise run` tasks under `danger-full-access`
([harness-setup.md](harness-setup.md#dsh)). A `workspace-write` run that cannot avoid it can
still set the variables in the same call, because each `pwsh` call is a fresh process:

```powershell
New-Item -ItemType Directory -Force target\tmp | Out-Null; $env:TMP = "$PWD\target\tmp"; $env:TEMP = $env:TMP; cargo test --workspace --all-features
```

### Approvals

Each operation the policy does not pre-approve stops and waits, and a wait that outlives the
program's deadline returns as `deadline reached` — which names the symptom and not the cause.
Cancelling is not free either: the operation is abandoned and the next step usually retries it.

* **Pre-approve `mise run *`.** That is why every agent-facing script has a task.
* **Keep the timeout short** (about 90 s) so a blocked command returns as a decision.
* **Surface the reason.** `blocked: awaiting approval — <reason>` is actionable; `deadline
  reached` is not.

### Timeouts

`run_code` defaults to a 120 s deadline and accepts `timeoutMs` up to a hard cap of 600 s. Pass
`timeoutMs` for a step known to be slow but bounded — a cold build, a sweep, a capture — rather
than let it die at 120 s. For anything not known to finish inside about 60 s, start it as a
background job (`run_in_background`) and collect it with `job_output`: no deadline applies to
a job, and it outlives the program that started it. Start a command that might hang in the
background from the first call — a `git filter-branch` once consumed the full 600 s and left
the repository untouched.

### The shell it gives you

Commands run through Windows PowerShell 5.1 (`5.1.26100`), one fresh `pwsh -Command` per call:
`$env:` assignments, functions, variables and `Push-Location` do not survive into the next call,
so a setup step and the command that needs it belong in the same call. Its 5.1 pitfalls are in
[Windows PowerShell 5.1](#windows-powershell-51), because every harness that shells out through
it meets them.

### Delegation

A `subagent` is spawned with an id and reports back when it finishes; `send_message` addressed
to that id failed with `active teammate "<id>" not found` (`TEAM_MEMBER_NOT_FOUND`), so nothing
can be added to its instructions after it starts. Treat the brief as the whole instruction —
goal, paths it may read, output shape and stopping condition — because there is no second one.

### Teammates

Agent Teams share the Lead's checkout. The policy above still applies: only one member
writes at a time, and the Lead is the default writer. Teammates may read, design, review and
return patches. If the Lead assigns independent tickets, it creates one worktree per writer
from its current `HEAD`; each writer commits only on that branch and the Lead integrates
it, never the teammate. A shared file (`AGENTS.md`, `docs/harness.md`, `mise.toml`,
`tests/conftest.py`) folds the tickets into one writer regardless of file scope.

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

Not yet documented: its timeout behaviour, and its sandboxing beyond the integrity label below.
Fill that in from observation, not from vendor documentation — this page records what we have seen.

### Editing a stack layer another worktree holds

Observed 2026-10-31, stacked PRs under `gh stack`, one worktree per layer. Git refuses to check
out a branch another worktree holds, and the session could write only inside its own worktree,
so a fix to a lower layer is made on a detached `HEAD` and the branch is moved underneath:

```sh
git -C <worktree-holding-layer> status --porcelain  # must print nothing: stop here if it does
git switch --detach <layer>                 # in your own worktree; the layer's tip, no branch
# edit, mise run check, git commit
git update-ref refs/heads/<layer> HEAD <old-tip> &&
  git -C <worktree-holding-layer> reset --hard     # its index and files catch up with the branch
```

The `status` check comes first because once the branch moves, the other worktree still has the
old files checked out under it and `git status` there reports your commit reversed as staged
changes, so a check made afterward cannot tell those from real uncommitted work. `reset --hard`
discards anything uncommitted, and the `&&` keeps it from running when `<old-tip>` no longer
matches and `update-ref` refuses. Writing into another worktree may need approval. Then rebase the layers above onto the new tip and re-gate each layer, in its own worktree, with `mise run regate -- <layer below>` ([development.md](development.md#re-gating-a-branch-after-a-rebase)); regate keeps every tree, so rebasing a layer onto a re-gated one leaves its gate lines true. `gh stack add`
works only from the top branch of the stack, so run it in the worktree that holds the top.

### A low-integrity virtualenv

Seen once (2026-11-01): every `mise run` Python task failed with a bare `PermissionError`
(`WinError 5` on `mkdir`) while PowerShell wrote the same paths. The checkout root carried an
inheritable `Mandatory Label\Low`, which `.venv` inherited; `icacls .venv` shows it. The machine's
owner removes it with `icacls <checkout> /setintegritylevel (OI)(CI)M` and recreates `.venv`.
Evidence and sources: [the research note](../work/2026-11/windows-sandbox-integrity-label/windows-sandbox-integrity-label-2026-11-01.md).

## Windows PowerShell 5.1

Any harness that shells out through the host's Windows PowerShell 5.1 meets these; observed
under DeepSeek Harness (2026-10-25) and Claude Code (2026-10-31).

* **No `utf8NoBOM`.** `Set-Content -Encoding utf8NoBOM` fails with "Unable to match the
  identifier name utf8NoBOM to a valid enumerator name", and one sweep's writes all failed while
  the sweep kept going, which reads like "nothing to change". 5.1's `Set-Content` and `Out-File`
  also write CRLF. Write UTF-8 without a BOM and with LF through
  `[IO.File]::WriteAllText($path, $text, (New-Object System.Text.UTF8Encoding($false)))`, with
  `` "`n" `` as the only line break in `$text`, and read one file back before running such a
  write over many.
* **Commit messages from a file.** A here-string piped to `git commit -F -` does not reach git.
  Write the message with `WriteAllText` above and run `git commit -F <file>`.
* **Search with the Grep tool, not a shell.** A pattern with quotes in it does not survive 5.1's
  quoting into a native command's arguments intact; the harness's own search tool takes it as
  written.
* **Parse `gh` output with `ConvertFrom-Json`.** A `gh ... --jq '<expression>'` filter loses its
  quotes the same way; ask for `--json <fields>` and pipe it to `ConvertFrom-Json` instead.

## Adding another harness

Add a section when you have used the harness here, and state what it confines, what shell it
gives you, what it asks before running a command, where its settings live, and whether those
settings can be committed.
Do not assume a behaviour because a different harness has it. Split this page into
`docs/harness/<tool>.md` when a second section outgrows a screen.

## Where the settings live

| Harness | Settings | Ship with the checkout? |
| --- | --- | --- |
| DeepSeek Harness | `~/.dsh` on this host | no — host-local |
| Claude Code | [.claude/settings.json](../.claude/settings.json) plus `~/.claude/settings.json` | repo file yes, user file no |

A checkout cannot ship the DeepSeek Harness policy, so this page is the repository's record of
what it should be.
