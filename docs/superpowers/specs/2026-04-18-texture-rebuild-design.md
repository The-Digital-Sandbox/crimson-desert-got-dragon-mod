# Drogon Texture Rebuild — Design

**Date:** 2026-04-18
**Status:** Approved by user, ready for implementation plan
**Goal:** Rebuild the Fortnite Drogon texture set on top of the existing v0.3.9 mesh, working back from a v1.0.0 baseline and re-adding improvements one at a time so each change is provably attributable.

---

## Context

- The mesh in v0.3.9 (Fortnite-sourced Drogon retargeted to CD's 227-bone palette) is staying. Only textures change.
- The previous build (v0.3.9) regressed the wing brightness because `Body_d` was multiplied by Fortnite's M.R map as fake AO, crushing wing-membrane pixels to near-black. Diagnosed in this session by decoding the public Drogon.zip wing slot and comparing to the v0.3.9 wing slot — same UV layout, very different brightness.
- v0.3.9 also shipped two genuine improvements over v1.0.0: a PBR mirror-fix on `_sp` (G-inverted smoothness) and a real BC4 displacement on `_disp` matched to per-submesh vanilla stats. We want to keep those wins, just prove them one at a time.
- See `docs/texture_map.md` for the full shader-slot map and how each texture feeds CD's renderer.

## Goals

- Match how Drogon looks in **Fortnite's renderer** (the visual reference is the Fortnite glider as shipped, not HBO Drogon and not "what looks good in CD lighting").
- Bright wing membranes restored to v1.0.0 quality or better.
- No mirror sheen on scales, no muddy overlay, no crystalline displacement shards.
- Each step measurable in-game so any regression is attributable to a single change.

## Non-goals

- No mesh changes (rigging, LODs, head facial bones, wing animation seams — out of scope).
- No new asset sourcing (Hogwarts Legacy / paid Sketchfab Drogon / hand-painted) — we use only the already-extracted Fortnite glider PNGs.
- No saddle/wyvern_armor textures — those live in a separate PAC and are unrelated to dragon-body appearance.
- No detail-tileable repaints in this round (reserved as future work).

---

## Architecture

**Source assets (single set, fixed):**
```
C:/Users/waelj/AppData/Local/FortnitePorting/Assets/BRCosmetics/.../Glider_OutlineLove/Texture/
  ├── T_OutlineLove_Glider_D.png   (diffuse)
  ├── T_OutlineLove_Glider_N.png   (normal — UE convention, G needs inverting)
  ├── T_OutlineLove_Glider_M.png   (ARM packed: A=AO, R=Roughness, M=Metallic? — confirm at step 0)
  ├── T_OutlineLove_Glider_S.png   (specular/material — used for displacement input at step 2)
  └── T_OutlineLove_Glider_FX.png  (effects — unused)
```

**Per-step staging directories** under `got-dragon-mod/textures/drogon_fortnite/`:
```
step0_v1_baseline/        # 4 DDS files
step1_pbr_fix/            # 4 DDS files (only sp differs from step0)
step2_real_disp/          # 4 DDS files (only disp differs from step1)
step3_sharp_normal/       # 4 DDS files (only n differs from step2)
step4_wing_safe_ao/       # 4 DDS files (only d differs from step3) — optional
```

Each step directory contains `Body_d.dds`, `Body_n.dds`, `Body_sp.dds`, `Body_disp.dds`. The `dragon_reskin.py` tool fans these 4 textures into the 23 game slots (5 submeshes × 4 maps + 3 eye textures) and patches the main PAC.

**Snapshot/rollback rule:** before staging a new step, copy the previous step's folder to `stepN_snapshot/` (verbatim duplicate). Any step is a one-click revert via swapping back the snapshot.

**Mask blackening** (`patch_dragon_masks_black.py`) runs **once at step 0** and is not touched again — the blackened mask suppresses CD's detail-tileable scale-pattern overlay across all steps.

## Build process per step

1. Generate the 4 DDS files into `stepN_<name>/` from the Fortnite source PNGs using a small per-step build script (`build_stepN_*.py`). Each script is small and only contains the recipe for that step.
2. Point `dragon_reskin.py` at `stepN_<name>/` (it already takes a source-dir parameter via the `DRAGONS["drogon_fortnite"]["source_dir"]` map).
3. Run `dragon_reskin.py --dragon drogon_fortnite --game-dir "C:/Program Files (x86)/Steam/steamapps/common/Crimson Desert"`.
4. Launch game, capture screenshots (see test protocol).
5. User judges verdict (better/same/worse), I record it in this spec's verdict log.

---

## Step ladder

### Step 0 — v1.0.0 baseline reproduction

**Recipe:**
- `Body_d.dds` — Fortnite D PNG, no AO multiplication, BC1_UNORM 2048×2048, 12 mips
- `Body_n.dds` — Fortnite N PNG with G channel inverted (UE→CD), BC5_UNORM 2048×2048, 12 mips
- `Body_sp.dds` — Fortnite M PNG passed through directly (R/G/B/A as-is), BC1_UNORM 2048×2048, 12 mips
- `Body_disp.dds` — solid black, BC1_UNORM 2048×2048, 12 mips
- Run `patch_dragon_masks_black.py` once

**Expected:** Bright Drogon wings + body matching the public v1.0.0 release. Mirror sheen on scales (known v1.0.0 issue, fixed at step 1). Flat surface (no displacement, fixed at step 2).

**Risk:** none — this is a known-good recipe.

### Step 1 — PBR mirror fix on `_sp`

**Recipe (only `Body_sp.dds` changes from step 0):**
- R = 255 (flat)
- G = 255 - Fortnite_M.G (smoothness — inverted because Fortnite/UE encodes roughness, CD encodes smoothness)
- B = 41 (low metallic — matches CD vanilla `_sp` convention)
- A = 255
- BC1_UNORM 2048×2048, 12 mips

**Expected:** Scales become matte. Wings unchanged (sp doesn't drive base colour).

**Risk:** low — recipe was proven in v0.3.9.

### Step 2 — Real BC4 displacement on `_disp`

**Recipe (only `Body_disp.dds` changes from step 1):**
- Source = Fortnite S.G channel
- Normalize to [0, 1]
- Remap to vanilla body-disp stats: `np.clip(38 + g_norm * 12, 0, 125)` (mean ≈ 38, max ≈ 125)
- Save as L-mode PNG, encode `texconv -f BC4_UNORM -w 2048 -h 2048 -m 12`

**Expected:** Subtle scale micro-relief without crystalline shard explosion. Surface gains depth.

**Risk:** medium. The previous failure mode was using S.G at full [0, 255] range with the shader's `_screenSpaceDisplacementScale=0.49` — produced crystalline shards. We constrain to vanilla stats to avoid that.

### Step 3 — Sharper / cleaner `_n`

**Recipe (only `Body_n.dds` changes from step 2):**
- Source = Fortnite N PNG at native resolution (likely 2048; confirm at build time)
- G channel inverted (UE→CD)
- BC5_UNORM 2048×2048, 12 mips with mip-aware downsample (no nearest-neighbour mip chain — texconv default is fine)

**Expected:** Crisper scale edges and rivet definition. Subtle improvement.

**Risk:** low — recipe is conservative.

### Step 4 — Wing-safe AO bake (optional)

**Only run if step 3 still reads "flat" compared to the Fortnite reference render.**

**Recipe (only `Body_d.dds` changes from step 3):**
- Bake cavity AO from the Fortnite Drogon mesh in Blender (Cycles, ~512 samples, surface only).
- Mask out the wing-membrane UV region (identify wing UV bounds on the Body sheet — likely the two large fan-shaped patches in the middle).
- Multiply onto Fortnite D at gentle strength: `result = D * (0.7 + ao * 0.3)` (so darkest cavity pixels get 70% brightness, wing pixels untouched).
- BC1_UNORM 2048×2048, 12 mips.

**Expected:** Body shading depth without darkening the wing membrane.

**Risk:** medium. The earlier AO bake regression was indiscriminate multiplication across the whole sheet. Wing-mask is the safety net here, but UV-region masking has to be precise.

### Steps 5+ — Reserved future work

Detail-tileable selective unmasking, per-part D variants, per-submesh source variations, etc. Out of scope for this round. Revisit only after step 4 is judged or skipped.

---

## A/B test protocol

**Vantage point:** Pinhol stable area (suggested) — flat ground, midday sun, no obstructions. **User confirms or names a different fixed spot once at step 0; same spot is used for every subsequent step.**

**Per step, 3 screenshots:**
1. **Side profile** — camera level with body, southside. Judges scale colour, wing membrane colour, mirror sheen.
2. **Wing-spread three-quarter** — dragon idle wing-flap pose. Judges wing brightness and translucency.
3. **Head close-up** — face / horns / eyes. Judges scale detail and PBR response.

**File layout:**
```
screenshots/
  step0_v1_baseline/
    side.png
    wing.png
    head.png
  step1_pbr_fix/
    ...
```

**Reference image:**
- One Fortnite render of the Drogon glider in similar lighting, pinned at `docs/references/fortnite_drogon_reference.png`. User obtains from Fortnite locker preview or any clean third-party render. Locked at step 0 and not changed after.

**Per-step verdict (user calls):**
- **Better:** keep, advance to next step.
- **Same:** keep (no regression), advance.
- **Worse:** revert from `step{N-1}_snapshot/`, log the failure mode in the verdict log below, decide whether to skip the step or retry with adjusted params.

**Stop condition:** any step where the user judges the side+wing+head trio "≥ Fortnite reference quality" ends the ladder. Remaining steps become reserved future work.

---

## Verdict log

Filled in as we go. Each entry is one line.

| Step | Date | Verdict | Notes |
|------|------|---------|-------|
| 0 | TBD | TBD | |
| 1 | TBD | TBD | |
| 2 | TBD | TBD | |
| 3 | TBD | TBD | |
| 4 | TBD | TBD | |

---

## Open questions / known unknowns

- Fortnite source resolution: M and N PNGs may be 1024 not 2048. If 1024, BC5 mip 0 will be upscaled, losing some sharpness. Confirm at step 0 build time and note in verdict log.
- Vanilla per-submesh disp stats are different (body 38, head 9, leg 23). Step 2 uses body stats for all 5 slots — head/leg may want their own per-submesh disp variants in a follow-up step. Reserved.
- Step 4 wing-UV masking accuracy. If the AO bake bleeds onto wing pixels even slightly, wings will darken again. May need to pad the mask boundary outward by a few pixels.
