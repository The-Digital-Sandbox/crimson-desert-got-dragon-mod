#!/usr/bin/env python3
"""
Drogon mesh swap v4 — PIX world-space projection with empirical bone matrices.

1. Use PIX world-space CD dragon as ground truth
2. Align Drogon OBJ to PIX world space
3. For each CD vertex, find nearest Drogon point (world space)
4. Convert new_world → bone-local using empirical per-bone inverse matrices
5. Encode to PAC
"""
import struct
import csv
import os
import sys
import json
import pickle
import numpy as np
from scipy.spatial import KDTree
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from pac_codec import (
    PAC_PATH, OUTPUT, VB_START, STRIDE,
    SUBMESH_NAMES, SUBMESH_VERTEX_COUNTS, SUBMESH_BASES,
    parse_submesh_descriptors, decode_all_submeshes, quantize_pos,
    SubmeshBbox, read_indices,
)
from pac_patcher import find_bbox_offsets, deploy_pac

DROGON_OBJ = r"C:\Users\user\Desktop\Outputs\DROGON.OBJ"
PIX_DIR = r"C:\Users\user\Desktop\Outputs"
PIX_MAP = {
    '7153': ('Body_02', 2),
    '7154': ('back', 3),
    '7155': ('Body', 4),
    '7156': ('Leg', 5),
    '7157': ('Wing', 6),
    '7158': ('Head', 7),
}


def load_drogon_verts(path):
    verts = []
    with open(path, 'r') as f:
        for line in f:
            if line.startswith('v '):
                p = line.split()
                verts.append((float(p[1]), float(p[2]), float(p[3])))
    return np.array(verts, dtype=np.float64)


def load_pix_positions():
    """Load all PIX world positions, keyed by (submesh_name, vertex_id)."""
    pix = {}
    for gpu_id, (sm_name, sm_idx) in PIX_MAP.items():
        csv_path = os.path.join(PIX_DIR,
            f"2026_3_30__9_24_50_GpuId{gpu_id}_VS_BufferData_exp0.csv")
        pix[sm_name] = {}
        with open(csv_path, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                vid = int(row['Vertex_ID'])
                if vid not in pix[sm_name]:
                    pix[sm_name][vid] = np.array([
                        float(row['TEXCOORD1_C0']),
                        float(row['TEXCOORD1_C1']),
                        float(row['TEXCOORD1_C2']),
                    ])
    return pix


def compute_bone_matrices(cd_data, pix, pac):
    """Compute per-bone forward and inverse matrices from paired (local, world) data."""
    palette_count = struct.unpack_from('<H', pac, 0x0441)[0]
    bone_palette = [struct.unpack_from('<I', pac, 0x0443 + i*4)[0] for i in range(palette_count)]

    # Collect single-bone vertex pairs
    bone_locals = {}
    bone_worlds = {}

    for sm_name in PIX_MAP.values():
        sm_name = sm_name[0]
        if sm_name not in pix:
            continue
        verts = cd_data[sm_name]['verts']
        for vid, world_pos in pix[sm_name].items():
            if vid >= len(verts):
                continue
            v = verts[vid]
            if v.bone_wt[0] >= 240:
                pidx = v.bone_idx[0]
                if pidx not in bone_locals:
                    bone_locals[pidx] = []
                    bone_worlds[pidx] = []
                bone_locals[pidx].append([*v.pos, 1.0])
                bone_worlds[pidx].append(world_pos)

    forward = {}
    inverse = {}

    for pidx in bone_locals:
        if len(bone_locals[pidx]) < 4:
            continue
        P = np.array(bone_locals[pidx])
        W = np.array(bone_worlds[pidx])
        M_T, _, _, _ = np.linalg.lstsq(P, W, rcond=None)
        M = M_T.T  # 3x4

        forward[pidx] = M
        R = M[:, :3]
        t = M[:, 3]
        try:
            R_inv = np.linalg.inv(R)
            M_inv = np.zeros((3, 4))
            M_inv[:, :3] = R_inv
            M_inv[:, 3] = -R_inv @ t
            inverse[pidx] = M_inv
        except np.linalg.LinAlgError:
            pass

    return forward, inverse, bone_palette


def world_to_local(world_pos, v, bone_fwd, bone_inv, bone_palette):
    """Convert world position to bone-local using empirical matrices."""
    # Build blended forward matrix
    M_blend = np.zeros((3, 4))
    total_w = 0

    for i in range(4):
        if v.bone_wt[i] > 0:
            pidx = v.bone_idx[i]
            w = v.bone_wt[i] / 255.0
            if pidx in bone_fwd:
                M_blend += w * bone_fwd[pidx]
                total_w += w

    if total_w < 0.01:
        return np.array(v.pos)

    M_blend /= total_w

    # Invert the blended matrix
    R = M_blend[:, :3]
    t = M_blend[:, 3]
    try:
        R_inv = np.linalg.inv(R)
        local = R_inv @ (world_pos - t)
        return local
    except np.linalg.LinAlgError:
        return np.array(v.pos)


def main():
    blend = float(sys.argv[sys.argv.index('--blend') + 1]) if '--blend' in sys.argv else 0.8

    print("=" * 60)
    print(f"DROGON MESH SWAP v4 (blend={blend})")
    print("PIX world-space + empirical bone matrices")
    print("=" * 60)

    # Load data
    print("\n[1] Loading data...")
    pac = bytearray(PAC_PATH.read_bytes())
    cd_data = decode_all_submeshes(bytes(pac))
    bboxes = parse_submesh_descriptors(bytes(pac))
    bbox_offsets = find_bbox_offsets(bytes(pac))

    pix = load_pix_positions()
    print(f"    PIX: {sum(len(v) for v in pix.values()):,} world positions")

    drogon_verts = load_drogon_verts(DROGON_OBJ)
    print(f"    Drogon: {len(drogon_verts):,} vertices")

    bone_fwd, bone_inv, bone_palette = compute_bone_matrices(cd_data, pix, bytes(pac))
    print(f"    Bone matrices: {len(bone_fwd)} forward, {len(bone_inv)} inverse")

    # Compute CD world bounds from PIX
    all_world = []
    for sm_name, positions in pix.items():
        all_world.extend(positions.values())
    all_world = np.array(all_world)
    cd_world_min = all_world.min(axis=0)
    cd_world_max = all_world.max(axis=0)
    cd_world_center = (cd_world_min + cd_world_max) / 2
    cd_world_span = cd_world_max - cd_world_min

    print(f"    CD world: center=({cd_world_center[0]:.1f},{cd_world_center[1]:.1f},{cd_world_center[2]:.1f}), "
          f"span=({cd_world_span[0]:.1f},{cd_world_span[1]:.1f},{cd_world_span[2]:.1f})")

    # Align Drogon to CD world space
    print("\n[2] Aligning Drogon to PIX world space...")
    d_min = drogon_verts.min(axis=0)
    d_max = drogon_verts.max(axis=0)
    d_center = (d_min + d_max) / 2
    d_span = d_max - d_min

    # Axis mapping: Drogon X=wingspan, Y=height, Z=length
    # CD PIX: X=lateral, Y=forward(neg), Z=up
    # Drogon X -> CD X, Drogon Z -> CD -Y, Drogon Y -> CD Z
    d_normalized = (drogon_verts - d_min) / d_span

    drogon_world = np.zeros_like(drogon_verts)
    drogon_world[:, 0] = cd_world_min[0] + d_normalized[:, 0] * cd_world_span[0]
    drogon_world[:, 1] = cd_world_max[1] - d_normalized[:, 2] * cd_world_span[1]  # Z->-Y
    drogon_world[:, 2] = cd_world_min[2] + d_normalized[:, 1] * cd_world_span[2]  # Y->Z

    print(f"    Drogon aligned: X=[{drogon_world[:,0].min():.1f},{drogon_world[:,0].max():.1f}], "
          f"Y=[{drogon_world[:,1].min():.1f},{drogon_world[:,1].max():.1f}], "
          f"Z=[{drogon_world[:,2].min():.1f},{drogon_world[:,2].max():.1f}]")

    # Build KD-tree
    print("\n[3] Projecting onto Drogon surface...")
    tree = KDTree(drogon_world)

    # For each submesh with PIX data, project and convert to local
    print("\n[4] Converting to bone-local space...")
    for sm_idx, sm_name in enumerate(SUBMESH_NAMES):
        base = SUBMESH_BASES[sm_idx]
        count = SUBMESH_VERTEX_COUNTS[sm_idx]
        bbox = bboxes[sm_idx]
        cd_verts = cd_data[sm_name]['verts']

        if sm_name not in pix:
            print(f"  {sm_name:12s}: no PIX data, keeping original")
            continue

        sm_pix = pix[sm_name]
        new_positions = []

        for vid in range(count):
            v = cd_verts[vid]

            if vid in sm_pix:
                old_world = sm_pix[vid]

                # Find nearest Drogon point in world space
                dist, idx = tree.query(old_world)
                drogon_point = drogon_world[idx]

                # Blend between CD and Drogon world position
                new_world = old_world + blend * (drogon_point - old_world)

                # Convert new_world to bone-local space
                new_local = world_to_local(new_world, v, bone_fwd, bone_inv, bone_palette)
                new_positions.append(new_local)
            else:
                new_positions.append(np.array(v.pos))

        new_positions = np.array(new_positions)

        # Compute new bbox
        new_min = new_positions.min(axis=0)
        new_max = new_positions.max(axis=0)
        new_dim = np.maximum(new_max - new_min, 1e-6)

        new_bbox = SubmeshBbox(
            name=sm_name,
            min_xyz=tuple(new_min),
            dim_xyz=tuple(new_dim),
            lod_near=bbox.lod_near,
            lod_far=bbox.lod_far,
        )

        print(f"  {sm_name:12s}: {count} verts, "
              f"dim ({bbox.dim_xyz[0]:.2f},{bbox.dim_xyz[1]:.2f},{bbox.dim_xyz[2]:.2f}) -> "
              f"({new_dim[0]:.2f},{new_dim[1]:.2f},{new_dim[2]:.2f})")

        # Write to PAC
        for j in range(count):
            off = VB_START + (base + j) * STRIDE
            x, y, z = new_positions[j]
            qx, qy, qz = quantize_pos(x, y, z, new_bbox)
            struct.pack_into('<3H', pac, off, qx, qy, qz)

        bbox_off = bbox_offsets[sm_idx]
        struct.pack_into('<2f', pac, bbox_off, bbox.lod_near, bbox.lod_far)
        struct.pack_into('<3f', pac, bbox_off + 8, *tuple(new_min))
        struct.pack_into('<3f', pac, bbox_off + 20, *tuple(new_dim))

    # Export OBJ for preview (model-space — will look fragmented but that's normal)
    output_path = str(OUTPUT / "dragon_drogon_v4.pac")
    with open(output_path, 'wb') as f:
        f.write(pac)
    print(f"\n[5] Wrote: {output_path}")

    # Also export a WORLD-SPACE preview OBJ using the bone forward matrices
    print("\n[6] Exporting world-space preview OBJ...")
    preview_path = str(OUTPUT / "dragon_drogon_v4_world.obj")
    with open(preview_path, 'w') as f:
        f.write("# Drogon swap v4 — world-space preview\n")
        f.write("# (re-projected through forward bone matrices)\n\n")

        indices_data = read_indices(bytes(pac))
        vert_offset = 0

        for sm_idx, sm_name in enumerate(SUBMESH_NAMES):
            cd_verts = cd_data[sm_name]['verts']
            count = SUBMESH_VERTEX_COUNTS[sm_idx]

            # Read new local positions from patched PAC
            new_bboxes = parse_submesh_descriptors(bytes(pac))
            nbbox = new_bboxes[sm_idx]

            for j in range(count):
                off = VB_START + (SUBMESH_BASES[sm_idx] + j) * STRIDE
                u16_x, u16_y, u16_z = struct.unpack_from('<3H', pac, off)
                lx = nbbox.min_xyz[0] + (u16_x / 32767.0) * nbbox.dim_xyz[0]
                ly = nbbox.min_xyz[1] + (u16_y / 32767.0) * nbbox.dim_xyz[1]
                lz = nbbox.min_xyz[2] + (u16_z / 32767.0) * nbbox.dim_xyz[2]

                v = cd_verts[j]
                # Forward transform to world space for preview
                local_h = np.array([lx, ly, lz, 1.0])
                M_blend = np.zeros((3, 4))
                total_w = 0
                for i in range(4):
                    if v.bone_wt[i] > 0:
                        pidx = v.bone_idx[i]
                        w = v.bone_wt[i] / 255.0
                        if pidx in bone_fwd:
                            M_blend += w * bone_fwd[pidx]
                            total_w += w
                if total_w > 0.01:
                    M_blend /= total_w
                    world = M_blend @ local_h
                    f.write(f"v {world[0]:.6f} {world[1]:.6f} {world[2]:.6f}\n")
                else:
                    f.write(f"v {lx:.6f} {ly:.6f} {lz:.6f}\n")

            f.write(f"\ng {sm_name}\n")
            sm_indices = indices_data[sm_name]
            for tri in range(len(sm_indices) // 3):
                i0 = sm_indices[tri*3+0] + vert_offset + 1
                i1 = sm_indices[tri*3+1] + vert_offset + 1
                i2 = sm_indices[tri*3+2] + vert_offset + 1
                f.write(f"f {i0} {i1} {i2}\n")
            vert_offset += count

    print(f"    Preview OBJ: {preview_path}")
    print("    (Open this in Blender to see the Drogon shape)")

    if '--deploy' in sys.argv:
        deploy_pac(output_path)
    else:
        print("\nAdd --deploy to patch game files.")


if __name__ == "__main__":
    main()
