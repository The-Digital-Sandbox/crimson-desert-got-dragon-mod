# Topology-Aware Submesh Assignment — Design Spec

**Date:** 2026-04-05
**Status:** Approved
**Context:** Crimson Desert GoT Dragon Mod — V10 boundary fix

## Problem

V10 (palette-aware hybrid) produces visible seam tears at submesh boundaries. The CD dragon PAC format splits the mesh into 8 submeshes, each with its own bounding box. Vertex positions are quantized as `uint16` relative to the submesh bbox (`pos = bbox_min + (u16/32767) * bbox_dim`).

When a triangle spans two submeshes, V10 handles it by adding "extra" vertices from the neighboring submesh. But these extra vertices get re-quantized against a different bbox, producing slightly different decoded positions. Result: visible gaps at every submesh boundary.

## Key Insight

The CD dragon's original mesh was designed so that **no triangle ever crosses a submesh boundary**. We should enforce that same invariant on Drogon's mesh, rather than trying to make cross-boundary triangles work.

The fix: **assign submeshes at the face level first, then derive vertex assignments from face assignments** — the inverse of V10's current approach (assign vertices, then hope faces don't cross).

## Algorithm

### Phase 1 — Seed Assignment (existing V10 logic, unchanged)

- Build KD-tree from all CD dragon vertices with submesh labels
- For each Drogon vertex, find nearest CD vertex and inherit its submesh
- Use **full target counts** (no 5% reserve)

### Phase 2 — Face-Level Ownership

- For each triangle, check if all 3 vertices share the same submesh
- If unanimous: face is "clean", assigned to that submesh
- If 2-of-3 agree: face assigned to the majority submesh
- If all 3 differ: face assigned to the submesh of the vertex nearest its CD neighbor (smallest KD-tree distance)

### Phase 3 — Vertex Migration (Flood-Fill Convergence)

- For each cross-boundary face, move the minority vertex/vertices to the face's assigned submesh
- Moving a vertex may create NEW cross-boundary faces on that vertex's other triangles
- **Iterate** until zero cross-boundary faces remain, or max 50 iterations
- Track a "frozen" set: vertices moved in the current iteration don't get pulled back in the same iteration (prevents oscillation)
- Log iteration count and remaining cross-boundary faces per iteration for debugging

### Phase 4 — Count Rebalancing

After convergence, vertex counts per submesh may not match targets.

**Oversized submeshes:**
- Identify interior vertices (all incident faces are in the same submesh)
- Sort by distance from submesh center (farthest first = most movable)
- Move to nearest undersized submesh, but ONLY if moving doesn't create cross-boundary faces
- Re-check all incident faces of the moved vertex before committing

**Undersized submeshes:**
- After moving from oversized, if still under target: pad with degenerate duplicate of last vertex (same as V10 padding)

**If exact counts impossible:**
- Accept small mismatch, pad/truncate as V10 does today
- Log warning with per-submesh actual vs target counts

### Phase 5 — Build Submesh Data (simplified V10 core)

- `build_submesh_data()` no longer needs `extra_verts` logic
- Every face is guaranteed to have all 3 vertices in the same submesh
- Quantization is always correct — no cross-bbox vertices
- All other V10 logic (palette-aware hybrid weights, tangent encoding, control data) remains unchanged

## Data Structures

```
# Pre-computed during Phase 2-3
face_owner: np.ndarray[int]       # shape (num_faces,) — submesh index per face
assignment: np.ndarray[int]       # shape (num_verts,) — submesh index per vertex (derived from face_owner)

# For convergence tracking
vert_to_faces: dict[int, list[int]]  # vertex index -> list of face indices (adjacency)
frozen: set[int]                     # vertices that shouldn't be moved back this iteration
```

## What Changes vs Base V10

| Area | V10 Current | New |
|------|------------|-----|
| `assign_submeshes_from_cd()` | Vertex-only + 5% reserve | Replaced by `assign_submeshes_topology_aware()` |
| `build_submesh_data()` | `extra_verts` boundary collection | Remove `extra_verts` entirely |
| `face_owner` computation | By majority vertex (post-hoc) | Explicit Phase 2, drives vertex migration |
| Reserve slots | 5% per submesh (RESERVE_FRACTION) | None |
| Rebalancing | Moves farthest vertices blindly | Moves only interior vertices preserving invariant |

## Edge Cases

1. **Topology islands** (eyes, disconnected pieces) — naturally stay in one submesh, no special handling needed
2. **Long migration chains** — a single triangle spanning head-to-body forces large vertex migration. Log warning if any chain exceeds 20 hops.
3. **Convergence failure** — if cross-boundary faces remain after 50 iterations, log count and accept. These faces will produce the same tears as V10 (no regression). In practice, convergence should happen in <10 iterations for well-connected meshes.
4. **Degenerate triangles** — faces where 2+ vertices map to the same local index after truncation become degenerate (area=0). Harmless.

## Expected Result

Zero seam tears at submesh boundaries. Every face's 3 vertices live in the same submesh, quantized against the same bbox. The mesh should look seamless.

## Files Modified

- `build_pac_v10.py` → new function `assign_submeshes_topology_aware()` replacing `assign_submeshes_from_cd()`
- `build_pac_v10.py` → `build_submesh_data()` simplified (remove `extra_verts` path)
- No other files affected — codec, palette, blender tools all unchanged

## Testing

1. Run V10 with new assignment on Drogon mesh
2. Verify zero cross-boundary faces in log output
3. Verify vertex counts within 1% of targets
4. Deploy to game, inspect all 8 submesh boundaries visually (neck, wing roots, leg joints, body segments)
5. Compare with V10-base (before boundary stitching) — should be strictly better
