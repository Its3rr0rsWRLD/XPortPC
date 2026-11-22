"""Source-built BCPack/BC7 pair supplied by timelery in Xbox2Windows issue #442.

The input uses no preset history. Both byte strings are fixed test data, so a
decoder can consume the input without depending on the encoder that made it.
"""

PACKED = bytes.fromhex("""
101010101010101004040303030304040101010101010140
000000000000024002027546281800000101df5f4b7c0341
020202411010101004040403101010104004100103030304
4001080001010104000000080000000041020994e4db27a4
410511fe6b020005
""")
BLOCK = bytes.fromhex("40 31 72 04 a5 68 19 be 02 34 56 78 9a bc de f0")

# RGBA8 in raster order. Mode 6 endpoints are (197,71,41,25) and
# (144,160,180,124), including the shared per-endpoint P bits (1,0).
RGBA = bytes.fromhex("""
c24d321f c5472919 b75f4e33 ba59452d
af6b6141 b4645739 a976734e ac716a47
a183865c a67c7c54 9b8e9868 9e888f62
939aab76 9793a06e c5472919 90a0b47c
""")


if __name__ == "__main__":
    from pathlib import Path
    import sys

    sys.path.insert(0, str(Path(sys.argv[1]).resolve()))
    from bcpack import decode_with_info

    actual, provisional = decode_with_info(PACKED, 7, len(BLOCK), allow_provisional=False)
    if actual != BLOCK or provisional:
        raise ValueError(f"Expected {BLOCK.hex()} with no provisional entries, got {actual.hex()}, {provisional}")
