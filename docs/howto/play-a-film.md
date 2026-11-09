# Play a film in the original player

```powershell
mise run play        # CTRY.FLM; mise run play -- --film corpus/stisldem/VAULT/INTRO.FLM
```

[`play.py`](../../python/scripts/play.py) stages the film and its archive, launches `PLAYONE.EXE` on dosbox-automation, presses the keys that select the film, and leaves the window to you until you close it. `--game-root <data>/builds/patch3` plays it on another build ([build the game builds](build-the-game-builds.md)). How the emulator is found and staged is [`development.md`, dosbox-automation](../development.md#2-dosbox-automation).
