"""Draw family `int_convert`: pixel_aot_check.py draw --family int_convert.

Conversions between binary32 and 32-bit integers: v_cvt_f32_i32, v_cvt_f32_u32, v_cvt_i32_f32 and v_cvt_u32_f32 in
their e32 and e64 forms, with clamp and omod on the integer-to-float forms and neg/abs on the float-to-integer ones.
Every program converts constant word 3 (s44, directly or through a v_mov_b32 copy in v18) and reads the whole 32-bit
result back as its four bytes (v_cvt_f32_ubyteN into v12..v15), so each draw checks one result word bit for bit
against a Python-integer reference of the RDNA semantics (tools/pixel_aot_ops/forms/valu_int.py): round to nearest
even into binary32; toward zero into an integer, saturating at the limits of the type, with NaN giving 0.

The words are chosen at the edges: rounding ties on both sides of an even mantissa near 2^24, 2^31 and 2^32, the
extremes of both integer types; for the float sources NaNs of both signs (quiet and signalling), the infinities,
+-2^31 and its neighbours, 2^32 and its neighbour, values far out of range, halves and fractions of both signs, -0.0
and denormals. Each program has wrong references for the bugs a lowering could plausibly have (round toward zero or
ties away, the wrong signedness, omod or clamp dropped or applied in the wrong order, the x86 "integer indefinite"
for NaN and overflow, rounding or flooring instead of truncation, a dropped source modifier, wrapping instead of
saturating). Each one must give a different word for at least one input, and the renderer must report it as a
pixel_mismatch.
"""
import math
import struct
import subprocess

from .common import M32, byte, must_reject, signed, translate, ubyte, with_constants

SIGN = 0x80000000


def readback(register):
    return [ubyte(n, 12 + n, register, "e32") for n in range(4)]


def f32_bits(value):
    return struct.unpack("<I", struct.pack("<f", value))[0]


def f32_value(word):
    return struct.unpack("<f", struct.pack("<I", word))[0]


def round_integer(n, mode):
    """n rounded to 24 significant bits: "rne" to nearest, ties to even; "away" ties away from zero; "rtz" toward
    zero. Integer arithmetic only, so the reference does not depend on the host's conversion."""
    magnitude = abs(n)
    shift = max(0, magnitude.bit_length() - 24)
    quotient, remainder = divmod(magnitude, 1 << shift)
    half = (1 << shift) >> 1
    if shift and mode == "rne":
        quotient += remainder > half or (remainder == half and quotient & 1)
    elif shift and mode == "away":
        quotient += remainder >= half
    return -(quotient << shift) if n < 0 else quotient << shift


def to_float(word, kind, omod=1.0, clamp=False, mode="rne", clamp_first=False):
    """The binary32 word of v_cvt_f32_{i32,u32}: round, then omod, then clamp (or clamp first, a bug)."""
    value = float(round_integer(signed(word) if kind == "i32" else word, mode))
    if clamp and clamp_first:
        value = min(max(value, 0.0), 1.0)
    value *= omod
    if clamp and not clamp_first:
        value = min(max(value, 0.0), 1.0)
    return f32_bits(value)


def modified(word, modifier):
    """The source word after the e64 source modifier: "" none, "neg", "abs" or "neg_abs" (sign-bit operations)."""
    return {"": word, "neg": word ^ SIGN, "abs": word & ~SIGN & M32, "neg_abs": word | SIGN}[modifier]


def is_nan(word):
    return (word & ~SIGN & M32) > 0x7f800000


def to_int(word, kind, modifier="", nan=0, high=None, low=None, rounding=math.trunc, wrap=False):
    """The word of v_cvt_{i32,u32}_f32: NaN gives `nan` (0), out of range saturates to [low, high] (the limits of
    the type), everything else rounds by `rounding` (toward zero). wrap makes u32 go through i32 (a bug)."""
    bits = modified(word, modifier)
    if is_nan(bits):
        return nan
    value = f32_value(bits)
    lo, hi = (-(1 << 31), (1 << 31) - 1) if kind == "i32" or wrap else (0, M32)
    lo, hi = lo if low is None else low, hi if high is None else high
    if math.isinf(value):
        return (hi if value > 0 else lo) & M32
    result = rounding(value)
    if result > hi:
        return hi & M32
    if result < lo:
        return lo & M32
    return result & M32


def nearest(value):
    return round(value)  # Python rounds half to even


# Integer source words: zero, +-1, the 24-bit limit and ties around it, ties around 2^31 and 2^32 (an odd mantissa
# below, an even one above and the reverse), the extremes, and plain words of both signs.
INT_WORDS = (0x00000000, 0x00000001, 0x00000002, 0x00000003, 0xffffffff, 0xfffffffe, 0xffffff81, 0x00ffffff,
             0x01000001, 0x01000003, 0x01000005, 0x02000006, 0xfefffffd, 0xfeffffff, 0x7fffff40, 0x7fffffbf,
             0x7fffffc0, 0x7fffffff, 0x80000000, 0x80000001, 0x80000080, 0x80000180, 0x800000c1, 0xffffff7f,
             0xffffff80, 0x12345678, 0x89abcdef, 0xfffffffd)
SMALL_INT_WORDS = (0x00000000, 0x00000001, 0x00000002, 0x00000003, 0x00000004, 0xffffffff, 0xfffffffe, 0x7fffffff,
                   0x80000000, 0x01000003)

# Float source words: +-0, denormals, fractions and halves of both signs, the limits of both integer types and their
# neighbours, values far out of range, the largest finites, the infinities and NaNs of both signs. 1.5, 3.0, the
# payload NaN 0xffc00001 and the integer word 0xfffffffd come from the test values of R0Y00/Xbox2Windows#438
# (JB2WIN) and #392 (abilliontokens); no code is taken from them.
FLOAT_WORDS = (0x00000000, 0x80000000, 0x00000001, 0x807fffff, 0x3f000000, 0xbf000000, 0x3f7fffff, 0xbf7fffff,
               0x3f800000, 0xbf800000, 0xbfc00000, 0x40200000, 0xc0200000, 0x40300000, 0xc0300000, 0x4b7fffff,
               0x4effffff, 0x4f000000, 0x4f000001, 0xceffffff, 0xcf000000, 0xcf000001, 0x4f32d05e, 0x4f7fffff,
               0x4f800000, 0x501502f9, 0xd01502f9, 0x7f7fffff, 0xff7fffff, 0x7f800000, 0xff800000, 0x7fc00000,
               0xffc00000, 0x7f800001, 0xffbfffff, 0x3fc00000, 0x40400000, 0xffc00001)


def int_program(kind, line, *, omod=1.0, clamp=False, through_vgpr=True):
    body = (["v_mov_b32_e32 v18, s44"] if through_vgpr else []) + [line] + readback("v19")
    bugs = {"other_signedness": lambda w: to_float(w, "u32" if kind == "i32" else "i32", omod, clamp)}
    if not clamp:  # a clamped result is 0, a multiple of 1/2 or 1: rounding never shows
        bugs["round_toward_zero"] = lambda w: to_float(w, kind, omod, mode="rtz")
        bugs["ties_away"] = lambda w: to_float(w, kind, omod, mode="away")
    if omod < 1.0 or (omod > 1.0 and not clamp):  # with clamp, a doubled integer saturates like the integer
        bugs["omod_dropped"] = lambda w: to_float(w, kind, 1.0, clamp)
    if clamp:
        bugs["clamp_dropped"] = lambda w: to_float(w, kind, omod, False)
        if omod != 1.0:
            bugs["clamp_before_omod"] = lambda w: to_float(w, kind, omod, True, clamp_first=True)
    return (line, body, lambda w: to_float(w, kind, omod, clamp), SMALL_INT_WORDS if clamp else INT_WORDS, bugs)


def float_program(kind, line, modifier="", through_vgpr=True):
    body = (["v_mov_b32_e32 v18, s44"] if through_vgpr else []) + [line] + readback("v19")
    bugs = {
        "nan_indefinite": lambda w: to_int(w, kind, modifier, nan=SIGN if kind == "i32" else M32),
        "round_to_nearest": lambda w: to_int(w, kind, modifier, rounding=nearest),
    }
    if kind == "i32" and modifier != "abs":  # floor and truncation differ only below zero, where u32 gives 0
        bugs["floor"] = lambda w: to_int(w, kind, modifier, rounding=math.floor)
    if kind == "i32":
        bugs["overflow_indefinite"] = lambda w: to_int(w, kind, modifier, high=-(1 << 31))
        bugs["nan_saturates"] = lambda w: to_int(w, kind, modifier, nan=0x7fffffff if not modified(w, modifier) & SIGN else SIGN)
    else:
        bugs["negative_wraps"] = lambda w: to_int(w, "i32", modifier)
        bugs["signed_limit"] = lambda w: to_int(w, kind, modifier, high=(1 << 31) - 1)
    if modifier:
        bugs["modifier_dropped"] = lambda w: to_int(w, kind)
    if modifier == "neg_abs":
        bugs["abs_dropped"] = lambda w: to_int(w, kind, "neg")
    return (line, body, lambda w: to_int(w, kind, modifier), FLOAT_WORDS, bugs)


CONVERT_PROGRAMS = (
    int_program("i32", "v_cvt_f32_i32_e32 v19, s44", through_vgpr=False),
    int_program("i32", "v_cvt_f32_i32_e32 v19, v18"),
    int_program("i32", "v_cvt_f32_i32_e64 v19, v18"),
    int_program("i32", "v_cvt_f32_i32_e64 v19, v18 mul:2", omod=2.0),  # full-screen UVs from the vertex index
    int_program("i32", "v_cvt_f32_i32_e64 v19, s44 div:2", omod=0.5, through_vgpr=False),
    int_program("i32", "v_cvt_f32_i32_e64 v19, v18 clamp", clamp=True),
    int_program("i32", "v_cvt_f32_i32_e64 v19, v18 clamp div:2", omod=0.5, clamp=True),
    int_program("u32", "v_cvt_f32_u32_e32 v19, s44", through_vgpr=False),
    int_program("u32", "v_cvt_f32_u32_e32 v19, v18"),
    int_program("u32", "v_cvt_f32_u32_e64 v19, v18 mul:2", omod=2.0),
    int_program("u32", "v_cvt_f32_u32_e64 v19, s44 mul:4", omod=4.0, through_vgpr=False),
    int_program("u32", "v_cvt_f32_u32_e64 v19, v18 clamp mul:2", omod=2.0, clamp=True),
    float_program("i32", "v_cvt_i32_f32_e32 v19, v18"),
    float_program("i32", "v_cvt_i32_f32_e32 v19, s44", through_vgpr=False),
    float_program("i32", "v_cvt_i32_f32_e64 v19, -v18", "neg"),
    float_program("i32", "v_cvt_i32_f32_e64 v19, |s44|", "abs", through_vgpr=False),
    float_program("i32", "v_cvt_i32_f32_e64 v19, -|v18|", "neg_abs"),
    float_program("u32", "v_cvt_u32_f32_e32 v19, v18"),
    float_program("u32", "v_cvt_u32_f32_e32 v19, s44", through_vgpr=False),
    float_program("u32", "v_cvt_u32_f32_e64 v19, -v18", "neg"),
    float_program("u32", "v_cvt_u32_f32_e64 v19, |v18|", "abs"),
)

# Conversions of an inline integer, a literal and inline floats. The four channels are one byte of each result; each
# bug changes one channel: -16 converted as unsigned, the literal tie rounded toward zero, and the float constants
# read as the integer bit patterns of the encoding (-4.0 as 0xc0800000 is then a NaN, 2.0 is 0x40000000).
CONSTANT_PROGRAM = (
    ["v_cvt_f32_i32_e32 v18, -16", "v_cvt_f32_u32_e32 v19, 0x7fffffc0", "v_cvt_i32_f32_e32 v20, -4.0",
     "v_cvt_u32_f32_e32 v21, 2.0",
     ubyte(3, 12, "v18", "e32"), ubyte(3, 13, "v19", "e32"), ubyte(0, 14, "v20", "e32"), ubyte(0, 15, "v21", "e32")],
    [byte(f32_bits(-16.0), 3), byte(f32_bits(2.0 ** 31), 3), byte((-4) & M32, 0), 2],
    {"unsigned_inline_integer": (0, byte(to_float(0xfffffff0, "u32"), 3)),
     "literal_toward_zero": (1, byte(to_float(0x7fffffc0, "u32", mode="rtz"), 3)),
     "float_constant_bits": (2, byte(to_int(0xfffffffc, "i32"), 0)),
     "float_constant_integer": (3, byte(0x40000000, 0))},
)


def constants_of(word):
    constants = bytearray(256)
    struct.pack_into("<4I", constants, 12, word, 0, 0, 0)
    return constants


def expect(case, constants, channels):
    case.write_bytes(constants + struct.pack("<4f", *(float(c) for c in channels)) * 64)


def run_word_programs(directory, compiler, renderer, backend, prefix, programs, constants_of=constants_of):
    """Each program is (name, body, model(input) -> result word, inputs, {bug: wrong(input) -> word}); the body
    leaves the four bytes of the result in v12..v15. Every input is drawn against the model; every bug is drawn,
    and must be reported as a pixel_mismatch, for the first input where it gives another word."""
    case = directory / f"{prefix}.case"
    for index, (name, body, model, inputs, bugs) in enumerate(programs):
        source = directory / f"{prefix}{index}.hlsl"
        shader = directory / f"{prefix}{index}.cso"
        source.write_text(translate(with_constants(body)), encoding="ascii")
        subprocess.run([compiler, "-Gis", "-T", "ps_6_0", "-E", "main", "-Fo", shader, source], check=True)
        draw = [renderer, backend, "--check-pixel-case", shader, case]
        pending = dict(bugs)
        for value in inputs:
            constants = constants_of(value)
            word = model(value)
            expect(case, constants, [byte(word, n) for n in range(4)])
            result = subprocess.run(draw, capture_output=True, text=True)
            if result.returncode == 77:  # no adapter: a skip, reported by pixel_aot_check.py
                raise subprocess.CalledProcessError(77, draw, result.stdout, result.stderr)
            if result.returncode:
                raise AssertionError(f"{name}: input {value} gives a result other than {word:#010x} on {backend}: "
                                     f"{result.stdout}{result.stderr}")
            for bug, wrong in list(pending.items()):
                bad = wrong(value)
                if bad == word:
                    continue
                del pending[bug]
                expect(case, constants, [byte(bad, n) for n in range(4)])
                result = subprocess.run(draw, capture_output=True, text=True)
                if result.returncode != 1 or "pixel_mismatch" not in result.stderr:
                    raise AssertionError(f"Wrong reference {bug} escaped detection in {name}, input {value}")
        assert not pending, (name, sorted(pending))


def check_int_convert_draws(directory, compiler, renderer, backend):
    run_word_programs(directory, compiler, renderer, backend, "cvt", CONVERT_PROGRAMS)
    body, channels, bugs = CONSTANT_PROGRAM
    source, shader, case = directory / "cvtk.hlsl", directory / "cvtk.cso", directory / "cvtk.case"
    source.write_text(translate(with_constants(body)), encoding="ascii")
    subprocess.run([compiler, "-Gis", "-T", "ps_6_0", "-E", "main", "-Fo", shader, source], check=True)
    draw = [renderer, backend, "--check-pixel-case", shader, case]
    expect(case, constants_of(0), channels)
    subprocess.run(draw, check=True)
    for bug, (channel, wrong) in bugs.items():
        assert wrong != channels[channel], bug
        expect(case, constants_of(0), [wrong if n == channel else c for n, c in enumerate(channels)])
        result = subprocess.run(draw, capture_output=True, text=True)
        if result.returncode != 1 or "pixel_mismatch" not in result.stderr:
            raise AssertionError(f"Wrong reference {bug} escaped detection in the constant conversions")


def check_references():
    """The integer rounding agrees with the host's binary32 rounding (ties to even), and every bug of every program
    is separated by some input, so no wrong reference is vacuous."""
    for word in INT_WORDS:
        for n in (signed(word), word):
            assert f32_bits(float(round_integer(n, "rne"))) == f32_bits(float(n)), hex(word)
    assert to_float(0x7fffffc0, "i32") == f32_bits(2.0 ** 31) and to_float(0x7fffffbf, "i32") == 0x4effffff
    assert to_float(0x01000001, "i32") == 0x4b800000 and to_float(0x01000003, "i32") == 0x4b800002
    assert to_float(0xffffff80, "u32") == f32_bits(2.0 ** 32) and to_float(0xffffffff, "i32") == 0xbf800000
    assert to_float(0xffffffff, "i32", 2.0) == 0xc0000000 and to_float(3, "i32", 0.5, True) == 0x3f800000
    for word, i32, u32 in ((0x7fc00000, 0, 0), (0xffc00000, 0, 0), (0x7f800001, 0, 0), (0x7f800000, 0x7fffffff, M32),
                           (0xff800000, SIGN, 0), (0x4f000000, 0x7fffffff, SIGN), (0xcf000000, SIGN, 0),
                           (0x4effffff, 0x7fffff80, 0x7fffff80), (0x4f800000, 0x7fffffff, M32),
                           (0x4f7fffff, 0x7fffffff, 0xffffff00), (0xc0300000, (-2) & M32, 0), (0x40300000, 2, 2),
                           (0x80000000, 0, 0), (0x807fffff, 0, 0), (0xbf7fffff, 0, 0), (0x501502f9, 0x7fffffff, M32)):
        assert (to_int(word, "i32"), to_int(word, "u32")) == (i32, u32), hex(word)
    for name, _, model, inputs, bugs in CONVERT_PROGRAMS:
        for bug, wrong in bugs.items():
            assert any(wrong(v) != model(v) for v in inputs), (name, bug)


def controls(directory):
    check_references()
    # The lowering: integer to float through exact 16-bit halves and one rounding add; float to integer with the NaN
    # and range tests on the bits; omod then clamp; no D3D conversion of an out-of-range value.
    main = translate(with_constants(CONVERT_PROGRAMS[6][1])).split("float4 main", 1)[1]
    assert "float(asint(cvtw21) >> 16) * 65536.0f + float(cvtw21 & 0xffffu)" in main, main
    assert "saturate((float(asint(cvtw21) >> 16) * 65536.0f + float(cvtw21 & 0xffffu)) * 0.5f)" in main, main
    main = translate(with_constants(CONVERT_PROGRAMS[11][1])).split("float4 main", 1)[1]
    assert "saturate((float(cvtw21 >> 16u) * 65536.0f + float(cvtw21 & 0xffffu)) * 2.0f)" in main, main
    main = translate(with_constants(CONVERT_PROGRAMS[16][1])).split("float4 main", 1)[1]
    assert "cvtm21 > 0x7f800000u ? 0u : cvtm21 >= 0x4f000000u ? 0x7fffffffu + (cvtb21 >> 31u) : asuint(int(cvti21))" in main, main
    assert "float cvti21 = asfloat(min(cvtm21, 0x4effffffu) | (cvtb21 & 0x80000000u));" in main, main
    assert "asuint((-abs(asfloat(movw20))))" in main, main
    main = translate(with_constants(CONVERT_PROGRAMS[17][1])).split("float4 main", 1)[1]
    assert "cvtb21 > 0x7f800000u ? 0u : cvtb21 >= 0x4f800000u ? 0xffffffffu : uint(cvti21)" in main, main
    assert "float cvti21 = asfloat(cvtb21 < 0x4f800000u ? cvtb21 : 0u);" in main, main
    # Refused: clamp and omod on the e32 forms and on float-to-integer conversions (llvm-mc assembles the e64 ones),
    # source modifiers on an integer source or on an e32 float source, unset and outstanding sources, and the
    # neighbouring forms this card does not lower.
    for line in ("v_cvt_f32_i32_e32 v19, v18 clamp", "v_cvt_f32_i32_e32 v19, v18 mul:2", "v_cvt_f32_u32_e32 v19, s44 div:2",
                 "v_cvt_f32_i32_e64 v19, -v18", "v_cvt_f32_i32_e64 v19, |v18|", "v_cvt_f32_u32_e64 v19, -s44",
                 "v_cvt_f32_i32_e64 v19, v18 mul:8", "v_cvt_f32_i32_e64 v19, v18 div:2 clamp",
                 "v_cvt_i32_f32_e64 v19, v18 clamp", "v_cvt_i32_f32_e64 v19, v18 mul:2", "v_cvt_u32_f32_e64 v19, v18 div:2",
                 "v_cvt_u32_f32_e64 v19, -|v18| clamp", "v_cvt_i32_f32_e32 v19, -v18", "v_cvt_u32_f32_e32 v19, |v18|",
                 "v_cvt_i32_f32_e32 v19, v30", "v_cvt_f32_i32_e32 v19, v30", "v_cvt_f32_u32_e32 v19, s90",
                 "v_cvt_f32_i32_dpp v19, v18 row_shl:1 row_mask:0xf bank_mask:0xf",
                 "v_cvt_f32_i32_e32 v19, 0x100000000", "v_cvt_i32_f32_e32 v19, 0x100000000"):
        must_reject(translate, with_constants(["v_mov_b32_e32 v18, s44", line]))
    program = with_constants([])
    load = program.index("s_buffer_load_dwordx4 s[44:47], s[44:47], 0xc") + 1
    wait = program.index("s_waitcnt vmcnt(0)")
    for at, early in ((load, "v_cvt_f32_i32_e32 v19, s44"), (load, "v_cvt_i32_f32_e32 v19, s45"),
                      (wait, "v_cvt_f32_u32_e32 v19, v13"), (wait, "v_cvt_u32_f32_e32 v19, v12"),
                      (wait, "v_cvt_f32_i32_e32 v13, 5"), (wait, "v_cvt_i32_f32_e32 v14, 1.0")):
        must_reject(translate, program[:at] + [early] + program[at:])


def binary_fixtures():
    """(program, translator) pairs that `pixel_aot_check.py binary` assembles, disassembles and lowers."""
    return [*((with_constants(body), translate) for _, body, *_ in CONVERT_PROGRAMS),
            (with_constants(CONSTANT_PROGRAM[0]), translate)]


draw = check_int_convert_draws
