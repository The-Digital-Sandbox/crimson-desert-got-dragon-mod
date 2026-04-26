"""Read-only listing of CD PAZ archive contents via PAMT index.

PAZ format reality (learned from CrimsonForge/core/paz_reader.py):
  PAZ files are raw binary blobs — they contain NO internal directory structure.
  All file metadata (name, offset, size, compression flags) lives in a companion
  PAMT index file (``0.pamt``) located in the same directory as the PAZ files.

  The PAMT maps virtual paths → which PAZ file (by index) + byte offset + sizes.
  Multiple PAZ files in one directory share one 0.pamt index.

PAMT binary layout (little-endian):
  [0:4]    self_crc   — PaChecksum of data[12:]
  [4:8]    paz_count  — number of PAZ files described
  [8:12]   hash+zero  — 8 padding/hash bytes
  [12:]    PAZ table  — paz_count × (u32 checksum, u32 size, [u32 sep if not last])
           then → folder section (u32 size prefix, entries)
           then → node section  (u32 size prefix, entries)
           then → folder record count + hash + folder_count*16-byte records
           then → file records   — each 20 bytes:
                    u32 node_ref, u32 paz_offset, u32 comp_size, u32 orig_size, u32 flags
                  flags & 0xFF == paz_index (relative to pamt_stem)

This module ONLY reads the PAMT directory — no PAZ payloads are read,
so listing is fast and uses constant memory regardless of archive size.
"""

from __future__ import annotations

import os
import struct
from collections import namedtuple
from pathlib import Path
from typing import List

PazEntry = namedtuple("PazEntry", ["filename", "offset", "size"])


def list_paz_contents(paz_path: Path) -> List[PazEntry]:
    """Return all files whose data lives in *paz_path*, per the companion PAMT index.

    Reads ``<paz_dir>/0.pamt``, parses its directory table, and returns every
    entry whose resolved PAZ filename matches ``paz_path``. No file-payload bytes
    from the PAZ are ever read.

    Args:
        paz_path: Absolute path to a ``.paz`` file.

    Returns:
        List of :class:`PazEntry` (filename, offset, size). ``size`` is the
        uncompressed logical size; ``offset`` is the byte offset inside the
        PAZ file. Order matches the PAMT file-record order.

    Raises:
        FileNotFoundError: ``paz_path`` does not exist, or its companion
            ``0.pamt`` index is missing.
        ValueError: ``0.pamt`` cannot be parsed (truncated or unrecognised format).
    """
    paz_path = Path(paz_path)
    if not paz_path.exists():
        raise FileNotFoundError(f"PAZ not found: {paz_path}")

    paz_dir = paz_path.parent
    pamt_path = paz_dir / "0.pamt"
    if not pamt_path.exists():
        raise FileNotFoundError(
            f"PAMT index not found: {pamt_path}. "
            f"Each PAZ directory must contain 0.pamt alongside the .paz files."
        )

    paz_stem = paz_path.stem  # e.g. "3" for "3.paz"
    if not paz_stem.isdigit():
        raise ValueError(f"PAZ filename must be numeric (got {paz_path.name!r})")

    target_paz_num = int(paz_stem)

    # Parse the PAMT file
    data = pamt_path.read_bytes()
    entries = _parse_pamt(data, pamt_path, paz_dir)

    # Filter to entries belonging to this specific PAZ file
    paz_name = paz_path.name.lower()  # e.g. "3.paz"
    result: List[PazEntry] = []
    for path_str, offset, comp_size, orig_size, paz_file_path in entries:
        if os.path.basename(paz_file_path).lower() == paz_name:
            result.append(PazEntry(
                filename=path_str,
                offset=offset,
                size=orig_size,  # logical (uncompressed) size
            ))

    return result


# ---------------------------------------------------------------------------
# Internal PAMT parser — mirrors CrimsonForge/core/pamt_parser.py but with
# no external dependencies (no utils.logger, no dataclasses beyond namedtuple).
# ---------------------------------------------------------------------------

def _parse_pamt(
    data: bytes,
    pamt_path: Path,
    paz_dir: Path,
) -> list:
    """Parse a PAMT index and return a list of raw tuples.

    Returns:
        List of (path_str, offset, comp_size, orig_size, paz_file_abs_str)
    """
    if len(data) < 16:
        raise ValueError(f"PAMT too small to be valid: {len(data)} bytes")

    off = 0
    # [0:4] self CRC — we don't verify it here (CrimsonForge uses a custom checksum)
    off += 4
    # [4:8] paz_count
    paz_count = struct.unpack_from("<I", data, off)[0]; off += 4
    # [8:12] hash/zero padding
    off += 8  # skip hash + zero (8 bytes total: 4 bytes each)

    # PAZ table: paz_count entries of (u32 checksum, u32 size),
    # separated by a u32 separator between entries (not after the last).
    pamt_stem = int(pamt_path.stem)  # e.g. 0 for "0.pamt"
    paz_index_to_num: dict[int, int] = {}
    for i in range(paz_count):
        _checksum = struct.unpack_from("<I", data, off)[0]; off += 4
        _size = struct.unpack_from("<I", data, off)[0]; off += 4
        paz_index_to_num[i] = pamt_stem + i
        if i < paz_count - 1:
            off += 4  # separator u32 between entries

    # Folder section
    if off + 4 > len(data):
        raise ValueError("PAMT truncated before folder section")
    folder_size = struct.unpack_from("<I", data, off)[0]; off += 4
    folder_end = off + folder_size
    folder_prefix = ""
    while off < folder_end:
        if off + 5 > len(data):
            break
        parent = struct.unpack_from("<I", data, off)[0]
        slen = data[off + 4]
        if off + 5 + slen > len(data):
            break
        name = data[off + 5: off + 5 + slen].decode("utf-8", errors="replace")
        if parent == 0xFFFFFFFF:
            folder_prefix = name
        off += 5 + slen

    # Node section
    if off + 4 > len(data):
        raise ValueError("PAMT truncated before node section")
    node_size = struct.unpack_from("<I", data, off)[0]; off += 4
    node_start = off
    nodes: dict[int, tuple] = {}  # rel_offset → (parent_ref, name)
    while off < node_start + node_size:
        rel = off - node_start
        if off + 5 > len(data):
            break
        parent = struct.unpack_from("<I", data, off)[0]
        slen = data[off + 4]
        if off + 5 + slen > len(data):
            break
        name = data[off + 5: off + 5 + slen].decode("utf-8", errors="replace")
        nodes[rel] = (parent, name)
        off += 5 + slen

    def build_path(node_ref: int) -> str:
        parts = []
        cur = node_ref
        depth = 0
        while cur != 0xFFFFFFFF and depth < 64:
            if cur not in nodes:
                break
            parent_ref, name = nodes[cur]
            parts.append(name)
            cur = parent_ref
            depth += 1
        return "".join(reversed(parts))

    # Folder records block (folder_count + hash + folder_count * 16 bytes)
    if off + 8 > len(data):
        raise ValueError("PAMT truncated before folder records")
    folder_count = struct.unpack_from("<I", data, off)[0]; off += 4
    off += 4  # hash
    off += folder_count * 16

    # File records: 20 bytes each
    # u32 node_ref, u32 paz_offset, u32 comp_size, u32 orig_size, u32 flags
    results = []
    while off + 20 <= len(data):
        node_ref, paz_offset, comp_size, orig_size, flags = \
            struct.unpack_from("<IIIII", data, off)
        off += 20

        paz_index = flags & 0xFF
        node_path = build_path(node_ref)
        full_path = f"{folder_prefix}/{node_path}" if folder_prefix else node_path

        paz_num = pamt_stem + paz_index
        paz_file = str(paz_dir / f"{paz_num}.paz")

        results.append((full_path, paz_offset, comp_size, orig_size, paz_file))

    return results
