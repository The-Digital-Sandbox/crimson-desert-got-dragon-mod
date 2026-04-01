#!/usr/bin/env python3
"""
Scan the 0009/0.pamt index for ALL dragon-related file entries.

Goal: find the second dragon mesh PAC that feeds the 8054 alternate
render pass (24,117 vertices at firstElement 3168 in resource 16288).

Usage:
    python tools/scan_pamt_dragon_entries.py
    python tools/scan_pamt_dragon_entries.py --all   # show ALL entries, not just dragon
"""

import struct
import sys
import os
from pathlib import Path

# Try to import from the repo's pamt_patcher_lib
sys.path.insert(0, str(Path(__file__).parent))
from pamt_patcher_lib import read_pamt_raw, resolve_filename

GAME_DIR = r"C:\Program Files (x86)\Steam\steamapps\common\Crimson Desert"
PAZ_DIR = os.path.join(GAME_DIR, "0009")
PAMT_FILE = os.path.join(PAZ_DIR, "0.pamt")

# Known dragon PAC record for reference
KNOWN_PAC_RECORD_OFFSET = 0x64CB5C
KNOWN_PAC_PAZ_OFFSET = 0x2DCAD1D0
KNOWN_PAC_SIZE = 5_208_284

# Known PAMT companion (from pamt_patch_test.py)
KNOWN_PAMT_PAZ_OFFSET = 0x2E1896D0
KNOWN_PAMT_COMP_SIZE = 296_563


def scan_entries(show_all=False):
    print(f"Reading PAMT: {PAMT_FILE}")
    print(f"File size: {os.path.getsize(PAMT_FILE):,} bytes")
    print()

    info = read_pamt_raw(PAMT_FILE)
    fn_data = info['fn_data']

    # Get dir block for directory resolution
    dir_data = info['raw'][
        info['dir_block_offset'] + 4:
        info['dir_block_offset'] + 4 + info['dir_block_size']
    ]

    # Build dir_path lookup from hash entries
    from pamt_patcher_lib import resolve_dirname
    dir_paths = {}
    for he in info['hash_entries']:
        dir_path = resolve_dirname(dir_data, he['name_offset'])
        dir_paths[he['folder_hash']] = (dir_path, he)

    print(f"PAZ count: {info['paz_count']}")
    print(f"File records: {info['file_count']}")
    print(f"Dir entries: {len(info['hash_entries'])}")
    print()

    # Scan all file records and resolve full paths
    dragon_entries = []
    all_entries = []

    fr_offset = info['file_records_offset'] + 4
    for idx in range(info['file_count']):
        fr = info['file_records'][idx]
        fname = resolve_filename(fn_data, fr['name_offset'])

        # Find directory for this file
        full_path = fname  # fallback
        for he in info['hash_entries']:
            if he['file_start_index'] <= idx < he['file_start_index'] + he['file_count']:
                dir_hash = he['folder_hash']
                if dir_hash in dir_paths:
                    dir_path = dir_paths[dir_hash][0]
                    full_path = (dir_path + '/' + fname) if dir_path else fname
                break

        entry_info = {
            'index': idx,
            'path': full_path,
            'paz_index': fr['paz_index'],
            'paz_offset': fr['paz_offset'],
            'comp_size': fr['comp_size'],
            'decomp_size': fr['decomp_size'],
            'flags': fr['flags'],
            'byte_offset': fr['_byte_offset'],
        }
        all_entries.append(entry_info)

        # Check if dragon-related
        if 'dragon' in full_path.lower() or 'cd_m0004' in full_path.lower():
            dragon_entries.append(entry_info)

    if show_all:
        print(f"=== ALL {len(all_entries)} ENTRIES ===")
        for e in all_entries:
            print(f"  [{e['index']:5d}] paz:{e['paz_index']} "
                  f"@0x{e['paz_offset']:08X} "
                  f"comp={e['comp_size']:>10,} "
                  f"decomp={e['decomp_size']:>10,} "
                  f"flags=0x{e['flags']:04X} "
                  f"record@0x{e['byte_offset']:06X} "
                  f"{e['path']}")
        print()

    print(f"=== DRAGON ENTRIES ({len(dragon_entries)}) ===")
    print()
    for e in dragon_entries:
        # Annotate known entries
        annotation = ""
        if e['paz_offset'] == KNOWN_PAC_PAZ_OFFSET:
            annotation = "  <-- KNOWN PAC (patched by mod)"
        elif e['paz_offset'] == KNOWN_PAMT_PAZ_OFFSET:
            annotation = "  <-- KNOWN PAMT COMPANION (NOT patched!)"
        elif e['comp_size'] > 1_000_000 and e['path'].endswith(('.pac', '.pacb')):
            annotation = "  <-- CANDIDATE SECOND MESH?"

        print(f"  [{e['index']:5d}] paz:{e['paz_index']} "
              f"@0x{e['paz_offset']:08X} "
              f"comp={e['comp_size']:>10,} "
              f"decomp={e['decomp_size']:>10,} "
              f"flags=0x{e['flags']:04X} "
              f"record@0x{e['byte_offset']:06X}")
        print(f"         {e['path']}{annotation}")
        print()

    # Also look for entries near the known PAC record offset
    # to find neighboring files in the same directory
    print(f"=== ENTRIES NEAR KNOWN PAC RECORD (0x{KNOWN_PAC_RECORD_OFFSET:06X}) ===")
    print()
    for e in all_entries:
        if abs(e['byte_offset'] - KNOWN_PAC_RECORD_OFFSET) <= 200:  # within 10 records
            marker = " <<<" if e['byte_offset'] == KNOWN_PAC_RECORD_OFFSET else ""
            print(f"  [{e['index']:5d}] record@0x{e['byte_offset']:06X} "
                  f"paz:{e['paz_index']} @0x{e['paz_offset']:08X} "
                  f"comp={e['comp_size']:>10,} "
                  f"decomp={e['decomp_size']:>10,} "
                  f"flags=0x{e['flags']:04X}{marker}")
            print(f"         {e['path']}")

    # Summary of file types found for dragon
    print()
    print("=== DRAGON FILE EXTENSIONS ===")
    exts = {}
    for e in dragon_entries:
        ext = os.path.splitext(e['path'])[1]
        if ext not in exts:
            exts[ext] = []
        exts[ext].append(e)
    for ext in sorted(exts):
        print(f"  {ext}: {len(exts[ext])} files")
        for e in exts[ext]:
            size_str = f"comp={e['comp_size']:,} decomp={e['decomp_size']:,}"
            print(f"    {e['path']}  ({size_str})")


if __name__ == '__main__':
    show_all = '--all' in sys.argv
    scan_entries(show_all)
