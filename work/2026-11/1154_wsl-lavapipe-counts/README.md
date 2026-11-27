---
title: "Does perf stat count instructions under WSL 2, and do Valgrind counts agree across machines?"
started: 2026-11-27
issue: 1154
outcome: "perf stat -e instructions:u works under WSL 2 with linux-tools 6.8 perf; a Cachegrind B30 count on this laptop is 0.008% above the cloud's whole-run median and 0.0013% below its outside-allocator median (not the same range); lavapipe-instruction-counts.md section 6"
---

# Does perf stat count instructions under WSL 2, and do Valgrind counts agree across machines?

The check ran on this laptop's WSL 2 distro ([`journal.md`](journal.md)); its finding is [`lavapipe-instruction-counts.md` § 6](../../../research/parity/lavapipe-instruction-counts.md#6-the-same-span-on-a-laptop-under-wsl-2).

## Files

- [`journal.md`](journal.md): the entry, with the numbers and the environment.
- [`perf-and-cachegrind-run.sh`](perf-and-cachegrind-run.sh): the native `perf stat` runs and the Cachegrind repeats, as run in WSL.
- [`count.sh`](count.sh), [`outside_allocator.py`](outside_allocator.py): `#1122`'s, unchanged.
- [`wsl-counts.csv`](wsl-counts.csv): `count.sh`'s rows from WSL.
- [`perf/`](perf): the `perf stat -x,` output of each native run.
- [`raw/`](raw): Cachegrind files (`.cg.xz`) and logs of the three `B30` repeats.
- [`outside-allocator.txt`](outside-allocator.txt), [`machine.txt`](machine.txt): the outside-allocator totals and the machine's `lscpu`, flags and tool versions.
