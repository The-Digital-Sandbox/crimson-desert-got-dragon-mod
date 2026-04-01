#!/usr/bin/env python3
"""Trace the known Autos.txt sample vertex through the 6804 shadow path.

This script anchors on the debugger sample from Autos.txt for the shadow Wing
draw (GpuId7157). It reconstructs the sampled vertex stage-by-stage and
compares each stage directly to the live debugger values.

Purpose:
- prove where the first non-trivial mismatch appears
- separate "bad math" from "live state provenance mismatch"
"""

from __future__ import annotations

import json
import struct
from pathlib import Path

import trace_6804_late_position_probe as late_probe
import trace_6804_texcoord1_path as tex1


ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "output"

OUT_DIR = OUTPUT / "shadow_6804_autos_sample"
OUT_REPORT = OUT_DIR / "report.txt"
OUT_MANIFEST = OUT_DIR / "manifest.json"


SAMPLE = {
    "submesh": "Wing",
    "gpu_id": "GpuId7157",
    "command_index": 149,
    "parameter_index": 119,
    "base_vertex": 13130,
    "local_vertex_id": 5921,
    "runtime_vertex_index": 19051,
}

AUTOS = {
    "u96": 2687054,
    "space15_handle": 41,
    "space15_index": 78,
    "2397": 0.470497102,
    "2398": 1.65752995,
    "2399": 0.575100064,
    "2400": -0.427568644,
    "2401": -1.72398496,
    "2402": 0.537620544,
    "2403": -0.696611643,
    "2404": 2.66567731,
    "2405": -0.662503660,
    "2406": -0.331828862,
    "2407": 1.62559032,
    "2408": 2.70799947,
    "2618": 3.75692725,
    "2622": -1.75588393,
    "2626": -0.830035210,
    "183": 0.172910511,
    "184": 0.0,
    "185": 0.984937489,
    "187": -0.0,
    "188": 1.0,
    "189": 0.0,
    "191": -0.984937489,
    "192": -0.0,
    "193": 0.172910511,
    "195": -13.4729309,
    "196": -9.84912109,
    "197": -24.3450623,
    "2736": -12.0057859,
    "2740": -11.6050053,
    "2744": -20.7882462,
    "2782": -0.686866164,
    "2783": -0.0846105590,
    "2784": -0.707243502,
    "2786": 2.68936456e-05,
    "2787": 1.72793400,
    "2788": -0.0688477308,
    "2790": 0.690965950,
    "2791": -0.0841758400,
    "2792": -0.703609705,
    "2794": 0.0,
    "2795": 0.0,
    "2796": 0.0,
    "2800": -6.11791372,
    "2804": -17.2869987,
    "2808": 23.9168034,
}


def tuple_error(a: tuple[float, float, float], b: tuple[float, float, float]) -> tuple[float, float, float]:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


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

    shared_constant = tex1.load_indirect_constant(SAMPLE["command_index"], resource_7968)
    draw_record = tex1.load_draw_record(shared_constant, resource_7879)
    param_index, handle, base_vertex, _aux_handle, _aux_base, control, flags = draw_record

    bbox_offset = param_index * tex1.STRIDE_242
    bbox_min = struct.unpack_from("<3f", resource_242, bbox_offset + 0)
    bbox_dim = struct.unpack_from("<3f", resource_242, bbox_offset + 16)

    runtime_raw = resource_16288[
        (tex1.RUNTIME_VIEW_FIRST_ELEMENT + base_vertex + SAMPLE["local_vertex_id"]) * tex1.VERTEX_STRIDE :
        (tex1.RUNTIME_VIEW_FIRST_ELEMENT + base_vertex + SAMPLE["local_vertex_id"] + 1) * tex1.VERTEX_STRIDE
    ]
    local_pos = tex1.dequantize_runtime_pos(runtime_raw, bbox_min, bbox_dim)

    shared_param_offset = param_index * tex1.STRIDE_242
    base0 = struct.unpack_from("<I", resource_242, shared_param_offset + 48)[0]
    base_lookup = struct.unpack_from("<I", resource_242, shared_param_offset + 104)[0]
    base_late = struct.unpack_from("<I", resource_242, shared_param_offset + 56)[0]
    cluster_word = struct.unpack_from("<I", resource_242, shared_param_offset + 96)[0]
    cluster_index = cluster_word & 0xFFFF
    cluster_handle = cluster_word >> 16

    late_matrix = late_probe.accumulate_late_matrix(
        raw40=runtime_raw,
        resource_147=resource_147,
        resource_2085=resource_2085,
        resource_2070=resource_2070,
        base0=base0,
        base_lookup=base_lookup,
        base_late_matrix=base_late,
    )

    late_pos = late_probe.apply_late_position(late_matrix, local_pos)
    space15_block = late_probe.load_space15_block(resource_80, cluster_index, 64)
    cb14_block = (
        struct.unpack_from("<4f", resource_20, 87 * 16),
        struct.unpack_from("<4f", resource_20, 88 * 16),
        struct.unpack_from("<4f", resource_20, 89 * 16),
        struct.unpack_from("<4f", resource_20, 90 * 16),
    )
    after_space15 = tex1.apply_space15_block(space15_block, late_pos)
    final_world = tex1.apply_cb14_block(cb14_block, after_space15)

    raw_space15 = {
        "183": space15_block[0][0],
        "184": space15_block[0][1],
        "185": space15_block[0][2],
        "187": space15_block[1][0],
        "188": space15_block[1][1],
        "189": space15_block[1][2],
        "191": space15_block[2][0],
        "192": space15_block[2][1],
        "193": space15_block[2][2],
        "195": space15_block[3][0],
        "196": space15_block[3][1],
        "197": space15_block[3][2],
    }
    raw_cb14 = {
        "2782": cb14_block[0][0],
        "2783": cb14_block[0][1],
        "2784": cb14_block[0][3],
        "2786": cb14_block[1][0],
        "2787": cb14_block[1][1],
        "2788": cb14_block[1][3],
        "2790": cb14_block[2][0],
        "2791": cb14_block[2][1],
        "2792": cb14_block[2][3],
        "2794": cb14_block[3][0],
        "2795": cb14_block[3][1],
        "2796": cb14_block[3][3],
    }

    report_lines = [
        "6804 Autos sample trace",
        "=======================",
        "",
        "Sample identity",
        "---------------",
        f"submesh           : {SAMPLE['submesh']}",
        f"gpu_id            : {SAMPLE['gpu_id']}",
        f"command_index     : {SAMPLE['command_index']}",
        f"draw_record       : {draw_record}",
        f"runtime_handle    : {handle}",
        f"base_vertex       : {base_vertex}",
        f"local_vertex_id   : {SAMPLE['local_vertex_id']}",
        f"runtime_vertex    : {tex1.RUNTIME_VIEW_FIRST_ELEMENT + base_vertex + SAMPLE['local_vertex_id']}",
        "",
        "Selector state",
        "--------------",
        f"u96 raw                 : {cluster_word} (0x{cluster_word:08X})",
        f"u96 Autos               : {AUTOS['u96']} (0x{AUTOS['u96']:08X})",
        f"space15 handle raw      : {cluster_handle}",
        f"space15 handle Autos    : {AUTOS['space15_handle']}",
        f"space15 index raw       : {cluster_index}",
        f"space15 index Autos     : {AUTOS['space15_index']}",
        "",
        "Late matrix rows",
        "----------------",
    ]
    for label, row in zip(
        ("2397..2400", "2401..2404", "2405..2408"),
        (
            (late_matrix[0][0], late_matrix[1][0], late_matrix[2][0], late_matrix[3][0]),
            (late_matrix[0][1], late_matrix[1][1], late_matrix[2][1], late_matrix[3][1]),
            (late_matrix[0][2], late_matrix[1][2], late_matrix[2][2], late_matrix[3][2]),
        ),
    ):
        report_lines.append(f"{label} raw   : {row}")
    report_lines.extend(
        [
            f"2397..2400 Autos: ({AUTOS['2397']}, {AUTOS['2398']}, {AUTOS['2399']}, {AUTOS['2400']})",
            f"2401..2404 Autos: ({AUTOS['2401']}, {AUTOS['2402']}, {AUTOS['2403']}, {AUTOS['2404']})",
            f"2405..2408 Autos: ({AUTOS['2405']}, {AUTOS['2406']}, {AUTOS['2407']}, {AUTOS['2408']})",
            "",
            "Stage positions",
            "---------------",
            f"local_pos raw         : {local_pos}",
            f"late_pos raw          : {late_pos}",
            f"late_pos Autos        : ({AUTOS['2618']}, {AUTOS['2622']}, {AUTOS['2626']})",
            f"late_pos delta        : {tuple_error(late_pos, (AUTOS['2618'], AUTOS['2622'], AUTOS['2626']))}",
            f"after_space15 raw     : {after_space15}",
            f"after_space15 Autos   : ({AUTOS['2736']}, {AUTOS['2740']}, {AUTOS['2744']})",
            f"after_space15 delta   : {tuple_error(after_space15, (AUTOS['2736'], AUTOS['2740'], AUTOS['2744']))}",
            f"final_world raw       : {final_world}",
            f"final_world Autos     : ({AUTOS['2800']}, {AUTOS['2804']}, {AUTOS['2808']})",
            f"final_world delta     : {tuple_error(final_world, (AUTOS['2800'], AUTOS['2804'], AUTOS['2808']))}",
            "",
            "Raw space15 vs Autos",
            "--------------------",
        ]
    )
    for key in ("183", "184", "185", "187", "188", "189", "191", "192", "193", "195", "196", "197"):
        report_lines.append(
            f"%{key}: raw {raw_space15[key]: .9f} | Autos {AUTOS[key]: .9f} | delta {raw_space15[key] - AUTOS[key]: .9f}"
        )
    report_lines.extend(["", "Raw cb14 vs Autos", "-----------------"])
    for key in ("2782", "2783", "2784", "2786", "2787", "2788", "2790", "2791", "2792", "2794", "2795", "2796"):
        report_lines.append(
            f"%{key}: raw {raw_cb14[key]: .9f} | Autos {AUTOS[key]: .9f} | delta {raw_cb14[key] - AUTOS[key]: .9f}"
        )
    report_lines.extend(
        [
            "",
            "Interpretation",
            "--------------",
            "- The late matrix stage should land essentially on the Autos sample if the 2070 path is correct.",
            "- Any remaining visible miss after that isolates the downstream constant stages.",
            "- If the largest deltas are already present in raw space15/cb14 constants, the blocker is state provenance,",
            "  not another hidden per-vertex branch.",
        ]
    )

    OUT_REPORT.write_text("\n".join(report_lines) + "\n", encoding="utf-8")
    OUT_MANIFEST.write_text(
        json.dumps(
            {
                "sample": SAMPLE,
                "draw_record": draw_record,
                "local_pos": [float(v) for v in local_pos],
                "late_pos": [float(v) for v in late_pos],
                "after_space15": [float(v) for v in after_space15],
                "final_world": [float(v) for v in final_world],
                "raw_space15": raw_space15,
                "raw_cb14": raw_cb14,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    print(f"wrote {OUT_REPORT}")
    print(f"wrote {OUT_MANIFEST}")


if __name__ == "__main__":
    main()
