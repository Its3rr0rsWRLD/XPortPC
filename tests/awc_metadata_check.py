"""Source-built little-endian AWC sound-effect metadata controls."""
from dataclasses import asdict
import io
import json
from pathlib import Path
import struct
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))


def fixture() -> bytes:
    # Three sounds with interleaved tag order and discontiguous format headers.
    awc = bytearray(512)
    struct.pack_into("<4sIII3I", awc, 0, b"ADAT", 0xff020001, 3, 76,
                     2 << 29 | 11, 2 << 29 | 12, 2 << 29 | 13)
    tags = ((0x55, 208, 16), (0x76, 96, 32), (0x76, 240, 32),
            (0x55, 304, 16), (0x55, 336, 16), (0x76, 400, 32))
    for index, (tag, offset, length) in enumerate(tags):
        struct.pack_into("<Q", awc, 28 + index * 8, tag << 56 | length << 28 | offset)
    for offset, samples, rate, codec in ((96, 1001, 48000, 11), (240, 225, 22050, 8), (400, 4097, 48000, 11)):
        struct.pack_into("<I", awc, offset, samples)
        struct.pack_into("<H", awc, offset + 8, rate)
        awc[offset + 28] = codec
    return bytes(awc)


EXPECTED = [
    {"sample_rate_hz": 22050, "codec_id": 8, "streams": 1, "samples": 225},
    {"sample_rate_hz": 48000, "codec_id": 11, "streams": 2, "samples": 5098},
]


class MetadataChecks(unittest.TestCase):
    def test_command(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "archive"
            path.write_bytes(b"prefix!" + fixture() + b"neighbor")
            command = [sys.executable, "-B", str(ROOT / "tools/awc_metadata.py"), str(path), "--offset", "7"]
            result = subprocess.run([*command, "--size", "0x200"], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), {"stream_count": 3, "formats": EXPECTED})
            short = subprocess.run([*command, "--size", "430"], capture_output=True, text=True)
            self.assertNotEqual(short.returncode, 0)
            self.assertEqual(short.stdout, "")

    def test_short_reads_are_metadata_only(self) -> None:
        from awc_metadata import read_formats

        class MetadataOnly(io.BytesIO):
            def read(self, size: int = -1, /) -> bytes:
                start = self.tell()
                if not any(low <= start <= start + size <= high for low, high in
                           ((7, 83), (103, 135), (247, 279), (407, 439))):
                    raise AssertionError("Read outside an AWC metadata range")
                return super().read(min(size, 3))

        groups = read_formats(MetadataOnly(b"prefix!" + fixture()), 7, 512)
        self.assertEqual([asdict(g) for g in groups], EXPECTED)
        aliased = bytearray(fixture())
        struct.pack_into("<Q", aliased, 36, 0x76 << 56 | 32 << 28 | 208)
        with self.assertRaisesRegex(ValueError, "Overlapping"):
            read_formats(MetadataOnly(b"prefix!" + aliased), 7, 512)

    def test_unflagged_v1(self) -> None:
        from awc_metadata import read_formats

        awc = bytearray(fixture())
        struct.pack_into("<I", awc, 4, 0xff000001)
        self.assertEqual([asdict(g) for g in read_formats(io.BytesIO(awc), 0, 512)], EXPECTED)

    def test_rejects_invalid_metadata(self) -> None:
        from awc_metadata import read_formats

        for label, offset, fmt, value in (
            ("signature", 0, "<4s", b"RIFF"),
            ("unsupported flags", 4, "<I", 0xff250001),
            ("stream budget", 8, "<I", 4097),
            ("truncated tag table", 12, "<I", 75),
            ("streamed bank", 16, "<I", 2 << 29),
            ("wrong tag owner", 20, "<I", 1 << 29 | 12),
            ("format truncated", 36, "<Q", 0x76 << 56 | 28 << 28 | 96),
            ("tag outside supplied span", 28, "<Q", 0x55 << 56 | 16 << 28 | 511),
        ):
            with self.subTest(label=label):
                awc = bytearray(fixture())
                struct.pack_into(fmt, awc, offset, value)
                with self.assertRaises(ValueError):
                    read_formats(io.BytesIO(awc), 0, len(awc))


if __name__ == "__main__":
    unittest.main()
