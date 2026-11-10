# Running the emulator in a cloud session

A cloud session does not run dosbox-automation, so it cannot run `capture-ref`, `capture-video`,
`probe-light` or `make-all`. A cloud task that needs fresh emulator output writes down what it
needs (film, ticks, archive); the owner runs the task on the primary machine and repacks
`captures` ([`docs/cloud-sessions.md`](../docs/cloud-sessions.md)).

## Why this is out of scope

A cloud task rarely needs fresh emulator output: the pinned archives and reference captures a
session fetches cover parity work. Against that small gain, the work is four separate pieces, two
of them with unknown answers:

- **Pin.** `mise.toml` pins dosbox-automation with a Windows `asset_pattern`. Linux needs a
  per-platform pattern for the release's `linux-x86_64` tarball, and a re-lock.
- **Display and audio.** The emulator opens an SDL window and a cloud container has no display.
  It would run under `xvfb-run -a` with `SDL_AUDIODRIVER=dummy`; whether
  `SDL_VIDEODRIVER=offscreen` works without Xvfb is untested.
- **Setup.** The cloud setup script and `cloud-session-start` install only the gate's tools.
- **Music files.** The `corpus-stuntisl` archive leaves out `RES/MUSIC1.*` and `RES/MUSIC2.*`.
  Whether PLAYONE and MAKEONE boot without them is unknown; if they do not, the archive needs a
  new version that the owner packs and uploads.

DOSBox-X (`debug-x`) is further off still: its pinned release ships no Linux binary. `play` stays
local because a person watches it.

## Reconsider when

Cloud tasks start to stall on emulator output often enough that the hand-off to the primary
machine is the bottleneck. #293 holds the settled scope, the proposed approach and the first
steps; start from it.

## Prior requests

- #293: "Cloud sessions cannot run the dosbox-automation tasks"
