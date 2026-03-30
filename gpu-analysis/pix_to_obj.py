"""
Convert PIX GPU capture VS Buffer CSV exports to OBJ files for Blender.
Uses TEXCOORD1 (world-space positions) and TEXCOORD (UVs).
Triangles are defined by Primitive_ID (every 3 consecutive vertices = 1 triangle).
"""
import csv
import sys
import os
import glob

def parse_csv(filepath):
    """Parse a PIX VS Buffer CSV and return vertices, UVs, normals, and faces."""
    vertices = []
    uvs = []
    normals = []
    faces = []  # list of (v_idx, vt_idx, vn_idx) triples

    with open(filepath, 'r') as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    # Group by Primitive_ID — each primitive is a triangle (3 vertices)
    # Rows are already in order: every 3 rows = 1 triangle
    seen_verts = {}  # (x, y, z) -> index (1-based for OBJ)
    seen_uvs = {}
    seen_normals = {}

    for i in range(0, len(rows), 3):
        if i + 2 >= len(rows):
            break

        face_v = []
        face_vt = []
        face_vn = []

        for j in range(3):
            row = rows[i + j]

            # World-space position from TEXCOORD1
            x = float(row['TEXCOORD1_C0'])
            y = float(row['TEXCOORD1_C1'])
            z = float(row['TEXCOORD1_C2'])

            # UV from TEXCOORD
            u = float(row['TEXCOORD_C0'])
            v = float(row['TEXCOORD_C1'])

            # Normal from TEXCOORD2
            nx = float(row['TEXCOORD2_C0'])
            ny = float(row['TEXCOORD2_C1'])
            nz = float(row['TEXCOORD2_C2'])

            # Deduplicate vertices
            vkey = (round(x, 6), round(y, 6), round(z, 6))
            if vkey not in seen_verts:
                seen_verts[vkey] = len(vertices) + 1  # OBJ is 1-based
                vertices.append((x, y, z))

            uvkey = (round(u, 6), round(v, 6))
            if uvkey not in seen_uvs:
                seen_uvs[uvkey] = len(uvs) + 1
                uvs.append((u, v))

            nkey = (round(nx, 6), round(ny, 6), round(nz, 6))
            if nkey not in seen_normals:
                seen_normals[nkey] = len(normals) + 1
                normals.append((nx, ny, nz))

            face_v.append(seen_verts[vkey])
            face_vt.append(seen_uvs[uvkey])
            face_vn.append(seen_normals[nkey])

        faces.append((face_v, face_vt, face_vn))

    return vertices, uvs, normals, faces


def write_obj(filepath, parts):
    """Write multiple mesh parts to a single OBJ file with groups."""
    with open(filepath, 'w') as f:
        f.write("# Crimson Desert Dragon - Extracted via PIX GPU Capture\n")
        f.write(f"# Total parts: {len(parts)}\n\n")

        v_offset = 0
        vt_offset = 0
        vn_offset = 0

        for part_name, (vertices, uvs, normals, faces) in parts:
            f.write(f"# Part: {part_name}\n")
            f.write(f"g {part_name}\n")
            f.write(f"o {part_name}\n")

            for x, y, z in vertices:
                f.write(f"v {x:.6f} {y:.6f} {z:.6f}\n")

            for u, v in uvs:
                f.write(f"vt {u:.6f} {v:.6f}\n")

            for nx, ny, nz in normals:
                f.write(f"vn {nx:.6f} {ny:.6f} {nz:.6f}\n")

            for face_v, face_vt, face_vn in faces:
                v1 = face_v[0] + v_offset
                v2 = face_v[1] + v_offset
                v3 = face_v[2] + v_offset
                vt1 = face_vt[0] + vt_offset
                vt2 = face_vt[1] + vt_offset
                vt3 = face_vt[2] + vt_offset
                vn1 = face_vn[0] + vn_offset
                vn2 = face_vn[1] + vn_offset
                vn3 = face_vn[2] + vn_offset
                f.write(f"f {v1}/{vt1}/{vn1} {v2}/{vt2}/{vn2} {v3}/{vt3}/{vn3}\n")

            v_offset += len(vertices)
            vt_offset += len(uvs)
            vn_offset += len(normals)

            f.write("\n")

    total_verts = sum(len(v) for _, (v, _, _, _) in parts)
    total_faces = sum(len(f) for _, (_, _, _, f) in parts)
    print(f"Written: {filepath}")
    print(f"Total vertices: {total_verts}")
    print(f"Total faces: {total_faces}")
    print(f"Parts: {len(parts)}")


def main():
    output_dir = r"C:\Users\waelj\Desktop\Outputs"

    part_names = {
        "7153": "horns_spikes",
        "7154": "neck",
        "7155": "tail_body",
        "7156": "body_legs",
        "7157": "wings",
        "7158": "head",
    }

    csv_files = sorted(glob.glob(os.path.join(output_dir, "*_VS_BufferData_exp0.csv")))

    parts = []
    for csv_file in csv_files:
        basename = os.path.basename(csv_file)
        # Extract GpuId from filename
        gpu_id = None
        for pid in part_names:
            if f"GpuId{pid}" in basename:
                gpu_id = pid
                break

        if gpu_id is None:
            # Unknown part, use filename
            part_name = basename.replace(".csv", "")
        else:
            part_name = part_names[gpu_id]

        print(f"Processing {basename} -> {part_name}...")
        vertices, uvs, normals, faces = parse_csv(csv_file)
        print(f"  Vertices: {len(vertices)}, Faces: {len(faces)}")
        parts.append((part_name, (vertices, uvs, normals, faces)))

    if not parts:
        print("No CSV files found!")
        return

    # Write combined OBJ
    obj_path = os.path.join(output_dir, "crimson_desert_dragon.obj")
    write_obj(obj_path, parts)

    # Also write individual OBJs for each part
    for part_name, data in parts:
        individual_path = os.path.join(output_dir, f"dragon_{part_name}.obj")
        write_obj(individual_path, [(part_name, data)])


if __name__ == "__main__":
    main()
