# Drogon Texture Rebuild Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the Drogon texture set on the existing v0.3.9 mesh by reproducing the v1.0.0 baseline first, then re-adding each v0.3.9 improvement (PBR mirror fix, real BC4 displacement, sharper normal) one at a time with in-game A/B verdict between every step.

**Architecture:** Five small Python build scripts, one per ladder step, emit four DDS files (`Body_d/n/sp/disp.dds`) into per-step staging folders under `got-dragon-mod/textures/drogon_fortnite/stepN_*/`. A new `deploy_step.py` activates a chosen step folder and invokes the existing `dragon_reskin.py` to fan the four textures into the 23 game slots and patch the main PAC. After each deploy the user captures three fixed-vantage in-game screenshots and writes a verdict line into the spec's verdict log. Per-step folders are immutable historical snapshots — rollback = redeploy from the prior step folder.

**Tech Stack:** Python 3.12, Pillow (PNG I/O), NumPy (channel math), `texconv.exe` 2025.10.28.1 (DDS encode), existing `tools/dragon_reskin.py` and `tools/patch_dragon_masks_black.py`, Crimson Desert game build April 2026.

---

## Implementation note on DDS formats

Our build scripts emit "ideal" formats (BC1 for d/sp, BC5 for n, BC4 for disp). `dragon_reskin.py`'s `convert_texture` runs `texconv` on every staged DDS and re-encodes to its own hardcoded targets (DXT1 for d/sp/disp, DXT5 for n) before patching into PAZ. This means the shipped textures will be BC1/DXT5/BC1/BC1 — a one-step quality compromise vs. our intermediate formats.

This is acceptable because (a) v1.0.0 shipped exactly this way with no quality complaints, (b) the channel CONTENT (smoothness in sp.G, height in disp grayscale, normal XY in n.RG) survives the re-encode intact, (c) the spec's "BC4 disp" intent is about content (single height channel) more than the encoding format. If quality issues surface later, a small patch to `dragon_reskin.py` to passthrough format-matching DDS would eliminate the double-encode — reserved as future work.

## File Structure

| Path | Status | Responsibility |
|------|--------|----------------|
| `tools/texture_lib.py` | NEW | Shared constants + texconv wrapper + step-folder helpers |
| `tools/build_step0_v1_baseline.py` | NEW | v1.0.0 baseline recipe |
| `tools/build_step1_pbr_fix.py` | NEW | PBR mirror-fix on `_sp` only |
| `tools/build_step2_real_disp.py` | NEW | BC4 displacement matched to vanilla body stats |
| `tools/build_step3_sharp_normal.py` | NEW | Cleaner BC5 normal at native res |
| `tools/build_step4_wing_safe_ao.py` | NEW (optional) | Wing-masked AO bake on `_d` |
| `tools/deploy_step.py` | NEW | Activate a step folder + run reskin + run mask blackener |
| `got-dragon-mod/textures/drogon_fortnite/stepN_*/` | NEW (5 dirs) | Per-step DDS snapshots |
| `screenshots/stepN_*/{side,wing,head}.png` | NEW | User-captured in-game shots |
| `docs/references/fortnite_drogon_reference.png` | NEW | Fortnite renderer reference image |
| `docs/superpowers/specs/2026-04-18-texture-rebuild-design.md` | UPDATE | Verdict log filled in as we go |
| `tools/dragon_reskin.py` | UNCHANGED | Re-used as the deployer |
| `tools/patch_dragon_masks_black.py` | UNCHANGED | Run once at step 0 |

---

## Task 1: Setup — texture_lib + environment verification

**Files:**
- Create: `tools/texture_lib.py`
- Create: `screenshots/.gitkeep`
- Create: `docs/references/.gitkeep`

- [ ] **Step 1: Create `tools/texture_lib.py`**

```python
"""Shared helpers for the Drogon texture rebuild ladder.

All paths and constants live here. Build scripts import the encoders
and the per-step folder helpers; deploy_step.py imports the activator.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

# ── Environment constants ────────────────────────────────────────────
TEXCONV = Path("C:/Users/user/texconv.exe")
GAME_DIR = Path("C:/Program Files (x86)/Steam/steamapps/common/Crimson Desert")

REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCE_PNG_DIR = Path(
    r"C:\Users\user\AppData\Local\FortnitePorting\Assets\BRCosmetics"
    r"\Gadgets\Assets\VinderTech_GliderChute\Glider_OutlineLove\Texture"
)
STAGING_ROOT = Path(r"C:\Users\user\got-dragon-mod\textures\drogon_fortnite")
ACTIVE_DIR = STAGING_ROOT  # dragon_reskin.py reads from here
SCREENSHOTS_ROOT = REPO_ROOT / "screenshots"

DRAGON_RESKIN = REPO_ROOT / "tools" / "dragon_reskin.py"
MASK_BLACKEN = REPO_ROOT / "tools" / "patch_dragon_masks_black.py"

# ── texconv wrapper ──────────────────────────────────────────────────

def texconv(*args: str) -> None:
    """Run texconv.exe with the given args; raise on failure."""
    cmd = [str(TEXCONV), *args]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"texconv failed (exit {result.returncode}):\n"
            f"  cmd: {' '.join(cmd)}\n"
            f"  stderr: {result.stderr}\n"
            f"  stdout: {result.stdout}"
        )


def _encode(png_path: Path, dds_path: Path, fmt: str, *, srgb: bool = False) -> None:
    """Encode a PNG to a DDS at 2048 with 12 mips in the given BC format."""
    args = ["-ft", "DDS", "-f", fmt, "-w", "2048", "-h", "2048", "-m", "12",
            "-o", str(dds_path.parent), "-y"]
    if srgb:
        args.insert(0, "-srgbi")
    args.append(str(png_path))
    texconv(*args)
    written = dds_path.parent / f"{png_path.stem}.dds"
    if written != dds_path:
        if dds_path.exists():
            dds_path.unlink()
        written.replace(dds_path)


def encode_bc1(png: Path, dds: Path, *, srgb: bool = False) -> None:
    """BC1_UNORM 2048² 12 mips. Use srgb=True for diffuse/colour."""
    _encode(png, dds, "BC1_UNORM", srgb=srgb)


def encode_bc4(png: Path, dds: Path) -> None:
    """BC4_UNORM 2048² 12 mips (single-channel: displacement)."""
    _encode(png, dds, "BC4_UNORM")


def encode_bc5(png: Path, dds: Path) -> None:
    """BC5_UNORM 2048² 12 mips (two-channel: normal XY)."""
    _encode(png, dds, "BC5_UNORM")

# ── Step folder management ───────────────────────────────────────────

def step_dir(step_id: str) -> Path:
    """Return the path to a step's staging folder, creating it if needed."""
    p = STAGING_ROOT / step_id
    p.mkdir(parents=True, exist_ok=True)
    return p


def copy_dds_from(prev_step_id: str, into_dir: Path) -> None:
    """Copy all DDS files from a previous step into `into_dir`."""
    src = STAGING_ROOT / prev_step_id
    if not src.exists():
        raise FileNotFoundError(f"Previous step folder not found: {src}")
    copied = 0
    for f in src.glob("*.dds"):
        shutil.copy2(f, into_dir / f.name)
        copied += 1
    if copied == 0:
        raise RuntimeError(f"No DDS files found in {src}")


def activate(step_id: str) -> None:
    """Copy a step folder's DDS files into the active staging dir."""
    src = STAGING_ROOT / step_id
    if not src.exists():
        raise FileNotFoundError(f"Step folder not found: {src}")
    # Only copy DDS files; never delete unrelated files in ACTIVE_DIR
    for f in ACTIVE_DIR.glob("Body_*.dds"):
        f.unlink()
    for f in src.glob("Body_*.dds"):
        shutil.copy2(f, ACTIVE_DIR / f.name)
```

- [ ] **Step 2: Verify the environment by importing the module and printing key paths**

Run:
```bash
cd /c/Users/user/crimson-desert-got-dragon-mod
python -c "from tools import texture_lib as t; print('texconv:', t.TEXCONV.exists()); print('source png dir:', t.SOURCE_PNG_DIR.exists()); print('staging:', t.STAGING_ROOT.exists()); print('reskin:', t.DRAGON_RESKIN.exists()); print('mask blackener:', t.MASK_BLACKEN.exists())"
```

Expected output:
```
texconv: True
source png dir: True
staging: True
reskin: True
mask blackener: True
```

If any line says `False`, stop and fix the path in `texture_lib.py` before continuing.

- [ ] **Step 3: Verify Pillow + NumPy are installed**

Run:
```bash
python -c "import PIL, numpy; print('PIL', PIL.__version__, 'numpy', numpy.__version__)"
```

Expected: prints versions, no `ModuleNotFoundError`. If missing: `pip install pillow numpy`.

- [ ] **Step 4: Create empty placeholder dirs for screenshots and references**

Run:
```bash
mkdir -p /c/Users/user/crimson-desert-got-dragon-mod/screenshots
mkdir -p /c/Users/user/crimson-desert-got-dragon-mod/docs/references
touch /c/Users/user/crimson-desert-got-dragon-mod/screenshots/.gitkeep
touch /c/Users/user/crimson-desert-got-dragon-mod/docs/references/.gitkeep
```

- [ ] **Step 5: Commit setup**

```bash
cd /c/Users/user/crimson-desert-got-dragon-mod
git add tools/texture_lib.py screenshots/.gitkeep docs/references/.gitkeep
git commit -m "$(cat <<'EOF'
Add texture rebuild shared library and folder skeleton

texture_lib.py centralises paths, texconv encoders (BC1/BC4/BC5),
and per-step folder helpers used by every build_stepN_*.py script.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: deploy_step.py — activate + reskin + (step-0-only) blacken masks

**Files:**
- Create: `tools/deploy_step.py`

- [ ] **Step 1: Create `tools/deploy_step.py`**

```python
"""Activate a step's textures and deploy them into Crimson Desert.

Usage:
    python tools/deploy_step.py <step_id> [--with-masks]

<step_id> is a folder name under got-dragon-mod/textures/drogon_fortnite/
e.g. step0_v1_baseline, step1_pbr_fix.

--with-masks runs patch_dragon_masks_black.py once. Pass it ONLY at step 0;
omit on every subsequent step so masks aren't re-blackened needlessly.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from texture_lib import activate, DRAGON_RESKIN, MASK_BLACKEN, GAME_DIR


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("step_id", help="folder name under staging root")
    parser.add_argument("--with-masks", action="store_true",
                        help="also run patch_dragon_masks_black.py (step 0 only)")
    args = parser.parse_args()

    print(f"==> Activating {args.step_id}")
    activate(args.step_id)

    print(f"==> Running dragon_reskin.py")
    rc = subprocess.call([sys.executable, str(DRAGON_RESKIN),
                          "--dragon", "drogon_fortnite",
                          "--game-dir", str(GAME_DIR)])
    if rc != 0:
        print(f"reskin failed (exit {rc})")
        return rc

    if args.with_masks:
        print(f"==> Running patch_dragon_masks_black.py")
        rc = subprocess.call([sys.executable, str(MASK_BLACKEN),
                              "--game-dir", str(GAME_DIR)])
        if rc != 0:
            print(f"mask blackener failed (exit {rc})")
            return rc

    print(f"==> Deploy complete. Launch Crimson Desert and capture screenshots.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Verify the script's argparse loads cleanly**

Run:
```bash
cd /c/Users/user/crimson-desert-got-dragon-mod
python tools/deploy_step.py --help
```

Expected: prints usage with `step_id` positional arg and `--with-masks` flag, exit 0.

- [ ] **Step 3: Confirm `patch_dragon_masks_black.py` accepts a `--game-dir` flag**

Run:
```bash
python tools/patch_dragon_masks_black.py --help 2>&1 | head -10
```

Expected: shows `--game-dir` in help. If it doesn't, edit `deploy_step.py` to omit `--game-dir` when calling the mask blackener and rely on its default. Re-test.

- [ ] **Step 4: Commit deploy script**

```bash
git add tools/deploy_step.py
git commit -m "$(cat <<'EOF'
Add deploy_step.py to activate a per-step folder and run reskin

Wraps the activate(step_id) helper + dragon_reskin.py + an optional
one-time mask-blackener pass for step 0.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Step 0 — v1.0.0 baseline build, deploy, judge, commit

**Files:**
- Create: `tools/build_step0_v1_baseline.py`
- Create (during step): `got-dragon-mod/textures/drogon_fortnite/step0_v1_baseline/Body_{d,n,sp,disp}.dds`
- Create (during step): `screenshots/step0_v1_baseline/{side,wing,head}.png`
- Update: `docs/superpowers/specs/2026-04-18-texture-rebuild-design.md` (verdict log row)

- [ ] **Step 1: Create `tools/build_step0_v1_baseline.py`**

```python
"""Step 0 — v1.0.0 baseline reproduction.

Recipe (per spec):
  Body_d.dds:    Fortnite D PNG, no AO, BC1_UNORM 2048 12 mips, sRGB
  Body_n.dds:    Fortnite N with G inverted, BC5_UNORM 2048 12 mips
  Body_sp.dds:   Fortnite M direct, BC1_UNORM 2048 12 mips
  Body_disp.dds: solid black, BC1_UNORM 2048 12 mips
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))
from texture_lib import (
    SOURCE_PNG_DIR, step_dir, encode_bc1, encode_bc5,
)

OUT = step_dir("step0_v1_baseline")
TMP = OUT / "_tmp"
TMP.mkdir(exist_ok=True)

# Body_d: Fortnite D unflipped, sRGB
d_in = SOURCE_PNG_DIR / "T_OutlineLove_Glider_D.png"
d_img = Image.open(d_in).convert("RGB")
assert d_img.size == (2048, 2048), f"D resolution {d_img.size} != 2048"
d_tmp = TMP / "Body_d.png"
d_img.save(d_tmp)
encode_bc1(d_tmp, OUT / "Body_d.dds", srgb=True)

# Body_n: Fortnite N with G inverted (UE→CD)
n_in = SOURCE_PNG_DIR / "T_OutlineLove_Glider_N.png"
n_img = Image.open(n_in).convert("RGB")
assert n_img.size == (2048, 2048), f"N resolution {n_img.size} != 2048"
n_arr = np.array(n_img)
n_arr[..., 1] = 255 - n_arr[..., 1]
Image.fromarray(n_arr, mode="RGB").save(TMP / "Body_n.png")
encode_bc5(TMP / "Body_n.png", OUT / "Body_n.dds")

# Body_sp: Fortnite M direct
m_in = SOURCE_PNG_DIR / "T_OutlineLove_Glider_M.png"
m_img = Image.open(m_in).convert("RGB")
assert m_img.size == (2048, 2048), f"M resolution {m_img.size} != 2048"
m_tmp = TMP / "Body_sp.png"
m_img.save(m_tmp)
encode_bc1(m_tmp, OUT / "Body_sp.dds")

# Body_disp: solid black
black = Image.new("RGB", (2048, 2048), (0, 0, 0))
b_tmp = TMP / "Body_disp.png"
black.save(b_tmp)
encode_bc1(b_tmp, OUT / "Body_disp.dds")

print(f"Step 0 baseline written to {OUT}")
for f in sorted(OUT.glob("*.dds")):
    print(f"  {f.name}: {f.stat().st_size:,} bytes")
```

- [ ] **Step 2: Run the build script**

```bash
cd /c/Users/user/crimson-desert-got-dragon-mod
python tools/build_step0_v1_baseline.py
```

Expected output:
```
Step 0 baseline written to ...\step0_v1_baseline
  Body_d.dds: 2,796,344 bytes
  Body_disp.dds: 2,796,344 bytes
  Body_n.dds: 5,592,560 bytes
  Body_sp.dds: 2,796,344 bytes
```

If any size differs from expected by more than 1 KB, stop and check the texconv command in `texture_lib._encode`.

- [ ] **Step 3: Capture the Fortnite reference image (one-time, only at step 0)**

User action: open Fortnite (or use a third-party Fortnite renderer / locker preview), view the Drogon glider in roughly side-profile lighting, screenshot, save as:
```
docs/references/fortnite_drogon_reference.png
```

If the user prefers, a clean static render from the FortnitePorting preview window or fortnite-api.com is also acceptable. Image must show the wing membrane colour clearly.

- [ ] **Step 4: Deploy step 0 with mask blackening**

```bash
cd /c/Users/user/crimson-desert-got-dragon-mod
python tools/deploy_step.py step0_v1_baseline --with-masks
```

Expected: prints `==> Activating`, `==> Running dragon_reskin.py`, then reskin output (23 textures patched), then `==> Running patch_dragon_masks_black.py` (5 masks patched), then `==> Deploy complete.`

If reskin reports any texture failed to patch, stop and read its error before continuing.

- [ ] **Step 5: User captures three screenshots in-game**

User action: launch Crimson Desert. Spawn Drogon at the chosen fixed vantage (suggested: Pinhol stable area, midday sun — confirm or change at this step; whatever spot you pick is locked for every later step). Capture:
- `screenshots/step0_v1_baseline/side.png` — side profile, southside camera
- `screenshots/step0_v1_baseline/wing.png` — wing-spread three-quarter
- `screenshots/step0_v1_baseline/head.png` — head close-up

Send the three to me for inline view.

- [ ] **Step 6: Record verdict in spec**

I will edit the verdict log row for Step 0 in `docs/superpowers/specs/2026-04-18-texture-rebuild-design.md`. Expected verdict: **Better** (vs. broken v0.3.9). If the verdict is **Worse** vs. broken v0.3.9 something is fundamentally wrong with the deploy chain — stop the ladder and debug.

- [ ] **Step 7: Commit step 0 artefacts**

```bash
cd /c/Users/user/crimson-desert-got-dragon-mod
git add tools/build_step0_v1_baseline.py \
        got-dragon-mod/textures/drogon_fortnite/step0_v1_baseline \
        screenshots/step0_v1_baseline \
        docs/references/fortnite_drogon_reference.png \
        docs/superpowers/specs/2026-04-18-texture-rebuild-design.md
git commit -m "$(cat <<'EOF'
Step 0: reproduce v1.0.0 baseline texture set

Body_d unflipped Fortnite D, Body_n G-inverted, Body_sp raw Fortnite M,
Body_disp solid black, masks blackened. Restores v1.0.0 wing brightness
as the floor for the iteration ladder.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Step 1 — PBR mirror fix on `_sp`

**Files:**
- Create: `tools/build_step1_pbr_fix.py`
- Create (during step): `got-dragon-mod/textures/drogon_fortnite/step1_pbr_fix/Body_{d,n,sp,disp}.dds`
- Create (during step): `screenshots/step1_pbr_fix/{side,wing,head}.png`
- Update: spec verdict log

- [ ] **Step 1: Create `tools/build_step1_pbr_fix.py`**

```python
"""Step 1 — PBR mirror fix on _sp only.

Recipe (per spec):
  Body_d, Body_n, Body_disp: copy from step0_v1_baseline (unchanged)
  Body_sp.dds: R=255, G=255-fnM.G (smoothness), B=41 (low metallic),
               A=255, BC1_UNORM 2048 12 mips
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))
from texture_lib import SOURCE_PNG_DIR, step_dir, copy_dds_from, encode_bc1

OUT = step_dir("step1_pbr_fix")
TMP = OUT / "_tmp"
TMP.mkdir(exist_ok=True)

# Carry forward d, n, disp from step 0
copy_dds_from("step0_v1_baseline", OUT)
# Re-encoding sp will overwrite the carried-over Body_sp.dds; that's fine.

# Build the PBR-fixed sp
m_in = SOURCE_PNG_DIR / "T_OutlineLove_Glider_M.png"
m_img = Image.open(m_in).convert("RGB")
m_arr = np.array(m_img)

sp_arr = np.empty_like(m_arr)
sp_arr[..., 0] = 255              # R = flat
sp_arr[..., 1] = 255 - m_arr[..., 1]  # G = smoothness (invert UE roughness)
sp_arr[..., 2] = 41               # B = low metallic (CD vanilla convention)

sp_png = TMP / "Body_sp.png"
Image.fromarray(sp_arr, mode="RGB").save(sp_png)
encode_bc1(sp_png, OUT / "Body_sp.dds")

print(f"Step 1 written to {OUT}")
for f in sorted(OUT.glob("*.dds")):
    print(f"  {f.name}: {f.stat().st_size:,} bytes")
```

- [ ] **Step 2: Run the build script**

```bash
python tools/build_step1_pbr_fix.py
```

Expected output: same four file sizes as step 0 (only sp content differs).

- [ ] **Step 3: Deploy without re-blackening masks**

```bash
python tools/deploy_step.py step1_pbr_fix
```

Expected: `==> Activating`, `==> Running dragon_reskin.py`, `==> Deploy complete.` No mask blackener output.

- [ ] **Step 4: User captures screenshots**

User action: launch Crimson Desert, same fixed vantage as step 0. Capture:
- `screenshots/step1_pbr_fix/side.png`
- `screenshots/step1_pbr_fix/wing.png`
- `screenshots/step1_pbr_fix/head.png`

Send to me.

- [ ] **Step 5: Record verdict**

I update the spec verdict log for Step 1. Expected: **Better** (mirror sheen gone). If **Worse**, redeploy step 0 (`python tools/deploy_step.py step0_v1_baseline`) and skip to step 2.

- [ ] **Step 6: Commit**

```bash
git add tools/build_step1_pbr_fix.py \
        got-dragon-mod/textures/drogon_fortnite/step1_pbr_fix \
        screenshots/step1_pbr_fix \
        docs/superpowers/specs/2026-04-18-texture-rebuild-design.md
git commit -m "$(cat <<'EOF'
Step 1: PBR mirror fix on _sp (R=255, G=smoothness, B=41, A=255)

Removes scale mirror sheen by inverting the Fortnite roughness map into
CD's smoothness convention and matching CD's flat metallic value.
Carries forward step 0's d/n/disp unchanged.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Step 2 — Real BC4 displacement on `_disp`

**Files:**
- Create: `tools/build_step2_real_disp.py`
- Create (during step): `got-dragon-mod/textures/drogon_fortnite/step2_real_disp/Body_{d,n,sp,disp}.dds`
- Create (during step): `screenshots/step2_real_disp/{side,wing,head}.png`
- Update: spec verdict log

- [ ] **Step 1: Create `tools/build_step2_real_disp.py`**

```python
"""Step 2 — Real BC4 displacement on _disp only.

Recipe (per spec):
  Body_d, Body_n, Body_sp: copy from step1_pbr_fix (unchanged)
  Body_disp.dds: source = Fortnite S.G channel, normalize to [0, 1],
                 remap to vanilla body-disp stats: clip(38 + g*12, 0, 125),
                 save as L-mode PNG, encode BC4_UNORM 2048 12 mips
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))
from texture_lib import SOURCE_PNG_DIR, step_dir, copy_dds_from, encode_bc4

OUT = step_dir("step2_real_disp")
TMP = OUT / "_tmp"
TMP.mkdir(exist_ok=True)

# Carry forward d, n, sp from step 1; disp will be re-encoded over the carry.
copy_dds_from("step1_pbr_fix", OUT)

# Build the BC4 displacement
s_in = SOURCE_PNG_DIR / "T_OutlineLove_Glider_S.png"
s_img = Image.open(s_in).convert("RGB")
s_arr = np.array(s_img, dtype=np.float32)

# Use S.G as source height
g = s_arr[..., 1] / 255.0           # normalize to [0, 1]
mapped = np.clip(38.0 + g * 12.0, 0, 125)  # vanilla body stats
disp_arr = mapped.astype(np.uint8)

disp_png = TMP / "Body_disp.png"
Image.fromarray(disp_arr, mode="L").save(disp_png)
encode_bc4(disp_png, OUT / "Body_disp.dds")

print(f"Step 2 written to {OUT}")
for f in sorted(OUT.glob("*.dds")):
    print(f"  {f.name}: {f.stat().st_size:,} bytes")
print(f"  disp stats: mean={disp_arr.mean():.1f}, max={disp_arr.max()}")
```

- [ ] **Step 2: Run the build script**

```bash
python tools/build_step2_real_disp.py
```

Expected output: four DDS sizes same as step 1, plus a final line like `disp stats: mean=44.0, max=50` (mean must be in 38-50 range, max ≤125 — anything higher means the clip didn't fire and the next step will likely produce shards in-game).

- [ ] **Step 3: Deploy**

```bash
python tools/deploy_step.py step2_real_disp
```

- [ ] **Step 4: User captures screenshots**

Same vantage. Save under `screenshots/step2_real_disp/`.

- [ ] **Step 5: Record verdict**

I update spec verdict log. Expected: **Better** (subtle scale relief). **Worse** symptoms include crystalline/shard surface or muddy darkening — if either appears, redeploy step 1 (`python tools/deploy_step.py step1_pbr_fix`) and skip to step 3.

- [ ] **Step 6: Commit**

```bash
git add tools/build_step2_real_disp.py \
        got-dragon-mod/textures/drogon_fortnite/step2_real_disp \
        screenshots/step2_real_disp \
        docs/superpowers/specs/2026-04-18-texture-rebuild-design.md
git commit -m "$(cat <<'EOF'
Step 2: real BC4 displacement matched to vanilla body stats

Fortnite S.G normalised then remapped to clip(38 + g*12, 0, 125) so
the shader's _screenSpaceDisplacementScale=0.49 produces subtle scale
micro-relief instead of crystalline shards. Carries forward step 1's
d/n/sp unchanged.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Step 3 — Sharper / cleaner `_n`

**Files:**
- Create: `tools/build_step3_sharp_normal.py`
- Create (during step): `got-dragon-mod/textures/drogon_fortnite/step3_sharp_normal/Body_{d,n,sp,disp}.dds`
- Create (during step): `screenshots/step3_sharp_normal/{side,wing,head}.png`
- Update: spec verdict log

- [ ] **Step 1: Create `tools/build_step3_sharp_normal.py`**

```python
"""Step 3 — sharper, cleaner _n.

Recipe (per spec):
  Body_d, Body_sp, Body_disp: copy from step2_real_disp (unchanged)
  Body_n.dds: Fortnite N at native 2048 (no resize), G inverted,
              BC5_UNORM 2048 12 mips with texconv default mip filter
              (bilinear / box) for cleaner mip pyramid than v1.0.0's
              implicit nearest-style downsample.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))
from texture_lib import SOURCE_PNG_DIR, step_dir, copy_dds_from, encode_bc5

OUT = step_dir("step3_sharp_normal")
TMP = OUT / "_tmp"
TMP.mkdir(exist_ok=True)

# Carry forward d, sp, disp from step 2; n is re-encoded.
copy_dds_from("step2_real_disp", OUT)

# Build the cleaner normal: native res, G inverted, no convert/resize so we
# preserve every pixel of detail; texconv handles the BC5 encode + mips.
n_in = SOURCE_PNG_DIR / "T_OutlineLove_Glider_N.png"
n_img = Image.open(n_in).convert("RGB")
assert n_img.size == (2048, 2048), f"N resolution {n_img.size} != 2048"
n_arr = np.array(n_img)
n_arr[..., 1] = 255 - n_arr[..., 1]   # invert G for CD convention
Image.fromarray(n_arr, mode="RGB").save(TMP / "Body_n.png")
encode_bc5(TMP / "Body_n.png", OUT / "Body_n.dds")

print(f"Step 3 written to {OUT}")
for f in sorted(OUT.glob("*.dds")):
    print(f"  {f.name}: {f.stat().st_size:,} bytes")
```

- [ ] **Step 2: Run the build script**

```bash
python tools/build_step3_sharp_normal.py
```

Expected: same four sizes as step 2 (Body_n same byte count as before).

- [ ] **Step 3: Deploy**

```bash
python tools/deploy_step.py step3_sharp_normal
```

- [ ] **Step 4: User captures screenshots**

Same vantage. Save under `screenshots/step3_sharp_normal/`.

- [ ] **Step 5: Record verdict**

Update spec. Expected: **Same** or **Better** (subtle change). If **Worse** (banding, weird sheen), redeploy step 2 and proceed to step 4.

- [ ] **Step 6: Commit**

```bash
git add tools/build_step3_sharp_normal.py \
        got-dragon-mod/textures/drogon_fortnite/step3_sharp_normal \
        screenshots/step3_sharp_normal \
        docs/superpowers/specs/2026-04-18-texture-rebuild-design.md
git commit -m "$(cat <<'EOF'
Step 3: cleaner BC5 normal at native 2048 resolution

Encodes Fortnite N (G inverted) with no intermediate resize so every
source pixel survives, plus texconv default mip filter for a smoother
mip chain than v1.0.0's. Carries forward step 2's d/sp/disp.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Step 4 (optional) — Wing-safe AO bake

**Gate:** ONLY do this task if the user judges step 3 result still reads "flat" compared to the Fortnite reference. If step 3 was already at-or-above reference, skip to Task 8.

**Files:**
- Create: `tools/build_step4_wing_safe_ao.py`
- Create (during step): `got-dragon-mod/textures/drogon_fortnite/step4_wing_safe_ao/Body_{d,n,sp,disp}.dds`
- Create (during step): `screenshots/step4_wing_safe_ao/{side,wing,head}.png`
- Create (during step): `got-dragon-mod/textures/drogon_fortnite/wing_uv_mask.png` (one-off helper)
- Update: spec verdict log

- [ ] **Step 1: User identifies wing UV bounds on the Body_d sheet**

User opens `got-dragon-mod/textures/drogon_fortnite/Body_d.png` (the source PNG, NOT the DDS) in any image editor (GIMP, Photoshop, Krita). The wing membranes appear as the two large fan-shaped patches on the texture. User paints a black-and-white mask:
- White (255) where wings are
- Black (0) elsewhere
- Soft black-to-white transition at edges (5–10 px feather)

Save as: `got-dragon-mod/textures/drogon_fortnite/wing_uv_mask.png` (RGB or L mode, 2048×2048).

If the user prefers, we generate the mask programmatically from the Drogon mesh's wing-bone weights instead — but that's a deeper detour; the hand-paint approach is faster and good enough.

- [ ] **Step 2: Generate AO via Blender bake (one-off)**

User opens the rigged Drogon Blend file (`output/drogon_fortnite_rigged.blend` per the texture map's references) in Blender 3.6+:
1. Select all Drogon mesh pieces.
2. Switch render engine to Cycles.
3. Add a new image texture in the materials: 2048×2048, RGB, named `Drogon_AO`.
4. Bake → AO bake mode, samples = 512, distance = 0.05, save image.
5. Export as `got-dragon-mod/textures/drogon_fortnite/drogon_ao.png` (8-bit grayscale or RGB).

If the user has not previously baked AO and this is too much detour, they can skip Task 7 entirely (step 3 is the shipping default).

- [ ] **Step 3: Create `tools/build_step4_wing_safe_ao.py`**

```python
"""Step 4 (optional) — wing-safe AO bake on _d only.

Recipe (per spec):
  Body_n, Body_sp, Body_disp: copy from step3_sharp_normal (unchanged)
  Body_d.dds: Fortnite D * (0.7 + ao * 0.3), masked so wing pixels keep
              their full Fortnite D brightness. BC1_UNORM 2048 12 mips, sRGB.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))
from texture_lib import (
    SOURCE_PNG_DIR, STAGING_ROOT, step_dir, copy_dds_from, encode_bc1,
)

OUT = step_dir("step4_wing_safe_ao")
TMP = OUT / "_tmp"
TMP.mkdir(exist_ok=True)

# Carry forward n, sp, disp from step 3; d is re-encoded.
copy_dds_from("step3_sharp_normal", OUT)

# Inputs
d_in = SOURCE_PNG_DIR / "T_OutlineLove_Glider_D.png"
ao_in = STAGING_ROOT / "drogon_ao.png"
mask_in = STAGING_ROOT / "wing_uv_mask.png"

assert d_in.exists(), f"missing {d_in}"
assert ao_in.exists(), f"missing AO bake at {ao_in} — see Task 7 step 2"
assert mask_in.exists(), f"missing wing mask at {mask_in} — see Task 7 step 1"

d = np.array(Image.open(d_in).convert("RGB"), dtype=np.float32) / 255.0
ao = np.array(Image.open(ao_in).convert("L"), dtype=np.float32) / 255.0
wing_mask = np.array(Image.open(mask_in).convert("L"), dtype=np.float32) / 255.0

# AO multiplier: 0.7 in fully-occluded pixels, 1.0 in fully-lit.
ao_mult = 0.7 + ao * 0.3
# Wing protection: where wing_mask is 1.0, multiplier becomes 1.0 (no AO).
ao_mult = ao_mult * (1.0 - wing_mask) + 1.0 * wing_mask

result = (d * ao_mult[..., None]).clip(0, 1) * 255.0
result_arr = result.astype(np.uint8)

result_png = TMP / "Body_d.png"
Image.fromarray(result_arr, mode="RGB").save(result_png)
encode_bc1(result_png, OUT / "Body_d.dds", srgb=True)

print(f"Step 4 written to {OUT}")
for f in sorted(OUT.glob("*.dds")):
    print(f"  {f.name}: {f.stat().st_size:,} bytes")
print(f"  d mean before: {(d.mean() * 255):.1f}, after: {result_arr.mean():.1f}")
print(f"  wing-area mean before: {(d[wing_mask > 0.5].mean() * 255):.1f}, "
      f"after: {result_arr[wing_mask > 0.5].mean():.1f} (should be ~equal)")
```

- [ ] **Step 4: Run the build script**

```bash
python tools/build_step4_wing_safe_ao.py
```

Expected: four DDS sizes same as step 3. Final two stat lines must show:
- Overall mean dropped slightly (e.g. 50 → 45 — body shading kicked in).
- Wing-area mean before ≈ after (within ±1) — wings preserved.

If wing-area mean drops by more than 2, the wing mask is leaking — re-paint with harder edges.

- [ ] **Step 5: Deploy**

```bash
python tools/deploy_step.py step4_wing_safe_ao
```

- [ ] **Step 6: User captures screenshots**

Same vantage. Save under `screenshots/step4_wing_safe_ao/`.

- [ ] **Step 7: Record verdict**

Update spec. Expected: **Better** (body has shading depth, wings still bright). If **Worse** (wings darken / weird body shadows), redeploy step 3 and call the ladder done at step 3.

- [ ] **Step 8: Commit**

```bash
git add tools/build_step4_wing_safe_ao.py \
        got-dragon-mod/textures/drogon_fortnite/step4_wing_safe_ao \
        got-dragon-mod/textures/drogon_fortnite/wing_uv_mask.png \
        got-dragon-mod/textures/drogon_fortnite/drogon_ao.png \
        screenshots/step4_wing_safe_ao \
        docs/superpowers/specs/2026-04-18-texture-rebuild-design.md
git commit -m "$(cat <<'EOF'
Step 4 (optional): wing-safe AO bake on _d

Multiplies Fortnite D by (0.7 + ao*0.3), with a hand-painted wing UV
mask forcing the wing-membrane pixels to multiplier=1.0 so they keep
their full v1.0.0 brightness. Adds body shading depth without
re-introducing the v0.3.9 wing-darkening regression.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: Finalisation — verdict log + ship

**Files:**
- Update: `docs/superpowers/specs/2026-04-18-texture-rebuild-design.md` (verdict log final summary + open questions resolved)
- Update: `MEMORY.md` (move texture rebuild status from "WIP" to "complete", point at the final shipping step)

- [ ] **Step 1: Pick the shipping step**

Identify the final committed step whose verdict was the highest. That folder under `got-dragon-mod/textures/drogon_fortnite/stepN_*/` is the ship-canonical content. Activate it as the active staging dir:

```bash
python -c "from tools.texture_lib import activate; activate('stepN_NAME')"
```
(replace `stepN_NAME` with the chosen folder).

- [ ] **Step 2: Update the spec verdict log final-summary section**

I (or whoever runs Task 8) edits the spec to add a paragraph after the verdict log:

```markdown
## Final outcome

Shipping recipe = **stepN_NAME** (commit `<sha>`). Side/wing/head screenshots in `screenshots/stepN_NAME/` are the reference renders. Reserved-future-work items remain unaddressed and are documented in their own follow-up tickets.
```

- [ ] **Step 3: Update memory pointer**

Edit `C:\Users\user\.claude\projects\C--Users-user\memory\MEMORY.md`: under the "Crimson Desert GoT Dragon Mod" section, replace the "FORTNITE DROGON … texture WIP" line with a one-line pointer to the spec + final shipping step.

- [ ] **Step 4: Commit**

```bash
git add docs/superpowers/specs/2026-04-18-texture-rebuild-design.md
git commit -m "$(cat <<'EOF'
Texture rebuild ladder complete — shipping stepN_NAME

Verdict log filled in; final shipping recipe pinned in the spec.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

The MEMORY.md edit is in a separate location and is committed separately if applicable.

---

## Spec coverage check (self-review)

Walking each spec section:

- **Architecture / per-step staging folders / dragon_reskin re-use** → Task 1 (texture_lib) + Task 2 (deploy_step). ✓
- **Mask blackening once at step 0** → Task 3 step 4 (`--with-masks` flag). ✓
- **Step 0 v1.0.0 baseline recipe** → Task 3 step 1. ✓
- **Step 1 PBR mirror fix recipe** → Task 4 step 1. ✓
- **Step 2 BC4 disp recipe + clamp safety** → Task 5 step 1 + the disp stats assertion at step 2. ✓
- **Step 3 sharper normal recipe** → Task 6 step 1. ✓
- **Step 4 wing-safe AO + mask gate** → Task 7 (entire). ✓
- **A/B test protocol — 3 screenshots per step, fixed vantage, verdict log** → encoded in every "user captures screenshots" + "record verdict" step. ✓
- **Reference image acquisition** → Task 3 step 3. ✓
- **Snapshot/rollback rule** → simplified: per-step folders are themselves the snapshots; rollback = redeploy from prior step folder; explicitly noted in steps 5/6 of every task with a "redeploy step{N-1}" callout. ✓
- **Stop condition** → noted in Task 7 gate. ✓
- **Open questions (source res, per-submesh disp variants, wing mask accuracy)** → source res confirmed at 2048 in Task 1 step 2; per-submesh disp variants left as reserved future work; wing mask accuracy explicitly checked by stat assertion in Task 7 step 4. ✓
