"""
Smart Bone Weight Calculator for Drogon
========================================
Run inside Blender AFTER blender_drogon_rig.py has positioned Drogon.

Improvements over basic nearest-bone:
  1. Bone envelope weighting — considers bone length + direction, not just distance
  2. Vertex prefers bones that "face" it (dot product of bone axis vs vertex direction)
  3. Laplacian smoothing — smooths weights across mesh surface to remove seams
  4. Configurable smooth passes and influence count

Can be re-run after repositioning bones without re-importing anything.
"""

import bpy
import math
from mathutils import Vector

# ==================== CONFIGURATION ====================
ARMATURE_NAME = "CD_Dragon"
MESH_NAME = "Drogon"

MAX_INFLUENCES = 4          # Max bones per vertex
FALLOFF_POWER = 2.0         # Distance falloff exponent
DIRECTION_BIAS = 0.3        # 0.0 = pure distance, 1.0 = heavily favor aligned bones
SMOOTH_PASSES = 3           # Laplacian smoothing iterations (0 = off)
SMOOTH_FACTOR = 0.5         # Smoothing strength per pass (0-1)
MIN_WEIGHT = 0.01           # Drop weights below this threshold
# =======================================================


def closest_point_on_segment(p, a, b):
    """Closest point on segment a->b to point p. Returns (point, dist, t)."""
    ab = b - a
    ab_sq = ab.dot(ab)
    if ab_sq < 1e-12:
        return a.copy(), (p - a).length, 0.0
    t = max(0.0, min(1.0, (p - a).dot(ab) / ab_sq))
    closest = a + ab * t
    return closest, (p - closest).length, t


def compute_bone_score(vert_pos, bone_head, bone_tail, bone_length):
    """Score a bone for a vertex — lower is better (like distance but smarter).

    Combines:
    - Perpendicular distance to bone segment
    - Direction alignment: vertices along the bone's axis score better
    - Bone length: longer bones have larger influence radius
    """
    closest, dist, t = closest_point_on_segment(vert_pos, bone_head, bone_tail)

    # Base score = distance
    score = dist

    # Direction bias: reduce score for vertices that are "in line" with the bone
    if DIRECTION_BIAS > 0 and bone_length > 0.001:
        bone_dir = (bone_tail - bone_head).normalized()
        vert_dir = (vert_pos - closest)
        vert_dist = vert_dir.length

        if vert_dist > 0.001:
            vert_dir_n = vert_dir.normalized()
            # How perpendicular is the vertex to the bone axis?
            # Dot=0 means perpendicular (good for nearby bones)
            # We want to slightly favor bones whose axis points toward the vertex
            alignment = abs(bone_dir.dot(vert_dir_n))
            # Vertices perpendicular to bone axis get a bonus
            perp_bonus = 1.0 - alignment  # 1.0 when perpendicular, 0.0 when parallel
            score *= (1.0 - DIRECTION_BIAS * perp_bonus * 0.5)

    # Bone length influence: longer bones naturally influence a wider area
    # Scale effective distance by inverse bone length (so long bones "reach" further)
    if bone_length > 0.01:
        length_factor = max(0.3, min(2.0, 1.0 / (bone_length * 0.5)))
        score *= length_factor

    return max(score, 1e-8)


def build_adjacency(mesh):
    """Build vertex adjacency map from mesh faces."""
    adj = [set() for _ in range(len(mesh.vertices))]

    for poly in mesh.polygons:
        verts = list(poly.vertices)
        n = len(verts)
        for i in range(n):
            v0 = verts[i]
            v1 = verts[(i + 1) % n]
            adj[v0].add(v1)
            adj[v1].add(v0)

    return adj


def main():
    print("=" * 60)
    print("  SMART BONE WEIGHT CALCULATOR")
    print("=" * 60)

    # Validate scene
    arm_obj = bpy.data.objects.get(ARMATURE_NAME)
    mesh_obj = bpy.data.objects.get(MESH_NAME)

    if arm_obj is None:
        print(f"ERROR: Armature '{ARMATURE_NAME}' not found")
        return
    if mesh_obj is None:
        print(f"ERROR: Mesh '{MESH_NAME}' not found")
        return

    mesh = mesh_obj.data
    vert_count = len(mesh.vertices)

    # Collect bone segments
    bone_data = []
    arm_world = arm_obj.matrix_world

    for bone in arm_obj.data.bones:
        head_w = arm_world @ bone.head_local
        tail_w = arm_world @ bone.tail_local
        length = (tail_w - head_w).length
        bone_data.append((bone.name, head_w, tail_w, length))

    bone_count = len(bone_data)
    print(f"\n  Mesh: {vert_count} verts")
    print(f"  Bones: {bone_count}")
    print(f"  Settings: {MAX_INFLUENCES} influences, falloff^{FALLOFF_POWER}, "
          f"direction_bias={DIRECTION_BIAS}, smooth={SMOOTH_PASSES}x{SMOOTH_FACTOR}")

    # --- Phase 1: Clear existing vertex groups ---
    print("\n  Phase 1: Clearing old weights...")
    mesh_obj.vertex_groups.clear()

    # Create fresh vertex groups for all bones
    vgroups = {}
    for bone_name, _, _, _ in bone_data:
        vg = mesh_obj.vertex_groups.new(name=bone_name)
        vgroups[bone_name] = vg

    # --- Phase 2: Compute raw weights ---
    print("  Phase 2: Computing bone distances...")

    mesh_world = mesh_obj.matrix_world
    # weights_per_vert[vi] = {bone_name: weight, ...}
    weights_per_vert = [{} for _ in range(vert_count)]

    progress_step = max(1, vert_count // 20)

    for vi in range(vert_count):
        if vi % progress_step == 0:
            print(f"    {vi * 100 // vert_count}%", end='\r')

        vert_world = mesh_world @ mesh.vertices[vi].co

        # Score every bone
        scores = []
        for bi, (bone_name, head_w, tail_w, length) in enumerate(bone_data):
            score = compute_bone_score(vert_world, head_w, tail_w, length)
            scores.append((score, bone_name))

        # Take best N (lowest score = closest/best)
        scores.sort(key=lambda x: x[0])
        closest = scores[:MAX_INFLUENCES]

        # Convert scores to weights (inverse score)
        epsilon = 1e-6
        raw = []
        for score, bone_name in closest:
            w = 1.0 / ((score + epsilon) ** FALLOFF_POWER)
            raw.append((w, bone_name))

        # Normalize
        total = sum(w for w, _ in raw)
        if total > 0:
            for w, bone_name in raw:
                nw = w / total
                if nw > MIN_WEIGHT:
                    weights_per_vert[vi][bone_name] = nw

    print(f"    100% — done")

    # --- Phase 3: Laplacian smoothing ---
    if SMOOTH_PASSES > 0:
        print(f"  Phase 3: Smoothing weights ({SMOOTH_PASSES} passes)...")

        adj = build_adjacency(mesh)

        for pass_num in range(SMOOTH_PASSES):
            new_weights = [{} for _ in range(vert_count)]

            for vi in range(vert_count):
                current = weights_per_vert[vi]
                neighbors = adj[vi]

                if not neighbors:
                    new_weights[vi] = dict(current)
                    continue

                # Average neighbor weights
                avg = {}
                for ni in neighbors:
                    for bone_name, w in weights_per_vert[ni].items():
                        avg[bone_name] = avg.get(bone_name, 0.0) + w
                for bone_name in avg:
                    avg[bone_name] /= len(neighbors)

                # Blend: (1-factor)*current + factor*average
                blended = {}
                all_bones = set(current.keys()) | set(avg.keys())
                for bone_name in all_bones:
                    cur_w = current.get(bone_name, 0.0)
                    avg_w = avg.get(bone_name, 0.0)
                    bw = (1.0 - SMOOTH_FACTOR) * cur_w + SMOOTH_FACTOR * avg_w
                    if bw > MIN_WEIGHT:
                        blended[bone_name] = bw

                # Keep only top N influences
                if len(blended) > MAX_INFLUENCES:
                    sorted_bones = sorted(blended.items(), key=lambda x: -x[1])
                    blended = dict(sorted_bones[:MAX_INFLUENCES])

                # Re-normalize
                total = sum(blended.values())
                if total > 0:
                    blended = {k: v / total for k, v in blended.items()}

                new_weights[vi] = blended

            weights_per_vert = new_weights
            print(f"    Pass {pass_num + 1}/{SMOOTH_PASSES} done")

    # --- Phase 4: Apply weights to vertex groups ---
    print("  Phase 4: Applying weights...")

    for vi in range(vert_count):
        for bone_name, weight in weights_per_vert[vi].items():
            if bone_name in vgroups:
                vgroups[bone_name].add([vi], weight, 'REPLACE')

    # Stats
    total_assignments = sum(len(w) for w in weights_per_vert)
    avg_influences = total_assignments / max(1, vert_count)
    active_groups = sum(1 for vg in mesh_obj.vertex_groups
                        if any(True for vi in range(vert_count)
                               if vg.name in weights_per_vert[vi]))

    print(f"\n  --- Results ---")
    print(f"  Total weight assignments: {total_assignments}")
    print(f"  Avg influences/vertex:    {avg_influences:.1f}")
    print(f"  Active bone groups:       {active_groups}/{bone_count}")

    print("\n" + "=" * 60)
    print("  WEIGHTS APPLIED")
    print("  Test by selecting armature > Pose Mode > rotate bones")
    print("  Re-run this script anytime after adjusting bone positions")
    print("=" * 60)


if __name__ == '__main__':
    main()
