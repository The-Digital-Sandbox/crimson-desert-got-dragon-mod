# CD Dragon Anim Format — Research Notes

Living document for the anim-retarget project. Append findings here as we go;
the Phase 2+ plan will be written against this file's state.

## Confirmed (2026-04-26, design phase)

- Format: Havok TAGFILE, magic `TAG0`, `SDKV20240200` (Havok SDK build 2024-02)
- Dragon skeleton hkx: `dragon-extract/character/cd_m0004_00_dragon.hkx` (505,220 bytes)
- Dragon cooked skeleton: `dragon-extract/character/cd_m0004_00_dragon.pab` (88,950 bytes)
- Dragon mesh PAZ: `0009/3.paz` @ offset `0x2DEEB8D0` (5,208,284 bytes)

## Open

- Which PAZ holds dragon anim clips
- File extension(s) for anim clips (`.hkx` likely, but unverified)
- Naming convention for clips (does filename indicate which gameplay state?)
- Whether the override mechanism (JMM) intercepts anim files at all
- `.paa` binary format internals (magic bytes, header layout, keyframe encoding) — full reverse engineer needed
- Whether `.paa_metabin` is required alongside the `.paa` for the engine to load a clip
- Whether `.motionblending` graphs reference clips by name or by some hash

## Phase 0 findings

### PAZ format learned (Task 2)

PAZ files are raw binary blobs with no internal structure — they are opaque without their sibling `0.pamt` index. Each numbered subdirectory (`0009/`, etc.) contains one `0.pamt` alongside its `.paz` files; the PAMT is the sole directory for all PAZ files in that folder and is small enough to load in full.

PAMT binary layout (little-endian):
- `[0:4]` self-CRC of `data[12:]` (PaChecksum, not verified during listing)
- `[4:8]` `paz_count` (u32) — number of PAZ files in this directory
- `[8:16]` 8-byte padding/hash
- PAZ table: `paz_count × (u32 checksum + u32 size)` with a u32 separator between entries (NOT after the last)
- Folder section: u32 size-prefix, then `(u32 parent, u8 slen, name bytes)` entries; parent `0xFFFFFFFF` marks the root folder prefix
- Node section: same `(u32 parent, u8 slen, name bytes)` structure; entries indexed by relative byte offset for cross-reference
- Folder records block: `u32 folder_count + u32 hash + folder_count × 16 bytes`
- File records: 20 bytes each — `u32 node_ref, u32 paz_offset, u32 comp_size, u32 orig_size, u32 flags`; `flags & 0xFF` = paz_index (added to pamt_stem to derive the PAZ filename number, e.g. stem 0 + index 3 → `3.paz`)

To list a specific PAZ, load its sibling `0.pamt`, parse all file records, and filter by `(pamt_stem + paz_index) == target_paz_stem`. No PAZ payload bytes are read.

### PAZ inventory (Task 1)

- Path: `C:\Program Files (x86)\Steam\steamapps\common\Crimson Desert`
- Structure: numbered subdirectories (`0000`–`0036`, 34 dirs, no root-level paz files)
- Count: 174 `.paz` archives across 34 subdirectories
- Total size: 126 GB
- Largest 5:
  1. `0008/0.paz` — 915 MB (959,641,488 bytes)
  2. `0012/3.paz` — 911 MB (955,071,280 bytes)
  3. `0000/21.paz` — 907 MB (951,223,600 bytes)
  4. `0004/0.paz` — 904 MB (948,341,408 bytes)
  5. `0008/1.paz` — 901 MB (944,812,624 bytes)
- Most-populated subdirs: `0015` (53 files), `0009` (37 files), `0000` (34 files)
- Mesh PAZ confirmed location: `C:\Program Files (x86)\Steam\steamapps\common\Crimson Desert\0009\3.paz` — 874 MB (sanity-check PASSED)

### Anim PAZ candidates (Task 3)

- Top PAZ: `0009/20.paz` with 921 scored entries, 74 entries for `cd_dragon_basic` specifically
- Filename pattern observed: names ARE fully descriptive — e.g. `cd_dragon_basic_00_00_air_move_fly_run_f_land_end_00.paa`, `cd_dragon_basic_00_00_nor_move_fly_run_break_00.paa`; state + direction + action encoded in path
- **CRITICAL FINDING: animation clips use `.paa` extension, NOT `.hkx`**. Zero `.hkx` files exist in the anim PAZ. The 45 `.hkx` files in `0009/35.paz` are all skeleton / ragdoll / physics-body assets (e.g. `cd_m0004_00_dragon_ub_00_0001.hkx`, `cd_m0004_00_dragon_tail_00_0001.hkx`) — not per-clip animations.
- Other PAZs with dragon-related content:
  - `0009/35.paz` — 45 `.hkx` skeleton/ragdoll files for m0004 creatures (dragon, wyvern, golemdragon, …)
  - `0009/36.paz` — 96 `.paa` entries, wyvern + rider anims (top score 3 via `fly`+`land`)
  - `0010/0.paz` — 715 `.paa_metabin` actionchart entries; 87 for `cd_dragon_basic` (mirror of 0009/20.paz anims as action-chart sidecars)
  - `0009/0.paz` — 323 `.motionblending` entries (motion-blending graphs; score 2 via `walk`)
- Total candidate clip count (across all PAZs): 2,741 scored entries across 29 PAZs; ~74 primary dragon (`cd_dragon_basic`) `.paa` clips in `0009/20.paz` plus ~87 matching actionchart sidecars in `0010/0.paz`
- `.paa` size range (dragon_basic only): 654 – 149,584 bytes; median ~5 KB — clearly standalone per-clip files, not monoliths
- Scan stats: 174 PAZs scanned, 29 with at least one score ≥ 2 entry; runtime ~2 minutes

**Phase 0 verdict: PROCEED — pivot from `.hkx` to `.paa`**

921 standalone per-clip files exist in `0009/20.paz`, including 74 dragon-specific (`cd_dragon_basic_*.paa`). The original kill criterion fired strictly because the clips are `.paa` not `.hkx`, but the underlying concern — that no per-clip injection units exist — is false. The 45 `.hkx` files found in `0009/35.paz` are skeleton/ragdoll/physics assets, not animation clips. Phase 1 override spike continues on a `.paa` file with no plan changes other than file extension. Phase 2 decode of `.paa` will be a new, harder project (Pearl Abyss proprietary format, no community tooling) — to be brainstormed separately when we get there.

### Pivot from .hkx to .paa (decision 2026-04-26)

The kill criterion as written ("no PAZ has more than 1 dragon `.hkx`") was a proxy for per-clip file existence. That proxy fired, but the underlying premise of the project — that standalone per-clip files exist which we can override — is fully intact: `0009/20.paz` contains 921 scored entries, 74 of them `cd_dragon_basic_*.paa`, clearly one file per animation state.

All future tasks (4–8) operate on `.paa` files instead of `.hkx`. The Havok TAGFILE assumption from the spec is dead for clip data; it remains correct for the skeleton (`cd_m0004_00_dragon.hkx` is genuinely Havok format).

Companion formats also discovered during the scan: `.paa_metabin` (87 dragon-specific entries in `0010/0.paz`, likely action-chart sidecars that accompany each `.paa` clip) and `.motionblending` (323 entries in `0009/0.paz`, motion-blending graphs that stitch clips together at runtime).

## Phase 1 findings

(to be filled in)
