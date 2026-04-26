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

(to be filled in)

## Phase 1 findings

(to be filled in)
