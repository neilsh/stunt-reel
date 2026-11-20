---
title: "Sky above 23.4 degrees: zenith bands 224-227 and the sun disc are not drawn"
started: 2026-11-20
issue: 617
outcome: "The sky drawer 0x8C45, the sun disc 0x908E and the var-13 light 0x196C are read live on BALLOON and drawn: every reference film rises on the GPU (mean SSIM 0.8728 -> 0.8998, balloon 0.8842 -> 0.9057), IoU unchanged; scoring the disc and 0xD0 fill as sky is #844."
---

# Sky above 23.4 degrees: zenith bands 224-227 and the sun disc are not drawn

The question: what `PLAYONE` draws above the 23.4-degree band (224 to 227) and where it draws the sun disc (239), so the renderer can draw both.

## What changed

- The sky drawer's law, the disc's projection and colour, and the var-13 light are recorded in [`palette-and-shading.md`](../../../research/formats/concepts/palette-and-shading.md#sky-bands) (Sky Bands), [`palette-fade.md` § 3.2](../../../research/playone-exe/palette-fade.md#32-other-readers-of-the-live-variables) and [`terrain-shade.md`](../../../research/playone-exe/terrain-shade.md) § 4.2, with the routines in the memory maps.
- `crates/stunt-render/src/sky.rs` lays out the bands and the disc per frame; `mode13h.wgsl` draws them; `ShadeLight::world` computes the light from any variable 13.
- The DOSBox-X plans `tools/dosbox-x/plans/sun-disc.toml` and `sky-bands.toml` reproduce the live reads.
- [`journal.md`](journal.md): the live reads, then the GPU sweep that adopted them.

## Handoff

- [#844](https://github.com/neilsh/stunt-reel/issues/844): the scorer counts the captured disc and `0xD0` fill as geometry, so `balloon`'s IoU did not move with the disc.
- `land:419` fell 0.0447 because our film shows another shot than the capture there; the sky change only exposed it.
