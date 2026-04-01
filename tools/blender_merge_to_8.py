"""
Merge Drogon's 11 materials into 8 submeshes matching the CD Dragon PAC layout.
Run inside Blender with the DrogonRigged-correctweights scene open.

After running:
  - Drogon mesh will have exactly 8 material slots with CD_M0004 names
  - Export as GLB: File > Export > glTF 2.0 (.glb)
    Settings: Selected Only, +Y Up, Include > Armatures+Skinning
    Save to: output/DrogonRigged-correctweights.glb

Material mapping (adjust if needed):
  Eyeright = eyes right half (X > 0)  — split from eyes.Mat
  Eyeleft  = eyes left half (X <= 0)  — split from eyes.Mat
  Body_02  = fins_tail + spikes1      — tail spikes/fins
  back     = fins_neck                — neck/back fins
  Body     = body.001.Mat             — second body material
  Leg      = claws + teeth + tongue + scales_chest1  — extremities
  Wing     = body.Mat                 — main body incl. wings
  Head     = head_horns               — head + horns
"""
import bpy
import bmesh

DROGON_NAME = "Drogon"

# ── Mapping: source material names -> CD submesh name ──
# Each CD submesh gets a list of source materials to merge into it.
# Eyes are special: split by X coordinate.
MERGE_MAP = {
    "CD_M0004_00_Dragon_Eyeright_0001": {"sources": ["eyes.Mat"], "filter": "x_positive"},
    "CD_M0004_00_Dragon_Eyeleft_0001":  {"sources": ["eyes.Mat"], "filter": "x_negative"},
    "CD_M0004_00_Dragon_Body_0001_02":  {"sources": ["fins_tail.Mat", "spikes1.Mat"]},
    "CD_M0004_00_Dragon_back_0001":     {"sources": ["fins_neck.Mat"]},
    "CD_M0004_00_Dragon_Body_0001":     {"sources": ["body.001.Mat", "scales_chest1.Mat"]},
    "CD_M0004_00_Dragon_Leg_0001":      {"sources": ["claws.Mat", "teeth.Mat", "tongue.Mat"]},
    "CD_M0004_00_Dragon_Wing_0001":     {"sources": ["body.Mat"]},
    "CD_M0004_00_Dragon_Head_0001":     {"sources": ["head_horns.Mat"]},
}


def main():
    obj = bpy.data.objects.get(DROGON_NAME)
    if not obj or obj.type != 'MESH':
        print(f"ERROR: '{DROGON_NAME}' mesh not found")
        return

    mesh = obj.data
    world = obj.matrix_world

    # Build reverse map: source material name -> set of face indices
    print("=== Analysing current materials ===")
    src_mat_names = {i: (mat.name if mat else f"None_{i}") for i, mat in enumerate(mesh.materials)}
    src_mat_faces = {}
    for i, mat_name in src_mat_names.items():
        src_mat_faces[mat_name] = set()

    for poly in mesh.polygons:
        mat_name = src_mat_names.get(poly.material_index, "Unknown")
        src_mat_faces[mat_name].add(poly.index)

    for name, faces in src_mat_faces.items():
        print(f"  {name}: {len(faces)} faces")

    # Build face -> new material index mapping
    print("\n=== Merging to 8 CD submeshes ===")
    cd_names = list(MERGE_MAP.keys())
    face_to_new_mat = {}

    for new_idx, cd_name in enumerate(cd_names):
        config = MERGE_MAP[cd_name]
        sources = config["sources"]
        x_filter = config.get("filter")

        count = 0
        for src_name in sources:
            if src_name not in src_mat_faces:
                print(f"  WARNING: source '{src_name}' not found in mesh")
                continue

            for face_idx in src_mat_faces[src_name]:
                poly = mesh.polygons[face_idx]

                if x_filter:
                    # Compute face center X in world space
                    center = world @ poly.center
                    if x_filter == "x_positive" and center.x <= 0:
                        continue
                    if x_filter == "x_negative" and center.x > 0:
                        continue

                face_to_new_mat[face_idx] = new_idx
                count += 1

        print(f"  {new_idx}: {cd_name} <- {count} faces")

    # Check for unassigned faces (shouldn't happen if mapping is complete)
    unassigned = set(range(len(mesh.polygons))) - set(face_to_new_mat.keys())
    if unassigned:
        print(f"\n  WARNING: {len(unassigned)} unassigned faces — assigning to Wing (SM6)")
        for fi in unassigned:
            face_to_new_mat[fi] = 6  # Wing

    # Create new materials
    print("\n=== Creating new material slots ===")

    # Clear existing materials
    mesh.materials.clear()

    # Add 8 new materials in order
    for cd_name in cd_names:
        mat = bpy.data.materials.new(name=cd_name)
        mat.use_nodes = True
        # Give each a distinct colour for visual checking
        bsdf = mat.node_tree.nodes.get("Principled BSDF")
        if bsdf:
            # Simple colour per submesh
            colours = [
                (1, 0, 0, 1),    # Eyeright - red
                (0, 1, 0, 1),    # Eyeleft - green
                (1, 1, 0, 1),    # Body_02 - yellow
                (0, 0, 1, 1),    # back - blue
                (0.5, 0.5, 0.5, 1),  # Body - grey
                (1, 0.5, 0, 1),  # Leg - orange
                (0, 1, 1, 1),    # Wing - cyan
                (1, 0, 1, 1),    # Head - magenta
            ]
            idx = len(mesh.materials)
            if idx < len(colours):
                bsdf.inputs["Base Color"].default_value = colours[idx]
        mesh.materials.append(mat)

    # Assign faces to new materials
    for poly in mesh.polygons:
        new_idx = face_to_new_mat.get(poly.index, 6)  # default to Wing
        poly.material_index = new_idx

    # Verify
    print("\n=== Verification ===")
    counts = [0] * 8
    vert_sets = [set() for _ in range(8)]
    for poly in mesh.polygons:
        counts[poly.material_index] += 1
        for vi in poly.vertices:
            vert_sets[poly.material_index].add(vi)

    for i, cd_name in enumerate(cd_names):
        print(f"  SM{i} {cd_name}: {counts[i]} faces, {len(vert_sets[i])} verts")

    total_faces = sum(counts)
    total_verts = len(set().union(*vert_sets))
    print(f"\n  Total: {total_faces} faces, {total_verts} verts, {len(mesh.materials)} materials")
    print("\n  DONE. Now export as GLB:")
    print("    File > Export > glTF 2.0 (.glb)")
    print("    Selected Only, +Y Up, Armatures+Skinning")
    print("    -> output/DrogonRigged-correctweights.glb")


if __name__ == '__main__':
    main()
