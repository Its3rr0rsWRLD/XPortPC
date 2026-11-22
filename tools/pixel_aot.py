"""Offline lowering for a straight-line, texture-sampling gfx1013 pixel shader."""
import argparse
import ctypes as C
import hashlib
import json
import mmap
from pathlib import Path
import re
import struct
import tempfile
import zlib

from resource_inventory import parts


def inflate(data, size, window):
    if not 0 < size <= 16 << 20:
        raise ValueError("Invalid decoded size")
    decoder = zlib.decompressobj(window)
    image = decoder.decompress(data, size + 1)
    if len(image) != size or not decoder.eof:
        raise ValueError("Incomplete or mismatched compressed stream")
    return image


def _read_named_container(data: mmap.mmap, end: int) -> bytes:
    payload = end + 17
    if payload > len(data):
        raise ValueError("Missing or truncated named record")
    stored, _, repeat, size = struct.unpack_from("<4I", data, end + 1)
    if stored != repeat or not 0 < stored <= 8 << 20 or payload + stored > len(data):
        raise ValueError("Invalid record extent")
    return inflate(data[payload:payload + stored], size, -15)


def _select_named_container(data: mmap.mmap, needle: bytes, digest: str) -> bytes:
    selected = None
    cursor = 0
    while (pos := data.find(needle, cursor)) >= 0:
        # Advance past the name, independent of the candidate's claimed payload extent.
        cursor = pos + len(needle)
        try:
            blob = _read_named_container(data, cursor)
        except (ValueError, zlib.error):
            continue
        if hashlib.sha256(blob).hexdigest() == digest:
            if selected is not None:
                raise ValueError("Multiple records match the name and container SHA-256")
            selected = blob
    if selected is None:
        raise ValueError("No record matches the name and container SHA-256")
    return selected


def native_program(archive: Path, record: str, *, container_sha256: str | None = None) -> tuple[bytes, bytes]:
    name = record.encode("ascii")
    if not 0 < len(name) < 255 or b"\0" in name:
        raise ValueError("Invalid length-prefixed record name")
    needle = bytes([len(name) + 1]) + name + b"\0"
    if container_sha256 is not None and not re.fullmatch(r"[0-9a-fA-F]{64}", container_sha256):
        raise ValueError("Invalid decoded container SHA-256")
    with archive.open("rb") as f, mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as data:
        if container_sha256 is None:
            pos = data.find(needle)
            end = pos + len(needle)
            if pos < 0 or end + 17 > len(data):
                raise ValueError("Missing or truncated named record")
            if data.find(needle, end) >= 0:
                raise ValueError("Multiple records match the name")
            blob = _read_named_container(data, end)
        else:
            blob = _select_named_container(data, needle, container_sha256.lower())
    program = parts(blob)[b"DXIL"]
    if len(program) < 24 or struct.unpack_from("<H", program, 2)[0] != 0:
        raise ValueError("Expected a pixel shader")
    table = program.index(b"XDAT", 24)
    if table + 12 > len(program):
        raise ValueError("Truncated XDAT header")
    count, = struct.unpack_from("<I", program, table+4)
    if table + 12 + count*12 > len(program):
        raise ValueError("Truncated XDAT table")
    entries = struct.iter_unpack("<3I", program[table+12:table+12+count*12])
    native_entries = [(o, n) for tag, o, n in entries if tag == 13]
    if len(native_entries) != 1:
        raise ValueError("Expected one native program entry")
    offset, length = native_entries[0]
    if offset < table + 12 + count * 12 or offset+length > len(program) or length < 24 or program[offset:offset+4] != b"XBCH":
        raise ValueError("Invalid native program entry")
    size, = struct.unpack_from("<I", program, offset+16)
    image = inflate(program[offset+24:offset+length], size, 15)
    if len(image) < 196 or image[:4] != b"FSSM":
        raise ValueError("Invalid native program header")
    start = struct.unpack_from("<I", image, 192)[0] + 40
    if start < 196 or start % 4 or start + 4 > len(image):
        raise ValueError("Invalid native code offset")
    ends = [i+4 for i in range(start, len(image)-3, 4) if image[i:i+4] == b"\0\0\x81\xbf"]
    if len(ends) != 1:
        raise ValueError("Expected one aligned, terminated program")
    return blob, image[start:ends[0]]


def disassemble(code, library, *, cpu=b"gfx1013", offsets=False):
    llvm = C.CDLL(library)
    for component in ("TargetInfo", "Target", "TargetMC", "AsmPrinter", "Disassembler"):
        getattr(llvm, "LLVMInitializeAMDGPU" + component)()
    pointer, string = C.c_void_p, C.c_char_p
    llvm.LLVMCreateDisasmCPU.argtypes = [string, string, pointer, C.c_int, pointer, pointer]
    llvm.LLVMCreateDisasmCPU.restype = pointer
    llvm.LLVMDisasmInstruction.argtypes = [pointer, pointer, C.c_uint64, C.c_uint64, pointer, C.c_size_t]
    llvm.LLVMDisasmInstruction.restype = C.c_size_t
    llvm.LLVMDisasmDispose.argtypes = [pointer]
    ctx = llvm.LLVMCreateDisasmCPU(b"amdgcn--amdpal", cpu, None, 0, None, None)
    if not ctx:
        raise ValueError(f"LLVM has no {cpu.decode()} disassembler")
    raw = C.create_string_buffer(code)
    offset = 0
    instructions = []
    try:
        while offset < len(code):
            line = C.create_string_buffer(1024)
            size = llvm.LLVMDisasmInstruction(ctx, C.byref(raw, offset), len(code)-offset,
                                              offset, line, len(line))
            if not size:
                raise ValueError(f"Unknown instruction at byte {offset}")
            decoded = line.value.decode("ascii").strip()
            instructions.append((offset, decoded) if offsets else decoded)
            offset += size
    finally:
        llvm.LLVMDisasmDispose(ctx)
    return instructions


PREAMBLE = """Texture2D<float4> tex : register(t0);
SamplerState samp : register(s0);
// v_cmp_class_f32: the ten binary32 classes of LLVM SIInstrFlags::ClassFlags, from the raw encoding:
// signaling NaN, quiet NaN, -inf, -normal, -denormal, -0, +0, +denormal, +normal, +inf.
uint class32(float value) {
    uint bits = asuint(value);
    uint magnitude = bits & 0x7fffffffu;
    bool negative = bits >= 0x80000000u;
    if (magnitude > 0x7f800000u) return (bits & 0x00400000u) != 0u ? 0x2u : 0x1u;
    if (magnitude == 0x7f800000u) return negative ? 0x4u : 0x200u;
    if (magnitude >= 0x00800000u) return negative ? 0x8u : 0x100u;
    if (magnitude != 0u) return negative ? 0x10u : 0x80u;
    return negative ? 0x20u : 0x40u;
}
// v_fract_f32: x - floor(x) clamped to 0x3f7fffff, so a tiny negative input cannot round up to 1.0.
// D3D frac has no clamp and differs between adapters. NaN fails the comparison and propagates.
float fract32(float value) {
    float f = frac(value);
    return f >= 1.0f ? asfloat(0x3f7fffffu) : f;
}
// v_mad_f32 and v_mac_f32 round the product before the add and do not support binary32 denormals.
// Flush each operand, the product and the sum to signed zero; NaN fails the comparison and propagates.
float ftz32(float value) {
    return abs(value) < asfloat(0x00800000u) ? asfloat(asuint(value) & 0x80000000u) : value;
}
float mad32(float a, float b, float c) {
    precise float product = ftz32(ftz32(a) * ftz32(b));
    precise float sum = product + ftz32(c);
    return ftz32(sum);
}
// Finite binary32 to binary16, round toward zero, then widen for the float target.
float export16(float value) {
    uint h = f32tof16(value);
    if (abs(f16tof32(h)) > abs(value)) h--;
    return f16tof32(h);
}
// v_cvt_f32_f16: widen the binary16 in the low half of a word, built from its encoding so that
// desktop denormal handling cannot change it. Subnormal halves stay exact as m * 2^-24; NaN payloads widen.
float widen16(uint word) {
    uint h = word & 0xffffu;
    uint sign = (h & 0x8000u) << 16;
    uint exponent = (h >> 10) & 0x1fu;
    uint mantissa = h & 0x3ffu;
    if (exponent == 0u) {
        precise float magnitude = float(mantissa) * asfloat(0x33800000u);
        return sign != 0u ? -magnitude : magnitude;
    }
    uint wide = exponent == 0x1fu ? 0xffu : exponent + 112u;
    return asfloat(sign | (wide << 23) | (mantissa << 13));
}
// v_cvt_f16_f32: binary32 to the binary16 encoding, rounding to nearest even in integer arithmetic so that
// desktop conversion and denormal handling cannot change it. Overflow gives infinity, a binary16 subnormal
// result is kept, and a NaN keeps its sign and top payload bits with the quiet bit set.
uint narrow16(float value) {
    uint bits = asuint(value);
    uint sign = (bits >> 16) & 0x8000u;
    uint exponent = (bits >> 23) & 0xffu;
    uint mantissa = bits & 0x7fffffu;
    if (exponent == 0xffu) {
        return sign | 0x7c00u | (mantissa != 0u ? 0x200u | (mantissa >> 13) : 0u);
    }
    if (exponent < 102u) {
        return sign;
    }
    uint full = mantissa | 0x800000u;
    if (exponent < 113u) {
        uint shift = 126u - exponent;
        return sign | ((full + (1u << (shift - 1u)) - 1u + ((full >> shift) & 1u)) >> shift);
    }
    if (exponent > 142u) {
        return sign | 0x7c00u;
    }
    uint rounded = (full + 0xfffu + ((full >> 13) & 1u)) >> 13;
    return sign | min(((exponent - 113u) << 10) + rounded, 0x7c00u);
}
// v_ldexp_f16: scale a widened binary16 by 2^exponent. The exponent is a signed 16-bit value; clamping it to
// [-64, 64] changes no result. A nonzero binary16 magnitude lies in [2^-24, 2^16), so at 40 or more the product is
// at least 2^16 (infinity once narrowed) and at -41 or less it is below 2^-25 (zero), while in the clamped range the
// product stays inside the normal binary32 range and the power-of-two scale is exact. The scale is built from its
// encoding because exp2 is not exact on every adapter.
float ldexp16(float value, int exponent) {
    precise float scale = asfloat(uint(clamp(exponent, -64, 64) + 127) << 23);
    return value * scale;
}
// v_fract_f16: x - floor(x) is exact in binary32 for a binary16 input. As in fract32, the result stays below 1.0,
// here 0x3bff, so a tiny negative input cannot round up to 1.0; a NaN keeps its encoding and a NaN input gives NaN.
uint fract16(float value) {
    precise float f = value - floor(value);
    uint h = narrow16(f);
    return h == 0x3c00u ? 0x3bffu : h;
}
float4 main(float2 uv : TEXCOORD0) : SV_Target0 {"""


def registers(first, last, count):
    first, last = int(first), int(last)
    if last - first + 1 != count:
        raise ValueError("Descriptor or vector width mismatch")
    return range(first, last+1)


HINT_LIMITS = {"s_clause": 0x3f, "s_setprio": 3, "s_sleep": 0x7f}

ALU = {
    "log": (1, "log2({0})"), "exp": (1, "exp2({0})"), "rcp": (1, "(1.0f / {0})"),
    "sqrt": (1, "sqrt({0})"), "rsq": (1, "rsqrt({0})"),
    "floor": (1, "floor({0})"), "ceil": (1, "ceil({0})"), "fract": (1, "fract32({0})"),
    "trunc": (1, "trunc({0})"),
    "add": (2, "({0} + {1})"), "mul": (2, "({0} * {1})"),
    "max": (2, "max({0}, {1})"), "min": (2, "min({0}, {1})"), "sub": (2, "({0} - {1})"),
    "subrev": (2, "({1} - {0})"),
    "mul_legacy": (2, "(({0} == 0 || {1} == 0) ? 0.0f : {0} * {1})"),
    "fma": (3, "mad({0}, {1}, {2})"), "fmac": (3, "mad({0}, {1}, {2})"),
    "mad": (3, "mad32({0}, {1}, {2})"), "mac": (3, "mad32({0}, {1}, {2})"),
}
# Binary16 arithmetic on widened operands. Each operation is computed once in binary32 and narrowed once with
# narrow16. That equals rounding the exact result straight to binary16 for add, sub, mul, min, max, floor, ceil,
# trunc, rndne, fract and ldexp: binary32 has p' = 24 significant bits and binary16 has p = 11, and p' >= 2p + 2
# makes the double rounding innocuous for + - * (Figueroa), while the others are exact in binary32. round() is the
# round-half-even of DXIL.
F16_ALU = {
    "add": (2, "({0} + {1})"), "sub": (2, "({0} - {1})"), "subrev": (2, "({1} - {0})"), "mul": (2, "({0} * {1})"),
    "max": (2, "max({0}, {1})"), "min": (2, "min({0}, {1})"),
    "floor": (1, "floor({0})"), "ceil": (1, "ceil({0})"), "trunc": (1, "trunc({0})"), "rndne": (1, "round({0})"),
}
# N-prefixed predicates include unordered operands. Keep NLG's NaN case explicit in DXIL.
COMPARE = {
    "f": "false", "tru": "true",
    "lt": "{0} < {1}", "eq": "{0} == {1}", "le": "{0} <= {1}", "gt": "{0} > {1}",
    "lg": "({0} < {1} || {0} > {1})", "ge": "{0} >= {1}",
    "o": "({0} == {0} && {1} == {1})", "u": "({0} != {0} || {1} != {1})",
    "nge": "({0} < {1} || isnan({0}) || isnan({1}))", "nlg": "({0} == {1} || isnan({0}) || isnan({1}))",
    "ngt": "({0} <= {1} || isnan({0}) || isnan({1}))", "nle": "({0} > {1} || isnan({0}) || isnan({1}))",
    "neq": "!({0} == {1})", "nlt": "({0} >= {1} || isnan({0}) || isnan({1}))",
}
LANE_MASK = r"(vcc(?:_lo)?|s\d+|s\[\d+:\d+\])"
SALU_BIT64 = {
    "and": "uint2({0} & {2}, {1} & {3})",
    "or": "uint2({0} | {2}, {1} | {3})",
    "xor": "uint2({0} ^ {2}, {1} ^ {3})",
    "andn2": "uint2({0} & ~{2}, {1} & ~{3})",
    "orn2": "uint2({0} | ~{2}, {1} | ~{3})",
}
SALU_HELPERS = {
    "s_lshl_b64": (
        "uint2 s_lshl_b64(uint2 v, uint s) {\n"
        "    s &= 63u;\n"
        "    if (s == 0u) return v;\n"
        "    if (s < 32u) return uint2(v.x << s, (v.y << s) | (v.x >> (32u - s)));\n"
        "    return uint2(0u, v.x << (s - 32u));\n"
        "}"
    ),
    "s_lshr_b64": (
        "uint2 s_lshr_b64(uint2 v, uint s) {\n"
        "    s &= 63u;\n"
        "    if (s == 0u) return v;\n"
        "    if (s < 32u) return uint2((v.x >> s) | (v.y << (32u - s)), v.y >> s);\n"
        "    return uint2(v.y >> (s - 32u), 0u);\n"
        "}"
    ),
    "s_ashr_i64": (
        "uint2 s_ashr_i64(uint2 v, uint s) {\n"
        "    s &= 63u;\n"
        "    if (s == 0u) return v;\n"
        "    if (s < 32u) return uint2((v.x >> s) | (v.y << (32u - s)), asuint(asint(v.y) >> s));\n"
        "    return uint2(asuint(asint(v.y) >> (s - 32u)), asuint(asint(v.y) >> 31));\n"
        "}"
    ),
    "s_bfm_b64": (
        "uint2 s_bfm_b64(uint width, uint offset) {\n"
        "    uint w = width & 63u;\n"
        "    uint2 m = uint2(0u, 0u);\n"
        "    if (w > 0u && w < 32u) m = uint2((1u << w) - 1u, 0u);\n"
        "    else if (w == 32u) m = uint2(0xffffffffu, 0u);\n"
        "    else if (w > 32u) m = uint2(0xffffffffu, (1u << (w - 32u)) - 1u);\n"
        "    return s_lshl_b64(m, offset);\n"
        "}"
    ),
    # 32x32 -> 64 products without 64-bit HLSL types: 16-bit partial products, carries summed in the middle word.
    "mul_hi_u32": (
        "uint mul_hi_u32(uint a, uint b) {\n"
        "    uint a0 = a & 0xffffu, a1 = a >> 16, b0 = b & 0xffffu, b1 = b >> 16;\n"
        "    uint p00 = a0 * b0, p01 = a0 * b1, p10 = a1 * b0, p11 = a1 * b1;\n"
        "    uint mid = (p00 >> 16) + (p01 & 0xffffu) + (p10 & 0xffffu);\n"
        "    return p11 + (p01 >> 16) + (p10 >> 16) + (mid >> 16);\n"
        "}"
    ),
    # Signed high word = unsigned high word minus b when a is negative and minus a when b is negative (mod 2^32).
    "mul_hi_i32": (
        "uint mul_hi_i32(uint a, uint b) {\n"
        "    return mul_hi_u32(a, b) - (asint(a) < 0 ? b : 0u) - (asint(b) < 0 ? a : 0u);\n"
        "}"
    ),
    # Saturating forms of the VOP3 clamp bit on integer add and subtract (LLVM saddsat/ssubsat patterns).
    "v_add_sat_u32": "uint v_add_sat_u32(uint a, uint b) {\n    uint r = a + b;\n    return r < a ? 0xffffffffu : r;\n}",
    "v_sub_sat_u32": "uint v_sub_sat_u32(uint a, uint b) {\n    return a >= b ? a - b : 0u;\n}",
    "v_add_sat_i32": (
        "uint v_add_sat_i32(uint a, uint b) {\n"
        "    uint r = a + b;\n"
        "    if (((a ^ r) & (b ^ r)) >> 31 != 0u) return (a >> 31) != 0u ? 0x80000000u : 0x7fffffffu;\n"
        "    return r;\n"
        "}"
    ),
    "v_sub_sat_i32": (
        "uint v_sub_sat_i32(uint a, uint b) {\n"
        "    uint r = a - b;\n"
        "    if (((a ^ b) & (a ^ r)) >> 31 != 0u) return (a >> 31) != 0u ? 0x80000000u : 0x7fffffffu;\n"
        "    return r;\n"
        "}"
    ),
    "s_bfe_u32": (
        "uint s_bfe_u32(uint src, uint ctrl) {\n"
        "    uint off = ctrl & 31u;\n"
        "    uint w = (ctrl >> 16) & 127u;\n"
        "    if (w == 0u) return 0u;\n"
        "    if (off + w < 32u) return (src << (32u - off - w)) >> (32u - w);\n"
        "    return src >> off;\n"
        "}"
    ),
    "s_bfe_i32": (
        "uint s_bfe_i32(uint src, uint ctrl) {\n"
        "    uint off = ctrl & 31u;\n"
        "    uint w = (ctrl >> 16) & 127u;\n"
        "    if (w == 0u) return 0u;\n"
        "    if (off + w < 32u) return asuint(asint(src << (32u - off - w)) >> (32u - w));\n"
        "    return asuint(asint(src) >> off);\n"
        "}"
    ),
}


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


def scalar_u32(token, scalar, pending):
    if re.fullmatch(r"s\d+", token):
        sgpr_name(token)
        if token in pending:
            raise ValueError("Constant read before load completion")
        value = scalar[token]
        if isinstance(value, int):
            return f"{value}u"
        if isinstance(value, tuple) and len(value) == 2 and value[0] == "uint":
            return value[1]
        if isinstance(value, str) and value.startswith("params["):
            return f"asuint({value})"
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


def fp_operand(token, scalar, vector, pending, sample_pending):
    if re.fullmatch(r"-\d+", token):
        return f"asfloat({int(token) & 0xffffffff}u)"
    if token.startswith("-"):
        return "(-" + fp_operand(token[1:], scalar, vector, pending, sample_pending) + ")"
    if absolute := re.fullmatch(r"abs\(([^()|]+)\)|\|([^()|]+)\|", token):
        inner = absolute.group(1) or absolute.group(2)
        return f"abs({fp_operand(inner, scalar, vector, pending, sample_pending)})"
    if re.fullmatch(r"[vs]\d+", token):
        if token in pending:
            raise ValueError("Constant read before load completion")
        value = (vector if token.startswith("v") else scalar)[token]
        if isinstance(value, int):
            return f"asfloat({value}u)"
        if isinstance(value, tuple) and len(value) == 2 and value[0] == "uint":
            return f"asfloat({value[1]})"
        if not isinstance(value, str) or not value.startswith(("sample", "alu", "params[")):
            raise ValueError("Expected a numeric register")
        if sample_pending and value.startswith("sample"):
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
        return f"(asuint({fp_operand(token, scalar, vector, pending, sample_pending)}) & 0xffffu)"
    raise ValueError(f"Unsupported 16-bit operand {token}")


def f16_operand(token, scalar, vector, pending, sample_pending):
    """A binary16 source widened to binary32. Negation and absolute value act on bit 15 of the 16-bit value, as in
    hardware, before widening."""
    if token in F16_CONSTANT or re.fullmatch(r"-\d+", token):
        return f"widen16({f16_bits(token, scalar, vector, pending, sample_pending)})"
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
    return f"widen16({bits})"


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


def vector_u32(token, scalar, vector, pending, sample_pending):
    """Read a 32-bit operand of an integer vector instruction as an unsigned HLSL expression."""
    if re.fullmatch(r"v\d+", token):
        if token in pending:
            raise ValueError("Constant read before load completion")
        value = vector.get(token)
        if value is None:
            raise ValueError(f"Read of unset vector register {token}")
        if isinstance(value, tuple) and len(value) == 2 and value[0] == "uint":
            return value[1]
        if not isinstance(value, str) or not value.startswith(("sample", "alu", "params[")):
            raise ValueError(f"Expected a numeric register: {token}")
        if sample_pending and value.startswith("sample"):
            raise ValueError("Sample used before vmcnt wait")
        return f"asuint({value})"
    if re.fullmatch(r"s\d+", token) and token not in scalar:
        raise ValueError(f"Read of unset scalar register {token}")
    return scalar_u32(token, scalar, pending)


# SDWA selections: (bit offset, width). A source selection is zero-extended, or sign-extended with sext();
# a destination selection writes the low bits of the result into that field. Following the equivalences in
# LLVM's SIPeepholeSDWA, UNUSED_PAD zeroes the other bits and UNUSED_PRESERVE keeps them from the destination.
SDWA_SEL = {"BYTE_0": (0, 8), "BYTE_1": (8, 8), "BYTE_2": (16, 8), "BYTE_3": (24, 8),
            "WORD_0": (0, 16), "WORD_1": (16, 16), "DWORD": (0, 32)}
# Exact arithmetic with SDWA forms on gfx1013 (docs/coverage/gfx1013.tsv).
SDWA_ALU = ("add", "sub", "subrev", "mul", "mul_legacy", "max", "min", "floor", "ceil", "fract", "trunc")


def sdwa_source(word, sel, sext):
    offset, width = SDWA_SEL[sel]
    if width == 32:
        return word
    if sext:
        return f"asuint(asint({word} << {32 - offset - width}u) >> {32 - width}u)"
    return f"(({word} >> {offset}u) & {(1 << width) - 1:#x}u)"


def sdwa_dest(result, sel, unused, old):
    offset, width = SDWA_SEL[sel]
    if width == 32:
        return result
    if unused == "UNUSED_SEXT":
        raise ValueError("UNUSED_SEXT is not lowered")
    field = f"(({result} & {(1 << width) - 1:#x}u) << {offset}u)"
    if unused == "UNUSED_PAD":
        return field
    # The kept bits must come from a tracked numeric value; hardware would keep whatever an untracked register holds.
    if not (isinstance(old, str) and old.startswith(("sample", "alu", "params["))):
        raise ValueError("UNUSED_PRESERVE needs a tracked numeric destination")
    keep = ~(((1 << width) - 1) << offset) & 0xffffffff
    return f"((asuint({old}) & {keep:#x}u) | {field})"


# Integer add, subtract, multiply and three-input forms. Semantics: AMD RDNA 2 ISA guide (instruction pseudocode in
# the VOP2/VOP3 sections): V_ADD_NC_U32 D=S0+S1, V_SUB_NC_U32 D=S0-S1, V_SUBREV_NC_U32 D=S1-S0, V_MUL_U32_U24
# D=S0.u[23:0]*S1.u[23:0], V_MUL_I32_I24 D=S0.i[23:0]*S1.i[23:0], V_MUL_HI_U32_U24 D=(S0.u24*S1.u24)>>32,
# V_MUL_HI_I32_I24 D=(S0.i24*S1.i24)>>32, V_MUL_HI_U32/V_MUL_HI_I32 D=(S0*S1)>>32, V_MUL_LO_U32 D=(S0*S1)[31:0],
# V_MAD_U32_U24 D=S0.u[23:0]*S1.u[23:0]+S2, V_MAD_I32_I24 D=S0.i[23:0]*S1.i[23:0]+S2, V_ADD3_U32 D=S0+S1+S2,
# V_LSHL_ADD_U32 D=(S0<<S1[4:0])+S2, V_ADD_LSHL_U32 D=(S0+S1)<<S2[4:0], V_LSHL_OR_B32 D=(S0<<S1[4:0])|S2,
# V_AND_OR_B32 D=(S0&S1)|S2, V_OR3_B32 D=S0|S1|S2, V_XOR3_B32 D=S0^S1^S2, V_XAD_U32 D=(S0^S1)+S2,
# V_ADD_NC_I32 D=S0+S1, V_SUB_NC_I32 D=S0-S1. Shift counts are the bit slice [4:0], so they are masked to five bits.
# Results wrap. The VOP3 clamp bit saturates the add and subtract forms (LLVM VOP3Instructions.td maps saddsat and
# ssubsat to V_ADD_I32_e64/V_SUB_I32_e64 with clamp); it is accepted only there, never on the multiplies, which
# llvm-mc assembles with clamp but whose saturation point is not established here.
INT_VOP2 = ("add_nc_u32", "sub_nc_u32", "subrev_nc_u32", "mul_u32_u24", "mul_i32_i24", "mul_hi_u32_u24", "mul_hi_i32_i24")
INT_VOP3 = ("add_nc_i32", "sub_nc_i32", "mul_lo_u32", "mul_hi_u32", "mul_hi_i32")
INT_CLAMPED = ("add_nc_u32", "sub_nc_u32", "subrev_nc_u32", "add_nc_i32", "sub_nc_i32")
INT_TERNARY = ("mad_u32_u24", "mad_i32_i24", "add3_u32", "lshl_add_u32", "add_lshl_u32", "lshl_or_b32", "and_or_b32",
               "or3_b32", "xor3_b32", "xad_u32")


def sext24(word):
    return f"asuint(asint({word} << 8u) >> 8)"


def int_binary(op, a, b, clamp, helpers):
    """HLSL uint expression for a two-source integer form; a and b are the first and second source words."""
    if clamp:
        name = {"add_nc_u32": "v_add_sat_u32", "sub_nc_u32": "v_sub_sat_u32", "subrev_nc_u32": "v_sub_sat_u32",
                "add_nc_i32": "v_add_sat_i32", "sub_nc_i32": "v_sub_sat_i32"}[op]
        helpers.add(name)
        return f"{name}({b}, {a})" if op == "subrev_nc_u32" else f"{name}({a}, {b})"
    if op.startswith("mul_hi"):
        helpers.update(("mul_hi_u32", "mul_hi_i32") if op.endswith("i32") or op.endswith("i24") else ("mul_hi_u32",))
    return {
        "add_nc_u32": f"({a} + {b})", "add_nc_i32": f"({a} + {b})",
        "sub_nc_u32": f"({a} - {b})", "sub_nc_i32": f"({a} - {b})", "subrev_nc_u32": f"({b} - {a})",
        "mul_u32_u24": f"(({a} & 0xffffffu) * ({b} & 0xffffffu))",
        "mul_i32_i24": f"({sext24(a)} * {sext24(b)})",
        "mul_hi_u32_u24": f"mul_hi_u32({a} & 0xffffffu, {b} & 0xffffffu)",
        "mul_hi_i32_i24": f"mul_hi_i32({sext24(a)}, {sext24(b)})",
        "mul_lo_u32": f"({a} * {b})", "mul_hi_u32": f"mul_hi_u32({a}, {b})", "mul_hi_i32": f"mul_hi_i32({a}, {b})",
    }[op]


def int_ternary(op, a, b, c):
    return {
        "mad_u32_u24": f"((({a} & 0xffffffu) * ({b} & 0xffffffu)) + {c})",
        "mad_i32_i24": f"(({sext24(a)} * {sext24(b)}) + {c})",
        "add3_u32": f"({a} + {b} + {c})",
        "lshl_add_u32": f"(({a} << ({b} & 31u)) + {c})",
        "add_lshl_u32": f"(({a} + {b}) << ({c} & 31u))",
        "lshl_or_b32": f"(({a} << ({b} & 31u)) | {c})",
        "and_or_b32": f"(({a} & {b}) | {c})",
        "or3_b32": f"({a} | {b} | {c})",
        "xor3_b32": f"({a} ^ {b} ^ {c})",
        "xad_u32": f"(({a} ^ {b}) + {c})",
    }[op]


def lower(instructions, texture_sgpr, interp_sgpr, sampler, constant_descriptor=None, *, second_texture_offset=None):
    """Track descriptor provenance, interpolation and packed exports through register writes."""
    if (texture_sgpr == interp_sgpr or not 0 <= texture_sgpr <= 105 or not 0 <= interp_sgpr <= 105
            or len(sampler) != 4 or any(not 0 <= word <= 0xffffffff for word in sampler)):
        raise ValueError("Invalid scalar inputs or sampler descriptor words")
    scalar = {f"s{texture_sgpr}": "texture_ptr", f"s{interp_sgpr}": "interp_base"}
    vector = {"v0": "bary_i", "v1": "bary_j"}
    lines = [PREAMBLE]
    if constant_descriptor is not None:
        if constant_descriptor < 0 or constant_descriptor % 4:
            raise ValueError("Invalid constant descriptor offset")
        lines.insert(0, "cbuffer Constants : register(b0) { float4 params[16]; };")
    bindings = {0: "tex"}
    if second_texture_offset is not None:
        if second_texture_offset < 32 or second_texture_offset % 32:
            raise ValueError("Second texture descriptor must have a distinct aligned offset")
        bindings[second_texture_offset] = "tex1"
        lines.insert(0, "Texture2D<float4> tex1 : register(t1);")
    if constant_descriptor is not None and any(
            start < constant_descriptor + 16 and constant_descriptor < start + 32 for start in bindings):
        raise ValueError("Texture and constant descriptors overlap")
    pending = set()
    scc = None
    helpers = set()
    mask = "entry"
    samples = 0
    sample_pending = False
    sample_dest = set()
    exported = False
    ended = False
    for i, line in enumerate(instructions):
        def match(pattern):
            return re.fullmatch(pattern, line)

        if ended:
            raise ValueError("Instruction follows program end")
        if exported and line != "s_endpgm":
            raise ValueError("Unexpected instruction after color export")
        if match(r"(?:s_inst_prefetch|s_nop) (?:0x[0-9a-f]+|\d+)"):
            continue
        # Scheduling hints with no effect on results. Each operand is limited to the width
        # of its RDNA 2 field: clause length minus one, wave priority and sleep duration.
        if m := match(r"(s_clause|s_setprio|s_sleep) (0x[0-9a-f]+|\d+)"):
            if int(m[2], 0) > HINT_LIMITS[m[1]]:
                raise ValueError(f"Invalid {m[1]} operand")
            continue
        if line == "s_waitcnt lgkmcnt(0)":
            pending.clear()
        elif line == "s_waitcnt vmcnt(0)":
            sample_pending = False
            sample_dest.clear()
        elif m := match(r"s_mov_b64 s\[(\d+):(\d+)\], exec"):
            regs = registers(*m.groups(), 2)
            for n in regs:
                if f"s{n}" in pending:
                    raise ValueError("Write overlaps an outstanding scalar load")
                scalar[f"s{n}"] = (mask, n-regs.start)
        elif line == "s_wqm_b64 exec, exec" and mask == "entry":
            mask = "quad"
            scc = None
        elif m := match(r"s_and_b64 exec, exec, s\[(\d+):(\d+)\]"):
            pair = registers(*m.groups(), 2)
            if mask != "quad" or [scalar.get(f"s{n}") for n in pair] != [("entry",0),("entry",1)]:
                raise ValueError("Unsupported execution mask")
            mask = "entry"
            scc = None
        elif m := match(r"s_(cmov|not|brev)_b64 (s\[\d+:\d+\]), ([^,]+)"):
            op, dst, src = m.groups()
            regs = sgpr_pair(dst)
            if pending.intersection(regs):
                raise ValueError("Write overlaps an outstanding scalar load")
            s0, s1 = scalar_u64(src, scalar, pending)
            if op == "cmov":
                if scc is None:
                    raise ValueError("Conditional move requires a tracked SCC")
                d0, d1 = scalar_u64(dst, scalar, pending)
                expr = f"({scc} ? uint2({s0}, {s1}) : uint2({d0}, {d1}))"
            elif op == "not":
                expr = f"uint2(~{s0}, ~{s1})"
            else:
                expr = f"uint2(reversebits({s1}), reversebits({s0}))"
            lines.append(f"    uint2 salu{i} = {expr};")
            scalar[regs[0]], scalar[regs[1]] = ("uint", f"salu{i}.x"), ("uint", f"salu{i}.y")
            if op == "not":
                scc = f"((salu{i}.x | salu{i}.y) != 0u)"
        elif m := match(rf"s_({'|'.join(SALU_BIT64)})_b64 (s\[\d+:\d+\]), ([^,]+), ([^,]+)"):
            op, dst, src0, src1 = m.groups()
            regs = sgpr_pair(dst)
            if pending.intersection(regs):
                raise ValueError("Write overlaps an outstanding scalar load")
            a0, a1 = scalar_u64(src0, scalar, pending)
            b0, b1 = scalar_u64(src1, scalar, pending)
            lines.append(f"    uint2 salu{i} = {SALU_BIT64[op].format(a0, a1, b0, b1)};")
            scalar[regs[0]], scalar[regs[1]] = ("uint", f"salu{i}.x"), ("uint", f"salu{i}.y")
            scc = f"((salu{i}.x | salu{i}.y) != 0u)"
        elif m := match(r"(s_lshl_b64|s_lshr_b64|s_ashr_i64|s_bfm_b64) (s\[\d+:\d+\]), ([^,]+), ([^,]+)"):
            op, dst, src0, src1 = m.groups()
            regs = sgpr_pair(dst)
            if pending.intersection(regs):
                raise ValueError("Write overlaps an outstanding scalar load")
            shift = scalar_u32(src1, scalar, pending)
            if op == "s_bfm_b64":
                width = scalar_u32(src0, scalar, pending)
                helpers.update(("s_lshl_b64", "s_bfm_b64"))
                expr = f"s_bfm_b64({width}, {shift})"
            else:
                a0, a1 = scalar_u64(src0, scalar, pending, signed=(op == "s_ashr_i64"))
                helpers.add(op)
                expr = f"{op}(uint2({a0}, {a1}), {shift})"
            lines.append(f"    uint2 salu{i} = {expr};")
            scalar[regs[0]], scalar[regs[1]] = ("uint", f"salu{i}.x"), ("uint", f"salu{i}.y")
            if op != "s_bfm_b64":
                scc = f"((salu{i}.x | salu{i}.y) != 0u)"
        elif m := match(r"(s_bfe_u32|s_bfe_i32) (s\d+), ([^,]+), ([^,]+)"):
            op, dst, src0, src1 = m.groups()
            sgpr_name(dst)
            if dst in pending:
                raise ValueError("Write overlaps an outstanding scalar load")
            a = scalar_u32(src0, scalar, pending)
            b = scalar_u32(src1, scalar, pending)
            helpers.add(op)
            lines.append(f"    uint salu{i} = {op}({a}, {b});")
            scalar[dst] = ("uint", f"salu{i}")
            scc = f"(salu{i} != 0u)"
        elif m := match(r"(s_mov_b32|s_movk_i32) (s\d+|m0), (s\d+|0x[0-9a-f]+|\d+)"):
            op, dst, src = m.groups()
            if src in pending or dst in pending:
                raise ValueError("Unresolved scalar memory dependency")
            val = scalar[src] if src.startswith("s") else int(src, 0)
            if op == "s_movk_i32":
                if not isinstance(val, int) or not 0 <= val <= 0xffff:
                    raise ValueError("Invalid movk immediate")
                val = (val if val < 0x8000 else val - 0x10000) & 0xffffffff
            scalar[dst] = val
        elif m := match(r"s_load_dwordx8 s\[(\d+):(\d+)\], s\[(\d+):(\d+)\], (null|0x[0-9a-f]+)"):
            dst = registers(*m.groups()[:2], 8)
            addr = registers(*m.groups()[2:4], 2)
            offset = 0 if m[5] == "null" else int(m[5], 16)
            if offset not in bindings:
                raise ValueError("Unbound texture descriptor offset")
            if any(f"s{n}" in pending for n in (*addr, *dst)) or [scalar.get(f"s{n}") for n in addr] != ["texture_ptr", 0]:
                raise ValueError("Texture address differs from binding contract")
            for j, n in enumerate(dst):
                scalar[f"s{n}"] = (bindings[offset], j)
                pending.add(f"s{n}")
        elif m := match(r"(?:(s_load_dwordx4|s_buffer_load_dwordx4) s\[(\d+):(\d+)\]|s_buffer_load_dword s(\d+))"
                        r", s\[(\d+):(\d+)\], (0x[0-9a-f]+|null)"):
            op, first, last, single, low, high, imm = m.groups()
            offset = 0 if imm == "null" else int(imm, 16)
            descriptor = op == "s_load_dwordx4"
            if single is not None and (int(single) > 105 or int(low) % 4 or int(high) > 105):
                raise ValueError("Invalid scalar buffer registers")
            dst = registers(single, single, 1) if single is not None else registers(first, last, 4)
            base = [f"s{n}" for n in registers(low, high, 2 if descriptor else 4)]
            expected = ["texture_ptr", 0] if descriptor else [("cbv", n) for n in range(4)]
            if constant_descriptor is None or pending.intersection(base) or [scalar.get(r) for r in base] != expected:
                raise ValueError("Unresolved constant buffer binding")
            if descriptor and offset != constant_descriptor:
                raise ValueError("Constant descriptor differs from binding contract")
            if not descriptor and (offset % 4 or offset + 4 * len(dst) > 256):
                raise ValueError("Constant read exceeds binding or is unaligned")
            for j, n in enumerate(dst):
                if f"s{n}" in pending:
                    raise ValueError("Write overlaps an outstanding scalar load")
                word = offset // 4 + j
                scalar[f"s{n}"] = ("cbv", j) if descriptor else f"params[{word // 4}].{'xyzw'[word % 4]}"
                pending.add(f"s{n}")
        elif m := match(r"v_cube(id|sc|tc|ma)_f32(?:_e64)? (v\d+), ([^,]+), ([^,]+), ([^,]+?)( clamp)?"):
            # LLVM ConstantFoldAMDGCNCubeIntrinsic: z, then y, then x is the major axis; a face is negative
            # only for a nonzero, non-NaN negative coordinate.
            op, dst, *tokens, clamp = m.groups()
            if mask != "entry":
                raise ValueError("Invalid cube operation")
            if dst in sample_dest:
                raise ValueError("Write overlaps an outstanding sample")
            x, y, z = [fp_operand(t, scalar, vector, pending, sample_pending) for t in tokens]
            lines.append(f"    precise float3 cube{i} = float3({x}, {y}, {z});")
            c, a = f"cube{i}", f"abs(cube{i})"
            zmajor = f"({a}.z >= {a}.x && {a}.z >= {a}.y)"
            ymajor = f"({a}.y >= {a}.x)"
            expression = {
                "id": f"({zmajor} ? ({c}.z < 0.0f ? 5.0f : 4.0f) : {ymajor} ? ({c}.y < 0.0f ? 3.0f : 2.0f) : ({c}.x < 0.0f ? 1.0f : 0.0f))",
                "sc": f"({zmajor} ? ({c}.z < 0.0f ? -{c}.x : {c}.x) : {ymajor} ? {c}.x : ({c}.x < 0.0f ? {c}.z : -{c}.z))",
                "tc": f"({zmajor} ? -{c}.y : {ymajor} ? ({c}.y < 0.0f ? -{c}.z : {c}.z) : -{c}.y)",
                "ma": f"(({zmajor} ? {c}.z : {ymajor} ? {c}.y : {c}.x) * 2.0f)",
            }[op]
            if clamp:
                expression = f"saturate({expression})"
            vector[dst] = f"alu{i}"
            lines.append(f"    precise float alu{i} = {expression};")
        elif m := match(r"v_interp_p([12])_f32_e32 (v\d+), (v\d+), attr0\.([xy])"):
            phase, dst, src, component = m.groups()
            if mask != "quad" or scalar.get("m0") != "interp_base":
                raise ValueError("Unknown interpolation context")
            if phase == "1" and vector[src] == "bary_i":
                vector[dst] = ("partial", component)
            elif phase == "2" and vector[src] == "bary_j" and vector[dst] == ("partial", component):
                vector[dst] = f"uv.{component}"
            else:
                raise ValueError("Unpaired interpolation")
        elif m := match(r"image_sample v\[(\d+):(\d+)\], v\[(\d+):(\d+)\], s\[(\d+):(\d+)\], s\[(\d+):(\d+)\] dmask:0xf dim:SQ_RSRC_IMG_2D"):
            operands = m.groups()
            dest, coords, image, state = [registers(*operands[k:k+2], width)
                                          for k, width in zip((0,2,4,6), (4,2,8,4))]
            descriptor = [scalar.get(f"s{n}") for n in image]
            texture = next((name for name in bindings.values() if descriptor == [(name, j) for j in range(8)]), None)
            if (mask != "entry" or any(f"s{n}" in pending for n in (*image, *state))
                    or texture is None
                    or [scalar.get(f"s{n}") for n in state] != list(sampler)):
                raise ValueError("Unsupported image or sampler binding")
            uv = [vector[f"v{n}"] for n in coords]
            if any(v not in ("uv.x", "uv.y") for v in uv):
                raise ValueError("Unsupported texture coordinate")
            lines.append(f"    float4 sample{i} = {texture}.Sample(samp, float2({', '.join(uv)}));")
            samples += 1
            sample_pending = True
            for j, n in enumerate(dest):
                vector[f"v{n}"] = f"sample{i}.{'xyzw'[j]}"
                sample_dest.add(f"v{n}")
        elif m := match(r"v_(fmaak|fmamk)_f32 (v\d+), ([^,]+), ([^,]+), ([^,]+)"):
            op, dst, *tokens = m.groups()
            literal = tokens[2] if op == "fmaak" else tokens[1]
            if mask != "entry" or not re.fullmatch(r"0x[0-9a-f]{1,8}", literal):
                raise ValueError("Invalid literal multiply-add")
            if dst in sample_dest:
                raise ValueError("Write overlaps an outstanding sample")
            values = [fp_operand(t, scalar, vector, pending, sample_pending) for t in tokens]
            vector[dst] = f"alu{i}"
            lines.append(f"    precise float alu{i} = {ALU['fma'][1].format(*values)};")
        elif m := match(r"v_mov_b32_sdwa (v\d+), (sext\()?([vs]\d+|-?\d+(?:\.\d+)?)(\))? dst_sel:(BYTE_[0-3]|WORD_[01]|DWORD) dst_unused:(UNUSED_PAD|UNUSED_SEXT|UNUSED_PRESERVE) src0_sel:(BYTE_[0-3]|WORD_[01]|DWORD)"):
            dst, sext, src, close, dst_sel, unused, src_sel = m.groups()
            if mask != "entry" or bool(sext) != bool(close):
                raise ValueError("Invalid register move")
            if dst in sample_dest:
                raise ValueError("Write overlaps an outstanding sample")
            word = f"asuint({fp_operand(src, scalar, vector, pending, sample_pending)})"
            result = sdwa_dest(sdwa_source(word, src_sel, bool(sext)), dst_sel, unused, vector.get(dst))
            vector[dst] = f"alu{i}"
            lines.append(f"    precise float alu{i} = asfloat({result});")
        elif m := match(r"v_cvt_f32_ubyte([0-3])(_e32|_e64)? (v\d+), ([^,\s]+)( clamp)?"):
            # D.f32 = float((S0 >> 8N) & 0xff); clamp exists only in the e64 encoding.
            byte, suffix, dst, src, clamp = m.groups()
            if mask != "entry" or (clamp and suffix != "_e64"):
                raise ValueError("Invalid conversion")
            if dst in sample_dest:
                raise ValueError("Write overlaps an outstanding sample")
            word = vector_u32(src, scalar, vector, pending, sample_pending)
            expression = f"float(({word} >> {8 * int(byte)}u) & 255u)"
            if clamp:
                expression = f"saturate({expression})"
            vector[dst] = f"alu{i}"
            lines.append(f"    precise float alu{i} = {expression};")
        elif m := match(r"v_(and|or|xor|xnor|lshlrev|lshrrev|ashrrev)_(?:b32|i32)(?:_e32|_e64)? (v\d+), ([^,\s]+), ([^,\s]+)"):
            # Bitwise operations and shifts. The shift forms take the count in the first source and mask it to
            # five bits; the arithmetic shift replicates the sign of the second source.
            op, dst, first, second = m.groups()
            if mask != "entry":
                raise ValueError("Invalid integer operation")
            if dst in sample_dest:
                raise ValueError("Write overlaps an outstanding sample")
            a = vector_u32(first, scalar, vector, pending, sample_pending)
            b = vector_u32(second, scalar, vector, pending, sample_pending)
            expression = {
                "and": f"({a} & {b})", "or": f"({a} | {b})", "xor": f"({a} ^ {b})", "xnor": f"(~({a} ^ {b}))",
                "lshlrev": f"({b} << ({a} & 31u))", "lshrrev": f"({b} >> ({a} & 31u))",
                "ashrrev": f"asuint(asint({b}) >> ({a} & 31u))",
            }[op]
            lines.append(f"    uint valu{i} = {expression};")
            vector[dst] = ("uint", f"valu{i}")
        elif m := match(r"v_(not|bfrev)_b32(?:_e32|_e64)? (v\d+), ([^,\s]+)"):
            op, dst, src = m.groups()
            if mask != "entry":
                raise ValueError("Invalid integer operation")
            if dst in sample_dest:
                raise ValueError("Write overlaps an outstanding sample")
            word = vector_u32(src, scalar, vector, pending, sample_pending)
            lines.append(f"    uint valu{i} = {'~' if op == 'not' else 'reversebits'}({word});")
            vector[dst] = ("uint", f"valu{i}")
        elif m := match(r"v_(" + "|".join(INT_VOP2 + INT_VOP3) + r")(_e32|_e64)? (v\d+), ([^,\s]+), ([^,\s]+)( clamp)?"):
            op, suffix, dst, first, second, clamp = m.groups()
            if mask != "entry" or (op in INT_VOP3 and suffix == "_e32") or (clamp and (suffix == "_e32" or op not in INT_CLAMPED)):
                raise ValueError("Invalid integer operation")
            if dst in sample_dest:
                raise ValueError("Write overlaps an outstanding sample")
            a = vector_u32(first, scalar, vector, pending, sample_pending)
            b = vector_u32(second, scalar, vector, pending, sample_pending)
            lines.append(f"    uint valu{i} = {int_binary(op, a, b, bool(clamp), helpers)};")
            vector[dst] = ("uint", f"valu{i}")
        elif m := match(r"v_(" + "|".join(INT_TERNARY) + r")(_e64)? (v\d+), ([^,\s]+), ([^,\s]+), ([^,\s]+)"):
            op, _, dst, first, second, third = m.groups()
            if mask != "entry":
                raise ValueError("Invalid integer operation")
            if dst in sample_dest:
                raise ValueError("Write overlaps an outstanding sample")
            a, b, c = (vector_u32(t, scalar, vector, pending, sample_pending) for t in (first, second, third))
            lines.append(f"    uint valu{i} = {int_ternary(op, a, b, c)};")
            vector[dst] = ("uint", f"valu{i}")
        elif m := match(r"v_cvt_f32_f16_sdwa (v\d+), (-?)(?:\|([vs]\d+)\||([vs]\d+))( clamp)? dst_sel:DWORD dst_unused:UNUSED_(?:PAD|PRESERVE) src0_sel:(WORD_[01])"):
            # The SDWA form widens the selected half; modifiers apply after widening, as in the e64 form.
            dst, negate, bars, plain, clamp, src_sel = m.groups()
            if mask != "entry":
                raise ValueError("Invalid conversion")
            if dst in sample_dest:
                raise ValueError("Write overlaps an outstanding sample")
            word = f"asuint({fp_operand(bars or plain, scalar, vector, pending, sample_pending)})"
            expression = f"widen16({sdwa_source(word, src_sel, False)})"
            if bars:
                expression = f"abs({expression})"
            if negate:
                expression = f"(-{expression})"
            if clamp:
                expression = f"saturate({expression})"
            vector[dst] = f"alu{i}"
            lines.append(f"    precise float alu{i} = {expression};")
        elif m := match(rf"v_({'|'.join(SDWA_ALU)})_f32_sdwa (v\d+), (.+?)( clamp)? dst_sel:(BYTE_[0-3]|WORD_[01]|DWORD) dst_unused:(UNUSED_PAD|UNUSED_SEXT|UNUSED_PRESERVE) src0_sel:DWORD( src1_sel:DWORD)?"):
            # SDWA forms of exact arithmetic take whole-dword sources, so the binary32 denormal mode never applies
            # to a zero-extended field; the result is placed like an SDWA move.
            op, dst, operands, clamp, dst_sel, unused, src1_sel = m.groups()
            tokens = operands.split(", ")
            arity, template = ALU[op]
            if mask != "entry" or len(tokens) != arity or bool(src1_sel) != (arity == 2):
                raise ValueError("Invalid arithmetic operation")
            if dst in sample_dest:
                raise ValueError("Write overlaps an outstanding sample")
            expression = template.format(*[fp_operand(t, scalar, vector, pending, sample_pending) for t in tokens])
            if clamp:
                expression = f"saturate({expression})"
            if dst_sel != "DWORD":
                expression = f"asfloat({sdwa_dest(f'asuint({expression})', dst_sel, unused, vector.get(dst))})"
            vector[dst] = f"alu{i}"
            lines.append(f"    precise float alu{i} = {expression};")
        elif m := match(r"v_mov_b32(?:_e32|_e64)? (v\d+), (-?\d+(?:\.\d+)?|0x[0-9a-f]{1,8}|[vs]\d+)"):
            # A bit copy of a numeric value; integer inline constants are bit patterns.
            dst, src = m.groups()
            if mask != "entry":
                raise ValueError("Invalid register move")
            if dst in sample_dest:
                raise ValueError("Write overlaps an outstanding sample")
            value = fp_operand(src, scalar, vector, pending, sample_pending)
            vector[dst] = f"alu{i}"
            lines.append(f"    precise float alu{i} = {value};")
        elif m := match(r"v_(log|exp|rcp|sqrt|rsq|floor|ceil|fract|trunc|add|mul|max|min|sub|subrev|mul_legacy|fma|fmac|mad|mac)_f32(?:_e32|_e64)? (v\d+), (.+?)( clamp)?"):
            op, dst, operands, clamp = m.groups()
            tokens = operands.split(", ")
            if op in ("fmac", "mac"):
                tokens.append(dst)
            arity, template = ALU[op]
            if mask != "entry" or len(tokens) != arity:
                raise ValueError("Invalid arithmetic operation")
            if dst in sample_dest:
                raise ValueError("Write overlaps an outstanding sample")
            values = [fp_operand(t, scalar, vector, pending, sample_pending) for t in tokens]
            expression = template.format(*values)
            if clamp:
                expression = f"saturate({expression})"
            vector[dst] = f"alu{i}"
            lines.append(f"    precise float alu{i} = {expression};")
        elif m := match(rf"v_cmp_class_f32(?:_e32|_e64)? {LANE_MASK}, ([^,]+), ([^,]+)"):
            dst, value, classes = m.groups()
            regs = lane_mask(dst)
            if mask != "entry" or pending.intersection(regs):
                raise ValueError("Invalid comparison")
            if re.fullmatch(r"-?\d+|0x[0-9a-f]{1,8}", classes):
                bits = f"{int(classes, 0) & 0xffffffff}u"
            elif re.fullmatch(r"[vs]\d+", classes):
                bits = f"asuint({fp_operand(classes, scalar, vector, pending, sample_pending)})"
            else:
                raise ValueError("Unsupported class mask")
            operand = fp_operand(value, scalar, vector, pending, sample_pending)
            for j, reg in enumerate(regs):
                scalar[reg] = ("condition", f"cmp{i}", j, len(regs))
            lines.append(f"    bool cmp{i} = (class32({operand}) & {bits}) != 0u;")
        elif m := match(rf"v_cmp_({'|'.join(COMPARE)})_f32(?:_e32|_e64)? {LANE_MASK}, ([^,]+), ([^,]+)"):
            op, dst, *tokens = m.groups()
            regs = lane_mask(dst)
            if mask != "entry" or pending.intersection(regs):
                raise ValueError("Invalid comparison")
            values = [fp_operand(t, scalar, vector, pending, sample_pending) for t in tokens]
            for j, reg in enumerate(regs):
                scalar[reg] = ("condition", f"cmp{i}", j, len(regs))
            lines.append(f"    bool cmp{i} = {COMPARE[op].format(*values)};")
        elif m := match(rf"v_cmp_({'|'.join(COMPARE)})_f32_sdwa {LANE_MASK}, ([^,]+), ([^,]+) src0_sel:DWORD src1_sel:DWORD"):
            # With whole-dword selections the SDWA comparison is the e32/e64 one; byte and word selections
            # would compare zero-extended fields as binary32 and are refused.
            op, dst, *tokens = m.groups()
            regs = lane_mask(dst)
            if mask != "entry" or pending.intersection(regs):
                raise ValueError("Invalid comparison")
            values = [fp_operand(t, scalar, vector, pending, sample_pending) for t in tokens]
            for j, reg in enumerate(regs):
                scalar[reg] = ("condition", f"cmp{i}", j, len(regs))
            lines.append(f"    bool cmp{i} = {COMPARE[op].format(*values)};")
        elif m := match(rf"v_cndmask_b32(?:_e32|_e64)? (v\d+), ([^,]+), ([^,]+), {LANE_MASK}"):
            dst, unset, chosen, source = m.groups()
            regs = lane_mask(source)
            condition = scalar.get(regs[0])
            if (mask != "entry" or pending.intersection(regs) or not isinstance(condition, tuple)
                    or condition[0] != "condition"
                    or [scalar.get(r) for r in regs] != [(*condition[:2], j, len(regs)) for j in range(len(regs))]):
                raise ValueError("Select mask is not a tracked comparison")
            values = [fp_operand(t, scalar, vector, pending, sample_pending) for t in (chosen, unset)]
            vector[dst] = f"alu{i}"
            lines.append(f"    precise float alu{i} = {condition[1]} ? {values[0]} : {values[1]};")
        elif m := match(r"v_cvt_f32_f16(?:_e32|_e64)? (v\d+), (-?)(?:\|([vs]\d+|0x[0-9a-f]{1,8}|\d+)\||abs\(([vs]\d+|0x[0-9a-f]{1,8}|\d+)\)|([vs]\d+|0x[0-9a-f]{1,8}|\d+))( clamp)?"):
            dst, negate, bars, call, plain, clamp = m.groups()
            if mask != "entry":
                raise ValueError("Invalid conversion")
            if dst in sample_dest:
                raise ValueError("Write overlaps an outstanding sample")
            source = bars or call or plain
            if re.fullmatch(r"0x[0-9a-f]{1,8}|\d+", source):
                word = f"{int(source, 0) & 0xffffffff}u"
            else:
                word = f"asuint({fp_operand(source, scalar, vector, pending, sample_pending)})"
            expression = f"widen16({word})"
            if bars or call:
                expression = f"abs({expression})"
            if negate:
                expression = f"(-{expression})"
            if clamp:
                expression = f"saturate({expression})"
            vector[dst] = f"alu{i}"
            lines.append(f"    precise float alu{i} = {expression};")
        elif m := match(r"v_cvt_f16_f32(?:_e32|_e64)? (v\d+), ([^,\s]+)"):
            # GFX10 16-bit results replace only the low half; the high half of the destination is kept
            # (LLVM GCNSubtarget::zeroesHigh16BitsOfDest). A destination with no tracked value contributes zero.
            dst, src = m.groups()
            if mask != "entry":
                raise ValueError("Invalid conversion")
            if dst in sample_dest:
                raise ValueError("Write overlaps an outstanding sample")
            old = vector.get(dst)
            if old is not None and not (isinstance(old, str) and old.startswith(("sample", "alu", "params["))):
                raise ValueError("Unsupported conversion destination")
            # fp_operand reads modifiers and inline constants, so -1 stays the bit pattern 0xffffffff.
            value = fp_operand(src, scalar, vector, pending, sample_pending)
            high = f"(asuint({old}) & 0xffff0000u)" if old is not None else "0u"
            vector[dst] = f"alu{i}"
            lines.append(f"    precise float alu{i} = asfloat({high} | narrow16({value}));")
        elif m := match(r"v_(add|sub|subrev|mul|max|min|ldexp|floor|ceil|trunc|rndne|fract)_f16(?:_(e32|e64))? (v\d+), (.+?)( clamp)?"):
            # Binary16 arithmetic. The result replaces only the low half of the destination, as for
            # v_cvt_f16_f32. Min and max take HLSL min/max, the NaN convention of the binary32 forms. Output
            # modifiers, op_sel and any other trailing text fail in the operand grammar. A clamp saturates the
            # binary32 value before narrowing, the same as saturating the binary16 result because 0 and 1 are exact.
            op, form, dst, operands, clamp = m.groups()
            tokens = operands.split(", ")
            if mask != "entry" or len(tokens) != (1 if op in ("floor", "ceil", "trunc", "rndne", "fract") else 2):
                raise ValueError("Invalid arithmetic operation")
            if clamp and form != "e64":
                raise ValueError("Invalid arithmetic operation")
            if dst in sample_dest:
                raise ValueError("Write overlaps an outstanding sample")
            old = vector.get(dst)
            if old is not None and not (isinstance(old, str) and old.startswith(("sample", "alu", "params["))):
                raise ValueError("Unsupported arithmetic destination")
            values = [f16_operand(t, scalar, vector, pending, sample_pending) for t in tokens[:1 if op == "ldexp" else len(tokens)]]
            if op == "fract":
                encoding = f"fract16({values[0]})"
                if clamp:
                    encoding = f"narrow16(saturate(widen16({encoding})))"
            else:
                if op == "ldexp":
                    exponent = f16_exponent(tokens[1], scalar, vector, pending, sample_pending)
                    expression = f"ldexp16({values[0]}, {exponent})"
                else:
                    expression = F16_ALU[op][1].format(*values)
                encoding = f"narrow16({f'saturate({expression})' if clamp else expression})"
            high = f"(asuint({old}) & 0xffff0000u)" if old is not None else "0u"
            vector[dst] = f"alu{i}"
            lines.append(f"    precise float alu{i} = asfloat({high} | {encoding});")
        elif m := match(r"v_cvt_pkrtz_f16_f32_e32 (v\d+), (v\d+), (v\d+)"):
            dst, lo, hi = m.groups()
            pair = (vector[lo], vector[hi])
            if mask != "entry" or sample_pending or not all(isinstance(v, str) and v.startswith(("sample", "alu")) for v in pair):
                raise ValueError("Unsupported pack operand")
            vector[dst] = pair
        elif m := match(r"exp mrt0,? (v\d+), \1, (v\d+), \2 done compr vm"):
            pairs = [vector[v] for v in m.groups()]
            if mask != "entry" or exported or not all(isinstance(p, tuple) and len(p)==2 and
                    all(v.startswith(("sample", "alu")) for v in p) for p in pairs):
                raise ValueError("Unsupported export")
            args = [f"export16({v})" for pair in pairs for v in pair]
            lines.append(f"    return float4({', '.join(args)});")
            exported = True
        elif line == "s_endpgm" and exported:
            ended = True
        else:
            raise ValueError(f"Unsupported instruction {i}: {line}")
    if not ended or samples != (2 if second_texture_offset is not None else 1):
        raise ValueError("Unexpected sample count or missing color export")
    if helpers:
        defs = [body for name, body in SALU_HELPERS.items() if name in helpers]
        pos = lines.index(PREAMBLE)
        lines[pos:pos] = defs
    return "\n".join([*lines, "}",""])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("record")
    parser.add_argument("--container-sha256", help="SHA-256 of the full decoded DXBC container to select by name")
    parser.add_argument("--llvm", required=True, help="LLVM C library with AMDGPU support")
    parser.add_argument("--texture-sgpr", type=int, required=True, help="Entry register for the low texture address")
    parser.add_argument("--interp-sgpr", type=int, required=True, help="Entry register for the interpolation base")
    parser.add_argument("--sampler-words", nargs=4, type=lambda s: int(s, 0), required=True,
                        help="Four descriptor words to bind to the supplied desktop sampler at s0")
    parser.add_argument("--output", type=Path, required=True, help="Destination .hlsl in a local output directory")
    parser.add_argument("--constant-descriptor", type=lambda s: int(s, 0),
                        help="Byte offset of a descriptor mapped to the 256-byte desktop buffer b0")
    parser.add_argument("--second-texture-offset", type=lambda s: int(s, 0), help="Byte offset of the t1 descriptor for a two-sample shader")
    args = parser.parse_args()
    dest = args.output.resolve()
    if dest.suffix.lower() != ".hlsl" or dest == args.archive.resolve():
        parser.error("Choose an HLSL destination distinct from the input")
    try:
        blob, code = native_program(args.archive, args.record, container_sha256=args.container_sha256)
        instructions = disassemble(code, args.llvm)
        source = lower(instructions, args.texture_sgpr, args.interp_sgpr, args.sampler_words, args.constant_descriptor, second_texture_offset=args.second_texture_offset)
    except (ValueError, KeyError, struct.error, OSError, AttributeError, zlib.error) as exc:
        parser.exit(1, f"Translation failed: {exc}\n")
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=dest.parent, delete=False, mode="wb") as f:
        f.write(source.encode("utf-8"))
    Path(f.name).replace(dest)
    print(json.dumps({"record":args.record, "container_sha256":hashlib.sha256(blob).hexdigest(),
                      "native_sha256":hashlib.sha256(code).hexdigest(), "instructions":len(instructions),
                      "hlsl_sha256":hashlib.sha256(dest.read_bytes()).hexdigest()}))


if __name__ == "__main__":
    main()
