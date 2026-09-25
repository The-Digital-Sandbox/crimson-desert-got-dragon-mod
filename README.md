# Crimson Desert mesh modding: reverse engineering the PAC skinned-mesh format

Research and tooling for replacing a skinned character mesh in Crimson Desert (Pearl Abyss),
built while swapping the game's dragon for a different model. The engine's `.pac` mesh
format is undocumented. This repo is the work of working it out from GPU captures and
shader disassembly, and the Python tooling that came out of it.

**No game files are in this repository.** Every asset, capture dump and extracted mesh has
been stripped from the history. The tools expect you to point them at your own copy of
the game.

## What was worked out

- **Skinned PAC meshes do not store 3D positions.** Vertex bytes 0 to 5 are quantised
  coordinates that the vertex shader reconstructs at runtime:
  `pos = bbox_min + (uint16 / 32767) * bbox_dim`, with a separate bounding box per
  submesh held in the PAC descriptor. Found by tracing the draw in PIX and reading the
  DXIL. See [`tools/pac_codec.py`](tools/pac_codec.py).
- **The vertex layout is a fixed 40-byte stride** with per-submesh contiguous ranges.
  Positions, normals, UVs, bone indices and weights all decode from that stride;
  `tools/verify_vertex_layout.py` checks a file against the layout.
- **The shadow pass is a second, simpler skinning path**, which made it the right place
  to validate a rebuilt mesh before the primary pass. The `tools/trace_*` and
  `tools/dump_runtime_*` scripts replay the shader stages on the CPU and compare against
  the capture, stage by stage. [`docs/gpu_reconstruction_pivot.md`](docs/gpu_reconstruction_pivot.md)
  records the residuals.
- **Existing extractors handle static PAM meshes only.** Skinned PACs needed the codec
  above.
- **Asset redirection without touching game files.** [`tools/pamt_patcher_lib.py`](tools/pamt_patcher_lib.py)
  writes modified copies of the PAMT and PAPGT tables into a staging directory so a
  runtime hook can serve replacement files from a new PAZ. Originals are never modified.
- **Things that looked right and were wrong**, kept so nobody repeats them: Blender
  shrinkwrap onto the original topology, GLB injection, texture-only swaps. The
  [handoff note](docs/handoff-2026-03-31.txt) explains why each was the wrong layer.

## Layout

```
tools/            Codec, patchers, Blender export pipeline, runtime tracers (Python)
tools/anim/       PAZ listing and animation extraction (feat-anim-retarget branch)
gpu-analysis/     Capture analysis scripts and the CMake project for the resource dumper
output/           Trace reports and manifests only (numbers, not meshes)
docs/             Design notes, plans, the pivot write-up and the original handoff
```

## Requirements

Python 3, Blender for the `blender_*.py` scripts, and a GPU capture tool
(PIX on Windows was used here) if you want to reproduce the traces. You need your own
installation of the game.

## Branches

- `master`: the codec, patchers and the GPU reconstruction work.
- `feat-anim-retarget`: PAZ listing and animation format notes, phase one of retargeting
  animations onto a replacement skeleton.
- `fix-pamt-scanner`: a PAMT entry scanner from an earlier fix attempt.

## Status

Research project. The codec decodes and re-encodes meshes correctly and a replacement
mesh has loaded in-engine. Full animation retargeting is not finished. Treat every script
as a lab notebook entry rather than a product.

## Licence

MIT. Crimson Desert is the property of Pearl Abyss. Nothing here grants any rights to
game content.
