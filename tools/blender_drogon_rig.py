"""
Drogon Direct Rig — Apply CD Dragon armature to Drogon mesh
=============================================================
Run inside Blender: Text Editor > Open > Run Script

Approach:
  1. Build CD dragon armature (274 bones from cd_skeleton.json)
  2. Import Drogon OBJ, mirror if half-mesh
  3. Scale + position Drogon over the armature
  4. For EVERY vertex, find nearest bones by segment distance
  5. Assign weights proportionally (inverse distance, 4 influences max)
  6. Parent to armature with Armature modifier

No auto-weights, no heat map, no Blender solver — pure Python math.
"""

import bpy
import json
import math
from pathlib import Path
from mathutils import Matrix, Vector

# ==================== CONFIGURATION ====================
ROOT = Path(r"C:\Users\waelj\crimson-desert-got-dragon-mod")
SKELETON_JSON = ROOT / "output" / "cd_skeleton.json"
DROGON_OBJ = ROOT / "gpu-analysis" / "DROGON.obj"

SCALE = 4.0                # BaseCharacterScale from prefab
ARMATURE_NAME = "CD_Dragon"
DROGON_NAME = "Drogon"
LEAF_BONE_LENGTH = 0.15

MAX_INFLUENCES = 4          # Max bones per vertex (matches PAC format)
FALLOFF_POWER = 2.0         # Weight falloff: 1/dist^power (2.0 = inverse square)
# =======================================================

# Y-up -> Z-up: +90 deg rotation around X axis
# Maps: X->X, Y->Z, Z->-Y
AXIS_SWAP = Matrix((
    (1,  0,  0, 0),
    (0,  0, -1, 0),
    (0,  1,  0, 0),
    (0,  0,  0, 1),
))


# ------------------------------------------------------------------
# Cleanup
# ------------------------------------------------------------------

def cleanup_scene():
    print("[1/5] Cleaning up...")
    for name in [DROGON_NAME, ARMATURE_NAME]:
        if name in bpy.data.objects:
            bpy.data.objects.remove(bpy.data.objects[name], do_unlink=True)
    if ARMATURE_NAME in bpy.data.armatures:
        bpy.data.armatures.remove(bpy.data.armatures[ARMATURE_NAME])
    for name in [DROGON_NAME]:
        if name in bpy.data.meshes:
            bpy.data.meshes.remove(bpy.data.meshes[name])


# ------------------------------------------------------------------
# Armature builder
# ------------------------------------------------------------------

def get_world_matrices(bones_data):
    blender_mats = []
    for b in bones_data:
        m = b['local_matrix']
        bm = Matrix((
            (m[0][0], m[1][0], m[2][0], m[3][0] * SCALE),
            (m[0][1], m[1][1], m[2][1], m[3][1] * SCALE),
            (m[0][2], m[1][2], m[2][2], m[3][2] * SCALE),
            (m[0][3], m[1][3], m[2][3], m[3][3]),
        ))
        bm = AXIS_SWAP @ bm
        blender_mats.append(bm)
    return blender_mats


def build_armature(bones_data):
    print("[2/5] Building CD dragon armature...")

    n = len(bones_data)
    world_mats = get_world_matrices(bones_data)

    children_of = {}
    for bd in bones_data:
        pid = bd['parent_index']
        if pid >= 0:
            children_of.setdefault(pid, []).append(bd['index'])

    arm = bpy.data.armatures.new(ARMATURE_NAME)
    arm_obj = bpy.data.objects.new(ARMATURE_NAME, arm)
    bpy.context.collection.objects.link(arm_obj)
    bpy.context.view_layer.objects.active = arm_obj
    arm_obj.select_set(True)

    bpy.ops.object.mode_set(mode='EDIT')

    ebs = {}
    for bd in bones_data:
        idx = bd['index']
        eb = arm.edit_bones.new(bd['name'])
        head = world_mats[idx].translation.copy()
        eb.head = head
        eb.tail = head + Vector((0, 0.01, 0))
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
            child_head = world_mats[kids[0]].translation
            direction = child_head - eb.head
            length = direction.length
            if length > 0.001:
                eb.tail = eb.head + direction.normalized() * length
            else:
                eb.tail = eb.head + y_axis * LEAF_BONE_LENGTH
        else:
            if y_axis.length > 0.001:
                eb.tail = eb.head + y_axis * LEAF_BONE_LENGTH
            else:
                eb.tail = eb.head + Vector((0, LEAF_BONE_LENGTH, 0))

        if (eb.tail - eb.head).length < 0.0001:
            eb.tail = eb.head + Vector((0, LEAF_BONE_LENGTH, 0))

        try:
            eb.align_roll(z_axis)
        except Exception:
            pass

    bpy.ops.object.mode_set(mode='OBJECT')

    arm_obj.show_in_front = True
    arm.display_type = 'STICK'

    print(f"  {n} bones built")
    return arm_obj


# ------------------------------------------------------------------
# Import Drogon
# ------------------------------------------------------------------

def is_half_mesh(obj):
    """Check if a mesh object is a half-mesh (asymmetric on X axis)."""
    if not obj.data.vertices:
        return False
    coords = [v.co.x for v in obj.data.vertices]
    x_min, x_max = min(coords), max(coords)
    x_span_neg = abs(x_min)
    x_span_pos = abs(x_max)
    denom = max(x_span_neg, x_span_pos, 0.001)
    ratio = min(x_span_neg, x_span_pos) / denom
    return ratio < 0.3


def is_body_part(obj):
    """Detect if this object is the main body (large, half-mesh).
    Body is typically the biggest half-mesh piece.
    Only the body should be mirrored — teeth, tongue, horns, eyes
    are either centered or already complete.
    """
    if not obj.data.vertices:
        return False
    # Must be a half-mesh to need mirroring
    if not is_half_mesh(obj):
        return False
    return True


def import_drogon():
    print("[3/5] Importing Drogon mesh (all parts)...")

    if not DROGON_OBJ.exists():
        raise FileNotFoundError(f"Drogon mesh not found: {DROGON_OBJ}")

    before = set(bpy.data.objects.keys())

    bpy.ops.wm.obj_import(
        filepath=str(DROGON_OBJ),
        forward_axis='NEGATIVE_Z',
        up_axis='Y',
    )

    after = set(bpy.data.objects.keys())
    new_names = after - before

    if not new_names:
        raise RuntimeError("OBJ import created no objects")

    # Collect all imported mesh objects
    imported_objs = []
    for name in sorted(new_names):
        obj = bpy.data.objects[name]
        if obj.type == 'MESH':
            imported_objs.append(obj)

    print(f"  Imported {len(imported_objs)} objects:")
    for obj in imported_objs:
        vc = len(obj.data.vertices)
        half = is_half_mesh(obj)
        print(f"    {obj.name}: {vc} verts {'(half-mesh)' if half else '(complete)'}")

    # Mirror only half-mesh body parts (not teeth, tongue, eyes, etc.)
    for obj in imported_objs:
        if is_body_part(obj):
            vert_before = len(obj.data.vertices)
            mirror = obj.modifiers.new(name='Mirror', type='MIRROR')
            mirror.use_axis[0] = True
            mirror.use_clip = True
            bpy.context.view_layer.objects.active = obj
            obj.select_set(True)
            bpy.ops.object.modifier_apply(modifier='Mirror')
            obj.select_set(False)
            vert_after = len(obj.data.vertices)
            print(f"    Mirrored '{obj.name}': {vert_before} -> {vert_after} verts")

    # Join all objects into one mesh
    print("  Joining all parts into single mesh...")

    bpy.ops.object.select_all(action='DESELECT')
    for obj in imported_objs:
        # Check object still exists (might have been consumed by join)
        if obj.name in bpy.data.objects:
            obj.select_set(True)

    # Set first object as active (join target)
    bpy.context.view_layer.objects.active = imported_objs[0]
    bpy.ops.object.join()

    # The active object is now the combined mesh
    drogon_obj = bpy.context.view_layer.objects.active
    drogon_obj.name = DROGON_NAME
    if drogon_obj.data:
        drogon_obj.data.name = DROGON_NAME

    total_verts = len(drogon_obj.data.vertices)
    print(f"  Combined '{DROGON_NAME}': {total_verts} total verts")

    return drogon_obj


# ------------------------------------------------------------------
# Position Drogon over armature
# ------------------------------------------------------------------

def get_armature_bbox(arm_obj):
    """Get bounding box from bone head/tail positions."""
    min_co = Vector((float('inf'), float('inf'), float('inf')))
    max_co = Vector((float('-inf'), float('-inf'), float('-inf')))

    for bone in arm_obj.data.bones:
        for pos in [arm_obj.matrix_world @ bone.head_local, arm_obj.matrix_world @ bone.tail_local]:
            min_co.x = min(min_co.x, pos.x)
            min_co.y = min(min_co.y, pos.y)
            min_co.z = min(min_co.z, pos.z)
            max_co.x = max(max_co.x, pos.x)
            max_co.y = max(max_co.y, pos.y)
            max_co.z = max(max_co.z, pos.z)

    return min_co, max_co


def get_mesh_bbox(obj):
    world = obj.matrix_world
    coords = [world @ v.co for v in obj.data.vertices]
    min_co = Vector((min(c.x for c in coords), min(c.y for c in coords), min(c.z for c in coords)))
    max_co = Vector((max(c.x for c in coords), max(c.y for c in coords), max(c.z for c in coords)))
    return min_co, max_co


def position_drogon(drogon_obj, arm_obj):
    """Scale and translate Drogon to cover the armature skeleton."""
    print("  Positioning Drogon over armature...")

    arm_min, arm_max = get_armature_bbox(arm_obj)
    arm_span = arm_max - arm_min
    arm_center = (arm_min + arm_max) / 2

    drogon_min, drogon_max = get_mesh_bbox(drogon_obj)
    drogon_span = drogon_max - drogon_min
    drogon_center = (drogon_min + drogon_max) / 2

    # Uniform scale to match armature extent
    arm_max_span = max(arm_span.x, arm_span.y, arm_span.z)
    drogon_max_span = max(drogon_span.x, drogon_span.y, drogon_span.z)

    if drogon_max_span < 0.001:
        raise RuntimeError("Drogon has zero extent")

    scale_factor = arm_max_span / drogon_max_span
    print(f"  Scale: {scale_factor:.4f} (arm span {arm_max_span:.2f} / drogon span {drogon_max_span:.2f})")

    drogon_obj.scale = (scale_factor, scale_factor, scale_factor)
    bpy.context.view_layer.objects.active = drogon_obj
    drogon_obj.select_set(True)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    drogon_obj.select_set(False)

    # Recompute bbox after scale
    drogon_min, drogon_max = get_mesh_bbox(drogon_obj)
    drogon_center = (drogon_min + drogon_max) / 2

    offset = arm_center - drogon_center
    drogon_obj.location += offset

    # Apply location
    bpy.context.view_layer.objects.active = drogon_obj
    drogon_obj.select_set(True)
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    drogon_obj.select_set(False)

    print(f"  Armature center: ({arm_center.x:.2f}, {arm_center.y:.2f}, {arm_center.z:.2f})")
    print(f"  Armature span:   ({arm_span.x:.2f}, {arm_span.y:.2f}, {arm_span.z:.2f})")


# ------------------------------------------------------------------
# Nearest-bone weight calculation
# ------------------------------------------------------------------

def closest_point_on_segment(p, a, b):
    """Find closest point on line segment a->b to point p. Returns (point, distance)."""
    ab = b - a
    ab_sq = ab.dot(ab)

    if ab_sq < 1e-12:
        # Degenerate bone (head == tail)
        return a.copy(), (p - a).length

    t = max(0.0, min(1.0, (p - a).dot(ab) / ab_sq))
    closest = a + ab * t
    return closest, (p - closest).length


def calculate_bone_weights(drogon_obj, arm_obj):
    """For every vertex, find nearest bones and assign weights by inverse distance."""
    print("[4/5] Calculating bone weights (nearest-bone distance)...")

    mesh = drogon_obj.data
    vert_count = len(mesh.vertices)

    # Collect all bone segments in world space
    bone_segments = []  # [(name, head_world, tail_world), ...]
    world_mat = arm_obj.matrix_world

    for bone in arm_obj.data.bones:
        head_w = world_mat @ bone.head_local
        tail_w = world_mat @ bone.tail_local
        bone_segments.append((bone.name, head_w, tail_w))

    bone_count = len(bone_segments)
    print(f"  {vert_count} vertices x {bone_count} bones = {vert_count * bone_count} distance checks")

    # Create vertex groups for all bones
    vgroups = {}
    for bone_name, _, _ in bone_segments:
        vg = drogon_obj.vertex_groups.new(name=bone_name)
        vgroups[bone_name] = vg

    # Process each vertex
    drogon_world = drogon_obj.matrix_world
    progress_step = max(1, vert_count // 20)

    for vi in range(vert_count):
        if vi % progress_step == 0:
            pct = vi * 100 // vert_count
            print(f"  {pct}% ({vi}/{vert_count})", end='\r')

        vert_world = drogon_world @ mesh.vertices[vi].co

        # Find distance to every bone segment
        distances = []
        for bi, (bone_name, head_w, tail_w) in enumerate(bone_segments):
            _, dist = closest_point_on_segment(vert_world, head_w, tail_w)
            distances.append((dist, bone_name))

        # Sort by distance, take closest N
        distances.sort(key=lambda x: x[0])
        closest = distances[:MAX_INFLUENCES]

        # Compute inverse-distance weights
        # Add small epsilon to avoid division by zero for vertices exactly on a bone
        epsilon = 1e-6
        raw_weights = []
        for dist, bone_name in closest:
            w = 1.0 / ((dist + epsilon) ** FALLOFF_POWER)
            raw_weights.append((w, bone_name))

        # Normalize so weights sum to 1.0
        total = sum(w for w, _ in raw_weights)
        if total > 0:
            for w, bone_name in raw_weights:
                normalized_w = w / total
                if normalized_w > 0.001:  # Skip negligible weights
                    vgroups[bone_name].add([vi], normalized_w, 'REPLACE')

    print(f"  100% ({vert_count}/{vert_count}) — done")
    print(f"  Assigned up to {MAX_INFLUENCES} bone influences per vertex")


# ------------------------------------------------------------------
# Parent to armature
# ------------------------------------------------------------------

def parent_to_armature(drogon_obj, arm_obj):
    print("[5/5] Parenting Drogon to armature...")

    drogon_obj.parent = arm_obj

    # Remove any existing armature modifier
    for mod in drogon_obj.modifiers:
        if mod.type == 'ARMATURE':
            drogon_obj.modifiers.remove(mod)

    mod = drogon_obj.modifiers.new(name='Armature', type='ARMATURE')
    mod.object = arm_obj

    print(f"  Parented with Armature modifier")


# ------------------------------------------------------------------
# Main
# ------------------------------------------------------------------

def main():
    print("=" * 60)
    print("  DROGON DIRECT RIG — CD Dragon Armature")
    print("  Pure Python bone weights (no auto-weights)")
    print("=" * 60)

    if bpy.context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    bpy.ops.object.select_all(action='DESELECT')

    # Load skeleton
    with open(str(SKELETON_JSON), 'r') as f:
        bones_data = json.load(f)
    print(f"\nLoaded {len(bones_data)} bones from skeleton")

    # Step 1: Cleanup
    cleanup_scene()

    # Step 2: Build armature
    arm_obj = build_armature(bones_data)

    # Step 3: Import Drogon
    drogon_obj = import_drogon()

    # Position Drogon over armature
    position_drogon(drogon_obj, arm_obj)

    # Step 4: Calculate and assign bone weights
    calculate_bone_weights(drogon_obj, arm_obj)

    # Step 5: Parent to armature
    parent_to_armature(drogon_obj, arm_obj)

    # Frame view
    bpy.ops.object.select_all(action='DESELECT')
    drogon_obj.select_set(True)
    bpy.context.view_layer.objects.active = drogon_obj

    for area in bpy.context.screen.areas:
        if area.type == 'VIEW_3D':
            for region in area.regions:
                if region.type == 'WINDOW':
                    with bpy.context.temp_override(area=area, region=region):
                        bpy.ops.view3d.view_all()
                    break
            break

    # Summary
    vert_count = len(drogon_obj.data.vertices)
    group_count = len(drogon_obj.vertex_groups)

    print("\n" + "=" * 60)
    print("  DROGON RIG COMPLETE")
    print("=" * 60)
    print(f"  Armature:    {ARMATURE_NAME} ({len(bones_data)} bones)")
    print(f"  Mesh:        {DROGON_NAME} ({vert_count} verts)")
    print(f"  Bone groups: {group_count}")
    print(f"  Influences:  {MAX_INFLUENCES} per vertex (inverse distance^{FALLOFF_POWER})")
    print("")
    print("  NEXT STEPS:")
    print("  1. Switch armature to Pose Mode, test bone rotations")
    print("  2. Adjust Drogon position/rotation if anatomy doesn't match")
    print("  3. Re-run weight calculation after repositioning")
    print("  4. Export to PAC format for game injection")
    print("=" * 60)


if __name__ == '__main__':
    main()
