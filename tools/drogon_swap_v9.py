#!/usr/bin/env python3
"""
Drogon swap v9 — POSITION-ONLY replacement.

The working formula: change ONLY positions (bytes 0-5) and bboxes.
Leave W, extra0, extra1, uv1, normals, bone data untouched from the original.
The engine needs those exact values.

Input: drogon_decimated.obj (8 groups, exact per-submesh vertex counts)
       OR falls back to sampling DROGON.OBJ evenly if decimated OBJ not found.

Pipeline:
  1. Read decimated Drogon OBJ (8 groups, exact vert counts)
  2. Convert from Blender Z-up to game Y-up
  3. Scale + translate to match CD dragon's bind-pose extent
  4. Per submesh: compute new bbox, quantize positions, write bytes 0-5
  5. Write new bboxes to PAC descriptor
  6. Optionally update normals (--normals flag)
  7. Deploy (--deploy flag)

Usage:
  python drogon_swap_v9.py                    # build PAC only
  python drogon_swap_v9.py --deploy           # build + deploy to game
  python drogon_swap_v9.py --normals          # also update normals
  python drogon_swap_v9.py --normals --deploy # full pipeline
  python drogon_swap_v9.py --restore          # restore original PAC
"""
import struct
import sys
import math
import numpy as np
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).parent))
from pac_codec import (
    PAC_PATH, OUTPUT, VB_START, STRIDE,
    SUBMESH_NAMES, SUBMESH_VERTEX_COUNTS, SUBMESH_BASES,
    parse_submesh_descriptors, decode_all_submeshes,
    quantize_pos, encode_normal_r10g10b10a2, SubmeshBbox,
    read_indices,
)
from pac_patcher import find_bbox_offsets, deploy_pac

DECIMATED_OBJ = OUTPUT / "drogon_decimated.obj"
DROGON_OBJ = Path(r"C:\Users\waelj\Desktop\Outputs\DROGON.OBJ")
OUTPUT_PAC = OUTPUT / "dragon_drogon_v9.pac"


def read_obj_groups(obj_path: str) -> dict:
    """Read OBJ file, return {group_name: [(x,y,z), ...]} preserving vertex order."""
    groups = {}
    current_group = None
    normals = {}
    current_normals = None

    with open(obj_path, 'r') as f:
        for line in f:
            line = line.strip()
            if line.startswith('g '):
                current_group = line.split(' ', 1)[1].strip()
                groups[current_group] = []
                normals[current_group] = []
                current_normals = normals[current_group]
            elif line.startswith('v ') and current_group is not None:
                parts = line.split()
                groups[current_group].append((float(parts[1]), float(parts[2]), float(parts[3])))
            elif line.startswith('vn ') and current_group is not None:
                parts = line.split()
                current_normals.append((float(parts[1]), float(parts[2]), float(parts[3])))

    return groups, normals


def read_obj_flat(obj_path: str) -> np.ndarray:
    """Read all vertices from OBJ, ignoring groups."""
    verts = []
    with open(obj_path, 'r') as f:
        for line in f:
            if line.startswith('v '):
                p = line.split()
                verts.append((float(p[1]), float(p[2]), float(p[3])))
    return np.array(verts)


def blender_to_game(positions: np.ndarray) -> np.ndarray:
    """Convert Blender Z-up coordinates to game Y-up.

    Blender: X-right, Y-forward, Z-up
    Game:    X-right, Y-up, Z-forward (roughly)

    Mapping: game_x = blender_x, game_y = blender_z, game_z = -blender_y
    """
    result = np.zeros_like(positions)
    result[:, 0] = positions[:, 0]   # X stays
    result[:, 1] = positions[:, 2]   # Y = Blender Z (up)
    result[:, 2] = -positions[:, 1]  # Z = -Blender Y (flip forward)
    return result


def blender_normal_to_game(normals: np.ndarray) -> np.ndarray:
    """Same axis swap for normals."""
    result = np.zeros_like(normals)
    result[:, 0] = normals[:, 0]
    result[:, 1] = normals[:, 2]
    result[:, 2] = -normals[:, 1]
    return result


def align_to_cd_bbox(drogon_game: np.ndarray, cd_overall_min: np.ndarray,
                     cd_overall_max: np.ndarray) -> np.ndarray:
    """Scale and translate Drogon game-space positions to match CD dragon's overall extent."""
    d_min = drogon_game.min(axis=0)
    d_max = drogon_game.max(axis=0)
    d_dim = d_max - d_min
    cd_dim = cd_overall_max - cd_overall_min

    # Uniform scale to fit within CD bbox (preserve aspect ratio)
    # Use the axis with largest ratio to ensure Drogon fits inside
    scale_per_axis = np.where(d_dim > 1e-6, cd_dim / d_dim, 1.0)
    uniform_scale = scale_per_axis.min()  # fit inside

    # Center Drogon on CD center
    d_center = (d_min + d_max) / 2.0
    cd_center = (cd_overall_min + cd_overall_max) / 2.0

    aligned = (drogon_game - d_center) * uniform_scale + cd_center
    return aligned


def compute_normals_from_indices(positions: np.ndarray, index_list: list, count: int) -> np.ndarray:
    """Compute per-vertex normals from positions and triangle indices."""
    normals = np.zeros((count, 3), dtype=np.float64)

    for tri in range(len(index_list) // 3):
        i0, i1, i2 = index_list[tri*3], index_list[tri*3+1], index_list[tri*3+2]
        if max(i0, i1, i2) >= count:
            continue
        v0, v1, v2 = positions[i0], positions[i1], positions[i2]
        e1 = v1 - v0
        e2 = v2 - v0
        n = np.cross(e1, e2)
        length = np.linalg.norm(n)
        if length > 1e-10:
            n /= length
        normals[i0] += n
        normals[i1] += n
        normals[i2] += n

    # Normalize
    lengths = np.linalg.norm(normals, axis=1, keepdims=True)
    lengths = np.where(lengths < 1e-10, 1.0, lengths)
    normals /= lengths
    return normals


def sample_evenly(all_verts: np.ndarray, submesh_counts: list) -> dict:
    """Fallback: sample Drogon verts evenly across submeshes."""
    total_needed = sum(submesh_counts)
    n = len(all_verts)
    indices = np.linspace(0, n - 1, total_needed, dtype=int)
    sampled = all_verts[indices]

    result = {}
    offset = 0
    for i, name in enumerate(SUBMESH_NAMES):
        count = submesh_counts[i]
        result[name] = sampled[offset:offset + count]
        offset += count
    return result


def main():
    do_deploy = '--deploy' in sys.argv
    do_normals = '--normals' in sys.argv
    do_restore = '--restore' in sys.argv

    if do_restore:
        from pac_patcher import restore_pac
        restore_pac()
        return

    print("=" * 60)
    print("DROGON SWAP v9 — POSITION-ONLY REPLACEMENT")
    print("=" * 60)
    print(f"  Normals: {'YES' if do_normals else 'NO (use --normals to enable)'}")
    print(f"  Deploy:  {'YES' if do_deploy else 'NO (use --deploy to enable)'}")

    # Load original PAC
    pac = bytearray(PAC_PATH.read_bytes())
    original_size = len(pac)
    bboxes = parse_submesh_descriptors(bytes(pac))
    bbox_offsets = find_bbox_offsets(bytes(pac))
    indices = read_indices(bytes(pac))

    print(f"\n  Original PAC: {original_size:,} bytes")

    # Compute CD dragon overall bbox
    cd_overall_min = np.array([999.0, 999.0, 999.0])
    cd_overall_max = np.array([-999.0, -999.0, -999.0])
    for bb in bboxes:
        mn = np.array(bb.min_xyz)
        mx = mn + np.array(bb.dim_xyz)
        cd_overall_min = np.minimum(cd_overall_min, mn)
        cd_overall_max = np.maximum(cd_overall_max, mx)
    print(f"  CD bbox: min=({cd_overall_min[0]:.3f},{cd_overall_min[1]:.3f},{cd_overall_min[2]:.3f}) "
          f"max=({cd_overall_max[0]:.3f},{cd_overall_max[1]:.3f},{cd_overall_max[2]:.3f})")

    # Load Drogon positions
    use_decimated = DECIMATED_OBJ.exists()
    drogon_normals_per_sm = {}

    if use_decimated:
        print(f"\n  Loading decimated OBJ: {DECIMATED_OBJ}")
        groups, obj_normals = read_obj_groups(str(DECIMATED_OBJ))

        # Validate counts
        drogon_per_sm = {}
        all_ok = True
        for i, sm_name in enumerate(SUBMESH_NAMES):
            if sm_name not in groups:
                print(f"  ERROR: group '{sm_name}' not found in OBJ")
                print(f"  Available groups: {list(groups.keys())}")
                all_ok = False
                continue
            actual = len(groups[sm_name])
            target = SUBMESH_VERTEX_COUNTS[i]
            status = "OK" if actual == target else f"MISMATCH"
            print(f"    {sm_name:12s}: {actual:6d} / {target:6d}  [{status}]")
            if actual != target:
                all_ok = False

            # Convert list of tuples to numpy array
            positions = np.array(groups[sm_name])
            # Convert from Blender Z-up to game Y-up
            positions = blender_to_game(positions)
            drogon_per_sm[sm_name] = positions

            if sm_name in obj_normals and len(obj_normals[sm_name]) == actual:
                n = np.array(obj_normals[sm_name])
                drogon_normals_per_sm[sm_name] = blender_normal_to_game(n)

        if not all_ok:
            print("\n  Vertex count mismatch! Re-run blender_decimate_drogon.py")
            print("  Falling back to even sampling...")
            use_decimated = False

    if not use_decimated:
        print(f"\n  Loading full Drogon OBJ: {DROGON_OBJ}")
        all_verts = read_obj_flat(str(DROGON_OBJ))
        print(f"  {len(all_verts)} verts loaded")

        # Convert to game space
        all_verts = blender_to_game(all_verts)

        # Align to CD bbox
        all_verts = align_to_cd_bbox(all_verts, cd_overall_min, cd_overall_max)

        # Sample evenly per submesh
        drogon_per_sm = sample_evenly(all_verts, SUBMESH_VERTEX_COUNTS)
        print("  Sampled evenly across submeshes")

    # Align each submesh's Drogon positions to CD space
    # For decimated OBJ: align the overall Drogon model to CD's bbox
    if use_decimated:
        # Combine all submesh positions to compute global alignment
        all_drogon = np.vstack(list(drogon_per_sm.values()))
        d_min = all_drogon.min(axis=0)
        d_max = all_drogon.max(axis=0)
        d_dim = d_max - d_min
        cd_dim = cd_overall_max - cd_overall_min

        # Uniform scale
        scale_per_axis = np.where(d_dim > 1e-6, cd_dim / d_dim, 1.0)
        uniform_scale = scale_per_axis.min()

        d_center = (d_min + d_max) / 2.0
        cd_center = (cd_overall_min + cd_overall_max) / 2.0

        print(f"\n  Alignment: scale={uniform_scale:.6f}")
        print(f"  Drogon center: ({d_center[0]:.3f},{d_center[1]:.3f},{d_center[2]:.3f})")
        print(f"  CD center:     ({cd_center[0]:.3f},{cd_center[1]:.3f},{cd_center[2]:.3f})")

        # Apply alignment to each submesh
        for sm_name in drogon_per_sm:
            drogon_per_sm[sm_name] = (drogon_per_sm[sm_name] - d_center) * uniform_scale + cd_center

    # Write positions into PAC
    print("\n  Writing positions to PAC...")
    for sm_idx, sm_name in enumerate(SUBMESH_NAMES):
        base = SUBMESH_BASES[sm_idx]
        count = SUBMESH_VERTEX_COUNTS[sm_idx]
        old_bbox = bboxes[sm_idx]

        positions = drogon_per_sm[sm_name]
        assert len(positions) == count, f"{sm_name}: {len(positions)} != {count}"

        # Compute new bbox (with tiny padding to avoid quantization edge cases)
        PAD = 0.001
        new_min = positions.min(axis=0) - PAD
        new_max = positions.max(axis=0) + PAD
        new_dim = np.maximum(new_max - new_min, 1e-6)
        new_bbox = SubmeshBbox(sm_name, tuple(new_min), tuple(new_dim),
                               old_bbox.lod_near, old_bbox.lod_far)

        # Write quantized positions (bytes 0-5 only)
        for j in range(count):
            off = VB_START + (base + j) * STRIDE
            x, y, z = positions[j]
            qx, qy, qz = quantize_pos(x, y, z, new_bbox)
            struct.pack_into('<3H', pac, off, qx, qy, qz)
            # bytes 6-7 (W), 8-39: UNTOUCHED from original

        # Write new bbox to PAC descriptor
        bbox_off = bbox_offsets[sm_idx]
        struct.pack_into('<2f', pac, bbox_off, old_bbox.lod_near, old_bbox.lod_far)
        struct.pack_into('<3f', pac, bbox_off + 8, *tuple(new_min))
        struct.pack_into('<3f', pac, bbox_off + 20, *tuple(new_dim))

        print(f"    {sm_name:12s}: {count:5d} verts, "
              f"bbox ({old_bbox.dim_xyz[0]:.2f},{old_bbox.dim_xyz[1]:.2f},{old_bbox.dim_xyz[2]:.2f}) -> "
              f"({new_dim[0]:.2f},{new_dim[1]:.2f},{new_dim[2]:.2f})")

    # Optionally update normals
    if do_normals:
        print("\n  Updating normals (bytes 8-11)...")
        for sm_idx, sm_name in enumerate(SUBMESH_NAMES):
            base = SUBMESH_BASES[sm_idx]
            count = SUBMESH_VERTEX_COUNTS[sm_idx]
            positions = drogon_per_sm[sm_name]

            if sm_name in drogon_normals_per_sm and use_decimated:
                # Use normals from OBJ export (pre-computed in Blender)
                norms = drogon_normals_per_sm[sm_name]
                src = "OBJ"
            else:
                # Compute from index buffer adjacency
                norms = compute_normals_from_indices(
                    positions, indices[sm_name], count)
                src = "computed"

            for j in range(count):
                off = VB_START + (base + j) * STRIDE + 8
                nx, ny, nz = norms[j]
                packed = encode_normal_r10g10b10a2(nx, ny, nz)
                struct.pack_into('<I', pac, off, packed)

            print(f"    {sm_name:12s}: {count:5d} normals ({src})")

    # Verify size
    assert len(pac) == original_size, f"PAC size changed! {len(pac)} != {original_size}"

    # Write output
    OUTPUT_PAC.write_bytes(pac)
    print(f"\n  Output: {OUTPUT_PAC}")
    print(f"  Size: {len(pac):,} bytes (matches original: {len(pac) == original_size})")

    # Export preview OBJ
    preview_path = OUTPUT / "dragon_drogon_v9_preview.obj"
    export_preview_obj(pac, str(preview_path))

    if do_deploy:
        print("\n  Deploying to game...")
        deploy_pac(str(OUTPUT_PAC))
    else:
        print("\n  Add --deploy to patch game files.")
        print("  Add --normals to also update normals.")


def export_preview_obj(pac: bytes, obj_path: str):
    """Export the patched PAC as OBJ for visual inspection."""
    from pac_codec import decode_all_submeshes, read_indices
    data = decode_all_submeshes(bytes(pac))
    idx = read_indices(bytes(pac))

    with open(obj_path, 'w') as f:
        f.write("# Drogon v9 preview — position-only replacement\n")
        global_off = 0
        for name in SUBMESH_NAMES:
            sm = data[name]
            f.write(f"\ng {name}\n")
            for v in sm['verts']:
                f.write(f"v {v.pos[0]:.6f} {v.pos[1]:.6f} {v.pos[2]:.6f}\n")
            for v in sm['verts']:
                f.write(f"vn {v.normal[0]:.6f} {v.normal[1]:.6f} {v.normal[2]:.6f}\n")
            sm_idx_list = idx[name]
            for tri in range(len(sm_idx_list) // 3):
                i0 = sm_idx_list[tri*3] + global_off + 1
                i1 = sm_idx_list[tri*3+1] + global_off + 1
                i2 = sm_idx_list[tri*3+2] + global_off + 1
                f.write(f"f {i0}//{i0} {i1}//{i1} {i2}//{i2}\n")
            global_off += sm['count']

    print(f"  Preview OBJ: {obj_path}")


if __name__ == "__main__":
    main()
