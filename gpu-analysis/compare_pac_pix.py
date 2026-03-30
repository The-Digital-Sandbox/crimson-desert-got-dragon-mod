"""
Compare PAC vertex data (bytes 0-7) with PIX-extracted world-space positions.
Goal: Find the encoding formula by looking at both sides of the equation.
"""
import struct
import csv
import os

PAC_PATH = r"C:\Users\waelj\got-dragon-cd-mod\output\dragon.pac"
PIX_DIR = r"C:\Users\waelj\Desktop\Outputs"

# Vertex buffer starts at 0x7BFA, stride 40 bytes, 27376 total verts
VB_START = 0x7BFA
STRIDE = 40

# Submesh layout from PAC analysis
SUBMESHES = {
    "SM0_Eyeright": {"verts": 225,  "base": 0},
    "SM1_Eyeleft":  {"verts": 225,  "base": 225},
    "SM2_Body_02":  {"verts": 2013, "base": 450},
    "SM3_back":     {"verts": 3307, "base": 2463},
    "SM4_Body":     {"verts": 2736, "base": 5770},
    "SM5_Leg":      {"verts": 4624, "base": 8506},
    "SM6_Wing":     {"verts": 6724, "base": 13130},
    "SM7_Head":     {"verts": 10258, "base": 19854},  # might overflow, let's check
}

# Map PIX draw calls to submeshes
PIX_TO_SM = {
    "7153": "SM2_Body_02",  # horns/spikes = Body_02 (2013 verts ~ 1631 unique)
    "7154": "SM3_back",     # neck = back (3307 verts ~ 3026 unique)
    "7155": "SM4_Body",     # tail/body = Body (2736 verts ~ 2460 unique)
    "7156": "SM5_Leg",      # body/legs = Leg (4624 verts ~ 3820 unique)
    "7157": "SM6_Wing",     # wings = Wing (6724 verts ~ 5850 unique)
    "7158": "SM7_Head",     # head = Head (10258 verts ~ 8858 unique)
}

def read_pac_vertex(pac_data, vertex_index):
    """Read raw bytes 0-39 for a vertex from the PAC."""
    offset = VB_START + vertex_index * STRIDE
    if offset + STRIDE > len(pac_data):
        return None
    raw = pac_data[offset:offset + STRIDE]

    # Bytes 0-1: uint16 or float16 X
    # Bytes 2-3: uint16 or float16 Y
    # Bytes 4-5: uint16 or float16 Z
    # Bytes 6-7: uint16 or float16 W

    # Try float16 interpretation
    f16_x = struct.unpack_from('<e', raw, 0)[0] if len(raw) >= 2 else 0
    f16_y = struct.unpack_from('<e', raw, 2)[0] if len(raw) >= 4 else 0
    f16_z = struct.unpack_from('<e', raw, 4)[0] if len(raw) >= 6 else 0
    f16_w = struct.unpack_from('<e', raw, 6)[0] if len(raw) >= 8 else 0

    # Try uint16 interpretation
    u16_x = struct.unpack_from('<H', raw, 0)[0]
    u16_y = struct.unpack_from('<H', raw, 2)[0]
    u16_z = struct.unpack_from('<H', raw, 4)[0]
    u16_w = struct.unpack_from('<H', raw, 6)[0]

    # Also get bone indices and weights
    bone_indices = struct.unpack_from('4B', raw, 12)
    bone_weights = struct.unpack_from('4B', raw, 20)

    # UV0
    uv0_raw = struct.unpack_from('<2H', raw, 32)
    uv0 = (uv0_raw[0] / 65535.0, uv0_raw[1] / 65535.0)

    return {
        'f16': (f16_x, f16_y, f16_z, f16_w),
        'u16': (u16_x, u16_y, u16_z, u16_w),
        'raw_hex': raw[:8].hex(),
        'bone_idx': bone_indices,
        'bone_wt': bone_weights,
        'uv0': uv0,
        'full_hex': raw.hex(),
    }


def read_pix_csv(filepath, max_rows=None):
    """Read PIX CSV and return dict of Vertex_ID -> world position."""
    verts = {}
    with open(filepath, 'r') as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader):
            if max_rows and i >= max_rows:
                break
            vid = int(row['Vertex_ID'])
            if vid not in verts:  # first occurrence
                verts[vid] = {
                    'world_pos': (
                        float(row['TEXCOORD1_C0']),
                        float(row['TEXCOORD1_C1']),
                        float(row['TEXCOORD1_C2']),
                    ),
                    'clip_pos': (
                        float(row['SV_POSITION_C0']),
                        float(row['SV_POSITION_C1']),
                        float(row['SV_POSITION_C2']),
                        float(row['SV_POSITION_C3']),
                    ),
                    'uv': (
                        float(row['TEXCOORD_C0']),
                        float(row['TEXCOORD_C1']),
                    ),
                    'normal': (
                        float(row['TEXCOORD2_C0']),
                        float(row['TEXCOORD2_C1']),
                        float(row['TEXCOORD2_C2']),
                    ),
                }
    return verts


def main():
    # Read PAC
    with open(PAC_PATH, 'rb') as f:
        pac_data = f.read()

    print(f"PAC size: {len(pac_data):,} bytes")
    print(f"Vertex buffer at 0x{VB_START:X}, stride {STRIDE}")
    print(f"Max vertex index: {(len(pac_data) - VB_START) // STRIDE}")
    print()

    # Check total vertex capacity
    max_vert = (len(pac_data) - VB_START) // STRIDE
    print(f"Total vertices that fit: {max_vert}")

    # Try each submesh base offset to see if they make sense
    print("\n=== Checking submesh base offsets ===")
    for sm_name, sm in SUBMESHES.items():
        end = sm['base'] + sm['verts']
        fits = "OK" if end <= max_vert else f"OVERFLOW (need {end}, have {max_vert})"
        print(f"  {sm_name}: base={sm['base']}, verts={sm['verts']}, end={end} {fits}")

    # Compare for each PIX draw call
    for gpu_id, sm_name in PIX_TO_SM.items():
        csv_file = os.path.join(PIX_DIR, f"2026_3_30__9_24_50_GpuId{gpu_id}_VS_BufferData_exp0.csv")
        if not os.path.exists(csv_file):
            print(f"\n--- Skipping {gpu_id} ({sm_name}): CSV not found ---")
            continue

        sm = SUBMESHES[sm_name]
        base = sm['base']

        print(f"\n{'='*80}")
        print(f"Draw Call {gpu_id} -> {sm_name} (base vertex: {base})")
        print(f"{'='*80}")

        pix_verts = read_pix_csv(csv_file)
        print(f"PIX unique vertices: {len(pix_verts)}")

        # Get first 15 unique vertex IDs sorted
        sorted_vids = sorted(pix_verts.keys())[:15]

        print(f"\n{'VID':>6} | {'PAC f16 X':>10} {'f16 Y':>10} {'f16 Z':>10} {'f16 W':>10} | {'PIX World X':>12} {'World Y':>12} {'World Z':>12} | {'PAC UV0':>16} | {'PIX UV':>16} | Raw Hex")
        print("-" * 160)

        for vid in sorted_vids:
            pac_idx = base + vid
            pac_v = read_pac_vertex(pac_data, pac_idx)
            pix_v = pix_verts[vid]

            if pac_v is None:
                print(f"{vid:>6} | PAC: OUT OF RANGE")
                continue

            f16 = pac_v['f16']
            wp = pix_v['world_pos']
            pac_uv = pac_v['uv0']
            pix_uv = pix_v['uv']

            print(f"{vid:>6} | {f16[0]:>10.4f} {f16[1]:>10.4f} {f16[2]:>10.4f} {f16[3]:>10.4f} | {wp[0]:>12.5f} {wp[1]:>12.5f} {wp[2]:>12.5f} | ({pac_uv[0]:.4f},{pac_uv[1]:.4f}) | ({pix_uv[0]:.4f},{pix_uv[1]:.4f}) | {pac_v['raw_hex']}")

        # Also try without base offset (in case Vertex_ID is absolute)
        print(f"\n--- Same vertices WITHOUT base offset (Vertex_ID as absolute index) ---")
        for vid in sorted_vids[:5]:
            pac_v = read_pac_vertex(pac_data, vid)
            pix_v = pix_verts[vid]
            if pac_v:
                f16 = pac_v['f16']
                wp = pix_v['world_pos']
                print(f"{vid:>6} | {f16[0]:>10.4f} {f16[1]:>10.4f} {f16[2]:>10.4f} {f16[3]:>10.4f} | {wp[0]:>12.5f} {wp[1]:>12.5f} {wp[2]:>12.5f} | {pac_v['raw_hex']}")


if __name__ == "__main__":
    main()
