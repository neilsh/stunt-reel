# Export a film to video or glTF

## Video

```bash
# Export film sequence to an MP4 video sampled at 30 fps
cargo run -p stunt-cli -- --headless "<data root>/corpus/stisldem/VAULT/CTRY.FLM" \
    --all "<data root>/corpus/stisldem/VAULT/CTRY.ALL" --video build/ctry.mp4 \
    --sidata "<data root>/corpus/siarchive/Developer/FreeFlight/SIDATA"
```

Headless video export samples the authored 50 Hz timeline at `--fps` (default 30), interpolates between slices, and encodes directly into a standard video container (`.mp4`, `.webm`, `.mkv`, or `.avi`) via `ffmpeg`, with physical 4:3 aspect ratio correction (320 × 240, `[I6]`).
`--tick-range <A..=B>` limits the export to a 0-based, inclusive range of ticks.
`CTRY.FLM` spans 1,342 ticks (26.84 s), producing 806 sampled frames at 30 fps; the container is trimmed to the authored span, so ffmpeg encodes 805 frames and ffprobe reports 26.833 s (nearest whole frame; 26.84 s exactly at `--fps 50`).
Requires `ffmpeg` on `PATH`.

## glTF

Export a shape, one frame of a film, or a whole film as an animation to glTF 2.0 (`.glb`) for viewing in Blender or any glTF viewer. To validate and render one without a GPU, see [`check-a-glb-without-a-gpu.md`](check-a-glb-without-a-gpu.md).
The exporter does not create the output directory, and a film frame needs `--sidata` for the demo's scenery, as above:

```bash
mkdir -p build/gltf_output
cargo run -p stunt-cli -- export-gltf --archive "<data root>/corpus/stisldem/VAULT/CTRY.ALL" \
    --film "<data root>/corpus/stisldem/VAULT/CTRY.FLM" --tick 400 --sidata "<data root>/corpus/siarchive/Developer/FreeFlight/SIDATA" \
    --out build/gltf_output/CTRY_t400.glb
cargo run -p stunt-cli -- export-gltf --archive "<data root>/corpus/stisldem/VAULT/CTRY.ALL" --shape 0x0408 --out build/gltf_output/shape.glb
```

On 2026-11-26 the `--shape 0x0408` command above stopped at opcode `0x022E` (`missing anchor table`) and wrote no vertices; the film-frame command is the one checked.

### A whole film as one animation

`--animate` replaces `--tick` and writes the whole film, or the 0-based inclusive `--tick-range A..=B`, as one `.glb` with one animation:

```bash
cargo run -p stunt-cli -- export-gltf --archive "<data root>/corpus/stisldem/VAULT/CTRY.ALL" \
    --film "<data root>/corpus/stisldem/VAULT/CTRY.FLM" --animate --sidata "<data root>/corpus/siarchive/Developer/FreeFlight/SIDATA" \
    --out build/gltf_output/CTRY.glb
```

The film is sampled at every 50 Hz tick and glTF time is seconds from the span's first tick, so set the scene to 50 fps before importing into Blender to land one frame on each tick; Blender's importer left the scene's end frame at its default 250 (`bpy` 5.0.1, 2026-11-26), so set it to the span's length in ticks.
The camera and every actor and view-facing prop are animated nodes; an actor is scaled to 0 while the film does not draw it, and a slot that changes shape gets one node per shape.
Keys that interpolation reproduces within 1 mm and 0.01° are dropped, and at a camera cut the pre-cut pose is keyed again 1 ms before it, so at one frame per tick nothing glides through the cut.
The exporter prints how many keys it kept.

Core glTF cannot animate a camera's field of view, so the file keeps the first tick's lens; when the lens zooms, the camera node's `extras.yfov_keys` lists `[time, yfov]` pairs, and `--lens-pointer` also writes them as a `KHR_animation_pointer` channel, which Blender 5.0 reads as an animated field of view (checked with the `bpy` 5.0.1 module, 2026-11-26) and a reader without the extension may reject: the `gltf` Rust crate 1.4.1 fails to parse a channel with no target node.
Each actor keeps its shape's rest pose and the world light, as in a single frame; shadows, sprites, palette fades, credits and sound are not exported.
