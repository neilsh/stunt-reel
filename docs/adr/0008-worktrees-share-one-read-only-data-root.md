# Worktrees share one read-only data root

Each agent works in its own git worktree, wherever its tool creates it: beside
the checkout, or under a gitignored directory inside it such as
``.claude/worktrees/`` or ``.agents/worktrees/``. The corpus, the
reference captures and ``target_bin/`` are gitignored, so they live once per
machine in ``<parent-of-primary>/<repo-name>.data`` (``STUNT_DATA_ROOT`` overrides),
and ``mise run init`` links them into every worktree: ``corpus/stisldem``,
``corpus/siarchive``, ``corpus/oracle``, ``target_bin/`` and ``build/parity/reference``.
Build outputs and the virtualenv stay per worktree; downloaded tool caches are
shared, and writable, through a second link (ADR 0013).

Two consequences are deliberate. The data root is read-only to agents: the two
writers, ``mise run capture-ref`` and oracle generation, refuse unless
``STUNT_DATA_WRITE=1``, because a stray write into the shared corpus damages every
other worktree silently. And capture stays serialised machine-wide: ``58991`` is
bound by ``ListenTransport`` with ``listen(1)`` (``SO_EXCLUSIVEADDRUSE`` on Windows,
so a second capture fails at the bind), the four ``dosbox-*.conf`` profiles
hardcode it, and one DOSBox-X instance serves the whole machine.

## What enforces this

- **The write guard.** [`require_shared_write`](../../python/stunt_reel/dataroot.py) is called by both writers: [`capture-ref`](../../python/scripts/capture_playone_reference.py) when `--out` resolves into the root, and oracle generation per destination in [`models.py`](../../python/stunt_reel/tac/models.py). [`test_dataroot.py`](../../tests/test_dataroot.py) covers the opt-in and the resolution through a real junction.
- **The capture lock.** The bind in [`transport.py`](../../python/stunt_reel/tac/transport.py), covered by the port-taken case in [`test_tac_transport_framing.py`](../../tests/test_tac_transport_framing.py). It serialises captures only: a second DOSBox-X still starts, and oracle generation is not exclusive.
- **`init` on first use.** [`ensure_links`](../../python/stunt_reel/dataroot.py) repairs a worktree that never ran `mise run init` at the point the corpus is read — `capture-ref`, `parity` and `sweep` — replacing a `.gitkeep` placeholder with the junction, creating a shared directory that is still empty, and refusing rather than moving a checkout that holds data of its own (`--migrate` is that decision). Covered by [`test_dataroot.py`](../../tests/test_dataroot.py). A worktree made by any tool therefore works on first read; the `stuntreel` census takes its corpus path from the caller, so it fails loudly instead.

## Considered Options

- **Plumbing only** — an environment variable plus ``--data-root`` on every reader (the flag survives on the parity scripts as an override that scores another checkout, not as the mechanism).
  Rejected because four DOSBox profiles, ``streamer.py``,
  ``adversarial_formats_challenge.py`` and ``verify_schemas_corpus.py`` resolve
  ``corpus/...`` against the working directory; each would need surgery and would
  still behave differently from the primary checkout.
- **A corpus copy per worktree.** Rejected: one corpus is 1 GB, the archive is not
  reproducible offline, and ``[I7]`` keeps it out of Git and CI.
- **A shared ``CARGO_TARGET_DIR``.** Rejected: Cargo locks the build directory, so
  parallel ``mise run check`` runs serialise — the same lock that already makes the
  release binary exclusive. Downloaded caches are shared instead (ADR 0013).
- **Symlinks instead of junctions.** Rejected on Windows, where symlinks need
  elevation or Developer Mode and junctions do not.

## Consequences

``mise run init`` adopts an existing in-checkout corpus with ``--migrate``,
``mise run clean -- --yes`` removes a worktree's outputs before it is reaped, and the
debug profile drops to ``line-tables-only``: full debug info was 14.4 GB of the
17 GB ``target/``, paid again by every worktree.

The SOP 6 shared-write gate is applied once by the capture session's `run_session` for both `capture-ref` and the light probe, and the capture lock is the listener bind inside the emulator adapter, so a second session fails at the bind before a process starts.

Two costs are visible in tooling. A worktree inside the checkout is read by every
recursive tool unless it is both gitignored and ruff-excluded, which is what
``tests/test_worktree_layout.py`` fails on: 61 seconds of ``test_doc_invariants``
before it pruned. And a junction is invisible to anything that enumerates the git
index: ``corpus/stisldem`` never appears in an editor's tree or in the agent's ``@``
file picker, because its contents are untracked, though a read by absolute path is
unaffected.
