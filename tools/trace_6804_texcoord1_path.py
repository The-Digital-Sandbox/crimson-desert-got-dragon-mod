#!/usr/bin/env python3
"""Reproduce the live 6804 shadow TEXCOORD1 path as closely as currently known.

This stays on the proven dragon shadow route:

- live draw records 145..150 in resource_7879 / resource_7968
- expanded runtime vertex cache in resource_16288 via handle 6804
- matrix lookup chain in resource_147 -> resource_2085 -> resource_135
- live space15 cluster block in resource_80[78] at offsets 64..112
- live cb14,space35 rows 87..90 from resource_20
- PIX VS exports GpuId7153..7158 as ground truth

What this tracer proves:

1. The active shadow path skips the 2411 normalization block.
2. The effective pre-space15 transform is a per-vertex lerp:
   M = lerp(M0, M1, blend)
   where:
   - M0 uses matrix base 2716
   - M1 uses matrix base 2990 (= 2716 + 274)
   - blend currently resolves to 1 - packed_vertex_factor for every tested vertex
3. After the exact space15 block and exact cb14 87..90 block, the result lands
   very close to PIX TEXCOORD1_C0..C2.

The remaining error is real but narrow; this script turns it into a stable,
repeatable artifact instead of another one-off shell experiment.
"""

from __future__ import annotations

import csv
import json
import math
import struct
from dataclasses import asdict, dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
GPU_ANALYSIS = ROOT / "gpu-analysis"
OUTPUT = ROOT / "output"
PIX_RESOURCES = OUTPUT / "pix_resources"
OUT_DIR = OUTPUT / "shadow_6804_texcoord1"
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
RESOURCE_80 = PIX_RESOURCES / "resource_80.bin"
RESOURCE_20 = PIX_RESOURCES / "resource_20.bin"

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
    error: float
    blend: float
    blend_source: str
    d0: float
    d1: float
    packed_factor: float
    local_pos: tuple[float, float, float]
    predicted_world: tuple[float, float, float]
    pix_world: tuple[float, float, float]


@dataclass(frozen=True)
class SharedConfig:
    base0: int
    base_lookup: int
    base_m0: int
    base_m1: int
    shift: int
    flag128_active: bool
    cluster_index: int
    half_scale_2c44: float


@dataclass(frozen=True)
class SubmeshReport:
    name: str
    gpu_id: str
    command_index: int
    parameter_index: int
    draw_record: tuple[int, int, int, int, int, int, int]
    vertex_count: int
    error: ErrorStats
    blend_min: float
    blend_avg: float
    blend_max: float
    packed_factor_min: float
    packed_factor_avg: float
    packed_factor_max: float
    d0_positive_count: int
    packed_fallback_count: int
    worst_vertices: list[VertexSample]


def load_draw_record(record_index: int, resource_7879: bytes) -> tuple[int, int, int, int, int, int, int]:
    return struct.unpack_from("<7I", resource_7879, record_index * STRIDE_7879)


def load_indirect_constant(command_index: int, resource_7968: bytes) -> int:
    return struct.unpack_from("<I", resource_7968, command_index * STRIDE_7968 + 16)[0]


def half_from_bits(bits: int) -> float:
    return float(struct.unpack("<e", struct.pack("<H", bits))[0])


def load_matrix4x4(buffer: bytes, index: int) -> tuple[tuple[float, float, float, float], ...]:
    offset = index * 64
    return (
        struct.unpack_from("<4f", buffer, offset + 0),
        struct.unpack_from("<4f", buffer, offset + 16),
        struct.unpack_from("<4f", buffer, offset + 32),
        struct.unpack_from("<4f", buffer, offset + 48),
    )


def load_u32(buffer: bytes, index: int) -> int:
    return struct.unpack_from("<I", buffer, index * 4)[0]


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


def apply_matrix_3x4(matrix: tuple[tuple[float, float, float, float], ...], point: tuple[float, float, float]) -> tuple[float, float, float]:
    x, y, z = point
    return (
        x * matrix[0][0] + y * matrix[1][0] + z * matrix[2][0] + matrix[3][0],
        x * matrix[0][1] + y * matrix[1][1] + z * matrix[2][1] + matrix[3][1],
        x * matrix[0][2] + y * matrix[1][2] + z * matrix[2][2] + matrix[3][2],
    )


def apply_space15_block(matrix: tuple[tuple[float, float, float, float], ...], point: tuple[float, float, float]) -> tuple[float, float, float]:
    x, y, z = point
    return (
        x * matrix[0][0] + y * matrix[1][0] + z * matrix[2][0] + matrix[3][0],
        x * matrix[0][1] + y * matrix[1][1] + z * matrix[2][1] + matrix[3][1],
        x * matrix[0][2] + y * matrix[1][2] + z * matrix[2][2] + matrix[3][2],
    )


def apply_cb14_block(matrix: tuple[tuple[float, float, float, float], ...], point: tuple[float, float, float]) -> tuple[float, float, float]:
    x, y, z = point
    return (
        x * matrix[0][0] + y * matrix[1][0] + z * matrix[2][0] + matrix[3][0],
        x * matrix[0][1] + y * matrix[1][1] + z * matrix[2][1] + matrix[3][1],
        x * matrix[0][3] + y * matrix[1][3] + z * matrix[2][3] + matrix[3][3],
    )


def compute_error_stats(errors: list[float]) -> ErrorStats:
    if not errors:
        return ErrorStats(rmse=0.0, avg=0.0, max=0.0)
    return ErrorStats(
        rmse=math.sqrt(sum(error * error for error in errors) / len(errors)),
        avg=sum(errors) / len(errors),
        max=max(errors),
    )


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    resource_242 = RESOURCE_242.read_bytes()
    resource_7879 = RESOURCE_7879.read_bytes()
    resource_7968 = RESOURCE_7968.read_bytes()
    resource_16288 = RESOURCE_16288.read_bytes()
    resource_147 = RESOURCE_147.read_bytes()
    resource_2085 = RESOURCE_2085.read_bytes()
    resource_135 = RESOURCE_135.read_bytes()
    resource_80 = RESOURCE_80.read_bytes()
    resource_20 = RESOURCE_20.read_bytes()

    shared_constant = load_indirect_constant(SHADOW_SUBMESHES[0][1], resource_7968)
    shared_record = load_draw_record(shared_constant, resource_7879)
    shared_param_index = shared_record[0]
    shared_param_offset = shared_param_index * STRIDE_242

    shared_config = SharedConfig(
        base0=struct.unpack_from("<I", resource_242, shared_param_offset + 48)[0],
        base_lookup=struct.unpack_from("<I", resource_242, shared_param_offset + 104)[0],
        base_m0=struct.unpack_from("<I", resource_242, shared_param_offset + 56)[0],
        base_m1=struct.unpack_from("<I", resource_242, shared_param_offset + 52)[0]
        + (struct.unpack_from("<I", resource_242, shared_param_offset + 76)[0] >> 16),
        shift=struct.unpack_from("<I", resource_242, shared_param_offset + 76)[0] >> 16,
        flag128_active=bool(struct.unpack_from("<I", resource_242, shared_param_offset + 44)[0] & 128),
        cluster_index=struct.unpack_from("<I", resource_242, shared_param_offset + 96)[0] & 0xFFFF,
        half_scale_2c44=half_from_bits(0x2C44),
    )

    space15_block = (
        struct.unpack_from("<4f", resource_80, shared_config.cluster_index * 272 + 64 + 0),
        struct.unpack_from("<4f", resource_80, shared_config.cluster_index * 272 + 64 + 16),
        struct.unpack_from("<4f", resource_80, shared_config.cluster_index * 272 + 64 + 32),
        struct.unpack_from("<4f", resource_80, shared_config.cluster_index * 272 + 64 + 48),
    )
    cb14_block = (
        struct.unpack_from("<4f", resource_20, 87 * 16),
        struct.unpack_from("<4f", resource_20, 88 * 16),
        struct.unpack_from("<4f", resource_20, 89 * 16),
        struct.unpack_from("<4f", resource_20, 90 * 16),
    )

    submesh_reports: list[SubmeshReport] = []
    all_samples: list[VertexSample] = []

    for submesh_name, command_index, gpu_id, vertex_count in SHADOW_SUBMESHES:
        constant0 = load_indirect_constant(command_index, resource_7968)
        draw_record = load_draw_record(constant0, resource_7879)
        parameter_index, _handle, base_vertex, _aux_handle, _aux_base, _control, _flags = draw_record
        bbox_offset = parameter_index * STRIDE_242
        bbox_min = struct.unpack_from("<3f", resource_242, bbox_offset + 0)
        bbox_dim = struct.unpack_from("<3f", resource_242, bbox_offset + 16)
        pix_rows = load_pix_world_positions(GPU_ANALYSIS / f"2026_3_30__9_24_50_{gpu_id}_VS_BufferData_exp0.csv")

        errors: list[float] = []
        blends: list[float] = []
        packed_factors: list[float] = []
        d0_positive_count = 0
        packed_fallback_count = 0
        samples: list[VertexSample] = []

        for local_index in range(vertex_count):
            runtime_raw = resource_16288[
                (RUNTIME_VIEW_FIRST_ELEMENT + base_vertex + local_index) * VERTEX_STRIDE :
                (RUNTIME_VIEW_FIRST_ELEMENT + base_vertex + local_index + 1) * VERTEX_STRIDE
            ]
            local_pos = dequantize_runtime_pos(runtime_raw, bbox_min, bbox_dim)
            codes, weights = decode_runtime_codes_weights(runtime_raw)

            total_weight = sum(weight for weight in weights if weight > 0)
            if total_weight <= 0:
                continue

            acc_m0 = [[0.0, 0.0, 0.0, 0.0] for _ in range(4)]
            acc_m1 = [[0.0, 0.0, 0.0, 0.0] for _ in range(4)]
            for code, weight in zip(codes, weights):
                if weight <= 0:
                    continue
                lookup0 = load_u32(resource_147, shared_config.base0 + code)
                lookup1 = load_u32(resource_2085, shared_config.base_lookup + lookup0)
                matrix0 = load_matrix4x4(resource_135, shared_config.base_m0 + lookup1)
                matrix1 = load_matrix4x4(resource_135, shared_config.base_m1 + lookup1)
                factor = weight / total_weight
                for row in range(4):
                    for col in range(4):
                        acc_m0[row][col] += matrix0[row][col] * factor
                        acc_m1[row][col] += matrix1[row][col] * factor

            packed_word = struct.unpack_from("<I", runtime_raw, 36)[0] >> 16
            if shared_config.flag128_active:
                packed_factor = float(packed_word & 0xF) * shared_config.half_scale_2c44
            else:
                packed_factor = float(packed_word & 0xFF) / float(half_from_bits(0x5BF8))

            d0 = acc_m0[0][3]
            d1 = acc_m0[1][3]
            if d0 > 0.0:
                blend = d1
                blend_source = "d1"
                d0_positive_count += 1
            else:
                blend = 1.0 - packed_factor
                blend_source = "packed"
                packed_fallback_count += 1

            blended_matrix = tuple(
                tuple(acc_m0[row][col] + (acc_m1[row][col] - acc_m0[row][col]) * blend for col in range(4))
                for row in range(4)
            )

            stage1_world = apply_matrix_3x4(blended_matrix, local_pos)
            after_space15 = apply_space15_block(space15_block, stage1_world)
            predicted_world = apply_cb14_block(cb14_block, after_space15)
            pix_world = pix_rows[local_index]
            error = math.dist(predicted_world, pix_world)

            errors.append(error)
            blends.append(blend)
            packed_factors.append(packed_factor)
            samples.append(
                VertexSample(
                    submesh=submesh_name,
                    gpu_id=gpu_id,
                    vertex_id=local_index,
                    error=error,
                    blend=blend,
                    blend_source=blend_source,
                    d0=d0,
                    d1=d1,
                    packed_factor=packed_factor,
                    local_pos=local_pos,
                    predicted_world=predicted_world,
                    pix_world=pix_world,
                )
            )

        samples.sort(key=lambda sample: sample.error, reverse=True)
        submesh_reports.append(
            SubmeshReport(
                name=submesh_name,
                gpu_id=gpu_id,
                command_index=command_index,
                parameter_index=parameter_index,
                draw_record=draw_record,
                vertex_count=vertex_count,
                error=compute_error_stats(errors),
                blend_min=min(blends) if blends else 0.0,
                blend_avg=sum(blends) / len(blends) if blends else 0.0,
                blend_max=max(blends) if blends else 0.0,
                packed_factor_min=min(packed_factors) if packed_factors else 0.0,
                packed_factor_avg=sum(packed_factors) / len(packed_factors) if packed_factors else 0.0,
                packed_factor_max=max(packed_factors) if packed_factors else 0.0,
                d0_positive_count=d0_positive_count,
                packed_fallback_count=packed_fallback_count,
                worst_vertices=samples[:8],
            )
        )
        all_samples.extend(samples)

    all_samples.sort(key=lambda sample: sample.error, reverse=True)
    overall_errors = [sample.error for sample in all_samples]
    overall_report = compute_error_stats(overall_errors)

    manifest = {
        "shared_config": asdict(shared_config),
        "overall_error": asdict(overall_report),
        "submeshes": [asdict(report) for report in submesh_reports],
    }
    OUT_MANIFEST.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    with OUT_WORST.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "submesh",
                "gpu_id",
                "vertex_id",
                "error",
                "blend",
                "blend_source",
                "d0",
                "d1",
                "packed_factor",
                "local_x",
                "local_y",
                "local_z",
                "pred_x",
                "pred_y",
                "pred_z",
                "pix_x",
                "pix_y",
                "pix_z",
            ]
        )
        for sample in all_samples[:64]:
            writer.writerow(
                [
                    sample.submesh,
                    sample.gpu_id,
                    sample.vertex_id,
                    f"{sample.error:.9f}",
                    f"{sample.blend:.9f}",
                    sample.blend_source,
                    f"{sample.d0:.9f}",
                    f"{sample.d1:.9f}",
                    f"{sample.packed_factor:.9f}",
                    f"{sample.local_pos[0]:.9f}",
                    f"{sample.local_pos[1]:.9f}",
                    f"{sample.local_pos[2]:.9f}",
                    f"{sample.predicted_world[0]:.9f}",
                    f"{sample.predicted_world[1]:.9f}",
                    f"{sample.predicted_world[2]:.9f}",
                    f"{sample.pix_world[0]:.9f}",
                    f"{sample.pix_world[1]:.9f}",
                    f"{sample.pix_world[2]:.9f}",
                ]
            )

    lines = [
        "6804 shadow TEXCOORD1 tracer",
        "===========================",
        "",
        "Shared config",
        "-------------",
        f"base0       : {shared_config.base0}",
        f"base_lookup : {shared_config.base_lookup}",
        f"base_m0     : {shared_config.base_m0}",
        f"base_m1     : {shared_config.base_m1}",
        f"shift       : {shared_config.shift}",
        f"flag128     : {shared_config.flag128_active}",
        f"cluster_idx : {shared_config.cluster_index}",
        f"half_2c44   : {shared_config.half_scale_2c44:.9f}",
        "",
        "Overall error after exact live path",
        "-----------------------------------",
        f"rmse : {overall_report.rmse:.9f}",
        f"avg  : {overall_report.avg:.9f}",
        f"max  : {overall_report.max:.9f}",
        "",
        "Per-submesh",
        "-----------",
    ]
    for report in submesh_reports:
        lines.extend(
            [
                f"{report.name} ({report.gpu_id})",
                f"  rmse              : {report.error.rmse:.9f}",
                f"  avg               : {report.error.avg:.9f}",
                f"  max               : {report.error.max:.9f}",
                f"  blend min/avg/max : {report.blend_min:.9f} / {report.blend_avg:.9f} / {report.blend_max:.9f}",
                (
                    "  packed min/avg/max: "
                    f"{report.packed_factor_min:.9f} / {report.packed_factor_avg:.9f} / {report.packed_factor_max:.9f}"
                ),
                f"  d0>0 branch count : {report.d0_positive_count}",
                f"  packed branch cnt : {report.packed_fallback_count}",
            ]
        )
    OUT_REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
