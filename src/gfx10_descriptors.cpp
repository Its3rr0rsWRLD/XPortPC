// GFX10.3 descriptor words (gfx10_descriptors.h). Field positions: Mesa 26.2.6 src/amd/registers/gfx10-rsrc.json
// (MIT), checked against that file by tests/gfx10_descriptors_fields_check.py.
#include "gfx10_descriptors.h"

#include <cstdio>

namespace x2w::gfx10
{

const Field kFields[] = {
    // T#: SQ_IMG_RSRC_WORD0..7 (words 4-6 in their GFX10.3 layout).
    {"SQ_IMG_RSRC_WORD1", "BASE_ADDRESS_HI", 1, 0, 7},
    {"SQ_IMG_RSRC_WORD1", "MIN_LOD", 1, 8, 19},
    {"SQ_IMG_RSRC_WORD1", "FORMAT", 1, 20, 28},
    {"SQ_IMG_RSRC_WORD1", "WIDTH_LO", 1, 30, 31},
    {"SQ_IMG_RSRC_WORD2", "WIDTH_HI", 2, 0, 11},
    {"SQ_IMG_RSRC_WORD2", "HEIGHT", 2, 14, 27},
    {"SQ_IMG_RSRC_WORD2", "RESOURCE_LEVEL", 2, 31, 31},
    {"SQ_IMG_RSRC_WORD3", "DST_SEL_X", 3, 0, 2},
    {"SQ_IMG_RSRC_WORD3", "DST_SEL_Y", 3, 3, 5},
    {"SQ_IMG_RSRC_WORD3", "DST_SEL_Z", 3, 6, 8},
    {"SQ_IMG_RSRC_WORD3", "DST_SEL_W", 3, 9, 11},
    {"SQ_IMG_RSRC_WORD3", "BASE_LEVEL", 3, 12, 15},
    {"SQ_IMG_RSRC_WORD3", "LAST_LEVEL", 3, 16, 19},
    {"SQ_IMG_RSRC_WORD3", "SW_MODE", 3, 20, 24},
    {"SQ_IMG_RSRC_WORD3", "BC_SWIZZLE", 3, 25, 27},
    {"SQ_IMG_RSRC_WORD3", "TYPE", 3, 28, 31},
    {"SQ_IMG_RSRC_WORD4_gfx103", "DEPTH", 4, 0, 12},
    {"SQ_IMG_RSRC_WORD4_gfx103", "PITCH_MSB", 4, 13, 13},
    {"SQ_IMG_RSRC_WORD4_gfx103", "BASE_ARRAY", 4, 16, 28},
    {"SQ_IMG_RSRC_WORD5_gfx103", "ARRAY_PITCH", 5, 0, 3},
    {"SQ_IMG_RSRC_WORD5_gfx103", "MAX_MIP", 5, 4, 7},
    {"SQ_IMG_RSRC_WORD6_gfx103", "COMPRESSION_EN", 6, 21, 21},
    // S#: SQ_IMG_SAMP_WORD0..3.
    {"SQ_IMG_SAMP_WORD0", "CLAMP_X", 0, 0, 2},
    {"SQ_IMG_SAMP_WORD0", "CLAMP_Y", 0, 3, 5},
    {"SQ_IMG_SAMP_WORD0", "CLAMP_Z", 0, 6, 8},
    {"SQ_IMG_SAMP_WORD0", "MAX_ANISO_RATIO", 0, 9, 11},
    {"SQ_IMG_SAMP_WORD0", "DEPTH_COMPARE_FUNC", 0, 12, 14},
    {"SQ_IMG_SAMP_WORD0", "FORCE_UNNORMALIZED", 0, 15, 15},
    {"SQ_IMG_SAMP_WORD0", "ANISO_THRESHOLD", 0, 16, 18},
    {"SQ_IMG_SAMP_WORD0", "MC_COORD_TRUNC", 0, 19, 19},
    {"SQ_IMG_SAMP_WORD0", "FORCE_DEGAMMA", 0, 20, 20},
    {"SQ_IMG_SAMP_WORD0", "ANISO_BIAS", 0, 21, 26},
    {"SQ_IMG_SAMP_WORD0", "TRUNC_COORD", 0, 27, 27},
    {"SQ_IMG_SAMP_WORD0", "DISABLE_CUBE_WRAP", 0, 28, 28},
    {"SQ_IMG_SAMP_WORD0", "FILTER_MODE", 0, 29, 30},
    {"SQ_IMG_SAMP_WORD0", "SKIP_DEGAMMA", 0, 31, 31},
    {"SQ_IMG_SAMP_WORD1", "MIN_LOD", 1, 0, 11},
    {"SQ_IMG_SAMP_WORD1", "MAX_LOD", 1, 12, 23},
    {"SQ_IMG_SAMP_WORD1", "PERF_MIP", 1, 24, 27},
    {"SQ_IMG_SAMP_WORD1", "PERF_Z", 1, 28, 31},
    {"SQ_IMG_SAMP_WORD2", "LOD_BIAS", 2, 0, 13},
    {"SQ_IMG_SAMP_WORD2", "LOD_BIAS_SEC", 2, 14, 19},
    {"SQ_IMG_SAMP_WORD2", "XY_MAG_FILTER", 2, 20, 21},
    {"SQ_IMG_SAMP_WORD2", "XY_MIN_FILTER", 2, 22, 23},
    {"SQ_IMG_SAMP_WORD2", "Z_FILTER", 2, 24, 25},
    {"SQ_IMG_SAMP_WORD2", "MIP_FILTER", 2, 26, 27},
    {"SQ_IMG_SAMP_WORD2", "MIP_POINT_PRECLAMP", 2, 28, 28},
    {"SQ_IMG_SAMP_WORD2", "ANISO_OVERRIDE", 2, 29, 29},
    {"SQ_IMG_SAMP_WORD2", "BLEND_ZERO_PRT", 2, 30, 30},
    {"SQ_IMG_SAMP_WORD3", "BORDER_COLOR_PTR", 3, 0, 11},
    {"SQ_IMG_SAMP_WORD3", "BORDER_COLOR_TYPE", 3, 30, 31},
    // V#: SQ_BUF_RSRC_WORD0..3 (word 3 in its GFX10.3 layout).
    {"SQ_BUF_RSRC_WORD1", "BASE_ADDRESS_HI", 1, 0, 15},
    {"SQ_BUF_RSRC_WORD1", "STRIDE", 1, 16, 29},
    {"SQ_BUF_RSRC_WORD1", "CACHE_SWIZZLE", 1, 30, 30},
    {"SQ_BUF_RSRC_WORD1", "SWIZZLE_ENABLE", 1, 31, 31},
    {"SQ_BUF_RSRC_WORD3_gfx103", "DST_SEL_X", 3, 0, 2},
    {"SQ_BUF_RSRC_WORD3_gfx103", "DST_SEL_Y", 3, 3, 5},
    {"SQ_BUF_RSRC_WORD3_gfx103", "DST_SEL_Z", 3, 6, 8},
    {"SQ_BUF_RSRC_WORD3_gfx103", "DST_SEL_W", 3, 9, 11},
    {"SQ_BUF_RSRC_WORD3_gfx103", "FORMAT", 3, 12, 18},
    {"SQ_BUF_RSRC_WORD3_gfx103", "INDEX_STRIDE", 3, 21, 22},
    {"SQ_BUF_RSRC_WORD3_gfx103", "ADD_TID_ENABLE", 3, 23, 23},
    {"SQ_BUF_RSRC_WORD3_gfx103", "RESOURCE_LEVEL", 3, 24, 24},
    {"SQ_BUF_RSRC_WORD3_gfx103", "OOB_SELECT", 3, 28, 29},
    {"SQ_BUF_RSRC_WORD3_gfx103", "TYPE", 3, 30, 31},
};
const unsigned kFieldCount = sizeof(kFields) / sizeof(kFields[0]);

namespace
{

// DXGI_FORMAT values (dxgiformat.h; the shim static_asserts them).
enum : std::uint32_t
{
    R32G32B32A32_FLOAT = 2, R32G32B32A32_UINT = 3, R32G32B32A32_SINT = 4,
    R16G16B16A16_FLOAT = 10, R16G16B16A16_UNORM = 11, R16G16B16A16_UINT = 12, R16G16B16A16_SNORM = 13,
    R16G16B16A16_SINT = 14, R32G32_FLOAT = 16, R32G32_UINT = 17, R32G32_SINT = 18,
    R10G10B10A2_UNORM = 24, R10G10B10A2_UINT = 25, R11G11B10_FLOAT = 26,
    R8G8B8A8_UNORM = 28, R8G8B8A8_UNORM_SRGB = 29, R8G8B8A8_UINT = 30, R8G8B8A8_SNORM = 31, R8G8B8A8_SINT = 32,
    R16G16_FLOAT = 34, R16G16_UNORM = 35, R16G16_UINT = 36, R16G16_SNORM = 37, R16G16_SINT = 38,
    R32_FLOAT = 41, R32_UINT = 42, R32_SINT = 43,
    R8G8_UNORM = 49, R8G8_UINT = 50, R8G8_SNORM = 51, R8G8_SINT = 52,
    R16_FLOAT = 54, R16_UNORM = 56, R16_UINT = 57, R16_SNORM = 58, R16_SINT = 59,
    R8_UNORM = 61, R8_UINT = 62, R8_SNORM = 63, R8_SINT = 64, R9G9B9E5_SHAREDEXP = 67,
    BC1_UNORM = 71, BC1_UNORM_SRGB = 72, BC2_UNORM = 74, BC2_UNORM_SRGB = 75, BC3_UNORM = 77, BC3_UNORM_SRGB = 78,
    BC4_UNORM = 80, BC4_SNORM = 81, BC5_UNORM = 83, BC5_SNORM = 84, B5G6R5_UNORM = 85, B5G5R5A1_UNORM = 86,
    BC6H_UF16 = 95, BC6H_SF16 = 96, BC7_UNORM = 98, BC7_UNORM_SRGB = 99, B4G4R4A4_UNORM = 115,
};

unsigned g_lookup_failures;

std::uint32_t bits(std::uint32_t word, unsigned lo, unsigned hi)
{
    const unsigned width = hi - lo + 1;
    return width == 32 ? word : (word >> lo) & ((1u << width) - 1u);
}

// The value of field `name` of register `reg` (kFields) in `words`.
std::uint32_t field(const std::uint32_t* words, const char* reg, const char* name)
{
    for (unsigned i = 0; i < kFieldCount; ++i) {
        const Field& f = kFields[i];
        const char* a = f.reg;
        const char* b = reg;
        while (*a && *a == *b) ++a, ++b;
        if (*a || *b) continue;
        a = f.name;
        b = name;
        while (*a && *a == *b) ++a, ++b;
        if (!*a && !*b) return bits(words[f.word], f.lo, f.hi);
    }
    ++g_lookup_failures;  // a name below that kFields lacks (tests/gfx10_descriptors_check.cpp requires none)
    return 0;
}

}  // namespace

// Identity channel order unless noted. Hardware numbers: GFX10_FORMAT in gfx10-rsrc.json.
#define X2W_FMT(n, name, dxgi, bytes, block) {n, name, dxgi, bytes, block, {0, 1, 2, 3}}
const ImageFormat kImageFormats[] = {
    X2W_FMT(1, "8_UNORM", R8_UNORM, 1, 1),
    X2W_FMT(2, "8_SNORM", R8_SNORM, 1, 1),
    X2W_FMT(5, "8_UINT", R8_UINT, 1, 1),
    X2W_FMT(6, "8_SINT", R8_SINT, 1, 1),
    X2W_FMT(7, "16_UNORM", R16_UNORM, 2, 1),
    X2W_FMT(8, "16_SNORM", R16_SNORM, 2, 1),
    X2W_FMT(11, "16_UINT", R16_UINT, 2, 1),
    X2W_FMT(12, "16_SINT", R16_SINT, 2, 1),
    X2W_FMT(13, "16_FLOAT", R16_FLOAT, 2, 1),
    X2W_FMT(14, "8_8_UNORM", R8G8_UNORM, 2, 1),
    X2W_FMT(15, "8_8_SNORM", R8G8_SNORM, 2, 1),
    X2W_FMT(18, "8_8_UINT", R8G8_UINT, 2, 1),
    X2W_FMT(19, "8_8_SINT", R8G8_SINT, 2, 1),
    X2W_FMT(20, "32_UINT", R32_UINT, 4, 1),
    X2W_FMT(21, "32_SINT", R32_SINT, 4, 1),
    X2W_FMT(22, "32_FLOAT", R32_FLOAT, 4, 1),
    X2W_FMT(23, "16_16_UNORM", R16G16_UNORM, 4, 1),
    X2W_FMT(24, "16_16_SNORM", R16G16_SNORM, 4, 1),
    X2W_FMT(27, "16_16_UINT", R16G16_UINT, 4, 1),
    X2W_FMT(28, "16_16_SINT", R16G16_SINT, 4, 1),
    X2W_FMT(29, "16_16_FLOAT", R16G16_FLOAT, 4, 1),
    X2W_FMT(36, "10_11_11_FLOAT", R11G11B10_FLOAT, 4, 1),  // channels 11, 11, 10 bits from the low end
    X2W_FMT(50, "2_10_10_10_UNORM", R10G10B10A2_UNORM, 4, 1),
    X2W_FMT(54, "2_10_10_10_UINT", R10G10B10A2_UINT, 4, 1),
    X2W_FMT(56, "8_8_8_8_UNORM", R8G8B8A8_UNORM, 4, 1),
    X2W_FMT(57, "8_8_8_8_SNORM", R8G8B8A8_SNORM, 4, 1),
    X2W_FMT(60, "8_8_8_8_UINT", R8G8B8A8_UINT, 4, 1),
    X2W_FMT(61, "8_8_8_8_SINT", R8G8B8A8_SINT, 4, 1),
    X2W_FMT(62, "32_32_UINT", R32G32_UINT, 8, 1),
    X2W_FMT(63, "32_32_SINT", R32G32_SINT, 8, 1),
    X2W_FMT(64, "32_32_FLOAT", R32G32_FLOAT, 8, 1),
    X2W_FMT(65, "16_16_16_16_UNORM", R16G16B16A16_UNORM, 8, 1),
    X2W_FMT(66, "16_16_16_16_SNORM", R16G16B16A16_SNORM, 8, 1),
    X2W_FMT(69, "16_16_16_16_UINT", R16G16B16A16_UINT, 8, 1),
    X2W_FMT(70, "16_16_16_16_SINT", R16G16B16A16_SINT, 8, 1),
    X2W_FMT(71, "16_16_16_16_FLOAT", R16G16B16A16_FLOAT, 8, 1),
    X2W_FMT(75, "32_32_32_32_UINT", R32G32B32A32_UINT, 16, 1),
    X2W_FMT(76, "32_32_32_32_SINT", R32G32B32A32_SINT, 16, 1),
    X2W_FMT(77, "32_32_32_32_FLOAT", R32G32B32A32_FLOAT, 16, 1),
    X2W_FMT(130, "8_8_8_8_SRGB", R8G8B8A8_UNORM_SRGB, 4, 1),
    X2W_FMT(132, "5_9_9_9_FLOAT", R9G9B9E5_SHAREDEXP, 4, 1),
    // Blue in the low bits on both sides: hardware channel 0 (lowest) is DXGI's B (component 2).
    {133, "5_6_5_UNORM", B5G6R5_UNORM, 2, 1, {2, 1, 0, 3}},
    {134, "1_5_5_5_UNORM", B5G5R5A1_UNORM, 2, 1, {2, 1, 0, 3}},
    {136, "4_4_4_4_UNORM", B4G4R4A4_UNORM, 2, 1, {2, 1, 0, 3}},
    X2W_FMT(169, "BC1_UNORM", BC1_UNORM, 8, 4),
    X2W_FMT(170, "BC1_SRGB", BC1_UNORM_SRGB, 8, 4),
    X2W_FMT(171, "BC2_UNORM", BC2_UNORM, 16, 4),
    X2W_FMT(172, "BC2_SRGB", BC2_UNORM_SRGB, 16, 4),
    X2W_FMT(173, "BC3_UNORM", BC3_UNORM, 16, 4),
    X2W_FMT(174, "BC3_SRGB", BC3_UNORM_SRGB, 16, 4),
    X2W_FMT(175, "BC4_UNORM", BC4_UNORM, 8, 4),
    X2W_FMT(176, "BC4_SNORM", BC4_SNORM, 8, 4),
    X2W_FMT(177, "BC5_UNORM", BC5_UNORM, 16, 4),
    X2W_FMT(178, "BC5_SNORM", BC5_SNORM, 16, 4),
    X2W_FMT(179, "BC6_UFLOAT", BC6H_UF16, 16, 4),
    X2W_FMT(180, "BC6_SFLOAT", BC6H_SF16, 16, 4),
    X2W_FMT(181, "BC7_UNORM", BC7_UNORM, 16, 4),
    X2W_FMT(182, "BC7_SRGB", BC7_UNORM_SRGB, 16, 4),
};
#undef X2W_FMT
const unsigned kImageFormatCount = sizeof(kImageFormats) / sizeof(kImageFormats[0]);

unsigned FieldLookupFailures() { return g_lookup_failures; }

const ImageFormat* FindImageFormat(std::uint32_t gfx10_format)
{
    for (unsigned i = 0; i < kImageFormatCount; ++i)
        if (kImageFormats[i].gfx10 == gfx10_format) return &kImageFormats[i];
    return nullptr;
}

float UnsignedFixed8(std::uint32_t value) { return static_cast<float>(value) / 256.0f; }

float SignedFixed8(std::uint32_t value, unsigned width)
{
    const std::int32_t shift = 32 - static_cast<std::int32_t>(width);
    const std::int32_t extended = static_cast<std::int32_t>(value << shift) >> shift;
    return static_cast<float>(extended) / 256.0f;
}

void DecodeImage(const std::uint32_t w[8], ImageDescriptor* d)
{
    *d = {};
    d->address_field = std::uint64_t(w[0]) | std::uint64_t(field(w, "SQ_IMG_RSRC_WORD1", "BASE_ADDRESS_HI")) << 32;
    d->min_lod = field(w, "SQ_IMG_RSRC_WORD1", "MIN_LOD");
    d->format = field(w, "SQ_IMG_RSRC_WORD1", "FORMAT");
    d->width = (field(w, "SQ_IMG_RSRC_WORD1", "WIDTH_LO") | field(w, "SQ_IMG_RSRC_WORD2", "WIDTH_HI") << 2) + 1;
    d->height = field(w, "SQ_IMG_RSRC_WORD2", "HEIGHT") + 1;
    d->dst_sel[0] = field(w, "SQ_IMG_RSRC_WORD3", "DST_SEL_X");
    d->dst_sel[1] = field(w, "SQ_IMG_RSRC_WORD3", "DST_SEL_Y");
    d->dst_sel[2] = field(w, "SQ_IMG_RSRC_WORD3", "DST_SEL_Z");
    d->dst_sel[3] = field(w, "SQ_IMG_RSRC_WORD3", "DST_SEL_W");
    d->base_level = field(w, "SQ_IMG_RSRC_WORD3", "BASE_LEVEL");
    d->last_level = field(w, "SQ_IMG_RSRC_WORD3", "LAST_LEVEL");
    d->sw_mode = field(w, "SQ_IMG_RSRC_WORD3", "SW_MODE");
    d->bc_swizzle = field(w, "SQ_IMG_RSRC_WORD3", "BC_SWIZZLE");
    d->type = field(w, "SQ_IMG_RSRC_WORD3", "TYPE");
    d->depth = field(w, "SQ_IMG_RSRC_WORD4_gfx103", "DEPTH");
    d->pitch_msb = field(w, "SQ_IMG_RSRC_WORD4_gfx103", "PITCH_MSB");
    d->base_array = field(w, "SQ_IMG_RSRC_WORD4_gfx103", "BASE_ARRAY");
    d->array_pitch = field(w, "SQ_IMG_RSRC_WORD5_gfx103", "ARRAY_PITCH");
    d->max_mip = field(w, "SQ_IMG_RSRC_WORD5_gfx103", "MAX_MIP");
    d->compression_en = field(w, "SQ_IMG_RSRC_WORD6_gfx103", "COMPRESSION_EN");
}

void DecodeSampler(const std::uint32_t w[4], SamplerDescriptor* d)
{
    *d = {};
    d->clamp_x = field(w, "SQ_IMG_SAMP_WORD0", "CLAMP_X");
    d->clamp_y = field(w, "SQ_IMG_SAMP_WORD0", "CLAMP_Y");
    d->clamp_z = field(w, "SQ_IMG_SAMP_WORD0", "CLAMP_Z");
    d->max_aniso_ratio = field(w, "SQ_IMG_SAMP_WORD0", "MAX_ANISO_RATIO");
    d->depth_compare_func = field(w, "SQ_IMG_SAMP_WORD0", "DEPTH_COMPARE_FUNC");
    d->force_unnormalized = field(w, "SQ_IMG_SAMP_WORD0", "FORCE_UNNORMALIZED");
    d->aniso_threshold = field(w, "SQ_IMG_SAMP_WORD0", "ANISO_THRESHOLD");
    d->mc_coord_trunc = field(w, "SQ_IMG_SAMP_WORD0", "MC_COORD_TRUNC");
    d->force_degamma = field(w, "SQ_IMG_SAMP_WORD0", "FORCE_DEGAMMA");
    d->aniso_bias = field(w, "SQ_IMG_SAMP_WORD0", "ANISO_BIAS");
    d->trunc_coord = field(w, "SQ_IMG_SAMP_WORD0", "TRUNC_COORD");
    d->disable_cube_wrap = field(w, "SQ_IMG_SAMP_WORD0", "DISABLE_CUBE_WRAP");
    d->filter_mode = field(w, "SQ_IMG_SAMP_WORD0", "FILTER_MODE");
    d->skip_degamma = field(w, "SQ_IMG_SAMP_WORD0", "SKIP_DEGAMMA");
    d->min_lod = field(w, "SQ_IMG_SAMP_WORD1", "MIN_LOD");
    d->max_lod = field(w, "SQ_IMG_SAMP_WORD1", "MAX_LOD");
    d->perf_mip = field(w, "SQ_IMG_SAMP_WORD1", "PERF_MIP");
    d->perf_z = field(w, "SQ_IMG_SAMP_WORD1", "PERF_Z");
    d->lod_bias = field(w, "SQ_IMG_SAMP_WORD2", "LOD_BIAS");
    d->lod_bias_sec = field(w, "SQ_IMG_SAMP_WORD2", "LOD_BIAS_SEC");
    d->xy_mag_filter = field(w, "SQ_IMG_SAMP_WORD2", "XY_MAG_FILTER");
    d->xy_min_filter = field(w, "SQ_IMG_SAMP_WORD2", "XY_MIN_FILTER");
    d->z_filter = field(w, "SQ_IMG_SAMP_WORD2", "Z_FILTER");
    d->mip_filter = field(w, "SQ_IMG_SAMP_WORD2", "MIP_FILTER");
    d->mip_point_preclamp = field(w, "SQ_IMG_SAMP_WORD2", "MIP_POINT_PRECLAMP");
    d->aniso_override = field(w, "SQ_IMG_SAMP_WORD2", "ANISO_OVERRIDE");
    d->blend_zero_prt = field(w, "SQ_IMG_SAMP_WORD2", "BLEND_ZERO_PRT");
    d->border_color_ptr = field(w, "SQ_IMG_SAMP_WORD3", "BORDER_COLOR_PTR");
    d->border_color_type = field(w, "SQ_IMG_SAMP_WORD3", "BORDER_COLOR_TYPE");
}

void DecodeBuffer(const std::uint32_t w[4], BufferDescriptor* d)
{
    *d = {};
    d->address = std::uint64_t(w[0]) | std::uint64_t(field(w, "SQ_BUF_RSRC_WORD1", "BASE_ADDRESS_HI")) << 32;
    d->stride = field(w, "SQ_BUF_RSRC_WORD1", "STRIDE");
    d->cache_swizzle = field(w, "SQ_BUF_RSRC_WORD1", "CACHE_SWIZZLE");
    d->swizzle_enable = field(w, "SQ_BUF_RSRC_WORD1", "SWIZZLE_ENABLE");
    d->num_records = w[2];
    d->dst_sel[0] = field(w, "SQ_BUF_RSRC_WORD3_gfx103", "DST_SEL_X");
    d->dst_sel[1] = field(w, "SQ_BUF_RSRC_WORD3_gfx103", "DST_SEL_Y");
    d->dst_sel[2] = field(w, "SQ_BUF_RSRC_WORD3_gfx103", "DST_SEL_Z");
    d->dst_sel[3] = field(w, "SQ_BUF_RSRC_WORD3_gfx103", "DST_SEL_W");
    d->format = field(w, "SQ_BUF_RSRC_WORD3_gfx103", "FORMAT");
    d->index_stride = field(w, "SQ_BUF_RSRC_WORD3_gfx103", "INDEX_STRIDE");
    d->add_tid_enable = field(w, "SQ_BUF_RSRC_WORD3_gfx103", "ADD_TID_ENABLE");
    d->resource_level = field(w, "SQ_BUF_RSRC_WORD3_gfx103", "RESOURCE_LEVEL");
    d->oob_select = field(w, "SQ_BUF_RSRC_WORD3_gfx103", "OOB_SELECT");
    d->type = field(w, "SQ_BUF_RSRC_WORD3_gfx103", "TYPE");
}

namespace
{

bool fail(std::string* why, const char* text)
{
    if (why) *why = text;
    return false;
}

// Swizzle modes with a pipe/bank XOR (addrlib's IsXor/IsT: ADDR_SW_64KB_Z_T and above).
bool has_pipe_bank_xor(std::uint32_t mode) { return mode >= 16; }

}  // namespace

bool PlanTexture(const Config& config, const ImageDescriptor& d, TexturePlan* out, std::string* why)
{
    *out = {};
    char text[160];
    if (d.type < Img1D) return fail(why, "the descriptor is not an image (TYPE below SQ_RSRC_IMG_1D)");
    if (d.type != Img2D) {
        std::snprintf(text, sizeof(text), "T# TYPE %u is not SQ_RSRC_IMG_2D, the only dimension the translations bind",
                      d.type);
        return fail(why, text);
    }
    const ImageFormat* format = FindImageFormat(d.format);
    if (!format) {
        std::snprintf(text, sizeof(text), "T# FORMAT %u has no desktop format here", d.format);
        return fail(why, text);
    }
    if (d.compression_en) return fail(why, "T# with COMPRESSION_EN (DCC metadata is not decoded)");
    if (d.base_array) return fail(why, "T# with a BASE_ARRAY (array slices are not bound)");
    if (d.depth || d.pitch_msb)
        return fail(why, d.sw_mode == 0 ? "linear T# with a custom pitch (DEPTH/PITCH_MSB), which the detiler does not cover"
                                        : "2D T# with a DEPTH (last array slice) above 0");
    if (d.base_level > d.last_level || d.last_level > d.max_mip)
        return fail(why, "T# levels out of order (BASE_LEVEL <= LAST_LEVEL <= MAX_MIP)");
    Surface s;
    s.dimension = Dimension::Tex2D;
    s.mode = static_cast<SwizzleMode>(d.sw_mode);
    s.element_bytes = format->element_bytes;
    s.element_width = s.element_height = format->block;
    s.width = d.width;
    s.height = d.height;
    s.depth_or_array = 1;
    s.mip_levels = d.max_mip + 1;
    Layout layout;
    std::string reason;
    if (!ComputeLayout(config, s, &layout, &reason)) {
        if (why) *why = "T# surface the detiler does not cover: " + reason;
        return false;
    }
    std::uint64_t field = d.address_field;
    if (has_pipe_bank_xor(d.sw_mode) && layout.block_size_log2 > 8) {
        const std::uint64_t mask = (std::uint64_t(1) << (layout.block_size_log2 - 8)) - 1;
        s.pipe_bank_xor = static_cast<std::uint32_t>(field & mask);
        field &= ~mask;
        if (!ComputeLayout(config, s, &layout, &reason)) {
            if (why) *why = "T# surface the detiler does not cover: " + reason;
            return false;
        }
    }
    out->address = field << 8;
    out->bytes = layout.surface_size;
    out->surface = s;
    out->dxgi_format = format->dxgi;
    out->most_detailed_mip = d.base_level;
    out->mip_levels = d.last_level - d.base_level + 1;
    out->min_lod_clamp = UnsignedFixed8(d.min_lod);
    std::uint32_t mapping = 1u << 12;  // D3D12_SHADER_COMPONENT_MAPPING_ALWAYS_SET_BIT_AVOIDING_ZEROMEM_MISTAKES
    for (unsigned c = 0; c < 4; ++c) {
        std::uint32_t source;
        switch (d.dst_sel[c]) {
        case SelZero: source = 4; break;  // D3D12_SHADER_COMPONENT_MAPPING_FORCE_VALUE_0
        case SelOne: source = 5; break;   // D3D12_SHADER_COMPONENT_MAPPING_FORCE_VALUE_1
        case SelX: case SelY: case SelZ: case SelW: source = format->channel[d.dst_sel[c] - SelX]; break;
        default: return fail(why, "T# DST_SEL with a reserved selector (2 or 3)");
        }
        mapping |= source << (3 * c);
    }
    out->component_mapping = mapping;
    return true;
}

bool PlanSampler(const SamplerDescriptor& d, DesktopSampler* out, std::string* why)
{
    *out = {};
    // SQ_TEX_CLAMP -> D3D12_TEXTURE_ADDRESS_MODE: WRAP 1, MIRROR 2, CLAMP 3, BORDER 4, MIRROR_ONCE 5.
    const auto address = [](std::uint32_t clamp) -> std::uint32_t {
        switch (clamp) {
        case 0: return 1;  // SQ_TEX_WRAP
        case 1: return 2;  // SQ_TEX_MIRROR
        case 2: return 3;  // SQ_TEX_CLAMP_LAST_TEXEL
        case 3: return 5;  // SQ_TEX_MIRROR_ONCE_LAST_TEXEL
        case 6: return 4;  // SQ_TEX_CLAMP_BORDER
        default: return 0;  // half-border clamps and MIRROR_ONCE_BORDER: no desktop mode
        }
    };
    out->address_u = address(d.clamp_x);
    out->address_v = address(d.clamp_y);
    out->address_w = address(d.clamp_z);
    if (!out->address_u || !out->address_v || !out->address_w)
        return fail(why, "S# address mode CLAMP_HALF_BORDER, MIRROR_ONCE_HALF_BORDER or MIRROR_ONCE_BORDER has no "
                         "desktop equivalent");
    if (d.force_unnormalized) return fail(why, "S# FORCE_UNNORMALIZED has no desktop equivalent");
    if (d.force_degamma || d.skip_degamma) return fail(why, "S# FORCE_DEGAMMA/SKIP_DEGAMMA has no desktop equivalent");
    if (d.mc_coord_trunc) return fail(why, "S# MC_COORD_TRUNC has no desktop equivalent");
    if (d.lod_bias_sec) return fail(why, "S# LOD_BIAS_SEC has no desktop equivalent");
    if (d.border_color_type == 3) return fail(why, "S# border colour from the border-colour table (REGISTER)");
    if (d.filter_mode > 2) return fail(why, "S# FILTER_MODE 3 is reserved");
    if (d.xy_mag_filter > 3 || d.xy_min_filter > 3 || d.mip_filter > 2) return fail(why, "S# reserved filter value");
    const std::uint32_t reduction = d.filter_mode == 0 ? 0 : d.filter_mode == 1 ? 2 : 3;  // standard, minimum, maximum
    const bool aniso = (d.xy_min_filter >= 2 || d.xy_mag_filter >= 2) && d.max_aniso_ratio > 0;
    if (aniso) {
        if (d.max_aniso_ratio > 4) return fail(why, "S# MAX_ANISO_RATIO above 16x");
        if (d.mip_filter != 2)
            return fail(why, "S# anisotropic filtering without a linear mip filter (D3D12_FILTER_ANISOTROPIC is linear "
                             "between levels)");
        out->filter = 0x55u | reduction << 7;  // D3D12_ENCODE_ANISOTROPIC_FILTER
        out->max_anisotropy = 1u << d.max_aniso_ratio;
    } else {
        const std::uint32_t min = d.xy_min_filter & 1, mag = d.xy_mag_filter & 1, mip = d.mip_filter == 2 ? 1 : 0;
        out->filter = min << 4 | mag << 2 | mip | reduction << 7;  // D3D12_ENCODE_BASIC_FILTER
        out->max_anisotropy = 1;
    }
    out->comparison_func = d.depth_compare_func + 1;  // SQ_TEX_DEPTH_COMPARE_NEVER (0) -> D3D12_COMPARISON_FUNC_NEVER
    out->mip_lod_bias = SignedFixed8(d.lod_bias, 14);
    if (out->mip_lod_bias < -16.0f || out->mip_lod_bias > 15.99f)
        return fail(why, "S# LOD_BIAS outside D3D12's [-16, 15.99]");
    out->min_lod = UnsignedFixed8(d.min_lod);
    out->max_lod = UnsignedFixed8(d.max_lod);
    // SQ_TEX_MIP_FILTER_NONE samples one level: point between levels with the LOD clamped to MIN_LOD.
    if (d.mip_filter == 0) out->max_lod = out->min_lod;
    static const float borders[3][4] = {{0, 0, 0, 0}, {0, 0, 0, 1}, {1, 1, 1, 1}};
    for (unsigned c = 0; c < 4; ++c) out->border_color[c] = borders[d.border_color_type][c];
    return true;
}

bool PlanConstantBuffer(const BufferDescriptor& d, std::uint64_t* address, std::uint64_t* bytes, std::string* why)
{
    if (d.type != 0) return fail(why, "the descriptor is not a buffer (V# TYPE is not SQ_RSRC_BUF)");
    if (d.swizzle_enable) return fail(why, "a swizzled V# (SWIZZLE_ENABLE) as a constant buffer");
    if (d.add_tid_enable) return fail(why, "a V# with ADD_TID_ENABLE as a constant buffer");
    *address = d.address;
    *bytes = d.stride ? std::uint64_t(d.num_records) * d.stride : d.num_records;
    return true;
}

}  // namespace x2w::gfx10
