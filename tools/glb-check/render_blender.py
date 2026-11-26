"""Renders one .glb to a PNG in Blender's background mode, on the CPU (Cycles), for a cloud session.

Run by glb_check.py as: blender -b --factory-startup -P render_blender.py -- IN.glb OUT.png SECONDS
The scene is framed on the union of its mesh bounding boxes at the frame for SECONDS.
"""

import math
import sys

import bpy
from mathutils import Vector

src, dst, seconds = sys.argv[sys.argv.index("--") + 1 :][:3]
seconds = float(seconds)

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=src)
scene = bpy.context.scene

fps = scene.render.fps or 24
frame = round(seconds * fps)
scene.frame_set(scene.frame_start + frame)

meshes = [o for o in scene.objects if o.type == "MESH"]
if not meshes:
    sys.exit(f"render_blender: {src} holds no mesh objects")
corners = [o.matrix_world @ Vector(c) for o in meshes for c in o.bound_box]
lo = Vector(map(min, zip(*corners, strict=True)))
hi = Vector(map(max, zip(*corners, strict=True)))
centre = (lo + hi) / 2
radius = max((hi - lo).length / 2, 1e-3)

target = bpy.data.objects.new("target", None)
scene.collection.objects.link(target)
target.location = centre

cam_data = bpy.data.cameras.new("camera")
cam_data.clip_end = radius * 100
camera = bpy.data.objects.new("camera", cam_data)
scene.collection.objects.link(camera)
camera.location = centre + Vector((1.0, -1.0, 0.6)).normalized() * radius * 3.0
track = camera.constraints.new("TRACK_TO")
track.target = target
track.track_axis = "TRACK_NEGATIVE_Z"
track.up_axis = "UP_Y"
scene.camera = camera

sun_data = bpy.data.lights.new("sun", "SUN")
sun_data.energy = 3.0
sun = bpy.data.objects.new("sun", sun_data)
scene.collection.objects.link(sun)
sun.rotation_euler = (math.radians(50), 0.0, math.radians(35))

world = bpy.data.worlds.new("world")
world.use_nodes = True
world.node_tree.nodes["Background"].inputs[0].default_value = (0.25, 0.27, 0.3, 1.0)
scene.world = world

scene.render.engine = "CYCLES"
scene.cycles.device = "CPU"
scene.cycles.samples = 64
scene.cycles.use_denoising = False
scene.render.resolution_x = 960
scene.render.resolution_y = 720
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = "PNG"
scene.render.filepath = dst
bpy.ops.render.render(write_still=True)
print(f"render_blender: wrote {dst} at frame {scene.frame_current} ({seconds:.3f} s)")  # noqa: T201 - Blender console
