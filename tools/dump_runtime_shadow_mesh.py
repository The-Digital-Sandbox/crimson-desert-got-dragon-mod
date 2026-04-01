#!/usr/bin/env python3
"""Dump the shadow-family runtime dragon mesh directly from PIX buffers.

This does not touch PAC storage. It resolves the live `space103` vertex-buffer
handle from the PIX descriptor heap, reads the extracted runtime resources, and
dequantizes the six main dragon submeshes used by the shadow-family passes.

Current target records are the stable six-draw family in resource 7879:
145..150 -> Body_02, back, Body, Leg, Wing, Head
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
OUT_DIR = ROOT / "output" / "runtime_shadow"

RESOURCE_242 = PIX_RESOURCES / "resource_242.bin"
RESOURCE_7879 = PIX_RESOURCES / "resource_7879.bin"

SPACE103_BASE = 368000
STRIDE_242 = 156
STRIDE_7879 = 28
VERTEX_STRIDE = 40

# Stable six-submesh dragon family inside the shadow-style records.
SHADOW_RECORDS = [
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
class RuntimeSubmeshSummary:
    name: str
    command_index: int
    parameter_index: int
    space103_handle: int
    base_vertex: int
    resource_id: int
    first_element: int
    num_elements: int
    stride: int
    bounds_min: tuple[float, float, float]
    bounds_max: tuple[float, float, float]
    output_obj: str


def load_shadow_records() -> dict[int, tuple[int, int, int, int, int, int, int]]:
    data = RESOURCE_7879.read_bytes()
    records: dict[int, tuple[int, int, int, int, int, int, int]] = {}
    for _, command_index, _ in SHADOW_RECORDS:
        records[command_index] = struct.unpack_from("<7I", data, command_index * STRIDE_7879)
    return records


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
            first_element = int(match.group(3))
            num_elements = int(match.group(4))
            stride = int(match.group(5))
            resolved[wanted[descriptor_index]] = DescriptorView(
                descriptor_index=descriptor_index,
                resource_id=resource_id,
                first_element=first_element,
                num_elements=num_elements,
                stride=stride,
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


def load_resource(resource_id: int) -> bytes:
    path = PIX_RESOURCES / f"resource_{resource_id}.bin"
    if not path.exists():
        raise FileNotFoundError(f"missing extracted PIX resource: {path}")
    return path.read_bytes()


def write_obj(path: Path, points: list[tuple[float, float, float]], name: str) -> None:
    with path.open("w", encoding="ascii", newline="\n") as handle:
        handle.write(f"# runtime shadow point cloud: {name}\n")
        for x, y, z in points:
            handle.write(f"v {x:.9f} {y:.9f} {z:.9f}\n")


def bounds(points: list[tuple[float, float, float]]) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    zs = [p[2] for p in points]
    return (min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs))


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    shadow_records = load_shadow_records()
    handles = {shadow_records[command_index][1] for _, command_index, _ in SHADOW_RECORDS}
    resolved_views = resolve_space103_descriptors(handles)
    resource_cache: dict[int, bytes] = {}

    summaries: list[RuntimeSubmeshSummary] = []

    for name, command_index, expected_count in SHADOW_RECORDS:
        parameter_index, handle, base_vertex, aux_handle, aux_base, control, flags = shadow_records[command_index]
        if aux_handle != 0 or aux_base != 0 or flags != 0:
            raise ValueError(
                f"shadow record {command_index} unexpectedly uses aux path: "
                f"{shadow_records[command_index]}"
            )

        view = resolved_views[handle]
        if view.stride != VERTEX_STRIDE:
            raise ValueError(f"unexpected stride for handle {handle}: {view.stride}")

        resource_bytes = resource_cache.setdefault(view.resource_id, load_resource(view.resource_id))
        bbox_min, bbox_dim = read_bbox(parameter_index)

        start_element = view.first_element + base_vertex
        if base_vertex + expected_count > view.num_elements:
            raise ValueError(
                f"{name}: base_vertex {base_vertex} + count {expected_count} exceeds view count {view.num_elements}"
            )

        points: list[tuple[float, float, float]] = []
        for i in range(expected_count):
            vertex_offset = (start_element + i) * view.stride
            raw40 = resource_bytes[vertex_offset : vertex_offset + view.stride]
            points.append(dequantize_vertex(raw40, bbox_min, bbox_dim))

        out_obj = OUT_DIR / f"{name.lower()}_points.obj"
        write_obj(out_obj, points, name)
        bmin, bmax = bounds(points)
        summaries.append(
            RuntimeSubmeshSummary(
                name=name,
                command_index=command_index,
                parameter_index=parameter_index,
                space103_handle=handle,
                base_vertex=base_vertex,
                resource_id=view.resource_id,
                first_element=view.first_element,
                num_elements=view.num_elements,
                stride=view.stride,
                bounds_min=bmin,
                bounds_max=bmax,
                output_obj=str(out_obj),
            )
        )

    manifest_path = OUT_DIR / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "space103_base": SPACE103_BASE,
                "records": [asdict(summary) for summary in summaries],
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    print(f"wrote {len(summaries)} runtime shadow point clouds to {OUT_DIR}")
    print(f"manifest: {manifest_path}")
    for summary in summaries:
        print(
            f"{summary.name}: cmd={summary.command_index} param={summary.parameter_index} "
            f"handle={summary.space103_handle} res={summary.resource_id} "
            f"base={summary.base_vertex} bounds={summary.bounds_min} -> {summary.bounds_max}"
        )


if __name__ == "__main__":
    main()
