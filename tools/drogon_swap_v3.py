#!/usr/bin/env python3
"""
Drogon mesh swap v3 — per-submesh model-space morphing.

No world-space transforms. For each CD submesh, map to the corresponding
Drogon body part group, align in model-space, and project vertices.
The game's bone transforms handle the rest.
"""
import struct
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

DROGON_OBJ = r"C:\Users\user\Desktop\Outputs\DROGON.OBJ"

# Map CD submeshes to Drogon OBJ groups
# CD submesh -> list of Drogon groups to use as projection target
SUBMESH_TO_DROGON = {
    'Eyeright':  ['eyes', 'head_horns'],
    'Eyeleft':   ['eyes', 'head_horns'],
    'Body_02':   ['spikes1', 'head_horns'],           # horns/spikes
    'back':      ['fins_neck', 'scales_chest1'],       # neck
    'Body':      ['fins_tail', 'body', 'body.001'],    # tail/body
    'Leg':       ['body', 'body.001', 'claws'],        # legs
    'Wing':      ['body', 'body.001', 'fins_neck', 'fins_tail'],  # wings
    'Head':      ['head_horns', 'teeth', 'tongue'],    # head
}


def load_drogon_groups(path):
    """Load Drogon OBJ into per-group vertex arrays."""
    groups = {}
    current_group = 'default'
    all_verts = []

    with open(path, 'r') as f:
        for line in f:
            if line.startswith('v '):
                parts = line.split()
                all_verts.append((float(parts[1]), float(parts[2]), float(parts[3])))
            elif line.startswith('g ') or line.startswith('o '):
                name = line.split(None, 1)[1].strip() if len(line.split()) > 1 else 'unnamed'
                current_group = name
            elif line.startswith('f '):
                if current_group not in groups:
                    groups[current_group] = set()
                parts = line.split()[1:]
                for p in parts:
                    idx = int(p.split('/')[0]) - 1  # OBJ is 1-indexed
                    groups[current_group].add(idx)

    all_verts = np.array(all_verts, dtype=np.float64)

    result = {}
    for name, indices in groups.items():
        idx_list = sorted(indices)
        result[name] = all_verts[idx_list]

    return result, all_verts


def align_drogon_to_submesh(drogon_verts, cd_verts_np):
    """Scale and translate Drogon group to match CD submesh bounds in model space."""
    cd_min = cd_verts_np.min(axis=0)
    cd_max = cd_verts_np.max(axis=0)
    cd_center = (cd_min + cd_max) / 2
    cd_span = cd_max - cd_min

    d_min = drogon_verts.min(axis=0)
    d_max = drogon_verts.max(axis=0)
    d_center = (d_min + d_max) / 2
    d_span = d_max - d_min

    # Prevent division by zero
    d_span[d_span < 1e-8] = 1.0
    cd_span[cd_span < 1e-6] = cd_span.max() * 0.01

    # Per-axis scaling: stretch Drogon to fill CD's bounding box
    scale = cd_span / d_span

    # Transform: center on CD, scale per-axis
    aligned = (drogon_verts - d_center) * scale + cd_center

    return aligned


def main():
    blend = float(sys.argv[sys.argv.index('--blend') + 1]) if '--blend' in sys.argv else 0.7

    print("=" * 60)
    print(f"DROGON MESH SWAP v3 (blend={blend})")
    print("Per-submesh model-space morphing")
    print("=" * 60)

    # Load PAC
    print("\n[1] Loading data...")
    pac = bytearray(PAC_PATH.read_bytes())
    cd_data = decode_all_submeshes(bytes(pac))
    bboxes = parse_submesh_descriptors(bytes(pac))
    bbox_offsets = find_bbox_offsets(bytes(pac))
    indices = read_indices(bytes(pac))

    # Load Drogon
    drogon_groups, drogon_all = load_drogon_groups(DROGON_OBJ)
    print(f"    Drogon: {len(drogon_all):,} total verts, {len(drogon_groups)} groups")
    for name, verts in sorted(drogon_groups.items()):
        print(f"      {name}: {len(verts):,} verts")

    # Process each submesh
    print(f"\n[2] Morphing submeshes (blend={blend})...")
    for sm_idx, sm_name in enumerate(SUBMESH_NAMES):
        base = SUBMESH_BASES[sm_idx]
        count = SUBMESH_VERTEX_COUNTS[sm_idx]
        bbox = bboxes[sm_idx]

        cd_verts = cd_data[sm_name]['verts']
        cd_positions = np.array([v.pos for v in cd_verts], dtype=np.float64)

        # Get Drogon target groups
        target_groups = SUBMESH_TO_DROGON.get(sm_name, [])
        drogon_target = []
        for gname in target_groups:
            if gname in drogon_groups:
                drogon_target.append(drogon_groups[gname])

        if not drogon_target:
            print(f"  {sm_name:12s}: no Drogon groups found, keeping original")
            continue

        # Combine target groups
        drogon_combined = np.vstack(drogon_target)

        # Align Drogon to CD submesh model space
        drogon_aligned = align_drogon_to_submesh(drogon_combined, cd_positions)

        # Build KD-tree and project
        tree = KDTree(drogon_aligned)
        dists, idxs = tree.query(cd_positions)

        # Blend: new = old + blend * (drogon - old)
        new_positions = cd_positions + blend * (drogon_aligned[idxs] - cd_positions)

        # Laplacian smoothing (2 passes)
        sm_indices_list = indices[sm_name]
        adj = [set() for _ in range(count)]
        for tri in range(len(sm_indices_list) // 3):
            i0 = sm_indices_list[tri * 3 + 0]
            i1 = sm_indices_list[tri * 3 + 1]
            i2 = sm_indices_list[tri * 3 + 2]
            if i0 < count and i1 < count and i2 < count:
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

        # Compute new bbox
        new_min = new_positions.min(axis=0)
        new_max = new_positions.max(axis=0)
        eps = 1e-6
        new_dim = np.maximum(new_max - new_min, eps)

        new_bbox = SubmeshBbox(
            name=sm_name,
            min_xyz=tuple(new_min),
            dim_xyz=tuple(new_dim),
            lod_near=bbox.lod_near,
            lod_far=bbox.lod_far,
        )

        avg_dist = np.mean(dists)
        print(f"  {sm_name:12s}: {count:5d} verts, avg_dist={avg_dist:.4f}, "
              f"dim ({bbox.dim_xyz[0]:.2f},{bbox.dim_xyz[1]:.2f},{bbox.dim_xyz[2]:.2f}) -> "
              f"({new_dim[0]:.2f},{new_dim[1]:.2f},{new_dim[2]:.2f})")

        # Write positions
        for j in range(count):
            off = VB_START + (base + j) * STRIDE
            x, y, z = new_positions[j]
            qx, qy, qz = quantize_pos(x, y, z, new_bbox)
            struct.pack_into('<3H', pac, off, qx, qy, qz)

        # Write bbox
        bbox_off = bbox_offsets[sm_idx]
        struct.pack_into('<2f', pac, bbox_off, bbox.lod_near, bbox.lod_far)
        struct.pack_into('<3f', pac, bbox_off + 8, *tuple(new_min))
        struct.pack_into('<3f', pac, bbox_off + 20, *tuple(new_dim))

    # Write output
    output_path = str(OUTPUT / "dragon_drogon_v3.pac")
    with open(output_path, 'wb') as f:
        f.write(pac)
    print(f"\n[3] Wrote: {output_path}")

    # Export OBJ for preview
    from pac_codec import export_obj
    export_obj(bytes(pac), str(OUTPUT / "dragon_drogon_v3.obj"))

    if '--deploy' in sys.argv:
        deploy_pac(output_path)
    else:
        print("Add --deploy to patch game files.")


if __name__ == "__main__":
    main()
