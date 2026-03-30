#!/usr/bin/env python3
"""Probe a PAC vertex against the current dragon skeleton data.

This script is meant to answer one question cleanly:

Which transform interpretation is self-consistent with the current files?

Important limitation:
  This probe still tests direct code -> skeleton mappings. The current PAC
  appears to use an additional indirection layer, so these formulas are useful
  for falsifying wrong assumptions, not for proving the final bind decode.

It reads:
  - output/dragon.pac
  - output/dragon_pamt_unpacked.bin
  - output/cd_skeleton.json

And reports, for a chosen vertex:
  - raw position
  - bytes 12:16 / 20:24 / 16:20 / 24:28
  - PAMT bone names for each channel
  - mapped skeleton bone names
  - candidate transform results

It can also summarize those same formulas across the whole mesh.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import struct
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "output"

PAC_PATH = OUTPUT / "dragon.pac"
PAMT_PATH = OUTPUT / "dragon_pamt_unpacked.bin"
SKELETON_PATH = OUTPUT / "cd_skeleton.json"

SECTION_OFFSET_OFFSETS = (0x14, 0x1C, 0x24, 0x2C, 0x34)
VERTEX_COUNT = 27376
VERTEX_STRIDE = 40


def load_pac() -> tuple[bytes, int]:
    pac = PAC_PATH.read_bytes()
    section_offsets = [struct.unpack_from("<Q", pac, off)[0] for off in SECTION_OFFSET_OFFSETS]
    vertex_start = section_offsets[1] - VERTEX_COUNT * VERTEX_STRIDE
    return pac, vertex_start


def load_skeleton() -> list[dict]:
    with SKELETON_PATH.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def parse_pamt_bones() -> list[dict]:
    data = PAMT_PATH.read_bytes()
    bones = []
    pos = 0x16

    while pos + 7 <= len(data):
        name_len = data[pos]
        if name_len == 0 or name_len > 80 or pos + 1 + name_len + 6 > len(data):
            break

        name_bytes = data[pos + 1 : pos + 1 + name_len]
        if any(b < 32 or b > 126 for b in name_bytes):
            break

        name = name_bytes.decode("ascii")
        parent = struct.unpack_from("<H", data, pos + 1 + name_len)[0]
        bone_hash = struct.unpack_from("<I", data, pos + 1 + name_len + 2)[0]
        bones.append(
            {
                "index": len(bones),
                "name": name,
                "parent": parent,
                "hash": bone_hash,
            }
        )
        pos += 1 + name_len + 6

    return bones


def build_pamt_to_skeleton_map(pamt_bones: list[dict], skeleton: list[dict]) -> dict[int, dict]:
    skeleton_by_name = {bone["name"]: bone for bone in skeleton}
    mapping: dict[int, dict] = {}

    for pamt_bone in pamt_bones[:256]:
        current = pamt_bone["index"]
        hop_count = 0

        while current < len(pamt_bones):
            current_name = pamt_bones[current]["name"]
            skeleton_bone = skeleton_by_name.get(current_name)
            if skeleton_bone is not None:
                mapping[pamt_bone["index"]] = {
                    "skeleton_bone": skeleton_bone,
                    "matched_name": current_name,
                    "hop_count": hop_count,
                }
                break

            parent = pamt_bones[current]["parent"]
            if parent == current or parent >= len(pamt_bones):
                break

            current = parent
            hop_count += 1

    return mapping


def row_mul_vec_mat(vec: np.ndarray, mat: np.ndarray) -> np.ndarray:
    return vec @ mat


def max_abs_delta(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.max(np.abs(a[:3] - b[:3])))


def decode_vertex(pac: bytes, vertex_start: int, vertex_index: int) -> dict:
    if not 0 <= vertex_index < VERTEX_COUNT:
        raise IndexError(f"vertex {vertex_index} is out of range 0..{VERTEX_COUNT - 1}")

    off = vertex_start + vertex_index * VERTEX_STRIDE
    x, y, z = struct.unpack_from("<3e", pac, off)
    bone_indices = list(pac[off + 12 : off + 16])
    bone_weights = list(pac[off + 20 : off + 24])

    return {
        "index": vertex_index,
        "offset": off,
        "position": np.array([float(x), float(y), float(z), 1.0], dtype=np.float64),
        "bone_indices": bone_indices,
        "bone_weights_raw": bone_weights,
        "weight_sum": sum(bone_weights),
        "extra0": bytes(pac[off + 16 : off + 20]),
        "extra1": bytes(pac[off + 24 : off + 28]),
    }


def normalize_weights(raw_weights: list[int]) -> tuple[list[float], list[float]]:
    by_255 = [weight / 255.0 for weight in raw_weights]
    total = sum(raw_weights)
    by_sum = [weight / total for weight in raw_weights] if total else [0.0, 0.0, 0.0, 0.0]
    return by_255, by_sum


def probe_vertex(
    vertex: dict,
    pamt_bones: list[dict],
    pamt_to_skeleton: dict[int, dict],
) -> dict[str, np.ndarray]:
    pos = vertex["position"]
    bone_indices = vertex["bone_indices"]
    raw_weights = vertex["bone_weights_raw"]
    weights_255, weights_sum = normalize_weights(raw_weights)

    primary = bone_indices[0]
    primary_map = pamt_to_skeleton.get(primary)

    out: dict[str, np.ndarray] = {
        "raw": pos.copy(),
        "primary_world": pos.copy(),
        "weighted_world_255": np.zeros(4, dtype=np.float64),
        "weighted_world_sum": np.zeros(4, dtype=np.float64),
        "weighted_bind_pair_255": np.zeros(4, dtype=np.float64),
        "weighted_bind_pair_sum": np.zeros(4, dtype=np.float64),
    }

    if primary_map is not None:
        primary_world = np.array(primary_map["skeleton_bone"]["world_matrix"], dtype=np.float64)
        out["primary_world"] = row_mul_vec_mat(pos, primary_world)

    for bone_index, raw_weight, weight_255, weight_sum in zip(
        bone_indices,
        raw_weights,
        weights_255,
        weights_sum,
    ):
        if raw_weight == 0:
            continue

        mapping = pamt_to_skeleton.get(bone_index)
        if mapping is None:
            continue

        skeleton_bone = mapping["skeleton_bone"]
        world = np.array(skeleton_bone["world_matrix"], dtype=np.float64)
        inv_world = np.array(skeleton_bone["inv_world_matrix"], dtype=np.float64)

        out["weighted_world_255"] += weight_255 * row_mul_vec_mat(pos, world)
        out["weighted_world_sum"] += weight_sum * row_mul_vec_mat(pos, world)
        out["weighted_bind_pair_255"] += weight_255 * row_mul_vec_mat(row_mul_vec_mat(pos, world), inv_world)
        out["weighted_bind_pair_sum"] += weight_sum * row_mul_vec_mat(row_mul_vec_mat(pos, world), inv_world)

    return out


def summarize_mesh(
    pac: bytes,
    vertex_start: int,
    pamt_bones: list[dict],
    pamt_to_skeleton: dict[int, dict],
) -> dict[str, dict[str, float]]:
    error_buckets = {
        "primary_world_vs_raw": [],
        "weighted_world_255_vs_raw": [],
        "weighted_world_sum_vs_raw": [],
        "weighted_bind_pair_255_vs_raw": [],
        "weighted_bind_pair_sum_vs_raw": [],
    }

    for vertex_index in range(VERTEX_COUNT):
        vertex = decode_vertex(pac, vertex_start, vertex_index)
        results = probe_vertex(vertex, pamt_bones, pamt_to_skeleton)
        raw = results["raw"]

        error_buckets["primary_world_vs_raw"].append(max_abs_delta(results["primary_world"], raw))
        error_buckets["weighted_world_255_vs_raw"].append(max_abs_delta(results["weighted_world_255"], raw))
        error_buckets["weighted_world_sum_vs_raw"].append(max_abs_delta(results["weighted_world_sum"], raw))
        error_buckets["weighted_bind_pair_255_vs_raw"].append(max_abs_delta(results["weighted_bind_pair_255"], raw))
        error_buckets["weighted_bind_pair_sum_vs_raw"].append(max_abs_delta(results["weighted_bind_pair_sum"], raw))

    summary = {}
    for label, errors in error_buckets.items():
        ordered = sorted(errors)
        summary[label] = {
            "median": statistics.median(ordered),
            "q90": ordered[int(len(ordered) * 0.90)],
            "q99": ordered[int(len(ordered) * 0.99)],
            "max": ordered[-1],
        }
    return summary


def format_vec3(vec: np.ndarray) -> str:
    return f"({vec[0]: .9f}, {vec[1]: .9f}, {vec[2]: .9f})"


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe a dragon PAC vertex against the current bind data.")
    parser.add_argument("vertex", type=int, nargs="?", default=153, help="vertex index to inspect")
    parser.add_argument(
        "--summary",
        action="store_true",
        help="compute whole-mesh error stats for the candidate formulas",
    )
    args = parser.parse_args()

    pac, vertex_start = load_pac()
    skeleton = load_skeleton()
    pamt_bones = parse_pamt_bones()
    pamt_to_skeleton = build_pamt_to_skeleton_map(pamt_bones, skeleton)
    vertex = decode_vertex(pac, vertex_start, args.vertex)
    results = probe_vertex(vertex, pamt_bones, pamt_to_skeleton)

    weights_255, weights_sum = normalize_weights(vertex["bone_weights_raw"])

    print(f"PAC:       {PAC_PATH}")
    print(f"PAMT:      {PAMT_PATH}")
    print(f"Skeleton:  {SKELETON_PATH}")
    print(f"Vertex:    {vertex['index']} @ 0x{vertex['offset']:X}")
    print(f"Position:  {format_vec3(vertex['position'])}")
    print(f"Bone idx:  {vertex['bone_indices']}")
    print(f"Bone raw:  {vertex['bone_weights_raw']}  sum={vertex['weight_sum']}")
    print(f"Weight/255:{[round(value, 6) for value in weights_255]}")
    print(f"Weight/sum:{[round(value, 6) for value in weights_sum]}")
    print(f"Extra0:    {vertex['extra0'].hex(' ')}")
    print(f"Extra1:    {vertex['extra1'].hex(' ')}")
    print()

    for channel, (bone_index, raw_weight, weight_sum) in enumerate(
        zip(vertex["bone_indices"], vertex["bone_weights_raw"], weights_sum)
    ):
        pamt_name = pamt_bones[bone_index]["name"] if bone_index < len(pamt_bones) else "<out of range>"
        mapping = pamt_to_skeleton.get(bone_index)
        if mapping is None:
            mapped_name = "<unmapped>"
            hop_count = "-"
        else:
            mapped_name = mapping["skeleton_bone"]["name"]
            hop_count = mapping["hop_count"]

        print(
            f"ch{channel}: idx={bone_index:3d}  raw_w={raw_weight:3d}  "
            f"norm_w={weight_sum:.6f}  pamt={pamt_name}  mapped={mapped_name}  hops={hop_count}"
        )

    print()
    for label in (
        "raw",
        "primary_world",
        "weighted_world_255",
        "weighted_world_sum",
        "weighted_bind_pair_255",
        "weighted_bind_pair_sum",
    ):
        delta = max_abs_delta(results[label], results["raw"])
        print(f"{label:24s} {format_vec3(results[label])}  delta_vs_raw={delta:.9f}")

    if args.summary:
        print()
        print("Whole-mesh error summary vs raw position:")
        summary = summarize_mesh(pac, vertex_start, pamt_bones, pamt_to_skeleton)
        for label, stats in summary.items():
            print(
                f"{label:28s} "
                f"median={stats['median']:.9f}  "
                f"q90={stats['q90']:.9f}  "
                f"q99={stats['q99']:.9f}  "
                f"max={stats['max']:.9f}"
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
