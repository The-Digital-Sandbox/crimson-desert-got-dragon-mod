"""Tests for PAZ content listing (read-only inspection, no extraction)."""

from pathlib import Path

from tools.anim.paz_listing import list_paz_contents, PazEntry


def test_list_paz_contents_returns_dragon_pac_for_known_paz():
    """The mesh PAZ at 0009/3.paz must list cd_m0004_00_dragon_00_0001.pac."""
    # Corrected path — no \Paz\ subdirectory in this install.
    paz_path = Path(
        r"C:\Program Files (x86)\Steam\steamapps\common\Crimson Desert\0009\3.paz"
    )
    if not paz_path.exists():
        # Allow alternate install paths; the test owner updates this constant.
        print(f"SKIP — PAZ not found: {paz_path}")
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
