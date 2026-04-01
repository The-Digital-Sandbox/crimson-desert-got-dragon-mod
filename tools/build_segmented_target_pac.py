#!/usr/bin/env python3
"""Build a topology-preserving PAC from segmented runtime-local targets.

This uses the reverse-generated runtime-local targets as the new per-vertex
positions, while preserving the original dragon PAC's topology, indices,
weights, UVs, normals, and all non-position fields.
"""

from __future__ import annotations

import json
import struct
from dataclasses import dataclass
from pathlib import Path

import pac_codec
from pac_patcher import find_bbox_offsets


ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "output"
PAC_INPUT = OUTPUT / "dragon.pac"
SEGMENTED_MANIFEST = OUTPUT / "reverse_drogon_runtime_targets_segmented" / "manifest.json"
OUT_PAC = OUTPUT / "dragon_drogon_segmented.pac"
OUT_REPORT = OUTPUT / "dragon_drogon_segmented_report.txt"


@dataclass(frozen=True)
class SubmeshTarget:
    name: str
    count: int
    local_obj: Path


def read_obj_vertices(path: Path) -> list[tuple[float, float, float]]:
    vertices: list[tuple[float, float, float]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("v "):
            continue
        _tag, xs, ys, zs = line.split(maxsplit=3)
        vertices.append((float(xs), float(ys), float(zs)))
    return vertices


def load_targets() -> list[SubmeshTarget]:
    manifest = json.loads(SEGMENTED_MANIFEST.read_text(encoding="utf-8"))
    submeshes = []
    for item in manifest["submeshes"]:
        submeshes.append(
            SubmeshTarget(
                name=item["name"],
                count=item["vertex_count"],
                local_obj=ROOT / item["output_local_obj"],
            )
        )
    return submeshes


def main() -> None:
    pac = bytearray(PAC_INPUT.read_bytes())
    pac_size = len(pac)
    bboxes = pac_codec.parse_submesh_descriptors(bytes(pac))
    bbox_offsets = find_bbox_offsets(bytes(pac))
    targets = {item.name: item for item in load_targets()}

    report_lines = [
        "Segmented runtime-local PAC build",
        "================================",
        "",
        f"input_pac   : {PAC_INPUT}",
        f"manifest    : {SEGMENTED_MANIFEST}",
        f"output_pac  : {OUT_PAC}",
        "",
        "Per-submesh",
        "-----------",
    ]

    base_vertex = 0
    for submesh_index, submesh_name in enumerate(pac_codec.SUBMESH_NAMES):
        submesh_count = pac_codec.SUBMESH_VERTEX_COUNTS[submesh_index]
        target = targets.get(submesh_name)
        if target is None:
            report_lines.extend(
                [
                    f"{submesh_name}",
                    f"  verts      : {submesh_count}",
                    "  action     : preserved original eye/aux geometry",
                ]
            )
            base_vertex += submesh_count
            continue

        points = read_obj_vertices(target.local_obj)
        if len(points) != target.count:
            raise ValueError(f"{target.name}: expected {target.count} verts, got {len(points)} from {target.local_obj}")

        old_bbox = bboxes[submesh_index]
        bbox_off = bbox_offsets[submesh_index]

        xs = [point[0] for point in points]
        ys = [point[1] for point in points]
        zs = [point[2] for point in points]

        pad = 0.001
        new_min = (min(xs) - pad, min(ys) - pad, min(zs) - pad)
        new_max = (max(xs) + pad, max(ys) + pad, max(zs) + pad)
        new_dim = (
            max(1e-6, new_max[0] - new_min[0]),
            max(1e-6, new_max[1] - new_min[1]),
            max(1e-6, new_max[2] - new_min[2]),
        )
        new_bbox = pac_codec.SubmeshBbox(
            name=target.name,
            min_xyz=new_min,
            dim_xyz=new_dim,
            lod_near=old_bbox.lod_near,
            lod_far=old_bbox.lod_far,
        )

        struct.pack_into("<2f", pac, bbox_off, old_bbox.lod_near, old_bbox.lod_far)
        struct.pack_into("<3f", pac, bbox_off + 8, *new_min)
        struct.pack_into("<3f", pac, bbox_off + 20, *new_dim)

        for local_index, pos in enumerate(points):
            vertex_index = base_vertex + local_index
            off = pac_codec.VB_START + vertex_index * pac_codec.STRIDE
            qx, qy, qz = pac_codec.quantize_pos(pos[0], pos[1], pos[2], new_bbox)
            struct.pack_into("<3H", pac, off, qx, qy, qz)

        report_lines.extend(
            [
                f"{target.name}",
                f"  verts      : {target.count}",
                f"  old_min    : ({old_bbox.min_xyz[0]:.6f}, {old_bbox.min_xyz[1]:.6f}, {old_bbox.min_xyz[2]:.6f})",
                f"  old_dim    : ({old_bbox.dim_xyz[0]:.6f}, {old_bbox.dim_xyz[1]:.6f}, {old_bbox.dim_xyz[2]:.6f})",
                f"  new_min    : ({new_min[0]:.6f}, {new_min[1]:.6f}, {new_min[2]:.6f})",
                f"  new_dim    : ({new_dim[0]:.6f}, {new_dim[1]:.6f}, {new_dim[2]:.6f})",
            ]
        )

        base_vertex += submesh_count

    if len(pac) != pac_size:
        raise ValueError("PAC size changed unexpectedly")

    OUT_PAC.write_bytes(pac)
    report_lines.extend(
        [
            "",
            "Output",
            "------",
            f"size       : {len(pac):,}",
            f"size_match : {'yes' if len(pac) == pac_size else 'no'}",
        ]
    )
    OUT_REPORT.write_text("\n".join(report_lines) + "\n", encoding="utf-8")

    print(f"wrote {OUT_PAC}")
    print(f"wrote {OUT_REPORT}")


if __name__ == "__main__":
    main()
