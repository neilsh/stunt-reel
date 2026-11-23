# Run the class agreement batch

The batch measures where the GPU and the canonical lavapipe draw the reference films differently, and pins it in [`expected/agreement.toml`](../../research/parity/expected/agreement.toml) beside the GPU's expected scores ([ADR 0055](../adr/0055-fidelity-pins-on-lavapipe-and-agreement-is-measured-apart.md)).
It runs on local-windows, which has both: the GPU natively, and the canonical lavapipe in a WSL distro set up as [`render-on-lavapipe.md` § 5](render-on-lavapipe.md#5-render-the-canonical-lavapipe-under-wsl) says, its clone at `~/stunt-reel` with its own data root.

## 1. See whether one is due

`mise run queue` prints `agreement batch due: <reason>` after 5 commits on `main` that change the renderer since the pinned `crates` tree, or 7 days after the pinned date once one has landed.

## 2. Run it

From the primary checkout, with no other render running:

```powershell
mise run agreement -- batch --wsl Ubuntu-24.04
```

It fetches `origin/main` into the worktree `.agents/worktrees/agreement` (detached; made on the first run), renders the seven films there on the GPU and in the distro's clone on lavapipe, from the same commit, and measures the two.
It skips, exit 0, while a `stuntreel` process runs.
When nothing flags it repins `gpu.toml` and `agreement.toml` on a branch `chore/agreement-<tree>` and opens a `chore(parity): repin class agreement` pull request.

`--if-due` stops after the fetch unless a batch is due, and skips a tree already measured or whose pin branch is on `origin`.
`--post` comments the result on the open issue titled `Class agreement batch` (opening it when none is open), once per tree, and files an `area:class-agreement` issue for each flag no open one covers.

## 3. Pin over flags or a changed pair

The batch pins nothing when a film flags, when nothing is pinned yet, or when either adapter or driver changed since the pin; it prints why.
Read the flags; file an issue for a real regression, or accept the measurement with a reason, from the worktree, where the measurement is kept:

```powershell
cd .agents/worktrees/agreement
mise run agreement -- pin --accept "<reason>"
```

The reason lands in `agreement.toml`'s `accepted` and in the pull request, so agreement never loosens without one.

## 4. Schedule it

A nightly task runs it unattended (the owner turns it on; until then the batch runs by hand):

```powershell
schtasks /Create /SC DAILY /ST 03:00 /TN stunt-reel-agreement /TR "pwsh -NoProfile -Command \"Set-Location E:\git\stunt-reel; mise run agreement -- batch --wsl Ubuntu-24.04 --if-due --post\""
schtasks /Query /TN stunt-reel-agreement
```

Use the primary checkout's own path in place of `E:\git\stunt-reel`.
`schtasks /Delete /TN stunt-reel-agreement /F` removes it.
