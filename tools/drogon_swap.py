#!/usr/bin/env python3
"""
Drogon mesh swap — project CD dragon vertices onto Drogon surface.

Strategy:
1. Load Drogon OBJ (149K verts) as target surface
2. Load CD dragon PIX world-space positions + PAC model-space positions
3. Align Drogon to CD world-space bounds
4. For each CD vertex, find nearest Drogon point (world-space)
5. Use per-vertex world/model ratio to convert Drogon positions to model-space
6. Encode to PAC and deploy
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
    PAC_PATH, OUTPUT, VB_START, STRIDE, TOTAL_VERTS,
    SUBMESH_NAMES, SUBMESH_VERTEX_COUNTS, SUBMESH_BASES,
    parse_submesh_descriptors, decode_all_submeshes, quantize_pos,
    SubmeshBbox, encode_normal_r10g10b10a2,
)
from pac_patcher import find_bbox_offsets, deploy_pac, PAC_SIZE

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


def load_drogon_obj(path):
    """Load Drogon OBJ as numpy array of vertex positions."""
    verts = []
    with open(path, 'r') as f:
        for line in f:
            if line.startswith('v '):
                parts = line.split()
                verts.append((float(parts[1]), float(parts[2]), float(parts[3])))
    return np.array(verts, dtype=np.float64)


def load_pix_world_positions(gpu_id, expected_count):
    """Load PIX VS output as dict of vertex_id -> world_pos."""
    csv_path = os.path.join(PIX_DIR,
        f"2026_3_30__9_24_50_GpuId{gpu_id}_VS_BufferData_exp0.csv")
    if not os.path.exists(csv_path):
        return None

    positions = {}
    with open(csv_path, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            vid = int(row['Vertex_ID'])
            if vid not in positions:
                positions[vid] = np.array([
                    float(row['TEXCOORD1_C0']),
                    float(row['TEXCOORD1_C1']),
                    float(row['TEXCOORD1_C2']),
                ], dtype=np.float64)
    return positions


def compute_alignment(drogon_verts, cd_world_bounds):
    """Compute scale + translation to align Drogon to CD world-space."""
    # CD world bounds (from PIX — all submeshes combined)
    cd_min = cd_world_bounds['min']
    cd_max = cd_world_bounds['max']
    cd_center = (cd_min + cd_max) / 2
    cd_span = cd_max - cd_min

    # Drogon bounds
    d_min = drogon_verts.min(axis=0)
    d_max = drogon_verts.max(axis=0)
    d_center = (d_min + d_max) / 2
    d_span = d_max - d_min

    # Scale: match the longest axis
    # CD dragon is roughly: X=14, Y=25, Z=19 (world-space)
    # Drogon: X=1676, Y=353, Z=1448
    # But axis mapping might differ. Let's check orientation:
    # CD: X=left-right, Y=up-forward(?), Z=up(?)
    # Need to figure out axis mapping from the group structure

    # From the bounds analysis:
    # Drogon: X=[-838, 838] (wingspan), Y=[-4, 349] (height), Z=[-382, 1066] (length)
    # CD world: X=[-12, 2] (lateral), Y=[-30, -5] (longitudinal?), Z=[19, 39] (up?)

    # The CD world Y goes negative (forward direction), Z is up
    # Drogon X is wingspan, Z is length (head to tail), Y is height

    # Mapping: Drogon X -> CD X (lateral/wingspan)
    #          Drogon Z -> CD Y (negated, length/forward-back)
    #          Drogon Y -> CD Z (height/up)

    return d_center, d_span, cd_center, cd_span


def transform_drogon_to_cd_world(drogon_verts, cd_world_bounds):
    """Transform Drogon vertices to CD world coordinate space."""
    d_center, d_span, cd_center, cd_span = compute_alignment(drogon_verts, cd_world_bounds)

    # Map Drogon -> CD world
    # Drogon X (wingspan, -838 to 838) -> CD X (lateral, -12 to 2, center ~-5)
    # Drogon Z (length, -382 to 1066) -> CD Y (forward, -30 to -5, center ~-17)
    # Drogon Y (height, -4 to 349) -> CD Z (up, 19 to 39, center ~29)

    # Normalize to [0,1]
    d_min = drogon_verts.min(axis=0)
    d_max = drogon_verts.max(axis=0)
    d_range = d_max - d_min
    d_range[d_range < 1e-8] = 1.0

    normalized = (drogon_verts - d_min) / d_range  # [0, 1]

    # Map to CD world space with axis swizzle
    cd_min = cd_world_bounds['min']
    cd_max = cd_world_bounds['max']
    cd_range = cd_max - cd_min

    result = np.zeros_like(drogon_verts)
    # Drogon X -> CD X (same direction: positive = right)
    result[:, 0] = cd_min[0] + normalized[:, 0] * cd_range[0]
    # Drogon Z -> CD Y (Drogon Z+ = forward, CD Y- = forward, so FLIP)
    result[:, 1] = cd_max[1] - normalized[:, 2] * cd_range[1]
    # Drogon Y -> CD Z (same direction: up)
    result[:, 2] = cd_min[2] + normalized[:, 1] * cd_range[2]

    return result


def main():
    print("=" * 60)
    print("DROGON MESH SWAP")
    print("=" * 60)

    # Step 1: Load Drogon
    print("\n[1] Loading Drogon OBJ...")
    drogon_verts = load_drogon_obj(DROGON_OBJ)
    print(f"    {len(drogon_verts):,} vertices loaded")
    print(f"    Bounds X: [{drogon_verts[:,0].min():.1f}, {drogon_verts[:,0].max():.1f}]")
    print(f"    Bounds Y: [{drogon_verts[:,1].min():.1f}, {drogon_verts[:,1].max():.1f}]")
    print(f"    Bounds Z: [{drogon_verts[:,2].min():.1f}, {drogon_verts[:,2].max():.1f}]")

    # Step 2: Load CD dragon from PAC
    print("\n[2] Loading CD dragon from PAC...")
    pac = bytearray(PAC_PATH.read_bytes())
    cd_data = decode_all_submeshes(bytes(pac))
    bboxes = parse_submesh_descriptors(bytes(pac))
    bbox_offsets = find_bbox_offsets(bytes(pac))

    # Step 3: Load PIX world positions and compute world bounds
    print("\n[3] Loading PIX world-space positions...")
    all_world_min = np.array([1e9, 1e9, 1e9])
    all_world_max = np.array([-1e9, -1e9, -1e9])
    pix_data = {}

    for gpu_id, (sm_name, sm_idx) in PIX_MAP.items():
        count = SUBMESH_VERTEX_COUNTS[sm_idx]
        positions = load_pix_world_positions(gpu_id, count)
        if positions is None:
            print(f"    WARNING: No PIX data for {sm_name}")
            continue
        pix_data[sm_name] = positions
        for wp in positions.values():
            all_world_min = np.minimum(all_world_min, wp)
            all_world_max = np.maximum(all_world_max, wp)
        print(f"    {sm_name}: {len(positions)} vertices")

    cd_world_bounds = {'min': all_world_min, 'max': all_world_max}
    print(f"    World bounds: X=[{all_world_min[0]:.2f},{all_world_max[0]:.2f}] "
          f"Y=[{all_world_min[1]:.2f},{all_world_max[1]:.2f}] "
          f"Z=[{all_world_min[2]:.2f},{all_world_max[2]:.2f}]")

    # Step 4: Transform Drogon to CD world space
    print("\n[4] Aligning Drogon to CD world-space...")
    drogon_world = transform_drogon_to_cd_world(drogon_verts, cd_world_bounds)
    print(f"    Aligned bounds X: [{drogon_world[:,0].min():.2f},{drogon_world[:,0].max():.2f}]")
    print(f"    Aligned bounds Y: [{drogon_world[:,1].min():.2f},{drogon_world[:,1].max():.2f}]")
    print(f"    Aligned bounds Z: [{drogon_world[:,2].min():.2f},{drogon_world[:,2].max():.2f}]")

    # Step 5: Build KD-tree of Drogon world positions
    print("\n[5] Building KD-tree of Drogon surface...")
    drogon_tree = KDTree(drogon_world)

    # Step 6: For each CD submesh, project onto Drogon
    print("\n[6] Projecting CD vertices onto Drogon surface...")
    for sm_name, (gpu_id_key) in [
        ('Body_02', '7153'), ('back', '7154'), ('Body', '7155'),
        ('Leg', '7156'), ('Wing', '7157'), ('Head', '7158')
    ]:
        sm_idx = SUBMESH_NAMES.index(sm_name)
        base = SUBMESH_BASES[sm_idx]
        count = SUBMESH_VERTEX_COUNTS[sm_idx]
        bbox = bboxes[sm_idx]

        if sm_name not in pix_data:
            print(f"  Skipping {sm_name} (no PIX data)")
            continue

        pix = pix_data[sm_name]
        cd_verts = cd_data[sm_name]['verts']

        new_positions = []

        for vid in range(count):
            old_model = np.array(cd_verts[vid].pos, dtype=np.float64)

            if vid in pix:
                old_world = pix[vid]

                # Find nearest Drogon point
                dist, idx = drogon_tree.query(old_world)
                new_world = drogon_world[idx]

                # Compute per-axis model/world ratio for coordinate transform
                # model_pos ≈ some_transform(world_pos)
                # For nearby vertices, this ratio is roughly constant
                delta_world = new_world - old_world

                # Approximate the world-to-model Jacobian from the local relationship
                # model_span / world_span per axis gives the scale
                # Use per-submesh bbox dim vs world extent as the scale factor
                world_extent = cd_world_bounds['max'] - cd_world_bounds['min']
                model_dim = np.array(bbox.dim_xyz, dtype=np.float64)

                # Better approach: compute ratio from this vertex's actual positions
                # model = f(world), and we want f(new_world) ≈ f(old_world) + J * (new_world - old_world)
                # where J = d(model)/d(world)
                # For single-bone vertices, J is just the inverse bone rotation/scale
                # Approximate J from the per-submesh relationship
                scale = model_dim / (world_extent + 1e-8)
                scale = np.clip(scale, -2, 2)

                new_model = old_model + delta_world * np.abs(scale)
            else:
                new_model = old_model

            new_positions.append(new_model)

        # Compute new bbox
        all_pos = np.array(new_positions)
        new_min = all_pos.min(axis=0)
        new_max = all_pos.max(axis=0)
        eps = 1e-6
        new_dim = np.maximum(new_max - new_min, eps)

        new_bbox = SubmeshBbox(
            name=sm_name,
            min_xyz=tuple(new_min),
            dim_xyz=tuple(new_dim),
            lod_near=bbox.lod_near,
            lod_far=bbox.lod_far,
        )

        print(f"  {sm_name}: projected {count} verts, "
              f"bbox dim ({bbox.dim_xyz[0]:.3f},{bbox.dim_xyz[1]:.3f},{bbox.dim_xyz[2]:.3f}) -> "
              f"({new_dim[0]:.3f},{new_dim[1]:.3f},{new_dim[2]:.3f})")

        # Write new positions to PAC
        for j in range(count):
            off = VB_START + (base + j) * STRIDE
            x, y, z = new_positions[j]
            qx, qy, qz = quantize_pos(x, y, z, new_bbox)
            struct.pack_into('<3H', pac, off, qx, qy, qz)

        # Write new bbox
        bbox_off = bbox_offsets[sm_idx]
        struct.pack_into('<2f', pac, bbox_off, bbox.lod_near, bbox.lod_far)
        struct.pack_into('<3f', pac, bbox_off + 8, *tuple(new_min))
        struct.pack_into('<3f', pac, bbox_off + 20, *tuple(new_dim))

    # Handle eyes (SM0, SM1) — no PIX data, keep original or scale slightly
    print("  Eyeright/Eyeleft: keeping original (no PIX data)")

    # Step 7: Write output
    output_path = str(OUTPUT / "dragon_drogon.pac")
    with open(output_path, 'wb') as f:
        f.write(pac)
    print(f"\n[7] Wrote Drogon-swapped PAC: {output_path}")
    print(f"    Size: {len(pac):,} bytes")

    # Step 8: Export OBJ for visual verification
    from pac_codec import export_obj
    export_obj(bytes(pac), str(OUTPUT / "dragon_drogon.obj"))

    if '--deploy' in sys.argv:
        print("\n[8] Deploying to game...")
        deploy_pac(output_path)
    else:
        print("\nAdd --deploy to patch game files.")

    return output_path


if __name__ == "__main__":
    main()
