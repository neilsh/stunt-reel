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
  store's volume by construction. A file system without hard links gets a copy, made under
  the swap lock like the links, so a `publish` waits up to five minutes for the lock rather
  than the 30 seconds a swap alone would need.
- **The links are made under the swap lock.** No `publish` lands between two links, so a
  snapshot never mixes two captures. The lock is held for the linking, which takes milliseconds,
  and released before the caller reads; a `publish` waits for it as it waits for another swap.
- **The pin is checked on the snapshot.** `references.open_reference(root, film)` replaces
  `reference_dir`: it takes the snapshot, hashes it, and yields it only when the hash is the pin.
  `parity_pipeline.reference_job` yields a job whose `capture` is that snapshot, for as long as the
  render and the score run. Every caller (`parity_run`, `parity_frame`, `parity_sweep`,
  `parity_probe` and `parity-bench run`, `errors-make` and `errors-example`) reads through a `with`
  block, so no caller can read the store's path after it checked the hash.
- **Leftovers are removed by the next snapshot.** Under the swap lock, a snapshot removes every
  `.old-*` sibling, which a `publish` leaves when a reader's open file keeps it from deleting the
  old capture, and every `.read-*` older than a day, which a killed reader leaves; no scoring run
  holds one that long. A `.partial-*` belongs to a writer that may still be running and is left
  alone.

## Considered Options

- **A reader lock that `publish` respects.** Rejected: scoring holds a capture for minutes, so a
  publish would either wait that long behind every reader or time out and lose a capture that took
  minutes to make. A shared reader lock that `publish` takes exclusively would avoid the count a
  killed reader leaves wrong, but it still makes the writer wait for the longest reader.
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
  as a `.old-*` sibling, as ADR 0028 already allows, until the next snapshot removes it.
- The batch survey's `current_job` and `parity-bench --batch` still read the store's path of an
  unpinned capture. `capture_store.snapshot` gives them the same protection when they need it.
