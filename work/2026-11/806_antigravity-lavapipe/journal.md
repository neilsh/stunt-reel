# Journal: cloud-antigravity's lavapipe and expected.lavapipe

## 2026-11-19: whether Ubuntu's LLVM 20.1.2 lavapipe can run on Debian 12

- **Question**: can `.claude/cloud-setup.sh --antigravity` unpack the lavapipe build that `expected.lavapipe` names (`llvmpipe (LLVM 20.1.2, 256 bits)`) into user space on cloud-antigravity's Debian 12, in place of the bookworm-backports `mesa-vulkan-drivers` (built on LLVM 15) it unpacks now (#806 option 1)?
- **Method**: in a Claude Code cloud session on `601954c` (Ubuntu 24.04.5; `mesa-vulkan-drivers` `25.2.8-0ubuntu0.24.04.5`, `libllvm20` `1:20.1.2-0ubuntu1~24.04.3`, the build behind `expected.lavapipe`'s adapter string), `objdump -T` and `objdump -p` on `/usr/lib/x86_64-linux-gnu/libvulkan_lvp.so` and `libLLVM.so.20.1`, listing their highest glibc symbol versions and their `NEEDED` libraries.
  Fetching bookworm-backports' `mesa-vulkan-drivers` here to render all seven films on both builds (option 2) failed: the session's network refuses `deb.debian.org` (proxy `CONNECT` 403), and the owner declined adding it to the environment.
- **Result**: both libraries need `GLIBC_2.38`, which Debian 12's glibc 2.36 lacks.
  `libvulkan_lvp.so` imports `__isoc23_strtol`, `__isoc23_strtoul`, `__isoc23_strtoll`, `__isoc23_strtoull` and `__isoc23_sscanf` at that version.
  `libLLVM.so.20.1` imports the same `__isoc23_*` set plus `__isoc23_scanf`, `fmod` and `fmodf`.
  `libLLVM.so.20.1` also imports `_ZSt21ios_base_library_initv` at `GLIBCXX_3.4.32` (GCC 13's libstdc++), and Debian 12's GCC 12 libstdc++ provides up to `GLIBCXX_3.4.30`.
  The renderer loads the driver into its own process through the Vulkan loader, so a renderer started under the system's glibc 2.36 cannot load either library.
- **Verdict**: rejected as a drop-in for the current unpack, because the libraries cannot load under the system's glibc and libstdc++, not on a score.
  Two routes were not tried: running the renderer under a separate, newer glibc and libstdc++ (Ubuntu's `ld-linux-x86-64.so.2 --library-path …`, or a container image), and rebuilding Mesa on Debian 12 against LLVM 20.1.2.
  Debian 12's glibc 2.36 and libstdc++ 3.4.30 are the release's package versions, not read on the VM.
  Option 2 (accept LLVM 15's scores against the LLVM 20.1.2 rows) still needs all seven films rendered on both builds; cloud-antigravity already has two (CTRY `+0.0000001`, LOCATION `-0.0000009` against the rows, in #806).
- **Lives in**: [`lavapipe.md` § Ruled out](../../../research/parity/lavapipe.md#ruled-out) and [`cloud-antigravity.md` § Rendering](../../../.agents/skills/working-in-an-environment/cloud-antigravity.md#rendering).
