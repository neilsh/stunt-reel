# Journal: seven-film stream recording

## 2026-11-27: Seven-film stream recording on Legion (#1201, #1211)

**Method.** `capture-video` for each film, Patch 3, reference `.ALL`, stubbed samples, on a quiet Legion (4% CPU, 17 GB free): once stream-off into the store, once `--stream --out` into scratch, then `stream-encode --delete-log`.
Films read from `corpus/stuntisl/VAULT/` (`CTRY` and `INTRO` from `stisldem`).

**Result.** `[Bounded Observation]`, one recording per film and mode.

* Every film ends `hold` and its `all_sha256` equals its `references.toml` row.
* For the six streamed films `capture.avi` and `meta.json` are byte-identical to the stream-off recording.
* Frames and held (flags 0, neither buffer equals `A000`) frames, from `stream.json`: CTRY 1,907 / 85; INTRO 5,383 / 137; LAND 1,618 / 35; BOMB 5,254 / 139; BALLOON 1,695 / 87; TRAINTNL 1,768 / 61.
* Log sizes: 235, 663, 199, 647, 209, 218 MB; encoded `stream.mkv` 8.5, 17.3, 5.7, 22.0, 7.8, 6.7 MB.
* `LOCATION` (11,616 frames) does not fit one script with the stream: it dies with `instruction limit exceeded` after about 157 s, while the stream-off recording succeeds (188 s). Step 5, segmented passes, is needed.
* The emulator log directory on Windows is `%LOCALAPPDATA%\dosbox-automation\logs`, not `~/.config`; `emulator_log_dir` now says so.
* Archives packed and uploaded for all seven; the six streamed films now include `stream.mkv` and `stream.json`. `cloud-assets verify` was not run (needs `R2_ACCOUNT_ID`, cloud only).
