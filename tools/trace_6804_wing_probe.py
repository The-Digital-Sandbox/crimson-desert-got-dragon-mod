#!/usr/bin/env python3
"""Focused probe for the remaining 6804 Wing mismatch.

This script does not try to solve the whole shader. It turns the current
wing-specific evidence into a stable artifact:

- exact-path wing error stats from the proven 6804 tracer
- split by hot/cold wing halves
- pre-cb14 target recovery by inverting the live cb14 world block
- comparison of the two obvious space15 blocks in resource_80[78]
- brute-force check that no other resource_80 element beats element 78

The goal is to keep the next reverse-engineering step narrow:
the dragon path is mostly solved; the remaining miss is concentrated in Wing.
"""

from __future__ import annotations

import json
import math
import struct
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

import trace_6804_texcoord1_path as tex1


ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "output"
PIX_RESOURCES = OUTPUT / "pix_resources"
GPU_ANALYSIS = ROOT / "gpu-analysis"

OUT_DIR = OUTPUT / "shadow_6804_wing_probe"
OUT_REPORT = OUT_DIR / "report.txt"
OUT_MANIFEST = OUT_DIR / "manifest.json"

RESOURCE_242 = PIX_RESOURCES / "resource_242.bin"
RESOURCE_7879 = PIX_RESOURCES / "resource_7879.bin"
RESOURCE_7968 = PIX_RESOURCES / "resource_7968.bin"
RESOURCE_16288 = PIX_RESOURCES / "resource_16288.bin"
RESOURCE_147 = PIX_RESOURCES / "resource_147.bin"
RESOURCE_2085 = PIX_RESOURCES / "resource_2085.bin"
RESOURCE_135 = PIX_RESOURCES / "resource_135.bin"
RESOURCE_80 = PIX_RESOURCES / "resource_80.bin"
RESOURCE_20 = PIX_RESOURCES / "resource_20.bin"


@dataclass(frozen=True)
class ErrorStats:
    rmse: float
    avg: float
    max: float


@dataclass(frozen=True)
class SplitStats:
    label: str
    count: int
    error: ErrorStats


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


def apply_space15_affine(
    block: tuple[tuple[float, float, float, float], ...],
    point: np.ndarray,
) -> np.ndarray:
    x, y, z = point
    return np.array(
        [
            x * block[0][0] + y * block[1][0] + z * block[2][0] + block[3][0],
            x * block[0][1] + y * block[1][1] + z * block[2][1] + block[3][1],
            x * block[0][2] + y * block[1][2] + z * block[2][2] + block[3][2],
        ],
        dtype=float,
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

    shared_constant = tex1.load_indirect_constant(tex1.SHADOW_SUBMESHES[0][1], resource_7968)
    shared_record = tex1.load_draw_record(shared_constant, resource_7879)
    shared_param_offset = shared_record[0] * tex1.STRIDE_242

    shared = {
        "base0": struct.unpack_from("<I", resource_242, shared_param_offset + 48)[0],
        "base_lookup": struct.unpack_from("<I", resource_242, shared_param_offset + 104)[0],
        "base_m0": struct.unpack_from("<I", resource_242, shared_param_offset + 56)[0],
        "base_m1": struct.unpack_from("<I", resource_242, shared_param_offset + 52)[0]
        + (struct.unpack_from("<I", resource_242, shared_param_offset + 76)[0] >> 16),
        "cluster_index": struct.unpack_from("<I", resource_242, shared_param_offset + 96)[0] & 0xFFFF,
        "flag128_active": bool(struct.unpack_from("<I", resource_242, shared_param_offset + 44)[0] & 128),
        "half_scale_2c44": tex1.half_from_bits(0x2C44),
    }

    cb14_rows = [
        struct.unpack_from("<4f", resource_20, register_index * 16)
        for register_index in (87, 88, 89, 90)
    ]
    cb14_linear = np.array(
        [
            [cb14_rows[0][0], cb14_rows[1][0], cb14_rows[2][0]],
            [cb14_rows[0][1], cb14_rows[1][1], cb14_rows[2][1]],
            [cb14_rows[0][3], cb14_rows[1][3], cb14_rows[2][3]],
        ],
        dtype=float,
    )
    cb14_translation = np.array([cb14_rows[3][0], cb14_rows[3][1], cb14_rows[3][3]], dtype=float)
    cb14_inverse = np.linalg.inv(cb14_linear)

    wing_name, wing_command_index, wing_gpu_id, wing_vertex_count = tex1.SHADOW_SUBMESHES[4]
    wing_constant = tex1.load_indirect_constant(wing_command_index, resource_7968)
    wing_record = tex1.load_draw_record(wing_constant, resource_7879)
    wing_param_index, _handle, wing_base_vertex, _aux_handle, _aux_base, _control, _flags = wing_record

    bbox_offset = wing_param_index * tex1.STRIDE_242
    bbox_min = struct.unpack_from("<3f", resource_242, bbox_offset + 0)
    bbox_dim = struct.unpack_from("<3f", resource_242, bbox_offset + 16)
    pix_world = tex1.load_pix_world_positions(GPU_ANALYSIS / f"2026_3_30__9_24_50_{wing_gpu_id}_VS_BufferData_exp0.csv")

    block_0 = load_space15_block(resource_80, shared["cluster_index"], 0)
    block_64 = load_space15_block(resource_80, shared["cluster_index"], 64)

    exact_errors: list[float] = []
    exact_errors_z_pos: list[float] = []
    exact_errors_z_neg: list[float] = []
    pre_cb14_errors_block0: list[float] = []
    pre_cb14_errors_block64: list[float] = []
    pre_cb14_errors_block64_z_pos: list[float] = []
    pre_cb14_errors_block64_z_neg: list[float] = []

    stage1_points: list[np.ndarray] = []
    target_pre_cb14: list[np.ndarray] = []
    local_positions: list[np.ndarray] = []

    for local_index in range(wing_vertex_count):
        runtime_offset = (tex1.RUNTIME_VIEW_FIRST_ELEMENT + wing_base_vertex + local_index) * tex1.VERTEX_STRIDE
        runtime_raw = resource_16288[runtime_offset : runtime_offset + tex1.VERTEX_STRIDE]

        local_pos = np.array(tex1.dequantize_runtime_pos(runtime_raw, bbox_min, bbox_dim), dtype=float)
        codes, weights = tex1.decode_runtime_codes_weights(runtime_raw)
        total_weight = sum(weight for weight in weights if weight > 0)
        if total_weight <= 0:
            continue

        accum_m0 = [[0.0, 0.0, 0.0, 0.0] for _ in range(4)]
        accum_m1 = [[0.0, 0.0, 0.0, 0.0] for _ in range(4)]
        for code, weight in zip(codes, weights):
            if weight <= 0:
                continue
            lookup0 = tex1.load_u32(resource_147, shared["base0"] + code)
            lookup1 = tex1.load_u32(resource_2085, shared["base_lookup"] + lookup0)
            matrix0 = tex1.load_matrix4x4(resource_135, shared["base_m0"] + lookup1)
            matrix1 = tex1.load_matrix4x4(resource_135, shared["base_m1"] + lookup1)
            factor = weight / total_weight
            for row in range(4):
                for col in range(4):
                    accum_m0[row][col] += matrix0[row][col] * factor
                    accum_m1[row][col] += matrix1[row][col] * factor

        packed_word = struct.unpack_from("<I", runtime_raw, 36)[0] >> 16
        packed_factor = float(packed_word & 0xF) * shared["half_scale_2c44"]
        blend = 1.0 - packed_factor
        blended_matrix = tuple(
            tuple(accum_m0[row][col] + (accum_m1[row][col] - accum_m0[row][col]) * blend for col in range(4))
            for row in range(4)
        )

        stage1 = np.array(tex1.apply_matrix_3x4(blended_matrix, tuple(local_pos)), dtype=float)
        world_truth = np.array(pix_world[local_index], dtype=float)
        target_pre = cb14_inverse @ (world_truth - cb14_translation)

        pred_pre_0 = apply_space15_affine(block_0, stage1)
        pred_pre_64 = apply_space15_affine(block_64, stage1)

        pred_world_64 = np.array(tex1.apply_cb14_block(tuple(cb14_rows), tuple(pred_pre_64)), dtype=float)

        exact_error = float(np.linalg.norm(pred_world_64 - world_truth))
        error_pre_0 = float(np.linalg.norm(pred_pre_0 - target_pre))
        error_pre_64 = float(np.linalg.norm(pred_pre_64 - target_pre))

        exact_errors.append(exact_error)
        pre_cb14_errors_block0.append(error_pre_0)
        pre_cb14_errors_block64.append(error_pre_64)
        stage1_points.append(stage1)
        target_pre_cb14.append(target_pre)
        local_positions.append(local_pos)

        if local_pos[2] > 0.0:
            exact_errors_z_pos.append(exact_error)
            pre_cb14_errors_block64_z_pos.append(error_pre_64)
        else:
            exact_errors_z_neg.append(exact_error)
            pre_cb14_errors_block64_z_neg.append(error_pre_64)

    stage1_array = np.stack(stage1_points)
    target_array = np.stack(target_pre_cb14)

    resource80_entry_count = len(resource_80) // 272
    candidate_scores_64: list[tuple[float, int]] = []
    candidate_scores_0: list[tuple[float, int]] = []

    for entry_index in range(resource80_entry_count):
        for base_offset, sink in ((0, candidate_scores_0), (64, candidate_scores_64)):
            block = load_space15_block(resource_80, entry_index, base_offset)
            predicted = np.stack([apply_space15_affine(block, point) for point in stage1_array])
            error = predicted - target_array
            rmse = float(np.sqrt(np.mean(np.sum(error * error, axis=1))))
            sink.append((rmse, entry_index))

    candidate_scores_0.sort()
    candidate_scores_64.sort()

    report = {
        "shared": shared,
        "wing_draw_record": wing_record,
        "exact_error": asdict(compute_error_stats(exact_errors)),
        "exact_split": [
            asdict(SplitStats("local_z>0", len(exact_errors_z_pos), compute_error_stats(exact_errors_z_pos))),
            asdict(SplitStats("local_z<=0", len(exact_errors_z_neg), compute_error_stats(exact_errors_z_neg))),
        ],
        "pre_cb14_block0": asdict(compute_error_stats(pre_cb14_errors_block0)),
        "pre_cb14_block64": asdict(compute_error_stats(pre_cb14_errors_block64)),
        "pre_cb14_split": [
            asdict(SplitStats("block64 local_z>0", len(pre_cb14_errors_block64_z_pos), compute_error_stats(pre_cb14_errors_block64_z_pos))),
            asdict(SplitStats("block64 local_z<=0", len(pre_cb14_errors_block64_z_neg), compute_error_stats(pre_cb14_errors_block64_z_neg))),
        ],
        "best_resource80_candidates": {
            "base_0": candidate_scores_0[:10],
            "base_64": candidate_scores_64[:10],
        },
    }

    OUT_MANIFEST.write_text(json.dumps(report, indent=2), encoding="utf-8")

    lines = [
        "6804 Wing Probe",
        "===============",
        "",
        "Shared config",
        "-------------",
        f"base0        : {shared['base0']}",
        f"base_lookup  : {shared['base_lookup']}",
        f"base_m0      : {shared['base_m0']}",
        f"base_m1      : {shared['base_m1']}",
        f"cluster_idx  : {shared['cluster_index']}",
        "",
        "Exact world-space error using the current proven path",
        "----------------------------------------------------",
        f"all          : rmse {compute_error_stats(exact_errors).rmse:.9f}, avg {compute_error_stats(exact_errors).avg:.9f}, max {compute_error_stats(exact_errors).max:.9f}",
        f"local_z > 0  : rmse {compute_error_stats(exact_errors_z_pos).rmse:.9f}, avg {compute_error_stats(exact_errors_z_pos).avg:.9f}, max {compute_error_stats(exact_errors_z_pos).max:.9f}",
        f"local_z <= 0 : rmse {compute_error_stats(exact_errors_z_neg).rmse:.9f}, avg {compute_error_stats(exact_errors_z_neg).avg:.9f}, max {compute_error_stats(exact_errors_z_neg).max:.9f}",
        "",
        "Recovered pre-cb14 target comparison",
        "------------------------------------",
        f"block 0..48  : rmse {compute_error_stats(pre_cb14_errors_block0).rmse:.9f}, avg {compute_error_stats(pre_cb14_errors_block0).avg:.9f}, max {compute_error_stats(pre_cb14_errors_block0).max:.9f}",
        f"block 64..112: rmse {compute_error_stats(pre_cb14_errors_block64).rmse:.9f}, avg {compute_error_stats(pre_cb14_errors_block64).avg:.9f}, max {compute_error_stats(pre_cb14_errors_block64).max:.9f}",
        f"block64 z>0  : rmse {compute_error_stats(pre_cb14_errors_block64_z_pos).rmse:.9f}, avg {compute_error_stats(pre_cb14_errors_block64_z_pos).avg:.9f}, max {compute_error_stats(pre_cb14_errors_block64_z_pos).max:.9f}",
        f"block64 z<=0 : rmse {compute_error_stats(pre_cb14_errors_block64_z_neg).rmse:.9f}, avg {compute_error_stats(pre_cb14_errors_block64_z_neg).avg:.9f}, max {compute_error_stats(pre_cb14_errors_block64_z_neg).max:.9f}",
        "",
        "Best resource_80 candidates against pre-cb14 target",
        "---------------------------------------------------",
        "base 0 candidates:",
    ]
    lines.extend([f"  entry {entry:3d}: rmse {rmse:.9f}" for rmse, entry in candidate_scores_0[:10]])
    lines.append("base 64 candidates:")
    lines.extend([f"  entry {entry:3d}: rmse {rmse:.9f}" for rmse, entry in candidate_scores_64[:10]])
    lines.extend(
        [
            "",
            "Interpretation",
            "--------------",
            "- The wing miss is concentrated in the local_z > 0 half.",
            "- The miss already exists before cb14, so cb14 is not the main culprit.",
            "- resource_80 entry 78 remains the best candidate for both obvious block offsets.",
            "- No alternative resource_80 element comes close, so the remaining issue is likely",
            "  a late branch or selector inside the proven wing path, not a wrong element lookup.",
        ]
    )
    OUT_REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
