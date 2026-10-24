# CI renders on lavapipe and fails when no GPU is found

## Status

accepted; implemented

## Context

The GPU integration tests in `stunt-render` need a Vulkan adapter. Before this decision they skipped silently when none was present, which included every CI run, so the renderer was never exercised in CI. Each test file also carried its own copy of the adapter-or-skip block.

## Decision

The ubuntu quality job installs Mesa's software Vulkan driver (lavapipe, `mesa-vulkan-drivers`) and sets `STUNT_REQUIRE_GPU=1` in [`ci.yml`](../../.github/workflows/ci.yml). With that variable set, a missing adapter panics instead of skipping. All adapter setup goes through one helper, `gpu_or_skip()` and `gpu_or_skip_with()`, in [`crates/stunt-render/tests/common/mod.rs`](../../crates/stunt-render/tests/common/mod.rs). The render, export and scene-renderer test files use it. The windows runner does not install a driver and does not set the variable, so its GPU tests still skip.

## Considered Options

- **Keep skipping silently.** Rejected. A runner with no adapter then passes without running the tests.
- **Mark the GPU tests `#[ignore]` and run them by hand.** Rejected. Nothing would run them automatically.

## Consequences

A CI run on the ubuntu job now fails if an adapter cannot be created, so a broken driver install shows up as a red build. Tests that fail under lavapipe must be fixed or marked `#[ignore]` with a reason, not left to skip. Whether every GPU test passes under lavapipe is not verified by this record.
