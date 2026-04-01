#!/usr/bin/env python3
"""Probe the late 6804 shadow-position path.

This script focuses on the stage that was missing from the older TEXCOORD1
tracer:

- runtime local vertex -> late matrix bank in resource_2070
- exact `%2397..%2408` / `%2603..%2614` style local transform
- exact shadow `space15` block `64..112`
- exact cb14 rows `87..90`

It also records a useful diagnostic:

- if the same late position is passed through the non-shader `space15` block
  `0..48`, it often lands even closer to PIX. That block is *not* the shader
  path for TEXCOORD1, but the comparison is still useful because it shows the
  remaining miss is downstream of the late matrix stage.

Critical branch result:

- all proven shadow-family dragon vertices currently have the packed 6-bit
  factor pegged at `63`
- therefore `%325`, `%404`, `%1526`, `%1585`, and `%2411` are dead for the
  full shadow dragon family in this capture
- the late path uses the full 6 runtime code/weight slots for every tested
  shadow vertex
"""

from __future__ import annotations

import csv
import json
import math
import struct
from dataclasses import asdict, dataclass
from pathlib import Path

import trace_6804_texcoord1_path as tex1


ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "output"
PIX_RESOURCES = OUTPUT / "pix_resources"
GPU_ANALYSIS = ROOT / "gpu-analysis"

OUT_DIR = OUTPUT / "shadow_6804_late_position"
OUT_REPORT = OUT_DIR / "report.txt"
OUT_MANIFEST = OUT_DIR / "manifest.json"
OUT_WORST = OUT_DIR / "worst_vertices.csv"

RESOURCE_242 = PIX_RESOURCES / "resource_242.bin"
RESOURCE_7879 = PIX_RESOURCES / "resource_7879.bin"
RESOURCE_7968 = PIX_RESOURCES / "resource_7968.bin"
RESOURCE_16288 = PIX_RESOURCES / "resource_16288.bin"
RESOURCE_147 = PIX_RESOURCES / "resource_147.bin"
RESOURCE_2085 = PIX_RESOURCES / "resource_2085.bin"
RESOURCE_2070 = PIX_RESOURCES / "resource_2070.bin"
RESOURCE_80 = PIX_RESOURCES / "resource_80.bin"
RESOURCE_20 = PIX_RESOURCES / "resource_20.bin"


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
    error_exact: float
    error_diag_block0: float
    late_factor_6bit: int
    active_influences: int
    local_pos: tuple[float, float, float]
    predicted_exact: tuple[float, float, float]
    pix_world: tuple[float, float, float]


@dataclass(frozen=True)
class SharedConfig:
    base0: int
    base_lookup: int
    base_late_matrix: int
    cluster_index: int
    u64_word: int
    u64_lt_2pow30: bool


@dataclass(frozen=True)
class SubmeshReport:
    name: str
    gpu_id: str
    command_index: int
    parameter_index: int
    draw_record: tuple[int, int, int, int, int, int, int]
    vertex_count: int
    late_factor_histogram: dict[int, int]
    exact_error: ErrorStats
    diagnostic_block0_error: ErrorStats
    worst_vertices: list[VertexSample]


def compute_error_stats(errors: list[float]) -> ErrorStats:
    if not errors:
        return ErrorStats(rmse=0.0, avg=0.0, max=0.0)
    return ErrorStats(
        rmse=math.sqrt(sum(value * value for value in errors) / len(errors)),
        avg=sum(errors) / len(errors),
        max=max(errors),
    )


def load_space15_block(resource_80: bytes, element_index: int, base_offset: int) -> tuple[tuple[float, float, float, float], ...]:
    base = element_index * 272 + base_offset
    return (
        struct.unpack_from("<4f", resource_80, base + 0),
        struct.unpack_from("<4f", resource_80, base + 16),
        struct.unpack_from("<4f", resource_80, base + 32),
        struct.unpack_from("<4f", resource_80, base + 48),
    )


def decode_late_factor_6bit(raw40: bytes) -> int:
    return (struct.unpack_from("<I", raw40, 36)[0] >> 24) & 63


def accumulate_late_matrix(
    raw40: bytes,
    resource_147: bytes,
    resource_2085: bytes,
    resource_2070: bytes,
    base0: int,
    base_lookup: int,
    base_late_matrix: int,
) -> tuple[tuple[float, float, float, float], ...]:
    codes, weights = tex1.decode_runtime_codes_weights(raw40)
    late_factor_6bit = decode_late_factor_6bit(raw40)
    active_count = 6 if late_factor_6bit >= 63 else 4
    total_weight = sum(weight for weight in weights[:active_count] if weight > 0)
    if total_weight <= 0:
        return (
            (0.0, 0.0, 0.0, 0.0),
            (0.0, 0.0, 0.0, 0.0),
            (0.0, 0.0, 0.0, 0.0),
            (0.0, 0.0, 0.0, 0.0),
        )

    accum = [[0.0, 0.0, 0.0, 0.0] for _ in range(4)]
    for code, weight in zip(codes[:active_count], weights[:active_count]):
        if weight <= 0:
            continue
        lookup0 = tex1.load_u32(resource_147, base0 + code)
        lookup1 = tex1.load_u32(resource_2085, base_lookup + lookup0)
        matrix = tex1.load_matrix4x4(resource_2070, base_late_matrix + lookup1)
        factor = weight / total_weight
        for row in range(4):
            for col in range(4):
                accum[row][col] += matrix[row][col] * factor

    return tuple(tuple(row) for row in accum)


def apply_late_position(matrix: tuple[tuple[float, float, float, float], ...], point: tuple[float, float, float]) -> tuple[float, float, float]:
    x, y, z = point
    return (
        x * matrix[0][0] + y * matrix[1][0] + z * matrix[2][0] + matrix[3][0],
        x * matrix[0][1] + y * matrix[1][1] + z * matrix[2][1] + matrix[3][1],
        x * matrix[0][2] + y * matrix[1][2] + z * matrix[2][2] + matrix[3][2],
    )


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    resource_242 = RESOURCE_242.read_bytes()
    resource_7879 = RESOURCE_7879.read_bytes()
    resource_7968 = RESOURCE_7968.read_bytes()
    resource_16288 = RESOURCE_16288.read_bytes()
    resource_147 = RESOURCE_147.read_bytes()
    resource_2085 = RESOURCE_2085.read_bytes()
    resource_2070 = RESOURCE_2070.read_bytes()
    resource_80 = RESOURCE_80.read_bytes()
    resource_20 = RESOURCE_20.read_bytes()

    shared_constant = tex1.load_indirect_constant(tex1.SHADOW_SUBMESHES[0][1], resource_7968)
    shared_record = tex1.load_draw_record(shared_constant, resource_7879)
    shared_param_offset = shared_record[0] * tex1.STRIDE_242

    shared_config = SharedConfig(
        base0=struct.unpack_from("<I", resource_242, shared_param_offset + 48)[0],
        base_lookup=struct.unpack_from("<I", resource_242, shared_param_offset + 104)[0],
        base_late_matrix=struct.unpack_from("<I", resource_242, shared_param_offset + 56)[0],
        cluster_index=struct.unpack_from("<I", resource_242, shared_param_offset + 96)[0] & 0xFFFF,
        u64_word=struct.unpack_from("<I", resource_242, shared_param_offset + 64)[0],
        u64_lt_2pow30=struct.unpack_from("<I", resource_242, shared_param_offset + 64)[0] < 1073741824,
    )

    block_0 = load_space15_block(resource_80, shared_config.cluster_index, 0)
    block_64 = load_space15_block(resource_80, shared_config.cluster_index, 64)
    cb14_block = (
        struct.unpack_from("<4f", resource_20, 87 * 16),
        struct.unpack_from("<4f", resource_20, 88 * 16),
        struct.unpack_from("<4f", resource_20, 89 * 16),
        struct.unpack_from("<4f", resource_20, 90 * 16),
    )

    submesh_reports: list[SubmeshReport] = []
    all_samples: list[VertexSample] = []
    global_histogram: dict[int, int] = {}

    for submesh_name, command_index, gpu_id, vertex_count in tex1.SHADOW_SUBMESHES:
        constant0 = tex1.load_indirect_constant(command_index, resource_7968)
        draw_record = tex1.load_draw_record(constant0, resource_7879)
        parameter_index, _handle, base_vertex, _aux_handle, _aux_base, _control, _flags = draw_record
        bbox_offset = parameter_index * tex1.STRIDE_242
        bbox_min = struct.unpack_from("<3f", resource_242, bbox_offset + 0)
        bbox_dim = struct.unpack_from("<3f", resource_242, bbox_offset + 16)
        pix_rows = tex1.load_pix_world_positions(GPU_ANALYSIS / f"2026_3_30__9_24_50_{gpu_id}_VS_BufferData_exp0.csv")

        late_factor_histogram: dict[int, int] = {}
        exact_errors: list[float] = []
        diagnostic_block0_errors: list[float] = []
        samples: list[VertexSample] = []

        for local_index in range(vertex_count):
            runtime_raw = resource_16288[
                (tex1.RUNTIME_VIEW_FIRST_ELEMENT + base_vertex + local_index) * tex1.VERTEX_STRIDE :
                (tex1.RUNTIME_VIEW_FIRST_ELEMENT + base_vertex + local_index + 1) * tex1.VERTEX_STRIDE
            ]
            local_pos = tex1.dequantize_runtime_pos(runtime_raw, bbox_min, bbox_dim)
            late_factor_6bit = decode_late_factor_6bit(runtime_raw)
            active_influences = 6 if late_factor_6bit >= 63 else 4
            late_factor_histogram[late_factor_6bit] = late_factor_histogram.get(late_factor_6bit, 0) + 1
            global_histogram[late_factor_6bit] = global_histogram.get(late_factor_6bit, 0) + 1

            late_matrix = accumulate_late_matrix(
                raw40=runtime_raw,
                resource_147=resource_147,
                resource_2085=resource_2085,
                resource_2070=resource_2070,
                base0=shared_config.base0,
                base_lookup=shared_config.base_lookup,
                base_late_matrix=shared_config.base_late_matrix,
            )
            late_pos = apply_late_position(late_matrix, local_pos)
            predicted_exact = tex1.apply_cb14_block(cb14_block, tex1.apply_space15_block(block_64, late_pos))
            predicted_diag_block0 = tex1.apply_cb14_block(cb14_block, tex1.apply_space15_block(block_0, late_pos))
            pix_world = pix_rows[local_index]

            error_exact = math.dist(predicted_exact, pix_world)
            error_diag_block0 = math.dist(predicted_diag_block0, pix_world)
            exact_errors.append(error_exact)
            diagnostic_block0_errors.append(error_diag_block0)
            samples.append(
                VertexSample(
                    submesh=submesh_name,
                    gpu_id=gpu_id,
                    vertex_id=local_index,
                    error_exact=error_exact,
                    error_diag_block0=error_diag_block0,
                    late_factor_6bit=late_factor_6bit,
                    active_influences=active_influences,
                    local_pos=local_pos,
                    predicted_exact=predicted_exact,
                    pix_world=pix_world,
                )
            )

        samples.sort(key=lambda sample: sample.error_exact, reverse=True)
        submesh_reports.append(
            SubmeshReport(
                name=submesh_name,
                gpu_id=gpu_id,
                command_index=command_index,
                parameter_index=parameter_index,
                draw_record=draw_record,
                vertex_count=vertex_count,
                late_factor_histogram=dict(sorted(late_factor_histogram.items())),
                exact_error=compute_error_stats(exact_errors),
                diagnostic_block0_error=compute_error_stats(diagnostic_block0_errors),
                worst_vertices=samples[:8],
            )
        )
        all_samples.extend(samples)

    all_samples.sort(key=lambda sample: sample.error_exact, reverse=True)
    mean_delta = (
        sum(sample.pix_world[0] - sample.predicted_exact[0] for sample in all_samples) / len(all_samples),
        sum(sample.pix_world[1] - sample.predicted_exact[1] for sample in all_samples) / len(all_samples),
        sum(sample.pix_world[2] - sample.predicted_exact[2] for sample in all_samples) / len(all_samples),
    )
    corrected_error_by_submesh: dict[str, ErrorStats] = {}
    for report in submesh_reports:
        corrected_errors = []
        for sample in all_samples:
            if sample.submesh != report.name:
                continue
            corrected_pred = (
                sample.predicted_exact[0] + mean_delta[0],
                sample.predicted_exact[1] + mean_delta[1],
                sample.predicted_exact[2] + mean_delta[2],
            )
            corrected_errors.append(math.dist(corrected_pred, sample.pix_world))
        corrected_error_by_submesh[report.name] = compute_error_stats(corrected_errors)

    manifest = {
        "shared_config": asdict(shared_config),
        "global_late_factor_histogram": dict(sorted(global_histogram.items())),
        "global_mean_delta_exact_to_pix": mean_delta,
        "shared_translation_corrected_error_by_submesh": {
            name: asdict(stats) for name, stats in corrected_error_by_submesh.items()
        },
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
                "error_exact",
                "error_diag_block0",
                "late_factor_6bit",
                "active_influences",
                "local_x",
                "local_y",
                "local_z",
                "pred_exact_x",
                "pred_exact_y",
                "pred_exact_z",
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
                    f"{sample.error_exact:.9f}",
                    f"{sample.error_diag_block0:.9f}",
                    sample.late_factor_6bit,
                    sample.active_influences,
                    f"{sample.local_pos[0]:.9f}",
                    f"{sample.local_pos[1]:.9f}",
                    f"{sample.local_pos[2]:.9f}",
                    f"{sample.predicted_exact[0]:.9f}",
                    f"{sample.predicted_exact[1]:.9f}",
                    f"{sample.predicted_exact[2]:.9f}",
                    f"{sample.pix_world[0]:.9f}",
                    f"{sample.pix_world[1]:.9f}",
                    f"{sample.pix_world[2]:.9f}",
                ]
            )

    lines = [
        "6804 late position probe",
        "=======================",
        "",
        "Shared config",
        "-------------",
        f"base0             : {shared_config.base0}",
        f"base_lookup       : {shared_config.base_lookup}",
        f"base_late_matrix  : {shared_config.base_late_matrix}",
        f"cluster_idx       : {shared_config.cluster_index}",
        f"u64_word          : {shared_config.u64_word}",
        f"u64 < 2^30        : {shared_config.u64_lt_2pow30}",
        "",
        "Global late-factor histogram",
        "----------------------------",
    ]
    for factor, count in sorted(global_histogram.items()):
        lines.append(f"  {factor:2d}: {count}")

    lines.extend(
        [
            "",
            "Interpretation",
            "--------------",
            "- The late position stage is built from resource_2070, not resource_135.",
            "- The exact TEXCOORD1 shader path remains: late_matrix -> space15[64..112] -> cb14[87..90].",
            "- The diagnostic block0 comparison is not a shader path; it only shows the remaining miss is downstream of the late matrix stage.",
            "- In this capture, the packed 6-bit factor is 63 for every shadow-family dragon vertex, so the alternate `%325` / `%2411` correction branches are dead on the proven 6804 route.",
            (
                "  A single shared translation delta removes most of the remaining error: "
                f"({mean_delta[0]:.9f}, {mean_delta[1]:.9f}, {mean_delta[2]:.9f})"
            ),
            "",
            "Per-submesh",
            "-----------",
        ]
    )
    for report in submesh_reports:
        lines.extend(
            [
                f"{report.name} ({report.gpu_id})",
                f"  exact late path rmse        : {report.exact_error.rmse:.9f}",
                f"  diagnostic block0 rmse      : {report.diagnostic_block0_error.rmse:.9f}",
                f"  shared-translation rmse     : {corrected_error_by_submesh[report.name].rmse:.9f}",
                f"  late factor histogram       : {report.late_factor_histogram}",
            ]
        )

    OUT_REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
