"""
Blender Scene Setup v2 — Crimson Desert Dragon Mesh Swap
=========================================================
Run inside Blender: Text Editor > Open > Run Script

KEY FIX vs v1: Builds the CD mesh DIRECTLY from PAC binary data using the
EXACT same AXIS_SWAP transform as the armature, bypassing Blender's OBJ
importer which may apply a different axis conversion. This guarantees the
mesh and armature are in identical coordinate spaces.

Pipeline:
  1. Builds CD dragon armature (274 bones from cd_skeleton.json)
  2. Reads CD dragon mesh directly from dragon.pac (30112 verts, 8 submeshes)
  3. Applies AXIS_SWAP + 4x scale (identical to armature)
  4. Creates vertex groups with bone weights from PAC bone palette
  5. Parents mesh to armature with Armature modifier
  6. Imports Drogon mesh and auto-aligns
  7. Adds Shrinkwrap modifier

After running:
  - CD_Mesh should perfectly align with CD_Dragon armature
  - Adjust Drogon position/scale, Shrinkwrap updates live
  - When satisfied, apply Shrinkwrap, then run export script
"""

import bpy
import json
import struct
import math
from pathlib import Path
from mathutils import Matrix, Vector

# ==================== CONFIGURATION ====================
ROOT = Path(r"C:\Users\user\crimson-desert-got-dragon-mod")
SKELETON_JSON = ROOT / "output" / "cd_skeleton.json"
PAC_PATH = ROOT / "output" / "dragon.pac"
DROGON_OBJ = Path(r"C:\Users\user\Desktop\Outputs\DROGON.OBJ")

SCALE = 4.0                # BaseCharacterScale from prefab
ARMATURE_NAME = "CD_Dragon"
CD_MESH_NAME = "CD_Mesh"
DROGON_NAME = "Drogon"
LEAF_BONE_LENGTH = 0.15    # Tail length for leaf bones (scaled units)
# =======================================================

# Y-up -> Z-up: +90 deg rotation around X axis
# Maps: X->X, Y->Z, Z->-Y
AXIS_SWAP = Matrix((
    (1,  0,  0, 0),
    (0,  0, -1, 0),
    (0,  1,  0, 0),
    (0,  0,  0, 1),
))

# PAC format constants
VB_START = 0x7BFA       # vertex buffer start offset
STRIDE = 40             # bytes per vertex
SUBMESH_NAMES = ["Eyeright", "Eyeleft", "Body_02", "back", "Body", "Leg", "Wing", "Head"]
SUBMESH_VERTEX_COUNTS = [225, 225, 2013, 3307, 2736, 4624, 6724, 10258]
SUBMESH_INDEX_COUNTS = [1248, 1248, 7992, 17007, 13380, 22464, 34902, 51180]

# Contiguous vertex bases
SUBMESH_BASES = []
_base = 0
for _vc in SUBMESH_VERTEX_COUNTS:
    SUBMESH_BASES.append(_base)
    _base += _vc
TOTAL_VERTS = _base  # 30112


# ------------------------------------------------------------------
# PAC parsing helpers
# ------------------------------------------------------------------

def parse_submesh_bboxes(pac):
    """Parse per-submesh bbox from PAC descriptor area.
    Returns list of (bbox_min, bbox_dim) tuples.
    """
    bboxes = []
    off = 0x0077

    for i in range(8):
        name_len = pac[off]
        off += 1 + name_len

        mat_len = pac[off]
        off += 1 + mat_len

        # 3 flag bytes
        off += 3

        # 8 x float32: [lod_near, lod_far, min_x, min_y, min_z, dim_x, dim_y, dim_z]
        floats = struct.unpack_from('<8f', pac, off)
        off += 32

        bbox_min = (floats[2], floats[3], floats[4])
        bbox_dim = (floats[5], floats[6], floats[7])
        bboxes.append((bbox_min, bbox_dim))

        # Skip to next submesh descriptor
        next_cd = pac.find(b'CD_M0004', off)
        if next_cd > 0 and next_cd < 0x0441:
            off = next_cd - 1
        else:
            off = 0x0441

    return bboxes


def parse_bone_palette(pac, skeleton):
    """Parse bone hash palette from PAC and map to skeleton bone names.
    Returns: palette list where palette[i] = skeleton bone name (or None)
    """
    skel_hash_to_name = {b['hash']: b['name'] for b in skeleton}

    pal_count = struct.unpack_from('<H', pac, 0x0441)[0]
    palette = []
    for i in range(pal_count):
        h = struct.unpack_from('<I', pac, 0x0443 + i * 4)[0]
        name = skel_hash_to_name.get(h)
        palette.append(name)

    return palette


def dequantize_pos(u16_x, u16_y, u16_z, bbox_min, bbox_dim):
    """Dequantize uint16 position to float using bbox.
    Formula verified from DXIL vertex shader: pos = min + (uint16 / 32767) * dim
    """
    x = bbox_min[0] + (u16_x / 32767.0) * bbox_dim[0]
    y = bbox_min[1] + (u16_y / 32767.0) * bbox_dim[1]
    z = bbox_min[2] + (u16_z / 32767.0) * bbox_dim[2]
    return (x, y, z)


def game_to_blender(x, y, z):
    """Convert game-space position (Y-up) to Blender-space (Z-up).
    Uses AXIS_SWAP: (x, y, z) -> (x, -z, y), then scales by 4.
    This is the EXACT same transform applied to armature bones.
    """
    return (x * SCALE, -z * SCALE, y * SCALE)


def read_pac_mesh(pac, bboxes, bone_palette):
    """Read all vertex data from PAC binary.
    Returns: (positions_blender, normals_blender, submesh_data)
    where submesh_data[i] = {verts, bone_groups}
    """
    positions = []       # Blender-space (x, y, z) for each vertex
    bone_groups = []     # [{bone_name: weight}, ...] per vertex

    for sm_idx in range(8):
        base = SUBMESH_BASES[sm_idx]
        count = SUBMESH_VERTEX_COUNTS[sm_idx]
        bbox_min, bbox_dim = bboxes[sm_idx]

        for j in range(count):
            off = VB_START + (base + j) * STRIDE
            raw = pac[off:off + STRIDE]

            # Bytes 0-5: 3 x uint16 position (quantized)
            u16_x, u16_y, u16_z = struct.unpack_from('<3H', raw, 0)
            gx, gy, gz = dequantize_pos(u16_x, u16_y, u16_z, bbox_min, bbox_dim)

            # Convert to Blender space (SAME transform as armature)
            bx, by, bz = game_to_blender(gx, gy, gz)
            positions.append((bx, by, bz))

            # Bytes 12-15: 4 x uint8 bone palette indices
            bi = struct.unpack_from('4B', raw, 12)
            # Bytes 20-23: 4 x uint8 bone weights
            bw = struct.unpack_from('4B', raw, 20)

            groups = {}
            total_w = sum(bw)
            if total_w > 0:
                for k in range(4):
                    if bw[k] > 0 and bi[k] < len(bone_palette):
                        bone_name = bone_palette[bi[k]]
                        if bone_name:
                            w = bw[k] / total_w
                            # Accumulate weights for same bone
                            groups[bone_name] = groups.get(bone_name, 0.0) + w
            bone_groups.append(groups)

    return positions, bone_groups


def read_pac_indices(pac):
    """Read index buffer for all submeshes."""
    total_indices = sum(SUBMESH_INDEX_COUNTS)
    index_start = len(pac) - total_indices * 2
    all_indices = struct.unpack_from(f'<{total_indices}H', pac, index_start)

    result = []
    pos = 0
    for i in range(8):
        count = SUBMESH_INDEX_COUNTS[i]
        result.append(list(all_indices[pos:pos + count]))
        pos += count

    return result


# ------------------------------------------------------------------
# Cleanup
# ------------------------------------------------------------------

def cleanup_scene():
    """Remove previous objects/armatures with our names so the script is re-runnable."""
    print("[1/6] Cleaning up previous scene objects...")

    names_to_remove = [CD_MESH_NAME, DROGON_NAME, ARMATURE_NAME]

    for name in names_to_remove:
        if name in bpy.data.objects:
            obj = bpy.data.objects[name]
            bpy.data.objects.remove(obj, do_unlink=True)

    if ARMATURE_NAME in bpy.data.armatures:
        bpy.data.armatures.remove(bpy.data.armatures[ARMATURE_NAME])

    for name in [CD_MESH_NAME, DROGON_NAME]:
        if name in bpy.data.meshes:
            bpy.data.meshes.remove(bpy.data.meshes[name])


# ------------------------------------------------------------------
# Armature builder
# ------------------------------------------------------------------

def get_world_matrices(bones_data):
    """Read world matrices directly from PAB (1st matrix = armature-space).
    Transpose for Blender (DX row-vector -> column-vector), scale translations,
    then apply AXIS_SWAP. IDENTICAL to mesh vertex transform.
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


def build_armature(bones_data):
    """Build the CD dragon armature from cd_skeleton.json (274 bones)."""
    print("[2/6] Building CD dragon armature...")

    n = len(bones_data)
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

    # --- Object mode ---
    bpy.ops.object.mode_set(mode='OBJECT')

    arm_obj.show_in_front = True
    arm.display_type = 'STICK'

    roots = sum(1 for bd in bones_data if bd['parent_index'] == -1)
    print(f"  Armature '{ARMATURE_NAME}': {n} bones, {roots} root(s)")

    return arm_obj


# ------------------------------------------------------------------
# Mesh builder (direct from PAC — no OBJ import!)
# ------------------------------------------------------------------

def build_cd_mesh(pac, bboxes, bone_palette, bones_data):
    """Build CD dragon mesh directly from PAC binary data.
    Applies the EXACT same AXIS_SWAP + scale as the armature.
    """
    print("[3/6] Building CD mesh from PAC data...")

    positions, bone_groups = read_pac_mesh(pac, bboxes, bone_palette)
    all_indices = read_pac_indices(pac)

    print(f"  Read {len(positions)} vertices from PAC")

    # Build faces (triangles) with global vertex indices
    faces = []
    for sm_idx in range(8):
        base = SUBMESH_BASES[sm_idx]
        sm_indices = all_indices[sm_idx]
        for tri in range(len(sm_indices) // 3):
            i0 = sm_indices[tri * 3 + 0] + base
            i1 = sm_indices[tri * 3 + 1] + base
            i2 = sm_indices[tri * 3 + 2] + base
            # Validate indices
            if i0 < TOTAL_VERTS and i1 < TOTAL_VERTS and i2 < TOTAL_VERTS:
                faces.append((i0, i1, i2))

    print(f"  Built {len(faces)} triangles from index buffer")

    # Create Blender mesh
    mesh = bpy.data.meshes.new(CD_MESH_NAME)
    mesh.from_pydata(positions, [], faces)
    mesh.update()

    # Create object
    cd_obj = bpy.data.objects.new(CD_MESH_NAME, mesh)
    bpy.context.collection.objects.link(cd_obj)

    # Add vertex groups for submeshes
    for sm_idx in range(8):
        vg = cd_obj.vertex_groups.new(name=SUBMESH_NAMES[sm_idx])
        base = SUBMESH_BASES[sm_idx]
        count = SUBMESH_VERTEX_COUNTS[sm_idx]
        vg.add(list(range(base, base + count)), 1.0, 'REPLACE')

    # Add vertex groups for bone weights
    print("  Assigning bone weights...")
    all_bone_names = set()
    for groups in bone_groups:
        all_bone_names.update(groups.keys())

    # Create vertex groups for all referenced bones
    bone_vgroups = {}
    for bone_name in sorted(all_bone_names):
        vg = cd_obj.vertex_groups.new(name=bone_name)
        bone_vgroups[bone_name] = vg

    # Assign weights per vertex
    for vi, groups in enumerate(bone_groups):
        for bone_name, weight in groups.items():
            if weight > 0.001:
                bone_vgroups[bone_name].add([vi], weight, 'REPLACE')

    # Print bounding box
    xs = [p[0] for p in positions]
    ys = [p[1] for p in positions]
    zs = [p[2] for p in positions]
    print(f"  Mesh '{CD_MESH_NAME}': {len(positions)} verts, {len(faces)} tris")
    print(f"  BBox: X[{min(xs):.2f}, {max(xs):.2f}] "
          f"Y[{min(ys):.2f}, {max(ys):.2f}] "
          f"Z[{min(zs):.2f}, {max(zs):.2f}]")
    print(f"  Bone weight groups: {len(all_bone_names)}")

    return cd_obj


# ------------------------------------------------------------------
# Parent mesh to armature
# ------------------------------------------------------------------

def parent_to_armature(cd_obj, arm_obj):
    """Parent mesh to armature with Armature modifier."""
    print("[4/6] Parenting mesh to armature...")

    # Set parent
    cd_obj.parent = arm_obj

    # Add Armature modifier
    mod = cd_obj.modifiers.new(name='Armature', type='ARMATURE')
    mod.object = arm_obj

    print(f"  Parented '{CD_MESH_NAME}' to '{ARMATURE_NAME}' with Armature modifier")


# ------------------------------------------------------------------
# Drogon import and alignment
# ------------------------------------------------------------------

def get_world_bbox(obj):
    """Compute world-space axis-aligned bounding box."""
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


def import_drogon():
    """Import Drogon mesh from OBJ, mirror if half-mesh."""
    print("[5/6] Importing Drogon mesh...")

    if not DROGON_OBJ.exists():
        print(f"  WARNING: Drogon mesh not found at {DROGON_OBJ}")
        print(f"  Skipping Drogon import. You can import it manually later.")
        return None

    before = set(bpy.data.objects.keys())

    bpy.ops.wm.obj_import(
        filepath=str(DROGON_OBJ),
        forward_axis='NEGATIVE_Z',
        up_axis='Y',
    )

    after = set(bpy.data.objects.keys())
    new_names = after - before

    if not new_names:
        print("  WARNING: OBJ import did not create any new objects")
        return None

    imported_name = sorted(new_names)[0]
    drogon_obj = bpy.data.objects[imported_name]
    drogon_obj.name = DROGON_NAME
    if drogon_obj.data:
        drogon_obj.data.name = DROGON_NAME

    vert_count = len(drogon_obj.data.vertices)
    print(f"  '{DROGON_NAME}': {vert_count} verts")

    # Check if half-mesh and mirror
    bbox = get_world_bbox(drogon_obj)
    x_min, x_max = bbox['min'].x, bbox['max'].x
    x_span_neg = abs(x_min)
    x_span_pos = abs(x_max)
    ratio = min(x_span_neg, x_span_pos) / max(x_span_neg, x_span_pos, 0.001)

    if ratio < 0.3:
        print(f"  Detected half-mesh (X ratio={ratio:.2f}), adding Mirror modifier...")
        mirror = drogon_obj.modifiers.new(name='Mirror', type='MIRROR')
        mirror.use_axis[0] = True
        mirror.use_clip = True
        bpy.context.view_layer.objects.active = drogon_obj
        drogon_obj.select_set(True)
        bpy.ops.object.modifier_apply(modifier='Mirror')
        drogon_obj.select_set(False)
        new_count = len(drogon_obj.data.vertices)
        print(f"  Mirrored: {vert_count} -> {new_count} verts")

    return drogon_obj


def auto_align_drogon(cd_obj, drogon_obj):
    """Scale and translate Drogon to match CD mesh bounding box."""
    print("  Auto-aligning Drogon to CD mesh...")

    cd_bbox = get_world_bbox(cd_obj)
    drogon_bbox = get_world_bbox(drogon_obj)

    cd_span = cd_bbox['max'] - cd_bbox['min']
    drogon_span = drogon_bbox['max'] - drogon_bbox['min']

    cd_max_span = max(cd_span.x, cd_span.y, cd_span.z)
    drogon_max_span = max(drogon_span.x, drogon_span.y, drogon_span.z)

    if drogon_max_span < 0.001:
        raise RuntimeError("Drogon mesh has zero extent")

    scale_factor = cd_max_span / drogon_max_span
    print(f"  Scale factor: {scale_factor:.4f}")

    drogon_obj.scale = (scale_factor, scale_factor, scale_factor)
    bpy.context.view_layer.objects.active = drogon_obj
    drogon_obj.select_set(True)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    drogon_obj.select_set(False)

    # Center Drogon on CD mesh
    drogon_bbox = get_world_bbox(drogon_obj)
    drogon_center = (drogon_bbox['min'] + drogon_bbox['max']) / 2
    cd_center = (cd_bbox['min'] + cd_bbox['max']) / 2
    offset = cd_center - drogon_center
    drogon_obj.location = drogon_obj.location + offset

    drogon_obj.display_type = 'WIRE'
    print(f"  Aligned and set to wireframe")


def add_shrinkwrap(cd_obj, drogon_obj):
    """Add Shrinkwrap modifier to CD_Mesh targeting Drogon."""
    print("[6/6] Adding Shrinkwrap modifier...")

    for mod in cd_obj.modifiers:
        if mod.type == 'SHRINKWRAP' and mod.name == 'Shrinkwrap_Drogon':
            cd_obj.modifiers.remove(mod)
            break

    sw = cd_obj.modifiers.new(name='Shrinkwrap_Drogon', type='SHRINKWRAP')
    sw.target = drogon_obj
    sw.wrap_method = 'NEAREST_SURFACEPOINT'
    sw.wrap_mode = 'ON_SURFACE'

    print(f"  Shrinkwrap added: {CD_MESH_NAME} -> {DROGON_NAME}")


# ------------------------------------------------------------------
# Verification
# ------------------------------------------------------------------

def verify_alignment(cd_obj, arm_obj, bones_data):
    """Check that key bone positions fall within the mesh bounding box."""
    print("\n  --- Alignment Verification ---")

    world_mats = get_world_matrices(bones_data)
    by_name = {bd['name']: bd['index'] for bd in bones_data}

    cd_bbox = get_world_bbox(cd_obj)

    key_bones = ['Bip01', 'Bip01 Pelvis', 'Bip01 Spine', 'Bip01 Head',
                 'Bip01 Tail', 'Bip01 L Thigh', 'Bip01 R Thigh',
                 'Bip01 L UpperArm', 'Bip01 R UpperArm']

    mesh_center = (cd_bbox['min'] + cd_bbox['max']) / 2
    mesh_span = cd_bbox['max'] - cd_bbox['min']

    for name in key_bones:
        if name not in by_name:
            continue
        idx = by_name[name]
        pos = world_mats[idx].translation
        # Check if bone is within expanded mesh bbox
        in_bbox = (cd_bbox['min'].x - 2 <= pos.x <= cd_bbox['max'].x + 2 and
                   cd_bbox['min'].y - 2 <= pos.y <= cd_bbox['max'].y + 2 and
                   cd_bbox['min'].z - 2 <= pos.z <= cd_bbox['max'].z + 2)
        status = "OK" if in_bbox else "OUTSIDE"
        print(f"  {name:25s} ({pos.x:+8.2f}, {pos.y:+8.2f}, {pos.z:+8.2f}) [{status}]")

    print(f"  Mesh center: ({mesh_center.x:.2f}, {mesh_center.y:.2f}, {mesh_center.z:.2f})")
    print(f"  Mesh span:   ({mesh_span.x:.2f}, {mesh_span.y:.2f}, {mesh_span.z:.2f})")


# ------------------------------------------------------------------
# Main
# ------------------------------------------------------------------

def main():
    print("=" * 60)
    print("  Crimson Desert Dragon Mesh Swap - Scene Setup v2")
    print("  (Direct PAC import — guaranteed axis alignment)")
    print("=" * 60)

    # Ensure object mode
    if bpy.context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    bpy.ops.object.select_all(action='DESELECT')

    # Load data files
    print("\nLoading data files...")
    with open(str(SKELETON_JSON), 'r') as f:
        bones_data = json.load(f)
    print(f"  Skeleton: {len(bones_data)} bones")

    pac = PAC_PATH.read_bytes()
    print(f"  PAC: {len(pac)} bytes")

    bboxes = parse_submesh_bboxes(pac)
    print(f"  Parsed {len(bboxes)} submesh bboxes")

    bone_palette = parse_bone_palette(pac, bones_data)
    matched = sum(1 for p in bone_palette if p is not None)
    print(f"  Bone palette: {len(bone_palette)} entries, {matched} matched to skeleton")

    # Step 1: Cleanup
    cleanup_scene()

    # Step 2: Build armature
    arm_obj = build_armature(bones_data)

    # Step 3: Build CD mesh directly from PAC
    cd_obj = build_cd_mesh(pac, bboxes, bone_palette, bones_data)

    # Step 4: Parent mesh to armature
    parent_to_armature(cd_obj, arm_obj)

    # Verify alignment
    verify_alignment(cd_obj, arm_obj, bones_data)

    # Step 5: Import Drogon and align
    drogon_obj = import_drogon()
    if drogon_obj:
        auto_align_drogon(cd_obj, drogon_obj)
        # Step 6: Shrinkwrap
        add_shrinkwrap(cd_obj, drogon_obj)

    # Final: select CD mesh and frame view
    bpy.ops.object.select_all(action='DESELECT')
    cd_obj.select_set(True)
    bpy.context.view_layer.objects.active = cd_obj

    for area in bpy.context.screen.areas:
        if area.type == 'VIEW_3D':
            for region in area.regions:
                if region.type == 'WINDOW':
                    with bpy.context.temp_override(area=area, region=region):
                        bpy.ops.view3d.view_all()
                    break
            break

    # Summary
    print("\n" + "=" * 60)
    print("  SCENE SETUP v2 COMPLETE")
    print("=" * 60)
    print(f"  Armature:  {ARMATURE_NAME} ({len(bones_data)} bones)")
    print(f"  CD Mesh:   {CD_MESH_NAME} ({TOTAL_VERTS} verts, built from PAC)")
    print(f"  Transform: AXIS_SWAP + {SCALE}x scale (identical for mesh AND armature)")
    if drogon_obj:
        print(f"  Drogon:    {DROGON_NAME} (auto-aligned, wireframe)")
        print(f"  Modifier:  Shrinkwrap on {CD_MESH_NAME} -> {DROGON_NAME}")
    print("")
    print("  KEY DIFFERENCE from v1:")
    print("  Mesh is built directly from PAC binary using the EXACT same")
    print("  coordinate transform as the armature (no OBJ import).")
    print("")
    print("  NEXT STEPS:")
    print("  1. Inspect mesh-armature alignment (they should overlap)")
    print("  2. If Drogon loaded, adjust its position/scale as needed")
    print("  3. Apply Shrinkwrap modifier when satisfied")
    print("  4. Run blender_export_pac.py to encode back to PAC")
    print("=" * 60)


if __name__ == '__main__':
    main()
