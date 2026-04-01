#!/usr/bin/env python3
"""
Build a PAC file by surgically injecting Drogon GLB geometry into the original
CD dragon PAC.

KEY FIX: Preserves the ORIGINAL bone palette byte-for-byte and maps GLB joint
indices to match. Previous versions rebuilt a compact palette which reordered
all 227 entries, causing every bone lookup to resolve to the wrong bone.

Changes: LOD0 vertex buffer (positions, normals, bone idx/wt, UVs),
         submesh bounding boxes, index buffer.
Preserves: bone palette, section offsets, LOD data, header, descriptor structure.

Usage:
    python tools/build_pac_from_glb.py
    python tools/build_pac_from_glb.py --deploy
"""
import struct
import json
import math
import sys
import numpy as np
from pathlib import Path

try:
    import pygltflib
except ImportError:
    print("pip install pygltflib numpy")
    raise

sys.path.insert(0, str(Path(__file__).parent))
from pac_codec import (
    VB_START, STRIDE, SUBMESH_NAMES, SUBMESH_VERTEX_COUNTS,
    SUBMESH_INDEX_COUNTS, SUBMESH_BASES, parse_submesh_descriptors,
    SubmeshBbox, encode_normal_r10g10b10a2, quantize_pos,
)

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "output"
GLB_PATH = OUTPUT / "DrogonRigged-correctweights.glb"
SKELETON_JSON = OUTPUT / "cd_skeleton.json"
ORIGINAL_PAC = OUTPUT / "dragon.pac"
OUTPUT_PAC = OUTPUT / "dragon_drogon_final.pac"

SCALE = 4.0  # Blender scene scale (armature is 4x game scale)

# CD submesh material names in PAC order
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

PALETTE_OFFSET = 0x443


# ── GLB Data Extraction ──────────────────────────────────────────────

def read_accessor(glb, accessor_index):
    """Read raw data from a GLB accessor into a list."""
    acc = glb.accessors[accessor_index]
    bv = glb.bufferViews[acc.bufferView]
    COMP_TYPES = {
        5120: ('b', 1), 5121: ('B', 1), 5122: ('h', 2),
        5123: ('H', 2), 5125: ('I', 4), 5126: ('f', 4),
    }
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


def extract_glb_meshes(glb_path):
    """Extract GLB primitives, reordered to match CD submesh order by material name."""
    glb = pygltflib.GLTF2().load(str(glb_path))
    mesh = glb.meshes[0]
    skin = glb.skins[0]
    joint_names = [glb.nodes[j].name for j in skin.joints]

    raw_prims = []
    for prim in mesh.primitives:
        mat_name = glb.materials[prim.material].name if prim.material is not None else ""
        d = {
            'mat_name': mat_name,
            'positions': read_accessor(glb, prim.attributes.POSITION),
            'normals': read_accessor(glb, prim.attributes.NORMAL),
            'uvs': read_accessor(glb, prim.attributes.TEXCOORD_0) if prim.attributes.TEXCOORD_0 is not None else None,
            'joints': read_accessor(glb, prim.attributes.JOINTS_0) if prim.attributes.JOINTS_0 is not None else None,
            'weights': read_accessor(glb, prim.attributes.WEIGHTS_0) if prim.attributes.WEIGHTS_0 is not None else None,
            'indices': read_accessor(glb, prim.indices) if prim.indices is not None else None,
        }
        d['vert_count'] = len(d['positions'])
        d['index_count'] = len(d['indices']) if d['indices'] else 0
        raw_prims.append(d)

    mat_to_prim = {p['mat_name']: p for p in raw_prims}
    primitives = []
    for expected_name in CD_SUBMESH_NAMES:
        if expected_name in mat_to_prim:
            primitives.append(mat_to_prim[expected_name])
        else:
            print(f"ERROR: No primitive for material '{expected_name}'")
            print(f"  Available: {[p['mat_name'] for p in raw_prims]}")
            return None, None

    print(f"  Reordered {len(primitives)} primitives to match CD submesh order")
    return primitives, joint_names


# ── Coordinate Conversion ────────────────────────────────────────────

def glb_to_game(gx, gy, gz):
    """GLB (Y-up) -> Game (Y-up, negate Z)."""
    return (gx / SCALE, gy / SCALE, -gz / SCALE)


def glb_normal_to_game(nx, ny, nz):
    """Convert normal from GLB to game space."""
    return (nx, ny, -nz)


# ── Bone Palette (PRESERVED from original PAC) ──────────────────────

def read_original_palette(pac, skeleton_by_hash):
    """Read the original bone palette from PAC at 0x443."""
    hashes = []
    offset = PALETTE_OFFSET
    while offset + 4 <= len(pac):
        h = struct.unpack_from('<I', pac, offset)[0]
        if h not in skeleton_by_hash:
            break
        hashes.append(h)
        offset += 4
    return hashes


def build_j2p_from_original_palette(joint_names, skeleton, original_palette_hashes):
    """Map GLB joint indices to ORIGINAL palette indices.

    Finds each GLB joint's bone hash and looks up where it already exists
    in the original palette. For unmapped joints, walks up the skeleton
    hierarchy to find the nearest ancestor that IS in the palette.
    """
    name_to_hash = {b['name']: b['hash'] for b in skeleton}
    name_to_bone = {b['name']: b for b in skeleton}

    hash_to_palette_idx = {}
    for pi, h in enumerate(original_palette_hashes):
        hash_to_palette_idx[h] = pi

    def find_ancestor_in_palette(bone_name):
        visited = set()
        current = bone_name
        while current and current not in visited:
            visited.add(current)
            bone = name_to_bone.get(current)
            if bone is None:
                break
            h = name_to_hash.get(current)
            if h is not None and h in hash_to_palette_idx:
                return hash_to_palette_idx[h], current
            current = bone.get('parent_name')
        for fallback_name in ['Bip01 Pelvis', 'Bip01 Spine', 'Bip01 Spine1']:
            h = name_to_hash.get(fallback_name)
            if h is not None and h in hash_to_palette_idx:
                return hash_to_palette_idx[h], fallback_name
        return 0, 'palette[0]'

    j2p = {}
    unmapped = []
    for gi, jname in enumerate(joint_names):
        h = name_to_hash.get(jname)
        if h is not None and h in hash_to_palette_idx:
            j2p[gi] = hash_to_palette_idx[h]
        else:
            pal_idx, ancestor = find_ancestor_in_palette(jname)
            j2p[gi] = pal_idx
            unmapped.append((gi, jname, ancestor, pal_idx))

    if unmapped:
        print(f"  Remapped {len(unmapped)} GLB joints via hierarchy walk:")
        for gi, jn, ancestor, pidx in unmapped[:15]:
            print(f"    joint[{gi:3d}] '{jn}' -> [{pidx:3d}] '{ancestor}'")

    return j2p


# ── Bbox finder ──────────────────────────────────────────────────────

def find_bbox_offsets(pac: bytes) -> list[int]:
    offsets = []
    off = 0x0077
    for i in range(8):
        name_len = pac[off]; off += 1 + name_len
        mat_len = pac[off]; off += 1 + mat_len
        off += 3
        offsets.append(off)
        off += 32
        next_cd = pac.find(b'CD_M0004', off)
        off = (next_cd - 1) if (0 < next_cd < 0x0441) else 0x0441
    return offsets


# ── Surgical PAC Build ───────────────────────────────────────────────

def build_pac(primitives, joint_names, skeleton):
    """Inject Drogon geometry into original PAC.

    - Copies entire original PAC byte-for-byte
    - Overwrites LOD0 vertex buffer per submesh
    - Updates submesh bounding boxes
    - Injects Drogon's index buffer
    - PRESERVES original bone palette (no reordering)
    """
    orig_pac = ORIGINAL_PAC.read_bytes()
    pac = bytearray(orig_pac)

    orig_bboxes = parse_submesh_descriptors(orig_pac)
    bbox_offsets = find_bbox_offsets(orig_pac)

    # Read ORIGINAL bone palette — DO NOT overwrite
    skeleton_by_hash = {b['hash']: b for b in skeleton}
    original_palette = read_original_palette(orig_pac, skeleton_by_hash)
    print(f"  Original bone palette: {len(original_palette)} entries (PRESERVED)")

    # Map GLB joint indices to original palette positions
    j2p = build_j2p_from_original_palette(joint_names, skeleton, original_palette)
    mapped_count = sum(1 for v in j2p.values() if v > 0)
    print(f"  Joint->palette mapping: {mapped_count} joints mapped to non-zero palette indices")

    # Process each submesh
    for si, prim in enumerate(primitives):
        cd_vert_count = SUBMESH_VERTEX_COUNTS[si]
        cd_base = SUBMESH_BASES[si]
        glb_vert_count = prim['vert_count']
        name = SUBMESH_NAMES[si]

        print(f"  SM{si} {name}: GLB={glb_vert_count} verts -> CD={cd_vert_count} slots")

        # Convert GLB positions to game space
        game_positions = []
        game_normals = []
        game_uvs = []
        game_bone_indices = []
        game_bone_weights = []

        for vi in range(glb_vert_count):
            bx, by, bz = prim['positions'][vi]
            game_positions.append(glb_to_game(bx, by, bz))

            nx, ny, nz = prim['normals'][vi]
            gnx, gny, gnz = glb_normal_to_game(nx, ny, nz)
            length = math.sqrt(gnx*gnx + gny*gny + gnz*gnz)
            if length > 1e-8:
                gnx /= length; gny /= length; gnz /= length
            game_normals.append((gnx, gny, gnz))

            if prim['uvs']:
                u, v = prim['uvs'][vi]
                game_uvs.append((u, v))
            else:
                game_uvs.append((0.0, 0.0))

            if prim['joints'] and prim['weights']:
                j0, j1, j2, j3 = prim['joints'][vi]
                w0, w1, w2, w3 = prim['weights'][vi]
                # Map through ORIGINAL palette (not compact)
                bi = (j2p.get(j0, 0), j2p.get(j1, 0), j2p.get(j2, 0), j2p.get(j3, 0))
                wt = [w0, w1, w2, w3]
                wt_sum = sum(wt)
                if wt_sum > 0:
                    wt = [w / wt_sum for w in wt]
                else:
                    wt = [1.0, 0.0, 0.0, 0.0]
                int_wt = [int(round(w * 255)) for w in wt]
                diff = 255 - sum(int_wt)
                if int_wt[0] + diff >= 0:
                    int_wt[0] += diff
                bw = tuple(max(0, min(255, w)) for w in int_wt)
                game_bone_indices.append(bi)
                game_bone_weights.append(bw)
            else:
                game_bone_indices.append((0, 0, 0, 0))
                game_bone_weights.append((255, 0, 0, 0))

        # Compute new bbox from Drogon positions
        xs = [p[0] for p in game_positions]
        ys = [p[1] for p in game_positions]
        zs = [p[2] for p in game_positions]

        PAD = 0.001
        new_min = (min(xs) - PAD, min(ys) - PAD, min(zs) - PAD)
        new_max = (max(xs) + PAD, max(ys) + PAD, max(zs) + PAD)
        new_dim = (new_max[0] - new_min[0], new_max[1] - new_min[1], new_max[2] - new_min[2])
        new_bbox = SubmeshBbox(name=name, min_xyz=new_min, dim_xyz=new_dim)

        # Write new bbox into PAC descriptor
        bbox_off = bbox_offsets[si]
        orig_bbox = orig_bboxes[si]
        struct.pack_into('<2f', pac, bbox_off, orig_bbox.lod_near, orig_bbox.lod_far)
        struct.pack_into('<3f', pac, bbox_off + 8, *new_min)
        struct.pack_into('<3f', pac, bbox_off + 20, *new_dim)

        # Write vertices into LOD0 VB slots
        write_count = min(glb_vert_count, cd_vert_count)

        for vi in range(write_count):
            off = VB_START + (cd_base + vi) * STRIDE

            # Preserve fields we don't set from original
            orig_raw_w = struct.unpack_from('<H', pac, off + 6)[0]

            gx, gy, gz = game_positions[vi]
            qx, qy, qz = quantize_pos(gx, gy, gz, new_bbox)
            struct.pack_into('<3H', pac, off, qx, qy, qz)
            struct.pack_into('<H', pac, off + 6, orig_raw_w)

            nx, ny, nz = game_normals[vi]
            struct.pack_into('<I', pac, off + 8, encode_normal_r10g10b10a2(nx, ny, nz))

            bi = game_bone_indices[vi]
            struct.pack_into('4B', pac, off + 12, bi[0] & 0xFF, bi[1] & 0xFF, bi[2] & 0xFF, bi[3] & 0xFF)

            # Tangent from normal
            if abs(nx) < 0.9:
                tx, ty, tz = 0.0, -nz, ny
            else:
                tx, ty, tz = -nz, 0.0, nx
            tlen = math.sqrt(tx*tx + ty*ty + tz*tz)
            if tlen > 1e-8:
                tx /= tlen; ty /= tlen; tz /= tlen
            struct.pack_into('<I', pac, off + 16, encode_normal_r10g10b10a2(tx, ty, tz))

            bw = game_bone_weights[vi]
            struct.pack_into('4B', pac, off + 20, *bw)

            # Preserve bytes 24-27 (extra1) and 28-31 (vcolor) from original

            # UV0
            u, v = game_uvs[vi]
            struct.pack_into('<2H', pac, off + 32,
                             max(0, min(65535, int(round(u * 65535)))),
                             max(0, min(65535, int(round(v * 65535)))))
            # UV1 — preserve from original (bytes 36-39 contain flags)

        # If GLB has fewer verts than CD, duplicate last vertex into remaining slots
        if glb_vert_count < cd_vert_count:
            print(f"    Padding {cd_vert_count - glb_vert_count} remaining slots with last vertex")
            last_off = VB_START + (cd_base + write_count - 1) * STRIDE
            last_vert = bytes(pac[last_off:last_off + STRIDE])
            for vi in range(write_count, cd_vert_count):
                off = VB_START + (cd_base + vi) * STRIDE
                pac[off:off + STRIDE] = last_vert

        if glb_vert_count > cd_vert_count:
            print(f"    WARNING: GLB has {glb_vert_count - cd_vert_count} extra verts (truncated)")

    # ── Inject index buffer ──────────────────────────────────────────
    total_orig_indices = sum(SUBMESH_INDEX_COUNTS)
    ib_start = len(pac) - total_orig_indices * 2

    print(f"\n  Injecting index buffer at 0x{ib_start:X}...")

    ib_offset = ib_start
    for si, prim in enumerate(primitives):
        cd_ic = SUBMESH_INDEX_COUNTS[si]
        cd_vc = SUBMESH_VERTEX_COUNTS[si]
        glb_indices = prim['indices'] if prim['indices'] else []
        glb_ic = len(glb_indices)
        name = SUBMESH_NAMES[si]

        write_ic = min(glb_ic, cd_ic)

        for ii in range(write_ic):
            idx = glb_indices[ii]
            if idx >= cd_vc:
                idx = cd_vc - 1
            struct.pack_into('<H', pac, ib_offset + ii * 2, idx)

        # Pad remaining index slots with degenerate triangles
        for ii in range(write_ic, cd_ic):
            struct.pack_into('<H', pac, ib_offset + ii * 2, 0)

        if glb_ic < cd_ic:
            print(f"    SM{si} {name}: wrote {glb_ic} indices, padded {cd_ic - glb_ic} degenerate")
        elif glb_ic > cd_ic:
            print(f"    SM{si} {name}: wrote {cd_ic} indices (truncated {glb_ic - cd_ic})")
        else:
            print(f"    SM{si} {name}: wrote {cd_ic} indices (exact)")

        ib_offset += cd_ic * 2

    print(f"\n  Output PAC: {len(pac):,} bytes (same as original: {len(orig_pac):,})")
    return bytes(pac)


def main():
    do_deploy = '--deploy' in sys.argv

    print("=" * 60)
    print("  GLB -> PAC Injection (palette-preserving)")
    print("=" * 60)

    print(f"\nLoading GLB: {GLB_PATH.name}")
    primitives, joint_names = extract_glb_meshes(GLB_PATH)
    if primitives is None:
        return
    print(f"  {len(primitives)} primitives, {len(joint_names)} joints")

    print(f"Loading skeleton: {SKELETON_JSON.name}")
    with open(str(SKELETON_JSON)) as f:
        skeleton = json.load(f)
    print(f"  {len(skeleton)} bones")

    print("\nInjecting into original PAC...")
    pac_data = build_pac(primitives, joint_names, skeleton)

    OUTPUT_PAC.write_bytes(pac_data)
    print(f"\nWrote: {OUTPUT_PAC}")
    print(f"Size: {len(pac_data):,} bytes")

    if do_deploy:
        from deploy_new_pac import deploy
        print("\nDeploying...")
        deploy()
    else:
        print("\nAdd --deploy to patch game files.")

    print("\n" + "=" * 60)
    print("  BUILD COMPLETE")
    print("=" * 60)


if __name__ == '__main__':
    main()
