# Worktrees share one read-only data root

## Status

superseded in part by [ADR 0021](0021-capture-chooses-its-control-port.md): the data
root stays read-only as described here; captures no longer serialise machine-wide,
because each session binds its own control port.

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
other worktree silently. Capture used to stay serialised machine-wide: ``58991`` was
bound by ``ListenTransport`` with ``listen(1)`` (``SO_EXCLUSIVEADDRUSE`` on Windows,
so a second capture failed at the bind) and the four ``dosbox-*.conf`` profiles
hardcoded it. [ADR 0021](0021-capture-chooses-its-control-port.md) supersedes that half:
each capture now binds port 0, tells DOSBox-X which port it got, and runs its own
instance, so two captures share the machine without sharing a port.

## What enforces this

- **The write guard.** [`require_shared_write`](../../python/stunt_reel/dataroot.py) is called by both writers: [`capture-ref`](../../python/scripts/capture_playone_reference.py) when `--out` resolves into the root, and oracle generation per destination in [`models.py`](../../python/stunt_reel/tac/models.py). [`test_dataroot.py`](../../tests/test_dataroot.py) covers the opt-in and the resolution through a real junction.
- **The capture lock (superseded by [ADR 0021](0021-capture-chooses-its-control-port.md)).** The bind in [`transport.py`](../../python/stunt_reel/tac/transport.py) used to serialise captures through a fixed port; each session now binds port 0 and reports what it got, so a second capture no longer fails at the bind. Oracle generation was never exclusive.
- **`init` on first use.** [`ensure_links`](../../python/stunt_reel/dataroot.py) is the one link policy: it repairs a worktree that never ran `mise run init` at the point the corpus is read — `capture-ref`, `parity` and `sweep` — replacing a `.gitkeep` placeholder with the junction and creating a shared directory that is still empty. It returns one outcome per target (`ok`, `repaired`, `created-empty` or `refused`), and [`mise run init`](../../python/scripts/worktree_init.py) renders those outcomes instead of walking `LINK_TARGETS` again, with `--migrate` as a pre-step. Its refusal stays all-or-nothing and happens before anything is touched: a checkout holding data of its own is left exactly as it was, because a half-repaired checkout reads as a worktree whose corpus is half present, which is worse than the empty placeholder. Moving that data remains `mise run init -- --migrate`'s decision, so `init` without `--migrate` now refuses instead of partially linking. Covered by [`test_dataroot.py`](../../tests/test_dataroot.py). A worktree made by any tool therefore works on first read; the `stuntreel` census takes its corpus path from the caller, so it fails loudly instead.

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

The SOP 6 shared-write gate is applied once by the capture session's `run_session` for both `capture-ref` and the light probe; the listener bind inside the emulator adapter is no longer a lock, so two sessions bind two ports ([ADR 0021](0021-capture-chooses-its-control-port.md)).

Two costs are visible in tooling. A worktree inside the checkout is read by every
recursive tool unless it is both gitignored and ruff-excluded, which is what
``tests/test_worktree_layout.py`` fails on: 61 seconds of ``test_doc_invariants``
before it pruned. And a junction is invisible to anything that enumerates the git
index: ``corpus/stisldem`` never appears in an editor's tree or in the agent's ``@``
file picker, because its contents are untracked, though a read by absolute path is
unaffected.

One consequence of keeping the root outside every checkout: a sandboxed agent session cannot create the junctions from a `workspace-write` workspace, because their targets sit outside it. Provisioning therefore takes one run with wider file access. See [`docs/harness-setup.md`](../harness-setup.md).
