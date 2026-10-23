struct CameraUniform {
    view_proj: mat4x4<f32>,
    camera_pos: vec3<f32>,
    _pad0: f32,
    sun_direction: vec3<f32>,
    ambient_intensity: f32,
    inv_view_proj: mat4x4<f32>,
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

// Sky: PLAYONE paints the sky as bands of palette indices 238 (at the horizon) down to
// 228 (high), selected by the sine of the view ray's elevation. The edges are the medians of
// the band transitions measured in CTRY.FLM captures: 2.14, 2.77, 3.59, 4.61, 5.82, 7.27,
// 9.23, 11.79, 15.75 and 20.23 degrees (research/parity-findings.md section 7).
const SKY_EDGE_SIN = array<f32, 10>(
    0.03734, 0.04833, 0.06262, 0.08037, 0.1014, 0.12655, 0.1604, 0.20433, 0.27144, 0.34579,
);

struct SkyVertexOutput {
    @builtin(position) clip_position: vec4<f32>,
    @location(0) ndc: vec2<f32>,
};

@vertex
fn vs_sky(@builtin(vertex_index) vertex_index: u32) -> SkyVertexOutput {
    var positions = array<vec2<f32>, 3>(
        vec2<f32>(-1.0, -1.0),
        vec2<f32>(3.0, -1.0),
        vec2<f32>(-1.0, 3.0),
    );
    var out: SkyVertexOutput;
    out.clip_position = vec4<f32>(positions[vertex_index], 1.0, 1.0);
    out.ndc = positions[vertex_index];
    return out;
}

fn sky_index(ndc: vec2<f32>) -> u32 {
    let far = camera.inv_view_proj * vec4<f32>(ndc, 1.0, 1.0);
    let ray = far.xyz / far.w - camera.camera_pos;
    let sin_elevation = ray.y / length(ray);
    var index = 238u;
    for (var k = 0u; k < 10u; k = k + 1u) {
        if (sin_elevation > SKY_EDGE_SIN[k]) {
            index = 237u - k;
        }
    }
    return index;
}

@fragment
fn fs_sky(in: SkyVertexOutput) -> @location(0) vec4<f32> {
    return textureLoad(palette_lut, vec2<i32>(i32(sky_index(in.ndc)), 31), 0);
}

@fragment
fn fs_sky_plane(in: SkyVertexOutput) -> PlaneOutput {
    var out: PlaneOutput;
    let index = sky_index(in.ndc);
    out.color = textureLoad(palette_lut, vec2<i32>(i32(index), 31), 0);
    out.plane = index;
    return out;
}
