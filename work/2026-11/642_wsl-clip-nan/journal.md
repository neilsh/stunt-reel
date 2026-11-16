# Journal: the lavapipe clip-NaN repro on WSL Ubuntu

## 2026-11-16: the repro on Ubuntu 26.04's Mesa 26.0.8, and why no patched Mesa build

- **Question**: does the standalone repro of [`lavapipe-clip-nan`](../lavapipe-clip-nan/README.md) draw NaN `noperspective` pixels on a Linux Mesa build, as it does on the two mesa-dist-win builds, so the upstream issue can name a Linux package? And is a lavapipe build with the draft's suggested `interp()` fix cheap enough to test here (issue #642, step 3)?
- **Method**: on `3a7afb76`, WSL 3.0.5.0 (kernel 6.18.58.1-microsoft-standard-WSL2, WSLg 1.0.79) distro `Ubuntu` (WSL 2), Ubuntu 26.04.1 LTS (Resolute Raccoon), Windows 11 10.0.26300. The distro already had `mesa-vulkan-drivers` 26.0.8-1ubuntu0.3 (with `mesa-libgallium` 26.0.8-1ubuntu0.3), `libllvm21` 1:21.1.8-6ubuntu1 and `libvulkan1` 1.4.341.0-1; nothing was installed with apt (`sudo` asks for a password). `vulkan-tools` is not installed: the repro prints the adapter itself. Rust came from rustup (`--profile minimal`): rustc 1.100.0 (0ef1bc386 2026-11-09), cargo 1.100.0. The repro's `Cargo.toml`, `Cargo.lock` and `src/` were copied to `~/clip-nan-repro` on the WSL filesystem (the checkout was not built in), built with `cargo build --release` (15 s), and run with `VK_DRIVER_FILES=/usr/share/vulkan/icd.d/lvp_icd.json`, then with it unset; the two runs' whole output compared byte-identical (`cmp`).
- **Result**: adapter `llvmpipe (LLVM 21.1.8, 256 bits)`, driver info `Mesa 26.0.8-1ubuntu0.3 (LLVM 21.1.8)`. Pixels per class out of 4,096 per target, the same in both runs:

  | Case | `noperspective` | perspective |
  |---|---|---|
  | A | NaN 1,077 | 1.0 on 1,077 |
  | B | NaN 442 | 1.0 on 442 |
  | control | 1.0 on 434 | 1.0 on 434 |

  No pixel was infinite or finite and wrong in any case on either target; NaN in cases A and B totals 1,519, the same as on the mesa-dist-win 25.2.8 and 26.2.6 builds ([`lavapipe-clip-nan` journal](../lavapipe-clip-nan/journal.md#2026-11-16-the-repro-on-two-mesa-builds-and-the-gpu)). The distro's `/usr/share/vulkan/icd.d/` holds no `dzn_icd.json`, so no WSL GPU row was run.
- **Step 3, not run**: a lavapipe build needs `meson`, `llvm-dev` (matching `libllvm21`), `libexpat1-dev`, `bison`, `flex`, `python3-mako` and `glslangValidator`; of these the distro has `ninja`, `python3-yaml`, `pkg-config`, `libdrm-dev`, `zlib1g-dev` and `gcc`. `meson` and `mako` would install per user with pip, but `llvm-dev`, `libexpat1-dev`, `bison` and `flex` need apt and so a sudo password, which this session does not have. Beyond that, the build is a Mesa source tree and LLVM-sized compile, more than the "short setup" the issue allows, so it was skipped, not attempted. The suggested fix stays checked only in `replay_interp.py --suggested-fix`.
- **Verdict**: control. The fault reproduces on a Linux Mesa package, 26.0.8 with LLVM 21.1.8, in both cases and not in the control. Step 3 is skipped for cost and for the missing sudo, not by any result. [`issue-draft.md`](issue-draft.md) here is a copy of the frozen draft with its "Affected versions" updated; the owner files it.
- **Lives in**: [`lavapipe.md`](../../../research/parity/lavapipe.md) section 2.
