#!/usr/bin/env python3
"""
Drogon mesh swap v7 — per-vertex local Jacobian from neighbor edges.

For each vertex, fit a 3x3 transform T from nearby vertex edges:
  (local_j - local_i) = T * (world_j - world_i)
Then: delta_local = T * delta_world

No bone matrix inversion needed. T is computed from actual paired data.
"""
import struct, csv, os, sys
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
    '7153': ('Body_02', 2), '7154': ('back', 3), '7155': ('Body', 4),
    '7156': ('Leg', 5), '7157': ('Wing', 6), '7158': ('Head', 7),
}

K_NEIGHBORS = 12  # neighbors for local Jacobian fit


def main():
    blend = float(sys.argv[sys.argv.index('--blend') + 1]) if '--blend' in sys.argv else 0.7

    print(f"DROGON SWAP v7 (blend={blend}) — per-vertex Jacobian from edges")

    pac = bytearray(PAC_PATH.read_bytes())
    cd_data = decode_all_submeshes(bytes(pac))
    bboxes = parse_submesh_descriptors(bytes(pac))
    bbox_offsets = find_bbox_offsets(bytes(pac))
    indices = read_indices(bytes(pac))

    # Load Drogon
    drogon = []
    with open(DROGON_OBJ, 'r') as f:
        for line in f:
            if line.startswith('v '):
                p = line.split()
                drogon.append((float(p[1]), float(p[2]), float(p[3])))
    drogon = np.array(drogon)

    # Load PIX
    pix_data = {}
    for gpu_id, (sm_name, _) in PIX_MAP.items():
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
    drogon_w[:, 1] = cd_max[1] - d_norm[:, 2] * cd_span[1]  # Z->-Y
    drogon_w[:, 2] = cd_min[2] + d_norm[:, 1] * cd_span[2]  # Y->Z
    drogon_tree = KDTree(drogon_w)

    # Process each submesh
    print(f"\n  Morphing...")
    for sm_idx, sm_name in enumerate(SUBMESH_NAMES):
        base = SUBMESH_BASES[sm_idx]
        count = SUBMESH_VERTEX_COUNTS[sm_idx]
        bbox = bboxes[sm_idx]
        cd_verts = cd_data[sm_name]['verts']

        if sm_name not in pix_data:
            print(f"    {sm_name:12s}: skip (no PIX)")
            continue

        sm_pix = pix_data[sm_name]

        # Build arrays of vertices that have PIX data
        pix_vids = sorted(vid for vid in sm_pix if vid < count)
        pix_locals = np.array([cd_verts[vid].pos for vid in pix_vids])
        pix_worlds = np.array([sm_pix[vid] for vid in pix_vids])
        vid_to_idx = {vid: i for i, vid in enumerate(pix_vids)}

        # Build KD-tree of world positions for neighbor lookup
        world_tree = KDTree(pix_worlds)

        new_positions = []
        morphed = 0

        for vid in range(count):
            v = cd_verts[vid]
            old_local = np.array(v.pos)

            if vid not in sm_pix:
                new_positions.append(old_local)
                continue

            old_world = sm_pix[vid]
            pidx = vid_to_idx[vid]

            # Find K nearest neighbors in world space (within this submesh)
            k = min(K_NEIGHBORS + 1, len(pix_vids))
            dists, nbr_idxs = world_tree.query(old_world, k=k)

            # Build edge vectors (excluding self)
            world_edges = []
            local_edges = []
            for ni in nbr_idxs:
                if ni == pidx:
                    continue
                de_world = pix_worlds[ni] - old_world
                de_local = pix_locals[ni] - old_local
                if np.linalg.norm(de_world) > 1e-6:
                    world_edges.append(de_world)
                    local_edges.append(de_local)

            if len(world_edges) >= 3:
                # Fit T: local_edge = T * world_edge
                # Stack: L = T * W  ->  L^T = W^T * T^T  ->  solve for T^T
                W = np.array(world_edges)  # N x 3
                L = np.array(local_edges)  # N x 3
                T_T, _, _, _ = np.linalg.lstsq(W, L, rcond=None)
                T = T_T.T  # 3x3

                # Find nearest Drogon point
                _, didx = drogon_tree.query(old_world)
                delta_world = drogon_w[didx] - old_world

                # Transform delta to local space
                delta_local = T @ delta_world

                # Clamp delta to prevent explosion (max 2x bbox dim per axis)
                max_delta = np.array(bbox.dim_xyz) * 2.0
                delta_local = np.clip(delta_local, -max_delta, max_delta)

                new_local = old_local + blend * delta_local
                morphed += 1
            else:
                new_local = old_local

            new_positions.append(new_local)

        new_positions = np.array(new_positions)

        # Laplacian smoothing (3 passes)
        adj = [set() for _ in range(count)]
        sm_idx_list = indices[sm_name]
        for tri in range(len(sm_idx_list) // 3):
            i0, i1, i2 = sm_idx_list[tri*3], sm_idx_list[tri*3+1], sm_idx_list[tri*3+2]
            if max(i0, i1, i2) < count:
                adj[i0].update([i1, i2]); adj[i1].update([i0, i2]); adj[i2].update([i0, i1])
        for _ in range(3):
            smoothed = np.copy(new_positions)
            for i in range(count):
                if adj[i]:
                    nbrs = list(adj[i])
                    avg = new_positions[nbrs].mean(0)
                    smoothed[i] = new_positions[i] * 0.6 + avg * 0.4
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

        print(f"    {sm_name:12s}: {morphed}/{count} morphed, "
              f"dim ({bbox.dim_xyz[0]:.2f},{bbox.dim_xyz[1]:.2f},{bbox.dim_xyz[2]:.2f}) -> "
              f"({new_dim[0]:.2f},{new_dim[1]:.2f},{new_dim[2]:.2f})")

    # World-space preview
    print(f"\n  Exporting preview...")
    preview = str(OUTPUT / "dragon_drogon_v7_preview.obj")
    new_bboxes = parse_submesh_descriptors(bytes(pac))
    with open(preview, 'w') as f:
        f.write("# Drogon v7 preview\n\n")
        vert_offset = 0
        for sm_idx, sm_name in enumerate(SUBMESH_NAMES):
            count = SUBMESH_VERTEX_COUNTS[sm_idx]
            cd_verts = cd_data[sm_name]['verts']
            nbbox = new_bboxes[sm_idx]
            sm_pix = pix_data.get(sm_name, {})

            # Build per-vertex Jacobians for forward preview (local→world)
            pix_vids = sorted(vid for vid in sm_pix if vid < count)
            if pix_vids:
                pix_locals_orig = np.array([cd_verts[vid].pos for vid in pix_vids])
                pix_worlds_orig = np.array([sm_pix[vid] for vid in pix_vids])
                world_tree_sm = KDTree(pix_worlds_orig)
                vid_to_idx_sm = {vid: i for i, vid in enumerate(pix_vids)}

            for j in range(count):
                off = VB_START + (SUBMESH_BASES[sm_idx] + j) * STRIDE
                u16_x, u16_y, u16_z = struct.unpack_from('<3H', pac, off)
                lx = nbbox.min_xyz[0] + (u16_x / 32767.0) * nbbox.dim_xyz[0]
                ly = nbbox.min_xyz[1] + (u16_y / 32767.0) * nbbox.dim_xyz[1]
                lz = nbbox.min_xyz[2] + (u16_z / 32767.0) * nbbox.dim_xyz[2]

                v = cd_verts[j]
                new_local = np.array([lx, ly, lz])
                old_local = np.array(v.pos)
                delta_local = new_local - old_local

                if j in sm_pix and pix_vids:
                    old_world = sm_pix[j]
                    pidx_sm = vid_to_idx_sm.get(j, -1)

                    if pidx_sm >= 0:
                        # Fit forward Jacobian J: world_edge = J * local_edge
                        k = min(K_NEIGHBORS + 1, len(pix_vids))
                        _, nbr_idxs = world_tree_sm.query(old_world, k=k)
                        we, le = [], []
                        for ni in nbr_idxs:
                            if ni == pidx_sm: continue
                            dw = pix_worlds_orig[ni] - old_world
                            dl = pix_locals_orig[ni] - old_local
                            if np.linalg.norm(dl) > 1e-6:
                                we.append(dw); le.append(dl)

                        if len(le) >= 3:
                            L = np.array(le); W = np.array(we)
                            J_T, _, _, _ = np.linalg.lstsq(L, W, rcond=None)
                            delta_world = J_T.T @ delta_local
                            world = old_world + delta_world
                        else:
                            world = old_world
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

    print(f"    {preview}")
    output_path = str(OUTPUT / "dragon_drogon_v7.pac")
    with open(output_path, 'wb') as f:
        f.write(pac)
    print(f"\n  Wrote: {output_path}")
    if '--deploy' in sys.argv:
        deploy_pac(output_path)
    else:
        print("  Add --deploy to patch game files.")


if __name__ == "__main__":
    main()
