# Worktrees share one read-only data root

Each agent works in its own git worktree outside the checkout. The corpus, the
reference captures and ``target_bin/`` are gitignored, so they live once per
machine in ``<parent-of-primary>/<repo-name>.data`` (``STUNT_DATA_ROOT`` overrides),
and ``mise run init`` links them into every worktree: ``corpus/stisldem``,
``corpus/si_archive``, ``corpus/oracle``, ``target_bin/`` and ``build/parity/reference``.
Build outputs, Python caches and the virtualenv stay per worktree.

Two consequences are deliberate. The data root is read-only to agents: the two
writers, ``mise run capture-ref`` and oracle generation, refuse unless
``STUNT_DATA_WRITE=1``, because a stray write into the shared corpus damages every
other worktree silently. And capture stays serialised machine-wide: ``58991`` is
bound by ``ListenTransport`` with ``listen(1)``, the four ``dosbox-*.conf`` profiles
hardcode it, and one DOSBox-X instance serves the whole machine.

## Considered Options

- **Plumbing only** — an environment variable plus ``--data-root`` on every reader.
  Rejected because four DOSBox profiles, ``streamer.py``,
  ``adversarial_formats_challenge.py`` and ``verify_schemas_corpus.py`` resolve
  ``corpus/...`` against the working directory; each would need surgery and would
  still behave differently from the primary checkout.
- **A corpus copy per worktree.** Rejected: one corpus is 1 GB, the archive is not
  reproducible offline, and ``[I7]`` keeps it out of Git and CI.
- **A shared ``CARGO_TARGET_DIR``.** Rejected: Cargo locks the build directory, so
  parallel ``mise run check`` runs serialise — the same lock that already makes the
  release binary exclusive.
- **Symlinks instead of junctions.** Rejected on Windows, where symlinks need
  elevation or Developer Mode and junctions do not.

## Consequences

``mise run init`` adopts an existing in-checkout corpus with ``--migrate``,
``mise run clean -- --yes`` removes a worktree's outputs before it is reaped, and the
debug profile drops to ``line-tables-only``: full debug info was 14.4 GB of the
17 GB ``target/``, paid again by every worktree.
