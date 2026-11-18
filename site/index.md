---
title: "Stunt Island research notes"
---

*Stunt Island* (1992) is a game for staging and filming stunts.
Stunt Reel is a new film player, written from scratch, that plays the game's films at modern resolutions.
To build it, we study how the original player behaves and check our frames against its own.

Stunt Reel is pre-alpha: it is still being built, and parts of its rendering are known to differ from the original.

## Where to start

<div class="sr-cards">
<div class="sr-card">

**[What's in a Stunt Island film?](guides/films.md)**

A film records where every actor and the camera are, moment by moment.

</div>
<div class="sr-card">

**[How does the game draw a frame?](guides/drawing.md)**

Each model draws itself, and the picture is painted from back to front.

</div>
<div class="sr-card">

**[How is the island built?](guides/island.md)**

Part of the ground is flat coloured patches, and distance decides how much detail is drawn.

</div>
<div class="sr-card">

**[How close is the reconstruction?](guides/reconstruction.md)**

We compare our frames with the original player's and track where they differ.

</div>
<div class="sr-card">

**[How do we know what we know?](reading.md)**

Where the evidence comes from, and how each finding is tagged.

</div>
<div class="sr-card">

**[How is Stunt Reel developed?](guides/process.md)**

Stunt Reel is partly a testbed for how AI agents can do this work reliably, in small, checked steps.

</div>
</div>

- [How we know what we know](reading.md)
- [The full list of notes](../research/MAP.md)
- [The glossary](../GLOSSARY.md)
- [The repository on GitHub](https://github.com/neilsh/stunt-reel)
