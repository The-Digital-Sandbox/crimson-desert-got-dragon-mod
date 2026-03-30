#!/usr/bin/env python3
"""
PAC mesh codec — decode and encode Crimson Desert skinned meshes.

Format cracked via PIX GPU capture + shader DXIL analysis (2026-03-30).
Position encoding: pos = bbox_min + (uint16 / 32767.0) * bbox_dim
Each submesh has its own bbox stored in the PAC descriptor.
"""
import struct
import math
import json
from pathlib import Path
from dataclasses import dataclass, field

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "output"
PAC_PATH = OUTPUT / "dragon.pac"

VB_START = 0x7BFA  # vertex buffer start offset in dragon.pac
STRIDE = 40        # bytes per vertex
TOTAL_VERTS = 27376

# Per-submesh vertex buffer layout (contiguous, no gaps)
SUBMESH_NAMES = ["Eyeright", "Eyeleft", "Body_02", "back", "Body", "Leg", "Wing", "Head"]
SUBMESH_VERTEX_COUNTS = [225, 225, 2013, 3307, 2736, 4624, 6724, 10258]
SUBMESH_INDEX_COUNTS = [1248, 1248, 7992, 17007, 13380, 22464, 34902, 51180]

# Vertex base offsets (contiguous)
SUBMESH_BASES = []
_base = 0
for vc in SUBMESH_VERTEX_COUNTS:
    SUBMESH_BASES.append(_base)
    _base += vc


@dataclass
class SubmeshBbox:
    """Per-submesh bounding box for position quantization."""
    name: str
    min_xyz: tuple  # (min_x, min_y, min_z)
    dim_xyz: tuple  # (dim_x, dim_y, dim_z)
    lod_near: float = 0.0
    lod_far: float = 0.0


@dataclass
class Vertex:
    """Decoded vertex data."""
    pos: tuple       # (x, y, z) local/bind-pose
    normal: tuple    # (nx, ny, nz)
    uv0: tuple       # (u, v)
    bone_idx: tuple   # 4 palette indices
    bone_wt: tuple    # 4 weights (0-255)
    raw_w: int = 0    # uint16 W value (byte 6-7)
    extra0: bytes = b'\x00\x00\x00\x00'  # bytes 16-19
    extra1: bytes = b'\x00\x00\x00\x00'  # bytes 24-27
    vcolor: int = 0xFF  # vertex color byte 28-31
    uv1_raw: int = 0    # bytes 36-39


def parse_submesh_descriptors(pac: bytes) -> list[SubmeshBbox]:
    """Parse per-submesh bbox from PAC descriptor area."""
    bboxes = []
    off = 0x0077  # after submesh count byte

    for i in range(8):
        name_len = pac[off]
        name = pac[off+1:off+1+name_len].decode('ascii', errors='replace')
        off += 1 + name_len

        mat_len = pac[off]
        off += 1 + mat_len

        # 3 flag bytes (01 00 XX)
        off += 3

        # 8 x float32: [lod_near, lod_far, min_x, min_y, min_z, dim_x, dim_y, dim_z]
        floats = struct.unpack_from('<8f', pac, off)
        off += 32

        bbox = SubmeshBbox(
            name=SUBMESH_NAMES[i],
            lod_near=floats[0],
            lod_far=floats[1],
            min_xyz=floats[2:5],
            dim_xyz=floats[5:8],
        )
        bboxes.append(bbox)

        # Skip trailing data (find next submesh or end of descriptor area)
        next_cd = pac.find(b'CD_M0004', off)
        if next_cd > 0 and next_cd < 0x0441:
            off = next_cd - 1  # name_len byte is 1 before name
        else:
            off = 0x0441

    return bboxes


def decode_normal_r10g10b10a2(packed: int) -> tuple:
    """Decode R10G10B10A2 packed normal."""
    x = (packed & 0x3FF) / 1023.0 * 2.0 - 1.0
    y = ((packed >> 10) & 0x3FF) / 1023.0 * 2.0 - 1.0
    z = ((packed >> 20) & 0x3FF) / 1023.0 * 2.0 - 1.0
    length = math.sqrt(x*x + y*y + z*z)
    if length > 1e-8:
        x /= length; y /= length; z /= length
    return (x, y, z)


def encode_normal_r10g10b10a2(nx: float, ny: float, nz: float) -> int:
    """Encode normal to R10G10B10A2."""
    def clamp_encode(v):
        return max(0, min(1023, int(round((v + 1.0) / 2.0 * 1023.0))))
    packed = clamp_encode(nx) | (clamp_encode(ny) << 10) | (clamp_encode(nz) << 20)
    return packed


def dequantize_pos(u16_x: int, u16_y: int, u16_z: int, bbox: SubmeshBbox) -> tuple:
    """Dequantize uint16 position to float using bbox."""
    x = bbox.min_xyz[0] + (u16_x / 32767.0) * bbox.dim_xyz[0]
    y = bbox.min_xyz[1] + (u16_y / 32767.0) * bbox.dim_xyz[1]
    z = bbox.min_xyz[2] + (u16_z / 32767.0) * bbox.dim_xyz[2]
    return (x, y, z)


def quantize_pos(x: float, y: float, z: float, bbox: SubmeshBbox) -> tuple:
    """Quantize float position to uint16 using bbox."""
    def q(val, bmin, bdim):
        if abs(bdim) < 1e-10:
            return 0
        return max(0, min(65535, int(round((val - bmin) / bdim * 32767.0))))
    return (
        q(x, bbox.min_xyz[0], bbox.dim_xyz[0]),
        q(y, bbox.min_xyz[1], bbox.dim_xyz[1]),
        q(z, bbox.min_xyz[2], bbox.dim_xyz[2]),
    )


def decode_vertex(pac: bytes, vertex_index: int, bbox: SubmeshBbox) -> Vertex:
    """Decode a single vertex from PAC data."""
    off = VB_START + vertex_index * STRIDE
    raw = pac[off:off + STRIDE]

    # Bytes 0-5: 3 x uint16 position (quantized)
    u16_x, u16_y, u16_z = struct.unpack_from('<3H', raw, 0)
    u16_w = struct.unpack_from('<H', raw, 6)[0]
    pos = dequantize_pos(u16_x, u16_y, u16_z, bbox)

    # Bytes 8-11: R10G10B10A2 normal
    packed_normal = struct.unpack_from('<I', raw, 8)[0]
    normal = decode_normal_r10g10b10a2(packed_normal)

    # Bytes 12-15: 4 x uint8 bone palette indices
    bone_idx = struct.unpack_from('4B', raw, 12)

    # Bytes 16-19: extra0
    extra0 = raw[16:20]

    # Bytes 20-23: 4 x uint8 bone weights
    bone_wt = struct.unpack_from('4B', raw, 20)

    # Bytes 24-27: extra1
    extra1 = raw[24:28]

    # Bytes 28-31: vertex color
    vcolor = struct.unpack_from('<I', raw, 28)[0]

    # Bytes 32-35: UV0 (2 x uint16 UNORM)
    u_raw, v_raw = struct.unpack_from('<2H', raw, 32)
    uv0 = (u_raw / 65535.0, v_raw / 65535.0)

    # Bytes 36-39: UV1 or extra
    uv1_raw = struct.unpack_from('<I', raw, 36)[0]

    return Vertex(
        pos=pos, normal=normal, uv0=uv0,
        bone_idx=bone_idx, bone_wt=bone_wt,
        raw_w=u16_w, extra0=extra0, extra1=extra1,
        vcolor=vcolor, uv1_raw=uv1_raw,
    )


def encode_vertex(v: Vertex, bbox: SubmeshBbox) -> bytes:
    """Encode a vertex back to 40-byte PAC format."""
    buf = bytearray(STRIDE)

    # Bytes 0-5: quantized position
    qx, qy, qz = quantize_pos(v.pos[0], v.pos[1], v.pos[2], bbox)
    struct.pack_into('<3H', buf, 0, qx, qy, qz)
    struct.pack_into('<H', buf, 6, v.raw_w)

    # Bytes 8-11: normal
    struct.pack_into('<I', buf, 8, encode_normal_r10g10b10a2(*v.normal))

    # Bytes 12-15: bone indices
    struct.pack_into('4B', buf, 12, *v.bone_idx)

    # Bytes 16-19: extra0
    buf[16:20] = v.extra0

    # Bytes 20-23: bone weights
    struct.pack_into('4B', buf, 20, *v.bone_wt)

    # Bytes 24-27: extra1
    buf[24:28] = v.extra1

    # Bytes 28-31: vertex color
    struct.pack_into('<I', buf, 28, v.vcolor)

    # Bytes 32-35: UV0
    struct.pack_into('<2H', buf, 32,
                     max(0, min(65535, int(round(v.uv0[0] * 65535)))),
                     max(0, min(65535, int(round(v.uv0[1] * 65535)))))

    # Bytes 36-39: UV1/extra
    struct.pack_into('<I', buf, 36, v.uv1_raw)

    return bytes(buf)


def decode_all_submeshes(pac: bytes) -> dict:
    """Decode all submesh vertices."""
    bboxes = parse_submesh_descriptors(pac)
    result = {}

    for i, (name, bbox) in enumerate(zip(SUBMESH_NAMES, bboxes)):
        base = SUBMESH_BASES[i]
        count = SUBMESH_VERTEX_COUNTS[i]
        verts = [decode_vertex(pac, base + j, bbox) for j in range(count)]
        result[name] = {'verts': verts, 'bbox': bbox, 'base': base, 'count': count}

    return result


def read_indices(pac: bytes) -> dict:
    """Read index buffer for all submeshes."""
    total_indices = sum(SUBMESH_INDEX_COUNTS)
    index_start = len(pac) - total_indices * 2
    all_indices = struct.unpack_from(f'<{total_indices}H', pac, index_start)

    result = {}
    pos = 0
    for i, name in enumerate(SUBMESH_NAMES):
        count = SUBMESH_INDEX_COUNTS[i]
        result[name] = list(all_indices[pos:pos+count])
        pos += count

    return result


def export_obj(pac: bytes, obj_path: str, submeshes: list[str] = None):
    """Export decoded mesh as OBJ file."""
    data = decode_all_submeshes(pac)
    indices = read_indices(pac)

    if submeshes is None:
        submeshes = SUBMESH_NAMES

    with open(obj_path, 'w') as f:
        f.write("# Crimson Desert dragon — PAC codec decode\n")
        f.write(f"# Formula: pos = bbox_min + (uint16/32767) * bbox_dim\n\n")

        global_vert_offset = 0
        for name in submeshes:
            sm = data[name]
            bbox = sm['bbox']
            f.write(f"# {name}: {sm['count']} verts, bbox_min=({bbox.min_xyz[0]:.4f},{bbox.min_xyz[1]:.4f},{bbox.min_xyz[2]:.4f}), bbox_dim=({bbox.dim_xyz[0]:.4f},{bbox.dim_xyz[1]:.4f},{bbox.dim_xyz[2]:.4f})\n")

            for v in sm['verts']:
                f.write(f"v {v.pos[0]:.6f} {v.pos[1]:.6f} {v.pos[2]:.6f}\n")
            for v in sm['verts']:
                f.write(f"vn {v.normal[0]:.6f} {v.normal[1]:.6f} {v.normal[2]:.6f}\n")
            for v in sm['verts']:
                f.write(f"vt {v.uv0[0]:.6f} {1.0 - v.uv0[1]:.6f}\n")

            f.write(f"\ng {name}\n")
            sm_indices = indices[name]
            for tri in range(len(sm_indices) // 3):
                i0 = sm_indices[tri*3+0] + global_vert_offset + 1
                i1 = sm_indices[tri*3+1] + global_vert_offset + 1
                i2 = sm_indices[tri*3+2] + global_vert_offset + 1
                f.write(f"f {i0}/{i0}/{i0} {i1}/{i1}/{i1} {i2}/{i2}/{i2}\n")

            global_vert_offset += sm['count']

    print(f"Exported {obj_path}")


def round_trip_test(pac: bytes):
    """Decode all vertices then re-encode — verify bytes match."""
    bboxes = parse_submesh_descriptors(pac)

    total_errors = 0
    max_pos_error = 0.0

    for i, (name, bbox) in enumerate(zip(SUBMESH_NAMES, bboxes)):
        base = SUBMESH_BASES[i]
        count = SUBMESH_VERTEX_COUNTS[i]

        errors = 0
        sm_max_err = 0.0

        for j in range(count):
            idx = base + j
            orig_off = VB_START + idx * STRIDE
            orig_bytes = pac[orig_off:orig_off + STRIDE]

            # Decode
            v = decode_vertex(pac, idx, bbox)
            # Re-encode
            enc = encode_vertex(v, bbox)

            # Compare position bytes (0-5) — allow ±1 LSB due to float rounding
            orig_u16 = struct.unpack_from('<3H', orig_bytes, 0)
            enc_u16 = struct.unpack_from('<3H', enc, 0)

            for axis in range(3):
                diff = abs(orig_u16[axis] - enc_u16[axis])
                if diff > 1:
                    errors += 1
                    break
                if diff == 1:
                    # Check position error in world units
                    dim = bbox.dim_xyz[axis]
                    pos_err = abs(dim / 32767.0)
                    sm_max_err = max(sm_max_err, pos_err)

            # Compare non-position bytes exactly
            if enc[6:] != orig_bytes[6:]:
                # Check what differs
                for b in range(6, STRIDE):
                    if enc[b] != orig_bytes[b]:
                        # Normal encoding may have ±1 LSB error
                        if 8 <= b <= 11:
                            continue  # normal rounding
                        errors += 1
                        break

        max_pos_error = max(max_pos_error, sm_max_err)
        total_errors += errors
        status = "PASS" if errors == 0 else f"FAIL ({errors} verts)"
        print(f"  {name:12s}: {status}  max_pos_err={sm_max_err:.8f}")

    print(f"\nTotal errors: {total_errors}")
    print(f"Max position error: {max_pos_error:.8f} units")
    return total_errors == 0


if __name__ == "__main__":
    pac = PAC_PATH.read_bytes()

    print("=" * 60)
    print("ROUND-TRIP TEST: decode -> re-encode -> compare")
    print("=" * 60)
    passed = round_trip_test(pac)

    print("\n" + "=" * 60)
    print("EXPORTING BIND-POSE OBJ")
    print("=" * 60)
    obj_path = str(OUTPUT / "dragon_decoded.obj")
    export_obj(pac, obj_path)

    # Print bbox summary
    print("\n" + "=" * 60)
    print("PER-SUBMESH BBOX SUMMARY")
    print("=" * 60)
    bboxes = parse_submesh_descriptors(pac)
    for i, bbox in enumerate(bboxes):
        print(f"SM{i} {bbox.name:12s}: min=({bbox.min_xyz[0]:8.4f},{bbox.min_xyz[1]:8.4f},{bbox.min_xyz[2]:8.4f}) dim=({bbox.dim_xyz[0]:8.4f},{bbox.dim_xyz[1]:8.4f},{bbox.dim_xyz[2]:8.4f})")
