# `make-all` generates archives with `MAKEONE.EXE`

## Status

accepted 2026-10-29. The design and decision numbers (D1 to D10) are in
[the make-all plan](../process/plans/make-all-2026-10-29.md); the evidence is in
[`research/makeone-exe/driving.md`](../../research/makeone-exe/driving.md). Builds on
[ADR 0021](0021-capture-chooses-its-control-port.md) and
[ADR 0022](0022-captures-are-add-only-beside-a-read-only-corpus.md).

## Context

`PLAYONE.EXE` plays a film only with its `.ALL` archive beside the `.FLM`. The demo ships
that pair for `INTRO` and `CTRY` only, and the full game ships `.FLM` and `.TKE` files with
no `.ALL`, so `capture-ref` could capture two films. `MAKEONE.EXE`, the retail film linker,
writes the archive. A spike on `BALLOON.FLM` showed it runs under the capture harness,
writes the same 46,702 bytes every time, and that `PLAYONE` plays the result.

## Decision

`mise run make-all -- --film X.FLM` runs `MAKEONE.EXE` in DOSBox-X through the capture
session and stores the archive it writes.

- **Driven like the player.** `run_session` takes a profile (how to stage, what to type);
  `MAKEONE` types the film's first letter and Enter. Completion is `VGA MODE` reporting
  `M_TEXT` after a graphics mode was seen, read through a new `video_mode()` transport
  operation, with a timeout.
- **Private copied mounts.** Each run stages a fresh mount holding exactly the engine
  files, `RES\` and the one film; files are copied, never linked, and `PLAYONE` mounts get
  the archive copied in from wherever it is stored.
- **Stored once.** The archive goes to `captures/all/<film>/<id>/` with a `meta.json`
  (film and archive hashes, the `MAKEONE` build, the staged files), published by rename
  with `meta.json` last, and an existing id is refused. `captures/` is already a shared
  link, so no new link, migration or reap rule is needed.
- **Resolved, never generated silently.** `resolve_all` returns a sibling `.ALL`, else the
  stored archive with the greatest id for the film's hash, else fails naming `make-all`.
  A stored archive that no longer matches its recorded hash is an error.
- **Scoring is separate.** Capturing a generated film is in scope; scoring it needs a
  `FILMS` entry and a reviewed `references.toml` row and is a follow-up.

## What will enforce this

- `tests/test_all_archive.py`: the archive check, the add-only publish and the resolver.
- `tests/test_tac_staging.py`: the `MAKEONE` mount holds exactly the listed tree and a conf
  without `playone.exe` is rejected.
- `tests/test_tac_makeone.py`: the keys, text mode before graphics does not complete, the
  timeout, and the mount is removed after every outcome.
- `tests/test_make_all_script.py` and `tests/test_tac_capture_session.py`: the reserved
  `ALL` stem and an existing id are refused before an emulator starts, and `capture-ref`
  finds a stored archive.

## Considered Options

- **Symlinks for adjacency.** Rejected: Windows symlinks need privilege, [ADR 0018](0018-reaping-unlinks-the-data-root-links-first.md)
  records junction removal differing between git builds, and copies are small.
- **Generating inside `capture-ref`.** Rejected: it hides a run of 90 s or more.
- **Writing the archive beside the `.FLM` in `corpus/`.** Rejected by ADR 0022.
- **Our own `.ALL` writer.** Deferred: it needs the packaging reverse-engineered first;
  `MAKEONE` output becomes its oracle.
- **Plain `autotype` as the primary route.** It works with a long wait but cannot tell
  completion from a stall; it is the fallback.

## Consequences

Each new film costs a run of its own length, because `MAKEONE` plays the film in real time.
Generated archives accumulate under `captures/all/` like captures do and are pruned
explicitly. A `.ALL` made under DOSBox-X may carry a different sound set-up than one made
on the original machine; frames are unaffected.

Archives are add-only (ADR 0022) and there is no overwrite path. When `resolve_all` reports a
stored archive that no longer matches its `meta.json`, or whose `meta.json` cannot be read, the
remedy is to delete that `captures/all/<film>/<id>/` directory and rerun `make-all`; the error
text says so. If the emulator fails to stop after a good run, the archive is kept and a warning
is printed, because the run took minutes and its output is already complete.
