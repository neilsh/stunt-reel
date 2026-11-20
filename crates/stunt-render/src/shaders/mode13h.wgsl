// The view's rotation and projection only: every model matrix arrives eye-relative, with the
// eye's translation applied on the CPU in f64 (camera.rs `eye_relative_matrix`), so the only
// world-scale arithmetic left here is a world vertex's `position - eye`, rounded once
// (research/parity/lavapipe.md section 5).
struct CameraUniform {
    rotation_proj: mat4x4<f32>,
    sun_direction: vec3<f32>,
    ambient_intensity: f32,
    inv_rotation_proj: mat4x4<f32>,
    // Half a Mode 13h pixel of the view in NDC.
    line_half_ndc: vec2<f32>,
    // The lens zoom over PLAYONE's default lens, the factor a disc is squeezed by along the
    // view's depth (`squeeze_disc`).
    disc_depth_scale: f32,
    _pad1: f32,
    // PLAYONE's sky for this view (sky.rs `SkyLayout`): band i + 1 lies where
    // `dot(sky_normal, pixel) >= sky_thresholds[i]`.
    sky_normal: vec2<f32>,
    sky_edge_count: u32,
    // Bit 0: the sun disc is drawn; bit 1: the last band fill covers it.
    sky_flags: u32,
    sky_thresholds: array<vec4<f32>, 4>,
    sky_colours: array<vec4<u32>, 4>,
    // The sun disc's centre pixel and radius.
    sun_disc: vec4<i32>,
};

// SodVertex::flags bits of a line corner (contracts/shape/mod.rs VERTEX_FLAG_LINE*).
const FLAG_LINE: u32 = 0x08u;
const FLAG_LINE_SIDE: u32 = 0x10u;
const FLAG_LINE_END: u32 = 0x20u;
// SodVertex::flags bit 1, a two-sided polygon.
const FLAG_TWO_SIDED: u32 = 0x02u;

// Whether the triangle `p`, `q`, `r` (clip space) winds back-facing on screen, as the
// rasteriser culls it (pipeline.rs: `FrontFace::Cw`, `cull_mode: Some(Face::Back)`), and
// covers at least one Mode 13h pixel. The determinant of their homogeneous screen coordinates
// is positive when it winds back; over `|p.w q.w r.w|` it is twice its area in NDC, and a
// pixel is `4 * line_half_ndc.x * line_half_ndc.y` of NDC. A thinner triangle (an edge-on
// polygon) winds by rounding noise, which differs between the corners of one outline quad
// and between its edges, so its outline is kept whole.
fn is_back_facing(p: vec4<f32>, q: vec4<f32>, r: vec4<f32>) -> bool {
    let det = determinant(mat3x3<f32>(p.xyw, q.xyw, r.xyw));
    let pixel = 8.0 * camera.line_half_ndc.x * camera.line_half_ndc.y;
    return det > pixel * abs(p.w * q.w * r.w);
}

// SodVertex::flags bit of an OP_PERFDISK rim vertex (contracts/shape/mod.rs VERTEX_FLAG_DISC).
const FLAG_DISC: u32 = 0x40u;

// Moves a disc's rim vertex at `clip`, whose disc centre is at `centre`, to where PLAYONE's
// outline puts it: its offset from the centre scaled along the view's depth by
// `camera.disc_depth_scale`, the lens zoom. PLAYONE builds the outline from the centre's depth
// in the zoomed matrix's depth units (true depth over the zoom) and the normal rescaled to the
// screen rows' units (0xA08E..0xA106), so the disc it outlines is the true one with every depth
// offset from the centre times the zoom (research/playone-exe/sod-vm-generators.md section 8.8).
// The projection is symmetric, so clip x and y hold no depth term: the depth offset lives in
// clip z and w alone.
fn squeeze_disc(clip: vec4<f32>, centre: vec4<f32>) -> vec4<f32> {
    let offset = clip - centre;
    return centre + vec4<f32>(offset.xy, offset.zw * camera.disc_depth_scale);
}

// Moves a line corner at `clip`, whose segment's other end is at `other`, to the corner of a
// screen quad one pixel wide: half a pixel across the segment's minor screen axis (to the
// side the flags name) and half a pixel past its endpoint along the major one. A steep
// segment then covers one pixel per row and a shallow one one pixel per column, end pixels
// included, as PLAYONE's inclusive spans draw a two-vertex polygon
// (research/playone-exe/sod-vm-generators.md section 8.9). Depth stays the endpoint's.
fn widen_line(clip: vec4<f32>, other: vec4<f32>, flags: u32) -> vec4<f32> {
    // The screen direction toward `other`, times clip.w squared (positive), so it holds while
    // `other` is behind the eye; in half-pixel units on each axis.
    let toward = (other.xy * clip.w - clip.xy * other.w) / camera.line_half_ndc;
    // From the first endpoint to the second; a segment seen end-on falls back to +x.
    var along = toward;
    if ((flags & FLAG_LINE_END) != 0u) {
        along = -toward;
    }
    let end = select(-1.0, 1.0, (flags & FLAG_LINE_END) != 0u);
    let side = select(-1.0, 1.0, (flags & FLAG_LINE_SIDE) != 0u);
    var offset: vec2<f32>;
    if (abs(along.x) >= abs(along.y)) {
        offset = vec2<f32>(end * select(1.0, -1.0, along.x < 0.0), side);
    } else {
        offset = vec2<f32>(side, end * select(1.0, -1.0, along.y < 0.0));
    }
    return vec4<f32>(clip.xy + offset * camera.line_half_ndc * clip.w, clip.zw);
}

struct ModelUniform {
    model_matrix: mat4x4<f32>,
    layer: vec4<u32>, // x: layer id written to the plane target, y: nonzero for a shadow, z: shape word (shape id + 1, 0 for none)
};

@group(0) @binding(0) var<uniform> camera: CameraUniform;
@group(1) @binding(0) var palette_lut: texture_2d<f32>;
@group(2) @binding(0) var<uniform> model: ModelUniform;

// A run of the world mesh's prop vertices, `first..end` in its vertex buffer, and the shape
// word of the shape they draw (stunt_core::world::PropRun, `shape id + 1`).
struct PropRun {
    first: u32,
    end: u32,
    shape: u32,
};

// The world's prop runs in vertex order. Only the plane pipelines bind it (`fs_main_plane`).
@group(3) @binding(0) var<storage, read> prop_runs: array<PropRun>;

// Scenery class of a world prop vertex (contracts/shape/mod.rs SCENERY_PROP).
const SCENERY_PROP: u32 = 3u;
// `VertexOutput::prop_vertex` of a vertex that is not a world prop's.
const NO_PROP_VERTEX: u32 = 0xffffffffu;

struct VertexInput {
    @location(0) position: vec3<f32>,
    @location(1) normal: vec3<f32>,
    @location(2) attr: vec4<u32>, // x: palette_index, y: flags, z: scenery_class, w: padding
    // The second vertex stream: for an outline corner, the third vertex of the triangle its
    // edge bounds (outline.rs `Outlined`); for any other vertex, its own position.
    @location(3) apex: vec3<f32>,
};

struct VertexOutput {
    @builtin(position) clip_position: vec4<f32>,
    @location(0) @interpolate(flat) palette_index: u32,
    @location(1) @interpolate(flat) light_level: u32,
    @location(2) @interpolate(flat) layer: u32,
    // The palette index again, interpolated linearly in screen space as PLAYONE's polygon
    // filler interpolates a Gouraud polygon's index (research/playone-exe/terrain-shade.md
    // section 6). A flat polygon has one index at every vertex, so it is unchanged.
    @location(3) @interpolate(linear) shade: f32,
    // `shade * w` and `w` at the vertex, both interpolated perspective-correct: their ratio is
    // the screen-space linear interpolation of `shade` (`fragment_index`).
    @location(4) @interpolate(perspective) shade_w: f32,
    @location(5) @interpolate(perspective) w: f32,
    // The draw's shape word (`ModelUniform` `layer.z`).
    @location(6) @interpolate(flat) shape: u32,
    // A world prop vertex's number in its vertex buffer, `NO_PROP_VERTEX` for any other
    // vertex: `prop_runs` gives its shape. Every vertex of a triangle or line lies in the
    // same run, so whichever vertex provokes names it.
    @location(7) @interpolate(flat) prop_vertex: u32,
};

// Whether `x` is NaN or infinite: all exponent bits set. WGSL has no isNan, and `x != x`
// may be folded.
fn is_non_finite(x: f32) -> bool {
    return (bitcast<u32>(x) & 0x7f800000u) == 0x7f800000u;
}

// The whole palette index a fragment draws [I3]. Mesa's software clipper (lavapipe) can
// interpolate a `linear` varying to NaN on a polygon that reaches behind the eye past a side
// plane, while it interpolates a `perspective` one with a finite weight
// (research/parity/lavapipe.md section 2). There a Gouraud polygon reads the ratio of the
// perspective copies of `shade * w` and `w`, which is `shade` interpolated linearly in screen
// space, the way PLAYONE's filler interpolates it (research/playone-exe/terrain-shade.md
// section 6); the provoking vertex's index is the last resort when that ratio is not finite
// either. A GPU interpolates finite values to finite ones, so neither branch should fire
// there: the RTX 4070's renders of the reference films are byte-identical with and without
// them.
fn fragment_index(in: VertexOutput) -> u32 {
    var shade = in.shade;
    if (is_non_finite(shade)) {
        let screen_linear = in.shade_w / in.w;
        if (is_non_finite(screen_linear)) {
            return in.palette_index;
        }
        shade = screen_linear;
    }
    return u32(clamp(floor(shade + 0.5), 0.0, 255.0));
}

struct PlaneOutput {
    @location(0) color: vec4<f32>,
    // x: layer id in bits 8.., unlit palette index in bits 0..8; y: the shape word, `shape id
    // + 1` of the prop that drew the pixel, 0 for none.
    @location(1) plane: vec2<u32>,
};

// The shape word of the prop run holding world vertex `vertex`, 0 when none does.
fn prop_shape(vertex: u32) -> u32 {
    var lo = 0u;
    var hi = arrayLength(&prop_runs);
    while (lo < hi) {
        let mid = (lo + hi) / 2u;
        let run = prop_runs[mid];
        if (vertex < run.first) {
            hi = mid;
        } else if (vertex >= run.end) {
            lo = mid + 1u;
        } else {
            return run.shape;
        }
    }
    return 0u;
}

@vertex
fn vs_main(in: VertexInput, @builtin(vertex_index) vertex_index: u32) -> VertexOutput {
    var out: VertexOutput;

    // Model space to eye-relative space to clip space.
    let eye_pos = model.model_matrix * vec4<f32>(in.position, 1.0);
    out.clip_position = camera.rotation_proj * eye_pos;
    if ((in.attr.y & FLAG_LINE) != 0u) {
        let other = camera.rotation_proj * (model.model_matrix * vec4<f32>(in.position + in.normal, 1.0));
        // An outline corner culls with the triangle its edge bounds, which winds from the
        // edge's first endpoint to its second and on to the apex; a two-sided polygon's and a
        // shadow's stay.
        let apex = camera.rotation_proj * (model.model_matrix * vec4<f32>(in.apex, 1.0));
        let at_end = (in.attr.y & FLAG_LINE_END) != 0u;
        let first = select(out.clip_position, other, at_end);
        let second = select(other, out.clip_position, at_end);
        // A corner whose apex is its own position (a ZLINETO's) bounds no triangle; it is
        // tested by position, since a determinant with two equal rows can round off zero.
        let bounds_triangle = any(in.apex != in.position);
        let two_sided = (in.attr.y & FLAG_TWO_SIDED) != 0u;
        // A shadow draws through a pipeline that culls no face, so its outline culls nothing.
        let shadow = model.layer.y != 0u;
        if (bounds_triangle && !two_sided && !shadow && is_back_facing(first, second, apex)) {
            // Every corner of the quad collapses to one point, so it covers no pixel.
            out.clip_position = vec4<f32>(0.0, 0.0, 0.0, 1.0);
        } else {
            out.clip_position = widen_line(out.clip_position, other, in.attr.y);
        }
    } else if ((in.attr.y & FLAG_DISC) != 0u) {
        let centre = camera.rotation_proj * (model.model_matrix * vec4<f32>(in.position + in.normal, 1.0));
        out.clip_position = squeeze_disc(out.clip_position, centre);
    }
    out.palette_index = in.attr.x & 255u;
    // A shadow draw fills every polygon flat in palette index 0, Gouraud ones included
    // (research/playone-exe/sod-vm-frame.md section 9.1).
    if (model.layer.y != 0u) {
        out.palette_index = 0u;
    }
    out.shade = f32(out.palette_index);
    // `shade * w` and `w` at the vertex. `widen_line` keeps `clip.w`, so `w` is the vertex's
    // own; a line is flat, and its ratio is its `shade`.
    let w = out.clip_position.w;
    out.shade_w = out.shade * w;
    out.w = w;
    out.layer = model.layer.x + in.attr.z;
    out.shape = model.layer.z;
    out.prop_vertex = select(NO_PROP_VERTEX, vertex_index, in.attr.z == SCENERY_PROP);

    // Polygons are drawn at their palette index with no directional lighting: against
    // PLAYONE captures of CTRY.FLM the unlit colour scores higher than any sun/ambient ramp
    // (research/formats/concepts/palette-and-shading.md), and the original picks shades with explicit
    // palette offsets (OP_SHADES, OP_SHADE16), not a sun vector. Row 31 is full brightness.
    out.light_level = 31u;

    return out;
}

@fragment
fn fs_main(in: VertexOutput) -> @location(0) vec4<f32> {
    // Mode 13h flat-shaded pixel lookup with zero bilinear bleed [I3]
    let coords = vec2<i32>(i32(fragment_index(in)), i32(in.light_level & 31u));
    return textureLoad(palette_lut, coords, 0);
}

@fragment
fn fs_main_plane(in: VertexOutput) -> PlaneOutput {
    var out: PlaneOutput;
    let index = fragment_index(in);
    let coords = vec2<i32>(i32(index), i32(in.light_level & 31u));
    out.color = textureLoad(palette_lut, coords, 0);
    var shape = in.shape;
    if (in.prop_vertex != NO_PROP_VERTEX) {
        shape = prop_shape(in.prop_vertex);
    }
    out.plane = vec2<u32>((in.layer << 8u) | index, shape);
    return out;
}

// Sky: PLAYONE paints the sky as band polygons of palette indices 224 to 238 and 0xD0, each
// edge a straight screen line parallel to the horizon, and the sun as a flat disc of index 239
// (crates/stunt-render/src/sky.rs, research/formats/concepts/palette-and-shading.md Sky Bands).
// The CPU lays them out per view; the pass picks a pixel's band and tests the disc.
const SUN_INDEX: u32 = 239u;

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

// Whether raster pixel `pixel` is in the sun disc: PLAYONE's rows run from `cy - r` to
// `cy + r - 1`, row `i` from the centre spanning `round(sqrt(r^2 - i^2))` either side of `cx`
// (0xCF39's span generator).
fn in_sun_disc(pixel: vec2<i32>) -> bool {
    let centre = camera.sun_disc.xy;
    let r = camera.sun_disc.z;
    let dy = pixel.y - centre.y;
    let i = select(-1 - dy, dy, dy >= 0);
    if (i >= r) {
        return false;
    }
    let half = i32(floor(sqrt(f32(r * r - i * i)) + 0.5));
    return abs(pixel.x - centre.x) <= half;
}

fn sky_index(ndc: vec2<f32>) -> u32 {
    // The Mode 13h pixel under the fragment: line_half_ndc is half a pixel in NDC.
    let raster = vec2<f32>(
        (ndc.x + 1.0) * 0.5 / camera.line_half_ndc.x,
        (1.0 - ndc.y) * 0.5 / camera.line_half_ndc.y,
    );
    let pixel = floor(raster);
    let side = dot(camera.sky_normal, pixel);
    var band = 0u;
    for (var i = 0u; i < camera.sky_edge_count; i = i + 1u) {
        if (side >= camera.sky_thresholds[i / 4u][i % 4u]) {
            band = i + 1u;
        }
    }
    var index = camera.sky_colours[band / 4u][band % 4u];
    let covered = (camera.sky_flags & 2u) != 0u && band == camera.sky_edge_count;
    if ((camera.sky_flags & 1u) != 0u && !covered && in_sun_disc(vec2<i32>(pixel))) {
        index = SUN_INDEX;
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
    out.plane = vec2<u32>(index, 0u);
    return out;
}
