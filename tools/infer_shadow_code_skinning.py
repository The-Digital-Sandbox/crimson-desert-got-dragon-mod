#!/usr/bin/env python3
"""Infer whether visible PAC codes behave like a skinning contract.

This script stays on the proven PAC <-> runtime-shadow bridge:

- PAC submesh order, bases, bboxes, and local triangle lists are authoritative
- runtime shadow vertex cache lives in resource_16288
- local vertex order matches between PAC and runtime shadow for the six dragon draws

The question here is narrower:

Can the visible PAC code/weight tuples explain the runtime-shadow positions
using code-specific affine transforms learned only from single-weight vertices?

If yes, the missing crack is much more likely to be code->matrix indirection
than arbitrary per-vertex topology rewrite.
"""

from __future__ import annotations

import json
import math
import struct
import sys
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import pac_codec


OUTPUT = ROOT / "output"
PIX_RESOURCES = OUTPUT / "pix_resources"
OUT_DIR = OUTPUT / "shadow_code_skinning"

PAC_PATH = OUTPUT / "dragon.pac"
RESOURCE_242 = PIX_RESOURCES / "resource_242.bin"
RESOURCE_7879 = PIX_RESOURCES / "resource_7879.bin"
RESOURCE_7968 = PIX_RESOURCES / "resource_7968.bin"
RESOURCE_16288 = PIX_RESOURCES / "resource_16288.bin"

STRIDE_242 = 156
STRIDE_7879 = 28
STRIDE_7968 = 40
VERTEX_STRIDE = 40
RUNTIME_VIEW_FIRST_ELEMENT = 46222

SHADOW_SUBMESHES = [
    ("Body_02", 145),
    ("back", 146),
    ("Body", 147),
    ("Leg", 148),
    ("Wing", 149),
    ("Head", 150),
]


@dataclass(frozen=True)
class IndirectRecord:
    command_index: int
    constant0: int
    base_vertex: int


@dataclass(frozen=True)
class VertexPair:
    submesh: str
    local_index: int
    pac_vertex_index: int
    runtime_vertex_index: int
    pac_pos: tuple[float, float, float]
    runtime_pos: tuple[float, float, float]
    bone_idx: tuple[int, int, int, int]
    bone_wt: tuple[int, int, int, int]


@dataclass(frozen=True)
class FitStats:
    count: int
    rmse: float
    avg_error: float
    max_error: float


@dataclass(frozen=True)
class CodeTransformSummary:
    code: int
    single_weight_vertices: int
    fit: FitStats


@dataclass(frozen=True)
class PredictionSummary:
    label: str
    coverage_count: int
    coverage_ratio: float
    fit: FitStats
    per_submesh_rmse: dict[str, float]


def build_code_transform_map(
    single_weight_pairs: list[VertexPair],
    key_fn,
) -> tuple[dict[object, np.ndarray], list[tuple[object, int, FitStats]]]:
    counts = Counter(key_fn(pair) for pair in single_weight_pairs)
    transforms: dict[object, np.ndarray] = {}
    summaries: list[tuple[object, int, FitStats]] = []
    for key, count in counts.most_common():
        if count < 4:
            continue
        subset = [pair for pair in single_weight_pairs if key_fn(pair) == key]
        transform, fit = fit_affine_transform(
            [pair.pac_pos for pair in subset],
            [pair.runtime_pos for pair in subset],
        )
        transforms[key] = transform
        summaries.append((key, count, fit))
    return transforms, summaries


def build_predictions(
    pairs: list[VertexPair],
    transforms: dict[object, np.ndarray],
    key_builder,
) -> dict[tuple[str, int], np.ndarray]:
    predictions: dict[tuple[str, int], np.ndarray] = {}
    for pair in pairs:
        weighted_points: list[tuple[int, np.ndarray]] = []
        for code, weight in zip(pair.bone_idx, pair.bone_wt):
            if weight <= 0:
                continue
            transform = transforms.get(key_builder(pair, code))
            if transform is None:
                break
            weighted_points.append((weight, apply_transform(transform, pair.pac_pos)))
        else:
            if weighted_points:
                weight_sum = sum(weight for weight, _predicted in weighted_points)
                blended = sum(weight * predicted for weight, predicted in weighted_points) / weight_sum
                predictions[(pair.submesh, pair.local_index)] = blended
    return predictions


def load_indirect_record(command_index: int, resource_7968: bytes) -> IndirectRecord:
    offset = command_index * STRIDE_7968
    constant0 = struct.unpack_from("<I", resource_7968, offset + 16)[0]
    _index_count, _instance_count, _start_index, base_vertex, _start_instance = struct.unpack_from(
        "<IIiII", resource_7968, offset + 20
    )
    return IndirectRecord(command_index=command_index, constant0=constant0, base_vertex=base_vertex)


def load_draw_record(record_index: int, resource_7879: bytes) -> tuple[int, int, int, int, int, int, int]:
    return struct.unpack_from("<7I", resource_7879, record_index * STRIDE_7879)


def read_runtime_bbox(parameter_index: int, resource_242: bytes) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    offset = parameter_index * STRIDE_242
    bbox_min = struct.unpack_from("<3f", resource_242, offset + 0)
    bbox_dim = struct.unpack_from("<3f", resource_242, offset + 16)
    return bbox_min, bbox_dim


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


def fit_affine_transform(
    pac_points: list[tuple[float, float, float]],
    runtime_points: list[tuple[float, float, float]],
) -> tuple[np.ndarray, FitStats]:
    pac_array = np.array([list(point) + [1.0] for point in pac_points], dtype=float)
    runtime_array = np.array(runtime_points, dtype=float)
    transform, _residuals, _rank, _singular = np.linalg.lstsq(pac_array, runtime_array, rcond=None)
    predicted = pac_array @ transform
    error_vectors = predicted - runtime_array
    error_lengths = np.linalg.norm(error_vectors, axis=1)
    fit = FitStats(
        count=len(pac_points),
        rmse=float(np.sqrt(np.mean(error_lengths * error_lengths))),
        avg_error=float(np.mean(error_lengths)),
        max_error=float(np.max(error_lengths)),
    )
    return transform, fit


def apply_transform(transform: np.ndarray, point: tuple[float, float, float]) -> np.ndarray:
    return np.array([point[0], point[1], point[2], 1.0], dtype=float) @ transform


def build_vertex_pairs() -> list[VertexPair]:
    pac_bytes = PAC_PATH.read_bytes()
    resource_242 = RESOURCE_242.read_bytes()
    resource_7879 = RESOURCE_7879.read_bytes()
    resource_7968 = RESOURCE_7968.read_bytes()
    runtime_bytes = RESOURCE_16288.read_bytes()
    bboxes_by_name = {bbox.name: bbox for bbox in pac_codec.parse_submesh_descriptors(pac_bytes)}

    pairs: list[VertexPair] = []
    for submesh_name, command_index in SHADOW_SUBMESHES:
        live_record = load_indirect_record(command_index, resource_7968)
        draw_record = load_draw_record(live_record.constant0, resource_7879)
        parameter_index = draw_record[0]
        runtime_bbox_min, runtime_bbox_dim = read_runtime_bbox(parameter_index, resource_242)
        pac_bbox = bboxes_by_name[submesh_name]
        submesh_index = pac_codec.SUBMESH_NAMES.index(submesh_name)
        pac_base = pac_codec.SUBMESH_BASES[submesh_index]
        vertex_count = pac_codec.SUBMESH_VERTEX_COUNTS[submesh_index]
        runtime_base = RUNTIME_VIEW_FIRST_ELEMENT + live_record.base_vertex

        for local_index in range(vertex_count):
            pac_vertex_index = pac_base + local_index
            runtime_vertex_index = runtime_base + local_index
            pac_vertex = pac_codec.decode_vertex(pac_bytes, pac_vertex_index, pac_bbox)
            runtime_raw_offset = runtime_vertex_index * VERTEX_STRIDE
            runtime_raw40 = runtime_bytes[runtime_raw_offset : runtime_raw_offset + VERTEX_STRIDE]
            runtime_pos = dequantize_runtime_pos(runtime_raw40, runtime_bbox_min, runtime_bbox_dim)
            pairs.append(
                VertexPair(
                    submesh=submesh_name,
                    local_index=local_index,
                    pac_vertex_index=pac_vertex_index,
                    runtime_vertex_index=runtime_vertex_index,
                    pac_pos=pac_vertex.pos,
                    runtime_pos=runtime_pos,
                    bone_idx=tuple(pac_vertex.bone_idx),
                    bone_wt=tuple(pac_vertex.bone_wt),
                )
            )
    return pairs


def summarize_prediction(
    label: str,
    predicted_by_pair: dict[tuple[str, int], np.ndarray],
    pairs: list[VertexPair],
) -> PredictionSummary:
    covered_pairs = [pair for pair in pairs if (pair.submesh, pair.local_index) in predicted_by_pair]
    errors: list[float] = []
    per_submesh_errors: dict[str, list[float]] = defaultdict(list)
    for pair in covered_pairs:
        predicted = predicted_by_pair[(pair.submesh, pair.local_index)]
        actual = np.array(pair.runtime_pos, dtype=float)
        error = float(np.linalg.norm(predicted - actual))
        errors.append(error)
        per_submesh_errors[pair.submesh].append(error)

    fit = FitStats(
        count=len(covered_pairs),
        rmse=float(math.sqrt(sum(error * error for error in errors) / len(errors))) if errors else 0.0,
        avg_error=float(sum(errors) / len(errors)) if errors else 0.0,
        max_error=float(max(errors)) if errors else 0.0,
    )
    per_submesh_rmse = {
        submesh: math.sqrt(sum(error * error for error in submesh_errors) / len(submesh_errors))
        for submesh, submesh_errors in per_submesh_errors.items()
    }
    return PredictionSummary(
        label=label,
        coverage_count=len(covered_pairs),
        coverage_ratio=(len(covered_pairs) / len(pairs)) if pairs else 0.0,
        fit=fit,
        per_submesh_rmse=per_submesh_rmse,
    )


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    pairs = build_vertex_pairs()

    all_pac_points = [pair.pac_pos for pair in pairs]
    all_runtime_points = [pair.runtime_pos for pair in pairs]
    _global_transform, global_fit = fit_affine_transform(all_pac_points, all_runtime_points)

    single_weight_pairs = [
        pair for pair in pairs if pair.bone_wt[0] == 255 and pair.bone_wt[1:] == (0, 0, 0)
    ]
    code_transforms, raw_code_summaries = build_code_transform_map(
        single_weight_pairs,
        key_fn=lambda pair: pair.bone_idx[0],
    )
    code_summaries = [
        CodeTransformSummary(code=code, single_weight_vertices=count, fit=fit)
        for code, count, fit in raw_code_summaries
    ]
    strict_predictions = build_predictions(
        pairs,
        code_transforms,
        key_builder=lambda pair, code: code,
    )
    strict_summary = summarize_prediction("global_code_blend", strict_predictions, pairs)

    local_code_transforms, local_code_summaries = build_code_transform_map(
        single_weight_pairs,
        key_fn=lambda pair: (pair.submesh, pair.bone_idx[0]),
    )
    local_code_predictions = build_predictions(
        pairs,
        local_code_transforms,
        key_builder=lambda pair, code: (pair.submesh, code),
    )
    local_code_summary = summarize_prediction("local_code_blend", local_code_predictions, pairs)

    manifest = {
        "vertex_count": len(pairs),
        "single_weight_vertex_count": len(single_weight_pairs),
        "learned_code_count": len(code_transforms),
        "global_affine_fit": asdict(global_fit),
        "global_code_prediction": asdict(strict_summary),
        "local_code_prediction": asdict(local_code_summary),
        "top_codes": [asdict(summary) for summary in code_summaries[:20]],
        "top_local_codes": [
            {
                "submesh": key[0],
                "code": key[1],
                "single_weight_vertices": count,
                "fit": asdict(fit),
            }
            for key, count, fit in local_code_summaries[:20]
        ],
    }

    report_path = OUT_DIR / "report.txt"
    with report_path.open("w", encoding="ascii", newline="\n") as handle:
        handle.write("PAC visible-code -> runtime shadow skinning inference\n")
        handle.write("===============================================\n\n")
        handle.write(f"vertex_count:              {len(pairs)}\n")
        handle.write(f"single_weight_vertices:    {len(single_weight_pairs)}\n")
        handle.write(f"learned_codes:             {len(code_transforms)}\n")
        handle.write("\n")
        handle.write("Global affine baseline (all vertices)\n")
        handle.write("-----------------------------------\n")
        handle.write(f"count:      {global_fit.count}\n")
        handle.write(f"rmse:       {global_fit.rmse:.6f}\n")
        handle.write(f"avg_error:  {global_fit.avg_error:.6f}\n")
        handle.write(f"max_error:  {global_fit.max_error:.6f}\n")
        handle.write("\n")
        handle.write("Global-code weighted prediction\n")
        handle.write("-------------------------------\n")
        handle.write(f"coverage:   {strict_summary.coverage_count} / {len(pairs)} ({strict_summary.coverage_ratio:.2%})\n")
        handle.write(f"rmse:       {strict_summary.fit.rmse:.6f}\n")
        handle.write(f"avg_error:  {strict_summary.fit.avg_error:.6f}\n")
        handle.write(f"max_error:  {strict_summary.fit.max_error:.6f}\n")
        handle.write("per_submesh_rmse:\n")
        for submesh, rmse in strict_summary.per_submesh_rmse.items():
            handle.write(f"  {submesh:8s} {rmse:.6f}\n")
        handle.write("\n")

        handle.write("Submesh-local code weighted prediction\n")
        handle.write("-------------------------------------\n")
        handle.write(f"coverage:   {local_code_summary.coverage_count} / {len(pairs)} ({local_code_summary.coverage_ratio:.2%})\n")
        handle.write(f"rmse:       {local_code_summary.fit.rmse:.6f}\n")
        handle.write(f"avg_error:  {local_code_summary.fit.avg_error:.6f}\n")
        handle.write(f"max_error:  {local_code_summary.fit.max_error:.6f}\n")
        handle.write("per_submesh_rmse:\n")
        for submesh, rmse in local_code_summary.per_submesh_rmse.items():
            handle.write(f"  {submesh:8s} {rmse:.6f}\n")
        handle.write("\n")
        handle.write("Top learned codes from single-weight vertices\n")
        handle.write("--------------------------------------------\n")
        for summary in code_summaries[:20]:
            handle.write(
                f"code={summary.code:3d}  single_weight_vertices={summary.single_weight_vertices:5d}  "
                f"rmse={summary.fit.rmse:.6f}  avg={summary.fit.avg_error:.6f}  max={summary.fit.max_error:.6f}\n"
            )
        handle.write("\n")
        handle.write("Top learned submesh-local codes from single-weight vertices\n")
        handle.write("---------------------------------------------------------\n")
        for key, count, fit in local_code_summaries[:20]:
            handle.write(
                f"submesh={key[0]:8s} code={key[1]:3d}  single_weight_vertices={count:5d}  "
                f"rmse={fit.rmse:.6f}  avg={fit.avg_error:.6f}  max={fit.max_error:.6f}\n"
            )

    (OUT_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="ascii")
    print(f"Wrote {report_path}")
    print(
        "global_rmse={:.6f} global_code_rmse={:.6f} global_code_coverage={}/{} local_code_rmse={:.6f} local_code_coverage={}/{}".format(
            global_fit.rmse,
            strict_summary.fit.rmse,
            strict_summary.coverage_count,
            len(pairs),
            local_code_summary.fit.rmse,
            local_code_summary.coverage_count,
            len(pairs),
        )
    )


if __name__ == "__main__":
    main()
