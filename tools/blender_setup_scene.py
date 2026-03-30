"""
Blender Scene Setup for Crimson Desert Dragon Mesh Swap
========================================================
Run inside Blender: Text Editor > Open > Run Script

Sets up a complete working scene:
  1. Builds the CD dragon armature (274 bones from cd_skeleton.json)
  2. Imports CD bind-pose mesh from dragon_decoded.obj
  3. Imports Drogon mesh from DROGON.OBJ
  4. Auto-aligns Drogon to CD mesh via bounding box matching
  5. Adds Shrinkwrap modifier on CD mesh targeting Drogon

After running, you can interactively adjust Drogon's position/scale,
and the Shrinkwrap on CD_Mesh will update in real time.
"""

import bpy
import json
from pathlib import Path
from mathutils import Matrix, Vector

# ==================== CONFIGURATION ====================
ROOT = Path(r"C:\Users\waelj\got-dragon-cd-mod")
SKELETON_JSON = ROOT / "output" / "cd_skeleton.json"
CD_MESH_OBJ = ROOT / "output" / "dragon_decoded.obj"
DROGON_OBJ = Path(r"C:\Users\waelj\Desktop\Outputs\DROGON.OBJ")

SCALE = 4.0                # BaseCharacterScale from prefab
ARMATURE_NAME = "CD_Dragon"
CD_MESH_NAME = "CD_Mesh"
DROGON_NAME = "Drogon"
LEAF_BONE_LENGTH = 0.15    # Tail length for leaf bones (scaled units)
# =======================================================

# Y-up -> Z-up: rotate -90 deg around X axis
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
    """Remove previous objects/armatures with our names so the script is re-runnable."""
    print("[1/5] Cleaning up previous scene objects...")

    names_to_remove = [CD_MESH_NAME, DROGON_NAME, ARMATURE_NAME]

    for name in names_to_remove:
        if name in bpy.data.objects:
            obj = bpy.data.objects[name]
            bpy.data.objects.remove(obj, do_unlink=True)
            print(f"  Removed object: {name}")

    if ARMATURE_NAME in bpy.data.armatures:
        bpy.data.armatures.remove(bpy.data.armatures[ARMATURE_NAME])
        print(f"  Removed armature data: {ARMATURE_NAME}")

    # Also clean up orphan meshes with same names
    for name in [CD_MESH_NAME, DROGON_NAME]:
        if name in bpy.data.meshes:
            bpy.data.meshes.remove(bpy.data.meshes[name])
            print(f"  Removed mesh data: {name}")


# ------------------------------------------------------------------
# Armature builder (inline from build_armature.py)
# ------------------------------------------------------------------

def get_world_matrices(bones_data):
    """Read world matrices directly from PAB (1st matrix = armature-space).

    No accumulation needed -- the 1st matrix ("local_matrix" in JSON) is
    already the world/armature-space transform. Transpose for Blender.
    """
    blender_mats = []
    for b in bones_data:
        m = b['local_matrix']  # 1st PAB matrix = world transform
        # Transpose: DX row-vector -> Blender column-vector
        # Scale translation only
        bm = Matrix((
            (m[0][0], m[1][0], m[2][0], m[3][0] * SCALE),
            (m[0][1], m[1][1], m[2][1], m[3][1] * SCALE),
            (m[0][2], m[1][2], m[2][2], m[3][2] * SCALE),
            (m[0][3], m[1][3], m[2][3], m[3][3]),
        ))
        bm = AXIS_SWAP @ bm
        blender_mats.append(bm)

    return blender_mats


def build_armature():
    """Build the CD dragon armature from cd_skeleton.json (274 bones)."""
    print("[2/5] Building CD dragon armature...")

    with open(str(SKELETON_JSON), 'r') as f:
        bones_data = json.load(f)

    n = len(bones_data)
    print(f"  Loaded {n} bones from {SKELETON_JSON.name}")

    world_mats = get_world_matrices(bones_data)

    # Build children lookup
    children_of = {}
    for bd in bones_data:
        pid = bd['parent_index']
        if pid >= 0:
            children_of.setdefault(pid, []).append(bd['index'])

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
                eb.tail = eb.head + direction.normalized() * length
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

    # Display settings
    arm_obj.show_in_front = True
    arm.display_type = 'STICK'

    roots = sum(1 for bd in bones_data if bd['parent_index'] == -1)
    print(f"  Armature '{ARMATURE_NAME}': {n} bones, {roots} root(s)")

    return arm_obj


# ------------------------------------------------------------------
# Mesh importers
# ------------------------------------------------------------------

def import_cd_mesh():
    """Import CD dragon bind-pose mesh from OBJ, apply 4x scale, rename."""
    print("[3/5] Importing CD dragon mesh...")

    if not CD_MESH_OBJ.exists():
        raise FileNotFoundError(f"CD mesh not found: {CD_MESH_OBJ}")

    # Track existing objects to identify the new one
    before = set(bpy.data.objects.keys())

    bpy.ops.wm.obj_import(
        filepath=str(CD_MESH_OBJ),
        forward_axis='NEGATIVE_Z',
        up_axis='Y',
    )

    after = set(bpy.data.objects.keys())
    new_names = after - before

    if not new_names:
        raise RuntimeError("OBJ import did not create any new objects")

    # Get the imported object (take the first new one)
    imported_name = sorted(new_names)[0]
    cd_obj = bpy.data.objects[imported_name]
    cd_obj.name = CD_MESH_NAME
    if cd_obj.data:
        cd_obj.data.name = CD_MESH_NAME

    # Apply 4x scale to match armature
    cd_obj.scale = (SCALE, SCALE, SCALE)
    bpy.context.view_layer.objects.active = cd_obj
    cd_obj.select_set(True)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    cd_obj.select_set(False)

    vert_count = len(cd_obj.data.vertices)
    groups = [g.name for g in cd_obj.vertex_groups]
    print(f"  '{CD_MESH_NAME}': {vert_count} verts, {len(groups)} vertex groups")
    if groups:
        print(f"  Groups: {', '.join(groups)}")

    # Print bounding box
    bbox = get_world_bbox(cd_obj)
    print(f"  BBox: X[{bbox['min'].x:.2f}, {bbox['max'].x:.2f}] "
          f"Y[{bbox['min'].y:.2f}, {bbox['max'].y:.2f}] "
          f"Z[{bbox['min'].z:.2f}, {bbox['max'].z:.2f}]")

    return cd_obj


def import_drogon():
    """Import Drogon mesh from OBJ, rename."""
    print("[4/5] Importing Drogon mesh...")

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
        raise RuntimeError("OBJ import did not create any new objects")

    imported_name = sorted(new_names)[0]
    drogon_obj = bpy.data.objects[imported_name]
    drogon_obj.name = DROGON_NAME
    if drogon_obj.data:
        drogon_obj.data.name = DROGON_NAME

    vert_count = len(drogon_obj.data.vertices)
    print(f"  '{DROGON_NAME}': {vert_count} verts")

    # Drogon is a half-mesh — mirror across X to get the full dragon
    bbox = get_world_bbox(drogon_obj)
    x_min, x_max = bbox['min'].x, bbox['max'].x
    x_span_neg = abs(x_min)
    x_span_pos = abs(x_max)

    # If one side has much less extent than the other, it's a half-mesh
    ratio = min(x_span_neg, x_span_pos) / max(x_span_neg, x_span_pos, 0.001)
    if ratio < 0.3:
        print(f"  Detected half-mesh (X ratio={ratio:.2f}), adding Mirror modifier...")
        mirror = drogon_obj.modifiers.new(name='Mirror', type='MIRROR')
        mirror.use_axis[0] = True  # Mirror X
        mirror.use_clip = True
        bpy.context.view_layer.objects.active = drogon_obj
        drogon_obj.select_set(True)
        bpy.ops.object.modifier_apply(modifier='Mirror')
        drogon_obj.select_set(False)
        new_count = len(drogon_obj.data.vertices)
        print(f"  Mirrored: {vert_count} -> {new_count} verts")

    bbox = get_world_bbox(drogon_obj)
    print(f"  BBox: X[{bbox['min'].x:.2f}, {bbox['max'].x:.2f}] "
          f"Y[{bbox['min'].y:.2f}, {bbox['max'].y:.2f}] "
          f"Z[{bbox['min'].z:.2f}, {bbox['max'].z:.2f}]")

    return drogon_obj


# ------------------------------------------------------------------
# Auto-alignment
# ------------------------------------------------------------------

def get_world_bbox(obj):
    """Compute world-space axis-aligned bounding box for a mesh object."""
    # Ensure depsgraph is up to date
    depsgraph = bpy.context.evaluated_depsgraph_get()
    eval_obj = obj.evaluated_get(depsgraph)
    mesh = eval_obj.data

    if not mesh.vertices:
        raise RuntimeError(f"Object '{obj.name}' has no vertices")

    world_mat = obj.matrix_world
    verts_world = [world_mat @ v.co for v in mesh.vertices]

    min_co = Vector((
        min(v.x for v in verts_world),
        min(v.y for v in verts_world),
        min(v.z for v in verts_world),
    ))
    max_co = Vector((
        max(v.x for v in verts_world),
        max(v.y for v in verts_world),
        max(v.z for v in verts_world),
    ))

    return {'min': min_co, 'max': max_co}


def auto_align_drogon(cd_obj, drogon_obj):
    """Scale and translate Drogon to match CD mesh bounding box."""
    print("  Auto-aligning Drogon to CD mesh...")

    cd_bbox = get_world_bbox(cd_obj)
    drogon_bbox = get_world_bbox(drogon_obj)

    # Compute spans
    cd_span = cd_bbox['max'] - cd_bbox['min']
    drogon_span = drogon_bbox['max'] - drogon_bbox['min']

    # Uniform scale based on largest CD span / largest Drogon span
    cd_max_span = max(cd_span.x, cd_span.y, cd_span.z)
    drogon_max_span = max(drogon_span.x, drogon_span.y, drogon_span.z)

    if drogon_max_span < 0.001:
        raise RuntimeError("Drogon mesh has zero extent")

    scale_factor = cd_max_span / drogon_max_span
    print(f"  Scale factor: {scale_factor:.6f} (CD span {cd_max_span:.2f} / Drogon span {drogon_max_span:.2f})")

    # Apply uniform scale
    drogon_obj.scale = (scale_factor, scale_factor, scale_factor)

    # We need to apply the scale first, then compute the new bbox for translation
    bpy.context.view_layer.objects.active = drogon_obj
    drogon_obj.select_set(True)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    drogon_obj.select_set(False)

    # Recompute Drogon bbox after scaling
    drogon_bbox = get_world_bbox(drogon_obj)
    drogon_center = (drogon_bbox['min'] + drogon_bbox['max']) / 2
    cd_center = (cd_bbox['min'] + cd_bbox['max']) / 2

    # Translate Drogon center to CD center
    offset = cd_center - drogon_center
    drogon_obj.location = drogon_obj.location + offset

    print(f"  CD center:     ({cd_center.x:.2f}, {cd_center.y:.2f}, {cd_center.z:.2f})")
    print(f"  Drogon offset: ({offset.x:.2f}, {offset.y:.2f}, {offset.z:.2f})")

    # Display Drogon as wireframe for visual clarity
    drogon_obj.display_type = 'WIRE'
    print(f"  Drogon display set to wireframe")


# ------------------------------------------------------------------
# Shrinkwrap
# ------------------------------------------------------------------

def add_shrinkwrap(cd_obj, drogon_obj):
    """Add Shrinkwrap modifier to CD_Mesh targeting Drogon."""
    print("[5/5] Adding Shrinkwrap modifier...")

    # Remove existing shrinkwrap if re-running
    for mod in cd_obj.modifiers:
        if mod.type == 'SHRINKWRAP' and mod.name == 'Shrinkwrap_Drogon':
            cd_obj.modifiers.remove(mod)
            break

    sw = cd_obj.modifiers.new(name='Shrinkwrap_Drogon', type='SHRINKWRAP')
    sw.target = drogon_obj
    sw.wrap_method = 'NEAREST_SURFACEPOINT'
    sw.wrap_mode = 'ON_SURFACE'

    print(f"  Shrinkwrap 'Shrinkwrap_Drogon' added to '{CD_MESH_NAME}'")
    print(f"    Target: {DROGON_NAME}")
    print(f"    Method: NEAREST_SURFACEPOINT")
    print(f"    Mode:   ON_SURFACE")
    print(f"    Status: UNAPPLIED (live preview)")


# ------------------------------------------------------------------
# Main
# ------------------------------------------------------------------

def main():
    print("=" * 60)
    print("  Crimson Desert Dragon Mesh Swap - Scene Setup")
    print("=" * 60)

    # Ensure we are in object mode
    if bpy.context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')

    # Deselect all
    bpy.ops.object.select_all(action='DESELECT')

    # Step 1: Cleanup
    cleanup_scene()

    # Step 2: Build armature
    arm_obj = build_armature()

    # Step 3: Import CD mesh
    cd_obj = import_cd_mesh()

    # Step 4: Import Drogon and auto-align
    drogon_obj = import_drogon()
    auto_align_drogon(cd_obj, drogon_obj)

    # Step 5: Shrinkwrap
    add_shrinkwrap(cd_obj, drogon_obj)

    # Final: select CD mesh and frame view
    bpy.ops.object.select_all(action='DESELECT')
    cd_obj.select_set(True)
    bpy.context.view_layer.objects.active = cd_obj

    # Frame all objects in viewport
    for area in bpy.context.screen.areas:
        if area.type == 'VIEW_3D':
            for region in area.regions:
                if region.type == 'WINDOW':
                    with bpy.context.temp_override(area=area, region=region):
                        bpy.ops.view3d.view_all()
                    break
            break

    # Summary
    print("")
    print("=" * 60)
    print("  SCENE SETUP COMPLETE")
    print("=" * 60)
    print(f"  Armature:  {ARMATURE_NAME} (274 bones)")
    print(f"  CD Mesh:   {CD_MESH_NAME} (bind-pose, 4x scaled)")
    print(f"  Drogon:    {DROGON_NAME} (auto-aligned, wireframe)")
    print(f"  Modifier:  Shrinkwrap on {CD_MESH_NAME} -> {DROGON_NAME}")
    print("")
    print("  NEXT STEPS:")
    print("  1. Visually inspect alignment - select Drogon and adjust")
    print("     position/rotation/scale as needed (Shrinkwrap updates live)")
    print("  2. Consider parenting CD_Mesh to armature (Ctrl+P > Armature Deform)")
    print("  3. When satisfied, apply the Shrinkwrap modifier")
    print("  4. Run the export script to encode back to PAC format")
    print("=" * 60)


if __name__ == '__main__':
    main()
