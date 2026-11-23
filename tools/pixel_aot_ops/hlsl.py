"""HLSL text the lowering emits: the preamble with its numeric helpers, title-memory helpers and the named
helper functions a form asks for through `st.helpers`."""
from pathlib import Path


# The pixel entry's declarations and signature around the stage-neutral numeric helpers. HELPERS is what another stage
# (tools/vertex_aot.py) emits with its own entry; PREAMBLE is unchanged for the pixel stage.
PIXEL_DECLARATIONS = """Texture2D<float4> tex : register(t0);
SamplerState samp : register(s0);
"""
HELPERS = """// v_cmp_class_f32: the ten binary32 classes of LLVM SIInstrFlags::ClassFlags, from the raw encoding:
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
"""
PIXEL_ENTRY = "float4 main(float2 uv : TEXCOORD0) : SV_Target0 {"
PREAMBLE = PIXEL_DECLARATIONS + HELPERS + PIXEL_ENTRY
# A program bound without a sampler (lower(sampler=None), from R0Y00/Xbox2Windows#480 by Royoo) takes no texture sample
# and declares neither the texture nor the sampler.
UNSAMPLED_PREAMBLE = HELPERS + PIXEL_ENTRY


# Title memory for buffer and global loads (see docs/experiments.md). The declarations match the pixel root signature
# of the harness (tests/pixel_aot_vs.hlsl); src/title_va_lookup.hlsli is read at translation time.
TITLE_LOOKUP = Path(__file__).resolve().parents[2] / "src" / "title_va_lookup.hlsli"
TITLE_DECLARATIONS = """StructuredBuffer<TitleRange> title_ranges : register(t2);
ByteAddressBuffer title_memory[8] : register(t0, space1);
cbuffer TitleCount : register(b1) { uint title_range_count; };
"""
# A program that stores or runs atomics binds the same slots as UAVs (u0, space1, the harness's write table) and loads
# through them too, since one resource cannot be both a shader resource and an unordered-access target in one draw.
TITLE_RW_DECLARATIONS = TITLE_DECLARATIONS.replace("ByteAddressBuffer title_memory[8] : register(t0, space1);",
                                                   "RWByteAddressBuffer title_memory[8] : register(u0, space1);")
assert TITLE_RW_DECLARATIONS != TITLE_DECLARATIONS
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
# Sub-dword loads (ubyte, sbyte, ushort, sshort and the d16 forms) read bytes one at a time, so any alignment works,
# and apply the same range rule to the offset of their first byte. Typed loads (buffer_load_format_*, tbuffer_load_format_*)
# decode every gfx10 unified format (LLVM AMDGPU::UfmtGFX10 numbers, Mesa radv_formats.c for the packed component order):
# see buffer_load_format below. The V# DST_SEL fields (word 3 bits 0 to 11: 0 = 0, 1 = 1, 4 to 7 = X, Y, Z, W) place the
# converted components; an invalid format and an out-of-range element read zero in every channel. The UNORM and SNORM
# rounding (to nearest even) and the NaN payloads of the small floats follow the Vulkan conversion rules
# (c / (2^n - 1), max(c / (2^(n-1) - 1), -1)) exactly; that console hardware rounds the same way is not checked here.
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
uint title_load8(uint2 address) {
    uint word = title_load32(uint2(address.x & ~3u, address.y));
    return (word >> ((address.x & 3u) * 8u)) & 0xffu;
}
uint title_load16(uint2 address) {
    return title_load8(address) | (title_load8(add64(address, uint2(1u, 0u))) << 8);
}
bool buffer_address(uint4 rsrc, uint soffset, uint voffset, uint inst_offset, uint index, out uint2 address) {
    uint stride = (rsrc.y >> 16) & 0x3fffu;
    uint num_records = rsrc.z;
    uint oob_select = (rsrc.w >> 28) & 3u;
    bool unmodelled = (rsrc.y >> 31) != 0u || ((rsrc.w >> 23) & 1u) != 0u;
    uint offset = voffset + inst_offset;
    bool wrapped = offset < voffset;
    bool in_range;
    if (oob_select == 0u) in_range = index < num_records && offset < stride;
    else if (oob_select == 1u) in_range = index < num_records;
    else if (oob_select == 2u) in_range = num_records != 0u;
    else in_range = offset < num_records;
    address = add64(add64(uint2(rsrc.x, rsrc.y & 0xffffu), uint2(soffset, 0u)), add64(mul_stride(stride, index), uint2(offset, 0u)));
    return !(unmodelled || wrapped || !in_range);
}
uint buffer_load_sub(uint4 rsrc, uint soffset, uint voffset, uint inst_offset, uint index, uint bytes) {
    uint2 address;
    if (!buffer_address(rsrc, soffset, voffset, inst_offset, index, address)) return 0u;
    return bytes == 1u ? title_load8(address) : title_load16(address);
}
// gfx10 unified buffer formats (LLVM AMDGPU::UfmtGFX10, 1..77): component widths in bits, x first from bit 0 (AMD
// names list components from the most significant: 10_11_11 is z10 y11 x11), and the numeric kind of every component:
// 0 UNORM, 1 SNORM, 2 USCALED, 3 SSCALED, 4 UINT, 5 SINT, 6 FLOAT. False for INVALID (0) and numbers past 77.
bool buffer_format_layout(uint f, out uint4 bits, out uint kind) {
    bits = uint4(0u, 0u, 0u, 0u);
    kind = 0u;
    if (f >= 1u && f <= 6u) { bits = uint4(8u, 0u, 0u, 0u); kind = f - 1u; }
    else if (f >= 7u && f <= 13u) { bits = uint4(16u, 0u, 0u, 0u); kind = f - 7u; }
    else if (f >= 14u && f <= 19u) { bits = uint4(8u, 8u, 0u, 0u); kind = f - 14u; }
    else if (f >= 20u && f <= 22u) { bits = uint4(32u, 0u, 0u, 0u); kind = f - 16u; }
    else if (f >= 23u && f <= 29u) { bits = uint4(16u, 16u, 0u, 0u); kind = f - 23u; }
    else if (f >= 30u && f <= 36u) { bits = uint4(11u, 11u, 10u, 0u); kind = f - 30u; }
    else if (f >= 37u && f <= 43u) { bits = uint4(10u, 11u, 11u, 0u); kind = f - 37u; }
    else if (f >= 44u && f <= 49u) { bits = uint4(2u, 10u, 10u, 10u); kind = f - 44u; }
    else if (f >= 50u && f <= 55u) { bits = uint4(10u, 10u, 10u, 2u); kind = f - 50u; }
    else if (f >= 56u && f <= 61u) { bits = uint4(8u, 8u, 8u, 8u); kind = f - 56u; }
    else if (f >= 62u && f <= 64u) { bits = uint4(32u, 32u, 0u, 0u); kind = f - 58u; }
    else if (f >= 65u && f <= 71u) { bits = uint4(16u, 16u, 16u, 16u); kind = f - 65u; }
    else if (f >= 72u && f <= 74u) { bits = uint4(32u, 32u, 32u, 0u); kind = f - 68u; }
    else if (f >= 75u && f <= 77u) { bits = uint4(32u, 32u, 32u, 32u); kind = f - 71u; }
    else return false;
    return true;
}
// c / d as binary32, rounded to nearest even, for 0 <= c <= d < 2^17: long division one quotient bit at a time (no
// floating-point division, whose rounding the shader model does not fix).
uint norm_bits(uint c, uint d) {
    if (c == 0u) return 0u;
    if (c >= d) return 0x3f800000u;
    uint r = c;
    uint p = 0u;
    [loop] for (uint k = 0u; k < 32u; ++k) {
        r <<= 1;
        p += 1u;
        if (r >= d) { r -= d; break; }
    }
    uint m = 1u;
    [loop] for (uint i = 0u; i < 23u; ++i) {
        r <<= 1;
        m <<= 1;
        if (r >= d) { r -= d; m |= 1u; }
    }
    r <<= 1;
    uint guard = r >= d ? 1u : 0u;
    if (guard != 0u) r -= d;
    if (guard != 0u && (r != 0u || (m & 1u) != 0u)) m += 1u;
    uint e = 127u - p;
    if (m == 0x1000000u) { m >>= 1; e += 1u; }
    return (e << 23) | (m & 0x7fffffu);
}
// A float with a 5-bit exponent (bias 15) and `mant` mantissa bits (16-bit: signed, 10; the packed 11- and 10-bit
// floats: unsigned, 6 and 5) as binary32: exact, subnormals normalized, Inf and NaN kept with the mantissa shifted.
uint small_float_bits(uint v, uint mant, bool signed_value) {
    uint sign = signed_value ? (v >> (5u + mant)) & 1u : 0u;
    uint e = (v >> mant) & 31u;
    uint m = v & ((1u << mant) - 1u);
    uint out = 0u;
    if (e == 31u) out = 0x7f800000u | (m << (23u - mant));
    else if (e != 0u) out = ((e + 112u) << 23) | (m << (23u - mant));
    else if (m != 0u) {
        uint shift = 0u;
        [loop] for (uint k = 0u; k < 11u; ++k) {
            if ((m & (1u << mant)) != 0u) break;
            m <<= 1;
            shift += 1u;
        }
        out = ((113u - shift) << 23) | ((m & ((1u << mant) - 1u)) << (23u - mant));
    }
    return out | (sign << 31);
}
uint convert_component(uint v, uint width, uint kind) {
    uint top = width == 32u ? 0u : 1u << (width - 1u);
    uint sext = width == 32u ? v : ((v & top) != 0u ? v | ~((top << 1) - 1u) : v);
    if (kind == 0u) return norm_bits(v, (top << 1) - 1u);
    if (kind == 1u) {
        if (sext == (0u - top)) return 0xbf800000u;  // the most negative value clamps to -1.0
        uint magnitude = (sext & 0x80000000u) != 0u ? 0u - sext : sext;
        return (sext & 0x80000000u) | norm_bits(magnitude, top - 1u);
    }
    if (kind == 2u) return asuint((float)v);
    if (kind == 3u) return asuint((float)asint(sext));
    if (kind == 4u) return v;
    if (kind == 5u) return sext;
    if (width == 16u) return small_float_bits(v, 10u, true);
    if (width == 11u) return small_float_bits(v, 6u, false);
    if (width == 10u) return small_float_bits(v, 5u, false);
    return v;
}
// Typed loads (buffer_load_format_*, tbuffer_load_format_*): the element at the V#'s address in the given format,
// converted component by component (UNORM c / (2^n - 1) and SNORM c / (2^(n-1) - 1) rounded to nearest even, the most
// negative SNORM value -1.0; scaled formats as exact floats; 16-, 11- and 10-bit floats exactly), missing components
// filled with 0, 0 and 1 (1.0 for the float kinds), then placed by DST_SEL. An invalid format and an out-of-range
// element read zero in every channel.
uint4 buffer_load_format(uint4 rsrc, uint soffset, uint voffset, uint inst_offset, uint index, uint format) {
    uint2 address;
    uint4 bits;
    uint kind;
    if (!buffer_format_layout(format, bits, kind) || !buffer_address(rsrc, soffset, voffset, inst_offset, index, address))
        return uint4(0u, 0u, 0u, 0u);
    uint bytes = (bits.x + bits.y + bits.z + bits.w) / 8u;
    uint4 data = uint4(0u, 0u, 0u, 0u);
    if (bytes < 4u) {
        data.x = bytes == 1u ? title_load8(address) : title_load16(address);
    } else {
        [unroll] for (uint k = 0u; k < 4u; ++k) {
            uint2 at = add64(address, uint2(4u * k, 0u));
            if (4u * k < bytes)
                data[k] = (at.x & 3u) == 0u ? title_load32(at)
                                            : title_load16(at) | (title_load16(add64(at, uint2(2u, 0u))) << 16);
        }
    }
    bool floats = kind != 4u && kind != 5u;
    uint4 raw = uint4(0u, 0u, 0u, floats ? 0x3f800000u : 1u);
    uint offset = 0u;
    [unroll] for (uint c = 0u; c < 4u; ++c) {
        uint width = bits[c];
        if (width != 0u) {
            uint word = data[offset >> 5];
            uint value = width == 32u ? word : (word >> (offset & 31u)) & ((1u << width) - 1u);
            raw[c] = convert_component(value, width, kind);
        }
        offset += width;
    }
    uint4 result;
    [unroll] for (uint c2 = 0u; c2 < 4u; ++c2) {
        uint select = (rsrc.w >> (3u * c2)) & 7u;
        uint one = floats ? 0x3f800000u : 1u;
        result[c2] = select == 1u ? one : (select >= 4u ? raw[select - 4u] : 0u);
    }
    return result;
}
uint global_load_sub(uint2 base, uint voffset, uint2 immediate, uint bytes) {
    uint2 address = add64(add64(base, uint2(voffset, 0u)), immediate);
    return bytes == 1u ? title_load8(address) : title_load16(address);
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
    # The texel offset of an offset MIMG form is packed in its first address VGPR as three signed 6-bit fields, x in
    # bits 5:0 and y in bits 13:8 (z, bits 21:16, is unused by a 2D read), the layout Mesa's ACO and radv pack for
    # RDNA. Direct3D can only give a literal offset, so the offset is added to the coordinate in texels of the level
    # that is read; under point filtering and clamp addressing, moving the coordinate by whole texels reads the texel
    # that many texels away, clamped at the edge, as the offset does. The addition is exact for the power-of-two level
    # sizes; at other sizes a coordinate within one binary32 ulp of a texel edge could land on the other side of it.
    "image_offset_uv": (
        "float2 image_offset_uv(Texture2D<float4> t, float2 uv, float level, uint packed) {\n"
        "    uint w, h, levels;\n"
        "    t.GetDimensions(uint(level), w, h, levels);\n"
        "    int2 o = int2(asint(packed << 26u) >> 26, asint((packed >> 8u) << 26u) >> 26);\n"
        "    return uv + float2(o) / float2(float(w), float(h));\n"
        "}"
    ),
    # The nearest level of an explicit lod, clamped to the levels that exist.
    "image_level": (
        "float image_level(Texture2D<float4> t, float lod) {\n"
        "    uint w, h, levels;\n"
        "    t.GetDimensions(0u, w, h, levels);\n"
        "    return clamp(floor(lod + 0.5f), 0.0f, float(levels - 1u));\n"
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
