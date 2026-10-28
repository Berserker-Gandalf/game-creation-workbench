"""Run only with Blender's bundled Python. No recipe content is executed."""
import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector


def main(folder):
    spec = json.loads((folder / 'recipe.json').read_text(encoding='utf-8'))
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    scene = bpy.context.scene
    scene.unit_settings.system = 'METRIC'
    scene.unit_settings.scale_length = 1
    scene['workbench_recipe'] = json.dumps(spec, ensure_ascii=False)
    scene['workbench_note'] = 'Editable low-poly blockout. Separate mesh parts. No rig or production topology.'
    materials, parts = {}, []
    for name, key in [('skin', 'skin_color'), ('cloth', 'clothing_color'), ('hair', 'hair_color'), ('accent', 'accent_color')]:
        color = [int(spec[key][i:i + 2], 16) / 255 for i in (1, 3, 5)]
        linear = [v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4 for v in color]
        mat = bpy.data.materials.new(name)
        mat.diffuse_color = (*linear, 1)
        mat.use_nodes = True
        node = mat.node_tree.nodes.get('Principled BSDF')
        node.inputs['Base Color'].default_value = (*linear, 1)
        node.inputs['Roughness'].default_value = .72
        materials[name] = mat

    def finish(name, material):
        obj = bpy.context.object
        obj.name = name
        obj.data.materials.append(materials[material])
        bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
        parts.append(obj)
        return obj

    def box(name, at, size, mat):
        bpy.ops.mesh.primitive_cube_add(size=1, location=at)
        bpy.context.object.scale = size
        return finish(name, mat)

    def sphere(name, at, size, mat):
        bpy.ops.mesh.primitive_uv_sphere_add(segments=12, ring_count=6, radius=1, location=at)
        bpy.context.object.scale = size
        return finish(name, mat)

    def limb(name, start, end, radius, mat):
        a, b = Vector(start), Vector(end)
        direction = b - a
        bpy.ops.mesh.primitive_cone_add(vertices=8, radius1=radius * .82, radius2=radius,
                                       depth=direction.length, location=(a + b) / 2)
        bpy.context.object.rotation_euler = direction.to_track_quat('Z', 'Y').to_euler()
        return finish(name, mat)

    h = spec['height']
    hh, hip = h * spec['head_ratio'], h * spec['leg_ratio']
    shoulder = h * spec['shoulder_ratio']
    width = shoulder * spec['body_scale']
    neck = h - hh
    depth = width * .48
    robot = spec['style'] == 'robot'
    box('Torso', (0, 0, (neck + hip) / 2), (width * .85, depth, (neck - hip) * .88), 'cloth')
    box('Hips', (0, 0, hip), (width * .7, depth * .95, h * .08), 'cloth')
    limb('Neck', (0, 0, neck - .02 * h), (0, 0, neck + .06 * hh), .065 * h, 'skin')
    head_size = (hh * (.5 if spec['style'] == 'chibi' else .46), hh * .42, hh * .5)
    if robot:
        box('Head', (0, 0, h - hh / 2), tuple(v * 2 for v in head_size), 'skin')
        box('Visor', (0, -hh * .425, h - hh * .46), (hh * .76, hh * .06, hh * .18), 'hair')
    else:
        sphere('Head', (0, 0, h - hh / 2), head_size, 'skin')
        for sign, label in [(-1, 'L'), (1, 'R')]:
            sphere('Ear_' + label, (sign * hh * .44, 0, h - hh * .51), (hh * .085, hh * .10, hh * .12), 'skin')
            sphere('Eye_' + label, (sign * hh * .17, -hh * .387, h - hh * .46), (hh * .045, hh * .035, hh * .06), 'hair')
        box('Mouth', (0, -hh * .394, h - hh * .68), (hh * .18, hh * .025, hh * .025), 'hair')
    if spec['hair'] != 'none':
        # Top hemisphere, open below, leaving the face visible.
        verts = [(0, 0, h + hh * .02)]
        for ring in range(1, 4):
            angle = ring * math.pi / 6
            for i in range(12):
                theta = i * 2 * math.pi / 12
                verts.append((hh * .48 * math.sin(angle) * math.cos(theta),
                              hh * .44 * math.sin(angle) * math.sin(theta), h - hh * .48 + hh * .5 * math.cos(angle) + hh * .23 * max(0, -math.sin(theta)) * math.sin(angle)))
        faces = [(0, 1 + i, 1 + (i + 1) % 12) for i in range(12)]
        for r in range(2):
            a, b = 1 + r * 12, 13 + r * 12
            faces.extend((a + i, b + i, b + (i + 1) % 12, a + (i + 1) % 12) for i in range(12))
        mesh = bpy.data.meshes.new('HairCap')
        mesh.from_pydata(verts, [], faces)
        mesh.update()
        obj = bpy.data.objects.new('HairCap', mesh)
        scene.collection.objects.link(obj)
        obj.data.materials.append(materials['hair'])
        parts.append(obj)
        if spec['hair'] == 'bob':
            box('HairBack', (0, hh * .27, h - hh * .63), (hh * .86, hh * .3, hh * .62), 'hair')

    for sign, label in [(-1, 'L'), (1, 'R')]:
        x = sign * width * .22
        knee, ankle = (x, -.015 * h, hip * .52), (x, 0, .09 * h)
        limb('Thigh_' + label, (x, 0, hip), knee, width * .17, 'cloth')
        sphere('Knee_' + label, knee, (width * .13,) * 3, 'accent' if robot else 'cloth')
        limb('Shin_' + label, knee, ankle, width * .13, 'cloth')
        box('Boot_' + label, (x, -.045 * h, .04 * h), (width * .27, .16 * h, .08 * h), 'hair')
        start = Vector((sign * shoulder * .48, 0, neck - h * .045))
        arm = spec['arm_ratio'] * h
        angle = math.radians(90 if spec['pose'] == 't_pose' else 35)
        direction = Vector((sign * math.sin(angle), 0, -math.cos(angle)))
        elbow, wrist = start + direction * arm * .52, start + direction * arm
        limb('UpperArm_' + label, start, elbow, shoulder * .12, 'cloth')
        sphere('Elbow_' + label, elbow, (shoulder * .10,) * 3, 'accent' if robot else 'skin')
        limb('Forearm_' + label, elbow, wrist, shoulder * .095, 'skin')
        sphere('Hand_' + label, wrist, (shoulder * .1, shoulder * .075, shoulder * .13), 'skin')
        if spec['outfit'] == 'armor':
            box('ShoulderArmor_' + label, start, (shoulder * .35, depth * 1.2, h * .09), 'accent')
    if spec['outfit'] in ('tunic', 'armor'):
        box('Belt', (0, -.005 * h, hip + h * .1), (width * .89, depth * 1.05, h * .035), 'accent')
        if spec['outfit'] == 'tunic':
            box('TunicHem', (0, 0, hip + h * .03), (width * .94, depth * 1.05, h * .13), 'cloth')
        else:
            box('ChestPlate', (0, -depth * .52, (neck + hip) / 2), (width * .68, h * .035, (neck - hip) * .6), 'accent')
    if spec['accessory'] == 'backpack':
        box('Backpack', (0, depth * .9, (neck + hip) / 2), (width * .65, depth * .75, h * .23), 'hair')
        box('BackpackFlap', (0, depth * 1.28, (neck + hip) / 2 + h * .055), (width * .58, h * .025, h * .06), 'accent')
    elif spec['accessory'] == 'staff':
        x = shoulder * .48 + spec['arm_ratio'] * h * math.sin(angle)
        limb('Staff', (x, -.06 * h, .01 * h), (x, -.06 * h, h * .92), h * .015, 'hair')
        sphere('StaffGem', (x, -.06 * h, h * .94), (h * .055,) * 3, 'accent')

    bpy.ops.object.select_all(action='DESELECT')
    for obj in parts:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = parts[0]
    bpy.ops.export_scene.gltf(filepath=str(folder / 'character.glb'), export_format='GLB',
                              use_selection=True, export_yup=True, export_extras=True)
    points = [obj.matrix_world @ Vector(corner) for obj in parts for corner in obj.bound_box]
    minimum = Vector(tuple(min(p[i] for p in points) for i in range(3)))
    maximum = Vector(tuple(max(p[i] for p in points) for i in range(3)))
    center = (minimum + maximum) / 2
    bpy.ops.object.camera_add(location=center + Vector((h * 1.5, -h * 2.8, h * 1.05)))
    camera = bpy.context.object
    camera.rotation_euler = (center - camera.location).to_track_quat('-Z', 'Y').to_euler()
    camera.data.type = 'ORTHO'
    camera.data.ortho_scale = max(maximum - minimum) * 1.4
    scene.camera = camera
    for location, power, size in [((h * 2, -h * 2, h * 3), 450, h * 2), ((-h * 2, -h, h * 2), 250, h * 2), ((0, h * 2, h * 3), 400, h)]:
        bpy.ops.object.light_add(type='AREA', location=location)
        light = bpy.context.object
        light.data.energy = power
        light.data.shape = 'DISK'
        light.data.size = size
        light.rotation_euler = (center - light.location).to_track_quat('-Z', 'Y').to_euler()
    scene.world.use_nodes = True
    scene.world.node_tree.nodes['Background'].inputs[0].default_value = (.12, .14, .18, 1)
    scene.world.node_tree.nodes['Background'].inputs[1].default_value = .5
    scene.render.engine = 'CYCLES'
    scene.cycles.device = 'CPU'
    scene.cycles.samples = 8
    scene.render.resolution_x = scene.render.resolution_y = 512
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = 'PNG'
    scene.render.filepath = str(folder / 'preview.png')
    bpy.ops.wm.save_as_mainfile(filepath=str(folder / 'character.blend'), compress=False)
    bpy.ops.render.render(write_still=True)
    stats = {'blender': bpy.app.version_string, 'objects': len(parts),
             'vertices': sum(len(o.data.vertices) for o in parts),
             'triangles': sum(sum(len(p.vertices) - 2 for p in o.data.polygons) for o in parts),
             'bounds': [list(minimum), list(maximum)], 'rigged': False}
    (folder / 'build.json').write_text(json.dumps(stats), encoding='utf-8')
    print('WORKBENCH_CHARACTER_OK ' + json.dumps(stats))


if __name__ == '__main__':
    main(Path(sys.argv[sys.argv.index('--') + 1]).resolve())
