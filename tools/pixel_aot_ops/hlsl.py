"""HLSL text the lowering emits: the preamble with its numeric helpers, title-memory helpers and the named
helper functions a form asks for through `st.helpers`."""
from pathlib import Path


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
TITLE_LOOKUP = Path(__file__).resolve().parents[2] / "src" / "title_va_lookup.hlsli"
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

# Helper functions by name, emitted before the preamble in this order when a form adds the name to st.helpers.
# A form module may add its own entries (SALU_HELPERS[name] = text) at import time; they follow these.
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
