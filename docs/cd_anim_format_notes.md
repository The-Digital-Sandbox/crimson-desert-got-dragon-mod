# CD Dragon Anim Format — Research Notes

Living document for the anim-retarget project. Append findings here as we go;
the Phase 2+ plan will be written against this file's state.

## Confirmed (2026-04-26, design phase)

- Format: Havok TAGFILE, magic `TAG0`, `SDKV20240200` (Havok SDK build 2024-02)
- Dragon skeleton hkx: `dragon-extract/character/cd_m0004_00_dragon.hkx` (505,220 bytes)
- Dragon cooked skeleton: `dragon-extract/character/cd_m0004_00_dragon.pab` (88,950 bytes)
- Dragon mesh PAZ: `0009/3.paz` @ offset `0x2DCAD140` (5,208,284 bytes)

## Open

- Which PAZ holds dragon anim clips
- File extension(s) for anim clips (`.hkx` likely, but unverified)
- Naming convention for clips (does filename indicate which gameplay state?)
- Whether anim files are standalone or aggregated into one container
- Whether the override mechanism (JMM) intercepts anim files at all

## Phase 0 findings

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

## Phase 1 findings

(to be filled in)
