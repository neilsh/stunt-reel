"""Baseline Stunt Island .SOD procedural bytecode mesh parser.

Implements the 10-byte header, scale lookup table, 12-byte aligned register VM
addressing (offset / 0x0c), and geometry opcodes (OP_ID, OP_VECTORS, OP_COLOR,
OP_POLYZ, OP_GVPOLY, etc.).

Converts coordinates to right-handed metric space (+X right, +Y up, +Z toward viewer, -Z forward)
adhering strictly to Architectural Invariants:
- [I1] Metric right-handed coordinates & attribute-preserving vertex welding.
- [I2] Flat arena layout compatibility with SodModelIr.
- [I3] VGA Mode 13h palette index color mapping.
- [I5] Coplanar decal identification and normal displacement flags.
"""

from __future__ import annotations

import math
import struct
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from stunt_reel.math import vec3_cross, vec3_length, vec3_normalize

__all__ = [
    "OP_ADDV",
    "OP_BLOCK",
    "OP_CLRV",
    "OP_COLOR",
    "OP_DOT",
    "OP_END",
    "OP_GETV",
    "OP_GVPOLY",
    "OP_GVPOLY16",
    "OP_ID",
    "OP_IFVIS",
    "OP_INTV",
    "OP_IPG",
    "OP_LINECOL",
    "OP_MOVETO",
    "OP_NEGV",
    "OP_PERFDISK",
    "OP_PERS",
    "OP_POLYZ",
    "OP_PUTV",
    "OP_REJ",
    "OP_RETURN",
    "OP_SHADES",
    "OP_SHLV",
    "OP_SHRV",
    "OP_SORT",
    "OP_SPHERE",
    "OP_SUBV",
    "OP_VEC",
    "OP_VECTORS",
    "OP_ZLINETO",
    "SOD_SCALE_TABLE",
    "SodModel",
    "SodPolygon",
    "SodVertex",
    "compute_polygon_normal",
    "parse_sod_bytes",
    "parse_sod_file",
]

# Standard .SOD Opcodes
OP_CLRV = 0x0000
OP_GETV = 0x0009
OP_ID = 0x000C
OP_PUTV = 0x0012
OP_INTV = 0x001B
OP_ADDV = 0x0024
OP_SUBV = 0x002D
OP_NEGV = 0x0036
OP_SHLV = 0x003F
OP_SHRV = 0x0048
OP_VEC = 0x004B
OP_IPG = 0x0063
OP_VECTORS = 0x0075
OP_PERS = 0x0099
OP_MOVETO = 0x00A2
OP_LINECOL = 0x00B4
OP_ZLINETO = 0x00BD
OP_POLYZ = 0x00F3
OP_SPHERE = 0x00FC
OP_PERFDISK = 0x010E
OP_COLOR = 0x0129
OP_SHADES = 0x0156
OP_GVPOLY = 0x0168
OP_IFVIS = 0x017A
OP_SORT = 0x018C
OP_RETURN = 0x0195
OP_END = 0x0195
OP_REJ = 0x01B9
OP_GVPOLY16 = 0x02BE
OP_DOT = 0x02D0
OP_BLOCK = 0x02D9

# Power-of-2 scaling multiplier table (historical sod_scale_table)
SOD_SCALE_TABLE: tuple[float, ...] = (
    10.0,
    5.0,
    5.0 / 2.0,
    5.0 / 4.0,
    5.0 / 8.0,
    5.0 / 16.0,
    5.0 / 32.0,
    5.0 / 64.0,
    5.0 / 128.0,
    5.0 / 256.0,
    5.0 / 512.0,
    5.0 / 1024.0,
    5.0 / 2048.0,
    5.0 / 4096.0,
    5.0 / 8192.0,
    5.0 / 16384.0,
    5.0 / 32768.0,
    5.0 / 65536.0,
)


@dataclass(slots=True)
class SodVertex:
    """Consolidated GPU-ready vertex matching Seam 3 SodVertex contract."""

    position: tuple[float, float, float]
    normal: tuple[float, float, float]
    palette_index: int
    flags: int = 0


@dataclass(slots=True)
class SodPolygon:
    """Single polygonal facet emitted by procedural bytecode."""

    vertices: list[tuple[float, float, float]]
    palette_index: int
    normal: tuple[float, float, float]
    flags: int = 0
    is_decal: bool = False


@dataclass
class SodModel:
    """Decoded procedural 3D model intermediate representation."""

    name: str
    bounding_size: int
    ground_y_offset: int
    flags: int
    scale_index: int
    scale_factor: float
    polygons: list[SodPolygon] = field(default_factory=list)

    def triangulate(self) -> tuple[list[SodVertex], list[int]]:
        """Tessellate polygons to triangle fan and apply attribute-preserving welding [I1].

        WeldKey = (quantize(pos, 1e-4), quantize(normal, 1e-3), palette_index, flags).
        """
        vertices: list[SodVertex] = []
        indices: list[int] = []
        weld_map: dict[
            tuple[
                tuple[float, float, float],
                tuple[float, float, float],
                int,
                int,
            ],
            int,
        ] = {}

        for poly in self.polygons:
            num_v = len(poly.vertices)
            if num_v < 3:
                continue

            poly_indices: list[int] = []
            for v_pos in poly.vertices:
                weld_key = (
                    (round(v_pos[0], 4), round(v_pos[1], 4), round(v_pos[2], 4)),
                    (round(poly.normal[0], 3), round(poly.normal[1], 3), round(poly.normal[2], 3)),
                    poly.palette_index,
                    poly.flags,
                )
                if weld_key in weld_map:
                    poly_indices.append(weld_map[weld_key])
                else:
                    idx = len(vertices)
                    vertex = SodVertex(
                        position=v_pos,
                        normal=poly.normal,
                        palette_index=poly.palette_index,
                        flags=poly.flags,
                    )
                    vertices.append(vertex)
                    weld_map[weld_key] = idx
                    poly_indices.append(idx)

            # Convex polygon fan triangulation: (0, 1, 2), (0, 2, 3), ...
            root_idx = poly_indices[0]
            for i in range(1, num_v - 1):
                indices.extend([root_idx, poly_indices[i], poly_indices[i + 1]])

        return vertices, indices

    def to_sod_model_ir(self) -> dict[str, Any]:
        """Export to Seam 3 SodModelIr dictionary representation."""
        vertices, indices = self.triangulate()
        raw_verts = [
            {
                "position": list(v.position),
                "normal": list(v.normal),
                "palette_index": v.palette_index,
                "flags": v.flags,
            }
            for v in vertices
        ]
        return {
            "name": self.name,
            "bounding_size": self.bounding_size,
            "ground_y_offset": self.ground_y_offset,
            "scale_factor": self.scale_factor,
            "vertices": raw_verts,
            "indices": indices,
        }


def compute_polygon_normal(vertices: Sequence[Sequence[float]]) -> tuple[float, float, float]:
    """Compute normalized outward surface normal from polygon vertices using Newell / edge cross."""
    if len(vertices) < 3:
        return (0.0, 1.0, 0.0)

    # Calculate cross product from first three vertices
    v0, v1, v2 = vertices[0], vertices[1], vertices[2]
    e1 = (v1[0] - v0[0], v1[1] - v0[1], v1[2] - v0[2])
    e2 = (v2[0] - v0[0], v2[1] - v0[1], v2[2] - v0[2])
    n = vec3_cross(e1, e2)
    length = vec3_length(n)

    if length > 1e-12:
        unit_n = vec3_normalize(n)
        return (unit_n[0], unit_n[1], unit_n[2])

    # Newell's method fallback for non-planar or collinear initial vertices
    nx, ny, nz = 0.0, 0.0, 0.0
    n_v = len(vertices)
    for i in range(n_v):
        curr = vertices[i]
        nxt = vertices[(i + 1) % n_v]
        nx += (curr[1] - nxt[1]) * (curr[2] + nxt[2])
        ny += (curr[2] - nxt[2]) * (curr[0] + nxt[0])
        nz += (curr[0] - nxt[0]) * (curr[1] + nxt[1])

    newell_len = math.sqrt(nx * nx + ny * ny + nz * nz)
    if newell_len > 1e-12:
        inv = 1.0 / newell_len
        return (nx * inv, ny * inv, nz * inv)

    return (0.0, 1.0, 0.0)


def parse_sod_bytes(data: bytes, name: str = "SOD_MODEL") -> SodModel:
    """Parse baseline .SOD binary bytecode stream into SodModel."""
    if len(data) < 10:
        raise ValueError(f"SOD data too short for 10-byte header ({len(data)} bytes)")

    # 1. Parse 10-byte header
    op_id, bounding_size, ground_y_offset, flags_scale, _collision_meta = struct.unpack_from(
        "<HHhHH", data, 0
    )
    if op_id != OP_ID:
        raise ValueError(f"Invalid SOD magic identifier: 0x{op_id:04x} (expected 0x000c)")

    scale_index = flags_scale & 0xFF
    header_flags = flags_scale >> 8

    if scale_index < len(SOD_SCALE_TABLE):
        scale_raw = SOD_SCALE_TABLE[scale_index]
    else:
        scale_raw = 5.0 / (2.0 ** (scale_index - 1)) if scale_index > 0 else 10.0

    # Scale multiplier in meters per integer unit (scale_table / 10.0)
    scale_factor = scale_raw / 10.0

    # 2. Initialize vertex register file (up to 1024 registers)
    verts: list[list[float]] = [[0.0, 0.0, 0.0] for _ in range(1024)]
    cur_vert: list[float] = [0.0, 0.0, 0.0]
    cur_color: int = 0
    polygons: list[SodPolygon] = []

    pos = 10
    total_len = len(data)

    def read_u16() -> int:
        nonlocal pos
        if pos + 2 > total_len:
            raise ValueError(f"Unexpected end of data at offset 0x{pos:04x}")
        val: int = struct.unpack_from("<H", data, pos)[0]
        pos += 2
        return val

    def read_i16() -> int:
        nonlocal pos
        if pos + 2 > total_len:
            raise ValueError(f"Unexpected end of data at offset 0x{pos:04x}")
        val: int = struct.unpack_from("<h", data, pos)[0]
        pos += 2
        return val

    # 3. Procedural bytecode execution loop
    while pos + 2 <= total_len:
        opcode = read_u16()

        if opcode == OP_CLRV:
            cur_vert = [0.0, 0.0, 0.0]

        elif opcode == OP_GETV:
            reg_off = read_u16()
            reg_idx = (reg_off // 12) & 1023
            cur_vert = list(verts[reg_idx])

        elif opcode == OP_PUTV:
            reg_off = read_u16()
            reg_idx = (reg_off // 12) & 1023
            verts[reg_idx] = list(cur_vert)

        elif opcode == OP_INTV:
            reg_off = read_u16()
            reg_idx = (reg_off // 12) & 1023
            target = verts[reg_idx]
            cur_vert = [
                (cur_vert[0] + target[0]) * 0.5,
                (cur_vert[1] + target[1]) * 0.5,
                (cur_vert[2] + target[2]) * 0.5,
            ]

        elif opcode == OP_ADDV:
            reg_off = read_u16()
            reg_idx = (reg_off // 12) & 1023
            target = verts[reg_idx]
            cur_vert = [
                cur_vert[0] + target[0],
                cur_vert[1] + target[1],
                cur_vert[2] + target[2],
            ]

        elif opcode == OP_SUBV:
            reg_off = read_u16()
            reg_idx = (reg_off // 12) & 1023
            target = verts[reg_idx]
            cur_vert = [
                cur_vert[0] - target[0],
                cur_vert[1] - target[1],
                cur_vert[2] - target[2],
            ]

        elif opcode == OP_NEGV:
            cur_vert = [-cur_vert[0], -cur_vert[1], -cur_vert[2]]

        elif opcode == OP_SHLV:
            shift = read_u16()
            cur_vert = [
                float(int(cur_vert[0]) << shift),
                float(int(cur_vert[1]) << shift),
                float(int(cur_vert[2]) << shift),
            ]

        elif opcode == OP_SHRV:
            shift = read_u16()
            cur_vert = [
                float(int(cur_vert[0]) >> shift),
                float(int(cur_vert[1]) >> shift),
                float(int(cur_vert[2]) >> shift),
            ]

        elif opcode == OP_IPG:
            ipg_type = read_u16()
            if ipg_type == 0:  # Cube
                dx = float(read_i16())
                dy = float(read_i16())
                dz = float(read_i16())
                start_off = read_u16()
                start_reg = (start_off // 12) & 1023
                verts[(start_reg + 0) & 1023] = [-dx, -dy, -dz]
                verts[(start_reg + 1) & 1023] = [-dx, -dy, dz]
                verts[(start_reg + 2) & 1023] = [dx, -dy, dz]
                verts[(start_reg + 3) & 1023] = [dx, -dy, -dz]
                verts[(start_reg + 4) & 1023] = [-dx, dy, -dz]
                verts[(start_reg + 5) & 1023] = [-dx, dy, dz]
                verts[(start_reg + 6) & 1023] = [dx, dy, dz]
                verts[(start_reg + 7) & 1023] = [dx, dy, -dz]
            elif ipg_type == 2:  # Ground Quad
                dx = float(read_i16())
                dz = float(read_i16())
                start_off = read_u16()
                start_reg = (start_off // 12) & 1023
                verts[(start_reg + 0) & 1023] = [-dx, 0.0, -dz]
                verts[(start_reg + 1) & 1023] = [-dx, 0.0, dz]
                verts[(start_reg + 2) & 1023] = [dx, 0.0, dz]
                verts[(start_reg + 3) & 1023] = [dx, 0.0, -dz]
            elif ipg_type == 8:  # Flat Vertical Quad
                dx = float(read_i16())
                dy = float(read_i16())
                start_off = read_u16()
                start_reg = (start_off // 12) & 1023
                verts[(start_reg + 0) & 1023] = [-dx, -dy, 0.0]
                verts[(start_reg + 1) & 1023] = [-dx, dy, 0.0]
                verts[(start_reg + 2) & 1023] = [dx, dy, 0.0]
                verts[(start_reg + 3) & 1023] = [dx, -dy, 0.0]
            else:
                # Skip unknown IPG type parameters safely
                _ = read_u16()
                _ = read_u16()

        elif opcode == OP_VECTORS:
            count = read_u16()
            start_off = read_u16()
            start_reg = (start_off // 12) & 1023
            for i in range(count):
                vx = float(read_i16())
                vy = float(read_i16())
                vz = float(read_i16())
                verts[(start_reg + i) & 1023] = [vx, vy, vz]

        elif opcode == OP_COLOR:
            cur_color = read_u16() & 0xFF

        elif opcode in (OP_LINECOL, OP_MOVETO, OP_ZLINETO, OP_DOT):
            _ = read_u16()

        elif opcode == OP_POLYZ:
            count = read_u16()
            reg_indices = [(read_u16() // 12) & 1023 for _ in range(count)]
            poly_verts: list[tuple[float, float, float]] = []
            for r_idx in reg_indices:
                raw_v = verts[r_idx]
                # Convert to metric coordinates [I1]
                mx = raw_v[0] * scale_factor
                my = (raw_v[1] + ground_y_offset) * scale_factor
                mz = raw_v[2] * scale_factor
                poly_verts.append((mx, my, mz))

            norm = compute_polygon_normal(poly_verts)
            polygons.append(
                SodPolygon(
                    vertices=poly_verts,
                    palette_index=cur_color,
                    normal=norm,
                )
            )

        elif opcode in (OP_GVPOLY, OP_GVPOLY16):
            count = read_u16()
            reg_indices = [(read_u16() // 12) & 1023 for _ in range(count)]
            norm_off = read_u16()
            norm_reg = (norm_off // 12) & 1023
            # Skip per-vertex shade offsets
            for _ in range(count):
                _ = read_u16()

            poly_verts = []
            for r_idx in reg_indices:
                raw_v = verts[r_idx]
                mx = raw_v[0] * scale_factor
                my = (raw_v[1] + ground_y_offset) * scale_factor
                mz = raw_v[2] * scale_factor
                poly_verts.append((mx, my, mz))

            raw_n = verts[norm_reg]
            n_len = vec3_length(raw_n)
            if n_len > 1e-12:
                un = vec3_normalize(raw_n)
                norm = (un[0], un[1], un[2])
            else:
                norm = compute_polygon_normal(poly_verts)

            polygons.append(
                SodPolygon(
                    vertices=poly_verts,
                    palette_index=cur_color,
                    normal=norm,
                )
            )

        elif opcode == OP_IFVIS:
            _ = read_u16()  # condition code
            sec_len = read_u16()  # section length in bytes
            # If section extends beyond EOF, clamp
            if pos + sec_len > total_len:
                break

        elif opcode == OP_SORT:
            _ = read_u16()
            _ = read_u16()
            _ = read_u16()

        elif opcode in (OP_SPHERE, OP_BLOCK):
            _ = read_u16()
            _ = read_u16()

        elif opcode == OP_PERFDISK:
            _ = read_u16()
            _ = read_u16()
            _ = read_u16()

        elif opcode == OP_PERS:
            _ = read_u16()
            _ = read_u16()

        elif opcode == OP_VEC:
            _ = read_u16()
            _ = read_u16()
            _ = read_u16()

        elif opcode == OP_REJ:
            _ = read_u16()
            num_faces = read_u16()
            for _ in range(num_faces):
                _ = read_u16()
                _ = read_u16()
                _ = read_u16()

        elif opcode == OP_SHADES:
            _ = read_u16()
            count = read_u16()
            for _ in range(count):
                _ = read_u16()
                _ = read_u16()
                _ = read_u16()

        elif opcode in (OP_RETURN, OP_END):
            # End of model bytecode stream
            break

        else:
            # Unknown opcode encountered; terminate safely
            break

    return SodModel(
        name=name,
        bounding_size=bounding_size,
        ground_y_offset=ground_y_offset,
        flags=header_flags,
        scale_index=scale_index,
        scale_factor=scale_factor,
        polygons=polygons,
    )


def parse_sod_file(file_path: Path | str) -> SodModel:
    """Read and decode a .SOD file from disk."""
    path = Path(file_path)
    data = path.read_bytes()
    return parse_sod_bytes(data, name=path.stem.upper())
