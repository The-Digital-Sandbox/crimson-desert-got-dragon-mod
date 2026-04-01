"""
Carrier workflow scene setup for the Crimson Desert dragon swap.

Run inside Blender from a clean scene.

This builds the real CD dragon mesh directly from dragon.pac, in the exact same
space as the CD skeleton, then duplicates it into an editable carrier mesh.

Objects created:
  - CD_Dragon:  armature built from cd_skeleton.json
  - CD_Source:  original CD mesh built from dragon.pac (hidden reference)
  - CD_Carrier: editable duplicate of CD_Source
  - Drogon_Reference: imported reference surface for manual fitting

Workflow:
  1. Edit CD_Carrier only.
  2. Keep CD_Dragon in REST pose while shaping the carrier.
  3. Export with blender_export_carrier_pac.py
"""

from __future__ import annotations

import bpy
import json
import struct
from pathlib import Path
from mathutils import Matrix, Vector


ROOT = Path(r"C:\Users\waelj\crimson-desert-got-dragon-mod")
SKELETON_JSON = ROOT / "output" / "cd_skeleton.json"
PAC_PATH = ROOT / "output" / "dragon.pac"
DROGON_CANDIDATES = [
    ROOT / "output" / "DrogonRigged-correctweights.glb",
    ROOT / "output" / "DrogonRiggedcorrectweights.obj",
    ROOT / "output" / "drogon_rigged.obj",
    Path(r"C:\Users\waelj\Desktop\Outputs\DROGON.OBJ"),
]

SCALE = 4.0
LEAF_BONE_LENGTH = 0.15

ARMATURE_NAME = "CD_Dragon"
SOURCE_NAME = "CD_Source"
CARRIER_NAME = "CD_Carrier"
DROGON_NAME = "Drogon_Reference"

AXIS_SWAP = Matrix((
    (1, 0, 0, 0),
    (0, 0, -1, 0),
    (0, 1, 0, 0),
    (0, 0, 0, 1),
))

VB_START = 0x7BFA
STRIDE = 40
SUBMESH_NAMES = ["Eyeright", "Eyeleft", "Body_02", "back", "Body", "Leg", "Wing", "Head"]
SUBMESH_VERTEX_COUNTS = [225, 225, 2013, 3307, 2736, 4624, 6724, 10258]
SUBMESH_INDEX_COUNTS = [1248, 1248, 7992, 17007, 13380, 22464, 34902, 51180]

SUBMESH_BASES = []
_base = 0
for _vc in SUBMESH_VERTEX_COUNTS:
    SUBMESH_BASES.append(_base)
    _base += _vc
TOTAL_VERTS = _base


def parse_submesh_bboxes(pac: bytes) -> list[tuple[tuple[float, float, float], tuple[float, float, float]]]:
    bboxes = []
    off = 0x0077
    for _ in range(8):
        name_len = pac[off]
        off += 1 + name_len
        mat_len = pac[off]
        off += 1 + mat_len
        off += 3
        floats = struct.unpack_from("<8f", pac, off)
        off += 32
        bbox_min = (floats[2], floats[3], floats[4])
        bbox_dim = (floats[5], floats[6], floats[7])
        bboxes.append((bbox_min, bbox_dim))
        next_cd = pac.find(b"CD_M0004", off)
        off = (next_cd - 1) if (0 < next_cd < 0x0441) else 0x0441
    return bboxes


def parse_bone_palette(pac: bytes, skeleton: list[dict]) -> list[str | None]:
    skel_hash_to_name = {b["hash"]: b["name"] for b in skeleton}
    pal_count = struct.unpack_from("<H", pac, 0x0441)[0]
    palette = []
    for i in range(pal_count):
        h = struct.unpack_from("<I", pac, 0x0443 + i * 4)[0]
        palette.append(skel_hash_to_name.get(h))
    return palette


def dequantize_pos(u16_x: int, u16_y: int, u16_z: int,
                   bbox_min: tuple[float, float, float],
                   bbox_dim: tuple[float, float, float]) -> tuple[float, float, float]:
    x = bbox_min[0] + (u16_x / 32767.0) * bbox_dim[0]
    y = bbox_min[1] + (u16_y / 32767.0) * bbox_dim[1]
    z = bbox_min[2] + (u16_z / 32767.0) * bbox_dim[2]
    return (x, y, z)


def game_to_blender(x: float, y: float, z: float) -> tuple[float, float, float]:
    return (x * SCALE, -z * SCALE, y * SCALE)


def read_pac_mesh(pac: bytes, bboxes, bone_palette):
    positions = []
    bone_groups = []

    for sm_idx in range(8):
        base = SUBMESH_BASES[sm_idx]
        count = SUBMESH_VERTEX_COUNTS[sm_idx]
        bbox_min, bbox_dim = bboxes[sm_idx]

        for j in range(count):
            off = VB_START + (base + j) * STRIDE
            raw = pac[off:off + STRIDE]

            u16_x, u16_y, u16_z = struct.unpack_from("<3H", raw, 0)
            gx, gy, gz = dequantize_pos(u16_x, u16_y, u16_z, bbox_min, bbox_dim)
            positions.append(game_to_blender(gx, gy, gz))

            bi = struct.unpack_from("4B", raw, 12)
            bw = struct.unpack_from("4B", raw, 20)

            groups = {}
            total_w = sum(bw)
            if total_w > 0:
                for k in range(4):
                    if bw[k] <= 0 or bi[k] >= len(bone_palette):
                        continue
                    bone_name = bone_palette[bi[k]]
                    if bone_name is None:
                        continue
                    groups[bone_name] = groups.get(bone_name, 0.0) + (bw[k] / total_w)
            bone_groups.append(groups)

    return positions, bone_groups


def read_pac_indices(pac: bytes) -> list[list[int]]:
    total_indices = sum(SUBMESH_INDEX_COUNTS)
    index_start = len(pac) - total_indices * 2
    all_indices = struct.unpack_from(f"<{total_indices}H", pac, index_start)

    result = []
    pos = 0
    for count in SUBMESH_INDEX_COUNTS:
        result.append(list(all_indices[pos:pos + count]))
        pos += count
    return result


def cleanup_scene() -> None:
    names_to_remove = [ARMATURE_NAME, SOURCE_NAME, CARRIER_NAME, DROGON_NAME, f"{DROGON_NAME}_Rig"]
    for name in names_to_remove:
        obj = bpy.data.objects.get(name)
        if obj is not None:
            bpy.data.objects.remove(obj, do_unlink=True)

    arm = bpy.data.armatures.get(ARMATURE_NAME)
    if arm is not None:
        bpy.data.armatures.remove(arm)

    for name in [SOURCE_NAME, CARRIER_NAME, DROGON_NAME]:
        mesh = bpy.data.meshes.get(name)
        if mesh is not None:
            bpy.data.meshes.remove(mesh)


def get_world_matrices(bones_data: list[dict]) -> list[Matrix]:
    blender_mats = []
    for bone in bones_data:
        m = bone["local_matrix"]
        bm = Matrix((
            (m[0][0], m[1][0], m[2][0], m[3][0] * SCALE),
            (m[0][1], m[1][1], m[2][1], m[3][1] * SCALE),
            (m[0][2], m[1][2], m[2][2], m[3][2] * SCALE),
            (m[0][3], m[1][3], m[2][3], m[3][3]),
        ))
        blender_mats.append(AXIS_SWAP @ bm)
    return blender_mats


def build_armature(bones_data: list[dict]) -> bpy.types.Object:
    n = len(bones_data)
    world_mats = get_world_matrices(bones_data)

    children_of = {}
    for bone in bones_data:
        pid = bone["parent_index"]
        if pid >= 0:
            children_of.setdefault(pid, []).append(bone["index"])

    arm = bpy.data.armatures.new(ARMATURE_NAME)
    arm_obj = bpy.data.objects.new(ARMATURE_NAME, arm)
    bpy.context.collection.objects.link(arm_obj)
    bpy.context.view_layer.objects.active = arm_obj
    arm_obj.select_set(True)

    bpy.ops.object.mode_set(mode="EDIT")
    ebs = {}
    for bone in bones_data:
        idx = bone["index"]
        eb = arm.edit_bones.new(bone["name"])
        head = world_mats[idx].translation.copy()
        eb.head = head
        eb.tail = head + Vector((0, 0.01, 0))
        ebs[idx] = eb

    for bone in bones_data:
        pid = bone["parent_index"]
        if 0 <= pid < n:
            ebs[bone["index"]].parent = ebs[pid]

    for bone in bones_data:
        idx = bone["index"]
        eb = ebs[idx]
        mat = world_mats[idx]

        y_axis = Vector((mat[0][1], mat[1][1], mat[2][1])).normalized()
        z_axis = Vector((mat[0][2], mat[1][2], mat[2][2])).normalized()

        kids = children_of.get(idx, [])
        if kids:
            child_head = world_mats[kids[0]].translation
            direction = child_head - eb.head
            if direction.length > 0.001:
                eb.tail = eb.head + direction.normalized() * direction.length
            else:
                eb.tail = eb.head + y_axis * LEAF_BONE_LENGTH
        else:
            eb.tail = eb.head + (y_axis if y_axis.length > 0.001 else Vector((0, 1, 0))) * LEAF_BONE_LENGTH

        if (eb.tail - eb.head).length < 0.0001:
            eb.tail = eb.head + Vector((0, LEAF_BONE_LENGTH, 0))

        try:
            eb.align_roll(z_axis)
        except Exception:
            pass

    bpy.ops.object.mode_set(mode="OBJECT")
    arm_obj.show_in_front = True
    arm.display_type = "STICK"
    arm.pose_position = "REST"
    return arm_obj


def build_cd_mesh(obj_name: str, pac: bytes, bboxes, bone_palette) -> bpy.types.Object:
    positions, bone_groups = read_pac_mesh(pac, bboxes, bone_palette)
    all_indices = read_pac_indices(pac)

    faces = []
    for sm_idx in range(8):
        base = SUBMESH_BASES[sm_idx]
        sm_indices = all_indices[sm_idx]
        for tri in range(len(sm_indices) // 3):
            i0 = sm_indices[tri * 3] + base
            i1 = sm_indices[tri * 3 + 1] + base
            i2 = sm_indices[tri * 3 + 2] + base
            if i0 < TOTAL_VERTS and i1 < TOTAL_VERTS and i2 < TOTAL_VERTS:
                faces.append((i0, i1, i2))

    mesh = bpy.data.meshes.new(obj_name)
    mesh.from_pydata(positions, [], faces)
    mesh.update()

    obj = bpy.data.objects.new(obj_name, mesh)
    bpy.context.collection.objects.link(obj)

    for sm_idx, sm_name in enumerate(SUBMESH_NAMES):
        vg = obj.vertex_groups.new(name=sm_name)
        base = SUBMESH_BASES[sm_idx]
        count = SUBMESH_VERTEX_COUNTS[sm_idx]
        vg.add(list(range(base, base + count)), 1.0, "REPLACE")

    all_bone_names = set()
    for groups in bone_groups:
        all_bone_names.update(groups.keys())

    bone_vgroups = {}
    for bone_name in sorted(all_bone_names):
        bone_vgroups[bone_name] = obj.vertex_groups.new(name=bone_name)

    for vi, groups in enumerate(bone_groups):
        for bone_name, weight in groups.items():
            if weight > 0.001:
                bone_vgroups[bone_name].add([vi], weight, "REPLACE")

    return obj


def parent_to_armature(mesh_obj: bpy.types.Object, arm_obj: bpy.types.Object) -> None:
    mesh_obj.parent = arm_obj
    mod = mesh_obj.modifiers.new(name="Armature", type="ARMATURE")
    mod.object = arm_obj


def get_world_bbox(obj: bpy.types.Object) -> dict[str, Vector]:
    depsgraph = bpy.context.evaluated_depsgraph_get()
    eval_obj = obj.evaluated_get(depsgraph)
    mesh = eval_obj.data
    verts_world = [obj.matrix_world @ v.co for v in mesh.vertices]
    return {
        "min": Vector((
            min(v.x for v in verts_world),
            min(v.y for v in verts_world),
            min(v.z for v in verts_world),
        )),
        "max": Vector((
            max(v.x for v in verts_world),
            max(v.y for v in verts_world),
            max(v.z for v in verts_world),
        )),
    }


def duplicate_carrier(source_obj: bpy.types.Object) -> bpy.types.Object:
    carrier_obj = source_obj.copy()
    carrier_obj.data = source_obj.data.copy()
    carrier_obj.name = CARRIER_NAME
    carrier_obj.data.name = CARRIER_NAME
    bpy.context.collection.objects.link(carrier_obj)
    return carrier_obj


def find_drogon_path() -> Path | None:
    for path in DROGON_CANDIDATES:
        if path.exists():
            return path
    return None


def import_drogon_reference() -> bpy.types.Object | None:
    path = find_drogon_path()
    if path is None:
        print("  WARNING: no Drogon OBJ found. Import it manually if needed.")
        return None

    before = set(bpy.data.objects.keys())
    suffix = path.suffix.lower()
    if suffix == ".glb":
        bpy.ops.import_scene.gltf(filepath=str(path))
    else:
        bpy.ops.wm.obj_import(filepath=str(path), forward_axis="NEGATIVE_Z", up_axis="Y")

    created_names = sorted(set(bpy.data.objects.keys()) - before)
    if not created_names:
        print("  WARNING: OBJ import created no new objects.")
        return None

    created = [bpy.data.objects[name] for name in created_names]
    mesh_objects = [obj for obj in created if obj.type == "MESH"]
    armature_objects = [obj for obj in created if obj.type == "ARMATURE"]

    if not mesh_objects:
        print("  WARNING: import created no mesh objects.")
        return None

    if len(mesh_objects) > 1:
        bpy.ops.object.select_all(action="DESELECT")
        for obj in mesh_objects:
            obj.select_set(True)
        bpy.context.view_layer.objects.active = mesh_objects[0]
        bpy.ops.object.join()
        mesh_obj = bpy.context.active_object
    else:
        mesh_obj = mesh_objects[0]

    mesh_obj.name = DROGON_NAME
    if mesh_obj.data:
        mesh_obj.data.name = DROGON_NAME

    if armature_objects:
        rig = armature_objects[0]
        rig.name = f"{DROGON_NAME}_Rig"
        rig.hide_set(True)
        rig.hide_select = True

    return mesh_obj


def auto_align_reference(source_obj: bpy.types.Object, drogon_obj: bpy.types.Object) -> None:
    cd_bbox = get_world_bbox(source_obj)
    drogon_bbox = get_world_bbox(drogon_obj)

    cd_span = cd_bbox["max"] - cd_bbox["min"]
    drogon_span = drogon_bbox["max"] - drogon_bbox["min"]

    cd_max_span = max(cd_span.x, cd_span.y, cd_span.z)
    drogon_max_span = max(drogon_span.x, drogon_span.y, drogon_span.z)
    if drogon_max_span < 0.001:
        return

    scale_factor = cd_max_span / drogon_max_span
    drogon_obj.scale = (scale_factor, scale_factor, scale_factor)
    bpy.context.view_layer.objects.active = drogon_obj
    drogon_obj.select_set(True)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    drogon_obj.select_set(False)

    drogon_bbox = get_world_bbox(drogon_obj)
    drogon_center = (drogon_bbox["min"] + drogon_bbox["max"]) / 2
    cd_center = (cd_bbox["min"] + cd_bbox["max"]) / 2
    drogon_obj.location = drogon_obj.location + (cd_center - drogon_center)


def configure_display(arm_obj, source_obj, carrier_obj, drogon_obj) -> None:
    arm_obj.data.pose_position = "REST"
    source_obj.display_type = "WIRE"
    source_obj.hide_select = True
    source_obj.hide_set(True)
    carrier_obj.display_type = "TEXTURED"
    carrier_obj.hide_select = False

    if drogon_obj is not None:
        drogon_obj.display_type = "WIRE"
        drogon_obj.show_in_front = True


def main() -> None:
    print("=" * 60)
    print("  Crimson Desert Carrier Workflow Setup")
    print("=" * 60)

    if bpy.context.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.object.select_all(action="DESELECT")

    with open(str(SKELETON_JSON), "r", encoding="utf-8") as f:
        bones_data = json.load(f)
    pac = PAC_PATH.read_bytes()
    bboxes = parse_submesh_bboxes(pac)
    bone_palette = parse_bone_palette(pac, bones_data)

    cleanup_scene()

    print("\n[1/5] Building CD armature...")
    arm_obj = build_armature(bones_data)

    print("[2/5] Building CD source mesh from PAC...")
    source_obj = build_cd_mesh(SOURCE_NAME, pac, bboxes, bone_palette)
    parent_to_armature(source_obj, arm_obj)

    print("[3/5] Duplicating editable carrier...")
    carrier_obj = duplicate_carrier(source_obj)

    print("[4/5] Parenting carrier to armature...")
    parent_to_armature(carrier_obj, arm_obj)

    print("[5/5] Importing Drogon reference...")
    drogon_obj = import_drogon_reference()
    if drogon_obj is not None:
        auto_align_reference(source_obj, drogon_obj)

    configure_display(arm_obj, source_obj, carrier_obj, drogon_obj)

    bpy.ops.object.select_all(action="DESELECT")
    carrier_obj.select_set(True)
    bpy.context.view_layer.objects.active = carrier_obj

    for area in bpy.context.screen.areas:
        if area.type == "VIEW_3D":
            for region in area.regions:
                if region.type == "WINDOW":
                    with bpy.context.temp_override(area=area, region=region):
                        bpy.ops.view3d.view_all()
                    break
            break

    print("\n" + "=" * 60)
    print("  SETUP COMPLETE")
    print("=" * 60)
    print(f"  Armature: {ARMATURE_NAME}")
    print(f"  Hidden source: {SOURCE_NAME}")
    print(f"  Editable carrier: {CARRIER_NAME}")
    if drogon_obj is not None:
        print(f"  Reference target: {DROGON_NAME}")
    print("")
    print("  Edit CD_Carrier only.")
    print("  Keep CD_Dragon in REST pose while shaping.")
    print("  Export with blender_export_carrier_pac.py")
    print("")
    print("  First proof should be HEAD only, not full body.")
    print("=" * 60)


if __name__ == "__main__":
    main()
