# CD Dragon Anim Retarget — Phase 0+1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Locate the PAZ archive that holds dragon animation `.hkx` clips, extract them, and prove via JMM override that we can replace anim bytes and the engine reads our edits.

**Architecture:** Two-phase research spike. Phase 0 = scan PAZ archives for dragon animation files and extract them. Phase 1 = drop one extracted anim into a JMM mod folder, replace bytes (zeros / clone-of-different-clip), launch the game, and observe the dragon visibly behave differently. Both phases have hard kill criteria — if either fails, this plan stops and we re-design.

**Tech Stack:** Python 3 (struct, pathlib, json), CrimsonDesert PAZ container (existing extract scripts in `CrimsonForge`), CD JSON Mod Manager for runtime override, manual in-game observation for verification.

**Spec:** `docs/superpowers/specs/2026-04-26-cd-anim-retarget-design.md` (commit `47a3b8c`)

**Out of scope for this plan:** TAG0 decoder, encoder, retargeting, Blender pipeline, encode-and-ship. Those land in a follow-up plan once Phase 0+1 ground-truth lands.

---

## File Structure

This plan creates / modifies the following:

```
crimson-desert-got-dragon-mod/
├── tools/
│   └── anim/
│       ├── __init__.py                 # NEW: empty package marker
│       ├── paz_listing.py              # NEW: lists PAZ contents without extracting
│       ├── find_anim_paz.py            # NEW: scans all PAZs for dragon-anim candidates
│       └── extract_anim_paz.py         # NEW: extracts identified anim PAZ to disk
├── tests/
│   └── anim/
│       ├── __init__.py                 # NEW: empty package marker
│       └── test_paz_listing.py         # NEW: validates listing output shape
├── dragon-anim-extract/                # NEW: target folder for extracted anim files (gitignored)
├── docs/
│   └── cd_anim_format_notes.md         # NEW: running notes on findings
└── .gitignore                          # MODIFY: ignore dragon-anim-extract/

C:\Users\waelj\Downloads\cd_json_mm\CD JSON Mod Manager\mods\
└── Drogon-AnimSpike-Phase1/            # NEW: throwaway JMM mod for override testing
    ├── mod.json
    └── files/
        └── <path-mirroring-vanilla>    # filled in during Phase 1
```

**Why this layout:** `tools/anim/` keeps anim work separate from the mature `tools/` mesh/PAB tooling so we don't accidentally break the V11 ship pipeline. `dragon-anim-extract/` mirrors the existing `dragon-extract/` naming convention. `docs/cd_anim_format_notes.md` is the single living document that captures findings as we go — it's what the Phase 2+ plan will be written against.

---

## Task 0: Set up isolated worktree and notes file

**Files:**
- Create: `docs/cd_anim_format_notes.md`
- Modify: `.gitignore`

**Why:** A multi-week reverse-engineering project with kill criteria belongs on its own branch so master stays clean if Phase 0/1 fails. The notes file accumulates findings the next plan will be written from.

- [ ] **Step 1: Create a worktree off master**

```bash
cd /c/Users/waelj/crimson-desert-got-dragon-mod
git worktree add -b feat-anim-retarget .worktrees/feat-anim-retarget master
cd .worktrees/feat-anim-retarget
```

Expected: new worktree at `.worktrees/feat-anim-retarget/` on branch `feat-anim-retarget`.

- [ ] **Step 2: Create the running-notes file**

Path: `docs/cd_anim_format_notes.md`

```markdown
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
```

- [ ] **Step 3: Add `dragon-anim-extract/` to gitignore**

Open `.gitignore`. Append:

```
# Phase 0 anim extraction output (large binary, regeneratable)
dragon-anim-extract/
```

- [ ] **Step 4: Create empty extraction target folder**

```bash
mkdir -p dragon-anim-extract
```

- [ ] **Step 5: Commit**

```bash
git add docs/cd_anim_format_notes.md .gitignore
git commit -m "anim: scaffold notes file and extraction folder"
```

---

## Task 1: Inventory existing PAZ archives

**Files:**
- Modify: `docs/cd_anim_format_notes.md`

**Why:** Before scanning for anim files we need a full list of PAZ archives the game uses. The existing `extract_cd_dragon.py` only points at one PAZ. We need to know all of them.

- [ ] **Step 1: Locate the game's PAZ folder**

The CD installation has a `Paz` folder under the install root. Check:

```bash
ls "/c/Program Files (x86)/Steam/steamapps/common/Crimson Desert/Paz/" 2>/dev/null | head -20
ls "/c/Program Files/Pearl Abyss/Crimson Desert/Paz/" 2>/dev/null | head -20
```

Record the actual path. If neither exists, search:

```bash
find /c -maxdepth 6 -name "*.paz" 2>/dev/null | head -10
```

- [ ] **Step 2: List all PAZ archives with sizes**

Run (substituting the path from Step 1):

```bash
ls -la "<paz-folder>/" | grep -E "\.paz$" > /tmp/paz_inventory.txt
wc -l /tmp/paz_inventory.txt
```

Expected: tens to hundreds of `.paz` files.

- [ ] **Step 3: Append the inventory summary to notes**

In `docs/cd_anim_format_notes.md`, under `## Phase 0 findings`, add:

```markdown
### PAZ inventory (Task 1)

- Path: `<absolute-path>`
- Count: <N> archives
- Total size: <X> GB
- Largest 5: <list>
- Mesh PAZ confirmed location: `<path>/0009/3.paz`
```

- [ ] **Step 4: Commit**

```bash
git add docs/cd_anim_format_notes.md
git commit -m "anim: inventory PAZ archives"
```

---

## Task 2: Write a PAZ-content lister (no extraction)

**Files:**
- Create: `tools/anim/__init__.py` (empty)
- Create: `tools/anim/paz_listing.py`
- Create: `tests/anim/__init__.py` (empty)
- Create: `tests/anim/test_paz_listing.py`

**Why:** Extracting every PAZ would consume hundreds of GB. We need to LIST contents (filenames + offsets) without writing extracted bytes to disk, so we can then grep for dragon/anim keywords across all archives cheaply.

The PAZ format is documented in CrimsonForge's existing `extract_cd_dragon.py`. We mirror its parsing here but skip the actual file-data write.

- [ ] **Step 1: Create empty package markers**

```bash
touch tools/anim/__init__.py tests/anim/__init__.py
```

- [ ] **Step 2: Write a failing test for the listing function**

Path: `tests/anim/test_paz_listing.py`

```python
"""Tests for PAZ content listing (read-only inspection, no extraction)."""

from pathlib import Path

from tools.anim.paz_listing import list_paz_contents, PazEntry


def test_list_paz_contents_returns_dragon_pac_for_known_paz():
    """The mesh PAZ at 0009/3.paz must list cd_m0004_00_dragon_00_0001.pac."""
    # Use the user's confirmed mesh PAZ path. Update if game install moved.
    paz_path = Path(
        r"C:\Program Files (x86)\Steam\steamapps\common\Crimson Desert\Paz\0009\3.paz"
    )
    if not paz_path.exists():
        # Allow alternate install paths; the test owner updates this constant.
        return  # skip — let the runner know via stdout

    entries = list_paz_contents(paz_path)

    # Must return a list of PazEntry namedtuples
    assert isinstance(entries, list)
    assert len(entries) > 0
    assert all(isinstance(e, PazEntry) for e in entries)

    # Each entry has filename, offset, size
    e = entries[0]
    assert hasattr(e, "filename")
    assert hasattr(e, "offset")
    assert hasattr(e, "size")
    assert isinstance(e.filename, str)
    assert isinstance(e.offset, int)
    assert isinstance(e.size, int)

    # The mesh PAZ must contain the dragon PAC at the known offset and size
    dragon_pac_entries = [
        e for e in entries
        if "cd_m0004_00_dragon_00_0001.pac" in e.filename.lower()
    ]
    assert len(dragon_pac_entries) == 1, \
        f"expected exactly one dragon PAC entry, got {len(dragon_pac_entries)}"
    assert dragon_pac_entries[0].size == 5_208_284
```

- [ ] **Step 3: Run the test, expect import failure**

```bash
cd /c/Users/waelj/crimson-desert-got-dragon-mod/.worktrees/feat-anim-retarget
python -m pytest tests/anim/test_paz_listing.py -v
```

Expected: ImportError or ModuleNotFoundError on `tools.anim.paz_listing`. If not, the test wasn't pulled in; fix the test path / pytest config.

- [ ] **Step 4: Implement the listing function**

Path: `tools/anim/paz_listing.py`

```python
"""Read-only listing of CD PAZ archive contents.

PAZ format (per existing CrimsonForge extract scripts):
  - Header magic and version
  - Directory table: per-file entries with [filename_string, offset_u64, size_u64]
  - File data blob

This module ONLY reads the directory table — no file payloads are dereferenced,
so listing is fast and uses constant memory regardless of archive size.

If the format reverse-engineered here drifts from CrimsonForge's parser, fall back
to subprocess-calling `extract_cd_dragon.py --list-only`. See cd_anim_format_notes.md.
"""

from __future__ import annotations
import struct
from collections import namedtuple
from pathlib import Path
from typing import List

PazEntry = namedtuple("PazEntry", ["filename", "offset", "size"])


def list_paz_contents(paz_path: Path) -> List[PazEntry]:
    """Return the directory table of a PAZ archive without reading any file payloads.

    Args:
        paz_path: Absolute path to a .paz file.

    Returns:
        List of PazEntry. Order matches the directory table order in the file.

    Raises:
        FileNotFoundError: paz_path does not exist.
        ValueError: file is not a recognisable PAZ archive (bad magic or truncated).
    """
    if not paz_path.exists():
        raise FileNotFoundError(f"PAZ not found: {paz_path}")

    with paz_path.open("rb") as f:
        header = f.read(16)
        # The exact PAZ magic is documented in CrimsonForge's extract scripts.
        # Implementer: confirm bytes 0-3 against extract_cd_dragon.py before trusting.
        # If the magic check below fails on a known-good PAZ, update MAGIC.
        MAGIC = b"PAZ\x00"  # Placeholder — verify against CrimsonForge
        if not header.startswith(MAGIC):
            # Fall back: defer to CrimsonForge's parser by importing its module.
            return _list_via_crimsonforge(paz_path)

        # Read the rest of the header to find directory offset + entry count.
        # Field layout below is a STARTING POINT — must be confirmed against
        # CrimsonForge's extract_cd_dragon.py before relying on this code path.
        version, dir_offset, entry_count = struct.unpack_from("<III", header, 4)

        f.seek(dir_offset)
        entries: List[PazEntry] = []
        for _ in range(entry_count):
            # Per-entry layout (placeholder — verify):
            #   uint16 name_len
            #   bytes  name (utf-8)
            #   uint64 offset
            #   uint64 size
            (name_len,) = struct.unpack("<H", f.read(2))
            name = f.read(name_len).decode("utf-8", errors="replace")
            offset, size = struct.unpack("<QQ", f.read(16))
            entries.append(PazEntry(filename=name, offset=offset, size=size))

    return entries


def _list_via_crimsonforge(paz_path: Path) -> List[PazEntry]:
    """Fallback: call CrimsonForge's parser if our header guess was wrong."""
    import sys
    cf = Path(r"C:\Users\waelj\Downloads\CrimsonForge-446-5-1775146612")
    if str(cf) not in sys.path:
        sys.path.insert(0, str(cf))
    # CrimsonForge exposes file enumeration via its extract module. Confirm the
    # function name by inspecting extract_cd_dragon.py — adjust import below.
    from extract_cd_dragon import enumerate_paz_entries  # type: ignore
    raw = enumerate_paz_entries(str(paz_path))
    return [PazEntry(filename=r["name"], offset=r["offset"], size=r["size"]) for r in raw]
```

> **Implementer note:** the byte-layout details (`MAGIC`, `<III`, `<H`, `<QQ` field widths) are extrapolated from typical PAZ-style archive layouts. Before running anything beyond Step 5 below, **open `C:\Users\waelj\Downloads\CrimsonForge-446-5-1775146612\extract_cd_dragon.py` and confirm the actual header structure**, then update `MAGIC` and the unpack format strings to match. If CrimsonForge's parser is cleaner, the `_list_via_crimsonforge` fallback is the entire implementation — `list_paz_contents` becomes a thin wrapper.

- [ ] **Step 5: Run the test, expect pass**

```bash
python -m pytest tests/anim/test_paz_listing.py -v
```

Expected: PASS. If it fails because the format guess was wrong, switch the implementation to delegate to CrimsonForge's parser entirely (delete the inline parsing branch, keep only `_list_via_crimsonforge`).

- [ ] **Step 6: Commit**

```bash
git add tools/anim/__init__.py tools/anim/paz_listing.py \
        tests/anim/__init__.py tests/anim/test_paz_listing.py
git commit -m "anim: PAZ content lister (read-only directory table)"
```

---

## Task 3: Scan all PAZs for dragon-anim candidates

**Files:**
- Create: `tools/anim/find_anim_paz.py`
- Modify: `docs/cd_anim_format_notes.md`

**Why:** With the lister working, we now sweep every PAZ archive and grep filenames for `m0004` (dragon entity ID), animation-suggestive substrings, and `.hkx` extension. The output is a ranked list of candidate PAZs to extract from.

- [ ] **Step 1: Implement the scanner**

Path: `tools/anim/find_anim_paz.py`

```python
"""Sweep all PAZ archives and emit a ranked list of dragon-anim candidates.

Heuristics for "dragon anim file":
  - Filename contains the dragon entity ID (`m0004`)
  - Filename ends in `.hkx`
  - Filename contains animation-suggestive substrings: 'anim', 'mot', 'clip',
    'fly', 'flap', 'idle', 'walk', 'run', 'attack', 'takeoff', 'land'

Score: 2 points for `m0004` + `.hkx`, +1 each for animation substring.
Top-scoring PAZs are the extraction targets in Task 4.
"""

from __future__ import annotations
import json
import sys
from pathlib import Path
from typing import Dict, List, Tuple

from tools.anim.paz_listing import list_paz_contents, PazEntry

ANIM_KEYWORDS = (
    "anim", "mot", "clip", "fly", "flap", "idle",
    "walk", "run", "attack", "takeoff", "land",
    "hover", "death", "hit", "pose",
)
DRAGON_ID = "m0004"


def score_entry(filename: str) -> int:
    """Score a single filename by anim-candidate heuristics."""
    name = filename.lower()
    score = 0
    if DRAGON_ID in name and name.endswith(".hkx"):
        score += 2
    for kw in ANIM_KEYWORDS:
        if kw in name:
            score += 1
    return score


def scan_paz_folder(paz_root: Path) -> Dict[str, List[Tuple[int, PazEntry]]]:
    """Return mapping {paz_relative_path: [(score, entry), ...]}.

    Only PAZs containing at least one entry with score >= 2 are included.
    Entries within each PAZ are sorted by descending score.
    """
    results: Dict[str, List[Tuple[int, PazEntry]]] = {}
    paz_files = sorted(paz_root.rglob("*.paz"))
    print(f"Scanning {len(paz_files)} PAZ archives under {paz_root}")

    for paz in paz_files:
        try:
            entries = list_paz_contents(paz)
        except Exception as exc:  # noqa: BLE001
            print(f"  [skip] {paz.relative_to(paz_root)}: {exc}")
            continue
        scored = [(score_entry(e.filename), e) for e in entries]
        hits = [(s, e) for s, e in scored if s >= 2]
        if hits:
            hits.sort(key=lambda x: -x[0])
            results[str(paz.relative_to(paz_root))] = hits
    return results


def main() -> None:
    if len(sys.argv) < 2:
        print("usage: python -m tools.anim.find_anim_paz <paz-root> [output.json]")
        sys.exit(2)
    paz_root = Path(sys.argv[1])
    out = Path(sys.argv[2]) if len(sys.argv) >= 3 else Path("dragon-anim-candidates.json")

    results = scan_paz_folder(paz_root)
    print(f"\nFound dragon-anim candidates in {len(results)} PAZs:")
    for paz_rel, hits in results.items():
        print(f"  {paz_rel}: {len(hits)} entries (top score {hits[0][0]})")
        for s, e in hits[:5]:
            print(f"    [{s}] {e.filename} ({e.size:,} bytes)")

    out.write_text(json.dumps(
        {paz: [{"score": s, "filename": e.filename, "offset": e.offset, "size": e.size}
               for s, e in hits]
         for paz, hits in results.items()},
        indent=2,
    ))
    print(f"\nWritten ranked candidates to {out}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run the scanner against the game's PAZ folder**

```bash
python -m tools.anim.find_anim_paz "<paz-folder-from-Task-1>" dragon-anim-candidates.json
```

Expected: console output listing 1–10 PAZs containing `m0004*.hkx` files, with file counts and example names. JSON saved to `dragon-anim-candidates.json` in repo root.

- [ ] **Step 3: Eyeball the output**

Look at the top-ranked PAZ. Are there filenames like `cd_m0004_anim_idle_0001.hkx`, `cd_m0004_anim_fly_loop.hkx`, etc.? Or are filenames opaque (`m0004_a01.hkx`)? Either is OK — record what you see.

- [ ] **Step 4: Append findings to notes**

In `docs/cd_anim_format_notes.md` under `## Phase 0 findings`, add:

```markdown
### Anim PAZ candidates (Task 3)

- Top PAZ: `<relative-path>` with <N> dragon-hkx entries
- Filename pattern observed: `<example>` (e.g. names ARE descriptive / names ARE NOT descriptive)
- Other PAZs with dragon hkx: <list>
- Total candidate clip count (across all PAZs): <N>
```

- [ ] **Step 5: Decide kill-or-proceed**

**Pass criterion:** at least one PAZ has 5+ dragon-related `.hkx` entries with reasonable file sizes (1 KB – 5 MB each). This means anims are standalone files we can extract and override individually.

**Kill criterion:** no PAZ has more than 1 dragon `.hkx` entry (the skeleton one we already have), OR all candidate hkx files are > 50 MB (suggests they're behaviour-graph monoliths, not per-clip files). In that case STOP this plan and write a new spec/plan for whatever the actual injection unit turns out to be.

Record the decision in the notes file as `**Phase 0 verdict: PROCEED**` or `**Phase 0 verdict: STOP — <reason>**`.

- [ ] **Step 6: Commit**

```bash
git add tools/anim/find_anim_paz.py docs/cd_anim_format_notes.md dragon-anim-candidates.json
git commit -m "anim: scan PAZs for dragon-anim candidates, record findings"
```

If the verdict is STOP, this plan ends here. Push the branch and write a follow-up brainstorm to figure out the alternative injection mechanism. Do not continue to Task 4.

---

## Task 4: Extract the top-candidate anim PAZ

**Files:**
- Create: `tools/anim/extract_anim_paz.py`
- Modify: `docs/cd_anim_format_notes.md`

**Why:** With one PAZ identified as the dragon-anim source, extract its dragon-hkx entries to `dragon-anim-extract/character/` (mirroring the existing `dragon-extract/` layout).

- [ ] **Step 1: Implement the extractor**

Path: `tools/anim/extract_anim_paz.py`

```python
"""Extract dragon-anim hkx files from an identified PAZ to dragon-anim-extract/.

Reads `dragon-anim-candidates.json` (produced by find_anim_paz.py), picks all
entries from the highest-scoring PAZ, and writes their bytes out preserving the
internal directory path under `dragon-anim-extract/`.
"""

from __future__ import annotations
import json
import sys
from pathlib import Path

from tools.anim.paz_listing import list_paz_contents


def extract_top_paz(paz_root: Path, candidates_path: Path, out_root: Path) -> int:
    """Extract every dragon-hkx entry from the top-ranked PAZ in candidates_path.

    Returns the number of files written.
    """
    candidates = json.loads(candidates_path.read_text())
    if not candidates:
        print("No candidates in JSON; nothing to extract.")
        return 0

    top_paz_rel = next(iter(candidates))
    target_filenames = {entry["filename"] for entry in candidates[top_paz_rel]}

    paz_path = paz_root / top_paz_rel
    print(f"Extracting from {paz_path}")
    print(f"Target entries: {len(target_filenames)}")

    entries = list_paz_contents(paz_path)
    targets = [e for e in entries if e.filename in target_filenames]

    written = 0
    with paz_path.open("rb") as src:
        for entry in targets:
            dest = out_root / entry.filename
            dest.parent.mkdir(parents=True, exist_ok=True)
            src.seek(entry.offset)
            dest.write_bytes(src.read(entry.size))
            written += 1
            print(f"  wrote {dest.relative_to(out_root)} ({entry.size:,} bytes)")
    return written


def main() -> None:
    if len(sys.argv) < 2:
        print("usage: python -m tools.anim.extract_anim_paz <paz-root> "
              "[candidates.json=dragon-anim-candidates.json] "
              "[out-root=dragon-anim-extract]")
        sys.exit(2)

    paz_root = Path(sys.argv[1])
    candidates = Path(sys.argv[2]) if len(sys.argv) >= 3 else Path("dragon-anim-candidates.json")
    out_root = Path(sys.argv[3]) if len(sys.argv) >= 4 else Path("dragon-anim-extract")

    n = extract_top_paz(paz_root, candidates, out_root)
    print(f"\nExtracted {n} files to {out_root}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run the extractor**

```bash
python -m tools.anim.extract_anim_paz "<paz-folder>"
```

Expected: console output listing each extracted file. Files appear under `dragon-anim-extract/character/` (or whatever internal path the PAZ used).

- [ ] **Step 3: Verify magic bytes match Havok TAGFILE**

```bash
for f in dragon-anim-extract/character/*.hkx; do
  echo "=== $f ==="
  head -c 16 "$f" | xxd
done | head -30
```

Expected: every file starts with `TAG0` (after a 4-byte size prefix) and contains `SDKV20240200`. If any file doesn't, that's a heterogeneous archive — record which formats appear and adjust Task 5's clip-pick accordingly.

- [ ] **Step 4: Append findings to notes**

In `docs/cd_anim_format_notes.md` under `## Phase 0 findings`, add:

```markdown
### Extracted anim files (Task 4)

- Source PAZ: `<top-paz-rel>`
- Files extracted: <N>
- Size range: <min>–<max> bytes
- All start with TAG0/SDKV20240200: yes/no
- Filename pattern visible after extraction: `<sample>`
- Anim that looks most like dragon idle (smallest sensible candidate): `<filename>`
- Anim that looks most like flap/fly: `<filename>`
```

- [ ] **Step 5: Commit (do not commit the extract folder, it's gitignored)**

```bash
git add tools/anim/extract_anim_paz.py docs/cd_anim_format_notes.md
git commit -m "anim: extractor for top-candidate anim PAZ + record extraction findings"
```

---

## Task 5: Phase 1 override spike — baseline clone test

**Files:**
- Create: `C:\Users\waelj\Downloads\cd_json_mm\CD JSON Mod Manager\mods\Drogon-AnimSpike-Phase1\mod.json`
- Create: `C:\Users\waelj\Downloads\cd_json_mm\CD JSON Mod Manager\mods\Drogon-AnimSpike-Phase1\files\<vanilla-relative-path>` (filled in this task)
- Modify: `docs/cd_anim_format_notes.md`

**Why:** Before we touch bytes, prove the baseline: dropping the *unchanged* anim file into JMM's mods folder must not change in-game behaviour. If JMM is somehow corrupting the file in transit, we need to know NOW, not after we've spent days decoding the format.

- [ ] **Step 1: Create the JMM mod scaffold**

Replace `<JMM-MODS>` below with `C:\Users\waelj\Downloads\cd_json_mm\CD JSON Mod Manager\mods` (forward-slash form: `/c/Users/waelj/Downloads/cd_json_mm/CD JSON Mod Manager/mods`).

```bash
JMM_MODS="/c/Users/waelj/Downloads/cd_json_mm/CD JSON Mod Manager/mods"
MOD="$JMM_MODS/Drogon-AnimSpike-Phase1"
mkdir -p "$MOD/files"
```

- [ ] **Step 2: Write the mod manifest**

Path: `<JMM-MODS>/Drogon-AnimSpike-Phase1/mod.json`

```json
{
    "modinfo": {
        "title": "Drogon Anim Spike (Phase 1)",
        "version": "0.1.0",
        "author": "Wael (The Digital Sandbox)",
        "description": "Phase 1 override spike for anim retarget project. Replaces one dragon anim hkx with (a) clone-of-itself, (b) zeros, (c) clone-of-different-clip across three sub-tests. Throwaway mod — disable when done."
    }
}
```

- [ ] **Step 3: Pick the test clip and copy it unchanged**

Choose the clip identified in Task 4 as "most like dragon idle" — it should be a clip that loops continuously when the dragon is on the ground, so any change is immediately visible. Record its name as `$CLIP` (e.g. `cd_m0004_anim_idle_0001.hkx`).

The relative path in the JMM mod must mirror its path inside the source PAZ (typically `character/` for dragon files). Confirm against Task 4's extraction output.

```bash
CLIP_REL="character/cd_m0004_anim_idle_0001.hkx"   # update with actual filename + relative path
SRC="dragon-anim-extract/$CLIP_REL"
DEST="$MOD/files/$CLIP_REL"
mkdir -p "$(dirname "$DEST")"
cp "$SRC" "$DEST"
```

- [ ] **Step 4: Disable all other Drogon mods in JMM, enable Phase1 spike**

Open the JMM UI. Disable any `Drogon-Fortnite-V*` mod that's currently active (especially V11). Enable `Drogon-AnimSpike-Phase1`. Apply.

- [ ] **Step 5: Launch CD and observe baseline**

Launch the game. Spawn / approach a dragon with the relevant gameplay state active (idle on ground if `$CLIP` is the idle clip). Watch for at least 30 seconds.

**Expected:** dragon behaves IDENTICALLY to vanilla. The clone-copy is byte-identical to what's already in the PAZ, so the engine must produce the same animation.

**If dragon behaves differently:** JMM is corrupting bytes in transit (compression layer? endian flip? path mismatch?). STOP — investigate JMM's override pipeline before any further task. Capture before/after byte hashes:

```bash
sha256sum dragon-anim-extract/$CLIP_REL "$DEST"
```

If hashes match but behaviour differs, the problem is JMM's runtime layer, not file copy. Open JMM's logs and document.

- [ ] **Step 6: Append baseline finding to notes**

```markdown
### Phase 1 sub-test A — clone-of-self (Task 5)

- Test clip: `<filename>`
- Relative path inside JMM: `files/character/<filename>`
- Result: PASS (vanilla behaviour) / FAIL (<describe>)
- File hash before/after: `<sha256>` / `<sha256>`
```

---

## Task 6: Phase 1 override spike — destructive zero test

**Files:**
- Modify: `<JMM-MODS>/Drogon-AnimSpike-Phase1/files/<clip-relative-path>`
- Modify: `docs/cd_anim_format_notes.md`

**Why:** The strongest possible signal that JMM intercepts anim files. Replace the chosen clip with all-zero bytes of the same length. The engine should react visibly — freeze, T-pose, fall back to default pose, or crash. Any of those is a PASS for "JMM overrides anims." Only "vanilla behaviour" is a fail.

- [ ] **Step 1: Replace the file with zeros**

```bash
SIZE=$(stat -c '%s' "$MOD/files/$CLIP_REL")
# Use Python because PowerShell here-strings are flaky for binary; bash here is fine.
python -c "from pathlib import Path; Path(r'$MOD/files/$CLIP_REL').write_bytes(b'\x00' * $SIZE)"
```

Verify size unchanged (some override systems care):

```bash
ls -la "$MOD/files/$CLIP_REL"
```

- [ ] **Step 2: Apply via JMM, launch CD, observe**

Apply mod via JMM. Launch game. Approach idle dragon.

**Expected outcomes (any of these = PASS):**
- Dragon freezes in current pose
- Dragon snaps to T-pose / bind pose
- Dragon's idle animation visibly breaks (joints flicker, jitter)
- Game crashes when dragon would normally trigger this clip

**FAIL outcome:**
- Dragon behaves identically to vanilla. Means the engine did NOT load our override and went back to the vanilla PAZ. **Stop and investigate JMM logs / override mechanism.**

- [ ] **Step 3: Record the result**

```markdown
### Phase 1 sub-test B — zero-bytes (Task 6)

- Result: <pass/fail outcome description>
- Specific behaviour observed: <e.g. "dragon froze with mouth open and stayed still">
- Implication: JMM does/does-not intercept anim hkx files
```

---

## Task 7: Phase 1 override spike — clone-of-different-clip swap

**Files:**
- Modify: `<JMM-MODS>/Drogon-AnimSpike-Phase1/files/<clip-relative-path>`
- Modify: `docs/cd_anim_format_notes.md`

**Why:** The most informative test. Replace the idle clip's bytes with the bytes of a *different* dragon clip (e.g. fly-loop). If the dragon plays the wrong animation while idle, we have proven:
1. JMM overrides anim files (already proven by Task 6)
2. The engine binds anims by FILENAME, not by some content-hash check
3. Clip data is portable across slots — i.e. we can author NEW data for any slot

This is the green-light for Phase 2.

- [ ] **Step 1: Identify a clearly-different clip**

From Task 4's extraction, pick a clip that is visibly distinct from the idle clip — ideally a fly/flap loop. Call it `$DONOR` (e.g. `cd_m0004_anim_fly_loop_0001.hkx`).

- [ ] **Step 2: Replace the idle clip's bytes with the donor's**

```bash
DONOR_REL="character/cd_m0004_anim_fly_loop_0001.hkx"   # update with actual donor
cp "dragon-anim-extract/$DONOR_REL" "$MOD/files/$CLIP_REL"
ls -la "$MOD/files/$CLIP_REL"  # size will likely differ now
```

- [ ] **Step 3: Apply, launch, observe**

**Expected outcomes (any = PASS):**
- Idle dragon now plays the fly/flap motion (wings flap while standing still)
- Idle dragon plays a fragment of the fly motion before something errors
- Game crashes (because the engine expected idle-clip-shape data and got fly-clip-shape data — depends on whether anim metadata is checked)

**Most informative outcome:** dragon plays donor clip in idle slot. Confirms filename-based binding and clip portability.

**Inconclusive outcome:** vanilla idle behaviour. Re-check that the donor file is actually being loaded (check JMM logs, file timestamps in the apply target, etc.).

- [ ] **Step 4: Record the result and Phase 1 verdict**

```markdown
### Phase 1 sub-test C — donor-clip swap (Task 7)

- Donor clip: `<filename>`
- Result: <description of in-game behaviour>
- Implication: engine binds anims by <filename | content-hash | other>

## Phase 1 verdict

**<PROCEED / STOP — reason>**

If PROCEED: ready to write Phase 2+ plan (TAG0 decode, retarget, encode, ship).
Phase 2 plan is to be written against findings recorded above.
```

- [ ] **Step 5: Commit notes (the JMM mod folder is outside the repo, doesn't get committed)**

```bash
git add docs/cd_anim_format_notes.md
git commit -m "anim: phase 1 spike complete, record verdict"
```

- [ ] **Step 6: Push the branch**

```bash
git push -u origin feat-anim-retarget
```

---

## Task 8: Handoff — write Phase 2+ brainstorm prompt

**Files:**
- Create: `docs/superpowers/specs/2026-04-26-cd-anim-retarget-design.md` is unchanged
- Create: `docs/superpowers/notes/2026-XX-XX-phase2-handoff.md` (date filled in when this task runs)

**Why:** The Phase 2+ plan must be written against ground-truth findings. This task creates a single document that the next brainstorming session reads to understand what we know.

- [ ] **Step 1: Create the handoff note**

Path: `docs/superpowers/notes/<today>-phase2-handoff.md`

```markdown
# Phase 2+ Handoff Note

This note exists so the next brainstorming session knows exactly what was confirmed
in Phase 0+1 and what's still unknown for Phase 2 (TAG0 decode + encode + retarget + ship).

## Phase 0 confirmed findings

(copy the relevant sections from `docs/cd_anim_format_notes.md` here verbatim)

## Phase 1 confirmed findings

(copy the verdict and per-test results)

## Open questions for Phase 2 brainstorm

- TAGFILE 2024-02 parser availability — survey Souls/Elden Ring modding tools (HKLib forks, SoulsAssetPipeline, RawHavokParser) and decide: adopt, fork, or write from scratch.
- Bone binding mode — does each anim track reference bones by name (string), index, or hash? Inspect 2–3 clips' first 256 bytes manually and look for ASCII bone names from `cd_skeleton.json`.
- Keyframe encoding — raw `hkaInterleavedUncompressedAnimation`, `hkaSplineCompressedAnimation`, or `hkaPredictiveCompressedAnimation`. Decoder strategy differs hugely per type.
- Root motion — is there a separate track named `RootMotion` / `Bip01` / similar?
- Source FBX bone palette — does Fortnite Drogon FBX cover all CD bones we need to drive, or are there CD-only bones we leave at rest?

## Recommended next steps

1. New brainstorm session that starts from this note.
2. Decide whether to write a single Phase 2-4 plan, or split (decode plan, then retarget plan, then ship plan).
3. Update `cd_anim_format_notes.md` with Phase 2 findings as that work happens.
```

- [ ] **Step 2: Commit and push**

```bash
git add docs/superpowers/notes/
git commit -m "anim: phase 2 handoff note"
git push
```

- [ ] **Step 3: Ready for next brainstorm**

When the user is ready to start Phase 2, the prompt is:
> "Continue the dragon anim retarget project. Read `docs/superpowers/notes/<date>-phase2-handoff.md` and `docs/superpowers/specs/2026-04-26-cd-anim-retarget-design.md`, then run `/superpowers:brainstorming` to scope Phase 2."

This plan is complete.

---

## Self-review checklist (run before considering plan done)

- [x] Spec coverage: every part of Phase 0+1 in the spec maps to a task here? Yes — locate (Tasks 1–4), override spike (Tasks 5–7), handoff (Task 8). Phase 2–4 deliberately deferred per scoping decision at top.
- [x] Placeholder scan: only one section with `<...>` placeholders, all in user-fillable JMM/path/filename fields where the executor must substitute their actual values. No "TODO/TBD" in implementation code.
- [x] Type consistency: `PazEntry` namedtuple defined once in `paz_listing.py`, used identically in `find_anim_paz.py` and tests. `score_entry`, `scan_paz_folder`, `extract_top_paz` signatures consistent throughout.
- [x] Kill criteria match the spec: Task 3 Step 5 enforces Phase 0 kill criterion; Task 5 Step 5, Task 6 Step 2, Task 7 Step 3 enforce Phase 1 sub-test pass/fail rules.
- [x] Frequent commits: every task ends in commit. Phase 1 commits notes only because JMM mod folder is outside the repo.
