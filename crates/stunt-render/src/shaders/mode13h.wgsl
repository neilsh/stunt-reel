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

// Scenery class of a world prop vertex (contracts/shape/mod.rs SCENERY_PROP).
const SCENERY_PROP: u32 = 3u;
struct VertexInput {
    @location(0) position: vec3<f32>,
    @location(1) normal: vec3<f32>,
    @location(2) attr: vec4<u32>, // x: palette_index, y: flags, z: scenery_class, w: decal_tie
    // The second vertex stream: for an outline corner, the third vertex of the triangle its
    // edge bounds (outline.rs `Outlined`); for any other vertex, its own position.
    @location(3) apex: vec3<f32>,
    // The same stream's shape word: for a world prop vertex, `shape id + 1` of the prop it
    // belongs to (stunt_core::world::PropRun), 0 for any other vertex.
    @location(4) prop_shape: u32,
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
    // The shape word of the pixel: a world prop vertex's own (`VertexInput::prop_shape`),
    // else the draw's (`ModelUniform` `layer.z`). Every vertex of a triangle or line lies in
    // the same prop run, so whichever vertex provokes names it.
    @location(6) @interpolate(flat) shape: u32,
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

// Beyond this many times its own distance, a vertex slid along its plane by `playone_vertex` is
// treated as having missed the plane (the ray through its pixel runs almost along it).
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
// plane of its edge and apex), which keeps a decal on a steep facet on its base; so does a
// world prop's vertex in a decal tie (`SodVertex::decal_tie`), such as a hangar's wall stripe.
// A ZLINETO line or a two-vertex polygon (no facet), a degenerate facet and every vertex of a
// shadow, whose model matrix flattens it onto the ground, slide horizontally too.
fn slide_normal(in: VertexInput) -> vec3<f32> {
    var n = in.normal;
    if ((in.attr.y & FLAG_LINE) != 0u) {
        n = cross(in.normal, in.apex - in.position);
    }
    let eye_n = (model.model_matrix * vec4<f32>(n, 0.0)).xyz;
    let decal_tie = in.attr.z == SCENERY_PROP && in.attr.w != 0u;
    let world = in.attr.z != 0u && !decal_tie;
    if (model.layer.y != 0u || world || dot(eye_n, eye_n) == 0.0
        || abs(eye_n.y) >= NEAR_HORIZONTAL * length(eye_n)) {
        return UP;
    }
    return eye_n;
}

@vertex
fn vs_main(in: VertexInput) -> VertexOutput {
    return vertex_output(in);
}

// `vs_main`'s work, callable from the other vertex entry points.
fn vertex_output(in: VertexInput) -> VertexOutput {
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
    out.shape = select(model.layer.z, in.prop_shape, in.attr.z == SCENERY_PROP);

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
    @builtin(clip_distances) clip_distances: array<f32, 4>,
};

// `vs_main` for the outline line lists, clipped to `EDGE_CLIP_BAND` times the view on each side.
@vertex
fn vs_edge(in: VertexInput) -> EdgeVertexOutput {
    let v = vertex_output(in);
    var out: EdgeVertexOutput;
    out.clip_position = v.clip_position;
    out.palette_index = v.palette_index;
    out.light_level = v.light_level;
    out.layer = v.layer;
    out.shade = v.shade;
    out.shade_w = v.shade_w;
    out.w = v.w;
    out.shape = v.shape;
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
    out.plane = vec2<u32>((in.layer << 8u) | index, in.shape);
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

// The modern look (`--look modern`): directional lighting and distance fog, drawn through entry
// points of its own beside the parity ones above, which keep their code. Viewer-only: never
// scored or stored (docs/SPEC.md [I3]). It reuses `vertex_output`, so the pixel snapping and the
// culling are the parity look's, and the plane output keeps `fragment_index`'s whole index.
// Its sky (`fs_sky_modern`) is a smooth gradient reusing `vs_sky`. Both end in `modern_finish`, the
// optional colour grade and vignette (`--grade`, `--vignette`); the letterbox bars have their own
// pipeline and take neither.

// The sun and fog the modern entry points read (camera.rs `ModernUniform`).
struct ModernUniform {
    // xyz: the unit direction toward the sun in [I1] axes; w: the sun's strength, the share of
    // full brightness a facet facing it gains.
    sun: vec4<f32>,
    // x, y: the fog's start and end distance from the eye in metres.
    fog: vec4<f32>,
    // x: the sky fill's brightness on a facet facing up; y: facing down; z: how far the fill's
    // colour leans toward the sky's rather than white.
    fill: vec4<f32>,
    // The sky's view ray at Mode 13h raster pixel (x, y): sky_ray[0].xyz + x * sky_ray[1].xyz
    // + y * sky_ray[2].xyz, unnormalised, in [I1] axes; sky_ray[0].w is 1 for a perspective view
    // and 0 for an orthographic one, whose sky is the horizon colour throughout.
    sky_ray: array<vec4<f32>, 3>,
    // x: the cosine of the sun glow's inner angle (full strength within it); y: the cosine of its
    // outer angle (none beyond it); z: the glow's strength at its centre.
    glow: vec4<f32>,
    // The colour grade: x: saturation, y: contrast about mid-grey, z: the warm shift (red up by
    // this much, green by 0.35 of it, blue down by it); w is 1 when the grade is on, 0 when it
    // is off and skipped.
    grade: vec4<f32>,
    // The vignette: x: the darkening at the view's corners, 0 when off; y, z: the radius, as a
    // share of the half-diagonal from the view's centre, where the darkening starts and where it
    // is full.
    vignette: vec4<f32>,
    // The view rectangle the scene is drawn into, in target pixels: x, y of its top-left corner,
    // then its width and height. Written where the viewport is set, after the rest.
    view: vec4<f32>,
};

@group(0) @binding(1) var<uniform> modern: ModernUniform;

// SodVertex::flags bit 7 (contracts/shape/mod.rs VERTEX_FLAG_PRESHADED): the palette index
// already carries the light, so Lambert would light it twice.
const FLAG_PRESHADED: u32 = 0x80u;
// SodVertex::flags bit 6 of an OP_PERFDISK rim vertex is `FLAG_DISC` above.

// The horizon sky band (sky.rs `SKY_ZENITH_INDEX + LAST_EDGE`), the colour distance fades to.
const FOG_INDEX: i32 = 238;

// `VertexOutput` with the eye-relative position and the facet normal the modern fragment needs.
struct ModernVertexOutput {
    @builtin(position) clip_position: vec4<f32>,
    @location(0) @interpolate(flat) palette_index: u32,
    @location(1) @interpolate(flat) light_level: u32,
    @location(2) @interpolate(flat) layer: u32,
    @location(3) @interpolate(linear) shade: f32,
    @location(4) @interpolate(perspective) shade_w: f32,
    @location(5) @interpolate(perspective) w: f32,
    @location(6) @interpolate(flat) shape: u32,
    // The vertex's eye-relative position, interpolated perspective-correct.
    @location(7) @interpolate(perspective) eye_pos: vec3<f32>,
    // The eye-relative unit facet normal; zero where the fragment takes no Lambert light.
    @location(8) @interpolate(flat) normal: vec3<f32>,
};

struct ModernEdgeVertexOutput {
    @builtin(position) clip_position: vec4<f32>,
    @location(0) @interpolate(flat) palette_index: u32,
    @location(1) @interpolate(flat) light_level: u32,
    @location(2) @interpolate(flat) layer: u32,
    @location(3) @interpolate(linear) shade: f32,
    @location(4) @interpolate(perspective) shade_w: f32,
    @location(5) @interpolate(perspective) w: f32,
    @location(6) @interpolate(flat) shape: u32,
    @location(7) @interpolate(perspective) eye_pos: vec3<f32>,
    @location(8) @interpolate(flat) normal: vec3<f32>,
    @builtin(clip_distances) clip_distances: array<f32, 4>,
};

// The eye-relative unit normal of the surface `in` lights, zero when it takes no Lambert light:
// a pre-shaded vertex, a shadow, a disc's rim, and a line with no facet (a ZLINETO).
fn modern_normal(in: VertexInput) -> vec3<f32> {
    if ((in.attr.y & FLAG_PRESHADED) != 0u || model.layer.y != 0u
        || (in.attr.y & FLAG_DISC) != 0u) {
        return vec3<f32>(0.0);
    }
    var n = in.normal;
    if ((in.attr.y & FLAG_LINE) != 0u) {
        // An outline corner's `normal` is its segment: light it by its edge's facet, as
        // `slide_normal` slides it.
        n = cross(in.normal, in.apex - in.position);
    }
    // Turned by the model matrix itself, not its inverse transpose: right for the rotations and
    // uniform scales of an actor's or the world's matrix.
    let eye_n = (model.model_matrix * vec4<f32>(n, 0.0)).xyz;
    let len = length(eye_n);
    if (len == 0.0) {
        return vec3<f32>(0.0);
    }
    return eye_n / len;
}

fn modern_vertex(in: VertexInput) -> ModernVertexOutput {
    let v = vertex_output(in);
    var out: ModernVertexOutput;
    out.clip_position = v.clip_position;
    out.palette_index = v.palette_index;
    out.light_level = v.light_level;
    out.layer = v.layer;
    out.shade = v.shade;
    out.shade_w = v.shade_w;
    out.w = v.w;
    out.shape = v.shape;
    out.eye_pos = (model.model_matrix * vec4<f32>(in.position, 1.0)).xyz;
    out.normal = modern_normal(in);
    return out;
}

@vertex
fn vs_modern(in: VertexInput) -> ModernVertexOutput {
    return modern_vertex(in);
}

// `vs_modern` for the outline line lists, clipped as `vs_edge` clips them.
@vertex
fn vs_modern_edge(in: VertexInput) -> ModernEdgeVertexOutput {
    let v = modern_vertex(in);
    var out: ModernEdgeVertexOutput;
    out.clip_position = v.clip_position;
    out.palette_index = v.palette_index;
    out.light_level = v.light_level;
    out.layer = v.layer;
    out.shade = v.shade;
    out.shade_w = v.shade_w;
    out.w = v.w;
    out.shape = v.shape;
    out.eye_pos = v.eye_pos;
    out.normal = v.normal;
    let c = v.clip_position;
    let band = EDGE_CLIP_BAND * c.w;
    out.clip_distances = array<f32, 4>(band - c.x, band + c.x, band - c.y, band + c.y);
    return out;
}

// The `VertexOutput` the parity fragment code reads, rebuilt from `in`.
fn parity_input(in: ModernVertexOutput) -> VertexOutput {
    var v: VertexOutput;
    v.clip_position = in.clip_position;
    v.palette_index = in.palette_index;
    v.light_level = in.light_level;
    v.layer = in.layer;
    v.shade = in.shade;
    v.shade_w = in.shade_w;
    v.w = in.w;
    v.shape = in.shape;
    return v;
}

// The fractional palette index the modern look colours a fragment by: `fragment_index`'s guarded
// read of `shade`, unrounded. A modern copy of that logic, not a refactor of it, so the parity
// entry points keep their code. The same lavapipe guard applies: where `shade` interpolates to
// NaN, the perspective ratio `shade_w / w` stands in, then the provoking vertex's index.
fn modern_shade(in: ModernVertexOutput) -> f32 {
    var shade = in.shade;
    if (is_non_finite(shade)) {
        let screen_linear = in.shade_w / in.w;
        if (is_non_finite(screen_linear)) {
            return f32(in.palette_index);
        }
        shade = screen_linear;
    }
    return clamp(shade, 0.0, 255.0);
}

// The palette colour of index `index` at full brightness (row 31, so palette fades still apply).
fn modern_palette(index: i32) -> vec3<f32> {
    return textureLoad(palette_lut, vec2<i32>(index, 31), 0).rgb;
}

// `colour` scaled to unit luminance (Rec. 601 weights): a tint that changes no brightness.
fn modern_tint(colour: vec3<f32>) -> vec3<f32> {
    return colour / max(dot(colour, vec3<f32>(0.299, 0.587, 0.114)), 1e-4);
}

// The optional finish on a modern fragment's colour, in the target's sRGB values: `grade` then
// `vignette`, each skipped when off so that with both off the colour is untouched. The grade
// scales the colour's distance from its luma by the saturation, its distance from mid-grey by the
// contrast, then adds the warm shift (`grade.z` to red, 0.35 of it to green, minus it to blue).
// The vignette scales the colour by `1 - strength * smoothstep(r0, r1, r)`, `r` the fragment's
// distance from the view's centre over the view's half-diagonal.
fn modern_finish(colour: vec3<f32>, frag_xy: vec2<f32>) -> vec3<f32> {
    var rgb = colour;
    if (modern.grade.w != 0.0) {
        let luma = dot(rgb, vec3<f32>(0.2126, 0.7152, 0.0722));
        rgb = mix(vec3<f32>(luma), rgb, modern.grade.x);
        rgb = (rgb - 0.5) * modern.grade.y + 0.5;
        rgb = rgb + modern.grade.z * vec3<f32>(1.0, 0.35, -1.0);
        rgb = clamp(rgb, vec3<f32>(0.0), vec3<f32>(1.0));
    }
    if (modern.vignette.x > 0.0 && modern.view.z > 0.0 && modern.view.w > 0.0) {
        let centre = modern.view.xy + 0.5 * modern.view.zw;
        let r = length(frag_xy - centre) / (0.5 * length(modern.view.zw));
        let edge = smoothstep(modern.vignette.y, modern.vignette.z, r);
        rgb = rgb * (1.0 - modern.vignette.x * edge);
    }
    return rgb;
}

// The colour of a fragment under the sun, the sky fill and the fog. Lighting is in RGB, not a
// palette row: the base is the palette colour at full brightness, the blend of the two entries
// either side of the fractional index `s`, so a Gouraud ramp is smooth where the parity look
// steps; an integer `s` gives exactly that entry. A facet takes `min(sun * lambert + fill, 1)`
// per channel, with `n` flipped toward the eye so either winding is lit on the side it shows.
// The fill is a hemisphere term, `FILL_UP` for a facet facing up to `FILL_DOWN` for one facing
// down, tinted by the zenith and horizon sky colours; the cap keeps a lit facet no brighter than
// its parity colour. A pre-shaded polygon, a disc and a line with no facet (a ZLINETO) have a
// zero normal: no light, no fill, their ramp smoothed. Distance then mixes the horizon sky in
// (`modern.fog.y` is past `modern.fog.x`, camera.rs `ModernUniform`), and `modern_finish` ends it.
fn modern_colour(in: ModernVertexOutput, s: f32) -> vec4<f32> {
    let i0 = i32(floor(s));
    let i1 = min(i0 + 1, 255);
    var base = mix(modern_palette(i0), modern_palette(i1), s - floor(s));
    if (dot(in.normal, in.normal) > 0.0) {
        var n = in.normal;
        if (dot(n, in.eye_pos) > 0.0) {
            n = -n;
        }
        let lambert = max(dot(n, modern.sun.xyz), 0.0);
        let up = 0.5 + 0.5 * n.y;
        let tint = mix(
            vec3<f32>(1.0),
            mix(modern_tint(modern_palette(FOG_INDEX)), modern_tint(modern_palette(224)), up),
            modern.fill.z,
        );
        let fill = mix(modern.fill.y, modern.fill.x, up) * tint;
        base = base * min(vec3<f32>(modern.sun.w * lambert) + fill, vec3<f32>(1.0));
    }
    let fog = modern_palette(FOG_INDEX);
    let amount = clamp(
        (length(in.eye_pos) - modern.fog.x) / (modern.fog.y - modern.fog.x),
        0.0,
        1.0,
    );
    return vec4<f32>(modern_finish(mix(base, fog, amount), in.clip_position.xy), 1.0);
}

@fragment
fn fs_modern(in: ModernVertexOutput) -> @location(0) vec4<f32> {
    return modern_colour(in, modern_shade(in));
}

@fragment
fn fs_modern_plane(in: ModernVertexOutput) -> PlaneOutput {
    var out: PlaneOutput;
    let index = fragment_index(parity_input(in));
    out.color = modern_colour(in, modern_shade(in));
    out.plane = vec2<u32>((in.layer << 8u) | index, in.shape);
    return out;
}

// The tangent of the elevation of the last sky band edge, 256 / 14336 (sky.rs `LAST_EDGE`: edge
// 14 is the point 14336 out and 256 up): at or below it the sky is the horizon colour.
const SKY_HORIZON_TAN: f32 = 0.017857143;

// The modern sky's colour on the Mode 13h raster at `ndc`, unfloored so the gradient is smooth at
// any output resolution. PLAYONE's band edge `j` is the point `1024 j` out and `2048 - 128 j` up,
// so a ray at elevation `t` (its tangent) lies on the continuous edge `j = 2048 / (1024 t + 128)`,
// and its colour is the blend of the palette entries either side of `224 + j`: the zenith colour
// straight up, `FOG_INDEX`'s colour at and below edge 14's elevation, with no seam where the fog
// meets it, a low sun's glow included: the glow tints only the sky above that elevation. The
// elevation is tested first: the formula's denominator reaches zero at
// `t = -0.125`, where a clamp would turn steep downward rays zenith-coloured. The edges are the
// view's centre column's bands; under pitch PLAYONE's straight edges differ away from it. The sun
// is a soft glow of its colour (index 239), not a hard disc.
fn modern_sky(ndc: vec2<f32>) -> vec3<f32> {
    let horizon = modern_palette(FOG_INDEX);
    if (modern.sky_ray[0].w == 0.0) {
        return horizon;
    }
    let raster = vec2<f32>(
        (ndc.x + 1.0) * 0.5 / camera.line_half_ndc.x,
        (1.0 - ndc.y) * 0.5 / camera.line_half_ndc.y,
    );
    let ray = normalize(
        modern.sky_ray[0].xyz + raster.x * modern.sky_ray[1].xyz + raster.y * modern.sky_ray[2].xyz,
    );
    let ground = length(ray.xz);
    var colour = horizon;
    if (ray.y > SKY_HORIZON_TAN * ground) {
        var j = 0.0;
        if (ground > 0.0) {
            j = 2048.0 / (1024.0 * ray.y / ground + 128.0);
        }
        let s = 224.0 + clamp(j, 0.0, 14.0);
        let i0 = i32(floor(s));
        colour = mix(modern_palette(i0), modern_palette(min(i0 + 1, 255)), s - floor(s));
        let toward = smoothstep(modern.glow.y, modern.glow.x, dot(ray, modern.sun.xyz));
        colour = mix(colour, modern_palette(i32(SUN_INDEX)), toward * modern.glow.z);
    }
    return colour;
}

@fragment
fn fs_sky_modern(in: SkyVertexOutput) -> @location(0) vec4<f32> {
    return vec4<f32>(modern_finish(modern_sky(in.ndc), in.clip_position.xy), 1.0);
}

// The plane keeps the parity sky's index (`fs_sky_plane`), so picking and the layer plane see it.
@fragment
fn fs_sky_modern_plane(in: SkyVertexOutput) -> PlaneOutput {
    var out: PlaneOutput;
    out.color = vec4<f32>(modern_finish(modern_sky(in.ndc), in.clip_position.xy), 1.0);
    out.plane = vec2<u32>(sky_index(in.ndc), 0u);
    return out;
}
