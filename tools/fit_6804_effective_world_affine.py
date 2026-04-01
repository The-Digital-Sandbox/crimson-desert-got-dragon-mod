#!/usr/bin/env python3
"""Fit the effective shared late-world affine for the proven 6804 shadow path.

This sits one stage later than ``trace_6804_late_position_probe.py``.

What it does:
- rebuild the proven late shadow position for all six 6804 dragon submeshes
- fit a single shared affine ``late_pos -> PIX TEXCOORD1`` across the whole dragon
- report exact-path RMSE, translation-only RMSE, and full-affine RMSE

Why it matters:
- if a single shared affine explains the remaining miss well, the blocker is no
  longer "hidden per-vertex shader logic"
- it gives us an effective downstream model we can reuse while the exact live
  provenance of the final space15/cb14 constants is still being verified
"""

from __future__ import annotations

import csv
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

import trace_6804_late_position_probe as late_probe
import trace_6804_texcoord1_path as tex1


ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "output"
GPU_ANALYSIS = ROOT / "gpu-analysis"

OUT_DIR = OUTPUT / "shadow_6804_effective_affine"
OUT_REPORT = OUT_DIR / "report.txt"
OUT_MANIFEST = OUT_DIR / "manifest.json"
OUT_WORST = OUT_DIR / "worst_vertices.csv"


@dataclass(frozen=True)
class ErrorStats:
    rmse: float
    avg: float
    max: float


@dataclass(frozen=True)
class WorstVertex:
    submesh: str
    gpu_id: str
    vertex_id: int
    error_exact: float
    error_translation_only: float
    error_affine: float
    late_pos: tuple[float, float, float]
    pix_world: tuple[float, float, float]


@dataclass(frozen=True)
class SubmeshReport:
    name: str
    gpu_id: str
    vertex_count: int
    exact_error: ErrorStats
    translation_only_error: ErrorStats
    affine_error: ErrorStats


def compute_error_stats(errors: list[float]) -> ErrorStats:
    if not errors:
        return ErrorStats(rmse=0.0, avg=0.0, max=0.0)
    return ErrorStats(
        rmse=math.sqrt(sum(value * value for value in errors) / len(errors)),
        avg=sum(errors) / len(errors),
        max=max(errors),
    )


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    resource_242 = late_probe.RESOURCE_242.read_bytes()
    resource_7879 = late_probe.RESOURCE_7879.read_bytes()
    resource_7968 = late_probe.RESOURCE_7968.read_bytes()
    resource_16288 = late_probe.RESOURCE_16288.read_bytes()
    resource_147 = late_probe.RESOURCE_147.read_bytes()
    resource_2085 = late_probe.RESOURCE_2085.read_bytes()
    resource_2070 = late_probe.RESOURCE_2070.read_bytes()
    resource_80 = late_probe.RESOURCE_80.read_bytes()
    resource_20 = late_probe.RESOURCE_20.read_bytes()

    shared_constant = tex1.load_indirect_constant(tex1.SHADOW_SUBMESHES[0][1], resource_7968)
    shared_record = tex1.load_draw_record(shared_constant, resource_7879)
    shared_param_offset = shared_record[0] * tex1.STRIDE_242
    shared_config = late_probe.SharedConfig(
        base0=int.from_bytes(resource_242[shared_param_offset + 48 : shared_param_offset + 52], "little"),
        base_lookup=int.from_bytes(resource_242[shared_param_offset + 104 : shared_param_offset + 108], "little"),
        base_late_matrix=int.from_bytes(resource_242[shared_param_offset + 56 : shared_param_offset + 60], "little"),
        cluster_index=int.from_bytes(resource_242[shared_param_offset + 96 : shared_param_offset + 100], "little") & 0xFFFF,
        u64_word=int.from_bytes(resource_242[shared_param_offset + 64 : shared_param_offset + 68], "little"),
        u64_lt_2pow30=int.from_bytes(resource_242[shared_param_offset + 64 : shared_param_offset + 68], "little") < 1073741824,
    )

    block_64 = late_probe.load_space15_block(resource_80, shared_config.cluster_index, 64)
    cb14_block = (
        tuple(np.frombuffer(resource_20[87 * 16 : 87 * 16 + 16], dtype="<f4")),
        tuple(np.frombuffer(resource_20[88 * 16 : 88 * 16 + 16], dtype="<f4")),
        tuple(np.frombuffer(resource_20[89 * 16 : 89 * 16 + 16], dtype="<f4")),
        tuple(np.frombuffer(resource_20[90 * 16 : 90 * 16 + 16], dtype="<f4")),
    )

    rows: list[list[float]] = []
    truths: list[list[float]] = []
    vertex_rows: list[tuple[str, str, int, tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]]] = []

    per_submesh_exact: dict[str, list[float]] = {}

    for submesh_name, command_index, gpu_id, vertex_count in tex1.SHADOW_SUBMESHES:
        constant0 = tex1.load_indirect_constant(command_index, resource_7968)
        draw_record = tex1.load_draw_record(constant0, resource_7879)
        parameter_index, _handle, base_vertex, _aux_handle, _aux_base, _control, _flags = draw_record
        bbox_offset = parameter_index * tex1.STRIDE_242
        bbox_min = tuple(np.frombuffer(resource_242[bbox_offset + 0 : bbox_offset + 12], dtype="<f4"))
        bbox_dim = tuple(np.frombuffer(resource_242[bbox_offset + 16 : bbox_offset + 28], dtype="<f4"))
        pix_rows = tex1.load_pix_world_positions(GPU_ANALYSIS / f"2026_3_30__9_24_50_{gpu_id}_VS_BufferData_exp0.csv")

        exact_errors = per_submesh_exact.setdefault(submesh_name, [])

        for local_index in range(vertex_count):
            raw40 = resource_16288[
                (tex1.RUNTIME_VIEW_FIRST_ELEMENT + base_vertex + local_index) * tex1.VERTEX_STRIDE :
                (tex1.RUNTIME_VIEW_FIRST_ELEMENT + base_vertex + local_index + 1) * tex1.VERTEX_STRIDE
            ]
            local_pos = tex1.dequantize_runtime_pos(raw40, bbox_min, bbox_dim)
            late_matrix = late_probe.accumulate_late_matrix(
                raw40=raw40,
                resource_147=resource_147,
                resource_2085=resource_2085,
                resource_2070=resource_2070,
                base0=shared_config.base0,
                base_lookup=shared_config.base_lookup,
                base_late_matrix=shared_config.base_late_matrix,
            )
            late_pos = late_probe.apply_late_position(late_matrix, local_pos)
            exact_world = tex1.apply_cb14_block(cb14_block, tex1.apply_space15_block(block_64, late_pos))
            pix_world = pix_rows[local_index]

            exact_errors.append(math.dist(exact_world, pix_world))
            rows.append([late_pos[0], late_pos[1], late_pos[2], 1.0])
            truths.append([pix_world[0], pix_world[1], pix_world[2]])
            vertex_rows.append((submesh_name, gpu_id, local_index, local_pos, late_pos, pix_world))

    row_array = np.asarray(rows, dtype=float)
    truth_array = np.asarray(truths, dtype=float)

    affine_solution, _, _, _ = np.linalg.lstsq(row_array, truth_array, rcond=None)
    predicted_affine = row_array @ affine_solution

    translation_only = truth_array - np.asarray(
        [
            tex1.apply_cb14_block(cb14_block, tex1.apply_space15_block(block_64, late_pos))
            for _, _, _, _, late_pos, _ in vertex_rows
        ],
        dtype=float,
    )
    translation_delta = translation_only.mean(axis=0)
    predicted_exact = truth_array - translation_only
    predicted_translation_only = predicted_exact + translation_delta

    submesh_reports: list[SubmeshReport] = []
    worst_vertices: list[WorstVertex] = []

    for submesh_name, _command_index, gpu_id, vertex_count in tex1.SHADOW_SUBMESHES:
        exact_errors: list[float] = []
        translation_errors: list[float] = []
        affine_errors: list[float] = []

        base = sum(count for name, _, _, count in tex1.SHADOW_SUBMESHES if name < submesh_name)
        # Keep stable explicit ordering instead of relying on lexical tuple ordering.
        base = 0
        for name, _cmd, _gid, count in tex1.SHADOW_SUBMESHES:
            if name == submesh_name:
                break
            base += count

        for local_index in range(vertex_count):
            global_index = base + local_index
            pix_world = tuple(truth_array[global_index])
            exact_world = tuple(predicted_exact[global_index])
            trans_world = tuple(predicted_translation_only[global_index])
            affine_world = tuple(predicted_affine[global_index])
            _name, _gid, _vid, _local_pos, late_pos, _pix = vertex_rows[global_index]

            error_exact = math.dist(exact_world, pix_world)
            error_translation = math.dist(trans_world, pix_world)
            error_affine = math.dist(affine_world, pix_world)

            exact_errors.append(error_exact)
            translation_errors.append(error_translation)
            affine_errors.append(error_affine)

            worst_vertices.append(
                WorstVertex(
                    submesh=submesh_name,
                    gpu_id=gpu_id,
                    vertex_id=local_index,
                    error_exact=error_exact,
                    error_translation_only=error_translation,
                    error_affine=error_affine,
                    late_pos=tuple(float(v) for v in late_pos),
                    pix_world=tuple(float(v) for v in pix_world),
                )
            )

        submesh_reports.append(
            SubmeshReport(
                name=submesh_name,
                gpu_id=gpu_id,
                vertex_count=vertex_count,
                exact_error=compute_error_stats(exact_errors),
                translation_only_error=compute_error_stats(translation_errors),
                affine_error=compute_error_stats(affine_errors),
            )
        )

    worst_vertices.sort(key=lambda row: row.error_affine, reverse=True)

    with OUT_WORST.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "submesh",
                "gpu_id",
                "vertex_id",
                "error_exact",
                "error_translation_only",
                "error_affine",
                "late_x",
                "late_y",
                "late_z",
                "pix_x",
                "pix_y",
                "pix_z",
            ]
        )
        for row in worst_vertices[:200]:
            writer.writerow(
                [
                    row.submesh,
                    row.gpu_id,
                    row.vertex_id,
                    f"{row.error_exact:.9f}",
                    f"{row.error_translation_only:.9f}",
                    f"{row.error_affine:.9f}",
                    f"{row.late_pos[0]:.9f}",
                    f"{row.late_pos[1]:.9f}",
                    f"{row.late_pos[2]:.9f}",
                    f"{row.pix_world[0]:.9f}",
                    f"{row.pix_world[1]:.9f}",
                    f"{row.pix_world[2]:.9f}",
                ]
            )

    overall_exact = compute_error_stats([row.error_exact for row in worst_vertices])
    overall_translation = compute_error_stats([row.error_translation_only for row in worst_vertices])
    overall_affine = compute_error_stats([row.error_affine for row in worst_vertices])

    report_lines = [
        "6804 effective late-world affine fit",
        "===================================",
        "",
        "Interpretation",
        "--------------",
        "- This fitter starts after the proven late resource_2070 shadow matrix stage.",
        "- It treats everything downstream as one shared affine late_pos -> PIX TEXCOORD1.",
        "- If that affine fits well, the remaining mismatch is a shared state/provenance issue,",
        "  not hidden per-vertex shader logic.",
        "",
        "Shared translation-only delta",
        "-----------------------------",
        f"delta_x: {translation_delta[0]:.9f}",
        f"delta_y: {translation_delta[1]:.9f}",
        f"delta_z: {translation_delta[2]:.9f}",
        "",
        "Best-fit affine",
        "---------------",
    ]
    for row_index in range(4):
        report_lines.append(
            "  "
            + " ".join(
                f"{float(affine_solution[row_index, col]): .9f}" for col in range(3)
            )
        )
    report_lines.extend(
        [
            "",
            "Overall error",
            "-------------",
            f"exact rmse            : {overall_exact.rmse:.9f}",
            f"translation-only rmse : {overall_translation.rmse:.9f}",
            f"full-affine rmse      : {overall_affine.rmse:.9f}",
            "",
            "Per-submesh",
            "-----------",
        ]
    )
    for submesh in submesh_reports:
        report_lines.extend(
            [
                f"{submesh.name} ({submesh.gpu_id})",
                f"  exact rmse            : {submesh.exact_error.rmse:.9f}",
                f"  translation-only rmse : {submesh.translation_only_error.rmse:.9f}",
                f"  full-affine rmse      : {submesh.affine_error.rmse:.9f}",
            ]
        )

    OUT_REPORT.write_text("\n".join(report_lines) + "\n", encoding="utf-8")
    OUT_MANIFEST.write_text(
        json.dumps(
            {
                "translation_delta": [float(value) for value in translation_delta],
                "affine_solution": [[float(value) for value in affine_solution[row]] for row in range(4)],
                "overall_exact_error": asdict(overall_exact),
                "overall_translation_only_error": asdict(overall_translation),
                "overall_affine_error": asdict(overall_affine),
                "submeshes": [asdict(item) for item in submesh_reports],
                "worst_vertices_csv": str(OUT_WORST.relative_to(ROOT)).replace("\\", "/"),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    print(f"wrote {OUT_REPORT}")
    print(f"wrote {OUT_MANIFEST}")
    print(f"wrote {OUT_WORST}")


if __name__ == "__main__":
    main()
