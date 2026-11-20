# Shadow plane of a static slot

`PLAYONE.EXE` probes the ground under a slot only when the slot has `SIF_MOVES` ([`sod-vm-frame.md` § 9.1](../research/playone-exe/sod-vm-frame.md#91-the-actor-shadow-draw)).
A shadow-casting slot without it keeps whatever plane and height its record holds: zero in the load image, or what an earlier moving occupant of the slot left there.
Our scene instead gives every shadow-casting actor the plane of the terrain under its own origin, whether or not its slot moves.
Matching `PLAYONE` here is deferred.

## Why this is out of scope

No archived film shows a shadowed slot without `SIF_MOVES`, and on level ground at `y = 0` both rules draw the same shadow, so no reference film can score the change.
The rule is also not fully known: which writer left the `0x0320` plane at `NEWFX.FLM` slot 8, which probe instant counts, and how the slot's previous drawn frame enters it.

If it is built, the owner's lean (2026-11-19, untested) is for the scene to replay the film's create timeline to find the slot's last moving occupant and probe the terrain there, which keeps seam 2 free of world-derived data, rather than a new `ActorTransform` field.

## Reconsider when

A film with an archive shows a shadowed slot without `SIF_MOVES` standing over raised ground, or the `0x0320` writer at `NEWFX.FLM` slot 8 is traced.

## Prior requests

- #726: "Shadow plane for a slot without SIF_MOVES: keep the record's plane, not the terrain's (#710 item 2)"
