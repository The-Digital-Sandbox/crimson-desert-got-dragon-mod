#!/usr/bin/env python3
"""Export head vertices as point cloud only - no faces, no transforms."""
import struct, math, os
os.environ['PYTHONIOENCODING'] = 'utf-8'

with open('output/dragon.pac', 'rb') as f:
    pac = f.read()

VBUF = 0x7BFA
STRIDE = 40
HEAD_VSTART = 17118
HEAD_VCOUNT = 10258

with open('output/head_points.obj', 'w') as f:
    f.write('# Dragon Head - point cloud only\n')
    for i in range(HEAD_VCOUNT):
        o = VBUF + (HEAD_VSTART + i) * STRIDE
        x, y, z = struct.unpack_from('<3e', pac, o)
        x, y, z = float(x), float(y), float(z)
        if math.isnan(x): x = 0
        if math.isnan(y): y = 0
        if math.isnan(z): z = 0
        f.write(f'v {x} {y} {z}\n')

print('Wrote output/head_points.obj')
