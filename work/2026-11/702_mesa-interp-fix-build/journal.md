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

## 2026-11-18: stock and patched lavapipe builds of mesa-25.2.8

- **Question**: issue #702, steps 1 and 2, now that the owner allowed building the downloaded tree: does a lavapipe built from `mesa-25.2.8` reproduce the repro's NaN counts, and does the draft's suggested `interp()` change make them 0?
- **Method**: a Claude Code cloud session (Ubuntu 24.04.5, gcc 13.3.0, 4 cores shared with other sessions), on `origin/main` `91ad1d3`, with the source, venv and tools of the entry above, under `/tmp`, outside the checkout.
  - Meson found `llvm-config-20` (LLVM 20.1.2), the same LLVM as Ubuntu's `mesa-vulkan-drivers` 25.2.8; the entry above's LLVM 18.1.3 is not what this build linked.
  - Both build directories were configured with the same options, the entry above's plus the ones that turn off what the box lacked:

    ```sh
    meson setup <build> <source> -Dbuildtype=release -Dvulkan-drivers=swrast \
      -Dgallium-drivers=llvmpipe -Dplatforms= -Dglx=disabled -Degl=disabled \
      -Dgbm=disabled -Dopengl=false -Dgles1=disabled -Dgles2=disabled \
      -Dllvm=enabled -Dshared-llvm=enabled -Dvideo-codecs= -Dvulkan-layers= \
      -Dtools= -Dlibunwind=disabled -Dvalgrind=disabled -Dlmsensors=disabled \
      -Dbuild-tests=false -Dzstd=disabled -Dexpat=disabled
    ninja -C <build> -j3 src/gallium/targets/lavapipe/libvulkan_lvp.so
    ```

  - Stock: `build-stock` on the unmodified tree.
    Patched: a copy of the tree with the draft's § *Suggested direction* applied to `interp()` in `src/gallium/auxiliary/draw/draw_pipe_clip.c` (the hunk at lines 193-205; nothing else changed), built in its own `build-patched` (775 steps, about 5 minutes); its one compiler warning is in `gallivm/lp_bld_debug.cpp`, not the clipper.
  - Each `libvulkan_lvp.so` was copied to its own directory beside a hand-written ICD JSON (`library_path` to that copy, `api_version` 1.4.318 from Ubuntu's `lvp_icd.json`), and the [repro](../lavapipe-clip-nan/README.md) (its `src/` identical to the checkout's, `cargo build --release`) ran with `VK_DRIVER_FILES` and `VK_ICD_FILENAMES` set to that JSON, twice per build; it also ran once on Ubuntu's package with neither set.
- **Result**: the two builds report driver info `Mesa 25.2.8 (LLVM 20.1.2)`, so neither run fell back to Ubuntu's `Mesa 25.2.8-0ubuntu0.24.04.5`.
  `noperspective` pixels out of 4,096 per target; the perspective copy read 1.0 on every covered pixel in every run, and no run had an infinite or finite-wrong pixel:

  | Case | Ubuntu package | Stock build | Patched build |
  |---|---|---|---|
  | A | NaN 1,077 | NaN 1,077 | 1.0 on 1,077 |
  | B | NaN 442 | NaN 442 | 1.0 on 442 |
  | control | 1.0 on 434 | 1.0 on 434 | 1.0 on 434 |

  Each build's two runs printed byte-identical output.
- **Verdict**: adopted for the issue draft: in a lavapipe built from `mesa-25.2.8`, the change takes the repro's NaN pixels from 1,519 to 0 and leaves the control as it was, so the filed issue can call the fix tested on this repro.
  What it does not show: the repro's varying is 1.0 at every vertex, so a varying that changes across the triangle was not checked for correct values (the draft's #190 caveat stands); no Mesa test suite (CTS, piglit) ran on the patched build; Mesa's `main` (step 3) was not built.
  [`issue-draft.md`](issue-draft.md) here is a copy of [`642_wsl-clip-nan/issue-draft.md`](../642_wsl-clip-nan/issue-draft.md) with this result in its *Affected versions* and *Suggested direction*.
- **Lives in**: [`lavapipe.md`](../../../research/parity/lavapipe.md) section 2.
