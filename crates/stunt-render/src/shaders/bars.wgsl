//! Fullscreen solid-black triangle used to paint the `[I6]` letterbox bars.

@vertex
fn vs_main(@builtin(vertex_index) vertex_index: u32) -> @builtin(position) vec4<f32> {
    // Oversized triangle covering the entire viewport in clip space.
    var positions = array<vec2<f32>, 3>(
        vec2<f32>(-1.0, -1.0),
        vec2<f32>(3.0, -1.0),
        vec2<f32>(-1.0, 3.0),
    );
    return vec4<f32>(positions[vertex_index], 0.0, 1.0);
}

@fragment
fn fs_main() -> @location(0) vec4<f32> {
    return vec4<f32>(0.0, 0.0, 0.0, 1.0);
}

struct BarPlaneOutput {
    @location(0) color: vec4<f32>,
    @location(1) plane: u32,
};

@fragment
fn fs_main_plane() -> BarPlaneOutput {
    var out: BarPlaneOutput;
    out.color = vec4<f32>(0.0, 0.0, 0.0, 1.0);
    out.plane = 0u;
    return out;
}
