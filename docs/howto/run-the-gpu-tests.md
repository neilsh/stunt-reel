# Run the GPU tests

A plain `cargo test` of stunt-render's `gpu` binary waits forever if a driver wedges ([why](../development.md#gpu-tests)). Run it under the watchdog instead:

```powershell
mise run test-render -- --runs 20
```

(or `uv run python python/scripts/watch_render_test.py`). It builds the binary once, gives each attempt a 60-second wall-clock bound (`--timeout-s`), kills the whole process tree on expiry, and prints `HANG` with the elapsed time, the last 20 stdout lines and the child-process count, exiting 1.

If it fires, do not leave the run unbounded: re-run with a longer `--timeout-s` and attach a debugger to the stuck process, or narrow it with `--test-threads 1`, and keep the diagnostics.
