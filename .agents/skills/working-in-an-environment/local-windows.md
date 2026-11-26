# Environment: local-windows

Part of the [`working-in-an-environment`](SKILL.md) skill.

The owner's Windows machine, the primary checkout and its worktrees.
Work labelled `env:local-only` ([`triage-labels.md`](../../../docs/agents/triage-labels.md#environment-roles)) is done here.

- **Has:** an RTX 4070 GPU, lavapipe beside it ([`render-on-lavapipe.md`](../../../docs/howto/render-on-lavapipe.md)), DOSBox and DOSBox-X, the full data root ([`managing-worktrees`](../managing-worktrees/SKILL.md)), Orca with dsh and Antigravity workers ([`harness.md`](../../../docs/harness.md)), the owner's `wrangler login`, and a `gh` that speaks GraphQL and `--attach`.
- **Lavapipe pins:** the local llvmpipe (Mesa 25.2.8, `llvmpipe (LLVM 21.1.7, 256 bits)`) is not the adapter `expected/lavapipe.toml` pins (`LLVM 20.1.2`, measured in the cloud), so `mise run parity` reports `not comparable: other adapter`.
  Repin `lavapipe` from the canonical lavapipe under WSL ([`render-on-lavapipe.md` § 5](../../../docs/howto/render-on-lavapipe.md#5-render-the-canonical-lavapipe-under-wsl)), which draws the pinned adapter's pixels on this machine; no PR repins `gpu`, which only the class agreement batch writes ([ADR 0055](../../../docs/adr/0055-fidelity-pins-on-lavapipe-and-agreement-is-measured-apart.md)).
- **Shell:** Windows PowerShell 5.1 under every harness: its quoting, encoding and chaining rules are in [`harness.md` § Windows PowerShell 5.1](../../../docs/harness.md#windows-powershell-51).
- **Disk:** checkouts, worktrees and the data root share one drive; check its free space with `(Get-PSDrive <letter>).Free / 1GB` and tidy with `mise run reap` ([`managing-worktrees`](../managing-worktrees/SKILL.md)).
