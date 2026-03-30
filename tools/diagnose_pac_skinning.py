#!/usr/bin/env python3
"""Diagnose why direct PAC skinning reconstruction collapses.

This script does not try to reconstruct the final mesh. It answers the
format question first:

1. How long is the explicit PAC master hash palette?
2. Which 8-bit skinning codes are actually used by the vertex buffer?
3. What breaks if those codes are treated as direct global palette indices?

The current CD dragon PAC uses all 256 byte codes in the vertex buffer, but
the explicit hash table near 0x443 only provides a shorter master palette.
That means a second indirection layer still exists.
"""

from __future__ import annotations

import argparse
import json
import struct
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "output"

PAC_PATH = OUTPUT / "dragon.pac"
SKELETON_PATH = OUTPUT / "cd_skeleton.json"

SECTION_OFFSET_OFFSETS = (0x14, 0x1C, 0x24, 0x2C, 0x34)
VERTEX_COUNT = 27376
VERTEX_STRIDE = 40
PAC_MASTER_PALETTE_OFFSET = 0x443

SUBMESH_NAMES = ["Eyeright", "Eyeleft", "Body_02", "back", "Body", "Leg", "Wing", "Head"]
SUBMESH_VERTEX_COUNTS = [225, 225, 2013, 3307, 2736, 4624, 6724, 10258]
UNIQUE_VERTEX_ORDER = [0, 1, 2, 3, 5, 6, 7]


def load_pac() -> tuple[bytes, int]:
    pac = PAC_PATH.read_bytes()
    section_offsets = [struct.unpack_from("<Q", pac, off)[0] for off in SECTION_OFFSET_OFFSETS]
    vertex_start = section_offsets[1] - VERTEX_COUNT * VERTEX_STRIDE
    return pac, vertex_start


def load_skeleton() -> list[dict]:
    return json.loads(SKELETON_PATH.read_text(encoding="utf-8"))


def build_submesh_ranges() -> dict[int, tuple[int, int]]:
    starts: dict[int, int] = {}
    cursor = 0
    for submesh_index in UNIQUE_VERTEX_ORDER:
        starts[submesh_index] = cursor
        cursor += SUBMESH_VERTEX_COUNTS[submesh_index]

    # Body shares the back vertex buffer.
    starts[4] = starts[3]

    return {
        submesh_index: (starts[submesh_index], starts[submesh_index] + SUBMESH_VERTEX_COUNTS[submesh_index])
        for submesh_index in range(len(SUBMESH_NAMES))
    }


def read_master_hash_palette(pac: bytes, skeleton_by_hash: dict[int, dict]) -> list[dict]:
    entries: list[dict] = []
    offset = PAC_MASTER_PALETTE_OFFSET

    while offset + 4 <= len(pac):
        bone_hash = struct.unpack_from("<I", pac, offset)[0]
        bone = skeleton_by_hash.get(bone_hash)
        if bone is None:
            break
        entries.append({"index": len(entries), "offset": offset, "hash": bone_hash, "name": bone["name"]})
        offset += 4

    return entries


def iter_vertex_codes(pac: bytes, vertex_start: int):
    for vertex_index in range(VERTEX_COUNT):
        offset = vertex_start + vertex_index * VERTEX_STRIDE
        x, y, z = struct.unpack_from("<3e", pac, offset)
        codes = list(pac[offset + 12 : offset + 16])
        weights = list(pac[offset + 20 : offset + 24])
        yield {
            "index": vertex_index,
            "offset": offset,
            "position": (float(x), float(y), float(z)),
            "codes": codes,
            "weights": weights,
        }


def collect_code_usage(pac: bytes, vertex_start: int) -> tuple[Counter[int], dict[int, list[dict]]]:
    counts: Counter[int] = Counter()
    examples: dict[int, list[dict]] = defaultdict(list)

    for vertex in iter_vertex_codes(pac, vertex_start):
        for channel, (code, weight) in enumerate(zip(vertex["codes"], vertex["weights"])):
            if weight == 0:
                continue
            counts[code] += 1
            if len(examples[code]) < 6:
                examples[code].append(
                    {
                        "vertex": vertex["index"],
                        "channel": channel,
                        "weight": weight,
                        "position": vertex["position"],
                    }
                )

    return counts, examples


def collect_submesh_code_usage(pac: bytes, vertex_start: int, ranges: dict[int, tuple[int, int]]) -> dict[int, Counter[int]]:
    per_submesh: dict[int, Counter[int]] = {}
    for submesh_index, (start, end) in ranges.items():
        counter: Counter[int] = Counter()
        for vertex_index in range(start, end):
            offset = vertex_start + vertex_index * VERTEX_STRIDE
            codes = pac[offset + 12 : offset + 16]
            weights = pac[offset + 20 : offset + 24]
            for code, weight in zip(codes, weights):
                if weight:
                    counter[code] += 1
        per_submesh[submesh_index] = counter
    return per_submesh


def format_position(position: tuple[float, float, float]) -> str:
    return f"({position[0]:.6f}, {position[1]:.6f}, {position[2]:.6f})"


def main() -> int:
    parser = argparse.ArgumentParser(description="Diagnose the PAC skinning code indirection problem.")
    parser.add_argument(
        "--top",
        type=int,
        default=24,
        help="number of globally most-used codes to list",
    )
    args = parser.parse_args()

    pac, vertex_start = load_pac()
    skeleton = load_skeleton()
    skeleton_by_hash = {bone["hash"]: bone for bone in skeleton}
    master_palette = read_master_hash_palette(pac, skeleton_by_hash)
    ranges = build_submesh_ranges()
    code_usage, examples = collect_code_usage(pac, vertex_start)
    per_submesh = collect_submesh_code_usage(pac, vertex_start, ranges)

    used_codes = sorted(code_usage)
    max_code = max(used_codes)
    unmapped_codes = [code for code in used_codes if code >= len(master_palette)]

    print(f"PAC:            {PAC_PATH}")
    print(f"Skeleton:       {SKELETON_PATH}")
    print(f"Vertex start:   0x{vertex_start:X}")
    print(f"Used codes:     {len(used_codes)} distinct, max={max_code}")
    print(f"Master palette: {len(master_palette)} contiguous hash entries from 0x{PAC_MASTER_PALETTE_OFFSET:X}")
    print(f"Unmapped codes: {len(unmapped_codes)} codes fall outside the explicit master palette")
    print()

    if master_palette:
        print("Master palette tail:")
        for entry in master_palette[-6:]:
            print(f"  code={entry['index']:3d}  hash=0x{entry['hash']:08X}  {entry['name']}")
        print()

    print("Most-used codes:")
    for code, count in code_usage.most_common(args.top):
        if code < len(master_palette):
            label = master_palette[code]["name"]
        else:
            label = "<outside master palette>"
        print(f"  code={code:3d}  bank={code >> 4:2d} slot={code & 0x0F:2d}  uses={count:5d}  direct={label}")
    print()

    print("Direct-mapping contradictions:")
    contradictions = [
        (16, "Eyeright"),
        (32, "Eyeright"),
        (48, "Eyeright"),
        (64, "Eyeright"),
        (224, "Leg"),
        (225, "Wing"),
        (226, "Wing"),
        (240, "Body_02"),
        (248, "Leg"),
        (252, "Wing"),
    ]

    for code, submesh_name in contradictions:
        submesh_index = SUBMESH_NAMES.index(submesh_name)
        submesh_hits = per_submesh[submesh_index][code]
        if submesh_hits == 0:
            continue
        direct = master_palette[code]["name"] if code < len(master_palette) else "<outside master palette>"
        sample = examples[code][0] if examples[code] else None
        if sample is None:
            sample_text = ""
        else:
            sample_text = (
                f"sample v{sample['vertex']} ch{sample['channel']} "
                f"w={sample['weight']} pos={format_position(sample['position'])}"
            )
        print(
            f"  {submesh_name:8s} uses code {code:3d} {submesh_hits:4d} times; "
            f"direct decode would mean {direct}. {sample_text}"
        )
    print()

    if unmapped_codes:
        print("Codes outside the explicit master palette:")
        preview = unmapped_codes[:32]
        print(f"  {preview}")
        if len(unmapped_codes) > len(preview):
            print(f"  ... ({len(unmapped_codes)} total)")
        print()

    print("Per-submesh high-code usage (>= 224):")
    for submesh_index, submesh_name in enumerate(SUBMESH_NAMES):
        high_codes = [code for code in sorted(per_submesh[submesh_index]) if code >= 224]
        if high_codes:
            print(f"  {submesh_name:8s} {high_codes}")
    print()

    print("Conclusion:")
    print("  The 8-bit PAC skinning code is not a direct global bone index.")
    print("  A second indirection layer still maps code -> actual bone/palette entry.")
    print("  Exporting raw positions or applying skeleton matrices with direct code lookup will collapse/explode the mesh.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
