# Journal: cloud-antigravity's lavapipe and expected.lavapipe

## 2026-11-23: the canonical Ubuntu lavapipe cannot load on Debian 12

- **Question**: can `.claude/cloud-setup.sh --antigravity` unpack the canonical lavapipe (`mesa-vulkan-drivers` `25.2.8-0ubuntu0.24.04.5` with `libllvm20` `1:20.1.2-0ubuntu1~24.04.3`) into user space on cloud-antigravity's Debian 12, in place of the bookworm-backports `mesa-vulkan-drivers` `25.0.7-2~bpo12+1` built on LLVM 15 (#806)?
- **Method**: on 2026-11-23, downloaded `mesa-vulkan-drivers_25.2.8-0ubuntu0.24.04.5_amd64.deb` from `http://archive.ubuntu.com/ubuntu/pool/main/m/mesa/` and `libllvm20_20.1.2-0ubuntu1~24.04.3_amd64.deb` from Launchpad, extracted both, and read `libvulkan_lvp.so` and `libLLVM.so.20.1` with `pyelftools`: each library's `DT_NEEDED` entries, the symbols it imports at `GLIBC_2.38`, and its highest `GLIBCXX` request.
  Debian 12's release library versions are glibc 2.36 (`libc6`) and GCC 12's libstdc++ (highest `GLIBCXX_3.4.30`).
- **Result**: `libvulkan_lvp.so` imports `__isoc23_strtol`, `__isoc23_strtoul`, `__isoc23_strtoll`, `__isoc23_strtoull` and `__isoc23_sscanf` at `GLIBC_2.38`; its highest `GLIBCXX` request is `GLIBCXX_3.4.29`, which Debian 12's 3.4.30 provides.
  `libLLVM.so.20.1` imports the same five symbols plus `__isoc23_scanf`, `fmod` and `fmodf` at `GLIBC_2.38`, and asks for `GLIBCXX_3.4.32`, past Debian 12's 3.4.30.
  The Vulkan loader opens the ICD's `libvulkan_lvp.so` into the renderer's own process, so under the system's glibc 2.36 the load fails before any pixel is drawn; `dpkg -x` into `~/.local/share/lavapipe` does not change that.
- **Verdict**: rejected as a drop-in for the current Antigravity install, on the dependency and not on a score.
  Three routes were not tried: running the renderer under a separate, newer glibc (Ubuntu's `ld-linux-x86-64.so.2 --library-path …`); an Antigravity base image whose glibc is 2.38 or newer, where the canonical package can load; and a lavapipe built on bookworm against LLVM 20.1.2 and hosted as a pinned artifact (the #877 plan, which used LLVM 21.1.7), which could report the pinned adapter string while running under glibc 2.36.
  The owner chose the Ubuntu package on 2026-11-21, so that choice needs revisiting before the setup script can change.
- **Lives in**: [`lavapipe.md` § Ruled out](../../../research/parity/lavapipe.md#ruled-out), [`cloud-antigravity.md` § Rendering](../../../.agents/skills/working-in-an-environment/cloud-antigravity.md#rendering).
