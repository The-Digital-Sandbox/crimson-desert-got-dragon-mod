#!/usr/bin/env python3
"""
Drogon mesh swap v5 — delta-based morphing through bone rotations.

Key insight: for DELTAS, translation cancels out. We only need the
bone's rotation matrix inverse (R_inv), which is numerically stable.

delta_local = R_inv * delta_world
new_local = old_local + blend * delta_local
"""
import struct
import csv
import os
import sys
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

DROGON_OBJ = r"C:\Users\waelj\Desktop\Outputs\DROGON.OBJ"
PIX_DIR = r"C:\Users\waelj\Desktop\Outputs"
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


def compute_bone_rotations(cd_data, pix_data, pac):
    """Compute per-bone 3x3 rotation matrices from (local, world) pairs.

    From forward matrix M = [R | t], we extract R and compute R_inv.
    R_inv is used to convert world-space deltas to local-space deltas.
    """
    palette_count = struct.unpack_from('<H', pac, 0x0441)[0]

    # Collect single-bone vertex pairs
    bone_locals = {}
    bone_worlds = {}

    for gpu_id, (sm_name, sm_idx) in PIX_MAP.items():
        if sm_name not in pix_data:
            continue
        verts = cd_data[sm_name]['verts']
        for vid, world_pos in pix_data[sm_name].items():
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

    bone_R = {}      # palette_idx -> 3x3 rotation
    bone_R_inv = {}   # palette_idx -> 3x3 inverse rotation

    for pidx in bone_locals:
        if len(bone_locals[pidx]) < 4:
            continue
        P = np.array(bone_locals[pidx])  # N x 4
        W = np.array(bone_worlds[pidx])  # N x 3

        M_T, _, _, _ = np.linalg.lstsq(P, W, rcond=None)
        M = M_T.T  # 3x4
        R = M[:, :3]  # 3x3 rotation+scale

        try:
            R_inv = np.linalg.inv(R)
            bone_R[pidx] = R
            bone_R_inv[pidx] = R_inv
        except np.linalg.LinAlgError:
            pass

    return bone_R, bone_R_inv


def get_vertex_R_inv(v, bone_R_inv):
    """Get blended inverse rotation for a vertex based on its bone weights."""
    R_inv_blend = np.zeros((3, 3))
    total_w = 0

    for i in range(4):
        if v.bone_wt[i] > 0:
            pidx = v.bone_idx[i]
            w = v.bone_wt[i] / 255.0
            if pidx in bone_R_inv:
                R_inv_blend += w * bone_R_inv[pidx]
                total_w += w

    if total_w < 0.01:
        return None

    return R_inv_blend / total_w


def main():
    blend = float(sys.argv[sys.argv.index('--blend') + 1]) if '--blend' in sys.argv else 0.7

    print("=" * 60)
    print(f"DROGON MESH SWAP v5 (blend={blend})")
    print("Delta-based morphing through bone rotations")
    print("=" * 60)

    # Load
    print("\n[1] Loading data...")
    pac = bytearray(PAC_PATH.read_bytes())
    cd_data = decode_all_submeshes(bytes(pac))
    bboxes = parse_submesh_descriptors(bytes(pac))
    bbox_offsets = find_bbox_offsets(bytes(pac))
    indices = read_indices(bytes(pac))

    drogon_verts = load_drogon_verts(DROGON_OBJ)
    print(f"    Drogon: {len(drogon_verts):,} verts")

    # Load PIX world positions
    pix_data = {}
    for gpu_id, (sm_name, sm_idx) in PIX_MAP.items():
        csv_path = os.path.join(PIX_DIR,
            f"2026_3_30__9_24_50_GpuId{gpu_id}_VS_BufferData_exp0.csv")
        pix_data[sm_name] = {}
        with open(csv_path, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                vid = int(row['Vertex_ID'])
                if vid not in pix_data[sm_name]:
                    pix_data[sm_name][vid] = np.array([
                        float(row['TEXCOORD1_C0']),
                        float(row['TEXCOORD1_C1']),
                        float(row['TEXCOORD1_C2']),
                    ])
    total_pix = sum(len(v) for v in pix_data.values())
    print(f"    PIX: {total_pix:,} world positions")

    # Compute bone rotations
    bone_R, bone_R_inv = compute_bone_rotations(cd_data, pix_data, bytes(pac))
    print(f"    Bone rotations: {len(bone_R_inv)} computed")

    # CD world bounds
    all_world = np.vstack([np.array(list(v.values())) for v in pix_data.values()])
    cd_min = all_world.min(axis=0)
    cd_max = all_world.max(axis=0)

    # Align Drogon: X->X, Z->-Y, Y->Z
    d_min = drogon_verts.min(axis=0)
    d_max = drogon_verts.max(axis=0)
    d_span = d_max - d_min
    cd_span = cd_max - cd_min
    d_norm = (drogon_verts - d_min) / d_span

    drogon_world = np.zeros_like(drogon_verts)
    drogon_world[:, 0] = cd_min[0] + d_norm[:, 0] * cd_span[0]
    drogon_world[:, 1] = cd_max[1] - d_norm[:, 2] * cd_span[1]
    drogon_world[:, 2] = cd_min[2] + d_norm[:, 1] * cd_span[2]

    tree = KDTree(drogon_world)
    print(f"    KD-tree built ({len(drogon_world):,} points)")

    # Morph each submesh
    print(f"\n[2] Morphing (blend={blend})...")
    for sm_idx, sm_name in enumerate(SUBMESH_NAMES):
        base = SUBMESH_BASES[sm_idx]
        count = SUBMESH_VERTEX_COUNTS[sm_idx]
        bbox = bboxes[sm_idx]
        cd_verts = cd_data[sm_name]['verts']

        if sm_name not in pix_data:
            print(f"  {sm_name:12s}: no PIX data, skip")
            continue

        sm_pix = pix_data[sm_name]
        new_positions = []
        deltas_applied = 0

        for vid in range(count):
            v = cd_verts[vid]
            old_local = np.array(v.pos)

            if vid in sm_pix:
                old_world = sm_pix[vid]

                # Find nearest Drogon point
                dist, idx = tree.query(old_world)
                drogon_point = drogon_world[idx]

                # World-space delta
                delta_world = drogon_point - old_world

                # Convert delta to local space via bone rotation inverse
                R_inv = get_vertex_R_inv(v, bone_R_inv)
                if R_inv is not None:
                    delta_local = R_inv @ delta_world
                    new_local = old_local + blend * delta_local
                    deltas_applied += 1
                else:
                    new_local = old_local
            else:
                new_local = old_local

            new_positions.append(new_local)

        new_positions = np.array(new_positions)

        # Laplacian smoothing (2 passes)
        sm_idx_list = indices[sm_name]
        adj = [set() for _ in range(count)]
        for tri in range(len(sm_idx_list) // 3):
            i0 = sm_idx_list[tri * 3]
            i1 = sm_idx_list[tri * 3 + 1]
            i2 = sm_idx_list[tri * 3 + 2]
            if max(i0, i1, i2) < count:
                adj[i0].update([i1, i2])
                adj[i1].update([i0, i2])
                adj[i2].update([i0, i1])

        for _ in range(2):
            smoothed = np.copy(new_positions)
            for i in range(count):
                if adj[i]:
                    nbrs = np.array(list(adj[i]))
                    avg = new_positions[nbrs].mean(axis=0)
                    smoothed[i] = new_positions[i] * 0.7 + avg * 0.3
            new_positions = smoothed

        # New bbox
        new_min = new_positions.min(axis=0)
        new_max = new_positions.max(axis=0)
        new_dim = np.maximum(new_max - new_min, 1e-6)

        new_bbox = SubmeshBbox(
            name=sm_name, min_xyz=tuple(new_min), dim_xyz=tuple(new_dim),
            lod_near=bbox.lod_near, lod_far=bbox.lod_far,
        )

        print(f"  {sm_name:12s}: {deltas_applied}/{count} morphed, "
              f"dim ({bbox.dim_xyz[0]:.2f},{bbox.dim_xyz[1]:.2f},{bbox.dim_xyz[2]:.2f}) -> "
              f"({new_dim[0]:.2f},{new_dim[1]:.2f},{new_dim[2]:.2f})")

        # Write
        for j in range(count):
            off = VB_START + (base + j) * STRIDE
            x, y, z = new_positions[j]
            qx, qy, qz = quantize_pos(x, y, z, new_bbox)
            struct.pack_into('<3H', pac, off, qx, qy, qz)

        bbox_off = bbox_offsets[sm_idx]
        struct.pack_into('<2f', pac, bbox_off, bbox.lod_near, bbox.lod_far)
        struct.pack_into('<3f', pac, bbox_off + 8, *tuple(new_min))
        struct.pack_into('<3f', pac, bbox_off + 20, *tuple(new_dim))

    # Export world-space preview using forward bone transforms
    print("\n[3] Exporting world-space preview OBJ...")
    preview_path = str(OUTPUT / "dragon_drogon_v5_preview.obj")
    with open(preview_path, 'w') as f:
        f.write("# Drogon v5 world-space preview\n\n")
        new_bboxes = parse_submesh_descriptors(bytes(pac))
        vert_offset = 0

        for sm_idx, sm_name in enumerate(SUBMESH_NAMES):
            count = SUBMESH_VERTEX_COUNTS[sm_idx]
            cd_verts = cd_data[sm_name]['verts']
            nbbox = new_bboxes[sm_idx]

            for j in range(count):
                off = VB_START + (SUBMESH_BASES[sm_idx] + j) * STRIDE
                u16_x, u16_y, u16_z = struct.unpack_from('<3H', pac, off)
                lx = nbbox.min_xyz[0] + (u16_x / 32767.0) * nbbox.dim_xyz[0]
                ly = nbbox.min_xyz[1] + (u16_y / 32767.0) * nbbox.dim_xyz[1]
                lz = nbbox.min_xyz[2] + (u16_z / 32767.0) * nbbox.dim_xyz[2]

                v = cd_verts[j]
                M_blend = np.zeros((3, 4))
                total_w = 0
                for i in range(4):
                    if v.bone_wt[i] > 0 and v.bone_idx[i] in bone_R:
                        pidx = v.bone_idx[i]
                        w = v.bone_wt[i] / 255.0
                        # Need full forward matrix, not just R
                        # Reconstruct: use original bone forward matrices
                        pass

                # Simpler: just use PIX position + delta for preview
                if sm_name in pix_data and j in pix_data[sm_name]:
                    old_world = pix_data[sm_name][j]
                    delta_local = np.array([lx, ly, lz]) - np.array(cd_verts[j].pos)
                    R_inv = get_vertex_R_inv(v, bone_R_inv)
                    if R_inv is not None:
                        # delta_world = R * delta_local (forward)
                        R = np.linalg.inv(R_inv)
                        delta_world = R @ delta_local
                        world = old_world + delta_world
                    else:
                        world = old_world
                    f.write(f"v {world[0]:.6f} {world[1]:.6f} {world[2]:.6f}\n")
                else:
                    f.write(f"v {lx:.6f} {ly:.6f} {lz:.6f}\n")

            f.write(f"\ng {sm_name}\n")
            sm_indices = indices[sm_name]
            for tri in range(len(sm_indices) // 3):
                i0 = sm_indices[tri*3] + vert_offset + 1
                i1 = sm_indices[tri*3+1] + vert_offset + 1
                i2 = sm_indices[tri*3+2] + vert_offset + 1
                f.write(f"f {i0} {i1} {i2}\n")
            vert_offset += count

    print(f"    {preview_path}")

    output_path = str(OUTPUT / "dragon_drogon_v5.pac")
    with open(output_path, 'wb') as f:
        f.write(pac)
    print(f"\n[4] Wrote: {output_path}")

    if '--deploy' in sys.argv:
        deploy_pac(output_path)
    else:
        print("Add --deploy to patch game files.")


if __name__ == "__main__":
    main()
