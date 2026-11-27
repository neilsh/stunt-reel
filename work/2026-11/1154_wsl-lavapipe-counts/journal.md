## 2026-11-27: perf stat and Valgrind counts on WSL 2 against the cloud's

- **Question**: does `perf stat -e instructions:u` count under WSL 2 on this laptop, and does a Cachegrind count of `B30` on this laptop agree with the cloud's (`#1122`)?
- **Method**: in the `Ubuntu-24.04` distro, as root, on the Linux filesystem (`/root/stunt-reel`, `/root/stunt-reel.data`), a release `stuntreel` of `70b0f76` (`sha256 296a26787fb2`, built with `mise exec -- cargo build --release -p stunt-cli`).
  `perf` is `/usr/lib/linux-tools-6.8.0-151/perf` (the kernel is `6.18.58.1-microsoft-standard-WSL2`; `linux-tools-generic` installs no matching perf, the 6.8 one runs).
  Native runs: [`perf-and-cachegrind-run.sh`](perf-and-cachegrind-run.sh) (`perf stat -x, -e instructions:u` around the binary with `count.sh`'s render arguments, `setarch -R`, `VK_DRIVER_FILES`, `MESA_SHADER_CACHE_DISABLE=true`), each `B30` and `B60` three times, once with `LP_NUM_THREADS` unset and once with `=1`.
  Cachegrind: [`count.sh`](count.sh) copied unchanged from `#1122`, `cachegrind`, `B30`, three labels `wsl-b30-r1..r3`.
- **Environment**: `AMD Ryzen 7 7745HX` (8 cores, 16 threads, `avx2` and `avx512f`), Valgrind 3.22.0, `mesa-vulkan-drivers 25.2.8-0ubuntu0.24.04.5`. Full output in [`machine.txt`](machine.txt).
  The cloud's `counts.csv` says `Intel(R) Xeon(R) Processor @ 2.30GHz`; the note says `@ 2.10 GHz`. Not resolved here: the cloud's `/proc/cpuinfo` is the only source.
- **Result, perf**: `perf stat -e instructions:u` works (`136,349` instructions for `true`, so counters are live).
  Native `B30`, default threads: `26,287,148,044`, `26,288,778,051`, `26,284,567,567` (spread `0.016%`). `B30`, `LP_NUM_THREADS=1`: `26,285,556,179`, `26,284,197,070`, `26,286,518,699` (spread `0.009%`).
  Native `B60`, default: `28,792,161,323`, `28,790,307,026`, `28,792,159,595` (spread `0.006%`). `B60`, `=1`: `28,792,961,759`, `28,794,557,594`, `28,791,006,775` (spread `0.012%`).
  The thread count changes the native count by under `0.01%`.
- **Result, Cachegrind `B30` on WSL**: `I refs` `28,161,524,166`, `28,161,662,364`, `28,161,498,289` (median `28,161,524,166`, spread `0.0006%`); store hash `4366f202b0fe10c7` in all three, the cloud's `B30` store. Wall `54.3..56.2 s`, peak RSS `1,165 MiB`.
  Outside glibc's `malloc.c` and `memmove` ([`outside-allocator.txt`](outside-allocator.txt)): `26,592,113,575`, `26,592,253,787`, `26,592,321,930` (median `26,592,253,787`, spread `0.0008%`).
- **Against the cloud's `B30`** (three repeats, from [`#1122`'s `counts.csv`](../1122_instruction-count-gate/counts.csv)): whole run median `28,159,327,819`, range `28,151,461,402..28,170,706,144` (spread `0.068%`); WSL's median is `+2,196,347` (`+0.008%`) above it and inside the cloud's range.
  Outside the allocator: cloud median `26,592,603,757`, range `26,592,584,430..26,593,034,524` (spread `0.0017%`); WSL's median is `-349,970` (`-0.0013%`) below it, and WSL's three repeats (`26,592,113,575..26,592,321,930`) sit about `0.001%` below the cloud's lowest repeat, so the ranges of three repeats a side do not overlap; the cloud's loaded run (`26,592,305,570`) and second build (`26,592,322,616`) widen its five-run range to take in WSL's third repeat.
- **Surprises**: native `perf` counts about `7%` fewer instructions than Valgrind's `I refs` on the same span (`26.29 G` against `28.16 G`); Valgrind counts what it emulates, and the native figure is from another run path, so the two are not compared as one quantity.
  The WSL CPU is not the cloud's, yet the Valgrind whole-run count lands inside the cloud's range.
- **Verdict**: a count from this laptop agrees with the cloud's to `0.008%` on the whole run and `0.0013%` outside the allocator; on three repeats a side the two machines' ranges just miss each other outside the allocator, so a gate compares builds on one machine, with that machine's repeats.
  `perf stat` works here, through the 6.8 tools.
