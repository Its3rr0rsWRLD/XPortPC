"""Draw family `f16`: pixel_aot_check.py draw --family f16."""
import math
import struct
import subprocess

from .common import (f16_const, half_rtz, half_value, must_reject, narrow_reference, sdwa_readback, translate,
                     with_constants)


# Binary16 arithmetic (the _f16 VALU forms). Every program is drawn with several constant sets and each channel
# is compared with an independent model: exact float64 arithmetic on the binary16 inputs, rounded once to
# binary16 by struct "e" (nearest even). Value programs widen the result with v_cvt_f32_f16, which gives the
# binary16 exactly through the half export. Bit programs preset the destination to 1.0 and split (v - 1) * 2^23
# into the low and high byte of the 16-bit result, as NARROW_BODY does, so signed zero, subnormal and infinite
# results and the kept high half are read bit for bit. The source words carry junk in the high half. Each program
# lists the plausible lowering bugs to model; a bug is drawn as a wrong reference wherever it changes a channel
# and must be reported as a mismatch. The channels of a bug-free model are asserted against the instruction
# semantics by hand in F16_EXPECTED.
def f16_in(word, bug):
    x = half_value(word)
    if bug == "flush" and x != 0 and abs(x) < 2.0 ** -14:
        return math.copysign(0.0, x)
    return x


def f16_out(x, bug):
    """The binary16 encoding of an exact result; half_up rounds ties away from zero, flush drops subnormals."""
    bits = narrow_reference(x)
    if bug == "half_up" and abs(x) < 65520:
        magnitude, mag = abs(x), bits & 0x7fff
        low = mag if half_value(mag) <= magnitude else mag - 1
        if low + 1 < 0x7c00 and magnitude - half_value(low) == half_value(low + 1) - magnitude:
            bits = (bits & 0x8000) | (low + 1)
    if bug == "flush" and 0 < (bits & 0x7fff) < 0x400:
        bits &= 0x8000
    return bits


def kept_sign(x, result):
    return math.copysign(0.0, x) if result == 0 else float(result)


def f16_floor(x):
    return x if abs(x) >= 1024 else kept_sign(x, math.floor(x))


def f16_ceil(x):
    return x if abs(x) >= 1024 else kept_sign(x, math.ceil(x))


def f16_trunc(x):
    return x if abs(x) >= 1024 else kept_sign(x, math.trunc(x))


def f16_rndne(x, bug):
    if abs(x) >= 1024:
        return x
    if bug == "rndne_away" and abs(x) % 1 == 0.5:
        return kept_sign(x, math.copysign(math.floor(abs(x) + 0.5), x))
    return kept_sign(x, round(x))


def f16_fract(x, bug):
    result = x - math.floor(x)
    return result if bug == "fract_no_clamp" else min(result, half_value(0x3bff))


def f16_ldexp(x, word, bug):
    exponent = word & 0xffff
    if bug != "unsigned_exp" and exponent & 0x8000:
        exponent -= 0x10000
    # The bound is independent of the lowering's: well beyond where a nonzero binary16 can still result.
    return math.ldexp(x, max(-200, min(200, exponent)))


def f16_words(*lows, junk=(0xdead, 0xbeef, 0x4d2f, 0xfc01)):
    """Constant words 3 to 6: the given low halves under junk high halves."""
    return tuple((high << 16) | low for high, low in zip(junk, (*lows, 0, 0, 0, 0)))


def f16_values(*results, bug=None):
    return [half_value(f16_out(x, bug)) for x in results]


def f16_bit_channels(*results, bug=None):
    """Two channels per result. Zeroing the high half instead of keeping it leaves a binary32 denormal in the
    destination, so (v - 1) * 2^23 is -2^23, which splits into -32768 * 256 + 0."""
    if bug == "high_zero":
        return [0.0, -32768.0] * len(results)
    return [value for x in results for bits in (f16_out(x, bug),) for value in (float(bits & 0xff), float(bits >> 8))]


def f16_values_readback():
    return [f"v_cvt_f32_f16_e32 v{r}, v{r}" for r in range(12, 16)]


def f16_bits_program(setup, first, second):
    """Run two operations into registers preset to 1.0 and read both encodings bit for bit."""
    return [*setup, "v_mov_b32_e32 v12, 1.0", first, *sdwa_readback("v12", "v13"),
            "v_mov_b32_e32 v14, 1.0", second, *sdwa_readback("v14", "v15")]


def f16_model_v1(words, bug):
    a, b, c, d = (f16_in(w, bug) for w in words)
    return f16_values(a + b, -a - (b if bug == "no_abs" else abs(b)), (c - b) if bug == "no_reverse" else b - c, d * b, bug=bug)


def f16_model_v2(words, bug):
    a, b = (f16_in(w, bug) for w in words[:2])
    return f16_values(max(-a if bug == "no_abs" else -abs(a), b), min(a, b), f16_const("0.5", bug) + b, half_value(0x3c02) + b, bug=bug)


def f16_model_v3(words, bug):
    x = f16_in(words[0], bug)
    return f16_values(f16_floor(x), f16_ceil(-x if bug == "no_abs" else -abs(x)), f16_trunc(x), f16_rndne(x, bug), bug=bug)


def f16_model_v4(words, bug):
    a, b, c = (f16_in(w, bug) for w in words[:3])
    return f16_values(f16_fract(a, bug), f16_fract(-abs(b), bug), f16_ldexp(c, words[3], bug), math.ldexp(-c, -3), bug=bug)


def f16_model_high(words, bug):
    a, b, c = (f16_in(w, bug) for w in words[:3])
    marker = half_value(words[3] >> 16)
    return [half_value(f16_out(a + b, bug)), 0.0 if bug == "high_zero" else marker, half_value(f16_out(c * b, bug)), 0.0]


def f16_model_b1(words, bug):
    a, b, c = (f16_in(w, bug) for w in words[:3])
    return f16_bit_channels(a + b, c * b, bug=bug)


def f16_model_b2(words, bug):
    a, b = (f16_in(w, bug) for w in words[:2])
    return f16_bit_channels((a - b) if bug == "no_reverse" else b - a, b - f16_const("0.15915494", bug), bug=bug)


def f16_model_b3(words, bug):
    a, b, c = (f16_in(w, bug) for w in words[:3])
    return f16_bit_channels(min(a, b), max(c, b), bug=bug)


def f16_model_b4(words, bug):
    x, y = f16_in(words[0], bug), f16_in(words[3], bug)
    return f16_bit_channels(f16_ldexp(x, words[1], bug), f16_ldexp(y, words[2], bug), bug=bug)


def f16_model_b5(words, bug):
    return f16_bit_channels(f16_floor(f16_in(words[0], bug)), f16_ceil(f16_in(words[2], bug)), bug=bug)


def f16_model_b6(words, bug):
    return f16_bit_channels(f16_trunc(f16_in(words[0], bug)), f16_rndne(f16_in(words[2], bug), bug), bug=bug)


def f16_model_b7(words, bug):
    b = f16_in(words[1], bug)
    return f16_bit_channels(f16_const("3", bug) * b, f16_const("64", bug) + b, bug=bug)


F16_B_SETUP = ["v_mov_b32_e32 v18, s45"]
# (name, body, model, constant sets, bugs). Operand forms: s44 to s47 are the sets' words; v18 and v19 copy s45
# and s47 so the e32 forms have a vector second operand.
F16_PROGRAMS = (
    ("v1", ["v_mov_b32_e32 v18, s45", "v_add_f16_e32 v12, s44, v18", "v_sub_f16_e64 v13, -s44, |v18|",
            "v_subrev_f16_e32 v14, s46, v18", "v_mul_f16_e32 v15, s47, v18", *f16_values_readback()],
     f16_model_v1,
     # Ties that round down to even in the sum, the negated sum and the product; the operand order of subrev;
     # an absolute value on the second operand.
     [f16_words(0x3c00, 0x1000, 0x3800, 0x3c03), f16_words(0x3c01, 0x3e00, 0x3c00, 0x3c03),
      f16_words(0xba00, 0xb400, 0xbe00, 0xc200)],
     ("half_up", "no_reverse", "no_abs")),
    ("v2", ["v_mov_b32_e32 v18, s45", "v_max_f16_e64 v12, -|s44|, v18", "v_min_f16_e32 v13, s44, v18",
            "v_add_f16_e32 v14, 0.5, v18", "v_add_f16_e32 v15, 0x3c02, v18", *f16_values_readback()],
     f16_model_v2,
     # The inline 0.5 and a literal; 1 + 2^-9 plus 2^-11 is a tie that rounds down to even.
     [f16_words(0xba00, 0x3400), f16_words(0x4200, 0xc100), f16_words(0x3c00, 0x1000)],
     ("half_up", "const_bits", "no_abs")),
    ("v3", ["v_floor_f16_e32 v12, s44", "v_ceil_f16_e64 v13, -|s44|", "v_trunc_f16_e32 v14, s44",
            "v_rndne_f16_e64 v15, s44", *f16_values_readback()],
     f16_model_v3,
     # 2.5, -2.5 and -1.5, and 1023.5, the last half-integer.
     [f16_words(low) for low in (0x4100, 0xc100, 0xbe00, 0x63ff)],
     ("rndne_away", "no_abs")),
    ("v4", ["v_mov_b32_e32 v19, s47", "v_fract_f16_e32 v12, s44", "v_fract_f16_e64 v13, -|s45|",
            "v_ldexp_f16_e32 v14, s46, v19", "v_ldexp_f16_e64 v15, -s46, -3", *f16_values_readback()],
     f16_model_v4,
     # fract of a negative value, of the tiniest negative half (it must stay below 1.0), and ldexp by a
     # positive and a negative register exponent and by the inline constant -3.
     [f16_words(0xb400, 0x4180, 0x3e00, 3), f16_words(0x8001, 0xbf00, 0xba00, 0xfffe),
      f16_words(0x4248, 0xc248, 0x4248, 0xffff)],
     ("fract_no_clamp", "unsigned_exp")),
    ("high", ["v_mov_b32_e32 v18, s45", "v_mov_b32_e32 v12, s47", "v_add_f16_e32 v12, s44, v18",
              "v_cvt_f32_f16_sdwa v13, v12 dst_sel:DWORD dst_unused:UNUSED_PAD src0_sel:WORD_1",
              "v_cvt_f32_f16_e32 v12, v12", "v_mul_f16_e64 v20, s46, v18",
              "v_cvt_f32_f16_sdwa v15, v20 dst_sel:DWORD dst_unused:UNUSED_PAD src0_sel:WORD_1",
              "v_cvt_f32_f16_e32 v14, v20"],
     f16_model_high,
     # The destination of the add holds a marker in its high half (5.0, then -0.75) and keeps it; the
     # destination of the multiply was never written, so its high half is zero.
     [f16_words(0x3c00, 0x1000, 0x3800, junk=(0xdead, 0xbeef, 0x4d2f, 0x4500)) [:3] + (0x45001234,),
      f16_words(0xc200, 0x3e00, 0x4000, junk=(0xdead, 0xbeef, 0x4d2f, 0x4500))[:3] + (0xba00ffff,)],
     ("half_up", "high_zero")),
    ("b1", f16_bits_program(F16_B_SETUP, "v_add_f16_e32 v12, s44, v18", "v_mul_f16_e64 v14, s46, v18"),
     f16_model_b1,
     # 65504 + 16 overflows at the tie; -0 + -0; an add of two subnormals, and a product that is the smallest
     # subnormal; the largest subnormal from 2^-14 - 2^-24 and a product that ties to -0; x + -x is +0, and a
     # product rounding to -3 * 2^-24; the sum and product that are 65504 and infinity.
     [f16_words(0x7bff, 0x4c00, 0x8000), f16_words(0x8000, 0x8000, 0x0c00), f16_words(0x0001, 0x0001, 0x0c00),
      f16_words(0x0001, 0x0c00, 0x0c00), f16_words(0x0400, 0x8001, 0x3800), f16_words(0x4248, 0xc248, 0x0001),
      f16_words(0x7bff, 0x4bff, 0x7bff)],
     ("half_up", "flush", "high_zero")),
    ("b2", f16_bits_program(F16_B_SETUP, "v_subrev_f16_e32 v12, s44, v18", "v_sub_f16_e64 v14, v18, 0.15915494"),
     f16_model_b2,
     # b - a and b - 1/(2*pi): equal operands, a signed zero, a subnormal, negative overflow, and a tie.
     [f16_words(0x3800, 0x3800), f16_words(0x8000, 0x0000), f16_words(0x0001, 0x0000), f16_words(0x7bff, 0xfbff),
      f16_words(0x3c01, 0x1000)],
     ("half_up", "no_reverse", "flush", "const_bits", "high_zero")),
    ("b3", f16_bits_program(F16_B_SETUP, "v_min_f16_e32 v12, s44, v18", "v_max_f16_e64 v14, s46, v18"),
     f16_model_b3,
     [f16_words(0x7c00, 0x3c00, 0x7c00), f16_words(0x0001, 0x0002, 0x8001), f16_words(0xbc00, 0x3c00, 0xbc00)],
     ("flush", "high_zero")),
    ("b4", f16_bits_program(["v_mov_b32_e32 v18, s45", "v_mov_b32_e32 v19, s47"], "v_ldexp_f16_e32 v12, s44, v18",
                            "v_ldexp_f16_e64 v14, v19, s46"),
     f16_model_b4,
     # (x, exponent 1, exponent 2, y): 2^-24, the tie 2^-25 that rounds to 0, 1.5 * 2^-25 rounding up to 2^-24,
     # -2^-26, a subnormal input scaled back, overflow, an exponent of -32768 (from 0x8000), zero and
     # infinity-sized exponents, and the largest half halved.
     [f16_words(0x3c00, 0xffe8, 0xffe7, 0x3c00), f16_words(0x3e00, 0xffe7, 0xffe6, 0xbc00),
      f16_words(0x0001, 24, 10, 0x0001), f16_words(0x3c00, 0x03e8, 0x8000, 0xbc00),
      f16_words(0x0000, 0x7fff, 0xfffb, 0x8000), f16_words(0x7bff, 1, 0xffff, 0x7bff),
      f16_words(0x4200, 0xfffd, 3, 0x3a00)],
     ("half_up", "flush", "unsigned_exp", "high_zero")),
    ("b5", f16_bits_program(F16_B_SETUP, "v_floor_f16_e32 v12, s44", "v_ceil_f16_e64 v14, s46"),
     f16_model_b5,
     # -0.5, 0.5, signed zeros, -2.5 and 2.5, and the smallest subnormals of each sign.
     [f16_words(0xb800, 0, 0xb800), f16_words(0x3800, 0, 0x3800), f16_words(0x8000, 0, 0x0000),
      f16_words(0xc100, 0, 0x4100), f16_words(0x8001, 0, 0x0001), f16_words(0x0001, 0, 0x8001)],
     ("flush", "high_zero")),
    ("b6", f16_bits_program(F16_B_SETUP, "v_trunc_f16_e32 v12, s44", "v_rndne_f16_e64 v14, s46"),
     f16_model_b6,
     [f16_words(0xb800, 0, 0xb800), f16_words(0x3800, 0, 0x3800), f16_words(0x4100, 0, 0x4100),
      f16_words(0xc100, 0, 0xc100), f16_words(0x7bff, 0, 0x7bff), f16_words(0x03ff, 0, 0x83ff)],
     ("rndne_away", "high_zero")),
    ("b7", f16_bits_program(F16_B_SETUP, "v_mul_f16_e32 v12, 3, v18", "v_add_f16_e64 v14, 64, v18"),
     f16_model_b7,
     # The integer inline constants 3 and 64 are subnormal bit patterns, not the numbers 3 and 64.
     [f16_words(0, 0x4000), f16_words(0, 0x0200), f16_words(0, 0x8200)],
     ("int_value", "flush", "high_zero")),
)
# Hand-computed channels of the bug-free models for one set of each program, so that a model and a lowering
# cannot be wrong in the same way: tie to even 1 + 2^-11 -> 1, -(1 + 2^-11) -> -1, 2^-11 - 0.5, 1.5 * 2^-11 * ...
F16_EXPECTED = {
    "v1": (0, [1.0, -1.0, 2.0 ** -11 - 0.5, (1 + 3 * 2.0 ** -10) * 2.0 ** -11]),
    "v2": (0, [0.25, -0.75, 0.75, 1 + 2.0 ** -9 + 0.25]),
    "v3": (1, [-3.0, -2.0, -2.0, -2.0]),
    "v4": (0, [0.75, 0.25, 12.0, -0.1875]),
    "high": (0, [1.0, 5.0, 2.0 ** -12, 0.0]),
    "b1": (0, [0x00, 0x7c, 0x00, 0x80]),
    "b2": (4, [0x00, 0xbc, 0x14, 0xb1]),
    "b4": (1, [0x01, 0x00, 0x00, 0x80]),
    "b5": (0, [0x00, 0xbc, 0x00, 0x80]),
    "b6": (1, [0x00, 0x00, 0x00, 0x00]),
    "b7": (0, [0x06, 0x00, 0x00, 0x40]),
}


def check_f16_models() -> None:
    """The models against hand-computed channels, and each listed bug against the sets that must expose it."""
    by_name = {name: (model, sets, bugs) for name, _, model, sets, bugs in F16_PROGRAMS}
    for name, (index, expected) in F16_EXPECTED.items():
        model, sets, _ = by_name[name]
        assert model(sets[index], None) == [float(v) for v in expected], (name, model(sets[index], None))
    for name, (model, sets, bugs) in by_name.items():
        for bug in bugs:
            assert any(model(words, bug) != model(words, None) for words in sets), (name, bug)
        for words in sets:
            for bug in (None, *bugs):
                for x in model(words, bug):
                    assert half_rtz(x) == x or x in (math.inf, -math.inf), (name, bug, x)


def check_f16_draws(directory, compiler, renderer, backend):
    check_f16_models()
    case = directory / "f16.case"
    for name, body, model, sets, bugs in F16_PROGRAMS:
        source = directory / f"f16_{name}.hlsl"
        shader = directory / f"f16_{name}.cso"
        source.write_text(translate(with_constants(body)), encoding="ascii")
        subprocess.run([compiler, "-Gis", "-T", "ps_6_0", "-E", "main", "-Fo", shader, source], check=True)
        draw = [renderer, backend, "--check-pixel-case", shader, case]
        for words in sets:
            constants = bytearray(256)
            struct.pack_into("<4I", constants, 12, *words)
            expected = model(words, None)
            case.write_bytes(constants + struct.pack("<4f", *expected) * 64)
            subprocess.run(draw, check=True)
            for bug in bugs:
                wrong = model(words, bug)
                if struct.pack("<4f", *wrong) == struct.pack("<4f", *expected):
                    continue
                case.write_bytes(constants + struct.pack("<4f", *wrong) * 64)
                result = subprocess.run(draw, capture_output=True, text=True)
                if result.returncode != 1 or "pixel_mismatch" not in result.stderr:
                    raise AssertionError(f"A binary16 lowering bug ({bug}) escaped detection in {name} for words {words}")


def controls(directory):
    # Binary16 arithmetic computes once in binary32 from the widened low halves, narrows once and keeps the
    # destination's high half; subrev swaps its operands, and a modifier acts on bit 15 before widening.
    body = translate(with_constants(F16_PROGRAMS[0][1])).split("float4 main", 1)[1]
    assert body.count("& 0xffff0000u) | narrow16(") == 4 and body.count("narrow16(") == 4, body
    assert "widen16(((params[0].w & 0xffffu) ^ 0x8000u)) - widen16(((movw20 & 0xffffu) & 0x7fffu))" in body, body
    assert "widen16((movw20 & 0xffffu)) - widen16((params[1].y & 0xffffu))" in body, body
    # An inline constant is a binary16 value, an integer inline constant is a bit pattern and a literal supplies
    # its low half; a destination that was never written contributes a zero high half.
    body = translate(with_constants(["v_add_f16_e32 v20, 0.5, v13", "v_add_f16_e32 v21, 3, v13", "v_add_f16_e64 v22, -3, v13",
                                     "v_add_f16_e32 v23, 0x3c02, v13", "v_add_f16_e32 v24, 0.15915494, v13",
                                     "v_add_f16_e64 v25, -|0.5|, v13"])).split("float4 main", 1)[1]
    for expected in ("widen16(0x3800u)", "widen16(0x3u)", "widen16(0xfffdu)", "widen16(0x3c02u)", "widen16(0x3118u)",
                     "widen16(((0x3800u & 0x7fffu) ^ 0x8000u))"):
        assert expected in body, expected
    assert body.count("asfloat(0u | narrow16(") == 6, body
    assert translate(with_constants(["v_add_f16 v12, s44, v13"])) == translate(with_constants(["v_add_f16_e32 v12, s44, v13"]))
    body = translate(with_constants(["v_ldexp_f16_e64 v12, s44, -3", "v_ldexp_f16_e64 v13, s44, 0xfffd",
                                     "v_ldexp_f16_e32 v14, s44, v15", "v_ldexp_f16_e64 v15, -s44, 5",
                                     "v_fract_f16_e64 v20, s44 clamp", "v_max_f16_e64 v21, s44, 0.5 clamp"])).split("float4 main", 1)[1]
    for expected in (", -3)", ", 5)", "((int((asuint(sample16.w) & 0xffffu)) ^ 0x8000) - 0x8000)",
                     "narrow16(saturate(widen16(fract16(", "narrow16(saturate(max("):
        assert expected in body, expected
    assert body.count(", -3)") == 2, body
    must_reject(translate, with_constants(["v_add_f16_e64 v12, s44, v13 mul:2"]))
    must_reject(translate, with_constants(["v_add_f16_e64 v12, s44, v13 div:2"]))
    must_reject(translate, with_constants(["v_mul_f16_e64 v12, s44, v13 op_sel:[0,0,1]"]))
    must_reject(translate, with_constants(["v_add_f16_e64 v12, s44, v13 clamp mul:2"]))
    must_reject(translate, with_constants(["v_add_f16_e32 v12, s44, v13 clamp"]))
    must_reject(translate, with_constants(["v_add_f16_sdwa v12, s44, v13 dst_sel:DWORD dst_unused:UNUSED_PAD src0_sel:WORD_0 src1_sel:WORD_0"]))
    must_reject(translate, with_constants(["v_add_f16_dpp v12, v13, v14 row_shl:1 row_mask:0xf bank_mask:0xf"]))
    for operation in ("v_fma_f16 v12, s44, v13, v14", "v_fmac_f16_e32 v12, s44, v13", "v_mad_f16 v12, s44, v13, v14",
                      "v_sqrt_f16_e32 v12, s44", "v_rcp_f16_e32 v12, s44", "v_rsq_f16_e32 v12, s44",
                      "v_log_f16_e32 v12, s44", "v_exp_f16_e32 v12, s44", "v_sin_f16_e32 v12, s44", "v_cos_f16_e32 v12, s44",
                      "v_add_f16_e32 v12, s44", "v_floor_f16_e32 v12, s44, v13", "v_ldexp_f16_e64 v12, s44",
                      "v_add_f16_e32 v12, 1.5, v13", "v_add_f16_e32 v12, 65, v13", "v_add_f16_e32 v12, -17, v13",
                      "v_add_f16_e32 v12, 0x12345, v13", "v_add_f16_e64 v12, --0.5, v13", "v_add_f16_e64 v12, |-s44|, v13",
                      "v_add_f16_e64 v12, neg(s44), v13", "v_add_f16_e32 v12, s44, v13, v14",
                      "v_ldexp_f16_e64 v12, v13, 1.0", "v_ldexp_f16_e64 v12, v13, -s44", "v_ldexp_f16_e64 v12, v13, |s44|",
                      "v_ldexp_f16_e64 v12, v13, 65", "v_ldexp_f16_e64 v12, v13, 0x12345", "v_ldexp_f16_e64 v12, v13, s44 clamp mul:2"):
        must_reject(translate, with_constants([operation]))
    # The destination's old value must be numeric (v0, v1, v8 and v9 hold interpolation state), a source cannot
    # be read before the sample or the scalar load it depends on arrives, and nothing may overwrite a sample
    # destination before vmcnt(0).
    for register in ("v0", "v1", "v8", "v9"):
        must_reject(translate, with_constants([f"v_mul_f16_e32 {register}, s44, v13"]))
        must_reject(translate, with_constants([f"v_floor_f16_e32 {register}, s44"]))
    program = with_constants(["v_add_f16_e32 v20, s44, v13"])
    translate(program)
    wait = program.index("s_waitcnt vmcnt(0)")
    for operation in ("v_add_f16_e32 v20, s44, v13", "v_add_f16_e32 v20, v12, v13", "v_add_f16_e32 v12, 0.5, v13",
                      "v_floor_f16_e32 v13, 0.5"):
        must_reject(translate, program[:wait] + [operation] + program[wait:])
    scalar_wait = program.index("s_waitcnt lgkmcnt(0)", program.index("s_buffer_load_dwordx4 s[44:47], s[44:47], 0xc"))
    for operation in ("v_add_f16_e64 v20, s44, s47", "v_ldexp_f16_e64 v20, s44, s45", "v_ceil_f16_e64 v20, s46"):
        must_reject(translate, program[:scalar_wait] + [operation] + program[scalar_wait:])
        translate(program[:scalar_wait + 1] + [operation] + program[scalar_wait + 1:])


def binary_fixtures():
    """(program, translator) pairs that `pixel_aot_check.py binary` assembles, disassembles and lowers."""
    return [
        *((with_constants(body), translate) for _, body, *_ in F16_PROGRAMS),
    ]


draw = check_f16_draws
