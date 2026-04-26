# Topology-Aware Submesh Assignment — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate submesh boundary seam tears by ensuring no triangle ever crosses a submesh boundary, then simplify `build_submesh_data()` to remove the `extra_verts` hack.

**Architecture:** Replace `assign_submeshes()` with a new `assign_submeshes_topology_aware()` that seeds vertex assignment from CD spatial data, then iteratively migrates vertices so every face's 3 vertices share the same submesh. Remove `extra_verts` logic from `build_submesh_data()`. All other V10 logic (palette-aware hybrid, tangent encoding, LOD patching) is unchanged.

**Tech Stack:** Python 3, NumPy, SciPy (cKDTree), struct

---

## File Map

- **Modify:** `C:\Users\waelj\Downloads\CrimsonForge-446-5-1775146612\build_pac_v10.py`
  - Replace `assign_submeshes()` (lines 414-501) with `assign_submeshes_topology_aware()`
  - Simplify `build_submesh_data()` (lines 732-912) — remove `extra_verts` path
  - Update `main()` call at line 1031 to use new function
- **No new files.** No other files modified.

---

### Task 1: Add `assign_submeshes_topology_aware()` function

**Files:**
- Modify: `C:\Users\waelj\Downloads\CrimsonForge-446-5-1775146612\build_pac_v10.py:414`

This replaces the existing `assign_submeshes()` function. The old function is kept renamed as `assign_submeshes_distance_based()` for rollback.

- [ ] **Step 1: Rename old function and add new function**

Find the existing `assign_submeshes()` at line 414 and rename it to `assign_submeshes_distance_based()`. Then add the new topology-aware function directly after it. Insert this code after the renamed function (after line 501):

```python
def assign_submeshes_topology_aware(game_pos, bboxes, target_counts, faces):
    """Assign vertices to submeshes ensuring NO face crosses a submesh boundary.

    Algorithm:
      Phase 1: Seed each vertex to nearest submesh center (same as distance-based)
      Phase 2: Assign each face to a submesh (majority vote of its 3 vertices)
      Phase 3: Iteratively migrate minority vertices to their face's submesh
               until no cross-boundary faces remain (flood-fill convergence)
      Phase 4: Rebalance counts by moving interior-only vertices
    """
    n = len(game_pos)
    n_sm = len(bboxes)

    # ── Phase 1: Seed assignment (distance to submesh centers) ──
    centers = np.array([
        [bb.min_xyz[0] + bb.dim_xyz[0]/2,
         bb.min_xyz[1] + bb.dim_xyz[1]/2,
         bb.min_xyz[2] + bb.dim_xyz[2]/2]
        for bb in bboxes
    ])
    dists = np.zeros((n, n_sm))
    for si in range(n_sm):
        diff = game_pos - centers[si]
        if SUBMESH_NAMES[si] == 'Wing':
            diff[:, 0] *= 0.3  # wings are wide — reduce lateral penalty
        dists[:, si] = np.sqrt((diff**2).sum(axis=1))

    assignment = np.argmin(dists, axis=1)

    counts = np.bincount(assignment, minlength=n_sm)
    print("\n  Phase 1 — Seed assignment (distance-based):")
    for i in range(n_sm):
        print(f"    {SUBMESH_NAMES[i]:12s}: {counts[i]:>6} (target {target_counts[i]:>6})")

    # ── Build vertex-to-face adjacency ──
    vert_to_faces = defaultdict(list)
    for fi, face in enumerate(faces):
        for vi, ti, ni in face:
            vert_to_faces[vi].append(fi)

    # ── Phase 2: Assign each face to a submesh ──
    face_owner = np.zeros(len(faces), dtype=np.int32)
    for fi, face in enumerate(faces):
        vis = [f[0] for f in face]
        sms = [int(assignment[vi]) for vi in vis]
        if sms[0] == sms[1] == sms[2]:
            face_owner[fi] = sms[0]
        else:
            # Majority vote (2-of-3)
            from collections import Counter
            counts_vote = Counter(sms)
            winner, count = counts_vote.most_common(1)[0]
            if count >= 2:
                face_owner[fi] = winner
            else:
                # All 3 differ — assign to submesh of vertex nearest its CD neighbor
                best_si = sms[np.argmin([dists[vi, sms[k]] for k, vi in enumerate(vis)])]
                face_owner[fi] = best_si

    # Count cross-boundary faces
    def count_cross_boundary():
        cross = 0
        for fi, face in enumerate(faces):
            for vi, ti, ni in face:
                if assignment[vi] != face_owner[fi]:
                    cross += 1
                    break
        return cross

    initial_cross = count_cross_boundary()
    print(f"\n  Phase 2 — Face ownership assigned. Cross-boundary faces: {initial_cross}")

    # ── Phase 3: Flood-fill convergence ──
    MAX_ITERATIONS = 50
    for iteration in range(MAX_ITERATIONS):
        moved = 0
        for fi, face in enumerate(faces):
            target_sm = face_owner[fi]
            for vi, ti, ni in face:
                if assignment[vi] != target_sm:
                    assignment[vi] = target_sm
                    moved += 1

        # After moving vertices, some faces may now have a new majority
        # Re-evaluate face ownership for faces whose vertices changed
        changed_faces = set()
        for fi, face in enumerate(faces):
            vis = [f[0] for f in face]
            sms = [int(assignment[vi]) for vi in vis]
            if not (sms[0] == sms[1] == sms[2]):
                changed_faces.add(fi)

        for fi in changed_faces:
            vis = [f[0] for f in faces[fi]]
            sms = [int(assignment[vi]) for vi in vis]
            from collections import Counter
            counts_vote = Counter(sms)
            winner, _ = counts_vote.most_common(1)[0]
            face_owner[fi] = winner

        cross = count_cross_boundary()
        print(f"    Iteration {iteration + 1}: moved {moved} vertices, {cross} cross-boundary faces remain")

        if cross == 0:
            print(f"  Phase 3 — Converged in {iteration + 1} iterations!")
            break
    else:
        print(f"  Phase 3 — WARNING: {cross} cross-boundary faces remain after {MAX_ITERATIONS} iterations")

    # ── Phase 4: Rebalance to target counts ──
    counts = np.bincount(assignment, minlength=n_sm)
    targets = np.array(target_counts)

    print("\n  Phase 4 — Pre-rebalance counts:")
    for i in range(n_sm):
        diff = counts[i] - targets[i]
        print(f"    {SUBMESH_NAMES[i]:12s}: {counts[i]:>6} (target {targets[i]:>6}, diff {diff:+d})")

    # Identify interior vertices (all incident faces share the same submesh)
    def is_interior(vi):
        sm = int(assignment[vi])
        return all(face_owner[fi] == sm for fi in vert_to_faces[vi])

    # Move interior vertices from oversized to undersized submeshes
    for iteration in range(200):
        counts = np.bincount(assignment, minlength=n_sm)
        over = np.where(counts > targets)[0]
        under = np.where(counts < targets)[0]
        if len(over) == 0 and len(under) == 0:
            break
        moved = 0
        for oi in over:
            excess = counts[oi] - targets[oi]
            if excess <= 0:
                continue
            in_sm = np.where(assignment == oi)[0]
            # Sort by distance from center (farthest first — most movable)
            sorted_by_dist = in_sm[np.argsort(-dists[in_sm, oi])]
            for vi in sorted_by_dist:
                if excess <= 0:
                    break
                if not is_interior(int(vi)):
                    continue  # Skip boundary vertices — moving them creates cross-boundary faces
                # Find nearest undersized submesh
                best_ui, best_dist = None, float('inf')
                for ui in under:
                    if counts[ui] < targets[ui] and dists[vi, ui] < best_dist:
                        best_dist = dists[vi, ui]
                        best_ui = ui
                if best_ui is not None:
                    old_sm = int(assignment[vi])
                    assignment[vi] = best_ui
                    # Update face owners for all incident faces
                    for fi in vert_to_faces[int(vi)]:
                        face_owner[fi] = best_ui
                    counts[oi] -= 1
                    counts[best_ui] += 1
                    excess -= 1
                    moved += 1
        if moved == 0:
            break

    # Final force-fit for any remaining imbalance (pad/truncate handles the rest)
    counts = np.bincount(assignment, minlength=n_sm)
    print("\n  Final assignment:")
    total_diff = 0
    for i in range(n_sm):
        diff = counts[i] - targets[i]
        total_diff += abs(diff)
        print(f"    {SUBMESH_NAMES[i]:12s}: {counts[i]:>6} (target {targets[i]:>6}, diff {diff:+d})")

    if total_diff > 0:
        print(f"\n  NOTE: {total_diff} vertex count mismatch — padding/truncation will handle remainder")

    # Verify zero cross-boundary faces
    final_cross = count_cross_boundary()
    print(f"\n  Cross-boundary faces: {final_cross}")
    if final_cross > 0:
        print(f"  WARNING: {final_cross} cross-boundary faces remain — these will have seam artifacts")

    return assignment, face_owner
```

- [ ] **Step 2: Verify the function is syntactically correct**

Run:
```bash
cd /c/Users/waelj/Downloads/CrimsonForge-446-5-1775146612 && python -c "import ast; ast.parse(open('build_pac_v10.py').read()); print('Syntax OK')"
```
Expected: `Syntax OK`

- [ ] **Step 3: Commit**

```bash
cd /c/Users/waelj/Downloads/CrimsonForge-446-5-1775146612 && git add build_pac_v10.py && git commit -m "feat: add topology-aware submesh assignment function"
```

---

### Task 2: Simplify `build_submesh_data()` — remove `extra_verts`

**Files:**
- Modify: `C:\Users\waelj\Downloads\CrimsonForge-446-5-1775146612\build_pac_v10.py` — `build_submesh_data()` function

The topology-aware assignment guarantees no face crosses a submesh boundary, so `extra_verts` is no longer needed. Simplify the function.

- [ ] **Step 1: Remove `extra_verts` logic from `build_submesh_data()`**

Replace lines 732-758 (the function signature through `full_g2l`) with this simplified version. The function signature changes to accept `face_owner` as a numpy array (from the new assignment function):

```python
def build_submesh_data(game_pos, obj_uvs, obj_normals, obj_faces,
                       bone_weights, assignment, submesh_idx, face_owner,
                       vert_normals_game, vert_tangents, cd_transferred,
                       vb_to_pab=None):
    """Build vertex buffer and index buffer — palette-aware hybrid mode.

    With topology-aware assignment, ALL faces assigned to this submesh have
    ALL their vertices in this submesh. No extra_verts needed.
    """
    sm_name = SUBMESH_NAMES[submesh_idx]
    target_verts = SUBMESH_VERTEX_COUNTS[submesh_idx]

    global_verts = np.where(assignment == submesh_idx)[0]
    g2l = {int(gv): li for li, gv in enumerate(global_verts)}

    # Collect faces owned by this submesh — all vertices guaranteed to be in g2l
    sm_faces = []
    for fi, face in enumerate(obj_faces):
        if face_owner[fi] != submesh_idx:
            continue
        sm_faces.append(face)
```

The rest of the function (from `# Compute submesh bbox` onward at line 760) stays exactly the same, except replace every reference to `full_g2l` with `g2l`:

- Line 761: `sm_positions = game_pos[list(g2l.keys())]` (was `full_g2l`)
- Line 773: `local_verts_sorted = sorted(g2l.items(), key=lambda x: x[1])` (was `full_g2l`)

And in the index buffer section (around line 894), `full_g2l` → `g2l`:
```python
        if valid and len(local_indices) == 3:
```
The `vi in full_g2l` check becomes `vi in g2l`.

- [ ] **Step 2: Verify syntax**

Run:
```bash
cd /c/Users/waelj/Downloads/CrimsonForge-446-5-1775146612 && python -c "import ast; ast.parse(open('build_pac_v10.py').read()); print('Syntax OK')"
```
Expected: `Syntax OK`

- [ ] **Step 3: Commit**

```bash
cd /c/Users/waelj/Downloads/CrimsonForge-446-5-1775146612 && git add build_pac_v10.py && git commit -m "refactor: remove extra_verts from build_submesh_data, trust topology-aware assignment"
```

---

### Task 3: Wire up `main()` to use the new assignment function

**Files:**
- Modify: `C:\Users\waelj\Downloads\CrimsonForge-446-5-1775146612\build_pac_v10.py` — `main()` function

- [ ] **Step 1: Update `main()` to call new assignment and pass face_owner**

Replace lines 1029-1063 (the submesh assignment block + face_owner computation) with:

```python
    # Step 3: Topology-aware submesh assignment
    print("\n[3] Assigning vertices to 8 submeshes (topology-aware)...")
    assignment, face_owner = assign_submeshes_topology_aware(
        game_pos_1x, orig_bboxes, SUBMESH_VERTEX_COUNTS, faces
    )
```

Remove the old face_owner computation block (lines 1057-1063) since `face_owner` is now returned by the assignment function:
```python
    # DELETE THIS BLOCK — face_owner now comes from assign_submeshes_topology_aware
    # face_owner = []
    # for face in faces:
    #     vis = [f[0] for f in face]
    #     sm_counts = defaultdict(int)
    #     for vi in vis:
    #         sm_counts[int(assignment[vi])] += 1
    #     face_owner.append(max(sm_counts, key=sm_counts.get))
```

- [ ] **Step 2: Verify syntax**

Run:
```bash
cd /c/Users/waelj/Downloads/CrimsonForge-446-5-1775146612 && python -c "import ast; ast.parse(open('build_pac_v10.py').read()); print('Syntax OK')"
```
Expected: `Syntax OK`

- [ ] **Step 3: Dry-run the full build (no --deploy)**

Run:
```bash
cd /c/Users/waelj/Downloads/CrimsonForge-446-5-1775146612 && python build_pac_v10.py 2>&1
```

Expected output should show:
- Phase 1-4 logs from the new assignment function
- "Cross-boundary faces: 0" (or very close to 0)
- All 8 submeshes building vertex + index data
- PAC written to `output/drogon_v10.pac`
- No Python errors/tracebacks

- [ ] **Step 4: Commit**

```bash
cd /c/Users/waelj/Downloads/CrimsonForge-446-5-1775146612 && git add build_pac_v10.py && git commit -m "feat: wire topology-aware assignment into main(), remove old face_owner computation"
```

---

### Task 4: Test build and deploy

**Files:**
- No code changes — testing only

- [ ] **Step 1: Run full build and inspect log output**

Run:
```bash
cd /c/Users/waelj/Downloads/CrimsonForge-446-5-1775146612 && python build_pac_v10.py 2>&1 | tee /c/Users/waelj/crimson-desert-got-dragon-mod/output/v10_topology_build_log.txt
```

Check the log for:
1. "Cross-boundary faces: 0" — this is the key success metric
2. Per-submesh vertex counts are within ~5% of targets
3. No traceback or errors
4. PAC file written successfully

- [ ] **Step 2: Deploy to game**

Run:
```bash
cd /c/Users/waelj/Downloads/CrimsonForge-446-5-1775146612 && python build_pac_v10.py --deploy
```

- [ ] **Step 3: Visual inspection in-game**

Launch Crimson Desert and inspect the dragon at all submesh boundaries:
- Neck/head junction
- Wing roots (where wings meet body)
- Leg/body junctions
- Body segment boundaries (Body, Body_02, back)

Compare with V10-base (pre-stitching). Seam tears should be eliminated.

- [ ] **Step 4: Save build log and commit**

```bash
cd /c/Users/waelj/crimson-desert-got-dragon-mod && git add output/v10_topology_build_log.txt && git commit -m "docs: save V10 topology-aware build log"
```
