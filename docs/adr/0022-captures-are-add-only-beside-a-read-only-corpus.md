# Captures are add-only beside a read-only corpus

## Status

accepted and implemented 2026-10-29: the landing steps and log are in
[the data-root split plan](../process/plans/data-root-split-2026-10-29.md). Supersedes
the write guard of [ADR 0008](0008-worktrees-share-one-read-only-data-root.md); one
data root per machine, linked into every worktree, stays. The
`captures\<film>\<capture id>\` layout is superseded by
[ADR 0024](0024-captures-are-filed-by-film-then-kind.md); add-only stays.

## Context

ADR 0008 kept everything gitignored in one tree and guarded it with
`STUNT_DATA_WRITE=1`, checked by `is_shared` against the whole root. Two writers reached
it: `capture-ref`, whose default `--out` resolves through a link into the root, so the
guard tripped in normal work; and oracle generation, which wrote `corpus/oracle/`. The
guard fenced 640 MB of irreplaceable game files in order to fence off 24 MB of our own
output.

It also guarded the wrong act. The damaging write was never to the game files: it was a
capture replacing the reference. `clear_frames` in
[`capture_playone_reference.py`](../../python/scripts/capture_playone_reference.py)
empties `--out` before sampling, so a recapture of `ctry` overwrites the reference in
place and moves every other worktree's parity baseline in the middle of a sweep. And the
oracle was never evidence: [`stream_oracle_intro`](../../python/stunt_reel/tac/streamer.py)
builds it from a `MockTransport` fed hand-written kinematics.

## Decision

The data root is split by what writes it. `corpus\` holds the original game files
(`stisldem`, `siarchive`, `stuntisl`, `patches`); once the oracle leaves, nothing this
project runs writes there. `captures\<film>\<capture id>\` holds captures, each written
once into a new directory and never changed. Which capture parity scores a film against
is not a property of the data root: a committed `research/parity/references.toml` names
the reference capture by id and content hash, so promoting one is a reviewed commit, the
choice has a history, and two branches can name different references. The synthetic
oracle becomes a per-worktree build output.

## What will enforce this

These guards replace the write guard; the tests named here carry them.

- **The capture id.** [`capture_playone_reference.py`](../../python/scripts/capture_playone_reference.py)
  writes a new id directory by default and refuses an existing one, which replaces
  `clear_frames`; `tests/test_tac_capture_session.py` covers the refusal.
- **The pointer.** Parity resolves a film's reference through `references.toml` with
  [`references.py`](../../python/stunt_reel/references.py) and fails, naming the id, when
  that capture is absent or its hash differs (`tests/test_references.py`).
- **The links.** `LINK_TARGETS` in [`dataroot.py`](../../python/stunt_reel/dataroot.py)
  names no oracle and no `target_bin`, so no checkout path leads a writer into
  `corpus\`.

## Considered Options

- **Keep one tree and the write guard.** Rejected for the reasons above: a consent gate
  that everyday captures trip, guarding the game files while the reference stayed
  overwritable.
- **A reference pointer inside `captures\<film>\`.** Rejected: machine-wide mutable
  state again, with no review and no history, and one branch's promotion changes every
  other branch's score.

## Consequences

`STUNT_DATA_WRITE`, `require_shared_write` and `is_shared` are removed with nothing in
their place. The `corpus/oracle` and `target_bin` links go. A worktree still borrows one
link per corpus folder, because `corpus/README.md` and `corpus/siarchive.md` are tracked
and `corpus/` cannot itself be a link, plus one link for `captures\`.

`corpus\` carries no read-only attribute. On Windows `attrib +R` does not stop new files
in a directory, and the `icacls` deny rule that does must be lifted for every migration;
with no writer left it would guard nothing. It is the first response if a stray write is
ever seen.

Captures accumulate. Removing them is a separate, explicit prune that never touches a
capture `references.toml` names. A checkout whose named reference is absent on this
machine fails parity with that message rather than scoring against another capture.
