"""Extract dragon-anim files from an identified PAZ to dragon-anim-extract/.

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
    """Extract every dragon-anim entry from the top-ranked PAZ in candidates_path.

    The top-ranked PAZ is defined as the one with the highest total score sum
    across all its entries.  The candidates JSON is insertion-ordered (written
    by find_anim_paz.py in alphabetical PAZ path order), so we cannot rely on
    key order — we must rank explicitly.

    Returns the number of files written.
    """
    candidates = json.loads(candidates_path.read_text())
    if not candidates:
        print("No candidates in JSON; nothing to extract.")
        return 0

    # Rank by total score across all entries in each PAZ.
    top_paz_rel = max(
        candidates,
        key=lambda paz: sum(e["score"] for e in candidates[paz]),
    )
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
