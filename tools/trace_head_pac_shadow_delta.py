#!/usr/bin/env python3
"""Trace the PAC -> runtime shadow delta on the head submesh only.

This uses the now-proven PAC/runtime bridge:

- same head submesh bbox
- same head triangle list
- same head local vertex order

The goal is not to solve the whole dragon in one step. It is to answer a
smaller question cleanly:

How "skinning-like" is the PAC -> runtime-shadow position change on the head?

The tracer:

- writes a paired per-vertex CSV for the head
- fits one global affine PAC->runtime transform
- fits affine transforms per exact visible PAC signature
- fits affine transforms per dominant PAC code for single-weight vertices

If those grouped fits are materially better than the global fit, that supports
the model that runtime shadow is a bone/cluster driven transform of PAC
storage, not an unrelated mesh rewrite.
"""

from __future__ import annotations

import csv
import json
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
OUT_DIR = OUTPUT / "head_pac_shadow_delta"

PAC_PATH = OUTPUT / "dragon.pac"
RESOURCE_242 = PIX_RESOURCES / "resource_242.bin"
RESOURCE_16288 = PIX_RESOURCES / "resource_16288.bin"

VERTEX_STRIDE = 40
RUNTIME_VIEW_FIRST_ELEMENT = 46222
HEAD_PARAMETER_INDEX = 120
HEAD_RUNTIME_BASE_VERTEX = 19854
HEAD_NAME = "Head"


@dataclass(frozen=True)
class FitSummary:
    label: str
    count: int
    rmse: float
    max_error: float


@dataclass(frozen=True)
class HeadTraceSummary:
    vertex_count: int
    global_fit: FitSummary
    single_weight_vertex_count: int
    top_signature_fits: list[FitSummary]
    top_code_fits: list[FitSummary]
    csv_path: str


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


def fit_affine(pac_points: list[tuple[float, float, float]], runtime_points: list[tuple[float, float, float]]) -> FitSummary:
    X = np.array([list(point) + [1.0] for point in pac_points], dtype=float)
    Y = np.array(runtime_points, dtype=float)
    transform, _residuals, _rank, _s = np.linalg.lstsq(X, Y, rcond=None)
    predicted = X @ transform
    errors = np.linalg.norm(predicted - Y, axis=1)
    return FitSummary(
        label="",
        count=len(pac_points),
        rmse=float(np.sqrt(np.mean(errors * errors))),
        max_error=float(errors.max()),
    )


def format_signature(code_tuple: tuple[int, int, int, int], weight_tuple: tuple[int, int, int, int]) -> str:
    return f"codes={code_tuple} weights={weight_tuple}"


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    pac_bytes = PAC_PATH.read_bytes()
    runtime_bytes = RESOURCE_16288.read_bytes()
    resource_242 = RESOURCE_242.read_bytes()

    head_index = pac_codec.SUBMESH_NAMES.index(HEAD_NAME)
    head_base = pac_codec.SUBMESH_BASES[head_index]
    head_count = pac_codec.SUBMESH_VERTEX_COUNTS[head_index]
    head_bbox = pac_codec.parse_submesh_descriptors(pac_bytes)[head_index]

    runtime_bbox_min = struct.unpack_from("<3f", resource_242, HEAD_PARAMETER_INDEX * 156 + 0)
    runtime_bbox_dim = struct.unpack_from("<3f", resource_242, HEAD_PARAMETER_INDEX * 156 + 16)
    runtime_head_base = RUNTIME_VIEW_FIRST_ELEMENT + HEAD_RUNTIME_BASE_VERTEX

    csv_path = OUT_DIR / "head_pairs.csv"

    all_pac_points: list[tuple[float, float, float]] = []
    all_runtime_points: list[tuple[float, float, float]] = []
    signature_points: dict[tuple[tuple[int, int, int, int], tuple[int, int, int, int]], tuple[list[tuple[float, float, float]], list[tuple[float, float, float]]]] = defaultdict(
        lambda: ([], [])
    )
    dominant_code_points: dict[int, tuple[list[tuple[float, float, float]], list[tuple[float, float, float]]]] = defaultdict(lambda: ([], []))
    single_weight_vertex_count = 0

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
                "delta_x",
                "delta_y",
                "delta_z",
                "delta_len",
                "bone_idx",
                "bone_wt",
                "extra0_hex",
                "extra1_hex",
                "uv1_raw",
                "pac_raw40_hex",
                "runtime_raw40_hex",
            ]
        )

        for local_index in range(head_count):
            pac_vertex_index = head_base + local_index
            runtime_vertex_index = runtime_head_base + local_index

            pac_vertex = pac_codec.decode_vertex(pac_bytes, pac_vertex_index, head_bbox)
            runtime_raw40 = runtime_bytes[runtime_vertex_index * VERTEX_STRIDE : (runtime_vertex_index + 1) * VERTEX_STRIDE]
            pac_raw40 = pac_bytes[
                pac_codec.VB_START + pac_vertex_index * VERTEX_STRIDE : pac_codec.VB_START + (pac_vertex_index + 1) * VERTEX_STRIDE
            ]
            runtime_pos = dequantize_runtime_pos(runtime_raw40, runtime_bbox_min, runtime_bbox_dim)

            delta = (
                runtime_pos[0] - pac_vertex.pos[0],
                runtime_pos[1] - pac_vertex.pos[1],
                runtime_pos[2] - pac_vertex.pos[2],
            )
            delta_len = float(np.linalg.norm(np.array(delta, dtype=float)))

            code_tuple = tuple(pac_vertex.bone_idx)
            weight_tuple = tuple(pac_vertex.bone_wt)
            signature = (code_tuple, weight_tuple)

            all_pac_points.append(pac_vertex.pos)
            all_runtime_points.append(runtime_pos)
            signature_points[signature][0].append(pac_vertex.pos)
            signature_points[signature][1].append(runtime_pos)

            if weight_tuple[0] == 255 and weight_tuple[1:] == (0, 0, 0):
                single_weight_vertex_count += 1
                dominant_code_points[code_tuple[0]][0].append(pac_vertex.pos)
                dominant_code_points[code_tuple[0]][1].append(runtime_pos)

            writer.writerow(
                [
                    local_index,
                    pac_vertex_index,
                    runtime_vertex_index,
                    f"{pac_vertex.pos[0]:.9f}",
                    f"{pac_vertex.pos[1]:.9f}",
                    f"{pac_vertex.pos[2]:.9f}",
                    f"{runtime_pos[0]:.9f}",
                    f"{runtime_pos[1]:.9f}",
                    f"{runtime_pos[2]:.9f}",
                    f"{delta[0]:.9f}",
                    f"{delta[1]:.9f}",
                    f"{delta[2]:.9f}",
                    f"{delta_len:.9f}",
                    code_tuple,
                    weight_tuple,
                    pac_vertex.extra0.hex(),
                    pac_vertex.extra1.hex(),
                    pac_vertex.uv1_raw,
                    pac_raw40.hex(),
                    runtime_raw40.hex(),
                ]
            )

    global_fit = fit_affine(all_pac_points, all_runtime_points)
    global_fit = FitSummary(label="global_head_affine", count=global_fit.count, rmse=global_fit.rmse, max_error=global_fit.max_error)

    top_signature_fits: list[FitSummary] = []
    signature_counts = Counter({signature: len(points[0]) for signature, points in signature_points.items()})
    for signature, count in signature_counts.most_common(20):
        if count < 4:
            continue
        pac_points, runtime_points = signature_points[signature]
        fit = fit_affine(pac_points, runtime_points)
        top_signature_fits.append(
            FitSummary(
                label=format_signature(signature[0], signature[1]),
                count=fit.count,
                rmse=fit.rmse,
                max_error=fit.max_error,
            )
        )

    top_code_fits: list[FitSummary] = []
    code_counts = Counter({code: len(points[0]) for code, points in dominant_code_points.items()})
    for code, count in code_counts.most_common(20):
        if count < 4:
            continue
        pac_points, runtime_points = dominant_code_points[code]
        fit = fit_affine(pac_points, runtime_points)
        top_code_fits.append(
            FitSummary(
                label=f"dominant_code={code} single_weight_only",
                count=fit.count,
                rmse=fit.rmse,
                max_error=fit.max_error,
            )
        )

    summary = HeadTraceSummary(
        vertex_count=head_count,
        global_fit=global_fit,
        single_weight_vertex_count=single_weight_vertex_count,
        top_signature_fits=top_signature_fits,
        top_code_fits=top_code_fits,
        csv_path=str(csv_path),
    )

    report_path = OUT_DIR / "report.txt"
    with report_path.open("w", encoding="ascii", newline="\n") as handle:
        handle.write("Head PAC -> runtime shadow delta trace\n")
        handle.write("=====================================\n\n")
        handle.write(f"vertex_count:             {summary.vertex_count}\n")
        handle.write(f"single_weight_vertex_count: {summary.single_weight_vertex_count}\n")
        handle.write(
            f"global_fit:               rmse={summary.global_fit.rmse:.6f} max={summary.global_fit.max_error:.6f}\n\n"
        )
        handle.write("Top signature fits\n")
        handle.write("------------------\n")
        for fit in summary.top_signature_fits:
            handle.write(f"{fit.count:5d}  rmse={fit.rmse:.6f} max={fit.max_error:.6f}  {fit.label}\n")
        handle.write("\nTop dominant-code fits (single-weight only)\n")
        handle.write("-------------------------------------------\n")
        for fit in summary.top_code_fits:
            handle.write(f"{fit.count:5d}  rmse={fit.rmse:.6f} max={fit.max_error:.6f}  {fit.label}\n")
        handle.write(f"\ncsv_path: {summary.csv_path}\n")

    manifest_path = OUT_DIR / "manifest.json"
    manifest_path.write_text(json.dumps(asdict(summary), indent=2), encoding="ascii")

    print(report_path)
    print(
        f"global affine rmse={summary.global_fit.rmse:.4f} max={summary.global_fit.max_error:.4f} "
        f"single_weight={summary.single_weight_vertex_count}/{summary.vertex_count}"
    )
    if summary.top_signature_fits:
        best = summary.top_signature_fits[0]
        print(f"top signature: count={best.count} rmse={best.rmse:.4f} max={best.max_error:.4f} {best.label}")
    if summary.top_code_fits:
        best = summary.top_code_fits[0]
        print(f"top code: count={best.count} rmse={best.rmse:.4f} max={best.max_error:.4f} {best.label}")


if __name__ == "__main__":
    main()
