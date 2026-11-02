# Seeding a new worktree's `target/` (2026-11-02)

Status: **design, awaiting review; no code yet**. Source: a session of 2026-11-02 that started
from "why is `target/` so large across the root and worktrees", measured kache 2.0.0, and settled
on cloning a donor's build output. The evidence and the decision are in
[ADR 0030](../../adr/0030-new-worktrees-seed-target-by-block-clone.md) (proposed); this note owns
the design, the steps and the measurement gate.

## 1. Goal

A worktree made by `mise run init` on the Dev Drive starts with a `target/` that Cargo already
considers built, at little physical disk:

- its first `mise run check` compiles only what differs from the donor (none, when donor and
  worktree are at the same commit);
- the seeded `target/` costs well under 0.5 GB of physical disk;
- nothing changes for a worktree that cannot be seeded: it builds from scratch as today.

Not in scope: re-seeding an existing `target/`, sharing build output between running worktrees,
and the other trims ADR 0030 lists (section 7).

## 2. Why it works, and the one precondition

Cargo decides a unit is fresh from its fingerprint and its outputs' modification times. A clone
that keeps both, in a checkout whose inputs have the same paths, is fresh. Registry and git units
qualify if `CARGO_HOME` is the same path: measured, a different `CARGO_HOME` path alone rebuilds
every dependency (ADR 0030). Workspace units fingerprint their sources by path within the
checkout and by modification time, so Cargo rebuilds the ones whose sources are newer than the
donor's outputs; ADR 0017's measurement compiled none.

So every checkout must name the one shared cache by one absolute path. Today each task sets
`CARGO_HOME = "{{config_root}}/.cache/cargo"`, a per-checkout junction to the same directory.

## 3. Design

### 3.1 One `CARGO_HOME` path

- [`mise.toml`](../../../mise.toml) gains a `[vars]` entry that resolves the primary checkout from
  git, and every task that sets `CARGO_HOME` uses it, still per task (ADR 0013's reason for not
  exporting it globally, mise's rustup shim, is unchanged):

  ```toml
  [vars]
  cargo_home = "{{ exec(command='git rev-parse --path-format=absolute --git-common-dir') | dirname }}/.cache/cargo"
  ```

  The prototype confirms `exec` and `dirname` behave in this mise version and that the value is
  identical in the primary, `.claude/worktrees/*`, `<repo>.wt/*` and Orca worktrees.
- [`build_at.py`](../../../python/scripts/build_at.py) and the `build-at` task set the same
  `CARGO_HOME`; today they fall back to the user's.
- The `.cache` junction stays; uv and `TMP` still use it.

### 3.2 Seeding step in `mise run init`

A new module, `python/stunt_reel/target_seed.py`, called from `_init` in
[`worktree_init.py`](../../../python/scripts/worktree_init.py) after the links and before
`uv sync`. It prints one line: what it seeded from, or why it did not.

1. **Only into an empty target.** Skip unless `target/` is absent or holds no `debug/`, `check/`
   or `matrix/`. Never overwrite.
2. **Only where the filesystem clones.** Skip unless this checkout's volume is ReFS (Windows:
   `GetVolumeInformationW`). Elsewhere a copy costs full size. Linux and macOS (`cp --reflink`,
   `cp -c`) are left for later.
3. **Pick a donor.** Candidates are the other checkouts from `git worktree list` whose `target/`
   is on the same volume, newest `target/debug/.fingerprint` first. A donor qualifies when:
   - its `target/.rustc_info.json` names the same `rustc` as `rustc -vV` here;
   - its last build used the shared `CARGO_HOME` (the registry path in one dependency's
     `.d` file starts with it);
   - no build is running in it: each seeded profile's `.cargo-lock` can be locked exclusively,
     and the lock is held until the copy finishes;
   - its commit's `Cargo.lock` matches this checkout's; a different one still qualifies but
     ranks below any match, since only the changed units rebuild.
4. **Copy.** `robocopy <donor>\target\<dir> <new>\target\<dir> /E /COPY:DAT /DCOPY:DAT /R:0 /W:0
   /NFL /NDL /NJH /NJS` for `debug`, `check` and `matrix`, in that order, plus
   `.rustc_info.json` and `CACHEDIR.TAG`. Timestamps must survive. `release` and `build-at` are
   left out: they are rebuilt per use and are large. Robocopy exit codes 0–7 are success.
5. **Best effort.** Any failure prints `! seed: <reason>`, removes what it copied, and lets init
   continue. Seeding never fails init.

A `mise run seed` task runs the same step on its own, for a checkout made by another tool.

### 3.3 What is not changed

The gate, its lanes and target directories (ADR 0016), `reap` and `clean`. `clean` still removes a
seeded `target/` like any other.

## 4. Tests

Offline and corpus-free, in `tests/test_target_seed.py`:

- donor ranking and each disqualifier (other `rustc`, other `CARGO_HOME`, locked profile,
  different lockfile ranks lower), on synthetic `target/` trees in `tmp_path`;
- skip reasons: non-empty target, non-ReFS volume (the volume probe is injected);
- the copier is injected, so the tests never run `robocopy`; failure cleanup is asserted.

A `[vars]` check in [`test_worktree_layout.py`](../../../tests/test_worktree_layout.py) fails if
any task sets `CARGO_HOME` to anything but `{{vars.cargo_home}}`.

## 5. Measurement gate (prototype, before the ADR is accepted)

Two fresh scratch worktrees on `E:` at the same commit, A built by `mise run check`, B made by
`mise run init` and seeded from A. Record in this note:

| measure | accept if |
| --- | --- |
| B's cold `mise run check` | under 30 s, and crates compiled is 0 |
| B's physical disk after the gate (logical size less clusters with a reference count above 1, as in ADR 0030) | under 0.5 GB |
| B one commit behind A's `Cargo.lock` change | only changed units rebuild |
| A's `target/` still builds warm after B was seeded from it | 0 crates compiled |
| init time added by seeding | under 15 s |

If B's gate compiles everything, the precondition in section 2 is wrong for some unit kind; find
which before going further.

## 6. Steps

1. `[vars] cargo_home` in `mise.toml`, used by every `CARGO_HOME` task and by `build-at`; the
   layout test. Every existing worktree rebuilds its dependencies once, on its next build.
2. `target_seed.py`, its tests, the init call and `mise run seed`.
3. The measurement gate (section 5), recorded here.
4. On a pass: ADR 0030 to accepted; ADR 0013's and ADR 0017's status lines point at it;
   [`docs/harness-setup.md`](../../harness-setup.md) and
   [`docs/development.md`](../../development.md) say that init seeds.

## 7. Follow-ups, separate from this plan

- A task that cleans idle or merged worktrees' `target/` (the first finding of the session;
  `kache clean --stale` is the model).
- Move `doc` into the clippy lane's `target/check` to drop its 192 MB duplicate (needs a gate
  timing; ADR 0016).
- No debug info for dependencies (`[profile.dev.package."*"] debug = false`): −0.16 GB per
  worktree, measured.
- Reopen kache under ADR 0030's conditions. A draft upstream issue on its seeding is in the
  session record, not posted.

## 8. Open questions

- Does a worktree on a different commit than its donor still compile few enough workspace units
  to matter? Expected yes (five crates), measured in section 5.
- Should `reap` prefer keeping one donor-quality `target/` alive (the primary's, say) so a fresh
  worktree always finds a donor?
