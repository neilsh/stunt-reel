---
title: "Why does PLAYONE draw a superset archive's pages differently from a film's own?"
started: 2026-11-09
issue: 348
outcome: "Not a timing shift, and the extra props are not needed: inert padding of the props' count and bytes changes more pages (CTRY 42/111, TOD 51/109 identical, against 72/112 and 108/115 for the props), and archives captured twice replay bit for bit; which property of the archive counts is open."
---

# Why does PLAYONE draw a superset archive's pages differently from a film's own?

Follows [#301](../301_superset-palettes-playone/README.md). The plan is in [`spec.md`](spec.md) and the run in [`journal.md`](journal.md). The finding lives in [`linking.md`](../../../research/makeone-exe/linking.md) § 7.2, Ruled out, and open questions 5 and 8.

## What changed

- `mise run capture-compare -- A B --shift N` looks for each page of A that B does not draw identically at its tick among B's pages within N ticks, and lists the ticks only one capture keeps and every page left unmatched with its bounding box.
- `mise run pad-all -- OWN.ALL -o OUT.ALL (--add-from SOURCE.ALL | --inert COUNT BYTES)` writes a film's archive with another archive's missing chunks, or with inert zero-filled chunks from `0xF001`.
- `stunt_reel.all_archive` gains `archive_chunks` and `pack_archive`, which `stub_sound_samples` now uses.

Bench: `<data root>/bench/vault-{ctry,tod}/348/unpatched/`, each with `compare.txt`.
