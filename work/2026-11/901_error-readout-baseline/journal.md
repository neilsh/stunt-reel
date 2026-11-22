# Journal

## 2026-11-22: The first error-readout baseline of the seven references

**Question**: which kinds of error does the vision-model readout see on the seven Patch #3 references at current `main` rendered on lavapipe, and has it moved since the 2026-11-16 readout ([`477_vault-attribution`](../477_vault-attribution/journal.md#2026-11-16-error-readout-on-the-patch-3-references)), before #894, #896, #897 and the #811 PR?

**Method**: `main` at `b9441a06`, which holds #894 (`5fbfe844`, a scorer change), #896 (`b028f7d3`), #897 (`581453ed`) and the #811 PR, #902 (`f95ec4a0`), each an ancestor of it. `VK_DRIVER_FILES` set to the data root's Mesa 25.2.8 `lvp_icd.x86_64.json`, `mise run parity -- --software-only`: every report's `adapter` is `llvmpipe (LLVM 21.1.7, 256 bits)`, class `cpu`; `expected/lavapipe.toml` pins LLVM 20.1.2, so the run is `not comparable: other adapter`, with SSIM and IoU within 0.000002 of the pinned rows on all seven. Then, per film, `errors-make` (12 sheets, seed 1), two Haiku passes (one fresh subagent per brief), `errors-disputes`, one Sonnet tie-break subagent on the disputed sheets (ctry 8, intro 2, land 4, balloon 1, traintnl 2, bomb 1, location 2), and `errors-score` with no `--against`. `errors-score --against research/parity/readouts/<film>.json` on the same run then printed `changes since ...: none` for all seven. `errors-table` reads the batch survey's reports, so each film's `build/parity/report/<film>_current/report.json` was copied to `build/parity/batch/<film>/report/report.json` first.

**Result**: no category reaches 3 frames of 12 on any film (the lead threshold of [`batch-vault-films.md`](../../../research/parity/batch-vault-films.md) section 4). Frames graded 2 or more: `ctry` none, `balloon` none; `intro` `background-misregistration` 2 (ticks 1355, 2597) and `shadow-missing` 1 (2773); `traintnl` `background-misregistration` 2 (123, 1013); `bomb` `scenery-missing` 2 (1585, 1904) and `background-misregistration` 1 (2850); `location` `background-misregistration` 1 (5611); `land` four categories on one frame each, three of them on tick 419 (`aircraft-misplaced`, `scenery-missing`, `background-misregistration`) and `shadow-shape-wrong` on 496. `land`'s tick 419 `other` note says the render shows a huge close aircraft and a hill where the capture shows a small distant one. `sea-band-wrong` is 0 frames on all seven, where on 2026-11-16 it was 7 (ctry), 6 (traintnl), 4 (bomb), 3 (land) and 2 (location, intro 1). `other` notes: ctry 0, intro 4, land 1, balloon 1, traintnl 5, bomb 0, location 2. Table (`errors-table`):

| Film | Ticks | Graded | Categories graded 2+ (frames) | `other` notes | SSIM (scored frames) |
|---|---|---|---|---|---|
| `ctry` | 14–980 | 12 | none | 0 | 0.938 (114) |
| `intro` | 1002–3477 | 12 | none | 4 | 0.883 (209) |
| `land` | 12–903 | 12 | none | 1 | 0.924 (97) |
| `balloon` | 12–1178 | 12 | none | 1 | 0.906 (107) |
| `traintnl` | 12–1233 | 12 | none | 5 | 0.911 (112) |
| `bomb` | 12–3477 | 12 | none | 0 | 0.895 (316) |
| `location` | 134–6161 | 12 | none | 2 | 0.873 (732) |

**Verdict**: the disappearance of `sea-band-wrong` is a lead that the merged render PRs removed it, not an attribution to any one of them: the two readouts used other renders (RTX 4070 then, lavapipe now), other `main` commits, and the ticks are the same 12 per film only where the scored set did not move. Per-PR attribution is out of scope of the issue. On the issue's open question: this baseline took 14 Haiku runs (69 to 76 thousand subagent tokens each) and 7 Sonnet tie-breaks (44 to 57 thousand each) for seven films, so a per-PR run would repeat that per render PR; [`error-readout.md`](../../../.agents/skills/improving-render-parity/error-readout.md) now says per batch, which the baseline's one-time cost supports but one baseline does not settle.

**Lives in**: [`readouts/`](../../../research/parity/readouts/) (the seven `readout.json` and `baseline.toml`), [`batch-vault-films.md`](../../../research/parity/batch-vault-films.md) section 7, [`error-readout.md`](../../../.agents/skills/improving-render-parity/error-readout.md).
