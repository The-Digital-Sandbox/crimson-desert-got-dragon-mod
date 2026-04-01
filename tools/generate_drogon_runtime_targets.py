#!/usr/bin/env python3
"""Generate Drogon reverse-encode targets in the proven 6804 runtime contract.

This is the first concrete reverse step after cracking the forward dragon path:

1. stay on the proven 6804 shadow-family dragon topology
2. build approximate desired world-space targets from a coarsely aligned Drogon
3. invert the fitted downstream affine ``late_pos -> PIX world``
4. invert each vertex's exact late matrix to recover desired runtime-local coords

This does NOT write PAC yet.
It writes preview meshes and metrics so we can judge whether the reverse side is
coherent before attempting any byte-level writeback.
"""

from __future__ import annotations

import csv
import json
import math
import struct
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
from scipy.spatial import cKDTree

import dump_runtime_shadow_triangles as shadow_tri
import trace_6804_late_position_probe as late_probe
import trace_6804_texcoord1_path as tex1


ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "output"
GPU_ANALYSIS = ROOT / "gpu-analysis"

OUT_DIR = OUTPUT / "reverse_drogon_runtime_targets"
OUT_MANIFEST = OUT_DIR / "manifest.json"
OUT_REPORT = OUT_DIR / "report.txt"
OUT_WORST = OUT_DIR / "worst_vertices.csv"
OUT_WORLD_OBJ = OUT_DIR / "drogon_target_world.obj"
OUT_LOCAL_OBJ = OUT_DIR / "drogon_target_runtime_local.obj"

AFFINE_MANIFEST = OUTPUT / "shadow_6804_effective_affine" / "manifest.json"
DROGON_OBJ = GPU_ANALYSIS / "DROGON.obj"


@dataclass(frozen=True)
class ErrorStats:
    rmse: float
    avg: float
    max: float


@dataclass(frozen=True)
class SubmeshReport:
    name: str
    gpu_id: str
    vertex_count: int
    triangle_count: int
    nearest_distance: ErrorStats
    reforward_error: ErrorStats
    bbox_overflow_count: int
    bbox_overflow_fraction: float
    original_local_min: tuple[float, float, float]
    original_local_max: tuple[float, float, float]
    target_local_min: tuple[float, float, float]
    target_local_max: tuple[float, float, float]
    output_world_obj: str
    output_local_obj: str


@dataclass(frozen=True)
class WorstVertex:
    submesh: str
    gpu_id: str
    vertex_id: int
    nearest_distance: float
    reforward_error: float
    world_x: float
    world_y: float
    world_z: float
    local_x: float
    local_y: float
    local_z: float


def compute_error_stats(values: list[float]) -> ErrorStats:
    if not values:
        return ErrorStats(rmse=0.0, avg=0.0, max=0.0)
    return ErrorStats(
        rmse=math.sqrt(sum(value * value for value in values) / len(values)),
        avg=sum(values) / len(values),
        max=max(values),
    )


def load_obj_vertices(path: Path) -> np.ndarray:
    verts: list[tuple[float, float, float]] = []
    with path.open("r", encoding="utf-8", errors="ignore") as handle:
        for line in handle:
            if not line.startswith("v "):
                continue
            _tag, xs, ys, zs, *_rest = line.split()
            verts.append((float(xs), float(ys), float(zs)))
    if not verts:
        raise ValueError(f"no OBJ vertices found in {path}")
    return np.asarray(verts, dtype=np.float64)


def load_pix_world_bounds() -> tuple[np.ndarray, np.ndarray]:
    points: list[tuple[float, float, float]] = []
    for _name, _command_index, gpu_id, _vertex_count in tex1.SHADOW_SUBMESHES:
        rows = tex1.load_pix_world_positions(GPU_ANALYSIS / f"2026_3_30__9_24_50_{gpu_id}_VS_BufferData_exp0.csv")
        points.extend(rows.values())
    array = np.asarray(points, dtype=np.float64)
    return array.min(axis=0), array.max(axis=0)


def align_drogon_to_world_bounds(drogon_obj_vertices: np.ndarray, world_min: np.ndarray, world_max: np.ndarray) -> np.ndarray:
    """Coarse axis-swizzled bbox alignment.

    Drogon source axes:
    - X: wingspan
    - Y: height
    - Z: length / head-tail

    Runtime dragon world axes:
    - X: lateral
    - Y: forward/back (negative forward in old notes)
    - Z: up

    Swizzle:
    - Drogon X -> world X
    - Drogon Z -> world Y, flipped
    - Drogon Y -> world Z
    """
    swizzled = np.empty_like(drogon_obj_vertices)
    swizzled[:, 0] = drogon_obj_vertices[:, 0]
    swizzled[:, 1] = -drogon_obj_vertices[:, 2]
    swizzled[:, 2] = drogon_obj_vertices[:, 1]

    src_min = swizzled.min(axis=0)
    src_max = swizzled.max(axis=0)
    src_span = np.maximum(src_max - src_min, 1e-8)
    dst_span = world_max - world_min
    normalized = (swizzled - src_min) / src_span
    return world_min + normalized * dst_span


def write_obj(path: Path, name: str, points: list[tuple[float, float, float]], indices: list[int]) -> None:
    with path.open("w", encoding="ascii", newline="\n") as handle:
        handle.write(f"# {name}\n")
        handle.write(f"o {name}\n")
        for x, y, z in points:
            handle.write(f"v {x:.9f} {y:.9f} {z:.9f}\n")
        for idx in range(0, len(indices), 3):
            handle.write(f"f {indices[idx] + 1} {indices[idx + 1] + 1} {indices[idx + 2] + 1}\n")


def write_combined_obj(
    path: Path,
    meshes: list[tuple[str, list[tuple[float, float, float]], list[int]]],
) -> None:
    with path.open("w", encoding="ascii", newline="\n") as handle:
        handle.write(f"# combined runtime reverse target preview\n")
        vertex_base = 1
        for name, points, indices in meshes:
            handle.write(f"o {name}\n")
            for x, y, z in points:
                handle.write(f"v {x:.9f} {y:.9f} {z:.9f}\n")
            for idx in range(0, len(indices), 3):
                a = vertex_base + indices[idx]
                b = vertex_base + indices[idx + 1]
                c = vertex_base + indices[idx + 2]
                handle.write(f"f {a} {b} {c}\n")
            vertex_base += len(points)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    if not DROGON_OBJ.exists():
        raise FileNotFoundError(f"missing Drogon OBJ: {DROGON_OBJ}")
    if not AFFINE_MANIFEST.exists():
        raise FileNotFoundError(f"missing affine manifest: {AFFINE_MANIFEST}")

    affine_manifest = json.loads(AFFINE_MANIFEST.read_text(encoding="utf-8"))
    affine_solution = np.asarray(affine_manifest["affine_solution"], dtype=np.float64)
    downstream_linear = affine_solution[:3, :]
    downstream_translation = affine_solution[3, :]
    downstream_linear_inv = np.linalg.inv(downstream_linear)

    resource_242 = late_probe.RESOURCE_242.read_bytes()
    resource_7879 = late_probe.RESOURCE_7879.read_bytes()
    resource_7968 = late_probe.RESOURCE_7968.read_bytes()
    resource_16288 = late_probe.RESOURCE_16288.read_bytes()
    resource_147 = late_probe.RESOURCE_147.read_bytes()
    resource_2085 = late_probe.RESOURCE_2085.read_bytes()
    resource_2070 = late_probe.RESOURCE_2070.read_bytes()
    resource_2074 = shadow_tri.RESOURCE_2074.read_bytes()

    shared_constant = tex1.load_indirect_constant(tex1.SHADOW_SUBMESHES[0][1], resource_7968)
    shared_record = tex1.load_draw_record(shared_constant, resource_7879)
    shared_param_offset = shared_record[0] * tex1.STRIDE_242
    shared_config = late_probe.SharedConfig(
        base0=struct.unpack_from("<I", resource_242, shared_param_offset + 48)[0],
        base_lookup=struct.unpack_from("<I", resource_242, shared_param_offset + 104)[0],
        base_late_matrix=struct.unpack_from("<I", resource_242, shared_param_offset + 56)[0],
        cluster_index=struct.unpack_from("<I", resource_242, shared_param_offset + 96)[0] & 0xFFFF,
        u64_word=struct.unpack_from("<I", resource_242, shared_param_offset + 64)[0],
        u64_lt_2pow30=struct.unpack_from("<I", resource_242, shared_param_offset + 64)[0] < 1073741824,
    )

    world_min, world_max = load_pix_world_bounds()
    drogon_vertices = load_obj_vertices(DROGON_OBJ)
    drogon_world = align_drogon_to_world_bounds(drogon_vertices, world_min, world_max)
    drogon_tree = cKDTree(drogon_world)

    live_records = [shadow_tri.load_indirect_record(command_index) for _name, command_index, _vertex_count in shadow_tri.SHADOW_DRAWS]
    draw_records = {record.constant0: shadow_tri.load_draw_record(record.constant0) for record in live_records}
    handles = {draw_records[record.constant0][1] for record in live_records}
    resolved_views = shadow_tri.resolve_space103_descriptors(handles)
    heap_base_gpuva = live_records[0].ib_gpuva - shadow_tri.SHADOW_IB_HEAP_OFFSET
    if heap_base_gpuva <= 0:
        raise ValueError(f"invalid index heap base: 0x{heap_base_gpuva:x}")

    world_meshes: list[tuple[str, list[tuple[float, float, float]], list[int]]] = []
    local_meshes: list[tuple[str, list[tuple[float, float, float]], list[int]]] = []
    submesh_reports: list[SubmeshReport] = []
    worst_vertices: list[WorstVertex] = []
    global_nearest_distances: list[float] = []
    global_reforward_errors: list[float] = []
    gpu_id_lookup = {entry_name: gpu_id for entry_name, _cmd, gpu_id, _count in tex1.SHADOW_SUBMESHES}

    for (name, command_index, vertex_count), indirect in zip(shadow_tri.SHADOW_DRAWS, live_records):
        parameter_index, space103_handle, base_vertex, _aux_handle, _aux_base, _control, _flags = draw_records[indirect.constant0]
        if space103_handle != 6804:
            raise ValueError(f"expected 6804 handle for {name}, got {space103_handle}")
        view = resolved_views[space103_handle]

        bbox_min, bbox_dim = shadow_tri.read_bbox(parameter_index)
        bbox_min_arr = np.asarray(bbox_min, dtype=np.float64)
        bbox_max_arr = bbox_min_arr + np.asarray(bbox_dim, dtype=np.float64)

        index_buffer_offset = indirect.ib_gpuva - heap_base_gpuva
        if index_buffer_offset < 0:
            raise ValueError(f"negative index buffer offset for {name}")
        index_buffer_size = indirect.index_count * 4
        index_block = resource_2074[index_buffer_offset : index_buffer_offset + index_buffer_size]
        if len(index_block) != index_buffer_size:
            raise ValueError(f"short index read for {name}")
        indices = list(struct.unpack_from(f"<{indirect.index_count}I", index_block, 0))

        target_world_points: list[tuple[float, float, float]] = []
        target_local_points: list[tuple[float, float, float]] = []
        nearest_distances: list[float] = []
        reforward_errors: list[float] = []
        overflow_count = 0

        for local_index in range(vertex_count):
            raw40 = resource_16288[
                (view.first_element + base_vertex + local_index) * tex1.VERTEX_STRIDE :
                (view.first_element + base_vertex + local_index + 1) * tex1.VERTEX_STRIDE
            ]
            local_pos = shadow_tri.dequantize_vertex(raw40, bbox_min, bbox_dim)
            late_matrix = late_probe.accumulate_late_matrix(
                raw40=raw40,
                resource_147=resource_147,
                resource_2085=resource_2085,
                resource_2070=resource_2070,
                base0=shared_config.base0,
                base_lookup=shared_config.base_lookup,
                base_late_matrix=shared_config.base_late_matrix,
            )
            late_linear = np.asarray(
                [
                    [late_matrix[0][0], late_matrix[0][1], late_matrix[0][2]],
                    [late_matrix[1][0], late_matrix[1][1], late_matrix[1][2]],
                    [late_matrix[2][0], late_matrix[2][1], late_matrix[2][2]],
                ],
                dtype=np.float64,
            )
            # apply_late_position uses row-vector convention; convert to equivalent
            # column-vector solve by transposing the linear block.
            late_linear_col = late_linear.T
            late_translation = np.asarray([late_matrix[3][0], late_matrix[3][1], late_matrix[3][2]], dtype=np.float64)

            current_late = np.asarray(late_probe.apply_late_position(late_matrix, local_pos), dtype=np.float64)
            current_world = current_late @ downstream_linear + downstream_translation

            nearest_distance, nearest_index = drogon_tree.query(current_world)
            target_world = drogon_world[int(nearest_index)]
            target_late = (target_world - downstream_translation) @ downstream_linear_inv

            try:
                target_local = np.linalg.solve(late_linear_col, target_late - late_translation)
            except np.linalg.LinAlgError:
                target_local = np.linalg.lstsq(late_linear_col, target_late - late_translation, rcond=None)[0]

            reforward_late = late_linear_col @ target_local + late_translation
            reforward_world = reforward_late @ downstream_linear + downstream_translation
            reforward_error = float(np.linalg.norm(reforward_world - target_world))

            if np.any(target_local < bbox_min_arr) or np.any(target_local > bbox_max_arr):
                overflow_count += 1

            target_world_tuple = (float(target_world[0]), float(target_world[1]), float(target_world[2]))
            target_local_tuple = (float(target_local[0]), float(target_local[1]), float(target_local[2]))
            target_world_points.append(target_world_tuple)
            target_local_points.append(target_local_tuple)
            nearest_distances.append(float(nearest_distance))
            reforward_errors.append(reforward_error)
            global_nearest_distances.append(float(nearest_distance))
            global_reforward_errors.append(reforward_error)
            worst_vertices.append(
                WorstVertex(
                    submesh=name,
                    gpu_id=gpu_id_lookup[name],
                    vertex_id=local_index,
                    nearest_distance=float(nearest_distance),
                    reforward_error=reforward_error,
                    world_x=target_world_tuple[0],
                    world_y=target_world_tuple[1],
                    world_z=target_world_tuple[2],
                    local_x=target_local_tuple[0],
                    local_y=target_local_tuple[1],
                    local_z=target_local_tuple[2],
                )
            )

        target_local_array = np.asarray(target_local_points, dtype=np.float64)
        target_local_min = tuple(target_local_array.min(axis=0))
        target_local_max = tuple(target_local_array.max(axis=0))

        world_obj = OUT_DIR / f"{name.lower()}_target_world.obj"
        local_obj = OUT_DIR / f"{name.lower()}_target_runtime_local.obj"
        write_obj(world_obj, f"{name}_target_world", target_world_points, indices)
        write_obj(local_obj, f"{name}_target_runtime_local", target_local_points, indices)
        world_meshes.append((f"{name}_target_world", target_world_points, indices))
        local_meshes.append((f"{name}_target_runtime_local", target_local_points, indices))

        submesh_reports.append(
            SubmeshReport(
                name=name,
                gpu_id=gpu_id_lookup[name],
                vertex_count=vertex_count,
                triangle_count=indirect.index_count // 3,
                nearest_distance=compute_error_stats(nearest_distances),
                reforward_error=compute_error_stats(reforward_errors),
                bbox_overflow_count=overflow_count,
                bbox_overflow_fraction=overflow_count / float(vertex_count),
                original_local_min=tuple(float(v) for v in bbox_min_arr),
                original_local_max=tuple(float(v) for v in bbox_max_arr),
                target_local_min=tuple(float(v) for v in target_local_min),
                target_local_max=tuple(float(v) for v in target_local_max),
                output_world_obj=str(world_obj.relative_to(ROOT)).replace("\\", "/"),
                output_local_obj=str(local_obj.relative_to(ROOT)).replace("\\", "/"),
            )
        )

    worst_vertices.sort(key=lambda row: row.nearest_distance, reverse=True)

    write_combined_obj(OUT_WORLD_OBJ, world_meshes)
    write_combined_obj(OUT_LOCAL_OBJ, local_meshes)

    with OUT_WORST.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "submesh",
                "gpu_id",
                "vertex_id",
                "nearest_distance",
                "reforward_error",
                "world_x",
                "world_y",
                "world_z",
                "local_x",
                "local_y",
                "local_z",
            ]
        )
        for row in worst_vertices[:200]:
            writer.writerow(
                [
                    row.submesh,
                    row.gpu_id,
                    row.vertex_id,
                    f"{row.nearest_distance:.9f}",
                    f"{row.reforward_error:.9f}",
                    f"{row.world_x:.9f}",
                    f"{row.world_y:.9f}",
                    f"{row.world_z:.9f}",
                    f"{row.local_x:.9f}",
                    f"{row.local_y:.9f}",
                    f"{row.local_z:.9f}",
                ]
            )

    overall_nearest = compute_error_stats(global_nearest_distances)
    overall_reforward = compute_error_stats(global_reforward_errors)

    report_lines = [
        "Drogon runtime reverse targets",
        "==============================",
        "",
        "Inputs",
        "------",
        f"drogon_obj       : {DROGON_OBJ}",
        f"affine_manifest  : {AFFINE_MANIFEST}",
        "",
        "Method",
        "------",
        "- Coarse-align Drogon OBJ to PIX dragon world bounds with axis swizzle:",
        "  Drogon X -> world X, Drogon Z -> -world Y, Drogon Y -> world Z",
        "- Query nearest Drogon vertex in world space for each proven 6804 dragon vertex.",
        "- Invert the fitted late_pos -> PIX world affine.",
        "- Invert the exact per-vertex late matrix to recover desired runtime-local coordinates.",
        "",
        "Important limitation",
        "--------------------",
        "- This is a vertex-cloud correspondence pass, not full nearest-triangle projection.",
        "- It is meant to generate a measurable runtime-local target set, not final PAC bytes.",
        "",
        "Overall",
        "-------",
        f"submeshes             : {len(submesh_reports)}",
        f"total_vertices        : {sum(item.vertex_count for item in submesh_reports)}",
        f"nearest rmse          : {overall_nearest.rmse:.9f}",
        f"nearest avg           : {overall_nearest.avg:.9f}",
        f"reforward rmse        : {overall_reforward.rmse:.9f}",
        f"reforward avg         : {overall_reforward.avg:.9f}",
        f"combined world obj    : {OUT_WORLD_OBJ.relative_to(ROOT).as_posix()}",
        f"combined local obj    : {OUT_LOCAL_OBJ.relative_to(ROOT).as_posix()}",
        "",
        "Per-submesh",
        "-----------",
    ]
    for item in submesh_reports:
        report_lines.extend(
            [
                f"{item.name} ({item.gpu_id})",
                f"  verts                 : {item.vertex_count}",
                f"  tris                  : {item.triangle_count}",
                f"  nearest rmse          : {item.nearest_distance.rmse:.9f}",
                f"  nearest avg           : {item.nearest_distance.avg:.9f}",
                f"  reforward rmse        : {item.reforward_error.rmse:.9f}",
                f"  bbox overflow         : {item.bbox_overflow_count} / {item.vertex_count} ({item.bbox_overflow_fraction:.2%})",
                f"  local target min      : ({item.target_local_min[0]:.6f}, {item.target_local_min[1]:.6f}, {item.target_local_min[2]:.6f})",
                f"  local target max      : ({item.target_local_max[0]:.6f}, {item.target_local_max[1]:.6f}, {item.target_local_max[2]:.6f})",
            ]
        )

    OUT_REPORT.write_text("\n".join(report_lines) + "\n", encoding="utf-8")
    OUT_MANIFEST.write_text(
        json.dumps(
            {
                "drogon_obj": str(DROGON_OBJ),
                "affine_manifest": str(AFFINE_MANIFEST),
                "combined_world_obj": str(OUT_WORLD_OBJ.relative_to(ROOT)).replace("\\", "/"),
                "combined_local_obj": str(OUT_LOCAL_OBJ.relative_to(ROOT)).replace("\\", "/"),
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
    print(f"wrote {OUT_WORLD_OBJ}")
    print(f"wrote {OUT_LOCAL_OBJ}")
    print(f"wrote {OUT_WORST}")


if __name__ == "__main__":
    main()
