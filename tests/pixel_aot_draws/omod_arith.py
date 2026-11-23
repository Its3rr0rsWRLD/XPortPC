"""Draw family `omod_arith`: pixel_aot_check.py draw --family omod_arith.

The VOP3 output modifiers mul:2, mul:4 and div:2 on the binary32 arithmetic forms: add, sub, subrev, mul, mul_legacy,
min, max, fma, fmac, mad and mac. The order is operation, then omod, then clamp (ISA). The mode is the graphics
default the other binary32 forms model (IEEE bit clear, denormals flushed; see forms/valu_f32.py), where omod is
honoured: the ISA ignores omod only while binary32 denormals are enabled, which a compiler never relies on.

Every program is table-generated from (op, clamp) and exports four registers as uncompressed binary32 with a strict
bitwise compare (f32_modes.uncompressed_export), so the scale is checked exactly rather than through binary16:
v12 is the operation with mul:2, v13 with mul:4, v14 with div:2 and v15 the plain operation. Each runs on constant sets
that put the operation's result at ordinary values (the clamp boundaries from both sides), at a full binary32 mantissa
where the operation rounds once (the forms with an unambiguous rounding), at 1.5 * 2^127 (mul:2 and mul:4 overflow to
infinity, div:2 does not) and at the smallest normal numbers (div:2 of 2^-126 is subnormal and is flushed to zero, of
1.5 * 2^-126 too; mul:2 and mul:4 are exact). The operation's own result is always a normal number.

Wrong references, each of which must mismatch on some set: omod dropped; the wrong factor (mul:2 as mul:4, mul:4 as
mul:2, div:2 as mul:2); omod applied to the plain channel; with clamp, omod applied after clamp (clamp first, then
scale) and clamp dropped; and a div:2 result that keeps its subnormal instead of flushing.
"""
from fractions import Fraction
import math
import struct

from .common import DrawBatch, case_data, compile_shader, must_reject, translate, with_constants
from .f32_modes import uncompressed_export

OMODS = ((" mul:2", 2.0), (" mul:4", 4.0), (" div:2", 0.5))
INF = float("inf")
MIN_NORMAL = 2.0 ** -126
BIG = 1.5 * 2.0 ** 127


def f32(value):
    """Round an exact rational to binary32, ties to even, with overflow to infinity (no subnormal flush)."""
    value = Fraction(value)
    if value == 0:
        return 0.0
    sign = -1 if value < 0 else 1
    magnitude = abs(value)
    exponent = magnitude.numerator.bit_length() - magnitude.denominator.bit_length()
    if Fraction(2) ** exponent > magnitude:
        exponent -= 1
    quantum = Fraction(2) ** (max(exponent, -126) - 23)
    n, rest = divmod(magnitude, quantum)
    if rest * 2 > quantum or (rest * 2 == quantum and n % 2):
        n += 1
    rounded = n * quantum
    if rounded >= Fraction(2) ** 128:
        return sign * INF
    return sign * float(rounded)


def exact(x, y, z, op):
    x, y, z = (Fraction(v) for v in (x, y, z))
    return {"add": x + y, "sub": x - y, "subrev": y - x, "mul": x * y, "mul_legacy": x * y if x and y else Fraction(0),
            "fma": x * y + z, "fmac": x * y + z}[op]


def operation(op, x, y, z):
    """The binary32 result of the operation before omod. Every input set keeps it a finite normal number."""
    if op in ("min", "max"):
        return (min if op == "min" else max)(x, y)
    if op in ("mad", "mac"):  # legacy multiply-add: the product is rounded, then the sum
        return f32(Fraction(f32(Fraction(x) * Fraction(y))) + Fraction(z))
    return f32(exact(x, y, z, op))


def scaled(value, factor, flush=True):
    """value * factor as the hardware does it: exact, infinity past the largest finite number, a subnormal flushed."""
    result = value * factor
    if abs(result) >= 2.0 ** 128:
        return math.copysign(INF, result)
    if flush and result and abs(result) < MIN_NORMAL:
        return math.copysign(0.0, result)
    return result


def sat(value):
    return min(1.0, max(0.0, value))


def reference(op, clamp, x, y, z):
    r = operation(op, x, y, z)
    channels = [scaled(r, factor) for _, factor in OMODS] + [r]
    return [sat(v) for v in channels] if clamp else channels


# Constant sets (x, y, z) per op for a wanted result r. near_max keeps every operand finite when r is huge; otherwise
# the operands are a few times r, so r near the smallest normal number keeps every operand a normal number too.
def inputs(op, r, near_min=False, near_max=False):
    if op == "add":
        return (4 * r, -3 * r, 0.5) if not near_max else (0.5 * r, 0.5 * r, 0.5)
    if op == "sub":
        return (4 * r, 3 * r, 0.5) if not near_max else (1.25 * r, 0.25 * r, 0.5)
    if op == "subrev":
        return (3 * r, 4 * r, 0.5) if not near_max else (0.25 * r, 1.25 * r, 0.5)
    if op in ("mul", "mul_legacy"):
        p = 2.0 ** -27 if near_max else 2.0 ** 27
        return (r * p, 1 / p, 0.5)
    if op == "min":
        return (r, 1.25 * r, 0.5)
    if op == "max":
        if r < 0:
            return (r, 1.25 * r, 0.5)
        return (r, 0.5 * r, 0.5) if near_max else (r, -2 * r, 0.5)  # the larger operand is r in each case
    # fma, fmac, mad, mac: the product and z sum to r, both exact.
    if near_max:
        p = 2.0 ** -27
        return (0.5 * r * p, 1 / p, 0.5 * r)
    return (4 * r, 1.0, -3 * r)


ORDINARY = (0.375, 0.75, -1.25, 3.0, 0.1875)
FULL = tuple(struct.unpack("<f", struct.pack("<f", v))[0] for v in (0.1234567, 0.7654321, -0.2468013))


def input_sets(op, clamp):
    sets = [inputs(op, r) for r in ORDINARY]
    if op in ("add", "sub", "subrev", "mul", "mul_legacy", "min", "max"):
        sets.append(FULL)
    sets.append(inputs(op, BIG, near_max=True))
    sets.append(inputs(op, 1.5 * MIN_NORMAL))
    if not clamp:
        sets.append(inputs(op, MIN_NORMAL))
    # Every set must keep the operation's own result finite and normal; the products and sums of the table are exact.
    for s in sets:
        r = operation(op, *s)
        assert r and MIN_NORMAL <= abs(r) < 2.0 ** 128 and not math.isinf(r), (op, s, r)
        assert all(abs(v) >= MIN_NORMAL for v in s[:2]) and (op not in ("fma", "fmac", "mad", "mac") or abs(s[2]) >= MIN_NORMAL), (op, s)
    return sets


def program(op, clamp):
    suffix = " clamp" if clamp else ""
    body = []
    three = op in ("fma", "mad")
    accumulator = op in ("fmac", "mac")
    if three:
        body.append("v_mov_b32_e32 v18, s46")
    for k, dst in enumerate(("v12", "v13", "v14", "v15")):
        omod = OMODS[k][0] if k < 3 else ""
        if accumulator:
            body.append(f"v_mov_b32_e32 {dst}, s46")
            body.append(f"v_{op}_f32_e64 {dst}, s44, s45{suffix}{omod}")
        elif three:
            body.append(f"v_{op}_f32 {dst}, s44, s45, v18{suffix}{omod}")
        else:
            body.append(f"v_{op}_f32_e64 {dst}, s44, s45{suffix}{omod}")
    return uncompressed_export(body)


def wrong_references(op, clamp):
    """(channel, name, reference(x, y, z) -> the wrong value of that channel)."""
    bugs = []
    factors = [factor for _, factor in OMODS]
    wrong_factor = (4.0, 2.0, 2.0)
    for k in range(3):
        def plain(x, y, z):
            return operation(op, x, y, z)

        def post(value):
            return sat(value) if clamp else value

        bugs.append((k, "omod dropped", lambda x, y, z: post(plain(x, y, z))))
        bugs.append((k, "wrong factor", lambda x, y, z, k=k: post(scaled(plain(x, y, z), wrong_factor[k]))))
        if clamp:
            bugs.append((k, "omod after clamp", lambda x, y, z, k=k: scaled(sat(plain(x, y, z)), factors[k])))
            bugs.append((k, "clamp dropped", lambda x, y, z, k=k: scaled(plain(x, y, z), factors[k])))
    bugs.append((3, "omod on the plain channel", lambda x, y, z: (sat if clamp else float)(scaled(operation(op, x, y, z), 2.0))))
    if clamp:
        bugs.append((3, "clamp dropped", lambda x, y, z: operation(op, x, y, z)))
    # div:2 keeping a subnormal result instead of flushing it (only the smallest-normal sets tell).
    bugs.append((2, "subnormal kept", lambda x, y, z: (sat if clamp else float)(scaled(operation(op, x, y, z), 0.5, flush=False))))
    return bugs


OPS = ("add", "sub", "subrev", "mul", "mul_legacy", "min", "max", "fma", "fmac", "mad", "mac")


def check_omod_arith_draws(directory, compiler, renderer, backend):
    for op in OPS:
        for clamp in (False, True):
            name = f"omod_arith_{op}{'_clamp' if clamp else ''}"
            source = directory / f"{name}.hlsl"
            shader = directory / f"{name}.cso"
            source.write_text(translate(program(op, clamp)), encoding="ascii")
            compile_shader(compiler, source, shader)
            batch = DrawBatch(directory, renderer, backend, shader, "omod_arith")
            bugs = wrong_references(op, clamp)
            separated = [False] * len(bugs)
            for inputs_ in input_sets(op, clamp):
                constants = bytearray(256)
                struct.pack_into("<4f", constants, 12, *inputs_, 0.0)
                expected = reference(op, clamp, *inputs_)
                batch.add(case_data(constants, expected), "pass",
                          f"{name} gives a result other than {expected} for inputs {inputs_}")
                for k, (channel, label, buggy) in enumerate(bugs):
                    value = float(buggy(*inputs_))
                    if separated[k] or struct.pack("<f", value) == struct.pack("<f", expected[channel]):
                        continue
                    wrong = list(expected)
                    wrong[channel] = value
                    batch.add(case_data(constants, wrong), "mismatch",
                              f"A wrong omod result ({label}) escaped detection in {name}, channel {channel}, inputs {inputs_}")
                    separated[k] = True
            batch.flush()
            missing = [bugs[k][1] for k, done in enumerate(separated) if not done]
            assert not missing, (name, missing)


def controls(directory):
    # The lowering: omod scales the operation and flushes a subnormal product, and clamp saturates after both.
    source = translate(program("add", True)).split("float4 main", 1)[1]
    assert "saturate(ftz32(((asfloat(params[0].w) + asfloat(params[1].x)) * 2.0f)))" in source, source
    assert "saturate(ftz32(((asfloat(params[0].w) + asfloat(params[1].x)) * 4.0f)))" in source, source
    assert "saturate(ftz32(((asfloat(params[0].w) + asfloat(params[1].x)) * 0.5f)))" in source, source
    assert "saturate((asfloat(params[0].w) + asfloat(params[1].x)))" in source, source
    source = translate(program("mad", False)).split("float4 main", 1)[1]
    assert "ftz32((mad32(" in source and "* 2.0f" in source, source
    source = translate(program("sub", False)).split("float4 main", 1)[1]
    assert "ftz32(((asfloat(params[0].w) - asfloat(params[1].x)) * 2.0f))" in source, source
    # Refused neighbours: an e32 spelling takes no omod, an unknown factor, omod before clamp, fract (the exact rounding forms take it: family pxblk),
    # a missing operand, and a VOP3-only form in its e32 spelling.
    for line in ("v_add_f32_e32 v12, s44, v13 mul:2", "v_mul_f32_e32 v12, s44, v13 div:2", "v_mac_f32_e32 v12, s44, v13 mul:4",
                 "v_add_f32_e64 v12, s44, s45 mul:3", "v_sub_f32_e64 v12, s44, s45 div:4", "v_add_f32_e64 v12, s44, s45 mul:2 clamp",
                 "v_mad_f32 v12, s44, s45, v13 div:2 clamp", "v_fract_f32_e64 v12, s44 div:2",
                 "v_fract_f32_e64 v12, s44 mul:4", "v_fract_f32_e64 v12, s44 clamp mul:2", "v_add_f32_e64 v12, s44 mul:2",
                 "v_fma_f32_e32 v12, s44, s45, v13 mul:2", "v_mad_f32 v12, s44, s45 mul:2"):
        must_reject(translate, with_constants([line]))


def binary_fixtures():
    """(program, translator) pairs that `pixel_aot_check.py binary` assembles, disassembles and lowers."""
    return [(program(op, clamp), translate) for op in OPS for clamp in (False, True)]


draw = check_omod_arith_draws
