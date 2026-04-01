#!/usr/bin/env python3
"""Trace the Crimson Desert dragon head draw from PAC storage to PIX capture.

This is a focused diagnostic for the head draw (`GpuId7158`).

It does three things:
1. Confirms the *stored* PAC head vertex window using the real 27,376-vertex layout.
2. Dequantizes that stored head window into object-space positions using the head bbox.
3. Exports a head-only OBJ/CSV side-by-side with the PIX capture so we can inspect
   the pre-skin payload without Blender or writeback noise.

Important limitations:
- This does NOT solve skinning yet.
- This does NOT decode the optional packed per-vertex offset path yet.
- This does NOT assume PAC UV decode is known.
"""

from __future__ import annotations

import csv
import math
import struct
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "output"
GPU_ANALYSIS = ROOT / "gpu-analysis"

PAC_PATH = OUTPUT / "dragon.pac"
PIX_CSV_PATH = GPU_ANALYSIS / "2026_3_30__9_24_50_GpuId7158_VS_BufferData_exp0.csv"
OUT_DIR = OUTPUT / "head_trace"
OUT_OBJ = OUT_DIR / "head_dequantized.obj"
OUT_CSV = OUT_DIR / "head_trace_compare.csv"
OUT_SUMMARY = OUT_DIR / "head_trace_summary.txt"

SECTION_OFFSET_OFFSETS = (0x14, 0x1C, 0x24, 0x2C, 0x34)
VERTEX_COUNT = 27376
VERTEX_STRIDE = 40

SUBMESH_NAMES = ["Eyeright", "Eyeleft", "Body_02", "back", "Body", "Leg", "Wing", "Head"]
SUBMESH_VERTEX_COUNTS = [225, 225, 2013, 3307, 2736, 4624, 6724, 10258]
SUBMESH_INDEX_COUNTS = [1248, 1248, 7992, 17007, 13380, 22464, 34902, 51180]
UNIQUE_VERTEX_ORDER = [0, 1, 2, 3, 5, 6, 7]
HEAD_SUBMESH_INDEX = 7


@dataclass(frozen=True)
class Bbox:
    min_xyz: tuple[float, float, float]
    dim_xyz: tuple[float, float, float]


@dataclass(frozen=True)
class PacHeadVertex:
    draw_vertex_id: int
    stored_vertex_index: int
    raw_u16: tuple[int, int, int]
    raw_w: int
    local_pos: tuple[float, float, float]
    raw_hex_0_7: str
    raw_hex_8_39: str


def load_pac() -> tuple[bytes, int, int]:
    pac = PAC_PATH.read_bytes()
    section_offsets = [struct.unpack_from("<Q", pac, off)[0] for off in SECTION_OFFSET_OFFSETS]
    vertex_start = section_offsets[1] - VERTEX_COUNT * VERTEX_STRIDE
    total_index_count = sum(SUBMESH_INDEX_COUNTS)
    index_start = len(pac) - total_index_count * 2
    return pac, vertex_start, index_start


def parse_submesh_bboxes(pac: bytes) -> list[Bbox]:
    bboxes: list[Bbox] = []
    off = 0x0077

    for _ in range(8):
        name_len = pac[off]
        off += 1 + name_len

        mat_len = pac[off]
        off += 1 + mat_len

        off += 3
        floats = struct.unpack_from("<8f", pac, off)
        off += 32

        bboxes.append(Bbox(min_xyz=floats[2:5], dim_xyz=floats[5:8]))

        next_cd = pac.find(b"CD_M0004", off)
        if next_cd > 0 and next_cd < 0x0441:
            off = next_cd - 1
        else:
            off = 0x0441

    return bboxes


def compute_stored_submesh_starts() -> dict[int, int]:
    starts: dict[int, int] = {}
    running = 0
    for submesh_index in UNIQUE_VERTEX_ORDER:
        starts[submesh_index] = running
        running += SUBMESH_VERTEX_COUNTS[submesh_index]

    # Body shares the back vertex buffer.
    starts[4] = starts[3]
    return starts


def dequantize_pos(u16_x: int, u16_y: int, u16_z: int, bbox: Bbox) -> tuple[float, float, float]:
    x = bbox.min_xyz[0] + (u16_x / 32767.0) * bbox.dim_xyz[0]
    y = bbox.min_xyz[1] + (u16_y / 32767.0) * bbox.dim_xyz[1]
    z = bbox.min_xyz[2] + (u16_z / 32767.0) * bbox.dim_xyz[2]
    return (x, y, z)


def decode_head_vertices(pac: bytes, vertex_start: int, head_base: int, head_bbox: Bbox) -> list[PacHeadVertex]:
    head_count = SUBMESH_VERTEX_COUNTS[HEAD_SUBMESH_INDEX]
    result: list[PacHeadVertex] = []

    for draw_vertex_id in range(head_count):
        stored_vertex_index = head_base + draw_vertex_id
        off = vertex_start + stored_vertex_index * VERTEX_STRIDE
        raw = pac[off : off + VERTEX_STRIDE]
        u16_x, u16_y, u16_z, u16_w = struct.unpack_from("<4H", raw, 0)
        local_pos = dequantize_pos(u16_x, u16_y, u16_z, head_bbox)
        result.append(
            PacHeadVertex(
                draw_vertex_id=draw_vertex_id,
                stored_vertex_index=stored_vertex_index,
                raw_u16=(u16_x, u16_y, u16_z),
                raw_w=u16_w,
                local_pos=local_pos,
                raw_hex_0_7=raw[:8].hex(),
                raw_hex_8_39=raw[8:].hex(),
            )
        )

    return result


def read_head_indices(pac: bytes, index_start: int) -> list[int]:
    total_index_count = sum(SUBMESH_INDEX_COUNTS)
    all_indices = struct.unpack_from(f"<{total_index_count}H", pac, index_start)
    head_offset = sum(SUBMESH_INDEX_COUNTS[:HEAD_SUBMESH_INDEX])
    head_count = SUBMESH_INDEX_COUNTS[HEAD_SUBMESH_INDEX]
    return list(all_indices[head_offset : head_offset + head_count])


def read_pix_head_vertices() -> list[dict]:
    rows_by_vid: dict[int, dict] = {}
    with PIX_CSV_PATH.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            vid = int(row["Vertex_ID"])
            if vid in rows_by_vid:
                continue
            rows_by_vid[vid] = {
                "draw_vertex_id": vid,
                "primitive_id": int(row["Primitive_ID"]),
                "instance_id": int(row["Instance_ID"]),
                "sv_position": (
                    float(row["SV_POSITION_C0"]),
                    float(row["SV_POSITION_C1"]),
                    float(row["SV_POSITION_C2"]),
                    float(row["SV_POSITION_C3"]),
                ),
                "uv0": (
                    float(row["TEXCOORD_C0"]),
                    float(row["TEXCOORD_C1"]),
                ),
                "world_pos": (
                    float(row["TEXCOORD1_C0"]),
                    float(row["TEXCOORD1_C1"]),
                    float(row["TEXCOORD1_C2"]),
                ),
                "normal": (
                    float(row["TEXCOORD2_C0"]),
                    float(row["TEXCOORD2_C1"]),
                    float(row["TEXCOORD2_C2"]),
                ),
                "tangent": (
                    float(row["TEXCOORD3_C0"]),
                    float(row["TEXCOORD3_C1"]),
                    float(row["TEXCOORD3_C2"]),
                    float(row["TEXCOORD3_C3"]),
                ),
                "texcoord4": int(row["TEXCOORD4"]),
            }

    return [rows_by_vid[i] for i in sorted(rows_by_vid)]


def compute_bounds(points: list[tuple[float, float, float]]) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    zs = [p[2] for p in points]
    return (min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs))


def compute_spans(bounds: tuple[tuple[float, float, float], tuple[float, float, float]]) -> tuple[float, float, float]:
    lo, hi = bounds
    return (hi[0] - lo[0], hi[1] - lo[1], hi[2] - lo[2])


def write_head_obj(vertices: list[PacHeadVertex], indices: list[int]) -> None:
    with OUT_OBJ.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write("# Crimson Desert dragon head - PAC dequantized object-space positions\n")
        handle.write(f"# source={PAC_PATH.name}\n")
        handle.write(f"# pix_source={PIX_CSV_PATH.name}\n")
        handle.write("# Note: pre-skin, pre-packed-offset diagnostic export\n\n")

        for vertex in vertices:
            x, y, z = vertex.local_pos
            handle.write(f"v {x:.9f} {y:.9f} {z:.9f}\n")

        handle.write("\ng Head\n")
        for tri in range(0, len(indices), 3):
            i0 = indices[tri + 0] + 1
            i1 = indices[tri + 1] + 1
            i2 = indices[tri + 2] + 1
            handle.write(f"f {i0} {i1} {i2}\n")


def write_compare_csv(vertices: list[PacHeadVertex], pix_rows: list[dict]) -> None:
    by_vid = {vertex.draw_vertex_id: vertex for vertex in vertices}

    with OUT_CSV.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "draw_vertex_id",
                "stored_vertex_index",
                "raw_u16_x",
                "raw_u16_y",
                "raw_u16_z",
                "raw_u16_w",
                "local_x",
                "local_y",
                "local_z",
                "pix_world_x",
                "pix_world_y",
                "pix_world_z",
                "pix_uv_u",
                "pix_uv_v",
                "pix_normal_x",
                "pix_normal_y",
                "pix_normal_z",
                "pix_tangent_x",
                "pix_tangent_y",
                "pix_tangent_z",
                "pix_tangent_w",
                "pix_texcoord4",
                "raw_hex_0_7",
                "raw_hex_8_39",
            ]
        )

        for pix in pix_rows:
            vertex = by_vid[pix["draw_vertex_id"]]
            writer.writerow(
                [
                    pix["draw_vertex_id"],
                    vertex.stored_vertex_index,
                    vertex.raw_u16[0],
                    vertex.raw_u16[1],
                    vertex.raw_u16[2],
                    vertex.raw_w,
                    f"{vertex.local_pos[0]:.9f}",
                    f"{vertex.local_pos[1]:.9f}",
                    f"{vertex.local_pos[2]:.9f}",
                    f"{pix['world_pos'][0]:.9f}",
                    f"{pix['world_pos'][1]:.9f}",
                    f"{pix['world_pos'][2]:.9f}",
                    f"{pix['uv0'][0]:.9f}",
                    f"{pix['uv0'][1]:.9f}",
                    f"{pix['normal'][0]:.9f}",
                    f"{pix['normal'][1]:.9f}",
                    f"{pix['normal'][2]:.9f}",
                    f"{pix['tangent'][0]:.9f}",
                    f"{pix['tangent'][1]:.9f}",
                    f"{pix['tangent'][2]:.9f}",
                    f"{pix['tangent'][3]:.9f}",
                    pix["texcoord4"],
                    vertex.raw_hex_0_7,
                    vertex.raw_hex_8_39,
                ]
            )


def write_summary(
    vertex_start: int,
    index_start: int,
    head_base: int,
    head_bbox: Bbox,
    vertices: list[PacHeadVertex],
    indices: list[int],
    pix_rows: list[dict],
) -> str:
    local_bounds = compute_bounds([vertex.local_pos for vertex in vertices])
    world_bounds = compute_bounds([row["world_pos"] for row in pix_rows])
    local_spans = compute_spans(local_bounds)
    world_spans = compute_spans(world_bounds)

    lines = [
        "Crimson Desert Head Draw Trace",
        "==============================",
        "",
        f"PAC:        {PAC_PATH}",
        f"PIX CSV:    {PIX_CSV_PATH}",
        f"vertexStart=0x{vertex_start:X}",
        f"indexStart=0x{index_start:X}",
        f"storedVertCount={VERTEX_COUNT}",
        "",
        "Stored layout:",
        f"  total stored verts = {VERTEX_COUNT}",
        "  body shares back buffer = True",
        f"  head stored base = {head_base}",
        f"  head stored end  = {head_base + len(vertices) - 1}",
        "",
        "Head bbox from PAC descriptor:",
        f"  min = ({head_bbox.min_xyz[0]:.9f}, {head_bbox.min_xyz[1]:.9f}, {head_bbox.min_xyz[2]:.9f})",
        f"  dim = ({head_bbox.dim_xyz[0]:.9f}, {head_bbox.dim_xyz[1]:.9f}, {head_bbox.dim_xyz[2]:.9f})",
        "",
        "Head draw counts:",
        f"  PIX unique vertices = {len(pix_rows)}",
        f"  PAC stored vertices = {len(vertices)}",
        f"  PAC head indices    = {len(indices)} ({len(indices) // 3} triangles)",
        "",
        "Bounds:",
        f"  local min = ({local_bounds[0][0]:.6f}, {local_bounds[0][1]:.6f}, {local_bounds[0][2]:.6f})",
        f"  local max = ({local_bounds[1][0]:.6f}, {local_bounds[1][1]:.6f}, {local_bounds[1][2]:.6f})",
        f"  local span= ({local_spans[0]:.6f}, {local_spans[1]:.6f}, {local_spans[2]:.6f})",
        f"  world min = ({world_bounds[0][0]:.6f}, {world_bounds[0][1]:.6f}, {world_bounds[0][2]:.6f})",
        f"  world max = ({world_bounds[1][0]:.6f}, {world_bounds[1][1]:.6f}, {world_bounds[1][2]:.6f})",
        f"  world span= ({world_spans[0]:.6f}, {world_spans[1]:.6f}, {world_spans[2]:.6f})",
        "",
        "Notes:",
        "  - This export is pre-skin and pre-packed-offset only.",
        "  - PAC UV decode is intentionally omitted here because the non-position layout is not fully solved yet.",
        "  - If this object-space head is coherent but does not match PIX world space, the remaining gap is in the shader-side offset + skinning path.",
        "",
        "Sample rows:",
    ]

    for sample_vid in [0, 1, 2, 100, 1000, 5000, 9000]:
        vertex = vertices[sample_vid]
        pix = pix_rows[sample_vid]
        lines.append(
            "  "
            f"vid={sample_vid:5d} stored={vertex.stored_vertex_index:5d} "
            f"u16={vertex.raw_u16} "
            f"local=({vertex.local_pos[0]: .6f}, {vertex.local_pos[1]: .6f}, {vertex.local_pos[2]: .6f}) "
            f"pixWorld=({pix['world_pos'][0]: .6f}, {pix['world_pos'][1]: .6f}, {pix['world_pos'][2]: .6f})"
        )

    summary = "\n".join(lines) + "\n"
    OUT_SUMMARY.write_text(summary, encoding="utf-8")
    return summary


def main() -> int:
    if not PAC_PATH.exists():
        raise SystemExit(f"PAC not found: {PAC_PATH}")
    if not PIX_CSV_PATH.exists():
        raise SystemExit(f"PIX CSV not found: {PIX_CSV_PATH}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    pac, vertex_start, index_start = load_pac()
    bboxes = parse_submesh_bboxes(pac)
    starts = compute_stored_submesh_starts()

    head_base = starts[HEAD_SUBMESH_INDEX]
    head_bbox = bboxes[HEAD_SUBMESH_INDEX]
    vertices = decode_head_vertices(pac, vertex_start, head_base, head_bbox)
    indices = read_head_indices(pac, index_start)
    pix_rows = read_pix_head_vertices()

    if len(vertices) != len(pix_rows):
        raise SystemExit(
            f"Head count mismatch: PAC={len(vertices)} PIX={len(pix_rows)}"
        )

    write_head_obj(vertices, indices)
    write_compare_csv(vertices, pix_rows)
    summary = write_summary(vertex_start, index_start, head_base, head_bbox, vertices, indices, pix_rows)

    print(summary, end="")
    print(f"Wrote OBJ:      {OUT_OBJ}")
    print(f"Wrote CSV:      {OUT_CSV}")
    print(f"Wrote summary:  {OUT_SUMMARY}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
