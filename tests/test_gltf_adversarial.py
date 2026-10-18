"""Adversarial stress tests and empirical verification for Stunt Reel glTF exporter.

Empirical verification suite for Challenger 2 (Ticket T04 / Milestone 1 Gate 1):
1. SOD bytecode VM: register indexing boundary cases (reg 0, 1023, out-of-bounds, unaligned),
   malformed opcode handling, vertex welding with attribute preservation [I1].
2. Invariant [I5] Decal Displacement: coplanar detection edge cases (strictly parallel vs slightly skewed,
   identical vs non-identical plane distance, non-overlapping bounding boxes, degenerate facets),
   strict +0.001 m displacement along outward surface normals, DECAL_FLAG_BIT setting.
3. Binary GLB structure: byte-exact 4-byte alignment of JSON and BIN chunks, magic header `glTF`,
   version 2, accessor byteOffsets, bufferView alignment, min/max array bounds.
4. Animation samplers: monotonically increasing non-negative timestamps, matching input/output counts,
   valid interpolation modes.
"""

from __future__ import annotations

import json
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
    OP_CLRV,
    OP_COLOR,
    OP_GETV,
    OP_ID,
    OP_IFVIS,
    OP_IPG,
    OP_POLYZ,
    OP_PUTV,
    OP_RETURN,
    OP_VECTORS,
    GlbBuilder,
    SodModel,
    SodPolygon,
    displace_decal_polygon,
    identify_coplanar_decals,
    is_coplanar_facet,
    parse_glb_bytes,
    parse_sod_bytes,
)

INTRO_GLB_PATH = Path("build/gltf_output/INTRO.glb")


def _make_sod_header(scale: int = 0) -> bytes:
    """Helper to pack a standard 10-byte SOD header."""
    return struct.pack("<HHhHH", OP_ID, 100, 0, scale, 0)


# =============================================================================
# 1. SOD Bytecode VM Adversarial Tests [I1], [I2]
# =============================================================================


def test_sod_vm_register_boundary_0_and_1023() -> None:
    """Test register indexing boundaries: register 0 (offset 0) and register 1023 (offset 12276)."""
    bytecode = bytearray(_make_sod_header())
    # Set reg 0 via OP_VECTORS: [12.0, -34.0, 56.0]
    bytecode.extend(struct.pack("<HHHhhh", OP_VECTORS, 1, 0, 12, -34, 56))
    # Copy reg 0 -> cur_vert -> reg 1023
    bytecode.extend(struct.pack("<HH", OP_GETV, 0))
    bytecode.extend(struct.pack("<HH", OP_PUTV, 1023 * 12))
    # Clear cur_vert, then retrieve from reg 1023
    bytecode.extend(struct.pack("<H", OP_CLRV))
    bytecode.extend(struct.pack("<HH", OP_GETV, 1023 * 12))
    # Put into reg 1
    bytecode.extend(struct.pack("<HH", OP_PUTV, 12))
    # Emit polygon using reg 0, reg 1, reg 1023
    bytecode.extend(struct.pack("<HH", OP_COLOR, 45))
    bytecode.extend(struct.pack("<5H", OP_POLYZ, 3, 0, 12, 1023 * 12))
    bytecode.extend(struct.pack("<H", OP_RETURN))

    model = parse_sod_bytes(bytes(bytecode), name="REG_BOUNDARY")
    assert len(model.polygons) == 1
    poly = model.polygons[0]
    assert poly.palette_index == 45
    assert len(poly.vertices) == 3
    # reg 0, reg 1, and reg 1023 should all have identical coordinates (12.0, -34.0, 56.0)
    for v in poly.vertices:
        assert v == (12.0, -34.0, 56.0)


def test_sod_vm_out_of_bounds_and_unaligned_register_offsets() -> None:
    """Verify that unaligned offsets and offsets >= 1024*12 are masked safely and do not raise IndexError."""
    bytecode = bytearray(_make_sod_header())
    # Unaligned offset 13 -> 13 // 12 = 1, masked with 1023 = 1
    bytecode.extend(struct.pack("<HH", OP_PUTV, 13))
    # Out of bounds offset 12288 -> 12288 // 12 = 1024, masked with 1023 = 0
    bytecode.extend(struct.pack("<HH", OP_PUTV, 12288))
    # Maximum 16-bit unsigned offset 65535 -> 65535 // 12 = 5461, masked with 1023 = 341
    bytecode.extend(struct.pack("<HH", OP_PUTV, 65535))
    bytecode.extend(struct.pack("<HH", OP_GETV, 65535))
    bytecode.extend(struct.pack("<H", OP_RETURN))

    model = parse_sod_bytes(bytes(bytecode), name="OOB_REGS")
    assert model.name == "OOB_REGS"


def test_sod_vm_ipg_register_wraparound() -> None:
    """Test procedural geometry generation (OP_IPG) wrapping around register 1023 into 0..7."""
    bytecode = bytearray(_make_sod_header())
    # IPG Cube starting at register 1022 (spans registers 1022, 1023, 0, 1, 2, 3, 4, 5)
    bytecode.extend(struct.pack("<HHHHH", OP_IPG, 0, 10, 10, 10))
    bytecode.extend(struct.pack("<H", 1022 * 12))

    # IPG Ground Quad starting at register 1023 (spans registers 1023, 0, 1, 2)
    bytecode.extend(struct.pack("<HHHH", OP_IPG, 2, 20, 20))
    bytecode.extend(struct.pack("<H", 1023 * 12))

    # IPG Flat Quad starting at register 1021 (spans registers 1021, 1022, 1023, 0)
    bytecode.extend(struct.pack("<HHHH", OP_IPG, 8, 30, 30))
    bytecode.extend(struct.pack("<H", 1021 * 12))

    bytecode.extend(struct.pack("<H", OP_RETURN))

    model = parse_sod_bytes(bytes(bytecode), name="IPG_WRAP")
    assert model.name == "IPG_WRAP"


def test_sod_vm_malformed_and_truncated_bytecode() -> None:
    """Stress-test parser robustness on truncated bytecode streams and malformed headers."""
    # 1. Truncated header (< 10 bytes)
    with pytest.raises(ValueError, match="too short"):
        parse_sod_bytes(b"\x0c\x00\x00\x00\x00")

    # 2. Invalid SOD magic
    with pytest.raises(ValueError, match="Invalid SOD magic"):
        parse_sod_bytes(struct.pack("<HHhHH", 0x9999, 100, 0, 0, 0))

    # 3. Truncated in the middle of OP_GETV argument
    b_trunc_op = bytearray(_make_sod_header())
    b_trunc_op.extend(struct.pack("<H", OP_GETV))
    with pytest.raises(ValueError, match="Unexpected end of data"):
        parse_sod_bytes(bytes(b_trunc_op))

    # 4. Truncated in the middle of OP_VECTORS payload
    b_trunc_vec = bytearray(_make_sod_header())
    b_trunc_vec.extend(struct.pack("<HHH", OP_VECTORS, 4, 0))
    b_trunc_vec.extend(struct.pack("<hhh", 1, 2, 3))  # only 1 vector provided instead of 4
    with pytest.raises(ValueError, match="Unexpected end of data"):
        parse_sod_bytes(bytes(b_trunc_vec))

    # 5. Unknown opcode terminates parsing gracefully
    b_unknown = bytearray(_make_sod_header())
    b_unknown.extend(struct.pack("<H", 0x7777))
    model = parse_sod_bytes(bytes(b_unknown), name="UNKNOWN_OP")
    assert model.name == "UNKNOWN_OP"

    # 6. OP_IFVIS with section length extending beyond EOF terminates gracefully
    b_ifvis = bytearray(_make_sod_header())
    b_ifvis.extend(struct.pack("<HHH", OP_IFVIS, 1, 5000))
    model_ifvis = parse_sod_bytes(bytes(b_ifvis), name="IFVIS_CLAMP")
    assert model_ifvis.name == "IFVIS_CLAMP"


def test_sod_vertex_welding_attribute_preservation() -> None:
    """Verify triangulate() welds duplicate positions while preserving distinct attributes [I1]."""
    # Poly 1: Base facet (pos: [(0,0,0), (1,0,0), (0,1,0)], normal=(0,0,1), col=10, flags=0)
    p1 = SodPolygon(
        vertices=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
        palette_index=10,
        normal=(0.0, 0.0, 1.0),
        flags=0,
    )
    # Poly 2: Duplicate of Poly 1 -> should weld 100% of vertices
    p2 = SodPolygon(
        vertices=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
        palette_index=10,
        normal=(0.0, 0.0, 1.0),
        flags=0,
    )
    # Poly 3: Same positions, but different normal (1,0,0) -> NOT welded (preserves normal attribute)
    p3 = SodPolygon(
        vertices=[(0.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)],
        palette_index=10,
        normal=(1.0, 0.0, 0.0),
        flags=0,
    )
    # Poly 4: Same positions, but different palette_index (25) -> NOT welded (preserves color attribute)
    p4 = SodPolygon(
        vertices=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
        palette_index=25,
        normal=(0.0, 0.0, 1.0),
        flags=0,
    )
    # Poly 5: Same positions, but different flags (DECAL_FLAG_BIT) -> NOT welded (preserves decal flag)
    p5 = SodPolygon(
        vertices=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
        palette_index=10,
        normal=(0.0, 0.0, 1.0),
        flags=DECAL_FLAG_BIT,
    )
    # Poly 6: Degenerate polygon (< 3 vertices) -> skipped
    p6_degen = SodPolygon(vertices=[(0.0, 0.0, 0.0)], palette_index=0, normal=(0.0, 1.0, 0.0))

    model = SodModel(
        name="WELD_TEST",
        bounding_size=10,
        ground_y_offset=0,
        flags=0,
        scale_index=0,
        scale_factor=1.0,
        polygons=[p1, p2, p3, p4, p5, p6_degen],
    )

    vertices, indices = model.triangulate()
    # 5 valid triangles * 3 indices = 15 indices
    assert len(indices) == 15
    # Poly 1 shares vertices with Poly 2, but p3, p4, p5 generate distinct vertices due to attributes
    assert len(vertices) == 12

    # Verify positions within 1e-4 tolerance are welded
    p_close1 = SodPolygon(
        vertices=[(1.00001, 0.0, 0.0), (2.0, 0.0, 0.0), (1.0, 1.0, 0.0)],
        palette_index=5,
        normal=(0.0, 0.0, 1.0),
    )
    p_close2 = SodPolygon(
        vertices=[(1.00004, 0.0, 0.0), (2.0, 0.0, 0.0), (1.0, 1.0, 0.0)],
        palette_index=5,
        normal=(0.0, 0.0, 1.0),
    )
    m_close = SodModel(
        name="CLOSE",
        bounding_size=10,
        ground_y_offset=0,
        flags=0,
        scale_index=0,
        scale_factor=1.0,
        polygons=[p_close1, p_close2],
    )
    v_close, idx_close = m_close.triangulate()
    # Position difference is 0.00003 (< 1e-4), rounds to same float -> welded into 3 unique vertices
    assert len(v_close) == 3
    assert len(idx_close) == 6


# =============================================================================
# 2. Invariant [I5] Decal Displacement Adversarial Tests
# =============================================================================


def test_coplanar_facet_parallel_vs_skewed_normals() -> None:
    """Stress-test coplanar facet normal parallel testing."""
    base = SodPolygon(
        vertices=[(0.0, 0.0, 0.0), (10.0, 0.0, 0.0), (10.0, 10.0, 0.0), (0.0, 10.0, 0.0)],
        palette_index=20,
        normal=(0.0, 0.0, 1.0),
    )

    # 1. Strictly parallel (dot = 1.0)
    decal_parallel = SodPolygon(
        vertices=[(2.0, 2.0, 0.0), (4.0, 2.0, 0.0), (4.0, 4.0, 0.0), (2.0, 4.0, 0.0)],
        palette_index=15,
        normal=(0.0, 0.0, 1.0),
    )
    assert is_coplanar_facet(decal_parallel, base)

    # 2. Skewed normal within tolerance (dot >= 1.0 - 1e-4) centered at origin
    theta_in = math.acos(1.0 - 5e-5)
    decal_skewed_in = SodPolygon(
        vertices=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0), (0.0, 1.0, 0.0)],
        palette_index=15,
        normal=(math.sin(theta_in), 0.0, math.cos(theta_in)),
    )
    assert is_coplanar_facet(decal_skewed_in, base)

    # 3. Skewed normal beyond tolerance (dot = 1.0 - 2e-4 < 1.0 - 1e-4)
    theta_out = math.acos(1.0 - 2e-4)
    decal_skewed_out = SodPolygon(
        vertices=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0), (0.0, 1.0, 0.0)],
        palette_index=15,
        normal=(math.sin(theta_out), 0.0, math.cos(theta_out)),
    )
    assert not is_coplanar_facet(decal_skewed_out, base)


def test_coplanar_facet_plane_distance_tolerance() -> None:
    """Stress-test coplanar plane constant distance evaluation."""
    base = SodPolygon(
        vertices=[(0.0, 0.0, 0.0), (10.0, 0.0, 0.0), (10.0, 10.0, 0.0), (0.0, 10.0, 0.0)],
        palette_index=20,
        normal=(0.0, 0.0, 1.0),
    )

    # Offset along normal by 5e-5 m (within 1e-4 tolerance)
    decal_near = SodPolygon(
        vertices=[(2.0, 2.0, 5e-5), (4.0, 2.0, 5e-5), (4.0, 4.0, 5e-5), (2.0, 4.0, 5e-5)],
        palette_index=15,
        normal=(0.0, 0.0, 1.0),
    )
    assert is_coplanar_facet(decal_near, base)

    # Offset along normal by 2e-4 m (exceeds 1e-4 tolerance)
    decal_far = SodPolygon(
        vertices=[(2.0, 2.0, 2e-4), (4.0, 2.0, 2e-4), (4.0, 4.0, 2e-4), (2.0, 4.0, 2e-4)],
        palette_index=15,
        normal=(0.0, 0.0, 1.0),
    )
    assert not is_coplanar_facet(decal_far, base)


def test_coplanar_facet_bounding_box_overlap_and_disjointness() -> None:
    """Verify coplanar facets with non-overlapping bounding boxes are NOT classified as decals."""
    base = SodPolygon(
        vertices=[(0.0, 0.0, 0.0), (10.0, 0.0, 0.0), (10.0, 10.0, 0.0), (0.0, 10.0, 0.0)],
        palette_index=20,
        normal=(0.0, 0.0, 1.0),
    )

    # Disjoint facet on same plane (X in [20, 25], base is [0, 10])
    decal_disjoint = SodPolygon(
        vertices=[(20.0, 2.0, 0.0), (25.0, 2.0, 0.0), (25.0, 4.0, 0.0), (20.0, 4.0, 0.0)],
        palette_index=15,
        normal=(0.0, 0.0, 1.0),
    )
    assert not is_coplanar_facet(decal_disjoint, base)

    # Boundary touching within tolerance
    decal_touching = SodPolygon(
        vertices=[(10.0, 2.0, 0.0), (15.0, 2.0, 0.0), (15.0, 4.0, 0.0), (10.0, 4.0, 0.0)],
        palette_index=15,
        normal=(0.0, 0.0, 1.0),
    )
    assert is_coplanar_facet(decal_touching, base)


def test_coplanar_facet_degenerate_zero_area_facets() -> None:
    """Verify degenerate point, line, and empty facets handle coplanarity and displacement safely."""
    base = SodPolygon(
        vertices=[(0.0, 0.0, 0.0), (10.0, 0.0, 0.0), (10.0, 10.0, 0.0), (0.0, 10.0, 0.0)],
        palette_index=20,
        normal=(0.0, 0.0, 1.0),
    )

    # Point facet (zero area)
    degen_point = SodPolygon(
        vertices=[(5.0, 5.0, 0.0), (5.0, 5.0, 0.0), (5.0, 5.0, 0.0)],
        palette_index=15,
        normal=(0.0, 0.0, 1.0),
    )
    assert is_coplanar_facet(degen_point, base)
    disp = displace_decal_polygon(degen_point)
    assert disp.is_decal
    assert abs(disp.vertices[0][2] - EPSILON_DISPLACEMENT) < 1e-6

    # Empty vertices
    degen_empty = SodPolygon(vertices=[], palette_index=0, normal=(0.0, 0.0, 1.0))
    assert not is_coplanar_facet(degen_empty, base)


def test_decal_displacement_multidirectional_surface_normals() -> None:
    """Verify displacement is strictly +0.001 m along outward surface normal across all 3D directions."""
    test_directions = [
        (1.0, 0.0, 0.0),
        (-1.0, 0.0, 0.0),
        (0.0, 1.0, 0.0),
        (0.0, -1.0, 0.0),
        (0.0, 0.0, 1.0),
        (0.0, 0.0, -1.0),
        (1.0 / math.sqrt(3.0), 1.0 / math.sqrt(3.0), 1.0 / math.sqrt(3.0)),
        (1.0 / math.sqrt(2.0), -1.0 / math.sqrt(2.0), 0.0),
    ]

    for norm in test_directions:
        poly = SodPolygon(
            vertices=[(10.0, 20.0, 30.0), (11.0, 20.0, 30.0), (10.0, 21.0, 30.0)],
            palette_index=7,
            normal=norm,
        )
        disp = displace_decal_polygon(poly, eps=0.001)
        assert disp.is_decal
        assert disp.flags & DECAL_FLAG_BIT

        for orig_v, disp_v in zip(poly.vertices, disp.vertices, strict=True):
            diff = (disp_v[0] - orig_v[0], disp_v[1] - orig_v[1], disp_v[2] - orig_v[2])
            dist = math.sqrt(diff[0] * diff[0] + diff[1] * diff[1] + diff[2] * diff[2])
            assert abs(dist - 0.001) < 1e-6

            # Direction cosine test: diff dot norm == dist
            dot = diff[0] * norm[0] + diff[1] * norm[1] + diff[2] * norm[2]
            assert abs(dot - dist) < 1e-6


def test_identify_coplanar_decals_sequential_draw_order() -> None:
    """Verify sequential draw order: earlier polygons are base, subsequent coplanar are displaced."""
    base = SodPolygon(
        vertices=[(0.0, 0.0, 0.0), (10.0, 0.0, 0.0), (10.0, 10.0, 0.0), (0.0, 10.0, 0.0)],
        palette_index=20,
        normal=(0.0, 0.0, 1.0),
    )
    decal1 = SodPolygon(
        vertices=[(1.0, 1.0, 0.0), (3.0, 1.0, 0.0), (3.0, 3.0, 0.0), (1.0, 3.0, 0.0)],
        palette_index=15,
        normal=(0.0, 0.0, 1.0),
    )
    decal2 = SodPolygon(
        vertices=[(5.0, 5.0, 0.0), (7.0, 5.0, 0.0), (7.0, 7.0, 0.0), (5.0, 7.0, 0.0)],
        palette_index=15,
        normal=(0.0, 0.0, 1.0),
    )
    separate = SodPolygon(
        vertices=[(0.0, 0.0, 5.0), (10.0, 0.0, 5.0), (10.0, 10.0, 5.0), (0.0, 10.0, 5.0)],
        palette_index=20,
        normal=(0.0, 0.0, 1.0),
    )

    result = identify_coplanar_decals([base, decal1, decal2, separate])
    assert len(result) == 4
    assert not result[0].is_decal
    assert result[1].is_decal and abs(result[1].vertices[0][2] - 0.001) < 1e-6
    assert result[2].is_decal and abs(result[2].vertices[0][2] - 0.001) < 1e-6
    assert not result[3].is_decal


# =============================================================================
# 3. Binary GLB Structure Adversarial Tests
# =============================================================================


def test_glb_container_header_and_chunk_alignment() -> None:
    """Adversarially verify 12-byte header, chunk 4-byte boundaries, and space/null padding."""
    builder = GlbBuilder(asset_generator="adversarial test harness")
    m_idx = builder.add_mesh_primitive(
        positions=[[0, 0, 0], [1, 0, 0], [0, 1, 0]],
        normals=[[0, 0, 1], [0, 0, 1], [0, 0, 1]],
        colors=[[1, 0, 0, 1], [0, 1, 0, 1], [0, 0, 1, 1]],
        indices=[0, 1, 2],
    )
    builder.add_node(name="AdversarialNode", mesh=m_idx, is_scene_root=True)
    glb_data = builder.build_glb()

    # 1. 12-byte container header
    assert len(glb_data) >= 20
    magic, version, total_len = struct.unpack_from("<4sII", glb_data, 0)
    assert magic == GLB_HEADER_MAGIC
    assert version == 2
    assert total_len == len(glb_data)
    assert total_len % 4 == 0

    # 2. Chunk 0: JSON
    c0_len, c0_type = struct.unpack_from("<II", glb_data, 12)
    assert c0_type == GLB_JSON_CHUNK_TYPE
    assert c0_len % 4 == 0
    json_bytes = glb_data[20 : 20 + c0_len]
    last_brace = json_bytes.rfind(b"}")
    pad_bytes = json_bytes[last_brace + 1 :]
    # glTF 2.0 spec requires trailing bytes of JSON chunk to be ASCII spaces (0x20)
    assert all(b == 0x20 for b in pad_bytes)

    # 3. Chunk 1: BIN
    c1_header_offset = 20 + c0_len
    c1_len, c1_type = struct.unpack_from("<II", glb_data, c1_header_offset)
    assert c1_type == GLB_BIN_CHUNK_TYPE
    assert c1_len % 4 == 0
    bin_data = glb_data[c1_header_offset + 8 : c1_header_offset + 8 + c1_len]
    assert len(bin_data) == c1_len


def test_production_intro_glb_binary_integrity() -> None:
    """Inspect production artifact build/gltf_output/INTRO.glb against glTF 2.0 binary specifications."""
    assert INTRO_GLB_PATH.exists(), f"Artifact {INTRO_GLB_PATH} not found"
    raw = INTRO_GLB_PATH.read_bytes()
    file_size = len(raw)

    # 1. Header integrity
    magic, version, total_len = struct.unpack_from("<4sII", raw, 0)
    assert magic == b"glTF"
    assert version == 2
    assert total_len == file_size
    assert file_size % 4 == 0

    # 2. Chunk 0 (JSON)
    c0_len, c0_type = struct.unpack_from("<II", raw, 12)
    assert c0_type == 0x4E4F534A
    assert c0_len % 4 == 0
    json_raw = raw[20 : 20 + c0_len].decode("utf-8")
    gltf = json.loads(json_raw)

    # 3. Chunk 1 (BIN)
    c1_offset = 20 + c0_len
    c1_len, c1_type = struct.unpack_from("<II", raw, c1_offset)
    assert c1_type == 0x004E4942
    assert c1_len % 4 == 0

    # 4. BufferViews and Accessor alignments
    buffer_views = gltf.get("bufferViews", [])
    accessors = gltf.get("accessors", [])
    component_sizes = {5120: 1, 5121: 1, 5122: 2, 5123: 2, 5125: 4, 5126: 4}
    type_counts = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}

    for i, bv in enumerate(buffer_views):
        bv_off = bv.get("byteOffset", 0)
        assert bv_off % 4 == 0, f"bufferView[{i}] byteOffset {bv_off} not 4-byte aligned"

    for i, acc in enumerate(accessors):
        bv = buffer_views[acc["bufferView"]]
        total_off = bv.get("byteOffset", 0) + acc.get("byteOffset", 0)
        c_size = component_sizes[acc["componentType"]]
        num_comps = type_counts[acc["type"]]
        assert total_off % c_size == 0, (
            f"Accessor[{i}] total offset {total_off} not aligned to component size {c_size}"
        )

        # Min/max correctness
        if "min" in acc or "max" in acc:
            assert len(acc["min"]) == num_comps
            assert len(acc["max"]) == num_comps
            for c in range(num_comps):
                assert acc["min"][c] <= acc["max"][c]


# =============================================================================
# 4. Animation Samplers Adversarial Tests
# =============================================================================


def test_animation_samplers_strictly_monotonic_timestamps() -> None:
    """Verify animation input timestamps in INTRO.glb are non-negative and strictly monotonically increasing."""
    raw = INTRO_GLB_PATH.read_bytes()
    gltf, bin_bytes = parse_glb_bytes(raw)
    animations = gltf.get("animations", [])
    assert len(animations) > 0

    for a_idx, anim in enumerate(animations):
        for s_idx, sampler in enumerate(anim.get("samplers", [])):
            in_acc = gltf["accessors"][sampler["input"]]
            assert in_acc["type"] == "SCALAR"
            assert in_acc["componentType"] == 5126  # FLOAT

            bv = gltf["bufferViews"][in_acc["bufferView"]]
            off = bv.get("byteOffset", 0) + in_acc.get("byteOffset", 0)
            count = in_acc["count"]
            assert count > 0

            timestamps = [struct.unpack_from("<f", bin_bytes, off + i * 4)[0] for i in range(count)]
            assert timestamps[0] >= 0.0, f"Animation {a_idx} Sampler {s_idx} negative start time"
            for i in range(len(timestamps) - 1):
                assert timestamps[i + 1] > timestamps[i], (
                    f"Animation {a_idx} Sampler {s_idx} not strictly increasing at index {i}"
                )


def test_animation_samplers_matching_input_output_counts() -> None:
    """Verify sampler input and output accessor counts match for LINEAR interpolation."""
    raw = INTRO_GLB_PATH.read_bytes()
    gltf, _ = parse_glb_bytes(raw)
    animations = gltf.get("animations", [])

    for anim in animations:
        for sampler in anim.get("samplers", []):
            interp = sampler.get("interpolation", "LINEAR")
            assert interp in ("LINEAR", "STEP", "CUBICSPLINE")
            in_acc = gltf["accessors"][sampler["input"]]
            out_acc = gltf["accessors"][sampler["output"]]
            if interp in ("LINEAR", "STEP"):
                assert in_acc["count"] == out_acc["count"]
            elif interp == "CUBICSPLINE":
                assert out_acc["count"] == 3 * in_acc["count"]


def test_glb_builder_animation_error_handling() -> None:
    """Stress-test GlbBuilder.add_animation() boundary assertions and validation errors."""
    builder = GlbBuilder()

    # Empty timestamps
    with pytest.raises(ValueError, match="Timestamps cannot be empty"):
        builder.add_animation("EmptyTimeline", timestamps=[])

    # Translation track length mismatch
    with pytest.raises(ValueError, match=r"Translation count .* mismatch"):
        builder.add_animation(
            "MismatchTrans",
            timestamps=[0.0, 0.05, 0.10],
            translations={0: [[0.0, 0.0, 0.0]]},  # 1 position vs 3 timestamps
        )

    # Rotation track length mismatch
    with pytest.raises(ValueError, match=r"Rotation count .* mismatch"):
        builder.add_animation(
            "MismatchRot",
            timestamps=[0.0, 0.05],
            rotations={0: [[0.0, 0.0, 0.0, 1.0], [0.0, 0.0, 0.0, 1.0], [0.0, 0.0, 0.0, 1.0]]},
        )
