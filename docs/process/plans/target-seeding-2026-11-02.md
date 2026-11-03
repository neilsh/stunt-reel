# Seeding a new worktree's `target/` (2026-11-02)

Status: **implemented on branch `claude/stunt-reel-target-size-b4b954`; measurement gate run 2026-11-02, two rows missed (section 5) and accepted as measured; ADR 0030 accepted 2026-11-02**. Tasks:
[`target-seeding-implementation-2026-11-02.md`](target-seeding-implementation-2026-11-02.md). Source: a session of 2026-11-02 that started
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

The converse is the hazard: a workspace unit whose sources are older than the donor's outputs is
fresh whatever the sources hold. A checkout created before its donor's last build would run the
donor's code, and test binaries embed the donor's `CARGO_MANIFEST_DIR` (a final review reproduced
both on 2026-11-02). So the seed drops the fingerprints of the checkout's own workspace members,
and those always rebuild; only dependency units are reused.

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
- The `build-at` task sets the same `CARGO_HOME`, as does every task whose script runs cargo itself
  or through `parity_pipeline` (`batch-parity` and `parity-probe` set none before); a layout test
  holds this. [`build_at.py`](../../../python/scripts/build_at.py) run without mise still uses the
  user's.
- `init` and `seed` pass the same value to the seed as `STUNT_CARGO_HOME`, so the donor check and
  cargo never derive the path twice.
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
   - its last build used the shared `CARGO_HOME` (the registry path in its newest dependency
     `.d` file starts with it);
   - no build is running in it: each seeded profile's `.cargo-lock` can be locked exclusively,
     and the lock is held until the copy finishes;
   - its commit's `Cargo.lock` matches this checkout's; a different one still qualifies but
     ranks below any match, since only the changed units rebuild.
4. **Copy.** `robocopy <donor>\target\<dir> <new>\target\<dir> /E /COPY:DAT /DCOPY:DAT /R:0 /W:0
   /NFL /NDL /NJH /NJS` for `debug`, `check` and `matrix`, in that order, plus
   `.rustc_info.json` and `CACHEDIR.TAG`. Timestamps must survive. `release` and `build-at` are
   left out: they are rebuilt per use and are large. Robocopy exit codes 0–7 are success. After
   each directory, the fingerprints of this checkout's workspace members (`<package>-<16 hex>`
   under any `.fingerprint/` one or two levels down) are deleted (section 2).
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
| B's cold `mise run check` | under 30 s, and crates compiled is 0 (revised 2026-11-02: no dependency compiled; the workspace crates always rebuild, section 2) |
| B's physical disk after the gate (logical size less clusters with a reference count above 1, as in ADR 0030) | under 0.5 GB |
| B one commit behind A's `Cargo.lock` change | only changed units rebuild |
| A's `target/` still builds warm after B was seeded from it | 0 crates compiled |
| init time added by seeding | under 15 s |

If B's gate compiles everything, the precondition in section 2 is wrong for some unit kind; find
which before going further.

### Results (2026-11-02)

A was this branch's worktree at `690674f`; B was `E:\git\stunt-reel.wt\seed-b` at the same commit,
seeded by `mise run init`. Other sessions were building on the machine.

| measure | result | verdict |
| --- | --- | --- |
| B's cold `mise run check` | 90 s, 15 units compiled: the five workspace crates in each lane, no dependency | **miss** |
| B's cold `mise run check-rust` (Rust lanes only) | 40 s (fmt 5, clippy 12, matrix 14, test 38, doc 3), against 91 s unseeded and 22 s warm | **miss** (under 30 s) |
| B's physical disk after the gate | 2,726 MB logical in files of 256 KiB and up, 2,017 MB of it shared; 0.7–0.9 GB of its own with the 167 MB of smaller files | **miss** (under 0.5 GB) |
| B one commit behind A's `Cargo.lock` change | not measured: no locked crate has a semver-compatible older version in the cache, so a drifted lock cannot be made offline | open |
| A still warm after seeding B | `mise run check-rust` 22 s, 0 compiled | pass |
| init time added by seeding | 5.5 s (`mise run seed` alone; `init` without seeding 1.0 s) | pass |

Every dependency arrived fresh, so section 2's precondition holds for registry units. The misses
have one cause: a new checkout's sources are newer than the donor's workspace outputs, so Cargo
rebuilds the five workspace crates in every lane and relinks the test executables, which is also
most of B's own disk. The full gate's wall time is set by `test-py` (about 80 s) either way.
ADR 0017's "0 crates compiled" did not reproduce. ADR 0030 stays proposed until the criteria are
revised or workspace units are made fresh too.

The final review then showed that making workspace units fresh by timestamp alone is unsafe
(section 2), and the seed now drops their fingerprints. Their rebuild is part of the design, so
the first row's "0 compiled" applies to dependencies only. The 30 s and 0.5 GB rows still miss;
ADR 0030 was accepted at 40 s and 0.7–0.9 GB on 2026-11-02, with closing the gap left to
section 7. A recheck after the fix, seeding an export of the branch from this worktree, compiled
the five workspace crates and no dependency (`cargo test --no-run`, 9 s).

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
- Done 2026-11-02: `doc` builds in the clippy lane's `target/check` (ADR 0016, amended), and
  dependencies keep no debug info (`[profile.dev.package."*"] debug = false`). A cold
  `mise run check-rust` from an empty `target/` then took 78 s and left 1.9 GB (1.3 GB `debug`,
  0.47 GB `check`, 0.20 GB `matrix`), against 2.4 GB before.
- Make workspace units reusable safely, about 18 s per new worktree: first read
  `CARGO_MANIFEST_DIR` at run time in tests instead of `env!` at compile time, so no binary embeds
  its checkout; then keep a member's fingerprint only where every source file is byte-identical
  to the donor's working copy, and give those files the donor's modification time.
- Reopen kache under ADR 0030's conditions. A draft upstream issue on its seeding is in the
  session record, not posted.

## 8. Open questions

- Does a worktree on a different commit than its donor still compile few enough workspace units
  to matter? Expected yes (five crates), measured in section 5.
- Should `reap` prefer keeping one donor-quality `target/` alive (the primary's, say) so a fresh
  worktree always finds a donor?
