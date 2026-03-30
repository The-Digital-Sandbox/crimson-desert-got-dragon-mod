#!/usr/bin/env python3
"""
PAC mesh patcher — modify dragon geometry and write back to PAC.

Proof of concept: apply transformations to submesh vertices,
recompute bboxes, and write a modified PAC file.
"""
import struct
import math
import shutil
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent))
from pac_codec import (
    PAC_PATH, OUTPUT, VB_START, STRIDE, TOTAL_VERTS,
    SUBMESH_NAMES, SUBMESH_VERTEX_COUNTS, SUBMESH_BASES,
    parse_submesh_descriptors, decode_all_submeshes,
    quantize_pos, encode_normal_r10g10b10a2, SubmeshBbox,
)

# The 8 float32 bbox values (lod_near, lod_far, min_x, min_y, min_z, dim_x, dim_y, dim_z)
# start at specific offsets in the PAC after each submesh's material name.
# We need to find these offsets to patch them.


def find_bbox_offsets(pac: bytes) -> list[int]:
    """Find the byte offset of each submesh's 8-float bbox block in the PAC."""
    offsets = []
    off = 0x0077

    for i in range(8):
        name_len = pac[off]
        off += 1 + name_len

        mat_len = pac[off]
        off += 1 + mat_len

        # 3 flag bytes
        off += 3

        # This is where the 8 floats start
        offsets.append(off)
        off += 32  # skip 8 float32

        # Skip trailing data
        next_cd = pac.find(b'CD_M0004', off)
        if next_cd > 0 and next_cd < 0x0441:
            off = next_cd - 1
        else:
            off = 0x0441

    return offsets


def patch_pac(transforms: dict, output_path: str = None):
    """
    Apply transforms to submesh vertices and write modified PAC.

    transforms: dict of submesh_name -> transform function
        Each function takes (x, y, z) and returns (x, y, z)
    """
    pac = bytearray(PAC_PATH.read_bytes())
    bboxes = parse_submesh_descriptors(bytes(pac))
    bbox_offsets = find_bbox_offsets(bytes(pac))

    if output_path is None:
        output_path = str(OUTPUT / "dragon_patched.pac")

    for i, (name, bbox) in enumerate(zip(SUBMESH_NAMES, bboxes)):
        if name not in transforms:
            continue

        transform = transforms[name]
        base = SUBMESH_BASES[i]
        count = SUBMESH_VERTEX_COUNTS[i]

        print(f"Patching {name}: {count} verts...")

        # Step 1: Decode all positions
        positions = []
        for j in range(count):
            off = VB_START + (base + j) * STRIDE
            u16_x, u16_y, u16_z = struct.unpack_from('<3H', pac, off)
            x = bbox.min_xyz[0] + (u16_x / 32767.0) * bbox.dim_xyz[0]
            y = bbox.min_xyz[1] + (u16_y / 32767.0) * bbox.dim_xyz[1]
            z = bbox.min_xyz[2] + (u16_z / 32767.0) * bbox.dim_xyz[2]
            positions.append(transform(x, y, z))

        # Step 2: Compute new bbox from transformed positions
        xs = [p[0] for p in positions]
        ys = [p[1] for p in positions]
        zs = [p[2] for p in positions]

        new_min = (min(xs), min(ys), min(zs))
        new_max = (max(xs), max(ys), max(zs))
        # Add tiny padding to avoid division by zero
        eps = 1e-6
        new_dim = (
            max(eps, new_max[0] - new_min[0]),
            max(eps, new_max[1] - new_min[1]),
            max(eps, new_max[2] - new_min[2]),
        )

        new_bbox = SubmeshBbox(name=name, min_xyz=new_min, dim_xyz=new_dim,
                               lod_near=bbox.lod_near, lod_far=bbox.lod_far)

        print(f"  Old bbox: min=({bbox.min_xyz[0]:.4f},{bbox.min_xyz[1]:.4f},{bbox.min_xyz[2]:.4f}) dim=({bbox.dim_xyz[0]:.4f},{bbox.dim_xyz[1]:.4f},{bbox.dim_xyz[2]:.4f})")
        print(f"  New bbox: min=({new_min[0]:.4f},{new_min[1]:.4f},{new_min[2]:.4f}) dim=({new_dim[0]:.4f},{new_dim[1]:.4f},{new_dim[2]:.4f})")

        # Step 3: Quantize transformed positions with new bbox
        for j in range(count):
            off = VB_START + (base + j) * STRIDE
            x, y, z = positions[j]
            qx, qy, qz = quantize_pos(x, y, z, new_bbox)
            struct.pack_into('<3H', pac, off, qx, qy, qz)

        # Step 4: Write new bbox to PAC descriptor
        bbox_off = bbox_offsets[i]
        # Keep LOD values, write new min + dim
        struct.pack_into('<2f', pac, bbox_off, bbox.lod_near, bbox.lod_far)
        struct.pack_into('<3f', pac, bbox_off + 8, *new_min)
        struct.pack_into('<3f', pac, bbox_off + 20, *new_dim)

    # Write output
    with open(output_path, 'wb') as f:
        f.write(pac)
    print(f"\nWrote patched PAC: {output_path}")
    print(f"Size: {len(pac):,} bytes (should match original: {PAC_PATH.stat().st_size:,})")

    return output_path


def main():
    # Proof-of-concept: scale the head 1.5x and horns 2x in all axes
    # relative to their respective centers
    def make_scale_transform(scale_x, scale_y, scale_z, center=None):
        def transform(x, y, z):
            if center:
                return (
                    center[0] + (x - center[0]) * scale_x,
                    center[1] + (y - center[1]) * scale_y,
                    center[2] + (z - center[2]) * scale_z,
                )
            return (x * scale_x, y * scale_y, z * scale_z)
        return transform

    # Read original to find submesh centers
    pac = PAC_PATH.read_bytes()
    data = decode_all_submeshes(pac)

    def get_center(name):
        verts = data[name]['verts']
        xs = [v.pos[0] for v in verts]
        ys = [v.pos[1] for v in verts]
        zs = [v.pos[2] for v in verts]
        return ((min(xs)+max(xs))/2, (min(ys)+max(ys))/2, (min(zs)+max(zs))/2)

    head_center = get_center('Head')
    horns_center = get_center('Body_02')

    transforms = {
        'Head': make_scale_transform(1.5, 1.5, 1.5, head_center),
        'Body_02': make_scale_transform(2.0, 2.0, 2.0, horns_center),
    }

    print("=" * 60)
    print("PAC MESH PATCHER - Proof of Concept")
    print("Scaling Head 1.5x and Horns/Spikes 2.0x")
    print("=" * 60)

    pac_path = patch_pac(transforms)

    if '--deploy' in sys.argv:
        deploy_pac(pac_path)
    else:
        print("\nAdd --deploy to patch game files.")
        print("Add --restore to restore original PAC.")


# ── Deployment ──────────────────────────────────────────────────────

PAZ_DIR = r"C:\Program Files (x86)\Steam\steamapps\common\Crimson Desert\0009"
PAZ_FILE = PAZ_DIR + r"\3.paz"
PAC_OFFSET = 0x2DCAD1D0
PAC_SIZE = 5_208_284


def deploy_pac(pac_path: str):
    """Write patched PAC directly into the PAZ archive."""
    import ctypes

    with open(pac_path, 'rb') as f:
        data = f.read()

    if len(data) != PAC_SIZE:
        print(f"ERROR: PAC size mismatch: {len(data)} != {PAC_SIZE}")
        return False

    # Backup original first (once)
    backup_path = Path(OUTPUT / "dragon_original.pac")
    if not backup_path.exists():
        print(f"Backing up original PAC to {backup_path}...")
        with open(PAZ_FILE, 'rb') as f:
            f.seek(PAC_OFFSET)
            original = f.read(PAC_SIZE)
        backup_path.write_bytes(original)

    # Save timestamps
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)

    class FILETIME(ctypes.Structure):
        _fields_ = [("lo", ctypes.c_uint32), ("hi", ctypes.c_uint32)]

    h = kernel32.CreateFileW(PAZ_FILE, 0x80000000, 1, None, 3, 0x80, None)
    ct, at, mt = FILETIME(), FILETIME(), FILETIME()
    if h != -1:
        kernel32.GetFileTime(h, ctypes.byref(ct), ctypes.byref(at), ctypes.byref(mt))
        kernel32.CloseHandle(h)
    else:
        ct = at = mt = None

    # Write
    with open(PAZ_FILE, 'r+b') as f:
        f.seek(PAC_OFFSET)
        f.write(data)

    # Restore timestamps
    if ct is not None:
        h = kernel32.CreateFileW(PAZ_FILE, 0x40000000, 0, None, 3, 0x80, None)
        if h != -1:
            kernel32.SetFileTime(h, ctypes.byref(ct), ctypes.byref(at), ctypes.byref(mt))
            kernel32.CloseHandle(h)

    print(f"Deployed PAC ({len(data):,} bytes) to {PAZ_FILE} @ 0x{PAC_OFFSET:X}")
    return True


def restore_pac():
    """Restore original PAC from backup."""
    backup_path = Path(OUTPUT / "dragon_original.pac")
    if not backup_path.exists():
        print("ERROR: No backup found. Cannot restore.")
        return False

    deploy_pac(str(backup_path))
    print("Original PAC restored.")
    return True


if __name__ == "__main__":
    import sys
    if '--restore' in sys.argv:
        restore_pac()
    else:
        main()
