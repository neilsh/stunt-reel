---
title: "Trace which object bucket PLAYONE's actor queue feeds, to order actors among world objects"
started: 2026-11-18
issue: 680
outcome: "The actor queue pushes one list (`DGROUP:0x4F00`) that the scenery walk splits by its planes; an entry joins bucket `0x2346 + 2 × box code` only at the object its probe recorded; recorded in research/playone-exe/scene-walk-actors.md."
---

# Trace which object bucket PLAYONE's actor queue feeds, to order actors among world objects

The question, the static read and its verdict are in the [journal](journal.md); the finding lives in [`scene-walk-actors.md`](../../../research/playone-exe/scene-walk-actors.md).
Drawing actors at their leaf's place in `stunt-render` is a separate item, filed as [#721](https://github.com/neilsh/stunt-reel/issues/721).
