#!/usr/bin/env python3
"""Export a bake-ready OBJ from segmented world targets with CD UVs.

The segmented reverse outputs have the right approximate Drogon-like geometry,
but they do not carry UVs. The PAC decode carries the UVs, but not a visually
useful surface in Blender. This script combines the segmented world positions
with the original CD UVs and triangle lists into a bake-friendly OBJ.
"""

from __future__ import annotations

import json
from pathlib import Path

import pac_codec


ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "output"
PAC_PATH = OUTPUT / "dragon_drogon_segmented.pac"
MANIFEST_PATH = OUTPUT / "reverse_drogon_runtime_targets_segmented" / "manifest.json"
OUT_OBJ = OUTPUT / "dragon_drogon_segmented_bake.obj"
OUT_REPORT = OUTPUT / "dragon_drogon_segmented_bake_report.txt"

BAKE_SUBMESHES = ["Body_02", "back", "Body", "Leg", "Wing", "Head"]


def read_obj_vertices(path: Path) -> list[tuple[float, float, float]]:
    vertices: list[tuple[float, float, float]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("v "):
            continue
        _tag, xs, ys, zs = line.split(maxsplit=3)
        vertices.append((float(xs), float(ys), float(zs)))
    return vertices


def main() -> None:
    pac = PAC_PATH.read_bytes()
    decoded = pac_codec.decode_all_submeshes(pac)
    indices = pac_codec.read_indices(pac)
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

    world_obj_by_name = {
        item["name"]: ROOT / item["output_world_obj"]
        for item in manifest["submeshes"]
    }

    missing = [name for name in BAKE_SUBMESHES if name not in world_obj_by_name]
    if missing:
        raise ValueError(f"missing segmented world objs for: {missing}")

    lines: list[str] = [
        "# Drogon segmented bake target",
        "# Geometry: segmented reverse world target",
        "# UVs: original CD dragon UVs preserved",
        "",
    ]
    report_lines: list[str] = [
        "Segmented Bake OBJ",
        "==================",
        "",
        f"input_pac     : {PAC_PATH}",
        f"manifest      : {MANIFEST_PATH}",
        f"output_obj    : {OUT_OBJ}",
        "",
        "Included submeshes",
        "------------------",
    ]

    vertex_base = 1
    uv_base = 1

    for name in BAKE_SUBMESHES:
        world_vertices = read_obj_vertices(world_obj_by_name[name])
        sm = decoded[name]
        sm_indices = indices[name]
        uv_vertices = [vertex.uv0 for vertex in sm["verts"]]

        if len(world_vertices) != len(uv_vertices):
            raise ValueError(
                f"{name}: world vertex count {len(world_vertices)} does not match UV vertex count {len(uv_vertices)}"
            )

        lines.append(f"o {name}")
        for x, y, z in world_vertices:
            lines.append(f"v {x:.9f} {y:.9f} {z:.9f}")
        for u, v in uv_vertices:
            lines.append(f"vt {u:.9f} {1.0 - v:.9f}")
        for tri in range(0, len(sm_indices), 3):
            i0 = sm_indices[tri + 0]
            i1 = sm_indices[tri + 1]
            i2 = sm_indices[tri + 2]
            lines.append(
                "f "
                f"{vertex_base + i0}/{uv_base + i0} "
                f"{vertex_base + i1}/{uv_base + i1} "
                f"{vertex_base + i2}/{uv_base + i2}"
            )
        lines.append("")

        report_lines.extend(
            [
                f"{name}",
                f"  vertices : {len(world_vertices)}",
                f"  triangles: {len(sm_indices) // 3}",
            ]
        )

        vertex_base += len(world_vertices)
        uv_base += len(uv_vertices)

    OUT_OBJ.write_text("\n".join(lines) + "\n", encoding="utf-8")
    OUT_REPORT.write_text("\n".join(report_lines) + "\n", encoding="utf-8")
    print(f"wrote {OUT_OBJ}")
    print(f"wrote {OUT_REPORT}")


if __name__ == "__main__":
    main()
