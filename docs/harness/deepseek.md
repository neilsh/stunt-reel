# DeepSeek Harness

What DeepSeek Harness (dsh) confines, asks and gives you on this host, observed by use; the [policy for every agent](../harness.md#policy-any-agent) is in `docs/harness.md`, and setting dsh up is in [`harness-setup.md` § DSH](../harness-setup.md#dsh).

Observed on this host 2026-10-25.

| Mode | Read | Write | Typical use |
| --- | --- | --- | --- |
| `read-only` | yes | no | inspecting a worktree you do not own |
| `workspace-write` | yes | inside the workspace only | the default for a normal session |
| `danger-full-access` | yes | anywhere the user can write | builds and tool installs that live outside the checkout |

The mode is visible in every `run_code` result footer as `File sandbox: <mode>`, and `enforcement: partial` means the host could not confine every operation.
A mode change mid-program aborts that program; re-run it rather than assuming it half-completed.

## What `workspace-write` cannot do here

Confirmed by failure on 2026-10-25, not by reading the packaged sources:

* `mise run` used to repair its pinned Rust toolchain under `%LOCALAPPDATA%\mise` on every invocation, because `components = "llvm-tools-preview"` does not match the component rustup reports (`llvm-tools-x86_64-pc-windows-msvc`), and `workspace-write` denied that write (`failed create_dir_all: ...\mise\downloads\rust\1.99.1: Access is denied (os error 5)`).
  The pin is now `llvm-tools`, which verifies clean, so a plain `mise run` no longer attempts the install.
  If it returns, run `mise install` once outside the sandbox; `MISE_DISABLE_TOOLS=rust` with the installed toolchain's `bin` on `PATH` remains a fallback.
* Directory ACLs are only partially enforced: a directory created under the sandbox can refuse a later nested creation inside it, and a stale one can refuse removal.
* A directory created with `mkdir(mode=0o700)` cannot be listed or removed by the process that created it, although Windows ignores the mode. pytest creates every temporary root that way; [`tests/conftest.py`](../../tests/conftest.py) installs a Windows-only `os.mkdir` shim that drops the mode, so the gate's Python half runs under `workspace-write`.
* `cargo` writes `target/` inside the checkout, so a warm build is fine once the toolchain resolves.
  `uv`'s cache is the primary checkout's `.cache/uv` by absolute path (ADR 0013, ADR 0036), which is outside a worktree's workspace.

A denied gate is an environment symptom before it is a code symptom.

## Temporary directories

The sandbox also denies the OS temp directory to the processes the tests spawn: a gate run whose `TMP` and `TEMP` pointed at the user's temp directory panicked in the `test-rust` step with `create temp dir: Os { code: 5, kind: PermissionDenied, message: "Access is denied." }`, and `pytest` hit `PermissionError: [WinError 5]` under DSH's own per-session temp path — so that directory is not a dependable exception either.

`mise.toml` used to point `TMP` and `TEMP` into the shared cache for this; since [ADR 0036](../adr/0036-worktrees-reach-shared-state-by-configuration.md) tasks use the OS temp directory, and a DSH session runs `mise run` tasks under `danger-full-access` ([harness-setup.md](../harness-setup.md#dsh)).
A `workspace-write` run that cannot avoid it can still set the variables in the same call, because each `pwsh` call is a fresh process:

```powershell
New-Item -ItemType Directory -Force target\tmp | Out-Null; $env:TMP = "$PWD\target\tmp"; $env:TEMP = $env:TMP; cargo test --workspace --all-features
```

## Approvals

Each operation the policy does not pre-approve stops and waits, and a wait that outlives the program's deadline returns as `deadline reached` — which names the symptom and not the cause.
Cancelling is not free either: the operation is abandoned and the next step usually retries it.

* **Pre-approve `mise run *`.**
  That is why every agent-facing script has a task.
* **Keep the timeout short** (about 90 s) so a blocked command returns as a decision.
* **Surface the reason.**
  `blocked: awaiting approval — <reason>` is actionable; `deadline reached` is not.

## Timeouts

`run_code` defaults to a 120 s deadline and accepts `timeoutMs` up to a hard cap of 600 s.
Pass `timeoutMs` for a step known to be slow but bounded — a cold build, a sweep, a capture — rather than let it die at 120 s.
For anything not known to finish inside about 60 s, start it as a background job (`run_in_background`) and collect it with `job_output`: no deadline applies to a job, and it outlives the program that started it.
Start a command that might hang in the background from the first call — a `git filter-branch` once consumed the full 600 s and left the repository untouched.

## The shell it gives you

Commands run through Windows PowerShell 5.1 (`5.1.26100`), one fresh `pwsh -Command` per call: `$env:` assignments, functions, variables and `Push-Location` do not survive into the next call, so a setup step and the command that needs it belong in the same call.
Its 5.1 pitfalls are in [Windows PowerShell 5.1](../harness.md#windows-powershell-51), because every harness that shells out through it meets them.

## Delegation

A `subagent` is spawned with an id and reports back when it finishes; `send_message` addressed to that id failed with `active teammate "<id>" not found` (`TEAM_MEMBER_NOT_FOUND`), so nothing can be added to its instructions after it starts.
Treat the brief as the whole instruction — goal, paths it may read, output shape and stopping condition — because there is no second one.

## Teammates

Agent Teams share the Lead's checkout.
The [policy](../harness.md#policy-any-agent) still applies: only one member writes at a time, and the Lead is the default writer.
Teammates may read, design, review and return patches.
If the Lead assigns independent tickets, it creates one worktree per writer from its current `HEAD`; each writer commits only on that branch and the Lead integrates it, never the teammate.
A shared file (`AGENTS.md`, `docs/harness.md`, `mise.toml`, `tests/conftest.py`) folds the tickets into one writer regardless of file scope.

## Reading and editing

* A file must be read in the session before it can be edited, and the read is per checkout path: reading a file in the primary checkout does not authorise the same path in a worktree.
* `edit` returns the affected region, and a large edit returns both the old and new text, so editing a 13 KB file can add ~27 KB to the conversation.
  Prefer several small edits.
* `grep` over temp paths can fail on non-UTF-8 paths; that is a ripgrep input error, not a policy denial.
