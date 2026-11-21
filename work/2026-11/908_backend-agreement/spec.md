# Pin fidelity on lavapipe and measure class agreement separately

Design agreed with the owner in the project thread of 2026-11-21; the plan is [`plan.md`](plan.md).

## Problem

A render PR in the classes [`cloud.md` § Rendering](../../../.agents/skills/working-in-an-environment/cloud.md#rendering) lists (depth testing or bias, the vertex transform, projection or clipping, draw order, `shade` interpolation) waits unmerged as `local-only` until `mise run judge` runs on the owner's GPU.
Work whose result turns on single pixels (a `background` band) goes to local-windows outright.
Each PR repins only its own class ([ADR 0053](../../../docs/adr/0053-expected-scores-live-in-a-generated-file-per-class.md)), so `gpu.toml` and `lavapipe.toml` each lag behind the other's PRs, and the lavapipe catch-up (#830) needs a cloud session because local-windows' llvmpipe is LLVM 21.1.7 and the pins name LLVM 20.1.2.
So parity work queues behind one machine, and its question (does our render match the capture?) is tangled with a second one (do lavapipe and the GPU draw the same pixels?).

## Two measures

- **Fidelity: capture against lavapipe.**
  All parity work: the adoption rule, sweeps, probes, `lavapipe.toml`.
  The GPU never gates it.
- **Class agreement: lavapipe against the GPU.**
  The index-plane pixels per tick on which lavapipe and the GPU differ, per film, as [`lavapipe.md` § 5](../../../research/parity/lavapipe.md#5-what-still-differs) has measured by hand.
  A batch on local-windows measures it and pins it; its regressions are their own issues.

## Fidelity

- **Verdicts run on either renderer class; pins on the canonical lavapipe.**
  The adoption rule compares a baseline and a variant on the same adapter, so a sweep on the GPU gives a valid verdict, and local-windows keeps its fast loop.
  Only `lavapipe.toml` needs the canonical lavapipe build.
  A verdict that does not carry over to lavapipe may show in the next agreement batch, if it crosses a flag (below); a smaller one does not.
- **No PR waits for the GPU.**
  The `local-only` hold of `cloud.md` § Rendering goes, and so does the `local-only` routing of pixel-level work such as a `background` band: both are done on lavapipe.
- **The canonical lavapipe build** is chosen by a spike (Task 1 of the plan) from those both local-windows and the cloud can run, by byte-identical index planes across machines first and render time second.
  The spike decided on 2026-11-21 (the journal's Verdict): the canonical build is the cloud's Ubuntu 24.04 `mesa-vulkan-drivers` `25.2.8-0ubuntu0.24.04.5` (`llvmpipe (LLVM 20.1.2, 256 bits)`), which local-windows renders under WSL 2; #830 keeps doing the catch-ups.
- **The canonical package is pinned** in CI and the cloud setup to the exact version the spike names, so an Ubuntu update cannot change the adapter silently.

## Class agreement

- **The figures** live in `research/parity/expected/agreement.toml`, generated, never hand-edited, and covered by ADR 0053's `expected-pins` merge driver like the other generated files.
  A `[measured]` table names the `crates` tree, the date, and both adapters.
  Each `[<film>]` table holds the ticks compared, the ticks differing, the mean and largest differing pixels per tick with the largest's tick, and a `[<film>.hot]` table of every tick differing by more than `HOT_TICK_PIXELS` (500) pixels.
- **`gpu.toml` stays, written only by the batch.**
  It keeps the GPU's drift line for a local GPU run, and `references.py` needs no change; the drift line and the sweep change only as below.
  The GPU-minus-lavapipe score gap the flags use comes from the batch's own two reports, on one tree.
  No PR repins `gpu`; the drift line for a lagging `gpu` reads `awaiting the next agreement batch`.
- **The batch** (`mise run agreement -- batch`) runs on local-windows in a worktree detached at `origin/main`: it renders the seven reference films on the GPU and on the local canonical-or-nearest lavapipe, counts the residue per film, scores both, compares with the pinned figures, and prints flags.
  With no flags it writes `agreement.toml` and `gpu.toml` and opens a `chore(parity): repin class agreement` PR.
- **Flags** (on a fixed pair of drivers renders are deterministic, so every change is real, but new geometry makes new ties legitimately):
  1. a film's mean rises by more than 25% and by at least 1 pixel per tick;
  2. a tick's count rises by more than `TICK_FLAG_PIXELS` (1,000) over its pinned count, or over `HOT_TICK_PIXELS` when it was not hot;
  3. a film's GPU-minus-lavapipe `mean_ssim_scored` gap exceeds 0.002 in magnitude, the margin [`lavapipe.md` § 4](../../../research/parity/lavapipe.md#4-lavapipe-beside-the-gpu-on-one-crates-tree) used.
  The thresholds are starting values, tuned after a few batches.
  `[measured]` also records each side's driver version, because the adapter name does not change with an NVIDIA driver or a Mesa package of the same LLVM.
  A changed adapter or driver on either side gives no flags and no pin: the batch says the pair changed and the owner re-baselines with `--accept`.
  So does a first batch, with nothing pinned.
- **A flag** either becomes a `class-agreement` issue (deduplicated by film and tick range) or is accepted: `mise run agreement -- pin --accept "<reason>"` pins anyway and puts the reason in the batch comment.
  Agreement never loosens without a recorded reason.
- **Due** after 5 commits on `main` that change the renderer (`expected_scores.renderer_changes`) since the pinned tree, or 7 days after the pinned date when at least one has landed; `mise run queue` prints the line.
- **It runs unattended**: a nightly Windows Task Scheduler job runs `mise run agreement -- batch --if-due --post`, which posts one comment per measured tree on the standing issue "Class agreement batch" (`local-only`, `ready-for-agent`) and files issues only on a flag.

## A per-PR guard with no GPU

Each sweep reads the pinned hot ticks and prints, for each film, how much of a variant's positive SSIM change against the baseline lies on hot ticks it scores.
Above half, it says to check that film on the GPU: a gain concentrated where lavapipe and the GPU disagree may be fitting a lavapipe quirk such as the clipper's NaN path ([`lavapipe.md` § 2](../../../research/parity/lavapipe.md#2-mechanism-the-clippers-screen-space-weight-is-00)).
The line is informational and leaves the verdict alone.

## GitHub

- New label `class-agreement` (category role): a difference between lavapipe and the GPU, measured by the batch, worked on local-windows (`local-only`).
- Parity issues stay as they are.
- Existing issues change as the plan's last task lists.

## What stays `local-only`

What [`triage-labels.md`](../../../docs/agents/triage-labels.md#environment-roles) lists today (GPU timing, DOSBox-X's debugger and `play`, the owner's logins, data-root files no cloud archive holds), less the GPU check and pixel-level work, plus the agreement batch itself and its flag issues.

## Out of scope

- Building a Linux lavapipe to match mesa-dist-win (#877's original spike); the comparison spike decides whether it is needed.
- Changing the adoption rule or its thresholds.
- Rendering in CI, which holds no corpus.
