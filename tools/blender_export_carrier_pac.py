"""
Export an edited CD carrier mesh back into the Crimson Desert PAC.

This is the clean carrier workflow:
  - CD topology stays unchanged
  - CD weights stay unchanged
  - CD indices stay unchanged
  - only positions, normals, and submesh bboxes are updated

Run after editing CD_Carrier in Blender.
"""

from __future__ import annotations

import math
import struct
from pathlib import Path

import bpy
from mathutils import Vector


ROOT = Path(r"C:\Users\user\crimson-desert-got-dragon-mod")
ORIGINAL_PAC = ROOT / "output" / "dragon.pac"
OUTPUT_PAC = ROOT / "output" / "dragon_drogon_final.pac"
OUTPUT_OBJ = ROOT / "output" / "dragon_drogon_carrier.obj"

ARMATURE_NAME = "CD_Dragon"
CARRIER_NAME = "CD_Carrier"
SCALE = 4.0

VB_START = 0x7BFA
STRIDE = 40
TOTAL_VERTS = 30112
EXPECTED_PAC_SIZE = 5_208_284

SUBMESH_NAMES = ["Eyeright", "Eyeleft", "Body_02", "back", "Body", "Leg", "Wing", "Head"]
SUBMESH_VERTEX_COUNTS = [225, 225, 2013, 3307, 2736, 4624, 6724, 10258]

SUBMESH_BASES = []
_base = 0
for _vc in SUBMESH_VERTEX_COUNTS:
    SUBMESH_BASES.append(_base)
    _base += _vc


def blender_to_game_pos(bx: float, by: float, bz: float) -> tuple[float, float, float]:
    return (bx / SCALE, bz / SCALE, -by / SCALE)


def blender_to_game_normal(nx: float, ny: float, nz: float) -> tuple[float, float, float]:
    return (nx, nz, -ny)


def encode_normal_r10g10b10a2(nx: float, ny: float, nz: float) -> int:
    def clamp_encode(v: float) -> int:
        return max(0, min(1023, int(round((v + 1.0) / 2.0 * 1023.0))))

    return clamp_encode(nx) | (clamp_encode(ny) << 10) | (clamp_encode(nz) << 20)


def quantize_pos(x: float, y: float, z: float,
                 bbox_min: tuple[float, float, float],
                 bbox_dim: tuple[float, float, float]) -> tuple[int, int, int]:
    def q(val: float, bmin: float, bdim: float) -> int:
        if abs(bdim) < 1e-10:
            return 0
        return max(0, min(65535, int(round((val - bmin) / bdim * 32767.0))))

    return (
        q(x, bbox_min[0], bbox_dim[0]),
        q(y, bbox_min[1], bbox_dim[1]),
        q(z, bbox_min[2], bbox_dim[2]),
    )


def find_bbox_offsets(pac: bytes) -> list[int]:
    offsets = []
    off = 0x0077
    for _ in range(8):
        name_len = pac[off]
        off += 1 + name_len
        mat_len = pac[off]
        off += 1 + mat_len
        off += 3
        offsets.append(off)
        off += 32
        next_cd = pac.find(b"CD_M0004", off)
        off = (next_cd - 1) if (0 < next_cd < 0x0441) else 0x0441
    return offsets


def read_bbox_at(pac: bytes, offset: int) -> dict[str, tuple[float, float, float] | float]:
    floats = struct.unpack_from("<8f", pac, offset)
    return {
        "lod_near": floats[0],
        "lod_far": floats[1],
        "min": (floats[2], floats[3], floats[4]),
        "dim": (floats[5], floats[6], floats[7]),
    }


def ensure_rest_pose() -> bool:
    arm_obj = bpy.data.objects.get(ARMATURE_NAME)
    if arm_obj is None or arm_obj.type != "ARMATURE":
        print(f"ERROR: '{ARMATURE_NAME}' armature not found.")
        return False

    if arm_obj.data.pose_position != "REST":
        print(f"ERROR: '{ARMATURE_NAME}' is not in REST pose.")
        print("       Set Armature Data > Skeleton > Rest Position, then export again.")
        return False

    return True


def export_pac() -> None:
    print("=" * 60)
    print("  CARRIER -> PAC EXPORT")
    print("=" * 60)

    if not ensure_rest_pose():
        return

    obj = bpy.data.objects.get(CARRIER_NAME)
    if obj is None or obj.type != "MESH":
        print(f"ERROR: '{CARRIER_NAME}' mesh not found.")
        return

    pac_orig = bytearray(ORIGINAL_PAC.read_bytes())
    if len(pac_orig) != EXPECTED_PAC_SIZE:
        print(f"WARNING: expected PAC size {EXPECTED_PAC_SIZE}, got {len(pac_orig)}")

    depsgraph = bpy.context.evaluated_depsgraph_get()
    obj_eval = obj.evaluated_get(depsgraph)
    mesh = obj_eval.to_mesh()

    vert_count = len(mesh.vertices)
    print(f"Carrier vertices: {vert_count}")
    if vert_count != TOTAL_VERTS:
        print(f"ERROR: expected {TOTAL_VERTS} vertices, got {vert_count}.")
        obj_eval.to_mesh_clear()
        return

    mesh.calc_normals_split()

    vert_normals = [Vector((0, 0, 0)) for _ in range(vert_count)]
    vert_normal_counts = [0] * vert_count
    for loop in mesh.loops:
        vi = loop.vertex_index
        vert_normals[vi] += Vector(loop.normal)
        vert_normal_counts[vi] += 1

    for i in range(vert_count):
        if vert_normal_counts[i] > 0:
            vert_normals[i] /= vert_normal_counts[i]
            if vert_normals[i].length > 1e-8:
                vert_normals[i].normalize()

    game_positions = []
    game_normals = []
    for i, vert in enumerate(mesh.vertices):
        gx, gy, gz = blender_to_game_pos(vert.co.x, vert.co.y, vert.co.z)
        game_positions.append((gx, gy, gz))

        gnx, gny, gnz = blender_to_game_normal(
            vert_normals[i].x,
            vert_normals[i].y,
            vert_normals[i].z,
        )
        length = math.sqrt(gnx * gnx + gny * gny + gnz * gnz)
        if length > 1e-8:
            gnx /= length
            gny /= length
            gnz /= length
        game_normals.append((gnx, gny, gnz))

    obj_eval.to_mesh_clear()

    bbox_offsets = find_bbox_offsets(pac_orig)
    new_bboxes = []

    print("\nPer-submesh bbox updates:")
    for si, name in enumerate(SUBMESH_NAMES):
        base = SUBMESH_BASES[si]
        count = SUBMESH_VERTEX_COUNTS[si]
        old_bbox = read_bbox_at(pac_orig, bbox_offsets[si])
        sm_positions = game_positions[base:base + count]

        min_x = min(p[0] for p in sm_positions)
        min_y = min(p[1] for p in sm_positions)
        min_z = min(p[2] for p in sm_positions)
        max_x = max(p[0] for p in sm_positions)
        max_y = max(p[1] for p in sm_positions)
        max_z = max(p[2] for p in sm_positions)

        pad = 0.001
        min_x -= pad
        min_y -= pad
        min_z -= pad
        max_x += pad
        max_y += pad
        max_z += pad

        new_min = (min_x, min_y, min_z)
        new_dim = (max_x - min_x, max_y - min_y, max_z - min_z)
        new_bboxes.append((new_min, new_dim))

        print(
            f"  {name:12s} old_dim=({old_bbox['dim'][0]:7.3f},{old_bbox['dim'][1]:7.3f},{old_bbox['dim'][2]:7.3f}) "
            f"new_dim=({new_dim[0]:7.3f},{new_dim[1]:7.3f},{new_dim[2]:7.3f})"
        )

    for si in range(len(SUBMESH_NAMES)):
        off = bbox_offsets[si]
        old_bbox = read_bbox_at(pac_orig, off)
        new_min, new_dim = new_bboxes[si]
        struct.pack_into("<2f", pac_orig, off, old_bbox["lod_near"], old_bbox["lod_far"])
        struct.pack_into("<3f", pac_orig, off + 8, *new_min)
        struct.pack_into("<3f", pac_orig, off + 20, *new_dim)

    patched_count = 0
    for si in range(len(SUBMESH_NAMES)):
        base = SUBMESH_BASES[si]
        count = SUBMESH_VERTEX_COUNTS[si]
        new_min, new_dim = new_bboxes[si]

        for j in range(count):
            vi = base + j
            vb_off = VB_START + vi * STRIDE

            gx, gy, gz = game_positions[vi]
            qx, qy, qz = quantize_pos(gx, gy, gz, new_min, new_dim)
            struct.pack_into("<3H", pac_orig, vb_off, qx, qy, qz)

            gnx, gny, gnz = game_normals[vi]
            struct.pack_into("<I", pac_orig, vb_off + 8, encode_normal_r10g10b10a2(gnx, gny, gnz))
            patched_count += 1

    OUTPUT_PAC.write_bytes(pac_orig)

    with open(OUTPUT_OBJ, "w", encoding="utf-8") as f:
        f.write("# Carrier export preview\n")
        f.write(f"# {TOTAL_VERTS} vertices\n\n")
        for gx, gy, gz in game_positions:
            f.write(f"v {gx:.6f} {gy:.6f} {gz:.6f}\n")
        vert_offset = 1
        for si, name in enumerate(SUBMESH_NAMES):
            count = SUBMESH_VERTEX_COUNTS[si]
            f.write(f"\ng {name}\n")
            f.write("p " + " ".join(str(vert_offset + j) for j in range(count)) + "\n")
            vert_offset += count

    out_size = OUTPUT_PAC.stat().st_size
    print("\n" + "=" * 60)
    print("  EXPORT COMPLETE")
    print("=" * 60)
    print(f"  PAC: {OUTPUT_PAC}")
    print(f"  Preview: {OUTPUT_OBJ}")
    print(f"  Vertices patched: {patched_count}")
    print(f"  Size: {out_size:,} bytes {'[OK]' if out_size == EXPECTED_PAC_SIZE else '[BAD]'}")
    print("")
    print("  Next:")
    print("  python tools/deploy_new_pac.py")
    print("=" * 60)


if __name__ == "__main__":
    export_pac()
