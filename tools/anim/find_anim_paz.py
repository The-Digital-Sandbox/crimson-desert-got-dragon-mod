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
