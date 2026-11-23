"""A wave-level model of the console's tessellation waves for tests/tess_aot_check.py (cards T-1 and T-2,
docs/design/stages.md).

Wave runs one gfx1013 wave64 program as the hardware would, instruction by instruction: SGPRs, per-lane VGPRs, EXEC,
VCC, SCC, the branches, LDS, the TF ring and the off-chip ring, the merged-wave entry registers (radv_shader_args.c)
and the NGG passthrough frame of the evaluation wave. It runs the whole program text the test wrote, frame included,
and does not use tools/tess_aot.py's frame matcher. The floating-point rules are tests/vertex_aot_check.py's (exact
binary32 with mad rounding twice and flushing subnormals). flaws switch single rules to a plausible wrong one; the
pipeline driver in tests/tess_aot_check.py applies the tessellator-level ones.
"""
from collections import Counter
import functools
import re
import struct

import vertex_aot_check as vc

M32 = 0xffffffff
M64 = (1 << 64) - 1
INLINE = {**vc.INLINE_FLOAT, "-1.0": 0xbf800000, "-0.5": 0xbf000000, "-2.0": 0xc0000000}


_F32 = struct.Struct("<f")
_U32 = struct.Struct("<I")


def _value(bits):
    return _F32.unpack(_U32.pack(bits))[0]


def _round(value):
    """binary64 to the nearest binary32 (ties to even), as tests/vertex_aot_check.py's round_f32 does with exact
    rationals: a binary64 sum, difference or product of two binary32 values is exact or within the innocuous double
    rounding bound (53 >= 2 * 24 + 2), so rounding it once more gives the correctly rounded binary32 result."""
    return _U32.unpack(_F32.pack(value))[0]


def _finite(*words):
    return all((w >> 23) & 0xff != 0xff for w in words)


def frac(bits):
    """The value of a binary32 word for comparisons (a float: binary64 holds every binary32 value exactly)."""
    return _value(vc.checked(bits))


def f32_mul(a, b):
    vc.checked(a), vc.checked(b)
    try:
        return vc.checked(_round(_value(a) * _value(b)))
    except OverflowError:
        return vc.f32_mul(a, b)


def f32_add(a, b):
    vc.checked(a), vc.checked(b)
    try:
        return vc.checked(_round(_value(a) + _value(b)))
    except OverflowError:
        return vc.f32_add(a, b)


def f32_mad(a, b, c):
    """v_mad_f32 as vc.f32_mad: flushed operands, the product rounded and flushed, the sum rounded and flushed."""
    if not _finite(a, b, c):
        return vc.f32_mad(a, b, c)
    a, b, c = vc.ftz(a), vc.ftz(b), vc.ftz(c)
    try:
        product = vc.ftz(_round(_value(a) * _value(b)))
        if not _finite(product):
            return vc.f32_mad(a, b, c)
        return vc.ftz(_round(_value(product) + _value(c)))
    except OverflowError:
        return vc.f32_mad(a, b, c)


@functools.lru_cache(maxsize=None)
def _scalar_operand(token):
    """("s", number), ("const", word) or ("special", name) for a scalar operand token (parsed once)."""
    token = token.strip()
    if token in INLINE:
        return "const", INLINE[token]
    if re.fullmatch(r"-?\d+", token):
        return "const", int(token) & M32
    if re.fullmatch(r"0x[0-9a-f]+", token):
        return "const", int(token, 16)
    if token in ("src_scc", "vcc_lo", "vcc_hi", "exec_lo"):
        return "special", token
    m = re.fullmatch(r"s(\d+)", token)
    if not m:
        raise AssertionError(f"Model has no scalar operand {token}")
    return "s", int(m[1])


@functools.lru_cache(maxsize=None)
def _vector_operand(token):
    """(negated, "v", number) or (negated, "scalar", scalar token) for a vector source operand (parsed once)."""
    token = token.strip().split()[0]
    if token.startswith("-") and not re.fullmatch(r"-\d+", token) and token not in INLINE:
        negate, kind, value = _vector_operand(token[1:])
        return not negate, kind, value
    if re.fullmatch(r"v\d+", token):
        return False, "v", int(token[1:])
    return False, "scalar", token


class Wave:
    """One wave64. memory: {"tf": {byte: word}, "offchip": {byte: word}} shared with the caller."""

    def __init__(self, model, sgprs, vgprs, lanes_exec, memory, lds=None, flaws=()):
        self.m = model
        self.s = dict(sgprs)  # number -> int or token tuple
        self.v = [dict(lane) for lane in vgprs] + [{} for _ in range(64 - len(vgprs))]
        self.exec = lanes_exec
        self.vcc = 0
        self.scc = 0
        self.mem = memory
        self.lds = lds if lds is not None else bytearray(0x10000)
        self.flaws = set(flaws)
        self.exports = {}  # lane -> {target: [words]}
        self.inv_regs = set()  # VGPRs holding the invocation id (v_bfe_u32 v, v1, 8, 5)

    # --- operands -----------------------------------------------------------------------------------------------
    def sval(self, token):
        kind, value = _scalar_operand(token)
        if kind == "s":
            return self.s[value]
        if kind == "const":
            return value
        if value == "src_scc":
            return self.scc
        if value == "vcc_lo":
            return self.vcc & M32
        if value == "vcc_hi":
            return self.vcc >> 32
        return self.exec & M32

    def s64(self, token):
        if token == "exec":
            return self.exec
        if token == "vcc":
            return self.vcc
        if re.fullmatch(r"-?\d+", token):
            return int(token) & M64
        m = re.fullmatch(r"s\[(\d+):(\d+)\]", token)
        assert m and int(m[2]) == int(m[1]) + 1, token
        lo, hi = self.s[int(m[1])], self.s[int(m[2])]
        assert isinstance(lo, int) and isinstance(hi, int), (token, lo, hi)
        return lo | hi << 32

    def set64(self, token, value):
        value &= M64
        if token == "exec":
            self.exec = value
        elif token == "vcc":
            self.vcc = value
        else:
            m = re.fullmatch(r"s\[(\d+):(\d+)\]", token)
            self.s[int(m[1])], self.s[int(m[2])] = value & M32, value >> 32

    def vval(self, lane, token):
        negate, kind, value = _vector_operand(token)
        if kind == "v":
            word = self.v[lane][value]
        else:
            word = self.sval(value)
            assert isinstance(word, int), (token, word)
        return word ^ 0x80000000 if negate else word

    def span(self, token):
        if m := re.fullmatch(r"[sv]\[(\d+):(\d+)\]", token):
            return list(range(int(m[1]), int(m[2]) + 1))
        return [int(token[1:])]

    def lanes(self):
        return [lane for lane in range(64) if self.exec >> lane & 1]

    # --- execution ----------------------------------------------------------------------------------------------
    def run(self, program):
        lines = [line.split(";")[0].strip() for line in program]
        lines = [" ".join(line.split()) for line in lines if line and not line.startswith("#")]
        labels = {line[:-1]: k for k, line in enumerate(lines) if line.endswith(":")}
        pc = 0
        steps = 0
        while pc < len(lines):
            steps += 1
            assert steps < 200000, "model runaway"
            line = lines[pc]
            pc += 1
            if line.endswith(":"):
                continue
            head, _, rest = line.partition(" ")
            ops = [t.strip() for t in rest.split(",")] if rest else []
            target = self.step(head, ops, line)
            if target == "end":
                return
            if target is not None:
                pc = labels[target]

    def step(self, head, ops, line):
        name = re.sub(r"_e(32|64)$", "", head)
        if name in ("s_setprio", "s_clause", "s_nop", "s_waitcnt", "s_waitcnt_depctr", "s_waitcnt_vscnt", "s_barrier",
                    "s_sendmsg"):
            return None
        if name == "s_endpgm":
            return "end"
        if name == "s_cbranch_execz":
            return ops[0] if self.exec == 0 else None
        if name == "s_cbranch_scc0":
            return ops[0] if not self.scc else None
        if name == "s_cbranch_scc1":
            return ops[0] if self.scc else None
        if name == "s_branch":
            return ops[0]
        if head.startswith("s_"):
            self.scalar(name, ops, line)
            return None
        if head == "exp":
            target = ops[0].split()[0]
            if target == "prim":
                return None
            sources = [ops[0].split()[1]] + ops[1:]
            sources[-1] = sources[-1].split()[0]
            for lane in self.lanes():
                self.exports.setdefault(lane, {})[target] = [
                    None if t == "off" else self.m.export_word(self.v[lane][int(t[1:])]) for t in sources]
            return None
        if head.startswith(("ds_", "buffer_")):
            self.memory_op(head, ops, line)
            return None
        self.vector(name, head, ops, line)
        return None

    def sset(self, token, value):
        if token == "m0":
            self.m0 = value & M32
        else:
            self.s[int(token[1:])] = value & M32

    def scalar(self, name, ops, line):
        s = self.s
        d = ops[0] if ops else None
        if name == "s_mov_b32":
            s[int(d[1:])] = s[int(ops[1][1:])] if re.fullmatch(r"s\d+", ops[1]) else self.sval(ops[1])
        elif name == "s_movk_i32":
            imm = int(ops[1], 0)
            s[int(d[1:])] = (imm - 0x10000 if imm & 0x8000 else imm) & M32
        elif name == "s_mov_b64":
            self.set64(d, self.s64(ops[1]))
        elif name == "s_pack_ll_b32_b16":
            s[int(d[1:])] = (self.sval(ops[1]) & 0xffff) | (self.sval(ops[2]) & 0xffff) << 16
        elif name == "s_bfe_u64":
            control = self.sval(ops[2])
            offset, width = control & 63, (control >> 16) & 0x7f
            value = (self.s64(ops[1]) >> offset) & ((1 << width) - 1 if width < 64 else M64)
            self.set64(d, value)
            self.scc = int(value != 0)
        elif name == "s_bfe_u32":
            control = self.sval(ops[2])
            offset, width = control & 31, (control >> 16) & 0x7f
            value = (self.sval(ops[1]) >> offset) & ((1 << width) - 1)
            s[int(d[1:])] = value
            self.scc = int(value != 0)
        elif name in ("s_lshl_b32", "s_and_b32", "s_or_b32", "s_add_u32", "s_mul_i32", "s_lshr_b32"):
            a, b = self.sval(ops[1]), self.sval(ops[2])
            value = {"s_lshl_b32": a << (b & 31), "s_and_b32": a & b, "s_or_b32": a | b, "s_add_u32": a + b,
                     "s_mul_i32": a * b, "s_lshr_b32": a >> (b & 31)}[name]
            self.sset(d, value)
            if name == "s_add_u32":
                self.scc = int(value > M32)
            elif name != "s_mul_i32":
                self.scc = int(value & M32 != 0)
        elif name == "s_mulk_i32":
            s[int(d[1:])] = s[int(d[1:])] * int(ops[1], 0) & M32
        elif name == "s_lshl4_add_u32":
            value = (self.sval(ops[1]) << 4) + self.sval(ops[2])
            s[int(d[1:])] = value & M32
            self.scc = int(value > M32)
        elif name in ("s_cmp_lt_u32", "s_cmp_lg_i32", "s_cmp_eq_i32", "s_cmp_lg_u32", "s_cmp_eq_u32"):
            a, b = self.sval(ops[0]), self.sval(ops[1])
            self.scc = int({"lt": a < b, "lg": a != b, "eq": a == b}[name.split("_")[2]])
        elif name == "s_cselect_b32":
            s[int(d[1:])] = self.sval(ops[1]) if self.scc else self.sval(ops[2])
        elif name == "s_cselect_b64":
            self.set64(d, self.s64(ops[1]) if self.scc else self.s64(ops[2]))
        elif name in ("s_and_b64", "s_or_b64", "s_andn2_b64", "s_nand_b64"):
            a, b = self.s64(ops[1]), self.s64(ops[2])
            value = {"s_and_b64": a & b, "s_or_b64": a | b, "s_andn2_b64": a & ~b, "s_nand_b64": ~(a & b)}[name]
            self.set64(d, value)
            self.scc = int(value & M64 != 0)
        elif name == "s_not_b64":
            value = ~self.s64(ops[1]) & M64
            self.set64(d, value)
            self.scc = int(value != 0)
        elif name == "s_and_saveexec_b64":
            saved = self.exec
            self.exec = self.s64(ops[1]) & self.exec
            self.set64(d, saved)
            self.scc = int(self.exec != 0)
        elif name == "s_ff1_i32_b64":
            value = self.s64(ops[1])
            s[int(d[1:])] = (value & -value).bit_length() - 1 if value else M32
        elif name == "s_lshl_b64":
            self.set64(d, self.s64(ops[1]) << (self.sval(ops[2]) & 63))
        elif name.startswith("s_load_dword"):
            self.scalar_load(ops)
        elif name.startswith("s_buffer_load_dword"):
            base = [s[n] for n in self.span(ops[1])]
            assert base == [("cbv", j) for j in range(4)], base
            offset = 0 if ops[2] == "null" else int(ops[2], 0)
            for j, n in enumerate(self.span(ops[0])):
                s[n] = self.m.constants[offset // 4 + j]
        else:
            raise AssertionError(f"Model has no instruction {line}")

    def scalar_load(self, ops):
        s = self.s
        pointer = s[self.span(ops[1])[0]]
        offset = 0 if ops[2] == "null" else int(ops[2], 0)
        if pointer == ("ringtable",):
            ring = {0x50: "tf", 0x60: "offchip"}[offset]
            for j, n in enumerate(self.span(ops[0])):
                s[n] = ("ring", ring, j)
            return
        assert isinstance(pointer, tuple) and pointer[0] == "pointer", pointer
        table_high, entries = self.m.roles[pointer[1]][1:]
        assert s[self.span(ops[1])[1]] == table_high
        for j, n in enumerate(self.span(ops[0])):
            at = offset + 4 * j
            start = next(k for k in entries if k <= at < k + 16)
            entry = entries[start]
            s[n] = ("cbv", (at - start) // 4) if entry == ("constants",) else \
                self.m.descriptors[entry[1] + (at - start) // 4]

    def memory_op(self, head, ops, line):
        offsets = lambda: [int(x) for x in re.findall(r"offset\d?:(\d+)", line)]  # noqa: E731
        if head.startswith("ds_"):
            for lane in self.lanes():
                v = self.v[lane]
                if head.startswith("ds_write"):
                    address = v[int(ops[0][1:])]
                    if head == "ds_write2_b32":
                        m = re.search(r"offset0:(\d+)", line), re.search(r"offset1:(\d+)", line)
                        pairs = [(4 * int(m[0][1]) if m[0] else 0, ops[1]), (4 * int(m[1][1]) if m[1] else 0,
                                                                          ops[2].split()[0])]
                    else:
                        o = (offsets() or [0])[0]
                        regs = self.span(ops[1].split()[0])
                        pairs = [(o + 4 * j, f"v{r}") for j, r in enumerate(regs)]
                    for at, token in pairs:
                        self.lds[address + at:address + at + 4] = self.vval(lane, token).to_bytes(4, "little")
                elif head == "ds_and_b32":
                    address = v[int(ops[0][1:])]
                    old = int.from_bytes(self.lds[address:address + 4], "little")
                    self.lds[address:address + 4] = (old & v[int(ops[1].split()[0][1:])]).to_bytes(4, "little")
                elif head.startswith("ds_read"):
                    address = v[int(ops[1].split()[0][1:])]
                    dest = self.span(ops[0])
                    if head == "ds_read2_b32":
                        m = re.search(r"offset0:(\d+)", line), re.search(r"offset1:(\d+)", line)
                        at = [4 * int(m[0][1]) if m[0] else 0, 4 * int(m[1][1]) if m[1] else 0]
                    else:
                        o = (offsets() or [0])[0]
                        at = [o + 4 * j for j in range(len(dest))]
                    for n, a in zip(dest, at):
                        v[n] = int.from_bytes(self.lds[address + a:address + a + 4], "little")
                else:
                    raise AssertionError(f"Model has no instruction {line}")
            return
        # MUBUF: the rings (offen, soffset) or a vertex fetch (idxen).
        rsrc = [self.s[n] for n in self.span(ops[2])]
        if isinstance(rsrc[0], tuple) and rsrc[0][0] == "ring":
            ring = self.mem[rsrc[0][1]]
            soffset = self.sval(ops[3].split()[0])
            inst = next((int(x) for x in re.findall(r"offset:(\d+)", line)), 0)
            regs = self.span(ops[0])
            for lane in self.lanes():
                base = self.v[lane][int(ops[1][1:])] + soffset + inst
                for j, n in enumerate(regs):
                    if head.startswith("buffer_store"):
                        ring[base + 4 * j] = self.v[lane][n]
                    else:
                        self.v[lane][n] = ring.get(base + 4 * j, 0xdead0000 | (base + 4 * j) & 0xffff)
            return
        assert head.startswith("buffer_load"), line
        for lane in self.lanes():
            sregs = {n: self.s[n] for n in self.span(ops[2])}
            self.m.vertex.fetch(ops, self.v[lane], sregs, self.span)

    def vector(self, name, head, ops, line):
        d = ops[0]
        if name in ("v_cmp_eq_i32", "v_cmp_eq_u32", "v_cmp_gt_i32", "v_cmp_lt_f32", "v_cmp_ge_f32", "v_cmp_gt_f32",
                    "v_cmpx_eq_i32", "v_cmpx_eq_u32"):
            cmpx = name.startswith("v_cmpx")
            a_tok, b_tok = (ops[0], ops[1]) if cmpx else (ops[1], ops[2])
            mask = 0
            for lane in self.lanes():
                a, b = self.vval(lane, a_tok), self.vval(lane, b_tok)
                if ("cp1" in self.flaws and name.endswith(("eq_i32", "eq_u32")) and a == 0
                        and b_tok in self.inv_regs):
                    a = 1  # a wrong reference: invocation 1, not 0, writes the patch constants
                kind = name.split("_")[-1]
                op = name.split("_")[-2]
                if kind == "f32":
                    fa, fb = frac(a), frac(b)
                    ok = {"lt": fa < fb, "ge": fa >= fb, "gt": fa > fb}[op]
                else:
                    sa = a - (1 << 32) if kind == "i32" and a >> 31 else a
                    sb = b - (1 << 32) if kind == "i32" and b >> 31 else b
                    ok = {"eq": sa == sb, "gt": sa > sb}[op]
                mask |= int(ok) << lane
            if cmpx:
                self.exec &= mask
            elif head.endswith("_e64"):
                self.set64(d, mask)
            else:
                self.vcc = mask
            return
        if name == "v_readfirstlane_b32":
            lanes = self.lanes() or [0]
            self.s[int(d[1:])] = self.vval(lanes[0], ops[1])
            return
        if name in ("v_mbcnt_lo_u32_b32", "v_mbcnt_hi_u32_b32"):
            for lane in self.lanes():
                mask = self.sval(ops[1]) if not ops[1].startswith("v") else None
                assert mask == M32, line
                count = min(lane, 32) if name.endswith("lo_u32_b32") else max(lane - 32, 0)
                self.v[lane][int(d[1:])] = (count + self.vval(lane, ops[2])) & M32
            return
        for lane in self.lanes():
            v = self.v[lane]
            val = lambda t: self.vval(lane, t)  # noqa: E731
            if name == "v_mov_b32":
                v[int(d[1:])] = val(ops[1])
            elif name == "v_bfe_u32":
                v[int(d[1:])] = (val(ops[1]) >> (val(ops[2]) & 31)) & ((1 << (val(ops[3]) & 31)) - 1)
            elif name == "v_add_nc_u32":
                v[int(d[1:])] = (val(ops[1]) + val(ops[2])) & M32
            elif name == "v_lshlrev_b32":
                v[int(d[1:])] = (val(ops[2]) << (val(ops[1]) & 31)) & M32
            elif name == "v_lshlrev_b32_sdwa":
                assert "src1_sel:BYTE_0" in line
                v[int(d[1:])] = ((val(ops[2]) & 0xff) << (val(ops[1]) & 31)) & M32
            elif name == "v_mul_u32_u24_sdwa":
                assert "src1_sel:BYTE_0" in line
                v[int(d[1:])] = ((val(ops[1]) & 0xffffff) * (val(ops[2]) & 0xff)) & M32
            elif name == "v_mul_u32_u24":
                v[int(d[1:])] = ((val(ops[1]) & 0xffffff) * (val(ops[2]) & 0xffffff)) & M32
            elif name == "v_mad_u32_u24":
                v[int(d[1:])] = ((val(ops[1]) & 0xffffff) * (val(ops[2]) & 0xffffff) + val(ops[3])) & M32
            elif name == "v_lshl_add_u32":
                v[int(d[1:])] = ((val(ops[1]) << (val(ops[2]) & 31)) + val(ops[3])) & M32
            elif name == "v_lshrrev_b64":
                regs = self.span(ops[2])
                src = (self.s[regs[0]] | self.s[regs[1]] << 32) if ops[2].startswith("s") else \
                    (v[regs[0]] | v[regs[1]] << 32)
                value = src >> (val(ops[1]) & 63)
                dst = self.span(d)
                v[dst[0]], v[dst[1]] = value & M32, value >> 32 & M32
            elif name == "v_cndmask_b32":
                mask = self.vcc if len(ops) == 3 or ops[3] == "vcc" else self.s64(ops[3])
                v[int(d[1:])] = val(ops[2]) if mask >> lane & 1 else val(ops[1])
            elif name == "v_cvt_f32_u32":
                v[int(d[1:])] = _round(float(val(ops[1])))
            elif name == "v_mul_f32":
                v[int(d[1:])] = f32_mul(val(ops[1]), val(ops[2]))
            elif name == "v_add_f32":
                v[int(d[1:])] = f32_add(val(ops[1]), val(ops[2]))
            elif name == "v_sub_f32":
                v[int(d[1:])] = f32_add(val(ops[1]), val(ops[2]) ^ 0x80000000)
            elif name == "v_mad_f32":
                v[int(d[1:])] = f32_mad(val(ops[1]), val(ops[2]), val(ops[3]))
            elif name == "v_mac_f32":
                v[int(d[1:])] = f32_mad(val(ops[1]), val(ops[2]), v[int(d[1:])])
            elif name in ("v_max_f32", "v_min_f32", "v_max3_f32", "v_min3_f32"):
                words = [val(t) for t in ops[1:]]
                pick = max if "max" in name else min
                v[int(d[1:])] = pick(words, key=frac)
            else:
                raise AssertionError(f"Model has no instruction {line}")
        if name == "v_bfe_u32" and ops[1:] == ["v1", "8", "5"]:
            self.inv_regs.add(d)
        elif d in self.inv_regs:
            self.inv_regs.discard(d)


class Context:
    """What the waves read from the draw: the user-SGPR roles, constants, descriptors, push words, vertex memory."""

    def __init__(self, roles, constants, descriptors, push, memory, flaws=()):
        self.roles, self.constants, self.descriptors = roles, constants, descriptors
        self.push = list(push) + [0] * (32 - len(push))
        self.vertex = vc.Model(roles, constants, memory, (), descriptors, push, "ngg")
        self.export_word = self.vertex.export_word

    def user_sgprs(self, layout_word=0):
        s = {}
        for number, role in self.roles.items():
            if role[0] == "descriptors":
                s[number] = ("pointer", number)
            elif role[0] == "base_vertex":
                s[number] = 0
            elif role[0] == "inline":
                s[number] = self.push[role[1]]
            elif role[0] == "tcs_offchip_layout":
                s[number] = layout_word
        s[0], s[1] = ("ringtable",), ("ringtable",)
        return s


# --- the pipeline: LS+HS waves, the tessellator, TES waves ------------------------------------------------------------

FACTOR_WORDS = {"tri": 4, "quad": 6}  # the TF ring words of one patch (outer, then inner), D3D11 order
PIPELINE_FLAWS = {"factors_swapped", "winding_flipped", "domain_swapped"}
FLIPPED = {"triangle_cw": "triangle_ccw", "triangle_ccw": "triangle_cw"}


def canonical(triangle):
    """A triangle of records rotated so that its smallest record comes first: the same winding compares equal."""
    k = triangle.index(min(triangle))
    return triangle[k:] + triangle[:k]


def hs_waves(patches, state):
    """[(first patch, patch count)]: as many whole patches per wave as 64 lanes and the ring attribute stride hold."""
    n = state["output_control_points"]
    per = min(64 // n, state["attr_stride"] // (16 * n))
    return [(first, min(per, patches - first)) for first in range(0, patches, per)]


def run_hs_wave(lshs, ls_ctx, state, first, count, flaws):
    """One merged LS+HS wave of `count` patches starting at `first` (vertex ids first * N + lane): returns its memory
    (the TF ring and the off-chip ring). Entry registers as radv_shader_args.c declares them for gfx10 merged_vs_tcs:
    s0:s1 the ring table, s2 the off-chip offset, s3 merged_wave_info (LS vertices in bits 0..7, HS invocations in
    8..15), s4 the TF offset; v0 the patch id, v1 rel_patch_id | invocation << 8, v2 the vertex id, v3 the LS
    rel_patch_id, v5 the instance id."""
    n = state["output_control_points"]
    lanes = count * n
    sgprs = ls_ctx.user_sgprs()
    sgprs.update({2: 0, 3: lanes | lanes << 8, 4: 0})
    vgprs = [{0: first + lane // n, 1: lane // n | (lane % n) << 8, 2: first * n + lane, 3: lane // n, 4: 0, 5: 0}
             for lane in range(lanes)]
    memory = {"tf": {}, "offchip": {}}
    Wave(ls_ctx, sgprs, vgprs, M64, memory, flaws=flaws).run(lshs)
    return memory


def run_tes_wave(tes, tes_ctx, memory, first, lanes, flaws):
    """One NGG evaluation wave over `lanes` [(rel_patch_id, u, v)]: returns each lane's exports. s3 carries the lane
    count in bits 0..7, no primitives (the passthrough primitive export is the desktop's own assembly) and a nonzero
    wave id, so the GS_ALLOC_REQ message is not sent; v5, v6 the coordinates, v7 rel_patch_id, v8 the patch id."""
    sgprs = tes_ctx.user_sgprs()
    sgprs.update({2: 0, 3: len(lanes) | 1 << 24, 4: 0})
    swap = "domain_swapped" in flaws
    flaws = set(flaws) - PIPELINE_FLAWS
    vgprs = [{0: 0, 5: v if swap else u, 6: u if swap else v, 7: r, 8: first + r} for r, u, v in lanes]
    wave = Wave(tes_ctx, sgprs, vgprs, M64, memory, flaws=flaws)
    wave.run(tes)
    return [wave.exports.get(lane, {}) for lane in range(len(lanes))]


def draw_reference(lshs, tes, state, ls_ctx, tes_ctx, patches, tessellate, targets, flaws=()):
    """The console's draw of `patches` patches: (Counter of canonical triangles, each a tuple of three records, a
    record the export words of `targets` in order with unwritten components as None; the factor words per patch).
    tessellate(domain, partitioning, topology, [factor words]) -> [(points [(u, v)], triangles [(a, b, c)])] is the
    D3D11 reference tessellator."""
    flaws = set(flaws)
    wave_flaws = flaws - PIPELINE_FLAWS
    words = FACTOR_WORDS[state["domain"]]
    waves, factors = [], []
    for first, count in hs_waves(patches, state):
        memory = run_hs_wave(lshs, ls_ctx, state, first, count, wave_flaws)
        waves.append((first, count, memory))
        for r in range(count):
            row = [memory["tf"].get(4 * words * r + 4 * k) for k in range(words)]
            assert None not in row, f"patch {first + r}: the HS wave did not write its tessellation factors {row}"
            if "factors_swapped" in flaws:
                row[0], row[1] = row[1], row[0]
            factors.append(row)
    topology = FLIPPED[state["topology"]] if "winding_flipped" in flaws else state["topology"]
    tessellated = tessellate(state["domain"], state["partitioning"], topology, factors)
    out = Counter()
    for first, count, memory in waves:
        lanes, owner = [], []
        for r in range(count):
            points, _ = tessellated[first + r]
            lanes += [(r, u, v) for u, v in points]
            owner += [(first + r, k) for k in range(len(points))]
        records = {}
        for at in range(0, len(lanes), 64):
            exports = run_tes_wave(tes, tes_ctx, memory, first, lanes[at:at + 64], flaws)
            for key, lane in zip(owner[at:at + 64], exports):
                records[key] = tuple(word for target in targets for word in lane[target])
        for r in range(count):
            _, triangles = tessellated[first + r]
            for t in triangles:
                out[canonical(tuple(records[(first + r, k)] for k in t))] += 1
    return out, factors
