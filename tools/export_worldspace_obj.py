"""
Export CD dragon mesh in WORLD SPACE — apply bone transforms to PAC vertices.

PAC vertices are bone-local offsets. To get the actual dragon shape:
  world_pos = sum(weight[i] * bone_world_matrix[palette[index[i]]] @ local_pos)

Uses the 1st PAB matrix (local_matrix in JSON) = actual world/armature-space transform.
Applies weighted skinning with all 4 bone influences per vertex.

Output: dragon_worldspace.obj — ready for Blender import and shrinkwrap.
"""
import struct, json, math
import numpy as np
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "output"
PAC_PATH = OUTPUT / "dragon.pac"
SKEL_PATH = OUTPUT / "cd_skeleton.json"
OUT_OBJ = OUTPUT / "dragon_worldspace.obj"

# PAC layout
VB_START = 0x7BFA
STRIDE = 40
SM_NAMES = ["Eyeright", "Eyeleft", "Body_02", "back", "Body", "Leg", "Wing", "Head"]
SM_VCOUNTS = [225, 225, 2013, 3307, 2736, 4624, 6724, 10258]
SM_ICOUNTS = [1248, 1248, 7992, 17007, 13380, 22464, 34902, 51180]
TOTAL_VERTS = sum(SM_VCOUNTS)

SM_BASES = []
_b = 0
for vc in SM_VCOUNTS:
    SM_BASES.append(_b)
    _b += vc


def parse_bboxes(pac):
    """Parse per-submesh bounding boxes from PAC descriptor area."""
    bboxes = []
    off = 0x0077
    for i in range(8):
        name_len = pac[off]; off += 1 + name_len
        mat_len = pac[off]; off += 1 + mat_len
        off += 3
        floats = struct.unpack_from('<8f', pac, off)
        off += 32
        bboxes.append({
            'min': np.array(floats[2:5]),
            'dim': np.array(floats[5:8]),
        })
        next_cd = pac.find(b'CD_M0004', off)
        if next_cd > 0 and next_cd < 0x0441:
            off = next_cd - 1
        else:
            off = 0x0441
    return bboxes


def main():
    pac = open(PAC_PATH, 'rb').read()
    with open(SKEL_PATH) as f:
        skel = json.load(f)

    bboxes = parse_bboxes(pac)

    # Build bone palette: palette[i] = bone hash
    pal_count = struct.unpack_from('<H', pac, 0x0441)[0]
    palette_hashes = [struct.unpack_from('<I', pac, 0x0443 + i * 4)[0] for i in range(pal_count)]
    print(f"Bone palette: {pal_count} entries")

    # Build hash -> world matrix lookup
    # 1st PAB matrix ("local_matrix" in JSON) = actual world transform
    hash_to_world = {}
    for bone in skel:
        mat = np.array(bone['local_matrix'], dtype=np.float64)  # 4x4 row-major, DX convention
        hash_to_world[bone['hash']] = mat

    # For each palette index, get the world matrix
    palette_world = {}
    for i, h in enumerate(palette_hashes):
        if h in hash_to_world:
            palette_world[i] = hash_to_world[h]

    print(f"Palette bones matched: {len(palette_world)}/{pal_count}")

    # Skinning: transform each vertex to world space
    world_positions = []
    sm_idx_for_vert = []  # track which submesh each vert belongs to

    for si in range(8):
        base = SM_BASES[si]
        count = SM_VCOUNTS[si]
        bbox = bboxes[si]

        for j in range(count):
            off = VB_START + (base + j) * STRIDE

            # Dequantize position using per-submesh bbox
            u16 = struct.unpack_from('<3H', pac, off)
            local_pos = np.array([
                bbox['min'][0] + (u16[0] / 32767.0) * bbox['dim'][0],
                bbox['min'][1] + (u16[1] / 32767.0) * bbox['dim'][1],
                bbox['min'][2] + (u16[2] / 32767.0) * bbox['dim'][2],
            ])

            # Bone indices and weights
            bi = [pac[off + 12 + b] for b in range(4)]
            bw = [pac[off + 20 + b] for b in range(4)]
            total_w = sum(bw)

            if total_w == 0:
                world_positions.append(local_pos)
                sm_idx_for_vert.append(si)
                continue

            # Weighted skinning: world = sum(w * (local @ bone_world))
            # DX row-vector convention: v_world = v_local @ M
            pos_h = np.array([local_pos[0], local_pos[1], local_pos[2], 1.0])
            result = np.zeros(3)

            for b in range(4):
                if bw[b] == 0:
                    continue
                w = bw[b] / total_w
                if bi[b] in palette_world:
                    mat = palette_world[bi[b]]
                    transformed = pos_h @ mat  # row-vector @ matrix
                    result += transformed[:3] * w
                else:
                    result += local_pos * w

            world_positions.append(result)
            sm_idx_for_vert.append(si)

    world_positions = np.array(world_positions)
    print(f"\nWorld-space positions ({len(world_positions)} verts):")
    print(f"  X: [{world_positions[:,0].min():.3f}, {world_positions[:,0].max():.3f}]")
    print(f"  Y: [{world_positions[:,1].min():.3f}, {world_positions[:,1].max():.3f}]")
    print(f"  Z: [{world_positions[:,2].min():.3f}, {world_positions[:,2].max():.3f}]")

    # Read index buffer
    total_indices = sum(SM_ICOUNTS)
    idx_start = len(pac) - total_indices * 2
    all_indices = struct.unpack_from(f'<{total_indices}H', pac, idx_start)

    # Write OBJ with submesh groups and faces
    with open(OUT_OBJ, 'w') as f:
        f.write("# CD Dragon — world-space (bone transforms applied)\n")
        f.write(f"# {len(world_positions)} verts, weighted skinning from PAC + PAB\n\n")

        for x, y, z in world_positions:
            f.write(f"v {x:.6f} {y:.6f} {z:.6f}\n")

        idx_pos = 0
        global_vert_offset = 0
        for si in range(8):
            count = SM_VCOUNTS[si]
            icount = SM_ICOUNTS[si]
            base = SM_BASES[si]
            f.write(f"\ng {SM_NAMES[si]}\n")
            for tri in range(icount // 3):
                i0 = all_indices[idx_pos + tri*3 + 0] + base + 1
                i1 = all_indices[idx_pos + tri*3 + 1] + base + 1
                i2 = all_indices[idx_pos + tri*3 + 2] + base + 1
                f.write(f"f {i0} {i1} {i2}\n")
            idx_pos += icount

    print(f"\nWrote: {OUT_OBJ}")


if __name__ == '__main__':
    main()
