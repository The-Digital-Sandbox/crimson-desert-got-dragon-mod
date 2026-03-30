"""
Import all 3 objects side by side for manual alignment.
Run in Blender: Text Editor > Open > Run Script

After running:
  - CD_Mesh and CD_Dragon armature are overlapping (matched coordinates)
  - Drogon is placed to the left, same scale, ready to drag into position
  - No shrinkwrap — add it yourself when Drogon is aligned

Manual workflow:
  1. Select Drogon, G to grab, move it over the CD mesh/armature
  2. R Z 180 to rotate if facing wrong way
  3. S X / S Y / S Z to scale per-axis to match
  4. When aligned: select CD_Mesh > Add Modifier > Shrinkwrap > target=Drogon
  5. Adjust until happy, then Apply the modifier
  6. Run blender_export_pac.py
"""

import bpy
import json
from pathlib import Path
from mathutils import Matrix, Vector

ROOT = Path(r"C:\Users\waelj\got-dragon-cd-mod")
SKELETON_JSON = ROOT / "output" / "cd_skeleton.json"
CD_MESH_OBJ = ROOT / "output" / "dragon_decoded.obj"
DROGON_OBJ = Path(r"C:\Users\waelj\Desktop\Outputs\DROGON.OBJ")
SCALE = 4.0
LEAF_BONE_LENGTH = 0.15

AXIS_SWAP = Matrix((
    (1,  0,  0, 0),
    (0,  0, -1, 0),
    (0,  1,  0, 0),
    (0,  0,  0, 1),
))


def cleanup():
    for name in ["CD_Mesh", "Drogon", "CD_Dragon"]:
        if name in bpy.data.objects:
            bpy.data.objects.remove(bpy.data.objects[name], do_unlink=True)
    if "CD_Dragon" in bpy.data.armatures:
        bpy.data.armatures.remove(bpy.data.armatures["CD_Dragon"])
    for m in list(bpy.data.meshes):
        if m.users == 0:
            bpy.data.meshes.remove(m)
    # Remove default cube if present
    if "Cube" in bpy.data.objects:
        bpy.data.objects.remove(bpy.data.objects["Cube"], do_unlink=True)


def build_armature():
    with open(str(SKELETON_JSON), 'r') as f:
        bones_data = json.load(f)

    n = len(bones_data)
    world_mats = []
    for b in bones_data:
        m = b['local_matrix']
        bm = Matrix((
            (m[0][0], m[1][0], m[2][0], m[3][0] * SCALE),
            (m[0][1], m[1][1], m[2][1], m[3][1] * SCALE),
            (m[0][2], m[1][2], m[2][2], m[3][2] * SCALE),
            (m[0][3], m[1][3], m[2][3], m[3][3]),
        ))
        world_mats.append(AXIS_SWAP @ bm)

    children_of = {}
    for bd in bones_data:
        pid = bd['parent_index']
        if pid >= 0:
            children_of.setdefault(pid, []).append(bd['index'])

    arm = bpy.data.armatures.new("CD_Dragon")
    arm_obj = bpy.data.objects.new("CD_Dragon", arm)
    bpy.context.collection.objects.link(arm_obj)
    bpy.context.view_layer.objects.active = arm_obj
    arm_obj.select_set(True)
    bpy.ops.object.mode_set(mode='EDIT')

    ebs = {}
    for bd in bones_data:
        idx = bd['index']
        eb = arm.edit_bones.new(bd['name'])
        eb.head = world_mats[idx].translation.copy()
        eb.tail = eb.head + Vector((0, 0.01, 0))
        ebs[idx] = eb

    for bd in bones_data:
        pid = bd['parent_index']
        if 0 <= pid < n:
            ebs[bd['index']].parent = ebs[pid]

    for bd in bones_data:
        idx = bd['index']
        eb = ebs[idx]
        mat = world_mats[idx]
        y_axis = Vector((mat[0][1], mat[1][1], mat[2][1])).normalized()
        z_axis = Vector((mat[0][2], mat[1][2], mat[2][2])).normalized()
        kids = children_of.get(idx, [])
        if kids:
            d = world_mats[kids[0]].translation - eb.head
            if d.length > 0.001:
                eb.tail = eb.head + d.normalized() * d.length
            else:
                eb.tail = eb.head + y_axis * LEAF_BONE_LENGTH
        else:
            eb.tail = eb.head + (y_axis * LEAF_BONE_LENGTH if y_axis.length > 0.001 else Vector((0, LEAF_BONE_LENGTH, 0)))
        if (eb.tail - eb.head).length < 0.0001:
            eb.tail = eb.head + Vector((0, LEAF_BONE_LENGTH, 0))
        try:
            eb.align_roll(z_axis)
        except:
            pass

    bpy.ops.object.mode_set(mode='OBJECT')
    arm_obj.show_in_front = True
    arm.display_type = 'STICK'
    print(f"Armature: {n} bones")
    return arm_obj


def import_obj(filepath, name):
    before = set(bpy.data.objects.keys())
    bpy.ops.wm.obj_import(filepath=str(filepath), forward_axis='NEGATIVE_Z', up_axis='Y')
    new_names = sorted(set(bpy.data.objects.keys()) - before)
    if not new_names:
        raise RuntimeError(f"Import failed: {filepath}")

    if len(new_names) == 1:
        obj = bpy.data.objects[new_names[0]]
    else:
        # Multiple objects imported (OBJ has groups) — join them all
        print(f"  Joining {len(new_names)} imported objects...")
        bpy.ops.object.select_all(action='DESELECT')
        for n in new_names:
            bpy.data.objects[n].select_set(True)
        bpy.context.view_layer.objects.active = bpy.data.objects[new_names[0]]
        bpy.ops.object.join()
        obj = bpy.context.active_object

    obj.name = name
    if obj.data:
        obj.data.name = name
    return obj


def main():
    if bpy.context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    bpy.ops.object.select_all(action='DESELECT')

    print("=" * 50)
    print("IMPORTING ALL — MANUAL ALIGNMENT MODE")
    print("=" * 50)

    cleanup()

    # 1. Armature (at correct position, Z-up, 4x)
    print("\n[1/3] Armature...")
    arm = build_armature()

    # 2. CD mesh (same space as armature)
    print("\n[2/3] CD mesh...")
    cd = import_obj(CD_MESH_OBJ, "CD_Mesh")
    cd.scale = (SCALE, SCALE, SCALE)
    bpy.context.view_layer.objects.active = cd
    cd.select_set(True)
    bpy.ops.object.transform_apply(scale=True)
    cd.select_set(False)
    print(f"  CD_Mesh: {len(cd.data.vertices)} verts, 4x scaled")

    # 3. Drogon (symmetrize + placed to the left, same scale as CD)
    print("\n[3/3] Drogon...")
    drogon = import_obj(DROGON_OBJ, "Drogon")

    # Symmetrize if half-mesh
    bpy.context.view_layer.objects.active = drogon
    drogon.select_set(True)
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.mesh.symmetrize(direction='NEGATIVE_X')
    bpy.ops.object.mode_set(mode='OBJECT')
    drogon.select_set(False)
    print(f"  Drogon: {len(drogon.data.vertices)} verts (symmetrized)")

    # Scale Drogon to roughly match CD mesh size
    cd_verts = [cd.matrix_world @ v.co for v in cd.data.vertices]
    cd_xs = [v.x for v in cd_verts]; cd_ys = [v.y for v in cd_verts]; cd_zs = [v.z for v in cd_verts]
    cd_span = max(max(cd_xs)-min(cd_xs), max(cd_ys)-min(cd_ys), max(cd_zs)-min(cd_zs))

    dr_verts = [drogon.matrix_world @ v.co for v in drogon.data.vertices]
    dr_xs = [v.x for v in dr_verts]; dr_ys = [v.y for v in dr_verts]; dr_zs = [v.z for v in dr_verts]
    dr_span = max(max(dr_xs)-min(dr_xs), max(dr_ys)-min(dr_ys), max(dr_zs)-min(dr_zs))

    scale_factor = cd_span / dr_span if dr_span > 0.001 else 1.0
    drogon.scale = (scale_factor, scale_factor, scale_factor)
    bpy.context.view_layer.objects.active = drogon
    drogon.select_set(True)
    bpy.ops.object.transform_apply(scale=True)
    drogon.select_set(False)
    print(f"  Scaled by {scale_factor:.6f}")

    # Place Drogon to the LEFT of CD mesh (offset on Y axis)
    drogon.location.y = min(cd_ys) - cd_span * 0.8

    # Set display
    drogon.display_type = 'WIRE'

    # Frame all
    bpy.ops.object.select_all(action='SELECT')
    for area in bpy.context.screen.areas:
        if area.type == 'VIEW_3D':
            for region in area.regions:
                if region.type == 'WINDOW':
                    with bpy.context.temp_override(area=area, region=region):
                        bpy.ops.view3d.view_all()
                    break
            break

    bpy.ops.object.select_all(action='DESELECT')

    print("\n" + "=" * 50)
    print("READY FOR MANUAL ALIGNMENT")
    print("=" * 50)
    print("  CD_Mesh + CD_Dragon armature: overlapping (correct)")
    print("  Drogon: offset to the side (wireframe)")
    print()
    print("  YOUR STEPS:")
    print("  1. Select Drogon (click it)")
    print("  2. G → drag over CD mesh/armature")
    print("  3. R Z 180 → rotate if facing wrong direction")
    print("  4. S X / S Y / S Z → scale per-axis to match")
    print("  5. Select CD_Mesh → Modifiers → Shrinkwrap → target: Drogon")
    print("  6. Tweak until happy → Apply modifier")
    print("  7. Run blender_export_pac.py")
    print("=" * 50)


if __name__ == '__main__':
    main()
