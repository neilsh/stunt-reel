# Environment: local-windows

Part of the [`working-in-an-environment`](SKILL.md) skill.

The owner's Windows machine, the primary checkout and its worktrees. Work labelled `local-only` ([`triage-labels.md`](../../../docs/agents/triage-labels.md#environment-roles)) is done here.

- **Has:** an RTX 4070 GPU, lavapipe beside it ([`render-on-lavapipe.md`](../../../docs/howto/render-on-lavapipe.md)), DOSBox and DOSBox-X, the full data root ([`managing-worktrees`](../managing-worktrees/SKILL.md)), Orca with dsh and Antigravity workers ([`harness.md`](../../../docs/harness.md)), the owner's `wrangler login`, and a `gh` that speaks GraphQL and `--attach`.
- **Shell:** Windows PowerShell 5.1 under every harness: its quoting, encoding and chaining rules are in [`harness.md` § Windows PowerShell 5.1](../../../docs/harness.md#windows-powershell-51).
- **Disk:** checkouts, worktrees and the data root share one drive; check its free space with `(Get-PSDrive <letter>).Free / 1GB` and tidy with `mise run reap` ([`managing-worktrees`](../managing-worktrees/SKILL.md)).
