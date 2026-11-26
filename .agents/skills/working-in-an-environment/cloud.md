# Environment: cloud

Part of the [`working-in-an-environment`](SKILL.md) skill.

A Claude Code cloud session: a Linux container with its own disk (30 GB, per the owner, 2026-11-16; `df /` read 29 GB used and 11 GB available at 12:13 UTC on 2026-11-18), set up and given the game archives by the SessionStart hook ([`cloud-sessions.md`](../../../docs/cloud-sessions.md)).
The evidence for each limit below is in [`cloud-sessions.md` § What a cloud session cannot do](../../../docs/cloud-sessions.md#what-a-cloud-session-cannot-do).

## GitHub: REST only

The proxy answers GraphQL with 403, so `gh issue`, `gh pr`, `gh repo view` and `gh api graphql` fail.
Reach GitHub through `gh api` REST routes:

- **Issues, labels, comments, search:** the `(cloud: …)` form beside each operation in [`issue-tracker.md`](../../../docs/agents/issue-tracker.md).
- **Review threads:** `mise run pr-threads`, which uses the proxy's `ccr/review_threads` routes.
- **Merge bar:** `mise run merge-bar -- <n>`, which reads the PR, its check runs and its comments through REST here.
- **Pages:** ask for `per_page=100&page=<n>` until a page comes back short; `gh api --paginate` fails on its second page.
- **Pull requests:**

| Operation | Command |
|---|---|
| Open | `gh api -X POST repos/{owner}/{repo}/pulls -f title='<subject>' -f head=<branch> -f base=main -F body=@build/scratch/<name>.md` |
| Edit the body | `gh api -X PATCH repos/{owner}/{repo}/pulls/<n> -F body=@build/scratch/<name>.md` |
| Head SHA | `gh api repos/{owner}/{repo}/pulls/<n> --jq '.head.sha[0:7]'` |
| State (Shutdown's merged or closed) | `gh api repos/{owner}/{repo}/pulls/<n> --jq '[.state, .merged] \| @tsv'` |
| Comment | `gh api -X POST repos/{owner}/{repo}/issues/<n>/comments -F body=@build/scratch/<name>.md` |
| Labels | the issue label routes in `issue-tracker.md`; a PR shares its issue number |
| Arm auto-merge | the GitHub MCP tool `enable_pr_auto_merge` (`mergeMethod: SQUASH`) while checks are pending |
| Merge directly | `merge_pull_request` (squash, `expectedHeadSha` = the reviewed head) when the merge state is `clean`, which `enable_pr_auto_merge` refuses |
| Disarm | the MCP tool `disable_pr_auto_merge`, untested: record it the first time it works |

`enable_pr_auto_merge` also refuses a PR that is `unstable` because of a stale cancelled `PR title` check run, or while `build` is still running: re-run that check, or wait for the running one, then retry; `merge_pull_request` merged such PRs once their checks finished.

A stacked PR can be neither merged nor armed here: keep a dependent change unstacked, started once its parent merges.

The auto mode's permission classifier may refuse a force-push, so merge `origin/main` into a pushed PR branch instead of rebasing it ([`pr-and-filing.md`](../running-unattended/pr-and-filing.md) step 1).
The proxy refuses ref deletes, so a session cannot delete a remote branch: create no throwaway branch on the remote, and leave a stray one to the owner.

## Rendering

Renders run on the canonical lavapipe, the one `expected/lavapipe.toml` is pinned on: render, score, judge, adopt and repin on it, pixel-level work such as a `background` band in `references.toml` included, and arm the PR like any other ([ADR 0055](../../../docs/adr/0055-fidelity-pins-on-lavapipe-and-agreement-is-measured-apart.md)).
No PR waits for the GPU: where lavapipe and the GPU draw differently is measured apart, by the class agreement batch on local-windows ([`run-the-agreement-batch.md`](../../../docs/howto/run-the-agreement-batch.md)).
When a sweep's stderr ends a film's line with `check it on the GPU`, more than half of that film's SSIM gain sits on the batch's pinned hot ticks, where it may be fitting a lavapipe quirk: say so in the PR body; the verdict stands, and the next batch shows whether the GPU moved.

`gh` has no `--attach` here, so a PR's comparison pictures are committed: [`pr-evidence.md`](../improving-render-parity/pr-evidence.md) step 6 says where.

## Handing work to local-windows

The session runs dosbox-automation, so `capture-ref` and `make-all` run here as working output ([`cloud-sessions.md` § Running the emulator](../../../docs/cloud-sessions.md#running-the-emulator)), when the environment's data root lies outside `/root`.
It lacks DOSBox-X (`debug-x`), a window for `play`, GPU timing, Orca, dsh and Antigravity, the owner's `wrangler login`, and the data-root files no cloud archive holds: the full game's music, `corpus/siarchive` beyond FreeFlight, and captures added since the `captures` archive was last packed ([`manifests/cloud-assets.toml`](../../../manifests/cloud-assets.toml)).
Work that needs one goes to [`local-windows`](local-windows.md):

- **An issue** gains `env:local-only` and swaps its state label (`status:in-progress` once claimed) for `status:ready-for-agent` when its body says exactly what to run there, `status:needs-plan` when it needs local planning, otherwise `status:needs-triage`; the body names the resource.
- **A PR** gains `env:local-only`, and its body names the check left to run.

`status:ready-for-human` is for a decision only a person makes.
