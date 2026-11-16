---
title: "The island"
order: 3
---

The ground is flat coloured patches over anchor points, compiled into a scenery tree, and distance decides how much detail is drawn. This guide follows the island from the files that describe it to what the player does with them each frame.

## Anchor points

The island's ground starts from a table of anchor points, each one a position on the island, with its height stored upside down so that the real height is the stored value negated. The [glossary](../../GLOSSARY.md#assets-and-models) defines an anchor point as a record shared by the terrain patches and by models, and that is how it is used: ground corners and model parts that must meet the terrain both name the same points. The table file is ANCHORPT.DAT, described in the [anchor point note](../../research/formats/auxiliary/anchorpt.md). Some entries are marked as "no point" with a special height, and the note records that the game's own copy of the table holds some of these too.

## Patches

A second file, MAP.BIN, lists the ground itself as patches. A patch is a flat polygon of three to eight corners, each corner an anchor point, with a single palette colour for the whole polygon. There is no texture and no shading: the [world and scene note](../../research/playone-exe/world-scene.md) records that the player draws a ground polygon as one flat palette colour. See [how the game draws a frame](drawing.md) for what a palette index is.

Patches come in two kinds of list. A coarse patch can carry a list of finer patches that replace it when the viewer is close. The coarse patch records the distance at which the swap happens. Patches without finer versions are simply drawn as they are.

## From files to a scenery tree

MAP.BIN and the anchor table are not what the game reads. They were working files of SD.EXE, a scenery compiler that the note identifies as the developers' own tool. The compiler also takes a second file, REGIONS.BIN, which divides the island into blocks by a tree of cutting planes. It slots each top-level patch into the block it belongs to and writes out one combined structure, the scenery tree.

```mermaid
flowchart LR
    A["Anchor points"] --> SD["SD.EXE compiler"]
    M["Patches (MAP.BIN)"] --> SD
    R["Blocks (REGIONS.BIN)"] --> SD
    SD --> T["Scenery tree in the game"]
```

The [glossary](../../GLOSSARY.md#assets-and-models) calls the island's static content the world: the ocean, the ground patches, and the props placed by the scenery tree. The [scenery note](../../research/formats/auxiliary/scenery.md) describes the tree as a space-dividing tree. Some of its nodes cut the island in two along a plane, so the player can tell which side of a cut the viewer is on. Some nodes shift the position where their children sit. Some are ground patches and some are leaves that stand a model, a prop, in place.

That note also records that the game does not ship the tree as a file. It sits inside the player program itself, and the file that other tools read is that copy, widened. The [map note](../../research/formats/auxiliary/map.md) adds a detail about what survives the journey. The patch file has a few patches that nothing links to, so the compiler never writes them into the tree, and the player never draws them.

## Distance and detail

The tree is how the player decides how much to draw. Two kinds of node make that decision.

- A ground patch with finer patches below it: near the viewer the player descends into the finer list, and farther away it draws the coarse polygon.
- A detail node on the props side: it holds a simple stand-in model. Beyond a threshold distance the player draws the stand-in and stops walking that branch. Closer than the threshold it skips the stand-in and carries on into the detailed subtree.

So the stand-in is drawn instead of the subtree, not on top of it. The [scenery note](../../research/formats/auxiliary/scenery.md) states this, and the [level-of-detail note](../../research/playone-exe/lod.md) traces it in the player's code. The same note records an earlier community viewer that drew both together, which is one place a reconstruction can go wrong.

The threshold is not a fixed distance. The level-of-detail note finds that it is scaled by a detail setting that the game reads from a settings file, and by the shot's zoom, so a zoomed shot keeps its fine detail further out than a wide one. The same note records that our reference captures were made without that settings file, so they run at full detail, as the note reasons. Even then the player still switches to coarser nodes as things recede.

## Props sit on the ground by their own height

One surprise from the scenery note is how a prop gets its height. The player does not look the terrain up under a prop. A prop's height is the sum of the height offsets on the path down the tree plus a lift stored in the model's own header. A model that stands on a hill therefore carries its height in the data, and nothing checks it against the ground at draw time.

## What the notes leave open

The glossary says what supplies the rest of the ground, such as the sand flats, is not established, so the patches are one known source rather than a full account. The [world and scene note](../../research/playone-exe/world-scene.md) also shows that the airfield's other ground colours come from scenery shapes placed on top, painted in walk order.

## Read next

- [The map format](../../research/formats/auxiliary/map.md) — the patch and block files, how their links work, and how SD.EXE compiles them into the tree
- [The anchor point table](../../research/formats/auxiliary/anchorpt.md) — the table of points that patches and models share, and where its copies differ
- [The scenery tree](../../research/formats/auxiliary/scenery.md) — each kind of node in the tree, the detail rule and how props get their height
- [How the ground is drawn](../../research/playone-exe/world-scene.md) — how the player walks the tree and where each ground colour comes from
- [The level-of-detail gate](../../research/playone-exe/lod.md) — the distance test, the detail setting that scales it and what that means for captures
