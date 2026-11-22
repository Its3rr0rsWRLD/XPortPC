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


def case_bytes(addresses, expected, memory):
    words = [w for a in addresses for w in address(a)] + [0] * 56
    return struct.pack("<64I", *words) + struct.pack("<4f", *expected) * 64 + memory


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

        bad = {
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
