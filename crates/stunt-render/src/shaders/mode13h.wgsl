struct CameraUniform {
    view_proj: mat4x4<f32>,
    camera_pos: vec3<f32>,
    _pad0: f32,
    sun_direction: vec3<f32>,
    ambient_intensity: f32,
};

struct ModelUniform {
    model_matrix: mat4x4<f32>,
    layer: vec4<u32>, // x: layer id written to the plane target
};

@group(0) @binding(0) var<uniform> camera: CameraUniform;
@group(1) @binding(0) var palette_lut: texture_2d<f32>;
@group(2) @binding(0) var<uniform> model: ModelUniform;

struct VertexInput {
    @location(0) position: vec3<f32>,
    @location(1) normal: vec3<f32>,
    @location(2) attr: vec4<u32>, // x: palette_index, y: flags, z/w: padding
};

struct VertexOutput {
    @builtin(position) clip_position: vec4<f32>,
    @location(0) @interpolate(flat) palette_index: u32,
    @location(1) @interpolate(flat) light_level: u32,
    @location(2) @interpolate(flat) layer: u32,
};

struct PlaneOutput {
    @location(0) color: vec4<f32>,
    // Layer id in bits 8.., unlit palette index in bits 0..8.
    @location(1) plane: u32,
};

@vertex
fn vs_main(in: VertexInput) -> VertexOutput {
    var out: VertexOutput;

    // Transform vertex position into clip space
    let world_pos = model.model_matrix * vec4<f32>(in.position, 1.0);
    out.clip_position = camera.view_proj * world_pos;
    out.palette_index = in.attr.x & 255u;
    out.layer = model.layer.x + in.attr.z;

    // Polygons are drawn at their palette index with no directional lighting: against
    // PLAYONE captures of CTRY.FLM the unlit colour scores higher than any sun/ambient ramp
    // (research/parity-findings.md section 6), and the original picks shades with explicit
    // palette offsets (OP_SHADES, OP_SHADE16), not a sun vector. Row 31 is full brightness.
    out.light_level = 31u;

    return out;
}

@fragment
fn fs_main(in: VertexOutput) -> @location(0) vec4<f32> {
    // Mode 13h flat-shaded pixel lookup with zero bilinear bleed [I3]
    let coords = vec2<i32>(i32(in.palette_index & 255u), i32(in.light_level & 31u));
    return textureLoad(palette_lut, coords, 0);
}

@fragment
fn fs_main_plane(in: VertexOutput) -> PlaneOutput {
    var out: PlaneOutput;
    let coords = vec2<i32>(i32(in.palette_index & 255u), i32(in.light_level & 31u));
    out.color = textureLoad(palette_lut, coords, 0);
    out.plane = (in.layer << 8u) | (in.palette_index & 255u);
    return out;
}
