"""Draw family `sdwa_arith`: pixel_aot_check.py draw --family sdwa_arith."""
import math
import struct
import subprocess

from .common import half_rtz, must_reject, sdwa_readback, translate, with_constants


# SDWA forms of exact arithmetic with whole-dword sources. Programs 0 to 2 draw each operation once with source
# modifiers, an inline constant, clamp and the legacy zero rule; program 2 also places the low byte of a sum into
# BYTE_3. Program 3 keeps WORD_0 and BYTE_2 results inside 1.0 (UNUSED_PRESERVE) and pads the low word of a
# result into WORD_1; a reference that moves the high word there instead must fail.
# Every result is exact in binary32 and after the half export. Each program has wrong references (channel, value).
def sdwa_arith(op, dst, operands, dst_sel="DWORD", unused="UNUSED_PAD", clamp=False):
    sels = " src0_sel:DWORD src1_sel:DWORD" if len(operands) == 2 else " src0_sel:DWORD"
    return (f"v_{op}_f32_sdwa {dst}, {', '.join(operands)}{' clamp' if clamp else ''}"
            f" dst_sel:{dst_sel} dst_unused:{unused}{sels}")


SDWA_ARITH = (
    ([
        "v_mov_b32_e32 v18, s45",
        sdwa_arith("add", "v12", ["s44", "v18"]),
        sdwa_arith("sub", "v13", ["-s44", "v18"]),
        sdwa_arith("subrev", "v14", ["s46", "v18"], clamp=True),
        sdwa_arith("mul", "v15", ["-|s46|", "v18"]),
    ], (1.5, 2.25, -3.0, 0.0), [3.75, -3.75, 1.0, -6.75], ((0, 0.75), (1, -0.75), (2, 5.25), (3, 6.75))),
    ([
        "v_mov_b32_e32 v18, s45",
        "v_mov_b32_e32 v19, s47",
        sdwa_arith("max", "v12", ["s44", "v18"]),
        sdwa_arith("min", "v13", ["0.5", "v18"]),
        sdwa_arith("mul_legacy", "v14", ["s46", "v19"]),
        sdwa_arith("floor", "v15", ["-s45"]),
    ], (-0.75, 2.5, 0.0, math.inf), [2.5, 0.5, 0.0, -3.0], ((0, -0.75), (1, 2.5), (2, -0.0), (3, -2.0))),
    ([
        sdwa_arith("ceil", "v12", ["s44"]),
        sdwa_arith("fract", "v13", ["-s45"]),
        sdwa_arith("trunc", "v14", ["|s46|"]),
        "v_mov_b32_e32 v19, 0",
        sdwa_arith("add", "v15", ["s47", "v19"], dst_sel="BYTE_3"),
    ], (-1.25, 2.75, -2.5, 0x3f800040), [-1.0, 0.25, 2.0, 2.0], ((0, -2.0), (1, 0.75), (2, -2.0), (3, 1.0))),
    ([
        "v_mov_b32_e32 v18, s45",
        "v_mov_b32_e32 v12, 1.0",
        sdwa_arith("mul", "v12", ["s44", "v18"], "WORD_0", "UNUSED_PRESERVE"),
        *sdwa_readback("v12", "v13"),
        "v_mov_b32_e32 v14, 1.0",
        sdwa_arith("floor", "v14", ["s46"], "BYTE_2", "UNUSED_PRESERVE"),
        sdwa_arith("mul", "v15", ["s47", "v18"], "WORD_1"),
    ], (0x3f801234, 1.0, 8388613.0, 0xc0a03fff), [52.0, 18.0, 0.51953125, 1.9921875],
     ((0, 128.0), (1, 63.0), (2, 1.0), (3, -5.0))),
    # The transcendental and root forms (exact on these powers of two): whole-dword results and then, in program 5,
    # reciprocal square root, a byte kept inside 1.0, a word padded (the low word of 1.5 is zero) and a negated source.
    ([
        sdwa_arith("exp", "v12", ["s47"]),
        sdwa_arith("log", "v13", ["s44"]),
        sdwa_arith("rcp", "v14", ["s45"]),
        sdwa_arith("sqrt", "v15", ["s46"]),
    ], (8.0, 4.0, 16.0, 3.0), [8.0, 3.0, 0.25, 4.0], ((0, 4.0), (1, 2.0), (2, 0.5), (3, 2.0))),
    ([
        sdwa_arith("rsq", "v12", ["s44"]),
        "v_mov_b32_e32 v13, 1.0",
        sdwa_arith("exp", "v13", ["s45"], "BYTE_2", "UNUSED_PRESERVE"),
        sdwa_arith("sqrt", "v14", ["s46"], "WORD_1"),
        sdwa_arith("rcp", "v15", ["-s47"]),
    ], (4.0, 0.0, 2.25, -1.0), [0.5, 0.5, 0.0, 1.0], ((0, 2.0), (1, 1.0), (2, 1.5), (3, -1.0))),
    # Round to nearest even: ties go to the even integer (2.5 to 2, 3.5 to 4, -1.5 to -2); the last result's low byte is
    # placed in BYTE_3 (8388672.0 is an integer, so it is its own rounding).
    ([
        sdwa_arith("rndne", "v12", ["s44"]),
        sdwa_arith("rndne", "v13", ["-s45"]),
        sdwa_arith("rndne", "v14", ["-|s46|"]),
        sdwa_arith("rndne", "v15", ["s47"], dst_sel="BYTE_3"),
    ], (2.5, -3.5, -1.5, 0x4b000040), [2.0, 4.0, -2.0, 2.0], ((0, 3.0), (1, 3.0), (2, -1.0), (3, 0.0))),
    # v_rcp_iflag_f32 is the reciprocal without the exception flag (powers of two, whose reciprocals are exact): a
    # source modifier, clamp, and a word kept inside 1.0 (the low word of 0.5 is zero, so the preserved word is 1.0's).
    ([
        sdwa_arith("rcp_iflag", "v12", ["s44"]),
        sdwa_arith("rcp_iflag", "v13", ["-|s45|"]),
        sdwa_arith("rcp_iflag", "v14", ["s46"], clamp=True),
        "v_mov_b32_e32 v15, 1.0",
        sdwa_arith("rcp_iflag", "v15", ["s47"], "WORD_0", "UNUSED_PRESERVE"),
    ], (4.0, -0.5, 0.5, 2.0), [0.25, -2.0, 1.0, 1.0], ((0, 4.0), (1, 2.0), (2, 2.0), (3, 0.5))),
)


def sdwa_arith_reference(index, inputs):
    """Python binary32 arithmetic on the constant words, independent of the lowering."""
    as_float = lambda w: struct.unpack("<f", struct.pack("<I", w))[0]
    bits = lambda x: struct.unpack("<I", struct.pack("<f", x))[0]
    x, y, z, w = (as_float(v) if isinstance(v, int) else v for v in inputs)
    if index == 0:
        return [x + y, -x - y, min(max(y - z, 0.0), 1.0), -abs(z) * y]
    if index == 1:
        return [max(x, y), min(0.5, y), 0.0 if z == 0 or w == 0 else z * w, float(math.floor(-y))]
    if index == 2:
        return [float(math.ceil(x)), -y - math.floor(-y), float(math.trunc(abs(z))), as_float((bits(w + 0.0) & 0xff) << 24)]
    if index == 4:
        return [2.0 ** w, math.log2(x), 1.0 / y, math.sqrt(z)]
    if index == 5:
        return [1.0 / math.sqrt(x), as_float((0x3f800000 & ~0xff0000) | ((bits(2.0 ** y) & 0xff) << 16)),
                as_float((bits(math.sqrt(z)) & 0xffff) << 16), 1.0 / -w]
    if index == 6:
        return [float(round(x)), float(round(-y)), float(round(-abs(z))), as_float((bits(float(round(w))) & 0xff) << 24)]
    if index == 7:
        return [1.0 / x, 1.0 / -abs(y), min(1.0 / z, 1.0), as_float(0x3f800000 & ~0xffff | (bits(1.0 / w) & 0xffff))]
    product = bits(x * y) & 0xffff
    return [float(product & 0xff), float(product >> 8),
            as_float((0x3f800000 & ~0xff0000) | ((bits(float(math.floor(z))) & 0xff) << 16)), as_float((bits(w * y) & 0xffff) << 16)]


def check_sdwa_arith_draws(directory, compiler, renderer, backend):
    case = directory / "sdwa_arith.case"
    for index, (body, inputs, expected, wrongs) in enumerate(SDWA_ARITH):
        assert sdwa_arith_reference(index, inputs) == expected, (index, sdwa_arith_reference(index, inputs))
        source = directory / f"sdwa_arith{index}.hlsl"
        shader = directory / f"sdwa_arith{index}.cso"
        source.write_text(translate(with_constants(body)), encoding="ascii")
        subprocess.run([compiler, "-Gis", "-T", "ps_6_0", "-E", "main", "-Fo", shader, source], check=True)
        words = [v if isinstance(v, int) else struct.unpack("<I", struct.pack("<f", v))[0] for v in inputs]
        constants = bytearray(256)
        struct.pack_into("<4I", constants, 12, *words)
        for x in (*expected, *(value for _, value in wrongs)):
            assert half_rtz(x) == x, x
        draw = [renderer, backend, "--check-pixel-case", shader, case]
        case.write_bytes(constants + struct.pack("<4f", *expected) * 64)
        subprocess.run(draw, check=True)
        for channel, value in wrongs:
            assert struct.pack("<f", value) != struct.pack("<f", expected[channel])
            wrong_values = list(expected)
            wrong_values[channel] = value
            case.write_bytes(constants + struct.pack("<4f", *wrong_values) * 64)
            result = subprocess.run(draw, capture_output=True, text=True)
            if result.returncode != 1 or "pixel_mismatch" not in result.stderr:
                raise AssertionError(f"A wrong SDWA arithmetic result escaped detection in program {index}, channel {channel}")


def controls(directory):
    # SDWA arithmetic takes whole-dword sources only and refuses output modifiers and a src1_sel on a unary op.
    for program, *_ in SDWA_ARITH:
        translate(with_constants(program))
    body = translate(with_constants(SDWA_ARITH[3][0])).split("float4 main", 1)[1]
    assert body.count("& 0xffff0000u) | ") == 1 and body.count("& 0xff00ffffu) | ") == 1, body
    body = translate(with_constants(SDWA_ARITH[5][0])).split("float4 main", 1)[1]
    assert body.count("& 0xff00ffffu) | ") == 1 and body.count("& 0xffffu) << 16u") == 1 and body.count("rsqrt(") == 1, body
    # The result of a field placement stays a word (movw), and a whole-dword result is a float.
    assert body.count("uint movw") >= 2 and "asfloat(((" not in body, body
    must_reject(translate, with_constants(["v_mov_b32_e32 v18, s45", sdwa_arith("add", "v12", ["s44", "v18 mul:2"])]))
    must_reject(translate, with_constants([sdwa_arith("rcp", "v12", ["s44"]).replace("src0_sel:DWORD", "src0_sel:BYTE_1")]))
    must_reject(translate, with_constants([sdwa_arith("rndne", "v12", ["s44"]).replace("src0_sel:DWORD", "src0_sel:WORD_1")]))
    must_reject(translate, with_constants([sdwa_arith("rcp_iflag", "v12", ["s44"]).replace("src0_sel:DWORD", "src0_sel:WORD_1")]))
    must_reject(translate, with_constants([sdwa_arith("rcp_iflag", "v12", ["s44", "s45"])]))
    # The reciprocal and its iflag form lower alike (the flag has no desktop counterpart).
    body = translate(with_constants(SDWA_ARITH[7][0])).split("float4 main", 1)[1]
    assert body.count("1.0f / ") == 4, body
    must_reject(translate, with_constants([sdwa_arith("rndne", "v12", ["s44", "v13"])]))
    must_reject(translate, with_constants([sdwa_arith("rndne", "v12", ["s44"], "BYTE_1", "UNUSED_SEXT")]))
    must_reject(translate, with_constants([sdwa_arith("exp", "v12", ["s44"]) + " src1_sel:DWORD"]))
    must_reject(translate, with_constants([sdwa_arith("sqrt", "v12", ["s44"], "BYTE_1", "UNUSED_SEXT")]))
    must_reject(translate, with_constants([sdwa_arith("add", "v12", ["s44", "v13"]).replace("src0_sel:DWORD", "src0_sel:WORD_1")]))
    must_reject(translate, with_constants([sdwa_arith("floor", "v12", ["s44"]) + " src1_sel:DWORD"]))
    # A partial UNUSED_PRESERVE result needs a tracked numeric destination, as for SDWA moves.
    for register in ("v0", "v8", "v20"):
        must_reject(translate, with_constants([sdwa_arith("floor", register, ["s44"], "BYTE_2", "UNUSED_PRESERVE")]))


def binary_fixtures():
    """(program, translator) pairs that `pixel_aot_check.py binary` assembles, disassembles and lowers."""
    return [
        *((with_constants(body), translate) for body, *_ in SDWA_ARITH),
    ]


draw = check_sdwa_arith_draws
