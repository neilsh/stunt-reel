# Journal

## 2026-11-13: dropping undrawn shapes before the upload

- **Question**: does `stuntreel --game` render the same and run faster on lavapipe when the scene keeps only the shapes a film can draw (`FilmScene::drawn_only`) before `SceneRenderer::new` uploads them, instead of all 2,516?
- **Method**: release builds of `3d680420` (before) and `ce861b2b` (after) in WSL Ubuntu on Mesa lavapipe (`llvmpipe (LLVM 21.1.8, 256 bits)`, `VK_DRIVER_FILES` set to `lvp_icd.json` only, 16 threads). The machine was shared with two GPU parity sweeps running at the same time. Each binary rendered `corpus/stisldem/VAULT/CTRY.FLM` and `INTRO.FLM` whole with `--game corpus/stuntisl --headless --out-dir`; the store was hashed as the SHA-256 of the `sha256sum` listing of `frames.zst`, `layers.zst` and `palettes.zst`. Timings are wall clock. One-tick renders used `--at-ticks 0`, five runs per binary, with the before binary on the demo `.ALL` as the archive baseline. Byte identity came from three hashed whole-film runs per binary and film. Whole-film timings ran separately, interleaved before, after and archive, unhashed: four rounds for CTRY and three for INTRO.
- **Result**: `frames.zst`, `layers.zst` and `palettes.zst` are byte-identical before and after on both films, on each of three hashed runs per binary (separate from the interleaved timing rounds below, which were not hashed; `render.json` and `preview/` were not hashed): CTRY `55be1054cabae42f…`, INTRO `2a85bd734185623e…`. The load report still says 2,516 models loaded, since it is printed before the drop. One-tick renders, five runs each in run order, then the median. The archive column is the before binary on the demo `.ALL`, not `ce861b2b`:

  | Film | `--game` before | `--game` after | archive |
  |---|---|---|---|
  | CTRY | 0.90 0.84 1.17 1.01 0.84; 0.90 s | 0.46 0.51 0.60 0.64 0.68; 0.60 s | 0.23 0.29 0.31 0.29 0.26; 0.29 s |
  | INTRO | 3.08 1.53 2.24 1.72 2.70; 2.24 s | 1.13 1.84 1.16 1.48 1.54; 1.48 s | 0.55 0.49 0.48 0.49 0.76; 0.49 s |

  Whole films, interleaved rounds, before / after / archive: CTRY 8.35 / 4.78 / 4.35, 5.17 / 4.20 / 4.60, 10.62 / 9.20 / 8.13, 9.34 / 8.69 / 4.50 s; INTRO 23.65 / 16.21 / 21.84, 14.11 / 13.46 / 13.79, 17.06 / 18.17 / 17.54 s. One binary's runs of one film vary by up to 2.2 times under the shared load, so these runs do not resolve a per-frame difference. The fastest runs are CTRY 5.17 / 4.20 / 4.35 s and INTRO 14.11 / 13.46 / 13.79 s.
- **Verdict**: adopted for output equality and the one-tick saving. A one-tick render includes drawing one frame, so it is not startup alone. CTRY's before and after ranges do not overlap; INTRO's do (1.53–3.08 against 1.13–1.84 s), though its median falls. The shared machine's noise hides any per-frame effect. The drop also runs on the archive path, where its output is unmeasured here.
- **Lives in**: [`research/makeone-exe/linking.md` § 7.1](../../../research/makeone-exe/linking.md#71-rendering-straight-from-res) and its open question 7.
