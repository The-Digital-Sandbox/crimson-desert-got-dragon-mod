#!/usr/bin/env python3
"""Summarize the dragon texture/material slots from the PAC XML manifest."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections import OrderedDict
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
XML_PATH = ROOT / "dragon-extract" / "character" / "cd_m0004_00_dragon_00_0001.pac.xml"
OUT_PATH = ROOT / "output" / "dragon_texture_slots.txt"


PRIORITY_PARAMS = [
    "_baseColorTexture",
    "_normalTexture",
    "_materialTexture",
    "_heightTexture",
    "_maskTexture",
]


def collect_wrappers(root: ET.Element) -> OrderedDict[str, dict]:
    by_submesh: OrderedDict[str, dict] = OrderedDict()
    for wrapper in root.iter("SkinnedMeshMaterialWrapper"):
        submesh_name = wrapper.attrib.get("_subMeshName", "").strip()
        if not submesh_name:
            continue

        material = wrapper.find("./Material")
        material_name = material.attrib.get("_materialName", "") if material is not None else ""
        params: OrderedDict[str, str] = OrderedDict()

        for param in wrapper.iter():
            param_name = param.attrib.get("_name")
            if not param_name:
                continue
            tex_ref = param.find("./ResourceReferencePath_ITexture")
            if tex_ref is None:
                continue
            tex_path = tex_ref.attrib.get("_path", "").strip()
            if not tex_path:
                continue
            params[param_name] = tex_path

        entry = by_submesh.setdefault(
            submesh_name,
            {
                "material_name": material_name,
                "variants": 0,
                "params": OrderedDict(),
            },
        )
        entry["variants"] += 1
        if not entry["material_name"]:
            entry["material_name"] = material_name
        for key, value in params.items():
            entry["params"].setdefault(key, value)

    return by_submesh


def main() -> None:
    xml_text = XML_PATH.read_text(encoding="utf-8")
    root = ET.fromstring(f"<Root>\n{xml_text}\n</Root>")
    wrappers = collect_wrappers(root)

    all_unique = OrderedDict()
    for entry in wrappers.values():
        for tex_path in entry["params"].values():
            all_unique.setdefault(tex_path, None)

    lines: list[str] = []
    lines.extend(
        [
            "Crimson Desert Dragon Texture Slots",
            "===================================",
            "",
            f"source xml : {XML_PATH}",
            f"submeshes   : {len(wrappers)}",
            f"unique dds  : {len(all_unique)}",
            "",
            "Fastest safe texture swap path",
            "------------------------------",
            "- Keep the working PAC geometry and current CD UV layout.",
            "- Bake Drogon color/normal into the existing CD UVs.",
            "- Replace only `_baseColorTexture` and `_normalTexture` first.",
            "- Keep `_materialTexture`, `_heightTexture`, `_maskTexture`, and detail layers",
            "  as the original CD files until the render is stable.",
            "",
            "Per-submesh Slots",
            "-----------------",
        ]
    )

    for submesh_name, entry in wrappers.items():
        lines.append(submesh_name)
        lines.append(f"  material : {entry['material_name']}")
        lines.append(f"  variants : {entry['variants']}")
        for key in PRIORITY_PARAMS:
            if key in entry["params"]:
                lines.append(f"  {key:20s} {entry['params'][key]}")
        detail_keys = [key for key in entry["params"] if key not in PRIORITY_PARAMS]
        if detail_keys:
            lines.append("  detail/extra:")
            for key in detail_keys:
                lines.append(f"    {key:18s} {entry['params'][key]}")
        lines.append("")

    lines.extend(
        [
            "Files To Replace First",
            "----------------------",
        ]
    )

    first_pass = OrderedDict()
    for entry in wrappers.values():
        for key in ("_baseColorTexture", "_normalTexture"):
            tex_path = entry["params"].get(key)
            if tex_path:
                first_pass[tex_path] = None

    for tex_path in first_pass:
        lines.append(f"- {tex_path}")

    lines.extend(
        [
            "",
            "Files To Keep CD For First Pass",
            "-------------------------------",
        ]
    )

    keep_cd = OrderedDict()
    for entry in wrappers.values():
        for key in ("_materialTexture", "_heightTexture", "_maskTexture"):
            tex_path = entry["params"].get(key)
            if tex_path:
                keep_cd[tex_path] = None
    for tex_path in keep_cd:
        lines.append(f"- {tex_path}")

    lines.extend(
        [
            "",
            "Shared Detail Layers",
            "--------------------",
            "- These are referenced by multiple body regions. Leave them alone at first.",
        ]
    )
    detail_paths = OrderedDict()
    for entry in wrappers.values():
        for key, value in entry["params"].items():
            if key.startswith("_detail"):
                detail_paths[value] = None
    for tex_path in detail_paths:
        lines.append(f"- {tex_path}")

    OUT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {OUT_PATH}")


if __name__ == "__main__":
    main()
