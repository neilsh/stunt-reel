# Environment: cloud-antigravity

Part of the [`working-in-an-environment`](SKILL.md) skill.

An Antigravity cloud session: a non-root (`uid=1000`, `antigravity`) Debian 12 (`bookworm`) microVM with a read-only `/`, `/home/antigravity` (19 GB XFS, persists across sleep/wake), and `/tmp` (overlay, resets on sleep/wake), observed 2026-11-18.

## Bootstrap and shell

- [`.agents/environment.json`](../../../.agents/environment.json) runs `bash .claude/cloud-setup.sh --antigravity`, installing `mise` into `~/.local/bin/mise`, pointing `RUSTUP_HOME` to `~/.local/share/mise/rustup` and `CARGO_HOME` to `~/.local/share/mise/cargo` (overriding the read-only `/usr/local/rustup`), installing the locked toolchain and `.venv`, and unpacking Debian `bookworm-backports` `mesa-vulkan-drivers` (`25.0.7-2~bpo12+1`, `libllvm15`) into `~/.local/share/lavapipe`.
- Each `run_command` starts a fresh non-interactive `bash` sourcing `~/.bashrc` via `BASH_ENV`, where `--antigravity` puts `~/.local/share/mise/shims` and `~/.local/bin` ahead of `/usr/local/bin` and exports `RUSTUP_HOME`, `CARGO_HOME`, `MISE_AUTO_INSTALL`, `MISE_USE_VERSIONS_HOST`, `MISE_LOCKED`, `STUNT_DATA_ROOT`, `VK_DRIVER_FILES` and `VK_ICD_FILENAMES`.
  The base image's `/usr/local/bin/uv` (`0.13.8`) stays further down `PATH`, so `mise run init` or `ensure` may warn about it while `mise run check` passes.
- `.claude/settings.json` `SessionStart` hooks do not run here (`CLAUDE_CODE_REMOTE` is unset); project-local `/home/antigravity/env-setup.sh` fetches the pinned archives from Google Drive via `gdrive` into `$STUNT_DATA_ROOT` (`~/stunt-reel.data`) and runs `mise run game-builds` and `mise run superset-all`.

## GitHub

`gh` (`2.103.3`) runs through `agy-plugin-proxy` with GraphQL enabled (`gh pr create` and `gh pr checks` worked on #799, 2026-11-18).
The VM clones with a single-branch refspec (`+refs/heads/main:refs/remotes/origin/main`), so checking out another PR's branch into a detached review worktree fetches it explicitly (`git fetch origin <branch> && git worktree add --detach <path> FETCH_HEAD`).
Image uploads with `gh --attach` through `agy-plugin-proxy` are untested here; commit comparison pictures as [`pr-evidence.md`](../improving-render-parity/pr-evidence.md) step 6 directs if uploads are blocked.

## Rendering

Renders run on user-space `bookworm-backports` lavapipe (`25.0.7-2~bpo12+1` with `libllvm15`).
`mise run test-gpu` passes (39 passed, 1 ignored on #799, 2026-11-18) and `mise run sweep` works for relative comparisons, while `mise run parity` reports `not comparable: other adapter` against `expected.lavapipe`'s `"llvmpipe (LLVM 20.1.2, 256 bits)"` (`ctry` scored `0.9188` SSIM / `0.9910` IoU, `+0.0000001` from the pinned row).
Follow [`cloud.md` § Rendering](cloud.md#rendering) when a change needs the GPU or `expected.lavapipe` verification, marking such PRs `local-only`.

## Handing work to local-windows

This VM runs `dosbox-automation`, so `capture-ref` and `make-all` are available when `$STUNT_DATA_ROOT` is outside `/root`.
Work that needs an RTX 4070 GPU, `expected.gpu` or `expected.lavapipe` repinning, DOSBox-X (`debug-x`), interactive `play`, Orca, dsh, `wrangler login`, or unarchived corpus files goes to [`local-windows`](local-windows.md) with the `local-only` label.
