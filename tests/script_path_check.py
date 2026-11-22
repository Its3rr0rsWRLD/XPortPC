"""Cross-check native sibling traversal on original, source-built state rows."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from script_path_replay import replay, state_index
from script_state_probe import joaat


def fixture(duplicate=False, integer_id=None):
    none = 0xffff
    attrs = []
    nodes = []

    def node(tag, parent, child, sibling, previous, label=None):
        first = len(attrs)
        if label is not None:
            attrs.append((joaat("id"), joaat(label), 0, 5, 1, 0))
        if integer_id == len(nodes):
            # An integer-kind id spelled like a label; the native host reports it as malformed.
            attrs.append((joaat("id"), joaat("panel"), 7, 3, 1, 0))
        nodes.append((joaat(tag), parent, child, sibling, previous, first, len(attrs) - first, 1))

    node("root", none, 1, none, none)
    node("states", 0, 2, none, none)
    node("state", 1, none, 3, none, "panel")
    node("state", 1, 5, 4, 2, "station")
    node("state", 1, none, none, 3, "other")
    node("state", 3, none, 6, none, "panel")
    node("state", 3, none, none, 5, "panel" if duplicate else "switch")
    return nodes, attrs, b""


class PathTests(unittest.TestCase):
    def walk(self, tree, *paths):
        return replay(tree, *state_index(*tree[:2]), paths, HOST)

    def test_context_and_round_trip(self):
        rows = self.walk(fixture(), "panel", "station", "./panel", "../switch", "../panel",
                         "other/panel", "../../../panel")
        self.assertEqual([r["after"] for r in rows], [2, 3, 5, 6, 5, 5, 5])
        self.assertEqual([r["status"] for r in rows], ["matched"] * 5 + ["missing"] * 2)

    def test_ambiguous_siblings(self):
        rows = self.walk(fixture(duplicate=True), "station", "./panel")
        self.assertEqual((rows[-1]["status"], rows[-1]["after"]), ("ambiguous", 3))

    def test_non_label_id_is_malformed(self):
        # On a sibling of the selected state, beside the selected label, and on an unrelated branch.
        for owner in (6, 5, 4):
            with self.subTest(owner=owner), self.assertRaisesRegex(ValueError, "Non-label state ID"):
                self.walk(fixture(integer_id=owner), "station", "./panel")

    def test_broken_links(self):
        for link, value in ((2, 6), (3, 5), (4, 2)):
            with self.subTest(link=link):
                tree = fixture()
                index = 3 if link == 2 else 5
                row = list(tree[0][index])
                row[link] = value
                tree[0][index] = tuple(row)
                with self.assertRaisesRegex(ValueError, "Linked traversal"):
                    self.walk(tree, "station/panel")

    def test_broken_link_after_ambiguous_siblings(self):
        none = 0xffff

        def three_children():
            nodes, attrs, vectors = fixture(duplicate=True)
            row = list(nodes[6])
            row[3] = 7
            nodes[6] = tuple(row)
            first = len(attrs)
            attrs.append((joaat("id"), joaat("extra"), 0, 5, 1, 0))
            nodes.append((joaat("state"), 3, none, none, 6, first, 1, 1))
            return nodes, attrs, vectors

        rows = self.walk(three_children(), "station", "./panel")
        self.assertEqual((rows[-1]["status"], rows[-1]["after"]), ("ambiguous", 3))
        for index, link, value in ((7, 4, 5), (6, 3, 5), (7, 1, 1)):
            with self.subTest(index=index, link=link):
                tree = three_children()
                row = list(tree[0][index])
                row[link] = value
                tree[0][index] = tuple(row)
                with self.assertRaisesRegex(ValueError, "Linked traversal returned -3"):
                    self.walk(tree, "station", "./panel")


if __name__ == "__main__":
    HOST = Path(sys.argv.pop(1))
    unittest.main()
