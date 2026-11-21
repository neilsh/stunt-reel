# Outline cull by width

The Mode 13h shader's `is_back_facing` culls a per-frame shape's outline with its back-facing triangle when the triangle covers more than 1 px² of screen.
`PLAYONE` has no facing test: its fillers skip only the rows whose right end lies left of the left ([`sod-vm-lines-spans.md` § 8.12](../research/playone-exe/sod-vm-lines-spans.md#812-back-faces-the-span-test)), so a long back-facing sliver under a pixel wide may still draw there.
Culling by the triangle's width over its longest edge instead of its area, to match that, is deferred.

## Why this is out of scope

The 13 frames searched, in `intro`, `balloon` and `bomb`, do not tell the two tests apart: where they draw differently, the capture matches each on some pixels and neither on others, and one edge sides with each eleven ticks apart ([`attribution.md` § 6](../research/parity/attribution.md#6-back-faces)). The other four films' frames and the apexes were not searched pixel by pixel.
No film's mean SSIM moves by more than 0.000013, and what `PLAYONE` draws for a back face's thin parts is `[Hypothesis]`, read from the instructions and not traced.

## Reconsider when

A trace or a capture made for it shows how many pixels `PLAYONE` draws along a back face's thin parts or at its lone apexes, or a reference film shows a back-facing sliver both tests miss.

## Prior requests

- #858: "Outline cull: spare back-face slivers by width, as PLAYONE's row test does, not by area"
