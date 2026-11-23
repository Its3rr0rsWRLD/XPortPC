// CPU check of the GFX10.3 descriptor decoder (src/gfx10_descriptors.h): no GPU, builds on Linux and Windows.
//
//   gfx10_descriptors_check            run the cases below; exit 0 on pass, 1 on the first failure
//   gfx10_descriptors_check --dump     print the field table and the image formats (one per line) for
//                                      tests/gfx10_descriptors_fields_check.py, which compares them with Mesa's
//                                      register database
//
// The words below are written field by field with the bit positions of Mesa's gfx10-rsrc.json, the way Mesa's
// ac_build_gfx10_texture_descriptor / ac_build_sampler_descriptor / ac_build_buffer_descriptor fill them (MIT), so a
// decoder that read a field from the wrong bits, or a plan that mapped a value wrongly, fails a case by name.
#include "gfx10_descriptors.h"

#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <string>

using namespace x2w::gfx10;

namespace {

int g_failures = 0;

void expect(bool condition, const char* what)
{
    if (condition) return;
    std::printf("FAIL: %s\n", what);
    ++g_failures;
}

std::uint32_t put(std::uint32_t value, unsigned lo, unsigned hi)
{
    const std::uint32_t mask = hi - lo == 31 ? ~0u : ((1u << (hi - lo + 1)) - 1);
    return (value & mask) << lo;
}

struct ImageWords {
    std::uint64_t va = 0;
    std::uint32_t xor_bits = 0, min_lod = 0, format = 56, width = 1, height = 1;
    std::uint32_t sel[4] = {SelX, SelY, SelZ, SelW};
    std::uint32_t base_level = 0, last_level = 0, sw_mode = 0, bc_swizzle = 0, type = Img2D;
    std::uint32_t depth = 0, pitch_msb = 0, base_array = 0, max_mip = 0, compression = 0;
    void encode(std::uint32_t w[8]) const
    {
        std::memset(w, 0, 32);
        w[0] = static_cast<std::uint32_t>(va >> 8) | xor_bits;  // desc[0] = va >> 8 | tile_swizzle
        w[1] = put(static_cast<std::uint32_t>(va >> 40), 0, 7) | put(min_lod, 8, 19) | put(format, 20, 28) |
               put(width - 1, 30, 31);
        w[2] = put((width - 1) >> 2, 0, 11) | put(height - 1, 14, 27) | put(1, 31, 31);
        w[3] = put(sel[0], 0, 2) | put(sel[1], 3, 5) | put(sel[2], 6, 8) | put(sel[3], 9, 11) | put(base_level, 12, 15) |
               put(last_level, 16, 19) | put(sw_mode, 20, 24) | put(bc_swizzle, 25, 27) | put(type, 28, 31);
        w[4] = put(depth, 0, 12) | put(pitch_msb, 13, 13) | put(base_array, 16, 28);
        w[5] = put(max_mip, 4, 7) | put(4, 20, 22);  // PERF_MOD 4, as Mesa sets it
        w[6] = put(compression, 21, 21);
    }
};

struct SamplerWords {
    std::uint32_t clamp[3] = {}, aniso = 0, compare = 0, unnorm = 0, trunc = 0, filter_mode = 0, degamma = 0;
    std::uint32_t min_lod = 0, max_lod = 0, lod_bias = 0, bias_sec = 0, mag = 0, min = 0, z = 0, mip = 0;
    std::uint32_t border_type = 0, border_ptr = 0;
    void encode(std::uint32_t w[4]) const
    {
        w[0] = put(clamp[0], 0, 2) | put(clamp[1], 3, 5) | put(clamp[2], 6, 8) | put(aniso, 9, 11) |
               put(compare, 12, 14) | put(unnorm, 15, 15) | put(aniso >> 1, 16, 18) | put(degamma, 20, 20) |
               put(aniso, 21, 26) | put(trunc, 27, 27) | put(filter_mode, 29, 30);
        w[1] = put(min_lod, 0, 11) | put(max_lod, 12, 23) | put(aniso ? aniso + 6 : 0, 24, 27);
        w[2] = put(lod_bias, 0, 13) | put(bias_sec, 14, 19) | put(mag, 20, 21) | put(min, 22, 23) | put(z, 24, 25) |
               put(mip, 26, 27) | put(1, 29, 29);
        w[3] = put(border_ptr, 0, 11) | put(border_type, 30, 31);
    }
};

std::uint32_t mapping(std::uint32_t a, std::uint32_t b, std::uint32_t c, std::uint32_t d)
{
    return a | b << 3 | c << 6 | d << 9 | 1u << 12;
}

const Config kConfig{MakeGbAddrConfig(4, 4), true, true};

void image_cases()
{
    // An 8x8 RGBA8 64 KiB R_X surface with 4 mips, the XOR in the low bits of word 0, levels 1..2 viewed.
    ImageWords t;
    t.va = 0x0000123456780000ull & ~0xffffull;
    t.xor_bits = 0x8b;
    t.width = 8;
    t.height = 8;
    t.sw_mode = 27;  // SW_64KB_R_X
    t.max_mip = 3;
    t.base_level = 1;
    t.last_level = 2;
    t.min_lod = 0x180;  // 1.5
    t.sel[0] = SelZ;
    t.sel[1] = SelX;
    t.sel[2] = SelOne;
    t.sel[3] = SelZero;
    std::uint32_t w[8];
    t.encode(w);
    ImageDescriptor d;
    DecodeImage(w, &d);
    expect(d.width == 8 && d.height == 8, "T# width/height (WIDTH_LO|WIDTH_HI, HEIGHT) + 1");
    expect(d.format == 56, "T# FORMAT");
    expect(d.sw_mode == 27 && d.type == Img2D, "T# SW_MODE and TYPE");
    expect(d.base_level == 1 && d.last_level == 2 && d.max_mip == 3, "T# BASE_LEVEL, LAST_LEVEL, MAX_MIP");
    expect(d.dst_sel[0] == SelZ && d.dst_sel[1] == SelX && d.dst_sel[2] == SelOne && d.dst_sel[3] == SelZero,
           "T# DST_SEL");
    expect(d.min_lod == 0x180, "T# MIN_LOD");
    TexturePlan p;
    std::string why;
    expect(PlanTexture(kConfig, d, &p, &why), ("plan of an R_X T#: " + why).c_str());
    expect(p.address == t.va, "the base address has the pipe/bank XOR taken out");
    expect(p.surface.pipe_bank_xor == 0x8b, "the pipe/bank XOR comes from the low bits of word 0");
    expect(p.surface.mip_levels == 4 && p.most_detailed_mip == 1 && p.mip_levels == 2,
           "resource mips MAX_MIP + 1, view BASE_LEVEL..LAST_LEVEL");
    expect(p.dxgi_format == 28, "8_8_8_8_UNORM -> DXGI_FORMAT_R8G8B8A8_UNORM");
    expect(p.min_lod_clamp == 1.5f, "MIN_LOD u4.8 -> 1.5");
    expect(p.component_mapping == mapping(2, 0, 5, 4), "DST_SEL (Z, X, 1, 0) -> component mapping");
    expect(p.bytes == 65536, "an 8x8 RGBA8 R_X chain is one 64 KiB block");

    // The same surface 4 KiB S_X: the XOR is 4 bits; bits above it stay in the address.
    t.sw_mode = 21;  // SW_4KB_S_X
    t.va = 0x40000000ull;
    t.xor_bits = 0x36;  // bits 4-5 are address bits for a 4 KiB block
    t.max_mip = 0;
    t.base_level = t.last_level = 0;
    t.encode(w);
    DecodeImage(w, &d);
    expect(PlanTexture(kConfig, d, &p, &why), ("plan of an S_X T#: " + why).c_str());
    expect(p.surface.pipe_bank_xor == 0x6 && p.address == 0x40000000ull + (0x30ull << 8),
           "a 4 KiB XOR mode takes 4 bits of XOR");

    // A linear T#: no XOR; every bit of word 0 is address.
    t.sw_mode = 0;
    t.xor_bits = 0;
    t.va = 0x12345600ull;
    t.encode(w);
    DecodeImage(w, &d);
    expect(PlanTexture(kConfig, d, &p, &why) && p.address == 0x12345600ull && p.surface.pipe_bank_xor == 0,
           "linear T# address");

    // Wide surfaces: width 6000 needs WIDTH_HI.
    t.width = 6000;
    t.height = 3;
    t.encode(w);
    DecodeImage(w, &d);
    expect(d.width == 6000 && d.height == 3, "T# 14-bit width across WIDTH_LO and WIDTH_HI");

    // 5_6_5: hardware channel 0 is DXGI blue.
    t = ImageWords();
    t.format = 133;
    t.width = t.height = 4;
    t.encode(w);
    DecodeImage(w, &d);
    expect(PlanTexture(kConfig, d, &p, &why) && p.dxgi_format == 85 && p.component_mapping == mapping(2, 1, 0, 3),
           "5_6_5_UNORM -> B5G6R5_UNORM with red from component 2");
    // BC7: 16-byte 4x4 elements.
    t.format = 181;
    t.width = t.height = 16;
    t.encode(w);
    DecodeImage(w, &d);
    expect(PlanTexture(kConfig, d, &p, &why) && p.dxgi_format == 98 && p.surface.element_bytes == 16 &&
               p.surface.element_width == 4,
           "BC7_UNORM -> 16-byte 4x4 elements");

    // Refusals.
    const auto refused = [&](ImageWords words, const char* what, const char* reason) {
        words.encode(w);
        DecodeImage(w, &d);
        std::string text;
        const bool planned = PlanTexture(kConfig, d, &p, &text);
        expect(!planned && text.find(reason) != std::string::npos, what);
    };
    ImageWords base;
    base.width = base.height = 8;
    ImageWords r = base;
    r.type = Img2DArray;
    refused(r, "a 2D array T# is refused", "TYPE 13");
    r = base;
    r.type = 0;
    refused(r, "a buffer-typed descriptor is refused as a T#", "not an image");
    r = base;
    r.format = 140;  // 32_FLOAT_CLAMP
    refused(r, "a format without a desktop equivalent is refused", "FORMAT 140");
    r = base;
    r.compression = 1;
    refused(r, "a DCC-compressed T# is refused", "COMPRESSION_EN");
    r = base;
    r.depth = 255;  // linear: custom pitch 256
    refused(r, "a linear T# with a custom pitch is refused", "custom pitch");
    r = base;
    r.sel[1] = 2;
    refused(r, "a reserved DST_SEL is refused", "reserved selector");
    r = base;
    r.last_level = 1;
    refused(r, "LAST_LEVEL above MAX_MIP is refused", "levels out of order");
    r = base;
    r.sw_mode = 3;  // reserved mode
    refused(r, "a reserved swizzle mode is refused", "does not cover");
}

void sampler_cases()
{
    std::uint32_t w[4];
    SamplerDescriptor d;
    DesktopSampler s;
    std::string why;
    SamplerWords point;
    point.clamp[0] = point.clamp[1] = point.clamp[2] = 2;  // CLAMP_LAST_TEXEL
    point.max_lod = 15 << 8;
    point.mip = 1;  // MIP_FILTER_POINT
    point.encode(w);
    DecodeSampler(w, &d);
    expect(d.clamp_x == 2 && d.clamp_y == 2 && d.clamp_z == 2 && d.max_lod == 15 << 8 && d.mip_filter == 1,
           "S# fields of a point clamp sampler");
    expect(PlanSampler(d, &s, &why) && s.filter == 0 && s.address_u == 3 && s.address_v == 3 && s.max_lod == 15.0f &&
               s.min_lod == 0.0f && s.comparison_func == 1,
           "point clamp -> D3D12_FILTER_MIN_MAG_MIP_POINT, CLAMP, NEVER");

    SamplerWords linear;
    linear.clamp[0] = 0;  // WRAP
    linear.clamp[1] = 1;  // MIRROR
    linear.clamp[2] = 3;  // MIRROR_ONCE_LAST_TEXEL
    linear.mag = 1;
    linear.min = 0;
    linear.mip = 2;
    linear.lod_bias = (1u << 14) - 0x80;  // -0.5 in s5.8
    linear.min_lod = 0x100;
    linear.max_lod = 0x280;
    linear.filter_mode = 2;  // MAX
    linear.compare = 3;      // LESSEQUAL
    linear.border_type = 1;
    linear.encode(w);
    DecodeSampler(w, &d);
    expect(PlanSampler(d, &s, &why), ("plan of a linear sampler: " + why).c_str());
    expect(s.filter == (0u << 4 | 1u << 2 | 1u | 3u << 7), "min point, mag linear, mip linear, maximum reduction");
    expect(s.address_u == 1 && s.address_v == 2 && s.address_w == 5, "WRAP, MIRROR, MIRROR_ONCE");
    expect(s.mip_lod_bias == -0.5f && s.min_lod == 1.0f && s.max_lod == 2.5f, "LOD bias s5.8 and LOD range u4.8");
    expect(s.comparison_func == 4, "SQ_TEX_DEPTH_COMPARE_LESSEQUAL -> D3D12_COMPARISON_FUNC_LESS_EQUAL");
    expect(s.border_color[3] == 1.0f && s.border_color[0] == 0.0f, "BORDER_COLOR_OPAQUE_BLACK");

    SamplerWords aniso;
    aniso.aniso = 3;  // 8x
    aniso.mag = aniso.min = 3;
    aniso.mip = 2;
    aniso.clamp[0] = aniso.clamp[1] = aniso.clamp[2] = 6;  // CLAMP_BORDER
    aniso.border_type = 2;
    aniso.encode(w);
    DecodeSampler(w, &d);
    expect(PlanSampler(d, &s, &why) && s.filter == 0x55 && s.max_anisotropy == 8 && s.address_u == 4 &&
               s.border_color[0] == 1.0f,
           "8x anisotropic with a white border");

    SamplerWords none = point;
    none.mip = 0;
    none.min_lod = 0x200;
    none.encode(w);
    DecodeSampler(w, &d);
    expect(PlanSampler(d, &s, &why) && s.min_lod == 2.0f && s.max_lod == 2.0f,
           "MIP_FILTER_NONE reads one level: MaxLOD = MinLOD");

    const auto refused = [&](SamplerWords words, const char* what, const char* reason) {
        words.encode(w);
        DecodeSampler(w, &d);
        std::string text;
        expect(!PlanSampler(d, &s, &text) && text.find(reason) != std::string::npos, what);
    };
    SamplerWords r = point;
    r.clamp[1] = 4;
    refused(r, "CLAMP_HALF_BORDER is refused", "HALF_BORDER");
    r = point;
    r.unnorm = 1;
    refused(r, "FORCE_UNNORMALIZED is refused", "FORCE_UNNORMALIZED");
    r = point;
    r.border_type = 3;
    refused(r, "a border colour from the table is refused", "REGISTER");
    r = point;
    r.bias_sec = 1;
    refused(r, "LOD_BIAS_SEC is refused", "LOD_BIAS_SEC");
    r = aniso;
    r.mip = 1;
    refused(r, "anisotropy with point mips is refused", "linear mip");
    r = point;
    r.lod_bias = 20 << 8;
    refused(r, "a LOD bias above 15.99 is refused", "LOD_BIAS outside");
    r = point;
    r.degamma = 1;
    refused(r, "FORCE_DEGAMMA is refused", "DEGAMMA");
}

void buffer_cases()
{
    // ac_build_buffer_descriptor: word0 va, word1 va hi | stride, word2 size, word3 dst_sel | format | oob | type 0.
    const std::uint64_t va = 0x00007ffe12345670ull;
    std::uint32_t w[4] = {static_cast<std::uint32_t>(va), put(static_cast<std::uint32_t>(va >> 32), 0, 15) | put(16, 16, 29),
                          4096, put(SelX, 0, 2) | put(SelY, 3, 5) | put(SelZ, 6, 8) | put(SelW, 9, 11) |
                                    put(22, 12, 18) | put(3, 28, 29) | put(1, 24, 24)};
    BufferDescriptor d;
    DecodeBuffer(w, &d);
    expect(d.address == va && d.stride == 16 && d.num_records == 4096, "V# address, stride, num_records");
    expect(d.format == 22 && d.oob_select == 3 && d.type == 0 && d.resource_level == 1 && d.dst_sel[3] == SelW,
           "V# format, OOB_SELECT, TYPE, dst_sel");
    std::uint64_t address = 0, bytes = 0;
    std::string why;
    expect(PlanConstantBuffer(d, &address, &bytes, &why) && address == va && bytes == 65536,
           "a strided constant V# covers num_records * stride bytes");
    w[1] &= ~put(0x3fff, 16, 29);
    DecodeBuffer(w, &d);
    expect(PlanConstantBuffer(d, &address, &bytes, &why) && bytes == 4096, "a raw constant V# covers num_records bytes");
    w[3] |= put(1, 30, 31);
    DecodeBuffer(w, &d);
    expect(!PlanConstantBuffer(d, &address, &bytes, &why), "a V# with TYPE 1 is refused");
    w[3] &= ~put(3, 30, 31);
    w[1] |= put(1, 31, 31);
    DecodeBuffer(w, &d);
    expect(!PlanConstantBuffer(d, &address, &bytes, &why), "a swizzled V# is refused as constants");
}

void table_cases()
{
    // No two fields of one register overlap, and every lookup the decoders make names a field.
    for (unsigned i = 0; i < kFieldCount; ++i)
        for (unsigned j = i + 1; j < kFieldCount; ++j)
            if (!std::strcmp(kFields[i].reg, kFields[j].reg) && kFields[i].word == kFields[j].word)
                expect(kFields[i].hi < kFields[j].lo || kFields[j].hi < kFields[i].lo, "fields of a register overlap");
    expect(FieldLookupFailures() == 0, "every field the decoders read is in kFields");
    for (unsigned i = 0; i < kImageFormatCount; ++i)
        for (unsigned j = i + 1; j < kImageFormatCount; ++j)
            expect(kImageFormats[i].gfx10 != kImageFormats[j].gfx10, "an image format is listed twice");
}

}  // namespace

int main(int argc, char** argv)
{
    if (argc == 2 && !std::strcmp(argv[1], "--dump")) {
        for (unsigned i = 0; i < kFieldCount; ++i)
            std::printf("field %s %s %u %u\n", kFields[i].reg, kFields[i].name, kFields[i].lo, kFields[i].hi);
        for (unsigned i = 0; i < kImageFormatCount; ++i)
            std::printf("format %s %u\n", kImageFormats[i].name, kImageFormats[i].gfx10);
        // The enumeration values src/gfx10_descriptors.cpp relies on (Mesa gfx6.json).
        static const struct { const char* type; const char* entry; unsigned value; } enums[] = {
            {"SQ_SEL_XYZW01", "SQ_SEL_0", SelZero}, {"SQ_SEL_XYZW01", "SQ_SEL_1", SelOne},
            {"SQ_SEL_XYZW01", "SQ_SEL_X", SelX}, {"SQ_SEL_XYZW01", "SQ_SEL_Y", SelY},
            {"SQ_SEL_XYZW01", "SQ_SEL_Z", SelZ}, {"SQ_SEL_XYZW01", "SQ_SEL_W", SelW},
            {"SQ_RSRC_IMG_TYPE", "SQ_RSRC_IMG_1D", Img1D}, {"SQ_RSRC_IMG_TYPE", "SQ_RSRC_IMG_2D", Img2D},
            {"SQ_RSRC_IMG_TYPE", "SQ_RSRC_IMG_2D_ARRAY", Img2DArray},
            {"SQ_RSRC_BUF_TYPE", "SQ_RSRC_BUF", 0},
            {"SQ_TEX_CLAMP", "SQ_TEX_WRAP", 0}, {"SQ_TEX_CLAMP", "SQ_TEX_MIRROR", 1},
            {"SQ_TEX_CLAMP", "SQ_TEX_CLAMP_LAST_TEXEL", 2}, {"SQ_TEX_CLAMP", "SQ_TEX_MIRROR_ONCE_LAST_TEXEL", 3},
            {"SQ_TEX_CLAMP", "SQ_TEX_CLAMP_HALF_BORDER", 4}, {"SQ_TEX_CLAMP", "SQ_TEX_MIRROR_ONCE_HALF_BORDER", 5},
            {"SQ_TEX_CLAMP", "SQ_TEX_CLAMP_BORDER", 6}, {"SQ_TEX_CLAMP", "SQ_TEX_MIRROR_ONCE_BORDER", 7},
            {"SQ_TEX_XY_FILTER", "SQ_TEX_XY_FILTER_POINT", 0}, {"SQ_TEX_XY_FILTER", "SQ_TEX_XY_FILTER_BILINEAR", 1},
            {"SQ_TEX_XY_FILTER", "SQ_TEX_XY_FILTER_ANISO_POINT", 2},
            {"SQ_TEX_XY_FILTER", "SQ_TEX_XY_FILTER_ANISO_BILINEAR", 3},
            {"SQ_TEX_MIP_FILTER", "SQ_TEX_MIP_FILTER_NONE", 0}, {"SQ_TEX_MIP_FILTER", "SQ_TEX_MIP_FILTER_POINT", 1},
            {"SQ_TEX_MIP_FILTER", "SQ_TEX_MIP_FILTER_LINEAR", 2},
            {"SQ_TEX_BORDER_COLOR", "SQ_TEX_BORDER_COLOR_TRANS_BLACK", 0},
            {"SQ_TEX_BORDER_COLOR", "SQ_TEX_BORDER_COLOR_OPAQUE_BLACK", 1},
            {"SQ_TEX_BORDER_COLOR", "SQ_TEX_BORDER_COLOR_OPAQUE_WHITE", 2},
            {"SQ_TEX_BORDER_COLOR", "SQ_TEX_BORDER_COLOR_REGISTER", 3},
            {"SQ_TEX_DEPTH_COMPARE", "SQ_TEX_DEPTH_COMPARE_NEVER", 0},
            {"SQ_TEX_DEPTH_COMPARE", "SQ_TEX_DEPTH_COMPARE_LESSEQUAL", 3},
            {"SQ_TEX_DEPTH_COMPARE", "SQ_TEX_DEPTH_COMPARE_ALWAYS", 7},
            {"SQ_IMG_FILTER_TYPE", "SQ_IMG_FILTER_MODE_BLEND", 0}, {"SQ_IMG_FILTER_TYPE", "SQ_IMG_FILTER_MODE_MIN", 1},
            {"SQ_IMG_FILTER_TYPE", "SQ_IMG_FILTER_MODE_MAX", 2},
        };
        for (const auto& e : enums) std::printf("enum %s %s %u\n", e.type, e.entry, e.value);
        return 0;
    }
    image_cases();
    sampler_cases();
    buffer_cases();
    table_cases();
    std::printf("%s (%d failures)\n", g_failures ? "FAIL" : "pass", g_failures);
    return g_failures ? 1 : 0;
}
