#!/usr/bin/env python3
"""Trace the proven 6804 shadow-family path.

This script does not try to solve the whole PAC->runtime transform at once.
It records the current hard facts for the six dragon shadow draws:

- live 7879 draw records for commands 145..150
- shared shadow parameter fields from resource_242
- resolved bindless descriptors for the handles those params reference
- runtime 16288 code-slot usage per submesh
- mismatch/correlation between visible PAC codes and runtime 10-bit codes
- a small stage-1 matrix sanity check for the two candidate matrix handles

The goal is to turn the current shader tracing work into a stable artifact that
can guide the next reverse-engineering pass.
"""

from __future__ import annotations

import json
import math
import re
import struct
import sys
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
GPU_ANALYSIS = ROOT / "gpu-analysis"
OUTPUT = ROOT / "output"
PIX_RESOURCES = OUTPUT / "pix_resources"
OUT_DIR = OUTPUT / "shadow_6804_trace"

sys.path.insert(0, str(ROOT / "tools"))
import pac_codec


PAC_PATH = OUTPUT / "dragon.pac"
RESOURCE_242 = PIX_RESOURCES / "resource_242.bin"
RESOURCE_7879 = PIX_RESOURCES / "resource_7879.bin"
RESOURCE_7968 = PIX_RESOURCES / "resource_7968.bin"
RESOURCE_16288 = PIX_RESOURCES / "resource_16288.bin"
RESOURCE_147 = PIX_RESOURCES / "resource_147.bin"
RESOURCE_2085 = PIX_RESOURCES / "resource_2085.bin"
RESOURCE_135 = PIX_RESOURCES / "resource_135.bin"
RESOURCE_2070 = PIX_RESOURCES / "resource_2070.bin"

STRIDE_242 = 156
STRIDE_7879 = 28
STRIDE_7968 = 40
VERTEX_STRIDE = 40
RUNTIME_VIEW_FIRST_ELEMENT = 46222
SPACE_BINDLESS_BASE = 138000
SPACE103_BASE = 368000

SHADOW_SUBMESHES = [
    ("Body_02", 145, "GpuId7153"),
    ("back", 146, "GpuId7154"),
    ("Body", 147, "GpuId7155"),
    ("Leg", 148, "GpuId7156"),
    ("Wing", 149, "GpuId7157"),
    ("Head", 150, "GpuId7158"),
]

AUTOS_KEYS = {
    "%365": "param_u80_handle",
    "%369": "param_u48_base0",
    "%374": "param_u76_lo",
    "%381": "param_u84_word_live",
    "%382": "param_u84_wavefirst_live",
    "%387": "param_u112_handle_live",
    "%388": "param_u112_wavefirst_live",
    "%390": "global_cb_handle33_live",
    "%393": "param_u52_base1_live",
    "%398": "param_u60_base2_live",
    "%402": "param_u104_base_lookup_live",
}

DESCRIPTOR_RE = re.compile(
    r"CreateShaderResourceView_Buffer\("
    r"GetResource\((\d+)\)\.Get\(\),\s*"
    r"GetCpuDescriptor\(g_descriptorHeap_393\.Get\(\),\s*(\d+)\),\s*"
    r"DXGI_FORMAT_UNKNOWN,\s*D3D12_SRV_DIMENSION_BUFFER,\s*"
    r"\d+,\s*(\d+),\s*(\d+),\s*(\d+),"
)

AUTOS_RE = re.compile(r"^(%\d+)\s+integer\s+%\d+\s+(-?\d+)\s+\((\d+)\)$")


@dataclass(frozen=True)
class DescriptorView:
    descriptor_index: int
    resource_id: int
    first_element: int
    num_elements: int
    stride: int
    source_file: str


@dataclass(frozen=True)
class ShadowParameterFields:
    parameter_index: int
    u44: int
    u48: int
    u52: int
    u60: int
    u76: int
    u80: int
    u84: int
    u88: int
    u96: int
    u104: int
    u112: int
    f128: float


@dataclass(frozen=True)
class Stage1Fit:
    matrix_handle_label: str
    resource_id: int
    overall_rmse: float
    per_submesh_rmse: dict[str, float]


@dataclass(frozen=True)
class SubmeshSummary:
    name: str
    gpu_id: str
    command_index: int
    parameter_index: int
    record: tuple[int, int, int, int, int, int, int]
    runtime_base_vertex: int
    vertex_count: int
    active_runtime_code_histogram: dict[int, int]
    exact_first4_matches: int
    sorted_code_overlap_matches: int
    top_first_code_pairs: list[tuple[tuple[int, int], int]]


def shader_source_paths() -> list[Path]:
    return sorted(GPU_ANALYSIS.glob("Descriptors_*.cpp")) + sorted(GPU_ANALYSIS.glob("ModifyDescriptors_*.cpp"))


def resolve_descriptor_views(descriptor_indices: set[int]) -> dict[int, DescriptorView]:
    resolved: dict[int, DescriptorView] = {}
    for path in shader_source_paths():
        text = path.read_text(encoding="utf-8", errors="ignore")
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


def load_draw_record(record_index: int, resource_7879: bytes) -> tuple[int, int, int, int, int, int, int]:
    return struct.unpack_from("<7I", resource_7879, record_index * STRIDE_7879)


def load_indirect_constant(command_index: int, resource_7968: bytes) -> int:
    return struct.unpack_from("<I", resource_7968, command_index * STRIDE_7968 + 16)[0]


def load_shadow_parameter(parameter_index: int, resource_242: bytes) -> ShadowParameterFields:
    offset = parameter_index * STRIDE_242
    return ShadowParameterFields(
        parameter_index=parameter_index,
        u44=struct.unpack_from("<I", resource_242, offset + 44)[0],
        u48=struct.unpack_from("<I", resource_242, offset + 48)[0],
        u52=struct.unpack_from("<I", resource_242, offset + 52)[0],
        u60=struct.unpack_from("<I", resource_242, offset + 60)[0],
        u76=struct.unpack_from("<I", resource_242, offset + 76)[0],
        u80=struct.unpack_from("<I", resource_242, offset + 80)[0],
        u84=struct.unpack_from("<I", resource_242, offset + 84)[0],
        u88=struct.unpack_from("<I", resource_242, offset + 88)[0],
        u96=struct.unpack_from("<I", resource_242, offset + 96)[0],
        u104=struct.unpack_from("<I", resource_242, offset + 104)[0],
        u112=struct.unpack_from("<I", resource_242, offset + 112)[0],
        f128=struct.unpack_from("<f", resource_242, offset + 128)[0],
    )


def load_autos_values() -> dict[str, int]:
    autos_path = GPU_ANALYSIS / "Autos.txt"
    values: dict[str, int] = {}
    for line in autos_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        match = AUTOS_RE.match(line.strip())
        if not match:
            continue
        key = match.group(1)
        if key not in AUTOS_KEYS:
            continue
        values[AUTOS_KEYS[key]] = int(match.group(3))
    return values


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


def decode_runtime_codes(raw40: bytes) -> tuple[list[int], list[int]]:
    u60, u61 = struct.unpack_from("<II", raw40, 20)
    u63, u64 = struct.unpack_from("<II", raw40, 28)
    codes = [
        u60 & 0x3FF,
        (u60 >> 10) & 0x3FF,
        (u60 >> 20) & 0x3FF,
        u61 & 0x3FF,
        (u61 >> 10) & 0x3FF,
        (u61 >> 20) & 0x3FF,
    ]
    weights = [
        u63 & 0xFF,
        (u63 >> 8) & 0xFF,
        (u63 >> 16) & 0xFF,
        (u63 >> 24) & 0xFF,
        u64 & 0xFF,
        (u64 >> 8) & 0xFF,
    ]
    return codes, weights


def load_u32(buffer: bytes, index: int) -> int:
    return struct.unpack_from("<I", buffer, index * 4)[0]


def load_matrix4x4(buffer: bytes, index: int) -> tuple[tuple[float, ...], ...]:
    offset = index * 64
    return (
        struct.unpack_from("<4f", buffer, offset + 0),
        struct.unpack_from("<4f", buffer, offset + 16),
        struct.unpack_from("<4f", buffer, offset + 32),
        struct.unpack_from("<4f", buffer, offset + 48),
    )


def apply_affine_columns(matrix: tuple[tuple[float, ...], ...], point: tuple[float, float, float]) -> tuple[float, float, float]:
    x, y, z = point
    return (
        x * matrix[0][0] + y * matrix[1][0] + z * matrix[2][0] + matrix[3][0],
        x * matrix[0][1] + y * matrix[1][1] + z * matrix[2][1] + matrix[3][1],
        x * matrix[0][2] + y * matrix[1][2] + z * matrix[2][2] + matrix[3][2],
    )


def rmse(values: list[float]) -> float:
    return math.sqrt(sum(value * value for value in values) / len(values)) if values else 0.0


def summarize_submesh(
    name: str,
    gpu_id: str,
    command_index: int,
    record: tuple[int, int, int, int, int, int, int],
    pac_bytes: bytes,
    resource_242: bytes,
    resource_16288: bytes,
) -> SubmeshSummary:
    parameter_index, _handle, base_vertex, _aux_handle, _aux_base, _control, _flags = record
    bbox = next(bbox for bbox in pac_codec.parse_submesh_descriptors(pac_bytes) if bbox.name == name)
    submesh_index = pac_codec.SUBMESH_NAMES.index(name)
    pac_base = pac_codec.SUBMESH_BASES[submesh_index]
    vertex_count = pac_codec.SUBMESH_VERTEX_COUNTS[submesh_index]
    runtime_base = RUNTIME_VIEW_FIRST_ELEMENT + base_vertex

    bbox_offset = parameter_index * STRIDE_242
    bbox_min = struct.unpack_from("<3f", resource_242, bbox_offset + 0)
    bbox_dim = struct.unpack_from("<3f", resource_242, bbox_offset + 16)

    runtime_slot_hist = Counter()
    first_code_pairs = Counter()
    exact_first4_matches = 0
    sorted_overlap_matches = 0

    for local_index in range(vertex_count):
        pac_vertex = pac_codec.decode_vertex(pac_bytes, pac_base + local_index, bbox)
        runtime_raw = resource_16288[(runtime_base + local_index) * VERTEX_STRIDE : (runtime_base + local_index + 1) * VERTEX_STRIDE]
        runtime_codes, runtime_weights = decode_runtime_codes(runtime_raw)

        active_runtime_codes = [code for code, weight in zip(runtime_codes, runtime_weights) if weight > 0]
        runtime_slot_hist[len(active_runtime_codes)] += 1

        if tuple(pac_vertex.bone_idx) == tuple(runtime_codes[:4]):
            exact_first4_matches += 1

        pac_codes_sorted = sorted(code for code, weight in zip(pac_vertex.bone_idx, pac_vertex.bone_wt) if weight > 0)
        runtime_codes_sorted = sorted(active_runtime_codes)
        if pac_codes_sorted == runtime_codes_sorted[: len(pac_codes_sorted)]:
            sorted_overlap_matches += 1

        pac_first = next((code for code, weight in zip(pac_vertex.bone_idx, pac_vertex.bone_wt) if weight > 0), None)
        runtime_first = next((code for code, weight in zip(runtime_codes, runtime_weights) if weight > 0), None)
        if pac_first is not None and runtime_first is not None:
            first_code_pairs[(pac_first, runtime_first)] += 1

    return SubmeshSummary(
        name=name,
        gpu_id=gpu_id,
        command_index=command_index,
        parameter_index=parameter_index,
        record=record,
        runtime_base_vertex=runtime_base,
        vertex_count=vertex_count,
        active_runtime_code_histogram=dict(sorted(runtime_slot_hist.items())),
        exact_first4_matches=exact_first4_matches,
        sorted_code_overlap_matches=sorted_overlap_matches,
        top_first_code_pairs=first_code_pairs.most_common(12),
    )


def stage1_fit(
    matrix_handle_label: str,
    matrix_buffer: bytes,
    shadow_summaries: list[SubmeshSummary],
    pac_bytes: bytes,
    resource_242: bytes,
    resource_16288: bytes,
    first_lookup_buffer: bytes,
    remap_buffer: bytes,
    base0: int,
    base1: int,
    base_lookup: int,
) -> Stage1Fit:
    per_submesh_rmse: dict[str, float] = {}
    all_errors: list[float] = []

    for summary in shadow_summaries:
        bbox = next(bbox for bbox in pac_codec.parse_submesh_descriptors(pac_bytes) if bbox.name == summary.name)
        submesh_index = pac_codec.SUBMESH_NAMES.index(summary.name)
        pac_base = pac_codec.SUBMESH_BASES[submesh_index]
        bbox_offset = summary.parameter_index * STRIDE_242
        bbox_min = struct.unpack_from("<3f", resource_242, bbox_offset + 0)
        bbox_dim = struct.unpack_from("<3f", resource_242, bbox_offset + 16)

        sub_errors: list[float] = []
        for local_index in range(summary.vertex_count):
            pac_vertex = pac_codec.decode_vertex(pac_bytes, pac_base + local_index, bbox)
            runtime_raw = resource_16288[(summary.runtime_base_vertex + local_index) * VERTEX_STRIDE : (summary.runtime_base_vertex + local_index + 1) * VERTEX_STRIDE]
            runtime_pos = dequantize_runtime_pos(runtime_raw, bbox_min, bbox_dim)

            weighted_predictions: list[tuple[int, tuple[float, float, float]]] = []
            for code, weight in zip(pac_vertex.bone_idx, pac_vertex.bone_wt):
                if weight <= 0:
                    continue
                lookup0 = load_u32(first_lookup_buffer, base0 + code)
                lookup1 = load_u32(remap_buffer, base_lookup + lookup0)
                matrix = load_matrix4x4(matrix_buffer, base1 + lookup1)
                weighted_predictions.append((weight, apply_affine_columns(matrix, pac_vertex.pos)))

            if not weighted_predictions:
                continue

            weight_sum = sum(weight for weight, _prediction in weighted_predictions)
            predicted = tuple(
                sum(weight * prediction[axis] for weight, prediction in weighted_predictions) / weight_sum
                for axis in range(3)
            )
            delta = math.dist(predicted, runtime_pos)
            sub_errors.append(delta)
            all_errors.append(delta)

        per_submesh_rmse[summary.name] = rmse(sub_errors)

    return Stage1Fit(
        matrix_handle_label=matrix_handle_label,
        resource_id=135 if matrix_handle_label == "handle9" else 2070,
        overall_rmse=rmse(all_errors),
        per_submesh_rmse=per_submesh_rmse,
    )


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    pac_bytes = PAC_PATH.read_bytes()
    resource_242 = RESOURCE_242.read_bytes()
    resource_7879 = RESOURCE_7879.read_bytes()
    resource_7968 = RESOURCE_7968.read_bytes()
    resource_16288 = RESOURCE_16288.read_bytes()
    resource_147 = RESOURCE_147.read_bytes()
    resource_2085 = RESOURCE_2085.read_bytes()
    resource_135 = RESOURCE_135.read_bytes()
    resource_2070 = RESOURCE_2070.read_bytes()
    autos_values = load_autos_values()

    first_constant = load_indirect_constant(SHADOW_SUBMESHES[0][1], resource_7968)
    shared_record = load_draw_record(first_constant, resource_7879)
    shared_param = load_shadow_parameter(shared_record[0], resource_242)

    descriptor_indices = {
        SPACE_BINDLESS_BASE + 24,
        SPACE_BINDLESS_BASE + 31,
        SPACE_BINDLESS_BASE + 6,
        SPACE_BINDLESS_BASE + 8,
        SPACE_BINDLESS_BASE + 9,
        SPACE_BINDLESS_BASE + 10,
        SPACE_BINDLESS_BASE + 41,
        SPACE103_BASE + 6804,
    }
    descriptor_views = resolve_descriptor_views(descriptor_indices)

    shadow_summaries: list[SubmeshSummary] = []
    for name, command_index, gpu_id in SHADOW_SUBMESHES:
        constant0 = load_indirect_constant(command_index, resource_7968)
        record = load_draw_record(constant0, resource_7879)
        shadow_summaries.append(
            summarize_submesh(
                name=name,
                gpu_id=gpu_id,
                command_index=command_index,
                record=record,
                pac_bytes=pac_bytes,
                resource_242=resource_242,
                resource_16288=resource_16288,
            )
        )

    fit_handle9 = stage1_fit(
        matrix_handle_label="handle9",
        matrix_buffer=resource_135,
        shadow_summaries=shadow_summaries,
        pac_bytes=pac_bytes,
        resource_242=resource_242,
        resource_16288=resource_16288,
        first_lookup_buffer=resource_147,
        remap_buffer=resource_2085,
        base0=shared_param.u48,
        base1=shared_param.u52,
        base_lookup=shared_param.u104,
    )
    fit_handle10 = stage1_fit(
        matrix_handle_label="handle10",
        matrix_buffer=resource_2070,
        shadow_summaries=shadow_summaries,
        pac_bytes=pac_bytes,
        resource_242=resource_242,
        resource_16288=resource_16288,
        first_lookup_buffer=resource_147,
        remap_buffer=resource_2085,
        base0=shared_param.u48,
        base1=shared_param.u52,
        base_lookup=shared_param.u104,
    )

    descriptor_summary = {
        "handle24_space20_or_lookup": asdict(descriptor_views[SPACE_BINDLESS_BASE + 24]),
        "handle31_space20_or_remap": asdict(descriptor_views[SPACE_BINDLESS_BASE + 31]),
        "handle6_space21_optional": asdict(descriptor_views[SPACE_BINDLESS_BASE + 6]),
        "handle8_space21_optional": asdict(descriptor_views[SPACE_BINDLESS_BASE + 8]),
        "handle9_space21_or_stage1": asdict(descriptor_views[SPACE_BINDLESS_BASE + 9]),
        "handle10_space21_candidate": asdict(descriptor_views[SPACE_BINDLESS_BASE + 10]),
        "handle41_space15_or_cluster": asdict(descriptor_views[SPACE_BINDLESS_BASE + 41]),
        "handle6804_space103_runtime_view": asdict(descriptor_views[SPACE103_BASE + 6804]),
    }

    report_lines = [
        "6804 shadow-family trace",
        "========================",
        "",
        "Shared shadow parameter fields from resource_242",
        "-----------------------------------------------",
        f"parameter index: {shared_param.parameter_index}",
        f"u44 : {shared_param.u44} (0x{shared_param.u44:08X})",
        f"u48 : {shared_param.u48} (0x{shared_param.u48:08X})",
        f"u52 : {shared_param.u52} (0x{shared_param.u52:08X})",
        f"u60 : {shared_param.u60} (0x{shared_param.u60:08X})",
        f"u76 : {shared_param.u76} (0x{shared_param.u76:08X})",
        f"u80 : {shared_param.u80} (0x{shared_param.u80:08X})",
        f"u84 : {shared_param.u84} (0x{shared_param.u84:08X})",
        f"u88 : {shared_param.u88} (0x{shared_param.u88:08X})",
        f"u96 : {shared_param.u96} (0x{shared_param.u96:08X})",
        f"u104: {shared_param.u104} (0x{shared_param.u104:08X})",
        f"u112: {shared_param.u112} (0x{shared_param.u112:08X})",
        f"f128: {shared_param.f128:.6f}",
        "",
        "Autos.txt live values for the same shadow path",
        "----------------------------------------------",
    ]
    for key in sorted(autos_values):
        report_lines.append(f"{key}: {autos_values[key]}")
    report_lines.extend(
        [
            "",
            "Key discrepancy",
            "---------------",
            f"resource_242 u84 raw word          : {shared_param.u84} (0x{shared_param.u84:08X})",
            f"Autos wave-read u84 live word      : {autos_values.get('param_u84_wavefirst_live', -1)}",
            f"resource_242 u112 raw handle       : {shared_param.u112}",
            f"Autos wave-read u112 live handle   : {autos_values.get('param_u112_wavefirst_live', -1)}",
            "",
            "Resolved descriptor views",
            "-------------------------",
        ]
    )
    for label, view in descriptor_summary.items():
        report_lines.append(
            f"{label}: desc={view['descriptor_index']} resource={view['resource_id']} "
            f"first={view['first_element']} count={view['num_elements']} stride={view['stride']} "
            f"source={view['source_file']}"
        )
    report_lines.extend(
        [
            "",
            "Stage-1 PAC->runtime sanity check using visible PAC codes",
            "---------------------------------------------------------",
            f"handle9/resource135 overall rmse : {fit_handle9.overall_rmse:.6f}",
            f"handle10/resource2070 overall rmse: {fit_handle10.overall_rmse:.6f}",
            "per-submesh rmse (handle9):",
        ]
    )
    for name, value in fit_handle9.per_submesh_rmse.items():
        report_lines.append(f"  {name:7s} {value:.6f}")
    report_lines.append("per-submesh rmse (handle10):")
    for name, value in fit_handle10.per_submesh_rmse.items():
        report_lines.append(f"  {name:7s} {value:.6f}")

    report_lines.extend(["", "Per-submesh runtime-code summary", "-------------------------------"])
    for summary in shadow_summaries:
        report_lines.extend(
            [
                f"{summary.name} ({summary.gpu_id})",
                f"  command/index/param: {summary.command_index} / {summary.record[2]} / {summary.parameter_index}",
                f"  active runtime slots: {summary.active_runtime_code_histogram}",
                f"  exact first4 PAC/runtime code matches: {summary.exact_first4_matches} / {summary.vertex_count}",
                f"  sorted PAC/runtime code overlaps:      {summary.sorted_code_overlap_matches} / {summary.vertex_count}",
                f"  top first-code pairs: {summary.top_first_code_pairs}",
            ]
        )

    report_path = OUT_DIR / "report.txt"
    report_path.write_text("\n".join(report_lines) + "\n", encoding="utf-8", newline="\n")

    manifest_path = OUT_DIR / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "shared_param": asdict(shared_param),
                "autos_values": autos_values,
                "descriptor_views": descriptor_summary,
                "stage1_fit": {
                    "handle9": asdict(fit_handle9),
                    "handle10": asdict(fit_handle10),
                },
                "submeshes": [asdict(summary) for summary in shadow_summaries],
            },
            indent=2,
        ),
        encoding="utf-8",
        newline="\n",
    )

    print(f"wrote {report_path}")
    print(f"wrote {manifest_path}")


if __name__ == "__main__":
    main()
