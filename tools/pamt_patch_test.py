#!/usr/bin/env python3
"""
PAMT zeroing test — zero the per-vertex data in the encrypted PAMT and deploy.

Pipeline: decrypt original -> decompress -> zero vertex region -> recompress -> re-encrypt -> patch PAZ
"""

import struct
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'cd-unpacker', 'python'))
from paz_crypto import decrypt, lz4_decompress
from paz_parse import parse_pamt

import lz4.block

# Paths
PAZ_DIR = r"C:\Program Files (x86)\Steam\steamapps\common\Crimson Desert\0009"
PAZ_FILE = os.path.join(PAZ_DIR, "3.paz")
PAMT_OFFSET = 0x2E1896D0
PAMT_COMP_SIZE = 296563
PAMT_ORIG_SIZE = 1326145
PAMT_FILENAME = "cd_m0004_00_dragon_00_0001.pamt"

# Vertex data region within decompressed PAMT
VERTEX_DATA_START = 0x2F41  # stride-48 data starts here
VERTEX_STRIDE = 48
VERTEX_COUNT = 27376


def read_original_pamt():
    """Read and decrypt+decompress the original PAMT."""
    with open(PAZ_FILE, 'rb') as f:
        f.seek(PAMT_OFFSET)
        raw = f.read(PAMT_COMP_SIZE)

    # Decrypt
    decrypted = decrypt(raw, PAMT_FILENAME)
    # Decompress
    decompressed = lz4_decompress(decrypted, PAMT_ORIG_SIZE)
    return raw, decompressed


def encrypt_and_compress(modified_data, original_raw):
    """Re-compress and re-encrypt modified PAMT data.

    CRITICAL: Must produce exactly the same compressed size as original
    to avoid shifting all subsequent data in the PAZ.
    """
    # Re-compress with LZ4 block
    compressed = lz4.block.compress(modified_data, store_size=False)

    # Re-encrypt with ChaCha20
    # The decrypt function is its own inverse for ChaCha20 (XOR cipher)
    encrypted = decrypt(compressed, PAMT_FILENAME)

    return encrypted


def deploy_pamt(encrypted_data):
    """Patch the encrypted PAMT data into the PAZ."""
    if len(encrypted_data) > PAMT_COMP_SIZE:
        print(f"WARNING: Compressed data ({len(encrypted_data)}) > original ({PAMT_COMP_SIZE})!")
        print(f"This will overwrite adjacent data. Aborting for safety.")
        return False

    # Pad to original size if shorter (safe — game reads exact comp_size bytes)
    padded = encrypted_data + b'\x00' * (PAMT_COMP_SIZE - len(encrypted_data))

    with open(PAZ_FILE, 'r+b') as f:
        f.seek(PAMT_OFFSET)
        f.write(padded)

    print(f"Deployed {len(encrypted_data)} bytes (padded to {PAMT_COMP_SIZE}) at 0x{PAMT_OFFSET:X}")
    return True


def restore_pamt(original_raw):
    """Restore original PAMT data."""
    with open(PAZ_FILE, 'r+b') as f:
        f.seek(PAMT_OFFSET)
        f.write(original_raw)
    print(f"Restored original PAMT ({len(original_raw)} bytes)")


def main():
    if len(sys.argv) < 2:
        print("Usage: pamt_patch_test.py <test> [--deploy]")
        print("\nTests:")
        print("  zero_verts   - Zero all per-vertex data (keep bone table + transforms)")
        print("  zero_all     - Zero entire PAMT (nuclear option)")
        print("  restore      - Restore original PAMT")
        print("  verify       - Decrypt and verify round-trip")
        return

    test = sys.argv[1]
    do_deploy = '--deploy' in sys.argv

    if test == 'restore':
        # Read original from our saved backup
        backup = os.path.join(os.path.dirname(__file__), '..', 'output', 'dragon_mesh_pamt.raw')
        with open(backup, 'rb') as f:
            original_raw = f.read()
        restore_pamt(original_raw)
        print("PAMT restored.")
        return

    if test == 'verify':
        print("Reading and decrypting PAMT...")
        original_raw, decompressed = read_original_pamt()
        print(f"Original compressed: {len(original_raw)} bytes")
        print(f"Decompressed: {len(decompressed)} bytes")
        print(f"Magic: {decompressed[:4]}")

        # Round-trip test
        print("\nRound-trip test (compress -> encrypt -> decrypt -> decompress)...")
        encrypted = encrypt_and_compress(decompressed, original_raw)
        print(f"Re-encrypted: {len(encrypted)} bytes (original: {len(original_raw)})")

        # Verify by decrypting again
        decrypted2 = decrypt(encrypted, PAMT_FILENAME)
        decompressed2 = lz4_decompress(decrypted2, PAMT_ORIG_SIZE)
        if decompressed2 == decompressed:
            print("ROUND-TRIP VERIFIED: data matches!")
        else:
            print("ROUND-TRIP FAILED: data mismatch!")
            # Find first difference
            for i in range(min(len(decompressed), len(decompressed2))):
                if decompressed[i] != decompressed2[i]:
                    print(f"  First difference at byte {i}")
                    break
        return

    # Read original
    print("Reading original PAMT...")
    original_raw, decompressed = read_original_pamt()
    modified = bytearray(decompressed)

    if test == 'zero_verts':
        print(f"Zeroing vertex data: offset 0x{VERTEX_DATA_START:X} to end ({VERTEX_COUNT * VERTEX_STRIDE:,} bytes)")
        for i in range(VERTEX_DATA_START, len(modified)):
            modified[i] = 0

    elif test == 'zero_all':
        print(f"Zeroing ENTIRE PAMT (keeping PAR magic)")
        for i in range(4, len(modified)):
            modified[i] = 0

    else:
        print(f"Unknown test: {test}")
        return

    # Save modified for inspection
    out_path = os.path.join(os.path.dirname(__file__), '..', 'output', f'pamt_test_{test}.bin')
    with open(out_path, 'wb') as f:
        f.write(modified)
    print(f"Saved modified PAMT: {out_path}")

    if do_deploy:
        print("Encrypting and compressing...")
        encrypted = encrypt_and_compress(bytes(modified), original_raw)
        print(f"Compressed size: {len(encrypted)} (original: {PAMT_COMP_SIZE})")

        if deploy_pamt(encrypted):
            print("\n>>> Launch Crimson Desert and check the dragon! <<<")
            print(">>> Run 'pamt_patch_test.py restore' when done <<<")
    else:
        print(f"\nAdd --deploy to patch game files.")


if __name__ == '__main__':
    main()
