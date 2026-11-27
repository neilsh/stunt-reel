# Journal

## 2026-11-27: PR B and #1109 PR 2, paused partway

State at the pause (one PR is planned for both issues; branch `claude/project-thread-b5g2j8`).

Done and committed here:
- `object-misaligned` in `error-categories.toml` (20 categories) with `props_shift:8` under `[faults]`; `props_shift` registered in `ALL_FAULTS` and kept out of the metric bench's PASS rule (`REPORTED_ONLY_FAULTS` in `bench/run.py`); the three tests updated.

Done in the cloud container, not committed (build output, lost with the container):
- All seven films rendered on lavapipe at `6d511d1` with no drift (`mise run parity -- --software-only`, 102 s).
- Sheets made with `errors-make` for all seven films, and the 12 sheets of each graded by two Haiku passes; the run and grade files are copied to `/mnt/project-files/1109-regrade/<film>/`.
  Grading is not finished: `errors-disputes`, the Sonnet tie-breaks, and `errors-score` have not run.

Deviation from #1110's D3: the `6486fb67` render is not re-made, because the captures were re-pinned and pairing changed since (#1165, #1172), so the sheets are of the current `main` render.

Blocked: `errors-make --calibrate` needs a CTRY recapture in `<data root>/bench/vault-ctry/recapture`.
In a cloud session `capture-ref` stalls because dosbox-automation mounts its own `drives/y` from the mise install under `/root`, which its mount policy refuses.
Copying the install to `/home/user/dba` and setting `DOSBOX_AUTOMATION_EXE` removed the refusal; the capture was running when paused.

Left to do: the recapture and calibration; the census (`object_shift` over the 84 frames with the timing test); disputes, tie-breaks and scoring; refresh `readouts/*.json` and `baseline.toml`; regenerate the 16 `error-examples`; docs (`error-readout.md`, `metric-bench.md` § 2.3); `mise run check -- --full`; PR, review, merge.
