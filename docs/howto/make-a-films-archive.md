# Make a film's archive

A film needs an `.ALL` to be captured: one beside its `.FLM`, or one that `make-all` stored under `captures/<film>/archives/`. The demo ships one for `INTRO` and `CTRY` only. For any other film, once:

```powershell
mise run make-all -- --film <path>.FLM
```

It takes about 90 s or more: `MAKEONE.EXE` plays the film in real time on dosbox-automation. It stores the result as the film's one archive, `captures/<film>/archives/`, where `<film>` is the film's parent folder and stem (`vault-ctry`; `--name` overrides), and `capture-ref` then checks it against the film's hash ([ADR 0023](../adr/0023-make-all-generates-archives-with-makeone.md), [`research/makeone-exe/driving.md`](../../research/makeone-exe/driving.md)).

`make-all` also writes the film's manifest, `manifests/all/<film>.toml`, for review and commit. Once committed, any checkout with the game files rebuilds the `.ALL` from it into `target/linked/` without the emulator. `mise run make-all -- --manifest-only --film <path>.FLM` writes one from an archive stored earlier ([ADR 0032](../adr/0032-a-films-archive-is-committed-as-a-manifest.md)).
