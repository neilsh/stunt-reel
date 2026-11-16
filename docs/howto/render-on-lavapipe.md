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

The archive holds `x64\` and `x86\` driver trees, an ICD manifest for each driver, and the release's two deploy scripts. Do not run the scripts: the variable below is not system-wide, it reaches this shell and every process the shell starts.

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

`--software-only` reaches `stuntreel`'s film renderer, which sets `RenderOptions::software_only` for the headless and the windowed path alike. Both halves are needed: with the ICD named but no flag, the first Vulkan attempt finds only lavapipe and passes it over, the all-backends attempt finds the RTX 4070, and the render lands on the GPU — `mise run frame -- --film ctry --ticks 400` recorded `NVIDIA GeForce RTX 4070 Laptop GPU`. With the flag but no `VK_DRIVER_FILES`, Vulkan has no CPU adapter and the same frame recorded `Microsoft Basic Render Driver`, WARP.

## 4. Check the adapter

```powershell
(Get-Content -Raw build/parity/report/ctry_current/report.json | ConvertFrom-Json).adapter | ConvertTo-Json -Compress
```

prints

```text
{"name":"llvmpipe (LLVM 21.1.7, 256 bits)","class":"cpu"}
```

on lavapipe, and `{"name":"NVIDIA GeForce RTX 4070 Laptop GPU","class":"hardware"}` on the GPU. The LLVM version moves with the Mesa release. `Microsoft Basic Render Driver` with class `cpu` is WARP: the loader did not find the ICD (a relative path, or the wrong JSON), and the all-backends attempt took the software adapter it found. The GPU's own name with class `hardware` on this setup indicates `--software-only` did not reach the render. The report copies the adapter from the render's `render.json`, so re-render rather than edit it. A run overwrites `build/parity/report/<film>_current`, so copy a report elsewhere before switching adapters:

```powershell
Copy-Item build/parity/report/ctry_current build/parity/report/ctry_lavapipe -Recurse
```

Without a `[ctry.expected.lavapipe]` table in [`references.toml`](../../research/parity/references.toml), the run's comparison line says `no expected score for lavapipe yet: add it`; #455 adds those rows. A `crates/` tree that differs from the row's recorded one makes the line say `crates/ changed` instead, and its `delta` is then not a verdict.
