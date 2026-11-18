# Environment: cloud

Part of the [`working-in-an-environment`](SKILL.md) skill.

A Claude Code cloud session: a Linux container with its own disk (30 GB, per the owner, 2026-11-16), set up and given the game archives by the SessionStart hook ([`cloud-sessions.md`](../../../docs/cloud-sessions.md)). The evidence for each limit below is in [`cloud-sessions.md` § What a cloud session cannot do](../../../docs/cloud-sessions.md#what-a-cloud-session-cannot-do).

## GitHub: REST only

The proxy answers GraphQL with 403, so `gh issue`, `gh pr`, `gh repo view` and `gh api graphql` fail. Reach GitHub through `gh api` REST routes:

- **Issues, labels, comments, search:** the `(cloud: …)` form beside each operation in [`issue-tracker.md`](../../../docs/agents/issue-tracker.md).
- **Review threads:** `mise run pr-threads`, which uses the proxy's `ccr/review_threads` routes.
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
| Squash-merge a green PR | `gh api -X PUT repos/{owner}/{repo}/pulls/<n>/merge -f merge_method=squash -f sha=<head SHA> -f commit_title='<PR title> (#<n>)'`, with the full head SHA from `gh api repos/{owner}/{repo}/pulls/<n> --jq .head.sha`. `sha` refuses the merge if the head moved since it was checked; with no `commit_message`, GitHub's default squash body applies (worked 2026-11-18, #706) |
| Arm or disarm auto-merge | the proxy's `repos/{owner}/{repo}/pulls/<n>/ccr/auto_merge` route, which it names in place of `gh pr merge --auto` ([`cloud-sessions.md`](../../../docs/cloud-sessions.md#what-a-cloud-session-cannot-do)); its method and body for arming and disarming are not yet recorded: record them in this row the first time they work |

A stacked PR can be neither merged nor armed here: keep a dependent change unstacked, started once its parent merges.

## Rendering

Renders run on lavapipe, which scored within 0.002 of the GPU on all seven reference films on the one `crates` tree [`lavapipe.md` § 4](../../../research/parity/lavapipe.md#4-lavapipe-beside-the-gpu-on-one-crates-tree) measured: render, score, judge and adopt on it. The exception is where lavapipe's residues lie ([§ 5](../../../research/parity/lavapipe.md#5-what-still-differs)): a change to depth testing or depth bias (`crates/stunt-render/src/pipeline.rs`), to the vertex transform, projection or clipping, to draw order, or to how `shade` is interpolated (`shade` and `shade_perspective` in `crates/stunt-render/src/shaders/mode13h.wgsl`). Its PR opens with lavapipe's scores, says in its body that it needs `mise run judge` on the GPU, and takes `local-only` instead of being armed. Work whose result turns on single pixels of our render, rather than on a score (a `background` band in `references.toml`, which admits an index only when no actor pixel of ours carries it), goes to local-windows: lavapipe differs from the GPU by 23 to 147 index-plane pixels per tick, averaged over each film (§ 5).

`gh` has no `--attach` here, so a PR's comparison pictures are committed: [`pr-evidence.md`](../improving-render-parity/pr-evidence.md) step 6 says where.

## Handing work to local-windows

The session lacks DOSBox and DOSBox-X, GPU timing, Orca, dsh and Antigravity, the owner's `wrangler login`, and the data-root files no cloud archive holds: the full game's music, `corpus/siarchive` beyond FreeFlight, and captures added since the `captures` archive was last packed ([`manifests/cloud-assets.toml`](../../../manifests/cloud-assets.toml)). Work that needs one goes to [`local-windows`](local-windows.md):

- **An issue** gains `local-only` and swaps its state label (`in-progress` once claimed) for `ready-for-agent` when its body says exactly what to run there, otherwise `needs-triage`; the body names the resource.
- **A PR** gains `local-only`, and its body names the check left to run.

`ready-for-human` is for a decision only a person makes.
