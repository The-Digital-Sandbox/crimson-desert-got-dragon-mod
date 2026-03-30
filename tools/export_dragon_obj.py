#!/usr/bin/env python3
"""Export the raw stored PAC vertex positions as OBJ.

This is a byte-faithful dump of the position stream. It is useful for debugging
the storage format, but it is not a reconstructed bind pose.
"""

from __future__ import annotations

import argparse
import math
import struct
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "output"
PAC_PATH = OUTPUT / "dragon.pac"
OBJ_PATH = OUTPUT / "dragon_bindpose.obj"

SECTION_OFFSET_OFFSETS = (0x14, 0x1C, 0x24, 0x2C, 0x34)
VERTEX_COUNT = 27376
VERTEX_STRIDE = 40

SUBMESH_NAMES = ["Eyeright", "Eyeleft", "Body_02", "back", "Body", "Leg", "Wing", "Head"]
SUBMESH_VERTEX_COUNTS = [225, 225, 2013, 3307, 2736, 4624, 6724, 10258]
SUBMESH_INDEX_COUNTS = [1248, 1248, 7992, 17007, 13380, 22464, 34902, 51180]
UNIQUE_VERTEX_ORDER = [0, 1, 2, 3, 5, 6, 7]


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


def compute_offsets(pac: bytes) -> tuple[int, int]:
    section_offsets = [struct.unpack_from("<Q", pac, off)[0] for off in SECTION_OFFSET_OFFSETS]
    vertex_start = section_offsets[1] - VERTEX_COUNT * VERTEX_STRIDE
    total_index_count = sum(SUBMESH_INDEX_COUNTS)
    index_start = len(pac) - total_index_count * 2
    return vertex_start, index_start


def compute_submesh_vertex_starts() -> dict[int, int]:
    starts = {}
    running = 0
    for submesh_index in UNIQUE_VERTEX_ORDER:
        starts[submesh_index] = running
        running += SUBMESH_VERTEX_COUNTS[submesh_index]
    starts[4] = starts[3]
    return starts


def main() -> int:
    parser = argparse.ArgumentParser(description="Export the raw PAC position stream as OBJ.")
    parser.add_argument("--scale", type=float, default=4.0, help="uniform scale to apply to positions")
    parser.add_argument("--out", type=Path, default=OBJ_PATH, help="output OBJ path")
    args = parser.parse_args()

    pac = PAC_PATH.read_bytes()
    vertex_start, index_start = compute_offsets(pac)
    submesh_vertex_starts = compute_submesh_vertex_starts()

    positions = []
    normals = []
    uvs = []

    for vertex_index in range(VERTEX_COUNT):
        off = vertex_start + vertex_index * VERTEX_STRIDE
        x, y, z = struct.unpack_from("<3e", pac, off)
        x = float(x) * args.scale
        y = float(y) * args.scale
        z = float(z) * args.scale
        positions.append((x, y, z))

        packed_normal = struct.unpack_from("<I", pac, off + 8)[0]
        normals.append(decode_normal_r10g10b10a2(packed_normal))

        u_raw, v_raw = struct.unpack_from("<2H", pac, off + 32)
        uvs.append((u_raw / 65535.0, 1.0 - v_raw / 65535.0))

    total_index_count = sum(SUBMESH_INDEX_COUNTS)
    all_indices = list(struct.unpack_from(f"<{total_index_count}H", pac, index_start))

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write("# Crimson Desert dragon raw position-stream export\n")
        handle.write(f"# source={PAC_PATH.name}\n")
        handle.write(f"# vertex_start=0x{vertex_start:X} index_start=0x{index_start:X}\n")
        handle.write(f"# scale={args.scale}\n\n")

        for x, y, z in positions:
            handle.write(f"v {x:.9f} {y:.9f} {z:.9f}\n")

        for nx, ny, nz in normals:
            handle.write(f"vn {nx:.6f} {ny:.6f} {nz:.6f}\n")

        for u, v in uvs:
            handle.write(f"vt {u:.9f} {v:.9f}\n")

        handle.write("\n")

        index_pos = 0
        for submesh_index, submesh_name in enumerate(SUBMESH_NAMES):
            index_count = SUBMESH_INDEX_COUNTS[submesh_index]
            vertex_base = submesh_vertex_starts[submesh_index]
            handle.write(f"g {submesh_name}\n")

            for tri in range(index_count // 3):
                i0 = all_indices[index_pos + tri * 3 + 0] + vertex_base + 1
                i1 = all_indices[index_pos + tri * 3 + 1] + vertex_base + 1
                i2 = all_indices[index_pos + tri * 3 + 2] + vertex_base + 1
                handle.write(f"f {i0}/{i0}/{i0} {i1}/{i1}/{i1} {i2}/{i2}/{i2}\n")

            handle.write("\n")
            index_pos += index_count

    print(f"Wrote {args.out}")
    print("Note: this OBJ contains raw stored positions only, not a reconstructed bind pose.")
    print(f"Vertex start: 0x{vertex_start:X}")
    print(f"Index start:  0x{index_start:X}")
    print(f"Vertices:     {VERTEX_COUNT}")
    print(f"Triangles:    {sum(SUBMESH_INDEX_COUNTS) // 3}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
