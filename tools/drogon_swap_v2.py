#!/usr/bin/env python3
"""
Drogon mesh swap v2 — proper bind-pose transforms.

Uses skeleton bind-pose matrices to:
1. Transform CD vertices to unified bind-pose world space
2. Align Drogon to that space
3. Project CD vertices onto Drogon surface
4. Transform back to model space using inverse bone matrices
"""
import struct
import csv
import os
import sys
import json
import numpy as np
from scipy.spatial import KDTree
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from pac_codec import (
    PAC_PATH, OUTPUT, VB_START, STRIDE, TOTAL_VERTS,
    SUBMESH_NAMES, SUBMESH_VERTEX_COUNTS, SUBMESH_BASES,
    parse_submesh_descriptors, decode_all_submeshes, quantize_pos,
    SubmeshBbox, read_indices,
)
from pac_patcher import find_bbox_offsets, deploy_pac

DROGON_OBJ = r"C:\Users\waelj\Desktop\Outputs\DROGON.OBJ"


def load_skeleton_matrices():
    """Load bone hash -> (world_matrix_4x4, inv_world_matrix_4x4) mapping."""
    with open(OUTPUT / "cd_skeleton.json", 'r') as f:
        skeleton = json.load(f)

    matrices = {}
    for bone in skeleton:
        h = bone['hash']
        wm = np.array(bone['world_matrix'], dtype=np.float64)  # 4x4
        iwm = np.array(bone['inv_world_matrix'], dtype=np.float64)  # 4x4
        matrices[h] = (wm, iwm)

    return matrices


def load_bone_palette(pac):
    """Load PAC bone palette: palette_idx -> bone_hash (unsigned)."""
    count = struct.unpack_from('<H', pac, 0x0441)[0]
    return [struct.unpack_from('<I', pac, 0x0443 + i * 4)[0] for i in range(count)]


def vertex_to_bind_world(v, bone_palette, skel_matrices):
    """Transform model-space vertex to bind-pose world space."""
    model_h = np.array([*v.pos, 1.0])
    world = np.zeros(3)

    for i in range(4):
        if v.bone_wt[i] > 0:
            w = v.bone_wt[i] / 255.0
            pidx = v.bone_idx[i]
            if pidx < len(bone_palette):
                bhash = bone_palette[pidx]
                if bhash in skel_matrices:
                    M = skel_matrices[bhash][0]  # world_matrix
                    world += w * (M @ model_h)[:3]
                else:
                    world += w * model_h[:3]
            else:
                world += w * model_h[:3]

    return world


def bind_world_to_model(world_pos, v, bone_palette, skel_matrices):
    """Transform bind-pose world position back to model space.

    Uses weighted inverse bone matrices — inverse of the forward skinning.
    For single-bone vertices this is exact. For multi-bone it's approximate.
    """
    world_h = np.array([*world_pos, 1.0])

    # Compute blended inverse matrix
    M_inv_blend = np.zeros((4, 4))
    total_w = 0

    for i in range(4):
        if v.bone_wt[i] > 0:
            w = v.bone_wt[i] / 255.0
            pidx = v.bone_idx[i]
            if pidx < len(bone_palette):
                bhash = bone_palette[pidx]
                if bhash in skel_matrices:
                    M_inv = skel_matrices[bhash][1]  # inv_world_matrix
                    M_inv_blend += w * M_inv
                    total_w += w

    if total_w < 0.01:
        return np.array(v.pos)

    # Normalize
    M_inv_blend /= total_w

    model = (M_inv_blend @ world_h)[:3]
    return model


def load_drogon_obj(path):
    """Load Drogon OBJ vertices."""
    verts = []
    with open(path, 'r') as f:
        for line in f:
            if line.startswith('v '):
                parts = line.split()
                verts.append((float(parts[1]), float(parts[2]), float(parts[3])))
    return np.array(verts, dtype=np.float64)


def compute_vertex_normals(positions, indices_per_submesh, submesh_bases, submesh_counts):
    """Recompute per-vertex normals from face normals."""
    normals = np.zeros_like(positions)

    global_offset = 0
    for sm_idx, sm_name in enumerate(SUBMESH_NAMES):
        base = submesh_bases[sm_idx]
        count = submesh_counts[sm_idx]
        indices = indices_per_submesh[sm_name]

        for tri in range(len(indices) // 3):
            i0 = indices[tri * 3 + 0]
            i1 = indices[tri * 3 + 1]
            i2 = indices[tri * 3 + 2]

            if i0 < count and i1 < count and i2 < count:
                p0 = positions[base + i0]
                p1 = positions[base + i1]
                p2 = positions[base + i2]

                edge1 = p1 - p0
                edge2 = p2 - p0
                face_normal = np.cross(edge1, edge2)
                norm = np.linalg.norm(face_normal)
                if norm > 1e-10:
                    face_normal /= norm

                normals[base + i0] += face_normal
                normals[base + i1] += face_normal
                normals[base + i2] += face_normal

    # Normalize
    norms = np.linalg.norm(normals, axis=1, keepdims=True)
    norms[norms < 1e-10] = 1.0
    normals /= norms

    return normals


def main():
    blend = float(sys.argv[sys.argv.index('--blend') + 1]) if '--blend' in sys.argv else 1.0

    print("=" * 60)
    print(f"DROGON MESH SWAP v2 (blend={blend})")
    print("Proper bind-pose transforms + smoothing")
    print("=" * 60)

    # Load everything
    print("\n[1] Loading data...")
    pac = bytearray(PAC_PATH.read_bytes())
    cd_data = decode_all_submeshes(bytes(pac))
    bboxes = parse_submesh_descriptors(bytes(pac))
    bbox_offsets = find_bbox_offsets(bytes(pac))
    indices = read_indices(bytes(pac))
    bone_palette = load_bone_palette(bytes(pac))
    skel_matrices = load_skeleton_matrices()
    print(f"    Skeleton: {len(skel_matrices)} bones, Palette: {len(bone_palette)} entries")

    drogon_raw = load_drogon_obj(DROGON_OBJ)
    print(f"    Drogon: {len(drogon_raw):,} vertices")

    # Step 2: Transform ALL CD vertices to bind-pose world space
    print("\n[2] Transforming CD vertices to bind-pose world space...")
    cd_bind_world = []
    all_verts_flat = []

    for sm_name in SUBMESH_NAMES:
        verts = cd_data[sm_name]['verts']
        for v in verts:
            bw = vertex_to_bind_world(v, bone_palette, skel_matrices)
            cd_bind_world.append(bw)
            all_verts_flat.append(v)

    cd_bind_world = np.array(cd_bind_world)
    print(f"    {len(cd_bind_world)} vertices transformed")
    print(f"    Bind-world X: [{cd_bind_world[:,0].min():.2f}, {cd_bind_world[:,0].max():.2f}]")
    print(f"    Bind-world Y: [{cd_bind_world[:,1].min():.2f}, {cd_bind_world[:,1].max():.2f}]")
    print(f"    Bind-world Z: [{cd_bind_world[:,2].min():.2f}, {cd_bind_world[:,2].max():.2f}]")

    # Step 3: Align Drogon to CD bind-world space
    print("\n[3] Aligning Drogon to CD bind-world space...")
    cd_min = cd_bind_world.min(axis=0)
    cd_max = cd_bind_world.max(axis=0)
    cd_center = (cd_min + cd_max) / 2
    cd_span = cd_max - cd_min

    d_min = drogon_raw.min(axis=0)
    d_max = drogon_raw.max(axis=0)
    d_center = (d_min + d_max) / 2
    d_span = d_max - d_min

    # Drogon axes: X=wingspan, Y=height, Z=length (head→tail)
    # CD bind-pose: need to determine from the data
    print(f"    CD bind span:    X={cd_span[0]:.2f} Y={cd_span[1]:.2f} Z={cd_span[2]:.2f}")
    print(f"    Drogon raw span: X={d_span[0]:.2f} Y={d_span[1]:.2f} Z={d_span[2]:.2f}")

    # Normalize Drogon to [0,1] then scale to CD
    d_normalized = (drogon_raw - d_min) / d_span

    # Axis mapping: try direct first (X→X, Y→Y, Z→Z)
    # We can also try swizzles and pick the one that produces the best fit
    drogon_aligned = np.zeros_like(drogon_raw)
    drogon_aligned[:, 0] = cd_min[0] + d_normalized[:, 0] * cd_span[0]
    drogon_aligned[:, 1] = cd_min[1] + d_normalized[:, 1] * cd_span[1]
    drogon_aligned[:, 2] = cd_min[2] + d_normalized[:, 2] * cd_span[2]

    print(f"    Drogon aligned span: X=[{drogon_aligned[:,0].min():.2f},{drogon_aligned[:,0].max():.2f}] "
          f"Y=[{drogon_aligned[:,1].min():.2f},{drogon_aligned[:,1].max():.2f}] "
          f"Z=[{drogon_aligned[:,2].min():.2f},{drogon_aligned[:,2].max():.2f}]")

    # Step 4: Build KD-tree and project
    print("\n[4] Building KD-tree and projecting...")
    tree = KDTree(drogon_aligned)

    new_bind_world = np.copy(cd_bind_world)
    dists, idxs = tree.query(cd_bind_world)

    # Blend between original and Drogon positions
    for i in range(len(cd_bind_world)):
        drogon_point = drogon_aligned[idxs[i]]
        new_bind_world[i] = cd_bind_world[i] + blend * (drogon_point - cd_bind_world[i])

    avg_dist = np.mean(dists)
    max_dist = np.max(dists)
    print(f"    Avg projection distance: {avg_dist:.4f}")
    print(f"    Max projection distance: {max_dist:.4f}")

    # Step 5: Laplacian smoothing (per-submesh to avoid index issues)
    print("\n[5] Smoothing projected positions...")
    smooth_factor = 0.3
    vert_offset = 0
    for sm_name in SUBMESH_NAMES:
        sm_count = SUBMESH_VERTEX_COUNTS[SUBMESH_NAMES.index(sm_name)]
        sm_indices_list = indices[sm_name]

        # Build local adjacency
        adj = [set() for _ in range(sm_count)]
        for tri in range(len(sm_indices_list) // 3):
            i0 = sm_indices_list[tri * 3 + 0]
            i1 = sm_indices_list[tri * 3 + 1]
            i2 = sm_indices_list[tri * 3 + 2]
            if i0 < sm_count and i1 < sm_count and i2 < sm_count:
                adj[i0].update([i1, i2])
                adj[i1].update([i0, i2])
                adj[i2].update([i0, i1])

        # 3 iterations of Laplacian smoothing on this submesh
        sm_slice = slice(vert_offset, vert_offset + sm_count)
        for _ in range(3):
            smoothed = np.copy(new_bind_world[sm_slice])
            for i in range(sm_count):
                if adj[i]:
                    neighbors = list(adj[i])
                    avg = new_bind_world[vert_offset + np.array(neighbors)].mean(axis=0)
                    smoothed[i] = new_bind_world[vert_offset + i] * (1 - smooth_factor) + avg * smooth_factor
            new_bind_world[sm_slice] = smoothed

        vert_offset += sm_count
    print(f"    3 Laplacian iterations per submesh (factor={smooth_factor})")

    # Step 6: Transform back to model space
    print("\n[6] Transforming back to model space...")
    new_model_positions = []
    vert_idx = 0
    for sm_name in SUBMESH_NAMES:
        verts = cd_data[sm_name]['verts']
        for v in verts:
            new_model = bind_world_to_model(new_bind_world[vert_idx], v,
                                             bone_palette, skel_matrices)
            new_model_positions.append(new_model)
            vert_idx += 1

    new_model_positions = np.array(new_model_positions)

    # Step 7: Write new positions to PAC
    print("\n[7] Encoding to PAC...")
    vert_idx = 0
    for sm_idx, sm_name in enumerate(SUBMESH_NAMES):
        base = SUBMESH_BASES[sm_idx]
        count = SUBMESH_VERTEX_COUNTS[sm_idx]
        bbox = bboxes[sm_idx]

        # Compute new bbox from this submesh's new positions
        sm_positions = new_model_positions[vert_idx:vert_idx + count]
        new_min = sm_positions.min(axis=0)
        new_max = sm_positions.max(axis=0)
        eps = 1e-6
        new_dim = np.maximum(new_max - new_min, eps)

        new_bbox = SubmeshBbox(
            name=sm_name,
            min_xyz=tuple(new_min),
            dim_xyz=tuple(new_dim),
            lod_near=bbox.lod_near,
            lod_far=bbox.lod_far,
        )

        print(f"  {sm_name:12s}: dim ({bbox.dim_xyz[0]:.3f},{bbox.dim_xyz[1]:.3f},{bbox.dim_xyz[2]:.3f}) "
              f"-> ({new_dim[0]:.3f},{new_dim[1]:.3f},{new_dim[2]:.3f})")

        # Write positions
        for j in range(count):
            off = VB_START + (base + j) * STRIDE
            x, y, z = new_model_positions[vert_idx + j]
            qx, qy, qz = quantize_pos(x, y, z, new_bbox)
            struct.pack_into('<3H', pac, off, qx, qy, qz)

        # Write bbox
        bbox_off = bbox_offsets[sm_idx]
        struct.pack_into('<2f', pac, bbox_off, bbox.lod_near, bbox.lod_far)
        struct.pack_into('<3f', pac, bbox_off + 8, *tuple(new_min))
        struct.pack_into('<3f', pac, bbox_off + 20, *tuple(new_dim))

        vert_idx += count

    # Write output
    output_path = str(OUTPUT / "dragon_drogon_v2.pac")
    with open(output_path, 'wb') as f:
        f.write(pac)
    print(f"\n[8] Wrote: {output_path} ({len(pac):,} bytes)")

    # Export OBJ
    from pac_codec import export_obj
    export_obj(bytes(pac), str(OUTPUT / "dragon_drogon_v2.obj"))

    if '--deploy' in sys.argv:
        print("\n[9] Deploying to game...")
        deploy_pac(output_path)
    else:
        print("\nAdd --deploy to patch game files.")


if __name__ == "__main__":
    main()
