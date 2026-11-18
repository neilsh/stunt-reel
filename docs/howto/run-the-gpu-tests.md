# Run the GPU tests

```powershell
mise run test-gpu
```

A driver that wedges would leave a plain `cargo test` of stunt-render's `gpu` binary waiting forever ([why](../quality-gate.md#gpu-tests)).
Every test in it runs under a deadline instead: a test still running after `STUNT_GPU_TEST_DEADLINE_S` seconds (a positive whole number; default 60) prints `HANG: <test> still running after <N>s` to stderr and aborts the process.

To measure the hang rate, run the task in a loop that stops at the first failure.

PowerShell:

```powershell
$env:STUNT_REQUIRE_GPU = "1"; 1..20 | % { mise run test-gpu; if ($LASTEXITCODE) { break } }
```

bash:

```bash
for i in $(seq 20); do STUNT_REQUIRE_GPU=1 mise run test-gpu || break; done
```

`STUNT_REQUIRE_GPU=1` makes a machine with no adapter fail instead of skipping every test, which would let the loop pass.

If a `HANG` line appears, re-run with a longer `STUNT_GPU_TEST_DEADLINE_S`, attach a debugger to the stuck process, or narrow it with `mise run test-gpu -- -- --test-threads 1`, and keep the diagnostics.
