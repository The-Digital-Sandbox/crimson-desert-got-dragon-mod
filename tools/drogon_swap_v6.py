#!/usr/bin/env python3
"""
Drogon mesh swap v6 — simple delta scaling, no matrix inversion.

For each vertex:
  1. Find nearest Drogon point in world space
  2. Compute world delta = drogon - cd_world
  3. Scale delta by per-bone ratio (local_extent / world_extent)
  4. new_local = old_local + blend * scaled_delta

No matrix inversion. Just empirical per-bone scale ratios from data.
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


def main():
    blend = float(sys.argv[sys.argv.index('--blend') + 1]) if '--blend' in sys.argv else 0.7

    print(f"DROGON SWAP v6 (blend={blend}) — per-bone scale ratios")

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

    # Compute per-bone scale ratios from paired data
    # For each bone: ratio = RMS(local_distances) / RMS(world_distances) among its vertices
    bone_verts = {}  # pidx -> [(local, world), ...]
    for sm_name in pix_data:
        verts = cd_data[sm_name]['verts']
        for vid, world in pix_data[sm_name].items():
            if vid < len(verts):
                v = verts[vid]
                pidx = v.bone_idx[0]  # primary bone
                if pidx not in bone_verts:
                    bone_verts[pidx] = []
                bone_verts[pidx].append((np.array(v.pos), world))

    bone_scale = {}  # pidx -> scalar scale ratio
    for pidx, pairs in bone_verts.items():
        if len(pairs) < 3:
            bone_scale[pidx] = 0.1  # conservative default
            continue

        locals_arr = np.array([p[0] for p in pairs])
        worlds_arr = np.array([p[1] for p in pairs])

        # Compute spans (max - min per axis)
        local_span = locals_arr.max(axis=0) - locals_arr.min(axis=0)
        world_span = worlds_arr.max(axis=0) - worlds_arr.min(axis=0)

        # Per-axis ratios, clamped
        ratios = []
        for ax in range(3):
            if world_span[ax] > 0.01:
                r = local_span[ax] / world_span[ax]
                ratios.append(min(r, 2.0))  # cap at 2x

        bone_scale[pidx] = np.mean(ratios) if ratios else 0.1

    print(f"  Bone scale ratios: {len(bone_scale)} bones, "
          f"range [{min(bone_scale.values()):.3f}, {max(bone_scale.values()):.3f}], "
          f"median={np.median(list(bone_scale.values())):.3f}")

    # Align Drogon to CD world space
    all_world = np.vstack([np.array(list(v.values())) for v in pix_data.values()])
    cd_min, cd_max = all_world.min(0), all_world.max(0)
    cd_span = cd_max - cd_min

    d_min, d_max = drogon.min(0), drogon.max(0)
    d_span = d_max - d_min
    d_norm = (drogon - d_min) / d_span

    drogon_w = np.zeros_like(drogon)
    drogon_w[:, 0] = cd_min[0] + d_norm[:, 0] * cd_span[0]
    drogon_w[:, 1] = cd_max[1] - d_norm[:, 2] * cd_span[1]  # Z->-Y
    drogon_w[:, 2] = cd_min[2] + d_norm[:, 1] * cd_span[2]  # Y->Z

    tree = KDTree(drogon_w)

    # Morph each submesh
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
        new_positions = []

        for vid in range(count):
            v = cd_verts[vid]
            old_local = np.array(v.pos)

            if vid in sm_pix:
                old_world = sm_pix[vid]
                _, idx = tree.query(old_world)
                delta_world = drogon_w[idx] - old_world

                # Get scale ratio for this vertex's primary bone
                pidx = v.bone_idx[0]
                scale = bone_scale.get(pidx, 0.1)

                # Scale world delta to local delta
                delta_local = delta_world * scale
                new_local = old_local + blend * delta_local
                new_positions.append(new_local)
            else:
                new_positions.append(old_local)

        new_positions = np.array(new_positions)

        # Laplacian smoothing
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
                    smoothed[i] = new_positions[i] * 0.65 + avg * 0.35
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

        print(f"    {sm_name:12s}: dim ({bbox.dim_xyz[0]:.2f},{bbox.dim_xyz[1]:.2f},{bbox.dim_xyz[2]:.2f}) -> "
              f"({new_dim[0]:.2f},{new_dim[1]:.2f},{new_dim[2]:.2f})")

    # World-space preview OBJ (reconstruct world pos from local delta + old world)
    print(f"\n  Exporting preview...")
    preview_path = str(OUTPUT / "dragon_drogon_v6_preview.obj")
    new_bboxes = parse_submesh_descriptors(bytes(pac))
    with open(preview_path, 'w') as f:
        f.write("# Drogon v6 world-space preview\n\n")
        vert_offset = 0
        for sm_idx, sm_name in enumerate(SUBMESH_NAMES):
            count = SUBMESH_VERTEX_COUNTS[sm_idx]
            cd_verts = cd_data[sm_name]['verts']
            nbbox = new_bboxes[sm_idx]
            sm_pix = pix_data.get(sm_name, {})

            for j in range(count):
                off = VB_START + (SUBMESH_BASES[sm_idx] + j) * STRIDE
                u16_x, u16_y, u16_z = struct.unpack_from('<3H', pac, off)
                lx = nbbox.min_xyz[0] + (u16_x / 32767.0) * nbbox.dim_xyz[0]
                ly = nbbox.min_xyz[1] + (u16_y / 32767.0) * nbbox.dim_xyz[1]
                lz = nbbox.min_xyz[2] + (u16_z / 32767.0) * nbbox.dim_xyz[2]

                v = cd_verts[j]
                old_local = np.array(v.pos)
                delta_local = np.array([lx, ly, lz]) - old_local

                if j in sm_pix:
                    pidx = v.bone_idx[0]
                    scale = bone_scale.get(pidx, 0.1)
                    if scale > 0.001:
                        delta_world = delta_local / scale
                    else:
                        delta_world = np.zeros(3)
                    world = sm_pix[j] + delta_world
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

    output_path = str(OUTPUT / "dragon_drogon_v6.pac")
    with open(output_path, 'wb') as f:
        f.write(pac)
    print(f"\n  Wrote: {output_path}")

    if '--deploy' in sys.argv:
        deploy_pac(output_path)
    else:
        print("  Add --deploy to patch game files.")


if __name__ == "__main__":
    main()
