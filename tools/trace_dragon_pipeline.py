#!/usr/bin/env python3
"""Trace the Crimson Desert dragon draw pipeline from PIX-generated C++ dumps.

This script reads the generated `gpu-analysis/*.cpp` files directly and emits
two artifacts:

1. A text report for the verified dragon compute->graphics path.
2. A JSON dump of every indirect buffer that contains the six-submesh dragon
   index-count sequence.

The goal is to keep future work grounded in repeatable facts instead of manual
grep sessions.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
GPU_ANALYSIS = ROOT / "gpu-analysis"
OUTPUT_DIR = ROOT / "output" / "dragon_pipeline"
REPORT_PATH = OUTPUT_DIR / "dragon_pipeline_report.txt"
JSON_PATH = OUTPUT_DIR / "dragon_pipeline_report.json"

TARGET_INDEX_COUNTS = [7992, 17007, 13380, 22464, 34902, 51180]


@dataclass
class IndirectCommand:
    ibv_resource: int
    ibv_offset: int
    ibv_size: int
    ibv_format: str
    constant0: int
    index_count: int
    instance_count: int
    start_index: int
    base_vertex: int
    start_instance: int


@dataclass
class IndirectBuffer:
    name: str
    source_file: str
    command_count: int
    commands: list[IndirectCommand] = field(default_factory=list)


@dataclass
class ExecuteIndirectUsage:
    source_file: str
    line_number: int
    command_list: int
    command_signature: int
    max_command_count: int
    buffer_name: str
    count_buffer_name: str
    next_pipeline_state: int | None


@dataclass
class DescriptorRange:
    root_param: int
    range_index: int
    kind: str
    count: int
    base_register: int
    space: int
    descriptor_offset: int


@dataclass
class DescriptorView:
    descriptor_index: int
    heap_id: int
    view_kind: str
    resource_id: int
    format: str
    first_element: int | None
    num_elements: int | None
    stride: int | None
    raw_text: str


@dataclass
class BufferResource:
    resource_id: int
    source_file: str
    size_bytes: int
    flags: str
    reader_chunk: int | None


INDIRECT_FUNCTION_RE = re.compile(r"void (CreateIndirectArgumentBuffer_7968_\d+)\(\)\s*\{", re.M)
EXECUTE_INDIRECT_RE = re.compile(
    r'GetCommandList\((\d+)\)->ExecuteIndirect\(GetCommandSignature\((\d+)\),\s*(\d+),\s*g_indirectArgumentBuffers\["([^"]+)"\]\.Get\(\),\s*0,\s*g_countBuffers\["([^"]+)"\]\.Get\(\),\s*0\);'
)

SET_PSO_RE = re.compile(r"GetCommandList\((\d+)\)->SetPipelineState\(GetPipelineState\((\d+)\)\);")

ROOT_SIG_BLOCK_RE = re.compile(
    r"// ApiObjectId\s*=\s*(\d+)\s*\n\s*\{\n(?P<body>.*?)\n\s*CreateAndTrackRootSignature\(\1,",
    re.S,
)
ROOT_PARAM_BLOCK_RE = re.compile(
    r"rootParameters\[(\d+)\]\.ParameterType = D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE;(?P<body>.*?)(?=rootParameters\[\d+\]\.ParameterType|$)",
    re.S,
)
DESCRIPTOR_RANGE_RE = re.compile(
    r"descriptorRanges\[(\d+)\] = \{ D3D12_DESCRIPTOR_RANGE_TYPE_([A-Z]+),\s*(\d+),\s*(\d+),\s*(\d+),.*?,\s*(\d+) \};"
)

SRV_BUFFER_RE = re.compile(
    r"CreateShaderResourceView_Buffer\(GetResource\((\d+)\)\.Get\(\), GetCpuDescriptor\(g_descriptorHeap_(\d+)\.Get\(\), (\d+)\), DXGI_FORMAT_([A-Z0-9_]+), .*?, \d+, (\d+), (\d+), (\d+), .*?\);"
)
UAV_BUFFER_RE = re.compile(
    r"CreateUnorderedAccessView_Buffer\(GetResource\((\d+)\)\.Get\(\), nullptr, GetCpuDescriptor\(g_descriptorHeap_(\d+)\.Get\(\), (\d+)\), DXGI_FORMAT_([A-Z0-9_]+), .*?, (\d+), (\d+), (\d+), (\d+), .*?\);"
)
CBV_RE = re.compile(
    r"CreateConstantBufferView\(GetCpuDescriptor\(g_descriptorHeap_(\d+)\.Get\(\), (\d+)\), GetGpuva\((\d+),\s*(\d+)\), (\d+)\);"
)

BUFFER_RESOURCE_RE = re.compile(
    r"// ApiObjectId\s*=\s*(\d+)\s*\nvoid CreateAndInitResource_\1\(\)\s*\{\n\s*static D3D12_RESOURCE_DESC resourceDesc = \{ D3D12_RESOURCE_DIMENSION_BUFFER,\s*65536,\s*(\d+),\s*1,\s*1,\s*1,\s*DXGI_FORMAT_[A-Z0-9_]+,\s*\{ 1, 0 \},\s*D3D12_TEXTURE_LAYOUT_ROW_MAJOR,\s*(D3D12_RESOURCE_FLAG_[A-Z_]+) \};(?P<body>.*?)\n\}",
    re.S,
)
RESOURCE_READER_RE = re.compile(r"g_resourceReader->Read\(\w+,\s*(\d+)\);")

PRIMARY_COMPUTE_SECTION_RE = re.compile(
    r"GetCommandList\(17363\)->SetComputeRootSignature\(GetRootSignature\(357\)\);(?P<body>.*?)GetCommandList\(17363\)->Dispatch\(17, 1, 1\);",
    re.S,
)
PRIMARY_GRAPHICS_SECTION_RE = re.compile(
    r"GetCommandList\(17363\)->SetGraphicsRootSignature\(GetRootSignature\(17386\)\);(?P<body>.*?)GetCommandList\(17363\)->ExecuteIndirect\(GetCommandSignature\(17480\), 155, g_indirectArgumentBuffers\[\"7968_7\"\]\.Get\(\), 0, g_countBuffers\[\"7968_7\"\]\.Get\(\), 0\);",
    re.S,
)
ROOT_TABLE_SET_RE = re.compile(
    r"Set(?:Compute|Graphics)RootDescriptorTable\((\d+), GetGpuDescriptor\(g_descriptorHeap_(\d+)\.Get\(\), (\d+)\)\);"
)
ROOT_CBV_RE = re.compile(r"Set(?:Compute|Graphics)RootConstantBufferView\((\d+), GetGpuva\((\d+),\s*(\d+)\)\);")
RESOURCE_BARRIER_RE = re.compile(r"GetResource\((\d+)\)\.Get\(\)")


def extract_function_body(text: str, start_index: int) -> str:
    brace_index = text.find("{", start_index)
    if brace_index < 0:
        raise ValueError("function body start not found")
    depth = 0
    for index in range(brace_index, len(text)):
        char = text[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[brace_index + 1 : index]
    raise ValueError("function body end not found")


def parse_indirect_buffers() -> dict[str, IndirectBuffer]:
    buffers: dict[str, IndirectBuffer] = {}
    for path in sorted(GPU_ANALYSIS.glob("CreateAndInitResources_*.cpp")):
        text = path.read_text(encoding="utf-8")
        for match in INDIRECT_FUNCTION_RE.finditer(text):
            name = match.group(1)
            body = extract_function_body(text, match.start())
            commands: list[IndirectCommand] = []
            pending_ibv: tuple[int, int, int, str] | None = None
            pending_constant: int | None = None
            for line in body.splitlines():
                ibv_match = re.search(
                    r"\*dstArg = \{ GetGpuva\((\d+),\s*(\d+)\),\s*(\d+),\s*(DXGI_FORMAT_[A-Z0-9_]+) \};",
                    line,
                )
                if ibv_match:
                    pending_ibv = (
                        int(ibv_match.group(1)),
                        int(ibv_match.group(2)),
                        int(ibv_match.group(3)),
                        ibv_match.group(4),
                    )
                    continue

                constant_match = re.search(r"UINT constants\[\] = \{ ([^}]*) \};", line)
                if constant_match:
                    constants = [int(part.strip()) for part in constant_match.group(1).split(",") if part.strip()]
                    pending_constant = constants[0] if constants else 0
                    continue

                draw_match = re.search(r"\*dstArg = \{ (\d+),\s*(\d+),\s*(\d+),\s*(\d+),\s*(\d+) \};", line)
                if draw_match and pending_ibv is not None and pending_constant is not None:
                    commands.append(
                        IndirectCommand(
                            ibv_resource=pending_ibv[0],
                            ibv_offset=pending_ibv[1],
                            ibv_size=pending_ibv[2],
                            ibv_format=pending_ibv[3],
                            constant0=pending_constant,
                            index_count=int(draw_match.group(1)),
                            instance_count=int(draw_match.group(2)),
                            start_index=int(draw_match.group(3)),
                            base_vertex=int(draw_match.group(4)),
                            start_instance=int(draw_match.group(5)),
                        )
                    )
                    pending_ibv = None
                    pending_constant = None
            buffers[name] = IndirectBuffer(
                name=name,
                source_file=path.name,
                command_count=len(commands),
                commands=commands,
            )
    return buffers


def find_target_sequence(buffers: dict[str, IndirectBuffer]) -> list[dict]:
    matches: list[dict] = []
    target_len = len(TARGET_INDEX_COUNTS)
    for buffer in sorted(buffers.values(), key=lambda item: item.name):
        counts = [command.index_count for command in buffer.commands]
        for start in range(0, max(0, len(counts) - target_len + 1)):
            window = counts[start : start + target_len]
            if window == TARGET_INDEX_COUNTS:
                matches.append(
                    {
                        "buffer_name": buffer.name,
                        "source_file": buffer.source_file,
                        "start_command_index": start,
                        "commands": [asdict(command) for command in buffer.commands[start : start + target_len]],
                    }
                )
    return matches


def parse_execute_indirect_usages() -> dict[str, list[ExecuteIndirectUsage]]:
    usages: dict[str, list[ExecuteIndirectUsage]] = {}
    for path in sorted(GPU_ANALYSIS.glob("CommandLists_*.cpp")):
        lines = path.read_text(encoding="utf-8").splitlines()
        for index, line in enumerate(lines):
            match = EXECUTE_INDIRECT_RE.search(line)
            if not match:
                continue
            next_pipeline_state = None
            for look_ahead in range(index + 1, min(index + 10, len(lines))):
                pso_match = SET_PSO_RE.search(lines[look_ahead])
                if pso_match:
                    next_pipeline_state = int(pso_match.group(2))
                    break
            usage = ExecuteIndirectUsage(
                source_file=path.name,
                line_number=index + 1,
                command_list=int(match.group(1)),
                command_signature=int(match.group(2)),
                max_command_count=int(match.group(3)),
                buffer_name=match.group(4),
                count_buffer_name=match.group(5),
                next_pipeline_state=next_pipeline_state,
            )
            usages.setdefault(usage.buffer_name, []).append(usage)
    return usages


def parse_root_signature(root_id: int) -> list[DescriptorRange]:
    text = (GPU_ANALYSIS / "FrameResources_000.cpp").read_text(encoding="utf-8")
    for match in ROOT_SIG_BLOCK_RE.finditer(text):
        if int(match.group(1)) != root_id:
            continue
        body = match.group("body")
        ranges: list[DescriptorRange] = []
        for param_match in ROOT_PARAM_BLOCK_RE.finditer(body):
            root_param = int(param_match.group(1))
            param_body = param_match.group("body")
            append_offset = 0
            for range_match in DESCRIPTOR_RANGE_RE.finditer(param_body):
                raw_offset = int(range_match.group(6))
                descriptor_offset = append_offset if raw_offset == 4294967295 else raw_offset
                count = int(range_match.group(3))
                ranges.append(
                    DescriptorRange(
                        root_param=root_param,
                        range_index=int(range_match.group(1)),
                        kind=range_match.group(2),
                        count=count,
                        base_register=int(range_match.group(4)),
                        space=int(range_match.group(5)),
                        descriptor_offset=descriptor_offset,
                    )
                )
                append_offset = descriptor_offset + count
        return ranges
    raise ValueError(f"root signature {root_id} not found")


def parse_descriptor_views() -> dict[int, DescriptorView]:
    views: dict[int, DescriptorView] = {}
    for path in sorted(GPU_ANALYSIS.glob("ModifyDescriptors_*.cpp")):
        text = path.read_text(encoding="utf-8")
        for match in SRV_BUFFER_RE.finditer(text):
            descriptor_index = int(match.group(3))
            views[descriptor_index] = DescriptorView(
                descriptor_index=descriptor_index,
                heap_id=int(match.group(2)),
                view_kind="SRV_BUFFER",
                resource_id=int(match.group(1)),
                format=match.group(4),
                first_element=int(match.group(5)),
                num_elements=int(match.group(6)),
                stride=int(match.group(7)),
                raw_text=match.group(0),
            )
        for match in UAV_BUFFER_RE.finditer(text):
            descriptor_index = int(match.group(3))
            views[descriptor_index] = DescriptorView(
                descriptor_index=descriptor_index,
                heap_id=int(match.group(2)),
                view_kind="UAV_BUFFER",
                resource_id=int(match.group(1)),
                format=match.group(4),
                first_element=int(match.group(5)),
                num_elements=int(match.group(6)),
                stride=int(match.group(7)),
                raw_text=match.group(0),
            )
        for match in CBV_RE.finditer(text):
            descriptor_index = int(match.group(2))
            views[descriptor_index] = DescriptorView(
                descriptor_index=descriptor_index,
                heap_id=int(match.group(1)),
                view_kind="CBV",
                resource_id=int(match.group(3)),
                format="NA",
                first_element=int(match.group(4)),
                num_elements=None,
                stride=int(match.group(5)),
                raw_text=match.group(0),
            )
    return views


def parse_buffer_resources(resource_ids: set[int]) -> dict[int, BufferResource]:
    resources: dict[int, BufferResource] = {}
    for path in sorted(GPU_ANALYSIS.glob("CreateAndInitResources_*.cpp")):
        text = path.read_text(encoding="utf-8")
        for match in BUFFER_RESOURCE_RE.finditer(text):
            resource_id = int(match.group(1))
            if resource_id not in resource_ids:
                continue
            body = match.group("body")
            chunk_match = RESOURCE_READER_RE.search(body)
            resources[resource_id] = BufferResource(
                resource_id=resource_id,
                source_file=path.name,
                size_bytes=int(match.group(2)),
                flags=match.group(3),
                reader_chunk=int(chunk_match.group(1)) if chunk_match else None,
            )
    return resources


def parse_primary_batch() -> dict:
    lines = (GPU_ANALYSIS / "CommandLists_000.cpp").read_text(encoding="utf-8").splitlines()
    compute_start = None
    compute_end = None
    graphics_start = None
    graphics_end = None
    for index, line in enumerate(lines):
        if "GetCommandList(17363)->SetPipelineState(GetPipelineState(17380));" in line:
            compute_start = index
        elif compute_start is not None and "GetCommandList(17363)->Dispatch(17, 1, 1);" in line:
            compute_end = index
        elif "GetCommandList(17363)->SetPipelineState(GetPipelineState(17416));" in line:
            graphics_start = index
        elif graphics_start is not None and 'GetCommandList(17363)->ExecuteIndirect(GetCommandSignature(17480), 155, g_indirectArgumentBuffers["7968_7"].Get(), 0, g_countBuffers["7968_7"].Get(), 0);' in line:
            graphics_end = index
            break
    if None in (compute_start, compute_end, graphics_start, graphics_end):
        raise ValueError("primary dragon batch not found in CommandLists_000.cpp")

    compute_body = "\n".join(lines[compute_start:compute_end + 1])
    graphics_body = "\n".join(lines[graphics_start:graphics_end + 1])

    compute_tables = {}
    for table_match in ROOT_TABLE_SET_RE.finditer(compute_body):
        compute_tables[int(table_match.group(1))] = {
            "heap_id": int(table_match.group(2)),
            "descriptor_index": int(table_match.group(3)),
        }
    graphics_tables = {}
    for table_match in ROOT_TABLE_SET_RE.finditer(graphics_body):
        graphics_tables[int(table_match.group(1))] = {
            "heap_id": int(table_match.group(2)),
            "descriptor_index": int(table_match.group(3)),
        }

    compute_cbvs = []
    for cbv_match in ROOT_CBV_RE.finditer(compute_body):
        compute_cbvs.append(
            {
                "root_param": int(cbv_match.group(1)),
                "resource_id": int(cbv_match.group(2)),
                "resource_offset": int(cbv_match.group(3)),
            }
        )
    graphics_cbvs = []
    for cbv_match in ROOT_CBV_RE.finditer(graphics_body):
        graphics_cbvs.append(
            {
                "root_param": int(cbv_match.group(1)),
                "resource_id": int(cbv_match.group(2)),
                "resource_offset": int(cbv_match.group(3)),
            }
        )

    compute_barrier_resources = [int(value) for value in RESOURCE_BARRIER_RE.findall(compute_body)]
    graphics_barrier_resources = [int(value) for value in RESOURCE_BARRIER_RE.findall(graphics_body)]

    return {
        "compute_root_signature": 357,
        "compute_pipeline_state": 17380,
        "compute_root_cbvs": compute_cbvs,
        "compute_root_tables": compute_tables,
        "compute_dispatch": [17, 1, 1],
        "compute_barrier_resources": compute_barrier_resources,
        "graphics_root_signature": 17386,
        "graphics_pipeline_state": 17416,
        "graphics_root_cbvs": graphics_cbvs,
        "graphics_root_tables": graphics_tables,
        "graphics_barrier_resources": graphics_barrier_resources,
        "execute_indirect": {
            "command_signature": 17480,
            "max_command_count": 155,
            "argument_buffer": "7968_7",
            "count_buffer": "7968_7",
            "followup_pipeline_state": 17403,
        },
    }


def resolve_descriptor(root_ranges: list[DescriptorRange], root_param: int, space: int, register_index: int, table_base: int) -> int | None:
    for descriptor_range in root_ranges:
        if descriptor_range.root_param != root_param:
            continue
        if descriptor_range.space != space:
            continue
        if register_index < descriptor_range.base_register:
            continue
        if register_index >= descriptor_range.base_register + descriptor_range.count:
            continue
        return table_base + descriptor_range.descriptor_offset + (register_index - descriptor_range.base_register)
    return None


def format_descriptor_view(view: DescriptorView | None) -> str:
    if view is None:
        return "missing"
    parts = [view.view_kind, f"res={view.resource_id}", f"fmt={view.format}"]
    if view.num_elements is not None:
        parts.append(f"count={view.num_elements}")
    if view.stride is not None:
        parts.append(f"stride={view.stride}")
    if view.first_element is not None:
        parts.append(f"first={view.first_element}")
    return ", ".join(parts)


def build_report() -> dict:
    indirect_buffers = parse_indirect_buffers()
    six_draw_matches = find_target_sequence(indirect_buffers)
    usages = parse_execute_indirect_usages()
    root_357 = parse_root_signature(357)
    root_17386 = parse_root_signature(17386)
    descriptor_views = parse_descriptor_views()
    primary_batch = parse_primary_batch()

    interesting_resource_ids = {
        118,
        230,
        232,
        242,
        7879,
        7968,
    }
    resources = parse_buffer_resources(interesting_resource_ids)

    graphics_space37_base = primary_batch["graphics_root_tables"][8]["descriptor_index"]
    graphics_t12_desc = resolve_descriptor(root_17386, 8, 37, 12, graphics_space37_base)
    graphics_t16_desc = resolve_descriptor(root_17386, 8, 37, 16, graphics_space37_base)

    compute_space37_base = primary_batch["compute_root_tables"][5]["descriptor_index"]
    compute_space39_base = primary_batch["compute_root_tables"][6]["descriptor_index"]
    compute_t37_desc = resolve_descriptor(root_357, 5, 37, 37, compute_space37_base)
    compute_t59_desc = resolve_descriptor(root_357, 5, 37, 59, compute_space37_base)
    compute_u10_desc = resolve_descriptor(root_357, 6, 39, 10, compute_space39_base)
    compute_u14_desc = resolve_descriptor(root_357, 6, 39, 14, compute_space39_base)
    compute_u39_desc = resolve_descriptor(root_357, 6, 39, 39, compute_space39_base)

    bindless_space103_offset = None
    for descriptor_range in root_17386:
        if descriptor_range.root_param == 16 and descriptor_range.space == 103:
            bindless_space103_offset = descriptor_range.descriptor_offset
            break

    report = {
        "primary_batch": primary_batch,
        "resolved_descriptors": {
            "graphics_t12_space37": {
                "descriptor_index": graphics_t12_desc,
                "view": asdict(descriptor_views[graphics_t12_desc]) if graphics_t12_desc in descriptor_views else None,
            },
            "graphics_t16_space37": {
                "descriptor_index": graphics_t16_desc,
                "view": asdict(descriptor_views[graphics_t16_desc]) if graphics_t16_desc in descriptor_views else None,
            },
            "compute_t37_space37": {
                "descriptor_index": compute_t37_desc,
                "view": asdict(descriptor_views[compute_t37_desc]) if compute_t37_desc in descriptor_views else None,
            },
            "compute_t59_space37": {
                "descriptor_index": compute_t59_desc,
                "view": asdict(descriptor_views[compute_t59_desc]) if compute_t59_desc in descriptor_views else None,
            },
            "compute_u10_space39": {
                "descriptor_index": compute_u10_desc,
                "view": asdict(descriptor_views[compute_u10_desc]) if compute_u10_desc in descriptor_views else None,
            },
            "compute_u14_space39": {
                "descriptor_index": compute_u14_desc,
                "view": asdict(descriptor_views[compute_u14_desc]) if compute_u14_desc in descriptor_views else None,
            },
            "compute_u39_space39": {
                "descriptor_index": compute_u39_desc,
                "view": asdict(descriptor_views[compute_u39_desc]) if compute_u39_desc in descriptor_views else None,
            },
            "bindless_space103_descriptor_offset": bindless_space103_offset,
        },
        "resources": {str(resource_id): asdict(resource) for resource_id, resource in sorted(resources.items())},
        "six_draw_matches": six_draw_matches,
        "six_draw_usages": {
            match["buffer_name"]: [
                asdict(usage)
                for usage in usages.get(match["buffer_name"].replace("CreateIndirectArgumentBuffer_", ""), [])
            ]
            for match in six_draw_matches
        },
    }
    return report


def report_to_text(report: dict) -> str:
    primary = report["primary_batch"]
    resolved = report["resolved_descriptors"]
    resources = report["resources"]
    lines: list[str] = []

    lines.append("Crimson Desert Dragon Pipeline Trace")
    lines.append("===================================")
    lines.append("")
    lines.append("Primary Dragon Batch")
    lines.append("--------------------")
    lines.append(
        f"Compute: CL 17363, RS {primary['compute_root_signature']}, PSO {primary['compute_pipeline_state']}, "
        f"Dispatch {tuple(primary['compute_dispatch'])}"
    )
    lines.append(
        "Compute root tables: "
        + ", ".join(
            f"param {key}=heap{value['heap_id']}:{value['descriptor_index']}"
            for key, value in sorted(primary["compute_root_tables"].items())
        )
    )
    lines.append(
        "Compute barriers touch: "
        + ", ".join(str(resource_id) for resource_id in primary["compute_barrier_resources"])
    )
    lines.append(
        f"Graphics: RS {primary['graphics_root_signature']}, PSO {primary['graphics_pipeline_state']}, "
        f"ExecuteIndirect sig {primary['execute_indirect']['command_signature']} "
        f"via {primary['execute_indirect']['argument_buffer']} ({primary['execute_indirect']['max_command_count']} max draws)"
    )
    lines.append(
        "Graphics root tables: "
        + ", ".join(
            f"param {key}=heap{value['heap_id']}:{value['descriptor_index']}"
            for key, value in sorted(primary["graphics_root_tables"].items())
        )
    )
    lines.append(
        "Graphics barriers touch: "
        + ", ".join(str(resource_id) for resource_id in primary["graphics_barrier_resources"])
    )
    lines.append("")
    lines.append("Resolved Descriptor Slots")
    lines.append("------------------------")
    lines.append(
        f"Graphics t12,space37 -> desc {resolved['graphics_t12_space37']['descriptor_index']} -> "
        f"{format_descriptor_view(DescriptorView(**resolved['graphics_t12_space37']['view']) if resolved['graphics_t12_space37']['view'] else None)}"
    )
    lines.append(
        f"Graphics t16,space37 -> desc {resolved['graphics_t16_space37']['descriptor_index']} -> "
        f"{format_descriptor_view(DescriptorView(**resolved['graphics_t16_space37']['view']) if resolved['graphics_t16_space37']['view'] else None)}"
    )
    lines.append(
        f"Compute t37,space37 -> desc {resolved['compute_t37_space37']['descriptor_index']} -> "
        f"{format_descriptor_view(DescriptorView(**resolved['compute_t37_space37']['view']) if resolved['compute_t37_space37']['view'] else None)}"
    )
    lines.append(
        f"Compute t59,space37 -> desc {resolved['compute_t59_space37']['descriptor_index']} -> "
        f"{format_descriptor_view(DescriptorView(**resolved['compute_t59_space37']['view']) if resolved['compute_t59_space37']['view'] else None)}"
    )
    lines.append(
        f"Compute u10,space39 -> desc {resolved['compute_u10_space39']['descriptor_index']} -> "
        f"{format_descriptor_view(DescriptorView(**resolved['compute_u10_space39']['view']) if resolved['compute_u10_space39']['view'] else None)}"
    )
    lines.append(
        f"Compute u14,space39 -> desc {resolved['compute_u14_space39']['descriptor_index']} -> "
        f"{format_descriptor_view(DescriptorView(**resolved['compute_u14_space39']['view']) if resolved['compute_u14_space39']['view'] else None)}"
    )
    lines.append(
        f"Compute u39,space39 -> desc {resolved['compute_u39_space39']['descriptor_index']} -> "
        f"{format_descriptor_view(DescriptorView(**resolved['compute_u39_space39']['view']) if resolved['compute_u39_space39']['view'] else None)}"
    )
    lines.append(
        f"Bindless space103 base offset inside root param 16: {resolved['bindless_space103_descriptor_offset']}"
    )
    lines.append("")
    lines.append("Interesting Buffer Resources")
    lines.append("---------------------------")
    for resource_id, resource in resources.items():
        lines.append(
            f"Resource {resource_id}: size={resource['size_bytes']} flags={resource['flags']} "
            f"reader_chunk={resource['reader_chunk']} source={resource['source_file']}"
        )
    lines.append("")
    lines.append("Six-Submesh Dragon Sequence Matches")
    lines.append("-----------------------------------")
    if not report["six_draw_matches"]:
        lines.append("No matching buffers found.")
    for match in report["six_draw_matches"]:
        short_name = match["buffer_name"].replace("CreateIndirectArgumentBuffer_", "")
        lines.append(
            f"{short_name} ({match['source_file']}), command index {match['start_command_index']}"
        )
        for command in match["commands"]:
            lines.append(
                f"  const={command['constant0']:>3} idxCount={command['index_count']:>5} "
                f"startIndex={command['start_index']:>5} baseVertex={command['base_vertex']:>5} "
                f"ibv=({command['ibv_resource']},{command['ibv_offset']})"
            )
        usages = report["six_draw_usages"].get(match["buffer_name"], [])
        for usage in usages:
            lines.append(
                f"    used by {usage['source_file']}:{usage['line_number']} "
                f"CL{usage['command_list']} sig={usage['command_signature']} "
                f"max={usage['max_command_count']} nextPSO={usage['next_pipeline_state']}"
            )
    lines.append("")
    lines.append("Strongest Current Implication")
    lines.append("----------------------------")
    lines.append(
        "The primary dragon path is a compute-prepared batch: resource 7879 is rebuilt as a UAV "
        "before the graphics draw and then read back as the VS stride-28 instance buffer."
    )
    lines.append(
        "Resource 7968 is also rewritten in that same compute pass and later consumed as an indirect/UAV raw buffer, "
        "which keeps it as the strongest candidate for the runtime-expanded vertex/command staging contract."
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    report = build_report()
    REPORT_PATH.write_text(report_to_text(report), encoding="utf-8", newline="\n")
    JSON_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8", newline="\n")
    print(f"Report written: {REPORT_PATH}")
    print(f"JSON written:   {JSON_PATH}")
    print(f"Six-draw matches: {len(report['six_draw_matches'])}")
    if report["six_draw_matches"]:
        for match in report["six_draw_matches"]:
            print(
                f"  {match['buffer_name']} @ command {match['start_command_index']} "
                f"({len(match['commands'])} draws)"
            )


if __name__ == "__main__":
    main()
