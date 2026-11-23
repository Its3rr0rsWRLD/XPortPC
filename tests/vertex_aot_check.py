"""Exercise offline vertex translation (cards V-1 to V-3, docs/design/vertex-stage.md) with hand-written gfx1013 programs.

Modes:
    vertex_aot_check.py --list-families
    vertex_aot_check.py controls                                   no DXC, no GPU
    vertex_aot_check.py draw <dxc> <offscreen_check> warp|hardware [--family NAME ...]
    vertex_aot_check.py binary <llvm-mc> <llvm-objcopy> [<libLLVM>]  assemble, disassemble and lower again

A draw translates a program with tools/vertex_aot.py, compiles it as vs_6_0, draws it as a point list and compares every
stream-output dword with a reference computed here in Python integers by a small model of the console (Model below),
which reads the same user-SGPR role map, descriptor words and title memory the draw binds. Each family also proves its
wrong references are caught: a reference with one plausible bug (base vertex ignored, instance id for vertex id, stride
ignored, the record at num_records read, parameters swapped, a fused multiply-add, a NaN quieted, ...) must make the
renderer report vertex_mismatch, and every bug must change at least one dword of some draw.

The programs follow the shapes of the RADV-built corpus vertex shaders (base vertex in a user SGPR, a 32-bit descriptor
pointer completed with s_movk_i32 0x8000, s_load_dwordx4/x8/x16 of V#s, indexed buffer_load_dword*, partial vmcnt waits,
pos0 and param exports). Cards V-2 and V-3 add the same programs inside RADV's NGG passthrough frame (both region
orders, with the NGG entry registers), the instance id with a start instance, inline push-constant words, a uniform
block read both as constants and by offen buffer loads, global loads through a 64-bit address in push words, and
clip and cull distances under PA_CL_VS_OUT_CNTL state. No corpus binary is used.
"""
from fractions import Fraction
import math
import os
from pathlib import Path
import re
import struct
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tests"))
import vertex_aot  # noqa: E402
from pixel_aot_ops.dispatch import claimants  # noqa: E402
import pixel_memory_check as titlemem  # noqa: E402

M32 = 0xffffffff
HIGH = vertex_aot.RADV_ADDRESS_HIGH

# First word of each line of every program the translator accepted in this run, for tools/form_coverage.py (written
# where CTest's FORM_COVERAGE_RECORD points). A program a check expects to be refused raises before it is recorded.
ACCEPTED = set()


def lower(instructions, roles, vs_out_cntl=None):
    source, layout = vertex_aot.lower_with_layout(instructions, roles, vs_out_cntl)
    lines = [line.split(";")[0].strip() for line in instructions]
    ACCEPTED.update(line.split()[0] for line in lines if line and not line.endswith(":"))
    for line in lines:
        if len(families := claimants(line)) > 1:
            raise AssertionError(f"Forms of more than one family match {line!r}: {', '.join(families)}")
    return source, layout


def write_record(path):
    if path:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text("".join(f"{word}\n" for word in sorted(ACCEPTED)), encoding="utf-8")


def must_refuse(instructions, roles, reason=None, vs_out_cntl=None):
    try:
        vertex_aot.lower_with_layout(instructions, roles, vs_out_cntl)
    except ValueError as error:
        if reason is not None and reason not in str(error):
            raise AssertionError(f"Refused for another reason: {error} (expected {reason!r})")
        return
    raise AssertionError(f"Accepted a program that must be refused ({reason}):\n" + "\n".join(instructions))


# --- binary32 in Python integers ---------------------------------------------------------------------------------------

def f32_fraction(bits):
    """The exact value of a finite binary32 encoding."""
    sign = -1 if bits >> 31 else 1
    exponent = (bits >> 23) & 0xff
    mantissa = bits & 0x7fffff
    if exponent == 0xff:
        raise ArithmeticError(f"{bits:#010x} is not finite")
    if exponent == 0:
        return sign * Fraction(mantissa, 1 << 149)
    return sign * Fraction(mantissa | 0x800000, 1 << 150) * (1 << exponent)


def round_f32(value, negative_zero=False):
    """Round an exact rational to binary32, to nearest with ties to even; overflow gives infinity."""
    if value == 0:
        return 0x80000000 if negative_zero else 0
    sign = 0x80000000 if value < 0 else 0
    value = abs(value)
    exponent = value.numerator.bit_length() - value.denominator.bit_length()
    if Fraction(1 << exponent if exponent >= 0 else 1, 1 if exponent >= 0 else 1 << -exponent) > value:
        exponent -= 1
    exponent = max(exponent, -126)  # below 2^-126 the quantum stays 2^-149
    quantum = Fraction(1 << (exponent - 23)) if exponent >= 23 else Fraction(1, 1 << (23 - exponent))
    scaled = value / quantum
    whole = scaled.numerator // scaled.denominator
    rest = scaled - whole
    if rest > Fraction(1, 2) or (rest == Fraction(1, 2) and whole & 1):
        whole += 1
    if whole == 1 << 24:
        whole, exponent = 1 << 23, exponent + 1
    if exponent > 127:
        return sign | 0x7f800000
    if whole < 1 << 23:
        return sign | whole  # subnormal (exponent is -126 here)
    return sign | (exponent + 127) << 23 | (whole & 0x7fffff)


def is_subnormal(bits):
    return (bits >> 23) & 0xff == 0 and bits & 0x7fffff


def ftz(bits):
    return bits & 0x80000000 if is_subnormal(bits) else bits


def checked(bits):
    """Keep the references away from the desktop's binary32 denormal mode, which the translation leaves to DXIL."""
    if is_subnormal(bits) or (bits >> 23) & 0xff == 0xff:
        raise ArithmeticError(f"Reference reached {bits:#010x}; choose other test data")
    return bits


def f32_mul(a, b):
    product = f32_fraction(checked(a)) * f32_fraction(checked(b))
    return checked(round_f32(product, negative_zero=(a ^ b) >> 31 == 1))


def f32_add(a, b):
    total = f32_fraction(checked(a)) + f32_fraction(checked(b))
    return checked(round_f32(total, negative_zero=a == b == 0x80000000))


def f32_mad(a, b, c, fused=False):
    """v_mad_f32/v_mac_f32: the product is rounded before the add, and every operand, the product and the sum are
    flushed to signed zero when subnormal (tools/pixel_aot_ops/hlsl.py, mad32). fused=True is the wrong reference:
    one rounding, as v_fma_f32."""
    a, b, c = ftz(a), ftz(b), ftz(c)
    if fused:
        exact = f32_fraction(a) * f32_fraction(b) + f32_fraction(c)
        return round_f32(exact, negative_zero=((a ^ b) >> 31 == 1) and c == 0x80000000)
    product = ftz(round_f32(f32_fraction(a) * f32_fraction(b), negative_zero=(a ^ b) >> 31 == 1))
    total = round_f32(f32_fraction(product) + f32_fraction(c), negative_zero=product == c == 0x80000000)
    return ftz(total)


INLINE_FLOAT = {"0.5": 0x3f000000, "1.0": 0x3f800000, "2.0": 0x40000000, "4.0": 0x40800000}


# --- a model of the console for the forms the V-1 programs use ---------------------------------------------------------

# --- typed fetch (gfx10 unified buffer formats) ------------------------------------------------------------------------

_K6 = ["UNORM", "SNORM", "USCALED", "SSCALED", "UINT", "SINT"]
_K7 = _K6 + ["FLOAT"]
# LLVM AMDGPU::UfmtGFX10 names of formats 1..77 (BUF_FMT_<name>); written out independently of tools/.
UFMT_NAMES = ([f"8_{k}" for k in _K6] + [f"16_{k}" for k in _K7] + [f"8_8_{k}" for k in _K6]
              + ["32_UINT", "32_SINT", "32_FLOAT"] + [f"16_16_{k}" for k in _K7] + [f"10_11_11_{k}" for k in _K7]
              + [f"11_11_10_{k}" for k in _K7] + [f"10_10_10_2_{k}" for k in _K6] + [f"2_10_10_10_{k}" for k in _K6]
              + [f"8_8_8_8_{k}" for k in _K6] + ["32_32_UINT", "32_32_SINT", "32_32_FLOAT"]
              + [f"16_16_16_16_{k}" for k in _K7] + ["32_32_32_UINT", "32_32_32_SINT", "32_32_32_FLOAT",
                                                    "32_32_32_32_UINT", "32_32_32_32_SINT", "32_32_32_32_FLOAT"])
assert len(UFMT_NAMES) == 77


def ufmt_layout(fmt, flaws=()):
    """(component widths x..w, numeric kind) of a gfx10 format read off its name, or None for INVALID and numbers past
    77. AMD names list components from the most significant bits, so x is the last field of the name (Mesa
    radv_formats.c gives R10G10B10A2 the format 2_10_10_10 and B10G11R11_UFLOAT 10_11_11); kinds are 0 UNORM, 1 SNORM,
    2 USCALED, 3 SSCALED, 4 UINT, 5 SINT, 6 FLOAT. The wrong reference "reversed_components" reads the name from x."""
    if not 1 <= fmt <= 77:
        return None
    *fields, kind = UFMT_NAMES[fmt - 1].split("_")
    widths = [int(w) for w in (fields if "reversed_components" in flaws else reversed(fields))]
    return widths + [0] * (4 - len(widths)), _K7.index(kind)


def small_float(bits, exponent_bits, mantissa_bits, signed, flaws=()):
    """The binary32 encoding of a float with the given fields: exact (every such value is a binary32 value); Inf and
    NaN keep their mantissa, shifted to the top."""
    sign = (bits >> (exponent_bits + mantissa_bits)) & 1 if signed else 0
    e = (bits >> mantissa_bits) & ((1 << exponent_bits) - 1)
    m = bits & ((1 << mantissa_bits) - 1)
    if e == (1 << exponent_bits) - 1:
        return sign << 31 | 0x7f800000 | m << (23 - mantissa_bits)
    bias = (1 << (exponent_bits - 1)) - 1
    if e == 0 and "small_float_flush" in flaws:
        value = Fraction(0)
    elif e == 0:
        value = Fraction(m, 1 << mantissa_bits) * Fraction(1, 1 << (bias - 1))
    else:
        value = (1 + Fraction(m, 1 << mantissa_bits)) * Fraction(2) ** (e - bias)
    return round_f32(-value if sign else value, negative_zero=bool(sign))


def typed_component(value, width, kind, flaws=()):
    """One component of a typed load as a 32-bit word: Vulkan's conversions (UNORM c / (2^n - 1), SNORM
    max(c / (2^(n-1) - 1), -1)) rounded to nearest even, scaled as exact floats, integers zero- or sign-extended."""
    top = 1 << (width - 1)
    signed = value - (1 << width) if value & top else value
    def rounded(fraction):
        bits = round_f32(fraction)
        if "norm_truncate" in flaws and abs(f32_fraction(bits)) > abs(fraction):
            bits -= 1  # a wrong reference: toward zero (one step down in magnitude)
        return bits
    if kind == 0:
        return rounded(Fraction(value, (1 << width) - 1))
    if kind == 1:
        if signed == -top and "snorm_unclamped" not in flaws:
            return 0xbf800000
        return rounded(Fraction(signed, top - 1))
    if kind == 2:
        return round_f32(Fraction(value))
    if kind == 3:
        return round_f32(Fraction(signed))
    if kind == 4:
        return value
    if kind == 5:
        return signed & M32
    if width == 32:
        return value
    return small_float(value, 5, width - 6 if width == 16 else width - 5, width == 16, flaws)


def typed_element(fmt, data, flaws=()):
    """The four raw components (missing ones 0, 0, 0 and 1 or 1.0) of an element of format `fmt` read as the integer
    `data` (little endian)."""
    widths, kind = ufmt_layout(fmt, flaws)
    floats = kind not in (4, 5)
    out = [0, 0, 0, 0x3f800000 if floats != ("w_default_swapped" in flaws) else 1]
    shift = 0
    for c in range(4):
        if widths[c]:
            out[c] = typed_component((data >> shift) & ((1 << widths[c]) - 1), widths[c], kind, flaws)
        shift += widths[c]
    return out


class Memory:
    """Title memory: (begin, bytes, slot) ranges. A dword read outside every range is a miss and reads 0, as in
    the shader's TitleLookup."""

    def __init__(self, ranges):
        self.ranges = [(begin, data) for begin, data in ranges]

    def word(self, address):
        for begin, data in self.ranges:
            if begin <= address and address + 4 <= begin + len(data) and address % 4 == 0:
                return int.from_bytes(data[address - begin:address - begin + 4], "little")
        return 0

    def byte(self, address):
        return (self.word(address & ~3) >> (8 * (address & 3))) & 0xff

    def section(self):
        return titlemem.section([(begin, begin + len(data), slot) for slot, (begin, data) in enumerate(self.ranges)],
                                [data for _, data in self.ranges])


def vsharp(base, stride, records, select):
    """Four gfx10 V# words: base 48 bits, stride in word 1, num_records, OOB_SELECT. DST_SEL and FORMAT are set to
    values the loads ignore, as in the pixel load checks."""
    noise = (1 << 24) | (0x14 << 12) | 0xfac
    return [base & M32, (base >> 32) | stride << 16, records, noise | select << 28]


class Model:
    """Straight-line execution of one vertex. flaws switches individual rules to a plausible wrong one."""

    def __init__(self, roles, constants, memory, flaws=(), descriptors=None, push=(), stage="legacy"):
        self.roles, self.constants, self.memory, self.flaws = roles, constants, memory, set(flaws)
        self.descriptors = constants[:64] if descriptors is None else descriptors
        self.push, self.stage = list(push) + [0] * (32 - len(push)), stage

    def run(self, program, vertex_id, base_vertex, instance_id=0, start_instance=0):
        s, v = {}, {}
        cbv_words = None
        carries = {}
        for number, role in self.roles.items():
            if role[0] == "descriptors":
                s[number] = ("pointer", number)
            elif role[0] == "base_vertex":
                s[number] = 0 if "base_ignored" in self.flaws else base_vertex
            elif role[0] == "start_instance":
                s[number] = 0 if "start_ignored" in self.flaws else start_instance
            elif role[0] == "inline":
                s[number] = self.push[role[1] + ("push_shifted" in self.flaws)]
        vid, iid = (0, 3) if self.stage == "legacy" else (5, 8)
        v[vid] = instance_id if "instance_id" in self.flaws else vertex_id
        v[iid] = vertex_id if "vertex_for_instance" in self.flaws else instance_id
        exports = {}

        def sreg(token):
            value = s[int(token[1:])]
            if not isinstance(value, int):
                raise AssertionError(f"{token} holds {value}, not data")
            return value

        def word(token):
            if token.startswith("-") and not re.fullmatch(r"-\d+", token):
                return word(token[1:]) ^ 0x80000000
            if re.fullmatch(r"v\d+", token):
                return v[int(token[1:])]
            if re.fullmatch(r"s\d+", token):
                return sreg(token)
            if token in INLINE_FLOAT:
                return INLINE_FLOAT[token]
            if re.fullmatch(r"-?\d+", token):
                return int(token) & M32
            if re.fullmatch(r"0x[0-9a-f]+", token):
                return int(token, 16)
            raise AssertionError(f"Model has no operand {token}")

        def span(token):
            if m := re.fullmatch(r"([sv])\[(\d+):(\d+)\]", token):
                return list(range(int(m[2]), int(m[3]) + 1))
            return [int(token[1:])]

        for raw in program:
            line = raw.split(";")[0].strip()
            if not line or line.endswith(":"):
                continue
            head, _, rest = line.partition(" ")
            ops = [t.strip() for t in rest.split(",")]
            name = re.sub(r"_e(32|64)$", "", head)
            if name in ("s_setprio", "s_clause", "s_nop", "s_waitcnt", "s_waitcnt_depctr", "s_endpgm"):
                continue
            if name == "s_mov_b32":
                s[int(ops[0][1:])] = s[int(ops[1][1:])] if ops[1].startswith("s") else word(ops[1])
            elif name == "s_movk_i32":
                imm = int(ops[1], 0)
                s[int(ops[0][1:])] = (imm - 0x10000 if imm & 0x8000 else imm) & M32
            elif name.startswith("s_load_dword") and isinstance(s[span(ops[1])[0]], int):
                low, high = (s[n] for n in span(ops[1]))  # a 64-bit address in data words: title memory
                address = ((low | high << 32) & ~3) + (0 if ops[2] == "null" else int(ops[2], 0))
                for j, n in enumerate(span(ops[0])):
                    s[n] = self.memory.word((address + 4 * j) % (1 << 64))
            elif name.startswith("s_load_dword"):
                pointer = s[span(ops[1])[0]]
                table_high, entries = self.roles[pointer[1]][1:]
                assert s[span(ops[1])[1]] == table_high
                offset = 0 if ops[2] == "null" else int(ops[2], 0)
                for j, n in enumerate(span(ops[0])):
                    at = offset + 4 * j
                    start = next(k for k in entries if k <= at < k + 16)
                    entry = entries[start]
                    if entry == ("constants",):
                        s[n] = ("cbv", (at - start) // 4)
                    else:
                        s[n] = self.descriptors[entry[1] + (at - start) // 4]
                        if entry[0] == "constants":
                            cbv_words = self.descriptors[entry[1]:entry[1] + 4]
            elif name.startswith("s_buffer_load_dword") and ops[2].startswith("s"):
                # A run-time byte offset (docs/design/compute-stage.md, dynamic scalar constant loads): the two low
                # bits ignored, each dword wholly inside the 64 KiB binding read, any other dword 0.
                base = span(ops[1])
                assert [s[n] for n in base] in ([("cbv", j) for j in range(4)], cbv_words)
                register, _, extra = ops[2].partition(" offset:")
                low = M32 if "dyn_unmasked" in self.flaws else ~3  # a wrong reference keeps the two low bits
                start = (0 if "dyn_ignored" in self.flaws else sreg(register) & low) + int(extra or "0", 0)
                for j, n in enumerate(span(ops[0])):
                    at = start + 4 * j
                    if "dyn_wrap" in self.flaws:  # a wrong reference: no range check, the offset wraps at 64 KiB
                        at %= 0x10000
                    s[n] = self.constants[at // 4] if at + 4 <= 0x10000 else 0
            elif name.startswith("s_buffer_load_dword"):
                base = span(ops[1])
                assert [s[n] for n in base] in ([("cbv", j) for j in range(4)], cbv_words)
                offset = 0 if ops[2] == "null" else int(ops[2], 0)
                values = [self.constants[offset // 4 + j] for j in range(len(span(ops[0])))]
                if "window_64" in self.flaws:  # a wrong reference: constant words past 64 read as zero
                    values = [0 if offset // 4 + j >= 64 else x for j, x in enumerate(values)]
                for n, value in zip(span(ops[0]), values):
                    s[n] = value
            elif name.startswith(("buffer_load_format", "tbuffer_load_format")):
                self.typed_fetch(name, ops, v, s, span)
            elif name.startswith("buffer_load_dword"):
                self.fetch(ops, v, s, span)
            elif name.startswith("global_load_dword"):
                tail = ops[2].split()
                imm = next((int(m[7:]) for m in tail[1:] if m.startswith("offset:")), 0)
                if tail[0] == "off":
                    lo, hi = (v[n] for n in span(ops[1]))
                    address = lo | hi << 32
                else:
                    lo, hi = (s[n] for n in span(tail[0]))
                    address = (lo | hi << 32) + v[int(ops[1][1:])]
                for j, n in enumerate(span(ops[0])):
                    v[n] = self.memory.word((address + imm + 4 * j) % (1 << 64))
            elif name in ("s_lshl_b32", "s_and_b32", "s_or_b32"):
                a, b = word(ops[1]), word(ops[2])
                s[int(ops[0][1:])] = {"s_lshl_b32": (a << (b & 31)) & M32, "s_and_b32": a & b,
                                      "s_or_b32": a | b}[name]
            elif name == "v_mov_b32":
                v[int(ops[0][1:])] = word(ops[1])
            elif name in ("v_add_nc_u32", "v_and_b32", "v_xor_b32", "v_or_b32", "v_lshlrev_b32", "v_mul_u32_u24"):
                a, b = word(ops[1]), word(ops[2])
                v[int(ops[0][1:])] = {
                    "v_add_nc_u32": (a + b) & M32, "v_and_b32": a & b, "v_xor_b32": a ^ b, "v_or_b32": a | b,
                    "v_lshlrev_b32": (b << (a & 31)) & M32, "v_mul_u32_u24": ((a & 0xffffff) * (b & 0xffffff)) & M32,
                }[name]
            elif name in ("v_sin_f32", "v_cos_f32", "v_rndne_f32"):
                source, _, modifier = ops[1].partition(" ")
                value = f32_fraction(checked(word(source)))
                if name == "v_rndne_f32":
                    result = round_f32(Fraction(round(value)))  # ties to even
                else:
                    result = round_f32(Fraction(self.trig(name, float(value))))
                    if modifier == "div:2" and "div2_ignored" not in self.flaws:
                        result = round_f32(f32_fraction(result) / 2)
                v[int(ops[0][1:])] = result
            elif re.fullmatch(r"v_(add|sub|subrev)_co_(ci_)?u32", name):
                kind = name.split("_")[1]
                a, b = word(ops[2]), word(ops[3])
                if kind == "subrev" and "subrev_swapped" not in self.flaws:
                    a, b = b, a
                mask = ops[1].replace("vcc_lo", "vcc")
                carry_in = 0
                if name.endswith("_ci_u32"):
                    carry_in = 0 if "no_carry_in" in self.flaws else carries[ops[4].replace("vcc_lo", "vcc")]
                if kind == "add":
                    total = a + b + carry_in
                    out = total >> 32
                else:
                    total = a - b - carry_in
                    out = 1 if total < 0 else 0
                    if "no_borrow" in self.flaws:
                        out = 0
                carries[mask] = out
                v[int(ops[0][1:])] = total & M32
            elif name == "v_cvt_f32_ubyte0":
                v[int(ops[0][1:])] = round_f32(Fraction(word(ops[1]) & 0xff))
            elif name == "v_mul_f32":
                v[int(ops[0][1:])] = f32_mul(word(ops[1]), word(ops[2]))
            elif name == "v_add_f32":
                v[int(ops[0][1:])] = f32_add(word(ops[1]), word(ops[2]))
            elif name == "v_sub_f32":
                v[int(ops[0][1:])] = f32_add(word(ops[1]), word(ops[2]) ^ 0x80000000)
            elif name == "v_mad_f32":
                v[int(ops[0][1:])] = f32_mad(word(ops[1]), word(ops[2]), word(ops[3]), "fused" in self.flaws)
            elif name == "v_mac_f32":
                v[int(ops[0][1:])] = f32_mad(word(ops[1]), word(ops[2]), word(ops[0]), "fused" in self.flaws)
            elif head == "exp":
                target = ops[0].split()[0]
                sources = [ops[0].split()[1]] + ops[1:]
                sources[-1] = sources[-1].split()[0]
                exports[target] = [None if t == "off" else self.export_word(v[int(t[1:])]) for t in sources]
            else:
                raise AssertionError(f"Model has no instruction {line}")
        return exports

    def trig(self, name, revolutions):
        """v_sin_f32 and v_cos_f32 take their argument in revolutions. "radians" is the wrong reference that does not
        scale it, "sin_cos_swapped" exchanges the two."""
        angle = revolutions if "radians" in self.flaws else 2 * math.pi * revolutions
        swapped = "sin_cos_swapped" in self.flaws
        return math.sin(angle) if (name == "v_sin_f32") != swapped else math.cos(angle)

    def fetch(self, ops, v, s, span):
        """buffer_load_dword* idxen with an instruction offset: gfx10 range rules as tools/pixel_aot_ops/hlsl.py cites
        them (Mesa ac_set_buf_desc_word3), per dword."""
        rsrc = [s[n] for n in span(ops[2])]
        if not all(isinstance(w, int) for w in rsrc):
            raise AssertionError("V# words are not data")
        modifiers = ops[-1].split()[1:]
        inst = next((int(m[7:]) for m in modifiers if m.startswith("offset:")), 0)
        if "offen" in modifiers:
            index, voffset = 0, v[int(ops[1][1:])]
        else:
            index, voffset = v[int(ops[1][1:])], 0
        base = rsrc[0] | (rsrc[1] & 0xffff) << 32
        stride, records, select = (rsrc[1] >> 16) & 0x3fff, rsrc[2], (rsrc[3] >> 28) & 3
        for j, n in enumerate(span(ops[0])):
            offset = voffset + inst + 4 * j
            if offset > M32:  # the offset sum wraps: the load reads 0
                v[n] = 0
                continue
            index_in = index <= records if "records_inclusive" in self.flaws else index < records
            if select == 0:
                ok = index_in and (offset < stride or "no_offset_check" in self.flaws)
            elif select == 1:
                ok = index_in and not ("mode1_offset_checked" in self.flaws and offset >= stride)
            elif select == 2:
                ok = records != 0
            else:
                ok = offset < records
            step = 0 if "nostride" in self.flaws else stride * index
            v[n] = self.memory.word((base + step + offset) % (1 << 64)) if ok else 0

    def typed_fetch(self, name, ops, v, s, span):
        """buffer_load_format_* (format from V# word 3 bits 12..18) and tbuffer_load_format_* (format from the
        instruction) idxen: the element whose first byte passes the range rule of `fetch`, converted (typed_element),
        placed by DST_SEL; an out-of-range element or an invalid format reads 0 in every channel."""
        rsrc = [s[n] for n in span(ops[2])]
        modifiers = ops[-1].split()[1:]
        inst = next((int(m[7:]) for m in modifiers if m.startswith("offset:")), 0)
        assert "idxen" in modifiers and "offen" not in modifiers
        index = v[int(ops[1][1:])]
        if name.startswith("tbuffer"):
            fmt_name = next(m for m in modifiers if m.startswith("format:"))[len("format:["):-1]
            fmt = UFMT_NAMES.index(fmt_name[len("BUF_FMT_"):]) + 1
        else:
            fmt = (rsrc[3] >> 12) & 0x7f
        if "format_ignored" in self.flaws:
            fmt = 77
        base = rsrc[0] | (rsrc[1] & 0xffff) << 32
        stride, records, select = (rsrc[1] >> 16) & 0x3fff, rsrc[2], (rsrc[3] >> 28) & 3
        ok = {0: index < records and inst < stride, 1: index < records, 2: records != 0, 3: inst < records}[select]
        layout = ufmt_layout(fmt)
        dsts = span(ops[0])
        if not ok or layout is None:
            for n in dsts:
                v[n] = 0
            return
        address = base + stride * index + inst
        size = sum(layout[0]) // 8
        data = sum(self.memory.byte((address + k) % (1 << 64)) << (8 * k) for k in range(size))
        raw = typed_element(fmt, data, self.flaws)
        floats = layout[1] not in (4, 5)
        one = 0x3f800000 if floats != ("w_default_swapped" in self.flaws) else 1
        selects = [4, 5, 6, 7] if "no_dst_sel" in self.flaws else [(rsrc[3] >> (3 * c)) & 7 for c in range(4)]
        out = [one if sel == 1 else raw[sel - 4] if sel >= 4 else 0 for sel in selects]
        for n, word in zip(dsts, out):
            v[n] = word

    def export_word(self, word):
        nan = (word >> 23) & 0xff == 0xff and word & 0x7fffff
        if nan and "canonical_nan" in self.flaws:
            return 0x7fc00000
        if nan and "quiet_nan" in self.flaws:
            return word | 0x400000
        if is_subnormal(word) and "flush_denormal" in self.flaws:
            return word & 0x80000000
        return word


# --- case files (tests/vertex_aot_render.cpp) --------------------------------------------------------------------------

DISTANCE_CODES = {"clip": 1, "cull": 2}


def case_file(records, base_vertex, params, constants, expected, mask, indices=None, memory=b"", descriptors=None,
              instances=1, start_instance=0, push=(), distances=()):
    """distances: the (kind, semantic index) of each distance vector, in stream-output order."""
    descriptors = constants[:64] if descriptors is None else descriptors
    wide = len(constants) != 64  # header word 19 names a constant window other than 64 words (multiple of 4, to 16384)
    assert len(params) <= 8 and len(constants) % 4 == 0 and 64 <= len(constants) <= 16384
    assert len(descriptors) == 64 and len(expected) == len(mask)
    assert len(push) <= 32 and len(distances) <= 2
    codes = [DISTANCE_CODES[kind] << 8 | index for kind, index in distances]
    header = [0x56573258, records, int(indices is not None), base_vertex & M32, len(params),
              *params, *[0] * (8 - len(params)), instances, start_instance & M32, len(push), len(codes),
              *codes, *[0] * (2 - len(codes)), len(constants) if wide else 0, *[0] * 12]
    assert len(header) == 32
    body = header + list(constants) + list(descriptors) + list(push) + list(indices or []) + list(expected) + list(mask)
    return struct.pack(f"<{len(body)}I", *body) + memory


def distance_semantics(layout):
    """(kind, semantic index) per distance vector, as vertex_aot numbers SV_ClipDistanceN and SV_CullDistanceN."""
    seen, out = {"clip": 0, "cull": 0}, []
    for _, kind, _ in layout["positions"]:
        out.append((kind, seen[kind]))
        seen[kind] += 1
    return out


def outputs(model, program, layout, ids, base_vertex, instances=1, start_instance=0):
    """Expected words and compare masks of a draw: per record (instance-major) pos0, each distance vector, then each
    parameter, xyzw. An `off` channel, and a distance channel PA_CL_VS_OUT_CNTL does not enable, is undefined: its mask
    is 0. Swapping parameters or distance vectors are wrong references."""
    positions = [name for name, _, _ in layout["positions"]]
    order = ["pos0", *positions, *(f"param{n}" for n in layout["params"])]
    first = 1 + len(positions)
    if "swap_params" in model.flaws:
        order[first], order[first + 1] = order[first + 1], order[first]
    if "swap_distances" in model.flaws:
        order[1], order[2] = order[2], order[1]
    expected, mask = [], []
    for instance in range(instances):
        for vertex_id in ids:
            exports = model.run(program, vertex_id, base_vertex, instance, start_instance)
            for name in order:
                defined = layout["channels"][name] if name in positions else (True,) * 4
                for word, on in zip(exports[name], defined):
                    expected.append(0 if word is None or not on else word)
                    mask.append(0 if word is None or not on else M32)
    return expected, mask


def float_words(seed, count):
    """Normal binary32 words with exponents within 2^-4..2^4 and both signs, from a fixed linear congruential sequence."""
    state, out = seed, []
    for _ in range(count):
        state = (state * 6364136223846793005 + 1442695040888963407) % (1 << 64)
        out.append((state >> 63) << 31 | (123 + (state >> 40) % 9) << 23 | (state >> 8) & 0x7fffff)
    return out


def words_bytes(words):
    return struct.pack(f"<{len(words)}I", *words)


# --- programs ----------------------------------------------------------------------------------------------------------

# RADV's entry shape: the base vertex arrives in s3, the vertex-buffer descriptor list pointer in s2; s3 is then reused as
# the pointer's high word.
PROLOGUE = [
    "s_setprio 3",
    "s_mov_b32 s0, s3",
    "s_movk_i32 s3, 0x8000",
]

FETCH = [
    *PROLOGUE,
    "s_load_dwordx8 s[8:15], s[2:3], null",
    "v_add_nc_u32_e32 v0, s0, v0",
    "s_waitcnt lgkmcnt(0)",
    "buffer_load_dwordx4 v[4:7], v0, s[8:11], 0 idxen",
    "buffer_load_dwordx3 v[8:10], v0, s[12:15], 0 idxen offset:4",
    "buffer_load_dwordx2 v[11:12], v0, s[8:11], 0 idxen offset:20",
    "buffer_load_dword v13, v0, s[12:15], 0 idxen",
    "v_mov_b32_e32 v14, 1.0",
    "s_waitcnt vmcnt(0)",
    "exp pos0 v4, v5, v6, v7 done vm",
    "exp param0 v8, v9, v10, off",
    "exp param1 v11, v12, v13, v14",
    "s_endpgm",
]
FETCH_ROLES = {2: ("descriptors", HIGH, {0: ("vsharp", 8), 16: ("vsharp", 12)}), 3: ("base_vertex",)}

MATRIX = [
    *PROLOGUE,
    "s_load_dwordx16 s[16:31], s[2:3], null",
    "v_add_nc_u32_e32 v0, s0, v0",
    "s_movk_i32 s5, 0x8000",
    "s_load_dwordx4 s[12:15], s[4:5], null",
    "s_waitcnt lgkmcnt(0)",
    "buffer_load_dwordx3 v[1:3], v0, s[16:19], 0 idxen",
    "buffer_load_dwordx4 v[4:7], v0, s[28:31], 0 idxen offset:12",
    "s_clause 0x1",
    "s_buffer_load_dwordx16 s[32:47], s[12:15], null",
    "s_buffer_load_dwordx4 s[48:51], s[12:15], 0x40",
    "s_waitcnt lgkmcnt(0)",
    "s_waitcnt vmcnt(1)",
    *[line for r in range(4) for line in (
        f"v_mul_f32_e64 v{8 + r}, s{32 + r}, v1",
        f"v_mac_f32_e32 v{8 + r}, s{36 + r}, v2",
        f"v_mad_f32 v{8 + r}, s{40 + r}, v3, v{8 + r}",
        f"v_add_f32_e32 v{8 + r}, s{44 + r}, v{8 + r}")],
    "s_waitcnt vmcnt(0)",
    *[f"v_mul_f32_e32 v{12 + c}, s{48 + c}, v{4 + c}" for c in range(4)],
    "v_sub_f32_e32 v16, v5, v4",
    "exp pos0 v8, v9, v10, v11 done vm",
    "exp param0 v12, v13, v14, v15",
    "exp param1 v16, v1, off, off",
    "s_endpgm",
]
MATRIX_ROLES = {2: ("descriptors", HIGH, {0: ("vsharp", 32), 16: ("vsharp", 36), 32: ("vsharp", 40),
                                          48: ("vsharp", 44)}),
                3: ("base_vertex",), 4: ("descriptors", HIGH, {0: ("constants",)})}

VERTEX_ID = [
    "s_setprio 3",
    "v_add_nc_u32_e32 v1, s3, v0",
    "v_lshlrev_b32_e32 v2, 1, v1",
    "v_and_b32_e32 v2, 2, v2",
    "v_and_b32_e32 v3, 2, v1",
    "v_cvt_f32_ubyte0_e32 v4, v2",
    "v_cvt_f32_ubyte0_e32 v5, v3",
    "v_mad_f32 v6, v4, 2.0, -1.0",
    "v_mad_f32 v7, v5, -2.0, 1.0",
    "v_mov_b32_e32 v8, 0",
    "v_mov_b32_e32 v9, 1.0",
    "v_mul_u32_u24_e32 v10, 0x9e3779b1, v1",
    "v_xor_b32_e32 v11, v1, v10",
    "exp pos0 v6, v7, v8, v9 done vm",
    "exp param0 v4, v5, off, off",
    "exp param2 v1, v10, v11, v0",
    "s_endpgm",
]
VERTEX_ID_ROLES = {3: ("base_vertex",)}

NAN = [
    *PROLOGUE,
    "s_load_dwordx4 s[8:11], s[2:3], null",
    "v_add_nc_u32_e32 v0, s0, v0",
    "s_movk_i32 s5, 0x8000",
    "s_load_dwordx4 s[12:15], s[4:5], null",
    "s_waitcnt lgkmcnt(0)",
    "buffer_load_dwordx4 v[1:4], v0, s[8:11], 0 idxen",
    "s_buffer_load_dwordx4 s[16:19], s[12:15], null",
    "v_mov_b32_e32 v5, 0x7f800001",
    "v_mov_b32_e32 v6, 0xffbfffff",
    "v_mov_b32_e32 v7, 0x7fc12345",
    "v_mov_b32_e32 v8, 1",
    "s_waitcnt lgkmcnt(0)",
    "v_mov_b32_e32 v9, s16",
    "v_mov_b32_e32 v10, s17",
    "v_mov_b32_e32 v11, s18",
    "v_mov_b32_e32 v12, s19",
    "s_waitcnt vmcnt(0)",
    "exp pos0 v1, v2, v3, v4 done vm",
    "exp param0 v5, v6, v7, v8",
    "exp param1 v9, v10, v11, v12",
    "s_endpgm",
]
NAN_ROLES = {2: ("descriptors", HIGH, {0: ("vsharp", 8)}), 3: ("base_vertex",),
             4: ("descriptors", HIGH, {0: ("constants",)})}
# Signaling and quiet NaNs with payloads and both signs, the largest and smallest subnormals, signed zero and infinity.
SPECIALS = [0x7f800001, 0xff800001, 0x7fbfffff, 0xffc00001, 0x7fc12345, 0xffffffff, 0x7fffffff, 0xff812345,
            0x00000001, 0x807fffff, 0x007fffff, 0x80000001, 0x80000000, 0x7f800000, 0xff800000, 0x00000000]

# Title memory: slot 0 crosses the 4 GiB line, slot 1 lies above it.
LOW_BASE = 0x1_0000_0000 - 0x200
HIGH_BASE = 0x2_0000_1000


def memory_for(seed):
    return Memory([(LOW_BASE, words_bytes(float_words(seed, 0x100))),
                   (HIGH_BASE, words_bytes(float_words(seed + 1, 0x100)))])


# --- draws -------------------------------------------------------------------------------------------------------------

def compile_vs(compiler, source, directory, name):
    hlsl, shader = directory / f"{name}.hlsl", directory / f"{name}.cso"
    hlsl.write_text(source, encoding="ascii")
    subprocess.run([compiler, "-Gis", "-T", "vs_6_0", "-E", "main", "-Fo", shader, hlsl], check=True)
    return shader


def run_sets(directory, compiler, renderer, backend, name, program, roles, sets, flaws, extra=None, body=None,
             vs_out_cntl=None, once=False):
    """Draw every set with its reference, then each wrong reference, which must be reported as a mismatch.
    A set is (constants, memory, record ids or (indices,), base vertex[, extras]), extras a dict with any of
    descriptors, push, instances, start_instance. `body` is the program the model runs when `program` is an NGG
    program (the vertex body inside its frame). `once`: each wrong reference is drawn only on the first set where it
    differs (families with many sets)."""
    source, layout = lower(program, roles, vs_out_cntl)
    stage = layout["stage"]
    body = program if body is None else body
    shader = compile_vs(compiler, source, directory, name)
    case = directory / f"{name}.case"
    draw = [renderer, backend, "--check-vertex-case", shader, case]
    separated = dict.fromkeys(map(frozenset, flaws), False)
    for constants, memory, ids, base, *more in sets:
        extras = more[0] if more else {}
        descriptors, push = extras.get("descriptors"), extras.get("push", ())
        instances, start = extras.get("instances", 1), extras.get("start_instance", 0)
        indices = ids[0] if isinstance(ids, tuple) else None
        records = list(indices) if indices is not None else list(range(ids))
        model = lambda flaw=(): Model(roles, constants, memory, flaw, descriptors, push, stage)  # noqa: E731
        expected, mask = outputs(model(), body, layout, records, base, instances, start)
        write = lambda e, m: case.write_bytes(case_file(  # noqa: E731
            len(records), base, layout["params"], constants, e, m, indices, memory.section(), descriptors,
            instances, start, push, distance_semantics(layout)))
        write(expected, mask)
        result = subprocess.run(draw, capture_output=True, text=True)
        sys.stdout.write(result.stdout)
        if result.returncode == 77:
            return 77
        if result.returncode:
            sys.stderr.write(result.stderr)
            raise AssertionError(f"{name}: the draw differs from the reference (base vertex {base:#x}, {len(records)} records)")
        for flaw in separated:
            if once and separated[flaw]:
                continue
            wrong, _ = outputs(model(flaw), body, layout, records, base, instances, start)
            if wrong == expected:
                continue
            separated[flaw] = True
            write(wrong, mask)
            result = subprocess.run(draw, capture_output=True, text=True)
            if result.returncode != 1 or "vertex_mismatch" not in result.stderr:
                raise AssertionError(f"{name}: a wrong reference ({sorted(flaw)}) escaped detection: {result.stderr}")
        if extra:
            extra(draw, case, write, expected, mask)
    missing = [sorted(f) for f, seen in separated.items() if not seen]
    assert not missing, f"{name}: these wrong references never differ from the right one: {missing}"
    return 0


def fetch_constants(v0, v1):
    words = [0] * 64
    words[8:12], words[12:16] = v0, v1
    return words


def draw_fetch(directory, compiler, renderer, backend):
    """Indexed vertex fetch through two runtime V#s: stride, num_records (OOB_SELECT 0 and 1), the offset check of
    mode 0 (offset:20 + 4 reaches the 24-byte stride), mode 1 reading past the stride into the next record, a base
    above 4 GiB, a base that crosses it, base-vertex wrap, an index buffer, and draws of different lengths."""
    memory = memory_for(11)
    cross = 0x1_0000_0000 - 8  # base + 12 * index crosses 4 GiB at index 1
    wide = lambda r0, r1: fetch_constants(vsharp(HIGH_BASE + 0x40, 24, r0, 0), vsharp(cross, 12, r1, 1))
    sets = [
        (wide(16, 16), memory, 7, 0),
        (wide(10, 8), memory, 9, 3),
        (wide(10, 8), memory, ([5, 0, 2, 2, 9, 1, 7],), 1),
        (wide(4, 4), memory, 4, 0xfffffffe),
    ]
    flaws = [{"base_ignored"}, {"instance_id"}, {"nostride"}, {"records_inclusive"}, {"swap_params"},
             {"no_offset_check"}, {"mode1_offset_checked"}]

    def controls(draw, case, write, expected, mask):
        # An `off` channel is undefined: garbage there passes while it is masked and fails once it is compared.
        off = 4 + 3  # record 0, param0.w
        assert mask[off] == 0
        garbage = list(expected)
        garbage[off] = 0x12345678
        write(garbage, mask)
        subprocess.run(draw, check=True, capture_output=True)
        checked_mask = list(mask)
        checked_mask[off] = M32
        write(garbage, checked_mask)
        result = subprocess.run(draw, capture_output=True, text=True)
        if result.returncode != 1 or "vertex_mismatch" not in result.stderr:
            raise AssertionError("A compared off channel with a wrong value escaped detection")
        # Malformed case files exit 2.
        good = case.read_bytes()
        header = struct.unpack_from("<16I", good)
        bad = {
            "wrong magic": struct.pack("<I", 0x12345678) + good[4:],
            "no records": good[:4] + struct.pack("<I", 0) + good[8:],
            "too many params": good[:16] + struct.pack("<I", 9) + good[20:],
            "truncated": good[:64 + 256 + 8],
            "unsorted params": good[:20] + struct.pack("<2I", header[6], header[5]) + good[28:],
            "bad memory": good + b"\0",
        }
        for why, data in bad.items():
            case.write_bytes(data)
            result = subprocess.run(draw, capture_output=True, text=True)
            if result.returncode != 2 or "Invalid case file" not in result.stderr:
                raise AssertionError(f"A malformed vertex case ({why}) gave exit {result.returncode}")
    return run_sets(directory, compiler, renderer, backend, "fetch", FETCH, FETCH_ROLES, sets, flaws, controls)


def draw_matrix(directory, compiler, renderer, backend):
    """A model-view-projection transform as RADV emits it: four V#s from one s_load_dwordx16, a constant buffer from a
    second descriptor pointer, s_buffer_load_dwordx16/x4, unfused v_mul/v_mac/v_mad/v_add, and a partial vmcnt(1) wait
    that reads the older load while the newer one is outstanding."""
    sets = []
    for seed, (count, base) in enumerate(((5, 0), (6, 2), (3, 0x40))):
        words = float_words(100 + seed, 20) + [0] * 44
        words[32:48] = (vsharp(HIGH_BASE, 12, 64, 0) + vsharp(LOW_BASE, 4, 1, 0) + vsharp(LOW_BASE, 4, 1, 0)
                        + vsharp(LOW_BASE + 0x40, 28, 48, 0))
        sets.append((words, memory_for(30 + seed), count, base))
    flaws = [{"fused"}, {"base_ignored"}, {"instance_id"}, {"nostride"}, {"swap_params"}]
    return run_sets(directory, compiler, renderer, backend, "matrix", MATRIX, MATRIX_ROLES, sets, flaws)


def draw_vertex_id(directory, compiler, renderer, backend):
    """A full-screen triangle and integer words built from the vertex id alone (no fetch): the base vertex as a root
    constant, its 32-bit wrap, raw integer words through the export, a TEXCOORD gap (param0 and param2), indexed draws."""
    sets = [([0] * 64, Memory([]), 6, 0), ([0] * 64, Memory([]), 5, 0x7ffffffe),
            ([0] * 64, Memory([]), ([0, 1, 2, 2, 1, 0, 7, 1000],), 5)]
    flaws = [{"base_ignored"}, {"instance_id"}, {"swap_params"}]
    return run_sets(directory, compiler, renderer, backend, "vertex_id", VERTEX_ID, VERTEX_ID_ROLES, sets, flaws)


def draw_nan(directory, compiler, renderer, backend):
    """NaN payloads, subnormals, signed zero and infinities stored through asfloat to SV_Position and TEXCOORDn and
    captured by stream output: from fetched memory words, from literal moves and from constant-buffer words. The
    design (docs/design/vertex-stage.md, Outputs) needs this to hold bit for bit on both adapters; if it fails, raw
    words that reach an export must become uint nointerpolation outputs."""
    memory = Memory([(HIGH_BASE, words_bytes(SPECIALS * 4))])
    sets = []
    for count, base, constants in ((4, 0, (0xff800001, 0x807fffff, 0x80000000, 0xffffffff)),
                                   (3, 1, (0x7fa00000, 0x00000001, 0xff800000, 0x7fc00000))):
        words = [0] * 64
        words[0:4] = constants
        words[8:12] = vsharp(HIGH_BASE, 16, 16, 0)
        sets.append((words, memory, count, base))
    flaws = [{"canonical_nan"}, {"quiet_nan"}, {"flush_denormal"}, {"base_ignored"}]
    return run_sets(directory, compiler, renderer, backend, "nan", NAN, NAN_ROLES, sets, flaws)


# --- typed fetch ------------------------------------------------------------------------------------------------------

TYPED = [
    *PROLOGUE,
    "s_load_dwordx16 s[8:23], s[2:3], null",
    "v_add_nc_u32_e32 v0, s0, v0",
    "s_waitcnt lgkmcnt(0)",
    "buffer_load_format_xyzw v[4:7], v0, s[8:11], 0 idxen",
    "buffer_load_format_xyzw v[8:11], v0, s[12:15], 0 idxen offset:4",
    "buffer_load_format_xy v[12:13], v0, s[16:19], 0 idxen",
    "tbuffer_load_format_xyzw v[14:17], v0, s[20:23], 0 format:[BUF_FMT_2_10_10_10_SNORM] idxen",
    "tbuffer_load_format_xyz v[18:20], v0, s[20:23], 0 format:[BUF_FMT_10_11_11_FLOAT] idxen offset:4",
    "tbuffer_load_format_x v21, v0, s[20:23], 0 format:[BUF_FMT_16_FLOAT] idxen offset:8",
    "s_waitcnt vmcnt(0)",
    "exp pos0 v4, v5, v6, v7 done vm",
    "exp param0 v8, v9, v10, v11",
    "exp param1 v12, v13, v14, v15",
    "exp param2 v16, v17, v18, v19",
    "exp param3 v20, v21, v20, v21",
    "s_endpgm",
]
TYPED_ROLES = {2: ("descriptors", HIGH, {0: ("vsharp", 8), 16: ("vsharp", 12), 32: ("vsharp", 16),
                                         48: ("vsharp", 20)}), 3: ("base_vertex",)}
TYPED_BASE = HIGH_BASE + 0x40
# Element bit patterns that reach the edges of every conversion: zero, all ones, the most negative SNORM value, its
# neighbour, half and small-float subnormals, infinities and NaNs, rounding ties.
TYPED_SPECIALS = [0x00000000, 0xffffffff, 0x80008000, 0x81818181, 0x7fff7fff, 0x00010001, 0x7c00fc00, 0x7e017c01,
                  0x3c00bc00, 0x03ff8001, 0x40000000, 0xc0000001, 0x0000ffff, 0xaaaa5555, 0x7f800001, 0x00800080]


def typed_memory(seed):
    """Title memory for the typed family: the specials, then a fixed pseudo-random byte sequence."""
    state, data = seed, bytearray(words_bytes(TYPED_SPECIALS))
    while len(data) < 0x400:
        state = (state * 1103515245 + 12345) & 0x7fffffff
        data.append(state >> 16 & 0xff)
    return Memory([(HIGH_BASE, bytes(data))])


def typed_sharp(base, stride, records, select, fmt, sel=4 | 5 << 3 | 6 << 6 | 7 << 9):
    return [base & M32, (base >> 32) | stride << 16, records, 1 << 24 | select << 28 | fmt << 12 | sel]


def typed_sets():
    """One set per pair of formats: V# 1 (xyzw, offset 4, a DST_SEL swizzle with the 0 and 1 selects in some sets) and
    V# 2 (xy). Together they name every gfx10 format; strides are odd multiples of 2 where the element allows, so
    four-byte elements are read unaligned; num_records cuts the last record of V# 1 in some sets. V# 0 (positions)
    is 32_32_32_32_FLOAT and V# 3 is read by the tbuffer loads in their instruction formats."""
    sets, formats = [], list(range(1, 78))
    swizzles = [4 | 5 << 3 | 6 << 6 | 7 << 9, 7 | 6 << 3 | 5 << 6 | 4 << 9, 5 | 0 << 3 | 1 << 6 | 4 << 9]
    for n in range(0, len(formats), 2):
        a, b = formats[n], formats[(n + 1) % len(formats)]
        size_a = sum(ufmt_layout(a)[0]) // 8
        size_b = sum(ufmt_layout(b)[0]) // 8
        stride_a = size_a + 4 + (2 if n % 4 else 0)
        stride_b = size_b + (2 if size_b >= 4 and n % 4 == 2 else 0)
        words = [0] * 64
        words[8:12] = typed_sharp(TYPED_BASE, 16, 8, 0, 77)
        words[12:16] = typed_sharp(TYPED_BASE + 0x80 + n, stride_a, 4 if n % 6 == 0 else 8, 0, a,
                                   swizzles[(n // 2) % 3])
        words[16:20] = typed_sharp(TYPED_BASE + 0x100 + 3 * n, stride_b, 8, 1, b)
        words[20:24] = typed_sharp(TYPED_BASE + 0x1c0, 12, 8, 0, 0)
        sets.append((words, typed_memory(90 + n), 5, n % 3))
    return sets


TYPED_FLAWS = [{"norm_truncate"}, {"snorm_unclamped"}, {"reversed_components"}, {"w_default_swapped"}, {"no_dst_sel"},
               {"format_ignored"}, {"small_float_flush"}, {"base_ignored"}]


def draw_typed(directory, compiler, renderer, backend):
    """Typed vertex fetch: buffer_load_format_* through V#s of every gfx10 unified format (component layout, UNORM,
    SNORM, scaled, integer and 16-, 11- and 10-bit float conversion, the missing-component fill, DST_SEL, range rules)
    and tbuffer_load_format_* in instruction formats, against the Python conversions above."""
    return run_sets(directory, compiler, renderer, backend, "typed", TYPED, TYPED_ROLES, typed_sets(), TYPED_FLAWS,
                    once=True)


# --- cards V-2 and V-3 -------------------------------------------------------------------------------------------------

def ngg_registers(program):
    """A legacy-VS program with the registers it would have in an NGG wave (docs/design/vertex-stage.md, Inputs):
    VGPRs move up by 5 (v0 vertex id -> v5, v3 instance id -> v8, and the unassigned v1/v2 -> v6/v7), entry user SGPRs
    s2..s7 move to s8..s13 (user SGPRs start at s8 after the merged wave's system SGPRs), and temporaries s8 and up move
    up by 8, which keeps every SGPR tuple aligned. s0 and s1 stay temporaries."""
    def sgpr(n):
        return n if n < 2 else n + 6 if n < 8 else n + 8

    def one(line):
        line = re.sub(r"\bv\[(\d+):(\d+)\]", lambda m: f"v[{int(m[1]) + 5}:{int(m[2]) + 5}]", line)
        line = re.sub(r"(?<![\w\[:])v(\d+)\b", lambda m: f"v{int(m[1]) + 5}", line)
        line = re.sub(r"\bs\[(\d+):(\d+)\]", lambda m: f"s[{sgpr(int(m[1]))}:{sgpr(int(m[2]))}]", line)
        return re.sub(r"(?<![\w\[:])s(\d+)\b", lambda m: f"s{sgpr(int(m[1]))}", line)
    return [one(line) for line in program]


def ngg_roles(roles):
    return {number + 6: role for number, role in roles.items()}


def ngg_frame(body, order="prim"):
    """RADV's NGG passthrough frame around a vertex body (the shape of every NGG dump of the corpus), with the primitive
    export first (order "prim", 237 corpus shaders) or after the body ("vertex", 7)."""
    body = [line for line in body if not line.startswith("s_setprio")]
    head = ["s_setprio 3", "s_barrier", "s_and_b32 s0, s3, 0xf000000", "s_cbranch_scc1 BB3", "BB1:",
            "s_bfe_u32 s0, s2, 0x90016", "s_lshl_b32 s0, s0, 12", "s_bfe_u32 s2, s2, 0x9000c", "s_or_b32 m0, s0, s2",
            "s_sendmsg sendmsg(MSG_GS_ALLOC_REQ)", "BB3:"]
    if order == "prim":
        return head + ["s_lshl_b32 s0, s3, 8", "s_bfe_u64 exec, -1, s0", "s_cbranch_execz BB9", "BB4:",
                       "exp prim v0, off, off, off done", "BB9:", "s_pack_ll_b32_b16 s3, 0, s3",
                       "s_waitcnt expcnt(0)", "s_bfe_u64 exec, -1, s3", "s_cbranch_execz BB15", "BB10:",
                       *body, "BB15:", "s_endpgm"]
    return head + ["s_pack_ll_b32_b16 s0, 0, s3", "s_bfe_u64 exec, -1, s0", "s_cbranch_execz BB15", "BB4:",
                   *body, "BB15:", "s_lshl_b32 s3, s3, 8", "s_waitcnt expcnt(0)", "s_bfe_u64 exec, -1, s3",
                   "s_cbranch_execz BB21", "BB16:", "exp prim v0, off, off, off done", "BB21:", "s_endpgm"]


def ngg_program(program, order="prim"):
    """(full NGG program, its vertex body without s_endpgm framing for the model)."""
    body = ngg_registers(program)
    return ngg_frame([line for line in body if line != "s_endpgm"], order), body


NGG_FETCH, NGG_FETCH_BODY = ngg_program(FETCH, "prim")
NGG_MATRIX, NGG_MATRIX_BODY = ngg_program(MATRIX, "vertex")
NGG_VERTEX_ID, NGG_VERTEX_ID_BODY = ngg_program(VERTEX_ID, "prim")

# Instance id, start instance, inline push words, a uniform block read both by s_buffer_load (b0) and by an offen
# buffer load indexed by the instance (its V# words are descriptor words 8..11), and global loads through a 64-bit
# address held in two push words (buffer device address), in both the saddr and the 64-bit VGPR form.
INSTANCE = [
    "s_setprio 3",
    "s_mov_b32 s0, s3",
    "s_movk_i32 s3, 0x8000",
    "s_load_dwordx4 s[12:15], s[2:3], null",
    "s_mov_b32 s2, s5",
    "s_load_dwordx4 s[16:19], s[2:3], null",
    "v_add_nc_u32_e32 v3, s4, v3",
    "v_lshlrev_b32_e32 v4, 4, v3",
    "v_add_nc_u32_e32 v0, s0, v0",
    "s_waitcnt lgkmcnt(0)",
    "buffer_load_dwordx4 v[5:8], v4, s[16:19], 0 offen offset:32",
    "buffer_load_dwordx2 v[9:10], v0, s[12:15], 0 idxen",
    "s_buffer_load_dwordx4 s[20:23], s[16:19], null",
    "v_mov_b32_e32 v11, s6",
    "v_mov_b32_e32 v12, s7",
    "v_lshlrev_b32_e32 v13, 3, v0",
    "global_load_dwordx2 v[14:15], v13, s[6:7] offset:8",
    "global_load_dword v16, v[11:12], off offset:4",
    "s_waitcnt lgkmcnt(0)",
    "v_mov_b32_e32 v17, s6",
    "v_xor_b32_e32 v18, s20, v3",
    "s_waitcnt vmcnt(0)",
    "exp pos0 v5, v6, v7, v8 done vm",
    "exp param0 v9, v10, v14, v15",
    "exp param1 v16, v17, v18, v3",
    "s_endpgm",
]
INSTANCE_ROLES = {2: ("descriptors", HIGH, {0: ("vsharp", 0)}), 3: ("base_vertex",), 4: ("start_instance",),
                  5: ("descriptors", HIGH, {0: ("constants", 8)}), 6: ("inline", 0), 7: ("inline", 1)}
NGG_INSTANCE, NGG_INSTANCE_BODY = ngg_program(INSTANCE, "prim")

# pos1 and pos2 as distance vectors: distances 0 and 2 clip (1 is exported but not enabled, 3 is off), 4 and 5 cull.
DISTANCE = [
    "s_setprio 3",
    "v_add_nc_u32_e32 v1, s3, v0",
    "v_cvt_f32_ubyte0_e32 v2, v1",
    "v_mov_b32_e32 v3, 1.0",
    "v_sub_f32_e32 v4, v2, v3",
    "v_mov_b32_e32 v5, 0",
    "v_mul_f32_e32 v6, 0.5, v2",
    "exp pos0 v2, v3, v5, v3 vm",
    "exp pos1 v4, v6, v2, off",
    "exp pos2 v6, v4, v3, v2 done",
    "exp param0 v1, v2, off, off",
    "s_endpgm",
]
DISTANCE_ROLES = {3: ("base_vertex",)}
DISTANCE_CNTL = 0b101 | 0b110000 << 8 | 1 << 22 | 1 << 23


def instance_set(seed, count, base, instances, start, records):
    """Title memory: a vertex buffer and the uniform block at HIGH_BASE, the global data at LOW_BASE (it crosses
    4 GiB). b0 holds the uniform block's first 64 words, as the runtime keeps it equal to that memory."""
    memory = memory_for(seed)
    block = HIGH_BASE + 0x100
    descriptors = [0] * 64
    descriptors[0:4] = vsharp(HIGH_BASE, 8, 20, 0)
    descriptors[8:12] = vsharp(block, 0, records, 3)  # raw: offset < num_records
    constants = [memory.word(block + 4 * k) for k in range(64)]
    pointer = LOW_BASE + 0x1f0
    push = [pointer & M32, pointer >> 32, 0x5eed]
    return (constants, memory, count, base,
            {"descriptors": descriptors, "push": push, "instances": instances, "start_instance": start})


INSTANCE_SETS = [instance_set(50, 4, 0, 3, 5, 144), instance_set(51, 3, 7, 2, 0, 0x80), instance_set(52, 5, 2, 1, 6, 0x100)]
INSTANCE_FLAWS = [{"base_ignored"}, {"start_ignored"}, {"instance_id"}, {"vertex_for_instance"}, {"push_shifted"},
                  {"swap_params"}, {"nostride"}]


def draw_ngg(directory, compiler, renderer, backend):
    """The V-1 programs inside RADV's NGG passthrough frame (card V-2): the frame dropped, v5 as the vertex id, both
    region orders. The references are the legacy model run on the vertex body."""
    memory = memory_for(11)
    cross = 0x1_0000_0000 - 8
    wide = lambda r0, r1: fetch_constants(vsharp(HIGH_BASE + 0x40, 24, r0, 0), vsharp(cross, 12, r1, 1))  # noqa: E731
    code = run_sets(directory, compiler, renderer, backend, "ngg_fetch", NGG_FETCH, ngg_roles(FETCH_ROLES),
                    [(wide(16, 16), memory, 7, 0), (wide(10, 8), memory, ([5, 0, 2, 2, 9, 1, 7],), 1)],
                    [{"base_ignored"}, {"nostride"}, {"records_inclusive"}, {"swap_params"}], body=NGG_FETCH_BODY)
    if code:
        return code
    sets = []
    for seed, (count, base) in enumerate(((5, 0), (6, 2))):
        words = float_words(100 + seed, 20) + [0] * 44
        words[32:48] = (vsharp(HIGH_BASE, 12, 64, 0) + vsharp(LOW_BASE, 4, 1, 0) + vsharp(LOW_BASE, 4, 1, 0)
                        + vsharp(LOW_BASE + 0x40, 28, 48, 0))
        sets.append((words, memory_for(30 + seed), count, base))
    code = run_sets(directory, compiler, renderer, backend, "ngg_matrix", NGG_MATRIX, ngg_roles(MATRIX_ROLES), sets,
                    [{"fused"}, {"base_ignored"}, {"swap_params"}], body=NGG_MATRIX_BODY)
    if code:
        return code
    return run_sets(directory, compiler, renderer, backend, "ngg_vertex_id", NGG_VERTEX_ID, ngg_roles(VERTEX_ID_ROLES),
                    [([0] * 64, Memory([]), 6, 0), ([0] * 64, Memory([]), ([0, 1, 2, 2, 1, 0, 7, 1000],), 5)],
                    [{"base_ignored"}, {"swap_params"}], body=NGG_VERTEX_ID_BODY)


def draw_instance(directory, compiler, renderer, backend):
    """Card V-3: instanced draws with a start instance (root constant), the instance id in v3 (and v8 in the NGG
    form), inline push words, an offen load out of a uniform block (num_records bounds the last instance), and global
    loads through a 64-bit push-word address that crosses 4 GiB."""
    code = run_sets(directory, compiler, renderer, backend, "instance", INSTANCE, INSTANCE_ROLES, INSTANCE_SETS,
                    INSTANCE_FLAWS)
    if code:
        return code
    return run_sets(directory, compiler, renderer, backend, "ngg_instance", NGG_INSTANCE, ngg_roles(INSTANCE_ROLES),
                    INSTANCE_SETS, INSTANCE_FLAWS, body=NGG_INSTANCE_BODY)


def draw_distance(directory, compiler, renderer, backend):
    """Card V-3: pos1 and pos2 as SV_ClipDistance0 and SV_CullDistance0 under PA_CL_VS_OUT_CNTL, captured by stream
    output; channels the state does not enable are undefined (masked)."""
    sets = [([0] * 64, Memory([]), 6, 0), ([0] * 64, Memory([]), 4, 9)]
    return run_sets(directory, compiler, renderer, backend, "distance", DISTANCE, DISTANCE_ROLES, sets,
                    [{"base_ignored"}, {"swap_distances"}], vs_out_cntl=DISTANCE_CNTL)


# Card V-4: v_sin_f32 and v_cos_f32 (the argument in revolutions) and the carry-in adds and subtractions. Every
# transcendental result is scaled and rounded to an integer before it is exported, at angles (n + 0.5) / 16 revolutions
# whose scaled sine and cosine lie at least 0.05 from a rounding tie, so the result does not depend on the last bits of
# the desktop's sin and cos.
TRIG = [
    "s_setprio 3",
    "v_add_nc_u32_e32 v1, s3, v0",
    "v_cvt_f32_ubyte0_e32 v2, v1",
    "v_add_f32_e32 v3, 0.5, v2",
    "v_mul_f32_e32 v4, 0x3d800000, v3",
    "v_sin_f32_e32 v5, v4",
    "v_cos_f32_e32 v6, v4",
    "v_mul_f32_e32 v7, 0x41000000, v5",
    "v_rndne_f32_e32 v7, v7",
    "v_mul_f32_e32 v8, 0x41000000, v6",
    "v_rndne_f32_e32 v8, v8",
    "v_sin_f32_e64 v9, v4 div:2",
    "v_mul_f32_e32 v9, 0x41800000, v9",
    "v_rndne_f32_e32 v9, v9",
    "v_cos_f32_e64 v10, v4 div:2",
    "v_mul_f32_e32 v10, 0x41800000, v10",
    "v_rndne_f32_e32 v10, v10",
    "v_mov_b32_e32 v11, 1.0",
    "exp pos0 v7, v8, v9, v11 done vm",
    "exp param0 v10, v1, off, off",
    "s_endpgm",
]
TRIG_ROLES = {3: ("base_vertex",)}

# 64-bit style limbs from the vertex id: v2 and v3 hold bit 0 and bit 1 of the id in bit 31, so v2 + v3 carries when
# both are set, and v3 - v2 borrows when only bit 1 is. The carry-in forms run in VCC and in a lane-mask SGPR, as the
# add, subtract and reverse subtract, each reading a mask the previous instruction wrote.
CARRY = [
    "s_setprio 3",
    "v_add_nc_u32_e32 v1, s3, v0",
    "v_lshlrev_b32_e32 v2, 31, v1",
    "v_lshlrev_b32_e32 v3, 30, v1",
    "v_mov_b32_e32 v5, -1",
    "v_mov_b32_e32 v6, 0",
    "v_add_co_u32 v4, vcc_lo, v2, v3",
    "v_add_co_ci_u32_e32 v7, vcc_lo, v5, v6, vcc_lo",
    "v_add_co_ci_u32_e32 v8, vcc_lo, 0, v6, vcc_lo",
    "v_sub_co_u32 v9, vcc_lo, v3, v2",
    "v_sub_co_ci_u32_e32 v10, vcc_lo, v1, v5, vcc_lo",
    "v_sub_co_u32 v13, vcc_lo, v3, v2",
    "v_subrev_co_ci_u32_e32 v11, vcc_lo, v1, v5, vcc_lo",
    "v_add_co_u32 v12, s10, v2, v3",
    "v_add_co_ci_u32_e64 v14, s12, v1, v6, s10",
    "v_add_co_ci_u32_e64 v15, s10, v5, v6, s12",
    "v_subrev_co_u32 v16, s12, v3, v2",
    "v_sub_co_ci_u32_e64 v17, s10, v6, v6, s12",
    "exp pos0 v4, v7, v8, v9 done vm",
    "exp param0 v10, v11, v12, v13",
    "exp param1 v14, v15, v16, v17",
    "s_endpgm",
]
CARRY_ROLES = {3: ("base_vertex",)}


# Constants past the first 64 words: the window grows to the highest word read (params[17] and params[65] here),
# up to the 4096 uint4 of a D3D12 constant buffer. Words 72 to 75 and 260 to 263 are read as a uint4 each.
WIDE = [
    "s_setprio 3",
    "s_mov_b32 s0, s3",
    "s_movk_i32 s3, 0x8000",
    "v_add_nc_u32_e32 v0, s0, v0",
    "s_movk_i32 s5, 0x8000",
    "s_load_dwordx4 s[12:15], s[4:5], null",
    "s_waitcnt lgkmcnt(0)",
    "s_buffer_load_dwordx4 s[16:19], s[12:15], 0x120",
    "s_buffer_load_dwordx4 s[20:23], s[12:15], 0x410",
    "s_waitcnt lgkmcnt(0)",
    "v_cvt_f32_ubyte0_e32 v1, v0",
    "v_mov_b32_e32 v2, s16",
    "v_mov_b32_e32 v3, s19",
    "v_add_nc_u32_e32 v4, s20, v0",
    "v_add_nc_u32_e32 v5, s23, v4",
    "v_mov_b32_e32 v6, s17",
    "v_mov_b32_e32 v7, s22",
    "exp pos0 v1, v2, v3, v4 done vm",
    "exp param0 v5, v6, v7, v0",
    "s_endpgm",
]
WIDE_ROLES = {3: ("base_vertex",), 4: ("descriptors", HIGH, {0: ("constants",)})}


def wide_constants(seed, words):
    state = [0] * words
    for k in range(words):
        seed = (seed * 6364136223846793005 + 1442695040888963407) % (1 << 64)
        state[k] = (seed >> 32) | 1
    return state


def draw_wide(directory, compiler, renderer, backend):
    """s_buffer_load words past the first 64 (byte offsets 0x120 and 0x410): the constant window is sized from the
    highest word read. The wrong reference reads every word past 64 as zero."""
    sets = [(wide_constants(5, 272), Memory([]), 6, 0), (wide_constants(9, 1024), Memory([]), 5, 3)]
    flaws = [{"window_64"}, {"base_ignored"}]
    return run_sets(directory, compiler, renderer, backend, "wide", WIDE, WIDE_ROLES, sets, flaws)


# s_buffer_load at a run-time byte offset made from push words (the shape of the corpus's cascade depth pass, which
# indexes a matrix array by a push-constant cascade index): 64 * push0 | (push1 & 3), x4 and x2 at offset:0x3c. A
# program with a run-time constant offset declares the whole 64 KiB binding (params[4096]), and the case binds all of it.
DYNAMIC = [
    "s_setprio 3",
    "s_mov_b32 s0, s3",
    "s_movk_i32 s3, 0x8000",
    "v_add_nc_u32_e32 v0, s0, v0",
    "s_movk_i32 s5, 0x8000",
    "s_load_dwordx4 s[12:15], s[4:5], null",
    "s_lshl_b32 s8, s6, 6",
    "s_and_b32 s9, s7, 3",
    "s_or_b32 s8, s8, s9",
    "s_waitcnt lgkmcnt(0)",
    "s_buffer_load_dwordx4 s[16:19], s[12:15], s8",
    "s_buffer_load_dwordx2 s[20:21], s[12:15], s8 offset:0x3c",
    "s_waitcnt lgkmcnt(0)",
    "v_cvt_f32_ubyte0_e32 v1, v0",
    "v_add_nc_u32_e32 v2, s16, v0",
    "v_mov_b32_e32 v3, s17",
    "v_mov_b32_e32 v4, s18",
    "v_xor_b32_e32 v5, s19, v0",
    "v_mov_b32_e32 v6, s20",
    "v_mov_b32_e32 v7, s21",
    "exp pos0 v1, v2, v3, v4 done vm",
    "exp param0 v5, v6, v7, v0",
    "s_endpgm",
]
DYNAMIC_ROLES = {3: ("base_vertex",), 4: ("descriptors", HIGH, {0: ("constants",)}), 6: ("inline", 0),
                 7: ("inline", 1)}


def draw_dynamic(directory, compiler, renderer, backend):
    """s_buffer_load_dwordx4/x2 at 64 * push0 | (push1 & 3) (+0x3c): the low bits ignored, the last dwords of the
    64 KiB binding read, past it 0 dword by dword. Wrong references: the offset ignored, the offset wrapped at 64 KiB
    in place of reading 0, the low bits kept in the range check."""
    words = wide_constants(7, 16384)
    sets = [(words, Memory([]), 4, 0, {"push": [3, 2]}), (words, Memory([]), 3, 5, {"push": [1022, 1]}),
            (words, Memory([]), 3, 1, {"push": [1023, 3]}), (words, Memory([]), 2, 2, {"push": [1024, 1]}),
            (words, Memory([]), 2, 0, {"push": [0x4000001, 0]})]
    flaws = [{"dyn_ignored"}, {"dyn_wrap"}, {"dyn_unmasked"}, {"base_ignored"}]
    return run_sets(directory, compiler, renderer, backend, "dynamic", DYNAMIC, DYNAMIC_ROLES, sets, flaws)


def draw_trig(directory, compiler, renderer, backend):
    """Card V-4: v_sin_f32 and v_cos_f32 (e32, and e64 with the div:2 output modifier) on angles in revolutions, each
    result scaled and rounded to an integer before export (see TRIG)."""
    sets = [([0] * 64, Memory([]), 16, 0), ([0] * 64, Memory([]), 8, 3)]
    flaws = [{"sin_cos_swapped"}, {"radians"}, {"div2_ignored"}, {"base_ignored"}]
    return run_sets(directory, compiler, renderer, backend, "trig", TRIG, TRIG_ROLES, sets, flaws)


def draw_carry(directory, compiler, renderer, backend):
    """Card V-4: v_add_co_ci_u32, v_sub_co_ci_u32 and v_subrev_co_ci_u32 reading the carry or borrow of the previous
    instruction, in VCC and in an SGPR lane mask, with ids that wrap the 32-bit base-vertex add."""
    sets = [([0] * 64, Memory([]), 8, 0), ([0] * 64, Memory([]), 6, 0x7ffffffe), ([0] * 64, Memory([]), 5, 0xfffffffd)]
    flaws = [{"no_carry_in"}, {"no_borrow"}, {"subrev_swapped"}, {"base_ignored"}]
    return run_sets(directory, compiler, renderer, backend, "carry", CARRY, CARRY_ROLES, sets, flaws)


DRAW_FAMILIES = {"fetch": draw_fetch, "matrix": draw_matrix, "vertex_id": draw_vertex_id, "nan": draw_nan,
                 "ngg": draw_ngg, "instance": draw_instance, "distance": draw_distance, "trig": draw_trig,
                 "carry": draw_carry, "wide": draw_wide, "dynamic": draw_dynamic, "typed": draw_typed}
PROGRAMS = ((FETCH, FETCH_ROLES, None), (MATRIX, MATRIX_ROLES, None), (VERTEX_ID, VERTEX_ID_ROLES, None),
            (NAN, NAN_ROLES, None), (NGG_FETCH, ngg_roles(FETCH_ROLES), None),
            (NGG_MATRIX, ngg_roles(MATRIX_ROLES), None), (NGG_VERTEX_ID, ngg_roles(VERTEX_ID_ROLES), None),
            (INSTANCE, INSTANCE_ROLES, None), (NGG_INSTANCE, ngg_roles(INSTANCE_ROLES), None),
            (DISTANCE, DISTANCE_ROLES, DISTANCE_CNTL), (TRIG, TRIG_ROLES, None), (CARRY, CARRY_ROLES, None),
            (WIDE, WIDE_ROLES, None), (DYNAMIC, DYNAMIC_ROLES, None), (TYPED, TYPED_ROLES, None))


# --- controls (no DXC, no GPU) -----------------------------------------------------------------------------------------

def check_reference_arithmetic():
    # round_f32 against the host's binary32 rounding where a double holds the exact result: products and sums of two
    # binary32 values (a sum's double rounding is innocuous because 53 >= 2 * 24 + 2).
    words = float_words(7, 400) + [0x3f800001, 0x4b7fffff, 0x00800000, 0x7f7fffff, 0x33800000]
    for a, b in zip(words, words[1:]):
        fa, fb = (struct.unpack("<f", struct.pack("<I", w))[0] for w in (a, b))
        for exact, host in ((f32_fraction(a) * f32_fraction(b), fa * fb), (f32_fraction(a) + f32_fraction(b), fa + fb)):
            try:
                want = struct.unpack("<I", struct.pack("<f", host))[0]
            except OverflowError:
                want = 0x7f800000 | (0x80000000 if host < 0 else 0)
            assert round_f32(exact, negative_zero=struct.pack("<f", host)[3] & 0x80 != 0) == want, (hex(a), hex(b))
    assert round_f32(Fraction(1, 1 << 149)) == 1 and round_f32(Fraction(1, 1 << 150)) == 0
    assert round_f32(Fraction(3, 1 << 150)) == 2  # tie between 1 and 2 quanta goes to even
    assert f32_mad(0x00400000, 0x3f800000, 0x3f800000) == 0x3f800000  # a subnormal operand is flushed
    # 1 + 2^-23 squared, minus (1 + 2^-22): the unfused product loses the 2^-46 term that the fused one keeps.
    one_ulp, two_ulp = 0x3f800001, 0x3f800002
    assert f32_mad(one_ulp, one_ulp, two_ulp ^ 0x80000000) == 0
    assert f32_mad(one_ulp, one_ulp, two_ulp ^ 0x80000000, fused=True) == 0x28800000


def check_translation_shape():
    source, layout = lower(VERTEX_ID, VERTEX_ID_ROLES)
    assert layout["params"] == [0, 2] and layout["channels"]["param0"] == (True, True, False, False), layout
    struct_text = source[source.index("struct VertexOutput"):source.index("};", source.index("struct VertexOutput"))]
    order = re.findall(r": (\w+);", struct_text)
    assert order == ["TEXCOORD0", "SV_Position", "TEXCOORD2"], order
    assert "VertexOutput main(uint vid : SV_VertexID)" in source and layout["stage"] == "legacy"
    assert "register(b2) { uint base_vertex; uint start_instance; }" in source
    assert "(base_vertex + vid)" in source and "title_memory" not in source and "Texture2D" not in source
    assert "SV_Target" not in source and "params[" not in source and "SV_InstanceID" not in source
    source, layout = lower(FETCH, FETCH_ROLES)
    assert "vsharp_words[2].x, vsharp_words[2].y, vsharp_words[2].z, vsharp_words[2].w" in source
    assert "buffer_load32(" in source and "uint4 vsharp_words[16]" in source and "params[" not in source
    assert "title_memory" in source and layout["params"] == [0, 1]
    source, _ = lower(MATRIX, MATRIX_ROLES)
    assert "mad32(" in source and "asfloat(params[0].x)" in source
    # The NGG form lowers to the same HLSL as the legacy program with its registers renamed: the frame is dropped.
    for legacy, roles, ngg in ((FETCH, FETCH_ROLES, NGG_FETCH), (MATRIX, MATRIX_ROLES, NGG_MATRIX),
                               (INSTANCE, INSTANCE_ROLES, NGG_INSTANCE)):
        source, layout = lower(ngg, ngg_roles(roles))
        assert layout["stage"] == "ngg" and "MSG_GS" not in source
        assert layout["params"] == lower(legacy, roles)[1]["params"]
    source, layout = lower(INSTANCE, INSTANCE_ROLES)
    assert "VertexOutput main(uint vid : SV_VertexID, uint iid : SV_InstanceID)" in source and layout["instance_id"]
    assert "register(b3) { uint4 push_words[8]; }" in source and "global_load32(" in source
    assert "(start_instance + iid)" in source
    source, layout = lower(DISTANCE, DISTANCE_ROLES, DISTANCE_CNTL)
    assert "float4 pos1 : SV_ClipDistance0;" in source and "float4 pos2 : SV_CullDistance0;" in source
    assert layout["channels"]["pos1"] == (True, False, True, False), layout
    assert layout["channels"]["pos2"] == (True, True, False, False), layout
    # Every hand-written program goes through the same form registry as the pixel stage; record the accepted forms.
    for program, roles, cntl in PROGRAMS:
        lower(program, roles, cntl)


def check_refusals():
    base = list(FETCH)
    end = base.index("exp pos0 v4, v5, v6, v7 done vm")

    def body(*lines, at=end):
        return base[:at] + list(lines) + base[at:]

    refusals = [
        # Later cards.
        (body("s_cbranch_scc0 _L0", "_L0:"), FETCH_ROLES, "card V-5"),
        (body("s_getpc_b64 s[20:21]"), FETCH_ROLES, "V-5"),
        (body("image_sample_lz v20, v[4:5], s[16:23], s[24:27] dmask:0x1 dim:SQ_RSRC_IMG_2D"), FETCH_ROLES, "V-5"),
        (body("v_mov_b32_e32 v20, v1"), FETCH_ROLES, "entry VGPR v1"),
        (body("v_mov_b32_e32 v20, v2"), FETCH_ROLES, "entry VGPR v2"),
        (body("exp pos1 v4, off, off, off done"), FETCH_ROLES, "PA_CL_VS_OUT_CNTL"),
        (body("v_mul_f32_e32 v20, v3, v4"), FETCH_ROLES, None),  # v3 holds the instance id now: accepted below
        # Typed fetch translates (family typed); its d16 forms, a missing or invalid tbuffer format and typed stores do not.
        (body("buffer_load_format_d16_xyzw v[20:21], v0, s[8:11], 0 idxen"), FETCH_ROLES, "d16 typed vertex fetch"),
        (body("tbuffer_load_format_d16_x v20, v0, s[8:11], 0 format:[BUF_FMT_16_FLOAT] idxen"), FETCH_ROLES, "d16"),
        (body("tbuffer_load_format_x v20, v0, s[8:11], 0 idxen"), FETCH_ROLES, "format: field"),
        (body("tbuffer_load_format_x v20, v0, s[8:11], 0 format:[BUF_FMT_INVALID] idxen"), FETCH_ROLES, "not lowered"),
        (body("tbuffer_load_format_x v20, v0, s[8:11], 0 format:78 idxen"), FETCH_ROLES, "not lowered"),
        (body("tbuffer_store_format_x v4, v0, s[8:11], 0 format:[BUF_FMT_32_UINT] idxen"), FETCH_ROLES, "side effects"),
        (body("buffer_store_format_x v4, v0, s[8:11], 0 idxen"), FETCH_ROLES, "side effects"),
        (body("flat_load_dword v20, v[4:5]"), FETCH_ROLES, "flat and scratch"),
        (body("global_store_dword v[4:5], v6, off"), FETCH_ROLES, "side effects"),
        ([*base], {**FETCH_ROLES, 5: ("inline",)}, "push-constant word"),
        ([*base], {**FETCH_ROLES, 5: ("inline", 32)}, "push-constant word"),
        ([*base], {**FETCH_ROLES, 5: ("inline", 1), 6: ("inline", 1)}, "Push-constant word 1"),
        ([*base], {**FETCH_ROLES, 5: ("start_instance",), 6: ("start_instance",)}, "At most one"),
        ([*base], {**FETCH_ROLES, 5: ("inline_vsharp",)}, "unknown role"),
        # NGG frame and lane-cooperative operations.
        (["s_barrier", *base], FETCH_ROLES, "NGG"),
        (body("s_sendmsg sendmsg(MSG_GS_ALLOC_REQ)"), FETCH_ROLES, "NGG"),
        (body("exp prim v0, off, off, off done"), FETCH_ROLES, "NGG"),
        (body("ds_read_b32 v20, v0"), FETCH_ROLES, "lane-cooperative"),
        (body("v_mbcnt_lo_u32_b32 v20, -1, 0"), FETCH_ROLES, "lane-cooperative"),
        (body("v_readfirstlane_b32 s20, v0"), FETCH_ROLES, "lane-cooperative"),
        (body("v_mov_b32_dpp v20, v4 quad_perm:[1,0,3,2] row_mask:0xf bank_mask:0xf"), FETCH_ROLES, "lane-cooperative"),
        (body("s_mov_b64 s[20:21], exec"), FETCH_ROLES, "execution mask"),
        (body("s_wqm_b64 exec, exec"), FETCH_ROLES, "execution mask"),
        (body("buffer_store_dword v4, v0, s[8:11], 0 idxen"), FETCH_ROLES, "side effects"),
        (body("v_interp_mov_f32_e32 v20, p0, attr1.x"), FETCH_ROLES, "interpolation"),
        # Exports.
        ([line for line in base if not line.startswith("exp pos0")], FETCH_ROLES, "pos0 exactly once"),
        (body("exp pos0 v4, v5, v6, v7 done vm", at=end + 1), FETCH_ROLES, "more than once"),
        (body("exp param0 v8, v9, v10, v11", at=end + 1), FETCH_ROLES, "more than once"),
        ([line.replace(" done vm", " vm") for line in base], FETCH_ROLES, "must have done"),
        ([line.replace("v11, v12, v13, v14", "v11, v12, v13, v14 done") for line in base], FETCH_ROLES, "belong"),
        (body("exp mrt0 v4, v5, v6, v7 done vm"), FETCH_ROLES, "not a vertex-shader export"),
        (body("exp param3 v4, v4, v5, v5 compr"), FETCH_ROLES, "compressed"),
        (body("exp param3 v4, v5, s6, v7"), FETCH_ROLES, "export source"),
        (body("exp param3 v4, v5, v30, v7"), FETCH_ROLES, "unset"),
        (base[:-1], FETCH_ROLES, "Missing s_endpgm"),
        (base + ["v_mov_b32_e32 v20, 0"], FETCH_ROLES, "follows program end"),
        # Waits: a fetched word read before its vmcnt wait, V# words before lgkmcnt.
        ([line for line in base if line != "s_waitcnt vmcnt(0)"], FETCH_ROLES, "vmcnt"),
        ([line.replace("vmcnt(0)", "vmcnt(1)") for line in base], FETCH_ROLES, "vmcnt"),
        ([line for line in base if line != "s_waitcnt lgkmcnt(0)"], FETCH_ROLES, "load completion"),
        # The role map and the descriptor contract.
        ([line.replace("s_movk_i32 s3, 0x8000", "s_movk_i32 s3, 0x8001") for line in base], FETCH_ROLES, "high word"),
        ([line for line in base if not line.startswith("s_movk_i32 s3")], FETCH_ROLES, "high word"),
        ([line.replace("s[2:3], null", "s[2:3], 0x10") for line in base], FETCH_ROLES, "not in the role map"),
        ([line.replace("s[2:3], null", "s[2:3], s5") for line in base], FETCH_ROLES, "immediate"),
        ([*base], {2: FETCH_ROLES[2]}, "unset scalar register"),  # s3 has no role: the base vertex copy reads nothing
        ([*base], {2: ("descriptors", HIGH, {0: ("vsharp", 8)}), 3: ("base_vertex",)}, "not in the role map"),
        ([*base], {**FETCH_ROLES, 2: ("descriptors", HIGH, {0: ("vsharp", 8), 16: ("vsharp", 10)})}, "overlap"),
        ([*base], {**FETCH_ROLES, 2: ("descriptors", HIGH, {8: ("vsharp", 8)})}, "aligned"),
        ([*base], {**FETCH_ROLES, 2: ("descriptors", HIGH, {0: ("vsharp", 61)})}, "unknown entry"),
        ([*base], {**FETCH_ROLES, 4: ("base_vertex",)}, "At most one"),
        ([*base], {**FETCH_ROLES, 4: ("descriptors", HIGH, {0: ("constants",)}),
                   5: ("descriptors", HIGH, {0: ("constants",)})}, "one constant-buffer"),
        ([*base], {**FETCH_ROLES, 106: ("base_vertex",)}, "out of range"),
        ([*base], {**FETCH_ROLES, 4: ("pointer",)}, "unknown role"),
        (body("v_add_f32_e32 v20, s2, v4"), FETCH_ROLES, "numeric"),  # a descriptor pointer is not data
        (body("buffer_load_dword v20, v0, s[0:3], 0 idxen"), FETCH_ROLES, "unset scalar register s1"),  # no V# in s[0:3]
        (body("s_buffer_load_dword s20, s[8:11], null"), FETCH_ROLES, "constant buffer"),  # a V# is not the cbuffer
        # A V-1 program in its NGG form keeps the frame: refused until V-2.
        (["s_barrier", "s_and_b32 s4, s3, 0xf000000", *base], FETCH_ROLES, "NGG"),
    ]
    accepted = refusals.pop(next(k for k, r in enumerate(refusals) if r[2] is None))
    lower(*accepted[:2])
    for program, roles, reason in refusals:
        must_refuse(program, roles, reason)
    check_ngg_refusals()
    check_v3_refusals()


def check_ngg_refusals():
    """Card V-2: the frame matcher refuses any other frame, naming the first difference, and the body's contract."""
    frame, roles = list(NGG_FETCH), ngg_roles(FETCH_ROLES)
    at = {line: k for k, line in enumerate(frame)}

    def edit(old, *new):
        k = at[old]
        return frame[:k] + list(new) + frame[k + 1:]
    body_at = at["s_mov_b32 s0, s9"]

    def body(*lines):
        return frame[:body_at] + list(lines) + frame[body_at:]
    refusals = [
        (edit("s_and_b32 s0, s3, 0xf000000", "s_and_b32 s0, s4, 0xf000000"), "wave-id test"),
        (edit("s_cbranch_scc1 BB3", "s_cbranch_scc1 BB4"), "does not land on BB4"),
        (edit("s_bfe_u32 s0, s2, 0x90016", "s_bfe_u32 s0, s2, 0x90017"), "primitive count from gs_tg_info"),
        (edit("s_bfe_u32 s2, s2, 0x9000c", "s_bfe_u32 s0, s2, 0x9000c"), "overwrites the primitive count"),
        (edit("s_sendmsg sendmsg(MSG_GS_ALLOC_REQ)", "s_sendmsg sendmsg(MSG_GS_DONE)"), "GS_ALLOC_REQ"),
        (edit("s_lshl_b32 s0, s3, 8", "s_lshl_b32 s0, s3, 9"), "a primitive count"),
        (edit("s_pack_ll_b32_b16 s3, 0, s3", "s_lshl_b32 s3, s3, 8"), "repeats"),
        (edit("s_bfe_u64 exec, -1, s3", "s_bfe_u64 exec, -1, s0"), "exec mask from the vertex count"),
        (edit("exp prim v0, off, off, off done", "exp prim v1, off, off, off done"), "passthrough export"),
        (edit("exp prim v0, off, off, off done", "exp prim v0, off, off, off done", "exp prim v0, off, off, off done"),
         "does not land on BB9"),
        (edit("BB15:", "BB16:"), "names no later label"),
        (frame + ["s_endpgm"], "s_endpgm after the two regions"),
        (body("v_mov_b32_e32 v30, v0"), "primitive payload"),
        (body("v_mov_b32_e32 v30, v6"), "entry VGPR v6"),
        (body("v_mov_b32_e32 v30, v8", "v_mov_b32_e32 v31, v4"), "entry VGPR v4"),
        (body("s_mov_b32 s40, s2"), "frame register s2"),
        (body("s_mov_b32 s40, m0"), "frame register m0"),
        (body("s_mov_b32 s40, s3"), "frame register s3"),
        (body("s_barrier"), "frame operation"),
        (body("exp prim v0, off, off, off done"), "frame operation"),
        (body("v_mbcnt_lo_u32_b32 v30, -1, 0"), "lane-cooperative"),
        (body("ds_write_b32 v5, v6"), "lane-cooperative"),
        (body("v_readfirstlane_b32 s40, v5"), "lane-cooperative"),
        # A legacy program refuses the NGG entry roles and the other way round.
        ([line for line in FETCH], {**FETCH_ROLES, 3: ("base_vertex",)}, None),
    ]
    refusals.pop()
    for program, reason in refusals:
        must_refuse(program, roles, reason)
    must_refuse(frame, {**roles, 3: ("inline", 0)}, "hardware SGPRs")
    # Vertex first: the primitive export after the body reads v0 and s3, so the body may not write them.
    vertex_first = list(NGG_MATRIX)
    k = vertex_first.index("s_movk_i32 s9, 0x8000")
    must_refuse(vertex_first[:k] + ["v_mov_b32_e32 v0, 0"] + vertex_first[k:], ngg_roles(MATRIX_ROLES), "writes v0")
    must_refuse(vertex_first[:k] + ["s_mov_b32 s3, 0"] + vertex_first[k:], ngg_roles(MATRIX_ROLES), "writes s3")
    # Prim first: the body may reuse v0 and the frame registers once it has written them.
    k = frame.index("s_mov_b32 s0, s9")
    lower(frame[:k] + ["v_mov_b32_e32 v0, 1.0", "s_mov_b32 s2, 0", "v_mov_b32_e32 v30, s2"] + frame[k:], roles)
    # The legacy program unchanged inside the frame reads s3 (merged_wave_info) as its base vertex: refused.
    must_refuse(ngg_frame([line for line in FETCH if line != "s_endpgm"]),
                {k + 6: r for k, r in FETCH_ROLES.items()}, "frame register s2, s3")


def check_v3_refusals():
    """Card V-3: PA_CL_VS_OUT_CNTL state and position exports, push words, and the constant buffer read as data."""
    for cntl, reason in ((None, "PA_CL_VS_OUT_CNTL state"), (1 << 22 | 1, "no pos2"),
                         (DISTANCE_CNTL | 1 << 16, "point size"), (DISTANCE_CNTL | 1 << 21, "misc vector"),
                         (DISTANCE_CNTL | 1 << 18, "render-target index"), (DISTANCE_CNTL | 1 << 24, "above"),
                         (1 << 22 | 1 << 23 | 0b1001 | 0x30 << 8 | 1 << 9, "both"), (1 << 22 | 1 << 23 | 1, "neither"),
                         (DISTANCE_CNTL | 1 << 8, "both clip and cull"), (0b101 | 1 << 22, "no pos2"),
                         (DISTANCE_CNTL & ~(1 << 23), "not exported")):
        must_refuse(DISTANCE, DISTANCE_ROLES, reason, cntl)
    k = DISTANCE.index("exp pos1 v4, v6, v2, off")
    must_refuse(DISTANCE[:k] + DISTANCE[k + 2:], DISTANCE_ROLES, "does not export", DISTANCE_CNTL)
    must_refuse([line.replace("v3, v2 done", "v3, v2") for line in DISTANCE], DISTANCE_ROLES, "must have done",
                DISTANCE_CNTL)
    must_refuse([line.replace("v3 vm", "v3 done vm") for line in DISTANCE], DISTANCE_ROLES, "and no other",
                DISTANCE_CNTL)
    # A distance vector enabled for distances 4..7 only is pos1, not pos2.
    lower([line.replace("v4, v6, v2, off", "v4, v6, v2, off done") for line in DISTANCE if not line.startswith("exp pos2")],
          DISTANCE_ROLES,
          0b110000 << 8 | 1 << 23)  # pos1 is then cull distances 4 and 5
    # The constant buffer V# read as data needs its descriptor words; without them buffer_load has no numeric V#.
    roles = {**INSTANCE_ROLES, 5: ("descriptors", HIGH, {0: ("constants",)})}
    must_refuse(INSTANCE, roles, "numeric")
    must_refuse(INSTANCE, {**INSTANCE_ROLES, 5: ("descriptors", HIGH, {0: ("constants", 0)})}, "overlap")
    # The instance index before the start instance is added, read through a pending scalar load.
    k = INSTANCE.index("s_waitcnt lgkmcnt(0)")
    must_refuse(INSTANCE[:k] + ["v_mov_b32_e32 v30, s20"] + INSTANCE[k:], INSTANCE_ROLES, "unset")
    # A typed fetch translates since family typed; its d16 form does not.
    must_refuse(INSTANCE[:k + 1] + ["buffer_load_format_d16_x v30, v0, s[12:15], 0 idxen"] + INSTANCE[k + 1:],
                INSTANCE_ROLES, "d16 typed vertex fetch")


def check_v4_controls():
    """Card V-4: the model's results against values worked out by hand, every wrong reference of the two families
    differing from the right one on some id, the translation shape, and the refused neighbours."""
    def run(program, roles, flaws=(), count=16, base=0):
        source, layout = lower(program, roles)
        model = Model(roles, [0] * 64, Memory([]), flaws)
        return outputs(model, program, layout, range(count), base)[0]

    # Angle (n + 0.5) / 16 revolutions: the eighths of sin and cos rounded to integers (exported as floats).
    words = run(TRIG, TRIG_ROLES)
    for n in range(16):
        angle = 2 * math.pi * (n + 0.5) / 16
        assert all(abs(8 * x % 1 - 0.5) > 0.04 for x in (math.sin(angle), math.cos(angle))), n
        sin8, cos8 = round(8 * math.sin(angle)), round(8 * math.cos(angle))
        got = [struct.unpack("<f", struct.pack("<I", w))[0] for w in words[8 * n:8 * n + 5]]
        assert got == [sin8, cos8, sin8, 1.0, cos8], (n, got)
    # The carry chain by integer arithmetic, limb by limb as the program's comments describe it.
    words = run(CARRY, CARRY_ROLES, count=8)
    for n in range(8):
        v2, v3, v5 = (n << 31) & M32, (n << 30) & M32, M32
        c1 = (v2 + v3) >> 32
        b1 = int(v3 < v2)
        want = [(v2 + v3) & M32, (v5 + c1) & M32, (v5 + c1) >> 32, (v3 - v2) & M32,    # pos0: v4 v7 v8 v9
                (n - v5 - b1) & M32, (v5 - n - b1) & M32, (v2 + v3) & M32, (v3 - v2) & M32,  # param0: v10 v11 v12 v13
                (n + c1) & M32, v5, (v2 - v3) & M32, -int(v2 < v3) & M32]                 # param1: v14 v15 v16 v17
        assert words[12 * n:12 * n + 12] == want, (n, words[12 * n:12 * n + 12], want)
    for program, roles, flaws, count in ((TRIG, TRIG_ROLES, ({"sin_cos_swapped"}, {"radians"}, {"div2_ignored"}, {"base_ignored"}), 16),
                                         (CARRY, CARRY_ROLES, ({"no_carry_in"}, {"no_borrow"}, {"subrev_swapped"}, {"base_ignored"}), 8)):
        right = run(program, roles, count=count, base=3)
        for flaw in flaws:
            assert run(program, roles, flaw, count, 3) != right, flaw
    source, _ = lower(CARRY, CARRY_ROLES)
    assert "coc" in source and source.count("bool cmp") >= 9
    source, _ = lower(TRIG, TRIG_ROLES)
    # The shared binary32 form lowers both through sin32/cos32 (pixel_aot_draws/trig.py), whole turns removed first.
    assert "sin32(" in source and "cos32(" in source and "6.28318548f" in source and "ftz32(" in source
    # The wave64 spellings (VCC and SGPR pairs) lower like the wave32 ones.
    wide = [line.replace("vcc_lo", "vcc").replace("s10", "s[10:11]").replace("s12", "s[12:13]") for line in CARRY]
    assert lower(wide, CARRY_ROLES)[0] == lower(CARRY, CARRY_ROLES)[0]
    # Refused neighbours: a carry-in no instruction produced, one from another mask, one that is a pair
    # mask whose second half was never written, clamp on the carry-in forms, an output modifier on the e32 sine, an extra operand, and
    # the binary16 sine.
    head = CARRY[:6]
    must_refuse([*head, "v_add_co_ci_u32_e32 v7, vcc_lo, v5, v6, vcc_lo", "s_endpgm"], CARRY_ROLES, "tracked")
    must_refuse([*head, "v_add_co_u32 v4, s10, v2, v3", "v_add_co_ci_u32_e32 v7, vcc_lo, v5, v6, vcc_lo", "s_endpgm"],
                CARRY_ROLES, "tracked")
    must_refuse([*head, "v_add_co_u32 v4, vcc_lo, v2, v3", "v_add_co_ci_u32_e64 v7, s10, v5, v6, s11", "s_endpgm"],
                CARRY_ROLES, "tracked")
    must_refuse([*head, "v_add_co_u32 v4, vcc_lo, v2, v3", "v_add_co_ci_u32_e64 v7, s10, v5, v6, vcc_lo clamp",
                 "s_endpgm"], CARRY_ROLES, "Unsupported")
    must_refuse([*TRIG[:5], "v_sin_f32_e32 v5, v4 div:2", "s_endpgm"], TRIG_ROLES, "Invalid arithmetic")
    must_refuse([*TRIG[:5], "v_sin_f32_e64 v5, v4 clamp mul:2 extra", "s_endpgm"], TRIG_ROLES, "Unsupported")
    must_refuse([*TRIG[:5], "v_sin_f32_e32 v5, v4, v3", "s_endpgm"], TRIG_ROLES)
    must_refuse([*TRIG[:5], "v_sin_f16_e32 v5, v4", "s_endpgm"], TRIG_ROLES, "Unsupported")


def check_wide_controls():
    """The constant window: a program that reads at most 64 words keeps params[16], a read past it sizes params[] to
    the highest word read rounded up to a uint4, a CBV's 4096 uint4 are the limit, and the wrong reference differs."""
    source, layout = lower(WIDE, WIDE_ROLES)
    assert "uint4 params[66];" in source and "params[65].w" in source, source[:400]  # words 260 to 263 are the last read
    narrow = [line.replace("0x120", "0x20").replace("0x410", "0x30") for line in WIDE]
    assert "uint4 params[16];" in lower(narrow, WIDE_ROLES)[0]
    assert "uint4 params[4096];" in lower([line.replace("0x410", "0xfff0") for line in WIDE], WIDE_ROLES)[0]
    must_refuse([line.replace("0x410", "0x10000") for line in WIDE], WIDE_ROLES, "exceeds")
    constants = wide_constants(5, 272)
    model = lambda flaw=(): outputs(Model(WIDE_ROLES, constants, Memory([]), flaw), WIDE, layout, range(6), 3)[0]  # noqa: E731
    for flaw in ({"window_64"}, {"base_ignored"}):
        assert model(flaw) != model(), flaw


def check_dynamic_controls():
    """A run-time constant offset declares the whole binding and reads 0 past it; every wrong reference differs; the
    neighbours stay refused: a misaligned offset: field, an offset register still being loaded, a descriptor load at an
    SGPR offset."""
    source, layout = lower(DYNAMIC, DYNAMIC_ROLES)
    assert "uint4 params[4096];" in source and "& 0xfffffffcu;" in source and "<= 65468u ?" in source, source[:600]
    words = wide_constants(7, 16384)
    for flaw in ({"dyn_ignored"}, {"dyn_wrap"}, {"dyn_unmasked"}):
        assert any(outputs(Model(DYNAMIC_ROLES, words, Memory([]), flaw, push=push), DYNAMIC, layout, range(3), 1)[0]
                   != outputs(Model(DYNAMIC_ROLES, words, Memory([]), (), push=push), DYNAMIC, layout, range(3), 1)[0]
                   for push in ([3, 2], [1023, 3], [1024, 1])), flaw
    must_refuse([line.replace("offset:0x3c", "offset:0x3e") for line in DYNAMIC], DYNAMIC_ROLES, "misaligned")
    early = [line for line in DYNAMIC if line != "s_waitcnt lgkmcnt(0)"]
    must_refuse(early, DYNAMIC_ROLES)
    chained = list(DYNAMIC)
    chained.insert(chained.index("s_buffer_load_dwordx2 s[20:21], s[12:15], s8 offset:0x3c"),
                   "s_buffer_load_dword s8, s[12:15], s16")  # its offset register is a load still outstanding
    must_refuse(chained, DYNAMIC_ROLES)
    must_refuse([line.replace("s_load_dwordx4 s[12:15], s[4:5], null", "s_load_dwordx4 s[12:15], s[4:5], s6")
                 for line in DYNAMIC], DYNAMIC_ROLES, "immediate")


def check_typed_controls():
    """Typed fetch: the reference conversions against values worked out by hand, every wrong reference differing from
    the right one on some set, and the translation's use of the run-time and instruction formats."""
    f = lambda name: UFMT_NAMES.index(name) + 1  # noqa: E731
    hand = [
        ("8_UNORM", 0xff, [0x3f800000, 0, 0, 0x3f800000]), ("8_UNORM", 0x80, [0x3f008081, 0, 0, 0x3f800000]),
        ("8_SNORM", 0x80, [0xbf800000, 0, 0, 0x3f800000]), ("8_SNORM", 0x81, [0xbf800000, 0, 0, 0x3f800000]),
        ("8_SNORM", 0x7f, [0x3f800000, 0, 0, 0x3f800000]), ("8_USCALED", 0xff, [0x437f0000, 0, 0, 0x3f800000]),
        ("8_SSCALED", 0xff, [0xbf800000, 0, 0, 0x3f800000]), ("8_UINT", 0xff, [0xff, 0, 0, 1]),
        ("8_SINT", 0xff, [M32, 0, 0, 1]), ("16_FLOAT", 0x3c00, [0x3f800000, 0, 0, 0x3f800000]),
        ("16_FLOAT", 0x0001, [0x33800000, 0, 0, 0x3f800000]), ("16_FLOAT", 0xfc01, [0xff802000, 0, 0, 0x3f800000]),
        ("16_16_UNORM", 0xffff0001, [0x37800080, 0x3f800000, 0, 0x3f800000]),
        ("10_11_11_FLOAT", 0x3c0 | 0x3c0 << 11 | 0x1e0 << 22, [0x3f800000] * 4),
        ("11_11_10_FLOAT", 0x1 | 0x3c0 << 10 | 0x7c1 << 21, [0x36000000, 0x3f800000, 0x7f820000, 0x3f800000]),
        ("2_10_10_10_UINT", 1 | 2 << 10 | 3 << 20 | 3 << 30, [1, 2, 3, 3]),
        ("10_10_10_2_UINT", 1 | 2 << 2 | 3 << 12 | 0x3ff << 22, [1, 2, 3, 0x3ff]),
        ("2_10_10_10_SNORM", 0x200 | 0x1ff << 10 | 2 << 30, [0xbf800000, 0x3f800000, 0, 0xbf800000]),
        ("8_8_8_8_UINT", 0x04030201, [1, 2, 3, 4]), ("32_32_FLOAT", 0x3f800000_7fc00001, [0x7fc00001, 0x3f800000, 0, 0x3f800000]),
    ]
    for name, data, want in hand:
        got = typed_element(f(name), data)
        assert got == want, (name, hex(data), [hex(x) for x in got])
    sets = typed_sets()
    assert {(w[15] >> 12) & 0x7f for w, *_ in sets} | {(w[19] >> 12) & 0x7f for w, *_ in sets} == set(range(1, 78))
    layout = lower(TYPED, TYPED_ROLES)[1]
    for flaw in TYPED_FLAWS:
        assert any(outputs(Model(TYPED_ROLES, c, m, flaw), TYPED, layout, range(n), b)
                   != outputs(Model(TYPED_ROLES, c, m), TYPED, layout, range(n), b) for c, m, n, b in sets), flaw
    source = lower(TYPED, TYPED_ROLES)[0]
    assert source.count(">> 12u) & 0x7fu);") == 3 and ", 51u);" in source and ", 36u);" in source \
        and ", 13u);" in source, "typed loads do not pass the V# or instruction format"
    print(f"vertex_aot typed controls ok: {len(hand)} hand values, {len(sets)} sets, {len(TYPED_FLAWS)} wrong references")


def check_controls():
    check_reference_arithmetic()
    check_typed_controls()
    check_translation_shape()
    check_refusals()
    check_v4_controls()
    check_wide_controls()
    check_dynamic_controls()
    # Every wrong reference of every family changes the model's output for at least one draw input; the draws check
    # that the renderer then reports the mismatch. Here: the model runs every family's program without error.
    model = Model(FETCH_ROLES, fetch_constants(vsharp(HIGH_BASE, 24, 8, 0), vsharp(HIGH_BASE, 12, 8, 1)),
                  memory_for(1))
    right = model.run(FETCH, 3, 1)
    model.flaws = {"nostride"}
    assert model.run(FETCH, 3, 1) != right
    print("vertex_aot controls ok")


# --- LLVM round trip ---------------------------------------------------------------------------------------------------

def llvm_disassemble(assembler, code):
    """Disassemble with llvm-mc itself (the LLVM 15 that assembled the program) when no libLLVM is given. Returns
    (byte offset, text) pairs like pixel_aot.disassemble(offsets=True); --show-encoding gives each size."""
    text = " ".join(f"0x{b:02x}" for b in code)
    result = subprocess.run([assembler, "--disassemble", "--show-encoding", "-triple=amdgcn--amdpal", "-mcpu=gfx1013"],
                            input=text, capture_output=True, text=True, check=True)
    out, offset = [], 0
    for line in result.stdout.splitlines():
        if not (m := re.fullmatch(r"\s*(.*?)\s*(?://|;)\s*encoding:\s*\[(.*)\]\s*", line)):
            continue
        out.append((offset, " ".join(m[1].split())))
        offset += len(m[2].split(","))
    assert offset == len(code), (offset, len(code))
    return out


def check_binary(directory, assembler, objcopy, library=None):
    """Assemble every program with llvm-mc 15, disassemble it again (libLLVM, or llvm-mc), name its branch targets as
    a native program's would be (the NGG frame's labels become _L<n>) and lower it: the HLSL must be the same."""
    sys.path.insert(0, str(ROOT / "tools"))
    import pixel_aot
    for index, (program, roles, cntl) in enumerate(PROGRAMS):
        source, obj, binary = directory / "v.s", directory / "v.o", directory / "v.bin"
        source.write_text("\n".join(program) + "\n", encoding="ascii")
        subprocess.run([assembler, "-triple=amdgcn--amdpal", "-mcpu=gfx1013", "-filetype=obj", source, "-o", obj],
                       check=True)
        subprocess.run([objcopy, "-O", "binary", "--only-section=.text", obj, binary], check=True)
        code = binary.read_bytes()
        decoded = (pixel_aot.disassemble(code, library, offsets=True) if library
                   else llvm_disassemble(assembler, code))
        decoded = pixel_aot.name_branch_targets(decoded, len(code))
        assert lower(decoded, roles, cntl) == lower(program, roles, cntl), (index, decoded)
    print(f"vertex_aot binary ok: {len(PROGRAMS)} programs")


def check_render(directory, compiler, renderer, backend, families):
    for name in families or DRAW_FAMILIES:
        try:
            code = DRAW_FAMILIES[name](directory, compiler, renderer, backend)
        except subprocess.CalledProcessError as error:
            if error.returncode != 77:
                raise
            return 77
        if code:
            return code
    return 0


def main():
    mode, *args = sys.argv[1:]
    if mode == "--list-families":
        print("\n".join(DRAW_FAMILIES))
        return 0
    families = []
    while "--family" in args:
        at = args.index("--family")
        families.append(args[at + 1])
        del args[at:at + 2]
    unknown = [name for name in families if name not in DRAW_FAMILIES]
    if unknown or (families and mode != "draw"):
        raise ValueError(f"Unknown or misplaced --family {unknown}; known families: {', '.join(DRAW_FAMILIES)}")
    with tempfile.TemporaryDirectory() as tmp:
        directory = Path(tmp)
        if mode == "controls":
            check_controls()
        elif mode == "binary":
            check_controls()
            check_binary(directory, *args)
        elif mode == "draw":
            if not families:
                check_controls()
            return check_render(directory, *args, families)
        else:
            raise ValueError("Expected controls, binary or draw mode")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:  # also on skip or failure; tools/form_coverage.py reads the test's status from JUnit
        write_record(os.environ.get("FORM_COVERAGE_RECORD"))
