// `vs_edge` writes clip distances (wgpu::Features::CLIP_DISTANCES, which the device requires).
enable clip_distances;

// The view's rotation and projection only: every model matrix arrives eye-relative, with the
// eye's translation applied on the CPU in f64 (camera.rs `eye_relative_matrix`), so the only
// world-scale arithmetic left here is a world vertex's `position - eye`, rounded once
// (research/parity/lavapipe.md section 5).
struct CameraUniform {
    rotation_proj: mat4x4<f32>,
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

// Moves a disc's rim vertex at `clip`, whose disc centre is at `centre`, so that the disc's
// filled triangles, drawn without an outline, cover the pixels 0xD11D fills
// (research/playone-exe/sod-vm-generators.md section 8.8). 0xD11D fills rows y - H to
// y + H - 1 and each row from x - w to x + w, with the centre pixel (x, y) the projection's
// centre plus the offset truncated toward it (0xA235..0xA25E) and H truncated (0xA27B). So
// the disc is centred on pixel x's centre and on the boundary above row y, and its vertical
// half-extent is half a pixel short of the radius: sampling pixel centres, that covers
// exactly 2 * trunc(r) rows and 2 * trunc(r) + 1 columns of a disc of radius r pixels. The
// rim vertex's distance from the centre stands in for the vertical half-extent, which it
// equals at the top and bottom of the rim.
fn snap_disc(clip: vec4<f32>, centre: vec4<f32>) -> vec4<f32> {
    if (centre.w <= 0.0 || clip.w <= 0.0) {
        return clip;
    }
    // Pixels from the top-left of the view, and the projection's centre in them.
    let half = 0.5 / camera.line_half_ndc;
    let to_pixels = vec2<f32>(half.x, -half.y);
    let middle = half;
    let c = middle + centre.xy / centre.w * to_pixels;
    let v = middle + clip.xy / clip.w * to_pixels;
    let o = c - middle;
    let snapped = vec2<f32>(
        middle.x + trunc(o.x) + 0.5,
        floor(middle.y) + trunc(o.y),
    );
    let rim = v - c;
    let len = length(rim);
    let shrink = select(0.0, max(0.0, 1.0 - 0.5 / len), len > 0.0);
    let moved = snapped + vec2<f32>(rim.x, rim.y * shrink);
    return vec4<f32>((moved - middle) / to_pixels * clip.w, clip.zw);
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
    // Two ends on one pixel (`playone_vertex` puts every end on a pixel centre) draw that
    // pixel, as the spans draw a polygon on one row (0xCAB4): `along` is rounding noise there.
    let gap = other.xy / other.w - clip.xy / clip.w;
    let one_pixel = clip.w > 0.0 && other.w > 0.0 && all(abs(gap) < camera.line_half_ndc);
    if (one_pixel) {
        offset = vec2<f32>(end, side);
    } else if (abs(along.x) >= abs(along.y)) {
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

// The largest scale `t` of `playone_vertex`'s ray direction `on_ray` (not unit length) at which the
// ray still counts as meeting the vertex's plane; a larger `t` means the ray through its pixel
// runs almost along that plane, and the vertex keeps its own projection.
const PLANE_SLIDE_MAX: f32 = 1.0e6;

// Moves a projected vertex at `clip` (eye-relative position `eye`) to the pixel PLAYONE's
// register projectors put it on: its offset from the projection centre truncated toward the
// centre (`idiv`, 0x9CF1 and 0x9D3A), drawn at that pixel's centre, as the inclusive span
// filler fills the vertex's own pixel (research/playone-exe/sod-vm-lines-spans.md section
// 8.14). The vertex slides along the ray through that pixel to the plane through it with
// eye-relative normal `normal` (`slide_normal`), so facets in one plane (a decal and its base,
// the ground and the ocean) stay coplanar and their depth ties hold. A vertex behind the eye,
// or whose ray does not meet that plane in front of it, keeps its own projection, as does
// every vertex of an orthographic view (shape views), whose clip w does not come from depth.
fn playone_vertex(clip: vec4<f32>, eye: vec4<f32>, normal: vec3<f32>) -> vec4<f32> {
    if (clip.w <= 0.0 || camera.rotation_proj[3][3] != 0.0) {
        return clip;
    }
    // Pixels from the top-left of the view, and our projection's centre in them.
    let half = 0.5 / camera.line_half_ndc;
    let to_pixels = vec2<f32>(half.x, -half.y);
    let middle = half;
    let offset = clip.xy / clip.w * to_pixels;
    let pixel = floor(middle) + trunc(offset) + 0.5;
    let ndc = (pixel - middle) / to_pixels;
    // The direction of the ray through `pixel`: where the planes `x = ndc.x * w` and
    // `y = ndc.y * w` of the projection meet, turned to the side where `w` is positive.
    let row_x = vec3<f32>(camera.rotation_proj[0][0], camera.rotation_proj[1][0], camera.rotation_proj[2][0]);
    let row_y = vec3<f32>(camera.rotation_proj[0][1], camera.rotation_proj[1][1], camera.rotation_proj[2][1]);
    let row_w = vec3<f32>(camera.rotation_proj[0][3], camera.rotation_proj[1][3], camera.rotation_proj[2][3]);
    var on_ray = cross(row_x - ndc.x * row_w, row_y - ndc.y * row_w);
    if (dot(row_w, on_ray) < 0.0) {
        on_ray = -on_ray;
    }
    let t = dot(normal, eye.xyz) / dot(normal, on_ray);
    if (!(t > 0.0) || t > PLANE_SLIDE_MAX) {
        return clip;
    }
    return camera.rotation_proj * vec4<f32>(on_ray * t, 1.0);
}

// World up, the plane normal of a vertex with no facet of its own (`slide_normal`).
const UP: vec3<f32> = vec3<f32>(0.0, 1.0, 0.0);

// A facet whose normal lies within this cosine of vertical slides horizontally (`slide_normal`).
const NEAR_HORIZONTAL: f32 = 0.9;

// The eye-relative normal of the plane `playone_vertex` slides a vertex in. A world mesh vertex
// (terrain, ocean, prop) and a shape facet within about 26 degrees of horizontal slide in the
// horizontal plane through them: the ground, the ocean and a flat prop snapped onto a slope
// (the river) lie in different planes but share one, so their depth ties hold. Any other
// polygon vertex slides in its facet's plane (`normal`, model space; for an outline corner the
// plane of its edge and apex), which keeps a decal on a steep facet on its base. A ZLINETO
// line or a two-vertex polygon (no facet), a degenerate facet and every vertex of a shadow,
// whose model matrix flattens it onto the ground, slide horizontally too.
fn slide_normal(in: VertexInput) -> vec3<f32> {
    var n = in.normal;
    if ((in.attr.y & FLAG_LINE) != 0u) {
        n = cross(in.normal, in.apex - in.position);
    }
    let eye_n = (model.model_matrix * vec4<f32>(n, 0.0)).xyz;
    if (model.layer.y != 0u || in.attr.z != 0u || dot(eye_n, eye_n) == 0.0
        || abs(eye_n.y) >= NEAR_HORIZONTAL * length(eye_n)) {
        return UP;
    }
    return eye_n;
}

@vertex
fn vs_main(in: VertexInput, @builtin(vertex_index) vertex_index: u32) -> VertexOutput {
    return vertex_output(in, vertex_index);
}

// `vs_main`'s work, callable from the other vertex entry points.
fn vertex_output(in: VertexInput, vertex_index: u32) -> VertexOutput {
    var out: VertexOutput;

    // Model space to eye-relative space to clip space.
    let eye_pos = model.model_matrix * vec4<f32>(in.position, 1.0);
    let projected = camera.rotation_proj * eye_pos;
    let plane = slide_normal(in);
    out.clip_position = playone_vertex(projected, eye_pos, plane);
    // OP_PERFDISK skips when shadow mode (work:0x806C) is set
    // (research/playone-exe/sod-vm-generators.md section 8.8).
    if (model.layer.y != 0u && (in.attr.y & FLAG_DISC) != 0u) {
        out.clip_position = vec4<f32>(0.0, 0.0, 0.0, 1.0);
    } else if ((in.attr.y & FLAG_LINE) != 0u) {
        let other_eye = model.model_matrix * vec4<f32>(in.position + in.normal, 1.0);
        let other = playone_vertex(camera.rotation_proj * other_eye, other_eye, plane);
        // An outline corner culls with the triangle its edge bounds, which winds from the
        // edge's first endpoint to its second and on to the apex; a two-sided polygon's and a
        // shadow's stay.
        let apex_eye = model.model_matrix * vec4<f32>(in.apex, 1.0);
        let apex = playone_vertex(camera.rotation_proj * apex_eye, apex_eye, plane);
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
        out.clip_position = snap_disc(squeeze_disc(projected, centre), centre);
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

// How far outside the view an outline line is clipped, as a multiple of `w`: 1.1 puts the
// planes 16 columns past the sides of a 320-column view and 9 rows past the top and bottom of
// a 185-row one, beyond any pixel a one-pixel line draws on screen. Lavapipe does not clip a
// line against the view's sides (Mesa's `bypass_clip_points_lines`), so a line cut beside
// the eye by the near plane reached its rasteriser tens of thousands of pixels off the page
// and was drawn as a wedge; it does clip against these user planes (research/parity/lavapipe-line-clip.md).
const EDGE_CLIP_BAND: f32 = 1.1;

// `VertexOutput` with the clip distances `vs_edge` adds: a fragment input cannot hold them, so
// the varyings are repeated here and must match `VertexOutput`'s.
struct EdgeVertexOutput {
    @builtin(position) clip_position: vec4<f32>,
    @location(0) @interpolate(flat) palette_index: u32,
    @location(1) @interpolate(flat) light_level: u32,
    @location(2) @interpolate(flat) layer: u32,
    @location(3) @interpolate(linear) shade: f32,
    @location(4) @interpolate(perspective) shade_w: f32,
    @location(5) @interpolate(perspective) w: f32,
    @location(6) @interpolate(flat) shape: u32,
    @location(7) @interpolate(flat) prop_vertex: u32,
    @builtin(clip_distances) clip_distances: array<f32, 4>,
};

// `vs_main` for the outline line lists, clipped to `EDGE_CLIP_BAND` times the view on each side.
@vertex
fn vs_edge(in: VertexInput, @builtin(vertex_index) vertex_index: u32) -> EdgeVertexOutput {
    let v = vertex_output(in, vertex_index);
    var out: EdgeVertexOutput;
    out.clip_position = v.clip_position;
    out.palette_index = v.palette_index;
    out.light_level = v.light_level;
    out.layer = v.layer;
    out.shade = v.shade;
    out.shade_w = v.shade_w;
    out.w = v.w;
    out.shape = v.shape;
    out.prop_vertex = v.prop_vertex;
    let c = v.clip_position;
    let band = EDGE_CLIP_BAND * c.w;
    out.clip_distances = array<f32, 4>(band - c.x, band + c.x, band - c.y, band + c.y);
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
