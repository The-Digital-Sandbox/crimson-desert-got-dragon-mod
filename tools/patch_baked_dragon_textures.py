#!/usr/bin/env python3
"""Convert baked dragon PNGs to DDS and patch them into archive 0009.

This is the first-pass texture swap only:
- baseColor + normal for body/back/leg/wing/head
- keeps the original CD spec/mask/height/detail layers
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "output"
CONVERTED = ROOT / "converted" / "baked"
BACKUP = ROOT / "backup" / "baked_textures"
GAME_DIR = Path(r"C:\Program Files (x86)\Steam\steamapps\common\Crimson Desert")
PAZ_DIR = GAME_DIR / "0009"
PAMT_PATH = PAZ_DIR / "0.pamt"

# Make unpacker importable before importing dragon_reskin helpers.
UNPACKER_DIR = ROOT.parent / "cd-unpacker" / "python"
sys.path.insert(0, str(UNPACKER_DIR))

from paz_parse import parse_pamt  # type: ignore  # noqa: E402
from dragon_reskin import (  # type: ignore  # noqa: E402
    CD_DRAGON_TEXTURES,
    TEXCONV,
    backup_texture,
    convert_texture,
    patch_texture,
    verify_dds,
)


TARGET_TEXTURES = [
    "cd_m0004_00_dragon_body_0001.dds",
    "cd_m0004_00_dragon_body_0001_n.dds",
    "cd_m0004_00_dragon_back_0001.dds",
    "cd_m0004_00_dragon_back_0001_n.dds",
    "cd_m0004_00_dragon_leg_0001.dds",
    "cd_m0004_00_dragon_leg_0001_n.dds",
    "cd_m0004_00_dragon_wing_0001.dds",
    "cd_m0004_00_dragon_wing_0001_n.dds",
    "cd_m0004_00_dragon_head_0001.dds",
    "cd_m0004_00_dragon_head_0001_n.dds",
]


def source_png_for(dds_name: str) -> Path:
    return OUTPUT / dds_name.replace(".dds", ".png")


def ensure_prereqs() -> None:
    if not Path(TEXCONV).exists() and os.path.basename(TEXCONV).lower() != "texconv":
        raise SystemExit(f"texconv.exe not found: {TEXCONV}")
    missing = [str(source_png_for(name)) for name in TARGET_TEXTURES if not source_png_for(name).exists()]
    if missing:
        raise SystemExit("Missing baked PNGs:\n" + "\n".join(missing))


def convert_all() -> list[Path]:
    CONVERTED.mkdir(parents=True, exist_ok=True)
    converted_paths: list[Path] = []
    for dds_name in TARGET_TEXTURES:
        source = source_png_for(dds_name)
        output = CONVERTED / dds_name
        tex_type, resolution, dds_format, mip_count = CD_DRAGON_TEXTURES[dds_name]
        print(f"CONVERT {source.name} -> {dds_name} ({dds_format} {resolution}px mips={mip_count})")
        ok = convert_texture(source, output, dds_format, resolution, mip_count)
        if not ok:
            raise SystemExit(f"Conversion failed for {source}")
        verified, msg = verify_dds(output, dds_format, resolution, mip_count)
        if not verified:
            raise SystemExit(f"Verification failed for {output.name}: {msg}")
        print(f"  OK {output}")
        converted_paths.append(output)
    return converted_paths


def patch_all(converted_paths: list[Path], no_backup: bool = False) -> None:
    if not PAMT_PATH.exists():
        raise SystemExit(f"Missing PAMT: {PAMT_PATH}")

    entries = parse_pamt(str(PAMT_PATH), paz_dir=str(PAZ_DIR))
    dragon_entries = {
        os.path.basename(e.path): e
        for e in entries
        if "cd_m0004_00_dragon_" in e.path and e.path.endswith(".dds")
    }

    BACKUP.mkdir(parents=True, exist_ok=True)

    for converted in converted_paths:
        entry = dragon_entries.get(converted.name)
        if entry is None:
            raise SystemExit(f"Archive entry not found for {converted.name}")
        print(f"PATCH {converted.name} -> paz:{entry.paz_index} off=0x{entry.offset:08X}")
        if not no_backup:
            backup_texture(entry, BACKUP)
        patch_texture(entry, converted)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--convert-only", action="store_true")
    parser.add_argument("--patch-only", action="store_true")
    parser.add_argument("--no-backup", action="store_true")
    args = parser.parse_args()

    ensure_prereqs()

    if args.patch_only:
        converted_paths = [CONVERTED / name for name in TARGET_TEXTURES]
        missing_dds = [str(p) for p in converted_paths if not p.exists()]
        if missing_dds:
            raise SystemExit("Missing converted DDS files:\n" + "\n".join(missing_dds))
    else:
        converted_paths = convert_all()

    if not args.convert_only:
        patch_all(converted_paths, no_backup=args.no_backup)

    print("DONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
