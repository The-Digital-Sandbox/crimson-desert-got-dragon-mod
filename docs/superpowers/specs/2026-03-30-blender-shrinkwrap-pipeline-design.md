# Blender Shrinkwrap Mesh Swap Pipeline

**Date:** 2026-03-30
**Goal:** Replace CD dragon geometry with Drogon's shape using Blender's Shrinkwrap modifier, then export back to PAC format for in-game use.

## Approach

**Topology morph (Option B):** Keep the CD dragon's original vertex topology (30,112 verts, 8 submeshes, index buffer) but project all vertices onto Drogon's surface using Blender's Shrinkwrap modifier. Only vertex positions and normals change — bone indices, bone weights, UVs, and vertex colors are preserved from the original PAC.

## Pipeline Overview

```
[build_armature.py]     → CD armature (274 bones, 4x scale, Z-up)
[dragon_decoded.obj]    → CD bind-pose mesh (30,112 verts, 8 submeshes)
[DROGON.OBJ]            → Drogon mesh (149,229 verts)
         ↓
[blender_setup_scene.py] → Scene with armature + CD mesh + aligned Drogon + Shrinkwrap modifier
         ↓
[Manual adjustment]      → Tweak Drogon position/scale, inspect, apply modifier
         ↓
[blender_export_pac.py]  → Read modified positions, quantize, write PAC
         ↓
[dragon_drogon_blender.pac] → Drop-in replacement for game
```

## Script 1: `blender_setup_scene.py`

**Purpose:** Set up the complete working scene in Blender with live shrinkwrap preview.

### Steps

1. **Create CD armature**
   - Load `output/cd_skeleton.json`
   - Use 1st PAB matrix directly as world transform (no accumulation)
   - Transpose DX row-vector → Blender column-vector
   - Apply 4x scale (BaseCharacterScale) to translations
   - Convert Y-up → Z-up via axis swap matrix
   - 274 bones with correct hierarchy, tail directions, and roll

2. **Import CD bind-pose mesh**
   - Source: `output/dragon_decoded.obj` (from pac_codec.py)
   - This OBJ has 8 named groups matching the submesh names
   - Import with same axis settings as armature (Y-up → Z-up)
   - Apply 4x scale to match armature

3. **Parent CD mesh to armature**
   - Parent with empty vertex groups (geometry association only)
   - Do NOT use automatic weights — the original PAC bone weights are authoritative

4. **Import Drogon mesh**
   - Source: `C:\Users\waelj\Desktop\Outputs\DROGON.OBJ`
   - Drogon is already Z-up (standard OBJ convention)

5. **Auto-align Drogon to CD mesh**
   - Compute bounding boxes of both meshes
   - Determine axis mapping: compare spans (wingspan vs length vs height) to find correct axis correspondence
   - Scale Drogon uniformly to match CD's largest span
   - Translate Drogon center to CD mesh center
   - If axis swap needed (comparing span ratios), apply rotation

6. **Add Shrinkwrap modifier**
   - Target: CD mesh (not Drogon — the CD mesh gets the modifier)
   - Wait — correction: **Shrinkwrap goes on the CD mesh**, targeting Drogon
   - Mode: `NEAREST_SURFACE_POINT`
   - Leave unapplied for live preview while adjusting Drogon's transform

### Output state
- Scene contains: armature (stick display, x-ray), CD mesh (with shrinkwrap modifier), Drogon mesh (wireframe display)
- Moving/scaling Drogon updates the CD mesh preview in real-time

## Manual Step

User adjusts in Blender:
- Fine-tune Drogon position, rotation, and scale
- Check wing tips, tail end, jaw, eye sockets — areas where nearest-surface may map poorly
- Optionally use vertex groups to mask shrinkwrap from sensitive areas (eyes)
- When satisfied: **Apply the Shrinkwrap modifier** to bake final positions

## Script 2: `blender_export_pac.py`

**Purpose:** Read modified vertex positions from Blender and write a valid PAC file.

### Steps

1. **Read modified CD mesh from Blender**
   - Access the mesh data object after shrinkwrap is applied
   - Vertices are in Blender world space (Z-up, 4x scaled)

2. **Reverse coordinate transform**
   - Undo axis swap: Blender Z-up → game Y-up (X→X, Y→Z, Z→-Y)
   - Undo 4x scale: divide positions by 4.0
   - Result: positions in PAC model space

3. **Map vertices to submesh order**
   - Use vertex group names (matching submesh names from OBJ groups) to identify which submesh each vertex belongs to
   - Alternatively: import order preservation — vertices stay in the same order as the original OBJ
   - Validate: each submesh has exactly the expected vertex count

4. **Compute per-submesh bounding boxes**
   - For each submesh, compute min/max of the new positions
   - bbox_min = per-axis minimum
   - bbox_dim = per-axis (max - min), with epsilon floor to avoid division by zero

5. **Quantize positions**
   - Formula: `uint16 = round((pos - bbox_min) / bbox_dim * 32767.0)`
   - Clamp to [0, 65535]
   - Same formula as `pac_codec.py:quantize_pos()`

6. **Recompute normals**
   - Read face normals from Blender's mesh (post-shrinkwrap)
   - Encode as R10G10B10A2 packed uint32
   - Same encoding as `pac_codec.py:encode_normal_r10g10b10a2()`

7. **Assemble PAC file**
   - Start from original `dragon.pac` as template (preserves header, bone palette, index buffer, all non-position data)
   - Overwrite vertex positions (bytes 0-5 per vertex) with new quantized values
   - Overwrite normals (bytes 8-11 per vertex) with recomputed values
   - Overwrite per-submesh bbox floats in descriptor area (using `pac_patcher.py:find_bbox_offsets()`)
   - Preserve: bone indices (12-15), bone weights (20-23), UVs (32-35), vertex colors (28-31), all extra bytes

8. **Write output**
   - Save to `output/dragon_drogon_blender.pac`
   - Print summary: per-submesh bbox changes, vertex position ranges
   - Optional: export preview OBJ for verification

## File Locations

| File | Path |
|------|------|
| Armature script | `tools/build_armature.py` (exists) |
| Setup script | `tools/blender_setup_scene.py` (new) |
| Export script | `tools/blender_export_pac.py` (new) |
| CD skeleton | `output/cd_skeleton.json` |
| CD mesh OBJ | `output/dragon_decoded.obj` |
| Original PAC | `output/dragon.pac` |
| Drogon mesh | `C:\Users\waelj\Desktop\Outputs\DROGON.OBJ` |
| Output PAC | `output/dragon_drogon_blender.pac` |
| PAC codec | `tools/pac_codec.py` (existing, used by export) |
| PAC patcher | `tools/pac_patcher.py` (existing, used by export) |

## PAC Format Reference

### Vertex buffer (40 bytes per vertex)
| Bytes | Content | Action |
|-------|---------|--------|
| 0-5 | Position (3x uint16) | **OVERWRITE** with shrinkwrapped positions |
| 6-7 | W value (uint16) | Preserve |
| 8-11 | Normal (R10G10B10A2) | **RECOMPUTE** from new geometry |
| 12-15 | Bone indices (4x uint8) | Preserve |
| 16-19 | Extra0 | Preserve |
| 20-23 | Bone weights (4x uint8) | Preserve |
| 24-27 | Extra1 | Preserve |
| 28-31 | Vertex color (uint32) | Preserve |
| 32-35 | UV0 (2x uint16) | Preserve |
| 36-39 | UV1/extra (uint32) | Preserve |

### Submesh vertex counts (fixed)
| Submesh | Verts | Indices |
|---------|-------|---------|
| Eyeright | 225 | 1,248 |
| Eyeleft | 225 | 1,248 |
| Body_02 | 2,013 | 7,992 |
| back | 3,307 | 17,007 |
| Body | 2,736 | 13,380 |
| Leg | 4,624 | 22,464 |
| Wing | 6,724 | 34,902 |
| Head | 10,258 | 51,180 |
| **Total** | **30,112** | **149,421** |

### Position quantization
- Encode: `uint16 = round((pos - bbox_min) / bbox_dim * 32767.0)`
- Decode: `pos = bbox_min + (uint16 / 32767.0) * bbox_dim`
- Per-submesh bounding box (bbox_min, bbox_dim stored in descriptor area)

## Constraints

- Vertex count per submesh is fixed — topology is unchanged
- Index buffer is copied verbatim from original PAC
- Bone palette (offset 0x0441) is preserved — same 227 bone hash entries
- Per-vertex bone indices reference the palette — unchanged since topology is preserved
- Only positions and normals are modified
- UVs will stretch over the new shape (texture handling deferred to later phase)

## Risks

- **Shrinkwrap artifacts at extremities:** Wing tips, tail end, and horns may map to wrong parts of Drogon if the meshes aren't well-aligned. Mitigation: manual adjustment before applying modifier.
- **Eye region distortion:** The 225-vertex eye submeshes may collapse if Drogon's eye sockets are in a different location. Mitigation: vertex group masking on shrinkwrap.
- **Bone weight mismatch:** CD's bone weights were painted for CD's shape. After shrinkwrap, vertices may be in positions where the original bone assignment doesn't make anatomical sense. Mitigation: acceptable for initial version — the bones still control the right general regions.
- **Quantization precision:** Per-submesh bbox recomputation may change the precision envelope. Mitigation: same quantization formula as original PAC, validated by pac_codec round-trip test.
