# Crimson Desert - Game of Thrones Dragon Mod

Full mesh swap mod to replace Crimson Desert's dragon with Game of Thrones' Drogon model, retextured and rerigged.

## Project Structure

```
├── output/              # Converted dragon models, animations, and PAC files
│   ├── dragon.pac       # Main PAC mesh file
│   ├── dragon_drogon_v*.pac  # Drogon variant iterations
│   ├── *.obj            # Exported mesh files (head, body, wings, tail)
│   └── *.blend          # Blender working files
├── gpu-analysis/        # GPU capture data (RenderDoc/Nsight/PIX)
│   ├── DROGON.obj       # GPU-captured post-shader Drogon mesh
│   ├── *.cpp            # GPU resource creation & descriptor dumps
│   ├── *.csv            # Vertex buffer & render instance data
│   └── *.py             # Analysis scripts
├── dragon-extract/      # Extracted dragon data and analysis
├── prefab/              # Game prefab files
│   └── character/bin__/prefab/2_mon/cd_m0004_00_dragon/
├── szkaradek123_scripts/  # Blender PAC/PAM import/export scripts (BDO format)
├── tools/               # Python utilities and conversion scripts
├── docs/                # Plans and specifications
└── rip/                 # Game capture logs
```

## Key Findings

- PAC skinned meshes do NOT store 3D positions — bytes 0-5 are UV-space coords, GPU reconstructs 3D at runtime
- CDPamExtractor works for PAM static meshes only, not PAC
- Pearl Abyss engine "deletes vertices", shifts position reconstruction to GPU shaders
- `meta/0.pathc` is texture cache only — deleting it crashes the game
- Prefab scale changes confirmed working (Taller Kliff mod precedent)

## Texture Reskin

9 GoT/HotD dragon texture variants completed:
- **GoT**: Drogon, Rhaegal, Viserion
- **HotD S2**: Dreamfyre, Moondancer, Seasmoke, Silverwing, Sunfyre, Vermithor

## Status

Active R&D — working on RenderDoc/Nsight GPU capture to extract post-shader 3D mesh, then reverse-encode for full mesh swap.

## Excluded Files

The following large files are excluded from this repo (available locally):
- `resources.bin` (1.4 GB) — GPU resource binary dump
- `render_instances.csv` (113 MB) — render instance data
