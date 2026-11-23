# Fidelity pins on lavapipe, and class agreement is measured apart

## Status

accepted 2026-11-23 for [#908](https://github.com/neilsh/stunt-reel/issues/908); the owner approved the design on 2026-11-21 ([`spec.md`](../../work/2026-11/908_backend-agreement/spec.md)).
Amends [ADR 0053](0053-expected-scores-live-in-a-generated-file-per-class.md)'s "Each PR repins only the class it measured": no PR repins `gpu`, which only the agreement batch writes.
ADR 0053's other decisions, [ADR 0006](0006-ci-renders-on-lavapipe.md) and [ADR 0054](0054-depth-is-reversed-and-infinite.md) stand.

## Context

A rendering PR that changed depth testing or bias, the vertex transform, projection or clipping, draw order or `shade` interpolation waited unmerged, labelled `env:local-only`, until `mise run judge` ran on the owner's GPU, and work that turned on single pixels (a `background` band) went to local-windows outright.
Each PR repinned only its own class, so `gpu.toml` and `lavapipe.toml` each lagged behind the other's PRs, and the lavapipe catch-ups (#830) needed the pinned llvmpipe.
Parity work queued behind one machine, and its question (does our render match the capture?) was tangled with a second one (do lavapipe and the GPU draw the same pixels?).

The spike of 2026-11-21 ([`lavapipe.md` § 6](../../research/parity/lavapipe.md#6-one-build-on-two-machines)) found one lavapipe build, Ubuntu 24.04's `mesa-vulkan-drivers` `25.2.8-0ubuntu0.24.04.5`, whose index planes match on every tick of all seven reference films in a cloud container and under WSL 2 on local-windows.

## Decision

- **Fidelity, capture against lavapipe, is pinned on the canonical lavapipe.**
  The adoption rule compares a baseline and a variant on one adapter, so a verdict may come from either renderer class; `lavapipe.toml` is repinned only from the canonical build, in a cloud session or under WSL on local-windows ([`render-on-lavapipe.md` § 5](../howto/render-on-lavapipe.md#5-render-the-canonical-lavapipe-under-wsl)).
  The canonical package is pinned in CI and the cloud setup, so an Ubuntu update cannot change the adapter silently.
- **No PR waits for the GPU.**
  The `env:local-only` hold on rendering PRs goes, and so does the local-windows routing of pixel-level work: both are done on lavapipe.
- **Class agreement, lavapipe against the GPU, is measured apart.**
  `mise run agreement -- batch` renders the seven reference films on the GPU and on the canonical lavapipe on local-windows, from one `crates` tree, counts the index-plane pixels per tick on which they differ, and pins the result in the generated `research/parity/expected/agreement.toml`, with every hot tick (over 500 pixels) of each film.
  A rise beyond the thresholds in [`class_agreement.py`](../../python/stunt_reel/class_agreement.py), or a film's GPU-minus-lavapipe SSIM gap beyond 0.002, is a flag: it becomes an `area:class-agreement` issue, or is pinned over with `--accept <reason>`, so agreement never loosens without a recorded reason.
  A changed adapter or driver on either side, or nothing pinned, pins only with `--accept`.
- **`gpu.toml` stays, and only the batch writes it.**
  Its rows keep the drift line for a local GPU run, which reads `awaiting the next agreement batch` on a newer tree than the row's.
- **A sweep flags gains on hot ticks.**
  A sweep prints, for each film where more than half of a variant's SSIM gain lies on the pinned hot ticks, a line asking for a GPU check; it leaves the verdict alone.

## Considered Options

- **Keep the hold:** every rendering PR in the listed classes waits for the GPU.
  Rejected: parity work queues behind one machine, and the hold judged agreement one PR at a time without a pinned figure to compare against.
- **Drop `gpu.toml` entirely:** fidelity only on lavapipe, no GPU rows.
  Rejected: a local GPU run would lose its drift line, and the batch already renders the GPU on one tree, so writing its rows costs nothing.
- **A path-based `gpu-pending` label:** PRs touching the renderer's depth, transform or shader paths merge, labelled, and a GPU session clears the labels later.
  Rejected: it still runs the GPU per PR, and a path says little about which pixels move; the batch measures what moved.

## Consequences

- Rendering PRs from a cloud session merge on lavapipe's verdict alone; a change that departs on the GPU shows in the next batch, if it crosses a flag, and a smaller one does not.
- `gpu.toml` lags `main` between batches by design; its drift line says so instead of `awaiting a repin or catch-up repin of this class`.
- The batch is due after 5 renderer commits since the pinned tree, or 7 days after the pinned date once one has landed; `mise run queue` prints the line, and [`run-the-agreement-batch.md`](../howto/run-the-agreement-batch.md) says how to run it, by hand or as a scheduled task.
- Thresholds are starting values, to be tuned after a few batches.

Source: `work/2026-11/908_backend-agreement/spec.md`, `work/2026-11/908_backend-agreement/plan.md`.
