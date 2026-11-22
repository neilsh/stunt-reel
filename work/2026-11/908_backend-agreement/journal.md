# Journal

## 2026-11-21: Four renderer builds on one crates tree, two machines

- **Question**: which lavapipe build can local-windows and the cloud both run with identical index planes, and how fast is each ([#877](https://github.com/neilsh/stunt-reel/issues/877), plan Task 1)?
- **Method**: commit `708fc0f` (branch `claude/project-thread-pn2dbt`), `crates` tree `9d08971`, all seven reference films at the default `--jobs 8`: on local-windows one release build per arm, then `mise run parity -- --no-build [--software-only]`; in the cloud a release build, then `mise run parity -- --software-only`.
  - **A**: local-windows (AMD Ryzen 7 7745HX, 8 cores, 16 threads), RTX 4070 Laptop GPU, NVIDIA driver 610.88.
  - **B**: the same machine, mesa-dist-win 25.2.8 MSVC (`llvmpipe (LLVM 21.1.7, 256 bits)`), selected by `VK_DRIVER_FILES` as `render-on-lavapipe.md` says.
  - **C**: the same machine under WSL 2, a fresh Ubuntu 24.04.5 distro run as root, `mesa-vulkan-drivers` `25.2.8-0ubuntu0.24.04.5` (`llvmpipe (LLVM 20.1.2, 256 bits)`, driver info `Mesa 25.2.8-0ubuntu0.24.04.5 (LLVM 20.1.2)`), `libvulkan1` `1.3.275.0-1build1`.
    The distro came with `25.2.8-0ubuntu0.24.04.2` and was moved to `.5` by `apt-get install mesa-vulkan-drivers=25.2.8-0ubuntu0.24.04.5`.
    Its data root lay on the WSL filesystem: the five cloud archives' contents copied from the Windows data root by `manifests/cloud-assets.toml`'s rules (local-windows has no R2 credentials), then `mise run game-builds` and `mise run superset-all`.
  - **D**: a Claude cloud thread container (Intel Xeon @ 2.30GHz, 4 vCPUs, Ubuntu 24.04.5), the same package and adapter, data root from `mise run cloud-assets -- fetch --replace-unmarked`, `mise run game-builds` and `mise run superset-all`.
  - Pixels: `mise run parity-residue` between A, B and C on local-windows; D against B and C by `--write-hashes` digests, compared per film and per 200-tick block of each film's sorted tick hashes (the per-tick hash files stayed on their machines).
  - B and C were each rendered twice.
- **Result**:
  - **C and D are identical**: every film's digest of all its tick hashes matches (20,621 ticks), and all 107 200-tick blocks match.
    B differs from D in 33 of the 107 blocks, on every film.
  - **B against C** (index-plane pixels): differing ticks per film BALLOON 44 of 1,179, BOMB 32 of 3,719, CTRY 17 of 1,320, INTRO 60 of 3,807, LAND 5 of 1,123, LOCATION 201 of 8,251, TRAINTNL 14 of 1,222; mean per tick 0.3 on BALLOON, 0.1 on LOCATION, under 0.05 on the rest; the largest 33 pixels (BALLOON 1084).
  - **A against B and against C**: mean differing pixels per tick CTRY 6.3, INTRO 8.9, LAND 26.2, BALLOON 8.9, TRAINTNL 5.2, BOMB 11.6, LOCATION 29.8, the same to one decimal for both; the largest LAND 2,075 at tick 416 and LOCATION 2,470 at 3830.
  - **Repeat runs**: B against B and C against C differ on no tick of any film.
  - **Scores** (`mean_ssim_scored`, A / B / C): CTRY 0.9376329 / 0.9376211 / 0.9376211, INTRO 0.8824304 / 0.8819951 / 0.8819947, LAND 0.9236066 / 0.9234964 / 0.9234974, BALLOON 0.9056968 / 0.9054334 / 0.9054309, TRAINTNL 0.9066099 / 0.9066371 / 0.9066374, BOMB 0.8774961 / 0.8773449 / 0.8773443, LOCATION 0.8720316 / 0.8721492 / 0.8721512.
    A read "no drift" against `expected/gpu.toml` on every film.
    B and C scored 0.019 to 0.088 above `expected/lavapipe.toml`, measured on `crates` `be54d86` (BALLOON IoU 0.950 against 0.719 there); D, on C's pixels, printed the same scores to the four decimals it shows, so the gap is not the machine; it is the `crates` change since `be54d86`, or the package revision those rows were measured on (`.4` on 2026-11-16, never compared with `.5`), or both.
  - **Wall time** for the whole run: A 49.8 s, B 1 m 43.3 s, C 2 m 33.6 s (2 m 37.3 s on its first run), D 251 s on 4 vCPUs.
    Solo CTRY: B 6.1 s; C 4.4 s with its data root on ext4 and 35.4 to 36.8 s with it read from `/mnt/e` over 9P.
    B's first run overlapped the WSL install and took 2 m 49.8 s; its pixels match its clean run's.
- **Verdict**: control (a measurement, no renderer change).
  The pinned Ubuntu package reproduces the cloud's planes on a different CPU vendor under WSL, so it can be the canonical lavapipe on both machines; mesa-dist-win 25.2.8 cannot, though it differs by at most 33 pixels on a tick.
  The owner chose it on 2026-11-21: `25.2.8-0ubuntu0.24.04.5` is the canonical lavapipe, pinned in CI and the cloud setup (plan Task 5), and local-windows renders it under WSL 2.
- **Lives in**: [`lavapipe.md` § 6](../../../research/parity/lavapipe.md#6-one-build-on-two-machines).
