"""Check the 4 KiB standard-swizzle BC7 surface conversion against a bit-order oracle."""
from pathlib import Path
import struct
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import bc7_tiles
from bc7_tiles import linearize_4k_s

PADDING = b"\xff" * 16


def block_index(x: int, y: int) -> int:
    # Written out from the documented order, low to high: y0 y1 x0 x1 y2 x2 y3 x3.
    order = (("y", 0), ("y", 1), ("x", 0), ("x", 1), ("y", 2), ("x", 2), ("y", 3), ("x", 3))
    value = {"x": x, "y": y}
    return sum(((value[axis] >> bit) & 1) << position for position, (axis, bit) in enumerate(order))


def tag(x: int, y: int) -> bytes:
    return struct.pack("<4sHH8x", b"BC7T", x, y)


def tiled_surface(width: int, height: int) -> tuple[bytearray, bytes]:
    """Place a tag naming each visible block at its oracle address; fill the rest with padding."""
    columns, rows = -(-width // 4), -(-height // 4)
    tile_pitch = -(-columns // 16)
    payload = bytearray(PADDING * (tile_pitch * -(-rows // 16) * 256))
    linear = bytearray()
    for y in range(rows):
        for x in range(columns):
            tile = (y // 16) * tile_pitch + x // 16
            start = tile * 4096 + block_index(x % 16, y % 16) * 16
            payload[start:start + 16] = tag(x, y)
            linear += tag(x, y)
    return payload, bytes(linear)


def first_mismatch(width: int, height: int, payload=None) -> tuple[int, int] | None:
    built, expected = tiled_surface(width, height)
    output = linearize_4k_s(built if payload is None else payload, width, height)
    columns = -(-width // 4)
    for offset in range(0, max(len(output), len(expected)), 16):
        if output[offset:offset + 16] != expected[offset:offset + 16]:
            return (offset // 16) % columns, (offset // 16) // columns
    return None


class TileChecks(unittest.TestCase):
    def test_oracle_covers_one_tile(self) -> None:
        indices = {block_index(x, y) for y in range(16) for x in range(16)}
        self.assertEqual(indices, set(range(256)))
        self.assertEqual([block_index(x, 0) for x in range(4)], [0, 4, 8, 12])
        self.assertEqual([block_index(0, y) for y in range(4)], [0, 1, 2, 3])
        self.assertEqual((block_index(4, 0), block_index(0, 4), block_index(8, 0), block_index(0, 8)),
                         (32, 16, 128, 64))

    def test_surfaces_match_oracle(self) -> None:
        # Pixel sizes that are not multiples of four, single blocks, exact tile
        # edges and surfaces that cross tile columns and rows.
        for width, height in ((1, 1), (3, 5), (4, 4), (64, 64), (65, 64), (64, 65),
                              (81, 69), (80, 72), (130, 260), (257, 3)):
            with self.subTest(width=width, height=height):
                self.assertIsNone(first_mismatch(width, height))

    def test_padding_blocks_are_never_read(self) -> None:
        payload, _ = tiled_surface(81, 69)
        output = linearize_4k_s(payload, 81, 69)
        self.assertEqual(len(output), 21 * 18 * 16)
        self.assertNotIn(PADDING, [output[i:i + 16] for i in range(0, len(output), 16)])
        self.assertEqual(len(set(output[i:i + 16] for i in range(0, len(output), 16))), 21 * 18)

    def test_accepts_buffer_views(self) -> None:
        payload, expected = tiled_surface(81, 69)
        self.assertEqual(linearize_4k_s(memoryview(payload), 81, 69), expected)
        self.assertEqual(linearize_4k_s(bytes(payload), 81, 69), expected)

    def test_rejects_invalid_dimensions_and_sizes(self) -> None:
        for width, height in ((0, 4), (4, 0), (-4, 4), (4, -1), (-64, 64)):
            # An empty payload matches the zero tiles such sizes would need.
            for payload in (b"", bytes(4096)):
                with self.subTest(width=width, height=height, size=len(payload)):
                    with self.assertRaises(ValueError):
                        linearize_4k_s(payload, width, height)
        # 64 pixels fit one tile column; 65 pixels need a second padded column.
        for width, height, tiles in ((64, 64, 1), (65, 64, 2), (64, 65, 2), (81, 69, 4)):
            for size in (tiles * 4096 - 16, tiles * 4096 + 16, (tiles - 1) * 4096, (tiles + 1) * 4096):
                with self.subTest(width=width, height=height, size=size):
                    with self.assertRaises(ValueError):
                        linearize_4k_s(bytes(size), width, height)
            self.assertEqual(len(linearize_4k_s(bytes(tiles * 4096), width, height)),
                             -(-width // 4) * -(-height // 4) * 16)

    def test_negative_controls(self) -> None:
        # The oracle must notice wrong bit tables in the tool.
        x_bits, y_bits = bc7_tiles._X_BITS, bc7_tiles._Y_BITS
        swapped_high_x = tuple(x_bits[(x & 3) | ((x & 4) << 1) | ((x & 8) >> 1)] for x in range(16))
        for name, x_table, y_table in (("transposed", y_bits, x_bits),
                                       ("x2 and x3 exchanged", swapped_high_x, y_bits)):
            with self.subTest(control=name):
                with mock.patch.object(bc7_tiles, "_X_BITS", x_table), \
                        mock.patch.object(bc7_tiles, "_Y_BITS", y_table):
                    self.assertIsNotNone(first_mismatch(81, 69))

        # A payload whose two tile columns are exchanged must not match either.
        payload, _ = tiled_surface(81, 69)
        payload[0:4096], payload[4096:8192] = payload[4096:8192], payload[0:4096]
        self.assertEqual(first_mismatch(81, 69, payload), (0, 0))

        # One altered block inside the second tile row is reported where it lands.
        payload, _ = tiled_surface(81, 69)
        start = 2 * 4096 + block_index(1, 0) * 16
        payload[start] ^= 1
        self.assertEqual(first_mismatch(81, 69, payload), (1, 16))


if __name__ == "__main__":
    unittest.main()
