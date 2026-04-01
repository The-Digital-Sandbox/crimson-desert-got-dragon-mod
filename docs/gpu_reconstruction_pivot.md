# GPU Reconstruction Pivot

## Latest 6804 Position Update

The repo now has a focused late-position tracer:

- [`tools/trace_6804_late_position_probe.py`](../tools/trace_6804_late_position_probe.py)

Outputs:

- [`output/shadow_6804_late_position/report.txt`](../output/shadow_6804_late_position/report.txt)
- [`output/shadow_6804_late_position/manifest.json`](../output/shadow_6804_late_position/manifest.json)
- [`output/shadow_6804_late_position/worst_vertices.csv`](../output/shadow_6804_late_position/worst_vertices.csv)

What it proves:

- the real late shadow position stage is built from `resource_2070`, not the
  earlier `resource_135` matrix stage
- for the proven `6804` shadow-family dragon path, every tested shadow vertex
  has the packed 6-bit factor fixed at `63`
- therefore `%325`, `%404`, `%1526`, `%1585`, and `%2411` are dead across the
  full shadow dragon in this capture
- the traced late TEXCOORD1 path is:
  - runtime local position
  - late matrix from `resource_2070`
  - `space15[64..112]`
  - `cb14[87..90]`

Current exact late-path RMSE vs PIX TEXCOORD1:

- `Body_02`: `0.257503401`
- `back`: `0.128955157`
- `Body`: `0.167162898`
- `Leg`: `0.130319199`
- `Wing`: `0.167838350`
- `Head`: `0.173642674`

A single shared translation delta still removes most of that remaining miss:

- delta = `(-0.010472420, -0.144051618, 0.008831669)`
- corrected RMSE:
  - `Body_02`: `0.140206840`
  - `back`: `0.016071252`
  - `Body`: `0.065889951`
  - `Leg`: `0.014626568`
  - `Wing`: `0.129301550`
  - `Head`: `0.073472465`

Interpretation:

- the old wing-only blocker is gone
- the remaining mismatch is now shared downstream of the late matrix stage
- the next task is not “find another wing branch”; it is “explain the smaller
  shared miss after the exact late matrix path”

## Latest 6804 Sample/Final-Stage Update

New tools:

- [`tools/trace_6804_autos_sample.py`](../tools/trace_6804_autos_sample.py)
- [`tools/fit_6804_effective_world_affine.py`](../tools/fit_6804_effective_world_affine.py)

New outputs:

- [`output/shadow_6804_autos_sample/report.txt`](../output/shadow_6804_autos_sample/report.txt)
- [`output/shadow_6804_autos_sample/manifest.json`](../output/shadow_6804_autos_sample/manifest.json)
- [`output/shadow_6804_effective_affine/report.txt`](../output/shadow_6804_effective_affine/report.txt)
- [`output/shadow_6804_effective_affine/manifest.json`](../output/shadow_6804_effective_affine/manifest.json)
- [`output/shadow_6804_effective_affine/worst_vertices.csv`](../output/shadow_6804_effective_affine/worst_vertices.csv)

What is now explicit:

- the known `Autos.txt` sample on the shadow Wing path is reproduced
  stage-by-stage
- the late `resource_2070` matrix stage is effectively exact
- the sample late-position delta is only:
  - `(-7.87e-06, -2.73e-07, -2.24e-06)`
- the first non-trivial miss appears after that, in the shared downstream
  constant stages
- raw `space15[handle41][78]` translation row `%195..%197` differs from
  `Autos.txt` by about:
  - `+0.011291496`
  - `+0.065002438`
  - `-0.003204302`
- raw `cb14[87..90]` also differs slightly from `Autos.txt`, but by much
  smaller amounts

This means the current residual is best modeled as a late shared
state/provenance mismatch in the `space15/cb14` stage, not another hidden
per-vertex branch.

The new effective downstream fit also gives two practical artifacts:

- shared post-path translation lowers overall RMSE from `0.1685` to `0.0863`
- best-fit affine from `late_pos -> PIX TEXCOORD1` lowers overall RMSE to
  `0.0821`

Operational interpretation:

- the 6804 dragon path is cracked enough to trust through the late matrix stage
- the exact remaining blocker is final shared constant provenance
- if needed, the fitted affine is now a defensible temporary downstream model
  while the exact live `space15/cb14` source is still being pinned down

## Latest Reverse-Target Update

New tool:

- [`tools/generate_drogon_runtime_targets.py`](../tools/generate_drogon_runtime_targets.py)

New outputs:

- [`output/reverse_drogon_runtime_targets/report.txt`](../output/reverse_drogon_runtime_targets/report.txt)
- [`output/reverse_drogon_runtime_targets/manifest.json`](../output/reverse_drogon_runtime_targets/manifest.json)
- [`output/reverse_drogon_runtime_targets/drogon_target_world.obj`](../output/reverse_drogon_runtime_targets/drogon_target_world.obj)
- [`output/reverse_drogon_runtime_targets/drogon_target_runtime_local.obj`](../output/reverse_drogon_runtime_targets/drogon_target_runtime_local.obj)
- [`output/reverse_drogon_runtime_targets/worst_vertices.csv`](../output/reverse_drogon_runtime_targets/worst_vertices.csv)

What this new reverse pass does:

1. loads the proven `6804` shadow-family dragon topology/runtime vertices
2. coarse-aligns [`DROGON.obj`](../gpu-analysis/DROGON.obj) into PIX dragon
   world bounds with axis swizzle:
   - Drogon X -> world X
   - Drogon Z -> -world Y
   - Drogon Y -> world Z
3. uses nearest Drogon vertex in world space as the provisional target
4. inverts the fitted downstream affine
5. inverts the exact per-vertex late matrix to recover desired runtime-local
   coordinates

What is now proven:

- the reverse-side math itself works
- re-forwarding the recovered runtime-local targets through the same
  affine/path lands exactly back on the provisional world target
- therefore the late-matrix inversion stage is not the new blocker

Current quality:

- overall nearest-distance RMSE: `2.988177629`
- overall nearest-distance avg : `2.563371772`
- reforward RMSE              : effectively `0`

Per-submesh nearest RMSE:

- `Body_02`: `2.756090691`
- `back`: `3.163444790`
- `Body`: `2.560444024`
- `Leg`: `1.388749511`
- `Wing`: `4.272619518`
- `Head`: `2.553188148`

Interpretation:

- the reverse contract work is now in place
- the remaining weakness is correspondence/alignment to Drogon, not inversion
- this first pass is vertex-cloud nearest-neighbor only
- it is good enough to generate runtime-local target sets
- it is not yet good enough for confident PAC writeback

Important metric:

- many target local positions fall outside the original per-submesh local bounds
  (for example `Head` and `back` are 100% overflow)
- that does not invalidate the reverse path, but it means any later writeback
  must either:
  - update submesh bbox/storage ranges, or
  - improve correspondence so the target stays closer to the original contract

## Why The Blender Route Failed

The PAC is not a normal skinned mesh container.

- The repo's own diagnosis already says PAC skinned meshes do not store final 3D positions.
- The vertex shader reconstructs positions on the GPU.
- The 8-bit PAC skin codes are not direct bone indices.

That means these workflows are fundamentally wrong as a first step:

- importing `dragon.pac` into Blender as if it were the final rendered mesh
- injecting arbitrary Drogon topology into the PAC vertex buffers
- projecting a fake PAC mesh onto Drogon and expecting stable animation

## What We Know Now

### 1. Draw-local vertex IDs are real

The PIX CSV exports use local draw vertex IDs, not global IDs.

- `GpuId7153`: `0..2012`
- `GpuId7154`: `0..3306`
- `GpuId7155`: `0..2735`
- `GpuId7156`: `0..4623`
- `GpuId7157`: `0..6723`
- `GpuId7158`: `0..10257`

Those ranges exactly match the 8 dragon submesh vertex counts.

### 2. The shader does an address indirection before reading vertex data

From [`gpu-analysis/dragon_vs_shader.txt`](../gpu-analysis/dragon_vs_shader.txt):

- `SV_VertexID` is loaded as `%9`
- a `StructuredBuffer<stride=28>` entry is selected first
- offset `+8` in that record is the base vertex
- the actual vertex record index becomes `baseVertex + SV_VertexID`
- offset `+4` in that record selects which stride-40 vertex buffer to read

Known field map for the 28-byte record:

- `[0]`: render-parameter index into the stride-156 buffer
- `[4]`: stride-40 vertex-buffer handle index
- `[8]`: base vertex for the current draw
- `[12]`: auxiliary packed-offset buffer handle index
- `[16]`: auxiliary packed-offset base index
- `[24]`: flags controlling optional extra per-vertex offset path

### 3. The base dequantization formula is already visible

The shader does:

```text
pos = bboxMin + (uint16_xyz / 32767.0) * bboxDim
```

For the head draw, the shader debugger already captured a plausible bbox:

- `bboxMin = (-0.732201993, 0.851953924, -3.64221001)`
- `bboxDim = (1.52116895, 1.99723601, 3.64221001)`

Using the real stored head base vertex `17118` from the 27,376-vertex PAC layout, dequantized PAC vertices produce sensible local-space head positions instead of garbage. That means the basic quantization step is likely correct.

### 4. There is still more than one reconstruction layer

After the base position is reconstructed, the shader may optionally add a packed 10:10:10 offset from another buffer.

Later, the shader applies skinning using palette resources that are not directly encoded by the raw PAC 8-bit codes.

There is also a likely *pre-VS expansion/remap* stage:

- the PAC on disk only stores `27,376` vertex records
- the shader debugger values line up with a `30,112`-vertex logical layout instead
- the head draw's debugger base vertex `19854` matches the old contiguous 8-submesh layout exactly
- the real stored PAC head base is only `17118`

That strongly suggests the runtime builds or remaps a separate contiguous stride-40 vertex buffer before the draw.

So the full forward path is:

1. draw-local `Vertex_ID`
2. draw record (`stride 28`)
3. runtime-expanded/remapped vertex record (`stride 40`)
4. bbox-based position dequantization
5. optional packed local offset
6. skin/palette indirection
7. final rendered position

## The Correct Reverse-Engineering Order

Do this on one draw only first. Use the head draw `GpuId7158`.

### Stage 1: Reproduce draw addressing

Goal:

- prove that `Vertex_ID n` maps to `baseVertex + n`
- prove which stride-40 record is read for the head draw

Success condition:

- offline tracer reads the same head draw vertex window the shader reads

### Stage 2: Reproduce object-space base positions

Goal:

- decode PAC bytes `0..5` through the bbox formula
- confirm the offline positions form a sensible head in local/model space

Success condition:

- the offline head cloud is coherent and stable

### Stage 3: Reproduce the optional packed offset

Goal:

- identify when the stride-4 packed-offset buffer is active
- decode the 10:10:10 signed offset and add it to the base position

Success condition:

- offline positions get closer to the PIX-captured head before skinning

### Stage 4: Crack skinning indirection

Goal:

- map PAC skin codes to the actual palette/matrix resources the shader uses
- stop assuming the PAC code bytes are direct bone indices

Success condition:

- one draw's offline-skinned positions match PIX world positions closely

### Stage 5: Only then attempt inverse encoding

Goal:

- keep the original CD draw contract intact
- replace only the encoded position inputs with Drogon-derived values

Success condition:

- in-game mesh stays stable because counts, submeshes, indices, weights, and palette contract remain untouched

## Immediate Next Step

Build a single-purpose offline tracer for `GpuId7158` that:

- reads the head draw base vertex and bbox
- decodes PAC head vertex records into object-space positions
- logs the packed-offset path inputs
- compares a handful of vertices against PIX-captured output

Do not go back to Blender export or PAC topology injection until that tracer is working.

## New Traced Facts

The repo now has a generated report at:

- [`output/dragon_pipeline/dragon_pipeline_report.txt`](../output/dragon_pipeline/dragon_pipeline_report.txt)
- [`output/dragon_pipeline/dragon_pipeline_report.json`](../output/dragon_pipeline/dragon_pipeline_report.json)

Those artifacts prove the primary dragon batch is:

- command list `17363`
- compute root signature `357`
- compute PSO `17380`
- `Dispatch(17, 1, 1)`
- graphics root signature `17386`
- graphics PSO `17416`
- `ExecuteIndirect(GetCommandSignature(17480), 155, "7968_7", ...)`

The exact six-submesh dragon sequence inside `7968_7` is at command indices `39..44`:

- const `39` -> `7992`, base vertex `450`
- const `40` -> `17007`, base vertex `2463`
- const `41` -> `13380`, base vertex `5770`
- const `42` -> `22464`, base vertex `8506`
- const `43` -> `34902`, base vertex `13130`
- const `44` -> `51180`, base vertex `19854`

Matching six-draw copies also exist in:

- `7968_33`
- `7968_58`
- `7968_68`

The verified descriptor bindings for the primary batch are:

- graphics `t12,space37` -> descriptor `472620` -> resource `242` -> `StructuredBuffer<stride=156>`
- graphics `t16,space37` -> descriptor `472624` -> resource `7879` -> `StructuredBuffer<stride=28>`
- compute `t59,space37` -> descriptor `472273` -> resource `230` -> raw SRV
- compute `u10,space39` -> descriptor `472299` -> resource `232` -> raw UAV
- compute `u14,space39` -> descriptor `472303` -> resource `7968` -> raw UAV
- compute `u39,space39` -> descriptor `472328` -> resource `7879` -> structured UAV, stride `28`

So the strongest currently supported forward path is:

1. compute pass `17380` updates `7968` and `7879`
2. graphics pass `17416` reads `7879` as the draw record / instance-data buffer
3. graphics pass reads resource `242` as the render-parameter buffer
4. draw-local vertex IDs then step through the six-submesh logical layout

This is why the next unknown to crack is no longer PAC extraction. It is the compute-expanded runtime contract that sits between PAC storage and the vertex shader.

## New Facts From PIX `resources.bin`

The Desktop PIX export (`C:\Users\waelj\Desktop\Outputs\resources.bin`) is now
hooked up directly. Extracted live buffers:

- [`output/pix_resources/resource_242.bin`](../output/pix_resources/resource_242.bin)
- [`output/pix_resources/resource_7879.bin`](../output/pix_resources/resource_7879.bin)
- [`output/pix_resources/resource_7968.bin`](../output/pix_resources/resource_7968.bin)
- [`output/pix_resources/resource_2074.bin`](../output/pix_resources/resource_2074.bin)
- [`output/pix_resources/resource_16288.bin`](../output/pix_resources/resource_16288.bin)
- [`output/pix_resources/resource_15390.bin`](../output/pix_resources/resource_15390.bin)
- [`output/pix_resources/resource_15486.bin`](../output/pix_resources/resource_15486.bin)

The stride-28 record layout in resource `7879` is now confirmed from shader use:

- `[0]` -> index into `t12` / resource `242` (`SkinnedMeshIndirectRenderParameter`)
- `[1]` -> bindless `space103` handle for the stride-40 vertex buffer
- `[2]` -> vertex base added by the shader
- `[3]` -> optional packed-offset buffer handle in `space22`
- `[4]` -> base offset into that optional packed-offset buffer
- `[5]` -> control value used by some passes
- `[6]` -> flags gating the optional packed-offset path

Stable shadow-family records in `7879`:

- `145..150` -> `(115..120, 6804, 450/2463/5770/8506/13130/19854, 0, 0, 1, 0)`
- `296..301` -> identical copy
- `2..7` -> identical geometry, but control field `[5] = 201`

The bindless shadow handle resolves cleanly:

- `space103 handle 6804` -> descriptor `374804`
- descriptor `374804` -> resource `16288`
- first element `46222`
- `30112` elements
- stride `40`

Primary-family handles also resolve:

- `4522` -> descriptor `372522` -> resource `15486`, first element `21258`, count `4202`, stride `40`
- `6773` -> descriptor `374773` -> resource `15486`, first element `0`, count `4164`, stride `40`
- `6774` -> descriptor `374774` -> resource `15390`, first element `94214`, count `437`, stride `40`
- `7696` -> descriptor `375696` -> resource `15390`, first element `14746`, count `428`, stride `40`

Another important dragon-side handle now has a concrete dump:

- `8054` -> descriptor `376054` -> resource `16288`, first element `3168`, count `24117`, stride `40`

The repo now has:

- [`tools/dump_runtime_8054_family.py`](../tools/dump_runtime_8054_family.py)
- [`output/runtime_8054_family/manifest.json`](../output/runtime_8054_family/manifest.json)

This family is not the bird/world-fauna path. It uses the same backing resource
`16288` and the same dragon parameter family `113..120`, but with reduced
submesh counts:

- `Eyeright`: `6`
- `Eyeleft`: `7`
- `Body_02`: `2013`
- `back`: `947`
- `Body`: `2736`
- `Leg`: `4624`
- `Wing`: `6724`
- `Head`: `7060`

That currently looks more like an alternate reduced dragon LOD/view/pass than a
separate armor overlay.

This is the first proof that a real runtime dragon vertex buffer exists outside
PAC storage, and that the shadow-family path uses a single contiguous `30112`
vertex view (`resource 16288`) rather than the raw PAC layout.

The repo now has direct runtime dump scripts:

- [`tools/dump_runtime_shadow_mesh.py`](../tools/dump_runtime_shadow_mesh.py)
- [`tools/dump_runtime_shadow_triangles.py`](../tools/dump_runtime_shadow_triangles.py)

Current outputs:

- [`output/runtime_shadow/body_02_points.obj`](../output/runtime_shadow/body_02_points.obj)
- [`output/runtime_shadow/back_points.obj`](../output/runtime_shadow/back_points.obj)
- [`output/runtime_shadow/body_points.obj`](../output/runtime_shadow/body_points.obj)
- [`output/runtime_shadow/leg_points.obj`](../output/runtime_shadow/leg_points.obj)
- [`output/runtime_shadow/wing_points.obj`](../output/runtime_shadow/wing_points.obj)
- [`output/runtime_shadow/head_points.obj`](../output/runtime_shadow/head_points.obj)
- [`output/runtime_shadow/manifest.json`](../output/runtime_shadow/manifest.json)
- [`output/runtime_shadow_triangles/body_02_triangles.obj`](../output/runtime_shadow_triangles/body_02_triangles.obj)
- [`output/runtime_shadow_triangles/back_triangles.obj`](../output/runtime_shadow_triangles/back_triangles.obj)
- [`output/runtime_shadow_triangles/body_triangles.obj`](../output/runtime_shadow_triangles/body_triangles.obj)
- [`output/runtime_shadow_triangles/leg_triangles.obj`](../output/runtime_shadow_triangles/leg_triangles.obj)
- [`output/runtime_shadow_triangles/wing_triangles.obj`](../output/runtime_shadow_triangles/wing_triangles.obj)
- [`output/runtime_shadow_triangles/head_triangles.obj`](../output/runtime_shadow_triangles/head_triangles.obj)
- [`output/runtime_shadow_triangles/manifest.json`](../output/runtime_shadow_triangles/manifest.json)

The point clouds are still useful for direct vertex debugging. The new triangle
meshes go one step further: they use live indirect records from resource 7968
plus the live index-buffer backing resource 2074.

The shadow-family indirect records now decode cleanly:

- `7968[145]` -> constant `145`, `7992` indices, `startIndex 2496`, `baseVertex 450`
- `7968[146]` -> constant `146`, `17007` indices, `startIndex 10488`, `baseVertex 2463`
- `7968[147]` -> constant `147`, `13380` indices, `startIndex 27495`, `baseVertex 5770`
- `7968[148]` -> constant `148`, `22464` indices, `startIndex 40875`, `baseVertex 8506`
- `7968[149]` -> constant `149`, `34902` indices, `startIndex 63339`, `baseVertex 13130`
- `7968[150]` -> constant `150`, `51180` indices, `startIndex 98241`, `baseVertex 19854`

Those six draws all share one live index-buffer view:

- GPUVA `0x2e070c600`
- size `298842` bytes
- format `DXGI_FORMAT_R16_UINT`

Using the generated `7968_7` template, that GPUVA maps to heap 2073 offset
`7390720`, which is inside live resource 2074. That means the repo now has
real runtime triangle meshes for the shadow-family dragon, not just point
clouds and not PAC-derived guesses.

One critical correction:

- the generated `CreateIndirectArgumentBuffer_7968_7()` data is only the
  pre-compute template
- after compute, the live `resource_7968.bin` records are the truth
- the live primary records `39..44` are now tiny draws, not the old six big
  dragon draws from the static initializer

So future work must prefer live `resource_7968.bin` over the generated
initializer whenever they disagree.

## New Facts From Live Primary Fragments

The repo now also has a direct primary-family dump:

- [`tools/dump_runtime_primary_fragments.py`](../tools/dump_runtime_primary_fragments.py)

Outputs:

- [`output/runtime_primary_fragments/manifest.json`](../output/runtime_primary_fragments/manifest.json)
- [`output/runtime_primary_fragments/primary_39.obj`](../output/runtime_primary_fragments/primary_39.obj)
- [`output/runtime_primary_fragments/primary_40.obj`](../output/runtime_primary_fragments/primary_40.obj)
- [`output/runtime_primary_fragments/primary_41.obj`](../output/runtime_primary_fragments/primary_41.obj)
- [`output/runtime_primary_fragments/primary_42.obj`](../output/runtime_primary_fragments/primary_42.obj)
- [`output/runtime_primary_fragments/primary_43.obj`](../output/runtime_primary_fragments/primary_43.obj)
- [`output/runtime_primary_fragments/primary_44.obj`](../output/runtime_primary_fragments/primary_44.obj)

This reconstructs the live primary records `39..44` from:

- live `7968` indirect records
- live `7879` draw records
- live vertex resources `15390` / `15486`
- live index backing resource `2074`

The result is important:

- `39..44` are genuinely six small live fragments
- they are not a hidden full-dragon six-submesh path
- they are all clustered in a small local box near the origin

Current decoded fragment summaries:

- `39` -> param `262`, handle `7696`, flags `3`, control `1`, `80` verts, `60` tris
- `40` -> param `123`, handle `4522`, flags `2`, control `1`, `162` verts, `161` tris
- `41` -> param `125`, handle `6773`, flags `2`, control `0`, `11` verts, `7` tris
- `42` -> param `131`, handle `6773`, flags `2`, control `0`, `162` verts, `163` tris
- `43` -> param `168`, handle `6774`, flags `3`, control `1`, `3` verts, `1` tri
- `44` -> param `174`, handle `6774`, flags `3`, control `1`, `77` verts, `74` tris

So the primary-family path is now best understood as a different runtime
representation and/or an aux-driven refinement path, not just another copy of
the shadow-family full dragon.

## New Facts From The PAC Shadow Bridge

The repo now has a dedicated PAC/runtime-shadow comparison script:

- [`tools/compare_pac_shadow_runtime.py`](../tools/compare_pac_shadow_runtime.py)

Outputs:

- [`output/pac_shadow_compare/report.txt`](../output/pac_shadow_compare/report.txt)
- [`output/pac_shadow_compare/manifest.json`](../output/pac_shadow_compare/manifest.json)
- [`output/pac_shadow_compare/body_02_pairs.csv`](../output/pac_shadow_compare/body_02_pairs.csv)
- [`output/pac_shadow_compare/back_pairs.csv`](../output/pac_shadow_compare/back_pairs.csv)
- [`output/pac_shadow_compare/body_pairs.csv`](../output/pac_shadow_compare/body_pairs.csv)
- [`output/pac_shadow_compare/leg_pairs.csv`](../output/pac_shadow_compare/leg_pairs.csv)
- [`output/pac_shadow_compare/wing_pairs.csv`](../output/pac_shadow_compare/wing_pairs.csv)
- [`output/pac_shadow_compare/head_pairs.csv`](../output/pac_shadow_compare/head_pairs.csv)

This script proves the strongest PAC/runtime statement in the repo so far:

- PAC bbox == runtime shadow parameter bbox for all six dragon submeshes
- PAC local triangle indices == live runtime shadow triangle indices for all six
- local vertex order can be compared directly by the same local vertex index
- raw PAC packets do not match runtime shadow packets
- raw PAC position bytes do not match runtime shadow position bytes

Per-submesh same-index PAC-vs-runtime position deltas:

- `Body_02`: min `0.0899`, avg `1.5095`, max `3.9902`
- `back`: min `0.0488`, avg `1.4210`, max `3.7842`
- `Body`: min `0.7163`, avg `3.1862`, max `11.0037`
- `Leg`: min `0.3070`, avg `1.4747`, max `3.2397`
- `Wing`: min `0.4886`, avg `4.1635`, max `11.2707`
- `Head`: min `0.0860`, avg `1.4227`, max `5.8205`

Packet-level implications:

- exact 40-byte packet matches: `0` for every submesh
- exact first-8-byte position packet matches: `0` for every submesh
- the only partial carry-over is bytes `24..27` (`extra1_4`), and even that is
  inconsistent across submeshes

So the runtime shadow dragon is now best modeled as:

- the same dragon topology contract as PAC
- but after a separate per-vertex transform/expansion stage
- likely feeding resource `16288`

This means the correct PAC task is no longer "find the right mesh."
It is "find how PAC storage becomes resource 16288."

## New Facts From Head Delta And Visible Code Fits

The repo now also has:

- [`tools/trace_head_pac_shadow_delta.py`](../tools/trace_head_pac_shadow_delta.py)
- [`output/head_pac_shadow_delta/report.txt`](../output/head_pac_shadow_delta/report.txt)
- [`output/head_pac_shadow_delta/manifest.json`](../output/head_pac_shadow_delta/manifest.json)
- [`tools/infer_shadow_code_skinning.py`](../tools/infer_shadow_code_skinning.py)
- [`output/shadow_code_skinning/report.txt`](../output/shadow_code_skinning/report.txt)
- [`output/shadow_code_skinning/manifest.json`](../output/shadow_code_skinning/manifest.json)

These two checks narrow the skinning model materially.

Head-only PAC/runtime delta:

- global affine PAC->runtime fit on head: rmse `0.5837`, max `1.7403`
- top exact visible signature `(8,0,0,0) / (255,0,0,0)`: rmse `0.5442`
- dominant single-weight head code `8`: rmse `0.5501` over `678` verts

That means the head delta is structured and skinning-like, not arbitrary mesh replacement.

Visible-code interpretation test:

- treating visible PAC code bytes as GLOBAL bone ids fails badly
  - global-code weighted prediction: rmse `59.0416`
- treating visible PAC code bytes as SUBMESH-LOCAL / DRAW-LOCAL works much better
  - local-code weighted prediction: rmse `1.7527`

Best local-code regions so far:

- `Head`: rmse `0.5392`
- `back`: rmse `0.8053`
- `Leg`: rmse `0.9199`
- `Body_02`: rmse `0.3203`

This is the strongest current skinning constraint:

- visible PAC code bytes are almost certainly not global bone ids
- they behave more like local palette indices scoped to a draw/submesh family
- the hidden crack is therefore palette indirection, not mesh topology

## New Facts From The Dedicated 6804 Shadow Trace

The repo now also has:

- [`tools/trace_6804_shadow_path.py`](../tools/trace_6804_shadow_path.py)
- [`output/shadow_6804_trace/report.txt`](../output/shadow_6804_trace/report.txt)
- [`output/shadow_6804_trace/manifest.json`](../output/shadow_6804_trace/manifest.json)

This script records the current hard facts for the proven `6804` dragon path.

Shared shadow params from `resource_242[115..120]`:

- `u48 = 11266`
- `u52 = 2716`
- `u60 = 0x80000000`
- `u76 = 0x01120112`
- `u80 = 24`
- `u84 = 0x000A0009`
- `u88 = 0x001F001F`
- `u96 = 0x0029004E`
- `u104 = 2026`
- `u112 = 8`
- `f128 = 0.0`

Resolved descriptor views now pinned down:

- handle `24` -> descriptor `138024` -> resource `147` -> stride `4`
- handle `31` -> descriptor `138031` -> resource `2085` -> stride `4`
- handle `6` -> descriptor `138006` -> resource `122` -> stride `64`
- handle `8` -> descriptor `138008` -> resource `154` -> stride `64`
- handle `9` -> descriptor `138009` -> resource `135` -> stride `64`
- handle `10` -> descriptor `138010` -> resource `2070` -> stride `64`
- handle `41` -> descriptor `138041` -> resource `80` -> stride `272`
- handle `6804` -> descriptor `374804` -> resource `16288` -> first element `46222`, count `30112`, stride `40`

Important live discrepancy from `Autos.txt`:

- shader live `u84` value is `589834` (`0x0009000A`), not the raw `resource_242`
  word `655369` (`0x000A0009`)
- shader live `u112` handle is `6`, not the raw `resource_242` value `8`

So raw `resource_242.bin` is good enough for bbox/base fields, but not yet safe to
trust blindly for every shadow-handle split.

Runtime `16288` packet facts from the same trace:

- the shadow packets carry their own 10-bit influence codes and up to `6` active
  runtime influence slots per vertex
- exact PAC-vs-runtime code equality is effectively absent:
  - `Body_02`: `0 / 2013` exact first-4 matches
  - `back`: `0 / 3307`
  - `Body`: `0 / 2736`
  - `Leg`: `0 / 4624`
  - `Wing`: `0 / 6724`
  - `Head`: `1 / 10258`

Example active-slot histograms:

- `Head`: `{1: 4371, 2: 1247, 3: 596, 4: 527, 5: 549, 6: 2968}`
- `Wing`: `{1: 386, 2: 696, 3: 1325, 4: 1684, 5: 1726, 6: 907}`
- `Leg`: `{1: 580, 2: 1599, 3: 1008, 4: 608, 5: 550, 6: 279}`

Stage-1 sanity check using visible PAC codes directly through the shadow matrix chain:

- handle `9` / resource `135`: overall rmse `4.7556`
- handle `10` / resource `2070`: overall rmse `4.7741`

This matters because it means:

- the first shadow matrix stage is real and partially explanatory
- but visible PAC codes are still not the runtime influence codes stored in `16288`
- the missing crack is now "how PAC codes expand/remap into runtime 10-bit codes"
  plus whatever later shadow-only branch is enabled by `u76`

## New Facts From The 6804 VS Compare

The repo now also has:

- [`tools/trace_6804_vs_compare.py`](../tools/trace_6804_vs_compare.py)
- [`output/shadow_6804_vs_compare/report.txt`](../output/shadow_6804_vs_compare/report.txt)
- [`output/shadow_6804_vs_compare/manifest.json`](../output/shadow_6804_vs_compare/manifest.json)
- [`output/shadow_6804_vs_compare/worst_vertices.csv`](../output/shadow_6804_vs_compare/worst_vertices.csv)

This tracer uses:

- the proven `6804` runtime cache in `resource_16288`
- the runtime 10-bit influence codes stored in those `40`-byte packets
- the resolved shadow lookup chain
  - `resource_147[base0 + code]`
  - `resource_2085[base_lookup + lookup0]`
  - `resource_135[base1 + lookup1]`
- the PIX VS `world_pos` outputs from `GpuId7153..7158`

Shared lookup values used:

- `base0 = 11266`
- `base1 = 2716`
- `u76_lo = 274`
- `base_lookup = 2026`

What it proved:

- raw runtime dequantized local positions are nowhere near PIX world positions
  - per-submesh direct RMSE is about `30..35`
- the first shadow matrix chain using the **runtime 10-bit codes** is the right path
  - direct stage-1-vs-PIX RMSE is still about `29..33`
- but after fitting **one shared affine across the whole dragon**, the stage-1
  predictions match PIX extremely tightly
  - global stage1->PIX affine:

```text
[[ 5.274262770e-01 -1.004070753e-01 -7.602403824e-01]
 [-2.160436760e-02  1.816177921e+00 -8.598418438e-02]
 [ 7.977613789e-01  1.015527724e-01  5.575065230e-01]
 [-7.545094859e+00 -1.378782336e+01  2.739719955e+01]]
```

Per-submesh stage1 + shared-affine RMSE:

- `Body_02`: `0.1230`
- `back`: `0.1444`
- `Body`: `0.2701`
- `Leg`: `0.2331`
- `Wing`: `0.3212`
- `Head`: `0.1217`

Control check:

- the alternate `u76`-shifted bank is worse even after the same style of affine fit
  - e.g. `Wing` rises to `1.3483`
  - e.g. `Head` rises to `0.3573`

This is the strongest 6804 result so far:

- the main handle-9/runtime-code chain is already producing a coherent dragon-space
  transform
- the leftover gap behaves like a **shared post-skin object/world placement step**
  or equivalent shared transform-space mismatch
- the problem is no longer "random hidden per-vertex magic"

So the next best move is no longer Blender or PAC writeback.
The next move is:

1. identify where that shared affine/object placement comes from in the capture
2. compare it against global/instance/cluster transforms available to the VS
3. only after that, circle back to the optional shadow-only branches if needed

## New Facts From The 6804 TEXCOORD1 Exact Tracer

The repo now also has:

- [`tools/trace_6804_texcoord1_path.py`](../tools/trace_6804_texcoord1_path.py)
- [`output/shadow_6804_texcoord1/report.txt`](../output/shadow_6804_texcoord1/report.txt)
- [`output/shadow_6804_texcoord1/manifest.json`](../output/shadow_6804_texcoord1/manifest.json)
- [`output/shadow_6804_texcoord1/worst_vertices.csv`](../output/shadow_6804_texcoord1/worst_vertices.csv)

This tracer formalizes the best current exact `6804` shadow TEXCOORD1 path:

1. dequantize the runtime local position from `resource_16288`
2. decode the runtime `10`-bit influence codes from the same `40`-byte packet
3. resolve lookup chain:
   - `resource_147[base0 + code]`
   - `resource_2085[base_lookup + lookup0]`
4. fetch two matrix banks from `resource_135`
   - `M0 = base_m0 = 2716`
   - `M1 = base_m1 = 2990`
5. blend those banks using the live packed fallback path
   - `blend = 1 - packed_factor`
   - the `d0 > 0` branch never fired on the tested shadow-family vertices
6. apply the live `space15` block from `resource_80[78]` at offsets `64..112`
7. apply `cb14,space35` rows `87..90`
   - important correction: output z uses the `.w` column, not `.z`

Shared values now confirmed in code:

- `base0 = 11266`
- `base_lookup = 2026`
- `base_m0 = 2716`
- `base_m1 = 2990`
- `shift = 274`
- `cluster_idx = 78`
- `flag128 = true`
- `half(0x2C44) = 0.066650390625`

Per-submesh exact-path RMSE:

- `Body_02`: `0.111965008`
- `back`: `0.115964311`
- `Body`: `0.123443556`
- `Leg`: `0.135918122`
- `Wing`: `0.758110781`
- `Head`: `0.113929167`

Overall exact-path error:

- `rmse = 0.376043556`
- `avg  = 0.224546821`
- `max  = 1.868558451`

Branch facts now proved:

- `%157` comes directly from `resource_242[%70].u96`
- `%70` is the wave-broadcast draw parameter index
- so the `space15` element selector is constant per draw, not per-vertex
- the `2411` normalization block is inactive on this proven shadow path
- the active blend source is the packed fallback for all tested shadow-family
  vertices

Wing-specific clue:

- the exact chain is very tight for `Body_02`, `back`, `Body`, `Leg`, and `Head`
- only `Wing` remains a clear outlier
- the residuals are structured, not random
- the worst region clusters in the `local_z > 0` half of the wing submesh
- using `resource_80[78]` offsets `0..48` instead of `64..112` helps wing a bit
  - wing rmse drops from `0.7581` to `0.7054`
- but those same offsets make the other `5` submeshes much worse

So the likely remaining blocker is now narrow:

- not PAC extraction
- not the global `6804` runtime shadow path
- not a whole-dragon transform-space mistake
- but a **wing-only late branch or selector** in the shadow TEXCOORD1 path

That should be the next target before any inverse-encoding attempt.

## New Facts From The 6804 Wing Probe

The repo now also has:

- [`tools/trace_6804_wing_probe.py`](../tools/trace_6804_wing_probe.py)
- [`output/shadow_6804_wing_probe/report.txt`](../output/shadow_6804_wing_probe/report.txt)
- [`output/shadow_6804_wing_probe/manifest.json`](../output/shadow_6804_wing_probe/manifest.json)

This probe turns the remaining wing mismatch into a stable diagnostic instead of
ad hoc shell notes.

What it proves:

1. The miss is genuinely local to the wing.

- exact world-space wing rmse: `0.758110781`
- split by local z:
  - `local_z > 0`: `1.057007644`
  - `local_z <= 0`: `0.370336003`

So the hot region is concentrated in the `local_z > 0` half of the combined wing
submesh.

2. The miss already exists before `cb14`.

The probe inverts the live `cb14` world block and compares the recovered
pre-`cb14` target against the two obvious `resource_80[78]` space15 blocks:

- block `0..48`: rmse `0.563429464`
- block `64..112`: rmse `0.588218540`

That means `cb14` is not the main culprit. The wing discrepancy is upstream of
final world placement.

3. `resource_80` entry `78` is still the correct space15 element.

A brute-force search over every full `272`-byte element in `resource_80` shows:

- base `0`: best candidate is still entry `78`, rmse `0.5634`
- base `64`: best candidate is still entry `78`, rmse `0.5882`
- the next-best candidate in either search is worse than `5.0`

So the remaining problem is **not** a wrong element lookup.

Updated interpretation:

- not PAC extraction
- not the global `6804` path
- not the final `cb14` world block
- not a wrong `resource_80` element
- but a wing-side branch/selector inside the otherwise proven late shadow path

The strongest next suspect is now the unresolved `610 -> 1231` vs `1182 -> 1231`
fork feeding `%1439..%1450`, especially whatever per-vertex factor makes `%644`
non-zero on wing-heavy samples.

## New Facts From Segmented Reverse Targets

The repo now has a stronger reverse-target path:

- [`tools/generate_drogon_runtime_targets_segmented.py`](../tools/generate_drogon_runtime_targets_segmented.py)
- [`output/reverse_drogon_runtime_targets_segmented/report.txt`](../output/reverse_drogon_runtime_targets_segmented/report.txt)
- [`output/reverse_drogon_runtime_targets_segmented/manifest.json`](../output/reverse_drogon_runtime_targets_segmented/manifest.json)

This does **not** change the proven `6804` reverse math. It only changes
correspondence:

- instead of one bbox fit per candidate cloud,
- it uses quantile-segmented bbox fitting on axis `2`,
- with `16` bins,
- then chooses the best candidate per submesh and runs the same exact reverse
  inversion through the late matrix + fitted downstream affine.

New segmented reverse metrics:

- overall nearest rmse: `0.491238006`
- overall nearest avg: `0.354531660`
- overall reforward rmse: effectively `0`

Per-submesh segmented rmse:

- `Body_02`: `0.190505565`
- `back`: `0.262603109`
- `Body`: `0.525888239`
- `Leg`: `0.377119964`
- `Wing`: `0.845426700`
- `Head`: `0.249102413`

Per-submesh bbox overflow after reverse inversion:

- `Body_02`: `2.58%`
- `back`: `0.67%`
- `Body`: `3.55%`
- `Leg`: `7.46%`
- `Wing`: `10.26%`
- `Head`: `0.04%`

That is the first reverse-target set that looks good enough to justify a real
PAC candidate instead of staying in diagnostic-only mode.

## New Facts From Segmented PAC Build

There is now a direct PAC build from those segmented runtime-local targets:

- [`tools/build_segmented_target_pac.py`](../tools/build_segmented_target_pac.py)
- [`output/dragon_drogon_segmented.pac`](../output/dragon_drogon_segmented.pac)
- [`output/dragon_drogon_segmented_report.txt`](../output/dragon_drogon_segmented_report.txt)

What this PAC build does:

- preserves the original dragon PAC topology
- preserves indices, UVs, normals, weights, and non-position fields
- patches only quantized position fields and per-submesh bbox blocks
- leaves `Eyeright` and `Eyeleft` untouched because the reverse set only covers
  the six main shadow-family dragon submeshes

Important build facts:

- output size still matches original exactly: `5,208,284`
- this is **not** GLB injection
- this is **not** the older Blender surface-projection build
- this is the first topology-preserving PAC built from the cracked `6804`
  reverse path itself

Deployment state:

- the segmented PAC was copied to `output/dragon_drogon_final.pac`
- and deployed via [`tools/deploy_new_pac.py`](../tools/deploy_new_pac.py)

Latest deploy facts:

- PAZ append offset: `0x36620200`
- PAMT checksum: `0x12A8F307`
- PAPGT checksum: `0x84909C3A`

So the immediate next question is no longer "can we build a plausible PAC
candidate?" We now can. The next question is the in-game result of that
segmented PAC candidate.

## New Facts From First In-Game Success And Texture Rebake

The segmented PAC candidate now has a real in-game proof:

- the dragon loads
- the silhouette is clearly Drogon-like
- seams between regions are still visible

That means the forward decode and reverse PAC writeback are now good enough to
produce a usable replacement candidate, even if it still needs refinement.

On the texture side, a first manual bake/reskin pass is now also proven:

- [`tools/patch_baked_dragon_textures.py`](../tools/patch_baked_dragon_textures.py)
- [`output/cd_m0004_00_dragon_body_0001.png`](../output/cd_m0004_00_dragon_body_0001.png)
- [`output/cd_m0004_00_dragon_body_0001_n.png`](../output/cd_m0004_00_dragon_body_0001_n.png)
- [`output/cd_m0004_00_dragon_back_0001.png`](../output/cd_m0004_00_dragon_back_0001.png)
- [`output/cd_m0004_00_dragon_back_0001_n.png`](../output/cd_m0004_00_dragon_back_0001_n.png)
- [`output/cd_m0004_00_dragon_head_0001.png`](../output/cd_m0004_00_dragon_head_0001.png)
- [`output/cd_m0004_00_dragon_head_0001_n.png`](../output/cd_m0004_00_dragon_head_0001_n.png)
- [`output/cd_m0004_00_dragon_leg_0001.png`](../output/cd_m0004_00_dragon_leg_0001.png)
- [`output/cd_m0004_00_dragon_leg_0001_n.png`](../output/cd_m0004_00_dragon_leg_0001_n.png)
- [`output/cd_m0004_00_dragon_wing_0001.png`](../output/cd_m0004_00_dragon_wing_0001.png)
- [`output/cd_m0004_00_dragon_wing_0001_n.png`](../output/cd_m0004_00_dragon_wing_0001_n.png)

The DDS patch path works, but the first bake was sparse. That confirms the
current mod is still using the preserved CD UV layout and material contract.
You cannot just substitute the original Drogon DDS files directly, because they
were authored for a different UV layout.

So the correct texture direction from here is:

- rebake Drogon appearance onto the preserved CD UVs, or
- rewrite UV/material layout coherently

Raw Drogon DDS swap is not sufficient on the current working PAC candidate.
