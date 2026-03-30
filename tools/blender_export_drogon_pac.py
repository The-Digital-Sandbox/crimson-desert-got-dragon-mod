"""
Export Rigged Drogon to CD Dragon PAC Format
=============================================
Run inside Blender with the DrogonRigged scene open.

For each of the 30,112 CD dragon vertices:
  1. Find nearest point on Drogon's surface (BVH tree)
  2. Use that position as the new vertex position
  3. Transfer bone weights from nearest Drogon vertex
  4. Quantize and write into original PAC structure

Output: A PAC file with Drogon's shape but CD dragon's topology.
Same vertex count, same index buffer, same submesh structure.
"""

import bpy
import struct
import json
import math
from pathlib import Path
from mathutils import Vector
from mathutils.bvhtree import BVHTree

# ==================== CONFIGURATION ====================
ROOT = Path(r"C:\Users\user\crimson-desert-got-dragon-mod")
PAC_PATH = ROOT / "output" / "dragon.pac"
SKELETON_JSON = ROOT / "output" / "cd_skeleton.json"
OUTPUT_PAC = ROOT / "output" / "dragon_drogon_final.pac"

DROGON_NAME = "Drogon"      # Name of the rigged Drogon mesh in the scene
ARMATURE_NAME = "CD_Dragon"

SCALE = 4.0
DEPLOY = False               # Set True to also patch the game files
# =======================================================

# PAC constants
VB_START = 0x7BFA
STRIDE = 40
SUBMESH_NAMES = ["Eyeright", "Eyeleft", "Body_02", "back", "Body", "Leg", "Wing", "Head"]
SUBMESH_VERTEX_COUNTS = [225, 225, 2013, 3307, 2736, 4624, 6724, 10258]
TOTAL_VERTS = sum(SUBMESH_VERTEX_COUNTS)  # 30112

SUBMESH_BASES = []
_base = 0
for _vc in SUBMESH_VERTEX_COUNTS:
    SUBMESH_BASES.append(_base)
    _base += _vc


def game_to_blender(x, y, z):
    """Game (Y-up) -> Blender (Z-up). Same as armature AXIS_SWAP + scale."""
    return Vector((x * SCALE, -z * SCALE, y * SCALE))


def blender_to_game(bx, by, bz):
    """Blender (Z-up) -> Game (Y-up). Inverse of AXIS_SWAP + scale."""
    return (bx / SCALE, bz / SCALE, -by / SCALE)


def parse_submesh_bboxes(pac):
    """Parse per-submesh bbox from PAC descriptor."""
    bboxes = []
    off = 0x0077
    for i in range(8):
        name_len = pac[off]; off += 1 + name_len
        mat_len = pac[off]; off += 1 + mat_len
        off += 3
        floats = struct.unpack_from('<8f', pac, off)
        off += 32
        bboxes.append({
            'lod_near': floats[0], 'lod_far': floats[1],
            'min': (floats[2], floats[3], floats[4]),
            'dim': (floats[5], floats[6], floats[7]),
        })
        next_cd = pac.find(b'CD_M0004', off)
        if next_cd > 0 and next_cd < 0x0441:
            off = next_cd - 1
        else:
            off = 0x0441
    return bboxes


def find_bbox_offsets(pac):
    """Find byte offsets of each submesh's bbox block."""
    offsets = []
    off = 0x0077
    for i in range(8):
        name_len = pac[off]; off += 1 + name_len
        mat_len = pac[off]; off += 1 + mat_len
        off += 3
        offsets.append(off)
        off += 32
        next_cd = pac.find(b'CD_M0004', off)
        if next_cd > 0 and next_cd < 0x0441:
            off = next_cd - 1
        else:
            off = 0x0441
    return offsets


def dequantize(u16_x, u16_y, u16_z, bbox):
    """uint16 -> float position using bbox."""
    x = bbox['min'][0] + (u16_x / 32767.0) * bbox['dim'][0]
    y = bbox['min'][1] + (u16_y / 32767.0) * bbox['dim'][1]
    z = bbox['min'][2] + (u16_z / 32767.0) * bbox['dim'][2]
    return (x, y, z)


def quantize(x, y, z, bbox_min, bbox_dim):
    """float -> uint16 using bbox."""
    def q(val, bmin, bdim):
        if abs(bdim) < 1e-10:
            return 0
        return max(0, min(65535, int(round((val - bmin) / bdim * 32767.0))))
    return (q(x, bbox_min[0], bbox_dim[0]),
            q(y, bbox_min[1], bbox_dim[1]),
            q(z, bbox_min[2], bbox_dim[2]))


def parse_bone_palette(pac, skeleton):
    """Parse bone hash palette and map to bone names."""
    skel_hash_to_name = {b['hash']: b['name'] for b in skeleton}
    name_to_palette_idx = {}

    pal_count = struct.unpack_from('<H', pac, 0x0441)[0]
    for i in range(pal_count):
        h = struct.unpack_from('<I', pac, 0x0443 + i * 4)[0]
        name = skel_hash_to_name.get(h)
        if name:
            name_to_palette_idx[name] = i

    return name_to_palette_idx, pal_count


def get_drogon_weights_at_vertex(drogon_obj, vert_index):
    """Get bone weights for a Drogon vertex as {group_name: weight}."""
    mesh = drogon_obj.data
    weights = {}
    for g in mesh.vertices[vert_index].groups:
        vg = drogon_obj.vertex_groups[g.group]
        if g.weight > 0.001:
            weights[vg.name] = g.weight
    return weights


def interpolate_weights_from_face(drogon_obj, face_index, hit_point):
    """Interpolate bone weights at a point on a face using barycentric coords."""
    mesh = drogon_obj.data
    poly = mesh.polygons[face_index]
    verts = list(poly.vertices)

    if len(verts) < 3:
        return get_drogon_weights_at_vertex(drogon_obj, verts[0])

    # Get vertex positions
    v0 = mesh.vertices[verts[0]].co
    v1 = mesh.vertices[verts[1]].co
    v2 = mesh.vertices[verts[2]].co

    # Compute barycentric coordinates
    e0 = v1 - v0
    e1 = v2 - v0
    ep = hit_point - v0

    d00 = e0.dot(e0)
    d01 = e0.dot(e1)
    d11 = e1.dot(e1)
    dp0 = ep.dot(e0)
    dp1 = ep.dot(e1)

    denom = d00 * d11 - d01 * d01
    if abs(denom) < 1e-10:
        return get_drogon_weights_at_vertex(drogon_obj, verts[0])

    u = (d11 * dp0 - d01 * dp1) / denom
    v = (d00 * dp1 - d01 * dp0) / denom
    w = 1.0 - u - v

    # Clamp
    w = max(0, w)
    u = max(0, u)
    v = max(0, v)
    total = w + u + v
    if total > 0:
        w /= total; u /= total; v /= total

    # Get weights for each vertex
    w0 = get_drogon_weights_at_vertex(drogon_obj, verts[0])
    w1 = get_drogon_weights_at_vertex(drogon_obj, verts[1])
    w2 = get_drogon_weights_at_vertex(drogon_obj, verts[2])

    # Interpolate
    blended = {}
    all_bones = set(w0.keys()) | set(w1.keys()) | set(w2.keys())
    for bone in all_bones:
        bw = w * w0.get(bone, 0) + u * w1.get(bone, 0) + v * w2.get(bone, 0)
        if bw > 0.001:
            blended[bone] = bw

    return blended


def weights_to_pac_format(weights, name_to_palette_idx, max_influences=4):
    """Convert {bone_name: weight} to PAC format (4x uint8 palette idx, 4x uint8 weight).

    Returns (bone_indices_4, bone_weights_4) as tuples of 4 ints each.
    """
    # Map bone names to palette indices and sort by weight
    mapped = []
    for bone_name, weight in weights.items():
        if bone_name in name_to_palette_idx:
            mapped.append((name_to_palette_idx[bone_name], weight))

    if not mapped:
        return (0, 0, 0, 0), (255, 0, 0, 0)

    # Sort by weight descending, take top N
    mapped.sort(key=lambda x: -x[1])
    mapped = mapped[:max_influences]

    # Normalize weights
    total = sum(w for _, w in mapped)
    if total <= 0:
        return (0, 0, 0, 0), (255, 0, 0, 0)

    # Convert to uint8 weights (must sum to 255)
    indices = []
    raw_weights = []
    for idx, w in mapped:
        indices.append(idx)
        raw_weights.append(w / total)

    # Quantize to uint8
    int_weights = [int(round(w * 255)) for w in raw_weights]

    # Ensure they sum to 255
    diff = 255 - sum(int_weights)
    if diff != 0 and int_weights:
        int_weights[0] += diff

    # Pad to 4
    while len(indices) < 4:
        indices.append(0)
    while len(int_weights) < 4:
        int_weights.append(0)

    return tuple(indices[:4]), tuple(int_weights[:4])


def main():
    print("=" * 60)
    print("  DROGON -> PAC EXPORT")
    print("  Surface projection: 30,112 CD verts -> Drogon surface")
    print("=" * 60)

    # --- Validate scene ---
    drogon_obj = bpy.data.objects.get(DROGON_NAME)
    if drogon_obj is None:
        print(f"ERROR: '{DROGON_NAME}' not found in scene")
        return
    if drogon_obj.type != 'MESH':
        print(f"ERROR: '{DROGON_NAME}' is not a mesh")
        return

    print(f"\n  Drogon mesh: {len(drogon_obj.data.vertices)} verts")

    # --- Load PAC and skeleton ---
    pac = bytearray(PAC_PATH.read_bytes())
    print(f"  Original PAC: {len(pac)} bytes")

    with open(str(SKELETON_JSON), 'r') as f:
        skeleton = json.load(f)

    bboxes = parse_submesh_bboxes(bytes(pac))
    bbox_offsets = find_bbox_offsets(bytes(pac))
    name_to_palette_idx, pal_count = parse_bone_palette(bytes(pac), skeleton)
    print(f"  Bone palette: {pal_count} entries, {len(name_to_palette_idx)} mapped")

    # --- Build BVH tree from Drogon ---
    print("\n  Building BVH tree from Drogon surface...")

    depsgraph = bpy.context.evaluated_depsgraph_get()
    drogon_eval = drogon_obj.evaluated_get(depsgraph)
    drogon_mesh = drogon_eval.to_mesh()

    # Build BVH in world space
    drogon_world = drogon_obj.matrix_world
    verts_world = [drogon_world @ v.co for v in drogon_mesh.vertices]
    polys = [list(p.vertices) for p in drogon_mesh.polygons]

    bvh = BVHTree.FromPolygons(verts_world, polys)
    print(f"  BVH built: {len(verts_world)} verts, {len(polys)} faces")

    # --- Process each CD vertex ---
    print("\n  Projecting CD vertices onto Drogon surface...")

    new_game_positions = []   # game-space (x, y, z) for each CD vertex
    new_bone_data = []        # (indices_4, weights_4) for each CD vertex

    total_projected = 0
    total_missed = 0
    progress_step = max(1, TOTAL_VERTS // 20)

    for sm_idx in range(8):
        sm_name = SUBMESH_NAMES[sm_idx]
        base = SUBMESH_BASES[sm_idx]
        count = SUBMESH_VERTEX_COUNTS[sm_idx]
        bbox = bboxes[sm_idx]

        for j in range(count):
            vi = base + j
            if vi % progress_step == 0:
                print(f"    {vi * 100 // TOTAL_VERTS}% ({vi}/{TOTAL_VERTS})", end='\r')

            # Read original CD vertex position
            off = VB_START + vi * STRIDE
            u16_x, u16_y, u16_z = struct.unpack_from('<3H', pac, off)
            gx, gy, gz = dequantize(u16_x, u16_y, u16_z, bbox)

            # Convert to Blender space
            blender_pos = game_to_blender(gx, gy, gz)

            # Find nearest point on Drogon surface
            hit_pos, hit_normal, hit_face, hit_dist = bvh.find_nearest(blender_pos)

            if hit_pos is not None and hit_face is not None:
                # Use the projected position
                new_gx, new_gy, new_gz = blender_to_game(hit_pos.x, hit_pos.y, hit_pos.z)
                new_game_positions.append((new_gx, new_gy, new_gz))

                # Transfer bone weights from Drogon
                weights = interpolate_weights_from_face(drogon_obj, hit_face, hit_pos)
                bi, bw = weights_to_pac_format(weights, name_to_palette_idx)
                new_bone_data.append((bi, bw))

                total_projected += 1
            else:
                # No hit — keep original position and weights
                new_game_positions.append((gx, gy, gz))
                orig_bi = struct.unpack_from('4B', pac, off + 12)
                orig_bw = struct.unpack_from('4B', pac, off + 20)
                new_bone_data.append((orig_bi, orig_bw))
                total_missed += 1

    print(f"    100% ({TOTAL_VERTS}/{TOTAL_VERTS})")
    print(f"  Projected: {total_projected}, Missed: {total_missed}")

    # --- Compute new bboxes and write PAC ---
    print("\n  Writing PAC...")

    for sm_idx in range(8):
        sm_name = SUBMESH_NAMES[sm_idx]
        base = SUBMESH_BASES[sm_idx]
        count = SUBMESH_VERTEX_COUNTS[sm_idx]
        old_bbox = bboxes[sm_idx]

        # Compute new bbox for this submesh
        sm_positions = new_game_positions[base:base + count]
        xs = [p[0] for p in sm_positions]
        ys = [p[1] for p in sm_positions]
        zs = [p[2] for p in sm_positions]

        PAD = 0.001
        new_min = (min(xs) - PAD, min(ys) - PAD, min(zs) - PAD)
        new_max = (max(xs) + PAD, max(ys) + PAD, max(zs) + PAD)
        new_dim = (new_max[0] - new_min[0], new_max[1] - new_min[1], new_max[2] - new_min[2])

        # Patch bbox in descriptor
        bbox_off = bbox_offsets[sm_idx]
        struct.pack_into('<2f', pac, bbox_off, old_bbox['lod_near'], old_bbox['lod_far'])
        struct.pack_into('<3f', pac, bbox_off + 8, *new_min)
        struct.pack_into('<3f', pac, bbox_off + 20, *new_dim)

        # Patch vertex positions and bone data
        for j in range(count):
            vi = base + j
            off = VB_START + vi * STRIDE

            gx, gy, gz = new_game_positions[vi]
            qx, qy, qz = quantize(gx, gy, gz, new_min, new_dim)
            struct.pack_into('<3H', pac, off, qx, qy, qz)

            # Write bone indices and weights
            bi, bw = new_bone_data[vi]
            struct.pack_into('4B', pac, off + 12, *bi)
            struct.pack_into('4B', pac, off + 20, *bw)

        print(f"  {sm_name:12s}: {count} verts patched")

    # --- Write output ---
    OUTPUT_PAC.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PAC.write_bytes(pac)
    out_size = OUTPUT_PAC.stat().st_size
    expected = PAC_PATH.stat().st_size

    print(f"\n  Output: {OUTPUT_PAC}")
    print(f"  Size: {out_size:,} bytes {'[OK]' if out_size == expected else '[SIZE MISMATCH]'}")

    # --- Optional deploy ---
    if DEPLOY:
        print("\n  Deploying to game...")
        import sys
        sys.path.insert(0, str(ROOT / "tools"))
        from pac_patcher import deploy_pac
        deploy_pac(str(OUTPUT_PAC))

    print("\n" + "=" * 60)
    print("  EXPORT COMPLETE")
    print("=" * 60)
    print(f"  PAC: {OUTPUT_PAC.name}")
    print(f"  Verts: {TOTAL_VERTS} (topology preserved)")
    print(f"  Projected: {total_projected} / Missed: {total_missed}")
    print("")
    print("  TO DEPLOY TO GAME:")
    print(f"  Set DEPLOY = True and re-run, or run:")
    print(f"  python tools/pac_patcher.py --deploy")
    print("=" * 60)


if __name__ == '__main__':
    main()
