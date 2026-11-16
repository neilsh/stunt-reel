# Render on lavapipe beside a GPU

CI renders on Mesa's lavapipe, a CPU Vulkan driver ([ADR 0006](../adr/0006-ci-renders-on-lavapipe.md)); #265 compares scores from there with a cloud session's and with this machine's GPU. By default the offscreen path skips a CPU adapter while a GPU exists (`preferred_adapter` in [`adapter.rs`](../../crates/stunt-render/src/renderer/adapter.rs)), so a local run that must land on lavapipe needs both the driver named and `--software-only`.

## 1. Unpack Mesa into the data root

`<data root>` below is the absolute data root: `STUNT_DATA_ROOT` when set, else `<parent of the primary checkout>\stunt-reel.data`, which `mise run init` prints. Download the **25.2.8 MSVC** build (66,540,000 bytes) and hash it:

```powershell
$archive = "$env:TEMP\mesa3d-25.2.8-release-msvc.7z"
curl.exe -L --fail -o $archive https://github.com/pal1000/mesa-dist-win/releases/download/25.2.8/mesa3d-25.2.8-release-msvc.7z
(Get-FileHash $archive -Algorithm SHA256).Hash.ToLower()
```

Its SHA-256 is `e47cfe0be35f0c40c3d488c0e965d10656154ed55cfdfe4f4d79d4395672dc02`, which GitHub publishes as the asset's digest; the download here measured the same on 2026-11-15. Unpack it into the data root, never into the checkout:

```powershell
$mesa = "<data root>\tools\mesa-25.2.8"
New-Item -ItemType Directory -Force $mesa | Out-Null
7z x -y "-o$mesa" $archive
```

Mesa 26.2.6 unpacks the same way into `tools\mesa-26.2.6`: `mesa3d-26.2.6-release-msvc.7z`, 55,964,101 bytes, SHA-256 `b2e00615feaba45942343c265cc8c5f576142ca682c1ac6661922d4b72492877` (GitHub's digest, measured the same on 2026-11-15); its llvmpipe reports `llvmpipe (LLVM 23.1.4, 256 bits)`.

The archive holds `x64\` and `x86\` driver trees, an ICD manifest for each of its two Vulkan drivers (lavapipe and Dozen — the OpenGL, OpenCL, VA-API and WARP DLLs beside them have none), `modules\`, `readme.txt` and the release's two deploy scripts. Do not run the scripts: the variable below is not system-wide, it reaches this shell and every process the shell starts.

## 2. Name only the lavapipe ICD

```powershell
$env:VK_DRIVER_FILES = "<data root>\tools\mesa-25.2.8\x64\lvp_icd.x86_64.json"
```

The manifest's `library_path` is `.\vulkan_lvp.dll`, relative to itself, so the JSON is the whole value; do not add the DLL. Take the x64 manifest (`lvp_icd.x86_64.json`) on a 64-bit host; `dzn_icd.x86_64.json` beside it is the Dozen driver, not lavapipe. Naming only this one keeps Vulkan to lavapipe, so a render that lands elsewhere shows it in the report (step 4).

## 3. Render with `--software-only`

```powershell
mise run parity -- --films ctry --software-only
mise run frame -- --film ctry --ticks 400,422 --software-only
```

`--software-only` reaches `stuntreel`'s film renderer, which sets `RenderOptions::software_only` for the headless and the windowed path alike. Both halves are needed, and `mise run frame` records the adapter each render used in the frame store's `build/scratch/frame/<film>/store/render.json`; on this machine (an RTX 4070 laptop), with the ICD named but no flag, the first Vulkan attempt found only lavapipe and passed it over, the all-backends attempt found the GPU, and the one-tick run (`--ticks 400`) recorded `NVIDIA GeForce RTX 4070 Laptop GPU` in the store. With the flag but no `VK_DRIVER_FILES`, Vulkan had no CPU driver and the same run recorded `Microsoft Basic Render Driver`, WARP.

`--no-build` renders with whatever `target/release/stuntreel.exe` holds. Rebuild after any temporary renderer edit, such as removing the NaN-shade guard to test it: a guard-removed binary left there by #265's byte-identity check rendered a lavapipe LOCATION run 0.19 below the GPU ([`lavapipe.md`](../../research/parity/lavapipe.md) section 4).

## 4. Check the adapter

```powershell
(Get-Content -Raw build/parity/report/ctry_current/report.json | ConvertFrom-Json).adapter | ConvertTo-Json -Compress
```

prints

```text
{"name":"llvmpipe (LLVM 21.1.7, 256 bits)","class":"cpu"}
```

on lavapipe, and `{"name":"NVIDIA GeForce RTX 4070 Laptop GPU","class":"hardware"}` on this machine's GPU. The LLVM version moves with the Mesa release. `Microsoft Basic Render Driver` with class `cpu` is WARP: the loader did not find the ICD (a relative path, or the wrong JSON), and, with `--software-only`, the all-backends attempt took the software adapter it found. The GPU's own name with class `hardware` on this setup indicates `--software-only` did not reach the render. The report copies the adapter from the render's `render.json`, so re-render rather than edit it. A run overwrites `build/parity/report/<film>_current`, so copy a report elsewhere before switching adapters:

```powershell
Copy-Item build/parity/report/ctry_current build/parity/report/ctry_lavapipe -Recurse
```

Without a `[ctry.expected.lavapipe]` table in [`references.toml`](../../research/parity/references.toml), the run's comparison line says `no expected score for lavapipe yet: add it`; #455 adds those rows. Once a row exists, `comparison_line` in [`expected_scores.py`](../../python/stunt_reel/expected_scores.py) checks the adapter name before `changed_since`: a row measured on an adapter with another name gives `not comparable: other adapter (expected on {expected.adapter})`, and only a row on the same adapter name, where the checkout's `crates/` tree differs from the row's recorded one, gives `crates/ changed: tree {found[:7]}, measured on {expected.crates[:7]}`. The first is the likely case here, since #455's cloud rows come from Ubuntu's Mesa build and its llvmpipe need not carry the same LLVM version; neither line is a verdict on the delta.
