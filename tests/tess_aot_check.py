"""Exercise offline tessellation translation (cards T-1 and T-2, docs/design/stages.md).

Modes:
    tess_aot_check.py --list-families
    tess_aot_check.py controls <tess_reference>                              no DXC, no GPU
    tess_aot_check.py tessellator <dxc> <offscreen_check> warp|hardware <tess_reference>
    tess_aot_check.py draw <dxc> <offscreen_check> warp|hardware <tess_reference> [--family NAME ...]
    tess_aot_check.py binary <llvm-mc> <llvm-objcopy>                        assemble, disassemble (wave64), lower again

"tessellator" measures the desktop tessellator against the D3D11 reference (tests/tess_tessellator.py) for every
domain, partitioning and winding and fails unless each partitioning tools/tess_aot.py accepts is exact.

A draw translates an LS+HS program with tools/tess_aot.py into a vertex shader (vs_6_0) and a hull shader (hs_6_0)
and its evaluation program into a domain shader (ds_6_0), draws patches through the three, captures the domain
shader's output by stream output and compares it with a reference computed here (tests/tess_model.py): the merged
LS+HS waves run instruction by instruction, frame included, and write the TF ring and the off-chip ring; the D3D11
reference tessellator (tests/tess_reference.cpp) turns each patch's TF ring words into domain points and triangles; the
evaluation waves run over those points with the console's entry registers. The comparison is of the multiset of
triangles, each a rotation-normalized triple of output records (the tessellator's emission order is not part of the
contract, the winding is), bit for bit. Each family also proves that its wrong references are caught: the factors of
two edges swapped, the winding flipped, the two domain coordinates swapped, the patch constants written by control
point 1 instead of 0.

The families: "scene" and "eds2" are the committed RADV dumps of the two corpus pipelines whose control and evaluation
programs both translate (SaschaWillems pipelinestatistics, MIT; Vulkan-Samples extended_dynamic_state2, Apache-2.0;
tests/corpus/README.md), with their pipeline state and user-SGPR roles as tools/stage_corpus_report.py reads them;
"pervertex" is the eds2 control program with its first edge factor computed from control point 0's position
(max(uniform, x)), drawn with every partitioning tools/tess_aot.py accepts.
"""
from collections import Counter
import os
from pathlib import Path
import random
import re
import struct
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tests"))
import corpus_translate  # noqa: E402
import stage_corpus_report  # noqa: E402
import tess_aot  # noqa: E402
import tess_model as tm  # noqa: E402
import tess_tessellator as tt  # noqa: E402
from pixel_aot_ops.dispatch import claimants  # noqa: E402
import vertex_aot_check as vc  # noqa: E402

STAGES = ROOT / "tests" / "corpus" / "isa" / "stages"
ACCEPTED = set()
TRANSLATED = {"sascha__pipelinestatistics__scene.tese.s", "sascha__pipelinestatistics__scene.vert.s",
              "vksamples__extended_dynamic_state2__glsl__tess.tese.s",
              "vksamples__extended_dynamic_state2__glsl__tess.vert.s",
              "vksamples__patch_control_points__glsl__tess.tese.s"}


def write_record(path):
    if path:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text("".join(f"{word}\n" for word in sorted(ACCEPTED)), encoding="utf-8")


def record(program):
    lines = [line.split(";")[0].strip() for line in program]
    ACCEPTED.update(line.split()[0] for line in lines if line and not line.endswith(":") and not line.startswith("#"))
    for line in lines:
        if line and not line.endswith(":") and len(families := claimants(line)) > 1:
            raise AssertionError(f"Forms of more than one family match {line!r}: {', '.join(families)}")


def lower(lshs, tes, ls_roles, tes_roles, state):
    vs, hs, hs_layout = tess_aot.lower_lshs(lshs, ls_roles, state)
    ds, ds_layout = tess_aot.lower_tes(tes, tes_roles, state)
    record(lshs)
    record(tes)
    return vs, hs, ds, hs_layout, ds_layout


def replace(program, old, new, count=1):
    text = "\n".join(program)
    assert old in text, old
    return text.replace(old, new, count).split("\n")


# --- families ----------------------------------------------------------------------------------------------------------

def corpus_pipeline(stem):
    lshs = corpus_translate.read_dump(STAGES / f"{stem}.vert.s")
    tes = corpus_translate.read_dump(STAGES / f"{stem}.tese.s")
    state = stage_corpus_report.tess_state(f"{stem}.vert.s")
    return (lshs, tes, stage_corpus_report.tess_contract(lshs, "lshs"), stage_corpus_report.tess_contract(tes, "tes"),
            state)


def f32(value):
    return struct.unpack("<I", struct.pack("<f", value))[0]


def vertex_memory(seed):
    """Vertex attributes (x in 1..9 so that a factor computed from it varies, y and z in -4..4, w words from
    tests/vertex_aot_check.py's float words) for 4096 vertices of 16 bytes, at a base above 4 GiB."""
    rnd = random.Random(seed)
    words = []
    for w in vc.float_words(seed, 4096):
        words += [f32(rnd.uniform(1.0, 9.0)), f32(rnd.uniform(-4.0, 4.0)), f32(rnd.uniform(-4.0, 4.0)), w]
    return vc.Memory([(vc.HIGH_BASE, vc.words_bytes(words))])


def draw_sets(seed, factors):
    """(constants, memory, descriptors, push, patches) per set: the V#s of descriptor words 0..11 read three attributes
    of a 48-byte vertex (16-byte records interleaved), the first constant word the tessellation factor."""
    out = []
    for j, (factor, patches) in enumerate(factors):
        constants = vc.float_words(seed + j, 64)
        constants[0] = f32(factor)
        descriptors = [0] * 64
        for k in range(3):
            descriptors[4 * k:4 * k + 4] = vc.vsharp(vc.HIGH_BASE + 16 * k, 48, 1024, 0)
        out.append((constants, vertex_memory(seed + j), descriptors, vc.float_words(seed + 20 + j, 16), patches))
    return out


def pervertex(stem="vksamples__extended_dynamic_state2__glsl__tess"):
    lshs, tes, ls_roles, tes_roles, state = corpus_pipeline(stem)
    return replace(lshs, "v_mov_b32_e32 v8, s5", "v_max_f32_e32 v8, s5, v2"), tes, ls_roles, tes_roles, state


ALL_FLAWS = [{"factors_swapped"}, {"winding_flipped"}, {"domain_swapped"}, {"cp1"}]
SYMMETRIC_FLAWS = [{"winding_flipped"}, {"domain_swapped"}]  # uniform factors: swapping two edges changes nothing


def families():
    """name -> [(pipeline, state overrides, sets, wrong references)]."""
    return {
        # Factors (1, 1, 1; 2) the program writes itself, three exported parameters, 30 patches in two waves.
        "scene": [(corpus_pipeline("sascha__pipelinestatistics__scene"), {}, draw_sets(11, [(1.0, 30), (1.0, 7)]),
                   SYMMETRIC_FLAWS)],
        # The factor from a constant buffer (clamped to 1.0 when not above 0), push constants in the evaluation shader.
        "eds2": [(corpus_pipeline("vksamples__extended_dynamic_state2__glsl__tess"), {},
                  draw_sets(21, [(3.0, 25), (6.4, 9), (-2.0, 4)]), SYMMETRIC_FLAWS)],
        # The first edge factor from control point 0, fractional factors, every accepted partitioning.
        "pervertex": [(pervertex(), {"partitioning": p}, draw_sets(31 + k, [(2.5, 25), (4.0, 44)]), ALL_FLAWS)
                      for k, p in enumerate(p for p in tess_aot.PARTITIONINGS
                                            if p not in tess_aot.REFUSED_PARTITIONINGS)],
    }


def targets_of(ds_layout):
    """Export targets in stream-output order and their semantic codes (0 SV_Position, 1 + n TEXCOORDn)."""
    params = sorted(ds_layout["params"])
    return ["pos0", *(f"param{n}" for n in params)], [0, *(1 + n for n in params)]


class Reference:
    def __init__(self, tool):
        self.tool = tool

    def __call__(self, domain, partitioning, topology, rows):
        return tt.run_reference(self.tool, domain, partitioning, topology, rows)


def model_draw(pipeline, state, data, tool, flaws=()):
    lshs, tes, ls_roles, tes_roles, _ = pipeline
    constants, memory, descriptors, push, patches = data
    ls = tm.Context(ls_roles, constants, descriptors, push, memory)
    te = tm.Context(tes_roles, constants, descriptors, push, memory)
    _, ds_layout = tess_aot.lower_tes(tes, tes_roles, state)
    targets, _ = targets_of(ds_layout)
    return tm.draw_reference(lshs, tes, state, ls, te, patches, Reference(tool), targets, flaws)


def captured_triangles(records):
    assert len(records) % 3 == 0, len(records)
    return Counter(tm.canonical(tuple(tuple(r) for r in records[k:k + 3])) for k in range(0, len(records), 3))


# --- draws -------------------------------------------------------------------------------------------------------------

def run_family(directory, compiler, renderer, backend, tool, name):
    for index, (pipeline, overrides, sets, flaws) in enumerate(families()[name]):
        lshs, tes, ls_roles, tes_roles, base = pipeline
        state = tess_aot.check_state({**base, **overrides})
        vs, hs, ds, hs_layout, ds_layout = lower(lshs, tes, ls_roles, tes_roles, state)
        _, semantics = targets_of(ds_layout)
        tag = f"{name}{index}"
        shaders = [tt.compile_shader(compiler, vs, directory, f"{tag}_vs", "vs_6_0"),
                   tt.compile_shader(compiler, hs, directory, f"{tag}_hs", "hs_6_0"),
                   tt.compile_shader(compiler, ds, directory, f"{tag}_ds", "ds_6_0")]
        separated = dict.fromkeys(map(frozenset, flaws), False)
        for data in sets:
            constants, memory, descriptors, push, patches = data
            want, factors = model_draw(pipeline, state, data, tool)
            assert want, f"{tag}: the reference draws no triangles"
            count = sum(want.values())
            case = tt.tess_case(state["output_control_points"], patches, semantics, 2 * 3 * count + 192, constants,
                                descriptors, push, memory.section())
            code, captured = tt.capture(renderer, backend, shaders, directory / f"{tag}.case", case,
                                        directory / f"{tag}.out")
            if code == 77:
                return 77
            got = captured_triangles(captured[1])
            print(f"tess_aot {backend} {tag} {state['partitioning']} {state['topology']}: patches={patches} "
                  f"triangles={sum(got.values())} reference={count} factors={sorted({tuple(r) for r in factors})[:3]}",
                  flush=True)
            if got != want:
                only_ref, only_gpu = sorted(want - got)[:1], sorted(got - want)[:1]
                raise AssertionError(f"{tag}: the draw differs from the reference ({sum(got.values())} triangles, "
                                     f"{count} expected); only in the reference {only_ref}; only on the desktop "
                                     f"{only_gpu}")
            for flaw in separated:
                wrong, _ = model_draw(pipeline, state, data, tool, flaw)
                if wrong != want:
                    separated[flaw] = True
                    assert got != wrong, f"{tag}: the capture matches a wrong reference ({sorted(flaw)})"
        missing = [sorted(f) for f, seen in separated.items() if not seen]
        assert not missing, f"{tag}: these wrong references never differ from the right one: {missing}"
    return 0


def check_render(directory, compiler, renderer, backend, tool, names):
    for name in names or families():
        code = run_family(directory, compiler, renderer, backend, tool, name)
        if code:
            return code
    return 0


# --- controls ----------------------------------------------------------------------------------------------------------

def check_translation_shape():
    rows = {path.name: stage_corpus_report.translate(path) for path in sorted(STAGES.glob("*.s"))}
    tess = {name: row for name, row in rows.items() if row[0] in ("lshs", "hs", "tes")}
    assert len(rows) == 22 and len(tess) == 16, (len(rows), len(tess))
    translated = {name for name, row in tess.items() if row[3] == "translated"}
    assert translated == TRANSLATED, sorted(translated ^ TRANSLATED)
    for name, row in tess.items():
        if name not in translated:
            assert "crash" not in row[5], (name, row[5])
    lshs, tes, ls_roles, tes_roles, state = corpus_pipeline("vksamples__extended_dynamic_state2__glsl__tess")
    vs, hs, ds, hs_layout, ds_layout = lower(lshs, tes, ls_roles, tes_roles, tess_aot.check_state(state))
    assert hs_layout["inputs"] == "temp" and hs_layout["vote"] and hs_layout["factors"] == 4, hs_layout
    assert '[partitioning("integer")]' in hs and '[outputtopology("triangle_cw")]' in hs and \
        "[outputcontrolpoints(3)]" in hs and '[patchconstantfunc("patch_constants")]' in hs
    assert "SV_TessFactor" in hs and "SV_InsideTessFactor" in hs and "SV_OutputControlPointID" in hs
    assert "SV_DomainLocation" in ds and "OutputPatch<HsControlPoint, 3>" in ds and "struct LsOutput" in vs
    # The per-vertex factor reads control point 0's input in the patch-constant function.
    _, hs, _ = tess_aot.lower_lshs(pervertex()[0], ls_roles, tess_aot.check_state(state))
    constants = hs[hs.index("HsPatch patch_constants"):hs.index("[domain")]
    assert "uint cpid = 0u;" in constants and "max(asfloat(salu8), asfloat(lsin0))" in constants, constants


def must_refuse(fn, reason):
    try:
        fn()
    except ValueError as error:
        if reason not in str(error):
            raise AssertionError(f"Refused for another reason: {error} (expected {reason!r})")
        return
    raise AssertionError(f"Accepted a program that must be refused ({reason})")


def check_refusals():
    lshs, tes, lr, trr, state = corpus_pipeline("vksamples__extended_dynamic_state2__glsl__tess")
    terrain = corpus_pipeline("vksamples__terrain_tessellation__glsl__terrain")
    hs = lambda p=lshs, s=state, r=lr: (lambda: tess_aot.lower_lshs(p, r, s))  # noqa: E731
    ds = lambda p=tes, s=state: (lambda: tess_aot.lower_tes(p, trr, s))  # noqa: E731
    refusals = [
        # Pipeline state: the measured partitioning, isolines, point mode, the ring stride.
        (hs(s={**state, "partitioning": "fractional_odd"}), "Refused partitioning fractional_odd"),
        (ds(s={**state, "partitioning": "fractional_odd"}), "Refused partitioning fractional_odd"),
        (hs(s={**state, "domain": "isoline"}), "isolines"),
        (hs(s={**state, "topology": "point"}), "point mode"),
        (hs(s={**state, "attr_stride": 1000}), "multiple of 256"),
        # The HS frame and its rings.
        (hs(replace(lshs, "v_cmpx_eq_i32_e32 0, v0", "v_cmpx_eq_i32_e32 1, v0")), "exec use"),
        (hs(replace(lshs, "s_load_dwordx4 s[16:19], s[0:1], 0x50", "s_load_dwordx4 s[16:19], s[0:1], 0x40")),
         "is not the TF or off-chip ring"),
        (hs(replace(lshs, "buffer_store_dwordx4 v[8:11], v0, s[16:19], s4 offen glc",
                    "buffer_store_dwordx4 v[8:11], v0, s[16:19], s4 offen offset:16 glc")), "TF ring word 4"),
        (hs(replace(lshs, "v_mov_b32_e32 v8, s5", "s_cbranch_vccz BB44\nv_mov_b32_e32 v8, s5")), "control flow"),
        (hs(replace(lshs, "buffer_store_dwordx4 v[8:11], v0, s[12:15], s2 offen glc",
                    "buffer_store_dwordx4 v[8:11], v0, s[12:15], s2 offen offset:1024 glc")), "ring slot 1"),
        (hs(replace(lshs, "v_add_nc_u32_e32 v2, s5, v2", "v_add_nc_u32_e32 v2, s5, v2\nv_add_nc_u32_e32 v2, v1, v2")),
         "relative ids (v1)"),
        (hs(replace(lshs, "v_mov_b32_e32 v8, s5", "v_cvt_f32_u32_e32 v8, v0")), "frame value"),
        (hs(replace(lshs, "v_mov_b32_e32 v8, s5", "ds_read_b32 v8, v1")), "not an HS input read"),
        (hs(replace(lshs, "v_mov_b32_e32 v8, s5", "v_mov_b32_e32 v8, s3")), "hardware SGPR s3"),
        (hs(replace(lshs, "v_cndmask_b32_e32 v8, 0, v2, vcc", "v_cndmask_b32_e32 v8, s10, v2, vcc")),
         "only invocation 0's region writes"),
        (hs(replace(lshs, "v_bfe_u32 v0, v1, 8, 5", "v_bfe_u32 v0, v1, 0, 8")), "exec use"),
        (hs(terrain[0], terrain[4], terrain[2]), "the LS half writes its outputs to LDS"),
        # The evaluation program.
        (ds(replace(tes, "offset:32 glc dlc", "offset:48 glc dlc")), "past the 3 control points"),
        (ds(replace(tes, "offset:32 glc dlc", "offset:1056 glc dlc")), "ring slot 1"),
        (ds(replace(tes, "v_add_f32_e32 v14, v5, v6", "v_add_f32_e32 v14, s4, v6")), "hardware SGPR s4"),
        (ds(replace(tes, "v_add_f32_e32 v14, v5, v6", "ds_read_b32 v14, v6")), "lane-cooperative"),
        (ds(replace(tes, "v_mul_u32_u24_e32 v7, 48, v7", "v_mul_u32_u24_e32 v7, 48, v8")), "not an off-chip ring read"),
        (ds(replace(tes, "v_mul_u32_u24_e32 v7, 48, v7", "v_mul_u32_u24_e32 v7, 32, v7")), "not an off-chip ring read"),
        (ds(replace(tes, "v_add_f32_e32 v14, v5, v6", "s_cbranch_vccz BB15\nv_add_f32_e32 v14, v5, v6")),
         "control flow"),
        (ds(s={**state, "domain": "quad", "output_control_points": 4}), "not an off-chip ring read"),
    ]
    for fn, reason in refusals:
        must_refuse(fn, reason)
    return len(refusals)


def check_reference(tool):
    """Every family's model draws triangles, and every wrong reference changes the triangles of some set."""
    for name, entries in families().items():
        for pipeline, overrides, sets, flaws in entries:
            state = tess_aot.check_state({**pipeline[4], **overrides})
            seen = dict.fromkeys(map(frozenset, flaws), False)
            for data in sets:
                want, _ = model_draw(pipeline, state, data, tool)
                assert want, name
                for flaw in seen:
                    if not seen[flaw] and model_draw(pipeline, state, data, tool, flaw)[0] != want:
                        seen[flaw] = True
            assert all(seen.values()), (name, [sorted(f) for f, ok in seen.items() if not ok])


def check_controls(tool):
    check_translation_shape()
    refused = check_refusals()
    check_reference(tool)
    print(f"tess_aot controls ok: {refused} refusals, {len(TRANSLATED)} corpus programs translate")


def check_tessellator(directory, compiler, renderer, backend, tool):
    """Every configuration is measured and printed; the check fails when one whose partitioning tools/tess_aot.py
    accepts is not exact (a refused partitioning is reported, and may be exact on one adapter and not another)."""
    results, skipped = tt.check(directory, compiler, renderer, backend, tool)
    if skipped:
        return 77
    bad = sorted(config for config, exact in results.items() if not exact)
    accepted_bad = [config for config in bad if config[1] not in tess_aot.REFUSED_PARTITIONINGS]
    print(f"tessellator {backend}: {len(results) - len(bad)} of {len(results)} configurations exact; inexact: "
          f"{bad or 'none'}; refused partitionings: {sorted(tess_aot.REFUSED_PARTITIONINGS) or 'none'}")
    if accepted_bad:
        print(f"tessellator {backend}: an accepted partitioning is inexact: {accepted_bad}")
    return 1 if accepted_bad else 0


# --- binary ------------------------------------------------------------------------------------------------------------

def llvm_disassemble(assembler, code):
    text = " ".join(f"0x{b:02x}" for b in code)
    result = subprocess.run([assembler, "--disassemble", "--show-encoding", "-triple=amdgcn--amdpal", "-mcpu=gfx1013",
                             "-mattr=+wavefrontsize64"], input=text, capture_output=True, text=True, check=True)
    out, offset = [], 0
    for line in result.stdout.splitlines():
        if not (m := re.fullmatch(r"\s*(.*?)\s*(?://|;)\s*encoding:\s*\[(.*)\]\s*", line)):
            continue
        out.append((offset, " ".join(m[1].split())))
        offset += len(m[2].split(","))
    assert offset == len(code), (offset, len(code))
    return out


def roundtrip(directory, assembler, objcopy, program):
    import pixel_aot
    source, obj, binary = directory / "t.s", directory / "t.o", directory / "t.bin"
    text = [line.split(";")[0].strip() for line in program]
    source.write_text("\n".join(line for line in text if line and not line.startswith("#")) + "\n", encoding="ascii")
    subprocess.run([assembler, "-triple=amdgcn--amdpal", "-mcpu=gfx1013", "-mattr=+wavefrontsize64",
                    "-filetype=obj", source, "-o", obj], check=True)
    subprocess.run([objcopy, "-O", "binary", "--only-section=.text", obj, binary], check=True)
    code = binary.read_bytes()
    return pixel_aot.name_branch_targets(llvm_disassemble(assembler, code), len(code))


def check_binary(directory, assembler, objcopy):
    """Assemble each drawn program (wave64), disassemble it with llvm-mc, name its branch targets as a native program's
    would be, and lower it again: every HLSL source must be the same."""
    count = 0
    for entries in families().values():
        for (lshs, tes, lr, trr, base), overrides, _, _ in entries[:1]:
            state = tess_aot.check_state({**base, **overrides})
            decoded = roundtrip(directory, assembler, objcopy, lshs), roundtrip(directory, assembler, objcopy, tes)
            assert lower(*decoded, lr, trr, state)[:3] == lower(lshs, tes, lr, trr, state)[:3], base
            count += 2
    print(f"tess_aot binary ok: {count} programs")


def main():
    mode, *args = sys.argv[1:]
    if mode == "--list-families":
        print("\n".join(families()))
        return 0
    names = []
    while "--family" in args:
        at = args.index("--family")
        names.append(args[at + 1])
        del args[at:at + 2]
    unknown = [name for name in names if name not in families()]
    if unknown or (names and mode != "draw"):
        raise ValueError(f"Unknown or misplaced --family {unknown}; known families: {', '.join(families())}")
    with tempfile.TemporaryDirectory() as tmp:
        directory = Path(tmp)
        if mode == "tessellator":
            return check_tessellator(directory, *args)
        if mode == "controls":
            check_controls(*args)
        elif mode == "binary":
            check_binary(directory, *args)
        elif mode == "draw":
            return check_render(directory, *args, names)
        else:
            raise ValueError("Expected controls, tessellator, binary or draw mode")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        write_record(os.environ.get("FORM_COVERAGE_RECORD"))
