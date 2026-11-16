---
title: "How the game draws a frame"
order: 2
---

Models are small programs that draw themselves, and the original paints each frame back to front, with colours taken from ramps in a fixed palette. This guide follows one frame from a model to the pixels on screen.

## A model is a program

A [shape](../../GLOSSARY.md#assets-and-models), the game's word for a 3D model, is not stored as a list of points and triangles. It is stored as a short program in a .SOD file. The original player runs that program each time it needs the model, and the program works out the corners, moves and turns its parts into place, and emits the coloured polygons to draw. The format note calls this a procedural display list.

Two things follow from that. A model can branch while it runs, for example on whether a face is turned towards the viewer, so one program can draw a part differently depending on the view. And a model can be built from parts that move relative to each other.

The player runs these programs through a small virtual machine of its own. One detail from the disassembly notes: the first time the machine meets an instruction, it overwrites it in the program with a direct pointer to the code that handles it, so later passes skip the lookup. The notes found no machine code being generated in the original film player. What changes is the program itself.

## Painting back to front

The player has no depth buffer, the modern trick of remembering how far away every pixel is. It uses the painter's method instead, as the render notes describe it:

1. Each frame it walks the scenery from the most distant objects to the nearest, skipping those too far away or too fine to matter.
2. It runs each object's program. The notes infer that a program can also order its own parts, drawing the far group before the near one.
3. It fills each polygon straight into the screen image. Whatever is drawn later covers what was drawn earlier, whatever their real distances.

So the order of drawing decides what you see. Where two surfaces lie in exactly the same place, such as a roundel painted on a wing, the later one wins. That is how the original draws markings: it paints them after the surface beneath.

A modern graphics card does it differently, and Stunt Reel's renderer uses the card's depth buffer on purpose. The two agree wherever the nearer surface is also painted later, which is most of the frame. They part ways on ties, where we copy the painter's rule that the later polygon wins, and on mistakes the painter made, which we do not copy. The [render model note](../../research/parity/render-model.md) lists each stage and where our picture differs.

## Colour comes from ramps

Each polygon is drawn in a palette index, a number that names one colour in a table of colours. The palette is built afresh for each frame from the film's variables, which is how a film's fades are done. See [what's in a film](films.md) for how those variables arrive.

Shading uses the palette too. Neighbouring colours in the table are arranged in runs that step from dark to light, and the major materials, such as fuselage grey, sand, olive, grass and water, each have such a ramp. For shapes that use the light-driven shading, the player works out how squarely a surface faces the light and picks the matching step along its material's ramp. The colour is picked from the palette table, not blended.

Not every surface is lit this way. In the captures we checked, the airfield ground in one film takes no sun-derived level, and the sky appears as bands of palette colours that tilt with the camera. The palette note records these as observations, not settled rules.

## Read next

- [The model format](../../research/formats/sod.md) — the model file header, how sizes are scaled and how decals are told from base faces
- [The model machine](../../research/playone-exe/sod-vm.md) — how the original runs a model program, from dispatch to the anchor points that attach terrain
- [Palette and shading](../../research/formats/concepts/palette-and-shading.md) — the colour groups, the shading ramps and how a modern renderer imitates them
- [The render model](../../research/parity/render-model.md) — the original's painter set against our depth buffer, stage by stage
