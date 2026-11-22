"""Check tools/form_coverage.py: its reference lists (denominators), one fixture-to-instruction example,
how skipped and failed tests change the count, and that only accepted shader programs count.
Needs requirements-dev.txt (iced-x86); no Windows."""
from datetime import datetime
import os
from pathlib import Path
import sys
import tempfile
import time
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import form_coverage as fc
import form_reference as fr

ENCODINGS = {"DPP16", "DPP8", "DS", "EXP", "FLAT", "MIMG", "MTBUF", "MUBUF", "SDWA", "SMEM", "SOP1", "SOP2",
             "SOPC", "SOPK", "SOPP", "VINTRP", "VOP1", "VOP2", "VOP3", "VOP3P", "VOPC"}


def check_denominators():
    for name in ("x64_zen2.tsv", "gfx1013.tsv", "rdna2.tsv"):
        lines = (fc.REFERENCE / name).read_text(encoding="utf-8").splitlines()
        count, source = int(lines[0].split()[1]), lines[0]
        assert "Source:" in source and len(lines) - 1 == count == len(set(lines[1:])), name
    # x64: the committed list is exactly what iced-x86 yields for Zen 2 user mode today.
    assert fc.load_reference("x64_zen2.tsv") == fr.x64_forms()
    # gfx: every form sits under a real encoding with a name that encoding allows.
    for name in ("gfx1013.tsv", "rdna2.tsv"):
        reference = fc.load_reference(name)
        assert {group for group, _ in reference} == ENCODINGS, name
        assert ("SOPP", "s_endpgm") in reference and ("EXP", "exp") in reference
    gfx1013, rdna2 = fc.load_reference("gfx1013.tsv"), fc.load_reference("rdna2.tsv")
    assert ("SMEM", "s_atomic_add") in gfx1013 and ("SMEM", "s_atomic_add") not in rdna2
    # The LLVM syntax-doc parser: short headings, operand-less instructions, and the trailing index.
    with tempfile.TemporaryDirectory() as tmp:
        doc = Path(tmp) / "sample.rst"
        doc.write_text("DS\n--\n\n.. parsed-literal::\n\n    ds_nop\n    ds_add_u32     vaddr, vdata\n\n"
                       "SOPP\n----\n\n    s_endpgm\n\n.. toctree::\n    :hidden:\n\n    gfx10_vdst_123\n")
        assert fr.llvm_forms(doc) == {("DS", "ds_nop"), ("DS", "ds_add_u32"), ("SOPP", "s_endpgm")}
        doc.write_text("DPP8\n----\n\n    ds_nop\n")
        try:
            fr.llvm_forms(doc)
        except AssertionError:
            pass
        else:
            raise AssertionError("a form filed under the wrong encoding was accepted")


# Small fixtures written here, so later edits to the repository's own tests/cpu/*.asm cannot change the
# expected counts. They use the repository's fixture names, so the real CPU_FIXTURES mapping applies.
BRANCH = """branch PROC
    mov eax, ecx
    cmp ecx, edx
IFDEF INVERT_BRANCH
    jae short high
ELSE
    jb short low
ENDIF
    add eax, 1
    jmp short done
low:
    sub eax, 1
high:
done:
    ret
branch ENDP
END
"""
DIRECT = "direct PROC\n    sub rsp, 28h\n    call helper\n    add rsp, 28h\n    ret\ndirect ENDP\nEND\n"
SWITCH = """switch PROC
    cmp ecx, 3
    ja short default
    lea rdx, table
    movsxd rax, DWORD PTR [rdx+rcx*4]
    add rax, rdx
    jmp rax
default:
    neg eax
    ret
table DD 0
switch ENDP
END
"""


def sample_repo(tmp, cpu, scripts=None):
    """A repository root holding only the given tests/cpu/<name>.asm and tests/<name>.py sources."""
    root = Path(tmp)
    (root / "tests" / "cpu").mkdir(parents=True, exist_ok=True)
    for name, text in cpu.items():
        (root / "tests" / "cpu" / f"{name}.asm").write_text(text, encoding="utf-8")
    for name, text in (scripts or {}).items():
        (root / "tests" / name).write_text(text, encoding="utf-8")
    return root


def check_example():
    """branch.asm -> eight x64 forms, counted only while cpu_leaf_aot_branches passes."""
    branch = fc.masm_mnemonics(BRANCH)
    assert branch == {"mov", "cmp", "jb", "jae", "add", "jmp", "sub", "ret"}, branch  # jae: INVERT_BRANCH build
    reference = fc.load_reference("x64_zen2.tsv")
    assert fc.x64_forms(branch, reference) == {("Integer", m) for m in branch}

    with tempfile.TemporaryDirectory() as tmp:
        root = sample_repo(tmp, {"branch": BRANCH, "direct": DIRECT})
        passed = fc.measure({"cpu_leaf_aot_branches": "pass"}, root)["x64_zen2"]
        skipped = fc.measure({"cpu_leaf_aot_branches": "skip"}, root)["x64_zen2"]
        failed = fc.measure({"cpu_leaf_aot_branches": "fail"}, root)["x64_zen2"]
        assert passed["covered"] == 8 and passed["groups"]["Integer"]["covered"] == 8
        assert skipped["covered"] == 0 and skipped["blocked_by_skip"] == sorted(f"Integer {m}" for m in branch)
        assert failed["covered"] == 0 and failed["blocked_by_skip"] == []
        # A skip never adds coverage, even when another passing fixture already covers the same form.
        both = fc.measure({"cpu_leaf_aot_branches": "skip", "cpu_aot_direct_call": "pass"}, root)["x64_zen2"]
        direct = fc.masm_mnemonics(DIRECT)
        assert direct == {"sub", "call", "add", "ret"}, direct
        assert both["covered"] == len(fc.x64_forms(direct, reference)) == 4
        assert both["blocked_by_skip"] == sorted(f"Integer {m}" for m in branch - direct)

    # gfx1013: _e32 selects the plain encoding, _e64 the VOP3 form; any passing adapter counts.
    gfx = fc.load_reference("gfx1013.tsv")
    assert fc.gfx_forms({"v_interp_p1_f32_e32", "v_fmac_f32_e64", "exp"}, gfx) == {
        ("VINTRP", "v_interp_p1_f32"), ("VOP3", "v_fmac_f32_e64"), ("EXP", "exp")}
    assert fc.fixture_status({"pixel_aot_warp": "pass", "pixel_aot_hardware": "skip"},
                             ("pixel_aot_warp", "pixel_aot_hardware")) == "pass"
    assert fc.fixture_status({"pixel_aot_hardware": "skip"}, ("pixel_aot_warp", "pixel_aot_hardware")) == "skip"


def check_jump_tables():
    """switch.asm (#86): a skipped cpu_aot_jump_tables run contributes zero covered forms."""
    switch = fc.masm_mnemonics(SWITCH)
    assert switch == {"cmp", "ja", "lea", "movsxd", "add", "jmp", "neg", "ret"}, sorted(switch)
    with tempfile.TemporaryDirectory() as tmp:
        root = sample_repo(tmp, {"switch": SWITCH, "branch": BRANCH})
        passed = fc.measure({"cpu_aot_jump_tables": "pass"}, root)["x64_zen2"]
        skipped = fc.measure({"cpu_aot_jump_tables": "skip"}, root)["x64_zen2"]
        assert passed["covered"] == len(switch) == 8
        assert skipped["covered"] == 0 and skipped["blocked_by_skip"] == sorted(f"Integer {m}" for m in switch)
        # Next to a passing fixture, the skipped run still adds nothing: only branch.asm's forms count.
        mixed = fc.measure({"cpu_aot_jump_tables": "skip", "cpu_leaf_aot_branches": "pass"}, root)["x64_zen2"]
        assert mixed["covered"] == len(fc.masm_mnemonics(BRANCH)) == 8
        assert mixed["blocked_by_skip"] == sorted(f"Integer {m}" for m in switch - fc.masm_mnemonics(BRANCH))


def check_unclassified():
    """A CPU fixture missing from CPU_FIXTURES is reported, never counted, never fatal. Shader text in a
    test file counts for nothing: only translation records do."""
    with tempfile.TemporaryDirectory() as tmp:
        root = sample_repo(tmp, {"branch": BRANCH, "added_later": "f PROC\n    xor eax, eax\n    ret\nf ENDP\nEND\n"},
                           {"added_later_check.py": 'P = "s_mov_b32 s0, 0\\ns_endpgm"\n'})
        every_test_passed = {"cpu_leaf_aot_branches": "pass", "added_later": "pass", "added_later_check": "pass"}
        m = fc.measure(every_test_passed, root)
        assert m["unclassified"] == ["added_later.asm"], m["unclassified"]
        assert m["x64_zen2"]["covered"] == 8  # branch.asm only; xor stays uncovered
        assert ("Integer", "xor") in fc.x64_forms({"xor"}, fc.load_reference("x64_zen2.tsv"))
        assert m["gfx1013"]["covered"] == m["gfx1013"]["known_in_fixtures"] == 0
        report = fc.report(m)
        assert "Not counted until classified in tools/form_coverage.py: added_later.asm" in report
        assert "Shader translation records from this run: none" in report
        assert "Not counted" not in fc.report(fc.measure(every_test_passed, sample_repo(Path(tmp) / "b", {"branch": BRANCH})))


def check_shader_records():
    """gfx forms come only from programs the translator accepted, recorded by the same run. The review's
    example: a program that reaches only must_reject (s_nop in place of a wait below, s_branch in the real
    controls) must stay out of covered."""
    import pixel_aot_check as pixel  # tests/ is on sys.path when this file runs
    gfx = fc.load_reference("gfx1013.tsv")
    assert ("SOPP", "s_nop") in gfx  # so counting s_nop would change the result
    pixel.ACCEPTED.clear()
    program = pixel.assembly(False)
    pixel.must_reject(pixel.translate, [line.replace("s_waitcnt lgkmcnt(0)", "s_nop 0") for line in program])
    assert not pixel.ACCEPTED  # the rejected program left no trace
    pixel.translate(program)
    accepted = {line.split()[0] for line in program}
    assert pixel.ACCEPTED == accepted and "s_nop" not in accepted
    with tempfile.TemporaryDirectory() as tmp:
        root = sample_repo(Path(tmp) / "repo", {})
        record = Path(tmp) / "records" / "pixel_aot_warp.txt"
        pixel.write_record(record)
        now = time.time()
        records = fc.read_records(record.parent, (now - 60, now + 60))
        assert records == {"pixel_aot_warp": accepted}
        expected = len(fc.gfx_forms(accepted, gfx))
        passed = fc.measure({"pixel_aot_warp": "pass"}, root, records)["gfx1013"]
        skipped = fc.measure({"pixel_aot_warp": "skip"}, root, records)["gfx1013"]
        failed = fc.measure({"pixel_aot_warp": "fail"}, root, records)["gfx1013"]
        assert passed["covered"] == expected > 0
        assert skipped["covered"] == 0 and len(skipped["blocked_by_skip"]) == expected
        assert failed["covered"] == 0 and failed["blocked_by_skip"] == []
        # Negative control: had the rejected program been recorded, s_nop would be covered.
        leaked = fc.measure({"pixel_aot_warp": "pass"}, root, {"pixel_aot_warp": accepted | {"s_nop"}})["gfx1013"]
        assert leaked["covered"] == expected + 1
        # A record written outside the JUnit run comes from another run, so it is ignored.
        os.utime(record, (now - 3600, now - 3600))
        assert fc.read_records(record.parent, (now - 60, now + 60)) == {}
    # The same holds in the real controls. The scheduling-hint fixtures translate programs with s_nop
    # and the hints, so those forms are recorded; s_branch reaches only must_reject and stays out.
    assert ("SOPP", "s_branch") in gfx
    pixel.ACCEPTED.clear()
    with tempfile.TemporaryDirectory() as tmp:
        pixel.check_controls(Path(tmp))
    assert {"s_nop", "s_clause", "s_setprio", "s_sleep", "image_sample"} <= pixel.ACCEPTED
    assert "s_branch" not in pixel.ACCEPTED and "s_code_end" not in pixel.ACCEPTED
    # Every newly lowered 64-bit SOP1/SOP2 and 32-bit BFE form is counted in both gfx1013 and rdna2,
    # while rejected neighbors (exec save/restore, #257 ops, 64-bit BFE/cselect) stay out of covered.
    scalar64_forms = {
        ("SOP1", "s_cmov_b64"), ("SOP1", "s_not_b64"), ("SOP1", "s_brev_b64"),
        ("SOP2", "s_and_b64"), ("SOP2", "s_or_b64"), ("SOP2", "s_xor_b64"),
        ("SOP2", "s_andn2_b64"), ("SOP2", "s_orn2_b64"),
        ("SOP2", "s_lshl_b64"), ("SOP2", "s_lshr_b64"), ("SOP2", "s_ashr_i64"),
        ("SOP2", "s_bfm_b64"), ("SOP2", "s_bfe_u32"), ("SOP2", "s_bfe_i32"),
    }
    rejected_forms = {
        "s_and_saveexec_b64", "s_or_saveexec_b64", "s_andn2_saveexec_b64",
        "s_cselect_b64", "s_bfe_u64", "s_bfe_i64", "s_nand_b64", "s_nor_b64", "s_xnor_b64",
        "s_cmp_eq_u64", "s_bitcmp1_b64", "s_bfm_b32",
        "s_add_u32", "s_and_b32", "s_not_b32", "s_cmp_eq_i32", "s_cselect_b32",
    }
    assert not (pixel.ACCEPTED & rejected_forms), pixel.ACCEPTED & rejected_forms
    for name in ("gfx1013.tsv", "rdna2.tsv"):
        covered = fc.gfx_forms(pixel.ACCEPTED, fc.load_reference(name))
        assert scalar64_forms <= covered, (name, scalar64_forms - covered)


def check_parsing():
    with tempfile.TemporaryDirectory() as tmp:
        junit = Path(tmp) / "results.xml"
        junit.write_text(
            '<testsuite time="32" timestamp="2026-11-21T21:05:21">'
            '<testcase name="a" status="run"/>'
            '<testcase name="b" status="fail"/>'
            '<testcase name="c" status="notrun"/>'
            '<testcase name="d" status="run"><failure message="mismatch"/></testcase>'
            '<testcase name="e" status="run"><error message="crash"/></testcase>'
            '<testcase name="f" status="run"><skipped/></testcase>'
            '</testsuite>',
            encoding="utf-8",
        )
        results, window = fc.read_results(junit)
        assert results == {"a": "pass", "b": "fail", "c": "skip", "d": "fail", "e": "fail", "f": "skip"}, results
        start = datetime(2026, 11, 21, 21, 5, 21).timestamp()  # CTest writes local time
        assert window == (start - 1, start + 34), window
    asm = ("emit MACRO dst\nLOCAL skip\n    lock cmpxchg [rdx], eax\n    rep movsb\nskip:\nENDM\n"
           "x PROC FRAME\n    .endprolog\nIFDEF A\n    jae short l\nELSE\n    jnz short l\nENDIF\n"
           "l:  mov DWORD PTR [rdx], eax ; c\ng:: ud2\n    emit rax\nvalue DQ 0\n    dd 1\n    ret\nx ENDP\nEND\n")
    assert fc.masm_mnemonics(asm) == {"cmpxchg", "movsb", "jae", "jne", "mov", "ud2", "ret"}, fc.masm_mnemonics(asm)
    with tempfile.TemporaryDirectory() as tmp:
        isolated = fc.measure({}, sample_repo(tmp, {"branch": asm}))["x64_zen2"]
        assert isolated["fixture_forms_not_in_reference"] == [], isolated["fixture_forms_not_in_reference"]
    # The real repository measures without error, with no macro names or LOCAL leaking into unmatched forms.
    full = fc.measure({})
    assert "not a measure of port completion" in fc.report(full)
    assert full["x64_zen2"]["covered"] == full["gfx1013"]["covered"] == 0
    unmatched = full["x64_zen2"]["fixture_forms_not_in_reference"]
    assert {"delta", "local", "plane_request"}.isdisjoint(unmatched), unmatched


def check_dashboard():
    """tools/coverage_svg.py draws one square per reference form, coloured by its measured state."""
    import coverage_svg as svg
    with tempfile.TemporaryDirectory() as tmp:
        root = sample_repo(tmp, {"branch": BRANCH, "switch": SWITCH})
        m = fc.measure({"cpu_leaf_aot_branches": "pass", "cpu_aot_jump_tables": "skip"}, root)
    drawn = svg.render(m, "a test run")
    assert drawn == svg.render(m, "a test run") and fc.measure({})["note"] == svg.NOTE in drawn
    assert "%" not in drawn  # counts only: coverage is not a completion percentage
    squares = {svg.COVERED: 0, svg.HELD: 0, svg.OPEN: 0}
    for g in ET.fromstring(drawn).iter("{http://www.w3.org/2000/svg}g"):
        if g.get("fill") in squares:
            squares[g.get("fill")] += len(g)
    held = fc.masm_mnemonics(SWITCH) - fc.masm_mnemonics(BRANCH)
    total = sum(m[key]["total"] for key, _, _ in svg.AREAS)
    assert squares == {svg.COVERED: 8, svg.HELD: len(held), svg.OPEN: total - 8 - len(held)}, squares
    # Every group, down to the one-form EXP box, keeps its squares and label inside its own box, and is
    # labelled there or in the panel's "Too small to label" line.
    root = ET.fromstring(drawn)
    ns = "{http://www.w3.org/2000/svg}"
    boxes = [box for box in root.iter(f"{ns}svg") if box is not root]
    groups = [(name, g) for key, _, _ in svg.AREAS for name, g in m[key]["groups"].items() if g["total"]]
    assert len(boxes) == len(groups), (len(boxes), len(groups))
    labels = []
    for box in boxes:
        w, h = float(box.get("width")), float(box.get("height"))
        for cell in box.iter(f"{ns}rect"):
            right = float(cell.get("x", 0)) + float(cell.get("width"))
            bottom = float(cell.get("y", 0)) + float(cell.get("height"))
            assert right <= w + 0.01 and bottom <= h + 0.01, (box.attrib, cell.attrib)
        for label in box.iter(f"{ns}text"):
            assert len(label.text) * svg.LABEL_CHAR + 4 <= w and float(label.get("y")) <= h, (box.attrib, label.text)
            labels.append(label.text)
    footnotes = "".join(t.text for t in root.iter(f"{ns}text") if t.text.startswith("Too small to label: "))
    for name, g in groups:
        entry = f"{name} {g['covered']}/{g['total']}"
        assert entry in labels or entry in footnotes, entry
    assert "EXP 0/1" in footnotes  # the smallest group cannot hold its label


if __name__ == "__main__":
    check_denominators()
    check_example()
    check_jump_tables()
    check_unclassified()
    check_shader_records()
    check_parsing()
    check_dashboard()
    print("form coverage checks passed")
