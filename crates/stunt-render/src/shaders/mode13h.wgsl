struct CameraUniform {
    view_proj: mat4x4<f32>,
    camera_pos: vec3<f32>,
    _pad0: f32,
    sun_direction: vec3<f32>,
    ambient_intensity: f32,
};

struct ModelUniform {
    model_matrix: mat4x4<f32>,
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
};

@vertex
fn vs_main(in: VertexInput) -> VertexOutput {
    var out: VertexOutput;

    // Transform vertex position into clip space
    let world_pos = model.model_matrix * vec4<f32>(in.position, 1.0);
    out.clip_position = camera.view_proj * world_pos;
    out.palette_index = in.attr.x & 255u;

    // Check emissive / unshaded flag (bit 2 = 0x04)
    if ((in.attr.y & 4u) != 0u) {
        out.light_level = 31u; // Full unshaded brightness
    } else {
        // Transform normal vector to world space using upper 3x3 of model matrix
        let norm_mat = mat3x3<f32>(
            model.model_matrix[0].xyz,
            model.model_matrix[1].xyz,
            model.model_matrix[2].xyz
        );
        let world_norm = normalize(norm_mat * in.normal);

        // Discrete directional lighting ramp
        let sun_dir = normalize(camera.sun_direction);
        let ndotl = max(dot(world_norm, sun_dir), 0.0);
        let intensity = clamp(camera.ambient_intensity + (1.0 - camera.ambient_intensity) * ndotl, 0.0, 1.0);
        out.light_level = u32(clamp(intensity * 31.0 + 0.5, 0.0, 31.0));
    }

    return out;
}

@fragment
fn fs_main(in: VertexOutput) -> @location(0) vec4<f32> {
    // Mode 13h flat-shaded pixel lookup with zero bilinear bleed [I3]
    let coords = vec2<i32>(i32(in.palette_index & 255u), i32(in.light_level & 31u));
    return textureLoad(palette_lut, coords, 0);
}
