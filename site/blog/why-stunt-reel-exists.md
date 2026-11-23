---
title: "Why Stunt Reel exists"
date: 2026-11-23
authors: neil
tags: [introduction, architecture, agents]
excerpt: "A 1992 stunt-filming game, a modern player for its films, and an experiment in how far AI agents can be trusted with careful reverse engineering."
---

<!-- DRAFT for Neil's review. Lines marked TODO(Neil) need your own words; everything else is drawn from the repository as of 2026-11-23. -->

*Stunt Island* came out in 1992, from Disney and The Assembly Line.
You built sets on an island, placed props and actors, flew stunts, and then cut the footage together into a film.
A small player program, `PLAYONE.EXE`, plays a finished film without the full game.

> TODO(Neil): a paragraph on your own history with the game: when you played it, what you made, and why its films stuck with you.

Stunt Reel is a new player for those films, written from scratch.
It reads the game's own files and draws the films with a modern GPU, at any resolution, with a free camera you can fly around the set.
It is pre-alpha: it plays the demo films, and parts of the picture still differ from the original.

## The problem

The films are thirty-odd years old, and today they play only inside a DOS emulator, at 320 by 200 pixels.
Beyond community notes, little was written down about how they are stored.
A film is not video: it is a recorded choreography, where every actor and the camera are at each moment, and the player redraws the whole scene every frame from the game's 3D models.
So keeping the films watchable means understanding the formats and the renderer well enough to do the drawing ourselves.

That breaks down into three questions:

1. **What is in the files?**
   The film itself (`.FLM`), its archive of models and scenery (`.ALL`), the models' display lists (`.SOD`) and the game's resource files (`.RES`).
   The [format catalog](../../research/formats/INDEX.md) describes each one, with machine-readable [Kaitai Struct](https://kaitai.io/) layouts beside the prose.
2. **How does the original player draw a frame?**
   Each model is a small program for a display-list virtual machine, and the picture is painted from back to front.
   The [`PLAYONE.EXE` notes](../../research/playone-exe/) come from disassembling the player.
3. **How close is our picture?**
   We run the original player in an emulator, capture its frames, render the same ticks ourselves, and score the pairs.
   The [reconstruction guide](../guides/reconstruction.md) explains the scoring and where the differences are.

No game files ship with the project.
Every test runs offline against small synthetic fixtures, and to watch a film you bring your own copy of the game's promotional demo.

## How it is built

The engine is Rust.
`stunt-core` parses the formats, runs the display-list VM and evaluates a film's timeline on its 50 Hz clock; it does no I/O and touches no GPU, so its tests run offline in seconds.
`stunt-render` draws with [`wgpu`](https://wgpu.rs/), keeping the game's flat-shaded, 256-colour look.
`stunt-cli` is the `stuntreel` program: interactive playback, headless rendering to images or video, and glTF export.
`stunt-score` compares rendered frames with captured ones.

The tooling around it is Python: the capture harness that drives the original player inside dosbox-automation, the parity loop that scores and reports, and the checks that keep the documentation honest.

Two rules shape most of the design.
The first is that the code meets at four **seams**, typed contracts for the archive, the trajectory, the shape and the parity comparison, defined once in [`contracts/`](../../crates/stunt-core/src/contracts/mod.rs).
The second is that every claim about the original carries an **evidence tier**, from `[Hypothesis]` up to `[Established]`, the last meaning it is proven from the disassembled code or a memory trap.
The checks fail the build if a document uses a tag that is not on the list.
[How we know what we know](../reading.md) explains the tiers.

The [specification](../../docs/SPEC.md) sets out the goals and invariants, the [architecture page](../../docs/ARCHITECTURE.md) maps each module to the notes that govern it, and more than fifty [decision records](../../docs/adr/) say why things are the way they are.

## Built with agents

Stunt Reel is also an experiment.
Most of the code and notes are written by AI coding agents, working from GitHub issues, under rules the repository spells out in [`AGENTS.md`](../../AGENTS.md).
The project has been worked with three agent harnesses so far: Claude Code, Antigravity and DeepSeek Harness.

> TODO(Neil): why you chose to build it this way, and what you hoped to learn.

Reverse engineering is a hard test for agents, because a confident wrong answer looks the same as a right one until something downstream breaks.
So most of the process is about evidence and review:

- Every finding lands in a research note, ruled-out hypotheses included, in the same commit as the code that relies on it.
- One command, `mise run check`, runs formatting, lint, module layers, type checks and the tests for Rust and Python, and it must pass before work is presented.
- Before a change to the research notes or the guides is pushed, a reviewer with no memory of the work, usually a fresh agent, reads the diff and the notes it cites and flags any claim broader than its evidence.
- Work that needs a plan gets a dated journal in a work folder, so current facts and the history of how we found them stay apart.

The repository's first commit was on 18 October 2026.
Since then more than 560 pull requests have merged.
[How Stunt Reel is developed](../guides/process.md) walks through one piece of work from issue to merge.

## What this blog is for

The guides and research notes say what is currently true.
This blog is for the story around them: how the architecture came to be, how the agent workflow works day to day, where it went wrong, and what changed because of it.

> TODO(Neil): a closing line in your own voice, and anything you want readers to do (follow along, try the demo, open an issue).
