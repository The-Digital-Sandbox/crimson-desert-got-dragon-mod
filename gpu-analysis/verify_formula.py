"""
Verify the position encoding formula from the shader:
  pos = bbox_min + (uint16 / 32767.0) * bbox_dim

Then bone transforms are applied. We verify by checking if the dequantized
positions form a sensible bind-pose mesh.
"""
import struct
import csv
import numpy as np

PAC_PATH = r"C:\Users\waelj\got-dragon-cd-mod\output\dragon.pac"
VB_START = 0x7BFA
STRIDE = 40

# Candidate bbox entries from render parameters (entries 112-120)
BBOX_CANDIDATES = {
    112: {"min": (-0.4559, 1.1044, -3.2347), "dim": (0.9091, 0.5301, 3.2347)},
    115: {"min": (-0.4847, 0.7248, -2.4956), "dim": (0.9699, 0.5540, 2.4956)},
    116: {"min": (-0.6638, 1.6195, -1.8393), "dim": (1.3577, 1.0496, 2.3280)},
    117: {"min": (-0.6293, 0.7813, -3.0450), "dim": (1.2617, 1.8093, 9.4253)},
    118: {"min": (-1.0292, -0.0150, -0.5279), "dim": (2.0566, 3.1157, 2.3679)},
    119: {"min": (-7.9752, 1.1535, -2.7553), "dim": (15.9505, 0.8571, 6.3700)},
    120: {"min": (-0.7322, 0.8520, -3.6422), "dim": (1.5212, 1.9972, 3.6422)},
}

# Also try entries 26-29 (large volumes)
BBOX_CANDIDATES.update({
    26: {"min": (-2.2653, -1.6771, -0.2293), "dim": (4.5215, 3.7092, 1.0525)},
    27: {"min": (-2.1592, -0.8938, -0.0484), "dim": (4.2328, 2.6999, 1.0298)},
    29: {"min": (-2.0970, -0.1847, -0.1736), "dim": (4.1563, 2.3167, 1.7468)},
})

SUBMESHES = {
    "SM2_Body_02":  {"verts": 2013, "base": 450,   "gpu_id": "7153", "name": "horns_spikes"},
    "SM3_back":     {"verts": 3307, "base": 2463,  "gpu_id": "7154", "name": "neck"},
    "SM4_Body":     {"verts": 2736, "base": 5770,  "gpu_id": "7155", "name": "tail_body"},
    "SM5_Leg":      {"verts": 4624, "base": 8506,  "gpu_id": "7156", "name": "body_legs"},
    "SM6_Wing":     {"verts": 6724, "base": 13130, "gpu_id": "7157", "name": "wings"},
    "SM7_Head":     {"verts": 10258,"base": 19854, "gpu_id": "7158", "name": "head"},
}

def read_pac_uint16(pac_data, vertex_index):
    """Read bytes 0-7 as uint16 values (the correct interpretation)."""
    offset = VB_START + vertex_index * STRIDE
    raw = pac_data[offset:offset + STRIDE]

    # Bytes 0-3 as uint32 LE
    val0 = struct.unpack_from('<I', raw, 0)[0]
    # Bytes 4-7 as uint32 LE
    val1 = struct.unpack_from('<I', raw, 4)[0]

    u16_x = val0 & 0xFFFF         # lower 16 bits
    u16_y = (val0 >> 16) & 0xFFFF # upper 16 bits
    u16_z = val1 & 0xFFFF         # lower 16 bits
    u16_w = (val1 >> 16) & 0xFFFF # upper 16 bits (W/sign)

    return u16_x, u16_y, u16_z, u16_w

def dequantize(u16_x, u16_y, u16_z, bbox_min, bbox_dim):
    """Apply shader formula: pos = bbox_min + (uint16 / 32767) * bbox_dim"""
    x = bbox_min[0] + (u16_x / 32767.0) * bbox_dim[0]
    y = bbox_min[1] + (u16_y / 32767.0) * bbox_dim[1]
    z = bbox_min[2] + (u16_z / 32767.0) * bbox_dim[2]
    return x, y, z

def main():
    with open(PAC_PATH, 'rb') as f:
        pac_data = f.read()

    print("=" * 80)
    print("TESTING POSITION FORMULA: pos = bbox_min + (uint16/32767) * bbox_dim")
    print("=" * 80)

    # For each submesh, try each bbox candidate and see which produces
    # a mesh that makes sense (reasonable range, not collapsed)
    for sm_name, sm in SUBMESHES.items():
        base = sm['base']
        num_verts = sm['verts']

        # Read first 20 vertices
        verts_u16 = []
        for i in range(min(20, num_verts)):
            verts_u16.append(read_pac_uint16(pac_data, base + i))

        print(f"\n{'='*60}")
        print(f"{sm_name} ({sm['name']}) - {num_verts} verts, base={base}")
        print(f"{'='*60}")

        # Show raw uint16 values for first 5 verts
        print(f"\nRaw uint16 values (first 5):")
        for i, (x, y, z, w) in enumerate(verts_u16[:5]):
            print(f"  v{i}: X={x:5d} Y={y:5d} Z={z:5d} W={w:5d}")

        # Try each bbox
        print(f"\nBbox candidates (showing vertex 0 decoded):")
        for bbox_idx, bbox in sorted(BBOX_CANDIDATES.items()):
            x, y, z = dequantize(verts_u16[0][0], verts_u16[0][1], verts_u16[0][2],
                                  bbox["min"], bbox["dim"])
            # Also compute range for all 20 verts
            positions = [dequantize(v[0], v[1], v[2], bbox["min"], bbox["dim"]) for v in verts_u16]
            xs = [p[0] for p in positions]
            ys = [p[1] for p in positions]
            zs = [p[2] for p in positions]
            span_x = max(xs) - min(xs)
            span_y = max(ys) - min(ys)
            span_z = max(zs) - min(zs)
            print(f"  bbox[{bbox_idx:3d}]: v0=({x:8.4f}, {y:8.4f}, {z:8.4f}), span=({span_x:.4f}, {span_y:.4f}, {span_z:.4f})")

    # Now let's try to build bind-pose meshes with the best candidates and save as OBJ
    print("\n" + "=" * 80)
    print("BUILDING BIND-POSE MESHES WITH BEST BBOX CANDIDATES")
    print("=" * 80)

    # The 8 submeshes should each use a different bbox entry
    # Let's try all combinations and see which ones produce non-degenerate meshes
    for sm_name, sm in SUBMESHES.items():
        base = sm['base']
        num_verts = sm['verts']

        best_bbox_idx = None
        best_span = 0

        # Sample 100 verts
        sample_indices = list(range(0, num_verts, max(1, num_verts // 100)))[:100]
        sample_u16 = [read_pac_uint16(pac_data, base + i) for i in sample_indices]

        for bbox_idx, bbox in BBOX_CANDIDATES.items():
            positions = [dequantize(v[0], v[1], v[2], bbox["min"], bbox["dim"]) for v in sample_u16]
            xs = [p[0] for p in positions]
            ys = [p[1] for p in positions]
            zs = [p[2] for p in positions]
            span = (max(xs)-min(xs)) * (max(ys)-min(ys)) * (max(zs)-min(zs))
            if span > best_span:
                best_span = span
                best_bbox_idx = bbox_idx

        bbox = BBOX_CANDIDATES[best_bbox_idx]
        print(f"\n{sm_name} ({sm['name']}): best bbox = entry [{best_bbox_idx}], volume={best_span:.4f}")
        print(f"  min=({bbox['min'][0]:.4f}, {bbox['min'][1]:.4f}, {bbox['min'][2]:.4f})")
        print(f"  dim=({bbox['dim'][0]:.4f}, {bbox['dim'][1]:.4f}, {bbox['dim'][2]:.4f})")

        # Write bind-pose OBJ using this bbox
        all_verts = [read_pac_uint16(pac_data, base + i) for i in range(num_verts)]
        positions = [dequantize(v[0], v[1], v[2], bbox["min"], bbox["dim"]) for v in all_verts]

        obj_path = f"C:/Users/waelj/Desktop/Outputs/bindpose_{sm['name']}.obj"
        with open(obj_path, 'w') as f:
            f.write(f"# Bind-pose {sm['name']} using bbox entry {best_bbox_idx}\n")
            f.write(f"# bbox_min = {bbox['min']}\n")
            f.write(f"# bbox_dim = {bbox['dim']}\n")
            for x, y, z in positions:
                f.write(f"v {x:.6f} {y:.6f} {z:.6f}\n")
        print(f"  Saved: {obj_path}")

if __name__ == "__main__":
    main()
