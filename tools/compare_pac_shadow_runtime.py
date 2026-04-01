#!/usr/bin/env python3
"""Compare original PAC storage against the proven runtime shadow dragon path.

This is the PAC bridge checkpoint script.

It verifies, for the six proven shadow-family dragon submeshes:

- PAC submesh bbox == runtime parameter bbox
- PAC local triangle indices == live runtime shadow indices
- same local vertex order can be compared directly between PAC and runtime
- PAC packets are not byte-identical to runtime shadow packets

It then dumps a per-submesh CSV pairing the same local vertex index across
PAC and runtime shadow so later reverse-engineering can work from one stable,
authoritative artifact instead of shell scraps.
"""

from __future__ import annotations

import csv
import json
import math
import struct
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import pac_codec

OUTPUT = ROOT / "output"
PIX_RESOURCES = OUTPUT / "pix_resources"
OUT_DIR = OUTPUT / "pac_shadow_compare"

PAC_PATH = OUTPUT / "dragon.pac"
RESOURCE_242 = PIX_RESOURCES / "resource_242.bin"
RESOURCE_7879 = PIX_RESOURCES / "resource_7879.bin"
RESOURCE_7968 = PIX_RESOURCES / "resource_7968.bin"
RESOURCE_2074 = PIX_RESOURCES / "resource_2074.bin"
RESOURCE_16288 = PIX_RESOURCES / "resource_16288.bin"

STRIDE_242 = 156
STRIDE_7879 = 28
STRIDE_7968 = 40
VERTEX_STRIDE = 40
RUNTIME_VIEW_FIRST_ELEMENT = 46222
SHADOW_IB_HEAP_OFFSET = 7_390_720

SHADOW_SUBMESHES = [
    ("Body_02", 145),
    ("back", 146),
    ("Body", 147),
    ("Leg", 148),
    ("Wing", 149),
    ("Head", 150),
]

FIELDS = {
    "pos6": (0, 6),
    "w2": (6, 8),
    "normal4": (8, 12),
    "bone_idx4": (12, 16),
    "extra0_4": (16, 20),
    "bone_wt4": (20, 24),
    "extra1_4": (24, 28),
    "vcolor4": (28, 32),
    "uv0_4": (32, 36),
    "uv1_4": (36, 40),
}


@dataclass(frozen=True)
class IndirectRecord:
    command_index: int
    constant0: int
    index_count: int
    start_index: int
    base_vertex: int


@dataclass(frozen=True)
class DeltaStats:
    minimum: float
    average: float
    maximum: float


@dataclass(frozen=True)
class FieldMatchStats:
    exact_packet_matches: int
    exact_position_packet_matches: int
    field_exact_matches: dict[str, int]
    field_exact_ratios: dict[str, float]


@dataclass(frozen=True)
class SubmeshSummary:
    name: str
    command_index: int
    parameter_index: int
    pac_base_vertex: int
    runtime_base_vertex: int
    vertex_count: int
    triangle_count: int
    bbox_match: bool
    index_match: bool
    delta: DeltaStats
    packet_matches: FieldMatchStats
    csv_path: str


def load_indirect_record(command_index: int) -> IndirectRecord:
    data = RESOURCE_7968.read_bytes()
    offset = command_index * STRIDE_7968
    constant0 = struct.unpack_from("<I", data, offset + 16)[0]
    index_count, _instance_count, start_index, base_vertex, _start_instance = struct.unpack_from(
        "<IIiII", data, offset + 20
    )
    return IndirectRecord(
        command_index=command_index,
        constant0=constant0,
        index_count=index_count,
        start_index=start_index,
        base_vertex=base_vertex,
    )


def read_runtime_bbox(parameter_index: int) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    data = RESOURCE_242.read_bytes()
    offset = parameter_index * STRIDE_242
    bbox_min = struct.unpack_from("<3f", data, offset + 0)
    bbox_dim = struct.unpack_from("<3f", data, offset + 16)
    return bbox_min, bbox_dim


def load_draw_record(record_index: int) -> tuple[int, int, int, int, int, int, int]:
    data = RESOURCE_7879.read_bytes()
    return struct.unpack_from("<7I", data, record_index * STRIDE_7879)


def dequantize_runtime_pos(
    raw40: bytes,
    bbox_min: tuple[float, float, float],
    bbox_dim: tuple[float, float, float],
) -> tuple[float, float, float]:
    packed_xy, packed_zw = struct.unpack_from("<II", raw40, 0)
    u16_x = packed_xy & 0xFFFF
    u16_y = (packed_xy >> 16) & 0xFFFF
    u16_z = packed_zw & 0xFFFF
    return (
        bbox_min[0] + (u16_x / 32767.0) * bbox_dim[0],
        bbox_min[1] + (u16_y / 32767.0) * bbox_dim[1],
        bbox_min[2] + (u16_z / 32767.0) * bbox_dim[2],
    )


def float3_close(a: tuple[float, float, float], b: tuple[float, float, float], tol: float = 1e-6) -> bool:
    return all(abs(x - y) <= tol for x, y in zip(a, b))


def compare_indices(live_record: IndirectRecord, pac_indices: list[int], index_bytes: bytes) -> bool:
    runtime_indices = struct.unpack_from(
        f"<{live_record.index_count}H",
        index_bytes,
        SHADOW_IB_HEAP_OFFSET + live_record.start_index * 2,
    )
    return list(runtime_indices) == pac_indices


def length3(delta: tuple[float, float, float]) -> float:
    return math.sqrt(delta[0] * delta[0] + delta[1] * delta[1] + delta[2] * delta[2])


def compare_submesh(
    name: str,
    command_index: int,
    bboxes_by_name: dict[str, pac_codec.SubmeshBbox],
    pac_indices_by_name: dict[str, list[int]],
    runtime_bytes: bytes,
    index_bytes: bytes,
    pac_bytes: bytes,
) -> SubmeshSummary:
    live_record = load_indirect_record(command_index)
    draw_record = load_draw_record(live_record.constant0)
    parameter_index = draw_record[0]
    runtime_bbox_min, runtime_bbox_dim = read_runtime_bbox(parameter_index)
    pac_bbox = bboxes_by_name[name]
    pac_base = pac_codec.SUBMESH_BASES[pac_codec.SUBMESH_NAMES.index(name)]
    vertex_count = pac_codec.SUBMESH_VERTEX_COUNTS[pac_codec.SUBMESH_NAMES.index(name)]

    bbox_match = float3_close(pac_bbox.min_xyz, runtime_bbox_min) and float3_close(pac_bbox.dim_xyz, runtime_bbox_dim)
    index_match = compare_indices(live_record, pac_indices_by_name[name], index_bytes)

    csv_path = OUT_DIR / f"{name.lower()}_pairs.csv"
    deltas: list[float] = []
    exact_packet_matches = 0
    exact_position_packet_matches = 0
    field_exact_matches = {field: 0 for field in FIELDS}

    with csv_path.open("w", encoding="ascii", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "local_index",
                "pac_vertex_index",
                "runtime_vertex_index",
                "pac_x",
                "pac_y",
                "pac_z",
                "runtime_x",
                "runtime_y",
                "runtime_z",
                "delta_len",
                "pac_raw40_hex",
                "runtime_raw40_hex",
            ]
        )

        for local_index in range(vertex_count):
            pac_vertex_index = pac_base + local_index
            runtime_vertex_index = RUNTIME_VIEW_FIRST_ELEMENT + live_record.base_vertex + local_index

            pac_raw_offset = pac_codec.VB_START + pac_vertex_index * VERTEX_STRIDE
            runtime_raw_offset = runtime_vertex_index * VERTEX_STRIDE

            pac_raw40 = pac_bytes[pac_raw_offset : pac_raw_offset + VERTEX_STRIDE]
            runtime_raw40 = runtime_bytes[runtime_raw_offset : runtime_raw_offset + VERTEX_STRIDE]

            if pac_raw40 == runtime_raw40:
                exact_packet_matches += 1
            if pac_raw40[:8] == runtime_raw40[:8]:
                exact_position_packet_matches += 1
            for field_name, (start, end) in FIELDS.items():
                if pac_raw40[start:end] == runtime_raw40[start:end]:
                    field_exact_matches[field_name] += 1

            pac_pos = pac_codec.decode_vertex(pac_bytes, pac_vertex_index, pac_bbox).pos
            runtime_pos = dequantize_runtime_pos(runtime_raw40, runtime_bbox_min, runtime_bbox_dim)
            delta_len = length3(
                (
                    runtime_pos[0] - pac_pos[0],
                    runtime_pos[1] - pac_pos[1],
                    runtime_pos[2] - pac_pos[2],
                )
            )
            deltas.append(delta_len)

            writer.writerow(
                [
                    local_index,
                    pac_vertex_index,
                    runtime_vertex_index,
                    f"{pac_pos[0]:.9f}",
                    f"{pac_pos[1]:.9f}",
                    f"{pac_pos[2]:.9f}",
                    f"{runtime_pos[0]:.9f}",
                    f"{runtime_pos[1]:.9f}",
                    f"{runtime_pos[2]:.9f}",
                    f"{delta_len:.9f}",
                    pac_raw40.hex(),
                    runtime_raw40.hex(),
                ]
            )

    field_exact_ratios = {field: field_exact_matches[field] / vertex_count for field in FIELDS}
    delta = DeltaStats(minimum=min(deltas), average=sum(deltas) / len(deltas), maximum=max(deltas))
    packet_stats = FieldMatchStats(
        exact_packet_matches=exact_packet_matches,
        exact_position_packet_matches=exact_position_packet_matches,
        field_exact_matches=field_exact_matches,
        field_exact_ratios=field_exact_ratios,
    )
    return SubmeshSummary(
        name=name,
        command_index=command_index,
        parameter_index=parameter_index,
        pac_base_vertex=pac_base,
        runtime_base_vertex=live_record.base_vertex,
        vertex_count=vertex_count,
        triangle_count=live_record.index_count // 3,
        bbox_match=bbox_match,
        index_match=index_match,
        delta=delta,
        packet_matches=packet_stats,
        csv_path=str(csv_path),
    )


def write_text_report(path: Path, summaries: list[SubmeshSummary]) -> None:
    with path.open("w", encoding="ascii", newline="\n") as handle:
        handle.write("PAC vs runtime shadow comparison\n")
        handle.write("================================\n\n")
        handle.write("This verifies the six proven dragon shadow submeshes against the original PAC.\n")
        handle.write("Expectation: bbox + local triangles match, raw packets do not.\n\n")
        for summary in summaries:
            handle.write(f"{summary.name}\n")
            handle.write(f"  command_index:       {summary.command_index}\n")
            handle.write(f"  parameter_index:     {summary.parameter_index}\n")
            handle.write(f"  vertex_count:        {summary.vertex_count}\n")
            handle.write(f"  triangle_count:      {summary.triangle_count}\n")
            handle.write(f"  bbox_match:          {summary.bbox_match}\n")
            handle.write(f"  index_match:         {summary.index_match}\n")
            handle.write(
                f"  delta_len:           min={summary.delta.minimum:.6f} avg={summary.delta.average:.6f} max={summary.delta.maximum:.6f}\n"
            )
            handle.write(
                f"  exact_packet_match:  {summary.packet_matches.exact_packet_matches} / {summary.vertex_count}\n"
            )
            handle.write(
                f"  exact_pos8_match:    {summary.packet_matches.exact_position_packet_matches} / {summary.vertex_count}\n"
            )
            handle.write("  field_exact_ratios:\n")
            for field_name in FIELDS:
                ratio = summary.packet_matches.field_exact_ratios[field_name]
                count = summary.packet_matches.field_exact_matches[field_name]
                handle.write(f"    {field_name:10s} {count:5d} / {summary.vertex_count:5d}  ({ratio:.4%})\n")
            handle.write(f"  csv_path:            {summary.csv_path}\n")
            handle.write("\n")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    pac_bytes = PAC_PATH.read_bytes()
    runtime_bytes = RESOURCE_16288.read_bytes()
    index_bytes = RESOURCE_2074.read_bytes()

    bboxes = pac_codec.parse_submesh_descriptors(pac_bytes)
    bboxes_by_name = {bbox.name: bbox for bbox in bboxes}
    pac_indices_by_name = pac_codec.read_indices(pac_bytes)

    summaries = [
        compare_submesh(name, command_index, bboxes_by_name, pac_indices_by_name, runtime_bytes, index_bytes, pac_bytes)
        for name, command_index in SHADOW_SUBMESHES
    ]

    manifest_path = OUT_DIR / "manifest.json"
    text_report_path = OUT_DIR / "report.txt"
    manifest_path.write_text(
        json.dumps(
            {
                "pac_path": str(PAC_PATH),
                "runtime_vertex_resource": str(RESOURCE_16288),
                "runtime_index_resource": str(RESOURCE_2074),
                "runtime_view_first_element": RUNTIME_VIEW_FIRST_ELEMENT,
                "records": [asdict(summary) for summary in summaries],
            },
            indent=2,
        ),
        encoding="ascii",
    )
    write_text_report(text_report_path, summaries)

    print(text_report_path)
    for summary in summaries:
        print(
            f"{summary.name:7s} bbox={summary.bbox_match} index={summary.index_match} "
            f"delta(avg={summary.delta.average:.4f}, max={summary.delta.maximum:.4f}) "
            f"exact40={summary.packet_matches.exact_packet_matches}"
        )


if __name__ == "__main__":
    main()
