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
// v_cmp_class_f16: the same ten classes from the binary16 encoding (the low 16 bits of a word), same bit order:
// signaling NaN, quiet NaN (bit 9 of the encoding), -inf, -normal, -subnormal, -0, +0, +subnormal, +normal, +inf.
uint class16(uint bits) {
    bits &= 0xffffu;
    uint magnitude = bits & 0x7fffu;
    bool negative = (bits & 0x8000u) != 0u;
    if (magnitude > 0x7c00u) return (bits & 0x0200u) != 0u ? 0x2u : 0x1u;
    if (magnitude == 0x7c00u) return negative ? 0x4u : 0x200u;
    if (magnitude >= 0x0400u) return negative ? 0x8u : 0x100u;
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


# Title memory for buffer and global loads (see docs/experiments.md). The declarations match the pixel root signature
# of the harness (tests/pixel_aot_vs.hlsl); src/title_va_lookup.hlsli is read at translation time.
TITLE_LOOKUP = Path(__file__).resolve().parents[1] / "src" / "title_va_lookup.hlsli"
TITLE_DECLARATIONS = """StructuredBuffer<TitleRange> title_ranges : register(t2);
ByteAddressBuffer title_memory[8] : register(t0, space1);
cbuffer TitleCount : register(b1) { uint title_range_count; };
"""
# Buffer resource (V#) on gfx10, as four words w0..w3:
#   base = w0 | (w1 & 0xffff) << 32, stride = (w1 >> 16) & 0x3fff, num_records = w2, OOB_SELECT = (w3 >> 28) & 3,
#   SWIZZLE_ENABLE = w1 bit 31, ADD_TID_ENABLE = w3 bit 23.
# Sources:
#   AMD RDNA Shader ISA (document 70652, 2020-09-25), Table 37 "Buffer Resource Descriptor": base address bits 47:0,
#     stride 61:48, swizzle enable 63, num_records 95:64, add tid enable 119, OOB_SELECT 125:124; section 8.1.5:
#     Final Address = const_base + sgpr_offset + buffer_offset, "the sgpr_offset is not a part of the offset term",
#     out-of-range reads return zero, Load/store-Dword-x{2,3,4} are range-checked per component.
#   Mesa src/amd/common/ac_descriptors.c, ac_set_buf_desc_word3 (android.googlesource.com mirror of Mesa), whose comment
#     gives OOB_SELECT for GFX10 as: 0: (index >= NUM_RECORDS) || (offset >= STRIDE); 1: index >= NUM_RECORDS;
#     2: NUM_RECORDS == 0; 3: swizzle_address >= NUM_RECORDS if SWIZZLE_ENABLE else offset >= NUM_RECORDS.
#     ac_build_buffer_descriptor puts va in w0, va >> 32 and the stride in w1 and the size in w2.
# Where they differ the code follows Mesa: the ISA table has "offset > stride" for 0 and "offset + payload > NumRecords"
# (with NumRecords reduced by sgpr_offset in raw mode) for 3. Per component, a dword is out of range when its own offset
# (voffset + inst_offset + 4 * dword) fails the rule; SWIZZLE_ENABLE and ADD_TID_ENABLE are not modelled and read zero,
# as does an offset sum that wraps 32 bits.
MEMORY_HELPERS = """uint2 add64(uint2 a, uint2 b) {
    uint low = a.x + b.x;
    return uint2(low, a.y + b.y + (low < a.x ? 1u : 0u));
}
uint2 mul_stride(uint stride, uint index) {
    uint low = stride * (index & 0xffffu);
    uint high = stride * (index >> 16);
    return add64(uint2(low, 0u), uint2(high << 16, high >> 16));
}
uint title_load32(uint2 address) {
    uint slot;
    uint offset;
    if (!TitleLookup(title_ranges, title_range_count, address, 4, slot, offset)) return 0u;
    return title_memory[NonUniformResourceIndex(slot)].Load(offset);
}
uint buffer_load32(uint4 rsrc, uint soffset, uint voffset, uint inst_offset, uint index, uint dword) {
    uint stride = (rsrc.y >> 16) & 0x3fffu;
    uint num_records = rsrc.z;
    uint oob_select = (rsrc.w >> 28) & 3u;
    bool unmodelled = (rsrc.y >> 31) != 0u || ((rsrc.w >> 23) & 1u) != 0u;
    uint partial = voffset + inst_offset;
    uint offset = partial + 4u * dword;
    bool wrapped = partial < voffset || offset < partial;
    bool in_range;
    if (oob_select == 0u) in_range = index < num_records && offset < stride;
    else if (oob_select == 1u) in_range = index < num_records;
    else if (oob_select == 2u) in_range = num_records != 0u;
    else in_range = offset < num_records;
    if (unmodelled || wrapped || !in_range) return 0u;
    uint2 address = add64(uint2(rsrc.x, rsrc.y & 0xffffu), uint2(soffset, 0u));
    address = add64(address, mul_stride(stride, index));
    return title_load32(add64(address, uint2(offset, 0u)));
}
uint global_load32(uint2 base, uint voffset, uint2 immediate, uint dword) {
    return title_load32(add64(add64(base, uint2(voffset, 0u)), add64(immediate, uint2(4u * dword, 0u))));
}
"""


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
    # MIMG helpers take the texture as a parameter. Out-of-range access is explicit so that no driver's
    # out-of-bounds convention is relied on: a texel outside the mip's extent, or a mip beyond the level count, is zero.
    "image_load": (
        "float4 image_load2d(Texture2D<float4> t, uint x, uint y, uint mip) {\n"
        "    uint w, h, levels;\n"
        "    t.GetDimensions(0u, w, h, levels);\n"
        "    if (mip >= levels) return float4(0.0f, 0.0f, 0.0f, 0.0f);\n"
        "    t.GetDimensions(mip, w, h, levels);\n"
        "    if (x >= w || y >= h) return float4(0.0f, 0.0f, 0.0f, 0.0f);\n"
        "    return t.Load(int3(int(x), int(y), int(mip)));\n"
        "}"
    ),
    "image_resinfo": (
        "uint4 image_resinfo2d(Texture2D<float4> t, uint mip) {\n"
        "    uint w, h, levels;\n"
        "    t.GetDimensions(0u, w, h, levels);\n"
        "    if (mip >= levels) return uint4(0u, 0u, 0u, levels);\n"
        "    t.GetDimensions(mip, w, h, levels);\n"
        "    return uint4(w, h, 0u, levels);\n"
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


def vgprs(token, count):
    """Name the consecutive vector registers of a load destination: vN for one dword, v[N:M] for several."""
    if m := re.fullmatch(r"v\[(\d+):(\d+)\]", token):
        return [f"v{n}" for n in registers(*m.groups(), count)]
    if count != 1 or not re.fullmatch(r"v\d+", token):
        raise ValueError("Load destination width mismatch")
    return [token]


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
            if sample_pending and value[1].startswith("mem"):
                raise ValueError("Memory load used before vmcnt wait")
            return f"asfloat({value[1]})"
        if not isinstance(value, str) or not value.startswith(("sample", "alu")):
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
# raw words had their own representation accept exactly the same registers now.
RAW_WORD_PREFIXES = ("params[", "movw", "selw")


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
            if sample_pending and value[1].startswith("mem"):
                raise ValueError("Memory load used before vmcnt wait")
            return value[1]
        if not isinstance(value, str) or not value.startswith(("sample", "alu")):
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
    kept = tracked_word(old)
    if kept is None:
        raise ValueError("UNUSED_PRESERVE needs a tracked numeric destination")
    keep = ~(((1 << width) - 1) << offset) & 0xffffffff
    return f"(({kept} & {keep:#x}u) | {field})"


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


# Mixed-precision fused multiply-add: v_fma_mix_f32, v_fma_mixlo_f16, v_fma_mixhi_f16 (VOP3P encoding).
# Sources:
#   AMD RDNA 2 ISA Reference Guide (document 70648, 2020-11-30), section 12.10 VOP3P Instructions, opcodes 32 to 34:
#     "Size and location of S0, S1 and S2 controlled by OPSEL: 0=src[31:0], 1=src[31:0], 2=src[15:0], 3=src[31:16]";
#     "for MAD_MIX, the NEG_HI field acts instead as an absolute-value modifier"; D.f[31:0] = S0.f * S1.f + S2.f for
#     V_FMA_MIX_F32, D.f[15:0] = ... "stored in low 16 bits" for MIXLO and D.f[31:16] = ... for MIXHI.
#     The OPSEL value of a source is {op_sel_hi, op_sel}: op_sel_hi 0 reads the whole binary32 word whatever op_sel
#     says; op_sel_hi 1 reads the binary16 half that op_sel picks (0 low, 1 high).
#   LLVM 15 (llvmorg-15.0.7) llvm/lib/Target/AMDGPU/VOP3PInstructions.td: VOP3P_Mix_Profile ("The inline immediate values
#     are really f16 converted to f32"; mixlo and mixhi tie $vdst to $vdst_in, so the other half of the destination is
#     kept); "Clamp modifier is applied after conversion to f16"; MadFmaMixPats model mixlo and mixhi as
#     fpround(fma(f32, f32, f32)).
# The ISA text does not say whether the narrowed result is rounded once. This lowering rounds the exact a*b+c once, to
# nearest even, to the format of the result; fpround(fma) in binary32 is not that (a result that lands on a binary16 tie
# after the binary32 rounding is then rounded again: a = 0x31e9, b = 0xb56a, c = 0x5a91 (all binary16) is 210.125, the
# correctly rounded result, where fma in binary32 and then narrowing gives 210.0; the draws use cases like it).
#
# The arithmetic is integer, so it needs no float64 capability and does not depend on whether a target fuses a*b+c or
# flushes binary32 denormals. A source is the encoding of a binary32 (a binary16 source is widened exactly first). A
# finite value is m * 2^e with m < 2^24. The product m_a * m_b < 2^48 is exact in two words. Each of the product and the
# addend is shifted left until its top bit is bit 62 of a 64-bit window; the one with the larger top exponent is the big
# operand, and the other is shifted right by the exponent difference with the bits shifted out OR-ed into bit 0 (a
# sticky bit). That is exact unless bits are lost, which needs a difference over 15 (product) or 39 (addend); then the
# result still has its top bit at 61 or 62, the rounding position is 37 or more bits above bit 0, and the sticky bit
# keeps bit 0 of the sum odd, so the sum is never on a rounding boundary or midpoint while the exact value is on neither
# (the exact value lies within one unit of the computed one and the boundaries are even). Equal signs add (the sum is
# below 2^64), unequal signs subtract the smaller magnitude. The result is rounded to p = 24 (binary32, quantum 2^-149)
# or p = 11 (binary16, quantum 2^-24) bits: nearest even, subnormal results gradual, overflow to infinity. The
# encoding is ((q + bias) << mantissa bits) + kept, where kept holds the implicit bit, so a carry out of kept moves into
# the exponent and a subnormal that rounds up becomes the smallest normal.
# Special values: a NaN source gives that NaN, quieted (first of a, b, c; a binary16 result keeps the top ten payload
# bits as narrow16 does); infinity times zero, or opposite infinities, give the default quiet NaN; an exact zero sum is
# +0 unless both the product and the addend are -0 (round to nearest). A NaN payload or sign from hardware is not
# modelled beyond this and the draws do not use NaN. Binary32 denormal inputs and results are not flushed, as in the
# v_fma_f32 branch (v_mad_f32 is the form that flushes). Clamp: NaN and any negative value, -0 included, give +0, a
# value above 1.0 gives 1.0; the draws avoid -0 under clamp because hardware is not documented for it.
FMA_MIX_HELPERS = """uint fm_msb(uint x) {
    uint n = 0u;
    if (x >= 0x10000u) { x >>= 16u; n += 16u; }
    if (x >= 0x100u) { x >>= 8u; n += 8u; }
    if (x >= 0x10u) { x >>= 4u; n += 4u; }
    if (x >= 0x4u) { x >>= 2u; n += 2u; }
    if (x >= 0x2u) { n += 1u; }
    return n;
}
uint fm_msb64(uint2 v) {
    return v.y != 0u ? 32u + fm_msb(v.y) : fm_msb(v.x);
}
uint2 fm_shl(uint2 v, uint n) {
    if (n == 0u) return v;
    if (n < 32u) return uint2(v.x << n, (v.y << n) | (v.x >> (32u - n)));
    return uint2(0u, v.x << (n - 32u));
}
uint2 fm_shr_jam(uint2 v, uint n) {
    if (n == 0u) return v;
    if (n >= 64u) return uint2((v.x | v.y) != 0u ? 1u : 0u, 0u);
    uint2 r;
    bool lost;
    if (n < 32u) {
        lost = (v.x << (32u - n)) != 0u;
        r = uint2((v.x >> n) | (v.y << (32u - n)), v.y >> n);
    } else if (n == 32u) {
        lost = v.x != 0u;
        r = uint2(v.y, 0u);
    } else {
        lost = v.x != 0u || (v.y << (64u - n)) != 0u;
        r = uint2(v.y >> (n - 32u), 0u);
    }
    return uint2(r.x | (lost ? 1u : 0u), r.y);
}
uint2 fm_add(uint2 a, uint2 b) {
    uint low = a.x + b.x;
    return uint2(low, a.y + b.y + (low < a.x ? 1u : 0u));
}
uint2 fm_sub(uint2 a, uint2 b) {
    return uint2(a.x - b.x, a.y - b.y - (a.x < b.x ? 1u : 0u));
}
bool fm_ge(uint2 a, uint2 b) {
    return a.y > b.y || (a.y == b.y && a.x >= b.x);
}
uint2 fm_mul24(uint a, uint b) {
    uint a0 = a & 0xffffu, a1 = a >> 16u, b0 = b & 0xffffu, b1 = b >> 16u;
    uint p00 = a0 * b0, mid = a0 * b1 + a1 * b0, p11 = a1 * b1;
    uint low = p00 + ((mid & 0xffffu) << 16u);
    return uint2(low, p11 + (mid >> 16u) + (low < p00 ? 1u : 0u));
}
uint fm_f16_word(uint h) {
    uint sign = (h & 0x8000u) << 16u;
    uint e = (h >> 10u) & 0x1fu;
    uint m = h & 0x3ffu;
    if (e == 0x1fu) return sign | 0x7f800000u | (m << 13u);
    if (e != 0u) return sign | ((e + 112u) << 23u) | (m << 13u);
    if (m == 0u) return sign;
    uint k = fm_msb(m);
    return sign | ((k + 103u) << 23u) | ((m << (23u - k)) & 0x7fffffu);
}
uint fm_nan(uint word, bool wide) {
    if (wide) return word | 0x00400000u;
    return ((word >> 16u) & 0x8000u) | 0x7e00u | ((word & 0x7fffffu) >> 13u);
}
uint fm_inf(uint sign, bool wide) {
    return wide ? ((sign << 31u) | 0x7f800000u) : ((sign << 15u) | 0x7c00u);
}
uint fm_zero(uint sign, bool wide) {
    return wide ? (sign << 31u) : (sign << 15u);
}
uint fma_mix_round(uint a, uint b, uint c, bool wide) {
    uint ma = a & 0x7fffffffu, mb = b & 0x7fffffffu, mc = c & 0x7fffffffu;
    uint sa = a >> 31u, sb = b >> 31u, sc = c >> 31u;
    uint sp = sa ^ sb;
    if (ma > 0x7f800000u) return fm_nan(a, wide);
    if (mb > 0x7f800000u) return fm_nan(b, wide);
    if (mc > 0x7f800000u) return fm_nan(c, wide);
    bool inf_p = ma == 0x7f800000u || mb == 0x7f800000u;
    if ((ma == 0x7f800000u && mb == 0u) || (mb == 0x7f800000u && ma == 0u)
        || (inf_p && mc == 0x7f800000u && sp != sc)) return fm_nan(0x7fc00000u, wide);
    if (inf_p) return fm_inf(sp, wide);
    if (mc == 0x7f800000u) return fm_inf(sc, wide);
    uint xa = ma >> 23u, xb = mb >> 23u, xc = mc >> 23u;
    uint na = xa == 0u ? ma : ((ma & 0x7fffffu) | 0x800000u);
    uint nb = xb == 0u ? mb : ((mb & 0x7fffffu) | 0x800000u);
    uint nc = xc == 0u ? mc : ((mc & 0x7fffffu) | 0x800000u);
    int ep = int(xa == 0u ? 1u : xa) + int(xb == 0u ? 1u : xb) - 300;
    int ec = int(xc == 0u ? 1u : xc) - 150;
    uint2 mp = fm_mul24(na, nb);
    bool pz = (mp.x | mp.y) == 0u;
    bool cz = nc == 0u;
    if (pz && cz) return fm_zero(sp & sc, wide);
    uint2 p = uint2(0u, 0u), cw = uint2(0u, 0u);
    int tp = 0, tc = 0;
    if (!pz) {
        uint up = 62u - fm_msb64(mp);
        p = fm_shl(mp, up);
        tp = ep - int(up);
    }
    if (!cz) {
        uint uc = 62u - fm_msb(nc);
        cw = fm_shl(uint2(nc, 0u), uc);
        tc = ec - int(uc);
    }
    bool p_big = cz || (!pz && tp >= tc);
    uint2 big = p_big ? p : cw;
    uint2 small = p_big ? cw : p;
    int big_e = p_big ? tp : tc;
    uint big_s = p_big ? sp : sc;
    uint small_s = p_big ? sc : sp;
    uint gap = (pz || cz) ? 0u : uint(p_big ? tp - tc : tc - tp);
    small = fm_shr_jam(small, gap);
    uint2 r;
    uint rs = big_s;
    if (big_s == small_s) {
        r = fm_add(big, small);
    } else if (fm_ge(big, small)) {
        r = fm_sub(big, small);
    } else {
        r = fm_sub(small, big);
        rs = small_s;
    }
    if ((r.x | r.y) == 0u) return 0u;
    int top = int(fm_msb64(r)) + big_e;
    int mant = wide ? 23 : 10;
    int quantum = max(top - mant, wide ? -149 : -24);
    int shift = quantum - big_e;
    uint2 s2;
    if (shift >= 2) s2 = fm_shr_jam(r, uint(shift - 2));
    else s2 = fm_shl(r, uint(2 - shift));
    uint kept = s2.x >> 2u;
    if ((s2.x & 2u) != 0u && ((s2.x & 1u) != 0u || (kept & 1u) != 0u)) kept += 1u;
    int field = quantum + (wide ? 149 : 24);
    uint infinity = wide ? 0x7f800000u : 0x7c00u;
    if (field >= (wide ? 255 : 31)) return fm_inf(rs, wide);
    uint encoding = (uint(field) << uint(mant)) + kept;
    return min(encoding, infinity) | fm_zero(rs, wide);
}
uint fma_mix_sat(uint v, bool wide) {
    uint sign = wide ? 0x80000000u : 0x8000u;
    uint one = wide ? 0x3f800000u : 0x3c00u;
    if ((v & (sign - 1u)) > (wide ? 0x7f800000u : 0x7c00u) || (v & sign) != 0u) return 0u;
    return min(v, one);
}
"""


def fma_mix_source(token, high, select, scalar, vector, pending, sample_pending):
    """One source of v_fma_mix_*: the binary32 encoding of its value after widening and modifiers, as a uint expression.

    high is op_sel_hi (the source is binary16) and select is op_sel (high half); select is ignored for a binary32
    source. Inline constants are read as binary16 values and widened, as LLVM does (VOP3P_Mix_Profile): 0, +-0.5,
    +-1, +-2 and +-4 are the same value in both formats and are accepted for either; 1/(2*pi) is accepted only for a
    binary16 source, where its value is known; other integer constants are refused. LLVM prints a literal as its low 16
    bits, so a literal source is lowered only as the low binary16 half; a binary32 literal or a high half is not in the
    text and is refused."""
    negate = absolute = False
    body = token
    constant = re.fullmatch(r"-?0\.5|-?1\.0|-?2\.0|-?4\.0|0|0\.15915494", token)
    if not constant:
        if body.startswith("neg(") and body.endswith(")"):
            negate, body = True, body[4:-1]
        elif body.startswith("-"):
            negate, body = True, body[1:]
        if len(body) > 2 and body.startswith("|") and body.endswith("|"):
            absolute, body = True, body[1:-1]
        constant = re.fullmatch(r"-?0\.5|-?1\.0|-?2\.0|-?4\.0|0|0\.15915494", body)
    if constant:
        text = constant.group(0)
        if (select and high) or (text == "0.15915494" and not high):
            raise ValueError(f"Unsupported constant source {token}")
        bits = F16_CONSTANT.get(text, 0)
        if absolute:
            bits &= 0x7fff
        if negate:
            bits ^= 0x8000
        return f"fm_f16_word({bits:#x}u)"
    if re.fullmatch(r"0x[0-9a-f]{1,4}", body):
        if not high or select:
            raise ValueError(f"A literal source is lowered only as the low binary16 half: {token}")
        word = f"{int(body, 16):#x}u"
    elif re.fullmatch(r"[vs]\d+", body):
        word = word_of(body, scalar, vector, pending, sample_pending)
    else:
        raise ValueError(f"Unsupported source {token}")
    if high:
        half = f"(({word} >> 16u) & 0xffffu)" if select else f"({word} & 0xffffu)"
        if absolute:
            half = f"({half} & 0x7fffu)"
        if negate:
            half = f"({half} ^ 0x8000u)"
        return f"fm_f16_word({half})"
    if absolute:
        word = f"({word} & 0x7fffffffu)"
    if negate:
        word = f"({word} ^ 0x80000000u)"
    return word


def lower(instructions, texture_sgpr, interp_sgpr, sampler, constant_descriptor=None, *, second_texture_offset=None,
          buffer_descriptors=None):
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
        # uint4, not float4: the words are raw data and must never be typed as floats (see docs/experiments.md).
        lines.insert(0, "cbuffer Constants : register(b0) { uint4 params[16]; };")
    bindings = {0: "tex"}
    if second_texture_offset is not None:
        if second_texture_offset < 32 or second_texture_offset % 32:
            raise ValueError("Second texture descriptor must have a distinct aligned offset")
        bindings[second_texture_offset] = "tex1"
        lines.insert(0, "Texture2D<float4> tex1 : register(t1);")
    if constant_descriptor is not None and any(
            start < constant_descriptor + 16 and constant_descriptor < start + 32 for start in bindings):
        raise ValueError("Texture and constant descriptors overlap")
    # buffer_descriptors maps the byte offset of a descriptor-table entry, as s_load_dwordx4 names it, to the index of the
    # first of four constant-buffer words that hold that buffer resource at runtime.
    vsharp_words = dict(buffer_descriptors or {})
    if vsharp_words and constant_descriptor is None:
        raise ValueError("Buffer descriptors need a constant descriptor")
    for offset, word in vsharp_words.items():
        if offset < 0 or offset % 16 or not 0 <= word <= 60:
            raise ValueError("Invalid buffer descriptor offset or constant word")
        if (any(start < offset + 16 and offset < start + 32 for start in bindings)
                or constant_descriptor < offset + 16 and offset < constant_descriptor + 16):
            raise ValueError("Buffer and texture or constant descriptors overlap")
    uses_memory = False
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
            if descriptor and offset != constant_descriptor and offset not in vsharp_words:
                raise ValueError("Constant descriptor differs from binding contract")
            if not descriptor and (offset % 4 or offset + 4 * len(dst) > 256):
                raise ValueError("Constant read exceeds binding or is unaligned")
            for j, n in enumerate(dst):
                if f"s{n}" in pending:
                    raise ValueError("Write overlaps an outstanding scalar load")
                word = offset // 4 + j
                if descriptor and offset in vsharp_words:
                    word = vsharp_words[offset] + j
                    scalar[f"s{n}"] = ("uint", f"params[{word // 4}].{'xyzw'[word % 4]}")
                else:
                    scalar[f"s{n}"] = ("cbv", j) if descriptor else ("uint", f"params[{word // 4}].{'xyzw'[word % 4]}")
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
        elif m := match(r"image_(load|load_mip|get_resinfo|gather4|gather4_lz) (v\d+|v\[\d+:\d+\]), (v\d+|v\[\d+:\d+\]), "
                        r"s\[(\d+):(\d+)\](?:, s\[(\d+):(\d+)\])? dmask:0x([0-9a-f]) dim:SQ_RSRC_IMG_2D((?: (?:unorm|glc|slc|dlc))*)"):
            # MIMG loads, level queries and gathers of a 2D T#, with the descriptor provenance rules of image_sample. Cache
            # modifiers do not change the value; unorm is accepted for loads and queries, where it has no effect on an
            # integer-addressed access. a16, d16, tfe, lwe, r128 and array or other dimensions do not match this
            # grammar. Destination and address widths must agree with the dmask and the form, as the assembler requires.
            op, dst_token, addr_token, f0, f1, s0, s1, dmask_digit, modifiers = m.groups()
            flags = modifiers.split()
            if len(set(flags)) != len(flags) or ("unorm" in flags and op.startswith("gather4")):
                raise ValueError("Repeated or unsupported image modifier")
            dmask = int(dmask_digit, 16)
            if mask != "entry" or not dmask:
                raise ValueError("Invalid image operation")
            if op == "gather4":
                raise ValueError("image_gather4 picks its mip level from derivatives, which Gather* cannot reproduce; "
                                 "only image_gather4_lz is lowered")
            gather = op.startswith("gather4")
            if gather != (s0 is not None):
                raise ValueError("Sampler operand does not match the image form")
            channels = [c for c in range(4) if dmask >> c & 1]
            if gather and len(channels) != 1:
                raise ValueError("image_gather4 needs exactly one dmask bit")
            if op == "get_resinfo" and 2 in channels:
                raise ValueError("image_get_resinfo depth word of a 2D resource is not defined by Direct3D; refused")
            dests = vgprs(dst_token, 4 if gather else len(channels))
            addr_width = {"load": 2, "load_mip": 3, "get_resinfo": 1, "gather4": 2, "gather4_lz": 2}[op]
            addrs = vgprs(addr_token, addr_width)
            image = [f"s{n}" for n in registers(f0, f1, 8)]
            descriptor = [scalar.get(r) for r in image]
            texture = next((name for name in bindings.values() if descriptor == [(name, j) for j in range(8)]), None)
            if texture is None or int(f0) % 4 or int(f1) > 105 or any(r in pending for r in image):
                raise ValueError("Unsupported image binding")
            if gather:
                state = [f"s{n}" for n in registers(s0, s1, 4)]
                if any(r in pending for r in state) or [scalar.get(r) for r in state] != list(sampler) or int(s0) % 4:
                    raise ValueError("Unsupported sampler binding")
            if any(d in sample_dest for d in dests) or any(int(d[1:]) > 255 for d in (*dests, *addrs)):
                raise ValueError("Write overlaps an outstanding sample")
            if gather:
                # Footprint order is the Direct3D one: x, y, z, w = (-,+), (+,+), (+,-), (-,-) texel offsets, which is
                # VDATA[0..3] = lower left, lower right, upper right, upper left. The coordinate is normalized.
                coords = []
                for r in addrs:
                    value = vector.get(r)
                    coords.append(value if value in ("uv.x", "uv.y") else fp_operand(r, scalar, vector, pending, sample_pending))
                call = f"{texture}.Gather{('Red', 'Green', 'Blue', 'Alpha')[channels[0]]}(samp, float2({coords[0]}, {coords[1]}))"
                lines.append(f"    float4 sample{i} = {call};")
                results = [f"sample{i}.{c}" for c in "xyzw"]
            elif op == "get_resinfo":
                # D3D resinfo: [width, height, depth or array size, level count]. The depth word of a 2D resource is
                # refused above; a level at or beyond the count returns zero extents and the level count.
                level = vector_u32(addrs[0], scalar, vector, pending, sample_pending)
                helpers.add("image_resinfo")
                lines.append(f"    uint4 mem_info{i} = image_resinfo2d({texture}, {level});")
                results = None
            else:
                x, y = (vector_u32(r, scalar, vector, pending, sample_pending) for r in addrs[:2])
                level = vector_u32(addrs[2], scalar, vector, pending, sample_pending) if op == "load_mip" else "0u"
                helpers.add("image_load")
                lines.append(f"    float4 sample{i} = image_load2d({texture}, {x}, {y}, {level});")
                results = [f"sample{i}.{c}" for c in "xyzw"]
            sample_pending = True
            if results is None:
                for d, c in zip(dests, channels):
                    vector[d] = ("uint", f"mem_info{i}.{'xyzw'[c]}")
            else:
                for d, c in zip(dests, [0, 1, 2, 3] if gather else channels):
                    vector[d] = results[c]
            sample_dest.update(dests)
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
            word = word_of(src, scalar, vector, pending, sample_pending)
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
            word = word_of(bars or plain, scalar, vector, pending, sample_pending)
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
            if raw_source(src, scalar, vector):
                # A raw word is copied as an unsigned integer. It never takes a float type, so the compiler or the
                # driver has no float semantics (NaN canonicalization, denormal flushing) to apply to it.
                lines.append(f"    uint movw{i} = {vector_u32(src, scalar, vector, pending, sample_pending)};")
                vector[dst] = ("uint", f"movw{i}")
            else:
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
                bits = word_of(classes, scalar, vector, pending, sample_pending)
            else:
                raise ValueError("Unsupported class mask")
            operand = fp_operand(value, scalar, vector, pending, sample_pending)
            for j, reg in enumerate(regs):
                scalar[reg] = ("condition", f"cmp{i}", j, len(regs))
            lines.append(f"    bool cmp{i} = (class32({operand}) & {bits}) != 0u;")
        elif m := match(rf"v_cmp_class_f16(?:_e32|_e64)? {LANE_MASK}, ([^,]+), ([^,]+)"):
            # The class is read from the binary16 encoding itself (class16). The class mask is a 32-bit integer
            # source, not a binary16 value, so a float constant there is refused.
            dst, value, classes = m.groups()
            regs = lane_mask(dst)
            if mask != "entry" or pending.intersection(regs):
                raise ValueError("Invalid comparison")
            if re.fullmatch(r"-?\d+|0x[0-9a-f]{1,8}", classes):
                bits = f"{int(classes, 0) & 0xffffffff}u"
            elif re.fullmatch(r"[vs]\d+", classes):
                bits = vector_u32(classes, scalar, vector, pending, sample_pending)
            else:
                raise ValueError("Unsupported class mask")
            operand = f16_encoding(value, scalar, vector, pending, sample_pending)
            for j, reg in enumerate(regs):
                scalar[reg] = ("condition", f"cmp{i}", j, len(regs))
            lines.append(f"    bool cmp{i} = (class16({operand}) & {bits}) != 0u;")
        elif m := match(rf"v_cmp_({'|'.join(COMPARE)})_f16(?:_e32|_e64)? {LANE_MASK}, ([^,]+), ([^,]+)"):
            # Both sources are widened from their low halves. Widening binary16 to binary32 is exact (including
            # subnormals, infinities and the NaN-ness of the operands), so every comparison of the widened values
            # in binary32 gives the binary16 result, and the f32 predicate table applies unchanged.
            op, dst, *tokens = m.groups()
            regs = lane_mask(dst)
            if mask != "entry" or pending.intersection(regs):
                raise ValueError("Invalid comparison")
            values = [f16_operand(t, scalar, vector, pending, sample_pending) for t in tokens]
            for j, reg in enumerate(regs):
                scalar[reg] = ("condition", f"cmp{i}", j, len(regs))
            lines.append(f"    precise float cmpa{i} = {values[0]};")
            lines.append(f"    precise float cmpb{i} = {values[1]};")
            lines.append(f"    bool cmp{i} = {COMPARE[op].format(f'cmpa{i}', f'cmpb{i}')};")
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
            plain = r"[vs]\d+|-?\d+|0x[0-9a-f]{1,8}|-?\d+\.\d+"
            if (all(re.fullmatch(plain, t) for t in (chosen, unset))
                    and any(raw_source(t, scalar, vector) for t in (chosen, unset))):
                # A select with a raw-word source picks between unsigned words, never between floats.
                words = [vector_u32(t, scalar, vector, pending, sample_pending) for t in (chosen, unset)]
                lines.append(f"    uint selw{i} = {condition[1]} ? {words[0]} : {words[1]};")
                vector[dst] = ("uint", f"selw{i}")
            else:
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
                word = word_of(source, scalar, vector, pending, sample_pending)
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
            if old is not None and tracked_word(old) is None:
                raise ValueError("Unsupported conversion destination")
            # fp_operand reads modifiers and inline constants, so -1 stays the bit pattern 0xffffffff.
            value = fp_operand(src, scalar, vector, pending, sample_pending)
            high = f"({tracked_word(old)} & 0xffff0000u)" if old is not None else "0u"
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
            if old is not None and tracked_word(old) is None:
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
            high = f"({tracked_word(old)} & 0xffff0000u)" if old is not None else "0u"
            vector[dst] = f"alu{i}"
            lines.append(f"    precise float alu{i} = asfloat({high} | {encoding});")
        elif m := match(r"v_fma_(mix_f32|mixlo_f16|mixhi_f16)(?:_e64)? (v\d+), ([^,\s]+), ([^,\s]+), ([^,\s]+)"
                        r"(?: op_sel:\[([01]),([01]),([01])\])?(?: op_sel_hi:\[([01]),([01]),([01])\])?( clamp)?"):
            # Mixed-precision fused multiply-add (see FMA_MIX_HELPERS). op_sel_hi picks binary16 for a source and op_sel
            # its high half; the printer omits an all-zero op_sel or op_sel_hi. Output modifiers, DPP and SDWA are not in
            # this grammar. A binary16 result replaces only its half of the destination, as v_cvt_f16_f32 does.
            op, dst, *tokens, s0, s1, s2, h0, h1, h2, clamp = m.groups()
            if mask != "entry":
                raise ValueError("Invalid arithmetic operation")
            if dst in sample_dest:
                raise ValueError("Write overlaps an outstanding sample")
            old = vector.get(dst)
            if op != "mix_f32" and old is not None and tracked_word(old) is None:
                raise ValueError("Unsupported arithmetic destination")
            if "fma_mix" not in helpers:
                helpers.add("fma_mix")
                lines.insert(lines.index(PREAMBLE), FMA_MIX_HELPERS)
            selects = [int(x or 0) for x in (s0, s1, s2)]
            highs = [int(x or 0) for x in (h0, h1, h2)]
            a, b, c = (fma_mix_source(t, h, s, scalar, vector, pending, sample_pending)
                       for t, h, s in zip(tokens, highs, selects))
            wide = op == "mix_f32"
            expression = f"fma_mix_round({a}, {b}, {c}, {'true' if wide else 'false'})"
            if clamp:
                expression = f"fma_mix_sat({expression}, {'true' if wide else 'false'})"
            if op == "mixlo_f16":
                keep = f"({tracked_word(old)} & 0xffff0000u)" if old is not None else "0u"
                expression = f"{keep} | {expression}"
            elif op == "mixhi_f16":
                keep = f"({tracked_word(old)} & 0xffffu)" if old is not None else "0u"
                expression = f"{keep} | ({expression} << 16u)"
            vector[dst] = f"alu{i}"
            lines.append(f"    precise float alu{i} = asfloat({expression});")
        elif m := match(r"v_cvt_pkrtz_f16_f32_e32 (v\d+), (v\d+), (v\d+)"):
            dst, lo, hi = m.groups()
            pair = []
            for n, register in enumerate((lo, hi)):
                value = vector[register]
                if isinstance(value, tuple) and tracked_word(value) is not None:
                    # A raw word is exported as the float with those bits; the export is where it becomes a float.
                    lines.append(f"    precise float alu{i}_{n} = asfloat({value[1]});")
                    value = f"alu{i}_{n}"
                pair.append(value)
            if mask != "entry" or sample_pending or not all(isinstance(v, str) and v.startswith(("sample", "alu")) for v in pair):
                raise ValueError("Unsupported pack operand")
            vector[dst] = tuple(pair)
        elif m := match(r"exp mrt0,? (v\d+), \1, (v\d+), \2 done compr vm"):
            pairs = [vector[v] for v in m.groups()]
            if mask != "entry" or exported or not all(isinstance(p, tuple) and len(p)==2 and
                    all(v.startswith(("sample", "alu")) for v in p) for p in pairs):
                raise ValueError("Unsupported export")
            args = [f"export16({v})" for pair in pairs for v in pair]
            lines.append(f"    return float4({', '.join(args)});")
            exported = True
        elif m := match(r"buffer_load_dword(x[234])? (v\d+|v\[\d+:\d+\]), (off|v\d+|v\[\d+:\d+\]), (s\[\d+:\d+\]), (s\d+|0|off)((?: \S+)*)"):
            # MUBUF loads of whole dwords through a runtime V#. glc, slc and dlc select cache behavior and do not change
            # the loaded value; tfe, lds and every other modifier are refused.
            width, dst_token, addr_token, rsrc_token, soffset_token, modifiers = m.groups()
            count = int(width[1]) if width else 1
            flags = set()
            inst_offset = 0
            for modifier in modifiers.split():
                if bm := re.fullmatch(r"offset:(\d+)", modifier):
                    if "offset" in flags:
                        raise ValueError("Repeated buffer offset")
                    flags.add("offset")
                    inst_offset = int(bm[1])
                elif modifier in ("offen", "idxen", "glc", "slc", "dlc") and modifier not in flags:
                    flags.add(modifier)
                else:
                    raise ValueError(f"Unsupported buffer load modifier {modifier}")
            if mask != "entry" or inst_offset > 4095:
                raise ValueError("Invalid buffer load")
            offen, idxen = "offen" in flags, "idxen" in flags
            dsts = vgprs(dst_token, count)
            if addr_token == "off":
                voffset = vindex = "0u"
                if offen or idxen:
                    raise ValueError("Buffer address register missing")
            elif addr_token.startswith("v["):
                first, last = map(int, re.findall(r"\d+", addr_token))
                if not (offen and idxen) or last != first + 1:
                    raise ValueError("Buffer address register pair needs both idxen and offen")
                vindex = vector_u32(f"v{first}", scalar, vector, pending, sample_pending)
                voffset = vector_u32(f"v{last}", scalar, vector, pending, sample_pending)
            else:
                if offen == idxen:
                    raise ValueError("A single buffer address register needs exactly one of idxen and offen")
                word = vector_u32(addr_token, scalar, vector, pending, sample_pending)
                voffset, vindex = (word, "0u") if offen else ("0u", word)
            rsrc = [f"s{n}" for n in registers(*re.findall(r"\d+", rsrc_token), 4)]
            if int(rsrc[0][1:]) % 4 or int(rsrc[3][1:]) > 105:
                raise ValueError("Buffer resource registers must be four aligned scalar registers")
            words = [vector_u32(r, scalar, vector, pending, sample_pending) for r in rsrc]
            soffset = "0u" if soffset_token in ("0", "off") else vector_u32(soffset_token, scalar, vector, pending, sample_pending)
            if any(d in sample_dest for d in dsts):
                raise ValueError("Write overlaps an outstanding sample")
            uses_memory = True
            lines.append(f"    uint4 rsrc{i} = uint4({', '.join(words)});")
            for j, d in enumerate(dsts):
                lines.append(f"    uint mem{i}_{j} = buffer_load32(rsrc{i}, {soffset}, {voffset}, {inst_offset}u, {vindex}, {j}u);")
                vector[d] = ("uint", f"mem{i}_{j}")
            sample_dest.update(dsts)
            sample_pending = True
        elif m := match(r"global_load_dword(x[234])? (v\d+|v\[\d+:\d+\]), (v\d+|v\[\d+:\d+\]), (off|s\[\d+:\d+\])((?: \S+)*)"):
            # Global loads of whole dwords: a 64-bit VGPR pair with saddr off, or an SGPR pair plus a 32-bit VGPR offset,
            # then the signed 12-bit instruction offset. Cache modifiers are accepted as above; the rest are refused.
            width, dst_token, addr_token, saddr_token, modifiers = m.groups()
            count = int(width[1]) if width else 1
            flags = set()
            immediate = 0
            for modifier in modifiers.split():
                if gm := re.fullmatch(r"offset:(-?\d+)", modifier):
                    if "offset" in flags:
                        raise ValueError("Repeated global offset")
                    flags.add("offset")
                    immediate = int(gm[1])
                elif modifier in ("glc", "slc", "dlc") and modifier not in flags:
                    flags.add(modifier)
                else:
                    raise ValueError(f"Unsupported global load modifier {modifier}")
            if mask != "entry" or not -2048 <= immediate <= 2047:
                raise ValueError("Invalid global load")
            dsts = vgprs(dst_token, count)
            if saddr_token == "off":
                if not addr_token.startswith("v["):
                    raise ValueError("Global load without saddr needs a 64-bit address register pair")
                first, last = map(int, re.findall(r"\d+", addr_token))
                if last != first + 1:
                    raise ValueError("Invalid global address register pair")
                base = [vector_u32(f"v{first}", scalar, vector, pending, sample_pending),
                        vector_u32(f"v{last}", scalar, vector, pending, sample_pending)]
                voffset = "0u"
            else:
                if addr_token.startswith("v["):
                    raise ValueError("Global load with saddr needs a 32-bit offset register")
                base = [vector_u32(r, scalar, vector, pending, sample_pending) for r in sgpr_pair(saddr_token)]
                voffset = vector_u32(addr_token, scalar, vector, pending, sample_pending)
            if any(d in sample_dest for d in dsts):
                raise ValueError("Write overlaps an outstanding sample")
            bits = immediate & 0xffffffffffffffff
            uses_memory = True
            for j, d in enumerate(dsts):
                lines.append(f"    uint mem{i}_{j} = global_load32(uint2({base[0]}, {base[1]}), {voffset}, "
                             f"uint2({bits & 0xffffffff}u, {bits >> 32}u), {j}u);")
                vector[d] = ("uint", f"mem{i}_{j}")
            sample_dest.update(dsts)
            sample_pending = True
        elif line.startswith("flat_load"):
            raise ValueError("flat loads are not lowered")
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
    if uses_memory:
        pos = lines.index(PREAMBLE)
        lines[pos:pos] = [TITLE_LOOKUP.read_text(encoding="utf-8"), TITLE_DECLARATIONS, MEMORY_HELPERS]
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
