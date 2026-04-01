#!/usr/bin/env python3
"""
Diagnose why build_pac_from_glb.py produces a scrambled mesh.

Checks:
1. Bone palette: original vs rebuilt — entry-by-entry diff
2. Vertex counts: GLB vs CD per submesh — truncation/padding
3. Index counts: GLB vs CD per submesh
4. Bone index validity in the OUTPUT PAC (dragon_drogon_final.pac)
5. Bone weight sanity in the OUTPUT PAC
6. GLB joint name -> CD skeleton name matching
7. Coordinate scale/range comparison
"""
import struct
import json
import math
import numpy as np
from pathlib import Path
from collections import Counter

try:
    import pygltflib
except ImportError:
    print("pip install pygltflib numpy")
    raise

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "output"
ORIGINAL_PAC = OUTPUT / "dragon.pac"
BUILT_PAC = OUTPUT / "dragon_drogon_final.pac"
GLB_PATH = OUTPUT / "DrogonRigged-correctweights.glb"
SKELETON_JSON = OUTPUT / "cd_skeleton.json"

VB_START = 0x7BFA
STRIDE = 40
PALETTE_OFFSET = 0x443

SUBMESH_NAMES = ["Eyeright", "Eyeleft", "Body_02", "back", "Body", "Leg", "Wing", "Head"]
SUBMESH_VERTEX_COUNTS = [225, 225, 2013, 3307, 2736, 4624, 6724, 10258]
SUBMESH_INDEX_COUNTS = [1248, 1248, 7992, 17007, 13380, 22464, 34902, 51180]

CD_SUBMESH_NAMES = [
    "CD_M0004_00_Dragon_Eyeright_0001",
    "CD_M0004_00_Dragon_Eyeleft_0001",
    "CD_M0004_00_Dragon_Body_0001_02",
    "CD_M0004_00_Dragon_back_0001",
    "CD_M0004_00_Dragon_Body_0001",
    "CD_M0004_00_Dragon_Leg_0001",
    "CD_M0004_00_Dragon_Wing_0001",
    "CD_M0004_00_Dragon_Head_0001",
]

SUBMESH_BASES = []
_base = 0
for vc in SUBMESH_VERTEX_COUNTS:
    SUBMESH_BASES.append(_base)
    _base += vc


def read_accessor(glb, accessor_index):
    acc = glb.accessors[accessor_index]
    bv = glb.bufferViews[acc.bufferView]
    COMP_TYPES = {5120: ('b', 1), 5121: ('B', 1), 5122: ('h', 2),
                  5123: ('H', 2), 5125: ('I', 4), 5126: ('f', 4)}
    fmt, comp_size = COMP_TYPES[acc.componentType]
    TYPE_COUNTS = {'SCALAR': 1, 'VEC2': 2, 'VEC3': 3, 'VEC4': 4, 'MAT4': 16}
    num_components = TYPE_COUNTS[acc.type]
    blob = glb.binary_blob()
    offset = (bv.byteOffset or 0) + (acc.byteOffset or 0)
    stride = bv.byteStride or (comp_size * num_components)
    result = []
    for i in range(acc.count):
        elem_offset = offset + i * stride
        values = struct.unpack_from(f'<{num_components}{fmt}', blob, elem_offset)
        result.append(values if num_components > 1 else values[0])
    return result


def read_bone_palette(pac, skeleton_by_hash):
    """Read palette hashes from PAC, stopping when hash not in skeleton."""
    hashes = []
    offset = PALETTE_OFFSET
    while offset + 4 <= len(pac):
        h = struct.unpack_from('<I', pac, offset)[0]
        if h not in skeleton_by_hash:
            break
        hashes.append(h)
        offset += 4
    return hashes


def read_vertex_bones(pac, vertex_index):
    """Read bone indices and weights from a vertex (old layout)."""
    off = VB_START + vertex_index * STRIDE
    bone_idx = struct.unpack_from('4B', pac, off + 12)
    bone_wt = struct.unpack_from('4B', pac, off + 20)
    return bone_idx, bone_wt


def read_vertex_pos_raw(pac, vertex_index):
    """Read raw u16 position from vertex."""
    off = VB_START + vertex_index * STRIDE
    return struct.unpack_from('<3H', pac, off)


def main():
    skeleton = json.loads(SKELETON_JSON.read_text(encoding='utf-8'))
    skeleton_by_hash = {b['hash']: b for b in skeleton}
    skeleton_by_name = {b['name']: b for b in skeleton}

    orig_pac = ORIGINAL_PAC.read_bytes()
    has_built = BUILT_PAC.exists()
    built_pac = BUILT_PAC.read_bytes() if has_built else None

    print("=" * 70)
    print("  BUILD DIAGNOSTIC")
    print("=" * 70)

    # ── 1. Bone palette comparison ──────────────────────────────────
    print(f"\n{'='*70}")
    print("  1. BONE PALETTE: Original vs Built")
    print("=" * 70)

    orig_palette = read_bone_palette(orig_pac, skeleton_by_hash)
    print(f"  Original palette: {len(orig_palette)} entries")

    if has_built:
        built_palette = read_bone_palette(built_pac, skeleton_by_hash)
        print(f"  Built palette:    {len(built_palette)} entries")

        if len(orig_palette) != len(built_palette):
            print(f"  !! PALETTE SIZE MISMATCH: {len(orig_palette)} vs {len(built_palette)}")

        diffs = 0
        for i in range(min(len(orig_palette), len(built_palette))):
            if orig_palette[i] != built_palette[i]:
                orig_bone = skeleton_by_hash.get(orig_palette[i], {}).get('name', '???')
                built_bone = skeleton_by_hash.get(built_palette[i], {}).get('name', '???')
                if diffs < 20:
                    print(f"  DIFF [{i:3d}]: orig={orig_bone:30s} built={built_bone}")
                diffs += 1

        if diffs == 0:
            print("  PALETTES MATCH EXACTLY")
        else:
            print(f"  Total diffs: {diffs} / {min(len(orig_palette), len(built_palette))}")
            print("  !! PALETTE REORDERING DETECTED — this will scramble bone lookups")
    else:
        print("  (no built PAC found, skipping comparison)")

    # ── 2. GLB mesh analysis ────────────────────────────────────────
    print(f"\n{'='*70}")
    print("  2. GLB vs CD: Vertex and Index Counts")
    print("=" * 70)

    if GLB_PATH.exists():
        glb = pygltflib.GLTF2().load(str(GLB_PATH))
        mesh = glb.meshes[0]
        skin = glb.skins[0]
        joint_names = [glb.nodes[j].name for j in skin.joints]

        print(f"  GLB joints: {len(joint_names)}")
        print(f"  GLB primitives: {len(mesh.primitives)}")

        # Map primitives by material name
        mat_to_prim = {}
        for prim in mesh.primitives:
            mat_name = glb.materials[prim.material].name if prim.material is not None else ""
            mat_to_prim[mat_name] = prim

        total_vert_deficit = 0
        total_idx_deficit = 0

        print(f"\n  {'Submesh':40s} {'GLB verts':>10s} {'CD verts':>10s} {'diff':>8s} "
              f"{'GLB idx':>10s} {'CD idx':>10s} {'diff':>8s}")
        print(f"  {'-'*40} {'-'*10} {'-'*10} {'-'*8} {'-'*10} {'-'*10} {'-'*8}")

        for si, cd_mat_name in enumerate(CD_SUBMESH_NAMES):
            prim = mat_to_prim.get(cd_mat_name)
            if prim is None:
                print(f"  {cd_mat_name:40s} MISSING IN GLB")
                continue

            glb_vc = glb.accessors[prim.attributes.POSITION].count
            cd_vc = SUBMESH_VERTEX_COUNTS[si]
            v_diff = glb_vc - cd_vc

            glb_ic = glb.accessors[prim.indices].count if prim.indices is not None else 0
            cd_ic = SUBMESH_INDEX_COUNTS[si]
            i_diff = glb_ic - cd_ic

            status_v = "OK" if v_diff == 0 else ("TRUNC" if v_diff > 0 else "PAD")
            status_i = "OK" if i_diff == 0 else ("TRUNC" if i_diff > 0 else "PAD")

            total_vert_deficit += abs(v_diff)
            total_idx_deficit += abs(i_diff)

            print(f"  {SUBMESH_NAMES[si]:40s} {glb_vc:10d} {cd_vc:10d} {v_diff:+8d} "
                  f"{glb_ic:10d} {cd_ic:10d} {i_diff:+8d}")

        print(f"\n  Total vertex misalignment: {total_vert_deficit}")
        print(f"  Total index misalignment:  {total_idx_deficit}")

        if total_vert_deficit > 0:
            print("  !! VERTEX COUNT MISMATCH — truncation/padding will corrupt bone assignments")

        # ── 3. Joint name matching ──────────────────────────────────
        print(f"\n{'='*70}")
        print("  3. GLB Joint Names vs CD Skeleton")
        print("=" * 70)

        matched = 0
        unmatched = []
        for i, jn in enumerate(joint_names):
            if jn in skeleton_by_name:
                matched += 1
            else:
                unmatched.append((i, jn))

        print(f"  Matched: {matched} / {len(joint_names)}")
        if unmatched:
            print(f"  UNMATCHED ({len(unmatched)}):")
            for idx, name in unmatched[:20]:
                print(f"    joint[{idx}]: '{name}'")
            if len(unmatched) > 20:
                print(f"    ... and {len(unmatched) - 20} more")
            print("  !! Unmatched joints will fall back to Bip01 (root) in palette")

        # ── 4. GLB bone weight analysis ─────────────────────────────
        print(f"\n{'='*70}")
        print("  4. GLB Bone Weight Quality")
        print("=" * 70)

        for si, cd_mat_name in enumerate(CD_SUBMESH_NAMES):
            prim = mat_to_prim.get(cd_mat_name)
            if prim is None:
                continue

            has_joints = prim.attributes.JOINTS_0 is not None
            has_weights = prim.attributes.WEIGHTS_0 is not None

            if not has_joints or not has_weights:
                print(f"  {SUBMESH_NAMES[si]:12s}: NO SKINNING DATA")
                continue

            joints = read_accessor(glb, prim.attributes.JOINTS_0)
            weights = read_accessor(glb, prim.attributes.WEIGHTS_0)

            zero_weight = 0
            max_bones_used = 0
            weight_sums = []
            out_of_range = 0

            for vi in range(len(joints)):
                j = joints[vi]
                w = weights[vi]
                wsum = sum(w)
                weight_sums.append(wsum)

                active = sum(1 for ww in w if ww > 0.001)
                max_bones_used = max(max_bones_used, active)

                if wsum < 0.01:
                    zero_weight += 1

                for ji in j:
                    if ji >= len(joint_names):
                        out_of_range += 1

            avg_sum = np.mean(weight_sums)
            min_sum = np.min(weight_sums)
            max_sum = np.max(weight_sums)

            print(f"  {SUBMESH_NAMES[si]:12s}: {len(joints):5d} verts, "
                  f"max_bones={max_bones_used}, zero_wt={zero_weight}, "
                  f"out_of_range_joints={out_of_range}, "
                  f"wsum=[{min_sum:.3f}, {avg_sum:.3f}, {max_sum:.3f}]")

    else:
        print("  GLB not found, skipping")

    # ── 5. Built PAC bone index sanity ──────────────────────────────
    if has_built:
        print(f"\n{'='*70}")
        print("  5. BUILT PAC: Bone Index & Weight Sanity")
        print("=" * 70)

        built_palette = read_bone_palette(built_pac, skeleton_by_hash)
        pal_size = len(built_palette)

        for si, sm_name in enumerate(SUBMESH_NAMES):
            base = SUBMESH_BASES[si]
            count = SUBMESH_VERTEX_COUNTS[si]

            out_of_range = 0
            zero_weight = 0
            bad_sum = 0
            bone_counter = Counter()

            for vi in range(base, base + count):
                bi, bw = read_vertex_bones(built_pac, vi)
                wsum = sum(bw)

                if wsum == 0:
                    zero_weight += 1
                elif abs(wsum - 255) > 1:
                    bad_sum += 1

                for ch in range(4):
                    if bw[ch] > 0:
                        if bi[ch] >= pal_size:
                            out_of_range += 1
                        else:
                            h = built_palette[bi[ch]]
                            bone = skeleton_by_hash.get(h)
                            if bone:
                                bone_counter[bone['name']] += 1

            top = bone_counter.most_common(5)
            top_str = ', '.join(f"{n}({c})" for n, c in top)
            print(f"  {sm_name:12s}: out_of_range={out_of_range:4d}, "
                  f"zero_wt={zero_weight:4d}, bad_sum={bad_sum:4d}")
            print(f"    top bones: {top_str}")

        # ── 6. Position range comparison ────────────────────────────
        print(f"\n{'='*70}")
        print("  6. Position Range: Original vs Built")
        print("=" * 70)

        for si, sm_name in enumerate(SUBMESH_NAMES):
            base = SUBMESH_BASES[si]
            count = SUBMESH_VERTEX_COUNTS[si]

            orig_positions = []
            built_positions = []
            for vi in range(base, base + count):
                orig_positions.append(read_vertex_pos_raw(orig_pac, vi))
                built_positions.append(read_vertex_pos_raw(built_pac, vi))

            orig_arr = np.array(orig_positions)
            built_arr = np.array(built_positions)

            print(f"  {sm_name:12s}:")
            print(f"    Orig  range: X=[{orig_arr[:,0].min():5d},{orig_arr[:,0].max():5d}] "
                  f"Y=[{orig_arr[:,1].min():5d},{orig_arr[:,1].max():5d}] "
                  f"Z=[{orig_arr[:,2].min():5d},{orig_arr[:,2].max():5d}]")
            print(f"    Built range: X=[{built_arr[:,0].min():5d},{built_arr[:,0].max():5d}] "
                  f"Y=[{built_arr[:,1].min():5d},{built_arr[:,1].max():5d}] "
                  f"Z=[{built_arr[:,2].min():5d},{built_arr[:,2].max():5d}]")

    # ── 7. Compare bytes that SHOULDN'T change ──────────────────────
    if has_built:
        print(f"\n{'='*70}")
        print("  7. Byte Preservation Check (fields that should match original)")
        print("=" * 70)

        # Check: are bytes 6-7 (W), 24-27 (extra1), 36-39 (UV1) preserved?
        fields_to_check = [
            ("W (bytes 6-7)", 6, 2),
            ("extra1 (bytes 24-27)", 24, 4),
        ]

        for field_name, field_off, field_len in fields_to_check:
            diffs = 0
            for vi in range(sum(SUBMESH_VERTEX_COUNTS)):
                off = VB_START + vi * STRIDE + field_off
                if orig_pac[off:off+field_len] != built_pac[off:off+field_len]:
                    diffs += 1

            status = "PRESERVED" if diffs == 0 else f"CHANGED in {diffs} verts"
            print(f"  {field_name:30s}: {status}")

        # Check header region (bytes 0x0000 to VB_START)
        header_match = orig_pac[:PALETTE_OFFSET] == built_pac[:PALETTE_OFFSET]
        print(f"  {'Header (0x0 to 0x443)':30s}: {'MATCH' if header_match else 'DIFFERS'}")

        # Check descriptor region changes
        desc_start = 0x77
        desc_end = PALETTE_OFFSET
        desc_diffs = sum(1 for i in range(desc_start, desc_end)
                        if orig_pac[i] != built_pac[i])
        print(f"  {'Descriptor region':30s}: {desc_diffs} bytes changed (bboxes expected)")

    print(f"\n{'='*70}")
    print("  DIAGNOSTIC COMPLETE")
    print("=" * 70)


if __name__ == '__main__':
    main()
