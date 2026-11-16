# Environment: cloud

Part of the [`working-in-an-environment`](SKILL.md) skill.

A Claude Code cloud session: a Linux container with its own 30 GB disk, set up and given the game archives by the SessionStart hook ([`cloud-sessions.md`](../../../docs/cloud-sessions.md)). The evidence for each limit below is in [`cloud-sessions.md` § What a cloud session cannot do](../../../docs/cloud-sessions.md#what-a-cloud-session-cannot-do).

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
| Arm or disarm auto-merge | the proxy's `repos/{owner}/{repo}/pulls/<n>/ccr/auto_merge` route, in place of `gh pr merge --auto` and `--disable-auto`; the proxy's 403 reply to the `gh pr merge` command names its method and fields |

A stacked PR can be neither merged nor armed here: keep a dependent change unstacked, started once its parent merges.

## Rendering

Renders run on lavapipe, which scores within 0.002 of the GPU on all seven reference films ([`lavapipe.md` § 4](../../../research/parity/lavapipe.md#4-lavapipe-beside-the-gpu-on-one-crates-tree)): render, score, judge and adopt as on the GPU. The exception is where lavapipe's residues lie ([§ 5](../../../research/parity/lavapipe.md#5-what-still-differs)): a change to depth testing or depth bias (`crates/stunt-render/src/pipeline.rs`), to draw order, or to how `shade` is interpolated (`shade` and `shade_perspective` in `crates/stunt-render/src/shaders/mode13h.wgsl`). Its PR opens with lavapipe's scores, says in its body that it needs `mise run judge` on the GPU, and takes `local-only` instead of being armed.

`gh` has no `--attach` here, so a PR's comparison pictures are committed: [`pr-evidence.md`](../improving-render-parity/pr-evidence.md) step 6 says where.

## Handing work to local-windows

The session lacks DOSBox and DOSBox-X, GPU timing, Orca, dsh and Antigravity, the owner's `wrangler login`, and the data-root files no cloud archive holds: the full game's music, `corpus/siarchive` beyond FreeFlight, and captures `references.toml` does not pin, such as `vault-brett` ([`manifests/cloud-assets.toml`](../../../manifests/cloud-assets.toml)). Work that needs one goes to [`local-windows`](local-windows.md):

- **An issue** keeps its state label (`ready-for-agent` when its body says exactly what to run there, otherwise `needs-triage`) and gains `local-only`; the body names the resource.
- **A PR** gains `local-only`, and its body names the check left to run.

`ready-for-human` is for a decision only a person makes.
