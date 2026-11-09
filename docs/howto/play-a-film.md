# Play a film in the original player

```bash
mise run play -- --film <path>.FLM [--game-root <data root>/builds/<build>]
```

[`play.py`](../../python/scripts/play.py) stages the film and the `.ALL` beside it, launches `PLAYONE.EXE` on dosbox-automation (`--game-root`'s; without it, the game tree the film's folder sits in when that tree holds `PLAYONE.EXE`, as `<tree>/VAULT/X.FLM`, else the demo's: `_engine_root` in [`staging.py`](../../python/stunt_reel/tac/staging.py)), presses the keys that select the film, and leaves the window to you until you close it. `--film` defaults to the demo's `CTRY.FLM`.

* **Only the sibling archive.** `play` does not read an archive `make-all` stored or one rebuilt from a manifest ([Make a film's archive](make-a-films-archive.md)), so a film without an `.ALL` beside it cannot be played.
* **Reference films are checked.** A film with a row in [`research/parity/references.toml`](../../research/parity/references.toml) is refused unless both the `PLAYONE.EXE` and the build that made its `.ALL` are the ones the row names. The rows name `patch3`, while the demo ships an unpatched player and unpatched archives, so the demo's `CTRY.FLM` and `INTRO.FLM` are refused as shipped, `--game-root <data root>/builds/patch3` included ([build the game builds](build-the-game-builds.md)). Such a film plays with `--game-root` on `patch3` once the `.ALL` beside it hashes to the `all_sha256` its manifest pins (`archive_makeone_build` in [`references.py`](../../python/stunt_reel/references.py)). A film with no row plays on any build.

How the emulator is found and staged is [`development.md`, dosbox-automation](../development.md#2-dosbox-automation).
