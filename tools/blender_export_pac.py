"""
Blender PAC Export — write modified dragon mesh back to Crimson Desert PAC.

Run inside Blender after applying the Shrinkwrap modifier on CD_Mesh.
Reads final vertex positions, reverses Blender coordinate transform,
recomputes normals and bounding boxes, patches original PAC.

Usage:
  1. Open Blender scene created by the setup script
  2. Select CD_Mesh, apply Shrinkwrap modifier (Ctrl+A)
  3. Run this script from Blender's scripting workspace
"""

import struct
import math
from pathlib import Path

import bpy
import bmesh
from mathutils import Vector

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
ROOT = Path(r"C:\Users\waelj\got-dragon-cd-mod")
ORIGINAL_PAC = ROOT / "output" / "dragon.pac"
OUTPUT_PAC = ROOT / "output" / "dragon_drogon_blender.pac"
OUTPUT_OBJ = ROOT / "output" / "dragon_drogon_blender.obj"
CD_MESH_NAME = "CD_Mesh"
SCALE = 4.0

# Deployment integration added separately
DEPLOY = False

# ---------------------------------------------------------------------------
# PAC constants
# ---------------------------------------------------------------------------
VB_START = 0x7BFA       # vertex buffer start offset
STRIDE = 40             # bytes per vertex
TOTAL_VERTS = 30112

SUBMESH_NAMES = ["Eyeright", "Eyeleft", "Body_02", "back", "Body", "Leg", "Wing", "Head"]
SUBMESH_VERTEX_COUNTS = [225, 225, 2013, 3307, 2736, 4624, 6724, 10258]

# Contiguous vertex bases
SUBMESH_BASES = []
_base = 0
for _vc in SUBMESH_VERTEX_COUNTS:
    SUBMESH_BASES.append(_base)
    _base += _vc

EXPECTED_PAC_SIZE = 5_208_284


# ---------------------------------------------------------------------------
# Coordinate transform: Blender (Z-up, 4x scale) -> Game (Y-up, 1x)
# ---------------------------------------------------------------------------
def blender_to_game_pos(bx, by, bz):
    """Reverse the import transform for positions."""
    return (bx / SCALE, bz / SCALE, -by / SCALE)


def blender_to_game_normal(nx, ny, nz):
    """Reverse the import transform for normals (axis swap only, no scale)."""
    return (nx, nz, -ny)


# ---------------------------------------------------------------------------
# PAC encoding helpers (inline — no imports from sibling files)
# ---------------------------------------------------------------------------
def encode_normal_r10g10b10a2(nx, ny, nz):
    """Encode unit normal to R10G10B10A2 packed uint32."""
    def clamp_encode(v):
        return max(0, min(1023, int(round((v + 1.0) / 2.0 * 1023.0))))
    return clamp_encode(nx) | (clamp_encode(ny) << 10) | (clamp_encode(nz) << 20)


def quantize_pos(x, y, z, bbox_min, bbox_dim):
    """Quantize float position to 3x uint16 using submesh bbox."""
    def q(val, bmin, bdim):
        if abs(bdim) < 1e-10:
            return 0
        return max(0, min(65535, int(round((val - bmin) / bdim * 32767.0))))
    return (
        q(x, bbox_min[0], bbox_dim[0]),
        q(y, bbox_min[1], bbox_dim[1]),
        q(z, bbox_min[2], bbox_dim[2]),
    )


# ---------------------------------------------------------------------------
# Bbox discovery in PAC descriptor
# ---------------------------------------------------------------------------
def find_bbox_offsets(pac):
    """Return byte offsets of each submesh's 8-float bbox block in the PAC descriptor.

    Each block is: [lod_near, lod_far, min_x, min_y, min_z, dim_x, dim_y, dim_z]
    """
    offsets = []
    off = 0x0077
    for i in range(8):
        name_len = pac[off]; off += 1 + name_len
        mat_len = pac[off]; off += 1 + mat_len
        off += 3  # flag bytes
        offsets.append(off)  # 8 floats start here
        off += 32
        next_cd = pac.find(b'CD_M0004', off)
        if next_cd > 0 and next_cd < 0x0441:
            off = next_cd - 1
        else:
            off = 0x0441
    return offsets


def read_bbox_at(pac, offset):
    """Read the 8-float bbox block at the given offset."""
    floats = struct.unpack_from('<8f', pac, offset)
    return {
        'lod_near': floats[0],
        'lod_far': floats[1],
        'min': (floats[2], floats[3], floats[4]),
        'dim': (floats[5], floats[6], floats[7]),
    }


# ---------------------------------------------------------------------------
# Main export
# ---------------------------------------------------------------------------
def export_pac():
    print("=" * 60)
    print("BLENDER PAC EXPORT — Crimson Desert Dragon Mesh Swap")
    print("=" * 60)

    # --- Validate scene ---
    obj = bpy.data.objects.get(CD_MESH_NAME)
    if obj is None:
        print(f"ERROR: Object '{CD_MESH_NAME}' not found in scene.")
        return

    # Check for unapplied Shrinkwrap
    for mod in obj.modifiers:
        if mod.type == 'SHRINKWRAP':
            print(f"WARNING: Shrinkwrap modifier '{mod.name}' is still active!")
            print("         You must APPLY it first (Ctrl+A) before exporting.")
            print("         Export aborted.")
            return

    # --- Read original PAC ---
    if not ORIGINAL_PAC.exists():
        print(f"ERROR: Original PAC not found at {ORIGINAL_PAC}")
        return

    pac_orig = bytearray(ORIGINAL_PAC.read_bytes())
    print(f"Original PAC: {len(pac_orig)} bytes")

    if len(pac_orig) != EXPECTED_PAC_SIZE:
        print(f"WARNING: Expected {EXPECTED_PAC_SIZE} bytes, got {len(pac_orig)}")

    # --- Get evaluated mesh (with all modifiers applied) ---
    depsgraph = bpy.context.evaluated_depsgraph_get()
    obj_eval = obj.evaluated_get(depsgraph)
    mesh = obj_eval.to_mesh()

    vert_count = len(mesh.vertices)
    print(f"Blender mesh vertices: {vert_count}")

    if vert_count != TOTAL_VERTS:
        print(f"ERROR: Expected {TOTAL_VERTS} vertices, got {vert_count}. Mesh mismatch.")
        obj_eval.to_mesh_clear()
        return

    # --- Compute per-vertex normals ---
    mesh.calc_normals_split()

    # We need per-vertex normals. Since calc_normals_split gives per-loop normals,
    # average them per vertex.
    vert_normals = [Vector((0, 0, 0)) for _ in range(vert_count)]
    vert_normal_counts = [0] * vert_count
    for loop in mesh.loops:
        vi = loop.vertex_index
        vert_normals[vi] += Vector(loop.normal)
        vert_normal_counts[vi] += 1

    for i in range(vert_count):
        if vert_normal_counts[i] > 0:
            vert_normals[i] /= vert_normal_counts[i]
            vert_normals[i].normalize()

    # --- Extract positions and normals in game space ---
    game_positions = []
    game_normals = []

    for i, vert in enumerate(mesh.vertices):
        bx, by, bz = vert.co.x, vert.co.y, vert.co.z
        gx, gy, gz = blender_to_game_pos(bx, by, bz)
        game_positions.append((gx, gy, gz))

        nx, ny, nz = vert_normals[i].x, vert_normals[i].y, vert_normals[i].z
        gnx, gny, gnz = blender_to_game_normal(nx, ny, nz)
        # Re-normalize after axis swap (should be fine but be safe)
        length = math.sqrt(gnx*gnx + gny*gny + gnz*gnz)
        if length > 1e-8:
            gnx /= length; gny /= length; gnz /= length
        game_normals.append((gnx, gny, gnz))

    obj_eval.to_mesh_clear()

    # --- Compute per-submesh bounding boxes ---
    print("\nPer-submesh bounding box changes:")
    print(f"  {'Submesh':12s}  {'Old min':>36s}  {'New min':>36s}")

    bbox_offsets = find_bbox_offsets(pac_orig)
    new_bboxes = []  # list of (min_xyz, dim_xyz)

    for si in range(len(SUBMESH_NAMES)):
        name = SUBMESH_NAMES[si]
        base = SUBMESH_BASES[si]
        count = SUBMESH_VERTEX_COUNTS[si]

        # Read old bbox
        old_bbox = read_bbox_at(pac_orig, bbox_offsets[si])

        # Compute new bbox from game-space positions
        sm_positions = game_positions[base:base + count]

        min_x = min(p[0] for p in sm_positions)
        min_y = min(p[1] for p in sm_positions)
        min_z = min(p[2] for p in sm_positions)
        max_x = max(p[0] for p in sm_positions)
        max_y = max(p[1] for p in sm_positions)
        max_z = max(p[2] for p in sm_positions)

        # Add small padding to avoid edge quantization issues
        PAD = 0.001
        min_x -= PAD; min_y -= PAD; min_z -= PAD
        max_x += PAD; max_y += PAD; max_z += PAD

        dim_x = max_x - min_x
        dim_y = max_y - min_y
        dim_z = max_z - min_z

        new_min = (min_x, min_y, min_z)
        new_dim = (dim_x, dim_y, dim_z)
        new_bboxes.append((new_min, new_dim))

        print(f"  {name:12s}  old=({old_bbox['min'][0]:8.4f},{old_bbox['min'][1]:8.4f},{old_bbox['min'][2]:8.4f})  "
              f"new=({min_x:8.4f},{min_y:8.4f},{min_z:8.4f})")
        print(f"  {'':12s}  dim=({old_bbox['dim'][0]:8.4f},{old_bbox['dim'][1]:8.4f},{old_bbox['dim'][2]:8.4f})  "
              f"dim=({dim_x:8.4f},{dim_y:8.4f},{dim_z:8.4f})")

    # --- Patch PAC: bounding boxes ---
    for si in range(len(SUBMESH_NAMES)):
        off = bbox_offsets[si]
        old_bbox = read_bbox_at(pac_orig, off)
        new_min, new_dim = new_bboxes[si]

        # Write: lod_near, lod_far (preserve), then min_x/y/z, dim_x/y/z
        struct.pack_into('<2f', pac_orig, off, old_bbox['lod_near'], old_bbox['lod_far'])
        struct.pack_into('<3f', pac_orig, off + 8, new_min[0], new_min[1], new_min[2])
        struct.pack_into('<3f', pac_orig, off + 20, new_dim[0], new_dim[1], new_dim[2])

    # --- Patch PAC: vertex positions and normals ---
    patched_count = 0
    for si in range(len(SUBMESH_NAMES)):
        base = SUBMESH_BASES[si]
        count = SUBMESH_VERTEX_COUNTS[si]
        new_min, new_dim = new_bboxes[si]

        for j in range(count):
            vi = base + j
            vb_off = VB_START + vi * STRIDE

            # Quantize new position
            gx, gy, gz = game_positions[vi]
            qx, qy, qz = quantize_pos(gx, gy, gz, new_min, new_dim)
            struct.pack_into('<3H', pac_orig, vb_off, qx, qy, qz)
            # Bytes 6-7 (W) preserved — no write needed

            # Encode new normal
            gnx, gny, gnz = game_normals[vi]
            packed_normal = encode_normal_r10g10b10a2(gnx, gny, gnz)
            struct.pack_into('<I', pac_orig, vb_off + 8, packed_normal)

            patched_count += 1

    print(f"\nPatched {patched_count} vertices")

    # --- Write output PAC ---
    OUTPUT_PAC.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PAC.write_bytes(pac_orig)
    out_size = OUTPUT_PAC.stat().st_size
    print(f"\nOutput PAC: {OUTPUT_PAC}")
    print(f"  Size: {out_size} bytes", end="")
    if out_size == EXPECTED_PAC_SIZE:
        print("  [OK — matches original]")
    else:
        print(f"  [ERROR — expected {EXPECTED_PAC_SIZE}]")

    # --- Write preview OBJ ---
    with open(OUTPUT_OBJ, 'w') as f:
        f.write("# Blender export preview — game-space positions\n")
        f.write(f"# {TOTAL_VERTS} vertices, {len(SUBMESH_NAMES)} submeshes\n\n")

        for si in range(len(SUBMESH_NAMES)):
            name = SUBMESH_NAMES[si]
            base = SUBMESH_BASES[si]
            count = SUBMESH_VERTEX_COUNTS[si]
            f.write(f"# {name}: {count} verts\n")
            for j in range(count):
                gx, gy, gz = game_positions[base + j]
                f.write(f"v {gx:.6f} {gy:.6f} {gz:.6f}\n")

        # Write submesh groups as point clouds (no faces — indices not modified)
        vert_offset = 1
        for si in range(len(SUBMESH_NAMES)):
            name = SUBMESH_NAMES[si]
            count = SUBMESH_VERTEX_COUNTS[si]
            f.write(f"\ng {name}\n")
            indices_str = " ".join(str(vert_offset + j) for j in range(count))
            f.write(f"p {indices_str}\n")
            vert_offset += count

    print(f"Preview OBJ: {OUTPUT_OBJ}")

    # --- Summary ---
    print("\n" + "=" * 60)
    print("EXPORT COMPLETE")
    print(f"  PAC: {OUTPUT_PAC}")
    print(f"  OBJ: {OUTPUT_OBJ}")
    print(f"  Vertices patched: {patched_count}")
    print(f"  PAC size match: {'YES' if out_size == EXPECTED_PAC_SIZE else 'NO'}")
    print("=" * 60)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    export_pac()
