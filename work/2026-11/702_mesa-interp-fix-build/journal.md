# Journal: building lavapipe with the suggested `interp()` change

## 2026-11-18: a cloud build stopped at `meson setup`

- **Question**: issue #702, steps 1 and 2: build lavapipe alone from `mesa-25.2.8`, check that the unpatched build reproduces case A 1,077 and case B 442 NaN pixels, then apply the draft's suggested change and rerun.
- **Method**: a Claude Code cloud session on `origin/main` (Ubuntu 24.04, gcc 13.3.0, LLVM 18.1.3 from `llvm-config`, 4 cores), all of it under the session's scratch directory, outside the checkout.
  - Source: `https://gitlab.freedesktop.org/mesa/mesa/-/archive/mesa-25.2.8/mesa-mesa-25.2.8.tar.gz` (HTTP 200, 67,863,192 bytes).
    The release tarball hosts answered no: `archive.mesa3d.org` with HTTP 403 and `mesa.freedesktop.org` with a 403 on the proxy's CONNECT; GitHub's `mesa3d/mesa` archive also returned 403.
  - Tools: `meson` 1.12.1, `mako` and `pyyaml` from PyPI in a venv (Ubuntu's `meson` is older than the tag needs); `flex` and `glslang-tools` from apt; `bison`, `ninja`, `libexpat1-dev` and `zlib1g-dev` were already installed.
  - Configure, run with the venv first on `PATH` so meson's `python3` finds `mako` (with the system `python3` it stops at "Python (3.x) mako module >= 0.8.0 required"):

    ```sh
    meson setup build-stock mesa-mesa-25.2.8 -Dbuildtype=release \
      -Dgallium-drivers=llvmpipe -Dvulkan-drivers=swrast -Dplatforms= \
      -Dglx=disabled -Degl=disabled -Dgbm=disabled -Dopengl=false \
      -Dgles1=disabled -Dgles2=disabled -Dllvm=enabled -Dshared-llvm=enabled \
      -Dvideo-codecs= -Dbuild-tests=false
    ninja -C build-stock src/gallium/targets/lavapipe/libvulkan_lvp.so
    ```

    Then the repro runs with `VK_DRIVER_FILES` pointing to the build's `src/gallium/targets/lavapipe/lvp_devenv_icd.x86_64.json` (the tag's `meson.build` writes it beside `libvulkan_lvp.so`; that target may need building too), the change goes into `src/gallium/auxiliary/draw/draw_pipe_clip.c`'s `interp()`, and a second build directory gets the same commands.
- **Result**: none.
  The session's auto-mode permission classifier refused both `meson setup` runs: the first ran inside the source tree, and the second passed the tree as an argument with the venv first on `PATH`.
  The only configure that ran stopped at the missing `mako` above.
  The source and tools were in place; nothing compiled.
- **Verdict**: open.
  The question is not answered either way, and the suggested fix is still checked only in [`replay_interp.py --suggested-fix`](../lavapipe-clip-nan/replay_interp.py).
  The upstream issue cannot call the fix tested yet.
