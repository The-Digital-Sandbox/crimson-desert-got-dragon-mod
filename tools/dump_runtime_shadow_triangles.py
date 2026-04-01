#!/usr/bin/env python3
"""Dump the shadow-family runtime dragon mesh with live triangle indices.

This stays on the proven PIX runtime path:

- live indirect draw records from resource 7968 (stride 40)
- live draw records from resource 7879 (stride 28)
- live expanded vertex buffer view from resource 16288 (stride 40)
- live index buffer backing resource 2074 (heap 2073)

The goal is to reconstruct the actual shadow-family dragon triangle meshes
directly from runtime buffers, without falling back to PAC guesses.
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
OUT_DIR = ROOT / "output" / "runtime_shadow_triangles"

RESOURCE_242 = PIX_RESOURCES / "resource_242.bin"
RESOURCE_7879 = PIX_RESOURCES / "resource_7879.bin"
RESOURCE_7968 = PIX_RESOURCES / "resource_7968.bin"
RESOURCE_2074 = PIX_RESOURCES / "resource_2074.bin"

SPACE103_BASE = 368000
STRIDE_242 = 156
STRIDE_7879 = 28
STRIDE_7968 = 40
VERTEX_STRIDE = 40

# Proven from the generated CreateIndirectArgumentBuffer_7968_7 template.
SHADOW_IB_HEAP_OFFSET = 7_390_720

SHADOW_DRAWS = [
    ("Body_02", 145, 2013),
    ("back", 146, 3307),
    ("Body", 147, 2736),
    ("Leg", 148, 4624),
    ("Wing", 149, 6724),
    ("Head", 150, 10258),
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
class RuntimeIndirectRecord:
    command_index: int
    ib_gpuva: int
    ib_size_bytes: int
    ib_format: int
    constant0: int
    index_count: int
    instance_count: int
    start_index: int
    base_vertex: int
    start_instance: int


@dataclass(frozen=True)
class RuntimeTriangleSummary:
    name: str
    command_index: int
    parameter_index: int
    space103_handle: int
    base_vertex: int
    vertex_count: int
    triangle_count: int
    vertex_resource_id: int
    index_resource_id: int
    index_buffer_offset: int
    index_buffer_size_bytes: int
    bounds_min: tuple[float, float, float]
    bounds_max: tuple[float, float, float]
    output_obj: str


def resolve_space103_descriptors(handles: set[int]) -> dict[int, DescriptorView]:
    wanted = {SPACE103_BASE + handle: handle for handle in handles}
    resolved: dict[int, DescriptorView] = {}

    for path in sorted(GPU_ANALYSIS.glob("Descriptors_*.cpp")):
        text = path.read_text(encoding="utf-8")
        for match in DESCRIPTOR_RE.finditer(text):
            resource_id = int(match.group(1))
            descriptor_index = int(match.group(2))
            if descriptor_index not in wanted:
                continue
            resolved[wanted[descriptor_index]] = DescriptorView(
                descriptor_index=descriptor_index,
                resource_id=resource_id,
                first_element=int(match.group(3)),
                num_elements=int(match.group(4)),
                stride=int(match.group(5)),
                source_file=path.name,
            )

    missing = sorted(handles - set(resolved))
    if missing:
        raise ValueError(f"missing descriptor resolution for space103 handles: {missing}")
    return resolved


def read_bbox(parameter_index: int) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    data = RESOURCE_242.read_bytes()
    offset = parameter_index * STRIDE_242
    bbox_min = struct.unpack_from("<3f", data, offset + 0)
    bbox_dim = struct.unpack_from("<3f", data, offset + 16)
    return bbox_min, bbox_dim


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


def load_indirect_record(command_index: int) -> RuntimeIndirectRecord:
    data = RESOURCE_7968.read_bytes()
    offset = command_index * STRIDE_7968
    ib_gpuva, ib_size_bytes, ib_format = struct.unpack_from("<QII", data, offset + 0)
    constant0 = struct.unpack_from("<I", data, offset + 16)[0]
    index_count, instance_count, start_index, base_vertex, start_instance = struct.unpack_from(
        "<IIiII", data, offset + 20
    )
    return RuntimeIndirectRecord(
        command_index=command_index,
        ib_gpuva=ib_gpuva,
        ib_size_bytes=ib_size_bytes,
        ib_format=ib_format,
        constant0=constant0,
        index_count=index_count,
        instance_count=instance_count,
        start_index=start_index,
        base_vertex=base_vertex,
        start_instance=start_instance,
    )


def load_draw_record(record_index: int) -> tuple[int, int, int, int, int, int, int]:
    data = RESOURCE_7879.read_bytes()
    return struct.unpack_from("<7I", data, record_index * STRIDE_7879)


def load_resource(resource_id: int) -> bytes:
    path = PIX_RESOURCES / f"resource_{resource_id}.bin"
    if not path.exists():
        raise FileNotFoundError(f"missing extracted PIX resource: {path}")
    return path.read_bytes()


def bounds(points: list[tuple[float, float, float]]) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    zs = [p[2] for p in points]
    return (min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs))


def write_obj(
    path: Path,
    name: str,
    points: list[tuple[float, float, float]],
    indices: list[int],
) -> None:
    with path.open("w", encoding="ascii", newline="\n") as handle:
        handle.write(f"# runtime shadow triangle mesh: {name}\n")
        for x, y, z in points:
            handle.write(f"v {x:.9f} {y:.9f} {z:.9f}\n")
        for i in range(0, len(indices), 3):
            handle.write(f"f {indices[i] + 1} {indices[i + 1] + 1} {indices[i + 2] + 1}\n")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    live_records = [load_indirect_record(command_index) for _, command_index, _ in SHADOW_DRAWS]
    heap_base_gpuva = live_records[0].ib_gpuva - SHADOW_IB_HEAP_OFFSET
    if heap_base_gpuva <= 0:
        raise ValueError(f"derived invalid heap base gpuva: 0x{heap_base_gpuva:x}")

    draw_records = {record.constant0: load_draw_record(record.constant0) for record in live_records}
    handles = {draw_records[record.constant0][1] for record in live_records}
    resolved_views = resolve_space103_descriptors(handles)
    index_bytes = RESOURCE_2074.read_bytes()
    resource_cache: dict[int, bytes] = {}

    summaries: list[RuntimeTriangleSummary] = []

    for name, command_index, expected_vertex_count in SHADOW_DRAWS:
        indirect = next(record for record in live_records if record.command_index == command_index)
        if indirect.instance_count != 1 or indirect.start_instance != 0:
            raise ValueError(f"{name}: unexpected draw args {indirect}")
        if indirect.ib_format != 57:
            raise ValueError(f"{name}: unexpected IB format {indirect.ib_format}")
        if indirect.index_count % 3 != 0:
            raise ValueError(f"{name}: index count {indirect.index_count} is not divisible by 3")

        parameter_index, handle, record_base_vertex, aux_handle, aux_base, control, flags = draw_records[indirect.constant0]
        if aux_handle != 0 or aux_base != 0 or flags != 0:
            raise ValueError(f"{name}: unexpected aux path in draw record {draw_records[indirect.constant0]}")
        if record_base_vertex != indirect.base_vertex:
            raise ValueError(
                f"{name}: base vertex mismatch between 7879 ({record_base_vertex}) and 7968 ({indirect.base_vertex})"
            )

        view = resolved_views[handle]
        if view.stride != VERTEX_STRIDE:
            raise ValueError(f"{name}: unexpected vertex stride {view.stride}")
        if indirect.base_vertex + expected_vertex_count > view.num_elements:
            raise ValueError(
                f"{name}: base_vertex {indirect.base_vertex} + count {expected_vertex_count} exceeds view size {view.num_elements}"
            )

        bbox_min, bbox_dim = read_bbox(parameter_index)
        vertex_resource = resource_cache.setdefault(view.resource_id, load_resource(view.resource_id))

        points: list[tuple[float, float, float]] = []
        for local_index in range(expected_vertex_count):
            absolute_index = view.first_element + indirect.base_vertex + local_index
            vertex_offset = absolute_index * view.stride
            raw40 = vertex_resource[vertex_offset : vertex_offset + view.stride]
            points.append(dequantize_vertex(raw40, bbox_min, bbox_dim))

        ib_resource_offset = indirect.ib_gpuva - heap_base_gpuva
        if ib_resource_offset < 0:
            raise ValueError(f"{name}: negative index buffer offset {ib_resource_offset}")
        if ib_resource_offset + indirect.ib_size_bytes > len(index_bytes):
            raise ValueError(
                f"{name}: index view overruns resource 2074 "
                f"({ib_resource_offset} + {indirect.ib_size_bytes} > {len(index_bytes)})"
            )

        indices = list(
            struct.unpack_from(
                "<" + ("H" * indirect.index_count),
                index_bytes,
                ib_resource_offset + indirect.start_index * 2,
            )
        )
        if max(indices) >= expected_vertex_count:
            raise ValueError(
                f"{name}: local index range 0..{max(indices)} exceeds expected vertex count {expected_vertex_count}"
            )

        out_obj = OUT_DIR / f"{name.lower()}_triangles.obj"
        write_obj(out_obj, name, points, indices)
        bmin, bmax = bounds(points)
        summaries.append(
            RuntimeTriangleSummary(
                name=name,
                command_index=command_index,
                parameter_index=parameter_index,
                space103_handle=handle,
                base_vertex=indirect.base_vertex,
                vertex_count=expected_vertex_count,
                triangle_count=indirect.index_count // 3,
                vertex_resource_id=view.resource_id,
                index_resource_id=2074,
                index_buffer_offset=ib_resource_offset,
                index_buffer_size_bytes=indirect.ib_size_bytes,
                bounds_min=bmin,
                bounds_max=bmax,
                output_obj=str(out_obj),
            )
        )

    manifest_path = OUT_DIR / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "heap_2073_base_gpuva": heap_base_gpuva,
                "shadow_ib_heap_offset": SHADOW_IB_HEAP_OFFSET,
                "records": [asdict(summary) for summary in summaries],
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    print(f"wrote {len(summaries)} runtime shadow triangle meshes to {OUT_DIR}")
    print(f"manifest: {manifest_path}")
    for summary in summaries:
        print(
            f"{summary.name}: cmd={summary.command_index} verts={summary.vertex_count} "
            f"tris={summary.triangle_count} vb_res={summary.vertex_resource_id} "
            f"ib_off={summary.index_buffer_offset} bounds={summary.bounds_min} -> {summary.bounds_max}"
        )


if __name__ == "__main__":
    main()
