"""
Blender Armature Builder for Crimson Desert Dragon (PAB Skeleton)
=================================================================
Run inside Blender: Text Editor > Open > Run Script  (or paste into console)

Reads cd_skeleton.json (274 bones from pab_decode.py) and builds a full
armature with correct hierarchy, positions, and orientations.

PAB stores 4 matrices per bone. The naming in pab_decode.py/cd_skeleton.json
is misleading:
  - "local_matrix" (1st)  = WORLD / armature-space transform (use directly)
  - "inv_local"    (2nd)  = inverse of 1st
  - "world_matrix" (3rd)  = LOCAL / bone-space transform (accumulates to 1st)
  - "inv_world"    (4th)  = inverse of 3rd

Verified: accumulating 3rd via child @ parent produces identical positions
to reading 1st directly. So we use the 1st matrix with NO accumulation —
same as BDO's ARMATURESPACE=True approach.

The PAB matrices use DirectX row-vector convention with translation in row 3.
Blender uses column-vector convention with translation in column 3.
Conversion: transpose the matrix.

Coordinate system: Game = Y-up (DirectX). Blender = Z-up.
"""

import bpy
import json
from mathutils import Matrix, Vector

# ==================== CONFIGURATION ====================
SKELETON_JSON = r"C:\Users\waelj\got-dragon-cd-mod\output\cd_skeleton.json"
SCALE = 4.0               # BaseCharacterScale from prefab
CONVERT_AXES = True        # Y-up (DX) → Z-up (Blender)
ARMATURE_NAME = "CD_Dragon"
LEAF_BONE_LENGTH = 0.15    # Tail length for leaf bones (scaled units)
# =======================================================

# Y-up → Z-up: rotate -90° around X axis
# Maps: X→X, Y→Z, Z→-Y
AXIS_SWAP = Matrix((
    (1,  0,  0, 0),
    (0,  0, -1, 0),
    (0,  1,  0, 0),
    (0,  0,  0, 1),
))


def get_world_matrices(bones_data):
    """Read world matrices directly from PAB (1st matrix = armature-space).

    No accumulation needed — the 1st matrix ("local_matrix" in JSON) is
    already the world/armature-space transform. Transpose for Blender.
    """
    blender_mats = []
    for b in bones_data:
        m = b['local_matrix']  # 1st PAB matrix = world transform
        # Transpose: DX row-vector → Blender column-vector
        # Scale translation only
        bm = Matrix((
            (m[0][0], m[1][0], m[2][0], m[3][0] * SCALE),
            (m[0][1], m[1][1], m[2][1], m[3][1] * SCALE),
            (m[0][2], m[1][2], m[2][2], m[3][2] * SCALE),
            (m[0][3], m[1][3], m[2][3], m[3][3]),
        ))
        if CONVERT_AXES:
            bm = AXIS_SWAP @ bm
        blender_mats.append(bm)

    return blender_mats


def build_armature():
    # Load skeleton
    with open(SKELETON_JSON, 'r') as f:
        bones_data = json.load(f)

    n = len(bones_data)
    print(f"Loaded {n} bones")

    # Use 1st PAB matrix directly as world transform (no accumulation)
    world_mats = get_world_matrices(bones_data)

    # Build children lookup
    children_of = {}
    for bd in bones_data:
        pid = bd['parent_index']
        if pid >= 0:
            children_of.setdefault(pid, []).append(bd['index'])

    # Clean up existing armature
    if ARMATURE_NAME in bpy.data.objects:
        obj = bpy.data.objects[ARMATURE_NAME]
        bpy.data.objects.remove(obj, do_unlink=True)
    if ARMATURE_NAME in bpy.data.armatures:
        bpy.data.armatures.remove(bpy.data.armatures[ARMATURE_NAME])

    # Create armature and object
    arm = bpy.data.armatures.new(ARMATURE_NAME)
    arm_obj = bpy.data.objects.new(ARMATURE_NAME, arm)
    bpy.context.collection.objects.link(arm_obj)
    bpy.context.view_layer.objects.active = arm_obj
    arm_obj.select_set(True)

    # --- Edit mode ---
    bpy.ops.object.mode_set(mode='EDIT')

    # Phase 1: Create all bones with temporary tails
    ebs = {}
    for bd in bones_data:
        idx = bd['index']
        eb = arm.edit_bones.new(bd['name'])
        head = world_mats[idx].translation.copy()
        eb.head = head
        eb.tail = head + Vector((0, 0.01, 0))  # temporary
        ebs[idx] = eb

    # Phase 2: Parent relationships
    for bd in bones_data:
        pid = bd['parent_index']
        if 0 <= pid < n:
            ebs[bd['index']].parent = ebs[pid]

    # Phase 3: Set tails and rolls from world matrices
    for bd in bones_data:
        idx = bd['index']
        eb = ebs[idx]
        mat = world_mats[idx]

        # Extract local axes from rotation part (columns of Blender matrix)
        y_axis = Vector((mat[0][1], mat[1][1], mat[2][1])).normalized()
        z_axis = Vector((mat[0][2], mat[1][2], mat[2][2])).normalized()

        kids = children_of.get(idx, [])

        if kids:
            # Point toward first child (preserves chain direction)
            child_head = world_mats[kids[0]].translation
            direction = child_head - eb.head
            length = direction.length

            if length > 0.001:
                # Cap bone length to avoid overshooting
                eb.tail = eb.head + direction.normalized() * min(length, length)
            else:
                eb.tail = eb.head + y_axis * LEAF_BONE_LENGTH
        else:
            # Leaf bone: offset along bone's local Y axis
            if y_axis.length > 0.001:
                eb.tail = eb.head + y_axis * LEAF_BONE_LENGTH
            else:
                eb.tail = eb.head + Vector((0, LEAF_BONE_LENGTH, 0))

        # Safety: head must differ from tail
        if (eb.tail - eb.head).length < 0.0001:
            eb.tail = eb.head + Vector((0, LEAF_BONE_LENGTH, 0))

        # Set roll from the bone's Z axis
        try:
            eb.align_roll(z_axis)
        except Exception:
            pass

    # --- Object mode ---
    bpy.ops.object.mode_set(mode='OBJECT')

    # Display
    arm_obj.show_in_front = True
    arm.display_type = 'STICK'

    # Summary
    roots = sum(1 for bd in bones_data if bd['parent_index'] == -1)
    print(f"\n{'='*50}")
    print(f"Armature: {ARMATURE_NAME}")
    print(f"  Bones: {n}  |  Roots: {roots}")
    print(f"  Scale: {SCALE}x  |  Axes: {'Z-up' if CONVERT_AXES else 'Y-up (raw)'}")

    # Print key bone positions for sanity check
    key = ['Bip01', 'Bip01 Pelvis', 'Bip01 Neck', 'Bip01 Head',
           'Bip01 Tail', 'Bip01 L Thigh', 'Bip01 R Thigh']
    by_name = {bd['name']: bd['index'] for bd in bones_data}
    for name in key:
        if name in by_name:
            pos = world_mats[by_name[name]].translation
            print(f"  {name:25s} ({pos.x:+8.2f}, {pos.y:+8.2f}, {pos.z:+8.2f})")

    print(f"{'='*50}")
    print("Done. Select armature and press 'A' in edit mode to see all bones.")


if __name__ == '__main__':
    build_armature()
