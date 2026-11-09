# Spec: why a superset archive's pages differ on `PLAYONE`

Follows [#301](../301_superset-palettes-playone/journal.md): with the palette items in and sound stubbed, a superset `.ALL` plays on `PLAYONE` with byte-equal palettes, but some pages differ from the film's own archive (CTRY unpatched 72 of 112 identical, TOD 108 of 115), while two own captures agree on every page. Some superset pages sit one film tick from the own archive's (12, 134, 178 against 14, 133, 177). Choices settled with the user on 2026-11-09.

## Stage 1: a timing check, no new captures

- **`capture-compare --shift N`** (default 0; output unchanged at 0): for each page of A at film tick `t` with no identical page of B at `t`, look for a pixel-identical B page at ticks `t-N`..`t+N`, and report how many match that way. Tested on synthetic captures under `tests/` only.
- Run with `N=2` on `<data root>/bench/vault-ctry/301/unpatched/` and `vault-tod/301/unpatched/`, `own-1` against `superset`.
- Only an exact pixel match counts as a timing shift. If every whole-view differing page is a shift, the question becomes "why does a bigger archive change frame pacing"; the small 1–104 pixel boxes stay a separate question.

## Stage 2: a padding probe

- Build an own `CTRY.ALL` padded with inert chunks in an unused resource index (`0xF0xx`) and capture it once.
- If `PLAYONE` refuses or misbehaves, fall back to item numbers above `SPRITES.RES`'s highest item.

## Stage 3: two arms on CTRY and TOD, unpatched build only

- **(a)** the own archive plus the superset's extra shape chunks;
- **(b)** the own archive plus inert padding with the same chunk count and total bytes as (a).
- One capture per arm plus one own-archive control per film per run; compare with `capture-compare` (pixels, and with `--shift` the tick sets drawn).
- Bench: `<data root>/bench/vault-<film>/348/unpatched/`; `--name 348-<film>` for `make-all` and `capture-ref` (CTRY's references pin refuses its own name).

## Recording

Findings go to [`linking.md`](../../../research/makeone-exe/linking.md) § 7.2 and open questions 5 and 8, by the `recording-findings` skill, with a journal entry per stage written before the next starts. A fresh reviewer subagent reads the research diff before the push. One PR, stacked on [PR 349](https://github.com/neilsh/stunt-reel/pull/349) (it carries `capture-ref --archive` and `make-all --out`, which stages 2 and 3 need; PR 349 is itself stacked on PR 347).
