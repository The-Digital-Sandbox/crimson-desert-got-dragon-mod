#!/usr/bin/env python3
"""Trace the live primary-family dragon fragments through skinning + cluster placement.

This stays entirely on the runtime PIX path:

- resource 7968: live indirect draw records
- resource 7879: live draw records / parameter selection
- resources 15390 / 15486: runtime primary-family vertex buffers
- resource 242: stride-156 render parameter buffer
- resources 147 / 2085 / 2081 / 2070: later skinning indirection + matrix tables
- resource 80: space15 cluster-frame buffer (stride 272)
- resource 2074: live index-buffer backing store on heap 2073

Current scope is intentionally narrow and matches the proven live primary family:

- early space22 packed-offset branch is skipped (`flags & 0xFFFE >= 2`)
- alternate `%861` matrix branch is skipped (`resource_242[128] == 0.0`)
- the first later matrix chain plus the 272-byte cluster frame are traced exactly

That is enough to move the tiny origin-local fragments into their placed primary-space
patches and gives us a real artifact to compare against later passes.
"""

from __future__ import annotations

import json
import re
import struct
from dataclasses import asdict, dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
GPU_ANALYSIS = ROOT / "gpu-analysis"
PIX_RESOURCES = ROOT / "output" / "pix_resources"
OUT_DIR = ROOT / "output" / "runtime_primary_skinning"

RESOURCE_242 = PIX_RESOURCES / "resource_242.bin"
RESOURCE_7879 = PIX_RESOURCES / "resource_7879.bin"
RESOURCE_7968 = PIX_RESOURCES / "resource_7968.bin"
RESOURCE_2074 = PIX_RESOURCES / "resource_2074.bin"

STRIDE_242 = 156
STRIDE_7879 = 28
STRIDE_7968 = 40
VERTEX_STRIDE = 40
CLUSTER_FRAME_STRIDE = 272
HEAP_2073_BASE_GPUVA = 0x2E0000000

SPACE_BINDLESS_BASE = 138000
SPACE103_BASE = 368000

PRIMARY_DRAWS = [
    ("Primary_39", 39),
    ("Primary_40", 40),
    ("Primary_41", 41),
    ("Primary_42", 42),
    ("Primary_43", 43),
    ("Primary_44", 44),
]

DESCRIPTOR_RE = re.compile(
    r"CreateShaderResourceView_Buffer\("
    r"GetResource\((\d+)\)\.Get\(\),\s*"
    r"GetCpuDescriptor\(g_descriptorHeap_393\.Get\(\),\s*(\d+)\),\s*"
    r"DXGI_FORMAT_UNKNOWN,\s*D3D12_SRV_DIMENSION_BUFFER,\s*"
    r"\d+,\s*(\d+),\s*(\d+),\s*(\d+),"
)


@dataclass(frozen=True)
class DescriptorView:
    descriptor_index: int
    resource_id: int
    first_element: int
    num_elements: int
    stride: int
    source_file: str


@dataclass(frozen=True)
class ParameterFields:
    parameter_index: int
    bbox_min: tuple[float, float, float]
    bbox_dim: tuple[float, float, float]
    first_lookup_base: int
    matrix_base: int
    remap_base: int
    first_lookup_handle: int
    remap_handle: int
    matrix_handle: int
    cluster_handle: int
    cluster_index: int
    blend_gate: float
    flags_word: int


@dataclass(frozen=True)
class TraceSummary:
    name: str
    command_index: int
    parameter_index: int
    flags: int
    control: int
    base_vertex: int
    vertex_count: int
    triangle_count: int
    vertex_resource_id: int
    first_lookup_resource_id: int
    remap_resource_id: int
    matrix_resource_id: int
    cluster_resource_id: int
    cluster_handle: int
    cluster_index: int
    pre_bounds_min: tuple[float, float, float]
    pre_bounds_max: tuple[float, float, float]
    skinned_bounds_min: tuple[float, float, float]
    skinned_bounds_max: tuple[float, float, float]
    final_bounds_min: tuple[float, float, float]
    final_bounds_max: tuple[float, float, float]
    pre_obj: str
    skinned_obj: str
    final_obj: str


def shader_source_paths() -> list[Path]:
    return sorted(GPU_ANALYSIS.glob("Descriptors_*.cpp")) + sorted(GPU_ANALYSIS.glob("ModifyDescriptors_*.cpp"))


def resolve_descriptor_views(descriptor_indices: set[int]) -> dict[int, DescriptorView]:
    resolved: dict[int, DescriptorView] = {}
    for path in shader_source_paths():
        text = path.read_text(encoding="utf-8")
        for match in DESCRIPTOR_RE.finditer(text):
            descriptor_index = int(match.group(2))
            if descriptor_index not in descriptor_indices or descriptor_index in resolved:
                continue
            resolved[descriptor_index] = DescriptorView(
                descriptor_index=descriptor_index,
                resource_id=int(match.group(1)),
                first_element=int(match.group(3)),
                num_elements=int(match.group(4)),
                stride=int(match.group(5)),
                source_file=path.name,
            )
    missing = sorted(descriptor_indices - set(resolved))
    if missing:
        raise ValueError(f"missing descriptor views for indices: {missing}")
    return resolved


def load_resource(resource_id: int, cache: dict[int, bytes]) -> bytes:
    if resource_id not in cache:
        path = PIX_RESOURCES / f"resource_{resource_id}.bin"
        if not path.exists():
            raise FileNotFoundError(f"missing extracted PIX resource: {path}")
        cache[resource_id] = path.read_bytes()
    return cache[resource_id]


def load_indirect_record(command_index: int) -> tuple[int, int, int, int, int, int, int, int, int]:
    data = RESOURCE_7968.read_bytes()
    offset = command_index * STRIDE_7968
    ib_gpuva, ib_size_bytes, ib_format = struct.unpack_from("<QII", data, offset + 0)
    constant0 = struct.unpack_from("<I", data, offset + 16)[0]
    draw = struct.unpack_from("<IIiII", data, offset + 20)
    return (ib_gpuva, ib_size_bytes, ib_format, constant0, *draw)


def load_draw_record(record_index: int) -> tuple[int, int, int, int, int, int, int]:
    data = RESOURCE_7879.read_bytes()
    return struct.unpack_from("<7I", data, record_index * STRIDE_7879)


def load_parameter_fields(parameter_index: int) -> ParameterFields:
    data = RESOURCE_242.read_bytes()
    offset = parameter_index * STRIDE_242
    bbox_min = struct.unpack_from("<3f", data, offset + 0)
    bbox_dim = struct.unpack_from("<3f", data, offset + 16)
    u48 = struct.unpack_from("<I", data, offset + 48)[0]
    u52 = struct.unpack_from("<I", data, offset + 52)[0]
    u76 = struct.unpack_from("<I", data, offset + 76)[0]
    u80 = struct.unpack_from("<I", data, offset + 80)[0]
    u84 = struct.unpack_from("<I", data, offset + 84)[0]
    u88 = struct.unpack_from("<I", data, offset + 88)[0]
    u96 = struct.unpack_from("<I", data, offset + 96)[0]
    u104 = struct.unpack_from("<I", data, offset + 104)[0]
    f128 = struct.unpack_from("<f", data, offset + 128)[0]
    return ParameterFields(
        parameter_index=parameter_index,
        bbox_min=bbox_min,
        bbox_dim=bbox_dim,
        first_lookup_base=u48,
        matrix_base=u52,
        remap_base=u104,
        first_lookup_handle=u80,
        remap_handle=u88 >> 16,
        matrix_handle=u84 >> 16,
        cluster_handle=u96 >> 16,
        cluster_index=u96 & 0xFFFF,
        blend_gate=1.0 - f128,
        flags_word=u76,
    )


def dequantize_vertex(
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


def decode_primary_phase0(raw40: bytes) -> tuple[list[int], list[float]]:
    _, _, _, _, _, u60, u61, u63, _, _ = struct.unpack_from("<10I", raw40, 0)
    indices = [
        u60 & 0x3FF,
        (u60 >> 10) & 0x3FF,
        (u60 >> 20) & 0x3FF,
        u61 & 0x3FF,
    ]
    weights = [
        (u63 & 0xFF) / 255.0,
        ((u63 >> 8) & 0xFF) / 255.0,
        ((u63 >> 16) & 0xFF) / 255.0,
        ((u63 >> 24) & 0xFF) / 255.0,
    ]
    return indices, weights


def load_u32(view: DescriptorView, buffer: bytes, index: int) -> int:
    absolute_index = view.first_element + index
    offset = absolute_index * view.stride
    return struct.unpack_from("<I", buffer, offset)[0]


def load_matrix4x4(view: DescriptorView, buffer: bytes, index: int) -> tuple[tuple[float, ...], ...]:
    absolute_index = view.first_element + index
    offset = absolute_index * view.stride
    return (
        struct.unpack_from("<4f", buffer, offset + 0),
        struct.unpack_from("<4f", buffer, offset + 16),
        struct.unpack_from("<4f", buffer, offset + 32),
        struct.unpack_from("<4f", buffer, offset + 48),
    )


def accumulate_phase0_matrix(
    indices: list[int],
    weights: list[float],
    fields: ParameterFields,
    first_lookup_view: DescriptorView,
    remap_view: DescriptorView,
    matrix_view: DescriptorView,
    resource_cache: dict[int, bytes],
) -> tuple[tuple[float, ...], ...]:
    first_lookup_buffer = load_resource(first_lookup_view.resource_id, resource_cache)
    remap_buffer = load_resource(remap_view.resource_id, resource_cache)
    matrix_buffer = load_resource(matrix_view.resource_id, resource_cache)
    accum = [[0.0, 0.0, 0.0, 0.0] for _ in range(4)]

    for index, weight in zip(indices, weights):
        if weight <= 0.0:
            continue
        lookup_0 = load_u32(first_lookup_view, first_lookup_buffer, fields.first_lookup_base + index)
        lookup_1 = load_u32(remap_view, remap_buffer, fields.remap_base + lookup_0)
        matrix_index = fields.matrix_base + lookup_1
        matrix = load_matrix4x4(matrix_view, matrix_buffer, matrix_index)
        for row in range(4):
            for col in range(4):
                accum[row][col] += matrix[row][col] * weight

    return tuple(tuple(row) for row in accum)


def apply_affine_columns(
    matrix: tuple[tuple[float, ...], ...],
    point: tuple[float, float, float],
) -> tuple[float, float, float]:
    x, y, z = point
    return (
        x * matrix[0][0] + y * matrix[1][0] + z * matrix[2][0] + matrix[3][0],
        x * matrix[0][1] + y * matrix[1][1] + z * matrix[2][1] + matrix[3][1],
        x * matrix[0][2] + y * matrix[1][2] + z * matrix[2][2] + matrix[3][2],
    )


def bounds(points: list[tuple[float, float, float]]) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    zs = [p[2] for p in points]
    return (min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs))


def write_obj(path: Path, name: str, points: list[tuple[float, float, float]], indices: list[int]) -> None:
    with path.open("w", encoding="ascii", newline="\n") as handle:
        handle.write(f"# {name}\n")
        for x, y, z in points:
            handle.write(f"v {x:.9f} {y:.9f} {z:.9f}\n")
        for i in range(0, len(indices), 3):
            handle.write(f"f {indices[i] + 1} {indices[i + 1] + 1} {indices[i + 2] + 1}\n")


def trace_draw(
    name: str,
    command_index: int,
    views: dict[int, DescriptorView],
    resource_cache: dict[int, bytes],
    index_bytes: bytes,
) -> TraceSummary:
    ib_gpuva, ib_size_bytes, ib_format, constant0, index_count, instance_count, start_index, base_vertex, start_instance = load_indirect_record(command_index)
    parameter_index, space103_handle, record_base_vertex, aux_handle, aux_base, control, flags = load_draw_record(constant0)

    if ib_format != 57:
        raise ValueError(f"{name}: unexpected IB format {ib_format}")
    if instance_count != 1 or start_instance != 0:
        raise ValueError(f"{name}: unexpected draw args {(index_count, instance_count, start_index, base_vertex, start_instance)}")
    if base_vertex != record_base_vertex:
        raise ValueError(f"{name}: base vertex mismatch {base_vertex} vs {record_base_vertex}")
    if aux_handle != 0 or aux_base != 0:
        raise ValueError(f"{name}: expected no aux handle/base, got {aux_handle}, {aux_base}")
    if (flags & 0xFFFE) < 2:
        raise ValueError(f"{name}: early space22 branch is active; this tracer only supports primary-family records")

    fields = load_parameter_fields(parameter_index)
    if fields.blend_gate < 1.0:
        raise ValueError(
            f"{name}: alternate %861 branch is active (blend gate {fields.blend_gate}); this tracer expects it to be skipped"
        )
    if (fields.flags_word & 0xFFFF) != 0:
        raise ValueError(f"{name}: optional extra phase is active via u76=0x{fields.flags_word:08X}")

    vertex_view = views[SPACE103_BASE + space103_handle]
    first_lookup_view = views[SPACE_BINDLESS_BASE + fields.first_lookup_handle]
    remap_view = views[SPACE_BINDLESS_BASE + fields.remap_handle]
    matrix_view = views[SPACE_BINDLESS_BASE + fields.matrix_handle]
    cluster_view = views[SPACE_BINDLESS_BASE + fields.cluster_handle]

    if vertex_view.stride != VERTEX_STRIDE:
        raise ValueError(f"{name}: unexpected vertex stride {vertex_view.stride}")
    if first_lookup_view.stride != 4 or remap_view.stride != 4:
        raise ValueError(f"{name}: unexpected lookup/remap stride {first_lookup_view.stride}/{remap_view.stride}")
    if matrix_view.stride != 64:
        raise ValueError(f"{name}: unexpected matrix stride {matrix_view.stride}")
    if cluster_view.stride != CLUSTER_FRAME_STRIDE:
        raise ValueError(f"{name}: unexpected cluster frame stride {cluster_view.stride}")

    indices = list(
        struct.unpack_from(
            "<" + ("H" * index_count),
            index_bytes,
            (ib_gpuva - HEAP_2073_BASE_GPUVA) + start_index * 2,
        )
    )
    local_vertex_count = max(indices) + 1 if indices else 0
    if base_vertex + local_vertex_count > vertex_view.num_elements:
        raise ValueError(
            f"{name}: base {base_vertex} + local count {local_vertex_count} exceeds view {vertex_view.num_elements}"
        )

    vertex_buffer = load_resource(vertex_view.resource_id, resource_cache)
    cluster_buffer = load_resource(cluster_view.resource_id, resource_cache)
    cluster_matrix = load_matrix4x4(cluster_view, cluster_buffer, fields.cluster_index)

    pre_points: list[tuple[float, float, float]] = []
    skinned_points: list[tuple[float, float, float]] = []
    final_points: list[tuple[float, float, float]] = []

    for local_index in range(local_vertex_count):
        absolute_index = vertex_view.first_element + base_vertex + local_index
        raw40 = vertex_buffer[absolute_index * vertex_view.stride : (absolute_index + 1) * vertex_view.stride]
        pre_point = dequantize_vertex(raw40, fields.bbox_min, fields.bbox_dim)
        indices_phase0, weights_phase0 = decode_primary_phase0(raw40)
        skin_matrix = accumulate_phase0_matrix(
            indices_phase0,
            weights_phase0,
            fields,
            first_lookup_view,
            remap_view,
            matrix_view,
            resource_cache,
        )
        skinned_point = apply_affine_columns(skin_matrix, pre_point)
        final_point = apply_affine_columns(cluster_matrix, skinned_point)
        pre_points.append(pre_point)
        skinned_points.append(skinned_point)
        final_points.append(final_point)

    pre_obj = OUT_DIR / f"{name.lower()}_pre.obj"
    skinned_obj = OUT_DIR / f"{name.lower()}_skinned.obj"
    final_obj = OUT_DIR / f"{name.lower()}_final.obj"
    write_obj(pre_obj, f"{name} pre-dequantized", pre_points, indices)
    write_obj(skinned_obj, f"{name} phase0-skinned", skinned_points, indices)
    write_obj(final_obj, f"{name} cluster-placed", final_points, indices)

    pre_min, pre_max = bounds(pre_points)
    skinned_min, skinned_max = bounds(skinned_points)
    final_min, final_max = bounds(final_points)

    return TraceSummary(
        name=name,
        command_index=command_index,
        parameter_index=parameter_index,
        flags=flags,
        control=control,
        base_vertex=base_vertex,
        vertex_count=local_vertex_count,
        triangle_count=index_count // 3,
        vertex_resource_id=vertex_view.resource_id,
        first_lookup_resource_id=first_lookup_view.resource_id,
        remap_resource_id=remap_view.resource_id,
        matrix_resource_id=matrix_view.resource_id,
        cluster_resource_id=cluster_view.resource_id,
        cluster_handle=fields.cluster_handle,
        cluster_index=fields.cluster_index,
        pre_bounds_min=pre_min,
        pre_bounds_max=pre_max,
        skinned_bounds_min=skinned_min,
        skinned_bounds_max=skinned_max,
        final_bounds_min=final_min,
        final_bounds_max=final_max,
        pre_obj=str(pre_obj),
        skinned_obj=str(skinned_obj),
        final_obj=str(final_obj),
    )


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    indirect_records = {command_index: load_indirect_record(command_index) for _, command_index in PRIMARY_DRAWS}
    draw_records = {
        command_index: load_draw_record(indirect_records[command_index][3])
        for _, command_index in PRIMARY_DRAWS
    }

    descriptor_indices: set[int] = set()
    for _, command_index in PRIMARY_DRAWS:
        parameter_index, space103_handle, _, _, _, _, _ = draw_records[command_index]
        fields = load_parameter_fields(parameter_index)
        descriptor_indices.add(SPACE103_BASE + space103_handle)
        descriptor_indices.add(SPACE_BINDLESS_BASE + fields.first_lookup_handle)
        descriptor_indices.add(SPACE_BINDLESS_BASE + fields.remap_handle)
        descriptor_indices.add(SPACE_BINDLESS_BASE + fields.matrix_handle)
        descriptor_indices.add(SPACE_BINDLESS_BASE + fields.cluster_handle)

    views = resolve_descriptor_views(descriptor_indices)
    resource_cache: dict[int, bytes] = {}
    index_bytes = RESOURCE_2074.read_bytes()

    summaries: list[TraceSummary] = []
    for name, command_index in PRIMARY_DRAWS:
        summaries.append(trace_draw(name, command_index, views, resource_cache, index_bytes))

    manifest_path = OUT_DIR / "manifest.json"
    manifest_path.write_text(
        json.dumps({"records": [asdict(summary) for summary in summaries]}, indent=2),
        encoding="utf-8",
        newline="\n",
    )

    print(f"wrote {len(summaries)} primary skin traces to {OUT_DIR}")
    print(f"manifest: {manifest_path}")
    for summary in summaries:
        print(
            f"{summary.name}: param={summary.parameter_index} flags={summary.flags} "
            f"cluster=({summary.cluster_handle},{summary.cluster_index}) "
            f"pre={summary.pre_bounds_min} -> {summary.pre_bounds_max} "
            f"final={summary.final_bounds_min} -> {summary.final_bounds_max}"
        )


if __name__ == "__main__":
    main()
