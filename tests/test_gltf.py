"""Comprehensive 100% offline unit and integration tests for Stunt Reel glTF exporter.

Covers:
- Authentic Mode 13h 256-color palette RGB mapping [I3].
- Baseline .SOD bytecode mesh parser and 12-byte aligned register VM [I1], [I2].
- Invariant [I5] coplanar decal identification and normal displacement (eps = 0.001 m).
- Pure standard library binary glTF 2.0 (.glb) container packing and 4-byte chunk alignment.
- 600-tick flight choreography trajectory animation binding.
- Invariant [I6] visual parity pipeline, 1.2x vertical aspect stretch (320x200 -> 320x240), and SSIM.
"""

from __future__ import annotations

import math
import struct
from pathlib import Path

import pytest

from stunt_reel.gltf import (
    DECAL_FLAG_BIT,
    EPSILON_DISPLACEMENT,
    GLB_BIN_CHUNK_TYPE,
    GLB_HEADER_MAGIC,
    GLB_JSON_CHUNK_TYPE,
    MODE_13H_PALETTE,
    OP_ADDV,
    OP_CLRV,
    OP_COLOR,
    OP_GETV,
    OP_INTV,
    OP_IPG,
    OP_NEGV,
    OP_POLYZ,
    OP_PUTV,
    OP_RETURN,
    OP_SHLV,
    OP_SHRV,
    OP_SUBV,
    PHASE1_SSIM_THRESHOLD,
    SOD_SCALE_TABLE,
    GlbBuilder,
    SodPolygon,
    VisualParityReport,
    apply_decal_displacement_to_model,
    bounds_overlap,
    build_baseline_aircraft_sod,
    build_runway_sod,
    compute_camera_quaternion,
    compute_frame_ssim,
    evaluate_visual_parity,
    export_trajectory_to_glb,
    get_palette_color_0,
    get_palette_rgb,
    get_palette_rgb_float,
    is_coplanar_facet,
    parse_glb_bytes,
    parse_sod_bytes,
    parse_sod_file,
    rescale_mode13h_frame,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"
SYNTHETIC_SOD_PATH = FIXTURES_DIR / "synthetic_minimal.sod"
SYNTHETIC_TRAJ_PATH = FIXTURES_DIR / "oracle_intro_trajectory.json"


# -----------------------------------------------------------------------------
# 1. Palette Mapping Tests [I3]
# -----------------------------------------------------------------------------


def test_palette_structure_and_bounds() -> None:
    """Verify authentic Mode 13h 256-color palette size, values, and wrapping."""
    assert len(MODE_13H_PALETTE) == 256
    # Index 0 is black
    assert get_palette_rgb(0) == (0, 0, 0)
    # Index 255 is white
    assert get_palette_rgb(255) == (252, 252, 252)

    # Index masking: index 256 wraps to index 0
    assert get_palette_rgb(256) == get_palette_rgb(0)
    assert get_palette_rgb(-1) == get_palette_rgb(255)


def test_palette_color_0_normalization() -> None:
    """Verify glTF COLOR_0 attributes are normalized to [0.0, 1.0] with alpha 1.0."""
    col0 = get_palette_color_0(0)
    assert len(col0) == 4
    assert col0 == (0.0, 0.0, 0.0, 1.0)

    col255 = get_palette_color_0(255)
    assert col255[3] == 1.0
    for comp in col255[:3]:
        assert 0.98 <= comp <= 1.0

    col_float = get_palette_rgb_float(40)
    assert len(col_float) == 3
    for comp in col_float:
        assert 0.0 <= comp <= 1.0


# -----------------------------------------------------------------------------
# 2. .SOD Decoder & VM Tests [I1], [I2]
# -----------------------------------------------------------------------------


def test_sod_header_validation() -> None:
    """Test header parsing, magic verification, and error handling."""
    # Data too short
    with pytest.raises(ValueError, match="too short"):
        parse_sod_bytes(b"\x00" * 8)

    # Invalid magic
    with pytest.raises(ValueError, match="Invalid SOD magic"):
        parse_sod_bytes(struct.pack("<HHhHH", 0x1234, 100, 0, 1, 0))


def test_sod_scale_table() -> None:
    """Verify power-of-2 scaling factors match historical sod_scale_table."""
    assert len(SOD_SCALE_TABLE) == 18
    assert SOD_SCALE_TABLE[0] == 10.0
    assert SOD_SCALE_TABLE[1] == 5.0
    assert SOD_SCALE_TABLE[2] == 2.5
    assert SOD_SCALE_TABLE[3] == 1.25


def test_sod_decoder_synthetic_minimal() -> None:
    """Parse synthetic_minimal.sod cleanroom fixture and verify geometric structures."""
    assert SYNTHETIC_SOD_PATH.exists()
    model = parse_sod_file(SYNTHETIC_SOD_PATH)

    assert model.name == "SYNTHETIC_MINIMAL"
    assert model.bounding_size == 100
    assert model.ground_y_offset == 0
    assert model.scale_factor == 0.5  # scale_index = 1 -> 5.0 / 10.0 = 0.5
    assert len(model.polygons) == 2

    # Poly 0: Base wing triangle
    p0 = model.polygons[0]
    assert p0.palette_index == 40
    assert p0.vertices == [(0.0, 0.0, 0.0), (5.0, 0.0, 0.0), (0.0, 5.0, 0.0)]
    assert p0.normal == (0.0, 0.0, 1.0)
    assert not p0.is_decal

    # Poly 1: Decal triangle
    p1 = model.polygons[1]
    assert p1.palette_index == 15
    assert p1.vertices == [(1.0, 1.0, 0.0), (3.0, 1.0, 0.0), (0.0, 5.0, 0.0)]
    assert abs(p1.normal[2] - 1.0) < 1e-6

    # Triangulation & welding
    verts, indices = model.triangulate()
    assert len(verts) > 0
    assert len(indices) == 6  # 2 triangles * 3 indices
    assert model.to_sod_model_ir()["name"] == "SYNTHETIC_MINIMAL"


def test_sod_vm_arithmetic_opcodes() -> None:
    """Verify vertex register VM execution (ADDV, SUBV, INTV, NEGV, SHLV, SHRV, IPG)."""
    # Header: OP_ID, bound=50, yoff=0, scale=0 (scale_factor=1.0), col=0
    header = struct.pack("<HHhHH", 0x000C, 50, 0, 0, 0)
    bytecode = bytearray(header)

    # 1. OP_IPG Type 0 (Cube) at register 0 (offset 0)
    bytecode.extend(struct.pack("<HHHHH", OP_IPG, 0, 10, 20, 30))
    bytecode.extend(struct.pack("<H", 0))  # offset 0

    # 2. OP_GETV from reg 0
    bytecode.extend(struct.pack("<HH", OP_GETV, 0))

    # 3. OP_NEGV
    bytecode.extend(struct.pack("<H", OP_NEGV))

    # 4. OP_PUTV to reg 10 (offset 120 = 0x78)
    bytecode.extend(struct.pack("<HH", OP_PUTV, 120))

    # 5. OP_ADDV with reg 10
    bytecode.extend(struct.pack("<HH", OP_ADDV, 120))

    # 6. OP_SUBV with reg 10
    bytecode.extend(struct.pack("<HH", OP_SUBV, 120))

    # 7. OP_INTV with reg 10
    bytecode.extend(struct.pack("<HH", OP_INTV, 120))

    # 8. OP_SHLV shift 1
    bytecode.extend(struct.pack("<HH", OP_SHLV, 1))

    # 9. OP_SHRV shift 1
    bytecode.extend(struct.pack("<HH", OP_SHRV, 1))

    # 10. OP_CLRV
    bytecode.extend(struct.pack("<H", OP_CLRV))

    # 11. OP_COLOR + OP_POLYZ with reg 0, 1, 2
    bytecode.extend(struct.pack("<HH", OP_COLOR, 35))
    bytecode.extend(struct.pack("<5H", OP_POLYZ, 3, 0, 12, 24))

    # 12. OP_RETURN
    bytecode.extend(struct.pack("<H", OP_RETURN))

    model = parse_sod_bytes(bytes(bytecode), name="VM_TEST")
    assert len(model.polygons) == 1
    assert model.polygons[0].palette_index == 35


# -----------------------------------------------------------------------------
# 3. Invariant [I5] Decal Identification & Displacement Tests
# -----------------------------------------------------------------------------


def test_coplanar_facet_detection() -> None:
    """Verify plane geometry tests identify coplanar facets and reject non-coplanar ones."""
    poly_base = SodPolygon(
        vertices=[(0.0, 0.0, 0.0), (10.0, 0.0, 0.0), (5.0, 10.0, 0.0)],
        palette_index=40,
        normal=(0.0, 0.0, 1.0),
    )
    # Overlapping decal on same Z=0 plane
    poly_decal = SodPolygon(
        vertices=[(2.0, 2.0, 0.0), (4.0, 2.0, 0.0), (3.0, 4.0, 0.0)],
        palette_index=15,
        normal=(0.0, 0.0, 1.0),
    )
    # Non-coplanar: different plane constant (Z=1.0)
    poly_parallel_offset = SodPolygon(
        vertices=[(2.0, 2.0, 1.0), (4.0, 2.0, 1.0), (3.0, 4.0, 1.0)],
        palette_index=15,
        normal=(0.0, 0.0, 1.0),
    )
    # Non-coplanar: orthogonal normal
    poly_orthogonal = SodPolygon(
        vertices=[(0.0, 0.0, 0.0), (0.0, 10.0, 0.0), (0.0, 5.0, 10.0)],
        palette_index=15,
        normal=(1.0, 0.0, 0.0),
    )

    assert is_coplanar_facet(poly_decal, poly_base)
    assert not is_coplanar_facet(poly_parallel_offset, poly_base)
    assert not is_coplanar_facet(poly_orthogonal, poly_base)


def test_decal_normal_displacement() -> None:
    """Verify Invariant [I5] displacements nudge vertices along outward surface normal by eps = 0.001m."""
    model = parse_sod_file(SYNTHETIC_SOD_PATH)
    displaced_model = apply_decal_displacement_to_model(model, eps=EPSILON_DISPLACEMENT)

    # Base wing facet: NOT displaced
    p0 = displaced_model.polygons[0]
    assert not p0.is_decal
    assert p0.flags == 0
    assert p0.vertices[0] == (0.0, 0.0, 0.0)

    # Decal facet: displaced by 0.001m in +Z direction
    p1 = displaced_model.polygons[1]
    assert p1.is_decal
    assert p1.flags & DECAL_FLAG_BIT
    # Original v0 was (1.0, 1.0, 0.0) -> now (1.0, 1.0, 0.001)
    assert abs(p1.vertices[0][0] - 1.0) < 1e-6
    assert abs(p1.vertices[0][1] - 1.0) < 1e-6
    assert abs(p1.vertices[0][2] - EPSILON_DISPLACEMENT) < 1e-6


def test_bounds_overlap_logic() -> None:
    """Test 3D bounding box overlap helper."""
    min1, max1 = (0.0, 0.0, 0.0), (10.0, 10.0, 10.0)
    min2, max2 = (5.0, 5.0, 5.0), (15.0, 15.0, 15.0)
    min3, max3 = (20.0, 20.0, 20.0), (30.0, 30.0, 30.0)

    assert bounds_overlap(min1, max1, min2, max2)
    assert not bounds_overlap(min1, max1, min3, max3)


# -----------------------------------------------------------------------------
# 4. Pure Python Binary glTF 2.0 (.glb) Writer Tests
# -----------------------------------------------------------------------------


def test_glb_container_headers_and_chunk_alignment() -> None:
    """Verify binary GLB 12-byte header, JSON chunk, and BIN chunk 4-byte padding."""
    builder = GlbBuilder(asset_generator="stunt-reel unit test")
    m_idx = builder.add_mesh_primitive(
        positions=[[0, 0, 0], [1, 0, 0], [0, 1, 0]],
        normals=[[0, 0, 1], [0, 0, 1], [0, 0, 1]],
        colors=[[1, 0, 0, 1], [0, 1, 0, 1], [0, 0, 1, 1]],
        indices=[0, 1, 2],
        name="TestMesh",
    )
    builder.add_node(name="RootNode", mesh=m_idx, is_scene_root=True)
    glb_data = builder.build_glb()

    assert len(glb_data) >= 20
    # 1. 12-byte header
    magic, version, total_len = struct.unpack_from("<4sII", glb_data, 0)
    assert magic == GLB_HEADER_MAGIC
    assert version == 2
    assert total_len == len(glb_data)
    assert total_len % 4 == 0

    # 2. Chunk 0: JSON
    c0_len, c0_type = struct.unpack_from("<II", glb_data, 12)
    assert c0_type == GLB_JSON_CHUNK_TYPE
    assert c0_len % 4 == 0

    # 3. Chunk 1: BIN
    bin_header_pos = 20 + c0_len
    c1_len, c1_type = struct.unpack_from("<II", glb_data, bin_header_pos)
    assert c1_type == GLB_BIN_CHUNK_TYPE
    assert c1_len % 4 == 0

    # Roundtrip parser verification
    json_dict, bin_bytes = parse_glb_bytes(glb_data)
    assert json_dict["asset"]["version"] == "2.0"
    assert len(json_dict["meshes"]) == 1
    assert len(bin_bytes) == c1_len


def test_glb_accessor_min_max_bounds() -> None:
    """Verify glTF 2.0 spec requirement: POSITION accessors must have accurate min/max."""
    builder = GlbBuilder()
    positions = [[1.5, -2.0, 3.0], [4.0, 5.5, -1.0], [0.0, 0.0, 0.0]]
    builder.add_mesh_primitive(
        positions=positions,
        normals=[[0, 1, 0], [0, 1, 0], [0, 1, 0]],
        colors=[[1, 1, 1, 1], [1, 1, 1, 1], [1, 1, 1, 1]],
        indices=[0, 1, 2],
    )
    glb_data = builder.build_glb()
    json_dict, _ = parse_glb_bytes(glb_data)

    pos_acc = json_dict["accessors"][0]
    assert pos_acc["type"] == "VEC3"
    assert pos_acc["min"] == [0.0, -2.0, -1.0]
    assert pos_acc["max"] == [4.0, 5.5, 3.0]


# -----------------------------------------------------------------------------
# 5. Animated Trajectory Export Tests
# -----------------------------------------------------------------------------


def test_camera_quaternion_computation() -> None:
    """Verify camera orientation quaternion computation against standard look-at."""
    eye = [0.0, 10.0, 50.0]
    target = [0.0, 10.0, 0.0]
    # Looking down -Z
    quat = compute_camera_quaternion(eye, target, roll_radians=0.0)
    assert len(quat) == 4
    # Unit norm constraint
    norm = math.sqrt(sum(c * c for c in quat))
    assert abs(norm - 1.0) < 1e-4


def test_end_to_end_intro_export_roundtrip(tmp_path: Path) -> None:
    """Export animated INTRO.glb from trajectory records and validate scene structure."""
    out_file = tmp_path / "TEST_INTRO.glb"
    assert SYNTHETIC_TRAJ_PATH.exists()

    result_path = export_trajectory_to_glb(
        trajectory_path=SYNTHETIC_TRAJ_PATH,
        output_path=out_file,
        tick_rate=20.0,
    )
    assert result_path.exists()
    assert result_path.stat().st_size > 0

    json_dict, _bin_bytes = parse_glb_bytes(result_path.read_bytes())
    assert json_dict["asset"]["version"] == "2.0"
    assert len(json_dict["scenes"]) == 1
    assert len(json_dict["nodes"]) >= 3
    assert len(json_dict["meshes"]) >= 1
    assert len(json_dict["animations"]) == 1

    anim = json_dict["animations"][0]
    assert anim["name"] == "INTRO_ALL"
    assert len(anim["channels"]) >= 2
    assert len(anim["samplers"]) >= 2


def test_baseline_aircraft_and_runway_generators() -> None:
    """Verify built-in baseline Fokker biplane and runway models have authentic decals."""
    plane = build_baseline_aircraft_sod("TEST_FOKKER")
    assert plane.name == "TEST_FOKKER"
    assert len(plane.polygons) >= 10
    # Decal roundels identified and displaced
    decal_polys = [p for p in plane.polygons if p.is_decal]
    assert len(decal_polys) >= 2
    for dp in decal_polys:
        assert dp.flags & DECAL_FLAG_BIT

    runway = build_runway_sod("TEST_RUNWAY")
    assert runway.name == "TEST_RUNWAY"
    runway_decals = [p for p in runway.polygons if p.is_decal]
    assert len(runway_decals) >= 5


# -----------------------------------------------------------------------------
# 6. Invariant [I6] Visual Parity Pipeline Tests
# -----------------------------------------------------------------------------


def test_aspect_ratio_rescaling() -> None:
    """Verify Mode 13h 320x200 -> 320x240 vertical aspect correction (1.2x factor)."""
    raw_200 = [100] * (320 * 200)
    # Nearest neighbor
    rescaled_nearest = rescale_mode13h_frame(raw_200, width=320, height=200, target_height=240)
    assert len(rescaled_nearest) == 320 * 240
    assert all(abs(v - 100.0) < 1e-4 for v in rescaled_nearest)

    # Bilinear
    rescaled_bilinear = rescale_mode13h_frame(
        raw_200, width=320, height=200, target_height=240, interpolation="bilinear"
    )
    assert len(rescaled_bilinear) == 320 * 240
    assert all(abs(v - 100.0) < 1e-4 for v in rescaled_bilinear)


def test_ssim_computation_identical_frames() -> None:
    """Verify SSIM between identical images is strictly 1.0000."""
    frame = [(i * 7) % 256 for i in range(320 * 240)]
    score = compute_frame_ssim(frame, frame, width=320, height=240)
    assert abs(score - 1.0) < 1e-5


def test_ssim_computation_degraded_frames() -> None:
    """Verify SSIM calculation responds to subtle luminance perturbations."""
    frame_ref = [(i * 3) % 256 for i in range(320 * 240)]
    frame_test = [min(255, v + 8) for v in frame_ref]

    score = compute_frame_ssim(frame_ref, frame_test, width=320, height=240)
    assert 0.88 <= score < 1.0


def test_visual_parity_report_evaluation() -> None:
    """Verify VisualParityReport evaluation complies with Seam 4 acceptance contract."""
    frame_ref = [128] * (320 * 200)
    frame_test = [128] * (320 * 200)

    report = evaluate_visual_parity(
        reference_frames=[frame_ref],
        test_frames=[frame_test],
        film_name="INTRO.ALL",
        threshold=PHASE1_SSIM_THRESHOLD,
    )
    assert report.frames_evaluated == 1
    assert abs(report.mean_ssim - 1.0) < 1e-5
    assert report.is_passing()

    # Failing threshold case
    failing_report = VisualParityReport(
        film_name="INTRO.ALL",
        frames_evaluated=10,
        mean_ssim=0.82,
        min_ssim=0.79,
        threshold=0.88,
        passed=True,
    )
    assert not failing_report.is_passing()
