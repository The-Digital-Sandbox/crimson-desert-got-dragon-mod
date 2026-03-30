#!/usr/bin/env python3
"""
Export CD dragon mesh using BDO-style bone hash palette.

Pipeline (from Szkaradek123's BDO script):
  1. PAC header: uint16 count + int32 bone hashes = per-submesh palette
  2. Vertex byte12 -> palette[byte12] -> bone hash -> skeleton bone index
  3. Skeleton bone world matrix transforms bone-local position to world space
  4. Weighted skinning: sum(weight[i] * pos * bone_world[palette[idx[i]]])
"""
import struct, json, math, os
import numpy as np

os.environ['PYTHONIOENCODING'] = 'utf-8'

with open('output/dragon.pac', 'rb') as f:
    pac = f.read()
with open('output/cd_skeleton.json') as f:
    skel = json.load(f)

# --- Constants ---
VBUF = 0x7BFA
STRIDE = 40
N = 27376
IDX_START = 0x4AE982
SCALE = 4.0

SM_NAMES = ['Eyeright', 'Eyeleft', 'Body_02', 'back', 'Body', 'Leg', 'Wing', 'Head']
SM_VCOUNTS = [225, 225, 2013, 3307, 2736, 4624, 6724, 10258]
SM_ICOUNTS = [1248, 1248, 7992, 17007, 13380, 22464, 34902, 51180]
UNIQUE_ORDER = [0, 1, 2, 3, 5, 6, 7]
SM_VSTART = {}
running = 0
for ui in UNIQUE_ORDER:
    SM_VSTART[ui] = running
    running += SM_VCOUNTS[ui]
SM_VSTART[4] = SM_VSTART[3]

# --- 1. Parse bone hash palette from PAC at 0x0441 ---
skel_hash_to_idx = {b['hash']: b['index'] for b in skel}
skel_hash_to_name = {b['hash']: b['name'] for b in skel}

pal_count = struct.unpack_from('<H', pac, 0x0441)[0]  # 227
palette = []  # palette[i] = skeleton bone index
for i in range(pal_count):
    h = struct.unpack_from('<I', pac, 0x0443 + i * 4)[0]
    palette.append(skel_hash_to_idx.get(h, -1))

print(f'Bone palette: {pal_count} entries, {sum(1 for p in palette if p >= 0)} matched')

# --- 2. Build skeleton world matrices ---
bone_local = {}
bone_parent = {}
for i, bone in enumerate(skel):
    bone_parent[i] = bone.get('parent_index', -1)
    bone_local[i] = np.array(bone['local_matrix'], dtype=np.float64) if 'local_matrix' in bone else np.eye(4)

# But BDO script uses ARMATURESPACE=True with bone.matrix directly from PAB
# That means the FIRST matrix in PAB is already world-space, no hierarchy accumulation needed
# Our skeleton.json has 'world_matrix' — let's use that directly
bone_world = {}
for bone in skel:
    bone_world[bone['index']] = np.array(bone['world_matrix'], dtype=np.float64)

# --- 3. Read vertices and apply skinning ---
print('Skinning vertices...')
skinned = []
raw_positions = []
untransformed = 0

for i in range(N):
    o = VBUF + i * STRIDE
    px, py, pz = struct.unpack_from('<3e', pac, o)
    px, py, pz = float(px), float(py), float(pz)
    if math.isnan(px): px = 0
    if math.isnan(py): py = 0
    if math.isnan(pz): pz = 0
    raw_positions.append((px, py, pz))

    # Bone indices and weights
    bi = [pac[o + 12 + b] for b in range(4)]
    bw = [pac[o + 20 + b] for b in range(4)]
    total_w = sum(bw)

    if total_w == 0:
        skinned.append((px * SCALE, py * SCALE, pz * SCALE))
        untransformed += 1
        continue

    pos = np.array([px, py, pz, 1.0])
    result = np.zeros(3)

    for b in range(4):
        if bw[b] == 0:
            continue
        pal_idx = bi[b]
        if pal_idx < len(palette) and palette[pal_idx] >= 0:
            skel_idx = palette[pal_idx]
            mat = bone_world[skel_idx]
            # Try row-vector: world = pos @ mat
            transformed = pos @ mat
            result += transformed[:3] * (bw[b] / total_w)
        else:
            result += np.array([px, py, pz]) * (bw[b] / total_w)
            untransformed += 1

    skinned.append((float(result[0]) * SCALE, float(result[1]) * SCALE, float(result[2]) * SCALE))

print(f'  Untransformed influences: {untransformed}')
xs = [v[0] for v in skinned]
ys = [v[1] for v in skinned]
zs = [v[2] for v in skinned]
print(f'  Range: X[{min(xs):.1f}, {max(xs):.1f}] Y[{min(ys):.1f}, {max(ys):.1f}] Z[{min(zs):.1f}, {max(zs):.1f}]')

# --- 4. Read indices ---
total_indices = sum(SM_ICOUNTS)
all_indices = list(struct.unpack_from(f'<{total_indices}H', pac, IDX_START))

# --- 5. Export ---
out = 'output/dragon_skinned.obj'
print(f'Writing {out}...')
with open(out, 'w') as f:
    f.write(f'# CD Dragon - bone hash palette + world matrices\n')
    f.write(f'# {N} verts, {total_indices//3} tris, scale={SCALE}\n\n')
    for x, y, z in skinned:
        f.write(f'v {x:.6f} {y:.6f} {z:.6f}\n')
    idx_pos = 0
    for si in range(8):
        icount = SM_ICOUNTS[si]
        voff = SM_VSTART[si]
        f.write(f'\ng {SM_NAMES[si]}\n')
        for tri in range(icount // 3):
            i0 = all_indices[idx_pos + tri*3] + voff + 1
            i1 = all_indices[idx_pos + tri*3+1] + voff + 1
            i2 = all_indices[idx_pos + tri*3+2] + voff + 1
            f.write(f'f {i0} {i1} {i2}\n')
        idx_pos += icount

# Also try column-vector convention: world = mat @ pos
skinned_col = []
for i in range(N):
    o = VBUF + i * STRIDE
    px, py, pz = raw_positions[i]
    bi = [pac[o + 12 + b] for b in range(4)]
    bw = [pac[o + 20 + b] for b in range(4)]
    total_w = sum(bw)
    if total_w == 0:
        skinned_col.append((px * SCALE, py * SCALE, pz * SCALE))
        continue
    pos = np.array([px, py, pz, 1.0])
    result = np.zeros(3)
    for b in range(4):
        if bw[b] == 0:
            continue
        pal_idx = bi[b]
        if pal_idx < len(palette) and palette[pal_idx] >= 0:
            mat = bone_world[palette[pal_idx]]
            transformed = mat @ pos  # column-vector convention
            result += transformed[:3] * (bw[b] / total_w)
        else:
            result += np.array([px, py, pz]) * (bw[b] / total_w)
    skinned_col.append((float(result[0]) * SCALE, float(result[1]) * SCALE, float(result[2]) * SCALE))

out2 = 'output/dragon_skinned_col.obj'
with open(out2, 'w') as f:
    f.write(f'# CD Dragon - column-vector convention\n\n')
    for x, y, z in skinned_col:
        f.write(f'v {x:.6f} {y:.6f} {z:.6f}\n')
    idx_pos = 0
    for si in range(8):
        icount = SM_ICOUNTS[si]
        voff = SM_VSTART[si]
        f.write(f'\ng {SM_NAMES[si]}\n')
        for tri in range(icount // 3):
            i0 = all_indices[idx_pos + tri*3] + voff + 1
            i1 = all_indices[idx_pos + tri*3+1] + voff + 1
            i2 = all_indices[idx_pos + tri*3+2] + voff + 1
            f.write(f'f {i0} {i1} {i2}\n')
        idx_pos += icount

# Raw (no transforms) for comparison
out3 = 'output/dragon_raw.obj'
with open(out3, 'w') as f:
    f.write(f'# CD Dragon - raw positions, no transforms\n\n')
    for x, y, z in raw_positions:
        f.write(f'v {x*SCALE:.6f} {y*SCALE:.6f} {z*SCALE:.6f}\n')
    idx_pos = 0
    for si in range(8):
        icount = SM_ICOUNTS[si]
        voff = SM_VSTART[si]
        f.write(f'\ng {SM_NAMES[si]}\n')
        for tri in range(icount // 3):
            i0 = all_indices[idx_pos + tri*3] + voff + 1
            i1 = all_indices[idx_pos + tri*3+1] + voff + 1
            i2 = all_indices[idx_pos + tri*3+2] + voff + 1
            f.write(f'f {i0} {i1} {i2}\n')
        idx_pos += icount

print(f'Wrote: {out}, {out2}, {out3}')
print('Open all 3 in Blender to compare.')
