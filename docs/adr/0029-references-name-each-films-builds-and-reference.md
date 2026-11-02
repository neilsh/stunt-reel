# `references.toml` names each film's builds and reference capture

## Status

accepted 2026-11-01, not yet implemented: the order of work is in
[the capture store plan](../process/plans/capture-store-deepening-2026-11-01.md). Answers the
decision [#80](https://github.com/neilsh/stunt-reel/issues/80) asks for. Builds on
[ADR 0028](0028-a-film-has-one-capture-of-each-kind.md).

## Context

A film runs today on its own folder's `PLAYONE`: the demo and `stuntisl` ship the unpatched build,
and `siarchive`'s NewPLAY folder ships patch3. The batch survey keeps a hand-written list,
`UNPATCHED_CAPTURES`, of the films that need the other build. A fresh machine relearns every
exception by trial, and some of those trials are 15-minute `MAKEONE` hangs.

The evidence ([`patch3.md` § 3](../../research/playone-exe/patch3.md#3-which-build-each-film-needs))
shows that the two builds draw the same picture, apart from the mouse pointer and a film clock that
runs 0 to 2 ticks ahead. The known stalls on patch3 are archive mismatches: TOD and INTRO stall with
their shipped `.ALL`, which the unpatched `MAKEONE` wrote, and play with one from the patch3
`MAKEONE`. An archive is tied to its build when the film uses a resource the patch replaced
(BIGMAN), and is byte-identical from both builds otherwise (COUNT, EXIT, EXIT2). The two can also
differ for one film: the patch3 `MAKEONE` never returns to DOS on EXIT/EXIT2, while the patch3
`PLAYONE` plays them.

The parity loop picks its films from a fixed list, `FILMS`, while the batch survey scores any film,
so a surveyed film has no route into the loop.

## Decision

- **patch3 is the default** for every film, for `MAKEONE` and `PLAYONE` alike. A capture plays the
  film's stored archive, not its shipped `.ALL`.
- **A film's row in `references.toml` can name its builds**: `makeone` and `playone`, each `"patch3"`
  or `"unpatched"`, defaulting to `"patch3"`, plus `reason`, which is required whenever either is
  unpatched. Capture and `make-all` use the builds the row names. A capture's `meta.json` only
  records what actually ran; when the two disagree, the next capture follows the row.
- **The fallback is for a film with no row**: if patch3 stalls (the trace budget runs out with the
  film clock stuck short of the film's end) or the emulator dies, try the unpatched build. Never
  fall back on a replay that diverges from its trace, which is drift from boot to boot (BIGMAN), not
  a build problem. A tool that falls back prints the row it suggests; only a reviewed commit adds it.
  `UNPATCHED_CAPTURES` is deleted.
- **A film enters the parity loop when its row has `sha256`**, the digest of its reference capture.
  `FILMS` is deleted. Promoting a surveyed film means committing a row with that digest.

## Considered Options

- **Let the store remember each film's build** (whatever build its last capture used). Rejected:
  the data root lives on one machine, so a new machine would repeat every trial.
- **Have tools write the rows themselves.** Rejected: promotion stays a reviewed commit, as in
  [ADR 0022](0022-captures-are-add-only-beside-a-read-only-corpus.md), and the standard library
  cannot write TOML.
- **One `build` field for the pair.** Rejected: EXIT/EXIT2 need the unpatched `MAKEONE` and play on
  patch3.
- **Rename the file to `films.toml`.** Rejected for now: it would ripple through ADRs, scripts and
  `AGENTS.md` for a name change only.

## Consequences

- Demo and `stuntisl` films move from the unpatched build to patch3.
- The `ctry` and `intro` references stay pinned as they are. Recapturing them on patch3, repinning
  them and re-measuring `noise_sigma` is a step of its own after the refactor, logged in
  [`research/parity/log.md`](../../research/parity/log.md).
- Films whose patch3 `MAKEONE` writes a complete archive but never returns to DOS depend on
  [#76](https://github.com/neilsh/stunt-reel/issues/76) being fixed first.
