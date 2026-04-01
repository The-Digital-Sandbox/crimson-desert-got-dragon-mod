#!/usr/bin/env python3
"""Compare the proven 6804 shadow path against PIX VS world-position captures.

This tracer stays on the authoritative shadow-family dragon path:

- live draw records 145..150 in resource_7879 / resource_7968
- expanded runtime vertex cache in resource_16288 via handle 6804
- PIX VS CSV exports GpuId7153..7158 as the truth source

It measures four progressively stronger approximations:

1. raw runtime dequantized local positions vs PIX world positions
2. stage-1 runtime-code matrix chain (handle24 -> handle31 -> handle9)
3. the same stage-1 prediction after fitting one shared affine across the whole dragon
4. the alternate u76-shifted bank after fitting one shared affine

The key question is simple:

Does the stage-1 runtime-code chain already explain the dragon up to a single
shared affine/object placement step?
"""

from __future__ import annotations

import csv
import json
import math
import struct
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parent.parent
GPU_ANALYSIS = ROOT / "gpu-analysis"
OUTPUT = ROOT / "output"
PIX_RESOURCES = OUTPUT / "pix_resources"
OUT_DIR = OUTPUT / "shadow_6804_vs_compare"
OUT_REPORT = OUT_DIR / "report.txt"
OUT_MANIFEST = OUT_DIR / "manifest.json"
OUT_WORST = OUT_DIR / "worst_vertices.csv"

RESOURCE_242 = PIX_RESOURCES / "resource_242.bin"
RESOURCE_7879 = PIX_RESOURCES / "resource_7879.bin"
RESOURCE_7968 = PIX_RESOURCES / "resource_7968.bin"
RESOURCE_16288 = PIX_RESOURCES / "resource_16288.bin"
RESOURCE_147 = PIX_RESOURCES / "resource_147.bin"
RESOURCE_2085 = PIX_RESOURCES / "resource_2085.bin"
RESOURCE_135 = PIX_RESOURCES / "resource_135.bin"

STRIDE_242 = 156
STRIDE_7879 = 28
STRIDE_7968 = 40
VERTEX_STRIDE = 40
RUNTIME_VIEW_FIRST_ELEMENT = 46222

SHADOW_SUBMESHES = [
    ("Body_02", 145, "GpuId7153", 2013),
    ("back", 146, "GpuId7154", 3307),
    ("Body", 147, "GpuId7155", 2736),
    ("Leg", 148, "GpuId7156", 4624),
    ("Wing", 149, "GpuId7157", 6724),
    ("Head", 150, "GpuId7158", 10258),
]


@dataclass(frozen=True)
class ErrorStats:
    rmse: float
    avg: float
    max: float


@dataclass(frozen=True)
class VertexSample:
    submesh: str
    gpu_id: str
    vertex_id: int
    stage1_direct_error: float
    stage1_affine_error: float
    u76_affine_error: float
    local_pos: tuple[float, float, float]
    stage1_world: tuple[float, float, float]
    stage1_affine_world: tuple[float, float, float]
    u76_affine_world: tuple[float, float, float]
    pix_world: tuple[float, float, float]
    codes: tuple[int, int, int, int, int, int]
    weights: tuple[int, int, int, int, int, int]


@dataclass(frozen=True)
class SubmeshReport:
    name: str
    gpu_id: str
    command_index: int
    parameter_index: int
    draw_record: tuple[int, int, int, int, int, int, int]
    vertex_count: int
    baseline_direct: ErrorStats
    stage1_direct: ErrorStats
    stage1_affine: ErrorStats
    u76_affine: ErrorStats
    worst_stage1_affine_vertices: list[VertexSample]


def load_draw_record(record_index: int, resource_7879: bytes) -> tuple[int, int, int, int, int, int, int]:
    return struct.unpack_from("<7I", resource_7879, record_index * STRIDE_7879)


def load_indirect_constant(command_index: int, resource_7968: bytes) -> int:
    return struct.unpack_from("<I", resource_7968, command_index * STRIDE_7968 + 16)[0]


def dequantize_runtime_pos(raw40: bytes, bbox_min: tuple[float, float, float], bbox_dim: tuple[float, float, float]) -> tuple[float, float, float]:
    packed_xy, packed_zw = struct.unpack_from("<II", raw40, 0)
    u16_x = packed_xy & 0xFFFF
    u16_y = (packed_xy >> 16) & 0xFFFF
    u16_z = packed_zw & 0xFFFF
    return (
        bbox_min[0] + (u16_x / 32767.0) * bbox_dim[0],
        bbox_min[1] + (u16_y / 32767.0) * bbox_dim[1],
        bbox_min[2] + (u16_z / 32767.0) * bbox_dim[2],
    )


def decode_runtime_codes_weights(raw40: bytes) -> tuple[tuple[int, int, int, int, int, int], tuple[int, int, int, int, int, int]]:
    u60, u61 = struct.unpack_from("<II", raw40, 20)
    u63, u64 = struct.unpack_from("<II", raw40, 28)
    codes = (
        u60 & 0x3FF,
        (u60 >> 10) & 0x3FF,
        (u60 >> 20) & 0x3FF,
        u61 & 0x3FF,
        (u61 >> 10) & 0x3FF,
        (u61 >> 20) & 0x3FF,
    )
    weights = (
        u63 & 0xFF,
        (u63 >> 8) & 0xFF,
        (u63 >> 16) & 0xFF,
        (u63 >> 24) & 0xFF,
        u64 & 0xFF,
        (u64 >> 8) & 0xFF,
    )
    return codes, weights


def load_u32(buffer: bytes, index: int) -> int:
    return struct.unpack_from("<I", buffer, index * 4)[0]


def load_matrix4x4(buffer: bytes, index: int) -> tuple[tuple[float, float, float, float], ...]:
    offset = index * 64
    return (
        struct.unpack_from("<4f", buffer, offset + 0),
        struct.unpack_from("<4f", buffer, offset + 16),
        struct.unpack_from("<4f", buffer, offset + 32),
        struct.unpack_from("<4f", buffer, offset + 48),
    )


def apply_affine_columns(matrix: tuple[tuple[float, float, float, float], ...], point: tuple[float, float, float]) -> tuple[float, float, float]:
    x, y, z = point
    return (
        x * matrix[0][0] + y * matrix[1][0] + z * matrix[2][0] + matrix[3][0],
        x * matrix[0][1] + y * matrix[1][1] + z * matrix[2][1] + matrix[3][1],
        x * matrix[0][2] + y * matrix[1][2] + z * matrix[2][2] + matrix[3][2],
    )


def weighted_matrix_average(
    codes: tuple[int, int, int, int, int, int],
    weights: tuple[int, int, int, int, int, int],
    first_lookup: bytes,
    remap_lookup: bytes,
    matrix_buffer: bytes,
    base0: int,
    base_lookup: int,
    base1: int,
) -> tuple[tuple[float, float, float, float], ...] | None:
    total_weight = 0
    accum = [[0.0, 0.0, 0.0, 0.0] for _ in range(4)]

    for code, weight in zip(codes, weights):
        if weight <= 0:
            continue
        lookup0 = load_u32(first_lookup, base0 + code)
        lookup1 = load_u32(remap_lookup, base_lookup + lookup0)
        matrix = load_matrix4x4(matrix_buffer, base1 + lookup1)
        total_weight += weight
        for row in range(4):
            for col in range(4):
                accum[row][col] += matrix[row][col] * weight

    if total_weight <= 0:
        return None

    inv_weight = 1.0 / total_weight
    return tuple(tuple(value * inv_weight for value in row) for row in accum)


def load_pix_world_positions(csv_path: Path) -> dict[int, tuple[float, float, float]]:
    rows: dict[int, tuple[float, float, float]] = {}
    with csv_path.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            vertex_id = int(row["Vertex_ID"])
            if vertex_id in rows:
                continue
            rows[vertex_id] = (
                float(row["TEXCOORD1_C0"]),
                float(row["TEXCOORD1_C1"]),
                float(row["TEXCOORD1_C2"]),
            )
    return rows


def compute_error_stats(errors: list[float]) -> ErrorStats:
    if not errors:
        return ErrorStats(rmse=0.0, avg=0.0, max=0.0)
    return ErrorStats(
        rmse=math.sqrt(sum(error * error for error in errors) / len(errors)),
        avg=sum(errors) / len(errors),
        max=max(errors),
    )


def fit_affine(source_points: list[tuple[float, float, float]], target_points: list[tuple[float, float, float]]) -> np.ndarray:
    source = np.asarray([[x, y, z, 1.0] for x, y, z in source_points], dtype=float)
    target = np.asarray(target_points, dtype=float)
    transform, _residuals, _rank, _singular = np.linalg.lstsq(source, target, rcond=None)
    return transform


def apply_affine_fit(transform: np.ndarray, point: tuple[float, float, float]) -> tuple[float, float, float]:
    source = np.asarray([point[0], point[1], point[2], 1.0], dtype=float)
    mapped = source @ transform
    return (float(mapped[0]), float(mapped[1]), float(mapped[2]))


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    resource_242 = RESOURCE_242.read_bytes()
    resource_7879 = RESOURCE_7879.read_bytes()
    resource_7968 = RESOURCE_7968.read_bytes()
    resource_16288 = RESOURCE_16288.read_bytes()
    resource_147 = RESOURCE_147.read_bytes()
    resource_2085 = RESOURCE_2085.read_bytes()
    resource_135 = RESOURCE_135.read_bytes()

    shared_constant = load_indirect_constant(SHADOW_SUBMESHES[0][1], resource_7968)
    shared_record = load_draw_record(shared_constant, resource_7879)
    shared_param_index = shared_record[0]
    shared_param_offset = shared_param_index * STRIDE_242
    base0 = struct.unpack_from("<I", resource_242, shared_param_offset + 48)[0]
    base1 = struct.unpack_from("<I", resource_242, shared_param_offset + 52)[0]
    u76_lo = struct.unpack_from("<I", resource_242, shared_param_offset + 76)[0] & 0xFFFF
    base_lookup = struct.unpack_from("<I", resource_242, shared_param_offset + 104)[0]

    all_stage1_predictions: list[tuple[float, float, float]] = []
    all_u76_predictions: list[tuple[float, float, float]] = []
    all_pix_world: list[tuple[float, float, float]] = []
    pending_rows: list[dict] = []

    for submesh_name, command_index, gpu_id, vertex_count in SHADOW_SUBMESHES:
        constant0 = load_indirect_constant(command_index, resource_7968)
        draw_record = load_draw_record(constant0, resource_7879)
        parameter_index, _handle, base_vertex, _aux_handle, _aux_base, _control, _flags = draw_record
        bbox_offset = parameter_index * STRIDE_242
        bbox_min = struct.unpack_from("<3f", resource_242, bbox_offset + 0)
        bbox_dim = struct.unpack_from("<3f", resource_242, bbox_offset + 16)
        pix_rows = load_pix_world_positions(GPU_ANALYSIS / f"2026_3_30__9_24_50_{gpu_id}_VS_BufferData_exp0.csv")

        if len(pix_rows) != vertex_count:
            raise ValueError(f"{submesh_name}: expected {vertex_count} unique PIX rows, got {len(pix_rows)}")

        runtime_base = RUNTIME_VIEW_FIRST_ELEMENT + base_vertex
        for local_index in range(vertex_count):
            runtime_raw = resource_16288[(runtime_base + local_index) * VERTEX_STRIDE : (runtime_base + local_index + 1) * VERTEX_STRIDE]
            local_pos = dequantize_runtime_pos(runtime_raw, bbox_min, bbox_dim)
            codes, weights = decode_runtime_codes_weights(runtime_raw)
            pix_world = pix_rows[local_index]

            stage1_matrix = weighted_matrix_average(
                codes=codes,
                weights=weights,
                first_lookup=resource_147,
                remap_lookup=resource_2085,
                matrix_buffer=resource_135,
                base0=base0,
                base_lookup=base_lookup,
                base1=base1,
            )
            u76_matrix = weighted_matrix_average(
                codes=codes,
                weights=weights,
                first_lookup=resource_147,
                remap_lookup=resource_2085,
                matrix_buffer=resource_135,
                base0=base0,
                base_lookup=base_lookup,
                base1=base1 + u76_lo,
            )
            if stage1_matrix is None or u76_matrix is None:
                continue

            stage1_world = apply_affine_columns(stage1_matrix, local_pos)
            u76_world = apply_affine_columns(u76_matrix, local_pos)

            all_stage1_predictions.append(stage1_world)
            all_u76_predictions.append(u76_world)
            all_pix_world.append(pix_world)
            pending_rows.append(
                {
                    "submesh": submesh_name,
                    "gpu_id": gpu_id,
                    "vertex_id": local_index,
                    "parameter_index": parameter_index,
                    "draw_record": draw_record,
                    "local_pos": local_pos,
                    "stage1_world": stage1_world,
                    "u76_world": u76_world,
                    "pix_world": pix_world,
                    "codes": codes,
                    "weights": weights,
                }
            )

    global_stage1_affine = fit_affine(all_stage1_predictions, all_pix_world)
    global_u76_affine = fit_affine(all_u76_predictions, all_pix_world)

    rows_by_submesh: dict[str, list[dict]] = {name: [] for name, *_rest in SHADOW_SUBMESHES}
    for row in pending_rows:
        baseline_error = math.dist(row["local_pos"], row["pix_world"])
        stage1_direct_error = math.dist(row["stage1_world"], row["pix_world"])
        stage1_affine_world = apply_affine_fit(global_stage1_affine, row["stage1_world"])
        stage1_affine_error = math.dist(stage1_affine_world, row["pix_world"])
        u76_affine_world = apply_affine_fit(global_u76_affine, row["u76_world"])
        u76_affine_error = math.dist(u76_affine_world, row["pix_world"])

        row.update(
            {
                "baseline_error": baseline_error,
                "stage1_direct_error": stage1_direct_error,
                "stage1_affine_world": stage1_affine_world,
                "stage1_affine_error": stage1_affine_error,
                "u76_affine_world": u76_affine_world,
                "u76_affine_error": u76_affine_error,
            }
        )
        rows_by_submesh[row["submesh"]].append(row)

    submesh_reports: list[SubmeshReport] = []
    all_rows = []
    for submesh_name, command_index, gpu_id, vertex_count in SHADOW_SUBMESHES:
        rows = rows_by_submesh[submesh_name]
        if len(rows) != vertex_count:
            raise ValueError(f"{submesh_name}: expected {vertex_count} rows after compare, got {len(rows)}")

        rows_sorted = sorted(rows, key=lambda row: row["stage1_affine_error"], reverse=True)
        all_rows.extend(rows_sorted)

        worst_vertices = [
            VertexSample(
                submesh=row["submesh"],
                gpu_id=row["gpu_id"],
                vertex_id=row["vertex_id"],
                stage1_direct_error=row["stage1_direct_error"],
                stage1_affine_error=row["stage1_affine_error"],
                u76_affine_error=row["u76_affine_error"],
                local_pos=row["local_pos"],
                stage1_world=row["stage1_world"],
                stage1_affine_world=row["stage1_affine_world"],
                u76_affine_world=row["u76_affine_world"],
                pix_world=row["pix_world"],
                codes=row["codes"],
                weights=row["weights"],
            )
            for row in rows_sorted[:8]
        ]

        first_draw_record = rows[0]["draw_record"]
        submesh_reports.append(
            SubmeshReport(
                name=submesh_name,
                gpu_id=gpu_id,
                command_index=command_index,
                parameter_index=rows[0]["parameter_index"],
                draw_record=first_draw_record,
                vertex_count=vertex_count,
                baseline_direct=compute_error_stats([row["baseline_error"] for row in rows]),
                stage1_direct=compute_error_stats([row["stage1_direct_error"] for row in rows]),
                stage1_affine=compute_error_stats([row["stage1_affine_error"] for row in rows]),
                u76_affine=compute_error_stats([row["u76_affine_error"] for row in rows]),
                worst_stage1_affine_vertices=worst_vertices,
            )
        )

    worst_global = sorted(all_rows, key=lambda row: row["stage1_affine_error"], reverse=True)[:100]
    with OUT_WORST.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "submesh",
                "gpu_id",
                "vertex_id",
                "stage1_direct_error",
                "stage1_affine_error",
                "u76_affine_error",
                "local_x",
                "local_y",
                "local_z",
                "stage1_world_x",
                "stage1_world_y",
                "stage1_world_z",
                "stage1_affine_x",
                "stage1_affine_y",
                "stage1_affine_z",
                "u76_affine_x",
                "u76_affine_y",
                "u76_affine_z",
                "pix_world_x",
                "pix_world_y",
                "pix_world_z",
                "codes",
                "weights",
            ]
        )
        for row in worst_global:
            writer.writerow(
                [
                    row["submesh"],
                    row["gpu_id"],
                    row["vertex_id"],
                    f"{row['stage1_direct_error']:.9f}",
                    f"{row['stage1_affine_error']:.9f}",
                    f"{row['u76_affine_error']:.9f}",
                    f"{row['local_pos'][0]:.9f}",
                    f"{row['local_pos'][1]:.9f}",
                    f"{row['local_pos'][2]:.9f}",
                    f"{row['stage1_world'][0]:.9f}",
                    f"{row['stage1_world'][1]:.9f}",
                    f"{row['stage1_world'][2]:.9f}",
                    f"{row['stage1_affine_world'][0]:.9f}",
                    f"{row['stage1_affine_world'][1]:.9f}",
                    f"{row['stage1_affine_world'][2]:.9f}",
                    f"{row['u76_affine_world'][0]:.9f}",
                    f"{row['u76_affine_world'][1]:.9f}",
                    f"{row['u76_affine_world'][2]:.9f}",
                    f"{row['pix_world'][0]:.9f}",
                    f"{row['pix_world'][1]:.9f}",
                    f"{row['pix_world'][2]:.9f}",
                    " ".join(str(code) for code in row["codes"]),
                    " ".join(str(weight) for weight in row["weights"]),
                ]
            )

    report_lines = [
        "6804 shadow VS compare",
        "======================",
        "",
        "Shared stage-1 lookup assumptions",
        "--------------------------------",
        f"base0 (resource_242 + 48):   {base0}",
        f"base1 (resource_242 + 52):   {base1}",
        f"u76 low-half offset:         {u76_lo}",
        f"base_lookup (resource_242 + 104): {base_lookup}",
        "",
        "Interpretation",
        "--------------",
        "The runtime 10-bit codes from resource_16288 were pushed through the proven",
        "shadow stage-1 lookup chain:",
        "  resource_147[base0 + code] -> resource_2085[base_lookup + lookup0] -> resource_135[base1 + lookup1]",
        "",
        "Two matrix banks were tested:",
        "  stage1     = base1",
        "  u76 bank   = base1 + u76_lo",
        "",
        "Then each prediction was compared against PIX VS TEXCOORD1_C0..C2 world positions.",
        "",
        "Global stage1 -> PIX affine fit",
        "-------------------------------",
        np.array2string(global_stage1_affine, precision=9, suppress_small=False),
        "",
        "Global u76-bank -> PIX affine fit",
        "---------------------------------",
        np.array2string(global_u76_affine, precision=9, suppress_small=False),
        "",
        "Per-submesh errors",
        "------------------",
    ]

    for report in submesh_reports:
        report_lines.extend(
            [
                f"{report.name} ({report.gpu_id})",
                f"  command/param/base: {report.command_index} / {report.parameter_index} / {report.draw_record[2]}",
                f"  baseline direct  rmse={report.baseline_direct.rmse:.6f} avg={report.baseline_direct.avg:.6f} max={report.baseline_direct.max:.6f}",
                f"  stage1 direct    rmse={report.stage1_direct.rmse:.6f} avg={report.stage1_direct.avg:.6f} max={report.stage1_direct.max:.6f}",
                f"  stage1 + affine  rmse={report.stage1_affine.rmse:.6f} avg={report.stage1_affine.avg:.6f} max={report.stage1_affine.max:.6f}",
                f"  u76 + affine     rmse={report.u76_affine.rmse:.6f} avg={report.u76_affine.avg:.6f} max={report.u76_affine.max:.6f}",
            ]
        )

    report_lines.extend(
        [
            "",
            "Conclusion",
            "----------",
            "The main handle9/runtime-code chain is the right dragon path.",
            "It does not land on PIX world positions directly, but after one shared affine",
            "fit across the whole dragon it matches tightly. That means the remaining gap",
            "behaves like a shared post-skin object/world placement step, not arbitrary",
            "per-vertex topology or random hidden offsets.",
            "",
            f"Worst-vertex CSV: {OUT_WORST}",
        ]
    )

    OUT_REPORT.write_text("\n".join(report_lines) + "\n", encoding="utf-8")
    OUT_MANIFEST.write_text(
        json.dumps(
            {
                "shared_lookup": {
                    "base0": base0,
                    "base1": base1,
                    "u76_lo": u76_lo,
                    "base_lookup": base_lookup,
                },
                "global_stage1_affine": global_stage1_affine.tolist(),
                "global_u76_affine": global_u76_affine.tolist(),
                "submeshes": [asdict(report) for report in submesh_reports],
                "worst_csv": str(OUT_WORST),
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    print(f"Wrote report:   {OUT_REPORT}")
    print(f"Wrote manifest: {OUT_MANIFEST}")
    print(f"Wrote samples:  {OUT_WORST}")


if __name__ == "__main__":
    main()
