#!/usr/bin/env python3
"""
Deploy a new PAC (different size from original) by appending to the PAZ
and updating the PAMT + PAPGT checksums.

Usage:
    python tools/deploy_new_pac.py
    python tools/deploy_new_pac.py --restore
"""
import struct
import shutil
import sys
import os
import ctypes
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "output"

GAME_DIR = r"C:\Program Files (x86)\Steam\steamapps\common\Crimson Desert"
PAZ_DIR = os.path.join(GAME_DIR, "0009")
PAZ_FILE = os.path.join(PAZ_DIR, "3.paz")
PAMT_FILE = os.path.join(PAZ_DIR, "0.pamt")
PAPGT_FILE = os.path.join(GAME_DIR, "meta", "0.papgt")

# Original dragon PAC PAMT record
PAMT_RECORD_OFFSET = 0x64CB5C  # 20-byte record in 0.pamt
ORIG_PAC_OFFSET = 0x2DCAD1D0
ORIG_PAC_SIZE = 5_208_284

# PAPGT entry index for 0009 directory
PAPGT_ENTRY_INDEX = 9

NEW_PAC = OUTPUT / "dragon_drogon_final.pac"


# ── PA Jenkins Lookup3 checksum ──────────────────────────────────────

PA_MAGIC = 0x2145E233
_MASK = 0xFFFFFFFF


def _rotl(v, n):
    v &= _MASK
    return ((v << n) | (v >> (32 - n))) & _MASK


def _rotr(v, n):
    v &= _MASK
    return ((v >> n) | (v << (32 - n))) & _MASK


def pa_checksum(data: bytes) -> int:
    """PA Jenkins Lookup3 hash of data."""
    length = len(data)
    if length == 0:
        return 0

    a = b = c = (length - PA_MAGIC) & _MASK
    offset = 0
    remaining = length

    while remaining > 12:
        a = (a + struct.unpack_from('<I', data, offset)[0]) & _MASK
        b = (b + struct.unpack_from('<I', data, offset + 4)[0]) & _MASK
        c = (c + struct.unpack_from('<I', data, offset + 8)[0]) & _MASK

        a = (a - c) & _MASK; a ^= _rotl(c, 4);  c = (c + b) & _MASK
        b = (b - a) & _MASK; b ^= _rotl(a, 6);  a = (a + c) & _MASK
        c = (c - b) & _MASK; c ^= _rotl(b, 8);  b = (b + a) & _MASK
        a = (a - c) & _MASK; a ^= _rotl(c, 16); c = (c + b) & _MASK
        b = (b - a) & _MASK; b ^= _rotl(a, 19); a = (a + c) & _MASK
        c = (c - b) & _MASK; c ^= _rotl(b, 4);  b = (b + a) & _MASK

        offset += 12
        remaining -= 12

    if remaining >= 12: c = (c + (data[offset + 11] << 24)) & _MASK
    if remaining >= 11: c = (c + (data[offset + 10] << 16)) & _MASK
    if remaining >= 10: c = (c + (data[offset + 9] << 8)) & _MASK
    if remaining >= 9:  c = (c + data[offset + 8]) & _MASK
    if remaining >= 8:  b = (b + (data[offset + 7] << 24)) & _MASK
    if remaining >= 7:  b = (b + (data[offset + 6] << 16)) & _MASK
    if remaining >= 6:  b = (b + (data[offset + 5] << 8)) & _MASK
    if remaining >= 5:  b = (b + data[offset + 4]) & _MASK
    if remaining >= 4:  a = (a + (data[offset + 3] << 24)) & _MASK
    if remaining >= 3:  a = (a + (data[offset + 2] << 16)) & _MASK
    if remaining >= 2:  a = (a + (data[offset + 1] << 8)) & _MASK
    if remaining >= 1:  a = (a + data[offset]) & _MASK

    v82 = ((b ^ c) - _rotl(b, 14)) & _MASK
    v83 = ((a ^ v82) - _rotl(v82, 11)) & _MASK
    v84 = ((v83 ^ b) - _rotr(v83, 7)) & _MASK
    v85 = ((v84 ^ v82) - _rotl(v84, 16)) & _MASK
    v86 = _rotl(v85, 4)
    t   = ((v83 ^ v85) - v86) & _MASK
    v87 = ((t ^ v84) - _rotl(t, 14)) & _MASK

    return ((v87 ^ v85) - _rotr(v87, 8)) & _MASK


# ── Windows file time helpers ────────────────────────────────────────

def get_file_times(path):
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)

    class FILETIME(ctypes.Structure):
        _fields_ = [("lo", ctypes.c_uint32), ("hi", ctypes.c_uint32)]

    h = kernel32.CreateFileW(path, 0x80000000, 1, None, 3, 0x80, None)
    if h == -1:
        return None
    ct, at, mt = FILETIME(), FILETIME(), FILETIME()
    kernel32.GetFileTime(h, ctypes.byref(ct), ctypes.byref(at), ctypes.byref(mt))
    kernel32.CloseHandle(h)
    return ct, at, mt


def set_file_times(path, ct, at, mt):
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    h = kernel32.CreateFileW(path, 0x40000000, 0, None, 3, 0x80, None)
    if h != -1:
        kernel32.SetFileTime(h, ctypes.byref(ct), ctypes.byref(at), ctypes.byref(mt))
        kernel32.CloseHandle(h)


# ── Deploy / Restore ─────────────────────────────────────────────────

def backup_file(path, suffix=".drogon_bak"):
    bak = path + suffix
    if not os.path.exists(bak):
        shutil.copy2(path, bak)
        print(f"  Backed up {os.path.basename(path)}")


def deploy():
    pac_data = NEW_PAC.read_bytes()
    pac_size = len(pac_data)

    print(f"Deploying Drogon PAC: {pac_size:,} bytes")

    # 1. Backups
    backup_file(PAMT_FILE)
    backup_file(PAPGT_FILE)

    # 2. Append PAC to end of PAZ
    paz_times = get_file_times(PAZ_FILE)
    paz_size = os.path.getsize(PAZ_FILE)
    new_offset = paz_size

    with open(PAZ_FILE, 'ab') as f:
        f.write(pac_data)
    if paz_times:
        set_file_times(PAZ_FILE, *paz_times)

    print(f"  PAZ: appended at 0x{new_offset:08X}")

    # 3. Update PAMT record (offset + sizes) and PazInfo file size
    pamt = bytearray(Path(PAMT_FILE).read_bytes())
    new_paz_size = os.path.getsize(PAZ_FILE)

    old_offset = struct.unpack_from('<I', pamt, PAMT_RECORD_OFFSET + 8)[0]
    old_size = struct.unpack_from('<I', pamt, PAMT_RECORD_OFFSET + 12)[0]

    struct.pack_into('<I', pamt, PAMT_RECORD_OFFSET + 8, new_offset)
    struct.pack_into('<I', pamt, PAMT_RECORD_OFFSET + 12, pac_size)
    struct.pack_into('<I', pamt, PAMT_RECORD_OFFSET + 16, pac_size)

    print(f"  PAMT record: offset 0x{old_offset:08X}->{new_offset:08X}, "
          f"size {old_size:,}->{pac_size:,}")

    # Update PazInfo entry for 3.paz file size
    # PazInfo: starts at offset 12, each entry 12 bytes [Index:u32, Crc:u32, FileSize:u32]
    paz_count = struct.unpack_from('<I', pamt, 4)[0]
    for pi in range(paz_count):
        paz_info_off = 12 + pi * 12
        paz_idx = struct.unpack_from('<I', pamt, paz_info_off)[0]
        if paz_idx == 3:  # our PAZ file
            old_paz_size = struct.unpack_from('<I', pamt, paz_info_off + 8)[0]
            struct.pack_into('<I', pamt, paz_info_off + 8, new_paz_size)
            print(f"  PazInfo[3] size: {old_paz_size:,} -> {new_paz_size:,}")
            break

    # 4. Recompute PAMT HeaderCrc = pa_checksum(pamt[12:])
    new_pamt_crc = pa_checksum(bytes(pamt[12:]))
    old_pamt_crc = struct.unpack_from('<I', pamt, 0)[0]
    struct.pack_into('<I', pamt, 0, new_pamt_crc)

    print(f"  PAMT checksum: 0x{old_pamt_crc:08X} -> 0x{new_pamt_crc:08X}")

    pamt_times = get_file_times(PAMT_FILE)
    Path(PAMT_FILE).write_bytes(pamt)
    if pamt_times:
        set_file_times(PAMT_FILE, *pamt_times)

    # 5. Update PAPGT: entry 9 PamtCrc + PAPGT FileCrc
    papgt = bytearray(Path(PAPGT_FILE).read_bytes())

    # Entry 9 hash field: offset 0x0C + 9*12 + 8
    entry_hash_offset = 0x0C + PAPGT_ENTRY_INDEX * 12 + 8
    old_entry_hash = struct.unpack_from('<I', papgt, entry_hash_offset)[0]
    struct.pack_into('<I', papgt, entry_hash_offset, new_pamt_crc)

    print(f"  PAPGT entry[{PAPGT_ENTRY_INDEX}]: 0x{old_entry_hash:08X} -> 0x{new_pamt_crc:08X}")

    # Recompute PAPGT FileCrc = pa_checksum(papgt[12:])
    #   (PAPGT header: u16 version + u16 pad @ 0, u32 FileCrc @ 4, u32 count_info @ 8)
    #   But from verification: FileCrc is at bytes 4-7, computed from papgt[12:]
    #   Actually let me check: the PAPGT structure has first 8 bytes as header
    #   Wait - we verified pa_checksum(papgt[12:]) matches papgt[4:8]. So:
    #   papgt[0:4] = version/size, papgt[4:8] = FileCrc, papgt[8:12] = count+flags
    new_papgt_crc = pa_checksum(bytes(papgt[12:]))
    old_papgt_crc = struct.unpack_from('<I', papgt, 4)[0]
    struct.pack_into('<I', papgt, 4, new_papgt_crc)

    print(f"  PAPGT checksum: 0x{old_papgt_crc:08X} -> 0x{new_papgt_crc:08X}")

    papgt_times = get_file_times(PAPGT_FILE)
    Path(PAPGT_FILE).write_bytes(papgt)
    if papgt_times:
        set_file_times(PAPGT_FILE, *papgt_times)

    print(f"\n  Deploy complete. PAZ: {os.path.getsize(PAZ_FILE):,} bytes")
    return True


def restore():
    restored = False

    for path in [PAMT_FILE, PAPGT_FILE]:
        bak = path + ".drogon_bak"
        if os.path.exists(bak):
            times = get_file_times(path)
            shutil.copy2(bak, path)
            if times:
                set_file_times(path, *times)
            print(f"Restored {os.path.basename(path)}")
            restored = True

    if restored:
        print("Note: PAZ still has appended data (harmless).")
        print("Steam 'Verify integrity' to fully restore PAZ size.")
    else:
        print("ERROR: No backups found. Run Steam verify.")
    return restored


if __name__ == '__main__':
    if '--restore' in sys.argv:
        restore()
    else:
        deploy()
