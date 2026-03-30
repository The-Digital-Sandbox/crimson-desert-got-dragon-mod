# Blender Shrinkwrap Mesh Swap Pipeline — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build two Blender scripts — one to set up a scene with CD armature + mesh + aligned Drogon + live shrinkwrap, and one to export the modified mesh back to PAC format.

**Architecture:** Script 1 (`blender_setup_scene.py`) creates the full working scene: builds the CD armature, imports the CD bind-pose mesh (4x scaled, axis-swapped to match), imports Drogon, auto-aligns it via bounding box matching, and adds a Shrinkwrap modifier. Script 2 (`blender_export_pac.py`) reads the post-shrinkwrap vertex positions, reverses the coordinate transform, and patches the original PAC file with new positions, normals, and bounding boxes.

**Tech Stack:** Blender Python API (bpy), existing `pac_codec.py` and `pac_patcher.py` for PAC I/O.

**Spec:** `docs/superpowers/specs/2026-03-30-blender-shrinkwrap-pipeline-design.md`

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `tools/blender_setup_scene.py` | Create | Scene setup: armature + CD mesh + Drogon + alignment + shrinkwrap |
| `tools/blender_export_pac.py` | Create | Export: read Blender mesh → reverse transform → patch PAC |
| `tools/build_armature.py` | Existing | Armature builder (called by setup script) |
| `tools/pac_codec.py` | Existing | PAC format codec (used by export script) |
| `tools/pac_patcher.py` | Existing | PAC patching + deployment (used by export script) |

---

### Task 1: Scene Setup Script — Armature + CD Mesh Import

**Files:**
- Create: `tools/blender_setup_scene.py`
- Reference: `tools/build_armature.py` (armature creation logic)
- Reference: `output/dragon_decoded.obj` (CD bind-pose mesh, 30,112 verts, 8 groups, Y-up model space)

- [ ] **Step 1: Create `blender_setup_scene.py` with armature + CD mesh import**

The script reuses `build_armature.py`'s logic inline (since Blender scripts can't easily import from sibling files), then imports the CD mesh OBJ with matching transforms.

Key coordinate facts:
- CD OBJ is in game model space: Y-up, no scale. Spans: X=[-4.92, 1.99], Y=[0.69, 2.11], Z=[-3.64, 10.56]
- Armature is in Blender space: Z-up, 4x scaled
- CD mesh needs: multiply by 4, then axis swap (X→X, Y→Z, Z→-Y) to match armature

Blender's OBJ importer has `forward_axis` and `up_axis` params. Import with `up_axis='Y'` to tell Blender the OBJ is Y-up, which auto-converts to Blender's Z-up. Then scale 4x.

```python
"""
Blender Scene Setup for CD Dragon Mesh Swap
=============================================
Run in Blender: Text Editor > Open > Run Script

Creates:
1. CD Dragon armature (274 bones)
2. CD bind-pose mesh (30,112 verts, matched to armature)
3. Drogon mesh (auto-aligned to CD)
4. Shrinkwrap modifier on CD mesh targeting Drogon

After running, adjust Drogon's position/scale as needed,
then Apply the Shrinkwrap modifier when satisfied.
"""

import bpy
import json
import struct
from mathutils import Matrix, Vector
from pathlib import Path

# ==================== CONFIGURATION ====================
ROOT = Path(r"C:\Users\waelj\got-dragon-cd-mod")
SKELETON_JSON = ROOT / "output" / "cd_skeleton.json"
CD_MESH_OBJ = ROOT / "output" / "dragon_decoded.obj"
DROGON_OBJ = Path(r"C:\Users\waelj\Desktop\Outputs\DROGON.OBJ")
SCALE = 4.0
ARMATURE_NAME = "CD_Dragon"
CD_MESH_NAME = "CD_Mesh"
DROGON_NAME = "Drogon"
LEAF_BONE_LENGTH = 0.15
# =======================================================

AXIS_SWAP = Matrix((
    (1,  0,  0, 0),
    (0,  0, -1, 0),
    (0,  1,  0, 0),
    (0,  0,  0, 1),
))


def cleanup_scene():
    """Remove existing objects from previous runs."""
    for name in [ARMATURE_NAME, CD_MESH_NAME, DROGON_NAME]:
        if name in bpy.data.objects:
            bpy.data.objects.remove(bpy.data.objects[name], do_unlink=True)
    for name in [ARMATURE_NAME]:
        if name in bpy.data.armatures:
            bpy.data.armatures.remove(bpy.data.armatures[name])
    # Clean orphan meshes
    for mesh in bpy.data.meshes:
        if mesh.users == 0:
            bpy.data.meshes.remove(mesh)


def build_armature():
    """Build CD dragon armature from skeleton JSON. Returns (armature_obj, world_mats)."""
    with open(str(SKELETON_JSON), 'r') as f:
        bones_data = json.load(f)

    n = len(bones_data)

    # Compute Blender world matrices (1st PAB matrix = world, transposed, scaled, axis-swapped)
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
            if direction.length > 0.001:
                eb.tail = eb.head + direction.normalized() * direction.length
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

    print(f"Armature: {n} bones")
    return arm_obj, world_mats


def import_cd_mesh():
    """Import CD bind-pose mesh OBJ, apply 4x scale and axis conversion."""
    bpy.ops.wm.obj_import(
        filepath=str(CD_MESH_OBJ),
        forward_axis='NEGATIVE_Z',
        up_axis='Y',
    )
    cd_obj = bpy.context.selected_objects[0]
    cd_obj.name = CD_MESH_NAME
    cd_obj.data.name = CD_MESH_NAME

    # Apply 4x scale
    cd_obj.scale = (SCALE, SCALE, SCALE)
    bpy.context.view_layer.objects.active = cd_obj
    bpy.ops.object.transform_apply(scale=True)

    print(f"CD mesh: {len(cd_obj.data.vertices)} verts")
    return cd_obj


def import_drogon():
    """Import Drogon mesh OBJ."""
    bpy.ops.wm.obj_import(
        filepath=str(DROGON_OBJ),
        forward_axis='NEGATIVE_Z',
        up_axis='Y',
    )
    drogon_obj = bpy.context.selected_objects[0]
    drogon_obj.name = DROGON_NAME
    drogon_obj.data.name = DROGON_NAME

    print(f"Drogon: {len(drogon_obj.data.vertices)} verts")
    return drogon_obj


def get_mesh_bounds(obj):
    """Get world-space bounding box of a mesh object."""
    coords = [obj.matrix_world @ v.co for v in obj.data.vertices]
    xs = [c.x for c in coords]
    ys = [c.y for c in coords]
    zs = [c.z for c in coords]
    return (
        Vector((min(xs), min(ys), min(zs))),
        Vector((max(xs), max(ys), max(zs))),
    )


def align_drogon_to_cd(drogon_obj, cd_obj):
    """Auto-align Drogon to CD mesh via bounding box matching."""
    cd_min, cd_max = get_mesh_bounds(cd_obj)
    cd_center = (cd_min + cd_max) / 2
    cd_span = cd_max - cd_min

    dr_min, dr_max = get_mesh_bounds(drogon_obj)
    dr_center = (dr_min + dr_max) / 2
    dr_span = dr_max - dr_min

    print(f"CD bounds:     span=({cd_span.x:.1f}, {cd_span.y:.1f}, {cd_span.z:.1f})")
    print(f"Drogon bounds: span=({dr_span.x:.1f}, {dr_span.y:.1f}, {dr_span.z:.1f})")

    # Uniform scale: match the largest axis (wingspan)
    # Both should have X as wingspan after import
    scale_factor = max(cd_span.x, cd_span.y, cd_span.z) / max(dr_span.x, dr_span.y, dr_span.z)
    drogon_obj.scale = (scale_factor, scale_factor, scale_factor)

    # Apply scale so bounds recalculate
    bpy.context.view_layer.objects.active = drogon_obj
    bpy.ops.object.transform_apply(scale=True)

    # Recompute bounds after scale
    dr_min, dr_max = get_mesh_bounds(drogon_obj)
    dr_center = (dr_min + dr_max) / 2

    # Translate center to match
    offset = cd_center - dr_center
    drogon_obj.location = offset

    print(f"Scale factor: {scale_factor:.6f}")
    print(f"Offset: ({offset.x:.2f}, {offset.y:.2f}, {offset.z:.2f})")


def setup_shrinkwrap(cd_obj, drogon_obj):
    """Add Shrinkwrap modifier to CD mesh targeting Drogon."""
    mod = cd_obj.modifiers.new(name="Shrinkwrap", type='SHRINKWRAP')
    mod.target = drogon_obj
    mod.wrap_method = 'NEAREST_SURFACEPOINT'
    mod.wrap_mode = 'ON_SURFACE'
    print("Shrinkwrap modifier added (not applied — adjust Drogon, then Apply)")


def main():
    print("=" * 60)
    print("CD DRAGON MESH SWAP — BLENDER SCENE SETUP")
    print("=" * 60)

    cleanup_scene()

    print("\n[1/5] Building armature...")
    arm_obj, world_mats = build_armature()

    print("\n[2/5] Importing CD mesh...")
    cd_obj = import_cd_mesh()

    print("\n[3/5] Importing Drogon...")
    drogon_obj = import_drogon()

    print("\n[4/5] Aligning Drogon to CD mesh...")
    align_drogon_to_cd(drogon_obj, cd_obj)

    print("\n[5/5] Adding Shrinkwrap modifier...")
    setup_shrinkwrap(cd_obj, drogon_obj)

    # Set display modes
    drogon_obj.display_type = 'WIRE'

    # Deselect all, select CD mesh
    bpy.ops.object.select_all(action='DESELECT')
    cd_obj.select_set(True)
    bpy.context.view_layer.objects.active = cd_obj

    print("\n" + "=" * 60)
    print("DONE. Scene ready:")
    print(f"  Armature: {ARMATURE_NAME} (stick, x-ray)")
    print(f"  CD Mesh:  {CD_MESH_NAME} (with Shrinkwrap modifier)")
    print(f"  Drogon:   {DROGON_NAME} (wireframe)")
    print()
    print("Next steps:")
    print("  1. Adjust Drogon position/scale (G, R, S keys)")
    print("  2. Check shrinkwrap preview on CD mesh")
    print("  3. When satisfied: select CD mesh → Modifiers → Apply Shrinkwrap")
    print("  4. Run blender_export_pac.py to write PAC file")
    print("=" * 60)


if __name__ == '__main__':
    main()
```

- [ ] **Step 2: Run in Blender to verify scene setup**

Open Blender, go to Text Editor > Open > navigate to `tools/blender_setup_scene.py` > Run Script.

Expected: console prints all 5 steps, scene shows armature (black sticks) + CD mesh (solid) + Drogon (wireframe, overlapping CD mesh) + Shrinkwrap modifier visible in properties panel. Moving Drogon updates CD mesh in real-time.

- [ ] **Step 3: Commit**

```bash
cd C:\Users\waelj\got-dragon-cd-mod
git add tools/blender_setup_scene.py
git commit -m "feat: add Blender scene setup script for mesh swap"
```

---

### Task 2: Export Script — Read Blender Mesh and Write PAC

**Files:**
- Create: `tools/blender_export_pac.py`
- Reference: `tools/pac_codec.py` — `VB_START=0x7BFA`, `STRIDE=40`, `SUBMESH_NAMES`, `SUBMESH_VERTEX_COUNTS`, `SUBMESH_BASES`, `quantize_pos()`, `encode_normal_r10g10b10a2()`, `SubmeshBbox`
- Reference: `tools/pac_patcher.py` — `find_bbox_offsets()`, `deploy_pac()`
- Reference: `output/dragon.pac` — original PAC file (template, 5,208,284 bytes)

- [ ] **Step 1: Create `blender_export_pac.py`**

This script runs inside Blender after the user has applied the Shrinkwrap modifier. It:
1. Reads vertex positions from the CD mesh object in Blender
2. Reverses the axis swap and 4x scale to get PAC model-space coordinates
3. Groups vertices by submesh (using Blender vertex groups from OBJ import)
4. Computes new bounding boxes per submesh
5. Quantizes positions and encodes normals
6. Patches the original PAC with new data
7. Writes `output/dragon_drogon_blender.pac`

```python
"""
Blender PAC Exporter for CD Dragon Mesh Swap
==============================================
Run in Blender AFTER applying the Shrinkwrap modifier on CD_Mesh.

Reads modified vertex positions from Blender, reverses the coordinate
transform, and writes a patched PAC file with new positions and normals.
"""

import bpy
import struct
import math
from pathlib import Path
from mathutils import Vector

# ==================== CONFIGURATION ====================
ROOT = Path(r"C:\Users\waelj\got-dragon-cd-mod")
ORIGINAL_PAC = ROOT / "output" / "dragon.pac"
OUTPUT_PAC = ROOT / "output" / "dragon_drogon_blender.pac"
OUTPUT_OBJ = ROOT / "output" / "dragon_drogon_blender.obj"
CD_MESH_NAME = "CD_Mesh"
SCALE = 4.0
DEPLOY = False  # Set True to deploy to game files
# =======================================================

# PAC constants (from pac_codec.py)
VB_START = 0x7BFA
STRIDE = 40
SUBMESH_NAMES = ["Eyeright", "Eyeleft", "Body_02", "back", "Body", "Leg", "Wing", "Head"]
SUBMESH_VERTEX_COUNTS = [225, 225, 2013, 3307, 2736, 4624, 6724, 10258]
TOTAL_VERTS = 30112

SUBMESH_BASES = []
_base = 0
for vc in SUBMESH_VERTEX_COUNTS:
    SUBMESH_BASES.append(_base)
    _base += vc


def find_bbox_offsets(pac):
    """Find byte offset of each submesh's 8-float bbox block in PAC."""
    offsets = []
    off = 0x0077
    for i in range(8):
        name_len = pac[off]
        off += 1 + name_len
        mat_len = pac[off]
        off += 1 + mat_len
        off += 3  # flag bytes
        offsets.append(off)
        off += 32
        next_cd = pac.find(b'CD_M0004', off)
        if next_cd > 0 and next_cd < 0x0441:
            off = next_cd - 1
        else:
            off = 0x0441
    return offsets


def quantize_pos(x, y, z, bbox_min, bbox_dim):
    """Quantize float position to uint16 using bounding box."""
    def q(val, bmin, bdim):
        if abs(bdim) < 1e-10:
            return 0
        return max(0, min(65535, int(round((val - bmin) / bdim * 32767.0))))
    return (q(x, bbox_min[0], bbox_dim[0]),
            q(y, bbox_min[1], bbox_dim[1]),
            q(z, bbox_min[2], bbox_dim[2]))


def encode_normal_r10g10b10a2(nx, ny, nz):
    """Encode normal vector to R10G10B10A2 packed uint32."""
    def clamp_encode(v):
        return max(0, min(1023, int(round((v + 1.0) / 2.0 * 1023.0))))
    return clamp_encode(nx) | (clamp_encode(ny) << 10) | (clamp_encode(nz) << 20)


def blender_to_model_space(co):
    """Convert Blender world coordinate (Z-up, 4x) to PAC model space (Y-up, 1x).

    Blender: X→X, Y→-Z_game, Z→Y_game  (from AXIS_SWAP matrix)
    Reverse: X→X, Y→Z_blender, Z→-Y_blender
    Then divide by SCALE.
    """
    return (
        co.x / SCALE,       # game X = blender X
        co.z / SCALE,       # game Y = blender Z
        -co.y / SCALE,      # game Z = -blender Y
    )


def export_pac():
    # Get CD mesh
    if CD_MESH_NAME not in bpy.data.objects:
        print(f"ERROR: '{CD_MESH_NAME}' not found. Run blender_setup_scene.py first.")
        return

    cd_obj = bpy.data.objects[CD_MESH_NAME]
    mesh = cd_obj.data

    # Check shrinkwrap is applied
    for mod in cd_obj.modifiers:
        if mod.type == 'SHRINKWRAP':
            print("WARNING: Shrinkwrap modifier still active (not applied).")
            print("  Apply it first (select CD_Mesh > Modifiers > Apply)")
            print("  Or continuing will export the UN-modified positions.")
            return

    # Evaluate mesh to get final positions (applies any remaining modifiers)
    depsgraph = bpy.context.evaluated_depsgraph_get()
    eval_obj = cd_obj.evaluated_get(depsgraph)
    eval_mesh = eval_obj.data

    n_verts = len(eval_mesh.vertices)
    if n_verts != TOTAL_VERTS:
        print(f"ERROR: Vertex count mismatch: {n_verts} != {TOTAL_VERTS}")
        return

    print(f"Reading {n_verts} vertices from '{CD_MESH_NAME}'...")

    # Read all positions in model space
    # Vertices are in the same order as the imported OBJ (submeshes contiguous)
    model_positions = []
    for v in eval_mesh.vertices:
        world_co = cd_obj.matrix_world @ v.co
        model_positions.append(blender_to_model_space(world_co))

    # Read vertex normals from Blender (post-shrinkwrap)
    eval_mesh.calc_normals_split()
    # Per-vertex normals (averaged from split normals)
    vertex_normals = []
    for v in eval_mesh.vertices:
        n = v.normal
        # Convert normal direction: same axis swap as position (but no translation/scale)
        gn = (n.x, n.z, -n.y)
        length = math.sqrt(gn[0]**2 + gn[1]**2 + gn[2]**2)
        if length > 1e-8:
            gn = (gn[0]/length, gn[1]/length, gn[2]/length)
        vertex_normals.append(gn)

    # Load original PAC as template
    pac = bytearray(ORIGINAL_PAC.read_bytes())
    bbox_offsets = find_bbox_offsets(bytes(pac))

    print(f"Loaded original PAC: {len(pac):,} bytes")

    # Process per submesh
    obj_lines = ["# Crimson Desert dragon — Blender shrinkwrap export\n"]
    global_vert_offset = 0

    for sm_idx, sm_name in enumerate(SUBMESH_NAMES):
        base = SUBMESH_BASES[sm_idx]
        count = SUBMESH_VERTEX_COUNTS[sm_idx]
        sm_positions = model_positions[base:base + count]
        sm_normals = vertex_normals[base:base + count]

        # Compute new bounding box
        xs = [p[0] for p in sm_positions]
        ys = [p[1] for p in sm_positions]
        zs = [p[2] for p in sm_positions]

        eps = 1e-6
        bbox_min = (min(xs), min(ys), min(zs))
        bbox_max = (max(xs), max(ys), max(zs))
        bbox_dim = (
            max(eps, bbox_max[0] - bbox_min[0]),
            max(eps, bbox_max[1] - bbox_min[1]),
            max(eps, bbox_max[2] - bbox_min[2]),
        )

        # Read old bbox for comparison
        old_floats = struct.unpack_from('<8f', pac, bbox_offsets[sm_idx])
        old_min = old_floats[2:5]
        old_dim = old_floats[5:8]

        print(f"  {sm_name:12s}: {count} verts  "
              f"bbox ({old_min[0]:.3f},{old_min[1]:.3f},{old_min[2]:.3f})"
              f" → ({bbox_min[0]:.3f},{bbox_min[1]:.3f},{bbox_min[2]:.3f})")

        # Write quantized positions and normals to PAC
        for j in range(count):
            off = VB_START + (base + j) * STRIDE
            x, y, z = sm_positions[j]
            qx, qy, qz = quantize_pos(x, y, z, bbox_min, bbox_dim)
            struct.pack_into('<3H', pac, off, qx, qy, qz)

            # Write normal
            nx, ny, nz = sm_normals[j]
            packed_normal = encode_normal_r10g10b10a2(nx, ny, nz)
            struct.pack_into('<I', pac, off + 8, packed_normal)

        # Write new bbox to PAC descriptor
        bbox_off = bbox_offsets[sm_idx]
        lod_near, lod_far = old_floats[0], old_floats[1]
        struct.pack_into('<2f', pac, bbox_off, lod_near, lod_far)
        struct.pack_into('<3f', pac, bbox_off + 8, *bbox_min)
        struct.pack_into('<3f', pac, bbox_off + 20, *bbox_dim)

        # OBJ preview
        for p in sm_positions:
            obj_lines.append(f"v {p[0]:.6f} {p[1]:.6f} {p[2]:.6f}\n")

        obj_lines.append(f"\ng {sm_name}\n")
        global_vert_offset += count

    # Write PAC
    OUTPUT_PAC.write_bytes(pac)
    print(f"\nWrote: {OUTPUT_PAC} ({len(pac):,} bytes)")

    # Write preview OBJ (positions only, no faces — quick visual check)
    with open(str(OUTPUT_OBJ), 'w') as f:
        f.writelines(obj_lines)
    print(f"Wrote preview: {OUTPUT_OBJ}")

    # Verify size matches original
    orig_size = ORIGINAL_PAC.stat().st_size
    if len(pac) == orig_size:
        print(f"Size OK: {len(pac):,} bytes (matches original)")
    else:
        print(f"WARNING: Size mismatch! {len(pac):,} != {orig_size:,}")

    print("\nDone. To deploy to game: set DEPLOY=True and re-run.")


if __name__ == '__main__':
    export_pac()
```

- [ ] **Step 2: Verify export in Blender**

After applying Shrinkwrap on CD mesh in the setup scene, run `blender_export_pac.py` in Blender's Text Editor.

Expected:
- Console prints per-submesh bbox changes
- `output/dragon_drogon_blender.pac` written (5,208,284 bytes, matches original size)
- `output/dragon_drogon_blender.obj` written (preview)

Verify: open the preview OBJ in Blender to check positions look correct.

- [ ] **Step 3: Commit**

```bash
cd C:\Users\waelj\got-dragon-cd-mod
git add tools/blender_export_pac.py
git commit -m "feat: add Blender PAC export script for mesh swap"
```

---

### Task 3: Deploy and Test In-Game

**Files:**
- Reference: `tools/pac_patcher.py` — `deploy_pac()` function, `PAZ_DIR`, `PAC_OFFSET`, `PAC_SIZE`

- [ ] **Step 1: Add deployment option to export script**

Add to the bottom of `blender_export_pac.py`, after the `export_pac()` function's final print:

```python
    if DEPLOY:
        import sys
        sys.path.insert(0, str(ROOT / "tools"))
        from pac_patcher import deploy_pac
        deploy_pac(str(OUTPUT_PAC))
```

- [ ] **Step 2: Deploy and test**

1. In `blender_export_pac.py`, set `DEPLOY = True`
2. Run the script in Blender
3. Launch Crimson Desert and check the dragon model

Expected: Dragon in-game shows Drogon's silhouette with CD's animations.

- [ ] **Step 3: Commit**

```bash
cd C:\Users\waelj\got-dragon-cd-mod
git add tools/blender_export_pac.py
git commit -m "feat: add deployment to Blender export script"
```
