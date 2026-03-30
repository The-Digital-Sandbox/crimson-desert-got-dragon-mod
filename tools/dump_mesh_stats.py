"""Run in Blender to dump mesh stats needed for PAC export planning."""
import bpy

print("=" * 60)
print("  MESH STATS DUMP")
print("=" * 60)

for obj in bpy.data.objects:
    if obj.type == 'MESH':
        mesh = obj.data
        verts = len(mesh.vertices)
        faces = len(mesh.polygons)
        tris = sum(len(p.vertices) - 2 for p in mesh.polygons)
        groups = len(obj.vertex_groups)

        print(f"\n  Object: {obj.name}")
        print(f"  Vertices:      {verts}")
        print(f"  Faces:         {faces}")
        print(f"  Triangles:     {tris}")
        print(f"  Vertex Groups: {groups}")

        # List vertex group names
        if groups > 0 and groups <= 20:
            for vg in obj.vertex_groups:
                print(f"    - {vg.name}")
        elif groups > 20:
            print(f"    (first 10:)")
            for vg in list(obj.vertex_groups)[:10]:
                print(f"    - {vg.name}")
            print(f"    ... and {groups - 10} more")

    elif obj.type == 'ARMATURE':
        bones = len(obj.data.bones)
        print(f"\n  Armature: {obj.name}")
        print(f"  Bones: {bones}")

print("\n" + "=" * 60)
print("  CD Dragon PAC target: 30112 verts, 149421 tris, 8 submeshes")
print("=" * 60)
