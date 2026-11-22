"""Cross-platform controls for the independent native-wave shuffle fixture.

Only synthetic inputs. This does not establish device correctness; the GPU
readback in bvh_shuffle_probe.cpp is the hardware acceptance test.
"""
import unittest


def affine(index, width):
    return (7 * index + 3) % width


def inverse(target, width):
    matches = [i for i in range(width) if affine(i, width) == target]
    if len(matches) != 1:
        raise ValueError(f"not a permutation at width {width}")
    return matches[0]


def source_values(width):
    # Distinct synthetic dwords; do not use an accidental constant broadcast.
    return [((0xf0000001 ^ (width * 0x051f3a19)) +
             (lane + 1) * 0x319db) & 0xffffffff for lane in range(width)]


class ShuffleOracle(unittest.TestCase):
    def test_forward_and_inverse_are_bijections(self):
        for width in (4, 8, 16, 32, 64):
            with self.subTest(width=width):
                self.assertEqual(len({affine(i, width) for i in range(width)}), width)
                for lane in range(width):
                    self.assertEqual(affine(inverse(lane, width), width), lane)

    def test_low_widths_cannot_identify_inversion(self):
        for width in (4, 8):
            self.assertTrue(all(affine(i, width) == inverse(i, width)
                                for i in range(width)))

    def test_large_widths_detect_inverted_affine_route(self):
        for width in (16, 32, 64):
            with self.subTest(width=width):
                values = source_values(width)
                requested = [values[affine(lane, width)] for lane in range(width)]
                inverted = [values[inverse(lane, width)] for lane in range(width)]
                wrong = sum(a != b for a, b in zip(requested, inverted))
                self.assertGreater(wrong, 0)
                # The broken permutation is not a valid outcome simply
                # because all outputs still belong to the input wave.
                self.assertEqual(set(requested), set(inverted))

    def test_nonuniform_source_indices_are_not_constant(self):
        for width in (16, 32, 64):
            with self.subTest(width=width):
                requested = [(t * 29 + 13 + (t // 32) * 7) % width
                             for t in range(64)]
                self.assertGreater(len(set(requested)), 2)
                values = source_values(width)
                self.assertGreater(len({values[i] for i in requested}), 2)

    def test_inverse_controls_do_not_hide_identity_and_mirror(self):
        for width in (16, 32, 64):
            with self.subTest(width=width):
                values = source_values(width)
                forward = [values[affine(i, width)] for i in range(width)]
                identity = values
                mirror = [values[width - 1 - i] for i in range(width)]
                self.assertNotEqual(forward, identity)
                self.assertNotEqual(forward, mirror)


if __name__ == "__main__":
    unittest.main()
