# Crimson Desert — Dragon Animation Retarget Design

**Date:** 2026-04-26
**Status:** Brainstorm complete, design approved, awaiting implementation plan
**Goal:** Replace the dragon's stiff vanilla flap/idle/fly animations with better clips retargeted from a source FBX (e.g. Fortnite Drogon), keeping CD's vanilla 274-bone skeleton and PAB intact.

## Scope

**In scope (Option A — better anims):**
- Decode CD's animation file format on the dragon
- Build a retarget pipeline: source FBX skeleton → CD's 274-bone palette → encoded CD anim file
- Ship one custom clip end-to-end as proof; everything beyond that is repetition

**Out of scope (deliberately):**
- Replacing or restructuring the skeleton itself (no new bones, no hierarchy changes)
- PAB rotation patches or apply-pose-as-rest (V13–V16 already burned us here)
- Behaviour-graph edits (state machines, transitions, IK setups)
- Ragdoll / physics rig edits
- More than one clip in the proof phase
- Animations on any character other than the dragon

## What we know about CD's animation system

Established 2026-04-26 from inspecting `dragon-extract/character/`:

- **CD uses Havok middleware.** The `.hkx` files in the dragon extract carry magic bytes `TAG0` followed by `SDKV 20240200` — that's Havok's TAGFILE serialization, SDK build 2024-02. Same family of formats as Skyrim / Souls / Elden Ring, but a much newer SDK build than the public 2014 release.
- **Two skeleton artifacts coexist for the dragon:**
  - `cd_m0004_00_dragon.hkx` (505 KB) — Havok-side skeleton, used by Havok's runtime animation system, likely also carries ragdoll/physics
  - `cd_m0004_00_dragon.pab` (89 KB) — CD's cooked skeleton, used by the mesh skinning pass; this is the file we've been position-patching since V11
  - Both must stay structurally consistent. This is the deeper reason rotation-patching the PAB has been so risky — it desyncs the cooked skeleton from the Havok skeleton driving animation.
- **Anim clips are not in the current `dragon-extract` folder.** Only the `_dragon` (skeleton) `.hkx` is there. Clips live in a different PAZ region we haven't extracted yet.

**Tooling caveat.** Skyrim-era Havok modding tools (`hkxcmd`, `hkxconv`) parse the older PackFile format and won't read TAGFILE directly. The Souls / Elden Ring modding scene has tools that handle newer TAGFILE variants (e.g. forks of `HKLib`, `HavokLib`, `SoulsAssetPipeline`); these are the most plausible starting point. If none cover SDK 2024-02 cleanly, we fall back to a small Python TAG0 parser written against the format spec.

## Architecture

Three artifacts, four transformations:

```
[Source FBX with anims]                [Vanilla CD anim clip .hkx]
       │                                          │
       │ (3) retarget onto CD bones               │ (2) decode TAG0 → JSON
       ▼                                          ▼
[Blender CD-skel armature with baked clip] ──► [understand track layout, bone-binding]
       │
       │ (4) encode (Blender clip → TAGFILE matching vanilla layout)
       ▼
[New anim .hkx] ──► JMM override ──► game loads new flap
```

### Components

**1. PAZ extractor for animation archive.** Reuses the existing `extract_cd_dragon.py` family of scripts in `CrimsonForge`. Targets whichever PAZ region holds dragon anim hkx. Outputs raw `.hkx` files into a new `dragon-anim-extract/` folder.

**2. TAG0 decoder.** Parses one anim hkx into a structured representation (Python dict / JSON). Identifies:
- Bone-track binding (by name vs index — determines retarget feasibility)
- Keyframe encoding (raw quat-pos-scale vs compressed/spline)
- Track count and per-track sample rate
- Root motion track (separate or embedded)

**3. TAG0 encoder.** Inverse of decoder. Validated by round-tripping vanilla bytes — encoder output must match decoder input byte-for-byte before it's trusted with edited data.

**4. Retarget pipeline (Blender).** Takes:
- Vanilla CD skeleton armature (already exists in the V11 `.blend`)
- Source FBX with its own skeleton + clip
- Bone-mapping JSON (Fortnite-skel bone → CD-skel bone)

Bakes via Blender's NLA/constraint copy + bake-action workflow. Output: a CD-skel armature with the retargeted clip on a single keyframe-per-frame action.

**5. Blender → TAG0 exporter.** Reads the baked Blender action, walks each CD bone's per-frame transform, and emits a TAGFILE clip whose layout matches the vanilla one we decoded.

**6. JMM mod folder.** Standard pattern from V9/V11 work — drop the new `.hkx` at the right relative path under `mods/Drogon-Anims-V1/`, JMM applies the override at game launch.

### Data flow per clip

1. User runs `extract_dragon_anims.py` once → produces `dragon-anim-extract/<clip_name>.hkx` (× N clips)
2. User runs `decode_clip.py <clip>.hkx` → produces `<clip>.json` (round-trip-validated)
3. User opens Blender, runs `import_cd_skel.py` (already have this in some form) → CD armature in scene
4. User runs `retarget_fbx.py --source fortnite_drogon.fbx --mapping bone_map.json --target_clip <clip_name>` → bakes action onto CD armature
5. User runs `export_clip.py <clip_name>` → produces new `<clip>.hkx` in JMM mod folder
6. User clicks "Apply" in JMM, restarts CD, observes dragon flap

## Phases & kill criteria

The project is staged so each phase has a clear pass/fail signal. If a phase fails its kill test, the next phase doesn't start — we re-design or stop.

### Phase 0 — Locate the anim PAZ (1 session)

Find which PAZ archive holds dragon anim clips. Extract one. Inspect file naming / count.

**Pass:** We have at least one extracted dragon anim `.hkx` on disk, and a believable list of clip names that matches gameplay states (idle, fly, takeoff, hover, attack, etc.).

**Kill if:** Anim data isn't standalone `.hkx` files — e.g. baked into a single behaviour-graph monolith, or driven by procedural systems with no per-clip files. In that case the project pivots to whatever the actual injection unit is, or stops.

### Phase 1 — Override spike (1 session)

Pick one extracted anim. Build a JMM mod that overrides it with (a) a zero-byte file, (b) a clone of a different clip from the same archive. Confirm the dragon visibly behaves differently in-game.

**Pass:** Dragon misbehaves visibly when we replace the file (T-poses, freezes, plays the wrong motion). This means JMM can override anim files and the engine reads our edits.

**Kill if:** Game ignores our override entirely — anims are loaded via a different path JMM doesn't intercept (e.g. memory-resident, signed, or pulled from an unmodded master archive). Different injection mechanism needed; project pauses.

### Phase 2 — Decode one clip (2–3 sessions)

Build a TAG0 parser for one specific clip. Identify track layout, bone binding, keyframe format. Round-trip vanilla bytes through encode → decode → encode and assert byte-exact match against the original file.

**Pass:** Round-trip is byte-exact for at least one vanilla clip.

**Kill if:** Keyframe encoding is opaque (delta-spline, learned compression, proprietary opcode stream) and we can't recover sample values reliably. In that case we either invest much more research time, or pivot to authoring against an external Havok runtime that handles encoding for us.

### Phase 3 — Retarget one Fortnite clip (1–2 sessions)

Hand-author a bone-mapping JSON from Fortnite Drogon skeleton to CD's 274-bone palette. Use Blender's NLA/constraint baking to bake one source clip onto a CD-skel armature.

**Pass:** Blender shows the CD skeleton playing a recognisable version of the source motion, with no obvious bone-mismapping (e.g. wing not driving leg).

**Kill if:** Source skeleton lacks bones that vanilla anims rely on (e.g. CD has fine wing-membrane bones the source rig doesn't have). Mitigation: leave those CD bones at rest pose for the proof clip; revisit after.

### Phase 4 — Encode + ship (1 session)

Run the encoder, deploy the new `.hkx` via JMM, launch the game, trigger the corresponding gameplay state.

**Pass:** Dragon plays the new clip in-game without crashing, T-posing, or visible bone explosions.

**Kill if:** Dragon crashes the game or animates pathologically wrong. Debug from the round-trip pipeline (was the encode actually byte-shape-correct? was the bone binding by name or index?).

## Definition of done

**One** custom anim clip (most likely a flap or idle) plays correctly in-game on the dragon, driven by a `.hkx` we generated from a baked Blender action retargeted from a Fortnite source clip. After this milestone, replacing additional clips is incremental — same pipeline, different source clip.

## Open unknowns

These are deliberately unresolved at design time and will be answered during Phase 0/2:

- **Which PAZ holds dragon anim clips?** Likely a `0009/X.paz` near the mesh PAZ, but unverified.
- **Bone binding by name or index?** Determines whether retargeting is mostly automatic (name-based, ours to manage) or requires exact index alignment with vanilla.
- **Root motion?** Whether flap/fly clips drive translation of the root bone or whether translation is engine-side.
- **TAGFILE 2024-02 parser availability.** Whether Souls-modding-scene tools handle this exact build, or we need to write a parser.
- **Number and naming of dragon clips.** Just `idle/fly/attack`, or a much larger state-machine vocabulary?

## Risks

- **TAGFILE compression is too opaque** — would block Phase 2. Most likely pivot: use Havok's own runtime via a hosted Havok-aware tool to do the encode rather than a from-scratch encoder.
- **Engine integrity-checks anim files** — would block Phase 1. We'd need to find and patch the check, or accept that anim modding isn't possible without runtime injection.
- **PAB and HKX skeletons drift apart on retarget** — even though we're not editing the skeleton, if the encoder produces tracks that reference bone indices not in the cooked PAB, the engine could crash. Mitigation: validate encoded tracks against `cd_skeleton.json` bone list before shipping.
- **Source FBX skeleton missing critical CD bones** — would force partial-clip ships (some bones at rest pose). Acceptable for proof; need to evaluate per-clip later.
- **JMM caching** — burned us before with texture caching. Always confirm JMM is cleared between test cycles.

## Success metric

Time to "one clip plays in-game" measured in sessions, not weeks. Approach 1 was chosen specifically because each phase has a same-day pass/fail signal; if any phase exceeds 3 sessions we stop and re-evaluate rather than grinding.

## Related references

- [crimson_export_pipeline.md](../../../../.claude/projects/C--Users-user/memory/crimson_export_pipeline.md) — PAC build pipeline, coord spaces
- [crimson_session_2026_04_18.md](../../../../.claude/projects/C--Users-user/memory/crimson_session_2026_04_18.md) — V9/JMM workflow, weight-transfer gotchas
- [crimson_v13_wip.md](../../../../.claude/projects/C--Users-user/memory/crimson_v13_wip.md) — V11 as production, why apply-pose-as-rest is dangerous
- [crimson_uv_seam_vb_fix.md](../../../../.claude/projects/C--Users-user/memory/crimson_uv_seam_vb_fix.md) — UV-seam vertex explosion (mesh-side, not directly relevant but same `build_pac_*` family)
