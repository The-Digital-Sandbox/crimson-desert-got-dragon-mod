"""
Decimate Drogon to exact CD Dragon vertex counts per submesh.
==============================================================
Run inside Blender with the DrogonRigged-correctweights scene open.

Scene must have:
  - "Drogon" mesh object with 8 materials (CD_M0004_00_Dragon_*)
  - "CD_Dragon" armature (274 bones)

This script:
  1. Separates mesh by material into 8 objects
  2. Decimates each to exact CD target vertex count
  3. Rejoins into single mesh (preserving material order)
  4. Exports GLB with armature + skinning

Output: output/DrogonRigged-correctweights.glb
"""

import bpy
import bmesh
from pathlib import Path

ROOT = Path(r"C:\Users\user\crimson-desert-got-dragon-mod")
OUTPUT_GLB = str(ROOT / "output" / "DrogonRigged-correctweights.glb")

# Submesh order MUST match CD PAC order and material slot order
SUBMESH_MATERIALS = [
    "CD_M0004_00_Dragon_Eyeright_0001",
    "CD_M0004_00_Dragon_Eyeleft_0001",
    "CD_M0004_00_Dragon_Body_0001_02",
    "CD_M0004_00_Dragon_back_0001",
    "CD_M0004_00_Dragon_Body_0001",
    "CD_M0004_00_Dragon_Leg_0001",
    "CD_M0004_00_Dragon_Wing_0001",
    "CD_M0004_00_Dragon_Head_0001",
]

TARGET_VERTS = [225, 225, 2013, 3307, 2736, 4624, 6724, 10258]

ARMATURE_NAME = "CD_Dragon"
MESH_NAME = "Drogon"


def find_mesh():
    """Find the Drogon mesh object by name, then by material."""
    obj = bpy.data.objects.get(MESH_NAME)
    if obj and obj.type == 'MESH':
        return obj
    # Fallback: find any mesh with CD_M0004 materials
    for obj in bpy.data.objects:
        if obj.type == 'MESH' and any(
            m and m.name.startswith("CD_M0004") for m in obj.data.materials
        ):
            return obj
    return None


def find_armature():
    """Find the CD_Dragon armature."""
    arm = bpy.data.objects.get(ARMATURE_NAME)
    if arm and arm.type == 'ARMATURE':
        return arm
    for obj in bpy.data.objects:
        if obj.type == 'ARMATURE':
            return obj
    return None


def separate_by_material(obj):
    """
    Separate mesh by material into individual objects.
    Returns dict: material_name -> object.
    """
    # Duplicate so we don't destroy the original
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.duplicate()
    dup = bpy.context.active_object
    dup.name = "Drogon_decimate_work"

    # Separate by material
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.mesh.separate(type='MATERIAL')
    bpy.ops.object.mode_set(mode='OBJECT')

    # Collect results keyed by material name
    parts = {}
    for o in list(bpy.data.objects):
        if not o.name.startswith("Drogon_decimate_work"):
            continue
        if o.type != 'MESH':
            continue
        if not o.data.materials:
            continue
        mat_name = o.data.materials[0].name
        parts[mat_name] = o
        print(f"    Separated: {mat_name} -> {len(o.data.vertices)} verts")

    return parts


def decimate_to_target(obj, target):
    """Decimate object to exact target vertex count. Returns final count."""
    current = len(obj.data.vertices)
    print(f"    {current} -> {target}", end="")

    if current == target:
        print(" (already exact)")
        return current

    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj

    # If we need MORE verts, subdivide first
    if current < target:
        while len(obj.data.vertices) < target:
            mod = obj.modifiers.new(name="Subdiv", type='SUBSURF')
            mod.levels = 1
            bpy.ops.object.modifier_apply(modifier=mod.name)
        current = len(obj.data.vertices)
        if current == target:
            print(f" -> {current} (subdiv exact)")
            return current

    # Binary search for decimate ratio
    lo, hi = 0.0, 1.0
    best_ratio = target / current
    best_diff = abs(current - target)

    for iteration in range(60):
        mid = (lo + hi) / 2.0

        mod = obj.modifiers.new(name="Dec", type='DECIMATE')
        mod.decimate_type = 'COLLAPSE'
        mod.ratio = mid

        depsgraph = bpy.context.evaluated_depsgraph_get()
        eval_obj = obj.evaluated_get(depsgraph)
        eval_mesh = eval_obj.to_mesh()
        result_verts = len(eval_mesh.vertices)
        eval_obj.to_mesh_clear()
        obj.modifiers.remove(mod)

        diff = result_verts - target
        if abs(diff) < best_diff:
            best_diff = abs(diff)
            best_ratio = mid

        if result_verts == target:
            best_ratio = mid
            break
        elif result_verts > target:
            hi = mid
        else:
            lo = mid

    # Apply best ratio
    mod = obj.modifiers.new(name="Dec", type='DECIMATE')
    mod.decimate_type = 'COLLAPSE'
    mod.ratio = best_ratio
    bpy.ops.object.modifier_apply(modifier=mod.name)
    current = len(obj.data.vertices)

    # Fine-tune with bmesh if not exact
    if current != target:
        bm = bmesh.new()
        bm.from_mesh(obj.data)
        bm.verts.ensure_lookup_table()
        bm.edges.ensure_lookup_table()

        if current > target:
            to_remove = current - target
            for _ in range(to_remove):
                bm.edges.ensure_lookup_table()
                if not bm.edges:
                    break
                shortest = min(bm.edges, key=lambda e: e.calc_length())
                bmesh.ops.collapse(bm, edges=[shortest])
                bm.verts.ensure_lookup_table()
        elif current < target:
            to_add = target - current
            for _ in range(to_add):
                bm.edges.ensure_lookup_table()
                if not bm.edges:
                    break
                longest = max(bm.edges, key=lambda e: e.calc_length())
                bmesh.ops.subdivide_edges(bm, edges=[longest], cuts=1)
                bm.verts.ensure_lookup_table()

        bm.to_mesh(obj.data)
        bm.free()
        current = len(obj.data.vertices)

    status = "OK" if current == target else f"MISMATCH ({current})"
    print(f" -> {current} [{status}]")
    return current


def rejoin_and_export(parts, armature):
    """
    Rejoin separated parts into single mesh in correct material order,
    parent to armature, and export GLB.
    """
    # Deselect all
    bpy.ops.object.select_all(action='DESELECT')

    # Join parts in material order
    joined = None
    for mat_name in SUBMESH_MATERIALS:
        obj = parts.get(mat_name)
        if not obj:
            print(f"  WARNING: {mat_name} missing, skipping")
            continue
        obj.select_set(True)
        if joined is None:
            bpy.context.view_layer.objects.active = obj
            joined = obj

    if not joined:
        print("ERROR: No parts to join")
        return

    # Join all selected into active
    bpy.ops.object.join()
    joined = bpy.context.active_object
    joined.name = "Drogon_decimated"

    # Ensure material slots are in correct order
    # After join, materials should be in order of the objects joined
    print(f"\n  Joined mesh: {len(joined.data.vertices)} verts, "
          f"{len(joined.data.materials)} materials")
    for i, m in enumerate(joined.data.materials):
        print(f"    Slot {i}: {m.name if m else 'None'}")

    # Parent to armature with armature modifier
    if armature:
        joined.parent = armature
        # Add armature modifier if not present
        has_arm_mod = any(m.type == 'ARMATURE' for m in joined.modifiers)
        if not has_arm_mod:
            mod = joined.modifiers.new(name="Armature", type='ARMATURE')
            mod.object = armature

    # Select armature + mesh for export
    bpy.ops.object.select_all(action='DESELECT')
    joined.select_set(True)
    if armature:
        armature.select_set(True)
    bpy.context.view_layer.objects.active = joined

    # Export GLB
    bpy.ops.export_scene.gltf(
        filepath=OUTPUT_GLB,
        export_format='GLB',
        use_selection=True,
        export_yup=True,
        export_skins=True,
        export_all_influences=False,
        export_animations=False,
        export_morph=False,
        export_lights=False,
        export_cameras=False,
    )
    print(f"\n  Exported GLB: {OUTPUT_GLB}")


def cleanup():
    """Remove temporary objects."""
    to_delete = [o for o in bpy.data.objects
                 if o.name.startswith("Drogon_decimate_work") or
                    o.name == "Drogon_decimated"]
    for o in to_delete:
        bpy.data.objects.remove(o, do_unlink=True)


def main():
    print("=" * 60)
    print("  DROGON DECIMATION -> CD VERTEX COUNTS")
    print("=" * 60)

    mesh_obj = find_mesh()
    if not mesh_obj:
        print("ERROR: No Drogon mesh found!")
        return
    print(f"\n  Mesh: {mesh_obj.name} ({len(mesh_obj.data.vertices)} verts)")

    armature = find_armature()
    if armature:
        print(f"  Armature: {armature.name} ({len(armature.data.bones)} bones)")
    else:
        print("  WARNING: No armature found, GLB will have no skinning")

    # Print current material slots
    print(f"\n  Material slots ({len(mesh_obj.data.materials)}):")
    for i, m in enumerate(mesh_obj.data.materials):
        print(f"    {i}: {m.name if m else 'None'}")

    # Step 1: Separate
    print("\n--- SEPARATE BY MATERIAL ---")
    parts = separate_by_material(mesh_obj)

    # Verify all 8 materials found
    missing = [m for m in SUBMESH_MATERIALS if m not in parts]
    if missing:
        print(f"\n  ERROR: Missing materials: {missing}")
        print(f"  Found: {list(parts.keys())}")
        # Cleanup before aborting
        for o in parts.values():
            bpy.data.objects.remove(o, do_unlink=True)
        return

    # Step 2: Decimate each
    print("\n--- DECIMATE ---")
    all_ok = True
    for i, mat_name in enumerate(SUBMESH_MATERIALS):
        target = TARGET_VERTS[i]
        short_name = mat_name.split("Dragon_")[1] if "Dragon_" in mat_name else mat_name
        print(f"  {short_name}:", end="")
        result = decimate_to_target(parts[mat_name], target)
        if result != target:
            all_ok = False

    # Step 3: Recalc normals
    print("\n--- RECALC NORMALS ---")
    for mat_name in SUBMESH_MATERIALS:
        obj = parts[mat_name]
        bpy.ops.object.select_all(action='DESELECT')
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_all(action='SELECT')
        bpy.ops.mesh.normals_make_consistent(inside=False)
        bpy.ops.object.mode_set(mode='OBJECT')

    # Step 4: Rejoin & export GLB
    print("\n--- REJOIN & EXPORT GLB ---")
    rejoin_and_export(parts, armature)

    # Summary
    total_target = sum(TARGET_VERTS)
    print("\n" + "=" * 60)
    if all_ok:
        print(f"  SUCCESS - {total_target} verts, exported to:")
    else:
        print(f"  PARTIAL - some submeshes off target, exported to:")
    print(f"  {OUTPUT_GLB}")
    print("=" * 60)

    print("\n  Next: python tools/build_pac_from_glb.py")
    print("  Then: python tools/deploy_new_pac.py")


if __name__ == '__main__':
    main()
