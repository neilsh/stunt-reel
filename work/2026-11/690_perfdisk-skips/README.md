---
title: "Renderer: apply OP_PERFDISK's shadow-mode, centre-depth and eye-plane skips"
started: 2026-11-20
issue: 690
outcome: "adopted: OP_PERFDISK shadow-mode skip (0xA045); centre-depth (0xA09A) and eye-plane (0xA156) filled-disc skips moved zero frames on the seven reference films (verified by positive controls) and remain unimplemented; gpu tables repinned, lavapipe repin left for a cloud run"
---

# Renderer: apply OP_PERFDISK's shadow-mode, centre-depth and eye-plane skips

The question: whether each of `OP_PERFDISK`'s three unimplemented skips (`0xA045` shadow mode, `0xA09A` centre depth below `0x80` signed, and `0xA156` eye plane) improves parity on the seven reference films.
See [the journal](journal.md).
