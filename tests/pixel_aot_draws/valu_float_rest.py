"""Draw family `valu_float_rest`: pixel_aot_check.py draw --family valu_float_rest.

Table-driven draws of the float forms lowered in tools/pixel_aot_ops/forms/valu_float_rest.py: v_cvt_off_f32_i4,
v_cvt_flr_i32_f32, v_cvt_rpi_i32_f32, v_cvt_f16_i16, v_cvt_f16_u16, v_cvt_i16_f16, v_cvt_u16_f16, v_sat_pk_u8_i16,
v_frexp_mant_f32, v_frexp_exp_i32_f32, v_frexp_mant_f16, v_frexp_exp_i16_f16 (e32 and e64, with neg and abs on the
sources that take them), v_min3_f16, v_max3_f16, v_med3_f16 (plain, with modifiers and with clamp), and
v_mad_legacy_f32 and v_mac_legacy_f32. The forms that were left out, and why, are in that module's docstring; each has
a must_reject control here.

Every row is one instruction: its sources are constant words 3 to 5 (s44 to s46), the destination v18 is first set from
word 6 (s47), whose high half is a marker (a 16-bit result keeps it; v_mac accumulates the word). The whole 32-bit result
is read back as four bytes (v_cvt_f32_ubyteN into v12..v15), so each channel is one byte of the result word and the draw
is bit for bit. Each row is drawn with several input sets against an independent Python model (integer arithmetic and
struct, not the lowering's expressions); every row also lists wrong references for the bugs a lowering could plausibly
have, each of which must change the result word on some input set (asserted without a GPU) and be reported by the
renderer as a pixel_mismatch.
"""
import math
import re
import struct
import subprocess

from .common import M32, byte, must_reject, narrow_reference, single, translate, ubyte, with_constants

NAN32, INF32 = 0x7fc00000, 0x7f800000


def f32w(x):
    return struct.unpack("<I", struct.pack("<f", x))[0]


def f32v(word):
    return struct.unpack("<f", struct.pack("<I", word))[0]


def h(x):
    return narrow_reference(x)


def hv(word):
    return struct.unpack("<e", struct.pack("<H", word & 0xffff))[0]


def sext(value, bits):
    value &= (1 << bits) - 1
    return value - (1 << bits) if value >> (bits - 1) else value


def saturate_int(value, low, high):
    return min(max(value, low), high)


def junk(word, k):
    """A binary16 or 16-bit word under a junk high half, so a model that ignores the high half is the right one."""
    return ((0xdead, 0xbeef, 0x4d2f, 0xfc01)[k % 4] << 16) | (word & 0xffff)


MARKERS = (0xdead0000, 0xbeef0000, 0x4d2f0000, 0xfc010000, 0x12340000, 0xabcd0000, 0x0f0f0000, 0xf0f00000)


# Models: word (after source modifiers) -> result (a 32-bit word, or its low 16 bits). bug selects a wrong variant.
def m_cvt_off(w, bug):
    n = {"unsigned": w & 15, "sext8": sext(w, 8)}.get(bug, sext(w, 4))
    return f32w(n / {"scale8": 8.0}.get(bug, 16.0))


def to_int32(x, bug, rounding):
    if math.isnan(x):
        return 0x7fffffff if bug == "nan_max" else 0
    if math.isinf(x):
        return 0x7fffffff if x > 0 else 0x80000000
    n = rounding(x)
    if bug == "wrap":
        return n & M32
    return saturate_int(n, -(1 << 31), (1 << 31) - 1) & M32


def m_flr(w, bug):
    rounding = {"trunc": math.trunc, "nearest": round}.get(bug, math.floor)
    return to_int32(f32v(w), bug, rounding)


def m_rpi(w, bug):
    x = f32v(w)
    rounding = {"no_half": lambda v: math.floor(v), "even": round, "ceil": lambda v: math.ceil(v + 0.5) - 1 if False else math.ceil(v)}.get(
        bug, lambda v: math.floor(v + 0.5))
    return to_int32(x, bug, rounding)


def m_f16_i16(w, bug):
    v = (w & 0xffff) if bug == "unsigned" else sext(w, 16)
    if bug == "rtz":
        from .common import half_rtz
        return struct.unpack("<H", struct.pack("<e", half_rtz(float(v))))[0] if abs(v) < 65520 else narrow_reference(float(v))
    return h(float(v))


def m_f16_u16(w, bug):
    v = sext(w, 16) if bug == "signed" else w & 0xffff
    return h(float(v))


def m_i16_f16(w, bug):
    x = hv(w)
    if math.isnan(x):
        return 0x7fff if bug == "nan_max" else 0
    if math.isinf(x):
        return 0x7fff if x > 0 else 0x8000
    n = {"nearest": round, "floor": math.floor}.get(bug, math.trunc)(x)
    return n & 0xffff if bug == "wrap" else saturate_int(n, -32768, 32767) & 0xffff


def m_u16_f16(w, bug):
    x = hv(w)
    if math.isnan(x):
        return 0
    if math.isinf(x):
        return 0xffff if x > 0 else 0
    n = {"nearest": round}.get(bug, math.trunc)(x)
    if bug == "wrap":
        return n & 0xffff
    return saturate_int(n, 0, 32767 if bug == "signed" else 65535)


def m_sat_pk(w, bug):
    lo, hi = sext(w, 16), sext(w >> 16, 16)
    if bug == "unsigned":
        lo, hi = w & 0xffff, (w >> 16) & 0xffff
    top = 127 if bug == "sat127" else 255
    lo, hi = saturate_int(lo, 0, top), saturate_int(hi, 0, top)
    return (lo << 8 | hi) if bug == "swap" else (hi << 8 | lo)


def frexp_parts(x, bug):
    if x == 0 or math.isinf(x) or math.isnan(x):
        return None
    m, e = math.frexp(x)
    return m, e


def m_mant32(w, bug):
    x = f32v(w)
    parts = frexp_parts(x, bug)
    if parts is None:
        return w
    m = parts[0] * (2 if bug == "ieee_scale" else 1)
    return f32w(abs(m) if bug == "no_sign" else m)


def m_exp32(w, bug):
    x = f32v(w)
    if bug == "denormal_zero" and 0 < abs(x) < 2.0 ** -126:
        return 0
    parts = frexp_parts(x, bug)
    return 0 if parts is None else (parts[1] - (1 if bug == "off_by_one" else 0)) & M32


def m_mant16(w, bug):
    x = hv(w)
    parts = frexp_parts(x, bug)
    if parts is None:
        return w & 0xffff
    m = parts[0] * (2 if bug == "ieee_scale" else 1)
    return h(abs(m) if bug == "no_sign" else m)


def m_exp16(w, bug):
    parts = frexp_parts(hv(w), bug)
    return 0 if parts is None else (parts[1] - (1 if bug == "off_by_one" else 0)) & 0xffff


# op -> (source kind, model, result width, bugs, input words)
OPS = {
    "cvt_off_f32_i4": ("bits", m_cvt_off, 32, ("unsigned", "scale8", "sext8"),
                       (0x0, 0x1, 0x7, 0x8, 0xf, 0xfffffff3, 0x12345678, 0xabcdef0d, 0x80, 0x98)),
    "cvt_flr_i32_f32": ("f32", m_flr, 32, ("trunc", "nearest", "wrap", "nan_max"),
                        tuple(f32w(x) for x in (2.5, -2.5, 0.75, -0.75, 3.0, -3.0, 0.5, -0.5, 1e10, -1e10)) + (NAN32, INF32, 0xff800000, 0x4effffff, 0xcf000000)),
    "cvt_rpi_i32_f32": ("f32", m_rpi, 32, ("no_half", "even", "ceil", "wrap", "nan_max"),
                        tuple(f32w(x) for x in (2.5, -2.5, 0.5, -0.5, 1.5, 0.25, 3.0, -3.0, 1e10, -1e10)) + (NAN32, INF32, 0xff800000)),
    "cvt_f16_i16": ("bits", m_f16_i16, 16, ("unsigned", "rtz", "high_zero"),
                    tuple(junk(w, k) for k, w in enumerate((0x0001, 0xffff, 0x0803, 0xf7fd, 0x1003, 0x7fff, 0x8000, 0x0000)))),
    "cvt_f16_u16": ("bits", m_f16_u16, 16, ("signed", "high_zero"),
                    tuple(junk(w, k) for k, w in enumerate((0x0001, 0xffff, 0x0803, 0xf7fd, 0x1003, 0x7fff, 0x8000, 0x0000)))),
    "cvt_i16_f16": ("f16", m_i16_f16, 16, ("nearest", "floor", "wrap", "nan_max", "high_zero"),
                    tuple(junk(h(x), k) for k, x in enumerate((2.5, -2.5, 0.75, -0.75, 1.5, 40000.0, -40000.0, 65504.0, -65504.0, 0.0))) + (junk(0x7c00, 1), junk(0xfc00, 2), junk(0x7e00, 3), junk(0x0001, 0))),
    "cvt_u16_f16": ("f16", m_u16_f16, 16, ("nearest", "wrap", "signed", "high_zero"),
                    tuple(junk(h(x), k) for k, x in enumerate((2.5, -2.5, 0.75, 1.5, 40000.0, 65504.0, -65504.0, 0.0))) + (junk(0x7c00, 1), junk(0xfc00, 2), junk(0x7e00, 3), junk(0x0001, 0))),
    "sat_pk_u8_i16": ("bits", m_sat_pk, 16, ("swap", "unsigned", "sat127", "high_zero"),
                      (0x00ff0100, 0x007f0080, 0xffff8000, 0x7fff0001, 0x00010000, 0x00c8ffc8, 0x12345678, 0x0000fffe)),
    "frexp_mant_f32": ("f32", m_mant32, 32, ("ieee_scale", "no_sign"),
                       tuple(f32w(x) for x in (1.0, -3.0, 0.1, 6.5, -0.0, 0.0, 1e30)) + (0x00000001, 0x00400000, 0x7f7fffff, INF32, 0xff800000)),
    "frexp_exp_i32_f32": ("f32", m_exp32, 32, ("off_by_one", "denormal_zero"),
                          tuple(f32w(x) for x in (1.0, -3.0, 0.1, 6.5, 0.0, 1e30)) + (0x00000001, 0x00400000, 0x7f7fffff, INF32, 0xff800000, NAN32)),
    "frexp_mant_f16": ("f16", m_mant16, 16, ("ieee_scale", "no_sign", "high_zero"),
                       tuple(junk(h(x), k) for k, x in enumerate((1.0, -3.0, 0.1, 6.5, -0.0, 0.0, 65504.0))) + (junk(0x0001, 1), junk(0x7c00, 2), junk(0xfc00, 3))),
    "frexp_exp_i16_f16": ("f16", m_exp16, 16, ("off_by_one", "high_zero"),
                          tuple(junk(h(x), k) for k, x in enumerate((1.0, -3.0, 0.1, 6.5, 0.0, 65504.0))) + (junk(0x0001, 1), junk(0x7c00, 2), junk(0xfc00, 3), junk(0x7e00, 0))),
}
NO_MODIFIER = {"cvt_off_f32_i4", "cvt_f16_i16", "cvt_f16_u16", "sat_pk_u8_i16", "frexp_exp_i32_f32", "frexp_exp_i16_f16"}


def modify(word, kind, neg, absolute):
    """neg and abs on the sign bit of a binary32 word, or on bit 15 of the low half of a binary16 source."""
    mask, sign = (0x7fffffff, 0x80000000) if kind != "f16" else (0x7fff, 0x8000)
    if absolute:
        word &= ~(sign) & M32 if kind != "f16" else 0xffff & mask
    if neg:
        word ^= sign
    return word


def readback():
    return [ubyte(n, 12 + n, "v18", "e32") for n in range(4)]


class Row:
    def __init__(self, name, asm, sources, model, bugs, inputs, count):
        self.name, self.asm, self.sources, self.model, self.bugs, self.inputs = name, asm, sources, model, bugs, inputs[:count]
        self.setup = []  # gfx10 allows two scalar sources per VOP3 instruction and none in the second VOP2 source

    def program(self):
        return with_constants(["v_mov_b32_e32 v18, s47", *self.setup, self.asm, *readback()])

    def words(self, args, k):
        """Constant words 3 to 6: the sources, then the marker word that preloads the destination."""
        sources = list(args) + [0] * (3 - len(args))
        return (*sources, MARKERS[k % len(MARKERS)])

    def result(self, words, bug):
        return self.model(words[:self.sources], words[3], bug)

    def channels(self, words, bug=None):
        result = self.result(words, bug)
        return [float(byte(result, n)) for n in range(4)]


def unary_row(op, spelling, token, neg, absolute, count):
    kind, model, width, bugs, inputs = OPS[op]

    def run(sources, old, bug):
        result = model(modify(sources[0], kind, neg and bug != "no_neg", absolute and bug != "no_abs"), bug)
        if width == 16:
            result = (result & 0xffff) | (0 if bug == "high_zero" else old & 0xffff0000)
        return result

    extra = (("no_neg",) if neg else ()) + (("no_abs",) if absolute else ())
    return Row(f"{op}_{spelling}{token}", f"v_{op}_{spelling} v18, {token.replace('X', 's44')}" if token else f"v_{op}_{spelling} v18, s44",
               1, run, bugs + extra, inputs, count)


def three_f16_rows():
    sets = tuple(tuple(junk(h(x), k + n) for n, x in enumerate(values)) for k, values in enumerate(
        ((1.5, -2.25, 0.75), (-1.5, 2.25, -0.75), (3.0, 1.0, 2.0), (-0.5, 0.25, 4.0), (0.25, 0.75, 0.5), (1.5, -0.5, 0.125), (0.25, -0.5, 0.75), (-0.75, -0.25, 0.5), (0.5, -0.25, 0.25))))
    selectors = {"min3": (min, {"max_for_min": max}), "max3": (max, {"min_for_max": min}),
                 "med3": (lambda a, b, c: sorted((a, b, c))[1], {"min_for_med": min, "max_for_med": max})}
    variants = (("", (0, 0, 0), False), ("mod", (1, 0, 1), False), ("modabs", (0, 3, 2), False), ("clamp", (0, 0, 0), True),
                ("modclamp", (1, 2, 0), True))
    rows = []
    for op, (select, wrongs) in selectors.items():
        for tag, mods, clamp in variants:
            tokens = []
            for n, bits in enumerate(mods):
                token = f"s{44 + n}"
                token = f"|{token}|" if bits & 2 else token
                tokens.append(f"-{token}" if bits & 1 else token)

            def run(sources, old, bug, op=op, select=select, wrongs=wrongs, mods=mods, clamp=clamp):
                values = []
                for word, bits in zip(sources, mods):
                    x = hv(word)
                    x = abs(x) if bits & 2 and bug != "no_abs" else x
                    values.append(-x if bits & 1 and bug != "no_neg" else x)
                result = wrongs.get(bug, select)(*values)
                if clamp and bug != "no_clamp":
                    result = min(1.0, max(0.0, result))
                return (h(result) & 0xffff) | (0 if bug == "high_zero" else old & 0xffff0000)

            bugs = tuple(wrongs) + ("high_zero",) + (("no_neg",) if any(b & 1 for b in mods) else ()) \
                + (("no_abs",) if any(b & 2 for b in mods) else ()) + (("no_clamp",) if clamp else ())
            tokens[2] = tokens[2].replace("s46", "v19")
            asm = f"v_{op}_f16 v18, {', '.join(tokens)}{' clamp' if clamp else ''}"
            rows.append(Row(f"{op}_f16_{tag or 'plain'}", asm, 3, run, bugs, sets, 9))
            rows[-1].setup = ["v_mov_b32_e32 v19, s46"]
    return rows


def legacy_rows():
    sets = tuple(tuple(f32w(x) if isinstance(x, float) else x for x in values) for values in (
        (1.5, 2.5, 0.25), (-3.0, 0.5, 4.0), (0.0, INF32, 1.0), (INF32, -0.0, 1.0), (0x3f800800, 0x3f800800, 0xbf801000), (-0.75, -2.0, 8.0)))
    rows = []
    for op, spelling, tokens in (("mad", "e64", ("s44", "s45", "s46")), ("mad", "e64", ("-s44", "|s45|", "-s46")),
                                 ("mac", "e32", ("s44", "s45")), ("mac", "e64", ("-s44", "|s45|"))):
        mods = [(t.startswith("-"), "|" in t) for t in tokens]

        def run(sources, old, bug, op=op, mods=mods):
            values = []
            for word, (neg, absolute) in zip(sources, mods):
                x = f32v(word)
                x = abs(x) if absolute and bug != "no_abs" else x
                values.append(-x if neg and bug != "no_neg" else x)
            a, b = values[0], values[1]
            c = f32v(old) if op == "mac" else values[2]
            if bug == "no_add":
                c = 0.0
            if bug == "dst_ignored":
                c = 0.0
            zero_rule = (a == 0 or b == 0) and bug != "ieee_mul"
            product = 0.0 if zero_rule else single(a * b) if not (math.isinf(a) and b == 0 or a == 0 and math.isinf(b)) else float("nan")
            if bug == "fused":
                return f32w(single(a * b + c))
            return f32w(single(product + c))

        bugs = ("ieee_mul", "fused") + (("dst_ignored",) if op == "mac" else ("no_add",)) \
            + (("no_neg",) if mods[0][0] else ()) + (("no_abs",) if mods[1][1] else ())
        shown = [t.replace("s46", "v19") for t in tokens]
        if op == "mac" and spelling == "e32":
            shown[1] = "v19"
        asm = f"v_{op}_legacy_f32_{spelling} v18, {', '.join(shown)}"
        rows.append(Row(f"{op}_legacy_f32_{spelling}_{'mod' if mods[0][0] else 'plain'}", asm, len(tokens), run, bugs, sets, 6))
        rows[-1].setup = ["v_mov_b32_e32 v19, s46"] if op == "mad" else ["v_mov_b32_e32 v19, s45"] if spelling == "e32" else []
        if op == "mac":  # the accumulator is the preloaded destination: use the marker as a float
            rows[-1].words = lambda args, k: (*(list(args) + [0] * (3 - len(args))), f32w((0.25, -1.0, 2.0, 8.0, 0.5, 4.0)[k % 6]))
    return rows


def rows():
    out, reduced = [], []
    for op, (kind, model, width, bugs, inputs) in OPS.items():
        out.append(unary_row(op, "e32", "", False, False, len(inputs)))
        reduced.append(unary_row(op, "e64", "", False, False, len(inputs)))
        if op not in NO_MODIFIER:
            for token, neg, absolute in (("-X", True, False), ("|X|", False, True), ("-|X|", True, True)):
                reduced.append(unary_row(op, "e64", token, neg, absolute, len(inputs)))
    return [*out, *reduced, *three_f16_rows(), *legacy_rows()]


def shrink(row):
    """Keep a smallest-first cover of the row's bugs: the inputs that each expose a bug nothing earlier does (at
    least two inputs), so the repeated spellings of an op are drawn on few sets."""
    words = [row.words(args if isinstance(args, tuple) else (args,), k) for k, args in enumerate(row.inputs)]
    keep, pending = [0, len(words) // 2], set(row.bugs)
    exposed = lambda k, bug: row.channels(words[k], bug) != row.channels(words[k])
    # A bug no input of this spelling can expose (floor and trunc agree once abs makes every input positive) is
    # drawn on the e32 spelling of the op, not here.
    row.bugs = tuple(bug for bug in row.bugs if any(exposed(k, bug) for k in range(len(words))))
    pending = set(row.bugs)
    pending -= {bug for bug in pending if any(exposed(k, bug) for k in keep)}
    while pending:
        k = max(range(len(words)), key=lambda k: sum(exposed(k, bug) for bug in pending))
        assert any(exposed(k, bug) for bug in pending), (row.name, pending)
        keep.append(k)
        pending -= {bug for bug in pending if exposed(k, bug)}
    row.inputs = [row.inputs[k] for k in sorted(set(keep))]
    return row


ROWS = rows()
for _row in ROWS:
    if _row.asm.split()[0].endswith("_e64") and _row.sources == 1:
        shrink(_row)


def row_words(row):
    return [row.words(args if isinstance(args, tuple) else (args,), k) for k, args in enumerate(row.inputs)]


def check_models():
    assert len({row.name for row in ROWS}) == len(ROWS)
    # Hand-computed results for a few rows (the model is checked against the instruction semantics, not itself).
    r = {row.name: row for row in ROWS}
    assert r["cvt_off_f32_i4_e32"].result((0x8, 0, 0, 0), None) == f32w(-0.5)
    assert r["cvt_off_f32_i4_e32"].result((0xf, 0, 0, 0), None) == f32w(-0.0625)
    assert r["cvt_flr_i32_f32_e32"].result((f32w(-2.5), 0, 0, 0), None) == 0xfffffffd
    assert r["cvt_rpi_i32_f32_e32"].result((f32w(2.5), 0, 0, 0), None) == 3
    assert r["cvt_rpi_i32_f32_e32"].result((f32w(-0.5), 0, 0, 0), None) == 0
    assert r["cvt_f16_i16_e32"].result((0xffff, 0, 0, 0xdead0000), None) == 0xdeadbc00  # -1.0, high half kept
    assert r["cvt_f16_u16_e32"].result((0x0803, 0, 0, 0), None) == h(2052.0) == 0x6802
    assert r["cvt_i16_f16_e32"].result((h(-2.5), 0, 0, 0), None) == 0xfffe
    assert r["cvt_u16_f16_e32"].result((h(65504.0), 0, 0, 0), None) == 65504
    assert r["sat_pk_u8_i16_e32"].result((0x00ff0100, 0, 0, 0), None) == 0xffff
    assert r["sat_pk_u8_i16_e32"].result((0xffff8000, 0, 0, 0), None) == 0
    assert r["frexp_mant_f32_e32"].result((f32w(-3.0), 0, 0, 0), None) == f32w(-0.75)
    assert r["frexp_exp_i32_f32_e32"].result((f32w(-3.0), 0, 0, 0), None) == 2
    assert r["frexp_exp_i32_f32_e32"].result((1, 0, 0, 0), None) == (-148) & M32
    assert r["frexp_exp_i16_f16_e32"].result((h(0.1), 0, 0, 0), None) == (-3) & 0xffff
    assert r["frexp_mant_f16_e32"].result((h(6.5), 0, 0, 0), None) == h(0.8125)
    assert r["med3_f16_plain"].result((h(1.5), h(-2.25), h(0.75), 0), None) == h(0.75)
    assert r["max3_f16_clamp"].result((h(1.5), h(-0.5), h(0.125), 0), None) == 0x3c00
    assert r["mad_legacy_f32_e64_plain"].result((0, INF32, f32w(1.0), 0), None) == f32w(1.0)
    assert r["mad_legacy_f32_e64_plain"].result((0x3f800800, 0x3f800800, 0xbf801000, 0), None) == 0
    for row in ROWS:
        words = row_words(row)
        assert words
        for bug in row.bugs:
            assert any(row.channels(w, bug) != row.channels(w) for w in words), (row.name, bug)


def check_draws(directory, compiler, renderer, backend):
    check_models()
    case = directory / "valu_float_rest.case"
    for n, row in enumerate(ROWS):
        source = directory / f"valu_float_rest_{n}.hlsl"
        shader = directory / f"valu_float_rest_{n}.cso"
        source.write_text(translate(row.program()), encoding="ascii")
        subprocess.run([compiler, "-Gis", "-T", "ps_6_0", "-E", "main", "-Fo", shader, source], check=True)
        draw = [renderer, backend, "--check-pixel-case", shader, case]
        sets = row_words(row)
        for words in sets:
            constants = bytearray(256)
            struct.pack_into("<4I", constants, 12, *words)
            case.write_bytes(constants + struct.pack("<4f", *row.channels(words)) * 64)
            subprocess.run(draw, check=True)
        for bug in row.bugs:
            words = next(w for w in sets if row.channels(w, bug) != row.channels(w))
            constants = bytearray(256)
            struct.pack_into("<4I", constants, 12, *words)
            case.write_bytes(constants + struct.pack("<4f", *row.channels(words, bug)) * 64)
            result = subprocess.run(draw, capture_output=True, text=True)
            if result.returncode != 1 or "pixel_mismatch" not in result.stderr:
                raise AssertionError(f"Lowering bug {bug} escaped detection in {row.name} for words {words}")


def refused(line):
    try:
        translate(with_constants([line]))
    except ValueError as error:
        assert "Unsupported instruction" in str(error), (line, error)
        return
    raise AssertionError(f"{line} was accepted")


# Forms that are not lowered (module docstring): each spelling is refused as an unsupported instruction.
REFUSED = (
    "v_fma_f16 v19, s44, s45, s46", "v_fma_f16 v19, -s44, |s45|, s46 clamp", "v_mad_f16 v19, s44, s45, s46",
    "v_fmac_f16_e32 v19, s44, v13", "v_fmac_f16_e64 v19, s44, s45", "v_fmaak_f16 v19, s44, v13, 0x3c00",
    "v_fmamk_f16 v19, s44, 0x3c00, v13",
    "v_div_fmas_f32 v19, s44, s45, s46", "v_div_scale_f32 v19, vcc, s44, s45, s46", "v_div_fixup_f32 v19, s44, s45, s46",
    "v_div_fixup_f16 v19, s44, s45, s46",
    "v_ldexp_f32 v19, s44, s45", "v_ldexp_f32 v19, s44, 3",
    "v_cvt_norm_i16_f16_e32 v19, s44", "v_cvt_norm_u16_f16_e32 v19, s44", "v_cvt_norm_i16_f16_e64 v19, s44",
    "v_cvt_norm_u16_f16_e64 v19, s44",
    "v_cvt_pknorm_i16_f32 v19, s44, s45", "v_cvt_pknorm_u16_f32 v19, s44, s45", "v_cvt_pknorm_i16_f16 v19, s44, s45",
    "v_cvt_pknorm_u16_f16 v19, s44, s45",
)


def controls(directory):
    for line in REFUSED:
        refused(line)
    # The lowering is the one the DPP forms use for these conversions: same helpers, with the plain-encoding operand rules.
    text = translate(with_constants(["v_cvt_flr_i32_f32_e64 v19, -|s44|"]))
    assert "dpp_cvt_i32_f32(floor((-abs(" in text, text
    text = translate(with_constants(["v_mov_b32_e32 v18, s47", "v_cvt_i16_f16_e64 v18, -|s44|"]))
    assert "0x7fffu) ^ 0x8000u" in text.replace(")", "") or "& 0x7fffu" in text, text
    assert "& 0xffff0000u" in text and "uint f16w" in text, text  # the high half of the destination is kept
    text = translate(with_constants(["v_frexp_exp_i32_f32_e64 v19, -|s44|"]))
    assert "& 0x7fffffffu" in text and "^ 0x80000000u" in text, text
    text = translate(with_constants(["v_min3_f16 v19, s44, s45, s46 clamp"]))
    assert "saturate(min(min(" in text and "narrow16(" in text, text
    assert "med3_f32(" in translate(with_constants(["v_med3_f16 v19, s44, s45, s46"]))
    assert "mad_legacy32(" in translate(with_constants(["v_mad_legacy_f32 v19, s44, s45, s46"]))
    # A 16-bit result with no value in the destination keeps a zero high half (as v_cvt_f16_f32).
    assert "uint f16w" in translate(with_constants(["v_cvt_f16_u16_e32 v19, s44"]))
    # Refusals of the forms that are lowered: modifiers where the source takes none, the e32 spelling with a VOP3
    # feature, clamp and omod on forms without them, a wrong operand count, a destination that holds no numeric word.
    for line in ("v_cvt_off_f32_i4_e64 v19, -s44", "v_cvt_f16_i16_e64 v19, |s44|", "v_sat_pk_u8_i16_e64 v19, -s44",
                 "v_cvt_flr_i32_f32_e32 v19, -s44", "v_cvt_flr_i32_f32_e32 v19, |s44|", "v_frexp_mant_f16_e32 v19, -s44",
                 "v_cvt_flr_i32_f32_e64 v19, s44 clamp", "v_cvt_flr_i32_f32_e64 v19, s44 mul:2", "v_cvt_f16_u16_e64 v19, s44 clamp",
                 "v_frexp_mant_f32_e64 v19, s44 div:2", "v_cvt_flr_i32_f32_e64 v19, s44, s45", "v_cvt_flr_i32_f32 v19",
                 "v_min3_f16 v19, s44, s45", "v_min3_f16 v19, s44, s45, s46, s47", "v_max3_f16 v19, s44, s45, s46 mul:2",
                 "v_med3_f16 v19, --s44, s45, s46", "v_med3_f16 v19, s44, s45, s46 clamp clamp",
                 "v_mad_legacy_f32_e32 v19, s44, s45, s46", "v_mad_legacy_f32 v19, s44, s45", "v_mad_legacy_f32 v19, s44, s45, s46 mul:2",
                 "v_mac_legacy_f32_e32 v19, s44, s45 clamp", "v_mac_legacy_f32_e32 v19, -s44, s45",
                 "v_cvt_f16_i16_e32 v8, s44", "v_min3_f16 v9, s44, s45, s46", "v_cvt_off_f32_i4_e32 v19, 1.5e3"):
        must_reject(translate, with_constants([line]))
    # Reading a register that was never written is refused, so is a mac accumulating into one.
    must_reject(translate, with_constants(["v_mac_legacy_f32_e32 v19, s44, s45"]))


def binary_fixtures():
    """(program, translator) pairs that `pixel_aot_check.py binary` assembles, disassembles and lowers."""
    return [(row.program(), translate) for row in ROWS]


draw = check_draws
