#!/usr/bin/env python3
"""Dump the alternate dragon-like 8054 view from runtime buffers.

This family is interesting because:

- draw records 320..327 all use handle 8054
- handle 8054 resolves to resource 16288, same backing resource as 6804
- params 113..120 line up with the dragon eye/body/head bbox family
- live indirect records exist for 320..327 in resource 7968

The goal is to determine whether 8054 is an alternate dragon LOD/view/pass
rather than a bird/world-fauna path.
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
OUT_DIR = ROOT / "output" / "runtime_8054_family"

RESOURCE_242 = PIX_RESOURCES / "resource_242.bin"
RESOURCE_7879 = PIX_RESOURCES / "resource_7879.bin"
RESOURCE_7968 = PIX_RESOURCES / "resource_7968.bin"
RESOURCE_2074 = PIX_RESOURCES / "resource_2074.bin"

SPACE103_BASE = 368000
STRIDE_242 = 156
STRIDE_7879 = 28
STRIDE_7968 = 40
VERTEX_STRIDE = 40
IB_HEAP_OFFSET = 7_390_720

ALT_DRAWS = [
    ("Eyeright", 320),
    ("Eyeleft", 321),
    ("Body_02", 322),
    ("back", 323),
    ("Body", 324),
    ("Leg", 325),
    ("Wing", 326),
    ("Head", 327),
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
class DrawSummary:
    name: str
    command_index: int
    parameter_index: int
    space103_handle: int
    base_vertex: int
    vertex_count: int
    index_count: int
    triangle_count: int
    vertex_resource_id: int
    index_resource_id: int
    bounds_min: tuple[float, float, float]
    bounds_max: tuple[float, float, float]
    output_obj: str


def resolve_space103_descriptors(handles: set[int]) -> dict[int, DescriptorView]:
    wanted = {SPACE103_BASE + handle: handle for handle in handles}
    resolved: dict[int, DescriptorView] = {}
    for path in sorted(GPU_ANALYSIS.glob("Descriptors_*.cpp")):
        text = path.read_text(encoding="utf-8")
        for match in DESCRIPTOR_RE.finditer(text):
            descriptor_index = int(match.group(2))
            if descriptor_index not in wanted:
                continue
            handle = wanted[descriptor_index]
            resolved[handle] = DescriptorView(
                descriptor_index=descriptor_index,
                resource_id=int(match.group(1)),
                first_element=int(match.group(3)),
                num_elements=int(match.group(4)),
                stride=int(match.group(5)),
                source_file=path.name,
            )
    missing = sorted(handles - set(resolved))
    if missing:
        raise ValueError(f"missing descriptor resolution for handles {missing}")
    return resolved


def read_bbox(parameter_index: int, data_242: bytes) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    offset = parameter_index * STRIDE_242
    bbox_min = struct.unpack_from("<3f", data_242, offset + 0)
    bbox_dim = struct.unpack_from("<3f", data_242, offset + 16)
    return bbox_min, bbox_dim


def dequantize_vertex(raw40: bytes, bbox_min: tuple[float, float, float], bbox_dim: tuple[float, float, float]) -> tuple[float, float, float]:
    packed_xy, packed_zw = struct.unpack_from("<II", raw40, 0)
    u16_x = packed_xy & 0xFFFF
    u16_y = (packed_xy >> 16) & 0xFFFF
    u16_z = packed_zw & 0xFFFF
    return (
        bbox_min[0] + (u16_x / 32767.0) * bbox_dim[0],
        bbox_min[1] + (u16_y / 32767.0) * bbox_dim[1],
        bbox_min[2] + (u16_z / 32767.0) * bbox_dim[2],
    )


def load_indirect_record(command_index: int, data_7968: bytes) -> tuple[int, int, int, int, int, int, int, int]:
    offset = command_index * STRIDE_7968
    ib_gpuva, ib_size_bytes, ib_format = struct.unpack_from("<QII", data_7968, offset + 0)
    constant0 = struct.unpack_from("<I", data_7968, offset + 16)[0]
    index_count, instance_count, start_index, base_vertex, start_instance = struct.unpack_from(
        "<IIiII", data_7968, offset + 20
    )
    return ib_gpuva, ib_size_bytes, ib_format, constant0, index_count, instance_count, start_index, base_vertex


def load_draw_record(record_index: int, data_7879: bytes) -> tuple[int, int, int, int, int, int, int]:
    return struct.unpack_from("<7I", data_7879, record_index * STRIDE_7879)


def write_obj(path: Path, name: str, points: list[tuple[float, float, float]], indices: list[int]) -> None:
    with path.open("w", encoding="ascii", newline="\n") as handle:
        handle.write(f"# runtime 8054 family mesh: {name}\n")
        for x, y, z in points:
            handle.write(f"v {x:.9f} {y:.9f} {z:.9f}\n")
        for i in range(0, len(indices), 3):
            handle.write(f"f {indices[i] + 1} {indices[i + 1] + 1} {indices[i + 2] + 1}\n")


def bounds(points: list[tuple[float, float, float]]) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    zs = [p[2] for p in points]
    return (min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs))


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    data_242 = RESOURCE_242.read_bytes()
    data_7879 = RESOURCE_7879.read_bytes()
    data_7968 = RESOURCE_7968.read_bytes()
    data_2074 = RESOURCE_2074.read_bytes()

    first_record = load_draw_record(ALT_DRAWS[0][1], data_7879)
    handle = first_record[1]
    view = resolve_space103_descriptors({handle})[handle]
    vertex_resource = (PIX_RESOURCES / f"resource_{view.resource_id}.bin").read_bytes()

    first_indirect = load_indirect_record(ALT_DRAWS[0][1], data_7968)
    heap_base_gpuva = first_indirect[0] - IB_HEAP_OFFSET
    if heap_base_gpuva <= 0:
        raise ValueError(f"invalid derived heap base gpuva 0x{heap_base_gpuva:x}")

    draw_records = {command_index: load_draw_record(command_index, data_7879) for _, command_index in ALT_DRAWS}
    base_vertices = [draw_records[command_index][2] for _, command_index in ALT_DRAWS]
    base_vertices.append(view.num_elements)
    vertex_counts = [base_vertices[i + 1] - base_vertices[i] for i in range(len(ALT_DRAWS))]

    summaries: list[DrawSummary] = []
    for (name, command_index), vertex_count in zip(ALT_DRAWS, vertex_counts):
        parameter_index, record_handle, record_base_vertex, aux_handle, aux_base, control, flags = draw_records[command_index]
        ib_gpuva, _ib_size_bytes, ib_format, constant0, index_count, instance_count, start_index, indirect_base_vertex = load_indirect_record(
            command_index, data_7968
        )
        if record_handle != handle:
            raise ValueError(f"{name}: mixed handle family encountered")
        if constant0 != command_index:
            raise ValueError(f"{name}: indirect constant mismatch")
        if record_base_vertex != indirect_base_vertex:
            raise ValueError(f"{name}: base vertex mismatch between 7879 and 7968")
        if instance_count != 1 or ib_format != 57:
            raise ValueError(f"{name}: unexpected indirect draw args")

        bbox_min, bbox_dim = read_bbox(parameter_index, data_242)
        points: list[tuple[float, float, float]] = []
        for local_index in range(vertex_count):
            absolute_index = view.first_element + record_base_vertex + local_index
            raw40 = vertex_resource[absolute_index * view.stride : (absolute_index + 1) * view.stride]
            points.append(dequantize_vertex(raw40, bbox_min, bbox_dim))

        ib_offset = ib_gpuva - heap_base_gpuva
        raw_indices = struct.unpack_from(f"<{index_count}H", data_2074, ib_offset)
        local_indices = [index - record_base_vertex for index in raw_indices]

        out_obj = OUT_DIR / f"{name.lower()}_triangles.obj"
        write_obj(out_obj, name, points, local_indices)
        bmin, bmax = bounds(points)
        summaries.append(
            DrawSummary(
                name=name,
                command_index=command_index,
                parameter_index=parameter_index,
                space103_handle=handle,
                base_vertex=record_base_vertex,
                vertex_count=vertex_count,
                index_count=index_count,
                triangle_count=index_count // 3,
                vertex_resource_id=view.resource_id,
                index_resource_id=2074,
                bounds_min=bmin,
                bounds_max=bmax,
                output_obj=str(out_obj),
            )
        )

    manifest = {
        "handle": handle,
        "descriptor_index": view.descriptor_index,
        "resource_id": view.resource_id,
        "first_element": view.first_element,
        "num_elements": view.num_elements,
        "stride": view.stride,
        "draws": [asdict(summary) for summary in summaries],
    }
    (OUT_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="ascii")
    print(f"Wrote {OUT_DIR / 'manifest.json'}")
    for summary in summaries:
        print(
            f"{summary.name}: param={summary.parameter_index} base={summary.base_vertex} verts={summary.vertex_count} "
            f"indices={summary.index_count} bounds_min={summary.bounds_min} bounds_max={summary.bounds_max}"
        )


if __name__ == "__main__":
    main()
