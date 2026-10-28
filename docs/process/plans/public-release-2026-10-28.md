# Public release plan (2026-10-28)

Status: **in progress** (steps 1–5 landed; 6 and 7 remain). Source: the `/grill-with-docs` interview of 2026-10-28 (two rounds),
then a fact re-check against `origin/main` (`f87ea6e`) and the GitHub repository. This note owns the decisions and the landing log; the durable
decision is [ADR 0020](../../adr/0020-publish-through-a-fresh-scrubbed-repository.md).

Placeholders: `<parent>` is the folder holding the primary checkout, `<personal address>` is the maintainer's non-noreply email, `<noreply>` is
`49814+neilsh@users.noreply.github.com`, `<user>` is the Windows account name. Never write the
real values into a tracked file, commit message or PR.

## 1. Decisions

| # | Decision |
|---|---|
| Q10 | Publish a **scrubbed history to a fresh public `neilsh/stunt-reel`**. Rename the current private repository to `stunt-reel-archive` and keep it; delete it later only by a separate decision. |
| Q1 / Q14 | `git filter-repo` over **all** refs: map `<personal address>` to `<noreply>` for author **and committer**; replace the two machine paths in ADR 0019 with neutral placeholders, keeping the measurement. |
| Q2 | Only `main` goes public, pushed by explicit refspec. Never `--all`, `--mirror` or `--tags`. |
| Q16 | Bundle every ref, including remotes and the stash, to `<parent>\stunt-reel-archive\stunt-reel-all-refs.bundle`. Drop `review-dsh-friction` and `rea-eval` from the rewrite. Keep `wt-*` and `arch-*`. |
| Q17 | The rewritten history replaces the local one; see the open question C2 for how. |
| Q3 / Q11 | Ship `AGENTS.md`, the skills, `docs/harness*.md` and `docs/process/` as they are. The audit found only fixture values (`C:/Users/me/…`, `t@example.invalid`). |
| Q4 | Move `dosbox-*.conf` and `play_ctry.bat` to `tools/dosbox/` with a short README; delete `test_mcp.conf`. |
| Q5 | One cold, full `mise run check` on the exact commit that is pushed. |
| Q6 | No game-art screenshot at launch; a fixture-based render only, if any. |
| Q7 | Add `LICENSE-CC-BY-4.0`; pin `hatchling` in `[build-system]`. |
| Q8 | `NOTICE.md` lists every path of each game-derived table (3 palette copies, 1 scale table). |
| Q9 | Keep "reverse-engineering" in the README; amend ADR 0015 §5; fix "cleanroom" in `mise.toml`. |
| Q12 | Add `CONTRIBUTING.md` and a CI badge; no `CODE_OF_CONDUCT.md`; no `.mailmap` (the rewrite makes it moot). |
| Q13 | Pin actions to SHAs and fix the stale "advisory" sentence before the push; add a ruleset right after. |
| Q15 | Keep the `Co-Authored-By: Claude …` trailers. |

## 2. Double-check: corrections to the handoff

Re-checked on 2026-10-28 against `origin/main` and `gh`:

1. **The leak is wider than four merge commits.** `<personal address>` is the **committer** on 7
   more `main` commits (`a5ea6dd`, `fe3291d`, `9650c7d`, `91f94b1`, `e13d5ce`, `aca17ee`,
   `f87ea6e`): 11 commits on `main`, 242 across all refs. All 7 were committed today, after
   the 2026-10-25 rewrite, so the leak is **still active**. The repository config holds
   `<noreply>`; the global `~/.gitconfig` holds `<personal address>`, and the four PR merges
   took GitHub's account email. Until that is fixed, the next commit can put the address back
   (open question C1).
2. **Eight PRs are open** (#10–#17, the `arch-*` stack, some based on each other). Renaming the
   repository strands them (open question C3).
3. **The screenshot branch contradicts Q6.** `wt-202610260757-readme-screenshot` (`b576f47`)
   adds `docs/images/parity-ctry-capture-vs-render.png`, a capture of the original game beside
   the render, and its own ADR numbered `0017`, a number already taken on `main`. It stays local
   and unpublished.
4. **The stash is real work**: uncommitted edits to `tests/conftest.py`, `pytest_helpers.py`,
   `test_pytest_basetemp.py` and `test_scratch.py`. It goes into the bundle; it is not dropped.
5. **`git filter-repo` is not installed.** Install it with
   `mise exec -- uv tool install git-filter-repo` (the `uv` on `PATH` is 0.10.9, not the pinned one).
6. **The "cleanroom" line is `mise.toml:121`**, not 113.
7. **ADR 0015 §1 planned to flip visibility.** ADR 0020 amends §1 (fresh repository) as well as
   §5 (wording) instead of editing an accepted ADR.
8. **Q13's required-check list was wrong.** `windows` runs only on pushes to `main`, so requiring
   it would block every PR. The required checks are `quality`, `windows-smoke`, `msrv` and `deny`.
9. **Rulesets are unavailable while private** (HTTP 403 on the free plan), so they can only
   follow the publish, as decided. The `gh` token has `repo` and `workflow` but not `delete_repo`;
   renaming needs only `repo`.
10. **The remote has no secrets, webhooks, rulesets or issues**, and the wiki is off. Moving costs
    only the PR threads and Actions history, and those stay in the archive.
11. **Stale commit hashes in docs.** `research/parity/log.md` (25 lines), the salvage note (12),
    `research/formats/concepts/coordinates-and-units.md` (11) and `research/parity/method.md` (6)
    contain hex strings that may cite commits. After the rewrite, those hashes resolve only in the
    private archive (open question C4).
12. **Moving the DOSBox files reaches further than docs.** Defaults name `dosbox-parity.conf` in
    `capture_playone_reference.py`, `probe_playone_light.py` and `tac/session.py`, three tests
    assert it, `mise.toml` launches three of them, and `research/stunt-exe/sets.md` links
    `dosbox-utils.conf`. The configs mount `corpus/stisldem` relative to the working directory, so
    they keep working only if every launcher runs from the repository root. CI cannot exercise
    DOSBox, so this needs a local smoke run (step 5.2).
13. **All 15 linked worktrees are clean.** `mise run reap` removes only merged ones; 9 hold
    unmerged branches (8 `arch-*`, `neil/reduce-ci`).

## 3. Round-3 decisions (accepted 2026-10-28)

- **C1: Stop the leak at its source.** The leak has two separate causes:
  - The four two-parent, GitHub-signed PR merges (#4, #5, #6, #9) took the GitHub account's
    commit email. The fix is GitHub's *Keep my email addresses private* setting, which makes
    web merges, squashes and edits use `<noreply>`.
  - The seven single-parent, unsigned commits (PRs #2, #3, #7, #8, #18) were rebased locally and
    pushed. Rebasing keeps the author, but the committer came from the global `~/.gitconfig`, so
    the rebase ran where this repository's config did not apply. The fix is a global
    `user.email` of `<noreply>`, or `includeIf` blocks if other repositories need the personal
    address.
  - Also turn on *Block command line pushes that expose my email*. GitHub documents it as
    checking the author, so it would not have caught these committer-only leaks; a local
    `pre-push` hook that rejects any non-noreply author or committer covers the gap. Step 4.1's
    identity scan stays the pre-publish backstop.
- **C2: How the local checkout takes the new history.** Recommended **in-place**: detach each
  worktree, force-fetch the rewritten heads into the primary, check each branch out again (trees
  are identical except ADR 0019), delete the legacy refs and the stash, expire reflogs and `gc`.
  This keeps `<parent>\stunt-reel`, the data-root junctions and every orca worktree. The
  alternative, swapping in a fresh clone, means removing 9 unmerged worktrees by hand, which
  `reap` refuses.
- **C3: The 8 open PRs.** Recommended: after publishing, push the rewritten `arch-*` branches to
  the public repository and recreate PRs #10–#17 with the same bases. The rewrite scrubs those
  branches too, so this widens Q2 from "`main` only" to "`main` plus the live PR branches". The
  alternative is landing or closing them before the rewrite.
- **C4: Stale hashes in docs.** Recommended: a one-off script that uses filter-repo's
  `commit-map` to replace every old hash that has a new counterpart in those four files, landed as
  an ordinary commit. Public readers cannot reach the archive, so leaving the hashes stale would
  break those citations for them.

## 4. Steps

Run from `<parent>\stunt-reel` unless stated. In Git Bash set `export GIT_CONFIG_COUNT=0`; in
PowerShell `$env:GIT_CONFIG_COUNT=$null`. Steps 1–5 change nothing on GitHub.

### Step 1: Prepare (non-destructive)

1. C1 done by the maintainer.
2. Fast-forward `main` to `origin/main` (`f87ea6e`). This is the original "rebase onto
   `origin/main`" request; `neilsh/goldeye` is identical to the old `main` and fast-forwards too.
3. Install `git-filter-repo` (2.5).

### Step 2: Archive

1. `git bundle create <parent>\stunt-reel-archive\stunt-reel-all-refs.bundle --all`
   (`--all` includes `refs/remotes/*` and `refs/stash`).
2. `git bundle verify` it and compare `git bundle list-heads` with `git for-each-ref`.

### Step 3: Rewrite in a mirror

1. `git clone --mirror <parent>\stunt-reel <parent>\stunt-reel.rewrite.git`.
2. In the mirror, delete `refs/heads/review-dsh-friction`, `refs/heads/rea-eval`, `refs/stash`,
   `refs/remotes/*`, and `wt-202610260757-readme-screenshot` (it lives on in the bundle). Then
   `git for-each-ref` must list only `refs/heads/*`, with no `worktrees/*` or other leftover refs.
3. `git filter-repo --mailmap <scratch>/mailmap --replace-text <scratch>/redact.txt`, both files in
   the session scratchpad, never the repository:
   - `mailmap`: `<noreply> <personal address>`, which covers author and committer.
   - `redact.txt`: the literal worktree path in ADR 0019 line 12 becomes `<worktree>`, and
     `<parent>\stunt-reel` becomes `<primary checkout>`.
4. Keep `filter-repo/commit-map` and `ref-map` for C4 and step 7. If filter-repo rejects the
   mirror as not a fresh clone after the ref deletions, `--force` is safe here: the mirror is
   disposable.

### Step 4: Verify the rewrite

1. Identity: `git log --all --format='%ae%n%ce' | sort -u` shows only `<noreply>`,
   `noreply@github.com` and the dependabot noreply.
2. Content: `git log --all -i -E -G'<personal domain>|Users[\\/]+<user>|orca[\\/]+workspaces|E:[\\/]+git'`
   and the same pattern through `--grep` both print nothing. Keep the pattern in the scratchpad:
   the real domain must not land in this note.
3. Shape: the new `main` has the same commit count as the old one, and its tree differs from the
   old `main` tree only in ADR 0019 (fetch the bundle's `main` into a temporary ref, `git diff`,
   then delete the ref).

### Step 5: Cleanup commits on the rewritten `main`

Ordinary commits under `<noreply>`, made in a scratch clone of the mirror that is pointed at
`<parent>\stunt-reel.data` with `STUNT_DATA_ROOT`. Each step is one commit:

1. **Q4**: `git mv` the four configs and `play_ctry.bat` to `tools/dosbox/`; delete
   `test_mcp.conf`; update `mise.toml` (62, 69, 74), the three Python defaults, three tests,
   `docs/development.md` (90–103, 194) and `research/stunt-exe/sets.md`. Make `play_ctry.bat`
   `pushd` to the repository root. Add `tools/dosbox/README.md`.
2. **Q4 smoke run** (local, needs the corpus): `mise run play` launches; a `capture-ref` with
   `--out` inside the checkout completes (no `STUNT_DATA_WRITE` needed).
3. **Q7**: `LICENSE-CC-BY-4.0`; pin `hatchling` to the version uv resolves today.
4. **Q8**: `NOTICE.md` names `crates/stunt-core/src/contracts/palette.rs`,
   `python/stunt_reel/tac/palette.py`, `tests/fixtures/mode13h_palette.json` and
   `crates/stunt-core/src/sod/vm.rs`.
5. **Q9**: `mise.toml:121` "cleanroom isolation" becomes "asset isolation".
6. **Q12**: `CONTRIBUTING.md` (points to `AGENTS.md`, `mise run check`, the noreply rule, asset
   isolation) and a CI badge in `README.md`.
7. **Q13**: pin `actions/checkout`, `actions/cache`, `jdx/mise-action` and
   `taiki-e/install-action` to commit SHAs with a version comment; rewrite the last sentence of
   `docs/development.md:200`.
8. **ADR 0020** "Publish through a fresh, scrubbed repository": amends ADR 0015 §1 and §5 and
   marks 0015 as amended. Records the rejected visibility flip (open PR merges keep the address).
9. **C4** hash-citation script, if accepted.
10. This plan note, with the landing log filled in.

Then: a **cold** `mise run check` (clear `target/`; about 11 minutes) on the final commit, then
step 4.1–4.2 again over the new commits, then push the scratch clone's `main` back to the
mirror, so the mirror holds exactly what step 6 publishes and step 7 fetches.

### Step 6: GitHub (asks before each command)

1. `gh repo rename stunt-reel-archive -R neilsh/stunt-reel`.
2. `gh repo create neilsh/stunt-reel --public --disable-wiki --description "<current description>"`.
3. `git push https://github.com/neilsh/stunt-reel.git main:main` from the scrubbed clone. One
   refspec only.
4. Watch the first CI run go green; turn on Dependabot alerts and security updates.
5. Add a ruleset on `main`: require `quality`, `windows-smoke`, `msrv` and `deny`, and block force
   pushes.
6. C3: push the rewritten `arch-*` branches and recreate PRs #10–#17 with their stacked bases.

### Step 7: Local cutover (C2, in place)

1. In each linked worktree, `git switch --detach`.
2. In the primary, `git fetch --force <parent>\stunt-reel.rewrite.git 'refs/heads/*:refs/heads/*'`,
   then `git remote set-url origin https://github.com/neilsh/stunt-reel.git` and `git fetch origin`.
3. In each worktree, `git switch <its branch>`. The status should be clean; ADR 0019 differs only
   where the branch contains it.
4. Delete the legacy refs, `refs/stash`, the screenshot branch and `refs/remotes/origin/*` from the
   old remote; `git reflog expire --expire=now --all`, `git gc --prune=now`.
5. Re-run step 4.1–4.2 in the primary. Remove `<parent>\stunt-reel.rewrite.git` and the scratch
   clone after confirming.

### Rollback

Until step 6.1, deleting the mirror and scratch clone undoes everything. Between 6.1 and 6.2,
renaming `stunt-reel-archive` back restores the original. After 6.2 the new repository takes
the name and GitHub's redirect from the old URL ends, so a rollback first deletes the new
repository (which needs the `delete_repo` scope) and then renames the archive back. Until step 7,
the local checkout is untouched; after it, the bundle restores every local ref.

## 5. Landing log

| Step | Date | Result |
|---|---|---|
| 1.1 (C1, local half) | 2026-10-28 | Global `user.email` set to `<noreply>`. Untracked `.git/hooks/pre-push` installed, shared by all linked worktrees. Tested: it rejects `0027a44..f87ea6e` (2 offenders) and passes a clean range, a new branch already on the remote, and a deletion. The GitHub email settings are still for the maintainer to turn on. |
| 1.2 | 2026-10-28 | `main` (primary) and `neilsh/goldeye` (`prep-public-repo` worktree) fast-forwarded to `origin/main` `f87ea6e`, which completes the original "rebase onto `origin/main`" request. Both working trees were clean apart from this untracked note. |
| 1.3 | 2026-10-28 | `git-filter-repo` 2.47.0 installed with `mise exec -- uv tool install` (pinned uv 0.13.1) into `~/.local/bin`; `git filter-repo --version` works. |
| 2 | 2026-10-28 | `<parent>\stunt-reel-archive\stunt-reel-all-refs.bundle`, 2.2 MB, sha256 `f5152d62…9c25fab3`. `git bundle verify` reports a complete history. All 47 local refs match by hash, including `refs/stash`, both legacy lineages, the screenshot branch and the 15 `refs/remotes/origin/*`. It also holds 15 `worktrees/*/HEAD` pseudo-refs, which are harmless. A mirror clone of the bundle passes `fsck --connectivity-only` and holds 608 commits, the same as the source. The bundle contains `<personal address>`: never upload it. |
| 3 | 2026-10-28 | Mirror `<parent>\stunt-reel.rewrite.git`, cloned with `--no-local`: a plain local clone hardlinks objects, and filter-repo rejects it as not fresh, so `--force` was not needed. Pruned to 27 `refs/heads/*` and nothing else (369 commits). Before the rewrite, only `f87ea6e` (ADR 0019) in the kept refs touched a machine path. `git filter-repo --mailmap --replace-text`, with both files in the session scratchpad. The redaction keeps the drive letters because the C:-versus-E: split is the measurement's context: the lines now read `C:\<worktree pool>\stunt-reel\worktree-init-perf` and `E:\<primary checkout>`. 15 refs changed (`main`, `goldeye`, the 8 `arch-*`, `neil/reduce-ci`, `ci-stacked-prs`, `dace`, `selkie`, `shrimp`); the 9 `wt-*` and `cleanup`/`fluke`/`whelk` predate the leaks. `filter-repo/suboptimal-issues` lists 9 hash-like strings in commit messages with no counterpart: pre-existing dangling hashes and `wt-` timestamps, not caused by this rewrite. |
| 4 | 2026-10-28 | Identities: only `<noreply>` (733), `noreply@github.com` (4, GitHub merge committers) and the dependabot noreply (1). Path, username and domain scans over diffs and messages print nothing. Of 369 mapped commits, exactly one tree differs (`f87ea6e`, the tip). Every ref has the same commit count as before (`main` 309 = 309). `main` differs from `f87ea6e` only in ADR 0019 (2 lines). |
| 5 | 2026-10-28 | Scratch clone `<parent>\stunt-reel.publish`, `mise run init` with `STUNT_DATA_ROOT=<parent>\stunt-reel.data`; it now holds data-root junctions, so remove it with `mise run reap` or by unlinking them first, never with a recursive delete (ADR 0018). Six commits: the Q4 move; legal (CC BY text, NOTICE paths, `hatchling==1.33.0`, "asset isolation"); CI (SHA pins `checkout` v7.0.1, `cache` v6.1.0, `mise-action` v5.2.4, `install-action` v2.88.0, the required-check paragraph); `CONTRIBUTING.md` and badge; ADR 0020 with 0015 marked amended; this note. C4 was a no-op: 29 commits changed hash, and no tracked file cites any of them. |
| 5 gate | 2026-10-28 | Cold run with no `target/`: 8/9 passed, including the cold Rust build and both test suites; `fmt-check-py` failed on the lengthened `probe_playone_light.py` default. After `mise run fmt-py`: **PASS 9/9**. |
| 5.2 | 2026-10-28 | **Not run.** `capture-ref` could not bind `127.0.0.1:58991` (WinError 10013): the port lies in a Windows excluded range (58949–59048, `netsh interface ipv4 show excludedportrange protocol=tcp`), not in use by DOSBox-X. Restarting `winnat` as admin frees it. The moved paths are covered by `test_tac_capture_session.py` (defaults) and the staging code resolving `--conf` against the repo root. To finish it: `mise run capture-ref -- --out build/scratch/smoke-capture --max-frames 3`. |
| 6.1 | 2026-10-28 | `neilsh/stunt-reel` renamed `neilsh/stunt-reel-archive`; still private, with its 8 open PRs. |
| 6.2–6.3 | 2026-10-28 | Public `neilsh/stunt-reel` created (wiki off, same description). Only `refs/heads/main` (`faf6d26`) was pushed, by explicit refspec. `git ls-remote` showed `HEAD` and `main` only. |
| 6.4 | 2026-10-28 | Dependabot alerts and security updates on; private vulnerability reporting on, because `SECURITY.md` points reporters at it. Secret scanning and push protection were on by default. First CI run on `main`: Ubuntu gate, Windows gate, MSRV and dependency policy all succeeded; Windows smoke is skipped on pushes by design. Dependabot's `uv` updater fails with `tool_version_not_supported`: its bundled uv rejects `required-version = "==0.13.1"`. This predates the release and is a follow-up. |
| 6.6 (C3) | 2026-10-28 | The 8 rewritten `arch-*` branches pushed by explicit refspecs. Archive PRs recreated with the same titles, bodies and bases, in stack order so cross-references could be rewritten: #10→#1, #11→#2, #12→#3, #15→#4, #17→#5, #13→#6 (on #1), #14→#7 (on #2), #16→#8 (on #7). The bodies were scanned first: no addresses, paths or hashes. `arch-01` adds an ADR numbered 0019 and `arch-05` one numbered 0020, and both numbers are now taken on `main`, so renumber them before merging. |
