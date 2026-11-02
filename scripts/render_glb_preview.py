#!/usr/bin/env python3
"""Render one unchanged external GLB with Blender in a disposable background process.

Example: blender --background --factory-startup --python scripts/render_glb_preview.py
         -- --input /path/to/model.glb --output preview.png
         --source-project project-name --source-id logical/model.glb
         --source-revision fixed-revision
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys

import bpy
from mathutils import Vector


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def arguments():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--source-project', required=True)
    parser.add_argument('--source-id', required=True)
    parser.add_argument('--source-revision', required=True)
    parser.add_argument('--azimuth', default=-45.0, type=float)
    parser.add_argument('--elevation', default=28.0, type=float)
    parser.add_argument('--samples', default=32, type=int)
    return parser.parse_args(sys.argv[sys.argv.index('--') + 1:])


def point_at(obj, target):
    obj.rotation_euler = (target - obj.location).to_track_quat('-Z', 'Y').to_euler()


def area_light(name, position, target, energy, size, specular):
    data = bpy.data.lights.new(name, 'AREA')
    data.energy = energy
    data.shape = 'DISK'
    data.size = size
    data.diffuse_factor = 1
    data.specular_factor = specular
    obj = bpy.data.objects.new(name, data)
    bpy.context.scene.collection.objects.link(obj)
    obj.location = position
    point_at(obj, target)


def main():
    args = arguments()
    source = args.input.resolve(strict=True)
    output = args.output.resolve()
    if source.suffix.lower() != '.glb' or output.suffix.lower() != '.png':
        raise ValueError('Expected a GLB source and PNG output')
    if output == source:
        raise ValueError('Output must not replace the source')
    if Path(args.source_id).is_absolute() or '://' in args.source_id:
        raise ValueError('Use a logical relative source identity, not a local path or URL')
    if output.exists() or output.with_suffix('.json').exists():
        raise FileExistsError('Use a new output; existing previews are not replaced')
    before = digest(source)
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    bpy.ops.import_scene.gltf(filepath=str(source))
    meshes = [o for o in bpy.context.scene.objects if o.type == 'MESH' and not o.hide_render]
    if not meshes:
        raise ValueError('The GLB contains no renderable mesh')
    points = [o.matrix_world @ vertex.co for o in meshes for vertex in o.data.vertices]
    low = Vector(tuple(min(p[i] for p in points) for i in range(3)))
    high = Vector(tuple(max(p[i] for p in points) for i in range(3)))
    center = (low + high) * 0.5
    span = high - low
    radius = max(span) * 0.5
    if not math.isfinite(radius) or radius <= 0:
        raise ValueError('Invalid mesh bounds')

    scene = bpy.context.scene
    scene.render.engine = 'CYCLES'
    scene.cycles.device = 'CPU'
    scene.cycles.samples = args.samples
    scene.cycles.use_denoising = True
    scene.render.threads_mode = 'FIXED'
    scene.render.threads = 2
    scene.render.resolution_x = 1536
    scene.render.resolution_y = 1024
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = True
    scene.render.dither_intensity = 0
    scene.render.image_settings.file_format = 'PNG'
    scene.render.image_settings.color_mode = 'RGB'
    scene.render.image_settings.color_depth = '8'
    scene.view_settings.view_transform = 'Standard'
    scene.view_settings.look = 'None'
    scene.view_settings.exposure = 0
    scene.view_settings.gamma = 1
    scene.render.image_settings.color_management = 'FOLLOW_SCENE'

    world = bpy.data.worlds.new('White preview environment')
    world.use_nodes = True
    scene.world = world
    nodes, links = world.node_tree.nodes, world.node_tree.links
    nodes.clear()
    out = nodes.new('ShaderNodeOutputWorld')
    ray = nodes.new('ShaderNodeLightPath')
    environment = nodes.new('ShaderNodeBackground')
    environment.inputs['Color'].default_value = (1, 1, 1, 1)
    environment.inputs['Strength'].default_value = 0.18
    reflection_environment = nodes.new('ShaderNodeBackground')
    reflection_environment.inputs['Color'].default_value = (1, 1, 1, 1)
    reflection_environment.inputs['Strength'].default_value = 0.015
    reflection_mix = nodes.new('ShaderNodeMixShader')
    links.new(ray.outputs['Is Glossy Ray'], reflection_mix.inputs[0])
    links.new(environment.outputs[0], reflection_mix.inputs[1])
    links.new(reflection_environment.outputs[0], reflection_mix.inputs[2])
    camera_background = nodes.new('ShaderNodeBackground')
    camera_background.inputs['Color'].default_value = (1, 1, 1, 1)
    camera_background.inputs['Strength'].default_value = 1
    mix = nodes.new('ShaderNodeMixShader')
    links.new(ray.outputs['Is Camera Ray'], mix.inputs[0])
    links.new(reflection_mix.outputs[0], mix.inputs[1])
    links.new(camera_background.outputs[0], mix.inputs[2])
    links.new(mix.outputs[0], out.inputs['Surface'])

    compositor = bpy.data.node_groups.new('White background composite', 'CompositorNodeTree')
    compositor.interface.new_socket(name='Image', in_out='OUTPUT', socket_type='NodeSocketColor')
    scene.compositing_node_group = compositor
    scene.render.use_compositing = True
    render_layer = compositor.nodes.new('CompositorNodeRLayers')
    render_layer.scene = scene
    alpha_over = compositor.nodes.new('CompositorNodeAlphaOver')
    alpha_over.inputs['Factor'].default_value = 1
    alpha_over.inputs['Background'].default_value = (1, 1, 1, 1)
    composite_output = compositor.nodes.new('NodeGroupOutput')
    compositor.links.new(render_layer.outputs['Image'], alpha_over.inputs['Foreground'])
    compositor.links.new(alpha_over.outputs['Image'], composite_output.inputs['Image'])

    camera_data = bpy.data.cameras.new('Model preview camera')
    camera_data.type = 'ORTHO'
    camera_data.clip_start = max(radius * 0.001, 0.0001)
    camera_data.clip_end = radius * 40
    camera = bpy.data.objects.new('Model preview camera', camera_data)
    scene.collection.objects.link(camera)
    azimuth, elevation = math.radians(args.azimuth), math.radians(args.elevation)
    direction = Vector((math.cos(elevation) * math.cos(azimuth),
                        math.cos(elevation) * math.sin(azimuth), math.sin(elevation)))
    camera.location = center + direction * radius * 7
    point_at(camera, center)
    local = camera.rotation_euler.to_matrix().transposed()
    projected = [local @ (p - center) for p in points]
    width = max(p.x for p in projected) - min(p.x for p in projected)
    height = max(p.y for p in projected) - min(p.y for p in projected)
    shift = Vector(((max(p.x for p in projected) + min(p.x for p in projected)) * 0.5,
                    (max(p.y for p in projected) + min(p.y for p in projected)) * 0.5, 0))
    world_shift = camera.rotation_euler.to_matrix() @ shift
    camera.location += world_shift
    camera_target = center + world_shift
    point_at(camera, camera_target)
    camera_data.ortho_scale = max(width, height * 1.5) * 1.22
    scene.camera = camera

    studio_lights = [
        ('Soft key', (3, -4, 5), 350, 8, 0.08),
        ('Soft fill', (-4, -1, 2.5), 150, 10, 0.05),
    ]
    for name, offset, energy, size, specular in studio_lights:
        area_light(name, center + Vector(offset) * radius, center,
                   energy * radius * radius, size * radius, specular)

    output.parent.mkdir(parents=True, exist_ok=True)
    scene.render.filepath = str(output)
    bpy.ops.render.render(write_still=True)
    if digest(source) != before:
        raise RuntimeError('Source changed during rendering')
    triangles = sum(sum(len(poly.vertices) - 2 for poly in o.data.polygons) for o in meshes)
    receipt = {
        'schema': 1,
        'kind': 'Actual GLB material preview; no new geometry or generated image',
        'source': {'project': args.source_project, 'revision': args.source_revision,
                   'file': args.source_id, 'bytes': source.stat().st_size, 'sha256': before},
        'blender_version': bpy.app.version_string,
        'generator': {'file': 'scripts/render_glb_preview.py', 'sha256': digest(Path(__file__))},
        'recipe': {'engine': 'CYCLES', 'device': 'CPU', 'samples': args.samples,
                   'threads': 2, 'resolution': [1536, 1024], 'view_transform': 'Standard',
                   'look': 'None', 'exposure': 0, 'gamma': 1,
                   'background': 'Render alpha composited over pure white',
                   'lighting': 'Neutral soft studio preview: direct highlights suppressed by light contribution controls; model materials unchanged',
                   'environment': {'diffuse_strength': 0.18, 'glossy_ray_strength': 0.015},
                   'area_lights': [{'name': name, 'offset_in_radius_units': offset,
                                    'energy_per_radius_squared': energy,
                                    'diameter_in_radius_units': size,
                                    'diffuse_factor': 1, 'specular_factor': specular}
                                   for name, offset, energy, size, specular in studio_lights],
                   'added_scene_geometry': False,
                   'camera': {'projection': 'orthographic', 'azimuth_degrees': args.azimuth,
                              'elevation_degrees': args.elevation, 'margin_factor': 1.22,
                              'fit': 'Actual mesh vertex projection, centered in image plane',
                              'ortho_scale': camera_data.ortho_scale,
                              'target': list(camera_target), 'location': list(camera.location)},
                   'bounds': {'min': list(low), 'max': list(high)},
                   'mesh_objects': len(meshes), 'triangles': triangles,
                   'source_operation': 'Imported unchanged, with original PBR materials and textures'},
        'output': {'file': output.name, 'bytes': output.stat().st_size, 'sha256': digest(output)},
        'source_unchanged_after_render': True,
        'scope': 'Model preview only; not an engine assembly, gameplay or performance check',
    }
    output.with_suffix('.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps({'saved': output.name, 'source_unchanged': True, 'sha256': receipt['output']['sha256']}))


if __name__ == '__main__':
    main()
