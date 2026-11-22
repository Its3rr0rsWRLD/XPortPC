"""Exercise offline vertex translation (card V-1, docs/design/vertex-stage.md) with hand-written gfx1013 programs.

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
pos0 and param exports). No corpus binary is used.
"""
from fractions import Fraction
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


def lower(instructions, roles):
    source, layout = vertex_aot.lower_with_layout(instructions, roles)
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


def must_refuse(instructions, roles, reason=None):
    try:
        vertex_aot.lower_with_layout(instructions, roles)
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

    def __init__(self, roles, constants, memory, flaws=()):
        self.roles, self.constants, self.memory, self.flaws = roles, constants, memory, set(flaws)

    def run(self, program, vertex_id, base_vertex):
        s, v = {}, {}
        for number, role in self.roles.items():
            if role[0] == "descriptors":
                s[number] = ("pointer", number)
            elif role[0] == "base_vertex":
                s[number] = 0 if "base_ignored" in self.flaws else base_vertex
        v[0] = 0 if "instance_id" in self.flaws else vertex_id  # a single-instance draw: the instance id is 0
        exports = {}

        def sreg(token):
            value = s[int(token[1:])]
            if not isinstance(value, int):
                raise AssertionError(f"{token} holds {value}, not data")
            return value

        def word(token):
            if token.startswith("-"):
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
            elif name.startswith("s_load_dword"):
                pointer = s[span(ops[1])[0]]
                table_high, entries = self.roles[pointer[1]][1:]
                assert s[span(ops[1])[1]] == table_high
                offset = 0 if ops[2] == "null" else int(ops[2], 0)
                for j, n in enumerate(span(ops[0])):
                    at = offset + 4 * j
                    start = next(k for k in entries if k <= at < k + 16)
                    entry = entries[start]
                    s[n] = (("cbv", (at - start) // 4) if entry[0] == "constants"
                            else self.constants[entry[1] + (at - start) // 4])
            elif name.startswith("s_buffer_load_dword"):
                base = span(ops[1])
                assert [s[n] for n in base] == [("cbv", j) for j in range(4)]
                offset = 0 if ops[2] == "null" else int(ops[2], 0)
                values = [self.constants[offset // 4 + j] for j in range(len(span(ops[0])))]
                for n, value in zip(span(ops[0]), values):
                    s[n] = value
            elif name.startswith("buffer_load_dword"):
                self.fetch(ops, v, s, span)
            elif name == "v_mov_b32":
                v[int(ops[0][1:])] = word(ops[1])
            elif name in ("v_add_nc_u32", "v_and_b32", "v_xor_b32", "v_or_b32", "v_lshlrev_b32", "v_mul_u32_u24"):
                a, b = word(ops[1]), word(ops[2])
                v[int(ops[0][1:])] = {
                    "v_add_nc_u32": (a + b) & M32, "v_and_b32": a & b, "v_xor_b32": a ^ b, "v_or_b32": a | b,
                    "v_lshlrev_b32": (b << (a & 31)) & M32, "v_mul_u32_u24": ((a & 0xffffff) * (b & 0xffffff)) & M32,
                }[name]
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

    def fetch(self, ops, v, s, span):
        """buffer_load_dword* idxen with an instruction offset: gfx10 range rules as tools/pixel_aot_ops/hlsl.py cites
        them (Mesa ac_set_buf_desc_word3), per dword."""
        rsrc = [s[n] for n in span(ops[2])]
        if not all(isinstance(w, int) for w in rsrc):
            raise AssertionError("V# words are not data")
        modifiers = ops[-1].split()[1:]
        inst = next((int(m[7:]) for m in modifiers if m.startswith("offset:")), 0)
        index = v[int(ops[1][1:])]
        base = rsrc[0] | (rsrc[1] & 0xffff) << 32
        stride, records, select = (rsrc[1] >> 16) & 0x3fff, rsrc[2], (rsrc[3] >> 28) & 3
        for j, n in enumerate(span(ops[0])):
            offset = inst + 4 * j
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

def case_file(records, base_vertex, params, constants, expected, mask, indices=None, memory=b""):
    assert len(params) <= 8 and len(constants) == 64 and len(expected) == len(mask)
    header = [0x56573258, records, int(indices is not None), base_vertex & M32, len(params),
              *params, *[0] * (8 - len(params)), 0, 0, 0]
    body = header + list(constants) + list(indices or []) + list(expected) + list(mask)
    return struct.pack(f"<{len(body)}I", *body) + memory


def outputs(model, program, layout, ids, base_vertex):
    """Expected words and compare masks of a draw: per record pos0 then each parameter, xyzw. An `off` channel is
    undefined: its mask is 0. Swapping parameters is one of the wrong references."""
    order = ["pos0", *(f"param{n}" for n in layout["params"])]
    if "swap_params" in model.flaws:
        order[1], order[2] = order[2], order[1]
    expected, mask = [], []
    for vertex_id in ids:
        exports = model.run(program, vertex_id, base_vertex)
        for name in order:
            for word in exports[name]:
                expected.append(0 if word is None else word)
                mask.append(0 if word is None else M32)
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


def run_sets(directory, compiler, renderer, backend, name, program, roles, sets, flaws, extra=None):
    """Draw every set with its reference, then each wrong reference, which must be reported as a mismatch.
    A set is (constants, memory, record ids or (indices,), base vertex)."""
    source, layout = lower(program, roles)
    shader = compile_vs(compiler, source, directory, name)
    case = directory / f"{name}.case"
    draw = [renderer, backend, "--check-vertex-case", shader, case]
    separated = dict.fromkeys(map(frozenset, flaws), False)
    for constants, memory, ids, base in sets:
        indices = ids[0] if isinstance(ids, tuple) else None
        records = list(indices) if indices is not None else list(range(ids))
        expected, mask = outputs(Model(roles, constants, memory), program, layout, records, base)
        write = lambda e, m: case.write_bytes(case_file(len(records), base, layout["params"], constants, e, m,
                                                        indices, memory.section()))
        write(expected, mask)
        result = subprocess.run(draw, capture_output=True, text=True)
        sys.stdout.write(result.stdout)
        if result.returncode == 77:
            return 77
        if result.returncode:
            sys.stderr.write(result.stderr)
            raise AssertionError(f"{name}: the draw differs from the reference (base vertex {base:#x}, {len(records)} records)")
        for flaw in separated:
            wrong, _ = outputs(Model(roles, constants, memory, flaw), program, layout, records, base)
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


DRAW_FAMILIES = {"fetch": draw_fetch, "matrix": draw_matrix, "vertex_id": draw_vertex_id, "nan": draw_nan}
PROGRAMS = ((FETCH, FETCH_ROLES), (MATRIX, MATRIX_ROLES), (VERTEX_ID, VERTEX_ID_ROLES), (NAN, NAN_ROLES))


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
    assert "VertexOutput main(uint vid : SV_VertexID)" in source and "register(b2) { uint base_vertex; }" in source
    assert "(base_vertex + vid)" in source and "title_memory" not in source and "Texture2D" not in source
    assert "SV_Target" not in source and "params[" not in source
    source, layout = lower(FETCH, FETCH_ROLES)
    assert "params[2].x, params[2].y, params[2].z, params[2].w" in source and "buffer_load32(" in source
    assert "title_memory" in source and "uint4 params[16]" in source and layout["params"] == [0, 1]
    source, _ = lower(MATRIX, MATRIX_ROLES)
    assert source.count("uint vmc") == 3, source  # the three words of the load that vmcnt(1) completes
    assert "mad32(" in source and "asfloat(params[0].x)" in source
    # Every hand-written program goes through the same form registry as the pixel stage; record the accepted forms.
    for program, roles in PROGRAMS:
        lower(program, roles)


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
        (body("v_mov_b32_e32 v20, v3"), FETCH_ROLES, "instance id"),
        (body("v_add_nc_u32_e32 v20, s0, v3"), FETCH_ROLES, "instance id"),
        (body("v_mov_b32_e32 v20, v1"), FETCH_ROLES, "entry VGPR v1"),
        (body("v_mov_b32_e32 v20, v2"), FETCH_ROLES, "entry VGPR v2"),
        (body("exp pos1 v4, off, off, off done"), FETCH_ROLES, "PA_CL_VS_OUT_CNTL"),
        (body("buffer_load_format_xyzw v[20:23], v0, s[8:11], 0 idxen"), FETCH_ROLES, "typed vertex fetch"),
        (body("tbuffer_load_format_x v20, v0, s[8:11], 0 format:[BUF_FMT_32_FLOAT] idxen"), FETCH_ROLES, "typed"),
        (body("buffer_load_dword v20, v0, s[8:11], 0 offen"), FETCH_ROLES, "offen"),
        (body("buffer_load_dword v20, v[0:1], s[8:11], 0 idxen offen"), FETCH_ROLES, "offen"),
        (body("buffer_load_dword v20, off, s[8:11], 0"), FETCH_ROLES, "offen"),
        (body("global_load_dword v20, v[4:5], off"), FETCH_ROLES, "V-3"),
        ([*base], {**FETCH_ROLES, 5: ("start_instance",)}, "V-3"),
        ([*base], {**FETCH_ROLES, 5: ("inline",)}, "V-3"),
        ([*base], {**FETCH_ROLES, 5: ("inline_vsharp",)}, "V-3"),
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
    for program, roles, reason in refusals:
        must_refuse(program, roles, reason)


def check_controls():
    check_reference_arithmetic()
    check_translation_shape()
    check_refusals()
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
    """Disassemble with llvm-mc itself (the LLVM 15 that assembled the program) when no libLLVM is given."""
    text = " ".join(f"0x{b:02x}" for b in code)
    result = subprocess.run([assembler, "--disassemble", "-triple=amdgcn--amdpal", "-mcpu=gfx1013"], input=text,
                            capture_output=True, text=True, check=True)
    lines = [line.split("//")[0].strip() for line in result.stdout.splitlines()]
    return [line for line in lines if line and not line.startswith(".")]


def check_binary(directory, assembler, objcopy, library=None):
    sys.path.insert(0, str(ROOT / "tools"))
    import pixel_aot
    for index, (program, roles) in enumerate(PROGRAMS):
        source, obj, binary = directory / "v.s", directory / "v.o", directory / "v.bin"
        source.write_text("\n".join(program) + "\n", encoding="ascii")
        subprocess.run([assembler, "-triple=amdgcn--amdpal", "-mcpu=gfx1013", "-filetype=obj", source, "-o", obj],
                       check=True)
        subprocess.run([objcopy, "-O", "binary", "--only-section=.text", obj, binary], check=True)
        code = binary.read_bytes()
        decoded = pixel_aot.disassemble(code, library) if library else llvm_disassemble(assembler, code)
        assert lower(decoded, roles) == lower(program, roles), (index, decoded)
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
