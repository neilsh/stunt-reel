# A captured page is paired by the slot pass before the one that drew it

## Status

accepted 2026-11-27 for [#1163](https://github.com/neilsh/stunt-reel/issues/1163); the owner approved the build on 2026-11-27 after the plan's pass bar held on all seven films.
Amends the pairing step of [ADR 0028](0028-a-film-has-one-capture-of-each-kind.md) and the `meta.json` fields of [ADR 0048](0048-the-python-parity-adapter-is-checked-against-a-generated-schema.md): a frame may carry two more words, and the score reads them.

## Context

The score paired a captured page with the render at its tag `film_tick`, which the renderer models as the state at `film_tick - 1`.
On the seven reference films that left a tick or two of timing error on up to nearly half of a film's pages (INTRO's 161 of 347): the best offset in -2..+2 per page would have raised LOCATION by 0.0195 and INTRO by 0.0191 ([`evidence-limits.md` § 3](../../research/parity/evidence-limits.md#3-what-is-not-yet-evidence)).
Reading PLAYONE's slot pass at the kept frame found the cause the tag could not carry: the page on screen was composed by the slot pass before the one whose state a read at the kept frame sees, and the clock of that earlier pass is the slot clock minus the ticks word (`0x489A - 0x22DC`, Patch 3 `0x4220 - 0x1C62`; [`capture.md` § 4](../../research/playone-exe/capture.md#4-observed-results)).
The rule was fixed before the three held-out films were recaptured, and held on all of them ([the journal](../../work/2026-11/1163_pair-by-slot-clock/journal.md)).

## Decision

* **The harness records two words.**
  A window pass reads the slot pass's clock and the ticks word in the step that reads the page, and `meta.json` writes them per frame as `slot_clock` and `slot_ticks`, both optional (`PlayoneLayout.slot_clock`, `slot_ticks`; Patch 3's are inferred from the build's uniform `0x67A` shift, as its composed-page offsets are).
* **The score pairs by `render_tick`.**
  A frame's `render_tick` is `slot_clock - slot_ticks + 1`, the store keying the state at `T - 1` at `T`; a frame without both words, or whose ticks word exceeds its clock, takes its `film_tick`, which is the old pairing.
  The rule is `CapturedFrame::render_tick` in `stunt-parity` and `CapturedFrame.render_tick` in the Python adapter, and the scorer, `--compare`'s sheets and verdict, the Python pairing and `--retime` all use it.
* **`film_tick` stays the tag.**
  Reports, `--compare` and the judge join on it; no report field changes.
* **The seven reference captures are recaptured with the words**, index-identical to the ones they replace on every page (compared on rows 0..184, palettes equal), and `references.toml` pins their new content hashes; the `lavapipe` expected scores are repinned.

## Consequences

* The seven films gain 0.0013 to 0.0189 mean SSIM on lavapipe (+0.0132 over their 1,687 scored frames), with no change to the renderer; the repin is those figures.
  A candidate's gain is measured against the new pins, not the old ones.
* A capture made before the words, and one made with a build whose layout lacks them, scores at its tag as before, so the batch survey's captures and older references keep working; a render needs no change for either.
* The state a render draws for a page is now chosen per page, so a render must hold the ticks a capture's `render_tick`s name: the Python pipeline renders their range, not the tags'.
* The words are two reads of Patch 3 offsets inferred from the unpatched build's; the replay check (every page's rows 0..184 identical, the words equal across two recaptures) found them stable, and `slot_clock` is the tag or one below it on every page, which a wrong offset would be unlikely to give.
* The cause of the ticks word's values is not established (`[Hypothesis]`: passes run once per emulated frame against a 50 Hz clock); the rule uses the word as read.
* A reference's `references.toml` pin and its stored archive in the cloud-assets `captures` bundle move together: the bundle must be packed and uploaded with the owner's credentials before a cloud session can fetch the new references.
* Fidelity is judged on lavapipe ([ADR 0055](0055-fidelity-pins-on-lavapipe-and-agreement-is-measured-apart.md)); whether the gain holds on a GPU class is the agreement batch's to measure, and the capture's words do not depend on the renderer.

## Considered Options

* **Pair by the tag only, the old rule.** Leaves the timing error on up to nearly half of a film's pages.
* **Pair by the HUD clock (`h - dct`) or by the last slot clock at or below the HUD (`R_prev`).** Both scored below the slot clock on four of the five films that had them and equal to it at four places on TRAINTNL (CTRY, INTRO, LOCATION, BALLOON, [journal](../../work/2026-11/1163_pair-by-slot-clock/journal.md)).
* **Choose each page's best offset by score.** A ceiling, not a rule: it fits the render, picks up chance gains and cannot be applied to a page without a reference.
* **Store the derived tick instead of the words.** One field fewer, but the words are the evidence the variants above were scored from; they are kept and the rule lives in one function per adapter.
