"""The register model: operand readers that turn a source token into an HLSL expression from the tracked
register values. Values are HLSL float names ("alu..", "sample.."), ("uint", expr) raw words, ints, lane
masks ("condition", name, j, width) and provenance markers (descriptor words, texture_ptr, interp_base)."""
import re
import struct


def registers(first, last, count):
    first, last = int(first), int(last)
    if last - first + 1 != count:
        raise ValueError("Descriptor or vector width mismatch")
    return range(first, last+1)

LANE_MASK = r"(vcc(?:_lo)?|s\d+|s\[\d+:\d+\])"


def sgpr_name(token):
    if not (m := re.fullmatch(r"s(\d+)", token)):
        raise ValueError(f"Expected a scalar register, got {token}")
    if not 0 <= int(m.group(1)) <= 105:
        raise ValueError(f"Scalar register out of range: {token}")
    return token


def sgpr_pair(token):
    if not (m := re.fullmatch(r"s\[(\d+):(\d+)\]", token)):
        raise ValueError(f"Expected a 64-bit scalar register pair, got {token}")
    regs = registers(*m.groups(), 2)
    if regs.start < 0 or regs.stop - 1 > 105 or regs.start % 2:
        raise ValueError(f"Invalid 64-bit scalar register pair: {token}")
    return [f"s{n}" for n in regs]


def vgprs(token, count):
    """Name the consecutive vector registers of a load destination: vN for one dword, v[N:M] for several."""
    if m := re.fullmatch(r"v\[(\d+):(\d+)\]", token):
        return [f"v{n}" for n in registers(*m.groups(), count)]
    if count != 1 or not re.fullmatch(r"v\d+", token):
        raise ValueError("Load destination width mismatch")
    return [token]


class DescriptorWord(tuple):
    """A descriptor word whose value the binding contract also supplies as data (docs/design/compute-stage.md,
    descriptor words as data): it is the provenance (tag, j) for every form that reads a descriptor (equal to that
    tuple), and `data` is its 32-bit value as a uint expression (a params[] word the harness writes), which
    scalar_u32 returns, so a SALU form reads it as any word (imageSize from the T#'s WIDTH and HEIGHT fields)."""

    def __new__(cls, value, data=None):
        word = super().__new__(cls, value)
        word.data = data
        return word


def scalar_u32(token, scalar, pending):
    if re.fullmatch(r"s\d+", token):
        sgpr_name(token)
        if token in pending:
            raise ValueError("Constant read before load completion")
        if token not in scalar:
            # An entry SGPR the binding contract does not name, or one never written: its value is unknown.
            raise ValueError(f"Read of unset scalar register {token}")
        value = scalar[token]
        if isinstance(value, int):
            return f"{value}u"
        if isinstance(value, tuple) and len(value) == 2 and value[0] == "uint":
            return value[1]
        if isinstance(value, DescriptorWord) and value.data is not None:
            return value.data
        raise ValueError(f"Expected a numeric scalar register: {token}")
    if re.fullmatch(r"-?\d+", token):
        value = int(token)
        if not -0x80000000 <= value <= 0xffffffff:
            raise ValueError(f"32-bit scalar immediate out of range: {token}")
        return f"{value & 0xffffffff}u"
    if re.fullmatch(r"0x[0-9a-f]{1,8}", token):
        return f"{int(token, 16)}u"
    if re.fullmatch(r"-?\d+\.\d+", token):
        bits, = struct.unpack("<I", struct.pack("<f", float(token)))
        return f"{bits}u"
    raise ValueError(f"Unsupported 32-bit scalar operand {token}")


def scalar_u64(token, scalar, pending, *, signed=False):
    if token.startswith("s["):
        lo, hi = sgpr_pair(token)
        return scalar_u32(lo, scalar, pending), scalar_u32(hi, scalar, pending)
    if re.fullmatch(r"-?\d+", token):
        value = int(token)
        if not -0x8000000000000000 <= value <= 0xffffffffffffffff:
            raise ValueError(f"64-bit scalar immediate out of range: {token}")
        bits = value & 0xffffffffffffffff
        return f"{bits & 0xffffffff}u", f"{bits >> 32}u"
    if re.fullmatch(r"0x[0-9a-f]{1,8}", token):
        value = int(token, 16)
        high = 0xffffffff if signed and (value & 0x80000000) else 0
        return f"{value}u", f"{high}u"
    raise ValueError(f"Unsupported 64-bit scalar operand {token}")


def lane_mask(token):
    """Name the registers of a per-lane condition for either wavefront width."""
    if token.startswith("vcc"):
        return ["vcc"]
    if m := re.fullmatch(r"s\[(\d+):(\d+)\]", token):
        return [f"s{n}" for n in registers(*m.groups(), 2)]
    return [token]


def fp_operand(token, scalar, vector, pending, sample_pending, *, quad_values=None):
    """quad_values: under whole-quad execution, the values defined on helper lanes (Lowering.quad_values); a VGPR
    source must then hold one of them."""
    if re.fullmatch(r"-\d+", token):
        return f"asfloat({int(token) & 0xffffffff}u)"
    if negated := re.fullmatch(r"neg\((\d+)\)", token):
        # LLVM's spelling of the neg modifier on an integer inline constant: the sign bit of its word flipped.
        return f"asfloat({(int(negated[1]) ^ 0x80000000) & 0xffffffff}u)"
    if token.startswith("-"):
        if token.startswith("--"):
            raise ValueError(f"Malformed modifier {token}")
        return "(-" + fp_operand(token[1:], scalar, vector, pending, sample_pending, quad_values=quad_values) + ")"
    if absolute := re.fullmatch(r"abs\(([^()|]+)\)|\|([^()|]+)\|", token):
        inner = absolute.group(1) or absolute.group(2)
        if inner.startswith("-") and not re.fullmatch(r"-\d+(?:\.\d+)?", inner):
            # LLVM prints |-2.0| for the absolute value of a negative inline constant; |-v1| it never prints.
            raise ValueError(f"Malformed modifier {token}")
        return f"abs({fp_operand(inner, scalar, vector, pending, sample_pending, quad_values=quad_values)})"
    if re.fullmatch(r"[vs]\d+", token):
        if token in pending:
            raise ValueError("Constant read before load completion")
        space = vector if token.startswith("v") else scalar
        if token not in space:
            raise ValueError(f"Read of unset {'vector' if token.startswith('v') else 'scalar'} register {token}")
        value = space[token]
        if quad_values is not None and token.startswith("v"):
            if not isinstance(value, str) or value not in quad_values:
                raise ValueError("Operand lacks a helper-lane definition")
        if isinstance(value, str) and value.startswith("uv."):
            return value  # the interpolated attr0.x or .y in whole-quad mode (forms/vintrp.py)
        if isinstance(value, int):
            return f"asfloat({value}u)"
        if isinstance(value, tuple) and len(value) == 2 and value[0] == "uint":
            if token in sample_pending and value[1].startswith("mem"):
                raise ValueError("Memory load used before vmcnt wait")
            return f"asfloat({value[1]})"
        if not isinstance(value, str) or not value.startswith(("sample", "alu")):
            raise ValueError("Expected a numeric register")
        if token in sample_pending and value.startswith("sample"):
            raise ValueError("Sample used before vmcnt wait")
        return value
    if re.fullmatch(r"0x[0-9a-f]{1,8}|\d+", token):
        return f"asfloat({int(token, 0)}u)"
    if re.fullmatch(r"\d+\.\d+", token):
        return token + "f"
    raise ValueError(f"Unsupported arithmetic operand {token}")

# Inline constants of 16-bit float operands (the ISA table, as LLVM prints them for gfx10): the binary16 value, so
# 1.0 is 0x3c00 and 1/(2*pi) is 0x3118. Integer inline constants -16..64 are the integer bit pattern in the low 16 bits.
F16_CONSTANT = {"0.5": 0x3800, "-0.5": 0xb800, "1.0": 0x3c00, "-1.0": 0xbc00, "2.0": 0x4000, "-2.0": 0xc000,
                "4.0": 0x4400, "-4.0": 0xc400, "0.15915494": 0x3118}


def f16_bits(token, scalar, vector, pending, sample_pending):
    """The low 16 bits of an unmodified source: a register's low half, an inline constant or a literal's low half."""
    if token in F16_CONSTANT:
        return f"{F16_CONSTANT[token]:#x}u"
    if re.fullmatch(r"-?\d+", token):
        if not -16 <= int(token) <= 64:
            raise ValueError(f"Integer inline constant out of range: {token}")
        return f"{int(token) & 0xffff:#x}u"
    if re.fullmatch(r"0x[0-9a-f]{1,4}", token):
        return f"{int(token, 16):#x}u"
    if re.fullmatch(r"[vs]\d+", token):
        return f"({word_of(token, scalar, vector, pending, sample_pending)} & 0xffffu)"
    raise ValueError(f"Unsupported 16-bit operand {token}")


def f16_operand(token, scalar, vector, pending, sample_pending):
    """A binary16 source widened to binary32. Negation and absolute value act on bit 15 of the 16-bit value, as in
    hardware, before widening."""
    return f"widen16({f16_encoding(token, scalar, vector, pending, sample_pending)})"


def f16_encoding(token, scalar, vector, pending, sample_pending):
    """The binary16 encoding of a source after its modifiers, as an unsigned expression: abs and neg act on bit 15."""
    if token in F16_CONSTANT or re.fullmatch(r"-\d+", token):
        return f16_bits(token, scalar, vector, pending, sample_pending)
    negate = token.startswith("-")
    body = token[1:] if negate else token
    absolute = re.fullmatch(r"\|([^|]+)\||abs\(([^()]+)\)", body)
    if absolute:
        body = absolute.group(1) or absolute.group(2)
    if body.startswith("-"):
        raise ValueError(f"Unsupported 16-bit operand {token}")
    bits = f16_bits(body, scalar, vector, pending, sample_pending)
    if absolute:
        bits = f"({bits} & 0x7fffu)"
    if negate:
        bits = f"({bits} ^ 0x8000u)"
    return bits


def f16_exponent(token, scalar, vector, pending, sample_pending):
    """The signed 16-bit exponent of v_ldexp_f16 as an int expression. Source modifiers and the inline float
    constants do not apply to an integer operand and are refused."""
    if re.fullmatch(r"-?\d+", token):
        if not -16 <= int(token) <= 64:
            raise ValueError(f"Integer inline constant out of range: {token}")
        return str(int(token))
    if re.fullmatch(r"0x[0-9a-f]{1,4}", token):
        value = int(token, 16)
        return str(value - 0x10000 if value & 0x8000 else value)
    if re.fullmatch(r"[vs]\d+", token):
        return f"((int({f16_bits(token, scalar, vector, pending, sample_pending)}) ^ 0x8000) - 0x8000)"
    raise ValueError(f"Unsupported exponent operand {token}")


# A raw 32-bit word held as an unsigned HLSL expression: a constant-buffer word or the result of a register move or
# select. These are tagged by name so that the places that accepted a tracked numeric value (a float string) before
# raw words had their own representation accept exactly the same registers now. jv_ and js_ are the join variables
# of control flow (docs/design/control-flow.md): raw 32-bit bits per register, declared where a branch or loop starts.
# exw is a masked write of a raw word over a raw word while the lane may be inactive (lowering.masked_writes). dppw is the
# sum or difference with carry of a DPP instruction (forms/dpp.py), a word that a later export may read as the float of its bits. f16w is a 16-bit result merged into the kept high half
# of its destination (forms/valu_float_rest.py). xw is a result of forms/valu_exact.py (ldexp, binary16 fma, 64-bit mad), computed on bit patterns.
RAW_WORD_PREFIXES = ("params[", "movw", "selw", "jv_", "js_", "exw", "dppw", "f16w", "xw")


class PackedPair(tuple):
    """The two binary32 values (low half, high half) a v_cvt_pkrtz_f16_f32 packed. The compressed export reads the pair
    itself; any other reader gets the word, whose helper `helpers` (the program's set of helper names) then receives, so
    a program that only exports the pair is unchanged."""
    helpers = None


PACK_WORD = "(pack16_rtz({0}) | (pack16_rtz({1}) << 16))"


def tracked_word(value):
    """The 32 bits of a tracked numeric register value as an unsigned expression, or None for any other value."""
    if isinstance(value, str) and value.startswith(("sample", "alu")):
        return f"asuint({value})"
    if isinstance(value, tuple) and len(value) == 2 and value[0] == "uint" and value[1].startswith(RAW_WORD_PREFIXES):
        return value[1]
    return None


def raw_source(token, scalar, vector):
    """Whether a plain source operand is a raw word: an integer literal, or a register that holds an integer word."""
    if re.fullmatch(r"-?\d+|0x[0-9a-f]{1,8}", token):
        return True
    if re.fullmatch(r"[vs]\d+", token):
        value = (vector if token.startswith("v") else scalar).get(token)
        return isinstance(value, int) or (isinstance(value, tuple) and len(value) == 2 and value[0] == "uint")
    return False


def word_of(token, scalar, vector, pending, sample_pending):
    """The 32 bits of a plain source operand: a raw word is read as the unsigned word it is, anything else through its
    float value."""
    if raw_source(token, scalar, vector):
        return vector_u32(token, scalar, vector, pending, sample_pending)
    return f"asuint({fp_operand(token, scalar, vector, pending, sample_pending)})"


def vector_u32(token, scalar, vector, pending, sample_pending):
    """Read a 32-bit operand of an integer vector instruction as an unsigned HLSL expression."""
    if re.fullmatch(r"v\d+", token):
        if token in pending:
            raise ValueError("Constant read before load completion")
        value = vector.get(token)
        if value is None:
            raise ValueError(f"Read of unset vector register {token}")
        if isinstance(value, tuple) and len(value) == 2 and value[0] == "uint":
            if token in sample_pending and value[1].startswith("mem"):
                raise ValueError("Memory load used before vmcnt wait")
            return value[1]
        if isinstance(value, PackedPair):
            if token in sample_pending and any(half.startswith("sample") for half in value):
                raise ValueError("Sample used before vmcnt wait")
            value.helpers.add("pack16_rtz")
            return PACK_WORD.format(*value)
        if not isinstance(value, str) or not value.startswith(("sample", "alu")):
            raise ValueError(f"Expected a numeric register: {token}")
        if token in sample_pending and value.startswith("sample"):
            raise ValueError("Sample used before vmcnt wait")
        return f"asuint({value})"
    if re.fullmatch(r"s\d+", token) and token not in scalar:
        raise ValueError(f"Read of unset scalar register {token}")
    return scalar_u32(token, scalar, pending)


def inactive(st):
    """Whether a form that writes only VGPRs must refuse because this lane may be inactive. The pixel stage refuses
    (CF-2a: those forms predate the masked-write rule there); the compute stage (docs/design/compute-stage.md, C-3)
    lowers them, and lowering.masked_writes keeps an inactive lane's old value in every VGPR they write."""
    return st.ex != "true" and st.stage == "pixel"
