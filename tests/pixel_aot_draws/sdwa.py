"""Draw family `sdwa`: pixel_aot_check.py draw --family sdwa."""
import math
import struct
import subprocess

from .common import half_rtz, half_value, must_reject, sdwa_readback, translate, with_constants


# SDWA moves and half widening. In SDWA_PRESERVE_BODY each move writes a 16-bit field into WORD_0 of a register
# holding 1.0 and keeps its high half, so the word is 1 + f * 2^-23; (v - 1) * 2^23 is split into the low and high
# bytes of f. Channels 0 and 1 read WORD_1 of S0; channels 2 and 3 read BYTE_2 of S1 sign-extended to 16 bits.
# SDWA_PAD_BODY writes BYTE_0 of S0 to BYTE_3 and WORD_0 of S2 to WORD_1 with zero padding, and widens each half
# of S1, the low one through -|x|. Each constant set has wrong references (channel, value) for one selection.
SDWA_PRESERVE_BODY = [
    "v_mov_b32_e32 v12, 1.0",
    "v_mov_b32_sdwa v12, s44 dst_sel:WORD_0 dst_unused:UNUSED_PRESERVE src0_sel:WORD_1",
    *sdwa_readback("v12", "v13"),
    "v_mov_b32_e32 v14, 1.0",
    "v_mov_b32_sdwa v14, sext(s45) dst_sel:WORD_0 dst_unused:UNUSED_PRESERVE src0_sel:BYTE_2",
    *sdwa_readback("v14", "v15"),
]
SDWA_PAD_BODY = [
    "v_mov_b32_sdwa v12, s44 dst_sel:BYTE_3 dst_unused:UNUSED_PAD src0_sel:BYTE_0",
    "v_cvt_f32_f16_sdwa v13, s45 dst_sel:DWORD dst_unused:UNUSED_PAD src0_sel:WORD_1",
    "v_cvt_f32_f16_sdwa v14, -|s45| dst_sel:DWORD dst_unused:UNUSED_PAD src0_sel:WORD_0",
    "v_mov_b32_sdwa v15, s46 dst_sel:WORD_1 dst_unused:UNUSED_PAD src0_sel:WORD_0",
]
SDWA_SETS = (
    # A wrong WORD_0 selection; a zero-extended byte.
    (SDWA_PRESERVE_BODY, (0x12345678, 0x00c00000, 0), [52.0, 18.0, 192.0, 255.0], ((0, 120.0), (1, 86.0), (3, 0.0))),
    (SDWA_PRESERVE_BODY, (0xfedc0000, 0x007f0000, 0), [220.0, 254.0, 127.0, 0.0], ((0, 0.0), (3, 255.0))),
    # BYTE_1 instead of BYTE_0; the other half of S1 in channels 1 and 2; WORD_1 instead of WORD_0 of S2.
    (SDWA_PAD_BODY, (0x0000c340, 0xc5003c00, 0x3f80c0a0), [2.0, -5.0, -1.0, -5.0], ((0, -128.0), (1, 1.0), (2, -5.0), (3, 1.0))),
    (SDWA_PAD_BODY, (0x000047c0, 0x38004900, 0x00004120), [-2.0, 0.5, -10.0, 10.0], ((0, 32768.0), (1, 10.0), (2, -0.5), (3, 0.0))),
)


def sdwa_reference(body, words):
    """Selections and widening on the integer words, independent of the lowering."""
    x, y, z = words
    if body is SDWA_PRESERVE_BODY:
        first = x >> 16
        byte = (y >> 16) & 0xff
        second = (byte - 0x100 if byte & 0x80 else byte) & 0xffff
        return [float(first & 0xff), float(first >> 8), float(second & 0xff), float(second >> 8)]
    as_float = lambda w: struct.unpack("<f", struct.pack("<I", w))[0]
    return [as_float((x & 0xff) << 24), half_value(y >> 16), -abs(half_value(y)), as_float((z & 0xffff) << 16)]


def check_sdwa_draw(directory, compiler, renderer, backend):
    check_sdwa_word_draws(directory, compiler, renderer, backend)
    check_sdwa_pack_draw(directory, compiler, renderer, backend)
    for name, body in (("sdwa_preserve", SDWA_PRESERVE_BODY), ("sdwa_pad", SDWA_PAD_BODY)):
        source = directory / f"{name}.hlsl"
        shader = directory / f"{name}.cso"
        source.write_text(translate(with_constants(body)), encoding="ascii")
        subprocess.run([compiler, "-Gis", "-T", "ps_6_0", "-E", "main", "-Fo", shader, source], check=True)
    case = directory / "sdwa.case"
    for body, words, expected, wrongs in SDWA_SETS:
        assert sdwa_reference(body, words) == expected, (words, expected)
        shader = directory / ("sdwa_preserve.cso" if body is SDWA_PRESERVE_BODY else "sdwa_pad.cso")
        constants = bytearray(256)
        struct.pack_into("<3I", constants, 12, *words)
        for x in (*expected, *(value for _, value in wrongs)):
            assert half_rtz(x) == x, x
        draw = [renderer, backend, "--check-pixel-case", shader, case]
        case.write_bytes(constants + struct.pack("<4f", *expected) * 64)
        subprocess.run(draw, check=True)
        for channel, value in wrongs:
            assert value != expected[channel]
            wrong_values = list(expected)
            wrong_values[channel] = value
            case.write_bytes(constants + struct.pack("<4f", *wrong_values) * 64)
            result = subprocess.run(draw, capture_output=True, text=True)
            if result.returncode != 1 or "pixel_mismatch" not in result.stderr:
                raise AssertionError(f"A wrong SDWA selection escaped detection for {words} in channel {channel}")


# Table-driven SDWA forms (integer, binary16, ubyte, narrowing). Each row is one instruction with its
# selections; the 32-bit result register is read back as four bytes (v_cvt_f32_ubyte0..3, each exact in the half
# export), so a draw compares every bit of the result including the bits the destination keeps or pads. The model
# below is an independent integer implementation of the selections. For each row the wrong references (a neighbouring
# source selector, sign- instead of zero-extension or the reverse, the other unused mode, a neighbouring destination
# field) are computed with the same model; every wrong reference that differs from the right word must fail the draw.
M32 = 0xffffffff
SELECTORS = {"BYTE_0": (0, 8), "BYTE_1": (8, 8), "BYTE_2": (16, 8), "BYTE_3": (24, 8), "WORD_0": (0, 16),
             "WORD_1": (16, 16), "DWORD": (0, 32)}


def model_field(word, sel, sext):
    offset, width = SELECTORS[sel]
    value = (word >> offset) & ((1 << width) - 1)
    if sext and width < 32 and value >> (width - 1):
        value -= 1 << width
    return value & M32


def model_place(result, sel, unused, old):
    offset, width = SELECTORS[sel]
    if width == 32:
        return result & M32
    mask = (1 << width) - 1
    field = (result & mask) << offset
    return field if unused == "UNUSED_PAD" else ((old & ~(mask << offset)) | field) & M32


def signed32(x):
    return x - (1 << 32) if x >> 31 else x


def signed24(x):
    return ((x & 0xffffff) ^ 0x800000) - 0x800000


def float_bits(x):
    return struct.unpack("<I", struct.pack("<f", x))[0]


def half_bits(x):
    try:
        return struct.unpack("<H", struct.pack("<e", x))[0]
    except OverflowError:
        return 0xfc00 if x < 0 else 0x7c00


def half_of(bits):
    return struct.unpack("<e", struct.pack("<H", bits & 0xffff))[0]


INT_MODEL = {
    "add_nc_u32": lambda a, b: a + b, "sub_nc_u32": lambda a, b: a - b, "subrev_nc_u32": lambda a, b: b - a,
    "mul_u32_u24": lambda a, b: (a & 0xffffff) * (b & 0xffffff),
    "mul_i32_i24": lambda a, b: signed24(a) * signed24(b),
    "mul_hi_u32_u24": lambda a, b: ((a & 0xffffff) * (b & 0xffffff)) >> 32,
    "mul_hi_i32_i24": lambda a, b: (signed24(a) * signed24(b)) >> 32,
    "and_b32": lambda a, b: a & b, "or_b32": lambda a, b: a | b, "xor_b32": lambda a, b: a ^ b,
    "xnor_b32": lambda a, b: ~(a ^ b),
    "lshlrev_b32": lambda a, b: b << (a & 31), "lshrrev_b32": lambda a, b: b >> (a & 31),
    "ashrrev_i32": lambda a, b: signed32(b) >> (a & 31),
}
UNARY_MODEL = {"not_b32": lambda a: ~a, "bfrev_b32": lambda a: int(f"{a & M32:032b}"[::-1], 2),
               **{f"cvt_f32_ubyte{n}": (lambda n: lambda a: float_bits(float((a >> 8 * n) & 255)))(n) for n in range(4)}}
F16_MODEL = {
    "add_f16": lambda a, b: half_bits(half_of(a) + half_of(b)), "subrev_f16": lambda a, b: half_bits(half_of(b) - half_of(a)),
    "mul_f16": lambda a, b: half_bits(half_of(a) * half_of(b)), "min_f16": lambda a, b: half_bits(min(half_of(a), half_of(b))),
    "floor_f16": lambda a: half_bits(float(math.floor(half_of(a)))),
    "trunc_f16": lambda a: half_bits(math.copysign(float(math.trunc(half_of(a))), half_of(a))),
    "fract_f16": lambda a: half_bits(half_of(a) - math.floor(half_of(a))),
    # The exponent operand is a signed 16-bit integer.
    "ldexp_f16": lambda a, b: half_bits(half_of(a) * 2.0 ** (((b & 0xffff) ^ 0x8000) - 0x8000)),
}
MODIFIED = {"": lambda bits: bits, "neg": lambda bits: bits ^ 0x8000, "abs": lambda bits: bits & 0x7fff,
            "negabs": lambda bits: (bits & 0x7fff) ^ 0x8000}


def Z(sel, mod=""):
    return (sel, False, mod)


def S(sel):
    return (sel, True, "")


# (instruction, dst_sel, dst_unused, src0, src1, (a, b, initial destination word, unused), kind)
# a and b are the words of v18 and v19, the initial word is the destination's earlier value (UNUSED_PRESERVE keeps
# its other bits). kind is "int", "f16" or "narrow".
A, B, INIT = 0xf1d28a93, 0x9be4a7c5, 0x3f80c0de
WORDS = None  # chosen by complete_rows: the best of fixed pseudo-random words for which every selection has a wrong reference

SHIFTS = ("lshlrev_b32", "lshrrev_b32", "ashrrev_i32")
INT_ROWS = []
for _op in INT_MODEL:
    # A shift count is the low five bits of its field, so only the shifted source shows an extension.
    first, second = (Z("BYTE_1"), S("BYTE_0")) if _op in SHIFTS else (S("WORD_1"), S("WORD_0"))
    INT_ROWS += [
        (_op, "DWORD", "UNUSED_PAD", first, second, WORDS, "int"),
        (_op, "BYTE_2", "UNUSED_PRESERVE", Z("BYTE_3"), S("BYTE_1"), WORDS, "int"),
    ]
INT_ROWS += [
    ("or_b32", "DWORD", "UNUSED_PAD", S("WORD_1"), Z("BYTE_0"), WORDS, "int"),
    ("add_nc_u32", "WORD_1", "UNUSED_PAD", Z("BYTE_1"), S("BYTE_2"), WORDS, "int"),
    ("sub_nc_u32", "WORD_0", "UNUSED_PRESERVE", S("BYTE_1"), Z("WORD_1"), WORDS, "int"),
    ("ashrrev_i32", "BYTE_0", "UNUSED_PAD", Z("BYTE_1"), S("BYTE_2"), WORDS, "int"),
    ("lshrrev_b32", "BYTE_3", "UNUSED_PRESERVE", Z("BYTE_0"), S("BYTE_3"), WORDS, "int"),
    ("mul_hi_i32_i24", "WORD_1", "UNUSED_PAD", Z("WORD_0"), S("BYTE_2"), WORDS, "int"),
    ("not_b32", "DWORD", "UNUSED_PAD", S("BYTE_2"), None, WORDS, "int"),
    ("not_b32", "WORD_1", "UNUSED_PRESERVE", Z("WORD_0"), None, WORDS, "int"),
    ("bfrev_b32", "DWORD", "UNUSED_PAD", S("BYTE_2"), None, WORDS, "int"),
    ("bfrev_b32", "BYTE_3", "UNUSED_PRESERVE", S("WORD_1"), None, WORDS, "int"),
    # The byte of the zero- or sign-extended field that cvt_f32_ubyteN converts is selected by N and the selector.
    ("cvt_f32_ubyte0", "DWORD", "UNUSED_PAD", Z("BYTE_2"), None, WORDS, "int"),
    ("cvt_f32_ubyte0", "DWORD", "UNUSED_PAD", S("WORD_1"), None, WORDS, "int"),
    ("cvt_f32_ubyte1", "DWORD", "UNUSED_PAD", S("BYTE_0"), None, WORDS, "int"),
    ("cvt_f32_ubyte1", "DWORD", "UNUSED_PAD", Z("WORD_1"), None, WORDS, "int"),
    ("cvt_f32_ubyte2", "DWORD", "UNUSED_PAD", S("WORD_0"), None, WORDS, "int"),
    ("cvt_f32_ubyte2", "DWORD", "UNUSED_PAD", S("BYTE_3"), None, WORDS, "int"),
    ("cvt_f32_ubyte3", "DWORD", "UNUSED_PAD", S("BYTE_1"), None, WORDS, "int"),
    ("cvt_f32_ubyte3", "DWORD", "UNUSED_PAD", S("BYTE_2"), None, WORDS, "int"),
]
# Binary16 halves: 1.0 0x3c00, 2.0 0x4000, -3.0 0xc200, 0.5 0x3800, 1.5 0x3e00, -2.5 0xc100, 4.0 0x4400, 0.25 0x3400.
H = lambda hi, lo: (hi << 16) | lo
F16_ROWS = [
    ("add_f16", "WORD_0", "UNUSED_PRESERVE", Z("WORD_1"), Z("WORD_0"), None, "f16"),
    ("add_f16", "WORD_1", "UNUSED_PAD", Z("WORD_0", "negabs"), Z("WORD_1", "neg"), None, "f16"),
    ("subrev_f16", "WORD_1", "UNUSED_PRESERVE", Z("WORD_1"), Z("WORD_0"), None, "f16"),
    ("subrev_f16", "BYTE_0", "UNUSED_PAD", Z("WORD_0", "abs"), Z("WORD_1"), None, "f16"),
    ("mul_f16", "WORD_0", "UNUSED_PAD", Z("WORD_1"), Z("WORD_0"), None, "f16"),
    ("mul_f16", "WORD_1", "UNUSED_PRESERVE", Z("WORD_0", "negabs"), Z("WORD_1"), None, "f16"),
    ("min_f16", "WORD_0", "UNUSED_PRESERVE", Z("WORD_1"), Z("WORD_0"), None, "f16"),
    ("min_f16", "WORD_1", "UNUSED_PAD", Z("WORD_0"), Z("WORD_1", "neg"), None, "f16"),
    ("floor_f16", "WORD_0", "UNUSED_PRESERVE", Z("WORD_1"), None, None, "f16"),
    ("floor_f16", "WORD_1", "UNUSED_PAD", Z("WORD_0", "neg"), None, None, "f16"),
    ("trunc_f16", "WORD_0", "UNUSED_PAD", Z("WORD_1"), None, None, "f16"),
    ("trunc_f16", "WORD_1", "UNUSED_PRESERVE", Z("WORD_0", "abs"), None, None, "f16"),
    ("fract_f16", "WORD_0", "UNUSED_PRESERVE", Z("WORD_1"), None, None, "f16"),
    ("fract_f16", "WORD_1", "UNUSED_PAD", Z("WORD_0", "negabs"), None, None, "f16"),
    # The exponent is a signed integer: sext of byte 0xfe is -2, zero-extended it is 254.
    ("ldexp_f16", "WORD_0", "UNUSED_PRESERVE", Z("WORD_1"), S("BYTE_2"), None, "f16"),
    ("ldexp_f16", "WORD_1", "UNUSED_PAD", Z("WORD_0"), S("BYTE_1"), None, "f16"),
    ("ldexp_f16", "BYTE_1", "UNUSED_PRESERVE", Z("WORD_1"), Z("BYTE_0"), None, "f16"),
    ("cvt_f16_f32", "WORD_1", "UNUSED_PRESERVE", ("DWORD", False, "neg"), None, (float_bits(1.5), 0, INIT, 0), "narrow"),
    ("cvt_f16_f32", "WORD_0", "UNUSED_PAD", ("DWORD", False, ""), None, (float_bits(-2.5), 0, INIT, 0), "narrow"),
    ("cvt_f16_f32", "BYTE_1", "UNUSED_PRESERVE", ("DWORD", False, ""), None, (float_bits(0.6), 0, INIT, 0), "narrow"),
]




def row_expected(row, src0=None, src1=None, dst=None):
    """The result word the model gives for a row, with any selection replaced for a wrong reference."""
    op, dst_sel, unused, s0, s1, (a, b, init, _), kind = row
    s0, s1 = src0 or s0, src1 or s1
    dst_sel, unused = dst or (dst_sel, unused)
    modified = lambda src, word: MODIFIED[src[2]](model_field(word, src[0], src[1]) & 0xffff)
    if kind == "narrow":
        value = struct.unpack("<f", struct.pack("<I", a))[0]
        result = half_bits(-value if s0[2] == "neg" else value)
    elif kind == "f16":
        if op in F16_MODEL and F16_MODEL[op].__code__.co_argcount == 1:
            result = F16_MODEL[op](modified(s0, a))
        elif op == "ldexp_f16":
            result = F16_MODEL[op](modified(s0, a), model_field(b, s1[0], s1[1]))
        else:
            result = F16_MODEL[op](modified(s0, a), modified(s1, b))
    elif op in UNARY_MODEL:
        result = UNARY_MODEL[op](model_field(a, s0[0], s0[1]))
    else:
        result = INT_MODEL[op](model_field(a, s0[0], s0[1]), model_field(b, s1[0], s1[1]))
    return model_place(result, dst_sel, unused, init)


def wrong_selections(src):
    """(label, wrong source) pairs: the neighbouring selector, and the other extension of the same field."""
    sel, sext, mod = src
    if sel == "DWORD":
        return []
    other = f"WORD_{1 - int(sel[-1])}" if sel.startswith("WORD") else f"BYTE_{(int(sel[-1]) + 1) % 4}"
    return [("selector", (other, sext, mod)), ("extension", (sel, not sext, mod))]


def row_wrongs(row):
    """Wrong references of a row as (label, result word) pairs, each from the model with one selection wrong."""
    op, dst_sel, unused, s0, s1, words, kind = row
    wrongs = []
    for index, src in enumerate((s0, s1)):
        if src is None:
            continue
        # sext is not a modifier of binary16 float sources; ldexp's exponent is the one integer source there.
        float_source = kind in ("f16", "narrow") and not (op == "ldexp_f16" and index == 1)
        for label, wrong in wrong_selections(src):
            if not (float_source and label == "extension"):
                wrongs.append((f"source{index} {label}", row_expected(row, **{f"src{index}": wrong})))
        if src[2]:
            flipped = {"neg": "", "abs": "negabs", "negabs": "abs"}[src[2]]
            wrongs.append((f"source{index} modifier", row_expected(row, **{f"src{index}": (src[0], src[1], flipped)})))
    if dst_sel != "DWORD":
        wrongs.append(("unused", row_expected(row, dst=(dst_sel, "UNUSED_PRESERVE" if unused == "UNUSED_PAD" else "UNUSED_PAD"))))
        other = "WORD_1" if dst_sel == "WORD_0" else "WORD_0" if dst_sel.startswith("WORD") else f"BYTE_{(int(dst_sel[-1]) + 1) % 4}"
        wrongs.append(("destination field", row_expected(row, dst=(other, unused))))
    right = row_expected(row)
    return [(label, word) for label, word in wrongs if word != right]


def row_complete(row):
    """Whether the destination, and modifiers of the row each have a wrong reference that the right word
    differs from. Source selectors and extensions are checked for all the rows of an operation (op_gaps), because
    what a row shows of them depends on its operation and destination."""
    op, dst_sel, unused, s0, s1, words, kind = row
    have = {label for label, _ in row_wrongs(row)}
    need = set()
    for index, src in enumerate((s0, s1)):
        if src is not None and src[2]:
            need.add(f"source{index} modifier")
    if dst_sel != "DWORD":
        need |= {"unused", "destination field"}
    return need <= have


def op_gaps(rows):
    """For each operation, the source selections that no row of it can tell from a wrong reference. An extension is
    visible only if the whole dword is written; a shift count is the low five bits of its field, whatever its
    extension, and the low byte of cvt_f32_ubyte0 does not see one."""
    seen, gaps = {}, []
    for row in rows:
        op, dst_sel, unused, s0, s1, words, kind = row
        seen.setdefault(op, set()).update(label for label, _ in row_wrongs(row))
    for row in rows:
        op, dst_sel, unused, s0, s1, words, kind = row
        for index, src in enumerate((s0, s1)):
            if src is None or src[0] == "DWORD":
                continue
            float_source = kind in ("f16", "narrow") and not (op == "ldexp_f16" and index == 1)
            wanted = ["selector"] + ([] if float_source or (op in SHIFTS and index == 0) or op.endswith("ubyte0") else ["extension"])
            gaps += [(op, f"source{index} {label}") for label in wanted if f"source{index} {label}" not in seen[op]]
    return sorted(set(gaps))


def candidate_words(row):
    """Deterministic data for a row without words: pseudo-random dwords, or binary16 values and exponents."""
    op, kind = row[0], row[6]
    state = 0x2545f491
    if kind in ("f16", "narrow"):
        halves = (0x3c00, 0x4000, 0xc200, 0x3800, 0x3e00, 0xc100, 0x4400, 0x3400, 0x3d55, 0xc155, 0x4166, 0x3aa3)
        exponents = (0x03, 0xfd, 0xfe, 0x02, 0x05, 0xfb)
        for x in range(1500):
            state = (state * 1664525 + 1013904223) & M32
            a = H(halves[state % 12], halves[(state >> 8) % 12])
            if op == "ldexp_f16":
                b = (exponents[(state >> 16) % 6] << 24) | (exponents[(state >> 20) % 6] << 16) | (exponents[(state >> 24) % 6] << 8) | exponents[(state >> 12) % 6]
            else:
                b = H(halves[(state >> 16) % 12], halves[(state >> 20) % 12])
            yield a, b
    else:
        for x in range(1500):
            state = (state * 1664525 + 1013904223) & M32
            a = state
            state = (state * 1664525 + 1013904223) & M32
            yield a, state


def complete_rows(rows):
    chosen = []
    for row in rows:
        if row[5]:
            chosen.append(row)
            continue
        best = None
        for a, b in candidate_words(row):
            trial = (*row[:5], (a, b, INIT, 0), row[6])
            if row_complete(trial) and row_expected(trial):
                labels = len({label for label, _ in row_wrongs(trial)})
                if best is None or labels > best[0]:
                    best = (labels, trial)
        chosen.append(best[1] if best else row)
    return chosen


WORD_ROWS = complete_rows(INT_ROWS + F16_ROWS)


def row_program(row):
    op, dst_sel, unused, s0, s1, words, kind = row
    fields = f" dst_sel:{dst_sel} dst_unused:{unused}"

    def token(reg, src):
        sel, sext, mod = src
        text = f"|{reg}|" if "abs" in mod else reg
        return f"-{text}" if "neg" in mod else f"sext({reg})" if sext else text

    body = ["v_mov_b32_e32 v18, s44", "v_mov_b32_e32 v19, s45", "v_mov_b32_e32 v20, s46"]
    sels = f" src0_sel:{s0[0]}" + (f" src1_sel:{s1[0]}" if s1 else "")
    operands = token("v18", s0) + (f", {token('v19', s1)}" if s1 else "")
    body.append(f"v_{op}_sdwa v20, {operands}{fields}{sels}")
    body += [f"v_cvt_f32_ubyte{n}_e32 v{12 + n}, v20" for n in range(4)]
    return with_constants(body)


def check_sdwa_word_draws(directory, compiler, renderer, backend):
    case = directory / "sdwa_word.case"
    for index, row in enumerate(WORD_ROWS):
        source = directory / f"sdwa_word{index}.hlsl"
        shader = directory / f"sdwa_word{index}.cso"
        source.write_text(translate(row_program(row)), encoding="ascii")
        subprocess.run([compiler, "-Gis", "-T", "ps_6_0", "-E", "main", "-Fo", shader, source], check=True)
        constants = bytearray(256)
        struct.pack_into("<4I", constants, 12, *row[5])
        draw = [renderer, backend, "--check-pixel-case", shader, case]
        checks = {row_expected(row): "right"}
        for label, word in row_wrongs(row):
            checks.setdefault(word, label)
        for word, label in checks.items():
            channels = [float((word >> 8 * n) & 255) for n in range(4)]
            case.write_bytes(constants + struct.pack("<4f", *channels) * 64)
            if label == "right":
                subprocess.run(draw, check=True)
                continue
            result = subprocess.run(draw, capture_output=True, text=True)
            if result.returncode != 1 or "pixel_mismatch" not in result.stderr:
                raise AssertionError(f"A wrong SDWA reference ({label}) escaped detection for {row[:5]}")


# v_cvt_pkrtz_f16_f32_sdwa with whole-dword selections is the packing of the export tail: the tail's two packs are
# replaced by SDWA ones. A reference with the red and green values swapped must fail.
PACK_BODY = ["v_mov_b32_e32 v12, s44", "v_mov_b32_e32 v13, s45", "v_mov_b32_e32 v14, s46", "v_mov_b32_e32 v15, s47"]


def pack_program():
    program = with_constants(PACK_BODY)
    sdwa = "dst_sel:DWORD dst_unused:UNUSED_PAD src0_sel:DWORD src1_sel:DWORD"
    program = [line.replace("v_cvt_pkrtz_f16_f32_e32 v16, v12, v13", f"v_cvt_pkrtz_f16_f32_sdwa v16, v12, v13 {sdwa}")
               .replace("v_cvt_pkrtz_f16_f32_e32 v17, v14, v15", f"v_cvt_pkrtz_f16_f32_sdwa v17, v14, v15 {sdwa}") for line in program]
    assert sum("pkrtz_f16_f32_sdwa" in line for line in program) == 2
    return program


def check_sdwa_pack_draw(directory, compiler, renderer, backend):
    source = directory / "sdwa_pack.hlsl"
    shader = directory / "sdwa_pack.cso"
    case = directory / "sdwa_pack.case"
    source.write_text(translate(pack_program()), encoding="ascii")
    subprocess.run([compiler, "-Gis", "-T", "ps_6_0", "-E", "main", "-Fo", shader, source], check=True)
    values = [1.5, -0.25, 3.0, 0.125]
    constants = bytearray(256)
    struct.pack_into("<4f", constants, 12, *values)
    draw = [renderer, backend, "--check-pixel-case", shader, case]
    case.write_bytes(constants + struct.pack("<4f", *values) * 64)
    subprocess.run(draw, check=True)
    case.write_bytes(constants + struct.pack("<4f", values[1], values[0], *values[2:]) * 64)
    result = subprocess.run(draw, capture_output=True, text=True)
    if result.returncode != 1 or "pixel_mismatch" not in result.stderr:
        raise AssertionError("Swapped packed halves escaped detection")


def controls(directory):
    # Every row has a wrong reference for each destination field, unused mode and modifier, and every
    # operation has one for each source selector and extension its rows can show.
    assert not op_gaps(WORD_ROWS), op_gaps(WORD_ROWS)
    for row in WORD_ROWS:
        assert row[5] and row_complete(row) and row_expected(row), row
        body = translate(row_program(row)).split("float4 main", 1)[1]
        # Integer and binary16 values stay uint words: the only float variables are the four byte read-backs, and
        # a whole-dword cvt_f32_ubyte result, which is a float.
        assert body.count("precise float") == 4 + (1 if row[0].startswith("cvt_f32_ubyte") and row[1] == "DWORD" else 0), (row, body)
    for operation in (  # A constant has no field to select, and a float constant is no integer.
                      "v_add_nc_u32_sdwa v12, 5, v13 dst_sel:DWORD dst_unused:UNUSED_PAD src0_sel:BYTE_1 src1_sel:DWORD",
                      "v_and_b32_sdwa v12, 1.0, v13 dst_sel:DWORD dst_unused:UNUSED_PAD src0_sel:DWORD src1_sel:DWORD",
                      "v_not_b32_sdwa v12, sext(5) dst_sel:DWORD dst_unused:UNUSED_PAD src0_sel:DWORD",
                      "v_xor_b32_sdwa v12, s44, v13 dst_sel:BYTE_1 dst_unused:UNUSED_SEXT src0_sel:DWORD src1_sel:DWORD",
                      "v_xor_b32_sdwa v12, s44, v13 dst_sel:DWORD dst_unused:UNUSED_PAD src0_sel:DWORD",
                      "v_xor_b32_sdwa v12, s44, v13 dst_sel:DWORD dst_unused:UNUSED_PAD src0_sel:DWORD src1_sel:DWORD clamp",
                      "v_not_b32_sdwa v12, s44 dst_sel:DWORD dst_unused:UNUSED_PAD src0_sel:DWORD src1_sel:DWORD",
                      "v_cvt_f32_ubyte1_sdwa v12, s44 dst_sel:DWORD dst_unused:UNUSED_PAD src0_sel:WORD_2",
                      "v_cvt_f32_ubyte4_sdwa v12, s44 dst_sel:DWORD dst_unused:UNUSED_PAD src0_sel:DWORD",
                      # A binary16 result has no whole-dword placement; sext is not a float modifier; a constant
                      # takes no sub-dword selection; the exponent of ldexp is an integer.
                      "v_mul_f16_sdwa v12, s44, v13 dst_sel:DWORD dst_unused:UNUSED_PAD src0_sel:WORD_1 src1_sel:WORD_0",
                      "v_mul_f16_sdwa v12, sext(s44), v13 dst_sel:WORD_1 dst_unused:UNUSED_PAD src0_sel:BYTE_1 src1_sel:WORD_0",
                      "v_mul_f16_sdwa v12, 1.0, v13 dst_sel:WORD_1 dst_unused:UNUSED_PAD src0_sel:WORD_1 src1_sel:WORD_0",
                      "v_floor_f16_sdwa v12, s44 dst_sel:WORD_1 dst_unused:UNUSED_PAD src0_sel:WORD_1 src1_sel:WORD_0",
                      "v_mul_f16_sdwa v12, s44, v13 dst_sel:WORD_1 dst_unused:UNUSED_PAD src0_sel:WORD_1",
                      "v_ldexp_f16_sdwa v12, s44, 1.0 dst_sel:WORD_1 dst_unused:UNUSED_PAD src0_sel:WORD_1 src1_sel:DWORD",
                      "v_ldexp_f16_sdwa v12, s44, v13 dst_sel:WORD_1 dst_unused:UNUSED_SEXT src0_sel:WORD_1 src1_sel:BYTE_0",
                      "v_cvt_f16_f32_sdwa v12, s44 dst_sel:DWORD dst_unused:UNUSED_PAD src0_sel:DWORD",
                      "v_cvt_f16_f32_sdwa v12, s44 dst_sel:WORD_1 dst_unused:UNUSED_PAD src0_sel:WORD_1",
                      "v_cvt_pkrtz_f16_f32_sdwa v12, s44, v13 dst_sel:WORD_1 dst_unused:UNUSED_PAD src0_sel:DWORD src1_sel:DWORD",
                      "v_cvt_pkrtz_f16_f32_sdwa v12, s44, v13 dst_sel:DWORD dst_unused:UNUSED_PAD src0_sel:WORD_0 src1_sel:DWORD",
                      # No SDWA select: libLLVM 18 does not decode v_cndmask_b32_sdwa for gfx1013, so it is not drawn.
                      "v_cndmask_b32_sdwa v12, s44, v13, vcc_lo dst_sel:DWORD dst_unused:UNUSED_PAD src0_sel:DWORD src1_sel:DWORD",
                      # A binary32 value of a class test or arithmetic has no field to select.
                      "v_sub_f32_e64 v18, s45, 0\nv_cmp_class_f32_sdwa vcc_lo, s44, v18 src0_sel:WORD_1 src1_sel:DWORD",
                      "v_cmp_class_f16_sdwa vcc_lo, s44, sext(5) src0_sel:WORD_1 src1_sel:DWORD",
                      "v_cmp_lt_f16_sdwa vcc_lo, sext(s44), v13 src0_sel:WORD_1 src1_sel:WORD_0",
                      "v_cmp_lt_f16_sdwa vcc_lo, s44, v13 src0_sel:WORD_1"):
        must_reject(translate, with_constants(operation.split("\n")))
    # A partial UNUSED_PRESERVE result needs a tracked numeric destination, as for SDWA moves.
    for register in ("v0", "v8", "v20"):
        must_reject(translate, with_constants([f"v_or_b32_sdwa {register}, s44, v13 dst_sel:WORD_1 dst_unused:UNUSED_PRESERVE src0_sel:WORD_0 src1_sel:DWORD"]))
        must_reject(translate, with_constants([f"v_mul_f16_sdwa {register}, s44, v13 dst_sel:WORD_1 dst_unused:UNUSED_PRESERVE src0_sel:WORD_0 src1_sel:WORD_1"]))
    # The two packs of the export tail, with whole-dword selections, lower as the e32 packs do.
    assert translate(pack_program()) == translate(with_constants(PACK_BODY)), "SDWA pack differs from the e32 pack"
    # SDWA moves select and place fields; UNUSED_SEXT, byte selections for half widening and
    # non-canonical SDWA text are refused.
    body = translate(with_constants(SDWA_PRESERVE_BODY + SDWA_PAD_BODY)).split("float4 main", 1)[1]
    assert body.count("& 0xffff0000u) | ") == 2 and body.count("asint(") == 1 and body.count("widen16(") == 2, body
    must_reject(translate, with_constants(["v_mov_b32_sdwa v12, s44 dst_sel:BYTE_0 dst_unused:UNUSED_SEXT src0_sel:WORD_1"]))
    must_reject(translate, with_constants(["v_cvt_f32_f16_sdwa v12, s44 dst_sel:DWORD dst_unused:UNUSED_PAD src0_sel:BYTE_1"]))
    must_reject(translate, with_constants(["v_mov_b32_sdwa v12, s44 src0_sel:WORD_1"]))
    # UNUSED_PRESERVE keeps bits only from a tracked numeric value; DWORD and padded writes may replace anything.
    for register in ("v0", "v1", "v8", "v9", "v20"):
        must_reject(translate, with_constants([f"v_mov_b32_sdwa {register}, s44 dst_sel:WORD_0 dst_unused:UNUSED_PRESERVE src0_sel:WORD_1"]))
    body = translate(with_constants(["v_mov_b32_sdwa v12, -0.5 dst_sel:DWORD dst_unused:UNUSED_PAD src0_sel:DWORD",
                                     "v_mov_b32_sdwa v20, s44 dst_sel:WORD_1 dst_unused:UNUSED_PAD src0_sel:WORD_0",
                                     "v_mov_b32_sdwa v13, v20 dst_sel:DWORD dst_unused:UNUSED_PRESERVE src0_sel:DWORD"])).split("float4 main", 1)[1]
    assert "asuint((-0.5f))" in body, body


def binary_fixtures():
    """(program, translator) pairs that `pixel_aot_check.py binary` assembles, disassembles and lowers."""
    return [
        *((with_constants(body), translate) for body in (SDWA_PRESERVE_BODY, SDWA_PAD_BODY)),
        *((row_program(row), translate) for row in WORD_ROWS),
        (pack_program(), translate),
    ]


draw = check_sdwa_draw
