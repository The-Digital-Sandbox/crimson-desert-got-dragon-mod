#!/usr/bin/env python3
"""
Verify the DXIL-derived vertex layout against the original CD dragon PAC.

Reads the original dragon.pac using the NEW layout interpretation (from shader
disassembly) and checks whether the decoded bone indices resolve to plausible
skeleton bones for each submesh.

This is a READ-ONLY diagnostic — no files are modified.

Layout (from DXIL analysis):
  Bytes  0-7:  position (3×u16) + W (u16)
  Bytes  8-11: 2 × half-float (tangent/UV data)
  Bytes 12-13: half-float bone index 0
  Bytes 14-15: half-float bone index 1
  Bytes 16-19: R10G10B10A2 normal + tangent sign
  Bytes 20-23: 3 × 10-bit bone indices (idx2, idx3, idx4)
  Bytes 24-27: 3 × 10-bit bone indices (idx5, idx6, idx7)
  Bytes 28-31: 4 × u8 bone weights (channels 0-3)
  Bytes 32-35: 4 × u8 bone weights (channels 4-7)
  Bytes 36-39: UV + packed flags
"""
import struct
import json
import numpy as np
from pathlib import Path
from collections import Counter, defaultdict

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "output"
PAC_PATH = OUTPUT / "dragon.pac"
SKELETON_PATH = OUTPUT / "cd_skeleton.json"

VB_START = 0x7BFA
STRIDE = 40
TOTAL_VERTS = 27376

SUBMESH_NAMES = ["Eyeright", "Eyeleft", "Body_02", "back", "Body", "Leg", "Wing", "Head"]
SUBMESH_VERTEX_COUNTS = [225, 225, 2013, 3307, 2736, 4624, 6724, 10258]

SUBMESH_BASES = []
_base = 0
for vc in SUBMESH_VERTEX_COUNTS:
    SUBMESH_BASES.append(_base)
    _base += vc

# Half-float conversion
def half_to_float(h):
    """Convert uint16 half-float to Python float."""
    buf = struct.pack('<H', h)
    return struct.unpack('<e', buf)[0]


def read_bone_palette(pac):
    """Read the bone hash palette starting at 0x443."""
    offset = 0x443
    hashes = []
    skeleton = json.loads(SKELETON_PATH.read_text(encoding='utf-8'))
    valid_hashes = {b['hash'] for b in skeleton}

    while offset + 4 <= len(pac):
        h = struct.unpack_from('<I', pac, offset)[0]
        if h not in valid_hashes:
            break
        hashes.append(h)
        offset += 4

    return hashes


def decode_vertex_new_layout(pac, vertex_index):
    """Decode a single vertex using the DXIL-derived layout."""
    off = VB_START + vertex_index * STRIDE

    # Bytes 0-7: position + W
    pos_x, pos_y, pos_z, w = struct.unpack_from('<4H', pac, off)

    # Bytes 8-15: 4 half-floats
    h0_raw, h1_raw, h2_raw, h3_raw = struct.unpack_from('<4H', pac, off + 8)
    half0 = half_to_float(h0_raw)
    half1 = half_to_float(h1_raw)
    bone_idx_half0 = half_to_float(h2_raw)  # bone index 0 as float
    bone_idx_half1 = half_to_float(h3_raw)  # bone index 1 as float

    # Bytes 16-19: R10G10B10A2
    packed_normal = struct.unpack_from('<I', pac, off + 16)[0]

    # Bytes 20-23: 3 × 10-bit bone indices
    packed_bi_a = struct.unpack_from('<I', pac, off + 20)[0]
    bi2 = packed_bi_a & 0x3FF
    bi3 = (packed_bi_a >> 10) & 0x3FF
    bi4 = (packed_bi_a >> 20) & 0x3FF

    # Bytes 24-27: 3 × 10-bit bone indices
    packed_bi_b = struct.unpack_from('<I', pac, off + 24)[0]
    bi5 = packed_bi_b & 0x3FF
    bi6 = (packed_bi_b >> 10) & 0x3FF
    bi7 = (packed_bi_b >> 20) & 0x3FF

    # Bytes 28-35: 8 × u8 bone weights
    weights = struct.unpack_from('8B', pac, off + 28)

    # Bytes 36-39: UV + flags
    uv_flags = struct.unpack_from('<I', pac, off + 36)[0]

    # Convert half-float bone indices to int (shader does +0.5 then fptoui)
    bi0 = int(round(bone_idx_half0)) if not (np.isnan(bone_idx_half0) or np.isinf(bone_idx_half0)) else 0
    bi1 = int(round(bone_idx_half1)) if not (np.isnan(bone_idx_half1) or np.isinf(bone_idx_half1)) else 0

    return {
        'pos': (pos_x, pos_y, pos_z),
        'w': w,
        'half0': half0, 'half1': half1,
        'half0_raw': h0_raw, 'half1_raw': h1_raw,
        'half2_raw': h2_raw, 'half3_raw': h3_raw,
        'bone_indices': [bi0, bi1, bi2, bi3, bi4, bi5, bi6, bi7],
        'bone_indices_raw': [bi0, bi1, bi2, bi3, bi4, bi5, bi6, bi7],
        'packed_bi_a': packed_bi_a,
        'packed_bi_b': packed_bi_b,
        'weights': list(weights),
        'packed_normal': packed_normal,
        'uv_flags': uv_flags,
    }


def decode_vertex_old_layout(pac, vertex_index):
    """Decode using the OLD (wrong) pac_codec layout for comparison."""
    off = VB_START + vertex_index * STRIDE

    # Old layout: bytes 12-15 = bone indices as 4×u8
    old_bi = struct.unpack_from('4B', pac, off + 12)
    # Old layout: bytes 20-23 = bone weights as 4×u8
    old_wt = struct.unpack_from('4B', pac, off + 20)

    return {
        'old_bone_indices': list(old_bi),
        'old_bone_weights': list(old_wt),
    }


def main():
    pac = PAC_PATH.read_bytes()
    skeleton = json.loads(SKELETON_PATH.read_text(encoding='utf-8'))
    palette_hashes = read_bone_palette(pac)
    hash_to_bone = {b['hash']: b for b in skeleton}

    print("=" * 70)
    print("  VERTEX LAYOUT VERIFICATION — DXIL vs pac_codec")
    print("=" * 70)

    print(f"\n  Bone palette: {len(palette_hashes)} entries at 0x443")
    print(f"  Skeleton: {len(skeleton)} bones")

    # Show first 10 palette entries
    print(f"\n  Palette sample (first 10):")
    for i in range(min(10, len(palette_hashes))):
        h = palette_hashes[i]
        bone = hash_to_bone.get(h)
        name = bone['name'] if bone else '???'
        print(f"    [{i:3d}] hash=0x{h:08X}  {name}")

    # ── Test 1: Are half-float bone indices plausible? ──────────────
    print(f"\n{'='*70}")
    print("  TEST 1: Half-float bone indices at bytes 12-15")
    print("=" * 70)

    half_idx_counter = Counter()
    half_nan_count = 0
    half_out_of_range = 0
    half_samples = []

    for vi in range(TOTAL_VERTS):
        v = decode_vertex_new_layout(pac, vi)
        for ch in range(2):
            raw = v['half2_raw'] if ch == 0 else v['half3_raw']
            fval = half_to_float(raw)
            idx = v['bone_indices'][ch]

            if np.isnan(fval) or np.isinf(fval):
                half_nan_count += 1
            elif idx < 0 or idx >= len(palette_hashes):
                half_out_of_range += 1
            else:
                half_idx_counter[idx] += 1

        if len(half_samples) < 5:
            half_samples.append(v)

    print(f"  NaN/Inf values: {half_nan_count}")
    print(f"  Out of palette range: {half_out_of_range}")
    print(f"  Valid palette indices: {sum(half_idx_counter.values())}")
    print(f"  Distinct indices used: {len(half_idx_counter)}")
    if half_idx_counter:
        print(f"  Top 10 most used:")
        for idx, count in half_idx_counter.most_common(10):
            h = palette_hashes[idx] if idx < len(palette_hashes) else 0
            bone = hash_to_bone.get(h)
            name = bone['name'] if bone else '???'
            print(f"    idx={idx:3d} count={count:5d}  {name}")

    print(f"\n  Sample vertices (first 5):")
    for i, v in enumerate(half_samples):
        h2 = v['half2_raw']
        h3 = v['half3_raw']
        f2 = half_to_float(h2)
        f3 = half_to_float(h3)
        print(f"    v{i}: half2=0x{h2:04X}({f2:8.2f}) half3=0x{h3:04X}({f3:8.2f}) "
              f"-> idx=[{v['bone_indices'][0]}, {v['bone_indices'][1]}]")

    # ── Test 2: Are 10-bit bone indices plausible? ──────────────────
    print(f"\n{'='*70}")
    print("  TEST 2: 10-bit packed bone indices at bytes 20-27")
    print("=" * 70)

    tenbit_counter = Counter()
    tenbit_out_of_range = 0

    for vi in range(TOTAL_VERTS):
        v = decode_vertex_new_layout(pac, vi)
        for ch in range(2, 8):
            idx = v['bone_indices'][ch]
            if idx >= len(palette_hashes):
                tenbit_out_of_range += 1
            else:
                tenbit_counter[idx] += 1

    print(f"  Out of palette range (>{len(palette_hashes)-1}): {tenbit_out_of_range}")
    print(f"  Valid palette indices: {sum(tenbit_counter.values())}")
    print(f"  Distinct indices used: {len(tenbit_counter)}")
    if tenbit_counter:
        print(f"  Top 10 most used:")
        for idx, count in tenbit_counter.most_common(10):
            h = palette_hashes[idx] if idx < len(palette_hashes) else 0
            bone = hash_to_bone.get(h)
            name = bone['name'] if bone else '???'
            print(f"    idx={idx:3d} count={count:5d}  {name}")

    # ── Test 3: Are weights at bytes 28-35 plausible? ───────────────
    print(f"\n{'='*70}")
    print("  TEST 3: Bone weights at bytes 28-35 (8 × u8)")
    print("=" * 70)

    weight_sum_histogram = Counter()
    zero_weight_verts = 0
    active_channels = Counter()

    for vi in range(TOTAL_VERTS):
        v = decode_vertex_new_layout(pac, vi)
        wt = v['weights']
        total = sum(wt)
        weight_sum_histogram[total] += 1
        if total == 0:
            zero_weight_verts += 1
        for ch, w in enumerate(wt):
            if w > 0:
                active_channels[ch] += 1

    print(f"  Zero-weight vertices: {zero_weight_verts}")
    print(f"  Weight sum distribution:")
    for s in sorted(weight_sum_histogram.keys()):
        count = weight_sum_histogram[s]
        if count > 10 or s in [0, 255, 254, 256, 510]:
            print(f"    sum={s:4d}: {count:6d} verts")
    print(f"  Active weight channels:")
    for ch in range(8):
        print(f"    channel {ch}: {active_channels.get(ch, 0):6d} verts with w>0")

    # ── Test 4: Compare old vs new layout ───────────────────────────
    print(f"\n{'='*70}")
    print("  TEST 4: Old layout (pac_codec) vs New layout comparison")
    print("=" * 70)

    print(f"\n  First 10 vertices — comparing interpretations:")
    for vi in range(10):
        new_v = decode_vertex_new_layout(pac, vi)
        old_v = decode_vertex_old_layout(pac, vi)
        print(f"\n  Vertex {vi}:")
        print(f"    OLD bone_idx:  {old_v['old_bone_indices']}  (4×u8 at bytes 12-15)")
        print(f"    NEW bone_idx:  {new_v['bone_indices']}  (2 half + 6×10bit)")
        print(f"    OLD bone_wt:   {old_v['old_bone_weights']}  (4×u8 at bytes 20-23)")
        print(f"    NEW bone_wt:   {new_v['weights']}  (8×u8 at bytes 28-35)")
        # Show what bones the new indices resolve to
        resolved = []
        for ch in range(8):
            idx = new_v['bone_indices'][ch]
            w = new_v['weights'][ch]
            if w > 0 and idx < len(palette_hashes):
                h = palette_hashes[idx]
                bone = hash_to_bone.get(h)
                resolved.append(f"{bone['name'] if bone else '???'}(w={w})")
        if resolved:
            print(f"    Resolved: {', '.join(resolved)}")

    # ── Test 5: Per-submesh bone sanity ─────────────────────────────
    print(f"\n{'='*70}")
    print("  TEST 5: Per-submesh — do bones make anatomical sense?")
    print("=" * 70)

    for si, sm_name in enumerate(SUBMESH_NAMES):
        base = SUBMESH_BASES[si]
        count = SUBMESH_VERTEX_COUNTS[si]
        bone_counter = Counter()

        for vi in range(base, base + count):
            v = decode_vertex_new_layout(pac, vi)
            for ch in range(8):
                idx = v['bone_indices'][ch]
                w = v['weights'][ch]
                if w > 0 and idx < len(palette_hashes):
                    h = palette_hashes[idx]
                    bone = hash_to_bone.get(h)
                    if bone:
                        bone_counter[bone['name']] += 1

        top_bones = bone_counter.most_common(8)
        print(f"\n  {sm_name} ({count} verts) — top bones:")
        for bname, bcount in top_bones:
            print(f"    {bname:30s}: {bcount:5d}")

    print(f"\n{'='*70}")
    print("  VERIFICATION COMPLETE")
    print("=" * 70)


if __name__ == '__main__':
    main()
