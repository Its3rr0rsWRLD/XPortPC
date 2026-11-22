"""Draw family `exports`: pixel_aot_check.py draw --family exports.

Pixel exports beyond the single compressed mrt0: several render targets (exp mrt0..mrt7) with their component masks
(including masks with gaps) and both data layouts (compressed binary16 pairs and uncompressed binary32 words), depth
(exp mrtz, SV_Depth), and a program whose only export is exp null (a pixel shader without outputs). The draws use the
renderer's --check-pixel-outputs case (tests/pixel_aot_render.cpp): R32G32B32A32_FLOAT targets cleared to -1, each drawn
with the write mask the lowering names for it (forms/exp.py WRITE_MASKS, checked against the export's en mask here) so
that a component the export leaves off keeps -1, and optionally a D32_FLOAT depth target cleared to 1. Every target and
the depth are compared bit-exactly per texel.
"""
import struct
import subprocess

from pixel_aot import disassemble

from pixel_aot_ops.dispatch import dispatch
from pixel_aot_ops.forms.exp import WRITE_MASKS, write_masks
from pixel_aot_ops.lowering import Lowering

from .common import RAMP, assembly, f32, half_rtz, half_value, translate, with_constants

CLEAR = -1.0
DEPTH_CLEAR = 1.0
OUTPUTS_MAGIC = 0x4f573258  # 'X2WO'

asfloat = lambda word: struct.unpack("<f", struct.pack("<I", word))[0]


def texels():
    """(r, g, b, a) of the sample at each texel, row-major: the binary32 values of the UNORM8 texture."""
    return [(f32(x / 255), f32(y / 255), f32(128 / 255), 1.0) for y in RAMP for x in RAMP]


def h(value):
    """A binary32 value packed by v_cvt_pkrtz_f16_f32 and exported compressed: rounded toward zero to binary16."""
    return half_rtz(value)


def outputs_case(constants, masks, colours, depth=None):
    """The --check-pixel-outputs case: constants, header, masks, 64 float4 per target, then 64 depths."""
    data = bytearray(constants) + struct.pack("<4I", OUTPUTS_MAGIC, len(masks), depth is not None, 0)
    data += struct.pack(f"<{len(masks)}I", *masks)
    for target in colours:
        assert len(target) == 64
        data += b"".join(struct.pack("<4f", *texel) for texel in target)
    if depth is not None:
        assert len(depth) == 64
        data += struct.pack("<64f", *depth)
    return bytes(data)


def program(body, exports):
    """with_constants (s44..s47 = constant words 3..6, the sample in v12..v15) with `body` before the packs, which leave
    the pkrtz pairs (v12, v13) in v16 and (v14, v15) in v17, and `exports` in place of the single mrt0 export."""
    lines = with_constants(body)
    at = lines.index("exp mrt0 v16, v16, v17, v17 done compr vm")
    lines[at:at + 1] = exports
    return lines


WORDS = ["v_mov_b32_e32 v18, s44", "v_mov_b32_e32 v19, s45", "v_mov_b32_e32 v20, s46", "v_mov_b32_e32 v21, s47"]

# Eight targets, exported out of order, with every mask and layout the lowering accepts: compressed RGBA from pkrtz
# pairs (mrt0), compressed RG of a raw word (mrt1), uncompressed RGBA, R, RG and RGB (mrt2..mrt5), compressed RGBA of a
# raw word and a pair (mrt6) and compressed RG of a pair, done (mrt7).
MRT_EXPORTS = [
    "exp mrt2 v12, v13, v14, v15",
    "exp mrt0 v16, v16, v17, v17 compr",
    "exp mrt1 v18, v18, off, off compr",
    "exp mrt3 v19, off, off, off",
    "exp mrt4 v13, v12, off, off",
    "exp mrt5 v20, v21, v12, off",
    "exp mrt6 v18, v18, v17, v17 compr",
    "exp mrt7 v16, v16, off, off done compr vm",
]
MRT_MASKS = [0xf, 0x3, 0xf, 0x1, 0x3, 0x7, 0xf, 0x3]


def mrt_reference(words):
    a, b, c, d = words
    lo, hi = half_value(a), half_value(a >> 16)
    targets = [[] for _ in range(8)]
    for r, g, bl, al in texels():
        targets[0].append((h(r), h(g), h(bl), h(al)))
        targets[1].append((lo, hi, CLEAR, CLEAR))
        targets[2].append((r, g, bl, al))
        targets[3].append((asfloat(b), CLEAR, CLEAR, CLEAR))
        targets[4].append((g, r, CLEAR, CLEAR))
        targets[5].append((asfloat(c), asfloat(d), r, CLEAR))
        targets[6].append((lo, hi, h(bl), h(al)))
        targets[7].append((h(r), h(g), CLEAR, CLEAR))
    return targets


def replace(targets, target, channel, values):
    wrong = [list(t) for t in targets]
    wrong[target] = [tuple(v if c != channel else values[k] for c, v in enumerate(texel))
                     for k, texel in enumerate(wrong[target])]
    return wrong


def mrt_wrongs(targets, words):
    a, b, c, d = words
    lo, hi = half_value(a), half_value(a >> 16)
    rgba = texels()
    swapped = [list(t) for t in targets]
    swapped[0], swapped[6] = swapped[6], swapped[0]
    return [
        ("mrt1 halves swapped", replace(replace(targets, 1, 0, [hi] * 64), 1, 1, [lo] * 64)),
        ("mrt1 mask ignored", replace(targets, 1, 2, [0.0] * 64)),
        ("mrt2 exported as binary16", replace(targets, 2, 0, [h(t[0]) for t in rgba])),
        ("mrt3 another word", replace(targets, 3, 0, [asfloat(c)] * 64)),
        ("mrt4 sources in order", replace(targets, 4, 0, [t[0] for t in rgba])),
        ("mrt5 third source", replace(targets, 5, 2, [t[1] for t in rgba])),
        ("mrt5 mask widened", replace(targets, 5, 3, [0.0] * 64)),
        ("mrt0 and mrt6 swapped", swapped),
        ("mrt6 word halves swapped", replace(targets, 6, 0, [hi] * 64)),
        ("mrt7 written as RGBA", replace(targets, 7, 2, [h(t[2]) for t in rgba])),
        ("mrt7 from the second pair", replace(targets, 7, 0, [h(t[2]) for t in rgba])),
    ]


# Masks with gaps, which the pipeline's write mask leaves at the clear value: uncompressed R+B (mrt0), compressed BA of a
# pkrtz pair (mrt1), uncompressed G+A of raw words (mrt2), uncompressed A alone (mrt3) and compressed BA of a raw word,
# done (mrt4).
GAP_EXPORTS = [
    "exp mrt0 v12, off, v14, off",
    "exp mrt1 off, off, v17, v17 compr",
    "exp mrt2 off, v19, off, v21",
    "exp mrt3 off, off, off, v13",
    "exp mrt4 off, off, v18, v18 done compr vm",
]
GAP_MASKS = [0x5, 0xc, 0xa, 0x8, 0xc]


def gap_reference(words):
    a, b, c, d = words
    lo, hi = half_value(a), half_value(a >> 16)
    targets = [[] for _ in range(5)]
    for r, g, bl, al in texels():
        targets[0].append((r, CLEAR, bl, CLEAR))
        targets[1].append((CLEAR, CLEAR, h(bl), h(al)))
        targets[2].append((CLEAR, asfloat(b), CLEAR, asfloat(d)))
        targets[3].append((CLEAR, CLEAR, CLEAR, g))
        targets[4].append((CLEAR, CLEAR, lo, hi))
    return targets


def gap_wrongs(targets, words):
    a, b, c, d = words
    lo, hi = half_value(a), half_value(a >> 16)
    rgba = texels()
    return [
        ("mrt0 gap written", replace(targets, 0, 1, [0.0] * 64)),
        ("mrt0 tail written", replace(targets, 0, 3, [0.0] * 64)),
        ("mrt1 pair in R and G", replace(replace(targets, 1, 0, [h(t[2]) for t in rgba]), 1, 1, [h(t[3]) for t in rgba])),
        ("mrt1 low pair written", replace(targets, 1, 0, [0.0] * 64)),
        ("mrt2 sources shifted down", replace(targets, 2, 0, [asfloat(b)] * 64)),
        ("mrt2 gap written", replace(targets, 2, 2, [0.0] * 64)),
        ("mrt3 in R", replace(replace(targets, 3, 0, [t[1] for t in rgba]), 3, 3, [CLEAR] * 64)),
        ("mrt4 halves swapped", replace(replace(targets, 4, 2, [hi] * 64), 4, 3, [lo] * 64)),
        ("mrt4 low pair placeholder written", replace(targets, 4, 0, [0.0] * 64)),
    ]


# Constant words 3..6: a word of two binary16 halves (a normal, then a negative subnormal or a normal) and binary32
# words exported as they are. No NaN, infinity or binary32 denormal: those reach the target through desktop float
# outputs, which this check does not claim to keep bit-exact.
MRT_WORDS = ((0x80013c01, 0x3f800001, 0xc0490fdb, 0x00800000), (0x4d00b555, 0xbf7fffff, 0x47efff00, 0x3eaaaaab))

# Depth with colour, both orders: mrtz before the done colour export, and after it as the done export.
DEPTH_PROGRAMS = (
    (["v_mul_f32_e32 v18, 0.5, v13"], ["exp mrtz v18, off, off, off", "exp mrt0 v16, v16, v17, v17 done compr vm"],
     lambda r, g, w: f32(g / 2)),
    (["v_mov_b32_e32 v19, s44"], ["exp mrt0 v16, v16, v17, v17 compr", "exp mrtz v19, off, off, off done vm"],
     lambda r, g, w: asfloat(w)),
    (["v_mov_b32_e32 v19, s44"], ["exp mrt0 v16, v16, v17, v17 compr", "exp mrtz v12, off, off, off done vm"],
     lambda r, g, w: r),
)
DEPTH_WORD = 0x3e800001  # a depth in (0, 1) with a low mantissa bit set

# The only export is exp null: main has no outputs; the draw binds no render target and checks the depth target.
NULL_EXPORT = "exp null off, off, off, off done vm"


def null_program():
    lines = assembly(False)
    first = lines.index("v_cvt_pkrtz_f16_f32_e32 v16, v12, v13")
    lines[first:lines.index("s_endpgm")] = [NULL_EXPORT]
    return lines


def colour_reference():
    return [(h(r), h(g), h(b), h(a)) for r, g, b, a in texels()]


def check_exports_draws(directory, compiler, renderer, backend):
    case = directory / "exports.case"

    def run(name, instructions, constants, masks, colours, depth, wrongs):
        source = directory / f"{name}.hlsl"
        shader = directory / f"{name}.cso"
        text = translate(instructions)
        # The masks the renderer applies are the ones the lowering names, which are the exports' en masks.
        assert write_masks(text) == dict(enumerate(masks)), (name, write_masks(text), masks)
        source.write_text(text, encoding="ascii")
        subprocess.run([compiler, "-Gis", "-T", "ps_6_0", "-E", "main", "-Fo", shader, source], check=True)
        draw = [renderer, backend, "--check-pixel-outputs", shader, case]
        right = outputs_case(constants, masks, colours, depth)
        case.write_bytes(right)
        subprocess.run(draw, check=True)
        for label, wrong_colours, wrong_depth in wrongs:
            wrong = outputs_case(constants, masks, wrong_colours, wrong_depth)
            assert wrong != right, (name, label)
            case.write_bytes(wrong)
            result = subprocess.run(draw, capture_output=True, text=True)
            if result.returncode != 1 or "pixel_mismatch" not in result.stderr:
                raise AssertionError(f"A wrong export result escaped detection in {name}: {label}")

    for index, words in enumerate(MRT_WORDS):
        constants = bytearray(256)
        struct.pack_into("<4I", constants, 12, *words)
        targets = mrt_reference(words)
        run(f"mrt{index}", program(WORDS, MRT_EXPORTS), constants, MRT_MASKS, targets, None,
            [(label, wrong, None) for label, wrong in mrt_wrongs(targets, words)])
        targets = gap_reference(words)
        run(f"gaps{index}", program(WORDS, GAP_EXPORTS), constants, GAP_MASKS, targets, None,
            [(label, wrong, None) for label, wrong in gap_wrongs(targets, words)])
    constants = bytearray(256)
    struct.pack_into("<I", constants, 12, DEPTH_WORD)
    rgba = texels()
    for index, (body, exports, depth_of) in enumerate(DEPTH_PROGRAMS):
        colours = [colour_reference()]
        depth = [depth_of(r, g, DEPTH_WORD) for r, g, _, _ in rgba]
        others = [f32(g) for _, g, _, _ in rgba] if index == 0 else [f32(g / 2) for _, g, _, _ in rgba]
        wrongs = [("depth not written", colours, [DEPTH_CLEAR] * 64),
                  ("rasterized depth", colours, [0.0] * 64),
                  ("another depth value", colours, others),
                  ("colour lost", [[(CLEAR,) * 4] * 64], depth)]
        run(f"depth{index}", program(body, exports), constants, [0xf], colours, depth, wrongs)
    # No render target: the void main runs for every pixel and leaves the rasterized depth (the vertex shader's z, 0).
    run("null", null_program(), bytes(256), [], [], [0.0] * 64,
        [("not drawn", [], [DEPTH_CLEAR] * 64), ("one texel not drawn", [], [0.0] * 63 + [DEPTH_CLEAR])])


def refuse(text, lines):
    """translate() refuses the program, for the reason named by `text`."""
    try:
        translate(lines)
    except (ValueError, KeyError) as error:
        assert text in str(error), (text, str(error))
        return
    raise AssertionError(f"An export program was accepted (expected: {text})")


def check_exports_controls():
    # The single compressed mrt0 export keeps the preamble's float4 SV_Target0 signature and returns the float4.
    source = translate(assembly(False))
    assert "float4 main(float2 uv : TEXCOORD0) : SV_Target0 {" in source and "PixelOutput" not in source, source
    assert "    return float4(export16(" in source, source
    # Several targets: one output each, in target order, the width of its mask.
    source = translate(program(WORDS, MRT_EXPORTS))
    assert ("struct PixelOutput { float4 target0 : SV_Target0; float2 target1 : SV_Target1; float4 target2 : SV_Target2; "
            "float target3 : SV_Target3; float2 target4 : SV_Target4; float3 target5 : SV_Target5; "
            "float4 target6 : SV_Target6; float2 target7 : SV_Target7; };") in source, source
    assert "PixelOutput main(float2 uv : TEXCOORD0) {" in source and "SV_Target0 {" not in source, source
    assert source.count("widen16(") == 4 + source.count("float widen16(") and "result.target7 = float2(export16(" in source
    assert write_masks(source) == dict(enumerate(MRT_MASKS)), source
    assert f"{WRITE_MASKS} SV_Target0 0xf, SV_Target1 0x3, SV_Target2 0xf, SV_Target3 0x1," in source, source
    # Masks with gaps: the output reaches the last enabled component and a disabled one below it is a masked 0.
    source = translate(program(WORDS, GAP_EXPORTS))
    assert ("struct PixelOutput { float3 target0 : SV_Target0; float4 target1 : SV_Target1; float4 target2 : SV_Target2; "
            "float4 target3 : SV_Target3; float4 target4 : SV_Target4; };") in source, source
    assert write_masks(source) == dict(enumerate(GAP_MASKS)), source
    assert "= float3(sample16.x, 0.0f, sample16.z);" in source and "= float4(0.0f, 0.0f, export16(sample16.z)," in source
    assert "result.target4 = float4(0.0f, 0.0f, widen16(" in source, source
    # A single mrt0 with fewer than four components leaves the preamble's signature too.
    source = translate(program(WORDS, ["exp mrt0 v16, v16, off, off done compr vm"]))
    assert "struct PixelOutput { float2 target0 : SV_Target0; };" in source and write_masks(source) == {0: 0x3}, source
    assert write_masks(translate(assembly(False))) == {0: 0xf}
    # Depth.
    source = translate(program(*DEPTH_PROGRAMS[0][:2]))
    assert "struct PixelOutput { float4 target0 : SV_Target0; float depth : SV_Depth; };" in source, source
    source = translate(program(*DEPTH_PROGRAMS[1][:2]))
    assert "result.depth = asfloat(" in source, source
    source = translate(program(["v_mov_b32_e32 v19, s44"], ["exp mrtz v19, off, off, off done vm"]))
    assert "struct PixelOutput { float depth : SV_Depth; };" in source and WRITE_MASKS not in source, source
    assert write_masks(source) == {}, source
    # The null-only program has no outputs.
    source = translate(null_program())
    assert "void main(float2 uv : TEXCOORD0) {" in source and source.endswith("    return;\n}\n"), source
    assert write_masks(source) == {} and "SV_Target" not in source and "SV_Depth" not in source, source
    # A program that is only s_endpgm lowers to the same empty void main, with no sample and no resource use.
    source = translate(["s_endpgm"])
    assert "void main(float2 uv : TEXCOORD0) {" in source and source.endswith("    return;\n}\n"), source
    assert write_masks(source) == {} and "SV_Target" not in source and "SV_Depth" not in source, source
    assert "tex.Sample" not in source and "SampleLevel" not in source, source
    # Controls: anything before s_endpgm still needs its export, and two s_endpgm are not the empty program.
    refuse("Unsupported instruction", ["s_nop 0", "s_endpgm"])
    refuse("Unsupported instruction 0", ["s_endpgm", "s_endpgm"])

    def with_exports(*exports, body=WORDS):
        return program(body, list(exports))

    done = "exp mrt7 v16, v16, off, off done compr vm"
    vertex, depth, compressed, empty = ("vertex or primitive export", "exp mrtz is accepted", "whole binary16 pairs",
                                        "at least one component")
    flags, null, follow = "Only the last export carries done", "exp null is accepted only", "Only exports may follow"
    refused = [
        # Vertex and primitive exports in a pixel program.
        (vertex, ["exp pos0 v12, v13, v14, v15 done vm"]), (vertex, ["exp pos0 v12, v13, v14, v15 done"]),
        (vertex, ["exp param0 v12, v13, v14, v15", done]), (vertex, ["exp param3 v12, off, off, off", done]),
        (vertex, ["exp prim v12, off, off, off done"]), ("Unknown export target", ["exp mrt8 v12, v13, v14, v15 done vm"]),
        # mrtz: stencil, sample mask and alpha components, compressed, or nothing.
        (depth, ["exp mrtz v12, v13, off, off done vm"]), (depth, ["exp mrtz v12, off, v13, off done vm"]),
        (depth, ["exp mrtz v12, off, off, v13 done vm"]), (depth, ["exp mrtz off, v13, off, off done vm"]),
        (depth, ["exp mrtz v12, v12, off, off done compr vm"]), (depth, ["exp mrtz off, off, off, off done vm"]),
        # Compressed masks that are not whole pairs (half a pair, which LLVM reassembles to another mask), pairs that
        # are not one register, and none.
        (compressed, ["exp mrt0 v16, off, off, off done compr vm"]), (compressed, ["exp mrt0 off, v16, off, off done compr vm"]),
        (compressed, ["exp mrt0 off, off, v17, off done compr vm"]), (compressed, ["exp mrt0 off, off, off, v17 done compr vm"]),
        (compressed, ["exp mrt0 v16, off, v17, off done compr vm"]), (compressed, ["exp mrt0 off, v16, off, v17 done compr vm"]),
        (compressed, ["exp mrt0 v16, v16, v17, off done compr vm"]), (compressed, ["exp mrt0 v16, v16, off, v17 done compr vm"]),
        (compressed, ["exp mrt0 v16, v17, v17, v17 done compr vm"]), (compressed, ["exp mrt0 v16, v16, v16, v17 done compr vm"]),
        (compressed, ["exp mrt0 off, off, off, off done compr vm"]),
        # An uncompressed export with no component.
        (empty, ["exp mrt0 off, off, off, off done vm"]), (empty, ["exp mrt3 off, off, off, off", done]),
        # A pkrtz pair exported uncompressed, and an unset register.
        ("Expected a numeric register", ["exp mrt0 v16, v17, off, off done vm"]),
        ("v40", ["exp mrt0 v40, off, off, off done vm"]), ("unset vector register", ["exp mrt0 v40, v40, off, off done compr vm"]),
        # done without vm, vm without done, a second done export, a target exported twice.
        (flags, ["exp mrt0 v16, v16, v17, v17 done compr"]), (flags, ["exp mrt0 v16, v16, v17, v17 compr vm", done]),
        ("after color export", ["exp mrt0 v16, v16, v17, v17 done compr vm", done]),
        ("appears twice", ["exp mrt1 v18, v18, off, off compr", "exp mrt1 v18, v18, off, off done compr vm"]),
        ("appears twice", ["exp mrtz v19, off, off, off", "exp mrtz v19, off, off, off done vm"]),
        # Exports with no done export: s_endpgm follows one that is not done.
        (follow, ["exp mrt0 v16, v16, v17, v17 compr"]),
        # exp null with a colour export, with sources, or not done.
        (null, ["exp mrt0 v16, v16, v17, v17 compr", NULL_EXPORT]), ("after color export", [NULL_EXPORT, done]),
        (null, ["exp null v12, off, off, off done vm"]), (null, ["exp null off, off, off, off"]),
        (flags, ["exp null off, off, off, off done"]), (null, ["exp null off, off, off, off done compr vm"]),
    ]
    for text, exports in refused:
        refuse(text, with_exports(*exports))
    # Only exports may follow an export that is not done.
    for between in ("s_nop 0", "v_mov_b32_e32 v18, s45", "s_waitcnt expcnt(0)"):
        refuse(follow, with_exports("exp mrt0 v16, v16, v17, v17 compr", between, done))
    # CF-2a: every lane is active in whole-quad mode, so an export there lowers as anywhere else, and the same
    # exports in whole-quad mode give the same HLSL.
    lines = with_exports("exp mrt0 v16, v16, v17, v17 done compr vm")
    plain = translate(lines)
    lines.insert(lines.index("exp mrt0 v16, v16, v17, v17 done compr vm"), "s_wqm_b64 exec, exec")
    assert translate(lines) == plain
    # An export while this lane may be inactive is refused: the done export, one that is not done, and exp null.
    for export in ("exp mrt0 v16, v16, v17, v17 done compr vm", "exp mrt0 v16, v16, v17, v17 compr",
                   "exp mrtz v12, off, off, off done vm", NULL_EXPORT):
        st = Lowering({}, {"v16": ("alu1", "alu2"), "v17": ("alu3", "alu4"), "v12": "alu5"}, [], {0: "tex"},
                      [1, 2, 3, 4], 64, {})
        st.ex = "ex9"
        try:
            dispatch(st, 1, export)
        except ValueError as error:
            assert "Unsupported export" in str(error), (export, str(error))
        else:
            raise AssertionError(f"{export!r} accepted with ex = {st.ex}")
    # An outstanding sample: the uncompressed export reads the sample before vmcnt(0).
    lines = [line for line in with_exports("exp mrt0 v12, v13, v14, v15 done vm") if not line.startswith("v_cvt_pkrtz")]
    lines.insert(lines.index("s_waitcnt vmcnt(0)"), "exp mrt1 v12, off, off, off")
    refuse("before vmcnt wait", lines)

    # Control flow: both arms of an if-else export the same targets, and each returns them.
    def branched(first, second):
        lines = with_constants(WORDS)
        start = lines.index("v_cvt_pkrtz_f16_f32_e32 v16, v12, v13")
        end = lines.index("s_endpgm")
        packs = lines[start:start + 2]
        lines[start:end] = (["s_cmp_eq_u32 s44, s45", "s_cbranch_scc1 BB0_8", *packs, *first, "s_branch BB0_9", "BB0_8:",
                             *packs, *second, "BB0_9:"])
        return lines

    same = ["exp mrt0 v16, v16, v17, v17 compr", "exp mrt1 v18, v18, off, off done compr vm"]
    # The second arm exports them in the other order: the outputs are the same.
    body = translate(branched(same, ["exp mrt1 v18, v18, off, off compr", "exp mrt0 v16, v16, v17, v17 done compr vm"]))
    assert body.count("return result;") == 2 and "} else {" in body, body
    # Arms that export different targets, or a different width, cannot share main's signature.
    differ = "export different targets"
    refuse(differ, branched(same, ["exp mrt0 v16, v16, v17, v17 done compr vm"]))
    refuse(differ, branched(same, ["exp mrt0 v16, v16, v17, v17 compr", "exp mrt1 v19, off, off, off done vm"]))
    refuse(differ, branched(same, [NULL_EXPORT]))
    # The same targets with another write mask on one path.
    refuse(differ, branched(same, ["exp mrt0 v16, v16, v17, v17 compr", "exp mrt1 off, off, v18, v18 done compr vm"]))
    # An export that is not done may not be followed by a branch or reach a join.
    lines = with_constants(WORDS)
    start = lines.index("exp mrt0 v16, v16, v17, v17 done compr vm")
    lines[start:start + 1] = ["exp mrt0 v16, v16, v17, v17 compr", "s_cmp_eq_u32 s44, s45", "s_cbranch_scc1 BB0_9",
                              "BB0_9:", "exp mrt1 v18, v18, off, off done compr vm"]
    refuse(follow, lines)
    lines = with_constants(WORDS)
    start = lines.index("v_cvt_pkrtz_f16_f32_e32 v16, v12, v13")
    end = lines.index("s_endpgm")
    packs = lines[start:start + 2]
    lines[start:end] = ["s_cmp_eq_u32 s44, s45", *packs, "s_cbranch_scc1 BB0_9", "exp mrt0 v16, v16, v17, v17 compr",
                        "BB0_9:", "exp mrt1 v18, v18, off, off done compr vm"]
    refuse("differs at a join", lines)


def controls(directory):
    check_exports_controls()


def binary_fixtures():
    """(program, translator) pairs that `pixel_aot_check.py binary` assembles, disassembles and lowers."""
    return [(program(WORDS, MRT_EXPORTS), translate), (program(WORDS, GAP_EXPORTS), translate),
            *((program(body, exports), translate) for body, exports, _ in DEPTH_PROGRAMS),
            (null_program(), translate), (["s_endpgm"], translate)]


draw = check_exports_draws


# LLVM 15 disassembles every raw four-bit EN value of a compressed export, printing the pair's register where a bit is set
# and off elsewhere, but reassembling that text keeps a pair exactly when its first operand is enabled: the expected EN
# after the round trip, by raw EN. (Ported from R0Y00/Xbox2Windows#434 by abilliontokens.)
COMPRESSED_EN_REENCODED = (0x0, 0x3, 0x0, 0x3, 0xc, 0xf, 0xc, 0xf, 0x0, 0x3, 0x0, 0x3, 0xc, 0xf, 0xc, 0xf)


def binary_checks(directory, assembler, objcopy, library):
    """Patch only the EN bits of an assembled compressed mrt0 export to each of the 16 values, then disassemble, lower,
    and reassemble the printed text: whole-pair masks lower like their text programs, every other mask is refused, and
    the reassembled EN follows the pair-first-operand rule."""
    def assembled(lines):
        source, obj, binary = directory / "en.s", directory / "en.o", directory / "en.bin"
        source.write_text("\n".join(lines) + "\n", encoding="ascii")
        subprocess.run([assembler, "-triple=amdgcn--amdpal", "-mcpu=gfx1013", "-filetype=obj", source, "-o", obj],
                       check=True)
        subprocess.run([objcopy, "-O", "binary", "--only-section=.text", obj, binary], check=True)
        return binary.read_bytes()

    reference = "exp mrt0 v16, v16, v17, v17 done compr vm"
    base = assembled(assembly(False))
    word = assembled([reference, "s_endpgm"])[:8]
    offset = base.find(word)
    assert offset >= 0 and base.find(word, offset + 1) < 0, "the reference export occurs once"
    base_lines = disassemble(base, library)
    for en, reencoded in enumerate(COMPRESSED_EN_REENCODED):
        patched = bytearray(base)
        patched[offset] = patched[offset] & 0xf0 | en
        lines = disassemble(bytes(patched), library)
        assert len(lines) == len(base_lines) and sum(a != b for a, b in zip(base_lines, lines)) == (en != 0xf), en
        text = next(line for line in lines if line.startswith("exp "))
        printed = ", ".join(register if en >> channel & 1 else "off"
                            for channel, register in enumerate(("v16", "v16", "v17", "v17")))
        assert text == f"exp mrt0 {printed} done compr vm", (hex(en), text)
        assert assembled([text, "s_endpgm"])[0] & 0xf == reencoded, (hex(en), text)
        if en in (0x3, 0xc, 0xf):
            expected = [text if line == reference else line for line in assembly(False)]
            assert translate(lines) == translate(expected), hex(en)
        else:
            refuse("whole binary16 pairs", lines)
