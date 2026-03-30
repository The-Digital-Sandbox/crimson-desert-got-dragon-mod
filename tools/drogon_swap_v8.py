#!/usr/bin/env python3
"""
Drogon mesh swap v8 — exact entity transform + empirical bone matrices.

Pipeline: world → skinned (via exact entity_inv) → local (via per-bone inv)
"""
import struct, csv, os, sys, pickle
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
    '7153': 'Body_02', '7154': 'back', '7155': 'Body',
    '7156': 'Leg', '7157': 'Wing', '7158': 'Head',
}


def main():
    blend = float(sys.argv[sys.argv.index('--blend') + 1]) if '--blend' in sys.argv else 0.6

    print(f"DROGON SWAP v8 (blend={blend}) — exact entity + bone matrices")

    pac = bytearray(PAC_PATH.read_bytes())
    cd_data = decode_all_submeshes(bytes(pac))
    bboxes = parse_submesh_descriptors(bytes(pac))
    bbox_offsets = find_bbox_offsets(bytes(pac))
    indices = read_indices(bytes(pac))

    # Load bone matrices
    with open(str(OUTPUT / 'bone_matrices_exact.pkl'), 'rb') as f:
        bm = pickle.load(f)
    M_entity_inv = bm['entity_inv']
    bone_fwd = bm['forward']
    bone_inv = bm['inverse']
    print(f"  {len(bone_fwd)} bone matrices, entity transform loaded")

    # Load Drogon
    drogon = []
    with open(DROGON_OBJ, 'r') as f:
        for line in f:
            if line.startswith('v '):
                p = line.split()
                drogon.append((float(p[1]), float(p[2]), float(p[3])))
    drogon = np.array(drogon)

    # Load PIX world positions
    pix_data = {}
    for gpu_id, sm_name in PIX_MAP.items():
        pix_data[sm_name] = {}
        csv_path = os.path.join(PIX_DIR, f"2026_3_30__9_24_50_GpuId{gpu_id}_VS_BufferData_exp0.csv")
        with open(csv_path, 'r') as f:
            for row in csv.DictReader(f):
                vid = int(row['Vertex_ID'])
                if vid not in pix_data[sm_name]:
                    pix_data[sm_name][vid] = np.array([
                        float(row['TEXCOORD1_C0']), float(row['TEXCOORD1_C1']),
                        float(row['TEXCOORD1_C2'])])

    # Align Drogon to CD world space
    all_world = np.vstack([np.array(list(v.values())) for v in pix_data.values()])
    cd_min, cd_max = all_world.min(0), all_world.max(0)
    cd_span = cd_max - cd_min
    d_min, d_max = drogon.min(0), drogon.max(0)
    d_norm = (drogon - d_min) / (d_max - d_min)

    drogon_w = np.zeros_like(drogon)
    drogon_w[:, 0] = cd_min[0] + d_norm[:, 0] * cd_span[0]
    drogon_w[:, 1] = cd_max[1] - d_norm[:, 2] * cd_span[1]
    drogon_w[:, 2] = cd_min[2] + d_norm[:, 1] * cd_span[2]
    drogon_tree = KDTree(drogon_w)

    print(f"  Drogon aligned, KD-tree built")

    # Process each submesh
    for sm_idx, sm_name in enumerate(SUBMESH_NAMES):
        base = SUBMESH_BASES[sm_idx]
        count = SUBMESH_VERTEX_COUNTS[sm_idx]
        bbox = bboxes[sm_idx]
        cd_verts = cd_data[sm_name]['verts']

        if sm_name not in pix_data:
            print(f"  {sm_name:12s}: skip (no PIX)")
            continue

        sm_pix = pix_data[sm_name]
        new_positions = []
        morphed = 0

        for vid in range(count):
            v = cd_verts[vid]
            old_local = np.array(v.pos)

            if vid not in sm_pix:
                new_positions.append(old_local)
                continue

            old_world = sm_pix[vid]
            _, didx = drogon_tree.query(old_world)
            drogon_point = drogon_w[didx]

            # Blend world position
            new_world = old_world + blend * (drogon_point - old_world)

            # World → skinned (exact entity transform)
            new_skinned = M_entity_inv @ new_world
            old_skinned = M_entity_inv @ old_world

            # Skinned → local (per-bone inverse)
            # Compute blended bone forward matrix, then invert
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
                R = M_blend[:, :3]
                t = M_blend[:, 3]
                try:
                    R_inv = np.linalg.inv(R)
                    new_local = R_inv @ (new_skinned - t)
                    # Sanity: clamp delta to prevent explosion
                    delta = new_local - old_local
                    max_d = np.array(bbox.dim_xyz) * 1.5
                    delta = np.clip(delta, -max_d, max_d)
                    new_local = old_local + delta
                    morphed += 1
                except np.linalg.LinAlgError:
                    new_local = old_local
            else:
                new_local = old_local

            new_positions.append(new_local)

        new_positions = np.array(new_positions)

        # Laplacian smoothing
        adj = [set() for _ in range(count)]
        sm_idx_list = indices[sm_name]
        for tri in range(len(sm_idx_list) // 3):
            i0, i1, i2 = sm_idx_list[tri*3], sm_idx_list[tri*3+1], sm_idx_list[tri*3+2]
            if max(i0, i1, i2) < count:
                adj[i0].update([i1, i2]); adj[i1].update([i0, i2]); adj[i2].update([i0, i1])
        for _ in range(2):
            smoothed = np.copy(new_positions)
            for i in range(count):
                if adj[i]:
                    nbrs = list(adj[i])
                    avg = new_positions[nbrs].mean(0)
                    smoothed[i] = new_positions[i] * 0.7 + avg * 0.3
            new_positions = smoothed

        # Bbox + write
        new_min = new_positions.min(0)
        new_dim = np.maximum(new_positions.max(0) - new_min, 1e-6)
        new_bbox = SubmeshBbox(sm_name, tuple(new_min), tuple(new_dim), bbox.lod_near, bbox.lod_far)

        for j in range(count):
            off = VB_START + (base + j) * STRIDE
            qx, qy, qz = quantize_pos(*new_positions[j], new_bbox)
            struct.pack_into('<3H', pac, off, qx, qy, qz)

        bbox_off = bbox_offsets[sm_idx]
        struct.pack_into('<2f', pac, bbox_off, bbox.lod_near, bbox.lod_far)
        struct.pack_into('<3f', pac, bbox_off + 8, *tuple(new_min))
        struct.pack_into('<3f', pac, bbox_off + 20, *tuple(new_dim))

        print(f"  {sm_name:12s}: {morphed}/{count} morphed, "
              f"dim ({bbox.dim_xyz[0]:.2f},{bbox.dim_xyz[1]:.2f},{bbox.dim_xyz[2]:.2f}) -> "
              f"({new_dim[0]:.2f},{new_dim[1]:.2f},{new_dim[2]:.2f})")

    output_path = str(OUTPUT / "dragon_drogon_v8.pac")
    with open(output_path, 'wb') as f:
        f.write(pac)
    print(f"\n  Wrote: {output_path}")

    if '--deploy' in sys.argv:
        deploy_pac(output_path)
    else:
        print("  Add --deploy to patch game files.")


if __name__ == "__main__":
    main()
