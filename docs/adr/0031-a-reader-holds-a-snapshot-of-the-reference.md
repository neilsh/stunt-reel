# A reader holds a snapshot of the reference capture it validated

## Status

accepted 2026-11-03, implemented. Builds on
[ADR 0028](0028-a-film-has-one-capture-of-each-kind.md), whose swap it makes safe for readers, and
[ADR 0029](0029-references-name-each-films-builds-and-reference.md), whose pin it checks.

## Context

ADR 0028 replaces a film's capture by swapping a new directory into `captures/<film>/frames`, and
`references.toml` pins the reference by `sha256`. The swap is coordinated between writers (a
`<kind>.lock` beside the capture) but not with readers. `references.reference_dir` checked the
digest and returned the store's path, and the parity loop then read from that path for minutes: the
render reads the capture's ticks, and `stuntreel parity` reads its frames only once the render ends.
A `mise run capture-ref` of the same film in another worktree, which shares the data root, could
publish in that window. The score would then use a capture that no longer matches the pin, or the
ticks of one capture and the frames of the other, and nothing would say so. On Windows the swap
could also fail outright, because a directory cannot be renamed while a reader holds a file open
inside it, and the capture that had just been made would be lost.

A capture is a few files (`meta.json` and the frames, 4 to 216 MB on the data root today), and a
published file is never changed in place: a writer only swaps whole directories.

## Decision

- **A reader holds a snapshot.** `capture_store.snapshot(directory)` is a context manager that
  makes `<kind>.read-<id>/` beside the capture, a tree of hard links to its files, and removes it
  when the block ends. Because a published file is never changed, the links are the capture as it
  was when they were made, whatever a later swap does. They cost no space, and they are on the
  store's volume by construction. A file system without hard links gets a copy.
- **The snapshot proves that no swap landed while it was made.** It compares the directory's file
  system identity (`st_dev`, `st_ino`) before and after linking. A rename keeps that identity and a
  swap changes it, so a mismatch means the links may mix two captures, and they are made again, up
  to three times.
- **The pin is checked on the snapshot.** `references.open_reference(root, film)` replaces
  `reference_dir`: it takes the snapshot, hashes it, and yields it only when the hash is the pin.
  `parity_pipeline.reference_job` yields a job whose `capture` is that snapshot, for as long as the
  render and the score run. Every caller (`parity_run`, `parity_frame`, `parity_sweep`,
  `parity_probe` and `parity-bench run`, `errors-make` and `errors-example`) reads through a `with`
  block, so no caller can read the store's path after it checked the hash.
- **A dead reader's snapshot is removed later.** A snapshot left by a killed process is removed by
  the next snapshot of the same capture once it is a day old; no scoring run holds one that long.

## Considered Options

- **A reader lock that `publish` respects.** Rejected: scoring holds a capture for minutes, so a
  publish would either wait that long behind every reader or time out and lose a capture that took
  minutes to make. Shared reader locks also need a reader count that a killed process cannot leave
  wrong, which the `mkdir` claim of the swap lock does not give.
- **A copy taken when the reference is validated.** Rejected in favour of hard links: the same
  guarantee, but a run would copy up to 216 MB per film before it starts. It stays as the fallback
  where links are not supported.
- **Re-checking the digest after scoring, and refusing a result whose capture changed.** Rejected:
  it detects the race but still spends the run, and it does nothing for the Windows rename that a
  reader's open file makes fail. It would also hash the capture twice per run.
- **Accepting the race and documenting it.** Rejected: the shared data root makes the race a normal
  use, a capture-ref in one worktree and the parity loop in another, and the failure is a silent
  wrong score in [`log.md`](../../research/parity/log.md).

## Consequences

- A score names a `frames.read-<id>` directory as its reference in the `stuntreel parity` command
  line; the directory is gone after the run, and the pin, not the path, is what identifies the
  capture.
- A swap during a run leaves the old capture's files alive until the snapshot is removed. On
  Windows a reader's open file can keep `publish` from deleting the old capture, which then stays
  as a `.old-*` sibling, as ADR 0028 already allows.
- The batch survey's `current_job` and `parity-bench --batch` still read the store's path of an
  unpinned capture. `capture_store.snapshot` gives them the same protection when they need it.
