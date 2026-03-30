"""GoT/HotD Dragon Reskin for Crimson Desert.

Converts Game of Thrones / House of the Dragon texture mods (from Skyrim)
to Crimson Desert's format and patches them into PAZ archives.

Requires: texconv.exe in PATH or same directory, plus paz_parse/paz_crypto
from https://github.com/lazorr410/crimson-desert-unpacker

Usage:
    python dragon_reskin.py --dragon drogon --game-dir "C:/Program Files (x86)/Steam/steamapps/common/Crimson Desert"
    python dragon_reskin.py --dragon dreamfyre --game-dir "..." --dry-run
    python dragon_reskin.py --list-dragons
    python dragon_reskin.py --restore  # restore original textures from backup
"""

import os
import sys
import shutil
import struct
import subprocess
import argparse
import json
from pathlib import Path
from datetime import datetime

# Add the unpacker to path
SCRIPT_DIR = Path(__file__).parent
UNPACKER_DIR = SCRIPT_DIR.parent.parent / "cd-unpacker" / "python"
sys.path.insert(0, str(UNPACKER_DIR))

from paz_parse import parse_pamt, PazEntry

# ── Configuration ────────────────────────────────────────────────────

TEXCONV = shutil.which("texconv") or str(SCRIPT_DIR.parent.parent / "texconv.exe")

GOT_TEXTURES_DIR = SCRIPT_DIR.parent.parent / "got-dragon-mod" / "textures"
HOTD_TEXTURES_DIR = SCRIPT_DIR.parent.parent / "got-dragon-mod" / "hotd-textures"

# CD dragon texture entries in archive 0009
CD_ARCHIVE = "0009"
CD_PAMT = "0.pamt"

# Mapping: CD texture name -> (type, resolution, dds_format, mip_count)
CD_DRAGON_TEXTURES = {
    "cd_m0004_00_dragon_body_0001.dds":      ("baseColor", 2048, "DXT1", 12),
    "cd_m0004_00_dragon_body_0001_n.dds":    ("normal",    2048, "DXT5", 12),
    "cd_m0004_00_dragon_body_0001_sp.dds":   ("specular",  2048, "DXT1", 12),
    "cd_m0004_00_dragon_body_0001_disp.dds": ("height",    2048, "DXT1", 12),
    "cd_m0004_00_dragon_back_0001.dds":      ("baseColor", 2048, "DXT1", 12),
    "cd_m0004_00_dragon_back_0001_n.dds":    ("normal",    2048, "DXT5", 12),
    "cd_m0004_00_dragon_back_0001_sp.dds":   ("specular",  2048, "DXT1", 12),
    "cd_m0004_00_dragon_back_0001_disp.dds": ("height",    2048, "DXT1", 12),
    "cd_m0004_00_dragon_head_0001.dds":      ("baseColor", 2048, "DXT1", 12),
    "cd_m0004_00_dragon_head_0001_n.dds":    ("normal",    2048, "DXT5", 12),
    "cd_m0004_00_dragon_head_0001_sp.dds":   ("specular",  2048, "DXT1", 12),
    "cd_m0004_00_dragon_head_0001_disp.dds": ("height",    2048, "DXT1", 12),
    "cd_m0004_00_dragon_leg_0001.dds":       ("baseColor", 2048, "DXT1", 12),
    "cd_m0004_00_dragon_leg_0001_n.dds":     ("normal",    2048, "DXT5", 12),
    "cd_m0004_00_dragon_leg_0001_sp.dds":    ("specular",  2048, "DXT1", 12),
    "cd_m0004_00_dragon_leg_0001_disp.dds":  ("height",    2048, "DXT1", 12),
    "cd_m0004_00_dragon_wing_0001.dds":      ("baseColor", 2048, "DXT1", 12),
    "cd_m0004_00_dragon_wing_0001_n.dds":    ("normal",    2048, "DXT5", 12),
    "cd_m0004_00_dragon_wing_0001_sp.dds":   ("specular",  2048, "DXT1", 12),
    "cd_m0004_00_dragon_wing_0001_disp.dds": ("height",    2048, "DXT1", 12),
    "cd_m0004_00_dragon_eye_0001.dds":       ("baseColor",  512, "DXT1", 10),
    "cd_m0004_00_dragon_eye_0001_n.dds":     ("normal",     512, "DXT5", 10),
    "cd_m0004_00_dragon_eye_0001_sp.dds":    ("specular",   512, "DXT1", 10),
}

# GoT/HotD dragon definitions: name -> {source_dir, texture_mapping}
# Mapping: CD body part -> GoT source texture basename (without _d/_n suffix)
DRAGONS = {
    # === Game of Thrones (Original Skyrim Textures) ===
    "drogon": {
        "display_name": "Drogon (GoT)",
        "source_dir": GOT_TEXTURES_DIR / "GoT Dragons-Textures" / "textures" / "Drogon",
        "mapping": {
            "body":  "Body",
            "back":  "Body",       # GoT uses single body texture
            "head":  "Body",       # mapped from body
            "leg":   "Body",
            "wing":  "Body",
            "eye":   "eyes",
        },
        "source_textures": {
            "Body_d":  "baseColor",
            "Body_n":  "normal",
        },
    },
    "rhaegal": {
        "display_name": "Rhaegal (GoT)",
        "source_dir": GOT_TEXTURES_DIR / "GoT Dragons-Textures" / "textures" / "Rhaegal",
        "mapping": {
            "body":  "Rhaegal",
            "back":  "Rhaegal",
            "head":  "Rhaegal",
            "leg":   "Rhaegal",
            "wing":  "Rhaegal_wings",
            "eye":   "eyes",
        },
    },
    "viserion": {
        "display_name": "Viserion (GoT)",
        "source_dir": GOT_TEXTURES_DIR / "GoT Dragons-Textures" / "textures" / "Viserion",
        "mapping": {
            "body":  "Viserion",
            "back":  "Viserion",
            "head":  "Viserion",
            "leg":   "Viserion",
            "wing":  "Viserion_wings",
            "eye":   "eyes",
        },
    },
    # === House of the Dragon (Season 2, 4K) ===
    "dreamfyre": {
        "display_name": "Dreamfyre (HotD S2)",
        "source_dir": HOTD_TEXTURES_DIR / "textures" / "Dreamfyre",
        "mapping": {
            "body":  "Dreamfyre",
            "back":  "scales",
            "head":  "Dreamfyre",
            "leg":   "Dreamfyre",
            "wing":  "wings_translucency",
            "eye":   "eyes",
        },
    },
    "seasmoke": {
        "display_name": "Seasmoke (HotD S2)",
        "source_dir": HOTD_TEXTURES_DIR / "textures" / "Seasmoke",
        "mapping": {
            "body":  "Seasmoke",
            "back":  "scales",
            "head":  "Seasmoke",
            "leg":   "Seasmoke",
            "wing":  "white_frills",
            "eye":   "eyes",
        },
    },
    "silverwing": {
        "display_name": "Silverwing (HotD S2)",
        "source_dir": HOTD_TEXTURES_DIR / "textures" / "Silverwing",
        "mapping": {
            "body":  "Silverwing",
            "back":  "scales",
            "head":  "Silverwing",
            "leg":   "Silverwing",
            "wing":  "white_frills",
            "eye":   "eyes",
        },
    },
    "sunfyre": {
        "display_name": "Sunfyre (HotD S2)",
        "source_dir": HOTD_TEXTURES_DIR / "textures" / "Sunfyre",
        "mapping": {
            "body":  "sunfyre",  # note: lowercase in mod files
            "back":  "scales",
            "head":  "sunfyre",
            "leg":   "sunfyre",
            "wing":  "wings_translucency",
            "eye":   "eyes",
        },
    },
    "vermithor": {
        "display_name": "Vermithor (HotD S2)",
        "source_dir": HOTD_TEXTURES_DIR / "textures" / "Vermithor",
        "mapping": {
            "body":  "vermithor",
            "back":  "scales",
            "head":  "vermithor",
            "leg":   "vermithor",
            "wing":  "wings_translucency",
            "eye":   "eyes",
        },
    },
    "moondancer": {
        "display_name": "Moondancer (HotD S2)",
        "source_dir": HOTD_TEXTURES_DIR / "textures" / "Moondancer",
        "mapping": {
            "body":  "Moondancer",
            "back":  "scales",
            "head":  "Moondancer",
            "leg":   "Moondancer",
            "wing":  "wings_translucency",
            "eye":   "eyes",
        },
    },
}


# ── Texture Conversion ────────────────────────────────────────────────

def find_source_texture(dragon_def: dict, part: str, tex_type: str) -> Path | None:
    """Find the source texture file for a given dragon part and texture type.

    Searches for common naming patterns: Name_d.dds, Name_n.dds, Name.dds
    """
    source_dir = Path(dragon_def["source_dir"])
    mapping = dragon_def["mapping"]

    if part not in mapping:
        return None

    base_name = mapping[part]

    # Suffix patterns for each texture type
    suffixes = {
        "baseColor": ["_d", ""],
        "normal":    ["_n"],
        "specular":  ["_sp", "_s", "_d"],  # fallback to diffuse for specular
        "height":    ["_disp", "_h", "_d"],  # fallback to diffuse for height
    }

    for suffix in suffixes.get(tex_type, [""]):
        for ext in [".dds", ".DDS"]:
            candidate = source_dir / f"{base_name}{suffix}{ext}"
            if candidate.exists():
                return candidate

    # Search recursively in source_dir
    for suffix in suffixes.get(tex_type, [""]):
        for ext in [".dds", ".DDS"]:
            pattern = f"**/{base_name}{suffix}{ext}"
            matches = list(source_dir.glob(pattern))
            if not matches:
                # Try case-insensitive by globbing everything
                pattern_ci = f"**/*{ext}"
                target = f"{base_name}{suffix}".lower()
                matches = [p for p in source_dir.glob(pattern_ci)
                          if p.stem.lower() == target]
            if matches:
                return matches[0]

    return None


def convert_texture(source: Path, output: Path, target_format: str,
                    target_size: int, target_mips: int) -> bool:
    """Convert a texture to the target format using texconv."""
    output.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        TEXCONV,
        "-f", target_format,
        "-w", str(target_size),
        "-h", str(target_size),
        "-m", str(target_mips),
        "-if", "CUBIC",      # high quality downscale filter
        "-srgbi",             # assume sRGB input
        "-y",                 # overwrite
        "-o", str(output.parent),
        "-px", "",
        str(source),
    ]

    # For normal maps, don't use sRGB
    if "normal" in str(output).lower() or "_n." in str(output).lower():
        cmd = [c for c in cmd if c != "-srgbi"]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            print(f"  texconv error: {result.stderr[:200]}")
            return False

        # texconv outputs with the same filename as input, rename if needed
        converted = output.parent / source.name
        if converted.exists() and converted != output:
            shutil.move(str(converted), str(output))
        elif not output.exists():
            # texconv may have used the stem only
            for f in output.parent.glob(f"{source.stem}.*"):
                if f.suffix.lower() == ".dds":
                    shutil.move(str(f), str(output))
                    break

        return output.exists()
    except Exception as e:
        print(f"  Conversion error: {e}")
        return False


def verify_dds(path: Path, expected_format: str, expected_size: int,
               expected_mips: int) -> tuple[bool, str]:
    """Verify a DDS file matches expected parameters."""
    if not path.exists():
        return False, "file not found"

    with open(path, 'rb') as f:
        magic = f.read(4)
        if magic != b'DDS ':
            return False, f"not a DDS file (magic: {magic!r})"
        hdr = f.read(124)

    _, _, height, width, _, _, mips = struct.unpack_from('<7I', hdr, 0)
    fourcc = hdr[80:84]

    format_map = {b'DXT1': "DXT1", b'DXT5': "DXT5", b'DX10': "DX10"}
    actual_format = format_map.get(fourcc, fourcc.hex())

    issues = []
    if width != expected_size or height != expected_size:
        issues.append(f"size {width}x{height} != {expected_size}x{expected_size}")
    if mips != expected_mips:
        issues.append(f"mips {mips} != {expected_mips}")
    if actual_format != expected_format:
        issues.append(f"format {actual_format} != {expected_format}")

    if issues:
        return False, "; ".join(issues)
    return True, "OK"


# ── PAZ Patching ──────────────────────────────────────────────────────

def _strip_mips_to_fit(dds_data: bytes, orig_size: int, comp_size: int) -> bytes:
    """Zero out lower mip levels in DDS data to improve LZ4 compressibility.

    Lower mips are tiny and zeroing them creates long runs of 0x00 which
    LZ4 compresses extremely well, reducing the compressed output size.
    """
    import lz4.block

    result = bytearray(dds_data)
    # Zero from the end (lowest mips) backwards until it fits
    chunk = len(result) // 8  # start by zeroing the last 1/8th
    while chunk >= 64:
        trial = bytes(result)
        trial = trial[:len(trial) - chunk] + b'\x00' * chunk
        if len(trial) < orig_size:
            trial = trial + b'\x00' * (orig_size - len(trial))
        else:
            trial = trial[:orig_size]
        compressed = lz4.block.compress(trial, store_size=False)
        if len(compressed) <= comp_size:
            return trial
        chunk = chunk + chunk // 2  # zero more aggressively
    return bytes(result[:orig_size])


def backup_texture(entry: PazEntry, backup_dir: Path) -> Path:
    """Backup original texture data from PAZ archive."""
    backup_path = backup_dir / entry.path.replace('/', os.sep)
    if backup_path.exists():
        return backup_path  # already backed up

    backup_path.parent.mkdir(parents=True, exist_ok=True)
    with open(entry.paz_file, 'rb') as f:
        f.seek(entry.offset)
        data = f.read(entry.comp_size)

    with open(backup_path, 'wb') as f:
        f.write(data)
    return backup_path


def patch_texture(entry: PazEntry, texture_path: Path) -> bool:
    """Patch a converted texture into the PAZ archive.

    Handles LZ4-compressed entries by compressing the new texture data
    to fit within the original comp_size slot.
    """
    import lz4.block

    with open(texture_path, 'rb') as f:
        new_data = f.read()

    if entry.compressed and entry.compression_type == 2:
        # Entry is LZ4 compressed — we need to:
        # 1. Ensure new_data matches orig_size (pad/truncate the decompressed data)
        # 2. LZ4 compress it
        # 3. Ensure compressed output fits in comp_size slot
        if len(new_data) > entry.orig_size:
            new_data = new_data[:entry.orig_size]
        elif len(new_data) < entry.orig_size:
            new_data = new_data + b'\x00' * (entry.orig_size - len(new_data))

        compressed = lz4.block.compress(new_data, store_size=False)
        if len(compressed) > entry.comp_size:
            # Try higher compression or truncate mips to fit
            print(f"  WARNING: compressed {len(compressed)} > slot {entry.comp_size}, "
                  f"stripping lower mips to fit")
            # Strip lower mip levels from the DDS to reduce size
            new_data = _strip_mips_to_fit(new_data, entry.orig_size, entry.comp_size)
            compressed = lz4.block.compress(new_data, store_size=False)
            if len(compressed) > entry.comp_size:
                compressed = compressed[:entry.comp_size]

        # Pad compressed data to exactly comp_size
        new_data = compressed + b'\x00' * (entry.comp_size - len(compressed))
    else:
        # Uncompressed entry
        target_size = entry.comp_size
        if len(new_data) > target_size:
            new_data = new_data[:target_size]
        elif len(new_data) < target_size:
            new_data = new_data + b'\x00' * (target_size - len(new_data))

    # Save timestamps (Windows)
    import ctypes
    if sys.platform == 'win32':
        kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
        class FILETIME(ctypes.Structure):
            _fields_ = [("lo", ctypes.c_uint32), ("hi", ctypes.c_uint32)]
        h = kernel32.CreateFileW(entry.paz_file, 0x80000000, 1, None, 3, 0x80, None)
        ct, at, mt = FILETIME(), FILETIME(), FILETIME()
        if h != -1:
            kernel32.GetFileTime(h, ctypes.byref(ct), ctypes.byref(at), ctypes.byref(mt))
            kernel32.CloseHandle(h)
        else:
            ct = at = mt = None
    else:
        ct = at = mt = None

    with open(entry.paz_file, 'r+b') as f:
        f.seek(entry.offset)
        f.write(new_data)

    # Restore timestamps
    if ct is not None:
        h = kernel32.CreateFileW(entry.paz_file, 0x40000000, 0, None, 3, 0x80, None)
        if h != -1:
            kernel32.SetFileTime(h, ctypes.byref(ct), ctypes.byref(at), ctypes.byref(mt))
            kernel32.CloseHandle(h)

    return True


# ── Main Pipeline ─────────────────────────────────────────────────────

def get_cd_part(cd_tex_name: str) -> str:
    """Extract body part from CD texture name."""
    # cd_m0004_00_dragon_body_0001.dds -> body
    parts = cd_tex_name.replace("cd_m0004_00_dragon_", "").split("_")
    return parts[0]


def get_cd_tex_type(cd_tex_name: str) -> str:
    """Extract texture type from CD texture name suffix."""
    name = cd_tex_name.rsplit('.', 1)[0]  # remove .dds
    if name.endswith("_n"):
        return "normal"
    elif name.endswith("_sp"):
        return "specular"
    elif name.endswith("_disp"):
        return "height"
    elif name.endswith("_m"):
        return "mask"
    elif name.endswith("_o"):
        return "occlusion"
    else:
        return "baseColor"


def run_reskin(dragon_name: str, game_dir: str, dry_run: bool = False,
               backup: bool = True):
    """Main reskin pipeline."""
    dragon_name = dragon_name.lower()
    if dragon_name not in DRAGONS:
        print(f"Unknown dragon: {dragon_name}")
        print(f"Available: {', '.join(DRAGONS.keys())}")
        return False

    dragon = DRAGONS[dragon_name]
    game_path = Path(game_dir)
    archive_dir = game_path / CD_ARCHIVE
    pamt_path = archive_dir / CD_PAMT
    converted_dir = SCRIPT_DIR.parent / "converted" / dragon_name
    backup_dir = SCRIPT_DIR.parent / "backup"

    print(f"=== GoT Dragon Reskin for Crimson Desert ===")
    print(f"Dragon: {dragon['display_name']}")
    print(f"Source: {dragon['source_dir']}")
    print(f"Game:   {game_dir}")
    print()

    # Verify texconv
    if not Path(TEXCONV).exists() and not shutil.which("texconv"):
        print(f"ERROR: texconv.exe not found at {TEXCONV}")
        print("Download from: https://github.com/microsoft/DirectXTex/releases")
        return False

    # Parse PAMT to find texture entries
    print("Parsing PAZ archive index...")
    entries = parse_pamt(str(pamt_path), paz_dir=str(archive_dir))
    dragon_entries = {
        os.path.basename(e.path): e for e in entries
        if "cd_m0004_00_dragon_" in e.path and e.path.endswith(".dds")
        and "golem" not in e.path and "trex" not in e.path
        and "komodo" not in e.path and "texturelayer" not in e.path
    }
    print(f"Found {len(dragon_entries)} dragon texture entries")
    print()

    # Process each CD texture
    success_count = 0
    skip_count = 0
    fail_count = 0

    for cd_tex_name, (tex_type, resolution, dds_format, mip_count) in CD_DRAGON_TEXTURES.items():
        part = get_cd_part(cd_tex_name)
        actual_type = get_cd_tex_type(cd_tex_name)

        # Find matching source texture
        source = find_source_texture(dragon, part, actual_type)
        if source is None:
            print(f"  SKIP  {cd_tex_name} — no source for {part}/{actual_type}")
            skip_count += 1
            continue

        # Convert texture
        output = converted_dir / cd_tex_name
        print(f"  CONVERT  {source.name} -> {cd_tex_name} ({resolution}px {dds_format})")

        if not dry_run:
            if not convert_texture(source, output, dds_format, resolution, mip_count):
                print(f"  FAIL  conversion failed")
                fail_count += 1
                continue

            # Verify conversion
            ok, msg = verify_dds(output, dds_format, resolution, mip_count)
            if not ok:
                print(f"  WARN  verification: {msg}")

        # Patch into PAZ
        if cd_tex_name in dragon_entries:
            entry = dragon_entries[cd_tex_name]
            if not dry_run:
                if backup:
                    backup_texture(entry, backup_dir)
                patch_texture(entry, output)
            print(f"  PATCH  -> paz:{entry.paz_index} @0x{entry.offset:08X}")
            success_count += 1
        else:
            print(f"  SKIP  {cd_tex_name} — not found in PAZ archive")
            skip_count += 1

    print()
    print(f"=== Results ===")
    print(f"Patched:  {success_count}")
    print(f"Skipped:  {skip_count}")
    print(f"Failed:   {fail_count}")

    if dry_run:
        print("\n(Dry run — no files were modified)")
    elif backup:
        print(f"\nOriginals backed up to: {backup_dir}")
        print("Run with --restore to revert changes")

    # Save state for restore
    if not dry_run and success_count > 0:
        state = {
            "dragon": dragon_name,
            "timestamp": datetime.now().isoformat(),
            "patched_textures": success_count,
            "archive": CD_ARCHIVE,
        }
        state_path = SCRIPT_DIR.parent / "last_reskin.json"
        with open(state_path, 'w') as f:
            json.dump(state, f, indent=2)

    return fail_count == 0


def restore_originals(game_dir: str):
    """Restore original textures from backup."""
    game_path = Path(game_dir)
    archive_dir = game_path / CD_ARCHIVE
    pamt_path = archive_dir / CD_PAMT
    backup_dir = SCRIPT_DIR.parent / "backup"

    if not backup_dir.exists():
        print("No backup found. Nothing to restore.")
        return

    print("Parsing PAZ archive index...")
    entries = parse_pamt(str(pamt_path), paz_dir=str(archive_dir))
    entry_map = {e.path: e for e in entries}

    restored = 0
    for backup_file in backup_dir.rglob("*.dds"):
        rel_path = str(backup_file.relative_to(backup_dir)).replace(os.sep, '/')
        if rel_path in entry_map:
            entry = entry_map[rel_path]
            with open(backup_file, 'rb') as f:
                data = f.read()
            with open(entry.paz_file, 'r+b') as f:
                f.seek(entry.offset)
                f.write(data)
            print(f"  RESTORED  {rel_path}")
            restored += 1

    print(f"\nRestored {restored} textures to original state.")
    if restored > 0:
        shutil.rmtree(backup_dir)
        state_path = SCRIPT_DIR.parent / "last_reskin.json"
        if state_path.exists():
            state_path.unlink()
        print("Backup cleaned up.")


# ── CLI ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="GoT/HotD Dragon Reskin for Crimson Desert",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Available dragons:
  GoT:  drogon, rhaegal, viserion
  HotD: dreamfyre, moondancer, seasmoke, silverwing, sunfyre, vermithor

Examples:
  %(prog)s --dragon drogon --game-dir "C:/Program Files (x86)/Steam/..."
  %(prog)s --dragon dreamfyre --dry-run --game-dir "..."
  %(prog)s --restore --game-dir "..."
  %(prog)s --list-dragons
""")
    parser.add_argument("--dragon", "-d", help="Dragon name to use")
    parser.add_argument("--game-dir", "-g",
                        default=r"C:\Program Files (x86)\Steam\steamapps\common\Crimson Desert",
                        help="Crimson Desert installation directory")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be done without modifying files")
    parser.add_argument("--no-backup", action="store_true",
                        help="Skip backing up original textures")
    parser.add_argument("--restore", action="store_true",
                        help="Restore original textures from backup")
    parser.add_argument("--list-dragons", action="store_true",
                        help="List all available dragons")

    args = parser.parse_args()

    if args.list_dragons:
        print("Available dragons:")
        print()
        print("  Game of Thrones:")
        for name, d in DRAGONS.items():
            if "GoT" in d["display_name"]:
                print(f"    {name:15s} — {d['display_name']}")
        print()
        print("  House of the Dragon (Season 2, 4K):")
        for name, d in DRAGONS.items():
            if "HotD" in d["display_name"]:
                print(f"    {name:15s} — {d['display_name']}")
        return

    if args.restore:
        restore_originals(args.game_dir)
        return

    if not args.dragon:
        parser.error("--dragon is required (or use --list-dragons / --restore)")

    run_reskin(args.dragon, args.game_dir, dry_run=args.dry_run,
               backup=not args.no_backup)


if __name__ == "__main__":
    main()
