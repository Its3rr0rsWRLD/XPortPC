"""Check tools/status_json.py against tiny fixtures, and that the status page makes no off-site requests."""

import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import status_json  # noqa: E402

JUNIT = """<?xml version="1.0"?>
<testsuite name="x" tests="4" timestamp="2026-11-20T10:00:00" time="5">
<testcase name="a" status="run"/>
<testcase name="b" status="run"/>
<testcase name="c" status="run"><failure message="no"/></testcase>
<testcase name="d" status="notrun"><skipped/></testcase>
</testsuite>
"""
COVERAGE = {"gfx1013": {"covered": 3, "total": 10, "groups": {"SOP1": {"covered": 2, "total": 4}, "VOP2": {"covered": 1, "total": 6}}},
            "x64_zen2": {"covered": 5, "total": 20}}
CORPUS = "# Corpus: 7 shaders (pixel 7).\n# Uses of covered forms: 50 of 200 (25.0%); reference forms covered: 3\nform\tencoding\n"
PARTS = {"parts": [{"name": "A", "state": "done", "note": "n"}, {"name": "B", "state": "not_started", "note": "m"}]}


def make_repo(base):
    (base / "docs" / "coverage").mkdir(parents=True)
    (base / "docs" / "coverage" / "corpus-gfx1013.tsv").write_text(CORPUS, encoding="utf-8")
    (base / "docs" / "status-parts.json").write_text(json.dumps(PARTS), encoding="utf-8")
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com", "PATH": __import__("os").environ["PATH"]}
    for cmd in (["init", "-q"], ["add", "."], ["commit", "-q", "-m", "x"]):
        subprocess.run(["git", "-C", str(base)] + cmd, check=True, env=env, capture_output=True)


class StatusJson(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.repo = self.dir / "repo"
        self.repo.mkdir()
        make_repo(self.repo)
        (self.dir / "j.xml").write_text(JUNIT, encoding="utf-8")
        (self.dir / "c.json").write_text(json.dumps(COVERAGE), encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_fields(self):
        data = status_json.build(self.dir / "j.xml", self.dir / "c.json", self.repo)
        self.assertEqual(list(data), ["schema", "commit", "tests", "gfx1013", "x64", "parts"])
        self.assertEqual({k: data["tests"][k] for k in ("passed", "failed", "skipped", "total")},
                         {"passed": 2, "failed": 1, "skipped": 1, "total": 4})
        self.assertEqual(data["tests"]["run_at"], "2026-11-20T10:00:00")
        g = data["gfx1013"]
        self.assertEqual((g["forms_covered"], g["forms_total"], g["uses_covered"], g["uses_total"],
                          g["uses_percent"], g["corpus_shaders"]), (3, 10, 50, 200, 25.0, 7))
        self.assertEqual(g["groups"][0], {"name": "SOP1", "covered": 2, "total": 4})
        self.assertEqual(data["x64"], {"covered": 5, "total": 20})
        self.assertEqual(len(data["commit"]["full"]), 40)
        self.assertTrue(data["commit"]["full"].startswith(data["commit"]["short"]))
        self.assertEqual([p["state"] for p in data["parts"]], ["done", "not_started"])

    def test_missing_input_exits_2_and_writes_nothing(self):
        out = self.dir / "status.json"
        out.write_text("old", encoding="utf-8")
        self.assertEqual(status_json.main(["--junit", str(self.dir / "none.xml"), "--coverage",
                                           str(self.dir / "c.json"), "--out", str(out)]), 2)
        self.assertEqual(out.read_text(encoding="utf-8"), "old")

    def test_real_parts_file_is_valid(self):
        status_json.read_parts(ROOT)


class Page(unittest.TestCase):
    def test_only_same_origin_requests(self):
        html = (ROOT / "site" / "index.html").read_text(encoding="utf-8")
        allowed = re.compile(r"https://github\.com/")
        anchors = re.findall(r'<a\b[^>]*\bhref="([^"]*)"', html)
        for url in anchors:
            if re.match(r"https?:", url):
                self.assertRegex(url, allowed)
        # Every other http(s) URL must be a string used only for anchors (REPO constant) or absent.
        stripped = re.sub(r'<a\b[^>]*\bhref="[^"]*"', "", html)
        for url in re.findall(r"https?://[^\s\"'<>)]*", stripped):
            self.assertRegex(url, allowed)
        for attr in re.findall(r'<(?:script|link|img|iframe|source|video|audio)\b[^>]*\b(?:src|href|srcset)="([^"]*)"', html):
            self.assertNotRegex(attr, r"^(?:https?:)?//")
        self.assertNotIn("@import", html)
        self.assertNotRegex(html, r"url\(\s*['\"]?(?:https?:)?//")
        self.assertEqual((ROOT / "site" / "CNAME").read_text(encoding="utf-8"), "xportpc.3rr0r.cc")


if __name__ == "__main__":
    unittest.main()
