"""Pixel harness title memory: ranges and aliased buffers bound for pixel shaders (src/title_va_lookup.hlsli)."""
from pathlib import Path
import struct
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
BASE0 = 0x1_0000_0000 - 0x100  # range 0 straddles the 4 GiB line
BASE1 = 0x2_0000_0400
SIZE0 = 0x200  # ends at 0x1_0000_0100
SIZE1 = 0x100


def contents(seed, size):
    return bytes((seed + 7 * i + (i >> 8)) & 0xff for i in range(size))


SLOTS = [contents(3, SIZE0), contents(11, SIZE1)]


def byte_at(slot, offset):
    return float(SLOTS[slot][offset])  # little-endian word: its low byte is the byte at offset


def address(value):
    return (value & 0xffffffff, value >> 32)


def section(ranges, slots, magic=0x4d573258, trailing=b""):
    out = struct.pack("<4I", magic, len(ranges), len(slots), 0)
    for begin, end, slot in ranges:
        out += struct.pack("<QQII", begin, end, slot, 0)
    for blob in slots:
        out += struct.pack("<I", len(blob)) + blob
    return out + trailing


def case_file(constants, expected, memory):
    """A pixel case: 64 constant words (b0), the expected float4 repeated for the 64 pixels, then the memory section."""
    return struct.pack("<64I", *constants) + struct.pack("<4f", *expected) * 64 + memory


def case_bytes(addresses, expected, memory):
    return case_file([w for a in addresses for w in address(a)] + [0] * 56, expected, memory)


EXPECTED_MAGIC = 0x45573258


def expect(slots, magic=EXPECTED_MAGIC):
    """The GOOD section followed by expected contents after the draw, one blob per slot."""
    return GOOD + struct.pack("<2I", magic, len(slots)) + b"".join(struct.pack("<I", len(b)) + b for b in slots)


IMAGE_MAGIC = 0x49573258


def image_entry(slot, channels, width, height, levels, initial, expected):
    return struct.pack("<5I", slot, channels, width, height, levels) + initial + expected


def images(*entries, magic=IMAGE_MAGIC, count=None):
    """Storage images after a memory section (the 'X2WI' part, used by the image_writes draws)."""
    return struct.pack("<3I", magic, len(entries) if count is None else count, 0) + b"".join(entries)


# A 4x2 R32_UINT image with three levels (4x2, 2x1, 1x1: 11 words) and a 2x3 R32G32B32A32_UINT one.
IMAGE0 = contents(29, 11 * 4)
IMAGE1 = contents(31, 6 * 16)
GOOD = section([(BASE0, BASE0 + SIZE0, 0), (BASE1, BASE1 + SIZE1, 1)], SLOTS)
HIT_FIRST = BASE0 + 0x44
LAST_WORD = BASE1 + SIZE1 - 4
PAST_END = BASE1 + SIZE1
UNALIGNED = BASE0 + 0x11
GAP = BASE0 + SIZE0 + 0x40
ADDRESSES = [HIT_FIRST, LAST_WORD, PAST_END, UNALIGNED]
EXPECTED = [byte_at(0, 0x44), byte_at(1, SIZE1 - 4), -1.0, -1.0]
GAP_ADDRESSES = [GAP, BASE0 + SIZE0 - 4, BASE0 - 4, BASE1]
GAP_EXPECTED = [-1.0, byte_at(0, SIZE0 - 4), -1.0, byte_at(1, 0)]


def run(draw, case, data):
    case.write_bytes(data)
    return subprocess.run(draw, capture_output=True, text=True)


def main(compiler, renderer, backend):
    with tempfile.TemporaryDirectory() as tmp:
        directory = Path(tmp)
        shader, case = directory / "probe.cso", directory / "probe.case"
        subprocess.run([compiler, "-T", "ps_6_0", "-E", "main", "-I", str(ROOT / "src"), "-Fo", str(shader),
                        str(ROOT / "tests" / "pixel_memory_probe.hlsl")], check=True)
        draw = [renderer, backend, "--check-pixel-case", str(shader), str(case)]
        first = run(draw, case, case_bytes(ADDRESSES, EXPECTED, GOOD))
        sys.stdout.write(first.stdout)
        if first.returncode in (0, 77):
            if first.returncode == 77:
                return 77
        else:
            sys.stderr.write(first.stderr)
            raise AssertionError("Title memory case failed")
        second = run(draw, case, case_bytes(GAP_ADDRESSES, GAP_EXPECTED, GOOD))
        if second.returncode != 0:
            sys.stderr.write(second.stderr)
            raise AssertionError("Gap and boundary case failed")
        # A case without a memory section still binds empty memory: every lookup misses.
        empty = run(draw, case, case_bytes(ADDRESSES, [-1.0] * 4, b""))
        if empty.returncode != 0:
            sys.stderr.write(empty.stderr)
            raise AssertionError("Case without a memory section did not miss every lookup")

        def must_mismatch(expected, why, addresses=ADDRESSES):
            result = run(draw, case, case_bytes(addresses, expected, GOOD))
            if result.returncode != 1 or "pixel_mismatch" not in result.stderr:
                raise AssertionError(f"{why} escaped detection (exit {result.returncode})")

        must_mismatch([byte_at(1, 0x44), EXPECTED[1], -1.0, -1.0], "A reference reading the wrong slot")
        must_mismatch([EXPECTED[0], EXPECTED[1], byte_at(1, SIZE1 - 4), -1.0], "A past-the-end hit")
        must_mismatch([EXPECTED[0], EXPECTED[1], -1.0, byte_at(0, 0x10)], "An unaligned hit")
        must_mismatch([EXPECTED[0], EXPECTED[1], byte_at(0, 0x10), -1.0], "A hit in the gap",
                      ADDRESSES[:2] + [GAP, UNALIGNED])

        # Expected contents after the draw (the 'X2WE' part, used by the stores and atomics draws): the probe writes
        # nothing, so its initial contents match and any changed byte is reported as a memory mismatch.
        same = run(draw, case, case_bytes(ADDRESSES, EXPECTED, expect(SLOTS)))
        if same.returncode != 0:
            sys.stderr.write(same.stderr)
            raise AssertionError("Unchanged memory did not match its expected contents")
        changed = [SLOTS[0], SLOTS[1][:7] + bytes([SLOTS[1][7] ^ 1]) + SLOTS[1][8:]]
        result = run(draw, case, case_bytes(ADDRESSES, EXPECTED, expect(changed)))
        if result.returncode != 1 or "memory_mismatch slot=1 offset=0x4" not in result.stderr:
            raise AssertionError(f"A changed expected byte escaped detection (exit {result.returncode})")

        # Storage images (the 'X2WI' part): the probe writes none, so their initial texels match and a changed word
        # is reported as an image mismatch; the section may follow expected memory or the slots directly.
        stored = images(image_entry(0, 1, 4, 2, 3, IMAGE0, IMAGE0), image_entry(2, 4, 2, 3, 1, IMAGE1, IMAGE1))
        # Without ranges every lookup misses.
        for memory, expected in ((GOOD + stored, EXPECTED), (expect(SLOTS) + stored, EXPECTED),
                                 (section([], []) + stored, [-1.0] * 4)):
            same = run(draw, case, case_bytes(ADDRESSES, expected, memory))
            if same.returncode != 0:
                sys.stderr.write(same.stderr)
                raise AssertionError("Unchanged storage images did not match their expected texels")
        moved = IMAGE1[:52] + bytes([IMAGE1[52] ^ 1]) + IMAGE1[53:]  # word 13: texel (1, 1), channel 1
        result = run(draw, case, case_bytes(ADDRESSES, EXPECTED, GOOD + images(
            image_entry(0, 1, 4, 2, 3, IMAGE0, IMAGE0), image_entry(2, 4, 2, 3, 1, IMAGE1, moved))))
        if result.returncode != 1 or "image_mismatch slot=2 level=0 x=1 y=1 channel=1" not in result.stderr:
            raise AssertionError(f"A changed expected texel escaped detection (exit {result.returncode})")
        last = IMAGE0[:40] + bytes([IMAGE0[40] ^ 1]) + IMAGE0[41:]  # word 10: level 2
        result = run(draw, case, case_bytes(ADDRESSES, EXPECTED, GOOD + images(image_entry(0, 1, 4, 2, 3, IMAGE0, last))))
        if result.returncode != 1 or "image_mismatch slot=0 level=2 x=0 y=0" not in result.stderr:
            raise AssertionError(f"A changed texel of the last level escaped detection (exit {result.returncode})")

        one = image_entry(0, 1, 4, 2, 3, IMAGE0, IMAGE0)
        bad = {
            "image magic": GOOD + images(one, magic=0x12345678),
            "image count zero": GOOD + images(),
            "image count five": GOOD + images(*(image_entry(n, 1, 1, 1, 1, b"\0" * 4, b"\0" * 4) for n in range(5))),
            "image count larger than images": GOOD + images(one, count=2),
            "image reserved": GOOD + struct.pack("<3I", IMAGE_MAGIC, 1, 1) + one,
            "image slot": GOOD + images(image_entry(4, 1, 4, 2, 3, IMAGE0, IMAGE0)),
            "image slots not ascending": GOOD + images(one, one),
            "image channels": GOOD + images(image_entry(0, 2, 4, 2, 3, IMAGE0, IMAGE0)),
            "image width": GOOD + images(image_entry(0, 1, 0, 2, 3, IMAGE0, IMAGE0)),
            "image height": GOOD + images(image_entry(0, 1, 4, 1025, 3, IMAGE0, IMAGE0)),
            "image levels": GOOD + images(image_entry(0, 1, 4, 2, 4, IMAGE0 + b"\0" * 4, IMAGE0 + b"\0" * 4)),
            "image no levels": GOOD + images(image_entry(0, 1, 4, 2, 0, b"", b"")),
            "image truncated": (GOOD + images(one))[:-1],
            "image trailing byte": GOOD + images(one) + b"\0",
            "image before expected memory": GOOD + images(one) + expect(SLOTS)[len(GOOD):],
            "expected magic": expect(SLOTS, magic=0x12345678),
            "expected slot count": GOOD + struct.pack("<2I", EXPECTED_MAGIC, 1) + struct.pack("<I", SIZE0) + SLOTS[0],
            "expected slot size": expect([SLOTS[0], SLOTS[1][:-4]]),
            "expected trailing byte": expect(SLOTS) + b"\0",
            "expected truncated": expect(SLOTS)[:-1],
            "unsorted ranges": section([(BASE1, BASE1 + SIZE1, 1), (BASE0, BASE0 + SIZE0, 0)], SLOTS),
            "overlapping ranges": section([(BASE0, BASE0 + SIZE0, 0), (BASE0 + 0x100, BASE0 + 0x180, 1)], SLOTS),
            "slot out of bounds": section([(BASE0, BASE0 + SIZE0, 0), (BASE1, BASE1 + SIZE1, 2)], SLOTS),
            "range larger than slot": section([(BASE0, BASE0 + SIZE0 + 4, 0)], SLOTS),
            "unaligned begin": section([(BASE0 + 2, BASE0 + SIZE0, 0)], SLOTS),
            "trailing byte": GOOD + b"\0",
            "wrong magic": section([], [], magic=0x12345678),
            "truncated slot": GOOD[:-1],
        }
        for name, memory in bad.items():
            result = run(draw, case, case_bytes(ADDRESSES, EXPECTED, memory))
            if result.returncode != 2 or "Invalid case file" not in result.stderr:
                raise AssertionError(f"Malformed section ({name}) gave exit {result.returncode}: {result.stderr}")
        print("pixel_memory ok")


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:4]))
