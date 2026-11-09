# Make a film's archive

A film needs an `.ALL` to be captured: one beside its `.FLM`, one rebuilt from the film's committed manifest under `manifests/all/` (no emulator needed), or one that `make-all` stored under `captures/<film>/archives/`. The demo ships one for `INTRO` and `CTRY` only, and it is an unpatched `MAKEONE.EXE`'s, which a film whose `references.toml` row pins `makeone = "patch3"` refuses. For a film with none of these, once:

```powershell
mise run make-all -- --film <path>.FLM
```

It takes about 90 s or more: `MAKEONE.EXE` plays the film in real time on dosbox-automation. It stores the result as the film's one archive, `captures/<film>/archives/`, where `<film>` is the film's parent folder and stem (`vault-ctry`; `--name` overrides), and `capture-ref` then checks it against the film's hash ([ADR 0023](../adr/0023-make-all-generates-archives-with-makeone.md), [`research/makeone-exe/driving.md`](../../research/makeone-exe/driving.md)).

`make-all` also writes the film's manifest, `manifests/all/<film>.toml`, for review and commit, when it can. An archive not rebuildable from the game files, or an extraction error, leaves none: `make-all` prints why, still exits 0, removes an earlier manifest of the replaced archive, and the stored archive stays the record. `--manifest-only` exits 1 when it writes none and leaves an earlier manifest alone ([`make_all.py`](../../python/scripts/make_all.py), `write_manifest`). Once committed, any checkout with the game files and the build the manifest's `game_root` names (`builds/patch3`, read from the data root; [build the game builds](build-the-game-builds.md)) rebuilds the `.ALL` from it into `target/linked/` without the emulator. `mise run make-all -- --manifest-only --film <path>.FLM` writes one from an archive stored earlier ([ADR 0032](../adr/0032-a-films-archive-is-committed-as-a-manifest.md)).
