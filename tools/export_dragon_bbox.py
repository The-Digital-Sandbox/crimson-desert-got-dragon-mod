#!/usr/bin/env python3
"""Export CD dragon PAC mesh using uint16 bbox dequantization.

Position encoding: 3 x uint16 quantized, dequantized via global bounding box.
Formula: pos[axis] = bbox_min[axis] + (uint16 / 65535) * (bbox_max[axis] - bbox_min[axis])

Global bbox at offset 0x07CF in PAC (3 x float32 min, 3 x float32 max).
Based on CDPamExtractor (PhorgeForge/Lathiel) proving this is the standard CD/PAM format.
"""

from __future__ import annotations

import math
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "output"
PAC_PATH = OUTPUT / "dragon.pac"
OBJ_PATH = OUTPUT / "dragon_bbox.obj"

SECTION_OFFSET_OFFSETS = (0x14, 0x1C, 0x24, 0x2C, 0x34)
VERTEX_COUNT = 27376
VERTEX_STRIDE = 40
GLOBAL_BBOX_OFFSET = 0x07CF

SUBMESH_NAMES = ["Eyeright", "Eyeleft", "Body_02", "back", "Body", "Leg", "Wing", "Head"]
SUBMESH_VERTEX_COUNTS = [225, 225, 2013, 3307, 2736, 4624, 6724, 10258]
SUBMESH_INDEX_COUNTS = [1248, 1248, 7992, 17007, 13380, 22464, 34902, 51180]
UNIQUE_VERTEX_ORDER = [0, 1, 2, 3, 5, 6, 7]  # SM4 (Body) shares SM3 (back) buffer


def dequantize(raw: int, bmin: float, bmax: float) -> float:
    return bmin + (raw / 65535.0) * (bmax - bmin)


def decode_normal_r10g10b10a2(packed: int) -> tuple[float, float, float]:
    x = (packed & 0x3FF) / 1023.0 * 2.0 - 1.0
    y = ((packed >> 10) & 0x3FF) / 1023.0 * 2.0 - 1.0
    z = ((packed >> 20) & 0x3FF) / 1023.0 * 2.0 - 1.0
    length = math.sqrt(x * x + y * y + z * z)
    if length > 1e-8:
        x /= length
        y /= length
        z /= length
    return x, y, z


def main() -> int:
    pac = PAC_PATH.read_bytes()

    # Read global bounding box
    bbox_min = struct.unpack_from('<3f', pac, GLOBAL_BBOX_OFFSET)
    bbox_max = struct.unpack_from('<3f', pac, GLOBAL_BBOX_OFFSET + 12)

    # Compute vertex/index buffer starts
    section_offsets = [struct.unpack_from("<Q", pac, off)[0] for off in SECTION_OFFSET_OFFSETS]
    vertex_start = section_offsets[1] - VERTEX_COUNT * VERTEX_STRIDE
    total_index_count = sum(SUBMESH_INDEX_COUNTS)
    index_start = len(pac) - total_index_count * 2

    # Build submesh vertex start offsets
    vertex_starts: dict[int, int] = {}
    running = 0
    for si in UNIQUE_VERTEX_ORDER:
        vertex_starts[si] = running
        running += SUBMESH_VERTEX_COUNTS[si]
    vertex_starts[4] = vertex_starts[3]  # SM4 (Body) shares SM3 (back) buffer

    # Decode all vertices
    positions: list[tuple[float, float, float]] = []
    normals: list[tuple[float, float, float]] = []
    uvs: list[tuple[float, float]] = []

    for vi in range(VERTEX_COUNT):
        off = vertex_start + vi * VERTEX_STRIDE
        xu, yu, zu = struct.unpack_from('<3H', pac, off)

        x = dequantize(xu, bbox_min[0], bbox_max[0])
        y = dequantize(yu, bbox_min[1], bbox_max[1])
        z = dequantize(zu, bbox_min[2], bbox_max[2])
        positions.append((x, y, z))

        packed_normal = struct.unpack_from("<I", pac, off + 8)[0]
        normals.append(decode_normal_r10g10b10a2(packed_normal))

        u_raw, v_raw = struct.unpack_from("<2H", pac, off + 32)
        uvs.append((u_raw / 65535.0, 1.0 - v_raw / 65535.0))

    # Read index buffer
    all_indices = list(struct.unpack_from(f"<{total_index_count}H", pac, index_start))

    # Write OBJ
    with OBJ_PATH.open("w", encoding="utf-8", newline="\n") as f:
        f.write("# Crimson Desert dragon — uint16 bbox dequantized export\n")
        f.write(f"# source: {PAC_PATH.name}\n")
        f.write(f"# bbox_min: ({bbox_min[0]:.4f}, {bbox_min[1]:.4f}, {bbox_min[2]:.4f})\n")
        f.write(f"# bbox_max: ({bbox_max[0]:.4f}, {bbox_max[1]:.4f}, {bbox_max[2]:.4f})\n")
        f.write(f"# vertices: {VERTEX_COUNT}, triangles: {total_index_count // 3}\n\n")

        for x, y, z in positions:
            f.write(f"v {x:.9f} {y:.9f} {z:.9f}\n")

        for nx, ny, nz in normals:
            f.write(f"vn {nx:.6f} {ny:.6f} {nz:.6f}\n")

        for u, v in uvs:
            f.write(f"vt {u:.9f} {v:.9f}\n")

        f.write("\n")

        index_pos = 0
        for si, name in enumerate(SUBMESH_NAMES):
            idx_count = SUBMESH_INDEX_COUNTS[si]
            vbase = vertex_starts[si]
            f.write(f"g {name}\n")

            for tri in range(idx_count // 3):
                i0 = all_indices[index_pos + tri * 3 + 0] + vbase + 1
                i1 = all_indices[index_pos + tri * 3 + 1] + vbase + 1
                i2 = all_indices[index_pos + tri * 3 + 2] + vbase + 1
                f.write(f"f {i0}/{i0}/{i0} {i1}/{i1}/{i1} {i2}/{i2}/{i2}\n")

            f.write("\n")
            index_pos += idx_count

    print(f"Wrote {OBJ_PATH}")
    print(f"Vertices: {VERTEX_COUNT}, Triangles: {total_index_count // 3}")
    print(f"Global bbox: min=({bbox_min[0]:.4f}, {bbox_min[1]:.4f}, {bbox_min[2]:.4f})")
    print(f"             max=({bbox_max[0]:.4f}, {bbox_max[1]:.4f}, {bbox_max[2]:.4f})")
    print(f"             size=({bbox_max[0]-bbox_min[0]:.3f}, {bbox_max[1]-bbox_min[1]:.3f}, {bbox_max[2]-bbox_min[2]:.3f})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
