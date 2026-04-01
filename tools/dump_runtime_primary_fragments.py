#!/usr/bin/env python3
"""Dump the live primary-family dragon fragments from runtime PIX buffers.

Unlike the shadow-family path, the live primary records 39..44 are tiny draws.
This script reconstructs those exact fragments from:

- resource 7968: live indirect draw records
- resource 7879: live draw records / parameter selection
- resources 15390 / 15486: primary-family runtime vertex buffers
- resource 2074: live index-buffer backing store on heap 2073

This stays on the runtime path only. No PAC assumptions.
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
OUT_DIR = ROOT / "output" / "runtime_primary_fragments"

RESOURCE_242 = PIX_RESOURCES / "resource_242.bin"
RESOURCE_7879 = PIX_RESOURCES / "resource_7879.bin"
RESOURCE_7968 = PIX_RESOURCES / "resource_7968.bin"
RESOURCE_2074 = PIX_RESOURCES / "resource_2074.bin"

SPACE103_BASE = 368000
STRIDE_242 = 156
STRIDE_7879 = 28
STRIDE_7968 = 40
VERTEX_STRIDE = 40
HEAP_2073_BASE_GPUVA = 0x2E0000000

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
class FragmentSummary:
    name: str
    command_index: int
    parameter_index: int
    space103_handle: int
    flags: int
    control: int
    base_vertex: int
    vertex_count: int
    triangle_count: int
    vertex_resource_id: int
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


def load_indirect_record(command_index: int) -> tuple[int, int, int, int, int, int, int, int, int]:
    data = RESOURCE_7968.read_bytes()
    offset = command_index * STRIDE_7968
    ib_gpuva, ib_size_bytes, ib_format = struct.unpack_from("<QII", data, offset + 0)
    constant0 = struct.unpack_from("<I", data, offset + 16)[0]
    return (ib_gpuva, ib_size_bytes, ib_format, constant0, *struct.unpack_from("<IIiII", data, offset + 20))


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


def write_obj(path: Path, name: str, points: list[tuple[float, float, float]], indices: list[int]) -> None:
    with path.open("w", encoding="ascii", newline="\n") as handle:
        handle.write(f"# runtime primary fragment: {name}\n")
        for x, y, z in points:
            handle.write(f"v {x:.9f} {y:.9f} {z:.9f}\n")
        for i in range(0, len(indices), 3):
            handle.write(f"f {indices[i] + 1} {indices[i + 1] + 1} {indices[i + 2] + 1}\n")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    indirect_records = {command_index: load_indirect_record(command_index) for _, command_index in PRIMARY_DRAWS}
    draw_records = {
        command_index: load_draw_record(indirect_records[command_index][3])
        for _, command_index in PRIMARY_DRAWS
    }
    handles = {draw_records[command_index][1] for _, command_index in PRIMARY_DRAWS}
    views = resolve_space103_descriptors(handles)
    index_bytes = RESOURCE_2074.read_bytes()
    resource_cache: dict[int, bytes] = {}
    summaries: list[FragmentSummary] = []

    for name, command_index in PRIMARY_DRAWS:
        ib_gpuva, ib_size_bytes, ib_format, constant0, index_count, instance_count, start_index, base_vertex, start_instance = indirect_records[command_index]
        parameter_index, handle, record_base_vertex, aux_handle, aux_base, control, flags = draw_records[command_index]
        if ib_format != 57:
            raise ValueError(f"{name}: unexpected ib format {ib_format}")
        if instance_count != 1 or start_instance != 0:
            raise ValueError(f"{name}: unexpected draw args {indirect_records[command_index]}")
        if base_vertex != record_base_vertex:
            raise ValueError(f"{name}: base vertex mismatch {base_vertex} vs {record_base_vertex}")
        if aux_handle != 0 or aux_base != 0:
            raise ValueError(f"{name}: unexpected aux handle/base {draw_records[command_index]}")

        view = views[handle]
        if view.stride != VERTEX_STRIDE:
            raise ValueError(f"{name}: unexpected stride {view.stride}")

        # Primary-family views are already trimmed. Only keep the local span this draw can touch.
        indices = list(
            struct.unpack_from(
                "<" + ("H" * index_count),
                index_bytes,
                (ib_gpuva - HEAP_2073_BASE_GPUVA) + start_index * 2,
            )
        )
        local_vertex_count = max(indices) + 1 if indices else 0
        if base_vertex + local_vertex_count > view.num_elements:
            raise ValueError(
                f"{name}: base {base_vertex} + local count {local_vertex_count} exceeds view {view.num_elements}"
            )

        bbox_min, bbox_dim = read_bbox(parameter_index)
        vertex_resource = resource_cache.setdefault(view.resource_id, load_resource(view.resource_id))
        points: list[tuple[float, float, float]] = []
        for local_index in range(local_vertex_count):
            absolute_index = view.first_element + base_vertex + local_index
            vertex_offset = absolute_index * view.stride
            raw40 = vertex_resource[vertex_offset : vertex_offset + view.stride]
            points.append(dequantize_vertex(raw40, bbox_min, bbox_dim))

        out_obj = OUT_DIR / f"{name.lower()}.obj"
        write_obj(out_obj, name, points, indices)
        bmin, bmax = bounds(points)
        summaries.append(
            FragmentSummary(
                name=name,
                command_index=command_index,
                parameter_index=parameter_index,
                space103_handle=handle,
                flags=flags,
                control=control,
                base_vertex=base_vertex,
                vertex_count=local_vertex_count,
                triangle_count=index_count // 3,
                vertex_resource_id=view.resource_id,
                index_buffer_offset=ib_gpuva - HEAP_2073_BASE_GPUVA,
                index_buffer_size_bytes=ib_size_bytes,
                bounds_min=bmin,
                bounds_max=bmax,
                output_obj=str(out_obj),
            )
        )

    manifest_path = OUT_DIR / "manifest.json"
    manifest_path.write_text(
        json.dumps({"records": [asdict(summary) for summary in summaries]}, indent=2),
        encoding="utf-8",
    )

    print(f"wrote {len(summaries)} primary runtime fragments to {OUT_DIR}")
    print(f"manifest: {manifest_path}")
    for summary in summaries:
        print(
            f"{summary.name}: param={summary.parameter_index} handle={summary.space103_handle} "
            f"flags={summary.flags} control={summary.control} verts={summary.vertex_count} "
            f"tris={summary.triangle_count} bounds={summary.bounds_min} -> {summary.bounds_max}"
        )


if __name__ == "__main__":
    main()
