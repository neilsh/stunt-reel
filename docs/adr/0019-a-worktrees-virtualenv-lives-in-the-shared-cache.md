# A worktree's virtualenv lives in the shared cache

A worktree is usually on another volume from the primary checkout, and uv can only
hardlink a package out of ``.cache`` when the environment receiving it is on that same
volume.  A per-checkout ``.venv`` therefore copies every package: 68 MiB at 3.15 s, paid
again by every fresh ``mise run init``.  The environment stays per worktree -- uv installs
*this* checkout's project into it, so a shared one would hand one worktree another's
editable path -- but it can live in the cache.  ``ensure_venv_link`` lays it out as
``<cache>/venvs/<checkout>-<digest>`` and points ``.venv`` at it with a junction, so uv
hardlinks the 17 packages in 148 ms instead of copying them.

Measured on a worktree at ``C:\<worktree pool>\stunt-reel\worktree-init-perf``
beside a primary checkout and cache at ``E:\<primary checkout>``:

| | before | after |
| --- | --- | --- |
| fresh ``mise run init`` | 4.0-4.2 s | 0.78 s |
| ``Installed 17 packages`` | 3.15 s, full copy | 148 ms, hardlinked |
| repeat ``mise run init`` | 0.61 s | 0.52 s |
| 14 worktrees' environments | 68-71 MiB each, ``1 GiB`` | hardlinked, metadata only |

The link also removes a smaller cost: ``init`` used to link ``.cache`` *after* running
``uv sync``, so a fresh worktree's first sync downloaded 69 MiB into a local cache that
``init`` then discarded, because the shared cache already held those entries.  Linking
first means that download happens once per machine, into the cache that keeps it.

## What enforces this

- **The link.** ``ensure_venv_link`` ([dataroot.py](../../python/stunt_reel/dataroot.py))
  creates the cache directory, writes the marker ``<environment>.checkout`` naming the
  checkout it serves, and replaces ``.venv`` with a junction at it.  The marker sits
  beside the environment, not in it: uv empties the environment directory when it
  replaces the interpreter (a Python pin change), and a marker inside went with it.  A
  ``.venv`` that is a real
  directory is the copy uv made before the link existed; its absolute paths cannot move,
  so it is discarded, never adopted.
- **The seed.** ``uv sync`` refuses a project environment it cannot validate and cannot
  create one through a link, and a junction cannot point at a directory that does not
  exist.  ``_uv_venv`` therefore runs ``uv venv --allow-existing <target>`` once, before
  the first sync ([worktree_init.py](../../python/scripts/worktree_init.py)).
- **The order.** ``_init`` links ``.cache`` and ``.venv``, then runs
  ``uv sync --locked --all-groups`` with ``UV_PROJECT_ENVIRONMENT`` set to the target, then
  links the data root.  The task runs plain ``python``, not ``uv run``, which would create
  an environment in the checkout before the link existed.
- **The cleanup.** ``reap`` deletes the environment after git removes the checkout, the
  pool-leftover and orphan sweeps do the same for checkouts that are gone, and
  ``mise run clean`` reports it without removing it.  The orphan sweep removes only an
  environment whose marker names a checkout that no longer exists; one with no marker
  has an unknown owner and is kept.
- **Tests.** [test_dataroot.py](../../tests/test_dataroot.py) covers the link, the
  discarded copy, the primary checkout, the per-checkout target and the orphan sweep;
  [test_worktree_reap.py](../../tests/test_worktree_reap.py) covers the reap deletion.

## Considered Options

- **``UV_PROJECT_ENVIRONMENT`` set once in ``mise.toml``.**  Rejected: every worktree's
  ``.cache`` junction resolves to the same directory, so one constant would name one
  environment for all of them.  uv installs the checkout's project into its environment,
  so each sync would repoint the editable path away from the worktree that ran last --
  the shared-environment option below, by accident.
- **One environment per ``uv.lock`` hash, shared by every worktree.**  Rejected: it needs
  the project kept out of the environment (``--no-install-project`` plus ``PYTHONPATH``),
  which breaks a bare ``uv run python -c 'import stunt_reel'`` outside mise, and two
  worktrees syncing one environment is a new race for `0.1 s over the per-worktree
  version.
- **Move the worktree pool onto the repository's volume.**  Rejected as the fix: it
  changes nothing for a pool another tool chose -- this worktree came from Orca's
  ``workspaces`` directory on ``C:`` -- and it is a host preference, not a property of the
  repository.
- **Skip the sync when the environment already matches the lock.**  Rejected as
  insufficient on its own: it saves 0.3 s of a 0.6 s repeat init and nothing of the 4 s
  fresh one.
- **``UV_LINK_MODE=copy``.**  Rejected: it silences the hardlink warning without paying
  any less for the copy.

## Consequences

``.venv`` is now a junction, so anything that deletes a checkout recursively must unlink
it first, exactly like the data-root links ([ADR 0018](0018-reaping-unlinks-the-data-root-links-first.md));
``reap`` already unlinks every reparse point before git removes the checkout.  Walkers
skip it because it is a link, and no code may treat ``.venv`` as a directory it owns.

The environment is disposable, not durable state: ``rm -rf .cache`` deletes every
worktree's environment with the cache, and the next ``mise run init`` recreates this
checkout's.  A checkout outside git, and the primary checkout itself, keep a real
``.venv`` because no junction is needed there.

The first init on a machine still downloads the packages once (`69 MiB into the shared
cache); it is the one cost this does not remove, and it no longer recurs per worktree.
The cache grows by one directory per live worktree, which ``init``, ``reap`` and
``reap --prune`` keep bounded.  [ADR 0013](0013-worktrees-share-one-writable-tool-cache.md)
still governs the cache itself.
