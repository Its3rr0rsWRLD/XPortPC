"""Check tools/vertex_corpus_report.py on tiny fixtures, and that its counts agree with tools/status_json.py."""

import contextlib
import io
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import status_json  # noqa: E402
import vertex_corpus_report as vcr  # noqa: E402

# Four vertex shaders: one covered, one blocked by v_a alone, one by v_a and v_b, one by a non-reference mnemonic.
TSV = ("# fixture\n"
       "pixel\tp.frag.s\t0\tv_mul_f32 exp\n"
       "vertex\ta.vert.s\t0\tv_mul_f32 exp s_setprio\n"
       "vertex\tb.vert.s\t0\tv_a exp\n"
       "vertex\tc.vert.s\t1\tv_a v_b exp\n"
       "vertex\td.vert.s\t0\t!v_odd exp\n")
COVERED = {"v_mul_f32", "exp", "s_setprio"}

FRAME_HEAD = """# Vertex Shader as ESGS
BB0:
\ts_setprio 3                                                 ; bf8f0003
\ts_barrier                                                   ; bf8a0000
\ts_and_b32 s0, s3, 0xf000000                                 ; 8700ff03 0f000000
\ts_cbranch_scc1 BB3                                          ; bf850007
BB1:
\ts_bfe_u32 s0, s2, 0x90016                                   ; 9380ff02 00090016
\ts_lshl_b32 s0, s0, 12                                       ; 8f008c00
\ts_bfe_u32 s2, s2, 0x9000c                                   ; 9382ff02 0009000c
\ts_or_b32 m0, s0, s2                                         ; 887c0200
\ts_sendmsg sendmsg(MSG_GS_ALLOC_REQ)                         ; bf900009
BB3:
"""
PRIM = """\ts_lshl_b32 s0, s3, 8                                        ; 8f008803
\ts_bfe_u64 exec, -1, s0                                      ; 94fe00c1
\ts_cbranch_execz BB9                                         ; bf880002
BB4:
\texp prim v0, off, off, off done                             ; f8000941 80808000
BB9:
"""
VERTEX_HEAD = """\ts_pack_ll_b32_b16 s3, 0, s3                                 ; 99030380
\ts_waitcnt expcnt(0)                                         ; bf8cff0f
\ts_bfe_u64 exec, -1, s3                                      ; 94fe03c1
\ts_cbranch_execz BB15                                        ; bf8800e9
BB10:
"""
BODY = """\ts_mov_b32 s0, s9                                            ; be800309
\ts_movk_i32 s9, 0x8000                                       ; b0098000
\ts_load_dwordx4 s[16:19], s[8:9], null                       ; f4080404 fa000000
\tv_add_nc_u32_e32 v5, s0, v5                                 ; 4a0a0a00
\ts_waitcnt lgkmcnt(0)                                        ; bf8cc07f
\tbuffer_load_dwordx4 v[1:4], v5, s[16:19], 0 idxen           ; e03c2000 80040105
\ts_waitcnt vmcnt(0)                                          ; bf8c3f70
\texp pos0 v1, v2, v3, v4 done vm                             ; f80018cf 04030201
\texp param0 v1, v2, off, off                                 ; f8000203 80800201
"""
END = """BB15:
\ts_endpgm                                                    ; bf810000
"""
LEGACY = """# Vertex Shader as VS
BB0:
\ts_setprio 3                                                 ; bf8f0003
\ts_mov_b32 s0, s3                                            ; be800303
\ts_movk_i32 s3, 0x8000                                       ; b0038000
\ts_load_dwordx4 s[8:11], s[2:3], null                        ; f4080201 fa000000
\tv_add_nc_u32_e32 v0, s0, v0                                 ; 4a000000
\ts_waitcnt lgkmcnt(0)                                        ; bf8cc07f
\tbuffer_load_dwordx4 v[1:4], v0, s[8:11], 0 idxen            ; e03c2000 80020100
\ts_waitcnt vmcnt(0)                                          ; bf8c3f70
\texp pos0 v1, v2, v3, v4 done vm                             ; f80018cf 16151413
\ts_endpgm                                                    ; bf810000
"""


def write(directory, name, text):
    path = Path(directory) / "vertex" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


class Forms(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tsv = Path(self.tmp.name) / "shaders.tsv"
        self.tsv.write_text(TSV, encoding="utf-8")
        self.report = vcr.form_report(vcr.read_forms(self.tsv), COVERED)

    def tearDown(self):
        self.tmp.cleanup()

    def test_counts(self):
        r = self.report
        self.assertEqual((r["vertex_shaders"], r["all_covered"], r["blocked"]), (4, 1, 3))
        self.assertEqual(r["blocked_by_count"], {1: 2, 2: 1})

    def test_blocking_forms_and_alone(self):
        rows = {b["form"]: (b["shaders"], b["alone"]) for b in self.report["blocking_forms"]}
        self.assertEqual(rows, {"v_a": (2, 1), "v_b": (1, 0), "!v_odd": (1, 1)})

    def test_greedy_skips_non_reference_forms(self):
        steps = [(s["forms"], s["unlocks"], s["cumulative"]) for s in self.report["greedy_unlock"]]
        self.assertEqual(steps, [(["v_a"], 1, 1), (["v_b"], 1, 2)])

    def test_vertex_only_forms(self):
        only = {v["form"]: (v["shaders"], v["covered"]) for v in self.report["vertex_only_forms"]}
        self.assertEqual(only, {"s_setprio": (1, True), "v_a": (2, False), "v_b": (1, False), "!v_odd": (1, False)})

    def test_bad_row_is_refused(self):
        self.tsv.write_text("vertex\tx\t2\tv_a\n", encoding="utf-8")
        with self.assertRaises(vcr.InputError):
            vcr.read_forms(self.tsv)

    def test_real_files_agree_with_status_json(self):
        covered = vcr.read_covered(ROOT / "site" / "status.json")
        stages, _ = status_json.recount_corpus(ROOT, covered)
        r = vcr.form_report(vcr.read_forms(vcr.SHADERS), covered)
        self.assertEqual((r["vertex_shaders"], r["all_covered"]),
                         (stages["vertex"]["shaders"], stages["vertex"]["all_covered"]))
        self.assertEqual(r["all_covered_straight_line"], stages["vertex"]["translatable_bound"])


class Structure(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def frame(self, text):
        return vcr.ngg_passthrough(vcr.read_isa(write(self.tmp.name, "x.vert.s", text))[1])

    def test_prim_first_frame(self):
        f = self.frame(FRAME_HEAD + PRIM + VERTEX_HEAD + BODY + END)
        self.assertEqual(f["order"], ["prim", "vertex"])
        self.assertEqual(f["roles"], {"merged_wave_info": "s3", "gs_tg_info": "s2", "prim_payload": "v0"})
        self.assertEqual(f["body"][0], "s_mov_b32 s0, s9")
        self.assertEqual(f["body"][-1], "exp param0 v1, v2, off, off")

    def test_vertex_first_frame(self):
        vertex = VERTEX_HEAD.replace("s_pack_ll_b32_b16 s3, 0, s3", "s_pack_ll_b32_b16 s0, 0, s3").replace(
            "s_waitcnt expcnt(0)                                         ; bf8cff0f\n", "").replace("exec, -1, s3", "exec, -1, s0")
        prim = PRIM.replace("s_lshl_b32 s0, s3, 8", "s_lshl_b32 s3, s3, 8").replace("exec, -1, s0", "exec, -1, s3")
        f = self.frame(FRAME_HEAD + vertex + BODY + "BB9:\n" + prim + END)
        self.assertEqual(f["order"], ["vertex", "prim"])

    def test_vertex_first_must_keep_payload(self):
        vertex = VERTEX_HEAD.replace("s_pack_ll_b32_b16 s3, 0, s3", "s_pack_ll_b32_b16 s0, 0, s3").replace(
            "exec, -1, s3", "exec, -1, s0")
        prim = PRIM.replace("s_lshl_b32 s0, s3, 8", "s_lshl_b32 s3, s3, 8").replace("exec, -1, s0", "exec, -1, s3")
        body = BODY.replace("exp param0 v1, v2, off, off", "v_mov_b32_e32 v0, 0\n\texp param0 v1, v2, off, off")
        with self.assertRaisesRegex(vcr.InputError, "overwrites the primitive payload v0"):
            self.frame(FRAME_HEAD + vertex + body + "BB9:\n" + prim + END)

    def test_refusals(self):
        cases = {
            "lane-cooperative": BODY.replace("\ts_waitcnt vmcnt(0)", "\tv_mbcnt_lo_u32_b32 v6, -1, 0\n\ts_waitcnt vmcnt(0)"),
            "reads frame register s3": BODY.replace("s_mov_b32 s0, s9", "s_mov_b32 s0, s3"),
        }
        for reason, body in cases.items():
            with self.subTest(reason), self.assertRaisesRegex(vcr.InputError, reason):
                self.frame(FRAME_HEAD + PRIM + VERTEX_HEAD + body + END)
        with self.assertRaisesRegex(vcr.InputError, "GS_ALLOC_REQ block"):
            self.frame(FRAME_HEAD.replace("sendmsg(MSG_GS_ALLOC_REQ)", "sendmsg(MSG_GS)") + PRIM + VERTEX_HEAD + BODY + END)
        with self.assertRaisesRegex(vcr.InputError, "single passthrough primitive export"):
            self.frame(FRAME_HEAD + PRIM.replace("exp prim v0", "exp prim v1") .replace("v1, off", "v1, v2") + VERTEX_HEAD + BODY + END)

    def test_features(self):
        insns = ["v_cmp_eq_f32_e32 vcc, 1.0, v1", "v_cndmask_b32_e32 v2, 0, v1, vcc",
                 "v_add_co_u32 v4, vcc, s5, v2", "v_add_co_ci_u32_e32 v5, vcc, s6, v3, vcc",
                 "v_mac_f32_e32 v7, s2, v1", "v_add_nc_u32_e32 v0, s0, v0",
                 "buffer_load_dword v8, v9, s[8:11], 0 offen", "global_load_dwordx2 v[10:11], v[4:5], off",
                 "exp pos0 v1, v2, v3, v4 done vm", "exp pos1 v4, off, off, off done"]
        f = vcr.features(insns)
        self.assertEqual(f["inputs_vgpr"], ["v1", "v3", "v7", "v0", "v9"])
        self.assertEqual(f["inputs_sgpr"], ["s5", "s6", "s2", "s0", "s8", "s9", "s10", "s11"])
        self.assertEqual(f["inputs_special"], [])
        # s5, s6 and s2 as ALU data and s[8:11] as an inline V#; s0 is the index base, not user data
        self.assertEqual(f["features"]["user_data_sgpr"], 4)
        self.assertEqual((f["features"]["fetch_raw_offen"], f["features"]["fetch_global"]), (1, 1))
        self.assertEqual(f["exports"], {"pos0": 1, "pos1": 1})

    def test_cards(self):
        legacy = vcr.parse_isa(write(self.tmp.name, "l.vert.s", LEGACY), {"s_setprio", "s_mov_b32", "s_movk_i32",
                               "s_load_dwordx4", "v_add_nc_u32", "s_waitcnt", "buffer_load_dwordx4", "exp", "s_endpgm"})
        covered = set(legacy["forms"])
        self.assertEqual(vcr.card(legacy, covered), ("V-1", []))
        self.assertEqual(vcr.card(legacy, covered - {"v_add_nc_u32"}), ("V-4", ["form v_add_nc_u32"]))
        instanced = dict(legacy, inputs_vgpr=["v0", "v3"])
        self.assertEqual(vcr.card(instanced, covered), ("V-3", ["instance id"]))
        unknown = dict(legacy, inputs_vgpr=["v0", "v1"])
        self.assertEqual(vcr.card(unknown, covered)[0], "refused")
        reference = covered | {"s_barrier", "s_and_b32", "s_cbranch_scc1", "s_bfe_u32", "s_lshl_b32", "s_or_b32",
                               "s_sendmsg", "s_bfe_u64", "s_cbranch_execz", "s_pack_ll_b32_b16"}
        ngg = vcr.parse_isa(write(self.tmp.name, "n.vert.s", FRAME_HEAD + PRIM + VERTEX_HEAD + BODY + END), reference)
        self.assertTrue(ngg["ngg"]["passthrough"])
        self.assertIn("s_barrier", ngg["forms"])
        self.assertNotIn("s_barrier", ngg["body_forms"])
        self.assertEqual(vcr.card(ngg, covered), ("V-2", ["NGG passthrough frame"]))
        culled = vcr.parse_isa(write(self.tmp.name, "c.vert.s", FRAME_HEAD + PRIM + VERTEX_HEAD
                               + BODY.replace("\ts_waitcnt vmcnt(0)", "\tds_write_b32 v0, v1\n\ts_waitcnt vmcnt(0)") + END), reference)
        self.assertEqual(vcr.card(culled, covered)[0], "refused")

    def test_isa_report_and_main(self):
        write(self.tmp.name, "l.vert.s", LEGACY)
        write(self.tmp.name, "n.vert.s", FRAME_HEAD + PRIM + VERTEX_HEAD + BODY + END)
        r = vcr.isa_report(self.tmp.name, {"exp"}, {"exp"})
        self.assertEqual(r["kinds"], {"legacy": 1, "ngg": 1})
        self.assertEqual(r["ngg_passthrough"], 1)
        self.assertEqual(r["input_vgprs"], {"v0": 2, "v5": 1})
        with contextlib.redirect_stdout(io.StringIO()) as out, contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(vcr.main(["--isa", self.tmp.name, "--json", str(Path(self.tmp.name) / "o.json")]), 0)
            self.assertEqual(vcr.main(["--isa", str(Path(self.tmp.name) / "missing")]), 2)
        self.assertIn("kinds legacy 1, ngg 1", out.getvalue())
        self.assertIn("has no .s files", err.getvalue())
        self.assertIn('"ngg_passthrough": 1', (Path(self.tmp.name) / "o.json").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
