"""High-level glTF 2.0 animated scene exporter for Stunt Reel.

Combines baseline .SOD polygonal geometries with 600-tick flight choreography
trajectories into valid, self-contained binary glTF 2.0 (.glb) scenes.

Adheres strictly to Architectural Invariants:
- [I1] Metric right-handed coordinates (+X right, +Y up, +Z toward viewer, -Z forward).
- [I3] Authentic Mode 13h 256-color palette index mapping.
- [I5] Coplanar decal normal displacement (eps = 0.001 m).
"""

from __future__ import annotations

import json
import math
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from stunt_reel.gltf.decal import apply_decal_displacement_to_model
from stunt_reel.gltf.glb import GlbBuilder
from stunt_reel.gltf.palette import get_palette_color_0
from stunt_reel.gltf.sod import SodModel, SodPolygon
from stunt_reel.math import (
    quat_from_direction_cosines,
    quat_normalize,
    vec3_cross,
    vec3_length,
    vec3_normalize,
)

__all__ = [
    "build_baseline_aircraft_sod",
    "build_runway_sod",
    "compute_camera_quaternion",
    "export_intro_glb",
    "export_trajectory_to_glb",
]


def compute_camera_quaternion(
    eye: Sequence[float],
    target: Sequence[float],
    roll_radians: float = 0.0,
) -> list[float]:
    """Compute camera orientation quaternion looking from eye to target.

    In glTF 2.0 convention:
    - Camera default view direction is along -Z.
    - Camera up vector is +Y.
    - Camera right vector is +X.
    """
    # Forward vector toward target
    fwd_x = target[0] - eye[0]
    fwd_y = target[1] - eye[1]
    fwd_z = target[2] - eye[2]
    fwd_len = math.sqrt(fwd_x * fwd_x + fwd_y * fwd_y + fwd_z * fwd_z)

    if fwd_len < 1e-6:
        # Default camera facing -Z
        return [0.0, 0.0, 0.0, 1.0]

    inv_len = 1.0 / fwd_len
    fwd = (fwd_x * inv_len, fwd_y * inv_len, fwd_z * inv_len)

    # In glTF, camera looks down -Z, so local camera Z axis points opposite to view direction
    cam_z = (-fwd[0], -fwd[1], -fwd[2])

    # World up reference
    up_ref = (0.0, 1.0, 0.0)
    # Check if forward is collinear with world up
    if abs(vec3_cross(fwd, up_ref)[1]) < 1e-6 and abs(fwd[1]) > 0.999:
        up_ref = (0.0, 0.0, 1.0)

    # Right vector = normalize(up_ref x cam_z)
    raw_right = vec3_cross(up_ref, cam_z)
    right_len = vec3_length(raw_right)
    cam_x: list[float] = [1.0, 0.0, 0.0] if right_len < 1e-6 else vec3_normalize(raw_right)

    # Orthogonal up vector = cam_z x right
    cam_y: list[float] = vec3_cross(cam_z, cam_x)

    # Apply camera roll around view axis if non-zero
    if abs(roll_radians) > 1e-6:
        cos_r = math.cos(roll_radians)
        sin_r = math.sin(roll_radians)
        rolled_x = [
            cam_x[0] * cos_r + cam_y[0] * sin_r,
            cam_x[1] * cos_r + cam_y[1] * sin_r,
            cam_x[2] * cos_r + cam_y[2] * sin_r,
        ]
        rolled_y = [
            -cam_x[0] * sin_r + cam_y[0] * cos_r,
            -cam_x[1] * sin_r + cam_y[1] * cos_r,
            -cam_x[2] * sin_r + cam_y[2] * cos_r,
        ]
        cam_x = rolled_x
        cam_y = rolled_y

    # Rotation matrix columns are [cam_x, cam_y, cam_z]
    # Row-major matrix representation for quat_from_direction_cosines:
    rot_matrix = [
        [cam_x[0], cam_y[0], cam_z[0]],
        [cam_x[1], cam_y[1], cam_z[1]],
        [cam_x[2], cam_y[2], cam_z[2]],
    ]

    quat = quat_from_direction_cosines(rot_matrix)
    return quat_normalize(quat)


def build_baseline_aircraft_sod(name: str = "FOKKER") -> SodModel:
    """Construct an authentic baseline Fokker biplane 3D model with coplanar decals."""
    polygons: list[SodPolygon] = []

    # 1. Fuselage Body (Box centered along Z axis, length 4m, width 0.8m, height 0.8m)
    # Fuselage Color: Olive Drab / Brown (Mode 13h color 70)
    col_fuse = 70
    x0, x1 = -0.4, 0.4
    y0, y1 = -0.4, 0.4
    z0, z1 = -2.0, 2.0

    # Top Face (+Y)
    polygons.append(
        SodPolygon(
            vertices=[(x0, y1, z0), (x1, y1, z0), (x1, y1, z1), (x0, y1, z1)],
            palette_index=col_fuse,
            normal=(0.0, 1.0, 0.0),
        )
    )
    # Bottom Face (-Y)
    polygons.append(
        SodPolygon(
            vertices=[(x0, y0, z1), (x1, y0, z1), (x1, y0, z0), (x0, y0, z0)],
            palette_index=col_fuse,
            normal=(0.0, -1.0, 0.0),
        )
    )
    # Left Face (-X)
    polygons.append(
        SodPolygon(
            vertices=[(x0, y0, z0), (x0, y1, z0), (x0, y1, z1), (x0, y0, z1)],
            palette_index=col_fuse,
            normal=(-1.0, 0.0, 0.0),
        )
    )
    # Right Face (+X)
    polygons.append(
        SodPolygon(
            vertices=[(x1, y0, z1), (x1, y1, z1), (x1, y1, z0), (x1, y0, z0)],
            palette_index=col_fuse,
            normal=(1.0, 0.0, 0.0),
        )
    )
    # Nose Front Face (-Z)
    polygons.append(
        SodPolygon(
            vertices=[(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0)],
            palette_index=col_fuse,
            normal=(0.0, 0.0, -1.0),
        )
    )
    # Tail Rear Face (+Z)
    polygons.append(
        SodPolygon(
            vertices=[(x0, y1, z1), (x1, y1, z1), (x1, y0, z1), (x0, y0, z1)],
            palette_index=col_fuse,
            normal=(0.0, 0.0, 1.0),
        )
    )

    # 2. Upper Biplane Wing (Span 7.0m, chord 1.2m, elevation Y = +0.7m)
    # Wing Color: Khaki / Green (Mode 13h color 120)
    col_wing = 120
    wx0, wx1 = -3.5, 3.5
    wz0, wz1 = -0.8, 0.4
    wy = 0.7

    # Upper Wing Top Face (+Y)
    polygons.append(
        SodPolygon(
            vertices=[(wx0, wy, wz0), (wx1, wy, wz0), (wx1, wy, wz1), (wx0, wy, wz1)],
            palette_index=col_wing,
            normal=(0.0, 1.0, 0.0),
        )
    )
    # Upper Wing Bottom Face (-Y)
    polygons.append(
        SodPolygon(
            vertices=[(wx0, wy, wz1), (wx1, wy, wz1), (wx1, wy, wz0), (wx0, wy, wz0)],
            palette_index=col_wing,
            normal=(0.0, -1.0, 0.0),
        )
    )

    # 3. Coplanar Decal Insignias on Upper Wing (Invariant [I5])
    # Left Roundel / Cross Decal (White background color 15, black cross color 0)
    polygons.append(
        SodPolygon(
            vertices=[(-2.5, wy, -0.4), (-1.5, wy, -0.4), (-1.5, wy, 0.0), (-2.5, wy, 0.0)],
            palette_index=15,  # White
            normal=(0.0, 1.0, 0.0),
        )
    )
    # Right Roundel / Cross Decal
    polygons.append(
        SodPolygon(
            vertices=[(1.5, wy, -0.4), (2.5, wy, -0.4), (2.5, wy, 0.0), (1.5, wy, 0.0)],
            palette_index=15,  # White
            normal=(0.0, 1.0, 0.0),
        )
    )

    # 4. Lower Biplane Wing (Span 6.0m, chord 1.0m, elevation Y = -0.1m)
    lwx0, lwx1 = -3.0, 3.0
    lwz0, lwz1 = -0.6, 0.4
    lwy = -0.1

    # Lower Wing Top Face (+Y)
    polygons.append(
        SodPolygon(
            vertices=[(lwx0, lwy, lwz0), (lwx1, lwy, lwz0), (lwx1, lwy, lwz1), (lwx0, lwy, lwz1)],
            palette_index=col_wing,
            normal=(0.0, 1.0, 0.0),
        )
    )
    # Lower Wing Bottom Face (-Y)
    polygons.append(
        SodPolygon(
            vertices=[(lwx0, lwy, lwz1), (lwx1, lwy, lwz1), (lwx1, lwy, lwz0), (lwx0, lwy, lwz0)],
            palette_index=col_wing,
            normal=(0.0, -1.0, 0.0),
        )
    )

    # 5. Tail Stabilizers
    # Horizontal Tail Wing (Z = 1.6 to 2.2, span 2.4m, Y = 0.3)
    polygons.append(
        SodPolygon(
            vertices=[(-1.2, 0.3, 1.6), (1.2, 0.3, 1.6), (1.2, 0.3, 2.2), (-1.2, 0.3, 2.2)],
            palette_index=col_wing,
            normal=(0.0, 1.0, 0.0),
        )
    )
    # Vertical Rudder (X = 0, Y = 0.4 to 1.2, Z = 1.6 to 2.2)
    col_rudder = 31  # White/Cream
    polygons.append(
        SodPolygon(
            vertices=[(0.0, 0.4, 1.6), (0.0, 1.2, 1.8), (0.0, 1.2, 2.2), (0.0, 0.4, 2.2)],
            palette_index=col_rudder,
            normal=(1.0, 0.0, 0.0),
        )
    )

    # 6. Propeller Disc (Front Z = -2.05, radius 0.9m)
    col_prop = 90  # Dark Wood Brown
    polygons.append(
        SodPolygon(
            vertices=[
                (-0.1, -0.9, -2.05),
                (0.1, -0.9, -2.05),
                (0.1, 0.9, -2.05),
                (-0.1, 0.9, -2.05),
            ],
            palette_index=col_prop,
            normal=(0.0, 0.0, -1.0),
        )
    )

    raw_model = SodModel(
        name=name,
        bounding_size=100,
        ground_y_offset=0,
        flags=0,
        scale_index=0,
        scale_factor=1.0,
        polygons=polygons,
    )

    # Apply Invariant [I5] decal identification and displacement
    return apply_decal_displacement_to_model(raw_model)


def build_runway_sod(name: str = "RUNWAY") -> SodModel:
    """Construct a static runway prop with coplanar centerline stripe decals [I5]."""
    polygons: list[SodPolygon] = []

    # 1. Main Asphalt Surface (Width 20m, Length 400m, Y = 0.0m)
    # Asphalt Color: Mode 13h color 24 (Dark Charcoal)
    polygons.append(
        SodPolygon(
            vertices=[
                (-10.0, 0.0, -200.0),
                (10.0, 0.0, -200.0),
                (10.0, 0.0, 200.0),
                (-10.0, 0.0, 200.0),
            ],
            palette_index=24,
            normal=(0.0, 1.0, 0.0),
        )
    )

    # 2. Coplanar Centerline Stripes (White color 15) at Y = 0.0m
    for z_start in range(-180, 180, 20):
        z_end = z_start + 10
        polygons.append(
            SodPolygon(
                vertices=[
                    (-0.3, 0.0, float(z_start)),
                    (0.3, 0.0, float(z_start)),
                    (0.3, 0.0, float(z_end)),
                    (-0.3, 0.0, float(z_end)),
                ],
                palette_index=15,  # White
                normal=(0.0, 1.0, 0.0),
            )
        )

    raw_model = SodModel(
        name=name,
        bounding_size=500,
        ground_y_offset=0,
        flags=0,
        scale_index=0,
        scale_factor=1.0,
        polygons=polygons,
    )
    return apply_decal_displacement_to_model(raw_model)


def export_trajectory_to_glb(
    trajectory_path: Path | str,
    output_path: Path | str,
    sod_models: dict[str, SodModel] | None = None,
    tick_rate: float = 20.0,
) -> Path:
    """Export 600-tick flight trajectory and SOD geometries to an animated glTF 2.0 .glb container."""
    traj_p = Path(trajectory_path)
    out_p = Path(output_path)
    out_p.parent.mkdir(parents=True, exist_ok=True)

    with traj_p.open("r", encoding="utf-8") as f:
        records: list[dict[str, Any]] = json.load(f)

    if not records:
        raise ValueError("Trajectory records cannot be empty")

    num_ticks = len(records)
    delta_t = 1.0 / tick_rate
    timestamps = [i * delta_t for i in range(num_ticks)]

    builder = GlbBuilder(asset_generator="stunt-reel Milestone 1 glTF Exporter")

    # 1. Prepare Models (FOKKER, RUNWAY)
    models: dict[str, SodModel] = {}
    if sod_models:
        models.update(sod_models)

    if "FOKKER" not in models:
        models["FOKKER"] = build_baseline_aircraft_sod("FOKKER")
    if "RUNWAY" not in models:
        models["RUNWAY"] = build_runway_sod("RUNWAY")

    # 2. Register Meshes in glTF
    mesh_indices: dict[str, int] = {}
    for m_name, sod_m in models.items():
        # Apply decal displacement if not already applied
        displaced_m = apply_decal_displacement_to_model(sod_m)
        vertices, indices = displaced_m.triangulate()
        if not vertices or not indices:
            continue

        positions = [list(v.position) for v in vertices]
        normals = [list(v.normal) for v in vertices]
        colors = [list(get_palette_color_0(v.palette_index)) for v in vertices]

        mesh_idx = builder.add_mesh_primitive(
            positions=positions,
            normals=normals,
            colors=colors,
            indices=indices,
            name=m_name,
        )
        mesh_indices[m_name] = mesh_idx

    # 3. Create Scene Graph Nodes
    # Root Stage Node for static environment
    stage_node = builder.add_node(name="StageEnvironment", is_scene_root=True)

    # Add static Runway mesh under StageEnvironment
    if "RUNWAY" in mesh_indices:
        _ = builder.add_node(
            name="Prop_Runway",
            mesh=mesh_indices["RUNWAY"],
            children=None,
        )
        # Note: can attach as child or root
        # Attach as child to stage_node:
        builder._nodes[stage_node]["children"] = [len(builder._nodes) - 1]

    # Camera Node
    cam_init_fov_deg = records[0]["camera"].get("fov_degrees", 45.0)
    cam_init_fov_rad = math.radians(cam_init_fov_deg)
    cam_idx = builder.add_camera(yfov_radians=cam_init_fov_rad, name="FlightCamera")

    cam_init_eye = records[0]["camera"]["eye"]
    cam_init_target = records[0]["camera"]["target"]
    cam_init_roll = records[0]["camera"].get("roll_radians", 0.0)
    cam_init_quat = compute_camera_quaternion(cam_init_eye, cam_init_target, cam_init_roll)

    cam_node = builder.add_node(
        name="CameraRig",
        camera=cam_idx,
        translation=cam_init_eye,
        rotation=cam_init_quat,
        is_scene_root=True,
    )

    # Actor Nodes
    # Identify unique actors in tick 0
    actor_nodes: dict[int, int] = {}
    for actor in records[0].get("actors", []):
        a_id = actor["actor_id"]
        m_name = actor.get("model_name", "FOKKER")
        m_idx = mesh_indices.get(m_name, mesh_indices.get("FOKKER"))
        pos = actor.get("position_meters", [0.0, 0.0, 0.0])
        quat = actor.get("rotation_quat", [0.0, 0.0, 0.0, 1.0])

        node_idx = builder.add_node(
            name=f"Actor_{a_id}_{m_name}",
            mesh=m_idx,
            translation=pos,
            rotation=quat,
            is_scene_root=True,
        )
        actor_nodes[a_id] = node_idx

    # 4. Extract Animation Tracks
    cam_trans_track: list[Sequence[float]] = []
    cam_rot_track: list[Sequence[float]] = []
    actor_trans_tracks: dict[int, list[Sequence[float]]] = {a_id: [] for a_id in actor_nodes}
    actor_rot_tracks: dict[int, list[Sequence[float]]] = {a_id: [] for a_id in actor_nodes}

    for rec in records:
        cam_info = rec["camera"]
        eye = cam_info["eye"]
        target = cam_info["target"]
        roll = cam_info.get("roll_radians", 0.0)

        cam_trans_track.append(eye)
        cam_rot_track.append(compute_camera_quaternion(eye, target, roll))

        actors_by_id = {a["actor_id"]: a for a in rec.get("actors", [])}
        for a_id in actor_nodes:
            if a_id in actors_by_id:
                act = actors_by_id[a_id]
                actor_trans_tracks[a_id].append(act["position_meters"])
                actor_rot_tracks[a_id].append(act["rotation_quat"])
            else:
                # Maintain last position if actor temporarily absent
                last_pos = (
                    actor_trans_tracks[a_id][-1] if actor_trans_tracks[a_id] else [0.0, 0.0, 0.0]
                )
                last_rot = (
                    actor_rot_tracks[a_id][-1] if actor_rot_tracks[a_id] else [0.0, 0.0, 0.0, 1.0]
                )
                actor_trans_tracks[a_id].append(last_pos)
                actor_rot_tracks[a_id].append(last_rot)

    # 5. Assemble Animation Channels
    anim_translations: dict[int, Sequence[Sequence[float]]] = {cam_node: cam_trans_track}
    anim_rotations: dict[int, Sequence[Sequence[float]]] = {cam_node: cam_rot_track}

    for a_id, a_node in actor_nodes.items():
        anim_translations[a_node] = actor_trans_tracks[a_id]
        anim_rotations[a_node] = actor_rot_tracks[a_id]

    builder.add_animation(
        name="INTRO_ALL",
        timestamps=timestamps,
        translations=anim_translations,
        rotations=anim_rotations,
    )

    # 6. Build and write .glb file
    glb_data = builder.build_glb()
    out_p.write_bytes(glb_data)
    return out_p


def export_intro_glb(
    output_path: Path | str = "build/gltf_output/INTRO.glb",
    trajectory_path: Path | str = "corpus/oracle/intro_trajectory.json",
) -> Path:
    """Produce the official Milestone 1 INTRO.glb delivery artifact."""
    return export_trajectory_to_glb(
        trajectory_path=trajectory_path,
        output_path=output_path,
        tick_rate=20.0,
    )
