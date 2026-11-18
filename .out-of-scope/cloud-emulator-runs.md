# DOSBox-X in a cloud session

A cloud session runs dosbox-automation, so `capture-ref` and `make-all` work there ([`docs/cloud-sessions.md` § Running the emulator](../docs/cloud-sessions.md#running-the-emulator)).
DOSBox-X (`debug-x`) does not: its pinned `dosbox-x-v2026.10.01` release ships no Linux binary, so Linux would need a source build with the debugger link.
`play` stays local because a person watches it.

## Why this is out of scope

No cloud task has asked for `debug-x` so far, and the primary machine runs it.

## Reconsider when

Cloud tasks stall on `debug-x` often enough that the hand-off to the primary machine is the bottleneck.

## Prior requests

- #293: "Cloud sessions cannot run the dosbox-automation tasks" (dosbox-automation landed; DOSBox-X stayed out)
