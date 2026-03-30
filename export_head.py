#!/usr/bin/env python3
"""Export just the Head submesh (SM7) with bone hash palette transforms."""
import struct, json, math, os
import numpy as np

os.environ['PYTHONIOENCODING'] = 'utf-8'

with open('output/dragon.pac', 'rb') as f:
    pac = f.read()
with open('output/cd_skeleton.json') as f:
    skel = json.load(f)

VBUF = 0x7BFA
STRIDE = 40
IDX_START = 0x4AE982
SCALE = 4.0
HEAD_VSTART = 17118
HEAD_VCOUNT = 10258
HEAD_ICOUNT = 51180

# Skip to Head's index offset (sum of prior submesh indices)
head_idx_offset = IDX_START + (1248 + 1248 + 7992 + 17007 + 13380 + 22464 + 34902) * 2

# Bone hash palette at 0x0441
skel_hash_to_idx = {b['hash']: b['index'] for b in skel}
pal_count = struct.unpack_from('<H', pac, 0x0441)[0]
palette = []
for i in range(pal_count):
    h = struct.unpack_from('<I', pac, 0x0443 + i * 4)[0]
    palette.append(skel_hash_to_idx.get(h, -1))

# Skeleton world matrices (direct from PAB, ARMATURESPACE)
bone_world = {b['index']: np.array(b['world_matrix'], dtype=np.float64) for b in skel}

# Read head vertices
print(f'Head: {HEAD_VCOUNT} verts, {HEAD_ICOUNT//3} tris')
print(f'Palette: {pal_count} entries')

# Export 4 versions: raw, row-vec, col-vec, inverse
for mode in ['raw', 'row', 'col']:
    verts = []
    for i in range(HEAD_VCOUNT):
        o = VBUF + (HEAD_VSTART + i) * STRIDE
        px, py, pz = struct.unpack_from('<3e', pac, o)
        px, py, pz = float(px), float(py), float(pz)
        if math.isnan(px): px = 0
        if math.isnan(py): py = 0
        if math.isnan(pz): pz = 0

        if mode == 'raw':
            verts.append((px * SCALE, py * SCALE, pz * SCALE))
            continue

        bi = [pac[o + 12 + b] for b in range(4)]
        bw = [pac[o + 20 + b] for b in range(4)]
        total_w = sum(bw)
        if total_w == 0:
            verts.append((px * SCALE, py * SCALE, pz * SCALE))
            continue

        pos = np.array([px, py, pz, 1.0])
        result = np.zeros(3)
        for b in range(4):
            if bw[b] == 0:
                continue
            pi = bi[b]
            if pi < len(palette) and palette[pi] >= 0:
                mat = bone_world[palette[pi]]
                if mode == 'row':
                    t = pos @ mat
                else:
                    t = mat @ pos
                result += t[:3] * (bw[b] / total_w)
            else:
                result += np.array([px, py, pz]) * (bw[b] / total_w)
        verts.append((float(result[0]) * SCALE, float(result[1]) * SCALE, float(result[2]) * SCALE))

    # Read head indices
    head_indices = list(struct.unpack_from(f'<{HEAD_ICOUNT}H', pac, head_idx_offset))

    out = f'output/head_{mode}.obj'
    with open(out, 'w') as f:
        f.write(f'# Dragon Head - {mode}\n')
        for x, y, z in verts:
            f.write(f'v {x:.6f} {y:.6f} {z:.6f}\n')
        for tri in range(HEAD_ICOUNT // 3):
            i0 = head_indices[tri * 3] + 1
            i1 = head_indices[tri * 3 + 1] + 1
            i2 = head_indices[tri * 3 + 2] + 1
            f.write(f'f {i0} {i1} {i2}\n')

    xs = [v[0] for v in verts]
    ys = [v[1] for v in verts]
    zs = [v[2] for v in verts]
    print(f'  {mode:4s}: X[{min(xs):.1f},{max(xs):.1f}] Y[{min(ys):.1f},{max(ys):.1f}] Z[{min(zs):.1f},{max(zs):.1f}] -> {out}')
