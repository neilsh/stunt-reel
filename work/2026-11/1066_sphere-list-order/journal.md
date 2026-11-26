# Journal

## 2026-11-26: a shape's primitives at their placement's depth, one rank step apart, in list order

`[Bounded Observation]`

- **Question**: does a GPU form that draws a shape's `SPHERE`s, and the polygons around them, in list order, while the shape still depth-tests against other objects, raise the reference films' scores, and does it conflict with the SPEC § 2.1 non-goal on a painter?
- **Track**: heuristic.
  The rule behind it (a shape's primitives paint in list order, [`render-model.md`](../../../research/parity/render-model.md) § 2) is read in [#1030](../1030_close-shape-order/journal.md#2026-11-24-list-order-explains-the-bomb-trees-not-the-canyon-rock) off a CPU painter checked against the capture, not cited at an image offset for this form.
- **Form** (`DBG_SPHERE_ORDER`, not committed; the diff is [`switches/DBG_SPHERE_ORDER.diff`](switches/DBG_SPHERE_ORDER.diff), written against `main` at `25eb9586`):
  - The decoder marks each `OP_SPHERE`'s 20 faces.
    A shape holding one gives each primitive a list-order rank, 1 to 255, in the vertex's padding byte: a sphere's 20 faces share one rank, every other polygon has its own.
    The weld key includes the rank.
  - A baked world prop's vertex carries its placement's origin in the apex stream; a shape drawn in place uses its model origin.
  - The vertex shader sets a ranked vertex's depth to its origin's depth plus 4.8e-7 (8 steps of `Depth24Plus`) times its rank, so a later primitive is nearer than an earlier one and a shape is still tested against other objects at its origin's depth.
    The compare stays `Greater`, so no pipeline changes.
    A corner an outline collapses to the screen centre (a back-facing polygon's) keeps its own depth.
- **Target frames** (the issue's): `--target bomb:2070-2179 --target bomb:2289-2388`, the two ranges that hold ticks 2080 and 2300.
- **Command** (GPU, RTX 4070 Laptop; `main` at `25eb9586` with the uncommitted switch): `mise run sweep -- --var DBG_SPHERE_ORDER=0,1 --track heuristic --record work/2026-11/1066_sphere-list-order --topic <words> --images work/2026-11/1066_sphere-list-order/images --target bomb:2070-2179 --target bomb:2289-2388`.
  The flags were typed in the command; this entry was written after the sweeps.
- **First run** ([`sweeps/flat-depth-by-list-rank.toml`](sweeps/flat-depth-by-list-rank.toml)): `winner: DBG_SPHERE_ORDER=1 adopts (heuristic target idx +0.0172, 21/21 frames up; films ok; worst target frame +0.0039 bomb:2102; 18 frames down >0.005, listed)`.
  Seven of those 18 frames are `balloon` 376 to 441, down 0.0211 to 0.0315: the capture | baseline | variant picture of `balloon` 386 ([picture](images/balloon-386-flat-depth-by-list-rank-guard.png)) shows olive streaks fanning from the pilot over the ground, which the baseline does not draw.
  `[Hypothesis]`: they are outline corners a back-facing polygon collapses to the screen centre, which the variant gave a real depth, so a quad whose corners did not all collapse drew a wedge from the centre.
  The streaks are gone with collapsed corners left at their own depth, and the second run measures that form; the cause was not isolated further (skipping every line corner also removed them).
- **Result** ([`sweeps/flat-depth-by-list-rank-collapsed-corners-kept.toml`](sweeps/flat-depth-by-list-rank-collapsed-corners-kept.toml); `mise run judge -- --recheck` on it prints the same winner line): `winner: DBG_SPHERE_ORDER=1 adopts (heuristic target idx +0.0172, 21/21 frames up; films ok; worst target frame +0.0039 bomb:2102; 7 frames down >0.005, listed)`.

  | Film | `0` (`main`) | `1` | Δ |
  |---|---|---|---|
  | ctry | 0.9439 | 0.9442 | +0.0003 |
  | intro | 0.9069 | 0.9069 | +0.0000 |
  | land | 0.9312 | 0.9313 | +0.0002 |
  | balloon | 0.9068 | 0.9081 | +0.0013 |
  | traintnl | 0.9164 | 0.9164 | +0.0000 |
  | bomb | 0.9085 | 0.9113 | +0.0028 |
  | location | 0.8967 | 0.8970 | +0.0003 |

  - No film falls; no film rises by 0.002 or more except `bomb`, so the film-mean branch does not adopt and the target branch does: the pooled target index agreement rises by 0.0172, every one of the 21 scored target frames rises, and each range's own target mean rises.
  - The seven frames down more than 0.005 are `location` 1651 to 1772 (five frames, down 0.0057 to 0.0145) and `intro` 2718 (−0.0059).
    `intro` 2718 ([picture](images/intro-2718-flat-depth-by-list-rank-collapsed-corners-kept-guard.png)): a dark slanted bar, by its position a propeller blade, draws over the aircraft's body in the variant where the baseline hides it behind the body, and the capture shows neither.
    `location` 1717 ([picture](images/location-1717-flat-depth-by-list-rank-collapsed-corners-kept-guard.png)): the forest's tree shapes cover each other in another order; the capture's trees are discs and ours stay polygons, so the picture does not show which order is nearer.
    Not found: why `location` loses where `bomb`'s trees gain.
  - Frames outside the target that moved more than 0.005: `intro` 1, `balloon` 18, `bomb` 54, `location` 16, the other three films none (the sweep's count, both directions).
- **SPEC § 2.1**: the form is not a CPU rasterizer or a painter's sort, and the draws stay in the GPU depth buffer, so the non-goal's "no CPU software rasterizer" is not broken.
  It does make depth within one shape a list-order rank instead of geometry, which [`SPEC.md`](../../../docs/SPEC.md) § 2.1 words as "Painter's Algorithm / BSP sorting give way to … depth buffering" and which [ADR 0045](../../../docs/adr/0045-flat-ground-is-painted-in-walk-order.md) already does for the flat ground.
  If adopted it needs an ADR amending that line, and the issue's own condition applies: the only form found needs per-draw flattened depth, so **the owner decides before it is adopted**.
- **Verdict**: the form adopts by the heuristic rule, and is not adopted, awaiting the owner.
  Productionising it would change the seam contracts (a rank in `SodVertex`'s padding byte, a per-vertex origin on `SodModelIr`), so it also needs [`changing-seam-contracts`](../../../.agents/skills/changing-seam-contracts/SKILL.md) and a lavapipe repin.
  The prototype's switch, the thread-local rank map and the weld-key offset are not fit to commit.
- **Lives in**: [`prop-shape-loss.md`](../../../research/parity/prop-shape-loss.md) § 2.3.
