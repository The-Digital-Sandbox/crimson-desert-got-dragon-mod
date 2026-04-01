#!/usr/bin/env python3
"""Generate improved Drogon runtime targets using hybrid submesh source clouds.

This extends the first reverse-target pass by choosing the best candidate source
cloud per dragon submesh before inverting back to runtime-local coordinates.

Candidate families:
- globally aligned raw Drogon OBJ
- per-submesh CD-named GLB primitive, bbox-aligned to the target submesh
- selected GLB unions for torso / leg / wing-heavy regions

Goal:
- keep the proven 6804 reverse math untouched
- improve anatomical correspondence before any PAC writeback attempt
"""

from __future__ import annotations

import csv
import json
import math
import struct
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
from pygltflib import GLTF2
from scipy.spatial import cKDTree

import dump_runtime_shadow_triangles as shadow_tri
import generate_drogon_runtime_targets as base
import trace_6804_late_position_probe as late_probe
import trace_6804_texcoord1_path as tex1


ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "output"
GPU_ANALYSIS = ROOT / "gpu-analysis"

OUT_DIR = OUTPUT / "reverse_drogon_runtime_targets_hybrid"
OUT_MANIFEST = OUT_DIR / "manifest.json"
OUT_REPORT = OUT_DIR / "report.txt"
OUT_WORST = OUT_DIR / "worst_vertices.csv"
OUT_WORLD_OBJ = OUT_DIR / "drogon_target_world.obj"
OUT_LOCAL_OBJ = OUT_DIR / "drogon_target_runtime_local.obj"

AFFINE_MANIFEST = OUTPUT / "shadow_6804_effective_affine" / "manifest.json"
RAW_DROGON_OBJ = GPU_ANALYSIS / "DROGON.obj"
RIGGED_GLB = OUTPUT / "DrogonRigged-correctweights.glb"

MATERIAL_BY_SUBMESH = {
    "Body_02": "CD_M0004_00_Dragon_Body_0001_02",
    "back": "CD_M0004_00_Dragon_back_0001",
    "Body": "CD_M0004_00_Dragon_Body_0001",
    "Leg": "CD_M0004_00_Dragon_Leg_0001",
    "Wing": "CD_M0004_00_Dragon_Wing_0001",
    "Head": "CD_M0004_00_Dragon_Head_0001",
}

UNION_MATERIALS = {
    "Body_union": [
        "CD_M0004_00_Dragon_Body_0001",
        "CD_M0004_00_Dragon_Body_0001_02",
        "CD_M0004_00_Dragon_back_0001",
        "CD_M0004_00_Dragon_Leg_0001",
        "CD_M0004_00_Dragon_Wing_0001",
    ],
    "Leg_union": [
        "CD_M0004_00_Dragon_Leg_0001",
        "CD_M0004_00_Dragon_Body_0001",
    ],
    "Wing_union": [
        "CD_M0004_00_Dragon_Wing_0001",
        "CD_M0004_00_Dragon_back_0001",
        "CD_M0004_00_Dragon_Body_0001_02",
    ],
}

SUBMESH_CANDIDATES = {
    "Body_02": ["raw_global", "glb_primitive_bbox"],
    "back": ["raw_global", "glb_primitive_bbox"],
    "Body": ["raw_global", "glb_primitive_bbox", "glb_body_union_bbox"],
    "Leg": ["raw_global", "glb_primitive_bbox", "glb_leg_union_bbox"],
    "Wing": ["raw_global", "glb_primitive_bbox", "glb_wing_union_bbox"],
    "Head": ["raw_global", "glb_primitive_bbox"],
}


@dataclass(frozen=True)
class ErrorStats:
    rmse: float
    avg: float
    max: float


@dataclass(frozen=True)
class CandidateSummary:
    name: str
    point_count: int
    error: ErrorStats


@dataclass(frozen=True)
class SubmeshReport:
    name: str
    gpu_id: str
    vertex_count: int
    triangle_count: int
    chosen_candidate: str
    chosen_candidate_points: int
    nearest_distance: ErrorStats
    reforward_error: ErrorStats
    bbox_overflow_count: int
    bbox_overflow_fraction: float
    original_local_min: tuple[float, float, float]
    original_local_max: tuple[float, float, float]
    target_local_min: tuple[float, float, float]
    target_local_max: tuple[float, float, float]
    candidates: list[CandidateSummary] = field(default_factory=list)
    output_world_obj: str = ""
    output_local_obj: str = ""


@dataclass(frozen=True)
class WorstVertex:
    submesh: str
    gpu_id: str
    vertex_id: int
    candidate: str
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
        handle.write("# combined hybrid runtime reverse target preview\n")
        vertex_base = 1
        for name, points, indices in meshes:
            handle.write(f"o {name}\n")
            for x, y, z in points:
                handle.write(f"v {x:.9f} {y:.9f} {z:.9f}\n")
            for idx in range(0, len(indices), 3):
                handle.write(
                    f"f {vertex_base + indices[idx]} {vertex_base + indices[idx + 1]} {vertex_base + indices[idx + 2]}\n"
                )
            vertex_base += len(points)


def load_glb_primitive_positions(path: Path) -> dict[str, np.ndarray]:
    glb = GLTF2().load(str(path))
    blob = glb.binary_blob()
    component_info = {
        5126: ("f", 4),
        5125: ("I", 4),
        5123: ("H", 2),
        5122: ("h", 2),
        5121: ("B", 1),
        5120: ("b", 1),
    }
    component_count = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}

    def read_accessor(accessor_index: int) -> np.ndarray:
        accessor = glb.accessors[accessor_index]
        buffer_view = glb.bufferViews[accessor.bufferView]
        fmt, scalar_size = component_info[accessor.componentType]
        width = component_count[accessor.type]
        stride = buffer_view.byteStride or (scalar_size * width)
        offset = (buffer_view.byteOffset or 0) + (accessor.byteOffset or 0)
        result = []
        for item_index in range(accessor.count):
            result.append(struct.unpack_from("<" + fmt * width, blob, offset + item_index * stride))
        return np.asarray(result, dtype=np.float64)

    positions: dict[str, np.ndarray] = {}
    mesh = glb.meshes[0]
    for primitive in mesh.primitives:
        material_name = glb.materials[primitive.material].name
        positions[material_name] = read_accessor(primitive.attributes.POSITION)
    return positions


def swizzle_to_world_axes(points: np.ndarray) -> np.ndarray:
    swizzled = np.empty_like(points)
    swizzled[:, 0] = points[:, 0]
    swizzled[:, 1] = -points[:, 2]
    swizzled[:, 2] = points[:, 1]
    return swizzled


def bbox_align(points_world_axes: np.ndarray, target_points: np.ndarray) -> np.ndarray:
    src_min = points_world_axes.min(axis=0)
    src_max = points_world_axes.max(axis=0)
    src_span = np.maximum(src_max - src_min, 1e-8)
    dst_min = target_points.min(axis=0)
    dst_max = target_points.max(axis=0)
    dst_span = dst_max - dst_min
    normalized = (points_world_axes - src_min) / src_span
    return dst_min + normalized * dst_span


def choose_candidate(
    submesh_name: str,
    target_points: np.ndarray,
    raw_global: np.ndarray,
    glb_positions: dict[str, np.ndarray],
) -> tuple[str, np.ndarray, list[CandidateSummary]]:
    candidates: list[tuple[str, np.ndarray]] = [("raw_global", raw_global)]

    material_name = MATERIAL_BY_SUBMESH[submesh_name]
    if material_name in glb_positions:
        candidates.append(
            (
                "glb_primitive_bbox",
                bbox_align(swizzle_to_world_axes(glb_positions[material_name]), target_points),
            )
        )

    if submesh_name == "Body":
        union_points = np.vstack([glb_positions[name] for name in UNION_MATERIALS["Body_union"] if name in glb_positions])
        candidates.append(("glb_body_union_bbox", bbox_align(swizzle_to_world_axes(union_points), target_points)))
    elif submesh_name == "Leg":
        union_points = np.vstack([glb_positions[name] for name in UNION_MATERIALS["Leg_union"] if name in glb_positions])
        candidates.append(("glb_leg_union_bbox", bbox_align(swizzle_to_world_axes(union_points), target_points)))
    elif submesh_name == "Wing":
        union_points = np.vstack([glb_positions[name] for name in UNION_MATERIALS["Wing_union"] if name in glb_positions])
        candidates.append(("glb_wing_union_bbox", bbox_align(swizzle_to_world_axes(union_points), target_points)))

    allowed = set(SUBMESH_CANDIDATES[submesh_name])
    candidates = [(name, points) for name, points in candidates if name in allowed]

    scored: list[CandidateSummary] = []
    best_name = ""
    best_points: np.ndarray | None = None
    best_rmse = float("inf")

    for candidate_name, candidate_points in candidates:
        distances, _indices = cKDTree(candidate_points).query(target_points)
        stats = compute_error_stats([float(value) for value in distances])
        scored.append(CandidateSummary(name=candidate_name, point_count=len(candidate_points), error=stats))
        if stats.rmse < best_rmse:
            best_rmse = stats.rmse
            best_name = candidate_name
            best_points = candidate_points

    if best_points is None:
        raise ValueError(f"no candidate points for {submesh_name}")
    return best_name, best_points, scored


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    if not RAW_DROGON_OBJ.exists():
        raise FileNotFoundError(f"missing raw Drogon OBJ: {RAW_DROGON_OBJ}")
    if not RIGGED_GLB.exists():
        raise FileNotFoundError(f"missing rigged GLB: {RIGGED_GLB}")
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

    raw_world_min, raw_world_max = base.load_pix_world_bounds()
    raw_drogon_vertices = base.load_obj_vertices(RAW_DROGON_OBJ)
    raw_drogon_world = base.align_drogon_to_world_bounds(raw_drogon_vertices, raw_world_min, raw_world_max)
    glb_positions = load_glb_primitive_positions(RIGGED_GLB)

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

    live_records = [shadow_tri.load_indirect_record(command_index) for _name, command_index, _vertex_count in shadow_tri.SHADOW_DRAWS]
    draw_records = {record.constant0: shadow_tri.load_draw_record(record.constant0) for record in live_records}
    handles = {draw_records[record.constant0][1] for record in live_records}
    resolved_views = shadow_tri.resolve_space103_descriptors(handles)
    heap_base_gpuva = live_records[0].ib_gpuva - shadow_tri.SHADOW_IB_HEAP_OFFSET
    if heap_base_gpuva <= 0:
        raise ValueError(f"invalid index heap base: 0x{heap_base_gpuva:x}")

    gpu_id_lookup = {entry_name: gpu_id for entry_name, _cmd, gpu_id, _count in tex1.SHADOW_SUBMESHES}
    world_meshes: list[tuple[str, list[tuple[float, float, float]], list[int]]] = []
    local_meshes: list[tuple[str, list[tuple[float, float, float]], list[int]]] = []
    submesh_reports: list[SubmeshReport] = []
    worst_vertices: list[WorstVertex] = []
    global_nearest_distances: list[float] = []
    global_reforward_errors: list[float] = []

    for (name, command_index, vertex_count), indirect in zip(shadow_tri.SHADOW_DRAWS, live_records):
        parameter_index, space103_handle, base_vertex, _aux_handle, _aux_base, _control, _flags = draw_records[indirect.constant0]
        if space103_handle != 6804:
            raise ValueError(f"expected 6804 handle for {name}, got {space103_handle}")
        view = resolved_views[space103_handle]

        pix_rows = tex1.load_pix_world_positions(GPU_ANALYSIS / f"2026_3_30__9_24_50_{gpu_id_lookup[name]}_VS_BufferData_exp0.csv")
        pix_array = np.asarray([pix_rows[idx] for idx in range(vertex_count)], dtype=np.float64)
        chosen_name, chosen_points, candidate_summaries = choose_candidate(name, pix_array, raw_drogon_world, glb_positions)
        chosen_tree = cKDTree(chosen_points)

        bbox_min, bbox_dim = shadow_tri.read_bbox(parameter_index)
        bbox_min_arr = np.asarray(bbox_min, dtype=np.float64)
        bbox_max_arr = bbox_min_arr + np.asarray(bbox_dim, dtype=np.float64)

        index_buffer_offset = indirect.ib_gpuva - heap_base_gpuva
        index_buffer_size = indirect.index_count * 4
        index_block = resource_2074[index_buffer_offset : index_buffer_offset + index_buffer_size]
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
            late_linear_col = late_linear.T
            late_translation = np.asarray([late_matrix[3][0], late_matrix[3][1], late_matrix[3][2]], dtype=np.float64)

            current_late = np.asarray(late_probe.apply_late_position(late_matrix, local_pos), dtype=np.float64)
            current_world = current_late @ downstream_linear + downstream_translation
            nearest_distance, nearest_index = chosen_tree.query(current_world)
            target_world = chosen_points[int(nearest_index)]
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
                    candidate=chosen_name,
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
                chosen_candidate=chosen_name,
                chosen_candidate_points=len(chosen_points),
                nearest_distance=compute_error_stats(nearest_distances),
                reforward_error=compute_error_stats(reforward_errors),
                bbox_overflow_count=overflow_count,
                bbox_overflow_fraction=overflow_count / float(vertex_count),
                original_local_min=tuple(float(v) for v in bbox_min_arr),
                original_local_max=tuple(float(v) for v in bbox_max_arr),
                target_local_min=tuple(float(v) for v in target_local_min),
                target_local_max=tuple(float(v) for v in target_local_max),
                candidates=candidate_summaries,
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
                "candidate",
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
                    row.candidate,
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
        "Drogon runtime reverse targets (hybrid)",
        "======================================",
        "",
        "Inputs",
        "------",
        f"raw_drogon_obj    : {RAW_DROGON_OBJ}",
        f"rigged_glb        : {RIGGED_GLB}",
        f"affine_manifest   : {AFFINE_MANIFEST}",
        "",
        "Method",
        "------",
        "- Score multiple source clouds per submesh against the live PIX world positions.",
        "- Keep the best candidate per submesh, then run the exact reverse inversion through",
        "  downstream affine inverse + exact per-vertex late matrix inverse.",
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
                f"  chosen candidate      : {item.chosen_candidate}",
                f"  candidate points      : {item.chosen_candidate_points}",
                f"  nearest rmse          : {item.nearest_distance.rmse:.9f}",
                f"  nearest avg           : {item.nearest_distance.avg:.9f}",
                f"  reforward rmse        : {item.reforward_error.rmse:.9f}",
                f"  bbox overflow         : {item.bbox_overflow_count} / {item.vertex_count} ({item.bbox_overflow_fraction:.2%})",
            ]
        )
        for candidate in item.candidates:
            report_lines.append(
                f"    cand {candidate.name:20s} points={candidate.point_count:6d} rmse={candidate.error.rmse:.9f} avg={candidate.error.avg:.9f}"
            )

    OUT_REPORT.write_text("\n".join(report_lines) + "\n", encoding="utf-8")
    OUT_MANIFEST.write_text(
        json.dumps(
            {
                "raw_drogon_obj": str(RAW_DROGON_OBJ),
                "rigged_glb": str(RIGGED_GLB),
                "affine_manifest": str(AFFINE_MANIFEST),
                "combined_world_obj": str(OUT_WORLD_OBJ.relative_to(ROOT)).replace("\\", "/"),
                "combined_local_obj": str(OUT_LOCAL_OBJ.relative_to(ROOT)).replace("\\", "/"),
                "overall_nearest_error": asdict(overall_nearest),
                "overall_reforward_error": asdict(overall_reforward),
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
