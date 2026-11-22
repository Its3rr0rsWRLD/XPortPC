"""Check tools/status_json.py against tiny fixtures, and that the status page makes no off-site requests."""

from datetime import datetime
import json
import os
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
<testsuite name="x" tests="5" timestamp="2026-11-20T10:00:00" time="5">
<testcase name="a" status="run"/>
<testcase name="cpu_leaf_aot_branches" status="run"/>
<testcase name="b" status="run"/>
<testcase name="c" status="run"><failure message="no"/></testcase>
<testcase name="d" status="notrun"><skipped/></testcase>
</testsuite>
"""
COVERAGE = {"gfx1013": {"covered": 3, "total": 10, "groups": {"SOP1": {"covered": 2, "total": 4}, "VOP2": {"covered": 1, "total": 6}}},
            "x64_zen2": {"covered": 5, "total": 20}}
CORPUS = ("# Corpus: 10 shaders (pixel 4, vertex 3, compute 2, other 1).\n"
          "# Uses of covered forms: 50 of 200 (25.0%); reference forms covered: 3\n"
          "# Stage pixel: shaders 4; all_covered 2; translatable_bound 1.\n"
          "# Stage vertex: shaders 3; all_covered 1; translatable_bound 1.\n"
          "# Stage compute: shaders 2; all_covered 0; translatable_bound 0.\n"
          "# Stage other: shaders 1; all_covered 0; translatable_bound 0.\n"
          "# Blocking form v_a_e64: 3 shaders\n# Blocking form s_b: 2 shaders\n# Blocking form v_c: 1 shaders\n"
          "# Blocking form v_d: 1 shaders\n# Blocking form v_e: 1 shaders\n# Blocking form v_f: 1 shaders\n"
          "form\tencoding\n")
GFX1013 = ("# 10 forms. Fixture.\n"
           "SOP1\ts_mov_b32\nSOP1\ts_not_b32\nSOP1\ts_abs_i32\nSOP1\ts_wqm_b32\n"
           "VOP2\tv_add_f32\nVOP2\tv_sub_f32\nVOP2\tv_mul_f32\nVOP2\tv_max_f32\nVOP2\tv_min_f32\nVOP2\tv_and_b32\n")
# Test a passed (2 SOP1 forms, and v_add_f32 through its _e32 spelling); c failed, so v_sub_f32 is not
# covered; "old" is a record from another run (outside the JUnit window), so v_mul_f32 is not covered.
RECORDS = {"a": "s_mov_b32 s_not_b32 s_endpgm", "b": "v_add_f32_e32 s_mov_b32", "c": "v_sub_f32", "old": "v_mul_f32"}
X64 = "# 20 forms. Fixture.\n" + "".join(f"Integer\t{m}\n" for m in (
    "add", "sub", "mov", "jmp", "je", "cmove", "xlatb", "nop", "push", "pop",
    "and", "or", "xor", "not", "neg", "inc", "dec", "imul", "shl", "shr"))
# branch.asm maps to cpu_leaf_aot_branches, which passed: add, mov, je (MASM jz), cmove (cmovz), push.
# xlatb.asm maps to cpu_aot_xlatb, absent from the run; register_probe.asm is a harness (None); an
# unlisted .asm is unclassified. None of those cover anything.
ASM = {"branch": "f proc\n  add eax, 1\n  mov ecx, eax\n  jz done\n  cmovz eax, ecx\n  push rbx\ndone:\n  ret\nf endp\nend\n",
       "xlatb": "xlatb\n", "register_probe": "nop\n", "unlisted": "neg eax\n"}
PARTS = {"parts": [{"name": "A", "state": "done", "note": "n"}, {"name": "B", "state": "not_started", "note": "m"}]}


def make_repo(base):
    (base / "docs" / "coverage").mkdir(parents=True)
    (base / "docs" / "coverage" / "corpus-gfx1013.tsv").write_text(CORPUS, encoding="utf-8")
    (base / "docs" / "coverage" / "gfx1013.tsv").write_text(GFX1013, encoding="utf-8")
    (base / "docs" / "coverage" / "x64_zen2.tsv").write_text(X64, encoding="utf-8")
    (base / "tests" / "cpu").mkdir(parents=True)
    for stem, text in ASM.items():
        (base / "tests" / "cpu" / f"{stem}.asm").write_text(text, encoding="utf-8")
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
        self.records = self.dir / "records"
        self.records.mkdir()
        run = datetime.fromisoformat("2026-11-20T10:00:00").timestamp() + 1
        for test, words in RECORDS.items():
            path = self.records / f"{test}.txt"
            path.write_text(words + "\n", encoding="utf-8")
            when = run - 86400 if test == "old" else run
            os.utime(path, (when, when))

    def build(self):
        return status_json.build(self.dir / "j.xml", self.dir / "c.json", self.repo, self.records)

    def tearDown(self):
        self.tmp.cleanup()

    def test_fields(self):
        data = self.build()
        self.assertEqual(list(data), ["schema", "commit", "tests", "gfx1013", "corpus", "stages_supported", "x64", "parts"])
        self.assertEqual(data["schema"], 4)
        self.assertEqual({k: data["tests"][k] for k in ("passed", "failed", "skipped", "total")},
                         {"passed": 3, "failed": 1, "skipped": 1, "total": 5})
        self.assertEqual(data["tests"]["run_at"], "2026-11-20T10:00:00")
        g = data["gfx1013"]
        self.assertEqual((g["forms_covered"], g["forms_total"], g["uses_covered"], g["uses_total"],
                          g["uses_percent"], g["corpus_shaders"]), (3, 10, 50, 200, 25.0, 10))
        self.assertEqual(g["forms_percent"], 30.0)
        corpus = data["corpus"]
        self.assertEqual(corpus["stages"]["pixel"], {"shaders": 4, "all_covered": 2, "translatable_bound": 1})
        self.assertEqual(list(corpus["stages"]), ["pixel", "vertex", "compute", "other"])
        self.assertEqual(corpus["uses_percent"], 25.0)
        self.assertEqual(corpus["blocking_forms"][0], {"form": "v_a_e64", "shaders": 3})
        self.assertEqual(len(corpus["blocking_forms"]), 5)
        self.assertEqual(data["stages_supported"], ["pixel"])
        self.assertEqual(g["groups"][0], {"name": "SOP1", "covered": 2, "total": 4})
        self.assertEqual({k: data["x64"][k] for k in ("covered", "total")}, {"covered": 5, "total": 20})
        x64 = data["x64"]["forms"]
        self.assertEqual(len(x64), 20)
        self.assertEqual(x64[0], {"name": "add", "covered": True})
        self.assertEqual(sorted(f["name"] for f in x64 if f["covered"]), ["add", "cmove", "je", "mov", "push"])
        self.assertEqual(len(data["commit"]["full"]), 40)
        self.assertTrue(data["commit"]["full"].startswith(data["commit"]["short"]))
        self.assertEqual([p["state"] for p in data["parts"]], ["done", "not_started"])
        forms = g["forms"]
        self.assertEqual(len(forms), 10)
        self.assertEqual(forms[0], {"name": "s_mov_b32", "group": "SOP1", "covered": True})
        self.assertEqual(sorted(f["name"] for f in forms if f["covered"]), ["s_mov_b32", "s_not_b32", "v_add_f32"])

    def test_output_is_compact_and_cli_unchanged(self):
        out = self.dir / "site" / "status.json"
        old = status_json.ROOT
        status_json.ROOT = self.repo
        try:
            # The merge script's command line, plus --records because the fixture is not in out/.
            code = status_json.main(["--junit", str(self.dir / "j.xml"), "--coverage", str(self.dir / "c.json"),
                                     "--out", str(out), "--records", str(self.records)])
        finally:
            status_json.ROOT = old
        self.assertEqual(code, 0)
        text = out.read_text(encoding="utf-8")
        self.assertEqual(text.count("\n"), 1)
        self.assertEqual(json.loads(text)["schema"], 4)

    def test_rerun_junit_overrides_by_name(self):
        # c failed in the main run and passes in a serial rerun 10 minutes later; its record is from the rerun.
        (self.dir / "r.xml").write_text('<?xml version="1.0"?>\n<testsuite name="x" tests="1" '
                                        'timestamp="2026-11-20T10:10:00" time="2"><testcase name="c" status="run"/>'
                                        '</testsuite>\n', encoding="utf-8")
        rerun = datetime.fromisoformat("2026-11-20T10:10:00").timestamp() + 1
        os.utime(self.records / "c.txt", (rerun, rerun))
        cov = json.loads(json.dumps(COVERAGE))
        cov["gfx1013"]["covered"] = 4
        cov["gfx1013"]["groups"]["VOP2"]["covered"] = 2
        (self.dir / "c.json").write_text(json.dumps(cov), encoding="utf-8")
        data = status_json.build([self.dir / "j.xml", self.dir / "r.xml"], self.dir / "c.json", self.repo, self.records)
        self.assertEqual({k: data["tests"][k] for k in ("passed", "failed", "skipped", "total", "run_at")},
                         {"passed": 4, "failed": 0, "skipped": 1, "total": 5, "run_at": "2026-11-20T10:00:00"})
        self.assertIn("v_sub_f32", [f["name"] for f in data["gfx1013"]["forms"] if f["covered"]])
        # Order matters: the main run given last overrides the rerun, so c is failed again and the
        # rerun's record no longer counts, which now disagrees with the coverage file.
        self.assertEqual(status_json.read_junit([self.dir / "r.xml", self.dir / "j.xml"])["failed"], 1)
        with self.assertRaises(status_json.InputError):
            status_json.build([self.dir / "r.xml", self.dir / "j.xml"], self.dir / "c.json", self.repo, self.records)
        out = self.dir / "two.json"
        old = status_json.ROOT
        status_json.ROOT = self.repo
        try:
            code = status_json.main(["--junit", str(self.dir / "j.xml"), "--junit", str(self.dir / "r.xml"),
                                     "--coverage", str(self.dir / "c.json"), "--out", str(out), "--records", str(self.records)])
        finally:
            status_json.ROOT = old
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out.read_text(encoding="utf-8"))["tests"]["passed"], 4)

    def test_x64_disagreeing_with_coverage_is_rejected(self):
        cov = json.loads(json.dumps(COVERAGE))
        cov["x64_zen2"]["covered"] = 6
        (self.dir / "c.json").write_text(json.dumps(cov), encoding="utf-8")
        with self.assertRaises(status_json.InputError):
            self.build()
        # The same run without the passing CPU test covers no x64 form, which also disagrees.
        (self.dir / "j.xml").write_text(JUNIT.replace('<testcase name="cpu_leaf_aot_branches" status="run"/>\n', ""), encoding="utf-8")
        (self.dir / "c.json").write_text(json.dumps(COVERAGE), encoding="utf-8")
        with self.assertRaises(status_json.InputError):
            self.build()

    def test_corpus_shaders_recount_stages_from_this_run(self):
        # Covered here: s_mov_b32, s_not_b32, v_add_f32. A '!' form is outside the reference list.
        (self.repo / "docs" / "coverage" / "corpus-shaders.tsv").write_text(
            "# stage\tname\tbranches\tforms\n"
            "pixel\ta.frag\t0\ts_mov_b32 v_add_f32\n"
            "pixel\tb.frag\t1\ts_mov_b32\n"
            "pixel\tc.frag\t0\ts_mov_b32 v_mul_f32\n"
            "pixel\td.frag\t0\ts_mov_b32 !odd_op\n"
            "vertex\te.vert\t0\ts_not_b32\n", encoding="utf-8")
        corpus = self.build()["corpus"]
        self.assertEqual(corpus["stages"]["pixel"], {"shaders": 4, "all_covered": 2, "translatable_bound": 1})
        self.assertEqual(corpus["stages"]["vertex"], {"shaders": 1, "all_covered": 1, "translatable_bound": 1})
        self.assertEqual(corpus["stages"]["compute"], {"shaders": 0, "all_covered": 0, "translatable_bound": 0})
        self.assertEqual(corpus["blocking_forms"], [{"form": "v_mul_f32", "shaders": 1}])

    def test_malformed_corpus_shaders_is_rejected(self):
        (self.repo / "docs" / "coverage" / "corpus-shaders.tsv").write_text("pixel\ta.frag\t2\ts_mov_b32\n", encoding="utf-8")
        with self.assertRaises(status_json.InputError):
            self.build()

    def test_missing_or_empty_records_exit_2(self):
        out = self.dir / "status.json"
        empty = self.dir / "empty"
        empty.mkdir()
        for records in (self.dir / "absent", empty):
            self.assertEqual(status_json.main(["--junit", str(self.dir / "j.xml"), "--coverage", str(self.dir / "c.json"),
                                               "--out", str(out), "--records", str(records)]), 2)
            self.assertFalse(out.exists())

    def test_records_disagreeing_with_coverage_are_rejected(self):
        (self.records / "a.txt").write_text("s_mov_b32 s_not_b32 s_abs_i32\n", encoding="utf-8")
        run = datetime.fromisoformat("2026-11-20T10:00:00").timestamp() + 1
        os.utime(self.records / "a.txt", (run, run))
        with self.assertRaises(status_json.InputError):
            self.build()

    def test_missing_input_exits_2_and_writes_nothing(self):
        out = self.dir / "status.json"
        out.write_text("old", encoding="utf-8")
        self.assertEqual(status_json.main(["--junit", str(self.dir / "none.xml"), "--coverage",
                                           str(self.dir / "c.json"), "--out", str(out)]), 2)
        self.assertEqual(out.read_text(encoding="utf-8"), "old")

    def test_old_corpus_header_is_rejected(self):
        (self.repo / "docs" / "coverage" / "corpus-gfx1013.tsv").write_text(
            "# Corpus: 7 shaders (pixel 7).\n# Uses of covered forms: 50 of 200 (25.0%)\n", encoding="utf-8")
        with self.assertRaises(status_json.InputError):
            self.build()

    def test_real_corpus_header_parses(self):
        _, corpus = status_json.read_corpus(ROOT)
        self.assertEqual(set(corpus["stages"]), set(status_json.STAGES))

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
