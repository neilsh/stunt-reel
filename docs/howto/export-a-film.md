# Export a film to video or glTF

## Video

```powershell
# Export film sequence to an MP4 video sampled at 30 fps
cargo run -p stunt-cli -- --headless "<data root>/corpus/stisldem/VAULT/CTRY.FLM" \
    --all "<data root>/corpus/stisldem/VAULT/CTRY.ALL" --video build/ctry.mp4
```

Headless video export samples the authored 50 Hz timeline at `--fps` (default 30), interpolates between slices, and encodes directly into a standard video container (`.mp4`, `.webm`, `.mkv`, or `.avi`) via `ffmpeg`, with physical 4:3 aspect ratio correction (320 × 240, `[I6]`). `--tick-range <A..=B>` limits the export to a 0-based, inclusive range of ticks. `CTRY.FLM` spans 1,342 ticks (26.84 s), producing 806 sampled frames at 30 fps; the container is trimmed to the authored span, so ffmpeg encodes 805 frames and ffprobe reports 26.833 s (nearest whole frame; 26.84 s exactly at `--fps 50`). Requires `ffmpeg` on `PATH`.

## glTF

Export a shape, or one frame of a film, to glTF 2.0 (`.glb`) for viewing in Blender or any glTF viewer:

```powershell
cargo run -p stunt-cli -- export-gltf --archive "<data root>/corpus/stisldem/VAULT/CTRY.ALL" \
    --film "<data root>/corpus/stisldem/VAULT/CTRY.FLM" --tick 400 --out build/gltf_output/CTRY_t400.glb
cargo run -p stunt-cli -- export-gltf --archive "<data root>/corpus/stisldem/VAULT/CTRY.ALL" --shape 0x0408 --out build/gltf_output/shape.glb
```
