"""Draw family `cf2_exec`: pixel_aot_check.py draw --family cf2_exec.

CF-2b (docs/design/control-flow.md, CF-2 section 3, card CF-2b): EXEC algebra in straight-line code. The lane bit
`ex` is narrowed by v_cmpx_* (f32, f16, i32, u32, i16, u16 and class, VOPC and VOP3; gfx10 writes EXEC only) and by
the ten *_saveexec_b64 forms, combined with lane masks by the SOP2 mask operations (EXEC, VCC, compare masks and the
uniform mask of s_cselect_b64 D, -1, 0), and restored by s_mov_b64 exec, S before the export. A VOPC compare while
the lane is inactive writes 0 (D = ex && cmp), and a VGPR written while it is inactive keeps its old value.

Every draw renders the 8x8 pixel case (texel (x, y) = (RAMP[x], RAMP[y], 128, 255), one pixel per texel), so the
conditions come from the sample and differ between pixels, also inside a quad. The results are small integers
(exact in binary16) and each program has a per-pixel Python reference and wrong references (a mask operation with
its operands or sense swapped, a v_cmpx that does not narrow, a saveexec that saves the new EXEC, a masked write
that is not masked) that must each be reported as a pixel_mismatch. Branches on EXEC are CF-2c (family cf2_skip)."""
import math
import struct
import subprocess

from pixel_aot_ops.dispatch import dispatch
from pixel_aot_ops.lowering import Lowering, masked_writes

from .common import RAMP, must_reject, translate, with_constants

NAN = float("nan")


def f32_bits(value):
    return struct.unpack("<I", struct.pack("<f", value))[0]


def word(value):
    return f32_bits(value) if isinstance(value, float) else value & 0xffffffff


# X and Y: the red and green bytes of the pixel's texel as integers (v20, v21), X also as a float (v24) and as
# binary16 (v25). From the unorm sample: 255 * R rounded to nearest is exact for every byte.
PREP = [
    "v_mul_f32_e32 v20, 0x437f0000, v12",
    "v_rndne_f32_e32 v20, v20",
    "v_cvt_u32_f32_e32 v20, v20",
    "v_mul_f32_e32 v21, 0x437f0000, v13",
    "v_rndne_f32_e32 v21, v21",
    "v_cvt_u32_f32_e32 v21, v21",
    "v_cvt_f32_u32_e32 v24, v20",
    "v_cvt_f16_f32_e32 v25, v24",
]


def outputs(*registers):
    return [f"v_mov_b32_e32 v{12 + n}, {r}" for n, r in enumerate(registers)]


class Pixel:
    def __init__(self, x, y, constants):
        self.X, self.Y = RAMP[x], RAMP[y]
        self.R, self.G = RAMP[x] / 255, RAMP[y] / 255
        self.k = constants  # the words s44..s47


def f32(w):
    return struct.unpack("<f", struct.pack("<I", w & 0xffffffff))[0]


def f16(w):
    return struct.unpack("<e", struct.pack("<H", w & 0xffff))[0]


def s32(w):
    w &= 0xffffffff
    return w - (1 << 32) if w & 0x80000000 else w


def s16(w):
    w &= 0xffff
    return w - (1 << 16) if w & 0x8000 else w


def bits(values):
    """A list of booleans, most significant first, as the binary number the programs accumulate (v = 2 v + bit)."""
    total = 0
    for value in values:
        total = 2 * total + int(bool(value))
    return float(total)


# --- if/else through s_and_saveexec_b64, as ACO lays it out without skips --------------------------------------------
IF_ELSE = [
    "v_mov_b32_e32 v22, 1.0",
    "v_mov_b32_e32 v23, 2.0",
    "v_mov_b32_e32 v26, 0",
    "v_cmp_lt_f32_e32 vcc_lo, s44, v12",  # c = T < R
    "s_and_saveexec_b64 s[60:61], vcc",
    "v_mov_b32_e32 v22, 4.0",  # then
    "v_add_f32_e32 v23, 1.0, v23",
    "s_andn2_b64 exec, s[60:61], exec",  # else: the saved lanes that were not in the then-arm
    "v_mov_b32_e32 v22, 0x41000000",
    "s_mov_b64 exec, s[60:61]",  # join
    "v_add_f32_e32 v26, v22, v23",
    *outputs("v22", "v23", "v26", "1.0"),
]


def if_else_reference(p):
    c = f32(p.k[0]) < p.R
    return [4.0 if c else 8.0, 3.0 if c else 2.0, 7.0 if c else 10.0, 1.0]


IF_ELSE_BUGS = [
    (0, lambda p: 8.0),  # masked write ignored: the else-arm write reaches the then lanes
    (1, lambda p: 3.0),  # masked write ignored: the then-arm write reaches the else lanes
    (0, lambda p: 4.0 if f32(p.k[0]) < p.R else 1.0),  # saveexec saved the new EXEC: the else arm runs no lane
    (0, lambda p: 8.0 if f32(p.k[0]) < p.R else 4.0),  # the else mask swapped (exec & ~S): then and else exchanged
]
IF_ELSE_SETS = ((0.3, 0, 0, 0), (0.7, 0, 0, 0), (-1.0, 0, 0, 0))

# --- s_mov_b64 S, exec + v_cmpx, a masked VOPC, VCC kept across v_cmpx, s_not_b64 of a masked compare ----------------
CMPX_REGION = [
    "v_mov_b32_e32 v22, 0",
    "v_mov_b32_e32 v23, 0",
    "v_cmp_gt_f32_e32 vcc_lo, s46, v12",  # p = s46 > R, before the region
    "s_mov_b64 s[62:63], exec",
    "v_cmpx_gt_f32_e64 -v13, s45",  # e = -G > s45; gfx10 v_cmpx leaves VCC alone
    "v_cndmask_b32_e64 v22, 1.0, 2.0, vcc_lo",  # in the region: p ? 2 : 1
    "v_cmp_lt_f32_e32 vcc_lo, s47, v12",  # masked: q = e && s47 < R
    "s_mov_b64 exec, s[62:63]",
    "v_cndmask_b32_e64 v23, 0, 1.0, vcc_lo",
    "s_not_b64 s[64:65], vcc",  # an inactive lane's 0 becomes 1
    "s_mov_b64 vcc, s[64:65]",
    "v_cndmask_b32_e64 v26, 0, 1.0, vcc_lo",
    *outputs("v22", "v23", "v26", "1.0"),
]


def cmpx_region_reference(p):
    e = -p.G > f32(p.k[1])
    q = e and f32(p.k[3]) < p.R
    return [(2.0 if f32(p.k[2]) > p.R else 1.0) if e else 0.0, float(q), float(not q), 1.0]


CMPX_REGION_BUGS = [
    (0, lambda p: 2.0 if f32(p.k[2]) > p.R else 1.0),  # v_cmpx not narrowing
    (0, lambda p: 2.0 if -p.G > f32(p.k[1]) else 0.0),  # v_cmpx also wrote VCC
    (1, lambda p: float(f32(p.k[3]) < p.R)),  # the compare in the region not zeroed for inactive lanes
    (2, lambda p: float(not (f32(p.k[3]) < p.R))),
]
CMPX_REGION_SETS = ((0, -0.5, 0.5, 0.2), (0, -0.2, 0.9, 0.05))

# --- a chain of integer v_cmpx narrowing further and further -----------------------------------------------------------
INT_CHAIN = [
    "v_mov_b32_e32 v22, 0",
    "s_mov_b64 s[62:63], exec",
    "v_cmpx_gt_u32_e32 s44, v20",  # a > X
    "v_add_f32_e32 v22, 1.0, v22",
    "v_cmpx_le_i32_e64 v21, s45",  # Y <= b
    "v_add_f32_e32 v22, 1.0, v22",
    "v_cmpx_ne_u16_e32 s46, v20",  # c[15:0] != X
    "v_add_f32_e32 v22, 1.0, v22",
    "v_cmpx_ge_i16_e64 v21, s47",  # Y >= sext(d[15:0])
    "v_add_f32_e32 v22, 1.0, v22",
    "s_mov_b64 exec, s[62:63]",
    "v_cvt_f32_u32_e32 v23, v21",
    *outputs("v22", "v24", "v23", "1.0"),
]


def chain_tests(p):
    a, b, c, d = p.k
    return [a > p.X, p.Y <= s32(b), (c & 0xffff) != p.X, p.Y >= s16(d)]


def chain_count(tests):
    n = 0
    for t in tests:
        if not t:
            break
        n += 1
    return float(n)


def int_chain_reference(p):
    return [chain_count(chain_tests(p)), float(p.X), float(p.Y), 1.0]


INT_CHAIN_BUGS = [
    (0, lambda p: float(sum(chain_tests(p)))),  # v_cmpx not narrowing: every test counted on its own
    (0, lambda p: 4.0),
]
INT_CHAIN_SETS = ((160, 153, 37, 0x10010), (0xfffffff0, 64, 0x10000, 0xfff0), (102, 0xffffffff, 64, 16))

# --- the ten saveexec forms: S = EXEC; EXEC = op(M, EXEC), then back to S, then to the outer save ----------------------
SAVEEXEC = {"and": lambda s, e: s and e, "or": lambda s, e: s or e, "xor": lambda s, e: s != e,
            "andn2": lambda s, e: s and not e, "orn2": lambda s, e: s or not e, "nand": lambda s, e: not (s and e),
            "nor": lambda s, e: not (s or e), "xnor": lambda s, e: s == e,
            "andn1": lambda s, e: not s and e, "orn1": lambda s, e: not s or e}
SAVEEXEC_BODY = ["v_mov_b32_e32 v22, 0", "v_mov_b32_e32 v23, 0",
                 "v_cmp_lt_f32_e32 vcc_lo, s44, v12",  # M = T1 < R
                 "s_mov_b64 s[68:69], vcc", "s_mov_b64 s[70:71], exec"]
for _op in SAVEEXEC:
    SAVEEXEC_BODY += ["v_mul_f32_e32 v22, 2.0, v22", "v_mul_f32_e32 v23, 2.0, v23",
                      "v_cmpx_lt_f32_e32 s45, v13",  # E = T2 < G
                      f"s_{_op}_saveexec_b64 s[72:73], s[68:69]",
                      "v_add_f32_e32 v22, 1.0, v22",
                      "s_mov_b64 exec, s[72:73]",  # back to E: the saved value
                      "v_add_f32_e32 v23, 1.0, v23",
                      "s_mov_b64 exec, s[70:71]"]
SAVEEXEC_BODY += outputs("v22", "v23", "1.0", "1.0")


def saveexec_masks(p):
    return f32(p.k[0]) < p.R, f32(p.k[1]) < p.G


def saveexec_reference(p):
    m, e = saveexec_masks(p)
    return [bits(op(m, e) for op in SAVEEXEC.values()), bits([e] * len(SAVEEXEC)), 1.0, 1.0]


SWAPPED = {"andn2": "andn1", "andn1": "andn2", "orn2": "orn1", "orn1": "orn2"}
SAVEEXEC_BUGS = [
    (1, lambda p: bits(op(*saveexec_masks(p)) for op in SAVEEXEC.values())),  # saveexec saved the new EXEC
    (0, lambda p: bits(SAVEEXEC[SWAPPED.get(n, n)](*saveexec_masks(p)) for n in SAVEEXEC)),  # S0 and EXEC swapped
    (0, lambda p: bits(op(saveexec_masks(p)[0], True) for op in SAVEEXEC.values())),  # EXEC read as all lanes
]
SAVEEXEC_SETS = ((0.3, 0.2, 0, 0), (0.7, 0.5, 0, 0))

# --- SOP2 mask algebra on compare masks, EXEC and the uniform mask of s_cselect_b64 ------------------------------------
MASK_OPS = {"and": lambda a, b: a and b, "or": lambda a, b: a or b, "xor": lambda a, b: a != b,
            "andn2": lambda a, b: a and not b, "orn2": lambda a, b: a or not b, "nand": lambda a, b: not (a and b),
            "nor": lambda a, b: not (a or b), "xnor": lambda a, b: a == b}
MASK_BODY = ["v_mov_b32_e32 v22, 0", "v_mov_b32_e32 v23, 0", "v_mov_b32_e32 v27, 0",
             "v_cmp_lt_f32_e32 vcc_lo, s44, v12", "s_mov_b64 s[64:65], vcc",  # A = T1 < R
             "v_cmp_lt_f32_e32 vcc_lo, s45, v13", "s_mov_b64 s[66:67], vcc",  # B = T2 < G
             "s_cmp_lt_u32 s46, s47", "s_cselect_b64 s[74:75], -1, 0"]  # U = s46 < s47, the same for every lane
for _op in MASK_OPS:
    MASK_BODY += [f"s_{_op}_b64 vcc, s[64:65], s[66:67]", "v_cndmask_b32_e64 v26, 0, 1.0, vcc_lo",
                  "v_mul_f32_e32 v22, 2.0, v22", "v_add_f32_e32 v22, v22, v26"]
MASK_EXTRA = [
    "s_and_b64 s[76:77], s[74:75], s[64:65]",  # U & A
    "s_nand_b64 s[76:77], s[66:67], s[74:75]",  # ~(B & U)
    "s_orn2_b64 s[76:77], s[74:75], s[64:65]",  # U | ~A
]
for _line in MASK_EXTRA:
    MASK_BODY += [_line, "s_mov_b64 vcc, s[76:77]", "v_cndmask_b32_e64 v26, 0, 1.0, vcc_lo",
                  "v_mul_f32_e32 v23, 2.0, v23", "v_add_f32_e32 v23, v23, v26"]
MASK_BODY += [
    "s_mov_b64 s[70:71], exec",
    "s_and_b64 exec, s[64:65], exec",  # the re-narrow form: EXEC = A
    "s_xor_b64 s[78:79], exec, s[66:67]",  # A != B, computed while narrowed (SALU is not masked)
    "s_andn2_b64 exec, s[70:71], exec",  # EXEC = ~A
    "v_add_f32_e32 v27, 2.0, v27",  # only the ~A lanes
    "s_or_b64 exec, exec, s[66:67]",  # EXEC = ~A | B
    "v_add_f32_e32 v27, 1.0, v27",
    "s_mov_b64 exec, s[70:71]",
    "s_mov_b64 vcc, s[78:79]", "v_cndmask_b32_e64 v26, 0, 1.0, vcc_lo",
    "v_mul_f32_e32 v23, 2.0, v23", "v_add_f32_e32 v23, v23, v26",
    *outputs("v22", "v23", "v27", "1.0"),
]


def mask_inputs(p):
    return f32(p.k[0]) < p.R, f32(p.k[1]) < p.G, p.k[2] < p.k[3]


def mask_reference(p):
    a, b, u = mask_inputs(p)
    return [bits(op(a, b) for op in MASK_OPS.values()),
            bits([u and a, not (b and u), u or not a, a != b]), float(2 * (not a) + (not a or b)), 1.0]


SWAPPED_OPS = {"andn2": lambda a, b: b and not a, "orn2": lambda a, b: b or not a}
MASK_BUGS = [
    (0, lambda p: bits(SWAPPED_OPS.get(n, op)(*mask_inputs(p)[:2]) for n, op in MASK_OPS.items())),  # operands swapped
    (0, lambda p: bits((not op(*mask_inputs(p)[:2])) if n in ("and", "nand") else op(*mask_inputs(p)[:2])
                       for n, op in MASK_OPS.items())),  # and and nand exchanged
    (1, lambda p: bits([mask_inputs(p)[2] and mask_inputs(p)[0], not (mask_inputs(p)[1] and mask_inputs(p)[2]),
                        mask_inputs(p)[2] or not mask_inputs(p)[0], mask_inputs(p)[1]])),  # xor read EXEC as all lanes
    (2, lambda p: 3.0),  # the masked adds ignore EXEC
]
MASK_SETS = ((0.3, 0.5, 1, 2), (0.7, 0.2, 5, 2))


# --- every v_cmpx form: one bit per compare, EXEC = the compare alone, then restored -------------------------------------
def nan_safe(op):
    def relation(a, b):
        unordered = math.isnan(a) or math.isnan(b)
        return {"f": False, "tru": True, "lt": a < b, "eq": a == b, "le": a <= b, "gt": a > b,
                "lg": a < b or a > b, "ge": a >= b, "o": not unordered, "u": unordered,
                "nge": not a >= b, "nlg": not (a < b or a > b), "ngt": not a > b, "nle": not a <= b,
                "neq": not a == b, "nlt": not a < b}[op]
    return relation


FLOAT_RELATIONS = ("f", "lt", "eq", "le", "gt", "lg", "ge", "o", "u", "nge", "nlg", "ngt", "nle", "neq", "nlt", "tru")
INT_RELATIONS = {"f": lambda a, b: False, "eq": lambda a, b: a == b, "ne": lambda a, b: a != b,
                 "lt": lambda a, b: a < b, "le": lambda a, b: a <= b, "gt": lambda a, b: a > b,
                 "ge": lambda a, b: a >= b, "t": lambda a, b: True}
INT16_RELATIONS = {k: v for k, v in INT_RELATIONS.items() if k not in ("f", "t")}
# Class bits: 0x40 is +0 (X = 0), 0x100 a positive normal, 0x240 +0 or +inf.
CLASS = lambda value, mask: bool(mask & (0x40 if value == 0 else 0x100))


def table_entries():
    """(v_cmpx text, predicate(pixel)). The VOPC form puts the constant first (an SGPR may only be src0), the VOP3
    form the pixel's value first; constants: s44 a float, s45 a binary16 word, s46 a 32-bit and s47 a 16-bit word."""
    entries = []
    for op in FLOAT_RELATIONS:
        rel = nan_safe(op)
        entries.append((f"v_cmpx_{op}_f32_e32 s44, v24", lambda p, rel=rel: rel(f32(p.k[0]), float(p.X))))
        entries.append((f"v_cmpx_{op}_f32_e64 v24, s44", lambda p, rel=rel: rel(float(p.X), f32(p.k[0]))))
    for op in FLOAT_RELATIONS:
        rel = nan_safe(op)
        entries.append((f"v_cmpx_{op}_f16_e32 s45, v25", lambda p, rel=rel: rel(f16(p.k[1]), float(p.X))))
        entries.append((f"v_cmpx_{op}_f16_e64 v25, s45", lambda p, rel=rel: rel(float(p.X), f16(p.k[1]))))
    for kind, conv in (("i32", s32), ("u32", lambda w: w & 0xffffffff)):
        for op, rel in INT_RELATIONS.items():
            entries.append((f"v_cmpx_{op}_{kind}_e32 s46, v20", lambda p, rel=rel, conv=conv: rel(conv(p.k[2]), p.X)))
            entries.append((f"v_cmpx_{op}_{kind}_e64 v20, s46", lambda p, rel=rel, conv=conv: rel(p.X, conv(p.k[2]))))
    for kind, conv in (("i16", s16), ("u16", lambda w: w & 0xffff)):
        for op, rel in INT16_RELATIONS.items():
            entries.append((f"v_cmpx_{op}_{kind}_e32 s47, v20", lambda p, rel=rel, conv=conv: rel(conv(p.k[3]), p.X)))
            entries.append((f"v_cmpx_{op}_{kind}_e64 v20, s47", lambda p, rel=rel, conv=conv: rel(p.X, conv(p.k[3]))))
    entries += [("v_cmpx_class_f32_e32 v24, v28", lambda p: CLASS(p.X, 0x40)),
                ("v_cmpx_class_f32_e64 v24, 0x100", lambda p: CLASS(p.X, 0x100)),
                ("v_cmpx_class_f16_e32 v25, v28", lambda p: CLASS(p.X, 0x40)),
                ("v_cmpx_class_f16_e64 v25, 0x240", lambda p: CLASS(p.X, 0x240))]
    return entries


CHANNEL_BITS = 11  # 2^11 - 1 is exact in binary16


def table_programs():
    """The table split into programs of four channels of at most 11 compares each."""
    entries = table_entries()
    chunks = [entries[n:n + CHANNEL_BITS] for n in range(0, len(entries), CHANNEL_BITS)]
    programs = []
    for start in range(0, len(chunks), 4):
        group = chunks[start:start + 4]
        body = [f"v_mov_b32_e32 v{30 + c}, 0" for c in range(4)] + ["v_mov_b32_e32 v28, 0x40",
                                                                    "s_mov_b64 s[62:63], exec"]
        for c, chunk in enumerate(group):
            for line, _ in chunk:
                body += [f"v_mul_f32_e32 v{30 + c}, 2.0, v{30 + c}", line, f"v_add_f32_e32 v{30 + c}, 1.0, v{30 + c}",
                         "s_mov_b64 exec, s[62:63]"]
        body += outputs(*(f"v{30 + c}" for c in range(4)))

        def reference(p, group=group):
            return [bits(pred(p) for _, pred in chunk) if c < len(group) else 0.0 for c, chunk in
                    enumerate(group + [[]] * (4 - len(group)))]

        def all_ones(p, n=len(group[0])):
            return float(2 ** n - 1)

        def inverted(p, chunk=group[-1]):
            return bits(not pred(p) for _, pred in chunk)

        bugs = [(0, all_ones), (len(group) - 1, inverted)]  # v_cmpx not narrowing; every relation inverted
        programs.append((f"cf2_table{start // 4}", body, reference, TABLE_SETS, bugs))
    return programs


TABLE_SETS = ((64.0, 0x5400, 64, 0x25), (NAN, 0x7e00, 0xfffffff0, 0xffc0), (100.5, 0x5a50, 0xa0, 0x10099))


def programs():
    return [("cf2_if_else", IF_ELSE, if_else_reference, IF_ELSE_SETS, IF_ELSE_BUGS),
            ("cf2_cmpx_region", CMPX_REGION, cmpx_region_reference, CMPX_REGION_SETS, CMPX_REGION_BUGS),
            ("cf2_int_chain", PREP + INT_CHAIN, int_chain_reference, INT_CHAIN_SETS, INT_CHAIN_BUGS),
            ("cf2_saveexec", SAVEEXEC_BODY, saveexec_reference, SAVEEXEC_SETS, SAVEEXEC_BUGS),
            ("cf2_mask", MASK_BODY, mask_reference, MASK_SETS, MASK_BUGS),
            *((name, PREP + body, reference, sets, bugs) for name, body, reference, sets, bugs in table_programs())]


def pixels(constants):
    words = tuple(word(c) for c in constants)
    return [Pixel(x, y, words) for y in range(8) for x in range(8)]


def case_bytes(constants, reference):
    case = bytearray(256)
    struct.pack_into("<4I", case, 12, *(word(c) for c in constants))
    for p in pixels(constants):
        case.extend(struct.pack("<4f", *reference(p)))
    return bytes(case)


def with_bug(reference, channel, wrong):
    def buggy(p):
        values = list(reference(p))
        values[channel] = wrong(p)
        return values
    return buggy


def check_references():
    """Offline: every result is exact in binary16, and every wrong reference differs from the reference in at least
    one pixel of one constant set (so its draw must report a mismatch)."""
    for name, body, reference, sets, bugs in programs():
        for constants in sets:
            for p in pixels(constants):
                for value in reference(p):
                    assert value == struct.unpack("<e", struct.pack("<e", value))[0], (name, value)
        for n, (channel, wrong) in enumerate(bugs):
            buggy = with_bug(reference, channel, wrong)
            assert any(buggy(p) != reference(p) for c in sets for p in pixels(c)), (name, n)


def check_cf2_exec_draws(directory, compiler, renderer, backend):
    source, shader, case = directory / "fixture.hlsl", directory / "fixture.cso", directory / "cf2_exec.case"
    for name, body, reference, sets, bugs in programs():
        source.write_text(translate(with_constants(body)), encoding="ascii")
        subprocess.run([compiler, "-Gis", "-T", "ps_6_0", "-E", "main", "-Fo", shader, source], check=True)
        draw = [renderer, backend, "--check-pixel-case", shader, case]
        for constants in sets:
            case.write_bytes(case_bytes(constants, reference))
            subprocess.run(draw, check=True)
        for n, (channel, wrong) in enumerate(bugs):
            buggy = with_bug(reference, channel, wrong)
            caught = False
            for constants in sets:
                if all(buggy(p) == reference(p) for p in pixels(constants)):
                    continue
                case.write_bytes(case_bytes(constants, buggy))
                result = subprocess.run(draw, capture_output=True, text=True)
                if result.returncode == 1 and "pixel_mismatch" in result.stderr:
                    caught = True
                    break
            if not caught:
                raise AssertionError(f"{name}: wrong reference {n} accepted")
    return 0


# --- controls -----------------------------------------------------------------------------------------------------------
def lane(ex="true"):
    st = Lowering({"s44": ("uint", "params[0].w"), "s45": ("uint", "params[1].x")},
                  {"v0": "bary_i", "v1": "bary_j", "v12": "sample4.x", "v13": "sample4.y"},
                  [], {0: "tex"}, [1, 2, 3, 4], 64, {})
    st.ex = ex
    return st


def step(st, i, line):
    ex, before = st.ex, dict(st.vector)
    dispatch(st, i, line)
    if ex != "true":
        masked_writes(st, i, ex, before)


def refused(text, st, i, line):
    try:
        step(st, i, line)
    except ValueError as error:
        assert text in str(error), (line, text, str(error))
        return
    raise AssertionError(f"{line!r} accepted")


def rejected(text, body):
    try:
        translate(with_constants(body))
    except ValueError as error:
        assert text in str(error), (text, str(error))
        return
    raise AssertionError(f"program accepted: {body}")


def check_cf2_exec_controls():
    check_references()
    for name, body, *_ in programs():
        text = translate(with_constants(body))
        assert "bool ex" in text and "if (" not in text.split("float4 main", 1)[1], name

    # v_cmpx: EXEC &= compare; no lane-mask register is written.
    st = lane()
    st.scalar["vcc"] = ("condition", "cmp1", 0, 1)
    step(st, 2, "v_cmpx_lt_f32_e32 s44, v12")
    assert st.lines == ["    bool cmp2 = asfloat(params[0].w) < sample4.x;", "    bool ex2 = cmp2;"], st.lines
    assert st.ex == "ex2" and st.scalar["vcc"] == ("condition", "cmp1", 0, 1)
    step(st, 3, "v_cmpx_class_f16_e64 v13, 0x240")
    assert st.lines[-1] == "    bool ex3 = ex2 && cmp3;" and st.ex == "ex3"
    # A compare while the lane may be inactive writes ex && cmp; a VALU write is masked.
    step(st, 4, "v_cmp_gt_f32_e32 vcc_lo, v12, v13")
    assert st.lines[-1] == "    bool cmp4 = ex3 && (sample4.x > sample4.y);", st.lines[-1]
    step(st, 5, "v_cndmask_b32_e64 v12, 0, 1.0, vcc_lo")
    assert st.lines[-1] == "    uint exw5_12 = ex3 ? selw5 : asuint(sample4.x);", st.lines[-1]
    # saveexec: S = the old EXEC, EXEC = op(S0, EXEC); andn1 and andn2 differ in which operand is inverted.
    for op, expected in (("and", "(cmp4 && ex3)"), ("andn2", "(cmp4 && !ex3)"), ("andn1", "(!cmp4 && ex3)"),
                         ("orn2", "(cmp4 || !ex3)"), ("orn1", "(!cmp4 || ex3)"), ("nand", "!(cmp4 && ex3)"),
                         ("nor", "!(cmp4 || ex3)"), ("xor", "(cmp4 != ex3)"), ("xnor", "!(cmp4 != ex3)"),
                         ("or", "(cmp4 || ex3)")):
        st2 = lane("ex3")
        st2.scalar["vcc"] = ("condition", "cmp4", 0, 1)
        step(st2, 6, f"s_{op}_saveexec_b64 s[60:61], vcc")
        assert st2.lines == [f"    bool ex6 = {expected};"] and st2.ex == "ex6", (op, st2.lines)
        assert st2.scalar["s60"] == ("condition", "ex3", 0, 2) and st2.scalar["s61"] == ("condition", "ex3", 1, 2)
        assert st2.scc is None  # SCC of a mask operation is lane local: not tracked
    st2 = lane("ex3")
    st2.scalar.update({"s60": ("condition", "cmp4", 0, 2), "s61": ("condition", "cmp4", 1, 2)})
    step(st2, 7, "s_and_saveexec_b64 s[60:61], s[60:61]")  # the source is read before the save
    assert st2.lines == ["    bool ex7 = (cmp4 && ex3);"] and st2.scalar["s60"] == ("condition", "ex3", 0, 2)
    # SOP2 on lane masks; the data form stays for data. A mask and data together are refused.
    st = lane()
    st.scalar.update({"s60": ("condition", "cmp1", 0, 2), "s61": ("condition", "cmp1", 1, 2),
                      "s46": ("uint", "params[1].y"), "s47": ("uint", "params[1].z"), "vcc": ("condition", "cmp2", 0, 1)})
    step(st, 8, "s_nand_b64 s[62:63], s[60:61], vcc")
    assert st.lines == ["    bool lm8 = !(cmp1 && cmp2);"] and st.scalar["s63"] == ("condition", "lm8", 1, 2)
    step(st, 9, "s_and_b64 s[64:65], s[44:45], s[46:47]")
    assert st.lines[-1].startswith("    uint2 salu9 = ") and st.scc == "((salu9.x | salu9.y) != 0u)"
    refused("Unsupported execution mask", st, 10, "s_and_b64 s[64:65], s[60:61], s[46:47]")
    st.scc = "(params[0].w < 3u)"
    step(st, 11, "s_cselect_b64 s[66:67], -1, 0")  # data words, and the uniform mask
    assert st.lines[-1] == "    uint2 salu11 = (params[0].w < 3u) ? uint2(4294967295u, 4294967295u) : uint2(0u, 0u);"
    assert st.scalar["s66"] == ("uint", "salu11.x")
    step(st, 12, "s_andn2_b64 vcc, s[66:67], s[60:61]")
    assert st.lines[-1] == "    bool lm12 = ((salu11.x != 0u) && !cmp1);" and st.scalar["vcc"] == ("condition", "lm12", 0, 1)
    step(st, 13, "s_and_b64 s[68:69], s[66:67], s[44:45]")  # uniform mask and data: the data form
    assert st.lines[-1].startswith("    uint2 salu13 = ")
    # Lane-local SCC is neither data nor a branch condition.
    step(st, 14, "s_or_b64 s[70:71], s[60:61], vcc")
    assert st.scc is None
    refused("Select requires a tracked SCC", st, 14, "s_cselect_b32 s50, s44, s45")
    refused("Select requires a tracked SCC", st, 14, "s_cselect_b64 s[70:71], -1, 0")
    # EXEC writes that could enable a lane that was never active (whole-wave mode) are refused.
    for line in ("s_mov_b64 exec, -1", "s_or_saveexec_b64 s[70:71], -1", "s_xor_b64 exec, exec, -1",
                 "s_nand_saveexec_b64 s[70:71], 0", "s_andn2_b64 exec, -1, exec", "s_orn2_b64 exec, exec, 0"):
        refused("whole-wave mode", lane("ex3"), 15, line)
    for line in ("s_and_saveexec_b64 s[70:71], -1", "s_mov_b64 exec, 0", "s_and_b64 exec, exec, -1",
                 "s_andn2_b64 exec, exec, 0"):
        st = lane("ex3")
        step(st, 15, line)
    # Restoring a saved EXEC brings back whole-quad mode as it was at the save.
    st = lane()
    step(st, 16, "s_mov_b64 s[50:51], exec")
    st.wqm = True
    step(st, 17, "s_mov_b64 s[52:53], exec")
    step(st, 18, "v_cmpx_lt_f32_e32 s44, v12")
    step(st, 19, "s_mov_b64 exec, s[52:53]")
    assert (st.ex, st.wqm) == ("true", True)
    step(st, 20, "v_cmpx_lt_f32_e32 s44, v12")
    step(st, 21, "s_mov_b64 exec, s[50:51]")
    assert (st.ex, st.wqm) == ("true", False)
    # The SDWA and DPP compares are not masked yet; branches on EXEC are CF-2c.
    refused("Invalid comparison", lane("ex3"), 22, "v_cmp_lt_f32_sdwa vcc_lo, v12, v13 src0_sel:DWORD src1_sel:DWORD")

    # Through lower(): a narrowed EXEC that is not restored reaches the export, which since CF-2d discards the lanes
    # that are off (family cf2_discard); a pair packed under the narrowed EXEC and exported after the restore is refused.
    for body in ([line for line in IF_ELSE if line != "s_mov_b64 exec, s[60:61]"],
                 [line for line in CMPX_REGION if line != "s_mov_b64 exec, s[62:63]"], ["v_cmpx_lt_f32_e32 s44, v12"]):
        assert ") discard;" in translate(with_constants(body))
    program = with_constants(["s_mov_b64 s[62:63], exec", "v_cmpx_lt_f32_e32 s44, v12"])
    pack = program.index("v_cvt_pkrtz_f16_f32_e32 v17, v14, v15") + 1
    program[pack:pack] = ["s_mov_b64 exec, s[62:63]"]
    must_reject(translate, program)
    # s_cbranch_exec* are lowered since CF-2c (family cf2_skip); a skip over the else form, which restores a mask
    # saved outside the skipped region, is refused.
    for branch in ("s_cbranch_execz", "s_cbranch_execnz"):
        rejected("EXEC re-enabled inside a skipped region", IF_ELSE[:5] + [f"{branch} BB0_2"] + IF_ELSE[5:9] + ["BB0_2:"] + IF_ELSE[9:])
    # Loads and interpolation while the lane may be inactive stay refused.
    rejected("Invalid buffer load", ["s_mov_b64 s[62:63], exec", "v_cmpx_lt_f32_e32 s44, v12",
                                     "buffer_load_dword v20, v12, s[28:31], 0 offen", "s_mov_b64 exec, s[62:63]"])
    must_reject(translate, with_constants(["s_mov_b64 s[62:63], exec", "v_cmpx_lt_f32_e32 s44, v12",
                                           "s_cselect_b32 s50, s44, s45", "s_mov_b64 exec, s[62:63]"]))
    # A compare destination of v_cmpx is not a gfx10 form.
    rejected("Unsupported", ["v_cmpx_lt_f32_e64 s[60:61], v12, v13"])


def controls(directory):
    check_cf2_exec_controls()


def binary_fixtures():
    """(program, translator) pairs that `pixel_aot_check.py binary` assembles, disassembles and lowers (wave32)."""
    return [(with_constants(body), translate) for _, body, *_ in programs()]


draw = check_cf2_exec_draws
