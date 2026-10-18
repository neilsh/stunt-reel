"""Pure standard library binary glTF 2.0 (.glb) container builder and parser.

Adheres strictly to the official Khronos glTF 2.0 binary specification:
- 12-byte container header (glTF version 2).
- 4-byte aligned JSON chunk (padded with 0x20 ASCII spaces).
- 4-byte aligned BIN chunk (padded with 0x00 null bytes).
- 4-byte aligned bufferViews and typed accessors with min/max bounds.
"""

from __future__ import annotations

import json
import struct
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "COMPONENT_FLOAT",
    "COMPONENT_UNSIGNED_BYTE",
    "COMPONENT_UNSIGNED_INT",
    "COMPONENT_UNSIGNED_SHORT",
    "GLB_BIN_CHUNK_TYPE",
    "GLB_HEADER_MAGIC",
    "GLB_JSON_CHUNK_TYPE",
    "TARGET_ARRAY_BUFFER",
    "TARGET_ELEMENT_ARRAY_BUFFER",
    "TYPE_MAT4",
    "TYPE_SCALAR",
    "TYPE_VEC2",
    "TYPE_VEC3",
    "TYPE_VEC4",
    "GlbBuilder",
    "parse_glb_bytes",
]

# glTF 2.0 Binary Constants
GLB_HEADER_MAGIC: bytes = b"glTF"
GLB_JSON_CHUNK_TYPE: int = 0x4E4F534A  # ASCII "JSON"
GLB_BIN_CHUNK_TYPE: int = 0x004E4942  # ASCII "BIN\0"

# Component Types
COMPONENT_UNSIGNED_BYTE: int = 5121
COMPONENT_UNSIGNED_SHORT: int = 5123
COMPONENT_UNSIGNED_INT: int = 5125
COMPONENT_FLOAT: int = 5126

# BufferView Targets
TARGET_ARRAY_BUFFER: int = 34962
TARGET_ELEMENT_ARRAY_BUFFER: int = 34963

# Accessor Types
TYPE_SCALAR: str = "SCALAR"
TYPE_VEC2: str = "VEC2"
TYPE_VEC3: str = "VEC3"
TYPE_VEC4: str = "VEC4"
TYPE_MAT4: str = "MAT4"


@dataclass
class GlbBuilder:
    """Zero-dependency glTF 2.0 binary (.glb) scene builder."""

    asset_generator: str = "stunt-reel gltf exporter"
    _bin_data: bytearray = field(default_factory=bytearray)
    _buffer_views: list[dict[str, Any]] = field(default_factory=list)
    _accessors: list[dict[str, Any]] = field(default_factory=list)
    _meshes: list[dict[str, Any]] = field(default_factory=list)
    _materials: list[dict[str, Any]] = field(default_factory=list)
    _cameras: list[dict[str, Any]] = field(default_factory=list)
    _nodes: list[dict[str, Any]] = field(default_factory=list)
    _animations: list[dict[str, Any]] = field(default_factory=list)
    _scene_nodes: list[int] = field(default_factory=list)
    _extensions_used: set[str] = field(default_factory=set)

    def __post_init__(self) -> None:
        """Initialize default unlit material."""
        self._materials.append(
            {
                "name": "StuntReel_Mode13h_Unlit",
                "pbrMetallicRoughness": {
                    "metallicFactor": 0.0,
                    "roughnessFactor": 1.0,
                },
                "extensions": {"KHR_materials_unlit": {}},
            }
        )
        self._extensions_used.add("KHR_materials_unlit")

    def add_buffer_data(self, data: bytes, target: int | None = None) -> int:
        """Append raw byte payload to the binary buffer and return its bufferView index.

        Automatically aligns the byte offset to a 4-byte boundary.
        """
        # Align existing buffer to 4-byte boundary
        pad_len = (4 - (len(self._bin_data) % 4)) % 4
        if pad_len > 0:
            self._bin_data.extend(b"\x00" * pad_len)

        byte_offset = len(self._bin_data)
        self._bin_data.extend(data)
        byte_length = len(data)

        view_idx = len(self._buffer_views)
        view_entry: dict[str, Any] = {
            "buffer": 0,
            "byteOffset": byte_offset,
            "byteLength": byte_length,
        }
        if target is not None:
            view_entry["target"] = target

        self._buffer_views.append(view_entry)
        return view_idx

    def add_accessor(
        self,
        buffer_view_idx: int,
        component_type: int,
        count: int,
        type_str: str,
        min_vals: Sequence[float] | None = None,
        max_vals: Sequence[float] | None = None,
        byte_offset: int = 0,
    ) -> int:
        """Create a glTF accessor referencing a bufferView and return its index."""
        acc_idx = len(self._accessors)
        acc_entry: dict[str, Any] = {
            "bufferView": buffer_view_idx,
            "byteOffset": byte_offset,
            "componentType": component_type,
            "count": count,
            "type": type_str,
        }
        if min_vals is not None:
            acc_entry["min"] = [float(v) for v in min_vals]
        if max_vals is not None:
            acc_entry["max"] = [float(v) for v in max_vals]

        self._accessors.append(acc_entry)
        return acc_idx

    def add_mesh_primitive(
        self,
        positions: Sequence[Sequence[float]],
        normals: Sequence[Sequence[float]],
        colors: Sequence[Sequence[float]],
        indices: Sequence[int],
        name: str = "Mesh",
    ) -> int:
        """Add geometry arrays, pack into binary buffer, and create a single-primitive mesh."""
        if not positions:
            raise ValueError("Positions cannot be empty")

        # 1. Pack Position (3 x float32 = 12 bytes per vertex)
        pos_bytes = bytearray()
        min_pos = [float("inf"), float("inf"), float("inf")]
        max_pos = [float("-inf"), float("-inf"), float("-inf")]
        for p in positions:
            pos_bytes.extend(struct.pack("<3f", p[0], p[1], p[2]))
            min_pos[0] = min(min_pos[0], p[0])
            min_pos[1] = min(min_pos[1], p[1])
            min_pos[2] = min(min_pos[2], p[2])
            max_pos[0] = max(max_pos[0], p[0])
            max_pos[1] = max(max_pos[1], p[1])
            max_pos[2] = max(max_pos[2], p[2])

        pos_view = self.add_buffer_data(bytes(pos_bytes), target=TARGET_ARRAY_BUFFER)
        pos_acc = self.add_accessor(
            pos_view,
            COMPONENT_FLOAT,
            len(positions),
            TYPE_VEC3,
            min_vals=min_pos,
            max_vals=max_pos,
        )

        # 2. Pack Normal (3 x float32 = 12 bytes per vertex)
        norm_bytes = bytearray()
        for n in normals:
            norm_bytes.extend(struct.pack("<3f", n[0], n[1], n[2]))
        norm_view = self.add_buffer_data(bytes(norm_bytes), target=TARGET_ARRAY_BUFFER)
        norm_acc = self.add_accessor(norm_view, COMPONENT_FLOAT, len(normals), TYPE_VEC3)

        # 3. Pack Color (4 x float32 = 16 bytes per vertex)
        col_bytes = bytearray()
        for c in colors:
            col_bytes.extend(struct.pack("<4f", c[0], c[1], c[2], c[3]))
        col_view = self.add_buffer_data(bytes(col_bytes), target=TARGET_ARRAY_BUFFER)
        col_acc = self.add_accessor(col_view, COMPONENT_FLOAT, len(colors), TYPE_VEC4)

        # 4. Pack Indices (uint32)
        idx_bytes = bytearray()
        for i in indices:
            idx_bytes.extend(struct.pack("<I", i))
        idx_view = self.add_buffer_data(bytes(idx_bytes), target=TARGET_ELEMENT_ARRAY_BUFFER)
        idx_acc = self.add_accessor(idx_view, COMPONENT_UNSIGNED_INT, len(indices), TYPE_SCALAR)

        mesh_idx = len(self._meshes)
        self._meshes.append(
            {
                "name": name,
                "primitives": [
                    {
                        "attributes": {
                            "POSITION": pos_acc,
                            "NORMAL": norm_acc,
                            "COLOR_0": col_acc,
                        },
                        "indices": idx_acc,
                        "material": 0,  # references default unlit material
                    }
                ],
            }
        )
        return mesh_idx

    def add_camera(
        self,
        yfov_radians: float,
        znear: float = 0.1,
        zfar: float = 10000.0,
        aspect_ratio: float = 4.0 / 3.0,
        name: str = "Camera",
    ) -> int:
        """Add a perspective camera and return its camera index."""
        cam_idx = len(self._cameras)
        self._cameras.append(
            {
                "name": name,
                "type": "perspective",
                "perspective": {
                    "yfov": yfov_radians,
                    "znear": znear,
                    "zfar": zfar,
                    "aspectRatio": aspect_ratio,
                },
            }
        )
        return cam_idx

    def add_node(
        self,
        name: str = "Node",
        mesh: int | None = None,
        camera: int | None = None,
        translation: Sequence[float] | None = None,
        rotation: Sequence[float] | None = None,
        children: Sequence[int] | None = None,
        is_scene_root: bool = False,
    ) -> int:
        """Add a scene node and optionally register it under the root scene."""
        node_idx = len(self._nodes)
        node_entry: dict[str, Any] = {"name": name}
        if mesh is not None:
            node_entry["mesh"] = mesh
        if camera is not None:
            node_entry["camera"] = camera
        if translation is not None:
            node_entry["translation"] = [float(v) for v in translation]
        if rotation is not None:
            node_entry["rotation"] = [float(v) for v in rotation]
        if children is not None:
            node_entry["children"] = list(children)

        self._nodes.append(node_entry)
        if is_scene_root:
            self._scene_nodes.append(node_idx)
        return node_idx

    def add_animation(
        self,
        name: str,
        timestamps: Sequence[float],
        translations: dict[int, Sequence[Sequence[float]]] | None = None,
        rotations: dict[int, Sequence[Sequence[float]]] | None = None,
    ) -> int:
        """Pack animation timeline samplers and channels for nodes."""
        if not timestamps:
            raise ValueError("Timestamps cannot be empty")

        # 1. Pack timestamp input accessor (SCALAR float32)
        time_bytes = bytearray()
        min_time = min(timestamps)
        max_time = max(timestamps)
        for t in timestamps:
            time_bytes.extend(struct.pack("<f", t))

        time_view = self.add_buffer_data(bytes(time_bytes))
        time_acc = self.add_accessor(
            time_view,
            COMPONENT_FLOAT,
            len(timestamps),
            TYPE_SCALAR,
            min_vals=[min_time],
            max_vals=[max_time],
        )

        channels: list[dict[str, Any]] = []
        samplers: list[dict[str, Any]] = []

        # 2. Pack translation channels
        if translations:
            for node_idx, pos_track in translations.items():
                if len(pos_track) != len(timestamps):
                    raise ValueError(
                        f"Translation count ({len(pos_track)}) mismatch with timestamps ({len(timestamps)})"
                    )
                track_bytes = bytearray()
                for p in pos_track:
                    track_bytes.extend(struct.pack("<3f", p[0], p[1], p[2]))
                track_view = self.add_buffer_data(bytes(track_bytes))
                track_acc = self.add_accessor(
                    track_view, COMPONENT_FLOAT, len(pos_track), TYPE_VEC3
                )

                sampler_idx = len(samplers)
                samplers.append(
                    {
                        "input": time_acc,
                        "output": track_acc,
                        "interpolation": "LINEAR",
                    }
                )
                channels.append(
                    {
                        "sampler": sampler_idx,
                        "target": {
                            "node": node_idx,
                            "path": "translation",
                        },
                    }
                )

        # 3. Pack rotation channels
        if rotations:
            for node_idx, rot_track in rotations.items():
                if len(rot_track) != len(timestamps):
                    raise ValueError(
                        f"Rotation count ({len(rot_track)}) mismatch with timestamps ({len(timestamps)})"
                    )
                track_bytes = bytearray()
                for q in rot_track:
                    track_bytes.extend(struct.pack("<4f", q[0], q[1], q[2], q[3]))
                track_view = self.add_buffer_data(bytes(track_bytes))
                track_acc = self.add_accessor(
                    track_view, COMPONENT_FLOAT, len(rot_track), TYPE_VEC4
                )

                sampler_idx = len(samplers)
                samplers.append(
                    {
                        "input": time_acc,
                        "output": track_acc,
                        "interpolation": "LINEAR",
                    }
                )
                channels.append(
                    {
                        "sampler": sampler_idx,
                        "target": {
                            "node": node_idx,
                            "path": "rotation",
                        },
                    }
                )

        anim_idx = len(self._animations)
        self._animations.append(
            {
                "name": name,
                "samplers": samplers,
                "channels": channels,
            }
        )
        return anim_idx

    def build_glb(self) -> bytes:
        """Serialize complete scene into a valid binary glTF 2.0 container."""
        # 1. Pad binary data chunk to 4-byte alignment
        bin_payload = bytearray(self._bin_data)
        bin_pad = (4 - (len(bin_payload) % 4)) % 4
        if bin_pad > 0:
            bin_payload.extend(b"\x00" * bin_pad)

        # 2. Assemble glTF JSON structure
        gltf_dict: dict[str, Any] = {
            "asset": {
                "generator": self.asset_generator,
                "version": "2.0",
            },
            "scene": 0,
            "scenes": [
                {
                    "name": "DefaultScene",
                    "nodes": list(self._scene_nodes),
                }
            ],
            "nodes": self._nodes,
            "buffers": [{"byteLength": len(bin_payload)}],
            "bufferViews": self._buffer_views,
            "accessors": self._accessors,
        }

        if self._meshes:
            gltf_dict["meshes"] = self._meshes
        if self._materials:
            gltf_dict["materials"] = self._materials
        if self._cameras:
            gltf_dict["cameras"] = self._cameras
        if self._animations:
            gltf_dict["animations"] = self._animations
        if self._extensions_used:
            gltf_dict["extensionsUsed"] = sorted(self._extensions_used)

        json_bytes = json.dumps(gltf_dict, separators=(",", ":")).encode("utf-8")
        # Pad JSON to 4-byte boundary using ASCII spaces (0x20)
        json_pad = (4 - (len(json_bytes) % 4)) % 4
        if json_pad > 0:
            json_bytes += b" " * json_pad

        # 3. Calculate total GLB size
        # Header: 12 bytes
        # Chunk 0 Header: 8 bytes + len(json_bytes)
        # Chunk 1 Header: 8 bytes + len(bin_payload)
        total_glb_len = 12 + 8 + len(json_bytes) + 8 + len(bin_payload)

        # 4. Pack 12-byte GLB container header
        glb = bytearray()
        glb.extend(struct.pack("<4sII", GLB_HEADER_MAGIC, 2, total_glb_len))

        # 5. Pack Chunk 0 (JSON)
        glb.extend(struct.pack("<II", len(json_bytes), GLB_JSON_CHUNK_TYPE))
        glb.extend(json_bytes)

        # 6. Pack Chunk 1 (BIN)
        glb.extend(struct.pack("<II", len(bin_payload), GLB_BIN_CHUNK_TYPE))
        glb.extend(bin_payload)

        return bytes(glb)


def parse_glb_bytes(data: bytes) -> tuple[dict[str, Any], bytes]:
    """Parse and validate binary glTF 2.0 container, returning (json_dict, bin_bytes)."""
    if len(data) < 20:
        raise ValueError("Data too short for GLB container")

    magic, version, total_len = struct.unpack_from("<4sII", data, 0)
    if magic != GLB_HEADER_MAGIC:
        raise ValueError(f"Invalid GLB magic: {magic!r} (expected b'glTF')")
    if version != 2:
        raise ValueError(f"Unsupported glTF version: {version} (expected 2)")
    if total_len != len(data):
        raise ValueError(f"GLB length mismatch: declared {total_len}, got {len(data)}")

    # Chunk 0: JSON
    c0_len, c0_type = struct.unpack_from("<II", data, 12)
    if c0_type != GLB_JSON_CHUNK_TYPE:
        raise ValueError(
            f"Expected JSON chunk 0 (0x{GLB_JSON_CHUNK_TYPE:08X}), got 0x{c0_type:08X}"
        )

    json_end = 20 + c0_len
    if json_end > len(data):
        raise ValueError("JSON chunk extends beyond file length")
    raw_json = data[20:json_end].decode("utf-8").strip()
    json_dict = json.loads(raw_json)

    # Chunk 1: BIN
    bin_data = b""
    if json_end + 8 <= len(data):
        c1_len, c1_type = struct.unpack_from("<II", data, json_end)
        if c1_type != GLB_BIN_CHUNK_TYPE:
            raise ValueError(
                f"Expected BIN chunk 1 (0x{GLB_BIN_CHUNK_TYPE:08X}), got 0x{c1_type:08X}"
            )
        bin_start = json_end + 8
        bin_end = bin_start + c1_len
        if bin_end > len(data):
            raise ValueError("BIN chunk extends beyond file length")
        bin_data = data[bin_start:bin_end]

    return json_dict, bin_data
